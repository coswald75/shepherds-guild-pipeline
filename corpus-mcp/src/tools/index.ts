import type { AuthContext, Env } from "../types";
import { askCorpusTool, runAskCorpus } from "./ask-corpus";

// Tool registry. The MCP server exposes ONE tool — ask_corpus — which
// routes server-side to the right underlying handler based on the
// pastor's question. The specific handlers (search-corpus, get-sermon,
// list-recent-sermons, surprise-me) are still in this directory; they're
// just imported by ask-corpus.ts rather than exposed directly.

export const TOOLS = [askCorpusTool] as const;

export async function callTool(
  name: string,
  args: Record<string, unknown>,
  auth: AuthContext,
  env: Env,
) {
  switch (name) {
    case "ask_corpus":
      return runAskCorpus(args, auth, env);
    default:
      throw new Error(`Unknown tool: ${name}`);
  }
}
