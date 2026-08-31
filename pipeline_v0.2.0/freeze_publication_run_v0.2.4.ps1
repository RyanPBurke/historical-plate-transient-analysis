$ErrorActionPreference = "Stop"
$exe = ".\.venv\Scripts\transient-pipeline.exe"
$python = ".\.venv\Scripts\python.exe"

Write-Host "Running v0.2.4 tests..."
& $python -m pytest tests -q
if ($LASTEXITCODE -ne 0) { throw "pytest failed" }

$migration = ".\research\EVIDENCE_INDEX_MIGRATION_v0.2.2_2026-08-20.json"
if (-not (Test-Path $migration)) {
    throw "v0.2.2 evidence migration record is missing; do not freeze v0.2.4."
}

$controls = ".\work\poss_preflight\skyview_equivalence_all5_v2\all5_equivalence_summary.json"
if (-not (Test-Path $controls)) {
    throw "Missing 5/5 SkyView/STScI equivalence control summary: $controls"
}
$controlJson = Get-Content $controls -Raw | ConvertFrom-Json
if ([int]$controlJson.strict_pass_count -ne 5 -or [int]$controlJson.strict_total -ne 5 -or -not [bool]$controlJson.all_five_strict_equivalence_pass) {
    throw "SkyView/STScI equivalence controls are not a strict 5/5 PASS."
}
$expectedJar = "2b949f68d73899cd63b2f600f60f6c5dfd1795532ed29b6ea986f71f83d36afe"
if ([string]$controlJson.skyview_jar_sha256 -ne $expectedJar) {
    throw "Unexpected SkyView control JAR hash in all5 summary."
}

$jar = ".\work\poss_preflight\skyview_source\skyview.jar"
if (-not (Test-Path $jar)) { throw "Missing preserved SkyView control JAR: $jar" }
$jarHash = (Get-FileHash $jar -Algorithm SHA256).Hash.ToLower()
if ($jarHash -ne $expectedJar) { throw "Preserved SkyView JAR hash mismatch." }

$dss1b = ".\work\poss_preflight\skyview_source\dss1b_external_definition\dss1b.xml"
$manifest = ".\work\poss_preflight\skyview_source\dss1b_external_definition\survey.manifest"
if (-not (Test-Path $dss1b)) { throw "Missing preserved DSS1B descriptor: $dss1b" }
if (-not (Test-Path $manifest)) { throw "Missing preserved SkyView survey manifest: $manifest" }
if ((Get-FileHash $dss1b -Algorithm SHA256).Hash.ToLower() -ne "36e8b0380a60dba556091f0c4cb9ff5cb6fb33478918fc0f34a0500a35a40603") {
    throw "DSS1B descriptor hash mismatch."
}
if ((Get-FileHash $manifest -Algorithm SHA256).Hash.ToLower() -ne "0fdf1796c9d15023b7fb7355203569e063c378ea34c25f29e15d90a010ebb325") {
    throw "SkyView survey manifest hash mismatch."
}

$correction = ".\research\POSS1_SKYVIEW_IDENTITY_GATE_CORRECTION_v0.2.4_2026-08-20.md"
if (-not (Test-Path $correction)) { throw "Missing v0.2.4 identity-gate correction note: $correction" }

Write-Host "Registering v0.2.4 identity-gate correction note..."
& $exe register-artifact --file $correction --kind poss1_identity_gate_correction --stage publication_freeze_v0.2.4 --snapshot
if ($LASTEXITCODE -ne 0) { throw "v0.2.4 correction-note evidence registration failed" }

Write-Host "Verifying evidence store before v0.2.4 control registration..."
& $exe verify-evidence --root .\evidence
if ($LASTEXITCODE -ne 0) { throw "evidence verification failed before v0.2.4 snapshot" }

Write-Host "Registering 5/5 mirror controls and preserved SkyView metadata..."
& $exe register-artifact --file $controls --kind skyview_dss_mirror_equivalence_controls --stage publication_freeze_v0.2.4 --snapshot
if ($LASTEXITCODE -ne 0) { throw "control-summary evidence registration failed" }
& $exe register-artifact --file $jar --kind skyview_control_reader_jar --stage publication_freeze_v0.2.4 --source-url "https://skyview.gsfc.nasa.gov/jar/skyview.jar"
if ($LASTEXITCODE -ne 0) { throw "SkyView JAR evidence registration failed" }
& $exe register-artifact --file $dss1b --kind skyview_dss1b_descriptor --stage publication_freeze_v0.2.4 --source-url "https://skyview.gsfc.nasa.gov/current/jar/surveys/xml/dss1b.xml.gz" --snapshot
if ($LASTEXITCODE -ne 0) { throw "DSS1B descriptor evidence registration failed" }
& $exe register-artifact --file $manifest --kind skyview_survey_manifest --stage publication_freeze_v0.2.4 --source-url "https://skyview.gsfc.nasa.gov/current/jar/surveys/survey.manifest" --snapshot
if ($LASTEXITCODE -ne 0) { throw "SkyView manifest evidence registration failed" }

Write-Host "Verifying evidence store after control registration..."
& $exe verify-evidence --root .\evidence
if ($LASTEXITCODE -ne 0) { throw "evidence verification failed after v0.2.4 control registration" }

$out = ".\research_snapshots\sub5_production_freeze_v0.2.4_2026-08-20"

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
  --extra .\research\EVIDENCE_INDEX_MIGRATION_v0.2.2_2026-08-20.json `
  --extra .\research\SKYVIEW_DSS_MIRROR_EQUIVALENCE_NOTE_2026-08-20.md `
  --extra $correction `
  --extra $controls `
  --extra $dss1b `
  --extra $manifest `
  --activate
if ($LASTEXITCODE -ne 0) { throw "publication snapshot failed" }

Write-Host ""
Write-Host "Indexing existing StarGlass FITS..."
& $exe index-starglass-cache --root .\cache\verified_starglass
if ($LASTEXITCODE -ne 0) { throw "StarGlass index failed" }

Write-Host ""
Write-Host "Verifying detector regressions..."
& $exe --db .\state\publication_regression_v024.sqlite starglass `
  --manifest .\examples\regression_cases.csv `
  --plate bi05607 `
  --cache-dir .\cache\verified_starglass `
  --export .\results\publication_regression_v024.csv
if ($LASTEXITCODE -ne 0) { throw "regression execution failed" }

& $exe verify-regressions --results .\results\publication_regression_v024.csv
if ($LASTEXITCODE -ne 0) { throw "regression comparison failed" }

Write-Host ""
Write-Host "PUBLICATION FREEZE v0.2.4 PASSED."
Write-Host "SkyView raw-DSS fallback control basis: strict 5/5 pixel equivalence."
Write-Host "Next: run .\repair_poss1_identity_state_v0.2.4.ps1, then .\run_poss1_identity_preflight.ps1; no transient detection yet."
