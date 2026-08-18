# Historical Plate Transient Research — reproducibility snapshot

Snapshot assembled **2026-08-18** before changing from a same-RA cross-observatory-only search to a three-branch methodology:

1. distant/common-sky independent-observatory coincidences;
2. independent single-observatory transient-population replication;
3. parallax-aware near-Earth simultaneous matching.

See **`ANALYSIS_PLAN.md`** before running any new analysis.

## Canonical current state

- corrected ≤5-minute pair set: **74**
- POSS-involving: **47**
- non-POSS: **27**
- all 74 have positive actual exposure overlap
- actual simultaneous exposure: **0.333–58 min**, median **12 min**
- defensible astrophysical survivors at snapshot: **0**
- recovered late morphology count: **106 cases reported**, but only **DEF-001..DEF-041 are preserved row-by-row** in the available bundle; DEF-042..DEF-106 must not be fabricated from summary memory
- rank 25 requires a clean rerun after discovery that legacy `POSS-I:1023:O` identifies two physical exposures
- rank 40 tile 1 is closed with zero survivors; tile 2 has detector counts saved but its strict crossmatch is not yet dispositioned

## Start here

- `ANALYSIS_PLAN.md` — frozen revised protocol
- `current/canonical_sub5_pairs_74.csv` — canonical current pair table with real exposure-overlap intervals
- `current/corrected_poss47_unique_ids_with_exposure_overlap.csv` — corrected 47 POSS-involving rows
- `current/nonposs27_with_exposure_overlap.csv` — unaffected 27 non-POSS rows
- `current/CURRENT_STATE.json` — machine-readable state
- `current/KNOWN_REMAINING_WORK.csv` — currently recoverable unfinished work
- `current/RANK25_IDENTITY_AUDIT.md` — duplicate-ID failure and correction
- `current/rank40_live_checkpoint.json` — latest rank-40 state
- `current/VALIDATION.txt` — invariants checked when export was built

## Directory policy

### `current/`
Use this for new work. IDs/times here supersede ambiguous legacy versions.

### `checkpoints/`
Preserved authoritative checkpoints from the 2026-08-17 continuation bundle. Some status rows are stale relative to the recovered late state; they are retained for auditability.

### `source_data/`
Raw/normalized archive metadata used by the preserved pipeline (DASCH, APPLAUSE, POSS VI/25, pair candidates).

### `scripts/`
Preserved pipeline code. **Important:** the old `build_overlap_matrix.py` contains the pre-fix POSS timing/ID logic and must not be used to regenerate authoritative POSS pairs without the corrections described in this repository.

### `legacy/`
Pre-correction products, reports, early FITS cutouts and other useful forensic material. Do not promote rows from here into current results without identity/time revalidation.

### `context_paper_audit/`
Existing Villarroel/VASCO methodology-audit context, including the claim matrix and audit report.

### `archive_original/`
Untouched 2026-08-17 handoff ZIP for provenance.

## Critical corrections

### POSS clock basis
VI/25 times are Palomar local/PST. After-midnight clock values belong to the next local civil date; then add 8 h to obtain UTC.

### POSS plate-number collisions
`POSS:<number>:<band>` is not globally unique. This export found **118 duplicated legacy IDs** in the full VI/25 exposure set. New IDs include `recno`.

### Rank 25
The two O-band plate-1023 records are physically different observations. Rank 23 maps to rec675; rank 25 maps to rec799. Preserved `DEF-011`, despite its rank-25 label, lies on the rank-23 field and is not valid rank-25 contemporaneous evidence.

### DSS historical headers
DSS `DATE-OBS` must not override VI/25 timing. Known decimal-hour/header-date formatting behaviour can make the DSS timestamp look like a different civil date/time.

## Frozen detector

Preserved implementation: `scripts/pilot_pixel_qa.py`

- Gaussian background sigma: 8 px
- both polarities via absolute residual local maxima
- 4 robust-sigma threshold
- MAD sigma estimator
- 7 px local maximum window
- 30 px edge mask
- 10 arcsec original match radius
- 3 arcsec stricter crowded/registered diagnostic

Do not silently change these parameters.

## Data loss / provenance caveat

The available persistent handoff contains a 41-row morphology register. Later work was recovered at summary level as having reached 106 cases, but the detailed DEF-042..DEF-106 rows are not present in the recovered bundle/Library search. This repository records that gap explicitly rather than reconstructing fictional row-level data.

## GitHub

This snapshot is Git-ready. The ChatGPT session that built it had Git installed but no authenticated GitHub connector or `gh` client, so it could not push directly to a remote repository. See `GITHUB_UPLOAD.md`.
