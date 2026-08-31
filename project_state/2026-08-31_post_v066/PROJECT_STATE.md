# Historical Plate Transient Analysis
## Post-v066 / Pre-registration checkpoint

Checkpoint date: 2026-08-31

This checkpoint records the project state after completion of the
supplemental Gaia DR3 reference acquisition stage v066 and before any
Gaia-based local astrometric registration or subsequent candidate
adjudication.

No astrometric registrations had been run at this checkpoint.
No candidate disposition was changed by v063-v066.
Science positives remained 0 at the existing frozen adjudication state;
this is NOT a post-registration scientific null result.

## Wide-census detector state

v056 detector execution:

- detector tiles: 6,293
- accepted detector detections/candidates: 5,083,325
- raw cross-observatory associations <=10 arcsec: 512,788
- raw cross-observatory associations <=3 arcsec: 185,532
- exposure pairs with <=10 arcsec associations: 33/33
- exposure pairs with <=3 arcsec associations: 32/33

A detection is one detector candidate on one plate/archive.
An association is a positional pairing between detections from the two
observatory sides of a contemporaneous exposure pair. Associations are
not unique physical events.

## Population controls v062

- observed <=3 arcsec associations: 185,532
- shifted-control mean <=3 arcsec: 17,165.50
- observed/control ratio <=3 arcsec: 10.8084
- observed <=10 arcsec associations: 512,788
- shifted-control mean <=10 arcsec: 190,525.94
- observed/control ratio <=10 arcsec: 2.6914

These excesses are not themselves transient detections. They motivate
the frozen target-independent local astrometric-registration stage.

## Gaia acquisition

v064 completed:
- ordinary base cells: 5,418 / 5,418
- resolved ordinary leaf queries: 6,651
- cached ordinary rows: 111,593,914
- HPM pair queries: 24 / 24
- cached HPM rows: 7
- registrations run: 0

v065 completeness correction:
- corrected ordinary J2016 margin: 125.4 arcsec
- registration-reference candidate domain: 30.25 arcmin
- corrected HPM margin: 915 arcsec
- required candidate-domain cells: 12,398
- new full cells: 6,980
- existing-leaf annulus queries: 6,651
- supplemental ordinary roots: 13,631
- corrected HPM pair queries: 33

v066 completed:
- ordinary supplemental roots: 13,631 / 13,631
- resolved ordinary leaf queries: 13,916
- cached ordinary rows: 52,453,208
- HPM pair queries: 33 / 33
- cached HPM rows: 9
- compressed v066 cache size at completion: 4.36 GiB
- astrometric registrations run: 0
- candidate dispositions: NONE
- science positives at existing frozen state: 0
- stage status: COMPLETE

## Authoritative frozen artefacts

### Candidate adjudication policy v002

Authoritative frozen copy:

pipeline_v0.2.0/frozen_stage_bundles/match3_method_freeze_v047_bundle/
candidate_adjudication_policy_v002.json

SHA256:
eb8512724b2ef23b3ee88e5ffcfab8088144c984f0b75adb7b68e87198cb4cbd

The later/live file:

pipeline_v0.2.0/config/candidate_adjudication_policy_v002.json

is intentionally retained but is not byte-identical.

Live/config SHA256:
3fc40ebab3b9e3c6e846d39f0c71abefb84a2994dde0a7692707aa9e9154dca7

### Post-detector adjudication contract v001

pipeline_v0.2.0/research/prospective_freezes/
wide_census_postdetector_adjudication_contract_v001.json

SHA256:
1215400b989b187e87ceee27237fd2faf7ccff80dd57632158e06cbed7add2ad

The v057 freeze/result record is a separate artefact:

project_state/2026-08-31_post_v066/compact_products/
wide_census_postdetector_adjudication_freeze_v057.json

Result SHA256:
fbdc7b9c2a28876120ce1d5e667e4b89327bedf6cabaf7a5bc431a56c47de507

### Gaia corrective acquisition contract v002

pipeline_v0.2.0/research/prospective_freezes/
wide_census_gaia_reference_acquisition_contract_v002.json

SHA256:
458a043dfbdda8dbb853cbae77c269ff17a586c0ddb2fdcf7ac0388ee57ab3fc

## Next scientific stage

The next stage is offline Gaia-based, pair-wise local astrometric
registration.

The primary scientific question is:

How much of the v062 10.8084x raw <=3 arcsec association excess survives
target-independent local astrometric correction?

No registration, threshold retuning, or post-v066 adjudication should
precede this repository checkpoint.

