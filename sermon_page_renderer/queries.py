"""
Query layer for the sermon page renderer.

All Supabase access lives here. The composer and template layers do not
call the Supabase client directly. Pure aggregations (`aggregate_loci`,
`roll_up_*`) are kept in this module too because they're tightly coupled
to the row shape returned by the queries.
"""

from __future__ import annotations

import logging
import os
import re
from datetime import date as date_type, timedelta
from typing import Optional

from dotenv import load_dotenv
from supabase import Client, create_client

load_dotenv(override=True)

log = logging.getLogger("sermon_page_renderer.queries")

_supabase_client: Optional[Client] = None


def get_supabase() -> Client:
    """Lazy service-role Supabase client. Same env vars as the rest of the pipeline."""
    global _supabase_client
    if _supabase_client is None:
        url = os.getenv("SUPABASE_URL")
        key = os.getenv("SUPABASE_KEY")
        if not url or not key:
            raise EnvironmentError("SUPABASE_URL and SUPABASE_KEY must be set")
        _supabase_client = create_client(url, key)
    return _supabase_client


# ---------------------------------------------------------------------------
# Sermon row joined with preacher and church
# ---------------------------------------------------------------------------

def get_sermon(sermon_id: str) -> dict:
    """Sermon row with embedded preacher and church (single() raises on miss)."""
    sb = get_supabase()
    result = (
        sb.table("sermons")
        .select("*, preachers(*, churches(*))")
        .eq("id", sermon_id)
        .single()
        .execute()
    )
    return result.data


# ---------------------------------------------------------------------------
# Units with citations, quotations, bt_moves, illustration_rewrites
# ---------------------------------------------------------------------------

def get_sermon_artifacts(sermon_id: str) -> dict[str, dict]:
    """
    Returns a {artifact_type: artifact_row} dict for the given sermon,
    filtered to any non-skipped status. Once the approval workflow ships,
    tighten this to ("approved", "published") so unreviewed drafts don't
    leak into public pages.
    """
    sb = get_supabase()
    rows = (
        sb.table("sermon_artifacts")
        .select("*")
        .eq("sermon_id", sermon_id)
        .neq("status", "skipped")
        .execute()
        .data
        or []
    )
    return {r["artifact_type"]: r for r in rows}


def get_units_with_decomp(sermon_id: str) -> list[dict]:
    """All units for a sermon, ordered by unit_index, with embedded related rows."""
    sb = get_supabase()
    result = (
        sb.table("units")
        .select(
            "*, citations(*), quotations(*), bt_moves(*), illustration_rewrites(*)"
        )
        .eq("sermon_id", sermon_id)
        .order("unit_index")
        .execute()
    )
    return result.data or []


# ---------------------------------------------------------------------------
# Thesis-unit selection + canonical-preacher neighbors
# ---------------------------------------------------------------------------

# Stopwords for the thesis-unit token-overlap heuristic. Deliberately short.
_STOPWORDS = frozenset({
    "a", "an", "the", "is", "are", "was", "were", "be", "been", "being",
    "of", "to", "in", "on", "at", "for", "with", "by", "and", "or", "but",
    "if", "that", "this", "these", "those", "it", "its", "as", "not", "no",
    "any", "all", "some", "each", "every", "what", "which", "who", "whom",
    "how", "when", "where", "why", "from", "into", "onto", "upon", "under",
    "over", "again", "further", "once", "do", "does", "did", "have", "has",
    "had", "i", "me", "my", "we", "us", "our", "you", "your", "yours",
    "he", "him", "his", "she", "her", "they", "them", "their",
    "must", "only", "very", "just", "so", "than", "then", "there", "here",
    "also", "make", "made", "get", "got",
})


def _tokenize(text: str) -> set[str]:
    return {
        w for w in re.findall(r"[a-z]+", (text or "").lower())
        if w not in _STOPWORDS and len(w) > 2
    }


def find_thesis_unit(sermon: dict, units: list[dict]) -> Optional[dict]:
    """
    Pick the unit whose key_claim most-closely matches the sermon's main_thesis
    (word-overlap, no embedding call). Restricts to theological_claim units first,
    falls back to any unit with a key_claim. Earlier unit_index wins on ties.
    """
    main_thesis = (sermon or {}).get("main_thesis")
    if not main_thesis:
        return None
    thesis_tokens = _tokenize(main_thesis)
    if not thesis_tokens:
        return None

    candidates = [
        u for u in units
        if u.get("rhetorical_function") == "theological_claim" and u.get("key_claim")
    ]
    if not candidates:
        candidates = [u for u in units if u.get("key_claim")]
    if not candidates:
        return None

    def score(u: dict) -> tuple[int, int]:
        overlap = len(thesis_tokens & _tokenize(u["key_claim"]))
        return (overlap, -(u.get("unit_index") or 0))

    return max(candidates, key=score)


def get_canonical_neighbors(
    sermon_id: str,
    thesis_unit_id: Optional[str],
    top_n: int = 5,
    fetch_n: int = 15,
) -> list[dict]:
    """
    Top-N canonical-preacher sermons by cosine distance from the thesis unit.
    Over-fetches and de-dupes a second time by (preacher_id, title) so accidental
    duplicate sermon rows in the corpus don't crowd the top-N.
    """
    if not thesis_unit_id:
        return []
    sb = get_supabase()
    result = sb.rpc(
        "renderer_canonical_neighbors_from_unit",
        {
            "source_unit_id": thesis_unit_id,
            "source_sermon_id": sermon_id,
            "top_n": fetch_n,
        },
    ).execute()
    rows = result.data or []

    seen: set[tuple[str, str]] = set()
    deduped: list[dict] = []
    for row in rows:
        key = (row.get("preacher_id"), (row.get("title") or "").strip().lower())
        if key in seen:
            continue
        seen.add(key)
        deduped.append(row)
        if len(deduped) >= top_n:
            break
    return deduped


# ---------------------------------------------------------------------------
# Three-sermon arc — N sermons by same preacher immediately preceding this one
# ---------------------------------------------------------------------------

def get_three_sermon_arc(sermon: dict, n: int = 3) -> list[dict]:
    """
    The n sermons that precede this one by date, from the same preacher.
    Returns [] when fewer than n prior sermons exist (template shows
    'not enough data yet').
    """
    sermon_date = sermon.get("date")
    preacher_id = sermon.get("preacher_id")
    sermon_id = sermon.get("id")
    if not sermon_date or not preacher_id or not sermon_id:
        return []

    sb = get_supabase()
    result = (
        sb.table("sermons")
        .select("id, title, slug, date, primary_text, series_name, main_thesis")
        .eq("preacher_id", preacher_id)
        .neq("id", sermon_id)
        .not_.is_("date", "null")
        .lt("date", sermon_date)
        .order("date", desc=True)
        .limit(n)
        .execute()
    )
    rows = result.data or []
    if len(rows) < n:
        return []
    return list(reversed(rows))  # oldest first for arc display


# ---------------------------------------------------------------------------
# Prior pastor references — same preacher, same book+chapter, outside ±90 days
# ---------------------------------------------------------------------------

_BOOK_CHAPTER_RE = re.compile(
    r"^\s*((?:\d\s+)?[A-Za-z]+(?:\s[A-Za-z]+)*?)\s+(\d+)",
    re.UNICODE,
)


def parse_passage_ref(text: Optional[str]) -> Optional[tuple[str, int]]:
    """
    Extract (book, chapter) from a primary_text reference.

      'Ephesians 4:11–16'   → ('Ephesians', 4)
      '1 John 3:16'         → ('1 John', 3)
      'Psalm 23'            → ('Psalm', 23)
      None / unparseable    → None
    """
    if not text:
        return None
    m = _BOOK_CHAPTER_RE.match(text)
    if not m:
        return None
    return (m.group(1).strip(), int(m.group(2)))


def get_prior_pastor_refs(sermon: dict, exclusion_days: int = 90) -> list[dict]:
    """
    Sermons by the same preacher on the same book+chapter as this sermon,
    outside a ±exclusion_days window. Most-recent first.
    """
    parsed = parse_passage_ref(sermon.get("primary_text"))
    preacher_id = sermon.get("preacher_id")
    sermon_id = sermon.get("id")
    if not parsed or not preacher_id or not sermon_id:
        return []
    book, chapter = parsed
    prefix = f"{book} {chapter}"

    sb = get_supabase()
    q = (
        sb.table("sermons")
        .select("id, title, slug, date, primary_text, main_thesis")
        .eq("preacher_id", preacher_id)
        .neq("id", sermon_id)
        .ilike("primary_text", f"{prefix}%")
        .order("date", desc=True)
    )

    sermon_date = sermon.get("date")
    if sermon_date:
        ds = (
            date_type.fromisoformat(sermon_date)
            if isinstance(sermon_date, str) else sermon_date
        )
        lower = (ds - timedelta(days=exclusion_days)).isoformat()
        upper = (ds + timedelta(days=exclusion_days)).isoformat()
        q = q.or_(f"date.lt.{lower},date.gt.{upper}")

    result = q.execute()
    return result.data or []


def count_citations_for_book_chapter(
    sermon_id: str, book: str, chapter: int
) -> int:
    """
    Count citations in `sermon_id`'s units whose reference begins with
    'Book Chapter' (matches sub-verses too — 'Eph 4:11', 'Eph 4').
    Used to populate "8 Eph 4 citations" type lines.
    """
    sb = get_supabase()
    prefix = f"{book} {chapter}"
    # Citations join through units, so we filter by units.sermon_id.
    result = (
        sb.table("citations")
        .select("id, reference, units!inner(sermon_id)", count="exact")
        .eq("units.sermon_id", sermon_id)
        .ilike("reference", f"{prefix}%")
        .execute()
    )
    return result.count or 0


# ---------------------------------------------------------------------------
# Pure aggregations
# ---------------------------------------------------------------------------

def aggregate_loci(units: list[dict]) -> list[tuple[str, int]]:
    """[(locus, count), ...] sorted by count desc, then locus asc."""
    counts: dict[str, int] = {}
    for u in units:
        for locus in u.get("doctrinal_loci") or []:
            counts[locus] = counts.get(locus, 0) + 1
    return sorted(counts.items(), key=lambda x: (-x[1], x[0]))


def select_pastoral_correction_unit(units: list[dict]) -> Optional[dict]:
    """
    Q3 cascade:
      1. First `application` unit with `pathos` register AND `Pastoral Theology` locus
      2. First `application` unit with application_specificity = 'concrete'
      3. First `application` unit
    None if no application unit exists.
    """
    application_units = [
        u for u in units if u.get("rhetorical_function") == "application"
    ]
    if not application_units:
        return None

    for u in application_units:
        register = u.get("rhetorical_register") or []
        loci = u.get("doctrinal_loci") or []
        if "pathos" in register and "Pastoral Theology" in loci:
            return u

    for u in application_units:
        if u.get("application_specificity") == "concrete":
            return u

    return application_units[0]


def roll_up_citations(units: list[dict]) -> tuple[list[str], int]:
    """
    Dedupe Bible citations across all units, preserving first-appearance order.
    Returns (ordered_refs, total_count_including_duplicates).
    """
    seen: dict[str, None] = {}
    total = 0
    for u in units:
        for c in u.get("citations") or []:
            ref = (c.get("reference") or "").strip()
            if not ref:
                continue
            total += 1
            if ref not in seen:
                seen[ref] = None
    return (list(seen.keys()), total)


def _unit_rewrite(unit: dict) -> Optional[dict]:
    """
    Normalize PostgREST's illustration_rewrites embed. Because illustration_rewrites.unit_id
    is the PRIMARY KEY (1:1 with units), PostgREST returns a dict or None — but during
    schema evolution it sometimes comes back as a single-element list. Handle both.
    """
    raw = unit.get("illustration_rewrites")
    if not raw:
        return None
    if isinstance(raw, list):
        return raw[0] if raw else None
    return raw


def roll_up_illustrations(units: list[dict]) -> list[dict]:
    """
    Illustration units in order, with type, summary, and rewrite (if any).
    """
    out: list[dict] = []
    for u in units:
        if u.get("rhetorical_function") != "illustration":
            continue
        rewrite = _unit_rewrite(u) or {}
        out.append({
            "unit_index": u.get("unit_index"),
            "illustration_type": u.get("illustration_type"),
            "summary": u.get("summary"),
            "key_claim": u.get("key_claim"),
            "rewrite_title": rewrite.get("title"),
            "rewrite_body": rewrite.get("body"),
        })
    return out


def roll_up_theological_claims(units: list[dict]) -> list[dict]:
    out: list[dict] = []
    for u in units:
        if u.get("rhetorical_function") != "theological_claim":
            continue
        out.append({
            "unit_index": u.get("unit_index"),
            "key_claim": u.get("key_claim") or u.get("summary"),
        })
    return out


def roll_up_quotations(units: list[dict]) -> list[dict]:
    out: list[dict] = []
    for u in units:
        for q in u.get("quotations") or []:
            out.append({
                "unit_index": u.get("unit_index"),
                "text": q.get("text"),
                "attribution": q.get("attribution"),
                "source": q.get("source"),
                "function": q.get("function"),
            })
    return out
