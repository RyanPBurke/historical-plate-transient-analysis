#!/usr/bin/env python3
from __future__ import annotations
from pathlib import Path
from collections import Counter, defaultdict
from datetime import datetime, timezone
import argparse, csv, hashlib, importlib.util, json, math, os, shutil

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT/"research"/"prospective_freezes"/"v094x_source_free_full_population_finite_geometry_synthetic_validation_contract.json"
EXPECTED_CONTRACT_SHA = "a0eb265413d15988252c47c9bf139ef0232a4f4dfa2d0ba9ba4c7c7f0efc87d3"
V094T = ROOT/"results"/"applause_dr4_source_free_opportunity_population_repair_v094t"
V094T_CSV = V094T/"applause_dr4_source_free_cross_site_opportunities_v094t.csv"
V094T_REPORT = V094T/"applause_dr4_source_free_opportunity_population_repair_v094t.json"
V094T_MANIFEST = V094T/"v094t_output_manifest.sha256"
V094W = ROOT/"results"/"applause_dr4_v094w_full_site_reference_coverage_replay"
V094W_SITE = V094W/"v094w_site_foundation.csv"
V094W_REPORT = V094W/"v094w_full_site_reference_coverage_replay.json"
V094W_MANIFEST = V094W/"v094w_output_manifest.sha256"
V094S_PROV = ROOT/"research"/"prospective_freezes"/"v094s_source_free_opportunity_population_parent_provenance.json"

WORK = ROOT/"work"/"applause_dr4_v094x_full_population_finite_geometry_synthetic_validation"
CHUNKS = WORK/"chunks"
RESULT = ROOT/"results"/"applause_dr4_v094x_full_population_finite_geometry_synthetic_validation"

GEOM_REL = Path("pipeline_v0.2.0/tools/run_applause_dr4_historical_geometry_validation_v094r3c.py")
R3B_REL = Path("pipeline_v0.2.0/research/prospective_freezes/v094r3b_historical_geometry_validation")
C01_REL = R3B_REL/"inputs/acquisition/references/EOP_C01_IAU2000_1846-now.txt"
HIST_REL = R3B_REL/"inputs/acquisition/references/historic_deltat.data"
V094V_REL = Path("pipeline_v0.2.0/research/prospective_freezes/v094v_site_reference_acquisition")
MONTH_REL = V094V_REL/"deltat.data"

C01_SHA = "846cb53ae1055de1cd80ab78e065b05ad0bc3b224bf8eafe27f428eb12da3ffb"
HIST_SHA = "9f43514119060601a00624a5d9287a91b0b1f5e12bec5209bbabda90b392b70b"
MONTH_SHA = "9f88e53593495a09219fe956eeadea0fa9f8e3e02c310b2aa2b70852383cdf6f"

RE = 6378.137
AU = 149597870.7
DISTANCES_KM = (2*RE, 0.01*AU, 0.1*AU)
GRID_LEVELS = (9,17,33,65)
MAX_PER_CASE = 3
CHUNK_SIZE = 25
SIG_FIELDS = (
    "pair_id","exposure_a","exposure_b","plate_a","plate_b",
    "solution_id_a","solution_id_b","scan_id_a","scan_id_b",
    "site_a","site_b","timing_bin","fragment_overlap_intervals_json",
    "fragment_overlap_count","total_fragment_overlap_seconds",
    "timing_status_a","timing_status_b","num_sub_a","num_sub_b"
)
OUTPUT_FIELDS = [
    "pair_index","pair_id","parent_signature_sha256","plate_a","plate_b","solution_id_a","solution_id_b",
    "site_a","site_b","legacy_infinity_geometry_status","old_common_positive_infinity_footprint",
    "overlap_interval_count","baseline_length_km_min","baseline_length_km_max","baseline_sweep_max_arcsec",
    "deltat_sources","deltat_uncertainty_qualification",
    "time_distance_cases","cases_with_observable_placement","cases_without_observable_placement",
    "max_grid_level_used","placements","recovered","recovery_failures",
    "available_published_reference_gt2arcsec","height107m_gt2arcsec",
    "observable_distance_grid_values_km_json","by_distance_json","status"
]

def sha(p):
    h=hashlib.sha256()
    with Path(p).open("rb") as f:
        for b in iter(lambda:f.read(8*1024*1024),b""):h.update(b)
    return h.hexdigest()

def rows(p):
    with Path(p).open("r",encoding="utf-8-sig",newline="") as f:
        yield from csv.DictReader(f)

def fnum(v):
    try:
        x=float(str(v if v is not None else "").strip())
        return x if math.isfinite(x) else None
    except:return None

def inum(v):
    x=fnum(v)
    if x is None:return None
    q=int(round(x))
    return q if abs(x-q)<1e-9 else None

def parse_dt(v):
    s=str(v or "").strip().replace("Z","+00:00")
    if not s:return None
    try:d=datetime.fromisoformat(s)
    except:return None
    if d.tzinfo is None:d=d.replace(tzinfo=timezone.utc)
    return d.astimezone(timezone.utc)

def log(s):
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {s}",flush=True)

def manifest_check(manifest,base):
    seen={}
    for line in Path(manifest).read_text(encoding="utf-8").splitlines():
        q=line.strip().split(None,1)
        if len(q)!=2:continue
        digest,name=q[0].lower(),q[1].strip()
        p=Path(base)/name
        if not p.is_file() or sha(p)!=digest:
            raise SystemExit(f"Manifest HOLD: {name}")
        seen[name]=digest
    return seen

def parent_signature(r):
    raw="\x1f".join(str(r.get(k,"")) for k in SIG_FIELDS).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()

def load_parent_geometry(repo_root):
    p=Path(repo_root)/GEOM_REL
    if not p.is_file():raise SystemExit(f"Missing inherited geometry module: {p}")
    spec=importlib.util.spec_from_file_location("v094x_r3c_geometry",p)
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
    required=("parse_c01","parse_hist_deltat","parse_month_deltat","geometry_at","search_pair",
              "reference_uncertainty_scores","center","project","unproject","inside",
              "in_polygon_vec","angle_arcsec","radec","xyz")
    missing=[x for x in required if not hasattr(m,x)]
    if missing:raise SystemExit(f"Inherited geometry API HOLD: {missing}")
    return m

def tangent_grid(m,poly,n):
    import numpy as np
    ra0,dec0=m.center([poly])
    px,py,ok=m.project([q[0] for q in poly],[q[1] for q in poly],ra0,dec0)
    if not np.all(ok):return []
    xs=np.linspace(float(px.min()),float(px.max()),n)
    ys=np.linspace(float(py.min()),float(py.max()),n)
    candidates=[]
    for y in ys:
        for x in xs:
            if m.inside(float(x),float(y),list(zip(px,py))):
                u=m.unproject(float(x),float(y),ra0,dec0)
                candidates.append((x*x+y*y,u))
    candidates.sort(key=lambda z:z[0])
    return [u for _,u in candidates]

def ray_sphere(r,n,D):
    import numpy as np
    r=np.asarray(r,float);n=np.asarray(n,float);n=n/np.linalg.norm(n)
    rn=float(r@n);disc=rn*rn + D*D - float(r@r)
    if disc<=0:return None
    t=-rn+math.sqrt(disc)
    if t<=0:return None
    return r+t*n

def unique_pair(m,seen,nA,nB):
    raA,deA=m.radec(nA);raB,deB=m.radec(nB)
    key=(round(raA,8),round(deA,8),round(raB,8),round(deB,8))
    if key in seen:return False
    seen.add(key);return True

def find_case_candidates(m,polyA,polyB,A,B,D,grid_cache):
    import numpy as np
    found=[];seen=set();used=GRID_LEVELS[-1]
    for N in GRID_LEVELS:
        for side in ("A","B"):
            key=(side,N)
            if key not in grid_cache:
                grid_cache[key]=tangent_grid(m,polyA if side=="A" else polyB,N)
            for n0 in grid_cache[key]:
                if side=="A":
                    if float(n0@A["up"])<=0:continue
                    R=ray_sphere(A["r"],n0,D)
                    if R is None:continue
                    nA=n0/np.linalg.norm(n0);nB=R-B["r"];nB/=np.linalg.norm(nB)
                else:
                    if float(n0@B["up"])<=0:continue
                    R=ray_sphere(B["r"],n0,D)
                    if R is None:continue
                    nB=n0/np.linalg.norm(n0);nA=R-A["r"];nA/=np.linalg.norm(nA)
                if float(nA@A["up"])<=0 or float(nB@B["up"])<=0:continue
                if not m.in_polygon_vec(nA,polyA) or not m.in_polygon_vec(nB,polyB):continue
                disp=m.angle_arcsec(nA,nB)
                if disp is None or disp<2.0:continue
                if unique_pair(m,seen,nA,nB):found.append((nA,nB))
        if len(found)>=MAX_PER_CASE:
            used=N;break
    if not found:return [],used
    cA=m.xyz(*m.center([polyA]));cB=m.xyz(*m.center([polyB]))
    ranked=[]
    for nA,nB in found:
        sc=(m.angle_arcsec(cA,nA) or 0)+(m.angle_arcsec(cB,nB) or 0)
        ranked.append((sc,nA,nB))
    ranked.sort(key=lambda z:z[0])
    if len(ranked)<=MAX_PER_CASE:chosen=ranked
    else:
        idx=sorted(set((0,len(ranked)//2,len(ranked)-1)))
        chosen=[ranked[i] for i in idx]
    return [(a,b) for _,a,b in chosen],used

def classify(nominal_ok,placements,recovery_fail,reference_fail,height_fail,monthly_qualified):
    if not nominal_ok:return "GEOMETRY_REFERENCE_COVERAGE_HOLD"
    if placements<=0:return "NO_JOINT_OBSERVABLE_CASE_FOUND_AT_MAX_RESOLUTION"
    if recovery_fail>0 or reference_fail>0:return "FINITE_GEOMETRY_SYNTHETIC_PRECISION_HOLD"
    if height_fail>0:return "FINITE_GEOMETRY_SITE_METADATA_STRESS_HOLD"
    if monthly_qualified:return "FINITE_GEOMETRY_SYNTHETIC_PASS_DELTAT_UNCERTAINTY_QUALIFIED"
    return "FINITE_GEOMETRY_SYNTHETIC_PASS"

def self_test():
    assert classify(True,0,0,0,0,False)=="NO_JOINT_OBSERVABLE_CASE_FOUND_AT_MAX_RESOLUTION"
    assert classify(True,3,0,0,0,True)=="FINITE_GEOMETRY_SYNTHETIC_PASS_DELTAT_UNCERTAINTY_QUALIFIED"
    assert classify(True,3,1,0,0,False)=="FINITE_GEOMETRY_SYNTHETIC_PRECISION_HOLD"
    assert classify(True,3,0,0,1,False)=="FINITE_GEOMETRY_SITE_METADATA_STRESS_HOLD"
    assert abs(DISTANCES_KM[0]-12756.274)<1e-9
    print("v094x finite-geometry/synthetic self-test PASS")
    return 0

def verify_existing_final():
    if not RESULT.is_dir():return False
    man=RESULT/"v094x_output_manifest.sha256"
    rep=RESULT/"v094x_full_population_finite_geometry_synthetic_validation.json"
    csvp=RESULT/"v094x_pair_geometry_synthetic_validation.csv"
    if not (man.is_file() and rep.is_file() and csvp.is_file()):
        raise SystemExit("Existing v094x final directory incomplete; preserve and inspect manually")
    manifest_check(man,RESULT)
    q=json.loads(rep.read_text(encoding="utf-8"))
    if q.get("status")!="COMPLETE" or int(q.get("output_rows",-1))!=8807:
        raise SystemExit("Existing v094x final report replay HOLD")
    print("Existing completed v094x result manifest-validated; no recomputation.")
    return True

def load_foundation(repo,m):
    # Parent artifacts.
    for p in (V094T_CSV,V094T_REPORT,V094T_MANIFEST,V094W_SITE,V094W_REPORT,V094W_MANIFEST,V094S_PROV):
        if not p.is_file():raise SystemExit(f"Missing parent artifact: {p}")
    manifest_check(V094T_MANIFEST,V094T);manifest_check(V094W_MANIFEST,V094W)
    tr=json.loads(V094T_REPORT.read_text(encoding="utf-8"))
    wr=json.loads(V094W_REPORT.read_text(encoding="utf-8"))
    if tr.get("status")!="COMPLETE" or int(tr.get("distinct_site_temporal_pairs_le15min",-1))!=13177:
        raise SystemExit("v094t parent report HOLD")
    if wr.get("outcome")!="READY_TO_FREEZE_NOMINAL_FINITE_DISTANCE_GEOMETRY":
        raise SystemExit("v094w readiness HOLD")
    if int(wr["population"]["overlap_pairs"])!=8807 or int(wr["population"]["positive_duration_overlap_intervals"])!=8925:
        raise SystemExit("v094w population replay HOLD")

    prov=json.loads(V094S_PROV.read_text(encoding="utf-8"))
    for k,r in prov["inputs"].items():
        p=ROOT/r["path"]
        if not p.is_file() or sha(p)!=str(r["sha256"]).lower():
            raise SystemExit(f"Frozen v094s input mismatch: {k}")
    solution_path=ROOT/prov["inputs"]["solution_full"]["path"]

    # Site foundation generated by frozen v094w replay.
    sites={}
    for r in rows(V094W_SITE):
        site=str(r.get("site_name") or "").strip()
        lon=fnum(r.get("site_longitude"));lat=fnum(r.get("site_latitude"));elev=fnum(r.get("site_elevation_m"))
        if not site or None in (lon,lat,elev):raise SystemExit("v094w site-foundation structural HOLD")
        sites[site]={"site_name":site,"site_longitude":lon,"site_latitude":lat,"site_elevation":elev}
    if len(sites)!=10:raise SystemExit(f"v094w site count HOLD: {len(sites)}")

    # Reference bytes are frozen in Git.
    c01=repo/C01_REL;hist=repo/HIST_REL;month=repo/MONTH_REL
    if not c01.is_file() or sha(c01)!=C01_SHA:raise SystemExit("C01 hash HOLD")
    if not hist.is_file() or sha(hist)!=HIST_SHA:raise SystemExit("historic DeltaT hash HOLD")
    if not month.is_file() or sha(month)!=MONTH_SHA:raise SystemExit("monthly DeltaT hash HOLD")
    refs={"c01":m.parse_c01(c01),"hist":m.parse_hist_deltat(hist),"monthly":m.parse_month_deltat(month)}
    if refs["monthly"] is None:raise SystemExit("Monthly DeltaT parser HOLD")

    # Only polygons referenced by the OVERLAP population are retained.
    overlap=list(r for r in rows(V094T_CSV) if str(r.get("timing_bin") or "")=="OVERLAP")
    if len(overlap)!=8807:raise SystemExit(f"v094t OVERLAP count HOLD: {len(overlap)}")
    required_sids=set()
    for r in overlap:
        for k in ("solution_id_a","solution_id_b"):
            sid=inum(r.get(k))
            if sid is None:raise SystemExit(f"Missing solution ID: {r.get('pair_id')}")
            required_sids.add(sid)
    polys={}
    for r in rows(solution_path):
        sid=inum(r.get("solution_id"))
        if sid in required_sids:
            p=m.parse_poly(r.get("stc_polygon"))
            if p is not None:polys[sid]=p
    missing=required_sids-set(polys)
    if missing:raise SystemExit(f"Solution polygon coverage HOLD: {len(missing)} missing")
    return sites,refs,polys,overlap

def parse_intervals(r):
    try:q=json.loads(str(r.get("fragment_overlap_intervals_json") or "[]"))
    except:return []
    out=[]
    for x in q:
        a=parse_dt(x.get("start_utc"));b=parse_dt(x.get("end_utc"));dur=fnum(x.get("duration_seconds"))
        if a is None or b is None or b<=a or dur is None or dur<=0:return []
        if abs((b-a).total_seconds()-dur)>0.001:return []
        out.append((a,b))
    return out

def process_pair(m,idx,r,sites,refs,polys):
    import numpy as np
    siteA=sites.get(str(r.get("site_a") or "").strip())
    siteB=sites.get(str(r.get("site_b") or "").strip())
    if siteA is None or siteB is None:raise SystemExit(f"Site foundation HOLD at pair {r.get('pair_id')}")
    polyA=polys[inum(r.get("solution_id_a"))];polyB=polys[inum(r.get("solution_id_b"))]
    intervals=parse_intervals(r)
    if not intervals:raise SystemExit(f"Validated overlap interval replay HOLD at pair {r.get('pair_id')}")

    nominal_ok=True
    baseline_lengths=[];baseline_sweep=[];dtsources=set()
    for s,e in intervals:
        bases=[]
        for t in (s,s+(e-s)*.25,s+(e-s)*.5,s+(e-s)*.75,e):
            g=m.geometry_at(siteA,siteB,t,refs)
            if g is None:
                nominal_ok=False;continue
            A,B,base=g;bases.append(base);baseline_lengths.append(float(np.linalg.norm(base)))
            dtsources.add(str(A.get("delta_t_source") or ""))
        if len(bases)>=2:
            ref=bases[0]
            baseline_sweep.append(max((m.angle_arcsec(ref,b) or 0.0) for b in bases[1:]))

    bydist={str(D):Counter() for D in DISTANCES_KM}
    cases=withplace=noplace=placements=recovered=recovery_fail=ref_fail=height_fail=0
    max_level=0;observable_dist=set();monthly_qualified=("MONTHLY_NO_ERROR" in dtsources)
    grid_cache={}
    for s,e in intervals:
        for true_t in (s,s+(e-s)/2,e):
            g=m.geometry_at(siteA,siteB,true_t,refs)
            if g is None:
                nominal_ok=False;continue
            A,B,_=g
            if str(A.get("delta_t_source") or "")=="MONTHLY_NO_ERROR":monthly_qualified=True
            for D in DISTANCES_KM:
                key=str(D);cases+=1;bydist[key]["cases"]+=1
                cand,lev=find_case_candidates(m,polyA,polyB,A,B,D,grid_cache)
                max_level=max(max_level,lev)
                bydist[key][f"grid_level_{lev}_cases"]+=1
                if not cand:
                    noplace+=1;bydist[key]["no_case_found"]+=1
                    continue
                withplace+=1;bydist[key]["cases_with_placement"]+=1;observable_dist.add(D)
                for nA,nB in cand:
                    placements+=1;bydist[key]["placements"]+=1
                    rr=m.search_pair(siteA,siteB,intervals,refs,nA,nB)
                    ok=False
                    if rr["generator_min_xt"]<=m.GEN_ARCSEC and rr["final"] is not None and rr["final"][1] is not None:
                        _,det=rr["final"];sol_mid=float(np.linalg.norm(det["mid"]))
                        ok=(det["xt"]<=m.FINAL_ARCSEC and det["closure"]<=m.FINAL_ARCSEC and
                            det["tA"]>0 and det["tB"]>0 and sol_mid>=m.RE and abs(sol_mid-D)/D<=0.01)
                    if ok:
                        recovered+=1;bydist[key]["recovered"]+=1
                    else:
                        recovery_fail+=1;bydist[key]["recovery_failures"]+=1
                    us=m.reference_uncertainty_scores(siteA,siteB,true_t,refs,nA,nB)
                    if us:
                        if us["published_max_score_arcsec"] is not None and us["published_max_score_arcsec"]>m.FINAL_ARCSEC:
                            ref_fail+=1;bydist[key]["available_published_reference_gt2arcsec"]+=1
                        if us["height107m_max_score_arcsec"] is not None and us["height107m_max_score_arcsec"]>m.FINAL_ARCSEC:
                            height_fail+=1;bydist[key]["height107m_gt2arcsec"]+=1

    status=classify(nominal_ok,placements,recovery_fail,ref_fail,height_fail,monthly_qualified)
    return {
        "pair_index":idx,
        "pair_id":str(r.get("pair_id") or ""),
        "parent_signature_sha256":parent_signature(r),
        "plate_a":r.get("plate_a",""),"plate_b":r.get("plate_b",""),
        "solution_id_a":r.get("solution_id_a",""),"solution_id_b":r.get("solution_id_b",""),
        "site_a":r.get("site_a",""),"site_b":r.get("site_b",""),
        "legacy_infinity_geometry_status":r.get("legacy_infinity_geometry_status",""),
        "old_common_positive_infinity_footprint":r.get("old_common_positive_infinity_footprint",""),
        "overlap_interval_count":len(intervals),
        "baseline_length_km_min":min(baseline_lengths) if baseline_lengths else "",
        "baseline_length_km_max":max(baseline_lengths) if baseline_lengths else "",
        "baseline_sweep_max_arcsec":max(baseline_sweep) if baseline_sweep else "",
        "deltat_sources":";".join(sorted(x for x in dtsources if x)),
        "deltat_uncertainty_qualification":("DELTAT_UNCERTAINTY_UNAVAILABLE" if monthly_qualified else "HISTORIC_DELTAT_ERROR_AVAILABLE"),
        "time_distance_cases":cases,
        "cases_with_observable_placement":withplace,
        "cases_without_observable_placement":noplace,
        "max_grid_level_used":max_level,
        "placements":placements,
        "recovered":recovered,
        "recovery_failures":recovery_fail,
        "available_published_reference_gt2arcsec":ref_fail,
        "height107m_gt2arcsec":height_fail,
        "observable_distance_grid_values_km_json":json.dumps(sorted(observable_dist),separators=(",",":")),
        "by_distance_json":json.dumps({k:dict(v) for k,v in bydist.items()},sort_keys=True,separators=(",",":")),
        "status":status,
    }

def validate_chunk(path,expected):
    if not Path(path).is_file():return None
    try:data=list(rows(path))
    except:return None
    if len(data)!=len(expected):return None
    byid={str(r.get("pair_id") or ""):r for r in data}
    if len(byid)!=len(data):return None
    for idx,r in expected:
        pid=str(r.get("pair_id") or "")
        q=byid.get(pid)
        if q is None or str(q.get("parent_signature_sha256") or "")!=parent_signature(r):
            return None
        if inum(q.get("pair_index"))!=idx:return None
    return data

def write_chunk_atomic(path,data):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_name(path.name+".__tmp__."+str(os.getpid()))
    with tmp.open("w",encoding="utf-8",newline="") as f:
        w=csv.DictWriter(f,fieldnames=OUTPUT_FIELDS);w.writeheader();w.writerows(data)
    os.replace(tmp,path)

def preserve_invalid(path):
    p=Path(path)
    if p.exists():
        stamp=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
        p.rename(p.with_name(p.name+".invalid."+stamp))

def run(repo_root):
    if not CONTRACT.is_file() or sha(CONTRACT)!=EXPECTED_CONTRACT_SHA:raise SystemExit("v094x contract SHA HOLD")
    if verify_existing_final():return 0
    repo=Path(repo_root).resolve();m=load_parent_geometry(repo)
    sites,refs,polys,overlap=load_foundation(repo,m)

    # Exact population/signature preflight before any geometry.
    ids=set();interval_count=0
    for r in overlap:
        pid=str(r.get("pair_id") or "")
        if not pid or pid in ids:raise SystemExit("v094x pair-key preflight HOLD")
        ids.add(pid);ivs=parse_intervals(r)
        if not ivs:raise SystemExit(f"v094x interval preflight HOLD: {pid}")
        interval_count+=len(ivs)
    if len(ids)!=8807 or interval_count!=8925:raise SystemExit(f"v094x population preflight HOLD: {len(ids)} / {interval_count}")
    print("v094x FULL-POPULATION GEOMETRY PREFLIGHT PASS")
    print(f"OVERLAP pairs / positive intervals: {len(ids):,} / {interval_count:,}")
    print(f"Sites / required solution polygons: {len(sites)} / {len(polys):,}")
    print("No source catalogue or candidate identity access.")

    CHUNKS.mkdir(parents=True,exist_ok=True)
    all_rows=[]
    total_chunks=(len(overlap)+CHUNK_SIZE-1)//CHUNK_SIZE
    for ci,start in enumerate(range(0,len(overlap),CHUNK_SIZE),1):
        part=overlap[start:start+CHUNK_SIZE]
        expected=[(start+j+1,r) for j,r in enumerate(part)]
        cp=CHUNKS/f"chunk_{ci:04d}_{start+1:05d}_{start+len(part):05d}.csv"
        cached=validate_chunk(cp,expected)
        if cached is not None:
            all_rows.extend(cached)
            log(f"v094x chunk {ci}/{total_chunks} reuse PASS; pairs {start+1}-{start+len(part)}")
            continue
        if cp.exists():preserve_invalid(cp)
        out=[]
        for j,r in expected:
            out.append(process_pair(m,j,r,sites,refs,polys))
            if j%5==0 or j==len(overlap):
                log(f"v094x geometry/synthetic pair {j:,}/{len(overlap):,}")
        write_chunk_atomic(cp,out)
        check=validate_chunk(cp,expected)
        if check is None:raise SystemExit(f"Chunk post-write replay HOLD: {cp}")
        all_rows.extend(check)
        log(f"v094x chunk {ci}/{total_chunks} COMPLETE; pairs {start+1}-{start+len(part)}")

    # Final exact key/signature replay.
    if len(all_rows)!=8807:raise SystemExit(f"Final row count HOLD: {len(all_rows)}")
    byid={str(r.get("pair_id") or ""):r for r in all_rows}
    if len(byid)!=8807:raise SystemExit("Final unique pair-key HOLD")
    sig_mismatch=0
    for idx,r in enumerate(overlap,1):
        q=byid.get(str(r.get("pair_id") or ""))
        if q is None or str(q.get("parent_signature_sha256") or "")!=parent_signature(r) or inum(q.get("pair_index"))!=idx:
            sig_mismatch+=1
    if sig_mismatch:raise SystemExit(f"Final parent signature replay HOLD: {sig_mismatch}")

    status_counts=Counter();legacy=defaultdict(Counter);dtagg=defaultdict(Counter)
    totals=Counter();monthly_pairs=0
    for q in all_rows:
        st=q["status"];status_counts[st]+=1
        legacy[str(q.get("legacy_infinity_geometry_status") or "")][st]+=1
        if str(q.get("deltat_uncertainty_qualification"))=="DELTAT_UNCERTAINTY_UNAVAILABLE":monthly_pairs+=1
        for k in ("time_distance_cases","cases_with_observable_placement","cases_without_observable_placement",
                  "placements","recovered","recovery_failures","available_published_reference_gt2arcsec","height107m_gt2arcsec"):
            totals[k]+=inum(q.get(k)) or 0
        try:bd=json.loads(q.get("by_distance_json") or "{}")
        except:bd={}
        for d,c in bd.items():
            for k,v in c.items():dtagg[d][k]+=int(v)

    if monthly_pairs!=12:raise SystemExit(f"Monthly-DeltaT pair replay HOLD: {monthly_pairs} != 12")

    if RESULT.exists():raise SystemExit(f"Final result directory appeared before publication: {RESULT}")
    stage=RESULT.parent/(RESULT.name+".__staging__."+datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")+"."+str(os.getpid()))
    stage.mkdir(parents=True,exist_ok=False)
    csvp=stage/"v094x_pair_geometry_synthetic_validation.csv"
    all_rows_sorted=sorted(all_rows,key=lambda q:int(q["pair_index"]))
    with csvp.open("w",encoding="utf-8",newline="") as f:
        w=csv.DictWriter(f,fieldnames=OUTPUT_FIELDS);w.writeheader();w.writerows(all_rows_sorted)
    # Re-read final staged CSV.
    reread=list(rows(csvp))
    if len(reread)!=8807 or len({r["pair_id"] for r in reread})!=8807:raise SystemExit("Staged final CSV key replay HOLD")
    for idx,r in enumerate(overlap,1):
        q=reread[idx-1]
        if q["pair_id"]!=str(r.get("pair_id") or "") or q["parent_signature_sha256"]!=parent_signature(r):
            raise SystemExit(f"Staged final CSV signature/order HOLD at {idx}")

    report={
        "status":"COMPLETE",
        "analysis_kind":"v094x_source_free_full_population_finite_geometry_synthetic_validation",
        "contract_sha256":EXPECTED_CONTRACT_SHA,
        "output_rows":8807,"unique_pair_ids":8807,"parent_signature_mismatches":0,
        "positive_duration_overlap_intervals":8925,
        "distance_grid_km":list(DISTANCES_KM),
        "grid_levels":list(GRID_LEVELS),
        "status_counts":dict(status_counts),
        "totals":dict(totals),
        "by_distance_km":{k:dict(v) for k,v in dtagg.items()},
        "by_legacy_infinity_geometry_status":{k:dict(v) for k,v in legacy.items()},
        "monthly_deltat_uncertainty_qualified_pairs":monthly_pairs,
        "no_case_interpretation":"NO_JOINT_OBSERVABLE_CASE_FOUND_AT_MAX_RESOLUTION is not proof of physical impossibility.",
        "site_metadata_qualification":{
            "height_stress_envelope_m":107.0,
            "horizontal_datum_accuracy":"UNDOCUMENTED_BY_APPLAUSE_SCHEMA"
        },
        "guards":{"network":0,"source_catalog_reads":0,"candidate_identity_inspection":0,"private_candidate_map_reads":0,
                  "pixels":0,"fits":0,"registration":0,"real_source_pairing":0,"threshold_retuning":0},
        "next_matcher_allowed":False,
        "next_stage":"Interpret this full-population grid/recovery validation before freezing continuous-distance admissibility or any source matcher."
    }
    rp=stage/"v094x_full_population_finite_geometry_synthetic_validation.json"
    rp.write_text(json.dumps(report,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    mp=stage/"v094x_output_manifest.sha256"
    mp.write_text(f"{sha(csvp)}  {csvp.name}\n{sha(rp)}  {rp.name}\n",encoding="utf-8")
    os.replace(stage,RESULT)

    print("\n"+"="*112)
    print("v094x FULL-POPULATION FINITE-DISTANCE GRID GEOMETRY + SYNTHETIC VALIDATION COMPLETE")
    print("="*112)
    print(f"Output rows / unique / signature mismatches:  8,807 / 8,807 / 0")
    print(f"Positive-duration overlap intervals:          8,925")
    print(f"Monthly-DeltaT uncertainty-qualified pairs:   {monthly_pairs}")
    print("Opportunity status counts:")
    for k,v in sorted(status_counts.items()):print(f"  {k:62s} {v:,}")
    print(f"Synthetic placements / recovered / failures: {totals['placements']:,} / {totals['recovered']:,} / {totals['recovery_failures']:,}")
    print(f"Available published-reference >2arcsec:       {totals['available_published_reference_gt2arcsec']:,}")
    print(f"+/-107m height-stress >2arcsec:               {totals['height107m_gt2arcsec']:,}")
    for d in DISTANCES_KM:
        q=dtagg[str(d)]
        print(f"Distance {d:.3f} km: cases={q['cases']:,}; with-placement={q['cases_with_placement']:,}; no-case={q['no_case_found']:,}; recovered={q['recovered']:,}")
    print("Source catalogues / candidate identities / network: 0 / 0 / 0")
    print("STOP: interpret before continuous-distance admissibility or source matching.")
    return 0

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--self-test",action="store_true")
    ap.add_argument("--repo-root")
    a=ap.parse_args()
    if a.self_test:return self_test()
    if not a.repo_root:raise SystemExit("--repo-root required")
    return run(a.repo_root)

if __name__=="__main__":raise SystemExit(main())
