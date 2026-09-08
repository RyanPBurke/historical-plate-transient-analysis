#!/usr/bin/env python3
from __future__ import annotations
from pathlib import Path
from collections import Counter,defaultdict
from datetime import datetime
import argparse,csv,hashlib,importlib.util,json,math
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
PARENT_RUNNER=ROOT/"tools"/"run_applause_dr4_historical_geometry_validation_v094r3c.py"
EXPECTED_PARENT_RUNNER_SHA="75751da3c21c06b7900688d2d4848bcda93bc7cc0c2a49fefeb583fc57c30dd8"
CONTRACT=ROOT/"research"/"prospective_freezes"/"v094r3d_observable_coverage_audit_contract.json"
EXPECTED_CONTRACT_SHA="62dcaf582b35e4f115a0d95b9be450cb09cfc7787b9b9dbc90819731ac35a07c"
R3C_DIR=ROOT/"results"/"applause_dr4_historical_geometry_validation_v094r3c"
RESULT=ROOT/"results"/"applause_dr4_observable_coverage_audit_v094r3d"
GRID_LEVELS=(9,17,33,65)
MAX_PER_CASE=3

def sha(p):
    h=hashlib.sha256()
    with Path(p).open("rb") as f:
        for b in iter(lambda:f.read(8*1024*1024),b""):h.update(b)
    return h.hexdigest()

def rows(p):
    with Path(p).open("r",encoding="utf-8-sig",newline="") as f:yield from csv.DictReader(f)

def log(s):print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {s}",flush=True)

def load_parent():
    if not PARENT_RUNNER.is_file() or sha(PARENT_RUNNER)!=EXPECTED_PARENT_RUNNER_SHA:
        raise SystemExit("Frozen r3c parent runner SHA mismatch")
    spec=importlib.util.spec_from_file_location("r3c_parent",PARENT_RUNNER)
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
    return m

def tangent_grid(m,poly,n):
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
    r=np.asarray(r,float);n=np.asarray(n,float);n=n/np.linalg.norm(n)
    rn=float(r@n);disc=rn*rn + D*D - float(r@r)
    if disc<=0:return None
    t=-rn+math.sqrt(disc)
    if t<=0:return None
    return r+t*n

def unique_pair(m,seen,nA,nB,tol_arcsec=0.01):
    # Deduplicate deterministically using rounded RA/Dec at much finer than any science threshold.
    raA,deA=m.radec(nA);raB,deB=m.radec(nB)
    key=(round(raA,8),round(deA,8),round(raB,8),round(deB,8))
    if key in seen:return False
    seen.add(key);return True

def find_case_candidates(m,pa,pb,polyA,polyB,A,B,D,grid_cache,keyA,keyB):
    found=[];seen=set();used_level=None
    for N in GRID_LEVELS:
        for side in ("A","B"):
            key=(keyA if side=="A" else keyB,N)
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
                if m.angle_arcsec(nA,nB)<2.0:continue
                if unique_pair(m,seen,nA,nB):
                    found.append((nA,nB))
        if len(found)>=MAX_PER_CASE:
            used_level=N;break
    if used_level is None:used_level=GRID_LEVELS[-1]
    if not found:return [],used_level
    # Parent grid ordering is central-first; here rank by combined angular offset from plate centers.
    cA=m.xyz(*m.center([polyA]));cB=m.xyz(*m.center([polyB]))
    ranked=[]
    for nA,nB in found:
        sc=(m.angle_arcsec(cA,nA) or 0)+(m.angle_arcsec(cB,nB) or 0)
        ranked.append((sc,nA,nB))
    ranked.sort(key=lambda z:z[0])
    if len(ranked)<=MAX_PER_CASE:
        chosen=ranked
    else:
        idx=sorted(set((0,len(ranked)//2,len(ranked)-1)))
        chosen=[ranked[i] for i in idx]
    return [(a,b) for _,a,b in chosen],used_level

def self_test():
    # Pure geometry test of directed ray->sphere->other-site construction.
    rA=np.array([6378.137,0,0.]);rB=np.array([6378.137,400.,0.]);D=100000.
    n=np.array([0.7,0.7,0.1]);n/=np.linalg.norm(n)
    R=ray_sphere(rA,n,D);assert R is not None
    assert abs(np.linalg.norm(R)-D)<1e-6
    nB=R-rB;nB/=np.linalg.norm(nB)
    assert np.isfinite(nB).all() and abs(np.linalg.norm(nB)-1)<1e-12
    print("v094r3d directed observable-placement self-test PASS")
    return 0

def run():
    if not CONTRACT.is_file() or sha(CONTRACT)!=EXPECTED_CONTRACT_SHA:
        raise SystemExit("r3d contract SHA mismatch")
    m=load_parent()
    # Verify the frozen parent geometry/reference stack before using it.
    manifest=m.verify_freeze()
    plates,refs,polys,plan=m.load_inputs(manifest)

    rjson=R3C_DIR/"applause_dr4_historical_geometry_validation_v094r3c.json"
    rcsv=R3C_DIR/"opportunity_geometry_validation_v094r3c.csv"
    rman=R3C_DIR/"v094r3c_output_manifest.sha256"
    for p in (rjson,rcsv,rman):
        if not p.is_file():raise SystemExit(f"Missing completed r3c result: {p}")
    rep=json.loads(rjson.read_text(encoding="utf-8"))
    if rep.get("status")!="COMPLETE":raise SystemExit("r3c result not COMPLETE")
    if rep["synthetic_totals"].get("synthetic_observable")!=rep["synthetic_totals"].get("synthetic_recovered"):
        raise SystemExit("r3c aggregate recovery premise changed")

    detail=list(rows(rcsv))
    targets=[r for r in detail if r["classification"]=="GEOMETRY_UNRESOLVED_PRECISION" and int(r["synthetic_observable"])==0]
    if len(targets)!=621:raise SystemExit(f"r3d target count HOLD: {len(targets)} != 621")
    target_idx={int(r["opportunity_index"]) for r in targets}
    overlap=[r for r in plan if str(r.get("timing_bin"))=="OVERLAP"]
    if len(overlap)!=1081:raise SystemExit("Parent overlap count HOLD")

    grid_cache={}
    outrows=[];agg=Counter();bydist=defaultdict(Counter);levels=Counter()
    for oi,r in enumerate(overlap,1):
        if oi not in target_idx:continue
        pa=plates[m.inum(r["plate_a"])];pb=plates[m.inum(r["plate_b"])]
        sidA=m.inum(r["solution_id_a"]);sidB=m.inum(r["solution_id_b"])
        polyA=polys[sidA];polyB=polys[sidB]
        try:qivs=json.loads(r.get("fragment_overlap_intervals_json") or "[]")
        except:qivs=[]
        intervals=[]
        for q in qivs:
            s,e=m.parse_dt(q.get("start_utc")),m.parse_dt(q.get("end_utc"))
            if s and e and e>s:intervals.append((s,e))

        cases=found_cases=placements=recovered=pubfail=heightfail=0
        max_level=0
        for s,e in intervals:
            for true_t in (s,s+(e-s)/2,e):
                g=m.geometry_at(pa,pb,true_t,refs)
                if g is None:continue
                A,B,_=g
                for D in m.DISTANCES_KM:
                    cases+=1;bydist[D]["cases"]+=1
                    cand,lev=find_case_candidates(m,pa,pb,polyA,polyB,A,B,D,grid_cache,sidA,sidB)
                    max_level=max(max_level,lev);levels[lev]+=1
                    if not cand:
                        bydist[D]["no_case_found"]+=1
                        continue
                    found_cases+=1;bydist[D]["cases_with_placement"]+=1
                    for nA,nB in cand:
                        placements+=1;bydist[D]["placements"]+=1
                        rr=m.search_pair(pa,pb,intervals,refs,nA,nB)
                        ok=False
                        if rr["generator_min_xt"]<=m.GEN_ARCSEC and rr["final"] is not None and rr["final"][1] is not None:
                            _,det=rr["final"];sol_mid=np.linalg.norm(det["mid"])
                            ok=(det["xt"]<=m.FINAL_ARCSEC and det["closure"]<=m.FINAL_ARCSEC and
                                det["tA"]>0 and det["tB"]>0 and sol_mid>=m.RE and abs(sol_mid-D)/D<=0.01)
                        if ok:
                            recovered+=1;bydist[D]["recovered"]+=1
                        else:
                            bydist[D]["recovery_fail"]+=1
                        us=m.reference_uncertainty_scores(pa,pb,true_t,refs,nA,nB)
                        if us:
                            if us["published_max_score_arcsec"] is not None and us["published_max_score_arcsec"]>m.FINAL_ARCSEC:
                                pubfail+=1;bydist[D]["published_reference_gt2"]+=1
                            if us["height107m_max_score_arcsec"] is not None and us["height107m_max_score_arcsec"]>m.FINAL_ARCSEC:
                                heightfail+=1;bydist[D]["height107m_gt2"]+=1

        if found_cases==0:
            cls="AUDIT_NO_JOINT_OBSERVABLE_CASE_FOUND_AT_MAX_RESOLUTION"
        elif recovered<placements or pubfail>0:
            cls="AUDIT_RECOVERY_OR_REFERENCE_HOLD"
        elif heightfail>0:
            cls="AUDIT_SITE_METADATA_HOLD"
        else:
            cls="AUDIT_OBSERVABLE_RECOVERY_PASS"
        agg[cls]+=1
        agg["cases"]+=cases;agg["found_cases"]+=found_cases;agg["placements"]+=placements
        agg["recovered"]+=recovered;agg["pubfail"]+=pubfail;agg["heightfail"]+=heightfail
        outrows.append({
          "opportunity_index":oi,"site_pair":r.get("site_pair",""),"epoch_label":r.get("epoch_label",""),
          "audit_classification":cls,"time_distance_cases":cases,"cases_with_observable_placement":found_cases,
          "placements_tested":placements,"placements_recovered":recovered,
          "published_reference_gt2arcsec":pubfail,"height107m_gt2arcsec":heightfail,
          "max_grid_resolution_reached":max_level
        })
        if len(outrows)%50==0:log(f"v094r3d observable-coverage audit: {len(outrows)}/621")

    RESULT.mkdir(parents=True,exist_ok=True)
    op=RESULT/"opportunity_observable_coverage_audit_v094r3d.csv"
    with op.open("w",encoding="utf-8",newline="") as f:
        w=csv.DictWriter(f,fieldnames=list(outrows[0].keys()));w.writeheader();w.writerows(outrows)
    report={
      "status":"COMPLETE",
      "contract_sha256":EXPECTED_CONTRACT_SHA,
      "parent_commit":"e4d1f9918ba498c8432a57809c6d16669c5f93da",
      "target_opportunities":len(outrows),
      "classification_counts":{k:v for k,v in agg.items() if k.startswith("AUDIT_")},
      "totals":{k:v for k,v in agg.items() if not k.startswith("AUDIT_")},
      "by_distance_km":{str(k):dict(v) for k,v in bydist.items()},
      "grid_level_use":{str(k):v for k,v in sorted(levels.items())},
      "interpretation_boundary":(
        "Failure to find a placement at 65x65 in both A->B and B->A is a bounded search result, "
        "not proof that no physically observable finite-distance point exists."
      ),
      "guards":{"network":0,"real_source_pairing":0,"candidate_identity_inspection":0,
                "private_candidate_map":0,"pixels":0,"registration":0},
      "next_matcher_allowed":False
    }
    jp=RESULT/"applause_dr4_observable_coverage_audit_v094r3d.json"
    jp.write_text(json.dumps(report,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    (RESULT/"v094r3d_output_manifest.sha256").write_text(
      f"{sha(op)}  {op.name}\n{sha(jp)}  {jp.name}\n",encoding="utf-8")

    print("\n"+"="*108)
    print("v094r3d OBSERVABLE SYNTHETIC COVERAGE COMPLETION AUDIT COMPLETE")
    print("="*108)
    for k in ("AUDIT_OBSERVABLE_RECOVERY_PASS","AUDIT_SITE_METADATA_HOLD",
              "AUDIT_RECOVERY_OR_REFERENCE_HOLD","AUDIT_NO_JOINT_OBSERVABLE_CASE_FOUND_AT_MAX_RESOLUTION"):
        print(f"{k:58s} {agg.get(k,0)}")
    print(f"Time-distance cases / with placement: {agg['cases']} / {agg['found_cases']}")
    print(f"Placements tested / recovered:        {agg['placements']} / {agg['recovered']}")
    print(f"Published-reference >2arcsec:         {agg['pubfail']}")
    print(f"±107m height-envelope >2arcsec:       {agg['heightfail']}")
    print("Candidate identities inspected:       0")
    print("Network / real source pairing:        0 / 0")
    print("NEW MATCHER: HOLD — interpret r3d coverage audit first.")
    return 0

def main():
    ap=argparse.ArgumentParser();ap.add_argument("--self-test",action="store_true");a=ap.parse_args()
    return self_test() if a.self_test else run()

if __name__=="__main__":raise SystemExit(main())
