WIDE CENSUS — GAIA GLOBAL-CACHE DEDUP v063a + ACQUISITION v064
=================================================================

v063 successfully froze a 9,191-row pair-scoped ordinary Gaia transport plan.

Before sending those requests, v063a removes ONLY exact duplicate J2016 transport
queries shared by multiple pairs. This is safe because the Gaia DR3 source row is
the same regardless of which historical pair consumes it. Pair-specific epoch
propagation remains downstream and is not deduplicated.

v063a:
- no network
- no Gaia outcomes
- no pixels
- no detector
- no candidate state change
- prints the actual request reduction before any new network work

v064:
- consumes the globally deduplicated plan
- Gaia DR3 TAP only
- verified HTTPS through curl
- checkpoints every successful response as raw CSV + SHA256 metadata
- exact cached responses are reused on resume
- if an ordinary cell reaches MAXREC=50000, ONLY that transport cell is
  recursively quartered down to the already-frozen 0.03125-degree minimum
- HPM >=1700 mas/yr rescue queries remain separate
- no propagation, registration or candidate adjudication is performed yet

Recommended run
---------------

1. Audit the deduplication first:

  Expand-Archive ".\wide_census_gaia_acquisition_v063a_v064.zip" `
      -DestinationPath ".\wide_census_gaia_acquisition_v063a_v064" `
      -Force

  Copy-Item ".\wide_census_gaia_acquisition_v063a_v064\*" ".\tools\" -Force

  & ".\.venv\Scripts\python.exe" `
      ".\tools\audit_wide_census_gaia_query_dedup_v063a.py"

2. If v063a passes, run v064.

For a 20-request smoke test first:

  & ".\.venv\Scripts\python.exe" `
      ".\tools\run_wide_census_gaia_acquisition_v064.py" `
      --max-new 20

Then resume without a cap:

  & ".\.venv\Scripts\python.exe" `
      ".\tools\run_wide_census_gaia_acquisition_v064.py"

You may skip the smoke-test cap and run the uncapped command directly. The worker
is checkpointed and resume-safe.

Important
---------
A network/TAP failure is an operational blocker, never a scientific negative.
A MAXREC subdivision changes transport geometry only; it does not change any
science threshold.
