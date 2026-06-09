import { adminClient } from "../auth";
import { embedQuery } from "../voyage";
import type { AuthContext, Env, SermonUnitHit } from "../types";
import { formatHitsAsText } from "./format";

// Quality floor: units shorter than this are decomposition artifacts
// ("In Job 4:7,", "John another incarnation passage") and should never
// be surfaced to the LLM as if they were real material.
const MIN_CONTENT_LENGTH = 200;

// Score calibration — empirically tuned 2026-06-03 across three rounds.
//
// Round 1: noise from unrelated queries scored 0.55-0.66 (nonexistent
// content flagged as "strong" at 0.62). Raised threshold 0.55 → 0.65.
//
// Round 2: with threshold 0.65, "SpaceX" still cleared at 0.662.
// Raised threshold to 0.70.
//
// Round 3: 0.70 over-corrected — de-flagged genuine matches in the
// 0.65-0.69 zone (e.g., Imperishable Beauty's own unit at 0.655, real
// cornerstone matches at 0.66-0.69). Settled on 0.675 as the cleanest
// separator between noise (which tops out around 0.66) and real hits
// (which start around 0.67).
//
//   STRONG_MATCH_THRESHOLD (0.675): mid-point of the gray zone.
//   ABSOLUTE_FLOOR (0.55): below this, no_real_match=true fires.
const STRONG_MATCH_THRESHOLD = 0.675;
const ABSOLUTE_FLOOR = 0.55;

export const searchCorpusTool = {
  name: "search_corpus",
  description:
    "Search the pastor's own preaching corpus for units (illustrations, " +
    "exposition, applications, theological claims, etc.) relevant to a " +
    "question or topic. Uses hybrid vector + keyword retrieval. Returns " +
    "the top matches with sermon title, date, key claim, and the full " +
    "unit text so the LLM can quote or summarize accurately. Cite by " +
    "sermon title and date when referencing.",
  inputSchema: {
    type: "object",
    properties: {
      query: {
        type: "string",
        description:
          "The question or topic to search for. Natural language works " +
          "best — e.g. 'when have I talked about Christ-centered " +
          "ministry' or 'illustrations about parenting failure'.",
      },
      rhetorical_functions: {
        type: "array",
        items: {
          type: "string",
          enum: [
            "exposition",
            "theological_claim",
            "application",
            "illustration",
            "introduction",
            "conclusion",
            "transition",
            "pastoral_aside",
            "prayer",
          ],
        },
        description:
          "Optional: narrow to specific unit types. Use 'illustration' " +
          "for recall queries ('have I ever used the X story'). Use " +
          "'application' for prep queries ('what have I said about how " +
          "to live this'). Omit to search all unit types.",
      },
      doctrinal_loci: {
        type: "array",
        items: { type: "string" },
        description:
          "Optional: narrow to specific doctrinal categories. Common " +
          "values: Christology, Soteriology, Ecclesiology, Eschatology, " +
          "Anthropology, Sanctification, Pastoral Theology. Filters by " +
          "array overlap.",
      },
      primary_text: {
        type: "string",
        description:
          "Optional: narrow to sermons whose primary text matches (e.g. " +
          "'Ephesians 4'). Substring match on sermons.primary_text.",
      },
      limit: {
        type: "integer",
        minimum: 1,
        maximum: 12,
        description: "How many units to return. Defaults to 5.",
      },
    },
    required: ["query"],
  } as const,
};

interface SearchArgs {
  query?: unknown;
  rhetorical_functions?: unknown;
  doctrinal_loci?: unknown;
  primary_text?: unknown;
  limit?: unknown;
}

export async function runSearchCorpus(
  args: SearchArgs,
  auth: AuthContext,
  env: Env,
) {
  const query = typeof args.query === "string" ? args.query.trim() : "";
  if (!query) {
    throw new Error("search_corpus requires a non-empty `query` string");
  }
  const limit = clampInt(
    args.limit,
    1,
    12,
    Number(env.DEFAULT_SEARCH_LIMIT) || 5,
  );
  const rhetoricalFunctions = stringArrayOrNull(args.rhetorical_functions);
  const doctrinalLoci = stringArrayOrNull(args.doctrinal_loci);
  const primaryText =
    typeof args.primary_text === "string" && args.primary_text.trim()
      ? args.primary_text.trim()
      : null;

  // Pull a wider candidate set than the requested limit so we can drop
  // degenerate units and dedupe by sermon without coming up short.
  const candidateCount = Math.max(limit * 3, 12);

  // Stage-by-stage timing — surfaces in Cloudflare logs so when something
  // hangs we can see which stage. The previous -32001 timeouts were
  // opaque because nothing in the search path logged.
  const t0 = Date.now();
  const isChurchScope = (auth.scope === "church" || auth.scope === "guild") && auth.preacher_ids?.length;
  console.log(
    `[search] start query="${query.slice(0, 60)}" ` +
      (isChurchScope
        ? `scope=${auth.scope} ${auth.church_id ? `church=${auth.church_id} ` : ""}preachers=${auth.preacher_ids!.length}`
        : `preacher=${auth.preacher_id}`),
  );

  const embedding = await embedQuery(query, env);
  const tEmbed = Date.now();

  const supabase = adminClient(env);

  // Two RPCs share the same scoring contract; only the WHERE clause
  // (preacher_id =  vs preacher_id = ANY()) differs. The church variant
  // additionally returns preacher_id + preacher_name per hit so we can
  // attribute results correctly across the whole roster.
  const rpcCall = isChurchScope
    ? supabase.rpc("match_units_for_church", {
        p_preacher_ids: auth.preacher_ids!,
        p_query_embedding: embedding,
        p_query_text: query,
        p_match_count: candidateCount,
        p_rhetorical_functions: rhetoricalFunctions,
        p_primary_text: primaryText,
        p_keyword_weight: 0.3,
        p_doctrinal_loci: doctrinalLoci,
      })
    : supabase.rpc("match_units_for_preacher", {
        p_preacher_id: auth.preacher_id,
        p_query_embedding: embedding,
        p_query_text: query,
        p_match_count: candidateCount,
        p_rhetorical_functions: rhetoricalFunctions,
        p_primary_text: primaryText,
        p_keyword_weight: 0.3,
        p_doctrinal_loci: doctrinalLoci,
      });
  const { data: rawHits, error } = await rpcCall;
  const tRpc = Date.now();

  if (error) {
    console.error(
      `[search] RPC error after ${tRpc - tEmbed}ms: ${error.message}`,
    );
    throw new Error(
      `Retrieval failed after ${tRpc - tEmbed}ms in vector match: ${error.message}`,
    );
  }

  const hits = (rawHits ?? []) as SermonUnitHit[];
  console.log(
    `[search] timing: embed=${tEmbed - t0}ms rpc=${tRpc - tEmbed}ms raw_hits=${hits.length}`,
  );

  // Stage 1: drop stub/degenerate units. These exist in the corpus as
  // decomposition artifacts and would otherwise pad results with garbage.
  const substantive = hits.filter(
    (h) => (h.content ?? "").trim().length >= MIN_CONTENT_LENGTH,
  );

  // Stage 2: dedupe by sermon — keep the highest-scoring unit per sermon.
  // Pastor reading the result shouldn't see "this sermon §12 / this same
  // sermon §20" as two of their four citations.
  const bestPerSermon = new Map<string, SermonUnitHit>();
  for (const h of substantive) {
    const existing = bestPerSermon.get(h.sermon_id);
    if (!existing || (h.final_score ?? 0) > (existing.final_score ?? 0)) {
      bestPerSermon.set(h.sermon_id, h);
    }
  }

  const deduped = [...bestPerSermon.values()]
    .sort((a, b) => (b.final_score ?? 0) - (a.final_score ?? 0))
    .slice(0, limit);

  const strong = deduped.filter(
    (h) => (h.final_score ?? 0) >= STRONG_MATCH_THRESHOLD,
  );
  const topScore = deduped[0]?.final_score ?? 0;
  // Hard "no real match" signal: the top hit is below even the absolute
  // floor. We still return the hits (the LLM can use them as nearest-
  // neighbor context), but the formatter explicitly tells the LLM to
  // tell the user nothing real matched. Prevents the dialed-up false
  // confidence at 0.55-0.66 scores observed in the 2026-06-03 test report.
  const noRealMatch = topScore < ABSOLUTE_FLOOR;

  return {
    content: [
      {
        type: "text",
        text: formatHitsAsText(deduped, {
          preacherName: auth.preacher_name,
          query,
          strongCount: strong.length,
          totalCount: deduped.length,
          threshold: STRONG_MATCH_THRESHOLD,
          noRealMatch,
          topScore,
        }),
      },
    ],
    // Structured data — clients that surface tool results visually can
    // render this as cards (claude.ai shows them inline; ChatGPT renders
    // them as accordions). Mirrors the corpus-query UI contract.
    structuredContent: {
      query,
      preacher_name: auth.preacher_name,
      strong_match_threshold: STRONG_MATCH_THRESHOLD,
      absolute_floor: ABSOLUTE_FLOOR,
      no_real_match: noRealMatch,
      top_score: topScore,
      hits: deduped.map((h) => ({
        sermon_title: h.sermon_title,
        sermon_date: h.sermon_date,
        primary_text: h.primary_text,
        unit_index: h.unit_index,
        rhetorical_function: h.rhetorical_function,
        illustration_type: h.illustration_type,
        doctrinal_loci: h.doctrinal_loci,
        key_claim: h.summary,
        content: h.content,
        score: h.final_score,
        is_strong_match: (h.final_score ?? 0) >= STRONG_MATCH_THRESHOLD,
        sermon_id: h.sermon_id,
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
