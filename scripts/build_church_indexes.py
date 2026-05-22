"""
Generate per-church sermon-index pages (V0).

Renders one `<repo>/<url_slug>/sermons/index.html` per church, listing every
fully-stewarded sermon as a link. Minimal style — matches the Sermon Steward
aesthetic (Inter, cream, brick-red). Designed to be replaced later with a
richer surface (filtering by topic, series view, etc.).
"""

from __future__ import annotations

import html
import math
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(REPO_ROOT / ".env", override=True)

from sermon_page_renderer import queries as q  # noqa: E402

SERMON_STEWARD_REPO = Path("/Users/dad/shepherds-guild/sermon-steward")

CHURCH_IDS = [
    "c121e66b-777d-4568-89d3-9ceea258061b",  # Providence
    "f1fc9898-fafd-4289-b6af-ce99dfde23d6",  # Cross of Grace
]

PAGE_SIZE = 25


PAGE = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Sermons{title_page_suffix} — {church_name} · Sermon Steward</title>
<meta name="description" content="Every stewarded sermon from {church_name}{loc_phrase}, with discussion, reading, prayer, and memory cards.">
<link rel="canonical" href="https://sermonsteward.com{canonical_path}">
{rel_prev_next}<meta property="og:type" content="website">
<meta property="og:title" content="Sermons — {church_name}">
<meta property="og:url" content="https://sermonsteward.com{canonical_path}">
<meta property="og:site_name" content="Sermon Steward">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet">
<style>
  :root {{
    --bg: #fbf8f1;
    --bg-card: #ffffff;
    --ink: #1a1a1a;
    --ink-soft: #4a4a4a;
    --ink-faint: #828282;
    --rule: #e6e1d3;
    --accent: #c4452f;
    --accent-deep: #9a3624;
    --sans: 'Inter', system-ui, -apple-system, sans-serif;
  }}
  * {{ box-sizing: border-box; }}
  html, body {{
    margin: 0; padding: 0; background: var(--bg); color: var(--ink);
    font-family: var(--sans); font-size: 17px; line-height: 1.55;
    -webkit-font-smoothing: antialiased;
  }}
  a {{ color: var(--accent); text-decoration: none; }}
  a:hover {{ color: var(--accent-deep); }}
  .site-header {{ padding: 24px 32px; border-bottom: 1px solid var(--rule); }}
  .wordmark {{ font-weight: 800; font-size: 22px; letter-spacing: -0.02em; color: var(--ink); }}
  .wordmark .dot {{ color: var(--accent); }}
  main {{ max-width: 860px; margin: 0 auto; padding: 56px 32px 96px; }}
  .breadcrumb {{ font-size: 13px; color: var(--ink-faint); margin-bottom: 16px; }}
  .breadcrumb a {{ color: var(--ink-soft); text-decoration: underline; text-underline-offset: 3px; }}
  h1 {{
    font-size: clamp(2rem, 4.5vw, 3rem); font-weight: 800;
    letter-spacing: -0.03em; line-height: 1.05;
    margin: 0 0 8px;
  }}
  .location {{ color: var(--ink-soft); font-size: 16px; margin: 0 0 40px; }}
  h2 {{
    font-size: 13px; font-weight: 600; letter-spacing: 0.08em;
    text-transform: uppercase; color: var(--accent);
    margin: 0 0 16px; padding-bottom: 12px;
    border-bottom: 1px solid var(--rule);
  }}
  .count {{ color: var(--ink-faint); font-weight: 400; letter-spacing: 0; text-transform: none; font-size: 13px; margin-left: 8px; }}
  ul.sermons {{ list-style: none; margin: 0; padding: 0; }}
  ul.sermons li {{
    padding: 18px 0;
    border-bottom: 1px solid var(--rule);
  }}
  ul.sermons li:last-child {{ border-bottom: 0; }}
  .sermon-title {{ font-size: 19px; font-weight: 600; margin: 0 0 4px; }}
  .sermon-title a {{ color: var(--ink); }}
  .sermon-title a:hover {{ color: var(--accent); }}
  .sermon-meta {{ font-size: 14px; color: var(--ink-soft); }}
  .sermon-meta .dot-sep {{ margin: 0 8px; color: var(--ink-faint); }}
  .sermon-meta .series {{ color: var(--accent-deep); font-weight: 500; }}
  footer {{
    padding: 24px 32px; font-size: 13px; color: var(--ink-faint);
    text-align: center; border-top: 1px solid var(--rule);
  }}
  footer a {{ color: var(--ink-soft); }}
  .note {{
    background: #fff; border: 1px solid var(--rule); border-radius: 10px;
    padding: 14px 18px; margin: 0 0 32px; font-size: 14px; color: var(--ink-soft);
  }}
  nav.pagination {{
    display: flex; align-items: center; justify-content: space-between;
    gap: 16px; margin-top: 40px; padding-top: 24px;
    border-top: 1px solid var(--rule); font-size: 14px;
  }}
  nav.pagination a, nav.pagination span.disabled {{
    padding: 8px 14px; border: 1px solid var(--rule); border-radius: 6px;
    background: var(--bg-card);
  }}
  nav.pagination a {{ color: var(--ink); }}
  nav.pagination a:hover {{ border-color: var(--accent); color: var(--accent); }}
  nav.pagination span.disabled {{ color: var(--ink-faint); background: transparent; border-style: dashed; }}
  nav.pagination .page-indicator {{ color: var(--ink-soft); font-variant-numeric: tabular-nums; }}
</style>
</head>
<body>

<header class="site-header">
  <a class="wordmark" href="/">Sermon Steward<span class="dot">.</span></a>
</header>

<main>
  <div class="breadcrumb"><a href="/">Sermon Steward</a> · {crumb_church} · Sermons</div>
  <h1>{church_name}</h1>
  <p class="location">{location}</p>
  {intro_note}<h2>Sermons<span class="count">({count} total{page_of_suffix})</span></h2>
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
      <p class="sermon-meta">{date_human}{primary_text_block}{series_block}</p>
    </li>"""


INTRO_NOTE = (
    '<div class="note">A simple index of every stewarded sermon. Each page '
    "includes the full transcript, six member-facing artifacts, and the "
    "related-teaching graph. Richer browsing surfaces (by topic, by series, "
    "by passage) are on the way.</div>\n  "
)


def _page_url(url_slug: str, page_num: int) -> str:
    """Site-relative path for a given page (leading slash, no trailing slash on root)."""
    if page_num == 1:
        return f"/{url_slug}/sermons"
    return f"/{url_slug}/sermons/page/{page_num}"


def _build_pagination_nav(url_slug: str, current_page: int, total_pages: int) -> str:
    if total_pages <= 1:
        return ""
    if current_page > 1:
        prev_target = _page_url(url_slug, current_page - 1) + "/"
        prev_html = f'<a href="{prev_target}" rel="prev">← Previous</a>'
    else:
        prev_html = '<span class="disabled">← Previous</span>'
    if current_page < total_pages:
        next_target = _page_url(url_slug, current_page + 1) + "/"
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


def _build_rel_prev_next(url_slug: str, current_page: int, total_pages: int) -> str:
    if total_pages <= 1:
        return ""
    lines = []
    if current_page > 1:
        lines.append(
            f'<link rel="prev" href="https://sermonsteward.com{_page_url(url_slug, current_page - 1)}">'
        )
    if current_page < total_pages:
        lines.append(
            f'<link rel="next" href="https://sermonsteward.com{_page_url(url_slug, current_page + 1)}">'
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
            "small_group_questions", "daily_readings", "prayer_prompt",
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
                ))

            canonical_path = _page_url(c["url_slug"], page_num)
            title_page_suffix = (
                f" (Page {page_num} of {total_pages})" if page_num > 1 else ""
            )
            page_of_suffix = (
                f" · page {page_num} of {total_pages}" if total_pages > 1 else ""
            )
            intro_note = INTRO_NOTE if page_num == 1 else ""

            page_html = PAGE.format(
                church_name=html.escape(c["name"] or ""),
                crumb_church=crumb_church,
                url_slug=c["url_slug"],
                canonical_path=canonical_path,
                rel_prev_next=_build_rel_prev_next(c["url_slug"], page_num, total_pages),
                location=html.escape(location or "Sermon archive"),
                loc_phrase=html.escape(loc_phrase),
                title_page_suffix=title_page_suffix,
                page_of_suffix=page_of_suffix,
                intro_note=intro_note,
                count=total_count,
                rows="\n".join(rows_html),
                pagination_nav=_build_pagination_nav(c["url_slug"], page_num, total_pages),
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

    return 0


if __name__ == "__main__":
    sys.exit(main())
