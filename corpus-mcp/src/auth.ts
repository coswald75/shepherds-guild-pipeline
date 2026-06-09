import { createClient } from "@supabase/supabase-js";
import type { AuthContext, Env } from "./types";

// Bearer token auth. Tokens are stored hashed (SHA-256) in mcp_tokens;
// the raw token is only ever held by the pastor. On every request we:
//   1. Pull the `Authorization: Bearer <raw>` header
//   2. Hash the raw token and look it up in mcp_tokens
//   3. Reject if missing, revoked, or expired
//   4. Touch last_used_at (best-effort, fire-and-forget)
//   5. Return preacher_id + name for the request context

export class AuthError extends Error {
  status: number;
  constructor(message: string, status = 401) {
    super(message);
    this.status = status;
  }
}

async function sha256Hex(input: string): Promise<string> {
  const data = new TextEncoder().encode(input);
  const digest = await crypto.subtle.digest("SHA-256", data);
  return [...new Uint8Array(digest)]
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
}

export function adminClient(env: Env) {
  return createClient(env.SUPABASE_URL, env.SUPABASE_SERVICE_ROLE_KEY, {
    auth: { persistSession: false, autoRefreshToken: false },
  });
}

export async function authenticate(
  req: Request,
  env: Env,
): Promise<AuthContext> {
  const header = req.headers.get("authorization") ?? "";
  const match = header.match(/^Bearer\s+(.+)$/i);
  if (!match) {
    throw new AuthError("Missing or malformed Authorization header");
  }
  const raw = match[1].trim();
  if (!raw) throw new AuthError("Empty bearer token");

  // Optional sanity check: our tokens are prefixed `sst_` so we can
  // fail fast on obviously-wrong values without hitting the DB.
  if (!raw.startsWith("sst_")) {
    throw new AuthError("Invalid token format");
  }

  // Two token formats live side-by-side:
  //   sst_oauth_...   — OAuth access token (issued by /oauth/token)
  //   sst_...         — legacy bearer token (issued by scripts/issue-token.ts)
  //
  // We check the more-specific prefix first so OAuth tokens don't get
  // mis-routed to the legacy path. Both flows return the same AuthContext.
  if (raw.startsWith("sst_oauth_")) {
    return authenticateOAuth(raw, env);
  }
  return authenticateLegacyBearer(raw, env);
}

async function authenticateLegacyBearer(
  raw: string,
  env: Env,
): Promise<AuthContext> {
  const tokenHash = await sha256Hex(raw);
  const supabase = adminClient(env);

  const { data: tokenRow, error } = await supabase
    .from("mcp_tokens")
    .select("preacher_id, name, revoked_at, preachers!inner(id, name)")
    .eq("token_hash", tokenHash)
    .maybeSingle();

  if (error) throw new AuthError(`Auth lookup failed: ${error.message}`, 500);
  if (!tokenRow) throw new AuthError("Token not recognized");
  if (tokenRow.revoked_at) throw new AuthError("Token revoked");

  supabase
    .from("mcp_tokens")
    .update({ last_used_at: new Date().toISOString() })
    .eq("token_hash", tokenHash)
    .then(() => {}, () => {});

  const preacher = (tokenRow as unknown as {
    preachers: { id: string; name: string };
  }).preachers;

  return {
    preacher_id: preacher.id,
    preacher_name: preacher.name,
    token_name: tokenRow.name ?? null,
  };
}

async function authenticateOAuth(
  raw: string,
  env: Env,
): Promise<AuthContext> {
  // Inline import to avoid a circular dep (oauth/store.ts also imports
  // adminClient from here).
  const { lookupAccessToken } = await import("./oauth/store");
  const row = await lookupAccessToken(env, raw);
  if (!row) throw new AuthError("Token not recognized or expired");
  const preacher = (row as unknown as {
    preachers: { id: string; name: string };
  }).preachers;
  return {
    preacher_id: preacher.id,
    preacher_name: preacher.name,
    token_name: null, // OAuth clients are labeled by client_name, not token name
  };
}

// Slug-based identity resolution for the public read path /p/:slug.
//
// Sermon material is public by design (it was preached to a congregation,
// posted on a church site, etc.). The slug isn't a *credential* — it's
// an addressing parameter that scopes which preacher's corpus this
// request is searching. Anyone can call /p/chris-oswald or /p/ricky-alcantar
// without authentication; attribution is enforced by the data model
// (every result cites preacher_name from the joined preachers row),
// not by a gate.
//
// This is separate from the bearer-token path and does NOT consume
// or affect mcp_tokens / oauth_access_tokens.
export async function authenticateBySlug(
  slug: string,
  env: Env,
): Promise<AuthContext> {
  if (!slug || !/^[a-z0-9-]+$/.test(slug)) {
    throw new AuthError("Invalid preacher slug format", 400);
  }
  const supabase = adminClient(env);
  const { data, error } = await supabase
    .from("preachers")
    .select("id, name")
    .eq("slug", slug)
    .maybeSingle();
  if (error) throw new AuthError(`Slug lookup failed: ${error.message}`, 500);
  if (!data) throw new AuthError(`Unknown preacher: ${slug}`, 404);
  return {
    preacher_id: data.id,
    preacher_name: data.name,
    token_name: null,
    scope: "preacher",
  };
}

// Guild Hall scope (/g): the canonical reference library — every preacher
// in the database whose church_id IS NULL. That's the Reformed reference
// set (Piper, Keller, Spurgeon, MacArthur, Lloyd-Jones, etc.) that the
// pipeline canonically compares working pastors against.
//
// Same public-read principle as /p/:slug and /c/:slug: this material is
// public artifacts, attribution is enforced by joined preacher data, not
// by access control. No auth header required.
//
// Optional `?speaker=<preacher-slug>` narrows the roster to a single
// guild member — lets a consumer query "Spurgeon only" through the
// guild endpoint instead of switching to /p/charles-spurgeon.
//
// There's no slug after /g — there's only one Guild Hall, so the path
// is unparameterized.
export async function authenticateGuildHall(
  speakerSlug: string | null,
  env: Env,
): Promise<AuthContext> {
  if (speakerSlug && !/^[a-z0-9-]+$/.test(speakerSlug)) {
    throw new AuthError("Invalid speaker slug format", 400);
  }
  const supabase = adminClient(env);

  // Pull the canonical reference set. church_id IS NULL is the marker:
  // when a preacher gets onboarded into a working-pastor cohort they
  // get a church_id; the reference library stays unattached.
  const { data: preachers, error } = await supabase
    .from("preachers")
    .select("id, name, slug")
    .is("church_id", null)
    .order("name");
  if (error) throw new AuthError(`Guild roster lookup failed: ${error.message}`, 500);
  if (!preachers || preachers.length === 0) {
    throw new AuthError("Guild Hall is empty", 404);
  }

  let scopedPreachers = preachers;
  let displayPreacherName = "Guild Hall";
  if (speakerSlug) {
    scopedPreachers = preachers.filter((p) => p.slug === speakerSlug);
    if (scopedPreachers.length === 0) {
      throw new AuthError(
        `No Guild Hall member with slug "${speakerSlug}"`,
        404,
      );
    }
    displayPreacherName = scopedPreachers[0].name;
  }

  const primary = scopedPreachers[0];

  return {
    preacher_id: primary.id,
    preacher_name: displayPreacherName,
    token_name: null,
    scope: "guild",
    preacher_ids: scopedPreachers.map((p) => p.id),
  };
}

// Church-wide variant of authenticateBySlug. Resolves a church_id from the
// URL path and loads the full roster of preacher_ids at that church. The
// resulting AuthContext is used by the tool handlers to scope queries via
// .in("preacher_id", preacher_ids) instead of .eq("preacher_id", X).
//
// Same public-read principle as /p/:slug: sermon material was preached
// publicly. No auth header required. Optional `?speaker=<preacher-slug>`
// query narrows preacher_ids to just one — lets a consumer use the church
// shape but currently focus on a single preacher (e.g. "Sermon Steward
// front-page lists every CoG preacher; click one and it filters").
export async function authenticateByChurchSlug(
  slug: string,
  speakerSlug: string | null,
  env: Env,
): Promise<AuthContext> {
  if (!slug || !/^[a-z0-9-]+$/.test(slug)) {
    throw new AuthError("Invalid church slug format", 400);
  }
  if (speakerSlug && !/^[a-z0-9-]+$/.test(speakerSlug)) {
    throw new AuthError("Invalid speaker slug format", 400);
  }
  const supabase = adminClient(env);

  const { data: church, error: cherr } = await supabase
    .from("churches")
    .select("id, name")
    .eq("slug", slug)
    .maybeSingle();
  if (cherr) throw new AuthError(`Church lookup failed: ${cherr.message}`, 500);
  if (!church) throw new AuthError(`Unknown church: ${slug}`, 404);

  // Pull all preachers attached to this church. preachers.church_id is
  // the source of truth (set during onboarding + when an adapter inserts
  // a new sermon attributed to a guest with no existing profile).
  const { data: preachers, error: perr } = await supabase
    .from("preachers")
    .select("id, name, slug")
    .eq("church_id", church.id);
  if (perr) throw new AuthError(`Preacher roster lookup failed: ${perr.message}`, 500);
  if (!preachers || preachers.length === 0) {
    throw new AuthError(`No preachers found at ${church.name}`, 404);
  }

  let scopedPreachers = preachers;
  let displayPreacherName = church.name;
  if (speakerSlug) {
    scopedPreachers = preachers.filter((p) => p.slug === speakerSlug);
    if (scopedPreachers.length === 0) {
      throw new AuthError(
        `No preacher with slug "${speakerSlug}" at ${church.name}`,
        404,
      );
    }
    displayPreacherName = scopedPreachers[0].name;
  }

  // For backward-compat with tool code paths that still expect a single
  // preacher_id / preacher_name, point at the first preacher (when
  // speaker_filter is active that's the filtered one; otherwise it's the
  // alphabetically-first preacher — which the church-aware tool handlers
  // ignore anyway in favor of preacher_ids).
  const primary = scopedPreachers[0];

  return {
    preacher_id: primary.id,
    preacher_name: displayPreacherName,
    token_name: null,
    scope: "church",
    church_id: church.id,
    church_name: church.name,
    preacher_ids: scopedPreachers.map((p) => p.id),
  };
}
