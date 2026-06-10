#!/usr/bin/env python3
"""Generate seeker-grade topical landing pages from a preacher's corpus.

For each topic (pilot: marriage, suffering, generosity) this script:

  1. RETRIEVES — embeds 4-5 phrasings of the topic (Voyage 3.5) and runs
     each through the match_units_for_preacher RPC, unioning hits. Multi-
     phrasing matters: the 2026-06-10 probe showed raw seeker phrasing
     ("help with my marriage") scores 0.59-0.68 — under the 0.675 pastor-
     recall bar — while the right sermons sit just beneath. Clean topic
     nouns + several angles recover them.
  2. SYNTHESIZES — one Sonnet call per topic, system-prompted with
     chris-voice-style-guide.md and hard rules: synthesize ONLY from the
     provided excerpts, cite by [n], no invented quotes or stats. Output
     is structured JSON; the citation table is rendered by US from our
     own source list, so the model cannot invent links.
  3. RENDERS — a static page at <church-dir>/topics/<slug>/index.html
     in the site's visual language, with a sources section linking each
     cited sermon page. Approximate minute marks are computed from word-
     count position × sermons.audio_duration_seconds where duration
     exists (no per-unit timestamps are stored), labeled "≈".

Cost: ~3 Sonnet calls per run (one per topic), pennies. Re-running
regenerates pages from current corpus state.

Usage:
    python scripts/generate_topic_pages.py \
        --church-dir /Users/dad/shepherds-guild/sermon-steward/ProvidenceLenexa \
        [--topics marriage,suffering,generosity] [--dry-run]
"""
from __future__ import annotations

import argparse
import html as htmlmod
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(override=True)

import anthropic  # noqa: E402
import voyageai  # noqa: E402
from supabase import create_client  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
from pipeline_batch import _extract_json_blob  # noqa: E402

VOYAGE_MODEL = "voyage-3.5"
SYNTH_MODEL = "claude-sonnet-4-6"
SCORE_FLOOR = 0.55
MAX_UNITS = 24
MIN_CONTENT_LEN = 200
WORDS_PER_MINUTE = 150  # fallback pace when proportioning against duration

PREACHER_CHRIS = "9c6f8d69-de55-45db-ac60-0fe6d0cfff59"

# ─── Pilot taxonomy ──────────────────────────────────────────────────────────
# Each topic: display name, page deck (subtitle), retrieval phrasings.
# Phrasings are tuned for embedding quality, not display.
TOPICS: dict[str, dict] = {
    "marriage": {
        "title": "Marriage",
        "deck": "What Providence teaches about marriage — drawn from the sermons themselves.",
        "phrasings": [
            "marriage",
            "husband and wife",
            "conflict and forgiveness in marriage",
            "what God designed marriage to be",
            "love, headship, and submission in marriage",
        ],
    },
    "suffering": {
        "title": "Suffering",
        "deck": "Why suffering comes, what God is doing in it, and how to endure — from the pulpit at Providence.",
        "phrasings": [
            "suffering",
            "why does God allow suffering",
            "enduring trials and affliction",
            "grief, pain, and loss",
            "hope in the midst of suffering",
        ],
    },
    "generosity": {
        "title": "Generosity",
        "deck": "Money, possessions, and the open hand — what Providence teaches about generosity.",
        "phrasings": [
            "generosity",
            "giving money to the church and the poor",
            "stewardship of money and possessions",
            "treasure in heaven versus treasure on earth",
            "greed, contentment, and the love of money",
        ],
    },
}


def retrieve_units(sb, vo, preacher_id: str, phrasings: list[str]) -> list[dict]:
    """Union of hits across phrasings; max score wins per unit."""
    best: dict[str, dict] = {}
    for phrase in phrasings:
        emb = vo.embed([phrase], model=VOYAGE_MODEL, input_type="query").embeddings[0]
        # All 8 params named explicitly — the DB has 7- and 8-param
        # overloads and PostgREST can't pick between them otherwise.
        # Retry on 57014: the HNSW iterative scan sporadically exceeds the
        # statement timeout on a cold cache (seen during artifact
        # generation too); the retry almost always lands on warm cache.
        res = None
        for attempt in range(3):
            try:
                res = sb.rpc(
                    "match_units_for_preacher",
                    {
                        "p_preacher_id": preacher_id,
                        "p_query_embedding": emb,
                        "p_query_text": phrase,
                        "p_match_count": 20,
                        "p_rhetorical_functions": None,
                        "p_primary_text": None,
                        "p_keyword_weight": 0.3,
                        "p_doctrinal_loci": None,
                    },
                ).execute()
                break
            except Exception as e:
                # postgrest.APIError stringifies as the message only —
                # match on message text AND the .code attribute.
                blob = f"{e} {getattr(e, 'code', '')}"
                if ("statement timeout" in blob or "57014" in blob) and attempt < 2:
                    import time
                    time.sleep(3 * (attempt + 1))
                    continue
                raise
        for h in res.data or []:
            score = h.get("final_score") or 0
            if score < SCORE_FLOOR:
                continue
            if len((h.get("content") or "").strip()) < MIN_CONTENT_LEN:
                continue
            uid = h["unit_id"]
            if uid not in best or score > best[uid]["final_score"]:
                h["final_score"] = score
                best[uid] = h
    units = sorted(best.values(), key=lambda h: -h["final_score"])[:MAX_UNITS]
    return units


def approx_minute(sb, sermon_id: str, unit_index: int) -> int | None:
    """Word-count-proportional position against audio_duration_seconds.

    Units carry no timestamps; this estimates where in the audio a unit
    lands by its share of the sermon's words. Returns whole minutes, or
    None when the sermon has no stored duration.
    """
    s = (
        sb.table("sermons")
        .select("audio_duration_seconds")
        .eq("id", sermon_id)
        .single()
        .execute()
        .data
    )
    dur = s.get("audio_duration_seconds") if s else None
    if not dur:
        return None
    rows = (
        sb.table("units")
        .select("unit_index, content")
        .eq("sermon_id", sermon_id)
        .order("unit_index")
        .execute()
        .data
        or []
    )
    total = sum(len((r["content"] or "").split()) for r in rows)
    if not total:
        return None
    before = sum(
        len((r["content"] or "").split()) for r in rows if r["unit_index"] < unit_index
    )
    return max(0, round((before / total) * (dur / 60)))


def build_sources(sb, units: list[dict], church_dir: Path) -> list[dict]:
    """Group units by sermon → numbered source list. Only sermons whose
    deployed page exists on disk are citable (no dead links)."""
    by_sermon: dict[str, dict] = {}
    for u in units:
        sid = u["sermon_id"]
        by_sermon.setdefault(sid, {"units": []})["units"].append(u)

    ids = list(by_sermon.keys())
    rows = (
        sb.table("sermons")
        .select(
            "id, title, date, slug, primary_text, audio_duration_seconds, "
            "audio_url, hosted_audio_url"
        )
        .in_("id", ids)
        .execute()
        .data
        or []
    )
    sources = []
    for r in rows:
        page = church_dir / "sermons" / f"{r['slug']}.html"
        if not r.get("slug") or not page.exists():
            continue
        # Display-quality gate: a handful of sermons carry filename-ish
        # titles ("nov-19", "denominationalplankpulling") from early
        # ingests. Real material, but citing them on a public seeker page
        # reads as broken. Skip until their titles get cleaned up.
        t = r.get("title") or ""
        if " " not in t.strip():
            continue
        us = sorted(by_sermon[r["id"]]["units"], key=lambda u: -u["final_score"])
        top = us[0]
        minute = approx_minute(sb, r["id"], top["unit_index"])
        has_audio = bool(r.get("audio_url") or r.get("hosted_audio_url"))
        sources.append(
            {
                "sermon_id": r["id"],
                "title": r["title"],
                "date": r.get("date"),
                "scripture": r.get("primary_text"),
                "href": f"/{church_dir.name}/sermons/{r['slug']}.html",
                "minute": minute,
                "has_audio": has_audio,
                "units": us,
                "best_score": top["final_score"],
            }
        )
    # Ordering gate (Chris, 2026-06-10): all of the corpus is fair game
    # for the synthesis, but the source list leads with sermons the
    # reader can actually LISTEN to at the cited moment — audio present
    # AND a minute mark computable. Everything else lists after, still
    # cited, just not at the top.
    def tier(s: dict) -> int:
        return 0 if (s["has_audio"] and s["minute"] is not None) else 1

    sources.sort(key=lambda s: (tier(s), -s["best_score"]))
    for n, s in enumerate(sources, 1):
        s["n"] = n
    return sources


SYNTH_SYSTEM_RULES = """You are synthesizing a topical teaching page from a pastor's own sermon excerpts.

HARD RULES — violating any of these makes the output unusable:
1. Synthesize ONLY from the numbered source excerpts provided. If the sources don't address an aspect of the topic, leave it out. Never fill gaps from general theological knowledge.
2. Every paragraph must carry at least one citation marker like [1] or [2][5], referring to the source numbers provided. Place markers at the end of the sentence they support.
3. Quote VERBATIM or not at all. Short verbatim quotes (a phrase to a sentence) from the excerpts are encouraged; never paraphrase inside quotation marks.
4. No invented statistics, anecdotes, or scripture applications that aren't in the sources.
5. Do not mention "excerpts", "sources", "units", or this process in the prose. Write as a finished teaching page.

OUTPUT: a single JSON object, no markdown fence, shaped exactly:
{
  "page_title": str,          // e.g. "What Providence Teaches About Marriage"
  "deck": str,                // 1-2 sentence subtitle
  "sections": [               // 4-6 sections, each a key concept
    { "heading": str, "paragraphs": [str, ...] }   // 1-3 paragraphs each, citation markers inline
  ],
  "closing": str              // 2-4 sentences: where to start, pastorally direct
}

Below is the style guide for the preacher's voice. Honor it.

"""


def synthesize(client, topic_cfg: dict, sources: list[dict], voice_guide: str) -> dict:
    src_lines = []
    for s in sources:
        date = s["date"] or "undated"
        scripture = f" ({s['scripture']})" if s["scripture"] else ""
        src_lines.append(f"SOURCE [{s['n']}] — \"{s['title']}\"{scripture}, {date}")
        for u in s["units"][:3]:
            content = (u["content"] or "").strip()
            if len(content) > 1600:
                content = content[:1600] + " …"
            src_lines.append(f"  excerpt ({u['rhetorical_function']}): {content}")
        src_lines.append("")
    user = (
        f"TOPIC: {topic_cfg['title']}\n\n"
        f"Write the topical teaching page for this topic from these sources.\n\n"
        + "\n".join(src_lines)
    )
    resp = client.messages.create(
        model=SYNTH_MODEL,
        max_tokens=4000,
        system=SYNTH_SYSTEM_RULES + voice_guide,
        messages=[{"role": "user", "content": user}],
    )
    raw = resp.content[0].text
    return json.loads(_extract_json_blob(raw))


PAGE_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title} — {church_name} · Sermon Steward</title>
<meta name="description" content="{deck_attr}">
<link rel="canonical" href="https://sermonsteward.com/{church_slug}/topics/{topic_slug}/">
<meta property="og:type" content="article">
<meta property="og:title" content="{title} — {church_name}">
<meta property="og:description" content="{deck_attr}">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet">
<style>
  :root {{
    --bg: #fbf8f1; --bg-card: #ffffff; --ink: #1a1a1a; --ink-soft: #4a4a4a;
    --ink-faint: #828282; --rule: #e6e1d3; --accent: #c4452f;
    --accent-deep: #9a3624; --highlight: #fef0c8;
    --sans: 'Inter', system-ui, -apple-system, sans-serif;
  }}
  * {{ box-sizing: border-box; }}
  html, body {{
    margin: 0; padding: 0; background: var(--bg); color: var(--ink);
    font-family: var(--sans); font-size: 17px; line-height: 1.65;
    -webkit-font-smoothing: antialiased;
  }}
  a {{ color: var(--accent); text-decoration: none; }}
  a:hover {{ color: var(--accent-deep); }}
  .site-header {{ padding: 24px 32px; border-bottom: 1px solid var(--rule); }}
  .wordmark {{ font-weight: 800; font-size: 22px; letter-spacing: -0.02em; color: var(--ink); }}
  .wordmark .dot {{ color: var(--accent); }}
  main {{ max-width: 720px; margin: 0 auto; padding: 48px 32px 96px; }}
  .breadcrumb {{ font-size: 13px; color: var(--ink-faint); margin-bottom: 20px; }}
  .breadcrumb a {{ color: var(--ink-soft); text-decoration: underline; text-underline-offset: 3px; }}
  h1 {{
    font-size: clamp(2.2rem, 5vw, 3rem); font-weight: 800;
    letter-spacing: -0.03em; line-height: 1.05; margin: 0 0 14px;
  }}
  .deck {{ font-size: 19px; color: var(--ink-soft); margin: 0 0 40px; }}
  h2 {{
    font-size: 22px; font-weight: 700; letter-spacing: -0.01em;
    margin: 44px 0 12px;
  }}
  p {{ margin: 0 0 16px; }}
  sup.cite {{ font-size: 11px; }}
  sup.cite a {{ color: var(--accent); font-weight: 600; }}
  .closing {{
    margin-top: 40px; padding: 20px 24px; background: var(--bg-card);
    border: 1px solid var(--rule); border-left: 3px solid var(--accent);
    border-radius: 8px; font-size: 16px;
  }}
  .sources {{ margin-top: 56px; padding-top: 24px; border-top: 1px solid var(--rule); }}
  .sources h2 {{
    font-size: 13px; font-weight: 600; letter-spacing: 0.08em;
    text-transform: uppercase; color: var(--accent); margin: 0 0 18px;
  }}
  ol.source-list {{ margin: 0; padding: 0 0 0 26px; }}
  ol.source-list li {{
    padding: 10px 0; border-bottom: 1px solid var(--rule);
    font-size: 15px; line-height: 1.5;
  }}
  ol.source-list li:last-child {{ border-bottom: 0; }}
  .source-meta {{ color: var(--ink-faint); font-size: 13.5px; }}
  .synth-note {{
    margin-top: 48px; font-size: 13.5px; color: var(--ink-faint);
    line-height: 1.6;
  }}
  footer {{
    padding: 24px 32px; font-size: 13px; color: var(--ink-faint);
    text-align: center; border-top: 1px solid var(--rule);
  }}
  footer a {{ color: var(--ink-soft); }}
</style>
</head>
<body>
<header class="site-header">
  <a class="wordmark" href="/">Sermon Steward<span class="dot">.</span></a>
</header>
<main>
  <div class="breadcrumb"><a href="/">Sermon Steward</a> · <a href="/{church_slug}/">{church_name}</a> · {title}</div>
  <h1>{h1}</h1>
  <p class="deck">{deck}</p>
{body}
{closing}
  <div class="sources">
    <h2>From the pulpit — the sermons behind this page</h2>
    <ol class="source-list">
{sources}
    </ol>
  </div>
  <p class="synth-note">This page synthesizes what {preacher_name} has preached
  on {title_lower} at {church_name}. Every claim above traces to the cited
  sermons — follow any citation to read the full sermon, listen to the audio,
  and see the surrounding context. Minute marks are approximate, estimated
  from each sermon's transcript.</p>
</main>
<footer>
  Sermon Steward stewards the preaching of {church_name}.
</footer>
</body>
</html>
"""


def cite_markers_to_links(text: str, valid_ns: set[int]) -> str:
    """[1][4] → superscript anchor links to #src-N. Unknown ns dropped."""
    import re

    def repl(m):
        n = int(m.group(1))
        if n not in valid_ns:
            return ""
        return f'<sup class="cite"><a href="#src-{n}">[{n}]</a></sup>'

    return re.sub(r"\[(\d+)\]", repl, htmlmod.escape(text))


def render_page(
    topic_slug: str,
    topic_cfg: dict,
    synth: dict,
    sources: list[dict],
    church_dir: Path,
    church_name: str,
    preacher_name: str,
) -> str:
    valid_ns = {s["n"] for s in sources}
    body_parts = []
    for sec in synth.get("sections", []):
        body_parts.append(f"  <h2>{htmlmod.escape(sec['heading'])}</h2>")
        for para in sec.get("paragraphs", []):
            body_parts.append(f"  <p>{cite_markers_to_links(para, valid_ns)}</p>")
    closing_html = ""
    if synth.get("closing"):
        closing_html = (
            f'  <div class="closing">{cite_markers_to_links(synth["closing"], valid_ns)}</div>'
        )
    src_parts = []
    for s in sources:
        date = s["date"] or "undated"
        scripture = f" · {htmlmod.escape(s['scripture'])}" if s["scripture"] else ""
        minute = (
            f" · discussion lands around ≈min {s['minute']}"
            if s["minute"] is not None
            else ""
        )
        src_parts.append(
            f'      <li id="src-{s["n"]}"><a href="{s["href"]}">'
            f"{htmlmod.escape(s['title'])}</a>"
            f'<br><span class="source-meta">{date}{scripture}{minute}</span></li>'
        )
    deck = synth.get("deck") or topic_cfg["deck"]
    return PAGE_TEMPLATE.format(
        title=topic_cfg["title"],
        title_lower=topic_cfg["title"].lower(),
        h1=htmlmod.escape(synth.get("page_title") or topic_cfg["title"]),
        deck=htmlmod.escape(deck),
        deck_attr=htmlmod.escape(deck, quote=True),
        church_slug=church_dir.name,
        church_name=church_name,
        preacher_name=preacher_name,
        topic_slug=topic_slug,
        body="\n".join(body_parts),
        closing=closing_html,
        sources="\n".join(src_parts),
    )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--church-dir", type=Path, required=True)
    ap.add_argument("--church-name", default="Providence Community Church")
    ap.add_argument("--preacher-name", default="Chris Oswald")
    ap.add_argument("--preacher-id", default=PREACHER_CHRIS)
    ap.add_argument("--topics", default=",".join(TOPICS.keys()))
    ap.add_argument("--dry-run", action="store_true",
                    help="retrieve + report, skip synthesis and rendering")
    args = ap.parse_args()

    sb = create_client(
        os.environ["SUPABASE_URL"],
        os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or os.environ["SUPABASE_KEY"],
    )
    vo = voyageai.Client(api_key=os.environ["VOYAGE_API_KEY"])
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    voice_guide = (REPO_ROOT / "chris-voice-style-guide.md").read_text()

    for slug in [t.strip() for t in args.topics.split(",") if t.strip()]:
        cfg = TOPICS.get(slug)
        if not cfg:
            print(f"unknown topic {slug!r} — skipping", file=sys.stderr)
            continue
        print(f"── {cfg['title']} " + "─" * 40)
        units = retrieve_units(sb, vo, args.preacher_id, cfg["phrasings"])
        sources = build_sources(sb, units, args.church_dir)
        print(f"  retrieved {len(units)} units across {len(sources)} citable sermons")
        for s in sources[:8]:
            mm = f" ≈min {s['minute']}" if s["minute"] is not None else ""
            print(f"    [{s['n']}] {s['best_score']:.2f}  {s['title'][:55]}{mm}")
        if args.dry_run:
            continue
        if len(sources) < 3:
            print(f"  only {len(sources)} citable sermons — skipping synthesis")
            continue
        synth = synthesize(client, cfg, sources, voice_guide)
        out_dir = args.church_dir / "topics" / slug
        out_dir.mkdir(parents=True, exist_ok=True)
        page = render_page(
            slug, cfg, synth, sources, args.church_dir,
            args.church_name, args.preacher_name,
        )
        (out_dir / "index.html").write_text(page)
        n_paras = sum(len(s.get("paragraphs", [])) for s in synth.get("sections", []))
        print(f"  wrote {out_dir / 'index.html'} ({len(synth.get('sections', []))} sections, {n_paras} paragraphs)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
