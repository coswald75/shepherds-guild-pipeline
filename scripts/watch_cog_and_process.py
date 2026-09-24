#!/usr/bin/env python3
"""
watch_cog_and_process.py — check Cross of Grace for a newly-uploaded sermon and,
if one is found, run the WHOLE pipeline end to end and publish it live:

    transcribe (if needed) → decompose → 6→5 artifacts → render → deploy

Idempotent and safe to run on a schedule: it only acts on Cross of Grace sermons
that are (a) created in the last few days and (b) not yet decomposed. Anything
already processed is skipped, so running it at 4/6/8pm just no-ops until the new
sermon actually lands.

A sermon that was decomposed but never rendered (a previous run died midway)
is resumed without submitting a second decomposition batch. When PUBLISH_RETRY
is true (the previous Actions run failed, or this is a re-run), sermons that
already rendered are deployed again so a failed wrangler publish is not lost.

Env comes from the repo .env on the Mac. A missing .env is fine when the
runner already has the variables. Set PIPELINE_REPO to point at a checkout
that is not this file's parent directory.

Deploy is handled by scripts/deploy_sermon_pages.py, which builds and runs
`wrangler deploy` itself, so a processed sermon goes all the way to live.

The process exits non-zero if any sermon fails, so GitHub Actions can email.
"""
import os
import sys
import subprocess
from datetime import datetime, timedelta
from pathlib import Path


def _repo_root() -> Path:
    override = os.environ.get("PIPELINE_REPO")
    if override:
        return Path(override).expanduser().resolve()
    return Path(__file__).resolve().parent.parent


REPO_PATH = _repo_root()
REPO = str(REPO_PATH)
os.chdir(REPO)
sys.path.insert(0, REPO)
sys.path.insert(0, str(REPO_PATH / "scripts"))
from dotenv import load_dotenv  # noqa: E402

_env_file = REPO_PATH / ".env"
if _env_file.is_file():
    load_dotenv(_env_file)
else:
    # No .env on GitHub Actions; secrets are already in the environment.
    load_dotenv()

from weekly_ingest import (  # noqa: E402
    supabase, submit_decomposition_batch, finish_batch, Customer, BatchNotFinished,
)
from selfserve_ingest import transcribe, generate_artifacts  # noqa: E402

COG_CHURCH_ID = "f1fc9898-fafd-4289-b6af-ce99dfde23d6"
RECENT_DAYS = 3  # only consider uploads from the last few days (skip old stragglers)


def log(msg: str) -> None:
    print(f"[{datetime.now().isoformat(timespec='seconds')}] {msg}", flush=True)


def _has_audio(row: dict) -> bool:
    return bool(row.get("hosted_audio_url") or row.get("audio_url"))


def _deploy(sid: str) -> None:
    d = subprocess.run(
        [sys.executable, "scripts/deploy_sermon_pages.py", "--sermon-ids", sid],
        cwd=REPO, capture_output=True, text=True,
    )
    if d.returncode != 0:
        raise RuntimeError("deploy failed: " + (d.stderr or d.stdout or "")[-300:])


def _render(sid: str) -> None:
    r = subprocess.run(
        [sys.executable, "generate_sermon_pages.py", "render", sid],
        cwd=REPO, capture_output=True, text=True,
    )
    if r.returncode != 0:
        raise RuntimeError("render failed: " + (r.stderr or r.stdout or "")[-300:])


def _resume_publish(sid: str) -> None:
    """Artifacts, render, deploy for a sermon that is already decomposed."""
    missing = generate_artifacts(sid)
    if missing:
        raise RuntimeError("artifacts still missing: " + ", ".join(missing))
    _render(sid)
    _deploy(sid)


def main() -> int:
    sb = supabase()
    pids = [r["id"] for r in (sb.table("preachers").select("id")
            .eq("church_id", COG_CHURCH_ID).execute().data or [])]
    if not pids:
        log("No Cross of Grace preachers found.")
        return 0

    cutoff = (datetime.utcnow() - timedelta(days=RECENT_DAYS)).isoformat() + "Z"
    base = (sb.table("sermons")
            .select("id,title,date,primary_text,preacher_id,raw_transcript,"
                    "hosted_audio_url,audio_url,decomposed_at,last_rendered_at")
            .in_("preacher_id", pids)
            .gte("created_at", cutoff))
    recent = [r for r in (base.execute().data or []) if _has_audio(r)]
    fresh = [r for r in recent if not r.get("decomposed_at")]
    unrendered = [r for r in recent if r.get("decomposed_at") and not r.get("last_rendered_at")]
    publish_retry = os.environ.get("PUBLISH_RETRY") == "true"
    retry_rows = [r for r in recent if r.get("decomposed_at") and r.get("last_rendered_at")] if publish_retry else []

    if not fresh and not unrendered and not retry_rows:
        log("No new Cross of Grace sermon to process. (nothing to do)")
        return 0

    failed = 0
    handled: set[str] = set()

    if fresh:
        log(f"Found {len(fresh)} new sermon(s) to process.")
    for r in fresh:
        sid = r["id"]
        handled.add(sid)
        pre = (sb.table("preachers").select("name").eq("id", r["preacher_id"])
               .single().execute().data or {}).get("name") or "Unknown"
        try:
            log(f"Processing {sid} — {r['title']} — {pre}")

            if not r.get("raw_transcript"):
                audio = r.get("hosted_audio_url") or r.get("audio_url")
                log("  transcribing via AssemblyAI …")
                text = transcribe(audio)
                sb.table("sermons").update({"raw_transcript": text}).eq("id", sid).execute()
                r["raw_transcript"] = text
                log(f"  transcript chars={len(text)}")

            cust = Customer(
                church_id=COG_CHURCH_ID, church_name="Cross of Grace Church",
                church_slug="cross-of-grace-church", preacher_id=r["preacher_id"],
                preacher_name=pre, ingest_source_type="nucleus",
                podcast_feed_url=None, audio_base_url=None, deploy_target=None,
            )
            bid = submit_decomposition_batch(cust, [r])
            if not bid:
                raise RuntimeError("decomposition submit failed")
            log(f"  batch {bid}; waiting for decomposition …")
            n_s, n_a, n_p = finish_batch(bid, pre)
            log(f"  finish_batch: sermons={n_s} artifacts={n_a} pages={n_p}")

            missing = generate_artifacts(sid)
            if missing:
                raise RuntimeError("artifacts still missing: " + ", ".join(missing))
            log("  artifacts complete")
            _deploy(sid)
            log("  deploy+publish: ok")
        except BatchNotFinished as e:
            failed += 1
            log(
                f"  still waiting on decomposition ({e}). "
                "Do not start a second batch for this sermon. "
                "After it finishes, run Weekly ingest with mode catchup and dry run off. "
                "That job reads the batch from Anthropic, not from this computer."
            )
        except Exception as e:
            failed += 1
            log(f"  ERROR processing {sid}: {e}")

    for r in unrendered:
        sid = r["id"]
        if sid in handled:
            continue
        handled.add(sid)
        try:
            log(f"Resuming unpublished sermon {sid} — {r.get('title')}")
            _resume_publish(sid)
            log("  resume publish: ok")
        except Exception as e:
            failed += 1
            log(f"  ERROR resuming {sid}: {e}")

    for r in retry_rows:
        sid = r["id"]
        if sid in handled:
            continue
        handled.add(sid)
        try:
            log(f"Retrying publish for {sid} — {r.get('title')}")
            _deploy(sid)
            log("  deploy+publish: ok")
        except Exception as e:
            failed += 1
            log(f"  ERROR redeploying {sid}: {e}")

    if failed:
        log(f"Done. {failed} sermon(s) failed.")
        return 1
    log("Done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
