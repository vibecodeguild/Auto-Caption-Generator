# Creator Production Implementation Checkpoint

Updated: 2026-07-29

## Authority and execution decision

`creator-video-production` is the sole workflow authority for new creator-video
projects. The retired Visual Production path remains recovery-only and is not an
input to Creator Production.

The former execution-host design is superseded. The application must not start,
hide, or wait on `codex exec`, `codex debug`, an ephemeral Codex process, or any
other nested Codex instance. A job now produces an immutable, schema-bound
handoff packet. A normal user-visible Codex task claims that packet, records its
visible skill inventory, writes the requested output, and asks the application
to validate and promote it. Cancellation prevents later promotion. Application
restart does not falsely mark a visible task interrupted.

The current task inventory contains no native HyperFrames or end-to-end
video-production skill. The fixture's claim receipts record the complete visible
inventory and reject forbidden skill IDs. Renderer and capability source are
frozen private project dependencies, not ambient workflow instructions.

## Implemented platform state

Implemented:

- Production-only workflow ownership and forbidden-workflow contract;
- immutable workflow, profile, capability, transcript, and project-state
  artifacts;
- immutable visible-task handoff packets, claim receipts, run receipts, and
  schema-bound output promotion;
- complete native animation capability inventory and sequence-scoped adaptation;
- exact word/frame timing authority and locked encoded-audio identity;
- semantic and materialized manifests with completed editorial chapters;
- creator-approved OBS capture-layout classification and derived source evidence;
- protected-region, canvas, timing, diversity, transition, and speaker-visibility
  preflight gates;
- deterministic admitted capability execution and exact implementation binding;
- explicit source pass-through that is not misclassified as duplicated authored
  design;
- sequence-scoped composition mounting, namespaced element IDs, allowlisted
  element styling, and source-video event targeting;
- Studio handoff and constrained edit import;
- final-quality chapter cache, localized invalidation, stream-copy assembly,
  seam checks, and one-time locked-audio attachment;
- single moving review surface, autosaved notes, and approval state;
- versioned channel profiles without channel-specific renderer branches.

The superseded nested-process implementation and its isolation-probe tests have
been removed. The legacy workflow-lock schema branch remains readable so frozen
history can still be verified.

## Transcript-bound semantic planning correction

The former plan task asked Codex to author the production semantic manifest
directly, including transcript word IDs, absolute frames, end-exclusive ranges,
recipe hashes, and candidate order. Schema validation could prove only that
those self-declared values were internally shaped correctly; it did not prove
that they came from the locked transcript. That allowed the July test analysis
to use inclusive last-word frames as end-exclusive proposition frames.

Planning now emits `editorial-plan-decisions`. Codex chooses editorial starts
from application-issued boundary references and resolves every exact spoken
phrase through the application within a selected proposition. The application
issues immutable spoken-span receipts, derives all sequence/chapter coverage
and word/frame fields, injects locked capability facts, and constructs the
existing downstream `semantic-manifest`.

The application validates analysis propositions against the locked transcript
before planning. Invalid decisions cannot promote. A plan receives one initial
submission and at most two correction submissions; the third failure terminates
the job without creator-review pauses or an infinite retry loop. Successful
decisions, their application-built semantic manifest, its materialization
receipt, and the deterministic sequence-decision index promote atomically.

The full authority split and command protocol are documented in
[Creator semantic planning contract](creator-semantic-planning-contract.md).

### Whole-plan structure and evidence correction

The former correction contract retained a locally valid prefix from a failed
planning submission. That decision is superseded. Editorial structure,
meaningful-change cadence, carries, chapters, and whole-video variation are
global properties, so no sequence or chapter is independently accepted until
the complete plan passes.

Analysis now groups propositions into contiguous semantic units and separately
records exact observed visual changes and continuous intentional-carry spans.
Planning receives boundary/cause references only for eligible semantic-unit
starts. Sentence, proposition, internal-reveal, and five-second boundaries are
not sequence boundaries. Source-origin changes and carries require unique
analysis evidence; authored changes require a spoken beat and a matching
materialized graph event. Failed submissions retain no editorial decisions;
the existing three-submission limit remains unchanged.

Verification after this correction: 377 Python/web-contract tests pass with 5
environment-dependent skips; TypeScript typecheck and the Next.js production
build pass.

## HyperFrames recipe-conformance correction

The former adaptation gate loaded only the selected blueprint. It did not
automatically load the governing animation contract, runtime adapters,
referenced atomic rules, or matching runnable example. That incomplete handoff
allowed an inferred implementation to reach admission.

Every inventoried HyperFrames capability now records a frozen instruction
dependency set. Adaptation preparation resolves that set from the selected
capability automatically. Admission requires the adaptation to retain the exact
resource IDs and hashes, and fixture validation rejects animated layout
properties such as `left`, `top`, `width`, and `height` before the implementation
can become selectable.

## End-to-end test state

The disposable July 23 fixture and its 28-segment generated plan were removed
after exposing the incomplete recipe handoff. They are not accepted test
evidence and must not be reused.

The later July analysis test also is not accepted evidence: its proposition
ends used the inclusive last-word frame as an end-exclusive frame. The new
analysis promotion gate rejects that artifact. The private project must receive
an explicit workflow-package upgrade, which invalidates the bad analysis and
all dependent planning artifacts, before the production test restarts from
analysis. This implementation did not run or mutate that private test project.

## Verification results

Verification after the transcript-bound planning correction:

- 368 Python and web-contract tests pass, with 5 environment-dependent skips;
- TypeScript typecheck passes;
- the Next.js production build passes;

No analysis, browser visual preflight, replacement plan, approval, or render
was started as part of this implementation.

Development servers remain owned by the user in VS Code and must not be started,
stopped, or replaced during verification.
