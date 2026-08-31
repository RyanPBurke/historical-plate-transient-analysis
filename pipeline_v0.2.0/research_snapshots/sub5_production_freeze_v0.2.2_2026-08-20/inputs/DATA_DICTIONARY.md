# Publication data dictionary

## Core identifiers

- `pair_key`: immutable textual identity of the two exposure records.
- `canonical_order`: order in the frozen ≤5-minute queue.
- `job_key` / `source_id`: per-target identifier within a processing stage.
- `stage`: frozen processing operation, including plate/process parameters where relevant.
- `run_id`: one invocation of a stage; retries/restarts create additional stage-run rows without erasing earlier history.

## Job status

- `pending`: eligible but not yet processed.
- `running`: currently claimed by a worker.
- `succeeded`: scientific computation completed on validated input.
- `failed_retryable`: remote/transient failure; not a scientific zero.
- `failed_terminal`: row-specific data/logic failure; not a scientific zero unless separately resolved and reclassified.

## Provenance payload

Each publication-mode manifest job carries `_provenance` containing:

- `manifest_path`
- `manifest_sha256`
- `frozen_config_path`
- `frozen_config_sha256`
- `code_fingerprint_sha256`
- active publication-snapshot metadata

## Evidence index

`evidence/index/evidence.jsonl` is append-only and contains:

- `remote_exchange`: service, stage, job, attempt, exact query hash/path, response hash/path, endpoint and selected response headers;
- `local_artifact`: file kind, path, SHA-256, size, stage/job identity, source URL and role metadata.

## Pixel fields

- `cutout_sha256`: SHA-256 of exact FITS bytes analysed.
- `cutout_cache_path`: local FITS path.
- `cutout_provenance_sidecar`: request/plate metadata sidecar.
- `nearest_peak_sep_arcsec`: angular separation between target coordinate and nearest frozen-detector peak.
- `nearest_peak_snr`: residual peak divided by robust MAD sigma.
- `nearest_peak_polarity`: sign of residual at nearest qualifying peak.
- `peak_count`: number of >4σ local maxima after edge exclusion.
- `strict_match`: true only when separation is within the frozen strict registered gate.
