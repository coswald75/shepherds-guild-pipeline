"""Unit tests for the self-serve engine's pure helpers (no network)."""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

ssi = pytest.importorskip("selfserve_ingest")


def test_form_metadata_wins_and_no_invented_series():
    decomp = {"title": "Model Title", "date": "2026-09-30",
              "series_name": "Key Government Issues in Israel", "series_position": "Part 1 of 4"}
    ssi.apply_form_metadata(decomp, "Productive Problem Solving", "2026-09-27", None)
    assert decomp["title"] == "Productive Problem Solving"
    assert decomp["date"] == "2026-09-27"
    assert decomp["series_name"] is None
    assert decomp["series_position"] is None


def test_pastor_series_is_kept():
    decomp = {"series_name": "Model guess"}
    ssi.apply_form_metadata(decomp, None, None, "1 Samuel")
    assert decomp["series_name"] == "1 Samuel"


def test_email_says_sermon_steward_and_no_prayer():
    subject, html = ssi.email_template("Chris Oswald", "Productive Problem Solving")
    assert subject == "Your Sermon Steward report — Productive Problem Solving"
    assert "Shepherd" not in html
    assert "pray" not in html.lower()
    assert "Thank you for trying Sermon Steward" in html
    assert "Sermon Steward &middot; sermonsteward.com" in html
    assert "free as part of" not in html


def test_email_cohort_line():
    _, html = ssi.email_template("Pat", "T", ssi.cohort_label("sg-mountain-west"))
    assert "free as part of the Sovereign Grace Midwest offer" in html


def test_norm_name():
    assert ssi.norm_name("Grace Church, Denver") == ssi.norm_name("grace church denver")
    assert ssi.norm_name(None) == ""


class FakeQuery:
    def __init__(self, rows, log):
        self.rows, self.log, self.filters = rows, log, {}
    def select(self, *_):
        return self
    def eq(self, k, v):
        self.filters[k] = v
        return self
    def insert(self, row):
        self.log.append(row)
        self.inserted = dict(row, id=f"new-{len(self.log)}")
        return self
    def execute(self):
        class R: pass
        r = R()
        if hasattr(self, "inserted"):
            r.data = [self.inserted]
        else:
            r.data = [x for x in self.rows if all(x.get(k) == v for k, v in self.filters.items())]
        return r


class FakeSB:
    def __init__(self, churches, preachers):
        self.data = {"churches": churches, "preachers": preachers}
        self.inserts = {"churches": [], "preachers": []}
    def table(self, name):
        return FakeQuery(self.data[name], self.inserts[name])


CHURCHES = [
    {"id": "c-live", "name": "Grace Church Denver", "brand": "sermon_steward", "auto_publish": True, "is_public": True},
    {"id": "c-prospect", "name": "Hope Church", "brand": "sermon_steward", "auto_publish": False, "is_public": False},
]
PREACHERS = [{"id": "p-1", "name": "Pat Smith", "church_id": "c-prospect"}]


def test_cohort_reuses_existing_prospect_church_and_preacher():
    sb = FakeSB(CHURCHES, PREACHERS)
    assert ssi.ensure_prospect(sb, "pat  smith", "HOPE church", match_existing=True) == ("c-prospect", "p-1")
    assert sb.inserts == {"churches": [], "preachers": []}


def test_cohort_adds_preacher_to_matched_church():
    sb = FakeSB(CHURCHES, PREACHERS)
    church_id, preacher_id = ssi.ensure_prospect(sb, "Lee Jones", "Hope Church", match_existing=True)
    assert church_id == "c-prospect"
    assert sb.inserts["churches"] == []
    assert sb.inserts["preachers"][0]["church_id"] == "c-prospect"
    assert sb.inserts["preachers"][0]["is_public"] is False


def test_live_customer_church_is_never_matched():
    sb = FakeSB(CHURCHES, PREACHERS)
    church_id, _ = ssi.ensure_prospect(sb, "Pat", "Grace Church Denver", match_existing=True)
    assert church_id != "c-live"
    assert sb.inserts["churches"][0]["auto_publish"] is False


def test_public_uploads_always_create_fresh_records():
    sb = FakeSB(CHURCHES, PREACHERS)
    church_id, _ = ssi.ensure_prospect(sb, "Pat Smith", "Hope Church")
    assert church_id != "c-prospect"
    assert len(sb.inserts["churches"]) == 1
