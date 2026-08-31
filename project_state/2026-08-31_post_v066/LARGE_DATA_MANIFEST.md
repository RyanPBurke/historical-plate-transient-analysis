# Large / local scientific data excluded from Git

The publication repository intentionally contains code, prospective
freezes, compact manifests, compact scientific summaries and provenance
records rather than the complete working data tree.

The original working tree remains authoritative for bulk products at
this checkpoint.

## Principal excluded products

### v056 detector candidates

Local path:
results\wide_census_detector_candidates_v056.csv

Approximate size:
912.5 MiB

Reason excluded:
Bulk derived detector catalogue.

Status:
Preserved in the working project. Not deleted or modified.

### v056 raw pair associations

Local path:
results\wide_census_pair_raw_matches_v056.csv

Approximate size:
143.7 MiB

Reason excluded:
Bulk derived association catalogue.

Status:
Preserved in the working project. Compact pair summary is included in
this repository checkpoint.

### v064 Gaia response cache

Reason excluded:
Very large resumable external-catalogue acquisition cache.

Status:
Preserved locally pending successful verification of downstream
registration products.

The compact v064 acquisition state, acquisition summary and acquisition
manifest are included in this checkpoint.

### v066 supplemental Gaia response cache

Compressed size at completion:
4.36 GiB

Reason excluded:
Very large resumable external-catalogue acquisition cache.

Status:
Preserved locally pending successful verification of downstream
registration products.

The compact v066 state, acquisition summary and response manifest are
included in this checkpoint.

## Other local-only trees

The following working-project areas are intentionally not copied wholesale
into the Git repository:

- results/
- work/
- cache/
- logs/
- .venv/
- .venv_dasch_geometry_v028/
- automation/backups/
- patch_backups/
- Python bytecode/cache directories

No source or bulk scientific data was deleted during repository
reconciliation.

Large derived products should ultimately be archived separately, e.g.
with a publication-data release/DOI, rather than embedded in ordinary Git
history.
