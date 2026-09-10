param([Parameter(Mandatory=$true)][string]$ProjectRoot,[Parameter(Mandatory=$true)][string]$RepoRoot)
$ErrorActionPreference="Stop"
$Python=Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$Runner=Join-Path $PSScriptRoot "run_v094z_build_matcher_population.py"
$Contract=Join-Path $PSScriptRoot "v094z_matcher_population_contract.json"
$Out=Join-Path $ProjectRoot "work\v094z_source_blind_matcher_population_rc1"
if(Test-Path $Out){throw "HOLD: output already exists: $Out"}
& $Python $Runner --repo-root $RepoRoot --output-dir $Out --contract $Contract
if($LASTEXITCODE-ne 0){throw "v094z derivation HOLD"}
