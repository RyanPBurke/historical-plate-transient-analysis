#!/usr/bin/env python3
from pathlib import Path
import argparse,csv,hashlib,json,subprocess
PARENT="96dcafbc93ebb015ecc6baf5475c27e92958a5f2"
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
 subprocess.run(["git","-C",str(repo),"merge-base","--is-ancestor",PARENT,"HEAD"],check=True,stdout=subprocess.DEVNULL)
 # Completed v094n result is aggregate-only input provenance; private map is deliberately not opened.
 rdir=root/"results"/"applause_dr4_no_radius_epipolar_parallax_matcher_v094n"
 rp=rdir/"applause_dr4_no_radius_epipolar_parallax_matcher_v094n.json"
 man=rdir/"v094n_output_manifest.sha256"
 if not rp.is_file() or not man.is_file():raise SystemExit("Missing completed v094n results")
 r=json.loads(rp.read_text(encoding="utf-8"))
 if r.get("status")!="COMPLETE":raise SystemExit("v094n not COMPLETE")
 g=r.get("aggregate",{})
 for k,v in {"physical_matches":997370,"calibrated_physical_matches":732422,"overlap_opportunities":1081,"nonoverlap_hold":159}.items():
  if int(g.get(k,-1))!=v:raise SystemExit(f"Unexpected v094n {k}: {g.get(k)}")
 # Frozen v094n provenance points to the exact plan/caches/site/solution parents.
 npv=fr/"applause_dr4_no_radius_epipolar_parallax_matcher_parent_provenance_v094n.json"
 if not npv.is_file():raise SystemExit("Missing frozen v094n parent provenance")
 p=json.loads(npv.read_text(encoding="utf-8"))
 plan=root/p["frozen_plan"]["path"];inv=root/p["source_cache_inventory"]["path"]
 if not plan.is_file() or sha(plan)!=p["frozen_plan"]["sha256"]:raise SystemExit("Frozen plan mismatch")
 ir=list(rows(inv))
 if len(ir)!=1386:raise SystemExit("Cache inventory row mismatch")
 total=0
 for i,q in enumerate(ir,1):
  f=root/q["relative_path"]
  if not f.is_file() or f.stat().st_size!=int(q["size_bytes"]) or sha(f)!=q["sha256"]:raise SystemExit(f"Cache mismatch row {i}")
  total+=int(q["rows"])
  if i%200==0:print(f"v094o source-cache provenance: {i}/1386",flush=True)
 for sec in ("plate_site_cache","solution_full"):
  rec=p[sec];f=root/rec["path"]
  if not f.is_file() or sha(f)!=rec["sha256"]:raise SystemExit(f"Frozen parent mismatch: {sec}")
 orig=root/"tools"/"run_applause_dr4_no_radius_epipolar_parallax_matcher_v094n.py"
 if not orig.is_file():raise SystemExit("Missing frozen original v094n runner")
 prov={"status":"PARENT_PROVENANCE_PREPARED_BEFORE_V094O_SYMMETRIC_NULL",
       "required_parent_git_commit":PARENT,
       "v094n_result":{"path":str(rp.relative_to(root)).replace("\\","/"),"sha256":sha(rp),
                       "manifest_path":str(man.relative_to(root)).replace("\\","/"),"manifest_sha256":sha(man),
                       "physical_matches":997370,"calibrated_physical_matches":732422},
       "frozen_plan":p["frozen_plan"],"source_cache_inventory":p["source_cache_inventory"],
       "plate_site_cache":p["plate_site_cache"],"solution_full":p["solution_full"],
       "original_v094n_runner":{"path":str(orig.relative_to(root)).replace("\\","/"),"sha256":sha(orig)},
       "private_candidate_map_read":False,
       "preparation_guards":{"source_value_reads":0,"candidate_identity_reads":0,"network_queries":0}}
 out=fr/"applause_dr4_symmetric_baseline_rotation_null_parent_provenance_v094o.json"
 out.write_text(json.dumps(prov,indent=2,sort_keys=True)+"\n",encoding="utf-8")
 print(f"v094o parent provenance prepared: {out}")
 print(f"strict-HQ cache products frozen: {len(ir)}")
 print(f"cache product row total: {total:,}")
if __name__=="__main__":main()
