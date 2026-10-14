# Insert clips (Stage 4)

**Status: APPROVED (2026-08-19 product; 2026-08-20 UI / audio / markers)**  
**Visual Package Stage 4** — program edit list after graphics lock.

Authority: [architecture.md §5.3](./architecture.md#53-insert-clips-are-a-program-edit-list-approved-2026-08-19).  
Not overlay B-roll ([§5.2](./architecture.md#52-overlay-b-roll-is-an-engine-approved-2026-08-19)). Not a locked-cut re-export.

---

## One-line job

After every assigned placement is **locked**, split the **show** by dropping clips at legal T points on the locked-cut clock. Preview seeks the piece under the playhead. One **Final** encodes the program list and publishes `exports/final-video.mp4`.

---

## Locked decisions (2026-08-20)

| # | Decision |
| --- | --- |
| S4-1 | Stage 3 **locks** graphics only. **Final** lives on Stage 4. |
| S4-2 | HyperFrames full-cut encode is a **private A-roll master** (`working/placement-final/a-roll-master.mp4`). It is not the published file. |
| S4-3 | Delivery Final concatenates A-roll slices + insert clips. Zero inserts = stream-copy the A-roll master to `exports/final-video.mp4`. |
| S4-4 | Live preview seeks the piece under the playhead (A-roll range or clip). No episode preview MP4. Stage 4 shows the Transcript Edit **Cut timeline** chrome on the locked-cut clock (legal gaps vs beat interiors, insert markers). ±1/±5/±10 frame nudges move Insert T, skipping illegal frames. |
| S4-5 | Insert audio **plays**. Per-insert **mute** is optional. A-roll audio does not continue under an insert. Overlay B-roll stays muted on the cut clock. |
| S4-6 | Program-transcript marker = insert **display name** (default clip filename). Rename on the insert row. No chapter field. |
| S4-7 | Legal T: locked-cut frame **not strictly inside** a beat `[startFrame, endFrameExclusive)`. Boundaries, pre-roll, gaps, and post-last-beat are allowed. Several inserts may share a T (list order). |
| S4-8 | Mid-sentence / mid-graphic T is out of v1. Locked graphics stay whole and shift on the program clock. |

Supersedes Placement §9 publishing `exports/final-video.mp4` from Stage 3. The graphics encode itself is unchanged (one full HyperFrames pass on the locked cut).

---

## Artifacts

| File | Role |
| --- | --- |
| `visual-production/program-edits.json` | Ordered inserts (T, clip, in-point, mute, display name) |
| `working/placement-final/a-roll-master.mp4` | Private graphics-on-cut encode |
| `transcripts/program-transcript.json` | Derived transcript on the **program** clock |
| `exports/final-video.mp4` | Program delivery |

---

## Insert row

```json
{
  "id": "ins_ab12cd",
  "tFrame": 900,
  "videoAssetId": "pexels-123",
  "clipStartSec": 0.0,
  "durationSec": 5.0,
  "muted": false,
  "displayName": "auth-flow.mp4"
}
```

Clip source is the same frozen placement store as overlay (local / library / Pexels). `clipStartSec` is the in-point. `durationSec` is the used length (default: rest of the file). Overlay engine is not used.

---

## Program transcript

- A-roll words keep locked-cut word IDs; times shift by total insert duration with `tFrame <= word.start_frame`.
- Each insert starts with a marker word (`ins:{id}:marker`) whose text is the display name.
- Unmuted clips with speech: transcribe **that clip** and splice words at program times. Word IDs are `ins:{id}:w:{n}` and must not collide with A-roll IDs.
- Muted or silent clips: marker only.

---

## Final

1. Ensure A-roll master (reuse when placement fingerprint + quality match).
2. Encode the program list once (FFmpeg concat; identity copy when there are no inserts).
3. Write `transcripts/program-transcript.json`.
4. Publish `exports/final-video.mp4`.
