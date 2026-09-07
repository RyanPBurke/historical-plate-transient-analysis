#!/usr/bin/env python3
from pathlib import Path
import argparse,csv,hashlib,json,subprocess
PARENT="13d16a85080a73d2eacff347c2b7f8e1a7e3b5ce"
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
 lres=root/"results"/"applause_dr4_local_astrometric_field_audit_v094l"
 lr=lres/"applause_dr4_local_astrometric_field_audit_v094l.json";lm=lres/"v094l_output_manifest.sha256"
 for p in (lr,lm):
  if not p.is_file():raise SystemExit(f"Missing completed v094l artifact: {p}")
 r=json.loads(lr.read_text(encoding="utf-8"))
 if r.get("status")!="COMPLETE":raise SystemExit("v094l not COMPLETE")
 g=r.get("aggregate",{});f=r.get("fractions",{});cv=r.get("cross_validation",{})
 checks={"targets_raw":7874,"affine_evaluable":7573,"local_evaluable":7573}
 for k,v in checks.items():
  if int(g.get(k,-1))!=v:raise SystemExit(f"Unexpected v094l {k}: {g.get(k)}")
 local_le2=sum(int(g.get(k,0)) for k in ("local_LE0P5","local_GT0P5_LE1","local_GT1_LE2"))
 if local_le2!=4969:raise SystemExit(f"Unexpected v094l local<=2 count: {local_le2}")
 if abs(float(cv.get("p95_arcsec"))-1.3937548444277144)>1e-12:raise SystemExit("Unexpected v094l CV p95")
 plan=fr/"applause_dr4_le5min_source_state_opportunity_plan_v094i.csv"
 inv=fr/"applause_dr4_v094i_strict_hq_source_cache_inventory_v094j.csv"
 hprov=fr/"applause_dr4_fragment_aware_cross_site_opportunity_census_parent_provenance_v094h.json"
 for p in (plan,inv,hprov):
  if not p.is_file():raise SystemExit(f"Missing frozen parent artifact: {p}")
 if sum(1 for _ in rows(plan))!=1240:raise SystemExit("v094i plan mismatch")
 ir=list(rows(inv))
 if len(ir)!=1386:raise SystemExit("cache inventory mismatch")
 total=0
 for i,q in enumerate(ir,1):
  p=root/q["relative_path"]
  if not p.is_file() or p.stat().st_size!=int(q["size_bytes"]) or sha(p)!=q["sha256"]:raise SystemExit(f"cache mismatch row {i}")
  total+=int(q["rows"])
  if i%200==0:print(f"v094m source-cache provenance: {i}/1386",flush=True)
 hp=json.loads(hprov.read_text(encoding="utf-8"))
 plate=root/hp["v093d_plate_cache"]["path"]
 sol=root/hp["v094d_normalized"]["solution_full"]["path"]
 for p,h in ((plate,hp["v093d_plate_cache"]["sha256"]),(sol,hp["v094d_normalized"]["solution_full"]["sha256"])):
  if not p.is_file() or sha(p)!=h:raise SystemExit(f"frozen v094h parent mismatch: {p}")
 prov={"status":"PARENT_PROVENANCE_PREPARED_BEFORE_V094M_PHYSICAL_SEARCH_SPACE_CENSUS",
       "required_parent_git_commit":PARENT,
       "v094l_results":{"report":str(lr.relative_to(root)).replace("\\","/"),"report_sha256":sha(lr),
                        "manifest":str(lm.relative_to(root)).replace("\\","/"),"manifest_sha256":sha(lm)},
       "frozen_plan":{"path":str(plan.relative_to(root)).replace("\\","/"),"sha256":sha(plan),"rows":1240},
       "source_cache_inventory":{"path":str(inv.relative_to(root)).replace("\\","/"),"sha256":sha(inv),"products":1386,"rows":total},
       "plate_site_cache":{"path":str(plate.relative_to(root)).replace("\\","/"),"sha256":sha(plate)},
       "solution_full":{"path":str(sol.relative_to(root)).replace("\\","/"),"sha256":sha(sol)},
       "preparation_guards":{"source_value_reads":0,"network_queries":0,"physical_source_pairing":0,"pixels":0,"candidate_inspection":0}}
 out=fr/"applause_dr4_physical_parallax_search_space_census_parent_provenance_v094m.json"
 out.write_text(json.dumps(prov,indent=2,sort_keys=True)+"\n",encoding="utf-8")
 print(f"v094m parent provenance prepared: {out}")
 print(f"strict-HQ cache products frozen: {len(ir)}")
 print(f"cache product row total: {total:,}")
if __name__=="__main__":main()
