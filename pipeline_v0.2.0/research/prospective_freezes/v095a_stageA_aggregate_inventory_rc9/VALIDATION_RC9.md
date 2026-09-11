# RC9 offline validation

Scope: final bounded mechanical correction for independent RC8 NAY B1/B2/B3. No TAP/catalogue/source/pixel access.

- `python -m unittest -v test_v095a_rc9.py`: **74/74 PASS**.
- Package `--self-test`: **PASS**, rerunning the same 74 regressions; `catalogue/network calls: 0`.
- Exact B1 negatives PASS: deleted attempt history, non-`VALIDATED` final attempt, and publication context mismatch all HOLD.
- Exact B2 path regression PASS: frozen parent remains `research/proof_archives/v094y_rc4_proof_archive.zip` with unchanged digest.
- B3 jobs-layer Ctrl+C regression PASS: buffered bounded body is hash-retained in uncertain submission evidence and resume makes zero replacement submissions.
- B3 spawned-worker POSIX SIGINT regression PASS after durable headers plus at least one body chunk: bytes survive temporary IPC cleanup.
- SQL SHA-256 unchanged: `1e318f66a80453208e77c41ccb89b6340c29b639b53741b634a459d649308b21`.
- bins SHA-256 unchanged: `c4fd3724579f37b847c1a4549fb6c45066531efc3607b1e37eca0a5567366313`.
- PGlite fixture was not rerun because the coordinator environment has no local Node dependency directory; SQL bytes are unchanged.
- Windows self-test/full frozen-parent preflight remain later gates after independent YAY.
