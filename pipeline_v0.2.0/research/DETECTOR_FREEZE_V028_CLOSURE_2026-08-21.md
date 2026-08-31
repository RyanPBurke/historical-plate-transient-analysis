# Detector freeze closure — v0.2.8

## Detector

Source:

`src/transient_pipeline/detector.py`

SHA256:

`709da8d7a7972b15808d70a1e4dbffa0fd0fee864a81d954f74fe4a5f5af25e7`

Frozen method SHA256:

`2cb3cabd573d7af99399899f2ccecd3002be90297e55bb0e0dcdd9dea1d0c4c1`

## Frozen semantics

- Gaussian local-background sigma: **8 px**
- residual: image minus Gaussian-filtered image
- centre: median of finite residuals
- robust sigma: **1.4826 × MAD**
- both polarities through absolute centred residual
- threshold: **strictly >4 robust sigma**
- local-maximum window: **7 px**
- edge exclusion: **30 px**
- broad diagnostic radius: **10 arcsec**
- strict registered coincidence gate: **3 arcsec**

The edge mask is applied after local-maximum/threshold construction.

## Conformance

- deterministic synthetic array cases: **10 passed**
- independent reference equivalence: **10/10**
- opposite polarities recovered: **passed**
- edge injections rejected: **passed**
- finite/NaN handling exercised: **passed**
- synthetic FITS/WCS end-to-end: **passed**
- existing repository tests: **passed**

No historical science pixel was analysed during this freeze.

## Science execution boundary

- physical POSS exposures: **40**
- detector-eligible identities: **37**
- identity-cache pixels presently linked: **27**
- require clean acquisition/reacquisition: **10**
- pixels unavailable / no detector: **3**

The three unavailable exposures remain in the denominator and are not
scientific non-detections.

Old exploratory detector dispositions are not reused.

Snapshot ID:

`e3a9b42eaf58027171bb5449533e8bc413672acae7881d9641884363fb2aef7a`

Manifest SHA256:

`4d66c8f7099ece364053a451f15688ba7d2105c8a3b112d392e8e7a4a6c97c06`
