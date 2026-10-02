"""Minimal searchable index for T1 chapters.

Default: keyword inverted index (stdlib only, $0).
Optional: Voyage embeddings when ``--embed`` and ``VOYAGE_API_KEY`` are set.
Never calls Anthropic.
"""

from __future__ import annotations

import math
import os
import re
from collections import Counter, defaultdict
from typing import Any, Iterable, Optional

from t1.chunker import Chapter

TOKEN_RE = re.compile(r"[a-z0-9']{3,}")

STOPWORDS = {
    "the", "and", "for", "that", "this", "with", "from", "you", "your",
    "was", "were", "are", "not", "but", "his", "her", "she", "they",
    "them", "our", "out", "all", "can", "had", "have", "has", "been",
    "what", "when", "who", "how", "why", "will", "would", "there",
    "their", "then", "than", "into", "onto", "about", "over", "after",
    "before", "because", "which", "while", "these", "those", "just",
    "like", "said", "says", "also", "more", "some", "any", "now",
}


def tokenize(text: str) -> list[str]:
    return [t for t in TOKEN_RE.findall(text.lower()) if t not in STOPWORDS]


def chapter_terms(chapter: Chapter, top_n: int = 24) -> list[str]:
    counts = Counter(tokenize(chapter.text))
    return [term for term, _ in counts.most_common(top_n)]


def build_keyword_index(
    sermons: Iterable[dict[str, Any]],
) -> dict[str, Any]:
    """Corpus inverted index: term -> [{sermon_id, chapter_id, tf}]."""
    postings: dict[str, list[dict[str, Any]]] = defaultdict(list)
    sermon_count = 0
    chapter_count = 0
    for sermon in sermons:
        sermon_count += 1
        sid = sermon["sermon_id"]
        for ch in sermon.get("chapters") or []:
            chapter_count += 1
            tokens = tokenize(ch.get("text") or "")
            if not tokens:
                continue
            tf = Counter(tokens)
            n = len(tokens)
            for term, count in tf.items():
                postings[term].append({
                    "sermon_id": sid,
                    "chapter_id": ch.get("chapter_id"),
                    "title": sermon.get("title"),
                    "chapter_title": ch.get("title"),
                    "tf": round(count / n, 6),
                    "count": count,
                })
    df = {term: len(hits) for term, hits in postings.items()}
    return {
        "kind": "keyword",
        "sermon_count": sermon_count,
        "chapter_count": chapter_count,
        "term_count": len(postings),
        "df": df,
        "postings": dict(postings),
    }


def search_index(
    index: dict[str, Any],
    query: str,
    limit: int = 8,
) -> list[dict[str, Any]]:
    terms = tokenize(query)
    if not terms:
        return []
    n_docs = max(1, index.get("chapter_count") or 1)
    df = index.get("df") or {}
    scores: dict[tuple[str, str], dict[str, Any]] = {}
    for term in terms:
        hits = (index.get("postings") or {}).get(term) or []
        idf = math.log((n_docs + 1) / (df.get(term, 0) + 1)) + 1.0
        for hit in hits:
            key = (hit["sermon_id"], hit.get("chapter_id") or "")
            bucket = scores.setdefault(key, {
                "sermon_id": hit["sermon_id"],
                "chapter_id": hit.get("chapter_id"),
                "title": hit.get("title"),
                "chapter_title": hit.get("chapter_title"),
                "score": 0.0,
                "matched_terms": [],
            })
            bucket["score"] += hit.get("tf", 0) * idf
            if term not in bucket["matched_terms"]:
                bucket["matched_terms"].append(term)
    ranked = sorted(scores.values(), key=lambda r: r["score"], reverse=True)
    return ranked[:limit]


def maybe_embed_chapters(
    chapters: list[Chapter],
    enabled: bool,
) -> tuple[Optional[list[list[float]]], list[str], Optional[str]]:
    """Return (vectors, apis_called, skip_reason). Never raises on missing keys."""
    if not enabled:
        return None, [], "embeddings disabled (default; pass --embed to opt in)"
    api_key = os.environ.get("VOYAGE_API_KEY")
    if not api_key:
        return None, [], "VOYAGE_API_KEY not set; keyword index only"
    try:
        import voyageai  # type: ignore
    except ImportError:
        return None, [], "voyageai package not installed; keyword index only"

    texts = [ch.text[:8000] for ch in chapters]
    if not texts:
        return [], [], None
    client = voyageai.Client(api_key=api_key)
    result = client.embed(texts, model="voyage-3.5", input_type="document")
    vectors = [list(v) for v in result.embeddings]
    return vectors, ["voyage.embed"], None
