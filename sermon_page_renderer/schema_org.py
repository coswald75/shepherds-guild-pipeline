"""
Schema.org JSON-LD builder for sermon pages.

Pure function from a composer dict to a JSON string. The template inlines
the result into a `<script type="application/ld+json">` block.

Reference Schema.org types used:
  Article — the sermon itself
  CreativeWorkSeries — sermon series (if set)
  Person — the preacher
  Church — both the publisher and the preacher's worksFor
  PostalAddress, GeoCoordinates — church location
"""

from __future__ import annotations

import json
from typing import Optional


def build_jsonld(
    *,
    sermon_title: str,
    primary_text: Optional[str],
    sermon_date_iso: Optional[str],
    series_name: Optional[str],
    abstract: Optional[str],
    keywords: list[str],
    canonical_url: str,
    preacher_name: str,
    church_name: str,
    church_address: Optional[dict],
    loci: list[str],
) -> str:
    """
    Construct the JSON-LD struct and serialize as a stable JSON string.

    `church_address` is the JSONB blob from `churches.address` — expected keys:
      locality, region, country, lat, lng (any may be absent).
    `keywords` and `loci` are caller-prepared lists.
    """
    article: dict = {
        "@context": "https://schema.org",
        "@type": "Article",
        "headline": sermon_title,
    }
    if primary_text:
        article["alternativeHeadline"] = primary_text
    if sermon_date_iso:
        article["datePublished"] = sermon_date_iso
    article["inLanguage"] = "en"

    if series_name:
        article["isPartOf"] = {
            "@type": "CreativeWorkSeries",
            "name": series_name,
        }

    article["author"] = {
        "@type": "Person",
        "name": preacher_name,
        "jobTitle": "Pastor",
        "worksFor": {
            "@type": "Church",
            "name": church_name,
        },
    }

    publisher: dict = {
        "@type": "Church",
        "name": church_name,
    }
    if church_address:
        postal: dict = {"@type": "PostalAddress"}
        for src, dst in (("locality", "addressLocality"),
                         ("region", "addressRegion"),
                         ("country", "addressCountry")):
            v = church_address.get(src)
            if v:
                postal[dst] = v
        if len(postal) > 1:  # has more than just @type
            publisher["address"] = postal

        lat = church_address.get("lat")
        lng = church_address.get("lng")
        if lat is not None and lng is not None:
            publisher["geo"] = {
                "@type": "GeoCoordinates",
                "latitude": lat,
                "longitude": lng,
            }
    article["publisher"] = publisher

    if loci:
        article["about"] = [{"@type": "Thing", "name": locus} for locus in loci]
    if abstract:
        article["abstract"] = abstract
    if keywords:
        article["keywords"] = ", ".join(keywords)
    article["mainEntityOfPage"] = canonical_url

    return json.dumps(article, indent=2, ensure_ascii=False)
