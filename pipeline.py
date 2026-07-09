"""
Shepherd's Guild — Sermon Decomposition Pipeline v3.1
=====================================================

Three-stage pipeline:
  1. DECOMPOSE  — Send transcript to Anthropic API with v3 spec → JSON
  2. EMBED      — Generate Voyage 3.5 embeddings for each unit's content
  3. INGEST     — Write normalized rows to Supabase

Usage:
  # Single sermon (.txt)
  python pipeline.py decompose transcript.txt --preacher "John MacArthur"

  # Single sermon (sermonindex .json — preacher auto-detected)
  python pipeline.py decompose sermon.json

  # Batch - all .txt and .json files in a folder
  python pipeline.py batch ./transcripts/ --preacher "John MacArthur"

  # Batch sermonindex JSONs (preacher auto-detected per file)
  python pipeline.py batch ./sermon-transcripts/da-carson/

  # Just embed + ingest a previously decomposed JSON
  python pipeline.py ingest decomposed.json --preacher "John MacArthur"

  # Decompose only (no database write) — for QA review
  python pipeline.py decompose transcript.txt --preacher "John MacArthur" --dry-run

Environment variables (set in .env or export):
  ANTHROPIC_API_KEY   — Your Anthropic API key
  VOYAGE_API_KEY      — Your Voyage AI API key
  SUPABASE_URL        — Your Supabase project URL
  SUPABASE_KEY        — Your Supabase service role key
"""

import os
import sys
import json
import time
import argparse
import logging
from pathlib import Path
from datetime import datetime
from typing import Optional

# ---------------------------------------------------------------------------
# Dependencies — install with:
#   pip install anthropic voyageai supabase python-dotenv
# ---------------------------------------------------------------------------
try:
    import anthropic
    import voyageai
    from supabase import create_client, Client
    from dotenv import load_dotenv
except ImportError as e:
    print(f"Missing dependency: {e}")
    print("Install with: pip install anthropic voyageai supabase python-dotenv")
    sys.exit(1)

load_dotenv()

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
ANTHROPIC_MODEL = "claude-sonnet-4-5-20250929"
VOYAGE_MODEL = "voyage-3.5"
VOYAGE_DIMENSIONS = 1024
SPEC_VERSION = "v3"

# Rate limiting
DECOMPOSE_DELAY_SEC = 2
EMBED_BATCH_SIZE = 32
EMBED_DELAY_SEC = 0.5

# Paths
SPEC_PATH = Path(__file__).parent / "sermon-decomposition-spec-v3.md"
OUTPUT_DIR = Path(__file__).parent / "output"
OUTPUT_DIR.mkdir(exist_ok=True)

# ---------------------------------------------------------------------------
# Taxonomy Validation Sets
# Every enum field that touches the database gets a validation set.
# The sanitizer strips invalid values and logs warnings.
# This catches model taxonomy drift without crashing the pipeline.
# ---------------------------------------------------------------------------
VALID_SERMON_TYPES = {
    "expository", "topical", "textual", "narrative", "polemic"
}

VALID_TONES = {
    "pastoral", "prophetic", "didactic", "celebratory",
    "lament", "polemic", "evangelistic"
}

VALID_HERMENEUTICAL_METHODS = {
    "grammatical_historical", "redemptive_historical",
    "canonical", "applicatory", "polemic"
}

VALID_RHETORICAL_FUNCTIONS = {
    "exposition", "theological_claim", "illustration", "application",
    "introduction", "conclusion", "transition", "pastoral_aside", "prayer"
}

VALID_REGISTERS = {
    "logos", "pathos", "ethos", "narrative", "doxological"
}

VALID_LOCI = {
    "Theology Proper", "Christology", "Pneumatology", "Soteriology",
    "Hamartiology", "Anthropology", "Ecclesiology", "Eschatology",
    "Bibliology", "Sanctification", "Providence / Sovereignty",
    "Covenant Theology", "Ethics / Moral Theology", "Doxology / Worship",
    "Spiritual Warfare", "Pastoral Theology"
}

VALID_ILLUSTRATION_TYPES = {
    "personal_story", "historical_example", "analogy",
    "hypothetical", "cultural_reference"
}

VALID_APPLICATION_SPECIFICITY = {
    "abstract", "concrete", "mixed"
}

VALID_CITATION_MODES = {
    "full_reading", "partial_reading", "reference_in_passing"
}

VALID_CITATION_FUNCTIONS = {
    "authority", "contrast", "echo", "fulfillment", "parallel", "corrective"
}

VALID_QUOTATION_FUNCTIONS = {
    "authority", "illustration", "provocation", "devotional", "opponent"
}

VALID_BT_TYPES = {
    "typology", "fulfillment", "progressive_revelation", "narrative_arc",
    "intertextual_echo", "contrast", "thematic_thread"
}

# Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S"
)
log = logging.getLogger("pipeline")


# ---------------------------------------------------------------------------
# Sanitizer helpers
# ---------------------------------------------------------------------------
def sanitize_enum(value, valid_set, field_name, context=""):
    """Sanitize a single enum value. Returns value if valid, None if not."""
    if value is None:
        return None
    if value in valid_set:
        return value
    log.warning(f"{context}invalid {field_name}: '{value}' (removed)")
    return None


def sanitize_enum_array(values, valid_set, field_name, context=""):
    """Sanitize an array of enum values. Returns only valid values."""
    if not values:
        return []
    clean = [v for v in values if v in valid_set]
    bad = set(values) - valid_set
    if bad:
        log.warning(f"{context}invalid {field_name} removed: {bad}")
    return clean


# ---------------------------------------------------------------------------
# Clients (initialized lazily)
# ---------------------------------------------------------------------------
_anthropic_client = None
_voyage_client = None
_supabase_client = None


def get_anthropic() -> anthropic.Anthropic:
    global _anthropic_client
    if _anthropic_client is None:
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            raise EnvironmentError("ANTHROPIC_API_KEY not set")
        _anthropic_client = anthropic.Anthropic(api_key=api_key)
    return _anthropic_client


def get_voyage() -> voyageai.Client:
    global _voyage_client
    if _voyage_client is None:
        api_key = os.getenv("VOYAGE_API_KEY")
        if not api_key:
            raise EnvironmentError("VOYAGE_API_KEY not set")
        _voyage_client = voyageai.Client(api_key=api_key)
    return _voyage_client


def get_supabase() -> Client:
    global _supabase_client
    if _supabase_client is None:
        url = os.getenv("SUPABASE_URL")
        key = os.getenv("SUPABASE_KEY")
        if not url or not key:
            raise EnvironmentError("SUPABASE_URL and SUPABASE_KEY must be set")
        _supabase_client = create_client(url, key)
    return _supabase_client


# ---------------------------------------------------------------------------
# SermonIndex JSON reader
# ---------------------------------------------------------------------------
def is_sermonindex_json(filepath: Path) -> bool:
    """Check if a JSON file is a sermonindex format."""
    if filepath.suffix.lower() != ".json":
        return False
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
        return "transcript" in data and "contributor" in data
    except (json.JSONDecodeError, KeyError):
        return False


def read_sermonindex_json(filepath: Path) -> dict:
    """Read a sermonindex JSON and extract metadata + transcript."""
    with open(filepath, "r", encoding="utf-8") as f:
        data = json.load(f)

    transcript = data.get("transcript")
    if not transcript:
        raise ValueError(f"No transcript in {filepath.name}")

    refs = data.get("bibleReferences") or []
    primary_text = None
    if refs:
        primary_text = refs[0].get("text", None)

    return {
        "transcript": transcript,
        "preacher": data.get("contributor", "Unknown"),
        "title": data.get("title"),
        "primary_text": primary_text,
        "si_metadata": {
            "sermonindex_id": data.get("id"),
            "description": data.get("description"),
            "topics": data.get("topics"),
            "bible_references": refs,
            "duration": data.get("duration"),
            "audio_url": data.get("audioUrl"),
            "views": data.get("views"),
        }
    }


# ---------------------------------------------------------------------------
# Stage 1: DECOMPOSE
# ---------------------------------------------------------------------------
def load_spec() -> str:
    """Load the v3 decomposition spec as the system prompt."""
    if not SPEC_PATH.exists():
        raise FileNotFoundError(
            f"Spec not found at {SPEC_PATH}. "
            f"Place sermon-decomposition-spec-v3.md next to this script."
        )
    return SPEC_PATH.read_text(encoding="utf-8")


def decompose_sermon(
    transcript: str,
    preacher: str,
    known_title: Optional[str] = None,
    known_primary_text: Optional[str] = None
) -> dict:
    """
    Send a sermon transcript to Claude and get back structured JSON
    per the v3 decomposition spec.
    """
    client = get_anthropic()
    spec = load_spec()

    metadata_hints = f"The preacher is: {preacher}"
    if known_title:
        metadata_hints += f"\nThe sermon title is: {known_title}"
    if known_primary_text:
        metadata_hints += f"\nThe primary text is: {known_primary_text}"

    system_prompt = (
        f"{spec}\n\n"
        f"---\n\n"
        f"You are a sermon decomposition engine. Given a sermon transcript, "
        f"produce a single JSON object conforming exactly to the spec above. "
        f"Output ONLY valid JSON — no markdown fences, no commentary, no preamble.\n\n"
        f"{metadata_hints}"
    )

    user_message = (
        f"Decompose the following sermon transcript:\n\n"
        f"---\n\n"
        f"{transcript}"
    )

    log.info(f"Sending to {ANTHROPIC_MODEL} ({len(transcript):,} chars)...")
    start = time.time()

    with client.messages.stream(
        model=ANTHROPIC_MODEL,
        max_tokens=64000,
        system=system_prompt,
        messages=[{"role": "user", "content": user_message}]
    ) as stream:
        for event in stream:
            pass
        response = stream.get_final_message()

    elapsed = time.time() - start
    input_tokens = response.usage.input_tokens
    output_tokens = response.usage.output_tokens

    log.info(
        f"Decomposition complete: {input_tokens:,} in / {output_tokens:,} out "
        f"({elapsed:.1f}s)"
    )

    raw_text = response.content[0].text.strip()

    if raw_text.startswith("```"):
        raw_text = raw_text.split("\n", 1)[1]
    if raw_text.endswith("```"):
        raw_text = raw_text.rsplit("```", 1)[0]
    raw_text = raw_text.strip()

    try:
        decomposition = json.loads(raw_text)
    except json.JSONDecodeError as e:
        # LLMs occasionally emit structurally-broken JSON — most often an
        # unescaped double-quote inside a string (verbatim Scripture/sermon
        # quotes reliably trigger this). Fall back to a tolerant repair parse
        # before giving up; retrying the model just re-rolls the same glitch.
        log.warning(f"Strict JSON parse failed ({e}); attempting repair…")
        try:
            import json_repair
            decomposition = json_repair.loads(raw_text)
            if not isinstance(decomposition, dict) or "units" not in decomposition:
                raise ValueError("repaired JSON missing expected structure")
            log.info("JSON repair succeeded")
        except Exception as e2:
            log.error(f"Failed to parse JSON response (even after repair): {e2}")
            log.error(f"First 500 chars: {raw_text[:500]}")
            debug_path = OUTPUT_DIR / f"debug_raw_{int(time.time())}.txt"
            debug_path.write_text(raw_text, encoding="utf-8")
            log.error(f"Raw output saved to {debug_path}")
            raise

    decomposition["_pipeline"] = {
        "spec_version": SPEC_VERSION,
        "model": ANTHROPIC_MODEL,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "processing_seconds": round(elapsed, 1),
        "processing_cost_usd": round(
            (input_tokens / 1_000_000 * 3.0) + (output_tokens / 1_000_000 * 15.0),
            4
        ),
        "decomposed_at": datetime.utcnow().isoformat() + "Z"
    }

    return decomposition


# ---------------------------------------------------------------------------
# Stage 2: EMBED
# ---------------------------------------------------------------------------
def embed_units(units: list[dict]) -> list[list[float]]:
    """Generate Voyage 3.5 embeddings for each unit's content field."""
    client = get_voyage()
    texts = [u["content"] for u in units]

    all_embeddings = []
    total_batches = (len(texts) + EMBED_BATCH_SIZE - 1) // EMBED_BATCH_SIZE

    for i in range(0, len(texts), EMBED_BATCH_SIZE):
        batch = texts[i:i + EMBED_BATCH_SIZE]
        batch_num = (i // EMBED_BATCH_SIZE) + 1
        log.info(f"Embedding batch {batch_num}/{total_batches} ({len(batch)} units)...")

        result = client.embed(
            batch,
            model=VOYAGE_MODEL,
            input_type="document",
            output_dimension=VOYAGE_DIMENSIONS
        )
        all_embeddings.extend(result.embeddings)

        if batch_num < total_batches:
            time.sleep(EMBED_DELAY_SEC)

    log.info(f"Embedded {len(all_embeddings)} units ({VOYAGE_DIMENSIONS} dims each)")
    return all_embeddings


# ---------------------------------------------------------------------------
# Stage 3: INGEST (with full sanitization)
# ---------------------------------------------------------------------------
def ensure_preacher(preacher_name: str, is_canonical: bool = False) -> str:
    """Get or create a preacher record. Returns the preacher UUID."""
    sb = get_supabase()

    result = sb.table("preachers").select("id").eq("name", preacher_name).execute()
    if result.data:
        preacher_id = result.data[0]["id"]
        log.info(f"Found existing preacher: {preacher_name} ({preacher_id})")
        return preacher_id

    result = sb.table("preachers").insert({
        "name": preacher_name,
        "is_canonical": is_canonical,
        "is_public": False
    }).execute()

    preacher_id = result.data[0]["id"]
    log.info(f"Created preacher: {preacher_name} ({preacher_id})")
    return preacher_id


def ingest_sermon(
    decomposition: dict,
    preacher_id: str,
    embeddings: list[list[float]],
    raw_transcript: Optional[str] = None
) -> str:
    """Write a decomposed sermon to Supabase with full sanitization."""
    sb = get_supabase()
    pipeline_meta = decomposition.get("_pipeline", {})
    units = decomposition.get("units", [])

    if len(embeddings) != len(units):
        raise ValueError(
            f"Embedding count ({len(embeddings)}) doesn't match "
            f"unit count ({len(units)})"
        )

    # --- Sanitize sermon-level fields ---
    sermon_data = {
        "preacher_id": preacher_id,
        "title": decomposition.get("title"),
        "date": decomposition.get("date"),
        "primary_text": decomposition.get("primary_text"),
        "sermon_type": sanitize_enum(
            decomposition.get("sermon_type"),
            VALID_SERMON_TYPES, "sermon_type", "Sermon: "
        ),
        "series_name": decomposition.get("series_name"),
        "series_position": decomposition.get("series_position"),
        "abstract": decomposition.get("abstract"),
        "main_thesis": decomposition.get("main_thesis"),
        "target_audience_cues": decomposition.get("target_audience_cues"),
        "tone": sanitize_enum_array(
            decomposition.get("tone"),
            VALID_TONES, "tone", "Sermon: "
        ),
        "hermeneutical_method": sanitize_enum_array(
            decomposition.get("hermeneutical_method"),
            VALID_HERMENEUTICAL_METHODS, "hermeneutical_method", "Sermon: "
        ),
        "raw_transcript": raw_transcript,
        "spec_version": pipeline_meta.get("spec_version", SPEC_VERSION),
        "decomposed_at": pipeline_meta.get("decomposed_at"),
        "decomposition_model": pipeline_meta.get("model"),
        "input_tokens": pipeline_meta.get("input_tokens"),
        "output_tokens": pipeline_meta.get("output_tokens"),
        "processing_cost_usd": pipeline_meta.get("processing_cost_usd"),
    }

    result = sb.table("sermons").insert(sermon_data).execute()
    sermon_id = result.data[0]["id"]
    log.info(f"Inserted sermon: {decomposition.get('title')} ({sermon_id})")

    # --- Insert units with full sanitization ---
    for i, unit in enumerate(units):
        ctx = f"Unit {unit.get('unit_index', i)}: "

        unit_data = {
            "sermon_id": sermon_id,
            "unit_index": unit.get("unit_index", i),
            "rhetorical_function": sanitize_enum(
                unit.get("rhetorical_function"),
                VALID_RHETORICAL_FUNCTIONS, "rhetorical_function", ctx
            ),
            "content": unit.get("content"),
            "summary": unit.get("summary"),
            "key_claim": unit.get("key_claim"),
            "illustration_type": sanitize_enum(
                unit.get("illustration_type"),
                VALID_ILLUSTRATION_TYPES, "illustration_type", ctx
            ),
            "application_specificity": sanitize_enum(
                unit.get("application_specificity"),
                VALID_APPLICATION_SPECIFICITY, "application_specificity", ctx
            ),
            "rhetorical_register": sanitize_enum_array(
                unit.get("rhetorical_register"),
                VALID_REGISTERS, "rhetorical_register", ctx
            ),
            "doctrinal_loci": sanitize_enum_array(
                unit.get("doctrinal_loci"),
                VALID_LOCI, "doctrinal_loci", ctx
            ),
            "people_referenced": unit.get("people_referenced"),
            "sermon_series_context": unit.get("sermon_series_context"),
            "embedding": embeddings[i],
        }

        unit_result = sb.table("units").insert(unit_data).execute()
        unit_id = unit_result.data[0]["id"]

        # --- Insert Tier 1 citations (primary text) ---
        for citation in unit.get("primary_text_citations", []) or []:
            sb.table("citations").insert({
                "unit_id": unit_id,
                "tier": 1,
                "reference": citation.get("reference"),
                "mode": sanitize_enum(
                    citation.get("mode"),
                    VALID_CITATION_MODES, "citation mode", ctx
                ),
            }).execute()

        # --- Insert Tier 2 citations (cross-references) ---
        for xref in unit.get("cross_references", []) or []:
            sb.table("citations").insert({
                "unit_id": unit_id,
                "tier": 2,
                "reference": xref.get("reference"),
                "function": sanitize_enum(
                    xref.get("function"),
                    VALID_CITATION_FUNCTIONS, "citation function", ctx
                ),
                "supports_claim": xref.get("supports_claim"),
            }).execute()

        # --- Insert Tier 3 quotations ---
        for quote in unit.get("quotations", []) or []:
            sb.table("quotations").insert({
                "unit_id": unit_id,
                "text": quote.get("text"),
                "attribution": quote.get("attribution"),
                "source": quote.get("source"),
                "function": sanitize_enum(
                    quote.get("function"),
                    VALID_QUOTATION_FUNCTIONS, "quotation function", ctx
                ),
            }).execute()

        # --- Insert BT moves ---
        for move in unit.get("biblical_theological_moves", []) or []:
            bt_type = sanitize_enum(
                move.get("type"),
                VALID_BT_TYPES, "BT move type", ctx
            )
            if bt_type is None:
                continue  # Skip entirely if type is invalid
            sb.table("bt_moves").insert({
                "unit_id": unit_id,
                "type": bt_type,
                "source_text": move.get("source_text"),
                "target_text": move.get("target_text"),
                "pastor_framing": move.get("pastor_framing"),
            }).execute()

    log.info(
        f"Ingested {len(units)} units with citations, quotations, and BT moves"
    )
    return sermon_id


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------
def process_sermon(
    transcript_path: Path,
    preacher: Optional[str] = None,
    is_canonical: bool = False,
    dry_run: bool = False
) -> Optional[str]:
    """
    Full pipeline: decompose → embed → ingest.
    Accepts .txt or sermonindex .json files.
    """
    si_data = None
    if is_sermonindex_json(transcript_path):
        si_data = read_sermonindex_json(transcript_path)
        transcript = si_data["transcript"]
        preacher = preacher or si_data["preacher"]
        known_title = si_data.get("title")
        known_primary_text = si_data.get("primary_text")
        log.info(f"SermonIndex JSON detected: {si_data['preacher']} — {known_title}")
    else:
        transcript = transcript_path.read_text(encoding="utf-8")
        known_title = None
        known_primary_text = None

    if not preacher:
        log.error("Preacher name required. Use --preacher or provide a sermonindex JSON.")
        sys.exit(1)

    log.info(f"{'='*60}")
    log.info(f"Processing: {transcript_path.name}")
    log.info(f"Preacher: {preacher}")
    log.info(f"{'='*60}")
    log.info(f"Transcript: {len(transcript):,} chars")

    decomposition = decompose_sermon(
        transcript, preacher,
        known_title=known_title,
        known_primary_text=known_primary_text
    )
    units = decomposition.get("units", [])
    log.info(f"Produced {len(units)} units")

    stem = transcript_path.stem
    json_path = OUTPUT_DIR / f"{stem}_decomposed.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(decomposition, f, indent=2, ensure_ascii=False)
    log.info(f"Saved decomposition: {json_path}")

    meta = decomposition.get("_pipeline", {})
    log.info(
        f"Cost: ${meta.get('processing_cost_usd', 0):.4f} "
        f"({meta.get('input_tokens', 0):,} in / "
        f"{meta.get('output_tokens', 0):,} out)"
    )

    if dry_run:
        log.info("DRY RUN — skipping embed and ingest")
        return None

    embeddings = embed_units(units)
    preacher_id = ensure_preacher(preacher, is_canonical=is_canonical)
    sermon_id = ingest_sermon(
        decomposition, preacher_id, embeddings, raw_transcript=transcript
    )

    log.info(f"Complete! Sermon ID: {sermon_id}")
    return sermon_id


def process_batch(
    folder: Path,
    preacher: Optional[str] = None,
    is_canonical: bool = False,
    dry_run: bool = False
):
    """Process all .txt and sermonindex .json files in a folder."""
    txt_files = sorted(folder.glob("*.txt"))
    json_files = [f for f in sorted(folder.glob("*.json"))
                  if f.name != "_index.json" and is_sermonindex_json(f)]
    files = txt_files + json_files

    if not files:
        log.error(f"No .txt or sermonindex .json files found in {folder}")
        return

    log.info(f"Found {len(files)} files ({len(txt_files)} txt, {len(json_files)} json) in {folder}")

    if txt_files and not preacher:
        log.error("--preacher required when batch processing .txt files")
        return

    total_cost = 0.0
    results = []

    for i, filepath in enumerate(files, 1):
        log.info(f"\n[{i}/{len(files)}] {filepath.name}")
        try:
            sermon_id = process_sermon(filepath, preacher, is_canonical, dry_run)
            results.append({"file": filepath.name, "sermon_id": sermon_id, "status": "ok"})

            json_path = OUTPUT_DIR / f"{filepath.stem}_decomposed.json"
            if json_path.exists():
                with open(json_path) as f:
                    data = json.load(f)
                    cost = data.get("_pipeline", {}).get("processing_cost_usd", 0)
                    total_cost += cost

        except Exception as e:
            log.error(f"FAILED: {filepath.name} — {e}")
            results.append({"file": filepath.name, "sermon_id": None, "status": str(e)})

        if i < len(files):
            time.sleep(DECOMPOSE_DELAY_SEC)

    log.info(f"\n{'='*60}")
    log.info(f"BATCH COMPLETE")
    log.info(f"{'='*60}")
    ok = sum(1 for r in results if r["status"] == "ok")
    log.info(f"Processed: {ok}/{len(files)} succeeded")
    log.info(f"Total decomposition cost: ${total_cost:.4f}")

    report_path = OUTPUT_DIR / f"batch_report_{int(time.time())}.json"
    with open(report_path, "w") as f:
        json.dump({
            "preacher": preacher,
            "total_files": len(files),
            "succeeded": ok,
            "total_cost_usd": round(total_cost, 4),
            "results": results
        }, f, indent=2)
    log.info(f"Batch report: {report_path}")


def ingest_existing(
    json_path: Path,
    preacher: Optional[str] = None,
    is_canonical: bool = False
):
    """Embed and ingest a previously decomposed JSON file."""
    log.info(f"Ingesting existing decomposition: {json_path}")

    with open(json_path, "r", encoding="utf-8") as f:
        decomposition = json.load(f)

    if not preacher:
        preacher = decomposition.get("preacher")
    if not preacher:
        log.error("Preacher name required. Use --preacher or ensure it's in the JSON.")
        sys.exit(1)

    units = decomposition.get("units", [])
    log.info(f"Found {len(units)} units")

    embeddings = embed_units(units)
    preacher_id = ensure_preacher(preacher, is_canonical=is_canonical)

    raw_transcript = None
    transcript_path = json_path.with_suffix(".txt")
    if transcript_path.exists():
        raw_transcript = transcript_path.read_text(encoding="utf-8")

    sermon_id = ingest_sermon(
        decomposition, preacher_id, embeddings, raw_transcript=raw_transcript
    )
    log.info(f"Complete! Sermon ID: {sermon_id}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(
        description="Shepherd's Guild — Sermon Decomposition Pipeline v3.1"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    p_decompose = subparsers.add_parser(
        "decompose", help="Decompose a single sermon (.txt or sermonindex .json)"
    )
    p_decompose.add_argument("transcript", type=Path,
                             help="Path to .txt transcript or sermonindex .json")
    p_decompose.add_argument("--preacher", required=False,
                             help="Preacher name (auto-detected from sermonindex JSON)")
    p_decompose.add_argument("--canonical", action="store_true",
                             help="Mark as Guild Hall canonical preacher")
    p_decompose.add_argument("--dry-run", action="store_true",
                             help="Decompose only — skip embed and ingest")

    p_batch = subparsers.add_parser(
        "batch", help="Decompose all .txt and sermonindex .json files in a folder"
    )
    p_batch.add_argument("folder", type=Path,
                         help="Folder containing .txt or sermonindex .json files")
    p_batch.add_argument("--preacher", required=False,
                         help="Preacher name (required for .txt, auto-detected for .json)")
    p_batch.add_argument("--canonical", action="store_true",
                         help="Mark as Guild Hall canonical preacher")
    p_batch.add_argument("--dry-run", action="store_true",
                         help="Decompose only — skip embed and ingest")

    p_ingest = subparsers.add_parser(
        "ingest", help="Embed and ingest a previously decomposed JSON"
    )
    p_ingest.add_argument("json_file", type=Path,
                          help="Path to decomposed .json file")
    p_ingest.add_argument("--preacher", required=False,
                          help="Preacher name (auto-detected from JSON if present)")
    p_ingest.add_argument("--canonical", action="store_true",
                          help="Mark as Guild Hall canonical preacher")

    args = parser.parse_args()

    if args.command == "decompose":
        if not args.transcript.exists():
            log.error(f"File not found: {args.transcript}")
            sys.exit(1)
        if args.transcript.suffix.lower() == ".txt" and not args.preacher:
            log.error("--preacher required for .txt files")
            sys.exit(1)
        process_sermon(args.transcript, args.preacher, args.canonical, args.dry_run)

    elif args.command == "batch":
        if not args.folder.is_dir():
            log.error(f"Not a directory: {args.folder}")
            sys.exit(1)
        process_batch(args.folder, args.preacher, args.canonical, args.dry_run)

    elif args.command == "ingest":
        if not args.json_file.exists():
            log.error(f"File not found: {args.json_file}")
            sys.exit(1)
        ingest_existing(args.json_file, args.preacher, args.canonical)


if __name__ == "__main__":
    main()