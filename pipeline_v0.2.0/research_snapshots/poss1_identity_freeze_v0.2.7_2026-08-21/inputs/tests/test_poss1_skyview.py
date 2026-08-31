from pathlib import Path
import math

import pytest

from transient_pipeline.poss1 import VI25Record
from transient_pipeline.poss1_skyview import (
    angular_sep_arcsec,
    expected_region_for_vi25,
    hhh_identity,
    parse_skyview_descriptor,
    raw_plate_directory,
    sexagesimal_dec_deg,
    sexagesimal_ra_deg,
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


def test_expected_region_mapping_matches_validated_control():
    r = rec523()
    assert expected_region_for_vi25(r, "O") == "XO522"
    assert expected_region_for_vi25(r, "E") == "XE522"


def test_expected_region_uses_mlp_not_vizier_recno():
    r = VI25Record(
        recno=726, poss="985", mlp="727", obs="1954-02-24", fobs="0-02-25",
        obse="22:14", obso="22:58", eexp_min=40.0, oexp_min=12.0,
        ra_icrs="08 30 51.1", dec_icrs="-12 29 15",
    )
    assert expected_region_for_vi25(r, "E") == "XE726"
    assert expected_region_for_vi25(r, "O") == "XO726"


def test_parse_dss1b_descriptor_and_raw_path():
    raw = b'''<Survey>\n<ShortName>DSS1B,DSS1 Blue</ShortName>\n<ImageFactory>skyview.survey.DSSImageFactory</ImageFactory>\n<FilePrefix> https://skyview.gsfc.nasa.gov/surveys/dss2/ </FilePrefix>\n<Image>xo/xo522 349.82933 12.78708 1951.601</Image>\n</Survey>'''
    d = parse_skyview_descriptor(raw)
    assert d.image_factory == "skyview.survey.DSSImageFactory"
    assert d.file_prefix == "https://skyview.gsfc.nasa.gov/surveys/dss2/"
    assert len(d.images) == 1
    assert d.images[0].path == "xo/xo522"
    assert raw_plate_directory(band="O", region="XO522", descriptor_entry=d.images[0]).endswith("/dss2/xo/xo522")


def test_hhh_identity_cards():
    cards = [
        "SIMPLE  =                    T".ljust(80),
        "REGION  = 'XO522   '           / GSSS".ljust(80),
        "PLATEID = 'A3M1    '           / GSSS".ljust(80),
        "DATE-OBS= '1951-08-07T08:43:00'".ljust(80),
        "PLATERA =        349.829333647".ljust(80),
        "PLATEDEC=       12.7870790553".ljust(80),
        "XPIXELS =                14000".ljust(80),
        "YPIXELS =                13999".ljust(80),
        "END".ljust(80),
    ]
    raw = "".join(cards).encode("ascii") + b" " * (2880 - len("".join(cards)))
    ident = hhh_identity(raw)
    assert ident["region"] == "XO522"
    assert ident["plate_id"] == "A3M1"
    assert ident["plate_ra_deg"] == pytest.approx(349.829333647)
    assert ident["plate_dec_deg"] == pytest.approx(12.7870790553)


def test_vi25_center_matches_control_hhh_within_five_arcsec():
    ra = sexagesimal_ra_deg("23 19 19.0")
    dec = sexagesimal_dec_deg("+12 47 13")
    sep = angular_sep_arcsec(ra, dec, 349.829333647, 12.7870790553)
    assert sep < 5.0


class _Resp:
    def __init__(self, content, url="https://example.invalid/x"):
        self.content = content
        self.url = url
        self.headers = {"Content-Type": "application/octet-stream"}
        self.status_code = 200


def _hhh_bytes(region="XO522", plate="A3M1", ra=349.829333647, dec=12.7870790553):
    cards = [
        "SIMPLE  =                    T".ljust(80),
        f"REGION  = '{region:<8}'           / GSSS".ljust(80),
        f"PLATEID = '{plate:<8}'           / GSSS".ljust(80),
        "DATE-OBS= '1951-08-07T08:43:00'".ljust(80),
        f"PLATERA = {ra:20.12f}".ljust(80),
        f"PLATEDEC= {dec:20.12f}".ljust(80),
        "XPIXELS =                14000".ljust(80),
        "YPIXELS =                13999".ljust(80),
        "END".ljust(80),
    ]
    body = "".join(cards).encode("ascii")
    return body + b" " * max(0, 2880 - len(body))


def test_fallback_identity_validates_descriptor_hhh_and_hcompress(monkeypatch, tmp_path):
    import transient_pipeline.poss1_skyview as sv

    descriptor = b'''<Survey>\n<ShortName>DSS1B,DSS1 Blue</ShortName>\n<ImageFactory>skyview.survey.DSSImageFactory</ImageFactory>\n<FilePrefix>https://skyview.gsfc.nasa.gov/surveys/dss2/</FilePrefix>\n<Image>xo/xo522 349.829333647 12.7870790553 1951.60</Image>\n</Survey>''' + b' ' * 1000
    hhh = _hhh_bytes()
    tile = b"\xDD\x99" + b"\x00" * 100

    class FakeSession:
        def __init__(self, *a, **k):
            pass
        def request(self, method, url, validator=None, **kwargs):
            if url.endswith("dss1b.xml.gz"):
                r = _Resp(descriptor, url)
            elif url.endswith("xo522.hhh"):
                r = _Resp(hhh, url)
            elif url.endswith("xo522.00"):
                r = _Resp(tile, url)
            else:
                raise AssertionError(url)
            if validator:
                validator(r)
            return r

    monkeypatch.setattr(sv, "ValidatedSession", FakeSession)
    result = sv.fallback_identity(
        record=rec523(), band="O", stage="test", job_key="POSS-I:313:O:rec523",
        attempt=1, cache_dir=tmp_path, evidence=None,
        primary_failure="stsci timeout",
    )
    assert result["identity_status"] == "validated"
    assert result["identity_source"] == "skyview_raw_fallback"
    assert result["finder_region"] == "XO522"
    assert result["finder_plate_id"] == "A3M1"
    assert result["eligible_for_science"] is True
    assert result["skyview_probe_tile_magic"] == "dd99"
    assert Path(result["provenance_sidecar"]).exists()


def test_fallback_identity_rejects_stsci_plateid_disagreement(monkeypatch, tmp_path):
    import transient_pipeline.poss1_skyview as sv

    descriptor = b'''<Survey>\n<ShortName>DSS1B,DSS1 Blue</ShortName>\n<ImageFactory>skyview.survey.DSSImageFactory</ImageFactory>\n<FilePrefix>https://skyview.gsfc.nasa.gov/surveys/dss2/</FilePrefix>\n<Image>xo/xo522 349.829333647 12.7870790553 1951.60</Image>\n</Survey>''' + b' ' * 1000
    hhh = _hhh_bytes(plate="A3M1")

    class FakeSession:
        def __init__(self, *a, **k):
            pass
        def request(self, method, url, validator=None, **kwargs):
            r = _Resp(descriptor if url.endswith("dss1b.xml.gz") else hhh, url)
            if validator:
                validator(r)
            return r

    monkeypatch.setattr(sv, "ValidatedSession", FakeSession)
    with pytest.raises(ValueError, match="PLATEID disagreement"):
        sv.fallback_identity(
            record=rec523(), band="O", stage="test", job_key="POSS-I:313:O:rec523",
            attempt=1, cache_dir=tmp_path, evidence=None,
            primary_failure="forced extraction timeout",
            expected_plate_id="WRONG",
            expected_region="XO522",
        )
