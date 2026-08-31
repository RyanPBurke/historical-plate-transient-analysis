v066 8-WORKER TRANSPORT CEILING PATCH
======================================

This patch changes ONLY the permitted number of in-flight worker threads:
  before: maximum 4
  after:  maximum 8

Default remains 2.

The SINGLE global request-start limiter remains 0.75 seconds. Thus even with
8 workers, new requests cannot start faster than ~1.333/s (~4800/hour).
Increasing workers only overlaps TAP/server latency.

UNCHANGED:
- query geometry and v065/v002 coverage contract
- retries/backoff
- MAXREC behavior and subdivision
- gzip cache and SHA verification
- 12 GiB low-disk abort
- no registration/adjudication

Install after Ctrl+C:

  Expand-Archive ".\v066_workers8_patch.zip" `
      -DestinationPath ".\v066_workers8_patch" `
      -Force

  Copy-Item ".\v066_workers8_patch\*" ".\tools\" -Force

  & ".\.venv\Scripts\python.exe" ".\tools\patch_v066_workers8.py"

Resume:

  & ".\.venv\Scripts\python.exe" `
      ".\tools\run_wide_census_gaia_supplemental_acquisition_v066.py" `
      --workers 8

If retry/throttling frequency clearly worsens, Ctrl+C and resume at --workers 4.
All completed cached work remains reusable.

Expected current (4-worker patch) normalized SHA:
66b41f6dfcef2db8ba5ffc70490e1b809aa04233a6eaa0c003f0b12403518275

Patched normalized SHA:
8b4a036eb18514ed2c0e4fd30089a1e3a78aa49a362953fb3e40396da1b28704
