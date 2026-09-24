#!/usr/bin/env python3
"""
check_stuck_sermons.py — read-only check for sermons that stalled mid-pipeline.

This script only SELECTs from Supabase. It never inserts, updates, or deletes.
When it finds a stalled sermon it emails Chris via the Resend HTTP API.
--dry-run and --no-email print the same note and do not send it.

A sermon counts as stuck when it belongs to a church with auto_publish on
and any of these is true, and the relevant timestamp is at least a day old:

  * it has audio, but decomposed_at is still empty
  * it is decomposed, but fewer than 5 congregant resources exist
    (small_group_questions, daily_readings, family_card, couples_guide,
    memory_verse)
  * it is decomposed, but last_rendered_at is empty, so the page was never
    rendered and therefore was not published

--workflow-failure sends a short note about a failed Actions run instead of
querying Supabase. The run link is the --run-url argument.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

CHRIS_EMAIL = "chris@sovgracekc.org"
RESEND_URL = "https://api.resend.com/emails"
STUCK_AFTER = timedelta(hours=24)
EXPECTED_ARTIFACTS = 5
_SECRET_RE = re.compile(r"(re_[A-Za-z0-9]+|Bearer\s+\S+)")


def _parse_ts(value) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _has_audio(row: dict) -> bool:
    return bool((row.get("audio_url") or "").strip() or (row.get("hosted_audio_url") or "").strip())


def classify_sermon(
    row: dict,
    artifact_types: set[str],
    now: datetime,
    stuck_after: timedelta = STUCK_AFTER,
) -> list[str]:
    """Plain-language problems for one sermon, or an empty list if it is fine."""
    title = row.get("title") or "Untitled sermon"
    created = _parse_ts(row.get("created_at"))
    decomposed = _parse_ts(row.get("decomposed_at"))
    rendered = _parse_ts(row.get("last_rendered_at"))
    problems: list[str] = []

    if _has_audio(row) and decomposed is None and created is not None and now - created >= stuck_after:
        problems.append(
            f'"{title}" has audio, but it has not been decomposed for more than a day '
            f"(added {created.date().isoformat()})."
        )

    if decomposed is not None and now - decomposed >= stuck_after:
        count = len(artifact_types)
        if count < EXPECTED_ARTIFACTS:
            problems.append(
                f'"{title}" was decomposed, but only {count} of {EXPECTED_ARTIFACTS} '
                "congregant resources were generated."
            )
        if rendered is None:
            problems.append(
                f'"{title}" was decomposed, but the page was never rendered, '
                "so it was not published to sermonsteward.com."
            )
    return problems


def _scrub(text: str) -> str:
    return _SECRET_RE.sub("[redacted]", text)


def _load_local_env() -> None:
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if not env_path.is_file():
        return
    from dotenv import load_dotenv
    # Do not override variables the runner already set.
    load_dotenv(env_path, override=False)


def _supabase():
    from supabase import create_client
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or os.environ.get("SUPABASE_KEY")
    if not url or not key:
        raise RuntimeError("SUPABASE_URL and SUPABASE_KEY must be set. Nothing was emailed.")
    return create_client(url, key)


def _page(query, page_size: int = 1000) -> list[dict]:
    rows: list[dict] = []
    offset = 0
    while True:
        page = query.range(offset, offset + page_size - 1).execute().data or []
        rows.extend(page)
        if len(page) < page_size:
            return rows
        offset += page_size


def find_stuck(now: datetime | None = None) -> list[str]:
    """Return plain-language lines for stalled sermons. Read-only."""
    now = now or datetime.now(timezone.utc)
    sb = _supabase()
    churches = sb.table("churches").select("id, name").eq("auto_publish", True).execute().data or []
    if not churches:
        return []
    church_ids = [c["id"] for c in churches]
    church_name = {c["id"]: c.get("name") or "the church" for c in churches}
    preachers = (
        sb.table("preachers").select("id, name, church_id").in_("church_id", church_ids).execute().data or []
    )
    if not preachers:
        return []
    preacher_name = {p["id"]: p.get("name") or "" for p in preachers}
    preacher_church = {p["id"]: p.get("church_id") for p in preachers}
    preacher_ids = list(preacher_name)

    sermons: list[dict] = []
    for i in range(0, len(preacher_ids), 50):
        chunk = preacher_ids[i:i + 50]
        sermons.extend(_page(
            sb.table("sermons").select(
                "id, title, date, created_at, audio_url, hosted_audio_url, "
                "decomposed_at, last_rendered_at, preacher_id"
            ).in_("preacher_id", chunk)
        ))

    decomposed_ids = [s["id"] for s in sermons if s.get("decomposed_at")]
    artifacts: dict[str, set[str]] = {sid: set() for sid in decomposed_ids}
    for i in range(0, len(decomposed_ids), 50):
        chunk = decomposed_ids[i:i + 50]
        for row in _page(
            sb.table("sermon_artifacts").select("sermon_id, artifact_type").in_("sermon_id", chunk)
        ):
            artifacts.setdefault(row["sermon_id"], set()).add(row["artifact_type"])

    lines: list[str] = []
    for sermon in sermons:
        problems = classify_sermon(sermon, artifacts.get(sermon["id"], set()), now)
        if not problems:
            continue
        who = preacher_name.get(sermon.get("preacher_id")) or "the preacher"
        where = church_name.get(preacher_church.get(sermon.get("preacher_id"))) or "the church"
        when = sermon.get("date") or "undated"
        for problem in problems:
            lines.append(f"{problem} Preacher: {who}. Church: {where}. Date: {when}. Id: {sermon['id']}.")
    return lines


def failure_message(workflow_name: str, run_url: str) -> tuple[str, str]:
    subject = "Sermon Steward: a pipeline run failed"
    link = run_url.strip() or "(no run link was provided)"
    body = (
        "Chris,\n\n"
        f'The "{workflow_name}" job on GitHub Actions did not finish successfully.\n\n'
        "Open the log to see what stopped:\n"
        f"{link}\n\n"
        "Nothing on the Mac was changed by this email. If the Mac launchd jobs "
        "are still loaded, leave the Actions schedules commented out. The two "
        "must not both be live, or each sermon is processed twice and the site "
        "is deployed twice.\n\n"
        "— Sermon Steward\n"
    )
    return subject, body


def stuck_message(lines: list[str], run_url: str) -> tuple[str, str]:
    count = len(lines)
    subject = "Sermon Steward: a sermon needs attention" if count == 1 else (
        f"Sermon Steward: {count} sermons need attention"
    )
    body = (
        "Chris,\n\n"
        "One or more sermons look stuck partway through the pipeline. "
        "This check only looked; it did not change anything.\n\n"
        + "\n".join(f"{i}. {line}" for i, line in enumerate(lines, start=1))
        + "\n\n"
    )
    if run_url.strip():
        body += f"The check that noticed this:\n{run_url.strip()}\n\n"
    body += (
        "A sermon that has audio but was never decomposed, or was decomposed "
        "but is missing its five congregant resources or its page, is listed above.\n\n"
        "— Sermon Steward\n"
    )
    return subject, body


def send_email(subject: str, body: str) -> None:
    key = os.environ.get("RESEND_API_KEY")
    sender = os.environ.get("RESEND_FROM")
    if not key or not sender:
        raise RuntimeError("RESEND_API_KEY and RESEND_FROM must be set to send mail.")
    payload = json.dumps({
        "from": sender,
        "to": [CHRIS_EMAIL],
        "subject": subject,
        "text": body,
    }).encode()
    request = urllib.request.Request(
        RESEND_URL,
        data=payload,
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "User-Agent": "sermon-steward-pipeline",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            response.read()
    except urllib.error.HTTPError as exc:
        detail = _scrub(exc.read().decode("utf-8", errors="replace")[:500])
        raise RuntimeError(f"Resend returned HTTP {exc.code}: {detail}") from None


def _write_summary(text: str) -> None:
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not path:
        return
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(text)
        if not text.endswith("\n"):
            handle.write("\n")


def _emit(subject: str, body: str, send: bool) -> int:
    print(subject)
    print()
    print(body)
    _write_summary(f"### {subject}\n\n```\n{body}\n```\n")
    if not send:
        print("DRY RUN — email not sent.")
        return 0
    send_email(subject, body)
    print(f"Emailed {CHRIS_EMAIL}.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Print the email instead of sending it.")
    parser.add_argument("--no-email", action="store_true", help="Same as --dry-run.")
    parser.add_argument("--workflow-failure", action="store_true",
                        help="Email that an Actions run failed. Does not query Supabase.")
    parser.add_argument("--run-url", default=os.environ.get("RUN_URL", ""),
                        help="Link to the Actions run, included in the email.")
    parser.add_argument("--workflow-name", default=os.environ.get("GITHUB_WORKFLOW", "pipeline"),
                        help="Name of the workflow that failed.")
    args = parser.parse_args()
    send = not (args.dry_run or args.no_email)

    if args.workflow_failure:
        subject, body = failure_message(args.workflow_name, args.run_url)
        return _emit(subject, body, send)

    _load_local_env()
    try:
        lines = find_stuck()
    except Exception as exc:
        print(f"Stuck-sermon check failed: {exc}", file=sys.stderr)
        return 1
    if not lines:
        print("No sermons are stuck.")
        _write_summary("No sermons are stuck.\n")
        return 0
    subject, body = stuck_message(lines, args.run_url)
    return _emit(subject, body, send)


if __name__ == "__main__":
    raise SystemExit(main())
