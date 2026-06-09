import { adminClient } from "../auth";
import type { AuthContext, Env } from "../types";
import { formatHitsAsText } from "./format";

// surprise_me — three random substantive units from the pastor's corpus.
// Designed as a stumble-upon feature: pastors forget their own material
// over time; this resurfaces older work they may want to reuse or build
// on. Avoids stubs by filtering on content length and weights toward
// older sermons (the ones genuinely "forgotten") via a date cap.

const MIN_CONTENT_LENGTH = 200;
const DEFAULT_COUNT = 3;
const MAX_COUNT = 8;

export const surpriseMeTool = {
  name: "surprise_me",
  description:
    "Surface random forgotten material from the pastor's corpus. Returns " +
    "three (configurable) substantive units chosen at random from sermons " +
    "the pastor has preached. Use when the pastor asks to be reminded of " +
    "old material, wants inspiration for an upcoming sermon, or simply " +
    "asks to 'surprise me'. Skips short/stub units so the results are " +
    "always genuinely substantive.",
  inputSchema: {
    type: "object",
    properties: {
      count: {
        type: "integer",
        minimum: 1,
        maximum: MAX_COUNT,
        description: `How many units to surface. Default ${DEFAULT_COUNT}.`,
      },
      older_than_days: {
        type: "integer",
        minimum: 0,
        description:
          "Optional: only pull units from sermons older than N days. " +
          "Useful for 'remind me of stuff I've actually forgotten' (try " +
          "365 or 730). Omit to include any sermon.",
      },
      rhetorical_function: {
        type: "string",
        description:
          "Optional: bias toward one type (e.g. 'illustration' for stumble-" +
          "upon illustrations, 'theological_claim' for thesis fragments).",
      },
    },
  } as const,
};

interface SurpriseArgs {
  count?: unknown;
  older_than_days?: unknown;
  rhetorical_function?: unknown;
}

export async function runSurpriseMe(
  args: SurpriseArgs,
  auth: AuthContext,
  env: Env,
) {
  const count = clampInt(args.count, 1, MAX_COUNT, DEFAULT_COUNT);
  const olderThanDays =
    typeof args.older_than_days === "number" &&
    Number.isFinite(args.older_than_days)
      ? Math.max(0, Math.floor(args.older_than_days))
      : null;
  const rhetoricalFunction =
    typeof args.rhetorical_function === "string" && args.rhetorical_function
      ? args.rhetorical_function
      : null;

  const supabase = adminClient(env);

  // Compute an upper-bound date if older_than_days was provided.
  // We do this in JS rather than Postgres so the WHERE clause stays
  // index-friendly (just a date <= comparison).
  let dateCap: string | null = null;
  if (olderThanDays !== null && olderThanDays > 0) {
    const cap = new Date();
    cap.setUTCDate(cap.getUTCDate() - olderThanDays);
    dateCap = cap.toISOString().slice(0, 10);
  }

  // Postgres' `random()` over a join is fine at corpus scale (tens of
  // thousands of rows). If this grows past hundreds of thousands of
  // units, swap to `tablesample bernoulli` for a sampled fast path.
  // We over-fetch 5x and post-filter so a small batch with bad luck
  // still returns the requested count.
  const overfetch = count * 5;

  type Row = {
    id: string;
    unit_index: number;
    rhetorical_function: string;
    illustration_type: string | null;
    doctrinal_loci: string[] | null;
    summary: string | null;
    content: string;
    sermons: {
      id: string;
      title: string;
      date: string;
      primary_text: string | null;
      preacher_id: string;
      preachers?: { name: string };
    };
  };

  const isChurchScope = auth.scope === "church" && auth.preacher_ids?.length;
  const selectStr = isChurchScope
    ? "id, unit_index, rhetorical_function, illustration_type, doctrinal_loci, summary, content, sermons!inner(id, title, date, primary_text, preacher_id, preachers!inner(name))"
    : "id, unit_index, rhetorical_function, illustration_type, doctrinal_loci, summary, content, sermons!inner(id, title, date, primary_text, preacher_id)";

  let q = supabase.from("units").select(selectStr);
  if (isChurchScope) {
    q = q.in("sermons.preacher_id", auth.preacher_ids!);
  } else {
    q = q.eq("sermons.preacher_id", auth.preacher_id);
  }

  if (rhetoricalFunction) {
    q = q.eq("rhetorical_function", rhetoricalFunction);
  }
  if (dateCap) {
    q = q.lte("sermons.date", dateCap);
  }

  // Supabase JS doesn't expose `ORDER BY random()` directly, so we pull
  // a larger sample and shuffle client-side. At ~5x overfetch on tens
  // of thousands of rows this is fine.
  q = q.limit(overfetch * 10);

  const { data: pool, error } = await q;
  if (error) throw new Error(`surprise_me fetch failed: ${error.message}`);

  const substantive = ((pool ?? []) as unknown as Row[]).filter(
    (r) => (r.content ?? "").trim().length >= MIN_CONTENT_LENGTH,
  );

  // Fisher-Yates shuffle of the substantive pool, take first N.
  for (let i = substantive.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [substantive[i], substantive[j]] = [substantive[j], substantive[i]];
  }
  const picks = substantive.slice(0, count);

  const hits = picks.map((p) => ({
    unit_id: p.id,
    sermon_id: p.sermons.id,
    sermon_title: p.sermons.title,
    sermon_date: p.sermons.date,
    primary_text: p.sermons.primary_text,
    unit_index: p.unit_index,
    rhetorical_function: p.rhetorical_function,
    illustration_type: p.illustration_type,
    doctrinal_loci: p.doctrinal_loci,
    content: p.content,
    summary: p.summary,
    // Church scope: preserve per-row preacher attribution so the formatter
    // can render "— preached by X".
    preacher_id: isChurchScope ? p.sermons.preacher_id : undefined,
    preacher_name: isChurchScope ? p.sermons.preachers?.name : undefined,
  }));

  const headerLine = picks.length
    ? `Three things from ${auth.preacher_name}'s corpus, picked at random${
        dateCap ? ` (from before ${dateCap})` : ""
      }:`
    : `No substantive units found for ${auth.preacher_name}${
        dateCap ? ` from before ${dateCap}` : ""
      }.`;

  const body = formatHitsAsText(hits, {
    preacherName: auth.preacher_name,
    query: "(surprise)",
    strongCount: hits.length,
    totalCount: hits.length,
    threshold: 0,
    header: headerLine,
  });

  return {
    content: [{ type: "text", text: body }],
    structuredContent: {
      preacher_name: auth.preacher_name,
      mode: "surprise",
      count: picks.length,
      hits,
    },
  };
}

function clampInt(v: unknown, min: number, max: number, fallback: number) {
  if (typeof v !== "number" || !Number.isFinite(v)) return fallback;
  return Math.min(max, Math.max(min, Math.floor(v)));
}
