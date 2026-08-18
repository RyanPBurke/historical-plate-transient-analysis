# Sources and method

## Launch catalogue

Event rows are extracted from the annual `1951 in spaceflight` through `1955
in spaceflight` tables. Those compilations cite contemporary NRL firing
summaries, Milton Rosen's *The Viking Rocket Story*, Soviet programme histories,
and specialist launch chronologies. The extraction retains the source-page URL
and raw date/time string for audit.

Annual expected totals are 61, 56, 88, 95, and 156 respectively (456 total).
Rows are validated against those totals. All are suborbital; therefore the
listed decay/impact date is normally the launch date.

## Plate catalogues

- **POSS-I:** VizieR catalogue VI/25, *Palomar Observatory Sky Survey Catalogue
  of Plates*, containing plate centres and observational metadata.
- **APPLAUSE:** DR4 tables accessed through the public TAP service. Exposure,
  archive, pointing, calibrated `ut_start`/`ut_end`, original recorded time,
  and duration are retained. Matching uses calibrated UT; the original time is
  retained only for provenance.
- **DASCH:** `dasch.wide_plates` and `dasch.narrow_plates` from the GAVO TAP
  service. The service exposes ObsCore timing, field centre, field of view and
  data-access identifiers.

## Pair/triplet construction

Two exposures are a discovery candidate when:

1. their midpoint separation is within the configured time threshold;
2. their approximate circular fields intersect; and
3. their archive/site labels are different.

Triplets are constructed by requiring all three pairwise links. This avoids a
chain in which A overlaps B and B overlaps C but A does not overlap C.

The bundle writes a strict 30-minute pair list and a broader six-hour
same-night list. Triplets use the six-hour discovery window because the current
public metadata yield no three-site set within 30 minutes. They are therefore
follow-up/negative-control opportunities, not simultaneous confirmations.

The generated matrix is a shortlist for pixel-level work, not a claim of
simultaneity. Historical timestamps can be imprecise; the original logbook and
plate jacket must be inspected before a candidate is promoted.

## Launch association screen

Launch/plate output is intentionally conservative. It identifies plates whose
exposure date falls within the configured date window of a launch. It does not
claim geometric visibility. Promotion requires launch-site coordinates,
trajectory/apogee, azimuth, observatory horizon and Sun geometry.

## Multiplicity analysis

For multiple transients on one plate, freeze the extraction configuration
before inspecting associations. Use one predetermined extraction per sky
position or an explicit repeated-measurement model, injection/recovery, and an
empirical plate-preserving null. Report plate-level multiplicity rather than
treating each extracted source as an independent trial.

## Public endpoints

- Annual launch pages: `https://en.wikipedia.org/wiki/1951_in_spaceflight`
  through `1955_in_spaceflight`.
- VizieR POSS-I catalogue: `https://vizier.cds.unistra.fr/viz-bin/asu-tsv?-source=VI/25&-out.all=1`
- APPLAUSE TAP: `https://www.plate-archive.org/tap/sync`
- GAVO TAP: `https://dc.g-vo.org/tap/sync`
- DASCH DR7 documentation: `https://dasch.cfa.harvard.edu/dr7/`
