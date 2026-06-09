# Connect Sermon Steward to Claude.ai (browser)

This connects your sermon corpus to the web version of Claude so you can
ask about your preaching from any browser, on any device.

## What you need

- A Claude.ai account (free or Pro; connectors require recent versions)
- Your **MCP token** — a long string starting with `sst_...`
- Your **MCP server URL** — typically
  `https://corpus-mcp.<your-account>.workers.dev`

## Steps

1. **Open Claude.ai** and sign in.

2. **Find the connectors page.** Click your profile (bottom left) →
   **Settings** → **Connectors** (sometimes called "Integrations").

3. **Add a custom connector.** Click "Add custom connector" (or
   "Add MCP server").

4. **Fill in the form:**

   - **Name:** Sermon Steward
   - **URL:** the URL the admin gave you
   - **Authentication:** Bearer token
   - **Token:** paste your `sst_...` token

5. **Save and test.** Claude.ai will try to call `initialize` on the
   server. If it succeeds, you'll see "Connected" and the four tools
   (`search_corpus`, `get_sermon`, `list_recent_sermons`, `surprise_me`)
   listed.

6. **Open a new chat.** Look for the prompt picker or "Use a prompt"
   option in the input area. Select your voice prompt (e.g. *"Chris
   Oswald — Voice"*) before you start asking corpus questions.

7. **Ask a question.** Try one of:

   - "Have I used the cemetery-plots illustration before?"
   - "Pull material on Ephesians 4 for an upcoming sermon."
   - "Surprise me — three things from older than a year ago."

## Troubleshooting

**Connection fails on save.**
The server URL is wrong (typo) or unreachable. Open the URL in a new
browser tab — you should see a plain-text "Sermon Steward MCP
server" landing page. If you see an error there, the server isn't
deployed.

**"Token not recognized" on tool call.**
Token is wrong, expired, or revoked. Re-issue.

**Tools don't show up in chat.**
The connector may be installed but disabled. Check Connectors settings
and make sure Sermon Steward is enabled.

**Mobile / iPad Sunday-morning use:**
Claude.ai works in mobile Safari on iPad. The same connector flows
through; nothing extra to install. Bookmark `claude.ai` to your home
screen for one-tap access.
