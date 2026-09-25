#!/usr/bin/env python3
"""
generate_series_report.py — a series-level "capstone" report synthesized across
all the sermons in a preaching series. First pilot: Cross of Grace's
"Living Life Backwards — A Journey Through Ecclesiastes" (summer 2026).

Pulls each sermon's decomposition (thesis + abstract) from Supabase, asks Sonnet
to synthesize the arc / throughline / chorus-of-voices, and renders a branded PDF
(mountain cover + Cross of Grace seal on interior pages) via headless Chromium.

Usage:
    python scripts/generate_series_report.py
"""
from __future__ import annotations

import base64
import json
import logging
import os
import re
import sys
from pathlib import Path

import anthropic
from dotenv import load_dotenv
from supabase import create_client

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s",
                    datefmt="%H:%M:%S")
log = logging.getLogger("series-report")

MODEL = "claude-sonnet-4-5-20250929"

# ── Series config (the pilot) ────────────────────────────────────────────────
SERIES = {
    "title": "Living Life Backwards",
    "subtitle": "A Journey Through Ecclesiastes",
    "church": "Cross of Grace Church",
    "location": "El Paso, TX",
    "season": "Summer 2026",
    "cover_image": Path.home() / "Downloads" / "COGelPasoThumbnail.jpg",
    "logo_image": Path.home() / "Downloads" / "COG-Black.png",
    # In preaching order:
    "sermon_ids": [
        "e8a4c0a5-48a3-489b-9ab1-5c71bf3b12cd",  # Why Does Life Seem Pointless — Ecc 1
        "2ee2b6f6-e9d2-4936-a133-bc6cb24df7d5",  # Open Hands — Ecc 2
        "00790941-51d1-44c2-9a3c-5594304477d7",  # Our Burdens, God's Gift — Ecc 3
        "8053a77b-2f51-452f-a243-4a4cca8998ab",  # How Do You Live Well — Ecc 9
        "707af3df-321b-4644-8fd4-eb19837526ba",  # How Can I Avoid Tragedy — Ecc 4-6
        "1a71d353-53b2-4166-85c1-cbbabcc545e4",  # Sit in the Sorrow, Sow the Seed — Ecc 7&11
        "6142e60b-3f84-405a-8882-67f7db7ad03e",  # Simplify Your Life — Ecc 12 (finale)
    ],
}

# Brand palette — monochrome slate to match the mountain cover.
BG = "#ffffff"
INK = "#1a1a1a"
INK_SOFT = "#4a4a4a"
INK_FAINT = "#8a8a8a"
ACCENT = "#3f5661"        # slate blue-grey (mountain tone)
RULE = "#e3e3e0"
PANEL = "#f6f5f2"


def _supabase():
    url = os.environ["SUPABASE_URL"]
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or os.environ.get("SUPABASE_KEY") \
        or os.environ.get("SUPABASE_SERVICE_KEY")
    return create_client(url, key)


def _anthropic():
    return anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])


def _data_uri(path: Path) -> str:
    mime = "image/png" if path.suffix.lower() == ".png" else "image/jpeg"
    b64 = base64.b64encode(path.read_bytes()).decode()
    return f"data:{mime};base64,{b64}"


def load_series(sb) -> list[dict]:
    rows = sb.table("sermons").select(
        "id, title, date, primary_text, main_thesis, abstract, "
        "preachers(name)"
    ).in_("id", SERIES["sermon_ids"]).execute().data
    by_id = {r["id"]: r for r in rows}
    out = []
    for sid in SERIES["sermon_ids"]:
        r = by_id.get(sid)
        if not r:
            continue
        out.append({
            "id": sid,
            "title": r.get("title"),
            "date": r.get("date"),
            "preacher": (r.get("preachers") or {}).get("name") or "",
            "primary_text": r.get("primary_text"),
            "main_thesis": r.get("main_thesis"),
            "abstract": r.get("abstract"),
        })
    return out


SCHEMA = {
    "type": "object",
    "properties": {
        "series_line": {"type": "string", "description": "One warm sentence capturing what this series was about."},
        "overview": {"type": "string", "description": "2-3 paragraphs (plain text, \\n\\n between) introducing Ecclesiastes and the 'Living Life Backwards' premise of the series."},
        "arc": {"type": "string", "description": "2-3 paragraphs tracing how the series journeyed through the book from chapter 1 to 12."},
        "themes": {
            "type": "array",
            "items": {"type": "object", "properties": {
                "title": {"type": "string"}, "body": {"type": "string"}},
                "required": ["title", "body"]},
            "description": "4-5 throughline themes that recurred across the series, each a short title + 2-3 sentence body."
        },
        "voices": {"type": "string", "description": "1-2 paragraphs on the chorus of preachers who carried the series — one unified message in multiple voices."},
        "sermons": {
            "type": "array",
            "items": {"type": "object", "properties": {
                "id": {"type": "string"}, "takeaway": {"type": "string", "description": "One vivid sentence — the heart of this sermon."}},
                "required": ["id", "takeaway"]},
            "description": "One entry per sermon (match by id), in the given order."
        },
        "closing": {"type": "string", "description": "1-2 paragraph pastoral closing reflection — where the whole series lands (fear God, keep His commandments)."},
    },
    "required": ["series_line", "overview", "arc", "themes", "voices", "sermons", "closing"],
}


def synthesize(client, sermons: list[dict]) -> dict:
    lines = []
    for i, s in enumerate(sermons, 1):
        lines.append(
            f"{i}. \"{s['title']}\" — {s['preacher']} — {s['primary_text']} ({s['date']})\n"
            f"   Thesis: {s['main_thesis']}\n"
            f"   Abstract: {s['abstract']}"
        )
    corpus = "\n\n".join(lines)
    prompt = (
        f"You are writing a warm, theologically rich CAPSTONE REFLECTION on a completed "
        f"preaching series at {SERIES['church']} ({SERIES['location']}): "
        f"\"{SERIES['title']}: {SERIES['subtitle']}\" — a {len(sermons)}-part journey through "
        f"the book of Ecclesiastes, preached in {SERIES['season']} by a rotation of preachers.\n\n"
        f"This is a gift to the congregation and pastors — a way to look back over the whole "
        f"journey and see the unified message. Write in a pastoral, literate, Reformed-evangelical "
        f"register: vivid but not flowery, faithful to Scripture, never inventing quotes or claims "
        f"beyond what the sermons below actually said. Synthesize ACROSS the sermons — find the arc, "
        f"the recurring threads, the gospel throughline (Ecclesiastes' realism about 'vapor' driving "
        f"us to fear God and receive life as gift, fulfilled in Christ).\n\n"
        f"THE SERMONS (in preaching order):\n\n{corpus}\n\n"
        f"Produce the structured reflection."
    )
    resp = client.messages.create(
        model=MODEL, max_tokens=4000,
        tools=[{"name": "series_report", "description": "Structured series reflection.",
                "input_schema": SCHEMA}],
        tool_choice={"type": "tool", "name": "series_report"},
        messages=[{"role": "user", "content": prompt}],
    )
    for block in resp.content:
        if block.type == "tool_use":
            return block.input
    raise SystemExit("no structured output returned")


# Ricky Alcantar — lead pastor, anchored the series (4 of 7, incl. the finale).
RICKY_ID = "ccb9e59c-bd20-414a-bd6b-25b117b8144c"


def load_voice() -> str:
    p = REPO_ROOT / "ricky-voice-style-guide.md"
    if p.exists():
        return p.read_text()
    p = REPO_ROOT / "sermon_artifacts" / "prompts" / "_voice_sgm.md"
    return p.read_text() if p.exists() else ""


ARTICLE_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string", "description": "An evocative article title (not just the series name)."},
        "body": {"type": "string", "description": "The full article, 750-950 words, plain text with \\n\\n between paragraphs. No headings inside."},
    },
    "required": ["title", "body"],
}


def generate_article(client, sermons: list[dict], synth: dict, voice: str) -> dict:
    material = "\n".join(
        f"- \"{s['title']}\" ({s['primary_text']}, {s['preacher']}): {s['main_thesis']}"
        for s in sermons
    )
    themes = "; ".join(t.get("title", "") for t in synth.get("themes", []))
    system = (
        "You are writing AS Ricky Alcantar, lead pastor of Cross of Grace Church in El Paso, "
        "in his own voice. Study and match this voice guide closely — cadence, diction, the way "
        "he moves from observation to Scripture to gospel:\n\n" + voice[:9000]
    )
    prompt = (
        "Write a single, cohesive ARTICLE that encapsulates our just-completed summer series through "
        "Ecclesiastes, \"Living Life Backwards\" — a reflective piece a member could read to relive the "
        "whole journey in one sitting, or that we could publish as a series wrap-up. 750-950 words. "
        "It should feel written, not summarized: one flowing essay, not a list. Trace the movement of "
        "the whole book and series (grasping vapor under the sun -> releasing control -> receiving life "
        "as gift -> the fear of God), and land where Ecclesiastes 12 lands — fear God, keep His "
        "commandments — fulfilled in Christ, who bore what we cannot carry and defeated the death that "
        "makes everything vapor. Draw only on what the series actually preached; do not invent quotes.\n\n"
        f"Recurring threads we named: {themes}.\n\n"
        f"The seven sermons, in order:\n{material}\n\n"
        "Write the article now, in Ricky's voice."
    )
    resp = client.messages.create(
        model=MODEL, max_tokens=3500, system=system,
        tools=[{"name": "article", "description": "The series article.", "input_schema": ARTICLE_SCHEMA}],
        tool_choice={"type": "tool", "name": "article"},
        messages=[{"role": "user", "content": prompt}],
    )
    for block in resp.content:
        if block.type == "tool_use":
            return block.input
    raise SystemExit("no article returned")


def fmt_date(d: str) -> str:
    from datetime import datetime
    try:
        return datetime.strptime(d, "%Y-%m-%d").strftime("%B %-d, %Y")
    except Exception:
        return d or ""


def esc(t) -> str:
    import html
    return html.escape(str(t or ""))


def paras(text: str) -> str:
    out = []
    for p in (text or "").split("\n\n"):
        if not p.strip():
            continue
        e = esc(p)
        # Convert any markdown emphasis the model emitted into real tags so
        # asterisks don't show up literally.
        e = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", e)
        e = re.sub(r"\*(.+?)\*", r"<em>\1</em>", e)
        e = re.sub(r"_(.+?)_", r"<em>\1</em>", e)
        out.append(f"<p>{e}</p>")
    return "".join(out)


def build_html(data: dict, sermons: list[dict], article: dict) -> str:
    cover = _data_uri(SERIES["cover_image"])
    by_id = {s["id"]: s for s in sermons}
    dates = [s["date"] for s in sermons if s["date"]]
    span = f"{fmt_date(min(dates))} – {fmt_date(max(dates))}" if dates else ""

    theme_html = "".join(
        f'<div class="theme"><h3>{esc(t["title"])}</h3><p>{esc(t["body"])}</p></div>'
        for t in data.get("themes", [])
    )
    take = {t["id"]: t["takeaway"] for t in data.get("sermons", []) if t.get("id")}
    cap_html = ""
    for i, s in enumerate(sermons, 1):
        cap_html += (
            f'<div class="cap">'
            f'<div class="cap-num">{i}</div>'
            f'<div class="cap-body">'
            f'<div class="cap-title">{esc(s["title"])}</div>'
            f'<div class="cap-meta">{esc(s["primary_text"])} &middot; {esc(s["preacher"])} &middot; {esc(fmt_date(s["date"]))}</div>'
            f'<div class="cap-take">{esc(take.get(s["id"], s["main_thesis"]))}</div>'
            f'</div></div>'
        )

    return f"""<!DOCTYPE html><html><head><meta charset="utf-8"><style>
  @page {{ size: Letter; }}
  * {{ box-sizing: border-box; }}
  body {{ margin:0; color:{INK}; background:{BG};
    font-family:"Source Serif Pro","Iowan Old Style",Georgia,serif; font-size:11.5pt; line-height:1.55; }}
  .ui {{ font-family:"Inter",system-ui,-apple-system,"Segoe UI",sans-serif; }}
  h1,h2,h3 {{ font-family:"Source Serif Pro",Georgia,serif; color:{INK}; line-height:1.15; }}
  p {{ margin:0 0 9pt; }}

  /* Cover — sized to fit a single page */
  .cover {{ text-align:center; padding-top:8pt; page-break-after:always; }}
  .cover .eyebrow {{ font-family:"Inter",sans-serif; font-size:10pt; letter-spacing:3px;
    text-transform:uppercase; color:{ACCENT}; font-weight:600; margin-bottom:12pt; }}
  .cover img {{ width:60%; border-radius:10px; box-shadow:0 8px 30px rgba(0,0,0,0.18); }}
  .cover h1 {{ font-size:32pt; margin:16pt 0 2pt; letter-spacing:-0.01em; }}
  .cover .sub {{ font-size:15pt; font-style:italic; color:{INK_SOFT}; margin-bottom:12pt; }}
  .cover .kind {{ font-family:"Inter",sans-serif; font-size:9.5pt; letter-spacing:2px;
    text-transform:uppercase; color:{ACCENT}; font-weight:600; }}
  .cover .meta {{ font-family:"Inter",sans-serif; font-size:10.5pt; color:{INK_FAINT}; margin-top:7pt; }}
  .cover .line {{ font-size:13pt; font-style:italic; color:{INK_SOFT}; max-width:80%; margin:14pt auto 0; }}

  /* Sections */
  .sec {{ margin-top:20pt; }}
  h2 {{ font-size:17pt; margin:0 0 3pt; }}
  h2 + .kicker {{ font-family:"Inter",sans-serif; font-size:8.5pt; letter-spacing:2px;
    text-transform:uppercase; color:{ACCENT}; font-weight:600; margin-bottom:9pt; }}
  .rule {{ height:2px; background:{ACCENT}; width:44pt; margin:0 0 12pt; border-radius:2px; }}

  .theme {{ margin:0 0 11pt; padding-left:12pt; border-left:2px solid {RULE}; }}
  .theme h3 {{ font-size:12.5pt; margin:0 0 2pt; }}
  .theme p {{ margin:0; color:{INK_SOFT}; }}

  .cap {{ display:flex; gap:12pt; padding:10pt 0; border-bottom:1px solid {RULE}; page-break-inside:avoid; }}
  .cap-num {{ font-family:"Inter",sans-serif; font-weight:700; font-size:13pt; color:{ACCENT};
    min-width:20pt; }}
  .cap-title {{ font-size:13pt; font-weight:600; }}
  .cap-meta {{ font-family:"Inter",sans-serif; font-size:8.5pt; text-transform:uppercase;
    letter-spacing:0.5px; color:{INK_FAINT}; margin:1pt 0 4pt; }}
  .cap-take {{ color:{INK_SOFT}; font-style:italic; }}

  .closing {{ margin-top:20pt; background:{PANEL}; border-radius:10px; padding:16pt 18pt; }}
  .closing h2 {{ margin-top:0; }}

  /* Capstone article */
  .article {{ page-break-before:always; padding-top:6pt; }}
  .article .art-eyebrow {{ font-family:"Inter",sans-serif; font-size:8.5pt; letter-spacing:2px;
    text-transform:uppercase; color:{ACCENT}; font-weight:600; }}
  .article .art-title {{ font-size:22pt; margin:4pt 0 3pt; letter-spacing:-0.01em; }}
  .article .byline {{ font-family:"Inter",sans-serif; font-size:9.5pt; color:{INK_FAINT};
    margin-bottom:14pt; }}
  .article .art-rule {{ height:2px; background:{ACCENT}; width:44pt; margin:0 0 14pt; border-radius:2px; }}
  .article p {{ margin:0 0 10pt; text-align:justify; }}
  .article p:first-of-type::first-letter {{ float:left; font-family:"Source Serif Pro",Georgia,serif;
    font-size:44pt; line-height:34pt; padding:2pt 6pt 0 0; color:{ACCENT}; font-weight:700; }}
</style></head>
<body>

  <div class="cover">
    <div class="eyebrow">{esc(SERIES['church'])} &middot; {esc(SERIES['location'])}</div>
    <img src="{cover}" alt="Cross of Grace Church">
    <h1>{esc(SERIES['title'])}</h1>
    <div class="sub">{esc(SERIES['subtitle'])}</div>
    <div class="kind">A Series Reflection</div>
    <div class="meta">{esc(len(sermons))} sermons &middot; {esc(span)}</div>
    <div class="line">{esc(data.get('series_line'))}</div>
  </div>

  <div class="sec"><h2>The Journey</h2><div class="kicker">What this series was</div><div class="rule"></div>
    {paras(data.get('overview'))}
    {paras(data.get('arc'))}
  </div>

  <div class="sec"><h2>The Threads That Held It Together</h2><div class="kicker">Throughline</div><div class="rule"></div>
    {theme_html}
  </div>

  <div class="sec"><h2>A Chorus of Voices</h2><div class="kicker">One message, many preachers</div><div class="rule"></div>
    {paras(data.get('voices'))}
  </div>

  <div class="sec"><h2>The Series, Sermon by Sermon</h2><div class="kicker">The whole arc</div><div class="rule"></div>
    {cap_html}
  </div>

  <div class="closing"><h2>A Word to Carry Forward</h2>
    {paras(data.get('closing'))}
  </div>

  <div class="article">
    <div class="art-eyebrow">The Series, In One Piece</div>
    <h1 class="art-title">{esc(article.get('title'))}</h1>
    <div class="byline ui">A reflection in the voice of Ricky Alcantar &middot; {esc(SERIES['church'])}</div>
    <div class="art-rule"></div>
    {paras(article.get('body'))}
  </div>

</body></html>"""


def html_to_pdf(html: str, pdf_path: Path):
    from playwright.sync_api import sync_playwright
    logo = _data_uri(SERIES["logo_image"])
    footer = (
        f'<div style="width:100%; text-align:center; padding:0 0 4px;">'
        f'<img src="{logo}" style="height:26px; opacity:0.85;"/></div>'
    )
    header = '<div></div>'
    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.set_content(html, wait_until="networkidle")
        page.pdf(path=str(pdf_path), format="Letter", print_background=True,
                 display_header_footer=True, header_template=header, footer_template=footer,
                 margin={"top": "0.55in", "bottom": "0.7in", "left": "0.7in", "right": "0.7in"})
        browser.close()


def main():
    load_dotenv(REPO_ROOT / ".env")
    sb = _supabase()
    client = _anthropic()
    sermons = load_series(sb)
    log.info(f"loaded {len(sermons)} sermons for the series")
    log.info("synthesizing series reflection …")
    data = synthesize(client, sermons)
    log.info(f"  {len(data.get('themes', []))} themes, {len(data.get('sermons', []))} capsules")
    log.info("writing the capstone article in Ricky's voice …")
    article = generate_article(client, sermons, data, load_voice())
    log.info(f"  article: {article.get('title')!r} ({len(article.get('body','').split())} words)")
    out = REPO_ROOT / "output" / "reports" / "cross-of-grace-church" / "SERIES-living-life-backwards.pdf"
    log.info("rendering PDF …")
    html_to_pdf(build_html(data, sermons, article), out)
    log.info(f"DONE → {out}")
    print(out)


if __name__ == "__main__":
    main()
