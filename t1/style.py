"""Provisional T1 preaching-style discernment (heuristic, $0).

Not the Coach product. Emits labels + short evidence quotes/offsets +
confidence so free corpora and Sermon Audit can ask “what kind of
preaching is this ministry?” without a T2 decompose.

Primary axis is always a category. Famous preacher names appear only as
optional school-illustration metadata nested under that category — never
as a living-likeness score.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Any, Iterable, Optional

STYLE_VERSION = "t1-style-v1"
METHOD = "heuristic_v1"

# ── Label set (provisional; Chris will refine taste/judgment) ─────────────

TEXT_RELATIONSHIP = (
    "continuous_exposition",  # verse-by-verse walk through a passage
    "textual",                # sermon on a pericope / short text
    "topical",                # theme-driven, texts as support
    "narrative",              # story-driven
    "unclear",
)

REDEMPTIVE_FRAME = (
    "redemptive_historical",  # Christ-centered / RH movement
    "moral_exemplary",        # be-like / lessons-from
    "doctrinal_systematic",   # doctrine, creed, loci
    "unclear",
)

FCF = (
    "fcf_gospel",        # diagnoses a fallen condition and resolves in the gospel
    "fcf_partial",       # diagnosis xor gospel, or weak both
    "tips_imperatives",  # mainly how-to / tips
    "unclear",
)

APPLICATION_WEIGHT = ("heavy", "moderate", "light", "unclear")
APPLICATION_AUDIENCE = ("corporate", "individual", "mixed", "unclear")

TONE_REGISTER = (
    "teaching",    # lectern / didactic
    "prophetic",   # urgent / woe / repent
    "pastoral",    # conversational / shepherding
    "unclear",
)

# Historical school illustrations only. Living names, if present, are
# tagged as popularizers of a *category* — not a nearest-neighbor score.
SCHOOLS: dict[tuple[str, str], dict[str, Any]] = {
    ("text_relationship", "continuous_exposition"): {
        "school": "lectio continua / consecutive exposition",
        "historical_examples": ["John Calvin", "Martyn Lloyd-Jones"],
        "note": "Category illustration, not a likeness score.",
    },
    ("text_relationship", "textual"): {
        "school": "textual / pericope sermon",
        "historical_examples": ["Charles Spurgeon (often textual)"],
        "note": "Category illustration, not a likeness score.",
    },
    ("text_relationship", "topical"): {
        "school": "topical-thematic",
        "historical_examples": ["Many revival and conference traditions"],
        "note": "Category illustration, not a likeness score.",
    },
    ("text_relationship", "narrative"): {
        "school": "narrative / story-driven",
        "historical_examples": ["Narrative preaching school (e.g. Lowry as theorist)"],
        "note": "Category illustration, not a likeness score.",
    },
    ("redemptive_frame", "redemptive_historical"): {
        "school": "redemptive-historical / Christ-centered",
        "historical_examples": ["Geerhardus Vos", "Edmund Clowney"],
        "popular_illustrations": [
            "Tim Keller is often cited as a popularizer of this school — "
            "illustration of the category only, never a living-likeness score."
        ],
        "note": "Do not score 'you preach like [living celebrity]'.",
    },
    ("redemptive_frame", "moral_exemplary"): {
        "school": "moral-exemplary / character imitation",
        "historical_examples": ["Much popular biographical preaching"],
        "note": "Category illustration, not a likeness score.",
    },
    ("redemptive_frame", "doctrinal_systematic"): {
        "school": "doctrinal-systematic / loci",
        "historical_examples": ["Reformed dogmatic preaching; catechetical sermons"],
        "note": "Category illustration, not a likeness score.",
    },
    ("fallen_condition_focus", "fcf_gospel"): {
        "school": "Fallen Condition Focus → gospel resolution",
        "historical_examples": ["Bryan Chapell (FCF as a teaching category)"],
        "note": "Heuristic for the category, not a quality grade of Chapell-style preaching.",
    },
    ("tone_register", "teaching"): {
        "school": "didactic / lectern",
        "historical_examples": ["Classic Reformed lectern exposition"],
        "note": "Category illustration, not a likeness score.",
    },
    ("tone_register", "prophetic"): {
        "school": "prophetic / urgent",
        "historical_examples": ["Puritan 'woe' register; revivalist urgency"],
        "note": "Category illustration, not a likeness score.",
    },
    ("tone_register", "pastoral"): {
        "school": "conversational-pastoral",
        "historical_examples": ["Cure-of-souls register"],
        "note": "Category illustration, not a likeness score.",
    },
}

DEFERRED_TO_COACH = [
    "Full Chapell FCF quality judgment (is the diagnosis the *right* FCF?).",
    "Living-preacher nearest-neighbor / 'you preach like Keller' scores.",
    "Unit-level rhetorical functions, citation tiers, BT moves (T2 spec).",
    "Illustration type, application_specificity enums from sermon-decomposition-spec-v3.",
    "Taste, judgment, and a refined homiletic taxonomy (Chris).",
    "Optional cheap-LLM second pass (Haiku/Flash) if heuristics saturate.",
]

# ── Patterns ──────────────────────────────────────────────────────────────

_VERSE_WALK = [
    (r"\bverse\s+by\s+verse\b", 3.0),
    (r"\bnext\s+verse\b", 2.0),
    (r"\blook\s+(?:with\s+me\s+)?(?:at\s+)?verse\s+\d+", 2.0),
    (r"\bverse\s+\d+\b", 1.2),
    (r"\bv(?:erse)?\.?\s*\d+\b", 1.0),
    (r"\bthen\s+(?:he|she|the\s+(?:text|writer|apostle|psalmist))\s+says\b", 1.2),
    (r"\bthe\s+next\s+(?:line|sentence|clause|verse)\b", 1.0),
    (r"\bclause\s+by\s+clause\b", 2.5),
    (r"\bconsecutive\s+exposition\b", 3.0),
]

_TEXTUAL = [
    (r"\bthis\s+(?:text|passage|pericope)\b", 2.0),
    (r"\bour\s+(?:text|passage)\b", 2.0),
    (r"\bthe\s+text\s+(?:before\s+us|says|begins|opens)\b", 1.5),
    (r"\bopen(?:ing)?\s+(?:to\s+)?(?:the\s+book\s+of\s+)?\w+\s+\d+", 1.2),
    (r"\b(?:luke|john|romans|acts|matthew|mark|psalm)\s+\d+", 0.8),
]

_TOPICAL = [
    (r"\btoday\s+i\s+want\s+to\s+talk\s+about\b", 3.0),
    (r"\bthe\s+topic\s+of\b", 2.0),
    (r"\bfive\s+habits\b", 2.5),
    (r"\b\d+\s+(?:tips|habits|keys|ways|steps|principles)\b", 2.5),
    (r"\bpractical\s+steps\b", 2.0),
    (r"\btheme\s+(?:of|for)\s+(?:this|today|a)\b", 1.5),
    (r"\btopical\s+preaching\b", 3.0),
]

_NARRATIVE = [
    (r"\bthe\s+story\s+of\b", 2.5),
    (r"\bthere\s+(?:once\s+)?was\s+a\b", 2.0),
    (r"\bparable\b", 1.5),
    (r"\bthen\s+he\s+(?:took|went|said|stood|ran)\b", 1.2),
    (r"\bdavid\s+and\s+goliath\b", 2.0),
    (r"\bonce\s+upon\b", 2.0),
    (r"\bnarrative\b", 1.5),
    (r"\blive\s+in\s+the\s+narrative\b", 2.5),
]

_RH_STRONG = [
    (r"\bredemptive[- ]historical\b", 3.0),
    (r"\bchrist[- ]centered\b", 2.5),
    (r"\bgreater\s+than\s+(?:jonah|solomon|david|moses)\b", 2.5),
    (r"\bsign\s+of\s+jonah\b", 2.0),
    (r"\bfulfilled\s+in\s+christ\b", 2.5),
    (r"\bdrama\s+of\s+redemption\b", 2.5),
    (r"\bword\s+became\s+flesh\b", 1.5),
    (r"\bempty\s+tomb\b", 2.0),
    (r"\bredemptive\s+thread\b", 2.0),
    (r"\bgod\s+presented\s+christ\b", 2.0),
    (r"\bgod\s+sent\s+his\s+own\s+son\b", 2.0),
]
# Weak gospel vocabulary only counts if a strong RH cue is already present.
# Otherwise "not resolving anything in the cross" false-fires on tip sermons.
_RH_WEAK = [
    (r"\bgospel\b", 0.6),
    (r"\bcross\b", 0.6),
    (r"\b(?:in|through)\s+christ\b", 1.0),
    (r"\bresurrection\b", 0.8),
    (r"\bredemption\b", 0.8),
]

_MORAL = [
    (r"\bbe\s+like\b", 2.5),
    (r"\bwe\s+should\s+(?:follow|imitate|copy)\b", 2.5),
    (r"\bthe\s+example\s+of\b", 2.0),
    (r"\blessons?\s+from\b", 2.0),
    (r"\blet\s+us\s+imitate\b", 2.5),
    (r"\bhave\s+courage\s+(?:like|this\s+week)\b", 2.0),
    (r"\bdavid\s+teaches\s+us\b", 2.0),
    (r"\bdrawing\s+the\s+moral\b", 2.5),
]

_DOCTRINE = [
    (r"\bdoctrine\s+of\b", 2.5),
    (r"\bwe\s+believe\b", 1.5),
    (r"\bthe\s+creed\b", 2.0),
    (r"\bnicene\b", 2.0),
    (r"\bjustification\b", 1.2),
    (r"\bpropitiation\b", 2.0),
    (r"\btrinity\b", 1.5),
    (r"\bsystematic\b", 1.5),
    (r"\bthe\s+word\s+means\b", 1.0),
    (r"\bhomoousi", 2.0),
]

_DIAGNOSIS = [
    (r"\ball\s+have\s+sinned\b", 2.5),
    (r"\bfallen\s+condition\b", 3.0),
    (r"\bour\s+(?:guilt|bondage|unbelief|problem|need|sin)\b", 1.8),
    (r"\bguilt\b", 0.8),
    (r"\bbondage\b", 1.2),
    (r"\bslave(?:holders|ry|master)?\b", 1.2),
    (r"\bunbelief\b", 1.2),
    (r"\bdarkness\b", 0.6),
    (r"\bthe\s+need\s+is\b", 1.5),
    (r"\bchildren\s+of\s+darkness\b", 2.0),
    (r"\bhostility\s+to\s+god\b", 2.5),
]

_GOSPEL_RESOLVE = [
    (r"\bgod\s+presented\s+christ\b", 3.0),
    (r"\bgod\s+sent\s+his\s+own\s+son\b", 3.0),
    (r"\bpropitiation\b", 2.0),
    (r"\bshedding\s+(?:of\s+)?(?:his\s+)?blood\b", 2.0),
    (r"\bjustif(?:y|ied|ication)\b", 1.2),
    (r"\bredeem(?:ed|s|ing|ption)\b", 1.0),
    (r"\bgrace\b", 0.5),
    (r"\bgospel\b", 0.6),
    (r"\bcross\b", 0.6),
    (r"\bempty\s+tomb\b", 2.0),
    (r"\bchrist\s+died\b", 2.0),
    (r"\bgospel\s+resolution\b", 3.0),
]

_TIPS = [
    (r"\b(?:five|three|four|ten)\s+(?:tips|habits|keys|ways|steps)\b", 3.0),
    (r"\btip\s+(?:one|two|three|1|2|3)\b", 2.5),
    (r"\bpractical\s+steps\b", 2.5),
    (r"\btry\s+to\b", 1.2),
    (r"\byou\s+should\b", 1.0),
    (r"\bhere\s+are\b", 1.0),
    (r"\bhow\s+to\b", 1.0),
    (r"\bevery\s+morning\b", 1.2),
    (r"\bleave\s+your\s+phone\b", 2.0),
    (r"\bfive\s+keys\b", 2.5),
]

_APP_CONCRETE = [
    (r"\bthis\s+week\b", 1.5),
    (r"\bat\s+work\b", 1.2),
    (r"\bin\s+your\s+(?:marriage|home|family|job)\b", 1.5),
    (r"\bgo\s+(?:and|home\s+and|to\s+bed)\b", 1.2),
    (r"\blet\s+us\b", 0.6),
    (r"\byou\s+(?:must|should|need\s+to)\b", 0.8),
    (r"\bpray\s+together\b", 1.5),
]

_CORPORATE = [
    (r"\bas\s+a\s+church\b", 2.0),
    (r"\bcongregation\b", 1.5),
    (r"\bone\s+another\b", 1.5),
    (r"\bthe\s+body\b", 0.8),
    (r"\belders?\b", 0.8),
    (r"\bbrothers\s+and\s+sisters\b", 1.5),
    (r"\bwe\s+together\b", 1.8),
]

_INDIVIDUAL = [
    (r"\byour\s+(?:heart|prayer\s+life|quiet\s+time|marriage|phone)\b", 1.8),
    (r"\byou\s+personally\b", 2.0),
    (r"\bin\s+your\s+own\b", 1.2),
    (r"\bevery\s+morning\b", 1.0),
    (r"\bindividual\s+piety\b", 2.5),
]

_TEACHING = [
    (r"\bthe\s+text\s+says\b", 2.0),
    (r"\bthe\s+(?:greek|hebrew)\b", 2.0),
    (r"\bthe\s+word\s+means\b", 2.0),
    (r"\bnotice\b", 0.5),
    (r"\blook\s+at\b", 0.5),
    (r"\bin\s+verse\b", 1.0),
    (r"\bthe\s+creed\b", 1.2),
    (r"\bdoctrine\b", 0.8),
]

_PROPHETIC = [
    (r"\bwoe\b", 2.5),
    (r"\brepent\b", 2.0),
    (r"\bevil\s+generation\b", 2.5),
    (r"\bjudgment\b", 1.2),
    (r"\bmust\s+change\b", 1.5),
    (r"\bhow\s+long\b", 1.2),
    (r"\bwarning\b", 1.0),
]

_PASTORAL = [
    (r"\bfriends\b", 1.2),
    (r"\bi\s+know\b", 0.8),
    (r"\bwe\s+struggle\b", 2.0),
    (r"\bi\s+want\s+you\s+to\b", 1.2),
    (r"\bpastoral\b", 1.5),
    (r"\bdear\s+(?:church|friends|brothers)\b", 2.0),
]

_BOOK_RE = re.compile(
    r"\b(?:genesis|exodus|leviticus|numbers|deuteronomy|joshua|judges|ruth|"
    r"(?:1|2|i|ii)\s*(?:samuel|kings|chronicles|corinthians|thessalonians|"
    r"timothy|peter|john)|"
    r"ezra|nehemiah|esther|job|psalms?|proverbs|ecclesiastes|"
    r"isaiah|jeremiah|lamentations|ezekiel|daniel|"
    r"hosea|joel|amos|obadiah|jonah|micah|nahum|habakkuk|zephaniah|"
    r"haggai|zechariah|malachi|"
    r"matthew|mark|luke|john|acts|romans|galatians|ephesians|philippians|"
    r"colossians|titus|philemon|hebrews|james|jude|revelation)\b",
    re.I,
)


def _score(text: str, weighted: list[tuple[str, float]], limit: int = 3) -> tuple[float, list[dict[str, Any]]]:
    total = 0.0
    evidence: list[dict[str, Any]] = []
    for pat, weight in weighted:
        for match in re.finditer(pat, text, re.I):
            total += weight
            if len(evidence) < limit:
                start = max(0, match.start() - 36)
                end = min(len(text), match.end() + 44)
                quote = re.sub(r"\s+", " ", text[start:end]).strip()
                evidence.append({
                    "quote": quote[:200],
                    "char_start": match.start(),
                    "char_end": match.end(),
                })
    return total, evidence


def _pick(
    scores: dict[str, float],
    evidence_map: dict[str, list[dict[str, Any]]],
    axis: str,
    labels: tuple[str, ...],
) -> dict[str, Any]:
    ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    best_label, best = ranked[0] if ranked else ("unclear", 0.0)
    second = ranked[1][1] if len(ranked) > 1 else 0.0
    if best <= 0:
        label = "unclear" if "unclear" in labels else best_label
        confidence = 0.2
    else:
        label = best_label
        margin = best - second
        confidence = max(
            0.28,
            min(0.92, 0.35 + (margin / (best + 1.0)) * 0.45 + min(best, 8) * 0.04),
        )
        if margin < 0.8 and second > 0:
            confidence = min(confidence, 0.55)
    payload: dict[str, Any] = {
        "axis": axis,
        "label": label,
        "confidence": round(confidence, 3),
        "scores": {k: round(v, 3) for k, v in scores.items()},
        "evidence": evidence_map.get(label) or next(
            (evidence_map[k] for k, _ in ranked if evidence_map.get(k)),
            [],
        )[:3],
        "provisional": True,
        "method": METHOD,
    }
    school = SCHOOLS.get((axis, label))
    if school:
        payload["school_illustration"] = school
    return payload


def _distinct_books(text: str) -> int:
    return len({m.group(0).lower() for m in _BOOK_RE.finditer(text)})


def discern_style(
    text: str,
    *,
    title: str = "",
    primary_text: Optional[str] = None,
) -> dict[str, Any]:
    """Return provisional style axes. Pure local heuristics — no API."""
    blob = f"{title}\n{primary_text or ''}\n{text}"

    tr_ce, tr_ce_ev = _score(blob, _VERSE_WALK)
    tr_tx, tr_tx_ev = _score(blob, _TEXTUAL)
    tr_to, tr_to_ev = _score(blob, _TOPICAL)
    tr_na, tr_na_ev = _score(blob, _NARRATIVE)
    tr_scores = {
        "continuous_exposition": tr_ce,
        "textual": tr_tx,
        "topical": tr_to,
        "narrative": tr_na,
    }
    tr_ev = {
        "continuous_exposition": tr_ce_ev,
        "textual": tr_tx_ev,
        "topical": tr_to_ev,
        "narrative": tr_na_ev,
    }
    books = _distinct_books(blob)
    if books >= 4:
        tr_scores["topical"] += 2.0
    elif books == 1 and tr_scores["continuous_exposition"] < tr_scores["textual"]:
        tr_scores["textual"] += 0.8
    if primary_text and re.search(r"\d+\s*:\s*\d+", primary_text or ""):
        tr_scores["textual"] += 1.0
    verse_nums = [int(n) for n in re.findall(r"\b(?:verse|v\.?)\s*(\d+)\b", blob, re.I)]
    if len(verse_nums) >= 3 and any(
        b == a + 1 for a, b in zip(verse_nums, verse_nums[1:])
    ):
        tr_scores["continuous_exposition"] += 3.0

    fr_rh_s, fr_rh_s_ev = _score(blob, _RH_STRONG)
    fr_rh_w, fr_rh_w_ev = _score(blob, _RH_WEAK)
    fr_rh = fr_rh_s + (fr_rh_w if fr_rh_s > 0 else 0.0)
    fr_rh_ev = fr_rh_s_ev or (fr_rh_w_ev if fr_rh_s > 0 else [])
    fr_mo, fr_mo_ev = _score(blob, _MORAL)
    fr_do, fr_do_ev = _score(blob, _DOCTRINE)
    frame_scores = {
        "redemptive_historical": fr_rh,
        "moral_exemplary": fr_mo,
        "doctrinal_systematic": fr_do,
    }
    frame_ev = {
        "redemptive_historical": fr_rh_ev,
        "moral_exemplary": fr_mo_ev,
        "doctrinal_systematic": fr_do_ev,
    }

    diag, diag_ev = _score(blob, _DIAGNOSIS, limit=3)
    gospel, gospel_ev = _score(blob, _GOSPEL_RESOLVE, limit=3)
    tips, tips_ev = _score(blob, _TIPS, limit=3)
    fcf_scores = {
        "fcf_gospel": min(diag, gospel) * 1.4 + (0.4 if diag and gospel else 0),
        "fcf_partial": abs(diag - gospel) * 0.5 + (diag + gospel) * 0.15,
        "tips_imperatives": tips,
    }
    if diag >= 2 and gospel >= 2:
        fcf_scores["fcf_gospel"] += 2.0
    if tips >= 3 and gospel < 1.5:
        fcf_scores["tips_imperatives"] += 2.0
        fcf_scores["fcf_gospel"] *= 0.4
    fcf_ev = {
        "fcf_gospel": (diag_ev + gospel_ev)[:3],
        "fcf_partial": diag_ev or gospel_ev,
        "tips_imperatives": tips_ev,
    }

    concrete, concrete_ev = _score(blob, _APP_CONCRETE)
    corp, corp_ev = _score(blob, _CORPORATE)
    indi, indi_ev = _score(blob, _INDIVIDUAL)
    if concrete >= 5:
        weight = "heavy"
    elif concrete >= 2:
        weight = "moderate"
    elif concrete > 0:
        weight = "light"
    else:
        weight = "unclear"
    if corp > 0 and indi > 0 and abs(corp - indi) < 1.2:
        audience = "mixed"
    elif corp > indi:
        audience = "corporate"
    elif indi > corp:
        audience = "individual"
    else:
        audience = "unclear"
    app_conf = max(0.28, min(0.88, 0.3 + concrete * 0.08 + max(corp, indi) * 0.06))
    app = {
        "axis": "application_shape",
        "label": weight,
        "audience": audience,
        "confidence": round(app_conf, 3),
        "scores": {
            "concrete": round(concrete, 3),
            "corporate": round(corp, 3),
            "individual": round(indi, 3),
        },
        "evidence": (concrete_ev + corp_ev + indi_ev)[:3],
        "provisional": True,
        "method": METHOD,
        "school_illustration": {
            "school": "application weight × audience",
            "note": "Heuristic only. T2 application_specificity is deferred.",
        },
    }

    tn_te, tn_te_ev = _score(blob, _TEACHING)
    tn_pr, tn_pr_ev = _score(blob, _PROPHETIC)
    tn_pa, tn_pa_ev = _score(blob, _PASTORAL)
    tone_scores = {
        "teaching": tn_te,
        "prophetic": tn_pr,
        "pastoral": tn_pa,
    }
    tone_ev = {
        "teaching": tn_te_ev,
        "prophetic": tn_pr_ev,
        "pastoral": tn_pa_ev,
    }

    axes = {
        "text_relationship": _pick(tr_scores, tr_ev, "text_relationship", TEXT_RELATIONSHIP),
        "redemptive_frame": _pick(frame_scores, frame_ev, "redemptive_frame", REDEMPTIVE_FRAME),
        "fallen_condition_focus": _pick(fcf_scores, fcf_ev, "fallen_condition_focus", FCF),
        "application_shape": app,
        "tone_register": _pick(tone_scores, tone_ev, "tone_register", TONE_REGISTER),
    }
    summary = (
        f"{axes['text_relationship']['label']} · "
        f"{axes['redemptive_frame']['label']} · "
        f"{axes['fallen_condition_focus']['label']} · "
        f"application:{axes['application_shape']['label']}/"
        f"{axes['application_shape']['audience']} · "
        f"tone:{axes['tone_register']['label']}"
    )
    return {
        "version": STYLE_VERSION,
        "method": METHOD,
        "provisional": True,
        "not_coach_product": True,
        "primary_axis": "category",
        "living_likeness_score": None,
        "summary": summary,
        "axes": axes,
        "deferred": DEFERRED_TO_COACH,
    }


def style_catalog_row(style: dict[str, Any]) -> dict[str, Any]:
    axes = style.get("axes") or {}
    return {
        "summary": style.get("summary"),
        "text_relationship": (axes.get("text_relationship") or {}).get("label"),
        "redemptive_frame": (axes.get("redemptive_frame") or {}).get("label"),
        "fallen_condition_focus": (axes.get("fallen_condition_focus") or {}).get("label"),
        "application": (axes.get("application_shape") or {}).get("label"),
        "audience": (axes.get("application_shape") or {}).get("audience"),
        "tone": (axes.get("tone_register") or {}).get("label"),
    }


def ministry_profile(styles: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Roll labels up so Sermon Audit can ask about a *ministry*, not one sermon."""
    counters = {
        "text_relationship": Counter(),
        "redemptive_frame": Counter(),
        "fallen_condition_focus": Counter(),
        "application": Counter(),
        "audience": Counter(),
        "tone": Counter(),
    }
    n = 0
    for style in styles:
        row = style_catalog_row(style)
        n += 1
        for key in counters:
            label = row.get(key)
            if label:
                counters[key][label] += 1
    majority = {
        key: (counts.most_common(1)[0][0] if counts else "unclear")
        for key, counts in counters.items()
    }
    return {
        "sermons": n,
        "majority": majority,
        "counts": {k: dict(v) for k, v in counters.items()},
        "question": "what kind of preaching is this ministry?",
        "living_likeness_score": None,
        "provisional": True,
    }


def label_set_doc() -> dict[str, Any]:
    return {
        "version": STYLE_VERSION,
        "axes": {
            "text_relationship": list(TEXT_RELATIONSHIP),
            "redemptive_frame": list(REDEMPTIVE_FRAME),
            "fallen_condition_focus": list(FCF),
            "application_shape.weight": list(APPLICATION_WEIGHT),
            "application_shape.audience": list(APPLICATION_AUDIENCE),
            "tone_register": list(TONE_REGISTER),
        },
        "method": METHOD,
        "cost_usd": 0.0,
        "deferred": DEFERRED_TO_COACH,
    }
