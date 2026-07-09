#!/usr/bin/env python3
"""
selfserve_ingest.py — the engine behind the Sermon Steward "drop an MP3, get a
report" landing-page CTA.

Given a prospect (name / church / email) and an audio file or URL, this runs the
WHOLE pipeline synchronously (so it's near-real-time, not the 1–2 hr batch):

    transcribe (AssemblyAI) → decompose → embed → ingest → 6 artifacts
        → PDF report → email the report via Resend

It also creates the prospect's Supabase records (a church + preacher, both
auto_publish=false / is_public=false so they never leak into the cron or the
customer dashboards) and a `self_serve_jobs` row that doubles as the lead record
and the job-status tracker.

Usage
-----
  # New job from a local MP3 (what the test + a queued upload look like):
  python3 scripts/selfserve_ingest.py --name "Jane Doe" --church "Grace Chapel" \
      --email "jane@example.com" --audio-file "/path/to/sermon.mp3"

  # Audio already in R2:
  python3 scripts/selfserve_ingest.py --name ... --church ... --email ... \
      --audio-url "https://sermons-cdn.sermonsteward.com/self-serve/<id>.mp3"

  # Re-run an existing pending job (what the poller calls):
  python3 scripts/selfserve_ingest.py --job <job_id>

Flags: --no-email (build but don't send), --keep (don't delete records on error).

Env (.env): ANTHROPIC_API_KEY, VOYAGE_API_KEY, SUPABASE_URL, SUPABASE_KEY,
ASSEMBLYAI_API_KEY, and (for sending) RESEND_API_KEY + RESEND_FROM.
"""
from __future__ import annotations

import argparse
import base64
import json
import logging
import os
import re
import subprocess
import sys
import uuid
from datetime import date as date_cls, datetime
from pathlib import Path
from typing import Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from dotenv import load_dotenv  # noqa: E402
load_dotenv(REPO_ROOT / ".env")

import requests  # noqa: E402
from pipeline import decompose_sermon, embed_units, ingest_sermon, get_supabase  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s",
                    datefmt="%H:%M:%S")
log = logging.getLogger("selfserve")

R2_BUCKET = "sermon-steward-audio"
R2_PUBLIC_BASE = "https://sermons-cdn.sermonsteward.com"
ARTIFACT_TYPES = ("small_group_questions", "daily_readings",
                  "family_card", "couples_guide", "memory_verse")


# ── small helpers ────────────────────────────────────────────────────────────

def slugify(s: str) -> str:
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", (s or "").lower())).strip("-")


def set_status(sb, job_id: str, status: str, **fields):
    fields["status"] = status
    fields["updated_at"] = datetime.utcnow().isoformat() + "Z"
    sb.table("self_serve_jobs").update(fields).eq("id", job_id).execute()
    log.info(f"  job {job_id[:8]} → {status}")


# ── prospect records ─────────────────────────────────────────────────────────

def ensure_prospect(sb, name: str, church_name: Optional[str]) -> tuple[str, str]:
    """Create a fresh prospect church + preacher. auto_publish/is_public stay
    false so they never enter the cron or customer-facing aggregates. Returns
    (church_id, preacher_id)."""
    # Prospect slugs must be globally unique (preachers.slug has a unique
    # constraint, and the name may already exist), so suffix with a short token.
    suffix = uuid.uuid4().hex[:6]
    cname = (church_name or f"{name}'s Church").strip()
    cslug = f"{slugify(cname) or 'self-serve-church'}-{suffix}"
    church = sb.table("churches").insert({
        "name": cname, "slug": cslug, "brand": "sermon_steward",
        "auto_publish": False, "is_public": False,
    }).execute().data[0]

    pslug = f"{slugify(name) or 'self-serve-preacher'}-{suffix}"
    preacher = sb.table("preachers").insert({
        "name": name.strip(), "slug": pslug, "church_id": church["id"],
        "is_public": False, "is_canonical": False,
    }).execute().data[0]
    log.info(f"  prospect: church={church['id'][:8]} preacher={preacher['id'][:8]}")
    return church["id"], preacher["id"]


# ── R2 (best-effort; transcription does not depend on it) ────────────────────

def upload_to_r2(local_path: Path, key: str) -> Optional[str]:
    cmd = ["wrangler", "r2", "object", "put", f"{R2_BUCKET}/{key}",
           "--file", str(local_path), "--content-type", "audio/mpeg", "--remote"]
    env = dict(os.environ)
    r = subprocess.run(cmd, cwd=REPO_ROOT, capture_output=True, text=True, env=env)
    if r.returncode != 0:
        log.warning(f"  R2 upload failed (continuing): {r.stderr[-200:]}")
        return None
    return f"{R2_PUBLIC_BASE}/{key}"


# ── transcription (AssemblyAI, blocking) ─────────────────────────────────────

def transcribe(audio_path_or_url: str) -> str:
    import assemblyai as aai
    aai.settings.api_key = os.environ["ASSEMBLYAI_API_KEY"]
    cfg = aai.TranscriptionConfig(speaker_labels=False, punctuate=True, format_text=True)
    t = aai.Transcriber().transcribe(audio_path_or_url, cfg)  # blocks until done
    if t.status == aai.TranscriptStatus.error:
        raise RuntimeError(f"AssemblyAI error: {t.error}")
    text = (t.text or "").replace("\x00", "").strip()
    if not text:
        raise RuntimeError("AssemblyAI returned empty transcript")
    return text + "\n"


# ── artifacts (subprocess to the proven CLI, with one retry + verify) ────────

def generate_artifacts(sermon_id: str) -> list[str]:
    """Generate all 6 artifact types, retrying once. Returns the list still
    missing after retries (empty == complete)."""
    for attempt in (1, 2):
        present = _present_artifacts(sermon_id)
        missing = [t for t in ARTIFACT_TYPES if t not in present]
        if not missing:
            return []
        for atype in missing:
            cmd = [sys.executable, str(REPO_ROOT / "generate_artifacts.py"),
                   "generate", sermon_id, "--type", atype]
            r = subprocess.run(cmd, cwd=REPO_ROOT, capture_output=True, text=True)
            if r.returncode != 0:
                log.warning(f"  artifact {atype} attempt {attempt} failed: {r.stderr[-160:]}")
    return [t for t in ARTIFACT_TYPES if t not in _present_artifacts(sermon_id)]


def _present_artifacts(sermon_id: str) -> set[str]:
    sb = get_supabase()
    rows = sb.table("sermon_artifacts").select("artifact_type").eq("sermon_id", sermon_id).execute().data or []
    return {r["artifact_type"] for r in rows}


def generate_report(sermon_id: str) -> Path:
    cmd = [sys.executable, str(REPO_ROOT / "scripts" / "generate_sermon_report.py"), sermon_id]
    r = subprocess.run(cmd, cwd=REPO_ROOT, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"report generation failed: {r.stderr[-300:]}")
    # The script prints the pdf path on the last non-empty stdout line.
    path = [ln for ln in r.stdout.splitlines() if ln.strip()][-1].strip()
    p = Path(path)
    if not p.exists():
        raise RuntimeError(f"report path not found: {path}")
    return p


# ── email (Resend) ───────────────────────────────────────────────────────────

def email_template(name: str, title: str) -> tuple[str, str]:
    first = name.split()[0] if name else "there"
    subject = f"Your Sermon Steward report — {title}"
    body = f"""<div style="font-family:Georgia,serif;font-size:15px;color:#1a1a2e;line-height:1.55;max-width:560px">
<p>{first},</p>
<p>Thank you for trying the Shepherd's Guild. We took the sermon you uploaded
&mdash; <strong>&ldquo;{title}&rdquo;</strong> &mdash; transcribed it, studied it,
and turned it into the report attached as a PDF.</p>
<p>Inside you'll find:</p>
<ul>
  <li>A plain-English <strong>summary</strong> of the sermon.</li>
  <li><strong>What we noticed</strong> &mdash; the doctrinal threads, themes, and a few editorial notes.</li>
  <li><strong>Writing prompts, one per point</strong> &mdash; concepts from each main point to explore in your own reading and writing.</li>
  <li>A <strong>sample article in your own voice</strong>, drafted from one of those prompts.</li>
  <li><strong>Resources for your people</strong> &mdash; small-group questions, a family prompt, a prayer, daily readings, and a memory verse.</li>
</ul>
<p>If this is useful, the best thanks is a word to a friend &mdash; do you know any
other pastors who'd love to see their preaching stewarded this way? I'd be glad
to make them one too.</p>
<p>Grateful,<br>Chris<br><span style="color:#6f6f80">The Shepherd's Guild &middot; sermonsteward.com</span></p>
</div>"""
    return subject, body


def send_email(to: str, subject: str, html: str, pdf_path: Path) -> bool:
    key = os.environ.get("RESEND_API_KEY")
    sender = os.environ.get("RESEND_FROM", "Sermon Steward <reports@sermonsteward.com>")
    if not key:
        log.warning("  RESEND_API_KEY not set — email NOT sent (report still generated)")
        return False
    pdf_b64 = base64.b64encode(pdf_path.read_bytes()).decode()
    r = requests.post("https://api.resend.com/emails",
                      headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                      json={"from": sender, "to": [to], "subject": subject, "html": html,
                            "attachments": [{"filename": pdf_path.name, "content": pdf_b64}]})
    if r.status_code >= 300:
        raise RuntimeError(f"Resend {r.status_code}: {r.text[:300]}")
    log.info(f"  email sent to {to} (id={r.json().get('id')})")
    return True


# ── the orchestrator ─────────────────────────────────────────────────────────

def run_job(job_id: str, audio_source: str, no_email: bool = False) -> dict:
    """audio_source: a local file path or an http(s) URL AssemblyAI can read."""
    sb = get_supabase()
    job = sb.table("self_serve_jobs").select("*").eq("id", job_id).single().execute().data
    name, church_name, email = job["name"], job.get("church_name"), job["email"]

    try:
        # 1. prospect records (idempotent-ish: reuse if already created)
        if job.get("preacher_id"):
            preacher_id, church_id = job["preacher_id"], job["church_id"]
        else:
            church_id, preacher_id = ensure_prospect(sb, name, church_name)
            set_status(sb, job_id, "pending", church_id=church_id, preacher_id=preacher_id)

        # 2. transcribe
        set_status(sb, job_id, "transcribing")
        log.info("  transcribing via AssemblyAI …")
        transcript = transcribe(audio_source)
        log.info(f"  transcript: {len(transcript):,} chars")

        # 3. decompose → embed → ingest (synchronous)
        set_status(sb, job_id, "processing")
        log.info("  decomposing …")
        # The model occasionally emits a malformed-JSON glitch (missing comma,
        # etc.) and decompose_sermon parses strictly — a re-ask almost always
        # returns clean JSON, so retry a couple of times before giving up.
        decomp = None
        for attempt in (1, 2, 3):
            try:
                decomp = decompose_sermon(transcript, name)
                break
            except Exception as de:
                log.warning(f"  decompose attempt {attempt} failed: {de}")
                if attempt == 3:
                    raise
        units = decomp.get("units", [])
        log.info(f"  {len(units)} units; embedding …")
        embeddings = embed_units(units)
        sermon_id = ingest_sermon(decomp, preacher_id, embeddings, raw_transcript=transcript)

        # 3b. patch the fields ingest_sermon doesn't set
        title = decomp.get("title") or "Untitled Sermon"
        sdate = decomp.get("date") or date_cls.today().isoformat()
        slug = f"{slugify(title)}-{sdate}"
        sb.table("sermons").update({
            "slug": slug, "date": sdate, "upload_source": "self_serve",
            "audio_url": job.get("audio_url"), "hosted_audio_url": job.get("audio_url"),
            "decomposed_at": datetime.utcnow().isoformat() + "Z",
        }).eq("id", sermon_id).execute()

        # 3c. write the decomposed JSON so the report has full context
        (REPO_ROOT / "output" / f"{sermon_id}_decomposed.json").write_text(
            json.dumps(decomp, indent=2, ensure_ascii=False))
        set_status(sb, job_id, "processing", sermon_id=sermon_id)

        # 4. artifacts (6, with retry + verify)
        log.info("  generating artifacts …")
        missing = generate_artifacts(sermon_id)
        if missing:
            raise RuntimeError(f"artifacts still missing after retries: {missing}")

        # 5. report
        log.info("  building report …")
        pdf = generate_report(sermon_id)
        log.info(f"  report → {pdf}")

        # 6. email
        emailed_at = None
        if not no_email:
            subject, html = email_template(name, title)
            if send_email(email, subject, html, pdf):
                emailed_at = datetime.utcnow().isoformat() + "Z"

        set_status(sb, job_id, "done", sermon_id=sermon_id,
                   report_path=str(pdf), emailed_at=emailed_at)
        return {"ok": True, "sermon_id": sermon_id, "report": str(pdf),
                "title": title, "emailed": bool(emailed_at)}

    except Exception as e:
        log.error(f"  job failed: {e}")
        set_status(sb, job_id, "error", error=str(e)[:500])
        return {"ok": False, "error": str(e)}


# ── CLI ──────────────────────────────────────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--job", help="process an existing self_serve_jobs id")
    ap.add_argument("--name"); ap.add_argument("--church"); ap.add_argument("--email")
    ap.add_argument("--audio-file"); ap.add_argument("--audio-url")
    ap.add_argument("--no-email", action="store_true")
    args = ap.parse_args()

    sb = get_supabase()

    if args.job:
        job = sb.table("self_serve_jobs").select("*").eq("id", args.job).single().execute().data
        source = job.get("audio_url")
        if not source:
            log.error("job has no audio_url and no local file; cannot process"); return 2
        res = run_job(args.job, source, no_email=args.no_email)
    else:
        if not (args.name and args.email and (args.audio_file or args.audio_url)):
            log.error("need --name, --email, and --audio-file or --audio-url"); return 2
        # Create the job (lead) record
        audio_url = args.audio_url
        job = sb.table("self_serve_jobs").insert({
            "name": args.name, "church_name": args.church, "email": args.email,
            "audio_url": audio_url, "status": "pending",
        }).execute().data[0]
        job_id = job["id"]
        log.info(f"created job {job_id}")

        # If a local file was given, store it in R2 (best-effort) and transcribe from it directly.
        source = args.audio_file or audio_url
        if args.audio_file:
            key = f"self-serve/{job_id}.mp3"
            url = upload_to_r2(Path(args.audio_file), key)
            if url:
                sb.table("self_serve_jobs").update({"audio_key": key, "audio_url": url}).eq("id", job_id).execute()
                # transcribe from the local file regardless (reliable, no R2-auth dependency)
        res = run_job(job_id, source, no_email=args.no_email)

    print(json.dumps(res, indent=2))
    return 0 if res.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
