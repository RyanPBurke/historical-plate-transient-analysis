#!/usr/bin/env python3
from __future__ import annotations
from pathlib import Path
import argparse,csv,hashlib,json,math

PARENT_COMMIT="10b1719aa188b2e589aab4730e3d1a0059f680da"

def sha(p:Path)->str:
    h=hashlib.sha256()
    with p.open("rb") as f:
        for b in iter(lambda:f.read(8*1024*1024),b""):h.update(b)
    return h.hexdigest()

def rows(p):
    with p.open("r",encoding="utf-8-sig",newline="") as f:yield from csv.DictReader(f)

def main():
    ap=argparse.ArgumentParser();ap.add_argument("--project-root",required=True);ap.add_argument("--repo-root",required=True);a=ap.parse_args()
    root=Path(a.project_root).resolve();repo=Path(a.repo_root).resolve();freeze=root/"research"/"prospective_freezes";freeze.mkdir(parents=True,exist_ok=True)
    res=root/"results"/"applause_dr4_corrected_le5min_blind_source_state_census_v094i"
    report=res/"applause_dr4_corrected_le5min_blind_source_state_census_v094i.json"
    manifest=res/"v094i_output_manifest.sha256"
    per=res/"per_opportunity_source_state_v094i.csv";site=res/"site_pair_source_state_summary_v094i.csv";te=res/"timing_epoch_source_state_summary_v094i.csv"
    for p in (report,manifest,per,site,te):
        if not p.is_file():raise SystemExit(f"Missing completed v094i artifact: {p}")
    r=json.loads(report.read_text(encoding="utf-8"))
    if r.get("status")!="COMPLETE":raise SystemExit("v094i report is not COMPLETE")
    expected={
      "opportunities_processed":1240,"exact_scan_solution_keys":1386
    }
    for k,v in expected.items():
        if int(r.get(k,-1))!=v:raise SystemExit(f"Unexpected v094i {k}: {r.get(k)}")
    astate=r.get("aggregate_source_state",{})
    checks={"hq_common_a":None,"hq_common_b":None,"gaia_unresolved_a":0,"gaia_unresolved_b":0,"same_gaia_unique_identities":472992,"zero_hq_side":155}
    for k,v in checks.items():
        if k not in astate:raise SystemExit(f"Missing v094i aggregate field {k}")
        if v is not None and int(astate[k])!=v:raise SystemExit(f"Unexpected v094i {k}: {astate[k]}")
    if int(astate["hq_common_a"])+int(astate["hq_common_b"])!=15042219:raise SystemExit("Unexpected v094i HQ incidence total")
    reuse=r.get("source_reuse",{})
    if int(reuse.get("unique_source_ids",-1))!=12250016:raise SystemExit("Unexpected v094i unique HQ source count")
    # Verify report-owned result hashes.
    oh=r.get("output_hashes",{})
    for p in (per,site,te):
        if oh.get(p.name)!=sha(p):raise SystemExit(f"v094i output hash mismatch: {p.name}")
    # Verify acquisition manifest and all exact cache products, then freeze an inventory without reading source values.
    acq=root/"work"/"applause_dr4_corrected_le5min_blind_source_state_census_v094i"/"state"/"source_acquisition_manifest_v094i.json"
    if not acq.is_file():raise SystemExit("Missing v094i source acquisition manifest")
    am=json.loads(acq.read_text(encoding="utf-8"))
    if am.get("status")!="COMPLETE":raise SystemExit("v094i source acquisition manifest not COMPLETE")
    products=am.get("products",[])
    if len(products)!=1386:raise SystemExit(f"Expected 1386 v094i source-cache products, got {len(products)}")
    invp=freeze/"applause_dr4_v094i_strict_hq_source_cache_inventory_v094j.csv"
    fields=["scan_id","solution_num","rows","relative_path","size_bytes","sha256"]
    tmp=invp.with_suffix(".csv.tmp");total_rows=0
    with tmp.open("w",encoding="utf-8",newline="") as f:
        w=csv.DictWriter(f,fieldnames=fields);w.writeheader()
        for i,x in enumerate(sorted(products,key=lambda q:(int(q["scan_id"]),int(q["solution_num"]))),1):
            p=root/x["path"]
            if not p.is_file():raise SystemExit(f"Missing v094i source cache: {p}")
            h=sha(p)
            if h!=x["sha256"]:raise SystemExit(f"v094i source cache hash mismatch: {p}")
            n=int(x["rows"]);total_rows+=n
            w.writerow({"scan_id":int(x["scan_id"]),"solution_num":int(x["solution_num"]),"rows":n,"relative_path":x["path"],"size_bytes":p.stat().st_size,"sha256":h})
            if i%200==0:print(f"v094j source-cache provenance: {i}/1386",flush=True)
    tmp.replace(invp)
    # Bind frozen v094i plan/provenance and v094d solution geometry.
    iprov=root/"research"/"prospective_freezes"/"applause_dr4_corrected_le5min_blind_source_state_parent_provenance_v094i.json"
    plan=root/"research"/"prospective_freezes"/"applause_dr4_le5min_source_state_opportunity_plan_v094i.csv"
    icontract=root/"research"/"prospective_freezes"/"applause_dr4_corrected_le5min_blind_source_state_census_contract_v094i.json"
    irunner=root/"tools"/"run_applause_dr4_corrected_le5min_blind_source_state_census_v094i.py"
    for p in (iprov,plan,icontract,irunner):
        if not p.is_file():raise SystemExit(f"Missing frozen v094i parent file: {p}")
    ip=json.loads(iprov.read_text(encoding="utf-8"));sol=root/ip["v094d_solution_full"]["path"]
    if not sol.is_file() or sha(sol)!=ip["v094d_solution_full"]["sha256"]:raise SystemExit("Frozen v094d solution_full mismatch")
    prov={
      "status":"PARENT_PROVENANCE_PREPARED_BEFORE_V094J_AGGREGATE_GEOMETRY",
      "required_parent_git_commit":PARENT_COMMIT,
      "preparation_guards":{"network_queries":0,"candidate_inspection":0,"source_value_reads":0,"pixels":0,"registration":0},
      "v094i_results":{"report":str(report.relative_to(root)).replace('\\','/'),"report_sha256":sha(report),"manifest":str(manifest.relative_to(root)).replace('\\','/'),"manifest_sha256":sha(manifest),"per_opportunity":str(per.relative_to(root)).replace('\\','/'),"per_opportunity_sha256":sha(per),"site_summary":str(site.relative_to(root)).replace('\\','/'),"site_summary_sha256":sha(site),"timing_epoch_summary":str(te.relative_to(root)).replace('\\','/'),"timing_epoch_summary_sha256":sha(te)},
      "v094i_frozen":{"contract":str(icontract.relative_to(root)).replace('\\','/'),"contract_sha256":sha(icontract),"runner":str(irunner.relative_to(root)).replace('\\','/'),"runner_sha256":sha(irunner),"parent_provenance":str(iprov.relative_to(root)).replace('\\','/'),"parent_provenance_sha256":sha(iprov),"plan":str(plan.relative_to(root)).replace('\\','/'),"plan_sha256":sha(plan)},
      "v094d_solution_full":{"path":str(sol.relative_to(root)).replace('\\','/'),"sha256":sha(sol)},
      "source_cache_inventory":{"path":str(invp.relative_to(root)).replace('\\','/'),"sha256":sha(invp),"products":1386,"total_rows_across_exact_keys":total_rows},
      "known_v094i_outcomes":{"opportunities":1240,"strict_hq_common_source_incidences_a_plus_b":15042219,"same_gaia_unique_identity_incidences":472992,"gaia_unresolved_hq_incidences_a_plus_b":0,"zero_hq_side_opportunities":155,"unique_hq_source_ids":12250016,"repeated_source_incidence_fraction":float(reuse.get("repeated_incidence_fraction"))}
    }
    pp=freeze/"applause_dr4_strict_hq_gaia_association_geometry_parent_provenance_v094j.json";pp.write_text(json.dumps(prov,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    print(f"v094j parent provenance prepared: {pp}")
    print(f"strict-HQ cache products frozen: 1386")
    print(f"cache product row total: {total_rows:,}")
    print(f"inventory sha256: {sha(invp)}")
    return 0
if __name__=="__main__":raise SystemExit(main())
