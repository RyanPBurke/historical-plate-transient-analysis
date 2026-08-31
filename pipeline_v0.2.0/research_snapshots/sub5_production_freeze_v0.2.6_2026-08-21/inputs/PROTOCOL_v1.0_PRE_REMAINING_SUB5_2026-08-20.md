# Historical photographic-plate transient search
## Production protocol v1.0 — frozen before remaining ≤5-minute queue

**Freeze date:** 2026-08-20  
**Scope:** remaining canonical ≤5-minute cross-observatory opportunities plus explicit revalidation of previously touched rows.  
**Scientific-algorithm status:** frozen. Publication-mode changes after this point may add logging, hashing, raw-response preservation, or recovery tooling, but must not change scientific thresholds or candidate definitions without a separately versioned protocol revision.

## 1. Transparency about prior exploratory work

This is **not** a claim that all 74 canonical ≤5-minute pairs were unseen before this freeze. Substantial exploratory work preceded the production protocol. `research/PRE_FREEZE_ANALYSIS_INVENTORY_2026-08-20.csv` records every queue row known to have a prior saved disposition or other explicit exploratory analysis at freeze time.

Rows touched before the freeze are to be labelled **development/revalidation** in any publication. Rows not touched before the freeze form the **prospective remainder**. If previously touched rows are rerun under this protocol, those reruns are valid reproductions/revalidations but must not be described as prospectively blinded tests.

The APPLAUSE 13623 ↔ DASCH bi05607 pair is a development/revalidation case. Its earlier Harvard pixel layer was invalidated after a provenance discrepancy; all Harvard results were rerun from verified current FITS products. Corrected result: 311 Harvard-tested targets and zero strict ≤3.0 arcsec coincidences.

## 2. Research branches

Three questions remain distinct:

1. **Branch A — distant/common-sky coincidence:** two independent observatories record a source at essentially the same sky position during overlapping exposures.
2. **Branch B — independent single-observatory transient replication:** an uncatalogued source is present on one exposure and absent on adequate neighbouring exposures in the same observing system.
3. **Branch C — parallax-aware near-Earth matching:** after a credible Branch-B candidate is established, search the other observatory along the physically allowed parallax locus as a function of time and range rather than demanding identical RA/Dec.

A result in one branch does not automatically validate another.

## 3. Canonical queue and timing

- The canonical ≤5-minute queue is the exact file frozen in the publication snapshot.
- Every pair retains raw exposure identifiers, archive/site labels, raw and interpreted timestamps, duration, midpoint separation, and actual exposure overlap.
- Actual overlap is:

  `max(0, min(end_A,end_B) - max(start_A,start_B))`

- Midpoint timing gates are processed in order: ≤5 minutes, then >5–≤10, then >10–≤15 if required.
- Archive/service failures are never scientific zeros.
- Within a gate, all viable opportunities are to be completed. There is **no result-dependent production stopping rule**. A strong candidate triggers evidence escalation and provenance checks but does not silently remove later queue opportunities from the denominator.

## 4. Physical identity and timing integrity

Before pixel interpretation:

- carry unique physical plate/exposure identifiers;
- POSS-I identifiers include VI/25 `recno` and must not rely on a duplicated bare numeric plate label;
- preserve raw timestamps and corrected/interpreted timestamps side-by-side;
- POSS-I VI/25 clock handling follows the established local-date/PST→UTC correction;
- DSS `DATE-OBS` is retained as archive metadata and is not substituted for authoritative historical POSS-I timing;
- APPLAUSE exposure times are taken from the frozen DR4 records used in the analysis;
- identify actual exposure intervals, not only midpoints;
- preserve the physical observing site and confidence when geometry/parallax depends on it.

## 5. Frozen detector

Unless protocol v1.x/2.x explicitly supersedes this file, the pixel detector is unchanged:

- Gaussian local-background sigma: **8 px**
- residual: image − Gaussian background
- both polarities through absolute residual
- robust sigma: **1.4826 × MAD** over finite residual pixels
- detection threshold: **>4 robust sigma**
- local-maximum window: **7 px**
- edge exclusion: **30 px**
- broad diagnostic cross-observatory radius: **10 arcsec**
- strict registered/contemporaneous coincidence gate: **3.0 arcsec**
- Hamburg independent recurrence gate: **3.2 arcsec**

No threshold is to be retuned in response to candidate appearance or yield.

## 6. APPLAUSE/Hamburg recurrence rule

For the Hamburg 13623-style workflow and analogous uses:

- target process is the explicitly identified discovery process;
- same-emulsion alternate scan is not counted as independent astronomical recurrence;
- for 13623, process 9549 is excluded as independent evidence because it is the Y scan of the same physical emulsion as process 9548;
- independent recurrence panel for that workflow: 9541, 9542, 9543, 9544, 9545, 9546, 9547, 9550;
- recurrence radius: **3.2 arcsec**;
- every TAP response used for a recurrence decision must be preserved verbatim and hashed in publication mode.

## 7. GPS1 static-source veto

Catalogue: **I/343/gps1**, J2010.

- query radius: **120 arcsec**;
- `pmRA` includes cos(dec), mas/yr;
- target epoch for the 13623 workflow: **1952.6198**;
- `dt = epoch − 2010`;
- `dec_hist = dec2010 + pmDE*dt/3.6e6`;
- `ra_hist = ra2010 + (pmRA*dt)/(3.6e6*cos(dec))`;
- static-source veto: propagated nearest source **≤10 arcsec**;
- no query hitting a row cap is scientifically usable;
- raw VizieR response and exact ADQL must be preserved and hashed.

For other epochs, the same propagation formula is used with the explicit plate epoch recorded in the stage context.

## 8. WCS and footprint

- Use the true plate/cutout WCS; do not replace a plate-polynomial WCS with a CRVAL/CD-only approximation where the data product requires the fuller solution.
- Verify plate identity before interpreting pixels.
- Forced plate extraction is required when automatic archive selection returns a different physical plate.
- Record the exact FITS hash for every image actually passed into the detector.
- A failed or unverified WCS/identity makes the row unresolved, not negative.

## 9. Evidence retention policy

### Tier 1 — mandatory for every scientific decision

Preserve:

- exact queue row / manifest input and SHA-256;
- exact frozen-method file and SHA-256;
- code fingerprint and active publication-snapshot ID;
- SQLite checkpoint row and append-only event log;
- exact remote query and successful raw response for catalogue/TAP decisions;
- status and error text for all failures;
- result CSV and hash.

### Tier 2 — mandatory for every pixel measurement

Preserve the exact FITS input passed to the detector, plus:

- SHA-256;
- archive endpoint / request parameters;
- plate/exposure/scan identity;
- WCS identity where available;
- role (`discovery`, `contemporaneous`, `pre-control`, `post-control`, `recurrence-control`, etc.).

DASCH/StarGlass cutouts are cached locally and hashed. Equivalent native products from other archives must be registered in the evidence index.

### Tier 3 — mandatory for promoted/high-confidence candidates or whole-plate algorithms

Preserve the native/full plate whenever:

- the scientific algorithm actually operates on the whole plate; or
- a candidate is promoted for detailed publication-level examination and the archive permits practical retrieval.

Where a native plate is very large, the exact stable archive identifier/DOI, scan metadata and archive-provided FITS checksum are preserved immediately; local native-plate download may be deferred until candidate promotion. Any derived cutout used quantitatively must itself be retained and hashed.

## 10. Candidate ledger and denominator

Every initial opportunity must remain represented, including rejected and failed rows. A publication must be able to recover:

- number of queue opportunities;
- number analysed in each branch;
- every gate applied;
- every exclusion and reason;
- retryable/terminal archive failures;
- every promoted candidate;
- every superseded result and reason.

`build-ledger` combines all SQLite jobs/stage runs into machine-readable ledgers. Manifests and queue snapshots remain separate immutable evidence and are linked through stored hashes.

## 11. Supersession rather than deletion

Scientifically invalid results are retained and explicitly superseded; they are not silently deleted. At minimum record:

- old result identifier/value;
- invalidation reason;
- affected input provenance;
- replacement result;
- replacement input hash.

The historical ~2.036 arcsec Harvard result for source `40095480011876` is an example: it is invalid because the historical pixel input was unpreserved/mis-associated; replacement separation is 52.810906810025216 arcsec from verified FITS SHA-256 `e593c06650d0f36a5eb8f72c0d517c39889c1f1f7f685d2bb6320eb0db843fb3`.

## 12. Manual adjudication

Any manual image classification must record reviewer, time, image hashes, information visible to the reviewer, decision and reason. Where practical, subjective morphology decisions should be made blind to the counterpart result. Automated frozen-detector outcomes are not manually overridden without a separately logged adjudication status.

## 13. Sensitivity and positive controls required before physical inference

Candidate discovery may proceed under this frozen detector, but a final paper must characterize sensitivity before interpreting a zero/low yield physically.

Required validation work includes:

- known-source astrometric/registration controls;
- known real-star recovery versus position and signal level;
- injection/recovery on representative plate/cutout strata;
- local depth/completeness assessment for comparison-image non-detections;
- shifted/randomized crossmatch controls where accidental coincidence density matters.

These tests may estimate detection efficiency; they must not be used to retune the frozen production detector after outcome inspection.

## 14. Publication labels

Any eventual manuscript must distinguish at least:

- `development/revalidation` — touched before this protocol freeze;
- `prospective_production` — not previously touched and processed after this freeze;
- `archive_blocked` — adequate public data unavailable or service failure unresolved;
- `scientific_negative` — required inputs succeeded and frozen criteria were not met;
- `candidate_promoted` — survived the relevant automated gates pending/after escalation;
- `superseded` — earlier result invalidated with recorded reason.

## 15. Change control

After the publication snapshot is activated:

- logging/storage/recovery changes that do not alter scientific inputs or decision thresholds may be released as implementation revisions while retaining this protocol version;
- any change to thresholds, WCS interpretation, timing rules, catalogue gates, recurrence definition, detector behavior, candidate promotion definition, or branch logic requires a new protocol version with a written rationale;
- the old protocol remains archived and hashed.
