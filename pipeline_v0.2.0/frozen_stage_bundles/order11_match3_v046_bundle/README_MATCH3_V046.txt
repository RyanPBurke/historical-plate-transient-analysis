ORDER 11 / MATCH 3 — v044/v045 + local dashboard bundle

Extract this bundle into the project root so that tools/ and config/ merge with the existing directories.
No frozen science/result file is included or replaced.

1) Optional dashboard (leave this PowerShell window open):
   & ".\.venv\Scripts\python.exe" ".\tools\transient_dashboard.py"
   Browser: http://127.0.0.1:8765/

2) Sparse-field astrometry fallback:
   & ".\.venv\Scripts\python.exe" ".\tools\run_order11_match3_adjudication_v044.py"

3) If v044 completes, morphology + consolidated disposition:
   & ".\.venv\Scripts\python.exe" ".\tools\run_order11_match3_morphology_final_v045.py"

Frozen candidate-adjudication policy:
   config\candidate_adjudication_policy_v001.json
   SHA256 a42be953f8162520de83f3b9d4e7e8f9cf2935d9a78b7b743de267107bea3af5

The policy is frozen before the v044/v045 scientific outcome. v044 and v045 verify its hash.
