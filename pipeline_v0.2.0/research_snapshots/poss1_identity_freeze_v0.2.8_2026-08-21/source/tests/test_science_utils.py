from transient_pipeline.timegate import exposure_relation
from transient_pipeline.astrometry import propagate_gps1_to_epoch, angular_sep_arcsec


def test_actual_overlap_pair_13623_bi05607():
    r = exposure_relation(
        "1952-08-14T20:51:12+00:00", "1952-08-14T21:31:12+00:00",
        "1952-08-14T20:41:28.299988+00:00", "1952-08-14T21:41:28.299988+00:00",
    )
    assert r.overlap_seconds == 2400.0
    assert r.overlaps


def test_gps1_pmra_includes_cos_dec():
    ra, dec = propagate_gps1_to_epoch(290.0, 30.0, 100.0, -50.0, 1952.6198)
    dt = 1952.6198 - 2010.0
    assert abs(dec - (30.0 + (-50.0)*dt/3.6e6)) < 1e-12
    # Propagating then separating from itself must be zero to numerical precision.
    assert angular_sep_arcsec(ra, dec, ra, dec) < 1e-6
