"""
One-shot slug backfill for existing churches and sermons.

Run once after the sermon_page_renderer schema migration. Idempotent —
only updates rows where slug IS NULL.

Usage:
    python scripts/backfill_slugs.py
    python scripts/backfill_slugs.py --dry-run
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import date as date_type
from pathlib import Path
from typing import Optional

# Make the sibling sermon_page_renderer package importable when this script
# is invoked as `python scripts/backfill_slugs.py` from the repo root.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
from supabase import Client, create_client

from sermon_page_renderer.slug import church_slug, sermon_slug, uniquify_slug

load_dotenv(override=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("backfill_slugs")


def get_supabase() -> Client:
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_KEY")
    if not url or not key:
        raise EnvironmentError("SUPABASE_URL and SUPABASE_KEY must be set")
    return create_client(url, key)


def _parse_date(value: Optional[str]) -> Optional[date_type]:
    if not value:
        return None
    try:
        return date_type.fromisoformat(value)
    except (ValueError, TypeError):
        return None


def backfill_churches(sb: Client, dry_run: bool) -> int:
    rows = sb.table("churches").select("id,name,slug").execute().data or []
    existing_slugs: set[str] = {r["slug"] for r in rows if r.get("slug")}
    needs_update = [r for r in rows if not r.get("slug")]

    log.info(f"Churches: {len(rows)} total, {len(needs_update)} need slugs")
    updated = 0
    for row in needs_update:
        base = church_slug(row["name"] or "")
        if not base:
            log.warning(f"  church {row['id']} has no name-derived slug — skipping")
            continue
        new_slug = uniquify_slug(base, existing_slugs)
        existing_slugs.add(new_slug)
        log.info(f"  {row['name']!r} → {new_slug}")
        if not dry_run:
            sb.table("churches").update({"slug": new_slug}).eq("id", row["id"]).execute()
        updated += 1
    return updated


def backfill_sermons(sb: Client, dry_run: bool) -> int:
    """
    Per-preacher slug uniqueness. We fetch all sermons and group by preacher_id
    so collision detection runs against existing peers for that preacher only.
    """
    # Page through sermons (Supabase's default limit is 1000)
    all_rows: list[dict] = []
    offset = 0
    page_size = 1000
    while True:
        page = (
            sb.table("sermons")
            .select("id,preacher_id,title,date,slug")
            .order("created_at")
            .range(offset, offset + page_size - 1)
            .execute()
            .data
            or []
        )
        if not page:
            break
        all_rows.extend(page)
        if len(page) < page_size:
            break
        offset += page_size

    log.info(f"Sermons: {len(all_rows)} total")

    # Per-preacher existing-slug set
    existing_by_preacher: dict[str, set[str]] = {}
    for r in all_rows:
        if r.get("slug"):
            existing_by_preacher.setdefault(r["preacher_id"], set()).add(r["slug"])

    needs_update = [r for r in all_rows if not r.get("slug")]
    log.info(f"  {len(needs_update)} sermons need slugs")

    updated = 0
    skipped = 0
    for row in needs_update:
        preacher_id = row["preacher_id"]
        title = row.get("title")
        sdate = _parse_date(row.get("date"))
        base = sermon_slug(title, sdate)
        if not base:
            log.warning(f"  sermon {row['id']} has no derivable slug — skipping")
            skipped += 1
            continue
        peer_slugs = existing_by_preacher.setdefault(preacher_id, set())
        new_slug = uniquify_slug(base, peer_slugs)
        peer_slugs.add(new_slug)
        if not dry_run:
            sb.table("sermons").update({"slug": new_slug}).eq("id", row["id"]).execute()
        updated += 1
        if updated % 100 == 0:
            log.info(f"  ... {updated}/{len(needs_update)} updated")

    log.info(f"  updated={updated} skipped={skipped}")
    return updated


def main():
    parser = argparse.ArgumentParser(description="Backfill slugs for churches and sermons.")
    parser.add_argument("--dry-run", action="store_true", help="Compute slugs, don't write.")
    args = parser.parse_args()

    sb = get_supabase()
    log.info("=" * 60)
    log.info(f"Slug backfill {'(dry run)' if args.dry_run else ''}")
    log.info("=" * 60)

    n_churches = backfill_churches(sb, args.dry_run)
    n_sermons = backfill_sermons(sb, args.dry_run)

    log.info("=" * 60)
    log.info(f"Done. churches: {n_churches}, sermons: {n_sermons}")


if __name__ == "__main__":
    main()
