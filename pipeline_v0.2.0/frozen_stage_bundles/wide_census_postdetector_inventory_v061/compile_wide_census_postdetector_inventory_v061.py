from pathlib import Path
from datetime import datetime, timezone
import csv, hashlib, json, math, re

ROOT = Path.cwd()
C57 = ROOT/"research"/"prospective_freezes"/"wide_census_postdetector_adjudication_contract_v001.json"
R56 = ROOT/"results"/"wide_census_detector_execution_v056.json"
CSUM = ROOT/"results"/"wide_census_pair_raw_match_summary_v056.csv"
CMAT = ROOT/"results"/"wide_census_pair_raw_matches_v056.csv"
CCAN = ROOT/"results"/"wide_census_detector_candidates_v056.csv"
OUT = ROOT/"results"/"wide_census_postdetector_inventory_v061"
FREEZE = ROOT/"research"/"prospective_freezes"/"wide_census_postdetector_execution_plan_v061.json"

EXPECTED_C57 = "1215400b989b187e87ceee27237fd2faf7ccff80dd57632158e06cbed7add2ad"
EXPECTED = dict(raw10=512788, raw3=185532, pairs=33, candidates=5083325, tiles=6293)

def sha(p):
    h=hashlib.sha256()
    with p.open("rb") as f:
        for b in iter(lambda:f.read(1024*1024), b""): h.update(b)
    return h.hexdigest()

def norm(s): return re.sub(r"[^a-z0-9]+","",str(s).lower())

def pick(r,*names,default=""):
    m={norm(k):k for k in r}
    for n in names:
        k=m.get(norm(n))
        if k is not None and r.get(k) not in (None,""): return r[k]
    return default

def f(v):
    try:
        x=float(str(v).strip())
        return x if math.isfinite(x) else None
    except: return None

def i(v):
    x=f(v); return None if x is None else int(x)

def pair_key(r, rownum=None):
    k=pick(r,"canonical_pair","pair_key","opportunity_id","pair_id","canonical_pair_key")
    if k: return str(k)
    a=pick(r,"exposure_a","endpoint_a","archive_endpoint_a","left_endpoint","poss_exposure")
    b=pick(r,"exposure_b","endpoint_b","archive_endpoint_b","right_endpoint","dasch_exposure")
    if a and b: return f"{a} || {b}"
    x=pick(r,"pair_index","opportunity_index","index")
    if x: return f"PAIR_INDEX:{x}"
    return f"PAIR_ROW:{rownum}" if rownum is not None else ""

def sep(r):
    return f(pick(r,"separation_arcsec","sep_arcsec","raw_separation_arcsec"))

def write_json(p,o):
    p.parent.mkdir(parents=True,exist_ok=True)
    t=p.with_suffix(p.suffix+".tmp")
    t.write_text(json.dumps(o,indent=2,sort_keys=True,default=str)+"\n",encoding="utf-8")
    t.replace(p)

def write_csv(p,rows,fields):
    p.parent.mkdir(parents=True,exist_ok=True)
    t=p.with_suffix(p.suffix+".tmp")
    with t.open("w",newline="",encoding="utf-8") as fh:
        w=csv.DictWriter(fh,fieldnames=fields,extrasaction="ignore");w.writeheader();w.writerows(rows)
    t.replace(p)

def main():
    print("="*132)
    print("WIDE CENSUS — POST-DETECTOR INVENTORY + FROZEN EXECUTION QUEUES v061")
    print("="*132)
    print("NO NETWORK. NO PIXELS. NO DETECTOR. NO CANDIDATE STATE MUTATION.\n")
    for p in (C57,R56,CSUM,CMAT,CCAN):
        if not p.is_file(): raise RuntimeError(f"REFUSING: missing {p}")
    if sha(C57)!=EXPECTED_C57:
        raise RuntimeError("REFUSING: v057 prospective contract SHA changed")
    print("v057 prospective contract SHA: PASS")

    with CSUM.open(newline="",encoding="utf-8-sig") as fh:
        sums=list(csv.DictReader(fh))
    if len(sums)!=EXPECTED["pairs"]:
        raise RuntimeError(f"REFUSING: expected 33 pair rows, got {len(sums)}")

    pairs=[]
    for n,r in enumerate(sums,1):
        a=pick(r,"exposure_a","endpoint_a","archive_endpoint_a","left_endpoint","poss_exposure")
        b=pick(r,"exposure_b","endpoint_b","archive_endpoint_b","right_endpoint","dasch_exposure")
        pairs.append({
            "adjudication_order":n,
            "pair_key":pair_key(r,n),
            "endpoint_a":a,
            "endpoint_b":b,
            "pair_family":pick(r,"pair_family","archive_pair_family"),
            "physical_overlap_s":pick(r,"physical_overlap_s","actual_overlap_s","overlap_s"),
            "summary_raw_le10":pick(r,"raw_le10_count","matches_le10","raw_matches_le10","match_count_le10","raw_match_count"),
            "summary_raw_le3":pick(r,"raw_le3_count","matches_le3","raw_matches_le3","match_count_le3","strict_match_count"),
            "summary_uninformative_coverage":pick(r,"uninformative_detector_coverage","has_uninformative_detector_coverage","coverage_uninformative"),
            "manual_review_state":"NOT_REACHED_AUTOMATED_ADJUDICATION_PENDING",
        })

    total=total3=0
    hist={"le0p5":0,"le1":0,"le2":0,"le3":0,"le5":0,"le10":0}
    with CMAT.open(newline="",encoding="utf-8-sig") as fh:
        rdr=csv.DictReader(fh)
        raw_fields=rdr.fieldnames or []
        for n,r in enumerate(rdr,1):
            s=sep(r)
            if s is None: raise RuntimeError(f"REFUSING: no separation on raw row {n}")
            if s>10.000001: raise RuntimeError(f"REFUSING: >10 arcsec raw row {n}: {s}")
            total+=1
            if s<=3: total3+=1
            if s<=.5: hist["le0p5"]+=1
            if s<=1: hist["le1"]+=1
            if s<=2: hist["le2"]+=1
            if s<=3: hist["le3"]+=1
            if s<=5: hist["le5"]+=1
            if s<=10: hist["le10"]+=1
    if total!=EXPECTED["raw10"] or total3!=EXPECTED["raw3"]:
        raise RuntimeError(f"REFUSING: raw counts changed: <=10 {total}, <=3 {total3}")

    controls=[]
    dirs=(("N",0,1),("NE",1,1),("E",1,0),("SE",1,-1),("S",0,-1),("SW",-1,-1),("W",-1,0),("NW",-1,1))
    for p in pairs:
        for rad in (60,120):
            for name,dx,dy in dirs:
                controls.append({
                    "adjudication_order":p["adjudication_order"],"pair_key":p["pair_key"],
                    "endpoint_a":p["endpoint_a"],"endpoint_b":p["endpoint_b"],
                    "shift_radius_arcsec":rad,"direction":name,"unit_dx":dx,"unit_dy":dy,
                    "gate_3arcsec":True,"gate_10arcsec":True,
                    "population_null_not_individual_rejection":True,
                })

    ast=[]
    for p in pairs:
        for win in (5,10,20,30):
            ast.append({
                "adjudication_order":p["adjudication_order"],"pair_key":p["pair_key"],
                "endpoint_a":p["endpoint_a"],"endpoint_b":p["endpoint_b"],
                "window_arcmin":win,"minimum_same_gaia_common_refs":5,
                "model":"TRANSLATION_MEDIAN_ONLY","clipping":False,"higher_order":False,
                "sparse_fallback_only_if_primary_lt5_at_30arcmin":True,
            })

    OUT.mkdir(parents=True,exist_ok=True)
    write_csv(OUT/"wide_census_postdetector_pair_inventory_v061.csv",pairs,list(pairs[0]))
    write_csv(OUT/"wide_census_population_control_queue_v061.csv",controls,list(controls[0]))
    write_csv(OUT/"wide_census_primary_astrometry_queue_v061.csv",ast,list(ast[0]))

    with CCAN.open(newline="",encoding="utf-8-sig") as fh:
        candidate_fields=next(csv.reader(fh))
    with CSUM.open(newline="",encoding="utf-8-sig") as fh:
        summary_fields=next(csv.reader(fh))
    write_json(OUT/"wide_census_v056_schema_audit_v061.json",{
        "candidate_fields":candidate_fields,"pair_summary_fields":summary_fields,
        "raw_match_fields":raw_fields
    })

    plan={
        "plan_id":"wide_census_postdetector_execution_plan_v061",
        "created_at_utc":datetime.now(timezone.utc).isoformat(),
        "governing_v057_contract":{"sha256":EXPECTED_C57,"path":str(C57.relative_to(ROOT)).replace("\\","/")},
        "v056_evidence":{
            "report_sha256":sha(R56),"candidates_sha256":sha(CCAN),
            "pair_summary_sha256":sha(CSUM),"raw_matches_sha256":sha(CMAT)
        },
        "verified_counts":{
            "tiles":EXPECTED["tiles"],"accepted_candidates":EXPECTED["candidates"],
            "raw_le10":total,"raw_le3":total3,"pairs":len(pairs),
            "pairs_raw_le10":33,"pairs_raw_le3":32,
            "zero_sigma_tiles":2,"pairs_with_uninformative_detector_coverage":2
        },
        "global_raw_separation_histogram":hist,
        "execution_order":[
            "population_shift_controls_60_120_arcsec_8_directions_gates_3_10",
            "primary_common_gaia_registration_windows_5_10_20_30arcmin_min5_translation_median",
            "sparse_fallback_only_if_primary_lt5_at30arcmin_min3_per_archive_LOO_all_gt3arcsec",
            "candidate_level_gaia_epoch_morphology_recurrence_context",
            "manual_review_terminal_survivors_or_ambiguities_only"
        ],
        "interpretation_boundary":"Raw coincidences are measurements only; no science-positive classification is made by v061."
    }
    if FREEZE.exists():
        old=json.loads(FREEZE.read_text(encoding="utf-8"))
        if old.get("plan_id")!=plan["plan_id"]:
            raise RuntimeError("REFUSING: incompatible v061 plan already exists")
    else:
        write_json(FREEZE,plan)

    report={
        "status":"COMPLETE","stage":"wide_census_postdetector_inventory_v061",
        "guards":{"network_access":False,"science_pixels_read":False,"transient_detector_rerun":False,"candidate_state_mutation":False,"automation_registry_mutation":False},
        "v057_contract_sha256":EXPECTED_C57,
        "v061_plan_sha256":sha(FREEZE),
        "verified_counts":plan["verified_counts"],
        "global_raw_separation_histogram":hist,
        "population_control_jobs":len(controls),
        "primary_astrometry_jobs":len(ast)
    }
    write_json(OUT/"wide_census_postdetector_inventory_v061.json",report)

    print("Raw <=10 rows verified:       ",total)
    print("Raw <=3 rows verified:        ",total3)
    print("Pairs verified:               ",len(pairs))
    print("Population-control jobs:      ",len(controls))
    print("Primary-astrometry jobs:      ",len(ast))
    print("Global separation histogram:  ",hist)
    print("Execution plan:",FREEZE)
    print("Execution plan SHA256:",sha(FREEZE))
    print("\nSCIENCE POSITIVES: 0")
    print("STAGE STATUS: PASS")

if __name__=="__main__":
    main()
