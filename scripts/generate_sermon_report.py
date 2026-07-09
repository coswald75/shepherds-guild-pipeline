#!/usr/bin/env python3
"""
generate_sermon_report.py
─────────────────────────────────────────────────────────────────────────────
Per-sermon client report (PDF) for a church (e.g. Cross of Grace).

Produces a Sermon Steward–branded PDF that mirrors the look of the live
sermon page, plus three things the live page doesn't carry:

  1. A plain-English SUMMARY of what the sermon is about (top of report).
  2. "WHAT WE NOTICED IN THE INGEST" — doctrinal loci (derived against the
     project's canonical 16-loci taxonomy), themes, and a few editor notes.
  3. ARTICLE IDEAS — a pitch for each major point of the sermon (Chris's
     point-by-point approach, not one-article-per-sermon), plus ONE pitch
     written out as a full sample article in the preacher's own voice.

Then it appends the six congregant resources (small-group, daily readings,
prayer, family, couples, memory verse) as polished sections.

Delivery is manual by design: this script only WRITES the PDF (and a sibling
HTML). Chris previews, downloads, and sends.

Usage:
    python3 scripts/generate_sermon_report.py <sermon_id>
    python3 scripts/generate_sermon_report.py <sermon_id> --model claude-sonnet-4-5-20250929

Output:
    output/reports/<church_slug>/<sermon_slug>.pdf
    output/reports/<church_slug>/<sermon_slug>.html

Env (from .env): ANTHROPIC_API_KEY, SUPABASE_URL, SUPABASE_KEY (service role).
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS_DIR))
sys.path.insert(0, str(REPO_ROOT))

import anthropic  # noqa: E402
from dotenv import load_dotenv  # noqa: E402
from jinja2 import Template  # noqa: E402
from supabase import create_client  # noqa: E402

from doctrinal_loci import LOCUS_NAMES, LOCUS_BLURB  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s",
                    datefmt="%H:%M:%S")
log = logging.getLogger("report")

DEFAULT_MODEL = "claude-sonnet-4-5-20250929"

# Per-preacher voice profile (kept in sync with generate_artifacts.VOICE_PROFILES).
VOICE_PROFILES: dict[str, str] = {
    "9c6f8d69-de55-45db-ac60-0fe6d0cfff59": "chris-voice-style-guide.md",
    "ccb9e59c-bd20-414a-bd6b-25b117b8144c": "ricky-voice-style-guide.md",
}

ARTIFACT_ORDER = [
    "small_group_questions", "daily_readings", "memory_verse",
    "family_card", "couples_guide",
]
ARTIFACT_LABELS = {
    "small_group_questions": "Small-Group Discussion",
    "daily_readings": "Daily Readings",
    "memory_verse": "Memory Verse",
    "prayer_prompt": "Prayer",
    "family_card": "Family Conversation",
    "couples_guide": "For Couples",
}


# ── Clients ──────────────────────────────────────────────────────────────────

def _supabase():
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or os.environ.get("SUPABASE_KEY")
    if not url or not key:
        raise RuntimeError("SUPABASE_URL / SUPABASE_KEY missing in env")
    return create_client(url, key)


def _anthropic():
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise RuntimeError("ANTHROPIC_API_KEY missing in env")
    return anthropic.Anthropic(api_key=key)


# ── Data loading ─────────────────────────────────────────────────────────────

def load_sermon(sb, sermon_id: str) -> dict:
    rows = sb.table("sermons").select(
        "id, title, slug, date, primary_text, series_name, sermon_type, abstract, "
        "main_thesis, tone, hermeneutical_method, preacher_id, "
        "preachers(name, churches(name, slug))"
    ).eq("id", sermon_id).execute().data
    if not rows:
        raise SystemExit(f"sermon {sermon_id} not found")
    return rows[0]


def load_units(sb, sermon_id: str) -> list[dict]:
    return sb.table("units").select(
        "unit_index, rhetorical_function, summary, key_claim"
    ).eq("sermon_id", sermon_id).order("unit_index").execute().data or []


def load_artifacts(sb, sermon_id: str) -> dict[str, dict]:
    rows = sb.table("sermon_artifacts").select("artifact_type, body").eq(
        "sermon_id", sermon_id).execute().data or []
    out: dict[str, dict] = {}
    for r in rows:
        body = r.get("body")
        if isinstance(body, str):
            try:
                body = json.loads(body)
            except Exception:
                body = {"text": body}
        out[r["artifact_type"]] = body or {}
    return out


def load_decomposed(sermon_id: str) -> Optional[dict]:
    p = REPO_ROOT / "output" / f"{sermon_id}_decomposed.json"
    if p.exists():
        try:
            return json.loads(p.read_text())
        except Exception as e:
            log.warning(f"could not parse {p.name}: {e}")
    return None


# ── Context for the LLM ──────────────────────────────────────────────────────

def build_facts(sermon: dict, units: list[dict], decomp: Optional[dict]) -> str:
    d = decomp or {}
    abstract = sermon.get("abstract") or d.get("abstract") or ""
    thesis = sermon.get("main_thesis") or d.get("main_thesis") or ""
    tone = sermon.get("tone") or d.get("tone") or []
    herm = sermon.get("hermeneutical_method") or d.get("hermeneutical_method") or []

    lines: list[str] = []
    lines.append(f"TITLE: {sermon.get('title')}")
    lines.append(f"PREACHER: {(sermon.get('preachers') or {}).get('name')}")
    lines.append(f"DATE: {sermon.get('date')}")
    lines.append(f"PRIMARY TEXT: {sermon.get('primary_text') or d.get('primary_text') or '—'}")
    if sermon.get("series_name"):
        lines.append(f"SERIES: {sermon['series_name']}")
    if abstract:
        lines.append(f"\nABSTRACT:\n{abstract}")
    if thesis:
        lines.append(f"\nMAIN THESIS:\n{thesis}")
    if tone:
        lines.append(f"\nTONE: {', '.join(tone) if isinstance(tone, list) else tone}")
    if herm:
        lines.append(f"HERMENEUTICAL METHOD: {', '.join(herm) if isinstance(herm, list) else herm}")

    # Ordered movement of the sermon — the raw material for point-by-point pitches.
    lines.append("\nSERMON MOVEMENT (unit by unit):")
    src_units = d.get("units") or units
    for u in src_units:
        idx = u.get("unit_index")
        fn = u.get("rhetorical_function") or ""
        summ = (u.get("summary") or "").strip()
        claim = (u.get("key_claim") or "").strip()
        if not (summ or claim):
            continue
        seg = f"  [{idx}] ({fn}) {summ}"
        if claim:
            seg += f"  KEY CLAIM: {claim}"
        lines.append(seg)

    quotes = (d.get("all_quotations") or [])[:12]
    if quotes:
        lines.append("\nNOTABLE QUOTATIONS / SOURCES CITED:")
        for q in quotes:
            if isinstance(q, dict):
                txt = q.get("text") or q.get("quote") or ""
                who = q.get("attribution") or q.get("source") or q.get("author") or ""
                lines.append(f"  - {txt}" + (f" — {who}" if who else ""))
            else:
                lines.append(f"  - {q}")

    xrefs = (d.get("all_cross_references") or [])[:25]
    if xrefs:
        flat = []
        for x in xrefs:
            flat.append(x.get("reference") if isinstance(x, dict) else x)
        flat = [f for f in flat if f]
        if flat:
            lines.append("\nCROSS-REFERENCES: " + ", ".join(flat))

    return "\n".join(lines)


def load_voice(preacher_id: Optional[str]) -> str:
    fname = VOICE_PROFILES.get(preacher_id or "")
    if fname:
        p = REPO_ROOT / fname
        if p.exists():
            return p.read_text()
    p = REPO_ROOT / "sermon_artifacts" / "prompts" / "_voice_sgm.md"
    return p.read_text() if p.exists() else ""


# ── LLM calls ────────────────────────────────────────────────────────────────

def _call_json(client, model: str, system: str, user: str, max_tokens: int) -> Any:
    """One Claude call that must return JSON. Retries transient errors."""
    last = None
    for attempt in range(3):
        try:
            resp = client.messages.create(
                model=model, max_tokens=max_tokens, system=system,
                messages=[{"role": "user", "content": user}],
            )
            text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
            return json.loads(_strip_fences(text))
        except (anthropic.RateLimitError, anthropic.APITimeoutError,
                anthropic.APIConnectionError, anthropic.InternalServerError) as e:
            last = e
            wait = 2 ** attempt
            log.warning(f"transient LLM error ({e.__class__.__name__}); retry in {wait}s")
            time.sleep(wait)
        except json.JSONDecodeError as e:
            last = e
            log.warning(f"JSON parse failed (attempt {attempt+1}); retrying")
            time.sleep(1)
    raise RuntimeError(f"LLM call failed after retries: {last}")


def _strip_fences(s: str) -> str:
    s = s.strip()
    if s.startswith("```"):
        s = re.sub(r"^```[a-zA-Z]*\n", "", s)
        s = re.sub(r"\n```$", "", s)
    # Fall back to the first {...} span if the model added prose.
    if not s.lstrip().startswith("{"):
        m = re.search(r"\{.*\}", s, re.DOTALL)
        if m:
            s = m.group(0)
    return s.strip()


def generate_analysis(client, model: str, facts: str) -> dict:
    loci_menu = "\n".join(f"  - {n}: {LOCUS_BLURB[n]}" for n in LOCUS_NAMES)
    system = (
        "You are a senior editor at Sermon Steward, writing an internal analytical "
        "report ABOUT a sermon for the pastor who preached it. Your voice here is "
        "clear, perceptive, and professional — you are NOT imitating the preacher in "
        "this part. Be specific to THIS sermon; never generic. Return ONLY valid JSON."
    )
    user = f"""Here is the decomposed sermon:

{facts}

Produce a JSON object with exactly these keys:

{{
  "summary": "120–200 words, plain English, what the sermon is about and where it lands. For an intelligent reader who didn't hear it.",
  "doctrinal_loci": [
    {{"locus": "<one of the canonical loci below, exact name>", "note": "one sentence: how this sermon engages it"}}
  ],
  "themes": ["3–6 short theme phrases"],
  "observations": ["2–4 editor notes on what stood out in the ingest — rhetorical structure, a notable move, the strongest illustration or quote. One sentence each."],
  "article_pitches": [
    {{"headline": "working title", "angle": "2–3 sentences on the article's argument and hook", "source_point": "which sermon point/verse this is drawn from"}}
  ]
}}

Rules:
- doctrinal_loci: choose the 2–4 loci this sermon MOST engages, by EXACT name from this list:
{loci_menu}
- article_pitches: one pitch per MAJOR point of the sermon (aim for 4–7). Each must stand alone as its own article built around a single point — not a summary of the whole sermon.
- Output JSON only, no markdown fences."""
    return _call_json(client, model, system, user, max_tokens=3000)


def generate_sample_article(client, model: str, facts: str, voice: str,
                            pitch: dict, preacher_name: str) -> dict:
    system = (
        "You are ghost-writing a short article in the preacher's OWN voice, for the "
        "preacher to publish under his name. Study and follow the voice profile "
        "exactly — cadence, diction, register, how he handles Scripture and "
        "application. Do not sound like a generic blog. Return ONLY valid JSON.\n\n"
        f"=== VOICE PROFILE: {preacher_name} ===\n{voice}"
    )
    user = f"""Sermon context (for grounding — draw on it, don't restate the whole sermon):

{facts}

Write ONE article that develops this single point into a standalone piece:

  HEADLINE: {pitch.get('headline')}
  ANGLE: {pitch.get('angle')}
  DRAWN FROM: {pitch.get('source_point')}

Requirements:
- 600–850 words, in {preacher_name}'s voice per the profile above.
- Build the whole article around this ONE point; do not try to cover the entire sermon.
- Open with a hook, not a recap. Land on a clear, pastoral application.
- Use Scripture the way he does in the profile.

Return JSON only:
{{"title": "final title", "body_markdown": "the article in markdown (## subheads ok, no H1)"}}"""
    return _call_json(client, model, system, user, max_tokens=3500)


# ── Tiny markdown → HTML (no dependency) ─────────────────────────────────────

def md_to_html(md: str) -> str:
    def inline(t: str) -> str:
        t = (t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))
        t = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", t)
        t = re.sub(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)", r"<em>\1</em>", t)
        return t

    html: list[str] = []
    lines = (md or "").split("\n")
    i = 0
    while i < len(lines):
        line = lines[i].rstrip()
        if not line.strip():
            i += 1
            continue
        if line.startswith("### "):
            html.append(f"<h4>{inline(line[4:])}</h4>")
        elif line.startswith("## "):
            html.append(f"<h3>{inline(line[3:])}</h3>")
        elif line.startswith("# "):
            html.append(f"<h3>{inline(line[2:])}</h3>")
        elif line.startswith("> "):
            html.append(f"<blockquote>{inline(line[2:])}</blockquote>")
        elif re.match(r"^\s*[-*]\s+", line):
            items = []
            while i < len(lines) and re.match(r"^\s*[-*]\s+", lines[i]):
                item_text = re.sub(r"^\s*[-*]\s+", "", lines[i])
                items.append("<li>" + inline(item_text) + "</li>")
                i += 1
            html.append("<ul>" + "".join(items) + "</ul>")
            continue
        elif re.match(r"^\s*\d+\.\s+", line):
            items = []
            while i < len(lines) and re.match(r"^\s*\d+\.\s+", lines[i]):
                item_text = re.sub(r"^\s*\d+\.\s+", "", lines[i])
                items.append("<li>" + inline(item_text) + "</li>")
                i += 1
            html.append("<ol>" + "".join(items) + "</ol>")
            continue
        else:
            html.append(f"<p>{inline(line)}</p>")
        i += 1
    return "\n".join(html)


# ── HTML report ──────────────────────────────────────────────────────────────

REPORT_TEMPLATE = Template(r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<style>
  :root {
    --ink:#1a1a2e; --ink-soft:#3d3d52; --ink-faint:#6f6f80;
    --line:#e4e0d8; --bg:#ffffff; --panel:#f8f5ef;
    --accent:{{ accent }}; --accent-soft:#efeae1;
  }
  @page { size: Letter; margin: 0.8in 0.75in; }
  * { box-sizing: border-box; }
  body { color:var(--ink); background:var(--bg); margin:0;
    font-family:"Source Serif Pro","Iowan Old Style",Charter,Georgia,serif;
    font-size:11.5pt; line-height:1.5; }
  .ui { font-family:"Inter",system-ui,-apple-system,"Segoe UI",sans-serif; }
  h1,h2,h3,h4 { font-family:"Source Serif Pro",Georgia,serif; color:var(--ink); line-height:1.2; }
  h1 { font-size:26pt; margin:0 0 4pt; }
  h2 { font-size:15pt; margin:0; padding:0 0 5pt; border-bottom:2px solid var(--accent);
       color:var(--accent); letter-spacing:.2px; }
  h3 { font-size:12.5pt; margin:14pt 0 3pt; }
  h4 { font-size:11pt; margin:10pt 0 2pt; color:var(--ink-soft); }
  p { margin:0 0 8pt; }
  .brandbar { font-family:"Inter",sans-serif; font-size:9pt; letter-spacing:2px;
    text-transform:uppercase; color:var(--accent); font-weight:600; }
  .meta { font-family:"Inter",sans-serif; color:var(--ink-faint); font-size:10pt; margin-top:6pt; }
  .meta strong { color:var(--ink-soft); font-weight:600; }
  .cover { border-bottom:1px solid var(--line); padding-bottom:14pt; margin-bottom:18pt; }
  section { margin:0 0 20pt; }
  .section-body { margin-top:9pt; }
  .lead { font-size:12.5pt; color:var(--ink-soft); }
  .chips { margin:6pt 0; }
  .chip { display:inline-block; font-family:"Inter",sans-serif; font-size:9pt;
    background:var(--accent-soft); color:var(--ink-soft); border-radius:20px;
    padding:2pt 10pt; margin:0 4pt 4pt 0; }
  .loci li { margin-bottom:5pt; }
  .loci b { color:var(--accent); }
  .note-list li { margin-bottom:4pt; color:var(--ink-soft); }
  .pitch { background:var(--panel); border:1px solid var(--line); border-left:3px solid var(--accent);
    border-radius:6px; padding:10pt 12pt; margin:0 0 9pt; break-inside:avoid; }
  .pitch .hl { font-weight:600; font-size:12pt; }
  .pitch .src { font-family:"Inter",sans-serif; font-size:8.5pt; text-transform:uppercase;
    letter-spacing:.5px; color:var(--ink-faint); margin-top:5pt; }
  .sample { background:#fff; border:1px solid var(--line); border-radius:6px; padding:14pt 16pt; }
  .sample .tag { font-family:"Inter",sans-serif; font-size:8.5pt; letter-spacing:1px;
    text-transform:uppercase; color:var(--accent); font-weight:600; }
  .sample blockquote { border-left:3px solid var(--accent-soft); margin:8pt 0; padding-left:10pt;
    color:var(--ink-soft); font-style:italic; }
  .resource { break-inside:avoid; margin-bottom:14pt; }
  .qa { margin:0 0 8pt; }
  .qa .q { font-weight:600; }
  .qa .f { color:var(--ink-soft); font-size:10.5pt; margin-left:10pt; }
  .qa .anchor { font-family:"Inter",sans-serif; font-size:8.5pt; color:var(--ink-faint);
    text-transform:uppercase; letter-spacing:.5px; }
  .day { margin-bottom:7pt; }
  .day .d { font-weight:600; } .day .p { color:var(--accent); font-size:10pt; }
  .verse { background:var(--panel); border-radius:6px; padding:10pt 12pt; font-style:italic; }
  .page-break { page-break-before:always; }
  .footer { margin-top:22pt; padding-top:8pt; border-top:1px solid var(--line);
    font-family:"Inter",sans-serif; font-size:8.5pt; color:var(--ink-faint); }
</style></head>
<body>
  <div class="cover">
    <div class="brandbar">Sermon Steward · Sermon Report</div>
    <h1>{{ sermon.title }}</h1>
    <div class="meta">
      <strong>{{ preacher }}</strong> &nbsp;·&nbsp; {{ church }} &nbsp;·&nbsp; {{ date_h }}
      {% if sermon.primary_text %}&nbsp;·&nbsp; {{ sermon.primary_text }}{% endif %}
      {% if sermon.series_name %}<br><span style="color:var(--ink-faint)">Series: {{ sermon.series_name }}</span>{% endif %}
    </div>
  </div>

  <section>
    <h2>Summary</h2>
    <div class="section-body"><p class="lead">{{ analysis.summary }}</p></div>
  </section>

  <section>
    <h2>What We Noticed</h2>
    <div class="section-body">
      <h3>Doctrinal loci</h3>
      <ul class="loci">
        {% for l in analysis.doctrinal_loci %}<li><b>{{ l.locus }}</b> — {{ l.note }}</li>{% endfor %}
      </ul>
      <h3>Themes</h3>
      <div class="chips">{% for t in analysis.themes %}<span class="chip">{{ t }}</span>{% endfor %}</div>
      {% if analysis.observations %}
      <h3>Editor notes</h3>
      <ul class="note-list">{% for o in analysis.observations %}<li>{{ o }}</li>{% endfor %}</ul>
      {% endif %}
    </div>
  </section>

  <section>
    <h2>Writing Prompts</h2>
    <div class="section-body">
      <p style="color:var(--ink-faint);font-family:'Inter',sans-serif;font-size:10pt">
        Here are some concepts you could explore further in your own reading and writing.</p>
      {% for p in analysis.article_pitches %}
      <div class="pitch">
        <div class="hl">{{ loop.index }}. {{ p.headline }}</div>
        <div>{{ p.angle }}</div>
        <div class="src">From: {{ p.source_point }}</div>
      </div>
      {% endfor %}
    </div>
  </section>

  <section>
    <h2>Sample Article</h2>
    <div class="section-body">
      <div class="sample">
        <div class="tag">Written in {{ preacher }}'s voice · from writing prompt #{{ sample_idx }}</div>
        <h3>{{ sample.title }}</h3>
        {{ sample_html|safe }}
      </div>
    </div>
  </section>

  <div class="page-break"></div>
  <section>
    <h2>Congregation Resources</h2>
    <div class="section-body">
      <p style="color:var(--ink-faint);font-family:'Inter',sans-serif;font-size:10pt">
        The same resources published on your live sermon page.</p>
      {% for block in resources %}
      <div class="resource">
        <h3>{{ block.label }}</h3>
        {{ block.html|safe }}
      </div>
      {% endfor %}
    </div>
  </section>

  <div class="footer">
    Generated by Sermon Steward · {{ generated }} · sermonsteward.com<br>
    Doctrinal loci and article ideas are machine-assisted analysis for your review.
  </div>
</body></html>""")


def esc(s: Any) -> str:
    return (str(s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def render_resource(atype: str, body: dict) -> str:
    """Per-artifact-type HTML for the congregant resources section."""
    if not body:
        return "<p><em>—</em></p>"
    if atype == "small_group_questions":
        out = []
        for q in body.get("questions", []):
            out.append('<div class="qa">'
                       f'<div class="q">{esc(q.get("question"))}</div>'
                       + (f'<div class="f">↳ {esc(q.get("follow_up"))}</div>' if q.get("follow_up") else "")
                       + (f'<div class="anchor">{esc(q.get("scripture_anchor"))}</div>' if q.get("scripture_anchor") else "")
                       + '</div>')
        return "\n".join(out)
    if atype == "daily_readings":
        out = []
        if body.get("intro"):
            out.append(f"<p>{esc(body['intro'])}</p>")
        for d in body.get("days", []):
            out.append('<div class="day">'
                       f'<span class="d">{esc(d.get("day"))}</span> '
                       f'<span class="p">{esc(d.get("passage"))}</span>'
                       f'<div>{esc(d.get("reflection"))}</div></div>')
        return "\n".join(out)
    if atype == "memory_verse":
        return (f'<div class="verse">{esc(body.get("full_text"))}<br>'
                f'<strong>— {esc(body.get("reference"))}</strong></div>'
                + (f'<p>{esc(body.get("why_this_verse"))}</p>' if body.get("why_this_verse") else ""))
    if atype == "prayer_prompt":
        h = f'<h4>{esc(body["title"])}</h4>' if body.get("title") else ""
        paras = "".join(f"<p>{esc(p)}</p>" for p in str(body.get("prayer_text", "")).split("\n\n") if p.strip())
        return h + paras
    if atype == "family_card":
        h = f'<h4>{esc(body["title"])}</h4>' if body.get("title") else ""
        out = [h, f"<p>{esc(body.get('prompt'))}</p>"]
        if body.get("age_band"):
            out.append(f'<p class="anchor">{esc(body["age_band"])}</p>')
        if body.get("framing_for_parents"):
            out.append(f"<p><em>For parents:</em> {esc(body['framing_for_parents'])}</p>")
        return "\n".join(out)
    if atype == "couples_guide":
        h = f'<h4>{esc(body["title"])}</h4>' if body.get("title") else ""
        qs = "".join(f'<div class="qa"><div class="q">{esc(q)}</div></div>' for q in body.get("questions", []))
        return h + qs
    # Fallback
    return f"<pre>{esc(json.dumps(body, indent=2))}</pre>"


# ── PDF ──────────────────────────────────────────────────────────────────────

def html_to_pdf(html: str, pdf_path: Path) -> None:
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.set_content(html, wait_until="networkidle")
        page.pdf(path=str(pdf_path), format="Letter", print_background=True,
                 margin={"top": "0.0in", "bottom": "0.0in", "left": "0.0in", "right": "0.0in"})
        browser.close()


def fmt_date(d: Optional[str]) -> str:
    if not d:
        return ""
    try:
        return datetime.strptime(d, "%Y-%m-%d").strftime("%B %-d, %Y")
    except Exception:
        return d


# ── Main ─────────────────────────────────────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("sermon_id")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--accent", default="#2d5a4a", help="brand accent color")
    args = ap.parse_args()

    load_dotenv(REPO_ROOT / ".env")
    sb = _supabase()
    client = _anthropic()

    sermon = load_sermon(sb, args.sermon_id)
    units = load_units(sb, args.sermon_id)
    artifacts = load_artifacts(sb, args.sermon_id)
    decomp = load_decomposed(args.sermon_id)

    preacher = (sermon.get("preachers") or {}).get("name") or "—"
    church_obj = (sermon.get("preachers") or {}).get("churches") or {}
    church = church_obj.get("name") or "—"
    church_slug = church_obj.get("slug") or "church"

    facts = build_facts(sermon, units, decomp)
    voice = load_voice(sermon.get("preacher_id"))

    log.info("generating analysis (summary, loci, themes, pitches) …")
    analysis = generate_analysis(client, args.model, facts)

    pitches = analysis.get("article_pitches") or []
    if not pitches:
        raise SystemExit("no article pitches returned")
    log.info(f"  {len(pitches)} pitches; writing sample article for pitch #1 …")
    sample = generate_sample_article(client, args.model, facts, voice, pitches[0], preacher)

    resources = [{"label": ARTIFACT_LABELS.get(t, t), "html": render_resource(t, artifacts.get(t, {}))}
                 for t in ARTIFACT_ORDER if t in artifacts]

    html = REPORT_TEMPLATE.render(
        sermon=sermon, preacher=preacher, church=church, date_h=fmt_date(sermon.get("date")),
        analysis=analysis, sample=sample, sample_idx=1, sample_html=md_to_html(sample.get("body_markdown", "")),
        resources=resources, accent=args.accent,
        generated=datetime.now().strftime("%B %-d, %Y"),
    )

    out_dir = REPO_ROOT / "output" / "reports" / church_slug
    out_dir.mkdir(parents=True, exist_ok=True)
    slug = sermon.get("slug") or args.sermon_id
    html_path = out_dir / f"{slug}.html"
    pdf_path = out_dir / f"{slug}.pdf"
    html_path.write_text(html)
    log.info("rendering PDF …")
    html_to_pdf(html, pdf_path)
    log.info(f"DONE → {pdf_path}")
    print(str(pdf_path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
