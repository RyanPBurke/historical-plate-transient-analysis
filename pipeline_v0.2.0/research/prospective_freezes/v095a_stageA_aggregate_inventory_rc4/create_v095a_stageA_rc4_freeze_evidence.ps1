param(
  [Parameter(Mandatory=$true)][string]$ProjectRoot,
  [Parameter(Mandatory=$true)][string]$RepoRoot,
  [Parameter(Mandatory=$true)][string]$FreezeCommit
)
$ErrorActionPreference = "Stop"
$Rel = "pipeline_v0.2.0/research/prospective_freezes/v095a_stageA_aggregate_inventory_rc4"
$Dir = Join-Path $RepoRoot $Rel
$Manifest = Join-Path $Dir "release_manifest.sha256"

if ($FreezeCommit -notmatch '^[0-9a-fA-F]{40}$') { throw "HOLD: full 40-hex freeze commit required" }
$Head = (& git -C $RepoRoot rev-parse HEAD).Trim()
if ($Head -ne $FreezeCommit) { throw "HOLD: HEAD != freeze commit" }
$Dirty = (& git -C $RepoRoot status --porcelain --untracked-files=no) -join "`n"
if ($Dirty) { throw "HOLD: tracked worktree/index not clean" }
if (-not (Test-Path $Manifest)) { throw "HOLD: release manifest missing" }

Get-Content $Manifest | ForEach-Object {
  if ($_ -match '^([0-9a-fA-F]{64})\s+(.+)$') {
    $ExpectedSha = $Matches[1].ToLower()
    $Name = $Matches[2].Trim()
    $File = Join-Path $Dir $Name
    if (-not (Test-Path $File)) { throw "HOLD: missing release file $Name" }
    $ActualSha = (Get-FileHash $File -Algorithm SHA256).Hash.ToLower()
    if ($ActualSha -ne $ExpectedSha) { throw "HOLD: release SHA mismatch $Name" }
    $RawBlob = (& git -C $RepoRoot hash-object --no-filters $File).Trim()
    $GitBlob = (& git -C $RepoRoot rev-parse "$FreezeCommit`:$Rel/$Name").Trim()
    if ($RawBlob -ne $GitBlob) { throw "HOLD: Git blob byte mismatch $Name" }
  }
}

$Remote = ((& git -C $RepoRoot ls-remote origin refs/heads/main) -split '\s+')[0]
if ($Remote -ne $FreezeCommit) { throw "HOLD: origin/main != freeze commit" }

$Evidence = [ordered]@{
  status = "REMOTE_FREEZE_VERIFIED"
  freeze_commit = $FreezeCommit
  origin_main = $Remote
  release_manifest_sha256 = (Get-FileHash $Manifest -Algorithm SHA256).Hash.ToLower()
  git_provenance_network_calls = 1
  verified_utc = [DateTime]::UtcNow.ToString("o")
}
$Dest = Join-Path $ProjectRoot "work\v095a_stageA_rc4_freeze_evidence.json"
$Evidence | ConvertTo-Json -Depth 5 | Set-Content $Dest -Encoding UTF8
Write-Host "v095a RC4 FREEZE EVIDENCE PASS"
Write-Host "commit: $FreezeCommit"
Write-Host "evidence: $Dest"
