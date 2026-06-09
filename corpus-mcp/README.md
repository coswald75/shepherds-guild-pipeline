# Sermon Steward MCP server

A Cloudflare Worker that exposes a pastor's own preaching corpus as a
set of tools to any Model Context Protocol client — Claude Desktop,
Claude.ai, or ChatGPT.

**The product idea:** pastors already use Claude or ChatGPT. Instead
of building yet another chat UI, we expose the corpus as a connector
they add once. Then in any normal conversation they can ask "have I
ever preached on X" or "surprise me with something I've forgotten"
and the LLM calls the tools, cites real sermons by title and date,
and refuses to invent material.

## Architecture

```
Pastor's LLM client (Claude Desktop / Claude.ai / ChatGPT)
    │
    │  JSON-RPC 2.0 over HTTP
    │  Authorization: Bearer <sst_...>
    ▼
Cloudflare Worker (this repo)
    │
    ├──► Voyage AI  (embedding queries, voyage-3.5, 1024 dim)
    └──► Supabase   (match_units_for_preacher RPC + sermons + units)
```

The MCP server:
1. Validates the bearer token, looks up which preacher it belongs to.
2. Dispatches the LLM's tool call to one of four implementations.
3. Returns structured citations the LLM can quote and cite.

## Tools exposed

| Tool | Purpose |
|---|---|
| `search_corpus` | Hybrid vector + keyword search across the pastor's units. Filters by rhetorical function, doctrinal loci, scripture text. |
| `get_sermon` | Full sermon record + all units, for context expansion after a relevant hit. |
| `list_recent_sermons` | Reverse-chronological browse, optionally filtered by series or date floor. |
| `surprise_me` | Three random substantive units — for serendipity and resurfacing forgotten material. |

## Prompts exposed

| Prompt | Loads |
|---|---|
| `chris-oswald-voice` | Chris's trust contract, voice notes, MacArthur-on-eschatology exclusion, tool-usage heuristics. |
| `ricky-alcantar-voice` | Skeleton for Ricky — universal trust contract + tool-usage; voice notes are placeholders to customize. |

Prompts are filtered per-pastor: Chris only sees his prompt in the
picker; Ricky only sees his.

## Setup (admin / Chris)

### 1. Apply the SQL migration

In Supabase SQL editor, run `sql/001_create_mcp_tokens.sql`.

This creates the `mcp_tokens` table that stores per-pastor bearer
tokens (hashed; raw never stored).

### 2. Install dependencies

```bash
cd corpus-mcp
npm install
```

### 3. Configure local secrets

Copy `.dev.vars.example` to `.dev.vars` and fill in:
- `SUPABASE_SERVICE_ROLE_KEY` — from Supabase dashboard → Project
  Settings → API → service_role
- `VOYAGE_API_KEY` — from voyageai.com

### 4. Issue a token for yourself

```bash
export SUPABASE_SERVICE_ROLE_KEY=eyJ...
npm run issue-token -- --preacher "Chris Oswald" --label "Chris's laptop"
```

The script prints a token once — copy it. It will not be shown again.

### 5. Run locally to test

```bash
npm run dev
```

This starts the worker at `http://localhost:8787`. Test the handshake:

```bash
curl -s -X POST http://localhost:8787 \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}'
```

You should see a JSON-RPC response with `protocolVersion` and `serverInfo`.

### 6. Deploy to Cloudflare

```bash
# One-time login
npx wrangler login

# Set the production secrets
npx wrangler secret put SUPABASE_SERVICE_ROLE_KEY
npx wrangler secret put VOYAGE_API_KEY

# Deploy
npm run deploy
```

Wrangler will print a `https://corpus-mcp.<your-account>.workers.dev`
URL. That's your MCP server endpoint.

### 7. (Optional) Bind a custom domain

In the Cloudflare dashboard: **Workers & Pages → corpus-mcp →
Settings → Triggers → Add Custom Domain**. Point it at e.g.
`mcp.sermonsteward.com`. DNS auto-provisions if sermonsteward.com is
already on Cloudflare.

## Setup (pastor side)

Hand the pastor:
1. Their MCP server URL (the Cloudflare workers.dev URL, or your custom domain)
2. Their token (the `sst_...` string from issue-token.ts)
3. The appropriate setup doc:
   - **Claude Desktop** → [docs/setup-claude-desktop.md](docs/setup-claude-desktop.md)
   - **Claude.ai (browser/mobile)** → [docs/setup-claude-web.md](docs/setup-claude-web.md)
   - **ChatGPT** → [docs/setup-chatgpt.md](docs/setup-chatgpt.md)

## Security notes

- Raw tokens are never stored. Only SHA-256 hashes.
- Service role key never leaves the worker.
- All preacher data access is scoped by `auth.preacher_id` resolved
  from the token — a token issued to Chris can only read Chris's
  sermons. Cross-tenant access is impossible without issuing a token
  to the wrong preacher.
- To revoke a token: `UPDATE mcp_tokens SET revoked_at = now() WHERE
  preacher_id = '...' AND name = '...'`. Takes effect on the next
  request (no caching).

## Dependencies

This worker depends on these existing pieces of the Sermon Steward
backend:
- `match_units_for_preacher` SQL function — must include the
  `p_doctrinal_loci TEXT[]` parameter from the loci-filter migration.
- `preachers`, `sermons`, `units` tables in their existing schema.

If those aren't present in your Supabase project, restore them before
this worker will work. The `match_units_for_preacher` function is the
critical one — without it `search_corpus` returns empty.

## What's NOT in this server

- **No OAuth.** v1 uses bearer tokens. OAuth is a planned v2.
- **No canonical-preacher search.** The Guild Hall pool (Spurgeon,
  Keller, etc.) isn't wired here yet — it stays in the deferred
  `corpus-query` Edge Function path.
- **No streaming responses.** MCP tool calls are request/response,
  not SSE. The LLM client streams its OWN response back to the user;
  our tool calls are fast enough not to need streaming.
- **No write tools.** The MCP server is read-only. Pastors can't
  delete or modify sermons through it.
