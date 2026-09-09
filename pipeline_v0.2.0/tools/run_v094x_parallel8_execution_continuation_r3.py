#!/usr/bin/env python3
from __future__ import annotations
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor, wait, FIRST_COMPLETED, CancelledError
from datetime import datetime, timezone
import argparse, csv, ctypes, hashlib, importlib.util, io, json, math, os, shutil, signal, sys, time

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT/"research"/"prospective_freezes"/"v094x_parallel8_r3_execution_continuation_contract.json"
EXPECTED_CONTRACT_SHA = "38bf417a82d5dfc450e4fbed06e704a943959af7cd204d19455c4116bfe82820"
BASE = ROOT/"tools"/"run_v094x_source_free_full_population_finite_geometry_synthetic_validation.py"
EXPECTED_BASE_SHA = "f75a866e63dfedd24a677acd925d8e4e2a53e34d99e582596e0adb9a3db5e7cc"
WORKERS = 8
MAX_IN_FLIGHT = 8
MIN_FREE_BYTES = 5 * 1024**3
MIN_AVAIL_PHYS_BYTES = 2 * 1024**3
MIN_AVAIL_COMMIT_BYTES = 4 * 1024**3
POLL_SECONDS = 2.0
VALIDATION_VERSION = "v094x_parallel8_r3_checkpoint_validation_v1"

_W = {}

def sha(p):
    h=hashlib.sha256()
    with Path(p).open("rb") as f:
        for b in iter(lambda:f.read(8*1024*1024),b""):h.update(b)
    return h.hexdigest()

def load_module(path,name):
    spec=importlib.util.spec_from_file_location(name,path)
    if spec is None or spec.loader is None:raise RuntimeError(f"Cannot import {path}")
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
    return m

def canonical_row(base,row):
    s=io.StringIO(newline="")
    w=csv.DictWriter(s,fieldnames=base.OUTPUT_FIELDS,lineterminator="\n")
    w.writeheader();w.writerow(row);s.seek(0)
    return next(csv.DictReader(s))

def int_exact(v,name):
    try:
        s=str(v).strip()
        if s=="" or any(c in s.lower() for c in (".","e")):
            # Frozen CSV writes integer counters as decimal integers. Reject float-looking corruption.
            raise ValueError
        x=int(s)
    except:
        raise ValueError(f"{name}: not an integer: {v!r}")
    if x<0:raise ValueError(f"{name}: negative: {x}")
    return x

def finite_float(v,name,allow_blank=False):
    s=str(v or "").strip()
    if allow_blank and s=="":return None
    try:x=float(s)
    except:raise ValueError(f"{name}: not numeric: {v!r}")
    if not math.isfinite(x):raise ValueError(f"{name}: non-finite")
    return x

def parse_json_strict(v,name,expected_type):
    try:q=json.loads(str(v))
    except Exception as e:raise ValueError(f"{name}: invalid JSON: {e}")
    if not isinstance(q,expected_type):raise ValueError(f"{name}: wrong JSON type")
    return q

def expected_parent_digest(base,expected):
    h=hashlib.sha256()
    for idx,r in expected:
        h.update(f"{idx}\x1f{r.get('pair_id','')}\x1f{base.parent_signature(r)}\n".encode("utf-8"))
    return h.hexdigest()

def checkpoint_meta_path(cp):
    return Path(str(cp)+".meta.json")

def provenance_snapshot(base):
    return {
        "v094t_manifest_sha256": sha(base.V094T_MANIFEST),
        "v094w_manifest_sha256": sha(base.V094W_MANIFEST),
        "v094s_provenance_sha256": sha(base.V094S_PROV),
    }

def validate_row_semantics(base,q,parent,idx):
    # Exact parent identity/provenance fields.
    exact = {
        "pair_index": str(idx),
        "pair_id": str(parent.get("pair_id") or ""),
        "parent_signature_sha256": base.parent_signature(parent),
        "plate_a": str(parent.get("plate_a","")),
        "plate_b": str(parent.get("plate_b","")),
        "solution_id_a": str(parent.get("solution_id_a","")),
        "solution_id_b": str(parent.get("solution_id_b","")),
        "site_a": str(parent.get("site_a","")),
        "site_b": str(parent.get("site_b","")),
        "legacy_infinity_geometry_status": str(parent.get("legacy_infinity_geometry_status","")),
        "old_common_positive_infinity_footprint": str(parent.get("old_common_positive_infinity_footprint","")),
    }
    for k,want in exact.items():
        if str(q.get(k,""))!=want:raise ValueError(f"{k}: parent mismatch")

    ivs=base.parse_intervals(parent)
    if not ivs:raise ValueError("parent overlap interval replay failed")
    n_iv=len(ivs)
    if int_exact(q["overlap_interval_count"],"overlap_interval_count")!=n_iv:
        raise ValueError("overlap_interval_count mismatch")

    status=str(q.get("status") or "")
    valid_status={
        "GEOMETRY_REFERENCE_COVERAGE_HOLD",
        "NO_JOINT_OBSERVABLE_CASE_FOUND_AT_MAX_RESOLUTION",
        "FINITE_GEOMETRY_SYNTHETIC_PRECISION_HOLD",
        "FINITE_GEOMETRY_SITE_METADATA_STRESS_HOLD",
        "FINITE_GEOMETRY_SYNTHETIC_PASS_DELTAT_UNCERTAINTY_QUALIFIED",
        "FINITE_GEOMETRY_SYNTHETIC_PASS",
    }
    if status not in valid_status:raise ValueError(f"invalid status: {status}")

    # Baseline outputs must be finite for non-reference-HOLD rows.
    bmin=finite_float(q["baseline_length_km_min"],"baseline_length_km_min",allow_blank=(status=="GEOMETRY_REFERENCE_COVERAGE_HOLD"))
    bmax=finite_float(q["baseline_length_km_max"],"baseline_length_km_max",allow_blank=(status=="GEOMETRY_REFERENCE_COVERAGE_HOLD"))
    sweep=finite_float(q["baseline_sweep_max_arcsec"],"baseline_sweep_max_arcsec",allow_blank=(status=="GEOMETRY_REFERENCE_COVERAGE_HOLD"))
    if bmin is not None and (bmin<=0 or bmax is None or bmax<bmin):raise ValueError("baseline length relationship invalid")
    if sweep is not None and sweep<0:raise ValueError("baseline sweep negative")

    sources={x for x in str(q.get("deltat_sources") or "").split(";") if x}
    if not sources.issubset({"HISTORIC_WITH_ERROR","MONTHLY_NO_ERROR"}):
        raise ValueError(f"invalid DeltaT sources: {sources}")
    monthly=("MONTHLY_NO_ERROR" in sources)
    qual=str(q.get("deltat_uncertainty_qualification") or "")
    expected_qual="DELTAT_UNCERTAINTY_UNAVAILABLE" if monthly else "HISTORIC_DELTAT_ERROR_AVAILABLE"
    if qual!=expected_qual:raise ValueError("DeltaT qualification inconsistent with sources")
    if status!="GEOMETRY_REFERENCE_COVERAGE_HOLD" and not sources:
        raise ValueError("non-HOLD row has no DeltaT source")

    cases=int_exact(q["time_distance_cases"],"time_distance_cases")
    withp=int_exact(q["cases_with_observable_placement"],"cases_with_observable_placement")
    nop=int_exact(q["cases_without_observable_placement"],"cases_without_observable_placement")
    placements=int_exact(q["placements"],"placements")
    recovered=int_exact(q["recovered"],"recovered")
    rfail=int_exact(q["recovery_failures"],"recovery_failures")
    refgt=int_exact(q["available_published_reference_gt2arcsec"],"available_published_reference_gt2arcsec")
    hgt=int_exact(q["height107m_gt2arcsec"],"height107m_gt2arcsec")
    level=int_exact(q["max_grid_level_used"],"max_grid_level_used")

    expected_cases=n_iv*3*len(base.DISTANCES_KM)
    if status!="GEOMETRY_REFERENCE_COVERAGE_HOLD" and cases!=expected_cases:
        raise ValueError(f"time_distance_cases {cases} != expected {expected_cases}")
    if cases>expected_cases:raise ValueError("time_distance_cases exceeds frozen design")
    if withp+nop!=cases:raise ValueError("with-placement + no-case != cases")
    if placements<withp or placements>withp*3:raise ValueError("placements outside 1..3 per observable case")
    if recovered+rfail!=placements:raise ValueError("recovered + recovery_failures != placements")
    if refgt>placements or hgt>placements:raise ValueError("stress-failure count exceeds placements")
    if not (status=="GEOMETRY_REFERENCE_COVERAGE_HOLD" and cases==0 and level==0) and level not in set(base.GRID_LEVELS):
        raise ValueError(f"invalid grid level {level}")

    obs=parse_json_strict(q["observable_distance_grid_values_km_json"],"observable_distance_grid_values_km_json",list)
    obs_float=[]
    for x in obs:
        try:z=float(x)
        except:raise ValueError("observable distance contains non-number")
        if not math.isfinite(z):raise ValueError("observable distance non-finite")
        obs_float.append(z)
    if obs_float!=sorted(set(obs_float)):raise ValueError("observable distance list not sorted/unique")
    allowed=[float(x) for x in base.DISTANCES_KM]
    if any(x not in allowed for x in obs_float):raise ValueError("observable distance outside frozen grid")

    bd=parse_json_strict(q["by_distance_json"],"by_distance_json",dict)
    expected_keys={str(x) for x in base.DISTANCES_KM}
    if set(bd)!=expected_keys:raise ValueError(f"distance JSON keys mismatch: {set(bd)}")
    known={
        "cases","no_case_found","cases_with_placement","placements","recovered","recovery_failures",
        "available_published_reference_gt2arcsec","height107m_gt2arcsec",
        "grid_level_9_cases","grid_level_17_cases","grid_level_33_cases","grid_level_65_cases"
    }
    sums={k:0 for k in ("cases","no_case_found","cases_with_placement","placements","recovered",
                        "recovery_failures","available_published_reference_gt2arcsec","height107m_gt2arcsec")}
    observed_from_bd=[]
    per_distance_expected=n_iv*3
    for dk in expected_keys:
        sub=bd[dk]
        if not isinstance(sub,dict):raise ValueError(f"{dk}: subtotal not object")
        if set(sub)-known:raise ValueError(f"{dk}: unknown subtotal keys {set(sub)-known}")
        vals={}
        for k,v in sub.items():
            vals[k]=int_exact(v,f"{dk}.{k}")
        c=vals.get("cases",0);wp=vals.get("cases_with_placement",0);nc=vals.get("no_case_found",0)
        pl=vals.get("placements",0);rc=vals.get("recovered",0);rf=vals.get("recovery_failures",0)
        rg=vals.get("available_published_reference_gt2arcsec",0);hg=vals.get("height107m_gt2arcsec",0)
        grids=sum(vals.get(f"grid_level_{g}_cases",0) for g in base.GRID_LEVELS)
        if status!="GEOMETRY_REFERENCE_COVERAGE_HOLD" and c!=per_distance_expected:
            raise ValueError(f"{dk}: cases {c} != expected {per_distance_expected}")
        if c>per_distance_expected:raise ValueError(f"{dk}: cases exceed design")
        if wp+nc!=c:raise ValueError(f"{dk}: with-placement + no-case != cases")
        if grids!=c:raise ValueError(f"{dk}: grid-level totals != cases")
        if pl<wp or pl>wp*3:raise ValueError(f"{dk}: placements outside 1..3 per observable case")
        if rc+rf!=pl:raise ValueError(f"{dk}: recovered + failures != placements")
        if rg>pl or hg>pl:raise ValueError(f"{dk}: stress count exceeds placements")
        if wp>0:observed_from_bd.append(float(dk))
        for k in sums:sums[k]+=vals.get(k,0)

    if sorted(observed_from_bd)!=obs_float:raise ValueError("observable-distance list disagrees with distance subtotals")
    if sums["cases"]!=cases or sums["cases_with_placement"]!=withp or sums["no_case_found"]!=nop:
        raise ValueError("distance case subtotals disagree with row totals")
    if sums["placements"]!=placements or sums["recovered"]!=recovered or sums["recovery_failures"]!=rfail:
        raise ValueError("distance recovery subtotals disagree with row totals")
    if sums["available_published_reference_gt2arcsec"]!=refgt or sums["height107m_gt2arcsec"]!=hgt:
        raise ValueError("distance stress subtotals disagree with row totals")

    if status!="GEOMETRY_REFERENCE_COVERAGE_HOLD":
        expected_status=base.classify(True,placements,rfail,refgt,hgt,monthly)
        if status!=expected_status:raise ValueError(f"status/accounting mismatch: {status} != {expected_status}")
    return True

def read_chunk_exact(base,path):
    with Path(path).open("r",encoding="utf-8-sig",newline="") as f:
        rd=csv.DictReader(f)
        if rd.fieldnames!=list(base.OUTPUT_FIELDS):
            raise ValueError(f"CSV schema/order mismatch: {rd.fieldnames}")
        data=list(rd)
    for r in data:
        if None in r:raise ValueError("CSV row has extra columns")
    return data

def write_json_atomic(path,obj):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_name(path.name+".__tmp__."+str(os.getpid()))
    tmp.write_text(json.dumps(obj,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    os.replace(tmp,path)

def validate_checkpoint(base,cp,expected,adopt_missing_meta=True):
    cp=Path(cp)
    if not cp.is_file():return None
    try:
        data=read_chunk_exact(base,cp)
        if len(data)!=len(expected):raise ValueError(f"row count {len(data)} != {len(expected)}")
        for pos,((idx,parent),q) in enumerate(zip(expected,data),1):
            validate_row_semantics(base,q,parent,idx)
        pd=expected_parent_digest(base,expected)
        meta_path=checkpoint_meta_path(cp)
        prov=provenance_snapshot(base)
        controller_sha=sha(Path(__file__).resolve())
        expected_meta={
            "validation_version":VALIDATION_VERSION,
            "checkpoint_csv_sha256":sha(cp),
            "row_count":len(data),
            "first_pair_index":expected[0][0],
            "last_pair_index":expected[-1][0],
            "parent_pair_signature_digest_sha256":pd,
            "frozen_science_runner_sha256":EXPECTED_BASE_SHA,
            "execution_contract_sha256":EXPECTED_CONTRACT_SHA,
            "controller_runner_sha256_at_validation":controller_sha,
            "parent_provenance":prov,
        }
        if meta_path.is_file():
            meta=json.loads(meta_path.read_text(encoding="utf-8"))
            for k,v in expected_meta.items():
                if meta.get(k)!=v:raise ValueError(f"checkpoint metadata mismatch: {k}")
        elif adopt_missing_meta:
            meta=dict(expected_meta)
            meta["validated_utc"]=datetime.now(timezone.utc).isoformat()
            meta["adoption"]="EXISTING_CHECKPOINT_FULL_ROW_VALIDATION"
            write_json_atomic(meta_path,meta)
        else:
            raise ValueError("checkpoint metadata missing")
        return data
    except Exception as e:
        return ("INVALID",str(e))

def preserve_checkpoint_pair(cp):
    cp=Path(cp);meta=checkpoint_meta_path(cp)
    stamp=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    if cp.exists():cp.rename(cp.with_name(cp.name+".invalid."+stamp))
    if meta.exists():meta.rename(meta.with_name(meta.name+".invalid."+stamp))

def checkpoint_worker_result(base,cp,expected,out):
    base.write_chunk_atomic(cp,out)
    # Full semantic validation first; then create/update a provenance sidecar.
    meta=checkpoint_meta_path(cp)
    if meta.exists():meta.unlink()
    check=validate_checkpoint(base,cp,expected,adopt_missing_meta=True)
    if isinstance(check,tuple) and check and check[0]=="INVALID":
        preserve_checkpoint_pair(cp)
        raise RuntimeError(f"post-write checkpoint validation HOLD: {check[1]}")
    if check is None:raise RuntimeError("post-write checkpoint disappeared")
    return check

# ---------- Windows resource / lock helpers ----------
class MEMORYSTATUSEX(ctypes.Structure):
    _fields_=[
        ("dwLength",ctypes.c_ulong),("dwMemoryLoad",ctypes.c_ulong),
        ("ullTotalPhys",ctypes.c_ulonglong),("ullAvailPhys",ctypes.c_ulonglong),
        ("ullTotalPageFile",ctypes.c_ulonglong),("ullAvailPageFile",ctypes.c_ulonglong),
        ("ullTotalVirtual",ctypes.c_ulonglong),("ullAvailVirtual",ctypes.c_ulonglong),
        ("ullAvailExtendedVirtual",ctypes.c_ulonglong)
    ]

class PROCESS_MEMORY_COUNTERS_EX(ctypes.Structure):
    _fields_=[
        ("cb",ctypes.c_ulong),("PageFaultCount",ctypes.c_ulong),
        ("PeakWorkingSetSize",ctypes.c_size_t),("WorkingSetSize",ctypes.c_size_t),
        ("QuotaPeakPagedPoolUsage",ctypes.c_size_t),("QuotaPagedPoolUsage",ctypes.c_size_t),
        ("QuotaPeakNonPagedPoolUsage",ctypes.c_size_t),("QuotaNonPagedPoolUsage",ctypes.c_size_t),
        ("PagefileUsage",ctypes.c_size_t),("PeakPagefileUsage",ctypes.c_size_t),
        ("PrivateUsage",ctypes.c_size_t)
    ]

def memory_status():
    if os.name!="nt":
        return {"total_phys":0,"avail_phys":2**63-1,"total_commit":0,"avail_commit":2**63-1}
    m=MEMORYSTATUSEX();m.dwLength=ctypes.sizeof(MEMORYSTATUSEX)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m)):
        raise RuntimeError("GlobalMemoryStatusEx failed")
    return {"total_phys":int(m.ullTotalPhys),"avail_phys":int(m.ullAvailPhys),
            "total_commit":int(m.ullTotalPageFile),"avail_commit":int(m.ullAvailPageFile)}

def process_memory(pid):
    if os.name!="nt":
        return {"private":0,"working_set":0,"measurement_ok":True,"error":None}
    PROCESS_QUERY_LIMITED_INFORMATION=0x1000
    ctypes.windll.kernel32.SetLastError(0)
    h=ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION,False,int(pid))
    if not h:
        err=int(ctypes.windll.kernel32.GetLastError())
        return {"private":None,"working_set":None,"measurement_ok":False,
                "error":{"pid":int(pid),"stage":"OpenProcess","windows_error":err}}
    try:
        c=PROCESS_MEMORY_COUNTERS_EX();c.cb=ctypes.sizeof(c)
        ctypes.windll.kernel32.SetLastError(0)
        ok=ctypes.windll.psapi.GetProcessMemoryInfo(h,ctypes.byref(c),c.cb)
        if not ok:
            err=int(ctypes.windll.kernel32.GetLastError())
            return {"private":None,"working_set":None,"measurement_ok":False,
                    "error":{"pid":int(pid),"stage":"GetProcessMemoryInfo","windows_error":err}}
        return {"private":int(c.PrivateUsage),"working_set":int(c.WorkingSetSize),
                "measurement_ok":True,"error":None}
    finally:
        ctypes.windll.kernel32.CloseHandle(h)

def resource_snapshot(pids=()):
    disk=shutil.disk_usage(ROOT)
    mem=memory_status()
    priv=ws=0;by_pid={};errors=[]
    for pid in sorted(set(int(x) for x in pids if x)):
        q=process_memory(pid);by_pid[str(pid)]=q
        if not q.get("measurement_ok",False):
            errors.append(q.get("error") or {"pid":int(pid),"stage":"unknown","windows_error":None})
            continue
        priv+=int(q["private"]);ws+=int(q["working_set"])
    return {"disk_free":disk.free,"avail_phys":mem["avail_phys"],"avail_commit":mem["avail_commit"],
            "worker_private":priv,"worker_working_set":ws,"workers":by_pid,
            "measurement_errors":errors}

def resource_reason(s):
    if s.get("measurement_errors"):
        return "memory measurement unavailable: " + json.dumps(s["measurement_errors"],sort_keys=True)
    if s["disk_free"]<MIN_FREE_BYTES:return f"disk free {s['disk_free']/1024**3:.2f} GB < 5.00 GB"
    if s["avail_phys"]<MIN_AVAIL_PHYS_BYTES:return f"available physical {s['avail_phys']/1024**3:.2f} GB < 2.00 GB"
    if s["avail_commit"]<MIN_AVAIL_COMMIT_BYTES:return f"available commit {s['avail_commit']/1024**3:.2f} GB < 4.00 GB"
    return None

def pre_pool_resource_reason(s,selfmem):
    if not selfmem.get("measurement_ok",False):
        return "controller memory measurement unavailable: " + json.dumps(selfmem.get("error"),sort_keys=True)
    if s.get("measurement_errors"):
        return "memory measurement unavailable: " + json.dumps(s["measurement_errors"],sort_keys=True)
    if s["disk_free"]<MIN_FREE_BYTES:
        return f"disk free {s['disk_free']/1024**3:.2f} GB < 5.00 GB"
    need_phys=max(4*1024**3,int(math.ceil(selfmem["working_set"]*WORKERS*1.15)))
    need_commit=max(6*1024**3,int(math.ceil(selfmem["private"]*WORKERS*1.25)))
    if s["avail_phys"]<need_phys:
        return (f"available physical {s['avail_phys']/1024**3:.2f} GB < dynamic 8-worker "
                f"preflight requirement {need_phys/1024**3:.2f} GB")
    if s["avail_commit"]<need_commit:
        return (f"available commit {s['avail_commit']/1024**3:.2f} GB < dynamic 8-worker "
                f"preflight requirement {need_commit/1024**3:.2f} GB")
    return None

def should_exit_work_loop(hold_reason,inflight):
    return hold_reason is not None and len(inflight)==0

class ControllerLock:
    def __init__(self):
        self.handle=None;self.lockfile=None
    def acquire(self):
        ident=hashlib.sha256(str(ROOT.resolve()).lower().encode()).hexdigest()[:20]
        if os.name=="nt":
            name=f"Local\\HistoricalTransient_v094x_parallel8_r3_{ident}"
            ctypes.windll.kernel32.SetLastError(0)
            h=ctypes.windll.kernel32.CreateMutexW(None,False,name)
            if not h:raise RuntimeError("CreateMutexW failed")
            err=ctypes.windll.kernel32.GetLastError()
            if err==183:
                ctypes.windll.kernel32.CloseHandle(h)
                raise SystemExit("CONTROLLER_LOCK_HOLD: another v094x parallel8-r3 controller is active for this project")
            self.handle=h
        else:
            p=ROOT/"work"/".v094x_parallel8_r3_controller.lock"
            p.parent.mkdir(parents=True,exist_ok=True)
            try:self.handle=os.open(p,os.O_CREAT|os.O_EXCL|os.O_WRONLY)
            except FileExistsError:raise SystemExit("CONTROLLER_LOCK_HOLD: another controller lock exists")
            self.lockfile=p
        info=ROOT/"work"/"applause_dr4_v094x_full_population_finite_geometry_synthetic_validation"/"parallel8_r3_controller.json"
        info.parent.mkdir(parents=True,exist_ok=True)
        self.info=info
        write_json_atomic(info,{"pid":os.getpid(),"started_utc":datetime.now(timezone.utc).isoformat(),
                                "root":str(ROOT.resolve()),"controller_sha256":sha(Path(__file__).resolve())})
    def release(self):
        try:
            if getattr(self,"info",None) and self.info.exists():self.info.unlink()
        except:pass
        if os.name=="nt" and self.handle:
            ctypes.windll.kernel32.ReleaseMutex(self.handle)
            ctypes.windll.kernel32.CloseHandle(self.handle)
        elif self.handle is not None:
            try:os.close(self.handle)
            except:pass
            try:
                if self.lockfile and self.lockfile.exists():self.lockfile.unlink()
            except:pass

def worker_init(project_root,repo_root):
    global _W
    try:signal.signal(signal.SIGINT,signal.SIG_IGN)
    except:pass
    root=Path(project_root)
    base_path=root/"tools"/"run_v094x_source_free_full_population_finite_geometry_synthetic_validation.py"
    if not base_path.is_file() or sha(base_path)!=EXPECTED_BASE_SHA:
        raise RuntimeError("Worker frozen v094x runner SHA mismatch")
    base=load_module(base_path,f"v094x_worker_{os.getpid()}")
    geom=base.load_parent_geometry(Path(repo_root))
    sites,refs,polys,overlap=base.load_foundation(Path(repo_root),geom)
    _W={"base":base,"geom":geom,"sites":sites,"refs":refs,"polys":polys,"overlap":overlap}

def worker_pair(index,row):
    w=_W
    out=w["base"].process_pair(w["geom"],index,row,w["sites"],w["refs"],w["polys"])
    return os.getpid(),out

def worker_chunk(chunk_no,start_index,part):
    w=_W;out=[]
    for off,row in enumerate(part):
        idx=start_index+off
        out.append(w["base"].process_pair(w["geom"],idx,row,w["sites"],w["refs"],w["polys"]))
        if (off+1)%5==0 or off+1==len(part):
            print(f"[worker {os.getpid()}] chunk {chunk_no}: {off+1}/{len(part)} pairs",flush=True)
    return os.getpid(),chunk_no,start_index,out

def build_synthetic_valid_row(fake,parent,idx):
    D=list(fake.DISTANCES_KM);per=3;cases=per*len(D)
    bd={}
    for d in D:
        bd[str(d)]={"cases":per,"cases_with_placement":1,"no_case_found":per-1,
                    "placements":1,"recovered":1,"grid_level_9_cases":per}
    return {
        "pair_index":str(idx),"pair_id":parent["pair_id"],"parent_signature_sha256":fake.parent_signature(parent),
        "plate_a":"1","plate_b":"2","solution_id_a":"10","solution_id_b":"20","site_a":"A","site_b":"B",
        "legacy_infinity_geometry_status":"LEGACY_TANGENT_NONPOSITIVE","old_common_positive_infinity_footprint":"False",
        "overlap_interval_count":"1","baseline_length_km_min":"100","baseline_length_km_max":"101",
        "baseline_sweep_max_arcsec":"0.5","deltat_sources":"HISTORIC_WITH_ERROR",
        "deltat_uncertainty_qualification":"HISTORIC_DELTAT_ERROR_AVAILABLE",
        "time_distance_cases":str(cases),"cases_with_observable_placement":str(len(D)),
        "cases_without_observable_placement":str(cases-len(D)),"max_grid_level_used":"9",
        "placements":str(len(D)),"recovered":str(len(D)),"recovery_failures":"0",
        "available_published_reference_gt2arcsec":"0","height107m_gt2arcsec":"0",
        "observable_distance_grid_values_km_json":json.dumps(D,separators=(",",":")),
        "by_distance_json":json.dumps(bd,sort_keys=True,separators=(",",":")),
        "status":"FINITE_GEOMETRY_SYNTHETIC_PASS"
    }

def self_test():
    # Exercise the new semantic validator rather than only constants.
    class Fake:
        OUTPUT_FIELDS=[
            "pair_index","pair_id","parent_signature_sha256","plate_a","plate_b","solution_id_a","solution_id_b",
            "site_a","site_b","legacy_infinity_geometry_status","old_common_positive_infinity_footprint",
            "overlap_interval_count","baseline_length_km_min","baseline_length_km_max","baseline_sweep_max_arcsec",
            "deltat_sources","deltat_uncertainty_qualification","time_distance_cases","cases_with_observable_placement",
            "cases_without_observable_placement","max_grid_level_used","placements","recovered","recovery_failures",
            "available_published_reference_gt2arcsec","height107m_gt2arcsec",
            "observable_distance_grid_values_km_json","by_distance_json","status"]
        DISTANCES_KM=(12756.274,1495978.707,14959787.07);GRID_LEVELS=(9,17,33,65)
        @staticmethod
        def parent_signature(r):return hashlib.sha256(r["pair_id"].encode()).hexdigest()
        @staticmethod
        def parse_intervals(r):return [(1,2)]
        @staticmethod
        def classify(nominal_ok,placements,recovery_fail,reference_fail,height_fail,monthly):
            if not nominal_ok:return "GEOMETRY_REFERENCE_COVERAGE_HOLD"
            if placements<=0:return "NO_JOINT_OBSERVABLE_CASE_FOUND_AT_MAX_RESOLUTION"
            if recovery_fail or reference_fail:return "FINITE_GEOMETRY_SYNTHETIC_PRECISION_HOLD"
            if height_fail:return "FINITE_GEOMETRY_SITE_METADATA_STRESS_HOLD"
            if monthly:return "FINITE_GEOMETRY_SYNTHETIC_PASS_DELTAT_UNCERTAINTY_QUALIFIED"
            return "FINITE_GEOMETRY_SYNTHETIC_PASS"
    parent={"pair_id":"P","plate_a":"1","plate_b":"2","solution_id_a":"10","solution_id_b":"20",
            "site_a":"A","site_b":"B","legacy_infinity_geometry_status":"LEGACY_TANGENT_NONPOSITIVE",
            "old_common_positive_infinity_footprint":"False"}
    q=build_synthetic_valid_row(Fake,parent,1)
    assert validate_row_semantics(Fake,q,parent,1)
    bad=dict(q);bad["recovered"]="4"
    try:validate_row_semantics(Fake,bad,parent,1);raise AssertionError("impossible recovery accounting accepted")
    except ValueError:pass
    bad=dict(q);bad["by_distance_json"]="{bad json"
    try:validate_row_semantics(Fake,bad,parent,1);raise AssertionError("malformed distance JSON accepted")
    except ValueError:pass
    bad=dict(q);bad["status"]="FINITE_GEOMETRY_SYNTHETIC_PRECISION_HOLD"
    try:validate_row_semantics(Fake,bad,parent,1);raise AssertionError("status/accounting mismatch accepted")
    except ValueError:pass
    assert resource_reason({"disk_free":4*1024**3,"avail_phys":9*1024**3,"avail_commit":20*1024**3}) is not None
    assert resource_reason({"disk_free":9*1024**3,"avail_phys":1*1024**3,"avail_commit":20*1024**3}) is not None
    assert resource_reason({"disk_free":9*1024**3,"avail_phys":9*1024**3,"avail_commit":3*1024**3}) is not None
    assert resource_reason({"disk_free":9*1024**3,"avail_phys":9*1024**3,"avail_commit":20*1024**3}) is None
    sm={"private":1*1024**3,"working_set":512*1024**2,"measurement_ok":True,"error":None}
    assert pre_pool_resource_reason({"disk_free":9*1024**3,"avail_phys":3*1024**3,"avail_commit":20*1024**3},sm) is not None
    assert pre_pool_resource_reason({"disk_free":9*1024**3,"avail_phys":12*1024**3,"avail_commit":9*1024**3},sm) is not None
    assert pre_pool_resource_reason({"disk_free":9*1024**3,"avail_phys":12*1024**3,"avail_commit":12*1024**3},sm) is None
    badmem={"private":None,"working_set":None,"measurement_ok":False,
            "error":{"pid":123,"stage":"GetProcessMemoryInfo","windows_error":5}}
    assert pre_pool_resource_reason({"disk_free":9*1024**3,"avail_phys":12*1024**3,
                                     "avail_commit":12*1024**3,"measurement_errors":[]},badmem) is not None
    assert resource_reason({"disk_free":9*1024**3,"avail_phys":12*1024**3,
                            "avail_commit":12*1024**3,
                            "measurement_errors":[{"pid":321,"stage":"OpenProcess","windows_error":5}]}) is not None
    assert should_exit_work_loop("RUNTIME_RESOURCE_HOLD",{}) is True
    assert should_exit_work_loop("RUNTIME_RESOURCE_HOLD",{"x":"future"}) is False
    assert should_exit_work_loop(None,{}) is False
    print("v094x parallel8-r3 execution self-test PASS")
    return 0

def process_done_result(base,item,result):
    ci,start,part,expected,cp=item
    pid,rci,rstart,out=result
    if rci!=ci or rstart!=start+1 or len(out)!=len(part):
        raise RuntimeError(f"worker result structural HOLD for chunk {ci}")
    checkpoint_worker_result(base,cp,expected,out)
    return pid

def cancel_not_started(inflight):
    n=0
    for f in list(inflight):
        if f.cancel():n+=1
    return n

def drain_inflight(base,inflight,failures):
    print(f"DRAIN: collecting {len(inflight)} outstanding futures; no new work will be submitted.",flush=True)
    while inflight:
        done,_=wait(list(inflight),timeout=POLL_SECONDS,return_when=FIRST_COMPLETED)
        if not done:
            s=resource_snapshot()
            print(f"[drain] outstanding={len(inflight)} free={s['disk_free']/1024**3:.2f}GB "
                  f"availRAM={s['avail_phys']/1024**3:.2f}GB availCommit={s['avail_commit']/1024**3:.2f}GB",flush=True)
            continue
        for fut in done:
            item=inflight.pop(fut)
            ci=item[0]
            try:
                res=fut.result()
                pid=process_done_result(base,item,res)
                print(f"[drain] chunk {ci} checkpointed successfully from worker {pid}",flush=True)
            except CancelledError:
                print(f"[drain] chunk {ci} cancelled before start",flush=True)
            except BaseException as e:
                failures.append((ci,repr(e)))
                print(f"[drain] chunk {ci} failed: {e!r}",flush=True)

def write_execution_audit(base,audit):
    p=base.WORK/"parallel8_r3_execution_audit.json"
    write_json_atomic(p,audit)

def run(repo_root,preflight_only=False):
    if not CONTRACT.is_file() or sha(CONTRACT)!=EXPECTED_CONTRACT_SHA:raise SystemExit("parallel8-r3 contract SHA HOLD")
    if not BASE.is_file() or sha(BASE)!=EXPECTED_BASE_SHA:raise SystemExit("Frozen v094x science runner SHA HOLD")

    lock=ControllerLock();lock.acquire()
    try:
        base=load_module(BASE,"v094x_parallel8_r3_controller")
        if base.verify_existing_final():return 0
        geom=base.load_parent_geometry(Path(repo_root))
        sites,refs,polys,overlap=base.load_foundation(Path(repo_root),geom)
        if len(overlap)!=8807:raise SystemExit(f"OVERLAP population HOLD: {len(overlap)}")
        base.CHUNKS.mkdir(parents=True,exist_ok=True)

        # Pre-pool resource gate: this occurs before any child process starts.
        pre=resource_snapshot()
        selfmem=process_memory(os.getpid())
        why=pre_pool_resource_reason(pre,selfmem)
        if why:
            raise SystemExit(f"PRE_POOL_RESOURCE_HOLD: {why}")
        est_phys=max(4*1024**3,int(math.ceil(selfmem["working_set"]*WORKERS*1.15)))
        est_commit=max(6*1024**3,int(math.ceil(selfmem["private"]*WORKERS*1.25)))
        print("="*112)
        print("v094x PARALLEL-8 r2 EXECUTION CONTINUATION")
        print("="*112)
        print(f"Disk free before worker pool:                  {pre['disk_free']/1024**3:.2f} GB")
        print(f"Available physical RAM before worker pool:    {pre['avail_phys']/1024**3:.2f} GB")
        print(f"Available commit before worker pool:          {pre['avail_commit']/1024**3:.2f} GB")
        print(f"Loaded controller private / working set:      {selfmem['private']/1024**3:.2f} / {selfmem['working_set']/1024**3:.2f} GB")
        print(f"Dynamic 8-worker pre-pool RAM requirement:    {est_phys/1024**3:.2f} GB available")
        print(f"Dynamic 8-worker pre-pool commit requirement: {est_commit/1024**3:.2f} GB available")
        # Full validation/adoption of EVERY existing chunk before reuse.
        valid_chunks={};todo=[]
        adopted=invalid=0
        for ci,start in enumerate(range(0,len(overlap),base.CHUNK_SIZE),1):
            part=overlap[start:start+base.CHUNK_SIZE]
            expected=[(start+j+1,r) for j,r in enumerate(part)]
            cp=base.CHUNKS/f"chunk_{ci:04d}_{start+1:05d}_{start+len(part):05d}.csv"
            meta_existed=checkpoint_meta_path(cp).is_file()
            chk=validate_checkpoint(base,cp,expected,adopt_missing_meta=True)
            if isinstance(chk,tuple) and chk and chk[0]=="INVALID":
                print(f"Checkpoint chunk {ci} INVALID: {chk[1]}",flush=True)
                preserve_checkpoint_pair(cp);invalid+=1
                todo.append((ci,start,part,expected,cp))
            elif chk is None:
                todo.append((ci,start,part,expected,cp))
            else:
                valid_chunks[ci]=(cp,chk,expected)
                if not meta_existed:adopted+=1
        print(f"Existing chunks passing full-row validation:  {len(valid_chunks)}")
        print(f"Existing serial chunks adopted with sidecar:  {adopted}")
        print(f"Invalid checkpoints preserved/requeued:       {invalid}")
        print(f"Chunks remaining after validation:            {len(todo)}")
        if len(valid_chunks)<8:raise SystemExit("EQUIVALENCE_GATE_HOLD: fewer than 8 valid existing chunks")

        ex=ProcessPoolExecutor(max_workers=WORKERS,initializer=worker_init,
                               initargs=(str(ROOT),str(Path(repo_root).resolve())))
        failures=[]
        gate_peak_private=gate_peak_ws=0
        gate_min_phys=2**63-1;gate_min_commit=2**63-1;gate_min_disk=2**63-1
        gate_pids=set()
        try:
            # One representative pair from every accepted existing checkpoint.
            gate={}
            for ci in sorted(valid_chunks):
                cp,data,expected=valid_chunks[ci]
                idx,row=expected[0]
                gate[ex.submit(worker_pair,idx,row)]=(ci,idx,row,data[0])

            while gate:
                # Use executor process table to measure all resident workers, not only workers that have completed a gate row.
                try:pool_pids=set(getattr(ex,"_processes",{}).keys())
                except:pool_pids=set()
                snap=resource_snapshot(pool_pids|gate_pids)
                gate_peak_private=max(gate_peak_private,snap["worker_private"])
                gate_peak_ws=max(gate_peak_ws,snap["worker_working_set"])
                gate_min_phys=min(gate_min_phys,snap["avail_phys"])
                gate_min_commit=min(gate_min_commit,snap["avail_commit"])
                gate_min_disk=min(gate_min_disk,snap["disk_free"])
                why=resource_reason(snap)
                if why:
                    cancel_not_started(gate)
                    # Gate futures are representative pairs only; wait/collect without releasing unseen work.
                    raise RuntimeError(f"EQUIVALENCE_GATE_RESOURCE_HOLD: {why}")

                done,_=wait(list(gate),timeout=1.0,return_when=FIRST_COMPLETED)
                for fut in done:
                    ci,idx,parent,serial_row=gate.pop(fut)
                    pid,recomputed=fut.result();gate_pids.add(pid)
                    canon=canonical_row(base,recomputed)
                    diffs=[k for k in base.OUTPUT_FIELDS if str(canon.get(k,""))!=str(serial_row.get(k,""))]
                    if diffs:raise RuntimeError(f"EQUIVALENCE_GATE_HOLD chunk={ci} pair={idx} fields={diffs}")

            pool_pids=set(getattr(ex,"_processes",{}).keys())|gate_pids
            postgate=resource_snapshot(pool_pids)
            why=resource_reason(postgate)
            print(f"Representative equivalence rows PASS:         {len(valid_chunks)}/{len(valid_chunks)}")
            print(f"Resident worker processes:                    {len(pool_pids)}")
            print(f"Gate peak aggregate worker private memory:    {gate_peak_private/1024**3:.2f} GB")
            print(f"Gate peak aggregate worker working set:       {gate_peak_ws/1024**3:.2f} GB")
            print(f"Gate minimum available physical RAM:          {gate_min_phys/1024**3:.2f} GB")
            print(f"Gate minimum available commit:                {gate_min_commit/1024**3:.2f} GB")
            print(f"Gate minimum free disk:                       {gate_min_disk/1024**3:.2f} GB")
            print(f"Post-gate available physical RAM:             {postgate['avail_phys']/1024**3:.2f} GB")
            print(f"Post-gate available commit:                   {postgate['avail_commit']/1024**3:.2f} GB")
            if len(pool_pids)!=WORKERS:
                raise RuntimeError(f"WORKER_POOL_HOLD: expected {WORKERS} resident worker processes, observed {len(pool_pids)}")
            if why:raise RuntimeError(f"POST_GATE_RESOURCE_HOLD: {why}")

            audit={
                "status":"RUNNING","started_utc":datetime.now(timezone.utc).isoformat(),
                "science_runner_sha256":EXPECTED_BASE_SHA,"contract_sha256":EXPECTED_CONTRACT_SHA,
                "controller_sha256":sha(Path(__file__).resolve()),"workers":WORKERS,
                "existing_valid_chunks":len(valid_chunks),"adopted_serial_chunks":adopted,
                "invalid_requeued_chunks":invalid,
                "equivalence_gate_rows":len(valid_chunks),
                "resource_pre_pool":pre,
                "resource_gate":{
                    "peak_worker_private":gate_peak_private,"peak_worker_working_set":gate_peak_ws,
                    "min_avail_phys":gate_min_phys,"min_avail_commit":gate_min_commit,"min_disk_free":gate_min_disk,
                    "post_gate":postgate,
                },
                "failures":[]
            }
            write_execution_audit(base,audit)

            if preflight_only:
                audit["status"]="PREFLIGHT_ONLY_PASS"
                audit["preflight_only_completed_utc"]=datetime.now(timezone.utc).isoformat()
                write_execution_audit(base,audit)
                print("\nPREFLIGHT_ONLY_PASS: checkpoint validation, equivalence and 8-worker resource gate completed.")
                print("No unseen v094x chunks were scheduled.")
                return 0

            # Main bounded queue: at most one submitted chunk per worker.
            remaining=list(todo);inflight={};hold_reason=None;completed_now=0
            interrupted=False

            def schedule():
                nonlocal hold_reason
                while remaining and len(inflight)<MAX_IN_FLIGHT and hold_reason is None:
                    snap=resource_snapshot(pool_pids)
                    why=resource_reason(snap)
                    if why:
                        hold_reason=f"RUNTIME_RESOURCE_HOLD: {why}"
                        break
                    item=remaining.pop(0)
                    ci,start,part,expected,cp=item
                    inflight[ex.submit(worker_chunk,ci,start+1,part)]=item

            try:
                # Initial submission is protected by the same interruption/drain handler.
                schedule()
                while inflight or remaining:
                    if hold_reason is None:
                        snap=resource_snapshot(pool_pids)
                        why=resource_reason(snap)
                        if why:
                            hold_reason=f"RUNTIME_RESOURCE_HOLD: {why}"
                            cancelled=cancel_not_started(inflight)
                            print(f"{hold_reason}; cancelled {cancelled} not-started futures; draining running work.",flush=True)

                    if should_exit_work_loop(hold_reason,inflight):
                        break

                    done,_=wait(list(inflight),timeout=POLL_SECONDS,return_when=FIRST_COMPLETED) if inflight else (set(),set())
                    if not done:
                        if should_exit_work_loop(hold_reason,inflight):
                            break
                        if hold_reason is None:
                            schedule()
                        continue

                    # Process every completion in the batch before reacting to a failure.
                    batch_failure=False
                    for fut in done:
                        item=inflight.pop(fut);ci=item[0]
                        try:
                            res=fut.result()
                            pid=process_done_result(base,item,res)
                            completed_now+=1
                            s=resource_snapshot(pool_pids)
                            print(f"[controller] chunk {ci}/{(len(overlap)+base.CHUNK_SIZE-1)//base.CHUNK_SIZE} "
                                  f"CHECKPOINTED via worker {pid}; new={completed_now}; "
                                  f"unscheduled={len(remaining)}; free={s['disk_free']/1024**3:.2f}GB; "
                                  f"availRAM={s['avail_phys']/1024**3:.2f}GB; availCommit={s['avail_commit']/1024**3:.2f}GB",flush=True)
                        except CancelledError:
                            pass
                        except BaseException as e:
                            failures.append((ci,repr(e)));batch_failure=True
                            print(f"WORKER_FAILURE chunk {ci}: {e!r}",flush=True)
                    if batch_failure and hold_reason is None:
                        hold_reason="WORKER_FAILURE_HOLD"
                        cancelled=cancel_not_started(inflight)
                        print(f"Worker failure detected; cancelled {cancelled} not-started futures; draining successful running work.",flush=True)
                    if hold_reason is None:schedule()

                    if hold_reason is not None and inflight:
                        drain_inflight(base,inflight,failures)
                        inflight.clear()
                    if hold_reason is not None:break

            except KeyboardInterrupt:
                interrupted=True;hold_reason="USER_INTERRUPT_HOLD"
                cancelled=cancel_not_started(inflight)
                print(f"\nCtrl+C received by controller. New submissions stopped; {cancelled} not-started futures cancelled.",flush=True)
                print("Running workers ignore Ctrl+C so successful chunks can be collected before exit.",flush=True)
                drain_inflight(base,inflight,failures);inflight.clear()

            audit["completed_new_chunks"]=completed_now
            audit["remaining_unscheduled_chunks"]=len(remaining)
            audit["failures"]=[{"chunk":c,"error":e} for c,e in failures]
            audit["hold_reason"]=hold_reason
            audit["ended_or_checkpointed_utc"]=datetime.now(timezone.utc).isoformat()
            audit["status"]="HOLD" if hold_reason else "RUNNING"
            write_execution_audit(base,audit)

            if hold_reason:
                raise SystemExit(f"{hold_reason}: valid checkpoints retained; failures={len(failures)}; unscheduled={len(remaining)}")

        finally:
            ex.shutdown(wait=True,cancel_futures=True)

        # Full revalidation of every checkpoint immediately before final frozen aggregation/publication.
        final_valid=0
        for ci,start in enumerate(range(0,len(overlap),base.CHUNK_SIZE),1):
            part=overlap[start:start+base.CHUNK_SIZE]
            expected=[(start+j+1,r) for j,r in enumerate(part)]
            cp=base.CHUNKS/f"chunk_{ci:04d}_{start+1:05d}_{start+len(part):05d}.csv"
            chk=validate_checkpoint(base,cp,expected,adopt_missing_meta=False)
            if isinstance(chk,tuple) or chk is None:
                raise SystemExit(f"FINAL_CHECKPOINT_REPLAY_HOLD chunk {ci}: {chk}")
            final_valid+=1

        audit=json.loads((base.WORK/"parallel8_r3_execution_audit.json").read_text(encoding="utf-8"))
        audit["status"]="ALL_CHECKPOINTS_VALIDATED"
        audit["final_valid_chunks"]=final_valid
        audit["final_checkpoint_validation_utc"]=datetime.now(timezone.utc).isoformat()
        write_execution_audit(base,audit)

        print(f"\nAll {final_valid} chunks passed full semantic/checksum/provenance replay.")
        print("Handing final aggregation and atomic publication to the exact frozen v094x run().")
        rc=base.run(Path(repo_root).resolve())

        audit=json.loads((base.WORK/"parallel8_r3_execution_audit.json").read_text(encoding="utf-8"))
        audit["status"]="COMPLETE"
        audit["completed_utc"]=datetime.now(timezone.utc).isoformat()
        write_execution_audit(base,audit)
        return rc
    finally:
        lock.release()

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--self-test",action="store_true")
    ap.add_argument("--repo-root")
    ap.add_argument("--preflight-only",action="store_true")
    a=ap.parse_args()
    if a.self_test:return self_test()
    if not a.repo_root:raise SystemExit("--repo-root required")
    return run(a.repo_root,preflight_only=a.preflight_only)

if __name__=="__main__":raise SystemExit(main())
