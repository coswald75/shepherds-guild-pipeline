import type { AuthContext } from "../types";
import { chrisOswaldPrompt } from "./chris-oswald";
import { rickyAlcantarPrompt } from "./ricky-alcantar";

// MCP "prompts" registry. Clients (Claude Desktop, Claude.ai, ChatGPT)
// expose these in a prompt picker. When the user selects one, the
// client calls prompts/get and we return a rendered messages array
// that gets injected at the top of the conversation.
//
// Pastors only see prompts associated with them. We do a name-based
// match on auth.preacher_name to filter — so when Chris connects he
// sees "Chris's Voice" and when Ricky connects he sees "Ricky's Voice."
//
// This is intentionally a registry of HARDCODED prompts rather than
// pulling from the DB. The prompts are version-controlled deliverables
// you tune over time; they shouldn't be user-editable surface area.

interface PromptDef {
  name: string;
  description: string;
  preacherName: string;
  arguments?: Array<{
    name: string;
    description: string;
    required?: boolean;
  }>;
  render: (args: Record<string, string>, auth: AuthContext) => string;
}

const ALL_PROMPTS: PromptDef[] = [
  {
    name: "chris-oswald-voice",
    description:
      "Voice, theology, and editorial constraints for Chris Oswald (Sovereign Grace, KCMO). Loads the trust contract, voice notes, and corpus-tool usage guidance.",
    preacherName: "Chris Oswald",
    arguments: [
      {
        name: "focus",
        description:
          "Optional: what you're working on today (e.g. 'Ephesians 4 sermon prep'). Lean retrieval and synthesis toward this.",
        required: false,
      },
    ],
    render: (args, auth) => chrisOswaldPrompt({ focus: args.focus }, auth),
  },
  {
    name: "ricky-alcantar-voice",
    description:
      "Voice, theology, and editorial constraints for Ricky Alcantar (Cross of Grace, El Paso). Placeholder voice notes until customized.",
    preacherName: "Ricky Alcantar",
    arguments: [
      {
        name: "focus",
        description: "Optional: what you're working on today.",
        required: false,
      },
    ],
    render: (args, auth) => rickyAlcantarPrompt({ focus: args.focus }, auth),
  },
];

// Filter at request time by authenticated pastor. Each pastor only
// sees their own prompt(s) — Chris never sees Ricky's in his picker
// and vice versa.
export function listPromptsForAuth(auth: AuthContext) {
  return ALL_PROMPTS.filter((p) => p.preacherName === auth.preacher_name).map(
    (p) => ({
      name: p.name,
      description: p.description,
      arguments: p.arguments ?? [],
    }),
  );
}

export function renderPrompt(
  name: string,
  args: Record<string, string>,
  auth: AuthContext,
): { description: string; messages: Array<{ role: "user"; content: { type: "text"; text: string } }> } | null {
  const def = ALL_PROMPTS.find((p) => p.name === name);
  if (!def) return null;

  // Tenancy gate: a preacher can only see their own voice prompt. Even
  // if Ricky somehow knew Chris's prompt name, his auth wouldn't render it.
  if (def.preacherName !== auth.preacher_name) return null;

  return {
    description: def.description,
    messages: [
      {
        role: "user",
        content: { type: "text", text: def.render(args, auth) },
      },
    ],
  };
}
