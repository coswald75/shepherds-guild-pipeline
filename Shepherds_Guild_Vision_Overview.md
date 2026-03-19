# Shepherd's Guild — Vision & Technical Overview
### Self-Contained Reference Document
*Last updated: March 2026*

---

## Vision Statement

Shepherd's Guild is the broadest categorical reference for all of Chris' ministry-related business. Think of it as Procter & Gamble, but organized around the following overarching vision statement:

> **Helping America's pastors become more skilled in their craft, more present in their homes, and more rested in Christ.**

If it's related to Christianity and isn't specifically pertaining to Providence Community Church or Sovereign Grace Ministries, there's a good chance it fits under the Shepherd's Guild umbrella.

---

## Table of Contents

1. [Infrastructure: Scraping & Transcription](#1-infrastructure-scraping--transcription)
   - [split-keller.py — Keller Archive Splitter](#split-kellerpy--keller-archive-splitter)
   - [AssemblyAIsermon_scraper.py — Audio Scraper & Transcriber](#assemblyaisermon_scraperpy--audio-scraper--transcriber)
   - [Millwerx — Public Domain Text Acquisition Pipeline](#millwerx--public-domain-text-acquisition-pipeline)
2. [Infrastructure: Decomposition Pipeline](#2-infrastructure-decomposition-pipeline)
   - [Decomposition Spec v2](#decomposition-spec-v2)
   - [pipeline.py — Single-Sermon Pipeline](#pipelinepy--single-sermon-pipeline-v31)
   - [pipeline_batch.py — Batch Mode (50% Cost Savings)](#pipeline_batchpy--batch-mode-50-cost-savings)
   - [repair_batch_failures.py — JSON Repair Tool](#repair_batch_failurespy--json-repair-tool)
   - [Pipeline README](#pipeline-readme)
3. [Infrastructure: Database](#3-infrastructure-database)
   - [supabase-schema-v3.sql](#supabase-schema-v3sql)
4. [Products](#4-products)
   - [Guild Hall](#guild-hall)
   - [Ingester & Included Products](#ingester--included-products)
   - [Report & Exemplar](#report--exemplar)
   - [Illustration & Quote Database](#illustration--quote-database)
   - [Book Recommendation](#book-recommendation)
   - [Annual Subscription](#annual-subscription)
   - [The Forge (Automated Coaching) → MIRRORVOX](#the-forge-automated-coaching--mirrorvox)
   - [Social Media Post Generator → OUTREACH](#social-media-post-generator--outreach)
   - [Guest Gift Book → BOOKGUIDE](#guest-gift-book--bookguide)
   - [Sermon Research → PASTORALRAG](#sermon-research--pastoralrag)
5. [Sales & Lead Generation](#5-sales--lead-generation)
   - [scrape_locate_church.py — Directory Scraper](#scrape_locate_churchpy--directory-scraper)
   - [enrich_leads.py — Detail Enrichment](#enrich_leadspy--detail-enrichment)

---


## 1. Infrastructure: Scraping & Transcription

The first product suite is built around a variety of content scraper/transcribers where sermons are grabbed from a variety of sources. The most useful in the long run is the AssemblyAI scraper that grabs podcasts and other audio sermon formats and runs them through AssemblyAI's transcription service, producing a JSON file for each sermon that feeds directly into the decomposition pipeline.

---

### split-keller.py — Keller Archive Splitter

Splits a combined Keller sermon archive into individual .txt files. Works with any Keller archive by detecting ALL CAPS title lines as sermon boundaries.

```python
"""
Split a combined Keller sermon archive into individual .txt files.
Works with any Keller archive by detecting ALL CAPS title lines
as sermon boundaries.

Usage: python3 split-keller.py input.txt output_folder/
"""

import sys
import re
import os


def is_sermon_title(line, lines, idx):
    """
    Detect sermon title lines. In Keller archives, sermon bodies
    start with an ALL CAPS title line (e.g., "CHILDREN OF THE LIGHT")
    that is:
    - At least 5 characters long
    - All uppercase letters (plus spaces, punctuation)
    - Not a section header like "Sermons by Date"
    - Followed within a few lines by a scripture reference or date
    """
    stripped = line.strip()
    
    # Must be non-empty and at least 5 chars
    if len(stripped) < 5:
        return False
    
    # Must be mostly uppercase letters
    # Allow spaces, commas, colons, apostrophes, hyphens, periods
    alpha_chars = [c for c in stripped if c.isalpha()]
    if len(alpha_chars) < 3:
        return False
    if not all(c.isupper() for c in alpha_chars):
        return False
    
    # Skip known non-sermon headers
    skip_patterns = [
        "SERMONS BY", "TABLE OF CONTENTS", "COPYRIGHT",
        "ALL RIGHTS", "REDEEMER", "ACKNOWLEDGMENT",
    ]
    for pat in skip_patterns:
        if pat in stripped:
            return False
    
    # Look ahead for confirming signals (scripture ref, date, or "This is the Word")
    lookahead = '\n'.join(lines[idx:idx+15]).lower()
    has_scripture = bool(re.search(r'\d+:\d+', lookahead))
    has_date = bool(re.search(r'(january|february|march|april|may|june|july|august|september|october|november|december)\s+\d', lookahead))
    has_word = 'word of the lord' in lookahead or 'scripture' in lookahead or 'reading' in lookahead
    
    return has_scripture or has_date or has_word


def split_sermons(input_path, output_dir):
    with open(input_path, 'r', encoding='utf-8') as f:
        text = f.read()
    
    lines = text.split('\n')
    
    # Find sermon start positions
    sermon_starts = []
    for i, line in enumerate(lines):
        if is_sermon_title(line, lines, i):
            title = line.strip().title()  # Convert "CHILDREN OF THE LIGHT" to "Children Of The Light"
            sermon_starts.append((i, title))
    
    print(f"Found {len(sermon_starts)} sermons")
    
    if len(sermon_starts) == 0:
        print("No sermons detected. Check the file format.")
        return
    
    os.makedirs(output_dir, exist_ok=True)
    
    for idx, (start_line, title) in enumerate(sermon_starts):
        # End is the start of the next sermon, or end of file
        if idx + 1 < len(sermon_starts):
            end_line = sermon_starts[idx + 1][0]
        else:
            end_line = len(lines)
        
        # Extract sermon text
        sermon_text = '\n'.join(lines[start_line:end_line]).strip()
        
        # Create filename from title
        safe_title = re.sub(r'[^\w\s-]', '', title).strip()
        safe_title = re.sub(r'\s+', '-', safe_title)
        filename = f"keller-{safe_title.lower()}.txt"
        
        filepath = os.path.join(output_dir, filename)
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(sermon_text)
        
        char_count = len(sermon_text)
        print(f"  [{idx+1:02d}] {title} — {char_count:,} chars → {filename}")
    
    print(f"\nDone! {len(sermon_starts)} sermons written to {output_dir}/")


if __name__ == '__main__':
    if len(sys.argv) < 3:
        print("Usage: python3 split-keller.py input.txt output_folder/")
        sys.exit(1)
    
    split_sermons(sys.argv[1], sys.argv[2])```

---

### AssemblyAIsermon_scraper.py — Audio Scraper & Transcriber

Three-phase workflow: **SCAN** (crawl website/RSS → extract audio URLs) → **TRANSCRIBE** (submit to AssemblyAI → get transcripts) → **PACKAGE** (output sermonindex-compatible JSON for pipeline.py).

```python
"""
Shepherd's Guild — Sermon Audio Scraper & Transcriber
======================================================

Scrapes church websites and podcast RSS feeds for sermon audio,
then transcribes via AssemblyAI into pipeline-ready JSON files.

Three-phase workflow:
  Phase 1: SCAN    — Crawl a website or RSS feed → extract audio URLs + metadata
  Phase 2: TRANSCRIBE — Submit audio URLs to AssemblyAI → get transcripts
  Phase 3: PACKAGE — Output sermonindex-compatible JSON files for pipeline.py

Usage:
  # Scan an RSS podcast feed and transcribe all episodes
  python sermon_scraper.py rss https://church.com/podcast/feed.xml --preacher "Pastor Name"

  # Scan a church website for audio links
  python sermon_scraper.py website https://church.com/sermons --preacher "Pastor Name"

  # Scan a website with depth (follow sermon detail pages)
  python sermon_scraper.py website https://church.com/sermons --preacher "Pastor Name" --depth 2

  # Transcribe from a manually-prepared CSV of audio URLs
  python sermon_scraper.py urls manifest.csv --preacher "Pastor Name"

  # Scan only (don't transcribe yet — just discover audio files)
  python sermon_scraper.py rss https://church.com/feed.xml --preacher "Pastor Name" --scan-only

  # Resume a partially completed batch (skip already-transcribed files)
  python sermon_scraper.py rss https://church.com/feed.xml --preacher "Pastor Name" --resume

Environment variables (set in .env or export):
  ASSEMBLYAI_API_KEY  — Your AssemblyAI API key
"""

import os
import sys
import json
import csv
import re
import time
import argparse
import logging
from pathlib import Path
from datetime import datetime
from typing import Optional
from urllib.parse import urljoin, urlparse
from concurrent.futures import ThreadPoolExecutor, as_completed

# ---------------------------------------------------------------------------
# Dependencies
# ---------------------------------------------------------------------------
try:
    import assemblyai as aai
    import requests
    from dotenv import load_dotenv
except ImportError as e:
    print(f"Missing dependency: {e}")
    print("Install with: pip install assemblyai requests python-dotenv")
    sys.exit(1)

try:
    from bs4 import BeautifulSoup
    HAS_BS4 = True
except ImportError:
    HAS_BS4 = False

try:
    import feedparser
    HAS_FEEDPARSER = True
except ImportError:
    HAS_FEEDPARSER = False

load_dotenv()

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
OUTPUT_DIR = Path(__file__).parent / "transcripts"
OUTPUT_DIR.mkdir(exist_ok=True)

AUDIO_EXTENSIONS = {".mp3", ".wav", ".m4a", ".ogg", ".opus", ".wma", ".aac", ".flac"}
MAX_CONCURRENT_TRANSCRIPTIONS = 5
SCAN_DELAY_SEC = 1  # Polite delay between page fetches

# Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S"
)
log = logging.getLogger("scraper")


# ---------------------------------------------------------------------------
# AssemblyAI client
# ---------------------------------------------------------------------------
def init_assemblyai():
    """Initialize AssemblyAI with API key."""
    api_key = os.getenv("ASSEMBLYAI_API_KEY")
    if not api_key:
        raise EnvironmentError(
            "ASSEMBLYAI_API_KEY not set. "
            "Add it to your .env file or export it."
        )
    aai.settings.api_key = api_key
    log.info("AssemblyAI initialized")


# ---------------------------------------------------------------------------
# Phase 1: SCAN — Extract audio URLs from various sources
# ---------------------------------------------------------------------------

def slugify(text: str) -> str:
    """Convert a string to a filesystem-safe slug."""
    text = text.lower().strip()
    text = re.sub(r'[^\w\s-]', '', text)
    text = re.sub(r'[\s_]+', '-', text)
    text = re.sub(r'-+', '-', text)
    return text[:80].strip('-')


def scan_rss_feed(feed_url: str) -> list[dict]:
    """
    Parse an RSS/podcast feed and extract episode metadata + audio URLs.
    """
    if not HAS_FEEDPARSER:
        log.error("feedparser not installed. Run: pip install feedparser")
        sys.exit(1)

    log.info(f"Parsing RSS feed: {feed_url}")
    feed = feedparser.parse(feed_url)

    if feed.bozo and not feed.entries:
        log.error(f"Failed to parse feed: {feed.bozo_exception}")
        return []

    log.info(f"Feed: {feed.feed.get('title', 'Unknown')} — {len(feed.entries)} entries")

    episodes = []
    for entry in feed.entries:
        # Find audio enclosure
        audio_url = None
        for enclosure in entry.get("enclosures", []):
            if enclosure.get("type", "").startswith("audio/") or \
               any(enclosure.get("href", "").lower().endswith(ext) for ext in AUDIO_EXTENSIONS):
                audio_url = enclosure.get("href")
                break

        # Also check for media content
        if not audio_url:
            for media in entry.get("media_content", []):
                if media.get("type", "").startswith("audio/"):
                    audio_url = media.get("url")
                    break

        # Check for direct link to audio in links
        if not audio_url:
            for link in entry.get("links", []):
                href = link.get("href", "")
                if any(href.lower().endswith(ext) for ext in AUDIO_EXTENSIONS):
                    audio_url = href
                    break

        if not audio_url:
            log.debug(f"No audio found for: {entry.get('title', 'Unknown')}")
            continue

        # Extract date
        date_str = None
        for date_field in ["published", "updated", "created"]:
            if date_field in entry:
                date_str = entry[date_field]
                break

        # Extract description/summary
        description = ""
        if "summary" in entry:
            description = entry["summary"]
        elif "description" in entry:
            description = entry["description"]

        # Clean HTML from description
        if HAS_BS4 and description:
            description = BeautifulSoup(description, "html.parser").get_text(separator=" ").strip()

        episodes.append({
            "title": entry.get("title", "Unknown"),
            "audio_url": audio_url,
            "date": date_str,
            "description": description,
            "duration": entry.get("itunes_duration"),
            "link": entry.get("link"),
        })

    log.info(f"Found {len(episodes)} episodes with audio")
    return episodes


def scan_website(url: str, depth: int = 1) -> list[dict]:
    """
    Crawl a website page and extract audio file links.
    With depth > 1, follows links on the page to find sermon detail pages.
    """
    if not HAS_BS4:
        log.error("beautifulsoup4 not installed. Run: pip install beautifulsoup4")
        sys.exit(1)

    visited = set()
    audio_items = []
    base_domain = urlparse(url).netloc

    def crawl_page(page_url: str, current_depth: int):
        if page_url in visited or current_depth > depth:
            return
        visited.add(page_url)

        log.info(f"Scanning: {page_url} (depth {current_depth})")
        try:
            resp = requests.get(page_url, timeout=30, headers={
                "User-Agent": "Mozilla/5.0 (ShepherdsGuild Sermon Scraper)"
            })
            resp.raise_for_status()
        except requests.RequestException as e:
            log.warning(f"Failed to fetch {page_url}: {e}")
            return

        soup = BeautifulSoup(resp.text, "html.parser")

        # Find direct audio links
        for tag in soup.find_all(["a", "source", "audio"]):
            href = tag.get("href") or tag.get("src") or ""
            href = urljoin(page_url, href)

            if any(href.lower().endswith(ext) for ext in AUDIO_EXTENSIONS):
                # Try to extract a title from context
                title = (
                    tag.get("title") or
                    tag.get("aria-label") or
                    tag.get_text(strip=True) or
                    ""
                )
                # Walk up to find a heading
                if not title:
                    parent = tag.parent
                    for _ in range(5):
                        if parent is None:
                            break
                        heading = parent.find(["h1", "h2", "h3", "h4", "h5"])
                        if heading:
                            title = heading.get_text(strip=True)
                            break
                        parent = parent.parent

                if not title:
                    title = Path(urlparse(href).path).stem

                if href not in {item["audio_url"] for item in audio_items}:
                    audio_items.append({
                        "title": title,
                        "audio_url": href,
                        "date": None,
                        "description": "",
                        "duration": None,
                        "link": page_url,
                    })

        # Follow links to deeper pages (same domain only)
        if current_depth < depth:
            for link_tag in soup.find_all("a", href=True):
                next_url = urljoin(page_url, link_tag["href"])
                if urlparse(next_url).netloc == base_domain:
                    time.sleep(SCAN_DELAY_SEC)
                    crawl_page(next_url, current_depth + 1)

    crawl_page(url, 1)
    log.info(f"Found {len(audio_items)} audio files across {len(visited)} pages")
    return audio_items


def load_url_manifest(csv_path: Path) -> list[dict]:
    """
    Load audio URLs from a CSV file.
    Expected columns: audio_url, title (optional), date (optional)
    """
    items = []
    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if "audio_url" not in row:
                log.error("CSV must have an 'audio_url' column")
                sys.exit(1)
            items.append({
                "title": row.get("title", Path(urlparse(row["audio_url"]).path).stem),
                "audio_url": row["audio_url"],
                "date": row.get("date"),
                "description": row.get("description", ""),
                "duration": row.get("duration"),
                "link": row.get("link"),
            })
    log.info(f"Loaded {len(items)} URLs from {csv_path}")
    return items


# ---------------------------------------------------------------------------
# Phase 2: TRANSCRIBE — Send audio to AssemblyAI
# ---------------------------------------------------------------------------

def transcribe_single(item: dict, transcriber: aai.Transcriber) -> dict:
    """Transcribe a single audio URL. Returns the item dict with transcript added."""
    title = item.get("title", "Unknown")
    audio_url = item["audio_url"]

    log.info(f"Submitting: {title}")
    try:
        transcript = transcriber.transcribe(audio_url)

        if transcript.status == aai.TranscriptStatus.error:
            log.error(f"Transcription error for '{title}': {transcript.error}")
            item["transcript"] = None
            item["_error"] = transcript.error
            return item

        item["transcript"] = transcript.text
        item["_assemblyai_id"] = transcript.id
        item["_audio_duration_sec"] = transcript.audio_duration

        # Get paragraphs for better formatting
        try:
            paragraphs = transcript.get_paragraphs()
            if paragraphs:
                item["transcript_paragraphs"] = [p.text for p in paragraphs]
        except Exception:
            pass

        log.info(
            f"Transcribed: {title} "
            f"({transcript.audio_duration:.0f}s, "
            f"{len(transcript.text):,} chars)"
        )

    except Exception as e:
        log.error(f"Failed to transcribe '{title}': {e}")
        item["transcript"] = None
        item["_error"] = str(e)

    return item


def transcribe_batch(
    items: list[dict],
    max_workers: int = MAX_CONCURRENT_TRANSCRIPTIONS
) -> list[dict]:
    """Transcribe a batch of audio items concurrently."""
    init_assemblyai()

    config = aai.TranscriptionConfig(
        speech_models=["universal-3-pro"],
        punctuate=True,
        format_text=True,
    )
    config = aai.TranscriptionConfig(
        speech_models=["universal-3-pro"],
        punctuate=True,
        format_text=True,
    )
    transcriber = aai.Transcriber(config=config)

    results = []
    total = len(items)

    log.info(f"Starting transcription of {total} items (max {max_workers} concurrent)...")
    start = time.time()

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(transcribe_single, item, transcriber): item
            for item in items
        }

        for i, future in enumerate(as_completed(futures), 1):
            result = future.result()
            results.append(result)
            status = "OK" if result.get("transcript") else "FAILED"
            log.info(f"[{i}/{total}] {status}: {result.get('title', 'Unknown')}")

    elapsed = time.time() - start
    ok = sum(1 for r in results if r.get("transcript"))
    log.info(f"Transcription complete: {ok}/{total} succeeded in {elapsed:.0f}s")

    return results


# ---------------------------------------------------------------------------
# Phase 3: PACKAGE — Output sermonindex-compatible JSON
# ---------------------------------------------------------------------------

def package_to_sermonindex_json(
    item: dict,
    preacher: str,
    output_dir: Path
) -> Optional[Path]:
    """
    Convert a transcribed item into a sermonindex-compatible JSON file
    that pipeline.py can consume directly.
    """
    if not item.get("transcript"):
        return None

    slug = slugify(item.get("title", "unknown"))
    output_path = output_dir / f"{slug}.json"

    # Build the sermonindex-compatible structure
    si_json = {
        "id": item.get("_assemblyai_id", slug),
        "title": item.get("title"),
        "contributor": preacher,
        "description": item.get("description", ""),
        "transcript": item["transcript"],
        "topics": [],
        "bibleReferences": [],
        "duration": item.get("_audio_duration_sec") or item.get("duration"),
        "audioUrl": item.get("audio_url"),
        "views": None,
        "_source": {
            "method": "sermon_scraper",
            "source_url": item.get("link"),
            "audio_url": item.get("audio_url"),
            "scraped_at": datetime.utcnow().isoformat() + "Z",
            "assemblyai_id": item.get("_assemblyai_id"),
            "audio_duration_sec": item.get("_audio_duration_sec"),
        }
    }

    # If we have the date, try to parse and include it
    if item.get("date"):
        si_json["date"] = item["date"]

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(si_json, f, indent=2, ensure_ascii=False)

    return output_path


def package_results(
    results: list[dict],
    preacher: str,
    output_dir: Path
) -> dict:
    """Package all successful transcriptions into sermonindex JSON files."""
    succeeded = 0
    failed = 0
    output_files = []

    for item in results:
        path = package_to_sermonindex_json(item, preacher, output_dir)
        if path:
            succeeded += 1
            output_files.append(str(path))
            log.info(f"Saved: {path.name}")
        else:
            failed += 1

    # Save a manifest of what was processed
    manifest = {
        "preacher": preacher,
        "total": len(results),
        "succeeded": succeeded,
        "failed": failed,
        "output_dir": str(output_dir),
        "files": output_files,
        "errors": [
            {"title": r.get("title"), "error": r.get("_error")}
            for r in results if not r.get("transcript")
        ],
        "packaged_at": datetime.utcnow().isoformat() + "Z",
    }

    manifest_path = output_dir / "_manifest.json"
    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=2)

    log.info(f"\n{'='*60}")
    log.info(f"PACKAGING COMPLETE")
    log.info(f"{'='*60}")
    log.info(f"Succeeded: {succeeded}")
    log.info(f"Failed: {failed}")
    log.info(f"Output: {output_dir}")
    log.info(f"Manifest: {manifest_path}")
    log.info(f"\nTo decompose these sermons:")
    log.info(f"  python pipeline.py batch {output_dir}/ --preacher \"{preacher}\" --canonical")
    log.info(f"  python pipeline_batch.py submit {output_dir}/ --preacher \"{preacher}\" --canonical")

    return manifest


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(
        description="Shepherd's Guild — Sermon Audio Scraper & Transcriber"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # --- rss ---
    p_rss = subparsers.add_parser(
        "rss", help="Scan a podcast RSS feed for sermon audio"
    )
    p_rss.add_argument("feed_url", help="URL of the RSS/podcast feed")
    p_rss.add_argument("--preacher", required=True, help="Preacher name")
    p_rss.add_argument("--scan-only", action="store_true",
                        help="Discover audio files without transcribing")
    p_rss.add_argument("--resume", action="store_true",
                        help="Skip files that already have output JSON")
    p_rss.add_argument("--limit", type=int, default=None,
                        help="Limit number of episodes to process")
    p_rss.add_argument("--output", type=Path, default=None,
                        help="Output directory (default: transcripts/<preacher-slug>/)")
    p_rss.add_argument("--workers", type=int, default=MAX_CONCURRENT_TRANSCRIPTIONS,
                        help=f"Max concurrent transcriptions (default: {MAX_CONCURRENT_TRANSCRIPTIONS})")

    # --- website ---
    p_web = subparsers.add_parser(
        "website", help="Scan a church website for sermon audio"
    )
    p_web.add_argument("url", help="URL of the sermons page")
    p_web.add_argument("--preacher", required=True, help="Preacher name")
    p_web.add_argument("--depth", type=int, default=1,
                        help="How many link levels deep to crawl (default: 1)")
    p_web.add_argument("--scan-only", action="store_true",
                        help="Discover audio files without transcribing")
    p_web.add_argument("--resume", action="store_true",
                        help="Skip files that already have output JSON")
    p_web.add_argument("--limit", type=int, default=None,
                        help="Limit number of files to process")
    p_web.add_argument("--output", type=Path, default=None,
                        help="Output directory")
    p_web.add_argument("--workers", type=int, default=MAX_CONCURRENT_TRANSCRIPTIONS,
                        help=f"Max concurrent transcriptions (default: {MAX_CONCURRENT_TRANSCRIPTIONS})")

    # --- urls ---
    p_urls = subparsers.add_parser(
        "urls", help="Transcribe from a CSV of audio URLs"
    )
    p_urls.add_argument("csv_file", type=Path, help="CSV with audio_url column")
    p_urls.add_argument("--preacher", required=True, help="Preacher name")
    p_urls.add_argument("--resume", action="store_true",
                        help="Skip files that already have output JSON")
    p_urls.add_argument("--limit", type=int, default=None,
                        help="Limit number of files to process")
    p_urls.add_argument("--output", type=Path, default=None,
                        help="Output directory")
    p_urls.add_argument("--workers", type=int, default=MAX_CONCURRENT_TRANSCRIPTIONS,
                        help=f"Max concurrent transcriptions (default: {MAX_CONCURRENT_TRANSCRIPTIONS})")

    args = parser.parse_args()

    # Determine output directory
    if hasattr(args, "output") and args.output:
        out_dir = args.output
    else:
        out_dir = OUTPUT_DIR / slugify(args.preacher)
    out_dir.mkdir(parents=True, exist_ok=True)

    # Phase 1: SCAN
    if args.command == "rss":
        items = scan_rss_feed(args.feed_url)
    elif args.command == "website":
        items = scan_website(args.url, depth=args.depth)
    elif args.command == "urls":
        items = load_url_manifest(args.csv_file)
    else:
        log.error(f"Unknown command: {args.command}")
        sys.exit(1)

    if not items:
        log.error("No audio items found. Nothing to do.")
        return

    # Apply limit
    if args.limit:
        items = items[:args.limit]
        log.info(f"Limited to {len(items)} items")

    # Resume: skip already-processed files
    if hasattr(args, "resume") and args.resume:
        existing = {f.stem for f in out_dir.glob("*.json") if f.name != "_manifest.json"}
        before = len(items)
        items = [i for i in items if slugify(i.get("title", "unknown")) not in existing]
        skipped = before - len(items)
        if skipped:
            log.info(f"Resuming: skipped {skipped} already-processed files")

    if not items:
        log.info("All items already processed. Nothing to do.")
        return

    # Save scan results
    scan_path = out_dir / "_scan_results.json"
    with open(scan_path, "w") as f:
        json.dump(items, f, indent=2, ensure_ascii=False)
    log.info(f"Scan results saved: {scan_path}")

    # Scan-only mode
    if hasattr(args, "scan_only") and args.scan_only:
        log.info(f"\nSCAN ONLY — found {len(items)} audio items:")
        for i, item in enumerate(items, 1):
            log.info(f"  {i}. {item.get('title', 'Unknown')}")
            log.info(f"     {item.get('audio_url', 'No URL')}")
        log.info(f"\nTo transcribe, run again without --scan-only")
        return

    # Phase 2: TRANSCRIBE
    workers = getattr(args, "workers", MAX_CONCURRENT_TRANSCRIPTIONS)
    results = transcribe_batch(items, max_workers=workers)

    # Phase 3: PACKAGE
    package_results(results, args.preacher, out_dir)


if __name__ == "__main__":
    main()
```

---

### Millwerx — Public Domain Text Acquisition Pipeline

Millwerx is Shepherd's Guild's internal pipeline for acquiring, cleaning, processing, and decomposing **public domain theological texts**. The name reflects the function: a mill takes raw grain and produces usable flour. Millwerx takes raw historical text and produces structured, machine-readable, annotated data.

Millwerx is **not a one-time project** — it is an ongoing operation. Every text processed is permanent inventory feeding multiple products simultaneously:

- **Guild Hall reference library** — benchmark preacher profiles from historical masters
- **Shepherd's Guild Daily** — 3-day attribute cycle devotional database
- **TRAININGDATA** — labeled theological reasoning corpus for AI lab licensing

**Scope:** Only texts verifiably in the US public domain (pre-1928 publication), openly licensed (Creative Commons), or with a valid commercial license from the rights holder. When in doubt, do not process.

#### Primary Source Targets

**Guild Hall Reference Library:**

| Author | Key Works | PD Status | Priority |
|---|---|---|---|
| Charles Spurgeon (1834–1892) | Metropolitan Tabernacle Pulpit (63 vols), Morning & Evening | Confirmed PD | CRITICAL |
| G. Campbell Morgan (1863–1945) | Westminster Pulpit (10 vols), The Analyzed Bible | Confirmed PD | HIGH |
| R.A. Torrey (1856–1928) | Various sermon collections | Confirmed PD | MEDIUM |
| Alexander Maclaren (1826–1910) | Expositions of Holy Scripture (32 vols) | Confirmed PD | MEDIUM |
| F.B. Meyer (1847–1929) | Various devotional and expository works | Likely PD — verify | MEDIUM |
| J.C. Ryle (1816–1900) | Expository Thoughts on the Gospels, Holiness | Confirmed PD | MEDIUM |

**Shepherd's Guild Daily — Devotional Database:**

| Author | Key Works | PD Status | Priority |
|---|---|---|---|
| Stephen Charnock (1628–1680) | Existence and Attributes of God | Confirmed PD | CRITICAL |
| Thomas Watson (1620–1686) | A Body of Divinity, The Ten Commandments | Confirmed PD | CRITICAL |
| John Owen (1616–1683) | Communion with God, Mortification of Sin | Confirmed PD | HIGH |
| William Gurnall (1616–1679) | The Christian in Complete Armour | Confirmed PD | HIGH |
| Thomas Brooks (1608–1680) | Precious Remedies Against Satan's Devices | Confirmed PD | MEDIUM |
| A.W. Pink (1886–1952) | The Attributes of God | Likely PD — verify pub date | HIGH |
| A.W. Tozer (1897–1963) | The Knowledge of the Holy | NOT PD — license required | MEDIUM — legal track |

**Verified Source Repositories:** CCEL (ccel.org), Project Gutenberg (gutenberg.org), Internet Archive (archive.org), Spurgeon.org, Monergism.com.

#### Millwerx Five-Stage Pipeline

Unlike the sermon decomposition pipeline (which processes modern transcripts through a single LLM pass), Millwerx uses a **tri-stage chunker architecture** optimized for lengthy historical texts:

**Stage 1 — Acquisition:** Download from verified repositories. Confirm PD status. File naming: `millwerx_[author-lastname]_[short-title]_[year-pub].[ext]`. Log in acquisition registry.

**Stage 2 — Cleaning:** Remove publisher introductions, modern footnotes, page numbers, OCR artifacts, copyright notices. Preserve original chapter divisions, the author's own footnotes, archaic spelling, and paragraph structure. Quality bar: spot-check 3 random passages — if any contain artifacts, return to cleaning.

**Stage 3 — Structure Extraction (Cheap Model):** Use a cheap/fast model to extract the document's structural outline as `outline.json` — chapter headings, numbered propositions, doctrinal statements, objection/answer pairs. This stage requires pattern recognition, not theological reasoning.

**Stage 4 — Chunking (Local):** Use the outline to produce semantically coherent chunks. Strategy varies by text type:

| Text Type | Primary Chunk Boundary | Typical Chunk Size |
|---|---|---|
| Systematic theology (Watson, Charnock) | Numbered proposition or doctrine | 600–1500 words |
| Expository sermons (Spurgeon, Morgan) | Full sermon — pass to decomp pipeline | Full sermon text |
| Devotional works (Brooks, Pink) | Chapter or numbered section | 400–1000 words |
| Commentary (Maclaren, Ryle) | Passage heading or chapter | 500–1200 words |

**Important:** Spurgeon and Morgan sermons bypass the chunker entirely — they go through the full Sermon Decomposition Spec v3 pipeline instead.

**Stage 5 — Enrichment (Expensive Model):** Add semantic metadata: doctrinal loci tags (same 16-category taxonomy as decomp spec), 2–3 sentence summary, key claim, scripture references, quotation extraction, and devotional cycle candidate tagging (attribute + devotional type classification).

#### Devotional Cycle Architecture

The Shepherd's Guild Daily devotional uses a **3-day attribute cycle** rotating through divine attributes. Each day's devotional draws from the enriched Millwerx corpus, tagged with:

- `attribute` — which divine attribute the passage illuminates (e.g., Holiness, Omniscience, Mercy)
- `devotional_type` — Day 1: Theological Foundation, Day 2: Scriptural Meditation, Day 3: Practical Application
- `communicable` — whether the attribute is one believers are called to reflect (love, faithfulness) or one that belongs to God alone (omnipotence, aseity)

**Working Attribute List:** Holiness, Love, Omniscience, Omnipotence, Omnipresence, Sovereignty, Faithfulness, Goodness, Justice, Mercy, Grace, Wisdom, Immutability, Eternality, Self-Sufficiency (Aseity), Trinity, Patience/Long-Suffering, Truth/Veracity.

#### Cost Model

| Operation | Model | Cost | Notes |
|---|---|---|---|
| Structure extraction (Stage 3) | Haiku/Flash | ~$0.05–0.10 per book | Cheap pattern recognition |
| Chunk enrichment (Stage 5) | Sonnet | ~$0.01–0.03 per chunk | Theological reasoning required |
| Full book enrichment | Sonnet | ~$5–15 per book | Depends on length and chunk density |

Processing economics are strong. A complete Charnock corpus at $10–15 produces a permanent devotional database asset feeding Shepherd's Guild Daily indefinitely.

*For the complete Millwerx Internal Product Guide including acquisition registry templates, enrichment prompt specifications, and the full working attribute list, see the separate `millwerx-product-guide.docx`.*


---

## 2. Infrastructure: Decomposition Pipeline

Once sermon transcripts have been downloaded, they are processed through the V3 decomp process. The decomp tool classifies sermon units into a structured JSON using Claude Sonnet, then embeds them via Voyage 3.5 and stores everything in Supabase.

---

### Decomposition Spec v2

The spec that defines the JSON schema for decomposed sermons. This is sent as the system prompt to Claude Sonnet during decomposition.

```markdown
# Sermon Corpus Decomposition Spec v2

## Purpose

Transform a sermon manuscript into a structured JSON document containing functional units with rich theological metadata. The output serves as the canonical record for semantic search, cross-referencing, voice replication, and derivative content generation.

---

## Sermon-Level Fields

**`title`** — As given or inferred from the manuscript.

**`preacher`** — Name.

**`date`** — If detectable.

**`primary_text`** — The main scripture passage for the sermon as a whole.

**`sermon_type`** — Enum: `expository`, `topical`, `textual`, `narrative`, `polemic`.

**`series_name`** — If detectable.

**`series_position`** — "Part 3 of 7" if detectable.

**`abstract`** — 4-6 sentences. The sermon's argument in compressed form. Not a teaser — a genuine summary capturing the logical arc.

**`main_thesis`** — One sentence. The sermon's controlling claim.

**`target_audience_cues`** — Detectable signals about who the sermon addresses. "New believers," "parents," "leaders," "the whole congregation."

**`tone`** — Enum array: `pastoral`, `prophetic`, `didactic`, `celebratory`, `lament`, `polemic`, `evangelistic`.

**`hermeneutical_method`** — Enum array:
- `grammatical_historical` — Close attention to original language, historical context, authorial intent.
- `redemptive_historical` — Passage read as a moment in the unfolding drama of redemption. Christotelic reading.
- `canonical` — Interpreting in light of the whole canon. Scripture interprets Scripture as active method.
- `applicatory` — Primary emphasis on "what does this mean for us" with less exegetical scaffolding.
- `polemic` — Passage marshaled to refute an error or defend a contested doctrine.

**`all_quotations`** — Rolled-up array of every human-author quotation in the sermon with `unit_index` reference.

**`all_cross_references`** — Rolled-up array of every scripture citation from outside the primary text with `unit_index` reference.

---

## Unit-Level Fields

Each sermon is decomposed into **functional units** — sections defined by rhetorical function shift, not character count.

### Core Fields

**`unit_index`** — Integer. Sequential position in the sermon.

**`rhetorical_function`** — Enum:
- `exposition` — Direct engagement with the biblical text. Exegesis, word studies, contextual background.
- `theological_claim` — A doctrinal assertion derived from or supported by the exposition.
- `illustration` — Story, analogy, historical example serving the argument.
- `application` — Direct address about what to do, believe, or become.
- `introduction` — Opening frame. Sets up the text, the problem, the question.
- `conclusion` — Closing frame. Summarizes, reiterates, issues final charge.
- `transition` — Connective tissue between major sections.
- `pastoral_aside` — Direct shepherding moment stepping outside the expositional flow.
- `prayer` — Opening, closing, or mid-sermon prayer.

**`content`** — Verbatim text of the unit. No summarization, no truncation.

**`summary`** — 2-3 sentences. What this unit accomplishes in the sermon's argument.

**`key_claim`** — One sentence. The single most important assertion. Null for transitions, prayers, some illustrations.

---

### Three-Tier Citation Architecture

Three fundamentally different kinds of cited material require different retrieval paths.

#### Tier 1: `primary_text_citations`

Verses from the sermon's own passage — the text being exposited. The pastor reads Exodus 5:22-23 because that is the passage under examination. Source material, not quotation.

Array of objects:
- `reference` — Book, chapter, verse.
- `mode` — Enum: `full_reading`, `partial_reading`, `reference_in_passing`.

#### Tier 2: `cross_references`

Scripture from outside the primary passage, brought in for support, contrast, illumination, or typological connection.

Array of objects:
- `reference` — Book, chapter, verse.
- `function` — Enum: `authority`, `contrast`, `echo`, `fulfillment`, `parallel`, `corrective`.
- `supports_claim` — One sentence identifying which argument this cross-reference serves.

#### Tier 3: `quotations`

Human authors only. Not scripture — scripture is handled in Tiers 1 and 2.

Array of objects:
- `text` — Verbatim quote as it appears in the manuscript.
- `attribution` — Who said it. Capture exactly what the manuscript gives.
- `source` — The work it's from if identifiable. Null if unspecified.
- `function` — Enum: `authority`, `illustration`, `provocation`, `devotional`, `opponent`.

---

### Theological Metadata

**`doctrinal_loci`** — Array. Controlled taxonomy:
- Theology Proper (doctrine of God)
- Christology
- Pneumatology (Holy Spirit)
- Soteriology (salvation)
- Hamartiology (sin)
- Anthropology (doctrine of humanity)
- Ecclesiology (church)
- Eschatology (last things)
- Bibliology (Scripture)
- Sanctification
- Providence / Sovereignty
- Covenant Theology
- Ethics / Moral Theology
- Doxology / Worship
- Spiritual Warfare
- Pastoral Theology

**`biblical_theological_moves`** — Array of objects. Detected instances of biblical theology — redemptive-historical trajectories, typological connections, progressive revelation, intertextual echoes.

- `type` — Enum: `typology`, `fulfillment`, `progressive_revelation`, `narrative_arc`, `intertextual_echo`, `contrast`, `thematic_thread`.
- `source_text` — The earlier canonical reference being drawn from.
- `target_text` — The later canonical reference where fulfillment/echo/development lands.
- `pastor_framing` — One sentence capturing how the pastor articulated the connection. Their specific language — reveals hermeneutical instincts and serves voice replication.

---

### Additional Unit Fields

**`people_referenced`** — Array. Historical figures, theologians, biblical characters mentioned.

**`sermon_series_context`** — How this unit connects to the broader series if detectable.

---

## Processing Notes

- Units are defined by rhetorical function shift, not paragraph breaks or character count.
- A unit can be a single sentence (transitions) or several paragraphs (extended exposition).
- When exposition and application weave within a single paragraph, split at the function boundary — even mid-paragraph.
- The `content` field preserves the pastor's exact language. No paraphrasing, no cleanup, no grammatical correction. The voice is the asset.
- If a field cannot be determined from the manuscript, set it to null. Do not fabricate metadata.
```

---

### pipeline.py — Single-Sermon Pipeline v3.1

Three-stage pipeline: **DECOMPOSE** (send transcript to Anthropic API with v3 spec → JSON) → **EMBED** (generate Voyage 3.5 embeddings) → **INGEST** (write normalized rows to Supabase). Includes full taxonomy sanitization on all constrained fields.

```python
"""
Shepherd's Guild — Sermon Decomposition Pipeline v3.1
=====================================================

Three-stage pipeline:
  1. DECOMPOSE  — Send transcript to Anthropic API with v3 spec → JSON
  2. EMBED      — Generate Voyage 3.5 embeddings for each unit's content
  3. INGEST     — Write normalized rows to Supabase

Usage:
  # Single sermon (.txt)
  python pipeline.py decompose transcript.txt --preacher "John MacArthur"

  # Single sermon (sermonindex .json — preacher auto-detected)
  python pipeline.py decompose sermon.json

  # Batch - all .txt and .json files in a folder
  python pipeline.py batch ./transcripts/ --preacher "John MacArthur"

  # Batch sermonindex JSONs (preacher auto-detected per file)
  python pipeline.py batch ./sermon-transcripts/da-carson/

  # Just embed + ingest a previously decomposed JSON
  python pipeline.py ingest decomposed.json --preacher "John MacArthur"

  # Decompose only (no database write) — for QA review
  python pipeline.py decompose transcript.txt --preacher "John MacArthur" --dry-run

Environment variables (set in .env or export):
  ANTHROPIC_API_KEY   — Your Anthropic API key
  VOYAGE_API_KEY      — Your Voyage AI API key
  SUPABASE_URL        — Your Supabase project URL
  SUPABASE_KEY        — Your Supabase service role key
"""

import os
import sys
import json
import time
import argparse
import logging
from pathlib import Path
from datetime import datetime
from typing import Optional

# ---------------------------------------------------------------------------
# Dependencies — install with:
#   pip install anthropic voyageai supabase python-dotenv
# ---------------------------------------------------------------------------
try:
    import anthropic
    import voyageai
    from supabase import create_client, Client
    from dotenv import load_dotenv
except ImportError as e:
    print(f"Missing dependency: {e}")
    print("Install with: pip install anthropic voyageai supabase python-dotenv")
    sys.exit(1)

load_dotenv()

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
ANTHROPIC_MODEL = "claude-sonnet-4-5-20250929"
VOYAGE_MODEL = "voyage-3.5"
VOYAGE_DIMENSIONS = 1024
SPEC_VERSION = "v3"

# Rate limiting
DECOMPOSE_DELAY_SEC = 2
EMBED_BATCH_SIZE = 32
EMBED_DELAY_SEC = 0.5

# Paths
SPEC_PATH = Path(__file__).parent / "sermon-decomposition-spec-v3.md"
OUTPUT_DIR = Path(__file__).parent / "output"
OUTPUT_DIR.mkdir(exist_ok=True)

# ---------------------------------------------------------------------------
# Taxonomy Validation Sets
# Every enum field that touches the database gets a validation set.
# The sanitizer strips invalid values and logs warnings.
# This catches model taxonomy drift without crashing the pipeline.
# ---------------------------------------------------------------------------
VALID_SERMON_TYPES = {
    "expository", "topical", "textual", "narrative", "polemic"
}

VALID_TONES = {
    "pastoral", "prophetic", "didactic", "celebratory",
    "lament", "polemic", "evangelistic"
}

VALID_HERMENEUTICAL_METHODS = {
    "grammatical_historical", "redemptive_historical",
    "canonical", "applicatory", "polemic"
}

VALID_RHETORICAL_FUNCTIONS = {
    "exposition", "theological_claim", "illustration", "application",
    "introduction", "conclusion", "transition", "pastoral_aside", "prayer"
}

VALID_REGISTERS = {
    "logos", "pathos", "ethos", "narrative", "doxological"
}

VALID_LOCI = {
    "Theology Proper", "Christology", "Pneumatology", "Soteriology",
    "Hamartiology", "Anthropology", "Ecclesiology", "Eschatology",
    "Bibliology", "Sanctification", "Providence / Sovereignty",
    "Covenant Theology", "Ethics / Moral Theology", "Doxology / Worship",
    "Spiritual Warfare", "Pastoral Theology"
}

VALID_ILLUSTRATION_TYPES = {
    "personal_story", "historical_example", "analogy",
    "hypothetical", "cultural_reference"
}

VALID_APPLICATION_SPECIFICITY = {
    "abstract", "concrete", "mixed"
}

VALID_CITATION_MODES = {
    "full_reading", "partial_reading", "reference_in_passing"
}

VALID_CITATION_FUNCTIONS = {
    "authority", "contrast", "echo", "fulfillment", "parallel", "corrective"
}

VALID_QUOTATION_FUNCTIONS = {
    "authority", "illustration", "provocation", "devotional", "opponent"
}

VALID_BT_TYPES = {
    "typology", "fulfillment", "progressive_revelation", "narrative_arc",
    "intertextual_echo", "contrast", "thematic_thread"
}

# Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S"
)
log = logging.getLogger("pipeline")


# ---------------------------------------------------------------------------
# Sanitizer helpers
# ---------------------------------------------------------------------------
def sanitize_enum(value, valid_set, field_name, context=""):
    """Sanitize a single enum value. Returns value if valid, None if not."""
    if value is None:
        return None
    if value in valid_set:
        return value
    log.warning(f"{context}invalid {field_name}: '{value}' (removed)")
    return None


def sanitize_enum_array(values, valid_set, field_name, context=""):
    """Sanitize an array of enum values. Returns only valid values."""
    if not values:
        return []
    clean = [v for v in values if v in valid_set]
    bad = set(values) - valid_set
    if bad:
        log.warning(f"{context}invalid {field_name} removed: {bad}")
    return clean


# ---------------------------------------------------------------------------
# Clients (initialized lazily)
# ---------------------------------------------------------------------------
_anthropic_client = None
_voyage_client = None
_supabase_client = None


def get_anthropic() -> anthropic.Anthropic:
    global _anthropic_client
    if _anthropic_client is None:
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            raise EnvironmentError("ANTHROPIC_API_KEY not set")
        _anthropic_client = anthropic.Anthropic(api_key=api_key)
    return _anthropic_client


def get_voyage() -> voyageai.Client:
    global _voyage_client
    if _voyage_client is None:
        api_key = os.getenv("VOYAGE_API_KEY")
        if not api_key:
            raise EnvironmentError("VOYAGE_API_KEY not set")
        _voyage_client = voyageai.Client(api_key=api_key)
    return _voyage_client


def get_supabase() -> Client:
    global _supabase_client
    if _supabase_client is None:
        url = os.getenv("SUPABASE_URL")
        key = os.getenv("SUPABASE_KEY")
        if not url or not key:
            raise EnvironmentError("SUPABASE_URL and SUPABASE_KEY must be set")
        _supabase_client = create_client(url, key)
    return _supabase_client


# ---------------------------------------------------------------------------
# SermonIndex JSON reader
# ---------------------------------------------------------------------------
def is_sermonindex_json(filepath: Path) -> bool:
    """Check if a JSON file is a sermonindex format."""
    if filepath.suffix.lower() != ".json":
        return False
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
        return "transcript" in data and "contributor" in data
    except (json.JSONDecodeError, KeyError):
        return False


def read_sermonindex_json(filepath: Path) -> dict:
    """Read a sermonindex JSON and extract metadata + transcript."""
    with open(filepath, "r", encoding="utf-8") as f:
        data = json.load(f)

    transcript = data.get("transcript")
    if not transcript:
        raise ValueError(f"No transcript in {filepath.name}")

    refs = data.get("bibleReferences") or []
    primary_text = None
    if refs:
        primary_text = refs[0].get("text", None)

    return {
        "transcript": transcript,
        "preacher": data.get("contributor", "Unknown"),
        "title": data.get("title"),
        "primary_text": primary_text,
        "si_metadata": {
            "sermonindex_id": data.get("id"),
            "description": data.get("description"),
            "topics": data.get("topics"),
            "bible_references": refs,
            "duration": data.get("duration"),
            "audio_url": data.get("audioUrl"),
            "views": data.get("views"),
        }
    }


# ---------------------------------------------------------------------------
# Stage 1: DECOMPOSE
# ---------------------------------------------------------------------------
def load_spec() -> str:
    """Load the v3 decomposition spec as the system prompt."""
    if not SPEC_PATH.exists():
        raise FileNotFoundError(
            f"Spec not found at {SPEC_PATH}. "
            f"Place sermon-decomposition-spec-v3.md next to this script."
        )
    return SPEC_PATH.read_text(encoding="utf-8")


def decompose_sermon(
    transcript: str,
    preacher: str,
    known_title: Optional[str] = None,
    known_primary_text: Optional[str] = None
) -> dict:
    """
    Send a sermon transcript to Claude and get back structured JSON
    per the v3 decomposition spec.
    """
    client = get_anthropic()
    spec = load_spec()

    metadata_hints = f"The preacher is: {preacher}"
    if known_title:
        metadata_hints += f"\nThe sermon title is: {known_title}"
    if known_primary_text:
        metadata_hints += f"\nThe primary text is: {known_primary_text}"

    system_prompt = (
        f"{spec}\n\n"
        f"---\n\n"
        f"You are a sermon decomposition engine. Given a sermon transcript, "
        f"produce a single JSON object conforming exactly to the spec above. "
        f"Output ONLY valid JSON — no markdown fences, no commentary, no preamble.\n\n"
        f"{metadata_hints}"
    )

    user_message = (
        f"Decompose the following sermon transcript:\n\n"
        f"---\n\n"
        f"{transcript}"
    )

    log.info(f"Sending to {ANTHROPIC_MODEL} ({len(transcript):,} chars)...")
    start = time.time()

    with client.messages.stream(
        model=ANTHROPIC_MODEL,
        max_tokens=64000,
        system=system_prompt,
        messages=[{"role": "user", "content": user_message}]
    ) as stream:
        for event in stream:
            pass
        response = stream.get_final_message()

    elapsed = time.time() - start
    input_tokens = response.usage.input_tokens
    output_tokens = response.usage.output_tokens

    log.info(
        f"Decomposition complete: {input_tokens:,} in / {output_tokens:,} out "
        f"({elapsed:.1f}s)"
    )

    raw_text = response.content[0].text.strip()

    if raw_text.startswith("```"):
        raw_text = raw_text.split("\n", 1)[1]
    if raw_text.endswith("```"):
        raw_text = raw_text.rsplit("```", 1)[0]
    raw_text = raw_text.strip()

    try:
        decomposition = json.loads(raw_text)
    except json.JSONDecodeError as e:
        log.error(f"Failed to parse JSON response: {e}")
        log.error(f"First 500 chars: {raw_text[:500]}")
        debug_path = OUTPUT_DIR / f"debug_raw_{int(time.time())}.txt"
        debug_path.write_text(raw_text, encoding="utf-8")
        log.error(f"Raw output saved to {debug_path}")
        raise

    decomposition["_pipeline"] = {
        "spec_version": SPEC_VERSION,
        "model": ANTHROPIC_MODEL,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "processing_seconds": round(elapsed, 1),
        "processing_cost_usd": round(
            (input_tokens / 1_000_000 * 3.0) + (output_tokens / 1_000_000 * 15.0),
            4
        ),
        "decomposed_at": datetime.utcnow().isoformat() + "Z"
    }

    return decomposition


# ---------------------------------------------------------------------------
# Stage 2: EMBED
# ---------------------------------------------------------------------------
def embed_units(units: list[dict]) -> list[list[float]]:
    """Generate Voyage 3.5 embeddings for each unit's content field."""
    client = get_voyage()
    texts = [u["content"] for u in units]

    all_embeddings = []
    total_batches = (len(texts) + EMBED_BATCH_SIZE - 1) // EMBED_BATCH_SIZE

    for i in range(0, len(texts), EMBED_BATCH_SIZE):
        batch = texts[i:i + EMBED_BATCH_SIZE]
        batch_num = (i // EMBED_BATCH_SIZE) + 1
        log.info(f"Embedding batch {batch_num}/{total_batches} ({len(batch)} units)...")

        result = client.embed(
            batch,
            model=VOYAGE_MODEL,
            input_type="document",
            output_dimension=VOYAGE_DIMENSIONS
        )
        all_embeddings.extend(result.embeddings)

        if batch_num < total_batches:
            time.sleep(EMBED_DELAY_SEC)

    log.info(f"Embedded {len(all_embeddings)} units ({VOYAGE_DIMENSIONS} dims each)")
    return all_embeddings


# ---------------------------------------------------------------------------
# Stage 3: INGEST (with full sanitization)
# ---------------------------------------------------------------------------
def ensure_preacher(preacher_name: str, is_canonical: bool = False) -> str:
    """Get or create a preacher record. Returns the preacher UUID."""
    sb = get_supabase()

    result = sb.table("preachers").select("id").eq("name", preacher_name).execute()
    if result.data:
        preacher_id = result.data[0]["id"]
        log.info(f"Found existing preacher: {preacher_name} ({preacher_id})")
        return preacher_id

    result = sb.table("preachers").insert({
        "name": preacher_name,
        "is_canonical": is_canonical,
        "is_public": False
    }).execute()

    preacher_id = result.data[0]["id"]
    log.info(f"Created preacher: {preacher_name} ({preacher_id})")
    return preacher_id


def ingest_sermon(
    decomposition: dict,
    preacher_id: str,
    embeddings: list[list[float]],
    raw_transcript: Optional[str] = None
) -> str:
    """Write a decomposed sermon to Supabase with full sanitization."""
    sb = get_supabase()
    pipeline_meta = decomposition.get("_pipeline", {})
    units = decomposition.get("units", [])

    if len(embeddings) != len(units):
        raise ValueError(
            f"Embedding count ({len(embeddings)}) doesn't match "
            f"unit count ({len(units)})"
        )

    # --- Sanitize sermon-level fields ---
    sermon_data = {
        "preacher_id": preacher_id,
        "title": decomposition.get("title"),
        "date": decomposition.get("date"),
        "primary_text": decomposition.get("primary_text"),
        "sermon_type": sanitize_enum(
            decomposition.get("sermon_type"),
            VALID_SERMON_TYPES, "sermon_type", "Sermon: "
        ),
        "series_name": decomposition.get("series_name"),
        "series_position": decomposition.get("series_position"),
        "abstract": decomposition.get("abstract"),
        "main_thesis": decomposition.get("main_thesis"),
        "target_audience_cues": decomposition.get("target_audience_cues"),
        "tone": sanitize_enum_array(
            decomposition.get("tone"),
            VALID_TONES, "tone", "Sermon: "
        ),
        "hermeneutical_method": sanitize_enum_array(
            decomposition.get("hermeneutical_method"),
            VALID_HERMENEUTICAL_METHODS, "hermeneutical_method", "Sermon: "
        ),
        "raw_transcript": raw_transcript,
        "spec_version": pipeline_meta.get("spec_version", SPEC_VERSION),
        "decomposed_at": pipeline_meta.get("decomposed_at"),
        "decomposition_model": pipeline_meta.get("model"),
        "input_tokens": pipeline_meta.get("input_tokens"),
        "output_tokens": pipeline_meta.get("output_tokens"),
        "processing_cost_usd": pipeline_meta.get("processing_cost_usd"),
    }

    result = sb.table("sermons").insert(sermon_data).execute()
    sermon_id = result.data[0]["id"]
    log.info(f"Inserted sermon: {decomposition.get('title')} ({sermon_id})")

    # --- Insert units with full sanitization ---
    for i, unit in enumerate(units):
        ctx = f"Unit {unit.get('unit_index', i)}: "

        unit_data = {
            "sermon_id": sermon_id,
            "unit_index": unit.get("unit_index", i),
            "rhetorical_function": sanitize_enum(
                unit.get("rhetorical_function"),
                VALID_RHETORICAL_FUNCTIONS, "rhetorical_function", ctx
            ),
            "content": unit.get("content"),
            "summary": unit.get("summary"),
            "key_claim": unit.get("key_claim"),
            "illustration_type": sanitize_enum(
                unit.get("illustration_type"),
                VALID_ILLUSTRATION_TYPES, "illustration_type", ctx
            ),
            "application_specificity": sanitize_enum(
                unit.get("application_specificity"),
                VALID_APPLICATION_SPECIFICITY, "application_specificity", ctx
            ),
            "rhetorical_register": sanitize_enum_array(
                unit.get("rhetorical_register"),
                VALID_REGISTERS, "rhetorical_register", ctx
            ),
            "doctrinal_loci": sanitize_enum_array(
                unit.get("doctrinal_loci"),
                VALID_LOCI, "doctrinal_loci", ctx
            ),
            "people_referenced": unit.get("people_referenced"),
            "sermon_series_context": unit.get("sermon_series_context"),
            "embedding": embeddings[i],
        }

        unit_result = sb.table("units").insert(unit_data).execute()
        unit_id = unit_result.data[0]["id"]

        # --- Insert Tier 1 citations (primary text) ---
        for citation in unit.get("primary_text_citations", []) or []:
            sb.table("citations").insert({
                "unit_id": unit_id,
                "tier": 1,
                "reference": citation.get("reference"),
                "mode": sanitize_enum(
                    citation.get("mode"),
                    VALID_CITATION_MODES, "citation mode", ctx
                ),
            }).execute()

        # --- Insert Tier 2 citations (cross-references) ---
        for xref in unit.get("cross_references", []) or []:
            sb.table("citations").insert({
                "unit_id": unit_id,
                "tier": 2,
                "reference": xref.get("reference"),
                "function": sanitize_enum(
                    xref.get("function"),
                    VALID_CITATION_FUNCTIONS, "citation function", ctx
                ),
                "supports_claim": xref.get("supports_claim"),
            }).execute()

        # --- Insert Tier 3 quotations ---
        for quote in unit.get("quotations", []) or []:
            sb.table("quotations").insert({
                "unit_id": unit_id,
                "text": quote.get("text"),
                "attribution": quote.get("attribution"),
                "source": quote.get("source"),
                "function": sanitize_enum(
                    quote.get("function"),
                    VALID_QUOTATION_FUNCTIONS, "quotation function", ctx
                ),
            }).execute()

        # --- Insert BT moves ---
        for move in unit.get("biblical_theological_moves", []) or []:
            bt_type = sanitize_enum(
                move.get("type"),
                VALID_BT_TYPES, "BT move type", ctx
            )
            if bt_type is None:
                continue  # Skip entirely if type is invalid
            sb.table("bt_moves").insert({
                "unit_id": unit_id,
                "type": bt_type,
                "source_text": move.get("source_text"),
                "target_text": move.get("target_text"),
                "pastor_framing": move.get("pastor_framing"),
            }).execute()

    log.info(
        f"Ingested {len(units)} units with citations, quotations, and BT moves"
    )
    return sermon_id


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------
def process_sermon(
    transcript_path: Path,
    preacher: Optional[str] = None,
    is_canonical: bool = False,
    dry_run: bool = False
) -> Optional[str]:
    """
    Full pipeline: decompose → embed → ingest.
    Accepts .txt or sermonindex .json files.
    """
    si_data = None
    if is_sermonindex_json(transcript_path):
        si_data = read_sermonindex_json(transcript_path)
        transcript = si_data["transcript"]
        preacher = preacher or si_data["preacher"]
        known_title = si_data.get("title")
        known_primary_text = si_data.get("primary_text")
        log.info(f"SermonIndex JSON detected: {si_data['preacher']} — {known_title}")
    else:
        transcript = transcript_path.read_text(encoding="utf-8")
        known_title = None
        known_primary_text = None

    if not preacher:
        log.error("Preacher name required. Use --preacher or provide a sermonindex JSON.")
        sys.exit(1)

    log.info(f"{'='*60}")
    log.info(f"Processing: {transcript_path.name}")
    log.info(f"Preacher: {preacher}")
    log.info(f"{'='*60}")
    log.info(f"Transcript: {len(transcript):,} chars")

    decomposition = decompose_sermon(
        transcript, preacher,
        known_title=known_title,
        known_primary_text=known_primary_text
    )
    units = decomposition.get("units", [])
    log.info(f"Produced {len(units)} units")

    stem = transcript_path.stem
    json_path = OUTPUT_DIR / f"{stem}_decomposed.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(decomposition, f, indent=2, ensure_ascii=False)
    log.info(f"Saved decomposition: {json_path}")

    meta = decomposition.get("_pipeline", {})
    log.info(
        f"Cost: ${meta.get('processing_cost_usd', 0):.4f} "
        f"({meta.get('input_tokens', 0):,} in / "
        f"{meta.get('output_tokens', 0):,} out)"
    )

    if dry_run:
        log.info("DRY RUN — skipping embed and ingest")
        return None

    embeddings = embed_units(units)
    preacher_id = ensure_preacher(preacher, is_canonical=is_canonical)
    sermon_id = ingest_sermon(
        decomposition, preacher_id, embeddings, raw_transcript=transcript
    )

    log.info(f"Complete! Sermon ID: {sermon_id}")
    return sermon_id


def process_batch(
    folder: Path,
    preacher: Optional[str] = None,
    is_canonical: bool = False,
    dry_run: bool = False
):
    """Process all .txt and sermonindex .json files in a folder."""
    txt_files = sorted(folder.glob("*.txt"))
    json_files = [f for f in sorted(folder.glob("*.json"))
                  if f.name != "_index.json" and is_sermonindex_json(f)]
    files = txt_files + json_files

    if not files:
        log.error(f"No .txt or sermonindex .json files found in {folder}")
        return

    log.info(f"Found {len(files)} files ({len(txt_files)} txt, {len(json_files)} json) in {folder}")

    if txt_files and not preacher:
        log.error("--preacher required when batch processing .txt files")
        return

    total_cost = 0.0
    results = []

    for i, filepath in enumerate(files, 1):
        log.info(f"\n[{i}/{len(files)}] {filepath.name}")
        try:
            sermon_id = process_sermon(filepath, preacher, is_canonical, dry_run)
            results.append({"file": filepath.name, "sermon_id": sermon_id, "status": "ok"})

            json_path = OUTPUT_DIR / f"{filepath.stem}_decomposed.json"
            if json_path.exists():
                with open(json_path) as f:
                    data = json.load(f)
                    cost = data.get("_pipeline", {}).get("processing_cost_usd", 0)
                    total_cost += cost

        except Exception as e:
            log.error(f"FAILED: {filepath.name} — {e}")
            results.append({"file": filepath.name, "sermon_id": None, "status": str(e)})

        if i < len(files):
            time.sleep(DECOMPOSE_DELAY_SEC)

    log.info(f"\n{'='*60}")
    log.info(f"BATCH COMPLETE")
    log.info(f"{'='*60}")
    ok = sum(1 for r in results if r["status"] == "ok")
    log.info(f"Processed: {ok}/{len(files)} succeeded")
    log.info(f"Total decomposition cost: ${total_cost:.4f}")

    report_path = OUTPUT_DIR / f"batch_report_{int(time.time())}.json"
    with open(report_path, "w") as f:
        json.dump({
            "preacher": preacher,
            "total_files": len(files),
            "succeeded": ok,
            "total_cost_usd": round(total_cost, 4),
            "results": results
        }, f, indent=2)
    log.info(f"Batch report: {report_path}")


def ingest_existing(
    json_path: Path,
    preacher: Optional[str] = None,
    is_canonical: bool = False
):
    """Embed and ingest a previously decomposed JSON file."""
    log.info(f"Ingesting existing decomposition: {json_path}")

    with open(json_path, "r", encoding="utf-8") as f:
        decomposition = json.load(f)

    if not preacher:
        preacher = decomposition.get("preacher")
    if not preacher:
        log.error("Preacher name required. Use --preacher or ensure it's in the JSON.")
        sys.exit(1)

    units = decomposition.get("units", [])
    log.info(f"Found {len(units)} units")

    embeddings = embed_units(units)
    preacher_id = ensure_preacher(preacher, is_canonical=is_canonical)

    raw_transcript = None
    transcript_path = json_path.with_suffix(".txt")
    if transcript_path.exists():
        raw_transcript = transcript_path.read_text(encoding="utf-8")

    sermon_id = ingest_sermon(
        decomposition, preacher_id, embeddings, raw_transcript=raw_transcript
    )
    log.info(f"Complete! Sermon ID: {sermon_id}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(
        description="Shepherd's Guild — Sermon Decomposition Pipeline v3.1"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    p_decompose = subparsers.add_parser(
        "decompose", help="Decompose a single sermon (.txt or sermonindex .json)"
    )
    p_decompose.add_argument("transcript", type=Path,
                             help="Path to .txt transcript or sermonindex .json")
    p_decompose.add_argument("--preacher", required=False,
                             help="Preacher name (auto-detected from sermonindex JSON)")
    p_decompose.add_argument("--canonical", action="store_true",
                             help="Mark as Guild Hall canonical preacher")
    p_decompose.add_argument("--dry-run", action="store_true",
                             help="Decompose only — skip embed and ingest")

    p_batch = subparsers.add_parser(
        "batch", help="Decompose all .txt and sermonindex .json files in a folder"
    )
    p_batch.add_argument("folder", type=Path,
                         help="Folder containing .txt or sermonindex .json files")
    p_batch.add_argument("--preacher", required=False,
                         help="Preacher name (required for .txt, auto-detected for .json)")
    p_batch.add_argument("--canonical", action="store_true",
                         help="Mark as Guild Hall canonical preacher")
    p_batch.add_argument("--dry-run", action="store_true",
                         help="Decompose only — skip embed and ingest")

    p_ingest = subparsers.add_parser(
        "ingest", help="Embed and ingest a previously decomposed JSON"
    )
    p_ingest.add_argument("json_file", type=Path,
                          help="Path to decomposed .json file")
    p_ingest.add_argument("--preacher", required=False,
                          help="Preacher name (auto-detected from JSON if present)")
    p_ingest.add_argument("--canonical", action="store_true",
                          help="Mark as Guild Hall canonical preacher")

    args = parser.parse_args()

    if args.command == "decompose":
        if not args.transcript.exists():
            log.error(f"File not found: {args.transcript}")
            sys.exit(1)
        if args.transcript.suffix.lower() == ".txt" and not args.preacher:
            log.error("--preacher required for .txt files")
            sys.exit(1)
        process_sermon(args.transcript, args.preacher, args.canonical, args.dry_run)

    elif args.command == "batch":
        if not args.folder.is_dir():
            log.error(f"Not a directory: {args.folder}")
            sys.exit(1)
        process_batch(args.folder, args.preacher, args.canonical, args.dry_run)

    elif args.command == "ingest":
        if not args.json_file.exists():
            log.error(f"File not found: {args.json_file}")
            sys.exit(1)
        ingest_existing(args.json_file, args.preacher, args.canonical)


if __name__ == "__main__":
    main()```

#### Commands for Pipeline v3

**Single sermon from a .txt file:**

```
python3 pipeline.py decompose sermon.txt --preacher "Chris Oswald"
```

**Single sermon from a .txt file (QA review only, no database):**

```
python3 pipeline.py decompose sermon.txt --preacher "Chris Oswald" --dry-run
```

**Single sermon from a sermonindex JSON:**

```
python3 pipeline.py decompose sermon.json
```

**Single sermon from a sermonindex JSON (QA review only):**

```
python3 pipeline.py decompose sermon.json --dry-run
```

**Single sermon from a sermonindex JSON (Guild Hall preacher):**

```
python3 pipeline.py decompose sermon.json --canonical
```

**Batch — folder of .txt files (same preacher):**

```
python3 pipeline.py batch ./transcripts/ --preacher "Chris Oswald"
```

**Batch — folder of .txt files (QA review only):**

```
python3 pipeline.py batch ./transcripts/ --preacher "Chris Oswald" --dry-run
```

**Batch — folder of sermonindex JSONs (preacher auto-detected):**

```
python3 pipeline.py batch ./sermon-transcripts/da-carson/
```

**Batch — folder of sermonindex JSONs (Guild Hall):**

```
python3 pipeline.py batch ./sermon-transcripts/da-carson/ --canonical
```

**Ingest a previously decomposed JSON (skip decomposition, just embed + write to DB):**

```
python3 pipeline.py ingest output/sermon_decomposed.json --preacher "Chris Oswald"
```

**Ingest — preacher auto-detected from the JSON:**

```
python3 pipeline.py ingest output/sermon_decomposed.json
```

**Convert RTF to TXT:**

```
textutil -convert txt filename.rtf
```

**Convert all .docx files in a folder to .txt:**

```
for f in *.docx; do textutil -convert txt "$f"; done
```

---

### pipeline_batch.py — Batch Mode (50% Cost Savings)

Uses Anthropic's Message Batches API for 50% cost reduction. Three-phase workflow: **SUBMIT** (build batch of decomposition requests → submit to API) → **POLL** (check batch status until complete) → **PROCESS** (parse results → sanitize → embed → ingest). This is the preferred pipeline for processing large corpora.

```python
"""
Shepherd's Guild — Sermon Decomposition Pipeline v3.1 (Batch Mode)
===================================================================

Uses Anthropic's Message Batches API for 50% cost reduction on
non-latency-sensitive decomposition work.

Three-phase workflow:
  Phase 1: SUBMIT  — Build batch of decomposition requests → submit to API
  Phase 2: POLL    — Check batch status until complete
  Phase 3: PROCESS — Parse results → sanitize → embed → ingest to Supabase

Usage:
  # Submit a batch from a folder of sermons
  python pipeline_batch.py submit ./transcripts/ --preacher "R.C. Sproul" --canonical

  # Submit sermonindex JSONs (preacher auto-detected per file)
  python pipeline_batch.py submit ./sermon-transcripts/sproul/

  # Check status of a running batch
  python pipeline_batch.py status msgbatch_01HkcTjaV5uDC8jWR4ZsDV8d

  # Process results once batch is complete
  python pipeline_batch.py process msgbatch_01HkcTjaV5uDC8jWR4ZsDV8d --preacher "R.C. Sproul" --canonical

  # Submit only (dry-run: save decomposed JSON, skip embed + ingest)
  python pipeline_batch.py submit ./transcripts/ --preacher "R.C. Sproul" --dry-run

  # List recent batches
  python pipeline_batch.py list

Environment variables (set in .env or export):
  ANTHROPIC_API_KEY   — Your Anthropic API key
  VOYAGE_API_KEY      — Your Voyage AI API key
  SUPABASE_URL        — Your Supabase project URL
  SUPABASE_KEY        — Your Supabase service role key
"""

import os
import sys
import json
import time
import argparse
import logging
from pathlib import Path
from datetime import datetime
from typing import Optional

# ---------------------------------------------------------------------------
# Dependencies — install with:
#   pip install anthropic voyageai supabase python-dotenv
# ---------------------------------------------------------------------------
try:
    import anthropic
    import voyageai
    from supabase import create_client, Client
    from dotenv import load_dotenv
except ImportError as e:
    print(f"Missing dependency: {e}")
    print("Install with: pip install anthropic voyageai supabase python-dotenv")
    sys.exit(1)

load_dotenv()

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
ANTHROPIC_MODEL = "claude-sonnet-4-5-20250929"
VOYAGE_MODEL = "voyage-3.5"
VOYAGE_DIMENSIONS = 1024
SPEC_VERSION = "v3"

# Batch API pricing (50% of standard rates)
BATCH_INPUT_COST_PER_MTOK = 1.5   # Standard is $3.0
BATCH_OUTPUT_COST_PER_MTOK = 7.5  # Standard is $15.0

# Rate limiting for embed stage
EMBED_BATCH_SIZE = 32
EMBED_DELAY_SEC = 0.5

# Paths
SPEC_PATH = Path(__file__).parent / "sermon-decomposition-spec-v3.md"
OUTPUT_DIR = Path(__file__).parent / "output"
BATCH_DIR = Path(__file__).parent / "output" / "batches"
OUTPUT_DIR.mkdir(exist_ok=True)
BATCH_DIR.mkdir(exist_ok=True)

# ---------------------------------------------------------------------------
# Taxonomy Validation Sets (identical to pipeline.py)
# ---------------------------------------------------------------------------
VALID_SERMON_TYPES = {
    "expository", "topical", "textual", "narrative", "polemic"
}

VALID_TONES = {
    "pastoral", "prophetic", "didactic", "celebratory",
    "lament", "polemic", "evangelistic"
}

VALID_HERMENEUTICAL_METHODS = {
    "grammatical_historical", "redemptive_historical",
    "canonical", "applicatory", "polemic"
}

VALID_RHETORICAL_FUNCTIONS = {
    "exposition", "theological_claim", "illustration", "application",
    "introduction", "conclusion", "transition", "pastoral_aside", "prayer"
}

VALID_REGISTERS = {
    "logos", "pathos", "ethos", "narrative", "doxological"
}

VALID_LOCI = {
    "Theology Proper", "Christology", "Pneumatology", "Soteriology",
    "Hamartiology", "Anthropology", "Ecclesiology", "Eschatology",
    "Bibliology", "Sanctification", "Providence / Sovereignty",
    "Covenant Theology", "Ethics / Moral Theology", "Doxology / Worship",
    "Spiritual Warfare", "Pastoral Theology"
}

VALID_ILLUSTRATION_TYPES = {
    "personal_story", "historical_example", "analogy",
    "hypothetical", "cultural_reference"
}

VALID_APPLICATION_SPECIFICITY = {
    "abstract", "concrete", "mixed"
}

VALID_CITATION_MODES = {
    "full_reading", "partial_reading", "reference_in_passing"
}

VALID_CITATION_FUNCTIONS = {
    "authority", "contrast", "echo", "fulfillment", "parallel", "corrective"
}

VALID_QUOTATION_FUNCTIONS = {
    "authority", "illustration", "provocation", "devotional", "opponent"
}

VALID_BT_TYPES = {
    "typology", "fulfillment", "progressive_revelation", "narrative_arc",
    "intertextual_echo", "contrast", "thematic_thread"
}

# Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S"
)
log = logging.getLogger("pipeline_batch")


# ---------------------------------------------------------------------------
# Sanitizer helpers (identical to pipeline.py)
# ---------------------------------------------------------------------------
def sanitize_enum(value, valid_set, field_name, context=""):
    if value is None:
        return None
    if value in valid_set:
        return value
    log.warning(f"{context}invalid {field_name}: '{value}' (removed)")
    return None


def sanitize_enum_array(values, valid_set, field_name, context=""):
    if not values:
        return []
    clean = [v for v in values if v in valid_set]
    bad = set(values) - valid_set
    if bad:
        log.warning(f"{context}invalid {field_name} removed: {bad}")
    return clean


# ---------------------------------------------------------------------------
# Clients (initialized lazily)
# ---------------------------------------------------------------------------
_anthropic_client = None
_voyage_client = None
_supabase_client = None


def get_anthropic() -> anthropic.Anthropic:
    global _anthropic_client
    if _anthropic_client is None:
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            raise EnvironmentError("ANTHROPIC_API_KEY not set")
        _anthropic_client = anthropic.Anthropic(api_key=api_key)
    return _anthropic_client


def get_voyage() -> voyageai.Client:
    global _voyage_client
    if _voyage_client is None:
        api_key = os.getenv("VOYAGE_API_KEY")
        if not api_key:
            raise EnvironmentError("VOYAGE_API_KEY not set")
        _voyage_client = voyageai.Client(api_key=api_key)
    return _voyage_client


def get_supabase() -> Client:
    global _supabase_client
    if _supabase_client is None:
        url = os.getenv("SUPABASE_URL")
        key = os.getenv("SUPABASE_KEY")
        if not url or not key:
            raise EnvironmentError("SUPABASE_URL and SUPABASE_KEY must be set")
        _supabase_client = create_client(url, key)
    return _supabase_client


# ---------------------------------------------------------------------------
# SermonIndex JSON reader (identical to pipeline.py)
# ---------------------------------------------------------------------------
def is_sermonindex_json(filepath: Path) -> bool:
    if filepath.suffix.lower() != ".json":
        return False
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
        return "transcript" in data and "contributor" in data
    except (json.JSONDecodeError, KeyError):
        return False


def read_sermonindex_json(filepath: Path) -> dict:
    with open(filepath, "r", encoding="utf-8") as f:
        data = json.load(f)

    transcript = data.get("transcript")
    if not transcript:
        raise ValueError(f"No transcript in {filepath.name}")

    refs = data.get("bibleReferences") or []
    primary_text = None
    if refs:
        primary_text = refs[0].get("text", None)

    return {
        "transcript": transcript,
        "preacher": data.get("contributor", "Unknown"),
        "title": data.get("title"),
        "primary_text": primary_text,
        "si_metadata": {
            "sermonindex_id": data.get("id"),
            "description": data.get("description"),
            "topics": data.get("topics"),
            "bible_references": refs,
            "duration": data.get("duration"),
            "audio_url": data.get("audioUrl"),
            "views": data.get("views"),
        }
    }


# ---------------------------------------------------------------------------
# Spec loader
# ---------------------------------------------------------------------------
def load_spec() -> str:
    if not SPEC_PATH.exists():
        raise FileNotFoundError(
            f"Spec not found at {SPEC_PATH}. "
            f"Place sermon-decomposition-spec-v3.md next to this script."
        )
    return SPEC_PATH.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Phase 1: SUBMIT — Build and submit batch
# ---------------------------------------------------------------------------
def build_batch_requests(
    folder: Path,
    preacher: Optional[str] = None
) -> tuple[list[dict], dict]:
    """
    Scan a folder for .txt and sermonindex .json files.
    Build a list of Batch API request objects.
    Returns (requests_list, manifest) where manifest maps custom_id → file info.
    """
    spec = load_spec()

    txt_files = sorted(folder.glob("*.txt"))
    json_files = [f for f in sorted(folder.glob("*.json"))
                  if f.name != "_index.json" and is_sermonindex_json(f)]
    files = txt_files + json_files

    if not files:
        log.error(f"No .txt or sermonindex .json files found in {folder}")
        return [], {}

    log.info(f"Found {len(files)} files ({len(txt_files)} txt, {len(json_files)} json)")

    if txt_files and not preacher:
        log.error("--preacher required when batch processing .txt files")
        return [], {}

    requests = []
    manifest = {}
    skipped = 0

    for filepath in files:
        # Read transcript
        try:
            if is_sermonindex_json(filepath):
                si_data = read_sermonindex_json(filepath)
                transcript = si_data["transcript"]
                file_preacher = preacher or si_data["preacher"]
                known_title = si_data.get("title")
                known_primary_text = si_data.get("primary_text")
            else:
                transcript = filepath.read_text(encoding="utf-8")
                file_preacher = preacher
                known_title = None
                known_primary_text = None
        except ValueError as e:
            log.warning(f"Skipping {filepath.name}: {e}")
            skipped += 1
            continue

        if not file_preacher:
            log.warning(f"Skipping {filepath.name}: no preacher name")
            skipped += 1
            continue

        # Build the custom_id from the filename stem
        custom_id = filepath.stem[:64]

        # Build system prompt (identical to pipeline.py)
        metadata_hints = f"The preacher is: {file_preacher}"
        if known_title:
            metadata_hints += f"\nThe sermon title is: {known_title}"
        if known_primary_text:
            metadata_hints += f"\nThe primary text is: {known_primary_text}"

        system_prompt = (
            f"{spec}\n\n"
            f"---\n\n"
            f"You are a sermon decomposition engine. Given a sermon transcript, "
            f"produce a single JSON object conforming exactly to the spec above. "
            f"Output ONLY valid JSON — no markdown fences, no commentary, no preamble.\n\n"
            f"{metadata_hints}"
        )

        user_message = (
            f"Decompose the following sermon transcript:\n\n"
            f"---\n\n"
            f"{transcript}"
        )

        # Build the batch request object
        requests.append({
            "custom_id": custom_id,
            "params": {
                "model": ANTHROPIC_MODEL,
                "max_tokens": 64000,
                "system": system_prompt,
                "messages": [{"role": "user", "content": user_message}]
            }
        })

        manifest[custom_id] = {
            "file": filepath.name,
            "preacher": file_preacher,
            "title": known_title,
            "primary_text": known_primary_text,
            "transcript_chars": len(transcript),
        }

    log.info(f"Built {len(requests)} batch requests ({skipped} skipped)")
    return requests, manifest


def submit_batch(
    folder: Path,
    preacher: Optional[str] = None
) -> Optional[str]:
    """Submit a batch to the Anthropic API. Returns the batch ID."""
    requests, manifest = build_batch_requests(folder, preacher)

    if not requests:
        log.error("No requests to submit")
        return None

    client = get_anthropic()

    log.info(f"Submitting batch of {len(requests)} requests to Anthropic...")
    start = time.time()

    batch = client.messages.batches.create(requests=requests)

    elapsed = time.time() - start
    log.info(f"Batch submitted in {elapsed:.1f}s")
    log.info(f"Batch ID: {batch.id}")
    log.info(f"Status: {batch.processing_status}")
    log.info(f"Expires: {batch.expires_at}")

    # Save manifest so we can map results back to files later
    manifest_path = BATCH_DIR / f"{batch.id}_manifest.json"
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump({
            "batch_id": batch.id,
            "submitted_at": datetime.utcnow().isoformat() + "Z",
            "preacher": preacher,
            "folder": str(folder),
            "request_count": len(requests),
            "manifest": manifest,
        }, f, indent=2)
    log.info(f"Manifest saved: {manifest_path}")

    return batch.id


# ---------------------------------------------------------------------------
# Phase 2: POLL — Check batch status
# ---------------------------------------------------------------------------
def check_status(batch_id: str, wait: bool = False, poll_interval: int = 60):
    """Check (and optionally wait for) batch completion."""
    client = get_anthropic()

    while True:
        batch = client.messages.batches.retrieve(batch_id)

        counts = batch.request_counts
        log.info(
            f"Batch {batch_id}: {batch.processing_status} | "
            f"succeeded={counts.succeeded} errored={counts.errored} "
            f"canceled={counts.canceled} expired={counts.expired} "
            f"processing={counts.processing}"
        )

        if batch.processing_status == "ended":
            log.info(f"Batch complete! Results URL available.")
            return batch

        if not wait:
            return batch

        log.info(f"Waiting {poll_interval}s before next check...")
        time.sleep(poll_interval)


def list_batches(limit: int = 10):
    """List recent batches."""
    client = get_anthropic()
    page = client.messages.batches.list(limit=limit)

    for batch in page.data:
        counts = batch.request_counts
        log.info(
            f"{batch.id} | {batch.processing_status} | "
            f"created={batch.created_at} | "
            f"ok={counts.succeeded} err={counts.errored} "
            f"exp={counts.expired} cancel={counts.canceled}"
        )


# ---------------------------------------------------------------------------
# Phase 3: PROCESS — Retrieve results, parse, embed, ingest
# ---------------------------------------------------------------------------
def process_batch_results(
    batch_id: str,
    preacher: Optional[str] = None,
    is_canonical: bool = False,
    dry_run: bool = False
):
    """
    Download batch results, parse decompositions, embed, and ingest.
    """
    client = get_anthropic()

    # Load manifest if available
    manifest_path = BATCH_DIR / f"{batch_id}_manifest.json"
    manifest = {}
    if manifest_path.exists():
        with open(manifest_path) as f:
            manifest_data = json.load(f)
            manifest = manifest_data.get("manifest", {})
            preacher = preacher or manifest_data.get("preacher")
        log.info(f"Loaded manifest: {len(manifest)} entries")
    else:
        log.warning(f"No manifest found at {manifest_path} — will use --preacher flag")

    # Stream results
    log.info(f"Retrieving results for batch {batch_id}...")
    result_stream = client.messages.batches.results(batch_id)

    total_cost = 0.0
    results = []
    succeeded = 0
    failed = 0

    for entry in result_stream:
        custom_id = entry.custom_id
        file_info = manifest.get(custom_id, {})
        filename = file_info.get("file", f"{custom_id}.json")
        file_preacher = file_info.get("preacher") or preacher

        if entry.result.type == "succeeded":
            message = entry.result.message
            raw_text = message.content[0].text.strip()

            # Strip markdown fences if present
            if raw_text.startswith("```"):
                raw_text = raw_text.split("\n", 1)[1]
            if raw_text.endswith("```"):
                raw_text = raw_text.rsplit("```", 1)[0]
            raw_text = raw_text.strip()

            # Calculate cost at batch rates
            input_tokens = message.usage.input_tokens
            output_tokens = message.usage.output_tokens
            cost = (
                (input_tokens / 1_000_000 * BATCH_INPUT_COST_PER_MTOK) +
                (output_tokens / 1_000_000 * BATCH_OUTPUT_COST_PER_MTOK)
            )
            total_cost += cost

            # Parse JSON
            try:
                decomposition = json.loads(raw_text)
            except json.JSONDecodeError as e:
                log.error(f"JSON parse failed for {filename}: {e}")
                # Save raw output for debugging
                debug_path = OUTPUT_DIR / f"debug_raw_{custom_id}.txt"
                debug_path.write_text(raw_text, encoding="utf-8")
                log.error(f"Raw output saved to {debug_path}")
                results.append({
                    "file": filename, "sermon_id": None,
                    "status": str(e), "cost_usd": round(cost, 4)
                })
                failed += 1
                continue

            # Attach pipeline metadata
            decomposition["_pipeline"] = {
                "spec_version": SPEC_VERSION,
                "model": ANTHROPIC_MODEL,
                "batch_id": batch_id,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "processing_cost_usd": round(cost, 4),
                "batch_mode": True,
                "decomposed_at": datetime.utcnow().isoformat() + "Z"
            }

            # Save decomposed JSON
            json_path = OUTPUT_DIR / f"{custom_id}_decomposed.json"
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(decomposition, f, indent=2, ensure_ascii=False)

            units = decomposition.get("units", [])
            log.info(
                f"OK: {filename} — {len(units)} units, "
                f"${cost:.4f} ({input_tokens:,} in / {output_tokens:,} out)"
            )

            if dry_run:
                results.append({
                    "file": filename, "sermon_id": None,
                    "status": "ok (dry-run)", "cost_usd": round(cost, 4)
                })
                succeeded += 1
                continue

            # Embed and ingest
            try:
                if not file_preacher:
                    log.error(f"No preacher for {filename} — skipping ingest")
                    results.append({
                        "file": filename, "sermon_id": None,
                        "status": "ok (no preacher for ingest)",
                        "cost_usd": round(cost, 4)
                    })
                    succeeded += 1
                    continue

                embeddings = embed_units(units)
                preacher_id = ensure_preacher(file_preacher, is_canonical=is_canonical)

                # Try to recover raw transcript for storage
                raw_transcript = None
                if file_info.get("transcript_chars"):
                    # We don't store the full transcript in manifest (too large)
                    # Try to find the original file
                    folder = manifest_data.get("folder", "") if manifest_path.exists() else ""
                    if folder:
                        orig_path = Path(folder) / filename
                        if orig_path.exists():
                            if is_sermonindex_json(orig_path):
                                si = read_sermonindex_json(orig_path)
                                raw_transcript = si["transcript"]
                            else:
                                raw_transcript = orig_path.read_text(encoding="utf-8")

                sermon_id = ingest_sermon(
                    decomposition, preacher_id, embeddings,
                    raw_transcript=raw_transcript
                )
                log.info(f"Ingested: {filename} → {sermon_id}")
                results.append({
                    "file": filename, "sermon_id": sermon_id,
                    "status": "ok", "cost_usd": round(cost, 4)
                })
                succeeded += 1

            except Exception as e:
                log.error(f"Ingest failed for {filename}: {e}")
                results.append({
                    "file": filename, "sermon_id": None,
                    "status": f"decomp ok, ingest failed: {e}",
                    "cost_usd": round(cost, 4)
                })
                failed += 1

        elif entry.result.type == "errored":
            error = entry.result.error
            log.error(f"API error for {filename}: {error}")
            results.append({
                "file": filename, "sermon_id": None,
                "status": f"api_error: {error}"
            })
            failed += 1

        elif entry.result.type == "canceled":
            log.warning(f"Canceled: {filename}")
            results.append({
                "file": filename, "sermon_id": None,
                "status": "canceled"
            })
            failed += 1

        elif entry.result.type == "expired":
            log.warning(f"Expired: {filename}")
            results.append({
                "file": filename, "sermon_id": None,
                "status": "expired"
            })
            failed += 1

    # Summary
    log.info(f"\n{'='*60}")
    log.info(f"BATCH RESULTS PROCESSED")
    log.info(f"{'='*60}")
    log.info(f"Succeeded: {succeeded}")
    log.info(f"Failed: {failed}")
    log.info(f"Total cost (batch rate): ${total_cost:.4f}")
    log.info(f"Equivalent standard rate: ${total_cost * 2:.4f}")
    log.info(f"Saved: ${total_cost:.4f} (50% batch discount)")

    # Save batch report
    report_path = BATCH_DIR / f"{batch_id}_report.json"
    with open(report_path, "w") as f:
        json.dump({
            "batch_id": batch_id,
            "preacher": preacher,
            "total_results": succeeded + failed,
            "succeeded": succeeded,
            "failed": failed,
            "total_cost_usd": round(total_cost, 4),
            "equivalent_standard_cost_usd": round(total_cost * 2, 4),
            "savings_usd": round(total_cost, 4),
            "results": results
        }, f, indent=2)
    log.info(f"Batch report: {report_path}")


# ---------------------------------------------------------------------------
# Embed (identical to pipeline.py)
# ---------------------------------------------------------------------------
def embed_units(units: list[dict]) -> list[list[float]]:
    client = get_voyage()
    texts = [u["content"] for u in units]

    all_embeddings = []
    total_batches = (len(texts) + EMBED_BATCH_SIZE - 1) // EMBED_BATCH_SIZE

    for i in range(0, len(texts), EMBED_BATCH_SIZE):
        batch = texts[i:i + EMBED_BATCH_SIZE]
        batch_num = (i // EMBED_BATCH_SIZE) + 1
        log.info(f"Embedding batch {batch_num}/{total_batches} ({len(batch)} units)...")

        result = client.embed(
            batch,
            model=VOYAGE_MODEL,
            input_type="document",
            output_dimension=VOYAGE_DIMENSIONS
        )
        all_embeddings.extend(result.embeddings)

        if batch_num < total_batches:
            time.sleep(EMBED_DELAY_SEC)

    log.info(f"Embedded {len(all_embeddings)} units ({VOYAGE_DIMENSIONS} dims each)")
    return all_embeddings


# ---------------------------------------------------------------------------
# Ingest (identical to pipeline.py)
# ---------------------------------------------------------------------------
def ensure_preacher(preacher_name: str, is_canonical: bool = False) -> str:
    sb = get_supabase()

    result = sb.table("preachers").select("id").eq("name", preacher_name).execute()
    if result.data:
        preacher_id = result.data[0]["id"]
        log.info(f"Found existing preacher: {preacher_name} ({preacher_id})")
        return preacher_id

    result = sb.table("preachers").insert({
        "name": preacher_name,
        "is_canonical": is_canonical,
        "is_public": False
    }).execute()

    preacher_id = result.data[0]["id"]
    log.info(f"Created preacher: {preacher_name} ({preacher_id})")
    return preacher_id


def ingest_sermon(
    decomposition: dict,
    preacher_id: str,
    embeddings: list[list[float]],
    raw_transcript: Optional[str] = None
) -> str:
    sb = get_supabase()
    pipeline_meta = decomposition.get("_pipeline", {})
    units = decomposition.get("units", [])

    if len(embeddings) != len(units):
        raise ValueError(
            f"Embedding count ({len(embeddings)}) doesn't match "
            f"unit count ({len(units)})"
        )

    sermon_data = {
        "preacher_id": preacher_id,
        "title": decomposition.get("title"),
        "date": decomposition.get("date"),
        "primary_text": decomposition.get("primary_text"),
        "sermon_type": sanitize_enum(
            decomposition.get("sermon_type"),
            VALID_SERMON_TYPES, "sermon_type", "Sermon: "
        ),
        "series_name": decomposition.get("series_name"),
        "series_position": decomposition.get("series_position"),
        "abstract": decomposition.get("abstract"),
        "main_thesis": decomposition.get("main_thesis"),
        "target_audience_cues": decomposition.get("target_audience_cues"),
        "tone": sanitize_enum_array(
            decomposition.get("tone"),
            VALID_TONES, "tone", "Sermon: "
        ),
        "hermeneutical_method": sanitize_enum_array(
            decomposition.get("hermeneutical_method"),
            VALID_HERMENEUTICAL_METHODS, "hermeneutical_method", "Sermon: "
        ),
        "raw_transcript": raw_transcript,
        "spec_version": pipeline_meta.get("spec_version", SPEC_VERSION),
        "decomposed_at": pipeline_meta.get("decomposed_at"),
        "decomposition_model": pipeline_meta.get("model"),
        "input_tokens": pipeline_meta.get("input_tokens"),
        "output_tokens": pipeline_meta.get("output_tokens"),
        "processing_cost_usd": pipeline_meta.get("processing_cost_usd"),
    }

    result = sb.table("sermons").insert(sermon_data).execute()
    sermon_id = result.data[0]["id"]
    log.info(f"Inserted sermon: {decomposition.get('title')} ({sermon_id})")

    for i, unit in enumerate(units):
        ctx = f"Unit {unit.get('unit_index', i)}: "

        unit_data = {
            "sermon_id": sermon_id,
            "unit_index": unit.get("unit_index", i),
            "rhetorical_function": sanitize_enum(
                unit.get("rhetorical_function"),
                VALID_RHETORICAL_FUNCTIONS, "rhetorical_function", ctx
            ),
            "content": unit.get("content"),
            "summary": unit.get("summary"),
            "key_claim": unit.get("key_claim"),
            "illustration_type": sanitize_enum(
                unit.get("illustration_type"),
                VALID_ILLUSTRATION_TYPES, "illustration_type", ctx
            ),
            "application_specificity": sanitize_enum(
                unit.get("application_specificity"),
                VALID_APPLICATION_SPECIFICITY, "application_specificity", ctx
            ),
            "rhetorical_register": sanitize_enum_array(
                unit.get("rhetorical_register"),
                VALID_REGISTERS, "rhetorical_register", ctx
            ),
            "doctrinal_loci": sanitize_enum_array(
                unit.get("doctrinal_loci"),
                VALID_LOCI, "doctrinal_loci", ctx
            ),
            "people_referenced": unit.get("people_referenced"),
            "sermon_series_context": unit.get("sermon_series_context"),
            "embedding": embeddings[i],
        }

        unit_result = sb.table("units").insert(unit_data).execute()
        unit_id = unit_result.data[0]["id"]

        for citation in unit.get("primary_text_citations", []) or []:
            sb.table("citations").insert({
                "unit_id": unit_id,
                "tier": 1,
                "reference": citation.get("reference"),
                "mode": sanitize_enum(
                    citation.get("mode"),
                    VALID_CITATION_MODES, "citation mode", ctx
                ),
            }).execute()

        for xref in unit.get("cross_references", []) or []:
            sb.table("citations").insert({
                "unit_id": unit_id,
                "tier": 2,
                "reference": xref.get("reference"),
                "function": sanitize_enum(
                    xref.get("function"),
                    VALID_CITATION_FUNCTIONS, "citation function", ctx
                ),
                "supports_claim": xref.get("supports_claim"),
            }).execute()

        for quote in unit.get("quotations", []) or []:
            sb.table("quotations").insert({
                "unit_id": unit_id,
                "text": quote.get("text"),
                "attribution": quote.get("attribution"),
                "source": quote.get("source"),
                "function": sanitize_enum(
                    quote.get("function"),
                    VALID_QUOTATION_FUNCTIONS, "quotation function", ctx
                ),
            }).execute()

        for move in unit.get("biblical_theological_moves", []) or []:
            bt_type = sanitize_enum(
                move.get("type"),
                VALID_BT_TYPES, "BT move type", ctx
            )
            if bt_type is None:
                continue
            sb.table("bt_moves").insert({
                "unit_id": unit_id,
                "type": bt_type,
                "source_text": move.get("source_text"),
                "target_text": move.get("target_text"),
                "pastor_framing": move.get("pastor_framing"),
            }).execute()

    log.info(
        f"Ingested {len(units)} units with citations, quotations, and BT moves"
    )
    return sermon_id


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(
        description="Shepherd's Guild — Sermon Decomposition Pipeline v3.1 (Batch Mode)"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # --- submit ---
    p_submit = subparsers.add_parser(
        "submit", help="Submit a folder of sermons as a batch"
    )
    p_submit.add_argument("folder", type=Path,
                          help="Folder containing .txt or sermonindex .json files")
    p_submit.add_argument("--preacher", required=False,
                          help="Preacher name (required for .txt, auto-detected for .json)")
    p_submit.add_argument("--canonical", action="store_true",
                          help="Mark as Guild Hall canonical preacher")
    p_submit.add_argument("--dry-run", action="store_true",
                          help="When processing results, skip embed and ingest")

    # --- status ---
    p_status = subparsers.add_parser(
        "status", help="Check status of a batch"
    )
    p_status.add_argument("batch_id", type=str, help="Batch ID")
    p_status.add_argument("--wait", action="store_true",
                          help="Poll until batch completes")
    p_status.add_argument("--interval", type=int, default=60,
                          help="Polling interval in seconds (default: 60)")

    # --- process ---
    p_process = subparsers.add_parser(
        "process", help="Process completed batch results"
    )
    p_process.add_argument("batch_id", type=str, help="Batch ID")
    p_process.add_argument("--preacher", required=False,
                           help="Preacher name (override manifest)")
    p_process.add_argument("--canonical", action="store_true",
                           help="Mark as Guild Hall canonical preacher")
    p_process.add_argument("--dry-run", action="store_true",
                           help="Save decomposed JSON only — skip embed and ingest")

    # --- list ---
    p_list = subparsers.add_parser(
        "list", help="List recent batches"
    )
    p_list.add_argument("--limit", type=int, default=10,
                        help="Number of batches to list (default: 10)")

    args = parser.parse_args()

    if args.command == "submit":
        if not args.folder.is_dir():
            log.error(f"Not a directory: {args.folder}")
            sys.exit(1)
        batch_id = submit_batch(args.folder, args.preacher)
        if batch_id:
            log.info(f"\nNext steps:")
            log.info(f"  Check status:    python pipeline_batch.py status {batch_id}")
            log.info(f"  Wait + process:  python pipeline_batch.py status {batch_id} --wait")
            log.info(f"  Process results: python pipeline_batch.py process {batch_id}"
                     f"{' --canonical' if args.canonical else ''}"
                     f"{' --dry-run' if args.dry_run else ''}")

    elif args.command == "status":
        check_status(args.batch_id, wait=args.wait, poll_interval=args.interval)

    elif args.command == "process":
        # First verify the batch is complete
        batch = check_status(args.batch_id)
        if batch.processing_status != "ended":
            log.error(
                f"Batch is still {batch.processing_status}. "
                f"Use 'status --wait' to wait for completion first."
            )
            sys.exit(1)
        process_batch_results(
            args.batch_id, args.preacher,
            is_canonical=args.canonical, dry_run=args.dry_run
        )

    elif args.command == "list":
        list_batches(args.limit)


if __name__ == "__main__":
    main()
```

#### Commands for Batch Pipeline

Here's how it works — three separate commands instead of one long-running process:

**Step 1: Submit.** `python pipeline_batch.py submit ./sproul-sermons/ --preacher "R.C. Sproul" --canonical` — scans the folder, skips files with no transcript (so you won't get those 28 phantom failures), builds all the API requests, and submits them as a single batch. Saves a manifest file that maps each `custom_id` back to its source file and preacher metadata.

**Step 2: Check.** `python pipeline_batch.py status msgbatch_XXXXX` — polls once and shows you the count of succeeded/errored/processing. Add `--wait` and it'll poll every 60 seconds until the batch finishes.

**Step 3: Process.** `python pipeline_batch.py process msgbatch_XXXXX --canonical` — streams the results, parses the JSON, runs embeddings, and ingests to Supabase. Same sanitization, same taxonomy validation, same Supabase insert logic as your original pipeline. Supports `--dry-run` to just save the decomposed JSONs without ingesting.

Key differences from the original:

The cost calculation uses batch rates ($1.50/$7.50 per MTok instead of $3.00/$15.00). The report at the end shows you what you paid, what it would have cost at standard rates, and the savings. The response comes back as a complete JSON blob — no streaming assembly, which eliminates the `json.loads()` failures from incomplete streamed responses. That alone should kill a big chunk of your 20 parse errors from the Sproul run.

The `list` command (`python pipeline_batch.py list`) shows your recent batches if you need to find an old batch ID.

---

### repair_batch_failures.py — JSON Repair Tool

Repairs malformed JSON from failed batch decompositions. Handles three failure modes: unescaped quotes inside string values, markdown wrapper instead of raw JSON, and bare unquoted values in arrays.

```python
"""
Shepherd's Guild — Batch Failure Repair Script
================================================

Repairs malformed JSON from failed batch decompositions.

Handles three failure modes:
  1. Unescaped quotes inside string values (most common)
  2. Markdown wrapper instead of raw JSON
  3. Bare unquoted values in arrays

Usage:
  # Dry run — show what would be repaired, don't write files
  python3 repair_batch_failures.py --output-dir ./output

  # Repair and write fixed JSON files
  python3 repair_batch_failures.py --output-dir ./output --write

  # Then re-run the process step (dry-run first to verify)
  python3 pipeline_batch.py process <batch_id> --canonical --dry-run

Requirements:
  pip install json-repair
"""

import os
import sys
import json
import argparse
import logging
from pathlib import Path

try:
    from json_repair import repair_json
except ImportError:
    print("Missing dependency: json-repair")
    print("Install with: pip install json-repair")
    sys.exit(1)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S"
)
log = logging.getLogger("repair")


def strip_markdown_wrapper(text: str) -> str:
    """Strip markdown headers and code fences to extract raw JSON."""
    stripped = text.strip()

    # If it already starts with {, no wrapping to remove
    if stripped.startswith("{"):
        return stripped

    # Find the first { — everything before it is markdown preamble
    first_brace = stripped.find("{")
    if first_brace < 0:
        return stripped  # No JSON object found at all

    stripped = stripped[first_brace:]

    # Find the last } — everything after it is trailing markdown
    last_brace = stripped.rfind("}")
    if last_brace < 0:
        return stripped

    stripped = stripped[:last_brace + 1]
    return stripped


def validate_decomposition(data: dict) -> list[str]:
    """Basic structural validation of a repaired decomposition."""
    warnings = []

    if not isinstance(data, dict):
        warnings.append("Root is not a dict")
        return warnings

    # Check required top-level fields
    for field in ["title", "primary_text", "units"]:
        if field not in data:
            warnings.append(f"Missing top-level field: {field}")

    units = data.get("units", [])
    if not isinstance(units, list):
        warnings.append("'units' is not a list")
    elif len(units) == 0:
        warnings.append("'units' is empty")
    else:
        for i, unit in enumerate(units):
            if not isinstance(unit, dict):
                warnings.append(f"Unit {i} is not a dict")
                continue
            if "content" not in unit:
                warnings.append(f"Unit {i} missing 'content'")
            if "rhetorical_function" not in unit:
                warnings.append(f"Unit {i} missing 'rhetorical_function'")

    return warnings


def repair_file(filepath: Path, write: bool = False) -> dict:
    """
    Attempt to repair a single debug_raw file.
    Returns a status dict.
    """
    raw = filepath.read_text(encoding="utf-8")

    # Phase 1: Strip markdown wrapper if present
    cleaned = strip_markdown_wrapper(raw)

    # Phase 2: Attempt standard JSON parse first
    try:
        data = json.loads(cleaned)
        return {
            "file": filepath.name,
            "status": "already_valid",
            "units": len(data.get("units", [])),
            "warnings": validate_decomposition(data),
        }
    except json.JSONDecodeError:
        pass

    # Phase 3: Use json_repair
    try:
        data = repair_json(cleaned, return_objects=True)
    except Exception as e:
        return {
            "file": filepath.name,
            "status": f"repair_failed: {e}",
            "units": 0,
            "warnings": [],
        }

    if not isinstance(data, dict):
        return {
            "file": filepath.name,
            "status": f"repair_produced_{type(data).__name__}_not_dict",
            "units": 0,
            "warnings": [],
        }

    # Phase 4: Validate the repaired output
    warnings = validate_decomposition(data)

    # Phase 5: Verify the repaired JSON round-trips cleanly
    try:
        roundtrip = json.dumps(data, ensure_ascii=False, indent=2)
        json.loads(roundtrip)  # Confirm it parses back
    except (json.JSONDecodeError, TypeError) as e:
        return {
            "file": filepath.name,
            "status": f"roundtrip_failed: {e}",
            "units": len(data.get("units", [])),
            "warnings": warnings,
        }

    units = data.get("units", [])
    status = "repaired"

    # Phase 6: Write the repaired file if requested
    if write:
        # Write as _decomposed.json matching the pipeline's naming convention
        # debug_raw_<custom_id>.txt → <custom_id>_decomposed.json
        stem = filepath.stem  # debug_raw_<custom_id>
        custom_id = stem.replace("debug_raw_", "", 1)
        output_path = filepath.parent / f"{custom_id}_decomposed.json"

        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

        log.info(f"Wrote: {output_path.name}")
        status = f"repaired_and_written → {output_path.name}"

    return {
        "file": filepath.name,
        "status": status,
        "units": len(units),
        "title": data.get("title", "(no title)"),
        "warnings": warnings,
    }


def main():
    parser = argparse.ArgumentParser(
        description="Repair failed batch decomposition JSON files"
    )
    parser.add_argument(
        "--output-dir", type=Path, required=True,
        help="Path to the pipeline output directory containing debug_raw_*.txt files"
    )
    parser.add_argument(
        "--write", action="store_true",
        help="Write repaired JSON files (without this flag, dry-run only)"
    )
    args = parser.parse_args()

    output_dir = args.output_dir
    if not output_dir.is_dir():
        log.error(f"Not a directory: {output_dir}")
        sys.exit(1)

    debug_files = sorted(output_dir.glob("debug_raw_*.txt"))
    if not debug_files:
        log.info(f"No debug_raw_*.txt files found in {output_dir}")
        sys.exit(0)

    log.info(f"Found {len(debug_files)} failed decomposition files to repair")
    if not args.write:
        log.info("DRY RUN — use --write to save repaired files\n")

    repaired = 0
    failed = 0
    already_valid = 0

    for filepath in debug_files:
        result = repair_file(filepath, write=args.write)

        if result["status"] == "already_valid":
            log.info(f"  OK (already valid): {result['file']} — {result['units']} units")
            already_valid += 1
        elif result["status"].startswith("repaired"):
            icon = "✓" if args.write else "→"
            log.info(
                f"  {icon} {result['file']} — {result['units']} units — "
                f"\"{result.get('title', '?')}\""
            )
            if result["warnings"]:
                for w in result["warnings"]:
                    log.warning(f"      ⚠ {w}")
            repaired += 1
        else:
            log.error(f"  ✗ {result['file']}: {result['status']}")
            failed += 1

    log.info(f"\n{'='*60}")
    log.info(f"REPAIR SUMMARY")
    log.info(f"{'='*60}")
    log.info(f"Already valid:  {already_valid}")
    log.info(f"Repaired:       {repaired}")
    log.info(f"Failed:         {failed}")
    log.info(f"Total:          {len(debug_files)}")

    if repaired > 0 and not args.write:
        log.info(f"\nRe-run with --write to save repaired files.")


if __name__ == "__main__":
    main()
```

---

### Pipeline README

```markdown
# Shepherd's Guild — Sermon Decomposition Pipeline v3

## Setup

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Configure environment
cp env.template .env
# Edit .env with your API keys and Supabase credentials

# 3. Place the spec file next to pipeline.py
# sermon-decomposition-spec-v3.md should be in the same directory

# 4. Create the Supabase schema
# Run supabase-schema-v3.sql in your Supabase SQL editor
```

## Usage

### Single sermon (full pipeline: decompose → embed → ingest)
```bash
python pipeline.py decompose sermon.txt --preacher "John MacArthur"
```

### Single sermon (decompose only — for QA review before ingesting)
```bash
python pipeline.py decompose sermon.txt --preacher "John MacArthur" --dry-run
```

### Batch processing (all .txt files in a folder)
```bash
python pipeline.py batch ./transcripts/macarthur/ --preacher "John MacArthur"
```

### Guild Hall canonical preachers
```bash
python pipeline.py batch ./transcripts/spurgeon/ --preacher "Charles Spurgeon" --canonical
```

### Ingest a previously decomposed JSON (skip decomposition, just embed + write to DB)
```bash
python pipeline.py ingest output/sermon_decomposed.json --preacher "John MacArthur"
```

## File Structure

```
pipeline/
├── pipeline.py                         # Main pipeline script
├── sermon-decomposition-spec-v3.md     # The v3 decomposition spec (system prompt)
├── supabase-schema-v3.sql              # Database schema
├── requirements.txt                    # Python dependencies
├── env.template                        # Environment variable template
├── .env                                # Your actual keys (git-ignored)
└── output/                             # Auto-created
    ├── sermon_decomposed.json          # Decomposition output (one per sermon)
    └── batch_report_*.json             # Batch processing reports
```

## Pipeline Stages

### Stage 1: Decompose
- Sends transcript to Claude Sonnet 4.5 with the v3 spec as system prompt
- Receives structured JSON conforming to the decomposition spec
- Saves JSON to `output/` directory (always, for audit trail and QA)
- Attaches pipeline metadata: model, token counts, cost, timestamp

### Stage 2: Embed
- Sends each unit's `content` field to Voyage 3.5
- Generates 1024-dimensional embeddings for semantic search
- Uses `input_type="document"` for optimal retrieval performance
- Batches units (32 per API call) with rate limiting

### Stage 3: Ingest
- Creates preacher record if not exists
- Inserts sermon with all sermon-level metadata
- Inserts units with embeddings and structured metadata
- Inserts citations (Tier 1 + Tier 2), quotations (Tier 3), and BT moves
- All foreign keys properly linked

## Cost Estimates (March 2026 pricing)

| Component | Cost per sermon |
|-----------|----------------|
| Decomposition (Sonnet 4.5) | ~$0.30-0.40 |
| Embeddings (Voyage 3.5) | ~$0.01 |
| Supabase | Free tier / negligible |
| **Total** | **~$0.31-0.41** |

For a 30-sermon corpus: ~$10-12
For the full Guild Hall (330 sermons): ~$100-135

## QA Workflow

1. Run with `--dry-run` first to get decomposition JSON without database writes
2. Review the JSON — check rhetorical function assignments, citation tier accuracy, BT moves
3. If quality is good, run `ingest` command to embed and write to database
4. If quality needs work, adjust the spec or transcript and re-decompose
```

---

## 3. Infrastructure: Database

All decomposed sermon data is stored in Supabase (PostgreSQL with pgvector). The schema supports the full product suite: PASTORALRAG, MIRRORVOX/Forge, Guild Hall, TRAININGDATA, and BookGuide.

Supabase project URL: `https://twbunmbzyqcqzgffdrib.supabase.co`

### supabase-schema-v3.sql

```sql
-- ============================================================================
-- Shepherd's Guild — Supabase Schema v3
-- Sermon Decomposition Pipeline + RAG Infrastructure
-- March 2026
-- ============================================================================
-- 
-- Designed to serve:
--   • PASTORALRAG — structured retrieval + semantic search
--   • Forge / MIRRORVOX — homiletical benchmarking + archetype analysis
--   • Guild Hall — canonical preacher reference library
--   • TRAININGDATA — labeled sermon corpora (future)
--   • BookGuide — illustration/quote extraction for publishing
--
-- Key design decisions:
--   • Fully normalized: sermons → units → citations/quotations/bt_moves
--   • pgvector embeddings on units for semantic search
--   • Multi-tenant via preacher → church scoping
--   • Canonical (Guild Hall) and customer preachers in same tables
--   • Row Level Security ready (not enabled here — add per deployment)
-- ============================================================================

-- Enable required extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "vector";

-- ============================================================================
-- CHURCHES
-- Multi-tenant root. Every customer pastor belongs to a church.
-- Canonical/Guild Hall preachers have church_id = NULL.
-- ============================================================================
CREATE TABLE churches (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name            TEXT NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ============================================================================
-- PREACHERS
-- Both customer pastors and canonical Guild Hall preachers.
-- is_canonical = true for reference library preachers.
-- is_public controls whether their corpus is queryable by other pastors
-- (the "dark until licensed" flag).
-- ============================================================================
CREATE TABLE preachers (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    church_id       UUID REFERENCES churches(id) ON DELETE SET NULL,
    name            TEXT NOT NULL,
    is_canonical    BOOLEAN NOT NULL DEFAULT false,
    is_public       BOOLEAN NOT NULL DEFAULT false,
    bio             TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_preachers_church ON preachers(church_id);
CREATE INDEX idx_preachers_canonical ON preachers(is_canonical) WHERE is_canonical = true;

-- ============================================================================
-- SERMONS
-- One row per sermon. All sermon-level fields from Decomposition Spec v3.
-- Arrays stored as native Postgres arrays or JSONB where appropriate.
-- ============================================================================
CREATE TABLE sermons (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    preacher_id         UUID NOT NULL REFERENCES preachers(id) ON DELETE CASCADE,
    
    -- Core metadata
    title               TEXT NOT NULL,
    date                DATE,
    primary_text        TEXT,
    sermon_type         TEXT CHECK (sermon_type IN (
                            'expository', 'topical', 'textual', 'narrative', 'polemic'
                        )),
    series_name         TEXT,
    series_position     TEXT,
    
    -- Analytical fields
    abstract            TEXT,
    main_thesis         TEXT,
    target_audience_cues TEXT,
    tone                TEXT[] CHECK (tone <@ ARRAY[
                            'pastoral', 'prophetic', 'didactic', 'celebratory',
                            'lament', 'polemic', 'evangelistic'
                        ]::TEXT[]),
    hermeneutical_method TEXT[] CHECK (hermeneutical_method <@ ARRAY[
                            'grammatical_historical', 'redemptive_historical',
                            'canonical', 'applicatory', 'polemic'
                        ]::TEXT[]),
    
    -- Raw source
    raw_transcript      TEXT,
    
    -- Pipeline metadata
    spec_version        TEXT NOT NULL DEFAULT 'v3',
    decomposed_at       TIMESTAMPTZ,
    decomposition_model TEXT,
    input_tokens        INTEGER,
    output_tokens       INTEGER,
    processing_cost_usd NUMERIC(8, 4),
    
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_sermons_preacher ON sermons(preacher_id);
CREATE INDEX idx_sermons_primary_text ON sermons(primary_text);
CREATE INDEX idx_sermons_sermon_type ON sermons(sermon_type);
CREATE INDEX idx_sermons_date ON sermons(date);
CREATE INDEX idx_sermons_series ON sermons(series_name);

-- ============================================================================
-- UNITS
-- One row per functional unit. The core analytical atom.
-- This is where most queries land — both structured and semantic.
-- ============================================================================
CREATE TABLE units (
    id                      UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    sermon_id               UUID NOT NULL REFERENCES sermons(id) ON DELETE CASCADE,
    unit_index              INTEGER NOT NULL,
    
    -- Core fields
    rhetorical_function     TEXT NOT NULL CHECK (rhetorical_function IN (
                                'exposition', 'theological_claim', 'illustration',
                                'application', 'introduction', 'conclusion',
                                'transition', 'pastoral_aside', 'prayer'
                            )),
    content                 TEXT NOT NULL,
    summary                 TEXT,
    key_claim               TEXT,
    
    -- v3 additions
    illustration_type       TEXT CHECK (illustration_type IN (
                                'personal_story', 'historical_example', 'analogy',
                                'hypothetical', 'cultural_reference'
                            )),
    application_specificity TEXT CHECK (application_specificity IN (
                                'abstract', 'concrete', 'mixed'
                            )),
    rhetorical_register     TEXT[] CHECK (rhetorical_register <@ ARRAY[
                                'logos', 'pathos', 'ethos', 'narrative', 'doxological'
                            ]::TEXT[]),
    
    -- Theological metadata
    doctrinal_loci          TEXT[] CHECK (doctrinal_loci <@ ARRAY[
                                'Theology Proper', 'Christology', 'Pneumatology',
                                'Soteriology', 'Hamartiology', 'Anthropology',
                                'Ecclesiology', 'Eschatology', 'Bibliology',
                                'Sanctification', 'Providence / Sovereignty',
                                'Covenant Theology', 'Ethics / Moral Theology',
                                'Doxology / Worship', 'Spiritual Warfare',
                                'Pastoral Theology'
                            ]::TEXT[]),
    people_referenced       TEXT[],
    sermon_series_context   TEXT,
    
    -- Semantic search (Voyage 3.5, 1024 dimensions default)
    embedding               vector(1024),
    
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Ensure unit ordering within a sermon
ALTER TABLE units ADD CONSTRAINT unique_sermon_unit_index UNIQUE (sermon_id, unit_index);

-- Structured query indexes
CREATE INDEX idx_units_sermon ON units(sermon_id);
CREATE INDEX idx_units_rhetorical_function ON units(rhetorical_function);
CREATE INDEX idx_units_illustration_type ON units(illustration_type) WHERE illustration_type IS NOT NULL;
CREATE INDEX idx_units_application_specificity ON units(application_specificity) WHERE application_specificity IS NOT NULL;
CREATE INDEX idx_units_doctrinal_loci ON units USING GIN(doctrinal_loci);
CREATE INDEX idx_units_rhetorical_register ON units USING GIN(rhetorical_register);
CREATE INDEX idx_units_people ON units USING GIN(people_referenced);

-- Semantic search index (IVFFlat — rebuild after loading data)
-- For < 10,000 rows, use exact search (no index needed).
-- When units exceed ~10k rows, create with:
-- CREATE INDEX idx_units_embedding ON units USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);

-- ============================================================================
-- CITATIONS
-- All three tiers of scripture citations in one table.
-- tier = 1 (primary text), 2 (cross-reference)
-- ============================================================================
CREATE TABLE citations (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    unit_id         UUID NOT NULL REFERENCES units(id) ON DELETE CASCADE,
    tier            SMALLINT NOT NULL CHECK (tier IN (1, 2)),
    
    reference       TEXT NOT NULL,
    
    -- Tier 1 fields
    mode            TEXT CHECK (mode IN (
                        'full_reading', 'partial_reading', 'reference_in_passing'
                    )),
    
    -- Tier 2 fields
    function        TEXT CHECK (function IN (
                        'authority', 'contrast', 'echo', 'fulfillment',
                        'parallel', 'corrective'
                    )),
    supports_claim  TEXT,
    
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_citations_unit ON citations(unit_id);
CREATE INDEX idx_citations_reference ON citations(reference);
CREATE INDEX idx_citations_tier ON citations(tier);
CREATE INDEX idx_citations_function ON citations(function) WHERE function IS NOT NULL;

-- ============================================================================
-- QUOTATIONS
-- Human-author quotations (Tier 3 in the spec).
-- Separate table because the fields are entirely different from citations.
-- ============================================================================
CREATE TABLE quotations (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    unit_id         UUID NOT NULL REFERENCES units(id) ON DELETE CASCADE,
    
    text            TEXT NOT NULL,
    attribution     TEXT NOT NULL,
    source          TEXT,
    function        TEXT CHECK (function IN (
                        'authority', 'illustration', 'provocation',
                        'devotional', 'opponent'
                    )),
    
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_quotations_unit ON quotations(unit_id);
CREATE INDEX idx_quotations_attribution ON quotations(attribution);
CREATE INDEX idx_quotations_function ON quotations(function);

-- ============================================================================
-- BIBLICAL-THEOLOGICAL MOVES
-- ============================================================================
CREATE TABLE bt_moves (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    unit_id         UUID NOT NULL REFERENCES units(id) ON DELETE CASCADE,
    
    type            TEXT NOT NULL CHECK (type IN (
                        'typology', 'fulfillment', 'progressive_revelation',
                        'narrative_arc', 'intertextual_echo', 'contrast',
                        'thematic_thread'
                    )),
    source_text     TEXT,
    target_text     TEXT,
    pastor_framing  TEXT,
    
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_bt_moves_unit ON bt_moves(unit_id);
CREATE INDEX idx_bt_moves_type ON bt_moves(type);

-- ============================================================================
-- SERMON-LEVEL ROLLED-UP ARRAYS
-- The spec includes all_quotations and all_cross_references at the sermon
-- level with unit_index references. These are derivable from the normalized
-- tables via JOINs, so we do NOT store them redundantly. Instead, we provide
-- views for convenience.
-- ============================================================================

CREATE VIEW sermon_quotations AS
SELECT
    s.id AS sermon_id,
    s.title AS sermon_title,
    u.unit_index,
    q.text,
    q.attribution,
    q.source,
    q.function
FROM sermons s
JOIN units u ON u.sermon_id = s.id
JOIN quotations q ON q.unit_id = u.id
ORDER BY s.id, u.unit_index;

CREATE VIEW sermon_cross_references AS
SELECT
    s.id AS sermon_id,
    s.title AS sermon_title,
    u.unit_index,
    c.reference,
    c.function,
    c.supports_claim
FROM sermons s
JOIN units u ON u.sermon_id = s.id
JOIN citations c ON c.unit_id = u.id
WHERE c.tier = 2
ORDER BY s.id, u.unit_index;

-- ============================================================================
-- HELPER VIEWS FOR COMMON QUERIES
-- ============================================================================

-- All illustrations with their sermon context
CREATE VIEW illustrations AS
SELECT
    u.id AS unit_id,
    u.sermon_id,
    s.preacher_id,
    p.name AS preacher_name,
    s.title AS sermon_title,
    s.date AS sermon_date,
    u.unit_index,
    u.content,
    u.summary,
    u.illustration_type,
    u.doctrinal_loci,
    u.people_referenced
FROM units u
JOIN sermons s ON s.id = u.sermon_id
JOIN preachers p ON p.id = s.preacher_id
WHERE u.rhetorical_function = 'illustration';

-- All application units with specificity
CREATE VIEW applications AS
SELECT
    u.id AS unit_id,
    u.sermon_id,
    s.preacher_id,
    p.name AS preacher_name,
    s.title AS sermon_title,
    s.date AS sermon_date,
    u.unit_index,
    u.content,
    u.summary,
    u.key_claim,
    u.application_specificity,
    u.doctrinal_loci
FROM units u
JOIN sermons s ON s.id = u.sermon_id
JOIN preachers p ON p.id = s.preacher_id
WHERE u.rhetorical_function = 'application';

-- Preacher profile stats (for Forge / archetype analysis)
CREATE VIEW preacher_profile_stats AS
SELECT
    p.id AS preacher_id,
    p.name AS preacher_name,
    p.is_canonical,
    COUNT(DISTINCT s.id) AS sermon_count,
    COUNT(u.id) AS total_units,
    ROUND(COUNT(u.id)::NUMERIC / NULLIF(COUNT(DISTINCT s.id), 0), 1) AS avg_units_per_sermon,
    
    -- Rhetorical function distribution
    ROUND(100.0 * COUNT(*) FILTER (WHERE u.rhetorical_function = 'exposition') / NULLIF(COUNT(*), 0), 1) AS pct_exposition,
    ROUND(100.0 * COUNT(*) FILTER (WHERE u.rhetorical_function = 'theological_claim') / NULLIF(COUNT(*), 0), 1) AS pct_theological_claim,
    ROUND(100.0 * COUNT(*) FILTER (WHERE u.rhetorical_function = 'illustration') / NULLIF(COUNT(*), 0), 1) AS pct_illustration,
    ROUND(100.0 * COUNT(*) FILTER (WHERE u.rhetorical_function = 'application') / NULLIF(COUNT(*), 0), 1) AS pct_application,
    ROUND(100.0 * COUNT(*) FILTER (WHERE u.rhetorical_function = 'pastoral_aside') / NULLIF(COUNT(*), 0), 1) AS pct_pastoral_aside,
    
    -- Illustration type distribution (of illustration units only)
    COUNT(*) FILTER (WHERE u.illustration_type = 'personal_story') AS illustration_personal_story,
    COUNT(*) FILTER (WHERE u.illustration_type = 'historical_example') AS illustration_historical_example,
    COUNT(*) FILTER (WHERE u.illustration_type = 'analogy') AS illustration_analogy,
    COUNT(*) FILTER (WHERE u.illustration_type = 'hypothetical') AS illustration_hypothetical,
    COUNT(*) FILTER (WHERE u.illustration_type = 'cultural_reference') AS illustration_cultural_reference,
    
    -- Application specificity distribution
    COUNT(*) FILTER (WHERE u.application_specificity = 'abstract') AS application_abstract,
    COUNT(*) FILTER (WHERE u.application_specificity = 'concrete') AS application_concrete,
    COUNT(*) FILTER (WHERE u.application_specificity = 'mixed') AS application_mixed,
    
    -- Cross-reference density
    ROUND(
        (SELECT COUNT(*)::NUMERIC FROM citations c2 
         JOIN units u2 ON u2.id = c2.unit_id 
         JOIN sermons s2 ON s2.id = u2.sermon_id 
         WHERE s2.preacher_id = p.id AND c2.tier = 2)
        / NULLIF(COUNT(DISTINCT s.id), 0), 1
    ) AS avg_cross_refs_per_sermon,
    
    -- BT move density
    ROUND(
        (SELECT COUNT(*)::NUMERIC FROM bt_moves bm 
         JOIN units u3 ON u3.id = bm.unit_id 
         JOIN sermons s3 ON s3.id = u3.sermon_id 
         WHERE s3.preacher_id = p.id)
        / NULLIF(COUNT(DISTINCT s.id), 0), 1
    ) AS avg_bt_moves_per_sermon,
    
    -- Quotation density
    ROUND(
        (SELECT COUNT(*)::NUMERIC FROM quotations q2 
         JOIN units u4 ON u4.id = q2.unit_id 
         JOIN sermons s4 ON s4.id = u4.sermon_id 
         WHERE s4.preacher_id = p.id)
        / NULLIF(COUNT(DISTINCT s.id), 0), 1
    ) AS avg_quotations_per_sermon

FROM preachers p
LEFT JOIN sermons s ON s.id IS NOT NULL AND s.preacher_id = p.id
LEFT JOIN units u ON u.sermon_id = s.id
GROUP BY p.id, p.name, p.is_canonical;

-- ============================================================================
-- EXAMPLE QUERIES (for reference — not executed)
-- ============================================================================

-- PASTORALRAG: "Find my illustrations about fatherhood"
-- SELECT u.content, u.summary, u.illustration_type, s.title, s.date
-- FROM units u
-- JOIN sermons s ON s.id = u.sermon_id
-- WHERE s.preacher_id = :pastor_id
--   AND u.rhetorical_function = 'illustration'
-- ORDER BY u.embedding <=> :query_embedding
-- LIMIT 10;

-- PASTORALRAG: "Any Spurgeon quotes in my sermons?"
-- SELECT q.text, q.source, q.function, s.title, s.date, u.unit_index
-- FROM quotations q
-- JOIN units u ON u.id = q.unit_id
-- JOIN sermons s ON s.id = u.sermon_id
-- WHERE s.preacher_id = :pastor_id
--   AND q.attribution ILIKE '%spurgeon%';

-- PASTORALRAG: "Everything I've preached on Romans 8"
-- SELECT DISTINCT s.id, s.title, s.date, s.abstract
-- FROM sermons s
-- LEFT JOIN units u ON u.sermon_id = s.id
-- LEFT JOIN citations c ON c.unit_id = u.id
-- WHERE s.preacher_id = :pastor_id
--   AND (s.primary_text ILIKE '%Romans 8%' OR c.reference ILIKE '%Romans 8%');

-- GUILD HALL RAG: "What would Spurgeon say about suffering?"
-- SELECT u.content, u.summary, u.key_claim, s.title
-- FROM units u
-- JOIN sermons s ON s.id = u.sermon_id
-- JOIN preachers p ON p.id = s.preacher_id
-- WHERE p.name = 'Charles Spurgeon'
--   AND p.is_public = true
--   AND 'Soteriology' = ANY(u.doctrinal_loci)
-- ORDER BY u.embedding <=> :query_embedding
-- LIMIT 10;

-- FORGE: Compare two preachers' profiles
-- SELECT * FROM preacher_profile_stats
-- WHERE preacher_id IN (:pastor_id, :exemplar_id);
```

---

## 4. Products

From the decomposed sermon corpus, the products begin to emerge.

### Guild Hall

The simplest product is the Guild Hall — which offers V3-level analysis of famously good preachers. Current members of "The Hall" include: Charles Spurgeon, Martyn Lloyd-Jones, John Stott, John Piper, CJ Mahaney, John MacArthur, RC Sproul, Tim Keller, Mark Dever, D.A. Carson, Tony Evans, and David Jeremiah.

**Sales Funnel:** There is potentially some virality via X and Facebook for the Hall. People (especially preachers) will be interested in seeing analytical metrics for some of their favorite preachers. The big idea is that the Guild Hall helps the prospective client (a local preacher) understand the unique value of the V3 decomp model, the general ethos of Shepherd's Guild, and spark a sense of curiosity about how his sermons "stack up." During his time on the SG website, a popup (or some other timeout function) will trigger an invitation: **"We have a vision for your sermon archive"** — in which the offer will be made to "join the Hall."

#### Guild Hall Roster (from guild-hall-index.html)

The Guild Hall index page presents 17 preachers spanning ~400 years of preaching history. The roster (as rendered on the public-facing site) is:

| # | Preacher | Dates | Status |
|---|---|---|---|
| 01 | Charles Spurgeon | 1834–1892 | Profile Available |
| 02 | Thomas Watson | 1620–1686 | Coming Soon |
| 03 | J.C. Ryle | 1816–1900 | Coming Soon |
| 04 | G. Campbell Morgan | 1863–1945 | Coming Soon |
| 05 | D. Martyn Lloyd-Jones | 1899–1981 | Coming Soon |
| 06 | W.A. Criswell | 1909–2002 | Coming Soon |
| 07 | R.C. Sproul | 1939–2017 | Coming Soon |
| 08 | John MacArthur | 1939– | Coming Soon |
| 09 | Haddon Robinson | 1931–2017 | Coming Soon |
| 10 | John Piper | 1946– | Coming Soon |
| 11 | D.A. Carson | 1946– | Coming Soon |
| 12 | Sinclair Ferguson | 1948– | Coming Soon |
| 13 | Tim Keller | 1950–2023 | Coming Soon |
| 14 | C.J. Mahaney | 1953– | Coming Soon |
| 15 | Mark Dever | 1960– | Coming Soon |
| 16 | Voddie Baucham | 1969– | Coming Soon |
| 17 | R.C. Sproul Jr. | 1965– | Coming Soon |

**Methodology section** (displayed on the page) explains three pillars: Corpus Decomposition (30–50 sermons per preacher, broken into functional units), Theological Metadata (16 doctrinal categories, BT move detection), and Rhetorical DNA (tone distribution, illustration frequency, application specificity, quotation patterns, cross-reference density).

**Join the Hall CTA** uses the four confirmed benefit bullets:
- Get access to every illustration and quote you've ever used
- Understand your preaching style and receive coaching for your craft
- Discover the book that's already written inside your archive
- Put your best material to work — social media, articles, and beyond

#### guild-hall-index.html (Full Source)

```html
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>The Guild Hall — Shepherd's Guild</title>
<link href="https://fonts.googleapis.com/css2?family=Cormorant+Garamond:ital,wght@0,300;0,400;0,500;0,600;0,700;1,400;1,500&family=DM+Sans:wght@300;400;500;600;700&family=JetBrains+Mono:wght@300;400;500&display=swap" rel="stylesheet">
<style>
  :root {
    --ink: #1a1714;
    --parchment: #f7f3ee;
    --cream: #ede8e0;
    --warm-gray: #9e9688;
    --gold: #c4a265;
    --gold-dim: #a8894f;
    --gold-bright: #dbb978;
    --burgundy: #6b2d3e;
    --burgundy-light: #8a3d52;
    --forest: #2d4a3e;
    --slate: #4a4640;
    --shadow-soft: 0 2px 20px rgba(26,23,20,0.06);
    --shadow-card: 0 4px 30px rgba(26,23,20,0.10);
  }
  * { margin: 0; padding: 0; box-sizing: border-box; }
  html { scroll-behavior: smooth; }
  body { font-family: 'DM Sans', sans-serif; background: var(--parchment); color: var(--ink); line-height: 1.7; -webkit-font-smoothing: antialiased; overflow-x: hidden; }

  /* HERO */
  .hero { min-height: 100vh; display: flex; flex-direction: column; justify-content: center; align-items: center; text-align: center; position: relative; background: var(--ink); color: var(--parchment); overflow: hidden; padding: 80px 30px 100px; }
  .hero::before { content: ''; position: absolute; inset: 0; background: radial-gradient(ellipse 80% 60% at 50% 40%, rgba(196,162,101,0.07) 0%, transparent 70%), radial-gradient(ellipse 50% 80% at 80% 20%, rgba(107,45,62,0.06) 0%, transparent 60%); pointer-events: none; }
  .hero::after { content: ''; position: absolute; inset: 0; background: url("data:image/svg+xml,%3Csvg width='60' height='60' viewBox='0 0 60 60' xmlns='http://www.w3.org/2000/svg'%3E%3Cg fill='none' fill-rule='evenodd'%3E%3Cg fill='%23c4a265' fill-opacity='0.03'%3E%3Cpath d='M36 34v-4h-2v4h-4v2h4v4h2v-4h4v-2h-4zm0-30V0h-2v4h-4v2h4v4h2V6h4V4h-4zM6 34v-4H4v4H0v2h4v4h2v-4h4v-2H6zM6 4V0H4v4H0v2h4v4h2V6h4V4H6z'/%3E%3C/g%3E%3C/g%3E%3C/svg%3E"); opacity: 0.5; pointer-events: none; }
  .hero-content { position: relative; z-index: 2; max-width: 760px; }
  .guild-mark { width: 60px; height: 60px; border: 1.5px solid var(--gold); border-radius: 50%; display: flex; align-items: center; justify-content: center; margin: 0 auto 48px; opacity: 0; animation: fadeUp 1s 0.2s forwards; }
  .guild-mark svg { width: 26px; height: 26px; }
  .hero-eyebrow { font-size: 0.68rem; font-weight: 600; letter-spacing: 0.28em; text-transform: uppercase; color: var(--gold); margin-bottom: 24px; opacity: 0; animation: fadeUp 1s 0.4s forwards; }
  .hero-title { font-family: 'Cormorant Garamond', serif; font-size: clamp(3.2rem, 7vw, 5.5rem); font-weight: 300; line-height: 1.05; letter-spacing: -0.02em; margin-bottom: 32px; opacity: 0; animation: fadeUp 1s 0.6s forwards; }
  .hero-title em { font-style: italic; color: var(--gold-bright); }
  .hero-divider { width: 1px; height: 48px; background: linear-gradient(to bottom, var(--gold), transparent); margin: 0 auto 32px; opacity: 0; animation: fadeUp 1s 0.8s forwards; }
  .hero-body { font-size: 1.05rem; color: rgba(247,243,238,0.6); max-width: 540px; margin: 0 auto 52px; line-height: 1.85; opacity: 0; animation: fadeUp 1s 0.9s forwards; }
  .hero-cta-group { display: flex; align-items: center; justify-content: center; gap: 20px; opacity: 0; animation: fadeUp 1s 1.05s forwards; flex-wrap: wrap; }
  .btn-primary { display: inline-flex; align-items: center; gap: 10px; background: var(--gold); color: var(--ink); font-size: 0.78rem; font-weight: 700; letter-spacing: 0.1em; text-transform: uppercase; text-decoration: none; padding: 14px 32px; border-radius: 4px; transition: all 0.25s; }
  .btn-primary:hover { background: var(--gold-bright); transform: translateY(-2px); box-shadow: 0 8px 30px rgba(196,162,101,0.3); }
  .btn-secondary { display: inline-flex; align-items: center; gap: 8px; color: rgba(247,243,238,0.55); font-size: 0.78rem; font-weight: 500; letter-spacing: 0.08em; text-transform: uppercase; text-decoration: none; padding: 14px 20px; border: 1px solid rgba(196,162,101,0.2); border-radius: 4px; transition: all 0.25s; }
  .btn-secondary:hover { color: var(--gold); border-color: rgba(196,162,101,0.5); }
  .scroll-hint { position: absolute; bottom: 44px; left: 50%; transform: translateX(-50%); opacity: 0; animation: fadeUp 1s 1.5s forwards; display: flex; flex-direction: column; align-items: center; gap: 8px; }
  .scroll-hint span { font-size: 0.6rem; letter-spacing: 0.2em; text-transform: uppercase; color: rgba(196,162,101,0.35); }
  .scroll-line { display: block; width: 1px; height: 36px; background: linear-gradient(to bottom, var(--gold), transparent); animation: scrollPulse 2s infinite; }
  @keyframes fadeUp { from { opacity: 0; transform: translateY(18px); } to { opacity: 1; transform: translateY(0); } }
  @keyframes scrollPulse { 0%,100% { opacity: 0.3; } 50% { opacity: 0.8; } }

  /* NAV */
  .nav { position: sticky; top: 0; z-index: 100; background: rgba(247,243,238,0.94); backdrop-filter: blur(16px); border-bottom: 1px solid rgba(196,162,101,0.15); padding: 0 30px; }
  .nav-inner { max-width: 1160px; margin: 0 auto; display: flex; align-items: center; justify-content: space-between; height: 56px; }
  .nav-brand { display: flex; align-items: center; gap: 10px; text-decoration: none; }
  .nav-brand-icon { width: 28px; height: 28px; border: 1px solid var(--gold); border-radius: 50%; display: flex; align-items: center; justify-content: center; }
  .nav-brand-icon svg { width: 12px; height: 12px; }
  .nav-brand-text { font-size: 0.72rem; font-weight: 600; letter-spacing: 0.12em; text-transform: uppercase; color: var(--ink); }
  .nav-brand-text span { color: var(--gold); }
  .nav-links { display: flex; align-items: center; gap: 4px; }
  .nav-links a { font-size: 0.7rem; font-weight: 500; letter-spacing: 0.06em; text-transform: uppercase; color: var(--slate); text-decoration: none; padding: 6px 12px; border-radius: 4px; transition: all 0.2s; }
  .nav-links a:hover { color: var(--burgundy); background: rgba(196,162,101,0.08); }
  .nav-cta { font-size: 0.68rem; font-weight: 600; letter-spacing: 0.1em; text-transform: uppercase; color: var(--ink); text-decoration: none; padding: 8px 18px; background: var(--gold); border-radius: 4px; transition: all 0.2s; }
  .nav-cta:hover { background: var(--gold-bright); }

  /* BODY */
  .page-body { max-width: 1160px; margin: 0 auto; padding: 0 30px; }
  section { padding: 100px 0; opacity: 0; transform: translateY(20px); transition: all 0.8s cubic-bezier(0.25,0.46,0.45,0.94); }
  section.visible { opacity: 1; transform: translateY(0); }
  .section-label { font-size: 0.65rem; font-weight: 600; letter-spacing: 0.3em; text-transform: uppercase; color: var(--gold); margin-bottom: 14px; }
  .section-title { font-family: 'Cormorant Garamond', serif; font-size: clamp(2rem,4vw,2.8rem); font-weight: 400; line-height: 1.2; margin-bottom: 20px; }
  .section-intro { font-size: 1rem; color: var(--slate); max-width: 600px; line-height: 1.85; margin-bottom: 64px; }

  /* STAT ROW */
  .stat-row { display: grid; grid-template-columns: repeat(4,1fr); background: var(--ink); border-radius: 16px; overflow: hidden; margin-bottom: 0; }
  .stat-cell { padding: 40px 28px; text-align: center; border-right: 1px solid rgba(196,162,101,0.1); }
  .stat-cell:last-child { border-right: none; }
  .stat-value { font-family: 'Cormorant Garamond', serif; font-size: 2.8rem; font-weight: 600; color: var(--gold-bright); line-height: 1; margin-bottom: 8px; }
  .stat-label { font-size: 0.68rem; font-weight: 500; letter-spacing: 0.15em; text-transform: uppercase; color: rgba(247,243,238,0.4); }

  /* PREACHERS GRID */
  .preachers-grid { display: grid; grid-template-columns: repeat(3,1fr); gap: 2px; background: rgba(196,162,101,0.12); border-radius: 16px; overflow: hidden; margin-bottom: 60px; }
  .preacher-card { background: #fff; padding: 26px 30px; display: flex; flex-direction: column; gap: 5px; text-decoration: none; color: inherit; position: relative; transition: all 0.25s; overflow: hidden; }
  .preacher-card::before { content: ''; position: absolute; left: 0; top: 0; bottom: 0; width: 3px; background: var(--gold); transform: scaleY(0); transition: transform 0.25s; transform-origin: bottom; }
  .preacher-card.available:hover { background: var(--parchment); transform: translateX(4px); }
  .preacher-card.available:hover::before { transform: scaleY(1); }
  .preacher-card.coming-soon { cursor: default; }
  .preacher-index { font-family: 'JetBrains Mono', monospace; font-size: 0.62rem; color: var(--gold); letter-spacing: 0.08em; }
  .preacher-name { font-family: 'Cormorant Garamond', serif; font-size: 1.22rem; font-weight: 600; line-height: 1.2; }
  .preacher-card.available .preacher-name { color: var(--ink); }
  .preacher-card.coming-soon .preacher-name { color: var(--warm-gray); }
  .preacher-dates { font-size: 0.72rem; color: var(--warm-gray); letter-spacing: 0.04em; }
  .preacher-tag { display: inline-flex; align-items: center; gap: 5px; font-size: 0.62rem; font-weight: 600; letter-spacing: 0.1em; text-transform: uppercase; margin-top: 4px; }
  .preacher-tag.live { color: var(--forest); }
  .preacher-tag.live::before { content: ''; width: 6px; height: 6px; border-radius: 50%; background: var(--forest); display: inline-block; }
  .preacher-tag.soon { color: var(--warm-gray); }
  .preacher-tag.soon::before { content: ''; width: 6px; height: 6px; border-radius: 50%; background: var(--cream); border: 1.5px solid var(--warm-gray); display: inline-block; }
  .preacher-arrow { position: absolute; right: 24px; top: 50%; transform: translateY(-50%) translateX(8px); opacity: 0; transition: all 0.25s; color: var(--gold); font-size: 1.1rem; }
  .preacher-card.available:hover .preacher-arrow { opacity: 1; transform: translateY(-50%) translateX(0); }

  /* EXPLAINER */
  .explainer-grid { display: grid; grid-template-columns: repeat(3,1fr); gap: 20px; margin-bottom: 60px; }
  .explainer-card { background: #fff; border-radius: 12px; padding: 32px; box-shadow: var(--shadow-soft); border: 1px solid rgba(196,162,101,0.08); }
  .explainer-icon { width: 44px; height: 44px; border-radius: 10px; display: flex; align-items: center; justify-content: center; margin-bottom: 20px; }
  .explainer-icon svg { width: 22px; height: 22px; }
  .explainer-title { font-family: 'Cormorant Garamond', serif; font-size: 1.2rem; font-weight: 600; margin-bottom: 10px; }
  .explainer-body { font-size: 0.87rem; color: var(--slate); line-height: 1.75; }

  /* PULL QUOTE */
  .pull-quote { border-left: 3px solid var(--gold); padding: 8px 0 8px 40px; margin: 20px 0 80px; max-width: 680px; }
  .pull-quote p { font-family: 'Cormorant Garamond', serif; font-size: 1.55rem; font-weight: 400; font-style: italic; line-height: 1.5; color: var(--ink); margin-bottom: 12px; }
  .pull-quote cite { font-size: 0.75rem; color: var(--warm-gray); letter-spacing: 0.08em; text-transform: uppercase; font-style: normal; }

  /* JOIN BANNER */
  .join-banner { background: var(--ink); border-radius: 20px; padding: 72px 64px; display: grid; grid-template-columns: 1fr auto; align-items: center; gap: 48px; position: relative; overflow: hidden; margin-bottom: 0; }
  .join-banner::before { content: ''; position: absolute; inset: 0; background: radial-gradient(ellipse 60% 80% at 20% 50%, rgba(196,162,101,0.07) 0%, transparent 70%), radial-gradient(ellipse 40% 60% at 90% 20%, rgba(107,45,62,0.06) 0%, transparent 60%); pointer-events: none; }
  .join-banner::after { content: ''; position: absolute; inset: 0; background: url("data:image/svg+xml,%3Csvg width='60' height='60' viewBox='0 0 60 60' xmlns='http://www.w3.org/2000/svg'%3E%3Cg fill='none' fill-rule='evenodd'%3E%3Cg fill='%23c4a265' fill-opacity='0.025'%3E%3Cpath d='M36 34v-4h-2v4h-4v2h4v4h2v-4h4v-2h-4zm0-30V0h-2v4h-4v2h4v4h2V6h4V4h-4zM6 34v-4H4v4H0v2h4v4h2v-4h4v-2H6zM6 4V0H4v4H0v2h4v4h2V6h4V4H6z'/%3E%3C/g%3E%3C/g%3E%3C/svg%3E"); pointer-events: none; }
  .join-content { position: relative; z-index: 2; }
  .join-eyebrow { font-size: 0.65rem; font-weight: 600; letter-spacing: 0.28em; text-transform: uppercase; color: var(--gold); margin-bottom: 16px; }
  .join-title { font-family: 'Cormorant Garamond', serif; font-size: clamp(1.8rem,3.5vw,2.8rem); font-weight: 300; color: var(--parchment); line-height: 1.2; margin-bottom: 16px; }
  .join-title strong { font-weight: 600; color: var(--gold-bright); }
  .join-body { font-size: 0.95rem; color: rgba(247,243,238,0.5); max-width: 480px; line-height: 1.8; }
  .join-action { position: relative; z-index: 2; flex-shrink: 0; display: flex; flex-direction: column; align-items: center; gap: 16px; }
  .join-btn { display: inline-flex; align-items: center; gap: 10px; background: var(--gold); color: var(--ink); font-size: 0.82rem; font-weight: 700; letter-spacing: 0.1em; text-transform: uppercase; text-decoration: none; padding: 18px 40px; border-radius: 6px; transition: all 0.25s; white-space: nowrap; }
  .join-btn:hover { background: var(--gold-bright); transform: translateY(-3px); box-shadow: 0 12px 40px rgba(196,162,101,0.35); }
  .join-note { font-size: 0.7rem; color: rgba(247,243,238,0.28); letter-spacing: 0.04em; text-align: center; }

  /* FOOTER */
  .site-footer { background: var(--ink); color: var(--parchment); padding: 80px 30px 48px; margin-top: 100px; }
  .footer-inner { max-width: 1160px; margin: 0 auto; display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 60px; padding-bottom: 60px; border-bottom: 1px solid rgba(196,162,101,0.1); }
  .footer-logo { display: flex; align-items: center; gap: 10px; margin-bottom: 16px; }
  .footer-logo-mark { width: 32px; height: 32px; border: 1px solid var(--gold-dim); border-radius: 50%; display: flex; align-items: center; justify-content: center; }
  .footer-logo-mark svg { width: 14px; height: 14px; }
  .footer-logo-text { font-size: 0.8rem; font-weight: 600; letter-spacing: 0.1em; text-transform: uppercase; }
  .footer-tagline { font-size: 0.85rem; color: rgba(247,243,238,0.35); line-height: 1.7; max-width: 240px; }
  .footer-col-title { font-size: 0.65rem; font-weight: 600; letter-spacing: 0.2em; text-transform: uppercase; color: var(--gold); margin-bottom: 20px; }
  .footer-links { list-style: none; display: flex; flex-direction: column; gap: 10px; }
  .footer-links a { font-size: 0.85rem; color: rgba(247,243,238,0.45); text-decoration: none; transition: color 0.2s; }
  .footer-links a:hover { color: var(--gold); }
  .footer-bottom { max-width: 1160px; margin: 0 auto; padding-top: 32px; display: flex; justify-content: space-between; align-items: center; }
  .footer-bottom p { font-size: 0.72rem; color: rgba(247,243,238,0.22); letter-spacing: 0.04em; }

  /* RESPONSIVE */
  @media (max-width: 900px) {
    .preachers-grid { grid-template-columns: repeat(2,1fr); }
    .explainer-grid { grid-template-columns: 1fr; }
    .stat-row { grid-template-columns: repeat(2,1fr); }
    .join-banner { grid-template-columns: 1fr; padding: 48px 36px; }
    .footer-inner { grid-template-columns: 1fr; gap: 40px; }
  }
  @media (max-width: 600px) {
    .preachers-grid { grid-template-columns: 1fr; }
    .nav-links { display: none; }
  }
</style>
</head>
<body>

<div class="hero">
  <div class="hero-content">
    <div class="guild-mark">
      <svg viewBox="0 0 24 24" fill="none" stroke="#c4a265" stroke-width="1.5">
        <path d="M12 2L2 7v10l10 5 10-5V7L12 2z"/>
        <path d="M12 22V12"/><path d="M2 7l10 5 10-5"/>
      </svg>
    </div>
    <div class="hero-eyebrow">Shepherd's Guild — The Guild Hall</div>
    <h1 class="hero-title">The Masters<br>of the <em>Pulpit</em></h1>
    <div class="hero-divider"></div>
    <p class="hero-body">A corpus study of history's most extraordinary preachers — their rhetorical fingerprints, theological emphases, and the DNA that made them unforgettable.</p>
    <div class="hero-cta-group">
      <a href="#preachers" class="btn-primary">Browse the Hall</a>
      <a href="#join" class="btn-secondary">Join the Hall →</a>
    </div>
  </div>
  <div class="scroll-hint"><span>Scroll</span><span class="scroll-line"></span></div>
</div>

<nav class="nav">
  <div class="nav-inner">
    <a href="#" class="nav-brand">
      <div class="nav-brand-icon">
        <svg viewBox="0 0 24 24" fill="none" stroke="#c4a265" stroke-width="1.5">
          <path d="M12 2L2 7v10l10 5 10-5V7L12 2z"/>
          <path d="M12 22V12"/><path d="M2 7l10 5 10-5"/>
        </svg>
      </div>
      <span class="nav-brand-text">Shepherd's Guild <span>/ The Guild Hall</span></span>
    </a>
    <div class="nav-links">
      <a href="#preachers">Preachers</a>
      <a href="#methodology">Methodology</a>
      <a href="#join">Join the Hall</a>
    </div>
    <a href="#join" class="nav-cta">Join the Hall</a>
  </div>
</nav>

<div class="page-body">

  <section id="stats">
    <div class="stat-row">
      <div class="stat-cell"><div class="stat-value">17</div><div class="stat-label">Preachers Profiled</div></div>
      <div class="stat-cell"><div class="stat-value">500+</div><div class="stat-label">Sermons Decomposed</div></div>
      <div class="stat-cell"><div class="stat-value">400yr</div><div class="stat-label">Span of Preaching</div></div>
      <div class="stat-cell"><div class="stat-value">16</div><div class="stat-label">Doctrinal Dimensions</div></div>
    </div>
  </section>

  <section id="preachers">
    <div class="section-label">The Preachers</div>
    <h2 class="section-title">Instruments in the Redeemer's Hands</h2>
    <p class="section-intro">These preachers were selected because history has already rendered its verdict on them — decades of faithful exposition across thousands of sermons, each with a voice distinct enough to be unmistakable. Together they represent the full range of what Reformed evangelical preaching can sound like: from Spurgeon's populist fire to Lloyd-Jones's systematic thunder to Mahaney's doxological preaching. The Guild Hall exists to make those differences visible, measurable, and useful — for pastors who are still in the middle of the work.</p>

    <div class="preachers-grid">
      <a href="spurgeon.html" class="preacher-card available">
        <div class="preacher-index">01</div>
        <div class="preacher-name">Charles Spurgeon</div>
        <div class="preacher-dates">1834 – 1892</div>
        <div class="preacher-tag live">Profile Available</div>
        <div class="preacher-arrow">→</div>
      </a>
      <div class="preacher-card coming-soon"><div class="preacher-index">02</div><div class="preacher-name">Thomas Watson</div><div class="preacher-dates">1620 – 1686</div><div class="preacher-tag soon">Coming Soon</div></div>
      <div class="preacher-card coming-soon"><div class="preacher-index">03</div><div class="preacher-name">J.C. Ryle</div><div class="preacher-dates">1816 – 1900</div><div class="preacher-tag soon">Coming Soon</div></div>
      <div class="preacher-card coming-soon"><div class="preacher-index">04</div><div class="preacher-name">G. Campbell Morgan</div><div class="preacher-dates">1863 – 1945</div><div class="preacher-tag soon">Coming Soon</div></div>
      <div class="preacher-card coming-soon"><div class="preacher-index">05</div><div class="preacher-name">D. Martyn Lloyd-Jones</div><div class="preacher-dates">1899 – 1981</div><div class="preacher-tag soon">Coming Soon</div></div>
      <div class="preacher-card coming-soon"><div class="preacher-index">06</div><div class="preacher-name">W.A. Criswell</div><div class="preacher-dates">1909 – 2002</div><div class="preacher-tag soon">Coming Soon</div></div>
      <div class="preacher-card coming-soon"><div class="preacher-index">07</div><div class="preacher-name">R.C. Sproul</div><div class="preacher-dates">1939 – 2017</div><div class="preacher-tag soon">Coming Soon</div></div>
      <div class="preacher-card coming-soon"><div class="preacher-index">08</div><div class="preacher-name">John MacArthur</div><div class="preacher-dates">1939 –</div><div class="preacher-tag soon">Coming Soon</div></div>
      <div class="preacher-card coming-soon"><div class="preacher-index">09</div><div class="preacher-name">Haddon Robinson</div><div class="preacher-dates">1931 – 2017</div><div class="preacher-tag soon">Coming Soon</div></div>
      <div class="preacher-card coming-soon"><div class="preacher-index">10</div><div class="preacher-name">John Piper</div><div class="preacher-dates">1946 –</div><div class="preacher-tag soon">Coming Soon</div></div>
      <div class="preacher-card coming-soon"><div class="preacher-index">11</div><div class="preacher-name">D.A. Carson</div><div class="preacher-dates">1946 –</div><div class="preacher-tag soon">Coming Soon</div></div>
      <div class="preacher-card coming-soon"><div class="preacher-index">12</div><div class="preacher-name">Sinclair Ferguson</div><div class="preacher-dates">1948 –</div><div class="preacher-tag soon">Coming Soon</div></div>
      <div class="preacher-card coming-soon"><div class="preacher-index">13</div><div class="preacher-name">Tim Keller</div><div class="preacher-dates">1950 – 2023</div><div class="preacher-tag soon">Coming Soon</div></div>
      <div class="preacher-card coming-soon"><div class="preacher-index">14</div><div class="preacher-name">C.J. Mahaney</div><div class="preacher-dates">1953 –</div><div class="preacher-tag soon">Coming Soon</div></div>
      <div class="preacher-card coming-soon"><div class="preacher-index">15</div><div class="preacher-name">Mark Dever</div><div class="preacher-dates">1960 –</div><div class="preacher-tag soon">Coming Soon</div></div>
      <div class="preacher-card coming-soon"><div class="preacher-index">16</div><div class="preacher-name">Voddie Baucham</div><div class="preacher-dates">1969 –</div><div class="preacher-tag soon">Coming Soon</div></div>
      <div class="preacher-card coming-soon"><div class="preacher-index">17</div><div class="preacher-name">R.C. Sproul Jr.</div><div class="preacher-dates">1965 –</div><div class="preacher-tag soon">Coming Soon</div></div>
    </div>
  </section>

  <div class="pull-quote">
    <p>"The greatest preachers in history left behind not just sermons — but a repeatable method. The Guild Hall exists to make that method visible."</p>
    <cite>Shepherd's Guild</cite>
  </div>

  <section id="methodology">
    <div class="section-label">The Methodology</div>
    <h2 class="section-title">How Every Profile Is Built</h2>
    <p class="section-intro">Every preacher in The Guild Hall is analyzed through the same proprietary decomposition pipeline — producing a consistent, comparable dataset across centuries of preaching.</p>
    <div class="explainer-grid">
      <div class="explainer-card">
        <div class="explainer-icon" style="background:rgba(107,45,62,0.08);">
          <svg viewBox="0 0 24 24" fill="none" stroke="#6b2d3e" stroke-width="1.5"><path d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2"/><rect x="9" y="3" width="6" height="4" rx="1"/><path d="M9 12h6M9 16h4"/></svg>
        </div>
        <div class="explainer-title">Corpus Decomposition</div>
        <div class="explainer-body">30–50 sermons per preacher, broken into functional units defined by rhetorical shift — not paragraph breaks or character count. Each unit typed: exposition, theological claim, illustration, application, and more.</div>
      </div>
      <div class="explainer-card">
        <div class="explainer-icon" style="background:rgba(45,74,62,0.08);">
          <svg viewBox="0 0 24 24" fill="none" stroke="#2d4a3e" stroke-width="1.5"><circle cx="12" cy="12" r="10"/><path d="M12 8v4l3 3"/></svg>
        </div>
        <div class="explainer-title">Theological Metadata</div>
        <div class="explainer-body">Every unit tagged across 16 doctrinal categories, with biblical-theological moves detected — typology, fulfillment, progressive revelation, intertextual echoes. The theological landscape made visible as data.</div>
      </div>
      <div class="explainer-card">
        <div class="explainer-icon" style="background:rgba(196,162,101,0.12);">
          <svg viewBox="0 0 24 24" fill="none" stroke="#a8894f" stroke-width="1.5"><polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/></svg>
        </div>
        <div class="explainer-title">Rhetorical DNA</div>
        <div class="explainer-body">Tone distribution, illustration frequency and type, application specificity, quotation patterns, cross-reference density. The fingerprint that makes each preacher sound like himself — and nobody else.</div>
      </div>
    </div>
  </section>

  <section id="join">
    <div class="join-banner">
      <div class="join-content">
        <div class="join-eyebrow">For Pastors</div>
        <h2 class="join-title">You've studied the masters.<br><strong>Now join the Hall.</strong></h2>
        <p class="join-body" style="margin-bottom:20px;">We have a vision for your preaching ministry.</p>
        <ul style="list-style:none;display:flex;flex-direction:column;gap:12px;padding:0;">
          <li style="display:flex;align-items:flex-start;gap:12px;font-size:0.9rem;color:rgba(247,243,238,0.55);line-height:1.6;"><span style="color:var(--gold);margin-top:2px;flex-shrink:0;">→</span>Get access to every illustration and quote you've ever used.</li>
          <li style="display:flex;align-items:flex-start;gap:12px;font-size:0.9rem;color:rgba(247,243,238,0.55);line-height:1.6;"><span style="color:var(--gold);margin-top:2px;flex-shrink:0;">→</span>Understand your preaching style and receive coaching for your craft.</li>
          <li style="display:flex;align-items:flex-start;gap:12px;font-size:0.9rem;color:rgba(247,243,238,0.55);line-height:1.6;"><span style="color:var(--gold);margin-top:2px;flex-shrink:0;">→</span>Discover the book that's already written inside your archive.</li>
          <li style="display:flex;align-items:flex-start;gap:12px;font-size:0.9rem;color:rgba(247,243,238,0.55);line-height:1.6;"><span style="color:var(--gold);margin-top:2px;flex-shrink:0;">→</span>Put your best material to work — social media, articles, and beyond.</li>
        </ul>
      </div>
      <div class="join-action">
        <a href="/join" class="join-btn">Join the Hall <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M5 12h14M12 5l7 7-7 7"/></svg></a>
        <p class="join-note">Corpus builds starting at $500</p>
      </div>
    </div>
  </section>

</div>

<footer class="site-footer">
  <div class="footer-inner">
    <div>
      <div class="footer-logo">
        <div class="footer-logo-mark"><svg viewBox="0 0 24 24" fill="none" stroke="#c4a265" stroke-width="1.5"><path d="M12 2L2 7v10l10 5 10-5V7L12 2z"/><path d="M12 22V12"/><path d="M2 7l10 5 10-5"/></svg></div>
        <span class="footer-logo-text">Shepherd's Guild</span>
      </div>
      <p class="footer-tagline">An ecosystem of encouragement and equipping for the local church pastor.</p>
    </div>
    <div>
      <div class="footer-col-title">The Guild Hall</div>
      <ul class="footer-links">
        <li><a href="#preachers">Browse Preachers</a></li>
        <li><a href="#methodology">Our Methodology</a></li>
        <li><a href="#join">Join the Hall</a></li>
      </ul>
    </div>
    <div>
      <div class="footer-col-title">Shepherd's Guild</div>
      <ul class="footer-links">
        <li><a href="#">Forge — Coaching</a></li>
        <li><a href="#">VoxPrint</a></li>
        <li><a href="#">BookGuide</a></li>
        <li><a href="#">Herald</a></li>
        <li><a href="#">Shepherd's Guild Daily</a></li>
      </ul>
    </div>
  </div>
  <div class="footer-bottom">
    <p>© 2026 Shepherd's Guild. All rights reserved.</p>
    <p>Proprietary decomposition methodology.</p>
  </div>
</footer>

<script>
const observer = new IntersectionObserver((entries) => {
  entries.forEach(e => { if (e.isIntersecting) e.target.classList.add('visible'); });
}, { threshold: 0.1 });
document.querySelectorAll('section').forEach(s => observer.observe(s));
document.querySelectorAll('a[href^="#"]').forEach(a => {
  a.addEventListener('click', e => {
    const t = document.querySelector(a.getAttribute('href'));
    if (t) { e.preventDefault(); t.scrollIntoView({ behavior: 'smooth', block: 'start' }); }
  });
});
</script>
</body>
</html>

```

---

### Ingester & Included Products

A white-glove service of the scrape/decomp process:

| Corpus Size | Price |
|---|---|
| 100–200 sermons | $500 |
| Up to 500 sermons | $1,000 |
| Larger corpora | Custom pricing |

---

### Report & Exemplar

A graphically pleasing HTML report providing a thorough breakdown of the preacher's sermonic approach, how his sermons compare with members of the Hall, and identification of 1–2 **exemplars** (Hall members we recommend he learn from going forward). **Provided free** as part of the Ingester service.

#### Decomposition Spec Wiki (Pastor-Facing Reference)

The Decomp Spec Wiki is a companion document provided to the preacher alongside his report. It serves as a **glossary and reference guide** so the preacher can understand what every field, enum, and metric in his report actually means. Without this, the report data is opaque — the pastor wouldn't know what "rhetorical_function: exposition" or "BT move: typology" signifies, or why his "application_specificity" score matters.

**Sections covered:**

1. **Sermon-Level Fields** — title, preacher, date, primary_text, sermon_type, series info, abstract, main_thesis, target_audience_cues, tone, hermeneutical_method
2. **Sermon Type** — expository, topical, textual, narrative, polemic (with full definitions)
3. **Tone** — pastoral, prophetic, didactic, celebratory, lament, polemic, evangelistic
4. **Hermeneutical Method** — grammatical_historical, redemptive_historical, canonical, applicatory, polemic
5. **Unit-Level Fields** — unit_index, rhetorical_function, content, summary, key_claim
6. **Rhetorical Function** — exposition, theological_claim, illustration, application, introduction, conclusion, transition, pastoral_aside, prayer (with rich definitions and examples)
7. **Three-Tier Citation Architecture** — Tier 1 (primary text citations), Tier 2 (cross-references), Tier 3 (human-author quotations) with visual tier stack
8. **Doctrinal Loci** — all 16 categories with full definitions (Theology Proper through Pastoral Theology)
9. **Biblical-Theological Moves** — typology, fulfillment, progressive_revelation, narrative_arc, intertextual_echo, contrast, thematic_thread
10. **Pending Spec Additions** — illustration_type, rhetorical_register, anticipated_objection, serves_unit, application_specificity, hinge_statement, is_fcf_moment

The wiki uses the canonical Shepherd's Guild visual system (dark parchment, Cormorant Garamond + DM Sans + JetBrains Mono, gold/burgundy/forest accents).

#### decomp-spec-wiki.html (Full Source)

```html
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Shepherd's Guild — Decomposition Spec Wiki</title>
<link href="https://fonts.googleapis.com/css2?family=Cormorant+Garamond:ital,wght@0,300;0,400;0,500;0,600;0,700;1,400;1,500&family=DM+Sans:wght@300;400;500;600;700&family=JetBrains+Mono:wght@300;400;500&display=swap" rel="stylesheet">
<style>
  :root {
    --ink: #1a1714;
    --parchment: #f7f3ee;
    --cream: #ede8e0;
    --warm-gray: #9e9688;
    --gold: #c4a265;
    --gold-dim: #a8894f;
    --gold-bright: #dbb978;
    --burgundy: #6b2d3e;
    --burgundy-light: #8a3d52;
    --forest: #2d4a3e;
    --slate: #4a4640;
    --shadow-soft: 0 2px 20px rgba(26, 23, 20, 0.06);
    --shadow-card: 0 4px 30px rgba(26, 23, 20, 0.08);
  }

  * { margin: 0; padding: 0; box-sizing: border-box; }
  html { scroll-behavior: smooth; font-size: 16px; }

  body {
    font-family: 'DM Sans', sans-serif;
    background: var(--parchment);
    color: var(--ink);
    line-height: 1.7;
    -webkit-font-smoothing: antialiased;
  }

  /* ── COVER ── */
  .cover {
    min-height: 60vh;
    display: flex;
    flex-direction: column;
    justify-content: center;
    align-items: center;
    text-align: center;
    background: var(--ink);
    color: var(--parchment);
    padding: 60px 30px;
    position: relative;
    overflow: hidden;
  }

  .cover::before {
    content: '';
    position: absolute;
    inset: 0;
    background:
      radial-gradient(ellipse 80% 60% at 50% 40%, rgba(196,162,101,0.08) 0%, transparent 70%),
      radial-gradient(ellipse 50% 80% at 80% 20%, rgba(107,45,62,0.06) 0%, transparent 60%);
    pointer-events: none;
  }

  .cover::after {
    content: '';
    position: absolute;
    inset: 0;
    background: url("data:image/svg+xml,%3Csvg width='60' height='60' viewBox='0 0 60 60' xmlns='http://www.w3.org/2000/svg'%3E%3Cg fill='none' fill-rule='evenodd'%3E%3Cg fill='%23c4a265' fill-opacity='0.03'%3E%3Cpath d='M36 34v-4h-2v4h-4v2h4v4h2v-4h4v-2h-4zm0-30V0h-2v4h-4v2h4v4h2V6h4V4h-4zM6 34v-4H4v4H0v2h4v4h2v-4h4v-2H6zM6 4V0H4v4H0v2h4v4h2V6h4V4H6z'/%3E%3C/g%3E%3C/g%3E%3C/svg%3E");
    opacity: 0.5;
    pointer-events: none;
  }

  .cover-content {
    position: relative;
    z-index: 2;
    max-width: 700px;
  }

  .guild-mark {
    width: 56px;
    height: 56px;
    border: 1.5px solid var(--gold);
    border-radius: 50%;
    display: flex;
    align-items: center;
    justify-content: center;
    margin: 0 auto 40px;
    opacity: 0;
    animation: fadeUp 1s 0.2s forwards;
  }

  .guild-mark svg { width: 24px; height: 24px; }

  .cover-label {
    font-size: 0.7rem;
    font-weight: 600;
    letter-spacing: 0.25em;
    text-transform: uppercase;
    color: var(--gold);
    margin-bottom: 32px;
    opacity: 0;
    animation: fadeUp 1s 0.4s forwards;
  }

  .cover-title {
    font-family: 'Cormorant Garamond', serif;
    font-size: clamp(2.4rem, 5vw, 3.8rem);
    font-weight: 300;
    line-height: 1.15;
    margin-bottom: 12px;
    opacity: 0;
    animation: fadeUp 1s 0.6s forwards;
  }

  .cover-subtitle {
    font-family: 'Cormorant Garamond', serif;
    font-size: clamp(1rem, 2vw, 1.3rem);
    font-weight: 400;
    font-style: italic;
    color: var(--gold-bright);
    margin-bottom: 48px;
    opacity: 0;
    animation: fadeUp 1s 0.8s forwards;
  }

  .cover-divider {
    width: 40px;
    height: 1px;
    background: var(--gold);
    margin: 0 auto;
    opacity: 0;
    animation: fadeUp 1s 1s forwards;
  }

  @keyframes fadeUp {
    from { opacity: 0; transform: translateY(16px); }
    to { opacity: 1; transform: translateY(0); }
  }

  /* ── NAV ── */
  .nav {
    position: sticky;
    top: 0;
    z-index: 100;
    background: rgba(247, 243, 238, 0.92);
    backdrop-filter: blur(16px);
    border-bottom: 1px solid rgba(196, 162, 101, 0.15);
    padding: 0 30px;
  }

  .nav-inner {
    max-width: 1100px;
    margin: 0 auto;
    display: flex;
    align-items: center;
    height: 52px;
    gap: 4px;
    overflow-x: auto;
    scrollbar-width: none;
  }

  .nav-inner::-webkit-scrollbar { display: none; }

  .nav a {
    font-size: 0.68rem;
    font-weight: 500;
    letter-spacing: 0.06em;
    text-transform: uppercase;
    color: var(--slate);
    text-decoration: none;
    padding: 6px 10px;
    border-radius: 4px;
    white-space: nowrap;
    transition: all 0.2s;
  }

  .nav a:hover {
    color: var(--burgundy);
    background: rgba(196, 162, 101, 0.1);
  }

  /* ── BODY ── */
  .report-body {
    max-width: 1100px;
    margin: 0 auto;
    padding: 0 30px;
  }

  section {
    padding: 72px 0 40px;
    opacity: 0;
    transform: translateY(20px);
    transition: all 0.8s cubic-bezier(0.25, 0.46, 0.45, 0.94);
  }

  section.visible {
    opacity: 1;
    transform: translateY(0);
  }

  .section-label {
    font-size: 0.65rem;
    font-weight: 600;
    letter-spacing: 0.3em;
    text-transform: uppercase;
    color: var(--gold);
    margin-bottom: 12px;
  }

  .section-title {
    font-family: 'Cormorant Garamond', serif;
    font-size: clamp(1.8rem, 4vw, 2.4rem);
    font-weight: 400;
    line-height: 1.2;
    margin-bottom: 12px;
    color: var(--ink);
  }

  .section-intro {
    font-size: 0.98rem;
    color: var(--slate);
    max-width: 680px;
    margin-bottom: 40px;
    line-height: 1.8;
  }

  /* ── TERM CARDS ── */
  .term-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
    gap: 16px;
    margin-bottom: 40px;
  }

  .term-card {
    background: #fff;
    border-radius: 12px;
    padding: 24px 28px;
    box-shadow: var(--shadow-soft);
    border: 1px solid rgba(196, 162, 101, 0.08);
    transition: all 0.3s;
    position: relative;
  }

  .term-card:hover {
    box-shadow: var(--shadow-card);
    transform: translateY(-2px);
  }

  .term-card.full-width {
    grid-column: 1 / -1;
  }

  .term-name {
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.82rem;
    font-weight: 500;
    color: var(--burgundy);
    margin-bottom: 6px;
    letter-spacing: -0.01em;
  }

  .term-category {
    font-size: 0.62rem;
    font-weight: 600;
    letter-spacing: 0.15em;
    text-transform: uppercase;
    color: var(--warm-gray);
    margin-bottom: 10px;
  }

  .term-def {
    font-size: 0.88rem;
    color: var(--slate);
    line-height: 1.7;
  }

  .term-def strong {
    color: var(--ink);
    font-weight: 600;
  }

  .term-example {
    margin-top: 10px;
    padding-top: 10px;
    border-top: 1px solid var(--cream);
    font-size: 0.82rem;
    color: var(--warm-gray);
    font-style: italic;
    line-height: 1.6;
  }

  .term-badge {
    position: absolute;
    top: 16px;
    right: 16px;
    font-size: 0.58rem;
    font-weight: 600;
    letter-spacing: 0.1em;
    text-transform: uppercase;
    padding: 3px 8px;
    border-radius: 4px;
    background: rgba(196, 162, 101, 0.12);
    color: var(--gold-dim);
  }

  .term-badge.pending {
    background: rgba(107, 45, 62, 0.1);
    color: var(--burgundy);
  }

  /* ── SECTION DIVIDER ── */
  .section-divider {
    width: 40px;
    height: 1px;
    background: var(--gold);
    margin: 0 0 40px;
  }

  /* ── ENUM TABLE ── */
  .enum-table {
    width: 100%;
    border-collapse: collapse;
    margin-bottom: 40px;
  }

  .enum-table th {
    font-size: 0.68rem;
    font-weight: 600;
    letter-spacing: 0.15em;
    text-transform: uppercase;
    color: var(--warm-gray);
    text-align: left;
    padding: 10px 16px;
    border-bottom: 2px solid var(--cream);
  }

  .enum-table td {
    padding: 14px 16px;
    border-bottom: 1px solid var(--cream);
    font-size: 0.88rem;
    color: var(--slate);
    line-height: 1.6;
    vertical-align: top;
  }

  .enum-table td:first-child {
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.8rem;
    font-weight: 500;
    color: var(--burgundy);
    white-space: nowrap;
    width: 200px;
  }

  .enum-table tr:hover td {
    background: rgba(196, 162, 101, 0.04);
  }

  /* ── TIER VISUALIZATION ── */
  .tier-stack {
    display: flex;
    flex-direction: column;
    gap: 0;
    margin-bottom: 40px;
  }

  .tier-block {
    padding: 28px 32px;
    border-left: 4px solid;
    background: #fff;
    position: relative;
  }

  .tier-block:first-child {
    border-radius: 12px 12px 0 0;
    box-shadow: 0 -2px 20px rgba(26,23,20,0.04);
  }
  .tier-block:last-child {
    border-radius: 0 0 12px 12px;
    box-shadow: 0 4px 20px rgba(26,23,20,0.06);
  }

  .tier-block + .tier-block {
    border-top: 1px solid var(--cream);
  }

  .tier-block.t1 { border-left-color: var(--burgundy); }
  .tier-block.t2 { border-left-color: var(--gold); }
  .tier-block.t3 { border-left-color: var(--forest); }

  .tier-label {
    font-size: 0.62rem;
    font-weight: 600;
    letter-spacing: 0.2em;
    text-transform: uppercase;
    margin-bottom: 6px;
  }

  .tier-block.t1 .tier-label { color: var(--burgundy); }
  .tier-block.t2 .tier-label { color: var(--gold-dim); }
  .tier-block.t3 .tier-label { color: var(--forest); }

  .tier-title {
    font-family: 'Cormorant Garamond', serif;
    font-size: 1.3rem;
    font-weight: 600;
    color: var(--ink);
    margin-bottom: 8px;
  }

  .tier-desc {
    font-size: 0.88rem;
    color: var(--slate);
    line-height: 1.7;
    margin-bottom: 12px;
  }

  .tier-fields {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
  }

  .field-tag {
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.7rem;
    padding: 3px 10px;
    border-radius: 4px;
    background: var(--cream);
    color: var(--slate);
  }

  /* ── PENDING SECTION ── */
  .pending-banner {
    background: linear-gradient(135deg, var(--ink) 0%, #2a2520 100%);
    border-radius: 16px;
    padding: 40px;
    color: var(--parchment);
    margin-bottom: 40px;
  }

  .pending-banner .section-label {
    color: var(--gold-bright);
  }

  .pending-banner .section-title {
    color: var(--parchment);
    margin-bottom: 8px;
  }

  .pending-banner .section-intro {
    color: rgba(247,243,238,0.6);
  }

  .pending-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
    gap: 12px;
  }

  .pending-card {
    background: rgba(255,255,255,0.06);
    border: 1px solid rgba(196,162,101,0.15);
    border-radius: 10px;
    padding: 20px 24px;
  }

  .pending-card .term-name {
    color: var(--gold-bright);
  }

  .pending-card .term-category {
    color: rgba(247,243,238,0.4);
  }

  .pending-card .term-def {
    color: rgba(247,243,238,0.7);
  }

  .pending-card .products {
    margin-top: 10px;
    display: flex;
    gap: 6px;
    flex-wrap: wrap;
  }

  .product-tag {
    font-size: 0.6rem;
    font-weight: 600;
    letter-spacing: 0.1em;
    text-transform: uppercase;
    padding: 2px 8px;
    border-radius: 3px;
    background: rgba(196,162,101,0.15);
    color: var(--gold-bright);
  }

  /* ── FOOTER ── */
  .report-footer {
    background: var(--ink);
    color: var(--parchment);
    padding: 60px 30px;
    text-align: center;
    margin-top: 40px;
  }

  .footer-mark {
    width: 40px;
    height: 40px;
    border: 1px solid var(--gold-dim);
    border-radius: 50%;
    display: flex;
    align-items: center;
    justify-content: center;
    margin: 0 auto 24px;
  }

  .footer-mark svg { width: 18px; height: 18px; }

  .footer-brand {
    font-family: 'Cormorant Garamond', serif;
    font-size: 1.1rem;
    font-weight: 500;
    color: var(--gold);
    letter-spacing: 0.08em;
  }

  .footer-text {
    font-size: 0.78rem;
    color: var(--warm-gray);
    margin-top: 8px;
  }

  /* ── RESPONSIVE ── */
  @media (max-width: 768px) {
    .term-grid { grid-template-columns: 1fr; }
    .enum-table td:first-child { width: auto; }
    .pending-grid { grid-template-columns: 1fr; }
    .tier-block { padding: 20px 24px; }
  }

  @media print {
    .nav { display: none; }
    section { opacity: 1 !important; transform: none !important; }
  }
</style>
</head>
<body>

<!-- ═══════ COVER ═══════ -->
<div class="cover">
  <div class="cover-content">
    <div class="guild-mark">
      <svg viewBox="0 0 24 24" fill="none" stroke="#c4a265" stroke-width="1.5">
        <path d="M12 2L2 7v10l10 5 10-5V7L12 2z"/>
        <path d="M12 22V12"/>
        <path d="M2 7l10 5 10-5"/>
      </svg>
    </div>
    <div class="cover-label">Shepherd's Guild — Reference Document</div>
    <h1 class="cover-title">Decomposition Spec Wiki</h1>
    <p class="cover-subtitle">A glossary of every field, enum, and taxonomy in the Sermon Decomposition Spec v2</p>
    <div class="cover-divider"></div>
  </div>
</div>

<!-- ═══════ NAV ═══════ -->
<nav class="nav">
  <div class="nav-inner">
    <a href="#sermon-level">Sermon-Level</a>
    <a href="#sermon-type">Sermon Type</a>
    <a href="#tone">Tone</a>
    <a href="#hermeneutics">Hermeneutics</a>
    <a href="#units">Units</a>
    <a href="#rhetorical">Rhetorical Function</a>
    <a href="#citations">Citations</a>
    <a href="#doctrine">Doctrine</a>
    <a href="#bt-moves">BT Moves</a>
    <a href="#pending">Pending</a>
  </div>
</nav>

<div class="report-body">

<!-- ═══════ SERMON-LEVEL FIELDS ═══════ -->
<section id="sermon-level">
  <div class="section-label">01 — Sermon-Level Fields</div>
  <h2 class="section-title">The Metadata Envelope</h2>
  <p class="section-intro">Every sermon receives a complete set of top-level metadata before being broken into functional units. These fields serve discovery, filtering, and clustering across the entire corpus.</p>

  <div class="term-grid">
    <div class="term-card">
      <div class="term-name">title</div>
      <div class="term-category">String</div>
      <div class="term-def">The sermon's title as given in the manuscript or as inferred from the content. If the pastor titled it, use his title. If untitled, construct one from the primary text and main thesis.</div>
    </div>
    <div class="term-card">
      <div class="term-name">preacher</div>
      <div class="term-category">String</div>
      <div class="term-def">The name of the pastor or speaker who delivered the sermon. Used for corpus-level attribution and multi-pastor church archives.</div>
    </div>
    <div class="term-card">
      <div class="term-name">date</div>
      <div class="term-category">String / Null</div>
      <div class="term-def">The date the sermon was preached, if detectable from the manuscript. Enables chronological browsing and tracking how a pastor's treatment of themes evolves over time.</div>
    </div>
    <div class="term-card">
      <div class="term-name">primary_text</div>
      <div class="term-category">Scripture Reference</div>
      <div class="term-def">The main scripture passage for the sermon as a whole — the text being exposited. This is distinct from cross-references (other passages brought in for support). A sermon on Romans 8:28-30 has that as its primary text, even if it also quotes Isaiah and Ephesians.</div>
    </div>
    <div class="term-card">
      <div class="term-name">series_name / series_position</div>
      <div class="term-category">String / Null</div>
      <div class="term-def">If the sermon belongs to a preaching series, the series name and position (e.g., "Part 3 of 7"). Enables series-level browsing and tracking how the pastor builds argument across multiple weeks.</div>
    </div>
    <div class="term-card">
      <div class="term-name">abstract</div>
      <div class="term-category">String (4–6 sentences)</div>
      <div class="term-def">The sermon's argument in compressed form. Not a teaser or marketing blurb — a genuine summary capturing the logical arc from problem to resolution. Should enable someone to understand the sermon's full trajectory without reading it.</div>
    </div>
    <div class="term-card">
      <div class="term-name">main_thesis</div>
      <div class="term-category">String (1 sentence)</div>
      <div class="term-def">The sermon's controlling claim — the single proposition the entire sermon exists to establish. Every unit in the sermon should, in some way, serve this thesis. If you had to reduce the sermon to one sentence, this is it.</div>
    </div>
    <div class="term-card">
      <div class="term-name">target_audience_cues</div>
      <div class="term-category">String</div>
      <div class="term-def">Detectable signals about who the sermon is addressing. Not the literal audience (the congregation), but rhetorical audience markers: "new believers," "parents," "leaders," "the whole congregation," "the discouraged." Reveals what the pastor assumes about his listeners' needs.</div>
    </div>
    <div class="term-card">
      <div class="term-name">all_quotations</div>
      <div class="term-category">Rolled-Up Array</div>
      <div class="term-def">A top-level convenience array collecting every human-author quotation from across all units, with <code>unit_index</code> references back to where each appears. Enables corpus-wide quotation search without scanning every unit.</div>
    </div>
    <div class="term-card">
      <div class="term-name">all_cross_references</div>
      <div class="term-category">Rolled-Up Array</div>
      <div class="term-def">A top-level convenience array collecting every cross-reference (scripture from outside the primary text) across all units, with <code>unit_index</code> references. Enables corpus-wide scripture search.</div>
    </div>
  </div>
</section>

<!-- ═══════ SERMON TYPE ═══════ -->
<section id="sermon-type">
  <div class="section-label">02 — Sermon Type</div>
  <h2 class="section-title">Classification by Structure</h2>
  <p class="section-intro">How the sermon is architecturally organized — what principle governs the outline and the flow of argument.</p>

  <table class="enum-table">
    <thead>
      <tr><th>Value</th><th>Definition</th></tr>
    </thead>
    <tbody>
      <tr>
        <td>expository</td>
        <td>The sermon walks through a passage of Scripture verse by verse or section by section. The text's own structure determines the sermon's structure. The pastor's job is to explain what the text says, what it means, and what it demands. The most common type in Reformed/evangelical preaching.</td>
      </tr>
      <tr>
        <td>topical</td>
        <td>The sermon is organized around a topic or theme rather than a single passage. Scripture is brought in to support the topic, but no one passage drives the structure. Example: "What the Bible says about anxiety" drawing from multiple books.</td>
      </tr>
      <tr>
        <td>textual</td>
        <td>The sermon takes a short text (often a single verse or phrase) and develops multiple points from it — but without walking through surrounding context the way an expository sermon would. The text provides the seed; the sermon grows outward from it.</td>
      </tr>
      <tr>
        <td>narrative</td>
        <td>The sermon follows a biblical narrative (a story), retelling and interpreting it in sequence. The structure mirrors the story's own arc: setting, conflict, resolution, meaning. Common in Old Testament preaching on Genesis, Exodus, the historical books.</td>
      </tr>
      <tr>
        <td>polemic</td>
        <td>The sermon is organized as an argument against a specific error, false teaching, or cultural position. Scripture is marshaled as evidence in a case. Rare in most pastoral preaching but appears when a pastor addresses a doctrinal controversy directly.</td>
      </tr>
    </tbody>
  </table>
</section>

<!-- ═══════ TONE ═══════ -->
<section id="tone">
  <div class="section-label">03 — Tone</div>
  <h2 class="section-title">Emotional & Rhetorical Register</h2>
  <p class="section-intro">The overall emotional posture of the sermon. Multiple tones can coexist — a sermon can be both pastoral and prophetic, or didactic and celebratory. The array captures the blend.</p>

  <table class="enum-table">
    <thead>
      <tr><th>Value</th><th>Definition</th></tr>
    </thead>
    <tbody>
      <tr>
        <td>pastoral</td>
        <td>The voice of the shepherd. Warm, caring, personally engaged with the listener's struggles and needs. The pastor speaks as one who knows his people and wants their good. Marked by direct address, empathy, and comfort.</td>
      </tr>
      <tr>
        <td>prophetic</td>
        <td>The voice of confrontation. The pastor addresses sin, complacency, injustice, or spiritual danger with urgency and moral weight. Not angry — authoritative. The tone says "this must change" and carries the weight of divine mandate behind it.</td>
      </tr>
      <tr>
        <td>didactic</td>
        <td>The voice of the teacher. Information-dense, explanatory, structured for comprehension. The pastor is primarily transmitting knowledge — explaining a doctrine, clarifying a text, building conceptual scaffolding. The emotional temperature is cooler; the intellectual demand is higher.</td>
      </tr>
      <tr>
        <td>celebratory</td>
        <td>The voice of worship. Joyful, exultant, marked by wonder at who God is and what he has done. Often surfaces at theological climaxes — the moment the sermon lands on a truth so good the response is praise rather than instruction.</td>
      </tr>
      <tr>
        <td>lament</td>
        <td>The voice of grief. The pastor enters into suffering — the congregation's, the world's, his own — and gives it voice. Honest about pain without rushing to resolution. Theologically grounded sorrow that makes space for the hard realities of life in a fallen world.</td>
      </tr>
      <tr>
        <td>polemic</td>
        <td>The voice of contention. The pastor engages a specific error, false teaching, or dangerous idea and argues against it directly. Distinguished from prophetic by its target: prophetic confronts behavior; polemic confronts ideas.</td>
      </tr>
      <tr>
        <td>evangelistic</td>
        <td>The voice of invitation. The pastor addresses the unconverted or the uncommitted and urges them toward Christ. Marked by direct appeal, promise-centered language, urgency, and an explicit call to respond. Can be warm or urgent or both.</td>
      </tr>
    </tbody>
  </table>
</section>

<!-- ═══════ HERMENEUTICS ═══════ -->
<section id="hermeneutics">
  <div class="section-label">04 — Hermeneutical Method</div>
  <h2 class="section-title">How the Pastor Reads the Text</h2>
  <p class="section-intro">The interpretive lens the pastor brings to the passage. Most sermons use more than one method — an expository sermon might be primarily grammatical-historical but include a redemptive-historical move when it connects the Old Testament text to Christ. The array captures the blend.</p>

  <table class="enum-table">
    <thead>
      <tr><th>Value</th><th>Definition</th></tr>
    </thead>
    <tbody>
      <tr>
        <td>grammatical_historical</td>
        <td>Close attention to the original language, historical context, and authorial intent. The pastor asks: what did these words mean to the original audience in their original setting? Word studies, verb tenses, cultural background, literary structure. The bread and butter of expository preaching.</td>
      </tr>
      <tr>
        <td>redemptive_historical</td>
        <td>The passage is read as a moment in the unfolding drama of redemption — creation, fall, redemption, consummation. A Christotelic reading: every text points toward, anticipates, or finds its fulfillment in Christ, even when Christ is not explicitly named. The pastor traces the trajectory from this text to the cross and beyond.</td>
      </tr>
      <tr>
        <td>canonical</td>
        <td>Interpreting the passage in light of the whole canon of Scripture. "Scripture interprets Scripture" is the active method — the pastor brings other biblical texts to bear on this one, building an intertextual web. When a pastor reads a Psalm through the lens of Paul's letters, that's canonical hermeneutics at work.</td>
      </tr>
      <tr>
        <td>applicatory</td>
        <td>Primary emphasis on "what does this mean for us" with less exegetical scaffolding. The pastor moves quickly from text to life — the interpretive energy goes into bridging the gap between ancient text and modern listener. Common in topical preaching and in pastors whose gift is practical wisdom.</td>
      </tr>
      <tr>
        <td>polemic</td>
        <td>The passage is marshaled to refute an error or defend a contested doctrine. The interpretive lens is adversarial — the pastor reads the text with a specific opponent in view (whether named or unnamed) and draws out the text's implications for that dispute.</td>
      </tr>
    </tbody>
  </table>
</section>

<!-- ═══════ UNIT-LEVEL FIELDS ═══════ -->
<section id="units">
  <div class="section-label">05 — Unit-Level Fields</div>
  <h2 class="section-title">The Functional Unit</h2>
  <p class="section-intro">Each sermon is decomposed into functional units — sections defined by rhetorical function shift, not paragraph breaks or character count. A unit can be a single sentence (a transition) or several paragraphs (extended exposition). When the rhetorical function changes, a new unit begins.</p>

  <div class="term-grid">
    <div class="term-card">
      <div class="term-name">unit_index</div>
      <div class="term-category">Integer</div>
      <div class="term-def">Sequential position in the sermon, starting at 1. Defines the order of units and enables cross-referencing between units (e.g., "this illustration serves the claim made in unit 5").</div>
    </div>
    <div class="term-card">
      <div class="term-name">rhetorical_function</div>
      <div class="term-category">Enum (9 values)</div>
      <div class="term-def">The primary purpose this unit serves in the sermon's argument. The controlled taxonomy of nine functions is the backbone of the decomposition — it's what makes the data searchable, filterable, and commercially valuable. See next section for full definitions.</div>
    </div>
    <div class="term-card">
      <div class="term-name">content</div>
      <div class="term-category">String (Verbatim)</div>
      <div class="term-def">The pastor's exact language for this unit. <strong>No paraphrasing, no cleanup, no grammatical correction.</strong> The voice is the asset. Every product downstream depends on having the authentic words. If the pastor said "ain't" or started a sentence with "And," that's what appears here.</div>
    </div>
    <div class="term-card">
      <div class="term-name">summary</div>
      <div class="term-category">String (2–3 sentences)</div>
      <div class="term-def">What this unit accomplishes in the sermon's argument — not what it says, but what it <em>does</em>. "This unit establishes the historical context for Moses' complaint" rather than "Moses complains to God." The summary captures function, not just content.</div>
    </div>
    <div class="term-card">
      <div class="term-name">key_claim</div>
      <div class="term-category">String (1 sentence) / Null</div>
      <div class="term-def">The single most important assertion this unit makes. A propositional distillation — the one thing you'd remember if you forgot everything else. Null for transitions, prayers, and some illustrations that serve other units' claims rather than making claims of their own.</div>
    </div>
    <div class="term-card">
      <div class="term-name">people_referenced</div>
      <div class="term-category">Array of Strings</div>
      <div class="term-def">Historical figures, theologians, biblical characters mentioned in this unit. Enables searching the corpus for every time the pastor mentions Augustine, or Luther, or Ruth, or Nebuchadnezzar.</div>
    </div>
  </div>
</section>

<!-- ═══════ RHETORICAL FUNCTION ═══════ -->
<section id="rhetorical">
  <div class="section-label">06 — Rhetorical Function Taxonomy</div>
  <h2 class="section-title">Nine Functions</h2>
  <p class="section-intro">The controlled vocabulary for what a unit does in the sermon. This taxonomy is the core IP — it's what separates annotated argument structure from raw transcripts. Only these nine values are permitted; the model may not invent new ones.</p>

  <table class="enum-table">
    <thead>
      <tr><th>Value</th><th>Definition</th></tr>
    </thead>
    <tbody>
      <tr>
        <td>exposition</td>
        <td>Direct engagement with the biblical text. The pastor is doing exegetical work: explaining what a word means, unpacking a verb tense, providing historical context, tracing the logic of a passage. The text is the subject; the pastor is the guide. This is where the interpretive homework lives.</td>
      </tr>
      <tr>
        <td>theological_claim</td>
        <td>A doctrinal assertion derived from or supported by the exposition. The pastor moves from "the text says this" to "therefore this is true about God, humanity, salvation, etc." The claim may be explicitly stated or implicitly constructed from the exposition. Distinguished from exposition by its propositional nature — it asserts, not just explains.</td>
      </tr>
      <tr>
        <td>illustration</td>
        <td>A story, analogy, historical example, or hypothetical scenario that serves the argument. Illustrations don't make claims — they make claims vivid, memorable, or emotionally accessible. They exist to serve a prior or subsequent claim. A pastor who tells a story about his father is illustrating; the point he draws from the story is a claim or application.</td>
      </tr>
      <tr>
        <td>application</td>
        <td>Direct address about what to do, believe, or become in response to the truth established. The pastor shifts from "this is true" to "here's what that means for you Monday morning." Characterized by imperative verbs, second-person address, and concrete instruction. The bridge from doctrine to life.</td>
      </tr>
      <tr>
        <td>introduction</td>
        <td>The opening frame of the sermon. Sets up the text, the problem, the question, or the tension the sermon will address. May include a hook (attention-getter), a reading of the primary text, or contextual background. Its job is to make the congregation care about what's coming.</td>
      </tr>
      <tr>
        <td>conclusion</td>
        <td>The closing frame. Summarizes the argument, reiterates the main thesis, issues a final charge, or lifts the congregation into worship. Often the most emotionally concentrated unit in the sermon. A good conclusion doesn't just end — it lands.</td>
      </tr>
      <tr>
        <td>transition</td>
        <td>Connective tissue between major sections. "Having seen what the text says, let's now ask what it means." "That's the first point. Here's the second." Transitions signal structural shifts and help the listener track the argument. Can be as short as a single sentence.</td>
      </tr>
      <tr>
        <td>pastoral_aside</td>
        <td>A direct shepherding moment where the pastor steps outside the expositional flow to address his people personally. "I know some of you are going through a season of doubt right now." "If you're struggling with this, please come talk to me." The voice shifts from teacher to shepherd. Marked by sudden intimacy and personal concern.</td>
      </tr>
      <tr>
        <td>prayer</td>
        <td>An opening, closing, or mid-sermon prayer. The pastor addresses God rather than the congregation. May appear anywhere in the sermon — some pastors pray at transitions, some pray after especially weighty claims. The rhetorical register shifts from horizontal (pastor-to-people) to vertical (pastor-to-God).</td>
      </tr>
    </tbody>
  </table>
</section>

<!-- ═══════ THREE-TIER CITATIONS ═══════ -->
<section id="citations">
  <div class="section-label">07 — Three-Tier Citation Architecture</div>
  <h2 class="section-title">Three Kinds of Citation</h2>
  <p class="section-intro">The spec separates three fundamentally different kinds of cited material — each requiring different retrieval logic. A pastor reading his primary text is not the same act as a pastor quoting Spurgeon, and the data must reflect that distinction.</p>

  <div class="tier-stack">
    <div class="tier-block t1">
      <div class="tier-label">Tier 1 — Primary Text Citations</div>
      <div class="tier-title">The Sermon's Own Passage</div>
      <div class="tier-desc">Verses from the passage being exposited — the scripture the sermon exists to explain. When a pastor preaching on Exodus 5 reads Exodus 5:22-23 aloud, that's a Tier 1 citation. It's source material, not supporting evidence. The text is not being quoted <em>in support</em> of an argument; the text <em>is</em> the argument.</div>
      <div class="tier-fields">
        <span class="field-tag">reference</span>
        <span class="field-tag">mode: full_reading</span>
        <span class="field-tag">mode: partial_reading</span>
        <span class="field-tag">mode: reference_in_passing</span>
      </div>
    </div>
    <div class="tier-block t2">
      <div class="tier-label">Tier 2 — Cross-References</div>
      <div class="tier-title">Scripture from Outside the Passage</div>
      <div class="tier-desc">Other biblical texts brought in for support, contrast, illumination, or typological connection. When a pastor preaching on Exodus 5 quotes Romans 8:28, that's a Tier 2 cross-reference — he's bringing a different part of the canon to bear on his primary text. These reveal the pastor's hermeneutical instincts: which scriptures does he instinctively connect?</div>
      <div class="tier-fields">
        <span class="field-tag">reference</span>
        <span class="field-tag">function: authority</span>
        <span class="field-tag">function: contrast</span>
        <span class="field-tag">function: echo</span>
        <span class="field-tag">function: fulfillment</span>
        <span class="field-tag">function: parallel</span>
        <span class="field-tag">function: corrective</span>
        <span class="field-tag">supports_claim</span>
      </div>
    </div>
    <div class="tier-block t3">
      <div class="tier-label">Tier 3 — Quotations</div>
      <div class="tier-title">Human Authors Only</div>
      <div class="tier-desc">Words from people, not from Scripture — Spurgeon, Piper, Edwards, a hymn writer, a secular author. Tracked with verbatim text, attribution, source work (if identifiable), and the function the quote serves. These reveal the pastor's intellectual influences and rhetorical habits.</div>
      <div class="tier-fields">
        <span class="field-tag">text</span>
        <span class="field-tag">attribution</span>
        <span class="field-tag">source</span>
        <span class="field-tag">function: authority</span>
        <span class="field-tag">function: illustration</span>
        <span class="field-tag">function: provocation</span>
        <span class="field-tag">function: devotional</span>
        <span class="field-tag">function: opponent</span>
      </div>
    </div>
  </div>

  <div class="section-divider"></div>
  <h3 style="font-family: 'Cormorant Garamond', serif; font-size: 1.4rem; font-weight: 500; margin-bottom: 20px;">Cross-Reference Functions</h3>

  <table class="enum-table">
    <thead>
      <tr><th>Value</th><th>Definition</th></tr>
    </thead>
    <tbody>
      <tr>
        <td>authority</td>
        <td>The cross-reference is brought in as proof — "Scripture confirms this point." The pastor cites another passage because it settles the question or lends decisive weight to the claim being made.</td>
      </tr>
      <tr>
        <td>contrast</td>
        <td>The cross-reference shows the difference between two realities — old and new covenant, law and grace, judgment and mercy. The pastor juxtaposes passages to illuminate what makes this text distinctive.</td>
      </tr>
      <tr>
        <td>echo</td>
        <td>A softer connection than authority — the cross-reference resonates with the primary text without directly proving it. Shared imagery, shared vocabulary, a family resemblance between two passages. The canon whispering to itself.</td>
      </tr>
      <tr>
        <td>fulfillment</td>
        <td>The cross-reference shows a promise-fulfillment relationship. An Old Testament prophecy finds its realization in a New Testament event, or a type finds its antitype. The pastor is tracing the arc of redemptive history.</td>
      </tr>
      <tr>
        <td>parallel</td>
        <td>A structural or thematic parallel between two passages — similar situations, similar responses, similar patterns. The pastor draws the comparison to show that what happened in one text illuminates what's happening in another.</td>
      </tr>
      <tr>
        <td>corrective</td>
        <td>The cross-reference is brought in to guard against misreading the primary text. "You might think this passage means X, but Paul clarifies in Romans that it means Y." A pre-emptive hermeneutical correction.</td>
      </tr>
    </tbody>
  </table>

  <div class="section-divider" style="margin-top: 40px;"></div>
  <h3 style="font-family: 'Cormorant Garamond', serif; font-size: 1.4rem; font-weight: 500; margin-bottom: 20px;">Quotation Functions</h3>

  <table class="enum-table">
    <thead>
      <tr><th>Value</th><th>Definition</th></tr>
    </thead>
    <tbody>
      <tr>
        <td>authority</td>
        <td>The quote is cited because the author carries weight — a trusted theologian, a church father, a respected scholar. The pastor borrows credibility: "Calvin himself said..."</td>
      </tr>
      <tr>
        <td>illustration</td>
        <td>The quote serves as an illustration — a vivid way of saying what the pastor is already arguing. Bunyan's Pilgrim's Progress, a memorable phrase from a hymn. The quote illuminates; it doesn't prove.</td>
      </tr>
      <tr>
        <td>provocation</td>
        <td>The quote is cited to provoke a reaction — to shock, to challenge, to disrupt complacency. May come from an ally or an opponent. The rhetorical purpose is to disturb, not to comfort.</td>
      </tr>
      <tr>
        <td>devotional</td>
        <td>The quote is cited for its affective power — to move the heart, not just the mind. Hymn stanzas, poetry, prayers from the tradition. The pastor wants the congregation to <em>feel</em> what the text means, and the quote does that work.</td>
      </tr>
      <tr>
        <td>opponent</td>
        <td>The quote comes from someone the pastor disagrees with — cited in order to be refuted, corrected, or shown to be inadequate. The pastor gives the opponent's view fairly and then dismantles it.</td>
      </tr>
    </tbody>
  </table>
</section>

<!-- ═══════ DOCTRINAL LOCI ═══════ -->
<section id="doctrine">
  <div class="section-label">08 — Doctrinal Loci</div>
  <h2 class="section-title">Sixteen Theological Categories</h2>
  <p class="section-intro">The controlled taxonomy for tagging each unit's theological content. These categories come from the traditional divisions of systematic theology. A single unit can carry multiple tags — a passage on Christ's atonement touches both Christology and Soteriology.</p>

  <table class="enum-table">
    <thead>
      <tr><th>Locus</th><th>Definition</th></tr>
    </thead>
    <tbody>
      <tr>
        <td>Theology Proper</td>
        <td>The doctrine of God himself — his existence, attributes, nature, and works. God's holiness, sovereignty, love, justice, omniscience, aseity (self-existence). When the sermon is primarily about who God is in himself, this is the locus.</td>
      </tr>
      <tr>
        <td>Christology</td>
        <td>The doctrine of Christ — his person (divine and human natures), his offices (prophet, priest, king), his work (incarnation, life, death, resurrection, ascension, return). Any unit centered on who Jesus is or what he has done.</td>
      </tr>
      <tr>
        <td>Pneumatology</td>
        <td>The doctrine of the Holy Spirit — his person, his role in salvation (regeneration, sanctification, sealing), his gifts, his indwelling of believers, his work in the church. Often underrepresented in preaching; the Spirit is frequently assumed rather than exposited.</td>
      </tr>
      <tr>
        <td>Soteriology</td>
        <td>The doctrine of salvation — how sinners are made right with God. Justification, redemption, reconciliation, propitiation, adoption, election, effectual calling, perseverance. The broadest and most frequent locus in evangelical preaching.</td>
      </tr>
      <tr>
        <td>Hamartiology</td>
        <td>The doctrine of sin — its origin, nature, effects, and extent. Original sin, total depravity, the fall, the relationship between sin and death. When the pastor is diagnosing the human problem before presenting the solution.</td>
      </tr>
      <tr>
        <td>Anthropology</td>
        <td>The doctrine of humanity — what it means to be human. Created in God's image, the nature of the soul, human dignity, the fall's effect on human nature, gender and embodiment. Distinct from Hamartiology (which focuses on the sin problem specifically).</td>
      </tr>
      <tr>
        <td>Ecclesiology</td>
        <td>The doctrine of the church — its nature, mission, ordinances (baptism, Lord's Supper), governance, membership, discipline, unity. When the pastor addresses what the church is and how it should function.</td>
      </tr>
      <tr>
        <td>Eschatology</td>
        <td>The doctrine of last things — death, judgment, heaven, hell, the return of Christ, the new creation, the intermediate state. Not just end-times speculation — includes the pastoral urgency that comes from eternal perspective.</td>
      </tr>
      <tr>
        <td>Bibliology</td>
        <td>The doctrine of Scripture — its inspiration, authority, inerrancy, sufficiency, clarity, and role in the Christian life. When the pastor is making claims about the Bible itself rather than just teaching from it.</td>
      </tr>
      <tr>
        <td>Sanctification</td>
        <td>The ongoing process of becoming more like Christ after conversion. Growth in holiness, the role of the Spirit in transformation, the means of grace, the battle against remaining sin. Distinguished from Soteriology's focus on how we <em>become</em> saved — this is about how we <em>grow</em> after being saved.</td>
      </tr>
      <tr>
        <td>Providence / Sovereignty</td>
        <td>God's active governance of all things — his control over history, nations, circumstances, and individual lives. The relationship between God's sovereignty and human responsibility. When the pastor argues that God is in control of a specific situation or circumstance.</td>
      </tr>
      <tr>
        <td>Covenant Theology</td>
        <td>The framework of God's relationship with his people through covenants — Adamic, Noahic, Abrahamic, Mosaic, Davidic, New. The continuity and discontinuity between Old and New Testaments. How the promises of God unfold across redemptive history through covenant commitments.</td>
      </tr>
      <tr>
        <td>Ethics / Moral Theology</td>
        <td>How Christians should live — moral reasoning, ethical principles, the relationship between law and gospel, specific ethical instruction. When the sermon moves from "what is true" to "what is right" — not just application (which is broader) but specifically moral and ethical reasoning.</td>
      </tr>
      <tr>
        <td>Doxology / Worship</td>
        <td>The theology and practice of worship — why we worship, how we worship, the nature of praise, the role of music, the relationship between liturgy and life. Also tagged when the sermon itself breaks into worship — when the pastor's exposition becomes doxology.</td>
      </tr>
      <tr>
        <td>Spiritual Warfare</td>
        <td>The reality and dynamics of spiritual conflict — Satan, demonic opposition, the believer's armor, temptation, the cosmic dimension of the Christian life. When the sermon acknowledges and addresses the unseen adversary and the nature of the battle.</td>
      </tr>
      <tr>
        <td>Pastoral Theology</td>
        <td>The theology of care — how pastors and churches minister to people in suffering, doubt, grief, transition, and crisis. Also covers the nature and calling of pastoral ministry itself. When the sermon functions as an act of shepherding more than teaching.</td>
      </tr>
    </tbody>
  </table>
</section>

<!-- ═══════ BIBLICAL-THEOLOGICAL MOVES ═══════ -->
<section id="bt-moves">
  <div class="section-label">09 — Biblical-Theological Moves</div>
  <h2 class="section-title">Seven Move Types</h2>
  <p class="section-intro">Detected instances of biblical theology at work — moments where the pastor traces connections across the canon, showing how themes develop, types are fulfilled, and the story of redemption unfolds. Each move captures the source text, target text, and the pastor's own framing of the connection.</p>

  <table class="enum-table">
    <thead>
      <tr><th>Move Type</th><th>Definition</th></tr>
    </thead>
    <tbody>
      <tr>
        <td>typology</td>
        <td>An Old Testament person, event, or institution is presented as a "type" — a divinely intended prefiguration — of a New Testament reality. Adam as a type of Christ. The Passover lamb as a type of Christ's sacrifice. The tabernacle as a type of God's presence with his people. The pastor traces the correspondence and says "this earlier thing points forward to this later thing."</td>
      </tr>
      <tr>
        <td>fulfillment</td>
        <td>A direct prophecy-to-fulfillment connection. Isaiah 53 fulfilled in Christ's passion. Jeremiah 31's new covenant fulfilled at the Last Supper. The pastor identifies an explicit Old Testament promise and shows where it landed in history. More specific than typology — this is about verbal predictions, not just structural parallels.</td>
      </tr>
      <tr>
        <td>progressive_revelation</td>
        <td>The same doctrine is shown to develop and deepen across the canon. What was dimly understood in the Old Testament becomes clearer in the New. The pastor traces how God revealed truth in stages — not contradicting earlier revelation, but filling it in. The hardest move for AI models to detect because it requires understanding what was <em>not yet known</em> at each stage.</td>
      </tr>
      <tr>
        <td>narrative_arc</td>
        <td>The pastor connects the passage to the larger story of Scripture — creation, fall, redemption, consummation. The sermon places this text on the map of the grand narrative. "This moment in Exodus is the first step toward what God will ultimately accomplish in Christ." The move is about location in the story, not just theological parallel.</td>
      </tr>
      <tr>
        <td>intertextual_echo</td>
        <td>A subtler connection than typology or fulfillment — shared language, imagery, or themes between two passages that suggest the later author was drawing on the earlier one. When Paul echoes Isaiah's servant language, or when Revelation draws on Exodus imagery. The resonance may be intentional or structural; the pastor surfaces it.</td>
      </tr>
      <tr>
        <td>contrast</td>
        <td>Two canonical moments placed side by side to show how they differ — Adam's disobedience vs. Christ's obedience, the old covenant's conditionality vs. the new covenant's unconditional grace, Moses' veiled face vs. the unveiled glory in Christ. The pastor uses the difference to illuminate the superiority or distinctiveness of one over the other.</td>
      </tr>
      <tr>
        <td>thematic_thread</td>
        <td>A recurring theme traced across multiple books or eras of Scripture — rest, exile, temple, kingdom, wilderness, Promised Land. The pastor shows that this theme appears here, and here, and here, building toward a climactic expression. Less about two specific texts and more about a through-line across the whole canon.</td>
      </tr>
    </tbody>
  </table>

  <div class="term-grid" style="margin-top: 32px;">
    <div class="term-card">
      <div class="term-name">source_text</div>
      <div class="term-category">BT Move Sub-Field</div>
      <div class="term-def">The earlier canonical reference being drawn from — the "from" end of the connection. The Old Testament type, the original prophecy, the first appearance of the theme.</div>
    </div>
    <div class="term-card">
      <div class="term-name">target_text</div>
      <div class="term-category">BT Move Sub-Field</div>
      <div class="term-def">The later canonical reference where the fulfillment, echo, or development lands — the "to" end of the connection. The New Testament antitype, the fulfilled promise, the climactic expression of the theme.</div>
    </div>
    <div class="term-card full-width">
      <div class="term-name">pastor_framing</div>
      <div class="term-category">BT Move Sub-Field</div>
      <div class="term-def">One sentence capturing how the pastor himself articulated the connection — in his specific language. This matters because different pastors frame the same typological move differently, and that framing reveals their hermeneutical instincts. Critical for voice replication and for MIRRORVOX's benchmark analysis.</div>
    </div>
  </div>
</section>

<!-- ═══════ PENDING ADDITIONS ═══════ -->
<section id="pending">
  <div class="pending-banner">
    <div class="section-label">10 — Pending Spec Additions</div>
    <h2 class="section-title" style="font-size: clamp(1.6rem, 3.5vw, 2.2rem);">Fields Not Yet in Production</h2>
    <p class="section-intro">These fields have been identified across multiple product specs as needed additions to the decomposition spec. They are prioritized by how many products depend on them and whether their detection has been validated.</p>

    <div class="pending-grid">
      <div class="pending-card">
        <div class="term-name">illustration_type</div>
        <div class="term-category">Critical Priority — Add Now</div>
        <div class="term-def">Classifies illustration units by source type: <strong>personal_story</strong> (the pastor's own experience), <strong>historical_example</strong> (real events or figures from history), <strong>analogy</strong> (A-is-like-B comparisons), <strong>hypothetical</strong> (imagined scenarios), or <strong>cultural_reference</strong> (books, films, current events). Without this, all illustrations are an undifferentiated bucket.</div>
        <div class="products">
          <span class="product-tag">PastoralRAG</span>
          <span class="product-tag">MirrorVox</span>
          <span class="product-tag">BookGuide</span>
        </div>
      </div>
      <div class="pending-card">
        <div class="term-name">rhetorical_register</div>
        <div class="term-category">High Priority — Test First</div>
        <div class="term-def">Tags the persuasive mode of each unit: <strong>logos</strong> (logical argument), <strong>pathos</strong> (emotional appeal), <strong>ethos</strong> (credibility/authority), <strong>narrative</strong> (story immersion), or <strong>doxological</strong> (worship/praise). Multiple values allowed. Needs reliability testing before production.</div>
        <div class="products">
          <span class="product-tag">TrainingData</span>
          <span class="product-tag">MirrorVox</span>
        </div>
      </div>
      <div class="pending-card">
        <div class="term-name">anticipated_objection</div>
        <div class="term-category">High Priority — Test Frequency</div>
        <div class="term-def">Captures moments where the pastor surfaces and responds to an implicit counter-argument: the <strong>objection_text</strong> (what the objector would say) and <strong>response_strategy</strong> (direct_refutation, reframe, concede_and_pivot, or rhetorical_question). The single most valuable reasoning pattern for TRAININGDATA.</div>
        <div class="products">
          <span class="product-tag">TrainingData</span>
        </div>
      </div>
      <div class="pending-card">
        <div class="term-name">serves_unit</div>
        <div class="term-category">High Priority — Argument Graph</div>
        <div class="term-def">Links units to the other units they serve — turning the flat JSON list into a directed argument graph. Each entry records the <strong>unit_index</strong> being served and the <strong>relationship</strong> (illustrates, supports, rebuts, qualifies, applies, anticipates). Potentially the highest-value addition for training data sales.</div>
        <div class="products">
          <span class="product-tag">TrainingData</span>
        </div>
      </div>
      <div class="pending-card">
        <div class="term-name">application_specificity</div>
        <div class="term-category">Medium Priority</div>
        <div class="term-def">Tags application units by concreteness: <strong>abstract</strong> ("trust God more"), <strong>concrete</strong> ("here are three things to do this week"), or <strong>mixed</strong>. Enables MIRRORVOX to measure whether a pastor tends toward general exhortation or specific instruction.</div>
        <div class="products">
          <span class="product-tag">MirrorVox</span>
        </div>
      </div>
      <div class="pending-card">
        <div class="term-name">hinge_statement</div>
        <div class="term-category">Medium Priority — Needs Expert Input</div>
        <div class="term-def">A boolean on transition units indicating whether the transition contains an explicit structural signal — a clear pivot between major sections. Distinguished from mere connective tissue. Requires clearer homiletical definition before implementation.</div>
        <div class="products">
          <span class="product-tag">MirrorVox</span>
        </div>
      </div>
      <div class="pending-card">
        <div class="term-name">is_fcf_moment</div>
        <div class="term-category">Lower Priority</div>
        <div class="term-def">Boolean + optional description flagging "Fallen Condition Focus" moments — where the pastor identifies the human problem or need the passage addresses. A standard move in Reformed homiletics (the FCF is the question the passage answers). Captures problem-framing before solution-delivery.</div>
        <div class="products">
          <span class="product-tag">TrainingData</span>
        </div>
      </div>
    </div>
  </div>
</section>

</div><!-- end report-body -->

<!-- ═══════ FOOTER ═══════ -->
<div class="report-footer">
  <div class="footer-mark">
    <svg viewBox="0 0 24 24" fill="none" stroke="#c4a265" stroke-width="1.5">
      <path d="M12 2L2 7v10l10 5 10-5V7L12 2z"/>
      <path d="M12 22V12"/>
      <path d="M2 7l10 5 10-5"/>
    </svg>
  </div>
  <div class="footer-brand">Shepherd's Guild</div>
  <div class="footer-text">Decomposition Spec Wiki — v2 Reference</div>
  <div class="footer-text" style="font-size: 0.68rem; opacity: 0.6; margin-top: 4px;">March 2026</div>
</div>

<script>
const observer = new IntersectionObserver((entries) => {
  entries.forEach(entry => {
    if (entry.isIntersecting) entry.target.classList.add('visible');
  });
}, { threshold: 0.1 });

document.querySelectorAll('section').forEach(s => observer.observe(s));
</script>

</body>
</html>

```

---

### Illustration & Quote Database

Preachers receive a PDF file of all illustrations the V3 ingester caught (which should be most of them). Included with the Ingester purchase.

---

### Book Recommendation

As part of the initial Ingester purchase, preachers get a "book topic recommendation" — essentially: "We scanned your sermons, you have 60% of a book on X subject already developed across these sermons." → This became **BOOKGUIDE**.

---

### Annual Subscription

Annual upkeep service where sermons are automatically scraped and processed every week. **~$300/year**, only available for those who purchased the archive ingester.

---

### The Forge (Automated Coaching) → MIRRORVOX

Preachers who have enrolled will have the opportunity to enroll in automated coaching for an additional **$20/month**. Uses the apprenticeship model to analyze sermons (weighted toward most recent), match with 1–2 exemplars, and make practical suggestions about modifying sermon structure. For example, many Hall masters excel at making double application (both to believers and unbelievers) — the V3 tool picks up on this in both presence and absence. A coached client might receive an email on Tuesday:

> "Hi Brad, we've analyzed your most recent sermon and here's the report. We like what you did X, Y, Z... and we noticed you could have done A, B, C. Here's how John Stott did that..."

---

### Social Media Post Generator → OUTREACH

The process of selecting one's own quotes for posting on personal or church Facebook is such a psychologically weird thing. We give the pastor a set of nicely formatted posts every week based on present and past preaching, sortable by theme. Two tiers:

- **You post** = $X/month
- **We post** = $XX/month

---

### Guest Gift Book → BOOKGUIDE

Each preacher should have the ability to give a book of his illustrations and other content to all visitors (and members of his local church). For a fee, we discover ideal material and format a small gift book that the church can send to a self-publishing service. This becomes a very simple and useful "visitor gift" that gives the preacher credibility as a "published author."

---

### Sermon Research → PASTORALRAG

Using proprietary tools, we provide preachers sermon prep resources within 1–3 days of text identification, customized according to his known style and rhetorical approaches. **$1,000/year** annual subscription.

---

## 5. Sales & Lead Generation

Two-tool pipeline for building the church leads database: first scrape church directories, then enrich with pastor/contact details.

---

### scrape_locate_church.py — Directory Scraper

Scrapes church listings from locate.church across 9Marks, Founders Ministries, and TGC networks. Two-pass approach: collect church stubs from paginated list pages, then visit each detail page for enriched data (pastor, email, phone, address, website). Outputs to the SG Church CRM spreadsheet format.

```python
#!/usr/bin/env python3
"""
Shepherd's Guild — Locate.Church Directory Scraper
===================================================
Scrapes church listings from locate.church for 9Marks, Founders Ministries,
and TGC networks. Two-pass approach:
  Pass 1: Collect church stubs from paginated list pages (name, location, networks, detail URL)
  Pass 2: Visit each detail page for enriched data (pastor, email, phone, address, website)

Outputs to the SG Church CRM spreadsheet format.

Usage:
  python scrape_locate_church.py                    # Full scrape, all networks, all pages
  python scrape_locate_church.py --max-pages 3      # Limit to 3 pages per network (test run)
  python scrape_locate_church.py --skip-details      # List pages only, no detail enrichment
  python scrape_locate_church.py --networks 9marks   # Single network only
  python scrape_locate_church.py --resume             # Resume from existing progress file
"""

import argparse
import csv
import json
import os
import re
import sys
import time
import random
import logging
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

# ============================================================
# CONFIG
# ============================================================
BASE_URL = "https://locate.church"
NETWORKS = {
    "9marks": "/networks/9marks",
    "founders": "/networks/founders-ministries",
    "tgc": "/networks/the-gospel-coalition",
}
# Fallback URL patterns (locate.church uses both /networks/ and /denominations/)
NETWORK_FALLBACKS = {
    "9marks": ["/denominations/9marks", "/networks/9-marks"],
    "founders": ["/denominations/founders-ministries", "/networks/founders"],
    "tgc": ["/denominations/the-gospel-coalition", "/networks/gospel-coalition"],
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

DELAY_MIN = 1.5  # seconds between requests
DELAY_MAX = 3.5
DETAIL_DELAY_MIN = 1.0
DETAIL_DELAY_MAX = 2.5
MAX_RETRIES = 3

PROGRESS_FILE = "scrape_progress.json"
OUTPUT_CSV = "locate_church_raw.csv"
OUTPUT_XLSX = "sg-church-crm-populated.xlsx"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("scraper")


# ============================================================
# HTTP
# ============================================================
session = requests.Session()
session.headers.update(HEADERS)


def fetch_page(url, retries=MAX_RETRIES):
    """Fetch a page with retry logic and polite delays."""
    for attempt in range(retries):
        try:
            delay = random.uniform(DELAY_MIN, DELAY_MAX)
            time.sleep(delay)
            resp = session.get(url, timeout=30)
            if resp.status_code == 200:
                return resp.text
            elif resp.status_code == 403:
                log.warning(f"403 Forbidden: {url} (attempt {attempt+1})")
                time.sleep(5 * (attempt + 1))
            elif resp.status_code == 429:
                wait = 30 * (attempt + 1)
                log.warning(f"Rate limited on {url}, waiting {wait}s")
                time.sleep(wait)
            else:
                log.warning(f"HTTP {resp.status_code}: {url}")
                time.sleep(3)
        except requests.RequestException as e:
            log.error(f"Request error: {e} (attempt {attempt+1})")
            time.sleep(5 * (attempt + 1))
    log.error(f"Failed after {retries} attempts: {url}")
    return None


def fetch_detail(url):
    """Fetch a detail page with shorter delays."""
    for attempt in range(MAX_RETRIES):
        try:
            delay = random.uniform(DETAIL_DELAY_MIN, DETAIL_DELAY_MAX)
            time.sleep(delay)
            resp = session.get(url, timeout=30)
            if resp.status_code == 200:
                return resp.text
            elif resp.status_code in (403, 429):
                wait = 10 * (attempt + 1)
                log.warning(f"HTTP {resp.status_code} on detail page, waiting {wait}s")
                time.sleep(wait)
            else:
                log.warning(f"HTTP {resp.status_code}: {url}")
                return None
        except requests.RequestException as e:
            log.error(f"Detail fetch error: {e}")
            time.sleep(5)
    return None


# ============================================================
# PARSING — LIST PAGES
# ============================================================
def parse_list_page(html, network_name):
    """Parse a paginated list page and return church stubs + next page URL."""
    soup = BeautifulSoup(html, "html.parser")
    churches = []

    # Church cards are typically h2 > a links with /churches/ in href
    # Also look for divs/articles containing church info
    church_links = []

    # Method 1: Find all links to /churches/ pages
    for a_tag in soup.find_all("a", href=True):
        href = a_tag.get("href", "")
        if "/churches/" in href and "View Details" not in a_tag.get_text():
            church_links.append(a_tag)

    # Build church entries by finding name links, then scanning siblings for context
    seen_slugs = set()

    # Collect all /churches/ links with their surrounding context
    all_a_tags = soup.find_all("a", href=True)
    church_anchors = []
    for a_tag in all_a_tags:
        href = a_tag.get("href", "")
        if "/churches/" not in href:
            continue
        text = a_tag.get_text(strip=True)
        if not text or text in ("View Details", "LOCATE.CHURCH", ""):
            continue
        if len(text) < 3:
            continue
        slug = href.rstrip("/").split("/")[-1]
        if slug in seen_slugs or not slug:
            continue
        seen_slugs.add(slug)
        church_anchors.append((a_tag, slug, text, href))

    for a_tag, slug, text, href in church_anchors:
        detail_url = urljoin(BASE_URL, href)

        # Walk up to the nearest container that holds this card's info
        parent = a_tag.parent
        card_text = ""
        for _ in range(8):
            if parent is None:
                break
            sibs_text = parent.get_text(separator="\n", strip=True)
            # A good card container has location OR networks but is not the entire page
            if ("📍" in sibs_text or "Networks:" in sibs_text) and len(sibs_text) < 1000:
                card_text = sibs_text
                break
            parent = parent.parent

        if not card_text:
            # Fallback: grab text from parent up to a reasonable depth
            parent = a_tag.parent
            for _ in range(4):
                if parent:
                    card_text = parent.get_text(separator="\n", strip=True)
                    parent = parent.parent
                    if len(card_text) > 30:
                        break

        # Parse location from THIS card's text
        location = ""
        loc_match = re.search(r"📍\s*(.+?)(?:\n|$)", card_text)
        if loc_match:
            location = loc_match.group(1).strip()

        # Parse networks from THIS card's text
        networks_list = []
        net_match = re.search(r"Networks?:\s*(.+?)(?:\n|$)", card_text)
        if net_match:
            raw = net_match.group(1).strip()
            networks_list = [n.strip() for n in raw.split(",") if n.strip()]

        # Parse description
        description = ""
        lines = [l.strip() for l in card_text.split("\n") if l.strip()]
        for line in lines:
            if (line != text and "📍" not in line and "Networks" not in line
                    and "View Details" not in line and len(line) > 20
                    and not line.startswith("Showing")):
                description = line[:200]
                break

        churches.append({
            "name": text,
            "slug": slug,
            "detail_url": detail_url,
            "location_raw": location,
            "networks": networks_list if networks_list else [network_name],
            "description": description,
        })

    # Find next page URL
    next_url = None
    next_link = soup.find("a", string=re.compile(r"Next"))
    if next_link and next_link.get("href"):
        next_url = urljoin(BASE_URL, next_link["href"])

    # Also check for numbered pagination
    if not next_url:
        for a in soup.find_all("a", href=True):
            if "page=" in a.get("href", ""):
                # We'll handle this in the main loop
                pass

    # Get total count if shown
    total = None
    count_match = re.search(r"of\s+([\d,]+)\s+churches", html)
    if count_match:
        total = int(count_match.group(1).replace(",", ""))

    return churches, next_url, total


def parse_location(location_raw):
    """Parse 'City, ST' or 'City ST ZIP' or 'City ST ZIP, ST' into components."""
    city, state, zipcode = "", "", ""
    if not location_raw:
        return city, state, zipcode

    raw = location_raw.strip().rstrip(",")

    # Try pattern: "City ST ZIP"
    m = re.match(r"^(.+?)\s+([A-Z]{2})\s+(\d{5})", raw)
    if m:
        city, state, zipcode = m.group(1).rstrip(","), m.group(2), m.group(3)
        return city, state, zipcode

    # Try pattern: "City, ST"
    m = re.match(r"^(.+?),?\s+([A-Z]{2})$", raw)
    if m:
        city, state = m.group(1).rstrip(","), m.group(2)
        return city, state, zipcode

    # Try pattern with extra state at end: "City ST ZIP, ST"
    m = re.match(r"^(.+?)\s+([A-Z]{2})\s+(\d{5}),?\s*[A-Z]{2}$", raw)
    if m:
        city, state, zipcode = m.group(1).rstrip(","), m.group(2), m.group(3)
        return city, state, zipcode

    # Fallback: just return the raw string as city
    city = raw
    return city, state, zipcode


# ============================================================
# PARSING — DETAIL PAGES
# ============================================================
def parse_detail_page(html):
    """Parse a church detail page for pastor, email, phone, address, website."""
    soup = BeautifulSoup(html, "html.parser")
    data = {
        "pastor": "",
        "email": "",
        "phone": "",
        "address": "",
        "website": "",
    }

    text = soup.get_text(separator="\n", strip=True)

    # Pastor
    pastor_match = re.search(r"Pastor:\s*(.+?)(?:\n|$)", text)
    if pastor_match:
        data["pastor"] = pastor_match.group(1).strip()

    # Email — from mailto links
    email_link = soup.find("a", href=re.compile(r"^mailto:"))
    if email_link:
        data["email"] = email_link["href"].replace("mailto:", "").strip()
    else:
        email_match = re.search(r"Email:\s*(\S+@\S+)", text)
        if email_match:
            data["email"] = email_match.group(1).strip()

    # Phone
    phone_match = re.search(r"Phone:\s*([\d\-\(\)\.\s]+)", text)
    if phone_match:
        data["phone"] = phone_match.group(1).strip()

    # Website — look for http links that aren't locate.church
    for a in soup.find_all("a", href=re.compile(r"^https?://")):
        href = a["href"]
        if "locate.church" not in href and "thegospelcoalition" not in href:
            data["website"] = href
            break

    # Address — the Contact Information section
    # Look for street address patterns
    addr_match = re.search(r"(\d+\s+[\w\s\.]+(?:Street|St|Avenue|Ave|Road|Rd|Drive|Dr|Boulevard|Blvd|Lane|Ln|Way|Circle|Ct|Court|Pike|Highway|Hwy)[\w\s\.]*)", text, re.IGNORECASE)
    if addr_match:
        data["address"] = addr_match.group(1).strip()

    # Networks (detail page may have more accurate info)
    networks = []
    net_match = re.search(r"Networks?:\s*(.+?)(?:\n|$)", text)
    if net_match:
        raw = net_match.group(1).strip()
        networks = [n.strip() for n in raw.split(",") if n.strip()]
    data["networks_detail"] = networks

    return data


# ============================================================
# PROGRESS MANAGEMENT
# ============================================================
def save_progress(churches, completed_networks, current_network, current_page):
    with open(PROGRESS_FILE, "w") as f:
        json.dump({
            "churches": churches,
            "completed_networks": completed_networks,
            "current_network": current_network,
            "current_page": current_page,
            "timestamp": datetime.now().isoformat(),
        }, f)


def load_progress():
    if os.path.exists(PROGRESS_FILE):
        with open(PROGRESS_FILE) as f:
            return json.load(f)
    return None


# ============================================================
# MAIN SCRAPE LOGIC
# ============================================================
def scrape_network(network_name, network_path, max_pages=None):
    """Scrape all pages of a single network. Returns list of church dicts."""
    churches = []
    page = 1
    total_expected = None

    # Try primary URL first
    base_list_url = f"{BASE_URL}{network_path}"
    url = base_list_url

    log.info(f"Starting network: {network_name} — {url}")

    while True:
        if max_pages and page > max_pages:
            log.info(f"Reached max pages ({max_pages}) for {network_name}")
            break

        log.info(f"  Fetching page {page}..." + (f" ({len(churches)} churches so far)" if churches else ""))
        html = fetch_page(url)

        if html is None:
            # Try fallback URLs on first page
            if page == 1 and network_name in NETWORK_FALLBACKS:
                for fallback_path in NETWORK_FALLBACKS[network_name]:
                    fallback_url = f"{BASE_URL}{fallback_path}"
                    log.info(f"  Trying fallback: {fallback_url}")
                    html = fetch_page(fallback_url)
                    if html:
                        base_list_url = fallback_url
                        break
            if html is None:
                log.error(f"  Could not fetch page {page}, stopping network {network_name}")
                break

        page_churches, next_url, total = parse_list_page(html, network_name)

        if total and not total_expected:
            total_expected = total
            log.info(f"  Total churches in {network_name}: {total}")

        if not page_churches:
            log.info(f"  No churches found on page {page}, done with {network_name}")
            break

        churches.extend(page_churches)
        log.info(f"  Page {page}: {len(page_churches)} churches (running total: {len(churches)})")

        # Determine next page URL
        if next_url:
            url = next_url
        else:
            # Try incrementing page parameter
            next_page_url = f"{base_list_url}?page={page + 1}"
            url = next_page_url

        page += 1

        # Safety valve
        if page > 500:
            log.warning("Safety valve: exceeded 500 pages, stopping")
            break

    log.info(f"Finished {network_name}: {len(churches)} churches collected")
    return churches


def deduplicate(all_churches):
    """Merge churches that appear in multiple networks by slug."""
    by_slug = {}
    for church in all_churches:
        slug = church["slug"]
        if slug in by_slug:
            # Merge networks
            existing = by_slug[slug]
            for net in church["networks"]:
                if net not in existing["networks"]:
                    existing["networks"].append(net)
            # Keep longer description
            if len(church.get("description", "")) > len(existing.get("description", "")):
                existing["description"] = church["description"]
        else:
            by_slug[slug] = church.copy()
    return list(by_slug.values())


def enrich_with_details(churches, skip_details=False):
    """Visit each church's detail page to get pastor/email/phone/website."""
    if skip_details:
        log.info("Skipping detail enrichment (--skip-details)")
        return churches

    total = len(churches)
    log.info(f"Enriching {total} churches with detail page data...")

    for i, church in enumerate(churches):
        if i % 50 == 0 and i > 0:
            log.info(f"  Progress: {i}/{total} ({i*100//total}%)")

        url = church.get("detail_url")
        if not url:
            continue

        html = fetch_detail(url)
        if not html:
            continue

        detail = parse_detail_page(html)
        church["pastor"] = detail.get("pastor", "")
        church["email"] = detail.get("email", "")
        church["phone"] = detail.get("phone", "")
        church["address"] = detail.get("address", "")
        church["website"] = detail.get("website", "")

        # Update networks if detail page has better data
        if detail.get("networks_detail"):
            for net in detail["networks_detail"]:
                if net not in church["networks"]:
                    church["networks"].append(net)

    log.info(f"Enrichment complete")
    return churches


# ============================================================
# OUTPUT — CSV (intermediate)
# ============================================================
def write_csv(churches, filepath):
    fieldnames = [
        "name", "slug", "pastor", "email", "phone", "website",
        "location_raw", "city", "state", "zip", "address",
        "networks", "is_9marks", "is_founders", "is_tgc",
        "description", "detail_url",
    ]
    with open(filepath, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for church in churches:
            city, state, zipcode = parse_location(church.get("location_raw", ""))
            nets = church.get("networks", [])
            nets_lower = [n.lower() for n in nets]
            writer.writerow({
                "name": church.get("name", ""),
                "slug": church.get("slug", ""),
                "pastor": church.get("pastor", ""),
                "email": church.get("email", ""),
                "phone": church.get("phone", ""),
                "website": church.get("website", ""),
                "location_raw": church.get("location_raw", ""),
                "city": city,
                "state": state,
                "zip": zipcode,
                "address": church.get("address", ""),
                "networks": ", ".join(nets),
                "is_9marks": "Yes" if any("9marks" in n or "9 marks" in n for n in nets_lower) else "No",
                "is_founders": "Yes" if any("founders" in n for n in nets_lower) else "No",
                "is_tgc": "Yes" if any("gospel coalition" in n or "tgc" in n for n in nets_lower) else "No",
                "description": church.get("description", ""),
                "detail_url": church.get("detail_url", ""),
            })
    log.info(f"CSV written: {filepath} ({len(churches)} rows)")


# ============================================================
# OUTPUT — XLSX (CRM format)
# ============================================================
def write_xlsx(churches, filepath):
    """Write to the SG Church CRM format spreadsheet."""
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    from openpyxl.worksheet.datavalidation import DataValidation
    from openpyxl.utils import get_column_letter

    HEADER_FILL = PatternFill("solid", fgColor="1A1A2E")
    HEADER_FONT = Font(name="Arial", bold=True, color="FFFFFF", size=11)
    BODY_FONT = Font(name="Arial", size=10, color="333333")
    thin_border = Border(
        left=Side(style="thin", color="CCCCCC"),
        right=Side(style="thin", color="CCCCCC"),
        top=Side(style="thin", color="CCCCCC"),
        bottom=Side(style="thin", color="CCCCCC"),
    )

    wb = Workbook()
    ws = wb.active
    ws.title = "Church Leads"
    ws.sheet_properties.tabColor = "1A1A2E"

    headers = [
        "Lead ID", "Church Name", "Senior Pastor", "Pastor Email",
        "Church Email", "Phone", "Website", "City", "State", "ZIP",
        "Denomination", "Est. Congregation Size", "Directory Source(s)",
        "9Marks Listed", "Founders Listed", "TGC Listed",
        "Fiscal Year Model", "Sermon Archive Online?", "Archive Platform",
        "Est. Sermon Count", "Lead Status", "Lead Score",
        "First Contact Date", "Last Contact Date", "Contact Method",
        "Notes", "Next Action", "Next Action Date", "Assigned To",
        "Source URL",
    ]

    for i, h in enumerate(headers, 1):
        cell = ws.cell(row=1, column=i, value=h)
        cell.font = HEADER_FONT
        cell.fill = HEADER_FILL
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = thin_border

    widths = [10, 30, 22, 28, 28, 16, 32, 16, 8, 10, 20, 14, 22,
              12, 12, 10, 16, 14, 18, 14, 16, 10, 14, 14, 14, 32, 24, 14, 14, 36]
    for i, w in enumerate(widths):
        ws.column_dimensions[get_column_letter(i + 1)].width = w

    # Write church data
    for idx, church in enumerate(churches):
        row = idx + 2
        lead_id = f"SG-{idx+1:04d}"

        city, state, zipcode = parse_location(church.get("location_raw", ""))
        nets = church.get("networks", [])
        nets_lower = [n.lower() for n in nets]

        is_9m = "Yes" if any("9marks" in n or "9 marks" in n for n in nets_lower) else "No"
        is_fn = "Yes" if any("founders" in n for n in nets_lower) else "No"
        is_tgc = "Yes" if any("gospel coalition" in n or "tgc" in n for n in nets_lower) else "No"

        # Calculate lead score
        score = 0
        directory_count = sum(1 for x in [is_9m, is_fn, is_tgc] if x == "Yes")
        if directory_count >= 2:
            score += 3
        elif directory_count == 1:
            score += 1

        row_data = [
            lead_id,
            church.get("name", ""),
            church.get("pastor", ""),
            church.get("email", ""),
            "",  # Church Email (separate from pastor email)
            church.get("phone", ""),
            church.get("website", ""),
            city,
            state,
            zipcode,
            "",  # Denomination (to be enriched)
            "",  # Est. Congregation Size
            ", ".join(nets),
            is_9m,
            is_fn,
            is_tgc,
            "",  # Fiscal Year Model
            "",  # Sermon Archive Online?
            "",  # Archive Platform
            "",  # Est. Sermon Count
            "New",  # Lead Status
            score if score > 0 else "",
            "",  # First Contact Date
            "",  # Last Contact Date
            "",  # Contact Method
            church.get("description", ""),
            "",  # Next Action
            "",  # Next Action Date
            "",  # Assigned To
            church.get("detail_url", ""),
        ]

        for c, val in enumerate(row_data, 1):
            cell = ws.cell(row=row, column=c, value=val)
            cell.font = BODY_FONT
            cell.alignment = Alignment(vertical="top", wrap_text=True)
            cell.border = thin_border

    # Data validations (only if we have data rows)
    max_row = max(len(churches) + 1, 2)
    dv_status = DataValidation(type="list", formula1='"New,Research,Contacted,Warm,Qualified,Proposal Sent,Won,Lost,Nurture"')
    ws.add_data_validation(dv_status)
    dv_status.add(f"U2:U{max_row}")

    dv_fiscal = DataValidation(type="list", formula1='"Calendar (Jan-Dec),Ministry (Sep-Aug),Unknown,Other"')
    ws.add_data_validation(dv_fiscal)
    dv_fiscal.add(f"Q2:Q{max_row}")

    for col_range in ["N", "O", "P", "R"]:
        dv = DataValidation(type="list", formula1='"Yes,No,Unknown"')
        ws.add_data_validation(dv)
        dv.add(f"{col_range}2:{col_range}{max_row}")

    ws.freeze_panes = "C2"
    ws.auto_filter.ref = f"A1:{get_column_letter(len(headers))}{max_row}"

    # --- Summary sheet ---
    ws2 = wb.create_sheet("Scrape Summary")
    ws2.sheet_properties.tabColor = "C5A55A"
    summary = [
        ["Shepherd's Guild — Locate.Church Scrape Results"],
        [f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}"],
        [""],
        ["Metric", "Value"],
        ["Total churches (deduplicated)", len(churches)],
        ["Churches on 9Marks", sum(1 for c in churches if any("9marks" in n.lower() or "9 marks" in n.lower() for n in c.get("networks", [])))],
        ["Churches on Founders", sum(1 for c in churches if any("founders" in n.lower() for n in c.get("networks", [])))],
        ["Churches on TGC", sum(1 for c in churches if any("gospel coalition" in n.lower() or "tgc" in n.lower() for n in c.get("networks", [])))],
        ["Multi-directory (2+)", sum(1 for c in churches if sum(1 for check in [
            any("9marks" in n.lower() or "9 marks" in n.lower() for n in c.get("networks", [])),
            any("founders" in n.lower() for n in c.get("networks", [])),
            any("gospel coalition" in n.lower() or "tgc" in n.lower() for n in c.get("networks", [])),
        ] if check) >= 2)],
        ["With pastor name", sum(1 for c in churches if c.get("pastor"))],
        ["With email", sum(1 for c in churches if c.get("email"))],
        ["With phone", sum(1 for c in churches if c.get("phone"))],
        ["With website", sum(1 for c in churches if c.get("website"))],
    ]
    for r, row_data in enumerate(summary, 1):
        for c, val in enumerate(row_data, 1):
            cell = ws2.cell(row=r, column=c, value=val)
            cell.font = BODY_FONT
    ws2["A1"].font = Font(name="Arial", bold=True, size=14, color="1A1A2E")
    ws2.merge_cells("A1:B1")
    ws2["A4"].font = Font(name="Arial", bold=True, size=10)
    ws2["B4"].font = Font(name="Arial", bold=True, size=10)
    ws2.column_dimensions["A"].width = 30
    ws2.column_dimensions["B"].width = 20

    wb.save(filepath)
    log.info(f"XLSX written: {filepath} ({len(churches)} rows)")


# ============================================================
# MAIN
# ============================================================
def main():
    parser = argparse.ArgumentParser(description="Scrape Locate.Church directories for SG CRM")
    parser.add_argument("--max-pages", type=int, default=None, help="Max pages per network (default: all)")
    parser.add_argument("--skip-details", action="store_true", help="Skip detail page enrichment")
    parser.add_argument("--networks", nargs="+", choices=["9marks", "founders", "tgc"], default=["9marks", "founders", "tgc"])
    parser.add_argument("--resume", action="store_true", help="Resume from progress file")
    parser.add_argument("--output-dir", default=".", help="Output directory")
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    all_churches = []
    completed_networks = []

    # Resume support
    if args.resume:
        progress = load_progress()
        if progress:
            all_churches = progress.get("churches", [])
            completed_networks = progress.get("completed_networks", [])
            log.info(f"Resumed with {len(all_churches)} churches from {len(completed_networks)} networks")

    # Scrape each network
    for net_name in args.networks:
        if net_name in completed_networks:
            log.info(f"Skipping {net_name} (already completed)")
            continue

        net_path = NETWORKS[net_name]
        churches = scrape_network(net_name, net_path, max_pages=args.max_pages)
        all_churches.extend(churches)
        completed_networks.append(net_name)

        # Save progress after each network
        save_progress(all_churches, completed_networks, net_name, -1)

    # Deduplicate
    log.info(f"Total raw: {len(all_churches)} churches")
    deduped = deduplicate(all_churches)
    log.info(f"After dedup: {len(deduped)} unique churches")

    # Enrich with detail pages
    deduped = enrich_with_details(deduped, skip_details=args.skip_details)

    # Write outputs
    csv_path = str(output_dir / OUTPUT_CSV)
    xlsx_path = str(output_dir / OUTPUT_XLSX)

    write_csv(deduped, csv_path)
    write_xlsx(deduped, xlsx_path)

    # Print summary
    print("\n" + "=" * 60)
    print("SCRAPE COMPLETE")
    print("=" * 60)
    print(f"Total unique churches: {len(deduped)}")

    nets_9m = sum(1 for c in deduped if any("9marks" in n.lower() or "9 marks" in n.lower() for n in c.get("networks", [])))
    nets_fn = sum(1 for c in deduped if any("founders" in n.lower() for n in c.get("networks", [])))
    nets_tgc = sum(1 for c in deduped if any("gospel coalition" in n.lower() or "tgc" in n.lower() for n in c.get("networks", [])))
    multi = sum(1 for c in deduped if sum(1 for check in [
        any("9marks" in n.lower() or "9 marks" in n.lower() for n in c.get("networks", [])),
        any("founders" in n.lower() for n in c.get("networks", [])),
        any("gospel coalition" in n.lower() or "tgc" in n.lower() for n in c.get("networks", [])),
    ] if check) >= 2)

    print(f"  9Marks: {nets_9m}")
    print(f"  Founders: {nets_fn}")
    print(f"  TGC: {nets_tgc}")
    print(f"  Multi-directory (2+): {multi}")
    with_pastor = sum(1 for c in deduped if c.get("pastor"))
    with_email = sum(1 for c in deduped if c.get("email"))
    print(f"  With pastor name: {with_pastor}")
    print(f"  With email: {with_email}")
    print(f"\nOutputs:")
    print(f"  CSV: {csv_path}")
    print(f"  XLSX: {xlsx_path}")
    print("=" * 60)

    # Cleanup progress file
    if os.path.exists(PROGRESS_FILE):
        os.remove(PROGRESS_FILE)


if __name__ == "__main__":
    main()
```

#### Commands for Church Scraper & Enrichment

# ============================================================
# INITIAL SCRAPE (scrape_locate_church.py)
# ============================================================

# Full pull, all 3 networks, no detail enrichment (~15-20 min)
python3 ~/shepherds-guild/pipeline/scrape_locate_church.py --skip-details

# Full pull, all 3 networks, WITH detail enrichment (~4-6 hours)
python3 ~/shepherds-guild/pipeline/scrape_locate_church.py

# Single network only
python3 ~/shepherds-guild/pipeline/scrape_locate_church.py --networks 9marks --skip-details
python3 ~/shepherds-guild/pipeline/scrape_locate_church.py --networks founders --skip-details
python3 ~/shepherds-guild/pipeline/scrape_locate_church.py --networks tgc --skip-details

# Two networks
python3 ~/shepherds-guild/pipeline/scrape_locate_church.py --networks 9marks founders --skip-details

# Test run (N pages per network)
python3 ~/shepherds-guild/pipeline/scrape_locate_church.py --max-pages 5 --networks 9marks --skip-details

# Resume after interruption (picks up where it left off)
python3 ~/shepherds-guild/pipeline/scrape_locate_church.py --resume --skip-details

# ============================================================
# ENRICHMENT (enrich_leads.py)
# ============================================================

# Enrich multi-directory churches only (176 churches, ~10 min)
python3 ~/shepherds-guild/pipeline/enrich_leads.py

# Enrich ALL 3,409 churches (~4-6 hours)
python3 ~/shepherds-guild/pipeline/enrich_leads.py --all

# Enrich any church on at least 1 directory (same as --all for this dataset)
python3 ~/shepherds-guild/pipeline/enrich_leads.py --min-score 1

# Point to a specific input CSV
python3 ~/shepherds-guild/pipeline/enrich_leads.py --input ~/shepherds-guild/data/locate_church_raw.csv

# Resume enrichment after interruption
python3 ~/shepherds-guild/pipeline/enrich_leads.py --resume

---

### enrich_leads.py — Detail Enrichment

Reads the raw CSV from the initial scrape, filters to multi-directory churches (listed on 2+ of 9Marks/Founders/TGC), fetches each church's detail page for pastor/email/phone/website, and writes enriched outputs as both CSV and a formatted XLSX CRM spreadsheet.

```python
#!/usr/bin/env python3
"""
Shepherd's Guild — Detail Enrichment Pass
==========================================
Reads the locate_church_raw.csv from the initial scrape, filters to
multi-directory churches (listed on 2+ of 9Marks/Founders/TGC), fetches
each church's detail page for pastor/email/phone/website, and writes
enriched outputs.

Usage:
  python3 enrich_leads.py                          # Enrich multi-directory only (default)
  python3 enrich_leads.py --all                     # Enrich ALL churches (slow)
  python3 enrich_leads.py --input path/to/raw.csv   # Custom input path
  python3 enrich_leads.py --min-score 1             # Enrich any church with score >= 1
"""

import argparse
import csv
import json
import os
import re
import random
import time
import logging
from datetime import datetime
from pathlib import Path

import requests
from bs4 import BeautifulSoup
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.worksheet.datavalidation import DataValidation
from openpyxl.utils import get_column_letter

# ============================================================
# CONFIG
# ============================================================
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}
DELAY_MIN = 1.0
DELAY_MAX = 2.5
MAX_RETRIES = 3

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("enricher")

session = requests.Session()
session.headers.update(HEADERS)

PROGRESS_FILE = "enrich_progress.json"


# ============================================================
# FETCH + PARSE
# ============================================================
def fetch_detail(url):
    for attempt in range(MAX_RETRIES):
        try:
            time.sleep(random.uniform(DELAY_MIN, DELAY_MAX))
            resp = session.get(url, timeout=30)
            if resp.status_code == 200:
                return resp.text
            elif resp.status_code in (403, 429):
                wait = 10 * (attempt + 1)
                log.warning(f"HTTP {resp.status_code}, waiting {wait}s — {url}")
                time.sleep(wait)
            else:
                log.warning(f"HTTP {resp.status_code}: {url}")
                return None
        except requests.RequestException as e:
            log.error(f"Error: {e} (attempt {attempt+1})")
            time.sleep(5)
    return None


def parse_detail(html):
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text(separator="\n", strip=True)
    data = {"pastor": "", "email": "", "phone": "", "address": "", "website": ""}

    # Pastor
    m = re.search(r"Pastor:\s*(.+?)(?:\n|$)", text)
    if m:
        data["pastor"] = m.group(1).strip()

    # Email
    email_link = soup.find("a", href=re.compile(r"^mailto:"))
    if email_link:
        data["email"] = email_link["href"].replace("mailto:", "").strip()
    else:
        m = re.search(r"Email:\s*(\S+@\S+)", text)
        if m:
            data["email"] = m.group(1).strip()

    # Phone
    m = re.search(r"Phone:\s*([\d\-\(\)\.\s]+)", text)
    if m:
        data["phone"] = m.group(1).strip()

    # Website
    for a in soup.find_all("a", href=re.compile(r"^https?://")):
        href = a["href"]
        if "locate.church" not in href and "thegospelcoalition" not in href:
            data["website"] = href
            break

    # Address
    m = re.search(
        r"(\d+\s+[\w\s\.]+(?:Street|St|Avenue|Ave|Road|Rd|Drive|Dr|Boulevard|Blvd|Lane|Ln|Way|Circle|Ct|Court|Pike|Highway|Hwy)[\w\s\.]*)",
        text, re.IGNORECASE,
    )
    if m:
        data["address"] = m.group(1).strip()

    return data


# ============================================================
# PROGRESS
# ============================================================
def save_progress(enriched, remaining_slugs):
    with open(PROGRESS_FILE, "w") as f:
        json.dump({
            "enriched": enriched,
            "remaining": remaining_slugs,
            "timestamp": datetime.now().isoformat(),
        }, f)


def load_progress():
    if os.path.exists(PROGRESS_FILE):
        with open(PROGRESS_FILE) as f:
            return json.load(f)
    return None


# ============================================================
# READ CSV
# ============================================================
def read_csv(filepath):
    churches = []
    with open(filepath, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            churches.append(row)
    return churches


def is_multi_directory(row):
    flags = [
        row.get("is_9marks", "").strip().lower() == "yes",
        row.get("is_founders", "").strip().lower() == "yes",
        row.get("is_tgc", "").strip().lower() == "yes",
    ]
    return sum(flags) >= 2


def directory_count(row):
    flags = [
        row.get("is_9marks", "").strip().lower() == "yes",
        row.get("is_founders", "").strip().lower() == "yes",
        row.get("is_tgc", "").strip().lower() == "yes",
    ]
    return sum(flags)


# ============================================================
# XLSX OUTPUT
# ============================================================
def write_enriched_xlsx(churches, filepath):
    HEADER_FILL = PatternFill("solid", fgColor="1A1A2E")
    HEADER_FONT = Font(name="Arial", bold=True, color="FFFFFF", size=11)
    BODY_FONT = Font(name="Arial", size=10, color="333333")
    GOLD_FILL = PatternFill("solid", fgColor="FFF8E1")
    thin_border = Border(
        left=Side(style="thin", color="CCCCCC"),
        right=Side(style="thin", color="CCCCCC"),
        top=Side(style="thin", color="CCCCCC"),
        bottom=Side(style="thin", color="CCCCCC"),
    )

    wb = Workbook()
    ws = wb.active
    ws.title = "Church Leads"
    ws.sheet_properties.tabColor = "1A1A2E"

    headers = [
        "Lead ID", "Church Name", "Senior Pastor", "Pastor Email",
        "Church Email", "Phone", "Website", "City", "State", "ZIP",
        "Denomination", "Est. Congregation Size", "Directory Source(s)",
        "9Marks Listed", "Founders Listed", "TGC Listed",
        "Fiscal Year Model", "Sermon Archive Online?", "Archive Platform",
        "Est. Sermon Count", "Lead Status", "Lead Score",
        "First Contact Date", "Last Contact Date", "Contact Method",
        "Notes", "Next Action", "Next Action Date", "Assigned To",
        "Source URL",
    ]

    for i, h in enumerate(headers, 1):
        cell = ws.cell(row=1, column=i, value=h)
        cell.font = HEADER_FONT
        cell.fill = HEADER_FILL
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = thin_border

    widths = [10, 30, 22, 28, 28, 16, 32, 16, 8, 10, 20, 14, 22,
              12, 12, 10, 16, 14, 18, 14, 16, 10, 14, 14, 14, 32, 24, 14, 14, 36]
    for i, w in enumerate(widths):
        ws.column_dimensions[get_column_letter(i + 1)].width = w

    # Sort: multi-directory first, then by directory count desc
    churches.sort(key=lambda c: directory_count(c), reverse=True)

    for idx, church in enumerate(churches):
        row = idx + 2
        lead_id = f"SG-{idx+1:04d}"

        dc = directory_count(church)
        score = 3 if dc >= 2 else (1 if dc == 1 else 0)

        is_9m = church.get("is_9marks", "No")
        is_fn = church.get("is_founders", "No")
        is_tgc = church.get("is_tgc", "No")

        row_data = [
            lead_id,
            church.get("name", ""),
            church.get("pastor", ""),
            church.get("email", ""),
            "",  # Church Email
            church.get("phone", ""),
            church.get("website", ""),
            church.get("city", ""),
            church.get("state", ""),
            church.get("zip", ""),
            "",  # Denomination
            "",  # Est. Congregation Size
            church.get("networks", ""),
            is_9m,
            is_fn,
            is_tgc,
            "",  # Fiscal Year Model
            "",  # Sermon Archive Online?
            "",  # Archive Platform
            "",  # Est. Sermon Count
            "Research" if dc >= 2 else "New",
            score if score > 0 else "",
            "",  # First Contact Date
            "",  # Last Contact Date
            "",  # Contact Method
            church.get("description", ""),
            "Verify pastor email" if church.get("email") else "Research contact info",
            "",  # Next Action Date
            "",  # Assigned To
            church.get("detail_url", ""),
        ]

        for c, val in enumerate(row_data, 1):
            cell = ws.cell(row=row, column=c, value=val)
            cell.font = BODY_FONT
            cell.alignment = Alignment(vertical="top", wrap_text=True)
            cell.border = thin_border
            # Highlight multi-directory rows
            if dc >= 2:
                cell.fill = GOLD_FILL

    max_row = max(len(churches) + 1, 2)

    dv_status = DataValidation(type="list", formula1='"New,Research,Contacted,Warm,Qualified,Proposal Sent,Won,Lost,Nurture"')
    ws.add_data_validation(dv_status)
    dv_status.add(f"U2:U{max_row}")

    dv_fiscal = DataValidation(type="list", formula1='"Calendar (Jan-Dec),Ministry (Sep-Aug),Unknown,Other"')
    ws.add_data_validation(dv_fiscal)
    dv_fiscal.add(f"Q2:Q{max_row}")

    for col_range in ["N", "O", "P", "R"]:
        dv = DataValidation(type="list", formula1='"Yes,No,Unknown"')
        ws.add_data_validation(dv)
        dv.add(f"{col_range}2:{col_range}{max_row}")

    ws.freeze_panes = "C2"
    ws.auto_filter.ref = f"A1:{get_column_letter(len(headers))}{max_row}"

    # --- Summary sheet ---
    ws2 = wb.create_sheet("Enrichment Summary")
    ws2.sheet_properties.tabColor = "C5A55A"

    enriched_count = sum(1 for c in churches if c.get("pastor") or c.get("email"))
    multi_count = sum(1 for c in churches if directory_count(c) >= 2)

    summary = [
        ["Shepherd's Guild — Enriched Lead List"],
        [f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}"],
        [""],
        ["Metric", "Value"],
        ["Total churches", len(churches)],
        ["Multi-directory (2+)", multi_count],
        ["With pastor name", sum(1 for c in churches if c.get("pastor"))],
        ["With email", sum(1 for c in churches if c.get("email"))],
        ["With phone", sum(1 for c in churches if c.get("phone"))],
        ["With website", sum(1 for c in churches if c.get("website"))],
        ["Enrichment rate", f"{enriched_count}/{len(churches)} ({enriched_count*100//max(len(churches),1)}%)"],
    ]
    for r, row_data in enumerate(summary, 1):
        for c, val in enumerate(row_data, 1):
            ws2.cell(row=r, column=c, value=val).font = Font(name="Arial", size=10)
    ws2["A1"].font = Font(name="Arial", bold=True, size=14, color="1A1A2E")
    ws2.merge_cells("A1:B1")
    ws2["A4"].font = Font(name="Arial", bold=True, size=10)
    ws2["B4"].font = Font(name="Arial", bold=True, size=10)
    ws2.column_dimensions["A"].width = 30
    ws2.column_dimensions["B"].width = 20

    wb.save(filepath)
    log.info(f"XLSX written: {filepath} ({len(churches)} rows, {multi_count} multi-directory)")


# ============================================================
# MAIN
# ============================================================
def main():
    parser = argparse.ArgumentParser(description="Enrich Locate.Church leads with detail page data")
    parser.add_argument("--input", default="locate_church_raw.csv", help="Path to raw CSV from initial scrape")
    parser.add_argument("--all", action="store_true", help="Enrich ALL churches, not just multi-directory")
    parser.add_argument("--min-score", type=int, default=None, help="Enrich churches with directory count >= this")
    parser.add_argument("--resume", action="store_true", help="Resume from progress file")
    parser.add_argument("--output-dir", default=".", help="Output directory")
    args = parser.parse_args()

    output_dir = Path(args.output_dir)

    # Read the raw CSV
    if not os.path.exists(args.input):
        log.error(f"Input file not found: {args.input}")
        log.info("Run the initial scrape first: python3 scrape_locate_church.py --skip-details")
        sys.exit(1)

    import sys
    churches = read_csv(args.input)
    log.info(f"Loaded {len(churches)} churches from {args.input}")

    # Determine which churches to enrich
    if args.all:
        to_enrich = churches
        log.info(f"Enriching ALL {len(to_enrich)} churches")
    elif args.min_score is not None:
        to_enrich = [c for c in churches if directory_count(c) >= args.min_score]
        log.info(f"Enriching {len(to_enrich)} churches with {args.min_score}+ directory listings")
    else:
        to_enrich = [c for c in churches if is_multi_directory(c)]
        log.info(f"Enriching {len(to_enrich)} multi-directory churches")

    not_enriching = [c for c in churches if c not in to_enrich]

    # Resume support
    already_done = {}
    if args.resume:
        progress = load_progress()
        if progress and progress.get("enriched"):
            already_done = {e["slug"]: e for e in progress["enriched"]}
            log.info(f"Resumed with {len(already_done)} already-enriched churches")

    # Enrich
    enriched = []
    total = len(to_enrich)
    for i, church in enumerate(to_enrich):
        slug = church.get("slug", "")

        # Skip if already done (resume)
        if slug in already_done:
            church.update(already_done[slug])
            enriched.append(church)
            continue

        detail_url = church.get("detail_url", "")
        if not detail_url:
            enriched.append(church)
            continue

        if i % 25 == 0:
            log.info(f"Progress: {i}/{total} ({i*100//max(total,1)}%)")

        html = fetch_detail(detail_url)
        if html:
            detail = parse_detail(html)
            church["pastor"] = detail.get("pastor", "")
            church["email"] = detail.get("email", "")
            church["phone"] = detail.get("phone", "")
            church["address"] = detail.get("address", "")
            if detail.get("website"):
                church["website"] = detail["website"]

        enriched.append(church)

        # Save progress every 50 churches
        if i > 0 and i % 50 == 0:
            remaining = [c.get("slug", "") for c in to_enrich[i+1:]]
            save_progress(enriched, remaining)

    log.info(f"Enrichment complete: {len(enriched)} churches processed")

    # Combine enriched + non-enriched
    all_churches = enriched + not_enriching

    # Write outputs
    csv_path = str(output_dir / "sg_enriched_leads.csv")
    xlsx_path = str(output_dir / "sg-church-crm-enriched.xlsx")

    # Write enriched CSV
    fieldnames = list(all_churches[0].keys()) if all_churches else []
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(all_churches)
    log.info(f"CSV written: {csv_path}")

    # Write enriched XLSX
    write_enriched_xlsx(all_churches, xlsx_path)

    # Summary
    with_pastor = sum(1 for c in enriched if c.get("pastor"))
    with_email = sum(1 for c in enriched if c.get("email"))
    with_phone = sum(1 for c in enriched if c.get("phone"))
    multi = sum(1 for c in enriched if is_multi_directory(c))

    print("\n" + "=" * 60)
    print("ENRICHMENT COMPLETE")
    print("=" * 60)
    print(f"Churches enriched: {len(enriched)}")
    print(f"  Multi-directory: {multi}")
    print(f"  With pastor name: {with_pastor}")
    print(f"  With email: {with_email}")
    print(f"  With phone: {with_phone}")
    print(f"Total churches in output: {len(all_churches)}")
    print(f"\nOutputs:")
    print(f"  CSV:  {csv_path}")
    print(f"  XLSX: {xlsx_path}")
    print("=" * 60)

    # Cleanup
    if os.path.exists(PROGRESS_FILE):
        os.remove(PROGRESS_FILE)


if __name__ == "__main__":
    main()
```

---

## Appendix: Key Technical Decisions

- **Controlled taxonomy is the core IP.** Uncontrolled taxonomy drift makes data unsearchable at scale. The decomp spec's controlled enums (rhetorical function, doctrinal loci, BT move types, etc.) are what differentiate Shepherd's Guild from commodity transcripts.
- **No "out" in the prompt.** Giving the model a confidence-scoring escape hatch induces more failures. Fix ambiguous classifications with hard rules and tiebreaker logic inside the prompt; triage/flagging logic belongs exclusively in post-processing pipeline code.
- **Quality over cost optimization.** Processing cost per sermon is a fraction of sale price — gross margins are very high. Preserving decomp quality matters more than reducing API costs.
- **Single-pass architecture confirmed.** Output tokens dominate cost; two-pass offers no meaningful advantage.
- **Stewardship reframe.** The most psychologically and theologically sound way to overcome pastor resistance to self-promotion. Shepherd's Guild sees the value in the archive so the pastor doesn't have to advocate for himself — guilt dissolves when the archive is framed as belonging to the ministry and future generations.

---

*This document is a self-contained snapshot of the Shepherd's Guild vision, infrastructure, and codebase as of March 2026.*
