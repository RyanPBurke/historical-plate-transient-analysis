
from __future__ import annotations

from pathlib import Path
import ast
import datetime as dt
import py_compile
import shutil

ROOT = Path.cwd()
AUTO = ROOT / "automation"
REG = AUTO / "registry_order01.py"
STAGE = AUTO / "stages" / "preflight_wide_heavy_detector_v054.py"
PAYLOAD = ROOT / "tools" / "_preflight_wide_heavy_detector_v054.payload.py"

ENTRY = """
    StageContract(
        stage_id="wide_census_heavy_detector_preflight_v054",
        title="Freeze detector endpoint identities, exact common-footprint tile workload and capacity",
        script="automation/stages/preflight_wide_heavy_detector_v054.py",
        requires=(
            "results/wide_census_exact_footprint_v052.json",
            "results/wide_census_detector_execution_plan_v053.json",
            "results/wide_census_detector_execution_queue_v053.csv",
            "config/candidate_adjudication_policy_v002.json",
            "research/NATIVE_TILE_EXECUTION_POLICY_V028_2026-08-21.json",
            "src/transient_pipeline/detector.py",
            "config/frozen_method.json",
        ),
        produces=(
            "results/wide_census_heavy_preflight_v054.json",
            "results/wide_census_detector_endpoint_plan_v054.csv",
            "results/wide_census_detector_pair_plan_v054.json",
            "results/wide_census_detector_tile_plan_v054.csv",
        ),
        dependencies=("wide_census_detector_execution_plan_v053",),
        network_access=True,
        retryable=True,
        notes="Metadata/capacity only. Resolves APPLAUSE scan/WCS/FITS identities and exact detector tiles. No science pixels or detector execution.",
    ),
"""


def add_entry(text):
    if 'stage_id="wide_census_heavy_detector_preflight_v054"' in text:
        return text, "already registered"

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
    lines.insert(container.end_lineno - 1, "\n" + ENTRY.rstrip() + "\n")

    out = "".join(lines)
    ast.parse(out)
    return out, f"inserted before ORDER01_STAGES closing line {container.end_lineno}"


def main():
    print("=" * 132)
    print("TRANSIENT AUTOMATION UPGRADE — HEAVY DETECTOR PREFLIGHT v054")
    print("=" * 132)
    print("INSTALLER: NO NETWORK. NO PIXELS. NO DETECTOR. NO CANDIDATE STATE MUTATION.\n")

    for path in (AUTO, REG, PAYLOAD):
        if not path.exists():
            raise RuntimeError(f"Missing installer input: {path}")

    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = ROOT / "patch_backups" / f"pre_v054_heavy_preflight_{stamp}"
    backup.mkdir(parents=True, exist_ok=False)
    shutil.copy2(REG, backup / REG.name)

    STAGE.parent.mkdir(parents=True, exist_ok=True)
    STAGE.write_text(
        PAYLOAD.read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    py_compile.compile(str(STAGE), doraise=True)

    text, note = add_entry(REG.read_text(encoding="utf-8"))
    REG.write_text(text, encoding="utf-8")
    print("Registry:", note)

    failures = []
    for path in sorted(
        p for p in AUTO.rglob("*.py")
        if "backups" not in p.parts
    ):
        try:
            py_compile.compile(str(path), doraise=True)
        except Exception as exc:
            failures.append((path, exc))
            print("FAIL", path.relative_to(ROOT), exc)

    if failures:
        raise RuntimeError("Compile regression after v054 install")

    print("Stage:", STAGE.relative_to(ROOT))
    print("\nUPGRADE STATUS: PASS")
    print("\nRun:")
    print(
        r'  & ".\.venv\Scripts\python.exe" '
        r'-m automation.runner run-until-blocked --allow-network'
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
