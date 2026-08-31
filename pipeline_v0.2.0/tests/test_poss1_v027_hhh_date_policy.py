from __future__ import annotations

import ast
import inspect
import textwrap

import transient_pipeline.poss1 as poss1
import transient_pipeline.poss1_skyview as skyview


def rec(*, recno, poss, obs, fobs, obse, obso):
    return poss1.VI25Record(
        recno=recno,
        poss=str(poss),
        mlp=str(recno),
        obs=obs,
        fobs=fobs,
        obse=obse,
        obso=obso,
        eexp_min=45.0,
        oexp_min=12.0,
        ra_icrs="00 00 00",
        dec_icrs="+00 00 00",
    )


def allowed_dates(record, band):
    start = poss1.vi25_start_utc(record, band)
    return start, {
        record.obs.strip(),
        start.date().isoformat(),
    }


def test_xe513_authoritative_vi25_time_and_utc_rollover():
    r = rec(
        recno=514,
        poss=782,
        obs="1953-08-12",
        fobs="0-08-13",
        obse="22:10",
        obso="23:01",
    )
    start, allowed = allowed_dates(r, "E")

    assert start.isoformat() == "1953-08-13T06:10:00+00:00"
    assert "1953-08-13" in allowed


def test_xe520_utc_date_is_allowed():
    r = rec(
        recno=521,
        poss=875,
        obs="1953-10-30",
        fobs="0-10-31",
        obse="19:31",
        obso="20:21",
    )
    start, allowed = allowed_dates(r, "E")

    assert start.isoformat() == "1953-10-31T03:31:00+00:00"
    assert "1953-10-31" in allowed


def test_xe238_utc_date_is_allowed():
    r = rec(
        recno=239,
        poss=876,
        obs="1953-10-30",
        fobs="0-10-31",
        obse="20:40",
        obso="21:34",
    )
    start, allowed = allowed_dates(r, "E")

    assert start.isoformat() == "1953-10-31T04:40:00+00:00"
    assert "1953-10-31" in allowed


def test_xo522_pixel_equivalent_control_initial_night_date_remains_allowed():
    r = rec(
        recno=523,
        poss=313,
        obs="1951-08-07",
        fobs="0-08-08",
        obse="00:41",
        obso="00:26",
    )
    start, allowed = allowed_dates(r, "O")

    # VI/25 normalization is on the following UTC date, while the verified
    # raw-HHH control carries the initial observing-night date.
    assert start.date().isoformat() == "1951-08-08"
    assert "1951-08-07" in allowed
    assert "1951-08-08" in allowed


def test_date_gate_is_two_encodings_not_arbitrary_plus_minus_one_day():
    src = inspect.getsource(skyview.fallback_identity)

    assert "vi25_initial_night_date = str(record.obs).strip()" in src
    assert (
        "vi25_normalized_utc_date = "
        "expected_start_utc.date().isoformat()"
    ) in src
    assert "if hhh_obs_date not in allowed_hhh_dates:" in src
    assert 'if hhh_obs_date != str(record.obs).strip():' not in src
    assert "timedelta(days=1)" not in src


def test_direct_call_compatibility_uses_authoritative_vi25_helper():
    sig = inspect.signature(skyview.fallback_identity)

    assert sig.parameters["expected_start_utc"].default is None

    src = inspect.getsource(skyview.fallback_identity)
    assert "from .poss1 import vi25_start_utc" in src
    assert "expected_start_utc = vi25_start_utc(record, band)" in src


def test_every_production_skyview_fallback_receives_expected_start():
    src = textwrap.dedent(inspect.getsource(poss1.poss1_identity_worker))
    tree = ast.parse(src)

    calls = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if isinstance(node.func, ast.Name) and node.func.id == "skyview_fallback_identity":
            calls.append(node)

    assert len(calls) == 3

    for call in calls:
        keywords = {
            kw.arg: kw.value
            for kw in call.keywords
            if kw.arg is not None
        }
        value = keywords["expected_start_utc"]
        assert isinstance(value, ast.Name)
        assert value.id == "expected_start"


def test_old_descriptor_hhh_center_terminal_gate_remains_absent():
    src = inspect.getsource(skyview.fallback_identity)

    assert (
        "if descriptor_hhh_center_sep > "
        "descriptor_hhh_center_tolerance_arcsec:"
    ) not in src


def test_exact_raw_hhh_404_policy_remains_present():
    src = inspect.getsource(skyview.fallback_identity)

    assert '"archive_failure_kind": "skyview_raw_hhh_http_404"' in src
    assert "No neighbouring DSS region is substituted." in src
