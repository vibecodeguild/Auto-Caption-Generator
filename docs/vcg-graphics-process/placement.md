# Placement (Stage 3)

**Status: APPROVED (2026-08-02)** — product contract for Visual Package Stage 3.  
**Locked decisions include UI studio, live preview, reveal UX, lock/final, all 18 engines.**

Related: [architecture.md](./architecture.md), [assignment.md](./assignment.md), [scenelayer.md](./scenelayer.md).  
Code: `app/core/placement_roles.py`, `app/core/placement.py`, Stage 3 in `web/app/visual-package.tsx`.

---

## 1. One-line job

For each **assigned** beat, produce a **locked instance** of that golden’s **engine**: on-screen **lines** (words) and **when each line reveals** (absolute frame), plus non-text knobs. Iterate with **live HyperFrames preview** (no encode). When **every** assigned placement is **locked**, run **one full episode re-render**.

```text
Beat + layout + usageId
  → draft lines + revealFrame
  → human edit (words + frames)
  → live Tier-B preview (instant)
  → Lock
  → (all locked) Final full render
```

**Not Placement:** choosing the golden (Assign), speech labels (Masterbeater), re-skinning goldens.

**Daily goal context:** Placement is the critical path for a ~2 hour full-video graphics finish; **preview speed** (live composition, not sample encodes) is a first-class requirement.

---

## 2. Locked product decisions

| # | Decision | Status |
| --- | --- | --- |
| D1 | **Final assemble** = one **full re-render** from locked placements on the locked cut. Not stitch of beat encodes as the product path. | **LOCKED** |
| D2 | **Beat iteration** = live **HyperFrames / GSAP** composition only (**Tier B**). No parallel “Tier A” fake sticker path. No draft FFmpeg encode required for timing/copy. | **LOCKED** |
| D3 | **Encode** only for **Final** (and optional rare debug). Never for every nudge. | **LOCKED** |
| D4 | **Content model** = `lines[]` with `{ text, revealFrame, slot }` (+ meta / assets / motion). | **LOCKED** |
| D5 | **No kickers / eyebrows** in placement content or new fills. Engine CSS kicker chrome = **deferred operator cleanup**. | **LOCKED** |
| D6 | **All 18 engines** have placement specs before more library engines. | **LOCKED** |
| D7 | **Explicit lock** per beat. **Final** enabled only when **all assigned** placements are locked. Unassigned beats do not block. | **LOCKED** |
| D8 | **UI** = single-beat **Placement studio** (not Masterbeater/Scenelayer full-transcript stream). | **LOCKED** |
| D9 | **Reveal UX** reuses transcript-editor DNA: word chips (set reveal to word `startFrame`), **±1/±5/±10 frame nudges**, pin to playhead. | **LOCKED** |
| D10 | **List engines** support **add/remove** bullets within `list_max` (e.g. dependency-stack **6** nodes). | **LOCKED** |
| D11 | Human owns hard copy + reveal craft; app drafts dumb/fast. No LLM required for core path. | **LOCKED** |
| D12 | Stitching beat preview MP4s = **not** product authority (optional future escape hatch only). | **LOCKED** |

---

## 3. Product stance

| Layer | Expectation |
| --- | --- |
| **Algorithm** | Deterministic first draft of lines/timing/meta from beat + engine map |
| **Human** | Owns copy quality and reveal craft (especially multi-line reveals) |
| **Live preview** | Real engine (Tier B) scrubbed to playhead — **instant** after nudge |
| **Final** | Single full re-render when `allLocked` |
| **Lock** | Explicit freeze for final + protect from re-Place overwrite |

Perfect zero-touch placement is **not** the goal. Fast human lock is.

---

## 4. Unified content model (all engines)

### 4.1 Line (unit of on-screen text)

```json
{
  "text": "string shown on screen",
  "revealFrame": 1234,
  "slot": "text"
}
```

| Field | Meaning |
| --- | --- |
| `text` | Exact string for that unit |
| `revealFrame` | **Absolute frame on the locked cut** when this line becomes active / fully revealed |
| `slot` | Engine parameter binding (`text`, `items.0`, `nodes.2`, …) |

One-line graphic → one line.  
Bullets / stack / callouts → N lines, each with its own `revealFrame`.

### 4.2 Bags

| Bag | Holds |
| --- | --- |
| **`lines`** | All human-edited words + reveal frames |
| **`meta`** | Non-prose scalars (`stepNumber`, `value`, `appName`, …) |
| **`assets`** | `imageAssetId`, `logoAssetId`, … |
| **`motion`** | Non-word knobs (`side`, `anchor`, `focusX`, `zoom`, bounds, …) |

### 4.3 Span

- `startFrame` / `endFrameExclusive` — default from beat; human may trim  
- Line `revealFrame` should lie within the span (clamp on draft)

### 4.4 Artifacts

| File | Role |
| --- | --- |
| `placement.json` | First algorithm draft (immutable from casual UI) |
| `placement-reviewed.json` | Working set + **`locked`** flags |
| `placement-edit-ledger.json` | Append-only human edits |

---

## 5. All 18 engines → slots

**Code authority:** `ENGINE_REGISTRY` in `app/core/visual_production.py` — each engine declares its placement interface (slots, list bounds, meta/assets/motion) next to its draw code. `app/core/placement_roles.py` is a thin adapter; its `ENGINE_PLACEMENT_SPECS` is a **derived view** (never hand-edit). To add or change a parameter: grow the engine's registry entry — placement inherits it. See [architecture.md §3](./architecture.md).  
Adapters map slots → existing `parameters.*` (engines keep draw names until cleaned).

| Engine | `lines` slots | List (add/remove) | `meta` | `assets` | `motion` |
| --- | --- | --- | --- | --- | --- |
| punchline-reveal | `text` (reveal = whole right card: borders + image + caption) | — | — (graphic end = placement `endFrameExclusive`, default beat end; trim earlier to undock before beat ends) | `imageAssetId` **required** (joke card only; demo default; custom via studio image picker → `assets/placement/`) | `accentColor?` |
| kinetic-word-punctuation | `phrase` | — | — | — | `side`, `anchor`, `accentColor?` |
| robot-cheer | `text`, `tagline?` | — | — | — | — |
| robot-defiant | `text` | — | — | — | — |
| robot-roast | `text` | — | — | — | — |
| robot-rocket-sign | `text` | — | — | — | — |
| speaker-side-panel | `text` + `items.*` | **items** max 12 | — | — | `side`, frame/panel knobs |
| dependency-stack | `text` + `nodes.*` | **nodes** max **6** | — | — | — |
| numbered-example-card | `titleLines.*` | **titleLines** max 8 | example #s | — | tags / accent |
| speaker-rise-callouts | `thesis` + `callouts.*` | **callouts** max 8 | accent index | — | — |
| problem-card-triptych | `cards.0`…`cards.2` | fixed 3 | — | — | — |
| progress-scale | `text`, `startLabel`, `targetLabel` + `milestones.*` | **milestones** max 8 | — | — | accent |
| numbered-step-intro | `title`, `action` | — | `stepNumber`, `showNumber?` | — | `side` |
| ui-callout | `label`, `detail` | — | — | — | bounds / pointer |
| windows-prompt-typing | `prompt` | — | `appName?` | — | `side` |
| brand-cta-lockup | `logoText`, `action`, `destination` | — | — | `logoAssetId?` | — |
| tradeoff-meter | `leftLabel`, `rightLabel`, `verdict` | — | `value` | — | `side` |
| source-punch-zoom | *(none)* | — | — | — | focus / zoom / motion |

**No `kicker` slot** anywhere. Adapters never fill kicker.

**Video-docking engines** (move `#main-video`, not only overlay text): include at least  
dependency-stack, speaker-side-panel, progress-scale, windows-prompt-typing, punchline-reveal (joke card), source-punch-zoom, brand-cta-lockup.  
Live preview **must** use real composition (Tier B), not a text-only sticker.

**Engine identity:** one engine id = one look. No dual modes.  
`punchline-reveal` is **only** the joke card (image + caption, head docks left).  
Text-only kinetic phrases use **`kinetic-word-punctuation`**, not a second mode of punchline-reveal.

---

## 6. Live preview (Tier B only) — **LOCKED**

### 6.1 Definition

| Mode | What | When |
| --- | --- | --- |
| **Live Tier B** | Same HyperFrames HTML + GSAP path as production, driven by current placement, scrubbed to player time | **Default** for all placement iteration |
| **Final encode** | Full-quality episode render from locked placements | Only when all assigned locked |
| **Draft FFmpeg encode** | Not product path for placement loop | Rejected as default (optional rare debug only) |
| **Tier A fake sticker** | Separate simple overlay path | **Rejected** — do not maintain |

**Both “simple sticker” and “real engine live” are fast (no encode wait).** We only ship **real engine live** so there is one code path and video-dock / typing / robot motion stay honest.

### 6.2 All 18 engines and live preview

**All 18 support live Tier B** for nudge → play → judge timing/copy.  
None require FFmpeg for the placement loop.

Engines that need the **full runtime** (not a static CSS opacity cheat) still stay in-browser:

- windows-prompt-typing (letter typing)  
- robots / rocket (multi-phase / SVG)  
- source-punch-zoom (video zoom)  
- video-dock family (stack, side-panel, progress, prompt, joke punchline, CTA)

### 6.3 Player UX (studio)

- **One primary player:** locked-cut **source** for this beat span  
- **Live composition** composited / scrubbed with playhead (not a second encode window as the hero)  
- Transport: prev beat · play beat · next beat · respect autoplay-on-select  
- Poster + name of assigned golden visible  

---

## 7. Reveal frame UX — **LOCKED**

Humans must not convert “words → clock → frames” by hand.

| Affordance | Behavior |
| --- | --- |
| **Arm a line** | Select row in lines list |
| **Click spoken word** | Beat-only word chips; set `revealFrame` = that word’s transcript `startFrame`; seek playhead |
| **Fine-tune nudges** | Same pattern as transcript editor: **±1 / ±5 / ±10** frames on armed line |
| **Pin to playhead** | Scrub/play source; pin current frame onto armed line |
| **Go / seek** | Jump player to a line’s reveal frame |
| **Display** | Show frame number + timecode for armed line / playhead |

Authority remains **frames**; UI works in speech + playhead + nudges.

---

## 8. Stage 3 UI — single-beat studio — **LOCKED**

**Reference mockup:** session `images/6.jpg` (craft left, live preview right).

**One beat at a time.** No Stage 1/2 transcript stream, no full beat list. Graphics/beats already locked in from earlier stages.

| Region | Content |
| --- | --- |
| **Craft panel (LEFT · primary)** | **Placement · beat N of M** · golden poster · layout/engine · line rows (arm by click) · **±10/5/1 frame hero** for armed line · Save / Lock · Pin to playhead · spoken word chips |
| **Live preview (RIGHT)** | Live Tier B HyperFrames for **this** beat only · badge “Live preview · HyperFrames · no encode” |
| **Transport (under preview)** | Prev · Play beat · Next · Autoplay |
| **Top stage rail** | Place · Final · lock count — no workspace status banner |

The left craft panel is the **critical** fine-tune surface (copy + reveal frames). The right player is for judging those edits live.

List engines: **Add line** / remove within `list_max` (dependency-stack **6** nodes, etc.).

---

## 9. Lock & final — **LOCKED**

| Action | Rule |
| --- | --- |
| **Lock** | Human marks beat ready for episode render |
| **Unlock** | Edit again; change usage/engine; re-draft that beat after unlock |
| **Re-Place** | Overwrites **unlocked** only; **never** locked |
| **Final** | Enabled only when every **assigned** placement has `locked: true` |
| **Final output** | One full re-render of locked cut with all locked placements (same engines as library samples) |

Unassigned beats (no golden) do not require a placement lock.

---

## 10. Draft algorithm (deterministic)

For each assigned unlocked beat:

1. Resolve `engineId` from usage  
2. Span ← beat frames  
3. Seed lines from `wordsText` + engine fixed/list slots  
4. Stagger `revealFrame` across span (human will refine)  
5. Default motion/meta; **never** kicker  
6. Skip locked on re-Place  

---

## 11. Implementation map

| Piece | Location | Status |
| --- | --- | --- |
| 18-engine slot specs | `ENGINE_REGISTRY` (`app/core/visual_production.py`); `placement_roles.py` derives | **BUILT** |
| Draft / save / lock / artifacts | `app/core/placement.py` | **BUILT** (v1) |
| HTTP | `POST …/placement/run`, `PUT …/placement/beat`, `POST …/placement/preview` | **BUILT** |
| Stage 3 UI studio | `web/app/visual-package.tsx` | **BUILT** — images/6 layout: craft left (primary), live preview right; word chips + ±1/5/10; no transcript wall |
| Live composition preview | HyperFrames single-beat workspace + player scrub | **BUILT** — Tier B hyperframes-player; rebuild on select/edit |
| Final full render from placements | Engine package path | **Not built** (gate ready) |

---

## 12. Deferred (explicit)

| Item | Owner |
| --- | --- |
| Remove kicker CSS/markup from engines that still draw eyebrows | Operator / later eng pass |
| Stitch beat encodes as alternate final | Not product path |
| Tier A sticker preview path | Rejected |
| LLM copy for lines | Not core path |

---

## 13. Success criteria

- Single-beat Placement studio; placement controls are the hero  
- Lines + revealFrame for all list/fixed slots; add/remove within max  
- Reveal set via words + nudges + playhead (no mental fps math)  
- Live Tier B preview for **all 18** engines after nudge — no encode wait  
- Explicit lock; Final only when all assigned locked  
- Final = one full re-render  
- No kicker in content path  
