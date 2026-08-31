# Legacy evidence gaps at publication-mode freeze — 2026-08-20

This file deliberately records evidence that **was not** preserved by the exploratory v0.1 workflow. It prevents later reconstruction from being misrepresented as contemporaneous preservation.

## Known gaps

1. Pre-v0.2 APPLAUSE TAP decisions generally retained derived nearest-match/count results but not the byte-exact VOTable response or exact request metadata.
2. Pre-v0.2 GPS1 decisions generally retained derived rows/nearest propagated match but not the byte-exact VizieR CSV response.
3. Harvard/StarGlass successful pixel jobs are substantially stronger: exact FITS cutouts were cached and SHA-256 hashed. Earlier pre-cache historical Harvard results for 13623↔bi05607 were invalidated and superseded.
4. Target/control native APPLAUSE plate FITS were not systematically downloaded for every catalogue-level decision. Stable scan metadata and native scan access can be reacquired from frozen DR4; any backfill must be labelled as a later evidence reconstruction.
5. Some earlier POSS-I explorations used downloaded/forced FITS without a unified central artifact index. Existing files/checkpoints should be registered into v0.2 evidence where available rather than regenerated silently.
6. The entire 74-pair queue was not prospectively unseen before the 2026-08-20 protocol freeze. Prior touched rows are enumerated separately.

## Backfill policy

- Never fabricate missing historical response bytes or retrieval timestamps.
- If a frozen archive is re-queried to reconstruct evidence, label the record `backfill_retrieval` with the new retrieval time while preserving the original scientific result/checkpoint separately.
- Prefer verification against preserved derived values/hashes when backfilling.
- Previously analysed rows remain `development/revalidation`, even after perfect computational reruns.
