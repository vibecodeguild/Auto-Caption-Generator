# VCG Graphics Process

**Home for the new daily graphics production path.**  
Everything else under `docs/` is older, parallel, or historical unless this folder says otherwise.

This folder stays **small on purpose**: only durable product authority. No explainer spam.

| File | Role |
| --- | --- |
| **This README** | Goal, stages, what is real, product stance |
| [architecture.md](./architecture.md) | **APPROVED** engine / usage / placement / assignment |
| [beat-universe.md](./beat-universe.md) | **APPROVED** portable beat contract (13 types + spotting rules only) |

Stage 1 skill (Grok): **`masterbeater`** — `.grok/skills/masterbeater` — loads [beat-universe.md](./beat-universe.md).

---

## Goal

For every **locked cut + final transcript**, produce professional VCG finishing graphics with a **repeatable** process—not free-form invention and not multi-day thrash.

### Product stance (accepted working model)

| Layer | Expectation |
| --- | --- |
| **Masterbeater** | Strong **first draft** of ordered beats |
| **Human** | Will still adjust types, boundaries, splits/merges, drops, and adds |
| **Software priority** | Make that human correction **fast and precise** — not “AI never needs me” |

Perfect zero-touch labeling is **not** the near-term goal. Efficient review is.

---

## Stages

```text
[0] Locked cut + final transcript     (existing product)
[1] Masterbeater                      → ordered beats (speech jobs)
[2] Assignment (later)                → match beats → golden usages (when/where)
[3] Placement (later)                 → instance copy + timing on this cut
[4] Engine draw                       → same production engine as library samples
[5] Review → fix → export
```

**Vernacular (approved 2026-08-01):** **engine** · **usage** · **placement** · **assignment** · **graphics library**.  
Usage **has-a** engine (not identity-coupled). `golden` = usage status only. Never “GR” / “module” / “seed” in product language.  
Authority: [architecture.md](./architecture.md).

**Golden lock (approved 2026-08-01):** brand/type **defaults apply while authoring `candidate` usages**. Promoting to **`golden` locks that usage’s size/position language** (sample is proof). Daily production assigns and places goldens — it does not re-skin them. Change the look only by demote → refine → re-promote. Full rule: [architecture.md §5.1](./architecture.md#51-candidate-authoring-vs-golden-lock-approved-2026-08-01).

**Library metrics:** Graphics Library → **Metrics** tab shows usage counts by beat type and by allowed layout (including zero rows for coverage gaps). API: `GET /api/graphics-library/metrics`.

---

## Stage 1 — Masterbeater (what exists)

### Authority

| Piece | Role |
| --- | --- |
| [beat-universe.md](./beat-universe.md) | Only allowed beat types (13) |
| `.grok/skills/masterbeater` | How to label + **full speech-act** word spans |
| App `app/core/masterbeater.py` | Normalize word IDs → frames / `wordsText` / production JSON |

### Timing contract (binding)

| Layer | Role |
| --- | --- |
| **Word IDs** (`startWordId`, `endWordId`) | What labeling produces (authoritative anchors) |
| **Frames** (`startFrame`, `endFrameExclusive`) | What the app resolves for handoff |
| **Seconds** | Human-facing only |
| **`wordsText`** | Exact transcript text between the word IDs (for review) |

Do not invent frame numbers. Edit anchors (when we add an editor); frames follow.

### Full speech act (binding for Stage 1)

Beats must **not** be 4–5 word keyword snippets (any type).

- Word span = **full spoken delivery of that job** (viewer-understandable moment).
- Optional short `span` / label = human title only — never a substitute for the word span.
- Sparse **count** of beats is correct. Sparse **word spans** are not.
- Full type-by-type span rules live in the Masterbeater skill (not duplicated here).

### Production artifact

On the private video project root:

- `masterbeater-beats.json` — production record (`schemaVersion` 2 shape via app normalize):  
  `agent`, `mode`, `timingAuthority`, `fps`, `beats[]` (type, word IDs, frames, `wordsText`, rationale, optional label), `gaps`, `notes`.

### How to run today

| Path | Notes |
| --- | --- |
| **Preferred for quality** | Grok session with **masterbeater** skill against the locked transcript → write/normalize into the project (or re-run a known-good project pass) |
| **In-app** | Tools → **Visual Package** → **Run Masterbeater** | LLM path exists but has been **fragile**; skill/host pass is the reliable kickoff |
| **Status / video** | `GET /api/visual-package/status`, `GET /api/visual-package/source-video` |
| **Run API** | `POST /api/visual-package/masterbeater/run` |

Requires active project with locked cut + final transcript. Preferred stage source is the locked cut when available.

### Visual Package UI (Stage 1) — **review, not edit**

**Built:**

- Tools → Visual Package stage rail (Stage 1 active)
- Load status for active project (`beatCount`, path, fps, etc.)
- Beat list + type filter
- Selection: type, id, frames, clock times, word IDs, word count, full `wordsText`, label, rationale
- Source video player: seek to beat, play beat span (stop at end)
- Keyboard next/prev among filtered beats

**Not built (accepted gap):**

- Retarget start/end word
- Change type, delete/add, split/merge
- Save edits back to `masterbeater-beats.json`
- Keyboard-first edit loop

Human adjustment today still means editing the JSON or regenerating outside the app. **Next software investment for Stage 1** (not started): make boundary/type/drop/add fixes in-app and cheap.

### Proven

- Project `2026-07-23-15-33-08` used as the Stage 1 test bed.
- Keyword-snippet pass replaced with a **full speech-act** pass (longer spans across **all** types, including `example` and `prompt`).
- Viewer is good enough to judge quality; editor is the remaining Stage 1 product hole.

---

## What is real right now

| Thing | Status |
| --- | --- |
| 13 beat types | **APPROVED** — [beat-universe.md](./beat-universe.md) |
| Full speech-act span policy | **APPROVED** in Masterbeater skill (all types) |
| Timing: word IDs → app frames | **BUILT** |
| Masterbeater normalize + project write | **BUILT** — `app/core/masterbeater.py` |
| Visual Package Stage 1 **viewer** | **BUILT** — list, select, words/frames, play span |
| Visual Package Stage 1 **editor** | **Not done** — priority for efficient human correction |
| In-app Masterbeater LLM run | **Fragile** — Grok skill host preferred |
| Plan JSON + validator | **BUILT** in code — not daily workflow |
| Graphics Library (usages + engines) | **BUILT** surface — assignment/placement later |
| Full daily “go” button | **Not done** |
| Creator Production / old multi-agent VP essays | **Not** daily authority |

---

## Implementation map (code, not more markdown)

| Concern | Location |
| --- | --- |
| Beat universe (portable) | `docs/vcg-graphics-process/beat-universe.md` |
| Masterbeater skill | `.grok/skills/masterbeater/SKILL.md` |
| Normalize + status + run | `app/core/masterbeater.py` |
| HTTP | `app/web_api.py` — `/api/visual-package/*` |
| Stage 1 UI | `web/app/visual-package.tsx` |
| Allowed plan shape + beat types | `visual-production/schemas/editorial-beats.v1.schema.json` (`schemaVersion: 2`) |
| Validate a plan | `app/core/editorial_beats.py` · `python scripts/editorial_beats.py validate --plan …` |
| Production graphics set | Graphics Library golden usages (`app/core/graphics_library.py` + UI) |

Do not add process docs that only restate those paths.

---

## Deliberate next focuses

1. **Graphics Library** — Stage 2 material (usages + engines; user’s active track).
2. **Stage 1 editor** (when returning to beats) — retarget words, change type, delete/add, persist; keep frames derived from word IDs.
3. Later stages stay blocked on solid beats + a real graphic library, not more Stage 1 theory.

---

## Deferred (explicit, not forgotten)

| Item | Why deferred | When it matters |
| --- | --- | --- |
| **Joke image aspect ratio / generation contract** (`punchline-reveal` with `imageAssetId`) | Layout is fixed: head docks left (~42%×78% tall frame), art + caption panel on the right (~40% width × ~84% height). Custom generated images must be created to a known ratio so they crop well under `object-fit: cover` without cutting faces or punchlines. | Before daily production of joke cards, or before any “generate joke still” helper. Separate process: measure the live right-panel media box (post CSS), publish a target aspect + safe margins, then wire image gen / authoring to that. |

Do not invent ad-hoc ratios per episode. Land one contract, then sample.
