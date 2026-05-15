# launchd jobs — Sermon Steward cron

Two scheduled jobs that drive the weekly ingest cadence on Chris's iMac.

| File | When it fires | What it does |
|---|---|---|
| `com.shepherdsguild.weekly.plist` | Sunday 7pm | `weekly_ingest.py weekly` — discovers new sermons across active customers and submits one Anthropic Batch per preacher. Exits immediately (batches are async). |
| `com.shepherdsguild.catchup.plist` | Monday 7am **and** Monday 9am | `weekly_ingest.py weekly --catchup` then `weekly_ingest.py auto-process` — picks up late-uploading customers AND processes any Sunday-night batches that should be done by now (artifacts + render + deploy). The 9am fire is a belt-and-suspenders second pass. |

Both jobs log to `/Users/dad/shepherds-guild/pipeline copy 2/logs/launchd-*.out` and `.err`.

## Install (do this when you're ready to go live)

```bash
# 1. Copy the .plist files into LaunchAgents
cp launchd/*.plist ~/Library/LaunchAgents/

# 2. Load them (registers with launchd; they'll fire at the scheduled time)
launchctl load ~/Library/LaunchAgents/com.shepherdsguild.weekly.plist
launchctl load ~/Library/LaunchAgents/com.shepherdsguild.catchup.plist

# 3. Verify they're loaded
launchctl list | grep shepherdsguild
```

## Uninstall

```bash
launchctl unload ~/Library/LaunchAgents/com.shepherdsguild.weekly.plist
launchctl unload ~/Library/LaunchAgents/com.shepherdsguild.catchup.plist
rm ~/Library/LaunchAgents/com.shepherdsguild.*.plist
```

## Test fire without waiting for the schedule

```bash
launchctl start com.shepherdsguild.weekly
# then tail the log
tail -f "/Users/dad/shepherds-guild/pipeline copy 2/logs/launchd-weekly.out"
```

## Prerequisites before loading

1. **`churches.auto_publish = true`** on Providence and Cross of Grace, otherwise the cron runs but finds no active customers.
2. **`.env` is populated** in `/Users/dad/shepherds-guild/pipeline copy 2/` with `ANTHROPIC_API_KEY`, `SUPABASE_URL`, `SUPABASE_KEY`, `VOYAGE_API_KEY`, `ASSEMBLYAI_API_KEY`.
3. **Python 3.10+** at `/usr/local/bin/python3` (`which python3` to confirm).
4. **`logs/` directory** exists in the pipeline folder (`mkdir -p "/Users/dad/shepherds-guild/pipeline copy 2/logs"`).
5. **The iMac is set to never sleep at the scheduled times.** System Preferences → Battery / Energy Saver → schedule wake or set sleep to "Never" for the relevant hours.

## Why launchd instead of cron

launchd survives reboots and respects macOS's power-management more gracefully than cron. If the iMac is asleep at the scheduled time and the job doesn't fire, launchd will fire it on wake (with the right setting); cron won't.

## Time zone

`StartCalendarInterval` uses the system's local time zone. The iMac should be set to America/Chicago (Central) for these schedules to make sense.
