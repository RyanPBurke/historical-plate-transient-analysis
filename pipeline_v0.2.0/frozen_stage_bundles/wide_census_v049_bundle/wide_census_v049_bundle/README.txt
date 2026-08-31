WIDE CENSUS PHYSICAL TIMING / PHYSICAL-PLATE IDENTITY v049

This installer makes no network requests, reads no science pixels, reruns no detector,
and mutates no candidate state.

Copy the extracted bundle contents into project\tools\:
  Copy-Item ".\wide_census_v049_bundle\*" ".\tools\" -Force

Install:
  & ".\.venv\Scripts\python.exe" ".\tools\upgrade_transient_automation_v049_wide_timing.py"

Recommended resumable execution:
  & ".\.venv\Scripts\python.exe" -m automation.runner run-until-blocked --allow-network

Or one 12-remote-identity checkpoint batch at a time:
  & ".\.venv\Scripts\python.exe" -m automation.runner run-next --allow-network

Expected unique source identities in the 111-row <=15-minute queue:
  APPLAUSE exposures: 96 (pinned local DR4 metadata)
  POSS exposures:     18 (VI/25 authoritative timing + SkyView identity metadata)
  DASCH plates:       42 (DR7 exposure metadata)

Important timing policy:
  - POSS start time is derived by the existing authoritative vi25_start_utc() helper.
  - SkyView HHH DATE-OBS clock is NOT used as a POSS timing authority; HHH is identity/date-only.
  - APPLAUSE uses DR4 UT start/end and plate_id for physical-plate identity.
  - DASCH selects the specific plate exposure by pre-existing catalogue midpoint/duration,
    not by whichever exposure would maximize pair overlap.

No pair becomes science-eligible in v049. Timing survivors next require true-footprint
intersection and remaining physical-provenance validation.

Dashboard update after install:
  Copy-Item ".\tools\transient_dashboard_v049.py" ".\tools\transient_dashboard.py" -Force
  restart the dashboard.
