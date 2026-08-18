# Research bundle summary

## Corrected inventories

| Dataset | Retrieved rows | Usable normalized exposures |
|---|---:|---:|
| Launches, 1951–1955 | 456 | 389 individually represented; 67 annual-series members lack individual dates |
| APPLAUSE DR4 | 14,018 | calibrated `ut_start`/`ut_end` used, not recorded local/original time |
| Harvard DASCH/GAVO | 17,515 | usable pointing and timing rows included |
| POSS-I VI/25 | 1,039 plate records | E and O exposures normalized separately where timing is present |
| Combined normalized exposure set | — | 16,796 |

## Corrected overlap results

- **236** cross-archive spatial candidates have exposure midpoints within 30 minutes.
- **32** are within five minutes and **73** within ten minutes.
- **34** strict candidates involve POSS-I.
- **3,381** cross-archive candidates fall within the broader six-hour same-night window.
- **240** same-night triplets pass pairwise approximate spatial overlap; none is a demonstrated strict simultaneous three-site transient.
- The launch/date screen contains **9,173** rows, **310** individually dated launches, and **6,005** exposures. These are date screens only.

These counts supersede the preliminary figures based on APPLAUSE's
`time_orig_start`. The corrected build uses the archive's calibrated UTC fields.

## Sub-five-minute validation

All 32 exposure intervals overlap. Historical DASCH metadata resolve distinct
physical sites for 27; five retain site uncertainty. The circular-footprint
screen initially promoted five POSS-I/DASCH pairs. Direct DASCH WCS cutout
queries confirm common 20-arcmin coverage for **three** and reject **two** as
catalog-pointing/footprint false positives.

The three retrieved pilot pairs are ranks 1, 3, and 4 in the validation table.
A symmetric 4-sigma local-peak screen found many unmatched single-image peaks
(4,730 total) because plate depth, passband, PSF, scan grain, and defects differ
strongly. They are **not transient detections**. A calibrated completeness/null
model and artifact vetting are required before interpreting multiplicity.

## Recommended next gates

1. Verify the three surviving pairs against original jackets/logbooks.
2. Perform PSF-aware photometry and injection/recovery separately by plate.
3. Build plate-preserving negative controls matched in archive, series, depth,
   sky density, and epoch.
4. Vet unmatched peaks in both polarities and reject scratches, emulsion flaws,
   saturation, diffraction structure, and astrometric edge failures.
5. Reconstruct launch trajectories only for candidates that survive the pixel
   and null-model gates; a launch-date match alone is not causal evidence.
