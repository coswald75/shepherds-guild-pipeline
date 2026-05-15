"""Unit tests for sermon_page_renderer/slug.py."""

from datetime import date

import pytest

from sermon_page_renderer.slug import (
    MAX_SLUG_LEN,
    church_slug,
    sermon_slug,
    slug_to_url_segment,
    slugify,
    uniquify_slug,
)


class TestSlugify:
    def test_simple_lowercase(self):
        assert slugify("Hello World") == "hello-world"

    def test_already_a_slug(self):
        assert slugify("already-a-slug") == "already-a-slug"

    def test_collapses_multiple_spaces(self):
        assert slugify("hello   world") == "hello-world"

    def test_strips_punctuation(self):
        assert slugify("Growing in Christ!") == "growing-in-christ"

    def test_handles_diacritics(self):
        assert slugify("Café Society") == "cafe-society"

    def test_em_and_en_dashes(self):
        assert slugify("title — with — dashes") == "title-with-dashes"
        assert slugify("title – range") == "title-range"

    def test_smart_quotes(self):
        # Curly apostrophes/quotes get dropped entirely (NFKD leaves them as-is,
        # ASCII-strip removes them) — they don't leave a hyphen separator.
        assert slugify("the pastor’s word") == "the-pastors-word"
        assert slugify("“Quote”") == "quote"

    def test_leading_and_trailing_punctuation(self):
        assert slugify("...title...") == "title"
        assert slugify("---title---") == "title"

    def test_empty_string(self):
        assert slugify("") == ""

    def test_only_punctuation(self):
        assert slugify("!!!") == ""

    def test_unicode_only_returns_empty(self):
        # No ASCII content survives — slug is empty (caller falls back).
        assert slugify("中文") == ""

    def test_respects_max_len(self):
        long_text = "growing in christ " * 10
        result = slugify(long_text, max_len=30)
        assert len(result) <= 30
        assert not result.startswith("-")
        assert not result.endswith("-")

    def test_truncates_at_word_boundary_when_possible(self):
        # "the-quick-brown-fox" truncated to 13 should cut at a hyphen
        result = slugify("the quick brown fox", max_len=13)
        # Should be "the-quick" (9), not "the-quick-bro" (13 mid-word)
        assert result == "the-quick"

    def test_truncation_strips_trailing_dash(self):
        # If naive truncation would leave a trailing dash, it must be stripped.
        result = slugify("abc-def-ghi", max_len=4)
        assert not result.endswith("-")


class TestChurchSlug:
    def test_basic(self):
        assert church_slug("Providence Community Church") == "providence-community-church"

    def test_diacritics(self):
        assert church_slug("Iglesia San José") == "iglesia-san-jose"

    def test_punctuation(self):
        assert church_slug("St. John's Reformed Church") == "st-john-s-reformed-church"

    def test_empty(self):
        assert church_slug("") == ""
        assert church_slug(None) == ""  # type: ignore[arg-type]


class TestSermonSlug:
    def test_with_date(self):
        assert sermon_slug("Growing in Christ", date(2026, 2, 22)) == "growing-in-christ-2026-02-22"

    def test_without_date(self):
        assert sermon_slug("Growing in Christ", None) == "growing-in-christ"

    def test_empty_title_with_date(self):
        # Date alone is a valid slug when title is empty
        assert sermon_slug("", date(2026, 2, 22)) == "2026-02-22"

    def test_empty_title_no_date(self):
        assert sermon_slug("", None) == "untitled-sermon"
        assert sermon_slug(None, None) == "untitled-sermon"

    def test_long_title_truncates_to_fit_with_date(self):
        # Even with a long title, total slug stays within MAX_SLUG_LEN
        long_title = "A Very Very Very Very Very Very Very Long Sermon Title That Goes On Forever"
        s = sermon_slug(long_title, date(2026, 2, 22))
        assert len(s) <= MAX_SLUG_LEN
        assert s.endswith("2026-02-22")

    def test_special_chars_in_title(self):
        assert sermon_slug("Sermon #5: \"The Way\"", date(2026, 1, 1)) == "sermon-5-the-way-2026-01-01"


class TestSlugToUrlSegment:
    def test_strips_iso_date_suffix(self):
        assert slug_to_url_segment("growing-in-christ-2026-02-22") == "growing-in-christ"

    def test_keeps_slug_without_date(self):
        assert slug_to_url_segment("growing-in-christ") == "growing-in-christ"

    def test_only_strips_trailing_iso_date(self):
        # Embedded dates are kept; only a trailing YYYY-MM-DD is stripped.
        assert slug_to_url_segment("sermon-2026-02-22-on-faith") == "sermon-2026-02-22-on-faith"

    def test_empty(self):
        assert slug_to_url_segment("") == ""


class TestUniquifySlug:
    def test_no_collision_returns_unchanged(self):
        assert uniquify_slug("foo", set()) == "foo"
        assert uniquify_slug("foo", {"bar", "baz"}) == "foo"

    def test_first_collision_returns_2(self):
        assert uniquify_slug("foo", {"foo"}) == "foo-2"

    def test_chain_of_collisions(self):
        assert uniquify_slug("foo", {"foo", "foo-2"}) == "foo-3"
        assert uniquify_slug("foo", {"foo", "foo-2", "foo-3", "foo-4"}) == "foo-5"

    def test_long_base_trimmed_to_fit_suffix(self):
        long_base = "a" * MAX_SLUG_LEN
        existing = {long_base}
        result = uniquify_slug(long_base, existing)
        assert len(result) <= MAX_SLUG_LEN
        assert result.endswith("-2")
