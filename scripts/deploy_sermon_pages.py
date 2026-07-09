"""
deploy_sermon_pages.py
─────────────────────────────────────────────────────────────────────────────
Copy rendered sermon HTML from `output/sermon-pages/` into the
`sermon-steward` repo's per-church directories, regenerate the church
sermon-index pages, commit, and push.

This is Stage 8 of the canonical weekly pipeline (currently stubbed in
`weekly_ingest.py`). The cron prints "would push"; this script actually
pushes.

Selection modes (pick one):
    --sermon-ids <id1,id2,…>   Deploy these specific sermon UUIDs only.
    --since <YYYY-MM-DD>       Deploy any sermon whose last_rendered_at
                               is newer than this date.
    --since-last-commit        Deploy any sermon whose last_rendered_at
                               is newer than HEAD's committer date in the
                               sermon-steward repo.
    --all-stale                Deploy any sermon where the output HTML on
                               disk is newer than the deployed copy in
                               sermon-steward (or no deployed copy exists).

Safety flags:
    --dry-run                  Print what would be copied; no writes,
                               no commit, no push.
    --no-commit                Copy files but don't run git add/commit.
    --no-push                  Commit but don't push to origin/main.
    --no-deploy                Skip the eleventy build + wrangler deploy
                               (git only; page will NOT go live).
    --branch <name>            Commit + push to a feature branch instead
                               of main. Useful for review before promoting.

Usage:
    # The common case after a manual weekly_ingest run finishes:
    python scripts/deploy_sermon_pages.py --since 2026-06-08

    # Single-sermon redeploy (after fixing an artifact, say):
    python scripts/deploy_sermon_pages.py --sermon-ids 2c10bb3c-00e0-4405-a614-19d2b338fca8

    # Full reconciliation against on-disk state (slowest, safest):
    python scripts/deploy_sermon_pages.py --all-stale --dry-run

Environment:
    SUPABASE_URL + SUPABASE_SERVICE_ROLE_KEY (or SUPABASE_KEY).
─────────────────────────────────────────────────────────────────────────────
"""
from __future__ import annotations

import argparse
import logging
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
from supabase import create_client

load_dotenv(override=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("deploy_sermon_pages")

REPO_ROOT = Path(__file__).resolve().parent.parent
SOURCE_ROOT = REPO_ROOT / "output" / "sermon-pages"
SS_REPO = Path("/Users/dad/shepherds-guild/sermon-steward").resolve()

# Church-slug → sermon-steward per-church passthrough directory.
# Source of truth is eleventy.config.js's addPassthroughCopy() calls;
# kept in sync manually here. Adding a new church = adding a row to
# this dict + creating the directory in the sermon-steward repo.
CHURCH_DIR = {
    "providence-community-church": "ProvidenceLenexa",
    "cross-of-grace-church": "CoGElPaso",
}


def supabase():
    url = os.environ.get("SUPABASE_URL")
    key = (
        os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
        or os.environ.get("SUPABASE_KEY")
    )
    if not url or not key:
        log.error("SUPABASE_URL / SUPABASE_KEY missing in env")
        sys.exit(2)
    return create_client(url, key)


def _git(args: list[str], cwd: Path, check: bool = True) -> subprocess.CompletedProcess:
    r = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True)
    if check and r.returncode != 0:
        log.error(f"git {' '.join(args)} failed (exit {r.returncode}):\n{r.stderr.strip()}")
        sys.exit(1)
    return r


def ensure_ss_repo_clean(branch: Optional[str]) -> None:
    """Refuse to clobber an in-progress edit in the sermon-steward working tree."""
    if not SS_REPO.exists():
        log.error(f"sermon-steward repo not found at {SS_REPO}")
        sys.exit(2)
    if not (SS_REPO / ".git").exists():
        log.error(f"{SS_REPO} is not a git checkout")
        sys.exit(2)

    status = _git(["status", "--porcelain"], cwd=SS_REPO)
    if status.stdout.strip():
        log.error(
            f"sermon-steward repo has uncommitted changes:\n{status.stdout}\n"
            "Refusing to deploy on top of a dirty working tree."
        )
        sys.exit(1)

    # Make sure we're on the branch we're about to push to (or switch to it).
    target_branch = branch or "main"
    cur = _git(["branch", "--show-current"], cwd=SS_REPO).stdout.strip()
    if cur != target_branch:
        log.info(f"sermon-steward is on {cur}; switching to {target_branch}")
        _git(["checkout", target_branch], cwd=SS_REPO)


def resolve_sermons(
    sb, *, ids: list[str] | None, since: datetime | None, all_stale: bool
) -> list[dict]:
    """Fetch the sermon rows to be deployed based on the selected mode."""
    base = sb.table("sermons").select(
        "id, slug, title, date, last_rendered_at, "
        "preacher_id, preachers!inner(church_id, churches!inner(slug))"
    )

    if ids:
        res = base.in_("id", ids).execute()
        return res.data or []

    if since:
        res = base.gte("last_rendered_at", since.isoformat()).execute()
        return res.data or []

    if all_stale:
        # Pull all sermons with last_rendered_at set; we'll filter in
        # Python by comparing source mtime vs deploy mtime.
        res = base.not_.is_("last_rendered_at", "null").execute()
        return res.data or []

    return []


def source_path_for(sermon: dict) -> Optional[Path]:
    """Locate the rendered HTML in output/sermon-pages/ for a given sermon row.

    Layout that generate_sermon_pages.py actually produces:
        output/sermon-pages/<church-slug>/<YYYY>/<MM>/<slug>.html
    Undated sermons fall back to:
        output/sermon-pages/<church-slug>/undated/<slug>.html
    """
    church_slug = sermon["preachers"]["churches"]["slug"]
    slug = sermon.get("slug")
    date = sermon.get("date")
    if not slug:
        return None
    if date and len(date) >= 7:
        year_dir = date[:4]
        month_dir = date[5:7]
        return SOURCE_ROOT / church_slug / year_dir / month_dir / f"{slug}.html"
    return SOURCE_ROOT / church_slug / "undated" / f"{slug}.html"


def target_path_for(sermon: dict) -> Optional[Path]:
    """Where this sermon's HTML lives in the sermon-steward repo."""
    church_slug = sermon["preachers"]["churches"]["slug"]
    slug = sermon.get("slug")
    if not slug:
        return None
    if church_slug not in CHURCH_DIR:
        return None
    return SS_REPO / CHURCH_DIR[church_slug] / "sermons" / f"{slug}.html"


def filter_to_actually_changed(rows: list[dict]) -> list[dict]:
    """For --all-stale: keep only sermons whose source is newer than deploy."""
    keep: list[dict] = []
    for s in rows:
        src = source_path_for(s)
        tgt = target_path_for(s)
        if not src or not tgt:
            continue
        if not src.exists():
            continue
        if not tgt.exists():
            keep.append(s)
            continue
        if src.stat().st_mtime > tgt.stat().st_mtime:
            keep.append(s)
    return keep


def copy_and_collect(sermons: list[dict], dry_run: bool) -> tuple[list[Path], list[dict]]:
    """Copy each sermon's HTML into sermon-steward; return (paths_touched, skipped)."""
    paths_touched: list[Path] = []
    skipped: list[dict] = []
    for s in sermons:
        src = source_path_for(s)
        tgt = target_path_for(s)
        title = (s.get("title") or "")[:50]
        if not src:
            log.warning(f"  skip (no slug): {title}")
            skipped.append(s)
            continue
        if not src.exists():
            log.warning(f"  skip (no source HTML on disk): {title}  ({src})")
            skipped.append(s)
            continue
        if not tgt:
            log.warning(f"  skip (unknown church → dir mapping): {title}")
            skipped.append(s)
            continue
        if dry_run:
            log.info(f"  WOULD COPY  {src.relative_to(REPO_ROOT)} → {tgt.relative_to(SS_REPO)}")
            paths_touched.append(tgt)
            continue
        tgt.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, tgt)
        log.info(f"  copied      {tgt.relative_to(SS_REPO)}")
        paths_touched.append(tgt)
    return paths_touched, skipped


def rebuild_church_indexes(dry_run: bool) -> None:
    """Re-run build_church_indexes.py so the listings reflect the new pages."""
    cmd = [sys.executable, str(REPO_ROOT / "scripts" / "build_church_indexes.py")]
    if dry_run:
        log.info(f"  WOULD RUN   {' '.join(cmd)}")
        return
    log.info(f"  rebuilding church index pages …")
    r = subprocess.run(cmd, cwd=REPO_ROOT)
    if r.returncode != 0:
        log.warning(f"  build_church_indexes.py exited with {r.returncode} — continuing")


def commit_and_push(
    paths_touched: list[Path],
    message: str,
    branch: str,
    dry_run: bool,
    no_commit: bool,
    no_push: bool,
) -> None:
    if dry_run or no_commit:
        log.info(f"  WOULD commit {len(paths_touched)} paths and {'push' if not no_push else 'skip push'}")
        return
    rels = sorted({str(p.relative_to(SS_REPO)) for p in paths_touched})
    # Also include index/listing pages that build_church_indexes might have touched.
    # Pass through to git add: tell it to pick up any modifications in the church dirs.
    add_args = ["add", *rels]
    for d in CHURCH_DIR.values():
        add_args.append(d)
    _git(add_args, cwd=SS_REPO, check=False)
    status = _git(["status", "--porcelain"], cwd=SS_REPO).stdout
    if not status.strip():
        log.info("  nothing staged to commit (target files were unchanged)")
        return
    _git(["commit", "-m", message], cwd=SS_REPO)
    log.info(f"  committed {len(paths_touched)} file(s) on {branch}")
    if no_push:
        log.info("  --no-push set; leaving local commit unpushed")
        return
    _git(["push", "origin", branch], cwd=SS_REPO)
    log.info(f"  pushed to origin/{branch}")


def build_and_deploy(dry_run: bool, no_deploy: bool) -> None:
    """Actually publish the site: build Eleventy → _site, then `wrangler deploy`.

    The git push alone does NOT make changes live — sermonsteward.com is a
    Cloudflare Worker whose git-connected build has proven unreliable — so we
    build and deploy directly. This is the step that guarantees the page is live.
    """
    if no_deploy:
        log.info("  --no-deploy set; skipping build + wrangler deploy (page NOT published)")
        return
    if dry_run:
        log.info("  WOULD build (eleventy) + wrangler deploy")
        return
    log.info("  building site (eleventy) …")
    b = subprocess.run(["npm", "run", "build"], cwd=str(SS_REPO), capture_output=True, text=True)
    if b.returncode != 0:
        log.error(f"  eleventy build failed — page NOT published: {b.stderr[-400:]}")
        return
    log.info("  publishing via wrangler deploy …")
    w = subprocess.run(["npx", "wrangler", "deploy"], cwd=str(SS_REPO), capture_output=True, text=True)
    out = (w.stdout or "") + (w.stderr or "")
    if w.returncode != 0:
        log.error(f"  wrangler deploy failed — page NOT published: {out[-400:]}")
        return
    for line in out.splitlines():
        if "Version ID" in line or "Deployed" in line or "Success!" in line:
            log.info(f"    {line.strip()}")
    log.info("  published live via wrangler deploy")


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--sermon-ids", help="Comma-separated sermon UUIDs to deploy")
    mode.add_argument("--since", help="Deploy any sermon with last_rendered_at >= this YYYY-MM-DD")
    mode.add_argument(
        "--since-last-commit",
        action="store_true",
        help="Deploy any sermon rendered since the sermon-steward repo's HEAD commit time",
    )
    mode.add_argument(
        "--all-stale",
        action="store_true",
        help="Deploy any sermon whose output/ HTML is newer than the deployed copy",
    )

    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-commit", action="store_true")
    ap.add_argument("--no-push", action="store_true")
    ap.add_argument("--no-deploy", action="store_true",
                    help="Skip the eleventy build + wrangler deploy (git only; page will NOT go live)")
    ap.add_argument("--branch", default="main", help="Branch in sermon-steward to push to (default: main)")
    ap.add_argument(
        "--message",
        default=None,
        help="Commit message. Default: 'Deploy N sermon page(s) — <iso-date>'.",
    )
    args = ap.parse_args()

    ensure_ss_repo_clean(args.branch)
    sb = supabase()

    # Resolve sermon selection
    ids: list[str] | None = None
    since: datetime | None = None
    if args.sermon_ids:
        ids = [s.strip() for s in args.sermon_ids.split(",") if s.strip()]
        log.info(f"Selection: {len(ids)} sermon ID(s) explicitly listed")
    elif args.since:
        since = datetime.fromisoformat(args.since)
        log.info(f"Selection: sermons with last_rendered_at >= {since.isoformat()}")
    elif args.since_last_commit:
        head_time = _git(["log", "-1", "--format=%cI"], cwd=SS_REPO).stdout.strip()
        if not head_time:
            log.error("Could not read sermon-steward HEAD commit time")
            return 2
        since = datetime.fromisoformat(head_time.replace("Z", "+00:00"))
        log.info(f"Selection: sermons rendered since SS-repo HEAD ({since.isoformat()})")

    sermons = resolve_sermons(sb, ids=ids, since=since, all_stale=args.all_stale)
    if args.all_stale:
        sermons = filter_to_actually_changed(sermons)
        log.info(f"  {len(sermons)} sermon(s) with source-newer-than-deploy")
    else:
        log.info(f"  {len(sermons)} sermon(s) matched the selection")

    if not sermons:
        log.info("Nothing to deploy. Exiting.")
        return 0

    paths_touched, skipped = copy_and_collect(sermons, dry_run=args.dry_run)
    log.info(f"Copied {len(paths_touched)} file(s); {len(skipped)} skipped")

    rebuild_church_indexes(dry_run=args.dry_run)

    if not paths_touched:
        log.info("No files were copied; nothing to commit.")
        return 0

    message = args.message or (
        f"Deploy {len(paths_touched)} sermon page(s) — "
        f"{datetime.now().date().isoformat()}"
    )
    commit_and_push(
        paths_touched=paths_touched,
        message=message,
        branch=args.branch,
        dry_run=args.dry_run,
        no_commit=args.no_commit,
        no_push=args.no_push,
    )

    # Publish for real: the git push above does not deploy the Cloudflare Worker.
    # This build + wrangler deploy is what makes the page(s) actually go live.
    build_and_deploy(dry_run=args.dry_run, no_deploy=args.no_deploy)

    log.info("Done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
