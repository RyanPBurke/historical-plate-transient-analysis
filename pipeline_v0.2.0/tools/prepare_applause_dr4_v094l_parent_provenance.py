#!/usr/bin/env python3
from pathlib import Path
import argparse,csv,hashlib,json,subprocess
PARENT="d5109eea6189e45df1d07045ce7ae57e4397a2cb"
def sha(p):
 h=hashlib.sha256()
 with Path(p).open("rb") as f:
  for b in iter(lambda:f.read(8*1024*1024),b""):h.update(b)
 return h.hexdigest()
def rows(p):
 with Path(p).open("r",encoding="utf-8-sig",newline="") as f:yield from csv.DictReader(f)
def main():
 ap=argparse.ArgumentParser();ap.add_argument("--project-root",required=True);ap.add_argument("--repo-root",required=True);a=ap.parse_args()
 root=Path(a.project_root).resolve();repo=Path(a.repo_root).resolve();freeze=root/"research"/"prospective_freezes";freeze.mkdir(parents=True,exist_ok=True)
 subprocess.run(["git","-C",str(repo),"cat-file","-e",PARENT+"^{commit}"],check=True,stdout=subprocess.DEVNULL)
 kres=root/"results"/"applause_dr4_different_gaia_concentration_astrometry_audit_v094k"
 kr=kres/"applause_dr4_different_gaia_concentration_astrometry_audit_v094k.json"
 km=kres/"v094k_output_manifest.sha256"
 for p in (kr,km):
  if not p.is_file():raise SystemExit(f"Missing completed v094k artifact: {p}")
 r=json.loads(kr.read_text(encoding="utf-8"))
 if r.get("status")!="COMPLETE":raise SystemExit("v094k report not COMPLETE")
 g=r.get("aggregate",{})
 checks={"opportunities":1240,"diff_le5":7874,"diff_le60":77378,"pair_closer_than_both_own_gaia":1523,"both_own_gaia_le1":511,"astrometric_reference_eligible":513}
 for k,v in checks.items():
  got=r.get(k) if k=="opportunities" else g.get(k)
  if int(got if got is not None else -1)!=v:raise SystemExit(f"Unexpected v094k {k}: {got}")
 # Frozen parent artifacts.
 plan=freeze/"applause_dr4_le5min_source_state_opportunity_plan_v094i.csv"
 inv=freeze/"applause_dr4_v094i_strict_hq_source_cache_inventory_v094j.csv"
 jprov=freeze/"applause_dr4_strict_hq_gaia_association_geometry_parent_provenance_v094j.json"
 for p in (plan,inv,jprov):
  if not p.is_file():raise SystemExit(f"Missing frozen parent artifact: {p}")
 if sum(1 for _ in rows(plan))!=1240:raise SystemExit("Plan row mismatch")
 ir=list(rows(inv))
 if len(ir)!=1386:raise SystemExit("Inventory row mismatch")
 total=0
 for i,rec in enumerate(ir,1):
  p=root/rec["relative_path"]
  if not p.is_file() or p.stat().st_size!=int(rec["size_bytes"]) or sha(p)!=rec["sha256"]:raise SystemExit(f"Cache mismatch row {i}")
  total+=int(rec["rows"])
  if i%200==0:print(f"v094l source-cache provenance: {i}/1386",flush=True)
 jp=json.loads(jprov.read_text(encoding="utf-8"));sol=root/jp["v094d_solution_full"]["path"]
 if not sol.is_file() or sha(sol)!=jp["v094d_solution_full"]["sha256"]:raise SystemExit("solution_full mismatch")
 prov={
  "status":"PARENT_PROVENANCE_PREPARED_BEFORE_V094L_LOCAL_FIELD_AUDIT",
  "required_parent_git_commit":PARENT,
  "v094k_results":{"report":str(kr.relative_to(root)).replace("\\","/"),"report_sha256":sha(kr),
                   "manifest":str(km.relative_to(root)).replace("\\","/"),"manifest_sha256":sha(km)},
  "frozen_plan":{"path":str(plan.relative_to(root)).replace("\\","/"),"sha256":sha(plan),"rows":1240},
  "source_cache_inventory":{"path":str(inv.relative_to(root)).replace("\\","/"),"sha256":sha(inv),"products":1386,"row_total":total},
  "v094d_solution_full":{"path":str(sol.relative_to(root)).replace("\\","/"),"sha256":sha(sol)},
  "guards":{"source_value_reads":0,"network_queries":0,"pixels":0,"registration":0,"candidate_inspection":0,"physical_parallax_pairing":0}
 }
 out=freeze/"applause_dr4_local_astrometric_field_audit_parent_provenance_v094l.json"
 out.write_text(json.dumps(prov,indent=2,sort_keys=True)+"\n",encoding="utf-8")
 print(f"v094l parent provenance prepared: {out}")
 print(f"strict-HQ cache products frozen: {len(ir)}")
 print(f"cache product row total: {total:,}")
if __name__=="__main__":main()
