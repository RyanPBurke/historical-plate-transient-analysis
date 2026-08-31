$ErrorActionPreference = "Stop"
$exe = ".\.venv\Scripts\transient-pipeline.exe"
$python = ".\.venv\Scripts\python.exe"

Write-Host "Running v0.2.1 tests..."
& $python -m pytest -q
if ($LASTEXITCODE -ne 0) { throw "pytest failed" }

$out = ".\research_snapshots\sub5_production_freeze_v0.2.1_2026-08-20"

& $exe publication-snapshot `
  --protocol .\protocol\PROTOCOL_v1.0_PRE_REMAINING_SUB5_2026-08-20.md `
  --queue .\research\production_sub5_queue_2026-08-20.csv `
  --out $out `
  --extra .\research\canonical_sub5_pairs_74.csv `
  --extra .\research\PRE_FREEZE_ANALYSIS_INVENTORY_2026-08-20.csv `
  --extra .\research\CURRENT_STATE_PRE_FREEZE_2026-08-18.json `
  --extra .\research\LEGACY_EVIDENCE_GAPS_AT_FREEZE_2026-08-20.md `
  --extra .\research\PAIR13623_BI05607_REVALIDATED_CLOSURE_2026-08-20.md `
  --extra .\analysis\superseded_results.csv `
  --extra .\protocol\EVIDENCE_POLICY.md `
  --extra .\protocol\DATA_DICTIONARY.md `
  --extra .\research\poss1_plate_metadata.csv `
  --extra .\research\POSS1_TIMESTAMP_AND_IDENTITY_NOTE_2026-08-20.md `
  --activate
if ($LASTEXITCODE -ne 0) { throw "publication snapshot failed" }

Write-Host ""
Write-Host "Indexing existing StarGlass FITS..."
& $exe index-starglass-cache --root .\cache\verified_starglass
if ($LASTEXITCODE -ne 0) { throw "StarGlass index failed" }

Write-Host ""
Write-Host "Verifying detector regressions..."
& $exe --db .\state\publication_regression_v021.sqlite starglass `
  --manifest .\examples\regression_cases.csv `
  --plate bi05607 `
  --cache-dir .\cache\verified_starglass `
  --export .\results\publication_regression_v021.csv
if ($LASTEXITCODE -ne 0) { throw "regression execution failed" }

& $exe verify-regressions --results .\results\publication_regression_v021.csv
if ($LASTEXITCODE -ne 0) { throw "regression comparison failed" }

Write-Host ""
Write-Host "PUBLICATION FREEZE v0.2.1 PASSED."
Write-Host "Next: POSS-I identity preflight; no transient detection yet."
