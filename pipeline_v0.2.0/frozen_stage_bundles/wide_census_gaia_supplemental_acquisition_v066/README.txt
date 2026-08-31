WIDE CENSUS — SUPPLEMENTAL GAIA DR3 ACQUISITION v066
====================================================

Prerequisite
------------
v065 PASS with corrective transport freeze:
458a043dfbdda8dbb853cbae77c269ff17a586c0ddb2fdcf7ac0388ee57ab3fc

Frozen supplemental workload:
  6,651 existing-leaf thin-margin annuli
  6,980 genuinely new 0.25-degree base cells
 13,631 ordinary supplemental root tasks total
     33 corrected pair-level HPM queries

Engineering changes for speed/disk
----------------------------------
- EXACTLY 2 concurrent Gaia TAP workers by default.
- ONE global request-start limiter shared by both workers: at least 0.75 seconds
  between ANY request starts, including retries and MAXREC children.
- Therefore MAXREC subdivision cannot create an uncontrolled request burst.
- Each successful response is checkpointed immediately.
- New v066 responses are stored as lossless deterministic gzip rather than raw CSV.
- Both the uncompressed response SHA256 and compressed-file SHA256 are recorded.
- Abort if free disk falls below 12 GiB.
- Resume scans/verifies existing v066 cache once; no per-query global rescans.

Science/coverage behavior unchanged
-----------------------------------
- v065/v002 defines all query geometry.
- Existing-leaf annulus hitting MAXREC is an OPERATIONAL BLOCKER, as prospectively frozen.
- New full cell hitting MAXREC is recursively quartered to the frozen 0.03125-degree minimum.
- No Gaia source is interpreted here.
- No epoch propagation.
- No registration.
- No candidate disposition.

Install
-------

  Expand-Archive ".\wide_census_gaia_supplemental_acquisition_v066.zip" `
      -DestinationPath ".\wide_census_gaia_supplemental_acquisition_v066" `
      -Force

  Copy-Item ".\wide_census_gaia_supplemental_acquisition_v066\*" ".\tools\" -Force

Recommended: 20-root concurrent smoke test first:

  & ".\.venv\Scripts\python.exe" `
      ".\tools\run_wide_census_gaia_supplemental_acquisition_v066.py" `
      --max-new 20

Then resume uncapped:

  & ".\.venv\Scripts\python.exe" `
      ".\tools\run_wide_census_gaia_supplemental_acquisition_v066.py"

If Gaia TAP becomes unstable, resume safely with one worker:

  & ".\.venv\Scripts\python.exe" `
      ".\tools\run_wide_census_gaia_supplemental_acquisition_v066.py" `
      --workers 1

A network failure or disk-space guard is operational only, never a scientific negative.


Checkpoint-performance note
---------------------------
v066 does NOT globally rescan/hash the growing cache every 50 roots. Progress
checkpoints are lightweight. Full cache reconciliation occurs at startup, once
at the ordinary->HPM transition, and at finalization; each response is hashed
individually when committed.
