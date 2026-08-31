# POSS-I identity / availability closure — v0.2.8

Date: 2026-08-21

## Scope

This freeze closes physical-plate identity and digital-pixel availability
for **all 40 unique POSS-I physical exposures** appearing in the
authoritative 74-row <=5-minute production denominator.

The authoritative production queue is:

`research/production_sub5_queue_2026-08-20.csv`

SHA256:

`b044684fef65437a352edd28eafd21d668640bbec50cd0bc95f92e3529d0d77c`

## Accounting

- authoritative temporal pairs: **74**
- POSS-involving pair rows: **47**
- unique POSS physical exposures: **40**
- physical identity validated / detector-eligible: **37**
- catalogue identified but digital pixels unavailable: **3**
- identity execution failures: **0**

## Pixels unavailable

1. `POSS-I:449:O:rec198` -> `XO197`
2. `POSS-I:832:E:rec760` -> `XE760`
3. `POSS-I:988:O:rec207` -> `XO206`

These three remain part of the denominator. Archive/pixel unavailability is
**not** a scientific zero or non-detection.

## Lineage

The v0.2.7 identity freeze remains immutable:

`59c2db6c2c43266bc2af693ff4c6efe1199db409ed912cfa324cadc10793ddb2`

It accounts for 31 physical POSS exposures.

v0.2.8 adds the nine previously omitted development-revalidation exposures
under the same reviewed physical-identity policy. All nine jobs completed;
eight were validated and O988/rec207 was catalogue identified with pixels
unavailable.

The authoritative science cohort labels were not altered.

## Duplicate POSS number 1023

The two physical O-band records remain distinct:

- `POSS-I:1023:O:rec675` -> `XO674`
- `POSS-I:1023:O:rec799` -> `XO799`

No bare `POSS-I:1023:O` identity is publication-safe.

## Evidence

Evidence verification at freeze:

- verified artifacts: **478**
- errors: **0**

## Detector

**No transient detector was run as part of this identity freeze.**

The next gate is pixel/FITS provenance reconciliation against these frozen
physical identities. Old exploratory detector dispositions must not be
silently promoted unless their exact physical plate and pixel provenance
matches this freeze.

Snapshot ID:

`8dc070b9df3febaa5db3585408e1fe88e9b3b9d71d436ddba16a71081b066d0e`

Manifest SHA256:

`56025ac7d0686be332fb0590411d097f642d668cd36c26c8ceb2f97924f9d36e`
