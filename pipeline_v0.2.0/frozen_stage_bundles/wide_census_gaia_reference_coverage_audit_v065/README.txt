WIDE CENSUS — GAIA REFERENCE-DOMAIN COVERAGE AUDIT v065
========================================================

Why this exists
---------------
v064 successfully completed the v063 acquisition plan. Before using those Gaia
rows for registration, this audit checks the acquisition geometry against the
already-frozen registration policy.

The v063 transport cells were generated from raw <=10" match midpoints.
Registration, however, may use ordinary detector/Gaia reference stars up to
30 arcmin from EACH raw target. In a sparse field, valid reference candidates
can therefore lie outside all v063 raw-midpoint cells.

There is also a narrow margin issue at the ordinary/HPM split:
the ordinary branch must accommodate the maximum 1951-55 -> Gaia J2016
displacement for a source just below 1700 mas/yr PLUS the frozen 15" reference
association radius.

v065 uses NO Gaia source rows and performs NO registration. It:
  * reads frozen raw target coordinates and all frozen detector candidate coordinates;
  * finds every detector candidate that could participate in a <=30' reference fit;
  * constructs the required global 0.25-degree candidate-domain cells;
  * identifies which cells are already in v064;
  * for existing MAXREC-subdivided cells, plans only thin outer-margin annuli
    around each COMPLETE leaf rather than downloading the 111M cached rows again;
  * plans full queries only for genuinely new cells;
  * plans corrected pair-level high-PM cones;
  * writes a prospective corrective transport freeze v002 before any registration.

No science threshold changes.

Run
---

  Expand-Archive ".\wide_census_gaia_reference_coverage_audit_v065.zip" `
      -DestinationPath ".\wide_census_gaia_reference_coverage_audit_v065" `
      -Force

  Copy-Item ".\wide_census_gaia_reference_coverage_audit_v065\*" ".\tools\" -Force

  & ".\.venv\Scripts\python.exe" `
      ".\tools\audit_wide_census_gaia_reference_coverage_v065.py"

This is CPU/local-I/O only. The 5.08M candidate CSV is streamed once; no new large
Gaia file is created by v065.
