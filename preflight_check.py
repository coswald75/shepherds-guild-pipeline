"""
Shepherd's Guild — Sermon Pre-Flight Check v0.1 (Experiment)
============================================================
Analyzes a sermon draft against a pastor's coaching benchmarks
before it's preached.

Usage:
  python3 preflight_check.py --preacher "Chris Oswald" --sermon sermon_draft.txt
"""

import os
import sys
import json
import argparse
from pathlib import Path

try:
    import anthropic
    from supabase import create_client
    from dotenv import load_dotenv
except ImportError as e:
    print(f"Missing dependency: {e}")
    sys.exit(1)

load_dotenv(Path(__file__).parent / ".env", override=True)


def run_preflight(preacher_name: str, sermon_text: str):
    # Get coaching benchmarks from Supabase
    sb = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY"))

    # Resolve preacher
    preacher = sb.table("preachers").select("id,name").ilike("name", f"%{preacher_name}%").execute()
    if not preacher.data:
        print(f"No preacher found matching '{preacher_name}'")
        sys.exit(1)
    preacher_id = preacher.data[0]["id"]
    name = preacher.data[0]["name"]
    first_name = name.split()[0]

    # Get analysis
    analysis = sb.table("preacher_analysis").select(
        "growth_areas,growth_intro,hall_distinction,exemplar_matches,stats"
    ).eq("preacher_id", preacher_id).single().execute()

    if not analysis.data:
        print(f"No analysis found for {name}. Run generate_analysis.py first.")
        sys.exit(1)

    data = analysis.data
    stats = data.get("stats", {})
    growth_areas = data.get("growth_areas", [])
    hall = data.get("hall_distinction", {})
    exemplars = data.get("exemplar_matches", [])

    # Build benchmark summary
    benchmarks_text = ""
    for i, ga in enumerate(growth_areas):
        benchmarks_text += f"""
### Benchmark {i+1}: {ga.get('label', 'Unknown')} (Current: {ga.get('metric_current', '?')}, Target: {ga.get('metric_target', '?')})
Title: {ga.get('title_html', '')}
Diagnosis: {ga.get('diagnosis', '')}
Recommendation: {ga.get('recommendation', '')}
"""

    exemplar_text = ""
    for ex in exemplars:
        exemplar_text += f"- {ex['rank']}: {ex['preacher_name']} ({ex['match_pct']}%) — {', '.join(ex.get('reasons', []))}\n"

    prompt = f"""You are a homiletics coach for The Shepherd's Guild. You are analyzing a sermon BEFORE it is preached, against the pastor's established coaching benchmarks.

## Pastor Profile: {name}
- Hall Distinction: {hall.get('label', 'Unknown')} — {hall.get('text', '')}
- Key stat: {hall.get('stat_n', '')} {hall.get('stat_label', '')}
- Corpus: {stats.get('sermon_count', '?')} sermons, {stats.get('total_units', '?')} units
- Illustration density: {stats.get('illustration_density', '?')} per sermon
- Application per sermon: {stats.get('application_per_sermon', '?')}

## Exemplar Matches
{exemplar_text}

## {first_name}'s Coaching Benchmarks (Growth Areas)
{benchmarks_text}

## THE SERMON TO ANALYZE

{sermon_text}

## YOUR TASK

Analyze this sermon against {first_name}'s coaching benchmarks. For each benchmark, evaluate how well THIS specific sermon performs relative to the growth area. Be specific — cite actual lines and moments from the sermon.

Return JSON with this structure:

{{
  "sermon_title": "inferred title",
  "text": "primary scripture reference",
  "overall_grade": "A/B/C — where B+ means hitting benchmarks at or above current averages, A means meaningfully exceeding them, C means below current averages",
  "summary": "2-3 sentences — the coach's overall read on this sermon relative to the growth areas",
  "benchmark_scores": [
    {{
      "benchmark": "benchmark label",
      "score": "A/B/C with +/- modifiers",
      "assessment": "3-5 sentences. Data-grounded, specific to THIS sermon. Count the actual instances. Compare to the pastor's averages.",
      "moments_found": ["direct quotes or specific descriptions of moments where the benchmark was hit"],
      "missed_opportunities": ["specific places in the sermon where the benchmark could have been hit harder — name the section, the doctrine, the moment"]
    }}
  ],
  "strongest_moment": "the single best moment in the sermon relative to growth areas — quote it directly",
  "one_thing_to_change": "the single most impactful edit before Sunday — concrete, specific, actionable. Name the section, what to add or change, and why it matters for the benchmarks."
}}

Voice rules:
- You are a wise homiletics coach who has studied {first_name}'s tape carefully
- Affirm before correcting — name what's working before naming gaps
- Data-first: ground every claim in something countable from the sermon
- Em-dashes for breath, not parentheses
- Theologically literate — you know the Reformed tradition
- Use {first_name}'s first name
- This is a mentor who respects the pastor enough to name real gaps
- Return ONLY valid JSON, no markdown fences"""

    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

    print(f"\n{'='*60}")
    print(f"PRE-FLIGHT CHECK — {name}")
    print(f"{'='*60}\n")
    print("Analyzing sermon against coaching benchmarks...\n")

    response = client.messages.create(
        model="claude-sonnet-4-5-20250929",
        max_tokens=4000,
        temperature=0.5,
        messages=[{"role": "user", "content": prompt}]
    )

    raw = response.content[0].text.strip()
    if raw.startswith("```"):
        lines = raw.split("\n")
        lines = [l for l in lines if not l.strip().startswith("```")]
        raw = "\n".join(lines)

    try:
        result = json.loads(raw)
        print(json.dumps(result, indent=2, ensure_ascii=False))

        # Save to output
        out_path = Path(__file__).parent / "output" / f"preflight_{first_name}_{Path(args.sermon).stem}.json"
        with open(out_path, "w") as f:
            json.dump(result, f, indent=2, ensure_ascii=False)
        print(f"\nSaved to {out_path}")

    except json.JSONDecodeError:
        print("Raw response (not valid JSON):")
        print(raw)

    print(f"\n({response.usage.input_tokens} input / {response.usage.output_tokens} output tokens)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Sermon Pre-Flight Check")
    parser.add_argument("--preacher", required=True, help="Preacher name")
    parser.add_argument("--sermon", required=True, help="Path to sermon text file")
    args = parser.parse_args()

    sermon_path = Path(args.sermon)
    if not sermon_path.exists():
        print(f"File not found: {sermon_path}")
        sys.exit(1)

    sermon_text = sermon_path.read_text(encoding="utf-8")
    run_preflight(args.preacher, sermon_text)
