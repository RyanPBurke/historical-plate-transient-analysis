# RC4 local validation record

Prepared 2026-09-10. Release candidate; no execution freeze or Stage A catalogue run performed.

## Passed

- `python3 -m unittest -v test_v095a_rc4`: **44 tests passed**, including parser/completeness/binding failures, durable job resumption and retry limits, late completion, failed response evidence, corruption refusal, process locking and spawned slow-stream termination.
- `node test_sql_rc4.mjs`: **PASS** using PGlite 0.5.8 / PostgreSQL 18.3. Exact Q0/Q1/Q2 templates executed against synthetic local tables. All four science-key components were varied independently. Empty plates, absent bindings/keys, real NULL rows, error-bin boundaries, NaN/infinities, coordinate categories and processing multiplicity were checked. Removing the Q2 composite FILTER reproduces the old empty-plate defect.
- Byte comparison with the uploaded RC3 ZIP: **SQL and histogram JSON unchanged**.
- AST comparison with RC3: parent/population/query-field/batch/launch-instant constants and foundation_provenance, verify_v094z and build_parent_associations functions are unchanged.

Test environment: Linux, Python 3.12.14, Node.js and local WebAssembly PostgreSQL. The HTTP lifecycle is simulated; the deadline/lock tests spawn real local processes without sending network requests. npm dependency installation accessed the package registry. The Python and SQL test executions themselves made **zero catalogue/network calls**.

## Remaining release gates

- Independent release-specific review of RC4 code and contract.
- RC4 self-test and full preflight on the Windows project with its original proof archive and frozen parent files. The supplied successful RC3 preflight is not relabelled as an RC4 preflight.
- Explicit execution freeze and remote/local provenance verification before any Stage A catalogue submission.

No Windows PowerShell execution or live APPLAUSE TAP integration test is claimed. The local SQL engine is PostgreSQL 18.3, while the unchanged service language parameter is postgresql-9.6; the fixture is a regression check, not a certification of the remote service.

## Artifact identity

- Input RC3 ZIP SHA-256: `4e3620b356b622c46402c52467a80d2c5a3304de0a1403a2a20f97fde0e34210`
- RC4 contract SHA-256: `597322e7c10413fc34d4eca39bef013c026a5483633266efd8e74b6100e7e5c3`
- Frozen SQL SHA-256: `1e318f66a80453208e77c41ccb89b6340c29b639b53741b634a459d649308b21`
- Frozen bins SHA-256: `c4fd3724579f37b847c1a4549fb6c45066531efc3607b1e37eca0a5567366313`

release_manifest.sha256 covers every release file except itself. Runtime caches and development node_modules are excluded from the distributable handoff. The ZIP SHA-256 is reported with delivery because an archive cannot contain its own hash.
