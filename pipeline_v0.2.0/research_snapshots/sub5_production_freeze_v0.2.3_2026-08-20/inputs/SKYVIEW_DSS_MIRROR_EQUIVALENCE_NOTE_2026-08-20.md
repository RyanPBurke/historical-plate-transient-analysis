# SkyView raw DSS mirror equivalence validation — 2026-08-20

## Purpose

This note records the pre-production validation used to justify NASA/GSFC SkyView's raw DSS plate store as an alternate byte source when the STScI DSS Plate Finder/extraction CGI is unavailable. This is an implementation/provenance change only. The frozen scientific detector, thresholds, queue, time gates, recurrence veto, GPS1 veto, strict 3.0 arcsec criterion, and no-result-dependent-stopping rule are unchanged.

## Control reader

The current SkyView JAR retrieved from `https://skyview.gsfc.nasa.gov/jar/skyview.jar` was preserved locally and had SHA256:

`2b949f68d73899cd63b2f600f60f6c5dfd1795532ed29b6ea986f71f83d36afe`

Its published `skyview.survey.DSSImage` implementation was used to read H-compressed raw DSS plate tiles. The reader itself is not required by the v0.2.3 identity fallback; its role here is to establish pixel equivalence between the two archive routes.

## Five independent physical-plate controls

For each already-successful STScI POSS-I preflight control, the exact physical `REGION` and `PLATEID` were required to match the SkyView `.hhh` plate header. The raw SkyView tiles were then decoded and the rectangle defined by the STScI FITS `CNPIX1`, `CNPIX2`, `NAXIS1`, and `NAXIS2` was compared value-for-value.

| Exposure | Band | REGION / PLATEID | Pixels compared | Orientation | Offset | Max abs difference | Result |
|---|---|---|---:|---|---|---:|---|
| POSS-I:236:E:rec425 | E/red | XE424 / 08M9 | 280,900 | identity | 0,0 | 0 | PASS |
| POSS-I:313:O:rec523 | O/blue | XO522 / A3M1 | 795,663 | identity | 0,0 | 0 | PASS |
| POSS-I:368:E:rec192 | E/red | XE191 / 07WI | 280,900 | identity | 0,0 | 0 | PASS |
| POSS-I:372:O:rec455 | O/blue | XO454 / A3K9 | 795,663 | identity | 0,0 | 0 | PASS |
| POSS-I:407:E:rec246 | E/red | XE245 / 08BI | 280,900 | identity | 0,0 | 0 | PASS |

Strict equivalence result: **5/5 PASS**. Every compared pixel was identical; no flip, shift, rescaling, or intensity offset was required.

The machine-readable local control summary is:

`work/poss_preflight/skyview_equivalence_all5_v2/all5_equivalence_summary.json`

## Raw storage routes validated

POSS-I E/red controls were read from the raw SkyView DSS store:

`https://skyview.gsfc.nasa.gov/surveys/dss/xe###/`

POSS-I O/blue controls were read from the current SkyView DSS1B definition. The external survey manifest identified `surveys/xml/dss1b.xml.gz`; that descriptor uses `skyview.survey.DSSImageFactory`, `FilePrefix=https://skyview.gsfc.nasa.gov/surveys/dss2/`, and image paths `xo/xo###`. The validated raw O/blue route is therefore:

`https://skyview.gsfc.nasa.gov/surveys/dss2/xo/xo###/`

The preserved external manifest and DSS1B descriptor retrieved during validation had SHA256 values:

- `survey.manifest`: `0fdf1796c9d15023b7fb7355203569e063c378ea34c25f29e15d90a010ebb325`
- `dss1b.xml`: `36e8b0380a60dba556091f0c4cb9ff5cb6fb33478918fc0f34a0500a35a40603`

## VI/25 → DSS region mapping used by the fallback

Across all five independent STScI controls, the VI/25 `MLP` field equals `recno`, and the corresponding GSSS region number is `MLP - 1`:

- rec425 → XE424
- rec523 → XO522
- rec192 → XE191
- rec455 → XO454
- rec246 → XE245

v0.2.3 does **not** accept this arithmetic mapping by itself. On fallback it additionally requires all of the following:

1. VI/25 `MLP` is numeric and exactly equals `recno`.
2. The appropriate current SkyView DSS1R/DSS1B descriptor contains exactly one image whose basename is the expected `XE###` or `XO###` region.
3. The descriptor image centre agrees with the VI/25 ICRS plate centre within 5 arcsec.
4. The raw SkyView `.hhh` header reports exactly the expected `REGION`.
5. The `.hhh` header contains a non-empty `PLATEID`.
6. The `.hhh` `PLATERA/PLATEDEC` centre agrees with the VI/25 ICRS plate centre within 5 arcsec.
7. If STScI Plate Finder had already returned a unique `REGION/PLATEID` before its extraction failed, the SkyView values must agree exactly with those STScI values.
8. A raw tile at `<region>.00` must be retrievable and begin with the H-compress `DD99` magic bytes.

Failure of any check is not converted into a scientific negative.

## Archive preference and fallback policy

v0.2.3 still prefers STScI. Each unresolved job first gets one bounded STScI Plate Finder/extraction attempt. Only a retryable STScI archive/network failure invokes SkyView. A successful but scientifically ambiguous STScI Plate Finder result (for example, no unique physical-plate match) is **not** bypassed by the fallback.

The SkyView fallback validates physical identity and raw pixel-store availability only. It does not run the frozen transient detector and does not silently manufacture a substitute FITS cutout. A later production pixel-retrieval step must preserve the raw SkyView provenance explicitly.

## Scientific status

No prospective transient detector was run during these controls. No prior scientific result changed. The purpose of this validation is solely to remove dependence on a persistently unavailable STScI CGI while preserving or strengthening the physical-plate identity standard.
