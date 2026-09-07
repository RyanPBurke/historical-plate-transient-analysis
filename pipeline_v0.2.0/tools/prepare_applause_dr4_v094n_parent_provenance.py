#!/usr/bin/env python3
from pathlib import Path
import argparse,csv,hashlib,json,subprocess
PARENT="bc425d122b9f293e1be77d321801cafbf49d141c"
def sha(p):
 h=hashlib.sha256()
 with Path(p).open("rb") as f:
  for b in iter(lambda:f.read(8*1024*1024),b""):h.update(b)
 return h.hexdigest()
def rows(p):
 with Path(p).open("r",encoding="utf-8-sig",newline="") as f:yield from csv.DictReader(f)
def main():
 ap=argparse.ArgumentParser();ap.add_argument("--project-root",required=True);ap.add_argument("--repo-root",required=True);a=ap.parse_args()
 root=Path(a.project_root).resolve();repo=Path(a.repo_root).resolve();fr=root/"research"/"prospective_freezes";fr.mkdir(parents=True,exist_ok=True)
 subprocess.run(["git","-C",str(repo),"cat-file","-e",PARENT+"^{commit}"],check=True,stdout=subprocess.DEVNULL)
 mres=root/"results"/"applause_dr4_physical_parallax_search_space_census_v094m"
 mr=mres/"applause_dr4_physical_parallax_search_space_census_v094m.json";mm=mres/"v094m_output_manifest.sha256"
 for p in (mr,mm):
  if not p.is_file():raise SystemExit(f"Missing completed v094m artifact: {p}")
 r=json.loads(mr.read_text(encoding="utf-8"))
 if r.get("status")!="COMPLETE":raise SystemExit("v094m not COMPLETE")
 g=r.get("aggregate",{});geom=r.get("physical_geometry",{})
 checks={"opportunities":1240,"overlap_opportunity":1081,"motion_parallax_degenerate_hold":159,
         "physical_overlap_geometry_eligible":1081,"physical_and_local_model_eligible":60}
 for k,v in checks.items():
  if int(g.get(k,-1))!=v:raise SystemExit(f"Unexpected v094m {k}: {g.get(k)}")
 if int(g.get("unshared_a",0))+int(g.get("unshared_b",0))!=14095293:raise SystemExit("Unexpected v094m unshared incidence total")
 if abs(float(geom.get("projected_baseline_km_median"))-374.39601077139474)>1e-9:raise SystemExit("Unexpected v094m median baseline")
 plan=fr/"applause_dr4_le5min_source_state_opportunity_plan_v094i.csv";inv=fr/"applause_dr4_v094i_strict_hq_source_cache_inventory_v094j.csv"
 mprov=fr/"applause_dr4_physical_parallax_search_space_census_parent_provenance_v094m.json"
 for p in (plan,inv,mprov):
  if not p.is_file():raise SystemExit(f"Missing frozen parent: {p}")
 ir=list(rows(inv))
 if len(ir)!=1386:raise SystemExit("cache inventory mismatch")
 total=0
 for i,q in enumerate(ir,1):
  p=root/q["relative_path"]
  if not p.is_file() or p.stat().st_size!=int(q["size_bytes"]) or sha(p)!=q["sha256"]:raise SystemExit(f"cache mismatch row {i}")
  total+=int(q["rows"])
  if i%200==0:print(f"v094n source-cache provenance: {i}/1386",flush=True)
 mp=json.loads(mprov.read_text(encoding="utf-8"))
 for sec in ("plate_site_cache","solution_full"):
  rec=mp[sec];p=root/rec["path"]
  if not p.is_file() or sha(p)!=rec["sha256"]:raise SystemExit(f"frozen v094m parent mismatch: {sec}")
 prov={"status":"PARENT_PROVENANCE_PREPARED_BEFORE_V094N_BLINDED_MATCHER","required_parent_git_commit":PARENT,
       "v094m_results":{"report":str(mr.relative_to(root)).replace("\\","/"),"report_sha256":sha(mr),
                        "manifest":str(mm.relative_to(root)).replace("\\","/"),"manifest_sha256":sha(mm)},
       "frozen_plan":{"path":str(plan.relative_to(root)).replace("\\","/"),"sha256":sha(plan),"rows":1240},
       "source_cache_inventory":{"path":str(inv.relative_to(root)).replace("\\","/"),"sha256":sha(inv),"products":1386,"rows":total},
       "plate_site_cache":mp["plate_site_cache"],"solution_full":mp["solution_full"],
       "preparation_guards":{"source_value_reads":0,"network_queries":0,"physical_source_pairing":0,"candidate_inspection":0}}
 out=fr/"applause_dr4_no_radius_epipolar_parallax_matcher_parent_provenance_v094n.json"
 out.write_text(json.dumps(prov,indent=2,sort_keys=True)+"\n",encoding="utf-8")
 print(f"v094n parent provenance prepared: {out}")
 print(f"strict-HQ cache products frozen: {len(ir)}")
 print(f"cache product row total: {total:,}")
if __name__=="__main__":main()
