# Placement-perfected engines

**Purpose:** Track which of the active placement engines have been human-reviewed in Stage 3 with live preview and accepted as “good enough to ship” for daily production.

**Active count:** 20 engines in `ENGINE_REGISTRY` (`app/core/visual_production.py`).  
(Originally framed as “18”; `speaker-side-panel` was retired → `dependency-stack`; `numbered-phrase-reveal`, `intro-credentials`, `windows-prompt-overlay` added 2026-08.)

**Status legend**

| Status | Meaning |
| --- | --- |
| **Perfected** | Reviewed in Placement; look + timing + craft UI accepted |
| **In progress** | Actively tuning |
| **Not started** | Not yet reviewed as a placement craft pass |

Update this file when a graphic is accepted (or reopened). Prefer engine ids from `ENGINE_REGISTRY`.

---

## Perfected (17)

Reviewed during Stage 3 placement polish (session through 2026-08).

| Engine id | Notes / what was locked in |
| --- | --- |
| `brand-cta-lockup` | Brand-fixed join line + skool link forever; no placement copy fields; logo brand-fixed |
| `dependency-stack` | Title + nodes land on placement revealFrames (not redistributed); settle/linger shrink to fit; Ends = undock; locked in placement |
| `kinetic-word-punctuation` | Magenta stamp (pink box + phrase) lands together at phrase revealFrame; no empty shell at beat start |
| `numbered-example-card` | Accepted in placement review; card animates in place without moving/scaling source footage |
| `numbered-step-intro` | Number + title one teal headline; larger pink action; showNumber toggle; stepNumber coerce for schema |
| `problem-card-triptych` | Three cards land on placement revealFrames (no redistrib); pink handoff / white settle; settle/linger shrink to fit |
| `progress-scale` | Title / Start / Target / Stop lines; bar fill syncs to stop reveal frames; word chips under right-column graphic card |
| `punchline-reveal` | Stage/dock at beat start; whole card (borders + image + caption) at Title; Ends = undock frame (default beat end); full-beat preview after Ends |
| `robot-cheer` | Accepted in placement review |
| `robot-defiant` | Accepted in placement review |
| `robot-roast` | Accepted in placement review |
| `robot-rocket-sign` | Accepted in placement review |
| `source-punch-zoom` | Zoom in / Zoom out absolute frames; one-shot preview (no loop); schema allows frame anchors |
| `speaker-rise-callouts` | Thesis + up to 8 pink edge callouts; revealFrames honored; face-clear layout; bottom slots raised |
| `tradeoff-meter` | No kicker; value meta 0–1 (coerced); knob fixed at value; fill grows to marker and lands at verdict revealFrame |
| `ui-callout` | Label only (no detail); meta x/y/width/height → targetBounds; studio 10×10 teal tenths grid toggle (craft aid only) |
| `windows-prompt-typing` | Accepted as-is: head docks right, Windows terminal types `prompt` over speech window (~13 cps floor); letter GSAP + caret; no per-char craft |

---

## Retired

| Engine id | Superseded by | Notes |
| --- | --- | --- |
| `speaker-side-panel` | `dependency-stack` | Removed 2026-08 — duplicative title+bullets+docked-head stage; old plans alias to dependency-stack |

---

## Not started (3)

| Engine id | Notes |
| --- | --- |
| `numbered-phrase-reveal` | Shipped production engine 2026-08 (white stage, teal `numberLabel`, black upper-right dock frame, magenta char-typed `text`). Placement craft review still open; promote in Graphics Library when accepted. |
| `intro-credentials` | Shipped 2026-08 for host intros: head docks LEFT; right name + experience bullets; large Thai Wai robot thank-you after settle. Placement craft review open. |
| `windows-prompt-overlay` | Shipped 2026-08: same CLI typing as windows-prompt-typing, but overlay-only (no dock/mask); terminal centered horizontally. Placement craft review open. |

---

## How to update

When you accept another graphic in Placement (or reopen one):

1. Move its row from **Not started** (or **In progress**) into **Perfected**, or reopen into **In progress**.
2. Add a one-line note on what was locked (timing, UI, known limits).
3. Optionally note follow-ups under that row if something is deferred but the graphic is still “good.”

This list is a **craft/review checklist**, not Graphics Library golden status. A usage can be golden in the library and still not placement-perfected, or vice versa.
