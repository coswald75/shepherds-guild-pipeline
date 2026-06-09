import { adminClient } from "../auth";
import type { AuthContext, Env, SermonWithUnits } from "../types";

// get_sermon — pull the full record for a sermon plus its decomposed
// units. Use after search_corpus returns a relevant unit and the LLM
// wants surrounding context ("what else did the pastor say in this
// sermon?"). RLS is bypassed via service role; we enforce ownership in
// the WHERE clause: only the authenticated pastor's sermons are visible.

export const getSermonTool = {
  name: "get_sermon",
  description:
    "Fetch a full sermon record by id, including all decomposed units " +
    "(in order), the primary text, abstract, main thesis, and series " +
    "info. Use this when search_corpus returns a relevant unit and you " +
    "want fuller context — what else the pastor said in that sermon, " +
    "the overall structure, or the thesis statement.",
  inputSchema: {
    type: "object",
    properties: {
      sermon_id: {
        type: "string",
        description:
          "The sermon UUID returned by search_corpus (sermon_id field).",
      },
    },
    required: ["sermon_id"],
  } as const,
};

interface GetSermonArgs {
  sermon_id?: unknown;
}

export async function runGetSermon(
  args: GetSermonArgs,
  auth: AuthContext,
  env: Env,
) {
  const sermonId =
    typeof args.sermon_id === "string" ? args.sermon_id.trim() : "";
  if (!sermonId) {
    throw new Error("get_sermon requires `sermon_id`");
  }

  const supabase = adminClient(env);

  // Pull the sermon scoped to the authenticated identity. For per-preacher
  // auth: single preacher_id filter (tenancy gate). For church-scope:
  // filter by IN(preacher_ids) and join preacher name for attribution.
  //
  // The select string and the filter are conditional, so the static return
  // type from supabase-js can't infer correctly; we cast through `unknown`
  // and use SermonRowWithJoin below for the shape we actually expect.
  const isChurchScope = auth.scope === "church" && auth.preacher_ids?.length;
  type SermonRowWithJoin = {
    id: string;
    title: string;
    date: string;
    primary_text: string | null;
    sermon_type: string | null;
    series_name: string | null;
    abstract: string | null;
    main_thesis: string | null;
    preacher_id: string;
    preachers?: { name: string };
  };
  const baseSelect = isChurchScope
    ? "id, title, date, primary_text, sermon_type, series_name, abstract, main_thesis, preacher_id, preachers!inner(name)"
    : "id, title, date, primary_text, sermon_type, series_name, abstract, main_thesis, preacher_id";
  let q = supabase
    .from("sermons")
    // deno-fmt-ignore — the .select() type breaks on conditional strings; cast through any.
    .select(baseSelect as never)
    .eq("id", sermonId);
  q = isChurchScope
    ? q.in("preacher_id", auth.preacher_ids!)
    : q.eq("preacher_id", auth.preacher_id);
  const { data: rawSermon, error: sErr } = await q.maybeSingle();
  const sermon = rawSermon as unknown as SermonRowWithJoin | null;

  if (sErr) throw new Error(`Sermon lookup failed: ${sErr.message}`);
  if (!sermon) {
    return {
      content: [
        {
          type: "text",
          text:
            `No sermon with id ${sermonId} found in ${auth.preacher_name}'s corpus. ` +
            `(Either the id is wrong, or it belongs to a different preacher.)`,
        },
      ],
      isError: true,
    };
  }

  // In church-scope mode, resolve the actual preacher_name from the joined
  // row so the rendered output attributes correctly even when /c/ is hit
  // without a ?speaker= filter.
  const preacherName = isChurchScope
    ? (sermon.preachers?.name ?? auth.preacher_name)
    : auth.preacher_name;

  const { data: units, error: uErr } = await supabase
    .from("units")
    .select(
      "id, unit_index, rhetorical_function, illustration_type, doctrinal_loci, summary, content",
    )
    .eq("sermon_id", sermonId)
    .order("unit_index", { ascending: true });

  if (uErr) throw new Error(`Unit fetch failed: ${uErr.message}`);

  const record: SermonWithUnits = {
    id: sermon.id,
    title: sermon.title,
    date: sermon.date,
    primary_text: sermon.primary_text,
    sermon_type: sermon.sermon_type,
    series_name: sermon.series_name,
    abstract: sermon.abstract,
    main_thesis: sermon.main_thesis,
    preacher_name: preacherName,
    units: (units ?? []).map((u) => ({
      unit_id: u.id,
      unit_index: u.unit_index,
      rhetorical_function: u.rhetorical_function,
      illustration_type: u.illustration_type,
      doctrinal_loci: u.doctrinal_loci,
      summary: u.summary,
      content: u.content,
    })),
  };

  const text = renderSermonAsText(record);

  return {
    content: [{ type: "text", text }],
    structuredContent: record,
  };
}

function renderSermonAsText(s: SermonWithUnits): string {
  const lines: string[] = [];
  lines.push(`# ${s.title}`);
  lines.push(`Preacher: ${s.preacher_name}`);
  lines.push(`Date: ${s.date}`);
  if (s.primary_text) lines.push(`Primary text: ${s.primary_text}`);
  if (s.series_name) lines.push(`Series: ${s.series_name}`);
  if (s.sermon_type) lines.push(`Type: ${s.sermon_type}`);
  if (s.main_thesis) lines.push(`\n## Main thesis\n${s.main_thesis}`);
  if (s.abstract) lines.push(`\n## Abstract\n${s.abstract}`);
  lines.push(`\n## Units (${s.units.length})`);
  for (const u of s.units) {
    const loci = u.doctrinal_loci?.length ? ` · ${u.doctrinal_loci.join(", ")}` : "";
    const subtype = u.illustration_type ? ` / ${u.illustration_type}` : "";
    lines.push(
      `\n### §${u.unit_index} · ${u.rhetorical_function}${subtype}${loci}`,
    );
    if (u.summary) lines.push(`*${u.summary}*`);
    lines.push(u.content);
  }
  return lines.join("\n");
}
