$ErrorActionPreference = "Stop"
$python = ".\.venv\Scripts\python.exe"
$db = ".\state\poss1_identity_prospective.sqlite"

Write-Host "Auditing and requeueing only the six reviewed v0.2.5 Plate Finder non-resolution completions..."
& $python .\tools\requeue_v025_platefinder_nonresolution_jobs.py --db $db --audit-dir .\research
if ($LASTEXITCODE -ne 0) {
    throw "v0.2.6 checkpoint repair refused or failed; no preflight rerun should start."
}

Write-Host ""
Write-Host "Checkpoint after repair:"
& ".\.venv\Scripts\transient-pipeline.exe" --db $db status --stage "poss1-identity:prospective_production"
if ($LASTEXITCODE -ne 0) { throw "could not read repaired checkpoint" }

Write-Host ""
Write-Host "v0.2.6 checkpoint repair PASSED."
Write-Host "Next: run .\run_poss1_identity_preflight.ps1"
Write-Host "No transient detection was run."
