from regional.mwnw.scripture import is_scripture

SCRIPTURE = [  # dropped by hand from the 10-4-26 / 10-11-26 quotes pages
    ("if anyone is caught in any transgression, you who are spiritual should restore him in a spirit of gentleness", None),
    ("I no longer call you servants, but I call you friends.", None),
    ("beloved, do not be surprised at the fiery trial when it comes upon you to test you, as if something strange were happening to you.", None),
    ("out of the overflow of the heart the mouth speaks", "Jesus"),
    ("as to righteousness under the law, blameless", None),
    ("Broad is the way that leads to destruction, but narrow is the path that leads to life", None),
]
KEEP = [
    ("there is a fountain filled with blood", None),
    ("my memory is nearly gone. But two things I do remember that I am a great sinner and that Christ is a great savior", "John Newton"),
    ("the gravity and gladness of God", "John Piper"),
    ("one day you'll be like me", None),
    ("from this point in Ezra 4 onwards, right to the end of Nehemiah, there is conflict. Nothing that is attempted for God will now go unchallenged.", "Derek Kidner"),
    ("Paul's letter to the Romans is a kind of Christian manifesto", "John Stott"),
]


def test_scripture_dropped():
    for text, author in SCRIPTURE:
        assert is_scripture(text, author), text


def test_author_and_hymn_quotes_kept():
    for text, author in KEEP:
        assert not is_scripture(text, author), text
