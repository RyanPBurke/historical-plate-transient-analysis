# Stage A release review workflow — RC9 final-cycle handoff

The active release review unit is GitHub PR #1 on branch `review/v095a-stagea-release`. RC9 is correction/review cycle **3 of 3 after RC5**. RC7 was staged but never submitted for independent review and therefore did not consume a cycle.

Allowed coordinator activity remains limited to repository/release-artifact reads, synthetic/offline tests, preservation of audit evidence, the narrow mechanical fixes required by an existing independent NAY, immutable release packet publication, state updates, PR replies/requests and append-only mailbox status.

Not authorized: TAP/catalogue requests (including diagnostics), candidate/source inspection, pixels/scans, changes to scientific SQL/bins/population/thresholds/selected-key binding/batch sizes/source permissions, modification of old freezes or failed checkpoints, merges, deployment, a new execution freeze, or reclassification/reset of RC4's unresolved submission.

A YAY means only `APPROVED_PENDING_WINDOWS`: Ryan still runs the Windows self-test/full frozen-parent preflight and separately controls any execution-freeze/execution authorization. RC4's unresolved live submission remains preserved and must pass the existing explicit acknowledgement gate before any future live POST.

A NAY on RC9 ends the bounded correction loop. Stop and notify Ryan; do not create RC10 under this workflow.
