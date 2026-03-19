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
