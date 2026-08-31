WIDE CENSUS — APPLAUSE PROCESS / SOLUTION-SET AUDIT v059
================================================================

Why
---
v058 found:
- 35 unresolved APPLAUSE endpoint occurrences
- 21 unique exposure IDs
- 12 physical plates
- 12 official scan rows
- only 1 official solution row
- 34 endpoint occurrences attached to plates with no solution row

v059 asks what "no solution row" actually means.

Official metadata queried
-------------------------
applause_dr4.process:
  process_id, scan_id, plate_id, archive_id, num_exposures,
  num_sources, solved, num_solutions, num_gaia_edr3,
  calibrated, completed, pyplate_version, timestamps

applause_dr4.solution_set:
  solutionset_id, process_id, scan_id, plate_id, archive_id,
  num_solutions, FOV/pixel scale summary, header_wcs

Exact scan identity is read from v058's cached official scan response.

Possible plate states
---------------------
V058_OFFICIAL_SOLUTION_ALREADY_PRESENT

NO_SOLUTION_ROW_BUT_USABLE_SOLUTION_SET_WCS
  Potentially recoverable later under a separately frozen resolver.

ASTROMETRY_REPORTED_SOLVED_BUT_NO_USABLE_SOLUTION_ROW_OR_SET_WCS
  Metadata inconsistency/coverage hold; do not infer a footprint.

PROCESS_COMPLETED_ASTROMETRICALLY_UNSOLVED
  The archive processed the scan but reports no astrometric solution.

PROCESS_PRESENT_NOT_COMPLETED_OR_UNSOLVED
  Processing exists but cannot be treated as completed astrometric failure.

NO_PROCESS_ROW_FOR_EXACT_SCAN
  Digitized scan exists, but no matching DR4 processing record.

Guards
------
NETWORK: APPLAUSE DR4 metadata only
SCIENCE PIXELS: NO
DETECTOR: NO
CANDIDATE STATE: NO CHANGE
v052/v058 CLASSIFICATION: NO CHANGE
AUTOMATION REGISTRY: NO CHANGE

Run while v056 continues:

  Expand-Archive ".\wide_census_applause_process_audit_v059.zip" `
      -DestinationPath ".\wide_census_applause_process_audit_v059" `
      -Force

  Copy-Item ".\wide_census_applause_process_audit_v059\*" ".\tools\" -Force

  & ".\.venv\Scripts\python.exe" `
      ".\tools\audit_wide_census_applause_process_v059.py"
