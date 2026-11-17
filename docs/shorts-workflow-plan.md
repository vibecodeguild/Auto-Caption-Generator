# Shorts workflow implementation plan

Recorded October 13, 2026. Product decisions below were agreed in conversation.
The workspace mockup and product direction were accepted in conversation. The
implementation sequence below is retained as the planning record. An initial
implementation now exists; verification status is recorded at the end.

## Agreed product contract

- Add **Shorts** as a new listing in the existing Tools menu and a dedicated
  workspace attached to the active private video project.
- Use the **locked cut before graphics** and its matching final transcript.
  Content is talking head, with no demo or screen-share layouts.
- Produce a 9:16 composition with **title at the top, the entire widescreen
  picture below it, captions underneath, and a black background**. Preserve the
  source picture's aspect ratio and full extent.
- Find self-contained candidates from the final long-form transcript, including
  candidates assembled from several source sections where editorially useful.
  Prefer a clear opening, useful substance, and a complete ending. No preferred
  duration, mandatory short length, or invented performance score.
- Review and fine-tune start/end boundaries and joins by frame nudges, following
  existing splice-review patterns. Do not add transcript-word deletion controls.
- Transcribe the assembled short into its **own saved caption transcript**.
  Caption preview and export use that same transcript. Timing edits make it stale.
- Draft posting copy for Facebook, LinkedIn, YouTube, TikTok, Instagram, and
  Threads, with no CTA initially. Additional destinations can be added deliberately.
- Keep long-form project edits, graphics placements, and existing outputs intact.

## Superseded proposal

The initial proposal derived caption timings by remapping the long-form
transcript into the short. That proposal is superseded by the short-owned
transcript above. The long-form transcript still identifies candidate source
sections; it does not supply the short's caption timing authority.

## Proposed workspace

Keep the existing application header, project utilities, and Tools menu. Add
Shorts without changing other tools. A compact local rail contains **Edit**,
**Captions**, **Posting**, and **Export**.

The left column lists suggested shorts with title, duration, section count, and
review state. Import Plan and New Short are the entry points. The center shows
the 9:16 composition. The right panel changes with the selected rail step.
At smaller widths, these regions stack rather than shrink the player or hide
essential controls.

Edit shows the title field, ordered source sections, and the selected start,
end, or join controls. Use source timecodes and frames, with the established
one-, five-, and ten-frame adjustments and short join auditions. A single-section
short exposes its two endpoints. Multi-section shorts also expose each join.
No general timeline editor, transcript deletion, or automatic silence removal.
Adding or reordering sections interactively is outside this first editing scope;
an imported plan may already contain several sections in playback order.

The composition preview uses one saved layout specification for both browser
preview and final rendering. The exact title font, spacing, and region positions
are proposed visual details, not additional approved brand defaults. Preserve
the complete source picture and keep title and captions in their separate regions.

Captions exposes the existing style and grouping controls, Prepare Captions,
and a clear current/stale state. The transcript is a saved word-timing artifact,
not an audio-editing surface. Manual caption-text correction is a possible
follow-up, not a dependency of the initial implementation.

Posting shows editable destination drafts derived from the actual short's
transcript. Export provides readiness, progress, cancellation, result paths,
and failure details in the existing workspace/modal patterns.

## Candidate selection and handoff

Use the existing agent-host workflow: supply the final transcript and request
an importable Shorts plan. Do not introduce an in-app AI provider, API-key
requirement, or automatic candidate generation service in this tranche.

Each candidate records an id, working title, selection rationale, context/join
concerns, and an ordered list of source sections. Each section identifies start
and end word ids in the selected final transcript. The app resolves anchors to
frames and validates them. Numeric time guesses are not authoritative.

Bind the plan to the project id, locked-cut content hash, final-transcript hash,
and source frame rate. Reject a mismatched import with an actionable explanation;
do not silently map it to a newer video. Validate unique candidate/section ids,
known anchors, positive ranges, and media bounds. Source sections need not appear
in chronological order; playback follows their explicit list order. Warn about
repeated or overlapping content for human review rather than silently dropping it.

Preserve the imported suggestion separately from the human-reviewed working
copy and an edit ledger, following the project's existing review conventions.
Manual creation uses the same candidate and section model, with source in/out
selection and the same validation.

## Timing and transcript lifecycle

1. Resolve approved source sections and frame nudges into an immutable edit
   snapshot. Keep source timing separate from assembled-short timing.
2. Render the assembled short's clean audio/video to private working storage.
   Show the assembled playback for checking joins before preparing captions.
3. Transcribe that exact assembled audio with the existing supported local
   transcription engine and settings. Save word times relative to short start.
4. Save provenance tying the caption transcript to the assembled-media hash,
   edit revision, engine/model, compute settings, and duration.
5. Group and style those saved words for preview and export using the existing
   caption primitives. Export does not independently transcribe again.

Changing section boundaries, membership, or order invalidates assembled media,
caption timing, posting copy, and delivery output for the current revision.
Keep prior successful artifacts, but visibly mark them stale and prevent their
accidental use as current exports. Require explicit Prepare/Regenerate Captions
before captioned export. Never overwrite the previous transcript on a failed job.

Title or caption-style changes invalidate only affected visual outputs. Platform
copy edits do not trigger transcription. A successful regeneration writes a new
transcript revision; do not silently replace manually reviewed posting drafts.

The existing standalone Caption Generator remains unchanged in this tranche.
Reuse its grouping, ASS styling, fonts, and subtitle renderer through a
transcript-consuming Shorts path. Its current export re-transcription behavior
is not copied into Shorts and is not fixed as unrelated scope.

## Proposed persistence and job behavior

Keep all content inside the active private project, outside the public checkout.
Proposed versioned paths:

- `shorts/shorts-plan.original.json`: imported suggestions and source provenance.
- `shorts/shorts-plan.reviewed.json`: current decisions and revision references.
- `shorts/shorts-edit-ledger.json`: human review and frame changes.
- `shorts/<short-id>/transcripts/`: revisioned short-owned caption transcripts.
- `shorts/<short-id>/posting.json`: destination drafts and content revision.
- `working/shorts/<short-id>/`: assembly, render staging, and job receipts.
- **Superseded:** `exports/shorts/<short-id>/<job-id>/` delivery folders.
- **Approved simplification (2026-10-14):** delivery files go directly in
  `exports/shorts/`, for example `01-a-useful-short.mp4`,
  `01-a-useful-short-posting.json`, and `01-a-useful-short-posting.txt`.
  Repeat exports add a numbered suffix, preserving earlier packages. Internal
  Shorts transcript, staging, and decision paths stay unchanged.

The user rejected the proposed broader folder remapping/consolidation. Keep all
existing parent-project path mappings and non-Shorts export layouts unchanged.
New projects create only folders currently needed; tool output folders appear
on first write. Do not move or delete existing folders or migrate projects.

Older projects need no migration to open. Missing Shorts data means an empty
workspace. Load known schema versions explicitly and reject unsupported data.
Validate all relative paths against the active project root. Source files,
locked cuts, and long-form transcripts are read-only inputs.

Jobs capture the project, source, edit, and caption revisions at start. Prevent
duplicate jobs for the same operation, expose cancellation, and do not let a
late result replace newer decisions. Reopening the workspace restores persisted
status; an interrupted job is reported honestly rather than shown as running
forever. Stage and verify outputs before publishing their revision references.
Cancellation and failure retain the previous successful output.

## Posting and delivery

Candidate length follows the content. Evaluate destination compatibility
separately; show why a specific destination needs a shorter version instead of
silently trimming speech. Keep platform constraints centralized and dated, with
official references verified during implementation. Do not hardcode one
universal duration limit or infer guaranteed performance.

Agent-authored posting drafts can accompany a candidate plan, but remain
provisional until checked against the assembled short's own transcript. The
agent handoff for final copy includes that transcript and selected destinations.
Persist editable titles/opening lines, descriptions/post text, and optional
relevant hashtags according to destination. No invented claims or CTA.
No publishing, scheduling, or social-account connections in this scope.

The core delivery is a captioned 1080 x 1920 MP4 and the posting drafts. Proposed
optional additions are a clean vertical MP4 and an SRT companion; these are not
required to prove the core milestone. Distinguish the on-video title from the
platform title so editing one does not silently change the other.

## Implementation sequence and acceptance

| Milestone | Proposed work | Acceptance evidence |
| --- | --- | --- |
| 1. Layout and workspace review | Approve this plan and the mockup; establish the new Tools entry and empty/project states after implementation authorization | Agreed composition visible; existing tool navigation unaffected |
| 2. One section through delivery | Persist a manual short, nudge endpoints, assemble, transcribe, preview captions, export | Full 16:9 image preserved; title above and captions below on black; export uses saved caption words and matches preview |
| 3. Plans and stitched shorts | Import source-bound candidates, review joins and frame adjustments, persist review history | Correct ordered audio/video sections; no clipping or timing drift at joins; mismatched plans rejected |
| 4. Posting packages | Import/review final platform copy, compatibility results, delivery package | Copy matches the actual short; requested destinations present; no CTA inserted |
| 5. Production verification | Exercise reopen, stale states, cancellation, failures, and representative talking-head footage | All acceptance checks below pass before feature handoff |

For implementation, run relevant model/API tests, TypeScript typecheck, the
production build, and the repository privacy guard. Add meaningful coverage for
source mismatch, boundary clamping, ordered concatenation, caption provenance,
staleness, stale-job completion, and preservation of prior outputs.

Use a generated public fixture with distinguishable sections/audio to verify
real FFmpeg duration, section order, frame geometry, and caption placement.
Exercise the workspace in-browser at desktop and narrow widths, including Tools
navigation, frame nudges, caption readiness, and reopening saved data. Then
verify single-section and stitched exports against representative private
talking-head footage without committing that footage or transcript.

Review the final diff for changes to existing workflows and documentation drift.
The user retains ownership of starting and stopping application servers. Do not
change transcription defaults, long-form editing, graphics engines, or existing
Caption Generator behavior as part of this feature.

## Initial implementation status

Tools → Shorts now implements manual source selection, word-anchored candidate
import, ordered assembly, frame nudges and boundary auditions, short-owned local
transcription, shared preview/export caption data, vertical rendering, and
editable posting packages. Agent-host briefs and imports serve candidate
selection and copywriting; no in-app AI provider or publishing service was added.
The optional clean vertical MP4 and SRT companion remain outside the initial
delivery. Existing long-form and standalone caption behavior is unchanged.

Generated-media checks exercise real FFmpeg trimming, reversed section order,
matching audio order, output duration, portrait dimensions, black background,
and rendered title/caption regions. Local inference is substituted in automated
fixtures; real talking-head transcription and visual approval remain production
validation steps. Source mismatch, stale captions, late jobs, cancellation,
posting provenance, persistence, and API import behavior have regression coverage.

The first full run passed 472 tests and failed three existing cut-export tests.
Those same failures were reproduced against the checked-in pre-Shorts API source:
the tests expect synchronous responses and normalization off, while the current
API uses jobs and defaults normalization on. This feature does not change that
existing behavior or rewrite those tests. The focused Shorts/API/inventory check
passes 30 tests. Production build passes.

Browser verification against the user-started servers exercised Tools navigation,
the empty state, manual source IN/OUT selection, frame nudges, assembly, actual
Large v3/NVIDIA transcription, caption readiness, and a real vertical export.
The private preview short contains 51 transcribed words and exports at 1080 x
1920, 30 fps, exactly 15 seconds, with both posting files present. Nudging a
boundary made captions stale and disabled export; restoring the exact edit
restored its matching artifacts. Narrow-screen composition geometry was also
checked in the browser. A private preview short is retained in the user's project.

The selected test project's locked cut already contains small burned-in captions.
Those remain in its complete source picture alongside the new Shorts captions.
Use a clean locked cut to avoid duplication; masking or cropping the source was
not added as a workaround. Posting-copy import and stitched audio/video order
have automated coverage; the live browser run used a single-section short.
