$ErrorActionPreference = "Stop"
$exe = ".\.venv\Scripts\transient-pipeline.exe"
$db = ".\state\poss1_identity_prospective.sqlite"
$stage = "poss1-identity:prospective_production"
$queue = ".\research\production_sub5_queue_2026-08-20.csv"

New-Item -ItemType Directory -Force .\logs | Out-Null
$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$log = ".\logs\poss1_identity_preflight_$stamp.log"
$stdout = ".\logs\poss1_identity_preflight_${stamp}_stdout.txt"
$stderr = ".\logs\poss1_identity_preflight_${stamp}_stderr.txt"

$possIds = @(
    Import-Csv $queue |
      Where-Object { $_.publication_cohort -eq "prospective_production" } |
      ForEach-Object {
          if ($_.exposure_a -like "POSS-I:*") { $_.exposure_a }
          if ($_.exposure_b -like "POSS-I:*") { $_.exposure_b }
      } |
      Sort-Object -Unique
)
$total = $possIds.Count

Start-Transcript -Path $log | Out-Null
try {
    Write-Host "POSS-I physical-plate identity/availability preflight v0.2.7"
    Write-Host "Unique prospective POSS-I exposures:" $total
    Write-Host "Primary source: STScI DSS. On retryable archive failure OR primary Plate Finder non-resolution: validated SkyView raw-DSS fallback. Valid VI/25 exposures with no current digital DSS pixels are accounted separately and remain in the denominator."
    Write-Host "No transient detection is performed by this command."
    Write-Host ""

    $args = @(
      "--db", $db,
      "poss1-preflight",
      "--queue", $queue,
      "--vi25", ".\research\poss1_plate_metadata.csv",
      "--cohort", "prospective_production",
      "--cache-dir", ".\cache\poss1_identity",
      "--export", ".\results\poss1_identity_preflight.csv"
    )

    Remove-Item $stdout,$stderr -Force -ErrorAction SilentlyContinue
    $p = Start-Process -FilePath $exe -ArgumentList $args -PassThru -NoNewWindow `
        -RedirectStandardOutput $stdout -RedirectStandardError $stderr

    $last = ""
    while (-not $p.HasExited) {
        Start-Sleep -Seconds 10
        $p.Refresh()
        try {
            $raw = & $exe --db $db status --stage $stage 2>$null | Out-String
            if (-not [string]::IsNullOrWhiteSpace($raw)) {
                $s = $raw | ConvertFrom-Json
                $ok = if ($null -ne $s.succeeded) { [int]$s.succeeded } else { 0 }
                $pending = if ($null -ne $s.pending) { [int]$s.pending } else { 0 }
                $running = if ($null -ne $s.running) { [int]$s.running } else { 0 }
                $retry = if ($null -ne $s.failed_retryable) { [int]$s.failed_retryable } else { 0 }
                $terminal = if ($null -ne $s.failed_terminal) { [int]$s.failed_terminal } else { 0 }
                $processed = $ok + $retry + $terminal
                $pct = if ($total -gt 0) { [math]::Round(100 * $processed / $total, 1) } else { 0 }
                $line = "[{0}] {1}/{2} processed ({3}%) | succeeded={4} pending={5} running={6} retryable={7} terminal={8}" -f `
                    (Get-Date -Format "HH:mm:ss"),$processed,$total,$pct,$ok,$pending,$running,$retry,$terminal
                if ($line -ne $last) { Write-Host $line; $last = $line }
            }
        }
        catch {
            Write-Host "[$(Get-Date -Format 'HH:mm:ss')] waiting for checkpoint database..."
        }
    }
    $p.WaitForExit()

    if (Test-Path $stdout) { Get-Content $stdout | ForEach-Object { Write-Host $_ } }
    if ((Test-Path $stderr) -and (Get-Item $stderr).Length -gt 0) {
        Write-Host ""; Write-Host "STDERR:"; Get-Content $stderr | ForEach-Object { Write-Host $_ }
    }

    $finalRaw = & $exe --db $db status --stage $stage 2>$null | Out-String
    if ([string]::IsNullOrWhiteSpace($finalRaw)) { throw "Could not read final POSS-I checkpoint state." }
    $final = $finalRaw | ConvertFrom-Json
    $ok = if ($null -ne $final.succeeded) { [int]$final.succeeded } else { 0 }
    $pending = if ($null -ne $final.pending) { [int]$final.pending } else { 0 }
    $running = if ($null -ne $final.running) { [int]$final.running } else { 0 }
    $retry = if ($null -ne $final.failed_retryable) { [int]$final.failed_retryable } else { 0 }
    $terminal = if ($null -ne $final.failed_terminal) { [int]$final.failed_terminal } else { 0 }

    Write-Host ""
    Write-Host "Final checkpoint:" $finalRaw.Trim()
    Write-Host ""
    Write-Host "Identity summary for succeeded jobs:"
    $rows = @(Import-Csv .\results\poss1_identity_preflight.csv)
    $rows |
      Where-Object { $_.status -eq "succeeded" } |
      Group-Object identity_status |
      Sort-Object Name |
      Select-Object Name,Count |
      Format-Table -AutoSize

    Write-Host "Identity source summary (blank = original STScI success):"
    $rows |
      Where-Object { $_.status -eq "succeeded" } |
      Group-Object identity_source |
      Sort-Object Name |
      Select-Object Name,Count |
      Format-Table -AutoSize

    Write-Host ""
    Write-Host "Evidence verification:"
    & $exe verify-evidence --root .\evidence
    if ($LASTEXITCODE -ne 0) { throw "evidence verification failed" }

    if ($terminal -gt 0) {
        throw "POSS-I preflight has terminal execution errors; inspect results/log before science."
    }
    if ($pending -gt 0 -or $running -gt 0) {
        throw "POSS-I preflight ended with pending/running jobs; inspect checkpoint."
    }
    if ($retry -gt 0) {
        Write-Host ""
        Write-Host "POSS-I IDENTITY PREFLIGHT PAUSED: $retry archive job(s) remain retryable."
        Write-Host "Re-run this same script later; completed jobs are preserved."
        Write-Host "No retryable failure is a scientific negative."
        Write-Host "Transcript:" $log
        return
    }

    $validated = @(
        $rows |
        Where-Object { $_.status -eq "succeeded" -and $_.identity_status -eq "validated" -and $_.eligible_for_science -match "^(True|true|1)$" }
    )
    $archiveUnavailable = @(
        $rows |
        Where-Object { $_.status -eq "succeeded" -and $_.identity_status -eq "catalogue_identified_pixels_unavailable" }
    )
    $otherSucceeded = @(
        $rows |
        Where-Object {
            $_.status -eq "succeeded" -and
            $_.identity_status -ne "validated" -and
            $_.identity_status -ne "catalogue_identified_pixels_unavailable"
        }
    )

    if ($otherSucceeded.Count -gt 0) {
        Write-Host ""
        $otherSucceeded |
          Select-Object exposure_id,identity_status,identity_source,finder_plate_id,finder_region,last_error |
          Format-Table -AutoSize
        throw "$($otherSucceeded.Count) POSS-I exposure(s) have unexpected succeeded identity states."
    }

    # v0.2.7 reviewed archive-availability exceptions.
    #
    # These are exact physical/catalogue identities with distinct validated
    # failure modes.  This is deliberately NOT a count-only allowance:
    # any other unavailable exposure, wrong region, wrong MLP mapping,
    # changed provenance class, or detector eligibility is terminal.
    $expectedArchiveUnavailable = @{
        "POSS-I:449:O:rec198" = @{
            finder_region                  = "XO197"
            vi25_mlp                       = "198"
            identity_source                = "vi25_plus_primary_stsci_failure_and_skyview_gap"
            descriptor_image_count         = "0"
            archive_failure_kind           = ""
            skyview_raw_hhh_url             = ""
        }
        "POSS-I:832:E:rec760" = @{
            finder_region                  = "XE760"
            vi25_mlp                       = "761"
            identity_source                = "vi25_plus_primary_stsci_failure_and_skyview_descriptor_raw_hhh_gap"
            descriptor_image_count         = "1"
            archive_failure_kind           = "skyview_raw_hhh_http_404"
            skyview_raw_hhh_url             = "https://skyview.gsfc.nasa.gov/surveys/dss/xe760/xe760.hhh"
        }
    }

    if ($archiveUnavailable.Count -ne $expectedArchiveUnavailable.Count) {
        throw (
            "Archive-unavailable exposure count mismatch: expected " +
            "$($expectedArchiveUnavailable.Count), got $($archiveUnavailable.Count)."
        )
    }

    foreach ($row in $archiveUnavailable) {
        if (-not $expectedArchiveUnavailable.ContainsKey($row.exposure_id)) {
            throw "Unexpected archive-unavailable exposure: $($row.exposure_id)"
        }

        $expected = $expectedArchiveUnavailable[$row.exposure_id]

        if ($row.finder_region -ne $expected.finder_region) {
            throw (
                "Archive-unavailable region mismatch for $($row.exposure_id): " +
                "$($row.finder_region) != $($expected.finder_region)"
            )
        }

        if ($row.vi25_mlp -ne $expected.vi25_mlp) {
            throw (
                "Archive-unavailable VI/25 MLP mismatch for $($row.exposure_id): " +
                "$($row.vi25_mlp) != $($expected.vi25_mlp)"
            )
        }

        if ($row.identity_source -ne $expected.identity_source) {
            throw (
                "Archive-unavailable identity-source mismatch for $($row.exposure_id): " +
                "$($row.identity_source)"
            )
        }

        if ($row.archive_availability_status -ne "digital_pixels_unavailable") {
            throw (
                "Archive availability status changed for $($row.exposure_id): " +
                "$($row.archive_availability_status)"
            )
        }

        if ($row.eligible_for_science -notmatch "^(False|false|0)$") {
            throw (
                "Archive-unavailable exposure became detector/science eligible: " +
                "$($row.exposure_id)"
            )
        }

        if (
            $row.skyview_descriptor_image_count -ne
            $expected.descriptor_image_count
        ) {
            throw (
                "SkyView descriptor-count mismatch for $($row.exposure_id): " +
                "$($row.skyview_descriptor_image_count) != " +
                "$($expected.descriptor_image_count)"
            )
        }

        if (
            $row.archive_failure_kind -ne
            $expected.archive_failure_kind
        ) {
            throw (
                "Archive failure-kind mismatch for $($row.exposure_id): " +
                "$($row.archive_failure_kind) != " +
                "$($expected.archive_failure_kind)"
            )
        }

        if (
            $row.skyview_raw_hhh_url -ne
            $expected.skyview_raw_hhh_url
        ) {
            throw (
                "Raw-HHH URL mismatch for $($row.exposure_id): " +
                "$($row.skyview_raw_hhh_url)"
            )
        }
    }

    if ($ok -ne $total) { throw "Expected $total accounted jobs, got $ok succeeded." }
    if (($validated.Count + $archiveUnavailable.Count) -ne $total) {
        throw "Succeeded-job accounting mismatch: validated + archive-unavailable does not equal total."
    }

    Write-Host ""
    if ($archiveUnavailable.Count -eq 0) {
        Write-Host "POSS-I IDENTITY PREFLIGHT PASSED: $($validated.Count)/$total unique exposures pixel-validated."
    } else {
        Write-Host "POSS-I IDENTITY/AVAILABILITY PREFLIGHT ACCOUNTED: $total/$total exposures."
        Write-Host "  pixel-validated / detector-eligible:" $validated.Count
        Write-Host "  catalogue-identified but digital pixels unavailable:" $archiveUnavailable.Count
        $archiveUnavailable |
          Select-Object exposure_id,identity_status,identity_source,finder_region,archive_availability_status |
          Format-Table -AutoSize
        Write-Host "Archive-unavailable exposure(s) remain in the frozen prospective denominator and are NOT scientific negatives."
    }
    Write-Host "No transient detector was run."
    Write-Host "Transcript:" $log
}
finally {
    Stop-Transcript | Out-Null
}
