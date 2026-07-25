# VCG AutoCaption

VCG AutoCaption is a local Windows video utility with three working workflows:

- transcript-based video cutting and splice review;
- burned-in, active-word caption generation; and
- audio loudness analysis and normalization.

The current product interface is a Next.js web UI backed by a local FastAPI
process. Media processing stays on the computer and is performed with
`faster-whisper` and FFmpeg. No account, cloud upload, analytics service, or API
key is required.

The repository also retains the earlier PySide6 desktop prototype. It remains a
useful reference and can still be launched, but new product work should target
the web application unless a desktop-specific fix is intentional.

## Current Status

The local web application is functional, but it is still a development build,
not a packaged end-user release. Its four workspaces are implemented and share
one local API process.

| Workspace | Current capability |
| --- | --- |
| Transcript Edit | Run the five-stage workflow: choose/transcribe source media, validate and remove long pauses, fine-tune and manually review splices, review the complete rendered cut, then export with optional audio normalization. |
| Caption Generator | Inherit the active project cut and export folder, prepare a timed browser preview, customize grouping and visual style, save custom styles, and render a captioned MP4. |
| Audio Normalizer | Inherit the active project cut and export folder, analyze loudness, make Original/Corrected A/B previews, and export a normalized MP4. |
| Visual Production | Build reusable graphics and imported-animation cues on the active project, render review ranges, generate the Codex visual-planning handoff, and render the final MP4. |
| Visual Storytelling | Search reusable private callback footage before Pexels, prepare 3–5 B-roll candidates, review AI briefs and graphics together, freeze approved media, and retain stock evidence and credits. |

For a detailed implementation inventory, data-flow description, and API list,
see [Current System](docs/current-system.md). For the known gaps and recommended
improvement order, see [Outstanding Work](docs/outstanding-work.md).
The currently approved production sequence and rendered-preview design are in
[Active Build Plan](docs/active-build-plan.md).

## Requirements

- Windows 10 or newer
- Python 3.10 or newer
- Node.js and npm compatible with Next.js 16
- FFmpeg supplied by `imageio-ffmpeg`, available on `PATH`, or placed at
  `tools\ffmpeg\ffmpeg.exe`
- Optional NVIDIA GPU support requires a compatible NVIDIA driver and the
  packages in `requirements-gpu.txt`

Whisper model files may be downloaded from Hugging Face on first use. After the
model is cached, transcription runs locally.

## Setup

Create the Python environment and install the base dependencies:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Install frontend dependencies:

```powershell
npm install
```

For optional NVIDIA support, install the GPU packages in the same environment:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-gpu.txt
```

## Run the Current Web App

```powershell
npm run dev
```

This starts both processes:

```text
Next.js UI:       http://127.0.0.1:3000
Python local API: http://127.0.0.1:8731
```

The development launcher reuses either process if its expected URL is already
responding. Stop it with `Ctrl+C` in the terminal that launched it.

This application has permission to read and write user-selected local media.
It has no remote-user authentication because it is deliberately local-only.
Do not bind it to `0.0.0.0` or expose ports `3000` or `8731` through a tunnel,
reverse proxy, router, container mapping, or firewall rule.

## Workflows

### Transcript Edit

1. Choose one or more source clips to create a private parent project, or open an existing
   `.vcg-project.json` project. Legacy `.vcg.json` transcript projects remain
   supported.
2. Review the Source Sequence. Add recordings, move them up or down, or remove
   them before transcription. Matching same-camera clips combine quickly without
   re-encoding; incompatible clips are standardized automatically.
3. If starting from video, choose the Whisper model and CPU/GPU mode, then
   generate the transcript.
4. Click **Analyze Pauses** to measure only Whisper gaps that meet the configured
   long-pause threshold. Candidates measured below the threshold disappear.
5. Select transcript words or validated long-pause chips and delete or restore
   them. Bulk removal shows how many measured pauses currently qualify.
6. Click **Fine Tune** to analyze only the current unreviewed splice OUT points.
   The utility reports how many cuts were checked, adjusted, or unchanged.
7. Review the dynamic splice queue. Preview 2, 4, or 6 seconds around each join,
   adjust the OUT and IN frames, and mark reviewed splices.
8. In Stage 4, render the complete edited video as a fast review draft. Use the
   full-duration splice timeline and compact splice list to navigate joins,
   adjust OUT/IN frames in the preview workspace, and refresh the complete
   draft when pending changes make it stale.
9. Transcript and edit decisions save automatically under the active private
   project.
10. In Stage 5, export the re-encoded result to `exports/locked-cut.mp4` inside
   that project. Optional audio normalization produces the same authoritative
   locked-cut output after using a private working intermediate.

Original source clips are never modified. The parent project stores their
order, technical metadata, continuous-timeline boundaries, transcript timing,
delete decisions, splice adjustments, artifact revisions, and review state.

### Caption Generator

1. Use the active project cut and project-managed export folder. Standalone
   legacy use can still choose these manually.
2. Select a Whisper model, compute mode, grouping preset, and caption style.
3. Prepare the live preview. If the same video is loaded in Transcript Edit,
   the existing transcript is reused; otherwise the preview transcribes and
   caches the selected source/model combination.
4. Adjust font, size, active-word treatment, colors, outline, shadow, glow,
   placement, and grouping limits.
5. Optionally save the style for later use.
6. Generate `<source>_captioned.mp4`.

Caption text itself is not yet manually editable. The current controls affect
grouping and presentation of the Whisper result.

### Audio Normalizer

1. Choose a video and one of Normalize Only, Gentle Voice Leveling, or Strong
   Voice Leveling.
2. Analyze the full track, or generate a preview and allow analysis to run as
   part of that operation.
3. Compare Original and Corrected versions of the same 20-second region. The UI
   can recommend the loudest and quietest speech regions using voice activity
   detection.
4. Export `<source>_normalized.mp4`.

Defaults target `-14 LUFS` integrated loudness, `-1.5 dBTP` true peak, and
`7 LU` loudness range. The export stream-copies video when possible and writes
48 kHz AAC audio. The original file is not modified.

## Files and Local Data

- Temporary audio, previews, subtitles, frames, and logs: `app/temp/`
- Default generated exports: `app/exports/`
- Saved custom caption styles: `%LOCALAPPDATA%\VCG AutoCaption\style_library.json`
- Whisper models: the normal Hugging Face cache outside this repository
- Editor projects: user-selected `.vcg.json` files containing transcript text
  and an absolute path to the source video

Generated media, project data, model files, local environments, secrets, and
build output are excluded by `.gitignore`.

Visual-production projects should be created outside the repository with
`scripts/new_visual_project.py`. See
[Visual Production Workflow](docs/visual-production-workflow.md) for the public
module/private-content boundary. Run `npm run privacy:check` before publishing;
the same check runs in CI and can be installed as a local pre-commit hook with
`scripts/install_privacy_hook.ps1`.

## Development Commands

```powershell
# Run API and UI together
npm run dev

# Run either side separately
npm run api
npm run web

# TypeScript validation and production build
npm run typecheck
npm run build

# Python test suite (explicit path avoids unrelated temp/cache traversal)
.\.venv\Scripts\python.exe -m pytest tests
```

The Python suite currently contains 141 tests covering transcript/edit models,
splice generation and preview, project persistence, caption grouping/ASS
generation, FFmpeg command construction, audio normalization, local API
behavior, host/origin enforcement, Windows dialog integration, and repository
privacy boundaries. There is not yet a browser-level end-to-end test suite.

If Open Video or Open Project fails, the existing transcript status area shows
the exact backend picker exception. Normal picker operation adds no extra UI.

## Retained PySide6 Prototype

The earlier desktop interface can still be launched with:

```text
Start VCG AutoCaption.cmd
```

or:

```powershell
.\.venv\Scripts\python.exe run_app.py
```

It contains the original caption generator and transcript-editor prototype.
The launcher does not start the current web application, and feature parity
between the two interfaces is not guaranteed.

## Security and Public Reuse

- The project is licensed under the MIT License.
- Current reporting guidance and the local-only boundary are in
  [SECURITY.md](SECURITY.md).
- [security_best_practices_report.md](security_best_practices_report.md) is a
  dated June 18, 2026 audit record, not a claim about all later changes.
- Do not commit real videos, transcripts, `.vcg.json` projects, generated
  exports, model files, FFmpeg binaries, logs, virtual environments, or secrets.
- Only redistribute fonts and FFmpeg builds under their respective licenses.

## Documentation Map

- [Current System](docs/current-system.md): source-of-truth implementation map
- [Outstanding Work](docs/outstanding-work.md): gaps, risks, and proposed order
- [Active Build Plan](docs/active-build-plan.md): approved implementation order,
  safety gates, and rendered-preview mockup
- [Web App Implementation Notes](docs/web-app-implementation-notes.md): concise
  developer runbook and endpoint catalog
- [Architecture Pivot](docs/web-app-architecture-pivot.md): historical decision
  record for moving away from a PySide6-first UI
- [Transcript Editor Design](docs/transcript-editor-design.md): original product
  model, with current implementation status noted at the top
- [Visual Production Workflow](docs/visual-production-workflow.md): separate
  post-cut graphics, imported media, review, and rendering contract
- [Visual Storytelling Assets](docs/visual-storytelling-assets.md): Creator
  Library, callback footage, Pexels B-roll, review queue, and provenance plan
  post-cut graphics workflow, reusable module contracts, and private workspace
  boundary
- [Security Policy](SECURITY.md): vulnerability reporting and trust boundary
