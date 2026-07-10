# Local Web App Architecture Pivot

> Historical decision record, updated with status on July 10, 2026. The pivot
> described here has happened: the Next.js/FastAPI application is now the main
> product surface. Use [Current System](current-system.md) for present behavior
> and [Outstanding Work](outstanding-work.md) for remaining work. Future-tense
> sections below preserve the reasoning that guided the migration.

This document captures the next architecture direction for VCG AutoCaption after
the PySide6 prototype. The current desktop app proved the caption pipeline,
transcription settings, style system, transcript data model, edit decisions, and
rough cut export. The next version should move the UI to a local web app.

## Decision

Pivot from a PySide6-first desktop UI to a local web application:

```text
Next.js frontend
  - transcript editor UI
  - caption generator UI
  - source video preview
  - keyboard shortcuts
  - project/style settings

Python local API
  - faster-whisper transcription
  - CPU/GPU model selection
  - local project file access
  - source video range serving
  - FFmpeg caption burn-in and cut export
```

The app runs locally and keeps videos on the user's machine. `npm run dev`
starts the UI and Python API together.

## Why Pivot

The transcript editor is now a browser-shaped product:

- It needs reliable video playback, seeking, keyboard interaction, and rich
  layout control.
- HTML video in a browser/WebView2 is a better fit than Qt media widgets for the
  source-video preview loop.
- Next.js gives faster UI iteration through hot reload.
- The same web UI can later move closer to a hosted app without rewriting the
  editing experience.
- Python remains the right place for Whisper, FFmpeg, local file access, and GPU
  configuration.

The prototype also showed what not to do: preview playback should not render
temporary preview MP4 files. Preview should use the original source video and
seek/jump across the selected splice. Export is the only workflow that should
create a new MP4.

## Local Development Shape

Recommended local developer workflow:

```powershell
npm run dev
```

The dev script starts both the Python API and the Next.js UI.

Recommended runtime ports:

```text
Next.js UI:       http://127.0.0.1:3000
Python local API: http://127.0.0.1:8731
```

The API should bind to `127.0.0.1`, reject non-local hosts, and reject
unexpected cross-origin requests.

## Client And Server Boundaries

### Next.js Frontend

The frontend owns interaction and presentation:

- Project dashboard and workspace navigation.
- Transcript editor layout.
- Word/dead-space selection.
- Inline splice controls.
- Keyboard shortcuts.
- Caption style controls and preview overlays.
- HTML video element playback.
- Calls to local API endpoints.

The frontend should not run FFmpeg, directly scan arbitrary local folders, or
own Whisper model execution.

### Python Local API

The Python API owns local machine operations:

- Open/select project files and source videos.
- Serve selected source video files with HTTP range support for browser
  playback.
- Run `faster-whisper` transcription with explicit model/device settings.
- Store transcripts, edit decisions, settings, and project metadata.
- Run FFmpeg exports for cuts and captioned videos.
- Write per-project logs and operation status.

The backend should return clear errors instead of silently falling back. GPU
transcription failures should stay visible.

## Video Preview Model

Preview must operate on the source video:

```text
User clicks splice Play 4
  -> frontend computes or receives preview windows
  -> HTML video seeks to source OUT preview start
  -> plays until OUT frame
  -> jumps to IN frame
  -> plays after-cut window
  -> stops or loops
```

No preview MP4 should be generated. Temporary video files are only appropriate
for final exports or explicit render artifacts.

The backend should expose the selected source video through a local endpoint
with byte-range support:

```text
GET /api/projects/{projectId}/source-video
```

This lets the browser video element seek efficiently without giving the web UI
unrestricted filesystem access.

## Export Model

Exports remain backend work:

- Cut export uses adjusted kept frame ranges.
- Captioned export burns ASS subtitles into the video.
- Final combined workflows can later produce cut + captioned versions.
- Exports write into the active project folder.

Frame-accurate cuts require re-encoding. Stream-copy export should not be the
default for precise transcript edits.

## Transcription Model Location

For the local app, Whisper runs locally:

```text
Python API -> faster-whisper -> local CPU or NVIDIA GPU
```

Model files should remain outside the repository, using the normal Hugging Face
cache or a shared local model cache.

For a hosted app, Whisper would move to the server:

```text
Hosted frontend -> hosted API/job queue -> server GPU/CPU workers
```

A hosted browser app cannot freely access local video files or the user's local
GPU. A deployed version would need upload/storage, server-side jobs, usage
limits, and probably authentication. The local version should be designed so the
UI can later call a hosted API, but the first build should stay local-first.

## Project File Direction

The app should move toward one folder per video project:

```text
project-name/
  source/
    raw-recording.mp4
  transcripts/
    transcript.raw.json
    transcript.clean.txt
    transcript.editor.json
  edits/
    edit-decision-list.json
  exports/
    rough-cut.mp4
    captioned.mp4
    final.mp4
  settings/
    project-settings.json
  logs/
    project.log
```

This avoids scattering transcripts, cut lists, logs, and exports next to random
source videos.

## Public Repo Safety

The repo should not include:

- Videos or audio.
- Generated transcripts from real projects.
- Project folders with user content.
- Model files.
- FFmpeg binaries.
- Local logs.
- API keys, tokens, certs, or `.env` files.

The `.gitignore` should continue to ignore generated project data, temp files,
exports, local models, virtual environments, and secret files.

## Migration Milestones

1. **Scaffold local web app**
   - Add Next.js frontend.
   - Add Python local API.
   - Add dev scripts.
   - Keep the existing PySide app untouched until replacement workflows work.
   - Status: first scaffold complete.

2. **Move transcript editor first**
   - Use HTML video playback against source video.
   - Port transcript display, selection, dead-space chips, compact dynamic
     splice markers, selected-splice navigation, OUT/IN cut frame previews,
     frame nudges, and keyboard shortcuts.
   - Save/open project JSON through the API.
   - Status: first open/edit/preview/save/export workflow implemented for
     existing `.vcg.json` editor projects.

2a. **Refine splice review workflow**
   - Treat dynamic splices as a review queue.
   - Show previous/next controls in the splice panel.
   - Keep the transcript context centered on the selected splice.
   - Move all play, review, and frame nudge controls out of the inline transcript
     row and into the selected-splice panel.
   - Give the splice panel enough space for OUT and IN frame strips.

3. **Wire transcription**
   - Reuse the existing `faster-whisper` backend logic.
   - Persist global model/device settings.
   - Report progress and logs through API status endpoints.

4. **Wire export**
   - Reuse FFmpeg cut export and caption burn-in logic.
   - Keep exports inside the project folder.
   - Remap transcript timings after cuts.

5. **Move caption generator**
   - Port caption preset/style UI into Next.js.
   - Use source frame preview and browser overlay rendering.
   - Keep FFmpeg rendering in Python.

6. **Package local launch**
   - Add a double-click launcher that starts the local API and opens the Next.js
     app in the browser or a WebView2 desktop shell.
   - Keep `npm run dev` as the main development workflow.

## Non-Goals For The Pivot

- Do not build cloud hosting in the first migration.
- Do not require accounts or API keys for the local app.
- Do not make the browser directly access arbitrary local files.
- Do not generate preview MP4 files for splice review.
- Do not continue investing in Qt-specific video playback fixes.
