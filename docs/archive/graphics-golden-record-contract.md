# Graphics Golden Record Contract

Status: **Phase A + A.1 implemented.** **Treatments-as-menu superseded** (fold into Golden Record — approved 2026-07-31).  
Purpose: one private, per-user **Graphics Library** (Golden Record) as the only production menu for graphics, with a published app UI any repo user can point at their own library.

Related: Creator Library (`story_assets.py`) for **footage/assets only**, Visual Production **modules** (render implementations only), `docs/vcg-editorial-production-contract.md`.

---

## 1. Product goal

Ship a **Graphics Library / Golden Record** so a creator can:

1. Maintain **every** graphic they might use in production (candidates through golden/rejected).
2. Inspect **producer metadata** + a **short sample clip** (typically 8–15s, max 20s) on real talking-head or screen-share footage.
3. Promote, reject, or supersede until **episode production (locked cut → final export) uses only what they trust**.

**Public product:** the UI, schema, APIs, privacy rules, and empty/setup states.  
**Private content:** each user’s catalog entries, sample media, posters, notes, ratings, and demo source receipts.

Anyone who clones the repo can connect **their own** golden record. The published app must not ship VCG (or any channel’s) private examples, face footage, or approved lists.

**Done means (end state):**

- creator manages available graphics **only** in Graphics Library;
- modules are **render contracts only** (not a second menu);
- **treatments / daily treatment kits are not a parallel selection path**;
- cook/plan may select only production-eligible GR ids (default: `status: golden`);
- no private media in git.

**Not the goal:**

- embedding one channel’s library in the public repo;
- letting HyperFrames native skills define production vocabulary;
- auto-marking every registered module as golden;
- full-length episode re-renders as the review surface;
- a second Cook / Codex creative loop inside this UI;
- a second “treatments” product that can disagree with Golden Record.

---

## 2. Authority model (approved vernacular — 2026-08-01)

Product language going forward. **Do not** invent parallel menus or a second draw stack.

| Layer | Authority | Notes |
| --- | --- | --- |
| **Usage** (Graphics Library entry) | Creator — **when / where** a graphic may be used | Beat types, allowed layouts, status (`candidate` / `golden`), sample, poster, notes. **Not** a second parameter schema. |
| **Engine** | Application code — **draw / render only** | One purpose, one input interface. Creates the graphic given content + (when needed) timing channels for internal reveals. |
| **Placement** | Episode / visual package workflow (later) | Puts a **usage** on a specific locked cut: instance copy, timing, word/bullet sync values. Not the library contract. |
| HyperFrames native skills | Motion primitives only | **Not** the library; must not invent production usage ids |
| Seed kit / treatments / daily kits as menus | **Superseded / destroy** | Codex dual stacks. Selection = library usages with `status: golden` only. |

**One-line contract:** Engine draws. Usage says when/where. Placement puts it on a video.

### 2.1 Terms (binding)

| Term | Meaning |
| --- | --- |
| **Engine** | Draw/render implementation. Owns the **draw interface** (content + declared timing **channels** it can animate). Product word: **engine** — never “module,” never “seed.” |
| **Usage** | Graphics Library shelf entry: **when/where** policy + proof + status. **Has-a engine** (`engineId` reference) — **not** identity-coupled to the engine. Own usage `id`. Stays thin. |
| **Placement** | One instance of a usage on a real video (later). Instance content, timing values, span on the cut. |
| **Assignment** | Later job after Masterbeater: match beats → eligible **usages** (`status: golden` + beat types + layouts + variety). Not Masterbeater; not the engine. |
| **Graphics Library** | Collection of **usages** (each referencing an engine). The product UI we are building. |
| **`golden` / `candidate`** | **Status on a usage only.** Production set = usages with `status === golden`. Do not name the product “golden record.” |
| Legacy code words | module→**engine**, library entry/GR→**usage**, treatment menu→**superseded**, seed→**destroy**. Old `implementationId` was seed/alias mess — superseded by clean **usage → engineId**. |

### 2.1a Composition (approved — not identity-coupled)

```text
Usage  ──engineId──►  Engine.draw(content, timingChannels)
   ▲
   │ usageId
Placement (later)
Assignment (later): Beats × golden Usages → proposed usage per beat
```

- **v1 seeding** may set `usage.id` equal to `engineId` for convenience; that is **not** a permanent law.
- Multiple usages may eventually share one engine with different when/where rules.
- Do not reintroduce seed aliases or a second draw stack.

### 2.1b Engine interface vs placement vs usage

| Engine owns | Placement owns (later) | Usage owns |
| --- | --- | --- |
| How to **draw** (geometry fixed by design) | Which usage is on this beat (after assignment) | `engineId`, beat types, allowed layouts |
| **Content** fields of the draw interface | Concrete copy / rows / labels for this cut | Sample + poster paths (proof only) |
| **Declared timing channels** only (e.g. bullet reveals, word hits) — not every timeline concept | Actual times/words for this voice track; span on cut | `candidate` / `golden`, display name, notes, rating |
| | | **Not** a stored parameter schema |

**Timing (approved):** Engine accepts the timing channels it knows how to animate. Placement supplies values. Usage does not store instance timing.

**Layouts (approved creator responsibility):** Engine draws in a designed screen region. Creator sets **allowed layouts** on the usage so only scenes where that draw looks good are eligible. A bad on-face result from a wrong layout is a **usage contract** mistake, not an engine “speaker safety” parameter system.

**Sample (approved):** Built with the **exact production engine** — no parallel sample renderer. Sample is mini-placement proof stored on the usage.

**Library UI parameters:** Live **passthrough** of the engine interface only — never a second schema on the usage.

**Usage stays thin (approved):** No default episode copy, no motion profiles as selection glue, no AI scores, no instance timing templates. When/where + proof + status + engine reference.

**Placement (explicitly later):** Episode complexity lives there. Future work; do not pre-stuff it onto usage.

### 2.1c Superseded names (do not reintroduce in product copy)

| Avoid | Use |
| --- | --- |
| module (product) | engine |
| golden record / GR | graphics library / usage |
| treatment (menu / third contract) | usage or placement |
| seed / seed-kit | deleted |
| “select the golden record” | select usages with status golden |

### 2.2 Superseded: Phase B as optional “maybe later”

Earlier text framed a production golden-only gate as optional “Phase B.” That gate is now **required end state** of the treatments→GR fold. Implementation remains **phased** so cook is not bricked mid-migration:

| Phase | What |
| --- | --- |
| A + A.1 | Library UI + samples (**done**) |
| Fold 0–1 | Contract + `get_production_graphics` API (**this slice**) |
| Fold 2–5 | Editorial + creator cook read GR only; delete treatment kits as menus |

Empty production set → **hard fail with CTA** (promote graphics), never silent HyperFrames free-for-all.

---

## 3. Privacy rules (non-negotiable)

### 3.1 What is public (may live in the git repo)

- UI route and components for the Golden Record workspace.
- API handlers that read/write only under a configured private root.
- JSON Schema for `golden-record.json` (structure only; no filled channel data).
- Empty states, setup copy, and generic field labels.
- Privacy-check coverage for golden-record paths and media types.
- Tests using **synthetic** fixtures under test temp dirs (no real creator footage).

### 3.2 What is private (must never enter the repo)

- Sample MP4/WebM clips and poster images of the creator or their product UI.
- Populated `golden-record.json` from a real channel.
- Demo source receipts that identify private project paths or episode content when those are considered private.
- Ratings, notes, and status history from a real channel.
- Any media under the configured golden-record root.

### 3.3 Storage location

Default root (overridable):

```text
%USERPROFILE%/Videos/VCG Creator Library/golden-record/
```

Environment override (same family as Creator Library):

```text
VCG_GOLDEN_RECORD   # absolute path to the golden-record directory
```

Settings UI must allow **Choose folder** / **Create new golden record** so non-VCG users can point elsewhere without env vars.

### 3.4 Serving and path safety

- Media endpoints may only stream files that resolve **inside** the configured golden-record root (`is_within`).
- Reject path traversal, absolute paths outside the root, and symlink escapes.
- No upload of golden-record media to third parties.
- No telemetry of entry titles, notes, or sample paths.

### 3.5 Privacy check

Extend `scripts/check_repo_privacy.py` / `npm run privacy:check` so tracked content fails if it includes:

- paths matching `golden-record/` with media or a non-empty production catalog fixture that looks like real channel data;
- committed sample clips for golden examples.

Synthetic unit-test fixtures under `tests/fixtures/` are allowed only if they contain no personal paths, no real faces implied by binary media, and no channel-specific copy.

### 3.6 Building in public

Docs and commit messages may describe the **feature**. They must not paste:

- private absolute user paths with usernames as examples in committed fixtures;
- real episode titles + timestamps as required public examples;
- screenshots of the creator’s face from samples.

---

## 4. On-disk layout (private)

```text
<golden-record-root>/
  golden-record.json              # catalog index (schemaVersioned)
  examples/
    <entryId>/
      sample.mp4                  # preferred; short demo clip
      poster.png                  # optional still (first readable frame or explicit grab)
      source-receipt.json         # how the sample was made (private)
  quarantine/
    <entryId>/                    # optional: rejected media kept for audit
```

### 4.1 `golden-record.json` (index)

Conceptual shape (exact schema in repo when implemented):

```json
{
  "schemaVersion": 1,
  "updatedAt": "ISO-8601",
  "rootLabel": "optional human label",
  "entries": [
    {
      "id": "numbered-example-card",
      "displayName": "Numbered example card",
      "family": "numbered-example-card",
      "status": "candidate",
      "implementationId": "numbered-example-card",
      "beatTypes": ["example", "list"],
      "allowedLayouts": ["talking-bottom-left", "talking-bottom-right"],
      "parametersSchema": {},
      "sample": {
        "relativePath": "examples/numbered-example-card/sample.mp4",
        "posterRelativePath": "examples/numbered-example-card/poster.png",
        "durationSec": 12.4,
        "hasAudio": true
      },
      "rating": null,
      "notes": "",
      "tags": [],
      "createdAt": "ISO-8601",
      "updatedAt": "ISO-8601",
      "history": []
    }
  ]
}
```

### 4.2 Status machine

| Status | Meaning | Production selectable |
| --- | --- | --- |
| `candidate` | Designing / refining in the library | No |
| `golden` | Production may use this graphic | **Yes** |

Legacy statuses (`approved`, `rejected`, `superseded`) normalize to `candidate` on load. Workflow: design as candidate → promote to golden; demote golden back to candidate if needed. Do not keep a reject pile in the library.

Transitions are creator-driven in the UI. App may seed `candidate` from a local module catalog; app must **not** auto-set `golden`.

### 4.3 `demoBed`

| Value | Intended sample footage class |
| --- | --- |
| `talking-head` | Face-primary performance |
| `screen-share` | Software UI + optional speaker |
| `either` | Works on both; one sample still required for v1 |

### 4.4 `source-receipt.json` (private, per entry)

Records enough to regenerate the sample later without guessing:

- demo bed kind;
- private project id / path **only on disk**, never required in public code;
- source media relative path inside that project;
- source start/end sec used for the bed;
- module/treatment id and parameter payload used for the overlay;
- render tool/version stamp;
- createdAt.

Receipts are not published.

### 4.5 Sample duration

| Rule | Value |
| --- | --- |
| Target total length | 8–15 seconds |
| Hard max | 20 seconds |
| Structure | short pre-roll → treatment on → short hold → off (or natural end) |
| Audio | include locked-cut audio when available so lip-sync / speech context is real |

---

## 5. UI surfaces (public app)

### 5.1 Navigation

Add a first-class workspace entry, e.g. **Graphics Library** or **Golden Record**, alongside existing production workspaces. Visible even when no project is open (library is cross-project).

### 5.2 Setup / empty states

When no golden-record root exists or index is missing:

- explain that the library is private and local;
- actions: **Create golden record**, **Choose existing folder**;
- do not invent sample media.

### 5.3 List view

- Rows/cards: poster (or placeholder), display name, status.
- Filters: status, search; sample count + production-set count in stats.
- Search: id, display name, notes (and residual tags/intents until scrub).

### 5.4 Detail view

- Video player for `sample` (play/pause, scrub, mute toggle; default muted optional).
- Metadata panel: name, status, beat types, layouts, implementation id, sample/poster links, notes, rating.
- Status: candidate ↔ golden (toggle + select).
- Sample and poster appear as **openable links** in the metadata panel (and sample plays in the stage when present).

### 5.5 Explicitly out of UI v1

- Codex / Cook handoff from this page.
- In-app generative “make me a new graphic” from HyperFrames skills.
- Multi-user cloud sync.
- Editing module HTML/CSS implementation.
- Full Visual Production timeline editor embedded here.

### 5.6 Sample generation (Phase A optional vs Phase A.1)

**Minimum Phase A:** UI can list/edit metadata and play samples **if present**.

**Phase A.1 (same contract, may ship same PR or follow immediately):** operator action **Render missing samples** / **Re-render sample** that:

1. Uses creator-configured demo bed sources (paths chosen in settings or a one-time picker).
2. Builds a short HyperFrames (or existing composition) render for that entry’s `implementationId` + demo parameters.
3. Writes `sample.mp4`, `poster.png`, and `source-receipt.json` under `examples/<id>/`.
4. Updates the index sample block.

For the **VCG operator’s private instance only** (not coded as product defaults in public fixtures):

- talking-head bed = intro region of private project `2026-07-23-…`;
- screen-share bed = mid-video screen-share region of the same project.

Public code stores **user-selected bed paths and time ranges** in local settings or in the private golden-record root settings file — not hardcoded personal project paths in the repository.

---

## 6. API surface (public code, private data)

All routes read/write only the configured root.

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/golden-record` | Root path, exists?, entry list summary |
| POST | `/api/golden-record/open` | Set/create root (folder dialog or path) |
| GET | `/api/golden-record/entries/{id}` | Full entry + resolved media URLs |
| PATCH | `/api/golden-record/entries/{id}` | Update status, notes, rating, display fields |
| GET | `/api/golden-record/entries/{id}/media/sample` | Stream sample |
| GET | `/api/golden-record/entries/{id}/media/poster` | Stream poster |
| POST | `/api/graphics-library/ensure-engine-usages` | Ensure `candidate` usage rows for each known engine (no golden, no media) |
| POST | `/api/golden-record/entries/{id}/render-sample` | Phase A.1: render sample into private examples |

No route returns another user’s data; there is only the local root.

---

## 7. Relationship to existing systems

| System | Relationship |
| --- | --- |
| Creator Library (`library.json`, assets) | Sibling private store for reusable **footage/assets**. Not the graphic menu. |
| `treatments.json` harvest | **Import-only** into GR candidates (ratings/notes). **Not** selection authority. |
| Module catalog / `MODULE_IDS` | **Render inventory** + seed of GR candidates. Not the production menu. |
| `DAILY_TREATMENT_KIT` / seed packages | **Deleted** — selection is Graphics Library golden usages only. |
| `editorial_variety` | Flat model: variety by **graphic id** only (no family tree of variants). |
| HyperFrames skills | Not vocabulary authority. |

### 7.0 Producer metadata (what “golden” should mean)

**Look lock (approved 2026-08-01):** `candidate` is where composition, type scale, and position are designed (under brand guardrails). **`golden` freezes that usage’s approved look** (hierarchy, sizes, frame geometry, motion character as shown in the sample). Episode production may change **instance** content and declared timing channels via placement; it must **not** invent a new type scale or layout for an already-golden usage. To redesign: demote → refine → re-sample → promote. See `docs/vcg-graphics-process/architecture.md` §5.1.

When a graphic is **golden**, creator-owned fields must be intentional for the full pipeline (select → place → vary → build):

| Field | Pipeline step |
| --- | --- |
| `status` | Gate (production set) |
| `implementationId` | Build / render |
| `allowedLayouts` | Place (OBS layout set) |
| (no family) | Flat shelf — one golden standard per job; variety by graphic id only |
| `beatTypes` | Select (which closed VCG beat jobs this graphic may serve) |
| `sample` | Human proof before promote |
| `rating` / `notes` | Review |

**`beatTypes`:** multi-select from the approved 13-type universe in `docs/vcg-graphics-process/beat-universe.md` (same ids Masterbeater emits). Empty means not tagged yet — tag before relying on selection.  

**Kept media (not scrubbed):**

| Field | UI |
| --- | --- |
| `sample` | Short proof clip — **openable link** in metadata (also plays in stage) |
| `poster` (`sample.posterRelativePath`) | Still frame — **openable link** in metadata |

**Dropped (noise — scrub at end-pass):**

| Field | Decision |
| --- | --- |
| `purpose` | Replaced by `beatTypes` |
| `reusePolicy` | Failed AI-control attempt; human editing owns frequency |
| `demoBed` (per entry) | Sample bed chosen at render time while designing; not process driver |
| `buildable` | Redundant flag — production set is golden status only |
| `implementationId` | Dropped — **graphic id is the module id** (one engine per library graphic) |

Library **settings** may still hold talking-head / screen-share *source clips* for sample renders. That is tooling configuration, not per-graphic metadata.

### 7.0b Approved architecture package (2026-08-01) — binding

See §2. Summary after pushback lock-in:

| Decision | Status |
| --- | --- |
| **Engine** draws; **usage** when/where; **placement** on a video; **assignment** after Masterbeater (later) | **Approved** |
| Product words: engine, usage, placement, assignment, graphics library — **not** module / GR / seed | **Approved** |
| `golden` = usage status only; production = golden usages | **Approved** |
| Usage **has-a** engine (`engineId`) — **not** identity-coupled (OOP composition) | **Approved** |
| Engine interface = content + **declared** timing channels only | **Approved** |
| Placement supplies instance content + timing values (later; future Shane + Grok) | **Approved** |
| Usage thin; no stored param schema; UI passthrough from engine | **Approved** |
| Layout eligibility = creator-owned usage contract vs engine draw region | **Approved** |
| Sample = exact production engine (no parallel renderer) | **Approved** |
| **Candidate authoring vs golden lock:** type/layout judgment while `candidate`; promote freezes that usage’s size/position language; production assigns/places goldens and does not re-skin them (demote to change look). Brand type **roles** are authoring defaults only | **Approved** (2026-08-01) — authority: `docs/vcg-graphics-process/architecture.md` §5.1 |
| Destroy seed kit as second draw stack | **Done** — `creator-production/seed-kit/` deleted |
| Seed-only aliases `compact-editorial-emphasis`, `compact-prompt-card` | **Deleted** |
| Dead selection/approval keys on old param dumps | Scrub end-pass |

**Clean library rule:** every usage references a real engine. Prefer re-curating private libraries from engines; do not invent seed-only ids.

### 7.0a End-pass tasks (do not implement full scrub mid-walk)

Two cleanup jobs run **once at the end** of the metadata walk — not piecemeal while editing each field. UI fields are removed as we decide; schema/private JSON strip waits for the end-pass.

#### A. Promote-to-golden validation (input gate)

Block or warn on promote when any of these are missing / invalid. **Draft list** — refine as we finish field decisions:

| Field | Required meaning |
| --- | --- |
| `displayName` | Non-empty human name |
| graphic `id` | Must be a runtime module id (the render engine) |
| `beatTypes` | ≥1 approved beat type |
| `allowedLayouts` | ≥1 layout (TBD if always true) |
| `sample` | Short sample present (human proof before promote) |

Not on the gate: free notes, rating (optional quality), timestamps.  
**Not on the gate:** `reusePolicy`, `demoBed`, `buildable`, `implementationId` (dropped).

#### B. Scrub / delete (everywhere — not just UI)

**Partial implement (2026-08-01):** Graphics Library load/save runs `scrub_usage_entry` so private indexes no longer re-persist list-B fields. Sample receipts / history events still may mention legacy bed keys until re-rendered.

Remove from remaining surfaces when cleaning other stacks, including:

- private `golden-record.json` entries
- seed / import / harvest writers
- public API views / TypeScript types / filters
- **sample render path** (`render_entry_sample`, batch re-render, source-receipt.json keys, history events)
- any remaining docs/schema examples that still list the field

| Field | Why scrub |
| --- | --- |
| `purpose` | Replaced by `beatTypes` |
| `reusePolicy` | Dropped — human edit process owns reuse |
| `demoBed` | Dropped as entry metadata — choose bed when requesting a sample render (including in sample render + receipts) |
| `buildable` | Dropped — not a production gate; module presence is graphic id |
| `implementationId` | Dropped — graphic id is the module id |
| Seed kit production path / seed-only alias graphic ids | Destroyed; modules only |
| Dead COMMON selection/approval keys on module param sets | Treatment-menu residue; not graphic content |
| `intents` | Old free-string planning tags; superseded by `beatTypes` |
| `preferredIntents` | Same family as intents |
| `family` | Flat shelf; not a selection tree (see variety rules) |
| `visualFamily` | Same — variety by graphic id only |
| `contentCapacity` | Free-string noise, not a closed contract |
| `motionProfile` | Free-string noise |
| `tags` | Unused / redundant if beats + notes exist |
| `lockedDefault` | Legacy treatment lock; not GR status |

**End-pass note for samples:** scrubbing `demoBed` / `buildable` includes sample render, receipts, and history — not only the entry form. Sample bed is chosen at design-time render request (or module default + library bed settings), never as permanent entry metadata. Keep **sample + poster media** and their open links.

Keep reviewing this table as we walk remaining fields. If a field is kept, remove it from B and add clear rules to A if it is golden-required.

### 7.1 VCG private cleanup (operator sidequest, not public data)

When the VCG operator first creates their golden record, an optional local migration may:

1. Seed candidates from the 29 buildable modules.
2. Restore metadata from Creator Library harvest + quarantine **except** true unbuildables (e.g. `build-review-change-loop`).
3. Preserve `numbered-example-card` rating/lock notes as candidate/approved metadata — still not auto-golden unless the creator promotes.

This migration runs against **private paths only** and must not write channel content into the repo.

---

## 8. Authorized implementation scope (when approved)

### Phase A — Library + UI (this approval request)

**Authorized:**

1. Private golden-record store module (load/save/validate index; path safety).
2. Schema file under public `schemas/` or `visual-production/schemas/` as appropriate.
3. API routes listed in §6 except render may be stubbed if A.1 is split.
4. Web workspace: setup, list, detail, status/notes/rating edits, media playback.
5. Settings/env for root path; folder create/open.
6. Privacy-check extensions and unit tests with synthetic fixtures.
7. Ensure-engine-usages (candidates only).
8. Optional local import from existing `treatments.json` / quarantine for buildable module ids.

**Excluded from Phase A:**

- Production hard-gate requiring golden ids (Phase B).
- Full episode cook changes.
- Cloud sync / multi-user.
- HyperFrames skill changes.
- Committing any real sample media or populated VCG catalog.
- Redesign of module markup unless required for sample render (prefer A.1 only if needed).

### Phase A.1 — Sample render pipeline

**Authorized when Phase A is approved and A.1 is explicitly included:**

- Demo bed configuration (two user-selected source windows).
- Per-entry short render into private `examples/`.
- Poster extraction.
- Source receipts.

### Phase B / Fold — Production gate + kill treatment menus (approved direction 2026-07-31)

**End state (required):**

- Editorial / Cook / plan validators accept only production-set GR ids (default: `status: golden`).
- Clear error when a plan references non-golden / unknown graphic ids.
- Empty production set → production blocked with setup CTA, not silent HF fallback.
- No parallel treatment/daily-kit **selection** path remains.

**Phased delivery** (do not big-bang delete cook):

0. Contract + terms (this amendment).  
1. `get_production_graphics()` + tests (library is queryable as production set).  
2. Editorial plan validation reads GR production set.  
3. Build resolves graphic id → GR → implementation.  
4. Creator Production same authority.  
5. Delete treatment menu surfaces; GR UI owns producer metadata.

---

## 9. Acceptance criteria

### Phase A

1. Fresh clone + app run: Golden Record workspace opens; empty state works; no private media required.
2. Create or open a golden-record folder outside the repo; index is created with `schemaVersion: 1`.
3. Ensure-engine-usages produces `candidate` entries only; zero entries are `golden` without a creator action.
4. List filters and detail view show metadata; PATCH persists status/notes/rating.
5. When a sample file exists under `examples/<id>/`, detail plays it via the media API.
6. Media API refuses paths outside the golden-record root.
7. `npm run privacy:check` still passes; no golden sample media is tracked by git.
8. Automated tests cover schema validation, path safety, status transitions, and empty root behavior using synthetic temp dirs.

### Phase A.1 (if in scope)

9. With two demo beds configured, render-sample for a buildable entry writes sample + poster + receipt under the private root and updates the index.
10. Sample duration is ≤ 20s and includes audible source audio when the bed has audio.
11. Re-render overwrites sample deterministically for the same entry params.

### Production gate / fold

12. `get_production_graphics` returns only golden (policy) ids; empty set is explicit, not a full-catalog fallback.  
13. Plan validation rejects graphic ids outside the production set (Fold phase 2+).  
14. No production selection via `DAILY_TREATMENT_KIT` / seed-treatment menus (Fold phase 5).

---

## 10. Verification plan

- Python unit tests for store + API path safety.
- Optional lightweight web typecheck for new TS types.
- Manual: create private root, seed, set one entry golden, play a hand-placed sample file.
- Privacy: `npm run privacy:check` after the change.
- Do **not** start or stop the user-owned dev server unless explicitly asked.

---

## 11. Risks and mitigations

| Risk | Mitigation |
| --- | --- |
| Private media leaks into git | Default root outside repo; gitignore media; privacy check; path-safe API |
| Auto-golden recreates Codex trust problem | Seed only `candidate`; creator promotes |
| HF skills reintroduce 3-loop graphics | Phase B golden-only gate; skills never write the golden index |
| Sample beds hardcoded to one creator’s paths | User-configured beds only in settings/private root |
| Confusion with Creator Library | Separate nav label + docs; separate index file |
| Empty catalog blocks all production too early | Phase B is separate approval; Phase A is browse/approve only |

---

## 12. Open decisions for approver

Defaults proposed below; change before implementation if needed.

| # | Decision | Proposed default |
| --- | --- | --- |
| D1 | Phase A.1 (sample render) in first implementation pass? | **Yes** — UI without samples is half a product; keep beds user-configured |
| D2 | Production golden-only gate | **Yes end state** — phased fold; do not leave treatments as parallel menu |
| D3 | Is `approved` production-selectable? | **No** — only `golden` |
| D4 | Nav label | **Graphics Library** (subtitle: Golden Record) |
| D5 | Default folder name under Creator Library | `golden-record/` |
| D6 | Import from existing treatments/quarantine on first seed? | **Yes** for buildable module ids only; restore ratings/notes; leave status `candidate` or `approved` if prior rating ≥ 5 and lockedDefault — still never auto-`golden` |

---

## 13. Approval

**Approved:** Phase A + A.1 (creator, 2026-07-30 session).

**Approved:** Fold treatments into Golden Record; kill parallel treatment menus; modules render-only; GR is sole production menu (creator, 2026-07-31 session). Delivery phased 0→5 as in §8.

Implementation landed (A + A.1):

- `app/core/graphics_library.py` — private store, seed, harvest import, sample render, production-set query  
  (`app/core/golden_record.py` is a legacy re-export shim only)
- API under `/api/graphics-library/*` (legacy `/api/golden-record/*` aliases)
- UI: Tools → **Graphics Library** (`web/app/graphics-library.tsx`)
- Schema: `visual-production/schemas/golden-record.v1.schema.json` (filename legacy; structure still v1)
- Operator seed: `python scripts/seed_graphics_library.py [--render]`
- Tests: `tests/test_graphics_library.py`

**Fold status:** Phases 0–5 **landed** (2026-07-31):

| Phase | Status |
| --- | --- |
| 0 Contract | Done |
| 1 `get_production_graphics` | Done |
| 2 Editorial plan validation | Done — GR production set only |
| 3 Build resolve | Done — `GRAPHIC_IMPLEMENTATION_BINDINGS` + GR `implementationId`; materialize checks production set |
| 4 Production menu | Golden usages on Graphics Library (no profile flag) |
| 5 Kill parallel menu | Done — treatment kit is legacy inventory only; variety prefers GR family; UI shows production count |

Private library may hold **temporary golden** marks for pipe testing; **re-curate before real episode export**.
