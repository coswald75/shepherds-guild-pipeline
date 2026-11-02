import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from church_page_index import add_sermon, add_sermons_to_church_page

PAGE = """x
<!-- accordion:sermon-index -->
      <div class="sermon-index-year">2026</div>
      <ul class="sermon-index">
        <li><span class="d">2026-10-25</span><a href="sermons/a-2026-10-25.html">Hand Edited</a></li>
        <li><span class="d">2026-10-18</span><a href="sermons/b-2026-10-18.html">B</a></li>
      </ul>
      <div class="sermon-index-year">2025</div>
      <ul class="sermon-index">
        <li><span class="d">2025-12-28</span><a href="sermons/c.html">C</a></li>
      </ul>
<!-- /accordion:sermon-index -->
y"""

def test_adds_newest_on_top_and_keeps_everything_else():
    out, ch = add_sermon(PAGE, date="2026-11-01", slug="god-sees-2026-11-01", title="God Sees")
    assert ch
    assert out.replace('        <li><span class="d">2026-11-01</span><a href="sermons/god-sees-2026-11-01.html">God Sees</a></li>\n', "") == PAGE
    assert out.index("god-sees") < out.index("a-2026-10-25")

def test_idempotent():
    out, _ = add_sermon(PAGE, date="2026-11-01", slug="g", title="G")
    out2, ch = add_sermon(out, date="2026-11-01", slug="g", title="G")
    assert not ch and out2 == out

def test_existing_link_untouched():
    out, ch = add_sermon(PAGE, date="2026-10-25", slug="a-2026-10-25", title="Other")
    assert not ch and out == PAGE

def test_middle_insert_and_new_year():
    out, _ = add_sermon(PAGE, date="2026-10-20", slug="m", title="M")
    assert out.index("a-2026-10-25") < out.index('"sermons/m.html"') < out.index("b-2026-10-18")
    out, _ = add_sermon(PAGE, date="2027-01-03", slug="n", title="N & Co")
    assert out.index('year">2027') < out.index('year">2026') and "N &amp; Co" in out

def test_no_markers_or_undated_noop():
    assert add_sermon("plain", date="2026-11-01", slug="g", title="G") == ("plain", False)
    assert add_sermon(PAGE, date="", slug="g", title="G") == (PAGE, False)

def test_file_level(tmp_path):
    d = tmp_path / "Church"; (d / "sermons").mkdir(parents=True)
    (d / "index.html").write_text(PAGE)
    (d / "sermons" / "g-2026-11-01.html").write_text('<meta property="og:title" content="God Sees — A sermon on Isaiah 1">')
    added = add_sermons_to_church_page(d, [{"slug": "g-2026-11-01", "date": "2026-11-01", "title": "x"},
                                          {"slug": "missing", "date": "2026-11-01", "title": "y"}])
    assert added == ["God Sees"]
    assert ">God Sees</a>" in (d / "index.html").read_text()
