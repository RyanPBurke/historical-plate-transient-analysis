# RC5 note

RC5 changes transport receipt evidence only; the scientific matcher/Stage A design below is unchanged from RC4.

# v095a Source Matcher / Stage A Design RC5

## State

**IMPLEMENTATION RELEASE CANDIDATE — NO CATALOGUE EXECUTION UNTIL RELEASE FREEZE**

RC5 supersedes RC3 before any Stage A catalogue execution. It retains the confirmed RC3 Q2 correction and repairs validation, durable job handling, HTTP deadlines and controller ownership.

Parent lineage:
- v094y geometry-results commit: `2d30c9f780d2f2c9d572f81843af9d1c141444ad`
- v094z exact-byte population freeze: `97005975e356fdef17022d000fb593006f9e6c3e`
- v094y proof archive SHA-256: `1d6cdfe596711dad561ad67892536d2d4a6b779c6b57416afe2e3b95be65b84e`

Frozen downstream geometry population:
- 2,655 retained pairs
- 2,683 retained overlap fragments
- 2,652 admissible pairs / 2,680 admissible fragments
- 3 unresolved pairs / 3 unresolved fragments retained conservatively
- 3,383 linked v094y witnesses
- 2,440 unique physical plates

The inherited v094z `next_matcher_allowed=true` is **not an execution permission**. It means only that a downstream stage may now be designed. Every source-facing stage requires its own contract and explicit permission.

## Permission model

RC5 defines two independent permissions:

1. `STAGE_A_AGGREGATE_INVENTORY_ALLOWED`
   - permits only the exact metadata-binding and aggregate query families frozen below;
   - permits no individual source rows, identifiers, coordinates, magnitudes or candidate pairing.

2. `INDIVIDUAL_SOURCE_EXTRACTION_ALLOWED=false`
   - remains false after Stage A;
   - may become true only in a later, separately reviewed contract after uncertainty treatment and chance-association controls are frozen.

The Stage A runner refuses production merely because v094z says `next_matcher_allowed=true`. Production requires the exact RC5 contract/query/bin hashes plus a separately created Git freeze-evidence record.

## Scientific role of Stage A

Stage A is **aggregate-only and candidate-identity-blind**, not fully blind to population properties. It may reveal workload, processing multiplicity, calibration completeness and aggregate quality distributions. It must not reveal individual candidate identities or positions.

Stage A results may alter batching, storage and computational strategy. They must not silently alter scientific inclusion, quality thresholds or candidate ranking.

## Frozen parent association

Counts for a physical plate alone are not sufficient for science-facing inventory.

The frozen source-free lineage selected a specific astrometric `solution_id` and `scan_id` for each exposure. For every retained v094z pair, reconstruct both sides from the completed frozen v094t source-free opportunity census by exact `pair_id`, and retain:

- `exposure_id`
- `plate_id`
- `scan_id`
- `solution_id`

The Stage A preflight must require:
- one exact v094t row for every retained v094z pair;
- pair-side plate IDs agree with v094z;
- the v094t manifest validates before use;
- no missing selected `solution_id` or `scan_id`;
- all selected associations are written to a pre-query provenance file and hashed.

Because APPLAUSE `source_calib.solution_num` is meaningful only with its processing association, a metadata-only binding query against `applause_dr4.solution` must recover for each selected `solution_id`:

- `plate_id`
- `scan_id`
- `process_id`
- `solution_num`
- `solutionset_id`

The returned `plate_id` and `scan_id` must exactly match the frozen values. Missing, duplicate or conflicting solution rows are a HOLD.

The resulting science key is:

`(plate_id, scan_id, process_id, solution_num)`

No aggregate source count is science-eligible unless it is grouped on exactly that key.

Raw physical-plate processing multiplicity is reported separately and never substituted for selected-key counts.

## APPLAUSE coordinate / identifier conventions

For later stages, `source_calib.ra_icrs` / `dec_icrs` are treated as ICRS catalogue coordinates. `ra_error` and `dec_error` are reported in arcseconds, but RC5 does **not** assume they are independent Gaussian sigmas, does not combine them into a radial sigma, and does not assume any hidden cos(dec) convention. Those semantics must be validated empirically/documentarily before matching.

Gaia IDs must never pass through floating point. Any later individual Gaia identifier must be read as exact integer/string. Stage A does not return individual Gaia IDs.

Stage A does not label `gaiaedr3_id IS NULL`, `=0`, `<0` or `>0` as "matched" or "unmatched" unless the archive semantics for that category are explicitly established. It reports these categories separately.

## Stage A query families

The exact SQL templates are frozen in `v095a_stageA_queries_rc5.sql`. Runtime insertion is limited to deterministically generated `VALUES` rows, sorted ascending, from the frozen parent associations.

Every fully materialized query string is SHA-256 hashed **before submission** and retained with the TAP job identifier and returned raw aggregate file.

### Q0 — selected solution binding

Input rows: unique `(solution_id, expected_plate_id, expected_scan_id)` from frozen v094t associations retained by v094z.

Returned columns only:
- selected key ordinal
- `solution_id`
- expected and returned plate/scan IDs
- `process_id`
- `solution_num`
- `solutionset_id`
- found-row indicator

Q0 reads no source catalogue rows.

Acceptance:
- one output row per requested unique solution ID;
- exactly one matching solution row;
- returned plate/scan equal frozen plate/scan;
- process and solution number non-null;
- otherwise HOLD before Q1/Q2.

### Q1 — selected science-key aggregate inventory

Input rows: unique selected `(plate_id, scan_id, process_id, solution_num)` keys produced by Q0.

LEFT JOIN is mandatory so a selected key with zero `source_calib` rows returns a real row with `source_rows=0`; absence of a returned grouping row is therefore not interpreted as zero.

Returned data are aggregate counts only. No `source_id`, individual RA/Dec, individual Gaia ID or individual magnitude is returned.

### Q2 — physical-plate processing multiplicity

Input rows: the fixed 2,440 unique v094z physical plate IDs.

Reports, per plate:
- total `source_calib` rows across all processing;
- distinct scan count;
- distinct process count;
- distinct `(process_id, solution_num)` count;
- distinct `(scan_id, process_id, solution_num)` count.

These are workload/completeness diagnostics only. They do not define science eligibility.

**RC3 empty-plate correction retained:** both composite DISTINCT counts use `FILTER (WHERE sc.plate_id IS NOT NULL)`. Without that filter, PostgreSQL counts the synthetic NULL-bearing row introduced by the LEFT JOIN as one composite value for an empty plate. The Python self-test rejects nonzero empty-plate counts; the separate local PostgreSQL suite executes the frozen SQL and demonstrates the old unfiltered failure.

## Frozen histogram/category boundaries

All bins are mutually exclusive and completeness sums are checked against `source_rows`.

### model_prediction
- NULL
- `<0`
- `[0,0.10)`
- `[0.10,0.50)`
- `[0.50,0.90)`
- `[0.90,0.99)`
- `[0.99,1.00]`
- `>1` / special out-of-domain bucket

No threshold for later candidate acceptance is implied by these inventory bins.

### ra_error and dec_error, separately, arcsec
- NULL
- `<0`
- `=0`
- `(0,0.25]`
- `(0.25,0.50]`
- `(0.50,1.0]`
- `(1.0,2.0]`
- `(2.0,5.0]`
- `(5.0,10.0]`
- `>10` / special out-of-domain bucket

No Gaussian interpretation is attached to these bins.

### Gaia ID representation
- NULL
- `<0`
- `=0`
- `>0`

These are representation categories only, not astrophysical labels.

### SExtractor flags
- NULL
- `<0`
- `=0`
- `>0`

### calibrated coordinates
- both NULL
- RA NULL only
- Dec NULL only
- both non-null and within `0 <= RA < 360`, `-90 <= Dec <= 90`
- both non-null but outside those bounds

### annular_bin
- NULL
- each integer bin 1 through 9 separately
- outside 1..9

## Failure and completeness semantics

Stage A must distinguish:

- `ZERO_SOURCE_ROWS_CONFIRMED` — Q1 returned the expected selected-key row and aggregate count is exactly zero;
- `MISSING_SOLUTION_BINDING_HOLD` — Q0 cannot bind the frozen solution;
- `SELECTED_KEY_RESULT_MISSING_HOLD` — an expected Q1 selected key has no returned aggregate row;
- `PHYSICAL_PLATE_RESULT_MISSING_HOLD` — one of the 2,440 Q2 plate rows is absent;
- `AGGREGATE_COMPLETENESS_HOLD` — any mutually exclusive category sum differs from its row total;
- `TAP_JOB_ERROR_HOLD` — terminal ERROR;
- `TAP_JOB_ABORTED_HOLD` — terminal ABORTED;
- `TAP_TIMEOUT_HOLD` — no accepted terminal result within the frozen wait policy;
- `RESULT_SCHEMA_HOLD` — returned columns differ from the frozen schema;
- `RESULT_PARSE_HOLD` — malformed/truncated/unparseable result;
- `QUERY_HASH_HOLD` — materialized query is not derived byte-for-byte from the frozen template plus deterministic VALUES construction.

No failed/missing/truncated query is converted to zero detections.

Retry / wait policy:
- at most 2 resubmissions after the initial attempt, across all invocations;
- exact same query bytes on every retry;
- 30 s then 120 s delay;
- APPLAUSE TAP queue parameter: `1h`;
- hard terminal deadline per submitted job attempt: **3900 s** measured locally from successful submission;
- HTTP connect timeout: **15 s**; HTTP read timeout: **120 s**; parent-enforced wall limit: **135 s**, capped by the remaining job/operation budget;
- polling: every **5 s** for elapsed <60 s, every **15 s** for 60-600 s, every **30 s** thereafter;
- terminal phases accepted: `COMPLETED`, `ERROR`, `ABORTED`;
- on local terminal-deadline expiry, record `TAP_TIMEOUT_HOLD` and attempt a UWS abort;
- every job ID, phase observation, query SHA-256 and raw result SHA-256 is retained;
- scientific output is published only from a COMPLETED job whose result passes exact schema, key and completeness validation.

Deterministic batches are frozen as Q0=1000 selected solutions, Q1=250 selected science keys, Q2=500 physical plates. Completed validated batch results are resumable only when their materialized query, raw result, release/context and expected-key hashes replay exactly. In-flight jobs retain their original deadline and submission budget; invalid checkpoints remain held.

## Network accounting

Report network activity in separate counters:

- `git_provenance_network_calls`
- `catalogue_tap_metadata_binding_calls` (Q0)
- `catalogue_tap_aggregate_inventory_calls` (Q1/Q2)
- `individual_source_catalogue_calls`
- `pixel_or_scan_network_calls`

Stage A requires `individual_source_catalogue_calls=0` and `pixel_or_scan_network_calls=0`.

A Git fetch/remote verification therefore no longer permits a misleading blanket `network=0` statement.

## Pre-Sputnik tranche

Use the exact priority cutoff `1957-10-04T19:28:34Z` and also preserve the earlier date-exclusive definition (`before 1957-10-04T00:00:00Z`) as a separately reported diagnostic.

Expected retained counts from the current frozen population:
- 1,223 pairs
- 1,237 retained fragments

No current retained fragment straddles either boundary. This is an observed property of the frozen population, not a future rule. If a later candidate/admissible interval straddles the launch instant, retain the ambiguity rather than forcing a pre/post label.

## What Stage A may change

Allowed after Stage A:
- batch sizes;
- query partitioning;
- storage layout;
- expected compute/disk requirements;
- operational retry strategy only if a new contract records the change before re-execution.

Not allowed from Stage A outcomes without a new prospective scientific contract:
- model-prediction cut;
- SExtractor-flag cut;
- astrometric-error cut;
- Gaia inclusion/exclusion rule;
- edge/annular cut;
- source-match tolerance;
- candidate ranking based on observed yield.

## Gate required before individual-source extraction

Stage A completion does **not** permit individual-source extraction.

Before that, a separate reviewed matcher/calibration contract must freeze:

1. **Astrometric uncertainty treatment**
   - empirical Gaia-matched calibration using exact processing/solution keys;
   - exact interpretation of RA/Dec error terms;
   - catalogue epoch/frame conventions and any propagation needed;
   - treatment of scan/process duplicates.

2. **Chance-association controls**
   - controls receive the identical continuous-time / finite-distance optimisation as real candidate pairs;
   - physical plates, not pair rows, are the dependence blocks because plates are shared across many opportunities;
   - false-pair construction is deterministic/hash-based and fixed before real cross-observatory candidate yield is inspected;
   - sky-shift/rotation controls preserve local source density and processing quality as far as the frozen construction permits;
   - static Gaia-matched controls quantify accidental finite solutions from astrometric scatter and near-parallel geometry;
   - repeated scan/process records cannot count as independent astrophysical events.

3. **Candidate-specific finite geometry**
   - common continuous event time within the exact overlap fragment;
   - no exposure-midpoint substitution;
   - no arbitrary upper distance cap;
   - finite solution distinguished from infinity/asymptotic compatibility and unresolved numerical cases;
   - WGS84 exterior, occultation and local-horizon checks;
   - the v094y witness is an existence gate only, never the candidate position/distance.

4. **Site uncertainty / height stress**
   - ±107 m remains a stress diagnostic, not a confidence interval;
   - nominal, height-stress-sensitive, height-stress-only and unresolved classes remain distinct;
   - documented observatory-coordinate uncertainty, if later found, must be a separate model.

## Source-facing stop rule

RC5 is an implementation release candidate. Stage A aggregate inventory becomes executable only after release-specific review, Git freeze, and freeze-evidence verification.

STOP after Stage A inventory publication and interpretation.

Do not query individual source rows, build candidate lists, pair detections, inspect coordinates/magnitudes, access pixels/scans, or tune scientific thresholds until the next contract is independently reviewed and frozen.


## RC5 execution boundary

The package includes a runner, but **production catalogue execution is disabled until a Git freeze is proven**.

Allowed before freeze:
- `--self-test`: synthetic/local tests only, no network;
- `--preflight-only`: parent/provenance/association verification and deterministic query planning only, no TAP calls.

Production requires:
- full 40-character freeze commit;
- local HEAD equal to that commit;
- tracked worktree clean;
- independently recorded `origin/main` equality in the freeze-evidence JSON;
- exact release-manifest hash and exact Git blob bytes for the RC5 release;
- parent v094z commit as an ancestor;
- v094y foundation provenance digest replay equal to `fac0993e225b3a35e325cdda78aaa8e25437384f2db1bce026cb3564baaf44db`;
- v094y proof archive SHA-256 replay.

Production output remains aggregate-only and candidate-identity-blind and ends with `individual_source_extraction_allowed=false`.


## RC5 execution corrections (supersede earlier RC3 operational descriptions)

The scientific SQL bytes and histogram specification are unchanged from RC3.
The implementation and machine-readable RC5 contract define the following corrections:

- Strict CSV parsing preserves newlines and rejects malformed records and non-integer count fields. Q2 multiplicity projections and per-plate Q1 <= Q2 totals are checked.
- A spawned HTTP child is terminated at the operation deadline, including slow streaming bodies. The original 3900 s terminal deadline survives restart; accepted completion must precede it. Downloads have separate 135 s attempts, with at most three downloads from the same completed job.
- Submission intent and job URL are saved before polling. Unknown submission acceptance is held for reconciliation. Known active jobs resume under their original deadline. The three-submission budget never resets on restart.
- Ctrl+C preserves state and attempts a bounded, confirmed abort. Unconfirmed aborts block new submissions. Failed validation and corrupted checkpoints remain held, with evidence preserved.
- A project OS lock covers mutable work. Publication uses its own unique staging directory and copies only validated batches. The recursive manifest includes queries, raw results and attempt metadata.
- Network operation attempts for this invocation and cumulative retained evidence are reported separately.
- Q0 and Q1 key_id values are family-local ordinals. Join binding and inventory tables by the exact four-column science key, not by key_id alone.

The Python self-test exercises simulated TAP lifecycle/failure paths. The separate SQL suite executes the exact templates in disposable local PostgreSQL. Neither queries APPLAUSE. Local Windows preflight and independent release review remain required before the execution freeze.
