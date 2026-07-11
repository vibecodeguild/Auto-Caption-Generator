# Web App Implementation Notes

Last verified: July 11, 2026.

This is the concise developer runbook. See [Current System](current-system.md)
for the full implementation inventory and [Outstanding Work](outstanding-work.md)
for the improvement assessment.

## Run

```powershell
npm run dev
```

The launcher starts or reuses:

```text
Python API: http://127.0.0.1:8731
Next.js UI: http://127.0.0.1:3000
```

The API must remain local-only. It reads and writes user-selected files and has
no remote-user authentication.

`windows_dialog.py` converts missing-PowerShell and picker-timeout failures into
actionable errors, and `web_api.py` returns the exception type/message in the
JSON error detail. The frontend shows actual failures in its existing transcript
status area and adds no UI while the picker is operating normally.

## Current UI

The page contains three tabs:

- **Transcript Edit** — use the five-stage source, pause analysis, cut review,
  complete rendered-preview, and final-export workflow. Final export can
  optionally normalize audio while preserving the unnormalized cut.
- **Caption Generator** — select source/output, prepare live timed captions,
  tune grouping/style, save styles, and render a captioned video.
- **Audio Normalizer** — select source/output, analyze, preview Original versus
  Corrected audio, and export normalized media.

The three workspaces are exposed through a compact Tools hover/focus menu in a
single-row header. Transcript Edit uses five connected numbered workflow
stages; the selected stage expands in place while other stages remain
number-only. Project open/save and settings remain separate compact utilities.

The transcript workspace uses a dedicated splice-review panel. Inline splice
markers select and navigate; playback, review, and IN/OUT adjustment controls
are not embedded in the transcript row.

## Development Commands

```powershell
npm run api
npm run web
npm run typecheck
npm run build
.\.venv\Scripts\python.exe -m pytest tests
```

## API Endpoints

```text
GET    /api/health

POST   /api/projects/open
POST   /api/projects/open-dialog
GET    /api/projects/current
POST   /api/projects/choose-video
POST   /api/projects/transcribe
POST   /api/projects/transcribe/start
GET    /api/projects/transcribe/jobs/{job_id}
POST   /api/projects/current/delete
POST   /api/projects/current/restore
POST   /api/projects/current/delete-dead-space
POST   /api/projects/current/settings
POST   /api/projects/current/analyze-pauses
POST   /api/projects/current/analyze-boundaries
POST   /api/projects/current/splices/adjust
POST   /api/projects/current/splices/review
POST   /api/projects/current/render-preview
GET    /api/projects/current/render-preview/{preview_id}
POST   /api/projects/current/save
GET    /api/projects/current/document
POST   /api/projects/current/export
GET    /api/projects/current/source-video
GET    /api/projects/current/frame

GET    /api/caption/options
POST   /api/caption/choose-video
POST   /api/caption/choose-output-folder
POST   /api/caption/preview
POST   /api/caption/generate
POST   /api/caption/styles
DELETE /api/caption/styles/{name}
GET    /api/caption/source-video

GET    /api/audio/options
POST   /api/audio/choose-video
POST   /api/audio/choose-output-folder
POST   /api/audio/analyze
POST   /api/audio/preview
POST   /api/audio/normalize
GET    /api/audio/source-video
GET    /api/audio/preview/{preview_id}/{mode}
```

All source and preview media routes support HTTP byte ranges. Stage 3 splice
review seeks through the source file. Stage 4 renders one complete temporary
review draft, returns every splice's rendered-timeline position, and replaces
the prior draft when refreshed.

## Process-State Caveat

`app/web_api.py` currently owns one active project plus caption/audio selections,
caches, analysis, previews, and transcription jobs in memory. Do not assume the
API is multi-tab safe or that unsaved state survives restart. This is the main
architectural constraint to address before multi-project work.

## Current Working-Tree Note

The current working tree contains the five-stage transcript workflow, cut-plan
validation, version-1-to-version-2 project compatibility, measured pause
analysis, Audio Boundary Assist, complete rendered-cut review, and optional
normalization during export. It also contains the earlier caption parity,
H.264, bundled-font, and Windows-native-dialog work. Recheck `git status`, run
the documented verification commands, and validate representative production
media before committing. Fixed word padding and transcript-wide automatic
boundary analysis are not part of the product.
