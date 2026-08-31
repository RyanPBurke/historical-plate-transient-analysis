$ErrorActionPreference = "Stop"
$python = ".\.venv\Scripts\python.exe"
$exe = ".\.venv\Scripts\transient-pipeline.exe"
$db = ".\state\poss1_identity_prospective.sqlite"
$stage = "poss1-identity:prospective_production"

Write-Host "Validating the reviewed XO197 archive-unavailability evidence..."
& $python .\tools\validate_xo197_archive_exception.py
if ($LASTEXITCODE -ne 0) { throw "XO197 archive-exception evidence validation failed." }

Write-Host ""
Write-Host "Auditing and requeueing the 26 reviewed v0.2.3 terminal states..."
& $python .\tools\requeue_v023_terminal_identity_jobs.py --db $db --stage $stage --audit-dir .\research --exception-validation .\research\POSS1_XO197_ARCHIVE_EXCEPTION_VALIDATION_v0.2.5.json
if ($LASTEXITCODE -ne 0) {
    throw "v0.2.5 checkpoint repair refused or failed; no preflight rerun should start."
}

Write-Host ""
Write-Host "Checkpoint after repair:"
& $exe --db $db status --stage $stage
if ($LASTEXITCODE -ne 0) { throw "could not read repaired checkpoint" }

Write-Host ""
Write-Host "v0.2.5 checkpoint repair PASSED."
Write-Host "Next: run .\run_poss1_identity_preflight.ps1"
Write-Host "XO197 remains in the denominator but will be detector-ineligible if digital pixels remain unavailable."
Write-Host "No transient detection was run."
