# Semantic episode planning task

Using only the locked transcript, whole-runtime analysis ledger, resolved
Production profile, resolved channel profile, capability catalog, and
application-issued boundary choices, produce one
`editorial-plan-decisions` JSON document.

This task makes editorial decisions. It does not calculate or copy transcript
word IDs, source frames, hashes, recipe evidence hashes, candidate order, or
chapter/sequence end boundaries. Those values are owned by the application.

## Transcript-bound decisions

A sequence is one continuous visual treatment or source strategy serving one
coherent editorial idea. It may contain multiple propositions and multiple
internal reveals or state changes. A sentence, proposition, five-second cadence
interval, or internal reveal does not by itself create a sequence.

Choose each sequence start from a supplied `boundaryRef` and
`boundaryCauseRef` pair. Production issues pairs only for analyzed semantic-unit
starts. Copy the issued `boundaryRef` into the decision's `startBoundaryRef`
field and keep its paired `boundaryCauseRef`; it derives the complete,
contiguous sequence coverage from the ordered starts. Choose each chapter start
from the first sequence in that completed
editorial section. Divide chapters only at completed editorial sections, like
meaningful YouTube description chapter breaks. Never create, split, merge, pad,
or truncate a chapter because of elapsed duration.

For every spoken beat, call the task handoff's `resolve-span` command with the
analysis proposition ID and the exact spoken phrase. Use only the returned
`spoken-span:*` receipt ID as `spanRef`. If a phrase occurs more than once in
that proposition, select one of the returned candidates using its surrounding
spoken context; never guess from the whole transcript. Timing anchors must
refer to an issued `spanRef` edge or a sequence edge.

For longer treatments, describe every ordered spoken beat and choose
`accumulate` or `replace` behavior. Planning owns the exact concise on-screen
copy, the spoken phrase it corresponds to, when it begins revealing, when it is
fully visible, and when it exits. Commands and visible software labels use
one compatible application-issued `copyEvidenceRef`. Their on-screen text must
exactly match the issued evidence's `observedText`, including capitalization and
punctuation, and the evidence proposition must match the resolved spoken span.
Source-event IDs and raw frame evidence strings are different reference types
and are forbidden in `copyEvidenceRef`. If no compatible receipt was issued,
record the missing evidence as unresolved instead of inventing a reference.
Prompts are summarized into concise editorial emphasis, not reproduced in full.
Copy must pass spelling, punctuation, and grammar review.

## Editorial treatment decisions

Choose semantic intent, presentation role, narrative-state role, candidate
canvas topologies, and truthful capability assessments. When the resolved
channel profile enables Graphics Library–only planning (or full-catalog
evaluation), assess every supplied planning capability ID exactly once. Do not
order or shortlist capabilities; the application owns frozen catalog order and
deterministic ranking. Prefer light callouts, captions, lists, and UI labels
that keep the speaker and demonstration mostly visible.

Read the exact frozen source recipe for every treatment before assessing it.
A capability name, alias, or filename is never semantic evidence. Name the
exact compatible recipe role and explain how it serves the sequence's
editorial job. If the recipe's stated intent, roles, or required media do not
serve the sequence, mark it semantically incompatible. Do not provide recipe
resource IDs or hashes; the application supplies those from the locked catalog.

Source-led sequences that do not plan an authored graphic must use empty
`capabilityAssessments`. If a source-led sequence genuinely adds an authored
graphic, classify it as hybrid and apply the full assessment rules.

For every authored or hybrid sequence, assess the complete supplied planning
catalog when the channel profile requires full-catalog evaluation or Graphics
Library–only planning. Otherwise, follow the profile's candidate requirements
without stopping at the first match. Record only the editorial exclusions,
editorial criterion values, and assumptions requested by the output schema. The
application supplies global, creator, runtime, lifecycle, and
implementation-maturity facts, then ranks the candidates deterministically. Do
not self-declare a winner.

Viewer-facing visual moments must land about every five seconds. A multi-beat
list counts once per revealed bullet. Intentional demo holds are allowed, but
they cannot blank the whole video and cannot run forever without light
emphasis. Sparse plans such as one graphic per minute are rejected.

For every sequence, write the complete editorial directive. Graphics must
explain the spoken idea, protect useful source footage and the speaker, and
provide meaningful visual changes. Screen-share demonstrations may use
emphasis overlays, exact UI labels, highlights, celebrations, and captions, but
must not be covered by a sustained authored treatment. A planned performance
or demonstration change must cite one exact supplied
`sourceVisualChangeRef` and use `null` for `at`; Production derives its exact
frame from the evidence. An authored change must cite one spoken beat. A
planned performance or demonstration carry must cite one exact supplied
`carrySpanRef`. When the same verified source event continues across multiple
independently issued semantic sequences, cite that same receipt in each
applicable sequence; Production derives and records the exact overlap. Never
invent carry fragments or use carry evidence to manufacture sequence
boundaries. A sequence boundary is not itself a meaningful visual change.

Do not choose final implementation bindings or write a composition graph.
Record every unresolved editorial issue explicitly.

Submit the document through the task handoff's `submit-decisions` command.
Correct every reported problem before resubmitting. Once the JSON structure is
valid, Production reports all independently reachable reference, evidence,
timing, structure, and cadence errors together with exact paths and compatible
choices. The application permits at most three validation submissions (the
initial submission plus two corrections). Every failed submission is preserved
with its diagnostic, but freezes no partial editorial decisions. Only a
complete plan that passes whole-plan structure, evidence, cadence, and local
validation may be completed and promoted.

Do not invoke another workflow and do not write outside the task output.
