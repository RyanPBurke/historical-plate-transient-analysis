from datetime import datetime, timezone
from transient_pipeline.poss1 import (
    FinderCandidate,
    VI25Record,
    legacy_decimal_clock_seconds,
    select_candidate,
    vi25_start_utc,
)


def record413():
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
    )


def test_vi25_pst_rollover_e():
    assert vi25_start_utc(record413(), "E") == datetime(1951, 11, 5, 7, 0, tzinfo=timezone.utc)


def test_vi25_pst_rollover_o():
    assert vi25_start_utc(record413(), "O") == datetime(1951, 11, 5, 6, 45, tzinfo=timezone.utc)


def test_dss_legacy_decimal_hour():
    assert legacy_decimal_clock_seconds("06:75:00") == 6.75 * 3600


def test_select_exact_06s2():
    rec = record413()
    candidates = [
        FinderCandidate("A33Z", "POSS-I O", "", 10.0, "XO296", "1951-11-04", "06:75:00", 1.01),
        FinderCandidate("06S2", "POSS-I E", "", 60.0, "XE296", "1951-11-04", "07:00:00", 1.70),
    ]
    selected, diag = select_candidate(
        candidates,
        record=rec,
        band="E",
        expected_start_utc=vi25_start_utc(rec, "E"),
        duration_min=60.0,
    )
    assert selected is not None
    assert selected.plate_id == "06S2"
    assert selected.region == "XE296"
    assert sum(d["identity_match"] for d in diag) == 1


def test_parse_platefinder_row():
    from transient_pipeline.poss1 import parse_platefinder_candidates
    raw = b'''<table><tr><th><input type="radio" name="plate_id" value="06S2"></th><td>POSS-E Red Plate</td><td>xx103aE + plexi<br>(POSS-I E)</td><td>60.0</td><td>XE296<br>(06S2)</td><td>1951-11-04 07:00:00</td><td>1.70</td><td>3.0</td><td>195.5</td></tr></table>'''
    rows = parse_platefinder_candidates(raw)
    assert len(rows) == 1
    assert rows[0].plate_id == "06S2"
    assert rows[0].region == "XE296"
    assert rows[0].exposure_min == 60.0


def test_all_prospective_queue_poss_times_match_vi25():
    from pathlib import Path
    from transient_pipeline.poss1 import load_vi25_records, queue_poss_jobs, vi25_duration_min
    root = Path(__file__).resolve().parents[1]
    records = load_vi25_records(root / "research" / "poss1_plate_metadata.csv")
    jobs = list(queue_poss_jobs(root / "research" / "production_sub5_queue_2026-08-20.csv", "prospective_production"))
    assert len(jobs) == 31
    for _, payload in jobs:
        record = records[payload["recno"]]
        assert str(record.poss) == str(payload["poss"])
        expected = vi25_start_utc(record, payload["band"])
        queue_start = datetime.fromisoformat(payload["queue_start_utc"].replace("Z", "+00:00"))
        assert abs((expected - queue_start).total_seconds()) <= 61.0
        assert abs(vi25_duration_min(record, payload["band"]) * 60.0 - payload["queue_duration_s"]) <= 1.0


def test_vi25_loader_includes_icrs_coordinates():
    from transient_pipeline.poss1 import load_vi25_records
    records = load_vi25_records("research/poss1_plate_metadata.csv")
    r = records[523]
    assert r.ra_icrs == "23 19 19.0"
    assert r.dec_icrs == "+12 47 13"
