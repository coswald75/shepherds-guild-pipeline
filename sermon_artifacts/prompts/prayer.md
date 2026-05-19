# Artifact — Weekly Prayer Prompt

## What this artifact is

A short corporate prayer (8–14 sentences) drawn directly from the sermon's
theological frame. Members will use it in private devotions or pray it
together in small groups during the week. It is **not** a closing benediction
or pulpit prayer — it is a *response prayer* the congregation prays as a body
under the sermon's preaching.

## The structural conviction

This prayer mirrors the homiletical pattern Paul follows in his epistles
and that Bryan Chapell calls the imperative-indicative balance: every
petition we make to God is **rooted in something true about God or
something Christ has accomplished**. We do not earn grace by asking; we
appeal to grace already given. So the prayer's shape is fixed:

- **First half — indicative.** Address the Father with what is true:
  who He is (*Father, you are…*), what He has done (*Father, we thank
  you that…*). The gospel ground is stated openly before any petition.
- **Hinge** (explicit). One short transitional clause — *Therefore*, *And
  so*, *In light of this*, *Because of this* — that marks the move from
  indicative ground to imperative request. The hinge must be visible.
- **Second half — petition rooted in the imperatives the sermon
  preached.** The asks of the prayer ("help us to…", "grant us…", "give
  us grace to…") correspond to the sermon's actual imperatives. We do
  not invent obedience requests the sermon did not call for.
- **Closing.** Through Christ our Lord / in His name / Amen.

## Constraints

- **Corporate voice.** "We," "our," "us" throughout. Never "I."
- **Address the Father, through the Son, in the Spirit.** Standard
  Trinitarian framing.
- **Anchor in this sermon's content.** Draw indicatives from the
  sermon's `main_thesis` and theological claims. Draw petitions from
  the sermon's application claims. The prayer should be unmistakably
  THIS sermon's response, not a generic prayer the congregation could
  offer any week.
- **Scripture references in parens** when the prayer draws on a
  passage from the sermon's primary text or cross-references.
- **Continuous prose**, broken into 2–4 short paragraphs. No bullets,
  no headings inside the prayer text.
- **The hinge is visible.** A reader should be able to point at one
  word or short phrase and say "that's where the indicative becomes
  imperative."
- **8–14 sentences total.** Roughly half indicative, half petition.

## Output JSON schema

```json
{
  "title": "Short noun-phrase title for the prayer — under 60 chars",
  "prayer_text": "Continuous prose of the prayer. Use \\n\\n between paragraphs."
}
```

Output ONLY a single JSON object conforming to the schema above. No markdown
fences. No commentary.

## Structural movement to aim for

1. **Address + adoration** (1–2 sentences) — *Father, you are…* /
   *Father of mercies…* — naming who God is in the dimension the sermon
   emphasized.
2. **Thanksgiving / gospel appropriation** (2–4 sentences) — *We thank
   you that…* / *We praise you that in Christ…* — re-stating the
   sermon's gospel announcement as adoration. The Christ-event in
   particular: cross, empty tomb, ongoing reign, indwelling Spirit.
3. **Hinge** (1 short clause) — *Therefore*, *And so*, *In light of
   this* — explicit transition from indicative ground to imperative
   request.
4. **Petition** (3–5 sentences) — *Help us to…*, *Grant us…*, *Give us
   grace to…*, *Make us a people who…* — tied to the sermon's actual
   application claims. Each petition should be answerable in the
   ordinary life of the congregation this week.
5. **Closing** (1–2 sentences) — corporate commitment, ascription of
   glory, or simply *through Christ our Lord. Amen.*

## What to avoid

- **Generic prayer language unmoored from the sermon.** "Lord, bless us
  today…" with no specific gospel content from the preaching. If a
  pastor reading this can't tell which sermon it was prayed under, the
  artifact failed.
- **Petitions without gospel ground.** Every *Help us…* must answer
  back to a *You are…* or *You have…* earlier in the prayer. If the
  hinge cannot be drawn, the petition floats and reads as moralism.
- **Confession that drifts into self-flagellation.** Acknowledgment of
  weakness is welcome but brief — the prayer's center is the gospel,
  not the confession. If confession is included, frame it as further
  indicative ("you have shown us…") that lands back on grace.
- **Christianese filler.** Avoid *Just* before verbs (*we just pray…*),
  *Lord, we ask that you would…* tautologies, *Father God* doublings.
  Direct petition language.
- **Quoting more than one sentence verbatim from the transcript.**
  Paraphrase. The prayer is a *response* to the sermon, not a
  transcription of it.
- **Exhortation to the reader.** This is a prayer to God, not a
  sermon about prayer. No "let us remember to…" or "may we always…"
  embedded in the body.
