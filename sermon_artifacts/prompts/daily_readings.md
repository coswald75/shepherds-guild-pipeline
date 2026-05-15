# Artifact — Daily Reading Plan (Mon-Fri)

## What this artifact is

A **five-day Bible-reading plan** that gives the church a week of meditation
on the sermon's theological claims through the lens of the sermon's
cross-references. Each day pairs a **cross-reference passage** with a
**reflection grounded in one specific theological claim from the sermon**.

The principle: the primary text was preached on Sunday. The week's readings
do not re-walk the primary text — they widen out into the *cross-references
the pastor brought in* and use them to deepen the congregation's grasp of
the *theological claims* the sermon established.

## Constraints

- **Five days exactly:** Monday, Tuesday, Wednesday, Thursday, Friday.
- **Scripture passages must come from the sermon's CROSS-REFERENCES list.**
  Do not invent new passages. If you genuinely need fewer than 5 distinct
  cross-references and one day requires falling back to a primary-text
  passage, that's acceptable — but the default is cross-references.
- **Each day's reflection must anchor to ONE specific theological claim
  from the sermon.** Reference the claim's logic (not the verbatim text)
  in 2-3 sentences that show *how this cross-reference deepens or
  illustrates that claim*. The connection between passage and claim is
  the whole point of the daily reading.
- **Span the theological claims across the week.** If the sermon
  established four claims, ideally each gets a day's reflection (with one
  claim repeating or two days illuminating one claim from different
  cross-references). Don't fixate on a single claim.
- **Build an arc across the week.** Mon = the most foundational
  theological claim. Tue–Thu = progressive deepening, each from a
  different cross-reference + different claim. Fri = the claim that
  drives application (often the most "so what" of the sermon).
- **Reflection length:** 2-3 sentences per day. A meditation, not a homily.
- **Use "we / us / our"** where natural — corporate, not individualistic.

## Output JSON schema

```json
{
  "intro": "One sentence framing the week's arc — the spine of theological
            claims it walks the reader through. Set to null if not needed.",
  "days": [
    {
      "day": "Monday",
      "passage": "Cross-reference exactly as cited in the sermon",
      "claim_anchor": "Quote or paraphrase the theological claim this
                       reading deepens (≤ 25 words). Lets a reviewer audit
                       the choice.",
      "reflection": "2-3 sentences. Show how the passage deepens the claim
                     anchored above. Theological precision + pastoral warmth."
    },
    ... × 5 in Mon-Tue-Wed-Thu-Fri order
  ]
}
```

Output ONLY the JSON object. No markdown fences. No commentary.

## What to avoid

- Inventing scripture references not present in the sermon
- Using the primary text as your default — the *cross-references* are the
  vehicle this week
- Pairing a passage with a claim it doesn't naturally serve (forced fits)
- Reflections that summarize the sermon rather than meditate on the
  cross-reference passage in light of a specific claim
- Repeating the same claim every day without rotation across the sermon's
  full theological frame
- Sentimentality — keep doctrinal weight even in two sentences
- Devotional clichés ("Reflect on God's love")
