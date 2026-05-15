"""
Shepherd's Guild — Sermon Page Renderer
========================================

Turns a Supabase sermon row into a deployable HTML page using the template
at templates/sermon_page.html.j2. Operates downstream of pipeline_batch.py,
so re-rendering against a new template costs $0 and does not touch the
Anthropic decomposition.

Usage:
  python generate_sermon_pages.py render <sermon_id>
  python generate_sermon_pages.py render-batch <batch_id>
  python generate_sermon_pages.py render-all                       # entire corpus
  python generate_sermon_pages.py render-all --preacher <preacher_id>
  python generate_sermon_pages.py render-all --church <church_id>
  python generate_sermon_pages.py render-stale                     # since last_rendered_at
  python generate_sermon_pages.py preview <sermon_id>              # stdout, no write

Global flags:
  --output-dir <path>     # default: ./output/sermon-pages/
  --dry-run               # log what would render, no writes
  --deploy                # invoke deploy adapter (V1: NotImplementedError stub)
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional

from dotenv import load_dotenv

from sermon_page_renderer import queries as q
from sermon_page_renderer.composer import compose
from sermon_page_renderer.template_engine import render_sermon_page

load_dotenv(override=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("generate_sermon_pages")

DEFAULT_OUTPUT_DIR = Path(__file__).parent / "output" / "sermon-pages"


# ---------------------------------------------------------------------------
# Output path resolution
# ---------------------------------------------------------------------------

def _output_path(output_dir: Path, sermon: dict, slug: str) -> Path:
    """
    output/sermon-pages/<church-slug>/<year>/<month>/<sermon-slug>.html
    Falls back to a flat layout if the sermon has no date.
    """
    church = (sermon.get("preachers") or {}).get("churches") or {}
    church_slug_value = church.get("slug") or "unknown-church"
    date_str = sermon.get("date")
    if date_str:
        year = date_str[:4]
        month = date_str[5:7]
        return output_dir / church_slug_value / year / month / f"{slug}.html"
    return output_dir / church_slug_value / "undated" / f"{slug}.html"


# ---------------------------------------------------------------------------
# Render one sermon (the core operation)
# ---------------------------------------------------------------------------

def render_one(
    sermon_id: str,
    output_dir: Path,
    *,
    dry_run: bool = False,
    stamp_last_rendered: bool = True,
) -> Optional[Path]:
    """Render a single sermon. Returns the output path (None on dry-run)."""
    raw_sermon = q.get_sermon(sermon_id)
    if not raw_sermon:
        raise ValueError(f"Sermon not found: {sermon_id}")

    slug = raw_sermon.get("slug") or sermon_id
    out_path = _output_path(output_dir, raw_sermon, slug)

    if dry_run:
        log.info(
            f"[dry-run] would render {sermon_id} → {out_path.relative_to(output_dir.parent)}"
        )
        return None

    context = compose(sermon_id)
    html = render_sermon_page(context)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html, encoding="utf-8")
    log.info(f"rendered {sermon_id} → {out_path}")

    if stamp_last_rendered:
        try:
            q.get_supabase().table("sermons").update(
                {"last_rendered_at": datetime.now(timezone.utc).isoformat()}
            ).eq("id", sermon_id).execute()
        except Exception as exc:
            log.warning(f"  could not stamp last_rendered_at for {sermon_id}: {exc}")

    return out_path


# ---------------------------------------------------------------------------
# Render-many strategies
# ---------------------------------------------------------------------------

def _all_sermon_ids(
    *,
    preacher_id: Optional[str] = None,
    church_id: Optional[str] = None,
) -> list[str]:
    sb = q.get_supabase()
    base = sb.table("sermons").select("id", count="exact")
    if preacher_id:
        base = base.eq("preacher_id", preacher_id)
    if church_id:
        # Filter via the preacher → church join.
        prs = (
            sb.table("preachers").select("id").eq("church_id", church_id).execute().data or []
        )
        prs_ids = [r["id"] for r in prs]
        if not prs_ids:
            return []
        base = base.in_("preacher_id", prs_ids)
    base = base.order("created_at")

    ids: list[str] = []
    offset = 0
    page = 1000
    while True:
        rows = base.range(offset, offset + page - 1).execute().data or []
        if not rows:
            break
        ids.extend(r["id"] for r in rows)
        if len(rows) < page:
            break
        offset += page
    return ids


def _stale_sermon_ids() -> list[str]:
    """
    Sermons needing re-render: last_rendered_at IS NULL, or related rows updated since.
    For V1, we use the simpler `last_rendered_at IS NULL OR updated_at > last_rendered_at`
    check on the sermon row — the units/citations cascade is captured by re-running
    after every pipeline_batch.py ingest.
    """
    sb = q.get_supabase()
    rows = (
        sb.table("sermons")
        .select("id, updated_at, last_rendered_at")
        .order("created_at")
        .execute()
        .data
        or []
    )
    stale = []
    for r in rows:
        if not r.get("last_rendered_at"):
            stale.append(r["id"])
        elif r.get("updated_at") and r["updated_at"] > r["last_rendered_at"]:
            stale.append(r["id"])
    return stale


def _ingested_in_batch(batch_id: str) -> list[str]:
    """
    Pull sermon IDs out of the batch report JSON at output/batches/<batch_id>_report.json
    (written by pipeline_batch.py process). Falls back to empty list when the report
    is absent.
    """
    report = Path(__file__).parent / "output" / "batches" / f"{batch_id}_report.json"
    if not report.exists():
        log.warning(f"No batch report at {report}")
        return []
    data = json.loads(report.read_text(encoding="utf-8"))
    return [r["sermon_id"] for r in data.get("results", []) if r.get("sermon_id")]


def _dry_run_many(sermon_ids: list[str], output_dir: Path) -> tuple[int, int]:
    """
    Fast dry-run path. Bulk-fetches sermons + preacher.church_slug in paged
    queries, then computes output paths locally. Avoids ~1s/sermon serial
    round-trips that the full per-sermon `render_one` would incur.
    """
    sb = q.get_supabase()

    # Bulk fetch (id, slug, date, preacher.church_id) for every requested ID.
    # PostgREST's .in_() filter caps at ~1000 IDs per call, so we chunk.
    chunk = 500
    rows_by_id: dict[str, dict] = {}
    for i in range(0, len(sermon_ids), chunk):
        batch = sermon_ids[i:i + chunk]
        result = (
            sb.table("sermons")
            .select("id, slug, date, preacher_id")
            .in_("id", batch)
            .execute()
        )
        for r in result.data or []:
            rows_by_id[r["id"]] = r

    # Resolve church_slug for each distinct preacher_id seen.
    preacher_ids = {r["preacher_id"] for r in rows_by_id.values() if r.get("preacher_id")}
    church_slug_by_preacher: dict[str, str] = {}
    if preacher_ids:
        preacher_rows = (
            sb.table("preachers")
            .select("id, churches(slug)")
            .in_("id", list(preacher_ids))
            .execute()
            .data or []
        )
        for p in preacher_rows:
            ch = p.get("churches") or {}
            church_slug_by_preacher[p["id"]] = ch.get("slug") or "unknown-church"

    succeeded = 0
    failed = 0
    for sid in sermon_ids:
        row = rows_by_id.get(sid)
        if not row:
            log.error(f"  missing sermon row for {sid}")
            failed += 1
            continue
        slug = row.get("slug") or sid
        # Build a minimal sermon dict shaped the way _output_path expects.
        synthetic = {
            "date": row.get("date"),
            "preachers": {
                "churches": {
                    "slug": church_slug_by_preacher.get(row.get("preacher_id"), "unknown-church")
                }
            },
        }
        out_path = _output_path(output_dir, synthetic, slug)
        try:
            log.info(
                f"[dry-run] would render {sid} → {out_path.relative_to(output_dir.parent)}"
            )
            succeeded += 1
        except Exception as exc:
            log.error(f"[dry-run] FAILED {sid}: {exc}")
            failed += 1
    return succeeded, failed


def render_many(
    sermon_ids: Iterable[str],
    output_dir: Path,
    *,
    dry_run: bool = False,
    deploy: bool = False,
) -> tuple[int, int]:
    ids = list(sermon_ids)
    log.info(f"Rendering {len(ids)} sermon(s) → {output_dir}")

    if dry_run:
        succeeded, failed = _dry_run_many(ids, output_dir)
    else:
        succeeded = 0
        failed = 0
        for i, sid in enumerate(ids, 1):
            try:
                render_one(sid, output_dir, dry_run=False)
                succeeded += 1
            except Exception as exc:
                log.error(f"[{i}/{len(ids)}] FAILED {sid}: {exc}")
                failed += 1

    if deploy and not dry_run:
        log.warning("--deploy requested but no adapter is implemented in V1 — skipping.")
    log.info(f"Done. succeeded={succeeded} failed={failed}")
    return succeeded, failed


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Shepherd's Guild — sermon page renderer"
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Output directory for generated HTML (default: ./output/sermon-pages/)",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Log what would render, no writes"
    )
    parser.add_argument(
        "--deploy", action="store_true",
        help="Invoke deploy adapter after render (V1: not implemented)",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    p_render = subparsers.add_parser("render", help="Render one sermon by UUID")
    p_render.add_argument("sermon_id", type=str)

    p_batch = subparsers.add_parser(
        "render-batch",
        help="Render every sermon ingested in an Anthropic batch (via its report JSON)",
    )
    p_batch.add_argument("batch_id", type=str)

    p_all = subparsers.add_parser("render-all", help="Render multiple sermons")
    p_all.add_argument("--preacher", dest="preacher_id", help="Filter to a preacher UUID")
    p_all.add_argument("--church", dest="church_id", help="Filter to a church UUID")

    subparsers.add_parser(
        "render-stale", help="Render sermons updated since last_rendered_at"
    )

    p_preview = subparsers.add_parser("preview", help="Render to stdout, no write")
    p_preview.add_argument("sermon_id", type=str)

    args = parser.parse_args()

    if args.command == "render":
        out_path = render_one(args.sermon_id, args.output_dir, dry_run=args.dry_run)
        if out_path and args.deploy:
            log.warning("--deploy requested but no adapter is implemented in V1 — skipping.")

    elif args.command == "render-batch":
        ids = _ingested_in_batch(args.batch_id)
        if not ids:
            log.error("No sermon IDs found for batch — aborting.")
            sys.exit(1)
        render_many(ids, args.output_dir, dry_run=args.dry_run, deploy=args.deploy)

    elif args.command == "render-all":
        ids = _all_sermon_ids(
            preacher_id=args.preacher_id, church_id=args.church_id
        )
        if not ids:
            log.error("No sermons matched — aborting.")
            sys.exit(1)
        render_many(ids, args.output_dir, dry_run=args.dry_run, deploy=args.deploy)

    elif args.command == "render-stale":
        ids = _stale_sermon_ids()
        if not ids:
            log.info("No stale sermons. Nothing to do.")
            return
        render_many(ids, args.output_dir, dry_run=args.dry_run, deploy=args.deploy)

    elif args.command == "preview":
        context = compose(args.sermon_id)
        html = render_sermon_page(context)
        sys.stdout.write(html)


if __name__ == "__main__":
    main()
