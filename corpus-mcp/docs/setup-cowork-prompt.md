# One-prompt setup for Cowork / Claude Desktop

This is the fast path for onboarding a pastor who's already running
Cowork (or Claude Desktop with local agent mode enabled). Instead of
asking them to open Finder, edit raw JSON, and quit/restart by hand,
you give them a single prompt that does all of it.

## When to use this doc

- The pastor is on Cowork OR Claude Desktop with local agent / bypass
  permissions enabled for their account.
- They're not comfortable editing config files by hand.
- You (the admin) are texting them the token separately.

If the pastor is on plain Claude Desktop with no local agent mode, use
[setup-claude-desktop.md](setup-claude-desktop.md) instead — that's the
manual config-edit path.

## Pre-flight check

Before sending the prompt, make sure the pastor's Cowork account has
**local agent mode** enabled. Without it, Claude can't read or write
the config file and the prompt will fail at step 2.

In Cowork, that's typically:
- Cowork Settings → Local Agent → toggle on (or similar)
- May require approving permission for the
  `~/Library/Application Support/Claude/` folder

A 1-line heads-up to include in your handover text:

> *"Make sure local agent mode is on for your Cowork account before
> pasting this — otherwise it can't edit the config file."*

## The handover sequence

1. **You text:** *"When you're at your computer let me know — I'll text
   you a token + a setup prompt to paste into Cowork. About a minute."*
2. **Pastor responds** when ready.
3. **You text two messages back-to-back:**
   - **Message 1:** the token alone, on a single line, e.g.
     `sst_AbCdEfGh…`
   - **Message 2:** the prompt below, as a single code block (iMessage
     and Signal both handle this fine; on a phone, long-press the bubble
     to copy the whole thing)
4. **Pastor pastes Message 2 into a Cowork chat, replaces the
   placeholder line with the token from Message 1, sends.**
5. **Cowork edits the config, tells the pastor to quit + reopen.**
6. **Pastor restarts Claude / Cowork, tries one suggested query.**

The whole interaction collapses to: paste, paste, restart, try a query.

## The prompt to send

Copy this entire block (everything between the opening and closing
triple-backticks). Send it as one message after the token message.

````markdown
You are helping me, a pastor, install the Sermon Steward MCP connector
on this machine. Do not ask clarifying questions. Just do the steps
below, report success, and stop.

# My token
sst_PASTE-THE-TOKEN-CHRIS-TEXTED-YOU-HERE

# Steps

1. Determine the Claude Desktop config path:
   - macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`
   - Windows: `%APPDATA%\Claude\claude_desktop_config.json`

2. Read it. If it doesn't exist, treat it as `{"mcpServers": {}}`.

3. Parse the JSON. Inside `mcpServers` (create the key if missing),
   add or overwrite the key `"sermon-steward"` with this exact value,
   substituting my token from above in place of `<TOKEN>`:

   ```json
   {
     "command": "npx",
     "args": [
       "-y",
       "mcp-remote",
       "https://corpus-mcp.chris-386.workers.dev",
       "--header",
       "Authorization: Bearer <TOKEN>"
     ]
   }
   ```

   IMPORTANT:
   - Preserve all other entries in `mcpServers` — do NOT replace the
     whole object, just add/overwrite the `sermon-steward` key.
   - Do NOT touch any other top-level keys in the config
     (preferences, coworkUserFilesPath, etc.).
   - Keep the file as valid JSON. No trailing commas, no comments.

4. Save the file.

5. Report back to me in plain English:
   - Confirm the file was updated and the token was inserted (mask it
     when echoing — show `sst_XYZ…ABC` instead of the whole thing).
   - Tell me to **fully quit Cowork / Claude Desktop** (Cmd+Q on Mac;
     right-click tray icon → Quit on Windows) and reopen it. Note that
     closing the window is NOT enough.
   - Mention that the first launch will spend 10–30 seconds downloading
     `mcp-remote` via npx — that's normal.
   - Tell me that after restart I should look for a hammer/tool icon
     near the message box showing one tool: `ask_corpus`.
   - Tell me that to use it, I should click the "+" or paperclip icon
     → "Use a prompt" → pick **ricky-alcantar-voice**.
   - Give me one suggested first query to verify it works:
     *"Surprise me with three sermon units I might have forgotten."*

If you can't read or write the config file because of permissions, tell
me exactly what permission to grant and stop. Don't try a workaround.
````

## What to expect on the pastor's side

After they paste and send, Cowork should:

1. Ask permission to read `~/Library/Application Support/Claude/` (one
   click to approve, if not already trusted).
2. Read the config file, show a brief summary.
3. Add or overwrite the `sermon-steward` entry.
4. Save the file.
5. Print the restart instructions back to them.

After the pastor restarts and tries the suggested query, Claude should
respond with citations from their actual sermons. If that works, they're
done. If not, they screenshot the response and text you.

## Per-pastor customization for this prompt

When you reuse this for a third / fourth pastor, swap two strings:

1. The `ricky-alcantar-voice` prompt name in step 5 → their own voice
   prompt name (`chris-oswald-voice`, etc.). These are defined in
   `src/prompts/index.ts` and filtered per token.
2. The suggested first query, if you want something tuned to their
   preaching style. Otherwise the "surprise me" query works for any
   pastor.

Everything else stays identical.

## When this prompt won't work

- **Pastor doesn't have local agent mode on.** Cowork can't touch the
  filesystem; the prompt fails at step 2. Have them enable it, or fall
  back to [setup-claude-desktop.md](setup-claude-desktop.md) for a
  manual walkthrough.
- **Pastor pasted the wrong block** (e.g. just the token, not the full
  prompt). Easy to spot — Cowork will say "I don't understand what you
  want me to do." Re-send the prompt.
- **Pastor's `claude_desktop_config.json` is malformed before the edit.**
  The prompt instructs Cowork to refuse a workaround — they'll get a
  specific error. Have them paste the error to you; usually a missing
  comma somewhere.

## Why this works at all

Cowork has local agent mode that gives Claude tool access to read/write
files on the user's machine. Combined with `bypassPermissionsModeEnabled`,
common edits don't require per-action approval. That's the same
mechanism we used during Chris's setup debugging — once it's on, Claude
can act as a config-installer just by being asked to.

The pastor's only real action is pasting and restarting. Everything
else is automation.
