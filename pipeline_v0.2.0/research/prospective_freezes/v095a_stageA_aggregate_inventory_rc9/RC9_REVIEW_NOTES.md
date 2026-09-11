# v095a Stage A RC9 final correction notes

RC9 is correction/review cycle **3 of 3 after RC5** and responds only to independent RC8 NAY comment `5634646740`. RC7 was staged but never submitted for review, so it did not consume a correction/review cycle. All prior candidates/freezes remain immutable.

## Blocking findings addressed

### B1 — publication lifecycle invariants
`copy_validated_jobs()` now calls the same strict checkpoint validator used by resume, with the exact expected family, batch number, materialized query bytes, field schema, validator, expected keys and execution context collected during this invocation. Publication therefore rejects empty/malformed attempt histories, requires 1–3 consecutive attempts, requires a final `VALIDATED` attempt for `COMPLETED_VALIDATED`, and rechecks query/context/result hashes plus submission receipt/disposition/timing/job-URL evidence before copying anything.

Added negative regressions delete the entire attempt list, change the final attempt to `WAITING`, and mutate context. All must `PUBLICATION_HOLD`.

### B2 — frozen parent archive path
The parent proof archive path is restored to the actual frozen RC4 artifact:
`research/proof_archives/v094y_rc4_proof_archive.zip`.
The frozen proof digest remains unchanged: `1d6cdfe596711dad561ad67892536d2d4a6b779c6b57416afe2e3b95be65b84e`.
A path-selection regression prevents candidate-version renaming of this parent artifact.

### B3 — buffered body evidence on Ctrl+C
The runtime now accepts a predeclared durable partial-body path for submission POSTs. If `KeyboardInterrupt`/controller cancellation occurs while the spawned worker is streaming the bounded body, the controller first stops the worker, reads the already-fsynced IPC body, enforces the configured body bound, and atomically copies those bytes outside the temporary directory before cleanup.

The jobs layer then combines those retained bytes with the durable header receipt into the normal hash-bound partial submission envelope (`TRANSPORT_RESPONSE_INCOMPLETE` / `CONTROLLER_INTERRUPT`). The attempt remains `SUBMITTING` under `FAILED_HOLD`; resume makes zero replacement submissions.

Regressions cover both the jobs-layer retained/hash-bound body and an actual POSIX spawned-worker SIGINT boundary after headers plus at least one body chunk.

## Frozen science unchanged
- SQL SHA-256: `1e318f66a80453208e77c41ccb89b6340c29b639b53741b634a459d649308b21`
- bins SHA-256: `c4fd3724579f37b847c1a4549fb6c45066531efc3607b1e37eca0a5567366313`
- parent population, selected-key binding, batch sizes, source restrictions and RC4 incident semantics are unchanged.
- expected population remains 2,655 pairs / 2,683 fragments / 2,440 physical plates; 1,223 pre-Sputnik pairs / 1,237 fragments.

No TAP/catalogue/source/pixel call was made while preparing RC9. An independent YAY means only `APPROVED_PENDING_WINDOWS`. If RC9 is NAYed, this workflow stops; no RC10 is authorized.
