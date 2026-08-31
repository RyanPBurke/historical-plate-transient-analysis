
from __future__ import annotations

from pathlib import Path
import ast
import datetime as dt
import py_compile
import shutil

ROOT = Path.cwd()
AUTO = ROOT / "automation"
REG = AUTO / "registry_order01.py"

PAY055 = ROOT / "tools" / "_certify_disk_bounded_execution_v055.payload.py"
PAY056 = ROOT / "tools" / "_execute_wide_frozen_detector_v056.payload.py"

STAGE055 = AUTO / "stages" / "certify_disk_bounded_execution_v055.py"
STAGE056 = AUTO / "stages" / "execute_wide_frozen_detector_v056.py"

ENTRIES = """
    StageContract(
        stage_id="wide_census_disk_bounded_execution_contract_v055",
        title="Certify disk-bounded native-tile persistence contract for heavy detector run",
        script="automation/stages/certify_disk_bounded_execution_v055.py",
        requires=(
            "results/wide_census_heavy_preflight_v054.json",
            "results/wide_census_detector_endpoint_plan_v054.csv",
            "results/wide_census_detector_pair_plan_v054.json",
            "results/wide_census_detector_tile_plan_v054.csv",
            "src/transient_pipeline/detector.py",
            "config/frozen_method.json",
            "research/NATIVE_TILE_EXECUTION_POLICY_V028_2026-08-21.json",
        ),
        produces=(
            "results/wide_census_disk_bounded_execution_contract_v055.json",
        ),
        dependencies=("wide_census_heavy_detector_preflight_v054",),
        notes="Local-only storage architecture certification. No science pixels/detector. Native tile arrays are hashed in-memory during v056 but not persisted.",
    ),

    StageContract(
        stage_id="wide_census_disk_bounded_frozen_detector_v056",
        title="Resumable frozen detector execution across robust wide-census opportunities",
        script="automation/stages/execute_wide_frozen_detector_v056.py",
        requires=(
            "results/wide_census_disk_bounded_execution_contract_v055.json",
            "results/wide_census_heavy_preflight_v054.json",
            "results/wide_census_detector_endpoint_plan_v054.csv",
            "results/wide_census_detector_pair_plan_v054.json",
            "results/wide_census_detector_tile_plan_v054.csv",
            "results/wide_census_heavy_preflight_v054/cache/applause_selected_solution_rows.json",
            "src/transient_pipeline/detector.py",
            "config/frozen_method.json",
            "research/NATIVE_TILE_EXECUTION_POLICY_V028_2026-08-21.json",
        ),
        produces=(
            "results/wide_census_detector_execution_v056.json",
            "results/wide_census_detector_candidates_v056.csv",
            "results/wide_census_pair_raw_match_summary_v056.csv",
            "results/wide_census_pair_raw_matches_v056.csv",
        ),
        dependencies=("wide_census_disk_bounded_execution_contract_v055",),
        network_access=True,
        science_pixels_read=True,
        transient_detector_rerun=True,
        retryable=True,
        notes="Actual heavy run. Frozen native detector, 1024-core/64-halo, no resampling/retuning. At most 32 tiles per checkpoint cycle; successful tile pixels are hashed but not persisted.",
    ),
"""


def add_entries(text):
    wanted = (
        'stage_id="wide_census_disk_bounded_execution_contract_v055"',
        'stage_id="wide_census_disk_bounded_frozen_detector_v056"',
    )
    if all(x in text for x in wanted):
        return text, "already registered"
    if any(x in text for x in wanted):
        raise RuntimeError("REFUSING: partial v055/v056 registration detected")

    tree = ast.parse(text)
    container = None
    for node in tree.body:
        value = None
        matched = False
        if isinstance(node, ast.Assign):
            value = node.value
            matched = any(
                isinstance(t, ast.Name) and t.id == "ORDER01_STAGES"
                for t in node.targets
            )
        elif isinstance(node, ast.AnnAssign):
            value = node.value
            matched = (
                isinstance(node.target, ast.Name)
                and node.target.id == "ORDER01_STAGES"
            )
        if matched and isinstance(value, (ast.List, ast.Tuple)):
            container = value
            break

    if container is None:
        raise RuntimeError("ORDER01_STAGES list/tuple not found")

    lines = text.splitlines(keepends=True)
    lines.insert(container.end_lineno - 1, "\n" + ENTRIES.rstrip() + "\n")
    out = "".join(lines)
    ast.parse(out)
    return out, f"inserted before ORDER01_STAGES closing line {container.end_lineno}"


def main():
    print("=" * 132)
    print("TRANSIENT AUTOMATION UPGRADE — DISK-BOUNDED HEAVY DETECTOR v055/v056")
    print("=" * 132)
    print("INSTALLER: NO NETWORK. NO PIXELS. NO DETECTOR. NO CANDIDATE STATE MUTATION.\n")

    for p in (AUTO, REG, PAY055, PAY056):
        if not p.exists():
            raise RuntimeError(f"Missing installer input: {p}")

    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = ROOT / "patch_backups" / f"pre_v055_v056_{stamp}"
    backup.mkdir(parents=True, exist_ok=False)
    shutil.copy2(REG, backup / REG.name)

    STAGE055.parent.mkdir(parents=True, exist_ok=True)
    STAGE055.write_text(PAY055.read_text(encoding="utf-8"), encoding="utf-8")
    STAGE056.write_text(PAY056.read_text(encoding="utf-8"), encoding="utf-8")
    py_compile.compile(str(STAGE055), doraise=True)
    py_compile.compile(str(STAGE056), doraise=True)

    text, note = add_entries(REG.read_text(encoding="utf-8"))
    REG.write_text(text, encoding="utf-8")

    failures = []
    for p in sorted(x for x in AUTO.rglob("*.py") if "backups" not in x.parts):
        try:
            py_compile.compile(str(p), doraise=True)
        except Exception as exc:
            failures.append((p, exc))
            print("FAIL", p.relative_to(ROOT), exc)

    if failures:
        raise RuntimeError("Compile regression after v055/v056 install")

    print("Registry:", note)
    print("Stage:", STAGE055.relative_to(ROOT))
    print("Stage:", STAGE056.relative_to(ROOT))
    print("\nUPGRADE STATUS: PASS")
    print("\nThis command now starts the actual heavy run:")
    print(
        r'  & ".\.venv\Scripts\python.exe" '
        r'-m automation.runner run-until-blocked --allow-network'
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
