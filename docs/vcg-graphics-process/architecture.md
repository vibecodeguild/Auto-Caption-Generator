# VCG Graphics Architecture

**Status: APPROVED (2026-08-01)**  
**Product vernacular (binding).** Code may still use legacy filenames; product language does not.

Related: [README.md](./README.md), [beat-universe.md](./beat-universe.md),  
`docs/graphics-golden-record-contract.md` §2 (storage/privacy still describe the private library folder).

---

## 1. Three objects (+ one later matcher)

| Object | Responsibility | Not responsible for |
| --- | --- | --- |
| **Engine** | **Draw** one graphic type. One purpose, one input interface. | When it may be used; which video; instance copy |
| **Usage** | Graphics library **when/where** contract + human proof | Drawing; episode instance values |
| **Placement** | Put a usage on a **specific** locked cut (later) | Library policy; inventing draw code |
| **Assignment** | After Masterbeater: match beats → golden usages ([assignment.md](./assignment.md) **APPROVED**) | Drawing; labeling speech |

```text
Usage  ──engineId──►  Engine.draw(content, timingChannels)
  ▲
  │ usageId
Placement (later)

Assignment (later): Beats × golden Usages → proposed usageId per beat
```

**One-line contract:** Engine draws. Usage says when/where. Placement puts it on a video. Assignment picks usages for beats.

---

## 2. Terms (binding)

| Term | Meaning |
| --- | --- |
| **Engine** | Sole production draw implementation for a type. Owns content fields + **declared timing channels** it can animate. Product word: **engine** (not “module,” not “seed”). |
| **Usage** | One Graphics Library shelf entry. Has-a **engineId** (composition — **not** identity-coupled). Own `id`. Beat types, allowed layouts, status, sample, poster. **`candidate`** = designing the look; **`golden`** = look locked for production (see §5.1). |
| **Placement** | One instance on a real project (later): content values, timing values, span on cut. |
| **Assignment** | Later job after Masterbeater. Not Masterbeater; not the engine. |
| **Graphics Library** | Collection of **usages** (each referencing an engine). UI product name. |
| **`golden` / `candidate`** | Status **on a usage only**. Production set = usages with `status === golden`. There is no product called “golden record.” |
| **Seed kit** | **Destroyed** as production draw stack (Codex dual path). |

Legacy code words → map: module→engine, GR entry→usage, treatment menu→superseded, seed→destroy.  
Old `implementationId` seed/alias mess → clean **`engineId`** on usage.

---

## 3. Engine interface

### Engine owns

- How to **draw** (designed screen region is part of the design).
- **Content** parameters of the draw interface.
- **Declared timing channels** only (e.g. bullet reveal times, word-sync hits) — not every timeline concept in the product.

### Placement owns (later)

- Concrete copy / rows / labels for **this** cut.
- Actual timing values for the engine’s channels (sync to voice).
- Span of the placement on the locked cut.
- Episode-level transitions if any (not library metadata).

### Usage owns

- `engineId` reference.
- `beatTypes`, `allowedLayouts`.
- `status` (candidate | golden), display name.
- Sample + poster **paths** (proof that the engine path was used).
- **Not** rating, notes, or audit history (noise).
- **Does not** store a parameter schema (no second interface).

**Library UI:** may **passthrough-display** the engine’s interface as help — never as editable usage-owned schema.

### Single interface declaration — `ENGINE_REGISTRY` (approved 2026-08-03)

Every engine's interface is declared **once**, next to its draw code:
`app/core/visual_production.py :: ENGINE_REGISTRY`. Each entry declares:

- the **placement interface** — line slots (text + revealFrame each), optional list slot with bounds, and the meta / assets / motion knobs the engine exposes per episode;
- **`legacy_parameter_keys`** — draw-accepted keys placement must never expose (today only `kicker`, awaiting the deferred D5 chrome cleanup).

`MODULE_IDS`, `MODULE_PARAMETER_KEYS`, and placement's `ENGINE_PLACEMENT_SPECS` are **derived views** of this registry — never hand-edit a parallel list. `app/core/placement_roles.py` is a **thin adapter**: it owns placement-layer policy only (slot → `parameters.*` mapping, the kicker ban) and declares no engine facts.

**Direction of flow (binding):** the engine/library declares → placement inherits. Discovering a missing parameter during placement work means growing the engine's registry entry (library-side design), never hardcoding a field on the placement side. Import-time validation rejects malformed declarations (kicker in a placement bucket, bad list bounds, placement keys outside engine parameters).

**Sample:** built with the **exact production engine**. No parallel sample renderer.

**Layouts:** Engine draws where it draws. Creator sets usage `allowedLayouts` so only scenes where that draw looks good are eligible. Bad overlay on face = usage contract mistake, not a speaker-safety parameter system on the engine.

---

## 4. Usage ↔ engine composition

- Usage **has-a** engine (`engineId`).
- **Not** required that `usage.id === engineId` forever.
- v1 seeding may set them equal for convenience.
- Later: multiple usages may share one engine with different when/where rules.

---

## 5. Pipeline

```text
[0] Locked cut + final transcript
[1] Masterbeater              → ordered beats (speech jobs)
[2] Scenelayer → Assignment   → layoutId per beat, then golden usages ([scenelayer.md](./scenelayer.md), [assignment.md](./assignment.md))
[3] Placement                 → lines + reveal frames, live Tier-B preview, lock; final full render ([placement.md](./placement.md))
[4] Engine.draw               → same path as library samples (powers live preview + final)
[5] Review → fix → export
```

**Placement (approved 2026-08-02; studio + live preview built):** single-beat studio; content = lines `{text, revealFrame, slot}` (no kickers); live HyperFrames preview only (no Tier-A sticker path, no draft encode for timing); explicit lock; final = one full re-render when all assigned locked. Authority: [placement.md](./placement.md).

Production selection: **usages where status is golden** — not “select the golden record.”

---

## 5.1 Candidate authoring vs golden lock (approved 2026-08-01)

**Product decision:** design consistency is enforced when **minting** library usages, not when restyling them every episode.

| Stage | What is free | What is locked / constrained |
| --- | --- | --- |
| **`candidate`** (new or demoted usage) | Composition, type scale, sizes, positions, motion character, sample layout choice — creator judgment while designing | Brand **non‑negotiables** (Montserrat, color roles, speaker safety / hard frames). Shared **type roles** (display / title / label / kicker / meta) are **authoring defaults**, not a second freeform type system per sample |
| **Promote → `golden`** | — | That usage’s **approved look** is locked: hierarchy, scale relationships, frame geometry, and engine motion character as proven by the sample. Promotion means “this is the standard for this job” |
| **Daily production** (assignment + placement) | Which **golden** usage, copy, voice/timing channels, layout eligibility, placement params the engine already exposes (e.g. punch-zoom motion, callout bounds, milestone text) | **Not** inventing new font sizes, positions, or a one-off redesign of a golden. To change the look: demote → refine as candidate → re-sample → promote again |

**One-line rule:** Standards and creativity apply to **candidate authoring**. **Golden** freezes size and position language for that usage. Production **assembles the kit**; it does not re-skin goldens.

**What this is not:**

- A full design system that re-themes goldens every plan.
- Episode-level type tokens overriding a golden usage.
- Forbidding placement params the engine already declares (copy, timing, allowed motion modes).

**Brand guardrails (authoring only):** shared type **roles** and color **roles** keep candidates from becoming random “almost VCG” garbage. They do not force every engine into identical layouts. Creativity lives in **new usages** and **which golden + placement**, not in freelancing px on already-golden shelf entries.

---

## 5.2 Overlay B-roll is an engine (approved 2026-08-19)

**Product decision:** covering the speaker with footage **without moving time** is a Visual Package **graphic**, not a recut and not a parallel B-roll timeline.

| Layer | Rule |
| --- | --- |
| **What it is** | A new **engine** (footage plate over the locked cut). Library **usages** of that engine are assigned and placed like every other golden. |
| **What it is not** | A new Masterbeater beat type. A source-sequence clip. A locked-cut re-export. An insert that grows program duration. |
| **Pipeline** | Same as every graphic: beats → scenelayer → assignment → placement (asset + trim/transform) → live Tier B → lock → Final. |
| **Clock** | Locked-cut frames stay authority. Transcript, beats, and other placements do not shift. Locked-cut audio continues under the plate. |
| **Not this engine** | **Insert clips** (split the program, drop a shot, shift everything after) — Stage 4, [§5.3](#53-insert-clips-are-a-program-edit-list-approved-2026-08-19). |

**Engine id:** `broll-overlay`. Placement chooses the clip (`videoAssetId`) and in-point (`clipStartSec`). The plate is **full-bleed** over the locked cut. **Starts** is a word-chip on the locked cut. **Ends** defaults to the out-point of the chosen clip (from that in-point), still inside the beat; a word pick only wins when it is earlier. They do not change locked-cut time. Library samples may render a placeholder plate until a clip is attached. Clip source is a **local file**, a **frozen project library** clip, or a **Pexels** search from Placement (landscape 16:9, Pexels License, frozen into the project with evidence). Overlay is muted. Pexels is the only stock provider — not a parallel Visual Production inbox.

---

## 5.3 Insert clips are a program edit list (approved 2026-08-19)

**Product decision:** after graphics are **locked**, a separate insert pass may split the **show** and drop one or more clips. This is not overlay B-roll (§5.2) and not a locked-cut re-export.

| Layer | Rule |
| --- | --- |
| **What stays frozen** | `locked-cut.mp4`, transcript word IDs, beats, assignment, placement frames (locked-cut clock). |
| **What is new** | A **program** edit list: play cut range, play clip, play cut range, play another clip, … Any number of inserts. Later inserts add to the waits already created by earlier ones. |
| **Preview / Final** | Live seek the piece under the playhead (cut or clip). Encode the list once at Final. No episode preview MP4. |
| **Program transcript** | After inserts, write a **derived** transcript on the **program** clock. A-roll words are the locked-cut transcript with times shifted by total insert duration before each word — not a new Whisper pass on the talking head. Each insert span includes a **marker** (clip name / chapter). When the clip has speech, transcribe **that clip** and splice those words into the same file at program times. Silent clips keep the marker only. Insert word IDs are clip-scoped; they must not collide with locked-cut word IDs. This file is what leaves the app for YouTube descriptions and other tools. |
| **Where T may land (v1)** | **Between beats / in gaps only.** A locked-cut frame is legal when it is **not strictly inside** a beat `[startFrame, endFrameExclusive)`. Boundaries, pre-first-beat, unlabeled gaps, and post-last-beat are allowed. Several inserts may share a T and play in list order. A locked graphic stays whole and shifts on the program clock if an insert is before it. Mid-sentence / mid-graphic splits are out of v1. |
| **UI (2026-08-20)** | Visual Package **Stage 4 · Inserts**, enabled when every assigned placement is locked. Stage 3 is Place + Lock only. **Final** is on Stage 4. |
| **A-roll / delivery (2026-08-20)** | HyperFrames full-cut encode is a private **A-roll master**. Delivery Final concatenates A-roll slices + clips (identity copy when there are no inserts) to `exports/final-video.mp4`. Preview seeks the piece under the playhead. No episode preview MP4. |
| **Insert audio (2026-08-20)** | Clip audio **plays**. Optional **mute** per insert. A-roll audio does not mix under an insert. Overlay B-roll remains muted on the locked-cut clock. |
| **Marker wording (2026-08-20)** | Clip **display name** only (default filename). Rename on the insert row. No chapter field. |

v1 contract: [inserts.md](./inserts.md).

---

## 6. What was destroyed / scrubbed

| Destroy / scrub | Why |
| --- | --- |
| Parallel package draw stacks | Second draw stack; white-card path |
| Alias ids that were not engines | Not engines |
| Stored usage `parameters` as authority | Drift; interface lives on engine |
| Product language: module, GR, treatment menu | Confusion |
| Dead selection/approval keys on param dumps | Cook residue, not draw content |

**Usage JSON scrub (implemented):** `scrub_usage_entry` on load/save keeps only product fields  
(`id`, `displayName`, `status`, `engineId`, `allowedLayouts`, `beatTypes`, `sample`, timestamps).  
Legacy keys (`rating`, `notes`, `history`, `implementationId`, `demoBed`, `parameters`, …) are stripped from private indexes.

---

## 7. OOP sketch

```text
Engine
  id
  interface: content fields + timing channels
  draw(content, timingChannels) → rendered output

Usage
  id
  engineId          // reference
  beatTypes[]
  allowedLayouts[]
  status            // candidate | golden
  sample, poster, displayName

Beat                // Masterbeater
  type, word span, …

Assignment          // Stage 2 — see assignment.md
  deal(beats, goldenUsages) → draft usageId per beat (bag per type)

Placement           // later
  beatId, usageId
  content, timingChannels, span
```

---

## 8. Implementation map (code)

| Concept | Primary code |
| --- | --- |
| Engine interface declarations (single source) | `app/core/visual_production.py` (`ENGINE_REGISTRY`; `MODULE_IDS` / `MODULE_PARAMETER_KEYS` are derived) |
| Placement adapter (policy only, no engine facts) | `app/core/placement_roles.py` (`ENGINE_PLACEMENT_SPECS` is a derived view) |
| Usage store + sample render | `app/core/graphics_library.py` (private root; product: Graphics Library) |
| Beat types | `app/core/masterbeater.py` / `app/core/editorial_beats.py` |
| Scene layouts | `app/core/editorial_layout.py` |
| Library UI | `web/app/graphics-library.tsx` |
| Visual Package UI | `web/app/visual-package.tsx` |
| API | `/api/graphics-library/*`, `/api/visual-package/*` |

Private root: `VCG_GRAPHICS_LIBRARY` (also discovers existing `golden-record` folder/index on disk for migration). Index: `graphics-library.json` (reads legacy `golden-record.json` if present).

Production draw is engines only; selection is Graphics Library golden usages.
