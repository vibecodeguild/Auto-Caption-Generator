# Scenelayer (Stage 2 — before Assignment)

**Status: APPROVED (2026-08-02)**  
**Product design.** Labels each Masterbeater beat with one OBS capture layout so Assignment can filter goldens.

Related: [README.md](./README.md), [architecture.md](./architecture.md), [assignment.md](./assignment.md).

---

## 1. One-line job

For each beat, look at the **first frame** of that beat on the locked cut, decide which of the **8 OBS layouts** is active, and store that on the beat for review and for Assignment.

```text
Beats + first frame → layoutId per beat → human may fix via dropdown → Assignment filters
```

**Not scenelayer:** placement, speaker safety math, free zones, copy, timing, engine draw.  
Geometry (`scene-geometry.json`) remains authority for **what each layout means**; scenelayer only **names** which layout is under the beat.

---

## 2. Product stance

| Layer | Expectation |
| --- | --- |
| **Algorithm** | Deterministic code (no agent). Closed set of 8 layout ids. |
| **Human** | Dropdown on the beat card to correct a wrong auto label. |
| **Assignment** | Uses `layoutId` as a hard filter with beat type + bag deal. |

---

## 3. Closed layout set (binding)

Same ids as Graphics Library / OBS catalog:

- `full-screen-talking`
- `talking-left`
- `talking-right`
- `talking-bottom-left`
- `talking-bottom-right`
- `talking-top-left`
- `talking-top-right`
- `computer-screen-only`

Do not invent layout names.

---

## 4. Sample rule

- **Frame:** first frame of the beat (start of beat span on the preferred review video / locked cut).
- **Output:** one `layoutId` per beat (or unassigned if classification fails — do not invent).

Classifier (implementation):

1. **Primary:** compare the beat’s **first frame** to a **static full-frame screenshot** of each OBS layout (not video-to-video). Screenshots live in the Graphics Library under  
   `layout-refs/{layoutId}.png` (also `.jpg` / `.webp`).  
   Match = **edge-map** structure (OBS chrome), not raw color — so lighting/content in the clip doesn’t dominate.
2. **Temporary fallback:** if a screenshot is missing, one frame may be taken from `layout-clips/{layoutId}.mp4` until the still exists.
3. **Last resort:** OBS geometry heuristics only when no reference still/clip exists for the winning layout set.

**Operator work:** drop **one screenshot per layout** for all eight OBS ids. Complete coverage is what makes Scenelayer reliable — geometry alone is a weak backup.

---

## 5. UI (Visual Package Stage 2 rail)

**Stage 2** of the top workflow rail, controls in this order:

1. **Refresh** (as needed)
2. **Scenelayer** — run layout labeling for all beats  
3. **Assign** — deal goldens (requires layouts where filtering needs them)

Scenelayer is **button-only** (no auto-run on open), same spirit as Assign.

**Beat cards:** show a **layout dropdown** (the eight ids). Auto fill after Scenelayer; user can change.

Stage 1 membership editing stays Stage 1. Stage 2 focuses on layout + assignment chrome (name/poster already on cards for assignment).

---

## 6. Artifacts (project root)

Same pattern as Masterbeater / Assignment:

| File | Role |
| --- | --- |
| `scenelayer.json` | **Original** first algorithm pass. UI does not overwrite with casual edits or re-runs. |
| `scenelayer-reviewed.json` | **Working** copy (human dropdown overrides). |
| `scenelayer-edit-ledger.json` | Append-only human layout changes. |

Suggested entry shape:

```json
{
  "agent": "scenelayer",
  "schemaVersion": 1,
  "beats": [
    {
      "beatId": "beat-001",
      "layoutId": "talking-left",
      "source": "algorithm"
    }
  ]
}
```

| Field | Meaning |
| --- | --- |
| `beatId` | Masterbeater beat id |
| `layoutId` | One of the eight, or null if unknown |
| `source` | `algorithm` \| `human` |

### Write rules

| Event | Original | Working | Ledger |
| --- | --- | --- | --- |
| First Scenelayer run | Write full labels | Same | Empty / unchanged |
| Re-run Scenelayer | **Unchanged** | Re-classify only non-human rows | Unchanged |
| Human dropdown change | **Unchanged** | That beat `source: human` | Append |

---

## 7. Handoff to Assignment

Assignment eligibility (updated):

1. Usage `status === golden`
2. Beat `beatType` ∈ usage `beatTypes`
3. Beat `layoutId` ∈ usage `allowedLayouts`

If a beat has no `layoutId`, it stays **unassigned** for that run (no invented graphic). Prefer running **Scenelayer before Assign** on a fresh project.

Re-run Assign still keeps human *usage* overrides; layout comes from scenelayer working copy at deal time.

---

## 8. Explicitly out of scope

| Item | Notes |
| --- | --- |
| Placement | Separate stage |
| Using scenelayer for free-zone math | Later / placement |
| Agent / LLM classification | Rejected |
| Layouts other than the eight | Rejected |

---

## 9. Success criteria

- Stage 2 rail: **Scenelayer** button before **Assign**.
- One press labels beats from first frames with the eight OBS ids.
- Cards show layout dropdown; human fixes stick on re-run.
- Assign only deals goldens allowed for that layout (and type).

---

## 10. Implementation map (built)

| Concern | Location |
| --- | --- |
| Classifier + artifacts | `app/core/scenelayer.py` |
| Run | `POST /api/visual-package/scenelayer/run` |
| Override | `PUT /api/visual-package/scenelayer/override` |
| Status | `GET /api/visual-package/status` → `scenelayer` |
| UI | Stage 2 rail + card layout dropdown in `web/app/visual-package.tsx` |
