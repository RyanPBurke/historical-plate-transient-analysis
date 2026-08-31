$ErrorActionPreference = "Stop"

if (-not (Test-Path .\.venv)) {
    py -3.12 -m venv .venv
}

& .\.venv\Scripts\python.exe -m pip install --upgrade pip
& .\.venv\Scripts\python.exe -m pip install -e .
& .\.venv\Scripts\python.exe -m pip install pytest
& .\.venv\Scripts\python.exe -m pytest -q

Write-Host ""
Write-Host "Installed historical-transient-pipeline v0.2.0 publication mode."
& .\.venv\Scripts\transient-pipeline.exe --help | Select-Object -First 8
