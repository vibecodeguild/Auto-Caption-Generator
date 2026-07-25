# Visual Storytelling Assets

Status: round-one and approved review-and-sync expansion implemented in the
working tree, July 14, 2026.

This is the implementation contract for expanding Visual Production beyond a
talking head and generated graphics. The objective is to minimize the time from
recording to final video: AI prepares visual opportunities and candidate media;
the creator makes fast decisions; the application performs private downloading,
freezing, placement, provenance tracking, and rendering.

## Approved Editorial Flow

After the cut and audio are locked, **Cook Visual Plan Prompt** asks Codex to
inspect the cut-remapped transcript and footage together and write the private
`visual-production/visual-suggestions.json` file. Suggestions may recommend:

- clean speaker footage;
- protected source footage;
- generated graphics;
- reusable Creator Library footage or callbacks;
- project-specific imported footage;
- Pexels B-roll;
- a new AI-footage generation brief.

Creator Library matches are ranked before generic stock. For every probable
stock moment, the application searches ahead and prepares three to five
lightweight Pexels candidates. Full-resolution media is downloaded only after
the creator selects it. There is no separate approval round before searching.

The Cook handoff includes a required reuse audit and B-roll audit. The reuse
audit records registered modules, proven recipe IDs, and Creator Library queries
that were considered or selected, plus a rationale for each genuinely bespoke
treatment. The B-roll audit records either `planned` with at least one timed
B-roll suggestion, or `not-suitable` with a concrete editorial rationale. This
makes "no B-roll" an explicit decision rather than a missing workflow step.

The
[Canonical Cook and Approval Contract](visual-production-workflow.md#canonical-cook-and-approval-contract---july-24-2026)
controls cadence, treatment duration, terminology, counts, preview evidence,
speaker safety, creator decisions, and build-through identity. This asset
contract extends that one workflow; it does not define an alternate cook or
approval path.

The reuse audit is enforced per graphic, not only once for the whole plan. Each
graphic compares at least three registered module or recipe candidates, records
the selected treatment and visual family, and explains the choice. Consecutive
graphics cannot use the same visual family unless the later item is an explicit
callback. A treatment can appear at most twice before later uses require an
intentional-repeat rationale. This preserves the shared VCG system without
turning one successful card into the default scene for an entire video.

Each graphic also carries a speaker-safety record measured against the locked
footage. The record contains normalized protected speaker bounds, every opaque
region rendered above the speaker, at least three checked scene states, the
speaker mode, and maximum speaker-absence duration. Saving is blocked when an
occlusion region intersects the speaker or when absence exceeds two seconds.
Lower-thirds and centered-bottom treatments receive the same geometry check as
every other layout; their placement is never assumed safe by convention.
The selected treatment and safety record must then be copied into the registered
cue. Review and final rendering remain blocked if the built cue drops that audit
or if an approved graphic exists only as an unregistered planning item.

## Visual Review Queue

The review queue combines graphics, callbacks, stock, AI briefs, protected
footage, and clean-speaker decisions. A suggestion supports:

- approve the proposed treatment;
- select candidate 1-5;
- keep the speaker;
- use a graphic;
- search the Creator Library;
- search Pexels again;
- create a new AI-generation brief;
- reject the treatment;
- move to the previous or next suggestion.

During playback, the Inspector automatically follows the active rendered cue.
The preview can enter fullscreen. The review-note dock owns **Next review** so a
creator can write a note, advance, and immediately watch only the next noted
section without returning to the command bar or timeline.

Approved media is inserted at the proposed timestamp, muted by default, and
remains editable with the existing timing, trim, placement, transform, opacity,
audio, transition, and layer controls.

The July 14 expansion makes suggestions visible on the layered timeline before
media is attached. B-roll and AI-footage briefs use different lane colors and
remain planning items until approved media or a real generated treatment is
built. This visibility is a production checklist, not a claim that an unbuilt
item will render.

Every cue or suggestion may carry one active creator review record. A non-empty
note marks it **Changes requested**; a completed Codex revision marks it **Ready
for review**; **Accept** clears the active marker and appends the full record to
durable accepted history. The note directive is targeted by default, or one of
the mutually exclusive scopes **Leave everything else** and **Replace all of
it**. Copying notes omits every empty item and includes stable IDs and exact
timing so the returned revision can update the same records.

## Private Creator Library

The default library is outside Git at:

```text
%USERPROFILE%/Videos/VCG Creator Library/
```

It contains a versioned `library.json`, reusable AI footage, animations,
images, thumbnails, and metadata. Import offers **Save to Creator Library and
use in this project** or **Use in this project only**. Reusable assets record:

- id, name, description, tags, series/callback, and tone;
- duration, orientation, important action timing, and audio default;
- original generator/provider when known;
- SHA-256 checksum for duplicate detection;
- favorite/archive state;
- usage count, first/last use, and project/timeline history.

Projects receive a frozen copy under `assets/creator-library/` or
`assets/ai-footage/`. Projects never render against a mutable library master.
Replacing a library master cannot change an older project.

The private `recipe-previews/` folder may contain one current PNG, JPG, or WebP
thumbnail named for each reusable recipe ID. The Generated panel uses the most
recent available private production thumbnail on hover and falls back to a
content-neutral illustration when no production thumbnail has been registered.
That fallback is for library browsing only. It is not historical treatment
evidence and cannot approve a scene proposal. Under the canonical contract, a
proposed graphic without appropriate historical evidence requires exactly one
representative sample frame beside its actual scene source frame.

## Pexels Version One

Pexels is the only stock provider in this round. Its API key is stored in local
application settings or supplied through `PEXELS_API_KEY`; it is never written
to a project, plan, log, or public repository.

Each structured B-roll brief carries literal queries, metaphorical queries,
avoid terms, narrative purpose, timing, and desired duration. Candidate ranking
prefers relevance, landscape orientation, sufficient duration/resolution, crop
flexibility, visual stability, variety, and low trademark/sensitive-use risk.

Selected stock is frozen under `assets/stock/videos/`. A private ledger records
provider asset id, creator, asset page, download URL and time, license name and
URL, license evidence, local filename, SHA-256, project usage, placement, and
suggested attribution. Stock audio is muted by default. The application can
generate paste-ready credits.

## Private Project Files

```text
assets/
  ai-footage/
  creator-library/
  generated/
  imported/
  stock/videos/
  stock/thumbnails/
  stock/licenses/
visual-production/
  visual-suggestions.json
  visual-plan.json
  stock-assets.json
previews/visual/
exports/final-video.mp4
```

Active review records and accepted review history are stored inside
`visual-plan.json`, preventing a second review-state file from drifting away
from the timeline. All footage, queries, thumbnails, suggestions, licenses,
decisions, and renders are private. Only content-neutral contracts and
implementation code may enter the public repository.

## Suggestion Contract

Statuses are `proposed`, `prepared`, `approved`, `rejected`, `built`, and
`needs-alternatives`. Every suggestion contains exact start/end timing,
transcript context, category, editorial purpose, confidence, protected-footage
conflicts, and the appropriate module parameters, library query, stock brief,
or AI-generation brief. An optional timeline-lane value may identify graphics,
B-roll, or AI footage explicitly; older suggestions infer the lane from their
category. New Cook handoffs also write top-level `coverage.reuseAudit` and
`coverage.bRollAudit`; the field remains optional when reopening legacy
suggestion files.

## Implementation Order

1. Shared asset records, checksums, frozen project copies, and provenance.
2. Private Creator Library import, search, metadata, and callback history.
3. Structured Visual Suggestions Inbox and upgraded Codex handoff.
4. Pexels API configuration, search, ranking, previews, download, and evidence.
5. Unified review, keyboard controls, automatic timeline placement, credits,
   review renders, and preview/render parity.

## Excluded

- paid or aggregated stock providers;
- automatic purchasing or publishing;
- automatic footage selection without approval;
- direct Grok, Gemini, or Sora generation APIs;
- stock music licensing;
- cloud storage;
- using stock media for model training.

## Acceptance Criteria

1. Downloads footage can be imported once and saved as a reusable private asset.
2. Duplicate imports are detected by checksum.
3. Creator assets are searchable across projects with usage/callback history.
4. Cook Visual Plan produces structured graphics, callback, B-roll, and AI briefs.
5. Each B-roll suggestion prepares three to five Pexels candidates.
6. The creator can select, reject, search again, change treatment, or keep speaker.
7. Selected media is privately frozen and added muted at the proposed time.
8. Every placement remains editable and reproducible.
9. License, attribution, source, timestamp, and checksum evidence is retained.
10. Review and final renders reproduce the approved plan.
11. Privacy/history checks pass and legacy projects remain functional.
12. Playback selects the active cue, fullscreen preview works, and Next review
    plays exactly the selected note range.
13. Every new Cook handoff records reuse and B-roll audits, even when no B-roll
    is editorially appropriate.
14. Every planned graphic compares at least three library treatments, records a
    visual family, and passes normalized speaker-occlusion checks before save.
