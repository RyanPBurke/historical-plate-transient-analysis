param(
  [Parameter(Mandatory=$true)][string]$ProjectRoot,
  [Parameter(Mandatory=$true)][switch]$AcknowledgeSupersedingReadOnlyRetry
)
$ErrorActionPreference = "Stop"

if (-not $AcknowledgeSupersedingReadOnlyRetry) {
  throw "HOLD: explicit -AcknowledgeSupersedingReadOnlyRetry is required"
}

$Relative = "work/v095a_stageA_aggregate_inventory_rc4/jobs/Q0_SELECTED_SOLUTION_BINDING/batch_0001/meta.json"
$Source = Join-Path $ProjectRoot ($Relative -replace '/', '\')
if (-not (Test-Path $Source -PathType Leaf)) { throw "HOLD: preserved RC4 checkpoint missing" }

$Meta = Get-Content $Source -Raw | ConvertFrom-Json
if ($Meta.family -ne "Q0_SELECTED_SOLUTION_BINDING" -or [int]$Meta.batch -ne 1) { throw "HOLD: RC4 batch identity mismatch" }
if ($Meta.status -ne "FAILED_HOLD") { throw "HOLD: RC4 checkpoint is not FAILED_HOLD" }
if (-not ([string]$Meta.failure).StartsWith("SUBMISSION_UNCERTAIN_HOLD")) { throw "HOLD: RC4 failure is not unknown submission" }
if ([int]$Meta.transport_request_attempts -ne 1) { throw "HOLD: RC4 request count is not exactly one" }
$Attempts = @($Meta.attempts)
if ($Attempts.Count -ne 1) { throw "HOLD: RC4 attempt count is not exactly one" }
if ([int]$Attempts[0].attempt -ne 1 -or $Attempts[0].state -ne "SUBMITTING") { throw "HOLD: RC4 attempt state mismatch" }
if ($Attempts[0].job_url) { throw "HOLD: RC4 has a job URL and must be reconciled instead" }

$Evidence = [ordered]@{
  schema_version = 1
  incident_id = "v095a-rc4-first-live-q0-submission"
  status = "UNRESOLVED_UNKNOWN_SUBMISSION_ACKNOWLEDGED_FOR_SUPERSEDING_READ_ONLY_RETRY"
  acknowledged_superseding_read_only_retry = $true
  acknowledgement_scope = "One preserved RC4 Q0 aggregate-only POST may have been accepted. Authorize a superseding reviewed Stage A aggregate-only attempt without reclassifying or deleting the RC4 evidence."
  acknowledged_utc = [DateTime]::UtcNow.ToString("o")
  source_checkpoint_relative = $Relative
  source_checkpoint_sha256 = (Get-FileHash $Source -Algorithm SHA256).Hash.ToLower()
  recorded_family = [string]$Meta.family
  recorded_batch = [int]$Meta.batch
  recorded_transport_request_attempts = [int]$Meta.transport_request_attempts
  recorded_attempt_count = $Attempts.Count
  recorded_attempt_state = [string]$Attempts[0].state
  recorded_job_url_present = [bool]$Attempts[0].job_url
  recorded_failure = [string]$Meta.failure
  recorded_created_utc = [string]$Meta.created_utc
  recorded_updated_utc = [string]$Meta.updated_utc
}

$Dest = Join-Path $ProjectRoot "work\v095a_rc4_unknown_submission_disposition.json"
$Evidence | ConvertTo-Json -Depth 5 | Set-Content $Dest -Encoding UTF8
Write-Host "v095a RC4 UNKNOWN SUBMISSION DISPOSITION PASS"
Write-Host "status: $($Evidence.status)"
Write-Host "source_sha256: $($Evidence.source_checkpoint_sha256)"
Write-Host "evidence: $Dest"
