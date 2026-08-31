from __future__ import annotations
from pathlib import Path
import ast, json, py_compile, shutil

ROOT=Path.cwd()
AUTO=ROOT/"automation"
REG=AUTO/"registry_order01.py"
STAGE=AUTO/"stages"/"freeze_order11_match3_method_lessons_v047.py"
CONFIG=ROOT/"config"/"candidate_adjudication_policy_v002.json"
SOURCE_POLICY=ROOT/"tools"/"_candidate_adjudication_policy_v002.payload.json"
BACKUP=ROOT/"patch_backups"/"pre_match3_method_freeze_v047"

ENTRY = """
    StageContract(
        stage_id="order11_match3_method_freeze_v047",
        title="Freeze Match-3 adjudication lessons into generic candidate policy",
        script="automation/stages/freeze_order11_match3_method_lessons_v047.py",
        requires=(
            "config/candidate_adjudication_policy_v002.json",
            "results/order11_followup_match3_v042/order11_match3_gaia_epoch_report_v042.json",
            "results/order11_followup_match3_v043a/order11_match3_local_astrometry_report_v043a.json",
            "results/order11_followup_match3_v044/order11_match3_sparse_astrometry_report_v044.json",
            "results/order11_followup_match3_v044b/order11_match3_sparse_robustness_audit_v044b.json",
            "results/order11_followup_match3_v045a/order11_match3_final_adjudication_v045a.json",
        ),
        produces=(
            "results/order11_followup_match3_v047/order11_match3_method_freeze_v047.json",
        ),
        notes="No network/pixels/detector/state mutation; freezes generic lessons demonstrated by Match 3 without altering frozen candidate evidence.",
    ),
"""

def append_entry(text):
    if 'stage_id="order11_match3_method_freeze_v047"' in text:
        return text, "already registered"
    tree=ast.parse(text)
    container=None
    for node in tree.body:
        val=None; matched=False
        if isinstance(node,ast.Assign):
            val=node.value
            matched=any(isinstance(t,ast.Name) and t.id=="ORDER01_STAGES" for t in node.targets)
        elif isinstance(node,ast.AnnAssign):
            val=node.value
            matched=isinstance(node.target,ast.Name) and node.target.id=="ORDER01_STAGES"
        if matched and isinstance(val,(ast.List,ast.Tuple)):
            container=val; break
    if container is None:
        raise RuntimeError("ORDER01_STAGES list/tuple not found")
    lines=text.splitlines(keepends=True)
    lines.insert(container.end_lineno-1, "\n"+ENTRY.rstrip()+"\n")
    out="".join(lines)
    ast.parse(out)
    return out, f"inserted before ORDER01_STAGES closing line {container.end_lineno}"

def main():
    print("="*120)
    print("TRANSIENT AUTOMATION UPGRADE — MATCH-3 METHOD LESSON FREEZE v047")
    print("="*120)
    print("NO NETWORK. NO PIXELS. NO DETECTOR. NO CANDIDATE STATE MUTATION.\n")

    for p in (AUTO,REG,SOURCE_POLICY):
        if not p.exists():
            print("FAIL missing:",p); return 2

    BACKUP.mkdir(parents=True,exist_ok=True)
    for p in (REG,):
        dst=BACKUP/p.name
        if not dst.exists(): shutil.copy2(p,dst)

    policy=json.loads(SOURCE_POLICY.read_text(encoding="utf-8"))
    CONFIG.parent.mkdir(parents=True,exist_ok=True)
    CONFIG.write_text(json.dumps(policy,indent=2,sort_keys=True)+"\n",encoding="utf-8")

    stage_source = SOURCE_POLICY.with_name("_freeze_order11_match3_method_lessons_v047.payload.py")
    if not stage_source.is_file():
        print("FAIL missing stage payload:",stage_source); return 2
    STAGE.parent.mkdir(parents=True,exist_ok=True)
    STAGE.write_text(stage_source.read_text(encoding="utf-8"),encoding="utf-8")
    py_compile.compile(str(STAGE),doraise=True)

    text=REG.read_text(encoding="utf-8")
    text,note=append_entry(text)
    REG.write_text(text,encoding="utf-8")
    print("Registry:",note)

    failures=[]
    for p in sorted(x for x in AUTO.rglob("*.py") if "backups" not in x.parts):
        try: py_compile.compile(str(p),doraise=True)
        except Exception as exc:
            failures.append((p,exc)); print("FAIL",p.relative_to(ROOT),exc)
    if failures:
        print("\nUPGRADE STATUS: FAIL")
        return 3

    print("Policy:",CONFIG.relative_to(ROOT))
    print("Stage:",STAGE.relative_to(ROOT))
    print("\nUPGRADE STATUS: PASS")
    print("\nNext:")
    print(r'  & ".\.venv\Scripts\python.exe" -m automation.runner status')
    print(r'  & ".\.venv\Scripts\python.exe" -m automation.runner run-next')
    print(r'  & ".\.venv\Scripts\python.exe" -m automation.runner verify-stage --stage order11_match3_method_freeze_v047')
    return 0

if __name__=="__main__":
    raise SystemExit(main())
