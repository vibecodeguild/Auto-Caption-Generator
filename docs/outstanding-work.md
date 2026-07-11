# Outstanding Work and Improvement Assessment

Last assessed: July 10, 2026.

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

The best next move is stabilization before major new features: settle and test
the current caption-rendering changes, establish a reproducible verification
baseline, make projects/outputs predictable, and then connect cut editing to
caption generation.

## Priority 0: Settle the Current Working Tree

The checkout currently contains uncommitted work affecting:

- caption wrapping and horizontal safe margins;
- browser preview scaling and placement;
- forced H.264/yuv420p/fast-start caption output;
- bundled Montserrat font files and licensing notes; and
- replacement of Tk dialogs with Windows-native dialog helpers.

Before broader improvement work, verify these changes with representative
landscape, portrait, and square media; compare browser preview with rendered
output; run the full suite outside the restricted temp-directory environment;
then either commit the set together or split it into coherent commits.

The working tree additionally contains the first cut-safety tranche: validated
non-overlapping cut ranges, version-2 editor settings, threshold-aware bulk
pause removal, and Audio Boundary Assist with separate Whisper, assisted, and
manual frames on each splice. Analyze Pauses validates only threshold-qualified
Whisper gaps and hides false long pauses; Fine Tune targets only unreviewed cuts
after the transcript edit. Representative production footage remains the
release gate for tuning the shared detector's conservative thresholds.

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

1. All 79 Python tests pass from a clean checkout.
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
  changing the current version-1 shape.
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
Caption rendering, rough-cut export, audio analysis, preview creation, and audio
normalization are synchronous API calls. The UI can show a modal, but the HTTP
request remains blocked and cannot be cancelled or resumed.

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
- No traditional timeline (intentionally out of scope unless product direction
  changes).
- No durable configurable keyboard-shortcut settings in the web UI.
- No multi-project dashboard or recent-project list.
- No explicit stale-source repair flow when a project’s absolute source path
  stops resolving.
- Export progress is indeterminate for some operations.
- Error/support logs are not surfaced as a coherent diagnostics bundle.

These should follow the project/job foundations rather than expand the current
single-process state object further.

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

- Finish and commit the current caption/dialog changes.
- Make all automated checks reproducible.
- Add a tiny legal test-media fixture or deterministic generator.
- Verify preview/render parity across common aspect ratios.

### Milestone B: Durable project model

- Define migration and compatibility rules for the existing version-1
  `.vcg.json` schema.
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
