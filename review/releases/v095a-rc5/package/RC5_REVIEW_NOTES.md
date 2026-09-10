# v095a Stage A RC5 transport-evidence repair

RC5 is a narrow repair to the execution-frozen RC4 after its first live Q0 submission entered `SUBMISSION_UNCERTAIN_HOLD` without preserving the returned HTTP status/headers/body. The RC4 failed checkpoint remains audit evidence and is not imported into RC5.

## Frozen science unchanged

- SQL SHA-256: `1e318f66a80453208e77c41ccb89b6340c29b639b53741b634a459d649308b21`
- bins SHA-256: `c4fd3724579f37b847c1a4549fb6c45066531efc3607b1e37eca0a5567366313`
- parent v094z population and v094y provenance: unchanged
- expected population: 2,655 pairs / 2,683 fragments / 2,440 physical plates
- source permissions: aggregate-only; individual IDs/coordinates/photometry/pairing/pixels/scans remain forbidden

## Transport change only

Before interpreting the submission receipt, RC5 durably stores the HTTP status, selected `Location`/content headers, SHA-256/size of the bounded response body, and the raw response artifact. The response body is never printed.

- Accepted job-receipt statuses remain 201/302/303 and still require a valid same-origin `/tap/async/<job-id>` Location.
- Explicit HTTP 4xx responses except 408 become `TAP_SUBMISSION_REJECTED_HOLD`; no automatic retry.
- HTTP 408, unexpected 2xx/3xx/5xx, transport failures, or accepted statuses without a valid job Location remain `SUBMISSION_UNCERTAIN_HOLD`; no automatic retry.
- A submission response body is capped at 64 KiB.

Parent RC4 freeze commit: `f4d8cf83e96aa10fe01470270ca24ea093f5b262`.

Independent release review and Windows self-test/preflight are required before any RC5 execution freeze. No catalogue calls were made while preparing RC5.
