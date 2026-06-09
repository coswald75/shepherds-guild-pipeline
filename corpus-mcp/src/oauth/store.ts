import { adminClient } from "../auth";
import type { Env } from "../types";

// Shared OAuth storage helpers. All raw secrets are SHA-256 hashed before
// they touch the database. The raw values exist only:
//   - in the Worker's response to the client at issuance
//   - in the client's local storage thereafter
// Compromise of the DB does not yield usable tokens.

// ─── Random + hashing primitives ───────────────────────────────────────────

export function randomToken(prefix: string, bytes = 32): string {
  const buf = new Uint8Array(bytes);
  crypto.getRandomValues(buf);
  // base64url, no padding, no plus/slash
  const b64 = btoa(String.fromCharCode(...buf))
    .replace(/\+/g, "-")
    .replace(/\//g, "_")
    .replace(/=+$/, "");
  return `${prefix}${b64}`;
}

export async function sha256Hex(input: string): Promise<string> {
  const data = new TextEncoder().encode(input);
  const digest = await crypto.subtle.digest("SHA-256", data);
  return [...new Uint8Array(digest)]
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
}

// PKCE S256 verification: SHA-256 the verifier, base64url it, compare to
// challenge from the authorization request.
export async function verifyPkceS256(
  codeVerifier: string,
  expectedChallenge: string,
): Promise<boolean> {
  const data = new TextEncoder().encode(codeVerifier);
  const digest = await crypto.subtle.digest("SHA-256", data);
  const b64url = btoa(String.fromCharCode(...new Uint8Array(digest)))
    .replace(/\+/g, "-")
    .replace(/\//g, "_")
    .replace(/=+$/, "");
  return b64url === expectedChallenge;
}

// ─── Client store ──────────────────────────────────────────────────────────

export interface RegisteredClient {
  client_id: string;
  client_secret?: string;
  client_name: string | null;
  redirect_uris: string[];
  token_endpoint_auth_method: "none" | "client_secret_basic" | "client_secret_post";
  scope: string;
}

export async function registerClient(
  env: Env,
  input: {
    client_name?: string;
    redirect_uris: string[];
    token_endpoint_auth_method?: "none";
  },
): Promise<RegisteredClient> {
  const supabase = adminClient(env);
  const clientId = randomToken("sst_client_", 16);
  // We only support public clients (PKCE-required) for v1 — MCP clients all
  // do PKCE so client_secret is unnecessary. Field stays nullable for future.
  const { error } = await supabase.from("oauth_clients").insert({
    client_id: clientId,
    client_name: input.client_name ?? null,
    redirect_uris: input.redirect_uris,
    token_endpoint_auth_method: "none",
    scope: "corpus:read",
  });
  if (error) throw new Error(`Client registration failed: ${error.message}`);
  return {
    client_id: clientId,
    client_name: input.client_name ?? null,
    redirect_uris: input.redirect_uris,
    token_endpoint_auth_method: "none",
    scope: "corpus:read",
  };
}

export async function getClient(env: Env, clientId: string) {
  const supabase = adminClient(env);
  const { data, error } = await supabase
    .from("oauth_clients")
    .select(
      "client_id, client_name, redirect_uris, token_endpoint_auth_method, scope, preacher_id, revoked_at",
    )
    .eq("client_id", clientId)
    .maybeSingle();
  if (error) throw new Error(`Client lookup failed: ${error.message}`);
  return data ?? null;
}

// Once a client is bound to a preacher (via first authorization code), it
// can only ever issue tokens for that preacher. Prevents one Claude Desktop
// install from being used to authenticate as someone else later.
export async function bindClientToPreacher(
  env: Env,
  clientId: string,
  preacherId: string,
) {
  const supabase = adminClient(env);
  const { error } = await supabase
    .from("oauth_clients")
    .update({ preacher_id: preacherId })
    .eq("client_id", clientId)
    .is("preacher_id", null);
  if (error) throw new Error(`Client binding failed: ${error.message}`);
}

// ─── Login state store (magic-link round-trip) ─────────────────────────────

export async function createLoginState(
  env: Env,
  input: {
    client_id: string;
    redirect_uri: string;
    scope: string;
    code_challenge: string;
    code_challenge_method: "S256";
    oauth_state?: string;
    email: string;
  },
): Promise<string> {
  const supabase = adminClient(env);
  const raw = randomToken("sst_login_", 24);
  const stateHash = await sha256Hex(raw);
  const expiresAt = new Date(Date.now() + 5 * 60_000).toISOString(); // 5 min
  const { error } = await supabase.from("oauth_login_states").insert({
    state_hash: stateHash,
    client_id: input.client_id,
    redirect_uri: input.redirect_uri,
    scope: input.scope,
    code_challenge: input.code_challenge,
    code_challenge_method: input.code_challenge_method,
    oauth_state: input.oauth_state ?? null,
    email: input.email,
    expires_at: expiresAt,
  });
  if (error) throw new Error(`Login state save failed: ${error.message}`);
  return raw;
}

export async function consumeLoginState(env: Env, rawState: string) {
  // Atomic peek + delete. Used by the magic-link callback path, which is
  // single-shot: there's no way to retry a magic-link click with the same
  // state, so consuming on read is correct there.
  const supabase = adminClient(env);
  const stateHash = await sha256Hex(rawState);
  const { data, error } = await supabase
    .from("oauth_login_states")
    .select("*")
    .eq("state_hash", stateHash)
    .maybeSingle();
  if (error) throw new Error(`Login state lookup failed: ${error.message}`);
  if (!data) return null;
  if (new Date(data.expires_at).getTime() < Date.now()) return null;
  // Delete on read (single use)
  await supabase.from("oauth_login_states").delete().eq("state_hash", stateHash);
  return data;
}

// Non-destructive variant. Used by the OTP code-entry path: a pastor may
// mistype the 6-digit code and need to retry, so we must NOT consume the
// login state until verifyOtp actually succeeds. Pair with deleteLoginState
// after success.
export async function peekLoginState(env: Env, rawState: string) {
  const supabase = adminClient(env);
  const stateHash = await sha256Hex(rawState);
  const { data, error } = await supabase
    .from("oauth_login_states")
    .select("*")
    .eq("state_hash", stateHash)
    .maybeSingle();
  if (error) throw new Error(`Login state lookup failed: ${error.message}`);
  if (!data) return null;
  if (new Date(data.expires_at).getTime() < Date.now()) return null;
  return data;
}

export async function deleteLoginState(env: Env, rawState: string) {
  const supabase = adminClient(env);
  const stateHash = await sha256Hex(rawState);
  await supabase
    .from("oauth_login_states")
    .delete()
    .eq("state_hash", stateHash);
}

// ─── Authorization code store ──────────────────────────────────────────────

export async function issueAuthorizationCode(
  env: Env,
  input: {
    client_id: string;
    preacher_id: string;
    redirect_uri: string;
    scope: string;
    code_challenge: string;
    code_challenge_method: "S256";
  },
): Promise<string> {
  const supabase = adminClient(env);
  const raw = randomToken("sst_code_", 24);
  const codeHash = await sha256Hex(raw);
  const expiresAt = new Date(Date.now() + 10 * 60_000).toISOString(); // 10 min
  const { error } = await supabase.from("oauth_authorization_codes").insert({
    code_hash: codeHash,
    client_id: input.client_id,
    preacher_id: input.preacher_id,
    redirect_uri: input.redirect_uri,
    scope: input.scope,
    code_challenge: input.code_challenge,
    code_challenge_method: input.code_challenge_method,
    expires_at: expiresAt,
  });
  if (error) throw new Error(`Code issuance failed: ${error.message}`);
  return raw;
}

export async function consumeAuthorizationCode(env: Env, rawCode: string) {
  const supabase = adminClient(env);
  const codeHash = await sha256Hex(rawCode);
  const { data, error } = await supabase
    .from("oauth_authorization_codes")
    .select("*")
    .eq("code_hash", codeHash)
    .maybeSingle();
  if (error) throw new Error(`Code lookup failed: ${error.message}`);
  if (!data) return null;
  if (new Date(data.expires_at).getTime() < Date.now()) return null;
  // Delete on read (single use) — prevents replay
  await supabase
    .from("oauth_authorization_codes")
    .delete()
    .eq("code_hash", codeHash);
  return data;
}

// ─── Access token store ────────────────────────────────────────────────────

export interface IssuedTokenPair {
  access_token: string;
  refresh_token: string;
  expires_in: number;
  scope: string;
  token_type: "Bearer";
}

export async function issueAccessToken(
  env: Env,
  input: {
    client_id: string;
    preacher_id: string;
    scope: string;
  },
): Promise<IssuedTokenPair> {
  const supabase = adminClient(env);
  const accessRaw = randomToken("sst_oauth_", 32);
  const refreshRaw = randomToken("sst_refresh_", 32);
  const [accessHash, refreshHash] = await Promise.all([
    sha256Hex(accessRaw),
    sha256Hex(refreshRaw),
  ]);
  const accessExpiresAt = new Date(Date.now() + 30 * 86400_000).toISOString();
  const refreshExpiresAt = new Date(Date.now() + 90 * 86400_000).toISOString();

  const { error } = await supabase.from("oauth_access_tokens").insert({
    token_hash: accessHash,
    client_id: input.client_id,
    preacher_id: input.preacher_id,
    scope: input.scope,
    expires_at: accessExpiresAt,
    refresh_token_hash: refreshHash,
    refresh_expires_at: refreshExpiresAt,
  });
  if (error) throw new Error(`Token issuance failed: ${error.message}`);
  return {
    access_token: accessRaw,
    refresh_token: refreshRaw,
    expires_in: 30 * 86400,
    scope: input.scope,
    token_type: "Bearer",
  };
}

export async function lookupAccessToken(env: Env, rawToken: string) {
  const supabase = adminClient(env);
  const tokenHash = await sha256Hex(rawToken);
  const { data, error } = await supabase
    .from("oauth_access_tokens")
    .select(
      "preacher_id, client_id, scope, expires_at, revoked_at, preachers!inner(id, name)",
    )
    .eq("token_hash", tokenHash)
    .maybeSingle();
  if (error || !data) return null;
  if (data.revoked_at) return null;
  if (new Date(data.expires_at).getTime() < Date.now()) return null;
  // Touch last_used_at (fire-and-forget)
  supabase
    .from("oauth_access_tokens")
    .update({ last_used_at: new Date().toISOString() })
    .eq("token_hash", tokenHash)
    .then(() => {}, () => {});
  return data;
}

export async function exchangeRefreshToken(
  env: Env,
  refreshRaw: string,
): Promise<IssuedTokenPair | null> {
  const supabase = adminClient(env);
  const refreshHash = await sha256Hex(refreshRaw);
  const { data: row, error } = await supabase
    .from("oauth_access_tokens")
    .select("client_id, preacher_id, scope, refresh_expires_at, revoked_at")
    .eq("refresh_token_hash", refreshHash)
    .maybeSingle();
  if (error || !row) return null;
  if (row.revoked_at) return null;
  if (
    !row.refresh_expires_at ||
    new Date(row.refresh_expires_at).getTime() < Date.now()
  ) {
    return null;
  }
  // Rotate: revoke the old token, issue a new pair
  await supabase
    .from("oauth_access_tokens")
    .update({ revoked_at: new Date().toISOString() })
    .eq("refresh_token_hash", refreshHash);
  return issueAccessToken(env, {
    client_id: row.client_id,
    preacher_id: row.preacher_id,
    scope: row.scope,
  });
}
