-- OAuth tables for corpus-mcp.
--
-- NOT YET APPLIED. Review OAUTH-DESIGN.md and approve before running.
--
-- The schema follows OAuth 2.1 + Dynamic Client Registration (RFC 7591).
-- All sensitive material (secrets, codes, tokens) is stored hashed; raw
-- values never persist to disk after issuance. RLS is enabled on every
-- table — service role only (the Worker carries it).

-- ─── oauth_clients ─────────────────────────────────────────────────────────
-- One row per pastor's MCP install (e.g. Chris's Claude Desktop, Chris's
-- ChatGPT, Ricky's Claude.ai). Created when a client calls /oauth/register.
-- A single pastor will typically have multiple clients over time.

CREATE TABLE IF NOT EXISTS oauth_clients (
  id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  client_id           TEXT NOT NULL UNIQUE,        -- public identifier, sent in OAuth requests
  client_secret_hash  TEXT,                        -- SHA-256 of secret; null for public clients
  client_name         TEXT,                        -- human label provided at registration ("Claude Desktop")
  redirect_uris       TEXT[] NOT NULL,             -- whitelisted callback URLs
  grant_types         TEXT[] NOT NULL DEFAULT ARRAY['authorization_code', 'refresh_token'],
  response_types      TEXT[] NOT NULL DEFAULT ARRAY['code'],
  token_endpoint_auth_method TEXT NOT NULL DEFAULT 'none',  -- 'none' = public client with PKCE
  scope               TEXT NOT NULL DEFAULT 'corpus:read',
  created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
  -- preacher_id is null at registration time — set when the first authorization
  -- code is issued for this client (after user sign-in). Once set, the client
  -- belongs to that pastor and can never be re-bound to another.
  preacher_id         UUID REFERENCES preachers(id) ON DELETE CASCADE,
  revoked_at          TIMESTAMPTZ
);

CREATE INDEX idx_oauth_clients_preacher ON oauth_clients(preacher_id)
  WHERE preacher_id IS NOT NULL AND revoked_at IS NULL;

-- ─── oauth_authorization_codes ─────────────────────────────────────────────
-- Short-lived (10 min TTL) codes issued at /authorize, exchanged at /token.
-- One-time use — deleted on first exchange or expiry.

CREATE TABLE IF NOT EXISTS oauth_authorization_codes (
  code_hash           TEXT PRIMARY KEY,            -- SHA-256 of the code
  client_id           TEXT NOT NULL REFERENCES oauth_clients(client_id) ON DELETE CASCADE,
  preacher_id         UUID NOT NULL REFERENCES preachers(id) ON DELETE CASCADE,
  redirect_uri        TEXT NOT NULL,               -- must match the one used at /token
  scope               TEXT NOT NULL,
  code_challenge      TEXT NOT NULL,               -- PKCE: client-provided
  code_challenge_method TEXT NOT NULL DEFAULT 'S256',
  expires_at          TIMESTAMPTZ NOT NULL,
  created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_oauth_codes_expiry ON oauth_authorization_codes(expires_at);

-- ─── oauth_access_tokens ───────────────────────────────────────────────────
-- Long-lived tokens issued at /token. The token itself is opaque (random
-- 32 bytes, base64url-encoded, prefixed `sst_oauth_`). Hash stored;
-- raw value lives only in the client.

CREATE TABLE IF NOT EXISTS oauth_access_tokens (
  token_hash          TEXT PRIMARY KEY,
  client_id           TEXT NOT NULL REFERENCES oauth_clients(client_id) ON DELETE CASCADE,
  preacher_id         UUID NOT NULL REFERENCES preachers(id) ON DELETE CASCADE,
  scope               TEXT NOT NULL,
  expires_at          TIMESTAMPTZ NOT NULL,
  -- For refresh: a refresh_token_hash that the client uses to mint a new
  -- access_token without re-authenticating. Null if no refresh token issued.
  refresh_token_hash  TEXT UNIQUE,
  refresh_expires_at  TIMESTAMPTZ,
  created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
  last_used_at        TIMESTAMPTZ,
  revoked_at          TIMESTAMPTZ
);

CREATE INDEX idx_oauth_tokens_preacher ON oauth_access_tokens(preacher_id)
  WHERE revoked_at IS NULL;
CREATE INDEX idx_oauth_tokens_refresh ON oauth_access_tokens(refresh_token_hash)
  WHERE refresh_token_hash IS NOT NULL AND revoked_at IS NULL;

-- ─── oauth_login_states ────────────────────────────────────────────────────
-- Short-lived (5 min TTL) state for the magic-link round-trip. When pastor
-- requests sign-in we mint a state, store the in-flight OAuth params here,
-- and pass the state token through the magic link. On click, we look up
-- this row to resume the authorization flow.

CREATE TABLE IF NOT EXISTS oauth_login_states (
  state_hash          TEXT PRIMARY KEY,
  client_id           TEXT NOT NULL,
  redirect_uri        TEXT NOT NULL,
  scope               TEXT NOT NULL,
  code_challenge      TEXT NOT NULL,
  code_challenge_method TEXT NOT NULL DEFAULT 'S256',
  oauth_state         TEXT,                        -- the client's state param, echoed back at redirect
  email               TEXT,                        -- what email we sent the magic link to
  expires_at          TIMESTAMPTZ NOT NULL,
  created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_oauth_login_states_expiry ON oauth_login_states(expires_at);

-- ─── RLS ───────────────────────────────────────────────────────────────────
ALTER TABLE oauth_clients ENABLE ROW LEVEL SECURITY;
ALTER TABLE oauth_authorization_codes ENABLE ROW LEVEL SECURITY;
ALTER TABLE oauth_access_tokens ENABLE ROW LEVEL SECURITY;
ALTER TABLE oauth_login_states ENABLE ROW LEVEL SECURITY;

-- ─── Cleanup helper ────────────────────────────────────────────────────────
-- Optional cron / scheduled job to purge expired codes and login states.
-- The Worker calls this opportunistically; not required for correctness
-- (lookups filter by expires_at anyway).

CREATE OR REPLACE FUNCTION oauth_cleanup_expired() RETURNS void AS $$
BEGIN
  DELETE FROM oauth_authorization_codes WHERE expires_at < now() - interval '1 day';
  DELETE FROM oauth_login_states WHERE expires_at < now() - interval '1 day';
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

COMMENT ON TABLE oauth_clients IS
  'Registered OAuth clients (MCP integrations). One row per pastor''s MCP install.';
COMMENT ON TABLE oauth_authorization_codes IS
  '10-minute TTL codes issued at /authorize, exchanged at /token. One-time use.';
COMMENT ON TABLE oauth_access_tokens IS
  '30-day TTL access tokens. Hashed (SHA-256); raw values only live in the client.';
COMMENT ON TABLE oauth_login_states IS
  '5-minute TTL state for the magic-link round-trip during /authorize.';
