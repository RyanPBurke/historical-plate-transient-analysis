WIDE CENSUS HEAVY DETECTOR PREFLIGHT v054

Purpose:
- freezes one deterministic scan/WCS identity for every detector endpoint;
- resolves actual APPLAUSE DR4 FITS products via datalink;
- uses cached DASCH DR7 package metadata from v052;
- computes exact common-polygon pixel bounding boxes;
- freezes a deduplicated 1024-core / 64-halo tile workload;
- estimates network upper bound, local tile storage and free-disk floor;
- reads NO science pixels and does NOT run the detector.

The 41 v052 exact-footprint holds remain a separate unresolved branch.

Install:
  Copy extracted files into project\tools\
  & ".\.venv\Scripts\python.exe" ".\tools\upgrade_transient_automation_v054.py"

Run:
  & ".\.venv\Scripts\python.exe" -m automation.runner run-until-blocked --allow-network

Dashboard:
  Copy-Item ".\tools\transient_dashboard_v054.py" ".\tools\transient_dashboard.py" -Force
  restart dashboard.

After v054 passes, the next stage is the actual resumable frozen-detector run.
