#!/usr/bin/env python3
"""
build_ricky_sample_pages.py

One-off generator for Ricky Alcantar sample sermon pages on
sermonsteward.com. Pulls each sermon's metadata + audio URL from Supabase,
emits a simplified HTML page styled to match growing-in-christ.html,
and writes into the sermon-steward repo.

Output dir: /Users/dad/shepherds-guild/sermon-steward/

Pages produced are intentionally simpler than growing-in-christ.html:
  - hero (title, date, primary text, audio player)
  - thesis pull-quote
  - abstract
  - "Full stewardship surfaces forthcoming" notice (the artifact-driven
    Discuss · apply · pray cards require the artifact pipeline + renderer
    to be wired together; that's the next ticket)
  - about-the-church card linking back to crossofgrace.net

Audio URLs from Nucleus expire ~6 months out (signed S3). Pages will
need re-rendering periodically. Long-term fix: stable URL pattern via
the Nucleus public site rather than direct S3.
"""
from __future__ import annotations
import os
from pathlib import Path
from dotenv import load_dotenv
from supabase import create_client

load_dotenv(override=True)

SERMON_IDS = [
    "680ee271-19de-4baa-a771-574fda65cb7e",  # Life, Gender, and the Pursuit of Happiness
    "e98ccdec-74ff-4885-946e-fd8d92710662",  # Rescuing Womanhood
    "9772e967-ddfd-4f40-9540-c8e2b7a59a5d",  # Rescuing Manhood
]
OUTPUT_DIR = Path("/Users/dad/shepherds-guild/sermon-steward")

MONTHS = ("January", "February", "March", "April", "May", "June",
          "July", "August", "September", "October", "November", "December")


def fmt_date_long(iso: str) -> str:
    y, m, d = iso.split("-")
    return f"{MONTHS[int(m)-1]} {int(d)}, {y}"


def file_slug(slug_with_date: str) -> str:
    # "rescuing-manhood-2026-04-12" → "rescuing-manhood"
    parts = slug_with_date.rsplit("-", 3)
    if len(parts) >= 4 and parts[-3].isdigit() and parts[-2].isdigit() and parts[-1].isdigit():
        return "-".join(parts[:-3])
    return slug_with_date


TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">

<title>{title} — Ricky Alcantar · Cross of Grace</title>
<meta name="description" content="{abstract_short}">

<meta property="og:type" content="article">
<meta property="og:title" content="{title} — A sermon on {primary_text}">
<meta property="og:description" content="{abstract_short}">
<meta property="og:site_name" content="Sermon Steward">
<meta property="article:published_time" content="{date_iso}">
<meta property="article:author" content="Ricky Alcantar">
<meta property="article:section" content="{series}">

<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="{title} — {primary_text}">
<meta name="twitter:description" content="{abstract_short}">

<script type="application/ld+json">
{{
  "@context": "https://schema.org",
  "@type": "Article",
  "headline": "{title}",
  "alternativeHeadline": "{primary_text}",
  "datePublished": "{date_iso}",
  "inLanguage": "en",
  "isPartOf": {{"@type": "CreativeWorkSeries", "name": "{series}"}},
  "author": {{"@type": "Person", "name": "Ricky Alcantar", "jobTitle": "Pastor"}},
  "publisher": {{"@type": "Church", "name": "Cross of Grace Church",
    "address": {{"@type": "PostalAddress", "addressLocality": "El Paso", "addressRegion": "TX", "addressCountry": "US"}}}}
}}
</script>

<style>
  :root {{
    --ink:        #1a1a2e;
    --ink-soft:   #3d3d52;
    --ink-faint:  #6f6f80;
    --paper:      #faf7f0;
    --paper-raised: #fffdf7;
    --rule:       #e2dcce;
    --rule-soft:  #ede7d8;
    --accent:     #2d5a4a;
    --accent-soft:#5a8073;
    --accent-deep:#1d3d31;
    --gold:       #b8893a;
    --gold-bg:    #fdf4d9;
  }}
  * {{ box-sizing: border-box; }}
  html, body {{
    margin: 0; padding: 0;
    background: var(--paper); color: var(--ink);
    font-family: "Source Serif Pro", "Iowan Old Style", "Charter", Georgia, serif;
    font-size: 18px; line-height: 1.62; -webkit-font-smoothing: antialiased;
  }}
  .ui {{ font-family: "Inter", system-ui, -apple-system, "Segoe UI", sans-serif; }}
  a {{ color: var(--accent); text-underline-offset: 2px; }}

  .site-header {{
    border-bottom: 1px solid var(--rule);
    background: var(--paper-raised);
    padding: 16px 24px;
  }}
  .site-header-inner {{
    max-width: 1080px; margin: 0 auto;
    display: flex; align-items: center; justify-content: space-between;
  }}
  .site-brand {{ font-family: "Inter", sans-serif; font-weight: 600; font-size: 13px;
    letter-spacing: 0.06em; color: var(--ink); text-decoration: none; }}
  .site-brand .dot {{ color: var(--accent); }}
  .site-tag {{ font-family: "Inter", sans-serif; font-size: 11px; color: var(--ink-faint);
    text-transform: uppercase; letter-spacing: 0.12em; }}

  main {{ max-width: 760px; margin: 0 auto; padding: 56px 24px 96px; }}

  .breadcrumb {{ font-size: 12px; color: var(--ink-faint); text-transform: uppercase;
    letter-spacing: 0.1em; margin-bottom: 22px; }}
  .breadcrumb a {{ color: var(--ink-soft); text-decoration: none; }}

  .sermon-title {{
    font-size: 44px; font-weight: 600; line-height: 1.1; letter-spacing: -0.015em;
    margin: 0 0 16px;
  }}
  .sermon-cite {{
    font-family: "Inter", sans-serif; font-size: 13px; color: var(--ink-faint);
    display: flex; gap: 18px; flex-wrap: wrap; margin-bottom: 28px;
  }}
  .sermon-cite strong {{ color: var(--ink-soft); font-weight: 600; }}

  .audio-player {{
    background: var(--paper-raised);
    border: 1px solid var(--rule);
    border-radius: 10px;
    padding: 18px 22px;
    display: flex; align-items: center; gap: 16px; margin-bottom: 36px;
  }}
  .play-button {{
    width: 48px; height: 48px; border-radius: 50%;
    background: var(--accent); border: 0; cursor: pointer;
    display: flex; align-items: center; justify-content: center;
    color: #fff; flex-shrink: 0;
  }}
  .play-button:hover {{ background: var(--accent-deep); }}
  .audio-meta {{ font-family: "Inter", sans-serif; font-size: 13px; color: var(--ink-soft); flex: 1; }}
  .audio-track {{ height: 4px; background: var(--rule); border-radius: 2px; margin-top: 6px;
    position: relative; cursor: pointer; }}
  .audio-progress {{ position: absolute; left: 0; top: 0; bottom: 0; width: 0;
    background: var(--accent); border-radius: 2px; transition: width 0.1s linear; }}
  .audio-duration {{ font-family: "Inter", sans-serif; font-size: 12px; color: var(--ink-faint); }}
  audio#sermonAudio {{ display: none; }}

  .thesis-hero {{
    border-left: 3px solid var(--accent);
    background: var(--paper-raised);
    padding: 22px 28px;
    margin: 0 0 36px;
    font-size: 22px; line-height: 1.5; color: var(--ink); font-style: italic;
  }}
  .thesis-label {{ display: block; font-family: "Inter", sans-serif; font-size: 10px;
    letter-spacing: 0.15em; text-transform: uppercase; color: var(--accent);
    font-style: normal; margin-bottom: 8px; }}

  .facts-strip {{
    display: grid; grid-template-columns: repeat(3, 1fr); gap: 18px;
    border-top: 1px solid var(--rule); border-bottom: 1px solid var(--rule);
    padding: 18px 0; margin-bottom: 40px;
  }}
  .fact-label {{ font-family: "Inter", sans-serif; font-size: 10px;
    text-transform: uppercase; letter-spacing: 0.12em; color: var(--ink-faint); margin-bottom: 4px; }}
  .fact-value {{ font-size: 15px; font-weight: 600; color: var(--ink-soft); }}

  .page-section {{ margin: 0 0 48px; }}
  .section-eyebrow {{ font-family: "Inter", sans-serif; font-size: 11px;
    letter-spacing: 0.16em; text-transform: uppercase; color: var(--accent); margin-bottom: 8px; }}
  .section-title-h2 {{ font-size: 28px; font-weight: 600; line-height: 1.18;
    margin: 0 0 14px; letter-spacing: -0.01em; }}
  .section-lede {{ color: var(--ink-soft); margin: 0 0 24px; font-size: 17px; line-height: 1.6; }}
  .section-body p {{ margin: 0 0 16px; }}

  .stewardship-notice {{
    background: var(--gold-bg);
    border: 1px solid #ead8a0; border-left: 4px solid var(--gold);
    border-radius: 6px; padding: 20px 24px;
    font-size: 15px; line-height: 1.6; color: var(--ink-soft);
  }}
  .stewardship-notice strong {{ color: var(--ink); }}

  .church-card {{
    background: var(--paper-raised); border: 1px solid var(--rule);
    border-radius: 12px; padding: 28px 32px;
    display: grid; grid-template-columns: 1fr auto; gap: 24px; align-items: center;
  }}
  .church-name {{ font-size: 22px; font-weight: 600; margin-bottom: 4px; }}
  .church-addr {{ font-family: "Inter", sans-serif; font-size: 13px; color: var(--ink-soft); line-height: 1.5; }}
  .visit-cta {{ display: inline-block; font-family: "Inter", sans-serif; font-size: 14px;
    font-weight: 600; background: var(--accent); color: #fff;
    padding: 12px 22px; border-radius: 6px; text-decoration: none; white-space: nowrap; }}
  .visit-cta:hover {{ background: var(--accent-deep); }}

  .page-footer {{
    max-width: 760px; margin: 64px auto 32px; padding: 0 24px;
    font-family: "Inter", sans-serif; font-size: 12px; color: var(--ink-faint); line-height: 1.6;
  }}
  .page-footer a {{ color: var(--ink-soft); }}

  @media (max-width: 600px) {{
    .sermon-title {{ font-size: 32px; }}
    .facts-strip {{ grid-template-columns: 1fr; }}
    .church-card {{ grid-template-columns: 1fr; }}
  }}
</style>
</head>
<body>

<header class="site-header">
  <div class="site-header-inner">
    <a class="site-brand" href="/">Sermon Steward<span class="dot">.</span></a>
    <span class="site-tag">Customer Sample · Cross of Grace</span>
  </div>
</header>

<main>
  <div class="breadcrumb"><a href="/samples">Samples</a> · {series}</div>

  <h1 class="sermon-title">{title}</h1>

  <div class="sermon-cite">
    <span><strong>{primary_text}</strong></span>
    <span>{date_long}</span>
    <span>Pastor Ricky Alcantar</span>
  </div>

  <div class="audio-player">
    <button class="play-button" id="audioPlayBtn" type="button" aria-label="Play sermon audio">
      <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor"><path id="audioIconPath" d="M8 5v14l11-7z"/></svg>
    </button>
    <div class="audio-meta">
      <div>Listen to the sermon</div>
      <div class="audio-track" id="audioTrack"><div class="audio-progress" id="audioProgress"></div></div>
    </div>
    <span class="audio-duration ui" id="audioDuration">— : —</span>
    <audio id="sermonAudio" preload="metadata" src="{audio_url_escaped}"></audio>
  </div>

  <blockquote class="thesis-hero">
    <span class="thesis-label">Thesis</span>
    {thesis}
  </blockquote>

  <div class="facts-strip">
    <div class="fact"><div class="fact-label">Series</div><div class="fact-value">{series}</div></div>
    <div class="fact"><div class="fact-label">Primary text</div><div class="fact-value">{primary_text}</div></div>
    <div class="fact"><div class="fact-label">Preacher</div><div class="fact-value">Ricky Alcantar</div></div>
  </div>

  <section class="page-section">
    <div class="section-eyebrow">What the sermon argues</div>
    <h2 class="section-title-h2">The shape of the message</h2>
    <div class="section-body">
      <p>{abstract}</p>
    </div>
  </section>

  <section class="page-section">
    <div class="stewardship-notice">
      <strong>Full stewardship surfaces forthcoming.</strong> This sample shows the sermon hero, audio, and abstract. The complete Sermon Steward treatment — small-group questions, daily readings, weekly prayer, family conversation, couples' guide, memory verse — is generated by Haiku 4.5 in the customer's own preaching voice and renders here automatically. See <a href="/growing-in-christ">Growing in Christ</a> for an example with the full surface stack in place.
    </div>
  </section>

  <section class="page-section">
    <div class="section-eyebrow">Where this was preached</div>
    <h2 class="section-title-h2">About the church</h2>
    <div class="church-card">
      <div>
        <div class="church-name">Cross of Grace Church</div>
        <div class="church-addr">
          El Paso, Texas<br>
          Pastored by Ricky Alcantar<br>
          <a href="https://www.crossofgrace.net" target="_blank" rel="noopener">crossofgrace.net</a>
        </div>
      </div>
      <a href="https://www.crossofgrace.net/sermons/{slug_full}/" target="_blank" rel="noopener" class="visit-cta ui">Open on Cross of Grace →</a>
    </div>
  </section>
</main>

<footer class="page-footer">
  Sample sermon page · stewarded by <a href="/">Sermon Steward</a>. Audio served from Cross of Grace's hosting platform.
</footer>

<script>
(function () {{
  var audio = document.getElementById('sermonAudio');
  var btn = document.getElementById('audioPlayBtn');
  var iconPath = document.getElementById('audioIconPath');
  var track = document.getElementById('audioTrack');
  var progress = document.getElementById('audioProgress');
  var durEl = document.getElementById('audioDuration');
  if (!audio || !btn) return;
  var PLAY_D = 'M8 5v14l11-7z';
  var PAUSE_D = 'M6 5h4v14H6zm8 0h4v14h-4z';
  function fmt(s) {{
    if (!isFinite(s) || s < 0) return '0:00';
    var m = Math.floor(s / 60);
    var r = Math.floor(s % 60);
    return m + ':' + String(r).padStart(2, '0');
  }}
  btn.addEventListener('click', function () {{ audio.paused ? audio.play() : audio.pause(); }});
  audio.addEventListener('play', function () {{ iconPath.setAttribute('d', PAUSE_D); btn.setAttribute('aria-label', 'Pause sermon audio'); }});
  audio.addEventListener('pause', function () {{ iconPath.setAttribute('d', PLAY_D); btn.setAttribute('aria-label', 'Play sermon audio'); }});
  audio.addEventListener('loadedmetadata', function () {{ if (isFinite(audio.duration)) durEl.textContent = fmt(audio.duration); }});
  audio.addEventListener('timeupdate', function () {{
    if (audio.duration) {{
      progress.style.width = (audio.currentTime / audio.duration * 100) + '%';
      durEl.textContent = fmt(audio.currentTime) + ' / ' + fmt(audio.duration);
    }}
  }});
  track.addEventListener('click', function (e) {{
    var rect = track.getBoundingClientRect();
    if (audio.duration) audio.currentTime = audio.duration * ((e.clientX - rect.left) / rect.width);
  }});
}})();
</script>
</body>
</html>
"""


def main() -> int:
    url = os.environ["SUPABASE_URL"]
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or os.environ["SUPABASE_KEY"]
    sb = create_client(url, key)

    rows = sb.table("sermons").select(
        "id, slug, date, title, primary_text, audio_url, main_thesis, abstract, series_name"
    ).in_("id", SERMON_IDS).execute().data

    by_id = {r["id"]: r for r in rows}

    for sid in SERMON_IDS:
        s = by_id.get(sid)
        if not s:
            print(f"missing: {sid}")
            continue
        slug = file_slug(s["slug"])
        out = OUTPUT_DIR / f"{slug}.html"
        # Short abstract for OG/meta (first sentence-ish)
        abstract_short = (s["abstract"] or "").split(". ")[0]
        if len(abstract_short) > 200:
            abstract_short = abstract_short[:197] + "…"
        # Audio URL escaping for HTML attribute — & needs to become &amp;
        audio_escaped = (s["audio_url"] or "").replace("&", "&amp;")
        page = TEMPLATE.format(
            title=s["title"],
            primary_text=s["primary_text"] or "",
            date_iso=s["date"],
            date_long=fmt_date_long(s["date"]),
            series=s.get("series_name") or "Frontera Church",
            thesis=s["main_thesis"] or s["abstract"] or "",
            abstract=s["abstract"] or "",
            abstract_short=abstract_short,
            audio_url_escaped=audio_escaped,
            slug_full=s["slug"],
        )
        out.write_text(page, encoding="utf-8")
        print(f"wrote {out} ({len(page):,} chars)")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
