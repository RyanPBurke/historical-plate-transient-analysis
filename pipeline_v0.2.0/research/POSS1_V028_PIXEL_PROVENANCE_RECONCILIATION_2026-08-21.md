# v0.2.8 POSS-I pixel/FITS provenance reconciliation

Snapshot ID: `8dc070b9df3febaa5db3585408e1fe88e9b3b9d71d436ddba16a71081b066d0e`

## Frozen identity boundary

- unique POSS physical exposures: **40**
- validated / detector-eligible: **37**
- pixels unavailable: **3**
- identity failures: **0**

## Pair handoff

- temporal pairs: **74**
- POSS-involving rows: **47**
- non-POSS rows: **27**
- rows with positive actual exposure overlap: **74**
- explicit overlap_start_utc/end_utc recorded: **74/74**

## Pixel inventory

- pixel/FITS-like files scanned: **369**
- `EXACT_FROZEN_PIXEL_HASH_MATCH`: **54**
- `UNLINKED_PIXEL_ARTIFACT`: **315**

## Exposure dispositions

- `FROZEN_IDENTITY_PIXEL_AVAILABLE_NO_PROVEN_LEGACY_MATCH`: **27**
- `NO_REUSABLE_PIXEL_PRODUCT_LOCATED`: **10**
- `UNAVAILABLE_NO_DETECTOR`: **3**

## Frozen unavailable exposures

- `POSS-I:449:O:rec198` -> `XO197`
- `POSS-I:832:E:rec760` -> `XE760`
- `POSS-I:988:O:rec207` -> `XO206`

Archive/pixel unavailability remains part of the denominator and is not a scientific zero/non-detection.

No old detector disposition was automatically promoted.

Even an exact legacy pixel hash match remains only a reuse candidate until deterministic cutout and frozen-detector method provenance are verified.

No transient detector was run.
