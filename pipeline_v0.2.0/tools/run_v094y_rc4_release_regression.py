#!/usr/bin/env python3
from __future__ import annotations
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor, wait, FIRST_COMPLETED
from datetime import datetime, timezone
from collections import Counter
import argparse, csv, hashlib, importlib.util, json, math, os, signal, sys, tempfile, traceback

EXPECTED_V094X_SHA = "f75a866e63dfedd24a677acd925d8e4e2a53e34d99e582596e0adb9a3db5e7cc"
EXPECTED_ROWS=8807
EXPECTED_POSITIVE_PAIRS=1200
EXPECTED_LEGACY_NONPOSITIVE_POSITIVE=122
EXPECTED_TANGENT_UNRESOLVED=30
EXPECTED_PLACEMENTS=29147
CHUNK_PAIRS=10
DEFAULT_WORKERS=8
CONTAINMENT_RESID_KM=2e-6
DISTANCE_REL_TOL=2e-10
_W=None

def sha(p):
    h=hashlib.sha256()
    with Path(p).open("rb") as f:
        for b in iter(lambda:f.read(8*1024*1024),b""):h.update(b)
    return h.hexdigest()

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

def rows(p):
    with Path(p).open("r",encoding="utf-8-sig",newline="") as q:yield from csv.DictReader(q)

def iv(v):return int(round(float(str(v).strip())))

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

def manifest_check(manifest,base):
    for line in Path(manifest).read_text(encoding="utf-8").splitlines():
        q=line.strip().split(None,1)
        if len(q)!=2:continue
        digest,name=q[0].lower(),q[1].strip();p=Path(base)/name
        if not p.is_file() or sha(p)!=digest:raise SystemExit(f"v094x final manifest HOLD: {name}")

def canonical_distance_key(x,distances):
    x=float(x)
    for d in distances:
        if abs(x-d)<=max(1e-6,abs(d)*1e-12):return str(d)
    raise ValueError(f"unexpected distance key {x}")

def load_foundation(project_root,repo_root,core_path):
    project=Path(project_root);repo=Path(repo_root)
    vx_path=project/"tools"/"run_v094x_source_free_full_population_finite_geometry_synthetic_validation.py"
    if not vx_path.is_file() or sha(vx_path)!=EXPECTED_V094X_SHA:raise SystemExit("frozen v094x science runner SHA HOLD")
    ident=release_identity(Path(__file__).resolve().parent)
    if sha(Path(core_path))!=ident["core_sha256"]:raise SystemExit("RC4 core release identity HOLD")
    vx=load_module(vx_path,f"v094x_rc4_regression_{os.getpid()}")
    proto=load_module(Path(core_path),f"v094y_rc4_core_{os.getpid()}")
    geom=vx.load_parent_geometry(repo);sites,refs,polys,overlap=vx.load_foundation(repo,geom)
    if len(overlap)!=EXPECTED_ROWS:raise SystemExit(f"v094x overlap replay HOLD: {len(overlap)}")
    provenance,provsha=foundation_provenance(project,repo,vx)
    return vx,proto,geom,sites,refs,polys,overlap,ident,provenance,provsha

def load_v094x_final(project_root):
    result=Path(project_root)/"results"/"applause_dr4_v094x_full_population_finite_geometry_synthetic_validation"
    manifest=result/"v094x_output_manifest.sha256";report=result/"v094x_full_population_finite_geometry_synthetic_validation.json";csvp=result/"v094x_pair_geometry_synthetic_validation.csv"
    if not(manifest.is_file() and report.is_file() and csvp.is_file()):raise SystemExit("banked v094x final output missing")
    manifest_check(manifest,result);rep=json.loads(report.read_text(encoding="utf-8"))
    if rep.get("status")!="COMPLETE" or int(rep.get("output_rows",-1))!=EXPECTED_ROWS:raise SystemExit("banked v094x final report HOLD")
    data=list(rows(csvp))
    if len(data)!=EXPECTED_ROWS:raise SystemExit(f"banked v094x CSV row HOLD: {len(data)}")
    byidx={iv(r["pair_index"]):r for r in data}
    if len(byidx)!=EXPECTED_ROWS or set(byidx)!=set(range(1,EXPECTED_ROWS+1)):raise SystemExit("v094x pair_index coverage HOLD")
    positives=[r for r in data if iv(r["placements"])>0]
    unresolved=[r for r in data if r["legacy_infinity_geometry_status"]=="LEGACY_TANGENT_UNRESOLVED"]
    if len(positives)!=EXPECTED_POSITIVE_PAIRS:raise SystemExit(f"positive-pair count HOLD: {len(positives)}")
    if sum(iv(r["placements"]) for r in positives)!=EXPECTED_PLACEMENTS:raise SystemExit("total placement count HOLD")
    if sum(1 for r in positives if r["legacy_infinity_geometry_status"]=="LEGACY_TANGENT_NONPOSITIVE")!=EXPECTED_LEGACY_NONPOSITIVE_POSITIVE:raise SystemExit("legacy nonpositive finite-positive count HOLD")
    if len(unresolved)!=EXPECTED_TANGENT_UNRESOLVED:raise SystemExit("legacy tangent-unresolved count HOLD")
    return byidx,positives,unresolved

def poly_components(proto,poly):
    vv=[proto.xyz(*q) for q in poly];tris=proto.triangulate_spherical_polygon(vv)
    return [(tri,proto.convex_component_edge_normals(tri)) for tri in tris]

def component_systems(proto,components,state,label):
    out=[]
    for ci,(_,edges) in enumerate(components):
        s=proto.component_halfspaces(edges,state["r"],label);s=proto.add_horizon(s,state["r"],state["up"],label);out.append((ci,s))
    return out

def candidate_point(vx,A,B,D,nA,nB):
    import numpy as np
    P=vx.ray_sphere(A["r"],nA,D)
    if P is None:return None,"A_RAY_SPHERE_NONE"
    P=np.asarray(P,float);d=float(np.linalg.norm(P))
    if abs(d-D)>max(1e-6,abs(D)*DISTANCE_REL_TOL):return None,f"DISTANCE_MISMATCH:{d}:{D}"
    db=P-B["r"];nn=float(np.linalg.norm(db))
    if nn<=0:return None,"B_ZERO_RAY"
    db/=nn;chord=float(np.linalg.norm(db-np.asarray(nB,float)))
    if chord>2e-10:return None,f"B_DIRECTION_MISMATCH_CHORD:{chord}"
    return P,None

def containing_component(proto,sysA,sysB,P,A,B):
    matches=[]
    for ia,sa in sysA:
        for ib,sb in sysB:
            system=proto.combine(sa,sb);resid=proto.min_residual(system,P)
            if resid>=-CONTAINMENT_RESID_KM:matches.append((resid,ia,ib,system))
    if not matches:return None,"NO_V094Y_COMPONENT_CONTAINS_V094X_POINT"
    matches.sort(key=lambda x:(-x[0],x[1],x[2]));resid,ia,ib,system=matches[0]
    ok,why=proto.verify_physical_witness(P,A,B)
    if not ok:return None,f"PHYSICAL_WITNESS_FAIL:{why}"
    state,_,_=proto.feasible_lp(system)
    if state!="FEASIBLE":return None,f"MATCHING_COMPONENT_LP_NOT_FEASIBLE:{state}"
    return {"component_a":ia,"component_b":ib,"residual_km":float(resid)},None

def replay_positive_pair(vx,proto,geom,sites,refs,polys,overlap,expected):
    idx=iv(expected["pair_index"]);r=overlap[idx-1]
    if str(r.get("pair_id") or "")!=expected["pair_id"]:raise RuntimeError(f"parent pair mismatch {idx}")
    siteA=sites[str(r["site_a"]).strip()];siteB=sites[str(r["site_b"]).strip()]
    polyA=polys[vx.inum(r["solution_id_a"])];polyB=polys[vx.inum(r["solution_id_b"])]
    compA=poly_components(proto,polyA);compB=poly_components(proto,polyB);intervals=vx.parse_intervals(r)
    if not intervals:raise RuntimeError(f"interval replay HOLD pair {idx}")
    grid_cache={};generated=0;cases_with=0;bydist=Counter();minres=None
    for s,e in intervals:
        for true_t in (s,s+(e-s)/2,e):
            g=geom.geometry_at(siteA,siteB,true_t,refs)
            if g is None:raise RuntimeError(f"geometry HOLD pair {idx}")
            A,B,_=g;sa=component_systems(proto,compA,A,"A");sb=component_systems(proto,compB,B,"B")
            for D in vx.DISTANCES_KM:
                cand,_=vx.find_case_candidates(geom,polyA,polyB,A,B,D,grid_cache)
                if cand:cases_with+=1
                for nA,nB in cand:
                    generated+=1;bydist[str(D)]+=1
                    P,err=candidate_point(vx,A,B,D,nA,nB)
                    if err:raise RuntimeError(f"pair {idx} placement {generated}: {err}")
                    match,err=containing_component(proto,sa,sb,P,A,B)
                    if err:raise RuntimeError(f"pair {idx} placement {generated}: {err}")
                    minres=match["residual_km"] if minres is None else min(minres,match["residual_km"])
    if generated!=iv(expected["placements"]):raise RuntimeError(f"pair {idx} placement mismatch regenerated={generated} banked={expected['placements']}")
    if cases_with!=iv(expected["cases_with_observable_placement"]):raise RuntimeError(f"pair {idx} case mismatch regenerated={cases_with} banked={expected['cases_with_observable_placement']}")
    bd=json.loads(expected["by_distance_json"]);exp={}
    for k,v in bd.items():exp[canonical_distance_key(k,vx.DISTANCES_KM)]=int(v.get("placements",0))
    got={k:v for k,v in bydist.items() if v};expnz={k:v for k,v in exp.items() if v}
    if got!=expnz:raise RuntimeError(f"pair {idx} by-distance mismatch regenerated={got} banked={expnz}")
    return {"pair_index":idx,"pair_id":expected["pair_id"],"placements":generated,"cases_with_observable_placement":cases_with,
            "legacy_infinity_geometry_status":expected["legacy_infinity_geometry_status"],"minimum_containment_residual_km":minres,"status":"REGRESSION_PASS"}

def structural_unresolved(vx,proto,geom,sites,refs,polys,overlap,expected):
    idx=iv(expected["pair_index"]);r=overlap[idx-1]
    siteA=sites[str(r["site_a"]).strip()];siteB=sites[str(r["site_b"]).strip()]
    polyA=polys[vx.inum(r["solution_id_a"])];polyB=polys[vx.inum(r["solution_id_b"])]
    ca=poly_components(proto,polyA);cb=poly_components(proto,polyB);ints=vx.parse_intervals(r)
    if not ints:raise RuntimeError(f"unresolved interval HOLD {idx}")
    samples=0
    for s,e in ints:
        for t in (s,s+(e-s)/2,e):
            g=geom.geometry_at(siteA,siteB,t,refs)
            if g is None:raise RuntimeError(f"unresolved geometry HOLD {idx}")
            A,B,_=g
            if len(component_systems(proto,ca,A,"A"))*len(component_systems(proto,cb,B,"B"))<=0:raise RuntimeError(f"unresolved component HOLD {idx}")
            samples+=1
    return {"pair_index":idx,"pair_id":expected["pair_id"],"time_samples":samples,"status":"TANGENT_UNRESOLVED_STRUCTURAL_PASS"}

def worker_init(project_root,repo_root,prototype_path,positive_expected):
    global _W
    try:signal.signal(signal.SIGINT,signal.SIG_IGN)
    except:pass
    vx,proto,geom,sites,refs,polys,overlap,ident,provenance,provsha=load_foundation(project_root,repo_root,prototype_path)
    _W={"vx":vx,"proto":proto,"geom":geom,"sites":sites,"refs":refs,"polys":polys,"overlap":overlap,"positive":positive_expected}

def worker_chunk(chunk_no,indices):
    out=[]
    for n,idx in enumerate(indices,1):
        out.append(replay_positive_pair(_W["vx"],_W["proto"],_W["geom"],_W["sites"],_W["refs"],_W["polys"],_W["overlap"],_W["positive"][str(idx)]))
        if n%2==0 or n==len(indices):print(f"[worker {os.getpid()}] regression chunk {chunk_no}: {n}/{len(indices)} pairs",flush=True)
    return os.getpid(),chunk_no,out

def expected_digest(indices,expected):
    raw=[[idx,expected[str(idx)]["pair_id"],expected[str(idx)]["placements"],expected[str(idx)]["cases_with_observable_placement"],expected[str(idx)]["by_distance_json"]] for idx in indices]
    return hashlib.sha256(json.dumps(raw,separators=(",",":"),ensure_ascii=True).encode()).hexdigest()

def cp_path(work,cn,ids):return Path(work)/"chunks"/f"chunk_{cn:04d}_{ids[0]:05d}_{ids[-1]:05d}.json"

def validate_cp(path,cn,ids,expected,ident,provsha):
    p=Path(path)
    if not p.is_file():return None
    try:q=json.loads(p.read_text(encoding="utf-8"))
    except:return None
    if q.get("release_identity")!=ident or q.get("input_provenance_sha256")!=provsha:return None
    if int(q.get("chunk_no",-1))!=cn or q.get("expected_digest")!=expected_digest(ids,expected):return None
    rr=q.get("rows")
    if not isinstance(rr,list) or len(rr)!=len(ids) or q.get("rows_sha256")!=canonical_sha(rr):return None
    for idx,row in zip(ids,rr):
        exp=expected[str(idx)]
        if int(row.get("pair_index",-1))!=idx or row.get("pair_id")!=exp["pair_id"] or row.get("status")!="REGRESSION_PASS":return None
        if int(row.get("placements",-1))!=iv(exp["placements"]):return None
    return q

def write_cp(path,cn,ids,expected,out,pid,ident,provsha):
    q={"release_identity":ident,"input_provenance_sha256":provsha,
       "frozen_v094x_sha256":EXPECTED_V094X_SHA,"chunk_no":cn,"expected_digest":expected_digest(ids,expected),
       "worker_pid":pid,"completed_utc":datetime.now(timezone.utc).isoformat(),"rows":out,"rows_sha256":canonical_sha(out)}
    atomic_json(path,q)
    if validate_cp(path,cn,ids,expected,ident,provsha) is None:raise RuntimeError(f"checkpoint self-validation failed chunk {cn}")


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

def self_test():
    here=Path(__file__).resolve().parent;core_path=here/"v094y_finite_geometry_core_rc4.py"
    ident=release_identity(here)
    proto=load_module(core_path,"v094y_rc4_regression_selftest_core")
    results=proto.fixture_tests()
    assert len(results)==19
    assert "self_crossing_polygon_rejected PASS" in results
    assert "verified_narrow_recession_ray PASS" in results
    assert "rotated_wgs84_frame PASS" in results
    assert "missing_rc2t_rejected PASS" in results
    assert _self_test_geometry_provenance_binding()
    s=proto.hs([[1,0,0],[-1,0,0]],[1,0]);cert=proto.exact_farkas_certificate(s)
    assert cert and cert["margin_float_km"]>0
    print(f"v094y RC4 release regression self-test PASS ({len(results)}/{len(results)} core fixtures)")
    return 0

def run(project_root,repo_root,workers):
    here=Path(__file__).resolve().parent;core_path=here/"v094y_finite_geometry_core_rc4.py"
    ident=release_identity(here)
    vx,proto,geom,sites,refs,polys,overlap,ident2,provenance,provsha=load_foundation(project_root,repo_root,core_path)
    if ident2!=ident:raise SystemExit("release identity replay HOLD")
    byidx,positives,unresolved=load_v094x_final(project_root)
    expected={str(iv(r["pair_index"])):r for r in positives};indices=sorted(map(int,expected))
    print("="*112);print("v094y RC4 RELEASE-BOUND REGRESSION -- NO PRODUCTION ADMISSIBILITY CLASSIFICATION");print("="*112)
    print(f"Banked v094x rows:                              {len(byidx)}")
    print(f"Placement-positive regression pairs:           {len(indices)}")
    print(f"Placements to reconstruct and contain:          {sum(iv(r['placements']) for r in positives)}")
    print(f"Legacy nonpositive finite-positive pairs:       {sum(1 for r in positives if r['legacy_infinity_geometry_status']=='LEGACY_TANGENT_NONPOSITIVE')}")
    print(f"Tangent-unresolved structural pairs:            {len(unresolved)}")
    print(f"Workers:                                         {workers}")
    work=Path(project_root)/"work"/"v094y_rc4_release_regression";(work/"chunks").mkdir(parents=True,exist_ok=True)
    chunks=[]
    for off in range(0,len(indices),CHUNK_PAIRS):chunks.append((len(chunks)+1,indices[off:off+CHUNK_PAIRS]))
    valid={};todo=[]
    for cn,ids in chunks:
        cp=cp_path(work,cn,ids);q=validate_cp(cp,cn,ids,expected,ident,provsha)
        if q is None:todo.append((cn,ids,cp))
        else:valid[cn]=q
    print(f"Validated existing checkpoints:                 {len(valid)}/{len(chunks)}")
    print(f"Regression chunks remaining:                    {len(todo)}")
    audit={"status":"RUNNING","started_utc":datetime.now(timezone.utc).isoformat(),"release_identity":ident,
           "input_provenance_sha256":provsha,"workers":workers,"existing_valid_chunks":len(valid)};atomic_json(work/"audit.json",audit)
    failures=[];remaining=list(todo);inflight={}
    ex=ProcessPoolExecutor(max_workers=workers,initializer=worker_init,initargs=(str(project_root),str(repo_root),str(core_path),expected))
    try:
        def schedule():
            while remaining and len(inflight)<workers:
                cn,ids,cp=remaining.pop(0);inflight[ex.submit(worker_chunk,cn,ids)]=(cn,ids,cp)
        try:
            schedule()
            while inflight:
                done,_=wait(list(inflight),timeout=2,return_when=FIRST_COMPLETED)
                if not done:continue
                batch_fail=False
                for fut in done:
                    cn,ids,cp=inflight.pop(fut)
                    try:
                        pid,rcn,out=fut.result()
                        if rcn!=cn or len(out)!=len(ids):raise RuntimeError("worker result structural HOLD")
                        write_cp(cp,cn,ids,expected,out,pid,ident,provsha);valid[cn]=validate_cp(cp,cn,ids,expected,ident,provsha)
                        dp=sum(len(valid[c]["rows"]) for c in valid);pl=sum(sum(int(x["placements"]) for x in valid[c]["rows"]) for c in valid)
                        print(f"[controller] checkpointed chunk {cn}/{len(chunks)} via worker {pid}; pairs={dp}/{EXPECTED_POSITIVE_PAIRS}; placements={pl}/{EXPECTED_PLACEMENTS}",flush=True)
                    except BaseException as e:
                        failures.append({"chunk":cn,"error":repr(e),"traceback":traceback.format_exc()});batch_fail=True;print(f"REGRESSION_WORKER_HOLD chunk {cn}: {e!r}",flush=True)
                if batch_fail:
                    for ftr in inflight:ftr.cancel()
                    while inflight:
                        dd,_=wait(list(inflight),timeout=2,return_when=FIRST_COMPLETED)
                        for fut in dd:
                            cn,ids,cp=inflight.pop(fut)
                            try:
                                pid,rcn,out=fut.result()
                                if rcn==cn and len(out)==len(ids):write_cp(cp,cn,ids,expected,out,pid,ident,provsha);valid[cn]=validate_cp(cp,cn,ids,expected,ident,provsha);print(f"[drain] checkpointed chunk {cn} via worker {pid}",flush=True)
                            except BaseException as e:failures.append({"chunk":cn,"error":repr(e)})
                    break
                schedule()
        except KeyboardInterrupt:
            print("\nCtrl+C: stopping new submissions and draining running prototype regression work.",flush=True);remaining=[]
            for ftr in inflight:ftr.cancel()
            while inflight:
                dd,_=wait(list(inflight),timeout=2,return_when=FIRST_COMPLETED)
                for fut in dd:
                    cn,ids,cp=inflight.pop(fut)
                    try:
                        pid,rcn,out=fut.result()
                        if rcn==cn and len(out)==len(ids):write_cp(cp,cn,ids,expected,out,pid,ident,provsha);valid[cn]=validate_cp(cp,cn,ids,expected,ident,provsha);print(f"[drain] checkpointed chunk {cn} via worker {pid}",flush=True)
                    except:pass
            raise SystemExit("USER_INTERRUPT_HOLD: validated regression checkpoints retained")
    finally:ex.shutdown(wait=True,cancel_futures=True)
    if failures:
        audit.update({"status":"HOLD","failures":failures,"valid_chunks":len(valid)});atomic_json(work/"audit.json",audit);raise SystemExit(f"REGRESSION_HOLD: {len(failures)} failures; checkpoints retained")
    allrows=[]
    for cn,ids in chunks:
        q=validate_cp(cp_path(work,cn,ids),cn,ids,expected,ident,provsha)
        if q is None:raise SystemExit(f"FINAL_CHECKPOINT_HOLD chunk {cn}")
        allrows.extend(q["rows"])
    if len(allrows)!=EXPECTED_POSITIVE_PAIRS or sum(int(r["placements"]) for r in allrows)!=EXPECTED_PLACEMENTS:raise SystemExit("FINAL regression aggregate HOLD")
    lnp=sum(1 for r in allrows if r["legacy_infinity_geometry_status"]=="LEGACY_TANGENT_NONPOSITIVE")
    if lnp!=EXPECTED_LEGACY_NONPOSITIVE_POSITIVE:raise SystemExit("FINAL legacy-nonpositive regression HOLD")
    ur=[]
    for n,exp in enumerate(sorted(unresolved,key=lambda r:iv(r["pair_index"])),1):
        ur.append(structural_unresolved(vx,proto,geom,sites,refs,polys,overlap,exp))
        if n%10==0 or n==len(unresolved):print(f"Tangent-unresolved structural replay: {n}/{len(unresolved)}",flush=True)
    if len(ur)!=EXPECTED_TANGENT_UNRESOLVED:raise SystemExit("FINAL tangent-unresolved structural HOLD")
    # Final manifest over all release-bound checkpoint bytes.
    cp_entries=[]
    for cn,ids in chunks:
        cp=cp_path(work,cn,ids);cp_entries.append({"chunk":cn,"path":str(cp),"sha256":sha(cp)})
    checkpoint_manifest_sha256=canonical_sha(cp_entries)
    summary={"status":"RC4_RELEASE_REGRESSION_PASS","completed_utc":datetime.now(timezone.utc).isoformat(),
             "production_admissibility_classifications_emitted":0,
             "positive_pairs_replayed":len(allrows),"placements_reconstructed_and_contained":sum(int(r["placements"]) for r in allrows),
             "legacy_nonpositive_finite_positive_pairs_passed":lnp,"legacy_tangent_unresolved_structural_pairs_passed":len(ur),
             "minimum_recorded_containment_residual_km":min(float(r["minimum_containment_residual_km"]) for r in allrows),
             "checkpoint_chunks":len(chunks),"checkpoint_manifest_sha256":checkpoint_manifest_sha256,
             "release_identity":ident,"input_provenance":provenance,"input_provenance_sha256":provsha,"failures":0,
             "next_stage":"Independent RC4 review/preflight; production remains disabled until Git freeze."}
    atomic_json(work/"checkpoint_manifest.json",cp_entries)
    atomic_json(work/"summary.json",summary);audit.update(summary);atomic_json(work/"audit.json",audit)
    print("\n"+json.dumps(summary,indent=2));print("\nv094y RC4 RELEASE-BOUND REGRESSION PASS.");print("No production pair-level admissibility classification has occurred; regression is release-bound.");return 0

def main():
    ap=argparse.ArgumentParser();ap.add_argument("--self-test",action="store_true");ap.add_argument("--project-root");ap.add_argument("--repo-root");ap.add_argument("--workers",type=int,default=DEFAULT_WORKERS);a=ap.parse_args()
    if a.self_test:return self_test()
    if not a.project_root or not a.repo_root:raise SystemExit("--project-root and --repo-root required")
    if not 1<=a.workers<=8:raise SystemExit("--workers must be 1..8")
    return run(Path(a.project_root),Path(a.repo_root),a.workers)
if __name__=="__main__":raise SystemExit(main())
