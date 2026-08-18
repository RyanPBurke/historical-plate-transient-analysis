# Transient cross-observatory investigation — continuation handoff

**Checkpoint date:** 2026-08-17 (Europe/London)  
**Purpose:** make the investigation resumable after a ChatGPT/tool/platform failure without reconstructing the work from conversation history.

## 1. Objective

Search historical photographic-plate archives for **contemporaneous transient detections in independent observatories/catalogues**. Pre-Sputnik is preferred. Post-Sputnik is still interesting, particularly if multiple anomalous objects occur on one exposure.

Current cadence is frozen:

1. finish all scientifically viable **≤5-minute midpoint-separated** pairs;
2. only if no defensible candidate survives, expand to **≤10 minutes**;
3. then, if still warranted, expand to **≤15 minutes**.

Do **not** widen the time window merely because catalogue screening is complete. Pixel/manual follow-up of the viable ≤5-minute cases comes first.

## 2. Headline state at this checkpoint

- Corrected timing reconstruction contains **74 ≤5-minute cross-site pairs**.
- **47** involve corrected POSS-I; **27** are non-POSS.
- All 47 corrected POSS pairs have a spatial/catalogue disposition in the checkpoint.
- All 27 non-POSS pairs have a spatial/catalogue disposition.
- **Rank 28 (ai44247 ↔ POSS O989) has a complete 3×3 pixel grid follow-up.**
- The authoritative morphology/manual-review register contains **41 retained cases (DEF-001…DEF-041)**.
- These retained cases are **NOT 41 transients**. They are probable plate defects, plate-texture coincidences, faint-static ambiguities, PSF/saturation structures, and deliberately retained controls for manual comparison.
- **No defensible two-observatory astrophysical transient has survived so far.**

The manual-review sample is intentionally being built for a later close visual/morphological comparison with the anomalous point sources reported by **Villarroel and Druska**.

## 3. Authoritative files — use these first

### `checkpoints/AUTHORITATIVE_postcorrection_progress.csv`
Current per-rank POSS/non-POSS progress table. For POSS ranks 1–47 it records catalogue, pixel, spatial-rejection and follow-up status.

**Known discrepancy:** rank 3 still says `negative_catalogue_pixel_pending`, but later pixel work did occur and yielded **DEF-003**. Treat `AUTHORITATIVE_probable_plate_defects_manual_review.csv` as the later evidence for rank 3. Do not erase this discrepancy; resolve it deliberately when next editing the checkpoint.

### `checkpoints/AUTHORITATIVE_nonposs_sub5_progress.csv`
All 27 non-POSS ≤5-minute pairs and their current dispositions.

### `checkpoints/AUTHORITATIVE_probable_plate_defects_manual_review.csv`
The latest and most complete manual morphology register: **41 rows, DEF-001 through DEF-041**. This supersedes the older 19-row register in `legacy/`.

### `checkpoints/corrected_poss47_true_wcs_screen.csv`
The ranked corrected POSS/DASCH ≤5-minute list and approximate WCS screening data. Live StarGlass cutout coverage always overrides the approximate wide-field linear-WCS result.

## 4. Frozen detector / scientific rules

From `scripts/pilot_pixel_qa.py`:

- local Gaussian background scale: **8 px**
- search **both polarities**
- threshold: **4σ**, robust sigma from MAD
- local maximum window: **7 px**
- edge mask: **30 px**
- original cross-observatory screening match radius: **10 arcsec**
- stricter crowded-field/registered diagnostic: **3 arcsec**

Do not silently alter the 4σ detector threshold in the main analysis.

The old `pilot_unmatched_peaks` population / thousands of local extrema is **diagnostic plate texture, not a transient catalogue**.

Promotion gates remain:

1. verified original timing/site/plate metadata;
2. true WCS overlap;
3. deterministic matched cutouts at preselected common-footprint locations;
4. identical frozen detector;
5. Gaia/static catalogue rejection;
6. plate/PSF/saturation/registration vetting;
7. negative controls and injection/recovery;
8. only then trajectory/launch interpretation or any transient claim.

## 5. Critical timing correction

POSS-I times in VI/25 are Palomar local/PST. After-midnight local exposures can belong to the ending local calendar date. Convert to UTC by adding 8 hours after applying the local-date rollover correctly.

This correction is what produced the current **74 ≤5-minute pairs**. Do not resume the older pre-correction “81 WCS pairs / tile 41” run.

DSS `DATE-OBS` strings are not authoritative for the corrected historical timing; use VI/25 timing as the primary timing record. STScI scan labels can also be offset by one from VI/25 numbering in some fields (examples encountered: VI/25 1009 vs STScI O1010; VI/25 985 vs STScI E986). Verify field/night identity rather than blindly equating the numeric labels.

## 6. Most important current morphology cases

The complete details are in the authoritative DEF CSV. The current **very-high-priority** cases are:

- **DEF-006** — rank 13, ka02504 / E318
- **DEF-008** — rank 15, fa13177 / E779
- **DEF-009, DEF-010** — rank 23, ai44304 / O1023
- **DEF-011** — rank 25, ai44306 / O1023
- **DEF-014** — rank 28, ai44247 / O989
- **DEF-023** — rank 28 south-centre tile
- **DEF-027** — rank 28 south-east tile
- **DEF-031** — rank 28 east-centre tile
- **DEF-037** — rank 28 north-east tile
- **DEF-040** — rank 28 north-east tile

Again: these are **manual-comparison targets / probable artefacts until proven otherwise**, not discoveries.

Rank 28 is particularly valuable because the complete 3×3 grid gives an empirical **false-transient / plate-texture population under the same detector**, rather than just one cherry-picked anomaly.

## 7. Highest-priority work to resume

### A. Finish candidate-bearing POSS ≤5-minute pixel grids

1. **Rank 3** fa12998 ↔ E606 — centre work produced DEF-003; checkpoint status is stale; finish/verify full grid.
2. **Rank 12** ai43241 ↔ E306 — DEF-004; full grid pending.
3. **Rank 13** ka02504 ↔ E318 — DEF-005/006/007; full grid pending.
4. **Rank 15** fa13177 ↔ E779 — DEF-008; full grid pending.
5. **Rank 23** ai44304 ↔ O1023 — DEF-009/010; full grid pending.
6. **Rank 25** ai44306 ↔ O1023 — DEF-011; full grid pending.

Rank 28 full grid is already complete — **do not redo it** unless reproducing as a verification run.

### B. Finish partial-overlap strip sampling

- **Rank 40** ai44291 ↔ O1009 (STScI may label O1010): real overlap is a northern strip; DEF-015/016 retained; rest of strip pending.
- **Rank 41** ka02474 ↔ E305: real overlap is only the far northern edge (~Dec +3 to +3.8°); DEF-017 retained; wider strip sampling can continue.
- **Rank 46** ai43235 ↔ O297: true NE partial overlap; DEF-018/019 retained; additional deterministic strip sampling can continue.

**Rank 39** ka02473 ↔ O305 is already a partial-overlap pixel negative at the sampled strip point: 9 H/O matches and all Gaia-close.

### C. Rank 30 alternative pixel source

**Rank 30 ai44246 ↔ O988:** STScI DSS returned an HTML error stating calibration/image data were not available for the field. Do not call this a negative. Obtain pixels from an alternative plate source if possible.

### D. Non-POSS ≤5-minute unfinished pixel/manual work

From `AUTHORITATIVE_nonposs_sub5_progress.csv`:

- `APPLAUSE:13623 | bi05607` — true WCS; pixel follow-up.
- `APPLAUSE:132097 | b76371` — thin-strip overlap; pixel follow-up.
- `APPLAUSE:131892 | ax04674` — substantial true WCS overlap; pixel follow-up.
- `APPLAUSE:115054 | fa13406` — catalogue-zero; pixel confirmation.
- `APPLAUSE:12469 | bi05459` — true partial overlap; pixel confirmation.
- `APPLAUSE:11787 | bi05352` and `APPLAUSE:11788 | bi05352` — catalogue-zero; pixel confirmation.
- Six Hamburg/Vatican pair-family rows are parked for **manual astrometric solution** because the Vatican plates have no usable published DR4 `source_calib` WCS/catalogue solution.

The main Hamburg/Vatican example is Hamburg plate 7017 / Vatican plate 95875 (APPLAUSE exposure IDs 12414 / 139005). Large FITS products were previously identified; Vatican requires manual astrometric solving.

## 8. Known completed/rejected examples — do not reopen without a reason

- **j03761 ↔ POSS 445:E/O** — rejected as bright-star PSF/saturation structure around Gaia G≈8.8 star. Preserved as DEF-001 morphology control.
- **ka02643 ↔ POSS 407:E** — negative at calibrated source depth; six official Harvard sources, all static.
- Corrected POSS ranks **31, 42, 43, 45, 47** — spatial false positives after live coverage testing / no true solved-WCS overlap.
- Rank 39 sampled true strip — pixel negative after Gaia rejection.
- Rank 28 full 3×3 grid — complete; produced morphology controls but no astrophysical survivor.

## 9. Archive/API notes and failure modes

### Harvard DASCH / StarGlass

Public cutout endpoint used by the scripts:
`https://api.starglass.cfa.harvard.edu/public/dasch/dr7/cutout`

`platephot` endpoint:
`https://api.starglass.cfa.harvard.edu/public/dasch/dr7/platephot`

Important:

- `solution_number` is **0-based**. A plate with one solution uses `0`, not `1`.
- `platephot` response is a **JSON array of CSV lines**, not raw CSV. Correct conceptual parsing: JSON → list of lines → join with `\n` → CSV.
- Recent work used `refcat: "atlas"`; do not silently mix reference catalogues within one comparison.
- StarGlass intermittently returns **HTTP 502**. Split 9-tile calls into 3-tile or single calls; do not treat failed requests as zero detections.
- Live cutout **200/422 coverage is more trustworthy than approximate wide-field linear WCS polygons**, especially near plate edges.
- Under Wolfram, cutout response encoding varied between wrapped/quoted base64 forms. Always type-check the response before decoding; do not accept a downstream fake `0 detections` after an import/parser warning.

### STScI DSS

DSS endpoint used by the scripts:
`https://archive.stsci.edu/cgi-bin/dss_search`

Use `poss1_red` / `poss1_blue`, FITS output, fixed small cutouts. A nominal HTTP 200 can still contain an HTML `ERROR` document; validate FITS before analysis.

### APPLAUSE DR4

APPLAUSE catalogue queries showed some Vatican plates have extracted/process data but **no calibrated `source_calib`/published astrometric solution**. Those are manual-solve cases, not catalogue negatives.

## 10. Tool/platform problems observed immediately before this handoff

The analysis itself was checkpointing correctly, but the external execution path became unreliable:

- intermittent StarGlass 502s;
- response-body encoding changed across equivalent requests;
- Wolfram import/type quirks produced misleading fake zero counts if not explicitly rejected;
- some larger/nested tool calls appeared to stall without a clean user-visible return.

Recommended continuation style:

- one external request at a time;
- small atomic calculations;
- type/status validation immediately after every response;
- checkpoint every completed tile/candidate;
- immediately report tool failures; never silently interpret them as scientific negatives.

## 11. File map

### `scripts/`
- `pilot_pixel_qa.py` — preserved detector settings / initial pixel workflow.
- `fetch_priority_cutouts.py` — DASCH + DSS cutout retrieval patterns.
- `validate_priority_pairs.py` — pair validation logic.
- `build_overlap_matrix.py` — overlap candidate construction.

### `source_data/`
- `poss1_plate_metadata.csv` — VI/25 POSS metadata used for corrected timing.
- `dasch_exposures_1951_1955.csv`
- `applause_exposures_1951_1955.csv`
- `archive_pair_overlap_candidates.csv`
- `dasch_priority_plate_details.csv`

### `legacy/`
Contains older/pre-correction checkpoints and the earlier `transients_launch_overlap_bundle.zip`. Keep these for audit/reconstruction, but **do not use them in preference to the authoritative current checkpoints**.

## 12. Stop condition before expanding to 10 minutes

Do not move to ≤10 minutes until the viable ≤5-minute pixel/manual work above has either:

- been completed and rejected/parked with explicit reason, or
- reached a genuine candidate that passes the promotion gates and therefore deserves deeper analysis first.

At this checkpoint, **no such astrophysical candidate exists**.
