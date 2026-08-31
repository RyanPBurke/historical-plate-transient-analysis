# POSS-I timestamp and physical-plate identity convention

Frozen before prospective POSS-I production analysis. This note documents archive semantics only; it does not alter the frozen detector or candidate-selection thresholds.

## VI/25 time basis
CDS VizieR VI/25 records the observing night as an initial and final local calendar date. `ObsE` and `ObsO` are exposure start times in Pacific Standard Time (UTC-8). The actual local date is inferred from which side of midnight the start time falls; converting to UTC can therefore roll into the following UTC date.

For POSS 413 / MLP 297 / VizieR recno 297:
- observing night: 1951-11-04 to 1951-11-05
- E start: 23:00 PST; exposure 60 min -> 1951-11-05 07:00 UTC
- O start: 22:45 PST; exposure 10 min -> 1951-11-05 06:45 UTC

## DSS Plate Finder legacy epoch display
The STScI DSS Plate Finder returns the same physical pair as:
- `06S2`, region `XE296`, POSS-I E, 60 min, displayed epoch `1951-11-04 07:00:00`
- `A33Z`, region `XO296`, POSS-I O, 10 min, displayed epoch `1951-11-04 06:75:00`

The impossible sexagesimal value `06:75` demonstrates that the time component is legacy decimal-hour hundredths rendered with a colon: 6.75 h = 06:45. For physical identity matching we therefore compare:
1. the Plate Finder date to the VI/25 *initial observing-night date*;
2. the Plate Finder legacy decimal-hour clock to the VI/25 PST time converted to UTC, modulo 24 h;
3. survey/band and exposure duration;
4. forced `plate_id` FITS `REGION` where present.

The scientific queue retains normalized UTC exposure intervals. Plate Finder's legacy display is preserved raw and never substituted for the normalized scientific timestamp.
