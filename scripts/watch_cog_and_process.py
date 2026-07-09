#!/usr/bin/env python3
"""
watch_cog_and_process.py — check Cross of Grace for a newly-uploaded sermon and,
if one is found, run the WHOLE pipeline end to end and publish it live:

    transcribe (if needed) → decompose → 6→5 artifacts → render → deploy

Idempotent and safe to run on a schedule: it only acts on Cross of Grace sermons
that are (a) created in the last few days and (b) not yet decomposed. Anything
already processed is skipped, so running it at 4/6/8pm just no-ops until the new
sermon actually lands.

Env comes from the repo .env (Anthropic / Voyage / Supabase / AssemblyAI / R2).
Deploy is handled by scripts/deploy_sermon_pages.py, which now builds + runs
`wrangler deploy` itself, so a processed sermon goes all the way to live.
"""
import os
import sys
import subprocess
from datetime import datetime, timedelta

REPO = "/Users/dad/shepherds-guild/pipeline copy 2"
os.chdir(REPO)
sys.path.insert(0, REPO)
sys.path.insert(0, REPO + "/scripts")
from dotenv import load_dotenv  # noqa: E402
load_dotenv(REPO + "/.env")

from weekly_ingest import supabase, submit_decomposition_batch, finish_batch, Customer  # noqa: E402
from selfserve_ingest import transcribe, generate_artifacts  # noqa: E402

COG_CHURCH_ID = "f1fc9898-fafd-4289-b6af-ce99dfde23d6"
RECENT_DAYS = 3  # only consider uploads from the last few days (skip old stragglers)


def log(msg: str) -> None:
    print(f"[{datetime.now().isoformat(timespec='seconds')}] {msg}", flush=True)


def main() -> int:
    sb = supabase()
    pids = [r["id"] for r in (sb.table("preachers").select("id")
            .eq("church_id", COG_CHURCH_ID).execute().data or [])]
    if not pids:
        log("No Cross of Grace preachers found."); return 0

    cutoff = (datetime.utcnow() - timedelta(days=RECENT_DAYS)).isoformat() + "Z"
    rows = (sb.table("sermons")
            .select("id,title,date,primary_text,preacher_id,raw_transcript,hosted_audio_url,audio_url")
            .in_("preacher_id", pids)
            .is_("decomposed_at", "null")
            .gte("created_at", cutoff)
            .execute().data or [])
    rows = [r for r in rows if r.get("hosted_audio_url") or r.get("audio_url")]

    if not rows:
        log("No new Cross of Grace sermon to process. (nothing to do)")
        return 0

    log(f"Found {len(rows)} new sermon(s) to process.")
    for r in rows:
        sid = r["id"]
        pre = (sb.table("preachers").select("name").eq("id", r["preacher_id"])
               .single().execute().data or {}).get("name") or "Unknown"
        try:
            log(f"Processing {sid} — {r['title']} — {pre}")

            if not r.get("raw_transcript"):
                audio = r.get("hosted_audio_url") or r.get("audio_url")
                log("  transcribing via AssemblyAI …")
                text = transcribe(audio)
                sb.table("sermons").update({"raw_transcript": text}).eq("id", sid).execute()
                r["raw_transcript"] = text
                log(f"  transcript chars={len(text)}")

            cust = Customer(
                church_id=COG_CHURCH_ID, church_name="Cross of Grace Church",
                church_slug="cross-of-grace-church", preacher_id=r["preacher_id"],
                preacher_name=pre, ingest_source_type="nucleus",
                podcast_feed_url=None, audio_base_url=None, deploy_target=None,
            )
            bid = submit_decomposition_batch(cust, [r])
            if not bid:
                log("  decomposition submit FAILED; skipping."); continue
            log(f"  batch {bid}; waiting for decomposition …")
            n_s, n_a, n_p = finish_batch(bid, pre)
            log(f"  finish_batch: sermons={n_s} artifacts={n_a} pages={n_p}")

            missing = generate_artifacts(sid)
            log(f"  artifacts missing after backfill: {missing or 'none'}")

            d = subprocess.run([sys.executable, "scripts/deploy_sermon_pages.py",
                                "--sermon-ids", sid], cwd=REPO, capture_output=True, text=True)
            log("  deploy+publish: " + ("ok" if d.returncode == 0
                                        else "FAILED " + d.stderr[-300:]))
        except Exception as e:
            log(f"  ERROR processing {sid}: {e}")
    log("Done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
