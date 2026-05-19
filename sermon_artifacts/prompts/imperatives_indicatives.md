# Artifact — Imperatives and Indicatives

## What this artifact is

A structural reading of the sermon that surfaces its **indicatives**
(what God has done, who Christ is, what is true of the believer in
Christ) and its **imperatives** (what Scripture commands, what response
the sermon calls for). Where possible, each imperative is paired with
the indicative(s) that ground it.

The structural conviction — drawn from Paul's letters and codified
in modern homiletics by Bryan Chapell and others — is that the
**imperative always flows from the indicative**. Obedience is a
response to the gospel, not a payment for it. *"Every imperative of
Scripture rests on the indicative, and the order is not reversible."*

- A sermon that issues imperatives without sufficient gospel ground
  drifts toward **legalism** — duty without grace, obedience as
  performance.
- A sermon that recites indicatives without calling for response
  drifts toward **antinomianism** — grace as license, no concrete
  obedience asked.

The reader of this artifact is a small-group leader preparing to
shepherd discussion, a pastor reviewing his own preaching, or a
serious member who wants to internalize the sermon's gospel-and-
response shape. The artifact describes the shape the sermon actually
took. It is not a grade.

## Constraints

- **3–6 indicatives.** Statements of what is TRUE — God's character,
  Christ's accomplished work, the Spirit's ongoing work, the
  believer's standing, the church's reality. Each indicative must
  reflect a claim the sermon actually establishes, asserts, or
  appeals to. Do not pad with generic doctrine the sermon did not
  invoke.
- **3–6 imperatives.** Statements of what the sermon calls hearers
  TO BE or TO DO. Anchored in the sermon's application units and its
  direct exhortations. Verbs should be active.
- **Ground each imperative in one or more indicatives** via the
  `grounded_in` field. Reference back to the indicative by short
  paraphrase. If the sermon issued an imperative without supplying
  gospel ground, mark `grounded_in` as `null` and let the
  `balance_note` observe it.
- **`balance_note`**: 1–3 sentences. Where did the sermon weight its
  emphasis — indicative-heavy, imperative-heavy, or balanced? Was
  there sufficient gospel ground to motivate the obedience asked?
  Pastoral observation, not critique. Avoid words like "should
  have," "needed more," "lacked." Describe what's there.
- **Scripture anchors** are optional per item, encouraged when the
  sermon explicitly tied the indicative or imperative to a
  citation.
- **Tone:** descriptive and pastoral. The model is reading a sermon
  alongside a thoughtful colleague, not grading a student. Honor the
  sermon as it was preached.

## Output JSON schema

```json
{
  "intro": "1–2 sentences naming the sermon's central gospel-and-response move. What's the truth, and what's the response it calls for?",
  "indicatives": [
    {
      "statement": "What is true — declarative, gospel-rooted.",
      "scripture": "Optional anchor reference, e.g., 'Colossians 3:1'"
    }
    // 3–6 entries
  ],
  "imperatives": [
    {
      "statement": "What we are called to be or do. Active verbs.",
      "scripture": "Optional anchor reference",
      "grounded_in": "Short paraphrase of the indicative that motivates this imperative, or null if the sermon did not supply one."
    }
    // 3–6 entries
  ],
  "balance_note": "1–3 sentences observing the weight and order. Was the indicative carried with enough weight to support the imperatives? Was an imperative left without sufficient gospel ground? Pastoral observation, not grading."
}
```

Output ONLY the JSON object. No markdown fences. No commentary before
or after.

## What to avoid

- **Inventing imperatives.** If the sermon did not actually call
  hearers to something, do not manufacture an exhortation. Four
  honest imperatives are stronger than six with two fabrications.
- **Restating the gospel as imperative.** "Believe harder" or
  "trust more" is not a clean imperative — it is a request to
  manufacture indicative reality. List the indicative. List the
  imperatives that flow from it.
- **Generic doctrinal padding.** "God is sovereign" by itself is not
  an indicative for this artifact — it is a sentence. An indicative
  is something the sermon actually established or appealed to as
  ground for obedience: "Because God reigns over your suffering this
  week, you can…"
- **Vague application.** "Be more faithful" is not an imperative
  for this artifact. Active verbs. Concrete spheres of action where
  the sermon supplied them.
- **Reversing the theological order.** If the sermon presented the
  imperative first and then grounded it in the indicative, that is
  permissible — Chapell explicitly allows the rhetorical order to
  vary. What is *not* permissible is letting an imperative stand
  with no gospel ground at all. Note such cases honestly in
  `grounded_in: null` and the `balance_note`.
- **Judgment or grading.** The artifact observes; it does not
  score.
