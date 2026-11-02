"""Add newly published sermons to a church landing page's "Full sermon index".

The church landing page (e.g. sermon-steward/ProvidenceLenexa/index.html)
carries a hand-curated, year-grouped sermon list between the markers
<!-- accordion:sermon-index --> and <!-- /accordion:sermon-index -->.
build_church_indexes.py rebuilds the /sermons/ listings but never touched this
page, so the church page fell a week behind every Sunday.

This is ADD-ONLY on purpose: existing lines (hand-edited titles, hidden
sermons, ordering fixes) are never rewritten or removed. A sermon is added
only if its link is not already in the block. Pages without the markers
(e.g. CoGElPaso) are left alone.
"""
from __future__ import annotations

import html as htmlmod
import re
from pathlib import Path

START = "<!-- accordion:sermon-index -->"
END = "<!-- /accordion:sermon-index -->"
_LI = re.compile(r'<li><span class="d">(\d{4}-\d{2}-\d{2})</span>')
_YEAR = re.compile(r'<div class="sermon-index-year">(\d{4})</div>')


def display_title(page_html: str, fallback: str) -> str:
    """Title the way the church-page renderer shows it: og:title, minus the
    'A sermon on <text>' suffix some renderer versions append."""
    m = re.search(r'<meta property="og:title" content="([^"]*)"', page_html[:6000])
    title = htmlmod.unescape(m.group(1)) if m else fallback
    return re.sub(r"\s+—\s+A sermon on .*$", "", title).strip() or fallback


def _li(date: str, href: str, title: str) -> str:
    return (f'        <li><span class="d">{date}</span>'
            f'<a href="{href}">{htmlmod.escape(title)}</a></li>')


def add_sermon(page: str, *, date: str, slug: str, title: str) -> tuple[str, bool]:
    """Return (new_page, changed). Inserts newest-first within the year group."""
    if START not in page or END not in page:
        return page, False
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date or ""):
        return page, False
    i = page.index(START) + len(START)
    j = page.index(END)
    block = page[i:j]
    href = f"sermons/{slug}.html"
    if f'href="{href}"' in block:
        return page, False
    lines = block.split("\n")
    new = _li(date, href, title)
    year = date[:4]
    # Find the year group.
    for k, line in enumerate(lines):
        ym = _YEAR.search(line)
        if not ym:
            continue
        if ym.group(1) == year:
            # lines[k+1] is the <ul>; insert before the first older entry.
            m = k + 2
            while m < len(lines) and "</ul>" not in lines[m]:
                d = _LI.search(lines[m])
                if d and d.group(1) < date:
                    break
                m += 1
            lines.insert(m, new)
            break
        if ym.group(1) < year:
            lines[k:k] = [f'      <div class="sermon-index-year">{year}</div>',
                          '      <ul class="sermon-index">', new, "      </ul>"]
            break
    else:
        return page, False
    return page[:i] + "\n".join(lines) + page[j:], True


def add_sermons_to_church_page(church_dir: Path, sermons: list[dict], dry_run: bool = False) -> list[str]:
    """sermons: dicts with date, slug, title. Returns titles added."""
    index = church_dir / "index.html"
    if not index.exists():
        return []
    page = index.read_text(encoding="utf-8")
    if START not in page:
        return []
    added = []
    for s in sorted(sermons, key=lambda s: s.get("date") or ""):
        slug = s.get("slug")
        if not slug:
            continue
        sp = church_dir / "sermons" / f"{slug}.html"
        if not sp.exists():
            continue  # never link a page that isn't deployed
        title = display_title(sp.read_text(encoding="utf-8", errors="replace"), s.get("title") or slug)
        page, changed = add_sermon(page, date=s.get("date") or "", slug=slug, title=title)
        if changed:
            added.append(title)
    if added and not dry_run:
        index.write_text(page, encoding="utf-8")
    return added
