from __future__ import annotations

from pathlib import Path
import hashlib
import json
import py_compile

ROOT = Path.cwd()

SOURCE = ROOT / "tools" / "run_order61_whole_native_v028.py"
ORDER01_PREFLIGHT = (
    ROOT / "results" / "order01_native_preflight_v028"
    / "order01_exact_native_source_and_dasch_metadata_v028.json"
)
POLICY = ROOT / "research" / "NATIVE_TILE_EXECUTION_POLICY_V028_2026-08-21.json"
TARGET = ROOT / "tools" / "run_order01_whole_native_v028.py"
MANIFEST = (
    ROOT / "results" / "order01_native_preflight_v028"
    / "order01_runner_generation_manifest_v028b.json"
)

EXPECTED_DETECTOR_SHA = "709da8d7a7972b15808d70a1e4dbffa0fd0fee864a81d954f74fe4a5f5af25e7"
EXPECTED_METHOD_SHA = "2cb3cabd573d7af99399899f2ccecd3002be90297e55bb0e0dcdd9dea1d0c4c1"
EXPECTED_POLICY_SHA = "44fc3453c3291a7cbe72894d781729a30943ad540aa169b2c0897b446c5c8ec7"
EXPECTED_JAR_SHA = "8483a20d986bb61fa1d733ce16d446fb2a0ff363bc1b1367e28b01a1bbdcbb8d"

GUARD_FUNCTION = 'def guard_order01_exact_source_preflight():\n    p = (\n        ROOT / "results" / "order01_native_preflight_v028"\n        / "order01_exact_native_source_and_dasch_metadata_v028.json"\n    )\n    if not p.is_file():\n        raise RuntimeError(\n            f"REFUSING: Order-1 exact native-source preflight missing: {p}"\n        )\n\n    obj = json.loads(p.read_text(encoding="utf-8"))\n    if obj.get("status") != "COMPLETE":\n        raise RuntimeError(\n            "REFUSING: Order-1 exact native-source preflight is not COMPLETE"\n        )\n\n    pair = obj["frozen_pair_map_row"]\n    src = obj["poss_native_source"]\n    ref = obj["frozen_poss_identity_fits"]\n    dp = obj["dasch_mosaic_package"]\n\n    checks = {\n        "canonical_order": int(float(pair["canonical_order"])) == 1,\n        "poss_id": pair["poss_exposure_id"] == POSS_ID,\n        "region": pair["poss_region"] == REGION,\n        "plate_id": ref["plate_id"] == POSS_PLATE,\n        "dasch": pair["partner_dasch_plate_id"].lower() == DASCH_PLATE,\n        "overlap": abs(float(pair["actual_overlap_s"]) - 3480.0) < 1e-6,\n        "fits_sha": ref["sha256"].lower()\n            == "6e8ca42e82804615316845436c934d0b184a5deddeeee9ab0c6951736088fa16",\n        "raw_dir": src["raw_plate_directory"].rstrip("/") == POSS_RAW,\n        "hhh_sha": src["hhh_sha256"].lower()\n            == "e7fce1b323623e4bb6a82e16537cb3728e620870a4a64d36bdc05b05756b37d2",\n        "hhh_region": src["hhh_identity"]["region"].upper() == REGION,\n        "hhh_plate": src["hhh_identity"]["plate_id"].upper() == POSS_PLATE,\n        "hhh_width": int(src["hhh_header_parse"]["selected_header"]["XPIXELS"]) == 14000,\n        "hhh_height": int(src["hhh_header_parse"]["selected_header"]["YPIXELS"]) == 13999,\n        "dasch_base_url": bool(dp.get("baseFitsUrl")),\n        "dasch_metadata": dp.get("metadata") is not None,\n        "preflight_no_detector": obj.get("detector_rerun") is False,\n        "preflight_no_poss_pixels": obj.get("native_science_pixels_read") is False,\n        "preflight_no_dasch_pixels": obj.get("dasch_science_pixels_read") is False,\n    }\n    if not all(checks.values()):\n        raise RuntimeError(\n            "REFUSING: Order-1 exact-source preflight guard failed: "\n            + repr(checks)\n        )\n    return obj\n\n'


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


def main():
    print("=" * 112)
    print("GENERATE ORDER 01 WHOLE-NATIVE RUNNER FROM VALIDATED ORDER 61 WORKER — v028b")
    print("=" * 112)
    print("Generator only: no detector execution and no science pixels.")
    print()

    for p in (SOURCE, ORDER01_PREFLIGHT, POLICY):
        require_file(p)

    detector = ROOT / "src" / "transient_pipeline" / "detector.py"
    method = ROOT / "config" / "frozen_method.json"
    require_file(detector)
    require_file(method)

    detector_sha = sha_file(detector)
    method_sha = sha_file(method)
    policy_sha = sha_file(POLICY)

    if detector_sha != EXPECTED_DETECTOR_SHA:
        raise RuntimeError(f"REFUSING: detector SHA changed: {detector_sha}")
    if method_sha != EXPECTED_METHOD_SHA:
        raise RuntimeError(f"REFUSING: method SHA changed: {method_sha}")
    if policy_sha != EXPECTED_POLICY_SHA:
        raise RuntimeError(f"REFUSING: tile-policy SHA changed: {policy_sha}")

    pre = json.loads(ORDER01_PREFLIGHT.read_text(encoding="utf-8"))
    if pre.get("status") != "COMPLETE":
        raise RuntimeError("REFUSING: Order-1 exact-source preflight is not COMPLETE")

    pair = pre["frozen_pair_map_row"]
    src = pre["poss_native_source"]
    ref = pre["frozen_poss_identity_fits"]
    dp = pre["dasch_mosaic_package"]

    guards = {
        "canonical_order": int(float(pair["canonical_order"])) == 1,
        "poss_id": pair["poss_exposure_id"] == "POSS-I:413:E:rec297",
        "region": pair["poss_region"] == "XE296",
        "plate_id": ref["plate_id"] == "06S2",
        "dasch": pair["partner_dasch_plate_id"].lower() == "ai43437",
        "overlap": abs(float(pair["actual_overlap_s"]) - 3480.0) < 1e-6,
        "fits_sha": ref["sha256"].lower()
            == "6e8ca42e82804615316845436c934d0b184a5deddeeee9ab0c6951736088fa16",
        "raw_dir": src["raw_plate_directory"].rstrip("/")
            == "https://skyview.gsfc.nasa.gov/surveys/dss/xe296",
        "hhh_sha": src["hhh_sha256"].lower()
            == "e7fce1b323623e4bb6a82e16537cb3728e620870a4a64d36bdc05b05756b37d2",
        "hhh_region": src["hhh_identity"]["region"].upper() == "XE296",
        "hhh_plate": src["hhh_identity"]["plate_id"].upper() == "06S2",
        "hhh_width": int(src["hhh_header_parse"]["selected_header"]["XPIXELS"]) == 14000,
        "hhh_height": int(src["hhh_header_parse"]["selected_header"]["YPIXELS"]) == 13999,
        "dasch_base_url_present": bool(dp.get("baseFitsUrl")),
        "dasch_metadata_present": dp.get("metadata") is not None,
        "no_detector_preflight": pre.get("detector_rerun") is False,
        "no_poss_pixels_preflight": pre.get("native_science_pixels_read") is False,
        "no_dasch_pixels_preflight": pre.get("dasch_science_pixels_read") is False,
    }
    if not all(guards.values()):
        raise RuntimeError("REFUSING: Order-1 preflight guard failure: " + repr(guards))

    print("Order-1 exact-source / frozen-method guards: PASS")
    print(f"  detector SHA: {detector_sha}")
    print(f"  method SHA:   {method_sha}")
    print(f"  policy SHA:   {policy_sha}")
    print()

    source_text = SOURCE.read_text(encoding="utf-8")
    source_sha = sha_file(SOURCE)

    structural_tokens = [
        'ORDER = 61',
        'POSS_ID, REGION, POSS_PLATE, DASCH_PLATE = "POSS-I:875:E:rec521", "XE520", "090N", "ai44092"',
        'CORE, HALO, DASCH_BOUND_PAD, GEOM_GRID = 1024, 64, 256, 65',
        'EXPECTED_DETECTOR_SHA = "709da8d7a7972b15808d70a1e4dbffa0fd0fee864a81d954f74fe4a5f5af25e7"',
        'EXPECTED_METHOD_SHA = "2cb3cabd573d7af99399899f2ccecd3002be90297e55bb0e0dcdd9dea1d0c4c1"',
        'EXPECTED_JAR_SHA = "8483a20d986bb61fa1d733ce16d446fb2a0ff363bc1b1367e28b01a1bbdcbb8d"',
        'POSS_RAW = "https://skyview.gsfc.nasa.gov/surveys/dss/xe520"',
        'POLICY = ROOT / "research/NATIVE_TILE_EXECUTION_POLICY_V028_2026-08-21.json"',
        'CONTROL_SOURCE = ROOT / "tools/run_pair61_native_detector_control_v028.py"',
        'from transient_pipeline.detector import detect_array',
        'def main():',
    ]
    missing = [x for x in structural_tokens if x not in source_text]
    if missing:
        raise RuntimeError(
            "REFUSING: Order-61 source structure drifted:\n" + "\n".join(missing)
        )

    text = source_text

    text = replace_once(text, 'ORDER = 61', 'ORDER = 1', 'ORDER')
    text = replace_once(
        text,
        'POSS_ID, REGION, POSS_PLATE, DASCH_PLATE = "POSS-I:875:E:rec521", "XE520", "090N", "ai44092"',
        'POSS_ID, REGION, POSS_PLATE, DASCH_PLATE = "POSS-I:413:E:rec297", "XE296", "06S2", "ai43437"',
        'pair constants',
    )
    text = replace_once(
        text,
        'REF = ROOT / "cache/poss1_exact_plate_cutout_preflight_v028b/POSS-I_875_E_rec521/XE520_090N_preflight.fits"',
        'REF = ROOT / "cache/poss1_identity/POSS-I_413_E_rec297/06S2_identity.fits"',
        'reference FITS',
    )
    text = replace_once(
        text,
        'WORK = ROOT / "work/order61_native_full_v028"',
        'WORK = ROOT / "work/order01_native_full_v028"',
        'work dir',
    )
    text = replace_once(
        text,
        'RESULT = ROOT / "results/order61_native_full_v028"',
        'RESULT = ROOT / "results/order01_native_full_v028"',
        'result dir',
    )
    text = replace_once(
        text,
        'UA = "historical-transient-pipeline/0.2.8-order61-whole-pair"',
        'UA = "historical-transient-pipeline/0.2.8-order01-whole-pair"',
        'user agent',
    )
    text = replace_once(
        text,
        'POSS_RAW = "https://skyview.gsfc.nasa.gov/surveys/dss/xe520"',
        'POSS_RAW = "https://skyview.gsfc.nasa.gov/surveys/dss/xe296"',
        'raw DSS source',
    )

    # Pair-specific final products/report labels only.
    replacements = {
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
        "ORDER 61 â€” RESUMABLE WHOLE-FOOTPRINT NATIVE DETECTOR EXECUTION":
            "ORDER 01 — RESUMABLE WHOLE-FOOTPRINT NATIVE DETECTOR EXECUTION",
        "ORDER 61 — RESUMABLE WHOLE-FOOTPRINT NATIVE DETECTOR EXECUTION":
            "ORDER 01 — RESUMABLE WHOLE-FOOTPRINT NATIVE DETECTOR EXECUTION",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)

    # Insert runtime guard immediately before the original main().
    if text.count("def main():\n") != 1:
        raise RuntimeError(
            f"REFUSING: expected exactly one main() definition, got {text.count('def main():')}"
        )
    text = text.replace(
        "def main():\n",
        GUARD_FUNCTION
        + "def main():\n"
        + "    order01_preflight = guard_order01_exact_source_preflight()\n"
        + '    print("Order-1 exact native-source preflight guard: PASS")\n',
        1,
    )

    # Intentionally preserve pair-61 environment/JAR provenance and frozen-policy provenance.
    retained = [
        'CONTROL_SOURCE = ROOT / "tools/run_pair61_native_detector_control_v028.py"',
        '/ "pair61_native_detector_control_v028"',
        '/ "pair61_native_detector_control_report.json"',
        '"fixed_before_complete_order61_footprint_outcome": True',
        '"note_order61_central_control_already_seen": True',
        'EXPECTED_JAR_SHA = "8483a20d986bb61fa1d733ce16d446fb2a0ff363bc1b1367e28b01a1bbdcbb8d"',
    ]
    missing_retained = [x for x in retained if x not in text]
    if missing_retained:
        raise RuntimeError(
            "REFUSING: frozen environment/policy provenance was removed:\n"
            + "\n".join(missing_retained)
        )

    forbidden_science_tokens = [
        "POSS-I:875:E:rec521",
        '"XE520"',
        '"090N"',
        '"ai44092"',
        "https://skyview.gsfc.nasa.gov/surveys/dss/xe520",
        "cache/poss1_exact_plate_cutout_preflight_v028b/POSS-I_875_E_rec521/XE520_090N_preflight.fits",
        'work/order61_native_full_v028',
        'results/order61_native_full_v028',
        '"order61_poss_native_candidates.csv"',
        '"order61_dasch_native_candidates.csv"',
        '"order61_raw_coincidences.csv"',
        '"order61_whole_pair_report.json"',
    ]
    stale = [x for x in forbidden_science_tokens if x in text]
    if stale:
        raise RuntimeError(
            "REFUSING: stale Order-61 SCIENCE tokens remain:\n" + "\n".join(stale)
        )

    intended = [
        'ORDER = 1',
        '"POSS-I:413:E:rec297"',
        '"XE296"',
        '"06S2"',
        '"ai43437"',
        'cache/poss1_identity/POSS-I_413_E_rec297/06S2_identity.fits',
        'work/order01_native_full_v028',
        'results/order01_native_full_v028',
        'https://skyview.gsfc.nasa.gov/surveys/dss/xe296',
        '"order01_whole_pair_report.json"',
        "guard_order01_exact_source_preflight",
        "detect_array(",
        'if __name__ == "__main__":',
    ]
    missing_intended = [x for x in intended if x not in text]
    if missing_intended:
        raise RuntimeError(
            "REFUSING: generated runner is missing required Order-1 structure:\n"
            + "\n".join(missing_intended)
        )

    # Write only after every transformation guard has passed.
    TARGET.write_text(text, encoding="utf-8")
    try:
        py_compile.compile(str(TARGET), doraise=True)
    except Exception:
        TARGET.unlink(missing_ok=True)
        raise

    # Critical regression guard for the failure in the previous generator.
    tail = "\n".join(TARGET.read_text(encoding="utf-8").splitlines()[-20:])
    if 'if __name__ == "__main__":' not in tail or "main()" not in tail:
        TARGET.unlink(missing_ok=True)
        raise RuntimeError(
            "REFUSING: generated runner lacks executable __main__ tail"
        )

    target_sha = sha_file(TARGET)

    manifest = {
        "status": "COMPLETE",
        "analysis_kind": "order01_runner_generation_v028b",
        "source": str(SOURCE),
        "source_sha256": source_sha,
        "target": str(TARGET),
        "target_sha256": target_sha,
        "guards": guards,
        "frozen": {
            "detector_sha256": detector_sha,
            "method_sha256": method_sha,
            "tile_policy_sha256": policy_sha,
            "skyview_jar_sha256": EXPECTED_JAR_SHA,
        },
        "science_executed": False,
        "detector_rerun": False,
        "science_pixels_read": False,
        "prior_generator_failure": {
            "worker": "generate_order01_whole_native_runner_v028.py",
            "failure": "downloadable generator truncated at guard_function = r",
            "local_science_effect": "none",
            "repo_science_outputs_created": False,
        },
        "next_command": (
            '& ".\\.venv\\Scripts\\python.exe" '
            '".\\tools\\run_order01_whole_native_v028.py"'
        ),
    }

    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    tmp = MANIFEST.with_suffix(MANIFEST.suffix + ".tmp")
    tmp.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(MANIFEST)

    print("Generated Order-1 runner: PASS")
    print(f"  source SHA256: {source_sha}")
    print(f"  target:        {TARGET}")
    print(f"  target SHA256: {target_sha}")
    print("  py_compile:    PASS")
    print("  __main__ tail: PASS")
    print()
    print("Science has NOT been executed.")
    print("Next command:")
    print('& ".\\.venv\\Scripts\\python.exe" ".\\tools\\run_order01_whole_native_v028.py"')


if __name__ == "__main__":
    main()
