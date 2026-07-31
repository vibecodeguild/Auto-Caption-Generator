# Creator semantic planning contract

## Purpose

The planning agent decides what the viewer should see and which spoken idea
controls each reveal. The application, not the agent, owns transcript identity,
word identity, source frames, coverage math, locked capability facts, and
promotion.

This separation prevents an editorially plausible plan from advancing with
invented or off-by-one transcript timing.

## Authority split

The planning agent owns:

- sequence and chapter editorial starts selected from application-issued
  boundary references;
- exact spoken phrases selected within an analysis proposition;
- concise on-screen copy and copy mode;
- reveal, fully-visible, and exit intent expressed as issued span edges or
  sequence edges;
- multi-beat accumulate/replace behavior;
- source strategy, semantic purpose, visual-change intent, and truthful
  editorial capability assessments.

A sequence is one continuous visual treatment or source strategy serving one
coherent editorial idea. It may contain multiple transcript propositions and
multiple meaningful internal changes. A sentence boundary, proposition
boundary, internal reveal, or five-second interval is not independently a
sequence boundary.

The application owns:

- verification that analysis propositions exactly match locked transcript
  words and inclusive/exclusive frame semantics;
- validation that semantic units cover propositions once and that only
  evidence-backed semantic-unit starts become sequence boundary choices;
- exact observed source-change and intentional-carry evidence;
- validation of exact visible UI-label observations against one locked source
  frame, plus validation of verbatim commands against transcript evidence;
- content-bound `copy-evidence:*` references issued only from those validated
  observations;
- phrase lookup inside the selected proposition;
- immutable spoken-span receipts containing word IDs and frames;
- contiguous sequence coverage, final sequence end, chapter ranges, and
  sequence word ranges;
- locked recipe resource IDs and hashes, catalog ordering, global restrictions,
  runtime facts, and implementation maturity;
- construction and validation of the existing `semantic-manifest`;
- atomic promotion of validated decisions, the materialized semantic manifest,
  its receipt, and deterministic sequence decisions.

## Planning protocol

1. The application validates the analysis ledger against the locked transcript.
2. It gives the planning task opaque boundary/cause pairs only for valid
   semantic-unit starts. Continuation and elaboration starts are not issued.
3. The agent calls `resolve-span` with a proposition ID and exact spoken phrase.
4. The application searches only that proposition. A unique match receives a
   signed-by-content `spoken-span:*` receipt. Repeated matches return candidate
   references plus local context and require an explicit candidate selection.
5. For a verbatim command or exact visible UI label, the agent selects an
   application-issued `copy-evidence:*` reference and copies its text exactly.
   A source-event ID, scene range, or agent-invented reference is invalid. The
   job-specific output schema accepts only references issued for that job.
6. The agent submits `editorial-plan-decisions`, which cannot contain raw
   frames, word IDs, source hashes, or recipe hashes.
7. The application resolves every reference, derives all ranges and locked
   facts, constructs the production `semantic-manifest`, and runs the existing
   semantic validators.
8. Once the document is structurally readable, validation returns every
   independently reachable planning error in one response, including its JSON
   path, invalid value, and compatible issued choices when applicable. Each
   rejected submission is preserved with its diagnostic.
9. A failed submission never promotes or partially freezes decisions. The task
   gets one initial submission and at most two corrections. A third failure
   terminates the job, preventing an infinite correction loop. Only the complete
   plan becomes immutable after whole-plan structure, evidence, cadence, and
   local validation all pass.
10. A successful submission is completed and promoted atomically. Downstream
   layout classification, adaptation, materialization, preflight, and rendering
   continue to consume the existing semantic manifest.

## Invariants

- The agent cannot author raw transcript timing.
- Repeated phrases are resolved within their selected proposition, never by a
  whole-transcript first match.
- Sequence coverage is gap-free and overlap-free by construction.
- Multi-beat graphics use independent, transcript-backed span references.
- Exact UI labels and verbatim commands use compatible, application-issued
  copy-evidence references and reproduce their observed text exactly.
- Sequence boundaries never satisfy meaningful-change cadence.
- Source-origin changes and carries use unique analysis evidence; authored
  changes must bind both a spoken beat and an actual materialized graph event.
- No failed or partially materialized plan becomes current project authority.
- Every failed planning submission and its full diagnostic remain inspectable.
- The correction loop is bounded and does not pause for creator review.
- Rendering and HyperFrames recipe execution are outside this contract and are
  unchanged.
