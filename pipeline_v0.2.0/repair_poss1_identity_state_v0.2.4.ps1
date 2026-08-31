$ErrorActionPreference = "Stop"
$python = ".\.venv\Scripts\python.exe"
$exe = ".\.venv\Scripts\transient-pipeline.exe"
$db = ".\state\poss1_identity_prospective.sqlite"
$stage = "poss1-identity:prospective_production"

Write-Host "Auditing and requeueing only known v0.2.3 implementation-gate terminals..."
& $python .\tools\requeue_v023_terminal_identity_jobs.py --db $db --stage $stage --audit-dir .\research
if ($LASTEXITCODE -ne 0) {
    throw "v0.2.4 checkpoint repair refused or failed; no preflight rerun should start."
}

Write-Host ""
Write-Host "Checkpoint after repair:"
& $exe --db $db status --stage $stage
if ($LASTEXITCODE -ne 0) { throw "could not read repaired checkpoint" }

Write-Host ""
Write-Host "v0.2.4 checkpoint repair PASSED."
Write-Host "Next: run .\run_poss1_identity_preflight.ps1"
Write-Host "No transient detection was run."
