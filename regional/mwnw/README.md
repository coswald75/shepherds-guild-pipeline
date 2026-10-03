# MWNW launch runner (Sovereign Grace Midwest/Northwest, 8 churches)

Builds each church's Sunday sermon into: sermon page (unlisted, noindex), 5 congregation
resources, a regional PDF report, a review packet, and an email DRAFT. **Nothing is ever
sent without Chris's explicit approval** (see "Send gating").

## Schedule (America/Chicago)
| When | What | Where |
|---|---|---|
| Sun 11:00 → Tue 08:00, every 15 min | `tick`: one independent process per church not yet READY (per-church lock; source checks throttled to every 25 min). A late church never blocks the others. | Studio launchd `com.shepherdsguild.mwnw.tick` |
| Mon 21:00 | `status --alert`: READY / MISSING per church (with reason) emailed to Chris | Studio launchd `com.shepherdsguild.mwnw.status` |
| Mon night | `python -m regional.mwnw.week all --week W --site <site worktree>` then `wrangler versions upload --preview-alias sg-midwest` | box (Studio has no node/wrangler) |
| Mon night | `python -m regional.mwnw review` + `drafts` → review packet | box or Studio |
| Tue AM | Chris reviews packet, fixes recipients + writes P1, approves | Chris |
| Tue | prod deploy of the site (needs Chris's OK) → `send --approve` (needs Chris's OK) | — |

## Per-church pipeline (`church K`)
find source (podcast by date / YouTube streams w/ release_timestamp on that Sunday, live_status
done, >35 min / Grace Life site / Providence DB) → reuse an existing DB sermon for that church+date
if present (never double-process) → AssemblyAI transcript → (YouTube) two-stage LLM sermon-bounds
cut, sanity 12–95 min → preacher → decompose → normalize → embed → ingest (is_public=false,
unlisted) → 5 artifacts → PDF. State: `output/mwnw/<week>/<key>/state.json`. Spend cap $4/church.
`--dry` stops before transcription / DB writes. Hard failures alert once per reason.

## Commands
```
python -m regional.mwnw tick                       # what launchd runs
python -m regional.mwnw church star [--dry] [--run sunday|monday] [--week 2026-10-04]
python -m regional.mwnw status [--alert]
python -m regional.mwnw review                     # output/mwnw/<week>/review/index.html
python -m regional.mwnw drafts                     # email_draft.json/.html per church
python -m regional.mwnw.week pages|quotes|dashboard|all --week 2026-10-04 --site /path/to/site
python -m regional.mwnw send --approve [--only k1,k2]   # DO NOT RUN without Chris
```

## Send gating (all must hold, per church)
`--approve` flag; church listed in `output/mwnw/<week>/APPROVED_BY_CHRIS.json`;
`RECIPIENTS_ARE_BEST_GUESS=False` in config.py (flip after Chris fixes recipients); P1
placeholder replaced; church READY with PDF; RESEND key present; every link returns 200;
no existing `sent.json`.

## Email
P1 = Chris's own (placeholder until he writes it). P2/P3 verbatim from Chris. Glossary link
https://sermonsteward.com/hall/glossary ; Spurgeon sample
https://sermonsteward.com/SignificantSermons/spurgeon/sermons/compel-them-to-come-in .
No pricing (MWNW churches are free for at least a year).

## Suggest a change
`templates/partials/suggest_change.html.j2` (enabled with `suggest_change=True` in the page
context; on for MWNW pages only) → edge function `sermon-suggest` →
`public.sermon_suggestions` (RLS on, no policies; review with SQL / dashboard). Never edits pages.
Review queue: `select created_at, sermon_slug, item_label, current_text, suggested_text,
submitter_name, submitter_email from sermon_suggestions where status='new' order by created_at;`

## Studio install
`git fetch <bundle or origin> mwnw-launch && git checkout mwnw-launch && bash scripts/mwnw_install_studio.sh`
(separate `.venv-mwnw`; does not touch selfserve). Uninstall: `--uninstall`.
