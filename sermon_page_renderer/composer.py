"""
Composer — builds the render-context dict from a sermon ID.

Calls the query layer, formats values for display, and returns a single dict
that the Jinja2 template can consume directly. This is the only place the
CLI and integration test need to call.
"""

from __future__ import annotations

import logging
from datetime import date as date_type, datetime, timezone
from typing import Optional

from . import queries as q
from . import schema_org
from .slug import slug_to_url_segment

log = logging.getLogger("sermon_page_renderer.composer")

# Calibrated against the reference HTML (34,852 chars / ~38 min).
CHARS_PER_WORD = 5
READING_WPM = 180

# Transcript preview — N units shown inline before the "Expand" cut.
TRANSCRIPT_PREVIEW_UNITS = 6

# Discuss / apply tile placeholders. Per Q10 — all six rendered as dead-anchor
# placeholders; the artifacts they link to don't exist yet.
APPLY_TILES = [
    {"key": "small_group", "label": "Small groups",  "title": "6 discussion questions",
     "desc": "Ready-to-print leader brief with cross-references and landing-zone application. PDF available.",
     "anchor": "#small-group"},
    {"key": "devotional",  "label": "Daily readings","title": "5-day reading plan",
     "desc": "Mon–Fri scripture readings drawn from this sermon's citations.",
     "anchor": "#devotional"},
    {"key": "family",      "label": "Family table",  "title": "Sunday-evening conversation card",
     "desc": "One prompt for the table; works for kids and adults alike.",
     "anchor": "#family"},
    {"key": "couples",     "label": "Couples",       "title": "Three questions over coffee",
     "desc": "For married members — works as a midweek check-in or a longer date conversation.",
     "anchor": "#couples"},
    {"key": "memory",      "label": "Memorize",      "title": None,
     "desc": None,
     "anchor": "#memory"},
]


def _month_name(month: int) -> str:
    return ["", "January", "February", "March", "April", "May", "June",
            "July", "August", "September", "October", "November", "December"][month]


def _coerce_date(d) -> Optional[date_type]:
    if not d:
        return None
    if isinstance(d, date_type):
        return d
    if isinstance(d, str):
        try:
            return date_type.fromisoformat(d)
        except ValueError:
            return None
    return None


def _format_long_date(d: Optional[date_type | str]) -> str:
    parsed = _coerce_date(d)
    if not parsed:
        return ""
    return f"{_month_name(parsed.month)} {parsed.day}, {parsed.year}"


def _format_short_date(d: Optional[date_type | str]) -> str:
    parsed = _coerce_date(d)
    if not parsed:
        return ""
    short_month = ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun",
                   "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"][parsed.month]
    return f"{short_month} {parsed.day}, {parsed.year}"


def _sermon_url_path(
    sermon_date: Optional[date_type],
    slug: str,
    church_url_slug: Optional[str] = None,
) -> str:
    """
    Public URL path on theshepherdsguild.com.

    With church_url_slug (the standard case):
      /PCC/sermons/2026/03/marriage-the-mission-of-god
    Without (legacy / single-tenant):
      /sermons/2026/03/marriage-the-mission-of-god

    The DB slug's trailing ISO date suffix is dropped — year/month already
    appear in the path.
    """
    seg = slug_to_url_segment(slug or "")
    prefix = f"/{church_url_slug}" if church_url_slug else ""
    if sermon_date:
        return f"{prefix}/sermons/{sermon_date.year}/{sermon_date.month:02d}/{seg}"
    return f"{prefix}/sermons/{seg}"


def _canonical_url(
    domain: str,
    sermon_date: Optional[date_type],
    slug: str,
    church_url_slug: Optional[str] = None,
) -> str:
    return f"https://{domain}{_sermon_url_path(sermon_date, slug, church_url_slug)}"


def _llms_txt(church: dict, sermon: dict, sermon_date: Optional[date_type],
              arc: list[dict]) -> str:
    """Body of the in-page <llms.txt> panel."""
    lines = [f"# {church.get('name') or ''}", ""]
    if church.get("about_short"):
        lines += [church["about_short"], ""]
    else:
        lines += [
            "A church preaching expository sermons through the books of the Bible.",
            "",
        ]
    lines.append("## Sermons")
    sermons_for_index = []
    for s in arc:
        sermons_for_index.append(s)
    sermons_for_index.append({
        "title": sermon.get("title"),
        "primary_text": sermon.get("primary_text"),
        "date": sermon.get("date"),
        "slug": sermon.get("slug"),
    })
    church_url_slug = church.get("url_slug")
    for s in sermons_for_index:
        d = _coerce_date(s.get("date"))
        url = _sermon_url_path(d, s.get("slug") or "", church_url_slug)
        bits = []
        if s.get("primary_text"):
            bits.append(s["primary_text"])
        if d:
            bits.append(d.isoformat())
        suffix = f" ({', '.join(bits)})" if bits else ""
        lines.append(f"- [{s.get('title') or ''}{suffix}]({url})")
    lines += ["", "## About", "- [About the church](/about)", "- [Plan a visit](/visit)"]
    return "\n".join(lines)


def _robots_txt(domain: str) -> str:
    return (
        "User-agent: *\n"
        "Allow: /\n\n"
        "User-agent: GPTBot\nAllow: /\n\n"
        "User-agent: ClaudeBot\nAllow: /\n\n"
        "User-agent: Google-Extended\nAllow: /\n\n"
        "User-agent: PerplexityBot\nAllow: /\n\n"
        f"Sitemap: https://{domain}/sitemap.xml"
    )


def compose(sermon_id: str) -> dict:
    """
    Assemble the full render context for one sermon. The CLI, the integration
    test, and `pipeline_batch.py process --render` all enter through here.
    """
    sermon = q.get_sermon(sermon_id)
    if not sermon:
        raise ValueError(f"Sermon not found: {sermon_id}")

    preacher = sermon.get("preachers") or {}
    church = preacher.get("churches") or {}
    address = church.get("address") or {}

    units = q.get_units_with_decomp(sermon_id)
    thesis_unit = q.find_thesis_unit(sermon, units)
    pastoral_unit = q.select_pastoral_correction_unit(units)
    artifacts = q.get_sermon_artifacts(sermon_id)

    loci = q.aggregate_loci(units)
    citations_chain, citations_total = q.roll_up_citations(units)
    illustrations = q.roll_up_illustrations(units)
    claims = q.roll_up_theological_claims(units)
    quotations = q.roll_up_quotations(units)

    # Canonical-neighbors section ("Preachers who said it like this") is
    # disabled as of 2026-05-26: matches were too unreliable to display
    # (e.g. a sermon on virtuous suffering returning Voddie Baucham on
    # Romans 1:26-27 + Mahaney on Sodom — keyword bleed, not thesis match).
    # Templates still guard with `{% if canonical_neighbors %}`, so emitting
    # an empty list cleanly hides the section without removing the markup.
    # See [[Work to be Done]] for the revisit plan.
    neighbors = []
    _ = q.get_canonical_neighbors  # keep the import wired for the revisit
    arc = q.get_three_sermon_arc(sermon)
    prior_refs = q.get_prior_pastor_refs(sermon)

    sermon_date = _coerce_date(sermon.get("date"))
    domain = church.get("domain") or "example.com"
    church_url_slug = church.get("url_slug")
    canonical_url = _canonical_url(
        domain, sermon_date, sermon.get("slug") or "", church_url_slug
    )

    # Prior-ref callout: take the most recent prior, count its book+chapter citations.
    prior_ref_summary = None
    if prior_refs:
        top = prior_refs[0]
        parsed = q.parse_passage_ref(sermon.get("primary_text"))
        cite_count = 0
        if parsed:
            cite_count = q.count_citations_for_book_chapter(
                top["id"], parsed[0], parsed[1]
            )
        prior_date = _coerce_date(top.get("date"))
        prior_ref_summary = {
            "id": top.get("id"),
            "title": top.get("title"),
            "primary_text": top.get("primary_text"),
            "date": top.get("date"),
            "date_long": _format_long_date(prior_date),
            "url": _sermon_url_path(prior_date, top.get("slug") or "", church_url_slug),
            "citation_count": cite_count,
            "book_chapter_label": f"{parsed[0]} {parsed[1]}" if parsed else None,
        }

    # Decorate arc rows with display strings.
    arc_decorated = []
    for s in arc:
        d = _coerce_date(s.get("date"))
        arc_decorated.append({
            **s,
            "date_short": _format_short_date(d),
            "url": _sermon_url_path(d, s.get("slug") or "", church_url_slug),
        })

    # Transcript meta
    transcript_chars = sum(len(u.get("content") or "") for u in units)
    word_count = transcript_chars // CHARS_PER_WORD
    reading_minutes = max(1, round(word_count / READING_WPM)) if word_count else 0

    # Transcript preview/expand split
    preview_units = units[:TRANSCRIPT_PREVIEW_UNITS]
    rest_units = units[TRANSCRIPT_PREVIEW_UNITS:]

    # Pastoral correction text comes from `summary` (Q2 = E)
    pastoral_text = None
    if pastoral_unit:
        pastoral_text = pastoral_unit.get("summary") or pastoral_unit.get("key_claim")

    # Audio: prefer our R2-hosted mirror (stable, never expires) when present,
    # else the original-host URL. The template still branches on audio_is_media
    # to render <audio> for direct MP3s vs. outbound link for sermon-page URLs.
    audio_url = sermon.get("hosted_audio_url") or sermon.get("audio_url")
    audio_is_media = bool(
        audio_url and audio_url.lower().split("?")[0].endswith(
            (".mp3", ".m4a", ".wav", ".ogg", ".aac")
        )
    )
    audio_host_label = None
    if audio_url and not audio_is_media:
        import urllib.parse as _urlparse
        host = _urlparse.urlsplit(audio_url).netloc.lower()
        audio_host_label = host[4:] if host.startswith("www.") else host

    # Memory verse — first Tier-1 citation reference if any
    memory_verse_ref = None
    for u in units:
        for c in u.get("citations") or []:
            if c.get("tier") == 1 and c.get("reference"):
                memory_verse_ref = c["reference"]
                break
        if memory_verse_ref:
            break

    # Apply tiles — slot real artifacts in when they exist; placeholders otherwise.
    apply_tiles = [dict(t) for t in APPLY_TILES]
    artifact_to_tile = {
        "small_group_questions": "small_group",
        "daily_readings": "devotional",
        "family_card": "family",
        "couples_guide": "couples",
        "memory_verse": "memory",
    }
    artifact_anchor = {
        "small_group_questions": "#artifact-small-group",
        "daily_readings": "#artifact-devotional",
        "family_card": "#artifact-family",
        "couples_guide": "#artifact-couples",
        "memory_verse": "#artifact-memory",
    }
    for t in apply_tiles:
        if t["key"] == "memory":
            t["title"] = memory_verse_ref or "Memory verse"
            t["desc"] = (
                "A verse from this sermon's primary text to commit to memory."
                if memory_verse_ref else "Coming soon."
            )
    # Overlay real artifact data onto matching tiles.
    for artifact_type, tile_key in artifact_to_tile.items():
        row = artifacts.get(artifact_type)
        if not row:
            continue
        body = row.get("body") or {}
        for t in apply_tiles:
            if t["key"] != tile_key:
                continue
            t["anchor"] = artifact_anchor[artifact_type]
            if artifact_type == "prayer_prompt":
                t["title"] = body.get("title") or "Weekly prayer prompt"
                preview = (body.get("prayer_text") or "").split("\n\n")[0][:140].rstrip()
                t["desc"] = preview + "…" if preview else t["desc"]
            elif artifact_type == "memory_verse":
                t["title"] = body.get("reference") or t["title"]
                t["desc"] = body.get("why_this_verse") or t["desc"]
            elif artifact_type == "small_group_questions":
                qs = body.get("questions") or []
                t["title"] = f"{len(qs)} discussion questions"
                if qs:
                    t["desc"] = qs[0].get("question", "")[:140].rstrip() + "…"
            elif artifact_type == "daily_readings":
                days = body.get("days") or []
                t["title"] = f"{len(days)}-day reading plan"
                t["desc"] = (body.get("intro") or
                             (days[0].get("reflection","")[:140] + "…" if days else t["desc"]))
            elif artifact_type == "family_card":
                t["title"] = body.get("title") or "Sunday-evening conversation card"
                t["desc"] = (body.get("framing_for_parents") or "")[:140].rstrip() + "…"
            elif artifact_type == "couples_guide":
                qs = body.get("questions") or []
                t["title"] = body.get("title") or "Three questions over coffee"
                t["desc"] = qs[0][:140].rstrip() + "…" if qs else t["desc"]

    # Expanded artifact sections (rendered below the tiles when present).
    # Only emit sections for artifact types we have an anchor / template
    # block for — sermons in the DB occasionally carry types like
    # `imperatives_indicatives` or `sermon_scraps` that the page template
    # doesn't yet handle. Skip those silently rather than KeyError.
    artifact_sections = []
    for artifact_type, row in artifacts.items():
        anchor = artifact_anchor.get(artifact_type)
        if not anchor:
            continue
        artifact_sections.append({
            "type": artifact_type,
            "anchor": anchor.lstrip("#"),
            "status": row.get("status"),
            "body": row.get("body") or {},
        })

    # Schema.org JSON-LD
    top_loci = [name for name, _ in loci[:3]]
    keyword_pool: list[str] = []
    if sermon.get("primary_text"):
        keyword_pool.append(sermon["primary_text"])
    keyword_pool.extend(top_loci)
    keyword_pool.append(church.get("name") or "")
    keyword_pool.append(preacher.get("name") or "")
    keyword_pool.append("expository preaching")
    keywords = [k for k in keyword_pool if k]
    jsonld = schema_org.build_jsonld(
        sermon_title=sermon.get("title") or "",
        primary_text=sermon.get("primary_text"),
        sermon_date_iso=sermon_date.isoformat() if sermon_date else None,
        series_name=sermon.get("series_name"),
        abstract=sermon.get("abstract"),
        keywords=keywords,
        canonical_url=canonical_url,
        preacher_name=preacher.get("name") or "",
        church_name=church.get("name") or "",
        church_address=address,
        loci=top_loci,
    )

    return {
        # Page-level
        "canonical_url": canonical_url,
        "url_path": _sermon_url_path(sermon_date, sermon.get("slug") or "", church_url_slug),
        "domain": domain,

        # Sermon facts
        "sermon": {
            "id": sermon.get("id"),
            "title": sermon.get("title"),
            "primary_text": sermon.get("primary_text"),
            "date_iso": sermon_date.isoformat() if sermon_date else None,
            "date_long": _format_long_date(sermon_date),
            "year": sermon_date.year if sermon_date else None,
            "series_name": sermon.get("series_name"),
            "series_position": sermon.get("series_position"),
            "sermon_type": sermon.get("sermon_type"),
            "tone": sermon.get("tone") or [],
            "hermeneutical_method": sermon.get("hermeneutical_method") or [],
            "abstract": sermon.get("abstract"),
            "main_thesis": sermon.get("main_thesis"),
            "audio_url": audio_url,
            "audio_is_media": audio_is_media,
            "audio_host_label": audio_host_label,
            "slug": sermon.get("slug"),
        },
        "preacher": {
            "name": preacher.get("name"),
            "is_canonical": preacher.get("is_canonical"),
        },
        "church": {
            "name": church.get("name"),
            "slug": church.get("slug"),
            "url_slug": church_url_slug,
            "domain": domain,
            "address": address,
            "service_times": church.get("service_times"),
            "brand_color": church.get("brand_color"),
            "about_short": church.get("about_short"),
        },

        # Pastoral correction
        "pastoral_correction": (
            {
                "unit_index": pastoral_unit.get("unit_index"),
                "text": pastoral_text,
            }
            if pastoral_unit and pastoral_text else None
        ),

        # Outline / decomp blocks
        "loci_counts": loci,
        "loci_total": len(loci),
        "citations_chain": citations_chain,
        "citations_total": citations_total,
        "illustrations": illustrations,
        "theological_claims": claims,
        "quotations": quotations,

        # Transcript
        "transcript_units": units,
        "transcript_preview_units": preview_units,
        "transcript_rest_units": rest_units,
        "transcript_chars": transcript_chars,
        "transcript_unit_count": len(units),
        "reading_minutes": reading_minutes,

        # Arc + prior refs + neighbors
        "arc": arc_decorated,
        "prior_ref": prior_ref_summary,
        "canonical_neighbors": neighbors,

        # Discuss / apply tiles (placeholders per Q10; overlaid with real
        # artifacts above when sermon_artifacts rows exist).
        "apply_tiles": apply_tiles,
        "artifact_sections": artifact_sections,
        # Raw {artifact_type: row} dict for templates that want to slot
        # specific artifacts in directly (e.g., the email digest).
        "artifacts": artifacts,

        # Crawler hygiene
        "robots_txt": _robots_txt(domain),
        "llms_txt": _llms_txt(church, sermon, sermon_date, arc),

        # Schema.org
        "jsonld_string": jsonld,

        # Footer / generation meta
        "generated_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "decomposed_at": sermon.get("decomposed_at"),
        "decomposition_model": sermon.get("decomposition_model"),
    }
