#!/usr/bin/env python3
from pathlib import Path
import argparse,csv,hashlib,json,subprocess

PARENT="d9d1bc3acf7ae6eff03d75afe89c9dd18c64aa30"

def sha(p):
    h=hashlib.sha256()
    with Path(p).open("rb") as f:
        for b in iter(lambda:f.read(8*1024*1024),b""):
            h.update(b)
    return h.hexdigest()

def rows(p):
    with Path(p).open("r",encoding="utf-8-sig",newline="") as f:
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

    subprocess.run(["git","-C",str(repo),"cat-file","-e",PARENT+"^{commit}"],check=True,stdout=subprocess.DEVNULL)
    subprocess.run(["git","-C",str(repo),"merge-base","--is-ancestor",PARENT,"HEAD"],check=True,stdout=subprocess.DEVNULL)

    pres=root/"results"/"applause_dr4_measurement_integrity_validation_gate_v094p"
    prep=pres/"applause_dr4_measurement_integrity_validation_gate_v094p.json"
    pman=pres/"v094p_output_manifest.sha256"
    for f in (prep,pman):
        if not f.is_file(): raise SystemExit(f"Missing completed v094p artifact: {f}")
    rr=json.loads(prep.read_text(encoding="utf-8"))
    if rr.get("status")!="COMPLETE": raise SystemExit("v094p is not COMPLETE")
    g=rr["gaia_id_integrity"]
    checks={
      "positive_row_cache_keys_exactly_verified":1362,
      "rows_compared":21609122,
      "gaia_id_rows_changed_by_cached_conversion":10583188,
      "gaia_positive_status_changes":0,
      "cached_gaia_values_with_multiple_distinct_exact_raw_ids":26331,
    }
    for k,v in checks.items():
        if int(g.get(k,-1))!=v: raise SystemExit(f"Unexpected v094p {k}: {g.get(k)}")

    pp=freeze/"applause_dr4_measurement_integrity_validation_gate_parent_provenance_v094p.json"
    if not pp.is_file(): raise SystemExit("Missing frozen v094p parent provenance")
    p=json.loads(pp.read_text(encoding="utf-8"))

    active={}
    for sec in ("frozen_plan","source_cache_inventory","plate_site_cache","solution_full","v094d_exposure_full","v094d_exposure_sub_full"):
        rec=p[sec];f=root/rec["path"]
        if not f.is_file() or sha(f)!=rec["sha256"]: raise SystemExit(f"Frozen v094p parent mismatch: {sec}")
        active[sec]=rec

    raw_files=p["raw_votables"]["files"]
    if len(raw_files)!=347: raise SystemExit(f"Expected 347 raw VOTables, got {len(raw_files)}")
    print("Verifying retained raw VOTable hashes for v094q provenance...",flush=True)
    for i,rec in enumerate(raw_files,1):
        f=root/rec["path"]
        if not f.is_file() or f.stat().st_size!=int(rec["size_bytes"]) or sha(f)!=rec["sha256"]:
            raise SystemExit(f"Raw VOTable mismatch: {f}")
        if i%25==0: print(f"v094q raw provenance: {i}/347",flush=True)

    inv=list(rows(root/active["source_cache_inventory"]["path"]))
    if len(inv)!=1386: raise SystemExit(f"Expected 1386 cache products, got {len(inv)}")
    if sum(int(r["rows"]) for r in inv)!=21609122: raise SystemExit("Frozen cache row total mismatch")

    prov={
      "status":"PARENT_PROVENANCE_PREPARED_BEFORE_V094Q_VALUES",
      "required_parent_git_commit":PARENT,
      "v094p_result":{"path":str(prep.relative_to(root)).replace("\\","/"),"sha256":sha(prep),
                      "manifest_path":str(pman.relative_to(root)).replace("\\","/"),"manifest_sha256":sha(pman)},
      **active,
      "raw_votables":{"files":raw_files,"file_count":347},
      "expected_cache_products":1386,
      "expected_cache_rows":21609122,
      "preparation_guards":{"raw_catalogue_value_reads":0,"source_cache_value_reads":0,
                            "candidate_identity_reads":0,"private_candidate_map_reads":0,"network_queries":0}
    }
    out=freeze/"applause_dr4_exact_gaia_identity_and_timing_reconstruction_parent_provenance_v094q.json"
    out.write_text(json.dumps(prov,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    print(f"v094q parent provenance prepared: {out}")
    return 0

if __name__=="__main__":
    raise SystemExit(main())
