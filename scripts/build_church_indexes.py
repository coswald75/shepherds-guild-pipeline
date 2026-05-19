"""
Generate per-church sermon-index pages (V0).

Renders one `<repo>/<url_slug>/sermons/index.html` per church, listing every
fully-stewarded sermon as a link. Minimal style — matches the Sermon Steward
aesthetic (Inter, cream, brick-red). Designed to be replaced later with a
richer surface (filtering by topic, series view, etc.).
"""

from __future__ import annotations

import html
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


PAGE = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Sermons — {church_name} · Sermon Steward</title>
<meta name="description" content="Every stewarded sermon from {church_name}{loc_phrase}, with discussion, reading, prayer, and memory cards.">
<link rel="canonical" href="https://sermonsteward.com/{url_slug}/sermons">
<meta property="og:type" content="website">
<meta property="og:title" content="Sermons — {church_name}">
<meta property="og:url" content="https://sermonsteward.com/{url_slug}/sermons">
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
  <div class="note">A simple index of every stewarded sermon. Each page includes the full transcript, six member-facing artifacts, and the related-teaching graph. Richer browsing surfaces (by topic, by series, by passage) are on the way.</div>
  <h2>Sermons<span class="count">({count} total)</span></h2>
  <ul class="sermons">
{rows}
  </ul>
</main>

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
        artifact_counts = (
            sb.table("sermon_artifacts")
            .select("sermon_id, artifact_type")
            .in_("sermon_id", [s["id"] for s in sermons])
            .execute()
            .data
            or []
        )
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

        rows_html = []
        for s in publishable:
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

        location = _format_location(c.get("address"))
        loc_phrase = f" in {location}" if location else ""
        # Only link the church name in the breadcrumb if a home page exists
        # at /<url_slug>/index.html (otherwise we'd ship a 404 link).
        home_exists = (SERMON_STEWARD_REPO / c["url_slug"] / "index.html").exists()
        if home_exists:
            crumb_church = f'<a href="/{c["url_slug"]}/">{html.escape(c["name"] or "")}</a>'
        else:
            crumb_church = html.escape(c["name"] or "")
        page_html = PAGE.format(
            church_name=html.escape(c["name"] or ""),
            crumb_church=crumb_church,
            url_slug=c["url_slug"],
            location=html.escape(location or "Sermon archive"),
            loc_phrase=html.escape(loc_phrase),
            count=len(publishable),
            rows="\n".join(rows_html),
        )

        out_dir = SERMON_STEWARD_REPO / c["url_slug"] / "sermons"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / "index.html"
        out_path.write_text(page_html, encoding="utf-8")
        print(f"wrote {out_path}  ({len(publishable)} sermons)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
