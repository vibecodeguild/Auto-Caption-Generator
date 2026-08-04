# Current System

Last verified against the working tree: July 11, 2026.

This document is the implementation-oriented source of truth for what exists in
VCG AutoCaption today. It describes the current working tree, including
uncommitted local changes; consult `git status` before treating every detail as
part of the last committed baseline.

## Product Shape

VCG AutoCaption is a Windows-first, local-only application. The main interface
is a Next.js single-page application. A FastAPI server performs all privileged
local operations: file dialogs, reading project/media files, transcription,
FFmpeg work, persistence, and media streaming.

```text
Browser at 127.0.0.1:3000
        |
        | JSON requests and HTTP range media
        v
FastAPI at 127.0.0.1:8731
        |
        +-- project/transcript/edit state
        +-- faster-whisper transcription
        +-- FFmpeg/ffprobe processing
        +-- Windows file and folder dialogs
        +-- local project/style/export/temp files
```

The API holds one active private parent video project, its transcript/edit
state, and the selected stage sources in process memory. Restarting it clears
in-memory selections and jobs, but reopening `project.vcg-project.json`
restores the project-owned inputs and destinations. Legacy `.vcg.json` projects
and custom styles remain supported.

## Main Components

| Location | Responsibility |
| --- | --- |
| `web/app/page.tsx` | Primary workspace shell, transcript/caption/audio interaction state, source playback, splice preview sequencing, caption overlay preview, and progress modals |
| `web/app/visual-production.tsx` | Separate private visual-finishing workspace, library, preview, inspector, render controls, and layered timeline |
| `web/lib/api.ts` | Typed client contracts and API calls |
| `app/web_api.py` | FastAPI routes, active process state, validation, file selection, job management, and media responses |
| `app/core/editor_pipeline.py` | Video probing, audio extraction, Whisper transcription, and transcript-project construction |
| `app/core/edit_decisions.py` | Word/silence deletion and restoration state |
| `app/core/splice_generation.py` | Derives current splice joins and preserves frame adjustments by source anchors |
| `app/core/splice_preview.py` | Calculates before/after source playback segments |
| `app/core/video_cutter.py` | Converts adjusted frame ranges into a re-encoded FFmpeg cut export |
| `app/core/pipeline.py` | Caption transcription, grouping, ASS creation, and subtitle burn-in |
| `app/core/ass_builder.py` | Active-word ASS events and visual style construction |
| `app/core/audio_normalizer.py` | Loudness measurement, speech-region recommendations, preview pairs, and two-pass normalization |
| `app/core/project_store.py` | `.vcg.json` serialization for projects, edits, splice adjustments, and review state |
| `app/core/video_project.py` | Private parent-project creation, portable stage paths, source resolution, and Codex visual-plan prompt generation |
| `app/core/story_assets.py` | Private Creator Library, checksums, frozen project copies, suggestion review state, Pexels search/download, stock evidence, and credits |
| `app/core/style_library.py` | Built-in and user-created caption style persistence |
| `app/core/visual_production.py` | Schema-v2 visual-plan validation, custom-composition registration, canonical revision hashes, production gates, asset import, deterministic HyperFrames authoring, and local rendering |
| `app/core/windows_dialog.py` | Windows-native open/save/folder dialogs used by the local API |
| `scripts/dev_web.py` | Starts or reuses the API and Next.js development processes |
| `visual-production/` | Public brand, reusable module catalog, styles, and visual-plan contract used by the Visual Production workflow |
| `scripts/new_visual_project.py` | Creates private visual projects outside the public Git checkout |
| `scripts/check_repo_privacy.py` | Rejects tracked creator material, private paths, and unsafe historical paths before publication |
| `app/main_window.py` | Retained PySide6 caption UI, not the primary product surface |

## Visual Production Workflow

Visual Production is a separate workflow after the cut and audio are locked.
The Tools menu opens a white-first workspace containing the reusable module and
treatment-recipe library, private imported assets, exact HyperFrames preview, editable
inspector, docked review notes, protected source-footage ranges, layered
timeline, and selected-range/full render actions. Plan edits save automatically;
Reload Files reads changes written by Codex or HyperFrames back from the same
private project.

The preview can enter browser fullscreen. While it plays, the inspector follows
the enabled cue at the current playhead instead of requiring timeline clicks.
**Next review** lives in the review-note dock; it selects the next active note,
seeks to its exact start, plays only that timestamped section, and stops at the
item boundary.

Private projects are created outside the Git checkout and contain copied source
media, transcript snapshots when available, imported assets, plans, working
files, and renders. Saved schema-v2 plans use project-relative paths and record
registered custom compositions, voice-timed semantic items, numbered revisions,
artifact hashes, and production gates. The API serves the active private media
and the registered HyperFrames source with range support and runs local background
HyperFrames renders. HyperFrames, GSAP, FFmpeg, and FFprobe are pinned project
dependencies, so rendering does not rely on AI tokens or globally installed
media tools.

The registered deterministic modules are shown as reusable VCG building blocks.
A separate proven-treatment catalog contains 33 reusable recipes from
production, prioritizes recipes with real prior-use previews, and uses **Reuse
with Codex** to create a timestamped adaptation request. The Cook Visual Plan
handoff must inspect modules, recipes, prior recipe previews, and the private
Creator Library before authoring bespoke work. Its machine-readable coverage
record also requires an explicit full-video B-roll decision, including a reason
when B-roll is correctly judged unsuitable. See
[Visual Production Workflow](visual-production-workflow.md).

## Parent Video Projects

Phase 1 creates a private parent project when the user chooses one or more raw
recordings. Every recording is copied under `source/`, and the application creates a portable
`project.vcg-project.json` manifest plus standard transcript, audio, asset,
preview, working, visual-production, and export directories. Manifest paths are
project-relative, so moving the entire folder preserves their relationships.

The parent manifest stores an ordered `sourceSequence` with clip ids, original
names, technical metadata, durations, and continuous-timeline start offsets.
The Phase 1 Source Sequence dialog can add, reorder, and remove recordings.
Matching clips use FFmpeg stream-copy concatenation into
`working/source-sequence.mp4`; an actual codec, resolution, frame-rate, pixel,
or audio mismatch triggers standardized private working copies before joining.
The originals are never modified. Transcript context shows a marker at each
source-clip boundary.

Every sequence rebuild increments `sequenceRevision` and invalidates transcript,
locked-cut, visual, and final artifact revisions. Stale files may remain on disk
for recovery, but the application will not select them as current inputs.

The working transcript saves automatically to `transcripts/editor.vcg.json`.
The first generated transcript for a source-sequence revision is also frozen as
`transcripts/original-generated.vcg.json`, including model, compute, engine,
source checksum, generation time, sequence revision, and initial repetition
suggestions. Phase 5 freezes the reviewed editor state as
`transcripts/editor-final-reviewed.vcg.json`, writes the remapped
`transcripts/final-transcript.json`, and records comparison-ready boundary and
repetition statistics in `transcripts/edit-analysis.json`.

Phase 5 defaults to `exports/locked-cut.mp4`. Caption and Audio inherit the active
project source and export directory without asking for another path. Visual
Production initializes from the locked cut and transcript, saves its plan under
`visual-production/`, uses its registered HyperFrames composition as the live
review surface, and writes the delivered revision to
`exports/final-video.mp4`. The same registered HyperFrames entry is used by the
in-app player and renderer.

The Project menu generates a copyable **Cook Visual Plan Prompt** containing the
exact private project paths, public VCG contracts, editorial timing rules,
privacy boundary, and a suggestions-only approval gate. Legacy standalone
transcript and visual projects retain manual selectors because they do not have
a parent manifest.

## Visual Storytelling Assets

Visual Production includes Generated, Creator, Project, and Review library tabs.
The private cross-project Creator Library imports AI footage and images from
local files, deduplicates them by SHA-256, stores searchable callback metadata,
and records usage history. Adding a library asset freezes a content-addressed
copy into the current project before creating its editable timeline cue.

The Review tab loads the private `visual-suggestions.json` written by the Cook
Visual Plan handoff. It reviews clean-speaker, protected-footage, graphic,
Creator Library, project-asset, stock, and AI-brief treatments together.
Graphics and source holds build directly into editable cues; Creator Library
selections are frozen and placed; AI briefs can be copied for an external
generator.

Graphics, B-roll, AI-footage briefs, imported media, and protected ranges have
distinct timeline lanes and colors. Selecting a cue or suggestion exposes a
review-note dock with targeted, leave-everything-else, or replace-all scope.
Non-empty notes become **Changes requested**; Codex can mark them **Ready for
review**; Accept archives them into durable plan history. **Copy All Notes**
copies only active non-empty notes with exact paths, IDs, and timestamps.
Numeric Inspector controls remain available for imported image and video cues.
The previous React overlay imitation and direct-manipulation preview are
superseded because they could diverge from the render runtime.

The Inspector labels module, imported-media, and custom-composition cues
separately from planning-only suggestions. **Export final** synchronously saves
the latest plan, prevents duplicate jobs, and reconnects to persistent progress
after a browser reload. It blocks on active review notes, missing voice anchors,
or composition-root overflow, then runs strict HyperFrames checks, renders once,
stream-copies the locked-cut audio, and validates the encoded delivery
before publishing it. Layout inspection samples each voice-timed semantic item
when it is fully visible, rather than treating hidden outgoing DOM at a hard cut
as readable content. If Windows has the current final open, the verified export
uses a timestamped filename instead of discarding the completed render. A
labeled **Import image/video** action copies supported media into the private
project and places it at the playhead.

### July 24 Visual Production contract

The Review tab displays the actual scene source frame beside evidence bound to
the selected treatment: either a real historical render or one exact
representative sample. Generic recipe illustrations remain available for
library browsing but are not approval evidence.

Approval Contract Three now persists timed internal meaningful changes,
intentional holds, fixed decision counts, full-runtime five-second cadence
validation, and typed approval evidence. Approval requires matching evidence
and speaker safety. The accepted cadence/evidence records are copied into built
cues and checked again by production gates. Registered modules can prepare
their one-frame sample in the app; unbuilt recipes must produce their exact
implementation sample during the same Cook operation and are never replaced by
a generic fallback.

Pexels is the only stock provider. Its key is read from `PEXELS_API_KEY` or
private local settings. When configured, stock suggestions prepare three to
five candidates ahead of review from up to three literal/metaphorical queries.
Only the selected full-resolution video downloads. The project records creator,
asset page, download time, license page/evidence, checksum, attribution, and
timeline placement, and can copy paste-ready credits. See
[Visual Storytelling Assets](visual-storytelling-assets.md).

## Transcript Edit Workflow

The application uses a single-row command header. A Tools hover/focus menu
switches between Transcript Edit, Caption Generator, Audio Normalizer, and the
separate Visual Production workflow.
Project open/save and settings are compact utilities. Transcript actions use a
five-stage numbered chevron rail; only the selected stage expands to show its
controls. Stage 4 renders and reviews the complete edited draft with splice
navigation and embedded adjustments; Stage 5 exports the final cut with
optional normalization.

### Creating or opening a project

The user can create a private parent project from one or more ordered source
clips, then start a background transcription job against the assembled
`working/source-sequence.mp4`. The application can also open an existing parent
manifest or a legacy standalone `.vcg.json` transcript project. Transcription
uses the sequence's declared camera frame rate, extracts audio, runs
`faster-whisper` with word timestamps, and builds words, sentence IDs, frame
indices, and silence ranges. Clip-boundary markers preserve the relationship to
the original recordings. Transcript project version 5 persists manual cuts and
the optional final OUT frame while versions 1 through 4 continue to load with
safe defaults.

Background job state contains `running`, `complete`, or `failed`, plus a numeric
or indeterminate progress value, message, result, and error. Jobs exist only in
the API process and are not resumable after restart.

### Editing and splice review

Words and silence are presented as one ordered token stream. Delete decisions
remain non-destructive and deleted content stays available for restoration.
The API also detects likely rerecorded takes within a 12-second review window.
It highlights only the earlier take when a long phrase is restated, while a
separate narrow rule catches tightly adjacent short restarts and immediately
repeated pronouns. Normal short phrases reused across sentences are excluded.
Deleted words are excluded so resolved repetitions disappear from the review
signal.
Current kept ranges generate the splice queue dynamically. A splice records:

- stable left/right source anchors;
- suggested and adjusted OUT/IN frames;
- separate left and right frame adjustments;
- surrounding transcript context;
- reviewed status; and
- 2-, 4-, and 6-second source preview segments.

The browser previews a splice by playing the outgoing source segment, seeking
to the incoming segment, and continuing playback. It does not render a preview
MP4. The compact splice controls show exact timecode, absolute frame, the
Whisper-suggested frame, and the user's manual adjustment without duplicating
the source preview as separate frame images.

The cut plan is validated after every frame adjustment and again before export.
Collapsed, reversed, negative, or overlapping kept ranges are rejected, and a
rejected adjustment is rolled back rather than saved. Whisper word timestamps
remain the immutable baseline. The primary **Fine Tune** action extracts a mono
WAV and examines only OUT points for current unreviewed splices. It can extend a
suggestion to the first sustained local silence, up to `0.35s` and never beyond
the next word. The Whisper frame, splice-level assisted suggestion, and manual
adjustment remain separate. For a deleted validated pause, Fine Tune reuses its
measured outgoing acoustic boundary. Reviewed splices are not analyzed or
changed.

The splice nudge controls clamp oversized moves to the nearest legal frame. An
OUT point can move no farther than `IN - 1`, and an IN point can move no earlier
than `OUT + 1`. Buttons disable at those limits while the backend retains its
independent overlap/collapse validation.

Stage 3 also exposes the final source OUT frame independently of splice joins.
The user can enter an exact frame, capture the current source-preview playhead,
or nudge by 1, 5, or 10 frames. Dedicated 2-, 4-, and 6-second previews play the
last retained source section into that inclusive OUT frame and stop there. The
optional boundary is stored in the editor project and changes the last interval
used by both Stage 4 rendering and final export. Reset restores the last kept
word's transcript end. The control cannot extend into transcript words
deliberately deleted from the end.

Stage 4 renders the complete current cut as a fast review draft using the same
interval conversion and cutter as final export. Its dedicated workspace has a
large rendered-video player, compact splice list, full-duration splice-marker
timeline, and embedded replay, review, navigation, and OUT/IN nudge controls.
Each sidebar entry shows every word in the complete kept transcript section on
both sides of its join; the two-word Stage 3 context remains unchanged.
Selecting an entry or timeline marker seeks to two seconds before that join.
Boundary changes leave the existing draft playable as a working preview and
mark accepted changes as pending. The rendered draft retains its own source
mapping, so the user can continue capturing manual OUT/IN points and using the
short join preview without rerendering after every accepted cut. **Rerender
Entire Preview** is an optional full-cut render available at any time and
returns to the relevant join. Only one rendered-cut draft is retained beneath
the ignored temporary directory.

Stage 4 also supports transcript-independent manual removals. The user pauses
the rendered draft on the last frame to keep, marks OUT, moves to the first
frame to keep after the unwanted section, and adds the cut at IN. Preview-time
segments map those playhead positions back to source frames. Manual cuts persist
in the editor project, appear in the splice queue, support frame nudges, review,
and removal, and participate in the same validated preview/export plan.
OUT and IN may be captured from the playhead or typed as preview times (`SS`,
`MM:SS`, `HH:MM:SS`, or `HH:MM:SS:FF`). A new manual cut is drawn immediately
on the shared splice timeline as a draft. Once both points are valid, that draft
owns the lower OUT/IN frame-nudge controls and remains compatible with the
2s/4s/6s join previews. **Accept Manual Cut** is the only persistence step; the
accepted cut then remains active with a distinct accepted-but-not-rendered
marker until **Rerender Entire Preview**.
The shared timeline opens at 1x with the complete draft visible. Holding `Ctrl`
while using the mouse wheel zooms around the pointer, up to approximately ten
pixels per frame (capped for unusually long sources). Zoom buttons provide the
same action and reset to 1x. The timeline viewport owns a persistent horizontal
scrollbar for panning whenever the scaled timeline extends beyond the panel.
A white playhead line follows rendered-draft playback smoothly. Dragging its
handle pauses and scrubs the preview at project-frame resolution; releasing it
holds the preview on that frame. **Set OUT** and **Set IN** explicitly copy the
held playhead time into the manual-cut fields. Arrow keys nudge a focused
playhead by one frame. This interaction is navigation-only: OUT/IN capture and
manual-cut creation remain explicit separate actions.
Setting OUT draws a temporary teal guide; setting a valid later IN adds a
magenta guide and shades the proposed removed interval. IN is disabled until
OUT is valid, and any OUT change clears the old IN. The draft can be auditioned
with the same 2s/4s/6s convention as transcript splices: the rendered video
plays the first half into OUT, jumps to IN, then plays the second half. These
guides and previews remain temporary until **Add Manual Cut** succeeds.

Whisper still records candidate gaps from `0.35s`, but those raw gaps are not
all shown as dead space. The primary **Analyze Pauses** action measures only raw
candidates meeting the project threshold (default `0.8s`) against the source
audio. It stores measured boundaries alongside the Whisper gap, hides measured
pauses below the threshold, and restores any rejected candidate that had been
deleted. Displayed chips, the toolbar count, and bulk removal all use the same
frame-based measured duration. Raw candidates are labeled separately, and bulk
removal remains disabled until all current threshold-qualified candidates have
been analyzed.

### Save and export

Saving writes a `.vcg.json` document. For newly transcribed projects, the first
save opens a Windows save dialog. Loaded projects save back to their existing
path. Edit actions also save automatically when the active project already has
a path.

Cut export uses adjusted kept frame ranges and re-encodes audio and video for
precise joins. It does not currently feed a remapped transcript directly into a
caption render or write an integrated cut-plus-caption deliverable.

## Caption Generator Workflow

Caption options expose grouping presets, Whisper model labels, CPU/NVIDIA
compute modes, three built-in styles, custom styles, selected source, and output
folder. Fresh sessions default to Large v3 on NVIDIA GPU while retaining the
other model and compute choices.

Preparing live preview obtains word timestamps in this order:

1. reuse the active transcript project when its source matches;
2. reuse the in-process preview cache for the same source/model/compute tuple;
3. otherwise extract audio and transcribe the selected video.

The browser groups those words and draws an active-word overlay over the actual
video element. Style controls cover font, main/active sizes and colors, bold,
outline, shadow, glow, top/middle/bottom position, vertical offset, and grouping
limits. User styles persist under the local application-data directory.

Generation independently runs the caption pipeline: validate source, derive
video dimensions, extract audio, transcribe, group words, write ASS, and burn
subtitles into `<source>_captioned.mp4`. The render uses H.264/AAC-compatible
output settings. Caption wrapping, safe horizontal margins, preview scaling,
bundled Montserrat handling, and Windows-compatible H.264 output are present in
the current working tree and still require representative-media validation.

## Audio Normalizer Workflow

The audio workspace supports:

- Normalize Only;
- Gentle Voice Leveling; and
- Strong Voice Leveling.

Analysis uses FFmpeg loudness filters and validates integrated loudness, true
peak, and loudness-range targets. Voice-leveling presets apply additional audio
processing before measurement. A loudness timeline plus faster-whisper voice
activity detection identifies likely loudest and quietest speech regions.

Preview generation creates temporary Original and Corrected clips of the same
5-30 second source range (the UI uses 20 seconds). Only one preview pair is kept
active; choosing a new source or preview replaces the old pair. Export performs
the measured second pass and writes `<source>_normalized.mp4` while preserving
the source video stream when possible.

Transcript Edit Stage 5 can also apply the same proven two-pass process to a
completed cut. Normalization is opt-in and defaults to Gentle Voice Leveling.
The cut is always written first as `<source>_cut.mp4`; enabled normalization
writes `<source>_cut_normalized.mp4` without overwriting either the source or
the successful cut. The standalone Audio Normalizer remains available.

## Creator Video Production Platform

New creator-video projects use the `creator-video-production` authority rather
than ambient HyperFrames workflow routing. The platform freezes the locked cut,
encoded audio packet stream, final transcript word timings, workflow resources,
channel profile, complete native HyperFrames source catalog, runtime, and
licenses into the private project before planning.

The current implementation state, global-skill cleanup boundary, preserved
renderer inventory, private WP8 fixture status, and fresh-task continuation
prompt are recorded in
[Creator Production Implementation Checkpoint](creator-production-checkpoint.md).

The executable episode manifest is the single creative authority. Production
creates an immutable, schema-bound file handoff for a normal user-visible Codex
task. The application does not start or monitor a nested Codex process. A task
claim records its visible startup skill inventory and rejects forbidden
end-to-end video workflows. The application independently verifies the handoff,
locked identities, output schema, capability bindings, and downstream gates
before promotion. No `OPENAI_API_KEY` is used. Source-only native recipes remain
visible as explicit adaptation debt and must pass restricted, deterministic
fixture execution before they become selectable.

Analysis groups transcript propositions into contiguous semantic units and
records exact observed visual changes and continuous performance/demonstration
carry spans. Planning receives sequence boundaries only at eligible
semantic-unit starts. A sequence is one coherent visual treatment or source
strategy, not a sentence or cadence slice. Whole-plan structure, evidence, and
cadence validate before any decision is frozen; failed submissions retain
nothing, while the three-submission correction limit remains in force.

Materialized sequences are mounted only for their exact half-open frame ranges.
Element IDs are sequence-namespaced, spoken reveals use immutable word frames,
speaker/source framing comes from manifest geometry, and entry/change/hold/exit
samples are checked against creator-confirmed subject and protected-content
regions. Authored scenes expose multiple ranked options, unrelated completed
visual signatures cannot be stamped repeatedly, and missing assets, rights,
capabilities, transitions, or timing remain blocking instead of falling back.

Review uses one moving final-quality composition with locked audio. Notes bind
to build, sequence, optional element, and absolute frame; they autosave and
remain active until a revised build is reviewed. The synchronized Studio
handoff opens the exact chapter workspace and only allowlisted edits can return
through a hashed `sourceOverrideRef`.

Completed editorial chapters—not arbitrary duration buckets—render
independently and persist in a content-addressed cache. Source extraction is
cached separately from graphics revisions. Unchanged verified chapters are
reused, video assembly is stream-copy only, decoded frames are compared on both
sides of every seam, and the original encoded audio packet stream is attached
once and verified. The approved review bytes become the delivery bytes.

Renderer authority is also local and immutable. The ignored
`app/private-renderer-assets/` store preserves the complete HyperFrames
0.7.54 package (including Engine, Producer, Studio, runtime, and templates),
GSAP 3.13.0, Chrome Headless Shell 152.0.7928.2, FFmpeg, and FFprobe. Its
manifest records file and whole-tree hashes. Production validates those hashes,
executes the preserved CLI, copies the preserved GSAP runtime into chapter
compositions, and injects explicit browser and media-tool paths into both
browser preflight and rendering. Missing or changed assets block rendering;
Production does not fall back to a global HyperFrames skill or user browser
cache.

Channel identity is data. Packaged fixtures and private profiles are discovered
dynamically by exact `id@version`; workflow and renderer code do not branch on
channel IDs. Private profiles and matching grammars may be placed under
`creator-production-inputs/profiles/` and
`creator-production-inputs/reference-grammars/` in the private video project.

The prior Visual Production implementation is read-only recovery only. Its
persisted projects, status, final-output discovery, and independent safety
checks remain available, but `POST /api/visual/render` returns HTTP 410 and
cannot execute the retired `talking-head-recut` request. It is not an authority
inside a new Creator Production project.

## API Inventory

Generated from `app/web_api.py` by `scripts/generate_api_inventory.py`. 146 routes.
Edit the route or its docstring, then regenerate; do not edit this section by hand.

### Visual Production

| Method | Route | Purpose |
| --- | --- | --- |
| PUT | `/api/visual-package/assignment/override` | Human swap of usage on one beat → assignment-reviewed.json + ledger |
| POST | `/api/visual-package/assignment/run` | Stage 2: deal golden usages onto working Masterbeater beats |
| PUT | `/api/visual-package/masterbeater/beats` | Auto-save Stage 1 word edits to masterbeater-beats-reviewed.json + ledger |
| POST | `/api/visual-package/masterbeater/run` | Run Masterbeater skill against the locked final transcript |
| PUT | `/api/visual-package/placement/beat` | Save lines/timing/lock for one placement beat. Original file untouched |
| POST | `/api/visual-package/placement/import-image-dialog` | Pick an image file and copy it into the project's placement image store |
| POST | `/api/visual-package/placement/preview` | Build live Tier B HyperFrames composition for one placement beat (no encode) |
| GET | `/api/visual-package/placement/preview/composition/{relative_path:path}` | Serve the active single-beat HyperFrames composition for placement live preview |
| POST | `/api/visual-package/placement/run` | Stage 3: draft placements for assigned beats (skips locked on re-run) |
| PUT | `/api/visual-package/scenelayer/override` | Human layout dropdown → scenelayer-reviewed.json + ledger |
| POST | `/api/visual-package/scenelayer/run` | Stage 2: label each beat with an OBS layout from its first frame |
| GET | `/api/visual-package/source-video` | Locked cut (preferred) or working source for Visual Package review |
| GET | `/api/visual-package/status` | Status + Masterbeater + Assignment for the open private video project |
| POST | `/api/visual/assets/import-dialog` | Import visual asset dialog |
| GET | `/api/visual/assets/{asset_id}` | Visual asset |
| GET | `/api/visual/catalog` | Visual catalog |
| GET | `/api/visual/catalog/recipes/{recipe_id}/preview` | Visual recipe preview |
| PATCH | `/api/visual/catalog/treatments/{treatment_id}` | Patch visual treatment |
| GET | `/api/visual/catalog/treatments/{treatment_id}/motion-preview` | Visual treatment motion preview |
| GET | `/api/visual/catalog/treatments/{treatment_id}/preview` | Visual treatment preview |
| POST | `/api/visual/create-dialog` | Create visual project dialog |
| GET | `/api/visual/credits` | Visual credits |
| GET | `/api/visual/current` | Current visual project |
| POST | `/api/visual/ensure` | Ensure visual project |
| GET | `/api/visual/final` | Visual final video |
| POST | `/api/visual/gates/full-review` | Approve visual full review |
| POST | `/api/visual/gates/reopen` | Verify visual delivery reopened |
| POST | `/api/visual/gates/representative` | Approve visual representative |
| POST | `/api/visual/open-dialog` | Open visual project dialog |
| GET | `/api/visual/pexels/settings` | Pexels configuration |
| POST | `/api/visual/pexels/settings` | Save pexels configuration |
| POST | `/api/visual/render` | Reject retired visual render execution |
| GET | `/api/visual/render/active` | Active visual render job |
| GET | `/api/visual/render/jobs/{job_id}` | Visual render job |
| GET | `/api/visual/render/jobs/{job_id}/video` | Visual render video |
| POST | `/api/visual/review-prompt` | Visual review prompt |
| GET | `/api/visual/runtime/composition/{relative_path:path}` | Visual runtime composition file |
| GET | `/api/visual/runtime/core.js` | Visual runtime core |
| GET | `/api/visual/runtime/player.js` | Visual runtime player |
| POST | `/api/visual/save` | Save current visual plan |
| GET | `/api/visual/source` | Visual source video |
| GET | `/api/visual/source-frame` | Visual source frame |
| GET | `/api/visual/suggestions` | Visual suggestions |
| POST | `/api/visual/suggestions/recipe` | Add recipe suggestion |
| PATCH | `/api/visual/suggestions/{suggestion_id}` | Patch visual suggestion |
| POST | `/api/visual/suggestions/{suggestion_id}/approval-evidence/prepare` | Prepare visual suggestion approval evidence |
| GET | `/api/visual/suggestions/{suggestion_id}/approval-frame` | Visual suggestion approval frame |
| POST | `/api/visual/suggestions/{suggestion_id}/build` | Build visual suggestion |
| POST | `/api/visual/suggestions/{suggestion_id}/decision` | Decide visual suggestion |
| POST | `/api/visual/suggestions/{suggestion_id}/pexels/search` | Search suggestion stock |
| POST | `/api/visual/suggestions/{suggestion_id}/pexels/select` | Select suggestion stock |

### Graphics Library

| Method | Route | Purpose |
| --- | --- | --- |
| GET | `/api/graphics-library` | Private Graphics Library summary and usage list |
| POST | `/api/graphics-library/create` | Create the default private Graphics Library folder and empty index |
| POST | `/api/graphics-library/ensure-engine-usages` | Ensure candidate usage rows exist for each known engine (never auto-golden) |
| POST | `/api/graphics-library/import-harvest` | Import ratings/notes from Creator Library harvest into candidates |
| GET | `/api/graphics-library/layout-clips` | List recorded full-frame OBS layout clips available for sample renders |
| POST | `/api/graphics-library/layout-clips/{layout_id}/import` | Import a recorded full-frame OBS layout clip into the private library |
| GET | `/api/graphics-library/metrics` | Usage counts by beat type and allowed layout for Graphics Library charts |
| POST | `/api/graphics-library/open-dialog` | Choose an existing private Graphics Library folder (Windows folder picker) |
| GET | `/api/graphics-library/production-set` | Golden usages from the Graphics Library (production selectable set) |
| GET | `/api/graphics-library/usages/{entry_id}` | Full usage with media availability and engine interface passthrough |
| PATCH | `/api/graphics-library/usages/{entry_id}` | Update status, notes, rating, engineId, beat types, layouts |
| GET | `/api/graphics-library/usages/{entry_id}/media/{kind}` | Stream a private sample or poster from the Graphics Library root |
| POST | `/api/graphics-library/usages/{entry_id}/render-sample` | Render a short sample; stream NDJSON progress events, then a final entry payload |

### Creator Library

| Method | Route | Purpose |
| --- | --- | --- |
| GET | `/api/creator-library` | Creator library |
| POST | `/api/creator-library/import-dialog` | Import creator library asset |
| PATCH | `/api/creator-library/{asset_id}` | Patch creator library asset |
| GET | `/api/creator-library/{asset_id}/media` | Creator library media |
| POST | `/api/creator-library/{asset_id}/use` | Use creator library asset |

### Video projects

| Method | Route | Purpose |
| --- | --- | --- |
| POST | `/api/video-project/clips/add-dialog` | Add video project clips |
| POST | `/api/video-project/clips/reorder` | Reorder video project clips |
| DELETE | `/api/video-project/clips/{clip_id}` | Delete video project clip |
| POST | `/api/video-project/create-dialog` | Create video project dialog |
| GET | `/api/video-project/current` | Current video project |
| POST | `/api/video-project/open-dialog` | Open video project dialog |
| GET | `/api/video-project/visual-prompt` | Video project visual prompt |

### Audio

| Method | Route | Purpose |
| --- | --- | --- |
| POST | `/api/audio/analyze` | Analyze video audio |
| POST | `/api/audio/choose-output-folder` | Choose audio output folder |
| POST | `/api/audio/choose-video` | Choose audio video |
| POST | `/api/audio/normalize` | Normalize audio |
| GET | `/api/audio/options` | Audio options |
| POST | `/api/audio/preview` | Generate audio preview |
| GET | `/api/audio/preview/{preview_id}/{mode}` | Audio preview media |
| GET | `/api/audio/source-video` | Audio source video |

### Transcript projects

| Method | Route | Purpose |
| --- | --- | --- |
| POST | `/api/projects/choose-video` | Choose transcript video |
| GET | `/api/projects/current` | Current project |
| POST | `/api/projects/current/analyze-boundaries` | Analyze current boundaries |
| POST | `/api/projects/current/analyze-pauses` | Analyze current pauses |
| POST | `/api/projects/current/delete` | Delete selection |
| POST | `/api/projects/current/delete-dead-space` | Delete dead space |
| GET | `/api/projects/current/document` | Project document |
| POST | `/api/projects/current/export` | Export cut |
| POST | `/api/projects/current/final-out-frame` | Set final out frame |
| GET | `/api/projects/current/frame` | Frame image |
| POST | `/api/projects/current/manual-cuts` | Add manual cut |
| POST | `/api/projects/current/manual-cuts/adjust` | Adjust manual cut |
| DELETE | `/api/projects/current/manual-cuts/{cut_id}` | Remove manual cut |
| POST | `/api/projects/current/render-preview` | Render cut preview |
| GET | `/api/projects/current/render-preview/{preview_id}` | Rendered cut preview |
| POST | `/api/projects/current/restore` | Restore selection |
| POST | `/api/projects/current/save` | Save project |
| POST | `/api/projects/current/settings` | Update editor settings |
| GET | `/api/projects/current/source-video` | Source video |
| POST | `/api/projects/current/splices/adjust` | Adjust splice |
| POST | `/api/projects/current/splices/review` | Review splice |
| POST | `/api/projects/open` | Open project |
| POST | `/api/projects/open-dialog` | Open project dialog |
| POST | `/api/projects/transcribe` | Transcribe project |
| GET | `/api/projects/transcribe/jobs/{job_id}` | Transcribe job status |
| POST | `/api/projects/transcribe/start` | Start transcribe project |

### Other

| Method | Route | Purpose |
| --- | --- | --- |
| POST | `/api/caption/choose-output-folder` | Choose caption output folder |
| POST | `/api/caption/choose-video` | Choose caption video |
| POST | `/api/caption/generate` | Generate caption video |
| GET | `/api/caption/options` | Caption options |
| POST | `/api/caption/preview` | Caption preview |
| GET | `/api/caption/source-video` | Caption source video |
| POST | `/api/caption/styles` | Save caption style |
| DELETE | `/api/caption/styles/{name}` | Delete caption style |
| GET | `/api/creator-production/capabilities` | Creator production capabilities |
| GET | `/api/creator-production/channel-profiles` | Creator production channel profiles |
| GET | `/api/creator-production/current` | Current creator production |
| POST | `/api/creator-production/initialize` | Initialize creator production |
| GET | `/api/creator-production/jobs` | List creator production jobs |
| POST | `/api/creator-production/jobs` | Create creator production job |
| GET | `/api/creator-production/jobs/{job_id}` | Get creator production job |
| POST | `/api/creator-production/jobs/{job_id}/cancel` | Cancel creator production job |
| POST | `/api/creator-production/jobs/{job_id}/claim` | Claim creator production job |
| POST | `/api/creator-production/jobs/{job_id}/complete` | Complete creator production job |
| GET | `/api/creator-production/jobs/{job_id}/handoff` | Get creator production handoff |
| POST | `/api/creator-production/jobs/{job_id}/start` | Reject the retired nested Codex execution path |
| GET | `/api/creator-production/pipeline` | Creator production pipeline |
| GET | `/api/creator-production/render-jobs` | List creator render jobs |
| POST | `/api/creator-production/render-jobs` | Create creator render job |
| POST | `/api/creator-production/render-jobs/{job_id}/cancel` | Cancel creator render job |
| POST | `/api/creator-production/render-jobs/{job_id}/start` | Start creator render job |
| GET | `/api/creator-production/review` | Get creator production review |
| GET | `/api/creator-production/review-video` | Creator production review video |
| POST | `/api/creator-production/review/approve` | Approve creator production review |
| POST | `/api/creator-production/review/notes` | Save creator production review note |
| POST | `/api/creator-production/review/notes/{note_id}/accept` | Accept creator production review note |
| GET | `/api/creator-production/source-evidence` | Get creator source evidence |
| POST | `/api/creator-production/source-evidence` | Update creator source evidence |
| POST | `/api/creator-production/studio/edits` | Apply creator studio edits |
| POST | `/api/creator-production/studio/handoff` | Create creator studio handoff |
| POST | `/api/creator-production/workflow-upgrade` | Upgrade creator production workflow |
| GET | `/api/health` | Health |

## Storage and State

| Data | Location/lifetime |
| --- | --- |
| Active sources, analysis, preview cache, jobs | FastAPI process memory |
| Editor project, decisions, and pause-removal setting | User-selected version-2 `.vcg.json`; version 1 remains readable |
| Custom caption styles | `%LOCALAPPDATA%\VCG AutoCaption\style_library.json` |
| Temporary media and logs | `app/temp/` |
| Default exports | `app/exports/` or a selected folder |
| Whisper model files | External Hugging Face cache |

The project format stores absolute source paths, so moving source media or
opening the same project on another computer can break the link.

## Security Boundary

Uvicorn and Next.js bind to `127.0.0.1`. The API applies trusted-host checks,
allows only the local UI origins, rejects unexpected browser origins, disables
OpenAPI/docs routes, and adds `nosniff` and no-referrer headers. These controls
reduce accidental exposure but do not turn the application into a remotely
hostable multi-user service.

## Validation Baseline

- All 344 Python tests pass when pytest is run explicitly against `tests/`;
  5 environment-dependent tests skip.
- All 3 Node web tests pass.
- File-picker failures expose the exact backend exception in the existing
  transcript status area; normal picker operation adds no diagnostic overlay.
- TypeScript typecheck and the Next.js production build pass.
- Test coverage is strongest around pure core logic and API handlers.
- There is no automated browser workflow test and no real-media golden-output
  suite.
- Pytest currently reports a Starlette `TestClient`/`httpx` deprecation warning;
  it does not fail the suite. Explicitly targeting `tests/` avoids unrelated
  ignored cache directories.
- Dependency/security audits should be rerun after the current uncommitted
  changes are settled.
