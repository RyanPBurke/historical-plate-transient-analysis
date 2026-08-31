from __future__ import annotations

from pathlib import Path
import ast
import datetime as dt
import py_compile
import shutil

ROOT = Path.cwd()
AUTO = ROOT / "automation"
REG = AUTO / "registry_order01.py"
STAGE = AUTO / "stages" / "execute_wide_census_physical_timing_v049.py"
AP_DEST = ROOT / "research" / "census_inputs" / "applause_exposures_1951_1955.csv"
POSS_DEST = ROOT / "research" / "census_inputs" / "poss1_plate_metadata.csv"
PAY_STAGE = ROOT / "tools" / "_execute_wide_census_physical_timing_v049.payload.py"
PAY_AP = ROOT / "tools" / "_applause_exposures_1951_1955.payload.csv"
PAY_POSS = ROOT / "tools" / "_poss1_plate_metadata.payload.csv"

ENTRY = """
    StageContract(
        stage_id="wide_census_physical_timing_v049",
        title="Resolve <=15-minute wide census physical timing and physical-plate identity",
        script="automation/stages/execute_wide_census_physical_timing_v049.py",
        requires=(
            "results/wide_census_physical_timing_queue_v048.csv",
            "results/census_scope_audit_v048.json",
            "research/census_inputs/applause_exposures_1951_1955.csv",
            "research/census_inputs/poss1_plate_metadata.csv",
            "config/candidate_adjudication_policy_v002.json",
        ),
        produces=(
            "results/wide_census_physical_timing_v049.json",
            "results/wide_census_physical_timing_v049.csv",
            "results/wide_census_timing_survivors_for_footprint_v049.csv",
        ),
        dependencies=("project_census_scope_audit_v048",),
        network_access=True,
        retryable=True,
        notes="Resumable metadata-only census; subprocess return code 10 means checkpointed IN_PROGRESS.",
    ),
"""


def add_entry(text: str):
    if 'stage_id="wide_census_physical_timing_v049"' in text:
        return text, "already registered"
    tree = ast.parse(text)
    container = None
    for node in tree.body:
        value = None
        matched = False
        if isinstance(node, ast.Assign):
            value = node.value
            matched = any(isinstance(t, ast.Name) and t.id == "ORDER01_STAGES" for t in node.targets)
        elif isinstance(node, ast.AnnAssign):
            value = node.value
            matched = isinstance(node.target, ast.Name) and node.target.id == "ORDER01_STAGES"
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


def copy_pinned(src: Path, dst: Path):
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists() and dst.read_bytes() != src.read_bytes():
        raise RuntimeError(f"REFUSING: existing pinned source differs from v049 payload: {dst}")
    shutil.copy2(src, dst)


def main():
    print("=" * 132)
    print("TRANSIENT AUTOMATION UPGRADE — WIDE PHYSICAL TIMING CENSUS v049")
    print("=" * 132)
    print("INSTALLER: NO NETWORK. NO PIXELS. NO DETECTOR. NO CANDIDATE STATE MUTATION.\n")

    for path in (AUTO, REG, PAY_STAGE, PAY_AP, PAY_POSS):
        if not path.exists():
            raise RuntimeError(f"missing installer payload: {path}")

    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = ROOT / "patch_backups" / f"pre_wide_timing_v049_{stamp}"
    backup.mkdir(parents=True, exist_ok=False)
    shutil.copy2(REG, backup / REG.name)

    copy_pinned(PAY_AP, AP_DEST)
    copy_pinned(PAY_POSS, POSS_DEST)

    STAGE.parent.mkdir(parents=True, exist_ok=True)
    STAGE.write_text(PAY_STAGE.read_text(encoding="utf-8"), encoding="utf-8")
    py_compile.compile(str(STAGE), doraise=True)

    text, note = add_entry(REG.read_text(encoding="utf-8"))
    REG.write_text(text, encoding="utf-8")
    print("Registry:", note)

    failures = []
    for path in sorted(x for x in AUTO.rglob("*.py") if "backups" not in x.parts):
        try:
            py_compile.compile(str(path), doraise=True)
        except Exception as exc:
            failures.append((path, exc))
            print("FAIL", path.relative_to(ROOT), exc)
    if failures:
        raise RuntimeError("automation compile regression after v049 install")

    print("Pinned APPLAUSE:", AP_DEST.relative_to(ROOT))
    print("Pinned POSS VI/25:", POSS_DEST.relative_to(ROOT))
    print("Stage:", STAGE.relative_to(ROOT))
    print("\nUPGRADE STATUS: PASS")
    print("\nRecommended run:")
    print(r'  & ".\.venv\Scripts\python.exe" -m automation.runner run-until-blocked --allow-network')
    print("\nOr one 12-identity checkpoint batch at a time:")
    print(r'  & ".\.venv\Scripts\python.exe" -m automation.runner run-next --allow-network')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
