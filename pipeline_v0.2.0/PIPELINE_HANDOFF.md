# Laptop pipeline handoff — 2026-08-20

## Scientific handoff point reached

APPLAUSE exposure 13623 / Harvard bi05607 is scientifically closed with no defensible promoted two-observatory transient. The one strict <=3 arcsec coincidence, source 40095480011876, remains chance-consistent and non-promoted.

The normalization/revalidation backlog caused by live archive instability is intentionally separate from the scientific conclusion. It can now be completed reproducibly by this laptop runner instead of via long interactive tool chains.

## First laptop objectives

1. Run `bootstrap.ps1`; all local tests must pass before live archive work.
2. Run `run_regression.ps1` while StarGlass is healthy. The two frozen numerical regressions must pass before bulk Harvard work.
3. Resolve `examples/strip5_normalized_source_ids.csv` through `resolve-applause`, then run the StarGlass stage for those 18 normalized survivors.
4. Import/rebuild the Strip 3, 6 and 7 survivor manifests and clear their Harvard revalidation backlog.
5. Recover exact Strip-4 normalized hard IDs with `gps1` once VizieR is stable.
6. Only after those regression/backlog runs are clean, expand the same job framework to the remaining canonical <=5-minute pair queue.

## Invariants

- Never convert a network/archive failure into a scientific zero.
- Never change frozen detector thresholds in response to candidate appearance.
- Record actual exposure overlap for every pair.
- Use explicit 3.2 arcsec for the recovered Hamburg recurrence-audit tolerance; retain the historical nominal-3.0 discrepancy in provenance.
- Strict registered/contemporaneous Harvard gate remains exactly 3.0 arcsec.
