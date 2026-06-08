"""
Sermon-artifact generator (V1 MVP).

One LLM call per (sermon × artifact_type). Writes the result to the
`sermon_artifacts` table. For V1 we run synchronously (one call at a time)
so we can iterate on prompt + voice quickly. Batch submission via the
Anthropic Batch API is V2 once voice is calibrated.

Usage:
  python generate_artifacts.py generate <sermon_id> --type prayer_prompt
  python generate_artifacts.py generate <sermon_id>                # all 6 (later)
  python generate_artifacts.py preview <sermon_id> --type prayer_prompt
      # render + print, do not write

Environment:
  ANTHROPIC_API_KEY, SUPABASE_URL, SUPABASE_KEY (per CLAUDE.md)
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Optional

import anthropic
from dotenv import load_dotenv
from supabase import Client, create_client

load_dotenv(override=True)

REPO_ROOT = Path(__file__).resolve().parent
PROMPTS_DIR = REPO_ROOT / "sermon_artifacts" / "prompts"

# ----------------------------------------------------------------------------
# Config
# ----------------------------------------------------------------------------
ARTIFACT_TYPES = (
    "small_group_questions",
    "daily_readings",
    "prayer_prompt",
    "family_card",
    "couples_guide",
    "memory_verse",
)

# Maps artifact_type → per-artifact prompt file.
PROMPT_FILES = {
    "small_group_questions": "small_group.md",
    "daily_readings": "daily_readings.md",
    "prayer_prompt": "prayer.md",
    "family_card": "family.md",
    "couples_guide": "couples.md",
    "memory_verse": "memory.md",
}

# Default to Haiku 4.5 for cost/speed — voice prompt + small outputs make
# Sonnet overkill. Override via --model if needed.
DEFAULT_MODEL = "claude-haiku-4-5-20251001"
MAX_OUTPUT_TOKENS = 4000

# Per-preacher voice profile mapping. Falls back to PROMPTS_DIR/_voice_sgm.md
# when a preacher isn't listed here (so existing behavior is preserved for the
# Guild Hall canonical preachers and anyone we haven't profiled yet).
VOICE_PROFILES: dict[str, str] = {
    "9c6f8d69-de55-45db-ac60-0fe6d0cfff59": "chris-voice-style-guide.md",  # Chris Oswald · Providence Community
    "ccb9e59c-bd20-414a-bd6b-25b117b8144c": "ricky-voice-style-guide.md",  # Ricky Alcantar · Cross of Grace
}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("generate_artifacts")

_anthropic_client: Optional[anthropic.Anthropic] = None
_supabase_client: Optional[Client] = None


def get_anthropic() -> anthropic.Anthropic:
    global _anthropic_client
    if _anthropic_client is None:
        key = os.getenv("ANTHROPIC_API_KEY")
        if not key:
            raise EnvironmentError("ANTHROPIC_API_KEY not set")
        _anthropic_client = anthropic.Anthropic(api_key=key)
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


# ----------------------------------------------------------------------------
# Sermon-facts block — minimal context for the LLM, no full transcript
# ----------------------------------------------------------------------------

def _build_sermon_facts(sermon_id: str) -> tuple[dict, str]:
    """
    Pull a compact sermon-facts block: sermon-level metadata, top loci,
    anchor key_claims, citation list. Returns (raw_dict, formatted_text).
    The dict includes `preacher_id` so the caller can route voice profile.

    We deliberately exclude full transcripts and per-unit content — keep input
    tokens low and let the voice prompt do the heavy lifting.
    """
    sb = get_supabase()
    sermon = (
        sb.table("sermons")
        .select(
            "id, title, preacher_id, primary_text, date, series_name, main_thesis, "
            "abstract, sermon_type, tone, hermeneutical_method, "
            "preachers(name, churches(name))"
        )
        .eq("id", sermon_id)
        .single()
        .execute()
        .data
    )
    if not sermon:
        raise ValueError(f"sermon not found: {sermon_id}")

    units = (
        sb.table("units")
        .select("unit_index, rhetorical_function, key_claim, doctrinal_loci")
        .eq("sermon_id", sermon_id)
        .order("unit_index")
        .execute()
        .data
        or []
    )

    citations = (
        sb.table("citations")
        .select("tier, reference, units!inner(sermon_id)")
        .eq("units.sermon_id", sermon_id)
        .execute()
        .data
        or []
    )

    # Aggregate loci across units
    loci_counts: dict[str, int] = {}
    for u in units:
        for l in u.get("doctrinal_loci") or []:
            loci_counts[l] = loci_counts.get(l, 0) + 1
    top_loci = sorted(loci_counts.items(), key=lambda x: -x[1])[:5]

    # Anchor units = theological_claims + first 3 applications
    anchor_units = [u for u in units if u.get("rhetorical_function") == "theological_claim" and u.get("key_claim")]
    application_units = [u for u in units if u.get("rhetorical_function") == "application" and u.get("key_claim")][:3]

    # Citations: dedupe + group by tier
    seen_refs: set[str] = set()
    primary_refs: list[str] = []
    cross_refs: list[str] = []
    for c in citations:
        ref = (c.get("reference") or "").strip()
        if not ref or ref in seen_refs:
            continue
        seen_refs.add(ref)
        (primary_refs if c.get("tier") == 1 else cross_refs).append(ref)

    preacher = sermon.get("preachers") or {}
    church = preacher.get("churches") or {}

    facts = {
        "title": sermon.get("title"),
        "preacher_id": sermon.get("preacher_id"),
        "preacher": preacher.get("name"),
        "church": church.get("name"),
        "date": sermon.get("date"),
        "primary_text": sermon.get("primary_text"),
        "series": sermon.get("series_name"),
        "sermon_type": sermon.get("sermon_type"),
        "tone": sermon.get("tone"),
        "main_thesis": sermon.get("main_thesis"),
        "abstract": sermon.get("abstract"),
        "top_loci": top_loci,
        "anchor_claims": [(u["unit_index"], u["key_claim"]) for u in anchor_units],
        "application_claims": [(u["unit_index"], u["key_claim"]) for u in application_units],
        "primary_text_refs": primary_refs,
        "cross_references": cross_refs[:15],  # cap to keep tokens reasonable
    }

    lines = [
        f"Title: {facts['title']}",
        f"Preacher: {facts['preacher']}",
        f"Church: {facts['church']}",
        f"Date: {facts['date']}",
        f"Series: {facts['series'] or '(none)'}",
        f"Primary text: {facts['primary_text']}",
        f"Sermon type: {facts['sermon_type']}",
        "",
        "Main thesis:",
        f"  {facts['main_thesis']}",
        "",
        "Abstract:",
        f"  {facts['abstract']}",
        "",
        "Doctrinal emphasis (top loci):",
    ]
    for name, count in top_loci:
        lines.append(f"  - {name} ({count} units)")
    lines.append("")
    lines.append("Theological claims established in this sermon:")
    for idx, claim in facts["anchor_claims"]:
        lines.append(f"  - unit #{idx}: {claim}")
    lines.append("")
    lines.append("Applications surfaced:")
    for idx, claim in facts["application_claims"]:
        lines.append(f"  - unit #{idx}: {claim}")
    lines.append("")
    lines.append("Primary-text citations (within the declared passage):")
    for r in primary_refs:
        lines.append(f"  - {r}")
    lines.append("")
    lines.append("Cross-references (outside the primary passage):")
    for r in facts["cross_references"]:
        lines.append(f"  - {r}")

    return facts, "\n".join(lines)


# ----------------------------------------------------------------------------
# Prompt assembly
# ----------------------------------------------------------------------------

def _load(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _voice_prompt_text(preacher_id: Optional[str] = None) -> tuple[str, str]:
    """Returns (voice_text, version_hash) so we know which voice produced output.
    If preacher_id is provided and registered in VOICE_PROFILES, use that pastor's
    style guide. Otherwise fall back to the generic _voice_sgm.md prompt.
    """
    if preacher_id and preacher_id in VOICE_PROFILES:
        path = REPO_ROOT / VOICE_PROFILES[preacher_id]
        if not path.exists():
            log.warning(f"voice profile for {preacher_id} not found at {path}; falling back to default")
            path = PROMPTS_DIR / "_voice_sgm.md"
    else:
        path = PROMPTS_DIR / "_voice_sgm.md"
    voice = _load(path)
    version = hashlib.sha256(voice.encode("utf-8")).hexdigest()[:12]
    return voice, version


def _artifact_prompt(artifact_type: str) -> str:
    fname = PROMPT_FILES.get(artifact_type)
    if not fname:
        raise ValueError(f"no prompt file registered for artifact_type={artifact_type}")
    return _load(PROMPTS_DIR / fname)


def _system_prompt(artifact_type: str, sermon_facts_text: str, preacher_id: Optional[str] = None) -> tuple[list[dict], str]:
    """
    Returns the system prompt as a list of content blocks with cache_control
    on the stable portions (voice + per-artifact instructions). Voice is
    selected per-preacher via VOICE_PROFILES.
    """
    voice, version = _voice_prompt_text(preacher_id)
    artifact = _artifact_prompt(artifact_type)

    blocks = [
        {
            "type": "text",
            "text": voice,
            "cache_control": {"type": "ephemeral"},
        },
        {
            "type": "text",
            "text": "\n\n---\n\n" + artifact,
            "cache_control": {"type": "ephemeral"},
        },
        {
            "type": "text",
            "text": "\n\n---\n\n# Sermon facts\n\n" + sermon_facts_text,
        },
    ]
    return blocks, version


# ----------------------------------------------------------------------------
# Generation
# ----------------------------------------------------------------------------

def _repair_json(raw: str) -> str:
    """
    Repair common LLM JSON malformations:
      - markdown fences
      - unescaped double quotes inside string values (verses often have them)
      - smart/curly quotes
      - trailing commas
      - truncation (best-effort: close open braces/brackets)
    Ported from pipeline.py:_repair_json.
    """
    import re as _re

    text = raw.strip()

    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
    if text.endswith("```"):
        text = text.rsplit("```", 1)[0].strip()

    text = text.replace("“", '\\"').replace("”", '\\"')
    text = text.replace("‘", "'").replace("’", "'")
    text = _re.sub(r",\s*([}\]])", r"\1", text)
    text = _re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", text)

    # Core: walk the text and escape rogue quotes inside string values.
    result = []
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if ch == '"':
            result.append('"')
            i += 1
            while i < n:
                c = text[i]
                if c == "\\" and i + 1 < n:
                    result.append(c); result.append(text[i + 1]); i += 2
                elif c == '"':
                    rest = text[i + 1:].lstrip()
                    if not rest or rest[0] in ",:]}\n":
                        result.append('"'); i += 1; break
                    else:
                        result.append('\\"'); i += 1
                elif c == "\n":
                    result.append("\\n"); i += 1
                else:
                    result.append(c); i += 1
            else:
                result.append('"')
        else:
            result.append(ch); i += 1
    text = "".join(result)

    # Close truncated structures.
    opens = text.count("{") - text.count("}")
    open_arr = text.count("[") - text.count("]")
    if open_arr > 0:
        text += "]" * open_arr
    if opens > 0:
        text += "}" * opens

    return text


def generate_one(sermon_id: str, artifact_type: str, *, model: str, write: bool) -> dict:
    if artifact_type not in ARTIFACT_TYPES:
        raise ValueError(f"unknown artifact_type: {artifact_type}")

    facts_dict, facts_text = _build_sermon_facts(sermon_id)
    blocks, voice_version = _system_prompt(artifact_type, facts_text, facts_dict.get("preacher_id"))

    user_message = (
        f"Generate the {artifact_type.replace('_', ' ')} artifact for the sermon described "
        f"above. Output ONLY a single JSON object matching the schema in the artifact "
        f"specification. No markdown fences. No commentary."
    )

    client = get_anthropic()
    log.info(f"calling {model} for sermon={sermon_id} type={artifact_type}")
    start = time.time()
    response = client.messages.create(
        model=model,
        max_tokens=MAX_OUTPUT_TOKENS,
        system=blocks,
        messages=[{"role": "user", "content": user_message}],
    )
    elapsed = time.time() - start

    raw = response.content[0].text.strip()
    repaired = _repair_json(raw)
    try:
        body = json.loads(repaired)
    except json.JSONDecodeError as exc:
        log.error(f"JSON parse failed: {exc}\nRaw output:\n{raw[:500]}")
        raise

    body_text = _flatten_body(body, artifact_type)

    in_tokens = response.usage.input_tokens
    out_tokens = response.usage.output_tokens
    cache_read = getattr(response.usage, "cache_read_input_tokens", 0) or 0
    cache_write = getattr(response.usage, "cache_creation_input_tokens", 0) or 0
    log.info(
        f"  done in {elapsed:.1f}s — in={in_tokens} (cache_read={cache_read}, "
        f"cache_write={cache_write}) out={out_tokens}"
    )

    if write:
        sb = get_supabase()
        sb.table("sermon_artifacts").upsert(
            {
                "sermon_id": sermon_id,
                "artifact_type": artifact_type,
                "body": body,
                "body_text": body_text,
                "status": "pending_review",
                "generation_model": model,
                "voice_prompt_version": voice_version,
                "input_tokens": in_tokens,
                "output_tokens": out_tokens,
                "updated_at": "now()",
            },
            on_conflict="sermon_id,artifact_type",
        ).execute()
        log.info("  written to sermon_artifacts")

    return body


def _flatten_body(body: dict | list, artifact_type: str) -> str:
    """Turn the structured artifact body into plain text for preview / search."""
    if artifact_type == "prayer_prompt":
        return f"{body.get('title','')}\n\n{body.get('prayer_text','')}".strip()
    if artifact_type == "memory_verse":
        return (
            f"{body.get('reference','')}\n\n{body.get('full_text','')}\n\n"
            f"{body.get('why_this_verse','')}"
        ).strip()
    if isinstance(body, list):
        return "\n\n".join(json.dumps(x, ensure_ascii=False) for x in body)
    return json.dumps(body, ensure_ascii=False, indent=2)


# ----------------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)

    p_gen = sub.add_parser("generate", help="Generate and write an artifact")
    p_gen.add_argument("sermon_id")
    p_gen.add_argument("--type", choices=ARTIFACT_TYPES,
                        help="Generate one type only. Omit for all six.")
    p_gen.add_argument("--model", default=DEFAULT_MODEL)
    p_gen.add_argument("--skip-existing", action="store_true",
                        help="Skip artifact types that already have a row for this sermon.")

    p_prev = sub.add_parser("preview", help="Generate and print, do not write")
    p_prev.add_argument("sermon_id")
    p_prev.add_argument("--type", choices=ARTIFACT_TYPES,
                         help="Generate one type only. Omit for all six.")
    p_prev.add_argument("--model", default=DEFAULT_MODEL)

    args = parser.parse_args()
    write = args.command == "generate"
    types = [args.type] if args.type else list(ARTIFACT_TYPES)

    existing: set[str] = set()
    if write and getattr(args, "skip_existing", False):
        sb = get_supabase()
        rows = (
            sb.table("sermon_artifacts")
            .select("artifact_type")
            .eq("sermon_id", args.sermon_id)
            .execute()
            .data
            or []
        )
        existing = {r["artifact_type"] for r in rows}

    for t in types:
        if t in existing:
            log.info(f"  skip {t} (already exists)")
            continue
        print(f"\n--- {t} ---")
        body = generate_one(args.sermon_id, t, model=args.model, write=write)
        if not write:
            print(json.dumps(body, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
