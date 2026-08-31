#!/usr/bin/env python3
"""Install the existing identified-pair inventory and processing plan."""
from __future__ import annotations

import hashlib, py_compile, re, shutil, subprocess, sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path.cwd()
QUEUE = ROOT / "research" / "poss1_pixel_repair_v028_queue.csv"
FREEZE = ROOT / "results" / "project_accounting_freeze_v028bz.json"
TARGET = ROOT / "automation" / "stages" / "inventory_existing_pairs_v028ca.py"
REGISTRY = ROOT / "automation" / "registry_order01.py"
INIT = ROOT / "automation" / "__init__.py"
RUNNER = ROOT / "automation" / "runner.py"
VERSION = "0.3.6"
STAGE_ID = "existing_identified_pair_inventory_v028ca"
BACKUP = ROOT / "automation" / "backups" / ("pre_v030_pair_inventory_" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"))

def refuse(message): raise SystemExit("REFUSING: " + message)

STAGE = r'''#!/usr/bin/env python3
from __future__ import annotations
import csv, hashlib, json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
QUEUE = ROOT / "research" / "poss1_pixel_repair_v028_queue.csv"
FREEZE = ROOT / "results" / "project_accounting_freeze_v028bz.json"
OUT_JSON = ROOT / "results" / "existing_identified_pair_inventory_v028ca.json"
OUT_CSV = ROOT / "results" / "existing_identified_pair_processing_queue_v028ca.csv"
OUT_MD = ROOT / "results" / "EXISTING_IDENTIFIED_PAIR_INVENTORY_V028CA.md"
QUEUE_SHA = "__QUEUE_SHA__"
FREEZE_SHA = "__FREEZE_SHA__"

def main():
    print("="*120); print("EXISTING IDENTIFIED PAIR INVENTORY v028ca"); print("="*120)
    print("NO NETWORK ACCESS. NO PIXELS ARE READ. No detector or candidate state is changed.\n")
    for p,e in ((QUEUE,QUEUE_SHA),(FREEZE,FREEZE_SHA)):
        if not p.is_file(): raise RuntimeError(f"missing frozen input: {p}")
        if hashlib.sha256(p.read_bytes()).hexdigest()!=e: raise RuntimeError(f"REFUSING: input hash changed: {p.name}")
    freeze=json.loads(FREEZE.read_text(encoding="utf-8"))
    if freeze["overall_classification"]!="ZERO_CONFIRMED_DIRECT_TWO_OBSERVATORY_TRANSIENTS_CANDIDATE462_RETAINED_AS_EXPLORATORY_TRAJECTORY_LEAD":
        raise RuntimeError("project accounting state changed")
    with QUEUE.open(encoding="utf-8-sig",newline="") as fh: rows=list(csv.DictReader(fh))
    if len(rows)!=11: raise RuntimeError(f"expected 11 repair-queue rows; got {len(rows)}")
    if len({r['pair_key'] for r in rows})!=11: raise RuntimeError("pair keys are not unique")
    completed={61}
    remaining=[r for r in rows if int(r['canonical_order']) not in completed]
    if len(remaining)!=10: raise RuntimeError(f"expected 10 remaining rows; got {len(remaining)}")
    # Greater real overlap first. For equal overlap, untouched prospective work precedes legacy revalidation.
    remaining.sort(key=lambda r:(-round(float(r['actual_exposure_overlap_s'])), r['pre_freeze_touched']=='True', int(r['canonical_order'])))
    plan=[]
    for seq,r in enumerate(remaining,1):
        plan.append({
            "processing_priority":seq,
            "canonical_order":int(r['canonical_order']),
            "legacy_rank":int(float(r['legacy_rank'])),
            "pair_key":r['pair_key'],
            "actual_exposure_overlap_s":float(r['actual_exposure_overlap_s']),
            "actual_exposure_overlap_minutes":float(r['actual_exposure_overlap_minutes']),
            "true_wcs_overlap_fraction":float(r['true_wcs_overlap_fraction']),
            "id_integrity":r['id_integrity'],
            "pre_freeze_touched":r['pre_freeze_touched']=='True',
            "pre_freeze_reason":r['pre_freeze_reason'],
            "production_action":r['production_action'],
            "status":"PENDING_CURRENT_PROTOCOL",
        })
    if plan[0]['canonical_order']!=55: raise RuntimeError("expected Order 55 to lead overlap-ranked plan")
    result={
      "stage":"EXISTING_IDENTIFIED_PAIR_INVENTORY_V028CA",
      "input_sha256":{QUEUE.name:QUEUE_SHA,FREEZE.name:FREEZE_SHA},
      "queue_scope":"POSS1_PIXEL_REPAIR_IDENTITY_REPAIR_V028_COHORT",
      "queue_rows":11,
      "already_completed_queue_orders":[61],
      "remaining_pair_count":10,
      "remaining_orders":[p['canonical_order'] for p in plan],
      "processing_plan":plan,
      "next_pair":plan[0],
      "priority_rule":"Actual exposure overlap descending; untouched prospective work precedes legacy revalidation at equal overlap; canonical order breaks remaining ties.",
      "scope_boundary":"This is the 11-row identity-repair/production queue, not proof that every historical or possible observatory pair has been enumerated.",
      "next_gate":{"order55_native_identity_and_source_preflight_may_run":True,"additional_observatory_expansion_may_run":False},
      "guards":{"network_access":False,"science_pixels_read":False,"non_science_pixels_read":False,"transient_detector_rerun":False,"candidate_state_mutation":False},
    }
    OUT_JSON.write_text(json.dumps(result,indent=2)+"\n",encoding="utf-8")
    with OUT_CSV.open('w',encoding='utf-8',newline='') as fh:
        w=csv.DictWriter(fh,fieldnames=list(plan[0])); w.writeheader(); w.writerows(plan)
    lines=["# Existing Identified Pair Inventory v028ca","",f"Remaining pairs: **{len(plan)}**.","","| Priority | Order | Overlap | Prior work |","|---:|---:|---:|---|"]
    for p in plan: lines.append(f"| {p['processing_priority']} | {p['canonical_order']} | {p['actual_exposure_overlap_minutes']:.1f} min | {'yes' if p['pre_freeze_touched'] else 'no'} |")
    lines += ["",f"Next pair: **Order {plan[0]['canonical_order']}**.","",result['scope_boundary']]
    OUT_MD.write_text("\n".join(lines)+"\n",encoding="utf-8")
    print(f"Queue rows: 11"); print("Already completed: Order 61"); print("Remaining pairs: 10")
    print("Processing order: "+", ".join(str(p['canonical_order']) for p in plan)); print("Next pair: Order 55")
    print("\nSTAGE STATUS: PASS"); return 0
if __name__=='__main__': raise SystemExit(main())
'''

def add_registry(text):
    if f'stage_id="{STAGE_ID}"' in text: return text
    marker="\n]\n\ndef by_id():"
    if text.count(marker)!=1: refuse("registry closing marker is not unique")
    block=r'''

    StageContract(
        stage_id="existing_identified_pair_inventory_v028ca",
        title="Inventory and prioritise existing identified pair queue",
        script="automation/stages/inventory_existing_pairs_v028ca.py",
        requires=("research/poss1_pixel_repair_v028_queue.csv", "results/project_accounting_freeze_v028bz.json"),
        produces=("results/existing_identified_pair_inventory_v028ca.json",),
        dependencies=("project_accounting_freeze_v028bz",),
        network_access=False,
        notes="Hash-pinned queue inventory only; selects Order 55 for current-protocol revalidation.",
    ),
'''
    return text.replace(marker,block+marker,1)

def main():
    print("="*120); print("TRANSIENT AUTOMATION UPGRADE v0.3.0 — EXISTING PAIR INVENTORY"); print("="*120)
    print("NO NETWORK ACCESS. NO PIXELS ARE READ. No detector or candidate state is changed.\n")
    for p in (QUEUE,FREEZE,REGISTRY,INIT,RUNNER):
        if not p.is_file(): refuse(f"required file missing: {p}")
    stage=STAGE.replace("__QUEUE_SHA__",hashlib.sha256(QUEUE.read_bytes()).hexdigest()).replace("__FREEZE_SHA__",hashlib.sha256(FREEZE.read_bytes()).hexdigest())
    compile(stage,str(TARGET),'exec'); BACKUP.mkdir(parents=True,exist_ok=False)
    for p in (REGISTRY,INIT,RUNNER): shutil.copy2(p,BACKUP/p.name)
    TARGET.write_text(stage,encoding='utf-8'); REGISTRY.write_text(add_registry(REGISTRY.read_text(encoding='utf-8')),encoding='utf-8')
    INIT.write_text(f'__version__ = "{VERSION}"\n',encoding='utf-8')
    runner=RUNNER.read_text(encoding='utf-8'); runner,n=re.subn(r"Transient automation v\d+\.\d+\.\d+",f"Transient automation v{VERSION}",runner)
    if n==0: refuse("runner version banner not found")
    RUNNER.write_text(runner,encoding='utf-8')
    for p in (TARGET,REGISTRY,INIT,RUNNER): py_compile.compile(str(p),doraise=True)
    subprocess.run([sys.executable,'-c',"import automation; from automation.registry_order01 import by_id; "+f"assert automation.__version__=='{VERSION}'; assert '{STAGE_ID}' in by_id()"],cwd=ROOT,check=True)
    print(f"Installed stage: {STAGE_ID}"); print(f"Backup: {BACKUP}"); print("\nUPGRADE STATUS: PASS"); return 0
if __name__=='__main__': raise SystemExit(main())
