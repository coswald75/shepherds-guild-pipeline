# launchd jobs — Sermon Steward cron

One scheduled job that drives the entire weekly cadence end-to-end.

| File | When | What |
|---|---|---|
| `com.shepherdsguild.weekly.plist` | **Tuesday 8am America/Chicago** | Runs `run_weekly_tuesday.sh`, which submits an Anthropic Batch for every newly-discovered sermon across active customers, waits for it to land (1–2h typical, 24h max), and drives the full 9-stage pipeline: ingest → 8 artifacts per sermon → render main + scraps pages → deploy to sermonsteward.com → refresh `preacher_analysis` (which feeds the theshepherdsguild.com/showcasev4 dashboards). |

The wrapper writes a timestamped log to `logs/weekly-tuesday-YYYYMMDD-HHMM.log`.

## Why Tuesday morning

- **Transcripts ready** — the host's auto-transcription reliably finishes by Tuesday for Sunday-preached sermons. Earlier-week schedules (Sunday evening, Monday morning) frequently miss sermons because the transcript isn't posted yet.
- **One cron tick** — the Anthropic Batch typically completes in 1–2 hours and Tuesday 8am puts the whole pipeline inside business hours, so any errors surface while a human can intervene.
- **No Sunday/Monday split needed** — the older design split discover-submit from process-deploy because of batch latency, but combining them into a single Tuesday tick is simpler and works as long as the batch wait is built into `auto-process` (it is, up to 24h).

## Install (when ready to go live)

```bash
# 1. Copy the .plist into LaunchAgents
cp launchd/com.shepherdsguild.weekly.plist ~/Library/LaunchAgents/

# 2. Load it
launchctl load ~/Library/LaunchAgents/com.shepherdsguild.weekly.plist

# 3. Verify
launchctl list | grep shepherdsguild
```

The wrapper itself stays in this repo at `launchd/run_weekly_tuesday.sh` and the plist references it by absolute path — no need to copy the wrapper into LaunchAgents.

## Uninstall

```bash
launchctl unload ~/Library/LaunchAgents/com.shepherdsguild.weekly.plist
rm ~/Library/LaunchAgents/com.shepherdsguild.weekly.plist
```

## Test fire without waiting for the schedule

```bash
launchctl start com.shepherdsguild.weekly
# then tail the log (the wrapper writes timestamped logs)
ls -t "/Users/dad/shepherds-guild/pipeline copy 2/logs/" | head -1 | xargs -I{} tail -f "/Users/dad/shepherds-guild/pipeline copy 2/logs/{}"
```

Or — run the wrapper directly without launchd:

```bash
bash "/Users/dad/shepherds-guild/pipeline copy 2/launchd/run_weekly_tuesday.sh"
```

## Prerequisites before loading

1. **`churches.auto_publish = true`** on every customer you want the cron to ingest, otherwise the cron runs but finds no active customers.
2. **`.env` populated** at `/Users/dad/shepherds-guild/pipeline copy 2/.env` with `ANTHROPIC_API_KEY`, `SUPABASE_URL`, `SUPABASE_KEY`, `VOYAGE_API_KEY`, `ASSEMBLYAI_API_KEY`.
3. **Python 3.10+** at `/usr/local/bin/python3` (`which python3` to confirm).
4. **Deploy repo cloned** to `/Users/dad/shepherds-guild/sermon-steward/` with push access via the iMac's git credentials.
5. **iMac set to never sleep** at the scheduled hour — System Preferences → Battery / Energy Saver. If the iMac is asleep at 8am Tuesday, launchd will fire on wake but the wrapper may run at an inconvenient time.

## Why launchd instead of cron

launchd survives reboots and respects macOS's power-management more gracefully than cron. If the iMac is asleep at the scheduled time and the job doesn't fire, launchd will fire it on wake (with the right setting); cron won't.

## Time zone

`StartCalendarInterval` uses the system's local time zone. The iMac should be set to America/Chicago (Central) for these schedules to make sense.

## What new clients need (one-time setup)

See the canonical onboarding checklist at:
`/Users/dad/Obsidian/Sermon_Vault/Sermon Steward/Customer Pipeline Workflow.md` § 5.

In short: one `churches` row + one `preachers` row + one voice-style-guide MD + one entry in `CHURCH_COPY` (in `scripts/build_church_home_pages.py`). After that, the Tuesday cron auto-runs the new client without further code changes.
