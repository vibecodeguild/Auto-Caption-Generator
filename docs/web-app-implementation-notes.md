# Web App Implementation Notes

The web app scaffold keeps the existing Python core logic and adds a Next.js UI
that talks to a local FastAPI server.

## Run

```powershell
npm run dev
```

This starts:

```text
Python API: http://127.0.0.1:8731
Next.js UI: http://127.0.0.1:3000
```

## Current Test Workflow

1. Start `npm run dev`.
2. Open `http://127.0.0.1:3000`.
3. Paste the path to an existing `.vcg.json` editor project.
4. Click **Open Project**.
5. Select words or dead-space chips.
6. Press `D` to delete or `R` to restore.
7. Use inline splice controls to preview `2`, `4`, or `6` seconds.
8. Use `Out -/+` and `In -/+` to nudge frames.
9. Save the project or export a rough cut.

## API Endpoints

```text
GET  /api/health
POST /api/projects/open
GET  /api/projects/current
POST /api/projects/current/delete
POST /api/projects/current/restore
POST /api/projects/current/splices/adjust
POST /api/projects/current/splices/review
POST /api/projects/current/save
POST /api/projects/current/export
GET  /api/projects/current/source-video
```

`source-video` serves the active source video with HTTP range support so the
browser video element can seek through the original file. Splice preview should
continue to operate by seeking the source video, not by rendering temporary
preview MP4 files.

## Current Limitations

- The first web milestone opens existing `.vcg.json` projects by path.
- New project creation and transcription from the web UI are still next scope.
- The caption generator has not yet been moved into the web UI.
- Export is synchronous in the first API version. Long-running export should move
  to a job/status endpoint.
- The local API keeps the currently loaded project in process memory. Multi-tab
  or multi-project support needs explicit project IDs.
