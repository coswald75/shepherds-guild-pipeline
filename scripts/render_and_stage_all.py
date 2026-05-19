"""
One-off driver: render all artifacted PCC + COG sermons against the new URL
shape, stage them into the sermon-steward repo, ready for a single commit/push.

Usage:
  python3 scripts/render_and_stage_all.py [--no-stage]

Prints a tab-separated summary to stdout. Slow renders (statement-timeout on
canonical-neighbors) auto-retry once.
"""

from __future__ import annotations

import argparse
import sys
import time
import traceback
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(REPO_ROOT / ".env", override=True)

from generate_sermon_pages import render_one, DEFAULT_OUTPUT_DIR  # noqa: E402
from sermon_page_renderer import queries as q  # noqa: E402
from sermon_page_renderer.deploy import CloudflarePagesAdapter  # noqa: E402

SERMON_STEWARD_REPO = Path("/Users/dad/shepherds-guild/sermon-steward")


def get_deploy_eligible_ids() -> list[str]:
    sb = q.get_supabase()
    chris = "9c6f8d69-de55-45db-ac60-0fe6d0cfff59"
    ricky = "ccb9e59c-bd20-414a-bd6b-25b117b8144c"
    sermons = (
        sb.table("sermons")
        .select("id, date, preacher_id, slug, main_thesis")
        .in_("preacher_id", [chris, ricky])
        .not_.is_("main_thesis", "null")
        .not_.is_("date", "null")
        .not_.is_("slug", "null")
        .order("date")
        .execute()
        .data
        or []
    )
    candidate_ids = [s["id"] for s in sermons]
    artifacts = (
        sb.table("sermon_artifacts")
        .select("sermon_id, artifact_type")
        .in_("sermon_id", candidate_ids)
        .execute()
        .data
        or []
    )
    bundle_counts: dict[str, set[str]] = {}
    for row in artifacts:
        bundle_counts.setdefault(row["sermon_id"], set()).add(row["artifact_type"])
    return [sid for sid in candidate_ids if len(bundle_counts.get(sid, set())) == 6]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--no-stage",
        action="store_true",
        help="Render only; skip staging into sermon-steward repo",
    )
    args = ap.parse_args()

    ids = get_deploy_eligible_ids()
    print(f"# {len(ids)} deploy-eligible sermons", flush=True)

    adapter = (
        None if args.no_stage else CloudflarePagesAdapter(SERMON_STEWARD_REPO)
    )

    rendered = 0
    staged = 0
    failed: list[tuple[str, str]] = []
    t0 = time.time()

    for i, sid in enumerate(ids, 1):
        for attempt in (1, 2, 3):
            try:
                out_path = render_one(sid, DEFAULT_OUTPUT_DIR)
                break
            except Exception as exc:
                if attempt == 3:
                    failed.append((sid, str(exc)))
                    out_path = None
                    break
                time.sleep(2)
                continue
        if out_path is None:
            print(f"  [{i:>3}/{len(ids)}] {sid[:8]}  FAILED", flush=True)
            continue
        rendered += 1
        if adapter:
            try:
                rel = out_path.relative_to(DEFAULT_OUTPUT_DIR)
                url_path = "/" + str(rel.with_suffix(""))
                adapter.stage(out_path, url_path)
                staged += 1
            except Exception as exc:
                failed.append((sid, f"stage: {exc}"))
        if i % 10 == 0 or i == len(ids):
            elapsed = time.time() - t0
            print(
                f"  [{i:>3}/{len(ids)}] rendered={rendered} staged={staged} "
                f"failed={len(failed)} elapsed={elapsed:.0f}s",
                flush=True,
            )

    elapsed = time.time() - t0
    print(
        f"\nDone in {elapsed:.0f}s: rendered={rendered} staged={staged} failed={len(failed)}"
    )
    if failed:
        print("\nFailures:")
        for sid, reason in failed:
            print(f"  {sid}: {reason}")
    if adapter:
        print(f"\n{staged} files now staged in {SERMON_STEWARD_REPO} for commit/push.")
    return 0 if not failed else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        traceback.print_exc()
        sys.exit(2)
