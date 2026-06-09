# OAuth deploy plan — handoff state

**Status:** Code complete + typechecks. **Not deployed. SQL not applied.** Review then approve.

## What got built while you were away

### New files

```
corpus-mcp/
├── OAUTH-DESIGN.md                   ← design doc, read this first
├── OAUTH-DEPLOY-PLAN.md              ← this doc
├── sql/002_oauth_tables.sql          ← migration, not applied
└── src/oauth/
    ├── store.ts                      ← DB helpers, hashing, token issuance
    ├── metadata.ts                   ← discovery endpoints
    ├── register.ts                   ← Dynamic Client Registration
    ├── authorize.ts                  ← /authorize + magic-link callback
    ├── token.ts                      ← /token (code → access_token, refresh)
    └── views.ts                      ← HTML templates (sign-in, error, etc.)
```

### Modified files

- `src/types.ts` — added optional `SUPABASE_ANON_KEY` to `Env`
- `src/auth.ts` — splits authenticate into legacy + OAuth paths based on token prefix. Both old `sst_*` and new `sst_oauth_*` tokens validate. **Your existing token still works.**
- `src/index.ts` — added 7 OAuth routes; 401 responses now carry `WWW-Authenticate` pointing at the discovery endpoint so MCP clients trigger sign-in instead of failing silently
- `.dev.vars.example` — documents the new `SUPABASE_ANON_KEY` secret

### Things I didn't touch

- The deployed Worker is unchanged
- No SQL ran against your Supabase
- Your Claude Desktop config is untouched — your existing `sst_*` token still works
- The `mcp_tokens` table is untouched
- `wrangler.toml` is unchanged (just env vars; the new secret goes in via `wrangler secret put`)

## To deploy, in order

### 1. Read [OAUTH-DESIGN.md](OAUTH-DESIGN.md)

Especially the "Decisions baked into the design" table — flag any you want to change. The "Open questions" section at the bottom has 5 things I made defaults for.

### 2. Apply the SQL migration

Either via the Supabase MCP tool (I can do it on your say-so) or paste `sql/002_oauth_tables.sql` into the Supabase SQL Editor. Creates 4 new tables with RLS enabled (service-role only).

### 3. Add the new Cloudflare secret

```bash
cd corpus-mcp
npx wrangler secret put SUPABASE_ANON_KEY
```

Paste your anon/publishable key. This is the new format `sb_publishable_...` from your Supabase dashboard. Same key your `study-app/.env.local` uses.

### 4. Deploy

```bash
npm run deploy
```

Should bundle slightly bigger than before (~830 KB / ~160 KB gzipped — Source Serif Pro reference adds some bytes; we can optimize later).

### 5. Verify the new endpoints

```bash
URL=https://corpus-mcp.chris-386.workers.dev

# Discovery should return JSON
curl -s "$URL/.well-known/oauth-protected-resource" | python3 -m json.tool
curl -s "$URL/.well-known/oauth-authorization-server" | python3 -m json.tool

# Dynamic Client Registration
curl -s -X POST "$URL/oauth/register" \
  -H "Content-Type: application/json" \
  -d '{"client_name":"test","redirect_uris":["http://localhost:8080/callback"]}' \
  | python3 -m json.tool

# Sign-in page should render
curl -s "$URL/oauth/authorize?client_id=BOGUS&redirect_uri=http://localhost/x&response_type=code&code_challenge=BOGUS" | head -30

# Old MCP path with your existing token still works
curl -s -X POST "$URL" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sst_bMvZmaJB0tZfJDtiaLPeIv5_GH7v-fJmeUbbPeOobl4" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}' \
  | python3 -m json.tool | head -20
```

### 6. End-to-end OAuth test from Claude Desktop

1. Remove the `Bearer ...` line from your `claude_desktop_config.json` so the connector has only `"url": "..."`. (Or remove the connector entirely and re-add.)
2. Restart Claude Desktop
3. The connector should show "Sign in" — click it
4. Magic-link email arrives (rate-limited — be careful)
5. Click link → bounces back → connector is now authenticated
6. Send a test query

If the magic link goes wrong, your existing `sst_*` token in the config still works as fallback; just re-add it.

### 7. (Later) Issue OAuth credentials to Ricky

For the second pastor, no admin work — he just adds the connector URL to his Claude Desktop and walks through the same sign-in flow himself.

## Test plan I'd want to run before declaring this done

| Test | How | Pass criteria |
|---|---|---|
| Discovery JSON shape | curl against both `.well-known` paths | Valid JSON, expected fields present |
| Register → returns client_id | POST /oauth/register | 201 with `client_id` starting `sst_client_` |
| Authorize without auth state | GET /oauth/authorize | HTML page renders, hidden fields present |
| Authorize with bad client_id | GET /oauth/authorize with fake id | Error page, status 400 |
| Email submit fires Supabase Auth | POST /oauth/authorize/email | Email arrives, "Check your email" page renders |
| Magic-link click → code issued | Click email link | Redirects to client redirect_uri with `?code=sst_code_...` |
| Token exchange | POST /oauth/token with code + verifier | Returns access_token starting `sst_oauth_` |
| Bad PKCE verifier | POST /oauth/token with wrong verifier | 400 `invalid_grant` |
| Token works on MCP | POST / with new access_token | tools/list returns one tool |
| Refresh rotation | POST /oauth/token with grant=refresh_token | New access_token; old one rejected |
| Backward compat | POST / with existing `sst_*` token | Still works |

## Known limitations I'd want to revisit

- **No revocation endpoint yet.** `/oauth/revoke` is stubbed in design but not implemented. Manual revocation works via `UPDATE oauth_access_tokens SET revoked_at = now() ...`.
- **No consent screen.** v1 redirects directly to the email form. A "Sermon Steward wants to access your sermon corpus" consent confirmation is a small follow-up.
- **No `prompt=login` or `prompt=none` handling.** Standard OAuth params for forcing re-auth or silent flow. Defer until needed.
- **Magic link emails are Supabase's default styling.** Branded sender requires SMTP config — deferrable.
- **Login state cleanup is opportunistic.** Old `oauth_login_states` and expired codes accumulate until the cleanup function runs. Run `SELECT oauth_cleanup_expired()` periodically (cron or pg_cron) — non-urgent at our scale.
- **No rate limiting on /authorize/email beyond Supabase's email send limit.** Could add per-IP throttle later.
