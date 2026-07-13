#!/usr/bin/env python3
"""
generate_og_card.py — per-sermon social share image (Open Graph / Twitter card).

Renders a 1200×630 PNG (title · Scripture · preacher · church, branded) with the
same headless-Chromium engine the PDF report uses, and writes it to

    output/og-cards/<church-slug>/<db-slug>.png

The renderer (sermon_page_renderer/composer.py) emits <meta property="og:image">
only when this file exists, and scripts/deploy_sermon_pages.py copies it into the
sermon-steward repo next to the page, so it deploys to

    https://sermonsteward.com/<ChurchDir>/sermons/<db-slug>.png

Usage:
    python scripts/generate_og_card.py <sermon_id>
"""
from __future__ import annotations

import argparse
import html
import logging
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from supabase import create_client

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s",
                    datefmt="%H:%M:%S")
log = logging.getLogger("og-card")

# Brand palette — mirrors the Sermon Steward home page (_src/index.njk).
BG = "#fbf8f1"
INK = "#1a1a1a"
INK_SOFT = "#4a4a4a"
INK_FAINT = "#8a8378"
ACCENT = "#c4452f"
RULE = "#e6e1d3"


def _supabase():
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or os.environ.get("SUPABASE_KEY")
    if not url or not key:
        raise RuntimeError("SUPABASE_URL / SUPABASE_KEY missing in env")
    return create_client(url, key)


def load_sermon(sb, sermon_id: str) -> dict:
    rows = sb.table("sermons").select(
        "id, title, slug, date, primary_text, series_name, "
        "preachers(name, churches(name, slug))"
    ).eq("id", sermon_id).execute().data
    if not rows:
        raise SystemExit(f"sermon {sermon_id} not found")
    return rows[0]


def _fmt_date(d: Optional[str]) -> str:
    if not d:
        return ""
    try:
        return datetime.strptime(d, "%Y-%m-%d").strftime("%B %-d, %Y")
    except Exception:
        return d


def _title_size(title: str) -> int:
    """Shrink the headline for long titles so it always fits the card."""
    n = len(title or "")
    if n <= 32:
        return 82
    if n <= 55:
        return 68
    if n <= 80:
        return 56
    return 46


def build_html(sermon: dict) -> str:
    preacher = (sermon.get("preachers") or {}).get("name") or ""
    church_obj = (sermon.get("preachers") or {}).get("churches") or {}
    church = church_obj.get("name") or ""
    title = sermon.get("title") or "Sermon"
    scripture = sermon.get("primary_text") or ""
    series = sermon.get("series_name") or ""
    date_long = _fmt_date(sermon.get("date"))

    # Top eyebrow: church name; optional series after a dot.
    eyebrow_bits = [b for b in (church, series) if b]
    eyebrow = "  ·  ".join(eyebrow_bits)

    # Bottom-left: preacher + date.
    foot_bits = [b for b in (preacher, date_long) if b]
    footline = "  ·  ".join(foot_bits)

    e = html.escape
    tsize = _title_size(title)

    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><style>
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  html, body {{ width:1200px; height:630px; }}
  body {{
    background:{BG}; color:{INK};
    font-family: system-ui,-apple-system,"Segoe UI",Helvetica,Arial,sans-serif;
    position:relative; overflow:hidden;
  }}
  .bar {{ position:absolute; top:0; left:0; right:0; height:14px; background:{ACCENT}; }}
  .frame {{
    position:absolute; inset:14px 0 0 0;
    padding:66px 78px 60px; display:flex; flex-direction:column; height:calc(100% - 14px);
  }}
  .eyebrow {{
    font-size:24px; font-weight:700; letter-spacing:.14em; text-transform:uppercase;
    color:{ACCENT};
  }}
  .title {{
    font-family:"Iowan Old Style",Charter,Georgia,"Times New Roman",serif;
    font-weight:700; color:{INK}; line-height:1.08; letter-spacing:-0.01em;
    font-size:{tsize}px; margin-top:26px;
    display:-webkit-box; -webkit-line-clamp:4; -webkit-box-orient:vertical; overflow:hidden;
  }}
  .scripture {{
    font-family:"Iowan Old Style",Charter,Georgia,serif; font-style:italic;
    font-size:34px; color:{INK_SOFT}; margin-top:26px;
  }}
  .spacer {{ flex:1 1 auto; }}
  .footer {{
    display:flex; align-items:flex-end; justify-content:space-between;
    border-top:2px solid {RULE}; padding-top:26px;
  }}
  .byline {{ font-size:28px; color:{INK_SOFT}; font-weight:600; }}
  .byline .date {{ color:{INK_FAINT}; font-weight:500; }}
  .wordmark {{ font-size:30px; font-weight:800; letter-spacing:-0.02em; color:{INK}; }}
  .wordmark .dot {{ color:{ACCENT}; }}
</style></head>
<body>
  <div class="bar"></div>
  <div class="frame">
    {f'<div class="eyebrow">{e(eyebrow)}</div>' if eyebrow else ''}
    <div class="title">{e(title)}</div>
    {f'<div class="scripture">{e(scripture)}</div>' if scripture else ''}
    <div class="spacer"></div>
    <div class="footer">
      <div class="byline">{e(footline)}</div>
      <div class="wordmark">Sermon Steward<span class="dot">.</span></div>
    </div>
  </div>
</body></html>"""


def html_to_png(html_str: str, png_path: Path) -> None:
    from playwright.sync_api import sync_playwright
    png_path.parent.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1200, "height": 630})
        page.set_content(html_str, wait_until="networkidle")
        page.screenshot(path=str(png_path), clip={"x": 0, "y": 0, "width": 1200, "height": 630})
        browser.close()


def generate_og_card(sermon_id: str, sb=None) -> Path:
    """Render the share card for one sermon. Returns the PNG path."""
    sb = sb or _supabase()
    sermon = load_sermon(sb, sermon_id)
    church_slug = ((sermon.get("preachers") or {}).get("churches") or {}).get("slug") or "church"
    slug = sermon.get("slug") or sermon_id
    out = REPO_ROOT / "output" / "og-cards" / church_slug / f"{slug}.png"
    html_to_png(build_html(sermon), out)
    log.info(f"wrote {out}")
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("sermon_id")
    args = ap.parse_args()
    load_dotenv(REPO_ROOT / ".env")
    print(generate_og_card(args.sermon_id))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
