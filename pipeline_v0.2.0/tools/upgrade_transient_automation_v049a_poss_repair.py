
from __future__ import annotations

from pathlib import Path
import ast
import datetime as dt
import py_compile
import shutil

ROOT = Path.cwd()
AUTO = ROOT / "automation"
REG = AUTO / "registry_order01.py"
STAGE = AUTO / "stages" / "repair_wide_census_poss_legacy_ids_v049a.py"
PAYLOAD = ROOT / "tools" / "_repair_wide_census_poss_legacy_ids_v049a.payload.py"

ENTRY = """
    StageContract(
        stage_id="wide_census_poss_legacy_identity_repair_v049a",
        title="Repair legacy POSS IDs and reclassify wide physical-timing census",
        script="automation/stages/repair_wide_census_poss_legacy_ids_v049a.py",
        requires=(
            "results/wide_census_physical_timing_queue_v048.csv",
            "results/wide_census_physical_timing_v049.json",
            "research/census_inputs/poss1_plate_metadata.csv",
            "config/candidate_adjudication_policy_v002.json",
        ),
        produces=(
            "results/wide_census_physical_timing_v049a.json",
            "results/wide_census_physical_timing_v049a.csv",
            "results/wide_census_timing_survivors_for_footprint_v049a.csv",
            "results/poss_legacy_identity_resolution_audit_v049a.csv",
        ),
        dependencies=("wide_census_physical_timing_v049",),
        network_access=True,
        retryable=True,
        notes="Repairs systematic legacy POSS IDs lacking :recNNN. Uses legacy clock only as exact identity key; authoritative timing remains vi25_start_utc(). Return 10 is checkpointed progress.",
    ),
"""


def add_entry(text):
    if 'stage_id="wide_census_poss_legacy_identity_repair_v049a"' in text:
        return text, "already registered"

    tree = ast.parse(text)
    container = None

    for node in tree.body:
        value = None
        matched = False
        if isinstance(node, ast.Assign):
            value = node.value
            matched = any(
                isinstance(target, ast.Name) and target.id == "ORDER01_STAGES"
                for target in node.targets
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
    print("TRANSIENT AUTOMATION UPGRADE — LEGACY POSS IDENTITY REPAIR v049a")
    print("=" * 132)
    print("INSTALLER: NO NETWORK. NO PIXELS. NO DETECTOR. NO CANDIDATE STATE MUTATION.\n")

    for path in (AUTO, REG, PAYLOAD):
        if not path.exists():
            raise RuntimeError(f"missing required installer input: {path}")

    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = ROOT / "patch_backups" / f"pre_wide_poss_repair_v049a_{stamp}"
    backup.mkdir(parents=True, exist_ok=False)
    shutil.copy2(REG, backup / REG.name)

    STAGE.parent.mkdir(parents=True, exist_ok=True)
    STAGE.write_text(PAYLOAD.read_text(encoding="utf-8"), encoding="utf-8")
    py_compile.compile(str(STAGE), doraise=True)

    text, note = add_entry(REG.read_text(encoding="utf-8"))
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
        raise RuntimeError("compile regression after v049a install")

    print("Stage:", STAGE.relative_to(ROOT))
    print("\nUPGRADE STATUS: PASS")
    print("\nRun:")
    print(r'  & ".\.venv\Scripts\python.exe" -m automation.runner run-until-blocked --allow-network')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
