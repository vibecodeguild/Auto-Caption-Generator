# Transcript Editor And Frame-Based Cutting Design

This document captures the planned direction for expanding VCG AutoCaption from
a caption generator into a local transcript-based video editor. The current app
generates burned-in captions. The editor described here is planned scope and is
not implemented yet.

## Goals

- Edit video by working directly from the transcript.
- Delete words, sentences, and silence without destructive changes to the
  original video.
- Generate a cut video from the current transcript edit decisions.
- Review every splice created by those decisions.
- Fine tune each splice frame by frame.
- Reopen a project later and adjust prior cut decisions.
- Keep all files for one video project together in one project folder.
- Reuse the same transcription source for both caption generation and transcript
  editing.

## Core Product Decisions

### Project Folders

Each video should live inside a project folder rather than scattering generated
files next to source media. A typical project folder should be able to contain:

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
```

This keeps raw media, transcript data, edit decisions, captions, and exports
organized around the video being produced.

### Shared Transcription Data

The transcript editor should use a richer transcription result than the current
caption-only pipeline. The shared transcript should include both raw Whisper word
text and cleaned display text:

```json
{
  "source": "raw-recording.mp4",
  "model": "base.en",
  "device": "cuda",
  "language": "en",
  "duration": 123.456,
  "words": [
    {
      "id": "word_000001",
      "raw": " Hello",
      "text": "Hello",
      "start": 0.1,
      "end": 0.42,
      "start_frame": 3,
      "end_frame": 13
    }
  ],
  "segments": [
    {
      "start": 0.0,
      "end": 4.8,
      "text": "Hello world."
    }
  ]
}
```

Raw word text preserves spacing for readable transcript reconstruction. Cleaned
word text remains better for selection, caption grouping, and display.

### Global Transcription Settings

Model and compute device choices should be application-level settings that
persist across projects. The app should continue to use explicit choices such as
CPU or NVIDIA GPU. GPU failure should be visible to the user rather than silently
falling back to CPU.

The larger Whisper models are deferred scope, but the settings model should allow
additional model choices later.

### Frame-First Editing

Whisper timestamps are useful estimates, but they are not precise edit points.
Cutting should be frame-based:

- Transcript word times propose initial cut locations.
- The app converts those times to frame positions.
- The user can nudge each splice frame by frame.
- The final export uses the adjusted frame decisions.

The app may store timestamps alongside frame indexes for compatibility with
FFmpeg and variable-frame-rate media, but the editing interface should present
cut decisions as frames.

### Non-Destructive Edit Decisions

The app should not permanently modify the source video or collapse prior
decisions into a one-way exported cut. It should save an edit decision list that
can be reopened and changed.

Example shape:

```json
{
  "source_video": "source/raw-recording.mp4",
  "fps": 30.0,
  "deleted_ranges": [
    {
      "id": "delete_001",
      "start_word_id": "word_000120",
      "end_word_id": "word_000145",
      "start_frame": 3620,
      "end_frame": 4411,
      "reason": "sentence"
    }
  ],
  "kept_ranges": [
    {
      "id": "keep_001",
      "suggested_start_frame": 0,
      "suggested_end_frame": 3619,
      "adjusted_start_frame": 0,
      "adjusted_end_frame": 3622
    }
  ]
}
```

The transcript is source data. The edit decision list is the user's editing
state. Exports are render artifacts.

## Dynamic Splice Model

Splices should not be permanently attached to sentences. A splice exists only
when current delete decisions create a join between two kept regions.

For example:

```text
Sentence 1: A B C
Sentence 2: D E F
Sentence 3: G H I
Sentence 4: J K L
```

If sentence 2 is deleted, the splice is:

```text
end of C -> start of G
```

If sentence 3 is also deleted, the splice changes to:

```text
end of C -> start of J
```

If only the first word of sentence 3 is deleted, the splice becomes:

```text
end of C -> start of H
```

The UI should therefore generate splice controls from the current kept ranges.
Those controls should appear, disappear, and update as words, sentences, and
silence ranges are deleted or restored.

Example splice object:

```json
{
  "id": "splice_003",
  "left_keep_range_id": "keep_001",
  "right_keep_range_id": "keep_002",
  "left_out_frame": 3622,
  "right_in_frame": 4550,
  "left_out_adjustment": 3,
  "right_in_adjustment": -2,
  "reviewed": false
}
```

The outgoing side and incoming side need separate controls because clipping can
occur on either side of the join.

## Editor UI Decisions

### Fixed Preview, Scrollable Transcript

The player and selected-splice details should remain fixed while the transcript
panel scrolls independently. The user should not need to scroll back to the top
to preview a cut after making transcript edits.

### Transcript Panel As The Editing Cockpit

The transcript panel should be the primary work surface. It should show sentence
blocks, selectable word tokens, silence chips, deleted content, and dynamic
splice rows.

Deleted content should remain visible, but muted and struck through, so the user
can understand and restore prior decisions.

### Inline Splice Controls

Each dynamic splice row should include the controls needed for the fast review
loop:

```text
Play [2] [4] [6] [Loop]   Out [-] [+]   In [-] [+]
```

Meaning:

- `2` plays one second before and one second after the splice.
- `4` plays two seconds before and two seconds after the splice.
- `6` plays three seconds before and three seconds after the splice.
- `Loop` repeats the selected splice preview.
- `Out [-] [+]` nudges the outgoing frame of the previous kept range.
- `In [-] [+]` nudges the incoming frame of the next kept range.

The minus and plus buttons should sit next to each other to minimize mouse
travel.

### Expanded Splice State

Each splice row can have a compact and expanded state.

The compact state should support normal fast editing:

```text
Splice 03  "...and it was super easy." -> "Luckily for me..."
Play [2] [4] [6] [Loop]   Out [-] [+]   In [-] [+]   Reviewed
```

The expanded state can show:

- Previous phrase and next phrase.
- OUT frame and IN frame numbers.
- Small before/after frame thumbnails.
- Reviewed status.
- Any export warnings for that splice.

The selected splice should also sync with the fixed preview area.

### Keyboard Shortcuts

Keyboard shortcuts should be configurable and persisted in settings. The primary
editing UI should not be cluttered with shortcut hints or instructional text.

Initial shortcut actions should include:

```json
{
  "play_splice_2s": "2",
  "play_splice_4s": "4",
  "play_splice_6s": "6",
  "toggle_loop": "L",
  "out_frame_back": "A",
  "out_frame_forward": "S",
  "in_frame_back": "D",
  "in_frame_forward": "F",
  "previous_splice": "J",
  "next_splice": "K",
  "mark_reviewed": "Enter",
  "delete_selection": "Delete",
  "restore_selection": "R"
}
```

Shortcut documentation can live in settings or a help dialog instead of the main
editing surface.

## Playback And Preview

The embedded player should support splice-specific preview playback:

- 2-second preview: one second before and one second after.
- 4-second preview: two seconds before and two seconds after.
- 6-second preview: three seconds before and three seconds after.

For the first implementation, PySide6 playback can be used for fast preview.
FFmpeg and ffprobe should remain the source of truth for frame calculations and
final export. If exact frame stepping in the player becomes necessary, the app
can later add FFmpeg, OpenCV, or PyAV-backed frame previews for selected splice
points.

## Export

The final render should be built from adjusted kept ranges, not raw word
timestamps. FFmpeg should trim source video and audio to the chosen ranges, then
concatenate the ranges into the output video.

Frame-accurate cuts require re-encoding. Stream-copy export is faster, but it is
not appropriate for precise cuts because it can only cut cleanly at keyframes.

The exporter should also remap transcript word timings to the new output
timeline, so captions and final transcripts line up with the cut video.

## Suggested Module Boundaries

The editor should be built as reusable core logic with a PySide6 UI layer:

```text
app/core/transcription.py
app/core/project_store.py
app/core/edit_decisions.py
app/core/splice_generation.py
app/core/frame_time.py
app/core/video_cutter.py
app/core/transcript_remap.py
app/ui/transcript_editor.py
app/ui/splice_controls.py
app/ui/video_preview.py
```

The exact file names can change during implementation, but the responsibilities
should remain separated:

- Transcription produces source transcript data.
- Project storage owns file layout and persistence.
- Edit decisions record user intent.
- Splice generation derives current splice controls from edit decisions.
- Frame/time conversion isolates video timing details.
- Video cutting exports adjusted kept ranges.
- Transcript remapping updates transcript timings after export.
- UI widgets render and manipulate the model without owning export logic.

## Non-Goals

- Do not build a traditional multi-track timeline editor.
- Do not make cuts destructive.
- Do not hide GPU failures with silent CPU fallback.
- Do not scatter project files next to arbitrary source videos.
- Do not require cloud accounts, API keys, or uploads for local editing.
- Do not clutter the transcript editor with visible shortcut hints.

## Open Implementation Questions

- Whether to port selected backend code from another prototype or rewrite the
  cutter and remapper inside this codebase.
- How much variable-frame-rate support is needed in the first implementation.
- Whether the first player version uses only `QMediaPlayer` or adds extracted
  frame thumbnails for selected splices immediately.
- How large the first transcript editor milestone should be: transcript editing
  only, or transcript editing plus export.

