# Connect Sermon Steward to Claude Desktop / Cowork

This connects your sermon corpus to the Claude Desktop app (and Claude
Cowork, which uses the same config) so you can ask questions about your
preaching in any conversation.

## What you need

- **Claude Desktop** installed (https://claude.ai/download). If you're
  on Cowork, that's the same app.
- **Your MCP token** — a long string starting with `sst_…` that Chris
  sent you. Treat it like a password.
- **Node.js + npx** on your machine. macOS likely has this already; if
  not, install Node from https://nodejs.org (LTS is fine).

You do not need to install anything else. The `mcp-remote` shim that
talks to the Sermon Steward server is fetched on first use by `npx`.

## Steps

### 1. Open the Claude Desktop config file

**macOS:** open Finder, press `⌘⇧G`, paste this path, hit Return:
```
~/Library/Application Support/Claude/claude_desktop_config.json
```

**Windows:** open Explorer and go to
`%APPDATA%\Claude\claude_desktop_config.json`.

Right-click the file → Open With → TextEdit (or any text editor).

If the file doesn't exist yet, create it with just `{}` inside.

### 2. Add the Sermon Steward connector

Paste this in, replacing `<YOUR-TOKEN>` with the `sst_…` string Chris
sent you (keep the `Bearer ` prefix, just swap the token):

```json
{
  "mcpServers": {
    "sermon-steward": {
      "command": "npx",
      "args": [
        "-y",
        "mcp-remote",
        "https://corpus-mcp.chris-386.workers.dev",
        "--header",
        "Authorization: Bearer <YOUR-TOKEN>"
      ]
    }
  }
}
```

If you already have entries under `mcpServers`, add `sermon-steward`
as a sibling — don't replace the whole object.

Save the file.

### 3. Fully quit Claude Desktop and reopen it

On Mac: **⌘Q** in the Claude window (not just close — closing the
window leaves the app running and the config doesn't reload). Wait
until the Claude icon disappears from the Dock, then re-open it.

On Windows: right-click the Claude icon in the system tray → Quit.

The first time the connector starts, `npx` will download `mcp-remote`
in the background. This takes 10–30 seconds. Be patient — no error
message means it's working.

### 4. Confirm the tool is loaded

In a new chat, look for a hammer / tool icon near the message box. It
should show one tool: **`ask_corpus`**. If you don't see it, see
Troubleshooting below.

### 5. Load your voice prompt

Click the "+" or paperclip icon by the message box → choose **"Use a
prompt"** → pick your own name's voice prompt (e.g. *"ricky-alcantar-voice"*
or *"chris-oswald-voice"*). This loads the trust contract + voice
notes so Claude knows how to use the corpus well.

You only see your own voice prompt — the others are filtered out by
your token.

### 6. Try a question

Ask one of these to confirm it's working. Claude should call the
corpus tool and cite specific sermons by title and date:

- *"Have I ever preached on Ephesians 4?"*
- *"List my 3 most recent sermons."*
- *"Surprise me with three things I might have forgotten preaching about."*
- *"What did I say about Titus 1:5–9?"*

If Claude responds with citations from your own sermons, you're done.

## Troubleshooting

**Nothing happens when I quit/reopen — no tools show up.**
- Most common cause: the JSON config has a syntax error. Paste it into
  https://jsonlint.com to check for typos (missing commas, unbalanced
  braces).
- Second most common: you closed the Claude window but didn't actually
  quit the app. Press ⌘Q (Mac) or quit from the system-tray menu
  (Windows), wait for the Dock/tray icon to disappear, then re-open.

**"Authorization failed" or "Token not recognized."**
- Token may be wrong, expired, or revoked. Double-check you copied the
  full token (no missing characters at the start or end). If it still
  fails, text Chris and he'll issue a new one.

**Multiple browser tabs popping up asking me to sign in.**
- This means your config does NOT have the `--header` line. Re-check
  step 2. The `--header "Authorization: Bearer …"` argument is what
  tells `mcp-remote` to skip OAuth and use your token directly.
- If it's still happening with `--header` present, kill any stray
  `mcp-remote` processes in Terminal: `pkill -f mcp-remote`, then fully
  quit and reopen Claude Desktop.

**Claude makes up sermons (cites titles that aren't yours).**
- You probably didn't load your voice prompt (step 5). Without it,
  Claude will sometimes synthesize "in the spirit of" your preaching.
  Always load your voice prompt at the start of a research session.

**"Tool not available" or the hammer icon doesn't appear.**
- The first launch downloads `mcp-remote` from npm; give it 30 seconds
  on the first start. If it still doesn't appear, check that you have
  `npx` available by opening Terminal and running `npx --version`. If
  that fails, install Node.js from https://nodejs.org.

## Privacy

Your queries travel: Claude Desktop → Anthropic's servers → the Sermon
Steward MCP server → your Supabase project. Your sermon content stays
in Supabase. The MCP server holds no per-pastor data of its own — only
the token-to-preacher mapping.

Your token gives access only to **your own** sermons. Other pastors'
material is invisible to your session by design (Row-Level Security
on the database).
