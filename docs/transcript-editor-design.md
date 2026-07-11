# Transcript Editor And Frame-Based Cutting Design

> Product design record, status reviewed July 11, 2026. Most of the core editor
> model and the web splice-review workflow are implemented. The authoritative
> current inventory is [Current System](current-system.md); remaining gaps are
> tracked in [Outstanding Work](outstanding-work.md). Proposed project-folder,
> integrated remap/caption, and packaging sections below are still design
> direction rather than completed behavior.
>
> The source-seeking-only preview statement retained below is historical. The
> approved workflow now uses source seeking in Stage 3 and a complete temporary
> rendered-cut draft in Stage 4, with embedded splice adjustment and refresh.

This document captures the product model for expanding VCG AutoCaption from a
caption generator into a local transcript-based video editor. The current app
generates burned-in captions and includes an early transcript editor foundation.

The implementation direction has changed since the first PySide6 prototype. New
UI work should target the local web app architecture described in
[`web-app-architecture-pivot.md`](web-app-architecture-pivot.md).

## Current Implementation Status

Implemented foundation:

- Canonical transcript, silence, edit decision, kept range, and dynamic splice
  models.
- Dynamic splice generation from deleted words and deleted silence.
- OUT and IN frame nudges that update export intervals.
- Transcript remapping for cut timelines.
- FFmpeg trim/concat command generation for cut export.
- A PySide6 transcript edit tab with sample data, fixed preview area,
  independently scrollable transcript panel, dynamic splice rows, inline
  controls, expanded selected-splice state, and configurable shortcut defaults.
- Real video transcription into the transcript editor tab.
- Project save/open for editor project JSON.
- Clickable word and dead-space controls for creating cut decisions.
- Rough cut export from the adjusted kept ranges.
- Complete rendered-cut review with splice timeline navigation, embedded frame
  adjustment, stale-state reporting, and full refresh.
- Optional audio normalization during final cut export.

Still planned or incomplete:

- Rich frame-strip thumbnail extraction; the current API/UI displays the active
  OUT and IN frames.
- Remapping captions/transcripts as part of the integrated export workflow.
- Full per-video project folder workflow.

Architecture pivot:

- The PySide6 transcript editor is a prototype and reference, not the target UI
  architecture.
- The next editor should use browser-native source video playback inside a
  Next.js frontend.
- The Python backend should serve source video ranges and run Whisper/FFmpeg.
- Superseded preview rule: the original design used only source-video seek/jump
  preview and reserved MP4 creation for export. Current Stage 3 keeps the fast
  source preview, while Stage 4 deliberately creates a complete temporary draft.

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

### Transcript Panel As The Content Editing Surface

The transcript panel should focus on content decisions. It should show sentence
blocks, selectable word tokens, silence chips, deleted content, and compact
splice markers. It should not carry the full frame-tuning UI inline.

Deleted content should remain visible, but muted and struck through, so the user
can understand and restore prior decisions.

### Compact Inline Splice Markers

Each dynamic splice in the transcript should appear as a compact marker:

```text
Splice 003 - Needs review
```

Clicking the marker selects the splice in the splice review panel and scrolls
the transcript context so the selected cut is centered. The inline marker is for
navigation and status only. It should not include play buttons, frame nudges, or
review controls.

### Splice Review Queue

Every dynamic splice must be reviewed as its own item in a queue. The selected
splice panel should provide:

- Previous and next splice navigation.
- Current position, such as `Splice 003 of 018`.
- Needs review / reviewed status.
- Source-video preview playback for 2, 4, and 6 second splice windows.
- Loop toggle for repeated listening.
- OUT cut frame showing the last kept frame before the cut.
- IN cut frame showing the first kept frame after the cut.
- Nudge controls for 1, 5, and 10 frames in either direction.
- A clear visual distinction between the selected cut frame and surrounding
  frames.

The user should be able to work through all splices one by one without hunting
through the transcript manually. The transcript view should follow the selected
splice, not the other way around.

### Splice Panel Layout Direction

The splice panel should receive the most visual space during review. A useful
landscape layout is:

```text
Top row:
  compact project controls | source preview | transcript context around selected splice

Bottom row:
  splice review panel with OUT/IN cut frames and nudge controls
```

This separates content editing from frame tuning:

- Transcript context answers "what text did I remove?"
- Splice review answers "does this cut sound and look perfect?"

After testing, the five-frame strips were removed from the first review layout.
They added visual weight without enough editing value. The review panel should
show the two active cut frames clearly, then rely on frame-step controls to move
those frames through the source video.

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
  "out_frame_earlier": "A",
  "out_frame_later": "S",
  "in_frame_earlier": "D",
  "in_frame_later": "F",
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

The next implementation should use browser-native source video playback. The
frontend should seek through the original source video, play the outgoing side
of the splice, jump to the incoming side, then play the after-cut window.

Preview should not create temporary MP4 files. FFmpeg and ffprobe should remain
the source of truth for frame calculations and final export.

## Export

The final render should be built from adjusted kept ranges, not raw word
timestamps. FFmpeg should trim source video and audio to the chosen ranges, then
concatenate the ranges into the output video.

Frame-accurate cuts require re-encoding. Stream-copy export is faster, but it is
not appropriate for precise cuts because it can only cut cleanly at keyframes.

The exporter should also remap transcript word timings to the new output
timeline, so captions and final transcripts line up with the cut video.

## Suggested Module Boundaries

The editor should be built as reusable core logic with a web UI layer and a
Python local API:

```text
web/
  transcript editor components
  caption generator components
  source video player
  shortcut/settings UI

api/
  local project endpoints
  source video range endpoint
  transcription jobs
  export jobs

app/core/
  transcription
  project_store
  edit_decisions
  splice_generation
  frame_time
  video_cutter
  transcript_remap
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
- UI components render and manipulate the model without owning export logic.

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
- Whether the local web app uses one combined dev command or separate frontend
  and backend dev commands at first.
- Whether the first migrated milestone includes only transcript editing/preview
  or transcript editing plus export.
- Whether frame thumbnails are part of the first web migration or a follow-up.
