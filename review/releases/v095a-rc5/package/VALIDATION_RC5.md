# RC5 local validation record

Prepared 2026-09-10. No catalogue/network calls were made during these tests.

RC5 adds transport-receipt evidence tests covering explicit 4xx rejection, ambiguous 2xx/3xx/5xx responses, valid 303 receipt, invalid/missing job location, and transport-failure partial bytes. Existing RC4 parser/lifecycle/lock tests are retained.

The SQL and histogram files are byte-for-byte unchanged from RC4; their SHA-256 values therefore remain unchanged. The frozen SQL fixture logic is unchanged and is not a new scientific modification.

Python regression suite: **51/51 PASS** on Linux/Python 3.12 in this build environment. No catalogue/network calls were made by the suite. Independent review and Windows preflight remain required before execution freeze.
