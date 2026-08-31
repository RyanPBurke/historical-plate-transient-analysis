from __future__ import annotations

from pathlib import Path
import hashlib
import json
import py_compile
import re

ROOT = Path.cwd()

SOURCE = ROOT / "tools" / "run_order61_whole_native_v028.py"
ORDER01_PREFLIGHT = (
    ROOT / "results" / "order01_native_preflight_v028"
    / "order01_exact_native_source_and_dasch_metadata_v028.json"
)
PAIR_MAP = ROOT / "research" / "SUB5_V028_POSS_PAIR_EXECUTION_MAP_2026-08-21.csv"
POLICY = ROOT / "research" / "NATIVE_TILE_EXECUTION_POLICY_V028_2026-08-21.json"

TARGET = ROOT / "tools" / "run_order01_whole_native_v028.py"
MANIFEST = (
    ROOT / "results" / "order01_native_preflight_v028"
    / "order01_runner_generation_manifest_v028.json"
)

EXPECTED = {
    "canonical_order": 1,
    "poss_exposure_id": "POSS-I:413:E:rec297",
    "poss_region": "XE296",
    "poss_plate_id": "06S2",
    "dasch_plate_id": "ai43437",
    "raw_plate_directory": "https://skyview.gsfc.nasa.gov/surveys/dss/xe296",
    "hhh_sha256": "e7fce1b323623e4bb6a82e16537cb3728e620870a4a64d36bdc05b05756b37d2",
    "poss_fits_sha256": "6e8ca42e82804615316845436c934d0b184a5deddeeee9ab0c6951736088fa16",
    "full_width": 14000,
    "full_height": 13999,
    "actual_overlap_s": 3480.0,
}

EXPECTED_DETECTOR_SHA = "709da8d7a7972b15808d70a1e4dbffa0fd0fee864a81d954f74fe4a5f5af25e7"
EXPECTED_METHOD_SHA = "2cb3cabd573d7af99399899f2ccecd3002be90297e55bb0e0dcdd9dea1d0c4c1"
EXPECTED_JAR_SHA = "8483a20d986bb61fa1d733ce16d446fb2a0ff363bc1b1367e28b01a1bbdcbb8d"
EXPECTED_POLICY_SHA = "44fc3453c3291a7cbe72894d781729a30943ad540aa169b2c0897b446c5c8ec7"


def sha_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def require_file(path: Path):
    if not path.is_file():
        raise RuntimeError(f"Missing required file: {path}")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    n = text.count(old)
    if n != 1:
        raise RuntimeError(
            f"REFUSING: expected exactly one {label} token, found {n}\nTOKEN:\n{old}"
        )
    return text.replace(old, new, 1)


def replacement_audit(text: str, forbidden: list[tuple[str, str]]):
    hits = []
    for label, token in forbidden:
        if token in text:
            hits.append({"label": label, "token": token, "count": text.count(token)})
    return hits


def main():
    print("=" * 112)
    print("GENERATE ORDER 01 WHOLE-NATIVE RUNNER FROM VALIDATED ORDER 61 WORKER — v028")
    print("=" * 112)
    print(
        "Guarded source transformation only. This command DOES NOT run the detector or read science pixels."
    )
    print()

    for p in (SOURCE, ORDER01_PREFLIGHT, PAIR_MAP, POLICY):
        require_file(p)

    detector = ROOT / "src" / "transient_pipeline" / "detector.py"
    method = ROOT / "config" / "frozen_method.json"
    require_file(detector)
    require_file(method)

    detector_sha = sha_file(detector)
    method_sha = sha_file(method)
    policy_sha = sha_file(POLICY)

    if detector_sha != EXPECTED_DETECTOR_SHA:
        raise RuntimeError(
            f"REFUSING: detector SHA changed: {detector_sha}"
        )
    if method_sha != EXPECTED_METHOD_SHA:
        raise RuntimeError(
            f"REFUSING: frozen method SHA changed: {method_sha}"
        )
    if policy_sha != EXPECTED_POLICY_SHA:
        raise RuntimeError(
            f"REFUSING: native tile policy SHA changed: {policy_sha}"
        )

    pre = json.loads(ORDER01_PREFLIGHT.read_text(encoding="utf-8"))
    if pre.get("status") != "COMPLETE":
        raise RuntimeError("REFUSING: Order-1 exact native-source preflight is not COMPLETE")

    pair = pre["frozen_pair_map_row"]
    poss = pre["poss_native_source"]
    fits_ref = pre["frozen_poss_identity_fits"]
    dasch = pre["dasch_mosaic_package"]

    guards = {
        "canonical_order": int(float(pair["canonical_order"])) == EXPECTED["canonical_order"],
        "poss_exposure_id": pair["poss_exposure_id"] == EXPECTED["poss_exposure_id"],
        "poss_region": pair["poss_region"] == EXPECTED["poss_region"],
        "dasch_plate": pair["partner_dasch_plate_id"].lower() == EXPECTED["dasch_plate_id"],
        "actual_overlap_s": abs(float(pair["actual_overlap_s"]) - EXPECTED["actual_overlap_s"]) < 1e-6,
        "poss_plate_id": fits_ref["plate_id"] == EXPECTED["poss_plate_id"],
        "poss_fits_sha": fits_ref["sha256"].lower() == EXPECTED["poss_fits_sha256"],
        "raw_plate_directory": poss["raw_plate_directory"].rstrip("/") == EXPECTED["raw_plate_directory"],
        "hhh_sha": poss["hhh_sha256"].lower() == EXPECTED["hhh_sha256"],
        "hhh_region": poss["hhh_identity"]["region"].upper() == EXPECTED["poss_region"],
        "hhh_plate_id": poss["hhh_identity"]["plate_id"].upper() == EXPECTED["poss_plate_id"],
        "hhh_width": int(poss["hhh_header_parse"]["selected_header"]["XPIXELS"]) == EXPECTED["full_width"],
        "hhh_height": int(poss["hhh_header_parse"]["selected_header"]["YPIXELS"]) == EXPECTED["full_height"],
        "dasch_base_url_present": bool(dasch.get("baseFitsUrl")),
        "dasch_metadata_present": dasch.get("metadata") is not None,
        "preflight_no_native_pixels": pre.get("native_science_pixels_read") is False,
        "preflight_no_dasch_pixels": pre.get("dasch_science_pixels_read") is False,
        "preflight_no_detector": pre.get("detector_rerun") is False,
    }
    if not all(guards.values()):
        raise RuntimeError("REFUSING: Order-1 preflight guard failure: " + repr(guards))

    print("Order-1 exact-source / frozen-method guards: PASS")
    print(f"  detector SHA: {detector_sha}")
    print(f"  method SHA:   {method_sha}")
    print(f"  policy SHA:   {policy_sha}")
    print(f"  POSS:         {EXPECTED['poss_exposure_id']} / {EXPECTED['poss_region']} / {EXPECTED['poss_plate_id']}")
    print(f"  native shape: {EXPECTED['full_width']} x {EXPECTED['full_height']}")
    print(f"  DASCH:        {EXPECTED['dasch_plate_id']}")
    print()

    source_text = SOURCE.read_text(encoding="utf-8")
    source_sha = sha_file(SOURCE)

    # ------------------------------------------------------------------
    # Critical structural guards against silently transforming a different
    # worker version than the completed Order-61 implementation.
    # ------------------------------------------------------------------
    structural_tokens = [
        'ORDER = 61',
        'POSS_ID, REGION, POSS_PLATE, DASCH_PLATE = "POSS-I:875:E:rec521", "XE520", "090N", "ai44092"',
        'CORE, HALO, DASCH_BOUND_PAD, GEOM_GRID = 1024, 64, 256, 65',
        'EXPECTED_DETECTOR_SHA = "709da8d7a7972b15808d70a1e4dbffa0fd0fee864a81d954f74fe4a5f5af25e7"',
        'EXPECTED_METHOD_SHA = "2cb3cabd573d7af99399899f2ccecd3002be90297e55bb0e0dcdd9dea1d0c4c1"',
        'EXPECTED_JAR_SHA = "8483a20d986bb61fa1d733ce16d446fb2a0ff363bc1b1367e28b01a1bbdcbb8d"',
        'POSS_RAW = "https://skyview.gsfc.nasa.gov/surveys/dss/xe520"',
        'POLICY = ROOT / "research/NATIVE_TILE_EXECUTION_POLICY_V028_2026-08-21.json"',
        'GEOM_SOURCE = ROOT / "tools/repair_remaining_poss_geometry_v028.py"',
        'CONTROL_SOURCE = ROOT / "tools/run_pair61_native_detector_control_v028.py"',
        'from transient_pipeline.detector import detect_array',
    ]
    missing = [tok for tok in structural_tokens if tok not in source_text]
    if missing:
        raise RuntimeError(
            "REFUSING: validated Order-61 source no longer has expected structure:\n"
            + "\n".join(missing)
        )

    text = source_text

    # ------------------------------------------------------------------
    # Pair-specific INPUT transformation.
    # ------------------------------------------------------------------
    text = replace_once(
        text,
        'ORDER = 61',
        'ORDER = 1',
        "ORDER constant",
    )
    text = replace_once(
        text,
        'POSS_ID, REGION, POSS_PLATE, DASCH_PLATE = "POSS-I:875:E:rec521", "XE520", "090N", "ai44092"',
        'POSS_ID, REGION, POSS_PLATE, DASCH_PLATE = "POSS-I:413:E:rec297", "XE296", "06S2", "ai43437"',
        "pair constants",
    )
    text = replace_once(
        text,
        'REF = ROOT / "cache/poss1_exact_plate_cutout_preflight_v028b/POSS-I_875_E_rec521/XE520_090N_preflight.fits"',
        'REF = ROOT / "cache/poss1_identity/POSS-I_413_E_rec297/06S2_identity.fits"',
        "reference FITS",
    )
    text = replace_once(
        text,
        'WORK = ROOT / "work/order61_native_full_v028"',
        'WORK = ROOT / "work/order01_native_full_v028"',
        "work directory",
    )
    text = replace_once(
        text,
        'RESULT = ROOT / "results/order61_native_full_v028"',
        'RESULT = ROOT / "results/order01_native_full_v028"',
        "result directory",
    )
    text = replace_once(
        text,
        'UA = "historical-transient-pipeline/0.2.8-order61-whole-pair"',
        'UA = "historical-transient-pipeline/0.2.8-order01-whole-pair"',
        "user agent",
    )
    text = replace_once(
        text,
        'POSS_RAW = "https://skyview.gsfc.nasa.gov/surveys/dss/xe520"',
        'POSS_RAW = "https://skyview.gsfc.nasa.gov/surveys/dss/xe296"',
        "native raw directory",
    )

    # ------------------------------------------------------------------
    # Pair-specific OUTPUT / report transformation.
    # Do NOT touch pair61 control/JAR provenance or the frozen policy keys.
    # ------------------------------------------------------------------
    text = text.replace(
        'ORDER 61 â€” RESUMABLE WHOLE-FOOTPRINT NATIVE DETECTOR EXECUTION',
        'ORDER 01 — RESUMABLE WHOLE-FOOTPRINT NATIVE DETECTOR EXECUTION',
    )
    text = text.replace(
        'ORDER 61 — RESUMABLE WHOLE-FOOTPRINT NATIVE DETECTOR EXECUTION',
        'ORDER 01 — RESUMABLE WHOLE-FOOTPRINT NATIVE DETECTOR EXECUTION',
    )

    output_replacements = {
        '"order61_poss_native_candidates.csv"': '"order01_poss_native_candidates.csv"',
        '"order61_dasch_native_candidates.csv"': '"order01_dasch_native_candidates.csv"',
        '"order61_raw_coincidences.csv"': '"order01_raw_coincidences.csv"',
        '"order61_whole_pair_report.json"': '"order01_whole_pair_report.json"',
        '"order61_whole_footprint_native_tile_frozen_detector"':
            '"order01_whole_footprint_native_tile_frozen_detector"',
        "Complete deterministic native-pixel tile execution for the full order-61 POSS footprint.":
            "Complete deterministic native-pixel tile execution for the full order-01 POSS footprint.",
        "REFUSING: order61 row count=": "REFUSING: order01 row count=",
        "REFUSING: order61 ": "REFUSING: order01 ",
        "REFUSING: unexpected XE520 full shape ": "REFUSING: unexpected XE296 full shape ",
    }
    for old, new in output_replacements.items():
        if old in text:
            text = text.replace(old, new)

    # ------------------------------------------------------------------
    # Insert an Order-1 exact-source guard into the generated runner.
    # It validates the completed metadata preflight BEFORE method/JAR/geometry
    # work and deliberately does not re-fetch science pixels.
    # ------------------------------------------------------------------
    anchor = 'def main():\n'
    if text.count(anchor) != 1:
        raise RuntimeError(
            f"REFUSING: expected one main() anchor, got {text.count(anchor)}"
        )

    guard_function = r