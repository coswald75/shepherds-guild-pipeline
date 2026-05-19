"""
sync_sermon_audio_from_rss.py
─────────────────────────────────────────────────────────────────────────────
Pull a podcast RSS feed and update sermons.audio_url + transcript_url +
audio_duration_seconds + audio_size_bytes + podcast_guid for matching rows
in Supabase.

Match strategy, in order of preference:
  1. existing sermons.podcast_guid == item.guid                  (re-runs)
  2. (preacher_id, normalized_title, date) match                 (first run)

If no match, the item is logged as unmatched. Nothing is inserted — this
script only updates audio metadata for sermons that already exist in
Supabase (which is true for everything in Chris's 287-row corpus).

Usage:
    python sync_sermon_audio_from_rss.py \
      --preacher 9c6f8d69-de55-45db-ac60-0fe6d0cfff59 \
      --feed https://sermons.sovgracekc.org/feed/ \
      [--dry-run]
─────────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from dataclasses import dataclass
from datetime import date as _date, timedelta
from difflib import SequenceMatcher
from email.utils import parsedate_to_datetime
from typing import Iterable

# Minimum title-similarity ratio (0.0–1.0) for a fuzzy ±7-day match to count.
# 0.6 catches "The Mystery of Godliness" ↔ "the mystery of godliness sermon"
# but excludes coincidental neighbors with unrelated titles.
FUZZY_THRESHOLD = 0.6
DATE_WINDOW_DAYS = 7

from dotenv import load_dotenv

load_dotenv(override=True)

try:
    import feedparser
except ImportError:
    print("pip install feedparser", file=sys.stderr)
    sys.exit(1)

try:
    from supabase import create_client
except ImportError:
    print("pip install supabase", file=sys.stderr)
    sys.exit(1)


_TITLE_NOISE = re.compile(r"[^\w\s]")
_WS = re.compile(r"\s+")


def normalize_title(t: str) -> str:
    return _WS.sub(" ", _TITLE_NOISE.sub(" ", (t or "").lower())).strip()


def parse_duration(raw: str | None) -> int | None:
    """Accept 'HH:MM:SS', 'MM:SS', or raw seconds."""
    if not raw:
        return None
    raw = raw.strip()
    if raw.isdigit():
        return int(raw)
    parts = raw.split(":")
    try:
        parts = [int(p) for p in parts]
    except ValueError:
        return None
    if len(parts) == 3:
        h, m, s = parts
    elif len(parts) == 2:
        h, m, s = 0, parts[0], parts[1]
    else:
        return None
    return h * 3600 + m * 60 + s


@dataclass
class FeedItem:
    guid: str
    title: str
    pub_date: _date | None
    audio_url: str | None
    audio_size: int | None
    duration_s: int | None
    transcript_url: str | None


def parse_feed(feed_url: str) -> list[FeedItem]:
    feed = feedparser.parse(feed_url)
    items: list[FeedItem] = []
    for e in feed.entries:
        # Audio enclosure: prefer entry.enclosures, fall back to links rel=enclosure
        audio_url = None
        audio_size = None
        for enc in getattr(e, "enclosures", []) or []:
            href = enc.get("href") or enc.get("url")
            if href and (enc.get("type", "").startswith("audio/") or href.lower().endswith(".mp3")):
                audio_url = href
                try:
                    audio_size = int(enc.get("length")) if enc.get("length") else None
                except (TypeError, ValueError):
                    audio_size = None
                break
        if not audio_url:
            for link in getattr(e, "links", []) or []:
                if link.get("rel") == "enclosure" or link.get("type", "").startswith("audio/"):
                    audio_url = link.get("href")
                    try:
                        audio_size = int(link.get("length")) if link.get("length") else None
                    except (TypeError, ValueError):
                        audio_size = None
                    break

        # Transcript via <podcast:transcript> namespace
        transcript_url = None
        for k in ("podcast_transcript", "transcript"):
            t = e.get(k)
            if isinstance(t, dict):
                transcript_url = t.get("url") or t.get("href")
                break
            if isinstance(t, list) and t:
                t0 = t[0]
                transcript_url = (t0 or {}).get("url") or (t0 or {}).get("href")
                break

        duration_s = parse_duration(e.get("itunes_duration") or e.get("duration"))

        pub_date = None
        if getattr(e, "published_parsed", None):
            pp = e.published_parsed
            pub_date = _date(pp.tm_year, pp.tm_mon, pp.tm_mday)
        elif e.get("published"):
            try:
                pub_date = parsedate_to_datetime(e["published"]).date()
            except (TypeError, ValueError):
                pass

        items.append(
            FeedItem(
                guid=e.get("guid") or e.get("id") or e.get("link", ""),
                title=e.get("title", "").strip(),
                pub_date=pub_date,
                audio_url=audio_url,
                audio_size=audio_size,
                duration_s=duration_s,
                transcript_url=transcript_url,
            )
        )
    return items


def find_match(sb, preacher_id: str, item: FeedItem) -> dict | None:
    # 1. Try by podcast_guid (idempotent re-runs)
    res = sb.table("sermons").select("id, title, date, podcast_guid").eq("podcast_guid", item.guid).limit(1).execute()
    if res.data:
        return res.data[0]
    if not item.pub_date:
        return None

    # 2. Pull the preacher's sermons in a ±7-day window around the feed pub_date —
    # YASH bulk-uploads drift the podcast pub_date off the actual preaching date.
    start = (item.pub_date - timedelta(days=DATE_WINDOW_DAYS)).isoformat()
    end = (item.pub_date + timedelta(days=DATE_WINDOW_DAYS)).isoformat()
    res = (
        sb.table("sermons")
        .select("id, title, date, primary_text")
        .eq("preacher_id", preacher_id)
        .gte("date", start)
        .lte("date", end)
        .execute()
    )
    rows = res.data or []
    if not rows:
        return None

    feed_norm = normalize_title(item.title)
    same_date_iso = item.pub_date.isoformat()

    # 2a. Exact normalized title on same date — strongest signal.
    for row in rows:
        if row["date"] == same_date_iso and normalize_title(row["title"]) == feed_norm:
            return row

    # 2b. Substring containment on same date (title or primary_text either way).
    for row in rows:
        if row["date"] != same_date_iso:
            continue
        db_title = normalize_title(row["title"])
        db_text = normalize_title(row.get("primary_text") or "")
        if db_title and feed_norm and (db_title in feed_norm or feed_norm in db_title):
            return row
        if db_text and feed_norm and (db_text in feed_norm or feed_norm in db_text):
            return row

    # 2c. SequenceMatcher across the window — compare feed title to BOTH the
    # sermon title and its primary_text, since some YASH entries use the
    # passage reference as their title instead of the topical name.
    best_row = None
    best_score = 0.0
    for row in rows:
        db_title = normalize_title(row["title"])
        db_text = normalize_title(row.get("primary_text") or "")
        if not feed_norm:
            continue
        score = 0.0
        if db_title:
            score = max(score, SequenceMatcher(None, db_title, feed_norm).ratio())
        if db_text:
            score = max(score, SequenceMatcher(None, db_text, feed_norm).ratio())
        if row["date"] == same_date_iso:
            score += 0.1
        if score > best_score:
            best_score = score
            best_row = row

    if best_row and best_score >= FUZZY_THRESHOLD:
        return best_row
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--preacher", required=True, help="preacher_id UUID")
    ap.add_argument("--feed", required=True, help="Podcast RSS feed URL")
    ap.add_argument("--dry-run", action="store_true", help="Print what would change; write nothing")
    args = ap.parse_args()

    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or os.environ.get("SUPABASE_KEY")
    if not url or not key:
        print("ERROR: set SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY (or SUPABASE_KEY) in env", file=sys.stderr)
        return 2
    sb = create_client(url, key)

    print(f"Fetching feed: {args.feed}")
    items = parse_feed(args.feed)
    print(f"  found {len(items)} items in feed")

    matched = 0
    updated = 0
    no_audio = 0
    unmatched: list[FeedItem] = []

    for it in items:
        if not it.audio_url:
            no_audio += 1
            continue
        row = find_match(sb, args.preacher, it)
        if not row:
            unmatched.append(it)
            continue
        matched += 1
        patch: dict[str, object] = {
            "audio_url": it.audio_url,
            "podcast_guid": it.guid,
        }
        if it.transcript_url:
            patch["transcript_url"] = it.transcript_url
        if it.duration_s:
            patch["audio_duration_seconds"] = it.duration_s
        if it.audio_size:
            patch["audio_size_bytes"] = it.audio_size

        if args.dry_run:
            print(f"  WOULD UPDATE {row['id']} ({row.get('date')}) {row['title'][:60]}")
            continue
        sb.table("sermons").update(patch).eq("id", row["id"]).execute()
        updated += 1

    print()
    print(f"Summary:")
    print(f"  Feed items:            {len(items)}")
    print(f"  Items with audio URL:  {len(items) - no_audio}")
    print(f"  Matched in Supabase:   {matched}")
    print(f"  Updated:               {updated}{' (dry-run)' if args.dry_run else ''}")
    print(f"  Unmatched (logged):    {len(unmatched)}")

    if unmatched:
        print()
        print("Unmatched items (first 20):")
        for it in unmatched[:20]:
            print(f"  {it.pub_date}  {it.title[:80]}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
