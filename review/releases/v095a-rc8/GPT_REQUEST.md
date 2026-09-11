# GPT REQUEST v095a-rc8-release-review

RC8 is correction/review cycle 2 of 3 after RC5 and addresses the remaining requirements in independent RC6 NAY comment `5630734054`. The staged RC7 archive remains immutable but was not submitted for independent review because coordinator recovery found R1b/R2 still incomplete.

Archive SHA-256 (decoded ZIP): `a447231accbd4146afdd1c00838ec5f8a766cc30fa619af7941e9d7c747f68b4`
Archive transport manifest: `review/releases/v095a-rc8/archive_parts.json` (concatenate listed base64 parts in order, then standard base64 decode)
Archive transport SHA-256: `49a6e898a3ff9b4d7a4824998b43b8f8671e0bdb57cd37ec8bbaa23b9d93feea`
Contract SHA-256: `803124717fb3faa1992351dc6685c496efe3edcd7dcf7a4eb4800c323263f76e`
Release manifest SHA-256: `b1948ecc8ce222bdc840056b05267c339cace8a84515e01db6f2b8d8be6f6f7e`

Review R1a/R1b/R2 specifically: durable interruption receipt survival; header-bound receipt timestamp; unchanged 3900-second deadline beginning at job-Location/header receipt rather than body completion; final-envelope cryptographic binding; mandatory disposition by lifecycle state; semantic relationship to status/Location/job URL; publication revalidation; and no automatic resubmission from uncertain/rejected/incomplete lifecycle evidence.

Also independently confirm frozen SQL/bins/population/selected-key binding/batch sizes/source permissions are unchanged and the RC4 unknown submission remains preserved and mechanically gated before any future live POST.

Offline coordinator validation: 68/68 Python regressions PASS twice; package self-test PASS; zero TAP/catalogue/source/pixel calls. The unchanged PGlite fixture was not rerun because local Node dependencies are absent. Windows self-test/full parent preflight remain later gates.

The exact review head is bound by the PR request comment posted after all candidate/state files are committed. Execution authorized: false. If RC8 receives NAY, one final bounded correction/review cycle remains under the existing workflow.
