# VCG Graphics Process

**Home for the new daily graphics production path.**  
Everything else under `docs/` is older, parallel, or historical unless this folder says otherwise.

This folder stays **small on purpose**: only durable product authority. No explainer spam.

| File | Role |
| --- | --- |
| **This README** | Goal, stages, what is real, product stance |
| [architecture.md](./architecture.md) | **APPROVED** engine / usage / placement / assignment vernacular |
| [beat-universe.md](./beat-universe.md) | **APPROVED** portable beat contract (13 types + spotting rules only) |
| [assignment.md](./assignment.md) | **APPROVED** Stage 2 assignment design (algorithm + UI + artifacts) |
| [scenelayer.md](./scenelayer.md) | **APPROVED** Stage 2 layout label per beat (before Assign) |
| [placement.md](./placement.md) | **APPROVED / LOCKED** Stage 3 (studio UI, live Tier B, reveal UX, lock, final) |

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
[2] Scenelayer → Assignment           → layout per beat, then golden usages ([scenelayer.md](./scenelayer.md), [assignment.md](./assignment.md))
[3] Placement                         → lines + reveal frames, lock, full render ([placement.md](./placement.md))
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

Do not invent frame numbers. Edit word anchors in the UI; frames always re-resolve from the transcript.

### Full speech act (binding for Stage 1)

Beats must **not** be 4–5 word keyword snippets (any type).

- Word span = **full spoken delivery of that job** (viewer-understandable moment).
- Optional short `span` / label = human title only — never a substitute for the word span.
- Sparse **count** of beats is correct. Sparse **word spans** are not.
- Full type-by-type span rules live in the Masterbeater skill (not duplicated here).

### Production artifacts

On the private video project root:

- `masterbeater-beats.json` — **original** agent suggestion (`schemaVersion` 2). Never overwritten by the review UI.
- `masterbeater-beats-reviewed.json` — **working copy** the UI edits (auto-saved on membership + structure changes).
- `masterbeater-edit-ledger.json` — append-only log of human edits (for future process learning).
- `masterbeater-raw.json` — optional debug dump from in-app API runs (stdout/stderr/parsed).

Shape (original / reviewed): `agent`, `mode`, `timingAuthority`, `fps`, `beats[]` (type, word IDs, frames, `wordsText`, rationale, optional label), `gaps`, `notes`.

---

## Daily run process (tight)

**Goal:** One reliable path from locked transcript → reviewable beats. No one-off scripts, no free-form JSON inventing frames.

### Prerequisites

1. Private video project open.
2. **Locked cut** available (preferred stage source).
3. **Final transcript** exported (`transcripts/final-transcript.json` with word IDs + frames).

If either is missing, stop. Do not label against a draft transcript.

### Canonical path (use this)

| Step | Who | What |
| --- | --- | --- |
| 1. Label | **Grok + `masterbeater` skill** | Load skill + [beat-universe.md](./beat-universe.md). Point at the project’s **final transcript word index**. Return **anchors-only** JSON: `mode`, `beats[]` with `id`, `beatType`, `startWordId`, `endWordId`, `rationale`, optional `span` / `gaps`. |
| 2. Normalize | **App** (`normalize_masterbeater_result`) | Bind word IDs → frames + exact `wordsText`. Drop invalid beats into `gaps` with reasons. Write **`masterbeater-beats.json`** (original). |
| 3. Review | **Human** in Visual Package | Refresh → edit membership + structure → auto-save to **reviewed** + **ledger**. Original stays untouched. |

**Binding output rule for the agent:** only word IDs and labels — never invent `startFrame` / times as authority. The app is the only resolver.

### Practical host workflow (today)

1. Open a Grok session with the **masterbeater** skill on the project.
2. Confirm transcript path and that word IDs look like `w000001` (copy exactly, keep zeros).
3. Produce the anchors-only JSON (full speech acts, sparse beat *count*).
4. Hand off through app normalize so production fields are filled:
   - Preferred long-term: single **import/normalize** into the open project (see *Tighten further* below).
   - Until that exists: same normalize path used by `POST /api/visual-package/masterbeater/run` and unit helpers — **do not** hand-edit frames into `masterbeater-beats.json`.
5. Visual Package → **Refresh** → review.

### In-app “API run” (experimental only)

| | |
| --- | --- |
| **UI** | Visual Package Stage 1 → **API run** |
| **API** | `POST /api/visual-package/masterbeater/run` |
| **What it does** | Bundles skill + beat universe + full word index → Grok CLI (`--json-schema`, short turn budget) → parse → normalize → write original |
| **Status** | **Experimental.** Quality and reliability trail a focused skill-host pass on long cuts (prompt size, turn budget, CLI packaging). |
| **Use when** | Quick smoke on a short project, or no host session available. Prefer skill host for production drafts. |

Do not treat a weak API run as “Masterbeater failed forever” — re-run via skill host with the same transcript.

### Re-run policy

| Action | Effect |
| --- | --- |
| New Masterbeater run (skill or API) | Rewrites **`masterbeater-beats.json`** (original suggestion). |
| Review UI edits | Touch **only** `masterbeater-beats-reviewed.json` + ledger. |
| After a re-run | **Refresh.** Working set is reviewed if present, else original. A stale reviewed copy can disagree with a new original — delete or replace reviewed deliberately when accepting a fresh draft. |

Never “fix” original by pasting human edits into `masterbeater-beats.json`.

### APIs (Stage 1)

| Endpoint | Role |
| --- | --- |
| `GET /api/visual-package/status` | Project readiness + original / reviewed / ledger presence |
| `GET /api/visual-package/source-video` | Locked-cut (or preferred) video for the player |
| `POST /api/visual-package/masterbeater/run` | Experimental end-to-end LLM run → original |
| `PUT /api/visual-package/masterbeater/beats` | Auto-save reviewed + ledger only |

---

### Visual Package UI (Stage 1) — **review editor**

**Built:**

- Tools → Visual Package stage rail (Stage 1 active)
- Load status for active project (`beatCount`, original/reviewed/ledger, fps, etc.)
- Inline transcript stream: beat cards + yellow gap blocks
- **Select-only** word clicks; **↑ / ↓** for membership (gap → neighbor beat; in-beat → eject to gap)
- Multi-word selection for phrase moves
- **Beat structure:** change type, add from selection, delete, merge with neighbor, split after selection
- Auto-save each change to `masterbeater-beats-reviewed.json` + append ledger entry
- Original `masterbeater-beats.json` preserved
- Source video: seek to beat, play span, **loop beat**, **autoplay on select** (pill toggles, not native checkboxes)

### Proven

- Project `2026-07-23-15-33-08` used as the Stage 1 test bed.
- Keyword-snippet pass replaced with a **full speech-act** pass (longer spans across **all** types, including `example` and `prompt`).
- Review editor is good enough for daily human correction; remaining Stage 1 gaps are quality-of-life only.

---

## What is real right now

| Thing | Status |
| --- | --- |
| 13 beat types | **APPROVED** — [beat-universe.md](./beat-universe.md) |
| Full speech-act span policy | **APPROVED** in Masterbeater skill (all types) |
| Timing: word IDs → app frames | **BUILT** |
| Masterbeater normalize + project write | **BUILT** — `app/core/masterbeater.py` |
| Visual Package Stage 1 **viewer** | **BUILT** |
| Visual Package Stage 1 **editor** | **BUILT** — membership + structure + auto-save |
| Daily run path | **Skill host label → app normalize → review** (canonical) |
| In-app Masterbeater LLM run | **Experimental** — skill host preferred for quality |
| Plan JSON + validator | **BUILT** in code — not daily workflow |
| Graphics Library (usages + engines) | **BUILT** surface |
| Assignment design (Stage 2) | **APPROVED** — [assignment.md](./assignment.md) |
| Assignment (deal + UI + artifacts) | **BUILT** — type + layout filter, card poster/name, original/working/ledger |
| Scenelayer | **BUILT** — Stage 2 button before Assign; layout dropdown; artifacts |
| Placement design | **APPROVED / LOCKED** — [placement.md](./placement.md) §2 decision table |
| Placement (draft, lines, lock APIs) | **BUILT** — Place / Save / Lock; Final gated |
| Placement studio UI + live Tier B preview + reveal nudges | **BUILT** — single-beat studio, word chips, ±1/5/10, pin, live HyperFrames |
| Final full episode render | **Not built** — gate ready when all locked |
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
| Stage 1–2 UI | `web/app/visual-package.tsx` |
| Assignment deal + artifacts | `app/core/assignment.py` |
| Scenelayer classify + artifacts | `app/core/scenelayer.py` |
| Allowed plan shape + beat types | `visual-production/schemas/editorial-beats.v1.schema.json` (`schemaVersion: 2`) |
| Validate a plan | `app/core/editorial_beats.py` · `python scripts/editorial_beats.py validate --plan …` |
| Production graphics set | Graphics Library golden usages (`app/core/graphics_library.py` + UI) |
| Engine interface declarations (single source) | `ENGINE_REGISTRY` in `app/core/visual_production.py` — placement/library views derive from it |

Do not add process docs that only restate those paths.

---

## Deliberate next focuses

1. **Final full-episode render** from locked placements (gate ready; encode path next).
2. **Final full render** from locked placements.
3. **Deferred:** engine kicker CSS cleanup (operator); goldens coverage.

### Tighten the run further (**proposed** eng — not approved until scheduled)

Process is already tight if skill host + normalize + review are followed. Remaining friction is **handoff**, not labeling rules:

| Improvement | Why |
| --- | --- |
| **Import / normalize-only API + UI** | Accept anchors-only JSON for the active project → normalize → write original. Removes one-off scripts and “did we paste frames?” mistakes. |
| **Clear re-run UX** | Warn when reviewed exists; option to keep reviewed, reset reviewed, or archive previous original. |
| **Surface drop reasons** | If normalize drops beats, show `gaps` / drop sample in Visual Package (already stored on the result). |
| **API-run reliability** | Only if daily use needs it: larger turn budget, chunked long transcripts, fail loud when Grok CLI missing — still secondary to skill host. |

Do not invent parallel run pipelines. One normalize path; two producers (skill host preferred, API experimental).

---

## Deferred (explicit, not forgotten)

| Item | Why deferred | When it matters |
| --- | --- | --- |
| **In-app original vs reviewed diff UI** | Original + reviewed + ledger already on disk; daily review uses the working stream. | Process audits, teaching the skill from systematic human fixes. |
| **Keyboard-first edit loop** | Mouse select + structure strip is fast enough for current volume. | High-volume review days / power-user speed. |
| **Process refinement from the ledger** | Ledger is append-only capture only; no analytics yet. | After enough reviewed episodes to spot repeated agent mistakes. |
| **Joke image aspect ratio / generation contract** (`punchline-reveal` with `imageAssetId`) | Layout is fixed: head docks left (~42%×78% tall frame), art + caption panel on the right (~40% width × ~84% height). Custom generated images need a known ratio for `object-fit: cover`. | Before daily joke cards or any “generate joke still” helper. Measure live media box → publish target aspect + safe margins → wire gen. |

Do not invent ad-hoc ratios per episode. Land one contract, then sample.
