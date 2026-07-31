# Creator Video Production workflow v1

This application-owned workflow is the only orchestration authority for Creator
Video Production projects.

## Authority

- Production owns state transitions, instruction assembly, selection,
  compilation, validation, review, rendering, and delivery.
- The final locked transcript is the only word-timing authority. Its word IDs,
  seconds, and frames are consumed exactly and are never realigned.
- The locked cut and locked-cut audio are immutable inputs.
- Chapters are completed editorial sections. Duration targets cannot create,
  split, truncate, or extend a chapter.
- Sequences are coherent editorial/visual units, not transcript sentences or
  cadence slices. Production issues only evidence-backed semantic-unit
  boundaries and validates the whole plan before accepting any decision.
- HyperFrames rules, blueprints, transitions, registry material, and runtime
  primitives are bounded capability sources. They do not own orchestration.

## Required execution order

1. Verify the workflow lock and all retrievable immutable resources.
2. Verify locked-cut, audio, transcript, and exact word-timing identity.
3. Resolve and freeze the production and channel profiles.
4. Analyze the complete episode before selection.
5. Inspect the locked source and classify every source span against the frozen
   creator-approved eight-layout OBS catalog. Production applies catalog
   geometry; the agent never invents rectangles.
6. Materialize explicit sequences, composition graphs, transitions, and
   semantic chapters without gaps.
7. Compile deterministically without creative defaults.
8. Pass semantic, timing, spatial, seek, transition, provenance, and parity
   gates.
9. Review the exact build represented by the build lock.
10. Render only approved build inputs, reusing unchanged chapter bytes.
11. Assemble and verify the final delivery against the locked source/audio.

## Forbidden routing

Do not discover, load, invoke, or defer orchestration to user-scoped native
workflow routers or end-to-end video skills. In particular,
`talking-head-recut`, `general-video`, `motion-graphics`,
`hyperframes-creative`, native automatic HyperFrames animation selection,
product-launch, faceless-explainer, website-to-video, PR-to-video,
music-to-video, and embedded-captions are not workflow authorities here.

No unknown capability or transition may fall back to another implementation.

## Execution host

Production work is handed to a normal user-visible Codex task through an
immutable file packet. The application never starts, hides, or waits on a nested
Codex process. The task explicitly claims the packet, records the skills visible
in its startup context, reads the exact frozen workflow and domain resources
named by the packet, and writes one schema-bound output.

A task exposing a forbidden end-to-end video workflow cannot claim the packet.
The application independently verifies packet hashes, locked identities,
capability bindings, state transitions, and every downstream gate before it
promotes output. App restarts do not interrupt or silently retry a visible
handoff. The creator may cancel a handoff at any time, after which no output
from it can be promoted. An OpenAI API key is not part of this workflow.
