# Data provenance and authority order

## Authority hierarchy

1. Raw observatory/archive catalogue metadata and plate/logbook metadata.
2. Corrected/current tables under `current/`, when the correction is documented.
3. Preserved checkpoint tables under `checkpoints/`.
4. Legacy/pre-correction outputs under `legacy/`.
5. Narrative/recovered-summary state only where row-level records are unavailable.

## Primary metadata included

- **POSS-I VI/25** plate metadata: `source_data/poss1_plate_metadata.csv`
- **Harvard DASCH / GAVO** exposure metadata: `source_data/dasch_exposures_1951_1955.csv`
- **APPLAUSE DR4** exposure metadata: `source_data/applause_exposures_1951_1955.csv`
- historical pair matrix used for non-POSS rows: `source_data/archive_pair_overlap_candidates.csv`

Source URLs are retained inside the source tables where available.

## Persistent Library items discovered during export

See `current/LIBRARY_ARTIFACT_INVENTORY.csv` for exact persistent Library file IDs and roles. Equivalent copies of the major source tables and the 2026-08-17 bundle are included in this repository.

## Current corrections created at export time

`current/corrected_poss47_unique_ids_with_exposure_overlap.csv`

- maps every corrected POSS pair to a physical VI/25 `recno`;
- requires <=1 s corrected-time residual and <=0.01 deg coordinate residual for the mapping;
- adds start/end and actual exposure-overlap fields.

`current/nonposs27_with_exposure_overlap.csv`

- selects the exactly 27 non-POSS rows with midpoint separation <=5 min from the preserved pair matrix;
- these rows are unaffected by the POSS clock correction;
- adds actual exposure overlap and saved checkpoint status/notes.

`current/canonical_sub5_pairs_74.csv`

- harmonised union of the 47 + 27 current rows;
- intended as the entry point for the revised analysis.

## Known incomplete provenance

The late detailed morphology register after `DEF-041` is not present in the preserved bundle or recovered Library results. The only safe recoverable facts are the aggregate late state recorded in `current/CURRENT_STATE.json`. Any future recovery of DEF-042..DEF-106 should be imported as a separate provenance event and checksummed; it should not overwrite this snapshot.
