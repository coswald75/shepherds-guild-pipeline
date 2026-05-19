"""
Parse Olney Hymns PDF into structured JSON records.

Each hymn has a regular shape in the source:

    1. On man, in his own image made     ← title-line (duplicated)
    1. On man, in his own image made     ← title-line (duplicated)
    Hymn 1                                ← marker
    John Newton                           ← author
    8,6,8,6                               ← meter
    ADAM. Gen 3:9                         ← theme [optional subtitle] [scripture]
    On man, in his own image made,        ← stanza 1 begins
    How much did GOD bestow?
    ...

Multi-page hymns continue with the title-line repeated at top of the next
page; we strip those repeated header echoes and rejoin the stanzas.

Output: JSON list of {book, number, author, meter, theme, scripture_anchor,
title, full_text}.

Usage:
    python3 scripts/extract_olney_hymns.py PATH/TO/olneyhymns.pdf > hymns.json
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass, asdict
from pathlib import Path

import pdfplumber

# ----------------------------------------------------------------------------
# Header / footer recognition
# ----------------------------------------------------------------------------

HYMN_MARKER = re.compile(r"^Hymn\s+(\d+)\s*$")
TITLE_LINE = re.compile(r"^\d+\.\s+\S")  # "1. On man, in his own image made"
PAGE_NUMBER = re.compile(r"^\s*\d+\s*$")  # bare page number on its own line
METER_INLINE = re.compile(r"\b(\d+(?:,\d+){1,7})\b")  # "8,6,8,6" anywhere in a line

# Bible-book recognition for scripture-anchor extraction. Newton/Cowper use
# abbreviated forms like "Gen 3:9", "Mk 9:24", "Ps 23", "Rev 2:11".
BIBLE_BOOK_ABBREV = (
    "Gen|Exod?|Ex|Lev|Num|Deut|Josh|Judg|Ruth|"
    "I[\\s-]?Sam|II[\\s-]?Sam|"
    "I[\\s-]?Ki(?:ngs)?|II[\\s-]?Ki(?:ngs)?|"
    "I[\\s-]?Chr|II[\\s-]?Chr|Ezr|Neh|Esth|Job|Ps(?:a)?|Prov|Eccl|Cant|Song|"
    "Isa|Jer|Lam|Ezek?|Dan|Hos|Joel|Amos|Obad|Jon|Mic|Nah|Hab|Zeph|Hag|Zech|Mal|"
    "Mt|Matt|Mk|Mark|Lk|Luke|Jn|John|Acts|Rom|"
    "I[\\s-]?Cor|II[\\s-]?Cor|Gal|Eph|Phil|Col|"
    "I[\\s-]?Thess|II[\\s-]?Thess|I[\\s-]?Tim|II[\\s-]?Tim|"
    "Titus|Phlm|Philem|Heb|Jas|James|"
    "I[\\s-]?Pet|II[\\s-]?Pet|"
    "I[\\s-]?Jn?|II[\\s-]?Jn?|III[\\s-]?Jn?|"
    "Jude|Rev"
)
SCRIPTURE_REF = re.compile(
    rf"\b({BIBLE_BOOK_ABBREV})\s*\.?\s*(\d+)(?::\d+(?:[\-,–]\d+)*)?\b",
    re.IGNORECASE,
)

# ----------------------------------------------------------------------------
# Models
# ----------------------------------------------------------------------------


@dataclass
class Hymn:
    book: int            # 1, 2, or 3 — derived from numbering resets
    number: int          # within-book number
    author: str | None   # 'John Newton' | 'William Cowper'
    meter: str | None    # e.g. '8,6,8,6'
    theme: str | None    # e.g. 'ADAM' or 'JEHOVAH-ROPHI' or 'MANNA'
    scripture_anchor: str | None  # e.g. 'Gen 3:9'
    title: str           # first-line of the hymn
    full_text: str       # stanzas joined with newlines, blank lines between stanzas


# ----------------------------------------------------------------------------
# Parsing
# ----------------------------------------------------------------------------


def _clean_lines(raw: str) -> list[str]:
    """Split into stripped non-empty lines."""
    return [ln.rstrip() for ln in raw.splitlines() if ln.strip()]


def _drop_repeated_title_echo(lines: list[str], title_token: str) -> list[str]:
    """
    On continuation pages, the title-line repeats at top as a running header.
    Drop any leading lines that match either the title token or a bare page
    number.
    """
    out = list(lines)
    while out and (out[0].startswith(title_token) or PAGE_NUMBER.match(out[0])):
        out.pop(0)
    # also strip trailing page numbers
    while out and PAGE_NUMBER.match(out[-1]):
        out.pop()
    return out


def _parse_theme_and_scripture(line: str) -> tuple[str | None, str | None]:
    """
    The header line below the meter typically looks like:
      'ADAM. Gen 3:9'
      'MANNA. Ex 16:18'
      'JEHOVAH-ROPHI, I am the Lord that healeth thee. Ex 15'
      'Smyrna. Rev 2:11'
      'The pool of Bethesda. Jn 5:2-4'
    We pull the scripture ref off the end and treat the rest as theme.
    """
    scripture = None
    theme = line.strip()
    m = list(SCRIPTURE_REF.finditer(line))
    if m:
        last = m[-1]
        scripture = last.group(0)
        # Strip trailing scripture + punctuation from the theme
        theme = (line[: last.start()]).rstrip(" ,.;–-")
    return (theme or None, scripture)


def parse(pdf_path: Path) -> list[Hymn]:
    hymns: list[Hymn] = []
    current_book = 1
    last_number = 0

    with pdfplumber.open(pdf_path) as pdf:
        # First pass: identify which pages START a hymn (have 'Hymn N' header)
        starts: list[tuple[int, int]] = []  # (page_index, hymn_number)
        for i, page in enumerate(pdf.pages):
            text = page.extract_text() or ""
            for line in text.splitlines():
                m = HYMN_MARKER.match(line.strip())
                if m:
                    starts.append((i, int(m.group(1))))
                    break  # one hymn per starting page

        # Second pass: for each start, walk forward until the next start
        for idx, (start_page, number) in enumerate(starts):
            end_page = starts[idx + 1][0] if idx + 1 < len(starts) else len(pdf.pages)

            # Detect book transitions: when numbering resets (e.g. 141 → 1)
            if number < last_number - 5:
                current_book += 1
            last_number = number

            # Gather all lines across the hymn's pages
            all_lines: list[str] = []
            for p in range(start_page, end_page):
                txt = pdf.pages[p].extract_text() or ""
                all_lines.extend(_clean_lines(txt))

            # Locate the 'Hymn N' marker line, then read forward
            try:
                marker_idx = next(
                    i for i, ln in enumerate(all_lines)
                    if HYMN_MARKER.match(ln.strip()) and int(HYMN_MARKER.match(ln.strip()).group(1)) == number
                )
            except StopIteration:
                continue

            # Title-line is whatever appeared above the marker (deduped — book has
            # it printed twice). Take the last occurrence before marker.
            title_lines = [ln for ln in all_lines[:marker_idx] if TITLE_LINE.match(ln)]
            title = title_lines[-1] if title_lines else ""
            # Strip the "1. " prefix
            title_clean = re.sub(r"^\d+\.\s*", "", title).rstrip(",.")

            # Token to identify continuation-page header echoes
            title_token = f"{number}."

            # Author, meter, theme, scripture — strip ALL page-number lines
            # before peeking at structure (they wedge unpredictably between
            # the marker and the real header lines).
            after_marker = [
                ln for ln in all_lines[marker_idx + 1 :]
                if not PAGE_NUMBER.match(ln)
            ]

            # Header parsing handles four layouts:
            #   A) author / meter / 'THEME. Scripture' / body
            #   B) author / meter / 'THEME.' / 'Scripture' / body
            #   C) 'Author Meter Pagenum' / 'THEME. Scripture' / body
            #   D) 'Author Meter Pagenum' / 'THEME.' / 'Scripture' / body
            # PDF text extraction occasionally collapses the author+meter
            # line into one row (layouts C/D), and scripture refs sometimes
            # sit on the line below the theme (layouts B/D).
            author = meter = theme = scripture = None
            cursor = 0
            if after_marker:
                first = after_marker[cursor]
                m = METER_INLINE.search(first)
                if m:
                    # Layouts C/D — split mashed line.
                    author = first[: m.start()].strip()
                    meter = m.group(1)
                else:
                    # Layouts A/B — author then meter on separate lines.
                    author = first
                    cursor += 1
                    if cursor < len(after_marker):
                        meter = after_marker[cursor].strip()
                cursor += 1

            if cursor < len(after_marker):
                theme_line = after_marker[cursor]
                cursor += 1
                theme, scripture = _parse_theme_and_scripture(theme_line)
                # Layouts B/D — scripture is the standalone next line.
                if not scripture and cursor < len(after_marker):
                    candidate = after_marker[cursor].strip()
                    if len(candidate) < 40 and SCRIPTURE_REF.match(candidate):
                        scripture = candidate
                        cursor += 1

            # Stanzas: everything from cursor onward, with continuation-page
            # title-echoes stripped. Also stop at back-of-book appendix
            # markers (only matters for the very last hymn).
            APPENDIX_MARKERS = (
                "Contents of the",
                "INDEX",
                "TABLE",
                "THE END OF",
                "A TABLE",
            )
            body_lines: list[str] = []
            for ln in after_marker[cursor:]:
                if any(ln.lstrip().startswith(m) for m in APPENDIX_MARKERS):
                    break
                if ln.startswith(title_token) and ln[len(title_token):].strip().startswith(title_clean[:25]):
                    continue  # repeated title echo on continuation page
                body_lines.append(ln)
            full_text = "\n".join(body_lines).strip()

            hymns.append(
                Hymn(
                    book=current_book,
                    number=number,
                    author=author,
                    meter=meter,
                    theme=theme,
                    scripture_anchor=scripture,
                    title=title_clean,
                    full_text=full_text,
                )
            )

    return hymns


def main() -> int:
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} <olneyhymns.pdf>", file=sys.stderr)
        return 2
    hymns = parse(Path(sys.argv[1]))
    print(json.dumps([asdict(h) for h in hymns], indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
