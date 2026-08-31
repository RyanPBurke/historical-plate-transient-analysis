from __future__ import annotations

from pathlib import Path
from datetime import datetime, timezone
from urllib.parse import urlencode
import argparse
import csv
import hashlib
import io
import json
import math
import shutil
import subprocess
import time

ROOT=Path.cwd()
PLAN=ROOT/"results/wide_census_gaia_query_dedup_v063a/wide_census_gaia_unique_ordinary_query_cells_v063a.csv"
HPLAN=ROOT/"results/wide_census_gaia_query_dedup_v063a/wide_census_gaia_unique_hpm_queries_v063a.csv"
AUDIT=ROOT/"results/wide_census_gaia_query_dedup_v063a/wide_census_gaia_query_dedup_v063a.json"
FREEZE=ROOT/"research/prospective_freezes/wide_census_gaia_reference_acquisition_contract_v001.json"

OUT=ROOT/"results/wide_census_gaia_acquisition_v064"
CACHE=OUT/"cache"
OCACHE=CACHE/"ordinary"
HCACHE=CACHE/"hpm"
STATE=OUT/"state_v064.json"
REPORT=OUT/"wide_census_gaia_acquisition_v064.json"
MANIFEST=OUT/"wide_census_gaia_acquisition_manifest_v064.csv"

EXPECTED_FREEZE_SHA="7a182349455a814423d68411d49aa7640dacdbe8dd6bafd5a5ec747c64b097fc"
TAP="https://gea.esac.esa.int/tap-server/tap/sync"
UA="historical-transient-pipeline/wide-census-gaia-acquisition-v064"
MAXREC=50000
MIN_CELL_DEG=0.03125
SUCCESS_PAUSE_S=0.75
MAX_ATTEMPTS=6

COLS=[
 "source_id","ra","dec","ref_epoch","ra_error","dec_error",
 "parallax","parallax_error","pm","pmra","pmdec","pmra_error","pmdec_error",
 "radial_velocity","phot_g_mean_mag","bp_rp","ruwe","astrometric_params_solved"
]


def sha_bytes(b):
    return hashlib.sha256(b).hexdigest()


def sha_file(p):
    h=hashlib.sha256()
    with p.open("rb") as f:
        for b in iter(lambda:f.read(1024*1024),b""):h.update(b)
    return h.hexdigest()


def read_csv(p):
    with p.open(newline="",encoding="utf-8-sig") as f:return list(csv.DictReader(f))


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


def parse_csv(b):
    text=b.decode("utf-8-sig",errors="strict")
    if "<VOTABLE" in text[:1000] or "QUERY_STATUS" in text[:2000]:
        raise RuntimeError("Gaia TAP returned VOTable/error instead of CSV: "+text[:700].replace("\n"," "))
    rdr=csv.DictReader(io.StringIO(text))
    if not rdr.fieldnames or "source_id" not in {str(x).strip().lower() for x in rdr.fieldnames}:
        raise RuntimeError("Gaia CSV missing source_id header")
    n=0
    for r in rdr:
        if str(r.get("source_id","")).strip(): n+=1
    return n


def curl_query(adql,maxrec=MAXREC):
    curl=shutil.which("curl.exe") or shutil.which("curl")
    if not curl: raise RuntimeError("curl.exe/curl unavailable; refusing to weaken TLS")
    cmd=[
        curl,"--fail","--silent","--show-error","--location",
        "--connect-timeout","30","--max-time","240",
        "--user-agent",UA,
        "--data-urlencode","REQUEST=doQuery",
        "--data-urlencode","LANG=ADQL",
        "--data-urlencode","FORMAT=csv",
        "--data-urlencode",f"MAXREC={maxrec}",
        "--data-urlencode",f"QUERY={adql}",
        TAP,
    ]
    cp=subprocess.run(cmd,capture_output=True,timeout=270)
    if cp.returncode!=0:
        err=cp.stderr.decode("utf-8",errors="replace") if isinstance(cp.stderr,(bytes,bytearray)) else str(cp.stderr)
        raise RuntimeError(f"curl exit {cp.returncode}: {err[:800]}")
    b=cp.stdout
    n=parse_csv(b)
    return b,n


def query_retry(adql):
    last=None
    for attempt in range(1,MAX_ATTEMPTS+1):
        try:
            b,n=curl_query(adql)
            return b,n,attempt
        except Exception as e:
            last=e
            print(f"      transport attempt {attempt}/{MAX_ATTEMPTS} failed: {e}",flush=True)
            if attempt<MAX_ATTEMPTS: time.sleep(min(60,2**attempt))
    raise RuntimeError(f"Gaia TAP failed after {MAX_ATTEMPTS} attempts: {last}")


def cone_adql(ra,dec,radius_deg,hpm_min=None):
    cols=", ".join(COLS)
    pm="" if hpm_min is None else f"pm >= {float(hpm_min):.6f} AND "
    return (
        f"SELECT {cols} FROM gaiadr3.gaia_source WHERE {pm}"
        f"1=CONTAINS(POINT('ICRS',ra,dec),"
        f"CIRCLE('ICRS',{ra:.12f},{dec:.12f},{radius_deg:.12f}))"
    )


def angsep(ra1,dec1,ra2,dec2):
    r1,r2=math.radians(ra1),math.radians(ra2)
    d1,d2=math.radians(dec1),math.radians(dec2)
    c=math.sin(d1)*math.sin(d2)+math.cos(d1)*math.cos(d2)*math.cos(r1-r2)
    return math.degrees(math.acos(max(-1,min(1,c))))


def geom_from_bounds(ra_lo,ra_hi,dec_lo,dec_hi,margin_arcsec):
    # Current historical fields are well away from RA wrap in individual cells;
    # keep unwrapped bounds for child subdivision, then normalize center RA.
    ra=(ra_lo+ra_hi)/2
    dec=(dec_lo+dec_hi)/2
    corners=[(ra_lo,dec_lo),(ra_hi,dec_lo),(ra_lo,dec_hi),(ra_hi,dec_hi)]
    far=max(angsep(ra%360,dec,x%360,y) for x,y in corners)
    return ra%360,dec,far+margin_arcsec/3600.0


def base_bounds(r):
    size=float(r["cell_size_deg"])
    ira=int(r["cell_ira"]); idec=int(r["cell_idec"])
    return (
        ira*size,(ira+1)*size,
        -90+idec*size,-90+(idec+1)*size
    )


def child_bounds(bounds,quadrant):
    ra0,ra1,d0,d1=bounds
    rm=(ra0+ra1)/2; dm=(d0+d1)/2
    return {
        0:(ra0,rm,d0,dm),
        1:(rm,ra1,d0,dm),
        2:(ra0,rm,dm,d1),
        3:(rm,ra1,dm,d1),
    }[quadrant]


def meta_path(kind,key):
    base=OCACHE if kind=="ordinary" else HCACHE
    return base/(key+".meta.json")


def data_path(kind,key):
    base=OCACHE if kind=="ordinary" else HCACHE
    return base/(key+".csv")


def valid_complete(key,kind,adql):
    mp=meta_path(kind,key); dp=data_path(kind,key)
    if not mp.is_file(): return None
    m=json.loads(mp.read_text(encoding="utf-8"))
    if m.get("adql")!=adql: raise RuntimeError(f"REFUSING cached ADQL changed for {key}")
    if m.get("status")=="COMPLETE":
        if not dp.is_file(): raise RuntimeError(f"missing cached CSV for {key}")
        b=dp.read_bytes()
        if m.get("sha256")!=sha_bytes(b): raise RuntimeError(f"cache hash mismatch for {key}")
        return m
    return m


def save_complete(kind,key,adql,b,n,attempt,extra):
    p=data_path(kind,key); p.parent.mkdir(parents=True,exist_ok=True)
    t=p.with_suffix(".csv.part"); t.write_bytes(b); t.replace(p)
    m={
        "status":"COMPLETE","adql":adql,"rows":n,"sha256":sha_bytes(b),
        "bytes":len(b),"attempt":attempt,"transport":"curl_verified_https",
        "tls_verification_disabled":False,
        "completed_at_utc":datetime.now(timezone.utc).isoformat(),**extra
    }
    write_json(meta_path(kind,key),m)
    return m


def ordinary_leaf(base, bounds, path, depth, consumer_pairs, counter):
    size=bounds[1]-bounds[0]
    margin=float(base["ordinary_j2016_margin_arcsec"])
    ra,dec,radius=geom_from_bounds(*bounds,margin)
    key=f"cell_{int(base['cell_ira']):04d}_{int(base['cell_idec']):04d}_d{depth}_{path or 'root'}"
    adql=cone_adql(ra,dec,radius,None)
    mp=meta_path("ordinary",key)

    if mp.is_file():
        old=json.loads(mp.read_text(encoding="utf-8"))
        if old.get("adql")!=adql: raise RuntimeError(f"REFUSING cached ADQL changed for {key}")
        if old.get("status")=="COMPLETE":
            dp=data_path("ordinary",key)
            if not dp.is_file() or sha_file(dp)!=old.get("sha256"):
                raise RuntimeError(f"cache integrity failure {key}")
            return {"leaf_queries":1,"rows":int(old["rows"]),"network_new":0}
        if old.get("status")=="SUBDIVIDED":
            total={"leaf_queries":0,"rows":0,"network_new":0}
            for q in range(4):
                r=ordinary_leaf(base,child_bounds(bounds,q),path+str(q),depth+1,consumer_pairs,counter)
                for k in total: total[k]+=r[k]
            return total

    counter["new"]+=1
    print(f"    query {key}: r={radius:.5f} deg",flush=True)
    b,n,attempt=query_retry(adql)

    if n>=MAXREC:
        if size/2 < MIN_CELL_DEG-1e-12:
            raise RuntimeError(
                f"DENSITY_OVERFLOW_AT_MIN_CELL {key}: rows={n}, size={size:.6f} deg"
            )
        # Preserve the capped response for audit, but do not treat it as complete.
        tp=(OCACHE/(key+".maxrec.csv")); tp.parent.mkdir(parents=True,exist_ok=True)
        tp.write_bytes(b)
        write_json(mp,{
            "status":"SUBDIVIDED","adql":adql,"rows_at_maxrec":n,
            "maxrec_response_sha256":sha_bytes(b),"cell_size_deg":size,
            "consumer_pair_indices":consumer_pairs,
            "subdivision_reason":"response reached MAXREC; transport completeness only",
            "children":[path+str(q) for q in range(4)],
        })
        print(f"      MAXREC reached ({n}); subdividing transport cell",flush=True)
        total={"leaf_queries":0,"rows":0,"network_new":1}
        for q in range(4):
            r=ordinary_leaf(base,child_bounds(bounds,q),path+str(q),depth+1,consumer_pairs,counter)
            for k in total: total[k]+=r[k]
        return total

    save_complete("ordinary",key,adql,b,n,attempt,{
        "cell_size_deg":size,"query_ra_deg":ra,"query_dec_deg":dec,
        "query_radius_deg":radius,"consumer_pair_indices":consumer_pairs,
        "base_global_query_index":int(base["global_query_index"]),
    })
    time.sleep(SUCCESS_PAUSE_S)
    return {"leaf_queries":1,"rows":n,"network_new":1}


def run_hpm(r,counter):
    idx=int(r["global_hpm_query_index"])
    key=f"hpm_{idx:04d}"
    ra=float(r["query_ra_deg"]);dec=float(r["query_dec_deg"])
    radius=float(r["query_radius_deg"]);pm=float(r["pm_min_masyr"])
    adql=cone_adql(ra,dec,radius,pm)
    old=valid_complete(key,"hpm",adql)
    if old and old.get("status")=="COMPLETE":
        return {"rows":int(old["rows"]),"network_new":0}
    counter["new"]+=1
    print(f"    HPM {key}: r={radius:.5f} deg pm>={pm:.0f}",flush=True)
    b,n,attempt=query_retry(adql)
    if n>=MAXREC:
        raise RuntimeError(f"HPM_MAXREC_REACHED {key}: {n}; operational blocker")
    save_complete("hpm",key,adql,b,n,attempt,{
        "query_ra_deg":ra,"query_dec_deg":dec,"query_radius_deg":radius,
        "pm_min_masyr":pm,"consumer_pair_indices":r["consumer_pair_indices"],
        "global_hpm_query_index":idx,
    })
    time.sleep(SUCCESS_PAUSE_S)
    return {"rows":n,"network_new":1}


def summarize(plan,hplan):
    rows=[]
    completed_base=0
    total_leaf=0
    total_rows=0
    for r in plan:
        bounds=base_bounds(r)
        # Walk cache metadata recursively without network.
        def walk(bounds,path,depth):
            size=bounds[1]-bounds[0]
            ra,dec,radius=geom_from_bounds(*bounds,float(r["ordinary_j2016_margin_arcsec"]))
            key=f"cell_{int(r['cell_ira']):04d}_{int(r['cell_idec']):04d}_d{depth}_{path or 'root'}"
            adql=cone_adql(ra,dec,radius,None)
            mp=meta_path("ordinary",key)
            if not mp.is_file(): return False,0,0
            m=json.loads(mp.read_text(encoding="utf-8"))
            if m.get("adql")!=adql: raise RuntimeError(f"cache ADQL changed {key}")
            if m.get("status")=="COMPLETE":
                dp=data_path("ordinary",key)
                if not dp.is_file() or sha_file(dp)!=m.get("sha256"):
                    raise RuntimeError(f"cache integrity failure {key}")
                return True,1,int(m["rows"])
            if m.get("status")=="SUBDIVIDED":
                ok=True; leaves=rr=0
                for q in range(4):
                    a,b,c=walk(child_bounds(bounds,q),path+str(q),depth+1)
                    ok=ok and a; leaves+=b; rr+=c
                return ok,leaves,rr
            return False,0,0
        ok,leaves,rr=walk(bounds,"",0)
        if ok:completed_base+=1
        total_leaf+=leaves;total_rows+=rr
        rows.append({
            "global_query_index":r["global_query_index"],
            "cell_ira":r["cell_ira"],"cell_idec":r["cell_idec"],
            "consumer_pair_count":r["consumer_pair_count"],
            "consumer_pair_indices":r["consumer_pair_indices"],
            "status":"COMPLETE" if ok else "PENDING",
            "resolved_leaf_queries":leaves,"cached_rows_across_leaves":rr,
        })

    hdone=0;hrows=0
    for r in hplan:
        key=f"hpm_{int(r['global_hpm_query_index']):04d}"
        mp=meta_path("hpm",key)
        if mp.is_file():
            m=json.loads(mp.read_text(encoding="utf-8"))
            if m.get("status")=="COMPLETE":
                dp=data_path("hpm",key)
                if not dp.is_file() or sha_file(dp)!=m.get("sha256"):
                    raise RuntimeError(f"HPM cache integrity failure {key}")
                hdone+=1;hrows+=int(m["rows"])
    return rows,completed_base,total_leaf,total_rows,hdone,hrows


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--max-new",type=int,default=None,help="optional smoke-test cap on new network queries")
    args=ap.parse_args()

    print("="*132)
    print("WIDE CENSUS — CACHED GAIA DR3 ACQUISITION v064")
    print("="*132)
    print("NETWORK: Gaia DR3 TAP metadata/catalogue rows only.")
    print("NO SCIENCE PIXELS. NO DETECTOR. NO ASTROMETRIC REGISTRATION. NO CANDIDATE STATE MUTATION.\n")

    for p in (PLAN,HPLAN,AUDIT,FREEZE):
        if not p.is_file(): raise RuntimeError(f"missing prerequisite: {p}")
    if sha_file(FREEZE)!=EXPECTED_FREEZE_SHA:raise RuntimeError("REFUSING v063 freeze SHA changed")
    a=json.loads(AUDIT.read_text(encoding="utf-8"))
    if a.get("status")!="COMPLETE":raise RuntimeError("REFUSING v063a incomplete")

    for d in (OUT,CACHE,OCACHE,HCACHE):d.mkdir(parents=True,exist_ok=True)
    plan=read_csv(PLAN);hplan=read_csv(HPLAN)
    counter={"new":0}

    print(f"Unique ordinary base queries: {len(plan)}")
    print(f"Unique HPM queries:           {len(hplan)}")
    if args.max_new is not None:print(f"Smoke-test cap:               {args.max_new} new network calls")
    print()

    stopped=False
    for i,r in enumerate(plan,1):
        rows,done,leaf,rr,hd,hr=summarize(plan,hplan)
        if rows[i-1]["status"]=="COMPLETE":
            continue
        if args.max_new is not None and counter["new"]>=args.max_new:
            stopped=True;break
        print(f"[ordinary {i}/{len(plan)}] global cell {r['global_query_index']} consumers={r['consumer_pair_count']}",flush=True)
        before=counter["new"]
        ordinary_leaf(r,base_bounds(r),"",0,r["consumer_pair_indices"],counter)
        if args.max_new is not None and counter["new"]>=args.max_new:
            stopped=True;break
        if counter["new"]==before:
            print("    cached",flush=True)

        if i%20==0:
            rows2,c2,l2,r2,h2,hr2=summarize(plan,hplan)
            write_json(STATE,{
                "status":"IN_PROGRESS","ordinary_base_complete":c2,
                "ordinary_base_total":len(plan),"ordinary_leaf_complete":l2,
                "ordinary_cached_rows":r2,"hpm_complete":h2,"hpm_total":len(hplan),
                "new_network_calls_this_invocation":counter["new"],
                "updated_at_utc":datetime.now(timezone.utc).isoformat(),
            })
            print(f"CHECKPOINT ordinary base {c2}/{len(plan)} | HPM {h2}/{len(hplan)}",flush=True)

    if not stopped:
        for i,r in enumerate(hplan,1):
            if args.max_new is not None and counter["new"]>=args.max_new:
                stopped=True;break
            run_hpm(r,counter)
            if i%5==0:
                _,c2,l2,r2,h2,hr2=summarize(plan,hplan)
                write_json(STATE,{
                    "status":"IN_PROGRESS","ordinary_base_complete":c2,
                    "ordinary_base_total":len(plan),"ordinary_leaf_complete":l2,
                    "ordinary_cached_rows":r2,"hpm_complete":h2,"hpm_total":len(hplan),
                    "new_network_calls_this_invocation":counter["new"],
                    "updated_at_utc":datetime.now(timezone.utc).isoformat(),
                })
                print(f"CHECKPOINT ordinary base {c2}/{len(plan)} | HPM {h2}/{len(hplan)}",flush=True)

    rows,c,l,rn,hd,hr=summarize(plan,hplan)
    write_csv(MANIFEST,rows,[
        "global_query_index","cell_ira","cell_idec","consumer_pair_count",
        "consumer_pair_indices","status","resolved_leaf_queries","cached_rows_across_leaves"
    ])

    complete=(c==len(plan) and hd==len(hplan))
    status="COMPLETE" if complete else "IN_PROGRESS_CHECKPOINTED"
    rep={
        "status":status,
        "analysis_kind":"wide_census_cached_gaia_dr3_acquisition_v064",
        "updated_at_utc":datetime.now(timezone.utc).isoformat(),
        "guards":{
            "network_access":True,"science_pixels_read":False,
            "transient_detector_rerun":False,"astrometric_registration_run":False,
            "candidate_state_mutation":False,"science_policy_changed":False,
        },
        "inputs":{
            "v063_freeze_sha256":sha_file(FREEZE),
            "v063a_audit_sha256":sha_file(AUDIT),
            "ordinary_plan_sha256":sha_file(PLAN),
            "hpm_plan_sha256":sha_file(HPLAN),
        },
        "progress":{
            "ordinary_base_complete":c,"ordinary_base_total":len(plan),
            "ordinary_resolved_leaf_queries":l,
            "ordinary_cached_rows_including_overlap":rn,
            "hpm_complete":hd,"hpm_total":len(hplan),
            "hpm_cached_rows":hr,
            "new_network_calls_this_invocation":counter["new"],
        },
        "cache_semantics":(
            "Gaia DR3 J2016 response bytes are transport evidence and may be reused "
            "by multiple pairs. Pair-specific propagation and astrometric fitting are deferred."
        ),
        "individual_candidate_dispositions":"NONE",
        "science_positives":0,
        "next_stage":(
            "After COMPLETE, build per-pair epoch-propagated Gaia pools and execute the "
            "prospectively frozen target-independent primary/sparse registration offline."
        ),
    }
    write_json(REPORT,rep);write_json(STATE,rep)

    print("\n"+"="*132)
    print("GAIA ACQUISITION",status)
    print("="*132)
    print(f"Ordinary base cells complete: {c}/{len(plan)}")
    print(f"Resolved ordinary leaf queries: {l}")
    print(f"Cached ordinary rows (overlap not deduplicated yet): {rn}")
    print(f"HPM queries complete: {hd}/{len(hplan)}")
    print(f"Cached HPM rows: {hr}")
    print(f"New network calls this invocation: {counter['new']}")
    print("Astrometric registrations run: 0")
    print("Candidate dispositions: NONE")
    print("SCIENCE POSITIVES: 0")
    print("STAGE STATUS:",status)


if __name__=="__main__":
    main()
