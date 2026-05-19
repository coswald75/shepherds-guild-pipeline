"""
weekly_ingest.py — Sunday-evening cron orchestrator.
─────────────────────────────────────────────────────────────────────────────
For every customer with `churches.auto_publish = true`, walks the full
Sunday-evening cadence:

  1. DISCOVER   pull new sermons from each customer's host
                (rss + yash_html implemented; others TODO)
  2. TRANSCRIBE for sermons missing transcripts, queue for AssemblyAI
                (currently stubbed — relies on RSS-provided transcripts)
  3. DECOMPOSE  submit one Anthropic Batch with all customers' new sermons
                using pipeline_batch.py submit
  4. WAIT       poll until batch completes (max 24h, typical 1-2h)
  5. PROCESS    parse batch results → embed → ingest to Supabase
                using pipeline_batch.py process
  6. ARTIFACTS  Haiku 4.5 — 6 calls per newly-ingested sermon
                using generate_artifacts.py
  7. RENDER     Jinja2 → HTML per sermon
                using generate_sermon_pages.py
  8. DEPLOY     push HTML to each customer's Cloudflare Worker
                (currently stubbed — prints what would deploy)

Each stage is idempotent: re-running picks up where it left off. The cron
intentionally runs twice — Sunday 7pm primary + Monday 7am --catchup — to
catch customers who upload late.

Usage:
    python weekly_ingest.py weekly                 # full cadence, blocking
    python weekly_ingest.py weekly --catchup       # second-pass mode
    python weekly_ingest.py discover --dry-run     # just print what's new
    python weekly_ingest.py process <batch_id>     # process a known batch

Environment (per CLAUDE.md):
    ANTHROPIC_API_KEY, SUPABASE_URL, SUPABASE_KEY, VOYAGE_API_KEY
─────────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

load_dotenv(override=True)

try:
    from supabase import Client, create_client
except ImportError:
    print("pip install supabase", file=sys.stderr)
    sys.exit(1)


REPO_ROOT = Path(__file__).resolve().parent
LOG_DIR = REPO_ROOT / "logs"
LOG_DIR.mkdir(exist_ok=True)
QUEUE_DIR = REPO_ROOT / "weekly_queue"
QUEUE_DIR.mkdir(exist_ok=True)

ARTIFACT_TYPES = (
    # The original 6 — member-facing pastoral cards rendered on the main page.
    "small_group_questions", "daily_readings", "prayer_prompt",
    "family_card", "couples_guide", "memory_verse",
    # Imperatives + indicatives — structural analysis rendered as a card on
    # the main page. Haiku, voice-prompted like the other 6.
    "imperatives_indicatives",
    # Sermon scraps — separate companion page (/<slug>/scraps). Sonnet 4.6,
    # no voice prompt. ~$0.14 per call. See sermon_artifacts/prompts/sermon_scraps.md.
    "sermon_scraps",
)

BATCH_POLL_SECONDS = 60
BATCH_MAX_WAIT_HOURS = 24

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("weekly_ingest")


# ────────────────────────────────────────────────────────────────────────────
# Supabase
# ────────────────────────────────────────────────────────────────────────────

_sb: Optional[Client] = None


def supabase() -> Client:
    global _sb
    if _sb is None:
        url = os.environ.get("SUPABASE_URL")
        key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or os.environ.get("SUPABASE_KEY")
        if not url or not key:
            raise RuntimeError("SUPABASE_URL / SUPABASE_KEY missing in env")
        _sb = create_client(url, key)
    return _sb


@dataclass
class Customer:
    church_id: str
    church_name: str
    church_slug: str
    preacher_id: str
    preacher_name: str
    ingest_source_type: str
    podcast_feed_url: Optional[str]
    audio_base_url: Optional[str]
    deploy_target: Optional[dict]


def active_customers() -> list[Customer]:
    """All churches flagged auto_publish=true, joined to their primary preacher."""
    sb = supabase()
    res = sb.table("churches").select(
        "id, name, slug, audio_base_url, podcast_feed_url, ingest_source_type, deploy_target"
    ).eq("auto_publish", True).execute()
    customers: list[Customer] = []
    for c in res.data or []:
        # Find the church's primary preacher (the one with the most sermons)
        pres = sb.rpc("primary_preacher_for_church", {"p_church_id": c["id"]}).execute() \
            if False else None  # placeholder for a future RPC
        # Fallback: pick any preacher row tied to this church via sermons
        # (Supabase schema joins via sermons.preacher_id; preachers don't have church_id)
        # For now, assume there's a 1:1 — find the preacher with the most sermons whose
        # sermon rows reference this church's audio_base_url or similar. This is a hack;
        # the proper fix is to add `preachers.primary_church_id`.
        # For the charter cohort, we hardcode the mapping below.
        pid_map = {
            "c121e66b-777d-4568-89d3-9ceea258061b": (  # Providence Community Church
                "9c6f8d69-de55-45db-ac60-0fe6d0cfff59", "Chris Oswald"
            ),
            "f1fc9898-fafd-4289-b6af-ce99dfde23d6": (  # Cross of Grace (El Paso, Nucleus)
                "ccb9e59c-bd20-414a-bd6b-25b117b8144c", "Ricky Alcantar"
            ),
        }
        if c["id"] not in pid_map:
            log.warning(f"no preacher mapping for church {c['id']} ({c['name']}); skipping")
            continue
        pid, pname = pid_map[c["id"]]
        customers.append(Customer(
            church_id=c["id"], church_name=c["name"], church_slug=c.get("slug") or "",
            preacher_id=pid, preacher_name=pname,
            ingest_source_type=c.get("ingest_source_type") or "",
            podcast_feed_url=c.get("podcast_feed_url"),
            audio_base_url=c.get("audio_base_url"),
            deploy_target=c.get("deploy_target"),
        ))
    return customers


# ────────────────────────────────────────────────────────────────────────────
# Stage 1 — Discover
# ────────────────────────────────────────────────────────────────────────────

def discover_new_for_customer(customer: Customer, dry_run: bool) -> int:
    """Run the per-host adapter for this customer. Returns count of new audio_urls set."""
    log.info(f"[discover] {customer.church_name} ({customer.ingest_source_type})")

    # Snapshot current state so we can count what was newly populated
    sb = supabase()
    before = sb.table("sermons").select("id", count="exact") \
        .eq("preacher_id", customer.preacher_id) \
        .not_.is_("audio_url", "null").execute()
    before_n = before.count or 0

    dispatch = {
        "rss": ["sync_sermon_audio_from_rss.py", "--feed", customer.podcast_feed_url or ""],
        "yash_html": ["sync_sermons_from_yash.py", "--host", customer.audio_base_url or ""],
        # Nucleus adapter TODO: model on download_crossofgrace.py but write audio_url
        # to Supabase instead of downloading. Engine ID lives in ingest_config.
        "nucleus": None,
    }
    if customer.ingest_source_type not in dispatch:
        log.warning(f"  no adapter for ingest_source_type={customer.ingest_source_type}; skipping")
        return 0
    if dispatch[customer.ingest_source_type] is None:
        log.warning(f"  {customer.ingest_source_type} adapter not yet built; skipping {customer.church_name}")
        return 0

    cmd = [sys.executable, str(REPO_ROOT / dispatch[customer.ingest_source_type][0]),
           "--preacher", customer.preacher_id, *dispatch[customer.ingest_source_type][1:]]
    if dry_run:
        cmd.append("--dry-run")
    log.info(f"  → {' '.join(cmd)}")

    result = subprocess.run(cmd, cwd=REPO_ROOT, capture_output=True, text=True)
    if result.returncode != 0:
        log.error(f"  adapter failed: {result.stderr[-500:]}")
        return 0
    # The script prints its own summary; log a trailing slice
    for line in result.stdout.strip().splitlines()[-8:]:
        log.info(f"    {line}")

    after = sb.table("sermons").select("id", count="exact") \
        .eq("preacher_id", customer.preacher_id) \
        .not_.is_("audio_url", "null").execute()
    after_n = after.count or 0
    return after_n - before_n


# ────────────────────────────────────────────────────────────────────────────
# Stage 2 — Pending sermons (those with audio_url but no units yet = un-decomposed)
# ────────────────────────────────────────────────────────────────────────────

def pending_for_decomposition(customer: Customer) -> list[dict]:
    """Sermons with audio_url + no units rows = ready to decompose."""
    sb = supabase()
    # Get all this preacher's sermons with audio_url
    res = sb.table("sermons").select("id, title, date, audio_url, raw_transcript") \
        .eq("preacher_id", customer.preacher_id) \
        .not_.is_("audio_url", "null") \
        .is_("decomposed_at", "null") \
        .order("date", desc=True).execute()
    return res.data or []


# ────────────────────────────────────────────────────────────────────────────
# Stages 4-5 — Wait for batch + process results
# ────────────────────────────────────────────────────────────────────────────

def _all_decomposed_ids(sb) -> set[str]:
    """Return every sermon_id with decomposed_at set, paginated.

    Supabase REST caps single-page results at 1000 rows. The corpus
    grew past that on 2026-05-13; without pagination the pre/post diff
    silently returns empty when newly-ingested rows fall on later pages.
    """
    ids: set[str] = set()
    offset = 0
    page = 1000
    while True:
        rows = (
            sb.table("sermons")
            .select("id")
            .not_.is_("decomposed_at", "null")
            .range(offset, offset + page - 1)
            .execute()
            .data
            or []
        )
        if not rows:
            break
        ids.update(r["id"] for r in rows)
        if len(rows) < page:
            break
        offset += page
    return ids


def wait_and_process_batch(batch_id: str, preacher_name: str) -> set[str]:
    """Wait for Anthropic batch to complete, then process results (parse → embed →
    ingest to Supabase). Returns set of sermon_ids newly populated with decomposed_at.
    """
    sb = supabase()
    before_decomposed = _all_decomposed_ids(sb)

    # Stage 4 — block until batch ends
    log.info(f"  [stage 4] waiting for batch {batch_id} …")
    cmd = [sys.executable, str(REPO_ROOT / "pipeline_batch.py"), "status", batch_id, "--wait"]
    r = subprocess.run(cmd, cwd=REPO_ROOT, capture_output=True, text=True, timeout=BATCH_MAX_WAIT_HOURS * 3600)
    if r.returncode != 0:
        log.error(f"  status --wait failed: {r.stderr[-500:]}")
        return set()

    # Stage 5 — process results
    log.info(f"  [stage 5] processing batch {batch_id} for preacher='{preacher_name}'")
    cmd = [sys.executable, str(REPO_ROOT / "pipeline_batch.py"), "process", batch_id, "--preacher", preacher_name]
    r = subprocess.run(cmd, cwd=REPO_ROOT, capture_output=True, text=True)
    if r.returncode != 0:
        log.error(f"  process failed: {r.stderr[-500:]}")
        # Continue anyway in case partial success
    for line in r.stdout.splitlines()[-10:]:
        log.info(f"    {line}")

    after_decomposed = _all_decomposed_ids(sb)
    return after_decomposed - before_decomposed


# ────────────────────────────────────────────────────────────────────────────
# Stage 6 — Artifacts (per-sermon, calls generate_artifacts.py)
# ────────────────────────────────────────────────────────────────────────────

def generate_artifacts_for(sermon_id: str) -> int:
    n = 0
    for atype in ARTIFACT_TYPES:
        cmd = [sys.executable, str(REPO_ROOT / "generate_artifacts.py"),
               "generate", sermon_id, "--type", atype]
        r = subprocess.run(cmd, cwd=REPO_ROOT, capture_output=True, text=True)
        if r.returncode == 0:
            n += 1
        else:
            log.warning(f"  artifact {atype} failed for {sermon_id}: {r.stderr[-200:]}")
    return n


# ────────────────────────────────────────────────────────────────────────────
# Stages 4-7 orchestrator for one completed batch
# ────────────────────────────────────────────────────────────────────────────

def finish_batch(batch_id: str, preacher_name: str) -> tuple[int, int, int, int]:
    """Wait → process → artifacts → render → deploy → refresh analysis.

    Returns (sermons, artifacts, pages, deployed).
    """
    new_sermon_ids = wait_and_process_batch(batch_id, preacher_name)
    log.info(f"  [stages 4-5] {len(new_sermon_ids)} sermon(s) newly ingested")

    n_artifacts = 0
    rendered_ids: list[str] = []
    for sid in new_sermon_ids:
        log.info(f"  [stage 6] generating artifacts for {sid}")
        n_artifacts += generate_artifacts_for(sid)
        log.info(f"  [stage 7] rendering main sermon page for {sid}")
        if render_page(sid):
            rendered_ids.append(sid)
            # Stage 7b — render the companion Sermon Scraps page. Tolerant
            # of failure: if scraps render fails, the main page still ships.
            log.info(f"  [stage 7b] rendering scraps page for {sid}")
            if not render_scraps_page(sid):
                log.warning(f"    scraps render failed for {sid}; main page will deploy without scraps")

    # Stage 7c — rebuild per-church sermon-index pages so the newly-rendered
    # sermons appear in the index. Tolerant: deploy still ships individual
    # sermon pages even if the index rebuild fails.
    if rendered_ids:
        log.info(f"  [stage 7c] rebuilding church sermon-index pages")
        if not rebuild_church_indexes():
            log.warning("    church-index rebuild failed; indexes may lag")

    n_deployed = deploy_rendered(rendered_ids)

    # Stage 9 — refresh the pastor's preacher_analysis row so the SG
    # dashboard at theshepherdsguild.com/showcasev4 reflects the new
    # corpus. Per-preacher (not per-sermon), so it runs once at the end.
    # Tolerant of failure: a stale dashboard is not worth rolling back
    # a successful deploy.
    if new_sermon_ids:
        preacher_id = _preacher_id_for_sermon(new_sermon_ids[0])
        if preacher_id:
            log.info(f"  [stage 9] refreshing preacher_analysis for {preacher_name}")
            if not refresh_preacher_analysis(preacher_id):
                log.warning(f"    preacher_analysis refresh failed for {preacher_name}; SG dashboard will lag")
        else:
            log.warning(f"  [stage 9] could not resolve preacher_id for {preacher_name}; skipping analysis refresh")

    return len(new_sermon_ids), n_artifacts, len(rendered_ids), n_deployed


# ────────────────────────────────────────────────────────────────────────────
# Stage 7 — Render pages
# ────────────────────────────────────────────────────────────────────────────

def render_page(sermon_id: str) -> bool:
    cmd = [sys.executable, str(REPO_ROOT / "generate_sermon_pages.py"), "render", sermon_id]
    r = subprocess.run(cmd, cwd=REPO_ROOT, capture_output=True, text=True)
    if r.returncode != 0:
        log.warning(f"  render failed for {sermon_id}: {r.stderr[-200:]}")
        return False
    return True


def render_scraps_page(sermon_id: str) -> bool:
    """Render the Sermon Scraps companion page to disk.

    Tolerant: returns False on any subprocess failure, but does not raise —
    the main sermon page can still deploy without the scraps companion.
    """
    cmd = [sys.executable, str(REPO_ROOT / "scripts" / "generate_sermon_scraps_page.py"), sermon_id]
    r = subprocess.run(cmd, cwd=REPO_ROOT, capture_output=True, text=True)
    if r.returncode != 0:
        log.warning(f"  scraps render failed for {sermon_id}: {r.stderr[-200:]}")
        return False
    return True


def rebuild_church_indexes() -> bool:
    """Regenerate per-church sermon-index pages.

    Called after stage 7/7b so freshly-rendered sermons appear in the
    /<url_slug>/sermons/ index. Writes index.html directly into the
    sermon-steward deploy repo (the builder script targets it by
    absolute path). Stage 8's git add -A picks the index up.

    Tolerant: returns False on subprocess failure; deploy still ships
    the individual sermon pages even if the index didn't rebuild.
    """
    cmd = [sys.executable, str(REPO_ROOT / "scripts" / "build_church_indexes.py")]
    r = subprocess.run(cmd, cwd=REPO_ROOT, capture_output=True, text=True)
    if r.returncode != 0:
        log.warning(f"  church-index rebuild failed: {r.stderr[-200:]}")
        return False
    return True


def _preacher_id_for_sermon(sermon_id: str) -> Optional[str]:
    """Look up a sermon's preacher_id from Supabase."""
    try:
        sb = supabase()
        row = (
            sb.table("sermons")
            .select("preacher_id")
            .eq("id", sermon_id)
            .single()
            .execute()
            .data
        )
        return (row or {}).get("preacher_id")
    except Exception as exc:
        log.warning(f"  preacher_id lookup failed for {sermon_id}: {exc}")
        return None


def refresh_preacher_analysis(preacher_id: str) -> bool:
    """Re-run generate_analysis.py for one pastor. Updates the SG dashboard.

    Tolerant: returns False on subprocess failure.
    """
    cmd = [sys.executable, str(REPO_ROOT / "generate_analysis.py"),
           "--preacher-id", preacher_id]
    r = subprocess.run(cmd, cwd=REPO_ROOT, capture_output=True, text=True)
    if r.returncode != 0:
        log.warning(f"  preacher_analysis refresh failed: {r.stderr[-200:]}")
        return False
    return True


# ────────────────────────────────────────────────────────────────────────────
# Stage 8 — Deploy
# ────────────────────────────────────────────────────────────────────────────
# One git push per brand. Each church's `brand` column picks the deploy repo;
# all sermons for a brand land in one commit so Cloudflare auto-deploys once
# per weekly run.

DEFAULT_OUTPUT_DIR = REPO_ROOT / "output" / "sermon-pages"

BRAND_REPOS: dict[str, Path] = {
    "sermon_steward": Path("/Users/dad/shepherds-guild/sermon-steward"),
    # "shepherds_guild": Path(...)  # reserved for future bailey-side surfaces
}


def deploy_rendered(sermon_ids: list[str]) -> int:
    """Stage every rendered page in its brand's repo and push one commit per brand.

    Returns the count of pages successfully pushed across all brands.
    """
    if not sermon_ids:
        return 0

    sb = supabase()
    rows = (
        sb.table("sermons")
        .select("id, slug, preachers(churches(url_slug, brand, name))")
        .in_("id", sermon_ids)
        .execute()
        .data
        or []
    )

    from sermon_page_renderer.deploy import CloudflarePagesAdapter

    # Group staged files by brand so each brand pushes once.
    # Each tuple: (file_path, url_path, church_name). For each sermon we
    # add both the main page and (when present) the scraps companion page.
    by_brand: dict[str, list[tuple[Path, str, str]]] = {}
    for r in rows:
        church = (r.get("preachers") or {}).get("churches") or {}
        brand = church.get("brand")
        url_slug = church.get("url_slug")
        sermon_slug = r.get("slug")
        if not (brand and url_slug and sermon_slug):
            log.warning(f"  [stage 8] skip {r.get('id')}: missing brand/url_slug/slug")
            continue

        church_name = church.get("name") or "?"
        main_file = DEFAULT_OUTPUT_DIR / url_slug / "sermons" / f"{sermon_slug}.html"
        if not main_file.exists():
            log.warning(f"  [stage 8] skip {r.get('id')}: main page missing at {main_file}")
            continue
        by_brand.setdefault(brand, []).append(
            (main_file, f"/{url_slug}/sermons/{sermon_slug}", church_name)
        )

        # Scraps page — optional companion. Stage if rendered, skip silently
        # if not (e.g., scraps generation failed earlier; the main page still
        # ships, just without the /scraps companion).
        scraps_file = DEFAULT_OUTPUT_DIR / url_slug / "sermons" / sermon_slug / "scraps.html"
        if scraps_file.exists():
            by_brand[brand].append(
                (scraps_file, f"/{url_slug}/sermons/{sermon_slug}/scraps", church_name)
            )

    deployed_main_pages = 0
    for brand, items in by_brand.items():
        repo = BRAND_REPOS.get(brand)
        if not repo:
            log.warning(f"  [stage 8] no deploy repo configured for brand={brand!r}; skipping {len(items)} files")
            continue
        adapter = CloudflarePagesAdapter(repo)
        for file_path, url_path, _ in items:
            adapter.stage(file_path, url_path)
        # Stage per-church index.html pages. They were rewritten by
        # stage 7c (rebuild_church_indexes) and live directly in the
        # repo at <repo>/<url_slug>/sermons/index.html. Use stage_in_place
        # so the adapter picks them up in the same commit.
        affected_url_slugs = {
            fp.relative_to(repo).parts[0]
            for fp, _, _ in items
            if fp.is_relative_to(repo)
        } if items else set()
        # items file_paths are still in the OUTPUT dir (not the repo) at
        # this point — they were copied INTO the repo by adapter.stage().
        # Re-derive affected url_slugs from the url_paths instead.
        affected_url_slugs = {url_path.lstrip("/").split("/")[0] for _, url_path, _ in items}
        for url_slug in affected_url_slugs:
            try:
                adapter.stage_in_place(f"{url_slug}/sermons/index.html")
            except FileNotFoundError:
                log.warning(f"  [stage 8] {url_slug}/sermons/index.html missing; index won't update")

        # Count distinct sermons (each sermon may stage 1 or 2 files —
        # the main page + the optional scraps.html companion). Index
        # pages are also staged but not counted as sermons.
        n_sermons = sum(1 for fp, _, _ in items if fp.name != "scraps.html")
        churches = ", ".join(sorted({name for _, _, name in items}))
        message = f"weekly_ingest: deploy {n_sermons} sermon(s) + scraps + index ({churches})"
        result = adapter.commit_and_push(message)
        if result.status == "success" and result.error not in ("nothing staged", "no diff"):
            log.info(f"  [stage 8] {brand}: pushed {len(items)} file(s) ({n_sermons} sermons) to {repo.name}")
            deployed_main_pages += n_sermons
        elif result.error == "no diff":
            log.info(f"  [stage 8] {brand}: no changes to push ({len(items)} files already up to date)")
        else:
            log.error(f"  [stage 8] {brand}: push failed — {result.error}")

    return deployed_main_pages


# ────────────────────────────────────────────────────────────────────────────
# Main flow
# ────────────────────────────────────────────────────────────────────────────

@dataclass
class RunSummary:
    started_at: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))
    customers: int = 0
    discovered: int = 0
    decomposed_submitted: int = 0
    batch_id: Optional[str] = None
    decomposed_processed: int = 0
    artifacts_generated: int = 0
    pages_rendered: int = 0
    pages_deployed: int = 0
    errors: list[str] = field(default_factory=list)


def run_weekly(catchup: bool, dry_run: bool) -> RunSummary:
    summary = RunSummary()
    log.info(f"=== weekly_ingest {'(catchup)' if catchup else ''} starting ===")

    customers = active_customers()
    summary.customers = len(customers)
    log.info(f"Active customers: {len(customers)}")
    if not customers:
        log.warning("No active customers (churches.auto_publish=true). Nothing to do.")
        return summary

    # Stage 1 — Discover
    for c in customers:
        try:
            n = discover_new_for_customer(c, dry_run=dry_run)
            summary.discovered += n
        except Exception as e:
            msg = f"discover failed for {c.church_name}: {e}"
            log.error(msg)
            summary.errors.append(msg)

    if dry_run:
        log.info("DRY RUN — stopping after discover stage")
        return summary

    # Stages 2–3 — Decompose pending sermons (those with audio + no decomposition yet)
    pending: list[tuple[Customer, dict]] = []
    for c in customers:
        for s in pending_for_decomposition(c):
            if s.get("raw_transcript"):
                pending.append((c, s))
            else:
                # TODO Stage 2: download from transcript_url if present, else AssemblyAI on audio_url
                log.info(f"  [skip] {c.church_name}: {s['title']!r} has no raw_transcript (TODO: download/AssemblyAI)")

    if not pending:
        log.info("No sermons pending decomposition.")
        return summary

    # Group by preacher — pipeline_batch.py submit takes one --preacher per run
    by_preacher: dict[str, tuple[Customer, list[dict]]] = {}
    for c, s in pending:
        key = c.preacher_id
        if key not in by_preacher:
            by_preacher[key] = (c, [])
        by_preacher[key][1].append(s)

    log.info(f"Submitting decomposition: {len(pending)} sermon(s) across {len(by_preacher)} preacher(s)")
    batch_ids: dict[str, str] = {}
    for preacher_id, (c, sermons) in by_preacher.items():
        bid = submit_decomposition_batch(c, sermons)
        if bid:
            batch_ids[c.preacher_name] = bid
            summary.decomposed_submitted += len(sermons)
    summary.batch_id = " · ".join(f"{k}={v}" for k, v in batch_ids.items()) if batch_ids else None

    if batch_ids:
        # Persist for the followup `process` command
        state = QUEUE_DIR / "pending_batches.json"
        state.write_text(json.dumps({
            "submitted_at": datetime.now().isoformat(timespec="seconds"),
            "batches": batch_ids,
        }, indent=2))
        log.info(f"Batch IDs persisted to {state}")
        log.info("Stages 4–8 (poll → process → artifacts → render → deploy) will run when you invoke:")
        for name, bid in batch_ids.items():
            log.info(f"  python weekly_ingest.py process {bid}    # {name}")

    return summary


# ────────────────────────────────────────────────────────────────────────────
# Stage 3 — Submit a decomposition batch for one preacher's pending sermons
# ────────────────────────────────────────────────────────────────────────────

def submit_decomposition_batch(customer: Customer, sermons: list[dict]) -> Optional[str]:
    """Write each sermon's raw_transcript to weekly_queue/<preacher_slug>/<sermon_id>.txt
    with a bracket header for LLM context, then call `pipeline_batch.py submit`.

    Returns the Anthropic batch_id (parsed from pipeline_batch.py's stdout) or None.
    """
    import re
    slug = re.sub(r"[^a-z0-9]+", "-", customer.preacher_name.lower()).strip("-")
    queue = QUEUE_DIR / slug
    queue.mkdir(parents=True, exist_ok=True)
    # Clear stale files so we only submit what's currently pending
    for f in queue.glob("*.txt"):
        f.unlink()

    for s in sermons:
        header_lines = [
            f"[Preached on {s['date']} by {customer.preacher_name} at {customer.church_name}]",
            f"[Title: {s['title']}]",
        ]
        if s.get("primary_text"):
            header_lines.append(f"[Primary text: {s['primary_text']}]")
        header = "\n".join(header_lines) + "\n\n"
        fn = queue / f"{s['id']}.txt"
        fn.write_text(header + (s.get("raw_transcript") or ""))

    log.info(f"  wrote {len(sermons)} transcript(s) to {queue}")

    cmd = [
        sys.executable, str(REPO_ROOT / "pipeline_batch.py"), "submit",
        str(queue),
        "--preacher", customer.preacher_name,
    ]
    log.info(f"  → {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=REPO_ROOT, capture_output=True, text=True)
    if result.returncode != 0:
        log.error(f"  submit failed: {result.stderr[-500:]}")
        return None

    # Parse "Batch ID: msgbatch_XXX" from stdout
    m = re.search(r"Batch ID:\s*(msgbatch_\w+)", result.stdout)
    if not m:
        log.error(f"  could not find batch ID in stdout. Last lines:\n{result.stdout[-500:]}")
        return None
    batch_id = m.group(1)
    log.info(f"  batch submitted: {batch_id}")
    return batch_id


def write_summary(s: RunSummary) -> Path:
    fn = LOG_DIR / f"weekly-{s.started_at.replace(':', '')}.json"
    fn.write_text(json.dumps(s.__dict__, indent=2, default=str))
    return fn


def print_summary(s: RunSummary) -> None:
    print()
    print("─" * 60)
    print(f"Weekly ingest — {s.started_at}")
    print("─" * 60)
    print(f"Customers processed:       {s.customers}")
    print(f"New audio URLs discovered: {s.discovered}")
    print(f"Sermons sent to decompose: {s.decomposed_submitted}")
    if s.batch_id:
        print(f"Batch ID:                  {s.batch_id}")
    print(f"Sermons processed:         {s.decomposed_processed}")
    print(f"Artifacts generated:       {s.artifacts_generated}")
    print(f"Pages rendered:            {s.pages_rendered}")
    print(f"Pages deployed:            {s.pages_deployed}")
    if s.errors:
        print(f"\nErrors ({len(s.errors)}):")
        for e in s.errors:
            print(f"  - {e}")


# ────────────────────────────────────────────────────────────────────────────
# CLI
# ────────────────────────────────────────────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = ap.add_subparsers(dest="mode", required=True)

    p_weekly = sub.add_parser("weekly", help="Run the full Sunday-evening cadence")
    p_weekly.add_argument("--catchup", action="store_true",
                          help="Mark this as the Monday-morning catchup pass")
    p_weekly.add_argument("--dry-run", action="store_true",
                          help="Stop after discover; print what would happen")

    p_discover = sub.add_parser("discover", help="Just run the discover stage")
    p_discover.add_argument("--dry-run", action="store_true")

    p_process = sub.add_parser("process", help="Process a known batch_id (wait + ingest + artifacts + render)")
    p_process.add_argument("batch_id")

    p_auto = sub.add_parser("auto-process", help="Process all batches listed in weekly_queue/pending_batches.json")

    args = ap.parse_args()

    if args.mode == "weekly":
        s = run_weekly(catchup=args.catchup, dry_run=args.dry_run)
        log_path = write_summary(s)
        print_summary(s)
        log.info(f"summary written to {log_path}")
        return 0
    elif args.mode == "discover":
        s = RunSummary()
        for c in active_customers():
            try:
                s.discovered += discover_new_for_customer(c, dry_run=args.dry_run)
                s.customers += 1
            except Exception as e:
                s.errors.append(f"{c.church_name}: {e}")
        print_summary(s)
        return 0
    elif args.mode == "process":
        # Look up preacher_name for this batch from pending_batches.json
        state_path = QUEUE_DIR / "pending_batches.json"
        preacher_name: Optional[str] = None
        if state_path.exists():
            state = json.loads(state_path.read_text())
            for name, bid in (state.get("batches") or {}).items():
                if bid == args.batch_id:
                    preacher_name = name
                    break
        if not preacher_name:
            # Fall back to scanning pipeline_batch's own manifest
            manifest = REPO_ROOT / "batches" / f"{args.batch_id}_manifest.json"
            if manifest.exists():
                m = json.loads(manifest.read_text())
                preacher_name = m.get("preacher")
        if not preacher_name:
            log.error(f"could not determine preacher for {args.batch_id}; pass --preacher")
            return 2
        log.info(f"processing batch {args.batch_id} for {preacher_name}")
        n_sermons, n_artifacts, n_pages, n_deployed = finish_batch(args.batch_id, preacher_name)
        log.info(f"DONE: {n_sermons} sermons, {n_artifacts} artifacts, {n_pages} pages, {n_deployed} deployed")
        # Mark this batch as processed
        if state_path.exists():
            state = json.loads(state_path.read_text())
            state.setdefault("processed", []).append({
                "batch_id": args.batch_id,
                "preacher": preacher_name,
                "sermons": n_sermons,
                "artifacts": n_artifacts,
                "pages": n_pages,
                "deployed": n_deployed,
                "processed_at": datetime.now().isoformat(timespec="seconds"),
            })
            # Remove from batches map
            state["batches"] = {k: v for k, v in (state.get("batches") or {}).items() if v != args.batch_id}
            state_path.write_text(json.dumps(state, indent=2))
        return 0

    elif args.mode == "auto-process":
        state_path = QUEUE_DIR / "pending_batches.json"
        if not state_path.exists():
            log.info("no pending batches")
            return 0
        state = json.loads(state_path.read_text())
        pending = state.get("batches") or {}
        if not pending:
            log.info("no pending batches")
            return 0
        log.info(f"auto-processing {len(pending)} pending batch(es)")
        for preacher_name, batch_id in pending.items():
            try:
                n_sermons, n_artifacts, n_pages, n_deployed = finish_batch(batch_id, preacher_name)
                log.info(f"  {preacher_name}: {n_sermons} sermons, {n_artifacts} artifacts, {n_pages} pages, {n_deployed} deployed")
                state.setdefault("processed", []).append({
                    "batch_id": batch_id, "preacher": preacher_name,
                    "sermons": n_sermons, "artifacts": n_artifacts, "pages": n_pages, "deployed": n_deployed,
                    "processed_at": datetime.now().isoformat(timespec="seconds"),
                })
            except Exception as e:
                log.error(f"  {preacher_name} failed: {e}")
        state["batches"] = {}
        state_path.write_text(json.dumps(state, indent=2))
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
