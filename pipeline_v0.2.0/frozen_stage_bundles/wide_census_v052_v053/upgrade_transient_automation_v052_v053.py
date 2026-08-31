from __future__ import annotations
from pathlib import Path
import ast,datetime as dt,py_compile,shutil
ROOT=Path.cwd();AUTO=ROOT/'automation';REG=AUTO/'registry_order01.py'
PAY052=ROOT/'tools'/'_execute_exact_footprints_v052.payload.py';PAY053=ROOT/'tools'/'_plan_detector_execution_v053.payload.py'
STAGE052=AUTO/'stages'/'execute_exact_footprints_v052.py';STAGE053=AUTO/'stages'/'plan_detector_execution_v053.py'
ENTRIES='''
    StageContract(
        stage_id="wide_census_exact_footprint_v052",
        title="Resolve exact archive-derived sky footprints for all timing survivors",
        script="automation/stages/execute_exact_footprints_v052.py",
        requires=(
            "results/wide_census_footprint_plan_v051.json",
            "results/wide_census_exact_footprint_queue_v051.csv",
            "results/wide_census_physical_timing_final_v050.json",
            "research/census_inputs/applause_exposures_1951_1955.csv",
            "config/candidate_adjudication_policy_v002.json",
        ),
        produces=(
            "results/wide_census_exact_footprint_v052.json",
            "results/wide_census_exact_footprint_v052.csv",
            "results/wide_census_true_overlap_survivors_v052.csv",
            "results/wide_census_footprint_holds_v052.csv",
        ),
        dependencies=("wide_census_footprint_plan_v051",),
        network_access=True,
        retryable=True,
        notes="APPLAUSE DR4 TAP stc_polygon plus DASCH DR7 TPV metadata. No science pixels or detector. Ambiguous geometry is held, never forced.",
    ),
    StageContract(
        stage_id="wide_census_detector_execution_plan_v053",
        title="Freeze robust true-overlap opportunities into detector execution queue",
        script="automation/stages/plan_detector_execution_v053.py",
        requires=(
            "results/wide_census_exact_footprint_v052.json",
            "results/wide_census_exact_footprint_queue_v051.csv",
            "config/candidate_adjudication_policy_v002.json",
        ),
        produces=(
            "results/wide_census_detector_execution_plan_v053.json",
            "results/wide_census_detector_execution_queue_v053.csv",
            "results/wide_census_detector_execution_holds_v053.csv",
        ),
        dependencies=("wide_census_exact_footprint_v052",),
        notes="Local-only execution-plan freeze. No transient candidate is promoted.",
    ),
'''
def add(text):
    wanted=('stage_id="wide_census_exact_footprint_v052"','stage_id="wide_census_detector_execution_plan_v053"')
    if all(x in text for x in wanted):return text,'already registered'
    if any(x in text for x in wanted):raise RuntimeError('REFUSING: partial v052/v053 registration detected')
    tree=ast.parse(text);container=None
    for n in tree.body:
        val=None;matched=False
        if isinstance(n,ast.Assign):val=n.value;matched=any(isinstance(t,ast.Name) and t.id=='ORDER01_STAGES' for t in n.targets)
        elif isinstance(n,ast.AnnAssign):val=n.value;matched=isinstance(n.target,ast.Name) and n.target.id=='ORDER01_STAGES'
        if matched and isinstance(val,(ast.List,ast.Tuple)):container=val;break
    if container is None:raise RuntimeError('ORDER01_STAGES list/tuple not found')
    lines=text.splitlines(keepends=True);lines.insert(container.end_lineno-1,'\n'+ENTRIES.rstrip()+'\n');out=''.join(lines);ast.parse(out);return out,f'inserted before ORDER01_STAGES closing line {container.end_lineno}'
def main():
    print('='*132);print('TRANSIENT AUTOMATION UPGRADE — EXACT FOOTPRINT + DETECTOR PLAN v052/v053');print('='*132);print('INSTALLER: NO NETWORK. NO PIXELS. NO DETECTOR. NO CANDIDATE STATE MUTATION.\n')
    for p in (AUTO,REG,PAY052,PAY053):
        if not p.exists():raise RuntimeError(f'Missing installer input: {p}')
    stamp=dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ');backup=ROOT/'patch_backups'/f'pre_v052_v053_{stamp}';backup.mkdir(parents=True,exist_ok=False);shutil.copy2(REG,backup/REG.name)
    STAGE052.parent.mkdir(parents=True,exist_ok=True);STAGE052.write_text(PAY052.read_text(encoding='utf-8'),encoding='utf-8');STAGE053.write_text(PAY053.read_text(encoding='utf-8'),encoding='utf-8');py_compile.compile(str(STAGE052),doraise=True);py_compile.compile(str(STAGE053),doraise=True)
    text,note=add(REG.read_text(encoding='utf-8'));REG.write_text(text,encoding='utf-8');print('Registry:',note)
    failures=[]
    for p in sorted(x for x in AUTO.rglob('*.py') if 'backups' not in x.parts):
        try:py_compile.compile(str(p),doraise=True)
        except Exception as exc:failures.append((p,exc));print('FAIL',p.relative_to(ROOT),exc)
    if failures:raise RuntimeError('Compile regression after v052/v053 install')
    print('Stage:',STAGE052.relative_to(ROOT));print('Stage:',STAGE053.relative_to(ROOT));print('\nUPGRADE STATUS: PASS');print('\nRun:');print(r'  & ".\.venv\Scripts\python.exe" -m automation.runner run-until-blocked --allow-network');return 0
if __name__=='__main__':raise SystemExit(main())
