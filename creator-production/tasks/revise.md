# Localized revision task

Revise only the sequences, elements, events, assets, or boundaries identified
by the active review notes and their matching build context. Preserve all
unnoted manifest decisions and absolute sequence/chapter ranges.

If a note authorizes a transition change, preserve explicit single-sequence
ownership and keep the transition binding's exact `eventIds` synchronized with
the composition graph.

Use the exact locked transcript and source-event timing. Preserve selected
semantic forms and capability families unless the creator explicitly requested
a substitution. Do not accept or archive review notes; only the creator can do
that.

Return the complete next `episode-manifest` revision. The Production host
computes localized invalidation from the old and new build locks; do not
self-report or guess it. Do not invoke another workflow or rerender unaffected
chapters.
