param([Parameter(Mandatory=$true)][string]$ProjectRoot)
$ErrorActionPreference = "Stop"
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
& $Python (Join-Path $PSScriptRoot "run_v095a_stageA_inventory_rc9.py") --self-test
if ($LASTEXITCODE -ne 0) { throw "v095a RC9 self-test HOLD" }
