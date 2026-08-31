WIDE CENSUS — GAIA REGISTRATION REFERENCE-ACQUISITION PREFLIGHT v063
======================================================================

Why this exists
---------------
v062 showed a very strong population-level close-match excess. The next frozen
science stage is common-Gaia local astrometric registration.

We must NOT implement that as one Gaia network request per raw match:
  512,788 <=10" raw matches
  185,532 <=3" raw matches

v063 therefore freezes a scalable, outcome-independent acquisition strategy
BEFORE any new Gaia result is read.

No network is used by v063.

Science method inherited unchanged
----------------------------------
- Gaia DR3, epoch-propagated
- 15" reference acquisition radius
- 30" target/science exclusion
- primary common same-Gaia references
- 5'/10'/20'/30' windows
- >=5 refs
- smallest qualifying window
- translation-only median
- no clipping
- no higher-order model
- sparse fallback only if primary <5 refs at 30'
- sparse >=3 references/archive, diagnostic only

Transport implementation frozen by v063
----------------------------------------
Ordinary Gaia:
- all <=10" raw-match midpoints are placed in fixed global 0.25-degree cells;
- one cone query per occupied cell;
- cone radius covers the farthest cell corner + 120";
- if MAXREC=50000 is hit, recursively quarter that transport cell only;
- returned sources are deduplicated by Gaia source_id offline.

High proper motion:
- one pair-level pm>=1700 mas/yr query covering all raw-match midpoints +900".

Each pair's Gaia propagation epoch is the midpoint of its authoritative physical
exposure-overlap interval.

This changes no science thresholds. Query tiling and MAXREC subdivision are
transport/cache mechanics only.

Run
---
  Expand-Archive ".\wide_census_gaia_registration_preflight_v063.zip" `
      -DestinationPath ".\wide_census_gaia_registration_preflight_v063" `
      -Force

  Copy-Item ".\wide_census_gaia_registration_preflight_v063\*" ".\tools\" -Force

  & ".\.venv\Scripts\python.exe" `
      ".\tools\preflight_wide_census_gaia_registration_v063.py"
