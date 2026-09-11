"""T1 cheap sermon structure path.

Opt-in companion to the production T2 Anthropic decompose pipeline.
Does not import ``pipeline.py`` (that module pulls Anthropic/Voyage at import time).
"""

from t1.acquire import AcquiredSermon, acquire_path
from t1.chunker import Chapter, chunk_sermon
from t1.cost import T1_COST_MODEL, estimate_t1_cost, estimate_t2_cost
from t1.pipeline import T1Result, structure_sermon

__all__ = [
    "AcquiredSermon",
    "Chapter",
    "T1Result",
    "T1_COST_MODEL",
    "acquire_path",
    "chunk_sermon",
    "estimate_t1_cost",
    "estimate_t2_cost",
    "structure_sermon",
]
