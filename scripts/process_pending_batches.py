#!/usr/bin/env python3
"""scripts/process_pending_batches.py
─────────────────────────────────────────────────────────────────────────────
Poll every batch listed in weekly_queue/pending_batches.json and run
`weekly_ingest.py process <batch_id>` for each as soon as Anthropic
reports `processing_status == "ended"`. Drives the Stage-3-to-Stage-7
walk autonomously without the user dispatching each `process` command
by hand.

Use this after every `weekly_ingest.py weekly` run that submits one or
more decomposition batches — that command writes the batch IDs to
`weekly_queue/pending_batches.json` and prints

  Stages 4–8 will run when you invoke:
    python weekly_ingest.py process <batch_id>    # <preacher>

…once per submitted batch. This script is the auto-runner for that.

What it does on each tick (default 60s):
  1. Loads pending_batches.json (the state file weekly_ingest writes).
  2. For each batch not yet processed, asks Anthropic for status.
  3. When a batch is `ended` AND has zero errored requests:
     - shells out to weekly_ingest.py process <batch_id>
     - that runs Stages 4–7 (process → artifacts → render) for that batch
  4. Reports per-batch progress to stdout and to the same persistent log
     directory weekly_ingest uses.
  5. Exits 0 when every batch is processed (or has errors flagged); 1
     if any failed to process.

Designed to be safe to re-run mid-flight: each call to
`weekly_ingest.py process` mutates pending_batches.json (moves the batch
from .batches to .processed), so a relaunch resumes from where it
stopped.

History note: today's first run (2026-06-09 ~07:12) caught a silent-loss
bug — 7 of 12 batches returned sermons=0 because Sonnet 4.6 sometimes
wraps its JSON in preamble/postamble that the previous extractor didn't
handle. Fix is in pipeline_batch.py._extract_json_blob (PR #23). This
script is now safe to use as the default `process` driver after every
weekly cron.

Usage:
    python scripts/process_pending_batches.py [--poll-seconds 60]
                                              [--state-path PATH]
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import anthropic

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_STATE_PATH = REPO_ROOT / "weekly_queue" / "pending_batches.json"


@dataclass
class BatchState:
    preacher_name: str
    batch_id: str
    status: str = "pending"  # pending | processing | processed | failed | aborted
    notes: str = ""


def load_pending(state_path: Path) -> list[BatchState]:
    """Read pending batches from weekly_queue/pending_batches.json.

    Returns the list of (preacher_name, batch_id) that have NOT yet been
    moved to the `processed` array. If the state file is missing or has
    no batches, returns [].
    """
    if not state_path.exists():
        return []
    state = json.loads(state_path.read_text())
    batches = state.get("batches") or {}
    return [BatchState(preacher_name=n, batch_id=bid) for n, bid in batches.items()]


def process_one(state: BatchState) -> None:
    """Shell out to weekly_ingest.py process <batch_id>. Mutates `state`
    in-place to reflect the outcome.
    """
    cmd = [
        sys.executable,
        str(REPO_ROOT / "weekly_ingest.py"),
        "process",
        state.batch_id,
    ]
    state.status = "processing"
    print(
        f"[{time.strftime('%H:%M:%S')}] {state.preacher_name:20s}  → running process …",
        flush=True,
    )
    result = subprocess.run(
        cmd, cwd=REPO_ROOT, capture_output=True, text=True, timeout=3600
    )
    if result.returncode != 0:
        state.status = "failed"
        state.notes = f"process exited {result.returncode}: {result.stderr[-200:].strip()}"
        print(
            f"[{time.strftime('%H:%M:%S')}] {state.preacher_name:20s}  PROCESS FAILED — {state.notes}",
            flush=True,
        )
    else:
        state.status = "processed"
        # Pull the DONE line from weekly_ingest's output (last 3 lines is
        # usually enough — it ends with "DONE: N sermons, N artifacts, …").
        tail = result.stdout.strip().splitlines()[-3:]
        state.notes = " | ".join(t.strip() for t in tail)
        print(
            f"[{time.strftime('%H:%M:%S')}] {state.preacher_name:20s}  PROCESSED — {state.notes[:140]}",
            flush=True,
        )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument(
        "--poll-seconds",
        type=int,
        default=60,
        help="How often to re-check batch status with Anthropic. Default 60s.",
    )
    ap.add_argument(
        "--state-path",
        type=Path,
        default=DEFAULT_STATE_PATH,
        help="Path to weekly_queue/pending_batches.json (default).",
    )
    args = ap.parse_args()

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("ANTHROPIC_API_KEY not set in env", file=sys.stderr)
        return 2

    client = anthropic.Anthropic(api_key=api_key)
    states = load_pending(args.state_path)
    if not states:
        print(f"[{time.strftime('%H:%M:%S')}] no pending batches at {args.state_path}", flush=True)
        return 0

    print(
        f"[{time.strftime('%H:%M:%S')}] orchestrator starting — {len(states)} batch(es) to drive",
        flush=True,
    )
    for s in states:
        print(f"  {s.preacher_name:20s}  {s.batch_id}")

    while any(s.status == "pending" for s in states):
        for s in states:
            if s.status != "pending":
                continue
            try:
                b = client.messages.batches.retrieve(s.batch_id)
            except Exception as e:
                s.status = "failed"
                s.notes = f"retrieve raised: {e}"
                print(
                    f"[{time.strftime('%H:%M:%S')}] {s.preacher_name:20s}  RETRIEVE FAILED — {s.notes}",
                    flush=True,
                )
                continue

            rc = b.request_counts
            if b.processing_status != "ended":
                continue

            if rc.errored:
                s.status = "failed"
                s.notes = f"errored={rc.errored} succeeded={rc.succeeded}"
                print(
                    f"[{time.strftime('%H:%M:%S')}] {s.preacher_name:20s}  BATCH ERRORED — {s.notes}",
                    flush=True,
                )
                continue

            print(
                f"[{time.strftime('%H:%M:%S')}] {s.preacher_name:20s}  ended (succ={rc.succeeded}) → process …",
                flush=True,
            )
            process_one(s)

        still_pending = [s.preacher_name for s in states if s.status == "pending"]
        if still_pending:
            print(
                f"[{time.strftime('%H:%M:%S')}] tick: "
                f"{sum(1 for s in states if s.status == 'processed')} processed, "
                f"{sum(1 for s in states if s.status == 'failed')} failed, "
                f"{len(still_pending)} waiting "
                f"({', '.join(still_pending)[:120]}) — sleeping {args.poll_seconds}s",
                flush=True,
            )
            time.sleep(args.poll_seconds)

    print()
    print("─" * 60)
    print("FINAL")
    print("─" * 60)
    for s in states:
        print(f"  {s.preacher_name:20s}  {s.status:10s}  {s.notes[:140]}")
    failed = [s for s in states if s.status == "failed"]
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
