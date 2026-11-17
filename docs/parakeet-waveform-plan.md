# Parakeet and waveform boundary review

Approved in discussion November 17, 2026. Implemented and verified as described
below. Waveform layout received live browser verification during the follow-up.

## Product contract

- One shared transcription service, used by every workflow. Parakeet is the
  application-wide default for new transcription; Whisper remains explicitly
  selectable. Never fall back between engines silently.
- Prefer NVIDIA GPU for Parakeet. If GPU execution fails, retry on CPU and
  report the actual device and reason in existing status/log surfaces.
- Support long-form recordings without a three-minute cap. Bound inference
  memory and preserve source offsets and repeated speech across chunks.
- Preserve original model timing, assisted cut anchors, and manual adjustments
  separately. Inspect model token durations before choosing a word-end
  conversion. Initial decision: the other application's fixed 80 ms padding was
  not approved. **Superseded by the timing decision below.**
- Preserve existing OUT assistance. Add conservative leading-silence trimming
  at unreviewed IN boundaries; moving IN earlier remains manual. Preserve quiet
  opening sounds and all cut-plan validation.
- Start (IN only) and End (OUT only) participate in boundary navigation, review,
  and Fine Tune. Retain exact-frame and playhead endpoint adjustment. This
  supersedes the separate final-endpoint product surface; its saved values and
  capabilities must survive the transition.
- Add visual-only waveforms at the existing Stage 3/4 boundary controls.
  No word labels, click/drag editing, or audio-only auditions. Retain frame
  nudges and existing 2/4/6-second auditions and Loop.
- Waveforms are independent of transcription and cached by source identity.
- Preserve Stage 3 source preview and Stage 4 rendered review. No new video
  proxies or changes to playback architecture.
- No backfill or migration work for completed projects. Preserve loading
  compatibility and existing endpoint adjustments.

## Sequence and acceptance

1. Validate isolated GPU runtime, actual device evidence, token durations, and
   CPU fallback on local audio before promoting a runtime/model combination.
2. Centralize engine routing, defaults, provenance, long-form processing, and
   device reporting. Keep the existing Whisper path usable.
3. Add boundary analysis and Start/End state using the existing edit model.
4. Add cached waveform data and visual-only displays in existing review panels.
5. Test timing/long-form seams and repeated speech, rollback, manual-boundary
   preservation, cut safety, endpoint persistence, waveform invalidation, and
   relevant API behavior. Run Python tests, TypeScript checks, web tests, and
   production build. Review final diff and documentation for scope drift.

Do not start, stop, or restart application servers during implementation.

## Validation findings — November 17, 2026

- Installed sherpa-onnx 2.0.1+cuda12.cudnn9 and isolated CUDA libraries. Verified
  executed CUDA kernels on the RTX 5070 Ti; the public model clip produced 17
  words on CUDA without fallback. Merely requesting CUDA was insufficient: an
  initial probe silently fell back because cuFFT was missing.
- The 190-second real-audio sample completed on CPU with 251 words across seven
  chunks. A GPU run produced zero-duration words; full-recording CPU fallback
  completed the same sample and reported the timing-validation reason.
- Full 31-minute validation exposed a word whose token duration extended across
  roughly nine seconds of silence. Treating native token durations as phonetic
  word lengths is therefore unsuitable. This also prevents reliable overlap
  reconciliation. No fixed padding or alternative alignment rule has been
  promoted into production behavior.
- Initial pending decision (now superseded): last-token + 80 ms initial estimates with existing review,
  or an additional word-alignment pass. Fine Tune remains a cut-anchor tool and
  does not repair every transcript word.
- Waveform, Start/End, IN assistance, manual-boundary preservation, persistence,
  and cut-safety tests pass. Production build and existing web playback tests
  pass. The full Python suite currently has three pre-existing export-test
  failures, reproduced against the committed API implementation; the remaining
  504 tests passed before the latest timing/fallback test additions.
- No application servers were started, stopped, or restarted. Local validation
  artifacts are under ignored `app/temp/`; published projects were read only.

## Timing decision approved after validation

The user explicitly approved last-token + 80 ms initial word-ending estimates,
capped at the next word's start or audio end, with existing Fine Tune and
waveform review. This supersedes the initial withholding of approval above.
Punctuation stays in text but does not extend acoustic word timing: delayed
punctuation emission otherwise stretched one word through nine seconds of
silence. Ends use the final lexical token. Co-timed words that cannot produce
positive intervals fail validation rather than being silently dropped or given
invented finer timing; GPU timing failures retry the complete recording on CPU.
These remain estimates, not phonetic
alignment. Raw tokens, timestamps, and decoder durations remain preserved.

## Final verification

- A 1,904-second recording completed on verified CUDA without fallback: 2,725
  words, 69 overlapping chunks, approximately 6.4 seconds for loading/device
  verification and 82 seconds for decoding (89 seconds total). All published
  word intervals are finite, positive, and ordered. Sample edit decisions plus
  IN/OUT assistance also passed cut-plan validation on this transcript.
- CPU decoding of the same full recording took approximately 77 seconds and
  produced 2,733 words. Word-sequence similarity was 98.2%; CPU/GPU output is
  not bit-identical. These are single-run observations. The quantized graph
  executes both CUDA and CPU nodes; GPU was not faster in these runs. NVIDIA
  remains the requested default; slower execution does not trigger fallback.
- The 190-second excerpt exercised actual whole-recording CPU fallback when
  GPU word estimates could not satisfy the positive-interval invariant. It
  completed with 247 words and a visible timing-validation reason. No engine
  substitution or silent word removal occurred.
- Whisper `base.en` rollback transcribed the public sample offline (17 words).
- Real-media waveform generation took about 2.2 seconds, with a subsequent
  visible-window cache read around 0.05 seconds. No ASR was required.
- Final full Python suite: 508 passed, three pre-existing asynchronous-export
  tests failed. Those same failures were reproduced using the committed API.
  TypeScript typecheck, three web playback tests, production build, dependency
  consistency, and diff whitespace checks passed.
- Existing preview architecture and 2/4/6-second auditions are retained. The
  existing monitor now also accepts single-sided Start/End audition segments.
  No live browser verification is claimed; no application server was operated.

## Follow-up layout correction — November 17, 2026

The user reported clipped frame-nudge controls. Live layout measurements found
cards compressed to about 84 pixels despite 230 pixels of content. Intrinsic
content-sized grid rows and card minimum heights now keep the nudge rows inside
each card; the existing review-panel scrollbar handles smaller viewports.
This changes layout only, preserving nudge callbacks and cut safety checks.

The user also removed the need for the Original/Assisted/Current legend text
and ±1/2/4-second context buttons. This supersedes those parts of the approved
mockup. Waveforms retain fixed ±1-second context and boundary markers, with no
new playback controls or changes to 2/4/6-second auditions.

The user subsequently requested one pink current-boundary marker only. This
supersedes displaying original/assisted markers; their underlying timing records
remain unchanged. The decorative horizontal reference line is also removed.

Additional approved refinement: Previous / Needs review / Next share the same
row as playback, labeled Prev / checkmark Accpt / Next. Review toggling and
advance behavior are preserved; tooltips explain the action on reviewed items.
The redundant Splice Review eyebrow is removed; the boundary count remains.
The single pink marker is thicker for visibility (six canvas pixels, about
three display pixels at the sidebar's normal width). Browser measurements at
900 pixels tall confirmed both six-button nudge rows fully inside their cards
and panel, with the combined toolbar fitting horizontally. TypeScript,
production build, and the existing three playback tests passed for this slice.
