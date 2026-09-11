param(
  [Parameter(Mandatory=$true)][string]$ProjectRoot,
  [Parameter(Mandatory=$true)][string]$RepoRoot
)
$ErrorActionPreference = "Stop"
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
& $Python (Join-Path $PSScriptRoot "run_v095a_stageA_inventory_rc9.py") `
  --preflight-only --project-root $ProjectRoot --repo-root $RepoRoot
if ($LASTEXITCODE -ne 0) { throw "v095a RC9 preflight HOLD" }
