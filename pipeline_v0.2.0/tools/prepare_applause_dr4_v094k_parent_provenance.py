#!/usr/bin/env python3
from __future__ import annotations
from pathlib import Path
import argparse,csv,hashlib,json,subprocess

PARENT_COMMIT="24e466b8b23a49dad0fbcdb4ecd460d0c12c8a83"

def sha(p:Path)->str:
    h=hashlib.sha256()
    with p.open("rb") as f:
        for b in iter(lambda:f.read(8*1024*1024),b""): h.update(b)
    return h.hexdigest()

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

    # Parent git ancestry must already exist locally.
    subprocess.run(["git","-C",str(repo),"cat-file","-e",PARENT_COMMIT+"^{commit}"],check=True,
                   stdout=subprocess.DEVNULL)

    v094j_res=root/"results"/"applause_dr4_strict_hq_gaia_association_geometry_audit_v094j"
    report=v094j_res/"applause_dr4_strict_hq_gaia_association_geometry_audit_v094j.json"
    manifest=v094j_res/"v094j_output_manifest.sha256"
    per=v094j_res/"per_opportunity_hq_gaia_geometry_v094j.csv"
    site=v094j_res/"site_pair_hq_gaia_geometry_summary_v094j.csv"
    te=v094j_res/"timing_epoch_hq_gaia_geometry_summary_v094j.csv"
    for p in (report,manifest,per,site,te):
        if not p.is_file(): raise SystemExit(f"Missing completed v094j artifact: {p}")

    r=json.loads(report.read_text(encoding="utf-8"))
    if r.get("status")!="COMPLETE": raise SystemExit("v094j report is not COMPLETE")
    if int(r.get("opportunities",-1))!=1240: raise SystemExit("Unexpected v094j opportunity count")
    g=r.get("aggregate",{})
    checks={
      "mutual_le5":410361,
      "mutual_SAME_GAIA_le5":402487,
      "mutual_DIFFERENT_GAIA_le5":7874,
      "mutual_DIFFERENT_GAIA_le60":77378,
      "mutual_DIFFERENT_GAIA_pair_closer_than_both_own_gaia_le5":1523,
      "mutual_DIFFERENT_GAIA_both_tight_le1_le5":511,
      "shared_gaia_identities":472992,
    }
    for k,v in checks.items():
        if int(g.get(k,-1))!=v: raise SystemExit(f"Unexpected v094j aggregate {k}: {g.get(k)}")

    # Verify hashes owned by v094j report.
    for p in (per,site,te):
        if r.get("output_hashes",{}).get(p.name)!=sha(p):
            raise SystemExit(f"v094j output hash mismatch: {p.name}")

    # Frozen v094i plan and v094j cache inventory are already prospective artifacts.
    plan=freeze/"applause_dr4_le5min_source_state_opportunity_plan_v094i.csv"
    inv=freeze/"applause_dr4_v094i_strict_hq_source_cache_inventory_v094j.csv"
    v094j_prov=freeze/"applause_dr4_strict_hq_gaia_association_geometry_parent_provenance_v094j.json"
    v094j_contract=freeze/"applause_dr4_strict_hq_gaia_association_geometry_contract_v094j.json"
    for p in (plan,inv,v094j_prov,v094j_contract):
        if not p.is_file(): raise SystemExit(f"Missing frozen parent artifact: {p}")
    if sum(1 for _ in rows(plan))!=1240: raise SystemExit("v094i plan row count mismatch")
    inv_rows=list(rows(inv))
    if len(inv_rows)!=1386: raise SystemExit("v094j cache inventory row count mismatch")

    # Hash-verify every source cache without interpreting source values.
    total_rows=0
    for i,rec in enumerate(inv_rows,1):
        p=root/rec["relative_path"]
        if (not p.is_file() or p.stat().st_size!=int(rec["size_bytes"]) or sha(p)!=rec["sha256"]):
            raise SystemExit(f"Frozen v094i source cache mismatch at inventory row {i}")
        total_rows+=int(rec["rows"])
        if i%200==0: print(f"v094k source-cache provenance: {i}/1386",flush=True)

    # Solution metadata is the already-frozen v094d normalized table.
    v094j_p=json.loads(v094j_prov.read_text(encoding="utf-8"))
    solrel=v094j_p["v094d_solution_full"]["path"]
    sol=root/solrel
    if not sol.is_file() or sha(sol)!=v094j_p["v094d_solution_full"]["sha256"]:
        raise SystemExit("Frozen solution_full mismatch")

    prov={
      "status":"PARENT_PROVENANCE_PREPARED_BEFORE_V094K_SOURCE_MECHANISM_AUDIT",
      "required_parent_git_commit":PARENT_COMMIT,
      "known_v094j_outcomes":{
        "opportunities":1240,
        "mutual_le5":410361,
        "mutual_same_gaia_le5":402487,
        "mutual_different_gaia_le5":7874,
        "mutual_different_gaia_le60":77378,
        "pair_closer_than_both_own_gaia_le5":1523,
        "both_own_gaia_le1_with_pair_le5":511
      },
      "v094j_results":{
        "report":str(report.relative_to(root)).replace("\\","/"),"report_sha256":sha(report),
        "manifest":str(manifest.relative_to(root)).replace("\\","/"),"manifest_sha256":sha(manifest),
        "per_opportunity":str(per.relative_to(root)).replace("\\","/"),"per_opportunity_sha256":sha(per),
        "site_summary":str(site.relative_to(root)).replace("\\","/"),"site_summary_sha256":sha(site),
        "timing_epoch_summary":str(te.relative_to(root)).replace("\\","/"),"timing_epoch_summary_sha256":sha(te)
      },
      "frozen_plan":{"path":str(plan.relative_to(root)).replace("\\","/"),"sha256":sha(plan),"rows":1240},
      "source_cache_inventory":{"path":str(inv.relative_to(root)).replace("\\","/"),"sha256":sha(inv),
                                "products":1386,"row_total":total_rows},
      "v094d_solution_full":{"path":solrel,"sha256":sha(sol)},
      "preparation_guards":{"source_value_reads":0,"network_queries":0,"candidate_inspection":0,
                            "pixels":0,"registration":0,"physical_parallax_pairing":0}
    }
    out=freeze/"applause_dr4_different_gaia_concentration_astrometry_parent_provenance_v094k.json"
    out.write_text(json.dumps(prov,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    print(f"v094k parent provenance prepared: {out}")
    print(f"strict-HQ cache products frozen: {len(inv_rows)}")
    print(f"cache product row total: {total_rows:,}")
    print(f"inventory sha256: {sha(inv)}")

if __name__=="__main__":
    main()
