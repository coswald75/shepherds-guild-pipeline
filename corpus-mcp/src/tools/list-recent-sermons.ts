import { adminClient } from "../auth";
import type { AuthContext, Env } from "../types";

// list_recent_sermons — descending-date browse of the pastor's corpus.
// Useful for "what have I been preaching on lately" or "show me my
// sermons from this year" style queries. Returns just metadata, not unit
// content — the LLM can call get_sermon on anything that looks relevant.

export const listRecentSermonsTool = {
  name: "list_recent_sermons",
  description:
    "List the pastor's most recent sermons in reverse chronological order. " +
    "Returns title, date, primary text, and series — but not unit content. " +
    "Use for 'what have I been preaching on lately' queries, or as a " +
    "browsing aid before calling get_sermon on a specific one.",
  inputSchema: {
    type: "object",
    properties: {
      limit: {
        type: "integer",
        minimum: 1,
        maximum: 50,
        description: "How many sermons to return. Defaults to 10.",
      },
      since: {
        type: "string",
        description:
          "Optional ISO date (YYYY-MM-DD). Only include sermons on or " +
          "after this date.",
      },
      series_name: {
        type: "string",
        description:
          "Optional: filter to one series (substring match on series_name).",
      },
    },
  } as const,
};

interface ListArgs {
  limit?: unknown;
  since?: unknown;
  until?: unknown;
  series_name?: unknown;
  // When true, the response includes ONLY sermons missing ingestion
  // metadata — i.e., sermons registered in the corpus but probably
  // unsearchable. Lets pastors see what's not yet content-indexed.
  unindexed_only?: unknown;
}

export async function runListRecentSermons(
  args: ListArgs,
  auth: AuthContext,
  env: Env,
) {
  const limit = clampInt(args.limit, 1, 50, 10);
  const since = typeof args.since === "string" ? args.since : null;
  // `until` is exclusive (matches the half-open [since, until) convention
  // used by parseDateRange in ask-corpus.ts).
  const until = typeof args.until === "string" ? args.until : null;
  const seriesName =
    typeof args.series_name === "string" && args.series_name.trim()
      ? args.series_name.trim()
      : null;
  const unindexedOnly = args.unindexed_only === true;

  // Exclude null-date sermons from the listing. Postgres' default for
  // ORDER BY date DESC is NULLS FIRST, which means null-date sermons
  // (192 of Chris's 446) crowded out his real recent preaching and made
  // the listing look broken. Recent-sermons listings should mean
  // "actually dated, sorted newest first" — undated rows are surfaced
  // through search and surprise_me, not browsed by date.
  // Church-scope: filter by IN(preacher_ids) and pull preacher_name +
  // preacher_id so the listing can attribute each sermon. Preacher-scope:
  // single .eq filter, no per-row preacher fields (caller already knows).
  // The select string is conditional, so supabase-js can't infer the row
  // type — we cast the response through `unknown` to SermonListRow below.
  type SermonListRow = {
    id: string;
    title: string;
    date: string;
    primary_text: string | null;
    series_name: string | null;
    sermon_type: string | null;
    preacher_id?: string;
    preachers?: { name: string };
  };
  const isChurchScope = (auth.scope === "church" || auth.scope === "guild") && auth.preacher_ids?.length;
  const selectCols = isChurchScope
    ? "id, title, date, primary_text, series_name, sermon_type, preacher_id, preachers!inner(name)"
    : "id, title, date, primary_text, series_name, sermon_type";

  // Date filter behavior depends on scope:
  //   - preacher / church: exclude null-date rows. Working pastors' sermons
  //     should all be dated; a null date is a data-quality issue. Listing
  //     them buries the real recent preaching.
  //   - guild: include null-date rows but sort dated-first via NULLS LAST.
  //     Guild Hall members include historical figures (Spurgeon, Watson,
  //     Campbell Morgan) whose 30/30 sermons have NULL date. Excluding
  //     them would make /g?speaker=charles-spurgeon return zero hits.
  const isGuildScope = auth.scope === "guild";
  let q = adminClient(env)
    .from("sermons")
    .select(selectCols as never)
    .order("date", { ascending: false, nullsFirst: false })
    .limit(limit);
  if (!isGuildScope) {
    q = q.not("date", "is", null);
  }

  if (isChurchScope) {
    q = q.in("preacher_id", auth.preacher_ids!);
  } else {
    q = q.eq("preacher_id", auth.preacher_id);
  }

  if (since) q = q.gte("date", since);
  if (until) q = q.lt("date", until);
  if (seriesName) q = q.ilike("series_name", `%${seriesName}%`);
  // The reliable tell for un-ingested sermons is null primary_text +
  // null series_name + null sermon_type. We use primary_text as the
  // single proxy because it's the most consistently null when the
  // decomposition pipeline didn't run.
  if (unindexedOnly) {
    q = q.is("primary_text", null);
  }

  const { data, error } = await q;
  if (error) throw new Error(`Sermon list failed: ${error.message}`);

  const sermons = (data ?? []) as unknown as SermonListRow[];

  const dateWindowLabel = since && until
    ? ` between ${since} and ${until}`
    : since
      ? ` since ${since}`
      : until
        ? ` before ${until}`
        : "";
  // Derive is_indexed per row. Null primary_text is the reliable proxy
  // for "registered but not searchable" — these sermons exist in the
  // date list but return no content via search.
  const enriched = sermons.map((s) => {
    // Flatten the joined preacher row so the LLM / formatter sees
    // preacher_name as a top-level field.
    const preacherName = s.preachers?.name ?? undefined;
    return {
      ...s,
      is_indexed: s.primary_text !== null,
      preacher_name: preacherName,
    };
  });

  // Count unindexed in the result so the LLM can caveat — important when
  // the pastor browses dates and gets a list that LOOKS complete but
  // some rows are silently un-searchable.
  const unindexedCount = enriched.filter((s) => !s.is_indexed).length;
  const unindexedNotice = unindexedCount > 0
    ? ` (NOTE: ${unindexedCount} of these have no indexed content yet — ` +
      `they show in the date list but search/get_sermon won't find ` +
      `material in them. Flagged as is_indexed: false in the structured data.)`
    : "";

  const text =
    sermons.length === 0
      ? `No sermons found for ${auth.preacher_name}${dateWindowLabel}${
          seriesName ? ` in series matching "${seriesName}"` : ""
        }${unindexedOnly ? " missing ingestion metadata" : ""}.`
      : enriched
          .map((s) => {
            const idxFlag = s.is_indexed ? "" : " [NOT YET INDEXED]";
            const parts = [
              `${s.date} — ${s.title}${idxFlag}`,
              // Church scope: include "preached by X" so the LLM gets
              // attribution without having to call back for it.
              isChurchScope && s.preacher_name
                ? `   preached by: ${s.preacher_name}`
                : null,
              s.primary_text ? `   text: ${s.primary_text}` : null,
              s.series_name ? `   series: ${s.series_name}` : null,
              `   sermon_id: ${s.id}`,
            ].filter(Boolean);
            return parts.join("\n");
          })
          .join("\n\n") + unindexedNotice;

  return {
    content: [{ type: "text", text }],
    structuredContent: {
      preacher_name: auth.preacher_name,
      sermons: enriched,
      unindexed_count: unindexedCount,
    },
  };
}

function clampInt(v: unknown, min: number, max: number, fallback: number) {
  if (typeof v !== "number" || !Number.isFinite(v)) return fallback;
  return Math.min(max, Math.max(min, Math.floor(v)));
}
