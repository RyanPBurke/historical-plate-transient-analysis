v095a Stage A Aggregate Inventory Implementation RC4
==================================================

STATUS: CORRECTED RELEASE CANDIDATE; NOT EXECUTION-FROZEN.
RC4 supersedes the supplied RC3 implementation. See RC4_REVIEW_NOTES.md.
No APPLAUSE catalogue execution was performed while preparing this revision.

Scientific scope
----------------
Q0/Q1/Q2 SQL and histogram JSON are byte-for-byte identical to RC3.
The Q2 FILTER correction already present in RC3 is retained. Selected solution
binding, parent hashes, population, quality bins and permission boundary remain
fixed. Only metadata bindings and aggregate counts may be returned. Stage A
never enables individual-source extraction, source pairing, pixels or scans.

Changes
-------
- Strict CSV parsing and exact integers; impossible Q2/cross-query counts HOLD.
- Durable job identities, original deadlines and retry budgets survive restart.
- Each HTTP operation has an enforced 135-second wall limit in a spawned child.
- Unknown POST acceptance and unconfirmed aborts cannot cause blind resubmission.
- Failed result bytes are retained and hashed before any validation.
- A project OS lock protects checkpoints and unique publication staging.
- Checkpoints bind release, parent, query and expected-key provenance.
- Publication includes an explicit validated-batch allowlist and recursive hashes.
- Offline Python failure tests and actual local PostgreSQL SQL fixtures included.

Local checks before independent release approval
-----------------------------------------------
Extract into a new RC4 directory; preserve the RC3 handoff and any earlier work.
Use the project's existing Python environment and its parent data/proof archive.
Do not run older Stage A controllers alongside RC4.

PowerShell, from the extracted package directory:

  $ProjectRoot = "C:\Dev\Transients\historical_transient_laptop_pipeline_v0.2.0_publication\transient_laptop_pipeline_v0.2.0"
  $RepoRoot = "C:\Dev\Transients\historical-plate-transient-analysis_repo"

  .\run_v095a_stageA_rc4_selftest.ps1 -ProjectRoot $ProjectRoot
  .\run_v095a_stageA_rc4_preflight.ps1 -ProjectRoot $ProjectRoot -RepoRoot $RepoRoot

Both commands make zero catalogue/network calls. The Python self-test runs
synthetic parser, lifecycle, process-lock and wall-deadline regressions.
Preflight additionally requires the real local frozen parents. Expected:
  pairs/fragments/plates = 2655 / 2683 / 2440
  pair_sides/selected_solutions = 5310 / 2440
  pre-Sputnik = 1223 pairs / 1237 fragments

Separate SQL suite (Node.js and npm required only for this development check):

  npm ci --ignore-scripts --no-audit --no-fund
  npm run test:sql

Dependency installation uses the npm registry. The SQL test itself is offline:
it executes the exact templates against a disposable PGlite PostgreSQL database
with synthetic data. It is not a test of the remote TAP service. Do not include
node_modules or __pycache__ when copying the reviewed release into Git.

Release/execution boundary
--------------------------
After independent RC4 release review and successful Windows preflight, the
reviewed files belong under:
  pipeline_v0.2.0/research/prospective_freezes/v095a_stageA_aggregate_inventory_rc4

Preserve exact bytes and release_manifest.sha256. The supplied .gitattributes
prevents line-ending conversion. Freeze-evidence and production scripts remain
available for the separately authorized execution step. No script here commits
or pushes automatically. Production verifies the exact frozen Git blobs,
origin/main, parent ancestry and proof hashes before submitting a catalogue job.

The new work directory is work/v095a_stageA_aggregate_inventory_rc4.
RC3 checkpoints are not silently imported. Resume RC4 with the same command,
release and freeze evidence. Do not delete or rename a held batch to get a retry:
unknown receipts, corrupt evidence and exhausted budgets require review.
Completed validated batches are reused without further catalogue requests.

Read VALIDATION_RC4.md for the checks actually completed on this handoff.
Read REVIEW_WORKFLOW.md for the proposed PR-based review loop; it is not active.
