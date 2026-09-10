# Proposed release review workflow

Status: proposal only. No GitHub issue, PR, automation, comment, commit or execution freeze was created by this repair.

Use one release PR as the review unit, optionally linked from a standing project issue. A PR binds discussion to a diff and a specific commit and can carry automated test results. A mailbox issue alone does not wake either existing chat.

## Roles and triggers

- A coordinator handles the release branch, regression tests, evidence manifest and responses to findings.
- An independent reviewer assesses the exact commit and package hash, including the scientific permission boundary and failure semantics.
- A configured GitHub PR event automation responds to new commits and reviews. It must check the current head before acting; a comment is not proof that an old review still applies.
- Ryan performs the local Windows parent-data preflight and the separately approved execution/freeze step while those resources remain on his laptop.

The existing named Sol/Astra chats are not automatically connected by posting an issue. A configured coordinating task can invoke a separate reviewer run if delegation is authorized; otherwise a PR review request or prompt remains the handoff mechanism. Repository access and write permissions must be confirmed during setup.

## Minimal release packet

Record the full head commit, parent hashes, package SHA-256, test commands/results, scope of the permitted next execution, and explicit unresolved findings. Require reviewer output to name the exact reviewed commit and artifact hash and give YAY or NAY with concrete blockers.

Suggested states: DRAFT -> TESTED -> REVIEW_REQUESTED -> CHANGES_REQUESTED or APPROVED -> WINDOWS_PREFLIGHT_PASS -> EXECUTION_FREEZE_READY. Execution approval is specific to the named scientific stage and does not authorize later individual-source work.

## Loop controls

Only act on a new head commit or an unprocessed external review. Deduplicate by commit/event/review ID, ignore the coordinator's own status comments, and invalidate approval when the head changes. Limit automated correction/review to three cycles or a stated runtime budget, then report the unresolved blockers. Do not merge, push an execution freeze or submit catalogue jobs just because an automated code-review check passed.

A generic automated code review supplements the release review: it does not establish scientific validity, source blindness, or Windows parent-provenance replay.

## Available implementation routes

GitHub-integrated Codex reviews can be requested with @codex review once the repository is configured. PR-event automations can react to comments, reviews and commits where supported by the account and connector. Neither is activated by this document.

References:
- https://learn.chatgpt.com/docs/third-party/github
- https://learn.chatgpt.com/docs/automations
