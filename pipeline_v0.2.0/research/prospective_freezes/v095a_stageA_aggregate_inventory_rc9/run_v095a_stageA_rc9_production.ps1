param(
  [Parameter(Mandatory=$true)][string]$ProjectRoot,
  [Parameter(Mandatory=$true)][string]$RepoRoot,
  [Parameter(Mandatory=$true)][string]$FreezeCommit,
  [Parameter(Mandatory=$true)][string]$FreezeEvidence,
  [Parameter(Mandatory=$true)][string]$PriorIncidentEvidence,
  [string]$TokenEnv = "APPLAUSE_TOKEN"
)
$ErrorActionPreference = "Stop"
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
& $Python (Join-Path $PSScriptRoot "run_v095a_stageA_inventory_rc9.py") `
  --production --project-root $ProjectRoot --repo-root $RepoRoot `
  --freeze-commit $FreezeCommit --freeze-evidence $FreezeEvidence `
  --prior-incident-evidence $PriorIncidentEvidence --token-env $TokenEnv
if ($LASTEXITCODE -ne 0) { throw "v095a RC9 production HOLD" }
