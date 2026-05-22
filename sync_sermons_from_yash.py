"""
sync_sermons_from_yash.py
─────────────────────────────────────────────────────────────────────────────
Scrape a yetanothersermon.host church domain (e.g. sermons.sovgracekc.org)
and update sermons.audio_url + podcast_guid in Supabase by matching scraped
items to existing rows for a given preacher.

Why this exists alongside sync_sermon_audio_from_rss.py:
  - The YASH RSS feed is capped at ~185 items and uses podcast pubDate
    (often != preaching date), which makes title+date matching unreliable.
  - The HTML listing fully paginates and each detail page exposes the
    actual preaching date in a <dt>Date</dt><dd>...</dd> block.

Match strategies, in order:
  1. existing sermons.podcast_guid == sermon_page_url       (re-runs)
  2. exact date + normalized-title equality                  (clean win)
  3. exact date + fuzzy title (SequenceMatcher >= 0.6)       (title drift)
  4. ±7 day window + fuzzy title (>= 0.7)                    (date drift)

Update-only — never inserts. Skips sermons not in Supabase (other speakers,
or not yet decomposed).

Usage:
    python sync_sermons_from_yash.py \
      --preacher 9c6f8d69-de55-45db-ac60-0fe6d0cfff59 \
      --host https://sermons.sovgracekc.org \
      [--dry-run] [--limit 10]
─────────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import time
from dataclasses import dataclass
from datetime import date as _date, datetime, timedelta
from difflib import SequenceMatcher
from typing import Iterable, Optional

from dotenv import load_dotenv

load_dotenv(override=True)

try:
    import requests
except ImportError:
    print("pip install requests", file=sys.stderr)
    sys.exit(1)

try:
    from supabase import create_client
except ImportError:
    print("pip install supabase", file=sys.stderr)
    sys.exit(1)


HEADERS = {"User-Agent": "Mozilla/5.0 (sermon-steward audio-sync)"}
POLITE_SLEEP = 0.35  # seconds between requests

_DT_DATE = re.compile(r"<dt[^>]*>\s*Date\s*</dt>\s*<dd[^>]*>(.*?)</dd>", re.DOTALL)
_DT_SPEAKER = re.compile(r"<dt[^>]*>\s*Speaker\s*</dt>\s*<dd[^>]*>(.*?)</dd>", re.DOTALL)
_SPEAKER_NAME = re.compile(
    r'<a[^>]*href="/preachers/\d+/[^"]+"[^>]*>\s*([^<]+?)\s*</a>',
    re.DOTALL,
)
_SOURCE = re.compile(r'<source[^>]+src="([^"]+)"')
_OG_AUDIO = re.compile(
    r'<meta[^>]+content="([^"]+)"[^>]+property="og:audio"'
    r'|<meta[^>]+property="og:audio"[^>]+content="([^"]+)"'
)
_TITLE = re.compile(r"<title>(.*?)</title>", re.DOTALL)
_LISTING_URLS = re.compile(r'href="(/sermons/\d+/[^"]+/)"')
_TAG = re.compile(r"<[^>]+>")


def slurp(url: str, retries: int = 3, backoff: float = 2.0) -> str:
    last: Exception | None = None
    for i in range(retries):
        try:
            r = requests.get(url, headers=HEADERS, timeout=20)
            r.raise_for_status()
            return r.text
        except requests.RequestException as e:
            last = e
            if i < retries - 1:
                time.sleep(backoff ** i)
    raise RuntimeError(f"Failed after {retries} attempts: {url}") from last


@dataclass
class Item:
    url: str
    title: str
    date: Optional[_date]
    audio_url: Optional[str]
    speaker: Optional[str]


def parse_date(text: str) -> Optional[_date]:
    text = text.strip()
    for fmt in ("%b. %d, %Y", "%B %d, %Y", "%b %d, %Y", "%Y-%m-%d", "%d %B %Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def parse_detail(url: str, html: str) -> Item:
    title = ""
    m = _TITLE.search(html)
    if m:
        title = re.sub(r"\s+", " ", m.group(1)).strip()

    date = None
    m = _DT_DATE.search(html)
    if m:
        date = parse_date(_TAG.sub("", m.group(1)).strip())

    audio = None
    m = _SOURCE.search(html)
    if m:
        audio = m.group(1)
    if not audio:
        m = _OG_AUDIO.search(html)
        if m:
            audio = m.group(1) or m.group(2)

    # Normalize relative audio URLs (e.g. "/media/mp3/123.mp3") against the
    # detail-page host so all callers get an absolute URL. Previously this
    # prefix-add happened in main()'s loop, which silently broke any code
    # path that called parse_detail directly (e.g. ad-hoc backfill scripts).
    if audio and audio.startswith("/"):
        from urllib.parse import urlsplit
        parts = urlsplit(url)
        audio = f"{parts.scheme}://{parts.netloc}{audio}"

    speaker = None
    m = _DT_SPEAKER.search(html)
    if m:
        m2 = _SPEAKER_NAME.search(m.group(1))
        if m2:
            speaker = m2.group(1).strip()

    return Item(url=url, title=title, date=date, audio_url=audio, speaker=speaker)


def walk_listing(host: str) -> list[str]:
    """Return all sermon detail-page URLs by walking /sermons/?page=N.
    Stops on the first page that returns 404 or contains no new sermon URLs."""
    out: list[str] = []
    seen: set[str] = set()
    host = host.rstrip("/")
    page = 1
    while True:
        listing_url = f"{host}/sermons/?page={page}"
        try:
            r = requests.get(listing_url, headers=HEADERS, timeout=20)
            if r.status_code == 404:
                break  # past last page
            r.raise_for_status()
            html = r.text
        except requests.RequestException:
            break  # any other failure ends pagination
        paths = _LISTING_URLS.findall(html)
        new_paths = [p for p in paths if p not in seen]
        if not new_paths:
            break
        for p in new_paths:
            seen.add(p)
            out.append(host + p)
        page += 1
        time.sleep(POLITE_SLEEP)
    return out


def normalize_title(t: str) -> str:
    t = (t or "").lower()
    t = re.sub(r"[^\w\s]", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def title_sim(a: str, b: str) -> float:
    return SequenceMatcher(None, normalize_title(a), normalize_title(b)).ratio()


def find_match(sb, preacher_id: str, item: Item) -> tuple[Optional[dict], str]:
    # Strategy 1: existing podcast_guid
    res = (
        sb.table("sermons")
        .select("id, title, date, slug, hosted_audio_url")
        .eq("podcast_guid", item.url)
        .limit(1)
        .execute()
    )
    if res.data:
        return res.data[0], "guid"

    if not item.date:
        return None, "no_date"

    # Strategy 2: exact date + normalized title equality
    res = (
        sb.table("sermons")
        .select("id, title, date, slug, hosted_audio_url")
        .eq("preacher_id", preacher_id)
        .eq("date", item.date.isoformat())
        .execute()
    )
    target = normalize_title(item.title)
    for row in res.data or []:
        if normalize_title(row["title"]) == target:
            return row, "exact"

    # Strategy 3: exact date + fuzzy title (>= 0.6)
    best, best_ratio = None, 0.0
    for row in res.data or []:
        r = title_sim(item.title, row["title"])
        if r > best_ratio:
            best, best_ratio = row, r
    if best and best_ratio >= 0.6:
        return best, f"fuzzy_date_{best_ratio:.2f}"

    # Strategy 4: ±7 day window + fuzzy title (>= 0.7)
    start = (item.date - timedelta(days=7)).isoformat()
    end = (item.date + timedelta(days=7)).isoformat()
    res = (
        sb.table("sermons")
        .select("id, title, date, slug, hosted_audio_url")
        .eq("preacher_id", preacher_id)
        .gte("date", start)
        .lte("date", end)
        .execute()
    )
    best, best_ratio = None, 0.0
    for row in res.data or []:
        r = title_sim(item.title, row["title"])
        if r > best_ratio:
            best, best_ratio = row, r
    if best and best_ratio >= 0.7:
        return best, f"window_{best_ratio:.2f}"

    return None, "no_match"


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--preacher", required=True)
    ap.add_argument("--host", required=True)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()

    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or os.environ.get("SUPABASE_KEY")
    if not url or not key:
        print("ERROR: SUPABASE_URL / SUPABASE_KEY missing in env", file=sys.stderr)
        return 2
    sb = create_client(url, key)

    pre = sb.table("preachers").select("church_id").eq("id", args.preacher).limit(1).execute()
    church_slug: Optional[str] = None
    if pre.data and pre.data[0].get("church_id"):
        ch = sb.table("churches").select("slug").eq("id", pre.data[0]["church_id"]).limit(1).execute()
        church_slug = (ch.data[0].get("slug") if ch.data else None)
    if not church_slug:
        print("  [warn] no church_slug for this preacher; R2 mirror will be skipped")

    try:
        sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent))
        import sermon_audio_host  # noqa: E402
    except Exception as e:
        print(f"  [warn] sermon_audio_host import failed: {e}; R2 mirror disabled")
        sermon_audio_host = None  # type: ignore

    host = args.host.rstrip("/")
    print(f"Walking {host}/sermons/ …")
    sermon_urls = walk_listing(host)
    print(f"  found {len(sermon_urls)} sermon URLs")

    if args.limit:
        sermon_urls = sermon_urls[: args.limit]
        print(f"  limited to {len(sermon_urls)}")

    counts = {"updated": 0, "no_match": 0, "no_audio": 0, "fetch_error": 0,
              "mirrored": 0, "mirror_skipped": 0, "mirror_failed": 0}
    by_method: dict[str, int] = {}
    unmatched: list[Item] = []

    for i, surl in enumerate(sermon_urls, 1):
        try:
            html = slurp(surl)
        except RuntimeError as e:
            counts["fetch_error"] += 1
            print(f"  [{i}/{len(sermon_urls)}] FETCH ERROR: {surl}: {e}")
            continue

        item = parse_detail(surl, html)
        time.sleep(POLITE_SLEEP)

        if not item.audio_url:
            counts["no_audio"] += 1
            continue

        audio = item.audio_url
        if audio.startswith("/"):
            audio = host + audio

        row, method = find_match(sb, args.preacher, item)
        by_method[method] = by_method.get(method, 0) + 1

        if not row:
            counts["no_match"] += 1
            unmatched.append(item)
            continue

        patch = {"audio_url": audio, "podcast_guid": surl}

        sermon_slug = row.get("slug")
        if (
            sermon_audio_host
            and sermon_audio_host.is_configured()
            and church_slug
            and sermon_slug
            and not row.get("hosted_audio_url")
            and not args.dry_run
        ):
            try:
                hosted = sermon_audio_host.mirror_sermon(
                    source_url=audio,
                    church_slug=church_slug,
                    sermon_slug=sermon_slug,
                )
            except Exception as e:
                print(f"  [{i}/{len(sermon_urls)}] mirror error: {e}")
                hosted = None
            if hosted:
                patch["hosted_audio_url"] = hosted
                counts["mirrored"] += 1
            else:
                counts["mirror_failed"] += 1
        elif row.get("hosted_audio_url"):
            counts["mirror_skipped"] += 1

        if args.dry_run:
            print(
                f"  [{i}/{len(sermon_urls)}] WOULD UPDATE ({method:18s}) "
                f"{item.date}  {item.title[:55]}"
            )
            counts["updated"] += 1
            continue

        sb.table("sermons").update(patch).eq("id", row["id"]).execute()
        counts["updated"] += 1
        if i % 25 == 0:
            print(f"  [{i}/{len(sermon_urls)}] {counts['updated']} updated, {counts['mirrored']} mirrored …")

    print()
    print("Summary:")
    print(f"  Sermon URLs scraped:   {len(sermon_urls)}")
    print(f"  With audio source:     {len(sermon_urls) - counts['no_audio']}")
    print(f"  {'Would update' if args.dry_run else 'Updated'}:           {counts['updated']}")
    print(f"  Mirrored to R2:        {counts['mirrored']}")
    print(f"  Mirror skipped:        {counts['mirror_skipped']}")
    print(f"  Mirror failed:         {counts['mirror_failed']}")
    print(f"  Unmatched:             {counts['no_match']}")
    print(f"  No audio source:       {counts['no_audio']}")
    print(f"  Fetch errors:          {counts['fetch_error']}")
    print()
    print("Match strategy breakdown:")
    for m, c in sorted(by_method.items(), key=lambda x: -x[1]):
        print(f"  {m:20s}  {c}")

    if unmatched:
        print()
        print("Unmatched (first 30):")
        for it in unmatched[:30]:
            spk = f" [{it.speaker}]" if it.speaker else ""
            print(f"  {it.date}  {it.title[:75]}{spk}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
