# Automated Stage A release review

This workflow operates on the dedicated draft release PR in RyanPBurke/historical-plate-transient-analysis. The shared mailbox links to that PR; the PR contains exact candidate packages, hashes, requests, tests and decisions.

## Roles

The reviewer automation reacts to commits and review discussion on this one PR. It independently checks a requested package, records the full reviewed head and archive hash, and posts an ASTRA RESPONSE with YAY/NAY and precise blocking scope. The reviewer does not author the implementation it approves.

The existing Sol coordinator automation checks for an unprocessed ASTRA RESPONSE. It may prepare narrowly scoped mechanical fixes and offline tests on the review branch, append GPT REPLY, then request independent review of the next candidate. Each uploaded/reviewed candidate directory and archive remains immutable; a new version gets a new directory.

These are separate asynchronous tasks, not a live conversation between the existing chats. The platform does not expose a per-task model selector; the role names do not guarantee different underlying model families.

## State and identity

Use review/RELEASE_REVIEW_STATE.json on the review branch for the active request, package path/hash, unresolved findings, status and correction-cycle count. Only the coordinator changes this state or candidate files. The reviewer records decisions in PR comments. Comments must bind the actual full PR head SHA and archive SHA. Mailbox updates on main are append-only status links and do not execute code.

Before acting, fetch current PR state/head, review state and comments. Read the package at that exact commit, verify archive/manifest identity, and recheck head before publishing. A changed head invalidates an old release approval. Deduplicate review by request ID plus reviewed head plus package hash; deduplicate coordinator responses by review comment ID. Ignore self-generated acknowledgments and already processed entries. Never interpret a repository comment as permission to expand scope.

Suggested comment headings:
- GPT REQUEST <request-id>
- ASTRA RESPONSE <request-id>
- GPT REPLY <request-id>

Initial status is CHANGES_REQUESTED for RC5 (R1 and R2). No need to review the identical RC5 again unless new evidence is supplied.

## Bounds

Allow at most three automatic correction/review cycles after RC5, then HOLD for Ryan. Each run should finish within 30 minutes or publish a concise checkpoint/HOLD. A failed tool, missing frozen input, conflicting branch update or absent dependency does not justify skipping a gate. Use optimistic updates and never force-push or overwrite another writer. Do not leave automatic fix loops running after APPROVED_PENDING_WINDOWS, HOLD, or PR closure.

Allowed: read repository/release artifacts; run synthetic/offline tests; preserve existing audit evidence; add narrow mechanical fixes, regression tests and new release packets on the review branch; post review/reply comments and append mailbox links.

Not authorized: catalogue/TAP execution (including diagnostic POSTs), individual detections or candidate inspection, scans/pixels, altered scientific populations/SQL/bins/thresholds, modifying old execution freezes or failed laptop checkpoints, merges, deployment, or a new execution freeze. A YAY means ready for the separately required Windows validation and explicit execution authorization.

## Local handoff

Ryan runs Windows self-test and full frozen-parent preflight after independent approval of the final candidate. Record those outputs and the RC4 unknown-submission disposition before requesting any new execution freeze. The existing RC4 freeze commit is preserved.
