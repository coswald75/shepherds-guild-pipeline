# Connect Sermon Steward to ChatGPT

This connects your sermon corpus to ChatGPT (web, desktop, or mobile)
so you can ask about your preaching from inside your existing ChatGPT
workflow.

## What you need

- ChatGPT account (Plus, Team, or Enterprise — MCP connectors are not
  available on the free tier as of this writing).
- Your **MCP token** — long string starting with `sst_...`
- Your **MCP server URL** — typically
  `https://corpus-mcp.<your-account>.workers.dev`

## Steps

1. **Open ChatGPT** and sign in.

2. **Find the connectors page.** Click your profile (bottom left) →
   **Settings** → **Connectors** (sometimes nested under "Beta features"
   while MCP is rolling out).

3. **Add a custom MCP server.** Click "Add MCP server" (label varies by
   ChatGPT version; sometimes "Add custom tool").

4. **Fill in the form:**

   - **Name:** Sermon Steward
   - **URL / Endpoint:** the URL the admin gave you
   - **Authentication:** Bearer token / API key
   - **Token / Key:** paste your `sst_...` token

5. **Save and confirm.** ChatGPT will probe the server and show the
   four tools when the handshake succeeds.

6. **Start a new chat.** In the message composer, click the "+" or
   tools menu → enable Sermon Steward for this chat. If your version
   of ChatGPT supports MCP prompts, you can also pick your voice
   prompt from the prompt picker.

   *(If your ChatGPT version doesn't yet expose MCP prompts in the
   picker, you can paste your voice prompt manually as the first
   message. The text is in `docs/voice-prompt-chris.md` (or your
   pastor's equivalent).)*

7. **Ask a question.** Try one of:

   - "Have I used the cemetery-plots illustration before?"
   - "What's my position on growth in the church?"
   - "Surprise me — three things from my older preaching."

## Troubleshooting

**"This connector requires a Plus subscription."**
ChatGPT free tier doesn't support custom MCP connectors yet.

**Connection succeeds but no tools show up.**
ChatGPT may be cached. Refresh the page or restart the app, then
re-open the chat.

**"Internal error" on tool call.**
Often means your token is recognized but Voyage (the embedding service)
returned an error. Ask the admin to check the worker logs.

**ChatGPT cites sermons that don't exist.**
You skipped the voice prompt. Without it, ChatGPT will sometimes invent
plausible-looking citations. Always load the voice prompt first.
