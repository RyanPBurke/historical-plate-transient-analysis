# POSS-I primary Plate Finder non-resolution fallback correction — v0.2.6

Date: 2026-08-21
Science analysis performed: **No**
Detector changes: **None**
Frozen scientific thresholds changed: **None**

## Trigger

After the v0.2.5 identity/availability run, all 31 prospective POSS-I jobs reached checkpoint status `succeeded`, but six had `identity_status=no_unique_platefinder_match` rather than a validated identity or the frozen XO197 archive-unavailability classification:

- `POSS-I:449:O:rec198`
- `POSS-I:782:E:rec514`
- `POSS-I:832:E:rec760`
- `POSS-I:872:O:rec148`
- `POSS-I:875:E:rec521`
- `POSS-I:876:E:rec239`

The publication wrapper refused to proceed, as intended.

## Implementation finding

In v0.2.5, a retryable STScI Plate Finder transport/archive failure entered the validated SkyView raw-DSS fallback, but a syntactically valid Plate Finder response for which `select_candidate()` returned no unique identity match completed immediately as `no_unique_platefinder_match`.

That branch therefore bypassed the already validated alternate identity source. A primary metadata service's inability to resolve one unique plate is **primary-source non-resolution**, not a physical-identity contradiction and not a scientific zero.

## v0.2.6 correction

When the STScI Plate Finder response is valid but yields no unique candidate, v0.2.6 now:

1. preserves the Plate Finder response hash, candidate count, and candidate diagnostics;
2. records `stsci_platefinder_resolution_status=no_unique_platefinder_match`;
3. invokes the same frozen SkyView raw-DSS identity fallback used after retryable STScI failure;
4. requires the unchanged SkyView identity checks (VI/25-derived region, descriptor identity, HHH REGION/PLATEID/date/centre consistency, and raw DD99 tile presence);
5. leaves the separately frozen `XO197` archive-unavailability policy unchanged.

No detector is executed by this stage.

## State migration

The v0.2.6 migration is deliberately narrow. It refuses to modify the checkpoint unless it contains exactly:

- 31 succeeded jobs;
- 25 `validated` + detector-eligible identities; and
- exactly the six reviewed `no_unique_platefinder_match` jobs listed above.

Before modification it creates a SQLite backup and an audit JSON containing the original six rows and results. It then requeues only those six and clears their stale result payloads.

## Interpretation

This is an implementation/control-flow correction to identity-source escalation. It does not change the prospective cohort, timing gates, detector, matching radii, recurrence/static vetoes, or denominator policy.
