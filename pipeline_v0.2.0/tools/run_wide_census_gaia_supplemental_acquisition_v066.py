#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
import argparse
import csv
import gzip
import hashlib
import io
import json
import math
import shutil
import subprocess
import threading
import time

ROOT=Path.cwd()

FREEZE=ROOT/"research/prospective_freezes/wide_census_gaia_reference_acquisition_contract_v002.json"
V065=ROOT/"results/wide_census_gaia_reference_coverage_audit_v065/wide_census_gaia_reference_coverage_audit_v065.json"
PLAN=ROOT/"results/wide_census_gaia_reference_coverage_audit_v065/wide_census_gaia_supplemental_query_plan_v065.csv"
HPLAN=ROOT/"results/wide_census_gaia_reference_coverage_audit_v065/wide_census_gaia_corrected_hpm_pair_queries_v065.csv"
V064=ROOT/"results/wide_census_gaia_acquisition_v064/wide_census_gaia_acquisition_v064.json"

OUTDIR=ROOT/"results/wide_census_gaia_supplemental_acquisition_v066"
CACHE=OUTDIR/"cache"
OCACHE=CACHE/"ordinary"
HCACHE=CACHE/"hpm"
STATE=OUTDIR/"state_v066.json"
REPORT=OUTDIR/"wide_census_gaia_supplemental_acquisition_v066.json"
MANIFEST=OUTDIR/"wide_census_gaia_supplemental_manifest_v066.csv"

EXPECTED_FREEZE_SHA="458a043dfbdda8dbb853cbae77c269ff17a586c0ddb2fdcf7ac0388ee57ab3fc"
EXPECTED_SUPP=13631
EXPECTED_HPM=33
EXPECTED_NEW_FULL=6980
EXPECTED_ANNULUS=6651

TAP="https://gea.esac.esa.int/tap-server/tap/sync"
UA="historical-transient-pipeline/wide-census-gaia-supplemental-v066"
MAXREC=50000
MIN_CELL_DEG=0.03125
BASE_CELL_DEG=0.25
MAX_ATTEMPTS=6
DEFAULT_WORKERS=2
GLOBAL_REQUEST_START_INTERVAL_S=0.75
LOW_DISK_ABORT_GIB=12.0

COLS=[
 "source_id","ra","dec","ref_epoch","ra_error","dec_error",
 "parallax","parallax_error","pm","pmra","pmdec","pmra_error","pmdec_error",
 "radial_velocity","phot_g_mean_mag","bp_rp","ruwe","astrometric_params_solved"
]

_counter_lock=threading.Lock()
_counter={"network_calls":0}
_print_lock=threading.Lock()

def log(*args,**kwargs):
    with _print_lock:
        print(*args,**kwargs,flush=True)

class GlobalRateLimiter:
    def __init__(self, interval_s):
        self.interval=float(interval_s)
        self.lock=threading.Lock()
        self.next_allowed=0.0
    def wait(self):
        with self.lock:
            now=time.monotonic()
            t=max(now,self.next_allowed)
            self.next_allowed=t+self.interval
        delay=t-time.monotonic()
        if delay>0: time.sleep(delay)

RATE=GlobalRateLimiter(GLOBAL_REQUEST_START_INTERVAL_S)

def sha_file(p):
    h=hashlib.sha256()
    with p.open("rb") as f:
        for b in iter(lambda:f.read(1024*1024),b""):h.update(b)
    return h.hexdigest()

def sha_bytes(b):
    return hashlib.sha256(b).hexdigest()

def read_csv(p):
    with p.open(newline="",encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))

def write_json(p,obj):
    p.parent.mkdir(parents=True,exist_ok=True)
    t=p.with_suffix(p.suffix+".tmp")
    t.write_text(json.dumps(obj,indent=2,sort_keys=True,default=str)+"\n",encoding="utf-8")
    t.replace(p)

def write_csv(p,rows,fields):
    p.parent.mkdir(parents=True,exist_ok=True)
    t=p.with_suffix(p.suffix+".tmp")
    with t.open("w",newline="",encoding="utf-8") as f:
        w=csv.DictWriter(f,fieldnames=fields,extrasaction="ignore")
        w.writeheader();w.writerows(rows)
    t.replace(p)

def parse_csv_bytes(b):
    text=b.decode("utf-8-sig",errors="strict")
    if "<VOTABLE" in text[:1000] or "QUERY_STATUS" in text[:2000]:
        raise RuntimeError("Gaia TAP returned VOTable/error instead of CSV: "+text[:700].replace("\n"," "))
    rdr=csv.DictReader(io.StringIO(text))
    fields={str(x).strip().lower() for x in (rdr.fieldnames or [])}
    if "source_id" not in fields:
        raise RuntimeError("Gaia CSV missing source_id header")
    n=0
    for r in rdr:
        if str(r.get("source_id","")).strip():n+=1
    return n

def check_disk():
    free=shutil.disk_usage(ROOT).free/(1024**3)
    if free<LOW_DISK_ABORT_GIB:
        raise RuntimeError(
            f"LOW_DISK_SPACE_GUARD: {free:.2f} GiB free < {LOW_DISK_ABORT_GIB:.1f} GiB. "
            "Checkpointed cache is safe; free space before resuming."
        )
    return free

def curl_query(adql):
    curl=shutil.which("curl.exe") or shutil.which("curl")
    if not curl:raise RuntimeError("curl.exe/curl unavailable; refusing to weaken TLS")
    last=None
    for attempt in range(1,MAX_ATTEMPTS+1):
        try:
            check_disk()
            RATE.wait()
            with _counter_lock:
                _counter["network_calls"]+=1
            cmd=[
                curl,"--fail","--silent","--show-error","--location",
                "--connect-timeout","30","--max-time","300",
                "--user-agent",UA,
                "--data-urlencode","REQUEST=doQuery",
                "--data-urlencode","LANG=ADQL",
                "--data-urlencode","FORMAT=csv",
                "--data-urlencode",f"MAXREC={MAXREC}",
                "--data-urlencode",f"QUERY={adql}",
                TAP
            ]
            cp=subprocess.run(cmd,capture_output=True,timeout=330)
            if cp.returncode!=0:
                err=cp.stderr.decode("utf-8",errors="replace") if isinstance(cp.stderr,(bytes,bytearray)) else str(cp.stderr)
                raise RuntimeError(f"curl exit {cp.returncode}: {err[:800]}")
            b=cp.stdout
            n=parse_csv_bytes(b)
            return b,n,attempt
        except Exception as e:
            last=e
            log(f"      transport attempt {attempt}/{MAX_ATTEMPTS} failed: {e}")
            if attempt<MAX_ATTEMPTS:
                time.sleep(min(60.0,2.0**attempt))
    raise RuntimeError(f"Gaia TAP failed after {MAX_ATTEMPTS} attempts: {last}")

def cone_expr(ra,dec,radius):
    return (
        "CONTAINS(POINT('ICRS',ra,dec),"
        f"CIRCLE('ICRS',{ra:.12f},{dec:.12f},{radius:.12f}))"
    )

def cone_adql(ra,dec,radius,pm_min=None):
    cols=", ".join(COLS)
    where=f"1={cone_expr(ra,dec,radius)}"
    if pm_min is not None:
        where=f"pm >= {float(pm_min):.6f} AND {where}"
    return f"SELECT {cols} FROM gaiadr3.gaia_source WHERE {where}"

def annulus_adql(ra,dec,inner,outer):
    cols=", ".join(COLS)
    return (
        f"SELECT {cols} FROM gaiadr3.gaia_source WHERE "
        f"1={cone_expr(ra,dec,outer)} AND 0={cone_expr(ra,dec,inner)}"
    )

def angsep_deg(ra1,dec1,ra2,dec2):
    r1,r2=math.radians(ra1),math.radians(ra2)
    d1,d2=math.radians(dec1),math.radians(dec2)
    c=math.sin(d1)*math.sin(d2)+math.cos(d1)*math.cos(d2)*math.cos(r1-r2)
    return math.degrees(math.acos(max(-1,min(1,c))))

def bounds_for_base(ira,idec):
    return (
        ira*BASE_CELL_DEG,(ira+1)*BASE_CELL_DEG,
        -90+idec*BASE_CELL_DEG,-90+(idec+1)*BASE_CELL_DEG,
    )

def child_bounds(bounds,q):
    r0,r1,d0,d1=bounds
    rm=(r0+r1)/2;dm=(d0+d1)/2
    return {
        0:(r0,rm,d0,dm),1:(rm,r1,d0,dm),
        2:(r0,rm,dm,d1),3:(rm,r1,dm,d1),
    }[q]

def geom(bounds,margin_arcsec):
    r0,r1,d0,d1=bounds
    ra=((r0+r1)/2)%360.0
    dec=(d0+d1)/2
    corners=[(r0,d0),(r1,d0),(r0,d1),(r1,d1)]
    far=max(angsep_deg(ra,dec,x%360,y) for x,y in corners)
    return ra,dec,far+margin_arcsec/3600.0

def gz_paths(kind,key):
    base=OCACHE if kind=="ordinary" else HCACHE
    return base/(key+".csv.gz"),base/(key+".meta.json")

def write_gzip_exact(path,b):
    path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_suffix(path.suffix+".tmp")
    with tmp.open("wb") as raw:
        with gzip.GzipFile(filename="",mode="wb",fileobj=raw,mtime=0,compresslevel=6) as g:
            g.write(b)
    tmp.replace(path)

def verify_gzip(path,expected_uncompressed_sha,expected_rows):
    h=hashlib.sha256();chunks=[]
    with gzip.open(path,"rb") as f:
        for b in iter(lambda:f.read(1024*1024),b""):
            h.update(b)
    if h.hexdigest()!=expected_uncompressed_sha:
        raise RuntimeError(f"gzip cache uncompressed SHA mismatch: {path}")
    # Row parsing was already done at acquisition. For integrity scans, SHA is authoritative.
    return True

def save_complete(kind,key,adql,b,n,attempt,extra):
    dp,mp=gz_paths(kind,key)
    write_gzip_exact(dp,b)
    m={
        "status":"COMPLETE","adql":adql,"rows":n,
        "uncompressed_sha256":sha_bytes(b),
        "compressed_sha256":sha_file(dp),
        "uncompressed_bytes":len(b),"compressed_bytes":dp.stat().st_size,
        "attempt":attempt,"transport":"curl_verified_https",
        "tls_verification_disabled":False,
        "completed_at_utc":datetime.now(timezone.utc).isoformat(),
        **extra
    }
    write_json(mp,m)
    return m

def cached_complete(kind,key,adql):
    dp,mp=gz_paths(kind,key)
    if not mp.is_file():return None
    m=json.loads(mp.read_text(encoding="utf-8"))
    if m.get("adql")!=adql:
        raise RuntimeError(f"REFUSING cached ADQL changed for {key}")
    if m.get("status")=="COMPLETE":
        if not dp.is_file():raise RuntimeError(f"missing compressed cache for {key}")
        if sha_file(dp)!=m.get("compressed_sha256"):
            raise RuntimeError(f"compressed cache SHA mismatch for {key}")
        return m
    return m

def full_leaf(task,bounds,path,depth):
    ira=int(task["base_cell_ira"]);idec=int(task["base_cell_idec"])
    margin=float(task["corrected_margin_arcsec"])
    size=bounds[1]-bounds[0]
    ra,dec,radius=geom(bounds,margin)
    key=f"supp_{int(task['supplemental_query_index']):05d}_cell_{ira:04d}_{idec:04d}_d{depth}_{path or 'root'}"
    adql=cone_adql(ra,dec,radius,None)
    dp,mp=gz_paths("ordinary",key)

    if mp.is_file():
        old=json.loads(mp.read_text(encoding="utf-8"))
        if old.get("adql")!=adql:raise RuntimeError(f"REFUSING cached ADQL changed for {key}")
        if old.get("status")=="COMPLETE":
            if not dp.is_file() or sha_file(dp)!=old.get("compressed_sha256"):
                raise RuntimeError(f"cache integrity failure {key}")
            return {"leaf_queries":1,"rows":int(old["rows"]),"compressed_bytes":int(old["compressed_bytes"]),"network_new":0}
        if old.get("status")=="SUBDIVIDED":
            total={"leaf_queries":0,"rows":0,"compressed_bytes":0,"network_new":0}
            for q in range(4):
                r=full_leaf(task,child_bounds(bounds,q),path+str(q),depth+1)
                for k in total:total[k]+=r[k]
            return total

    log(f"    query {key}: r={radius:.5f} deg")
    b,n,attempt=curl_query(adql)
    if n>=MAXREC:
        if size/2 < MIN_CELL_DEG-1e-12:
            raise RuntimeError(f"DENSITY_OVERFLOW_AT_MIN_CELL {key}: rows={n}, size={size:.6f} deg")
        cap=OCACHE/(key+".maxrec.csv.gz")
        write_gzip_exact(cap,b)
        write_json(mp,{
            "status":"SUBDIVIDED","adql":adql,"rows_at_maxrec":n,
            "maxrec_uncompressed_sha256":sha_bytes(b),
            "maxrec_compressed_sha256":sha_file(cap),
            "cell_size_deg":size,
            "subdivision_reason":"response reached MAXREC; transport completeness only",
        })
        log(f"      MAXREC reached ({n}); subdividing transport cell")
        total={"leaf_queries":0,"rows":0,"compressed_bytes":0,"network_new":1}
        for q in range(4):
            r=full_leaf(task,child_bounds(bounds,q),path+str(q),depth+1)
            for k in total:total[k]+=r[k]
        return total

    m=save_complete("ordinary",key,adql,b,n,attempt,{
        "mode":"FULL_NEW_BASE_CELL",
        "supplemental_query_index":int(task["supplemental_query_index"]),
        "base_cell_ira":ira,"base_cell_idec":idec,
        "depth":depth,"path":path or "root",
        "query_ra_deg":ra,"query_dec_deg":dec,"query_radius_deg":radius,
    })
    return {"leaf_queries":1,"rows":n,"compressed_bytes":int(m["compressed_bytes"]),"network_new":1}

def process_ordinary(task):
    mode=task["mode"]
    idx=int(task["supplemental_query_index"])
    if mode=="MARGIN_ANNULUS_EXISTING_LEAF":
        ra=float(task["query_ra_deg"]);dec=float(task["query_dec_deg"])
        inner=float(task["inner_radius_deg"]);outer=float(task["outer_radius_deg"])
        key=f"supp_{idx:05d}_annulus_{task['leaf_key']}"
        adql=annulus_adql(ra,dec,inner,outer)
        old=cached_complete("ordinary",key,adql)
        if old and old.get("status")=="COMPLETE":
            return idx,{"leaf_queries":1,"rows":int(old["rows"]),"compressed_bytes":int(old["compressed_bytes"]),"network_new":0}
        log(f"[supp {idx}/{EXPECTED_SUPP}] annulus {task['leaf_key']} {inner:.5f}->{outer:.5f} deg")
        b,n,attempt=curl_query(adql)
        if n>=MAXREC:
            raise RuntimeError(
                f"ANNULUS_MAXREC_OPERATIONAL_BLOCKER {key}: rows={n}; "
                "v065 freeze forbids interpreting a capped annulus."
            )
        m=save_complete("ordinary",key,adql,b,n,attempt,{
            "mode":mode,"supplemental_query_index":idx,
            "base_cell_ira":int(task["base_cell_ira"]),
            "base_cell_idec":int(task["base_cell_idec"]),
            "leaf_key":task["leaf_key"],
            "inner_radius_deg":inner,"outer_radius_deg":outer,
        })
        return idx,{"leaf_queries":1,"rows":n,"compressed_bytes":int(m["compressed_bytes"]),"network_new":1}

    if mode=="FULL_NEW_BASE_CELL":
        ira=int(task["base_cell_ira"]);idec=int(task["base_cell_idec"])
        log(f"[supp {idx}/{EXPECTED_SUPP}] full cell {ira},{idec}")
        return idx,full_leaf(task,bounds_for_base(ira,idec),"",0)

    raise RuntimeError(f"REFUSING unknown supplemental mode {mode!r}")

def process_hpm(r):
    idx=int(r["pair_index"])
    ra=float(r["query_ra_deg"]);dec=float(r["query_dec_deg"])
    radius=float(r["query_radius_deg"]);pm=float(r["pm_min_masyr"])
    key=f"hpm_pair_{idx:02d}"
    adql=cone_adql(ra,dec,radius,pm)
    old=cached_complete("hpm",key,adql)
    if old and old.get("status")=="COMPLETE":
        return idx,{"rows":int(old["rows"]),"compressed_bytes":int(old["compressed_bytes"]),"network_new":0}
    log(f"[HPM pair {idx}/33] r={radius:.5f} deg pm>={pm:.0f}")
    b,n,attempt=curl_query(adql)
    if n>=MAXREC:
        raise RuntimeError(f"HPM_MAXREC_OPERATIONAL_BLOCKER pair {idx}: rows={n}")
    m=save_complete("hpm",key,adql,b,n,attempt,{
        "pair_index":idx,"query_ra_deg":ra,"query_dec_deg":dec,
        "query_radius_deg":radius,"pm_min_masyr":pm,
    })
    return idx,{"rows":n,"compressed_bytes":int(m["compressed_bytes"]),"network_new":1}

def ordinary_task_complete(task):
    idx=int(task["supplemental_query_index"])
    mode=task["mode"]
    if mode=="MARGIN_ANNULUS_EXISTING_LEAF":
        ra=float(task["query_ra_deg"]);dec=float(task["query_dec_deg"])
        inner=float(task["inner_radius_deg"]);outer=float(task["outer_radius_deg"])
        key=f"supp_{idx:05d}_annulus_{task['leaf_key']}"
        adql=annulus_adql(ra,dec,inner,outer)
        old=cached_complete("ordinary",key,adql)
        if old and old.get("status")=="COMPLETE":
            return True,1,int(old["rows"]),int(old["compressed_bytes"])
        return False,0,0,0

    ira=int(task["base_cell_ira"]);idec=int(task["base_cell_idec"])
    margin=float(task["corrected_margin_arcsec"])
    def walk(bounds,path,depth):
        ra,dec,radius=geom(bounds,margin)
        key=f"supp_{idx:05d}_cell_{ira:04d}_{idec:04d}_d{depth}_{path or 'root'}"
        adql=cone_adql(ra,dec,radius,None)
        dp,mp=gz_paths("ordinary",key)
        if not mp.is_file():return False,0,0,0
        m=json.loads(mp.read_text(encoding="utf-8"))
        if m.get("adql")!=adql:raise RuntimeError(f"cache ADQL changed {key}")
        if m.get("status")=="COMPLETE":
            if not dp.is_file() or sha_file(dp)!=m.get("compressed_sha256"):
                raise RuntimeError(f"cache integrity failure {key}")
            return True,1,int(m["rows"]),int(m["compressed_bytes"])
        if m.get("status")=="SUBDIVIDED":
            ok=True;leaves=rows=cb=0
            for q in range(4):
                a,b,c,d=walk(child_bounds(bounds,q),path+str(q),depth+1)
                ok=ok and a;leaves+=b;rows+=c;cb+=d
            return ok,leaves,rows,cb
        return False,0,0,0
    return walk(bounds_for_base(ira,idec),"",0)

def scan_all(plan,hplan):
    manifest=[]
    done=leaves=rows=cb=0
    for t in plan:
        ok,l,r,b=ordinary_task_complete(t)
        if ok:done+=1
        leaves+=l;rows+=r;cb+=b
        manifest.append({
            "supplemental_query_index":t["supplemental_query_index"],
            "mode":t["mode"],
            "base_cell_ira":t["base_cell_ira"],
            "base_cell_idec":t["base_cell_idec"],
            "leaf_key":t["leaf_key"],
            "status":"COMPLETE" if ok else "PENDING",
            "resolved_leaf_queries":l,
            "cached_rows":r,
            "compressed_bytes":b,
        })
    hdone=hrows=hcb=0
    for r in hplan:
        idx=int(r["pair_index"])
        ra=float(r["query_ra_deg"]);dec=float(r["query_dec_deg"])
        radius=float(r["query_radius_deg"]);pm=float(r["pm_min_masyr"])
        key=f"hpm_pair_{idx:02d}"
        adql=cone_adql(ra,dec,radius,pm)
        old=cached_complete("hpm",key,adql)
        if old and old.get("status")=="COMPLETE":
            hdone+=1;hrows+=int(old["rows"]);hcb+=int(old["compressed_bytes"])
    return manifest,done,leaves,rows,cb,hdone,hrows,hcb

def write_state(status,done,leaves,rows,cb,hdone,hrows,hcb,total,workers):
    write_json(STATE,{
        "status":status,
        "ordinary_root_complete":done,"ordinary_root_total":total,
        "ordinary_resolved_leaf_queries":leaves,
        "ordinary_cached_rows_including_overlap":rows,
        "ordinary_compressed_bytes":cb,
        "hpm_complete":hdone,"hpm_total":EXPECTED_HPM,
        "hpm_cached_rows":hrows,"hpm_compressed_bytes":hcb,
        "network_calls_this_invocation":_counter["network_calls"],
        "workers":workers,
        "global_request_start_interval_s":GLOBAL_REQUEST_START_INTERVAL_S,
        "updated_at_utc":datetime.now(timezone.utc).isoformat(),
    })

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--workers",type=int,default=DEFAULT_WORKERS)
    ap.add_argument("--max-new",type=int,default=None,
                    help="optional smoke-test cap on successful root tasks, not raw HTTP calls")
    args=ap.parse_args()
    if args.workers not in (1,2,3,4,5,6,7,8):
        raise RuntimeError("REFUSING: v066 supports only 1 to 8 workers; default remains 2 and operational maximum is 8")

    print("="*136)
    print("WIDE CENSUS — SUPPLEMENTAL GAIA DR3 ACQUISITION v066")
    print("="*136)
    print("Gaia TAP catalogue metadata only. NO PIXELS. NO DETECTOR. NO REGISTRATION. NO CANDIDATE MUTATION.")
    print(f"Workers: {args.workers} (default 2; max 8) | GLOBAL minimum request-start spacing: {GLOBAL_REQUEST_START_INTERVAL_S:.2f}s")
    print("Cache: lossless gzip; SHA256 of both uncompressed response and compressed file.")
    print(f"Low-disk abort guard: {LOW_DISK_ABORT_GIB:.1f} GiB free.\n")

    for p in (FREEZE,V065,PLAN,HPLAN,V064):
        if not p.is_file():raise RuntimeError(f"REFUSING missing prerequisite {p}")
    if sha_file(FREEZE)!=EXPECTED_FREEZE_SHA:
        raise RuntimeError("REFUSING: v065 corrective freeze SHA changed")
    v65=json.loads(V065.read_text(encoding="utf-8"))
    if v65.get("status")!="COMPLETE":raise RuntimeError("REFUSING v065 incomplete")
    v64=json.loads(V064.read_text(encoding="utf-8"))
    if v64.get("status")!="COMPLETE":raise RuntimeError("REFUSING v064 incomplete")

    plan=read_csv(PLAN);hplan=read_csv(HPLAN)
    if len(plan)!=EXPECTED_SUPP or len(hplan)!=EXPECTED_HPM:
        raise RuntimeError(f"REFUSING plan counts ordinary={len(plan)} hpm={len(hplan)}")
    modes={}
    for r in plan:modes[r["mode"]]=modes.get(r["mode"],0)+1
    if modes.get("FULL_NEW_BASE_CELL")!=EXPECTED_NEW_FULL or modes.get("MARGIN_ANNULUS_EXISTING_LEAF")!=EXPECTED_ANNULUS:
        raise RuntimeError(f"REFUSING mode counts changed: {modes}")

    for d in (OUTDIR,CACHE,OCACHE,HCACHE):d.mkdir(parents=True,exist_ok=True)
    free=check_disk()
    print(f"Free disk at start: {free:.2f} GiB")

    print("Scanning/verifying existing v066 cache once ...",flush=True)
    manifest,done,leaves,rows,cb,hdone,hrows,hcb=scan_all(plan,hplan)
    print(
        f"RESUME CACHE: ordinary roots {done}/{len(plan)} | leaves {leaves} | "
        f"HPM {hdone}/{len(hplan)} | compressed {(cb+hcb)/(1024**3):.2f} GiB",
        flush=True
    )

    pending=[r for r,m in zip(plan,manifest) if m["status"]!="COMPLETE"]
    completed_this_run=0
    checkpoint_count=0
    root_done_runtime=done
    hpm_done_runtime=hdone

    def checkpoint_light():
        # Lightweight checkpoint only: never rescan/hash the whole cache here.
        # Exact leaf/row/byte totals remain those from the startup integrity scan
        # until the final full reconciliation. Every newly written response has
        # already been individually SHA-recorded.
        write_json(STATE,{
            "status":"IN_PROGRESS_CHECKPOINTED",
            "ordinary_root_complete":root_done_runtime,
            "ordinary_root_total":len(plan),
            "ordinary_resolved_leaf_queries_at_last_full_scan":leaves,
            "ordinary_cached_rows_at_last_full_scan":rows,
            "ordinary_compressed_bytes_at_last_full_scan":cb,
            "hpm_complete":hpm_done_runtime,
            "hpm_total":len(hplan),
            "hpm_cached_rows_at_last_full_scan":hrows,
            "hpm_compressed_bytes_at_last_full_scan":hcb,
            "network_calls_this_invocation":_counter["network_calls"],
            "workers":args.workers,
            "global_request_start_interval_s":GLOBAL_REQUEST_START_INTERVAL_S,
            "checkpoint_kind":"lightweight_no_global_cache_rescan",
            "updated_at_utc":datetime.now(timezone.utc).isoformat(),
        })
        log(
            f"CHECKPOINT ordinary {root_done_runtime}/{len(plan)} | "
            f"HPM {hpm_done_runtime}/{len(hplan)} "
            "(lightweight; no global cache rescan)"
        )

    # Bounded future queue: never hold thousands of futures or create a burst.
    with ThreadPoolExecutor(max_workers=args.workers,thread_name_prefix="gaia-v066") as ex:
        iterator=iter(pending)
        inflight={}
        stop_submit=False

        def submit_one():
            nonlocal stop_submit
            if stop_submit:return False
            try:t=next(iterator)
            except StopIteration:return False
            fut=ex.submit(process_ordinary,t)
            inflight[fut]=t
            return True

        for _ in range(args.workers):
            if not submit_one():break

        while inflight:
            finished,_=wait(list(inflight),return_when=FIRST_COMPLETED)
            for fut in finished:
                t=inflight.pop(fut)
                idx,stats=fut.result()  # exception is intentionally fatal/operational
                completed_this_run+=1
                root_done_runtime+=1
                checkpoint_count+=1
                log(
                    f"      complete supp {idx}: leaves={stats['leaf_queries']} rows={stats['rows']:,} "
                    f"compressed={stats['compressed_bytes']/(1024**2):.1f} MiB"
                )
                if checkpoint_count>=50:
                    checkpoint_light();checkpoint_count=0
                if args.max_new is not None and completed_this_run>=args.max_new:
                    stop_submit=True
                if not stop_submit:
                    submit_one()

    # If smoke-test stopped early, finalize checkpoint without starting HPM.
    if args.max_new is not None and completed_this_run>=args.max_new and len(pending)>completed_this_run:
        checkpoint_light()
        log("\nSMOKE/BOUNDED RUN COMPLETE: ordinary acquisition remains checkpointed.")
    else:
        if checkpoint_count:checkpoint_light()

        # 33 HPM queries: same bounded two-worker transport path.
        manifest,done,leaves,rows,cb,hdone,hrows,hcb=scan_all(plan,hplan)
        pending_h=[]
        for r in hplan:
            idx=int(r["pair_index"])
            ra=float(r["query_ra_deg"]);dec=float(r["query_dec_deg"])
            radius=float(r["query_radius_deg"]);pm=float(r["pm_min_masyr"])
            key=f"hpm_pair_{idx:02d}"
            adql=cone_adql(ra,dec,radius,pm)
            old=cached_complete("hpm",key,adql)
            if not (old and old.get("status")=="COMPLETE"):
                pending_h.append(r)

        with ThreadPoolExecutor(max_workers=args.workers,thread_name_prefix="gaia-v066-hpm") as ex:
            futures=[ex.submit(process_hpm,r) for r in pending_h]
            for n,f in enumerate(futures,1):
                idx,stats=f.result()
                hpm_done_runtime+=1
                log(f"      complete HPM pair {idx}: rows={stats['rows']}")
                if n%5==0:
                    checkpoint_light()

    log("\nFINAL INTEGRITY SCAN: verifying v066 cache ...")
    manifest,done,leaves,rows,cb,hdone,hrows,hcb=scan_all(plan,hplan)
    write_csv(MANIFEST,manifest,[
        "supplemental_query_index","mode","base_cell_ira","base_cell_idec","leaf_key",
        "status","resolved_leaf_queries","cached_rows","compressed_bytes"
    ])

    complete=(done==len(plan) and hdone==len(hplan))
    status="COMPLETE" if complete else "IN_PROGRESS_CHECKPOINTED"
    rep={
        "status":status,
        "analysis_kind":"wide_census_supplemental_gaia_dr3_acquisition_v066",
        "updated_at_utc":datetime.now(timezone.utc).isoformat(),
        "guards":{
            "network_access":True,"science_pixels_read":False,"transient_detector_rerun":False,
            "astrometric_registration_run":False,"candidate_state_mutation":False,
            "science_policy_changed":False,
        },
        "inputs":{
            "v002_corrective_freeze_sha256":sha_file(FREEZE),
            "v065_report_sha256":sha_file(V065),
            "supplemental_plan_sha256":sha_file(PLAN),
            "corrected_hpm_plan_sha256":sha_file(HPLAN),
            "v064_report_sha256":sha_file(V064),
        },
        "transport":{
            "workers":args.workers,
            "default_workers":DEFAULT_WORKERS,
            "maximum_workers_allowed":8,
            "global_request_start_interval_s":GLOBAL_REQUEST_START_INTERVAL_S,
            "cache_encoding":"gzip lossless; deterministic mtime=0",
            "low_disk_abort_gib":LOW_DISK_ABORT_GIB,
            "ordinary_annulus_maxrec_policy":"operational blocker per v065 freeze",
            "new_full_cell_maxrec_policy":"recursive quarter-cell subdivision to 0.03125 deg",
        },
        "progress":{
            "ordinary_root_complete":done,"ordinary_root_total":len(plan),
            "ordinary_resolved_leaf_queries":leaves,
            "ordinary_cached_rows_including_overlap":rows,
            "ordinary_compressed_bytes":cb,
            "hpm_complete":hdone,"hpm_total":len(hplan),
            "hpm_cached_rows":hrows,"hpm_compressed_bytes":hcb,
            "network_calls_this_invocation":_counter["network_calls"],
        },
        "individual_candidate_dispositions":"NONE",
        "science_positives":0,
        "next_stage":(
            "After COMPLETE: offline pair-wise Gaia source_id deduplication across v064+v066, "
            "pair-epoch propagation, reciprocal-nearest candidate/Gaia association, "
            "common-reference construction and frozen primary/sparse registration."
        ),
    }
    write_json(REPORT,rep);write_json(STATE,rep)

    print("\n"+"="*136)
    print("SUPPLEMENTAL GAIA ACQUISITION",status)
    print("="*136)
    print(f"Ordinary supplemental roots complete: {done}/{len(plan)}")
    print(f"Resolved ordinary leaf queries:       {leaves}")
    print(f"Cached ordinary rows:                 {rows:,}")
    print(f"HPM pair queries complete:            {hdone}/{len(hplan)}")
    print(f"Cached HPM rows:                      {hrows:,}")
    print(f"v066 compressed cache size:           {(cb+hcb)/(1024**3):.2f} GiB")
    print(f"Free disk now:                        {shutil.disk_usage(ROOT).free/(1024**3):.2f} GiB")
    print(f"Network calls this invocation:        {_counter['network_calls']}")
    print("Astrometric registrations run:        0")
    print("Candidate dispositions:               NONE")
    print("SCIENCE POSITIVES:                    0")
    print("STAGE STATUS:",status)

if __name__=="__main__":
    main()
