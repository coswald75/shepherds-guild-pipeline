"""
Integration test — render the *Growing in Christ* sermon end-to-end.

Hits the live Supabase corpus (`twbunmbzyqcqzgffdrib`). Skipped automatically
when SUPABASE_URL / SUPABASE_KEY are not present (e.g., on CI without secrets).

Assertions are structural — not byte-for-byte against the demo HTML.
The demo HTML in Sermon Steward/ was hand-curated; real rendered output
diverges in details (pastoral-correction unit, transcript truncation point,
exact arc sermons) and that divergence is intentional per the V1 spec.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

import pytest
from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parent.parent

# Load .env before the skip-mark sees the env vars (otherwise tests would skip
# on a clean Python session even when .env exists).
load_dotenv(REPO_ROOT / ".env", override=True)

SERMON_ID = "cd42ce5d-3813-42a9-97c0-c7adaf809eb5"
EXPECTED_TITLE = "Growing in Christ"
EXPECTED_PRIMARY_TEXT = "Ephesians 4:11-16"
EXPECTED_PREACHER = "Chris Oswald"
EXPECTED_CHURCH = "Providence Community Church"
EXPECTED_CANONICAL = (
    "https://providencecommunitychurch.example/sermons/2026/02/growing-in-christ"
)

LIVE_DB = bool(os.getenv("SUPABASE_URL") and os.getenv("SUPABASE_KEY"))
requires_db = pytest.mark.skipif(
    not LIVE_DB, reason="SUPABASE_URL / SUPABASE_KEY not set"
)


@pytest.fixture(scope="module")
def rendered_html() -> str:
    from sermon_page_renderer.composer import compose
    from sermon_page_renderer.template_engine import render_sermon_page

    context = compose(SERMON_ID)
    return render_sermon_page(context)


@requires_db
class TestSermonPageStructure:
    def test_html_doctype(self, rendered_html: str):
        assert rendered_html.startswith("<!DOCTYPE html>")

    def test_title_and_meta(self, rendered_html: str):
        assert f"<title>{EXPECTED_TITLE} — Pastor {EXPECTED_PREACHER}" in rendered_html
        assert f'<meta property="og:title" content="{EXPECTED_TITLE}' in rendered_html
        assert f'<meta property="og:site_name" content="{EXPECTED_CHURCH}">' in rendered_html

    def test_canonical_link(self, rendered_html: str):
        assert f'<link rel="canonical" href="{EXPECTED_CANONICAL}">' in rendered_html
        assert f'<meta property="og:url" content="{EXPECTED_CANONICAL}">' in rendered_html

    def test_sermon_hero(self, rendered_html: str):
        assert f">{EXPECTED_TITLE}</h1>" in rendered_html
        assert f"<strong>{EXPECTED_PRIMARY_TEXT}</strong>" in rendered_html
        assert "February 22, 2026" in rendered_html
        assert f"Pastor {EXPECTED_PREACHER}" in rendered_html

    def test_thesis_block_present(self, rendered_html: str):
        assert 'class="thesis-hero"' in rendered_html
        assert "All growth" in rendered_html  # opening words of main_thesis

    def test_facts_strip(self, rendered_html: str):
        assert "Expository" in rendered_html
        assert "<span class=\"chip\">pastoral</span>" in rendered_html

    def test_pastoral_correction_present(self, rendered_html: str):
        # Per Q3, an application unit is picked — there are 12 in this sermon.
        assert 'class="pastoral-correction"' in rendered_html
        assert "Pastoral correction · unit #" in rendered_html

    def test_outline_blocks(self, rendered_html: str):
        assert "Doctrinal loci" in rendered_html
        # 11 loci surface in this sermon per the session summary
        assert "11 surfaced" in rendered_html
        # MacArthur-dominated top-3 chips highlighted
        assert "Ecclesiology · 21" in rendered_html
        assert "Christology · 14" in rendered_html
        assert "Sanctification · 10" in rendered_html

    def test_citation_chain(self, rendered_html: str):
        assert "Bible citations" in rendered_html
        assert "Ephesians 4:11-16" in rendered_html
        assert "Matthew 7:24-27" in rendered_html
        assert "1 Peter 2:9" in rendered_html

    def test_illustrations_section(self, rendered_html: str):
        assert "Illustrations" in rendered_html
        assert "personal story" in rendered_html

    def test_theological_claims_section(self, rendered_html: str):
        assert "Theological claims" in rendered_html
        # Five claims per session summary, but the count is also rendered
        assert ">Theological claims<" in rendered_html

    def test_quotations_section(self, rendered_html: str):
        assert "Quotations" in rendered_html
        # Per session summary: 2 quotations, both attributed to "a revitalization pastor"
        assert "revitalization pastor" in rendered_html

    def test_transcript_renders_all_units_with_anchors(self, rendered_html: str):
        # 39 units total; the reading-time strip should reflect this
        assert "<strong>39</strong> units" in rendered_html
        # Unit anchors render as id="unit-N"
        anchor_count = len(re.findall(r'id="unit-\d+"', rendered_html))
        assert anchor_count == 39, f"expected 39 unit anchors, got {anchor_count}"

    def test_transcript_preview_and_expand(self, rendered_html: str):
        # First N units are visible; the rest are wrapped in a hidden div.
        assert 'id="tx-rest"' in rendered_html
        assert "Expand the remaining" in rendered_html

    def test_three_sermon_arc(self, rendered_html: str):
        assert "Recent preaching context" in rendered_html
        # Verified arc sermons for Growing in Christ (apostrophes get HTML-escaped)
        for prior in [
            "Gospel Unity",
            "God&#39;s Cosmic Construction Project",
            "Walking in Faith",
        ]:
            assert prior in rendered_html, f"missing arc sermon: {prior}"

    def test_prior_pastor_ref_echo_card(self, rendered_html: str):
        assert "Earlier in the corpus" in rendered_html
        # The notable 2017 sermon on Eph 4:1-16
        assert "Ephesians 4:1-16" in rendered_html

    def test_canonical_neighbors_top_5(self, rendered_html: str):
        # Session-summary documented top-5: MacArthur×3 + Ferguson + Stott
        assert "Related teaching" in rendered_html
        for name in [
            "John MacArthur",
            "Sinclair Ferguson",
            "John Stott",
        ]:
            assert name in rendered_html, f"missing neighbor preacher: {name}"
        assert "Keys to Spiritual Growth - Part 6" in rendered_html
        # Top distance ~0.20 per session summary
        assert re.search(r"·\s*0\.20", rendered_html), "expected ~0.20 top distance"

    def test_apply_tiles(self, rendered_html: str):
        # All six placeholder tiles per Q10
        for label in ["Small groups", "Daily readings", "Prayer",
                      "Family table", "Couples", "Memorize"]:
            assert label in rendered_html, f"missing tile: {label}"

    def test_church_card(self, rendered_html: str):
        assert "About the church" in rendered_html
        assert EXPECTED_CHURCH in rendered_html
        assert "Kansas City" in rendered_html
        assert "Sundays" in rendered_html  # service times

    def test_crawler_panel_contents(self, rendered_html: str):
        # Ampersand is HTML-escaped in the rendered output.
        assert "Crawler &amp; AI-search policy" in rendered_html
        assert "ClaudeBot" in rendered_html
        assert "GPTBot" in rendered_html
        assert "PerplexityBot" in rendered_html
        assert "Sitemap: https://providencecommunitychurch.example/sitemap.xml" in rendered_html

    def test_no_publish_bar(self, rendered_html: str):
        # Per Q8 — publish bar omitted from production renders.
        assert "publish-bar" not in rendered_html
        assert "publishBar" not in rendered_html

    def test_footer_attribution(self, rendered_html: str):
        assert "<strong>Pastor Chris Oswald</strong>" in rendered_html
        assert "<strong>Providence Community Church</strong>" in rendered_html
        assert "<strong>February 22, 2026</strong>" in rendered_html


@requires_db
class TestSchemaOrgJsonLD:
    @pytest.fixture
    def jsonld(self, rendered_html: str) -> dict:
        # Extract the JSON-LD blob from the rendered HTML
        m = re.search(
            r'<script type="application/ld\+json">\s*(\{.*?\})\s*</script>',
            rendered_html,
            re.DOTALL,
        )
        assert m, "JSON-LD <script> block not found"
        return json.loads(m.group(1))

    def test_top_level_types(self, jsonld: dict):
        assert jsonld["@context"] == "https://schema.org"
        assert jsonld["@type"] == "Article"

    def test_required_fields(self, jsonld: dict):
        assert jsonld["headline"] == EXPECTED_TITLE
        assert jsonld["alternativeHeadline"] == EXPECTED_PRIMARY_TEXT
        assert jsonld["datePublished"] == "2026-02-22"

    def test_author(self, jsonld: dict):
        author = jsonld["author"]
        assert author["@type"] == "Person"
        assert author["name"] == EXPECTED_PREACHER
        assert author["worksFor"]["@type"] == "Church"
        assert author["worksFor"]["name"] == EXPECTED_CHURCH

    def test_publisher_has_address_and_geo(self, jsonld: dict):
        publisher = jsonld["publisher"]
        assert publisher["@type"] == "Church"
        assert publisher["name"] == EXPECTED_CHURCH
        assert publisher["address"]["addressLocality"] == "Kansas City"
        assert publisher["address"]["addressRegion"] == "MO"
        assert publisher["geo"]["@type"] == "GeoCoordinates"
        assert abs(publisher["geo"]["latitude"] - 39.0997) < 0.01
        assert abs(publisher["geo"]["longitude"] - (-94.5786)) < 0.01

    def test_about_has_loci(self, jsonld: dict):
        names = {a["name"] for a in jsonld["about"]}
        assert "Ecclesiology" in names
        assert "Christology" in names
        assert "Sanctification" in names

    def test_canonical_url(self, jsonld: dict):
        assert jsonld["mainEntityOfPage"] == EXPECTED_CANONICAL


@requires_db
class TestCanonicalNeighborsDedup:
    """One row per sermon, no duplicates by (preacher, title)."""

    def test_dedup_by_preacher_and_title(self):
        from sermon_page_renderer import queries as q
        from sermon_page_renderer.composer import compose

        ctx = compose(SERMON_ID)
        neighbors = ctx["canonical_neighbors"]
        keys = [(n["preacher_name"], n["title"]) for n in neighbors]
        assert len(keys) == len(set(keys)), f"duplicates in neighbors: {keys}"
        assert len(neighbors) <= 5
