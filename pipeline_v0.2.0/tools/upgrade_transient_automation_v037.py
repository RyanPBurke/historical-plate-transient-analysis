from __future__ import annotations

from pathlib import Path
import ast
import datetime as dt
import json
import re
import shutil

ROOT = Path.cwd()
REGISTRY = ROOT / "automation" / "registry_order01.py"
INIT = ROOT / "automation" / "__init__.py"
PLAN = ROOT / "results" / "physical_overlap_survivor_execution_plan_v028ch.json"
STAGE_ID = "parameterized_native_worker_contract_v028ci"
STAGE_REL = "automation/stages/certify_parameterized_native_worker_contract_v028ci.py"
STAGE = ROOT / STAGE_REL
OUT_REL = "results/parameterized_native_worker_contract_v028ci.json"

STAGE_SOURCE = r'''from __future__ import annotations
from pathlib import Path
import ast
import csv
import hashlib
import json

ROOT = Path.cwd()
PLAN = ROOT / "results" / "physical_overlap_survivor_execution_plan_v028ch.json"
WORKER = ROOT / "tools" / "run_order61_whole_native_v028.py"
GEOMETRY = ROOT / "tools" / "repair_remaining_poss_geometry_v028.py"
CONTROL = ROOT / "tools" / "run_pair61_native_detector_control_v028.py"
POLICY = ROOT / "research" / "NATIVE_TILE_EXECUTION_POLICY_V028_2026-08-21.json"
OUT = ROOT / "results" / "parameterized_native_worker_contract_v028ci.json"
QUEUE = ROOT / "results" / "survivor_poss_reference_acquisition_queue_v028ci.csv"

EXPECTED = {
    "worker_sha256": "18206c150e792d72c144c7803bc7dd37d32ea4804f4f034de1e15db23d6c1c70",
    "geometry_sha256": "3ee68d3dee944f470130dac9120d8caa158905e845de5ea42e9179a966bf5ed4",
    "control_sha256": "42722ac50fcb784ed4f0594d7bbefa7b8dc9e8ae65ba22d2c61aebcb915f4291",
    "policy_sha256": "44fc3453c3291a7cbe72894d781729a30943ad540aa169b2c0897b446c5c8ec7",
}


def sha(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def functions(path):
    tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
    return sorted(n.name for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)))


def main():
    print("=" * 120)
    print("PARAMETERISED NATIVE WORKER — EXTRACTION CONTRACT AND REFERENCE QUEUE v028ci")
    print("=" * 120)
    print("NO NETWORK. NO PIXELS. No detector or candidate mutation.\n")
    for path in (PLAN, WORKER, GEOMETRY, CONTROL, POLICY):
        if not path.is_file():
            raise RuntimeError(f"Missing required input: {path}")
    actual = {"worker_sha256": sha(WORKER), "geometry_sha256": sha(GEOMETRY),
              "control_sha256": sha(CONTROL), "policy_sha256": sha(POLICY)}
    if actual != EXPECTED:
        raise RuntimeError(f"REFUSING: source provenance changed: expected={EXPECTED} actual={actual}")
    worker_functions, geometry_functions, control_functions = functions(WORKER), functions(GEOMETRY), functions(CONTROL)
    required_worker = {"guard_method", "freeze_policy", "compile_java", "geometry_sig", "output_rect_to_base",
                       "core_specs", "checkpoint_valid", "run_poss_tile", "run_dasch_tile", "retries", "crossmatch"}
    required_geometry = {"plate_center_radians", "dss_world"}
    required_control = {"tpv", "base_slice"}
    missing = {"worker": sorted(required_worker-set(worker_functions)),
               "geometry": sorted(required_geometry-set(geometry_functions)),
               "control": sorted(required_control-set(control_functions))}
    if any(missing.values()):
        raise RuntimeError("REFUSING: generic function contract incomplete: " + repr(missing))

    plan = json.loads(PLAN.read_text(encoding="utf-8"))
    if plan.get("execution_order") != [11, 28, 29, 24, 18]:
        raise RuntimeError("REFUSING: execution order changed")
    poss = plan.get("unique_poss_inputs") or []
    if len(poss) != 4:
        raise RuntimeError("REFUSING: expected four unique POSS inputs")
    rows = []
    for item in poss:
        band = str(item["poss_exposure"]).split(":")[2].upper()
        rows.append({"poss_exposure": item["poss_exposure"], "band": band, "region": item["region"],
                     "plate_id": item["plate_id"], "used_by_orders": ";".join(map(str,item["used_by_orders"])),
                     "required_reference": "small_exact_plate_cutout_with_complete_GSSS_header_and_local_celestial_WCS",
                     "reference_status": "REQUIRED_NOT_YET_FROZEN"})
    rows.sort(key=lambda x: min(map(int,x["used_by_orders"].split(";"))))
    with QUEUE.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader(); w.writerows(rows)

    unsafe_hardcodes = {
        "order": 61, "poss_identity": "POSS-I:875:E:rec521", "region": "XE520", "plate_id": "090N",
        "dasch_plate": "ai44092", "reference_fits": "Order-61-specific",
        "full_dimensions": "explicitly rejects anything other than 14000x13999",
        "work_and_result_directories": "Order-61-specific",
        "raw_crossmatch": "uses unregistered WCS coordinates; downstream local registration remains mandatory",
    }
    contract = {
        "runtime_identity_from_frozen_plan": True,
        "isolated_cache_key": "archive + physical plate identity + source checksum + detector/method/policy checksums",
        "poss_raw_directory_from_verified_hhh_parent": True,
        "dimensions_from_verified_header": True,
        "reference_validation_per_unique_poss_plate": True,
        "full_dense_poss_footprint_must_lie_inside_dasch": True,
        "detector_and_method_hashes_unchanged": True,
        "no_resampling": True,
        "raw_3arcsec_result_is_not_final_classification": True,
        "local_registration_required_before_strict_pair_decision": True,
    }
    result = {"status": "COMPLETE", "analysis_kind": "parameterized_native_worker_contract_v028ci",
              "guards": {"network_access": False, "science_pixels_read": False, "non_science_pixels_read": False,
                         "transient_detector_rerun": False, "candidate_state_mutation": False},
              "input_sha256": actual, "generic_function_contract": {"missing": missing, "pass": True},
              "unsafe_order61_hardcodes": unsafe_hardcodes, "parameterized_worker_contract": contract,
              "pair_opportunities": 5, "unique_poss_references_required": 4,
              "reference_queue_csv": str(QUEUE.relative_to(ROOT)).replace("\\","/"),
              "reference_queue": rows,
              "classification": "GENERIC_CORE_RECOVERABLE_PER_PLATE_REFERENCE_CERTIFICATION_REQUIRED",
              "next_stage": "Acquire and hash-pin four small exact-plate reference FITS files; validate GSSS polynomial against each local WCS before extracting full native tiles."}
    tmp = OUT.with_suffix(OUT.suffix + ".tmp")
    tmp.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(OUT)
    print("Generic worker functions: PASS")
    print("Frozen source hashes: PASS")
    print("Unsafe Order-61 assumptions isolated: PASS")
    print("Per-plate reference queue: 4")
    print(f"Outputs: {OUT}, {QUEUE}\nSTAGE STATUS: PASS")


if __name__ == "__main__":
    main()
'''


def main():
    print("=" * 120)
    print("TRANSIENT AUTOMATION UPGRADE v0.3.7 — PARAMETERISED NATIVE WORKER CONTRACT")
    print("=" * 120)
    print("NO NETWORK. NO PIXELS. No detector or candidate mutation.\n")
    for path in (REGISTRY, INIT, PLAN):
        if not path.is_file():
            raise RuntimeError(f"Missing required input: {path}")
    ast.parse(STAGE_SOURCE, filename=str(STAGE))
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = ROOT / "automation" / "backups" / f"pre_v037_worker_contract_{stamp}"
    backup.mkdir(parents=True, exist_ok=False)
    shutil.copy2(REGISTRY, backup / REGISTRY.name); shutil.copy2(INIT, backup / INIT.name)
    STAGE.parent.mkdir(parents=True, exist_ok=True)
    STAGE.write_text(STAGE_SOURCE, encoding="utf-8", newline="\n")
    registry = REGISTRY.read_text(encoding="utf-8")
    if STAGE_ID not in registry:
        marker = re.search(r"\n\]\s*\n\s*def by_id\(\):", registry)
        if not marker: raise RuntimeError("REFUSING: registry closing marker not found")
        contract = f'''\n\n    StageContract(\n        stage_id="{STAGE_ID}",\n        title="Certify generic native-worker core and queue four plate references",\n        script="{STAGE_REL}",\n        requires=("results/physical_overlap_survivor_execution_plan_v028ch.json", "tools/run_order61_whole_native_v028.py", "tools/repair_remaining_poss_geometry_v028.py", "tools/run_pair61_native_detector_control_v028.py", "research/NATIVE_TILE_EXECUTION_POLICY_V028_2026-08-21.json"),\n        produces=("{OUT_REL}",),\n        dependencies=("physical_overlap_survivor_execution_plan_v028ch",),\n        notes="No network/pixels; hash-pins reusable functions and isolates Order-61-specific assumptions.",\n    ),\n'''
        registry = registry[:marker.start()] + contract + registry[marker.start():]
        ast.parse(registry, filename=str(REGISTRY)); REGISTRY.write_text(registry, encoding="utf-8", newline="\n")
    init = re.sub(r'__version__\s*=\s*["\'][^"\']+["\']', '__version__ = "0.3.13"', INIT.read_text(encoding="utf-8"), count=1)
    ast.parse(init, filename=str(INIT)); INIT.write_text(init, encoding="utf-8", newline="\n")
    print(f"Installed stage: {STAGE_ID}")
    print(f"Backup: {backup}\n\nUPGRADE STATUS: PASS")


if __name__ == "__main__": main()
