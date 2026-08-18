# POSS-I transient evidence audit

**Status:** public-material audit complete; author-data-dependent tests identified  
**Cut-off:** 2026-08-16

## Executive position

The public evidence supports a narrower conclusion than the strongest papers
claim: many reported coordinates correspond to compact features on historical
plate scans that lack a simple modern Pan-STARRS match. It does not yet support
a calibrated population of astrophysical fast transients, nor the published
Earth-shadow, nuclear-test, UAP, or technosignature interpretations without
substantial additional selection-function and observing-coverage work.

Three distinct evidential layers must remain separate:

1. an image feature exists;
2. the feature passed a reproducible transient-selection procedure;
3. a population of selected features has a valid physical or temporal
   association.

Success at one layer does not validate the next.

## Finding 1 — catalogue lineage

The published 5,399-source Solano catalogue and the later 107,875-source sample
are not two releases of one frozen, fully documented pipeline. The latter was
constructed by revisiting the earlier unpublished 298,165-source population in
2025 and applying further exclusions. Its row-level provenance, code, and full
table are not public. The later author response also corrects the earlier
description of NeoWISE removal and acknowledges a potentially large
false-positive fraction.

Consequently, reproducing the 5,399 catalogue would not reproduce the input to
the 2025 Earth-shadow or nuclear/UAP papers.

## Finding 2 — Busko repository is auditable but not rerunnable

The public repository was frozen at commit
`dee4288ffb9a0bb9bae2af03409fc513c823e53d`. It has two commits on one day: one
bulk code/data commit and a README-only commit.

The final decision table contains:

- 294 reviewed rows;
- 283 marked for removal;
- 11 retained;
- a 96.2585% removal rate;
- one retained source (`40654930007722`) annotated
  `not picked up - edited manually into table`.

The repository cannot reproduce those 294 rows from raw data because:

- its active DR configuration contains seven sequences, while the result table
  contains 62 sequences; 56 result sequences are absent from the configuration;
- the retained set includes absent configurations such as sequences 11, 74,
  117, 117a, and 120;
- `images.json`, the master catalogue, plate scans, and intermediate FITS tables
  are absent;
- several telescope import modules referenced by settings are absent;
- the data root is an author-local `/Volumes/...` path.

The public materials therefore permit a static logic/output audit, but not an
end-to-end computational reproduction.

## Finding 3 — manuscript/code selection discrepancy

The coma paper says computer-vision shape filters were turned off for the
Doppel-Reflektor analysis. In the committed code, `exceeds_criteria()` rejects
on profile difference, elongation, circularity, shape defect, circle deviation,
and an aperture-photometry ratio, and the display/pipeline notebooks call this
function. The repository lacks the frozen intermediate inputs required to prove
which branch produced each published candidate, so this is presently a
documentation/code discrepancy rather than proof that the paper's eleven were
all filtered by the committed function.

The paper also describes selective whole-plate blinking and reverse-direction
runs on only some interesting plates. Those actions destroy a simple uniform
selection probability unless logged and incorporated into the analysis.

The committed selection graph contains at least 19 numeric gates before human
review, followed by catalogue checks, POSS-II inspection, subjective coma
assessment, selective blinking, selective reverse runs, and final table editing.
Because none of the per-object intermediate measurements are committed, no
numeric filter can presently be removed and rerun against the 294 candidates.

## Finding 4 — Hayes 2026 is important but preliminary

Hayes reports an independently detected 2,852,431-source catalogue and matches
3,450/5,399 Solano entries (63.9%). For the 1,949 unrecovered entries, the paper
reports 66 outside its footprint, roughly 1,010 detected but rejected by its PSF
filter, and roughly 870 not detected above 5 sigma.

This corroborates the existence and unmatched status of many Solano features,
but simultaneously reports material morphology disagreement and a large
non-recovery fraction.

The full-sky catalogue was produced using preliminary 5-sigma and broad PSF
settings, not the later calibrated 8-sigma settings used for the favourable
benchmark false-positive result. All cross-catalogue and temporal results use
that preliminary catalogue. The paper supplies no visible code or catalogue
repository in its arXiv HTML. Its numbers are therefore recorded as unverified
preprint claims pending materials.

Its coverage-adjusted negative-binomial analysis is null: IRR 1.03, 95% CI
0.89–1.18, p=0.71 for the ±1-day nuclear-test window. More importantly, it
demonstrates that the binary calendar-day statistic collapses to whether POSS-I
observed that day when every observed night has candidates. That strongly
supports treating observing opportunity as a central confound.

## Finding 5 — the public Bayesian reanalysis still lacks exposure data

The `euxoa/plates` repository is an independent Bayesian reanalysis by Janne
Sinkkonen, rather than the computational supplement for the Watters et al.
critical paper. It has meaningful development history and explicit Stan models,
but says that both source spreadsheets are not included.

Its conversion script left-joins the list of transient dates onto all 2,718
calendar dates and fills every absent transient count with zero. It does not
include a plate-count, exposure-time, scanned-area, or observed-night offset.
Therefore a zero can still mean either “observed with no selected feature” or
“not observed.” A latent temporal random walk cannot by itself resolve that
measurement/denominator ambiguity.

The principal model estimates seven nuclear and seven UAP lag coefficients and
reports nominal two-sided posterior tail values. Three fall below 0.05, including
nuclear lag -1 at 0.037. No family-level multiplicity adjustment or preregistered
single lag is described in the repository. These results are exploratory until
the observation schedule and multiple lag search are handled explicitly.

## Finding 6 — the published contingency tables reproduce, and expose the confound

Independent recalculation from the cell counts printed by Watters et al. gives:

| Comparison | Relative risk | Fisher two-sided p | Pearson p |
|---|---:|---:|---:|
| 107,875 sample over all 2,718 calendar days | 1.447 | 0.0110 | 0.0084 |
| 5,399 sample over all 2,718 calendar days | 1.450 | 0.0153 | 0.0104 |
| 5,399 sample over 312 relevant observation days | 1.071 | 0.1439 | 0.0995 |
| Observation schedule versus nuclear window | 1.367 | 0.0307 | 0.0282 |

This confirms the arithmetic behind both sides of the dispute. Treating all
unobserved dates as genuine zero-detection dates creates the large association.
Restricting to relevant observation days reduces it sharply, while the telescope
schedule itself has almost the same association with the nuclear window as the
original claimed transient effect.

Watters et al. quote p=0.1 alongside a Wald relative-risk interval of 1.02–1.13
for the sparse 312-day table. We reproduce both approximately, but they arise
from different asymptotic procedures and appear contradictory. Exact Fisher
testing gives p=0.144 two-sided (0.077 directional). The exact result reinforces
the non-significant conclusion but the paper should not present the Wald interval
as though it were methodologically interchangeable with that p-value.

## Finding 7 — the live 5,399 catalogue is complete but provenance-poor

The complete current SVO table has been downloaded and checksummed. It contains
5,399 unique coordinate pairs. There are no pairs within 5 arcsec, consistent
with an effective positional deduplication/matching floor; four pairs lie between
5 and 10 arcsec.

The sky coverage is overwhelmingly northern: 5,323 entries are north of the
equator and only 76 south (98.59% northern). This directly confirms that the
catalogue cannot be treated as an approximately uniform full-sky population.

Even at maximum query verbosity the machine-readable table exposes only RA,
declination, distance from the query centre, and empty image-link fields. It
does not expose:

- plate identifier or observation timestamp;
- original SExtractor detection identifier;
- tile centre or overlapping-tile alternatives;
- FWHM, ellipticity, `SPREAD_MODEL`, flags, or PSF model;
- rejection stages or modern-catalogue match history.

The separate HTML interface provides POSS-I and Pan-STARRS thumbnails for all
rows, and a 5,399-row image index has now been extracted. These thumbnails are
useful for visual triage but contain display overlays and resampling, and at
least one inspected preview renders the plate information as a tiny central
patch. They are not suitable for quantitative PSF/FWHM reproduction. That work
requires raw DSS cutouts at the published coordinates.

## Finding 8 — the current DSS timestamp looks ISO-compliant but is not

Raw FITS cutouts reveal a potentially consequential archive trap. In the first
127-source sample, 46 `DATE-OBS` values are syntactically impossible, including
times such as `08:93:00`, `10:88:00`, and `03:62:00`.

Comparison with the older DSS header for plate E1611 resolves the encoding. The
current header says `1957-04-28T05:57:00`; the historical header reports UT
`05:34:00`. Interpreting `05:57` as 5.57 decimal hours gives 05:34:12. Thus the
current generator has placed decimal-hour hundredths into an ISO-looking minute
field.

This affects not only the 36% of sampled rows whose minute field exceeds 59.
Every timestamp is potentially misread: a superficially valid `05:30` means
5.30 hours (05:18), not 05:30. Any Earth-shadow calculation that parses the
current `DATE-OBS` literally will be wrong by up to approximately 24 minutes.
The working catalogue now retains both the raw value and a decimal-hour-corrected
value; exposure start versus midpoint remains a separate uncertainty.

## Finding 9 — morphology result fails a nine-setting sensitivity grid

A deterministic random sample of 50 catalogue rows was measured on raw 5-arcmin
DSS cutouts using a deliberately simple, fully transparent connected-
component and moment pipeline. Each target was compared with same-field sources
of similar peak brightness. Results were repeated across a 3-by-3 grid of
detection thresholds (3, 5, and 8 sigma) and comparison tolerances (±0.1, ±0.25,
and ±0.5 magnitudes).

Depending on settings, 17–44 random targets had at least three usable comparison
sources and a centroid within three pixels. Across all nine settings:

- moment-FWHM target/control median ratios ranged from 0.93 to 1.02;
- equal-area half-maximum ratios were 1.00;
- ellipticity ratios ranged from 0.84 to 1.28;
- no two-sided Wilcoxon or sign test was significant for FWHM or ellipticity;
- moment-FWHM Wilcoxon p-values ranged from 0.053 to 0.84;
- ellipticity Wilcoxon p-values ranged from 0.077 to 0.88.

At the closest ±0.1-mag comparison, the moment-FWHM ratio was 1.023 (Wilcoxon
p=0.64); at ±0.5 mag it was 0.93 (p=0.18). Thus this independent diagnostic does
not show the catalogue population to be systematically narrower or rounder than
local sources.

This is not a replacement for SExtractor/PSFEx and does not prove morphological
equivalence. It is a robustness warning: the claimed morphology is not obvious
under a reasonable independent measurement, the direction changes with analyst
settings, and the conclusion does not become significant at the paper's 5-sigma
threshold or the independently calibrated 8-sigma threshold used by Hayes.

## Finding 10 — overlap is an unreported repeated-opportunity selection mechanism

Solano et al. tessellated the sky into circular 30-arcmin-radius regions, applied
source and morphology filters to each region, then concatenated surviving lists
and removed duplicates because the tessellated images overlap. This ordering
means a marginal source in more than one cutout can enter the catalogue if it
passes in any cutout. Background, segmentation, edge distance, and local median
morphology can differ between cutouts, so duplicate removal does not undo the
extra opportunity to pass.

The tile grid and pre-deduplication detections are unavailable, so the actual
effect cannot be estimated. A generic sensitivity calculation shows its possible
scale: if one cutout has a 5% chance of passing a marginal artefact, two, three,
and four independent opportunities increase retention to 9.75%, 14.26%, and
18.55%. Independence is only an illustration, not an assumption about the real
tiles. The methodological requirement is to publish multiplicity and either use
one predetermined extraction per position or model repeated measurements.

## Finding 11 — the calendar association decomposes exactly into schedule and detection

For the red-only 5,399 catalogue, the published calendar-day relative risk of
1.4498 is exactly the product of:

- observation probability RR: 1.3531 (52/350 versus 260/2368);
- candidate-positive given observation RR: 1.0714 (51/52 versus 238/260).

Thus `1.3531 × 1.0714 = 1.4498`. The large calendar statistic is primarily an
observing-opportunity statistic. The smaller conditional component is not
significant by two-sided Fisher testing (p=0.1439). This algebraic decomposition
is stronger than a qualitative warning about confounding: it identifies exactly
where the published effect size comes from.

## Finding 12 — the 2026 ML paper does not provide an independent gold standard

Bruehl et al. (published 10 August 2026) train an ensemble on 250 deliberately
chosen exemplars: 134 labelled likely real and 116 labelled plate defects. The
primary labeler is Villarroel, a co-discoverer and co-author. A second reviewer
was trained by the primary reviewer, reviewed only a subset, and resolved
disagreements by discussion; no independent blinded adjudication or inter-rater
reliability statistic is reported.

This can measure agreement with the authors' visual definition, but it cannot by
itself validate celestial reality. Other important limitations are:

- the selected exemplar prevalence is not a population prevalence;
- isotonic calibration collapsed, so uncalibrated raw ensemble outputs were used
  while repeatedly described as probabilities of being real;
- only 20% of the deployed catalogue exceeded a raw score of 0.66 and only the
  top 10% approached/exceeded 0.80;
- the model includes six plate-aggregate variables, yet only ordinary five-fold
  cross-validation is described; no plate-grouped split is documented;
- plate quality alone differs extremely between labels (GOOD: 42.5% of “real”
  versus 91.4% of “artifact”), making leakage/generalization across plates a
  central concern;
- the final script is cited at `dca-doherty/VASCO-ML`, but the repository was not
  publicly retrievable during this audit.

Because the deployment score contains plate-level quality information, showing
that high-score events vary by observing date or reconstructed plate geometry is
not automatically an external validation; the same plate/date structure can
affect both the score and the claimed downstream association.

## Finding 13 — the revised shadow null is plate-aware only in a limited geometric sense

The 2026 ML paper improves the geometry to a 3D topocentric penumbra and reports
433/62,600 simulated positions (0.692%) in shadow. However, “plates” are inferred
by clustering transient coordinates per date with a 15-degree threshold rather
than taken from released plate IDs. One hundred positions are then drawn
uniformly within each inferred field, without reproducing the within-plate
detection mask, overlap multiplicity, vignetting, star density, catalogue-match
losses, morphology acceptance, or spatially varying contamination.

The 0.692% control is also a Monte Carlo estimate, not an exact known probability:
its binomial simulation standard error is about 0.033 percentage points (roughly
4.8% relative). Subsequent binomial tests treat it as fixed. More importantly,
the paper does not state how the archive timestamp encoding or exposure
start-versus-midpoint uncertainty was handled. A geometric upgrade does not
replace an empirical selection-function null.

## Finding 14 — alignments require the full search trial count

An all-trials coordinate scan of the public 5,399-source table illustrates the
look-elsewhere problem. Within a 10-arcmin neighbourhood there are 428 neighbour-
pair angles around 131 possible anchors; the best apparent collinearity is 0.168
degrees, but an isotropic calculation gives a 90.8% chance of at least one result
within 0.5 degrees after 428 trials. At 30 arcmin there are 6,455 tested angles
and the best is 0.020 degrees; finding at least one within 0.1 degrees is then
expected with probability 99.92% under the simple isotropic benchmark.

This is not a null model for the private 107,875 catalogue—the public catalogue
is spatially nonuniform and the trials are dependent. It demonstrates why a
visually selected alignment cannot be assigned the single-triplet probability.
A valid test must freeze the grouping radius, alignment metric, minimum/maximum
group size, all scanned plates, and the spatially structured null before looking
at the most striking group.

## Finding 15 — the UAP analysis remains non-reproducible and exposure-free

The 2025 article says its final SPSS dataset is available only on reasonable
request; no supplementary data file is posted. The reported UAP models therefore
cannot be recomputed from the article. Methodologically, the same exposure
problem remains: the negative-binomial daily transient-count model includes no
plate count, surveyed area, limiting depth, weather, or observation-time offset.

The paper's first UAP analysis restricts the correlation to the 310 dates with
at least one selected transient and says this “eliminates” bias from zeros.
Conditioning on a positive outcome does not create missing exposure information
and can itself induce selection bias. The full-sample model then treats daily
counts as the outcome but does not document temporal autocorrelation, seasonal
trends, changing UAP reporting intensity, or catalogue coverage. UFOCAT has at
least one report on 89.3% of all study dates, so raw report count is better
understood as a historically varying reporting process than a calibrated measure
of physical UAP incidence. The reported association is consequently exploratory,
not evidence that validates the astronomical candidate population.

## Current blockers

- exact Solano SExtractor and PSFEx configurations;
- Solano tile-level pre-deduplication detections;
- complete 107,875-source table and construction flags;
- 2026 ML training rows, labels, plate groups, out-of-fold scores, deployed
  scores, and publicly accessible cited repository;
- frozen Busko input catalogue, scans, intermediate tables, and complete
  per-sequence configuration;
- Hayes code, catalogue, patch summary, and test-date file.

## Remaining highest-value work

1. Obtain the 107,875 row-level catalogue and frozen plate/time metadata; without
   it, exact shadow, nuclear, UAP, and ML-score reproduction is impossible.
2. Re-run ML validation with plate-grouped folds, independent blinded labels,
   known-star/known-defect controls, and calibrated held-out probabilities.
3. Replace uniform within-field shadow controls with injection/recovery or an
   empirical rotation/permutation that preserves every plate's selection mask.
4. Fit nightly count models with plate area/limiting depth as exposure, calendar
   and weather controls, and predeclared temporal windows.
5. Test alignments with a frozen all-search statistic on simulated or rotated
   catalogues that preserve plate clustering and detector artefacts.
