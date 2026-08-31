# POSS-I identity/availability preflight v0.2.7 closure

**Frozen:** 2026-08-21  
**Prospective exposures:** 31  
**Pixel-validated / detector-eligible:** 29  
**Catalogue-identified, digital pixels unavailable:** 2  
**Execution failures at freeze:** 0  
**Evidence artifacts verified:** 447  
**Evidence errors:** 0  
**Transient detection performed by this freeze:** No

## Final identity accounting

The prospective POSS-I identity/availability preflight completed with all
31 exposure jobs in `succeeded` state. Twenty-nine exposures have validated
digital plate pixels and are eligible for subsequent detector execution.

Two physical exposures remain in the prospective denominator but are not
detector-eligible because validated digital pixels are unavailable:

1. `POSS-I:449:O:rec198` — deterministic region `XO197`.
   VI/25 identity is retained, but no exact current SkyView DSS1 descriptor
   product exists for the required region.

2. `POSS-I:832:E:rec760` — VI/25 MLP `761`, deterministic region `XE760`.
   The exact `XE760` descriptor entry exists, but the exact raw product
   `https://skyview.gsfc.nasa.gov/surveys/dss/xe760/xe760.hhh`
   returns HTTP 404. No neighbouring region is substituted.

These two exposures are archive-availability states, not scientific
non-detections.

## Corrected DSS-region interpretation

An earlier investigative narrative referred to the second unavailable
exposure as `XE759`. That interpretation was incorrect and is superseded.

The deterministic POSS-I DSS region mapping uses the VI/25 MLP lineage,
not the catalogue `recno` value directly. For
`POSS-I:832:E:rec760`, VI/25 records MLP `761`, yielding deterministic
region `XE760`. The final pipeline result, descriptor path, raw-HHH URL,
and archive-availability provenance are therefore internally consistent.

## Descriptor / raw-header positional policy

An initially proposed descriptor-to-HHH plate-centre equality gate was
empirically rejected. Pixel-equivalent controls demonstrated intrinsic
cross-source centre offsets of at least 357.680 arcsec.

Descriptor/HHH centre separation is therefore retained as diagnostic
provenance but is not a terminal identity criterion. Stronger independent
identity checks remain in force.

Suggested methods wording:

> An initially proposed cross-source positional identity check was
> empirically rejected after pixel-equivalent controls demonstrated
> intrinsic descriptor/header centre offsets of at least 357.7 arcsec.

## VI/25 and GSSS date semantics

VI/25 expresses an exposure within a two-date observing night and records
E/O start clocks in Pacific Standard Time. The historical GSSS raw headers
were empirically found to encode their `DATE-OBS` calendar date using at
least two conventions among pixel-equivalent POSS-I controls:

- the initial observing-night date; or
- the calendar date of the normalized UTC exposure start.

The hard HHH calendar-date identity check therefore admits only those two
independently defined encodings. It does not use a generic +/-1-day
tolerance.

GSSS `DATE-OBS` clock values are retained as provenance but are not used as
minute-accurate exposure-start authority. VI/25-derived normalized UTC
exposure intervals remain authoritative for temporal overlap calculations.

## Regression-fixture correction

The historical XE513 test fixture incorrectly contained E/O clock values
`20:15` / `19:55`. The authoritative VI/25 values are `22:10` / `23:01`.
The regression fixture was corrected before this freeze.

## Detector boundary

No transient detector was run during the identity-remediation or freeze
process.

Subsequent scientific analysis must:

- execute only against the 29 detector-eligible exposures;
- retain XO197 and XE760 in the prospective denominator;
- never treat archive unavailability as a scientific zero;
- calculate and record actual exposure-overlap intervals for every
  cross-observatory candidate pair rather than relying only on midpoint
  separation.
