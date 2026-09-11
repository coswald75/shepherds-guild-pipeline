"""T0/T1 acquire — load source text + durable ids. No paid APIs."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Optional


@dataclass
class AcquiredSermon:
    """Normalized sermon ready for T1 structure."""

    sermon_id: str
    source_path: str
    title: str
    preacher: str
    text: str
    primary_text: Optional[str] = None
    source_kind: str = "txt"  # txt | sermonindex | html | sidecar
    audio_url: Optional[str] = None
    duration_sec: Optional[int] = None
    sidecar_chapters: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def durable_id(self) -> str:
        return self.sermon_id


class _HTMLToText(HTMLParser):
    """Strip tags; keep heading text marked with markdown so the chunker can see it."""

    _BLOCK = {
        "p", "div", "br", "li", "tr", "blockquote", "section", "article",
    }
    _HEADING = {"h1", "h2", "h3", "h4", "h5", "h6"}
    _SKIP = {"script", "style", "noscript", "svg"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._parts: list[str] = []
        self._skip_depth = 0
        self._heading_level: Optional[int] = None

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in self._SKIP:
            self._skip_depth += 1
            return
        if self._skip_depth:
            return
        if tag in self._HEADING:
            self._heading_level = int(tag[1])
            self._parts.append("\n\n")
        elif tag in self._BLOCK:
            self._parts.append("\n\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in self._SKIP and self._skip_depth:
            self._skip_depth -= 1
            return
        if tag in self._HEADING:
            self._heading_level = None
            self._parts.append("\n\n")
        elif tag in self._BLOCK:
            self._parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        text = data.strip()
        if not text:
            return
        if self._heading_level:
            hashes = "#" * min(self._heading_level, 6)
            self._parts.append(f"{hashes} {text}")
        else:
            self._parts.append(text + " ")

    def text(self) -> str:
        raw = "".join(self._parts)
        raw = re.sub(r"[ \t]+", " ", raw)
        raw = re.sub(r"\n{3,}", "\n\n", raw)
        return raw.strip()


def html_to_text(html: str) -> str:
    parser = _HTMLToText()
    try:
        parser.feed(html)
        parser.close()
    except Exception:
        return re.sub(r"<[^>]+>", " ", html)
    return parser.text()


def looks_like_html(text: str) -> bool:
    sample = text.lstrip()[:400].lower()
    return sample.startswith("<") or "<p" in sample or "<h" in sample or "<div" in sample


def slugify(text: str) -> str:
    text = (text or "").lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_]+", "-", text)
    text = re.sub(r"-+", "-", text)
    return (text[:80].strip("-") or "untitled-sermon")


def _stable_id(parts: list[str]) -> str:
    blob = "|".join(p or "" for p in parts)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def _chapters_from_payload(data: dict[str, Any]) -> list[dict[str, Any]]:
    """Accept AssemblyAI-style or local sidecar chapter lists if already present."""
    for key in ("chapters", "auto_chapters", "t1_chapters"):
        value = data.get(key)
        if isinstance(value, list) and value:
            return [c for c in value if isinstance(c, dict)]
    source = data.get("_source") or {}
    if isinstance(source, dict):
        value = source.get("chapters")
        if isinstance(value, list) and value:
            return [c for c in value if isinstance(c, dict)]
    return []


def acquire_text(
    text: str,
    *,
    title: Optional[str] = None,
    preacher: Optional[str] = None,
    source_path: str = "memory",
    source_kind: str = "txt",
    **kwargs: Any,
) -> AcquiredSermon:
    cleaned = text or ""
    if looks_like_html(cleaned):
        cleaned = html_to_text(cleaned)
        source_kind = "html" if source_kind == "txt" else source_kind
    cleaned = cleaned.replace("\x00", "").strip()
    if not cleaned:
        raise ValueError(f"No usable text in {source_path}")

    title = (title or "").strip() or Path(source_path).stem.replace("-", " ").title()
    preacher = (preacher or "").strip() or "Unknown"
    sermon_id = kwargs.pop("sermon_id", None) or _stable_id(
        [preacher, title, cleaned[:240]]
    )
    return AcquiredSermon(
        sermon_id=sermon_id,
        source_path=source_path,
        title=title,
        preacher=preacher,
        text=cleaned,
        source_kind=source_kind,
        **kwargs,
    )


def acquire_path(path: Path, preacher: Optional[str] = None) -> AcquiredSermon:
    """Load a .txt or sermonindex-style .json without calling any API."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(path)

    if path.suffix.lower() == ".json":
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or "transcript" not in data:
            raise ValueError(f"Not a sermon JSON (missing transcript): {path}")
        transcript = data.get("transcript") or ""
        if not isinstance(transcript, str):
            raise ValueError(f"transcript must be a string in {path}")
        refs = data.get("bibleReferences") or []
        primary = None
        if refs and isinstance(refs, list) and isinstance(refs[0], dict):
            primary = refs[0].get("text")
        sidecar = _chapters_from_payload(data)
        source = data.get("_source") or {}
        audio = data.get("audioUrl") or data.get("audio_url")
        if not audio and isinstance(source, dict):
            audio = source.get("audio_url")
        duration = data.get("duration")
        sermon_id = str(data.get("id") or data.get("slug") or "") or None
        return acquire_text(
            transcript,
            title=data.get("title"),
            preacher=preacher or data.get("contributor") or data.get("preacher"),
            source_path=str(path),
            source_kind="sidecar" if sidecar else "sermonindex",
            sermon_id=sermon_id,
            primary_text=primary,
            audio_url=audio,
            duration_sec=int(duration) if duration else None,
            sidecar_chapters=sidecar,
            metadata={
                "description": data.get("description"),
                "topics": data.get("topics") or [],
                "bible_references": refs,
                "source_url": data.get("sourceUrl") or (source.get("source_url") if isinstance(source, dict) else None),
            },
        )

    text = path.read_text(encoding="utf-8")
    title = None
    # Optional YAML-ish header: Title: / Preacher:
    header_preacher = None
    lines = text.splitlines()
    consumed = 0
    for line in lines[:8]:
        m_title = re.match(r"^(?:#\s+)?title:\s*(.+)$", line, re.I)
        m_preach = re.match(r"^(?:#\s+)?preacher:\s*(.+)$", line, re.I)
        if m_title:
            title = m_title.group(1).strip()
            consumed += 1
        elif m_preach:
            header_preacher = m_preach.group(1).strip()
            consumed += 1
        elif line.strip() == "":
            if consumed:
                consumed += 1
            else:
                break
        else:
            break
    if consumed:
        text = "\n".join(lines[consumed:])
    return acquire_text(
        text,
        title=title,
        preacher=preacher or header_preacher,
        source_path=str(path),
        source_kind="txt",
    )


def iter_sermon_files(folder: Path) -> list[Path]:
    """Collect ingestible files; skip indexes and hidden files."""
    folder = Path(folder)
    if folder.is_file():
        return [folder]
    files: list[Path] = []
    for path in sorted(folder.iterdir()):
        if path.name.startswith(".") or path.name.startswith("_"):
            continue
        if path.name.lower() in {"manifest.json", "readme.md", "readme.txt"}:
            continue
        if path.suffix.lower() in {".txt", ".md", ".json"}:
            files.append(path)
    return files
