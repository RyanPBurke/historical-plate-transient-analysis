# Transients launch and plate-overlap bundle

This bundle supports a plate-aware replication of the Transients/Villarroel
analysis for 1951–1955. It keeps three questions separate:

1. Was a rocket launch recorded on the observing date?
2. Did independent observatories expose overlapping sky at sufficiently close
   times?
3. Could a launch trajectory actually have crossed the plate footprint from
   the observing site?

The first two can be screened with the included catalogues. The third requires
trajectory/ephemeris reconstruction and must not be inferred from a date match.

## Contents

- `data/launches_1951_1955.csv` — event-level launch catalogue.
- `data/launch_site_registry.csv` — approximate coordinates and confidence for
  recurring launch sites.
- `data/poss1_plate_metadata.csv` — POSS-I catalogue VI/25 where retrieval was
  available.
- `data/applause_exposures_1951_1955.csv` — APPLAUSE DR4 exposure metadata.
- `data/dasch_exposures_1951_1955.csv` — public DASCH/GAVO exposure metadata.
- `results/archive_pair_overlap_candidates.csv` — cross-observatory temporal
  and footprint candidates within 30 minutes.
- `results/archive_pair_same_night_candidates.csv` — broader six-hour
  cross-observatory candidates.
- `results/archive_triplet_overlap_candidates.csv` — three-site candidates in
  which every pair overlaps spatially within the six-hour discovery window.
- `results/launch_plate_date_candidates.csv` — deliberately broad date-window
  screening table; not evidence of causal association.
- `results/validated_sub5_pairs.csv` — ranked metadata validation of the
  sub-five-minute queue, including actual exposure-interval overlap.
- `results/dasch_priority_plate_details.csv` — resolved telescope, observing
  station and WCS availability for DASCH plates in that queue.
- `scripts/build_catalogues.py` — reproducible public-source retrieval.
- `scripts/build_overlap_matrix.py` — deterministic overlap calculation.
- `scripts/validate_priority_pairs.py` — interval/footprint validation and
  ranking of the strictest pair queue.
- `scripts/fetch_priority_cutouts.py` — deterministic public retrieval of
  paired 20-arcmin FITS cutouts for the top POSS-I/DASCH queue.
- `results/priority_cutout_manifest.csv` — cutout coordinates, selection rule,
  local files and retrieval status.
- `cutouts/` — three matched DASCH/POSS 20-arcmin FITS pairs; two additional
  circular-screen candidates were rejected by the DASCH WCS service.
- `scripts/pilot_pixel_qa.py` — frozen symmetric local-peak and sky-crossmatch
  pilot for the retrieved tiles.
- `results/pilot_pixel_summary.csv` and `results/pilot_unmatched_peaks.csv` —
  screening output; unmatched peaks are explicitly not claimed as transients.
- `SOURCES_AND_METHOD.md` — provenance, assumptions, limitations, and next
  validation gates.
- `SUMMARY.md` — counts, principal findings, and ranked follow-up queues.
- `PAIR_VALIDATION_REPORT.md` — interpretation and promotion gates for the
  sub-five-minute queue.

## Rebuild

```bash
python scripts/build_catalogues.py
python scripts/build_overlap_matrix.py
```

The overlap script uses a 24-hour launch/plate screening window, a 30-minute
strict pair window, and a six-hour same-night window for pair/triplet discovery.
The six-hour output is not labelled simultaneous. Tight scientific tests should
use actual exposure intervals and reconstructed trajectories.

## Interpretation guardrails

- All 1951–1955 launches are suborbital. A same-date impact/decay entry does
  not mean the object was visible from an observatory.
- Missing launch times are retained as missing, never imputed.
- Date-only matches are labelled `date_screen_only`.
- Circular fields of view are approximations unless a true footprint polygon
  is supplied.
- A cross-observatory candidate is not a confirmed transient; pixels must be
  reprocessed with the same frozen detector and plate-preserving null model.
