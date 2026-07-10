# Current System

Last verified against the working tree: July 10, 2026.

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

The API holds one active transcript project, one selected caption source, and
one selected audio source in process memory. Restarting it clears unsaved
in-memory selections and jobs, but saved `.vcg.json` projects and custom styles
remain on disk.

## Main Components

| Location | Responsibility |
| --- | --- |
| `web/app/page.tsx` | All three workspace UIs, interaction state, source playback, splice preview sequencing, caption overlay preview, and progress modals |
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
| `app/core/style_library.py` | Built-in and user-created caption style persistence |
| `app/core/windows_dialog.py` | Windows-native open/save/folder dialogs used by the local API |
| `scripts/dev_web.py` | Starts or reuses the API and Next.js development processes |
| `app/main_window.py` | Retained PySide6 caption UI, not the primary product surface |

## Transcript Edit Workflow

### Creating or opening a project

The user can select a source video and start a background transcription job, or
open an existing `.vcg.json` file. Transcription probes the source FPS, extracts
audio, runs `faster-whisper` with word timestamps, and builds words, sentence
IDs, frame indices, and silence ranges.

Background job state contains `running`, `complete`, or `failed`, plus a numeric
or indeterminate progress value, message, result, and error. Jobs exist only in
the API process and are not resumable after restart.

### Editing and splice review

Words and silence are presented as one ordered token stream. Delete decisions
remain non-destructive and deleted content stays available for restoration.
Current kept ranges generate the splice queue dynamically. A splice records:

- stable left/right source anchors;
- suggested and adjusted OUT/IN frames;
- separate left and right frame adjustments;
- surrounding transcript context;
- reviewed status; and
- 2-, 4-, and 6-second source preview segments.

The browser previews a splice by playing the outgoing source segment, seeking
to the incoming segment, and continuing playback. It does not render a preview
MP4. Individual frames are available from the API for the IN/OUT review cards.

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
folder.

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
output settings. In the current uncommitted working tree, caption wrapping,
safe horizontal margins, preview scaling, bundled Montserrat handling, and
Windows-compatible H.264 output are being refined.

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
| POST | `/api/projects/current/delete-dead-space` | Delete all current silence ranges |
| POST | `/api/projects/current/splices/adjust` | Nudge splice OUT/IN frames |
| POST | `/api/projects/current/splices/review` | Set reviewed state |
| POST | `/api/projects/current/save` | Save active project, prompting if necessary |
| GET | `/api/projects/current/document` | Return the serializable project document |
| POST | `/api/projects/current/export` | Export adjusted kept ranges |
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
| Editor project and decisions | User-selected `.vcg.json` |
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

- All 58 Python tests pass.
- TypeScript typecheck and the Next.js production build pass.
- Test coverage is strongest around pure core logic and API handlers.
- There is no automated browser workflow test and no real-media golden-output
  suite.
- Pytest currently reports a Starlette `TestClient`/`httpx` deprecation warning
  and a local cache-directory permission warning; neither fails the suite.
- Dependency/security audits should be rerun after the current uncommitted
  changes are settled.
