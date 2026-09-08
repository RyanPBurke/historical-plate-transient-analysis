#!/usr/bin/env python3
from pathlib import Path
import argparse,csv,hashlib,json,platform,shutil,sys,importlib.metadata

EXPECTED_SPEC="2a24508c359f31bb14d55755c2579e0314d73d152462286606203273619794cd"
PARENT="bfbc10b0b0357762b74f6ff89ea856cc6509a383"

def sha(p):
    h=hashlib.sha256()
    with Path(p).open("rb") as f:
        for b in iter(lambda:f.read(8*1024*1024),b""):h.update(b)
    return h.hexdigest()

def all_files(base):
    return sorted([p for p in base.rglob("*") if p.is_file()],key=lambda p:str(p.relative_to(base)))

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--project-root",required=True)
    ap.add_argument("--artifact-dir",required=True)
    a=ap.parse_args()
    root=Path(a.project_root).resolve();ad=Path(a.artifact_dir).resolve()
    work=root/"work"/"applause_dr4_v094r3_operational_preparation"
    s0=work/"stage0_cache_integrity.json";s1=work/"operational_preparation_manifest.json"
    acq=work/"acquisition"
    if not s0.is_file() or not s1.is_file() or not acq.is_dir():raise SystemExit("Missing completed v094r3 operational preparation")
    q0=json.loads(s0.read_text());q1=json.loads(s1.read_text())
    if q0.get("status")!="PASS":raise SystemExit("Stage 0 not PASS")
    for k,v in {"legacy_products_verified":1386,"exact_products_verified":1386,"rows_verified":21609122,
                "non_gaia_array_changes":0,"gaia_positive_status_changes":0}.items():
        if int(q0.get(k,-1))!=v:raise SystemExit(f"Stage 0 acceptance HOLD {k}")
    if q1.get("status")!="OPERATIONAL_PREPARATION_COMPLETE" or q1.get("scientific_outcomes_inspected") is not False:
        raise SystemExit("Stage 1 status/HOLD")
    apm=q1["applause"]
    if int(apm["rows"])!=1289 or int(apm["site_name_mismatches"])!=0 or int(apm["lonlat_mismatches"])!=0 or int(apm["missing_elevations"])!=0:
        raise SystemExit("Stage 1 APPLAUSE completeness HOLD")
    combined=root/apm["combined_path"]
    if not combined.is_file() or sha(combined)!=apm["combined_sha256"]:raise SystemExit("Combined APPLAUSE hash HOLD")
    for rec in q1["references"].values():
        if rec:
            p=root/rec["path"]
            if not p.is_file() or sha(p)!=rec["sha256"]:raise SystemExit(f"Reference hash HOLD: {p}")

    spec=ad/"applause_dr4_historical_geometry_validation_spec_v094r3b.json"
    runner=ad/"run_applause_dr4_historical_geometry_validation_v094r3b.py"
    if sha(spec)!=EXPECTED_SPEC:raise SystemExit("Artifact scientific spec hash HOLD")

    qprov=root/"research"/"prospective_freezes"/"applause_dr4_exact_gaia_identity_and_timing_reconstruction_parent_provenance_v094q.json"
    if not qprov.is_file():raise SystemExit("Missing v094q frozen provenance")
    qp=json.loads(qprov.read_text())
    active={}
    for sec in ("frozen_plan","solution_full"):
        rec=qp[sec];p=root/rec["path"]
        if not p.is_file() or sha(p)!=rec["sha256"]:raise SystemExit(f"Active input hash HOLD: {sec}")
        active[sec]=rec

    fr=root/"research"/"prospective_freezes"/"v094r3b_historical_geometry_validation"
    if fr.exists():shutil.rmtree(fr)
    (fr/"inputs").mkdir(parents=True)
    shutil.copy2(spec,fr/spec.name)
    shutil.copy2(s0,fr/"stage0_cache_integrity.json")
    shutil.copy2(s1,fr/"operational_preparation_manifest.json")
    shutil.copytree(acq,fr/"inputs"/"acquisition")

    deps={}
    for pkg in ("numpy","scipy","astropy","pyerfa"):
        try:deps[pkg]=importlib.metadata.version(pkg)
        except Exception:deps[pkg]=None
    deps["python"]=sys.version
    deps["platform"]=platform.platform()
    (fr/"dependency_versions_v094r3b.json").write_text(json.dumps(deps,indent=2,sort_keys=True)+"\n")

    frozen=[]
    for p in all_files(fr):
        if p.name=="freeze_manifest_v094r3b.json":continue
        frozen.append({"relative_path":str(p.relative_to(fr)).replace("\\","/"),
                       "sha256":sha(p),"size_bytes":p.stat().st_size})
    manifest={
      "status":"INPUTS_AND_EXECUTABLE_PREPARED_FOR_FREEZE",
      "required_parent_git_commit":PARENT,
      "scientific_spec_sha256":EXPECTED_SPEC,
      "runner_sha256":sha(runner),
      "stage0_report_sha256":sha(s0),
      "stage1_manifest_sha256":sha(s1),
      "active_project_inputs":active,
      "frozen_files":frozen,
      "dependencies":deps,
      "target_geometry_outcomes_inspected":False,
      "network_allowed_after_freeze":False
    }
    mp=fr/"freeze_manifest_v094r3b.json"
    mp.write_text(json.dumps(manifest,indent=2,sort_keys=True)+"\n")
    print("v094r3b freeze inputs assembled")
    print(f"Scientific spec SHA256: {EXPECTED_SPEC}")
    print(f"Runner SHA256:          {manifest['runner_sha256']}")
    print(f"Frozen files:           {len(frozen)+1}")
    print(f"Freeze manifest:        {mp}")
    return 0

if __name__=="__main__":raise SystemExit(main())
