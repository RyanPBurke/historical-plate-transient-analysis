$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (-not (Test-Path .venv)) {
    py -3.12 -m venv .venv
}
$python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
& $python -m pip install --upgrade pip
& $python -m pip install -e .
& $python -m pip install pytest
& $python -m pytest -q
Write-Host "Pipeline installed and self-tests passed."
Write-Host "Use: .venv\Scripts\transient-pipeline.exe --help"
