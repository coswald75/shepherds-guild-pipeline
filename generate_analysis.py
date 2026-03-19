"""
Shepherd's Guild — Preacher Analysis Generator v1.0
====================================================

Generates the Analysis layer for a preacher's dashboard:
  1. AGGREGATE  — Query Supabase for raw stats from decomposed units
  2. COMPARE    — Rank against Guild Hall exemplar preachers
  3. GENERATE   — Claude API produces prose sections in the house style
  4. STORE      — Upsert results into preacher_analysis table

Usage:
  # Generate analysis for a specific preacher
  python generate_analysis.py --preacher "Chris Oswald"

  # Generate by preacher UUID
  python generate_analysis.py --preacher-id 9c6f8d69-de55-45db-ac60-0fe6d0cfff59

  # Dry run — print stats + prose to stdout, don't write to Supabase
  python generate_analysis.py --preacher "Chris Oswald" --dry-run

  # Regenerate analysis for ALL customer preachers
  python generate_analysis.py --all

Environment variables (set in .env or export):
  ANTHROPIC_API_KEY   — Your Anthropic API key
  SUPABASE_URL        — Your Supabase project URL
  SUPABASE_KEY        — Your Supabase service role key
"""

import os
import sys
import json
import math
import argparse
import logging
from datetime import datetime
from typing import Optional

try:
    import anthropic
    from supabase import create_client, Client
    from dotenv import load_dotenv
except ImportError as e:
    print(f"Missing dependency: {e}")
    print("Install with: pip install anthropic supabase python-dotenv")
    sys.exit(1)

load_dotenv(override=True)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
ANTHROPIC_MODEL = "claude-sonnet-4-5-20250929"
SPEC_VERSION = "1.0"

# Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S"
)
log = logging.getLogger("analysis")

# ---------------------------------------------------------------------------
# Clients (lazy)
# ---------------------------------------------------------------------------
_anthropic_client = None
_supabase_client = None


def get_anthropic() -> anthropic.Anthropic:
    global _anthropic_client
    if _anthropic_client is None:
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            raise EnvironmentError("ANTHROPIC_API_KEY not set")
        _anthropic_client = anthropic.Anthropic(api_key=api_key)
    return _anthropic_client


def get_supabase() -> Client:
    global _supabase_client
    if _supabase_client is None:
        url = os.getenv("SUPABASE_URL")
        key = os.getenv("SUPABASE_KEY")
        if not url or not key:
            raise EnvironmentError("SUPABASE_URL and SUPABASE_KEY must be set")
        _supabase_client = create_client(url, key)
    return _supabase_client


# ═══════════════════════════════════════════════════════════════════════════
# STEP 1: STATS AGGREGATION
# ═══════════════════════════════════════════════════════════════════════════

def aggregate_stats(preacher_id: str) -> dict:
    """
    Query Supabase for all decomposed data and compute dashboard stats.
    Returns a flat dict of everything needed for comparison + prose generation.
    """
    sb = get_supabase()
    log.info(f"Aggregating stats for preacher {preacher_id}...")

    # ── Get preacher info ──
    preacher = sb.table("preachers").select("*").eq("id", preacher_id).single().execute()
    preacher_data = preacher.data
    preacher_name = preacher_data["name"]
    church_id = preacher_data.get("church_id")
    church_name = None
    if church_id:
        church = sb.table("churches").select("name").eq("id", church_id).single().execute()
        church_name = church.data["name"]

    log.info(f"  Preacher: {preacher_name}")

    # ── Get all sermons ──
    sermons_resp = sb.table("sermons").select("*").eq("preacher_id", preacher_id).order("date", desc=True).execute()
    sermons = sermons_resp.data
    sermon_count = len(sermons)
    log.info(f"  Sermons: {sermon_count}")

    if sermon_count == 0:
        log.warning("  No sermons found — cannot generate analysis")
        return None

    sermon_ids = [s["id"] for s in sermons]

    # ── Get all units ──
    # Supabase has a URL length limit, so batch if needed
    all_units = []
    batch_size = 20  # sermon IDs per batch
    for i in range(0, len(sermon_ids), batch_size):
        batch_ids = sermon_ids[i:i + batch_size]
        ids_str = ",".join(batch_ids)
        resp = sb.table("units").select(
            "id,sermon_id,unit_index,rhetorical_function,summary,key_claim,"
            "illustration_type,application_specificity,rhetorical_register,"
            "doctrinal_loci,content"
        ).in_("sermon_id", batch_ids).execute()
        all_units.extend(resp.data)

    total_units = len(all_units)
    log.info(f"  Units: {total_units}")

    # ── Theological Fingerprint (doctrinal_loci counts) ──
    loci_counts = {}
    for u in all_units:
        for locus in (u.get("doctrinal_loci") or []):
            loci_counts[locus] = loci_counts.get(locus, 0) + 1
    # Sort by count descending
    theological_fingerprint = dict(sorted(loci_counts.items(), key=lambda x: -x[1]))

    # ── Rhetorical Register distribution ──
    register_counts = {}
    for u in all_units:
        for reg in (u.get("rhetorical_register") or []):
            register_counts[reg] = register_counts.get(reg, 0) + 1
    # Convert to percentages
    rhetorical_register = {}
    if total_units > 0:
        for reg, count in register_counts.items():
            rhetorical_register[reg] = round(100 * count / total_units)
    rhetorical_register = dict(sorted(rhetorical_register.items(), key=lambda x: -x[1]))

    # ── Homiletical Method (rhetorical_function counts) ──
    function_counts = {}
    for u in all_units:
        fn = u.get("rhetorical_function")
        if fn:
            function_counts[fn] = function_counts.get(fn, 0) + 1
    homiletical_method = dict(sorted(function_counts.items(), key=lambda x: -x[1]))

    # ── Sermon type breakdown ──
    type_counts = {}
    for s in sermons:
        st = s.get("sermon_type")
        if st:
            type_counts[st] = type_counts.get(st, 0) + 1
    expository_pct = round(100 * type_counts.get("expository", 0) / sermon_count) if sermon_count else 0

    # ── Illustration stats ──
    illus_units = [u for u in all_units if u["rhetorical_function"] == "illustration"]
    illus_count = len(illus_units)
    illus_density = round(illus_count / sermon_count, 1) if sermon_count else 0

    illus_types = {}
    for u in illus_units:
        it = u.get("illustration_type") or "unclassified"
        illus_types[it] = illus_types.get(it, 0) + 1
    illus_types = dict(sorted(illus_types.items(), key=lambda x: -x[1]))

    # ── Application stats ──
    app_units = [u for u in all_units if u["rhetorical_function"] == "application"]
    app_count = len(app_units)
    app_per_sermon = round(app_count / sermon_count, 1) if sermon_count else 0

    app_specificity = {}
    for u in app_units:
        spec = u.get("application_specificity") or "unclassified"
        app_specificity[spec] = app_specificity.get(spec, 0) + 1

    # ── Quotations ──
    all_quotations = []
    for i in range(0, len(sermon_ids), batch_size):
        batch_ids = sermon_ids[i:i + batch_size]
        # Get unit IDs for these sermons
        unit_ids_resp = sb.table("units").select("id").in_("sermon_id", batch_ids).execute()
        unit_ids = [u["id"] for u in unit_ids_resp.data]
        if unit_ids:
            for j in range(0, len(unit_ids), 50):
                uid_batch = unit_ids[j:j + 50]
                q_resp = sb.table("quotations").select("text,attribution,source,function").in_("unit_id", uid_batch).execute()
                all_quotations.extend(q_resp.data)

    quotation_count = len(all_quotations)

    # Top quoted authors
    author_counts = {}
    for q in all_quotations:
        author = q.get("attribution", "Unknown")
        author_counts[author] = author_counts.get(author, 0) + 1
    top_quoted_authors = sorted(
        [{"author": a, "count": c} for a, c in author_counts.items()],
        key=lambda x: -x["count"]
    )

    # ── Series analysis (for latent book detection) ──
    series_map = {}
    for s in sermons:
        sn = s.get("series_name")
        if sn:
            if sn not in series_map:
                series_map[sn] = []
            series_map[sn].append(s)
    series_info = [
        {"name": name, "sermon_count": len(slist), "sermons": [s["title"] for s in slist]}
        for name, slist in sorted(series_map.items(), key=lambda x: -len(x[1]))
    ]

    # ── Build the stats object ──
    stats = {
        "preacher_name": preacher_name,
        "church_name": church_name,
        "sermon_count": sermon_count,
        "total_units": total_units,
        "expository_pct": expository_pct,
        "theological_fingerprint": theological_fingerprint,
        "rhetorical_register": rhetorical_register,
        "homiletical_method": homiletical_method,
        "illustration_count": illus_count,
        "illustration_density": illus_density,
        "illustration_types": illus_types,
        "application_count": app_count,
        "application_per_sermon": app_per_sermon,
        "application_specificity": app_specificity,
        "quotation_count": quotation_count,
        "top_quoted_authors": top_quoted_authors[:15],
        "series_info": series_info,
    }

    log.info(f"  Stats aggregated: {sermon_count} sermons, {total_units} units, {illus_count} illustrations, {quotation_count} quotations")
    return stats


# ═══════════════════════════════════════════════════════════════════════════
# STEP 2: EXEMPLAR COMPARISON
# ═══════════════════════════════════════════════════════════════════════════

def get_hall_stats(exclude_preacher_id: str = None) -> list:
    """
    Fetch aggregated stats for all canonical (Guild Hall) preachers.
    Returns a list of stats dicts in the same shape as aggregate_stats().
    """
    sb = get_supabase()
    log.info("Fetching Hall preacher stats...")

    # Get canonical preachers
    preachers_resp = sb.table("preachers").select("id,name").eq("is_canonical", True).execute()
    hall_preachers = preachers_resp.data

    if exclude_preacher_id:
        hall_preachers = [p for p in hall_preachers if p["id"] != exclude_preacher_id]

    log.info(f"  Found {len(hall_preachers)} Hall preachers")

    hall_stats = []
    for hp in hall_preachers:
        try:
            stats = aggregate_stats(hp["id"])
            if stats and stats["sermon_count"] > 0:
                stats["preacher_id"] = hp["id"]
                hall_stats.append(stats)
                log.info(f"  ✓ {hp['name']}: {stats['sermon_count']} sermons, {stats['total_units']} units")
        except Exception as e:
            log.warning(f"  ✗ {hp['name']}: {e}")

    return hall_stats


def compute_similarity(pastor_stats: dict, hall_stats: dict) -> dict:
    """
    Compute a similarity score between a pastor and a Hall preacher.
    Uses a weighted comparison across multiple dimensions.
    Returns {"score": 0-100, "reasons": [...], "deltas": {...}}
    """
    reasons = []
    scores = []

    # ── Rhetorical register similarity ──
    pastor_reg = pastor_stats.get("rhetorical_register", {})
    hall_reg = hall_stats.get("rhetorical_register", {})
    all_regs = set(list(pastor_reg.keys()) + list(hall_reg.keys()))
    if all_regs:
        reg_diff = sum(abs(pastor_reg.get(r, 0) - hall_reg.get(r, 0)) for r in all_regs)
        reg_score = max(0, 100 - reg_diff)
        scores.append(("register", reg_score, 0.25))

        # Find the dominant register for both
        pastor_dom = max(pastor_reg, key=pastor_reg.get) if pastor_reg else None
        hall_dom = max(hall_reg, key=hall_reg.get) if hall_reg else None
        if pastor_dom and hall_dom and pastor_dom == hall_dom:
            reasons.append(f"{pastor_dom.capitalize()}-dominant register")

    # ── Theological fingerprint similarity ──
    pastor_fp = pastor_stats.get("theological_fingerprint", {})
    hall_fp = hall_stats.get("theological_fingerprint", {})
    all_loci = set(list(pastor_fp.keys()) + list(hall_fp.keys()))
    if all_loci:
        # Normalize to percentages
        pastor_total = sum(pastor_fp.values()) or 1
        hall_total = sum(hall_fp.values()) or 1
        fp_diff = sum(
            abs(pastor_fp.get(l, 0) / pastor_total - hall_fp.get(l, 0) / hall_total)
            for l in all_loci
        )
        fp_score = max(0, 100 - fp_diff * 100)
        scores.append(("fingerprint", fp_score, 0.25))

        # Find shared top loci
        pastor_top = sorted(pastor_fp.items(), key=lambda x: -x[1])[:3]
        hall_top = sorted(hall_fp.items(), key=lambda x: -x[1])[:3]
        pastor_top_names = {l[0] for l in pastor_top}
        hall_top_names = {l[0] for l in hall_top}
        shared_top = pastor_top_names & hall_top_names
        for locus in shared_top:
            reasons.append(f"{locus} as organizing center")

    # ── Illustration profile similarity ──
    pastor_id_val = pastor_stats.get("illustration_density", 0)
    hall_id_val = hall_stats.get("illustration_density", 0)
    if hall_id_val > 0:
        id_diff = abs(pastor_id_val - hall_id_val) / max(hall_id_val, 1)
        id_score = max(0, 100 - id_diff * 100)
        scores.append(("illustration", id_score, 0.15))

        # Compare illustration types
        pastor_it = pastor_stats.get("illustration_types", {})
        hall_it = hall_stats.get("illustration_types", {})
        pastor_illus_total = sum(pastor_it.values()) or 1
        hall_illus_total = sum(hall_it.values()) or 1
        for itype in ["cultural_reference", "personal_story", "historical_example"]:
            p_pct = pastor_it.get(itype, 0) / pastor_illus_total
            h_pct = hall_it.get(itype, 0) / hall_illus_total
            if p_pct > 0.15 and h_pct > 0.15 and abs(p_pct - h_pct) < 0.15:
                label = itype.replace("_", " ").title()
                reasons.append(f"{label.replace('_', ' ')} density")

    # ── Homiletical method similarity ──
    pastor_hm = pastor_stats.get("homiletical_method", {})
    hall_hm = hall_stats.get("homiletical_method", {})
    if pastor_hm and hall_hm:
        pastor_hm_total = sum(pastor_hm.values()) or 1
        hall_hm_total = sum(hall_hm.values()) or 1
        hm_diff = sum(
            abs(pastor_hm.get(f, 0) / pastor_hm_total - hall_hm.get(f, 0) / hall_hm_total)
            for f in set(list(pastor_hm.keys()) + list(hall_hm.keys()))
        )
        hm_score = max(0, 100 - hm_diff * 100)
        scores.append(("method", hm_score, 0.2))

        # Check for shared dominant method
        pastor_dom_method = max(pastor_hm, key=pastor_hm.get)
        hall_dom_method = max(hall_hm, key=hall_hm.get)
        if pastor_dom_method == hall_dom_method:
            reasons.append(f"Canonical hermeneutical method")

    # ── Expository rate comparison ──
    pastor_exp = pastor_stats.get("expository_pct", 0)
    hall_exp = hall_stats.get("expository_pct", 0)
    if pastor_exp > 0 and hall_exp > 0:
        exp_diff = abs(pastor_exp - hall_exp)
        exp_score = max(0, 100 - exp_diff * 2)
        scores.append(("expository", exp_score, 0.15))
        if exp_diff < 10 and pastor_exp > 70:
            reasons.append(f"Exposition rate ({pastor_exp}% vs {hall_exp}%)")

    # ── Weighted average ──
    if scores:
        total_weight = sum(s[2] for s in scores)
        weighted = sum(s[1] * s[2] for s in scores) / total_weight if total_weight else 0
        final_score = round(weighted)
    else:
        final_score = 0

    # ── Compute deltas for growth area detection ──
    deltas = {
        "illustration_density": {
            "pastor": pastor_id_val,
            "hall": hall_id_val,
        },
        "application_per_sermon": {
            "pastor": pastor_stats.get("application_per_sermon", 0),
            "hall": hall_stats.get("application_per_sermon", 0),
        },
        "pathos_register": {
            "pastor": pastor_reg.get("pathos", 0),
            "hall": hall_reg.get("pathos", 0),
        },
        "logos_register": {
            "pastor": pastor_reg.get("logos", 0),
            "hall": hall_reg.get("logos", 0),
        },
    }

    return {
        "score": final_score,
        "reasons": reasons[:5],  # Cap at 5 most relevant
        "deltas": deltas,
    }


def rank_exemplars(pastor_stats: dict, hall_stats_list: list) -> list:
    """
    Compare pastor against all Hall preachers, return ranked matches.
    """
    log.info("Computing exemplar similarities...")
    matches = []
    for hs in hall_stats_list:
        sim = compute_similarity(pastor_stats, hs)
        matches.append({
            "preacher_name": hs["preacher_name"],
            "preacher_id": hs.get("preacher_id"),
            "match_pct": sim["score"],
            "reasons": sim["reasons"],
            "deltas": sim["deltas"],
            "stats": {
                "illustration_density": hs.get("illustration_density", 0),
                "application_per_sermon": hs.get("application_per_sermon", 0),
                "rhetorical_register": hs.get("rhetorical_register", {}),
                "sermon_count": hs.get("sermon_count", 0),
            }
        })

    matches.sort(key=lambda x: -x["match_pct"])

    # Assign ranks
    rank_labels = ["Primary Match", "Secondary Match", "Tertiary Match"]
    for i, m in enumerate(matches[:3]):
        m["rank"] = rank_labels[i] if i < len(rank_labels) else f"Match #{i+1}"
        log.info(f"  {m['rank']}: {m['preacher_name']} ({m['match_pct']}%)")

    return matches[:3]


# ═══════════════════════════════════════════════════════════════════════════
# STEP 3: PROSE GENERATION (Claude API)
# ═══════════════════════════════════════════════════════════════════════════

# The style guide is extracted from Chris Oswald's hand-written analysis.
# This IS the product voice. Every future pastor's analysis must match it.
STYLE_GUIDE = """
## Shepherd's Guild Analysis Prose — Style Guide

You are writing analysis sections for a preacher's personal dashboard on The Shepherd's Guild.
The audience is the pastor himself. He is seeing his own sermon data reflected back with insight.

### Voice
- You are a wise, experienced homiletics coach who has studied this pastor's tape carefully.
- You are NOT a report generator or data analyst.
- The tone is affirming but honest — a mentor who respects the pastor enough to name real gaps.
- You write with theological literacy. You know the Reformed tradition. You know preaching.

### Prose Rules
1. DATA FIRST, THEN INTERPRETATION. Never just vibes. Always ground in a number, then explain what it means.
   Good: "At 3.1 illustrations per sermon, Chris's density is solid — but meaningfully below Keller's 4.8"
   Bad: "Chris could use more illustrations in his sermons."

2. AFFIRM BEFORE CORRECTING. Growth areas never say "you're bad at this."
   Good: "Chris's Logos dominance (79%) is a strength and should be protected — but the Pathos register (22%) sits below..."
   Bad: "Chris lacks emotional depth in his preaching."

3. CONCRETE RECOMMENDATIONS WITH THEOLOGICAL ANCHORING. Not generic advice.
   Good: "Identify one moment per sermon to set down the argument and speak directly to the listener's experience — not to manipulate, but to acknowledge the weight of what the text is actually asking."
   Bad: "Try to be more emotional in your preaching."

4. USE EM-DASHES FOR BREATH, not parentheses. The prose breathes through em-dashes.
   Good: "The gap isn't random: Keller's extra illustrations are almost entirely cultural reference, not personal story."

5. ITALICIZED EMPHASIS on key words in titles (rendered as <em> tags).
   Good: "Room to illustrate <em>more.</em>"
   Good: "Application is present, but <em>often general.</em>"

6. SPECIFIC COMPARISONS ARE NAMED AND REASONED. Don't just say "74% match" — explain WHY.
   Good: "Christology as organizing center, Cultural illustration density, Canonical hermeneutical method"

7. THE DOCTRINE EARNS THE EMOTION. When discussing pathos or emotional register, always frame it theologically.
   Good: "This is where Lloyd-Jones's 'do you know this?' register lives. The doctrine earns the emotion; the emotion shouldn't be skipped."

8. SHORT, PUNCHY SENTENCES mixed with longer analytical ones. Vary rhythm.

9. USE THE PASTOR'S FIRST NAME (not last name, not "the pastor").

10. NUMBERS USE REAL DATA from the stats provided. Never invent statistics.
"""

FEW_SHOT_EXAMPLES = """
## Examples of Correct Output (from a real analysis)

### Hall Distinction Example:
{
  "label": "Logos-dominant",
  "text": "Nearly 8 in 10 units operate in the register of argument and exposition. Chris preaches to the mind, trusting the heart will follow the intellect illuminated by the Spirit.",
  "stat_n": "79%",
  "stat_label": "Logos register\\nacross all units"
}

### Growth Intro Example:
{
  "label": "What This Means For Your Development",
  "text": "The Keller\\u2013Carson axis is a distinctive combination \\u2014 <em>cultural fluency married to canonical rigor.</em> Keller\\u2019s weakness (fewer systematic loci, lighter on Soteriology) is where Carson is strongest. Chris\\u2019s corpus already reflects both instincts. The gaps below represent specific, measurable opportunities to grow without losing what makes the voice distinctive."
}

### Growth Area Example:
{
  "number": "01",
  "label": "Illustration Density",
  "title_html": "Room to illustrate <em>more.</em>",
  "diagnosis": "At 3.1 illustrations per sermon, Chris\\u2019s density is solid \\u2014 but meaningfully below Keller\\u2019s 4.8 and the Hall average of 4.2. The gap isn\\u2019t random: Keller\\u2019s extra illustrations are almost entirely cultural reference, not personal story. Chris already uses cultural reference well (22% of his arsenal). The opportunity is to pull more of them per sermon, not change types.",
  "metric_current": "3.1",
  "metric_current_label": "Chris",
  "metric_target": "4.8",
  "metric_target_label": "Keller",
  "metric_caption": "Illus. per sermon\\nHall avg: 4.2",
  "recommendation": "In each sermon\\u2019s prep, identify <strong>one additional cultural moment</strong> \\u2014 a film scene, current event, or broadly shared experience \\u2014 that refracts the doctrinal claim. Don\\u2019t add illustrations for their own sake; look for the one that makes the abstract concrete at the moment of highest doctrinal density."
}

### Latent Book Example:
{
  "confidence": "High",
  "title": "The Psalms of the Broken:",
  "subtitle": "Suffering, Lament, and the God Who Stays",
  "body": "Across your Psalms series alone, you have preached 13 sermons on themes of affliction, divine nearness in suffering, and what it means to keep praying when the silence feels absolute. The material is not scattered \\u2014 it follows a discernible arc: the reality of suffering is named, the instinct to suppress lament is challenged, and the Psalms are read as permission to bring full weight to prayer. That arc is a book. You have most of chapter one through eight written already. What\\u2019s missing is an introduction and a pastoral closing \\u2014 perhaps 15,000 words of original material around an existing 40,000-word skeleton.",
  "evidence_signals": [
    {"label": "Thematic concentration in corpus", "pct": 81},
    {"label": "Sustained argument across series", "pct": 74},
    {"label": "Illustration density on topic", "pct": 68},
    {"label": "Personal narrative investment", "pct": 55}
  ],
  "evidence_cards": [
    {
      "type": "Doctrinal Spine",
      "text": "The corpus records 298 Christology units and 238 Soteriology units \\u2014 but within the Psalms sermons specifically, the dominant movement is union with Christ as the theological explanation for why lament is not faithlessness.",
      "source": "Source: 13 Psalms sermons \\u00b7 187 units analyzed"
    }
  ],
  "secondary": {
    "confidence": "Moderate",
    "title_html": "A theology of <em>sanctification in the ordinary.</em>",
    "diagnosis": "Your Ephesians and 1 John sermons share a recurring preoccupation...",
    "metric_current": "13",
    "metric_current_label": "Sermons",
    "metric_target": "8",
    "metric_target_label": "Sermons",
    "metric_caption": "Ephesians + 1 John\\ncombined series",
    "next_step": "Your corpus would need a <strong>focused sermon or two on vocation and daily obedience</strong> to complete the arc."
  }
}
"""


def generate_prose(pastor_stats: dict, exemplar_matches: list, hall_averages: dict) -> dict:
    """
    Call Claude API to generate all prose sections for the dashboard.
    Returns a dict with: hall_distinction, growth_intro, growth_areas, latent_book
    """
    client = get_anthropic()
    preacher_name = pastor_stats["preacher_name"]
    first_name = preacher_name.split()[0]

    log.info(f"Generating prose for {preacher_name}...")

    prompt = f"""You are generating analysis prose for {preacher_name}'s Shepherd's Guild dashboard.

{STYLE_GUIDE}

{FEW_SHOT_EXAMPLES}

## Data for {preacher_name}

### Raw Stats
```json
{json.dumps(pastor_stats, indent=2)}
```

### Exemplar Matches (top 3 Hall preachers by similarity)
```json
{json.dumps(exemplar_matches, indent=2)}
```

### Hall Averages (for comparison baselines)
```json
{json.dumps(hall_averages, indent=2)}
```

## Your Task

Generate a JSON object with these sections. Use {first_name}'s REAL data — never invent numbers.
Every statistic must come from the data above.

Return ONLY valid JSON (no markdown code fences), with this exact structure:

{{
  "hall_distinction": {{
    "label": "<2-3 word label based on dominant register or defining trait>",
    "text": "<1-2 sentences — what makes this preacher's voice distinctive, grounded in data>",
    "stat_n": "<the key percentage or number>",
    "stat_label": "<what the stat measures, can use \\n for line break>"
  }},
  "growth_intro": {{
    "label": "What This Means For Your Development",
    "text": "<2-3 sentences framing the top exemplar matches and what the growth gaps mean. Use <em> for emphasis.>"
  }},
  "growth_areas": [
    {{
      "number": "01",
      "label": "<area name>",
      "title_html": "<short title with <em> on key word>",
      "diagnosis": "<3-5 sentences. Data-first, specific, affirming-then-honest. Reference specific numbers from the stats and comparisons.>",
      "metric_current": "<pastor's number>",
      "metric_current_label": "<short label>",
      "metric_target": "<exemplar's number or direction arrow>",
      "metric_target_label": "<exemplar name or 'Specificity' etc>",
      "metric_caption": "<context line, use \\n for line breaks>",
      "recommendation": "<2-3 sentences. Concrete, actionable, theologically grounded. Use <strong> for the key action.>"
    }},
    // Generate exactly 3 growth areas based on the largest gaps in the data
  ],
  "latent_book": {{
    "confidence": "High or Moderate",
    "title": "<evocative book title based on dominant themes>",
    "subtitle": "<subtitle>",
    "body": "<5-7 sentences. Identify the strongest thematic thread across their series. Name specific series, sermon counts, thematic arcs. Frame as a book that already exists in skeleton form.>",
    "evidence_signals": [
      {{"label": "<signal name>", "pct": <50-95>}},
      // 4 signals
    ],
    "evidence_cards": [
      {{
        "type": "Doctrinal Spine",
        "text": "<what theological framework runs through the material>",
        "source": "Source: <specific data reference>"
      }},
      {{
        "type": "Rhetorical Signature",
        "text": "<what makes this pastor's treatment of the topic distinctive>",
        "source": "Source: <specific data reference>"
      }},
      {{
        "type": "Exemplar Parallel",
        "text": "<closest published work in the tradition and how this pastor's voice differs>",
        "source": "Source: <specific data reference>"
      }},
      {{
        "type": "Market Gap",
        "text": "<what's missing in the published landscape that this material could fill>",
        "source": "Source: algorithmic gap analysis \\u00b7 Guild Hall comparable titles"
      }}
    ],
    "secondary": {{
      "confidence": "Moderate",
      "title_html": "<second book candidate with <em>>",
      "diagnosis": "<3-5 sentences on the secondary thematic thread>",
      "metric_current": "<number>",
      "metric_current_label": "<label>",
      "metric_target": "<number>",
      "metric_target_label": "<label>",
      "metric_caption": "<context>",
      "next_step": "<1-2 sentences with <strong> for key action>"
    }}
  }}
}}
"""

    log.info("  Calling Claude API...")
    response = client.messages.create(
        model=ANTHROPIC_MODEL,
        max_tokens=8000,
        temperature=0.7,  # Some creativity for prose, but grounded
        messages=[{"role": "user", "content": prompt}]
    )

    raw_text = response.content[0].text.strip()

    # Strip markdown code fences if present
    if raw_text.startswith("```"):
        lines = raw_text.split("\n")
        # Remove first and last lines (fences)
        lines = [l for l in lines if not l.strip().startswith("```")]
        raw_text = "\n".join(lines)

    try:
        prose = json.loads(raw_text)
    except json.JSONDecodeError as e:
        log.warning(f"  JSON parse failed ({e}), attempting repair...")
        # Common fixes: trailing commas, unescaped newlines in strings
        import re
        repaired = raw_text
        # Fix newlines inside JSON string values (replace with \\n)
        repaired = re.sub(r'(?<=": ")((?:[^"\\]|\\.)*)(?=")', lambda m: m.group(0).replace('\n', '\\n'), repaired)
        repaired = re.sub(r'(?<=": ")((?:[^"\\]|\\.)*)(?=")', lambda m: m.group(0).replace('\t', '\\t'), repaired)
        # Remove trailing commas before } or ]
        repaired = re.sub(r',\s*([}\]])', r'\1', repaired)
        try:
            prose = json.loads(repaired)
            log.info("  JSON repair succeeded")
        except json.JSONDecodeError:
            log.error(f"  JSON repair also failed. Raw response (first 500 chars): {raw_text[:500]}")
            debug_path = f"output/analysis_debug_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
            with open(debug_path, "w") as f:
                f.write(raw_text)
            log.error(f"  Full response saved to {debug_path}")
            raise

    log.info(f"  Prose generated successfully ({response.usage.input_tokens} in / {response.usage.output_tokens} out)")
    return prose


def compute_hall_averages(hall_stats_list: list) -> dict:
    """Compute average stats across all Hall preachers for baseline comparisons."""
    if not hall_stats_list:
        return {}

    n = len(hall_stats_list)
    avg = {
        "illustration_density": round(sum(h.get("illustration_density", 0) for h in hall_stats_list) / n, 1),
        "application_per_sermon": round(sum(h.get("application_per_sermon", 0) for h in hall_stats_list) / n, 1),
        "rhetorical_register": {},
        "sermon_count_avg": round(sum(h.get("sermon_count", 0) for h in hall_stats_list) / n),
    }

    # Average rhetorical register
    all_regs = set()
    for h in hall_stats_list:
        all_regs.update(h.get("rhetorical_register", {}).keys())
    for reg in all_regs:
        avg["rhetorical_register"][reg] = round(
            sum(h.get("rhetorical_register", {}).get(reg, 0) for h in hall_stats_list) / n
        )

    return avg


# ═══════════════════════════════════════════════════════════════════════════
# STEP 4: STORE TO SUPABASE
# ═══════════════════════════════════════════════════════════════════════════

def store_analysis(preacher_id: str, stats: dict, exemplar_matches: list,
                   prose: dict, quotes: list):
    """Upsert the complete analysis into preacher_analysis table."""
    sb = get_supabase()
    log.info(f"Storing analysis for {preacher_id}...")

    row = {
        "preacher_id": preacher_id,
        "stats": stats,
        "exemplar_matches": [
            {
                "preacher_name": m["preacher_name"],
                "match_pct": m["match_pct"],
                "rank": m["rank"],
                "reasons": m["reasons"],
            }
            for m in exemplar_matches
        ],
        "hall_distinction": prose.get("hall_distinction", {}),
        "growth_intro": prose.get("growth_intro", {}),
        "growth_areas": prose.get("growth_areas", []),
        "latent_book": prose.get("latent_book", {}),
        "quotes": quotes,
        "generated_at": datetime.utcnow().isoformat(),
        "generation_model": ANTHROPIC_MODEL,
        "generation_version": SPEC_VERSION,
        "updated_at": datetime.utcnow().isoformat(),
    }

    # Upsert (insert or update on preacher_id conflict)
    resp = sb.table("preacher_analysis").upsert(row, on_conflict="preacher_id").execute()
    log.info(f"  ✓ Analysis stored ({len(json.dumps(row))} bytes)")
    return resp


# ═══════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════

def resolve_preacher_id(name: str = None, preacher_id: str = None) -> str:
    """Resolve a preacher name to their UUID."""
    sb = get_supabase()
    if preacher_id:
        return preacher_id
    if name:
        resp = sb.table("preachers").select("id").ilike("name", f"%{name}%").execute()
        if resp.data:
            if len(resp.data) > 1:
                log.warning(f"Multiple matches for '{name}': {[r['id'] for r in resp.data]}. Using first.")
            return resp.data[0]["id"]
        else:
            log.error(f"No preacher found matching '{name}'")
            sys.exit(1)
    log.error("Must provide --preacher or --preacher-id")
    sys.exit(1)


def extract_quotes(preacher_id: str) -> list:
    """Pull all quotations for a preacher's sermons from Supabase."""
    sb = get_supabase()
    log.info("Extracting quotes...")

    # Get sermon IDs
    sermons = sb.table("sermons").select("id").eq("preacher_id", preacher_id).execute()
    sermon_ids = [s["id"] for s in sermons.data]

    if not sermon_ids:
        return []

    # Get all unit IDs (with sermon_id for linking)
    all_quotes = []
    batch_size = 20
    for i in range(0, len(sermon_ids), batch_size):
        batch = sermon_ids[i:i + batch_size]
        units = sb.table("units").select("id,sermon_id").in_("sermon_id", batch).execute()
        # Build unit_id → sermon_id lookup
        unit_sermon_map = {u["id"]: u["sermon_id"] for u in units.data}
        unit_ids = list(unit_sermon_map.keys())
        if unit_ids:
            for j in range(0, len(unit_ids), 50):
                uid_batch = unit_ids[j:j + 50]
                q_resp = sb.table("quotations").select("text,attribution,source,unit_id").in_("unit_id", uid_batch).execute()
                for q in q_resp.data:
                    q["_sermon_id"] = unit_sermon_map.get(q.get("unit_id"), "")
                all_quotes.extend(q_resp.data)

    # Format for dashboard (now includes sermon_id for click-through)
    quotes = [
        {
            "text": q["text"],
            "attr": q["attribution"],
            "source": q.get("source", ""),
            "sermon_id": q.get("_sermon_id", ""),
        }
        for q in all_quotes
        if q.get("text")
    ]

    log.info(f"  Found {len(quotes)} quotes")
    return quotes


def run_analysis(preacher_id: str, dry_run: bool = False):
    """Run the complete analysis pipeline for one preacher."""
    log.info("=" * 60)
    log.info(f"ANALYSIS PIPELINE — {preacher_id}")
    log.info("=" * 60)

    # Step 1: Aggregate pastor stats
    pastor_stats = aggregate_stats(preacher_id)
    if not pastor_stats:
        log.error("Cannot generate analysis — no sermon data")
        return

    # Step 2: Get Hall stats + compare
    hall_stats_list = get_hall_stats(exclude_preacher_id=preacher_id)

    if hall_stats_list:
        exemplar_matches = rank_exemplars(pastor_stats, hall_stats_list)
        hall_averages = compute_hall_averages(hall_stats_list)
    else:
        log.warning("No Hall preachers found — skipping exemplar comparison")
        exemplar_matches = []
        hall_averages = {}

    # Step 3: Generate prose
    prose = generate_prose(pastor_stats, exemplar_matches, hall_averages)

    # Extract quotes
    quotes = extract_quotes(preacher_id)

    if dry_run:
        log.info("DRY RUN — printing results to stdout")
        output = {
            "stats": pastor_stats,
            "exemplar_matches": exemplar_matches,
            "prose": prose,
            "quotes_count": len(quotes),
        }
        print(json.dumps(output, indent=2, ensure_ascii=False))

        # Also save to file
        out_path = f"output/analysis_{pastor_stats['preacher_name'].replace(' ', '_')}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        with open(out_path, "w") as f:
            json.dump(output, f, indent=2, ensure_ascii=False)
        log.info(f"  Saved to {out_path}")
    else:
        # Step 4: Store
        store_analysis(preacher_id, pastor_stats, exemplar_matches, prose, quotes)

    log.info("=" * 60)
    log.info("ANALYSIS COMPLETE")
    log.info("=" * 60)


def main():
    parser = argparse.ArgumentParser(
        description="Generate preacher analysis for the Shepherd's Guild dashboard"
    )
    parser.add_argument("--preacher", help="Preacher name (fuzzy match)")
    parser.add_argument("--preacher-id", help="Preacher UUID")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print results to stdout, don't write to Supabase")
    parser.add_argument("--all", action="store_true",
                        help="Generate analysis for ALL customer (non-canonical) preachers")

    args = parser.parse_args()

    if args.all:
        sb = get_supabase()
        preachers = sb.table("preachers").select("id,name").eq("is_canonical", False).execute()
        log.info(f"Running analysis for {len(preachers.data)} customer preachers...")
        for p in preachers.data:
            try:
                run_analysis(p["id"], dry_run=args.dry_run)
            except Exception as e:
                log.error(f"Failed for {p['name']}: {e}")
    else:
        preacher_id = resolve_preacher_id(args.preacher, args.preacher_id)
        run_analysis(preacher_id, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
