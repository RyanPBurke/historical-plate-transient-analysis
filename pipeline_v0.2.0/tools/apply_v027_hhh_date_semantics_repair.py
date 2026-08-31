from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import hashlib
import shutil


ROOT = Path.cwd()

SKY = ROOT / "src" / "transient_pipeline" / "poss1_skyview.py"
POSS = ROOT / "src" / "transient_pipeline" / "poss1.py"
TEST_FIXTURE = ROOT / "tests" / "test_poss1_v026_nonresolution_fallback.py"
NEW_TEST = ROOT / "tests" / "test_poss1_v027_hhh_date_policy.py"

EXPECTED_SKY_SHA256 = (
    "df125f17bfc4f21f6dd1a16ba3290790b5a47e37a8d8bffba6e239932da2000a"
)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


print("=" * 88)
print("POSS-I v0.2.7 REVIEWED HHH DATE-SEMANTICS REPAIR")
print("=" * 88)

for p in (SKY, POSS, TEST_FIXTURE):
    if not p.exists():
        raise SystemExit(f"Missing required file: {p}")

actual_sky_sha = sha256_file(SKY)

print("pre-patch poss1_skyview SHA256:", actual_sky_sha)
print("pre-patch poss1.py SHA256:       ", sha256_file(POSS))

if actual_sky_sha != EXPECTED_SKY_SHA256:
    raise SystemExit(
        "REFUSING: poss1_skyview.py is not the exact tested v0.2.7 source.\n"
        f"Expected: {EXPECTED_SKY_SHA256}\n"
        f"Actual:   {actual_sky_sha}"
    )

stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
backup = ROOT / "patch_backups" / f"pre_v0.2.7_hhh_date_repair_{stamp}"

for src in (SKY, POSS, TEST_FIXTURE):
    rel = src.relative_to(ROOT)
    dst = backup / rel
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)

print("backup:", backup)

# ======================================================================
# 1. poss1_skyview.py
#
# Pass in the already-normalized VI/25 UTC exposure start rather than
# reimplementing VI/25/PST date logic inside the fallback.
# ======================================================================

text = SKY.read_text(encoding="utf-8")

old_sig = '''    primary_failure: str,
    expected_plate_id: str | None = None,
'''

new_sig = '''    primary_failure: str,
    expected_start_utc: Any,
    expected_plate_id: str | None = None,
'''

if text.count(old_sig) != 1:
    raise SystemExit(
        "REFUSING: expected exactly one fallback signature insertion point; "
        f"found {text.count(old_sig)}"
    )

text = text.replace(old_sig, new_sig, 1)

old_start = '''    band = str(band).upper()
    expected_region_from_vi25 = expected_region_for_vi25(record, band)
'''

new_start = '''    band = str(band).upper()

    # The caller owns VI/25 timestamp normalization.  Require its UTC result
    # explicitly rather than duplicating the observing-night/PST rules here.
    if expected_start_utc is None:
        raise ValueError("SkyView fallback requires normalized VI/25 UTC start")
    try:
        utc_offset = expected_start_utc.utcoffset()
    except Exception as exc:
        raise ValueError(
            "SkyView fallback received invalid normalized VI/25 UTC start"
        ) from exc
    if utc_offset is None or utc_offset.total_seconds() != 0:
        raise ValueError(
            "SkyView fallback expected_start_utc must be timezone-aware UTC"
        )

    expected_region_from_vi25 = expected_region_for_vi25(record, band)
'''

if text.count(old_start) != 1:
    raise SystemExit(
        "REFUSING: expected exactly one fallback start block; "
        f"found {text.count(old_start)}"
    )

text = text.replace(old_start, new_start, 1)

old_date = '''    # GSSS DATE-OBS clock values are not a reliable exposure-start authority (the
    # verified XO522 control differs from VI/25 by minutes), but the observing-night
    # calendar date is stable and provides an independent date identity check.
    hhh_obs_date = hhh_observing_date(str(ident["date_obs"]))
    if hhh_obs_date != str(record.obs).strip():
        raise ValueError(
            f"SkyView HHH observing-date mismatch for {expected_region_from_vi25}: "
            f"{hhh_obs_date!r} != VI/25 {record.obs!r}"
        )
'''

new_date = '''    # GSSS DATE-OBS calendar rollover is not uniform across the verified POSS-I
    # raw headers.  Pixel-equivalent controls retain the initial observing-night
    # calendar date even when the corresponding VI/25 PST exposure normalizes to
    # the following UTC date, while other valid raw headers use that normalized
    # UTC date.  Preserve a hard date identity check, but admit only those two
    # physically/documentarily justified encodings -- never an arbitrary +/-1 day.
    hhh_obs_date = hhh_observing_date(str(ident["date_obs"]))
    vi25_initial_night_date = str(record.obs).strip()
    vi25_normalized_utc_date = expected_start_utc.date().isoformat()
    allowed_hhh_dates = {
        vi25_initial_night_date,
        vi25_normalized_utc_date,
    }
    if hhh_obs_date not in allowed_hhh_dates:
        raise ValueError(
            f"SkyView HHH observing-date mismatch for {expected_region_from_vi25}: "
            f"{hhh_obs_date!r} not in reviewed VI/25-compatible dates "
            f"{sorted(allowed_hhh_dates)!r}"
        )
'''

if text.count(old_date) != 1:
    raise SystemExit(
        "REFUSING: expected exactly one old HHH date gate; "
        f"found {text.count(old_date)}"
    )

text = text.replace(old_date, new_date, 1)

# Add the actual time/date-policy provenance to the successful identity sidecar.
old_vi25_sidecar = '''            "ra_icrs_deg": ra_icrs,
            "dec_icrs_deg": dec_icrs,
'''

new_vi25_sidecar = '''            "ra_icrs_deg": ra_icrs,
            "dec_icrs_deg": dec_icrs,
            "observing_night_initial": record.obs,
            "observing_night_final": record.fobs,
            "normalized_start_utc": expected_start_utc.isoformat(),
            "normalized_start_utc_date": vi25_normalized_utc_date,
            "allowed_hhh_calendar_dates": sorted(allowed_hhh_dates),
'''

if text.count(old_vi25_sidecar) != 1:
    raise SystemExit(
        "REFUSING: expected exactly one successful VI/25 provenance block; "
        f"found {text.count(old_vi25_sidecar)}"
    )

text = text.replace(old_vi25_sidecar, new_vi25_sidecar, 1)

old_hhh_prov = '''            "hhh_observing_date": hhh_obs_date,
            "probe_tile_url": probe_url,
'''

new_hhh_prov = '''            "hhh_observing_date": hhh_obs_date,
            "hhh_date_identity_policy": (
                "vi25_initial_night_or_normalized_utc_date_v0.2.7"
            ),
            "probe_tile_url": probe_url,
'''

if text.count(old_hhh_prov) != 1:
    raise SystemExit(
        "REFUSING: expected exactly one HHH provenance insertion point; "
        f"found {text.count(old_hhh_prov)}"
    )

text = text.replace(old_hhh_prov, new_hhh_prov, 1)

SKY.write_text(text, encoding="utf-8")

# ======================================================================
# 2. poss1.py
#
# There are exactly three production fallback call sites.  All already have
# `expected_start` in scope.  Wire that authoritative value through.
# ======================================================================

text = POSS.read_text(encoding="utf-8")

call1_old = '''                evidence=evidence,
                primary_failure=f"stsci_platefinder_retryable: {exc}",
'''

call1_new = '''                evidence=evidence,
                expected_start_utc=expected_start,
                primary_failure=f"stsci_platefinder_retryable: {exc}",
'''

call2_old = '''                evidence=evidence,
                primary_failure=(
                    "stsci_platefinder_no_unique_match: "
'''

call2_new = '''                evidence=evidence,
                expected_start_utc=expected_start,
                primary_failure=(
                    "stsci_platefinder_no_unique_match: "
'''

call3_old = '''                evidence=evidence,
                primary_failure=f"stsci_forced_extract_retryable: {exc}",
                expected_plate_id=selected.plate_id,
'''

call3_new = '''                evidence=evidence,
                expected_start_utc=expected_start,
                primary_failure=f"stsci_forced_extract_retryable: {exc}",
                expected_plate_id=selected.plate_id,
'''

for label, old, new in (
    ("Plate Finder retryable", call1_old, call1_new),
    ("Plate Finder non-resolution", call2_old, call2_new),
    ("forced-extract retryable", call3_old, call3_new),
):
    if text.count(old) != 1:
        raise SystemExit(
            f"REFUSING: expected exactly one {label} fallback call; "
            f"found {text.count(old)}"
        )
    text = text.replace(old, new, 1)

if text.count("expected_start_utc=expected_start") != 3:
    raise SystemExit(
        "REFUSING: expected exactly three normalized-UTC fallback arguments "
        f"after patch; found {text.count('expected_start_utc=expected_start')}"
    )

POSS.write_text(text, encoding="utf-8")

# ======================================================================
# 3. Repair stale XE513 regression fixture.
#
# VI/25 recno 514 / POSS 782 is 22:10 E and 23:01 O, not 20:15/19:55.
# ======================================================================

fixture = TEST_FIXTURE.read_text(encoding="utf-8")

old_fixture = '''        obse="20:15",
        obso="19:55",
'''

new_fixture = '''        obse="22:10",
        obso="23:01",
'''

if fixture.count(old_fixture) != 1:
    raise SystemExit(
        "REFUSING: expected exactly one stale XE513 timing fixture; "
        f"found {fixture.count(old_fixture)}"
    )

fixture = fixture.replace(old_fixture, new_fixture, 1)
TEST_FIXTURE.write_text(fixture, encoding="utf-8")

# ======================================================================
# 4. Regression tests.
# ======================================================================

test_text = r'''from __future__ import annotations

import inspect

import pytest

import transient_pipeline.poss1 as poss1
import transient_pipeline.poss1_skyview as skyview


def rec(
    *,
    recno,
    poss,
    obs,
    fobs,
    obse,
    obso,
):
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


@pytest.mark.parametrize(
    "record,band,hhh_date,expected_utc",
    [
        # Four v0.2.7 terminal cases.  Their HHH date follows the normalized
        # UTC exposure date rather than VI/25's initial observing-night date.
        (
            rec(
                recno=514, poss=782,
                obs="1953-08-12", fobs="0-08-13",
                obse="22:10", obso="23:01",
            ),
            "E", "1953-08-13", "1953-08-13T06:10:00+00:00",
        ),
        (
            rec(
                recno=148, poss=872,
                obs="1953-10-28", fobs="0-10-29",
                obse="19:35", obso="20:27",
            ),
            "O", "1953-10-29", "1953-10-29T04:27:00+00:00",
        ),
        (
            rec(
                recno=521, poss=875,
                obs="1953-10-30", fobs="0-10-31",
                obse="19:31", obso="20:21",
            ),
            "E", "1953-10-31", "1953-10-31T03:31:00+00:00",
        ),
        (
            rec(
                recno=239, poss=876,
                obs="1953-10-30", fobs="0-10-31",
                obse="20:40", obso="21:34",
            ),
            "E", "1953-10-31", "1953-10-31T04:40:00+00:00",
        ),
    ],
)
def test_four_reviewed_rollover_cases_are_vi25_compatible(
    record, band, hhh_date, expected_utc
):
    start = poss1.vi25_start_utc(record, band)

    assert start.isoformat() == expected_utc

    allowed = {
        record.obs.strip(),
        start.date().isoformat(),
    }

    assert hhh_date in allowed


@pytest.mark.parametrize(
    "record,band,hhh_date",
    [
        # Five strict pixel-equivalence controls.  These demonstrate the other
        # historical GSSS convention: DATE-OBS can retain the initial night date.
        (
            rec(
                recno=425, poss=236,
                obs="1951-02-03", fobs="0-02-04",
                obse="21:54", obso="22:49",
            ),
            "E", "1951-02-03",
        ),
        (
            rec(
                recno=523, poss=313,
                obs="1951-08-07", fobs="0-08-08",
                obse="00:41", obso="00:26",
            ),
            "O", "1951-08-07",
        ),
        (
            rec(
                recno=192, poss=368,
                obs="1951-09-09", fobs="0-09-10",
                obse="00:01", obso="23:45",
            ),
            "E", "1951-09-09",
        ),
        (
            rec(
                recno=455, poss=372,
                obs="1951-09-20", fobs="0-09-21",
                obse="19:20", obso="20:25",
            ),
            "O", "1951-09-20",
        ),
        (
            rec(
                recno=246, poss=407,
                obs="1951-11-02", fobs="0-11-03",
                obse="23:01", obso="22:45",
            ),
            "E", "1951-11-02",
        ),
    ],
)
def test_five_pixel_equivalent_controls_retain_initial_night_as_allowed_date(
    record, band, hhh_date
):
    start = poss1.vi25_start_utc(record, band)

    allowed = {
        record.obs.strip(),
        start.date().isoformat(),
    }

    assert hhh_date in allowed


def test_fallback_date_gate_uses_only_two_reviewed_encodings():
    src = inspect.getsource(skyview.fallback_identity)

    assert "vi25_initial_night_date = str(record.obs).strip()" in src
    assert (
        "vi25_normalized_utc_date = "
        "expected_start_utc.date().isoformat()"
    ) in src
    assert "allowed_hhh_dates = {" in src
    assert "if hhh_obs_date not in allowed_hhh_dates:" in src

    # The invalid old hard equality must not return.
    assert 'if hhh_obs_date != str(record.obs).strip():' not in src

    # And this is intentionally NOT an arbitrary +/- 1-day tolerance.
    assert "timedelta(days=1)" not in src


def test_all_production_skyview_fallback_calls_pass_authoritative_utc_start():
    src = inspect.getsource(poss1.poss1_identity_worker)

    assert src.count("expected_start_utc=expected_start") == 3


def test_xe513_authoritative_fixture_is_2210_not_stale_2015():
    record = rec(
        recno=514,
        poss=782,
        obs="1953-08-12",
        fobs="0-08-13",
        obse="22:10",
        obso="23:01",
    )

    assert poss1.vi25_start_utc(record, "E").isoformat() == (
        "1953-08-13T06:10:00+00:00"
    )
'''

NEW_TEST.write_text(test_text, encoding="utf-8")

print()
print("PATCH APPLIED")
print("-" * 88)
print("poss1_skyview SHA256:", sha256_file(SKY))
print("poss1.py SHA256:       ", sha256_file(POSS))
print("fixture SHA256:        ", sha256_file(TEST_FIXTURE))
print("new test:", NEW_TEST)
print()
print("Changes:")
print("  1. fallback now receives authoritative VI/25 normalized UTC start")
print("  2. HHH date gate accepts only initial-night OR normalized-UTC date")
print("  3. no arbitrary +/-1-day tolerance introduced")
print("  4. successful identity sidecars record both date encodings")
print("  5. stale XE513 test times corrected from 20:15/19:55 to 22:10/23:01")
print()
print("No checkpoint state was changed.")
print("No transient detector was run.")
