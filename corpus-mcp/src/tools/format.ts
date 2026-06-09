import type { SermonUnitHit } from "../types";

// Shared formatter — both search_corpus and surprise_me render their
// hits the same way so the LLM gets a consistent shape regardless of
// which tool produced them.

interface FormatOpts {
  preacherName: string;
  query: string;
  strongCount: number;
  totalCount: number;
  threshold: number;
  header?: string;
  // When true, the formatter prepends an explicit "no real match" notice
  // telling the LLM that the top hit is below the absolute confidence
  // floor and the user should be told nothing matched.
  noRealMatch?: boolean;
  topScore?: number;
}

export function formatHitsAsText(
  hits: Array<Partial<SermonUnitHit>>,
  opts: FormatOpts,
): string {
  if (hits.length === 0) {
    return (
      `No units found in ${opts.preacherName}'s corpus matching "${opts.query}". ` +
      `Tell the user plainly that you don't find anything in their prior ` +
      `preaching speaking to this — they may not have preached it yet.`
    );
  }

  const lines: string[] = [];
  if (opts.header) {
    lines.push(opts.header, "");
  } else if (opts.noRealMatch) {
    // Hard "no match" signal — the top hit is below the absolute floor.
    // Tell the LLM unambiguously that there's nothing real here, so it
    // doesn't get tricked by a 0.45 score into thinking it found
    // something. The hits are still included as nearest-neighbor context
    // for the LLM to acknowledge ("I looked, but the closest things in
    // your corpus are...") rather than confidently cite.
    lines.push(
      `**No real match found in the pastor's corpus for "${opts.query}".** ` +
        `The top semantic score is ${(opts.topScore ?? 0).toFixed(2)} — ` +
        `below the floor (${(opts.topScore ?? 0) < 0.5 ? "0.50" : "weak"}) ` +
        `where matches are trustworthy. The hits below are the nearest ` +
        `neighbors in semantic space, but they likely don't answer the ` +
        `question. Tell the user plainly that you don't find anything in ` +
        `their corpus speaking to this topic. Do NOT cite the hits below ` +
        `as if they answered the question — at most, acknowledge "the ` +
        `nearest thing was X, but it isn't really about this."`,
      "",
    );
  } else if (opts.strongCount < opts.totalCount && opts.threshold > 0) {
    // Mixed strong + weak: label them so the LLM treats them differently.
    lines.push(
      `Retrieved ${opts.totalCount} candidates for "${opts.query}". ` +
        `${opts.strongCount} pass the strong-match threshold (score ≥ ` +
        `${opts.threshold.toFixed(2)}); the rest are nearest neighbors ` +
        `included for context. If only the weak ones answer the question, ` +
        `say so plainly rather than overclaiming.`,
      "",
    );
  } else {
    lines.push(
      `Retrieved ${opts.totalCount} unit${opts.totalCount === 1 ? "" : "s"} for "${opts.query}".`,
      "",
    );
  }

  for (const h of hits) {
    const score = typeof h.final_score === "number" ? h.final_score : null;
    const strong =
      score === null || opts.threshold === 0 || score >= opts.threshold;
    const scoreLabel =
      score === null
        ? ""
        : strong
          ? ` · score ${score.toFixed(2)}`
          : ` · score ${score.toFixed(2)} (WEAK)`;
    const loci = h.doctrinal_loci?.length
      ? ` · loci: ${h.doctrinal_loci.join(", ")}`
      : "";
    const subtype = h.illustration_type ? ` / ${h.illustration_type}` : "";

    // Church-scope hits carry per-row preacher_name; render it so the LLM
    // attributes results correctly across a multi-preacher church corpus.
    // Per-preacher hits don't carry it — preacher attribution is already
    // clear from the connector context.
    const attribution = h.preacher_name ? ` — ${h.preacher_name}` : "";
    lines.push(
      `### ${h.sermon_title} — ${h.sermon_date}${attribution} — §${h.unit_index}`,
    );
    lines.push(
      `${h.rhetorical_function}${subtype}${loci}${scoreLabel}` +
        (h.primary_text ? ` · text: ${h.primary_text}` : ""),
    );
    if (h.summary) lines.push(`Key claim: ${h.summary}`);
    lines.push("", h.content ?? "", "");
  }

  return lines.join("\n");
}
