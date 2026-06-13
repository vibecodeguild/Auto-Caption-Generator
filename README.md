# VCG AutoCaption

VCG AutoCaption is a local Windows desktop app for generating burned-in,
CapCut-style captions for creator videos. It transcribes speech locally with
`faster-whisper`, creates active-word ASS subtitles, and renders a finished
MP4 with FFmpeg.

The app does not require user accounts, cloud uploads, analytics, or API keys.

## Features

- Dark desktop editor UI built with PySide6
- First-frame video preview with live caption styling
- Embedded splice preview playback for transcript edits
- Local transcription through `faster-whisper`
- Word-level timestamp captions
- Active-word highlighting
- Caption presets for short-form, creator, YouTube, and podcast-style videos
- CPU mode by default
- Optional NVIDIA GPU mode
- Reusable caption style library
- Font, color, outline, shadow, glow, position, and grouping controls
- FFmpeg subtitle burn-in and transcript cut export to MP4
- Experimental transcript edit tab with video transcription, dynamic splice rows, frame nudge controls, project save/open, splice preview, and rough cut export

## Planned Direction

The next major direction is full transcript-based video editing with
non-destructive, frame-based cutting. The design is documented in
[`docs/transcript-editor-design.md`](docs/transcript-editor-design.md).

The current transcript editor tab is an early working foundation. It can
transcribe a selected video, save/open editor project JSON, select words and
dead-space chips as cut decisions, review dynamic splice rows, nudge OUT/IN
frames, preview splice playback, and export a rough cut. Frame thumbnails and
full project-folder workflow are still planned scope.

## Requirements

- Windows
- Python 3.10 or newer
- FFmpeg from the `imageio-ffmpeg` Python dependency, FFmpeg available on
  `PATH`, or `ffmpeg.exe` placed at `tools/ffmpeg/ffmpeg.exe`
- For CPU mode: no GPU setup is required
- For NVIDIA GPU mode: an NVIDIA driver compatible with CUDA 12, plus CUDA/cuDNN runtime DLLs

## Setup

Create a virtual environment and install the base dependencies:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

For optional NVIDIA GPU support, install the GPU dependency set instead:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-gpu.txt
```

The base dependency set includes `imageio-ffmpeg`, which provides an FFmpeg
binary inside the virtual environment. If you prefer a system FFmpeg install,
install FFmpeg from a trusted source and make sure `ffmpeg` is available:

```powershell
ffmpeg -version
```

You can also place FFmpeg manually here:

```text
tools\ffmpeg\ffmpeg.exe
```

FFmpeg binaries are not committed to this repository.

## Run

Double-click:

```text
Start VCG AutoCaption.cmd
```

That launcher opens the app without typing terminal commands, as long as the
virtual environment has been created first.

Manual fallback:

```powershell
.\.venv\Scripts\python.exe run_app.py
```

If Python is associated with `.pyw` files on Windows, you can also double-click:

```text
VCG AutoCaption.pyw
```

## Basic Workflow

1. Choose a video file.
2. Choose an output folder.
3. Select a caption preset.
4. Select the Whisper model.
5. Choose CPU or NVIDIA GPU.
6. Adjust style settings with the preview panel.
7. Save the style if you want to reuse it.
8. Click **Generate Video**.

The exported file is named:

```text
input-name_captioned.mp4
```

## Privacy

- Videos stay on the local machine.
- Audio extraction, transcription, subtitle generation, and rendering happen locally.
- No API keys are required.
- No videos are uploaded by this app.
- Temporary audio, preview, and subtitle files are written under `app/temp/`.
- Per-run editor logs are written under `app/temp/logs/`.
- Exported videos are written to the selected output folder.

`faster-whisper` may download model files on first use through the Hugging Face
model cache. That is expected setup-time network access for local model files.

## Tests

```powershell
.\.venv\Scripts\python.exe -m pytest
```

The core tests cover caption grouping, ASS subtitle formatting, active-word
subtitle events, style persistence, and effect rendering flags.

## Notes For Public Reuse

- The project is licensed under the MIT License.
- Do not commit videos, generated exports, temporary audio, model files, FFmpeg binaries, virtual environments, or secret files.
- Only include font files you are licensed to redistribute.
- FFmpeg has its own license and redistribution requirements.
- Whisper/faster-whisper model files are downloaded and cached outside this repository by default.

## Known Limitations

- First transcription can be slow because the selected model may download.
- CPU transcription can be slow for long videos.
- GPU mode depends on the local NVIDIA/CUDA/cuDNN environment.
- Word timing is only as accurate as Whisper's timestamps.
- Noisy audio can reduce caption accuracy.
- Captions are burned permanently into the exported video.
- Manual caption editing and batch processing are not included yet.
- Transcript-based cutting has an experimental editor foundation. Embedded media playback, frame thumbnails, and full project-folder workflow are not complete yet.
