# Artifact — Weekly Prayer Prompt

## What this artifact is

A short corporate prayer (8–14 sentences) drawn directly from the sermon's
theological frame. Members will use it in private devotions or pray it
together in small groups during the week. It is **not** a closing benediction
or pulpit prayer — it is a *response prayer* the congregation prays as a body
under the sermon's preaching.

## Constraints

- **Address**: pray *to* God the Father, through the Son, in the Spirit. The
  prayer is a corporate utterance — use "we," "our," "us" throughout.
- **Center on the sermon**: anchor the prayer in the sermon's `main_thesis`
  and at least one of its theological claims. Quote or paraphrase a
  specific phrase from the sermon when it serves the prayer's movement.
- **Gospel-shaped arc**: confess our need → adore God's character →
  appropriate the gospel → ask for grace to live in light of the truth
  preached → close with doxology or commitment.
- **Scripture references in parens** where the prayer draws on or alludes
  to a passage from the sermon's primary text or cross-references.
- **No bullet points, no headings inside the prayer text.** Continuous
  prose, broken into 2–4 short paragraphs.
- **No exhortation to the reader.** This is a prayer *to God*, not a sermon
  about prayer.

## Output JSON schema

```json
{
  "title": "Short noun-phrase title for the prayer — under 60 chars",
  "prayer_text": "Continuous prose of the prayer. Use \\n\\n between paragraphs."
}
```

Output ONLY a single JSON object conforming to the schema above. No markdown
fences. No commentary.

## Movement / structure to aim for

1. **Opening adoration** (1–2 sentences) — name something about God's
   character that the sermon emphasized.
2. **Confession** (2–3 sentences) — name the specific dimension of our
   weakness the sermon surfaced. Acknowledge it with pastoral tenderness,
   not flagellation.
3. **Gospel appropriation** (2–3 sentences) — re-state what Christ has
   accomplished that addresses the confession.
4. **Petition** (3–4 sentences) — ask God for the grace to live in light
   of the truth preached. Tie petitions to specific applications surfaced
   in the sermon.
5. **Closing commitment or doxology** (1–2 sentences) — corporate
   commitment, or a brief ascription of glory.

## What to avoid

- Generic prayer language unmoored from the sermon ("Lord, help us today…")
- Long sentences that lose the corporate "we" thread
- Theologically thin appeals — every petition should connect to what the
  gospel makes possible
- Quoting more than a sentence verbatim from the sermon transcript
- The phrase "Just" before verbs ("we just pray…") — avoid Christianese
  filler. Use direct petition.
