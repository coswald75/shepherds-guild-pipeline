#!/usr/bin/env python3
"""Rebuild the accordion block on a church landing page.

The church landing pages (e.g. sermon-steward/ProvidenceLenexa/index.html)
carry an expand/collapse menu between the About-the-Church prose and the
"What <church> values" list:

  - About the preaching   (the hand-written preacher profile — preserved
                           verbatim, never regenerated; see feedback_style)
  - Full sermon index     (every deployed sermon page, grouped by year,
                           newest first — REGENERATED from disk each run)
  - Doctrinal index       (the doctrine-loci browse pages — REGENERATED
                           from the deployed doctrine index each run)

This script regenerates the two data-driven sections in place. It finds
the accordion by its HTML comment markers, so it's safe to re-run after
every deploy_sermon_pages.py push (new sermons appear in the index
automatically). The hand-written "About the preaching" body is left
untouched.

Usage:
    python scripts/church_page_accordion.py --church-dir \
        /Users/dad/shepherds-guild/sermon-steward/ProvidenceLenexa
"""
from __future__ import annotations

import argparse
import html as htmlmod
import re
import sys
from pathlib import Path


def extract_sermons(sermons_dir: Path) -> list[dict]:
    """Pull (title, date, href) from every deployed sermon page."""
    out = []
    for f in sorted(sermons_dir.glob("*.html")):
        if f.name == "index.html" or f.name.startswith("page-"):
            continue
        head = f.read_text(errors="replace")[:4000]
        m_title = re.search(r'<meta property="og:title" content="([^"]*)"', head)
        m_date = re.search(r'"datePublished":\s*"(\d{4}-\d{2}-\d{2})"', head)
        title = htmlmod.unescape(m_title.group(1)) if m_title else f.stem
        # Some renderer versions append "— A sermon on <text>" to og:title.
        # Redundant in a dense index where the scripture ref is usually in
        # the title already; strip for display.
        title = re.sub(r"\s+—\s+A sermon on .*$", "", title)
        # Knox Classical School no longer exists (Chris, 2026-06-10) —
        # exclude anything school-related from the public sermon index.
        if "knox" in title.lower() or "classical school" in title.lower():
            continue
        out.append({
            "title": title,
            "date": m_date.group(1) if m_date else None,
            "href": f"sermons/{f.name}",
        })
    return out


def sermon_index_html(sermons: list[dict]) -> str:
    """Year-grouped, newest-first list. Undated sermons sort last."""
    dated = sorted(
        [s for s in sermons if s["date"]], key=lambda s: s["date"], reverse=True
    )
    undated = sorted(
        [s for s in sermons if not s["date"]], key=lambda s: s["title"].lower()
    )
    lines: list[str] = []
    year = None
    for s in dated:
        y = s["date"][:4]
        if y != year:
            if year is not None:
                lines.append("      </ul>")
            lines.append(f'      <div class="sermon-index-year">{y}</div>')
            lines.append('      <ul class="sermon-index">')
            year = y
        lines.append(
            f'        <li><span class="d">{s["date"]}</span>'
            f'<a href="{s["href"]}">{htmlmod.escape(s["title"])}</a></li>'
        )
    if year is not None:
        lines.append("      </ul>")
    if undated:
        lines.append('      <div class="sermon-index-year">Undated</div>')
        lines.append('      <ul class="sermon-index">')
        for s in undated:
            lines.append(
                f'        <li><span class="d">—</span>'
                f'<a href="{s["href"]}">{htmlmod.escape(s["title"])}</a></li>'
            )
        lines.append("      </ul>")
    return "\n".join(lines)


def topical_index_html(church_dir: Path) -> str:
    """Doctrinal index toggle content: the one-off synthesized pages.

    As of 2026-06-10 the toggle links the synthesized doctrine pages at
    <church>/doctrine/<slug>/ (same treatment as the topic pages —
    dominant pulpit themes anchored to the Statement of Faith, every
    claim cited to its sermon), NOT the old paginated browse indexes
    under sermons/doctrine/ (those remain deployed for archive nav).
    Scans the deployed doctrine pages on disk; label comes from each
    page's H1, blurb from its deck line. New-tab links per Chris's spec.
    """
    doctrine_dir = church_dir / "doctrine"
    pages = sorted(doctrine_dir.glob("*/index.html")) if doctrine_dir.exists() else []
    if not pages:
        return "      <p>Doctrinal pages are being prepared for this church.</p>"

    lines = ['      <ul class="topic-index">']
    for page in pages:
        slug = page.parent.name
        body = page.read_text(errors="replace")
        m_h1 = re.search(r"<h1>([^<]+)</h1>", body)
        m_deck = re.search(r'<p class="deck">([^<]+)<', body)
        label = htmlmod.unescape(m_h1.group(1)) if m_h1 else slug.replace("-", " ").title()
        blurb = htmlmod.unescape(m_deck.group(1)).strip() if m_deck else ""
        blurb_html = (
            f' <span class="topic-blurb">{htmlmod.escape(blurb)}</span>' if blurb else ""
        )
        lines.append(
            f'        <li><a href="/{church_dir.name}/doctrine/{slug}/" target="_blank" rel="noopener">'
            f"<strong>{htmlmod.escape(label)}</strong></a>{blurb_html}</li>"
        )
    lines.append("      </ul>")
    lines.append(
        '      <p class="topic-more">Each doctrine opens in a new tab — the dominant '
        "themes preached here, anchored to the church's Statement of Faith, with every "
        "claim cited back to its sermon. You can also browse the archive "
        '<a href="sermons/scripture/">by book of the Bible</a> or '
        '<a href="sermons/series/">by sermon series</a>.</p>'
    )
    return "\n".join(lines)


def replace_between(text: str, start_marker: str, end_marker: str, new_inner: str) -> str:
    i = text.index(start_marker) + len(start_marker)
    j = text.index(end_marker)
    return text[:i] + "\n" + new_inner + "\n" + text[j:]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--church-dir", type=Path, required=True)
    args = ap.parse_args()

    index = args.church_dir / "index.html"
    if not index.exists():
        print(f"no index.html at {args.church_dir}", file=sys.stderr)
        return 1
    page = index.read_text()

    if "<!-- accordion:sermon-index -->" not in page:
        print(
            "accordion markers not found — run the one-time conversion first "
            "(this script only refreshes the data-driven sections)",
            file=sys.stderr,
        )
        return 1

    sermons = extract_sermons(args.church_dir / "sermons")
    page = replace_between(
        page,
        "<!-- accordion:sermon-index -->",
        "<!-- /accordion:sermon-index -->",
        sermon_index_html(sermons),
    )
    page = replace_between(
        page,
        "<!-- accordion:topical-index -->",
        "<!-- /accordion:topical-index -->",
        topical_index_html(args.church_dir),
    )
    index.write_text(page)
    dated = sum(1 for s in sermons if s["date"])
    print(f"refreshed {index}: {len(sermons)} sermons in index ({dated} dated)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
