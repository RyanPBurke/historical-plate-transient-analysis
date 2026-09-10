#!/usr/bin/env python3
from __future__ import annotations
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor, wait, FIRST_COMPLETED
from collections import Counter
from datetime import datetime, timezone
import argparse, csv, hashlib, importlib.util, json, math, os, signal, sys, tempfile, traceback, re, subprocess
import numpy as np

EXPECTED_V094X_SHA="f75a866e63dfedd24a677acd925d8e4e2a53e34d99e582596e0adb9a3db5e7cc"

EXPECTED_PAIRS=8807
EXPECTED_FRAGMENTS=8925
MIN_CELL_WIDTH_S=0.0625
MAX_DEPTH=18
MAX_CELLS_PER_FRAGMENT=16383
MOTION_BOUND_KM_S=0.60
REFERENCE_SWITCH_ALLOWANCE_KM=0.03
CHUNK_PAIRS=25
DEFAULT_WORKERS=8

PAIR_FIELDS=[
 "pair_index","pair_id","plate_a","plate_b","site_a","site_b","legacy_infinity_geometry_status",
 "overlap_fragment_count","pair_status","extent_status","witness_fragment_index","witness_time_utc",
 "witness_distance_km","witness_disparity_arcsec","witness_ge2arcsec",
 "deltat_sources","deltat_uncertainty_qualification",
 "published_reference_max_score_arcsec","height107m_max_score_arcsec",
 "cells_processed","cells_certified_empty","cells_unresolved","exact_time_probes",
 "negative_certificate_digest_sha256","input_hold_reason"
]
FRAG_FIELDS=[
 "pair_index","pair_id","fragment_index","start_utc","end_utc","duration_seconds",
 "fragment_status","extent_status","witness_time_utc","witness_distance_km",
 "witness_disparity_arcsec","witness_ge2arcsec","fixed_time_component_intervals_json",
 "deltat_source","deltat_uncertainty_qualification",
 "published_reference_max_score_arcsec","height107m_max_score_arcsec",
 "cells_processed","cells_certified_empty","cells_unresolved","max_depth_reached","exact_time_probes",
 "negative_certificate_digest_sha256","unresolved_reason","input_hold_reason"
]
WIT_FIELDS=[
 "pair_index","pair_id","fragment_index","time_utc","component_a","component_b",
 "x_km","y_km","z_km","distance_km","topocentric_ra_a_deg","topocentric_dec_a_deg",
 "topocentric_ra_b_deg","topocentric_dec_b_deg","altitude_a_deg","altitude_b_deg",
 "disparity_arcsec","ge2arcsec","interval_min_distance_km","interval_max_distance_km",
 "interval_max_unbounded","interval_upper_extent_state","interval_lower_closed","interval_upper_closed",
 "deltat_source","deltat_uncertainty_qualification",
 "published_reference_max_score_arcsec","height107m_max_score_arcsec"
]

_W=None

def sha(p):
    h=hashlib.sha256()
    with Path(p).open("rb") as f:
        for b in iter(lambda:f.read(8*1024*1024),b""):h.update(b)
    return h.hexdigest()

def atomic_json(path,obj):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    fd,tmp=tempfile.mkstemp(prefix=path.name+".",suffix=".tmp",dir=str(path.parent))
    try:
        with os.fdopen(fd,"w",encoding="utf-8",newline="\n") as q:
            json.dump(obj,q,indent=2,sort_keys=True);q.write("\n");q.flush();os.fsync(q.fileno())
        os.replace(tmp,path)
    finally:
        try:
            if os.path.exists(tmp):os.unlink(tmp)
        except:pass

def canonical_sha(obj):
    return hashlib.sha256(json.dumps(obj,sort_keys=True,separators=(",",":"),ensure_ascii=True).encode()).hexdigest()


def release_manifest_map(here):
    p=Path(here)/"release_manifest.sha256"
    if not p.is_file():raise SystemExit("RELEASE_MANIFEST_HOLD: missing release_manifest.sha256")
    m={}
    for line in p.read_text(encoding="utf-8").splitlines():
        q=line.strip().split(None,1)
        if len(q)!=2:continue
        m[q[1].strip()]=q[0].lower()
    return p,m

def release_identity(here):
    p,m=release_manifest_map(here)
    required=["v094y_finite_geometry_core_rc4.py","v094y_production_rc4_contract.json",
              "run_v094y_production_rc4.py","run_v094y_rc4_release_regression.py"]
    for name in required:
        f=Path(here)/name
        if name not in m or not f.is_file() or sha(f)!=m[name]:
            raise SystemExit(f"RELEASE_MANIFEST_HOLD: {name}")
    return {"release_manifest_sha256":sha(p),"core_sha256":m[required[0]],"contract_sha256":m[required[1]],
            "production_runner_sha256":m[required[2]],"regression_runner_sha256":m[required[3]]}

def foundation_provenance(project,repo,vx):
    prov=json.loads(vx.V094S_PROV.read_text(encoding="utf-8"))
    solution=Path(project)/prov["inputs"]["solution_full"]["path"]
    files={
      "v094x_science_runner":Path(project)/"tools"/"run_v094x_source_free_full_population_finite_geometry_synthetic_validation.py",
      "geometry_execution_module":Path(repo)/vx.GEOM_REL,
      "v094t_csv":vx.V094T_CSV,"v094t_report":vx.V094T_REPORT,"v094t_manifest":vx.V094T_MANIFEST,
      "v094w_site":vx.V094W_SITE,"v094w_report":vx.V094W_REPORT,"v094w_manifest":vx.V094W_MANIFEST,
      "v094s_provenance":vx.V094S_PROV,"solution_full":solution,
      "c01":Path(repo)/vx.C01_REL,"historic_deltat":Path(repo)/vx.HIST_REL,"monthly_deltat":Path(repo)/vx.MONTH_REL
    }
    q={k:{"path":str(v),"sha256":sha(v)} for k,v in files.items()}
    return q,canonical_sha(q)

def load_module(path,name):
    sp=importlib.util.spec_from_file_location(name,path)
    if sp is None or sp.loader is None:raise RuntimeError(f"cannot load {path}")
    m=importlib.util.module_from_spec(sp);sys.modules[name]=m;sp.loader.exec_module(m);return m

def manifest_check(manifest,base):
    for line in Path(manifest).read_text(encoding="utf-8").splitlines():
        q=line.strip().split(None,1)
        if len(q)!=2:continue
        digest,name=q[0].lower(),q[1].strip()
        p=Path(base)/name
        if not p.is_file() or sha(p)!=digest:raise SystemExit(f"manifest HOLD: {name}")

def iso(t):return t.astimezone(timezone.utc).isoformat()

def check_gates(project,repo,vx,ident,provsha):
    reg=Path(project)/"work"/"v094y_rc4_release_regression"/"summary.json"
    cpm=Path(project)/"work"/"v094y_rc4_release_regression"/"checkpoint_manifest.json"
    surv=Path(project)/"work"/"v094y_continuous_time_budget_prototype_r1"/"survey.json"
    if not reg.is_file() or not cpm.is_file():raise SystemExit("PRECHECK_HOLD: RC4 release-bound regression has not completed")
    r=json.loads(reg.read_text(encoding="utf-8"))
    wants={"status":"RC4_RELEASE_REGRESSION_PASS","positive_pairs_replayed":1200,
           "placements_reconstructed_and_contained":29147,"legacy_nonpositive_finite_positive_pairs_passed":122,
           "legacy_tangent_unresolved_structural_pairs_passed":30,"checkpoint_chunks":120,"failures":0}
    for k,v in wants.items():
        if r.get(k)!=v:raise SystemExit(f"PRECHECK_HOLD RC4 regression {k}={r.get(k)!r}")
    if r.get("release_identity")!=ident:raise SystemExit("PRECHECK_HOLD RC4 regression release identity mismatch")
    if r.get("input_provenance_sha256")!=provsha:raise SystemExit("PRECHECK_HOLD RC4 regression input provenance mismatch")
    cp_entries=json.loads(cpm.read_text(encoding="utf-8"))
    if len(cp_entries)!=120 or canonical_sha(cp_entries)!=r.get("checkpoint_manifest_sha256"):
        raise SystemExit("PRECHECK_HOLD RC4 checkpoint manifest mismatch")
    for x in cp_entries:
        p=Path(x["path"])
        if not p.is_file() or sha(p)!=x["sha256"]:raise SystemExit(f"PRECHECK_HOLD RC4 regression checkpoint byte mismatch: {p}")
    if not surv.is_file():raise SystemExit("PRECHECK_HOLD: missing time-budget survey")
    s=json.loads(surv.read_text(encoding="utf-8"))
    if s.get("status")!="PROTOTYPE_TIME_BUDGET_SURVEY_PASS":raise SystemExit("PRECHECK_HOLD survey status")
    st=s["synthetic_time_search_stress"]
    if int(st.get("false_negative_count",-1))!=0:raise SystemExit("PRECHECK_HOLD synthetic false negatives")
    p3=[x for x in st["profiles"] if x.get("name")=="P3"]
    if len(p3)!=1 or p3[0].get("min_cell_width_s")!=MIN_CELL_WIDTH_S or p3[0].get("max_depth")!=MAX_DEPTH or p3[0].get("max_cells")!=MAX_CELLS_PER_FRAGMENT:
        raise SystemExit("PRECHECK_HOLD P3 profile mismatch")
    unr=[x for x in st["fixture_rows"] if x.get("profile")=="P3" and str(x.get("status","")).startswith("UNRESOLVED")]
    if len(unr)!=12 or any(float(x.get("window_width_s",-1))!=0.01 for x in unr):raise SystemExit("PRECHECK_HOLD P3 unresolved replay")
    if float(s["motion_survey"]["observed_finite_difference_speed_km_s"]["max"])>=MOTION_BOUND_KM_S:raise SystemExit("PRECHECK_HOLD motion bound")
    if int(s["motion_survey"].get("sampled_reference_source_switch_site_fragments",-1))!=0:raise SystemExit("PRECHECK_HOLD reference switch")
    return {"rc4_release_regression_summary_sha256":sha(reg),"rc4_checkpoint_manifest_sha256":sha(cpm),"time_budget_survey_sha256":sha(surv)}

def load_foundation(project,repo,core_path):
    project=Path(project);repo=Path(repo);here=Path(__file__).resolve().parent
    ident=release_identity(here)
    vx_path=project/"tools"/"run_v094x_source_free_full_population_finite_geometry_synthetic_validation.py"
    if not vx_path.is_file() or sha(vx_path)!=EXPECTED_V094X_SHA:raise SystemExit("v094x science SHA HOLD")
    if sha(core_path)!=ident["core_sha256"]:raise SystemExit("v094y RC4 core release identity HOLD")
    vx=load_module(vx_path,"v094y_prod_v094x_parent")
    core=load_module(core_path,"v094y_prod_core")
    geom=vx.load_parent_geometry(repo);sites,refs,polys,overlap=vx.load_foundation(repo,geom)
    if len(overlap)!=EXPECTED_PAIRS:raise SystemExit(f"population HOLD {len(overlap)}")
    nfrag=sum(len(vx.parse_intervals(r)) for r in overlap)
    if nfrag!=EXPECTED_FRAGMENTS:raise SystemExit(f"fragment population HOLD {nfrag}")
    provenance,provsha=foundation_provenance(project,repo,vx)
    return vx,core,geom,sites,refs,polys,overlap,ident,provenance,provsha

def preflight_site_geometry(vx,core,geom,sites,refs,overlap):
    # Site metadata preconditions: nonnegative nominal height and transformed up vector consistency.
    import numpy as np
    for name,s in sites.items():
        if float(s["site_elevation"])<0:raise SystemExit(f"SITE_PREFLIGHT_HOLD negative height: {name}")
    # One deterministic real sample for every site used in the population.
    sample={}
    for r in overlap:
        ints=vx.parse_intervals(r)
        t=ints[0][0]+(ints[0][1]-ints[0][0])/2
        for side in ("a","b"):
            name=str(r[f"site_{side}"]).strip()
            if name in sample:continue
            st=geom.site_celestial(sites[name],t,refs)
            if st is None:raise SystemExit(f"SITE_PREFLIGHT_HOLD transform: {name}")
            lon,lat=geom.corrected_lonlat(name,sites[name]["site_longitude"],sites[name]["site_latitude"])
            expected=geom.up_ecef(lat,lon);actual=st["rc2t"]@st["up"]
            if float(np.linalg.norm(actual-expected))>2e-12:
                raise SystemExit(f"SITE_PREFLIGHT_HOLD up-vector mismatch: {name}")
            if core.ellipsoid_value(st["r"],st)<1-1e-10:
                raise SystemExit(f"SITE_PREFLIGHT_HOLD observer inside ellipsoid: {name}")
            sample[name]=True
    if len(sample)!=len(sites):raise SystemExit("SITE_PREFLIGHT_HOLD incomplete site replay")

def poly_components(core,poly):
    vv=[core.xyz(*q) for q in poly]
    tris=core.triangulate_spherical_polygon(vv)
    return [(i,core.convex_component_edge_normals(t)) for i,t in enumerate(tris)]

def exact_systems(core,components,state,label):
    out=[]
    for ci,edges in components:
        s=core.component_halfspaces(edges,state["r"],label)
        s=core.add_horizon(s,state["r"],state["up"],label)
        out.append((ci,s))
    return out

def witness_record(vx,core,geom,pair_idx,pid,frag_idx,t,ia,ib,res,A,B,siteA,siteB,refs):
    import numpy as np
    p=np.asarray(res.witness,float)
    nA=p-A["r"];nB=p-B["r"]
    la=float(np.linalg.norm(nA));lb=float(np.linalg.norm(nB))
    if la<=core.RAY_ZERO_KM or lb<=core.RAY_ZERO_KM:return None,"ZERO_LENGTH_OBSERVER_RAY"
    nA/=la;nB/=lb
    raA,deA=core.radec(nA);raB,deB=core.radec(nB)
    altA=math.degrees(math.asin(max(-1,min(1,float(A["up"]@nA)))))
    altB=math.degrees(math.asin(max(-1,min(1,float(B["up"]@nB)))))
    disp=geom.angle_arcsec(nA,nB)
    ok,why=core.verify_physical_witness(p,A,B)
    if not ok:return None,why
    us=geom.reference_uncertainty_scores(siteA,siteB,t,refs,nA,nB)
    pub=None if not us else us.get("published_max_score_arcsec")
    h107=None if not us else us.get("height107m_max_score_arcsec")
    src=str(A.get("delta_t_source") or "")
    qual="DELTAT_UNCERTAINTY_UNAVAILABLE_FROM_FROZEN_REFERENCE" if src=="MONTHLY_NO_ERROR" else "HISTORIC_DELTAT_ERROR_AVAILABLE"
    return {
      "pair_index":pair_idx,"pair_id":pid,"fragment_index":frag_idx,"time_utc":iso(t),
      "component_a":ia,"component_b":ib,
      "x_km":float(p[0]),"y_km":float(p[1]),"z_km":float(p[2]),"distance_km":float(np.linalg.norm(p)),
      "topocentric_ra_a_deg":raA,"topocentric_dec_a_deg":deA,
      "topocentric_ra_b_deg":raB,"topocentric_dec_b_deg":deB,
      "altitude_a_deg":altA,"altitude_b_deg":altB,
      "disparity_arcsec":disp,"ge2arcsec":bool(disp is not None and disp>=2.0),
      "interval_min_distance_km":res.min_distance_km,
      "interval_max_distance_km":res.max_distance_km,
      "interval_max_unbounded":res.max_unbounded,
      "interval_upper_extent_state":("VERIFIED_UNBOUNDED" if res.max_unbounded is True else ("VERIFIED_BOUNDED" if res.max_unbounded is False and res.max_distance_km is not None else "UNRESOLVED")),
      "interval_lower_closed":res.lower_closed,"interval_upper_closed":res.upper_closed,
      "deltat_source":src,"deltat_uncertainty_qualification":qual,
      "published_reference_max_score_arcsec":pub,"height107m_max_score_arcsec":h107
    },None

def fixed_time_probe(vx,core,geom,t,pair_idx,pid,frag_idx,siteA,siteB,refs,compA,compB):
    g=geom.geometry_at(siteA,siteB,t,refs)
    if g is None:return {"status":"INPUT_HOLD","reason":"GEOMETRY_REFERENCE_COVERAGE_HOLD"}
    A,B,_=g
    sa=exact_systems(core,compA,A,"A");sb=exact_systems(core,compB,B,"B")
    positives=[];unresolved=False
    for ia,a in sa:
        for ib,b in sb:
            sysx=core.combine(a,b)
            rr=core.fixed_time_component(sysx,A,B)
            if rr.status=="ADMISSIBLE_WITNESS":
                w,err=witness_record(vx,core,geom,pair_idx,pid,frag_idx,t,ia,ib,rr,A,B,siteA,siteB,refs)
                if w is not None:positives.append(w)
                else:unresolved=True
            elif rr.status!="CERTIFIED_NONADMISSIBLE":
                unresolved=True
    if positives:
        positives.sort(key=lambda w:(w["distance_km"],w["component_a"],w["component_b"]))
        return {"status":"WITNESS","witnesses":positives,"A":A,"B":B}
    return {"status":"UNRESOLVED" if unresolved else "NO_WITNESS","A":A,"B":B}

def cell_outer_cert(core,mid_state,compA,compB,half_s,crosses_switch):
    A,B=mid_state;rho=MOTION_BOUND_KM_S*half_s+(REFERENCE_SWITCH_ALLOWANCE_KM if crosses_switch else 0.0)
    cert_records=[]
    for ia,ea in compA:
        for ib,eb in compB:
            sysx=core.relaxed_footprint_system(ea,eb,A["r"],B["r"],rho,rho)
            state,_,_=core.feasible_lp(sysx)
            if state!="LP_INFEASIBLE":return None
            cert=core.exact_farkas_certificate(sysx)
            if cert is None:return None
            cert_records.append({"component_a":ia,"component_b":ib,"support_indices":cert["support_indices"]})
    return cert_records

def cert_digest(records):
    h=hashlib.sha256()
    for r in records:
        h.update(json.dumps(r,sort_keys=True,separators=(",",":")).encode());h.update(b"\n")
    return h.hexdigest()

def process_fragment(vx,core,geom,pair_idx,pid,frag_idx,s,e,siteA,siteB,refs,compA,compB):
    duration=(e-s).total_seconds()
    cache={};all_certs=[];unresolved_audit=[];cells=cert_cells=unresolved_cells=probes=0;maxdepth=0
    unresolved_reasons=Counter()

    # Detect a DeltaT-source transition independently for this exact fragment.
    gs=geom.geometry_at(siteA,siteB,s,refs); ge=geom.geometry_at(siteA,siteB,e,refs)
    if gs is None or ge is None:
        return {"fragment_status":"FINITE_GEOMETRY_INPUT_HOLD","extent_status":"NOT_APPLICABLE",
                "input_hold_reason":"GEOMETRY_REFERENCE_COVERAGE_HOLD","cells_processed":0,
                "cells_certified_empty":0,"cells_unresolved":0,"max_depth_reached":0,
                "exact_time_probes":0,"negative_certificate_digest_sha256":"",
                "unresolved_reason":"","certificate_audit":all_certs,"unresolved_audit":unresolved_audit,"witnesses":[]}
    srcs={str(gs[0].get("delta_t_source") or ""),str(gs[1].get("delta_t_source") or ""),
          str(ge[0].get("delta_t_source") or ""),str(ge[1].get("delta_t_source") or "")}
    crosses_reference_switch=len(srcs)>1

    def probe(t):
        nonlocal probes
        k=iso(t)
        if k not in cache:
            cache[k]=fixed_time_probe(vx,core,geom,t,pair_idx,pid,frag_idx,siteA,siteB,refs,compA,compB)
            probes+=1
        return cache[k]

    stack=[(s,e,0)]
    while stack:
        if cells>=MAX_CELLS_PER_FRAGMENT:
            unresolved_cells+=len(stack)
            unresolved_reasons["MAX_CELLS_PER_FRAGMENT"]+=len(stack)
            unresolved_audit.extend({"start_utc":iso(x[0]),"end_utc":iso(x[1]),"depth":x[2],"reason":"MAX_CELLS_PER_FRAGMENT"} for x in stack)
            break

        a,b,d=stack.pop();cells+=1;maxdepth=max(maxdepth,d)
        if cells%2000==0:
            print(f"[worker {os.getpid()}] pair {pair_idx} fragment {frag_idx}: cells={cells}, "
                  f"certified={cert_cells}, unresolved={unresolved_cells}, depth={maxdepth}",flush=True)
        m=a+(b-a)/2
        qlist=[probe(a),probe(m),probe(b)]

        hold=next((q for q in qlist if q["status"]=="INPUT_HOLD"),None)
        if hold:
            return {"fragment_status":"FINITE_GEOMETRY_INPUT_HOLD","extent_status":"NOT_APPLICABLE",
                    "input_hold_reason":hold["reason"],"cells_processed":cells,
                    "cells_certified_empty":cert_cells,"cells_unresolved":unresolved_cells,
                    "max_depth_reached":maxdepth,"exact_time_probes":probes,
                    "negative_certificate_digest_sha256":cert_digest(all_certs) if all_certs else "",
                    "unresolved_reason":"","certificate_audit":all_certs,"unresolved_audit":unresolved_audit,"witnesses":[]}

        wit=next((q for q in qlist if q["status"]=="WITNESS"),None)
        if wit:
            return {"fragment_status":"FINITE_GEOMETRY_ADMISSIBLE_WITNESS","extent_status":"PARTIAL_UNRESOLVED",
                    "input_hold_reason":"","cells_processed":cells,
                    "cells_certified_empty":cert_cells,"cells_unresolved":unresolved_cells,
                    "max_depth_reached":maxdepth,"exact_time_probes":probes,
                    "negative_certificate_digest_sha256":cert_digest(all_certs) if all_certs else "",
                    "unresolved_reason":"","certificate_audit":all_certs,"unresolved_audit":unresolved_audit,"witnesses":wit["witnesses"]}

        midq=qlist[1]
        certs=cell_outer_cert(core,(midq["A"],midq["B"]),compA,compB,
                              (b-a).total_seconds()/2,crosses_reference_switch)
        if certs is not None:
            cert_cells+=1
            all_certs.append({"start_utc":iso(a),"end_utc":iso(b),"depth":d,"component_certificates":certs})
            continue

        width=(b-a).total_seconds()
        if width<=MIN_CELL_WIDTH_S:
            unresolved_cells+=1;unresolved_reasons["MIN_CELL_WIDTH"]+=1;unresolved_audit.append({"start_utc":iso(a),"end_utc":iso(b),"depth":d,"reason":"MIN_CELL_WIDTH"});continue
        if d>=MAX_DEPTH:
            unresolved_cells+=1;unresolved_reasons["MAX_DEPTH"]+=1;unresolved_audit.append({"start_utc":iso(a),"end_utc":iso(b),"depth":d,"reason":"MAX_DEPTH"});continue
        stack.append((m,b,d+1));stack.append((a,m,d+1))

    status="FINITE_GEOMETRY_UNRESOLVED" if unresolved_cells else "FINITE_GEOMETRY_CERTIFIED_NONADMISSIBLE"
    extent="PARTIAL_UNRESOLVED" if unresolved_cells else "FULL_TIME_DOMAIN_CLASSIFIED"
    return {"fragment_status":status,"extent_status":extent,"input_hold_reason":"",
            "cells_processed":cells,"cells_certified_empty":cert_cells,"cells_unresolved":unresolved_cells,
            "max_depth_reached":maxdepth,"exact_time_probes":probes,
            "negative_certificate_digest_sha256":cert_digest(all_certs) if all_certs else "",
            "unresolved_reason":";".join(f"{k}:{v}" for k,v in sorted(unresolved_reasons.items())),
            "certificate_audit":all_certs,"unresolved_audit":unresolved_audit,"witnesses":[]}

def process_pair(vx,core,geom,idx,r,sites,refs,polys):
    pid=str(r["pair_id"])
    siteA=sites[str(r["site_a"]).strip()];siteB=sites[str(r["site_b"]).strip()]
    compA=poly_components(core,polys[vx.inum(r["solution_id_a"])])
    compB=poly_components(core,polys[vx.inum(r["solution_id_b"])])
    ints=vx.parse_intervals(r)
    if not ints:raise RuntimeError(f"interval replay HOLD {pid}")
    frows=[];wrows=[]

    # Process EVERY frozen overlap fragment even when an earlier fragment has a witness.
    for fi,(s,e) in enumerate(ints,1):
        rr=process_fragment(vx,core,geom,idx,pid,fi,s,e,siteA,siteB,refs,compA,compB)
        ws=rr.pop("witnesses")
        first=ws[0] if ws else None
        interval_json=[]
        for w in ws:
            interval_json.append({
              "component_a":w["component_a"],"component_b":w["component_b"],
              "min_distance_km":w["interval_min_distance_km"],"max_distance_km":w["interval_max_distance_km"],
              "max_unbounded":w["interval_max_unbounded"],"upper_extent_state":w["interval_upper_extent_state"],"lower_closed":w["interval_lower_closed"],
              "upper_closed":w["interval_upper_closed"]
            })
        frows.append({
          "pair_index":idx,"pair_id":pid,"fragment_index":fi,"start_utc":iso(s),"end_utc":iso(e),
          "duration_seconds":(e-s).total_seconds(),**rr,
          "witness_time_utc":"" if not first else first["time_utc"],
          "witness_distance_km":"" if not first else first["distance_km"],
          "witness_disparity_arcsec":"" if not first else first["disparity_arcsec"],
          "witness_ge2arcsec":"" if not first else first["ge2arcsec"],
          "fixed_time_component_intervals_json":json.dumps(interval_json,sort_keys=True,separators=(",",":")),
          "deltat_source":"" if not first else first["deltat_source"],
          "deltat_uncertainty_qualification":"" if not first else first["deltat_uncertainty_qualification"],
          "published_reference_max_score_arcsec":"" if not first else first["published_reference_max_score_arcsec"],
          "height107m_max_score_arcsec":"" if not first else first["height107m_max_score_arcsec"]
        })
        wrows.extend(ws)

    if len(frows)!=len(ints):
        raise RuntimeError(f"fragment completeness HOLD {pid}: {len(frows)}/{len(ints)}")

    statuses=[x["fragment_status"] for x in frows]
    if "FINITE_GEOMETRY_ADMISSIBLE_WITNESS" in statuses:
        pair_status="FINITE_GEOMETRY_ADMISSIBLE_WITNESS"
        extent="FULL_TIME_DOMAIN_CLASSIFIED" if all(x["extent_status"]=="FULL_TIME_DOMAIN_CLASSIFIED" for x in frows) else "PARTIAL_UNRESOLVED"
    elif "FINITE_GEOMETRY_INPUT_HOLD" in statuses:
        pair_status="FINITE_GEOMETRY_INPUT_HOLD";extent="NOT_APPLICABLE"
    elif "FINITE_GEOMETRY_UNRESOLVED" in statuses:
        pair_status="FINITE_GEOMETRY_UNRESOLVED";extent="PARTIAL_UNRESOLVED"
    elif all(x=="FINITE_GEOMETRY_CERTIFIED_NONADMISSIBLE" for x in statuses):
        pair_status="FINITE_GEOMETRY_CERTIFIED_NONADMISSIBLE";extent="FULL_TIME_DOMAIN_CLASSIFIED"
    else:
        pair_status="FINITE_GEOMETRY_UNRESOLVED";extent="PARTIAL_UNRESOLVED"

    first=wrows[0] if wrows else None
    sources=sorted(set(str(w["deltat_source"]) for w in wrows if str(w.get("deltat_source") or "")))
    quals=sorted(set(str(w["deltat_uncertainty_qualification"]) for w in wrows if str(w.get("deltat_uncertainty_qualification") or "")))
    pubs=[float(w["published_reference_max_score_arcsec"]) for w in wrows if w.get("published_reference_max_score_arcsec") not in (None,"")]
    h107=[float(w["height107m_max_score_arcsec"]) for w in wrows if w.get("height107m_max_score_arcsec") not in (None,"")]
    dig=hashlib.sha256("\n".join(x["negative_certificate_digest_sha256"] for x in frows).encode()).hexdigest() if frows else ""

    prow={
      "pair_index":idx,"pair_id":pid,"plate_a":r.get("plate_a",""),"plate_b":r.get("plate_b",""),
      "site_a":r.get("site_a",""),"site_b":r.get("site_b",""),
      "legacy_infinity_geometry_status":r.get("legacy_infinity_geometry_status",""),
      "overlap_fragment_count":len(ints),"pair_status":pair_status,"extent_status":extent,
      "witness_fragment_index":"" if not first else first["fragment_index"],
      "witness_time_utc":"" if not first else first["time_utc"],
      "witness_distance_km":"" if not first else first["distance_km"],
      "witness_disparity_arcsec":"" if not first else first["disparity_arcsec"],
      "witness_ge2arcsec":"" if not first else first["ge2arcsec"],
      "deltat_sources":";".join(sources),
      "deltat_uncertainty_qualification":";".join(quals),
      "published_reference_max_score_arcsec":max(pubs) if pubs else "",
      "height107m_max_score_arcsec":max(h107) if h107 else "",
      "cells_processed":sum(int(x["cells_processed"]) for x in frows),
      "cells_certified_empty":sum(int(x["cells_certified_empty"]) for x in frows),
      "cells_unresolved":sum(int(x["cells_unresolved"]) for x in frows),
      "exact_time_probes":sum(int(x["exact_time_probes"]) for x in frows),
      "negative_certificate_digest_sha256":dig,
      "input_hold_reason":";".join(x["input_hold_reason"] for x in frows if x["input_hold_reason"])
    }
    return {"pair":prow,"fragments":frows,"witnesses":wrows}

def worker_init(project,repo,core_path):
    global _W
    try:signal.signal(signal.SIGINT,signal.SIG_IGN)
    except:pass
    vx,core,geom,sites,refs,polys,overlap,ident,provenance,provsha=load_foundation(project,repo,Path(core_path))
    _W={"vx":vx,"core":core,"geom":geom,"sites":sites,"refs":refs,"polys":polys,"overlap":overlap}

def worker_chunk(cn,indices):
    out=[]
    for n,idx in enumerate(indices,1):
        out.append(process_pair(_W["vx"],_W["core"],_W["geom"],idx,_W["overlap"][idx-1],
                                _W["sites"],_W["refs"],_W["polys"]))
        if n%5==0 or n==len(indices):print(f"[worker {os.getpid()}] chunk {cn}: {n}/{len(indices)} pairs",flush=True)
    return os.getpid(),cn,out

def checkpoint_path(work,cn,ids):return Path(work)/"chunks"/f"chunk_{cn:04d}_{ids[0]:05d}_{ids[-1]:05d}.json"

def parse_iso_utc(s):
    from datetime import datetime,timezone
    try:
        q=datetime.fromisoformat(str(s).replace("Z","+00:00"))
        if q.tzinfo is None:return None
        return q.astimezone(timezone.utc)
    except:return None

def fragment_parent_identity_ok(fr,idx,pid,fi,s,e):
    if int(fr.get("pair_index",-1))!=idx or fr.get("pair_id")!=pid or int(fr.get("fragment_index",-1))!=fi:return False
    if parse_iso_utc(fr.get("start_utc"))!=s or parse_iso_utc(fr.get("end_utc"))!=e:return False
    try:dur=float(fr.get("duration_seconds"))
    except:return False
    return abs(dur-(e-s).total_seconds())<=1e-9

def status_accounting_ok(fr,cert_audit,unresolved_audit,s,e):
    st=fr.get("fragment_status");ext=fr.get("extent_status")
    try:
        cells=int(fr.get("cells_processed",-1));certn=int(fr.get("cells_certified_empty",-1));unrn=int(fr.get("cells_unresolved",-1));depth=int(fr.get("max_depth_reached",-1));probes=int(fr.get("exact_time_probes",-1))
    except:return False
    if min(cells,certn,unrn,depth,probes)<0 or depth>MAX_DEPTH or certn>cells:return False
    if len(cert_audit)!=certn or len(unresolved_audit)!=unrn:return False
    if st=="FINITE_GEOMETRY_CERTIFIED_NONADMISSIBLE":
        return (ext=="FULL_TIME_DOMAIN_CLASSIFIED" and unrn==0 and certn>0 and
                intervals_cover_exact(s,e,cert_audit) and cells==2*certn-1)
    if st=="FINITE_GEOMETRY_UNRESOLVED":
        if ext!="PARTIAL_UNRESOLVED" or unrn<=0 or not str(fr.get("unresolved_reason") or ""):return False
        if not intervals_cover_exact(s,e,cert_audit+unresolved_audit):return False
        return ("MAX_CELLS_PER_FRAGMENT" in str(fr.get("unresolved_reason") or "") or cells==2*(certn+unrn)-1)
    if st=="FINITE_GEOMETRY_INPUT_HOLD":
        return ext=="NOT_APPLICABLE" and bool(str(fr.get("input_hold_reason") or ""))
    if st=="FINITE_GEOMETRY_ADMISSIBLE_WITNESS":
        return ext=="PARTIAL_UNRESOLVED"
    return False

def aggregate_pair_status(frags,wits):
    sts=[f["fragment_status"] for f in frags]
    if any(x=="FINITE_GEOMETRY_ADMISSIBLE_WITNESS" for x in sts):return "FINITE_GEOMETRY_ADMISSIBLE_WITNESS","PARTIAL_UNRESOLVED"
    if any(x=="FINITE_GEOMETRY_INPUT_HOLD" for x in sts):return "FINITE_GEOMETRY_INPUT_HOLD","NOT_APPLICABLE"
    if any(x=="FINITE_GEOMETRY_UNRESOLVED" for x in sts):return "FINITE_GEOMETRY_UNRESOLVED","PARTIAL_UNRESOLVED"
    if sts and all(x=="FINITE_GEOMETRY_CERTIFIED_NONADMISSIBLE" for x in sts):return "FINITE_GEOMETRY_CERTIFIED_NONADMISSIBLE","FULL_TIME_DOMAIN_CLASSIFIED"
    return None,None

def intervals_cover_exact(start,end,leaves):
    spans=[]
    for x in leaves:
        a=parse_iso_utc(x.get("start_utc"));b=parse_iso_utc(x.get("end_utc"))
        if a is None or b is None or b<=a:return False
        spans.append((a,b))
    spans.sort()
    if not spans or spans[0][0]!=start or spans[-1][1]!=end:return False
    cur=start
    for a,b in spans:
        if a!=cur:return False
        cur=b
    return cur==end

def verify_certificate_audit(core,geom,siteA,siteB,refs,compA,compB,record):
    a=parse_iso_utc(record.get("start_utc"));b=parse_iso_utc(record.get("end_utc"))
    if a is None or b is None or b<=a:return False
    m=a+(b-a)/2;g=geom.geometry_at(siteA,siteB,m,refs)
    if g is None:return False
    A,B,_=g
    gs=geom.geometry_at(siteA,siteB,a,refs);ge=geom.geometry_at(siteA,siteB,b,refs)
    if gs is None or ge is None:return False
    srcs={str(gs[0].get("delta_t_source") or ""),str(gs[1].get("delta_t_source") or ""),
          str(ge[0].get("delta_t_source") or ""),str(ge[1].get("delta_t_source") or "")}
    rho=MOTION_BOUND_KM_S*(b-a).total_seconds()/2+(REFERENCE_SWITCH_ALLOWANCE_KM if len(srcs)>1 else 0.0)
    expected={(ia,ib):(ea,eb) for ia,ea in compA for ib,eb in compB}
    cc=record.get("component_certificates")
    if not isinstance(cc,list) or len(cc)!=len(expected):return False
    seen=set()
    for c in cc:
        key=(int(c.get("component_a",-1)),int(c.get("component_b",-1)))
        if key not in expected or key in seen:return False
        seen.add(key);ea,eb=expected[key]
        sysx=core.relaxed_footprint_system(ea,eb,A["r"],B["r"],rho,rho)
        ids=c.get("support_indices")
        cert=core.exact_farkas_certificate_for_support(sysx,ids)
        if cert is None:return False
    return seen==set(expected)

def validate_result_record(vx,core,geom,sites,refs,polys,idx,parent,rr):
    allowed={"FINITE_GEOMETRY_ADMISSIBLE_WITNESS","FINITE_GEOMETRY_CERTIFIED_NONADMISSIBLE","FINITE_GEOMETRY_UNRESOLVED","FINITE_GEOMETRY_INPUT_HOLD"}
    pid=str(parent["pair_id"]);pair=rr.get("pair");frags=rr.get("fragments");wits=rr.get("witnesses")
    if not isinstance(pair,dict) or not isinstance(frags,list) or not isinstance(wits,list):return False
    ints=vx.parse_intervals(parent)
    if len(ints)!=int(float(parent["fragment_overlap_count"])) or len(frags)!=len(ints):return False
    if int(pair.get("pair_index",-1))!=idx or pair.get("pair_id")!=pid or pair.get("pair_status") not in allowed:return False
    if int(pair.get("overlap_fragment_count",-1))!=len(ints):return False
    siteA=sites[str(parent["site_a"]).strip()];siteB=sites[str(parent["site_b"]).strip()]
    compA=poly_components(core,polys[vx.inum(parent["solution_id_a"])]);compB=poly_components(core,polys[vx.inum(parent["solution_id_b"])])
    wby={k:[] for k in range(1,len(ints)+1)}
    for w in wits:
        if int(w.get("pair_index",-1))!=idx or w.get("pair_id")!=pid:return False
        fi=int(w.get("fragment_index",-1))
        if fi not in wby:return False
        t=parse_iso_utc(w.get("time_utc"));s,e=ints[fi-1]
        if t is None or t<s or t>e:return False
        p=np.array([float(w["x_km"]),float(w["y_km"]),float(w["z_km"])])
        ia=int(w.get("component_a",-1));ib=int(w.get("component_b",-1))
        ca=dict(compA).get(ia);cb=dict(compB).get(ib)
        if ca is None or cb is None:return False
        g=geom.geometry_at(siteA,siteB,t,refs)
        if g is None:return False
        A,B,_=g
        sa=core.add_horizon(core.component_halfspaces(ca,A["r"],"A"),A["r"],A["up"],"A")
        sb=core.add_horizon(core.component_halfspaces(cb,B["r"],"B"),B["r"],B["up"],"B")
        sysx=core.combine(sa,sb)
        if not core.exact_halfspace_contains(sysx,p):return False
        if not core.verify_physical_witness(p,A,B)[0]:return False
        if abs(float(np.linalg.norm(p))-float(w.get("distance_km")))>max(1e-7,abs(float(w.get("distance_km")))*1e-12):return False
        wby[fi].append(w)
    for fi,(fr,(s,e)) in enumerate(zip(frags,ints),1):
        if not fragment_parent_identity_ok(fr,idx,pid,fi,s,e):return False
        st=fr.get("fragment_status");ext=fr.get("extent_status")
        if st not in allowed:return False
        cells=int(fr.get("cells_processed",-1));certn=int(fr.get("cells_certified_empty",-1));unrn=int(fr.get("cells_unresolved",-1));depth=int(fr.get("max_depth_reached",-1));probes=int(fr.get("exact_time_probes",-1))
        if min(cells,certn,unrn,depth,probes)<0 or depth>MAX_DEPTH or certn>cells:return False
        ca=fr.get("certificate_audit",[]);ua=fr.get("unresolved_audit",[])
        if not isinstance(ca,list) or not isinstance(ua,list):return False
        if not status_accounting_ok(fr,ca,ua,s,e):return False
        for rec in ca:
            if not verify_certificate_audit(core,geom,siteA,siteB,refs,compA,compB,rec):return False
        if st=="FINITE_GEOMETRY_ADMISSIBLE_WITNESS":
            if ext!="PARTIAL_UNRESOLVED" or not wby[fi] or not str(fr.get("witness_time_utc") or ""):return False
        else:
            if wby[fi]:return False
        if st=="FINITE_GEOMETRY_CERTIFIED_NONADMISSIBLE":
            if ext!="FULL_TIME_DOMAIN_CLASSIFIED" or unrn!=0 or certn<=0:return False
            if not intervals_cover_exact(s,e,ca):return False
            if cells!=2*certn-1:return False
            if not re.fullmatch(r"[0-9a-f]{64}",str(fr.get("negative_certificate_digest_sha256") or "")):return False
            if fr.get("negative_certificate_digest_sha256")!=cert_digest(ca):return False
        elif st=="FINITE_GEOMETRY_UNRESOLVED":
            if ext!="PARTIAL_UNRESOLVED" or unrn<=0 or not str(fr.get("unresolved_reason") or ""):return False
            if not intervals_cover_exact(s,e,ca+ua):return False
            expected_digest=cert_digest(ca) if ca else ""
            if str(fr.get("negative_certificate_digest_sha256") or "")!=expected_digest:return False
            if "MAX_CELLS_PER_FRAGMENT" not in str(fr.get("unresolved_reason") or "") and cells!=2*(certn+unrn)-1:return False
        elif st=="FINITE_GEOMETRY_INPUT_HOLD":
            if ext!="NOT_APPLICABLE" or not str(fr.get("input_hold_reason") or ""):return False
    agg,aggext=aggregate_pair_status(frags,wits)
    if pair.get("pair_status")!=agg or pair.get("extent_status")!=aggext:return False
    if int(pair.get("cells_processed",-1))!=sum(int(f["cells_processed"]) for f in frags):return False
    if int(pair.get("cells_certified_empty",-1))!=sum(int(f["cells_certified_empty"]) for f in frags):return False
    if int(pair.get("cells_unresolved",-1))!=sum(int(f["cells_unresolved"]) for f in frags):return False
    if int(pair.get("exact_time_probes",-1))!=sum(int(f["exact_time_probes"]) for f in frags):return False
    expected_pair_digest=hashlib.sha256("\n".join(str(f.get("negative_certificate_digest_sha256") or "") for f in frags).encode()).hexdigest()
    if pair.get("negative_certificate_digest_sha256")!=expected_pair_digest:return False
    return True

def validate_checkpoint(path,cn,ids,overlap,vx,core,geom,sites,refs,polys,ident,provsha):
    p=Path(path)
    if not p.is_file():return None
    try:q=json.loads(p.read_text(encoding="utf-8"))
    except:return None
    if q.get("release_identity")!=ident or q.get("input_provenance_sha256")!=provsha:return None
    if int(q.get("chunk_no",-1))!=cn or q.get("pair_indices")!=ids:return None
    data=q.get("results")
    if not isinstance(data,list) or len(data)!=len(ids) or q.get("results_sha256")!=canonical_sha(data):return None
    for idx,rr in zip(ids,data):
        if not validate_result_record(vx,core,geom,sites,refs,polys,idx,overlap[idx-1],rr):return None
    return q


def _self_test_geometry_provenance_binding():
    from types import SimpleNamespace
    with tempfile.TemporaryDirectory() as td:
        root=Path(td);project=root/"project";repo=root/"repo";project.mkdir();repo.mkdir()
        sol=project/"solution.csv";sol.write_text("solution\n",encoding="utf-8")
        prov=project/"prov.json";prov.write_text(json.dumps({"inputs":{"solution_full":{"path":"solution.csv"}}}),encoding="utf-8")
        def mk(base,name,content):
            p=base/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(content,encoding="utf-8");return p
        vx=SimpleNamespace(
            V094S_PROV=prov,
            V094T_CSV=mk(project,"v094t.csv","t\n"),
            V094T_REPORT=mk(project,"v094t.json","{}\n"),
            V094T_MANIFEST=mk(project,"v094t.sha256","m\n"),
            V094W_SITE=mk(project,"v094w_site.csv","s\n"),
            V094W_REPORT=mk(project,"v094w.json","{}\n"),
            V094W_MANIFEST=mk(project,"v094w.sha256","m\n"),
            GEOM_REL=Path("pipeline_v0.2.0/tools/executed_geometry.py"),
            C01_REL=Path("refs/c01.txt"),HIST_REL=Path("refs/hist.txt"),MONTH_REL=Path("refs/month.txt")
        )
        mk(project,"tools/run_v094x_source_free_full_population_finite_geometry_synthetic_validation.py","v094x-science\n")
        geom=mk(repo,vx.GEOM_REL,"geometry-v1\n")
        mk(repo,vx.C01_REL,"c01\n");mk(repo,vx.HIST_REL,"hist\n");mk(repo,vx.MONTH_REL,"month\n")
        q1,h1=foundation_provenance(project,repo,vx)
        assert "geometry_execution_module" in q1
        assert q1["geometry_execution_module"]["sha256"]==sha(geom)
        geom.write_text("geometry-v2\n",encoding="utf-8")
        q2,h2=foundation_provenance(project,repo,vx)
        assert h1!=h2 and q1["geometry_execution_module"]["sha256"]!=q2["geometry_execution_module"]["sha256"]
    return True

def self_test(core_path):
    ident=release_identity(Path(__file__).resolve().parent)
    if sha(core_path)!=ident["core_sha256"]:raise SystemExit("core release identity HOLD")
    core=load_module(core_path,"v094y_prod_selftest_core")
    ff=core.fixture_tests()
    if len(ff)!=19:raise SystemExit(f"core fixture count HOLD: {len(ff)}")
    # Pair aggregation must never convert unresolved fragment content into a certified negative.
    fr=[{"fragment_status":"FINITE_GEOMETRY_CERTIFIED_NONADMISSIBLE"},{"fragment_status":"FINITE_GEOMETRY_UNRESOLVED"}]
    assert aggregate_pair_status(fr,[])[0]=="FINITE_GEOMETRY_UNRESOLVED"
    from datetime import datetime,timezone,timedelta
    s0=datetime(1950,1,1,tzinfo=timezone.utc);e0=s0+timedelta(seconds=10)
    good_id={"pair_index":1,"pair_id":"p","fragment_index":1,"start_utc":iso(s0),"end_utc":iso(e0),"duration_seconds":10}
    bad_id=dict(good_id);bad_id["start_utc"]=iso(s0+timedelta(seconds=1))
    assert fragment_parent_identity_ok(good_id,1,"p",1,s0,e0)
    assert not fragment_parent_identity_ok(bad_id,1,"p",1,s0,e0)
    bad_negative={**good_id,"fragment_status":"FINITE_GEOMETRY_CERTIFIED_NONADMISSIBLE","extent_status":"FULL_TIME_DOMAIN_CLASSIFIED",
                  "cells_processed":1,"cells_certified_empty":0,"cells_unresolved":0,"max_depth_reached":0,"exact_time_probes":3,
                  "unresolved_reason":"","input_hold_reason":""}
    assert not status_accounting_ok(bad_negative,[],[],s0,e0)
    # Mutex literal must contain exactly namespace separator + no extra backslash in remainder.
    mname="Local"+chr(92)+"v094y_continuous_finite_geometry_admissibility_rc4_controller"
    sep=chr(92); assert mname.startswith("Local"+sep) and sep not in mname[len("Local"+sep):]
    assert _self_test_geometry_provenance_binding()
    # Freeze evidence reader must accept both PowerShell 5.1 UTF-8-with-BOM and BOM-less UTF-8.
    with tempfile.TemporaryDirectory() as td:
        fc="a"*40;rid={"release_manifest_sha256":"b"*64}
        payload={"freeze_commit":fc,"origin_main":fc,"release_manifest_sha256":rid["release_manifest_sha256"]}
        p1=Path(td)/"bom.json";p1.write_text(json.dumps(payload),encoding="utf-8-sig")
        p2=Path(td)/"plain.json";p2.write_text(json.dumps(payload),encoding="utf-8")
        assert verify_freeze_evidence(p1,fc,rid)
        assert verify_freeze_evidence(p2,fc,rid)
    print("v094y production RC4 self-test PASS")
    print(f"Core analytic fixtures: {len(ff)}/{len(ff)} PASS")
    print("Aggregation/mutex safety fixtures: PASS")
    return 0

def preflight(project,repo,core_path):
    vx,core,geom,sites,refs,polys,overlap,ident,provenance,provsha=load_foundation(project,repo,core_path)
    gates=check_gates(project,repo,vx,ident,provsha)
    preflight_site_geometry(vx,core,geom,sites,refs,overlap)
    required=set()
    for r in overlap:required|={vx.inum(r["solution_id_a"]),vx.inum(r["solution_id_b"])}
    for sid in sorted(required):poly_components(core,polys[sid])
    print("v094y RC4 PREFLIGHT PASS")
    print(f"Population: {len(overlap)} pairs / {sum(len(vx.parse_intervals(r)) for r in overlap)} fragments")
    print(f"Sites: {len(sites)}; required polygons: {len(required)}")
    print("RC4 release-bound regression: 1200 pairs / 29147 placements PASS and byte/provenance verified")
    print("P3 time-budget gate: 0 synthetic false negatives; only 0.01 s windows unresolved")
    print("No production pair has been classified by preflight.")
    return gates,ident,provsha

def write_csv(path,fields,rows):
    with Path(path).open("w",encoding="utf-8",newline="") as f:
        w=csv.DictWriter(f,fieldnames=fields,extrasaction="ignore");w.writeheader();w.writerows(rows)

def publish(project,allres,gates,runner_sha,ident,provsha):
    result=Path(project)/"results"/"applause_dr4_v094y_continuous_finite_geometry_admissibility"
    if result.exists():raise SystemExit(f"FINAL_PUBLISH_HOLD: result directory already exists: {result}")
    tmp=result.with_name(result.name+".tmp")
    if tmp.exists():
        import shutil;shutil.rmtree(tmp)
    tmp.mkdir(parents=True)

    pairs=[r["pair"] for r in allres]
    frags=[f for r in allres for f in r["fragments"]]
    wits=[w for r in allres for w in r["witnesses"]]
    if len(pairs)!=EXPECTED_PAIRS:raise SystemExit(f"FINAL_PUBLISH_HOLD pair rows {len(pairs)}")
    if len(frags)!=EXPECTED_FRAGMENTS:raise SystemExit(f"FINAL_PUBLISH_HOLD fragment rows {len(frags)}")

    write_csv(tmp/"v094y_pair_admissibility.csv",PAIR_FIELDS,pairs)
    write_csv(tmp/"v094y_fragment_admissibility.csv",FRAG_FIELDS,frags)
    write_csv(tmp/"v094y_witnesses.csv",WIT_FIELDS,wits)

    counts=Counter(r["pair_status"] for r in pairs)
    fcounts=Counter(r["fragment_status"] for r in frags)
    report={
      "analysis_kind":"v094y_continuous_finite_geometry_admissibility",
      "status":"COMPLETE","completed_utc":datetime.now(timezone.utc).isoformat(),
      "population_pairs":len(pairs),"population_fragments":len(frags),
      "pair_status_counts":dict(counts),"fragment_status_counts":dict(fcounts),
      "witness_rows":len(wits),
      "selected_time_profile":{"name":"P3","min_cell_width_s":MIN_CELL_WIDTH_S,
                               "max_depth":MAX_DEPTH,"max_cells_per_fragment":MAX_CELLS_PER_FRAGMENT},
      "motion_bound_km_s":MOTION_BOUND_KM_S,
      "reference_switch_allowance_km":REFERENCE_SWITCH_ALLOWANCE_KM,
      "production_guards":{"source_catalog_reads":0,"candidate_identity_inspection":0,
                           "pixels":0,"registration":0,"real_source_pairing":0,"network":0},
      "parent_gate_hashes":gates,"release_identity":ident,"input_provenance_sha256":provsha,
      "contract_sha256":ident["contract_sha256"],
      "core_sha256":ident["core_sha256"],
      "runner_sha256":runner_sha,
      "negative_interpretation":"CERTIFIED_NONADMISSIBLE applies under the frozen nominal timing/site model only.",
      "positive_interpretation":"A witness proves existence; PARTIAL_UNRESOLVED means the complete time-distance extent was not mapped.",
      "next_matcher_allowed":False
    }
    (tmp/"v094y_continuous_finite_geometry_admissibility.json").write_text(
        json.dumps(report,indent=2,sort_keys=True)+"\n",encoding="utf-8")

    outs=["v094y_pair_admissibility.csv","v094y_fragment_admissibility.csv","v094y_witnesses.csv",
          "v094y_continuous_finite_geometry_admissibility.json"]
    with (tmp/"v094y_output_manifest.sha256").open("w",encoding="utf-8",newline="\n") as f:
        for name in outs:f.write(f"{sha(tmp/name)}  {name}\n")
    os.replace(tmp,result)
    return report

def _checkpoint_result(cp,cn,ids,res,pid,overlap,vx,core,geom,sites,refs,polys,ident,provsha):
    q={"release_identity":ident,"input_provenance_sha256":provsha,
       "chunk_no":cn,"pair_indices":ids,"worker_pid":pid,
       "completed_utc":datetime.now(timezone.utc).isoformat(),"results":res,
       "results_sha256":canonical_sha(res)}
    atomic_json(cp,q)
    vv=validate_checkpoint(cp,cn,ids,overlap,vx,core,geom,sites,refs,polys,ident,provsha)
    if vv is None:raise RuntimeError(f"checkpoint validation failed chunk {cn}")
    return vv

def _drain_inflight(inflight,valid,overlap,label,vx,core,geom,sites,refs,polys,ident,provsha):
    while inflight:
        done,_=wait(list(inflight),timeout=2,return_when=FIRST_COMPLETED)
        if not done:continue
        for fut in done:
            cn,ids,cp=inflight.pop(fut)
            try:
                pid,rcn,res=fut.result()
                if rcn!=cn:raise RuntimeError("chunk number mismatch")
                valid[cn]=_checkpoint_result(cp,cn,ids,res,pid,overlap,vx,core,geom,sites,refs,polys,ident,provsha)
                print(f"[{label}] checkpointed chunk {cn}",flush=True)
            except BaseException as e:
                print(f"[{label}] chunk {cn} not retained: {e!r}",flush=True)

def run_production(project,repo,core_path,workers):
    gates,ident,provsha=preflight(project,repo,core_path)
    vx,core,geom,sites,refs,polys,overlap,ident2,provenance,provsha2=load_foundation(project,repo,core_path)
    if ident2!=ident or provsha2!=provsha:raise SystemExit("production preflight identity replay HOLD")
    work=Path(project)/"work"/"v094y_continuous_finite_geometry_admissibility_rc4"
    (work/"chunks").mkdir(parents=True,exist_ok=True)

    chunks=[]
    for off in range(0,EXPECTED_PAIRS,CHUNK_PAIRS):
        ids=list(range(off+1,min(EXPECTED_PAIRS,off+CHUNK_PAIRS)+1))
        chunks.append((len(chunks)+1,ids))

    valid={};todo=[]
    for cn,ids in chunks:
        cp=checkpoint_path(work,cn,ids);q=validate_checkpoint(cp,cn,ids,overlap,vx,core,geom,sites,refs,polys,ident,provsha)
        if q is None:todo.append((cn,ids,cp))
        else:valid[cn]=q
    print(f"Validated checkpoints: {len(valid)}/{len(chunks)}; remaining {len(todo)}")

    inflight={};remaining=list(todo);failures=[]
    ex=ProcessPoolExecutor(max_workers=workers,initializer=worker_init,
                           initargs=(str(project),str(repo),str(core_path)))
    try:
        def schedule():
            while remaining and len(inflight)<workers:
                cn,ids,cp=remaining.pop(0)
                inflight[ex.submit(worker_chunk,cn,ids)]=(cn,ids,cp)

        try:
            schedule()
            while inflight:
                done,_=wait(list(inflight),timeout=2,return_when=FIRST_COMPLETED)
                if not done:continue
                batch_failed=False
                for fut in done:
                    cn,ids,cp=inflight.pop(fut)
                    try:
                        pid,rcn,res=fut.result()
                        if rcn!=cn:raise RuntimeError("chunk number mismatch")
                        valid[cn]=_checkpoint_result(cp,cn,ids,res,pid,overlap,vx,core,geom,sites,refs,polys,ident,provsha)
                        donepairs=sum(len(valid[c]["results"]) for c in valid)
                        donefrags=sum(len(x["fragments"]) for c in valid for x in valid[c]["results"])
                        sc=Counter(x["pair"]["pair_status"] for c in valid for x in valid[c]["results"])
                        print(f"[controller] chunk {cn}/{len(chunks)} checkpointed; "
                              f"pairs={donepairs}/{EXPECTED_PAIRS}; fragments={donefrags}/{EXPECTED_FRAGMENTS}; "
                              f"statuses={dict(sc)}",flush=True)
                    except BaseException as e:
                        failures.append({"chunk":cn,"error":repr(e),"traceback":traceback.format_exc()})
                        batch_failed=True
                        print(f"PRODUCTION_CHUNK_HOLD chunk {cn}: {e!r}",flush=True)

                if batch_failed:
                    remaining=[]
                    for ftr in inflight:ftr.cancel()
                    _drain_inflight(inflight,valid,overlap,"failure-drain",vx,core,geom,sites,refs,polys,ident,provsha)
                    break
                schedule()

        except KeyboardInterrupt:
            print("USER_INTERRUPT: stopping new submissions; running chunks will drain.",flush=True)
            remaining=[]
            for ftr in inflight:ftr.cancel()
            _drain_inflight(inflight,valid,overlap,"interrupt-drain",vx,core,geom,sites,refs,polys,ident,provsha)
            raise SystemExit("USER_INTERRUPT_HOLD: validated completed chunks retained")
    finally:
        ex.shutdown(wait=True,cancel_futures=True)

    if failures:
        atomic_json(work/"hold.json",{"status":"HOLD","failures":failures,
                                      "valid_chunks_retained":len(valid),
                                      "utc":datetime.now(timezone.utc).isoformat()})
        raise SystemExit(f"PRODUCTION_HOLD: {len(failures)} chunk failure(s); validated checkpoints retained")

    allres=[]
    totalfrags=0
    for cn,ids in chunks:
        q=validate_checkpoint(checkpoint_path(work,cn,ids),cn,ids,overlap,vx,core,geom,sites,refs,polys,ident,provsha)
        if q is None:raise SystemExit(f"FINAL_CHECKPOINT_HOLD chunk {cn}")
        allres.extend(q["results"])
        totalfrags+=sum(len(x["fragments"]) for x in q["results"])
    if len(allres)!=EXPECTED_PAIRS:raise SystemExit("FINAL pair count HOLD")
    if totalfrags!=EXPECTED_FRAGMENTS:raise SystemExit(f"FINAL fragment count HOLD {totalfrags}")

    rep=publish(project,allres,gates,sha(Path(__file__)),ident,provsha)
    print(json.dumps(rep,indent=2))
    return 0

def _git(repo,*args,bytes_out=False):
    cp=subprocess.run(["git","-C",str(repo),*args],capture_output=True)
    if cp.returncode!=0:raise SystemExit(f"GIT_FREEZE_HOLD: git {' '.join(args)} failed: {cp.stderr.decode(errors='replace').strip()}")
    return cp.stdout if bytes_out else cp.stdout.decode().strip()

def verify_freeze_evidence(path,freeze_commit,ident):
    p=Path(path)
    if not p.is_file():raise SystemExit("GIT_FREEZE_HOLD: missing freeze evidence JSON")
    q=json.loads(p.read_text(encoding="utf-8-sig"))
    if q.get("freeze_commit")!=freeze_commit or q.get("origin_main")!=freeze_commit:return False
    if q.get("release_manifest_sha256")!=ident["release_manifest_sha256"]:return False
    return True

def verify_git_freeze(repo,freeze_commit,freeze_evidence,ident,here):
    if not re.fullmatch(r"[0-9a-fA-F]{40}",str(freeze_commit)):raise SystemExit("GIT_FREEZE_HOLD: --freeze-commit must be full 40-hex SHA")
    freeze_commit=str(freeze_commit).lower()
    resolved=_git(repo,"rev-parse",f"{freeze_commit}^{{commit}}").lower()
    if resolved!=freeze_commit:raise SystemExit("GIT_FREEZE_HOLD: commit resolution mismatch")
    if _git(repo,"rev-parse","HEAD").lower()!=freeze_commit:raise SystemExit("GIT_FREEZE_HOLD: RepoRoot HEAD is not the frozen commit")
    if _git(repo,"status","--porcelain","--untracked-files=no").strip():raise SystemExit("GIT_FREEZE_HOLD: tracked working tree/index is not clean")
    if not verify_freeze_evidence(freeze_evidence,freeze_commit,ident):raise SystemExit("GIT_FREEZE_HOLD: freeze evidence mismatch")
    paths={
      "v094y_finite_geometry_core_rc4.py":"pipeline_v0.2.0/tools/v094y_finite_geometry_core_rc4.py",
      "run_v094y_production_rc4.py":"pipeline_v0.2.0/tools/run_v094y_production_rc4.py",
      "run_v094y_rc4_release_regression.py":"pipeline_v0.2.0/tools/run_v094y_rc4_release_regression.py",
      "v094y_production_rc4_contract.json":"pipeline_v0.2.0/research/prospective_freezes/v094y_continuous_finite_geometry_admissibility_rc4/v094y_production_rc4_contract.json",
      "release_manifest.sha256":"pipeline_v0.2.0/research/prospective_freezes/v094y_continuous_finite_geometry_admissibility_rc4/release_manifest.sha256"
    }
    manmap=release_manifest_map(here)[1]
    for local,rel in paths.items():
        data=_git(repo,"show",f"{freeze_commit}:{rel}",bytes_out=True)
        if hashlib.sha256(data).hexdigest()!=sha(Path(here)/local):raise SystemExit(f"GIT_FREEZE_HOLD: Git blob mismatch {rel}")
        if local!="release_manifest.sha256" and manmap.get(local)!=sha(Path(here)/local):raise SystemExit(f"GIT_FREEZE_HOLD: manifest mismatch {local}")
    print(f"Git freeze verification PASS: {freeze_commit}")
    return freeze_commit

def acquire_controller_mutex():
    if os.name!="nt":
        return None
    import ctypes
    from ctypes import wintypes
    k=ctypes.WinDLL("kernel32",use_last_error=True)
    k.CreateMutexW.argtypes=[wintypes.LPVOID,wintypes.BOOL,wintypes.LPCWSTR]
    k.CreateMutexW.restype=wintypes.HANDLE
    k.CloseHandle.argtypes=[wintypes.HANDLE]
    name=r"Local\v094y_continuous_finite_geometry_admissibility_rc4_controller"
    h=k.CreateMutexW(None,False,name)
    if not h:raise SystemExit(f"CONTROLLER_MUTEX_HOLD: CreateMutexW failed {ctypes.get_last_error()}")
    if ctypes.get_last_error()==183:
        k.CloseHandle(h)
        raise SystemExit("CONTROLLER_MUTEX_HOLD: another v094y RC4 production controller is already running")
    return (k,h)

def release_controller_mutex(token):
    if token is None:return
    k,h=token
    try:k.CloseHandle(h)
    except:pass

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--project-root")
    ap.add_argument("--repo-root")
    ap.add_argument("--self-test",action="store_true")
    ap.add_argument("--preflight-only",action="store_true")
    ap.add_argument("--production",action="store_true")
    ap.add_argument("--workers",type=int,default=DEFAULT_WORKERS)
    ap.add_argument("--freeze-commit")
    ap.add_argument("--freeze-evidence")
    a=ap.parse_args()
    here=Path(__file__).resolve().parent;core_path=here/"v094y_finite_geometry_core_rc4.py"
    contract=here/"v094y_production_rc4_contract.json"
    ident=release_identity(here)
    if sha(contract)!=ident["contract_sha256"]:raise SystemExit("contract release identity HOLD")
    if a.self_test:return self_test(core_path)
    if not a.project_root or not a.repo_root:raise SystemExit("--project-root and --repo-root required")
    if not 1<=a.workers<=8:raise SystemExit("--workers must be 1..8")
    if a.preflight_only:
        self_test(core_path);preflight(Path(a.project_root),Path(a.repo_root),core_path);return 0
    if not a.production:
        raise SystemExit("SAFETY HOLD: RC4 production requires explicit --production. Review/regression/preflight/freeze first.")
    if not a.freeze_commit or not a.freeze_evidence:
        raise SystemExit("SAFETY HOLD: production also requires --freeze-commit and --freeze-evidence")
    verify_git_freeze(Path(a.repo_root),a.freeze_commit,a.freeze_evidence,ident,here)
    mutex=acquire_controller_mutex()
    try:
        return run_production(Path(a.project_root),Path(a.repo_root),core_path,a.workers)
    finally:
        release_controller_mutex(mutex)

if __name__=="__main__":
    raise SystemExit(main())
