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

## API Inventory

### Health and project editing

| Method | Route | Purpose |
| --- | --- | --- |
| GET | `/api/health` | Process health check |
| POST | `/api/projects/open` | Open a `.vcg.json` by supplied path |
| POST | `/api/projects/open-dialog` | Open a project through a Windows dialog |
| GET | `/api/projects/current` | Return active project, tokens, edits, splices, and kept ranges |
| POST | `/api/projects/choose-video` | Select a transcript source video |
| POST | `/api/projects/transcribe` | Synchronous transcription compatibility route |
| POST | `/api/projects/transcribe/start` | Start a background transcription job |
| GET | `/api/projects/transcribe/jobs/{job_id}` | Poll transcription status/result |
| POST | `/api/projects/current/delete` | Delete selected word/silence tokens |
| POST | `/api/projects/current/restore` | Restore selected word/silence tokens |
| POST | `/api/projects/current/delete-dead-space` | Delete undeleted silence ranges meeting the project threshold |
| POST | `/api/projects/current/settings` | Update the bulk-pause threshold setting |
| POST | `/api/projects/current/analyze-pauses` | Measure threshold-qualified Whisper gap candidates and reject false long pauses |
| POST | `/api/projects/current/analyze-boundaries` | Analyze and persist assisted word-end suggestions for the current project |
| POST | `/api/projects/current/splices/adjust` | Nudge splice OUT/IN frames |
| POST | `/api/projects/current/splices/review` | Set reviewed state |
| POST | `/api/projects/current/render-preview` | Render the complete current cut and return its splice timeline |
| GET | `/api/projects/current/render-preview/{preview_id}` | Stream the active complete-cut review draft |
| POST | `/api/projects/current/save` | Save active project, prompting if necessary |
| GET | `/api/projects/current/document` | Return the serializable project document |
| POST | `/api/projects/current/export` | Export adjusted kept ranges, with optional sequential audio normalization |
| GET | `/api/projects/current/source-video` | Stream active source with byte-range support |
| GET | `/api/projects/current/frame` | Extract and return one source frame |

### Captions

| Method | Route | Purpose |
| --- | --- | --- |
| GET | `/api/caption/options` | Models, compute options, presets, styles, source, and output folder |
| POST | `/api/caption/choose-video` | Select caption source |
| POST | `/api/caption/choose-output-folder` | Select caption destination |
| POST | `/api/caption/preview` | Return/reuse timed words and caption groups |
| POST | `/api/caption/generate` | Render burned-in captions |
| POST | `/api/caption/styles` | Save a user style |
| DELETE | `/api/caption/styles/{name}` | Delete a non-built-in style |
| GET | `/api/caption/source-video` | Stream selected caption source |

### Audio

| Method | Route | Purpose |
| --- | --- | --- |
| GET | `/api/audio/options` | Presets, targets, source, and output folder |
| POST | `/api/audio/choose-video` | Select audio source |
| POST | `/api/audio/choose-output-folder` | Select audio destination |
| POST | `/api/audio/analyze` | Measure audio and recommend speech regions |
| POST | `/api/audio/preview` | Generate matched Original/Corrected clips |
| POST | `/api/audio/normalize` | Export normalized audio/video |
| GET | `/api/audio/source-video` | Stream selected source |
| GET | `/api/audio/preview/{preview_id}/{mode}` | Stream original or corrected preview |

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

- All 84 Python tests pass when pytest is run explicitly against `tests/`.
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
