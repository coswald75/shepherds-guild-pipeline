// Shared types for the MCP server. The SermonUnitHit shape mirrors the
// match_units_for_preacher SQL function's RETURNS TABLE; the others are
// derived from the sermons / preachers / units schema.

export interface Env {
  // Vars (wrangler.toml)
  SUPABASE_URL: string;
  DEFAULT_SEARCH_LIMIT: string;
  VOYAGE_MODEL: string;
  VOYAGE_DIMENSIONS: string;

  // Secrets (wrangler secret put / .dev.vars)
  SUPABASE_SERVICE_ROLE_KEY: string;
  VOYAGE_API_KEY: string;
  // Added for OAuth: anon key is used to send magic-link emails via
  // Supabase Auth (subject to the project's email rate limits, not the
  // service role's). Optional — without it, the OAuth flow is disabled
  // and legacy sst_* bearer tokens are the only auth path.
  SUPABASE_ANON_KEY?: string;
}

// Three scoping modes share this shape:
//   - Per-preacher (bearer token, /p/:slug):
//       preacher_id is set, preacher_name is set, scope = "preacher".
//   - Whole-church (/c/:slug):
//       church_id is set, scope = "church", preacher_ids is the full roster
//       of preachers at that church_id. preacher_id is the church's
//       "display" preacher (the primary, used for legacy code paths that
//       still expect one), but per-preacher filtering should use
//       preacher_ids when scope === "church".
//   - Guild Hall (/g):
//       scope = "guild". preacher_ids is the full canonical reference
//       library (every preacher in the DB whose church_id IS NULL —
//       Piper, Keller, Spurgeon, MacArthur, etc.). One global endpoint;
//       no slug after /g. preacher_id is the "display" preacher (first
//       in the roster) — same role as the church mode's display.
//   - Optional speaker_filter (set via /c/:slug?speaker=<slug> or
//       /g?speaker=<slug>) narrows preacher_ids to just one — useful when
//       a consumer wants the multi-preacher endpoint shape but is
//       currently focused on a single preacher.
//
// Tool handlers treat "church" and "guild" identically — both use
// preacher_ids[] as the filter list. The scope field exists so the
// landing-page text and a couple of attribution labels can read "Guild
// Hall" vs "the church" in the right places.
export interface AuthContext {
  preacher_id: string;
  preacher_name: string;
  token_name: string | null;
  scope?: "preacher" | "church" | "guild";
  church_id?: string;
  church_name?: string;
  preacher_ids?: string[];
}

export interface SermonUnitHit {
  unit_id: string;
  sermon_id: string;
  sermon_title: string;
  sermon_date: string;
  primary_text: string | null;
  unit_index: number;
  rhetorical_function: string;
  illustration_type: string | null;
  doctrinal_loci: string[] | null;
  content: string;
  summary: string | null;
  similarity?: number;
  final_score?: number;
  // Set on hits from match_units_for_church (so the formatter can include
  // "— preached by Ricky Alcantar" attribution). Unset on per-preacher hits.
  preacher_id?: string;
  preacher_name?: string;
}

export interface SermonRecord {
  id: string;
  title: string;
  date: string;
  primary_text: string | null;
  sermon_type: string | null;
  series_name: string | null;
  abstract: string | null;
  main_thesis: string | null;
  preacher_name: string;
}

export interface SermonWithUnits extends SermonRecord {
  units: Array<{
    unit_id: string;
    unit_index: number;
    rhetorical_function: string;
    illustration_type: string | null;
    doctrinal_loci: string[] | null;
    summary: string | null;
    content: string;
  }>;
}

// JSON-RPC 2.0 envelopes — we hand-roll the wire format because the
// official MCP SDK is Node-targeted and Workers' V8 isolate environment
// gives us a smaller, more predictable bundle when we own the protocol.
export interface JsonRpcRequest {
  jsonrpc: "2.0";
  id?: string | number | null;
  method: string;
  params?: Record<string, unknown>;
}

export interface JsonRpcResponse {
  jsonrpc: "2.0";
  id: string | number | null;
  result?: unknown;
  error?: { code: number; message: string; data?: unknown };
}
