# POSS-I SkyView identity-gate correction — v0.2.4 — 2026-08-20

This is an implementation/provenance correction only. It does not change the frozen transient detector, time gates, recurrence veto, GPS1 veto, strict 3-arcsec cross-observatory criterion, or publication cohort.

## Why v0.2.3 was invalid for unresolved fallback jobs

v0.2.3 introduced two overly strict identity assertions that were not part of the scientific protocol:

1. It required VI/25 `MLP == recno`. `recno` is the VizieR row identifier; `MLP` is the field used to map to the DSS region sequence. Legitimate prospective rows include `rec726 / MLP727`, `rec754 / MLP755`, `rec760 / MLP761`, and `rec742 / MLP743`.
2. It required the VI/25 nominal ICRS field pointing to agree with SkyView/GSSS `PLATERA/PLATEDEC` to 5 arcsec. These quantities are not equivalent. The already independently identified first prospective plate, VI/25 rec297 / POSS 413 E, has nominal centre `(28.07125, 30.72)` while the validated GSSS plate XE296 / 06S2 has `(28.0155954649, 30.7367699255)`, a separation of about 182.5 arcsec.

Because exceptions from those assertions were classified as terminal data/logic errors, the v0.2.3 run produced terminal execution states rather than retryable archive states. Those states are not scientific negatives.

## v0.2.4 identity logic

- DSS region is derived from VI/25 `MLP`: `X{band}{MLP-1}`. `recno` is retained only as the VizieR row identifier.
- SkyView descriptor must contain exactly one matching region and use `skyview.survey.DSSImageFactory`.
- Descriptor nominal-centre separation from VI/25 is retained as a diagnostic with only a broad 1-degree sanity bound.
- Descriptor epoch is checked coarsely against the VI/25 observing date (14-day tolerance for rounded decimal epoch metadata).
- Raw HHH must match the exact expected `REGION`, contain a non-empty `PLATEID`, and its solved centre must agree with the descriptor centre within 5 arcsec.
- HHH observing-night calendar date must equal VI/25 `Obs`. HHH clock is deliberately not used as exposure-start authority because a verified control (XO522/A3M1) demonstrates minute-scale disagreement while STScI Plate Finder and VI/25 identify the same physical plate.
- If STScI Plate Finder resolved a physical plate before forced extraction failed, exact `REGION` and `PLATEID` agreement with SkyView remains mandatory.
- Raw H-compressed availability probe remains mandatory.

The strict five-plate STScI/SkyView pixel-equivalence control remains unchanged: 5/5 PASS across both POSS-I E and O, identity orientation, zero offset, and zero pixel difference.

No transient detection is performed by the identity preflight or the checkpoint repair.
