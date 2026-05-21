"""
backfill_hosted_audio.py
─────────────────────────────────────────────────────────────────────────────
One-shot (and idempotent) backfill of sermons.hosted_audio_url for a preacher.

For each sermon WHERE hosted_audio_url IS NULL AND audio_url IS NOT NULL,
download the audio from audio_url and mirror it to R2 at
  <church_slug>/<sermon_slug>.mp3
then set hosted_audio_url to the stable sermons-cdn.sermonsteward.com URL.

Customers like Cross of Grace serve signed S3 URLs that expire ~24h after
fetch — so the script supports refreshing source URLs first by re-running the
preacher's ingest adapter (Nucleus or YASH). The adapter itself now also
mirrors as it sweeps, so a refresh pass alone may already do the job; this
backfill catches any pending rows the adapter didn't touch.

Usage:
    python scripts/backfill_hosted_audio.py \
        --preacher ccb9e59c-bd20-414a-bd6b-25b117b8144c \
        [--refresh-via auto|nucleus|yash|none] \
        [--limit 50] \
        [--dry-run]

Re-running is safe: sermon_audio_host.mirror_sermon HEADs R2 before uploading,
so already-mirrored sermons are no-ops.
─────────────────────────────────────────────────────────────────────────────
"""
from __future__ import annotations

import argparse
import logging
import os
import subprocess
import sys
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
from supabase import create_client

import sermon_audio_host  # noqa: E402

load_dotenv(override=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("backfill_hosted_audio")

REPO_ROOT = Path(__file__).resolve().parent.parent


def supabase():
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or os.environ.get("SUPABASE_KEY")
    if not url or not key:
        log.error("SUPABASE_URL / SUPABASE_KEY missing in env")
        sys.exit(2)
    return create_client(url, key)


def resolve_church(sb, preacher_id: str) -> Optional[dict]:
    pre = sb.table("preachers").select("church_id").eq("id", preacher_id).limit(1).execute()
    if not pre.data or not pre.data[0].get("church_id"):
        return None
    ch = (
        sb.table("churches")
        .select("id, slug, ingest_source_type, audio_base_url, ingest_config")
        .eq("id", pre.data[0]["church_id"])
        .limit(1)
        .execute()
    )
    return ch.data[0] if ch.data else None


def refresh_source(preacher_id: str, church: dict, mode: str) -> None:
    """Re-run the ingest adapter as a subprocess so audio_url values are fresh."""
    src = church.get("ingest_source_type") if mode == "auto" else mode
    if src in (None, "none"):
        log.info("Skipping source refresh (mode=none)")
        return

    if src == "nucleus":
        cfg = church.get("ingest_config") or {}
        engine_id = cfg.get("engine_id") if isinstance(cfg, dict) else None
        host = church.get("audio_base_url")
        if not (engine_id and host):
            log.warning(f"Nucleus refresh skipped: missing engine_id or audio_base_url on church")
            return
        cmd = [
            sys.executable, str(REPO_ROOT / "sync_sermons_from_nucleus.py"),
            "--preacher", preacher_id,
            "--host", host,
            "--engine-id", engine_id,
        ]
    elif src == "yash" or src == "yash_html":
        host = church.get("audio_base_url")
        if not host:
            log.warning("YASH refresh skipped: missing audio_base_url on church")
            return
        cmd = [
            sys.executable, str(REPO_ROOT / "sync_sermons_from_yash.py"),
            "--preacher", preacher_id,
            "--host", host,
        ]
    else:
        log.warning(f"Unknown source refresh mode: {src}; skipping refresh")
        return

    log.info(f"Refreshing source URLs: {' '.join(cmd)}")
    r = subprocess.run(cmd, cwd=REPO_ROOT)
    if r.returncode != 0:
        log.warning(f"Source refresh exited with {r.returncode}; continuing to backfill pass")


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--preacher", required=True, help="preacher UUID")
    ap.add_argument(
        "--refresh-via",
        choices=["auto", "nucleus", "yash", "none"],
        default="auto",
        help="Re-run the ingest adapter first to refresh expiring signed URLs. "
             "'auto' uses the church row's ingest_source_type.",
    )
    ap.add_argument("--limit", type=int, default=None, help="cap rows processed")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if not sermon_audio_host.is_configured():
        log.error("R2 env vars missing. Set R2_ACCOUNT_ID, R2_ACCESS_KEY_ID, "
                  "R2_SECRET_ACCESS_KEY, R2_BUCKET, R2_PUBLIC_BASE.")
        return 2

    sb = supabase()
    church = resolve_church(sb, args.preacher)
    if not church:
        log.error(f"No church found for preacher {args.preacher}")
        return 2
    church_slug = church.get("slug")
    if not church_slug:
        log.error("Church has no slug; cannot mirror without a key prefix")
        return 2
    log.info(f"Target church: {church_slug}")

    if args.refresh_via != "none" and not args.dry_run:
        refresh_source(args.preacher, church, args.refresh_via)

    res = (
        sb.table("sermons")
        .select("id, slug, title, date, audio_url, hosted_audio_url")
        .eq("preacher_id", args.preacher)
        .is_("hosted_audio_url", "null")
        .not_.is_("audio_url", "null")
        .order("date", desc=True)
        .execute()
    )
    pending = res.data or []
    if args.limit:
        pending = pending[: args.limit]

    log.info(f"Pending sermons to mirror: {len(pending)}")
    if not pending:
        return 0

    n_ok = n_skip = n_fail = 0
    for i, s in enumerate(pending, 1):
        slug = s.get("slug")
        audio = s.get("audio_url")
        title = (s.get("title") or "")[:55]
        if not slug:
            log.warning(f"  [{i}/{len(pending)}] no slug; skipping  {title}")
            n_skip += 1
            continue
        if args.dry_run:
            log.info(f"  [{i}/{len(pending)}] WOULD MIRROR  {s.get('date')}  {title}")
            n_ok += 1
            continue

        try:
            hosted = sermon_audio_host.mirror_sermon(
                source_url=audio,
                church_slug=church_slug,
                sermon_slug=slug,
            )
        except Exception as e:
            log.warning(f"  [{i}/{len(pending)}] mirror error: {e}  {title}")
            n_fail += 1
            continue

        if not hosted:
            n_fail += 1
            log.warning(f"  [{i}/{len(pending)}] mirror failed  {title}")
            continue

        sb.table("sermons").update({"hosted_audio_url": hosted}).eq("id", s["id"]).execute()
        n_ok += 1
        if i % 10 == 0:
            log.info(f"  progress: {n_ok} mirrored, {n_fail} failed of {i}/{len(pending)}")

    log.info("─" * 60)
    log.info(f"Mirrored:  {n_ok}")
    log.info(f"Skipped:   {n_skip}")
    log.info(f"Failed:    {n_fail}")
    return 0 if n_fail == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
