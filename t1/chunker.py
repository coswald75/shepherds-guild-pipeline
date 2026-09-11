"""Cheap T1 chapter/chunk structure.

Default: local heuristics (headings, discourse markers, paragraph windows).
No Anthropic. No AssemblyAI.

If T0 already attached AssemblyAI-style chapter sidecars (start/end ms + text),
those are preferred — they cost nothing at T1 because the STT bill was T0.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any, Optional

from t1.acquire import AcquiredSermon

# Target chapter size when we fall back to windows. ~350-500 words is a
# cheap "light chunk" — enough for keyword/embedding search, far below a
# T2 rhetorical unit graph. Typical 30-min transcript → 8–15 chunks.
WINDOW_WORDS = 400
WINDOW_MIN_WORDS = 80
WINDOW_OVERLAP_WORDS = 30

HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$", re.M)

# Paragraph-initial discourse markers common in evangelical exposition.
DISCOURSE_RE = re.compile(
    r"^(?:"
    r"(?:first|second|third|fourth|fifth|finally|lastly)"
    r"|(?:firstly|secondly|thirdly|fourthly)"
    r"|(?:in conclusion|to conclude|by way of conclusion)"
    r"|(?:now[, ]+(?:let us|we (?:turn|look|come)))"
    r"|(?:let us (?:turn|look|consider|pray))"
    r"|(?:the (?:first|second|third|fourth|next|last) (?:point|word|reason|truth|thing))"
    r")\b",
    re.I,
)


@dataclass
class Chapter:
    chapter_id: str
    title: str
    text: str
    char_start: int
    char_end: int
    start_ms: Optional[int] = None
    end_ms: Optional[int] = None
    source: str = "window"  # sidecar | heading | discourse | window

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _chapter_id(index: int) -> str:
    return f"c{index:02d}"


def _first_line_title(text: str, fallback: str) -> str:
    for line in text.splitlines():
        stripped = line.strip().lstrip("#").strip()
        if stripped:
            return stripped[:120]
    return fallback


def _split_paragraphs(text: str) -> list[tuple[int, int, str]]:
    """Return (start, end, paragraph) spans over the original text."""
    spans: list[tuple[int, int, str]] = []
    for match in re.finditer(r"(?:.+\n?)+", text):
        block = match.group(0)
        # re.finditer on `.+\n?` greedy-runs consecutive non-empty lines;
        # blank lines are the separators because `.` does not match `\n`.
        start, end = match.start(), match.end()
        para = block.strip()
        if para:
            # trim trailing whitespace from the span without losing start
            inner = text[start:end]
            lead = len(inner) - len(inner.lstrip())
            trail = len(inner.rstrip())
            spans.append((start + lead, start + trail, para))
    if not spans and text.strip():
        stripped = text.strip()
        start = text.find(stripped)
        spans.append((start, start + len(stripped), stripped))
    return spans


def _word_count(text: str) -> int:
    return len(re.findall(r"\b[\w']+\b", text))


SENTENCE_RE = re.compile(r".+?(?:[.!?][\"')\]]?\s+|\Z)", re.S)


def _split_sentences(text: str, abs_start: int) -> list[tuple[int, int, str]]:
    """Sentence spans inside a (possibly huge) paragraph, offsets into the sermon."""
    spans: list[tuple[int, int, str]] = []
    for match in SENTENCE_RE.finditer(text):
        sent = match.group(0)
        stripped = sent.strip()
        if not stripped:
            continue
        local = sent.find(stripped)
        start = abs_start + match.start() + local
        end = start + len(stripped)
        spans.append((start, end, stripped))
    if not spans:
        stripped = text.strip()
        if stripped:
            start = abs_start + text.find(stripped)
            spans.append((start, start + len(stripped), stripped))
    return spans


def _units_for_windows(text: str) -> list[tuple[int, int, str]]:
    """Paragraphs, with oversize blocks broken into sentence groups."""
    units: list[tuple[int, int, str]] = []
    for start, end, para in _split_paragraphs(text):
        if _word_count(para) <= WINDOW_WORDS:
            units.append((start, end, para))
            continue
        sentences = _split_sentences(text[start:end], start)
        buf: list[tuple[int, int, str]] = []
        words = 0
        for sent in sentences:
            buf.append(sent)
            words += _word_count(sent[2])
            if words >= WINDOW_WORDS:
                units.append((buf[0][0], buf[-1][1], text[buf[0][0]:buf[-1][1]].strip()))
                buf, words = [], 0
        if buf:
            units.append((buf[0][0], buf[-1][1], text[buf[0][0]:buf[-1][1]].strip()))
    return units


def _from_sidecar(sermon: AcquiredSermon) -> list[Chapter]:
    chapters: list[Chapter] = []
    cursor = 0
    text = sermon.text
    for i, raw in enumerate(sermon.sidecar_chapters, start=1):
        headline = (
            raw.get("headline")
            or raw.get("gist")
            or raw.get("title")
            or f"Chapter {i}"
        )
        body = (raw.get("summary") or raw.get("text") or "").strip()
        start_ms = raw.get("start") if raw.get("start") is not None else raw.get("start_ms")
        end_ms = raw.get("end") if raw.get("end") is not None else raw.get("end_ms")
        try:
            start_ms = int(start_ms) if start_ms is not None else None
        except (TypeError, ValueError):
            start_ms = None
        try:
            end_ms = int(end_ms) if end_ms is not None else None
        except (TypeError, ValueError):
            end_ms = None

        char_start = 0
        char_end = len(text)
        if body:
            found = text.find(body[:80], cursor) if body else -1
            if found >= 0:
                char_start = found
                char_end = found + len(body) if text.startswith(body, found) else found + min(len(body), len(text) - found)
                cursor = char_end
            else:
                # Sidecar summary may not be a verbatim slice — keep offsets unknown-ish
                # but still sequential so the index has a stable span.
                char_start = cursor
                char_end = min(len(text), cursor + max(len(body), 1))
                cursor = char_end
            chunk_text = body
        else:
            chunk_text = text[char_start:char_end] if i == 1 else ""
            if not chunk_text:
                continue

        chapters.append(
            Chapter(
                chapter_id=_chapter_id(i),
                title=str(headline).strip()[:120],
                text=chunk_text,
                char_start=char_start,
                char_end=char_end,
                start_ms=start_ms,
                end_ms=end_ms,
                source="sidecar",
            )
        )
    return chapters


def _from_headings(text: str) -> list[Chapter]:
    matches = list(HEADING_RE.finditer(text))
    if not matches:
        return []
    # Need at least one heading that is not the very first line-only title
    # of a short note — still valid if it divides the body.
    chapters: list[Chapter] = []
    preamble_end = matches[0].start()
    if preamble_end > 0 and text[:preamble_end].strip():
        pre = text[:preamble_end].strip()
        chapters.append(
            Chapter(
                chapter_id=_chapter_id(len(chapters) + 1),
                title=_first_line_title(pre, "Introduction"),
                text=pre,
                char_start=0,
                char_end=preamble_end,
                source="heading",
            )
        )
    for i, match in enumerate(matches):
        start = match.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[start:end].strip()
        if not body:
            continue
        chapters.append(
            Chapter(
                chapter_id=_chapter_id(len(chapters) + 1),
                title=match.group(2).strip()[:120],
                text=body,
                char_start=start,
                char_end=end,
                source="heading",
            )
        )
    return chapters if len(chapters) >= 2 else []


def _from_discourse(text: str) -> list[Chapter]:
    paras = _split_paragraphs(text)
    if len(paras) < 3:
        return []
    starts: list[int] = []
    for idx, (_s, _e, para) in enumerate(paras):
        first = para.split("\n", 1)[0].strip()
        if DISCOURSE_RE.match(first) or DISCOURSE_RE.match(para[:80]):
            starts.append(idx)
    if len(starts) < 2:
        return []
    if starts[0] != 0:
        starts = [0] + starts
    chapters: list[Chapter] = []
    for i, para_idx in enumerate(starts):
        next_idx = starts[i + 1] if i + 1 < len(starts) else len(paras)
        chunk_paras = paras[para_idx:next_idx]
        char_start = chunk_paras[0][0]
        char_end = chunk_paras[-1][1]
        body = text[char_start:char_end].strip()
        if _word_count(body) < 20:
            continue
        chapters.append(
            Chapter(
                chapter_id=_chapter_id(len(chapters) + 1),
                title=_first_line_title(body, f"Movement {len(chapters) + 1}"),
                text=body,
                char_start=char_start,
                char_end=char_end,
                source="discourse",
            )
        )
    return chapters if len(chapters) >= 2 else []


def _from_windows(text: str) -> list[Chapter]:
    paras = _units_for_windows(text)
    if not paras:
        return []
    chapters: list[Chapter] = []
    buf: list[tuple[int, int, str]] = []
    words = 0

    def flush() -> None:
        nonlocal buf, words
        if not buf:
            return
        char_start, char_end = buf[0][0], buf[-1][1]
        body = text[char_start:char_end].strip()
        if not body:
            buf, words = [], 0
            return
        chapters.append(
            Chapter(
                chapter_id=_chapter_id(len(chapters) + 1),
                title=_first_line_title(body, f"Chunk {len(chapters) + 1}"),
                text=body,
                char_start=char_start,
                char_end=char_end,
                source="window",
            )
        )
        # overlap: keep the last short paragraph when the next window starts
        if WINDOW_OVERLAP_WORDS and len(buf) > 1:
            last = buf[-1]
            buf = [last]
            words = _word_count(last[2])
        else:
            buf, words = [], 0

    for span in paras:
        buf.append(span)
        words += _word_count(span[2])
        if words >= WINDOW_WORDS:
            flush()
    if buf:
        # Merge a tiny tail into the previous chapter when possible.
        tail_words = sum(_word_count(p[2]) for p in buf)
        if chapters and tail_words < WINDOW_MIN_WORDS:
            prev = chapters[-1]
            char_end = buf[-1][1]
            prev.text = text[prev.char_start:char_end].strip()
            prev.char_end = char_end
        else:
            flush()
    if not chapters:
        stripped = text.strip()
        start = text.find(stripped)
        chapters.append(
            Chapter(
                chapter_id=_chapter_id(1),
                title=_first_line_title(stripped, "Sermon"),
                text=stripped,
                char_start=start,
                char_end=start + len(stripped),
                source="window",
            )
        )
    return chapters


def chunk_sermon(sermon: AcquiredSermon) -> list[Chapter]:
    """Pick the cheapest credible chapterer that yields structure."""
    if sermon.sidecar_chapters:
        chapters = _from_sidecar(sermon)
        if chapters:
            return chapters
    heading = _from_headings(sermon.text)
    if heading:
        return heading
    discourse = _from_discourse(sermon.text)
    if discourse:
        return discourse
    return _from_windows(sermon.text)
