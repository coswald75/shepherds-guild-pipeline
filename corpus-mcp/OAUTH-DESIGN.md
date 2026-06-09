# OAuth design for corpus-mcp

**Status:** Design — nothing implemented yet. Reviewed and approved before any deployment or migration.

## Why we're doing this

The current setup uses **bearer tokens pasted into config files**. Pastor must:
1. Receive an `sst_...` token out-of-band
2. Open Claude Desktop's `claude_desktop_config.json`
3. Paste the token + URL into JSON
4. Restart the app

This is too much friction for non-technical pastors. We pivot to **OAuth** so pastor setup becomes:

1. In their LLM client → "Add custom connector"
2. Paste our URL: `https://corpus-mcp.chris-386.workers.dev`
3. Click "Sign in with Sermon Steward" → bounces to our login page → bounces back
4. Done — tools and voice prompts appear

No config file editing. No token pasting. The same shape as adding Google Drive or Gmail to Claude.

## OAuth flavor: MCP-spec OAuth 2.1 with PKCE + Dynamic Client Registration

This is what Claude Desktop, Claude.ai, and ChatGPT MCP all implement. Specifically:

- **OAuth 2.1 Authorization Code grant** (with PKCE required, no implicit flow)
- **Dynamic Client Registration** (RFC 7591) so MCP clients register themselves without manual admin work
- **Protected Resource Metadata** (RFC 9728) at `/.well-known/oauth-protected-resource`
- **Authorization Server Metadata** (RFC 8414) at `/.well-known/oauth-authorization-server`

## End-to-end flow

```
┌─────────────────────────────────────────────────────────────────┐
│  Pastor in Claude Desktop                                       │
│  "Add custom connector" → paste corpus-mcp URL                  │
└────────┬────────────────────────────────────────────────────────┘
         │
         │ POST initialize, no auth header
         ▼
┌─────────────────────────────────────────────────────────────────┐
│  corpus-mcp Worker                                              │
│  Returns 401 + WWW-Authenticate header pointing at              │
│  /.well-known/oauth-protected-resource                          │
└────────┬────────────────────────────────────────────────────────┘
         │
         │ Discovery
         ▼
┌─────────────────────────────────────────────────────────────────┐
│  Claude Desktop fetches:                                        │
│    /.well-known/oauth-protected-resource   → tells it the auth  │
│                                              server is the same │
│                                              corpus-mcp host    │
│    /.well-known/oauth-authorization-server → endpoints, scopes  │
└────────┬────────────────────────────────────────────────────────┘
         │
         │ Dynamic client registration
         ▼
┌─────────────────────────────────────────────────────────────────┐
│  POST /oauth/register                                           │
│  → returns { client_id, client_secret? }                        │
│  Claude stores these for future use                             │
└────────┬────────────────────────────────────────────────────────┘
         │
         │ Authorization Code request
         ▼
┌─────────────────────────────────────────────────────────────────┐
│  Claude opens browser to                                        │
│  /oauth/authorize?client_id=...&code_challenge=...&redirect_uri │
└────────┬────────────────────────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────────────────────────────┐
│  Our sign-in page (HTML served from Worker)                     │
│  "Sign in to Sermon Steward to connect Claude"                  │
│  Pastor enters email → magic link sent (Supabase Auth)          │
│  Pastor clicks magic link → returns to /oauth/authorize         │
│  with auth state. We resolve preacher_id, show consent,         │
│  pastor approves → redirect back to Claude with code            │
└────────┬────────────────────────────────────────────────────────┘
         │
         │ Token exchange
         ▼
┌─────────────────────────────────────────────────────────────────┐
│  POST /oauth/token { grant_type, code, code_verifier, ...}     │
│  → returns { access_token, refresh_token?, expires_in }         │
└────────┬────────────────────────────────────────────────────────┘
         │
         │ Tool calls
         ▼
┌─────────────────────────────────────────────────────────────────┐
│  POST / (MCP requests) with Authorization: Bearer <access_token>│
│  Worker validates token → resolves preacher_id → dispatches     │
└─────────────────────────────────────────────────────────────────┘
```

## What we add to the Worker

### New endpoints

| Path | Method | Purpose |
|---|---|---|
| `/.well-known/oauth-protected-resource` | GET | Tells client where the auth server is |
| `/.well-known/oauth-authorization-server` | GET | Tells client the auth endpoints + capabilities |
| `/oauth/register` | POST | Dynamic Client Registration (RFC 7591) |
| `/oauth/authorize` | GET | Shows sign-in page or processes consent |
| `/oauth/authorize/callback` | GET | Magic-link landing point |
| `/oauth/token` | POST | Exchanges code for access_token |
| `/oauth/revoke` | POST | (Optional) Revokes a token |

### New database tables

| Table | Stores |
|---|---|
| `oauth_clients` | Registered MCP clients (Claude Desktop, ChatGPT, etc.) — one row per pastor's install |
| `oauth_authorization_codes` | Short-lived codes (10 min TTL) issued at /authorize, exchanged at /token |
| `oauth_access_tokens` | Issued access tokens, hashed (sha256). Maps to (client_id, preacher_id, scopes, expires_at) |
| `oauth_login_states` | Short-lived state for the magic-link round-trip (5 min TTL) |

### Updated `auth.ts`

Currently looks up `sst_*` bearer tokens in `mcp_tokens`. Adds a branch that, if the token doesn't match `sst_*` prefix, looks it up in `oauth_access_tokens` instead. Both paths return the same `AuthContext` to the rest of the code — fully backward compatible. Existing `sst_*` tokens (e.g. yours) keep working.

### New sign-in page

Simple HTML page served at `/oauth/authorize` (GET, when no `code` param). Shows:

- "Sign in to Sermon Steward to connect to your Claude" header
- Email input
- "Send sign-in link" button
- After submission: "Check your email"

Magic-link click goes to `/oauth/authorize/callback?token=...&state=...`. We:
1. Verify the magic link token via Supabase Auth
2. Resolve the authenticated user's `auth_user_id` → `preachers.id`
3. Generate an authorization code, store it in `oauth_authorization_codes`
4. Redirect back to the OAuth `redirect_uri` (the MCP client) with the code

## What we add to Supabase

Migrations (deferred until approved):
- `oauth_clients`
- `oauth_authorization_codes`
- `oauth_access_tokens`
- `oauth_login_states`

Each with appropriate RLS — service role only (the Worker has it), no anon access.

## Decisions baked into the design

These are choices I made without checking — flag any to change before deployment.

| Decision | Choice | Rationale |
|---|---|---|
| Login mechanism | **Supabase Auth magic link** | Reuses existing infrastructure; pastor doesn't manage a password; consistent with the magic-link path we already designed for /study |
| Authorization Server identity | **Same host as Resource Server** (both at corpus-mcp URL) | Simpler than separate auth server; standard for small MCP deployments |
| Access token format | **Opaque (random, hashed in DB)** | Simpler than JWT for now. Can switch to JWT later if we need self-validation in a CDN edge worker |
| Access token TTL | **30 days** | Long enough that pastors aren't re-authing constantly; short enough that revocation eventually takes effect even without explicit revoke |
| Refresh tokens | **Yes, 90-day TTL** | Standard. Pastor's connector keeps working as long as they use it regularly |
| PKCE | **Required** (S256 only) | OAuth 2.1 mandates it; modern MCP clients send it |
| Scopes | **Single scope: `corpus:read`** for now | We don't have writes; can add scopes later if we add admin or write actions |
| Dynamic Client Registration | **Open** (no pre-approval) | Pastors don't manage clients; their MCP client registers itself silently |
| Consent screen | **Yes, simple "connect this app"** | Required by OAuth norms; lets the pastor confirm they're connecting Claude/ChatGPT and not something else |

## Files to create

```
corpus-mcp/
├── OAUTH-DESIGN.md                    ← this doc
├── sql/002_oauth_tables.sql           ← new migration
├── src/
│   ├── oauth/
│   │   ├── metadata.ts                ← discovery endpoints
│   │   ├── register.ts                ← DCR endpoint
│   │   ├── authorize.ts               ← /authorize + sign-in page + callback
│   │   ├── token.ts                   ← /token endpoint (code → access_token)
│   │   ├── revoke.ts                  ← /revoke (optional)
│   │   ├── store.ts                   ← shared DB helpers
│   │   └── views.ts                   ← HTML pages (sign-in, consent, error)
│   ├── index.ts                       ← MODIFY: route new paths to oauth/ handlers
│   ├── auth.ts                        ← MODIFY: accept OAuth access tokens too
│   └── types.ts                       ← MODIFY: add OAuth types
```

## Test plan (local, before deploy)

1. `wrangler dev` runs the Worker on localhost:8787
2. Use `curl` to exercise:
   - GET `/.well-known/oauth-protected-resource` → expected JSON
   - GET `/.well-known/oauth-authorization-server` → expected JSON
   - POST `/oauth/register` → returns client_id
   - GET `/oauth/authorize?…` → shows sign-in HTML
   - POST magic link submit (mock) → expect email send
   - Simulate magic link click → expect redirect with code
   - POST `/oauth/token` → expect access_token
   - POST `/` with `Authorization: Bearer <access_token>` → expect tools/list to work
3. Backward compat: same probe with the existing `sst_…` bearer token → still works

## Open questions for review

- **Login UI styling.** Want it on-brand (Sermon Steward typography/colors)? Default minimal styling is fine for v1?
- **Email sender.** Supabase Auth sends from `noreply@mail.app.supabase.io` by default. Configure your own SMTP for branded sender? Defer to later?
- **Pastor-not-linked case.** If someone signs in but their `auth.users.id` isn't linked to any `preachers` row, what do we show? Currently I'd reject with an explanatory page. Could also create a "pending" state.
- **Multi-device per pastor.** OAuth flow as designed lets one pastor install on multiple devices (laptop, iPad, ChatGPT). Each install gets its own access_token. Tokens can be revoked individually. Fine?
- **Production secrets.** Need to add Supabase Auth-related secrets (anon key, JWT secret) to Worker env. List in deploy notes.

## What I won't do without your approval

- Apply the SQL migration to Supabase
- Deploy the Worker code change
- Touch existing `mcp_tokens` rows (your token stays valid throughout)
- Modify `claude_desktop_config.json` again

When you're back: read this, tell me to proceed (or what to change), and we cut over.
