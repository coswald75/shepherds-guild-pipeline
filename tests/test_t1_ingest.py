"""T1 cheap ingest — no secrets, no Anthropic, no network."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
FIXTURES = REPO / "fixtures" / "t1"
CLI = REPO / "t1_ingest.py"

from t1.acquire import acquire_path, html_to_text, iter_sermon_files
from t1.chunker import chunk_sermon
from t1.cost import estimate_t1_cost, estimate_t2_cost
from t1.index import build_keyword_index, search_index
from t1.pipeline import ingest_paths, structure_sermon
from t1.promote import promote_record, t2_command
from t1.style import discern_style, label_set_doc, ministry_profile


def test_fixtures_exist_for_ci_without_secrets():
    files = iter_sermon_files(FIXTURES)
    assert len(files) >= 5
    assert (FIXTURES / "heading-blessing.txt").exists()


def test_acquire_txt_header_and_html_json():
    heading = acquire_path(FIXTURES / "heading-blessing.txt")
    assert heading.preacher == "Fixture Preacher"
    assert heading.title == "Hearing and Keeping the Word"
    assert "sign of Jonah" in heading.text

    html = acquire_path(FIXTURES / "html-ligonier-style.json")
    assert html.source_kind == "html"
    assert "## Receiving a Greater Blessing" in html.text or "# Receiving a Greater Blessing" in html.text
    assert "<h4>" not in html.text
    assert "sign of Jonah" in html.text


def test_html_to_text_keeps_headings():
    text = html_to_text("<p>Intro</p><h4>Point One</h4><p>Body</p>")
    assert "Point One" in text
    assert "#### Point One" in text or "### Point One" in text
    assert "<p>" not in text


def test_heading_chunker():
    sermon = acquire_path(FIXTURES / "heading-blessing.txt")
    chapters = chunk_sermon(sermon)
    assert len(chapters) >= 3
    assert {c.source for c in chapters} == {"heading"}
    titles = " ".join(c.title for c in chapters).lower()
    assert "blessing" in titles
    assert "sign" in titles
    for ch in chapters:
        assert 0 <= ch.char_start < ch.char_end <= len(sermon.text)
        assert ch.text
        assert ch.start_ms is None


def test_discourse_chunker():
    sermon = acquire_path(FIXTURES / "discourse-three-words.txt")
    chapters = chunk_sermon(sermon)
    assert len(chapters) >= 3
    assert {c.source for c in chapters} == {"discourse"}
    blob = " ".join(c.text.lower() for c in chapters)
    assert "redemption" in blob
    assert "propitiation" in blob
    assert "justification" in blob


def test_window_chunker_has_offsets():
    sermon = acquire_path(FIXTURES / "plain-window.txt")
    chapters = chunk_sermon(sermon)
    assert len(chapters) >= 2
    assert all(c.source == "window" for c in chapters)
    for ch in chapters:
        assert sermon.text[ch.char_start:ch.char_end].strip()
        assert ch.char_end > ch.char_start


def test_window_chunker_splits_single_paragraph_stt_blob():
    """AssemblyAI transcripts are often one long paragraph with no blank lines."""
    from t1.acquire import acquire_text

    sentence = (
        "The Word became flesh and dwelt among us, and we have seen his glory. "
    )
    text = sentence * 80  # ~720 words, one paragraph
    sermon = acquire_text(text, title="STT Blob", preacher="Fixture")
    chapters = chunk_sermon(sermon)
    assert len(chapters) >= 2
    assert all(c.source == "window" for c in chapters)
    assert sum(_approx_words(c.text) for c in chapters) >= 600


def _approx_words(text: str) -> int:
    return len(text.split())


def test_sidecar_timestamps_preferred():
    sermon = acquire_path(FIXTURES / "sidecar-chapters.json")
    assert len(sermon.sidecar_chapters) == 3
    chapters = chunk_sermon(sermon)
    assert len(chapters) == 3
    assert all(c.source == "sidecar" for c in chapters)
    assert chapters[0].start_ms == 0
    assert chapters[0].end_ms == 180000
    assert chapters[2].end_ms == 480000
    assert "justification" in chapters[2].text.lower()


def test_structure_never_lists_anthropic(tmp_path):
    acquired = acquire_path(FIXTURES / "sermonindex-nicene.json")
    _, payload = structure_sermon(acquired, embed=False)
    assert payload["tier"] == "T1"
    assert payload["cost"]["usd_estimate"] == 0.0
    assert payload["cost"]["apis_called"] == []
    assert "anthropic" not in json.dumps(payload).lower() or payload["apis_forbidden"] == ["anthropic"]
    assert payload["promote"]["command"].startswith("python pipeline.py decompose")


def test_keyword_search_finds_justification(tmp_path):
    results = ingest_paths(
        list(iter_sermon_files(FIXTURES)),
        output_dir=tmp_path,
        embed=False,
    )
    assert len(results) >= 5
    index = json.loads((tmp_path / "index.json").read_text())
    hits = search_index(index, "justification redemption")
    assert hits
    assert hits[0]["score"] > 0
    report = json.loads((tmp_path / "run_report.json").read_text())
    assert report["anthropic_called"] is False
    assert report["t1_usd_total"] == 0.0


def test_embed_without_key_stays_keyword(monkeypatch):
    monkeypatch.delenv("VOYAGE_API_KEY", raising=False)
    acquired = acquire_path(FIXTURES / "heading-blessing.txt")
    _, payload = structure_sermon(acquired, embed=True)
    assert payload["index"]["kind"] == "keyword"
    assert payload["index"]["embedding_dims"] is None
    assert "voyage.embed" not in payload["cost"]["apis_called"]


def test_cost_model_t1_cheaper_than_t2():
    t1 = estimate_t1_cost(has_source_text=True, embed=False, char_count=20000, chapter_count=10)
    t2 = estimate_t2_cost()
    assert t1["usd_estimate"] == 0.0
    assert t2["usd_range"][0] >= 0.20
    t1_embed = estimate_t1_cost(has_source_text=True, embed=True, char_count=20000, chapter_count=10)
    assert t1_embed["usd_estimate"] < 0.01


def test_promote_stub_does_not_call_t2():
    record = promote_record({
        "sermon_id": "x",
        "title": "Demo",
        "preacher": "Fixture Preacher",
        "source_path": "fixtures/t1/heading-blessing.txt",
    })
    assert record["status"] == "stub"
    assert "pipeline.py decompose" in record["command"]
    assert t2_command("sermon.txt", "Jane Doe").endswith('--preacher "Jane Doe" --dry-run')


def test_cli_batch_and_search(tmp_path):
    out = tmp_path / "t1_output"
    proc = subprocess.run(
        [sys.executable, str(CLI), "batch", str(FIXTURES), "--output", str(out)],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert "T1 structured" in proc.stdout
    assert (out / "index.json").exists()
    assert (out / "run_report.json").exists()
    sermons = list((out / "sermons").glob("*.json"))
    assert len(sermons) >= 5

    search = subprocess.run(
        [sys.executable, str(CLI), "search", "Jonah", "--index", str(out / "index.json")],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    )
    assert search.returncode == 0, search.stderr
    assert "Jonah" in search.stdout or "jonah" in search.stdout.lower() or search.stdout.strip() != "no hits"

    promote = subprocess.run(
        [sys.executable, str(CLI), "promote", str(sermons[0]), "--output", str(out)],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    )
    assert promote.returncode == 0, promote.stderr
    assert "pipeline.py decompose" in promote.stdout
    assert list((out / "promote").glob("*.promote.json"))


def test_style_continuous_exposition():
    sermon = acquire_path(FIXTURES / "continuous-romans8.txt")
    style = discern_style(sermon.text, title=sermon.title)
    assert style["living_likeness_score"] is None
    assert style["not_coach_product"] is True
    assert style["axes"]["text_relationship"]["label"] == "continuous_exposition"
    ev = style["axes"]["text_relationship"]["evidence"]
    assert ev and ev[0]["quote"]
    assert ev[0]["char_end"] > ev[0]["char_start"]
    assert style["axes"]["fallen_condition_focus"]["label"] == "fcf_gospel"


def test_style_topical_tips_individual():
    sermon = acquire_path(FIXTURES / "topical-tips-habits.txt")
    style = discern_style(sermon.text, title=sermon.title)
    assert style["axes"]["text_relationship"]["label"] == "topical"
    assert style["axes"]["fallen_condition_focus"]["label"] == "tips_imperatives"
    assert style["axes"]["application_shape"]["audience"] == "individual"
    assert style["axes"]["redemptive_frame"]["label"] != "redemptive_historical"


def test_style_narrative_moral():
    sermon = acquire_path(FIXTURES / "narrative-david.txt")
    style = discern_style(sermon.text, title=sermon.title)
    assert style["axes"]["text_relationship"]["label"] == "narrative"
    assert style["axes"]["redemptive_frame"]["label"] == "moral_exemplary"
    school = style["axes"]["redemptive_frame"].get("school_illustration") or {}
    assert "likeness" in (school.get("note") or "").lower()


def test_style_fcf_on_gospel_words():
    sermon = acquire_path(FIXTURES / "discourse-three-words.txt")
    style = discern_style(sermon.text, title=sermon.title)
    assert style["axes"]["fallen_condition_focus"]["label"] == "fcf_gospel"
    assert style["axes"]["redemptive_frame"]["label"] in {
        "redemptive_historical", "doctrinal_systematic",
    }


def test_style_never_scores_living_likeness():
    sermon = acquire_path(FIXTURES / "heading-blessing.txt")
    _, payload = structure_sermon(sermon)
    style = payload["style"]
    assert style["living_likeness_score"] is None
    dump = json.dumps(style)
    # Keller may appear only inside school_illustration, never as a score key.
    if "Keller" in dump:
        assert "school_illustration" in dump
    assert style["primary_axis"] == "category"
    assert "preacher_similarity" not in dump
    assert "nearest_neighbor" not in dump


def test_no_style_flag_omits_block(tmp_path):
    results = ingest_paths(
        [FIXTURES / "heading-blessing.txt"],
        output_dir=tmp_path,
        style=False,
    )
    assert results[0].payload.get("style") is None


def test_ministry_profile_and_cli_styles(tmp_path):
    results = ingest_paths(list(iter_sermon_files(FIXTURES)), output_dir=tmp_path)
    assert results
    index = json.loads((tmp_path / "index.json").read_text())
    profile = index["ministry_profile"]
    assert profile["sermons"] >= 8
    assert profile["living_likeness_score"] is None
    assert profile["majority"]["text_relationship"]
    report = json.loads((tmp_path / "run_report.json").read_text())
    assert report["style_enabled"] is True

    proc = subprocess.run(
        [sys.executable, str(CLI), "styles", "--index", str(tmp_path / "index.json")],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert "living_likeness_score: None" in proc.stdout
    assert "ministry profile" in proc.stdout

    labels = label_set_doc()
    assert "continuous_exposition" in labels["axes"]["text_relationship"]
    assert labels["cost_usd"] == 0.0
    rolled = ministry_profile([r.payload["style"] for r in results])
    assert rolled["question"].startswith("what kind of preaching")


def test_cli_does_not_import_production_pipeline():
    # The module must be importable without anthropic/voyage/supabase.
    src = (REPO / "t1_ingest.py").read_text()
    assert "import pipeline" not in src
    assert "from pipeline" not in src
    assert "import anthropic" not in src
    assert "import weekly_ingest" not in src
    assert "from weekly_ingest" not in src
