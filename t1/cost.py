"""Documented T1 vs T2 cost model (USD, mid-2026 public list prices)."""

from __future__ import annotations

from typing import Any, Iterable, Optional

# T2 path — matches pipeline-README.md (March 2026) and current weekly ingest.
T2_DECOMPOSE_USD = (0.20, 0.40)  # Anthropic Sonnet batch/sync per typical sermon
T2_VOYAGE_USD = 0.01             # unit embeddings for a full decompose graph
T2_HAIKU_ARTIFACTS_USD = 0.03    # 5 congregant resources; not required for T1
T2_ASSEMBLYAI_STT_PER_HOUR = 0.15  # Universal-2 async; Universal-3.5 Pro is ~$0.21/hr

# AssemblyAI chaptering investigation (why it is NOT the default T1 chunker):
# - auto_chapters is deprecated, Universal-2 only, +$0.08/hr, removed 2026-09-15
# - replacement is LLM Gateway (Claude/GPT) billed as tokens — that's T2-class spend
# - chapters require audio + STT first (~$0.10–0.14 for a 40-min sermon)
# - text-first corpora (Ligonier/RC Sproul pages, church site HTML) skip STT
ASSEMBLYAI_AUTO_CHAPTERS_PER_HOUR = 0.08

# Voyage 3.5 list: $0.06 / 1M tokens. A 6k-word sermon ≈ 8k tokens.
VOYAGE_USD_PER_MTOK = 0.06

T1_COST_MODEL = {
    "tier": "T1",
    "intent": "cents per sermon (or $0) for structure + a searchable index",
    "default_apis": [],
    "optional_apis": {
        "voyage.embed": "only with --embed and VOYAGE_API_KEY",
        "assemblyai.transcribe": "T0 only, when no source text exists",
    },
    "never_called_at_t1": [
        "anthropic.messages (Sonnet decompose)",
        "anthropic.messages (Haiku artifacts)",
        "anthropic Message Batches API",
    ],
    "usd_per_sermon": {
        "t1_text_keyword": 0.0,
        "t1_text_plus_voyage": "~$0.0005",
        "t1_if_stt_already_paid_at_t0": 0.0,
        "t2_decompose_plus_embed": "$0.21–0.41",
    },
    "assemblyai_chaptering_verdict": (
        "Rejected as the default T1 chunker. auto_chapters is deprecated "
        "(sunset 2026-09-15), requires paid STT, does not work on text-only "
        "sources, and the documented replacement is an LLM Gateway call. "
        "Local heading/discourse/window chunking meets the cents/sermon intent."
    ),
}


def estimate_voyage_usd(char_count: int, chapter_count: int) -> float:
    """Rough token estimate: ~4 chars/token, plus a little overhead per chapter."""
    tokens = (char_count / 4.0) + (chapter_count * 8)
    return round((tokens / 1_000_000.0) * VOYAGE_USD_PER_MTOK, 6)


def estimate_t1_cost(
    *,
    has_source_text: bool,
    embed: bool,
    char_count: int = 0,
    chapter_count: int = 0,
    audio_duration_sec: Optional[int] = None,
) -> dict[str, Any]:
    apis: list[str] = []
    usd = 0.0
    notes: list[str] = []

    if not has_source_text:
        hours = (audio_duration_sec or 40 * 60) / 3600.0
        stt = round(hours * T2_ASSEMBLYAI_STT_PER_HOUR, 4)
        usd += stt
        apis.append("assemblyai.transcribe")
        notes.append(
            f"T0 STT estimated at ${stt:.3f} "
            f"({hours * 60:.0f} min × ${T2_ASSEMBLYAI_STT_PER_HOUR}/hr). "
            "T1 itself does not submit this job; use weekly_ingest / sermon scraper."
        )
    else:
        notes.append("Source text present — transcription skipped (no AssemblyAI call).")

    if embed:
        v = estimate_voyage_usd(char_count, chapter_count)
        usd += v
        apis.append("voyage.embed")
        notes.append(f"Optional Voyage chapter embeddings ≈ ${v:.5f}.")
    else:
        notes.append("Keyword inverted index only — $0 embeddings.")

    notes.append("Anthropic decompose not called.")
    return {
        "usd_estimate": round(usd, 6),
        "apis_called": apis,
        "notes": notes,
        "vs_t2_midpoint_usd": 0.31,
    }


def estimate_t2_cost(audio_duration_sec: Optional[int] = None) -> dict[str, Any]:
    stt = 0.0
    if audio_duration_sec:
        stt = round((audio_duration_sec / 3600.0) * T2_ASSEMBLYAI_STT_PER_HOUR, 4)
    low = T2_DECOMPOSE_USD[0] + T2_VOYAGE_USD + stt
    high = T2_DECOMPOSE_USD[1] + T2_VOYAGE_USD + stt
    return {
        "usd_range": [round(low, 3), round(high, 3)],
        "components": {
            "anthropic_decompose": list(T2_DECOMPOSE_USD),
            "voyage_unit_embeddings": T2_VOYAGE_USD,
            "assemblyai_stt_if_needed": stt,
        },
        "notes": [
            "T2 is the existing production path (pipeline.py / pipeline_batch.py).",
            "Haiku artifacts (~$0.03) are extra and not required to store the unit graph.",
        ],
    }


def summarize_run_costs(per_sermon: Iterable[dict[str, Any]]) -> dict[str, Any]:
    items = list(per_sermon)
    return {
        "sermons": len(items),
        "t1_usd_total": round(sum(x.get("usd_estimate") or 0 for x in items), 6),
        "apis_called": sorted({
            api for x in items for api in (x.get("apis_called") or [])
        }),
        "t2_would_have_cost_usd": estimate_t2_cost()["usd_range"],
    }
