-- Sermon Steward MCP — per-pastor bearer tokens.
--
-- Each row authorizes one MCP client (Chris's laptop, Ricky's iPad, etc.)
-- to call the MCP server as a specific preacher. The raw token is never
-- stored — we hash with SHA-256 and store only the hash, so a database
-- breach can't be used to log in as a pastor.
--
-- Token issuance is server-side (see corpus-mcp/scripts/issue-token.ts);
-- pastors get the raw token once and paste it into their LLM client's
-- MCP connector config.

CREATE TABLE IF NOT EXISTS mcp_tokens (
  id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  token_hash   TEXT NOT NULL UNIQUE,
  preacher_id  UUID NOT NULL REFERENCES preachers(id) ON DELETE CASCADE,
  -- Human-friendly label for the token row ("Chris's laptop", "iPad").
  -- NOT the preacher's name; that lives in preachers.name.
  name         TEXT NOT NULL,
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  last_used_at TIMESTAMPTZ,
  revoked_at   TIMESTAMPTZ,
  -- Optional: who issued it. Nullable so initial bootstrap tokens
  -- (issued by hand before auth is wired) don't require a user.
  issued_by    UUID REFERENCES auth.users(id)
);

CREATE INDEX IF NOT EXISTS idx_mcp_tokens_preacher ON mcp_tokens(preacher_id);
CREATE INDEX IF NOT EXISTS idx_mcp_tokens_last_used ON mcp_tokens(last_used_at)
  WHERE revoked_at IS NULL;

-- RLS: only the service role touches this table. The MCP server runs
-- with the service role key; pastors never query it directly. We still
-- enable RLS so the anon key can't be tricked into reading token rows
-- if it leaks (e.g. via the public site).
ALTER TABLE mcp_tokens ENABLE ROW LEVEL SECURITY;

-- No anon SELECT/INSERT/UPDATE/DELETE policies — service role bypasses RLS.
-- If you ever want pastors to manage their own tokens via the web UI,
-- add a policy like:
--   CREATE POLICY mcp_tokens_owner_select ON mcp_tokens FOR SELECT
--   USING (preacher_id IN (
--     SELECT id FROM preachers WHERE auth_user_id = auth.uid()
--   ));

COMMENT ON TABLE mcp_tokens IS
  'Per-pastor bearer tokens for the Sermon Steward MCP server. Raw token never stored; only SHA-256 hash.';
COMMENT ON COLUMN mcp_tokens.name IS
  'Human-friendly label for the token row (e.g. "Chris''s laptop"). Not the preacher name.';
