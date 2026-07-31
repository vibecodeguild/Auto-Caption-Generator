# Source capture-layout classification task

Using only the locked cut, the semantic sequence ranges, and the frozen
creator-approved capture-layout catalog, classify the source footage into the
eight exact OBS layouts listed in that catalog.

Inspect actual source frames. Do not infer a layout from transcript meaning,
sequence duration, semantic topology names, or prior workflow output. Do not
estimate, redraw, or alter speaker rectangles. Geometry is owned by the frozen
catalog and will be applied deterministically by the Production host after this
task.

For every semantic sequence:

- cover its complete half-open frame range with contiguous, non-overlapping
  `layoutSpans`;
- use the sequence boundaries when the layout remains stable;
- when the OBS layout changes inside the sequence, locate the actual visual
  switch frame from source pixels and split there;
- record one or more actual inspected `evidenceFrames` inside every span;
- choose exactly one catalog `layoutId` when the source frame matches;
- if a span is genuinely ambiguous or matches none of the eight layouts, set
  `layoutId` to null, list the plausible catalog IDs, and explain the unresolved
  reason. Never pick a convenient layout to make the gate pass.

The same documented layout may appear in many sequences. That is expected.
Classification is factual source inspection, not a creative decision and not a
creator approval request.

Do not invoke another workflow, load ambient skills, write geometry, create
chapters, change timing, or write outside the schema-bound task output.
