
from __future__ import annotations

from pathlib import Path
import ast
import datetime as dt
import py_compile
import shutil

ROOT = Path.cwd()
AUTO = ROOT / "automation"
REG = AUTO / "registry_order01.py"

PAY050 = ROOT / "tools" / "_finalize_wide_timing_v050.payload.py"
PAY051 = ROOT / "tools" / "_plan_wide_footprints_v051.payload.py"

STAGE050 = AUTO / "stages" / "finalize_wide_timing_v050.py"
STAGE051 = AUTO / "stages" / "plan_wide_footprints_v051.py"

ENTRIES = """
    StageContract(
        stage_id="wide_census_timing_final_v050",
        title="Finalize wide timing census from authoritative VI/25 timing",
        script="automation/stages/finalize_wide_timing_v050.py",
        requires=(
            "results/wide_census_physical_timing_v049a.json",
            "results/wide_census_physical_timing_queue_v048.csv",
            "research/census_inputs/poss1_plate_metadata.csv",
            "results/poss_legacy_identity_resolution_audit_v049a.csv",
            "config/candidate_adjudication_policy_v002.json",
        ),
        produces=(
            "results/wide_census_physical_timing_final_v050.json",
            "results/wide_census_physical_timing_final_v050.csv",
            "results/wide_census_timing_survivors_v050.csv",
            "results/wide_census_timing_nonopportunities_v050.csv",
        ),
        dependencies=("wide_census_poss_legacy_identity_repair_v049a",),
        notes="No network/pixels/detector/state mutation. Completes timing for residual POSS rows using vi25_start_utc; unresolved physical-scan provenance is retained separately.",
    ),

    StageContract(
        stage_id="wide_census_footprint_plan_v051",
        title="Freeze exact-footprint and physical-independence execution queue",
        script="automation/stages/plan_wide_footprints_v051.py",
        requires=(
            "results/wide_census_physical_timing_final_v050.json",
            "research/census_inputs/archive_pair_overlap_candidates.csv",
            "research/census_inputs/applause_exposures_1951_1955.csv",
            "config/candidate_adjudication_policy_v002.json",
        ),
        produces=(
            "results/wide_census_footprint_plan_v051.json",
            "results/wide_census_exact_footprint_queue_v051.csv",
            "results/wide_census_independence_closed_v051.csv",
        ),
        dependencies=("wide_census_timing_final_v050",),
        notes="No network/pixels/detector/state mutation. Coarse FOV is prioritization only; all independent timing survivors proceed to exact archive-derived footprint geometry.",
    ),
"""


def add_entries(text):
    wanted = (
        'stage_id="wide_census_timing_final_v050"',
        'stage_id="wide_census_footprint_plan_v051"',
    )
    if all(x in text for x in wanted):
        return text, "already registered"

    if any(x in text for x in wanted):
        raise RuntimeError("REFUSING: partial v050/v051 registration detected")

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
            matched = isinstance(node.target, ast.Name) and node.target.id == "ORDER01_STAGES"

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
    print("TRANSIENT AUTOMATION UPGRADE — FINAL TIMING + FOOTPRINT PLAN v050/v051")
    print("=" * 132)
    print("INSTALLER: NO NETWORK. NO PIXELS. NO DETECTOR. NO CANDIDATE STATE MUTATION.\n")

    for path in (AUTO, REG, PAY050, PAY051):
        if not path.exists():
            raise RuntimeError(f"Missing installer input: {path}")

    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = ROOT / "patch_backups" / f"pre_v050_v051_{stamp}"
    backup.mkdir(parents=True, exist_ok=False)
    shutil.copy2(REG, backup / REG.name)

    STAGE050.parent.mkdir(parents=True, exist_ok=True)
    STAGE050.write_text(PAY050.read_text(encoding="utf-8"), encoding="utf-8")
    STAGE051.write_text(PAY051.read_text(encoding="utf-8"), encoding="utf-8")
    py_compile.compile(str(STAGE050), doraise=True)
    py_compile.compile(str(STAGE051), doraise=True)

    text, note = add_entries(REG.read_text(encoding="utf-8"))
    REG.write_text(text, encoding="utf-8")
    print("Registry:", note)

    failures = []
    for path in sorted(p for p in AUTO.rglob("*.py") if "backups" not in p.parts):
        try:
            py_compile.compile(str(path), doraise=True)
        except Exception as exc:
            failures.append((path, exc))
            print("FAIL", path.relative_to(ROOT), exc)

    if failures:
        raise RuntimeError("Compile regression after v050/v051 install")

    print("Stage:", STAGE050.relative_to(ROOT))
    print("Stage:", STAGE051.relative_to(ROOT))
    print("\nUPGRADE STATUS: PASS")
    print("\nRun:")
    print(r'  & ".\.venv\Scripts\python.exe" -m automation.runner run-until-blocked')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
