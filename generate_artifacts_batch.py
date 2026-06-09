"""
generate_artifacts_batch.py
─────────────────────────────────────────────────────────────────────────────
Submit the 6-artifact bundle for N sermons via Anthropic's Message Batches
API. Same prompt structure as generate_artifacts.py (voice + artifact
prompt + sermon facts), all cache_controlled — but 50% cost vs. sync.

For 45 sermons × 6 artifacts = 270 batch requests:
  Sync (claude-haiku-4-5):    ~$54
  Batch (50% off):            ~$27

Three-phase workflow (mirrors pipeline_batch.py):
  Phase 1: SUBMIT  — Build requests → submit to API → persist manifest
  Phase 2: POLL    — Check batch status until complete
  Phase 3: PROCESS — Stream results → JSON-repair → INSERT to sermon_artifacts

Usage:
  # Submit the full 6-artifact bundle for a list of sermons:
  python generate_artifacts_batch.py submit \
      --sermon-ids id1,id2,id3

  # Submit for every sermon by a preacher with date >= cutoff:
  python generate_artifacts_batch.py submit \
      --preacher 9c6f8d69-de55-45db-ac60-0fe6d0cfff59 \
      --since 2025-01-01

  # Just generate one specific artifact type for the batch:
  python generate_artifacts_batch.py submit \
      --sermon-ids id1 \
      --types prayer_prompt,small_group_questions

  # Check status:
  python generate_artifacts_batch.py status msgbatch_01HK...

  # Process results once batch is complete (idempotent — won't re-insert
  # existing artifacts):
  python generate_artifacts_batch.py process msgbatch_01HK...

  # Dry-run submit (build requests + print count; do not call Anthropic):
  python generate_artifacts_batch.py submit --sermon-ids id1 --dry-run

Environment:
  ANTHROPIC_API_KEY, SUPABASE_URL, SUPABASE_KEY (per CLAUDE.md)
─────────────────────────────────────────────────────────────────────────────
"""
from __future__ import annotations

import argparse
import json
import logging
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

# Reuse helpers from the sync version so prompts stay 1:1 identical.
# (Voice profiles, artifact prompts, sermon-facts builder, JSON repair, body
# flattener — all the same; we only swap the transport from messages.create
# to messages.batches.create.)
import generate_artifacts as ga  # noqa: E402

from dotenv import load_dotenv

load_dotenv(override=True)

REPO_ROOT = Path(__file__).resolve().parent
BATCH_DIR = REPO_ROOT / "output" / "artifact_batches"
BATCH_DIR.mkdir(parents=True, exist_ok=True)

# Use the same Haiku model as the sync path. Override via --model if needed.
DEFAULT_MODEL = ga.DEFAULT_MODEL
MAX_OUTPUT_TOKENS = ga.MAX_OUTPUT_TOKENS

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("generate_artifacts_batch")


# ────────────────────────────────────────────────────────────────────────────
# Phase 1: SUBMIT — Build batch requests, post to Anthropic
# ────────────────────────────────────────────────────────────────────────────

def _custom_id(sermon_id: str, artifact_type: str) -> str:
    """
    Anthropic Batch API requires ^[a-zA-Z0-9_-]{1,64}$.
    UUIDs have dashes (legal). Use full sermon UUID + '__' + artifact_type.
    Max length: 36 (uuid) + 2 (sep) + 21 (longest artifact name) = 59 chars.
    """
    cid = f"{sermon_id}__{artifact_type}"
    # Defensive sanitize in case sermon_id ever isn't a clean UUID.
    return re.sub(r"[^a-zA-Z0-9_-]", "-", cid)[:64]


def _parse_custom_id(custom_id: str) -> tuple[str, str]:
    """Inverse of _custom_id — returns (sermon_id, artifact_type)."""
    if "__" not in custom_id:
        raise ValueError(f"malformed custom_id (no '__' separator): {custom_id}")
    sermon_id, artifact_type = custom_id.rsplit("__", 1)
    return sermon_id, artifact_type


def _existing_artifacts(sermon_ids: list[str]) -> set[tuple[str, str]]:
    """Return the set of (sermon_id, artifact_type) pairs that already have
    a row in sermon_artifacts — so we can skip them on submit."""
    if not sermon_ids:
        return set()
    sb = ga.get_supabase()
    res = (
        sb.table("sermon_artifacts")
        .select("sermon_id, artifact_type")
        .in_("sermon_id", sermon_ids)
        .execute()
        .data
        or []
    )
    return {(r["sermon_id"], r["artifact_type"]) for r in res}


def resolve_sermon_ids(
    *,
    explicit_ids: list[str] | None,
    preacher_id: str | None,
    since: str | None,
    only_undecomposed: bool,
) -> list[str]:
    """Pick the sermons to submit. Either explicit, or by preacher + date."""
    sb = ga.get_supabase()
    if explicit_ids:
        # Trust caller; verify they exist + are decomposed (so artifact
        # generation has units/facts to work with).
        ids = [s.strip() for s in explicit_ids if s.strip()]
        res = sb.table("sermons").select("id, decomposed_at").in_("id", ids).execute().data or []
        ready = [r["id"] for r in res if r.get("decomposed_at")]
        not_ready = [r["id"] for r in res if not r.get("decomposed_at")]
        if not_ready:
            log.warning(f"  skipping {len(not_ready)} sermon(s) without decomposed_at — artifacts need a decomposed sermon")
        return ready

    if preacher_id:
        q = sb.table("sermons").select("id, date").eq("preacher_id", preacher_id)
        if since:
            q = q.gte("date", since)
        if only_undecomposed is False:
            q = q.not_.is_("decomposed_at", "null")
        rows = q.order("date", desc=True).execute().data or []
        return [r["id"] for r in rows]

    log.error("must pass either --sermon-ids or --preacher")
    sys.exit(2)


def build_batch_requests(
    sermon_ids: list[str],
    artifact_types: list[str],
    *,
    model: str,
    skip_existing: bool,
) -> tuple[list[dict], dict]:
    """Build the list of Anthropic Batch API request objects.

    Returns (requests, manifest). manifest maps custom_id → metadata so the
    process phase can fall back to it if the live DB lookup gets weird.

    Skips (sermon, artifact_type) pairs that already exist in sermon_artifacts
    unless skip_existing=False.
    """
    requests: list[dict] = []
    manifest: dict = {}
    skipped_existing = 0
    skipped_facts_error = 0

    existing = _existing_artifacts(sermon_ids) if skip_existing else set()

    for sermon_id in sermon_ids:
        # Build sermon facts ONCE per sermon — the same facts block goes
        # into every artifact's user prompt for that sermon.
        try:
            facts_dict, facts_text = ga._build_sermon_facts(sermon_id)
        except Exception as e:
            log.warning(f"  skip {sermon_id}: facts build failed — {e}")
            skipped_facts_error += 1
            continue
        preacher_id = facts_dict.get("preacher_id")

        for artifact_type in artifact_types:
            if (sermon_id, artifact_type) in existing:
                skipped_existing += 1
                continue

            blocks, _voice_version = ga._system_prompt(artifact_type, facts_text, preacher_id)
            user_message = (
                f"Generate the {artifact_type.replace('_', ' ')} artifact for the sermon "
                f"described above. Output ONLY a single JSON object matching the schema "
                f"in the artifact specification. No markdown fences. No commentary."
            )

            requests.append({
                "custom_id": _custom_id(sermon_id, artifact_type),
                "params": {
                    "model": model,
                    "max_tokens": MAX_OUTPUT_TOKENS,
                    "system": blocks,
                    "messages": [{"role": "user", "content": user_message}],
                },
            })

            manifest[_custom_id(sermon_id, artifact_type)] = {
                "sermon_id": sermon_id,
                "artifact_type": artifact_type,
                "preacher_id": preacher_id,
                "title": facts_dict.get("title"),
                "date": facts_dict.get("date"),
            }

    log.info(
        f"Built {len(requests)} batch requests "
        f"({skipped_existing} skipped: already exist in sermon_artifacts; "
        f"{skipped_facts_error} skipped: facts build failed)"
    )
    return requests, manifest


def submit_batch(
    requests: list[dict],
    manifest: dict,
    *,
    model: str,
    note: str | None = None,
) -> Optional[str]:
    """Submit a built batch to Anthropic. Persists a manifest file alongside."""
    if not requests:
        log.error("No requests to submit")
        return None

    client = ga.get_anthropic()
    log.info(f"Submitting batch of {len(requests)} requests to Anthropic ({model})…")
    start = time.time()
    batch = client.messages.batches.create(requests=requests)
    elapsed = time.time() - start

    log.info(f"Batch submitted in {elapsed:.1f}s")
    log.info(f"  Batch ID:   {batch.id}")
    log.info(f"  Status:     {batch.processing_status}")
    log.info(f"  Expires:    {batch.expires_at}")

    manifest_path = BATCH_DIR / f"{batch.id}_manifest.json"
    payload = {
        "batch_id": batch.id,
        "model": model,
        "submitted_at": datetime.utcnow().isoformat() + "Z",
        "request_count": len(requests),
        "note": note,
        "manifest": manifest,
    }
    manifest_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    log.info(f"  Manifest:   {manifest_path}")

    return batch.id


# ────────────────────────────────────────────────────────────────────────────
# Phase 2: POLL — Check batch status
# ────────────────────────────────────────────────────────────────────────────

def check_status(batch_id: str, *, wait: bool, poll_interval: int) -> object:
    client = ga.get_anthropic()
    while True:
        batch = client.messages.batches.retrieve(batch_id)
        counts = batch.request_counts
        log.info(
            f"Batch {batch_id}: {batch.processing_status} | "
            f"succeeded={counts.succeeded} errored={counts.errored} "
            f"canceled={counts.canceled} expired={counts.expired} "
            f"processing={counts.processing}"
        )
        if batch.processing_status == "ended":
            return batch
        if not wait:
            return batch
        time.sleep(poll_interval)


# ────────────────────────────────────────────────────────────────────────────
# Phase 3: PROCESS — Stream results, JSON-repair, INSERT to sermon_artifacts
# ────────────────────────────────────────────────────────────────────────────

def _insert_artifact(
    *,
    sermon_id: str,
    artifact_type: str,
    body: dict,
    body_text: str,
    model: str,
    in_tokens: int,
    out_tokens: int,
    voice_version: str,
) -> None:
    """Mirror of generate_artifacts._write_artifact, factored out so the batch
    processor doesn't need to duplicate the upsert logic."""
    sb = ga.get_supabase()
    payload = {
        "sermon_id": sermon_id,
        "artifact_type": artifact_type,
        "body": body,
        "body_text": body_text,
        # Matches sync generate_artifacts.py + the sermon_artifacts_status_check
        # CHECK constraint which only allows
        # ('pending_review', 'approved', 'published', 'skipped').
        "status": "pending_review",
        "generation_model": model,
        "voice_prompt_version": voice_version,
        "input_tokens": in_tokens,
        "output_tokens": out_tokens,
    }
    # Upsert: re-runs replace prior generated rows for the same
    # (sermon_id, artifact_type).
    sb.table("sermon_artifacts").upsert(
        payload, on_conflict="sermon_id,artifact_type"
    ).execute()


def process_batch(
    batch_id: str,
    *,
    dry_run: bool = False,
) -> tuple[int, int, int]:
    """Stream results, parse each, INSERT to sermon_artifacts.

    Returns (succeeded, failed, skipped) counts.
    """
    client = ga.get_anthropic()

    # Load manifest for fallback metadata (in particular, the preacher_id
    # of the parent sermon so we can recompute voice_version).
    manifest_path = BATCH_DIR / f"{batch_id}_manifest.json"
    manifest: dict = {}
    if manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8")).get("manifest", {})
            log.info(f"Loaded manifest: {len(manifest)} entries")
        except Exception as e:
            log.warning(f"Manifest unreadable ({e}) — will recompute per result from DB")

    succeeded = failed = skipped = 0
    log.info(f"Streaming results for batch {batch_id} …")
    for entry in client.messages.batches.results(batch_id):
        cid = entry.custom_id
        try:
            sermon_id, artifact_type = _parse_custom_id(cid)
        except ValueError as e:
            log.warning(f"  skip {cid}: {e}")
            skipped += 1
            continue

        result = entry.result
        if result.type == "errored":
            err = getattr(result, "error", None)
            log.warning(f"  ✗ {sermon_id} {artifact_type}: errored — {err}")
            failed += 1
            continue
        if result.type == "expired":
            log.warning(f"  ✗ {sermon_id} {artifact_type}: expired")
            failed += 1
            continue
        if result.type == "canceled":
            log.warning(f"  ✗ {sermon_id} {artifact_type}: canceled")
            failed += 1
            continue
        if result.type != "succeeded":
            log.warning(f"  ? {sermon_id} {artifact_type}: unknown result.type={result.type}")
            failed += 1
            continue

        msg = result.message
        raw = msg.content[0].text.strip() if msg.content else ""
        if not raw:
            log.warning(f"  ✗ {sermon_id} {artifact_type}: empty response body")
            failed += 1
            continue

        repaired = ga._repair_json(raw)
        try:
            body = json.loads(repaired)
        except json.JSONDecodeError as exc:
            log.warning(f"  ✗ {sermon_id} {artifact_type}: JSON parse failed — {exc}")
            failed += 1
            continue

        try:
            body_text = ga._flatten_body(body, artifact_type)
        except Exception as exc:
            log.warning(f"  ✗ {sermon_id} {artifact_type}: body flatten failed — {exc}")
            failed += 1
            continue

        # Look up preacher_id so voice_version is consistent with the
        # sync generator's accounting.
        preacher_id = (manifest.get(cid) or {}).get("preacher_id")
        if not preacher_id:
            sermon_row = (
                ga.get_supabase()
                .table("sermons")
                .select("preacher_id")
                .eq("id", sermon_id)
                .single()
                .execute()
                .data
            )
            preacher_id = (sermon_row or {}).get("preacher_id")
        _, voice_version = ga._voice_prompt_text(preacher_id)

        in_tokens = msg.usage.input_tokens
        out_tokens = msg.usage.output_tokens

        if dry_run:
            log.info(f"  ✓ DRY {sermon_id} {artifact_type}: would insert ({out_tokens} out tokens)")
            succeeded += 1
            continue

        try:
            _insert_artifact(
                sermon_id=sermon_id,
                artifact_type=artifact_type,
                body=body,
                body_text=body_text,
                model=msg.model,
                in_tokens=in_tokens,
                out_tokens=out_tokens,
                voice_version=voice_version,
            )
            succeeded += 1
            log.info(f"  ✓ {sermon_id[:8]} {artifact_type}: inserted (in={in_tokens} out={out_tokens})")
        except Exception as e:
            log.warning(f"  ✗ {sermon_id} {artifact_type}: insert failed — {e}")
            failed += 1

    log.info("─" * 60)
    log.info(f"Process complete: {succeeded} succeeded, {failed} failed, {skipped} skipped")
    return succeeded, failed, skipped


# ────────────────────────────────────────────────────────────────────────────
# CLI
# ────────────────────────────────────────────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = ap.add_subparsers(dest="cmd", required=True)

    # ─── submit ───
    p_submit = sub.add_parser("submit", help="Build + submit a batch of artifact requests")
    sel = p_submit.add_mutually_exclusive_group(required=True)
    sel.add_argument("--sermon-ids", help="Comma-separated sermon UUIDs")
    sel.add_argument(
        "--preacher",
        help="Submit for every sermon by this preacher_id (with --since to cap by date)",
    )
    p_submit.add_argument("--since", help="When --preacher is set, lower bound on sermons.date (YYYY-MM-DD)")
    p_submit.add_argument(
        "--types",
        default=",".join(ga.ARTIFACT_TYPES),
        help=f"Comma-separated artifact types. Default: all 6 ({','.join(ga.ARTIFACT_TYPES)})",
    )
    p_submit.add_argument("--model", default=DEFAULT_MODEL, help=f"Model id (default {DEFAULT_MODEL})")
    p_submit.add_argument("--force", action="store_true", help="Re-submit pairs that already exist in sermon_artifacts")
    p_submit.add_argument("--dry-run", action="store_true", help="Build requests, print count, do NOT submit")
    p_submit.add_argument("--note", help="Free-form note saved into the manifest file")

    # ─── status ───
    p_status = sub.add_parser("status", help="Check batch processing status")
    p_status.add_argument("batch_id")
    p_status.add_argument("--wait", action="store_true", help="Poll until ended")
    p_status.add_argument("--poll-interval", type=int, default=60, help="seconds between polls when --wait")

    # ─── process ───
    p_process = sub.add_parser("process", help="Stream results from a completed batch and INSERT artifacts")
    p_process.add_argument("batch_id")
    p_process.add_argument("--dry-run", action="store_true", help="Parse + log; do NOT INSERT")

    # ─── list ───
    p_list = sub.add_parser("list", help="List recent batches via the Anthropic API")
    p_list.add_argument("--limit", type=int, default=10)

    args = ap.parse_args()

    if args.cmd == "submit":
        explicit_ids = args.sermon_ids.split(",") if args.sermon_ids else None
        sermon_ids = resolve_sermon_ids(
            explicit_ids=explicit_ids,
            preacher_id=args.preacher,
            since=args.since,
            only_undecomposed=False,
        )
        if not sermon_ids:
            log.error("No sermons resolved from the selection. Nothing to submit.")
            return 1
        log.info(f"Resolved {len(sermon_ids)} sermon(s)")

        artifact_types = [t.strip() for t in args.types.split(",") if t.strip()]
        for t in artifact_types:
            if t not in ga.ARTIFACT_TYPES:
                log.error(f"unknown artifact_type: {t} (valid: {ga.ARTIFACT_TYPES})")
                return 2

        requests, manifest = build_batch_requests(
            sermon_ids,
            artifact_types,
            model=args.model,
            skip_existing=not args.force,
        )
        if not requests:
            log.info("Nothing to submit (all pairs already exist or skipped).")
            return 0

        if args.dry_run:
            log.info(f"DRY RUN — would submit {len(requests)} requests across {len(sermon_ids)} sermons.")
            log.info(f"  approx cost (batch Haiku 4.5):  ${len(requests) * 0.10:.2f}")
            return 0

        batch_id = submit_batch(requests, manifest, model=args.model, note=args.note)
        if not batch_id:
            return 1
        print(f"\nBATCH_ID={batch_id}")
        return 0

    if args.cmd == "status":
        check_status(args.batch_id, wait=args.wait, poll_interval=args.poll_interval)
        return 0

    if args.cmd == "process":
        succeeded, failed, _ = process_batch(args.batch_id, dry_run=args.dry_run)
        return 0 if failed == 0 else 1

    if args.cmd == "list":
        client = ga.get_anthropic()
        page = client.messages.batches.list(limit=args.limit)
        for b in page.data:
            counts = b.request_counts
            log.info(
                f"{b.id} | {b.processing_status} | created={b.created_at} | "
                f"ok={counts.succeeded} err={counts.errored} exp={counts.expired} cancel={counts.canceled}"
            )
        return 0

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
