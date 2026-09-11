# GPT REQUEST v095a-rc6-release-review

RC6 is correction cycle 1 after Astra RC5 NAY comment `5626606472`. Review the immutable RC6 package and archive.

Archive SHA-256 (decoded ZIP): `5084519b79b4cd55f28fef5bee0e24fc77fc1dcac1baa1676ab8e03902bbb651`
Archive transport manifest: `review/releases/v095a-rc6/archive_parts.json` (concatenate listed base64 parts in order, then standard base64 decode)
Archive transport SHA-256: `cb53deb74848cd058847e5188aaaf4548fcd6bcdcb140509fa37b9b884d83cc7`
Contract SHA-256: `d38b0daace296b6e1317dd642c9d446883209e8ad85d1b727774c72b05b4d8c1`
Release manifest SHA-256: `a0047c0825f9da11bbdf61c5dcbc2706d00657373ce572202a94b6cc7cf80a9e`

Check R1/R2 specifically: immediate sanitized header persistence through body failure/deadline; canonical receipt-envelope binding; state-dependent semantic validation against status/Location/job URL/disposition; mandatory completed-checkpoint evidence; publication revalidation. Also independently confirm SQL/bins/population/permissions remain unchanged and no path can automatically resubmit an uncertain/rejected submission.

The exact review head is bound by the PR request comment posted after the atomic candidate commit. No catalogue execution or execution freeze is authorized.
