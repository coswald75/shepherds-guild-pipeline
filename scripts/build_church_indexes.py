"""
Generate per-church sermon-index pages.

Surfaces emitted per church:
  - /<url_slug>/sermons/                       all-sermons listing, paginated 25/page
  - /<url_slug>/sermons/scripture/             66-book grid with counts
  - /<url_slug>/sermons/scripture/<book>/      per-book sermon listing, paginated
  - /<url_slug>/sermons/doctrine/              16 doctrinal-loci cards
  - /<url_slug>/sermons/doctrine/<locus>/      per-locus listing with editorial blurb
  - /<url_slug>/sermons/series/                preaching-series cards, most-recent first
  - /<url_slug>/sermons/series/<series>/       per-series listing in preaching order
"""

from __future__ import annotations

import html
import math
import re
import shutil
import sys
from collections import defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(REPO_ROOT / ".env", override=True)

from sermon_page_renderer import queries as q  # noqa: E402
from bible_books import (  # noqa: E402
    BOOKS, OT_BOOKS, NT_BOOKS, BOOK_ORDER, canonical_book, book_slug,
)
from doctrinal_loci import (  # noqa: E402
    LOCUS_NAMES, LOCUS_SET, LOCUS_BLURB, locus_slug,
)

SERMON_STEWARD_REPO = Path("/Users/dad/shepherds-guild/sermon-steward")

CHURCH_IDS = [
    "c121e66b-777d-4568-89d3-9ceea258061b",  # Providence
    "f1fc9898-fafd-4289-b6af-ce99dfde23d6",  # Cross of Grace
]

PAGE_SIZE = 25


CSS_BASE = """\
  :root {
    --bg: #fbf8f1;
    --bg-card: #ffffff;
    --ink: #1a1a1a;
    --ink-soft: #4a4a4a;
    --ink-faint: #828282;
    --rule: #e6e1d3;
    --accent: #c4452f;
    --accent-deep: #9a3624;
    --sans: 'Inter', system-ui, -apple-system, sans-serif;
  }
  * { box-sizing: border-box; }
  html, body {
    margin: 0; padding: 0; background: var(--bg); color: var(--ink);
    font-family: var(--sans); font-size: 17px; line-height: 1.55;
    -webkit-font-smoothing: antialiased;
  }
  a { color: var(--accent); text-decoration: none; }
  a:hover { color: var(--accent-deep); }
  .site-header { padding: 24px 32px; border-bottom: 1px solid var(--rule); }
  .wordmark { font-weight: 800; font-size: 22px; letter-spacing: -0.02em; color: var(--ink); }
  .wordmark .dot { color: var(--accent); }
  main { max-width: 860px; margin: 0 auto; padding: 56px 32px 96px; }
  .breadcrumb { font-size: 13px; color: var(--ink-faint); margin-bottom: 16px; }
  .breadcrumb a { color: var(--ink-soft); text-decoration: underline; text-underline-offset: 3px; }
  h1 {
    font-size: clamp(2rem, 4.5vw, 3rem); font-weight: 800;
    letter-spacing: -0.03em; line-height: 1.05;
    margin: 0 0 8px;
  }
  .location { color: var(--ink-soft); font-size: 16px; margin: 0 0 40px; }
  h2 {
    font-size: 13px; font-weight: 600; letter-spacing: 0.08em;
    text-transform: uppercase; color: var(--accent);
    margin: 32px 0 16px; padding-bottom: 12px;
    border-bottom: 1px solid var(--rule);
  }
  h2:first-of-type { margin-top: 0; }
  .count { color: var(--ink-faint); font-weight: 400; letter-spacing: 0; text-transform: none; font-size: 13px; margin-left: 8px; }
  ul.sermons { list-style: none; margin: 0; padding: 0; }
  ul.sermons li {
    padding: 18px 0;
    border-bottom: 1px solid var(--rule);
  }
  ul.sermons li:last-child { border-bottom: 0; }
  .sermon-title { font-size: 19px; font-weight: 600; margin: 0 0 4px; }
  .sermon-title a { color: var(--ink); }
  .sermon-title a:hover { color: var(--accent); }
  .sermon-meta { font-size: 14px; color: var(--ink-soft); }
  .sermon-meta .dot-sep { margin: 0 8px; color: var(--ink-faint); }
  .sermon-meta .series { color: var(--accent-deep); font-weight: 500; }
  .sermon-meta .badge {
    display: inline-block; padding: 1px 7px; margin-left: 8px;
    border-radius: 10px; background: rgba(196, 69, 47, 0.08);
    color: var(--accent-deep); font-size: 11px; font-weight: 600;
    letter-spacing: 0.02em; text-transform: uppercase;
  }
  footer {
    padding: 24px 32px; font-size: 13px; color: var(--ink-faint);
    text-align: center; border-top: 1px solid var(--rule);
  }
  footer a { color: var(--ink-soft); }
  .note {
    background: #fff; border: 1px solid var(--rule); border-radius: 10px;
    padding: 14px 18px; margin: 0 0 32px; font-size: 14px; color: var(--ink-soft);
  }
  .browse-by {
    display: flex; flex-wrap: wrap; gap: 8px; align-items: center;
    margin: 0 0 32px; font-size: 13px; color: var(--ink-faint);
  }
  .browse-by .label { letter-spacing: 0.06em; text-transform: uppercase; }
  .browse-by a {
    padding: 6px 12px; border: 1px solid var(--rule); border-radius: 16px;
    color: var(--ink-soft); background: var(--bg-card);
  }
  .browse-by a:hover { border-color: var(--accent); color: var(--accent); }
  .browse-by a[aria-current="page"] {
    border-color: var(--accent); color: var(--accent); font-weight: 600;
  }
  nav.pagination {
    display: flex; align-items: center; justify-content: space-between;
    gap: 16px; margin-top: 40px; padding-top: 24px;
    border-top: 1px solid var(--rule); font-size: 14px;
  }
  nav.pagination a, nav.pagination span.disabled {
    padding: 8px 14px; border: 1px solid var(--rule); border-radius: 6px;
    background: var(--bg-card);
  }
  nav.pagination a { color: var(--ink); }
  nav.pagination a:hover { border-color: var(--accent); color: var(--accent); }
  nav.pagination span.disabled { color: var(--ink-faint); background: transparent; border-style: dashed; }
  nav.pagination .page-indicator { color: var(--ink-soft); font-variant-numeric: tabular-nums; }
  .book-grid {
    display: grid; grid-template-columns: repeat(auto-fill, minmax(160px, 1fr));
    gap: 10px; margin: 0 0 8px;
  }
  .book-grid a, .book-grid span.empty {
    display: flex; align-items: baseline; justify-content: space-between;
    gap: 8px; padding: 12px 14px;
    border: 1px solid var(--rule); border-radius: 8px;
    background: var(--bg-card); color: var(--ink);
    font-size: 14px; font-weight: 500;
  }
  .book-grid a:hover { border-color: var(--accent); color: var(--accent); }
  .book-grid a .n { color: var(--ink-faint); font-weight: 400; font-variant-numeric: tabular-nums; }
  .book-grid a:hover .n { color: var(--accent); }
  .book-grid span.empty { color: var(--ink-faint); background: transparent; border-style: dashed; cursor: default; }
  .book-grid span.empty .n { font-weight: 400; }
  .locus-grid {
    display: grid; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
    gap: 16px; margin: 0;
  }
  .locus-card {
    display: block; padding: 18px 20px;
    border: 1px solid var(--rule); border-radius: 10px;
    background: var(--bg-card); color: var(--ink);
  }
  .locus-card:hover { border-color: var(--accent); }
  .locus-card .head {
    display: flex; align-items: baseline; justify-content: space-between;
    gap: 8px; margin-bottom: 8px;
  }
  .locus-card .name { font-size: 17px; font-weight: 700; letter-spacing: -0.01em; }
  .locus-card:hover .name { color: var(--accent); }
  .locus-card .n {
    color: var(--ink-faint); font-size: 13px; font-weight: 500;
    font-variant-numeric: tabular-nums;
  }
  .locus-card .blurb {
    font-size: 14px; line-height: 1.5; color: var(--ink-soft);
    margin: 0;
  }
  .locus-blurb {
    background: #fff; border: 1px solid var(--rule); border-radius: 10px;
    padding: 18px 22px; margin: 0 0 32px;
    font-size: 16px; line-height: 1.6; color: var(--ink-soft);
  }
  .locus-blurb em { color: var(--ink); font-style: italic; }
  .series-grid {
    display: grid; grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
    gap: 14px; margin: 0;
  }
  .series-card {
    display: block; padding: 16px 18px;
    border: 1px solid var(--rule); border-radius: 10px;
    background: var(--bg-card); color: var(--ink);
  }
  .series-card:hover { border-color: var(--accent); }
  .series-card .name {
    display: block; font-size: 17px; font-weight: 700;
    letter-spacing: -0.01em; margin-bottom: 6px;
  }
  .series-card:hover .name { color: var(--accent); }
  .series-card .meta {
    font-size: 13px; color: var(--ink-faint);
    font-variant-numeric: tabular-nums;
  }
"""


PAGE = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Sermons{title_page_suffix} — {church_name} · Sermon Steward</title>
<meta name="description" content="Every stewarded sermon from {church_name}{loc_phrase}, with discussion, reading, and memory cards.">
<link rel="canonical" href="https://sermonsteward.com{canonical_path}">
{rel_prev_next}<meta property="og:type" content="website">
<meta property="og:title" content="Sermons — {church_name}">
<meta property="og:url" content="https://sermonsteward.com{canonical_path}">
<meta property="og:site_name" content="Sermon Steward">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet">
<style>
{css}</style>
</head>
<body>

<header class="site-header">
  <a class="wordmark" href="/">Sermon Steward<span class="dot">.</span></a>
</header>

<main>
  <div class="breadcrumb"><a href="/">Sermon Steward</a> · {crumb_church} · Sermons</div>
  <h1>{church_name}</h1>
  <p class="location">{location}</p>
  {intro_note}{browse_by}<h2>Sermons<span class="count">({count} total{page_of_suffix})</span></h2>
  <div style="display:flex;align-items:center;gap:12px;background:#f0d4cc;border:1px solid #e3a08c;border-radius:12px;padding:13px 18px;margin:12px 0 20px;color:#9a3624;font-weight:600;font-size:15.5px;line-height:1.4;">
    <span aria-hidden="true" style="font-size:20px;flex:none;line-height:1;">&darr;</span>
    <span>Click any sermon below to see everything we add &mdash; the full transcript, discussion questions, devotionals, article ideas, and more.</span>
  </div>
  <ul class="sermons">
{rows}
  </ul>
{pagination_nav}</main>

<footer>
  Built by pastors, for pastors. · <a href="/">Sermon Steward</a>
</footer>

</body>
</html>
"""


ROW = """    <li>
      <p class="sermon-title"><a href="/{url_slug}/sermons/{slug}">{title}</a></p>
      <p class="sermon-meta">{date_human}{primary_text_block}{series_block}{primary_book_badge}</p>
    </li>"""


INTRO_NOTE = (
    '<div class="note">A simple index of every stewarded sermon. Each page '
    "includes the full transcript, its member-facing resources, and the "
    "related-teaching graph. Other ways to browse below.</div>\n  "
)


def _browse_by_nav(url_slug: str, here: str) -> str:
    """Render the Browse-by chip row. `here` ∈ {'all', 'scripture', 'doctrine', 'series'}."""
    items = [
        ("all",       f"/{url_slug}/sermons/",           "All sermons"),
        ("scripture", f"/{url_slug}/sermons/scripture/", "Scripture"),
        ("doctrine",  f"/{url_slug}/sermons/doctrine/",  "Doctrine"),
        ("series",    f"/{url_slug}/sermons/series/",    "Series"),
    ]
    parts = ['<div class="browse-by"><span class="label">Browse:</span>']
    for key, href, label in items:
        cur = ' aria-current="page"' if key == here else ""
        parts.append(f'<a href="{href}"{cur}>{label}</a>')
    parts.append("</div>\n  ")
    return "".join(parts)


SCRIPTURE_INDEX_PAGE = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Browse by Scripture — {church_name} · Sermon Steward</title>
<meta name="description" content="Sermons from {church_name}{loc_phrase} grouped by book of the Bible.">
<link rel="canonical" href="https://sermonsteward.com/{url_slug}/sermons/scripture">
<meta property="og:type" content="website">
<meta property="og:title" content="Browse by Scripture — {church_name}">
<meta property="og:url" content="https://sermonsteward.com/{url_slug}/sermons/scripture">
<meta property="og:site_name" content="Sermon Steward">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet">
<style>
{css}</style>
</head>
<body>

<header class="site-header">
  <a class="wordmark" href="/">Sermon Steward<span class="dot">.</span></a>
</header>

<main>
  <div class="breadcrumb"><a href="/">Sermon Steward</a> · {crumb_church} · <a href="/{url_slug}/sermons/">Sermons</a> · Scripture</div>
  <h1>Browse by Scripture</h1>
  <p class="location">{cited_count} sermons across {books_with_sermons} books of the Bible</p>
  {browse_by}<h2>Old Testament</h2>
  <div class="book-grid">
{ot_tiles}
  </div>
  <h2>New Testament</h2>
  <div class="book-grid">
{nt_tiles}
  </div>
</main>

<footer>
  Built by pastors, for pastors. · <a href="/">Sermon Steward</a>
</footer>

</body>
</html>
"""


BOOK_TILE_LINK = (
    '    <a href="/{url_slug}/sermons/scripture/{book_slug}/">'
    '<span class="name">{book}</span><span class="n">{count}</span></a>'
)
BOOK_TILE_EMPTY = (
    '    <span class="empty"><span class="name">{book}</span>'
    '<span class="n">0</span></span>'
)


DOCTRINE_INDEX_PAGE = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Browse by Doctrine — {church_name} · Sermon Steward</title>
<meta name="description" content="Sermons from {church_name}{loc_phrase} grouped by 16 doctrinal loci — Christology, Soteriology, Sanctification, and more.">
<link rel="canonical" href="https://sermonsteward.com/{url_slug}/sermons/doctrine">
<meta property="og:type" content="website">
<meta property="og:title" content="Browse by Doctrine — {church_name}">
<meta property="og:url" content="https://sermonsteward.com/{url_slug}/sermons/doctrine">
<meta property="og:site_name" content="Sermon Steward">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet">
<style>
{css}</style>
</head>
<body>

<header class="site-header">
  <a class="wordmark" href="/">Sermon Steward<span class="dot">.</span></a>
</header>

<main>
  <div class="breadcrumb"><a href="/">Sermon Steward</a> · {crumb_church} · <a href="/{url_slug}/sermons/">Sermons</a> · Doctrine</div>
  <h1>Browse by Doctrine</h1>
  <p class="location">{total_count} sermons across 16 doctrinal loci</p>
  {browse_by}<div class="locus-grid">
{cards}
  </div>
</main>

<footer>
  Built by pastors, for pastors. · <a href="/">Sermon Steward</a>
</footer>

</body>
</html>
"""


LOCUS_CARD = """\
    <a class="locus-card" href="/{url_slug}/sermons/doctrine/{locus_slug}/">
      <div class="head"><span class="name">{name}</span><span class="n">{count} sermon{count_plural}</span></div>
      <p class="blurb">{blurb_short}</p>
    </a>"""


SERIES_INDEX_PAGE = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Browse by Series — {church_name} · Sermon Steward</title>
<meta name="description" content="Sermons from {church_name}{loc_phrase} grouped by preaching series.">
<link rel="canonical" href="https://sermonsteward.com/{url_slug}/sermons/series">
<meta property="og:type" content="website">
<meta property="og:title" content="Browse by Series — {church_name}">
<meta property="og:url" content="https://sermonsteward.com/{url_slug}/sermons/series">
<meta property="og:site_name" content="Sermon Steward">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet">
<style>
{css}</style>
</head>
<body>

<header class="site-header">
  <a class="wordmark" href="/">Sermon Steward<span class="dot">.</span></a>
</header>

<main>
  <div class="breadcrumb"><a href="/">Sermon Steward</a> · {crumb_church} · <a href="/{url_slug}/sermons/">Sermons</a> · Series</div>
  <h1>Browse by Series</h1>
  <p class="location">{total_count} sermons across {series_count} preaching series</p>
  {browse_by}<div class="series-grid">
{cards}
  </div>
</main>

<footer>
  Built by pastors, for pastors. · <a href="/">Sermon Steward</a>
</footer>

</body>
</html>
"""


SERIES_CARD = """\
    <a class="series-card" href="/{url_slug}/sermons/series/{series_slug}/">
      <span class="name">{name}</span>
      <span class="meta">{count} sermon{count_plural}{date_range_block}</span>
    </a>"""


SERIES_DETAIL_PAGE = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{series}{title_page_suffix} — Sermons from {church_name} · Sermon Steward</title>
<meta name="description" content="Sermons from the {series} series at {church_name}.">
<link rel="canonical" href="https://sermonsteward.com{canonical_path}">
{rel_prev_next}<meta property="og:type" content="website">
<meta property="og:title" content="{series} — Sermons from {church_name}">
<meta property="og:url" content="https://sermonsteward.com{canonical_path}">
<meta property="og:site_name" content="Sermon Steward">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet">
<style>
{css}</style>
</head>
<body>

<header class="site-header">
  <a class="wordmark" href="/">Sermon Steward<span class="dot">.</span></a>
</header>

<main>
  <div class="breadcrumb"><a href="/">Sermon Steward</a> · {crumb_church} · <a href="/{url_slug}/sermons/">Sermons</a> · <a href="/{url_slug}/sermons/series/">Series</a> · {series}</div>
  <h1>{series}</h1>
  <p class="location">{count} sermon{count_plural} from {church_name}{page_of_suffix}</p>
  <h2>Sermons<span class="count">(in preaching order)</span></h2>
  <ul class="sermons">
{rows}
  </ul>
{pagination_nav}</main>

<footer>
  Built by pastors, for pastors. · <a href="/">Sermon Steward</a>
</footer>

</body>
</html>
"""


DOCTRINE_LOCUS_PAGE = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{locus}{title_page_suffix} — Sermons from {church_name} · Sermon Steward</title>
<meta name="description" content="Sermons from {church_name}{loc_phrase} engaging the doctrine of {locus}.">
<link rel="canonical" href="https://sermonsteward.com{canonical_path}">
{rel_prev_next}<meta property="og:type" content="website">
<meta property="og:title" content="{locus} — Sermons from {church_name}">
<meta property="og:url" content="https://sermonsteward.com{canonical_path}">
<meta property="og:site_name" content="Sermon Steward">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet">
<style>
{css}</style>
</head>
<body>

<header class="site-header">
  <a class="wordmark" href="/">Sermon Steward<span class="dot">.</span></a>
</header>

<main>
  <div class="breadcrumb"><a href="/">Sermon Steward</a> · {crumb_church} · <a href="/{url_slug}/sermons/">Sermons</a> · <a href="/{url_slug}/sermons/doctrine/">Doctrine</a> · {locus}</div>
  <h1>{locus}</h1>
  <p class="location">{count} sermon{count_plural} from {church_name}{page_of_suffix}</p>
  {blurb_block}<h2>Sermons</h2>
  <ul class="sermons">
{rows}
  </ul>
{pagination_nav}</main>

<footer>
  Built by pastors, for pastors. · <a href="/">Sermon Steward</a>
</footer>

</body>
</html>
"""


SCRIPTURE_BOOK_PAGE = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{book}{title_page_suffix} — Sermons from {church_name} · Sermon Steward</title>
<meta name="description" content="Sermons from {church_name}{loc_phrase} engaging the book of {book}.">
<link rel="canonical" href="https://sermonsteward.com{canonical_path}">
{rel_prev_next}<meta property="og:type" content="website">
<meta property="og:title" content="{book} — Sermons from {church_name}">
<meta property="og:url" content="https://sermonsteward.com{canonical_path}">
<meta property="og:site_name" content="Sermon Steward">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet">
<style>
{css}</style>
</head>
<body>

<header class="site-header">
  <a class="wordmark" href="/">Sermon Steward<span class="dot">.</span></a>
</header>

<main>
  <div class="breadcrumb"><a href="/">Sermon Steward</a> · {crumb_church} · <a href="/{url_slug}/sermons/">Sermons</a> · <a href="/{url_slug}/sermons/scripture/">Scripture</a> · {book}</div>
  <h1>{book}</h1>
  <p class="location">{count} sermon{count_plural} from {church_name}{page_of_suffix}</p>
  <h2>Sermons<span class="count">(primary-text sermons listed first)</span></h2>
  <ul class="sermons">
{rows}
  </ul>
{pagination_nav}</main>

<footer>
  Built by pastors, for pastors. · <a href="/">Sermon Steward</a>
</footer>

</body>
</html>
"""


def _page_url(base_path: str, page_num: int) -> str:
    """Site-relative path for page N of a paginated surface.

    base_path is the page-1 URL (e.g. '/<slug>/sermons' or '/<slug>/sermons/scripture/romans').
    Page 1 returns base_path as-is; pages 2+ append '/page/N'.
    """
    if page_num == 1:
        return base_path
    return f"{base_path}/page/{page_num}"


def _build_pagination_nav(base_path: str, current_page: int, total_pages: int) -> str:
    if total_pages <= 1:
        return ""
    if current_page > 1:
        prev_target = _page_url(base_path, current_page - 1) + "/"
        prev_html = f'<a href="{prev_target}" rel="prev">← Previous</a>'
    else:
        prev_html = '<span class="disabled">← Previous</span>'
    if current_page < total_pages:
        next_target = _page_url(base_path, current_page + 1) + "/"
        next_html = f'<a href="{next_target}" rel="next">Next →</a>'
    else:
        next_html = '<span class="disabled">Next →</span>'
    indicator = f'<span class="page-indicator">Page {current_page} of {total_pages}</span>'
    return (
        '  <nav class="pagination" aria-label="Sermon listing pagination">\n'
        f"    {prev_html}\n"
        f"    {indicator}\n"
        f"    {next_html}\n"
        "  </nav>\n"
    )


def _build_rel_prev_next(base_path: str, current_page: int, total_pages: int) -> str:
    if total_pages <= 1:
        return ""
    lines = []
    if current_page > 1:
        lines.append(
            f'<link rel="prev" href="https://sermonsteward.com{_page_url(base_path, current_page - 1)}">'
        )
    if current_page < total_pages:
        lines.append(
            f'<link rel="next" href="https://sermonsteward.com{_page_url(base_path, current_page + 1)}">'
        )
    return "\n".join(lines) + "\n" if lines else ""


_MONTHS = [
    "Jan", "Feb", "Mar", "Apr", "May", "Jun",
    "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
]


def _format_date(d: str) -> str:
    """ '2026-02-22' → 'Feb 22, 2026' """
    y, m, day = d.split("-")
    return f"{_MONTHS[int(m) - 1]} {int(day)}, {y}"


def _format_location(address) -> str:
    if not address:
        return ""
    bits = []
    locality = address.get("locality")
    region = address.get("region")
    if locality:
        bits.append(locality)
    if region:
        bits.append(region)
    return ", ".join(bits)


def _gather_books_for_church(
    sb, preacher_ids: list[str], url_slug: str
) -> tuple[dict[str, list[dict]], dict[str, str | None]]:
    """Map canonical-book → [sermon dicts] for sermons that have a rendered HTML
    page on disk in the sermon-steward repo.

    Returns:
        (book_to_sermons, sermon_primary_book)
        book_to_sermons[book] = list of sermon dicts, sorted by date desc then title.
        sermon_primary_book[sermon_id] = canonical book of sermon.primary_text, or None.

    A sermon appears for book B if either:
      - its primary_text resolves to B (its main passage), OR
      - any unit citation reference resolves to B (the sermon engages B).
    """
    sermons_dir = SERMON_STEWARD_REPO / url_slug / "sermons"

    # 1. Pull church sermons, broadly. We want anything with a slug — date and
    # primary_text may be NULL (date-unknown sermons still appear per plan).
    sermons = (
        sb.table("sermons")
        .select("id, title, date, slug, primary_text, series_name")
        .in_("preacher_id", preacher_ids)
        .eq("unlisted", False)
        .not_.is_("slug", "null")
        .execute().data or []
    )

    # 2. Cross-check disk: only include sermons whose HTML file exists.
    sermons = [s for s in sermons if (sermons_dir / f"{s['slug']}.html").exists()]
    sermon_by_id = {s["id"]: s for s in sermons}
    sermon_ids = list(sermon_by_id)

    # 3. primary_text → canonical book per sermon
    sermon_primary_book: dict[str, str | None] = {
        sid: canonical_book(s.get("primary_text")) for sid, s in sermon_by_id.items()
    }

    # 4. Pull units per sermon. PostgREST caps responses at 1000 rows, so we
    # both chunk the IN-list AND paginate within each chunk — a single chunk
    # of 100 sermons hits the cap on its own (~30 sermons × ~30 units = 900+).
    CHUNK = 100
    units_by_sermon: dict[str, set[str]] = defaultdict(set)
    for i in range(0, len(sermon_ids), CHUNK):
        offset = 0
        while True:
            rows = (
                sb.table("units")
                .select("id, sermon_id")
                .in_("sermon_id", sermon_ids[i:i + CHUNK])
                .range(offset, offset + 999)
                .execute().data or []
            )
            for r in rows:
                units_by_sermon[r["sermon_id"]].add(r["id"])
            if len(rows) < 1000:
                break
            offset += 1000

    all_unit_ids = sorted({u for s in units_by_sermon.values() for u in s})

    # Citations may be many rows per unit; pull in unit-id chunks of ~250.
    UCHUNK = 250
    unit_to_books: dict[str, set[str]] = defaultdict(set)
    for i in range(0, len(all_unit_ids), UCHUNK):
        offset = 0
        while True:
            rows = (
                sb.table("citations")
                .select("unit_id, reference")
                .in_("unit_id", all_unit_ids[i:i + UCHUNK])
                .not_.is_("reference", "null")
                .range(offset, offset + 999)
                .execute().data or []
            )
            for r in rows:
                book = canonical_book(r["reference"])
                if book:
                    unit_to_books[r["unit_id"]].add(book)
            if len(rows) < 1000:
                break
            offset += 1000

    # 5. Roll up unit-level books to sermon-level
    sermon_books: dict[str, set[str]] = defaultdict(set)
    for sid, unit_ids in units_by_sermon.items():
        for uid in unit_ids:
            sermon_books[sid].update(unit_to_books.get(uid, ()))
        # primary_text contributes too
        pb = sermon_primary_book.get(sid)
        if pb:
            sermon_books[sid].add(pb)

    # 6. Invert to book → [sermon] and sort each list
    book_to_sermons: dict[str, list[dict]] = defaultdict(list)
    for sid, books in sermon_books.items():
        s = sermon_by_id[sid]
        for b in books:
            book_to_sermons[b].append(s)

    def _sort_key(s):
        # Primary-text sermons before citation-only ones for the book?
        # We don't know the book here — sort by date desc only, "primary text"
        # ordering is applied later when we know the book context.
        d = s.get("date") or ""  # NULLs sort to the bottom of "date desc"
        return (d == "", -1 * (int(d.replace("-", "")) if d else 0), (s.get("title") or "").lower())

    for b in book_to_sermons:
        book_to_sermons[b].sort(key=_sort_key)

    return dict(book_to_sermons), sermon_primary_book


def _render_scripture_surface(
    c: dict,
    book_to_sermons: dict[str, list[dict]],
    sermon_primary_book: dict[str, str | None],
    crumb_church: str,
    location: str,
    loc_phrase: str,
) -> int:
    """Emit /<url_slug>/sermons/scripture/ index + per-book pages.

    Returns the total number of pages written.
    """
    url_slug = c["url_slug"]
    scripture_root = SERMON_STEWARD_REPO / url_slug / "sermons" / "scripture"
    scripture_root.mkdir(parents=True, exist_ok=True)

    # Total distinct sermons cited (across all books)
    all_cited_sermons = {s["id"] for sermons in book_to_sermons.values() for s in sermons}
    books_with_sermons = sum(1 for b in BOOKS if book_to_sermons.get(b))

    # --- book index ---------------------------------------------------------
    def _tiles(book_list: list[str]) -> str:
        out = []
        for book in book_list:
            count = len(book_to_sermons.get(book, []))
            if count:
                out.append(BOOK_TILE_LINK.format(
                    url_slug=url_slug, book_slug=book_slug(book),
                    book=html.escape(book), count=count,
                ))
            else:
                out.append(BOOK_TILE_EMPTY.format(book=html.escape(book)))
        return "\n".join(out)

    index_html = SCRIPTURE_INDEX_PAGE.format(
        css=CSS_BASE,
        church_name=html.escape(c["name"] or ""),
        crumb_church=crumb_church,
        url_slug=url_slug,
        cited_count=len(all_cited_sermons),
        books_with_sermons=books_with_sermons,
        loc_phrase=html.escape(loc_phrase),
        browse_by=_browse_by_nav(url_slug, here="scripture"),
        ot_tiles=_tiles(OT_BOOKS),
        nt_tiles=_tiles(NT_BOOKS),
    )
    (scripture_root / "index.html").write_text(index_html, encoding="utf-8")
    pages_written = 1

    # Track which book dirs we keep; prune stale ones at end.
    keep_book_dirs = set()

    # --- per-book listings --------------------------------------------------
    for book in BOOKS:
        sermons = book_to_sermons.get(book, [])
        if not sermons:
            continue
        bslug = book_slug(book)
        keep_book_dirs.add(bslug)
        book_dir = scripture_root / bslug
        book_dir.mkdir(parents=True, exist_ok=True)

        # Re-sort with primary-text sermons first (so the most relevant ones
        # for the book lead). Within each group, keep the date-desc order.
        primary_first = [s for s in sermons if sermon_primary_book.get(s["id"]) == book]
        rest = [s for s in sermons if sermon_primary_book.get(s["id"]) != book]
        ordered = primary_first + rest

        total = len(ordered)
        total_pages = max(1, math.ceil(total / PAGE_SIZE))
        base_path = f"/{url_slug}/sermons/scripture/{bslug}"

        # Prune stale page/N/ subdirs from earlier runs if any
        page_root = book_dir / "page"
        if page_root.exists():
            for child in page_root.iterdir():
                if child.is_dir() and child.name.isdigit():
                    n = int(child.name)
                    if n < 2 or n > total_pages:
                        shutil.rmtree(child)
            if total_pages == 1 and not any(page_root.iterdir()):
                page_root.rmdir()

        for page_num in range(1, total_pages + 1):
            start = (page_num - 1) * PAGE_SIZE
            chunk = ordered[start:start + PAGE_SIZE]

            rows_html = []
            for s in chunk:
                pt = s.get("primary_text") or ""
                series = s.get("series_name") or ""
                pt_block = (
                    f'<span class="dot-sep">·</span>{html.escape(pt)}'
                    if pt else ""
                )
                series_block = (
                    f'<span class="dot-sep">·</span><span class="series">{html.escape(series)}</span>'
                    if series else ""
                )
                badge = (
                    '<span class="badge">primary text</span>'
                    if sermon_primary_book.get(s["id"]) == book else ""
                )
                date_h = _format_date(s["date"]) if s.get("date") else "Date unknown"
                rows_html.append(ROW.format(
                    url_slug=url_slug,
                    slug=s["slug"],
                    title=html.escape(s["title"] or "(untitled)"),
                    date_human=date_h,
                    primary_text_block=pt_block,
                    series_block=series_block,
                    primary_book_badge=badge,
                ))

            canonical_path = _page_url(base_path, page_num)
            title_page_suffix = f" (Page {page_num} of {total_pages})" if page_num > 1 else ""
            page_of_suffix = f" · page {page_num} of {total_pages}" if total_pages > 1 else ""

            html_doc = SCRIPTURE_BOOK_PAGE.format(
                css=CSS_BASE,
                book=html.escape(book),
                church_name=html.escape(c["name"] or ""),
                crumb_church=crumb_church,
                url_slug=url_slug,
                canonical_path=canonical_path,
                rel_prev_next=_build_rel_prev_next(base_path, page_num, total_pages),
                loc_phrase=html.escape(loc_phrase),
                title_page_suffix=title_page_suffix,
                page_of_suffix=page_of_suffix,
                count=total,
                count_plural="" if total == 1 else "s",
                rows="\n".join(rows_html),
                pagination_nav=_build_pagination_nav(base_path, page_num, total_pages),
            )

            if page_num == 1:
                out_path = book_dir / "index.html"
            else:
                out_path = book_dir / "page" / str(page_num) / "index.html"
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(html_doc, encoding="utf-8")
            pages_written += 1

    # Prune stale book directories from earlier runs (sermon dropped from book)
    for child in scripture_root.iterdir():
        if child.is_dir() and child.name not in keep_book_dirs:
            shutil.rmtree(child)

    return pages_written


def _series_slug(name: str) -> str:
    """'Kingdom Come' → 'kingdom-come', "Paul's First Missionary Journey" → 'pauls-first-missionary-journey'."""
    s = name.lower()
    s = re.sub(r"[^a-z0-9\s-]", "", s)
    s = re.sub(r"\s+", "-", s)
    s = re.sub(r"-+", "-", s)
    return s.strip("-") or "series"


def _format_date_short(d: str) -> str:
    """'2026-02-22' → 'Feb 2026' (for series-card date ranges)."""
    y, m, _ = d.split("-")
    return f"{_MONTHS[int(m) - 1]} {y}"


def _gather_series_for_church(
    sb, preacher_ids: list[str], url_slug: str
) -> dict[str, list[dict]]:
    """Map series_name → [sermon dicts] for sermons with a rendered HTML page
    and a non-NULL series_name.

    Within each series, sermons are sorted by date ASCENDING (oldest first,
    so Part 1 precedes Part 2). Sermons with NULL date sort to the end of
    their series.
    """
    sermons_dir = SERMON_STEWARD_REPO / url_slug / "sermons"
    sermons = (
        sb.table("sermons")
        .select("id, title, date, slug, primary_text, series_name")
        .in_("preacher_id", preacher_ids)
        .eq("unlisted", False)
        .not_.is_("slug", "null")
        .not_.is_("series_name", "null")
        .execute().data or []
    )
    sermons = [s for s in sermons if (sermons_dir / f"{s['slug']}.html").exists()]

    series_to_sermons: dict[str, list[dict]] = defaultdict(list)
    for s in sermons:
        series_to_sermons[s["series_name"]].append(s)

    def _sort_key_asc(s):
        d = s.get("date") or ""
        # Sermons with no date sort to the end (date-asc); use a big sentinel.
        return (d == "", int(d.replace("-", "")) if d else 99999999, (s.get("title") or "").lower())

    for name in series_to_sermons:
        series_to_sermons[name].sort(key=_sort_key_asc)

    return dict(series_to_sermons)


def _render_series_surface(
    c: dict,
    series_to_sermons: dict[str, list[dict]],
    crumb_church: str,
    loc_phrase: str,
) -> int:
    """Emit /<url_slug>/sermons/series/ index + per-series pages."""
    url_slug = c["url_slug"]
    series_root = SERMON_STEWARD_REPO / url_slug / "sermons" / "series"
    series_root.mkdir(parents=True, exist_ok=True)

    all_sermons_in_series = sum(len(s) for s in series_to_sermons.values())

    # Order index cards by most-recent sermon in each series, desc.
    def _series_recency(name_sermons):
        _, sermons = name_sermons
        dates = [s["date"] for s in sermons if s.get("date")]
        return max(dates) if dates else "0000-00-00"

    ordered_series = sorted(
        series_to_sermons.items(),
        key=_series_recency,
        reverse=True,
    )

    # --- series index ---
    cards = []
    for name, sermons in ordered_series:
        count = len(sermons)
        dates = sorted(s["date"] for s in sermons if s.get("date"))
        if dates and dates[0] != dates[-1]:
            date_range = f" · {_format_date_short(dates[0])} – {_format_date_short(dates[-1])}"
        elif dates:
            date_range = f" · {_format_date_short(dates[0])}"
        else:
            date_range = ""
        cards.append(SERIES_CARD.format(
            url_slug=url_slug,
            series_slug=_series_slug(name),
            name=html.escape(name),
            count=count,
            count_plural="" if count == 1 else "s",
            date_range_block=date_range,
        ))

    index_html = SERIES_INDEX_PAGE.format(
        css=CSS_BASE,
        church_name=html.escape(c["name"] or ""),
        crumb_church=crumb_church,
        url_slug=url_slug,
        total_count=all_sermons_in_series,
        series_count=len(series_to_sermons),
        loc_phrase=html.escape(loc_phrase),
        browse_by=_browse_by_nav(url_slug, here="series"),
        cards="\n".join(cards),
    )
    (series_root / "index.html").write_text(index_html, encoding="utf-8")
    pages_written = 1

    keep_series_dirs = set()

    # --- per-series listings ---
    for name, sermons in series_to_sermons.items():
        sslug = _series_slug(name)
        keep_series_dirs.add(sslug)
        series_dir = series_root / sslug
        series_dir.mkdir(parents=True, exist_ok=True)

        total = len(sermons)
        total_pages = max(1, math.ceil(total / PAGE_SIZE))
        base_path = f"/{url_slug}/sermons/series/{sslug}"

        page_root = series_dir / "page"
        if page_root.exists():
            for child in page_root.iterdir():
                if child.is_dir() and child.name.isdigit():
                    n = int(child.name)
                    if n < 2 or n > total_pages:
                        shutil.rmtree(child)
            if total_pages == 1 and not any(page_root.iterdir()):
                page_root.rmdir()

        for page_num in range(1, total_pages + 1):
            start = (page_num - 1) * PAGE_SIZE
            chunk = sermons[start:start + PAGE_SIZE]

            rows_html = []
            for s in chunk:
                pt = s.get("primary_text") or ""
                pt_block = (
                    f'<span class="dot-sep">·</span>{html.escape(pt)}' if pt else ""
                )
                # Inside a series page, don't repeat the series name on every row.
                series_block = ""
                date_h = _format_date(s["date"]) if s.get("date") else "Date unknown"
                rows_html.append(ROW.format(
                    url_slug=url_slug,
                    slug=s["slug"],
                    title=html.escape(s["title"] or "(untitled)"),
                    date_human=date_h,
                    primary_text_block=pt_block,
                    series_block=series_block,
                    primary_book_badge="",
                ))

            canonical_path = _page_url(base_path, page_num)
            title_page_suffix = f" (Page {page_num} of {total_pages})" if page_num > 1 else ""
            page_of_suffix = f" · page {page_num} of {total_pages}" if total_pages > 1 else ""

            html_doc = SERIES_DETAIL_PAGE.format(
                css=CSS_BASE,
                series=html.escape(name),
                church_name=html.escape(c["name"] or ""),
                crumb_church=crumb_church,
                url_slug=url_slug,
                canonical_path=canonical_path,
                rel_prev_next=_build_rel_prev_next(base_path, page_num, total_pages),
                loc_phrase=html.escape(loc_phrase),
                title_page_suffix=title_page_suffix,
                page_of_suffix=page_of_suffix,
                count=total,
                count_plural="" if total == 1 else "s",
                rows="\n".join(rows_html),
                pagination_nav=_build_pagination_nav(base_path, page_num, total_pages),
            )

            if page_num == 1:
                out_path = series_dir / "index.html"
            else:
                out_path = series_dir / "page" / str(page_num) / "index.html"
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(html_doc, encoding="utf-8")
            pages_written += 1

    # Prune stale series directories
    for child in series_root.iterdir():
        if child.is_dir() and child.name not in keep_series_dirs:
            shutil.rmtree(child)

    return pages_written


def _gather_loci_for_church(
    sb, preacher_ids: list[str], url_slug: str
) -> dict[str, list[dict]]:
    """Map canonical-locus → [sermon dicts] for sermons with a rendered HTML page
    whose units' doctrinal_loci arrays mention that locus.

    Loci come from the Sonnet decomposition's per-unit `doctrinal_loci text[]`.
    Only the 16 canonical loci (matching VALID_LOCI in pipeline_batch.py) are
    counted; unknown values are silently dropped.
    """
    sermons_dir = SERMON_STEWARD_REPO / url_slug / "sermons"

    sermons = (
        sb.table("sermons")
        .select("id, title, date, slug, primary_text, series_name")
        .in_("preacher_id", preacher_ids)
        .eq("unlisted", False)
        .not_.is_("slug", "null")
        .execute().data or []
    )
    sermons = [s for s in sermons if (sermons_dir / f"{s['slug']}.html").exists()]
    sermon_by_id = {s["id"]: s for s in sermons}
    sermon_ids = list(sermon_by_id)

    # Pull units with doctrinal_loci, chunked AND paginated within each chunk.
    CHUNK = 100
    sermon_loci: dict[str, set[str]] = defaultdict(set)
    for i in range(0, len(sermon_ids), CHUNK):
        offset = 0
        while True:
            rows = (
                sb.table("units")
                .select("sermon_id, doctrinal_loci")
                .in_("sermon_id", sermon_ids[i:i + CHUNK])
                .range(offset, offset + 999)
                .execute().data or []
            )
            for r in rows:
                for locus in r.get("doctrinal_loci") or []:
                    if locus in LOCUS_SET:
                        sermon_loci[r["sermon_id"]].add(locus)
            if len(rows) < 1000:
                break
            offset += 1000

    # Invert sermon→loci to locus→[sermons]
    locus_to_sermons: dict[str, list[dict]] = defaultdict(list)
    for sid, loci in sermon_loci.items():
        s = sermon_by_id[sid]
        for locus in loci:
            locus_to_sermons[locus].append(s)

    def _sort_key(s):
        d = s.get("date") or ""
        return (d == "", -1 * (int(d.replace("-", "")) if d else 0), (s.get("title") or "").lower())

    for locus in locus_to_sermons:
        locus_to_sermons[locus].sort(key=_sort_key)

    return dict(locus_to_sermons)


def _render_doctrine_surface(
    c: dict,
    locus_to_sermons: dict[str, list[dict]],
    crumb_church: str,
    loc_phrase: str,
) -> int:
    """Emit /<url_slug>/sermons/doctrine/ index + per-locus pages.

    Returns the total number of pages written.
    """
    url_slug = c["url_slug"]
    doctrine_root = SERMON_STEWARD_REPO / url_slug / "sermons" / "doctrine"
    doctrine_root.mkdir(parents=True, exist_ok=True)

    all_engaged_sermons = {
        s["id"] for sermons in locus_to_sermons.values() for s in sermons
    }

    # --- doctrine index ---
    cards = []
    for name in LOCUS_NAMES:
        sermons = locus_to_sermons.get(name, [])
        count = len(sermons)
        blurb = LOCUS_BLURB[name]
        # Truncate blurb at first sentence for the card preview.
        first_sentence = blurb.split(". ", 1)[0].rstrip(".") + "."
        cards.append(LOCUS_CARD.format(
            url_slug=url_slug,
            locus_slug=locus_slug(name),
            name=html.escape(name),
            count=count,
            count_plural="" if count == 1 else "s",
            blurb_short=html.escape(first_sentence),
        ))

    index_html = DOCTRINE_INDEX_PAGE.format(
        css=CSS_BASE,
        church_name=html.escape(c["name"] or ""),
        crumb_church=crumb_church,
        url_slug=url_slug,
        total_count=len(all_engaged_sermons),
        loc_phrase=html.escape(loc_phrase),
        browse_by=_browse_by_nav(url_slug, here="doctrine"),
        cards="\n".join(cards),
    )
    (doctrine_root / "index.html").write_text(index_html, encoding="utf-8")
    pages_written = 1

    keep_locus_dirs = set()

    # --- per-locus listings ---
    for name in LOCUS_NAMES:
        sermons = locus_to_sermons.get(name, [])
        if not sermons:
            continue
        lslug = locus_slug(name)
        keep_locus_dirs.add(lslug)
        locus_dir = doctrine_root / lslug
        locus_dir.mkdir(parents=True, exist_ok=True)

        total = len(sermons)
        total_pages = max(1, math.ceil(total / PAGE_SIZE))
        base_path = f"/{url_slug}/sermons/doctrine/{lslug}"

        # Prune stale page/ subdirs
        page_root = locus_dir / "page"
        if page_root.exists():
            for child in page_root.iterdir():
                if child.is_dir() and child.name.isdigit():
                    n = int(child.name)
                    if n < 2 or n > total_pages:
                        shutil.rmtree(child)
            if total_pages == 1 and not any(page_root.iterdir()):
                page_root.rmdir()

        for page_num in range(1, total_pages + 1):
            start = (page_num - 1) * PAGE_SIZE
            chunk = sermons[start:start + PAGE_SIZE]

            rows_html = []
            for s in chunk:
                pt = s.get("primary_text") or ""
                series = s.get("series_name") or ""
                pt_block = (
                    f'<span class="dot-sep">·</span>{html.escape(pt)}' if pt else ""
                )
                series_block = (
                    f'<span class="dot-sep">·</span><span class="series">{html.escape(series)}</span>'
                    if series else ""
                )
                date_h = _format_date(s["date"]) if s.get("date") else "Date unknown"
                rows_html.append(ROW.format(
                    url_slug=url_slug,
                    slug=s["slug"],
                    title=html.escape(s["title"] or "(untitled)"),
                    date_human=date_h,
                    primary_text_block=pt_block,
                    series_block=series_block,
                    primary_book_badge="",
                ))

            canonical_path = _page_url(base_path, page_num)
            title_page_suffix = f" (Page {page_num} of {total_pages})" if page_num > 1 else ""
            page_of_suffix = f" · page {page_num} of {total_pages}" if total_pages > 1 else ""
            # Editorial blurb appears only on page 1 (it's a curator's hello).
            blurb_block = (
                f'<div class="locus-blurb">{html.escape(LOCUS_BLURB[name])}</div>\n  '
                if page_num == 1 else ""
            )

            html_doc = DOCTRINE_LOCUS_PAGE.format(
                css=CSS_BASE,
                locus=html.escape(name),
                church_name=html.escape(c["name"] or ""),
                crumb_church=crumb_church,
                url_slug=url_slug,
                canonical_path=canonical_path,
                rel_prev_next=_build_rel_prev_next(base_path, page_num, total_pages),
                loc_phrase=html.escape(loc_phrase),
                title_page_suffix=title_page_suffix,
                page_of_suffix=page_of_suffix,
                blurb_block=blurb_block,
                count=total,
                count_plural="" if total == 1 else "s",
                rows="\n".join(rows_html),
                pagination_nav=_build_pagination_nav(base_path, page_num, total_pages),
            )

            if page_num == 1:
                out_path = locus_dir / "index.html"
            else:
                out_path = locus_dir / "page" / str(page_num) / "index.html"
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(html_doc, encoding="utf-8")
            pages_written += 1

    # Prune stale locus directories
    for child in doctrine_root.iterdir():
        if child.is_dir() and child.name not in keep_locus_dirs:
            shutil.rmtree(child)

    return pages_written


def main() -> int:
    sb = q.get_supabase()

    # Single query: pull churches with their sermons + artifact-bundle counts.
    churches = (
        sb.table("churches")
        .select("id, name, url_slug, address")
        .in_("id", CHURCH_IDS)
        .execute()
        .data
        or []
    )

    # For each church, pull its preachers' sermons with full 6-artifact bundles.
    preachers = (
        sb.table("preachers")
        .select("id, church_id")
        .in_("church_id", CHURCH_IDS)
        .execute()
        .data
        or []
    )
    preacher_by_church: dict[str, list[str]] = {}
    for p in preachers:
        preacher_by_church.setdefault(p["church_id"], []).append(p["id"])

    for c in churches:
        preacher_ids = preacher_by_church.get(c["id"], [])
        if not preacher_ids:
            continue
        sermons = (
            sb.table("sermons")
            .select("id, title, date, slug, primary_text, series_name")
            .in_("preacher_id", preacher_ids)
            .eq("unlisted", False)
            .not_.is_("main_thesis", "null")
            .not_.is_("date", "null")
            .not_.is_("slug", "null")
            .order("date", desc=True)
            .order("title")
            .execute()
            .data
            or []
        )
        # Filter to those with the full 6-artifact pastoral bundle (or more —
        # newer sermons may carry imperatives_indicatives + sermon_scraps too).
        # Existing 145-sermon corpus has exactly 6 artifacts each; new sermons
        # post-2026-05-18 have 8. Using >= keeps both ends happy.
        # Supabase PostgREST has a server-side max_rows cap (default 1000) that
        # client `.limit()` can't override. With 200+ sermons × 6 artifacts we
        # exceed it. Paginate per-chunk-of-sermon-ids so every row is captured.
        sermon_id_list = [s["id"] for s in sermons]
        artifact_counts = []
        CHUNK = 100  # 100 sermons × 8 artifact types max = 800 rows, well under 1000
        for i in range(0, len(sermon_id_list), CHUNK):
            page = (
                sb.table("sermon_artifacts")
                .select("sermon_id, artifact_type")
                .in_("sermon_id", sermon_id_list[i:i + CHUNK])
                .execute()
                .data
                or []
            )
            artifact_counts.extend(page)
        bundle: dict[str, set[str]] = {}
        for row in artifact_counts:
            bundle.setdefault(row["sermon_id"], set()).add(row["artifact_type"])
        # Require the original 6 pastoral artifacts. The 2 newer ones are bonus.
        REQUIRED_PASTORAL = {
            "small_group_questions", "daily_readings",
            "family_card", "couples_guide", "memory_verse",
        }
        publishable = [
            s for s in sermons
            if REQUIRED_PASTORAL.issubset(bundle.get(s["id"], set()))
        ]

        location = _format_location(c.get("address"))
        loc_phrase = f" in {location}" if location else ""
        # Only link the church name in the breadcrumb if a home page exists
        # at /<url_slug>/index.html (otherwise we'd ship a 404 link).
        home_exists = (SERMON_STEWARD_REPO / c["url_slug"] / "index.html").exists()
        if home_exists:
            crumb_church = f'<a href="/{c["url_slug"]}/">{html.escape(c["name"] or "")}</a>'
        else:
            crumb_church = html.escape(c["name"] or "")

        total_count = len(publishable)
        total_pages = max(1, math.ceil(total_count / PAGE_SIZE))

        # Prune stale page/N/ directories from a prior run that produced more
        # pages than this one would. Anything outside [2, total_pages] is dead.
        page_root = SERMON_STEWARD_REPO / c["url_slug"] / "sermons" / "page"
        if page_root.exists():
            for child in page_root.iterdir():
                if not child.is_dir() or not child.name.isdigit():
                    continue
                n = int(child.name)
                if n < 2 or n > total_pages:
                    shutil.rmtree(child)
            # If pagination collapsed back to a single page, remove the empty parent.
            if total_pages == 1 and not any(page_root.iterdir()):
                page_root.rmdir()

        for page_num in range(1, total_pages + 1):
            start = (page_num - 1) * PAGE_SIZE
            chunk = publishable[start:start + PAGE_SIZE]

            rows_html = []
            for s in chunk:
                primary_text = s.get("primary_text") or ""
                series = s.get("series_name") or ""
                pt_block = (
                    f'<span class="dot-sep">·</span>{html.escape(primary_text)}'
                    if primary_text else ""
                )
                series_block = (
                    f'<span class="dot-sep">·</span><span class="series">{html.escape(series)}</span>'
                    if series else ""
                )
                rows_html.append(ROW.format(
                    url_slug=c["url_slug"],
                    slug=s["slug"],
                    title=html.escape(s["title"] or "(untitled)"),
                    date_human=_format_date(s["date"]),
                    primary_text_block=pt_block,
                    series_block=series_block,
                    primary_book_badge="",
                ))

            base_path = f"/{c['url_slug']}/sermons"
            canonical_path = _page_url(base_path, page_num)
            title_page_suffix = (
                f" (Page {page_num} of {total_pages})" if page_num > 1 else ""
            )
            page_of_suffix = (
                f" · page {page_num} of {total_pages}" if total_pages > 1 else ""
            )
            intro_note = INTRO_NOTE if page_num == 1 else ""
            browse_by = _browse_by_nav(c["url_slug"], here="all") if page_num == 1 else ""

            page_html = PAGE.format(
                css=CSS_BASE,
                church_name=html.escape(c["name"] or ""),
                crumb_church=crumb_church,
                url_slug=c["url_slug"],
                canonical_path=canonical_path,
                rel_prev_next=_build_rel_prev_next(base_path, page_num, total_pages),
                location=html.escape(location or "Sermon archive"),
                loc_phrase=html.escape(loc_phrase),
                title_page_suffix=title_page_suffix,
                page_of_suffix=page_of_suffix,
                intro_note=intro_note,
                browse_by=browse_by,
                count=total_count,
                rows="\n".join(rows_html),
                pagination_nav=_build_pagination_nav(base_path, page_num, total_pages),
            )

            if page_num == 1:
                out_path = SERMON_STEWARD_REPO / c["url_slug"] / "sermons" / "index.html"
            else:
                out_path = (
                    SERMON_STEWARD_REPO / c["url_slug"] / "sermons"
                    / "page" / str(page_num) / "index.html"
                )
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(page_html, encoding="utf-8")

        print(
            f"wrote {SERMON_STEWARD_REPO / c['url_slug'] / 'sermons'}/  "
            f"({total_count} sermons across {total_pages} page"
            f"{'s' if total_pages != 1 else ''})"
        )

        # --- scripture surface ---
        book_to_sermons, sermon_primary_book = _gather_books_for_church(
            sb, preacher_ids, c["url_slug"]
        )
        scripture_pages = _render_scripture_surface(
            c, book_to_sermons, sermon_primary_book,
            crumb_church=crumb_church,
            location=location,
            loc_phrase=loc_phrase,
        )
        books_touched = sum(1 for b in BOOKS if book_to_sermons.get(b))
        total_cited = len({s["id"] for sermons in book_to_sermons.values() for s in sermons})
        print(
            f"wrote {SERMON_STEWARD_REPO / c['url_slug'] / 'sermons' / 'scripture'}/  "
            f"({total_cited} sermons across {books_touched} books, "
            f"{scripture_pages} pages)"
        )

        # --- doctrine surface ---
        locus_to_sermons = _gather_loci_for_church(sb, preacher_ids, c["url_slug"])
        doctrine_pages = _render_doctrine_surface(
            c, locus_to_sermons,
            crumb_church=crumb_church,
            loc_phrase=loc_phrase,
        )
        loci_touched = sum(1 for n in LOCUS_NAMES if locus_to_sermons.get(n))
        total_engaged = len({s["id"] for sermons in locus_to_sermons.values() for s in sermons})
        print(
            f"wrote {SERMON_STEWARD_REPO / c['url_slug'] / 'sermons' / 'doctrine'}/  "
            f"({total_engaged} sermons across {loci_touched} loci, "
            f"{doctrine_pages} pages)"
        )

        # --- series surface ---
        series_to_sermons = _gather_series_for_church(sb, preacher_ids, c["url_slug"])
        series_pages = _render_series_surface(
            c, series_to_sermons,
            crumb_church=crumb_church,
            loc_phrase=loc_phrase,
        )
        total_in_series = sum(len(s) for s in series_to_sermons.values())
        print(
            f"wrote {SERMON_STEWARD_REPO / c['url_slug'] / 'sermons' / 'series'}/  "
            f"({total_in_series} sermons across {len(series_to_sermons)} series, "
            f"{series_pages} pages)"
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
