#!/usr/bin/env python3
"""
build_famous_preacher_pages.py

One-off generator for famous-preacher sample sermon pages on
sermonsteward.com. For each preacher we've picked, pulls the sermon
+ all six artifacts (already generated via Haiku) from Supabase and
emits a fully-stewarded HTML page styled to match growing-in-christ.html.

These pages have the complete Discuss · apply · pray surface stack
populated from the artifacts table — unlike the Ricky simplified
samples, which still show "forthcoming" placeholders.

No audio players (none of the famous-preacher sermons have audio_url).

Output dir: /Users/dad/shepherds-guild/sermon-steward/
"""
from __future__ import annotations
import html
import os
from pathlib import Path
from dotenv import load_dotenv
from supabase import create_client

load_dotenv(override=True)

# (preacher_name, sermon_id, filename_slug, short_bio)
PREACHERS: list[tuple[str, str, str, str]] = [
    ("Tim Keller",        "942488fd-07d9-4e74-be7f-2d7769238c0e", "preacher-keller",    "Founding pastor of Redeemer Presbyterian Church in Manhattan; author of <em>The Reason for God</em>, <em>Counterfeit Gods</em>, and the <em>Gospel in Life</em> curriculum."),
    ("Charles Spurgeon",  "d58b0bd3-000e-4bbb-8e39-3d1c66dee335", "preacher-spurgeon",  "19th-century Baptist pastor of the Metropolitan Tabernacle in London; the <em>Treasury of David</em> commentary and his weekly <em>Metropolitan Tabernacle Pulpit</em> remain in print today."),
    ("John MacArthur",    "bfdb32f8-ba3d-467d-ae35-ddd5d18e104c", "preacher-macarthur", "Pastor of Grace Community Church in Sun Valley, CA; expository preacher whose <em>Grace to You</em> radio ministry has carried verse-by-verse preaching across multiple decades."),
    ("R.C. Sproul",       "822ced66-15c4-420e-95c1-3738066928fb", "preacher-sproul",    "Founder of Ligonier Ministries and pastor of Saint Andrew's Chapel in Sanford, FL; author of <em>The Holiness of God</em> and a defining teacher of Reformed doctrine."),
    ("John Piper",        "1d7d3dea-e5bc-4147-9f55-4139b4dc7c9c", "preacher-piper",     "Pastor emeritus of Bethlehem Baptist Church in Minneapolis; founder of Desiring God and author of <em>Desiring God</em>, <em>Don't Waste Your Life</em>, and many biographical studies."),
    ("Martyn Lloyd-Jones","f864329c-37b2-4c18-b958-4948ecc3bb6e", "preacher-mlj",       "Welsh physician-turned-pastor of Westminster Chapel in London (1939–1968); his expositions of Romans and Ephesians sit on most Reformed pastors' shelves."),
    ("Sinclair Ferguson", "97580489-b6b0-413c-a040-a99c0315f888", "preacher-ferguson",  "Scottish Reformed theologian, formerly pastor of First Presbyterian Church in Columbia, SC; author of <em>The Whole Christ</em> and a teaching fellow at Ligonier."),
    ("D.A. Carson",       "cf1abd75-fe04-40cb-a587-88e2b40a5f4f", "preacher-carson",    "Research professor of New Testament at Trinity Evangelical Divinity School; co-founder of The Gospel Coalition and author of <em>The Gagging of God</em>, <em>How Long, O Lord?</em>, and many commentaries."),
    ("John Stott",        "ed938948-97b1-4ec4-b39c-f67897e46c35", "preacher-stott",     "Long-time rector of All Souls Church, Langham Place in London; central figure in 20th-century global evangelicalism and author of <em>The Cross of Christ</em>."),
    ("Thomas Watson",     "a762752c-c392-483b-a767-47b6128656b8", "preacher-watson",    "17th-century English Puritan pastor of St Stephen's Walbrook; his <em>A Body of Divinity</em>, <em>The Beatitudes</em>, and <em>The Doctrine of Repentance</em> remain in print across Reformed publishing houses."),
    ("James Boice",       "43483f88-bfc5-40c3-8165-97a70c2c75c5", "preacher-boice",     "Long-time pastor of Tenth Presbyterian Church in Philadelphia; founder of the Alliance of Confessing Evangelicals and a tireless expositor of the Pauline epistles."),
    ("C.J. Mahaney",      "0468d470-6f5f-40f3-9e1c-ff71cbc39289", "preacher-mahaney",   "Founder of Sovereign Grace Churches and pastor of Sovereign Grace Church of Louisville; long-time senior pastor of Covenant Life Church in Gaithersburg, MD; author of <em>Humility</em> and <em>The Cross-Centered Life</em>."),
]

OUTPUT_DIR = Path("/Users/dad/shepherds-guild/sermon-steward")

MONTHS = ("January","February","March","April","May","June","July","August","September","October","November","December")


def fmt_date_long(iso: str | None) -> str:
    if not iso:
        return ""
    y, m, d = iso.split("-")
    return f"{MONTHS[int(m)-1]} {int(d)}, {y}"


def h(s: str | None) -> str:
    return html.escape(s or "", quote=False)


def render_small_group(body: dict) -> str:
    qs = body.get("questions") or []
    if not qs:
        return ""
    items = []
    for q in qs:
        text = h(q.get("question", ""))
        anchor = q.get("scripture_anchor")
        followup = q.get("follow_up")
        extra = ""
        if anchor:
            extra += f' <span class="qmeta">{h(anchor)}</span>'
        li = f"<li>{text}{extra}"
        if followup:
            li += f'<div class="followup">{h(followup)}</div>'
        li += "</li>"
        items.append(li)
    return f'<ol class="discuss-list">\n{"".join(items)}\n</ol>'


def render_daily_readings(body: dict) -> str:
    days = body.get("days") or []
    intro = body.get("intro")
    rows = []
    for d in days:
        rows.append(
            f'<div class="daily-row">'
            f'<div class="daily-day">{h(d.get("day",""))}</div>'
            f'<div>'
            f'<span class="daily-title">{h(d.get("claim_anchor",""))}</span>'
            f'<span class="daily-ref">{h(d.get("passage",""))}</span>'
            f'<div class="daily-question">{h(d.get("reflection",""))}</div>'
            f'</div></div>'
        )
    out = ""
    if intro:
        out += f'<p style="margin:0 0 14px;color:var(--ink-soft)">{h(intro)}</p>'
    out += f'<div class="daily-plan">{"".join(rows)}</div>'
    return out


def render_prayer(body: dict) -> str:
    text = (body.get("prayer_text") or "").replace("\n\n", "</p><p>").replace("\n", "<br>")
    return f'<blockquote class="prayer-quote"><p>{text}</p></blockquote>'


def render_memory(body: dict) -> str:
    ref = h(body.get("reference",""))
    full = h(body.get("full_text",""))
    why = h(body.get("why_this_verse",""))
    out = f'<blockquote class="memorize-quote">&ldquo;{full}&rdquo;</blockquote>'
    if why:
        out += f'<div class="memorize-ref">{why}</div>'
    return out


def render_family(body: dict) -> str:
    out = ""
    if body.get("prompt"):
        out += f"<p><strong>One question for the table:</strong> {h(body['prompt'])}</p>"
    if body.get("age_band"):
        out += f'<p style="font-size:13px;color:var(--ink-faint)"><em>{h(body["age_band"])}</em></p>'
    if body.get("framing_for_parents"):
        out += f"<p><strong>For parents:</strong> {h(body['framing_for_parents'])}</p>"
    return out


def render_couples(body: dict) -> str:
    qs = body.get("questions") or []
    items = "".join(f"<li>{h(q)}</li>" for q in qs)
    return f'<ol class="discuss-list">{items}</ol>'


RENDERERS = {
    "small_group_questions": ("Small-group leader brief", "Questions for midweek", render_small_group, True),  # wide
    "daily_readings":        ("Daily readings",          "Five-day reading plan", render_daily_readings, True),
    "prayer_prompt":         ("Weekly prayer",           lambda b: b.get("title","A prayer from this sermon"), render_prayer, False),
    "memory_verse":          ("Memorize",                lambda b: b.get("reference","Memory verse"), render_memory, False),
    "family_card":           ("Family table",            lambda b: b.get("title","Conversation for the table"), render_family, False),
    "couples_guide":         ("Couples",                 lambda b: b.get("title","Three questions over coffee"), render_couples, False),
}


def build_discuss_section(artifacts_by_type: dict[str, dict]) -> str:
    cards = []
    # Render wide cards first
    for atype, (label, title_spec, renderer, wide) in RENDERERS.items():
        body = artifacts_by_type.get(atype)
        if not body:
            continue
        title = title_spec(body) if callable(title_spec) else title_spec
        wide_cls = " discuss-card-wide" if wide else ""
        cards.append(
            f'<div class="discuss-card{wide_cls}">'
            f'<div class="discuss-card-label ui">{label}</div>'
            f'<h3 class="discuss-card-title">{h(title)}</h3>'
            f"{renderer(body)}"
            f"</div>"
        )
    return "\n".join(cards)


PAGE_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title} — {preacher} · Sermon Steward</title>
<meta name="description" content="{description}">
<meta property="og:type" content="article">
<meta property="og:title" content="{title} — {preacher}">
<meta property="og:description" content="{description}">
<meta property="og:site_name" content="Sermon Steward">
<style>
  :root {{
    --ink: #1a1a2e; --ink-soft: #3d3d52; --ink-faint: #6f6f80;
    --paper: #faf7f0; --paper-raised: #fffdf7;
    --rule: #e2dcce; --rule-soft: #ede7d8;
    --accent: #2d5a4a; --accent-soft: #5a8073; --accent-deep: #1d3d31;
    --gold: #b8893a; --gold-bg: #fdf4d9;
  }}
  * {{ box-sizing: border-box; }}
  html, body {{ margin:0; padding:0; background:var(--paper); color:var(--ink);
    font-family:"Source Serif Pro","Iowan Old Style","Charter",Georgia,serif;
    font-size:18px; line-height:1.62; -webkit-font-smoothing:antialiased; }}
  .ui {{ font-family:"Inter",system-ui,sans-serif; }}
  a {{ color:var(--accent); text-underline-offset:2px; }}

  .site-header {{ border-bottom:1px solid var(--rule); background:var(--paper-raised); padding:16px 24px; }}
  .site-header-inner {{ max-width:1080px; margin:0 auto; display:flex; align-items:center; justify-content:space-between; }}
  .site-brand {{ font-family:"Inter",sans-serif; font-weight:600; font-size:13px; letter-spacing:0.06em; color:var(--ink); text-decoration:none; }}
  .site-brand .dot {{ color:var(--accent); }}
  .site-tag {{ font-family:"Inter",sans-serif; font-size:11px; color:var(--ink-faint); text-transform:uppercase; letter-spacing:0.12em; }}

  main {{ max-width:780px; margin:0 auto; padding:56px 24px 96px; }}

  .breadcrumb {{ font-size:12px; color:var(--ink-faint); text-transform:uppercase; letter-spacing:0.1em; margin-bottom:22px; }}
  .breadcrumb a {{ color:var(--ink-soft); text-decoration:none; }}

  .sermon-title {{ font-size:42px; font-weight:600; line-height:1.1; letter-spacing:-0.015em; margin:0 0 16px; }}
  .sermon-cite {{ font-family:"Inter",sans-serif; font-size:13px; color:var(--ink-faint);
    display:flex; gap:18px; flex-wrap:wrap; margin-bottom:36px; }}
  .sermon-cite strong {{ color:var(--ink-soft); font-weight:600; }}

  .thesis-hero {{ border-left:3px solid var(--accent); background:var(--paper-raised);
    padding:22px 28px; margin:0 0 36px;
    font-size:22px; line-height:1.5; color:var(--ink); font-style:italic; }}
  .thesis-label {{ display:block; font-family:"Inter",sans-serif; font-size:10px;
    letter-spacing:0.15em; text-transform:uppercase; color:var(--accent);
    font-style:normal; margin-bottom:8px; }}

  .facts-strip {{ display:grid; grid-template-columns:repeat(3,1fr); gap:18px;
    border-top:1px solid var(--rule); border-bottom:1px solid var(--rule);
    padding:18px 0; margin-bottom:40px; }}
  .fact-label {{ font-family:"Inter",sans-serif; font-size:10px; text-transform:uppercase;
    letter-spacing:0.12em; color:var(--ink-faint); margin-bottom:4px; }}
  .fact-value {{ font-size:15px; font-weight:600; color:var(--ink-soft); }}

  .page-section {{ margin:0 0 56px; }}
  .section-eyebrow {{ font-family:"Inter",sans-serif; font-size:11px; letter-spacing:0.16em;
    text-transform:uppercase; color:var(--accent); margin-bottom:8px; }}
  .section-title-h2 {{ font-size:28px; font-weight:600; line-height:1.18; margin:0 0 14px; letter-spacing:-0.01em; }}
  .section-lede {{ color:var(--ink-soft); margin:0 0 24px; font-size:17px; line-height:1.6; }}

  /* Discuss/apply/pray cards */
  .discuss-grid {{ display:grid; grid-template-columns:repeat(2,1fr); gap:16px; margin-top:8px; }}
  .discuss-card {{ background:var(--paper-raised); border:1px solid var(--rule);
    border-radius:12px; padding:26px 28px 24px; color:inherit; }}
  .discuss-card-wide {{ grid-column:1/-1; }}
  .discuss-card-label {{ font-family:"Inter",sans-serif; font-size:10px; font-weight:600;
    text-transform:uppercase; letter-spacing:0.12em; color:var(--accent); margin-bottom:8px; }}
  .discuss-card-title {{ font-weight:600; font-size:20px; margin:0 0 16px; color:var(--ink);
    letter-spacing:-0.005em; }}
  .discuss-card p {{ color:var(--ink-soft); font-size:15.5px; line-height:1.6; margin:0 0 12px; }}
  .discuss-card p:last-child {{ margin-bottom:0; }}
  .discuss-list {{ margin:0; padding-left:22px; color:var(--ink-soft); font-size:15.5px; line-height:1.55; }}
  .discuss-list li {{ margin-bottom:10px; }}
  .discuss-list li::marker {{ color:var(--accent); font-weight:600; }}
  .qmeta {{ font-family:"Inter",sans-serif; font-size:12px; color:var(--ink-faint); margin-left:6px; }}
  .followup {{ font-style:italic; font-size:14.5px; color:var(--ink-faint); margin-top:6px; line-height:1.5; }}

  .daily-plan {{ margin:0; }}
  .daily-row {{ display:grid; grid-template-columns:60px 1fr; gap:14px;
    padding:12px 0; border-bottom:1px solid var(--rule-soft);
    font-size:15px; line-height:1.55; color:var(--ink-soft); }}
  .daily-row:last-child {{ border-bottom:0; }}
  .daily-day {{ font-family:"Inter",sans-serif; font-size:11px; font-weight:700;
    letter-spacing:0.1em; text-transform:uppercase; color:var(--accent); padding-top:2px; }}
  .daily-title {{ color:var(--ink); font-weight:600; }}
  .daily-ref {{ font-family:"Inter",sans-serif; font-size:12px; color:var(--ink-faint); margin-left:8px; }}
  .daily-question {{ margin-top:4px; color:var(--ink-soft); }}

  .prayer-quote {{ font-family:inherit; font-size:16.5px; line-height:1.62; color:var(--ink);
    border-left:3px solid var(--accent); padding:4px 0 4px 18px; margin:4px 0 0; font-style:italic; }}
  .prayer-quote p {{ margin:0 0 12px; color:var(--ink); }}
  .prayer-quote p:last-child {{ margin-bottom:0; }}

  .memorize-quote {{ font-size:19px; line-height:1.55; color:var(--ink); font-style:italic;
    border-left:3px solid var(--accent); padding:4px 0 4px 18px; margin:0; }}
  .memorize-ref {{ font-family:"Inter",sans-serif; font-size:12px; color:var(--ink-faint);
    margin-top:12px; line-height:1.55; }}

  /* About the pastor */
  .pastor-card {{ background:var(--paper-raised); border:1px solid var(--rule);
    border-radius:12px; padding:28px 32px; }}
  .pastor-name {{ font-size:22px; font-weight:600; margin-bottom:8px; }}
  .pastor-bio {{ font-size:15.5px; line-height:1.6; color:var(--ink-soft); margin:0; }}

  .page-footer {{ max-width:780px; margin:64px auto 32px; padding:0 24px;
    font-family:"Inter",sans-serif; font-size:12px; color:var(--ink-faint); line-height:1.6; }}
  .page-footer a {{ color:var(--ink-soft); }}

  @media (max-width:600px) {{
    .sermon-title {{ font-size:32px; }}
    .facts-strip {{ grid-template-columns:1fr; }}
    .discuss-grid {{ grid-template-columns:1fr; }}
    .discuss-card-wide {{ grid-column:auto; }}
  }}
</style>
</head>
<body>

<header class="site-header">
  <div class="site-header-inner">
    <a class="site-brand" href="/">Sermon Steward<span class="dot">.</span></a>
    <span class="site-tag">Famous-Preacher Sample · {preacher}</span>
  </div>
</header>

<main>
  <div class="breadcrumb"><a href="/samples">Samples</a> · Significant sermons stewarded</div>

  <h1 class="sermon-title">{title}</h1>

  <div class="sermon-cite">
    <span><strong>{primary_text}</strong></span>{date_block}
    <span>{preacher}</span>
  </div>

  <blockquote class="thesis-hero">
    <span class="thesis-label">Thesis</span>
    {thesis}
  </blockquote>

  <div class="facts-strip">
    <div class="fact"><div class="fact-label">Primary text</div><div class="fact-value">{primary_text}</div></div>
    <div class="fact"><div class="fact-label">Preacher</div><div class="fact-value">{preacher}</div></div>
    <div class="fact"><div class="fact-label">Surfaces</div><div class="fact-value">6 stewarded</div></div>
  </div>

  {abstract_section}

  <section class="page-section">
    <div class="section-eyebrow">Take it further</div>
    <h2 class="section-title-h2">Discuss · apply · pray</h2>
    <p class="section-lede">Six surfaces drawn from this sermon — small-group leader brief, daily reading plan, weekly prayer, memorize, family table, couples — generated automatically by Sermon Steward.</p>
    <div class="discuss-grid">
{discuss_cards}
    </div>
  </section>

  <section class="page-section">
    <div class="section-eyebrow">About the preacher</div>
    <h2 class="section-title-h2">{preacher}</h2>
    <div class="pastor-card">
      <p class="pastor-bio">{bio}</p>
    </div>
  </section>
</main>

<footer class="page-footer">
  Sample sermon page · stewarded by <a href="/">Sermon Steward</a>. Decomposition + artifact generation produced automatically; voice profile is the default (per-preacher voice profiles are calibrated for paying customers only).
</footer>

</body>
</html>
"""


def main() -> int:
    url = os.environ["SUPABASE_URL"]
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or os.environ["SUPABASE_KEY"]
    sb = create_client(url, key)

    sermon_ids = [p[1] for p in PREACHERS]
    sermons = sb.table("sermons").select(
        "id, title, date, primary_text, main_thesis, abstract"
    ).in_("id", sermon_ids).execute().data
    by_sid = {s["id"]: s for s in sermons}

    artifacts = sb.table("sermon_artifacts").select(
        "sermon_id, artifact_type, body"
    ).in_("sermon_id", sermon_ids).execute().data
    arts_by_sid: dict[str, dict[str, dict]] = {}
    for a in artifacts:
        arts_by_sid.setdefault(a["sermon_id"], {})[a["artifact_type"]] = a["body"]

    wrote = 0
    skipped = 0
    for preacher, sid, slug, bio in PREACHERS:
        s = by_sid.get(sid)
        if not s:
            print(f"  SKIP {preacher}: sermon row not found")
            skipped += 1
            continue
        arts = arts_by_sid.get(sid, {})
        if not arts:
            print(f"  SKIP {preacher}: no artifacts yet (still generating?)")
            skipped += 1
            continue

        date_block = f'<span>{fmt_date_long(s["date"])}</span>' if s.get("date") else ""
        abstract = s.get("abstract") or ""
        abstract_section = ""
        if abstract:
            abstract_section = (
                '<section class="page-section">'
                '<div class="section-eyebrow">What the sermon argues</div>'
                '<h2 class="section-title-h2">The shape of the message</h2>'
                f'<p class="section-lede">{h(abstract)}</p>'
                "</section>"
            )

        discuss = build_discuss_section(arts)
        description = (abstract.split(". ")[0] if abstract else (s.get("main_thesis") or ""))[:200]

        page = PAGE_TEMPLATE.format(
            title=h(s.get("title", "")),
            preacher=preacher,
            primary_text=h(s.get("primary_text", "")),
            date_block=date_block,
            thesis=h(s.get("main_thesis") or s.get("abstract") or ""),
            abstract_section=abstract_section,
            description=h(description),
            discuss_cards=discuss,
            bio=bio,
        )
        out = OUTPUT_DIR / f"{slug}.html"
        out.write_text(page, encoding="utf-8")
        print(f"  wrote {out.name} ({len(page):,} chars)")
        wrote += 1

    print(f"\n{wrote} pages written, {skipped} skipped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
