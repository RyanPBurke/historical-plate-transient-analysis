# Historical Photographic-Plate Transient Analysis Plan

**Protocol freeze date:** 2026-08-18  
**Primary aim:** test whether historical photographic-plate “transients” represent genuine incident-light events, and separately test whether a population is compatible with nearby reflective objects (including GEO/high-Earth-orbit glints), without conflating those hypotheses.

## 1. Research questions

The project now has three distinct analysis branches. They share the same plate identity, timing, WCS, detector, morphology and catalogue controls, but answer different questions.

### Branch A — distant/common-sky transient test
Ask whether two geographically independent observatories recorded a point-like source at essentially the same celestial position during genuinely overlapping exposures.

This is appropriate for astronomical or sufficiently distant sources. It is **not** the primary test of a GEO-range object because parallax between distant observing sites can be degrees rather than arcseconds.

### Branch B — independent single-observatory transient-population replication
At each archive/observatory independently, identify sources that are present on one exposure but absent from suitably deep neighbouring exposures and modern/static catalogues. Then compare the resulting populations between observatories.

This is the principal replication test of the Villarroel/VASCO-style phenomenon. The same physical transient does **not** need to be seen by two observatories for this branch.

### Branch C — parallax-aware near-Earth simultaneous test
For a credible single-observatory transient recorded during an exposure that overlaps another observatory, do **not** demand the same RA/Dec at the second site. Instead, calculate the second observer's expected sky locus as a function of event time and range, then search along that locus for a contemporaneous uncatalogued point source.

A positive match can constrain/triangulate range. A non-detection at the second observatory does **not** falsify a specular-glint hypothesis because reflection is directional.

---

## 2. Immutable data-integrity gates

Before analysing pixels:

1. **Physical plate identity**
   - Use unique identifiers tied to the physical catalogue record.
   - POSS-I IDs must include VI/25 `recno`: `POSS-I:<POSS>:<band>:rec<recno>`.
   - Legacy `{POSS}:{band}` identifiers are non-authoritative because 118 such identifiers are duplicated globally.

2. **Authoritative time basis**
   - POSS-I VI/25 clock times are Palomar local/PST.
   - After-midnight local clocks belong to the following local civil date before conversion to UTC.
   - Convert PST to UTC by +8 h after local-date rollover.
   - DSS `DATE-OBS` is not authoritative for historical POSS timing; retain it only as scan/header metadata.
   - Preserve raw and corrected timestamps side-by-side.

3. **Exposure interval**
   - Record start, end, duration and midpoint for every exposure.
   - For a pair, calculate actual simultaneous exposure:

     `overlap = max(0, min(endA,endB) - max(startA,startB))`

   - Record overlap minutes and overlap fraction of each exposure.
   - Midpoint-separation gates remain ≤5, then ≤10, then ≤15 minutes for simultaneous branches, but actual overlap is the physically relevant timing quantity.

4. **Historical observing site**
   - Resolve the physical telescope/station for every plate used in parallax work.
   - `Harvard DASCH` is an archive/holding label and cannot automatically be treated as Cambridge, Massachusetts.
   - Record site latitude, longitude, elevation, source and confidence.
   - No Branch-C geometry is permitted with an unresolved observing site.

5. **True WCS / footprint**
   - Use the solved plate footprint or live cutout coverage, not circular-FOV overlap alone.
   - Record plate/scan label, WCS solution identifier and retrieval provenance.

---

## 3. Frozen pixel detector

Unless an explicitly versioned protocol revision is created, use the existing detector unchanged:

- local Gaussian background sigma: **8 px**
- residual polarity: **both**, implemented through absolute residual local maxima
- threshold: **4 robust-sigma**
- sigma estimator: **MAD-based robust sigma**
- local-maximum window: **7 px**
- edge mask: **30 px**
- historical broad cross-observatory radius: **10 arcsec**
- stricter registered diagnostic radius: **3 arcsec**

Do not silently retune the 4-sigma threshold in response to candidate appearance.

The old `pilot_unmatched_peaks.csv` is a plate-texture diagnostic, not a transient catalogue.

---

## 4. Plate-level preprocessing and quality masks

For every analysed plate/cutout:

1. Verify plate identity and checksum.
2. Verify WCS and target footprint.
3. Measure local background and detector depth.
4. Build an edge/bad-region/vignetting mask.
5. Measure recovery of known Gaia/static stars as a function of magnitude and position.
6. Estimate local PSF statistics from nearby unsaturated real stars.
7. Record saturation, halos, diffraction/optical structure, scratches/emulsion defects and scanner artefacts.
8. Exclude regions where a comparison plate cannot demonstrate adequate local completeness.

This allows non-detections to mean “source absent to adequate depth”, rather than “comparison image was too poor to see it”.

---

## 5. Branch A — distant/common-sky coincidence workflow

For every viable cross-observatory pair in the current time gate:

1. Run the frozen detector independently on A and B.
2. Convert detections to celestial coordinates through each plate's WCS.
3. Crossmatch using the frozen broad 10-arcsec radius and the stricter 3-arcsec registered diagnostic.
4. Quantify local astrometric residuals using known common stars; do not interpret a raw separation without the local registration error distribution.
5. Apply static-source vetoes:
   - Gaia with epoch/proper-motion propagation where necessary;
   - Pan-STARRS / GPS1 or equivalent;
   - other appropriate historical/modern catalogues;
   - known variables/movers where applicable.
6. Compare morphology in both plates against the local stellar PSF.
7. Run shifted-position/randomised crossmatch controls to measure accidental-match density.
8. Run injection/recovery tests at relevant magnitudes where a candidate is close to the detection threshold.
9. If a cross-observatory common-sky source survives, immediately invoke the neighbouring-plate escalation in Section 8 and stop the queue.

Interpretation: a survivor is strong evidence of real incident light and strongly disfavors a defect unique to one plate/scan. It does not by itself identify the source mechanism.

---

## 6. Branch B — independent single-observatory transient replication

This branch is run independently for Palomar/POSS, Harvard/DASCH and additional archives where image quality permits.

For each discovery exposure:

1. Run the frozen detector.
2. Reject catalogue/static sources and propagated proper-motion stars.
3. Require point-source-like morphology relative to nearby real stars of comparable signal level.
4. Retrieve the best preceding and subsequent same-field exposures from the **same observing system/archive**, preferring the closest in time that provide adequate depth.
5. At the candidate coordinate, quantify rather than eyeball the comparison images:
   - local sigma/SNR;
   - injected-source recovery at candidate brightness;
   - nearby comparison-star recovery;
   - local background/transparency quality.
6. Classify temporal evidence:
   - `single_plate_only_unconfirmed` — no adequate adjacent plate exists;
   - `one_side_temporal_veto` — adequate pre **or** post plate absent;
   - `two_side_transient_supported` — adequate pre **and** post plates absent.
7. Where independent scans/copy plates exist, use them only to test scan/copy artefacts. Do **not** count scans of the same original exposure as independent astronomical detections.
8. Record transient surface density/rate using effective sky area × exposure time, not raw plate or calendar-day counts.

Population-level comparison:

- compare transient rate after matching effective depth, usable area and exposure duration;
- compare PSF/magnitude/multiplicity/alignment distributions;
- compare Palomar with Harvard and other independent observatories;
- explicitly test whether a phenomenon is peculiar to POSS-I photographic/processing history.

---

## 7. Branch C — parallax-aware near-Earth matching

Only perform this branch after a Branch-B candidate survives morphology, catalogue and neighbouring-plate tests sufficiently to be credible.

1. Require resolved physical observing sites for A and B.
2. Define the exact simultaneous exposure interval.
3. Because the flash time within a long exposure is unknown, sample event time across the simultaneous interval.
4. Sample a predeclared range grid rather than fitting only GEO after seeing the data. Suggested reporting bins:
   - 0.5–2 thousand km (LEO-like)
   - 2–30 thousand km (MEO-like)
   - 30–50 thousand km (GEO/high-Earth focus)
   - 50–100 thousand km
   - 100–500 thousand km (high/cislunar control)
5. For each `(time, range)` hypothesis, intersect observer A's line of sight with the corresponding 3-D location and project that position into observer B's topocentric sky.
6. The resulting family of predictions forms a parallax locus/band on plate B.
7. Search B for uncatalogued point-like detections along that locus using a tolerance derived from:
   - A and B astrometric uncertainty;
   - plate PSFs;
   - time sampling;
   - range-grid spacing.
8. For any B detection, solve the two lines of sight jointly and estimate closest-approach distance/range with uncertainty.
9. Test whether the inferred motion/exposure behaviour is compatible with a point-like brief flash rather than a trail.
10. Evaluate solar illumination and Earth-shadow state at the inferred location/time.
11. Do **not** treat absence in B as a rejection of specular reflection; use Branch C primarily as a positive-identification/triangulation test.

---

## 8. Mandatory strong-candidate escalation and stop rule

If any event becomes a credible candidate, **finish that event's analysis and stop before starting the next case**.

A stop-worthy candidate includes either:

- a common-sky cross-observatory source that survives static, morphology, registration and chance-alignment controls; or
- a single-observatory before/positive/after transient that is morphologically stellar and has no convincing static counterpart; or
- a parallax-consistent simultaneous pair compatible with one nearby physical source.

Escalation package:

1. Freeze all source images/cutouts and checksums.
2. Retrieve adjacent plates from both archives where available.
3. Perform local completeness/injection tests.
4. Inspect independent scans/copy chains.
5. Query static, variable, minor-planet/satellite and historical catalogues as applicable.
6. Re-run astrometry with local reference stars.
7. Conduct blinded/shifted controls.
8. Produce candidate dossier with images, coordinates, timing, morphology and alternative explanations.
9. **Report to the user and wait before resuming the queue.**

---

## 9. Correlation-informed processing priority

Correlations affect **order only**, never inclusion/exclusion or detection thresholds. Metadata should be calculated before inspecting candidate outcomes wherever practicable.

Priority metadata:

1. nuclear-test timing, especially the previously reported **+1-day** sub-result, with ±1-day window retained;
2. solar illumination / Earth-shadow geometry (reported deficit in the GEO umbra; shadow regions are useful negative controls);
3. geomagnetic Kp / quietness as a separately-labelled newer exploratory result;
4. historical UAP-report count as exploratory metadata only;
5. multiple/aligned transient context where present;
6. actual simultaneous exposure duration and usable common sky area as observational-power tie-breakers.

All claimed correlation datasets and date/time conversions must be versioned and independently rechecked before being used for priority scoring.

---

## 10. Time-gate order

For simultaneous Branches A and C:

1. finish **≤5-minute midpoint gate**;
2. only after its viable opportunities are dispositioned, generate/process **>5 to ≤10 minutes**;
3. then generate/process **>10 to ≤15 minutes**.

The wider gates are incremental; do not re-count lower-gate pairs as new observations.

Branch B does not fundamentally require a cross-observatory midpoint gate. Initially, however, process the plates already represented in the ≤5-minute set because they have simultaneous independent coverage and therefore maximize follow-up options; later expand to a controlled archive-wide sample.

---

## 11. Negative controls and calibration

For each major analysis mode:

- shifted-coordinate crossmatches;
- random sky-position controls preserving local source density;
- negative plates matched in depth/quality;
- injection/recovery grids by magnitude and plate position;
- local static-star recovery/completeness;
- plate-defect/morphology control library;
- blinded candidate ordering where practical.

Report candidate excess relative to controls; never infer significance from raw match count alone.

---

## 12. Required outputs

Append-only canonical tables should include:

- physical plate IDs and raw catalogue IDs;
- archive, telescope/series and resolved observing site;
- raw time metadata and corrected UTC start/end/midpoint;
- actual exposure-overlap seconds/minutes/fractions;
- WCS/footprint provenance;
- detector version and parameters;
- detections and crossmatch separations;
- local registration residuals;
- Gaia/Pan-STARRS/catalogue distances and proper-motion propagation;
- PSF/morphology metrics;
- pre/post comparison-plate evidence and completeness;
- shifted/random control counts;
- correlation-priority metadata;
- final disposition and reason;
- candidate-stop flag.

Never overwrite an old disposition silently. A correction creates a new row/version referencing the superseded result.

---

## 13. Current restart point

Do **not** resume the old workflow blindly. First:

1. resolve the observing sites needed for active ≤5-minute pairs;
2. calculate correlation-priority metadata using independently verified source tables;
3. reinterpret the remaining ≤5-minute work under Branches A/B/C;
4. retain completed same-sky negatives as valid Branch-A controls;
5. re-run rank 25 at the unique `rec799` identity;
6. continue rank 40 from the saved live checkpoint only after deciding which Branch-B candidate-generation work is required for its plates.

The existing work is not discarded: it becomes Branch-A evidence and a morphology/false-match control set.
