# v095a Stage A RC4 corrections

RC4 repairs the supplied RC3 implementation before any Stage A catalogue execution. It is a new release candidate, not an amendment of a previous execution freeze.

| RC3 issue | RC4 correction | Regression evidence |
|---|---|---|
| CSV parsing accepted an unterminated quote and could fold a quoted newline into an integer. | Strict CSV parsing preserves record boundaries and rejects embedded newlines, wrong widths, malformed schemas and non-integer counts. | Truncation, quoted-newline, schema, duplicate, missing/extra-cell and exact-integer tests. |
| Positive Q2 rows could contain impossible distinct counts. | Check count/projection inequalities and nonempty composite counts. Sum selected Q1 rows per plate and require that sum to fit Q2 all-processing rows. | Impossible-positive, projection, NULL-tuple and cross-query tests. |
| In-flight job IDs and submission budgets were not durable across interruptions. | Save intent before POST, receipt/deadlines before polling, and every phase, retry and interruption. Resume the known job and original budget. | Crash/resume, Ctrl+C, three-attempt exhaustion, uncertain receipt and unconfirmed-abort tests. |
| The nominal wait deadline could be exceeded by a request or slow stream. | Parent-enforced spawned-process HTTP limit, deadline checks after receipt, and persisted terminal expiry. | Late-completion, resumed-expiry and actual spawned slow-drip termination tests. |
| Failed validation discarded raw-response evidence. | Retain and hash each received result before parsing; preserve failed and partial downloads. Failed validation is a sticky HOLD. | Malformed-result and HTTP-error retention, download-retry and corruption tests. |
| Concurrent controllers and shared staging could damage each other's work. | OS project lock covers mutable work. Publication uses a unique staging directory, validated-batch allowlist and recursive manifest. | Same-process/cross-process lock and publication allowlist tests. |
| SQL was not executed by the self-test. | Separate pinned local PostgreSQL suite executes the exact frozen Q0/Q1/Q2 templates. | Empty plate, old unfiltered negative regression, exact four-part key isolation, NULL/sentinel/boundary and populated multiplicity fixtures. |

## Frozen science

The Q2 empty-plate FILTER was already correct in RC3 and is not changed. Both the SQL and bins JSON remain byte-for-byte identical to the uploaded RC3 files. The SQL's original RC3 comment is intentionally retained to preserve its hash.

- SQL SHA-256: `1e318f66a80453208e77c41ccb89b6340c29b639b53741b634a459d649308b21`
- Bins SHA-256: `c4fd3724579f37b847c1a4549fb6c45066531efc3607b1e37eca0a5567366313`
- v094z population commit: `97005975e356fdef17022d000fb593006f9e6c3e`
- v094y foundation digest: `fac0993e225b3a35e325cdda78aaa8e25437384f2db1bce026cb3564baaf44db`
- v094y proof archive digest: `1d6cdfe596711dad561ad67892536d2d4a6b779c6b57416afe2e3b95be65b84e`

No quality thresholds, selected-solution rules, population definitions or permitted source-facing outputs change. Q0 and Q1 key_id values are family-local ordinals; join their outputs by plate_id/scan_id/process_id/solution_num, not key_id alone.

## Execution policy

Each job has the original 3900-second terminal deadline from receipt of its URL. At most three job submissions are allowed per batch across all invocations, with 30/120-second retry delays. Known active jobs are resumed. An ambiguous submission receipt is held for reconciliation instead of resubmitted.

Each HTTP operation has a 135-second wall limit, also capped by its remaining enclosing budget; 15-second connect and 120-second inactivity timeouts remain. A spawned worker enforces termination even if response bytes keep arriving. Cleanup allows up to two seconds after terminate and two after kill. GET redirects are restricted to the archive origin, with at most three hops; POST redirects are not automatically followed.

Abort has a separate 135-second budget and requires a terminal observation. An HTTP acknowledgement alone does not unlock another submission. A completed job permits at most three result-download attempts, each 135 seconds, from that same job. Neither a restart nor a failed parse resets these budgets.

The result-body limit is 8 MiB; phase responses are capped at 4096 bytes. Invalid schemas and values are not printed. Failed response artifacts are evidence, not validated scientific output; preserve them without opening them for candidate inspection. An unexpected schema is a HOLD.

Batch metadata binds the freeze commit, release manifest, contract, SQL, bins, frozen parent/proof hashes, exact query and expected keys. Invalid or failed checkpoints remain in place. Request-attempt counters include transport failures and distinguish the present invocation from cumulative checkpoint history.

The OS lock is effective between RC4 controllers using the same canonical project path. Older releases do not acquire it and must be stopped before RC4 is used. Do not run another controller or manually edit its work directory during execution.

## Review boundary

See VALIDATION_RC4.md for results and limitations. Independent review of the revised transport/lifecycle code and local Windows preflight remain required before the execution freeze. This package does not claim live TAP integration testing or completed Stage A inventory.
