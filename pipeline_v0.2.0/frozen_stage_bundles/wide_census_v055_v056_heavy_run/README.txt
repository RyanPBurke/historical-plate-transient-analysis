WIDE CENSUS DISK-BOUNDED HEAVY RUN v055/v056

v055 (local, quick):
- certifies a storage-only change: native science tiles are processed in memory,
  content-hashed, run through the unchanged frozen detector, and released;
- persists candidate CSV + per-tile audit JSON, not 29+ GiB of .npy pixel copies;
- preserves native 1024 core / 64 halo / no-resampling / core-only acceptance;
- uses a very conservative 2 MiB result allowance per tile + 2 GiB fixed output
  + 8 GiB untouched safety reserve.

v056 (THE ACTUAL HEAVY RUN):
- 6293 native tiles across 53 endpoints / 33 robust observing opportunities;
- remote FITS range/section access;
- frozen detector SHA and frozen method SHA guarded;
- <=32 tiles per runner cycle;
- successful tiles checkpointed and skipped on resume;
- tile native pixels SHA256-recorded but not persisted;
- final pairwise raw <=10" and <=3" coincidence inventory is restricted to the
  exact v054 common-sky polygon;
- raw matches are NOT classified as transients;
- 41 v052 exact-footprint holds remain outside this run and remain unresolved.

Install:
  Copy extracted files into project\tools\
  & ".\.venv\Scripts\python.exe" ".\tools\upgrade_transient_automation_v055_v056.py"

START THE HEAVY RUN:
  & ".\.venv\Scripts\python.exe" -m automation.runner run-until-blocked --allow-network

Dashboard:
  Copy-Item ".\tools\transient_dashboard_v056.py" ".\tools\transient_dashboard.py" -Force
  restart dashboard.

Expected runtime: this is intentionally the long-running phase. Leave
run-until-blocked running; it will checkpoint every <=32 tiles and can resume.
