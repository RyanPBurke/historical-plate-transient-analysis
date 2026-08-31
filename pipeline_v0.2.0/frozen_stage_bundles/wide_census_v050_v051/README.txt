WIDE CENSUS v050/v051

v050:
- no network
- resolves the residual six POSS cases for timing with vi25_start_utc()
- retains unresolved physical-scan provenance separately
- refuses to call the timing census final if any residual pair still has positive overlap

v051:
- no network
- checks physical-plate/site independence where already knowable
- builds the exact archive-footprint execution queue
- coarse FOV geometry is PRIORITIZATION ONLY and cannot reject a pair

Install:
  Copy extracted files to project\tools\
  & ".\.venv\Scripts\python.exe" ".\tools\upgrade_transient_automation_v050_v051.py"

Run:
  & ".\.venv\Scripts\python.exe" -m automation.runner run-until-blocked

Dashboard:
  Copy-Item ".\tools\transient_dashboard_v051.py" ".\tools\transient_dashboard.py" -Force
  restart dashboard.
