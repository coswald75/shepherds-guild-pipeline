"""
One-shot scraper for crossofgrace.net (Nucleus platform).

Pulls Ricky Alcantar's sermons preached after the latest one already in
Supabase, downloads each PDF transcript via the Nucleus public API, extracts
plain text with pypdf, strips the disclaimer + structured header, and writes
clean .txt files into new_sermons_ricky/ ready for pipeline_batch.py submit.

Unlike sermons.sovgracekc.org (txt download with line timestamps),
crossofgrace.net transcripts come as PDFs with a small metadata header
followed by clean paragraph-formatted prose. The PDF header has the form:

    Date: April 12, 2026
    Series: ...
    Title: Rescuing Manhood
    Scripture Passage: Genesis 1-2; Ephesians 5
    Speaker: Ricky Alcantar
    [disclaimer line]
    [transcript prose]
"""

from __future__ import annotations

import argparse
import io
import json
import logging
import re
import sys
import time
from pathlib import Path
from urllib.request import Request, urlopen

import pdfplumber

API_BASE = (
    "https://www.crossofgrace.net/_api/public/sermon-hub"
    "/sermonengine_1cece008cc344cf78ce011f620a7ccff"
)
SITE_BASE = "https://www.crossofgrace.net"

# Ricky Alcantar's Nucleus speaker ID (verified by cross-referencing
# "The Empty Tomb" 2026-04-05 already attributed to him in Supabase).
RICKY_SPEAKER_ID = "speaker_68f3184b5ea8488e8163a7a12ca9bf25"

PREACHER = "Ricky Alcantar"
CHURCH = "Cross of Grace Church"

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/121.0 Safari/537.36"
)

# Sermons by Ricky (speaker_id matches) preached after 2026-04-05 — the latest
# Ricky sermon currently in Supabase. The 2 omitted Sundays (4/26 Rescuing Work,
# 5/3 Rescuing Marriage) are by other Cross of Grace preachers.
RICKY_SLUGS = [
    "rescuing-manhood",
    "rescuing-womanhood",
    "life-gender-and-the-pursuit-of-happiness",
]


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("scrape_crossofgrace")


def _fetch(url: str) -> bytes:
    req = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(req, timeout=120) as resp:
        return resp.read()


def _fetch_json(url: str) -> dict:
    return json.loads(_fetch(url).decode("utf-8"))


def _sermon_detail(slug: str) -> dict:
    return _fetch_json(f"{API_BASE}/page/{slug}?basePath=sermons")


def _extract_sermon_block(detail: dict) -> dict | None:
    for section in (detail.get("page") or {}).get("sections", {}).values():
        for block in (section.get("payload") or {}).get("blocks", []):
            if block.get("sermon"):
                return block["sermon"]
    return None


def _transcript_url(sermon: dict) -> str | None:
    for att in sermon.get("attachments", []) or []:
        if "transcript" in (att.get("label") or "").lower():
            dest = att.get("destination") or ""
            if dest.startswith("/"):
                return SITE_BASE + dest
            return dest
    return None


def _pdf_to_text(pdf_bytes: bytes) -> str:
    """
    pdfplumber preserves paragraph structure better than pypdf for these
    transcripts. We collapse runs of internal whitespace within each extracted
    page to a single space (pdfplumber's column-based extractor sometimes
    introduces extra spaces between glyphs), but preserve line breaks for
    later paragraph reflow.
    """
    pages = []
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for page in pdf.pages:
            pages.append(page.extract_text() or "")
    return "\n\n".join(pages)


_HEADER_RE = re.compile(
    r"Date:\s*(?P<date>.+?)\s+"
    r"(?:Series:\s*(?P<series>.+?)\s+)?"
    r"Title:\s*(?P<title>.+?)\s+"
    r"Scripture\s+Passage:\s*(?P<scripture>.+?)\s+"
    r"Speaker:\s*(?P<speaker>.+?)\s+"
    r"(?:Unedited|Sermon|For\s+personal)",
    re.DOTALL | re.IGNORECASE,
)
_DISCLAIMER_RE = re.compile(
    r"(?:unedited\s+)?transcript\s+provided\s+for\s+personal\s+use\."
    r"\s*There\s+may\s+be\s+small\s+errors\s+or\s+missed\s+phrases\.",
    re.IGNORECASE | re.DOTALL,
)
_INTERNAL_DOUBLE_SPACE = re.compile(r"[ \t]{2,}")
_BROKEN_NEWLINES = re.compile(r"(?<=\w)\n(?=\w)")


def _strip_header(text: str) -> tuple[dict, str]:
    """
    Pull the structured header out of the extracted text and return both the
    parsed metadata and the body with header + disclaimer removed.

    pdfplumber sometimes runs the header onto one line (with double-spaces
    between fields), other times onto separate lines — the regex tolerates
    both via `\\s+`.
    """
    meta: dict = {}
    match = _HEADER_RE.search(text)
    body = text
    if match:
        for k in ("date", "series", "title", "scripture", "speaker"):
            val = match.group(k)
            if val:
                # Tighten internal whitespace caused by pdfplumber column extraction
                meta[k] = _INTERNAL_DOUBLE_SPACE.sub(" ", val.strip())
        body = text[match.end():]
    body = _DISCLAIMER_RE.sub("", body)
    # Collapse double-spaces, glue back single-word line breaks, normalize blanks.
    body = _INTERNAL_DOUBLE_SPACE.sub(" ", body)
    body = _BROKEN_NEWLINES.sub(" ", body)
    body = re.sub(r"\n{3,}", "\n\n", body).strip()
    return meta, body + "\n"


def _normalize_date(date_str: str | None) -> str | None:
    """PDF header gives 'April 12, 2026' → ISO '2026-04-12'."""
    if not date_str:
        return None
    months = {
        "january": 1, "february": 2, "march": 3, "april": 4, "may": 5,
        "june": 6, "july": 7, "august": 8, "september": 9, "october": 10,
        "november": 11, "december": 12,
    }
    m = re.match(r"([A-Za-z]+)\s+(\d{1,2}),?\s+(\d{4})", date_str.strip())
    if m:
        mon = months.get(m.group(1).lower())
        if mon:
            return f"{m.group(3)}-{mon:02d}-{int(m.group(2)):02d}"
    return date_str  # fall through; pipeline may still parse it


def _build_metadata_header(meta: dict, fallback_title: str) -> str:
    date_iso = _normalize_date(meta.get("date"))
    title = meta.get("title") or fallback_title
    lines = [
        f"[Preached on {date_iso} by {PREACHER} at {CHURCH}]" if date_iso
        else f"[Preached by {PREACHER} at {CHURCH}]",
        f"[Title: {title}]",
    ]
    if meta.get("scripture"):
        lines.append(f"[Primary text: {meta['scripture']}]")
    if meta.get("series"):
        lines.append(f"[Series: {meta['series']}]")
    return "\n".join(lines) + "\n\n"


def scrape_one(slug: str, output_dir: Path, *, sleep_secs: float = 0.5) -> Path | None:
    log.info(f"  fetching: {slug}")
    detail = _sermon_detail(slug)
    sermon = _extract_sermon_block(detail)
    if not sermon:
        raise RuntimeError(f"No sermon block found for {slug}")
    speakers = sermon.get("speakers") or []
    if RICKY_SPEAKER_ID not in speakers:
        log.warning(f"    skip: {slug} not by Ricky (speakers={speakers})")
        return None

    tx_url = _transcript_url(sermon)
    if not tx_url:
        raise RuntimeError(f"No transcript attachment for {slug}")

    pdf_bytes = _fetch(tx_url)
    raw_text = _pdf_to_text(pdf_bytes)
    meta, body = _strip_header(raw_text)
    header = _build_metadata_header(meta, fallback_title=sermon.get("title") or slug)

    date_iso = _normalize_date(meta.get("date"))
    out_slug = f"{slug}-{date_iso}" if date_iso else slug
    out_path = output_dir / f"{out_slug}.txt"
    out_path.write_text(header + body, encoding="utf-8")
    log.info(f"    saved {len(body):,} chars → {out_path.name}")
    if sleep_secs:
        time.sleep(sleep_secs)
    return out_path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(__file__).resolve().parent.parent / "new_sermons_ricky",
    )
    parser.add_argument(
        "--slug", action="append", default=None,
        help="Override slug list (repeatable). Default: hard-coded RICKY_SLUGS.",
    )
    args = parser.parse_args()

    args.output_dir.mkdir(parents=True, exist_ok=True)
    slugs = args.slug or RICKY_SLUGS
    log.info(f"Scraping {len(slugs)} Ricky sermon(s) → {args.output_dir}")

    succeeded = 0
    failed = 0
    for slug in slugs:
        try:
            if scrape_one(slug, args.output_dir):
                succeeded += 1
        except Exception as exc:
            log.error(f"  FAILED {slug}: {exc}")
            failed += 1

    log.info(f"Done. succeeded={succeeded} failed={failed}")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
