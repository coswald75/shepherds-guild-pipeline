"""
weekly_ingest.py — Sunday-evening cron orchestrator.
─────────────────────────────────────────────────────────────────────────────
For every customer with `churches.auto_publish = true`, walks the full
Sunday-evening cadence:

  1. DISCOVER   pull new sermons from each customer's host
                (rss + yash_html + nucleus implemented; RSS inserts new rows)
  2. TRANSCRIBE for sermons missing transcripts: fetch from transcript_url
                if present; else submit AssemblyAI job and queue the id in
                transcript_url for the next cron run to poll/collect
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
    "small_group_questions", "daily_readings", "prayer_prompt",
    "family_card", "couples_guide", "memory_verse",
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
    ingest_config: Optional[dict] = None  # per-host params (Nucleus engine_id, etc)


def active_customers() -> list[Customer]:
    """All churches flagged auto_publish=true, joined to their primary preacher."""
    sb = supabase()
    res = sb.table("churches").select(
        "id, name, slug, audio_base_url, podcast_feed_url, ingest_source_type, ingest_config, deploy_target"
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
            ingest_config=c.get("ingest_config"),
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

    engine_id = (customer.ingest_config or {}).get("engine_id") or ""
    dispatch = {
        "rss": ["sync_sermon_audio_from_rss.py", "--feed", customer.podcast_feed_url or ""],
        "yash_html": ["sync_sermons_from_yash.py", "--host", customer.audio_base_url or ""],
        "nucleus": [
            "sync_sermons_from_nucleus.py",
            "--host", customer.audio_base_url or "",
            "--engine-id", engine_id,
        ],
    }
    if customer.ingest_source_type not in dispatch:
        log.warning(f"  no adapter for ingest_source_type={customer.ingest_source_type}; skipping")
        return 0
    if customer.ingest_source_type == "nucleus" and not engine_id:
        log.warning(f"  nucleus adapter requires ingest_config.engine_id; skipping {customer.church_name}")
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

# AssemblyAI-pending sentinel. When a sermon's audio is queued for
# transcription, we stash the AssemblyAI transcript ID in transcript_url
# as f"assemblyai://{id}" — so the next cron run knows to poll instead of
# re-submit. Survives without a schema change.
ASSEMBLYAI_URL_SCHEME = "assemblyai://"

# How long an HTTP transcript fetch is allowed before we give up and fall
# through to the AssemblyAI path.
TRANSCRIPT_FETCH_TIMEOUT_S = 30


def pending_for_decomposition(customer: Customer) -> list[dict]:
    """Sermons with audio_url + no decomposition yet = candidates for Stage 2/3.

    Returns transcript_url too so Stage 2 can decide: fetch synchronously
    (regular HTTP transcript), poll an in-flight AssemblyAI job, or submit
    a fresh AssemblyAI job for the audio.
    """
    sb = supabase()
    res = sb.table("sermons").select(
        "id, title, date, audio_url, raw_transcript, transcript_url"
    ) \
        .eq("preacher_id", customer.preacher_id) \
        .not_.is_("audio_url", "null") \
        .is_("decomposed_at", "null") \
        .order("date", desc=True).execute()
    return res.data or []


def fetch_transcript_text(url: str) -> Optional[str]:
    """Synchronously fetch a transcript URL and return cleaned text.

    Handles plain text, basic VTT (drop cue timings), and basic SRT (drop
    sequence + timing lines). Returns None on any failure — caller falls
    through to AssemblyAI.

    Strips Unicode NULL bytes (\\x00) before returning. Postgres TEXT
    cannot store them and will reject the UPDATE with
    "unsupported Unicode escape sequence — \\u0000 cannot be converted
    to text" (caught in production 2026-06-08).
    """
    import re as _re
    import urllib.request as _urlreq

    try:
        req = _urlreq.Request(url, headers={"User-Agent": "shepherds-guild-pipeline/1.0"})
        with _urlreq.urlopen(req, timeout=TRANSCRIPT_FETCH_TIMEOUT_S) as resp:
            body = resp.read().decode("utf-8", errors="replace")
    except Exception as e:
        log.warning(f"  transcript fetch failed for {url}: {e}")
        return None

    # Strip null bytes up front so the rest of the pipeline doesn't have
    # to think about them.
    body = body.replace("\x00", "")
    if not body.strip():
        return None

    # VTT: drop "WEBVTT" header line, cue timing lines (00:00:00.000 --> ...),
    # and per-line cue numbers. SRT is similar; drop integer-only lines + timings.
    cleaned_lines: list[str] = []
    for line in body.splitlines():
        s = line.strip()
        if not s:
            cleaned_lines.append("")
            continue
        if s == "WEBVTT" or s.startswith("WEBVTT"):
            continue
        if "-->" in s and _re.match(r"^\d{1,2}:\d{2}", s):
            continue  # VTT / SRT timing line
        if s.isdigit():
            continue  # SRT sequence number
        # Strip VTT inline tags like <v Speaker> or <c.classname>
        s = _re.sub(r"</?[a-zA-Z][^>]*>", "", s)
        cleaned_lines.append(s)
    text = "\n".join(cleaned_lines)
    # Collapse runs of blank lines.
    text = _re.sub(r"\n{3,}", "\n\n", text).strip()
    # Belt-and-suspenders: in case any null byte snuck back in via decode
    # round-tripping or regex weirdness.
    text = text.replace("\x00", "")
    if not text:
        return None
    return text + "\n"


def submit_assemblyai_job(audio_url: str) -> Optional[str]:
    """Submit an audio URL to AssemblyAI for transcription. Returns the
    AssemblyAI transcript ID immediately (does NOT block on completion).

    Returns None if AssemblyAI isn't configured or the submit fails — caller
    logs and moves on. Subsequent cron runs pick up via poll_assemblyai_job.
    """
    api_key = os.environ.get("ASSEMBLYAI_API_KEY")
    if not api_key:
        log.warning("  ASSEMBLYAI_API_KEY not set — cannot submit transcription job")
        return None
    try:
        import assemblyai as aai
    except ImportError:
        log.warning("  assemblyai package not installed — cannot submit transcription job")
        return None

    aai.settings.api_key = api_key
    try:
        config = aai.TranscriptionConfig(speaker_labels=False, punctuate=True, format_text=True)
        transcript = aai.Transcriber().submit(audio_url, config)
        return transcript.id
    except Exception as e:
        log.warning(f"  assemblyai submit failed for {audio_url}: {e}")
        return None


def poll_assemblyai_job(transcript_id: str) -> Optional[str]:
    """Fetch an AssemblyAI transcript by ID. Returns transcript text if
    completed, None otherwise (still running, errored, or AssemblyAI down).

    The status check is one API call and returns immediately even when the
    job is still processing — cron-friendly.
    """
    api_key = os.environ.get("ASSEMBLYAI_API_KEY")
    if not api_key:
        return None
    try:
        import assemblyai as aai
    except ImportError:
        return None

    aai.settings.api_key = api_key
    try:
        t = aai.Transcript.get_by_id(transcript_id)
    except Exception as e:
        log.warning(f"  assemblyai poll failed for {transcript_id}: {e}")
        return None

    status = getattr(t, "status", None)
    status_str = status.value if hasattr(status, "value") else str(status)
    if status_str == "completed":
        # Strip null bytes (same Postgres TEXT constraint as fetch_transcript_text).
        text = (t.text or "").replace("\x00", "").strip()
        return text + "\n" if text else None
    if status_str == "error":
        log.warning(f"  assemblyai job {transcript_id} errored: {getattr(t, 'error', '?')}")
        return None
    log.info(f"  assemblyai job {transcript_id} status={status_str}; will retry next run")
    return None


def resolve_transcript_for_pending(sermon: dict) -> Optional[str]:
    """Decide which transcript path applies to this pending sermon, do the work,
    and return the populated transcript text — OR return None if the sermon
    can't be transcribed this run (in flight, no path available, etc.).

    Side effect: when an AssemblyAI job is submitted, writes
    transcript_url='assemblyai://<id>' so subsequent runs poll instead of
    re-submitting.
    """
    sb = supabase()
    t_url = sermon.get("transcript_url")

    # Case 1: an AssemblyAI job is already in flight — just poll
    if t_url and t_url.startswith(ASSEMBLYAI_URL_SCHEME):
        job_id = t_url[len(ASSEMBLYAI_URL_SCHEME):]
        text = poll_assemblyai_job(job_id)
        if text:
            sb.table("sermons").update({
                "raw_transcript": text,
            }).eq("id", sermon["id"]).execute()
            return text
        return None  # still in flight

    # Case 2: regular transcript URL (host-provided) — fetch synchronously
    if t_url:
        text = fetch_transcript_text(t_url)
        if text:
            sb.table("sermons").update({
                "raw_transcript": text,
            }).eq("id", sermon["id"]).execute()
            return text
        # Fall through to AssemblyAI if the URL failed (404, 5xx, parse error)

    # Case 3: submit a fresh AssemblyAI job. Stash the id in transcript_url
    # so the next run polls it instead of re-submitting.
    if sermon.get("audio_url"):
        job_id = submit_assemblyai_job(sermon["audio_url"])
        if job_id:
            sb.table("sermons").update({
                "transcript_url": f"{ASSEMBLYAI_URL_SCHEME}{job_id}",
            }).eq("id", sermon["id"]).execute()
        return None

    return None  # nothing to do


# ────────────────────────────────────────────────────────────────────────────
# Stages 4-5 — Wait for batch + process results
# ────────────────────────────────────────────────────────────────────────────

def _all_decomposed_ids(sb: Client) -> set[str]:
    """Page through `sermons` and return the set of IDs with decomposed_at NOT NULL.

    A single .execute() is capped at 1000 rows by Supabase PostgREST. The corpus
    crossed that threshold around 2026-05 — without pagination the snapshot
    silently truncates and the before/after diff drops any sermons whose IDs
    land in the truncated tail.
    """
    ids: set[str] = set()
    offset = 0
    while True:
        page = (
            sb.table("sermons")
            .select("id")
            .not_.is_("decomposed_at", "null")
            .range(offset, offset + 999)
            .execute().data or []
        )
        ids.update(r["id"] for r in page)
        if len(page) < 1000:
            break
        offset += 1000
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

def finish_batch(batch_id: str, preacher_name: str) -> tuple[int, int, int]:
    """Wait → process → artifacts → render. Returns (sermons, artifacts, pages)."""
    new_sermon_ids = wait_and_process_batch(batch_id, preacher_name)
    log.info(f"  [stages 4-5] {len(new_sermon_ids)} sermon(s) newly ingested")

    n_artifacts = 0
    n_pages = 0
    for sid in new_sermon_ids:
        log.info(f"  [stage 6] generating artifacts for {sid}")
        n_artifacts += generate_artifacts_for(sid)
        log.info(f"  [stage 7] rendering page for {sid}")
        if render_page(sid):
            n_pages += 1
    return len(new_sermon_ids), n_artifacts, n_pages


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


# ────────────────────────────────────────────────────────────────────────────
# Stage 8 — Deploy (STUBBED — print what would happen)
# ────────────────────────────────────────────────────────────────────────────

def deploy_for_customer(customer: Customer, sermon_count: int) -> None:
    target = customer.deploy_target or {}
    host = target.get("host", "unset")
    project = target.get("project", "unset")
    log.info(f"  [deploy STUB] {customer.church_name}: would push {sermon_count} pages to {host}:{project}")


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
    customers_deployed: int = 0
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
    #
    # Stage 2 priority order, per sermon:
    #   (a) raw_transcript already populated → ready for decomposition
    #   (b) transcript_url is assemblyai://<id> → poll job; collect if done
    #   (c) transcript_url is regular HTTP → fetch synchronously
    #   (d) audio_url only → submit AssemblyAI, queue for next run
    # See resolve_transcript_for_pending().
    pending: list[tuple[Customer, dict]] = []
    stage2_stats = {"already_had": 0, "fetched": 0, "assemblyai_polled_done": 0,
                    "assemblyai_in_flight": 0, "assemblyai_submitted": 0, "skipped": 0}
    for c in customers:
        for s in pending_for_decomposition(c):
            if s.get("raw_transcript"):
                pending.append((c, s))
                stage2_stats["already_had"] += 1
                continue

            t_url = s.get("transcript_url") or ""
            was_assemblyai = t_url.startswith(ASSEMBLYAI_URL_SCHEME)
            had_url = bool(t_url) and not was_assemblyai

            text = resolve_transcript_for_pending(s)
            if text:
                # Got a transcript this run — re-include for downstream stages
                s["raw_transcript"] = text
                pending.append((c, s))
                if was_assemblyai:
                    stage2_stats["assemblyai_polled_done"] += 1
                    log.info(f"  [transcript collected from AssemblyAI] {c.church_name}: {s['title']!r}")
                elif had_url:
                    stage2_stats["fetched"] += 1
                    log.info(f"  [transcript fetched] {c.church_name}: {s['title']!r}")
                else:
                    # Edge case: AssemblyAI synchronous result. Shouldn't happen with current code.
                    stage2_stats["fetched"] += 1
                continue

            # No transcript this run. Figure out which queued state we ended in.
            if was_assemblyai:
                stage2_stats["assemblyai_in_flight"] += 1
                log.info(f"  [waiting on AssemblyAI] {c.church_name}: {s['title']!r}")
            elif s.get("audio_url"):
                # resolve_transcript_for_pending submitted a fresh AssemblyAI job
                stage2_stats["assemblyai_submitted"] += 1
                log.info(f"  [AssemblyAI submitted] {c.church_name}: {s['title']!r}")
            else:
                stage2_stats["skipped"] += 1
                log.info(f"  [skip] {c.church_name}: {s['title']!r} has no audio path")
    log.info(
        f"Stage 2 summary: had={stage2_stats['already_had']} "
        f"fetched={stage2_stats['fetched']} "
        f"assemblyai_done={stage2_stats['assemblyai_polled_done']} "
        f"assemblyai_inflight={stage2_stats['assemblyai_in_flight']} "
        f"assemblyai_submitted={stage2_stats['assemblyai_submitted']} "
        f"skipped={stage2_stats['skipped']}"
    )

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

    # Parse "Batch ID: msgbatch_XXX" — pipeline_batch.py uses the `logging`
    # module which writes to stderr by default, so check both streams.
    m = re.search(r"Batch ID:\s*(msgbatch_\w+)", (result.stdout or "") + (result.stderr or ""))
    if not m:
        log.error(f"  could not find batch ID. stdout: {result.stdout[-300:]}\n  stderr: {result.stderr[-300:]}")
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
    print(f"Customers deployed:        {s.customers_deployed}")
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
        n_sermons, n_artifacts, n_pages = finish_batch(args.batch_id, preacher_name)
        log.info(f"DONE: {n_sermons} sermons, {n_artifacts} artifacts, {n_pages} pages")
        # Mark this batch as processed
        if state_path.exists():
            state = json.loads(state_path.read_text())
            state.setdefault("processed", []).append({
                "batch_id": args.batch_id,
                "preacher": preacher_name,
                "sermons": n_sermons,
                "artifacts": n_artifacts,
                "pages": n_pages,
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
                n_sermons, n_artifacts, n_pages = finish_batch(batch_id, preacher_name)
                log.info(f"  {preacher_name}: {n_sermons} sermons, {n_artifacts} artifacts, {n_pages} pages")
                state.setdefault("processed", []).append({
                    "batch_id": batch_id, "preacher": preacher_name,
                    "sermons": n_sermons, "artifacts": n_artifacts, "pages": n_pages,
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
