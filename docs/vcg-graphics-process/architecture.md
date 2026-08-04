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
| Creator Production holdover (not product path) | `app/core/creator_production_menu.py` |
| Beats → engine cues | `app/core/editorial_visual_plan.py` |
| Editorial build (engine path only) | `app/core/editorial_build.py` |
| Beat plan validation | `app/core/editorial_beats.py` |
| Library UI | `web/app/graphics-library.tsx` |
| API | `/api/graphics-library/*` |

Private root: `VCG_GRAPHICS_LIBRARY` (also discovers existing `golden-record` folder/index on disk for migration). Index: `graphics-library.json` (reads legacy `golden-record.json` if present).

Production draw is engines only; selection is Graphics Library golden usages.
