from __future__ import annotations

"""Install the resumable frozen native-pixel execution stage for Order 11."""

from pathlib import Path
from datetime import datetime, timezone
import ast
import hashlib
import re
import shutil


ROOT = Path.cwd()
SOURCE = ROOT / "tools" / "run_order61_whole_native_v028.py"
STAGE = ROOT / "automation" / "stages" / "execute_order11_whole_native_v028cl.py"
REGISTRY = ROOT / "automation" / "registry_order01.py"
INIT = ROOT / "automation" / "__init__.py"
EXPECTED_SOURCE_SHA = "18206c150e792d72c144c7803bc7dd37d32ea4804f4f034de1e15db23d6c1c70"


REPLACEMENTS = (
    ('ORDER = 61', 'ORDER = 11'),
    ('POSS_ID, REGION, POSS_PLATE, DASCH_PLATE = "POSS-I:875:E:rec521", "XE520", "090N", "ai44092"',
     'POSS_ID, REGION, POSS_PLATE, DASCH_PLATE = "POSS-I:779:E:rec404", "XE403", "0733", "fa13177"'),
    ('REF = ROOT / "cache/poss1_exact_plate_cutout_preflight_v028b/POSS-I_875_E_rec521/XE520_090N_preflight.fits"',
     'REF = ROOT / "cache/survivor_poss_coordinate_references_v028cj/POSS-I_779_E_rec404/XE403_0733_coordinate_reference.fits"'),
    ('WORK = ROOT / "work/order61_native_full_v028"', 'WORK = ROOT / "work/order11_native_full_v028"'),
    ('RESULT = ROOT / "results/order61_native_full_v028"', 'RESULT = ROOT / "results/order11_native_full_v028"'),
    ('UA = "historical-transient-pipeline/0.2.8-order61-whole-pair"',
     'UA = "historical-transient-pipeline/0.2.8-order11-whole-pair"'),
    ('POSS_RAW = "https://skyview.gsfc.nasa.gov/surveys/dss/xe520"',
     'POSS_RAW = "https://skyview.gsfc.nasa.gov/surveys/dss/xe403"'),
    ('RESULT/"order61_incomplete_report.json"', 'RESULT/"order11_incomplete_report.json"'),
    ('RESULT/"order61_poss_native_candidates.csv"', 'RESULT/"order11_poss_native_candidates.csv"'),
    ('RESULT/"order61_dasch_native_candidates.csv"', 'RESULT/"order11_dasch_native_candidates.csv"'),
    ('RESULT/"order61_raw_coincidences.csv"', 'RESULT/"order11_raw_coincidences.csv"'),
    ('"run_kind":"order61_whole_footprint_native_tile_frozen_detector"',
     '"run_kind":"order11_whole_footprint_native_tile_frozen_detector"'),
    ('RESULT/"order61_whole_pair_report.json"', 'RESULT/"order11_whole_pair_report.json"'),
)


CONTRACT = '''    StageContract(
        stage_id="order11_whole_native_execution_v028cl",
        title="Resumable whole-footprint frozen native detector execution for Order 11",
        script="automation/stages/execute_order11_whole_native_v028cl.py",
        requires=(
            "results/order11_native_preflight_v028/order11_native_execution_preflight_v028ck.json",
            "results/survivor_poss_reference_acquisition_v028cj.json",
            "results/parameterized_native_worker_contract_v028ci.json",
            "src/transient_pipeline/detector.py",
            "config/frozen_method.json",
            "research/NATIVE_TILE_EXECUTION_POLICY_V028_2026-08-21.json",
        ),
        produces=("results/order11_native_full_v028/order11_whole_pair_report.json",),
        dependencies=("order11_native_execution_preflight_v028ck",),
        network_access=True,
        science_pixels_read=True,
        transient_detector_rerun=True,
        notes="Frozen detector on new Order-11 POSS/DASCH native pixels; resumable 1024px cores with 64px halo; raw matches are not classifications.",
    ),
'''


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def main():
    print("=" * 120)
    print("TRANSIENT AUTOMATION UPGRADE v0.4.0 — ORDER-11 RESUMABLE NATIVE EXECUTION")
    print("=" * 120)
    print("NO NETWORK DURING INSTALL. NO PIXELS. No detector or candidate mutation.\n")
    for p in (SOURCE, REGISTRY, INIT):
        if not p.is_file():
            raise RuntimeError(f"Missing required file: {p}")
    actual = sha(SOURCE)
    if actual != EXPECTED_SOURCE_SHA:
        raise RuntimeError(f"REFUSING: validated Order-61 worker SHA changed: {actual}")
    text = SOURCE.read_text(encoding="utf-8-sig")
    for old, new in REPLACEMENTS:
        count = text.count(old)
        if count != 1:
            raise RuntimeError(f"REFUSING: expected exactly one worker replacement target; found {count}: {old}")
        text = text.replace(old, new, 1)

    # Add the machine-readable execution guards required by the verifier.
    report_anchor = '"status":"COMPLETE","run_kind":"order11_whole_footprint_native_tile_frozen_detector",'
    report_replacement = (
        '"status":"COMPLETE","run_kind":"order11_whole_footprint_native_tile_frozen_detector",'
        '"guards":{"network_access":True,"science_pixels_read":True,'
        '"non_science_pixels_read":False,"transient_detector_rerun":True,'
        '"candidate_state_mutation":False},'
    )
    if text.count(report_anchor) != 1:
        raise RuntimeError("REFUSING: complete-report insertion point was not found exactly once")
    text = text.replace(report_anchor, report_replacement, 1)
    ast.parse(text, filename=str(STAGE))

    registry = REGISTRY.read_text(encoding="utf-8-sig")
    if "order11_whole_native_execution_v028cl" in registry:
        raise RuntimeError("REFUSING: v028cl is already registered")
    marker = "]\n\ndef by_id()"
    if marker not in registry:
        raise RuntimeError("REFUSING: registry insertion marker not found")

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = ROOT / "automation" / "backups" / f"pre_v040_order11_native_{stamp}"
    backup.mkdir(parents=True, exist_ok=False)
    shutil.copy2(REGISTRY, backup / REGISTRY.name)
    shutil.copy2(INIT, backup / INIT.name)
    if STAGE.exists():
        shutil.copy2(STAGE, backup / STAGE.name)

    STAGE.parent.mkdir(parents=True, exist_ok=True)
    STAGE.write_text(text, encoding="utf-8")
    REGISTRY.write_text(registry.replace(marker, "\n" + CONTRACT + marker, 1), encoding="utf-8")
    init = INIT.read_text(encoding="utf-8-sig")
    init = re.sub(r'__version__\s*=\s*["\'][^"\']+["\']', '__version__ = "0.4.0"', init, count=1)
    INIT.write_text(init, encoding="utf-8")
    ast.parse(STAGE.read_text(encoding="utf-8"), filename=str(STAGE))
    ast.parse(REGISTRY.read_text(encoding="utf-8"), filename=str(REGISTRY))

    print("Validated source worker SHA: PASS")
    print("Installed stage: order11_whole_native_execution_v028cl")
    print("Checkpoint policy: valid completed tiles are skipped on rerun")
    print(f"Backup: {backup}")
    print("\nUPGRADE STATUS: PASS")


if __name__ == "__main__":
    main()
