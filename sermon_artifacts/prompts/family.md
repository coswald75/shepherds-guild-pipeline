# Artifact — Sunday-Evening Family Table Card

## What this artifact is

**One short conversation prompt** designed for a family dinner table on
Sunday evening — typically gathered around a meal in the hours after the
sermon was preached. Works for households with children of varied ages
(school-age and up) without dumbing down the theology.

## Constraints

- **One prompt only.** Not three, not a discussion guide — a single question
  or invitation that opens conversation.
- **Age-anchored:** the prompt itself should work for ~age 7 and up.
  Younger kids can listen and join with help; teens and adults engage at
  their own depth. Use concrete language, not abstract theological terms,
  but don't avoid theological weight — the goal is to give parents an
  on-ramp into rich conversation, not to water down the truth.
- **Anchor in one specific image or moment from the sermon** — a story,
  illustration, primary-text moment, or vivid metaphor. Concrete > abstract.
- **Brief framing for the parent.** Two sentences max, explaining how to
  set the prompt up and what the goal of the conversation is. This is for
  the parent reading the card to know what they're doing.
- **Suggested age band:** indicate the youngest age the prompt comfortably
  serves ("works for ages 6+", "works for ages 8+", etc.). Use your
  judgment — if the prompt requires more abstraction, the band shifts up.

## Output JSON schema

```json
{
  "title": "Short noun-phrase title — what the family card is about (under 60 chars)",
  "framing_for_parents": "Two sentences. How to set this up at the table and what to listen for.",
  "prompt": "The actual question / invitation to read aloud at the table.",
  "age_band": "Description like 'works for ages 6+' or 'works for ages 10+ — younger kids can listen'"
}
```

Output ONLY the JSON object. No markdown fences. No commentary.

## What to avoid

- Mini-lessons disguised as questions ("Did you know that Jesus…")
- Yes/no prompts
- Abstract spiritual-formation language for kids ("How is your soul…")
- The phrase "What does this verse mean to you?" — too generic
- Parent-coaching tone in the prompt itself; the parent-facing setup is
  separate from the prompt the family hears
