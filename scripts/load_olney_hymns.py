"""
Load the extracted Olney Hymns into Supabase + generate Voyage embeddings.

Reads the JSON produced by extract_olney_hymns.py, upserts each hymn into
the `hymns` table (idempotent on source+book+number), then generates a
single Voyage embedding per hymn. Embedding input combines title, theme,
scripture_anchor, and full_text — strong signal for both topical and
biblical semantic retrieval.

Usage:
    python3 scripts/extract_olney_hymns.py olneyhymns.pdf > /tmp/olney_hymns.json
    python3 scripts/load_olney_hymns.py /tmp/olney_hymns.json
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from dotenv import load_dotenv

load_dotenv(REPO_ROOT / ".env", override=True)

import voyageai  # noqa: E402
from supabase import create_client  # noqa: E402

VOYAGE_MODEL = "voyage-3.5"
VOYAGE_DIMENSIONS = 1024
EMBED_BATCH_SIZE = 64
SOURCE = "olney_hymns_1779"


def main() -> int:
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} <hymns.json>", file=sys.stderr)
        return 2

    hymns = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    print(f"Loaded {len(hymns)} hymns from JSON")

    sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])
    voyage = voyageai.Client(api_key=os.environ["VOYAGE_API_KEY"])

    # --- 1. Upsert rows (without embeddings) ----------------------------------
    rows = [
        {
            "source": SOURCE,
            "book": h["book"],
            "number": h["number"],
            "author": h["author"] or "Unknown",
            "meter": h["meter"],
            "theme": h["theme"],
            "scripture_anchor": h["scripture_anchor"],
            "title": h["title"],
            "full_text": h["full_text"],
        }
        for h in hymns
    ]
    # Upsert in batches (supabase-py has limits on payload size)
    for i in range(0, len(rows), 100):
        chunk = rows[i : i + 100]
        sb.table("hymns").upsert(chunk, on_conflict="source,book,number").execute()
    print(f"Upserted {len(rows)} rows")

    # --- 2. Build embedding input texts ---------------------------------------
    # Seed: title + theme + scripture_anchor + full_text. Each adds a layer of
    # retrieval signal — title for topical matching, theme for category,
    # scripture for biblical overlap, full_text for the actual content.
    def _embed_text(h: dict) -> str:
        parts = []
        if h.get("title"):
            parts.append(h["title"])
        if h.get("theme"):
            parts.append(h["theme"])
        if h.get("scripture_anchor"):
            parts.append(h["scripture_anchor"])
        parts.append(h["full_text"])
        return "\n\n".join(parts)

    inputs = [_embed_text(h) for h in hymns]

    # --- 3. Embed in batches --------------------------------------------------
    print(f"Embedding {len(inputs)} hymns via Voyage {VOYAGE_MODEL}...")
    all_embeddings: list[list[float]] = []
    for i in range(0, len(inputs), EMBED_BATCH_SIZE):
        batch = inputs[i : i + EMBED_BATCH_SIZE]
        result = voyage.embed(
            batch,
            model=VOYAGE_MODEL,
            input_type="document",
            output_dimension=VOYAGE_DIMENSIONS,
        )
        all_embeddings.extend(result.embeddings)
        print(f"  embedded {min(i + EMBED_BATCH_SIZE, len(inputs))}/{len(inputs)}")

    # --- 4. Write embeddings back ---------------------------------------------
    print("Writing embeddings...")
    for h, emb in zip(hymns, all_embeddings):
        sb.table("hymns").update({"embedding": emb}).eq("source", SOURCE).eq(
            "book", h["book"]
        ).eq("number", h["number"]).execute()
    print(f"Done. {len(all_embeddings)} embeddings stored.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
