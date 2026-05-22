"""
Canonical 66-book Bible list + reference normalization.

Used by the scripture-browse surface to map free-text references like
'Romans 8:28' or 'Psalm 23' or 'Gospel of John' into one of the 66
canonical book names. Returns None for non-book strings ('Jesus', 'Paul',
'Mateo', etc.) so callers can skip them.
"""

from __future__ import annotations

import re

OT_BOOKS = [
    "Genesis", "Exodus", "Leviticus", "Numbers", "Deuteronomy",
    "Joshua", "Judges", "Ruth",
    "1 Samuel", "2 Samuel", "1 Kings", "2 Kings",
    "1 Chronicles", "2 Chronicles",
    "Ezra", "Nehemiah", "Esther",
    "Job", "Psalms", "Proverbs", "Ecclesiastes", "Song of Solomon",
    "Isaiah", "Jeremiah", "Lamentations", "Ezekiel", "Daniel",
    "Hosea", "Joel", "Amos", "Obadiah", "Jonah", "Micah",
    "Nahum", "Habakkuk", "Zephaniah", "Haggai", "Zechariah", "Malachi",
]

NT_BOOKS = [
    "Matthew", "Mark", "Luke", "John", "Acts",
    "Romans", "1 Corinthians", "2 Corinthians", "Galatians",
    "Ephesians", "Philippians", "Colossians",
    "1 Thessalonians", "2 Thessalonians",
    "1 Timothy", "2 Timothy", "Titus", "Philemon",
    "Hebrews", "James", "1 Peter", "2 Peter",
    "1 John", "2 John", "3 John", "Jude", "Revelation",
]

BOOKS = OT_BOOKS + NT_BOOKS
BOOK_SET = set(BOOKS)
BOOK_ORDER = {b: i for i, b in enumerate(BOOKS)}

# Common variants seen in the citations table.
SYNONYMS = {
    "Psalm": "Psalms",
    "Song of Songs": "Song of Solomon",
    "Canticles": "Song of Solomon",
}

# Match the longest forms first so '1 John' isn't shadowed by 'John'.
_ALL_FORMS = sorted(BOOKS + list(SYNONYMS), key=len, reverse=True)
_BOOK_PATTERN = re.compile(
    r"^(?:Book of |Gospel of |Letter of |Letter to the )?"
    r"(" + "|".join(re.escape(b) for b in _ALL_FORMS) + r")"
    r"(?=$|[\s:.,;\-0-9])"
)


def canonical_book(text: str | None) -> str | None:
    """Return the canonical book name for a scripture reference, or None.

    'Romans 8:28'       → 'Romans'
    '1 Corinthians 13'  → '1 Corinthians'
    'Psalm 23'          → 'Psalms'
    'Gospel of John 3'  → 'John'
    'Book of Job 1:1'   → 'Job'
    'Jesus'             → None
    'Mateo 5'           → None  (Spanish, ignored)
    """
    if not text:
        return None
    m = _BOOK_PATTERN.match(text.strip())
    if not m:
        return None
    matched = m.group(1)
    return SYNONYMS.get(matched, matched if matched in BOOK_SET else None)


def book_slug(name: str) -> str:
    """'1 Corinthians' → '1-corinthians', 'Song of Solomon' → 'song-of-solomon'."""
    return name.lower().replace(" ", "-")
