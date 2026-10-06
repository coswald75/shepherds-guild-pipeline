"""Gimme da quotes! filter: keep real quotations of outside (non-biblical) sources only.

Code-level rules (reliable, explainable; each returns a reason):
  1. author is a biblical person (Paul, Jesus, Moses...)          -> Scripture
  2. work is a Bible book reference ("Philippians 3", "1 Timothy") -> Scripture
  3. an UNATTRIBUTED line introduced by a Bible reference just before it in the transcript
     ("in Matthew 7:13, he'll state...", "Continuing on from Philippians 3, ...") -> Scripture
  4. an attributed line that OPENS with its own author's name ("John Calvin wrote a commentary on...",
     "John Piper, took him 8 years...")
     -> a remark about the author, not his words
The preacher's own narration / invented lines can't be caught reliably in code; the extraction prompt excludes them.
"""
from __future__ import annotations
import re
from .titles import REF, _BOOKS

BIBLE_PEOPLE = {"paul", "saul of tarsus", "jesus", "jesus christ", "christ", "the lord", "god", "moses", "david", "solomon",
                "isaiah", "jeremiah", "ezekiel", "daniel", "peter", "simon peter", "john the baptist", "james", "jude", "luke",
                "matthew", "mark", "the psalmist", "the prophet", "the apostle", "the apostle paul", "apostle paul",
                "the apostle peter", "the apostle john", "the author of hebrews", "the preacher (ecclesiastes)", "nehemiah", "ezra"}
_REF_RE = re.compile(REF, re.I)
_WORK_BOOK = re.compile(rf"^(?:[1-3]\s?)?(?:{_BOOKS})(?:\s+\d|\s*\(|\s*$)", re.I)


def bible_person(name) -> bool:
    n = (name or "").strip().lower()
    return bool(n) and (n in BIBLE_PEOPLE or re.sub(r"^(?:the\s+)?apostle\s+", "", n) in BIBLE_PEOPLE)


def why_excluded(q: dict, raw: str | None = None, pos: int | None = None) -> str | None:
    a = (q.get("author") or "").strip(); w = (q.get("work") or "").strip(); text = q.get("text") or ""
    if bible_person(a): return "Scripture (biblical author)"
    if w and _WORK_BOOK.match(w): return "Scripture (work is a Bible reference)"
    if not q.get("attributed") and raw is not None and pos is not None and pos >= 0:
        # unattributed only: with a named outside author, a nearby reference is just context (Augustine on Romans 13)
        m = None
        for m in _REF_RE.finditer(raw[max(0, pos - 110):pos]): pass
        if m: return f"Scripture (introduced by {m.group(0).strip()})"
    toks = re.findall(r"[A-Za-z]{3,}", a)
    if q.get("attributed") and toks and re.match(rf"^\W*(?:{re.escape(a)}|{re.escape(toks[-1])})\b", text, re.I):
        return "remark about the author, not a quotation"   # line opens with his name: "John Calvin wrote a commentary..."
    return None
