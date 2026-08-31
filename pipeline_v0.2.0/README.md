# Historical Transient Laptop Pipeline

Restart-safe implementation of the frozen historical photographic-plate transient checks.

## Frozen detector

The detector is deliberately not adaptive:

- Gaussian local background sigma: **8 px**
- both polarities via absolute residual
- robust sigma: **1.4826 × MAD**
- threshold: **>4 sigma**
- local maximum window: **7 px**
- edge exclusion: **30 px**
- diagnostic cross-observatory radius: **10 arcsec**
- strict registered/contemporaneous gate: **3 arcsec**
- Hamburg recurrence audit tolerance: **3.2 arcsec**

Do not tune these values after looking at candidate outcomes.

## Why this runner exists

The interactive investigation repeatedly encountered StarGlass 502s, malformed/over-filtered TAP responses, connector timeouts, and interrupted long runs. This package makes those conditions explicit:

1. Every target is a unique SQLite job.
2. A result is committed only after the entire target finishes successfully.
3. HTTP 5xx/429/network failures are retryable failures, never scientific zeros.
4. Malformed payloads fail validation before analysis.
5. On restart, any `running` job is returned to `pending`.
6. A retryable 502/network failure is deferred until the next invocation; other pending jobs continue instead of hammering the failed target.
7. Validated StarGlass FITS cutouts are written atomically to a local cache and SHA-256 hashed, so a successful download is not repeated.
8. Completed jobs are never repeated unless the database is deliberately reset.
9. An append-only `.events.jsonl` file records transitions independently of the result table.

## Windows / PowerShell setup

```powershell
cd historical-transient-pipeline
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -e .
pip install pytest
pytest -q
```

If script activation is blocked, use `.venv\Scripts\python.exe` directly.

## Harvard / StarGlass resume run

Prepare a CSV containing at least:

```text
source_id,ra_deg,dec_deg
...
```

Then:

```powershell
transient-pipeline --db state\pair13623.sqlite starglass `
  --manifest examples\starglass_manifest.csv `
  --plate bi05607 `
  --export results\bi05607_results.csv
```

If the archive starts returning 502s, stop the process whenever convenient. Re-run the same command later. Successfully completed rows remain committed; interrupted rows are recovered and retried.

Check state without running anything:

```powershell
transient-pipeline --db state\pair13623.sqlite status
```

## Scientific-zero rule

A remote failure is represented by job state (`failed_retryable`) and error text. It must never be converted to `strict_match=false`, `nearest_peak_sep_arcsec=inf`, or any other scientific result.

## Next modules

The initial package implements the most failure-prone step first: validated StarGlass retrieval + frozen Harvard detector + persistent resume. The same job/checkpoint framework is intended for:

- APPLAUSE TAP source/control retrieval;
- GPS1 propagated static-source veto;
- exposure-overlap calculation and canonical pair queue;
- deterministic cutout caching/checksums;
- negative controls and injection/recovery;
- final pair-level aggregation.

## Frozen regression cases

`examples/regression_cases.csv` contains two live-archive numerical regression targets already reproduced during the interactive audit. After a successful StarGlass run:

```powershell
transient-pipeline --db state\regression.sqlite starglass `
  --manifest examples\starglass_manifest.csv --plate bi05607 `
  --export results\regression_results.csv
transient-pipeline verify-regressions --results results\regression_results.csv
```

The regression command checks exact peak count, robust sigma, SNR, polarity and WCS separation within tight numerical tolerances. An archive failure produces a failed job, not a failed scientific regression value.

## Catalogue/control stages

The same restart-safe database can now drive the catalogue gates:

```powershell
# Resolve a source_id-only list into APPLAUSE process-9548 coordinates
transient-pipeline resolve-applause --ids source_ids.csv --out manifest.csv

# Full independent Hamburg recurrence panel, explicit 3.2 arcsec
transient-pipeline --db state\pair.sqlite hamburg --manifest manifest.csv `
  --export results\hamburg.csv

# Full 120-arcsec GPS1 cone, propagated to epoch 1952.6198; <=10 arcsec static veto
transient-pipeline --db state\pair.sqlite gps1 --manifest manifest.csv `
  --export results\gps1.csv
```

These are intentionally separate stages: a failed archive never silently removes a target from a later scientific denominator. The exported CSV always retains job status and error text alongside successful measurements.

---

# Publication mode (v0.2.0)

Version 0.2.0 adds **provenance and evidence retention only**; it does not alter the frozen detector or catalogue thresholds.

## Publication evidence store

By default scientific commands now write evidence under `evidence/`:

- exact ADQL text, content-addressed by SHA-256;
- byte-exact successful APPLAUSE VOTable responses;
- byte-exact successful VizieR/GPS1 CSV responses;
- append-only request/response index records by stage/job/attempt;
- indexed StarGlass FITS cutouts and provenance sidecars;
- result CSV hashes.

Disable only deliberately with `--evidence-dir ""`.

## Freeze the production protocol

Before the remaining ≤5-minute production queue:

```powershell
.\freeze_publication_run.ps1
```

This freezes and hashes:

- `protocol/PROTOCOL_v1.0_PRE_REMAINING_SUB5_2026-08-20.md`
- `research/canonical_sub5_pairs_74.csv`
- frozen detector config
- pre-freeze analysis inventory
- code tree fingerprint
- exact Python/platform environment and `pip freeze`

The resulting snapshot is immutable and its ID is written to `research/ACTIVE_SNAPSHOT.json`. New stage jobs automatically retain that snapshot ID plus manifest/config/code hashes.

## Publication ledgers

At any milestone:

```powershell
transient-pipeline build-ledger --state-dir state `
  --jobs-out analysis\master_job_ledger.csv `
  --runs-out analysis\stage_run_ledger.csv
```

This does not replace queue/manifests; it gives one joinable record of every checkpointed job and every invocation/retry.

## Verify stored evidence

```powershell
transient-pipeline verify-evidence --root evidence
```

A missing or modified response/FITS is reported as an integrity failure.

## Register external/native images

For POSS-I, APPLAUSE native scans, GAVO SODA files, or any image retrieved by a custom branch:

```powershell
transient-pipeline register-artifact `
  --file .\cache\poss\plate.fits `
  --kind poss1_native_fits `
  --stage branch-a `
  --job-key candidate-123 `
  --source-url "<archive URL>" `
  --metadata-json '{"role":"discovery","plate_id":"..."}'
```

For APPLAUSE native scan identity/DOI/DataLink metadata:

```powershell
transient-pipeline applause-scan-info --process 9548 --out evidence\scan_info\process9548.json
```

Native APPLAUSE scans can be hundreds of MB, so publication mode does not blindly duplicate every full plate. Preserve/download the full native plate for promoted candidates or whenever the actual algorithm operates on full-plate pixels; otherwise preserve the exact quantitative cutout plus scan identity/DOI/checksum metadata.

## Legacy caveat

`research/LEGACY_EVIDENCE_GAPS_AT_FREEZE_2026-08-20.md` records which evidence was not preserved by pre-v0.2 exploratory runs. A later re-query of a frozen archive is a labelled backfill, not a claim that the original response bytes were retained.

## v0.2.1 POSS-I publication identity preflight

Adds `poss1-preflight`, which performs no transient detection. It validates the frozen queue against the preserved VI/25 plate catalogue, resolves the exact STScI DSS physical `plate_id` using survey/band, exposure duration, observing-night date and the documented/observed legacy decimal-hour epoch display, force-extracts a FITS cutout from that exact `plate_id`, verifies `REGION` where present, preserves byte-exact archive responses and FITS SHA-256 hashes, and records archive failures as retryable rather than scientific negatives.

The 37 prospective queue rows contain 31 unique POSS-I exposures; all 31 frozen UTC intervals and durations reproduce from the preserved VI/25 PST metadata in the v0.2.1 test suite.
