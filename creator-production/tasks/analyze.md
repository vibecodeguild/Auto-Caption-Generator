# Whole-runtime analysis task

Read the locked final transcript and inspect the locked video across its complete
runtime. Produce one `analysis-ledger` JSON document.

The ledger is channel-neutral evidence. It must cover every frame without gaps
and record propositions, contiguous semantic units, semantic beat kinds,
relationships, source events, gesture/reaction/joke/demonstration evidence,
subject and screen geometry, candidate protected regions, semantic asset needs,
uncertainty, and unresolved ambiguity.

A semantic unit is one coherent spoken idea or demonstration step and may
contain multiple propositions. Sentence boundaries do not create semantic
units. Mark continuation and elaboration relationships explicitly; Production
does not issue sequence boundaries for them.

Record each meaningful source-footage change as one exact
`observedVisualChanges` frame with evidence. A broad demonstration section does
not prove a change at every sentence. Record only the exact bounded
performance/demonstration ranges that genuinely carry the explanation in
`intentionalCarrySpans`. Adjacent or overlapping carry fragments from the same
source event must be one continuous span.

Record exact visible software labels in `copyEvidence` only after inspecting
the locked frame where the text is readable. Copy the visible spelling,
capitalization, and punctuation exactly, cite
`locked-cut:frame:<absoluteFrame>`, and bind the observation to its source event
and transcript proposition. Broad scene ranges and contact sheets are not exact
UI-label evidence. Record verbatim spoken commands against their exact
transcript proposition evidence. Do not invent opaque evidence IDs; Production
derives and issues those IDs after validating the analysis ledger.

Do not choose a presentation role, narrative-state role, visual treatment,
canvas topology, capability, blueprint, transition, or chapter duration.
Do not alter, offset, smooth, regenerate, or reinterpret transcript word timing.
Do not write outside the task output.
