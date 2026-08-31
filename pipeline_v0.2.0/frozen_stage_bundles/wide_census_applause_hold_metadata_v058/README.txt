WIDE CENSUS — APPLAUSE HOLD OFFICIAL METADATA INVENTORY v058
================================================================

Purpose
-------
Work on the dominant branch found by v057 while v056 continues:
  34 endpoint occurrences: UNRESOLVED_APPLAUSE_NO_EXACT_POLYGON
   1 endpoint occurrence : UNRESOLVED_APPLAUSE_SOLUTION_EXPOSURE_ASSOCIATION

This is a standalone parallel script. It does NOT edit the automation registry
or v052 classifications.

Method
------
1. Read the v057 41-hold inventory.
2. Crosswalk each unresolved APPLAUSE exposure_id to exact plate_id/archive_id
   using applause_exposures_1951_1955.csv.
3. Query official APPLAUSE DR4 metadata only:
     applause_dr4.solution
     applause_dr4.scan
4. Preserve every official solution identity:
     solution_id, process_id, solutionset_id, scan_id, plate_id,
     archive_id, solution_num.
5. Preserve exact scan metadata:
     filename_scan, naxis1, naxis2, file_size, FITS checksum.
6. For each solution:
   - use official solution.stc_polygon when present;
   - otherwise reconstruct the image footprint from official header_wcs plus
     exact scan dimensions using WCS.calc_footprint(center=False).
7. DO NOT choose among multiple solutions. Exposure-center separation is
   diagnostic ordering only.
8. Compare official stc_polygon vs header-WCS-derived footprints when both
   exist, for an audit distribution only. No outcome-derived threshold.

Guards
------
NETWORK: APPLAUSE TAP metadata only
SCIENCE PIXELS: NO
DETECTOR: NO
CANDIDATE STATE MUTATION: NO
v052 CLASSIFICATION MUTATION: NO
AUTOMATION REGISTRY EDIT: NO

Run in the SECOND PowerShell window while v056 continues:

  Expand-Archive ".\wide_census_applause_hold_metadata_v058.zip" `
      -DestinationPath ".\wide_census_applause_hold_metadata_v058" `
      -Force

  Copy-Item ".\wide_census_applause_hold_metadata_v058\*" ".\tools\" -Force

  & ".\.venv\Scripts\python.exe" `
      ".\tools\analyze_wide_census_applause_holds_v058.py"

Expected output is a distribution such as:
  UNIQUE_POLYGONABLE_OFFICIAL_SOLUTION
  MULTIPLE_POLYGONABLE_OFFICIAL_SOLUTIONS_RETAIN_ASSOCIATION_HOLD
  OFFICIAL_SOLUTIONS_PRESENT_BUT_NO_USABLE_EXACT_FOOTPRINT
  NO_OFFICIAL_SOLUTION_ROWS_FOR_PHYSICAL_PLATE

The result tells us how much of the 35-endpoint APPLAUSE branch can be resolved
mechanically in the next separately frozen resolver.
