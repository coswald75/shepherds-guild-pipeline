# Sermon Corpus Decomposition Spec v3

## Purpose

Transform a sermon manuscript into a structured JSON document containing functional units with rich theological metadata. The output serves as the canonical record for semantic search, cross-referencing, voice replication, homiletical benchmarking, stylistic archetype analysis, and derivative content generation.

---

## Sermon-Level Fields

**`title`** — As given or inferred from the manuscript.

**`preacher`** — Name.

**`date`** — If detectable.

**`primary_text`** — The main scripture passage for the sermon as a whole.

**`sermon_type`** — Enum: `expository`, `topical`, `textual`, `narrative`, `polemic`.

**`series_name`** — If detectable.

**`series_position`** — "Part 3 of 7" if detectable.

**`abstract`** — 4-6 sentences. The sermon's argument in compressed form. Not a teaser — a genuine summary capturing the logical arc from problem to resolution.

**`main_thesis`** — One sentence. The sermon's controlling claim — the single proposition the entire sermon exists to establish. Every unit should in some way serve this thesis.

**`target_audience_cues`** — Detectable signals about who the sermon addresses. "New believers," "parents," "leaders," "the whole congregation," "the discouraged."

**`tone`** — Enum array: `pastoral`, `prophetic`, `didactic`, `celebratory`, `lament`, `polemic`, `evangelistic`.

**`hermeneutical_method`** — Enum array:
- `grammatical_historical` — Close attention to original language, historical context, authorial intent.
- `redemptive_historical` — Passage read as a moment in the unfolding drama of redemption. Christotelic reading.
- `canonical` — Interpreting in light of the whole canon. Scripture interprets Scripture as active method.
- `applicatory` — Primary emphasis on "what does this mean for us" with less exegetical scaffolding.
- `polemic` — Passage marshaled to refute an error or defend a contested doctrine.

**`all_quotations`** — Rolled-up array of every human-author quotation in the sermon with `unit_index` reference.

**`all_cross_references`** — Rolled-up array of every scripture citation from outside the primary text with `unit_index` reference.

---

## Unit-Level Fields

Each sermon is decomposed into **functional units** — sections defined by rhetorical function shift, not character count.

### Core Fields

**`unit_index`** — Integer. Sequential position in the sermon, starting at 0.

**`rhetorical_function`** — Enum. Use only the values defined below. Do not invent new values. If no defined function fits, use the closest match and note the ambiguity in the `summary` field.

- `exposition` — Direct engagement with the biblical text. Exegesis, word studies, contextual background. The text is the subject; the pastor is the guide.
- `theological_claim` — A doctrinal assertion derived from or supported by the exposition. Distinguished from exposition by its propositional nature — it asserts, not just explains.
- `illustration` — Story, analogy, historical example, hypothetical scenario, or cultural reference serving the argument. Illustrations do not make claims — they make claims vivid, memorable, or emotionally accessible.
- `application` — Direct address about what to do, believe, or become in response to the truth established. Characterized by imperative verbs, second-person address, and concrete instruction.
- `introduction` — Opening frame. Sets up the text, the problem, the question, or the tension the sermon will address. May appear after the scripture reading and prayer if the pastor delays the sermon's framing.
- `conclusion` — Closing frame. Summarizes, reiterates, issues final charge, or lifts the congregation into worship.
- `transition` — Connective tissue between major sections. Signals structural shifts and helps the listener track the argument.
- `pastoral_aside` — Direct shepherding moment stepping outside the expositional flow to address the congregation personally. The voice shifts from teacher to shepherd. Marked by sudden intimacy and personal concern.
- `prayer` — Opening, closing, or mid-sermon prayer. The pastor addresses God rather than the congregation.

**`content`** — Verbatim text of the unit. No summarization, no truncation, no paraphrasing, no grammatical correction. The voice is the asset.

**`summary`** — 2-3 sentences. What this unit accomplishes in the sermon's argument — not what it says, but what it *does*. Capture function, not just content.

**`key_claim`** — One sentence. The single most important assertion this unit makes. Must stay within what the unit itself establishes — do not reach forward to claims made in later units. Null for transitions, prayers, and illustrations that serve other units' claims rather than making claims of their own.

---

### Three-Tier Citation Architecture

Three fundamentally different kinds of cited material require different retrieval paths. Correct tier classification is critical — do not allow cross-contamination between tiers.

#### Tier 1: `primary_text_citations`

**Verses from within the sermon's declared `primary_text` passage ONLY.** If `primary_text` is Luke 7:36-50, then only references falling within Luke 7:36-50 belong in Tier 1. A pastor who reads Luke 6:7 aloud while preaching on Luke 7:36-50 is making a Tier 2 cross-reference, not a Tier 1 citation — regardless of how the verse is delivered.

The determining question is: **does this reference fall within the `primary_text` range?** If yes, Tier 1. If no, Tier 2. Delivery mode (read aloud, quoted from memory, referenced in passing) does not change the tier — it only determines the `mode` value within the appropriate tier.

Array of objects:
- `reference` — Book, chapter, verse.
- `mode` — Enum: `full_reading`, `partial_reading`, `reference_in_passing`.

#### Tier 2: `cross_references`

**All scripture from outside the `primary_text` passage**, brought in for support, contrast, illumination, or typological connection. This includes verses read aloud, quoted at length, or mentioned in passing — if the reference falls outside the `primary_text` range, it is Tier 2.

Array of objects:
- `reference` — Book, chapter, verse.
- `function` — Enum: `authority`, `contrast`, `echo`, `fulfillment`, `parallel`, `corrective`.
- `supports_claim` — One sentence identifying which argument this cross-reference serves.

#### Tier 3: `quotations`

**Non-biblical human authors only.** Scripture is handled exclusively in Tiers 1 and 2 — never in Tier 3.

**CRITICAL BOUNDARY:** If the speaker is a biblical figure (Jesus, Paul, Peter, Moses, David, Solomon, Isaiah, Jeremiah, God, the Lord, the Holy Spirit, any prophet, any apostle, any psalm/psalmist) OR the source is a biblical book or passage reference (e.g., "Romans 8:28", "Psalm 23", "John 14:6", "the Sermon on the Mount"), it belongs in `cross_references` (Tier 2), NOT here. This applies even when the preacher quotes the biblical text from memory, paraphrases it, or introduces it as speech ("Jesus said...", "Paul writes..."). The test: **could this be given a Bible reference?** If yes → Tier 2 cross-reference. If no → Tier 3 quotation.

Tier 3 is reserved for: theologians (Calvin, Owen, Spurgeon, Edwards, Carson, Keller), authors (C.S. Lewis, Tolkien), hymn writers, poets, cultural figures, unnamed commentators, and other non-biblical human voices.

Array of objects:
- `text` — Verbatim quote as it appears in the manuscript.
- `attribution` — Who said it. Capture exactly what the manuscript gives.
- `source` — The work it's from if identifiable. Null if unspecified.
- `function` — Enum: `authority`, `illustration`, `provocation`, `devotional`, `opponent`.

---

### Illustration Metadata

**`illustration_type`** — Enum. Required on all units where `rhetorical_function` is `illustration`. Null on all other units.

- `personal_story` — The pastor's own lived experience. "When I was in seminary..." or "My father once told me..."
- `historical_example` — A real event, figure, or episode from history (including biblical history when used illustratively rather than expositionally). David and Bathsheba used to illustrate consequences of sin; the fall of Rome used to illustrate cultural decline.
- `analogy` — An A-is-like-B comparison. "Grace is like..." or "The church is like a body in that..." Abstract mapping from one domain to another.
- `hypothetical` — An imagined scenario. "Imagine you received a call from your bank..." or "Picture yourself in that room..." Did not happen; constructed for rhetorical effect.
- `cultural_reference` — Books, films, current events, public figures, cultural moments. "As Hugh Hefner said..." or "Like the scene in Les Misérables..."

Note: Some illustrations blend types (a historical example used as an analogy). Tag the primary mode — the type that best describes how the material functions in the argument.

---

### Application Metadata

**`application_specificity`** — Enum. Required on all units where `rhetorical_function` is `application`. Null on all other units.

- `abstract` — General exhortation without concrete instruction. "Trust God more." "Walk in holiness." "Love one another." The listener must supply the specific action.
- `concrete` — Specific, actionable instruction. "This week, write down three sins you need to confess." "Open your Bible to this passage every morning." "Call that person you've been avoiding." The listener knows exactly what to do.
- `mixed` — The unit contains both abstract exhortation and concrete instruction in meaningful proportion.

---

### Rhetorical Register

**`rhetorical_register`** — Enum array. The persuasive mode of the unit — how it seeks to move the listener. Multiple values allowed when the unit operates in more than one register simultaneously.

- `logos` — Logical argument. Reasoning, evidence, cause-and-effect, exegetical demonstration. The unit persuades by proving.
- `pathos` — Emotional appeal. The unit seeks to move the heart — through grief, joy, urgency, wonder, or fear. The emotional temperature is high and intentional.
- `ethos` — Credibility and authority. The unit establishes why the speaker (or a cited authority) should be trusted. Personal testimony, pastoral experience, scholarly citation used to build trust.
- `narrative` — Story immersion. The unit draws the listener into a narrative — biblical, historical, or personal — and persuades by making the listener experience the story rather than merely hear an argument about it.
- `doxological` — Worship and praise. The unit breaks into or toward worship. The rhetorical aim is not to inform or persuade but to adore. The pastor's exposition becomes doxology.

Required on all units. Even exposition units have a register — most exposition is `logos`, but a pastor who traces a narrative through Genesis is operating in `narrative` register even while doing expositional work.

---

### Theological Metadata

**`doctrinal_loci`** — Array. Controlled taxonomy. Use only these values:
- Theology Proper (doctrine of God)
- Christology
- Pneumatology (Holy Spirit)
- Soteriology (salvation)
- Hamartiology (sin)
- Anthropology (doctrine of humanity)
- Ecclesiology (church)
- Eschatology (last things)
- Bibliology (Scripture)
- Sanctification
- Providence / Sovereignty
- Covenant Theology
- Ethics / Moral Theology
- Doxology / Worship
- Spiritual Warfare
- Pastoral Theology

**`biblical_theological_moves`** — Array of objects. Detected instances of biblical theology — moments where the pastor traces connections across the canon.

**Actively look for these moves.** They are the most theologically sophisticated element of the decomposition and the most commonly under-detected. Many sermons contain BT moves that are implicit in the pastor's reasoning even when not explicitly labeled. Common patterns to watch for:

- A pastor connecting an OT text to Christ or the cross (typology or fulfillment)
- A pastor citing an OT passage alongside a NT passage to show development (progressive_revelation)
- A pastor placing the sermon's text on the map of the grand biblical narrative (narrative_arc)
- A pastor noting shared language or imagery between two passages (intertextual_echo)
- A pastor juxtaposing old covenant and new covenant realities (contrast)
- A pastor tracing a theme (rest, exile, temple, kingdom) across multiple books (thematic_thread)
- A pastor using one passage to interpret or qualify another (canonical hermeneutics producing any of the above)

Each move captures:
- `type` — Enum: `typology`, `fulfillment`, `progressive_revelation`, `narrative_arc`, `intertextual_echo`, `contrast`, `thematic_thread`.
- `source_text` — The earlier canonical reference being drawn from.
- `target_text` — The later canonical reference where fulfillment/echo/development lands.
- `pastor_framing` — One sentence capturing how the pastor articulated the connection in his specific language. This reveals hermeneutical instincts and serves voice replication and archetype analysis.

---

### Additional Unit Fields

**`people_referenced`** — Array. Historical figures, theologians, biblical characters mentioned.

**`sermon_series_context`** — How this unit connects to the broader series if detectable.

---

## Processing Notes

### Unit Boundary Rules

- Units are defined by **rhetorical function shift**, not paragraph breaks or character count.
- A unit can be a single sentence (transitions) or several paragraphs (extended exposition).
- **When two distinct rhetorical functions occur within the same passage, split into separate units** — even mid-paragraph. A theological claim followed by an illustration supporting it should be two units, not one. A doctrinal assertion with an embedded pastoral anecdote should be split at the point where the function shifts. The test: if the material serves two different purposes, it belongs in two different units.
- Exception: brief embedded quotations or single-sentence illustrations that are syntactically woven into a larger unit need not be split if they serve the enclosing unit's primary function without constituting a distinct rhetorical move.
- The `content` field preserves the pastor's exact language. No paraphrasing, no cleanup, no grammatical correction. The voice is the asset.
- If a field cannot be determined from the manuscript, set it to null. Do not fabricate metadata.

### Output Consistency

Maintain the same granularity and analytical rigor from the first unit to the last. The final third of a sermon requires the same precision in unit boundary detection, rhetorical function assignment, and metadata tagging as the opening. Do not allow units to grow progressively larger or less precisely segmented as the sermon continues. A conclusion with three distinct rhetorical moves (synthesis, doxological climax, eschatological charge) requires three units — not one large unit tagged `conclusion`. A closing prayer deserves the same careful boundary detection as the opening exposition. If you notice your units growing longer or your metadata growing sparser toward the end of the sermon, you are losing precision — stop and correct.

### Taxonomy Discipline

- Use **only** the rhetorical functions defined in this spec. Do not invent new values (e.g., do not create `quotation`, `exhortation`, `narrative`, or other ad hoc functions).
- Use **only** the doctrinal loci defined in this spec.
- Use **only** the enum values defined for each field. If no defined value fits, use the closest match and note the ambiguity in the `summary` field.

### Key Claim Discipline

- The `key_claim` must capture what **this unit** asserts — do not reach forward to claims established in later units or backward to claims from earlier units.
- The claim should be propositional: a statement that can be affirmed or denied.
- Null is appropriate for transitions, prayers, and illustrations that serve other units' claims.

---

## Pending Fields (Deferred to v4 — Requires Validation)

The following fields have been identified as high-value additions but are deferred pending validation across a larger corpus (target: 330 sermons across 11 preachers). They may be added via augmentation passes on already-decomposed sermons without requiring full re-decomposition.

**`anticipated_objection`** — Captures moments where the pastor surfaces and responds to an implicit counter-argument. Sub-fields: `objection_text` (what the objector would say) and `response_strategy` (enum: `direct_refutation | reframe | concede_and_pivot | rhetorical_question`). The single most valuable reasoning pattern for training data purposes. Deferred because frequency across preachers is unknown — needs validation before committing to the schema.

**`serves_unit`** — Links units to the other units they serve, turning the flat JSON list into a directed argument graph. Sub-fields: `unit_index` (the unit being served) and `relationship` (enum: `illustrates | supports | rebuts | qualifies | applies | anticipates`). Potentially the highest-value structural addition. Deferred because the design question of single-parent vs. multiple-parent references is unresolved.

**`hinge_statement`** — Boolean on transition units indicating whether the transition contains an explicit structural signal (a clear pivot between major sections). Deferred pending expert homiletical definition of what constitutes a hinge vs. mere connective tissue.

**`is_fcf_moment`** — Boolean with optional description flagging Fallen Condition Focus moments — where the pastor identifies the human problem or need the passage addresses. Deferred as lower priority.

---

## Changelog

### v3 (March 2026)

**Tier A — Prompt-Level Fixes:**
- Tier 1 vs. Tier 2 citation classification: Added explicit rule that Tier 1 is restricted to verses falling within the declared `primary_text` range. All other scripture is Tier 2 regardless of delivery mode.
- Biblical-theological move detection: Added active detection instructions with common pattern examples to address systematic under-detection observed in v2 output.
- Unit-splitting guidance: Strengthened instruction to split units when two distinct rhetorical functions co-occur. Added test criterion and exception for trivially embedded material.
- Rhetorical function taxonomy discipline: Added explicit instruction to use only defined values, with fallback guidance.
- Key claim discipline: Added instruction to keep claims within the unit's own scope, preventing forward-reaching claims.
- Introduction positioning: Clarified that `introduction` may appear after scripture reading and prayer if the pastor delays the sermon's framing.

**Tier B — New Fields:**
- `illustration_type` — Enum on illustration units classifying the source type of the illustrative material. Serves PASTORALRAG retrieval, Forge coaching, Guild Hall archetype analysis.
- `application_specificity` — Enum on application units classifying the concreteness of the instruction. Serves Forge coaching and archetype differentiation.
- `rhetorical_register` — Enum array on all units classifying the persuasive mode. Serves archetype differentiation (distinguishing Sproul's logos from Mahaney's doxological from Evans's narrative), Forge coaching, and TRAININGDATA.

**Deferred to v4:**
- `anticipated_objection`, `serves_unit`, `hinge_statement`, `is_fcf_moment` — All flagged with rationale for deferral. Designed to be addable via augmentation pass without full re-decomposition.
