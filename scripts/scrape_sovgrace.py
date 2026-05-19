"""
One-shot scraper for sermons.sovgracekc.org.

Pulls a hard-coded list of sermon URLs, extracts each page's
/transcriptions/<id>.txt download link, downloads the txt, strips the
auto-transcription disclaimer + timestamp markers, and writes one clean
.txt per sermon into new_sermons/ ready for pipeline_batch.py submit.

A metadata header is prepended to each transcript so the decomposition LLM
gets title / passage / date directly (the auto-transcript doesn't include
service-bulletin context):

    [Preached on YYYY-MM-DD by Chris Oswald at Providence Community Church]
    [Title: ...]
    [Primary text: ...]

    <verbatim sermon text>
"""

from __future__ import annotations

import argparse
import logging
import re
import sys
import time
from pathlib import Path
from urllib.request import Request, urlopen

# Hard-coded sermon list — current "next batch" of Chris Oswald's sermons
# to scrape and ingest. Update this list with each weekly run, or with
# whatever batch you want to bring in. (Dov's sermons live at the same
# host but on a different preacher_id and are excluded from this list.)
#
# Previously-ingested batches preserved in git history (May 13 batch:
# 2026-03-15 through 2026-04-19, seven sermons).
SERMONS = [
    {
        "url": "https://sermons.sovgracekc.org/sermons/93869/",
        "date": "2026-05-10",
        "title": "Imperishable Beauty",
        "primary_text": "1 Peter 3:1-6",
        "slug": "imperishable-beauty-2026-05-10",
    },
    {
        "url": "https://sermons.sovgracekc.org/sermons/93896/",
        "date": "2026-05-15",
        "title": "Don't Waste Your Crisis: How to Recover from a Self-Inflicted Wound",
        "primary_text": "Psalm 51",
        "slug": "dont-waste-your-crisis-2026-05-15",
    },
]

PREACHER = "Chris Oswald"
CHURCH = "Providence Community Church"

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/121.0 Safari/537.36"
)

# Patterns
_TX_LINK_RE = re.compile(r'href="(/transcriptions/[^"]+\.txt)"')
_TIMESTAMP_RE = re.compile(r"^\[\d+:\d+(?::\d+)?\]\s*", re.MULTILINE)
_DISCLAIMER_RE = re.compile(
    r"^.*?automatically generated machine transcription.*?audio if you are in any doubt\.?\s*",
    re.DOTALL | re.IGNORECASE,
)
_HEADER_LINE_RE = re.compile(r"^Transcription downloaded from .*?\.\s*", re.IGNORECASE)


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("scrape_sovgrace")


def _fetch(url: str) -> bytes:
    req = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(req, timeout=60) as resp:
        return resp.read()


def _find_transcript_url(html: bytes) -> str:
    """Locate the /transcriptions/<id>.txt link inside a sermon detail page."""
    text = html.decode("utf-8", errors="replace")
    m = _TX_LINK_RE.search(text)
    if not m:
        raise RuntimeError("No /transcriptions/*.txt link found on page")
    return m.group(1)


def _clean_transcript(raw: str) -> str:
    """Strip the file's leading metadata + disclaimer + per-line timestamps."""
    text = raw.lstrip("﻿")  # BOM if present
    text = _HEADER_LINE_RE.sub("", text, count=1).lstrip()
    text = _DISCLAIMER_RE.sub("", text, count=1).lstrip()
    # Strip timestamp markers at the start of each line.
    text = _TIMESTAMP_RE.sub("", text)
    # Collapse runs of blank lines.
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text + "\n"


def _build_metadata_header(sermon: dict) -> str:
    lines = [
        f"[Preached on {sermon['date']} by {PREACHER} at {CHURCH}]",
        f"[Title: {sermon['title']}]",
    ]
    if sermon.get("primary_text"):
        lines.append(f"[Primary text: {sermon['primary_text']}]")
    return "\n".join(lines) + "\n\n"


def scrape_one(sermon: dict, output_dir: Path, *, sleep_secs: float = 0.5) -> Path:
    log.info(f"  fetching: {sermon['title']} ({sermon['date']})")
    html = _fetch(sermon["url"])
    tx_path = _find_transcript_url(html)
    tx_url = "https://sermons.sovgracekc.org" + tx_path
    raw_txt = _fetch(tx_url).decode("utf-8", errors="replace")
    cleaned = _clean_transcript(raw_txt)
    header = _build_metadata_header(sermon)

    out_path = output_dir / f"{sermon['slug']}.txt"
    out_path.write_text(header + cleaned, encoding="utf-8")
    log.info(f"    saved {len(cleaned):,} chars → {out_path.name}")
    if sleep_secs:
        time.sleep(sleep_secs)
    return out_path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(__file__).resolve().parent.parent / "new_sermons",
    )
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    args.output_dir.mkdir(parents=True, exist_ok=True)
    log.info(f"Scraping {len(SERMONS)} sermon(s) → {args.output_dir}")

    succeeded = 0
    failed = 0
    for i, sermon in enumerate(SERMONS, 1):
        if args.limit and i > args.limit:
            break
        try:
            scrape_one(sermon, args.output_dir)
            succeeded += 1
        except Exception as exc:
            log.error(f"  FAILED {sermon['slug']}: {exc}")
            failed += 1

    log.info(f"Done. succeeded={succeeded} failed={failed}")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
