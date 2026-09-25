import { adminClient } from "../auth";
import { embedQuery } from "../voyage";
import type { AuthContext, Env } from "../types";

// search_references — vector search over the 99k-row commonplace corpus
// (Hoyt's, Nave's, Collacon, Nuttall, Bartlett's, A.W. Pink).
//
// Admin/master scope only. Regular pastor scope doesn't see this tool
// (filtered out in tools/index.ts by is_admin flag).
//
// Backed by the search_reference_units RPC + the existing ivfflat index
// (350 lists on 99k rows — well-sized).

export const searchReferencesTool = {
  name: "search_references",
  description:
    "Vector search over the commonplace / reference corpus — public-domain " +
    "quotation and homiletic reference works: Hoyt's Cyclopædia of " +
    "Practical Quotations, Nave's Topical Bible, Collacon, Nuttall " +
    "Encyclopædia, Bartlett's Familiar Quotations, and A.W. Pink. Use " +
    "for sermon prep and content research when the pastor wants to find " +
    "commonplace material on a topic. Optional filters narrow by work " +
    "or by attributed author (e.g., only Pink, only Shakespeare).",
  inputSchema: {
    type: "object",
    properties: {
      query: {
        type: "string",
        description:
          "The topic, theme, phrase, or question to search for. Natural " +
          "language works best. Examples: 'quotations on the fear of the " +
          "Lord', 'anything Pink says about assurance', 'commonplace on " +
          "the transience of life'.",
      },
      works: {
        type: "array",
        items: {
          type: "string",
          enum: ["Hoyt", "Nave", "Collacon", "Nuttall", "Bartlett", "Pink"],
        },
        description:
          "Optional: narrow to specific reference works. Pass one or more " +
          "of the enum values. Omit to search across all six works.",
      },
      attributions: {
        type: "array",
        items: { type: "string" },
        description:
          "Optional: narrow to specific attributed authors. Common values: " +
          "'A. W. Pink', 'William Shakespeare', 'John Milton', 'Alexander " +
          "Pope', 'Cicero', 'Seneca', 'Bible (KJV)'. Filter is exact-match.",
      },
      subjects: {
        type: "array",
        items: { type: "string" },
        description:
          "Optional: narrow to specific subject headings (varies by work). " +
          "Only useful if you know the exact subject label.",
      },
      limit: {
        type: "integer",
        minimum: 1,
        maximum: 20,
        description: "How many entries to return. Defaults to 8.",
      },
    },
    required: ["query"],
  } as const,
};

interface SearchArgs {
  query?: unknown;
  works?: unknown;
  attributions?: unknown;
  subjects?: unknown;
  limit?: unknown;
}

export async function runSearchReferences(
  args: SearchArgs,
  auth: AuthContext,
  env: Env,
) {
  if (!auth.is_admin) {
    throw new Error(
      "search_references is admin-only. Your token doesn't have master scope.",
    );
  }

  const query = typeof args.query === "string" ? args.query.trim() : "";
  if (!query) {
    throw new Error("search_references requires a non-empty `query` string");
  }
  const limit = clampInt(args.limit, 1, 20, 8);
  const works = stringArrayOrNull(args.works);
  const attributions = stringArrayOrNull(args.attributions);
  const subjects = stringArrayOrNull(args.subjects);

  const t0 = Date.now();
  console.log(
    `[search_references] q="${query.slice(0, 60)}" works=${JSON.stringify(works)} attrs=${JSON.stringify(attributions)}`,
  );

  const embedding = await embedQuery(query, env);
  const tEmbed = Date.now();

  const supabase = adminClient(env);
  const { data: rawHits, error } = await supabase.rpc(
    "search_reference_units",
    {
      p_query_embedding: embedding,
      p_match_count: limit,
      p_works: works,
      p_attributions: attributions,
      p_subjects: subjects,
    },
  );
  const tRpc = Date.now();

  if (error) {
    throw new Error(
      `Reference search failed after ${tRpc - tEmbed}ms: ${error.message}`,
    );
  }

  type Row = {
    ref_id: string;
    work: string;
    subject: string;
    content: string;
    attribution: string | null;
    source_ref: string | null;
    similarity: number;
  };
  const hits = (rawHits ?? []) as Row[];

  console.log(
    `[search_references] embed=${tEmbed - t0}ms rpc=${tRpc - tEmbed}ms hits=${hits.length}`,
  );

  const lines: string[] = [];
  lines.push(
    `Retrieved ${hits.length} entries from the commonplace corpus for "${query}".`,
    "",
  );
  for (const h of hits) {
    const attr = h.attribution ? ` — ${h.attribution}` : "";
    const ref = h.source_ref ? ` (${h.source_ref})` : "";
    lines.push(
      `### ${h.work} · ${h.subject}  · score ${h.similarity.toFixed(2)}`,
    );
    lines.push(`> ${h.content}${attr}${ref}`, "");
  }

  return {
    content: [{ type: "text", text: lines.join("\n") }],
    structuredContent: {
      query,
      source: "reference_units",
      hits: hits.map((h) => ({
        source_type: "reference",
        work: h.work,
        subject: h.subject,
        content: h.content,
        attribution: h.attribution,
        source_ref: h.source_ref,
        score: h.similarity,
        ref_id: h.ref_id,
      })),
    },
  };
}

function clampInt(v: unknown, min: number, max: number, fallback: number) {
  if (typeof v !== "number" || !Number.isFinite(v)) return fallback;
  return Math.min(max, Math.max(min, Math.floor(v)));
}

function stringArrayOrNull(v: unknown): string[] | null {
  if (!Array.isArray(v)) return null;
  const arr = v.filter((x): x is string => typeof x === "string" && x.length > 0);
  return arr.length > 0 ? arr : null;
}
