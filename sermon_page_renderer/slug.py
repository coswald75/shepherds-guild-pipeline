"""
Slug generation for churches and sermons.

Pure functions, no I/O — easy to unit-test and reuse from both runtime
rendering and the one-shot slug backfill script.

Rules (from Architecture — Sermon Page Renderer.md):
  - Lowercase, ASCII-only, max 60 chars
  - Sermon: kebab-case title + ISO date suffix (e.g. "growing-in-christ-2026-02-22")
  - Church: kebab-case name (e.g. "providence-community-church")
"""

from __future__ import annotations

import re
import unicodedata
from datetime import date
from typing import Optional

MAX_SLUG_LEN = 60

_NON_ALNUM = re.compile(r"[^a-z0-9]+")
_MULTI_DASH = re.compile(r"-+")


def slugify(text: str, max_len: int = MAX_SLUG_LEN) -> str:
    """
    Convert arbitrary text to a kebab-case, ASCII-only slug.

    - Unicode normalized (NFKD) then ASCII-stripped to remove diacritics
    - Lowercased
    - Non-alphanumerics collapsed to a single hyphen
    - Trimmed; truncated at a hyphen boundary when reasonable
    """
    if not text:
        return ""
    normalized = unicodedata.normalize("NFKD", text)
    ascii_only = normalized.encode("ascii", "ignore").decode("ascii")
    lowered = ascii_only.lower()
    hyphenated = _NON_ALNUM.sub("-", lowered)
    collapsed = _MULTI_DASH.sub("-", hyphenated).strip("-")

    if len(collapsed) <= max_len:
        return collapsed

    truncated = collapsed[:max_len]
    # Prefer to cut at a hyphen boundary so we don't end mid-word, but only
    # if doing so doesn't lose too much of the slug.
    last_dash = truncated.rfind("-")
    if last_dash >= max_len // 2:
        truncated = truncated[:last_dash]
    return truncated.strip("-")


def church_slug(name: str) -> str:
    """Slug for a church (e.g. 'Providence Community Church' → 'providence-community-church')."""
    return slugify(name or "")


def sermon_slug(title: Optional[str], sermon_date: Optional[date]) -> str:
    """
    Slug for a sermon. Title kebab-cased; ISO date suffix when present.

      ('Growing in Christ', date(2026, 2, 22)) → 'growing-in-christ-2026-02-22'
      ('Untitled', None)                       → 'untitled'

    Always returns something non-empty when given a non-empty title OR a date.
    """
    title_base = slugify(title or "")
    if sermon_date is None:
        return title_base or "untitled-sermon"

    date_part = sermon_date.isoformat()  # YYYY-MM-DD
    if not title_base:
        return date_part

    # Reserve room for the date suffix so the combined slug fits in MAX_SLUG_LEN.
    reserve = len(date_part) + 1  # +1 for the separating hyphen
    max_title_len = MAX_SLUG_LEN - reserve
    if max_title_len < 1:
        # Pathological: the date itself is longer than the limit. Return just the date.
        return date_part
    if len(title_base) > max_title_len:
        title_base = slugify(title or "", max_len=max_title_len)
    return f"{title_base}-{date_part}"


_TRAILING_DATE = re.compile(r"-\d{4}-\d{2}-\d{2}$")


def slug_to_url_segment(slug: str) -> str:
    """
    Drop a trailing ISO-date suffix when composing a URL that already carries
    year/month in its path. The DB slug stays date-suffixed (uniqueness), but
    the readable URL path component does not duplicate the date.

      'growing-in-christ-2026-02-22' → 'growing-in-christ'
      'growing-in-christ'            → 'growing-in-christ'
    """
    return _TRAILING_DATE.sub("", slug or "")


def uniquify_slug(slug: str, existing: set[str]) -> str:
    """
    Append a numeric suffix to disambiguate a slug from an existing set.

      uniquify_slug('foo', set())                       → 'foo'
      uniquify_slug('foo', {'foo'})                     → 'foo-2'
      uniquify_slug('foo', {'foo', 'foo-2'})            → 'foo-3'

    The suffix is bounded by MAX_SLUG_LEN — if appending the counter pushes
    the slug past the limit, the base is trimmed accordingly.
    """
    if slug not in existing:
        return slug
    n = 2
    while True:
        suffix = f"-{n}"
        base = slug
        if len(base) + len(suffix) > MAX_SLUG_LEN:
            base = base[: MAX_SLUG_LEN - len(suffix)].rstrip("-")
        candidate = f"{base}{suffix}"
        if candidate not in existing:
            return candidate
        n += 1
