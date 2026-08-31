from __future__ import annotations

from types import SimpleNamespace

import transient_pipeline.poss1 as poss1
from transient_pipeline.checkpoint import Job


def record_xe513():
    return poss1.VI25Record(
        recno=514,
        poss="782",
        mlp="514",
        obs="1953-08-12",
        fobs="0-08-13",
        obse="22:10",
        obso="23:01",
        eexp_min=60.0,
        oexp_min=10.0,
        ra_icrs="19 42 47.6",
        dec_icrs="+12 20 25",
    )


def test_platefinder_no_unique_match_routes_to_skyview(monkeypatch, tmp_path):
    rec = record_xe513()
    expected_start = poss1.vi25_start_utc(rec, "E")

    # Valid Plate Finder-shaped HTML but deliberately no plate rows.
    html = (
        "<html><body>survey name emulsion region epoch plate scale "
        + ("diagnostic filler " * 80)
        + "</body></html>"
    ).encode("ascii")

    class FakeSession:
        def __init__(self, *args, **kwargs):
            pass

        def request(self, method, url, **kwargs):
            assert method == "POST"
            assert url == poss1.PLATE_FINDER
            return SimpleNamespace(
                content=html,
                headers={"Content-Type": "text/html"},
                url=url,
            )

    called = {}

    def fake_fallback(**kwargs):
        called.update(kwargs)
        return {
            "identity_status": "validated",
            "identity_source": "skyview_raw_fallback",
            "eligible_for_science": True,
            "finder_plate_id": "TEST",
            "finder_region": "XE513",
        }

    monkeypatch.setattr(poss1, "ValidatedSession", FakeSession)
    monkeypatch.setattr(poss1, "skyview_fallback_identity", fake_fallback)

    worker = poss1.poss1_identity_worker(
        vi25_records={514: rec},
        evidence=None,
        cache_dir=tmp_path,
        stage="poss1-identity:prospective_production",
    )
    job = Job(
        job_key="POSS-I:782:E:rec514",
        stage="poss1-identity:prospective_production",
        status="running",
        attempts=4,
        payload={
            "band": "E",
            "recno": 514,
            "poss": "782",
            "ra_deg": 295.6983333333333,
            "dec_deg": 12.340277777777779,
            "queue_start_utc": expected_start.isoformat(),
            "queue_end_utc": (expected_start).isoformat(),
            "queue_duration_s": 3600.0,
        },
        result=None,
        last_error=None,
    )

    result = worker(job)

    assert called["job_key"] == job.job_key
    assert called["record"] == rec
    assert called["band"] == "E"
    assert called["expected_plate_id"] is None if "expected_plate_id" in called else True
    assert called["primary_failure"].startswith("stsci_platefinder_no_unique_match:")
    assert result["identity_status"] == "validated"
    assert result["identity_source"] == "skyview_raw_fallback"
    assert result["stsci_platefinder_resolution_status"] == "no_unique_platefinder_match"
    assert result["finder_candidate_count"] == 0
    assert result["finder_response_sha256"]
    assert result["finder_diagnostics_json"] == "[]"


def test_platefinder_nonresolution_preserves_archive_unavailable_result(monkeypatch, tmp_path):
    rec = record_xe513()
    expected_start = poss1.vi25_start_utc(rec, "E")
    html = (
        "<html><body>survey name emulsion region epoch plate scale "
        + ("diagnostic filler " * 80)
        + "</body></html>"
    ).encode("ascii")

    class FakeSession:
        def __init__(self, *args, **kwargs):
            pass
        def request(self, method, url, **kwargs):
            return SimpleNamespace(content=html, headers={"Content-Type": "text/html"}, url=url)

    monkeypatch.setattr(poss1, "ValidatedSession", FakeSession)
    monkeypatch.setattr(
        poss1,
        "skyview_fallback_identity",
        lambda **kwargs: {
            "identity_status": "catalogue_identified_pixels_unavailable",
            "identity_source": "vi25_plus_primary_stsci_failure_and_skyview_gap",
            "eligible_for_science": False,
            "finder_region": "XE513",
        },
    )

    worker = poss1.poss1_identity_worker(
        vi25_records={514: rec}, evidence=None, cache_dir=tmp_path,
        stage="poss1-identity:prospective_production",
    )
    job = Job(
        job_key="POSS-I:782:E:rec514", stage="poss1-identity:prospective_production",
        status="running", attempts=1,
        payload={
            "band": "E", "recno": 514, "poss": "782",
            "ra_deg": 295.6983333333333, "dec_deg": 12.340277777777779,
            "queue_start_utc": expected_start.isoformat(),
            "queue_end_utc": expected_start.isoformat(),
            "queue_duration_s": 3600.0,
        },
        result=None, last_error=None,
    )
    result = worker(job)
    assert result["identity_status"] == "catalogue_identified_pixels_unavailable"
    assert result["eligible_for_science"] is False
    assert result["stsci_platefinder_resolution_status"] == "no_unique_platefinder_match"
