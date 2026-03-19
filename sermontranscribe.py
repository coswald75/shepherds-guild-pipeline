"""
Shepherd's Guild — Sermon Transcription Pipeline
=================================================
sermontranscribe.py

Accepts sermon audio from three intake paths:
  1. RSS/podcast feed URL  →  auto-discovers episodes, downloads audio
  2. CSV of direct audio URLs  →  downloads each file
  3. Local directory of audio files  →  processes in place

All paths converge at Whisper GPU transcription and output clean .txt
transcripts with .meta.json sidecar files, ready for the decomp pipeline.

SETUP (one time):
    pip install openai-whisper torch requests feedparser --break-system-packages

    For NVIDIA GPU acceleration (highly recommended):
    pip install torch --index-url https://download.pytorch.org/whl/cu121 --break-system-packages

USAGE:

    # From a podcast RSS feed (auto-discovers all episodes):
    python sermontranscribe.py rss "https://feeds.example.com/sermons" --preacher "Mark Dever" --output ./transcripts

    # From a podcast RSS feed (limit to 30 most recent):
    python sermontranscribe.py rss "https://feeds.example.com/sermons" --preacher "Mark Dever" --limit 30

    # From a CSV of direct audio URLs:
    python sermontranscribe.py csv sermons.csv --output ./transcripts

    # From a local folder of MP3s:
    python sermontranscribe.py local ./audio_files --preacher "Tony Evans" --output ./transcripts

    # Use a smaller model if VRAM is limited:
    python sermontranscribe.py rss "https://feed.url" --preacher "Name" --model medium

CSV FORMAT:
    preacher,title,primary_text,date,series_name,audio_url
    "Mark Dever","The Whole Message","Genesis 1-3","2024-01-07","","https://example.com/sermon.mp3"

    Only 'audio_url' is required. All other columns are optional metadata.
"""

import argparse
import csv
import json
import os
import re
import sys
import time
from pathlib import Path
from datetime import datetime

import requests

# ── Optional imports (deferred for clean error messages) ──
try:
    import whisper
    WHISPER_OK = True
except ImportError:
    WHISPER_OK = False

try:
    import feedparser
    FEEDPARSER_OK = True
except ImportError:
    FEEDPARSER_OK = False

try:
    import torch
    GPU_AVAILABLE = torch.cuda.is_available()
    GPU_NAME = torch.cuda.get_device_name(0) if GPU_AVAILABLE else None
    GPU_VRAM = torch.cuda.get_device_properties(0).total_mem / (1024 ** 3) if GPU_AVAILABLE else 0
except ImportError:
    GPU_AVAILABLE = False
    GPU_NAME = None
    GPU_VRAM = 0


# ══════════════════════════════════════════════════════════════════════
# Constants
# ══════════════════════════════════════════════════════════════════════

AUDIO_EXTENSIONS = {".mp3", ".m4a", ".wav", ".ogg", ".flac", ".webm", ".mp4", ".aac"}
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
DOWNLOAD_TIMEOUT = 600  # 10 minutes per file (sermons can be large)
MAX_RETRIES = 3

VRAM_REQUIREMENTS = {
    "tiny": 1, "base": 1, "small": 2, "medium": 5,
    "large-v2": 10, "large-v3": 10, "large": 10,
}


# ══════════════════════════════════════════════════════════════════════
# Utilities
# ══════════════════════════════════════════════════════════════════════

def slugify(text):
    """Filesystem-safe slug from text."""
    text = text.lower().strip()
    text = re.sub(r'[^\w\s-]', '', text)
    text = re.sub(r'[\s_]+', '-', text)
    text = re.sub(r'-+', '-', text).strip('-')
    return text[:80]


def fmt_duration(seconds):
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    return f"{h}h {m}m {s}s" if h else f"{m}m {s}s"


def fmt_size(bytes):
    mb = bytes / (1024 * 1024)
    return f"{mb:.1f} MB"


def detect_extension(url, headers=None):
    """Guess audio extension from URL or response headers."""
    url_clean = url.split("?")[0].split("#")[0].lower()
    for ext in AUDIO_EXTENSIONS:
        if url_clean.endswith(ext):
            return ext
    if headers:
        ct = headers.get("content-type", "").lower()
        mime_map = {
            "audio/mpeg": ".mp3", "audio/mp3": ".mp3", "audio/mp4": ".m4a",
            "audio/x-m4a": ".m4a", "audio/wav": ".wav", "audio/ogg": ".ogg",
            "audio/flac": ".flac", "audio/aac": ".aac", "audio/webm": ".webm",
        }
        for mime, ext in mime_map.items():
            if mime in ct:
                return ext
    return ".mp3"


# ══════════════════════════════════════════════════════════════════════
# Intake: RSS Feed
# ══════════════════════════════════════════════════════════════════════

def intake_rss(feed_url, preacher, limit=None):
    """Parse RSS/podcast feed and return sermon metadata list."""
    if not FEEDPARSER_OK:
        print("ERROR: feedparser not installed. Run: pip install feedparser")
        sys.exit(1)

    print(f"  Parsing RSS feed: {feed_url}")
    feed = feedparser.parse(feed_url)

    if feed.bozo and not feed.entries:
        print(f"  ERROR: Could not parse feed — {feed.bozo_exception}")
        sys.exit(1)

    print(f"  Feed: {feed.feed.get('title', 'Unknown')}")
    print(f"  Episodes found: {len(feed.entries)}")

    sermons = []
    for entry in feed.entries:
        # Find audio enclosure
        audio_url = None
        for link in entry.get("links", []):
            if link.get("type", "").startswith("audio/") or link.get("rel") == "enclosure":
                audio_url = link.get("href")
                break
        # Also check enclosures directly
        if not audio_url:
            for enc in entry.get("enclosures", []):
                if enc.get("type", "").startswith("audio/"):
                    audio_url = enc.get("href")
                    break

        if not audio_url:
            continue

        # Extract metadata
        title = entry.get("title", "Untitled").strip()
        date = ""
        if entry.get("published_parsed"):
            try:
                date = time.strftime("%Y-%m-%d", entry.published_parsed)
            except:
                pass

        # Some podcast feeds include scripture ref or series in itunes tags
        summary = entry.get("summary", "")
        series = entry.get("itunes_season", "") or ""

        sermons.append({
            "preacher": preacher,
            "title": title,
            "primary_text": "",  # Not reliably in RSS — will need manual or decomp detection
            "date": date,
            "series_name": series,
            "audio_url": audio_url,
        })

    # Sort by date (newest first) and apply limit
    sermons.sort(key=lambda s: s["date"], reverse=True)
    if limit:
        sermons = sermons[:limit]

    print(f"  Sermons with audio: {len(sermons)}")
    return sermons


# ══════════════════════════════════════════════════════════════════════
# Intake: CSV
# ══════════════════════════════════════════════════════════════════════

def intake_csv(csv_path):
    """Read sermon metadata from CSV file."""
    sermons = []
    with open(csv_path, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames:
            reader.fieldnames = [fn.strip().lower().replace(" ", "_") for fn in reader.fieldnames]
        for row in reader:
            sermon = {
                "preacher": row.get("preacher", "").strip(),
                "title": row.get("title", "").strip(),
                "primary_text": row.get("primary_text", "").strip(),
                "date": row.get("date", "").strip(),
                "series_name": row.get("series_name", "").strip(),
                "audio_url": row.get("audio_url", "").strip(),
            }
            if sermon["audio_url"]:
                sermons.append(sermon)

    print(f"  Loaded {len(sermons)} sermons from CSV")
    return sermons


# ══════════════════════════════════════════════════════════════════════
# Intake: Local Files
# ══════════════════════════════════════════════════════════════════════

def intake_local(directory, preacher):
    """Scan a local directory for audio files."""
    directory = Path(directory)
    if not directory.is_dir():
        print(f"  ERROR: {directory} is not a directory")
        sys.exit(1)

    sermons = []
    for f in sorted(directory.iterdir()):
        if f.suffix.lower() in AUDIO_EXTENSIONS:
            title = f.stem.replace("-", " ").replace("_", " ").strip()
            sermons.append({
                "preacher": preacher,
                "title": title,
                "primary_text": "",
                "date": "",
                "series_name": "",
                "audio_url": "",
                "_local_path": str(f),
            })

    print(f"  Found {len(sermons)} audio files in {directory}")
    return sermons


# ══════════════════════════════════════════════════════════════════════
# Download
# ══════════════════════════════════════════════════════════════════════

def download_audio(url, dest_dir, filename_base):
    """Download audio file, return local path."""
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = requests.get(url, headers={"User-Agent": USER_AGENT},
                                stream=True, timeout=DOWNLOAD_TIMEOUT, allow_redirects=True)
            resp.raise_for_status()

            ext = detect_extension(url, resp.headers)
            dest = Path(dest_dir) / f"{filename_base}{ext}"

            total = int(resp.headers.get("content-length", 0))
            downloaded = 0

            with open(dest, "wb") as f:
                for chunk in resp.iter_content(chunk_size=65536):
                    f.write(chunk)
                    downloaded += len(chunk)

            return str(dest)

        except Exception as e:
            if attempt < MAX_RETRIES:
                wait = attempt * 5
                print(f"      Retry {attempt}/{MAX_RETRIES} in {wait}s: {e}")
                time.sleep(wait)
            else:
                raise


# ══════════════════════════════════════════════════════════════════════
# Transcription
# ══════════════════════════════════════════════════════════════════════

def clean_transcript(text):
    """Clean Whisper output for decomp pipeline."""
    # Remove repeated lines (Whisper hallucination artifact)
    lines = text.split("\n")
    cleaned = []
    prev = ""
    for line in lines:
        s = line.strip()
        if s and s != prev:
            cleaned.append(s)
            prev = s
    text = "\n".join(cleaned)

    # Remove audio event markers
    text = re.sub(r'\[(?:Music|Applause|Laughter|Silence|Inaudible|BLANK_AUDIO)\]',
                  '', text, flags=re.IGNORECASE)

    # Normalize whitespace
    text = re.sub(r' +', ' ', text)
    text = re.sub(r'\n{3,}', '\n\n', text)

    # Remove leading/trailing whitespace per line
    lines = [l.strip() for l in text.split("\n")]
    text = "\n".join(lines)

    return text.strip()


def transcribe_sermon(model, audio_path, language="en"):
    """Run Whisper on a single audio file, return cleaned text."""
    result = model.transcribe(
        audio_path,
        language=language,
        task="transcribe",
        verbose=False,
        # Sermon-specific settings:
        condition_on_previous_text=True,  # Helps with coherence in long audio
        compression_ratio_threshold=2.4,  # Default; catches hallucination loops
        no_speech_threshold=0.6,          # Default
    )
    raw_text = result["text"]
    return clean_transcript(raw_text)


# ══════════════════════════════════════════════════════════════════════
# Main Pipeline
# ══════════════════════════════════════════════════════════════════════

def run(sermons, output_dir, model_name="large-v3", language="en", skip_existing=True):
    """Process a list of sermon dicts through download → transcribe → save."""

    if not WHISPER_OK:
        print("\nERROR: openai-whisper is not installed.")
        print("  pip install openai-whisper torch requests feedparser --break-system-packages")
        print("  For GPU: pip install torch --index-url https://download.pytorch.org/whl/cu121")
        sys.exit(1)

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    audio_cache = output_dir / "_audio_cache"
    audio_cache.mkdir(exist_ok=True)

    # ── System info ──
    print()
    print("=" * 64)
    print("  Shepherd's Guild — Sermon Transcription Pipeline")
    print("=" * 64)
    device = "cuda" if GPU_AVAILABLE else "cpu"
    if GPU_AVAILABLE:
        print(f"  GPU:      {GPU_NAME} ({GPU_VRAM:.1f} GB VRAM)")
    else:
        print(f"  GPU:      None — using CPU (expect ~10x slower)")
    print(f"  Model:    {model_name}")
    print(f"  Device:   {device}")
    print(f"  Sermons:  {len(sermons)}")
    print(f"  Output:   {output_dir.resolve()}")

    # VRAM check
    needed = VRAM_REQUIREMENTS.get(model_name, 10)
    if GPU_AVAILABLE and GPU_VRAM < needed:
        print(f"\n  WARNING: {model_name} needs ~{needed} GB VRAM, you have {GPU_VRAM:.1f} GB")
        print(f"  Consider: --model medium (5 GB) or --model small (2 GB)")

    # ── Load model ──
    print(f"\n  Loading Whisper {model_name}...")
    t0 = time.time()
    model = whisper.load_model(model_name, device=device)
    print(f"  Model loaded in {fmt_duration(time.time() - t0)}")
    print("-" * 64)

    # ── Process ──
    results = []
    total_start = time.time()
    skipped = 0
    failed = 0

    for i, sermon in enumerate(sermons, 1):
        preacher_slug = slugify(sermon["preacher"]) or "unknown"
        title_slug = slugify(sermon["title"]) or f"sermon-{i:03d}"
        filename = f"{preacher_slug}_{title_slug}"

        transcript_path = output_dir / f"{filename}.txt"
        meta_path = output_dir / f"{filename}.meta.json"

        print(f"\n[{i}/{len(sermons)}] {sermon['preacher']} — {sermon['title'][:50]}")

        # Skip if already done
        if skip_existing and transcript_path.exists():
            print(f"  SKIP (transcript exists)")
            skipped += 1
            continue

        # ── Get audio path ──
        audio_path = sermon.get("_local_path")

        if not audio_path and sermon.get("audio_url"):
            try:
                print(f"  Downloading...")
                audio_path = download_audio(sermon["audio_url"], str(audio_cache), filename)
                fsize = Path(audio_path).stat().st_size
                print(f"  Downloaded: {fmt_size(fsize)}")
            except Exception as e:
                print(f"  FAILED (download): {e}")
                results.append({"sermon": sermon, "status": "download_failed", "error": str(e)})
                failed += 1
                continue

        if not audio_path or not Path(audio_path).exists():
            print(f"  FAILED: No audio file found")
            results.append({"sermon": sermon, "status": "no_audio", "error": "No audio path"})
            failed += 1
            continue

        # ── Transcribe ──
        try:
            print(f"  Transcribing...")
            t1 = time.time()
            transcript = transcribe_sermon(model, audio_path, language)
            elapsed = time.time() - t1
            word_count = len(transcript.split())
            print(f"  Done: {word_count:,} words in {fmt_duration(elapsed)}")
        except Exception as e:
            print(f"  FAILED (transcription): {e}")
            results.append({"sermon": sermon, "status": "transcribe_failed", "error": str(e)})
            failed += 1
            continue

        # ── Save transcript ──
        with open(transcript_path, "w", encoding="utf-8") as f:
            f.write(transcript)

        # ── Save metadata sidecar ──
        meta = {
            "preacher": sermon["preacher"],
            "title": sermon["title"],
            "primary_text": sermon.get("primary_text", ""),
            "date": sermon.get("date", ""),
            "series_name": sermon.get("series_name", ""),
            "audio_url": sermon.get("audio_url", ""),
            "audio_file": os.path.basename(audio_path) if audio_path else "",
            "transcript_file": transcript_path.name,
            "word_count": word_count,
            "transcription_time_seconds": round(elapsed, 1),
            "whisper_model": model_name,
            "transcribed_at": datetime.now().isoformat(),
        }
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2, ensure_ascii=False)

        results.append({"sermon": sermon, "status": "success", "words": word_count, "time": elapsed})

    # ── Summary ──
    total_time = time.time() - total_start
    successful = len([r for r in results if r.get("status") == "success"])

    print()
    print("=" * 64)
    print(f"  COMPLETE")
    print(f"  Processed:  {successful} sermons")
    print(f"  Skipped:    {skipped} (already transcribed)")
    print(f"  Failed:     {failed}")
    print(f"  Total time: {fmt_duration(total_time)}")
    if successful > 0:
        avg = total_time / successful
        print(f"  Avg time:   {fmt_duration(avg)} per sermon")
    print(f"  Output:     {output_dir.resolve()}")
    print("=" * 64)

    # ── Save run log ──
    log_path = output_dir / "_run_log.json"
    log = {
        "run_at": datetime.now().isoformat(),
        "model": model_name,
        "device": device,
        "gpu": GPU_NAME,
        "total_sermons": len(sermons),
        "successful": successful,
        "skipped": skipped,
        "failed": failed,
        "total_seconds": round(total_time, 1),
        "results": [
            {
                "title": r["sermon"]["title"],
                "preacher": r["sermon"]["preacher"],
                "status": r.get("status"),
                "words": r.get("words"),
                "time": round(r["time"], 1) if r.get("time") else None,
                "error": r.get("error"),
            }
            for r in results
        ],
    }
    with open(log_path, "w", encoding="utf-8") as f:
        json.dump(log, f, indent=2, ensure_ascii=False)

    return results


# ══════════════════════════════════════════════════════════════════════
# CLI
# ══════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="Shepherd's Guild — Sermon Transcription Pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python sermontranscribe.py rss "https://feed.url/rss" --preacher "Mark Dever"
  python sermontranscribe.py csv sermons.csv
  python sermontranscribe.py local ./mp3s --preacher "Tony Evans"
  python sermontranscribe.py rss "https://feed.url" --preacher "Name" --limit 30 --model medium
        """,
    )

    subparsers = parser.add_subparsers(dest="source", required=True)

    # RSS subcommand
    rss_parser = subparsers.add_parser("rss", help="Transcribe from RSS/podcast feed")
    rss_parser.add_argument("feed_url", help="RSS feed URL")
    rss_parser.add_argument("--preacher", required=True, help="Preacher name")
    rss_parser.add_argument("--limit", type=int, help="Max episodes to process (newest first)")

    # CSV subcommand
    csv_parser = subparsers.add_parser("csv", help="Transcribe from CSV of audio URLs")
    csv_parser.add_argument("csv_path", help="Path to CSV file")

    # Local subcommand
    local_parser = subparsers.add_parser("local", help="Transcribe local audio files")
    local_parser.add_argument("directory", help="Directory containing audio files")
    local_parser.add_argument("--preacher", required=True, help="Preacher name")

    # Shared options
    for sub in [rss_parser, csv_parser, local_parser]:
        sub.add_argument("--output", "-o", default="./transcripts", help="Output directory (default: ./transcripts)")
        sub.add_argument("--model", "-m", default="large-v3",
                         choices=["tiny", "base", "small", "medium", "large-v2", "large-v3"],
                         help="Whisper model (default: large-v3, needs ~10GB VRAM)")
        sub.add_argument("--language", "-l", default="en", help="Language code (default: en)")
        sub.add_argument("--no-skip", action="store_true", help="Re-transcribe even if output exists")

    args = parser.parse_args()

    # ── Intake ──
    if args.source == "rss":
        sermons = intake_rss(args.feed_url, args.preacher, args.limit)
    elif args.source == "csv":
        sermons = intake_csv(args.csv_path)
    elif args.source == "local":
        sermons = intake_local(args.directory, args.preacher)
    else:
        parser.print_help()
        sys.exit(1)

    if not sermons:
        print("  No sermons found. Exiting.")
        sys.exit(0)

    # ── Run ──
    run(sermons, args.output, model_name=args.model, language=args.language,
        skip_existing=not getattr(args, "no_skip", False))


if __name__ == "__main__":
    main()
