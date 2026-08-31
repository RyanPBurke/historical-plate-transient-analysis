from pathlib import Path

import pytest

from transient_pipeline.poss1 import VI25Record


def rec297():
    return VI25Record(
        recno=297,
        poss="413",
        mlp="297",
        obs="1951-11-04",
        fobs="0-11-05",
        obse="23:00",
        obso="22:45",
        eexp_min=60.0,
        oexp_min=10.0,
        ra_icrs="01 52 17.1",
        dec_icrs="+30 43 12",
    )


def rec523():
    return VI25Record(
        recno=523,
        poss="313",
        mlp="523",
        obs="1951-08-07",
        fobs="0-08-08",
        obse="00:41",
        obso="00:26",
        eexp_min=50.0,
        oexp_min=10.0,
        ra_icrs="23 19 19.0",
        dec_icrs="+12 47 13",
    )


class Resp:
    def __init__(self, content, url):
        self.content = content
        self.url = url
        self.headers = {"Content-Type": "application/octet-stream"}
        self.status_code = 200


def hhh_bytes(region, plate, ra, dec, date_obs):
    cards = [
        "SIMPLE  =                    T".ljust(80),
        f"REGION  = '{region:<8}'           / GSSS".ljust(80),
        f"PLATEID = '{plate:<8}'           / GSSS".ljust(80),
        f"DATE-OBS= '{date_obs}'".ljust(80),
        f"PLATERA = {ra:20.12f}".ljust(80),
        f"PLATEDEC= {dec:20.12f}".ljust(80),
        "XPIXELS =                14000".ljust(80),
        "YPIXELS =                13999".ljust(80),
        "END".ljust(80),
    ]
    body = "".join(cards).encode("ascii")
    return body + b" " * max(0, 2880 - len(body))


def test_xe296_known_182arcsec_nominal_offset_is_diagnostic_not_failure(monkeypatch, tmp_path):
    import transient_pipeline.poss1_skyview as sv

    descriptor = (
        b"<Survey>\n"
        b"<ShortName>DSS1R,DSS1 Red</ShortName>\n"
        b"<ImageFactory>skyview.survey.DSSImageFactory</ImageFactory>\n"
        b"<FilePrefix>https://skyview.gsfc.nasa.gov/surveys/dss/</FilePrefix>\n"
        b"<Image>xe296 28.0155954649 30.7367699255 1951.843</Image>\n"
        b"</Survey>" + b" " * 1000
    )
    hhh = hhh_bytes("XE296", "06S2", 28.0155954649, 30.7367699255, "1951-11-04T07:00:00")
    tile = b"\xDD\x99" + b"\x00" * 100

    class FakeSession:
        def __init__(self, *a, **k):
            pass

        def request(self, method, url, validator=None, **kwargs):
            if url.endswith("dss1r.xml.gz"):
                r = Resp(descriptor, url)
            elif url.endswith("xe296.hhh"):
                r = Resp(hhh, url)
            elif url.endswith("xe296.00"):
                r = Resp(tile, url)
            else:
                raise AssertionError(url)
            if validator:
                validator(r)
            return r

    monkeypatch.setattr(sv, "ValidatedSession", FakeSession)
    result = sv.fallback_identity(
        record=rec297(),
        band="E",
        stage="test",
        job_key="POSS-I:413:E:rec297",
        attempt=1,
        cache_dir=tmp_path,
        evidence=None,
        primary_failure="stsci timeout",
    )

    assert result["identity_status"] == "validated"
    assert result["finder_region"] == "XE296"
    assert result["finder_plate_id"] == "06S2"
    assert result["skyview_descriptor_nominal_center_sep_arcsec"] == pytest.approx(182.5, abs=0.2)


def test_hhh_wrong_observing_night_date_is_terminal_identity_mismatch(monkeypatch, tmp_path):
    import transient_pipeline.poss1_skyview as sv

    descriptor = (
        b"<Survey>\n"
        b"<ShortName>DSS1B,DSS1 Blue</ShortName>\n"
        b"<ImageFactory>skyview.survey.DSSImageFactory</ImageFactory>\n"
        b"<FilePrefix>https://skyview.gsfc.nasa.gov/surveys/dss2/</FilePrefix>\n"
        b"<Image>xo/xo522 349.829333647 12.7870790553 1951.600</Image>\n"
        b"</Survey>" + b" " * 1000
    )
    hhh = hhh_bytes("XO522", "A3M1", 349.829333647, 12.7870790553, "1951-08-06T08:43:00")

    class FakeSession:
        def __init__(self, *a, **k):
            pass

        def request(self, method, url, validator=None, **kwargs):
            r = Resp(descriptor if url.endswith("dss1b.xml.gz") else hhh, url)
            if validator:
                validator(r)
            return r

    monkeypatch.setattr(sv, "ValidatedSession", FakeSession)
    with pytest.raises(ValueError, match="observing-date mismatch"):
        sv.fallback_identity(
            record=rec523(),
            band="O",
            stage="test",
            job_key="POSS-I:313:O:rec523",
            attempt=1,
            cache_dir=tmp_path,
            evidence=None,
            primary_failure="stsci timeout",
        )


def test_publication_queue_all_31_regions_map_from_vi25_mlp():
    from transient_pipeline.poss1 import load_vi25_records, queue_poss_jobs
    from transient_pipeline.poss1_skyview import expected_region_for_vi25

    records = load_vi25_records("research/poss1_plate_metadata.csv")
    jobs = list(queue_poss_jobs("research/production_sub5_queue_2026-08-20.csv"))
    assert len(jobs) == 31

    mismatched_row_ids = set()
    for exposure_id, payload in jobs:
        rec = records[int(payload["recno"])]
        region = expected_region_for_vi25(rec, payload["band"])
        assert region.startswith("X" + payload["band"])
        assert region[2:] == f"{int(rec.mlp) - 1:03d}"
        if int(rec.mlp) != int(rec.recno):
            mismatched_row_ids.add(rec.recno)

    assert mismatched_row_ids == {726, 742, 754, 760}


def test_missing_skyview_descriptor_region_is_accounted_as_pixels_unavailable(monkeypatch, tmp_path):
    import transient_pipeline.poss1_skyview as sv

    descriptor = (
        b"<Survey>\n"
        b"<ShortName>DSS1B,DSS1 Blue</ShortName>\n"
        b"<ImageFactory>skyview.survey.DSSImageFactory</ImageFactory>\n"
        b"<FilePrefix>https://skyview.gsfc.nasa.gov/surveys/dss2/</FilePrefix>\n"
        b"<Image>xo/xo196 32.23 42.71 1953.998</Image>\n"
        b"<Image>xo/xo198 47.35 42.48 1957.968</Image>\n"
        b"</Survey>" + b" " * 1200
    )

    record = VI25Record(
        recno=198,
        poss="449",
        mlp="198",
        obs="1951-12-21",
        fobs="0-12-22",
        obse="20:12",
        obso="19:55",
        eexp_min=60.0,
        oexp_min=10.0,
        ra_icrs="02 39 17.7",
        dec_icrs="+42 37 43",
    )

    class FakeSession:
        def __init__(self, *a, **k):
            pass

        def request(self, method, url, validator=None, **kwargs):
            r = Resp(descriptor, url)
            if validator:
                validator(r)
            return r

    monkeypatch.setattr(sv, "ValidatedSession", FakeSession)
    result = sv.fallback_identity(
        record=record,
        band="O",
        stage="test",
        job_key="POSS-I:449:O:rec198",
        attempt=1,
        cache_dir=tmp_path,
        evidence=None,
        primary_failure="stsci timeout",
    )

    assert result["identity_status"] == "catalogue_identified_pixels_unavailable"
    assert result["eligible_for_science"] is False
    assert result["finder_region"] == "XO197"
    assert result["skyview_descriptor_image_count"] == 0
    assert Path(result["archive_unavailable_provenance_sidecar"]).exists()
