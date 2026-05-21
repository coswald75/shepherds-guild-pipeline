"""
Shepherd's Guild — Sermon Decomposition Pipeline v3.1 (Batch Mode)
===================================================================

Uses Anthropic's Message Batches API for 50% cost reduction on
non-latency-sensitive decomposition work.

Three-phase workflow:
  Phase 1: SUBMIT  — Build batch of decomposition requests → submit to API
  Phase 2: POLL    — Check batch status until complete
  Phase 3: PROCESS — Parse results → sanitize → embed → ingest to Supabase

Usage:
  # Submit a batch from a folder of sermons
  python pipeline_batch.py submit ./transcripts/ --preacher "R.C. Sproul" --canonical

  # Submit sermonindex JSONs (preacher auto-detected per file)
  python pipeline_batch.py submit ./sermon-transcripts/sproul/

  # Check status of a running batch
  python pipeline_batch.py status msgbatch_01HkcTjaV5uDC8jWR4ZsDV8d

  # Process results once batch is complete
  python pipeline_batch.py process msgbatch_01HkcTjaV5uDC8jWR4ZsDV8d --preacher "R.C. Sproul" --canonical

  # Submit only (dry-run: save decomposed JSON, skip embed + ingest)
  python pipeline_batch.py submit ./transcripts/ --preacher "R.C. Sproul" --dry-run

  # List recent batches
  python pipeline_batch.py list

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

load_dotenv(override=True)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
ANTHROPIC_MODEL = "claude-sonnet-4-5-20250929"
VOYAGE_MODEL = "voyage-3.5"
VOYAGE_DIMENSIONS = 1024
SPEC_VERSION = "v3"

# Batch API pricing (50% of standard rates)
BATCH_INPUT_COST_PER_MTOK = 1.5   # Standard is $3.0
BATCH_OUTPUT_COST_PER_MTOK = 7.5  # Standard is $15.0

# Rate limiting for embed stage
EMBED_BATCH_SIZE = 32
EMBED_DELAY_SEC = 0.5

# Paths
SPEC_PATH = Path(__file__).parent / "sermon-decomposition-spec-v3.md"
OUTPUT_DIR = Path(__file__).parent / "output"
BATCH_DIR = Path(__file__).parent / "output" / "batches"
OUTPUT_DIR.mkdir(exist_ok=True)
BATCH_DIR.mkdir(exist_ok=True)

# ---------------------------------------------------------------------------
# Taxonomy Validation Sets (identical to pipeline.py)
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
log = logging.getLogger("pipeline_batch")


# ---------------------------------------------------------------------------
# Sanitizer helpers (identical to pipeline.py)
# ---------------------------------------------------------------------------
def sanitize_enum(value, valid_set, field_name, context=""):
    if value is None:
        return None
    if value in valid_set:
        return value
    log.warning(f"{context}invalid {field_name}: '{value}' (removed)")
    return None


def sanitize_enum_array(values, valid_set, field_name, context=""):
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
# SermonIndex JSON reader (identical to pipeline.py)
# ---------------------------------------------------------------------------
def is_sermonindex_json(filepath: Path) -> bool:
    if filepath.suffix.lower() != ".json":
        return False
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
        return "transcript" in data and "contributor" in data
    except (json.JSONDecodeError, KeyError):
        return False


def read_sermonindex_json(filepath: Path) -> dict:
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
# Spec loader
# ---------------------------------------------------------------------------
def load_spec() -> str:
    if not SPEC_PATH.exists():
        raise FileNotFoundError(
            f"Spec not found at {SPEC_PATH}. "
            f"Place sermon-decomposition-spec-v3.md next to this script."
        )
    return SPEC_PATH.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Phase 1: SUBMIT — Build and submit batch
# ---------------------------------------------------------------------------
def build_batch_requests(
    folder: Path,
    preacher: Optional[str] = None
) -> tuple[list[dict], dict]:
    """
    Scan a folder for .txt and sermonindex .json files.
    Build a list of Batch API request objects.
    Returns (requests_list, manifest) where manifest maps custom_id → file info.
    """
    spec = load_spec()

    txt_files = sorted(folder.glob("*.txt"))
    json_files = [f for f in sorted(folder.glob("*.json"))
                  if f.name != "_index.json" and is_sermonindex_json(f)]
    files = txt_files + json_files

    if not files:
        log.error(f"No .txt or sermonindex .json files found in {folder}")
        return [], {}

    log.info(f"Found {len(files)} files ({len(txt_files)} txt, {len(json_files)} json)")

    if txt_files and not preacher:
        log.error("--preacher required when batch processing .txt files")
        return [], {}

    requests = []
    manifest = {}
    skipped = 0

    for filepath in files:
        # Read transcript
        try:
            if is_sermonindex_json(filepath):
                si_data = read_sermonindex_json(filepath)
                transcript = si_data["transcript"]
                file_preacher = preacher or si_data["preacher"]
                known_title = si_data.get("title")
                known_primary_text = si_data.get("primary_text")
            else:
                transcript = filepath.read_text(encoding="utf-8")
                file_preacher = preacher
                known_title = None
                known_primary_text = None
        except ValueError as e:
            log.warning(f"Skipping {filepath.name}: {e}")
            skipped += 1
            continue

        if not file_preacher:
            log.warning(f"Skipping {filepath.name}: no preacher name")
            skipped += 1
            continue

        # Build the custom_id from the filename stem
        custom_id = filepath.stem[:64]

        # Build system prompt (identical to pipeline.py)
        metadata_hints = f"The preacher is: {file_preacher}"
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

        # Build the batch request object
        requests.append({
            "custom_id": custom_id,
            "params": {
                "model": ANTHROPIC_MODEL,
                "max_tokens": 64000,
                "system": system_prompt,
                "messages": [{"role": "user", "content": user_message}]
            }
        })

        manifest[custom_id] = {
            "file": filepath.name,
            "preacher": file_preacher,
            "title": known_title,
            "primary_text": known_primary_text,
            "transcript_chars": len(transcript),
        }

    log.info(f"Built {len(requests)} batch requests ({skipped} skipped)")
    return requests, manifest


def submit_batch(
    folder: Path,
    preacher: Optional[str] = None
) -> Optional[str]:
    """Submit a batch to the Anthropic API. Returns the batch ID."""
    requests, manifest = build_batch_requests(folder, preacher)

    if not requests:
        log.error("No requests to submit")
        return None

    client = get_anthropic()

    log.info(f"Submitting batch of {len(requests)} requests to Anthropic...")
    start = time.time()

    batch = client.messages.batches.create(requests=requests)

    elapsed = time.time() - start
    log.info(f"Batch submitted in {elapsed:.1f}s")
    log.info(f"Batch ID: {batch.id}")
    log.info(f"Status: {batch.processing_status}")
    log.info(f"Expires: {batch.expires_at}")

    # Save manifest so we can map results back to files later
    manifest_path = BATCH_DIR / f"{batch.id}_manifest.json"
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump({
            "batch_id": batch.id,
            "submitted_at": datetime.utcnow().isoformat() + "Z",
            "preacher": preacher,
            "folder": str(folder),
            "request_count": len(requests),
            "manifest": manifest,
        }, f, indent=2)
    log.info(f"Manifest saved: {manifest_path}")

    return batch.id


# ---------------------------------------------------------------------------
# Phase 2: POLL — Check batch status
# ---------------------------------------------------------------------------
def check_status(batch_id: str, wait: bool = False, poll_interval: int = 60):
    """Check (and optionally wait for) batch completion."""
    client = get_anthropic()

    while True:
        batch = client.messages.batches.retrieve(batch_id)

        counts = batch.request_counts
        log.info(
            f"Batch {batch_id}: {batch.processing_status} | "
            f"succeeded={counts.succeeded} errored={counts.errored} "
            f"canceled={counts.canceled} expired={counts.expired} "
            f"processing={counts.processing}"
        )

        if batch.processing_status == "ended":
            log.info(f"Batch complete! Results URL available.")
            return batch

        if not wait:
            return batch

        log.info(f"Waiting {poll_interval}s before next check...")
        time.sleep(poll_interval)


def list_batches(limit: int = 10):
    """List recent batches."""
    client = get_anthropic()
    page = client.messages.batches.list(limit=limit)

    for batch in page.data:
        counts = batch.request_counts
        log.info(
            f"{batch.id} | {batch.processing_status} | "
            f"created={batch.created_at} | "
            f"ok={counts.succeeded} err={counts.errored} "
            f"exp={counts.expired} cancel={counts.canceled}"
        )


# ---------------------------------------------------------------------------
# Phase 3: PROCESS — Retrieve results, parse, embed, ingest
# ---------------------------------------------------------------------------
def process_batch_results(
    batch_id: str,
    preacher: Optional[str] = None,
    is_canonical: bool = False,
    dry_run: bool = False
):
    """
    Download batch results, parse decompositions, embed, and ingest.
    """
    client = get_anthropic()

    # Load manifest if available
    manifest_path = BATCH_DIR / f"{batch_id}_manifest.json"
    manifest = {}
    if manifest_path.exists():
        with open(manifest_path) as f:
            manifest_data = json.load(f)
            manifest = manifest_data.get("manifest", {})
            preacher = preacher or manifest_data.get("preacher")
        log.info(f"Loaded manifest: {len(manifest)} entries")
    else:
        log.warning(f"No manifest found at {manifest_path} — will use --preacher flag")

    # Stream results
    log.info(f"Retrieving results for batch {batch_id}...")
    result_stream = client.messages.batches.results(batch_id)

    total_cost = 0.0
    results = []
    succeeded = 0
    failed = 0

    for entry in result_stream:
        custom_id = entry.custom_id
        file_info = manifest.get(custom_id, {})
        filename = file_info.get("file", f"{custom_id}.json")
        file_preacher = file_info.get("preacher") or preacher

        if entry.result.type == "succeeded":
            message = entry.result.message
            raw_text = message.content[0].text.strip()

            # Strip markdown fences if present
            if raw_text.startswith("```"):
                raw_text = raw_text.split("\n", 1)[1]
            if raw_text.endswith("```"):
                raw_text = raw_text.rsplit("```", 1)[0]
            raw_text = raw_text.strip()

            # Calculate cost at batch rates
            input_tokens = message.usage.input_tokens
            output_tokens = message.usage.output_tokens
            cost = (
                (input_tokens / 1_000_000 * BATCH_INPUT_COST_PER_MTOK) +
                (output_tokens / 1_000_000 * BATCH_OUTPUT_COST_PER_MTOK)
            )
            total_cost += cost

            # Parse JSON
            try:
                decomposition = json.loads(raw_text)
            except json.JSONDecodeError as e:
                log.error(f"JSON parse failed for {filename}: {e}")
                # Save raw output for debugging
                debug_path = OUTPUT_DIR / f"debug_raw_{custom_id}.txt"
                debug_path.write_text(raw_text, encoding="utf-8")
                log.error(f"Raw output saved to {debug_path}")
                results.append({
                    "file": filename, "sermon_id": None,
                    "status": str(e), "cost_usd": round(cost, 4)
                })
                failed += 1
                continue

            # Attach pipeline metadata
            decomposition["_pipeline"] = {
                "spec_version": SPEC_VERSION,
                "model": ANTHROPIC_MODEL,
                "batch_id": batch_id,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "processing_cost_usd": round(cost, 4),
                "batch_mode": True,
                "decomposed_at": datetime.utcnow().isoformat() + "Z"
            }

            # Save decomposed JSON
            json_path = OUTPUT_DIR / f"{custom_id}_decomposed.json"
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(decomposition, f, indent=2, ensure_ascii=False)

            units = decomposition.get("units", [])
            log.info(
                f"OK: {filename} — {len(units)} units, "
                f"${cost:.4f} ({input_tokens:,} in / {output_tokens:,} out)"
            )

            if dry_run:
                results.append({
                    "file": filename, "sermon_id": None,
                    "status": "ok (dry-run)", "cost_usd": round(cost, 4)
                })
                succeeded += 1
                continue

            # Embed and ingest
            try:
                if not file_preacher:
                    log.error(f"No preacher for {filename} — skipping ingest")
                    results.append({
                        "file": filename, "sermon_id": None,
                        "status": "ok (no preacher for ingest)",
                        "cost_usd": round(cost, 4)
                    })
                    succeeded += 1
                    continue

                embeddings = embed_units(units)
                preacher_id = ensure_preacher(file_preacher, is_canonical=is_canonical)

                # Try to recover raw transcript for storage
                raw_transcript = None
                if file_info.get("transcript_chars"):
                    # We don't store the full transcript in manifest (too large)
                    # Try to find the original file
                    folder = manifest_data.get("folder", "") if manifest_path.exists() else ""
                    if folder:
                        orig_path = Path(folder) / filename
                        if orig_path.exists():
                            if is_sermonindex_json(orig_path):
                                si = read_sermonindex_json(orig_path)
                                raw_transcript = si["transcript"]
                            else:
                                raw_transcript = orig_path.read_text(encoding="utf-8")

                sermon_id = ingest_sermon(
                    decomposition, preacher_id, embeddings,
                    raw_transcript=raw_transcript,
                    # weekly_ingest names files <uuid>.txt → triggers UPDATE
                    # of the existing sermon row. Sermonindex/slug names pass
                    # through to INSERT (since UUID regex won't match).
                    existing_sermon_id=custom_id,
                )
                log.info(f"Ingested: {filename} → {sermon_id}")
                results.append({
                    "file": filename, "sermon_id": sermon_id,
                    "status": "ok", "cost_usd": round(cost, 4)
                })
                succeeded += 1

            except Exception as e:
                log.error(f"Ingest failed for {filename}: {e}")
                results.append({
                    "file": filename, "sermon_id": None,
                    "status": f"decomp ok, ingest failed: {e}",
                    "cost_usd": round(cost, 4)
                })
                failed += 1

        elif entry.result.type == "errored":
            error = entry.result.error
            log.error(f"API error for {filename}: {error}")
            results.append({
                "file": filename, "sermon_id": None,
                "status": f"api_error: {error}"
            })
            failed += 1

        elif entry.result.type == "canceled":
            log.warning(f"Canceled: {filename}")
            results.append({
                "file": filename, "sermon_id": None,
                "status": "canceled"
            })
            failed += 1

        elif entry.result.type == "expired":
            log.warning(f"Expired: {filename}")
            results.append({
                "file": filename, "sermon_id": None,
                "status": "expired"
            })
            failed += 1

    # Summary
    log.info(f"\n{'='*60}")
    log.info(f"BATCH RESULTS PROCESSED")
    log.info(f"{'='*60}")
    log.info(f"Succeeded: {succeeded}")
    log.info(f"Failed: {failed}")
    log.info(f"Total cost (batch rate): ${total_cost:.4f}")
    log.info(f"Equivalent standard rate: ${total_cost * 2:.4f}")
    log.info(f"Saved: ${total_cost:.4f} (50% batch discount)")

    # Save batch report
    report_path = BATCH_DIR / f"{batch_id}_report.json"
    with open(report_path, "w") as f:
        json.dump({
            "batch_id": batch_id,
            "preacher": preacher,
            "total_results": succeeded + failed,
            "succeeded": succeeded,
            "failed": failed,
            "total_cost_usd": round(total_cost, 4),
            "equivalent_standard_cost_usd": round(total_cost * 2, 4),
            "savings_usd": round(total_cost, 4),
            "results": results
        }, f, indent=2)
    log.info(f"Batch report: {report_path}")


# ---------------------------------------------------------------------------
# Embed (identical to pipeline.py)
# ---------------------------------------------------------------------------
def embed_units(units: list[dict]) -> list[list[float]]:
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
# Ingest (identical to pipeline.py)
# ---------------------------------------------------------------------------
def ensure_preacher(preacher_name: str, is_canonical: bool = False) -> str:
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


# UUID matcher for sniffing whether the batch custom_id maps to an existing
# sermon row. weekly_ingest names submission files <sermon_id>.txt where
# sermon_id is the row's UUID — for those, we should UPDATE the existing
# row, not INSERT a duplicate. Sermonindex/canonical submissions use slug
# filenames and continue to take the INSERT path.
_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I
)


def ingest_sermon(
    decomposition: dict,
    preacher_id: str,
    embeddings: list[list[float]],
    raw_transcript: Optional[str] = None,
    existing_sermon_id: Optional[str] = None,
) -> str:
    sb = get_supabase()
    pipeline_meta = decomposition.get("_pipeline", {})
    units = decomposition.get("units", [])

    if len(embeddings) != len(units):
        raise ValueError(
            f"Embedding count ({len(embeddings)}) doesn't match "
            f"unit count ({len(units)})"
        )

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

    # UPSERT: if the caller knows an existing sermon row to update (because
    # the batch was launched against existing audio-having rows), UPDATE that
    # row in place. Otherwise INSERT a new row (sermonindex/canonical path).
    if existing_sermon_id and _UUID_RE.match(existing_sermon_id):
        # Clear out any prior decomp children so we don't collide on the
        # unit_index unique constraint when inserting fresh units below.
        sb.table("units").delete().eq("sermon_id", existing_sermon_id).execute()
        sb.table("sermon_artifacts").delete().eq("sermon_id", existing_sermon_id).execute()
        # Don't overwrite audio_url/slug/hosted_audio_url — those are upstream
        # fields that came from the ingest adapter, not from decomposition.
        update_fields = {k: v for k, v in sermon_data.items()
                         if k not in ("preacher_id",)}  # also keep preacher stable
        sb.table("sermons").update(update_fields).eq("id", existing_sermon_id).execute()
        sermon_id = existing_sermon_id
        log.info(f"Updated existing sermon: {decomposition.get('title')} ({sermon_id})")
    else:
        result = sb.table("sermons").insert(sermon_data).execute()
        sermon_id = result.data[0]["id"]
        log.info(f"Inserted sermon: {decomposition.get('title')} ({sermon_id})")

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

        for move in unit.get("biblical_theological_moves", []) or []:
            bt_type = sanitize_enum(
                move.get("type"),
                VALID_BT_TYPES, "BT move type", ctx
            )
            if bt_type is None:
                continue
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
# CLI
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(
        description="Shepherd's Guild — Sermon Decomposition Pipeline v3.1 (Batch Mode)"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # --- submit ---
    p_submit = subparsers.add_parser(
        "submit", help="Submit a folder of sermons as a batch"
    )
    p_submit.add_argument("folder", type=Path,
                          help="Folder containing .txt or sermonindex .json files")
    p_submit.add_argument("--preacher", required=False,
                          help="Preacher name (required for .txt, auto-detected for .json)")
    p_submit.add_argument("--canonical", action="store_true",
                          help="Mark as Guild Hall canonical preacher")
    p_submit.add_argument("--dry-run", action="store_true",
                          help="When processing results, skip embed and ingest")

    # --- status ---
    p_status = subparsers.add_parser(
        "status", help="Check status of a batch"
    )
    p_status.add_argument("batch_id", type=str, help="Batch ID")
    p_status.add_argument("--wait", action="store_true",
                          help="Poll until batch completes")
    p_status.add_argument("--interval", type=int, default=60,
                          help="Polling interval in seconds (default: 60)")

    # --- process ---
    p_process = subparsers.add_parser(
        "process", help="Process completed batch results"
    )
    p_process.add_argument("batch_id", type=str, help="Batch ID")
    p_process.add_argument("--preacher", required=False,
                           help="Preacher name (override manifest)")
    p_process.add_argument("--canonical", action="store_true",
                           help="Mark as Guild Hall canonical preacher")
    p_process.add_argument("--dry-run", action="store_true",
                           help="Save decomposed JSON only — skip embed and ingest")

    # --- list ---
    p_list = subparsers.add_parser(
        "list", help="List recent batches"
    )
    p_list.add_argument("--limit", type=int, default=10,
                        help="Number of batches to list (default: 10)")

    args = parser.parse_args()

    if args.command == "submit":
        if not args.folder.is_dir():
            log.error(f"Not a directory: {args.folder}")
            sys.exit(1)
        batch_id = submit_batch(args.folder, args.preacher)
        if batch_id:
            log.info(f"\nNext steps:")
            log.info(f"  Check status:    python pipeline_batch.py status {batch_id}")
            log.info(f"  Wait + process:  python pipeline_batch.py status {batch_id} --wait")
            log.info(f"  Process results: python pipeline_batch.py process {batch_id}"
                     f"{' --canonical' if args.canonical else ''}"
                     f"{' --dry-run' if args.dry_run else ''}")

    elif args.command == "status":
        check_status(args.batch_id, wait=args.wait, poll_interval=args.interval)

    elif args.command == "process":
        # First verify the batch is complete
        batch = check_status(args.batch_id)
        if batch.processing_status != "ended":
            log.error(
                f"Batch is still {batch.processing_status}. "
                f"Use 'status --wait' to wait for completion first."
            )
            sys.exit(1)
        process_batch_results(
            args.batch_id, args.preacher,
            is_canonical=args.canonical, dry_run=args.dry_run
        )

    elif args.command == "list":
        list_batches(args.limit)


if __name__ == "__main__":
    main()
