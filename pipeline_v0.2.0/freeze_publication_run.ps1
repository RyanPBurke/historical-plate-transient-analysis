$ErrorActionPreference = "Stop"

$exe = ".\.venv\Scripts\transient-pipeline.exe"
if (-not (Test-Path $exe)) {
    throw "Publication venv is not installed. Run .\bootstrap_publication.ps1 first."
}

$out = ".\research_snapshots\sub5_production_freeze_2026-08-20"

if (Test-Path $out) {
    throw "$out already exists. A publication snapshot is immutable; do not overwrite it."
}

& $exe publication-snapshot `
    --protocol .\protocol\PROTOCOL_v1.0_PRE_REMAINING_SUB5_2026-08-20.md `
    --queue .\research\production_sub5_queue_2026-08-20.csv `
    --extra .\research\canonical_sub5_pairs_74.csv `
    --extra .\research\PRE_FREEZE_ANALYSIS_INVENTORY_2026-08-20.csv `
    --extra .\research\CURRENT_STATE_PRE_FREEZE_2026-08-18.json `
    --extra .\research\LEGACY_EVIDENCE_GAPS_AT_FREEZE_2026-08-20.md `
    --extra .\research\PAIR13623_BI05607_REVALIDATED_CLOSURE_2026-08-20.md `
    --extra .\analysis\superseded_results.csv `
    --extra .\protocol\EVIDENCE_POLICY.md `
    --extra .\protocol\DATA_DICTIONARY.md `
    --out $out `
    --activate

if ($LASTEXITCODE -ne 0) {
    throw "Publication snapshot failed."
}

Write-Host ""
Write-Host "Indexing preserved legacy StarGlass FITS without re-downloading..."
& $exe index-starglass-cache --root .\cache\verified_starglass
if ($LASTEXITCODE -ne 0) {
    throw "Legacy StarGlass cache indexing failed."
}

Write-Host ""
Write-Host "Verifying detector regressions using the already cached verified FITS when available..."

& $exe `
    --db .\state\publication_regression.sqlite `
    starglass `
    --manifest .\examples\starglass_manifest.csv `
    --plate bi05607 `
    --cache-dir .\cache\verified_starglass `
    --export .\results\publication_regression.csv

if ($LASTEXITCODE -ne 0) {
    throw "Regression detector run failed."
}

& $exe verify-regressions --results .\results\publication_regression.csv
if ($LASTEXITCODE -ne 0) {
    throw "Verified detector regression failed. Do not start production."
}

Write-Host ""
Write-Host "Building current ledgers..."
& $exe build-ledger `
    --state-dir .\state `
    --jobs-out .\analysis\master_job_ledger_preproduction.csv `
    --runs-out .\analysis\stage_run_ledger_preproduction.csv

Write-Host ""
Write-Host "PUBLICATION FREEZE PASSED."
Write-Host "Active snapshot: .\research\ACTIVE_SNAPSHOT.json"
Write-Host "Do not modify protocol/queue/config for the production run without versioning a new protocol."
