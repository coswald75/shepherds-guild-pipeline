#!/usr/bin/env python3
"""Choose the weekly-ingest command for this Actions run.

workflow_dispatch uses the inputs. A schedule (kept commented out in the
workflow until Chris turns it on) maps the UTC cron back to Sunday submit
or Monday catchup. GitHub cron is UTC and does not follow daylight saving
time, so both the CDT and the CST conversions are recognized.
"""
from __future__ import annotations

import json
import os
import sys

# Sunday 7:00pm America/Chicago.
SUNDAY_SUBMIT = {
    "0 0 * * 1",  # CDT (UTC-5) → Monday 00:00 UTC
    "0 1 * * 1",  # CST (UTC-6) → Monday 01:00 UTC
}
# Monday 7:00am and 9:00am America/Chicago.
MONDAY_CATCHUP = {
    "0 12 * * 1",  # 7:00am CDT
    "0 13 * * 1",  # 7:00am CST
    "0 14 * * 1",  # 9:00am CDT
    "0 15 * * 1",  # 9:00am CST
}


def decide_cogwatch(event_name: str, dry_run: str) -> dict[str, str]:
    """Cross of Grace watcher. A schedule is always a real run. Dispatch defaults to dry."""
    if event_name == "workflow_dispatch":
        dry = "true" if str(dry_run).lower() == "true" else "false"
    else:
        dry = "false"
    return {"dry_run": dry, "needs_publish": "false" if dry == "true" else "true"}


def decide(event_name: str, mode: str, dry_run: str, schedule: str) -> dict[str, str]:
    """Return mode, dry_run, and needs_publish as the strings Actions outputs use."""
    if event_name == "workflow_dispatch":
        chosen = (mode or "discover-dry-run").strip()
        dry = "true" if str(dry_run).lower() == "true" else "false"
        # This mode is dry by name, even if the checkbox was cleared.
        if chosen == "discover-dry-run":
            dry = "true"
        if chosen not in {"weekly", "catchup", "discover-dry-run"}:
            raise SystemExit(f"Unknown mode {chosen!r}. Use weekly, catchup, or discover-dry-run.")
    else:
        if schedule in SUNDAY_SUBMIT:
            chosen, dry = "weekly", "false"
        elif schedule in MONDAY_CATCHUP:
            chosen, dry = "catchup", "false"
        else:
            raise SystemExit(
                f"Unrecognized schedule {schedule!r}. "
                "Uncomment only one set of cron lines (CDT or CST), not both."
            )
    # Sunday's submit pass does not render or deploy. Monday's catchup does.
    needs_publish = "true" if chosen == "catchup" and dry == "false" else "false"
    return {"mode": chosen, "dry_run": dry, "needs_publish": needs_publish}


def main() -> int:
    event = json.loads(os.environ.get("EVENT_JSON") or "{}")
    schedule = str(event.get("schedule") or "")
    event_name = os.environ.get("EVENT_NAME") or "workflow_dispatch"
    dry_input = os.environ.get("INPUT_DRY_RUN") if os.environ.get("INPUT_DRY_RUN") is not None else "true"
    if os.environ.get("PLAN_KIND") == "cogwatch":
        result = decide_cogwatch(event_name, dry_input)
    else:
        result = decide(
            event_name,
            os.environ.get("INPUT_MODE") or "",
            dry_input,
            schedule,
        )
    text = "".join(f"{key}={value}\n" for key, value in result.items())
    output_path = os.environ.get("GITHUB_OUTPUT")
    if output_path:
        with open(output_path, "a", encoding="utf-8") as handle:
            handle.write(text)
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
