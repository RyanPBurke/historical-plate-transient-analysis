
CENSUS SCOPE v048

This upgrade makes no network requests, reads no pixels, reruns no detector,
and mutates no candidate state.

Copy all files in this folder to project\tools\, then:

& ".\.venv\Scripts\python.exe" ".\tools\upgrade_transient_automation_v048_census_scope.py"
& ".\.venv\Scripts\python.exe" -m automation.runner status
& ".\.venv\Scripts\python.exe" -m automation.runner run-next
& ".\.venv\Scripts\python.exe" -m automation.runner verify-stage --stage project_census_scope_audit_v048

Optional dashboard replacement:

Copy-Item ".\tools\transient_dashboard_v048.py" ".\tools\transient_dashboard.py" -Force

Then restart the dashboard.

Expected scope audit:
- 236 unique wide catalogue-time candidate pairs
- 10 archive-pair families
- <=5 min: 32
- <=10 min cumulative: 73
- <=15 min cumulative: 111
- all 111 remain non-science-eligible until physical timing and physical-plate provenance are validated
