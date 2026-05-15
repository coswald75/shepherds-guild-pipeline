# Artifact — Memory Verse

## What this artifact is

**One verse** drawn from the sermon's citations that the congregation
should commit to memory this week — accompanied by a brief explanation of
why this verse (rather than any other) is the right anchor for what was
preached.

## Constraints

- **The verse MUST come from the sermon's citation list** — primary text
  preferred, but a cross-reference is acceptable when the cross-reference
  more crisply captures the sermon's central claim than any single verse
  in the primary text. State your reasoning in `why_this_verse`.
- **Quote the verse fully.** Use the ESV unless the sermon's transcript
  cites a different translation explicitly. If you don't have the verse
  text from the sermon and aren't sure of the ESV phrasing, output the
  reference only and let the rendering layer fill in the text.
- **Length:** one verse (occasionally two consecutive verses if the unit
  of thought spans both — e.g., 1 Peter 1:8-9). Not a paragraph.
- **`why_this_verse` is 2-3 sentences.** It should answer: of all the
  verses cited in this sermon, *why is THIS the one to memorize?* The
  answer should reference the sermon's main thesis or a specific
  theological claim.

## Output JSON schema

```json
{
  "reference": "Book chapter:verse (e.g., '1 Peter 1:3') — must appear in the citation list",
  "full_text": "The verse text. ESV unless the sermon used a different translation.",
  "why_this_verse": "2-3 sentences explaining why this verse anchors the sermon's central claim."
}
```

Output ONLY the JSON object. No markdown fences. No commentary.

## What to avoid

- Choosing a verse not cited in the sermon
- Generic encouragement verses unrelated to the sermon's specific argument
- Long passages (more than 2 verses)
- `why_this_verse` that summarizes the sermon rather than justifying the
  verse selection
- Sentimentality — the reason this verse is worth memorizing should be
  theological, not emotional
