"""Scripture detection for the weekly "Gimme da quotes!" picker.

A candidate "external" quote is treated as Scripture (and dropped) when any of these hold:
  1. the attribution names a Bible book or a biblical speaker/writer (Jesus, Paul, Peter, David, ...);
  2. its wording matches Bible text: >=30% of its word 4-grams appear in a public-domain Bible
     (BSB, KJV, ASV; data/bible_pd.tsv.gz), or >=70% of its content words (at least 3 of 4, for lines
     with only 3-4 content words) fall in one verse or two adjacent verses (catches modern translations such as the ESV that differ in word order);
  3. it carries a scripture citation ("Galatians 6:1", "1 Pet 5") AND has moderate Bible overlap,
     so commentary that merely mentions a passage ("from this point in Ezra 4 onwards") is kept.
Hymn, creed and author quotes are kept: they don't match verse text and aren't attributed to a Bible figure.
"""
import gzip, re
from functools import lru_cache
from pathlib import Path

DATA = Path(__file__).with_name("data") / "bible_pd.tsv.gz"
BOOKS = ("Genesis Exodus Leviticus Numbers Deuteronomy Joshua Judges Ruth Samuel Kings Chronicles Ezra Nehemiah Esther Job "
         "Psalm Psalms Proverbs Ecclesiastes Song Isaiah Jeremiah Lamentations Ezekiel Daniel Hosea Joel Amos Obadiah Jonah "
         "Micah Nahum Habakkuk Zephaniah Haggai Zechariah Malachi Matthew Mark Luke John Acts Romans Corinthians Galatians "
         "Ephesians Philippians Colossians Thessalonians Timothy Titus Philemon Hebrews James Peter Jude Revelation").split()
ABBR = "Gen Ex Exod Lev Num Deut Josh Judg Sam Kgs Chr Neh Esth Ps Prov Eccl Isa Jer Lam Ezek Dan Hos Obad Mic Nah Hab Zeph Hag Zech Mal Matt Mt Mk Lk Jn Rom Cor Gal Eph Phil Col Thess Tim Tit Phlm Heb Jas Pet Rev".split()
REF = re.compile(r"\b(?:[123]\s*)?(?:%s)\.?\s+\d{1,3}(?:\s*[:.]\s*\d{1,3}|\s*,?\s*verses?\s+\d{1,3})?" % "|".join(BOOKS + ABBR), re.I)
BIBLE_PEOPLE = {"jesus", "christ", "paul", "peter", "john the baptist", "moses", "david", "solomon", "isaiah", "jeremiah",
                "the lord", "god", "james", "jude", "matthew", "mark", "luke", "the apostle", "apostle paul", "the psalmist"}
STOP = set("the and that for you your with this have will not but are was were his her him they them their from what when "
           "who whom which all any our out his has had also into upon unto shall then than there these those its it's "
           "one day like youll ill just now know see come make say said can get got very".split())


def _toks(s):
    return re.findall(r"[a-z]+", (s or "").lower().replace("\u2019", "'").replace("'", ""))


@lru_cache(maxsize=1)
def _index():
    grams, verses, by_word = set(), [], {}
    with gzip.open(DATA, "rt", encoding="utf-8") as f:
        for line in f:
            _, ref, text = line.rstrip("\n").split("\t", 2)
            t = _toks(text)
            grams.update(" ".join(t[i:i + 4]) for i in range(len(t) - 3))
            vi = len(verses); verses.append((ref, {w for w in t if len(w) > 2 and w not in STOP}))
            for w in verses[vi][1]: by_word.setdefault(w, []).append(vi)
    return grams, verses, by_word


def gram_overlap(text):
    grams = _index()[0]; t = _toks(text); g = [" ".join(t[i:i + 4]) for i in range(len(t) - 3)]
    return sum(x in grams for x in g) / len(g) if g else 0.0


def verse_word_overlap(text):
    _, verses, by_word = _index()
    cw = {w for w in _toks(text) if len(w) > 2 and w not in STOP}
    if len(cw) < 3: return 0.0, None
    rare = sorted(cw, key=lambda w: len(by_word.get(w, ())))[:3]
    cands = {i for w in rare for i in by_word.get(w, ())[:4000]}
    best, ref = 0.0, None
    for i in cands:
        words = verses[i][1] | (verses[i + 1][1] if i + 1 < len(verses) else set())
        s = len(cw & words) / len(cw)
        if s > best: best, ref = s, verses[i][0]
    return best, ref


def biblical_attribution(*names):
    for n in names:
        n = (n or "").strip().lower()
        if not n: continue
        if n in BIBLE_PEOPLE or n.startswith("the apostle") or any(n == b.lower() or re.match(re.escape(b.lower()) + r"\s+\d", n) for b in BOOKS):
            return True
    return False


def is_scripture(text, author=None, work=None):
    """Return a reason string if the quote is Scripture, else None."""
    if biblical_attribution(author, work): return f"attributed to {author or work}"
    g = gram_overlap(text)
    if g >= 0.30: return f"Bible wording ({g:.0%} of 4-grams)"
    v, ref = verse_word_overlap(text)
    v_cw = len({w for w in _toks(text) if len(w) > 2 and w not in STOP})
    if v >= (0.70 if v_cw >= 5 else 0.75): return f"matches {ref} ({v:.0%} of content words)"
    if REF.search(text) and (g >= 0.15 or v >= 0.5): return "scripture citation + Bible wording"
    return None
