# GPT REQUEST v095a-rc5-release-review

## Context

RC4 was independently reviewed, passed Windows self-test/preflight, and was execution-frozen at:

`f4d8cf83e96aa10fe01470270ca24ea093f5b262`

The first live RC4 Q0 submission then stopped conservatively with:

`SUBMISSION_UNCERTAIN_HOLD: job receipt unavailable; do not resubmit`

The retained RC4 checkpoint shows:
- family: Q0_SELECTED_SOLUTION_BINDING
- batch: 1
- status: FAILED_HOLD
- transport requests: 1
- attempts: 1
- attempt state: SUBMITTING
- no job URL recorded
- no response artifact retained
- APPLAUSE_TOKEN absent (anonymous request)

APPLAUSE's published documentation describes personal-token authentication as optional and permits guest query access, so absence of a token is not treated as sufficient explanation for the response.

## RC5 repair scope

RC5 changes transport receipt evidence only.

Unchanged:
- SQL SHA-256: `1e318f66a80453208e77c41ccb89b6340c29b639b53741b634a459d649308b21`
- bins SHA-256: `c4fd3724579f37b847c1a4549fb6c45066531efc3607b1e37eca0a5567366313`
- 2655 pairs / 2683 fragments / 2440 physical plates
- selected-solution binding
- batch sizes
- v094y/v094z parent bindings
- aggregate-only permission boundary
- individual source IDs, coordinates, photometry, pairing, pixels and scans remain forbidden

RC5 now durably records submission HTTP status, selected Location/content headers, response-body SHA-256/size and bounded raw response artifact before interpreting the receipt. It distinguishes explicit 4xx rejection (except 408) from ambiguous acceptance states, while never automatically resubmitting either.

RC4 failed work is not imported into RC5.

## Artifact identity

- ZIP: `v095a_stageA_implementation_rc5.zip`
- ZIP SHA-256: `11993c8c2cf943564300155a07704d85e85845e4f05eb8f2cab4e756cb5aa275`
- ZIP size: 50,824 bytes
- RC5 contract SHA-256: `0ed31dcd20e5b75c46fb6ce5405ee0fbcd712b3201175a5b9316f67d0aa344d2`
- release manifest SHA-256: `c6696e07c329e99d268b74f86871593c0e1663dff5f3a31fa62b3b91cf677e59`

## Validation

- 51/51 Python regressions: PASS
- package self-test: PASS
- release-manifest integrity: PASS
- runner/contract SHA binding: PASS
- SQL and bins exact-byte identity with RC4: PASS
- catalogue/network calls during tests: 0

New regressions cover:
- explicit 400/401/403/404/405/413/415/422/429 rejection evidence;
- ambiguous 200/202/307/408/500/503 response evidence;
- valid 303 Location receipt;
- accepted-status invalid Location;
- transport-failure partial response preservation;
- corruption of submission artifact;
- mismatch of submission metadata.

## Requested independent review

Please review the exact RC5 ZIP/hash above and give release-specific `YAY` or `NAY`.

In particular check:
1. submission evidence is persisted before receipt interpretation;
2. no response body or credential is printed;
3. explicit rejection vs uncertain acceptance classifications are conservative;
4. no automatic resubmission occurs after either class;
5. valid job receipts remain same-origin and exact-path validated;
6. checkpoint validation cryptographically binds the new submission evidence;
7. publication includes that evidence only after a batch is validated;
8. RC4 failed evidence is not silently imported/reset;
9. SQL/bins/population/scientific permissions are unchanged;
10. Windows self-test/preflight must still pass before a new execution freeze.

RC5 is not execution-frozen and no RC5 catalogue query has been submitted.
