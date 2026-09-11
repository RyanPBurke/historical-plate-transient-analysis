# RC9 final-cycle correction evidence

Controlling independent review: ASTRA RESPONSE v095a-rc8-release-review comment `5634646740`, reviewed head `ba52c2c2ae299ef9fda76309e2f96ab875fc1a9a`.

RC9 is correction/review cycle **3 of 3 after RC5**. If RC9 is independently NAYed, stop and notify Ryan; no RC10/fourth correction candidate is authorized by the current workflow.

Blocking findings addressed only:
- **B1 publication lifecycle:** publication now invokes the same complete checkpoint validator as resume using the exact expected family/batch/materialized query/fields/validator/expected keys/execution context. Empty attempt history, non-`VALIDATED` final state, context/query/result/receipt inconsistencies all HOLD before copying.
- **B2 frozen parent path:** restored `research/proof_archives/v094y_rc4_proof_archive.zip`; frozen digest unchanged.
- **B3 interrupted body evidence:** controller interruption stops the spawned worker, copies already-fsynced bounded submission-body bytes out of temporary IPC before cleanup, and the jobs layer hash-binds them with the durable header receipt into uncertain submission evidence. State remains HOLD; resume performs zero replacement POSTs.

Offline validation:
- 74/74 Python regressions PASS.
- Package self-test PASS, rerunning 74/74; catalogue/network calls = 0.
- Actual POSIX spawned-worker SIGINT regression after headers plus one body chunk PASS.
- Exact B1 negative mutations and B2 path-selection regression PASS.
- PGlite SQL fixture not rerun because local Node dependencies are absent; SQL bytes are unchanged.

Frozen science unchanged:
- SQL SHA-256: `1e318f66a80453208e77c41ccb89b6340c29b639b53741b634a459d649308b21`
- bins SHA-256: `c4fd3724579f37b847c1a4549fb6c45066531efc3607b1e37eca0a5567366313`
- population: 2,655 pairs / 2,683 fragments / 2,440 plates; 1,223 pre-Sputnik pairs / 1,237 fragments.
- selected-key binding, batch sizes, source restrictions and RC4 incident semantics unchanged.

RC4's unresolved live submission remains preserved and gated. It was not marked rejected/completed, imported/reset, or used as permission for a live retry. No TAP/catalogue/source/pixel request was made.
