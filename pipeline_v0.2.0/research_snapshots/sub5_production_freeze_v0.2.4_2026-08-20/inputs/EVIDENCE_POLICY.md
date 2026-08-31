# Evidence retention policy

This project separates **scientific result state** from **evidence state**.

A job result says what the frozen analysis concluded. The evidence store records what exact external bytes and local scientific inputs supported that conclusion.

## Always retain

1. Queue/protocol/config/code/environment snapshot.
2. Input manifest hash for each stage.
3. SQLite jobs and append-only event logs.
4. Raw successful TAP/catalogue responses and exact query text.
5. Exact FITS inputs for every pixel analysis and SHA-256.
6. Result CSVs and hashes.
7. Failures as failures; never encode remote failure as absence.
8. Superseded results with invalidation reason.

## Native/full plate policy

Full plate scans can be hundreds of MB. Do not automatically duplicate every native plate merely because catalogue metadata were queried.

Download/preserve the native plate when:

- the algorithm uses the full plate pixels; or
- a candidate is promoted and the native plate is practical to retrieve; or
- the cutout service is not sufficiently stable/reproducible to reconstruct the exact quantitative input.

Otherwise retain the exact quantitative cutout plus stable native-plate identifier, DOI/DataLink, scan metadata and archive checksum.

## Checksums

SHA-256 is the project-level content identity. Archive-native FITS CHECKSUM/DATASUM values are preserved in addition where available.
