#!/bin/bash
# Tuesday-AM weekly ingest wrapper.
#
# Drives the full 9-stage pipeline end-to-end for every customer with
# churches.auto_publish=true. Submits an Anthropic Batch for any newly-
# discovered sermon transcripts, waits for the batch to complete (typical
# 1-2h, max 24h), then ingests, artifacts, renders, deploys, and refreshes
# preacher_analysis.
#
# Designed to run from launchd. Logs land in logs/ with the cron timestamp.
#
# WHY TUESDAY MORNING:
#   - Gives the host's auto-transcription time to finish (Sunday-preached
#     sermons reliably have transcripts on the host by Tuesday).
#   - Anthropic Batch latency completes during business hours so any
#     errors are caught while a human can intervene.
#   - One cron tick covers the whole flow — no Sunday-evening + Monday-
#     morning split.

set -euo pipefail

REPO_ROOT="/Users/dad/shepherds-guild/pipeline copy 2"
LOG_DIR="$REPO_ROOT/logs"
TS=$(date +%Y%m%d-%H%M)
LOG="$LOG_DIR/weekly-tuesday-$TS.log"

mkdir -p "$LOG_DIR"

cd "$REPO_ROOT"

{
  echo "═══ weekly_ingest run started at $(date) ═══"
  echo ""

  echo "── Stage 1-3: discover, transcribe-prep, submit batch ──"
  python3 weekly_ingest.py weekly

  echo ""
  echo "── Stage 4-9: wait → process → artifacts → render → deploy → analysis ──"
  # auto-process waits for any pending batches (up to 24h), then runs
  # finish_batch for each — which fires all of stages 4 through 9.
  python3 weekly_ingest.py auto-process

  echo ""
  echo "═══ weekly_ingest run completed at $(date) ═══"
} >> "$LOG" 2>&1
