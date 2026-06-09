import type { AuthContext, Env } from "../types";
import { adminClient } from "../auth";
import { runSearchCorpus } from "./search-corpus";
import { runGetSermon } from "./get-sermon";
import { runListRecentSermons } from "./list-recent-sermons";
import { runSurpriseMe } from "./surprise-me";

// Single-tool surface for the MCP server.
//
// The pastor's LLM client only ever sees ONE tool: ask_corpus. It accepts
// a natural-language question and routes server-side to the appropriate
// underlying handler (search, get_sermon, list, surprise). This keeps the
// conversation UX clean — pastors don't see four named tools to choose
// from when conceptually it's one capability: ask the corpus.
//
// The router is conservative: when ambiguous, falls through to semantic
// search rather than guessing wrong on a more specific mode. Search is
// the most general and the result includes enough context to answer
// most follow-ups without a second call.

export const askCorpusTool = {
  name: "ask_corpus",
  description:
    "Ask anything about the pastor's sermon corpus. The tool reads your " +
    "question and decides what to do — search for relevant material across " +
    "all sermons, pull a specific sermon's full text, list recent sermons " +
    "by date, or surface random forgotten units. You don't need to specify " +
    "a mode; just describe what the pastor wants in natural language. " +
    "Always cite results by sermon title and date. Never invent material.\n\n" +
    "FULL SERMON PULL: When the pastor references a specific sermon by " +
    "name or asks you to summarize / show / read / walk through / get the " +
    "content of one sermon, include the FULL sermon title in the question " +
    "verbatim (don't truncate). If you know the sermon UUID, also pass it " +
    "as `sermon_id` for guaranteed routing. The tool will return all " +
    "units in order — that's how to actually summarize one sermon.\n\n" +
    "AUTHOR-SCOPED QUERIES (multi-author endpoints only): When the user " +
    "names a specific voice — \"what did Spurgeon say about hell\", " +
    "\"Piper on suffering\", \"Lloyd-Jones on Romans 8\" — pass the author " +
    "name as the `author` parameter. That HARD-FILTERS to that author and " +
    "ranks within their sermons, so their best units on the topic can't " +
    "lose the global ranking to other voices and disappear. Naming the " +
    "author in the question text alone is only a soft semantic nudge and " +
    "WILL return mixed-author results.",
  inputSchema: {
    type: "object",
    properties: {
      question: {
        type: "string",
        description:
          "The pastor's question or request, in natural language. " +
          "If they're asking about a specific sermon, include the FULL " +
          "title verbatim (not truncated) — the tool uses title matching " +
          "to route full-sermon pulls.\n\n" +
          "Examples:\n" +
          "  - 'have I ever used the cemetery-plots illustration?'\n" +
          "  - 'pull material on Ephesians 4 for an upcoming sermon'\n" +
          "  - 'show me my last 10 sermons'\n" +
          "  - 'surprise me with three things I might have forgotten'\n" +
          "  - 'summarize Seven Habits of Highly Successful Sufferers'\n" +
          "  - 'show me Imperishable Beauty'  (full title, not truncated)\n" +
          "  - 'what's in Virtue as a Vehicle?'\n" +
          "Pass the question through largely as the pastor said it.",
      },
      sermon_id: {
        type: "string",
        description:
          "Optional. If you know the exact UUID of the sermon to fetch " +
          "(e.g., from a prior search or list call), pass it here. This " +
          "guarantees the full-sermon-fetch path regardless of question " +
          "phrasing. Format: 8-4-4-4-12 hex UUID.",
      },
      author: {
        type: "string",
        description:
          "Optional. Restricts the search to a single author on the " +
          "aggregate endpoints (/g Guild Hall, /c/<church-slug> whole " +
          "church). Vector ranking happens WITHIN that author rather than " +
          "across the full roster — which is what you want whenever the " +
          "user names a specific author in their question.\n\n" +
          "Accepts canonical names case-insensitively plus obvious variants:\n" +
          "  - 'Spurgeon', 'Charles Spurgeon', 'charles-spurgeon'\n" +
          "  - 'Lloyd-Jones', 'lloyd jones', 'Martyn Lloyd-Jones'\n" +
          "  - 'piper', 'John Piper', 'john-piper'\n\n" +
          "Guild Hall roster (canonical spellings): C.J. Mahaney, " +
          "Charles Spurgeon, D.A. Carson, David VanAcker, G. Campbell " +
          "Morgan, Haddon Robinson, James Boice, John MacArthur, John " +
          "Piper, John Stott, Kevin DeYoung, Martyn Lloyd-Jones, " +
          "R.C. Sproul, S. Lewis Johnson, Sinclair Ferguson, Thomas " +
          "Watson, Tim Keller, Voddie Baucham.\n\n" +
          "Unknown names produce an error listing the valid roster — " +
          "the tool will NOT silently fall back to an all-author search. " +
          "Rejected on per-preacher endpoints (/p/<slug>) where the " +
          "scope is already a single voice.\n\n" +
          "Pass this whenever the user names an author. Don't pass it " +
          "for general-corpus questions like 'what do Reformed pastors " +
          "say about hell' — that's a cross-author question.",
      },
    },
    required: ["question"],
  } as const,
};

interface AskArgs {
  question?: unknown;
  sermon_id?: unknown;
  author?: unknown;
}

interface RouteDecision {
  mode: "search" | "list" | "surprise" | "get_sermon";
  // Hints the underlying handler reads:
  rhetorical_functions?: string[];
  primary_text?: string;
  limit?: number;
  since?: string;
  until?: string;
  older_than_days?: number;
  sermon_hint?: string;
  // For search mode: a cleaned-up version of the query with aggregation
  // noise stripped, used as the actual embedding/search input.
  clean_query?: string;
  // For search mode: tells the formatter to lean into "show many" framing.
  is_aggregation?: boolean;
  // For list mode: only show sermons missing ingestion metadata.
  unindexed_only?: boolean;
}

// ─── Scripture detection ────────────────────────────────────────────────────
const SCRIPTURE_RE =
  /\b((?:1|2|3|first|second|third|1st|2nd|3rd)\s+)?(genesis|gen|exodus|exod|exo|leviticus|lev|numbers|num|deuteronomy|deut|deu|joshua|josh|judges|judg|ruth|samuel|sam|kings|kgs|chronicles|chron|chr|ezra|nehemiah|neh|esther|esth|job|psalms?|psa?|proverbs|prov|pro|ecclesiastes|eccl|ecc|song|isaiah|isa|jeremiah|jer|lamentations|lam|ezekiel|ezek|eze|daniel|dan|hosea|hos|joel|amos|obadiah|obad|jonah|micah|mic|nahum|nah|habakkuk|hab|zephaniah|zeph|haggai|hag|zechariah|zech|zec|malachi|mal|matthew|matt|mat|mark|mk|luke|lk|john|jn|acts|romans|rom|corinthians|cor|galatians|gal|ephesians|eph|philippians|phil|colossians|col|thessalonians|thess|thes|timothy|tim|titus|philemon|phlm|hebrews|heb|james|jas|peter|pet|jude|revelation|rev)\.?\s+\d+(:\d+(-\d+)?)?\b/i;

// ─── Month name → ISO month index ──────────────────────────────────────────
// Used to parse "May 2026", "Jul-Dec 2025", "from January through June," etc.
const MONTHS: Record<string, number> = {
  january: 1, jan: 1, february: 2, feb: 2, march: 3, mar: 3,
  april: 4, apr: 4, may: 5, june: 6, jun: 6, july: 7, jul: 7,
  august: 8, aug: 8, september: 9, sep: 9, sept: 9,
  october: 10, oct: 10, november: 11, nov: 11, december: 12, dec: 12,
};

function isoMonthBounds(year: number, month: number): { start: string; end: string } {
  const start = `${year}-${String(month).padStart(2, "0")}-01`;
  const nextMonth = month === 12 ? { y: year + 1, m: 1 } : { y: year, m: month + 1 };
  const end = `${nextMonth.y}-${String(nextMonth.m).padStart(2, "0")}-01`;
  return { start, end };
}

// Try to extract a date range from a natural-language fragment. Returns
// { since, until } in YYYY-MM-DD format, or null if no parsable range.
function parseDateRange(s: string): { since?: string; until?: string } | null {
  const monthNames = Object.keys(MONTHS).join("|");

  // "May 2026", "in May 2026", "preached in May 2026"
  const singleMonth = s.match(new RegExp(`\\b(${monthNames})\\s+(\\d{4})\\b`, "i"));
  if (singleMonth) {
    const month = MONTHS[singleMonth[1].toLowerCase()];
    const year = parseInt(singleMonth[2], 10);
    const { start, end } = isoMonthBounds(year, month);
    return { since: start, until: end };
  }

  // Range: "Jul-Dec 2025", "July through December 2025", "from Jan to Jun 2026"
  const range = s.match(
    new RegExp(
      `\\b(${monthNames})\\s*(?:[-–—]|to|through|\\bthru\\b)\\s*(${monthNames})\\s+(\\d{4})\\b`,
      "i",
    ),
  );
  if (range) {
    const m1 = MONTHS[range[1].toLowerCase()];
    const m2 = MONTHS[range[2].toLowerCase()];
    const year = parseInt(range[3], 10);
    const { start } = isoMonthBounds(year, m1);
    const { end } = isoMonthBounds(year, m2);
    return { since: start, until: end };
  }

  // Just a year: "in 2024", "from 2025"
  const yearOnly = s.match(/\b(?:in|from|during|year)\s+(\d{4})\b/i);
  if (yearOnly) {
    const year = parseInt(yearOnly[1], 10);
    return { since: `${year}-01-01`, until: `${year + 1}-01-01` };
  }

  return null;
}

// ─── Aggregation phrasing detection ────────────────────────────────────────
// Queries like "show me everywhere I've preached on X" embed badly because
// the aggregation phrase dilutes the topic vector. Strip the wrapper and
// keep just the topic part for the actual embedding.
function stripAggregation(s: string): { clean: string; isAggregation: boolean } {
  const aggregationPatterns = [
    /show me everywhere (?:i've|i have)?\s*(?:preached|talked|said|written)?\s*(?:about|on|regarding)?\s*/i,
    /everywhere (?:i've|i have)?\s*(?:preached|talked|said|written)?\s*(?:about|on|regarding)?\s*/i,
    /every place (?:i've|i have)?\s*(?:preached|talked|said|written)?\s*(?:about|on|regarding)?\s*/i,
    /all (?:my|the) (?:places|sermons|times) (?:where )?(?:i've|i have)?\s*(?:preached|talked|said|written)?\s*(?:about|on|regarding)?\s*/i,
    /every time (?:i've|i have)?\s*(?:preached|talked|said|written)?\s*(?:about|on|regarding)?\s*/i,
    /everything (?:i've|i have)?\s*(?:said|written|preached)?\s*(?:about|on|regarding)?\s*/i,
  ];
  for (const pat of aggregationPatterns) {
    if (pat.test(s)) {
      return { clean: s.replace(pat, "").trim(), isAggregation: true };
    }
  }
  return { clean: s, isAggregation: false };
}

// ─── Sermon-title hint cleanup ─────────────────────────────────────────────
// The raw regex capture may include junk like quotes, trailing "in order",
// "intro to conclusion", "from start to finish", etc. Strip those so the
// fuzzy title match has a clean shot.
function cleanSermonHint(hint: string): string {
  let h = hint.trim();
  // Strip surrounding quotes (straight + curly)
  h = h.replace(/^["'""''`]+|["'""''`]+$/g, "");
  // Strip trailing common modifiers
  const trailingJunk = [
    /\s+in\s+order\b.*$/i,
    /\s+(?:intro|from start)\s+to\s+(?:conclusion|finish|end)\b.*$/i,
    /\s+(?:from\s+)?(?:start|beginning)\s+to\s+(?:finish|end|conclusion)\b.*$/i,
    /\s+(?:in\s+full|complete|entirely)\b.*$/i,
    /\s+please\b.*$/i,
    /\s+(?:sermon|message)$/i,
    /[.,!?]+$/,
    /^the\s+/i,
  ];
  for (const pat of trailingJunk) h = h.replace(pat, "");
  h = h.trim();
  // Strip residual surrounding quotes after trimming
  h = h.replace(/^["'""''`]+|["'""''`]+$/g, "").trim();
  return h;
}

// ─── Intent router ──────────────────────────────────────────────────────────

function routeIntent(question: string): RouteDecision {
  const s = question.toLowerCase().trim();

  // (1) Surprise / serendipity
  if (
    /(^|\s)(surprise me|stumble[- ]?upon|forgotten|something random|random (illustration|story|thing))/.test(s) ||
    /(remind me of (something|some) (forgotten|old|random))/.test(s)
  ) {
    const decision: RouteDecision = { mode: "surprise" };
    const olderMatch = s.match(/older than (\d+)\s*(day|week|month|year)s?/);
    if (olderMatch) {
      const n = parseInt(olderMatch[1], 10);
      const unit = olderMatch[2];
      const days =
        unit === "year" ? n * 365
        : unit === "month" ? n * 30
        : unit === "week" ? n * 7
        : n;
      decision.older_than_days = days;
    }
    return decision;
  }

  // (2a) Ingestion-coverage queries — "what isn't indexed / searchable /
  // ingested." Routes to list mode with unindexed_only=true. Lets the
  // pastor see exactly which sermons appear in the catalog but have no
  // content yet (HIGH-2 from the 2026-06-03 test report).
  if (
    /(which|what) (?:sermons|of my sermons)? ?(?:are |aren'?t |haven'?t (?:been )?)(?:indexed|ingested|processed|searchable|content[- ]indexed)/.test(s) ||
    /(?:show me|list) (?:the )?(?:unindexed|un-indexed|unsearchable|missing|incomplete|pending) sermons?/.test(s) ||
    /what (?:hasn'?t|haven'?t) (?:been )?(?:indexed|ingested|processed|loaded)/.test(s) ||
    /which sermons are missing (?:content|transcripts|units)/.test(s)
  ) {
    return { mode: "list", limit: 50, unindexed_only: true };
  }

  // (2) Browse-by-date / list mode — now with proper month/range parsing.
  // Patterns accept both per-preacher phrasing ("my last 5 sermons") and
  // multi-preacher phrasing ("show me 5 sermons", "list 5 sermons") — the
  // multi-preacher version matters for /c/<church> and /g where the LLM
  // doesn't have a "my" relationship to the corpus.
  const looksLikeListQuery =
    /(my (last|recent) \d* ?sermons?)|(list .* sermons)|(what (have|did) i (been )?preach)|(recent (preaching|sermons))|(what (did|have) i preach.*(in|during|from))|(my sermons (in|from|during))|(sermons (in|from|during))|(preached (in|during|from))|((show|give|get|pull|fetch) (me )?(\d+|some|a few|the) (recent |last )?sermons?)|((show|list|browse) (me )?(recent |all |latest )?sermons?)/.test(s);
  if (looksLikeListQuery) {
    const decision: RouteDecision = { mode: "list", limit: 10 };

    // limit from "last N sermons" or "show me N sermons"
    const nMatch = s.match(/(?:last|recent|show me|give me|pull|get me|list) (\d+) ?(?:recent |last )?sermons?/);
    if (nMatch) decision.limit = Math.min(50, parseInt(nMatch[1], 10));

    // date constraints (month, range, year)
    const dateRange = parseDateRange(s);
    if (dateRange) {
      if (dateRange.since) decision.since = dateRange.since;
      if (dateRange.until) decision.until = dateRange.until;
      // When the user specifies a date window, they typically want all
      // sermons in that window, not just 10. Bump the limit.
      decision.limit = 50;
    }
    return decision;
  }

  // (3) Get-sermon / pull-full mode — significantly widened phrasing
  // detection. The router now catches many more shapes pastors actually use.
  const fullPullPatterns: RegExp[] = [
    // Explicit "full / whole / entire"
    /(?:show|pull|give|read|get) (?:me )?(?:the )?(?:full|whole|entire|complete) (?:text(?: of)?|sermon|transcript|content)(?: of| for| from| on)?\s+["'""''`]?(.+?)["'""''`]?$/i,
    /(?:full|whole|entire|complete) (?:text of|transcript of|sermon|message)(?: called| titled| named)?\s+["'""''`]?(.+?)["'""''`]?$/i,
    // "Every unit of X" / "all units of X"
    /(?:every|all|each) units? of\s+["'""''`]?(.+?)["'""''`]?$/i,
    // "Pull X" / "Show me X" — only when X looks title-like (capitalized
    // in original) and there's no clear topical phrasing. We use the
    // original-case question for the title-likeness check.
    /^(?:pull|show me|give me|read me|read out|let's see|let me see|i want to (?:see|read)|can i see|can you (?:show|pull|give) me) (?:the )?["'""''`](.+?)["'""''`]/i,
    // "Sermon called/titled/named X"
    /(?:sermon|message) (?:called|titled|named)\s+["'""''`]?(.+?)["'""''`]?$/i,
    // "Read me X in order" / "X intro to conclusion"
    /(?:read|pull|show) (?:me )?(.+?) (?:in order|intro to (?:conclusion|finish|end)|from start to finish|from beginning to end)$/i,
    // "Tell me about / about the X sermon"
    /tell me about (?:the )?(.+?) sermon(?: in (?:full|order))?$/i,
    // "Open / take me to X"
    /(?:open|take me to|navigate to)\s+["'""''`]?(.+?)["'""''`]?$/i,
  ];
  for (const pat of fullPullPatterns) {
    const m = question.match(pat);
    if (m && m[1]) {
      const hint = cleanSermonHint(m[1]);
      if (hint.length >= 3) {
        return { mode: "get_sermon", sermon_hint: hint };
      }
    }
  }

  // (4) Recall queries — bias toward illustrations
  if (
    /(have i (ever )?(used|preached|said))|(did i (use|preach|say))|(have i used)|(i preached this)|(used (this|that) (illustration|story))|(preached.*before)|(ever (preach|use))/.test(s)
  ) {
    const { clean, isAggregation } = stripAggregation(s);
    return {
      mode: "search",
      rhetorical_functions: ["illustration"],
      clean_query: clean,
      is_aggregation: isAggregation,
    };
  }

  // (5) Prep queries — scripture refs or explicit prep language
  const scriptureMatch = question.match(SCRIPTURE_RE);
  if (
    scriptureMatch ||
    /(\bprep\b|preparing|coming up|next (sunday|week)|upcoming|pull .* for|sermon on)/.test(s)
  ) {
    const decision: RouteDecision = { mode: "search" };
    const { clean, isAggregation } = stripAggregation(s);
    decision.clean_query = clean;
    decision.is_aggregation = isAggregation;
    // primary_text is a HARD filter that restricts to sermons preached
    // on this text. That's right for prep ("I'm preparing on Eph 4") but
    // WRONG for aggregation ("everywhere I've referenced X from Eph 4")
    // where the pastor wants references across all sermons. Only set the
    // hard filter when there's no aggregation framing.
    if (scriptureMatch && !isAggregation) {
      decision.primary_text = scriptureMatch[0];
    }
    return decision;
  }

  // (6) Default — open semantic search, with aggregation stripping
  const { clean, isAggregation } = stripAggregation(s);
  return { mode: "search", clean_query: clean, is_aggregation: isAggregation };
}

// ─── Command-prefix stripping ──────────────────────────────────────────────
// Strip leading verb phrases that the LLM uses ("show me", "summarize",
// "walk me through") so the title-in-question lookup can find a clean
// title at the START. Without this, "show me Seven Habits" hits none of
// our bidirectional cases because "show me Seven Habits" is not a
// substring of any title, nor is it a prefix.

function stripCommandPrefix(q: string): string {
  let cleaned = q.trim();
  const prefixes = [
    // Verb + "me" forms ("show me", "tell me about")
    /^(?:show|tell|give|pull|read|get|fetch|find|bring) me (?:about )?(?:the )?/i,
    // "Full text of" style explicit pulls
    /^(?:show|tell|give|pull|read|get|fetch|find|bring) (?:me )?(?:the )?(?:full|whole|entire|complete) (?:text(?: of)?|sermon|transcript|content)(?: of| for| from| on)?\s+/i,
    // Bare imperative verbs ("show X", "get X", "open X") — safe because
    // these only make sense if X is a specific sermon title. We restrict
    // to clearly-imperative verbs ("find" excluded because "find material
    // on X" is a topical search, not a title reference).
    /^(?:show|pull|open|get|fetch|bring|read|grab)\s+(?:up\s+)?(?:the )?/i,
    /^(?:summarize|summary of|recap|outline|abstract of)\s+(?:the )?/i,
    /^(?:walk me through|run me through|run through|take me through)\s+(?:the )?/i,
    /^(?:what(?:'s| is| does)?(?: in)?)\s+(?:the )?/i,
    /^(?:i want to (?:read|see|hear)|i'd like to (?:read|see|hear))\s+(?:the )?/i,
    /^(?:open|take me to|navigate to|jump to|go to)\s+(?:the )?/i,
    /^(?:let me see|let me read|let me hear)\s+(?:the )?/i,
    /^(?:can (?:i|you) (?:see|read|pull|show))\s+(?:me )?(?:the )?/i,
    /^(?:please )?/i, // strip leading politeness
  ];
  // Apply repeatedly so chained prefixes get peeled (e.g. "please show me")
  for (let i = 0; i < 3; i++) {
    let changed = false;
    for (const p of prefixes) {
      const next = cleaned.replace(p, "").trim();
      if (next !== cleaned) {
        cleaned = next;
        changed = true;
      }
    }
    if (!changed) break;
  }
  // Strip trailing punctuation and trailing "sermon" word
  cleaned = cleaned
    .replace(/[?!.]+$/, "")
    .replace(/\s+(?:sermon|message|talk|transcript)\s*$/i, "")
    .replace(/\s+in order$/i, "")
    .replace(/\s+intro to (?:conclusion|finish|end)$/i, "")
    .trim();
  return cleaned;
}

// ─── Title-in-question lookup ───────────────────────────────────────────────
// Strongest get_sermon signal: a real sermon title overlaps significantly
// with the (prefix-stripped) question. Catches LLM phrasings of every
// shape — "summarize X", "show me X", "tell me about X" — without
// requiring the regex layer to enumerate every possible verb form.
//
// We try the lookup with the original question AND with the stripped
// version. The RPC returns the highest-scoring match across either path.

async function findSermonTitleInQuestion(
  question: string,
  auth: AuthContext,
  env: Env,
): Promise<string | null> {
  const wordCount = question.split(/\s+/).length;
  if (wordCount > 18) return null;
  if (question.trim().length < 5) return null;

  const supabase = adminClient(env);
  // Try the stripped form first — it's the most likely to hit Case 2 or 3
  // (exact/prefix). Falls back to the original if stripping yielded nothing.
  const stripped = stripCommandPrefix(question);
  const candidates = stripped !== question && stripped.length >= 3
    ? [stripped, question]
    : [question];

  const isChurchScope = (auth.scope === "church" || auth.scope === "guild") && auth.preacher_ids?.length;
  for (const candidate of candidates) {
    const rpcCall = isChurchScope
      ? supabase.rpc("find_sermon_by_title_in_text_church", {
          p_preacher_ids: auth.preacher_ids!,
          p_text: candidate,
        })
      : supabase.rpc("find_sermon_by_title_in_text", {
          p_preacher_id: auth.preacher_id,
          p_text: candidate,
        });
    const { data, error } = await rpcCall;
    if (error) continue;
    if (typeof data === "string" && data.length > 0) {
      return data;
    }
  }
  return null;
}

// UUID detection — if the question contains a sermon_id (LLM may pass it
// when the user references a specific sermon by id), route directly.
const UUID_RE =
  /\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b/i;

// ─── Fuzzy sermon lookup ────────────────────────────────────────────────────
// Resolves a free-text sermon hint to a sermon_id. Tries multiple strategies:
//   1. Exact title (case-insensitive)
//   2. ILIKE substring with the full hint
//   3. ILIKE substring with progressively shorter hint (handles trailing junk)
//   4. ts_rank via full-text search on titles
// Returns the best match's id, or null if nothing scored well enough.

async function resolveSermonByHint(
  hint: string,
  auth: AuthContext,
  env: Env,
): Promise<string | null> {
  const supabase = adminClient(env);
  const cleaned = hint.trim();
  if (cleaned.length < 3) return null;

  // Helper applies the right preacher-scope filter for either mode.
  const isChurchScope = (auth.scope === "church" || auth.scope === "guild") && auth.preacher_ids?.length;
  const scoped = <T>(qb: T): T => {
    if (isChurchScope) {
      return (qb as unknown as { in: (col: string, vals: string[]) => T }).in(
        "preacher_id",
        auth.preacher_ids!,
      );
    }
    return (qb as unknown as { eq: (col: string, val: string) => T }).eq(
      "preacher_id",
      auth.preacher_id,
    );
  };

  // Strategy 1: exact title match
  const { data: exact } = await scoped(
    supabase.from("sermons").select("id, title"),
  )
    .ilike("title", cleaned)
    .limit(1);
  if (exact && exact.length > 0) return exact[0].id;

  // Strategy 2: substring ILIKE
  const { data: substr } = await scoped(
    supabase.from("sermons").select("id, title"),
  )
    .ilike("title", `%${cleaned}%`)
    .limit(5);
  if (substr && substr.length > 0) {
    // Pick the shortest title — usually the most specific match
    return substr.sort((a, b) => a.title.length - b.title.length)[0].id;
  }

  // Strategy 3: try with progressively shorter prefixes — handles cases
  // where the hint has junk at the end that our cleaner missed.
  const words = cleaned.split(/\s+/);
  if (words.length > 2) {
    const firstWords = words.slice(0, Math.max(2, Math.floor(words.length / 2)))
      .join(" ");
    const { data: prefix } = await scoped(
      supabase.from("sermons").select("id, title"),
    )
      .ilike("title", `%${firstWords}%`)
      .limit(5);
    if (prefix && prefix.length > 0) {
      return prefix.sort((a, b) => a.title.length - b.title.length)[0].id;
    }
  }

  return null;
}

// ─── Dispatcher ─────────────────────────────────────────────────────────────
// ─── Author resolution ─────────────────────────────────────────────────────
// Resolve a free-text author name to one preacher in the eligible roster
// (auth.preacher_ids) on aggregate scopes (/g, /c/<church>). Returns a new
// AuthContext narrowed to that single preacher_id so the downstream tools
// (search, list, surprise, get_sermon) all scope their queries to that
// author by the same in()/eq() preacher filter they already implement.
//
// Resolution strategies, in order of decreasing specificity:
//   1. Exact case-insensitive name match           ("Charles Spurgeon")
//   2. Exact slug match                            ("charles-spurgeon")
//   3. Last-name only                              ("Spurgeon", "Lloyd-Jones")
//   4. Partial substring match (unique candidate)  ("Lloyd-Jones" within
//                                                   "Martyn Lloyd-Jones")
//   5. Slug-normalized last-name match             ("lloyd jones",
//                                                   "lloydjones")
//
// Unknown input throws an Error whose message lists the canonical roster
// — the user explicitly asked for NO silent fallback, since the current
// "soft semantic nudge" behavior produces mixed-author results that look
// authoritative.
async function resolveAuthor(
  input: string,
  auth: AuthContext,
  env: Env,
): Promise<AuthContext> {
  if (auth.scope !== "guild" && auth.scope !== "church") {
    throw new Error(
      "`author` only applies on aggregate endpoints (/g Guild Hall or " +
        "/c/<church-slug> whole church). This endpoint is already scoped " +
        "to a single voice; drop the author parameter."
    );
  }
  if (!auth.preacher_ids?.length) {
    throw new Error(
      "No preacher roster on this scope; cannot resolve author."
    );
  }

  const supabase = adminClient(env);
  const { data: roster, error } = await supabase
    .from("preachers")
    .select("id, name, slug")
    .in("id", auth.preacher_ids);
  if (error) {
    throw new Error(`Roster lookup failed: ${error.message}`);
  }
  const eligible = (roster ?? []) as Array<{
    id: string;
    name: string;
    slug: string;
  }>;

  const needle = input.trim();
  const lower = needle.toLowerCase();
  // Normalize hyphens/underscores/punctuation → "lloyd-jones" and "lloyd jones"
  // and "Lloyd-Jones" all collapse to "lloyd-jones".
  const norm = (s: string) =>
    s.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "");
  const needleSlug = norm(needle);

  // (1) Exact name (case-insensitive)
  let match = eligible.find((p) => p.name.toLowerCase() === lower);

  // (2) Exact slug
  if (!match) match = eligible.find((p) => p.slug === needleSlug);

  // (3) Last-name only — uses the slug-normalized form so "Lloyd-Jones"
  // matches the slug "lloyd-jones" embedded in "martyn-lloyd-jones".
  if (!match) {
    const lastCandidates = eligible.filter((p) => {
      const lastName = p.name.split(/\s+/).slice(-1)[0];
      return norm(lastName) === needleSlug;
    });
    if (lastCandidates.length === 1) match = lastCandidates[0];
  }

  // (4) Substring containment — handles "lloyd jones" inside the canonical
  // "martyn lloyd-jones" (after norm), and "Piper" inside "John Piper".
  if (!match) {
    const partial = eligible.filter((p) => {
      const pn = norm(p.name);
      return pn.includes(needleSlug) || needleSlug.includes(pn);
    });
    if (partial.length === 1) match = partial[0];
  }

  if (!match) {
    const roster_list = eligible
      .map((p) => p.name)
      .sort()
      .join(", ");
    throw new Error(
      `Unknown author "${input}". Valid authors on this endpoint: ${roster_list}.`
    );
  }

  return {
    ...auth,
    preacher_id: match.id,
    preacher_name: match.name,
    preacher_ids: [match.id],
  };
}

export async function runAskCorpus(
  args: AskArgs,
  auth: AuthContext,
  env: Env,
) {
  const question =
    typeof args.question === "string" ? args.question.trim() : "";
  if (!question) {
    throw new Error("ask_corpus requires a non-empty `question` string");
  }

  // Author override (aggregate endpoints only). Resolved BEFORE any other
  // dispatch so every downstream call — sermon_id, get_sermon, list,
  // surprise, search — runs against the narrowed roster. This is the hard
  // filter the feature request asked for: vector ranking happens WITHIN
  // the chosen author, not across all 18.
  const authorArg =
    typeof args.author === "string" && args.author.trim()
      ? args.author.trim()
      : "";
  if (authorArg) {
    auth = await resolveAuthor(authorArg, auth, env);
    console.log(
      `[ask_corpus] author override → ${auth.preacher_name} (${auth.preacher_id})`
    );
  }

  // Explicit sermon_id arg wins over everything else. The LLM passes this
  // when it has the exact UUID and wants guaranteed routing — e.g., after
  // a prior list_recent_sermons surfaced the id, or when summarizing a
  // specific sermon the user just discussed.
  const explicitSermonId =
    typeof args.sermon_id === "string" && UUID_RE.test(args.sermon_id)
      ? args.sermon_id
      : null;
  if (explicitSermonId) {
    console.log(
      `[ask_corpus] explicit sermon_id arg → get_sermon ${explicitSermonId}`,
    );
    return runGetSermon({ sermon_id: explicitSermonId }, auth, env);
  }

  const decision = routeIntent(question);
  console.log(
    `[ask_corpus] mode=${decision.mode} q="${question.slice(0, 80)}"` +
      (decision.sermon_hint ? ` hint="${decision.sermon_hint}"` : "") +
      (decision.since ? ` since=${decision.since}` : "") +
      (decision.until ? ` until=${decision.until}` : ""),
  );

  switch (decision.mode) {
    case "surprise":
      return runSurpriseMe(
        {
          count: 3,
          older_than_days: decision.older_than_days,
        },
        auth,
        env,
      );

    case "list":
      return runListRecentSermons(
        {
          limit: decision.limit,
          since: decision.since,
          until: decision.until,
          unindexed_only: decision.unindexed_only,
        },
        auth,
        env,
      );

    case "get_sermon": {
      const sermonId = decision.sermon_hint
        ? await resolveSermonByHint(decision.sermon_hint, auth, env)
        : null;
      if (sermonId) {
        return runGetSermon({ sermon_id: sermonId }, auth, env);
      }
      // No confident title match — fall through to search, but tell the
      // LLM (via the formatter) that we tried to find a specific sermon
      // and couldn't. Search results may help the LLM say "I'm not sure
      // which sermon you mean — these have similar themes."
      console.log(
        `[ask_corpus] get_sermon: no title match for "${decision.sermon_hint}"; falling through to search`,
      );
      return runSearchCorpus(
        {
          query: decision.clean_query ?? question,
        },
        auth,
        env,
      );
    }

    case "search":
    default: {
      // Title-grounded routing: before falling to semantic search, check
      // whether the question contains a real sermon title as a substring.
      // If so, the user is almost certainly asking about that specific
      // sermon — route to get_sermon for the full ordered transcript,
      // bypassing semantic ranking. Catches phrasings the regex layer
      // misses ("summarize X", "show me X", "what's in X", etc.) — the
      // round-2 test report (2026-06-03) showed the LLM consistently
      // using these.
      const uuidMatch = question.match(UUID_RE);
      if (uuidMatch) {
        console.log(`[ask_corpus] UUID detected: ${uuidMatch[0]}`);
        return runGetSermon({ sermon_id: uuidMatch[0] }, auth, env);
      }
      const titleSermonId = await findSermonTitleInQuestion(question, auth, env);
      if (titleSermonId) {
        console.log(
          `[ask_corpus] title-in-question match → get_sermon ${titleSermonId}`,
        );
        return runGetSermon({ sermon_id: titleSermonId }, auth, env);
      }

      return runSearchCorpus(
        {
          query: decision.clean_query ?? question,
          rhetorical_functions: decision.rhetorical_functions,
          primary_text: decision.primary_text,
          // Aggregation queries get a higher limit so the LLM has more
          // material to list ("here are the 8 places you've covered X").
          limit: decision.is_aggregation ? 10 : undefined,
        },
        auth,
        env,
      );
    }
  }
}
