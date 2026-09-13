"""T1 fidelity-slice harvest — no secrets, no Anthropic, no network."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from t1.fidelity import (
    COST_USD,
    attribute_sermon,
    harvest_folder,
    score_sermon,
    write_bundle,
)

REPO = Path(__file__).resolve().parents[1]
CLI = REPO / "t1_ingest.py"
STOTT = REPO / "sermon-transcripts" / "john-stott"


def test_attribute_historical_sermonindex():
    text = (
        "My own desire, brethren, in these Bible hours, is that we hear the word of God. "
        "As an Anglican clergyman I prefer the Authorized Version on your lap."
    )
    attr = attribute_sermon(
        text=text,
        metadata={
            "id": "j33UOzcFk_HCYQpF",
            "title": "Great Commission - Part 1",
            "audioUrl": "http://archive.org/download/SERMONINDEX_SID11785/SID11785.mp3",
        },
        source_path="sermon-transcripts/john-stott/j33UOzcFk_HCYQpF.json",
    )
    assert attr["attribution"] == "historical_stott"
    assert attr["confidence"] >= 0.8
    assert any("SermonIndex" in r or "hash" in r.lower() or "Urbana" in r for r in attr["reasons"])


def test_attribute_all_souls_contemporary():
    text = (
        "In our morning services at All Souls we are commemorating the Nicene Creed, "
        "written 1700 years ago. Look it up on Instagram later. We were on Zoom last week. "
        "John Stott, who was a famous preacher and author who used to work at this church, "
        "once said something similar."
    )
    attr = attribute_sermon(
        text=text,
        metadata={
            "id": "19f30267-6268-42f3-ad8a-888c14bec1c2",
            "title": "The Son (John 1:1–18)",
            "date": "Sun, 03 Aug 2025 12:00:00 GMT",
            "_source": {
                "method": "sermon_scraper",
                "source_url": "https://www.allsouls.org/Media/Player.aspx?media_id=347773",
            },
        },
        source_path="sermon-transcripts/john-stott/the-son-john-1118.json",
    )
    assert attr["attribution"] == "all_souls_contemporary"
    assert attr["confidence"] >= 0.75
    assert not any("historical:" in r for r in attr["reasons"])


def test_attribute_uncertain_when_empty():
    attr = attribute_sermon(text="A short untitled talk about kindness.", metadata={}, source_path="")
    assert attr["attribution"] == "uncertain"


def test_a1_classic_vs_egal_vs_no_hit():
    classic = score_sermon(
        "Paul writes in 1 Timothy 2:12, I do not permit a woman to teach or "
        "to have authority over a man; she must be silent. This is the creation order, "
        "Adam was formed first, then Eve. Women should not teach in the assembly.",
        title="1 Timothy 2",
    )
    assert classic["axes"]["A1"]["hit"] is True
    assert classic["axes"]["A1"]["band"] == "classic_complementarian"

    egal = score_sermon(
        "People worry about 1 Timothy 2. I think women can and should teach. "
        "Paul was only addressing a local problem; the text is culturally bound.",
        title="Women in ministry",
    )
    assert egal["axes"]["A1"]["band"] == "egalitarian_reframing"

    silent = score_sermon("We continue our series in Mark's gospel. Jesus heals a man.", title="Mark 2")
    assert silent["axes"]["A1"]["band"] == "avoided_or_no_hit"
    assert silent["axes"]["A1"]["hit"] is False


def test_a2_undercalls_citation_only():
    row = score_sermon(
        "Please open Ephesians 5. We will come back to that household later.",
        title="Walk in love",
    )
    # Citation without stance must not invent complementarian or egalitarian drift.
    assert row["axes"]["A2"]["band"] == "avoided_or_no_hit"


def test_a2_classic_headship():
    row = score_sermon(
        "In Ephesians 5:22, wives are to submit to their husbands. "
        "The husband is the head of the wife as the church submits to Christ. "
        "This headship in marriage is not optional.",
        title="Ephesians 5",
    )
    assert row["axes"]["A2"]["band"] == "classic_complementarian"
    assert row["axes"]["A2"]["evidence"]


def test_b1_stout_vs_thinned_vs_no_hit():
    stout = score_sermon(
        "Where was God in the tragedy? He is sovereign even over suffering. "
        "He ordained this hour and meant it for good; he works all things together for good.",
        title="Providence",
    )
    assert stout["axes"]["B1"]["band"] == "stout_providence"

    thin = score_sermon(
        "Where was God? God would never cause evil. Suffering is only because of our free will. "
        "God does not ordain tragedy.",
        title="Why suffering",
    )
    assert thin["axes"]["B1"]["band"] == "thinned_freewill"

    quiet = score_sermon("Jesus told a parable about seeds.", title="Soils")
    assert quiet["axes"]["B1"]["band"] == "unclear_or_no_hit"


def test_b3_judicial_vs_emptied():
    judicial = score_sermon(
        "The wrath of God is real. Hell is real. God will judge the impenitent. "
        "This is the day of judgment and eternal punishment.",
        title="Judgment",
    )
    assert judicial["axes"]["B3"]["band"] == "judicial_retained"

    empty = score_sermon(
        "People talk about the wrath of God, but there is no hell. "
        "God is only love and never judges. There is no angry God.",
        title="Love only",
    )
    assert empty["axes"]["B3"]["band"] == "emptied_or_silent"


def test_b3_ignores_what_the_hell():
    row = score_sermon("What the hell were they thinking on that fishing trip?", title="Anecdote")
    assert row["axes"]["B3"]["band"] == "unclear_or_no_hit"


def test_b4_guilt_not_wound_only_when_repentance_present():
    guilt = score_sermon(
        "We are sinners, guilty before God. We need the forgiveness of our sins. "
        "Repentance is the door. Our bad conscience is not healed by therapy alone.",
        title="Guilt",
    )
    assert guilt["axes"]["B4"]["band"] == "guilt_before_god"

    wound = score_sermon(
        "You are not guilty. Sin is just a wound. Trauma and inner brokenness "
        "are the real story; shame, not guilt, is what God heals.",
        title="Wound",
    )
    assert wound["axes"]["B4"]["band"] == "wound_only"

    mixed = score_sermon(
        "We are guilty before God and need repentance and the forgiveness of our sins. "
        "We also carry trauma and brokenness and systemic injustice.",
        title="Both",
    )
    assert mixed["axes"]["B4"]["band"] == "mixed"


def test_b5_exclusive_vs_pluralist():
    hard = score_sermon(
        "Jesus said in John 14:6, no one comes to the Father except through me. "
        "There is no other name under heaven. Only through Christ.",
        title="The way",
    )
    assert hard["axes"]["B5"]["band"] == "exclusive_hard"

    plural = score_sermon(
        "Other religions are many paths. Sincere seekers will be saved. "
        "Islam is also a valid path to God. John 14:6 is just our way of speaking.",
        title="Many ways",
    )
    assert plural["axes"]["B5"]["band"] == "soft_pluralist"


def test_b6_annihilation_flags_historical_stott():
    row = score_sermon(
        "I have come to wonder whether the wicked are annihilated. "
        "Conditional immortality, not eternal conscious torment, may be right.",
        attribution="historical_stott",
        title="Final state",
        slug="demo-stott",
    )
    assert row["axes"]["B6"]["band"] == "annihilation_or_conditional"
    assert row["axes"]["B6"].get("notes")

    silent = score_sermon("We sang a hymn and went home.", title="Benediction")
    assert silent["axes"]["B6"]["band"] == "no_hit"


def test_b7_classical_vs_flat_vs_citation_only():
    classical = score_sermon(
        "Romans 13 says submit to the governing authorities. "
        "Yet Acts 5:29, we must obey God rather than men. There are limits of obedience.",
        title="State",
    )
    assert classical["axes"]["B7"]["band"] == "classical_tension"

    flat = score_sermon(
        "Romans 13 is plain. Christians must simply obey the government. "
        "Always submit to the authorities. There is no right to resist the state.",
        title="Obey",
    )
    assert flat["axes"]["B7"]["band"] == "flat_compliance_only"

    cite_only = score_sermon(
        "Someone mentioned Romans 13 in the notices. We will not stay there.",
        title="Notices",
    )
    assert cite_only["axes"]["B7"]["band"] == "no_hit"


def test_score_is_zero_cost_and_not_coach():
    row = score_sermon("Hello.", title="Hi", slug="hi")
    assert row["cost_usd"] == 0.0
    assert row["not_coach_product"] is True
    assert COST_USD == 0.0


def test_harvest_and_cli_on_stott_subset(tmp_path):
    if not (STOTT / "j33UOzcFk_HCYQpF.json").exists():
        return
    # Two known files: one historical hash, one All Souls scrape.
    dest = tmp_path / "subset"
    dest.mkdir()
    for name in ("j33UOzcFk_HCYQpF.json", "the-son-john-1118.json"):
        src = STOTT / name
        if src.exists():
            (dest / name).write_bytes(src.read_bytes())
    bundle = harvest_folder(dest, preacher="John Stott")
    labels = {row["attribution"] for row in bundle["attributions"].values()}
    assert "historical_stott" in labels
    assert "all_souls_contemporary" in labels
    written = write_bundle(bundle, tmp_path / "out")
    assert written["attribution"].exists()
    assert written["hits"].exists()
    rollup = written["rollup"].read_text()
    assert "$0" in rollup or "0.00" in rollup
    assert "Do not merge" in rollup
    hits = written["hits"].read_text().strip().splitlines()
    assert hits

    proc = subprocess.run(
        [
            sys.executable, str(CLI), "fidelity", str(dest),
            "--output", str(tmp_path / "cli"),
            "--preacher", "John Stott",
        ],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert "$0.00" in proc.stdout
    assert "no Anthropic" in proc.stdout or "no anthropic" in proc.stdout.lower()


def test_cli_source_does_not_import_paid_stack():
    src = (REPO / "t1_ingest.py").read_text()
    assert "import pipeline" not in src
    assert "import anthropic" not in src
    fid = (REPO / "t1" / "fidelity.py").read_text()
    assert "import anthropic" not in fid
    assert "import voyage" not in fid
    assert "Does not call Anthropic" in fid
