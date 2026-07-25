# Visual Production Integrity Audit

Status: findings only. Every remediation in this document is **proposed** and has
not been approved or implemented. Audit performed against the working tree on
July 25, 2026.

Scope: the pipeline from Transcript Edit Stage 5 (export the cut) through Visual
Production final export. This document records what the code actually does, not
what the contract documents say it does. Where the two disagree, the code is
recorded as authoritative and the disagreement is logged.

Method: direct reading of `app/web_api.py`, `app/core/video_project.py`,
`app/core/story_assets.py`, `app/core/visual_production.py`,
`scripts/promote_frozen_visual_revision.py`, `web/app/visual-production.tsx`,
`web/lib/api.ts`, the two JSON schemas, and the test suite. Claims below carry
file and line references so each can be re-verified independently.

## Root cause

Stage 1 through Stage 5 are implemented as software: deterministic functions,
persisted artifacts, and revision stamps. Everything after Stage 5 is
implemented as a prose contract delivered to an external language model through
a clipboard.

The transition point is `build_visual_plan_prompt`
(`app/core/video_project.py:378`), which renders roughly 4,500 words of rules
into a string. The operator pastes that string into an external agent. That
agent then writes `visual-suggestions.json` directly to disk with a file write.
There is no API, no schema enforcement at the boundary, and no state machine.

Every integrity problem below follows from that one boundary choice. The rules
exist in four independent copies -- the workflow document, the generated prompt,
the JSON schemas, and the Python validators -- with no mechanism keeping them in
sync. Copies drift, and they drift permissively, because a copy that is too
strict breaks a run immediately and gets corrected while a copy that is too
loose passes silently.

## Findings

### F1. Contract enforcement is opt-in, and the authoring agent selects the option

Severity: blocker.

Every approval gate is guarded by a field that the authoring agent writes into
the file being validated.

| Condition written by the agent | Consequence | Evidence |
| --- | --- | --- |
| `coverage` key absent | All suggestion validation skipped | `story_assets.py:509`, `:545` |
| `coverage.reuseAudit.reviewed` is false | Graphic contract validation skipped | `story_assets.py:545` |
| `contractVersion` is not 3 | Approval contract validation skipped | `story_assets.py:552` |
| `contractVersion` is not 3 | App stops computing counts and cadence; agent-supplied numbers are trusted | `story_assets.py:343` |
| `contractVersion` is not 3 | Export planning gate returns no issues | `visual_production.py:1084` |
| `contractVersion` is not in {2, 3} | Export speaker-safety gate returns no issues | `visual_production.py:1021` |
| `visual-suggestions.json` does not exist | Both export gates return no issues | `visual_production.py:1014`, `:1077` |

The final row is the widest hole. Writing cues directly into `visual-plan.json`
without ever creating a suggestions file reduces `can_deliver`
(`visual_production.py:1208`) to three checks: semantic items anchored, no
composition-root overflow suppression, and no open review notes. Approval,
evidence, speaker safety, cadence, and runtime coverage are all skipped.

Proposed fix: remove every early return listed above. Absence of a suggestions
file, of a coverage block, or of a contract version must be a hard failure, not
a pass. Retain a single explicit migration path for pre-existing projects rather
than an implicit one keyed on a field the agent controls.

### F2. The JSON schemas are never executed

Severity: blocker.

`jsonschema` is not listed in `requirements.txt` and is not imported anywhere in
the codebase. `visual-production/schemas/visual-suggestions.schema.json` and
`visual-plan.schema.json` are read only to be interpolated into the generated
prompt (`video_project.py:410`, `:412`).

The suggestions schema is also materially weaker than the prose contract. The
required set for a suggestion is `id`, `status`, `category`, `startSec`,
`endSec`, `editorialPurpose` (`visual-suggestions.schema.json:59`).
`scenePacket`, `speakerSafety`, `approvalEvidence`, `rankedCandidates`,
`decision`, and `meaningfulChanges` are all optional. The `items` object does
not set `additionalProperties: false`, so invented fields validate.

Proposed fix: add `jsonschema` as a dependency and validate both documents on
every read and write. Promote the prose-required fields into `required` and set
`additionalProperties: false`.

### F3. Regression tests assert the text of the schema, not the behavior of the system

Severity: high.

`tests/test_visual_production_contract.py` asserts that the schema file contains
certain keys and constants -- for example that `candidateTreatmentIds.minItems`
equals 3 (`:69`) and that `cadenceAudit.maxAllowedGapSec.const` equals 5
(`:95`). No test in that file validates a document against the schema.

This is the artifact that permits the claim in
`docs/visual-production-workflow.md:288` that "schema, prompt, backend, UI, and
regression coverage enforce the contract." The schema does not enforce, and the
coverage tests do not exercise enforcement.

Proposed fix: replace schema-introspection assertions with round-trip fixtures
-- a known-good document that must validate, and a set of known-bad documents
that must each be rejected for a named reason.

### F4. `promote_frozen_visual_revision.py` is a parallel delivery path that writes the gates as passed

Severity: blocker.

`scripts/promote_frozen_visual_revision.py` accepts an externally produced MP4
plus `storyboard.json` and `timing-ledger.json` -- a planning format with no
schema anywhere in this repository -- and:

- replaces all cues and custom compositions wholesale (`:183`, `:184`);
- clears active review notes (`:185`) and revision history (`:223`);
- writes `productionGates.representativeApproval`,
  `fullReviewApproval`, and `layoutInspection` with `status: "passed"`, stamped
  with a matching plan hash (`:224`-`:236`);
- copies the supplied master to `exports/final-video.mp4`, bypassing
  `render_visual_plan`, the locked-cut audio remux, `verify_delivered_media`,
  and the delivery manifest;
- never reads or updates `visual-suggestions.json`, so Cook, Review, and
  Approval are skipped entirely.

The `--skip-production-checks` flag is documented as "Migration tests only; do
not use for production promotion" (`:266`). Nothing enforces that. With the flag
set, `layoutInspection` is still recorded as passed, with the literal command
list `["legacy-approved-render"]` (`:208`).

`docs/visual-production-workflow.md:70` forbids exactly this: "Do not create an
alternate storyboard, disconnected HyperFrames project, second approval queue,
or parallel delivery state." The script does all four.

`tests/test_visual_production.py:348` asserts `report["canDeliver"] is True` for
this path, which regression-locks the bypass as intended behavior.

Proposed fix: decide whether this script is a one-time migration tool or a
supported path. If migration only, remove it from the working tree and delete
the test that certifies its output as deliverable. If supported, it must be
unable to write `productionGates` and must route through the same verification
and manifest code as `render_visual_plan`.

### F5. Asset cues can never satisfy the planning gate, deadlocking B-roll and imports

Severity: blocker.

Three functions create cues, and only one attaches the approval linkage that the
export gate requires.

| Function | Cue kind | Sets `planningSuggestionId` |
| --- | --- | --- |
| `build_nonmedia_suggestion` (`story_assets.py:1315`) | module | Yes (`:1363`) |
| `freeze_creator_asset` (`story_assets.py:267`) | asset | No |
| `select_pexels_candidate` (`story_assets.py:1447`) | asset | No |
| `import_visual_asset` (`visual_production.py:607`) | asset | No |

The latter three build their cue through `_asset_cue`
(`story_assets.py:1501`), whose parameter dictionary contains only geometry and
playback fields.

`visual_planning_gate_issues` (`visual_production.py:1116`-`1122`) skips
disabled cues and cues whose `moduleId` is `source-footage-hold`, then requires
`parameters.planningSuggestionId` to name an approved suggestion. An asset cue
has no `moduleId`, so it is not skipped, and its `planningSuggestionId` is
absent.

Under `contractVersion: 3`, every Creator Library asset, every Pexels B-roll
clip, and every imported animation therefore produces "is not backed by an
approved scene selection" and there is no code path that can satisfy it.
`canDeliver` becomes false permanently. The only available escape is lowering
the contract version, which disables the entire contract per F1.

This is a hard conflict between two features that the workflow document requires
to be used together.

Proposed fix: either propagate `planningSuggestionId` through `_asset_cue` from
the originating suggestion, or exempt `kind == "asset"` from the planning gate
and verify asset provenance separately. The first preserves traceability and is
preferred.

### F6. The review-render stage is unreachable from the application

Severity: high.

`approveVisualRepresentative` and `approveVisualFullReview` are exported from
`web/lib/api.ts:1176` and `:1180` but are never imported or called anywhere in
`web/app/`. `startVisualRender` is called exactly once, at
`web/app/visual-production.tsx:1046`, always with `purpose: "final"`.

Consequently `productionGates.representativeApproval` can never be set through
the UI, `canRenderReview` (`visual_production.py:1207`) is permanently false,
and the `range` and `review` branches of `POST /api/visual/render` are
unreachable. The "Review the live registered composition" step described at
`docs/visual-production-workflow.md:66` has no control surface.

Proposed fix: either restore the review-render controls or remove the
unreachable branches, the two dead API helpers, and the corresponding
documentation. Leaving them in place makes the documented workflow untestable.

### F7. Build silently substitutes a generic module

Severity: high.

`build_nonmedia_suggestion` contains:

```python
if module_id not in registered_modules:
    module_id = "speaker-side-panel"
```

at `story_assets.py:1340`-`1341`. An unregistered, misplaced, or fabricated
treatment identifier is silently replaced with a generic side panel.

There is a guard one line earlier for the case where `recipeId` is set and
`moduleId` is not (`:1335`-`:1339`), but it does not cover a recipe identifier
placed in the `moduleId` field. That arrangement passes validation, because
`_validate_graphic_suggestion_contract` (`:570`-`:575`) checks the selected
identifier against the union of module and recipe identifiers without checking
that the field matches the kind.

This directly contradicts the generated prompt (`video_project.py:427`,
`:437`) and `docs/visual-production-workflow.md:801`, both of which prohibit
silent substitution.

Proposed fix: raise instead of substituting, and validate that `moduleId`
contains a module identifier and `recipeId` contains a recipe identifier.

### F8. Nothing binds the visual plan to the locked cut it was authored against

Severity: blocker.

- The plan records no checksum of the locked cut
  (`visual_production.py:286`).
- `composition.durationSec` is probed once at plan creation and never
  re-checked. `validate_visual_plan` (`:440`) validates cue timing against the
  stored duration, not the actual media (`:483`).
- `sequenceRevision` increments only in `build_source_sequence`
  (`video_project.py:225`), that is, only when raw source clips are added,
  reordered, or removed. Re-cutting the transcript does not increment it.
- `POST /api/visual/ensure` checks `artifact_current(manifest,
  "lockedCutRevision")` only on the branch that creates a plan
  (`web_api.py:1601`). When the plan already exists it is loaded without any
  freshness check (`web_api.py:1597`-`1598`).

Re-cutting the transcript after Visual Production has started therefore produces
a new locked cut with a different duration while every existing cue keeps its
old timing, and the cadence audit is computed against a stale runtime
(`story_assets.py:346`). No warning is produced at any point.

Related: `export_cut` writes to `payload.output_path` when supplied
(`web_api.py:1220`-`1221`), but `_save_final_transcript` stamps
`lockedCutRevision` as current regardless (`web_api.py:2521`). The manifest can
therefore report a current locked cut at a path that was never written.

Proposed fix: store a SHA-256 of the locked cut in the plan at creation and
verify it on every open, render, and export. Add a `visualPlanRevision` artifact
key and invalidate it whenever a new locked cut is written.

### F9. The generated prompt has already drifted from the catalog

Severity: high.

`video_project.py:427` instructs the model that `numbered-step-intro` is "the
locked first-choice family" for the intent "Example number ___".

`visual-production/recipes/catalog.json` records `numbered-step-intro` with
`"lockedDefault": false` and `"supersededBy": "numbered-example-card"`. The
actual locked default for that intent is `numbered-example-card`, with
`"lockedDefault": true` and `"creatorRating": 5`.

The prompt is a Python f-string whose exact phrasing is pinned by substring
assertions in `tests/test_video_project.py:50`-`70`. The catalog can therefore
be updated freely while the prompt drifts, and the test suite defends the stale
text.

This is the concrete instance of the four-copy drift described under Root cause.

Proposed fix: generate the reuse and ranking section of the prompt from the
catalog at request time rather than hand-writing it, and replace exact-substring
tests with tests that assert the prompt agrees with the catalog.

### F10. Most of the treatment catalog cannot be rendered

Severity: high.

The catalog contains 6 registered modules (`visual_production.py:22`-`29`) and
34 recipes. Recipes carry metadata only; no renderer exists for them.

`prepare_suggestion_approval_evidence` raises for a recipe with no historical
render and no registered renderer (`story_assets.py:1120`-`1126`), and
`build_nonmedia_suggestion` raises when an approved recipe has no registered
composition (`:1335`-`:1339`). Both messages are correct and deliberate.

The consequence is structural rather than incidental. The Scene Selector is
required to rank at least three candidates per graphic from a catalog that is
approximately 85 percent unbuildable. The documented resolution is for the
authoring agent to hand-produce a bespoke HyperFrames composition, but there is
no API and no UI that registers one -- `customCompositions` is written only by
hand-editing the plan file or by the promotion script in F4. This is the largest
single driver of unstructured agent authorship in the pipeline.

Proposed fix: this requires a product decision, recorded below under Open
decisions.

### F11. The governing agent skill is untracked and incomplete

Severity: high.

`docs/visual-production-workflow.md:331` and `docs/outstanding-work.md:231`
describe a private `$vcg-visual-producer` skill that carries the editorial
rules. `.codex/` and `.agents/` in this repository are empty directories.

The only copy present in the working tree is at `app/temp/vcg-skill-update/`,
inside a gitignored scratch directory. It contains `SKILL.md` and three
reference documents. `SKILL.md:18` instructs the agent to read
`references/animation-library.md`, which does not exist.

The document that governs the entire Visual Production process is therefore
untracked, unreviewable, unversioned against the code it governs, and missing
one of the four references it declares.

Proposed fix: move the skill under version control, restore or remove the
missing reference, and add a test that every file referenced by `SKILL.md`
exists.

### F12. The workflow document is five stacked contracts

Severity: high.

`docs/visual-production-workflow.md` is 834 lines containing, in order:
"Canonical Cook and Approval Contract - July 24", "Canonical Revision and
Production Contract - July 16", "Direct Final Export Contract - July 20",
"Approved Review and Sync Expansion - July 14", and "Approval contract three".
Each partially supersedes the others in prose. Lines 20 through 25 add a
conflict-resolution clause declaring which section controls, which is itself an
acknowledgement that the document contradicts itself.

A reader following the document in good faith can cite support for materially
different behaviors.

Separately, the API inventory in `docs/current-system.md:402`-`456` omits every
`/api/visual/*` and `/api/video-project/*` route, approximately 40 endpoints.

Proposed fix: collapse the superseded sections into a single current contract
with a separate, clearly-labeled history appendix. Regenerate the API inventory
from the route table rather than maintaining it by hand.

## Contradiction register

Recorded so that each can be resolved deliberately rather than rediscovered.

| Rule as stated | Where stated | What the code does |
| --- | --- | --- |
| No silent substitution of a treatment | `video_project.py:427`, `workflow.md:801` | Substitutes `speaker-side-panel` (`story_assets.py:1340`) |
| `numbered-step-intro` is the locked default | `video_project.py:427` | Superseded by `numbered-example-card` in the catalog |
| No alternate storyboard or parallel delivery state | `workflow.md:70` | `promote_frozen_visual_revision.py` creates both |
| Schema and regression coverage enforce the contract | `workflow.md:288` | Schemas are never executed; tests assert schema text |
| Full-frame graphic treatment policy | `internal/brand/visual-identity.md` (private, gitignored) | `brief-full-frame-hit` is a valid mode (`story_assets.py:283`); `workflow.md:220` permits a two-second hit |
| Overlay geometry must be verified against the reference host frame | `internal/brand/visual-identity.md` (private, gitignored) | No code reads that file or the reference frame |
| Review the live composition before final export | `workflow.md:66` | Review render is unreachable (F6) |

The last three involve private brand material held outside this repository. The
substance of those rules is deliberately not reproduced here; only the existence
of the conflict is recorded.

## Duplicate implementations

Recorded for consolidation, lower priority than the findings above.

- Two visual-project creation paths: `create_visual_project`
  (`visual_production.py:194`) and `create_visual_plan_in_video_project`
  (`:255`), exposed as `/api/visual/create-dialog` and `/api/visual/ensure`.
  The former self-delegates to the latter when a parent project is open
  (`web_api.py:1560`).
- Two speaker-safety validators with identical rules and different reporting
  styles: `story_assets._validate_speaker_safety` (`:739`) and
  `visual_production._speaker_safety_metadata_issues` (`:1126`).
- Two approval-evidence resolvers that can disagree: `_refresh_approval_evidence`
  (`story_assets.py:458`) derives status on every read and can silently
  downgrade to `sample-required`, invalidating an approval that
  `_validate_approval_contract` (`:719`) then rejects.
- Two render-job stores: in-memory `state.visual_render_jobs` and on-disk
  `render-job.json` (`web_api.py:239`). `/api/visual/render/active` reconciles
  both; `/api/visual/render/jobs/{id}` reads only memory, so a known job
  identifier returns 404 after a restart while `/active` still reports it.
- `sha256_file` is defined twice (`visual_production.py:716`,
  `story_assets.py:1509`); `_is_within` twice (`video_project.py:64`,
  `visual_production.py:74`); a slug helper three times
  (`video_project.py:59`, `visual_production.py:69`, `story_assets.py:1517`).
- `captionedCut` and `captionedCutRevision` are declared
  (`video_project.py:27`, `:360`) but never written, making that branch of
  `preferred_stage_source` unreachable.

## Proposed remediation sequence

Not approved. Ordered so that each step leaves the tree in a working state.

1. Add `jsonschema`, tighten both schemas, and validate on every read and write
   (F2). Replace schema-introspection tests with round-trip fixtures (F3).
2. Fix the asset-cue linkage (F5) before removing the opt-outs, so that closing
   the escape hatches does not immediately deadlock every project that uses
   B-roll.
3. Remove the enforcement opt-outs (F1) and the silent substitution (F7).
4. Bind the plan to the locked cut by checksum and add a visual plan revision
   artifact (F8).
5. Generate the catalog-dependent portion of the prompt from the catalog (F9).
6. Resolve `promote_frozen_visual_revision.py` (F4) and the unreachable review
   stage (F6).
7. Bring the agent skill under version control (F11) and collapse the workflow
   document (F12).

## Open decisions

These require a product decision and are recorded rather than assumed.

1. **Unbuildable recipes.** Should recipes without a renderer be selectable
   during Cook? Blocking them makes planning honest and narrows the available
   vocabulary sharply. Permitting them is what places the authoring agent into
   unbounded bespoke composition work with no schema, which appears to be the
   principal source of unstructured output. A third option is to permit
   selection but require the bespoke composition to be registered through a new
   API before the suggestion can be approved.

2. **Full-frame treatments.** The private brand material and the public workflow
   contract disagree on whether a graphic may take the full frame. The code
   currently implements the permissive reading. Whichever is correct, one of the
   two documents needs to be corrected, and if the restrictive reading wins,
   `brief-full-frame-hit` should be removed from the valid speaker modes rather
   than left as an unused option.

3. **Host geometry validation.** The private brand material specifies fixed
   overlay safe zones and requires visual verification against a reference
   frame. No code implements either. If these are still binding, they should
   become validated constraints measured against actual speaker bounds rather
   than prose.

## Not verified

Recorded so that absence of a finding is not read as a clean result.

- No end-to-end run was performed against real creator media. All findings are
  from static reading of the working tree.
- The HyperFrames renderer itself, its lint, validate, and strict inspect
  behavior, was not audited.
- Audio normalization correctness and the delivery manifest packet-identity
  verification were read but not exercised.
- The transcript, caption, and audio workflows before Stage 5 were reviewed only
  where they produce inputs to Visual Production.
