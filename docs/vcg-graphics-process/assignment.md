# Assignment (Stage 2)

**Status: APPROVED (2026-08-02)**  
**Product design for Visual Package Stage 2.** Implementation follows this contract.

Related: [README.md](./README.md), [architecture.md](./architecture.md), [beat-universe.md](./beat-universe.md).

---

## 1. One-line job

After Masterbeater: for each beat, pick a **golden** Graphics Library **usage** that fits the beat type. Human can override. No drawing, no placement copy/timing.

```text
Reviewed beats  ×  golden usages  →  usageId per beat (draft kit)
```

**Not Assignment:** labeling speech (Stage 1), engine draw, instance copy, voice-synced timing channels (placement, later).

---

## 2. Product stance

| Layer | Expectation |
| --- | --- |
| **Algorithm** | Deterministic code (no agent). Filter by beat type; deal for variety. |
| **Human** | May swap the graphic on a beat; overrides are sticky on re-run. |
| **Software priority** | Fast, obvious Stage 2 review on the same beat cards — not “AI picks better if I re-run.” |

Re-running Assignment only reshuffles algorithm picks. It is **not** a quality ladder.

---

## 3. Eligibility

**Layout filter:** beat’s `layoutId` (from [scenelayer](./scenelayer.md) working copy) must be in the usage’s `allowedLayouts`.

A usage is eligible for a beat when **all** of:

1. `status === golden`
2. Beat’s `beatType` is in the usage’s `beatTypes`
3. Beat’s `layoutId` is in the usage’s `allowedLayouts`

If the beat has no `layoutId`, or no golden matches type+layout → that beat stays **unassigned** (no invented graphic).

Production set = Graphics Library usages with `status === golden` only. Candidates never assign.

**UI order (Stage 2 rail):** **Scenelayer** button, then **Assign** button. Run scenelayer before assign on a fresh project.

---

## 4. Deal algorithm (binding)

Deal is in **transcript / beat list order**. Variety bags are keyed by **(beatType, layoutId)** so different layouts do not share a bag.

For each beat in order:

1. Eligible pool = goldens matching that beat’s type **and** layout (see §3).
2. Bag for that `(beatType, layoutId)`: if empty, **refill** with the full eligible pool for that pair.
3. Pick **uniformly at random** from the bag, assign, **remove** from the bag.
4. No layout or empty pool → unassigned.

No preference weights in v1. No cross-type variety rules beyond per-type bags.

### Re-run (same Assign button again)

| Beat state on working copy | On re-run |
| --- | --- |
| `source: human` (manual override) | **Keep** |
| `source: algorithm` or empty / unassigned | **Re-deal** with the algorithm above |

Original artifact is **not** rewritten by re-run or by UI edits (see §5).

---

## 5. Artifacts (project root)

Same pattern as Masterbeater: immutable first algorithm output + working copy + append-only human ledger.

| File | Role |
| --- | --- |
| `assignment.json` | **Original** — first successful Assign run. UI must not overwrite with casual edits or re-runs. |
| `assignment-reviewed.json` | **Working** — what Stage 2 shows and edits. |
| `assignment-edit-ledger.json` | **Ledger** — append-only human overrides for process learning. |

Suggested entry shape (implementation may extend fields; product meaning is fixed):

```json
{
  "agent": "assignment",
  "schemaVersion": 1,
  "beats": [
    {
      "beatId": "beat-001",
      "usageId": "some-golden-usage-id",
      "source": "algorithm"
    }
  ]
}
```

| Field | Meaning |
| --- | --- |
| `beatId` | Masterbeater beat id |
| `usageId` | Graphics Library usage id, or null / omitted if unassigned |
| `source` | `algorithm` \| `human` |

**Working UI display** resolves `usageId` → `displayName` + poster from the live library (do not snapshot poster pixels into the assignment file unless needed later for offline audit).

### Write rules

| Event | Original | Working | Ledger |
| --- | --- | --- | --- |
| First Assign (no original yet) | Write full deal | Same deal | Unchanged (empty) |
| Re-run Assign | **Unchanged** | Re-deal non-human only | Unchanged |
| Human swap on a beat | **Unchanged** | Update that beat (`source: human`) | Append entry (from → to) |

Never paste human edits into `assignment.json`.

---

## 6. UI (Visual Package Stage 2)

**Where:** Stage 2 of the top workflow rail (graphic pass / assignment).

**Control:** **Assign** button (user must press). No auto-run on open.

**Stream:** Same beat cards as Stage 1 review.

**Per card (right side):**

- Assigned: usage **display name** + **poster**
- Unassigned: empty / “no graphic”

**Manual override:** user can change the pick among **eligible goldens for that beat type** only. That sets `source: human` and appends a ledger entry.

**Stage 1 edits after assign:** out of scope for deep merge rules in v1. Practical v1: if beat set changes materially, human re-runs Assign (human locks kept where `beatId` still exists). Document any stronger merge only if product needs it later.

---

## 7. APIs (built)

| Concern | Endpoint / location |
| --- | --- |
| Run assign | `POST /api/visual-package/assignment/run` |
| Load status / working | `GET /api/visual-package/status` → `assignment` block |
| Save human swap | `PUT /api/visual-package/assignment/override` |
| Library | golden usages + posters via Graphics Library |

Code homes:

- Matcher + artifacts: `app/core/assignment.py`
- HTTP: `app/web_api.py` under `/api/visual-package/…`
- UI: Stage 2 in `web/app/visual-package.tsx`

---

## 8. Explicitly out of scope (v1)

| Item | When |
| --- | --- |
| Layout-aware eligibility | **Required** via [scenelayer.md](./scenelayer.md) (not optional long-term) |
| Placement (copy, timing channels, span on cut) | Stage 3 |
| Engine draw / render | After placement |
| In-app original vs working diff UI | Nice-to-have |
| Ledger analytics | After enough episodes |
| Weighted / learned pick order | After ledger learning |
| Agent / LLM assignment | Never for this stage (rejected) |

---

## 9. Success criteria

- Press **Assign** once → every beat with library coverage gets a golden usage; variety within type via bag deal.
- Cards show name + poster on the right in Stage 2.
- Manual swap sticks across re-run; algorithm picks can reshuffle.
- First algorithm output remains on disk as original; working + ledger track human path.
- No candidate usages appear in production assignment.
