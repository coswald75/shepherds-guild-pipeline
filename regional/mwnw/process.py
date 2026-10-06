"""One church, one week: find -> audio/transcript -> (cut) -> decompose -> ingest -> artifacts -> PDF.

Idempotent: every step records its result in state.json and is skipped on the next run.
A church is processed ONCE per week. Before decomposing we also check the DB for a sermon on that
date from any of the church's preachers (so a manual run or the Providence pipeline never gets
double-processed). New rows are private: sermons.is_public=False, unlisted=True.

dry=True does everything that costs nothing or is cached, and stops before any paid model call or
DB write (no AssemblyAI, no decomposition, no ingest)."""
from __future__ import annotations
import re
import json, re, time, uuid
from datetime import datetime, timezone
from pathlib import Path
from . import config, sources, media
from .util import REPO, State, log, week_dir, retry, alert, spend_usd, church_lock, run_label, CT

ART_TYPES = ["small_group_questions", "daily_readings", "family_card", "couples_guide", "memory_verse"]
RF = {"exposition", "theological_claim", "illustration", "application", "introduction", "conclusion", "transition", "pastoral_aside", "prayer"}


def slugify(s): return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", (s or "").lower())).strip("-")


def normalize(dec: dict) -> list[str]:
    """Same fixes as the Sep 27 regional run: loci with parentheticals; off-list rhetorical_function."""
    fixes = []
    for u in dec.get("units", []):
        if u.get("doctrinal_loci"):
            new = [re.sub(r"\s*\(.*\)\s*$", "", l).strip() for l in u["doctrinal_loci"]]
            if new != u["doctrinal_loci"]: fixes.append("loci"); u["doctrinal_loci"] = new
        f = u.get("rhetorical_function")
        if f not in RF:
            g = (f or "").lower()
            m = ("illustration" if any(x in g for x in ("illustr", "quot", "story", "anecdote")) else "application" if "appl" in g else
                 "theological_claim" if any(x in g for x in ("claim", "doctr", "theolog")) else "introduction" if "intro" in g else
                 "conclusion" if "concl" in g else "prayer" if "pray" in g else "transition" if "trans" in g else "exposition")
            fixes.append(f"rf:{f}->{m}"); u["rhetorical_function"] = m
    return fixes


def sb():
    from pipeline import get_supabase
    return get_supabase()


def existing_sermon(church: dict, week: str) -> dict | None:
    pids = [p["id"] for p in sb().table("preachers").select("id").eq("church_id", church["church_id"]).execute().data]
    if not pids: return None
    rows = sb().table("sermons").select("id,title,slug,preacher_id").in_("preacher_id", pids).eq("date", week).execute().data
    return rows[0] if rows else None


def preacher_for(church: dict, name: str, dry: bool) -> str | None:
    rows = sb().table("preachers").select("id,name").eq("church_id", church["church_id"]).execute().data
    for r in rows:
        if r["name"].strip().lower() == (name or "").strip().lower(): return r["id"]
    if dry: return None
    pr = sb().table("preachers").insert({"name": name, "slug": f"{slugify(name)}-sgmw-{uuid.uuid4().hex[:6]}", "church_id": church["church_id"],
                                         "is_public": False, "is_canonical": False}).execute().data[0]
    log.info(f"{church['key']}: created preacher {name} ({pr['id']})"); return pr["id"]


@retry(tries=3, wait=30, what="decompose")
def _decompose(tx, preacher, title, text):
    from pipeline import decompose_sermon
    return decompose_sermon(tx, preacher, known_title=title, known_primary_text=text)


def _gen_artifacts(sid: str, key: str) -> list[str]:
    import generate_artifacts as ga
    client = sb()
    have = {r["artifact_type"] for r in client.table("sermon_artifacts").select("artifact_type").eq("sermon_id", sid).execute().data}
    for t in ART_TYPES:
        if t in have: continue
        for att in range(3):
            try: ga.generate_one(sid, t, model=ga.DEFAULT_MODEL, write=True); break
            except Exception as e:  # noqa: BLE001
                log.warning(f"{key} artifact {t} attempt {att + 1}: {str(e)[:200]}"); time.sleep(10 * (att + 1))
    return sorted({r["artifact_type"] for r in client.table("sermon_artifacts").select("artifact_type").eq("sermon_id", sid).execute().data})


def run_church(st: State, church: dict, run: str, *, dry: bool = False, max_spend: float = 4.0) -> dict:
    week, key = st.week, church["key"]
    c = st.data; d = st.dir
    c.setdefault("log", [])
    def note(msg): c["log"].append(f"{datetime.now(timezone.utc):%Y-%m-%dT%H:%MZ} {run}: {msg}"); st.save()
    if c.get("status") == "READY":
        return c

    # 1. find (free: RSS / page fetches / yt-dlp metadata). Throttled so a 15-min poller
    #    doesn't hit YouTube every tick.
    if not c.get("source"):
        import os
        every = int(os.environ.get("MWNW_FIND_EVERY_MIN", "25"))
        last = c.get("last_find")
        if last and not dry and (datetime.now(CT) - datetime.fromisoformat(last)).total_seconds() < every * 60 - 30:
            return c
        c["last_find"] = datetime.now(CT).isoformat()
        cand, notes = sources.find(church, week, run)
        c["find_notes"] = notes; note("; ".join(notes))
        if not cand:
            ex = existing_sermon(church, week)   # e.g. processed by hand earlier; reuse, never redo
            if not ex:
                c["status"] = "MISSING"; c["reason"] = "; ".join(notes) or "no source"; st.save(); return c
            cand = dict(kind="existing", sermon_id=ex["id"], title=ex["title"])
        c["source"] = cand; st.save()
    src = c["source"]

    # Providence: the iMac pipeline already did it. Never re-process.
    if src["kind"] == "pipeline":
        c.update(sermon_id=src["sermon_id"], title=src["title"], preacher=src["preacher"], slug=src["slug"])
        _finish(st, church, c, dry, note); return c

    # Already in the DB for this date (manual run, earlier attempt)? Reuse it.
    if not c.get("sermon_id"):
        ex = existing_sermon(church, week)
        if ex:
            c.update(sermon_id=ex["id"], title=ex["title"], slug=ex["slug"], reused_existing=True); note(f"reusing existing sermon {ex['id']}")
    if c.get("sermon_id"):
        _finish(st, church, c, dry, note); return c

    if c.get("spend_usd", 0) + spend_usd() > max_spend:
        c["status"] = "MISSING"; c["reason"] = f"spend cap ${max_spend} reached this run; will retry next run"; st.save(); return c

    # 2. audio + transcript
    txj = d / "transcript.json"
    if not txj.exists() and dry:
        c["status"] = "MISSING"; c["reason"] = f"dry run: found {src['kind']} source, stopping before transcription"; st.save(); return c
    try:
        if src["kind"] == "youtube":
            audio = media.download_youtube(src["yt_id"], d / "livestream")
            c["audio_file"] = str(audio); st.save()
            T = media.transcribe(str(audio), txj)
        else:
            T = media.transcribe(src["audio_url"], txj)
    except Exception as e:  # noqa: BLE001
        c["status"] = "MISSING"; c["reason"] = f"audio/transcription failed: {str(e)[:300]}"; note(c["reason"])
        c.pop("source", None)  # re-detect next time (stream may have been re-processed / URL rotated)
        st.save(); return c
    S = T["sentences"]; c["audio_sec"] = T["duration"]

    # 3. livestream: find the sermon and cut it out
    if src["kind"] == "youtube" and not c.get("cut"):
        try:
            b = media.find_bounds(S)
        except Exception as e:  # noqa: BLE001
            c["status"] = "MISSING"; c["reason"] = f"could not find sermon in livestream: {str(e)[:200]}"; note(c["reason"]); st.save(); return c
        clip = d / f"{slugify(church['church'] + ' ' + church['city'])}-{week}.mp3"
        try: media.cut_mp3(Path(c["audio_file"]), b["start_ms"], b["end_ms"], clip, f"{church['church']} {week} sermon")
        except Exception as e: note(f"clip cut failed (transcript still usable): {e}"); clip = None  # noqa: E701
        c["cut"] = {k: v for k, v in b.items() if k != "usage"} | {"clip": str(clip) if clip else None,
                    "start": media.mmss(b["start_ms"]), "end": media.mmss(b["end_ms"]), "usage": b["usage"]}
        st.save()
    if src["kind"] == "youtube":
        S = S[c["cut"]["first_idx"]:c["cut"]["last_idx"] + 1]
    tx = " ".join(s["t"] for s in S).replace("\x00", "").strip() + "\n"
    c["sermon_minutes"] = round((S[-1]["e"] - S[0]["s"]) / 60000, 1)
    c["first_sentence"] = S[0]["t"]; c["last_sentence"] = S[-1]["t"]

    # 4. who / what
    if not c.get("meta"):
        hints = json.dumps({k: src.get(k) for k in ("title", "preacher", "description", "page_url")}, ensure_ascii=False)
        try: m = media.identify_preacher(S, hints, c.setdefault("usage", []))
        except Exception as e: m = {"preacher": None, "basis": f"identify failed: {e}"}  # noqa: E701
        cut = c.get("cut") or {}
        mp = m.get("preacher")
        # Strip a leading honorific so "Pastor Jeff" collapses to "Jeff" before matching.
        if mp:
            mp = re.sub(r"^(?:Pastor|Rev\.?|Reverend)\s+", "", mp, flags=re.I).strip() or mp
        if mp and len(mp.split()) == 1:   # bare first name → only keep if it matches the lead pastor's first name
            mp = church["default_preacher"] if (church["default_preacher"] or "").split()[0].lower() == mp.lower() else None
        m["preacher"] = mp
        preacher = mp or cut.get("preacher") or src.get("preacher") or church["default_preacher"]
        basis = "transcript" if m.get("preacher") else "livestream" if cut.get("preacher") else "feed" if src.get("preacher") else "default (VERIFY)"
        title = src.get("title") if src["kind"] != "youtube" else (cut.get("title") or m.get("title"))
        c["meta"] = dict(preacher=preacher, preacher_basis=basis, guest=bool(m.get("guest")), title=_clean_title(title),
                         text=m.get("text") or cut.get("text"), model=m)
        if not preacher:
            c["status"] = "MISSING"; c["reason"] = "could not tell who preached; set it in state.json meta.preacher and re-run"; st.save(); return c
        st.save()
    meta = c["meta"]

    # 5. decompose + ingest (paid; the only DB writes)
    decj = d / "decomposed.json"
    try:
        if decj.exists(): dec = json.loads(decj.read_text())
        else:
            dec = _decompose(tx, meta["preacher"], meta.get("title"), meta.get("text"))
            decj.write_text(json.dumps(dec, ensure_ascii=False))
        if meta.get("title"): dec["title"] = meta["title"]
        dec["date"] = week
        if not dec.get("series_name"): dec["series_position"] = None
        c["normalized"] = normalize(dec)
        pid = preacher_for(church, meta["preacher"], dry=False)
        # Last-moment dedup: if anything (e.g. the iMac pipeline) created this church's sermon for
        # this date, or a row already owns this feed item's guid, do NOT ingest a second copy.
        ex = existing_sermon(church, week)
        if not ex and src.get("guid"):
            g = sb().table("sermons").select("id,title,slug,preacher_id").eq("podcast_guid", src["guid"]).limit(1).execute().data
            ex = g[0] if g else None
        if ex:
            c.update(sermon_id=ex["id"], title=ex["title"], slug=ex["slug"], reused_existing=True)
            note(f"another job created {ex['id']} meanwhile; reusing it, not ingesting a duplicate")
            _finish(st, church, c, dry, note); return c
        from pipeline import embed_units, ingest_sermon
        emb = embed_units(dec.get("units", []))
        sid = ingest_sermon(dec, pid, emb, raw_transcript=tx)
        title = dec.get("title") or meta.get("title") or "Sermon"
        slug = f"{slugify(title)}-{week}"
        audio = src.get("audio_url")
        patch = {"slug": slug, "title": title, "date": week, "is_public": False, "unlisted": True,
                 "audio_duration_seconds": int(c["sermon_minutes"] * 60), "audio_url": audio, "hosted_audio_url": audio,
                 "decomposed_at": datetime.now(timezone.utc).isoformat()}
        if church.get("public"):
            # Providence: make the row look exactly like the iMac pipeline's own (normal listing,
            # host_sync, feed guid). hosted_audio_url left empty so the iMac's RSS sync mirrors it to R2.
            patch.update(unlisted=False, upload_source="host_sync", hosted_audio_url=None)
        if src.get("guid"): patch["podcast_guid"] = src["guid"]
        sb().table("sermons").update(patch).eq("id", sid).execute()
        (REPO / "output" / f"{sid}_decomposed.json").write_text(json.dumps(dec, indent=2, ensure_ascii=False))
        c.update(sermon_id=sid, slug=slug, title=title, preacher=meta["preacher"], preacher_id=pid,
                 decomp_cost=dec.get("_pipeline", {}).get("processing_cost_usd"), units=len(dec.get("units", [])))
        note(f"ingested {sid}")
    except Exception as e:  # noqa: BLE001
        c["status"] = "MISSING"; c["reason"] = f"decompose/ingest failed: {str(e)[:300]}"; note(c["reason"]); st.save(); return c
    _finish(st, church, c, dry, note)
    return c


def _clean_title(t):
    if not t: return t
    t = re.sub(r"\s*\|\s*(Sunday|Livestream|Live Stream|Worship).*$", "", t, flags=re.I)
    return t.strip(" -|")


def _finish(st, church, c, dry, note):
    """Artifacts + PDF. Sets READY when the sermon, five resources and the PDF all exist."""
    sid = c["sermon_id"]
    row = sb().table("sermons").select("title,slug,date,preacher_id,preachers(name)").eq("id", sid).single().execute().data
    c.update(title=row["title"], slug=row["slug"], preacher=(row.get("preachers") or {}).get("name"))
    have = sorted({r["artifact_type"] for r in sb().table("sermon_artifacts").select("artifact_type").eq("sermon_id", sid).execute().data})
    imac_owns = church["key"] == "prov" and (c.get("source") or {}).get("kind") == "pipeline"
    if len(set(have) & set(ART_TYPES)) < 5 and not dry and not imac_owns:
        have = _gen_artifacts(sid, church["key"])
    c["artifacts"] = have
    if len(set(have) & set(ART_TYPES)) < 5:
        c["status"] = "MISSING"; c["reason"] = f"only {len(have)}/5 congregation resources" + (" (Providence: wait for the iMac catchup run)" if imac_owns else "")
        st.save(); return
    from . import report_pdf
    try:
        c["pdf"] = str(report_pdf.build(st.week, church, sid, dry=dry))
    except Exception as e:  # noqa: BLE001
        c["status"] = "MISSING"; c["reason"] = f"PDF failed: {str(e)[:300]}"; note(c["reason"]); st.save(); return
    c["status"] = "READY"; c["reason"] = ""; note("READY"); st.save()


HARD = ("failed", "crash", "could not", "only ")   # reasons worth an alert (vs. "not posted yet")


def run_one(week: str, key: str, run: str | None = None, *, dry=False, max_spend=4.0) -> dict:
    """Process ONE church in this process. Safe to call repeatedly (poller does every ~15 min)."""
    church = config.BY_KEY[key]; run = run or run_label(week=week)
    with church_lock(week, key) as got:
        if not got:
            log.info(f"{key}: another process is already working on it"); return State(week, key).data
        st = State(week, key)
        if st.data.get("status") == "READY": return st.data
        st.data["attempts"] = st.data.get("attempts", 0) + 1; st.data["last_attempt"] = datetime.now(CT).isoformat()
        try:
            c = run_church(st, church, run, dry=dry, max_spend=max_spend)
        except Exception as e:  # noqa: BLE001
            log.exception(f"{key} crashed"); c = st.data; c["status"] = "MISSING"; c["reason"] = f"crash: {str(e)[:300]}"
        c["spend_usd"] = round(c.get("spend_usd", 0) + spend_usd(), 3)
        st.save()
        log.info(f"{key:6} {c.get('status')}  {c.get('title') or ''}  {c.get('reason') or ''}")
        r = c.get("reason") or ""
        if c.get("status") != "READY" and any(h in r for h in HARD) and c.get("alerted") != r and not dry:
            alert(f"{church['church']} ({church['city']}) not ready for {week}", f"{r}\n\nstate: {st.path}")
            c["alerted"] = r; st.save()
        return c
