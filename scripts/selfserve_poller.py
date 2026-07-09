#!/usr/bin/env python3
"""
selfserve_poller.py — process any PENDING self-serve upload jobs end to end.

A visitor uploads an MP3 at try.sermonsteward.com; the Worker drops a
`self_serve_jobs` row (status='pending') and puts the audio in R2. This poller
(run on a schedule by launchd) picks up each pending job and runs the full
engine — transcribe → decompose → artifacts → report → EMAIL it — via
selfserve_ingest.py.

Idempotent: only touches status='pending' jobs, and the orchestrator flips a
job to 'transcribing'/'processing' immediately, so a later poll won't double-run
one that's already underway.

Env from .env (Anthropic / Voyage / Supabase / AssemblyAI / Resend).
"""
import os
import sys
import subprocess
from datetime import datetime

REPO = "/Users/dad/shepherds-guild/pipeline copy 2"
os.chdir(REPO)
sys.path.insert(0, REPO)
sys.path.insert(0, REPO + "/scripts")
from dotenv import load_dotenv  # noqa: E402
load_dotenv(REPO + "/.env")

from weekly_ingest import supabase  # noqa: E402


def log(msg: str) -> None:
    print(f"[{datetime.now().isoformat(timespec='seconds')}] {msg}", flush=True)


def main() -> int:
    sb = supabase()
    jobs = (sb.table("self_serve_jobs").select("id,name,email")
            .eq("status", "pending").order("created_at").execute().data or [])
    if not jobs:
        log("no pending self-serve jobs. (nothing to do)")
        return 0

    log(f"{len(jobs)} pending self-serve job(s) to process.")
    for j in jobs:
        jid = j["id"]
        log(f"processing job {jid} — {j.get('name')} <{j.get('email')}>")
        r = subprocess.run(
            [sys.executable, "scripts/selfserve_ingest.py", "--job", jid],
            cwd=REPO, capture_output=True, text=True,
        )
        tail = [ln for ln in r.stdout.splitlines() if ln.strip()][-2:]
        for ln in tail:
            log(f"    {ln}")
        if r.returncode != 0:
            log(f"    job {jid} FAILED (exit {r.returncode}): {r.stderr[-200:]}")
    log("Done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
