"""
sync_sermons_from_nucleus.py
─────────────────────────────────────────────────────────────────────────────
Walk a Nucleus Church platform sermon-hub API and update sermons.audio_url +
transcript_url + podcast_guid in Supabase. Sermons are routed to whichever
preacher at the church the Nucleus item's speakers list matches.

Why Nucleus (vs RSS/YASH):
  - Nucleus exposes a clean public JSON API at
    {host}/_api/public/sermon-hub/{engine_id}/sermons (cursor pagination)
    and detail pages at /page/{slug}?basePath=sermons.
  - Each item carries a `speakers` list, which is what enables church-wide
    dispatch: we know which pastor preached without having to guess.

Whole-church dispatch (default):
  Nucleus serves the church's full catalog including guest preachers.
  This script resolves the church from --preacher and then routes each
  Nucleus item to whichever preacher_id at that church the speakers list
  matches. So a Cross of Grace run for --preacher Ricky also picks up Sal
  Valenzuela's, Jonathan Vogan's, Alec Shoffeitt's, etc. sermons —
  attributed correctly to each.

  Items whose speaker isn't in the preachers table for that church are
  skipped (truly unknown — outside guest preacher with no profile yet).

  Use --single-preacher to revert to legacy behavior (only match the
  given preacher; skip everything else).

Match strategies (per dispatched preacher_id):
  1. existing sermons.podcast_guid == "nucleus:<slug>"          (re-runs)
  2. exact date + normalized-title equality                     (clean win)
  3. exact date + fuzzy title (SequenceMatcher >= 0.6)          (title drift)
  4. ±7 day window + fuzzy title (>= 0.7)                       (date drift)

If no match, INSERT a new sermons row under the routed preacher_id.
Insert is idempotent: subsequent runs hit the podcast_guid match
(strategy 1) and fall through to UPDATE. Use --no-insert to keep the
legacy log-only behavior for debug runs.

Usage:
    # Whole-church (default) — ingests every preacher's sermons at the
    # church under the right preacher_id:
    python sync_sermons_from_nucleus.py \\
      --preacher ccb9e59c-bd20-414a-bd6b-25b117b8144c \\
      --host https://www.crossofgrace.net \\
      --engine-id sermonengine_1cece008cc344cf78ce011f620a7ccff \\
      [--dry-run]
      [--no-insert]
      [--limit 10]

    # Legacy single-preacher (only matches the given preacher):
    python sync_sermons_from_nucleus.py \\
      ... \\
      --single-preacher

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

    Used only in --single-preacher mode. In default whole-church mode,
    dispatch_speaker_to_preacher() is used instead.
    """
    if not target_name or not speakers:
        return False
    target_tokens = set(normalize_title(target_name).split())
    if not target_tokens:
        return False
    for s in speakers:
        s_tokens = set(normalize_title(s or "").split())
        if target_tokens.issubset(s_tokens):
            return True
    return False


def dispatch_speaker_to_preacher(
    speakers: list[str],
    preachers_by_name: dict[frozenset[str], tuple[str, str]],
) -> Optional[tuple[str, str]]:
    """Given Nucleus' speakers list, return (preacher_id, preacher_name) of
    the church preacher whose name tokens are a subset of any speaker's
    tokens. Returns None when no preacher matches.

    The `preachers_by_name` map is built once at startup by load_church_preachers.
    Keys are frozensets of normalized name tokens for fast subset checks.

    Matching rule mirrors speaker_matches_target — every token of the
    preacher's name must appear in the speaker label. Falsely matches
    "Joe Alcantar Jr." for "Alcantar" alone are impossible because
    preacher names in `preachers` always include first AND last name.

    If a speaker matches multiple preachers (rare — would require a sermon
    where Nucleus listed e.g. "Ricky Alcantar and Joe Alcantar Jr." in one
    string), the longest preacher-name match wins (more specific = better).
    """
    if not speakers:
        return None
    best: Optional[tuple[str, str, int]] = None  # (id, name, specificity)
    for s in speakers:
        s_tokens = set(normalize_title(s or "").split())
        if not s_tokens:
            continue
        for tokens, (pid, pname) in preachers_by_name.items():
            if tokens and tokens.issubset(s_tokens):
                specificity = len(tokens)
                if best is None or specificity > best[2]:
                    best = (pid, pname, specificity)
    return (best[0], best[1]) if best else None


def load_church_preachers(sb, preacher_id: str) -> tuple[Optional[str], str, dict[frozenset[str], tuple[str, str]]]:
    """Resolve church_id from a preacher_id, then load every preacher at
    that church into a dispatch map.

    Returns (church_id, primary_preacher_name, preachers_by_name) where
    preachers_by_name maps {frozenset(normalized name tokens) → (id, name)}.
    """
    pre = sb.table("preachers").select("church_id, name").eq("id", preacher_id).limit(1).execute()
    if not pre.data:
        return None, "", {}
    primary_name = pre.data[0].get("name") or ""
    church_id = pre.data[0].get("church_id")
    if not church_id:
        return None, primary_name, {}

    rows = sb.table("preachers").select("id, name").eq("church_id", church_id).execute().data or []
    by_name: dict[frozenset[str], tuple[str, str]] = {}
    for row in rows:
        tokens = frozenset(normalize_title(row.get("name") or "").split())
        if not tokens:
            continue
        # Last-write-wins on duplicate token sets — only matters for the
        # known Greg Dirnberger / Steve Whitacre name collisions, both of
        # whom belong to different churches anyway.
        by_name[tokens] = (row["id"], row.get("name") or "")
    return church_id, primary_name, by_name


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
    ap.add_argument("--preacher", required=True, help="Entry point preacher_id; church is resolved from this. Default is whole-church dispatch (every preacher at the church). Use --single-preacher for legacy single-target behavior.")
    ap.add_argument("--host", required=True, help="e.g. https://www.crossofgrace.net")
    ap.add_argument("--engine-id", required=True, help="Nucleus sermon-hub engine ID")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument(
        "--no-insert",
        action="store_true",
        help="Legacy behavior: log unmatched items, do not INSERT new rows. "
             "Default is to insert.",
    )
    ap.add_argument(
        "--single-preacher",
        action="store_true",
        help="Legacy single-preacher gate: only match the --preacher; skip "
             "items spoken by anyone else. Default is whole-church dispatch: "
             "route each item to the matching preacher_id at the church.",
    )
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()

    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or os.environ.get("SUPABASE_KEY")
    if not url or not key:
        print("ERROR: SUPABASE_URL / SUPABASE_KEY missing in env", file=sys.stderr)
        return 2
    sb = create_client(url, key)

    # Resolve church + load every preacher at the church for whole-church
    # dispatch. The --preacher arg is just the entry point — used to find
    # the church_id. From there we route by speaker, not by single target.
    church_id, target_preacher_name, preachers_by_name = load_church_preachers(
        sb, args.preacher
    )
    if not target_preacher_name:
        print(f"  [error] could not resolve target preacher name for id={args.preacher}; refusing to run")
        return 2
    if not church_id:
        print(f"  [error] preacher {args.preacher} has no church_id; refusing to run")
        return 2

    # Resolve church_slug for R2 mirror keys.
    church_slug: Optional[str] = None
    ch = sb.table("churches").select("slug").eq("id", church_id).limit(1).execute()
    if ch.data:
        church_slug = ch.data[0].get("slug")
    if not church_slug:
        print("  [warn] no church_slug for this church; R2 mirror will be skipped")

    if args.single_preacher:
        print(f"  --single-preacher mode: only matching {target_preacher_name!r}; "
              f"all other CoG preachers' sermons will be SKIPPED")
    else:
        n_preachers = len(preachers_by_name)
        print(f"  whole-church dispatch: {n_preachers} preachers loaded at the church; "
              f"each item routed to its matching preacher_id")

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
              "skipped_unknown_speaker": 0,
              "fetch_error": 0, "mirrored": 0, "mirror_skipped": 0, "mirror_failed": 0}
    by_method: dict[str, int] = {}
    by_routed_preacher: dict[str, int] = {}
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

        # ─── Dispatch by speaker ─────────────────────────────────────────
        # Default: whole-church — route to whichever preacher_id at the
        # church the speakers list matches. Falls through to skip-and-log
        # if no preacher matches (truly unknown speaker, e.g. outside
        # guest with no profile yet).
        # --single-preacher: legacy gate — only the entry-point preacher
        # is allowed; everyone else is skipped.
        if args.single_preacher:
            if not speaker_matches_target(item.speakers, target_preacher_name):
                counts["skipped_unknown_speaker"] += 1
                continue
            routed_preacher_id = args.preacher
            routed_preacher_name = target_preacher_name
        else:
            match = dispatch_speaker_to_preacher(item.speakers, preachers_by_name)
            if match is None:
                counts["skipped_unknown_speaker"] += 1
                if item.speakers:
                    print(f"  [{i}/{len(sermons)}] no preacher_id for speakers={item.speakers!r} — skipping")
                continue
            routed_preacher_id, routed_preacher_name = match

        by_routed_preacher[routed_preacher_name] = by_routed_preacher.get(routed_preacher_name, 0) + 1

        row, method = find_match(sb, routed_preacher_id, item)
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
                "preacher_id": routed_preacher_id,
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
                    f"{item.title[:55]} → {routed_preacher_name}  slug={new_slug}"
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
    print(f"  Unknown speaker (skipped):  {counts['skipped_unknown_speaker']}")
    print(f"  {'Would update' if args.dry_run else 'Updated'}:                  {counts['updated']}")
    print(f"  {'Would insert' if args.dry_run else 'Inserted'}:                 {counts['inserted']}")
    print(f"  Mirrored to R2:             {counts['mirrored']}")
    print(f"  Mirror skipped (had URL):   {counts['mirror_skipped']}")
    print(f"  Mirror failed:              {counts['mirror_failed']}")
    print(f"  Unmatched & not inserted:   {counts['no_match']}")
    print(f"  No audio source:            {counts['no_audio']}")
    print(f"  Fetch errors:               {counts['fetch_error']}")
    print()
    print("Routed to preacher (whole-church dispatch):")
    for name, c in sorted(by_routed_preacher.items(), key=lambda x: -x[1]):
        print(f"  {name:30s}  {c}")
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
