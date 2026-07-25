# Active Build Plan

Approved: July 10, 2026.

This plan records the next production work for VCG AutoCaption. The application
is used daily, so changes must remain incremental, backward compatible, covered
by regression tests, and independently reversible.

Addendum approved July 11, 2026: Visual Production is a separate workflow after
the cut and audio are locked. It must not be inserted into Stage 4 or alter the
accepted five-stage transcript-edit contract. Its implementation contract lives
in [Visual Production Workflow](visual-production-workflow.md).

Addendum approved July 11, 2026: the earlier single-source Phase 1 assumption is
superseded. A parent project may contain an ordered sequence of recordings.
Phase 1 builds one deterministic working source, preserves clip boundaries, and
invalidates downstream artifacts whenever the sequence changes.

Addendum approved July 11, 2026: Visual Production expands with the private
Creator Library, structured suggestions inbox, Pexels-only B-roll candidates,
license evidence, and unified approval queue defined in
[Visual Storytelling Assets](visual-storytelling-assets.md).

Addendum approved July 14, 2026: the next Visual Production slice is the shared
review-and-sync workflow defined in
[Visual Production Workflow](visual-production-workflow.md). Documentation is
the implementation contract and must be updated before code. The authorized
scope is:

1. docked per-item notes with mutually exclusive **Leave everything else** and
   **Replace all of it** directives;
2. active **Changes requested** and **Ready for review** states, easy navigation,
   acceptance, and durable accepted-note history;
3. a **Copy All Notes** handoff containing only non-empty notes plus exact
   timestamps, stable IDs, private project context, and preservation scope;
4. automatic plan persistence and an explicit reload path so browser edits and
   Codex/HyperFrames edits use the same private files;
5. direct drag/resize manipulation for imported image and video overlays;
6. distinct B-roll and AI-footage planning lanes; and
7. a Generated panel that distinguishes renderable **Ready** modules from
   **Needs Build** treatment requests.

This slice does not authorize a new renderer, a generalized keyframe editor,
automatic AI generation, fake renderable module IDs, or changes to locked-cut
timing and audio.

Implementation note, July 14, 2026: this approved slice is complete in the
working tree. The visual plan now carries active reviews and accepted history;
the workspace auto-saves and reloads private files; imported overlays support
direct drag/resize; planning lanes distinguish B-roll and AI footage; and the
Generated panel separates five renderable modules from 33 unbuilt treatment
recipes.

Clarification approved July 14, 2026: recipe cards no longer jump directly to
Review. They show hover previews and use an explicit **Build with Codex** action
that creates and copies the scoped build request. Render Range and Render Final
save the current plan synchronously before starting. The Inspector labels
renderable cues versus planning-only suggestions, and image/video import is a
labeled primary action.

Addendum approved July 16, 2026: the version-one frozen-master workaround and
static React preview are superseded. Visual Production uses one schema-v2
canonical revision model: registered HyperFrames source, composition scene
cues, explicit spoken/fully-visible timing for semantic items, review and final
artifact paths and hashes, and a numbered active revision. The embedded
HyperFrames player previews the same entry used for rendering. Full builds and
delivery are blocked by representative approval, anchored voice timing,
composition-root overflow checks, full-review approval, strict HyperFrames
inspection at voice-anchored fully-visible states, and delivered-revision reopen
verification. Existing review notes
remain in `visual-plan.json`; custom authoring folders are not parallel review
or delivery state.

Addendum approved July 20, 2026: the blocking `Render full review -> Approve
full review -> Deliver final` sequence is superseded. The registered live
HyperFrames player is the full review surface, and **Export final** is the only
delivery action after active notes are resolved. It saves first, prevents and
reconnects to duplicate jobs, persists real progress, runs the automated gates,
renders once, stream-copies and verifies the locked-cut audio, validates
the encoded media, and atomically publishes the final (with a timestamped
fallback when the existing target is open). Legacy gate fields remain for
project compatibility but no longer block final export.

Addendum approved July 20, 2026: review playback and visual planning are
reuse-first. The preview supports fullscreen and automatically selects the cue
under the playing playhead. **Next review** is docked beside the note controls
and plays only the next note's exact range. Cook Visual Plan must inspect the
registered modules, proven recipe catalog, prior recipe previews, and private
Creator Library before proposing bespoke work, and must persist explicit reuse
and B-roll audits. B-roll may be marked not suitable, but it may not be silently
omitted from planning.

Addendum approved July 22, 2026: Visual Production planning is generalized for
all future videos and uses approval contract three. Every proposed scene passes
through four explicit responsibilities: Scene Analyst, Scene Selector, Producer,
and Variation Agent. The analyst records one of eight supported source layouts,
actual speaker and protected-content geometry, a video screenshot time,
transcript beats, editorial purpose, density, motion opportunities, B-roll fit,
and surrounding constraints. The selector hard-filters the complete library by
layout and protected regions, then ranks intent, locked canonical defaults,
creator rating, proven usage, motion/content fit, and whole-video variation.
The producer either selects a ranked reusable treatment or records the genuine
library gap. The Variation Agent maintains family/treatment counts and
intentional-series exceptions.

Before production rendering, the creator compares the actual scene frame and
the library treatment screenshot, then approves, rejects with notes, requests
another option, or approves an intentional series as a group. Rejections remain
in suggestion history and route into the existing review-note handoff. The
accepted treatment map is an implementation contract, and final rendering is
blocked until each planned scene is approved and each built cue retains its
scene and treatment identity.

The private treatment library stores creator ratings independently from
explicit default locks. Rating 1-5 controls preference; **Lock as default**
creates a canonical first choice for its compatible intent and scope. The
numbered example/title treatment is the initial five-star locked default for
“Example number ___” and is intentionally reusable as a series. After each
video, the Rate view presents each unique used treatment once so the library is
recursively strengthened.

Audio terminology is evidence-based. Locked-cut audio is never described as
normalized or mastered without recorded proof. Stage 5 records whether
normalization was applied, the preset and target when present, and the available
loudness measurement. Final Visual Production delivery writes a private
manifest with this evidence plus verified source/delivery packet hashes, codec,
sample rate, channels, resolution, frame rate, and duration.

Addendum approved July 24, 2026: the
[Canonical Cook and Approval Contract](visual-production-workflow.md#canonical-cook-and-approval-contract---july-24-2026)
is the single authority for Visual Production planning. It extends Approval
Contract Three without creating another schema family, planning file, review
surface, or render path.

The approved cadence is one meaningful visual change within five seconds of the
previous meaningful change, except for an explicitly documented and approved
clean-performance hold. This is a maximum unchanged duration, not a graphic
duration, scene duration, five-second slicing rule, or graphics-per-minute
quota. Long treatments remain one treatment and satisfy the cadence through
timestamped internal reveals and state changes.

Every proposed graphic must show its actual scene source frame beside either a
real approved historical treatment frame or one representative sample frame.
Missing historical evidence triggers the sample-frame task; it does not permit
a generic illustration, silent substitution, omitted proposal, or full
production render. Approval remains blocked until evidence and speaker-safety
checks are present.

Cook Visual Plan is one orchestrated operation. Scene Analyst, Scene Selector,
Producer, and Variation Agent are mandatory sequential responsibilities that
write into the same private suggestion record. They are not parallel planning
paths. Counts must distinguish timeline decisions, graphic treatments,
internal meaningful changes, clean-performance holds, protected footage,
B-roll, and unresolved approvals.

The accepted treatment map remains binding through build and export. The
internal-change ledger and approval-evidence reference also survive into the
built cue. Implementation completed July 24, 2026 through Approval Contract
Three: computed cadence/count audits, one-frame evidence preparation,
evidence/safety approval gates, build-through preservation, fixed Review
labels, and regression tests all use the existing single path.

## Approved Sequence

1. **Cut-plan validation and overlap prevention**
   - Enforce ordered, positive-length kept ranges.
   - Prevent neighboring IN/OUT adjustments from crossing or collapsing a
     range.
   - Validate at adjustment time and again immediately before export.
   - Clamp oversized UI nudges to the nearest legal frame and disable controls
     that cannot move farther without crossing the neighboring boundary.
   - Preserve behavior for every currently valid saved project.
   - Persist an optional final source OUT frame, adjustable from the Stage 3
     source playhead, exact frame entry, or frame nudges. Apply it to both the
     complete rendered preview and final export without re-including deleted
     trailing transcript words.
   - Audition that endpoint with the established 2s/4s/6s source-preview
     durations, stopping playback on the inclusive final OUT boundary.
2. **Threshold-aware dead-space removal**
   - Treat Whisper gaps as candidate timing data, not verified silence.
   - Analyze only candidates meeting the configured threshold when the user
     clicks the primary **Analyze Pauses** action.
   - Store Whisper and measured acoustic boundaries separately.
   - Show only measured long-pause chips meeting the configured threshold.
   - Restore previously deleted candidates when measurement rejects them.
   - Make the displayed chips, affected count, and bulk removal use the same
     measured duration.
   - Disable bulk removal while threshold-qualified raw candidates remain
     unanalyzed.
   - Consider retained-pause trimming as a follow-up after threshold behavior is
     tested against production footage.
3. **Audio Boundary Assist**
   - Keep Whisper word start/end timestamps as the immutable baseline for every
     assisted cut anchor.
   - Use Whisper's word boundary as the baseline, then inspect a short audio
     window around that boundary for the actual completion of the spoken word.
   - Preserve the Whisper-suggested frame separately from any assisted frame and
     the user's manual adjustment.
   - Run only when the user clicks the primary **Fine Tune** action, after
     transcript edits have created splices.
   - Analyze only splice OUT points that are still marked unreviewed.
   - Report cuts checked, adjusted, and unchanged; do not report transcript
     word counts.
   - Validate and tune the conservative energy/silence detector against
     representative production clips before changing its limits.
   - Do not use fixed padding or word character count as a proxy for speech
     timing.
4. **Normalization during cut export**
   - Retain the standalone Audio Normalizer.
   - Add an optional **Normalize audio** choice to Stage 5; it defaults off so
     the existing cut-only export remains unchanged.
   - When enabled, expose the existing normalization presets and default to the
     established Gentle Voice Leveling preset.
   - Compose the proven pipelines sequentially: export the cut first, analyze
     that cut, then normalize its audio.
   - Keep the successful cut as a separate file and write normalization to a
     sibling `_normalized.mp4` file. Never overwrite the source or the cut.
   - If normalization fails, report that the cut succeeded and preserve its
     exact path so the user can recover or use it.
5. **Rendered cut preview**
   - Render the complete current cut as a fast draft after Stage 3 review and
     manual adjustment.
   - Present that complete draft in the approved dedicated Stage 4 workspace
     with a large player, compact splice navigation, and a full-duration
     timeline containing every splice marker.
   - Show the complete kept transcript section on both sides of each splice in
     the sidebar rather than the two-word context used by the compact Stage 3
     review panel.
   - Seek the rendered draft when a transcript/splice entry or timeline marker
     is selected.
   - Embed OUT/IN adjustment, replay, review, and previous/next controls directly
     in the rendered-preview workspace.
   - Keep the existing draft playable after adjustments and provide **Rerender
     Entire Preview** to rerender the complete cut at any time.
   - The July 16 requirement to gate manual OUT/IN capture until a full refresh
     is superseded. Preserve the working preview's source mapping so accepted
     cuts can remain pending while the user continues marking and short-previewing
     additional manual cuts without a full render.
   - After refreshing, return playback to the relevant join.
   - Write only to the ignored temporary directory and retain only the active
     rendered draft.
   - Allow a manual source-frame cut to be marked directly from the rendered
     draft playhead without creating or changing transcript selections.
   - Persist manual OUT/IN boundaries as edit decisions, expose the same frame
     nudge/review/removal workflow as transcript splices, and apply them to both
     refreshed previews and the final export.
   - Accept manual OUT/IN positions either from the rendered-draft playhead or
     as typed preview timecodes, with frame-accurate source mapping.
   - Show a newly created manual cut immediately on the shared splice timeline;
     distinguish its pending marker until the rendered draft is refreshed, and
     make that exact new manual cut active in the lower OUT/IN fine-tuning panel.
   - Support CapCut-style timeline inspection: `Ctrl` + mouse wheel zooms around
     the pointer from the full-duration view down to practical frame spacing,
     while an always-available horizontal scrollbar pans the expanded timeline.
   - Start with a narrow, reversible playhead interaction: show one draggable
     line synchronized to the rendered draft and scrub it at frame resolution.
     Releasing the line holds the preview on that frame so the explicit **Set
     OUT** or **Set IN** action can capture it. The playhead remains navigation
     only and does not create or modify an edit decision.
   - During manual-cut drafting, show temporary labeled OUT/IN guides and shade
     the proposed removed interval on the shared timeline. Require a valid OUT
     before IN can be typed or captured, and clear IN whenever OUT changes.
   - Once both draft boundaries are valid, make the unpersisted draft active in
     the lower fine-tuning panel. Reuse the frame-nudge cards there and feed each
     adjustment back into the draft markers, typed values, and 2s/4s/6s preview.
     Persist nothing until **Accept Manual Cut** is explicitly clicked.
   - Reuse the established 2s/4s/6s splice-preview durations before persistence:
     play the rendered draft into OUT, jump to IN, and continue for the selected
     duration. Draft preview does not create the cut; **Add Manual Cut** remains
     explicit.
6. **Repeated-phrase transcription investigation — superseded July 14, 2026**
   - The earlier decision deferred changes until representative production
     failures were available.
   - Three confirmed failures from the July 14 production recording showed that
     the Base model collapsed nearby restatements into long word spans.
   - The approved replacement defaults are Large v3 and NVIDIA GPU.
   - The first implementation highlighted both copies of any nearby two-word
     match. Production review showed that this was too broad and is superseded.
   - The approved refinement highlights only the likely earlier take: a long
     repeated phrase, a tightly adjacent short restart, or an immediately
     repeated pronoun. Normal short wording reused across sentences is excluded.
   - Highlighting is review assistance only. It does not delete content or infer
     speech that Whisper omitted from the transcript.

7. **Transcript learning history — approved July 15, 2026**
   - Keep Large v3 and NVIDIA GPU as the production defaults.
   - Freeze the first generated transcript before edits and the final reviewed
     editor project before final transcript remapping.
   - Record model/runtime/source provenance and a machine-readable report of IN,
     OUT, deletion, and repetition-review outcomes for every exported project.
   - Preserve Whisper, assisted, and manual IN frames separately.
   - Production calibration rejected raw waveform onset and VAD-padding changes
     as IN-point fixes because they produced false moves on approved cuts.
   - Phoneme forced alignment was approved and calibrated against the July 15
     reviewed project. WhisperX's English model did not improve the moved-cut
     average, while the multilingual MMS model improved moved cuts but damaged
     accepted cuts and had no reliable safety gate. Automatic replacement is
     therefore rejected for production; the diagnostic remains available for
     future comparisons against accumulated project history.

## Approved Rendered-Preview Direction

![Approved rendered cut preview](assets/rendered-cut-preview-approved.png)

The approved screen keeps transcript context visible while making the rendered
video the main review surface. Each cut point displays:

- source timecode in `HH:MM:SS:FF` form;
- absolute source frame;
- the original suggested frame; and
- the manual adjustment delta.

Splice controls remain embedded below the rendered video. Users should not need
to navigate back to another screen to nudge a cut.

## Approved Header Direction

![Approved single-row staged header](assets/single-row-stage-header-approved.png)

The production header remains a single row. A conventional **Tools** hover menu
contains Transcript Edit, Caption Generator, Audio Normalizer, and the separate
Visual Production workflow. Project open,
save, and settings remain compact secondary utilities outside the editing
workflow.

Transcript editing is represented as five connected numbered chevrons. Only the
selected stage expands horizontally:

1. Open Video and Generate Transcript
2. Analyze Pauses and Remove Long Pauses
3. Fine Tune
4. Rendered Preview
5. Export

Collapsed stages show only their number. The expanded stage uses outlined teal
and magenta accents rather than large solid action blocks. All five stages now
have an initial implementation; production-media validation remains required.

## Production Safety Rules

- Never overwrite source media.
- Keep existing export behavior available until a replacement is verified.
- Apply project-format changes through versioned, backward-compatible loading.
- New output-changing settings default to current behavior for existing files.
- Validate the complete cut plan before invoking FFmpeg.
- Write rendered previews only beneath the ignored temporary directory.
- Keep each milestone independently testable and revertible.
- Run the full Python suite, TypeScript typecheck, and production build before
  considering a milestone complete.
- Test representative landscape and portrait footage before changing defaults.

## Current Milestone

Milestone 4 now has an initial implementation and automated validation. Stage 5
provides an optional normalization control while preserving cut-only export as
the default. The integrated path reuses the standalone normalizer's existing
two-pass loudness analysis and normalization implementation against the
completed cut. Its final result is `<source>_cut_normalized.mp4`; the
intermediate `<source>_cut.mp4` remains available even when normalization
succeeds. A normalization failure reports the successful cut path rather than
discarding the usable export.

The initial selected-splice-only preview was rejected because it did not satisfy
the approved full-video review workflow shown in the mockup, and it has been
replaced rather than retained as a competing workflow. Stage 4 now renders the
complete cut and exposes every splice through its sidebar and full-duration
timeline. Embedded adjustments mark the draft stale, and the refresh action
rerenders the complete cut using the current plan. Production-footage runtime
and visual validation remain outstanding.

Milestones 1–3 have an initial implementation and automated validation:

- invalid and overlapping plans are rejected and adjustment changes roll back;
- bulk pause removal defaults to `0.8s`, reports the affected count, and keeps
  only threshold-qualified measured pause tokens visible;
- Analyze Pauses measures only threshold-qualified Whisper candidates and
  rejects false long pauses before transcript editing;
- audio boundary suggestions preserve Whisper timestamps while extending OUT
  points only when local audio evidence supports it; and
- project files now write version 2 while version-1 files load with safe
  defaults.

Audio Boundary Assist now runs only from the primary **Fine Tune** toolbar
action after transcript edits create splices. It extracts the source audio once,
examines only outgoing words for unreviewed splices, and checks up to `0.35s`
after each Whisper word end. It extends only when local energy shows continuing
speech and stops at sustained silence or the next word. The splice adjustment
stores the original Whisper frame, assisted suggestion, and manual nudge as
separate values. Representative production footage is still required to
validate and tune the conservative detector.

### Superseded proposal

An initial fixed word-tail-padding implementation was added on July 10, 2026
without approval. It was removed the same day because it changed every eligible
OUT point rather than intelligently locating spoken-word completion. Fixed
padding and character-count timing are not part of the approved plan.
