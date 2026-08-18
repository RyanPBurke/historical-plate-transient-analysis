# Sub-five-minute pair validation

## Outcome

- Input candidates: **32**
- Exposure intervals actually overlap: **32**
- Distinct physical sites resolved directly from metadata: **27**
- POSS-I circular-screen candidates: **5**
- POSS-I/DASCH pairs with confirmed public WCS cutout coverage: **3**
- Rejected by direct WCS coverage query: **2**
- DASCH-site resolution still required: **5**

The original shortlist used midpoint separation. This validation adds exposure
start/end intervals, approximate circle-intersection area, smaller-field overlap
fraction, timestamp provenance, and a reproducible priority score.

The direct pixel-retrieval gate is decisive for the five POSS-I/DASCH rows:
ranks 1, 3, and 4 returned paired 20-arcmin FITS cutouts; ranks 2 and 5 returned
HTTP 422 from the DASCH WCS service. Inspection of their plate solutions shows
large differences between catalog and WCS centers, so those two are rejected as
spatial false positives rather than treated as missing data.

## Pixel pilot

`pilot_pixel_summary.csv` applies one symmetric, frozen local-peak rule to the
three retrieved pairs: 8-pixel background smoothing, both polarities, 4-sigma
threshold, 7-pixel local-maximum window, 30-pixel edge mask, and 10-arcsec sky
crossmatch. It yields 4,730 unmatched screening peaks. This high number is a
diagnostic of differing depth/passband/PSF and photographic artifacts—not a
transient count. The full list is retained for reproducibility, but no peak is
promoted without PSF-aware calibration, artifact rejection, negative controls,
and injection/recovery.

## Promotion rule

`validated_sub5_pairs.csv` is ranked, but no row is yet a confirmed transient
pair. Promotion requires:

1. original logbook/jacket verification of time and observing station;
2. true WCS footprint intersection rather than the circular approximation;
3. selection of predetermined sky positions in the common footprint;
4. pixel retrieval and identical frozen detection on both plates;
5. plate-preserving negative controls and injection/recovery.

## Ranking

- 40 points: exposure intervals overlap.
- 25 points: gap no more than five minutes when intervals do not overlap.
- 25 points: at least 25% of the smaller approximate footprint overlaps.
- 20 points: one member is POSS-I.
- 15 points: metadata directly resolve distinct physical sites.

The score is triage only and has no statistical interpretation. Direct WCS
validation overrides the score where they disagree.
