import type { AuthContext, Env } from "../types";
import { askCorpusTool, runAskCorpus } from "./ask-corpus";
import { searchReferencesTool, runSearchReferences } from "./search-references";

// Tool registry.
//
// Regular scope (per-preacher, church, guild):
//   - ask_corpus  → server-side router dispatches to search/get_sermon/
//                   list_recent_sermons/surprise_me/get_ingestion_coverage.
//
// Admin/master scope (Chris's bearer/OAuth token → is_admin=true):
//   - ask_corpus         → same as above but also searches across all
//                          preachers when the router asks it to.
//   - search_references  → commonplace corpus (Hoyt, Nave, Collacon,
//                          Nuttall, Bartlett, Pink) — 99k entries.
//
// The tool list returned to any given caller is filtered by is_admin
// via listToolsForAuth() below.

const BASE_TOOLS = [askCorpusTool] as const;
const ADMIN_TOOLS = [searchReferencesTool] as const;

export function listToolsForAuth(auth: AuthContext) {
  const tools: unknown[] = [...BASE_TOOLS];
  if (auth.is_admin) tools.push(...ADMIN_TOOLS);
  return tools as ReadonlyArray<
    typeof askCorpusTool | typeof searchReferencesTool
  >;
}

// Legacy export — kept for backward compat with callers that iterated
// TOOLS directly. Prefer listToolsForAuth(auth) going forward.
export const TOOLS = BASE_TOOLS;

export async function callTool(
  name: string,
  args: Record<string, unknown>,
  auth: AuthContext,
  env: Env,
) {
  switch (name) {
    case "ask_corpus":
      return runAskCorpus(args, auth, env);
    case "search_references":
      // Admin gate: runSearchReferences throws if !auth.is_admin, but we
      // also fail fast here for a cleaner MCP error.
      if (!auth.is_admin) {
        throw new Error(
          "search_references is only available to admin/master scope",
        );
      }
      return runSearchReferences(args, auth, env);
    default:
      throw new Error(`Unknown tool: ${name}`);
  }
}
