"""Sermon title rule (Chris, 2026-10-06): never put scripture in a sermon title. Show the plain title, with the
scripture reference on its own line underneath (pages, dashboards, How We Said It / Gimme da quotes, PDFs).
clean_title() strips a reference the church baked into the title; slugs/URLs are never derived from it."""
import re

_BOOKS = ("Genesis|Exodus|Leviticus|Numbers|Deuteronomy|Joshua|Judges|Ruth|Samuel|Kings|Chronicles|Ezra|Nehemiah|Esther|Job|"
          "Psalms?|Proverbs|Ecclesiastes|Song of Songs|Song of Solomon|Isaiah|Jeremiah|Lamentations|Ezekiel|Daniel|Hosea|Joel|Amos|"
          "Obadiah|Jonah|Micah|Nahum|Habakkuk|Zephaniah|Haggai|Zechariah|Malachi|Matthew|Mark|Luke|John|Acts|Romans|Corinthians|"
          "Galatians|Ephesians|Philippians|Colossians|Thessalonians|Timothy|Titus|Philemon|Hebrews|James|Peter|Jude|Revelation")
# Book + chapter (+ optional :verse, ranges, ff). Requires a chapter number, so "1 John Introduction" is left alone.
REF = rf"(?:[1-3]\s?)?(?:{_BOOKS})\.?\s+\d+(?::\d+[a-c]?)?(?:\s*[-–—]\s*\d+(?::\d+[a-c]?)?)?(?:\s*ff\.?)?(?:\s*[,;]\s*\d+(?::\d+)?(?:\s*[-–]\s*\d+)?)*"
_SEP = r"\s*(?:\||[-–—:]|,)\s*"
_PATTERNS = [
    re.compile(rf"^(?P<t>.+?)\s*\(\s*(?P<r>{REF})\s*\)\s*$", re.I),        # Title (Acts 15:1-35)
    re.compile(rf"^(?P<t>.+?){_SEP}(?P<r>{REF})\s*$", re.I),               # Title | Ezra 3 / Title - Romans 1:1
    re.compile(rf"^(?P<r>{REF}){_SEP}(?!\d)(?P<t>.+)$", re.I),             # Acts 9:1-19 | Title / Acts 9: Title
    re.compile(rf"^(?P<r>{REF})\s+(?P<t>[A-Z].*)$"),                        # Acts 9:1-19 An Unlikely Convert
]


def split_title(title: str):
    """-> (plain_title, ref_or_None). A title that is ONLY a reference is returned unchanged (nothing to show instead)."""
    t = (title or "").strip()
    for p in _PATTERNS:
        m = p.match(t)
        if m and m.group("t").strip(" |-–—:,"):
            return m.group("t").strip(" |-–—:,"), m.group("r").strip()
    return t, None


def clean_title(title: str) -> str:
    return split_title(title)[0]


if __name__ == "__main__":
    for s in ["The Theological Center (Acts 15:1-35)", "Acts 9:1-19 An Unlikely Convert", "Where to Begin When Your Life Is in Ruins | Ezra 3",
              "Introduction | Romans 1:1", "What is Saul to Us?", "Our Faithful God", "All The Fullness", "Center Church Turns 1",
              "What Makes the Gospel Any Different?", "1 John Introduction", "Romans 8", "Joy in the City", "Psalm 23 - The Lord Is My Shepherd",
              "Iconium, Lystra, Derbe, and the Long Way Home", "The Justice of God", "Hope (1 Peter 1:3-9)", "2 Corinthians 4:7-18: Jars of Clay",
              "Matthew 5 Sermon on the Mount", "Mark the Evangelist"]:
        print(f"{s!r:52} -> {split_title(s)}")
