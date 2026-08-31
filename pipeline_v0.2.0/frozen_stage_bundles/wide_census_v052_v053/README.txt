WIDE CENSUS EXACT FOOTPRINT + DETECTOR PLAN v052/v053

v052:
- one APPLAUSE DR4 TAP query for exact solution.stc_polygon data on 49 physical plates
- DASCH DR7 mosaic-package metadata in resumable batches of 8 plates
- exact archive astrometry, not nominal FOV, determines sky overlap
- multiple scans / near-degenerate solutions are propagated conservatively
- ambiguous geometry becomes HOLD, never a forced positive or negative
- NO science pixels and NO detector execution

v053:
- local only
- robust true-overlap opportunities become READY_FOR_FROZEN_DETECTOR_EXECUTION
- no-overlap pairs close the two-observatory opportunity branch
- holds remain separate
- no transient candidate is promoted

Install after extracting this flat ZIP into the project root:
  Copy-Item ".\wide_census_v052_v053\*" ".\tools\" -Force
  & ".\.venv\Scripts\python.exe" ".\tools\upgrade_transient_automation_v052_v053.py"

Run:
  & ".\.venv\Scripts\python.exe" -m automation.runner run-until-blocked --allow-network
