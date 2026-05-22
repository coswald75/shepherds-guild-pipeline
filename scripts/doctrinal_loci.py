"""
The 16 canonical doctrinal loci used across the sermon decomposition pipeline,
each with an editorial blurb for the browse-by-doctrine surface.

Blurbs are 2-3 sentences in pastoral-not-academic prose. They define the
doctrine in concrete sub-topics and then say something about why it matters
for Christian life. Generic (no specific preacher named) so they read well
for any church. Edit before merge — these are LLM drafts, not the curator's
final voice.
"""

from __future__ import annotations

# Order: same canonical order used in the pipeline's VALID_LOCI, grouped
# loosely from "who God is" → "what God has done" → "what God is doing" →
# "what God will do" → practical theology.
LOCI: list[tuple[str, str]] = [
    (
        "Theology Proper",
        "Sermons on who God is — his being, attributes, character, and triune life. "
        "Holiness, righteousness, love, faithfulness, sovereignty, mercy: the things "
        "about God that make the rest of theology possible to think clearly about.",
    ),
    (
        "Christology",
        "Sermons centered on the person and work of Jesus Christ — his eternal "
        "divinity, incarnation, atoning death, bodily resurrection, ascension, and "
        "present reign. This is the doctrinal center of gravity for almost "
        "everything else; every other locus eventually circles back to who Jesus is "
        "and what he has done.",
    ),
    (
        "Pneumatology",
        "Sermons on the person and work of the Holy Spirit — his deity, his role in "
        "salvation and sanctification, his gifts to the church, and his fruit in the "
        "believer. The doctrine without which the Christian life would be conviction "
        "without power.",
    ),
    (
        "Bibliology",
        "Sermons on the Bible itself — its inspiration, inerrancy, sufficiency, "
        "clarity, and authority. Why this old book is the church's living rule of "
        "faith and life, and how to read it well as God's own speech to his people.",
    ),
    (
        "Anthropology",
        "Sermons on what it means to be human — created in God's image, embodied, "
        "gendered, fallen, redeemable. Covers identity, vocation, family, suffering, "
        "and death: who we are before God before any other identity gets named.",
    ),
    (
        "Hamartiology",
        "Sermons on the nature, depth, and reach of human sin — original sin, "
        "indwelling sin, sins of commission and omission, and the death that sin "
        "brings. Not a popular doctrine to teach plainly, but without it the gospel "
        "becomes news of little importance.",
    ),
    (
        "Soteriology",
        "Sermons engaging the gospel itself — what God has done in Christ to rescue "
        "sinners, how that salvation is applied, and how a person enters into it. "
        "Covers election, calling, justification, adoption, and assurance: the "
        "architecture of grace as received.",
    ),
    (
        "Sanctification",
        "Sermons on the Spirit's work to conform believers to the image of Christ — "
        "putting sin to death, growing in grace, persevering through trial, and "
        "bearing fruit. Often the most personally addressed locus: where doctrine "
        "has to touch how this Tuesday morning goes.",
    ),
    (
        "Ecclesiology",
        "Sermons on the church — what it is, who belongs to it, how it gathers and "
        "governs, and what it is for in the world. Covers the marks of a true "
        "church, ordinances, membership, leadership, mission, and the meaning of "
        "belonging to a particular local body.",
    ),
    (
        "Covenant Theology",
        "Sermons that read Scripture through the covenants — the unfolding promise "
        "that runs from Eden through Abraham, Sinai, and David to its fulfillment in "
        "Christ and inheritance by his church. The frame that holds the whole story "
        "together.",
    ),
    (
        "Providence / Sovereignty",
        "Sermons on God's active rule over every event of history — orchestrating "
        "salvation, ordaining suffering, governing nations, hearing prayers, and "
        "never letting the smallest sparrow fall outside his decree. The doctrine "
        "that makes Christian hope possible when the news is bad.",
    ),
    (
        "Eschatology",
        "Sermons engaging the doctrine of last things — Christ's return, the "
        "resurrection, the new creation, judgment, and the kingdom that does not "
        "end. Preaching here ranges from the throne room of Revelation 5 to the "
        "practical Christian hope that fuels endurance under suffering.",
    ),
    (
        "Doxology / Worship",
        "Sermons on what it means to worship God — the why and the how of corporate "
        "and personal praise, the place of prayer, singing, the Lord's Supper, and "
        "the daily affections of a heart aimed at God. Where right doctrine becomes "
        "right worship.",
    ),
    (
        "Ethics / Moral Theology",
        "Sermons applying Scripture to how Christians live — work and money, sex "
        "and marriage, speech and conduct, the use of the body, the use of the day. "
        "Where doctrine pays out in choices Christians make on Monday.",
    ),
    (
        "Pastoral Theology",
        "Sermons that address the practical work of shepherding — pastoring "
        "families, walking through suffering, counseling the doubting, confronting "
        "sin in love, and forming the next generation in the faith. The doctrine "
        "here is doctrine you can lay a hand on a shoulder with.",
    ),
    (
        "Spiritual Warfare",
        "Sermons on the conflict every Christian is in — against sin and indwelling "
        "temptation, against the world's pressures, and against unseen spiritual "
        "opposition. Sober rather than sensational: the realism behind every "
        "imperative in the New Testament.",
    ),
]

LOCUS_NAMES = [name for name, _ in LOCI]
LOCUS_SET = set(LOCUS_NAMES)
LOCUS_BLURB = {name: blurb for name, blurb in LOCI}
LOCUS_ORDER = {name: i for i, name in enumerate(LOCUS_NAMES)}


def locus_slug(name: str) -> str:
    """'Christology' → 'christology', 'Ethics / Moral Theology' → 'ethics-moral-theology'."""
    return (
        name.lower()
        .replace(" / ", "-")
        .replace("/", "-")
        .replace(" ", "-")
    )
