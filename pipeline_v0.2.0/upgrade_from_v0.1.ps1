param(
    [Parameter(Mandatory=$true)]
    [string]$OldRoot
)

$ErrorActionPreference = "Stop"
$NewRoot = $PSScriptRoot
$OldRoot = (Resolve-Path $OldRoot).Path

Write-Host "Old research root: $OldRoot"
Write-Host "New publication root: $NewRoot"

if ($OldRoot -eq $NewRoot) {
    throw "OldRoot and new root are the same. This upgrader intentionally creates an adjacent publication copy."
}

$dirs = @("state", "results", "cache", "logs", "work")

foreach ($d in $dirs) {
    $src = Join-Path $OldRoot $d
    $dst = Join-Path $NewRoot $d
    if (Test-Path $src) {
        New-Item -ItemType Directory -Force $dst | Out-Null
        Write-Host "Copying $d ..."
        Copy-Item -Path (Join-Path $src "*") -Destination $dst -Recurse -Force -ErrorAction SilentlyContinue
    }
}

# Preserve any top-level research closure/checkpoint notes without replacing the new code/protocol files.
foreach ($pattern in @("*.md", "*.json", "*.csv")) {
    Get-ChildItem -Path $OldRoot -Filter $pattern -File -ErrorAction SilentlyContinue |
        ForEach-Object {
            $dest = Join-Path $NewRoot ("legacy_" + $_.Name)
            if (-not (Test-Path $dest)) {
                Copy-Item $_.FullName $dest
            }
        }
}

Write-Host "Research state/cache/results copied. New source code and frozen publication protocol were not overwritten."
Write-Host "Next: run .\bootstrap_publication.ps1"
