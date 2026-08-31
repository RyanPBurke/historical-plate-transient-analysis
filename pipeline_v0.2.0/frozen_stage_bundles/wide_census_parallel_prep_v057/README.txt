WIDE CENSUS PARALLEL PREP v057
================================

These two standalone scripts are intentionally NOT added to the automation
registry while the v056 heavy detector run is live.

1) freeze_wide_census_postdetector_contract_v057.py

Run this NOW, while v056 is still running, to freeze the post-detector
adjudication logic prospectively before the completed v056 raw-match outcome
is inspected.

It reads only completed v052/v053/v054 products plus candidate policies v001
and v002. It explicitly does not read any v056 candidate/output file.

Outputs:
  research/prospective_freezes/wide_census_postdetector_adjudication_contract_v001.json
  results/wide_census_postdetector_adjudication_freeze_v057.json

2) analyze_wide_census_geometry_holds_v057.py

A cheap local/read-only science-state analysis of the 41 v052 geometry holds.
It records the exact side-level unresolved states and maps each to a generic
metadata-only repair branch without changing any footprint classification.

Outputs:
  results/wide_census_geometry_hold_inventory_v057/
    wide_census_geometry_hold_inventory_v057.json
    wide_census_geometry_hold_inventory_v057.csv
    wide_census_geometry_hold_cause_counts_v057.csv

Both scripts:
- no network
- no science pixels
- no detector
- no candidate state mutation
- no automation-registry edit

Suggested parallel execution in a SECOND PowerShell window:

  & ".\.venv\Scripts\python.exe" ".\tools\freeze_wide_census_postdetector_contract_v057.py"

  & ".\.venv\Scripts\python.exe" ".\tools\analyze_wide_census_geometry_holds_v057.py"

Do not stop the v056 heavy-run window.
