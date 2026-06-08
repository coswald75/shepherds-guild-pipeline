"""
sync_sermons_from_nucleus.py
─────────────────────────────────────────────────────────────────────────────
Walk a Nucleus Church platform sermon-hub API and update sermons.audio_url +
transcript_url + podcast_guid in Supabase by matching scraped items to
existing rows for a given preacher.

Why Nucleus (vs RSS/YASH):
  - Nucleus exposes a clean public JSON API at
    {host}/_api/public/sermon-hub/{engine_id}/sermons (cursor pagination)
    and detail pages at /page/{slug}?basePath=sermons.
  - The Cross of Grace pattern (download_crossofgrace.py) already extracts
    media URLs from `sermon.mediaItems[].item.src` (audio) and
    `sermon.attachments[]` (transcript). This script does the same, but
    writes URLs to Supabase instead of downloading files.

Match strategies, in order:
  1. existing sermons.podcast_guid == "nucleus:<slug>"          (re-runs)
  2. exact date + normalized-title equality                     (clean win)
  3. exact date + fuzzy title (SequenceMatcher >= 0.6)          (title drift)
  4. ±7 day window + fuzzy title (>= 0.7)                       (date drift)

If no match, INSERT a new sermons row from the Nucleus item (title, date,
audio_url, transcript_url, podcast_guid='nucleus:<slug>', slug). Insert
is idempotent: subsequent runs hit the podcast_guid match (strategy 1)
and fall through to UPDATE. Use --no-insert to keep the legacy
log-only behavior for debug runs.

Usage:
    python sync_sermons_from_nucleus.py \\
      --preacher ccb9e59c-bd20-414a-bd6b-25b117b8144c \\
      --host https://www.crossofgrace.net \\
      --engine-id sermonengine_1cece008cc344cf78ce011f620a7ccff \\
      [--dry-run]    # print what would happen; no writes
      [--no-insert]  # keep legacy behavior: log unmatched, do not insert
      [--limit 10]

For Supabase-driven invocation, the church row should have:
    ingest_source_type = 'nucleus'
    audio_base_url     = 'https://www.crossofgrace.net'
    ingest_config      = {"engine_id": "sermonengine_..."}
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
from typing import Optional

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


HEADERS = {"User-Agent": "Mozilla/5.0 (sermon-steward nucleus-sync)"}
POLITE_SLEEP = 0.3


@dataclass
class Item:
    slug: str
    title: str
    date: Optional[_date]
    audio_url: Optional[str]
    transcript_url: Optional[str]
    speakers: list[str]
    audio_size: Optional[int] = None
    sermon_page_url: Optional[str] = None  # for podcast_guid


def _api_get(url: str, retries: int = 3) -> dict:
    last: Exception | None = None
    for i in range(retries):
        try:
            r = requests.get(url, headers=HEADERS, timeout=20)
            r.raise_for_status()
            return r.json()
        except (requests.RequestException, ValueError) as e:
            last = e
            if i < retries - 1:
                time.sleep(2 ** i)
    raise RuntimeError(f"Failed after {retries}: {url}") from last


def _parse_iso_date(s: str | None) -> Optional[_date]:
    if not s:
        return None
    try:
        # Nucleus returns "2026-05-10T12:00:00.000Z"
        return datetime.fromisoformat(s.replace("Z", "+00:00")).date()
    except (ValueError, TypeError):
        return None


def walk_listing(host: str, engine_id: str) -> list[dict]:
    """Cursor-paginate all sermons from the Nucleus API."""
    base = f"{host.rstrip('/')}/_api/public/sermon-hub/{engine_id}"
    out: list[dict] = []
    cursor: Optional[str] = None
    while True:
        url = f"{base}/sermons?order=desc&orderBy=date"
        if cursor:
            url += f"&cursor={cursor}"
        data = _api_get(url)
        sermons = data.get("sermons") or []
        if not sermons:
            break
        out.extend(sermons)
        cursor = data.get("cursor")
        if not cursor:
            break
        time.sleep(POLITE_SLEEP)
    return out


def extract_media(detail: dict) -> tuple[Optional[str], Optional[str], Optional[int]]:
    """From a Nucleus detail page, pull (audio_url, transcript_url, audio_size_bytes)."""
    audio_url = None
    transcript_url = None
    audio_size = None
    page = detail.get("page", {})
    for section in (page.get("sections", {}) or {}).values():
        for block in (section.get("payload", {}).get("blocks", []) or []):
            sermon = block.get("sermon", {}) or {}
            # Transcript via attachments
            for att in sermon.get("attachments", []) or []:
                label = (att.get("label") or "").lower()
                dest = (att.get("destination") or "").lower()
                if not transcript_url and ("transcript" in label or "transcript" in dest):
                    transcript_url = att.get("destination")
            # Audio via mediaItems
            for media in (sermon.get("mediaItems") or {}).values():
                item = media.get("item", {}) or {}
                src = item.get("src", "")
                ctype = item.get("contentType", "")
                if not audio_url and src and (".mp3" in src or ctype.startswith("audio") or "audio" in src):
                    audio_url = src
                    audio_size = item.get("size") or item.get("contentLength")
                    try:
                        audio_size = int(audio_size) if audio_size else None
                    except (TypeError, ValueError):
                        audio_size = None
    return audio_url, transcript_url, audio_size


def fetch_item(host: str, engine_id: str, sermon: dict) -> Item:
    base = f"{host.rstrip('/')}/_api/public/sermon-hub/{engine_id}"
    slug = sermon.get("slug", "")
    title = sermon.get("title", "").strip()
    date = _parse_iso_date(sermon.get("date"))
    speakers_dict = sermon.get("speakers", {}) or {}
    speakers = [v.get("displayName", "") for v in speakers_dict.values() if isinstance(v, dict)]

    audio_url = transcript_url = None
    audio_size = None
    try:
        detail = _api_get(f"{base}/page/{slug}?basePath=sermons")
        audio_url, transcript_url, audio_size = extract_media(detail)
    except RuntimeError:
        pass

    # Resolve relative transcript URL against host
    if transcript_url and transcript_url.startswith("/"):
        transcript_url = host.rstrip("/") + transcript_url

    sermon_page_url = f"{host.rstrip('/')}/sermons/{slug}/"

    return Item(
        slug=slug, title=title, date=date,
        audio_url=audio_url, transcript_url=transcript_url,
        speakers=speakers, audio_size=audio_size,
        sermon_page_url=sermon_page_url,
    )


def normalize_title(t: str) -> str:
    t = (t or "").lower()
    t = re.sub(r"[^\w\s]", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def title_sim(a: str, b: str) -> float:
    return SequenceMatcher(None, normalize_title(a), normalize_title(b)).ratio()


def speaker_matches_target(speakers: list[str], target_name: str) -> bool:
    """True iff every token of the target preacher's name appears in the
    speaker label.

    Nucleus serves the whole CHURCH catalog including guest preachers.
    Without this filter, the INSERT branch would attribute every guest's
    sermon to the target preacher (the 96-row mess discovered 2026-06-08).

    "Every token" is the right level of strictness:

    - For target "Ricky Alcantar" — matches speaker "Ricky Alcantar",
      "Pastor Ricky Alcantar", "Reverend Doctor Ricky Alcantar III", etc.
    - Rejects "Joe Alcantar Jr." (shares only one token) — important
      because Ricky's relative Joe Alcantar Jr. also appears in the
      CoG catalog.
    - Rejects "Ricky" alone — unfortunate but unavoidable when only the
      first name is present. Safer to skip than to risk attributing a
      different "Ricky" to the wrong preacher.
    - Rejects "Sal Valenzuela", "Alec Shoffeitt", etc. — the
      not-actually-Ricky guest preachers.
    """
    if not target_name or not speakers:
        return False
    target_tokens = set(normalize_title(target_name).split())
    if not target_tokens:
        return False
    for s in speakers:
        s_tokens = set(normalize_title(s or "").split())
        # All target tokens must be present in the speaker tokens.
        if target_tokens.issubset(s_tokens):
            return True
    return False


_SLUG_NONALNUM = re.compile(r"[^a-z0-9]+")


def generate_slug(title: str, pub_date: _date | None) -> str:
    """Make a URL-safe slug from title (+ date suffix for collisions).

    Matches the date-suffixed convention used by scrape_sovgrace.py and the
    RSS adapter:
        "Where We're At 2021" + 2021-01-01 → "where-we-re-at-2021-2021-01-01"
    """
    base = _SLUG_NONALNUM.sub("-", (title or "").lower()).strip("-")
    base = base[:80].rstrip("-") if base else "untitled"
    if pub_date:
        return f"{base}-{pub_date.isoformat()}"
    return base


def find_match(sb, preacher_id: str, item: Item) -> tuple[Optional[dict], str]:
    guid = f"nucleus:{item.slug}"
    res = sb.table("sermons").select("id, title, date, slug, hosted_audio_url") \
        .eq("podcast_guid", guid).limit(1).execute()
    if res.data:
        return res.data[0], "guid"

    if not item.date:
        return None, "no_date"

    res = sb.table("sermons").select("id, title, date, slug, hosted_audio_url") \
        .eq("preacher_id", preacher_id) \
        .eq("date", item.date.isoformat()).execute()
    target = normalize_title(item.title)
    for row in res.data or []:
        if normalize_title(row["title"]) == target:
            return row, "exact"

    best, best_ratio = None, 0.0
    for row in res.data or []:
        r = title_sim(item.title, row["title"])
        if r > best_ratio:
            best, best_ratio = row, r
    if best and best_ratio >= 0.6:
        return best, f"fuzzy_date_{best_ratio:.2f}"

    start = (item.date - timedelta(days=7)).isoformat()
    end = (item.date + timedelta(days=7)).isoformat()
    res = sb.table("sermons").select("id, title, date, slug, hosted_audio_url") \
        .eq("preacher_id", preacher_id) \
        .gte("date", start).lte("date", end).execute()
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
    ap.add_argument("--host", required=True, help="e.g. https://www.crossofgrace.net")
    ap.add_argument("--engine-id", required=True, help="Nucleus sermon-hub engine ID")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument(
        "--no-insert",
        action="store_true",
        help="Legacy behavior: log unmatched items, do not INSERT new rows. "
             "Default is to insert.",
    )
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()

    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or os.environ.get("SUPABASE_KEY")
    if not url or not key:
        print("ERROR: SUPABASE_URL / SUPABASE_KEY missing in env", file=sys.stderr)
        return 2
    sb = create_client(url, key)

    # Resolve church_slug + preacher name once. The name is required for the
    # multi-speaker guard below (Nucleus serves the whole church catalog
    # including guest preachers; we MUST skip non-target speakers or we
    # mis-attribute their sermons to the --preacher arg).
    pre = (
        sb.table("preachers")
        .select("church_id, name")
        .eq("id", args.preacher)
        .limit(1)
        .execute()
    )
    church_slug: Optional[str] = None
    target_preacher_name: str = ""
    if pre.data:
        target_preacher_name = pre.data[0].get("name") or ""
        if pre.data[0].get("church_id"):
            ch = sb.table("churches").select("slug").eq("id", pre.data[0]["church_id"]).limit(1).execute()
            church_slug = (ch.data[0].get("slug") if ch.data else None)
    if not church_slug:
        print("  [warn] no church_slug for this preacher; R2 mirror will be skipped")
    if not target_preacher_name:
        print(f"  [error] could not resolve target preacher name for id={args.preacher}; refusing to run")
        return 2
    print(f"  target preacher: {target_preacher_name!r} (will skip items spoken by others)")

    # Lazy-import so the script still works when boto3 isn't installed.
    try:
        sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent))
        import sermon_audio_host  # noqa: E402
    except Exception as e:
        print(f"  [warn] sermon_audio_host import failed: {e}; R2 mirror disabled")
        sermon_audio_host = None  # type: ignore

    host = args.host.rstrip("/")
    print(f"Walking Nucleus listing for {host} (engine={args.engine_id}) …")
    sermons = walk_listing(host, args.engine_id)
    print(f"  found {len(sermons)} sermons")

    if args.limit:
        sermons = sermons[: args.limit]
        print(f"  limited to {len(sermons)}")

    counts = {"updated": 0, "inserted": 0, "no_match": 0, "no_audio": 0,
              "skipped_other_preacher": 0,
              "fetch_error": 0, "mirrored": 0, "mirror_skipped": 0, "mirror_failed": 0}
    by_method: dict[str, int] = {}
    unmatched: list[Item] = []

    for i, raw in enumerate(sermons, 1):
        try:
            item = fetch_item(host, args.engine_id, raw)
        except Exception as e:
            counts["fetch_error"] += 1
            print(f"  [{i}/{len(sermons)}] FETCH ERROR: {raw.get('slug')}: {e}")
            continue
        time.sleep(POLITE_SLEEP)

        if not item.audio_url:
            counts["no_audio"] += 1
            continue

        # ─── Multi-speaker guard ─────────────────────────────────────────
        # Nucleus serves the whole CHURCH catalog including guest preachers.
        # The Item.speakers list comes from the same Nucleus payload; if
        # the target preacher's last name isn't in that list, this sermon
        # isn't ours and must be skipped — otherwise the INSERT branch
        # would attribute someone else's sermon to args.preacher (the
        # 2026-06-08 bug that produced 96 mis-attributed rows).
        if not speaker_matches_target(item.speakers, target_preacher_name):
            counts["skipped_other_preacher"] += 1
            continue

        row, method = find_match(sb, args.preacher, item)
        by_method[method] = by_method.get(method, 0) + 1

        # ─── INSERT path: unmatched Nucleus item → new sermons row ─────────
        # The four-strategy match (above) makes a false negative unlikely.
        # When this fires it's a genuinely new sermon — typically the
        # week's fresh Sunday. Re-runs land in strategy 1 (podcast_guid
        # match) and fall through to UPDATE instead of double-inserting.
        if not row:
            if args.no_insert:
                counts["no_match"] += 1
                unmatched.append(item)
                continue

            new_slug = generate_slug(item.title, item.date)
            insert_payload: dict[str, object] = {
                "preacher_id": args.preacher,
                "title": item.title or "Untitled",
                "audio_url": item.audio_url,
                "podcast_guid": f"nucleus:{item.slug}",
                "slug": new_slug,
                "upload_source": "host_sync",
            }
            if item.date:
                insert_payload["date"] = item.date.isoformat()
            if item.transcript_url:
                insert_payload["transcript_url"] = item.transcript_url
            if item.audio_size:
                insert_payload["audio_size_bytes"] = item.audio_size

            if args.dry_run:
                print(
                    f"  [{i}/{len(sermons)}] WOULD INSERT  {item.date}  "
                    f"{item.title[:55]} slug={new_slug}"
                )
                counts["inserted"] += 1
                continue

            try:
                ins = sb.table("sermons").insert(insert_payload).execute()
                if not ins.data:
                    counts["no_match"] += 1
                    unmatched.append(item)
                    print(f"  [{i}/{len(sermons)}] insert returned no rows for {item.title[:55]!r}")
                    continue
                new_id = ins.data[0]["id"]
                counts["inserted"] += 1
                print(f"  [{i}/{len(sermons)}] INSERTED {new_id} ({item.date}) {item.title[:55]}")
            except Exception as e:
                counts["no_match"] += 1
                unmatched.append(item)
                print(f"  [{i}/{len(sermons)}] insert failed for {item.title[:55]!r}: {e}")
                continue

            # R2 mirror in the same pass (mirrors the UPDATE-side behavior below).
            if (
                sermon_audio_host
                and sermon_audio_host.is_configured()
                and church_slug
            ):
                try:
                    hosted = sermon_audio_host.mirror_sermon(
                        source_url=item.audio_url,
                        church_slug=church_slug,
                        sermon_slug=new_slug,
                    )
                except Exception as e:
                    print(f"  [{i}/{len(sermons)}] mirror error: {e}")
                    hosted = None
                if hosted:
                    sb.table("sermons").update({"hosted_audio_url": hosted}).eq(
                        "id", new_id
                    ).execute()
                    counts["mirrored"] += 1
                else:
                    counts["mirror_failed"] += 1
            continue

        # ─── UPDATE path: existing row, populate metadata + R2 mirror ─────
        patch = {
            "audio_url": item.audio_url,
            "podcast_guid": f"nucleus:{item.slug}",
        }
        if item.transcript_url:
            patch["transcript_url"] = item.transcript_url
        if item.audio_size:
            patch["audio_size_bytes"] = item.audio_size

        # Mirror to R2 if we can. Even when audio_url itself is unchanged,
        # row.hosted_audio_url may be NULL — mirror covers that case too.
        hosted = None
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
                    source_url=item.audio_url,
                    church_slug=church_slug,
                    sermon_slug=sermon_slug,
                )
            except Exception as e:
                print(f"  [{i}/{len(sermons)}] mirror error: {e}")
            if hosted:
                patch["hosted_audio_url"] = hosted
                counts["mirrored"] += 1
            else:
                counts["mirror_failed"] += 1
        elif row.get("hosted_audio_url"):
            counts["mirror_skipped"] += 1

        if args.dry_run:
            print(f"  [{i}/{len(sermons)}] WOULD UPDATE ({method:18s}) {item.date}  {item.title[:55]}")
            counts["updated"] += 1
            continue
        sb.table("sermons").update(patch).eq("id", row["id"]).execute()
        counts["updated"] += 1
        if i % 25 == 0:
            print(f"  [{i}/{len(sermons)}] {counts['updated']} updated, {counts['mirrored']} mirrored …")

    print()
    print("Summary:")
    print(f"  Sermons in Nucleus listing: {len(sermons)}")
    print(f"  With audio URL:             {len(sermons) - counts['no_audio']}")
    print(f"  Other preacher (skipped):   {counts['skipped_other_preacher']}")
    print(f"  {'Would update' if args.dry_run else 'Updated'}:                  {counts['updated']}")
    print(f"  {'Would insert' if args.dry_run else 'Inserted'}:                 {counts['inserted']}")
    print(f"  Mirrored to R2:             {counts['mirrored']}")
    print(f"  Mirror skipped (had URL):   {counts['mirror_skipped']}")
    print(f"  Mirror failed:              {counts['mirror_failed']}")
    print(f"  Unmatched & not inserted:   {counts['no_match']}")
    print(f"  No audio source:            {counts['no_audio']}")
    print(f"  Fetch errors:               {counts['fetch_error']}")
    print()
    print("Match strategy breakdown:")
    for m, c in sorted(by_method.items(), key=lambda x: -x[1]):
        print(f"  {m:20s}  {c}")

    if unmatched:
        print()
        if args.no_insert:
            print("Unmatched (would have been inserted without --no-insert; first 30):")
        else:
            print("Unmatched that failed to insert (first 30):")
        for it in unmatched[:30]:
            spk = f" [{', '.join(it.speakers)}]" if it.speakers else ""
            print(f"  {it.date}  {it.title[:65]}{spk}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
