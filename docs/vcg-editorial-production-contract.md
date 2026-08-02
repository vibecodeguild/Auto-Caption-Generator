# VCG Editorial Production Contract

> **Do not start here.**  
> New process home: **[`docs/vcg-graphics-process/README.md`](./vcg-graphics-process/README.md)**  
> Beat types: **[`docs/vcg-graphics-process/beat-universe.md`](./vcg-graphics-process/beat-universe.md)**  
> This file is a **mixed-age proposed essay** (history only).

Status: **PROPOSED / historical** — superseded as the start-here by `docs/vcg-graphics-process/`  
Grounded in: successful published-era projects `2026-07-14`, `2026-07-20`, `2026-07-22`  
Not grounded in: Creator Production density spam, white-card sample shells, or salvaging a single past video

## 1. Product goal

Build a **robust, repeatable editorial process** that, for **every** new locked cut + transcript, produces professional VCG finishing graphics without multi-day agent thrash.

A single video is only a **validation run**. The system fails if it only works once with heroic babysitting.

**Done means:** same process tomorrow on a different video, in hours, at channel quality.

**Not the goal:**

- salvaging one specific already-published video;
- cloning one old timeline onto another file as the product;
- “a label every N seconds” as the creative model;
- a parallel Creator Production bureaucracy that never uses the Visual Production player/timeline;
- vibe-coded white cards that are not the VCG kit.

## 2. What already worked (evidence)

Observed production rates on successful projects:

| Project | Mode | Cues | Cues / min | Character |
| --- | --- | --- | --- | --- |
| 2026-07-14 | Talking-head packaging | 39 / ~12 min | ~3.3 | Punchlines, panels, stacks, **many holds** |
| 2026-07-22 | Tutorial overlays (Grok for Word) | 52 / ~14 min | ~3.7 | Example cards, prompt cards, emphasis, joke containers, face-safe composition |
| 2026-07-20 | Tutorial overlays (Grok for Excel) | 66 / ~12.5 min | ~5.3 | Callouts + prompt typing + steps (heavier on one shell) |

**Creative ceiling is roughly 3–6 designed scenes per minute**, not 15–20 word stickers per minute.

### 2.1 Talking-head mode (7/14 pattern)

- Primary visual is the speaker.
- Graphics are sparse and high-signal.
- Jokes and performance often keep **source primary** (no big card over the face), but still get **motion** (reframe, punchline kinetic, light edge hit) inside cadence — not a long static freeze.
- Punchlines land **when spoken**, not early.
- Side panels carry questions and supporting points without covering the face.

Example labels that worked:

- “HOW DO YOU START VIBE CODING?”
- “JUST START.”
- “NO SECRET. NO COURSE.”

### 2.2 Tutorial mode (7/22 pattern — default for Grok-for-X videos)

- Primary visual is often screen + speaker.
- Overlays are the main finishing language.
- Numbered example cards structure the video.
- Prompt cards summarize commands without reprinting walls of text.
- Compact emphasis carries theses and jokes.
- Kinetic hits land a few charged phrases.
- Custom HyperFrames composition may exist for face-safe variety, but **recipe identity and editorial labels remain explicit**.
- Joke containers are real designed beats (e.g. “WORD-MOGGING…”, “WORD FIGHTS YOU”, “EIGHTH GRADER…”, asset gags), not random words.

Example labels that worked:

- “10 WAYS TO GO FULL BEAST MODE”
- “GROK LIVES INSIDE WORD”
- “01 — TURN ROUGH NOTES INTO A POLISHED ONBOARDING GUIDE”
- “AN EIGHTH GRADER SHOULD GET IT”

## 3. Video modes (first decision in the process)

Every project declares exactly one **mode** before planning:

| Mode | Use when | Default kit bias |
| --- | --- | --- |
| `talking-head` | Mostly face/camera performance; little UI demo | Punchlines, side panels, stacks/scales, reframes; source-primary on jokes with motion |
| `tutorial` | Software demo + explanation (Grok for Word/Excel/PowerPoint) | Example cards, prompt cards, emphasis, UI callouts; light motion during demos |
| `hybrid` | Extended A-roll and extended demos both matter | Mix; source-primary only when needed, never long freezes |

Mode is **data on the project**, not a fork of the whole application.

## 4. Editorial beat types (the only planner vocabulary)

**Live authority:** `docs/vcg-graphics-process/beat-universe.md` (approved 2026-07-31); Stage 1 skill: `masterbeater` (see `docs/vcg-graphics-process/README.md`).

The planner does **not** emit arbitrary graphics. It emits a sequence of **beats** from the closed universe only.

| Beat type | Meaning |
| --- | --- |
| `hook` | Curiosity gap / open loop (cold open or mid-video “later”) |
| `setup` | Baseline assumption before a twist |
| `punchline` | Main land / payoff now |
| `aftershock` | Immediate secondary punches after the main punch (same bit) |
| `callback` | Later return to earlier material |
| `proof` | Metric, credential, hard number |
| `context` | Background / definition / stakes without open loop |
| `cta` | Subscribe, follow, link, destination |
| `example` | Numbered or named worked case |
| `prompt` | Prompt, command, short code |
| `list` | Multi-item sequence as visual rows |
| `structure` | Process, stack, pathway, tradeoff as a system |
| `ui` | Point at software on screen |

**Superseded (do not use):** `source-led-motion`, `section-label`, `example-card`, `prompt-card`, `list-reveal`, `ui-callout` as type IDs. Map form names to `example` / `prompt` / `list` / `ui`. Face-primary delivery is layout/Golden choice—not a beat type. Full spotting rules: `docs/vcg-graphics-process/beat-universe.md`.

A beat record must include:

- `beatType`
- `start` / `end` bound to **transcript word IDs** (app owns exact frames)
- `onScreenCopy` (editorial English, not a raw conjunction)
- `treatmentId` from the approved kit
- `motionKind` for source-led stretches (reframe / kinetic / edge-callout / list-row / etc.)
- `faceSafe` / `uiSafe` intent (must pass measured geometry later)

### 4.1 Forbidden planner outputs

- On-screen copy that is only a function word: *if, to, and, the, a, of, in, for, is, that, you, I…*
- Labels that do not restate a **viewer-useful idea** (joke, promise, step, contrast, command, number, name of a thing)
- Invented treatments outside the approved kit
- Covering face or critical UI “because cadence”
- **Long static “holds”** that leave the frame unchanged for more than the cadence max (see §6–7)

## 5. Copy rules

1. **Copy is editorial, not transcription.** Compress speech into a title, punchline, step name, or prompt gist.
2. **Jokes keep the funny words.** Prefer “soul-crushing corporate jobs” / “parking spots like Lumberg” over “probably” / “definitely”.
3. **Prompts are summarized** unless the beat type is exact command/UI label (then verbatim only with evidence).
4. **Example cards are numbered and specific** (“01 — …”), not “EXAMPLE”.
5. **One primary line per beat** unless the beat type is multi-row (`list`).
6. **Length:** aim for scannable (roughly ≤ 8 words for emphasis; example titles may be longer).

## 6. Source-led ≠ freeze (supersedes long holds)

**Creator decision (binding):** there is **no 45-second hold, ever.**  
There should **always be visual movement within about five seconds.**  
Many social-native creators aim nearer **~2 seconds** between changes because attention is trained by short-form feeds; VCG should feel alive, not like a static webinar.

### 6.1 What “hold” used to mean (rejected as loophole)

Agents treated “clean performance / screen share hold” as permission for **hundreds of seconds of unchanged source** and zero finishing. That is forbidden.

### 6.2 What source-led still means (kept)

When the joke, face, or UI **is** the story:

- do **not** bury it under a big opaque card;
- **do** still change something within cadence:  
  speaker reframe/container move, punch zoom, kinetic punchline timed to the joke, light edge callout, list row, UI highlight, chart state, treatment enter/exit.

So: **protect the payload, keep the frame moving.**

### 6.3 Screen share default (tutorial mode)

Screen share **defaults to light motion/overlays** (prompt gist, UI callout, step label, list row, emphasis), not emptiness.  
“UI must stay readable” constrains **how heavy** the graphic is, not whether motion exists.

## 7. Cadence (binding)

### 7.1 Hard maximum gap

> After each **meaningful visual change**, the next must begin within **about 5 seconds**.  
> **No exception** for long freezes. No multi-minute clean-source voids.

This is a **maximum stillness** rule, not a requirement to stamp a new full-screen card every 5s.

### 7.2 Target energy

- **Target:** meaningful motion nearer **~2 seconds** when the editorial material supports it (internal reveals, kinetic hits, callout updates, reframes).
- **Floor of quality:** never weaker than “something real changed within ~5s.”

### 7.3 What counts as a meaningful visual change

Qualifying (same spirit as the Visual Production workflow contract):

- new bullet/step/comparison/conclusion;
- chart/UI/demo state change;
- relevant callout or emphasis change;
- composition reframe / speaker container move;
- deliberate punch zoom used sparingly;
- treatment enter/exit;
- supporting visual cut-in.

**Does not count** (cannot be used to “satisfy” cadence):

- ambient drift / decorative loop;
- unchanged graphic sitting still;
- function-word or junk “captions” over unchanged footage;
- idle cursor wobble;
- repeated zoom on the same idea.

### 7.4 Multi-beat treatments

A single treatment may stay for a long editorial idea **only if** it keeps producing meaningful internal changes inside the 5s max (e.g. list rows landing).  
Do not slice one idea into fake separate graphics only to game the clock — **do** land real sub-reveals.

### 7.5 Density without spam

Successful VCG videos often sit around **a handful of designed scenes per minute**, each with **internal motion**.  
That is compatible with a 2–5s motion clock.  
It is **not** compatible with 200+ weak word stickers **or** 500s of static source.

### 7.6 Variety (binding — app-owned)

Do **not** loop the same completed graphic shell across the video.

Hard gates (implemented in `app/core/editorial_variety.py`, enforced on plan
validate and after face-safe remaps):

- no consecutive graphic beats with the same visual *family* unless they share
  an explicit `intentionalSeriesId` (callback / series);
- no single treatment above ~25% of graphic beats;
- top two treatments together may not exceed ~45%;
- face-safe remaps **rotate** among safe alternatives for the active OBS layout
  — they must not collapse everything to one kinetic stamp.

**Authority:** VCG validators. HyperFrames native skills (including
talking-head-recut “pick 2–3 motion patterns and reuse”) are **not** variety
authority and must not override this gate.

## 8. Approved treatment kit (v1 daily kit)

### 8.1 Core kit (must be buildable and preferred)

Drawn from modules that already appear in successful projects and/or the registered catalog:

**Source-led motion / safety** (never a long static freeze)

- No static hold engine. Clear chrome with source-led motion only: `source-punch-zoom`, light kinetic, or exit treatments. Long static holds are invalid under §6–7.
- `source-punch-zoom`

**Talking-head / emphasis**

- `punchline-reveal` (text or joke-image card)
- `speaker-side-panel`
- `kinetic-word-punctuation`
- `speaker-rise-callouts`
- `problem-card-triptych`

**Tutorial structure**

- `numbered-example-card`
- `numbered-step-intro`
- `windows-prompt-typing`
- `ui-callout`

**Structure / proof / end / soft CTA**

- `dependency-stack`
- `progress-scale`
- `tradeoff-meter`
- `brand-cta-lockup` (Skool hard CTA)
- `robot-cheer` / `robot-defiant` / `robot-roast` / `robot-rocket-sign` (mascot / soft CTA)

Removed from the kit (do not plan): `source-footage-hold`, `list-reveal-pinned-thesis`, `career-pathway`, `milestone-path`, and other retired engines.

### 8.2 Mode defaults

- **talking-head default palette:** punchline, side-panel, kinetic, punch-zoom, dependency-stack, progress-scale (source-led motion on jokes, not freezes)  
- **tutorial default palette:** numbered-example-card, windows-prompt-typing, punchline-reveal / kinetic-word, ui-callout, CTA (light overlays during demos; motion every ≤5s)  

### 8.3 Expansion rule

New treatments enter the daily kit only after:

1. one real render in a project, and  
2. creator marks them reusable.

No “full HyperFrames catalog assessment” on every sequence.

## 9. Face and UI safety

1. Speaker and protected UI regions come from **measured layout / OBS catalog / evidence**, not agent-declared rectangles.
2. Opaque overlays must not intersect the protected speaker region.
3. Tutorial overlays prefer **edge lanes** and document/UI-safe zones (as 7/22 purposes repeatedly required).
4. If a treatment cannot be placed safely, switch to **source-led motion** (reframe/kinetic/edge) or another kit treatment — never “cover the face anyway,” and never a long static freeze.

## 10. Repeatable pipeline (daily path)

One path. Visual Production remains the creator review surface (player + timeline). Backend may evolve, but the **editorial contract does not fork**.

```text
Locked cut + final transcript
        │
        v
[1] Mode select (talking-head | tutorial | hybrid)
        │
        v
[2] Editorial plan (beat list only; kit-constrained; human-skimmable)
        │
        v
[3] App validates: copy rules, kit membership, density band, word binding
        │
        v
[4] Deterministic build into visual plan / composition (real treatments)
        │
        v
[5] Review in Visual Production player + timeline
        │
        v
[6] Notes → rebuild only dirty beats/sections → re-render
        │
        v
[7] Export final with locked audio
```

### 10.1 Planner authority (human or LLM)

May decide:

- beat type,
- on-screen copy,
- which kit treatment,
- where holds go,
- example numbering / prompt gist.

Must not decide:

- raw frame math (app uses word IDs),
- freehand layouts that ignore safety,
- treatments outside the kit,
- filler beats to hit a quota.

### 10.2 Application authority

- transcript identity and frames,
- validation gates,
- geometry safety,
- build/render,
- section invalidation.

## 11. Validation gates (ship blockers)

A plan is invalid if:

1. any beat copy is function-word-only or empty when a graphic is required;  
2. any graphic beat lacks a kit `treatmentId`;  
3. weak copy is used only to fake cadence (anti-spam);  
4. any span of the timeline exceeds **~5s without a meaningful visual change** (including during demos/jokes — source-led motion still required);  
5. word bindings missing or outside locked transcript;  
6. safety checks fail after build (opaque chrome on face/critical UI).

**Both** gates always apply: **motion clock** (≤5s, target ~2s) **and** **editorial quality** (no junk labels). Neither may be satisfied by gaming the other.

## 12. Surfaces and ownership

| Surface | Role |
| --- | --- |
| Transcript Edit | Produce locked cut + transcript |
| **Visual Production** | Daily review/edit/render surface (player, timeline, library) |
| Creator Production | Experimental/parallel; **not** the daily editorial authority unless explicitly re-approved later |

Daily work must not require a second mystery workspace to see the real plan.

## 13. Implementation sequence (after this contract is accepted)

1. **Encode the beat schema + kit IDs** as the only plan format for new work.  
   - **Phase 1 landed:** `visual-production/schemas/editorial-beats.v1.schema.json`,  
     `app/core/editorial_beats.py`, `scripts/editorial_beats.py` (`validate` / `kit` / `example`).  
     Gates: schema, daily kit membership, weak-copy ban, ≤5s motion gaps, no long  
     static source holds, optional transcript wordSpan binding.
2. **Planner** (app-assisted; optional local LLM later) that only emits that schema.  
3. **Validators** for geometry/safety at build time (copy/kit/cadence are Phase 1).  
4. **Build** beats → registered modules/recipes into `visual-plan` cues.  
   - **Phase 2 (corrected):** map kit `treatmentId` → **Visual Production modules**  
     (`app/core/editorial_visual_plan.py` + `scripts/render_editorial_build_sample.py`),  
     the same markup/CSS brand language as successful 7/14–7/22 videos  
     (magenta kinetic stamps, left speaker-side panels, numbered-example cards,  
     windows-prompt typing, lower-thirds). **Not** white-card placeholders.  
     Sample render path: editorial beats → `visual-plan` cues →  
     `build_hyperframes_composition` → HyperFrames + locked audio.  
   - Parallel package draw stacks removed; engines only.  

5. **Review loop** already largely exists in Visual Production; wire notes to dirty beats.  
6. **Validation video:** next *new* project (not a historical salvage requirement).

## 14. Explicit supersessions

- “Full native HyperFrames catalog assessment every sequence” is **not** daily process.  
- “Meaningful change every 5s via random words” is **rejected** as the creative model.  
- “Long intentional hold / clean-performance freeze” as a loophole for empty screen-share chapters is **rejected**. Creator rule: **no multi-tens-of-seconds static holds; motion within ~5s always; target nearer ~2s when content allows.**  
- Throwaway white-card sample HTML is **not** the design system.  
- Cloning one finished project’s cue list onto another video is **not** the product (though past projects remain the **style evidence** for this contract).

## 15. Acceptance criteria for this contract

This contract is successful when:

1. A creator can read a plan in minutes and recognize jokes, examples, holds, and prompts.  
2. Built graphics use VCG treatments and fonts/layout language from the real kit.  
3. Face/UI stays protected by default.  
4. The same pipeline runs on the next video without redesigning the process.  
5. Revision is note → local rebuild, not multi-day replan.

---

When this document is accepted, implementation starts at §13.1 — schema + kit freeze — not more experimental sample shells.
