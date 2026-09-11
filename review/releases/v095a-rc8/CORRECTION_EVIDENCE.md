# RC8 correction evidence

Processed controlling independent review comment: `5630734054` (RC6 NAY).

RC8 is correction/review cycle 2 of 3 after RC5. RC7 was staged but never submitted for independent review, so it does not consume a correction/review cycle. The partially published RC7 archive chunks are preserved immutable and were never submitted for independent review; manual coordinator recovery found that RC7 still left RC6 R1b/R2 incomplete, so RC8 addresses only those remaining receipt-time and lifecycle/disposition mechanics.

Offline validation:
- `python -m unittest -v test_v095a_rc8.py`: 68/68 PASS, twice.
- `python run_v095a_stageA_inventory_rc8.py --self-test`: PASS; catalogue/network calls=0.
- Actual HTTP worker captures and hash-binds receipt wall/monotonic time before delayed body completion.
- Synthetic 120-second POST body delay does not move the fixed 3900-second terminal deadline from header/job-Location receipt time.
- Completed receipt with missing disposition: CHECKPOINT_HOLD; zero replacement submissions.
- Re-hashing mutated receipt times cannot extend the recorded job deadline.
- Publication revalidates mandatory disposition, receipt timing, job URL and receipt semantics.
- RC7's durable interruption sidecar, late-response status/header retention and RC4 unknown-submission acknowledgement gate are retained.
- SQL SHA-256 unchanged: `1e318f66a80453208e77c41ccb89b6340c29b639b53741b634a459d649308b21`.
- bins SHA-256 unchanged: `c4fd3724579f37b847c1a4549fb6c45066531efc3607b1e37eca0a5567366313`.

Unchanged PGlite SQL fixtures were not re-run because this coordinator environment has no local Node dependency directory and dependency installation is outside the offline workflow. Windows self-test/full parent-data preflight remains Ryan's separate later gate.

RC4's unknown live submission remains unresolved and preserved. It was not marked rejected/completed, its budget was not reset, it was not imported as a valid checkpoint, and no TAP/catalogue/source/pixel call was made.
