#!/usr/bin/env python3
from pathlib import Path
import argparse,csv,hashlib,json,subprocess
PARENT="48a64ae951bbae0f052be32fce63b11592d70509"
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
 o=root/"results"/"applause_dr4_symmetric_baseline_rotation_null_v094o";orep=o/"applause_dr4_symmetric_baseline_rotation_null_v094o.json";oman=o/"v094o_output_manifest.sha256"
 for f in (orep,oman):
  if not f.is_file():raise SystemExit(f"Missing completed v094o artifact: {f}")
 rr=json.loads(orep.read_text(encoding="utf-8"))
 if rr.get("status")!="COMPLETE" or int(rr["aggregate"]["ROT0"]["matches"])!=997370:raise SystemExit("Unexpected v094o result")
 opv=fr/"applause_dr4_symmetric_baseline_rotation_null_parent_provenance_v094o.json"
 if not opv.is_file():raise SystemExit("Missing frozen v094o parent provenance")
 p=json.loads(opv.read_text(encoding="utf-8"))
 for sec in ("frozen_plan","source_cache_inventory","plate_site_cache","solution_full"):
  rec=p[sec];f=root/rec["path"]
  if not f.is_file() or sha(f)!=rec["sha256"]:raise SystemExit(f"Frozen parent mismatch: {sec}")
 norm=root/"work"/"applause_dr4_fragment_timing_recoverability_audit_v094d"/"tap_normalized_csv";ef=norm/"exposure_full.csv";es=norm/"exposure_sub_full.csv"
 for f in (ef,es):
  if not f.is_file():raise SystemExit(f"Missing frozen v094d normalized file: {f}")
 rawdir=root/"work"/"applause_dr4_corrected_le5min_blind_source_state_census_v094i"/"tap_raw"
 raws=sorted(rawdir.glob("*.vot")) if rawdir.is_dir() else []
 if not raws:raise SystemExit(f"No retained v094i raw VOTables found in {rawdir}")
 print(f"Hashing retained raw VOTables for v094p provenance: {len(raws)} files",flush=True)
 ri=[]
 for i,f in enumerate(raws,1):
  ri.append({"path":str(f.relative_to(root)).replace("\\","/"),"size_bytes":f.stat().st_size,"sha256":sha(f)})
  if i%25==0:print(f"v094p raw provenance: {i}/{len(raws)}",flush=True)
 inv=list(rows(root/p["source_cache_inventory"]["path"]));pos=sum(int(q.get("rows") or 0)>0 for q in inv)
 if len(inv)!=1386:raise SystemExit(f"Expected 1386 cache keys, got {len(inv)}")
 prov={"status":"PARENT_PROVENANCE_PREPARED_BEFORE_V094P_MEASUREMENT_INTEGRITY_VALUES","required_parent_git_commit":PARENT,
       "v094o_result":{"path":str(orep.relative_to(root)).replace("\\","/"),"sha256":sha(orep),"manifest_path":str(oman.relative_to(root)).replace("\\","/"),"manifest_sha256":sha(oman)},
       "frozen_plan":p["frozen_plan"],"source_cache_inventory":p["source_cache_inventory"],"plate_site_cache":p["plate_site_cache"],"solution_full":p["solution_full"],
       "v094d_exposure_full":{"path":str(ef.relative_to(root)).replace("\\","/"),"sha256":sha(ef)},"v094d_exposure_sub_full":{"path":str(es.relative_to(root)).replace("\\","/"),"sha256":sha(es)},
       "raw_votables":{"directory":str(rawdir.relative_to(root)).replace("\\","/"),"files":ri,"file_count":len(ri),"positive_row_cache_keys":pos},
       "preparation_guards":{"raw_votable_value_reads":0,"source_cache_value_reads":0,"candidate_identity_reads":0,"private_candidate_map_reads":0,"network_queries":0}}
 out=fr/"applause_dr4_measurement_integrity_validation_gate_parent_provenance_v094p.json";out.write_text(json.dumps(prov,indent=2,sort_keys=True)+"\n",encoding="utf-8")
 print(f"v094p parent provenance prepared: {out}");print(f"Retained raw VOTables frozen: {len(ri)}");print(f"Positive-row cache keys requiring exact-ID verification: {pos}")
 return 0
if __name__=="__main__":raise SystemExit(main())
