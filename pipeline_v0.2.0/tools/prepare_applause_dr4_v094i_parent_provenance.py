#!/usr/bin/env python3
from __future__ import annotations
from pathlib import Path
import argparse,csv,hashlib,json,math

PARENT_COMMIT="b2e7989b2e3237dceee69e28f34023d651894a2f"

def sha(p:Path)->str:
    h=hashlib.sha256()
    with p.open("rb") as f:
        for b in iter(lambda:f.read(8*1024*1024),b""): h.update(b)
    return h.hexdigest()

def inum(v):
    try:
        x=float(str(v or "").strip())
        r=int(round(x))
        return r if math.isfinite(x) and abs(x-r)<1e-7 else None
    except Exception:return None

def bval(v): return str(v or "").strip().lower() in {"1","true","yes"}

def rows(p):
    with p.open("r",encoding="utf-8-sig",newline="") as f:
        yield from csv.DictReader(f)

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--project-root",required=True)
    ap.add_argument("--repo-root",required=True)
    a=ap.parse_args()
    root=Path(a.project_root).resolve()
    repo=Path(a.repo_root).resolve()
    freeze=root/"research"/"prospective_freezes"
    freeze.mkdir(parents=True,exist_ok=True)

    hres=root/"results"/"applause_dr4_fragment_aware_cross_site_opportunity_census_v094h"
    hcsv=hres/"applause_dr4_fragment_aware_cross_site_opportunities_v094h.csv"
    hreport=hres/"applause_dr4_fragment_aware_cross_site_opportunity_census_v094h.json"
    hmanifest=hres/"v094h_output_manifest.sha256"
    for p in (hcsv,hreport,hmanifest):
        if not p.is_file(): raise SystemExit(f"Missing completed v094h parent artifact: {p}")
    rep=json.loads(hreport.read_text(encoding="utf-8"))
    if rep.get("status")!="COMPLETE": raise SystemExit("v094h report is not COMPLETE")
    if int(rep.get("opportunity_rows",-1))!=1541: raise SystemExit("Unexpected v094h opportunity count")
    if int(rep.get("cumulative_gate_counts",{}).get("LE5MIN_INCLUDING_OVERLAP",-1))!=1240:
        raise SystemExit("Unexpected v094h <=5min gate count")
    exp_hash=rep.get("output_hashes",{}).get(hcsv.name)
    if not exp_hash or sha(hcsv)!=exp_hash: raise SystemExit("v094h opportunity CSV hash mismatch against report")

    hprov=root/"research"/"prospective_freezes"/"applause_dr4_fragment_aware_cross_site_opportunity_census_parent_provenance_v094h.json"
    if not hprov.is_file(): raise SystemExit("Missing frozen v094h parent provenance")
    hp=json.loads(hprov.read_text(encoding="utf-8"))
    sol_rel=hp["v094d_normalized"]["solution_full"]["path"]
    sol_path=root/sol_rel
    if not sol_path.is_file() or sha(sol_path)!=hp["v094d_normalized"]["solution_full"]["sha256"]:
        raise SystemExit("Frozen v094d solution_full mismatch")

    # Resolve exact solution_num for every selected v094h solution_id.
    solmap={}
    for r in rows(sol_path):
        sid=inum(r.get("solution_id"))
        if sid is None: continue
        solmap[sid]={
            "scan_id":inum(r.get("scan_id")),
            "plate_id":inum(r.get("plate_id")),
            "solution_num":inum(r.get("solution_num")),
        }

    plan_path=freeze/"applause_dr4_le5min_source_state_opportunity_plan_v094i.csv"
    fields=[
        "pair_id","exposure_a","exposure_b","plate_a","plate_b","archive_a","archive_b",
        "site_a","site_b","site_pair","timing_bin","min_fragment_gap_seconds",
        "fragment_overlap_intervals_json","fragment_overlap_count","total_fragment_overlap_seconds",
        "max_fragment_overlap_seconds","scan_id_a","scan_id_b","solution_id_a","solution_id_b",
        "solution_num_a","solution_num_b","common_tangent_area_deg2","common_fraction_of_a",
        "common_fraction_of_b","common_fraction_of_smaller","site_separation_km_diagnostic",
        "site_separation_band","epoch_label","in_1951_1955","pre_sputnik"
    ]
    n=0; keys=set(); sitepairs={}; bins={}; epochs={}
    tmp=plan_path.with_suffix(".csv.tmp")
    with tmp.open("w",encoding="utf-8",newline="") as f:
        w=csv.DictWriter(f,fieldnames=fields); w.writeheader()
        for r in rows(hcsv):
            if not bval(r.get("gate_le5min")): continue
            sa,sb=inum(r.get("solution_id_a")),inum(r.get("solution_id_b"))
            sca,scb=inum(r.get("scan_id_a")),inum(r.get("scan_id_b"))
            if sa not in solmap or sb not in solmap: raise SystemExit("Selected solution_id missing from frozen solution_full")
            ma,mb=solmap[sa],solmap[sb]
            if ma["solution_num"] is None or mb["solution_num"] is None:
                raise SystemExit(f"PROVENANCE HOLD: missing solution_num for v094h pair {r.get('pair_id')}")
            if ma["scan_id"]!=sca or mb["scan_id"]!=scb:
                raise SystemExit(f"PROVENANCE HOLD: v094h scan/solution mismatch for {r.get('pair_id')}")
            if ma["plate_id"]!=inum(r.get("plate_a")) or mb["plate_id"]!=inum(r.get("plate_b")):
                raise SystemExit(f"PROVENANCE HOLD: v094h plate/solution mismatch for {r.get('pair_id')}")
            pair=" | ".join(sorted((str(r.get("site_a") or "").strip(),str(r.get("site_b") or "").strip())))
            out={k:r.get(k,"") for k in fields}
            out["site_pair"]=pair
            out["solution_num_a"]=ma["solution_num"]; out["solution_num_b"]=mb["solution_num"]
            w.writerow(out); n+=1
            keys.add((sca,ma["solution_num"])); keys.add((scb,mb["solution_num"]))
            sitepairs[pair]=sitepairs.get(pair,0)+1
            tb=str(r.get("timing_bin") or ""); bins[tb]=bins.get(tb,0)+1
            ep=str(r.get("epoch_label") or ""); epochs[ep]=epochs.get(ep,0)+1
    tmp.replace(plan_path)
    if n!=1240: raise SystemExit(f"Expected 1240 <=5min rows, wrote {n}")

    # Bind v094h frozen code as local parent provenance too.
    parent_contract=root/"research"/"prospective_freezes"/"applause_dr4_fragment_aware_cross_site_opportunity_census_contract_v094h.json"
    parent_runner=root/"tools"/"run_applause_dr4_fragment_aware_cross_site_opportunity_census_v094h.py"
    for p in (parent_contract,parent_runner):
        if not p.is_file(): raise SystemExit(f"Missing frozen parent code: {p}")

    prov={
      "status":"PARENT_PROVENANCE_PREPARED_BEFORE_V094I_SOURCE_ACQUISITION",
      "required_parent_git_commit":PARENT_COMMIT,
      "guards_at_preparation":{
        "source_catalog_queries":0,"candidate_csv_reads":0,"candidate_inspection":0,
        "pixels":0,"registration":0
      },
      "v094h":{
        "opportunity_csv":str(hcsv.relative_to(root)).replace("\\","/"),
        "opportunity_csv_sha256":sha(hcsv),
        "report":str(hreport.relative_to(root)).replace("\\","/"),
        "report_sha256":sha(hreport),
        "output_manifest":str(hmanifest.relative_to(root)).replace("\\","/"),
        "output_manifest_sha256":sha(hmanifest),
        "contract":str(parent_contract.relative_to(root)).replace("\\","/"),
        "contract_sha256":sha(parent_contract),
        "runner":str(parent_runner.relative_to(root)).replace("\\","/"),
        "runner_sha256":sha(parent_runner),
        "all_opportunities":1541,
        "le5_opportunities":1240
      },
      "v094d_solution_full":{
        "path":str(sol_path.relative_to(root)).replace("\\","/"),
        "sha256":sha(sol_path)
      },
      "frozen_le5_plan":{
        "path":str(plan_path.relative_to(root)).replace("\\","/"),
        "sha256":sha(plan_path),
        "rows":n,
        "unique_scan_solution_keys":len(keys),
        "timing_bins":dict(sorted(bins.items())),
        "epoch_labels":dict(sorted(epochs.items())),
        "site_pairs":dict(sorted(sitepairs.items(),key=lambda kv:(-kv[1],kv[0])))
      }
    }
    pp=freeze/"applause_dr4_corrected_le5min_blind_source_state_parent_provenance_v094i.json"
    pp.write_text(json.dumps(prov,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    print(f"v094i parent provenance prepared: {pp}")
    print(f"<=5min opportunities: {n}")
    print(f"unique exact (scan_id, solution_num) source keys: {len(keys)}")
    print(f"dominant site pair <=5min: {max(sitepairs.items(), key=lambda kv:kv[1]) if sitepairs else None}")
    print(f"plan sha256: {sha(plan_path)}")
    return 0
if __name__=="__main__": raise SystemExit(main())
