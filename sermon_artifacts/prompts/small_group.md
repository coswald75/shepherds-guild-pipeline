# Artifact — Small Group Discussion Questions

## What this artifact is

A leader-facing set of **six discussion questions** for a small group meeting
that gathers this week to process the sermon. The leader will read these
aloud or distribute them. The questions are designed to (a) move the group
through the sermon's argument, (b) press into application without
moralizing, and (c) anchor every prompt in Scripture.

## Constraints

- **Six questions.** Not five, not seven. The group is structured around
  this count.
- **Move from observation → interpretation → application.** Questions 1-2
  surface what the text actually says; 3-4 wrestle with what it means; 5-6
  press into how it reshapes our lives this week.
- **At least one question must reference a specific cross-reference** from
  the sermon (use the cross-references list).
- **At least one question must surface a "fallen condition focus"** — the
  specific way this passage names our need or weakness.
- **At least one question must explicitly invoke the gospel** — what
  Christ has accomplished that addresses the need surfaced above.
- **Follow-ups are optional**: when included, a follow-up should redirect
  a tendency toward abstraction back into concrete experience, or vice
  versa.
- **No yes/no questions.** Open-ended only.
- **Tone:** the leader is shepherding believers, not lecturing students.
  Questions should presume the group can think theologically together.

## Output JSON schema

```json
{
  "questions": [
    {
      "question": "Primary discussion prompt",
      "follow_up": "Optional second-order prompt — null if not needed",
      "scripture_anchor": "Optional scripture reference if the question
                          ties to a specific text — null otherwise"
    },
    ... × 6
  ]
}
```

Output ONLY the JSON object. No markdown fences. No commentary.

## What to avoid

- Questions that can be answered with "yes" or "no"
- Questions that are really mini-sermons in disguise ("Given that we know
  X, Y, and Z, how should we…")
- Vague application prompts ("How can we apply this?")
- Moralism — framing obedience as effort rather than grace-empowered
  response
- Repetition of the same theme across multiple questions; each should
  open a distinct facet of the sermon
- Christianese filler ("How is the Lord stirring your heart…")
