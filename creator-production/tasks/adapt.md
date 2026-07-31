# Project-scoped capability adaptation task

Adapt the requested frozen native HyperFrames source recipe into one exact,
reusable, parameterized project implementation for the named semantic sequence.
Return one `capability-adaptation` JSON document.

The bounded capability resources contain the source recipe's complete frozen
instruction dependency set: the governing animation contract, runtime adapters,
referenced atomic rules, and any matching runnable source example. Read and
follow every supplied dependency. Do not infer motion behavior from the
blueprint alone. Copy the complete capability-resource ID set into
`sourceResourceIds` and include every corresponding hash in `sourceHashes`;
admission rejects an incomplete or altered set.

The `files` array must contain `implementation.mjs`. That module must export a
pure `build(context)` function which returns a fully specified composition
graph fragment. It may use only declared deterministic browser/runtime
dependencies. It may not read ambient files, environment variables, network
resources, clocks, random values, or other skills. It must bind visual design
through the supplied semantic channel tokens and timing only through exact
`wordId`, measured `sourceEventAnchorId`, or an already resolved absolute frame.
Visible copy and semantic reveal timing are required context inputs from the
episode's editorial directive. The implementation must consume them as
parameters and must never supply generic recipe-default copy or independently
invent a reveal schedule.

Preserve the strongest capabilities of the source recipe. Do not replace it
with a generic card, text box, punch zoom, or other easier approximation.
Record actual capacity and limitations. Do not claim technical admission; the
Production host performs that check after generation.

Include one realistic validation fixture. `build(context)` must return an
object with `elements` and `events` arrays using only Production-supported
operations: set, reveal, enter, show, type-reveal, move, scale, rotate,
emphasize, hide, and exit. The host executes the fixture twice in a restricted
JavaScript VM, validates normalized geometry and references, and requires
byte-identical canonical output before project admission.

The returned fragment is the complete graph contribution for the binding,
including the locked `speaker-source` element when the treatment shares the
frame with the creator. During episode materialization, Production executes
this exact implementation with host-resolved tokens, timing, canvas, evidence,
and approved parameters; any graph that differs from that output is rejected.
