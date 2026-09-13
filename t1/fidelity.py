"""T1 cheap fidelity-slice harvest (heuristic, $0).

Keyword / citation / regex diagnosis for a handful of contested axes.
Not Coach. Not a ministry profile. Prefer under-calling over drift claims.

Does not call Anthropic, Voyage, or AssemblyAI.
"""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional

from t1.acquire import acquire_path, iter_sermon_files, slugify

FIDELITY_VERSION = "t1-fidelity-v1"
METHOD = "keyword_citation_heuristic_v1"
COST_USD = 0.0

ATTRIBUTIONS = (
    "historical_stott",
    "all_souls_contemporary",
    "uncertain",
)

# SermonIndex hash ids for the Urbana / Great Commission + 2 Timothy set
# identified on the prior Stott ingest. Used as a high-confidence cue only.
KNOWN_HISTORICAL_STOTT_IDS = frozenset({
    "srW7my7NyrY0mEHS",
    "UePashFDdBWFBE61",
    "j33UOzcFk_HCYQpF",
    "2yarrkVlmM2NkVZa",
    "kP_976RY-CWgXqt4",
    "GAe4bVy5BB0qD9O9",
    "Qv-VCAnJiR1SApEQ",
})

AXIS_META = {
    "A1": {
        "name": "1_timothy_2",
        "title": "A1 — 1 Timothy 2 (women / teach / authority)",
        "bands": (
            "classic_complementarian",
            "soft_hedged",
            "egalitarian_reframing",
            "avoided_or_no_hit",
        ),
        "no_hit": "avoided_or_no_hit",
    },
    "A2": {
        "name": "ephesians_5",
        "title": "A2 — Ephesians 5 (headship / marriage)",
        "bands": (
            "classic_complementarian",
            "soft_hedged",
            "egalitarian_reframing",
            "avoided_or_no_hit",
        ),
        "no_hit": "avoided_or_no_hit",
    },
    "B1": {
        "name": "sovereignty_under_evil",
        "title": "B1/B2 — Sovereignty under evil",
        "bands": (
            "stout_providence",
            "mixed",
            "thinned_freewill",
            "unclear_or_no_hit",
        ),
        "no_hit": "unclear_or_no_hit",
    },
    "B3": {
        "name": "wrath_judgment_hell",
        "title": "B3 — Wrath / judgment / hell",
        "bands": (
            "judicial_retained",
            "hedged",
            "emptied_or_silent",
            "unclear_or_no_hit",
        ),
        "no_hit": "unclear_or_no_hit",
    },
    "B4": {
        "name": "sin_guilt_vs_wound",
        "title": "B4 — Sin: guilt vs wound",
        "bands": (
            "guilt_before_god",
            "mixed",
            "wound_only",
            "unclear_or_no_hit",
        ),
        "no_hit": "unclear_or_no_hit",
    },
    "B5": {
        "name": "exclusivity",
        "title": "B5 — Exclusivity of Christ",
        "bands": (
            "exclusive_hard",
            "hedged",
            "soft_pluralist",
            "unclear_or_no_hit",
        ),
        "no_hit": "unclear_or_no_hit",
    },
    "B6": {
        "name": "annihilation_conditional",
        "title": "B6 — Annihilation / conditional immortality",
        "bands": (
            "traditional_ecp",
            "annihilation_or_conditional",
            "ambiguous",
            "no_hit",
        ),
        "no_hit": "no_hit",
    },
    "B7": {
        "name": "romans_13",
        "title": "B7 — Romans 13 (governing authorities)",
        "bands": (
            "classical_tension",
            "mixed",
            "flat_compliance_only",
            "no_hit",
        ),
        "no_hit": "no_hit",
    },
}

_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.I,
)
_HASH_ID_RE = re.compile(r"^[A-Za-z0-9_-]{10,22}$")
_WS = re.compile(r"\s+")

# ── Evidence helpers ──────────────────────────────────────────────────────


def _quote(text: str, start: int, end: int, pad: int = 72) -> dict[str, Any]:
    q_start = max(0, start - pad)
    q_end = min(len(text), end + pad)
    quote = _WS.sub(" ", text[q_start:q_end]).strip()
    return {
        "quote": quote[:280],
        "char_start": start,
        "char_end": end,
    }


def _score(
    text: str,
    weighted: list[tuple[str, float]],
    *,
    limit: int = 3,
    flags: int = re.I,
) -> tuple[float, list[dict[str, Any]]]:
    total = 0.0
    evidence: list[dict[str, Any]] = []
    for pat, weight in weighted:
        for match in re.finditer(pat, text, flags):
            total += weight
            if len(evidence) < limit:
                evidence.append(_quote(text, match.start(), match.end()))
    return total, evidence


def _near(
    text: str,
    pat_a: str,
    pat_b: str,
    window: int = 180,
) -> list[dict[str, Any]]:
    hits: list[dict[str, Any]] = []
    for ma in re.finditer(pat_a, text, re.I):
        start = max(0, ma.start() - window)
        end = min(len(text), ma.end() + window)
        mb = re.search(pat_b, text[start:end], re.I)
        if mb:
            abs_start = start + mb.start()
            hits.append(_quote(text, min(ma.start(), abs_start), max(ma.end(), start + mb.end())))
    return hits


def _merge_evidence(*groups: Iterable[dict[str, Any]], limit: int = 3) -> list[dict[str, Any]]:
    seen: set[tuple[int, int]] = set()
    out: list[dict[str, Any]] = []
    for group in groups:
        for item in group:
            key = (item.get("char_start", 0), item.get("char_end", 0))
            if key in seen:
                continue
            seen.add(key)
            out.append(item)
            if len(out) >= limit:
                return out
    return out


def _confidence(best: float, second: float, *, floor: float = 0.28, ceiling: float = 0.88) -> float:
    if best <= 0:
        return 0.22
    margin = best - second
    conf = 0.34 + (margin / (best + 1.0)) * 0.40 + min(best, 8) * 0.035
    if margin < 0.9 and second > 0:
        conf = min(conf, 0.52)
    return round(max(floor, min(ceiling, conf)), 3)


def _pick_band(
    scores: dict[str, float],
    evidence_map: dict[str, list[dict[str, Any]]],
    *,
    axis: str,
    no_hit: str,
    min_score: float = 1.6,
    undercall_to: Optional[str] = None,
) -> dict[str, Any]:
    ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    best_label, best = ranked[0] if ranked else (no_hit, 0.0)
    second = ranked[1][1] if len(ranked) > 1 else 0.0
    if best < min_score:
        label = no_hit
        conf = 0.24 if best <= 0 else 0.32
        evidence = _merge_evidence(*evidence_map.values())
    else:
        label = best_label
        # Close races: under-call rather than invent a sharp drift band.
        if undercall_to and second > 0 and (best - second) < 0.9:
            label = undercall_to
        conf = _confidence(best, second)
        evidence = evidence_map.get(label) or _merge_evidence(*evidence_map.values())
    return {
        "axis": axis,
        "name": AXIS_META[axis]["name"],
        "band": label,
        "confidence": conf,
        "hit": label != no_hit,
        "scores": {k: round(v, 3) for k, v in scores.items()},
        "evidence": evidence[:3],
        "provisional": True,
        "method": METHOD,
    }


# ── Attribution ───────────────────────────────────────────────────────────

_MODERN_MARKERS = [
    (r"\bzoom\b", "mentions Zoom"),
    (r"\binstagram\b", "mentions Instagram"),
    (r"\bcovid(?:-?19)?\b", "mentions Covid"),
    (r"\bcoronavirus\b", "mentions coronavirus"),
    (r"\blockdown\b", "mentions lockdown"),
    (r"\bwhatsapp\b", "mentions WhatsApp"),
    (r"\bspotify\b", "mentions Spotify"),
    (r"\btiktok\b", "mentions TikTok"),
    (r"\byoutube\b", "mentions YouTube"),
    (r"\bmeme\b", "mentions a meme"),
    (r"\blivestream\b", "mentions livestream"),
    (r"\bonline service\b", "mentions online service"),
    (r"\b1700 years?\b", "Nicaea 1700th-anniversary language"),
    (r"\bnicene creed\b.{0,80}\b1700\b|\b1700\b.{0,80}\bnicene\b", "Nicaea 1700th framing"),
    (r"\bdonald trump\b", "mentions Donald Trump"),
    (r"\bcrossfit\b", "mentions CrossFit"),
    (r"\bmy big fat greek wedding\b", "contemporary pop-culture illustration"),
]

_HISTORICAL_REGISTER = [
    (r"\bbrethren\b", "oral 'brethren' register"),
    (r"\bbible hours\b", "congress/Urbana 'Bible hours' framing"),
    (r"\bauthorized version\b|\bking james\b", "KJV/AV register"),
    (r"\bbilly graham\b", "contemporary-to-Stott Billy Graham reference"),
    (r"\barchbishop'?s commission\b", "mid-century Anglican commission reference"),
    (r"\bas an anglican clergyman\b", "Stott self-identifies as Anglican clergyman"),
]


def _blob_meta(metadata: dict[str, Any], source_path: str = "") -> dict[str, str]:
    source = metadata.get("_source") if isinstance(metadata.get("_source"), dict) else {}
    audio = (
        metadata.get("audioUrl")
        or metadata.get("audio_url")
        or source.get("audio_url")
        or ""
    )
    url = (
        metadata.get("sourceUrl")
        or metadata.get("source_url")
        or source.get("source_url")
        or ""
    )
    return {
        "id": str(metadata.get("id") or metadata.get("sermon_id") or ""),
        "title": str(metadata.get("title") or ""),
        "audio": str(audio or ""),
        "url": str(url or ""),
        "date": str(metadata.get("date") or ""),
        "created": str(metadata.get("createdAt") or metadata.get("created_at") or ""),
        "method": str(source.get("method") or ""),
        "path": source_path,
        "stem": Path(source_path).stem if source_path else "",
    }


def attribute_sermon(
    *,
    text: str,
    metadata: Optional[dict[str, Any]] = None,
    source_path: str = "",
) -> dict[str, Any]:
    """Return historical_stott | all_souls_contemporary | uncertain with reasons."""
    metadata = metadata or {}
    meta = _blob_meta(metadata, source_path)
    hist: list[str] = []
    contemp: list[str] = []
    sid = meta["id"]
    stem = meta["stem"]

    if sid in KNOWN_HISTORICAL_STOTT_IDS or stem in KNOWN_HISTORICAL_STOTT_IDS:
        hist.append("known Urbana / Great Commission / 2 Timothy SermonIndex id")
    if sid and _HASH_ID_RE.match(sid) and not _UUID_RE.match(sid):
        hist.append(f"SermonIndex-style hash id ({sid})")
    if stem and _HASH_ID_RE.match(stem) and not _UUID_RE.match(stem) and "-" not in stem:
        hist.append(f"hash-id filename ({stem})")
    joined_urls = f"{meta['audio']} {meta['url']}"
    if re.search(r"sermonindex|archive\.org/download/SERMONINDEX", joined_urls, re.I):
        hist.append("SermonIndex / archive.org SERMONINDEX audio")
    title_l = meta["title"].lower()
    if re.search(r"great commission|ii timothy|2 timothy.*(gospel|continue|proclaim|guard|suffer)", title_l):
        hist.append(f"Urbana-set title ({meta['title']})")
    for pat, reason in _HISTORICAL_REGISTER:
        if re.search(pat, text, re.I):
            hist.append(reason)

    if sid and _UUID_RE.match(sid):
        contemp.append(f"UUID scrape id ({sid})")
    if re.search(r"allsouls\.org|media\.allsouls\.org", joined_urls, re.I):
        contemp.append("All Souls media URL")
    if meta["method"] == "sermon_scraper":
        contemp.append("sermon_scraper source")
    if re.search(r"\b20(25|26)\b", meta["date"]):
        contemp.append(f"All Souls date stamp ({meta['date']})")
    if re.search(r"john stott.{0,80}used to work at this church|famous preacher and author who used to work", text, re.I):
        contemp.append("speaker refers to historical Stott in the third person")
    for pat, reason in _MODERN_MARKERS:
        if re.search(pat, text, re.I):
            contemp.append(reason)

    # Scrape-date createdAt on SermonIndex rows is not a sermon date — ignore it
    # unless All Souls URL is also present.
    h, c = len(set(hist)), len(set(contemp))
    if h >= 2 and c == 0:
        label, conf = "historical_stott", min(0.97, 0.72 + 0.05 * h)
    elif c >= 2 and h == 0:
        label, conf = "all_souls_contemporary", min(0.97, 0.70 + 0.04 * c)
    elif h >= 3 and c <= 1:
        label, conf = "historical_stott", 0.8
    elif c >= 3 and h <= 1:
        label, conf = "all_souls_contemporary", 0.78
    elif h == 0 and c == 0:
        label, conf = "uncertain", 0.3
    else:
        label, conf = "uncertain", 0.45

    reasons = []
    if label == "historical_stott":
        reasons = list(dict.fromkeys(hist))
    elif label == "all_souls_contemporary":
        reasons = list(dict.fromkeys(contemp))
    else:
        reasons = [
            "mixed or thin signals",
            *(f"historical: {r}" for r in hist[:4]),
            *(f"contemporary: {r}" for r in contemp[:4]),
        ]
    return {
        "slug": stem or slugify(meta["title"] or sid or "sermon"),
        "sermon_id": sid or None,
        "title": meta["title"] or stem,
        "attribution": label,
        "confidence": round(conf, 3),
        "reasons": reasons[:8],
        "signals": {
            "historical": list(dict.fromkeys(hist)),
            "contemporary": list(dict.fromkeys(contemp)),
        },
        "source_path": source_path or None,
        "method": METHOD,
    }


# ── Axis patterns ─────────────────────────────────────────────────────────

_A1_GATE = [
    (r"\b1(?:st)?\s*tim(?:othy)?\s*2\b", 3.0),
    (r"\bfirst\s+timothy\s+(?:chapter\s+)?(?:two|2)\b", 3.0),
    (r"\btimothy\s+2\s*:\s*(?:8|9|10|11|12|13|14|15)\b", 3.2),
    (r"\bwom[ae]n\b.{0,40}\b(?:teach|authority|silent|silence|quiet)\b", 2.2),
    (r"\b(?:teach|authority|silent|silence)\b.{0,40}\bwom[ae]n\b", 2.2),
    (r"\bchildbearing\b", 2.4),
    (r"\bcreation order\b", 2.6),
    (r"\badam\b.{0,50}\beve\b.{0,40}\b(?:first|created|deceived|formed)\b", 2.0),
]

_A1_CLASSIC = [
    (r"\b(?:do|does|must)\s+not\s+(?:permit|allow|let)\s+(?:a\s+)?wom[ae]n\s+to\s+teach\b", 3.0),
    (r"\bwom[ae]n\s+(?:should|must|are)\s+not\s+(?:teach|have authority|usurp)\b", 3.0),
    (r"\bI\s+(?:do\s+)?not\s+permit\s+a\s+woman\s+to\s+teach\b", 3.2),
    (r"\bauthority\s+over\s+(?:a\s+)?man\b", 2.4),
    (r"\bshe\s+must\s+be\s+silent\b|\bwomen\s+(?:are\s+to\s+)?remain\s+silent\b", 2.6),
    (r"\bcomplementarian\b", 2.0),
]

_A1_HEDGE = [
    (r"\bcontroversial\b.{0,40}\b(?:passage|text|verses?|women)\b", 2.0),
    (r"\bwe\s+need\s+to\s+be\s+careful\b", 1.6),
    (r"\bit'?s\s+complicated\b", 1.6),
    (r"\bhard\s+passage\b|\bdifficult\s+(?:text|passage)\b", 1.6),
]

_A1_EGAL = [
    (r"\bwom[ae]n\s+(?:can|may|should|must)\s+(?:also\s+)?(?:teach|preach|lead)\b", 2.8),
    (r"\bcultural(?:ly)?\s+(?:bound|conditioned|specific)\b.{0,40}\b(?:women|gender|teach)\b", 2.6),
    (r"\bnot\s+about\s+gender\s+roles\b", 2.8),
    (r"\begalitarian\b", 2.2),
    (r"\bpaul\s+was\s+(?:only\s+)?addressing\s+(?:a\s+)?local\b", 2.4),
]

_A2_GATE = [
    (r"\beph(?:esians)?\s*5(?:\s*:\s*2[1-9]|\s*:\s*3[0-3])?\b", 3.0),
    (r"\bephesians\s+chapter\s+five\b", 2.8),
    (r"\bwives?,?\s+submit\b", 3.0),
    (r"\bhusbands?,?\s+love\s+your\s+wives\b", 2.6),
    (r"\bheadship\b", 2.8),
    (r"\bhusband\s+is\s+the\s+head\b", 3.0),
    (r"\bchrist\s+(?:and|is\s+head\s+of)\s+the\s+church\b.{0,40}\b(?:wife|husband|marriage)\b", 2.4),
]

_A2_CLASSIC = [
    (r"\bwives?\s+(?:are\s+to|should|must|ought\s+to)\s+submit\b", 3.0),
    (r"\bhusband\s+is\s+the\s+head\s+of\s+the\s+wife\b", 3.0),
    (r"\bheadship\b.{0,40}\b(?:home|marriage|husband)\b", 2.4),
    (r"\bas\s+the\s+church\s+submits?\s+to\s+christ\b", 2.6),
]

_A2_HEDGE = [
    (r"\bmutual(?:ly)?\s+submi", 2.4),
    (r"\bsubmit(?:ting)?\s+to\s+one\s+another\b", 2.2),
    (r"\bnot\s+about\s+domination\b|\bnot\s+a\s+license\s+to\s+(?:rule|dominate)\b", 2.2),
    (r"\bthis\s+is(?:n't| not)\s+about\s+power\b", 2.0),
]

_A2_EGAL = [
    (r"\bhead\s+means\s+source\b|\bkephale\b.{0,30}\bsource\b", 3.0),
    (r"\bno\s+(?:hierarchy|hierarchical)\s+(?:in\s+)?(?:marriage|the home)\b", 2.8),
    (r"\bcultural\b.{0,40}\b(?:wives|submit|household\s+code)\b", 2.4),
    (r"\bequal(?:ity)?\s+in\s+(?:the\s+)?(?:home|marriage)\b.{0,30}\bno\s+role\b", 2.2),
]

_B1_GATE = [
    (r"\bprovidence\b", 2.4),
    (r"\b(?:god|he)\s+(?:ordain(?:ed|s)?|sovereign)\b", 2.2),
    (r"\bwhere\s+was\s+god\b", 3.0),
    (r"\bwhy\s+(?:does|did)\s+god\s+(?:allow|let|permit)\b", 2.8),
    (r"\btheodicy\b", 2.8),
    (r"\bfree\s+will\b", 1.8),
    (r"\bgod\s+would\s+never\b", 2.6),
    (r"\b(?:suffering|tragedy|injustice|evil)\b.{0,50}\b(?:god|lord|providence)\b", 2.0),
    (r"\bgod\b.{0,40}\b(?:suffering|tragedy|injustice|evil)\b", 1.6),
    (r"\bmeant\s+it\s+for\s+good\b", 2.4),
    (r"\bworks?\s+(?:all\s+things\s+)?together\s+for\s+(?:the\s+)?good\b", 2.4),
]

_B1_STOUT = [
    (r"\bgod\s+(?:is\s+)?sovereign\s+(?:even\s+)?(?:over|in)\b", 3.0),
    (r"\b(?:he|god)\s+ordain(?:ed|s)\b", 2.8),
    (r"\bprovidence\b", 2.2),
    (r"\bmeant\s+it\s+for\s+good\b", 2.6),
    (r"\bworks?\s+all\s+things\s+together\s+for\s+(?:the\s+)?good\b", 2.6),
    (r"\bnothing\s+(?:happens|takes\s+place)\s+(?:outside|apart from)\s+(?:his|god'?s)\s+(?:will|purpose)\b", 3.0),
    (r"\bgod\s+(?:purposed|planned|decreed)\b", 2.2),
]

_B1_THIN = [
    (r"\bgod\s+would\s+never\s+(?:cause|ordain|will|send)\b", 3.2),
    (r"\bgod\s+does\s+not\s+(?:cause|ordain|will)\s+(?:evil|suffering|tragedy)\b", 3.0),
    (r"\bonly\s+(?:because\s+of\s+)?(?:our|human)\s+free\s+will\b", 2.8),
    (r"\bgod\s+(?:is\s+)?(?:just\s+)?(?:with\s+us|alongside)\s+in\s+(?:our\s+)?(?:pain|suffering)\b.{0,40}\bnot\s+(?:over|in\s+control)\b", 2.8),
    (r"\bit'?s\s+(?:just\s+)?(?:bad\s+luck|random|meaningless)\b", 2.2),
]

_B3_GATE = [
    (r"\bwrath\s+of\s+god\b|\bgod'?s\s+wrath\b|\bdivine\s+wrath\b", 3.0),
    (r"\bhell\b", 2.2),
    (r"\beternal\s+(?:punishment|condemnation|fire|torment)\b", 3.0),
    (r"\bday\s+of\s+(?:judgment|judgement)\b", 2.4),
    (r"\b(?:final|last)\s+judgment\b", 2.4),
    (r"\bjudgment\s+(?:of|from)\s+god\b|\bgod'?s\s+judgment\b", 2.6),
    (r"\blake\s+of\s+fire\b", 2.8),
    (r"\bcondemn(?:ed|ation)\b", 1.4),
]

_B3_JUDICIAL = [
    (r"\bwrath\s+of\s+god\b|\bgod'?s\s+wrath\b", 2.8),
    (r"\bhell\s+is\s+(?:real|eternal|a\s+real)\b", 3.0),
    (r"\beternal\s+(?:punishment|fire|condemnation)\b", 2.8),
    (r"\bgod\s+(?:will\s+)?(?:judge|judges)\b", 2.0),
    (r"\bjudgment\s+(?:is\s+coming|seat|day)\b", 2.2),
    (r"\bretention\s+of\s+sins\b", 2.4),
    (r"\bthreatening\s+judgment\b", 2.6),
]

_B3_HEDGE = [
    (r"\bwe\s+don'?t\s+(?:like\s+to|often)\s+talk\s+about\s+(?:hell|wrath|judgment)\b", 2.8),
    (r"\bnot\s+(?:fire\s+and\s+brimstone|a\s+hellfire)\b", 2.6),
    (r"\bhell\s+is\s+(?:just\s+)?(?:a\s+)?metaphor\b", 2.4),
    (r"\bwhatever\s+hell\s+(?:means|is)\b", 2.2),
]

_B3_EMPTY = [
    (r"\bthere\s+is\s+no\s+hell\b", 3.2),
    (r"\bgod\s+(?:is\s+)?(?:only\s+)?love\s+and\s+(?:never|does\s+not)\s+(?:judge|wrath|punish)\b", 3.0),
    (r"\bjudgment\s+(?:is\s+)?(?:just\s+)?(?:consequences|natural\s+outcome)\b", 2.4),
    (r"\bno\s+(?:angry|wrathful)\s+god\b", 2.6),
]

_B4_GUILT = [
    (r"\bguilt(?:y)?\s+before\s+god\b", 3.0),
    (r"\bforgiveness\s+of\s+(?:our\s+)?sins\b", 2.2),
    (r"\brepent(?:ance|ed|s)?\b", 1.8),
    (r"\btrespass(?:es)?\b", 2.0),
    (r"\bculpab", 2.4),
    (r"\bbad\s+conscience\b|\bguilty\s+conscience\b", 2.6),
    (r"\bwe\s+are\s+(?:sinners|guilty)\b", 2.2),
    (r"\bsin\s+(?:is|as)\s+(?:guilt|rebellion|transgression|disobedience)\b", 2.6),
    (r"\bneed(?:s)?\s+(?:the\s+)?forgiveness\b", 2.0),
]

_B4_WOUND = [
    (r"\btrauma(?:tized|tic)?\b", 2.4),
    (r"\bbrokenness\b", 2.0),
    (r"\bshame\b.{0,30}\bnot\s+guilt\b|\bnot\s+guilt\b.{0,30}\bshame\b", 3.0),
    (r"\bsystems?(?:ic)?\s+(?:sin|injustice|oppression)\b", 2.0),
    (r"\bwound(?:ed|s)?\b.{0,30}\b(?:inner|soul|heart)\b", 2.0),
    (r"\byou\s+are\s+not\s+guilty\b", 2.8),
    (r"\bsin\s+is\s+(?:just\s+)?(?:a\s+)?(?:wound|sickness|brokenness)\b", 2.8),
]

_B5_GATE = [
    (r"\bjohn\s+14\s*:\s*6\b", 3.2),
    (r"\bno\s+one\s+comes\s+to\s+the\s+father\s+(?:except|but)\b", 3.2),
    (r"\bthe\s+(?:way|truth|life)\b.{0,30}\bno\s+one\s+comes\b", 2.8),
    (r"\bno\s+other\s+name\b", 3.0),
    (r"\bonly\s+name\s+(?:under\s+heaven|by\s+which)\b", 3.0),
    (r"\bother\s+religions?\b", 2.2),
    (r"\bsincere\s+seekers?\b", 2.4),
    (r"\bonly\s+(?:through|in)\s+(?:jesus|christ)\b", 2.0),
    (r"\bjehovah'?s\s+witness", 1.8),
    (r"\bislam\b|\bmuslim\b", 1.4),
]

_B5_HARD = [
    (r"\bno\s+one\s+comes\s+to\s+the\s+father\s+(?:except|but)\s+(?:through|by)\s+me\b", 3.2),
    (r"\bno\s+other\s+name\b", 3.0),
    (r"\bonly\s+name\s+(?:under\s+heaven|given)\b", 3.0),
    (r"\bonly\s+(?:through|in)\s+(?:jesus|christ)\b", 2.2),
    (r"\bthere\s+is\s+no\s+other\s+(?:way|saviou?r|name)\b", 3.0),
]

_B5_HEDGE = [
    (r"\bwe\s+(?:can'?t|cannot|do\s+not)\s+know\s+(?:about|what\s+happens\s+to)\s+(?:those|people|others)\b", 2.6),
    (r"\bleave\s+(?:them|it|that)\s+to\s+god\b", 2.2),
    (r"\bwe\s+believe\b.{0,40}\bbut\s+we\s+don'?t\s+know\b", 2.4),
]

_B5_PLURAL = [
    (r"\bmany\s+paths?\b|\ball\s+religions\s+(?:lead|are)\b", 3.0),
    (r"\bsincere\s+seekers?\s+(?:will\s+be\s+)?(?:saved|accepted)\b", 3.0),
    (r"\bit\s+doesn'?t\s+matter\s+what\s+you\s+believe\b", 2.8),
    (r"\bislam\s+(?:is\s+)?(?:also\s+)?(?:a\s+)?(?:valid|true)\s+(?:path|way)\b", 3.0),
]

_B6_GATE = [
    (r"\bannihilat", 3.0),
    (r"\bconditional\s+immortality\b", 3.2),
    (r"\bconditionalism\b", 3.2),
    (r"\bsoul\s+sleep\b", 3.0),
    (r"\beternal\s+conscious\s+torment\b", 3.2),
    (r"\beverlasting\s+punishment\b", 2.8),
    (r"\beternal\s+punishment\b", 2.2),
    (r"\bimmortality\s+of\s+the\s+soul\b", 2.0),
]

_B6_ECP = [
    (r"\beternal\s+conscious\s+torment\b", 3.2),
    (r"\beverlasting\s+punishment\b", 2.8),
    (r"\bconscious(?:ly)?\s+(?:torment|suffering)\s+forever\b", 3.0),
    (r"\bhell\s+(?:is|means)\s+(?:eternal|everlasting)\b", 2.6),
]

_B6_ANN = [
    (r"\bannihilat", 3.0),
    (r"\bconditional\s+immortality\b", 3.2),
    (r"\bconditionalism\b", 3.2),
    (r"\bsoul\s+sleep\b", 2.8),
    (r"\bthe\s+wicked\s+(?:cease\s+to\s+exist|are\s+destroyed)\b", 3.0),
]

_B7_GATE = [
    (r"\bromans\s*13\b", 3.2),
    (r"\bgoverning\s+authorit", 3.0),
    (r"\bsubmit(?:ted|s)?\s+to\s+(?:the\s+)?(?:government|state|authorities)\b", 2.8),
    (r"\bauthorities\s+that\s+exist\s+(?:have\s+been\s+)?(?:established|instituted)\b", 2.8),
]

_B7_TENSION = [
    (r"\bacts\s*5\s*:\s*29\b", 3.2),
    (r"\bwe\s+must\s+obey\s+god\s+rather\s+than\s+(?:men|human|man)\b", 3.2),
    (r"\bconscience\b", 1.8),
    (r"\bcivil\s+disobedience\b", 2.6),
    (r"\bprophetic\b.{0,30}\b(?:state|government|king|empire)\b", 2.2),
    (r"\blimits?\s+(?:of|to)\s+(?:obedience|submission)\b", 2.6),
]

_B7_FLAT = [
    (r"\balways\s+(?:obey|submit\s+to)\s+(?:the\s+)?(?:government|authorities|state)\b", 3.0),
    (r"\bchristians?\s+must\s+(?:simply\s+)?(?:obey|submit)\b.{0,30}\b(?:government|rulers|state)\b", 2.8),
    (r"\bno\s+(?:right|place)\s+to\s+(?:resist|question)\s+(?:the\s+)?(?:government|authorities)\b", 3.0),
]


def _axis_a1(text: str) -> dict[str, Any]:
    gate, gate_ev = _score(text, _A1_GATE)
    classic, c_ev = _score(text, _A1_CLASSIC)
    hedge, h_ev = _score(text, _A1_HEDGE)
    egal, e_ev = _score(text, _A1_EGAL)
    if gate < 1.8:
        return _pick_band(
            {"classic_complementarian": 0, "soft_hedged": 0, "egalitarian_reframing": 0},
            {"avoided_or_no_hit": gate_ev},
            axis="A1",
            no_hit="avoided_or_no_hit",
            min_score=99,
        )
    # Citation without stance → avoided, not a drift call.
    scores = {
        "classic_complementarian": classic,
        "soft_hedged": hedge,
        "egalitarian_reframing": egal,
    }
    ev = {
        "classic_complementarian": _merge_evidence(c_ev, gate_ev),
        "soft_hedged": _merge_evidence(h_ev, gate_ev),
        "egalitarian_reframing": _merge_evidence(e_ev, gate_ev),
        "avoided_or_no_hit": gate_ev,
    }
    return _pick_band(
        scores, ev, axis="A1", no_hit="avoided_or_no_hit",
        min_score=1.8, undercall_to="soft_hedged",
    )


def _axis_a2(text: str) -> dict[str, Any]:
    gate, gate_ev = _score(text, _A2_GATE)
    classic, c_ev = _score(text, _A2_CLASSIC)
    hedge, h_ev = _score(text, _A2_HEDGE)
    egal, e_ev = _score(text, _A2_EGAL)
    if gate < 1.8:
        return _pick_band(
            {"classic_complementarian": 0, "soft_hedged": 0, "egalitarian_reframing": 0},
            {"avoided_or_no_hit": gate_ev},
            axis="A2",
            no_hit="avoided_or_no_hit",
            min_score=99,
        )
    scores = {
        "classic_complementarian": classic,
        "soft_hedged": hedge,
        "egalitarian_reframing": egal,
    }
    ev = {
        "classic_complementarian": _merge_evidence(c_ev, gate_ev),
        "soft_hedged": _merge_evidence(h_ev, gate_ev),
        "egalitarian_reframing": _merge_evidence(e_ev, gate_ev),
        "avoided_or_no_hit": gate_ev,
    }
    return _pick_band(
        scores, ev, axis="A2", no_hit="avoided_or_no_hit",
        min_score=1.8, undercall_to="soft_hedged",
    )


def _axis_b1(text: str) -> dict[str, Any]:
    gate, gate_ev = _score(text, _B1_GATE)
    stout, s_ev = _score(text, _B1_STOUT)
    thin, t_ev = _score(text, _B1_THIN)
    if gate < 1.8:
        return _pick_band(
            {"stout_providence": 0, "mixed": 0, "thinned_freewill": 0},
            {"unclear_or_no_hit": gate_ev},
            axis="B1",
            no_hit="unclear_or_no_hit",
            min_score=99,
        )
    mixed = 0.0
    if stout >= 1.6 and thin >= 1.6:
        mixed = min(stout, thin) + 1.2
    scores = {
        "stout_providence": stout if mixed < stout else stout * 0.4,
        "mixed": mixed,
        "thinned_freewill": thin if mixed < thin else thin * 0.4,
    }
    ev = {
        "stout_providence": _merge_evidence(s_ev, gate_ev),
        "mixed": _merge_evidence(s_ev, t_ev, gate_ev),
        "thinned_freewill": _merge_evidence(t_ev, gate_ev),
        "unclear_or_no_hit": gate_ev,
    }
    return _pick_band(
        scores, ev, axis="B1", no_hit="unclear_or_no_hit",
        min_score=1.8, undercall_to="mixed",
    )


def _axis_b3(text: str) -> dict[str, Any]:
    # Filter casual "what the hell" / "hell of a".
    cleaned = re.sub(r"\b(?:what|why|who|how) the hell\b|\bhell of a\b", " ", text, flags=re.I)
    gate, gate_ev = _score(cleaned, _B3_GATE)
    jud, j_ev = _score(cleaned, _B3_JUDICIAL)
    hedge, h_ev = _score(cleaned, _B3_HEDGE)
    empty, e_ev = _score(cleaned, _B3_EMPTY)
    if gate < 2.0:
        return _pick_band(
            {"judicial_retained": 0, "hedged": 0, "emptied_or_silent": 0},
            {"unclear_or_no_hit": gate_ev},
            axis="B3",
            no_hit="unclear_or_no_hit",
            min_score=99,
        )
    scores = {
        "judicial_retained": jud,
        "hedged": hedge,
        "emptied_or_silent": empty,
    }
    ev = {
        "judicial_retained": _merge_evidence(j_ev, gate_ev),
        "hedged": _merge_evidence(h_ev, gate_ev),
        "emptied_or_silent": _merge_evidence(e_ev, gate_ev),
        "unclear_or_no_hit": gate_ev,
    }
    return _pick_band(
        scores, ev, axis="B3", no_hit="unclear_or_no_hit",
        min_score=1.8, undercall_to="hedged",
    )


def _axis_b4(text: str) -> dict[str, Any]:
    guilt, g_ev = _score(text, _B4_GUILT)
    wound, w_ev = _score(text, _B4_WOUND)
    if guilt < 1.6 and wound < 1.6:
        return _pick_band(
            {"guilt_before_god": 0, "mixed": 0, "wound_only": 0},
            {"unclear_or_no_hit": _merge_evidence(g_ev, w_ev)},
            axis="B4",
            no_hit="unclear_or_no_hit",
            min_score=99,
        )
    mixed = 0.0
    if guilt >= 1.6 and wound >= 1.8:
        mixed = min(guilt, wound) + 1.0
    # Wound-only requires wound language AND weak guilt. Do not over-call.
    wound_only = wound if guilt < 1.4 else 0.0
    scores = {
        "guilt_before_god": guilt if mixed < 1.6 else guilt * 0.35,
        "mixed": mixed,
        "wound_only": wound_only,
    }
    ev = {
        "guilt_before_god": g_ev,
        "mixed": _merge_evidence(g_ev, w_ev),
        "wound_only": w_ev,
        "unclear_or_no_hit": _merge_evidence(g_ev, w_ev),
    }
    return _pick_band(
        scores, ev, axis="B4", no_hit="unclear_or_no_hit",
        min_score=1.7, undercall_to="mixed",
    )


def _axis_b5(text: str) -> dict[str, Any]:
    gate, gate_ev = _score(text, _B5_GATE)
    hard, h_ev = _score(text, _B5_HARD)
    hedge, d_ev = _score(text, _B5_HEDGE)
    plural, p_ev = _score(text, _B5_PLURAL)
    if gate < 1.8:
        return _pick_band(
            {"exclusive_hard": 0, "hedged": 0, "soft_pluralist": 0},
            {"unclear_or_no_hit": gate_ev},
            axis="B5",
            no_hit="unclear_or_no_hit",
            min_score=99,
        )
    scores = {
        "exclusive_hard": hard,
        "hedged": hedge,
        "soft_pluralist": plural,
    }
    ev = {
        "exclusive_hard": _merge_evidence(h_ev, gate_ev),
        "hedged": _merge_evidence(d_ev, gate_ev),
        "soft_pluralist": _merge_evidence(p_ev, gate_ev),
        "unclear_or_no_hit": gate_ev,
    }
    return _pick_band(
        scores, ev, axis="B5", no_hit="unclear_or_no_hit",
        min_score=1.8, undercall_to="hedged",
    )


def _axis_b6(text: str, *, attribution: str = "") -> dict[str, Any]:
    gate, gate_ev = _score(text, _B6_GATE)
    ecp, e_ev = _score(text, _B6_ECP)
    ann, a_ev = _score(text, _B6_ANN)
    notes: list[str] = []
    if attribution == "historical_stott" and (ann > 0 or gate > 0):
        notes.append(
            "Historical Stott: late-career openness to annihilation is documented; "
            "do not treat a hit as 'drift from Stott' without reading the quote."
        )
    if gate < 1.8:
        row = _pick_band(
            {"traditional_ecp": 0, "annihilation_or_conditional": 0, "ambiguous": 0},
            {"no_hit": gate_ev},
            axis="B6",
            no_hit="no_hit",
            min_score=99,
        )
        if notes:
            row["notes"] = notes
        return row
    ambiguous = 0.0
    if ecp >= 1.6 and ann >= 1.6:
        ambiguous = min(ecp, ann) + 1.4
    scores = {
        "traditional_ecp": ecp if ambiguous < ecp else ecp * 0.4,
        "annihilation_or_conditional": ann if ambiguous < ann else ann * 0.4,
        "ambiguous": ambiguous,
    }
    ev = {
        "traditional_ecp": _merge_evidence(e_ev, gate_ev),
        "annihilation_or_conditional": _merge_evidence(a_ev, gate_ev),
        "ambiguous": _merge_evidence(e_ev, a_ev, gate_ev),
        "no_hit": gate_ev,
    }
    row = _pick_band(
        scores, ev, axis="B6", no_hit="no_hit",
        min_score=1.8, undercall_to="ambiguous",
    )
    if notes:
        row["notes"] = notes
    return row


def _axis_b7(text: str) -> dict[str, Any]:
    gate, gate_ev = _score(text, _B7_GATE)
    tension, t_ev = _score(text, _B7_TENSION)
    flat, f_ev = _score(text, _B7_FLAT)
    if gate < 1.8:
        return _pick_band(
            {"classical_tension": 0, "mixed": 0, "flat_compliance_only": 0},
            {"no_hit": gate_ev},
            axis="B7",
            no_hit="no_hit",
            min_score=99,
        )
    mixed = 0.0
    if tension >= 1.4 and flat >= 1.6:
        mixed = min(tension, flat) + 1.0
    # A Romans 13 hit with neither tension nor flat language stays no_hit-adjacent:
    # we will not call flat_compliance from the citation alone.
    scores = {
        "classical_tension": tension,
        "mixed": mixed,
        "flat_compliance_only": flat if tension < 1.2 else flat * 0.35,
    }
    ev = {
        "classical_tension": _merge_evidence(t_ev, gate_ev),
        "mixed": _merge_evidence(t_ev, f_ev, gate_ev),
        "flat_compliance_only": _merge_evidence(f_ev, gate_ev),
        "no_hit": gate_ev,
    }
    return _pick_band(
        scores, ev, axis="B7", no_hit="no_hit",
        min_score=1.8, undercall_to="mixed",
    )


def score_sermon(
    text: str,
    *,
    attribution: str = "uncertain",
    title: str = "",
    slug: str = "",
    sermon_id: Optional[str] = None,
) -> dict[str, Any]:
    blob = f"{title}\n{text}"
    axes = {
        "A1": _axis_a1(blob),
        "A2": _axis_a2(blob),
        "B1": _axis_b1(blob),
        "B3": _axis_b3(blob),
        "B4": _axis_b4(blob),
        "B5": _axis_b5(blob),
        "B6": _axis_b6(blob, attribution=attribution),
        "B7": _axis_b7(blob),
    }
    hit_axes = [k for k, v in axes.items() if v.get("hit")]
    return {
        "slug": slug,
        "sermon_id": sermon_id,
        "title": title,
        "attribution": attribution,
        "axes": axes,
        "hit_axes": hit_axes,
        "hit_count": len(hit_axes),
        "version": FIDELITY_VERSION,
        "method": METHOD,
        "cost_usd": COST_USD,
        "not_coach_product": True,
        "provisional": True,
    }


def load_source_payload(path: Path) -> dict[str, Any]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"not an object: {path}")
    return raw


def harvest_folder(folder: Path, *, preacher: Optional[str] = None) -> dict[str, Any]:
    files = iter_sermon_files(folder)
    attributions: dict[str, Any] = {}
    hits: list[dict[str, Any]] = []
    for path in files:
        acquired = acquire_path(path, preacher=preacher)
        raw: dict[str, Any] = {}
        if path.suffix.lower() == ".json":
            raw = load_source_payload(path)
        attr = attribute_sermon(
            text=acquired.text,
            metadata=raw or {
                "id": acquired.sermon_id,
                "title": acquired.title,
                "audioUrl": acquired.audio_url,
                "_source": acquired.metadata,
            },
            source_path=str(path),
        )
        slug = attr["slug"]
        attributions[slug] = {
            "slug": slug,
            "sermon_id": attr.get("sermon_id"),
            "title": attr.get("title") or acquired.title,
            "attribution": attr["attribution"],
            "confidence": attr["confidence"],
            "reasons": attr["reasons"],
            "signals": attr["signals"],
            "source_path": str(path),
        }
        hit = score_sermon(
            acquired.text,
            attribution=attr["attribution"],
            title=acquired.title,
            slug=slug,
            sermon_id=attr.get("sermon_id") or acquired.sermon_id,
        )
        hits.append(hit)
    return {
        "attributions": attributions,
        "hits": hits,
        "version": FIDELITY_VERSION,
        "method": METHOD,
        "cost_usd": COST_USD,
        "folder": str(folder),
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def _pct(n: int, d: int) -> str:
    if d <= 0:
        return "n/a"
    return f"{n}/{d} ({n / d:.0%})"


def _best_quotes(hits: list[dict[str, Any]], limit: int = 16) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for hit in hits:
        for axis_id, axis in (hit.get("axes") or {}).items():
            if not axis.get("hit"):
                continue
            for ev in axis.get("evidence") or []:
                rows.append({
                    "axis": axis_id,
                    "band": axis.get("band"),
                    "confidence": axis.get("confidence") or 0,
                    "slug": hit.get("slug"),
                    "title": hit.get("title"),
                    "attribution": hit.get("attribution"),
                    "quote": ev.get("quote"),
                    "char_start": ev.get("char_start"),
                    "char_end": ev.get("char_end"),
                })
    # Diversity: at most two quotes per axis, prefer higher confidence.
    rows.sort(key=lambda r: (-float(r["confidence"]), r["axis"], r["slug"] or ""))
    picked: list[dict[str, Any]] = []
    per_axis: Counter[str] = Counter()
    seen_quotes: set[str] = set()
    for row in rows:
        q = (row.get("quote") or "").strip()
        if not q or q in seen_quotes:
            continue
        if per_axis[row["axis"]] >= 3:
            continue
        per_axis[row["axis"]] += 1
        seen_quotes.add(q)
        picked.append(row)
        if len(picked) >= limit:
            break
    return picked


def render_rollup(bundle: dict[str, Any]) -> str:
    attrs = bundle.get("attributions") or {}
    hits = bundle.get("hits") or []
    by_attr = Counter(v["attribution"] for v in attrs.values())
    hits_by_attr: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for h in hits:
        hits_by_attr[h.get("attribution") or "uncertain"].append(h)

    lines: list[str] = [
        "# Stott / All Souls fidelity slice (T1 cheap path)",
        "",
        "Chris-facing diagnosis. **Not Coach.** Heuristic bands only. "
        "Tiny historical-n. Prefer under-calling over drift claims.",
        "",
        f"- Method: `{METHOD}` / `{FIDELITY_VERSION}`",
        f"- Cost: **$0** (no Anthropic, no T2, no Voyage)",
        f"- Sermons scored: **{len(hits)}**",
        f"- Generated: {bundle.get('created_at') or ''}",
        "",
        "## 1. Attribution (do this before any Stott profile)",
        "",
        "Scrapes labeled contributor `John Stott` are **not** thereby Stott. "
        "The All Souls 2025–26 set is contemporary preaching mis-tagged on ingest.",
        "",
        f"- `historical_stott`: **{by_attr.get('historical_stott', 0)}** "
        "(SermonIndex hash ids; Urbana Great Commission + 2 Timothy set)",
        f"- `all_souls_contemporary`: **{by_attr.get('all_souls_contemporary', 0)}** "
        "(UUID + allsouls.org + 2025–26 dates / modern markers)",
        f"- `uncertain`: **{by_attr.get('uncertain', 0)}**",
        "",
        "**Do not merge the All Souls contemporary set into a Stott ministry profile.**",
        "",
    ]

    if by_attr.get("historical_stott"):
        lines.append("Historical Stott slugs:")
        for slug, row in sorted(attrs.items()):
            if row["attribution"] == "historical_stott":
                lines.append(f"- `{slug}` — {row.get('title') or ''}")
        lines.append("")

    lines += [
        "## 2. Hit rates by attribution group",
        "",
        "A sermon *hits* an axis when the harvester finds enough citation/topic "
        "plus stance language to assign a band other than the no-hit default. "
        "Low hit rates are expected and should stay honest.",
        "",
        "| Axis | historical_stott hits | all_souls_contemporary hits | uncertain hits |",
        "|---|---:|---:|---:|",
    ]
    groups = ("historical_stott", "all_souls_contemporary", "uncertain")
    for axis_id, meta in AXIS_META.items():
        cells = []
        for g in groups:
            subset = hits_by_attr.get(g) or []
            n_hit = sum(1 for h in subset if (h.get("axes") or {}).get(axis_id, {}).get("hit"))
            cells.append(_pct(n_hit, len(subset)))
        lines.append(f"| {axis_id} {meta['name']} | {cells[0]} | {cells[1]} | {cells[2]} |")

    lines += [
        "",
        "## 3. Band distributions (hits only, then all-sermon including no-hit)",
        "",
    ]
    for axis_id, meta in AXIS_META.items():
        lines.append(f"### {meta['title']}")
        lines.append("")
        for g in groups:
            subset = hits_by_attr.get(g) or []
            if not subset:
                continue
            hit_bands = Counter()
            all_bands = Counter()
            for h in subset:
                axis = (h.get("axes") or {}).get(axis_id) or {}
                band = axis.get("band") or meta["no_hit"]
                all_bands[band] += 1
                if axis.get("hit"):
                    hit_bands[band] += 1
            lines.append(f"**{g}** (n={len(subset)}; hits={sum(hit_bands.values())})")
            if hit_bands:
                bits = ", ".join(f"`{b}` {c}" for b, c in hit_bands.most_common())
                lines.append(f"- among hits: {bits}")
            else:
                lines.append("- among hits: *(none — do not infer drift)*")
            bits = ", ".join(f"`{b}` {c}" for b, c in all_bands.most_common())
            lines.append(f"- all sermons: {bits}")
            lines.append("")

    quotes = _best_quotes(hits, limit=18)
    lines += [
        "## 4. Best evidence quotes",
        "",
        "Selected for axis coverage and confidence. Offsets are into "
        "`title + newline + cleaned transcript`.",
        "",
    ]
    if not quotes:
        lines.append("No stance-level quotes cleared the hit threshold.")
        lines.append("")
    for i, q in enumerate(quotes, start=1):
        quote = (q.get("quote") or "").replace("\n", " ")
        lines.append(
            f"{i}. **{q['axis']}** `{q['band']}` — {q.get('attribution')} "
            f"`{q.get('slug')}` ({q.get('title')})"
        )
        lines.append(f"   > {quote}")
        if q.get("char_start") is not None:
            lines.append(f"   offsets {q['char_start']}–{q['char_end']}")
        lines.append("")

    lines += [
        "## 5. Caveats",
        "",
        "- Historical Stott **n is tiny** (the SermonIndex Urbana set). "
        "Do not treat group percentages as a Stott doctrine profile.",
        "- Bands are **regex / proximity heuristics**. Close races under-call "
        "to `mixed` / `hedged` / `soft_hedged` rather than a drift label.",
        "- `avoided_or_no_hit` / `unclear_or_no_hit` / `no_hit` mean the slice "
        "did not fire. Silence is not evidence of emptying a doctrine.",
        "- A1/A2 (1 Tim 2 / Eph 5) often will not appear in a random lectionary "
        "or series scrape. Few hits ≠ egalitarian drift.",
        "- B6: Stott’s late-career openness to annihilation is known. A "
        "historical hit on annihilation language is a flag to read, not a gotcha.",
        "- B7: citation of Romans 13 alone is not `flat_compliance_only`.",
        "- This is **not Coach** and not a living-preacher likeness score.",
        "- Cost of this slice: **$0.00**. No production data was deleted.",
        "",
        "## 6. Cost",
        "",
        "| Step | API | USD |",
        "|---|---|---:|",
        "| T1 structure (optional companion batch) | none | 0.00 |",
        "| Attribution + axis harvest | none | 0.00 |",
        "| **Total** | | **0.00** |",
        "",
    ]
    return "\n".join(lines) + "\n"


def compact_summary(bundle: dict[str, Any]) -> dict[str, Any]:
    attrs = bundle.get("attributions") or {}
    hits = bundle.get("hits") or []
    by_attr = Counter(v["attribution"] for v in attrs.values())
    axes_out: dict[str, Any] = {}
    for axis_id, meta in AXIS_META.items():
        groups: dict[str, Any] = {}
        for g in ("historical_stott", "all_souls_contemporary", "uncertain"):
            subset = [h for h in hits if h.get("attribution") == g]
            bands = Counter(
                ((h.get("axes") or {}).get(axis_id) or {}).get("band") or meta["no_hit"]
                for h in subset
            )
            n_hit = sum(
                1 for h in subset
                if ((h.get("axes") or {}).get(axis_id) or {}).get("hit")
            )
            groups[g] = {
                "n": len(subset),
                "hits": n_hit,
                "bands": dict(bands),
            }
        axes_out[axis_id] = {"name": meta["name"], "groups": groups}
    return {
        "version": FIDELITY_VERSION,
        "method": METHOD,
        "cost_usd": COST_USD,
        "not_coach_product": True,
        "sermons": len(hits),
        "attribution_counts": dict(by_attr),
        "axes": axes_out,
        "historical_slugs": sorted(
            s for s, row in attrs.items() if row.get("attribution") == "historical_stott"
        ),
        "do_not_merge_into_stott_profile": [
            s for s, row in attrs.items()
            if row.get("attribution") == "all_souls_contemporary"
        ],
        "best_quotes": _best_quotes(hits, limit=18),
        "created_at": bundle.get("created_at"),
    }


def write_bundle(bundle: dict[str, Any], output_dir: Path) -> dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    attr_path = output_dir / "attribution.json"
    hits_path = output_dir / "hits.jsonl"
    rollup_path = output_dir / "rollup.md"
    summary_path = output_dir / "summary.json"

    attr_doc = {
        "version": FIDELITY_VERSION,
        "method": METHOD,
        "cost_usd": COST_USD,
        "created_at": bundle.get("created_at"),
        "counts": dict(Counter(v["attribution"] for v in bundle["attributions"].values())),
        "sermons": bundle["attributions"],
        "note": (
            "all_souls_contemporary rows are mis-tagged as John Stott on scrape. "
            "Do not fold them into a historical Stott ministry profile."
        ),
    }
    attr_path.write_text(json.dumps(attr_doc, indent=2) + "\n", encoding="utf-8")
    with hits_path.open("w", encoding="utf-8") as fh:
        for row in bundle["hits"]:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    rollup_path.write_text(render_rollup(bundle), encoding="utf-8")
    summary_path.write_text(
        json.dumps(compact_summary(bundle), indent=2) + "\n", encoding="utf-8"
    )
    return {
        "attribution": attr_path,
        "hits": hits_path,
        "rollup": rollup_path,
        "summary": summary_path,
    }
