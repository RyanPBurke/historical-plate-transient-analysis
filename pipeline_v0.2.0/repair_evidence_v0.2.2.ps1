$ErrorActionPreference = "Stop"
$python = ".\.venv\Scripts\python.exe"
$exe = ".\.venv\Scripts\transient-pipeline.exe"

Write-Host "Backing up and migrating legacy mutable derived-artifact evidence records..."
& $python .\tools\migrate_evidence_v022.py
if ($LASTEXITCODE -ne 0) { throw "evidence index migration failed" }

Write-Host ""
Write-Host "Verifying migrated evidence store..."
& $exe verify-evidence --root .\evidence
if ($LASTEXITCODE -ne 0) { throw "migrated evidence verification failed" }

Write-Host ""
Write-Host "EVIDENCE MIGRATION v0.2.2 PASSED."
Write-Host "No scientific job/checkpoint/result was changed by this migration."
