$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
$exe = Join-Path $PSScriptRoot ".venv\Scripts\transient-pipeline.exe"
& $exe --db state\regression.sqlite starglass --manifest examples\starglass_manifest.csv --plate bi05607 --export results\regression_results.csv
& $exe --db state\regression.sqlite verify-regressions --results results\regression_results.csv
