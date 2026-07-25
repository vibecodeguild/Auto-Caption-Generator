# Outstanding Work and Improvement Assessment

Last assessed: July 11, 2026.

The user-approved implementation sequence now lives in
[Active Build Plan](active-build-plan.md). This document remains the broader
assessment and backlog.

This is a repository-backed assessment of unfinished work. It distinguishes
confirmed gaps in the current implementation from optional product expansion.

## Executive Assessment

The project is no longer an early scaffold. Its core local workflows are real
and testable. The biggest issue is that they grew as three useful tools inside a
development shell without a fully unified project model, durable job system, or
release/packaging path.

The approved five-stage transcript workflow now has an initial implementation,
including measured pause analysis, Audio Boundary Assist, complete rendered-cut
review, and optional normalization during final export. The best next move is
live production testing and stabilization before major new features: validate
real recordings, capture repeatable failure clips, establish real-media and
browser quality gates, and then address project durability and cut-to-caption
integration.

A separate Visual Production workflow is also approved for development after
the locked cut/audio boundary. Its goal is to replace CapCut as the final
assembly step for generated graphics, imported AI animations, overlays,
transitions, and final rendering. The 60-second segment of an already published
video is the development fixture; completing the full 14-minute video is not a
deliverable. See [Visual Production Workflow](visual-production-workflow.md).

## Accurate IN-Point Alignment

Large v3 and NVIDIA GPU remain the approved production transcription defaults.
Real-project calibration showed that raw waveform onset and VAD-padding changes
do not reliably reproduce reviewed IN points. GPU phoneme forced alignment was
also calibrated after approval: WhisperX's English model did not improve the
moved-cut average, and the multilingual MMS model improved moved cuts but caused
false moves on accepted cuts. Neither has a reliable production gate, so no
automatic timestamp rewrite is enabled.

The supporting history layer is implemented: new projects preserve the first
generated transcript, final reviewed editor state, generation provenance, and an
edit-analysis report for future calibration.

The next decision should use multiple saved project histories to identify a
repeatable, model-specific signal that separates boundaries needing a later IN
from intentionally preserved lead-in. Do not introduce a fixed offset or an
alignment-score threshold from the single July 15 project.

## Priority 0: Live-Test and Settle the Current Working Tree

The checkout contains the complete current feature tranche as uncommitted work:

- cut-plan validation and safe frame clamping;
- measured, threshold-aware pause analysis and removal;
- Audio Boundary Assist with separate Whisper, assisted, and manual frames;
- the single-row five-stage header;
- complete rendered-cut review with splice navigation and stale refresh;
- optional normalization during Stage 5 export; and
- the earlier caption parity, H.264, bundled-font, and Windows-dialog changes.

Use the next real production videos to verify complete workflow behavior,
render time, audiovisual joins, pause classification, assisted word endings,
landscape/portrait layout, rendered-preview navigation, refresh behavior, and
normalized final output. Preserve representative failure clips before tuning
detectors or transcription settings. After live validation, review the diff and
commit the feature set in coherent units.

### Visual Production live-test enhancements

- [x] **Prevent duplicate render jobs and preserve visible status.** The July
  20 Grok for Excel production test allowed a second render to start while the
  first was still running. The final-export control is disabled during an
  active job, the API returns the existing job for duplicate starts, and the
  private job snapshot restores stage, percentage, timing, failure, and output
  status after a UI reload. One project can no longer create two concurrent
  HyperFrames renders through the application.
- [ ] **Add explicit export cancellation.** Cancellation remains a separate
  enhancement because it must terminate the complete render process tree and
  remove only that job's temporary video files without risking another export
  or project media.

## Priority 1: Restore a Reproducible Quality Gate

Confirmed gaps:

- The README previously used bare `pytest`, which can traverse ignored temp
  caches. Use an explicit `tests` path and consider adding pytest configuration.
- Current tests mostly mock FFmpeg and dialogs. They validate commands and state
  transitions, not final audiovisual correctness.
- There are no browser-level end-to-end tests for the three primary workflows.
- Caption preview/render parity has no golden-image or fixture-video test.
- The API tests emit a Starlette `TestClient`/`httpx` deprecation warning that
  should be resolved before it becomes a compatibility failure.
- The dated security report has not been refreshed for later changes.

Recommended completion criteria:

1. All 102 Python tests pass from a clean checkout using the explicit `tests`
   path.
2. `npm run typecheck` and `npm run build` pass.
3. One small checked-out or generated fixture validates real FFmpeg output for
   caption, cut, and normalization workflows without committing private media.
4. A browser smoke test covers loading each workspace and one mocked happy path.
5. Dependency audits are rerun and the dated security report is either refreshed
   or retained explicitly as an archived point-in-time report.

## Priority 2: Make Projects and Persistence Coherent

Confirmed gaps:

- The API supports only one active project in process memory.
- Model/compute choices and most workspace state are not persisted globally.
- `.vcg.json` stores an absolute source path and is not portable when media is
  moved.
- The earlier one-folder-per-video design has not been implemented.
- Caption and audio selections are independent process state rather than named
  project assets/settings.
- Background transcription jobs disappear on restart and have no cleanup or
  cancellation model.

Recommended direction:

- Introduce an explicit project root with source reference, transcript, edits,
  settings, logs, and exports.
- Decide whether media is copied into the project or referenced with a
  repairable relative/absolute path.
- Preserve the existing versioned project format and add migrations before
  changing the current version-2 shape; version-1 files remain readable.
- Persist app-level defaults such as Whisper model, compute choice, and output
  conventions.
- Keep single-user/local-only scope, but use project IDs in API routes so tabs
  and future queues do not implicitly share one mutable object.

## Priority 3: Unify Cut and Caption Workflows

Confirmed gaps:

- Rough-cut export and captioned export are separate terminal operations.
- `transcript_remap.py` exists and is tested, but the web export workflow does
  not expose a remapped transcript as the next caption source.
- Caption generation can reuse an uncut active project transcript, but there is
  no integrated cut-and-caption render.
- Caption text cannot be corrected manually before export.

Recommended first integrated flow:

1. Export the adjusted cut.
2. Remap kept word timestamps to the cut timeline.
3. Save the remapped transcript beside the cut.
4. Open that result directly in Caption Generator without retranscription.
5. Add a final “cut and caption” export once the intermediate artifacts are
   inspectable and reliable.

Manual transcript correction should edit display text without changing source
timing/identity unless the user deliberately requests a timing adjustment.

## Priority 4: Move All Long Operations to Jobs

Only transcript generation currently has a background job/status endpoint.
Caption rendering, final cut export, audio analysis, complete rendered-cut
preview creation, and audio normalization are synchronous API calls. The UI can
show a modal, but the HTTP request remains blocked and cannot be cancelled or
resumed.

Recommended job contract:

- queued/running/complete/failed/cancelled states;
- progress value and human-readable stage;
- operation-specific result and log path;
- cancellation that terminates FFmpeg safely;
- bounded job retention and temp cleanup; and
- recovery rules for application restart.

This is more valuable than adding cosmetic progress percentages to synchronous
requests.

## Priority 5: Decide the Desktop and Packaging Story

Confirmed gaps:

- `Start VCG AutoCaption.cmd` launches the old PySide6 app, not the current web
  product.
- The web app requires a developer terminal, Python environment, Node modules,
  and two dev servers.
- The retained Qt UI and web UI can drift because both remain runnable.
- There is no installer, production launcher, WebView shell, auto-update path,
  or explicit migration/deprecation policy for the desktop prototype.

Recommended decision:

- Treat PySide6 as legacy/reference and stop adding product features there.
- Create a Windows launcher for the production-built web UI and local API.
- Open the UI automatically, report startup failures clearly, and shut down
  child processes cleanly.
- Only consider WebView2 or an installer after the production local-launch path
  works reliably from a clean machine.

## Priority 6: UX and Editing Depth

Useful confirmed gaps and refinements:

- No manual caption/transcript text correction.
- No undo/redo history beyond restoring selected deleted tokens.
- No batch processing.
- The transcript editor intentionally remains transcript-first rather than a
  traditional NLE. Product direction has changed for the separate Visual
  Production workflow, which now requires a focused layered timeline for main
  video, generated graphics, imported media, and audio.
- No durable configurable keyboard-shortcut settings in the web UI.
- No multi-project dashboard or recent-project list.
- No explicit stale-source repair flow when a project’s absolute source path
  stops resolving.
- Export progress is indeterminate for some operations.
- Error/support logs are not surfaced as a coherent diagnostics bundle.

These should follow the project/job foundations rather than expand the current
single-process state object further.

## Approved Separate Track: Visual Production

Confirmed foundation already present:

- VCG white-editorial brand tokens and CSS;
- a content-neutral module catalog and visual-plan schema;
- private-project creation outside the Git checkout;
- repository and CI privacy guards;
- a private `$vcg-visual-producer` Codex skill carrying the editorial rules.

Round-one implementation completed in the current working tree:

1. Add a separate Visual Production workspace after cut/audio lock.
2. Persist versioned private visual plans with project-relative asset paths.
3. Implement the five initial generated modules.
4. Add a private imported-media library for external animations and images.
5. Add a layered timeline and inspectors for timing, trim, placement, transform,
   opacity, audio, and transitions.
6. Respect protected source-footage ranges.
7. Add accurate moment/range preview and deterministic local render jobs.
8. Save, reopen, and reproduce a private short acceptance fixture without AI or
   CapCut.

Completed in the working tree on July 14, 2026: per-item review notes and
history, copyable exact handoff prompts, file-backed browser/Codex
synchronization, canvas drag/resize for imported overlays, distinct B-roll and
AI planning lanes, and an honest Ready-versus-Needs-Build generated-treatment
library.

Completed in the working tree on July 20, 2026: fullscreen Visual Production
preview, playhead-driven Inspector selection, docked Next Review with automatic
range playback, reuse-first treatment presentation, and required machine-
readable reuse/B-roll audits in new Cook Visual Plan handoffs.

Follow-up evolution still remains: broader transcript suggestion automation,
additional transition vocabulary, versioned plan migrations, generalized
promotion tooling for successful private experiments, and broader
preview/render parity testing across aspect ratios and imported codecs.

### Canonical Cook and Approval Contract implementation

Completed July 24, 2026 through the existing Approval Contract Three path.
Timed internal changes, intentional holds, computed cadence/count audits,
treatment-bound historical/sample evidence, evidence/safety approval gates,
build-through preservation, fixed Review labels, and regression coverage all
use the single Cook → Review → Approve → Build path. No alternate contract
version, storyboard file, preview application, approval queue, renderer, or
delivery path was added.

The private parent video-project manifest and copyable Codex handoff prompt are
now implemented. A future in-app suggestion engine may replace the copy/paste
handoff, but it must consume the same manifest and preserve the approval gate.

The first Visual Storytelling Assets round is implemented: Creator Library,
checksum deduplication, frozen project copies, structured suggestions, unified
review, Pexels candidates, stock evidence, and credits. Follow-up work includes
direct AI-generator integrations, richer automatic visual-semantic ranking,
and additional providers only if Pexels proves insufficient.

The library must remain extensible: private experiments can invent new
treatments, and only generalized successful patterns are promoted publicly.
Round one does not include full NLE parity, cloud rendering, a large template
marketplace, or processing the published 14-minute video.

## Security and Operational Follow-up

- Preserve the `127.0.0.1` binding and host/origin enforcement.
- Keep API docs disabled in the normal local runtime.
- Re-audit dependencies before a public release, especially after updating
  Next.js, FastAPI, FFmpeg tooling, or GPU packages.
- Add limits/cleanup for uploaded-like request state, job records, frame images,
  previews, and temp media even though the service is local.
- Ensure future logs do not expose transcripts or absolute paths by default
  when users share diagnostics.
- Do not pursue remote hosting without authentication, authorization, storage
  isolation, upload limits, CSRF review, and a redesigned trust model.

## Suggested Improvement Sequence

### Milestone A: Known-good baseline

- Live-test and commit the current five-stage workflow and caption/dialog
  changes.
- Make all automated checks reproducible.
- Add a tiny legal test-media fixture or deterministic generator.
- Verify preview/render parity across common aspect ratios.

### Milestone B: Durable project model

- Define migration and compatibility rules for the existing version-2
  `.vcg.json` schema while preserving version-1 loading.
- Add project-root and source-relink behavior.
- Persist app defaults and output conventions.
- Replace implicit global project routes with explicit project identity.

### Milestone C: Integrated editing output

- Save remapped transcripts from cut export.
- Hand the cut/remapped transcript into Caption Generator.
- Add manual text correction.
- Add combined cut-plus-caption export.

### Milestone D: Robust operations

- Convert all expensive work to cancellable jobs.
- Centralize progress, logs, failure reporting, and temp cleanup.
- Add browser smoke tests and real-media integration tests.

### Milestone E: Usable local release

- Production-build the frontend.
- Add a double-click web-app launcher and health/error UI.
- Document clean install, upgrade, backup, and uninstall behavior.
- Decide whether an installer/WebView wrapper is warranted.

## Deferred Ideas, Not Current Defects

These are optional product expansions rather than unfinished promises:

- hosted/cloud operation;
- accounts or collaboration;
- multi-user or network access;
- a full multi-track timeline;
- mobile support;
- server-side GPU workers; and
- advanced batch queues.

They should not shape the local architecture until the current single-user
workflow is stable and packaged.
