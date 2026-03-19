// Shepherd's Guild — PreFlight Check Edge Function
// Analyzes a sermon draft against a pastor's coaching benchmarks
// Called from showcasev4.html via: POST /functions/v1/preflight-check

import { serve } from "https://deno.land/std@0.177.0/http/server.ts";
import { createClient } from "https://esm.sh/@supabase/supabase-js@2";

const corsHeaders = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers":
    "authorization, x-client-info, apikey, content-type",
};

serve(async (req: Request) => {
  // Handle CORS preflight
  if (req.method === "OPTIONS") {
    return new Response("ok", { headers: corsHeaders });
  }

  try {
    const { preacher_id, sermon_text } = await req.json();

    if (!preacher_id || !sermon_text) {
      return new Response(
        JSON.stringify({ error: "preacher_id and sermon_text are required" }),
        { status: 400, headers: { ...corsHeaders, "Content-Type": "application/json" } }
      );
    }

    // ── Supabase client ──
    const supabaseUrl = Deno.env.get("SUPABASE_URL")!;
    const supabaseKey = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!;
    const sb = createClient(supabaseUrl, supabaseKey);

    // ── Get preacher name ──
    const { data: preacher, error: pErr } = await sb
      .from("preachers")
      .select("id, name")
      .eq("id", preacher_id)
      .single();

    if (pErr || !preacher) {
      return new Response(
        JSON.stringify({ error: "Preacher not found" }),
        { status: 404, headers: { ...corsHeaders, "Content-Type": "application/json" } }
      );
    }

    const name = preacher.name;
    const firstName = name.split(" ")[0];

    // ── Get analysis data ──
    const { data: analysis, error: aErr } = await sb
      .from("preacher_analysis")
      .select("growth_areas, growth_intro, hall_distinction, exemplar_matches, stats")
      .eq("preacher_id", preacher_id)
      .single();

    if (aErr || !analysis) {
      return new Response(
        JSON.stringify({ error: "No analysis found. Run generate_analysis.py first." }),
        { status: 404, headers: { ...corsHeaders, "Content-Type": "application/json" } }
      );
    }

    const stats = analysis.stats || {};
    const growthAreas = analysis.growth_areas || [];
    const hall = analysis.hall_distinction || {};
    const exemplars = analysis.exemplar_matches || [];

    // ── Build benchmark summary ──
    let benchmarksText = "";
    for (let i = 0; i < growthAreas.length; i++) {
      const ga = growthAreas[i];
      benchmarksText += `
### Benchmark ${i + 1}: ${ga.label || "Unknown"} (Current: ${ga.metric_current || "?"}, Target: ${ga.metric_target || "?"})
Title: ${ga.title_html || ""}
Diagnosis: ${ga.diagnosis || ""}
Recommendation: ${ga.recommendation || ""}
`;
    }

    let exemplarText = "";
    for (const ex of exemplars) {
      exemplarText += `- ${ex.rank}: ${ex.preacher_name} (${ex.match_pct}%) — ${(ex.reasons || []).join(", ")}\n`;
    }

    // ── Build prompt ──
    const prompt = `You are a homiletics coach for The Shepherd's Guild. You are analyzing a sermon BEFORE it is preached, against the pastor's established coaching benchmarks.

## Pastor Profile: ${name}
- Hall Distinction: ${hall.label || "Unknown"} — ${hall.text || ""}
- Key stat: ${hall.stat_n || ""} ${hall.stat_label || ""}
- Corpus: ${stats.sermon_count || "?"} sermons, ${stats.total_units || "?"} units
- Illustration density: ${stats.illustration_density || "?"} per sermon
- Application per sermon: ${stats.application_per_sermon || "?"}

## Exemplar Matches
${exemplarText}

## ${firstName}'s Coaching Benchmarks (Growth Areas)
${benchmarksText}

## THE SERMON TO ANALYZE

${sermon_text}

## YOUR TASK

Analyze this sermon against ${firstName}'s coaching benchmarks. For each benchmark, evaluate how well THIS specific sermon performs relative to the growth area. Be specific — cite actual lines and moments from the sermon.

Return JSON with this structure:

{
  "sermon_title": "inferred title",
  "text": "primary scripture reference",
  "overall_grade": "A/B/C — where B+ means hitting benchmarks at or above current averages, A means meaningfully exceeding them, C means below current averages",
  "summary": "2-3 sentences — the coach's overall read on this sermon relative to the growth areas",
  "benchmark_scores": [
    {
      "benchmark": "benchmark label",
      "score": "A/B/C with +/- modifiers",
      "assessment": "3-5 sentences. Data-grounded, specific to THIS sermon. Count the actual instances. Compare to the pastor's averages.",
      "moments_found": ["direct quotes or specific descriptions of moments where the benchmark was hit"],
      "missed_opportunities": ["specific places in the sermon where the benchmark could have been hit harder — name the section, the doctrine, the moment"]
    }
  ],
  "strongest_moment": "the single best moment in the sermon relative to growth areas — quote it directly",
  "one_thing_to_change": "the single most impactful edit before Sunday — concrete, specific, actionable. Name the section, what to add or change, and why it matters for the benchmarks."
}

Voice rules:
- You are a wise homiletics coach who has studied ${firstName}'s tape carefully
- Affirm before correcting — name what's working before naming gaps
- Data-first: ground every claim in something countable from the sermon
- Em-dashes for breath, not parentheses
- Theologically literate — you know the Reformed tradition
- Use ${firstName}'s first name
- This is a mentor who respects the pastor enough to name real gaps
- Return ONLY valid JSON, no markdown fences`;

    // ── Call Claude API ──
    const anthropicKey = Deno.env.get("ANTHROPIC_API_KEY");
    if (!anthropicKey) {
      return new Response(
        JSON.stringify({ error: "ANTHROPIC_API_KEY not configured" }),
        { status: 500, headers: { ...corsHeaders, "Content-Type": "application/json" } }
      );
    }

    const claudeRes = await fetch("https://api.anthropic.com/v1/messages", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "x-api-key": anthropicKey,
        "anthropic-version": "2023-06-01",
      },
      body: JSON.stringify({
        model: "claude-sonnet-4-5-20250929",
        max_tokens: 4000,
        temperature: 0.5,
        messages: [{ role: "user", content: prompt }],
      }),
    });

    if (!claudeRes.ok) {
      const errText = await claudeRes.text();
      console.error("Claude API error:", errText);
      return new Response(
        JSON.stringify({ error: "Claude API error: " + claudeRes.status }),
        { status: 502, headers: { ...corsHeaders, "Content-Type": "application/json" } }
      );
    }

    const claudeData = await claudeRes.json();
    let raw = claudeData.content[0].text.trim();

    // Strip markdown fences if present
    if (raw.startsWith("```")) {
      const lines = raw.split("\n");
      raw = lines.filter((l: string) => !l.trim().startsWith("```")).join("\n");
    }

    const result = JSON.parse(raw);

    return new Response(JSON.stringify(result), {
      headers: { ...corsHeaders, "Content-Type": "application/json" },
    });
  } catch (err) {
    console.error("preflight-check error:", err);
    return new Response(
      JSON.stringify({ error: "Internal server error: " + (err as Error).message }),
      { status: 500, headers: { ...corsHeaders, "Content-Type": "application/json" } }
    );
  }
});
