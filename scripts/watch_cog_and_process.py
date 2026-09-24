#!/usr/bin/env python3
"""
watch_cog_and_process.py — check Cross of Grace for a newly-uploaded sermon and,
if one is found, run the WHOLE pipeline end to end and publish it live:

    transcribe (if needed) → decompose → 6→5 artifacts → render → deploy

Idempotent and safe to run on a schedule: it only acts on Cross of Grace sermons
that are (a) created in the last few days and (b) not yet decomposed. Anything
already processed is skipped, so running it at 4/6/8pm just no-ops until the new
sermon actually lands.

Env comes from the repo .env (Anthropic / Voyage / Supabase / AssemblyAI / R2).
Deploy is handled by scripts/deploy_sermon_pages.py, which now builds + runs
`wrangler deploy` itself, so a processed sermon goes all the way to live.
"""
import os
import sys
import base64
import subprocess
from datetime import datetime, timedelta, date
from pathlib import Path

import requests

REPO = "/Users/dad/shepherds-guild/pipeline copy 2"
os.chdir(REPO)
sys.path.insert(0, REPO)
sys.path.insert(0, REPO + "/scripts")
from dotenv import load_dotenv  # noqa: E402
load_dotenv(REPO + "/.env")

from weekly_ingest import supabase, submit_decomposition_batch, finish_batch, Customer  # noqa: E402
from selfserve_ingest import transcribe, generate_artifacts  # noqa: E402

COG_CHURCH_ID = "f1fc9898-fafd-4289-b6af-ce99dfde23d6"
RECENT_DAYS = 3  # only consider uploads from the last few days (skip old stragglers)

# ── TEMPORARY (set 2026-09-02): auto-email the per-sermon report to Cross of
#    Grace after it auto-publishes, while Chris is traveling and can't run the
#    PDF + Gmail-draft step by hand each Tuesday. Sends from Sermon Steward
#    <reports@sermonsteward.com> (Resend), reply-to + BCC Chris so he gets a
#    copy of every send. SAFETY: this auto-send switches itself OFF after
#    AUTO_EMAIL_UNTIL so it can never keep emailing clients unattended — after
#    that date the cron reverts to ingest-only and Chris resumes manual drafts.
#    Disable early by setting COG_AUTO_EMAIL_REPORTS=0 in the environment. ──
AUTO_EMAIL_UNTIL = date(2026, 9, 23)          # last day auto-send is allowed
REPORT_RECIPIENTS = ["ricky@crossofgrace.net", "janel@crossofgrace.net"]
REPORT_REPLY_TO = "chris@sovgracekc.org"      # replies route to Chris
REPORT_BCC = "chris@sovgracekc.org"           # Chris gets a copy of each send


def log(msg: str) -> None:
    print(f"[{datetime.now().isoformat(timespec='seconds')}] {msg}", flush=True)


def _auto_email_on() -> bool:
    if os.environ.get("COG_AUTO_EMAIL_REPORTS", "1") == "0":
        return False
    return date.today() <= AUTO_EMAIL_UNTIL


def email_cog_report(sid: str, title: str, date_str: str) -> None:
    """Best-effort: build the per-sermon PDF report and email it to Cross of
    Grace (reply-to + BCC Chris). Never raises — the sermon is already live."""
    try:
        pretty = datetime.strptime(date_str, "%Y-%m-%d").strftime("%b %-d, %Y")
    except Exception:
        pretty = date_str
    try:
        log("  generating report PDF …")
        rc = subprocess.run([sys.executable, "scripts/generate_sermon_report.py", sid],
                            cwd=REPO, capture_output=True, text=True)
        pdf = next((ln.strip() for ln in reversed(rc.stdout.splitlines())
                    if ln.strip().endswith(".pdf")), None)
        if rc.returncode != 0 or not pdf or not Path(pdf).exists():
            log("  report PDF FAILED; email skipped. " + (rc.stderr[-300:] or "")); return

        slug = Path(pdf).stem
        url = f"https://sermonsteward.com/CoGElPaso/sermons/{slug}"
        subject = f'Sermon Steward report — "{title}" ({pretty})'
        html = f"""<div style="font-family:Georgia,serif;font-size:15px;line-height:1.55;color:#1a1a1a">
<p>Hi Ricky and Janel,</p>
<p>Here's the Sermon Steward report for Sunday's message,
<strong>&ldquo;{title}&rdquo;</strong> ({pretty}).</p>
<p>The report opens with a plain-English summary and what we noticed in the ingest,
then a set of article ideas &mdash; one pitch per major point, with one written out
as a full sample article in the preacher's voice &mdash; followed by the congregant
resources (small-group questions, daily readings, family and couples guides, and a
memory verse).</p>
<p>The sermon is also live with its own page and a Facebook-ready share card:<br>
<a href="{url}">{url}</a></p>
<p>Report is attached. Reply here if anything looks off or you'd like a different
angle on any of the pieces.</p>
<p>Grace and peace,<br>Chris</p>
<hr style="border:none;border-top:1px solid #e5e0d5;margin:18px 0">
<p style="font-size:12px;color:#8a8a8a">Sent automatically by Sermon Steward on Chris's behalf. Replies go to Chris.</p>
</div>"""

        key = os.environ.get("RESEND_API_KEY")
        sender = os.environ.get("RESEND_FROM", "Sermon Steward <reports@sermonsteward.com>")
        if not key:
            log("  RESEND_API_KEY not set — report generated but NOT emailed."); return
        payload = {"from": sender, "to": REPORT_RECIPIENTS, "subject": subject, "html": html,
                   "reply_to": REPORT_REPLY_TO, "bcc": [REPORT_BCC],
                   "attachments": [{"filename": Path(pdf).name,
                                    "content": base64.b64encode(Path(pdf).read_bytes()).decode()}]}
        resp = requests.post("https://api.resend.com/emails",
                             headers={"Authorization": f"Bearer {key}",
                                      "Content-Type": "application/json"},
                             json=payload, timeout=60)
        if resp.status_code >= 300:
            log(f"  Resend FAILED {resp.status_code}: {resp.text[:300]}"); return
        log(f"  report emailed to {', '.join(REPORT_RECIPIENTS)} (bcc {REPORT_BCC}, id={resp.json().get('id')})")
    except Exception as e:
        log(f"  report email ERROR (sermon still live): {e}")


def main() -> int:
    sb = supabase()
    pids = [r["id"] for r in (sb.table("preachers").select("id")
            .eq("church_id", COG_CHURCH_ID).execute().data or [])]
    if not pids:
        log("No Cross of Grace preachers found."); return 0

    cutoff = (datetime.utcnow() - timedelta(days=RECENT_DAYS)).isoformat() + "Z"
    rows = (sb.table("sermons")
            .select("id,title,date,primary_text,preacher_id,raw_transcript,hosted_audio_url,audio_url")
            .in_("preacher_id", pids)
            .is_("decomposed_at", "null")
            .gte("created_at", cutoff)
            .execute().data or [])
    rows = [r for r in rows if r.get("hosted_audio_url") or r.get("audio_url")]

    if not rows:
        log("No new Cross of Grace sermon to process. (nothing to do)")
        return 0

    log(f"Found {len(rows)} new sermon(s) to process.")
    for r in rows:
        sid = r["id"]
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
                log("  decomposition submit FAILED; skipping."); continue
            log(f"  batch {bid}; waiting for decomposition …")
            n_s, n_a, n_p = finish_batch(bid, pre)
            log(f"  finish_batch: sermons={n_s} artifacts={n_a} pages={n_p}")

            missing = generate_artifacts(sid)
            log(f"  artifacts missing after backfill: {missing or 'none'}")

            d = subprocess.run([sys.executable, "scripts/deploy_sermon_pages.py",
                                "--sermon-ids", sid], cwd=REPO, capture_output=True, text=True)
            deployed_ok = d.returncode == 0
            log("  deploy+publish: " + ("ok" if deployed_ok
                                        else "FAILED " + d.stderr[-300:]))

            if deployed_ok and _auto_email_on():
                email_cog_report(sid, r["title"], r.get("date") or "")
            elif deployed_ok and os.environ.get("COG_AUTO_EMAIL_REPORTS", "1") != "0":
                log(f"  auto-email window closed (after {AUTO_EMAIL_UNTIL}); report NOT sent.")
        except Exception as e:
            log(f"  ERROR processing {sid}: {e}")
    log("Done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
