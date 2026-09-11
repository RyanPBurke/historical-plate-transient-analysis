# ASTRA RESPONSE v095a-rc5-release-review

**Verdict: NAY for the RC5 execution freeze and Stage A catalogue execution.**
Offline repair and review may proceed. No individual-source work is authorized.

Reviewed archive SHA-256: `11993c8c2cf943564300155a07704d85e85845e4f05eb8f2cab4e756cb5aa275`.
Contract: `0ed31dcd20e5b75c46fb6ce5405ee0fbcd712b3201175a5b9316f67d0aa344d2`.
Manifest: `c6696e07c329e99d268b74f86871593c0e1663dff5f3a31fa62b3b91cf677e59`.
Compared with all 21 exact Git blobs of RC4 at `f4d8cf83e96aa10fe01470270ca24ea093f5b262`. The PR review comment binds this report and the supplied package to its full review-branch commit.

## Evidence

The supplied package self-test passed all 51 Python regressions. The SQL fixtures passed in local PGlite 0.5.8 / PostgreSQL 18.3, including Q0 binding, Q1 selected-key isolation and null/nonfinite/bin boundaries, and Q2 empty-plate/multiplicity regressions. This is an offline SQL-engine check, not a claim about the live service.

Six additional offline probes reproduced the two blockers below. They replace the requests module with synthetic responses and exercise the actual RC5 worker/controller path; they make no network or catalogue calls. The probe code and observed results accompany this report. Deadline-test byte counts can vary with scheduling.

### R1 — Retain received headers even when reading the body fails (blocking)

Locations: `package/v095a_runtime_rc5.py`, functions `_http_worker` and `isolated_request`; `package/v095a_jobs_rc5.py`, submission and TransportFailure handling.

RC5 asks the POST transport to read up to 64 KiB before returning its response. The worker keeps HTTP status and Location in memory until the body loop ends. On a stream error or oversize body, its IPC metadata contains the headers, but `isolated_request` throws them away when it raises `TransportFailure`. On a wall timeout the worker is killed before that metadata is written. The jobs layer then persists a receipt with null status and empty headers.

Reproductions:
- 303 plus a valid synthetic job Location, followed by a stream error: receipt loses status and Location.
- 401 followed by an oversize body: receipt loses the already known rejection status.
- 303 plus valid Location followed by a slow body and parent deadline: receipt loses status and Location.

All three correctly HOLD after one simulated POST; none resubmits. The defect is lost evidence and job identity, directly within RC5's stated repair scope. It can leave a job whose URL was actually received impossible to reconcile from the checkpoint.

Before the next freeze, persist a sanitized status/header receipt as soon as headers arrive, separately from cookie-bearing IPC and body collection. Carry that receipt and bounded partial bytes through transport failures, timeout and interruption. Preserve any received job identity for reconciliation without automatically authorizing another POST. Record the receipt time so body collection does not extend the frozen 3900-second job deadline. Add failure tests at these transport/durability boundaries, including Ctrl+C.

### R2 — Require and bind the complete receipt on resume/publication (blocking)

Location: `package/v095a_jobs_rc5.py::validate_checkpoint`; publication in `package/run_v095a_stageA_inventory_rc5.py::copy_validated_jobs`.

The validator checks the receipt only if `submission_response` exists. Its hash checks cover body bytes, not the HTTP status or header values, and it does not reconcile Location/status with `job_url` and `submission_disposition`.

Starting with a valid, fully completed synthetic checkpoint, each of these mutations still returns `resume PASS` without new requests:
- change receipt status from 303 to 401;
- change receipt Location to a different origin while leaving the recorded job URL unchanged;
- remove the entire receipt record and its submission artifact.

This is not a live redirect vulnerability: initial job URL validation remains strict. It is a checkpoint/evidence integrity defect. The publication routine can copy a nominally validated checkpoint without mandatory receipt evidence, so publication inherits the same gap.

Before the next freeze, define mandatory receipt fields/artifacts for each attempt state; persist and hash a canonical sanitized receipt envelope containing HTTP metadata, body digest, query/attempt identity and receipt time; verify its digest and semantic relationship to the recorded job and disposition. Missing/corrupt/inconsistent required evidence must HOLD. Reuse these checks before publication. Do not claim a checksum authenticates a hostile rewrite of both data and hashes; the requirement here is reliable integrity and consistency checking. Add deletion, status/Location mutation and publication regression tests.

## Requested checks

| Check | Assessment |
|---|---|
| Receipt saved before interpretation | Pass when the transport returns normally; **fails on interrupted body collection (R1)**. |
| No body/credential printing | Normal controller paths do not print the raw receipt or authorization token; only selected response headers are recorded. Raw response artifacts remain untrusted service content. |
| Rejection vs uncertain acceptance | The implemented classes conservatively HOLD; classification is lost on transport failures after received headers (R1). |
| No automatic resubmission after either HOLD | Pass within the same RC5 work directory, including the supplied regression coverage. |
| Same-origin/exact-path job receipt | Pass on initial acceptance. Stored receipt consistency is incomplete (R2). |
| Cryptographic binding of submission evidence | Body binding exists; full receipt binding and mandatory-presence validation **fail (R2)**. |
| Publish only validated batch evidence | Gating/copy hashes exist, but receipt completeness depends on fixing R2. |
| Preserve RC4 failed state | RC5 uses a separate directory and does not import/reset RC4. This does not resolve the old unknown submission. |
| Science/permission identity | SQL and bins match RC4 exactly; runner changes are version/contract binding. Population, selected keys, batch sizes and source restrictions are preserved. |
| Windows validation before freeze | Still required. This review did not perform Ryan's Windows parent-data preflight. |

SQL SHA-256 remains `1e318f66a80453208e77c41ccb89b6340c29b639b53741b634a459d649308b21`; bins SHA-256 remains `c4fd3724579f37b847c1a4549fb6c45066531efc3607b1e37eca0a5567366313`.

## Cross-release handoff

Preserve and hash the RC4 failed checkpoint before any replacement execution, and explicitly record its unresolved submission in the next release's handoff. A fresh RC5/RC6 directory is not evidence that RC4's POST created no server job and must not silently reset the operational attempt history. Reconciliation, or a specifically reviewed decision about that uncertainty, belongs before another live POST. This review cannot infer the old HTTP status or whether a job exists.

The next version should address R1 and R2 without changing scientific SQL/bins or importing unknown RC4 state as a valid checkpoint. Then obtain independent review of the new exact artifact, Windows self-test/full parent preflight, and a separately authorized execution freeze. Current authorization covers offline repair/review only.
