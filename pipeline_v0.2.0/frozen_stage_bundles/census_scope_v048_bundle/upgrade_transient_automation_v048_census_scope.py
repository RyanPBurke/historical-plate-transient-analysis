
from __future__ import annotations
from pathlib import Path
import ast, py_compile, shutil, datetime as dt

ROOT = Path.cwd()
AUTO = ROOT / "automation"
REG = AUTO / "registry_order01.py"
STAGE = AUTO / "stages" / "audit_project_census_scope_v048.py"
SOURCE_DEST = ROOT / "research" / "census_inputs" / "archive_pair_overlap_candidates.csv"
PAYLOAD_STAGE = ROOT / "tools" / "_audit_project_census_scope_v048.payload.py"
PAYLOAD_CSV = ROOT / "tools" / "_archive_pair_overlap_candidates.payload.csv"

ENTRY = r'''
    StageContract(
        stage_id="project_census_scope_audit_v048",
        title="Freeze broad archive-pair census scope and <=15-minute physical-timing queue",
        script="automation/stages/audit_project_census_scope_v048.py",
        requires=(
            "research/census_inputs/archive_pair_overlap_candidates.csv",
            "results/existing_identified_pair_inventory_v028ca.json",
            "results/remaining_pair_physical_timing_census_v028cg.json",
            "results/physical_overlap_survivor_execution_plan_v028ch.json",
            "results/order11_followup_match3_v047/order11_match3_method_freeze_v047.json",
        ),
        produces=(
            "results/census_scope_audit_v048.json",
            "results/wide_census_physical_timing_queue_v048.csv",
        ),
        dependencies=("order11_match3_method_freeze_v047",),
        notes="No network/pixels/detector/state mutation; preserves cohort boundary and creates metadata-only <=15-minute timing/provenance queue.",
    ),
'''

def append_entry(text):
    if 'stage_id="project_census_scope_audit_v048"' in text:
        return text, "already registered"
    tree = ast.parse(text)
    container = None
    for node in tree.body:
        val = None
        matched = False
        if isinstance(node, ast.Assign):
            val = node.value
            matched = any(isinstance(t, ast.Name) and t.id == "ORDER01_STAGES" for t in node.targets)
        elif isinstance(node, ast.AnnAssign):
            val = node.value
            matched = isinstance(node.target, ast.Name) and node.target.id == "ORDER01_STAGES"
        if matched and isinstance(val, (ast.List, ast.Tuple)):
            container = val
            break
    if container is None:
        raise RuntimeError("ORDER01_STAGES list/tuple not found")
    lines = text.splitlines(keepends=True)
    lines.insert(container.end_lineno - 1, "\n" + ENTRY.rstrip() + "\n")
    out = "".join(lines)
    ast.parse(out)
    return out, f"inserted before ORDER01_STAGES closing line {container.end_lineno}"

def main():
    print("="*128)
    print("TRANSIENT AUTOMATION UPGRADE — PROJECT CENSUS SCOPE AUDIT v048")
    print("="*128)
    print("NO NETWORK. NO PIXELS. NO DETECTOR. NO CANDIDATE STATE MUTATION.\n")

    for p in (AUTO, REG, PAYLOAD_STAGE, PAYLOAD_CSV):
        if not p.exists():
            raise RuntimeError(f"Missing installer payload: {p}")

    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = ROOT / "patch_backups" / f"pre_census_scope_v048_{stamp}"
    backup.mkdir(parents=True, exist_ok=False)
    shutil.copy2(REG, backup / REG.name)

    SOURCE_DEST.parent.mkdir(parents=True, exist_ok=True)
    if SOURCE_DEST.exists() and SOURCE_DEST.read_bytes() != PAYLOAD_CSV.read_bytes():
        raise RuntimeError("REFUSING: existing archive_pair_overlap_candidates.csv differs from payload")
    shutil.copy2(PAYLOAD_CSV, SOURCE_DEST)

    STAGE.parent.mkdir(parents=True, exist_ok=True)
    STAGE.write_text(PAYLOAD_STAGE.read_text(encoding="utf-8"), encoding="utf-8")
    py_compile.compile(str(STAGE), doraise=True)

    text = REG.read_text(encoding="utf-8")
    text, note = append_entry(text)
    REG.write_text(text, encoding="utf-8")
    print("Registry:", note)

    failures = []
    for p in sorted(x for x in AUTO.rglob("*.py") if "backups" not in x.parts):
        try:
            py_compile.compile(str(p), doraise=True)
        except Exception as exc:
            failures.append((p, exc))
            print("FAIL", p.relative_to(ROOT), exc)
    if failures:
        raise RuntimeError("Automation compile regression after v048 install")

    print("Installed source:", SOURCE_DEST.relative_to(ROOT))
    print("Installed stage:", STAGE.relative_to(ROOT))
    print("\nUPGRADE STATUS: PASS")
    print("\nNext:")
    print(r'  & ".\.venv\Scripts\python.exe" -m automation.runner status')
    print(r'  & ".\.venv\Scripts\python.exe" -m automation.runner run-next')
    print(r'  & ".\.venv\Scripts\python.exe" -m automation.runner verify-stage --stage project_census_scope_audit_v048')
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
