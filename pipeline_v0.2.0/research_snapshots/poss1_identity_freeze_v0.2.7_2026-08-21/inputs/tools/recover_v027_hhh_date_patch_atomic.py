from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import ast
import hashlib
import shutil


ROOT = Path.cwd()

SKY = ROOT / "src" / "transient_pipeline" / "poss1_skyview.py"
POSS = ROOT / "src" / "transient_pipeline" / "poss1.py"
FIXTURE = ROOT / "tests" / "test_poss1_v026_nonresolution_fallback.py"
NEW_TEST = ROOT / "tests" / "test_poss1_v027_hhh_date_policy.py"

FAILED_PATCH_BACKUP = (
    ROOT
    / "patch_backups"
    / "pre_v0.2.7_hhh_date_repair_20260821T140416Z"
)
BASE_SKY = (
    FAILED_PATCH_BACKUP
    / "src"
    / "transient_pipeline"
    / "poss1_skyview.py"
)

EXPECTED_BASE_SKY_SHA256 = (
    "df125f17bfc4f21f6dd1a16ba3290790b5a47e37a8d8bffba6e239932da2000a"
)
EXPECTED_POSS_SHA256 = (
    "71de9f518ba19cbef00717d2d2a0a26300510db97fecbda4cce236908f913136"
)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def replace1(text: str, old: str, new: str, label: str) -> str:
    n = text.count(old)
    if n != 1:
        raise SystemExit(
            f"REFUSING: {label}: expected exactly one match, found {n}"
        )
    return text.replace(old, new, 1)


print("=" * 92)
print("POSS-I v0.2.7 ATOMIC HHH DATE-SEMANTICS RECOVERY")
print("=" * 92)

for path in (SKY, POSS, FIXTURE, BASE_SKY):
    if not path.exists():
        raise SystemExit(f"Missing required file: {path}")

if sha256_file(BASE_SKY) != EXPECTED_BASE_SKY_SHA256:
    raise SystemExit(
        "REFUSING: failed-patch backup does not contain the exact validated "
        "pre-date-repair v0.2.7 SkyView source."
    )

if sha256_file(POSS) != EXPECTED_POSS_SHA256:
    raise SystemExit(
        "REFUSING: poss1.py changed unexpectedly after the failed patch.\n"
        f"Expected: {EXPECTED_POSS_SHA256}\n"
        f"Actual:   {sha256_file(POSS)}"
    )

base_sky = BASE_SKY.read_text(encoding="utf-8")
current_sky = SKY.read_text(encoding="utf-8")

# ----------------------------------------------------------------------
# Reconstruct exactly what the failed script should have written to SKY
# before it aborted.  This lets us prove that the current file contains
# ONLY the known partial edit before restoring/repatching it.
# ----------------------------------------------------------------------

old_sig = '''    primary_failure: str,
    expected_plate_id: str | None = None,
'''

half_sig = '''    primary_failure: str,
    expected_start_utc: Any,
    expected_plate_id: str | None = None,
'''

old_start = '''    band = str(band).upper()
    expected_region_from_vi25 = expected_region_for_vi25(record, band)
'''

half_start = '''    band = str(band).upper()

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

old_hhh_prov = '''            "hhh_observing_date": hhh_obs_date,
            "probe_tile_url": probe_url,
'''

new_hhh_prov = '''            "hhh_observing_date": hhh_obs_date,
            "hhh_date_identity_policy": (
                "vi25_initial_night_or_normalized_utc_date_v0.2.7"
            ),
            "probe_tile_url": probe_url,
'''

expected_half = base_sky
expected_half = replace1(
    expected_half, old_sig, half_sig, "reconstruct partial signature"
)
expected_half = replace1(
    expected_half, old_start, half_start, "reconstruct partial start"
)
expected_half = replace1(
    expected_half, old_date, new_date, "reconstruct partial date gate"
)
expected_half = replace1(
    expected_half,
    old_vi25_sidecar,
    new_vi25_sidecar,
    "reconstruct partial VI25 sidecar",
)
expected_half = replace1(
    expected_half,
    old_hhh_prov,
    new_hhh_prov,
    "reconstruct partial HHH sidecar",
)

print()
print("CURRENT PARTIAL-STATE VERIFICATION")
print("-" * 92)
print("validated base SkyView SHA256:", sha256_file(BASE_SKY))
print("current SkyView SHA256:       ", sha256_file(SKY))
print("current equals expected half:  ", current_sky == expected_half)

if current_sky != expected_half:
    raise SystemExit(
        "REFUSING: current poss1_skyview.py is not exactly the known "
        "half-applied state. No files changed."
    )

# ----------------------------------------------------------------------
# Stage the corrected SkyView edit IN MEMORY.
#
# Production callers pass the normalized timestamp explicitly.
# Direct/test callers retain compatibility: when omitted, this function
# lazily imports the authoritative vi25_start_utc helper.  No duplicate
# PST/overnight timestamp implementation is introduced.
# ----------------------------------------------------------------------

final_sig = '''    primary_failure: str,
    expected_start_utc: Any | None = None,
    expected_plate_id: str | None = None,
'''

final_start = '''    band = str(band).upper()

    # Production callers pass the already-normalized VI/25 UTC start.
    # Direct/test callers may omit it; derive it from the same authoritative
    # VI/25 helper rather than duplicating observing-night/PST logic here.
    if expected_start_utc is None:
        from .poss1 import vi25_start_utc
        expected_start_utc = vi25_start_utc(record, band)

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

final_sky = base_sky
final_sky = replace1(
    final_sky, old_sig, final_sig, "final fallback signature"
)
final_sky = replace1(
    final_sky, old_start, final_start, "final fallback start"
)
final_sky = replace1(
    final_sky, old_date, new_date, "final HHH date gate"
)
final_sky = replace1(
    final_sky,
    old_vi25_sidecar,
    new_vi25_sidecar,
    "final VI25 provenance",
)
final_sky = replace1(
    final_sky,
    old_hhh_prov,
    new_hhh_prov,
    "final HHH provenance",
)

# Scientific-policy invariants.
required_sky = (
    "expected_start_utc: Any | None = None",
    "from .poss1 import vi25_start_utc",
    "vi25_initial_night_date = str(record.obs).strip()",
    "vi25_normalized_utc_date = expected_start_utc.date().isoformat()",
    "if hhh_obs_date not in allowed_hhh_dates:",
    "vi25_initial_night_or_normalized_utc_date_v0.2.7",
    "descriptor_hhh_center_policy",
    "skyview_raw_hhh_http_404",
)

for needle in required_sky:
    if needle not in final_sky:
        raise SystemExit(f"REFUSING: final SkyView invariant missing: {needle}")

if 'if hhh_obs_date != str(record.obs).strip():' in final_sky:
    raise SystemExit("REFUSING: obsolete HHH initial-date equality survived")

if (
    "if descriptor_hhh_center_sep > "
    "descriptor_hhh_center_tolerance_arcsec:"
) in final_sky:
    raise SystemExit("REFUSING: obsolete descriptor/HHH centre gate returned")

# ----------------------------------------------------------------------
# Stage poss1.py production wiring IN MEMORY.
# ----------------------------------------------------------------------

final_poss = POSS.read_text(encoding="utf-8")

# One occurrence already exists legitimately in select_candidate().
pre_count = final_poss.count("expected_start_utc=expected_start")
print()
print("PRE-EXISTING expected_start_utc=expected_start COUNT:", pre_count)

if pre_count != 1:
    raise SystemExit(
        "REFUSING: expected exactly one pre-existing normalized-start "
        f"argument in poss1.py, found {pre_count}"
    )

if final_poss.count("skyview_fallback_identity(") != 3:
    raise SystemExit(
        "REFUSING: expected exactly three production SkyView fallback calls, "
        f"found {final_poss.count('skyview_fallback_identity(')}"
    )

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

final_poss = replace1(
    final_poss, call1_old, call1_new, "Plate Finder retryable fallback"
)
final_poss = replace1(
    final_poss, call2_old, call2_new, "Plate Finder non-resolution fallback"
)
final_poss = replace1(
    final_poss, call3_old, call3_new, "forced-extract retryable fallback"
)

# Correct total: one select_candidate() + three fallback calls.
post_count = final_poss.count("expected_start_utc=expected_start")
if post_count != 4:
    raise SystemExit(
        "REFUSING: expected four total normalized-start arguments "
        f"(1 existing + 3 fallback), found {post_count}"
    )

# AST-level confirmation that EACH SkyView fallback call has exactly the
# authoritative local variable `expected_start`.
tree = ast.parse(final_poss)
fallback_calls = []
for node in ast.walk(tree):
    if not isinstance(node, ast.Call):
        continue
    if isinstance(node.func, ast.Name) and node.func.id == "skyview_fallback_identity":
        fallback_calls.append(node)

if len(fallback_calls) != 3:
    raise SystemExit(
        f"REFUSING: AST found {len(fallback_calls)} SkyView fallback calls"
    )

for i, node in enumerate(fallback_calls, start=1):
    kw = {x.arg: x.value for x in node.keywords if x.arg is not None}
    value = kw.get("expected_start_utc")
    if not (
        isinstance(value, ast.Name)
        and value.id == "expected_start"
    ):
        raise SystemExit(
            f"REFUSING: fallback call {i} does not receive expected_start"
        )

# ----------------------------------------------------------------------
# Stage correction of the stale XE513 test fixture IN MEMORY.
# ----------------------------------------------------------------------

fixture = FIXTURE.read_text(encoding="utf-8")

stale_fixture = '''        obse="20:15",
        obso="19:55",
'''
correct_fixture = '''        obse="22:10",
        obso="23:01",
'''

fixture = replace1(
    fixture,
    stale_fixture,
    correct_fixture,
    "XE513 authoritative VI/25 fixture",
)

# ----------------------------------------------------------------------
# New regression tests.
# ----------------------------------------------------------------------

test_text = r'''from __future__ import annotations

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
'''

# ----------------------------------------------------------------------
# All transformations have now been validated in memory.
# Only NOW create a fresh recovery backup and write all files.
# ----------------------------------------------------------------------

stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
backup = (
    ROOT
    / "patch_backups"
    / f"pre_v0.2.7_hhh_date_atomic_recovery_{stamp}"
)

for path in (SKY, POSS, FIXTURE):
    dst = backup / path.relative_to(ROOT)
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(path, dst)

if NEW_TEST.exists():
    raise SystemExit(
        f"REFUSING: unexpected existing new-test file: {NEW_TEST}"
    )

SKY.write_text(final_sky, encoding="utf-8")
POSS.write_text(final_poss, encoding="utf-8")
FIXTURE.write_text(fixture, encoding="utf-8")
NEW_TEST.write_text(test_text, encoding="utf-8")

print()
print("=" * 92)
print("ATOMIC RECOVERY WRITTEN")
print("=" * 92)
print("backup:", backup)
print("poss1_skyview SHA256:", sha256_file(SKY))
print("poss1.py SHA256:       ", sha256_file(POSS))
print("fixture SHA256:        ", sha256_file(FIXTURE))
print("new test:              ", NEW_TEST)
print()
print("Production fallback calls:", len(fallback_calls))
print("Total expected_start_utc=expected_start occurrences:", post_count)
print()
print("No checkpoint state was changed.")
print("No transient detector was run.")
