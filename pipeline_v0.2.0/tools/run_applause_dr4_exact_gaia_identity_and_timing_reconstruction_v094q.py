#!/usr/bin/env python3
from __future__ import annotations
from pathlib import Path
from collections import defaultdict,OrderedDict,Counter
from datetime import datetime,timezone
import argparse,csv,hashlib,json,math,shutil
import numpy as np
from scipy.spatial import cKDTree

ROOT=Path(__file__).resolve().parents[1]
CONTRACT=ROOT/"research"/"prospective_freezes"/"applause_dr4_exact_gaia_identity_and_timing_reconstruction_contract_v094q.json"
PROV=ROOT/"research"/"prospective_freezes"/"applause_dr4_exact_gaia_identity_and_timing_reconstruction_parent_provenance_v094q.json"
EXPECTED="2ad909d4253f6031e5e230069f259a18b3fdeea3836b385b4c79865d2d2f0880"
WORK=ROOT/"work"/"applause_dr4_exact_gaia_identity_and_timing_reconstruction_v094q"
EXACT=WORK/"exact_hq_scan_solution_npz"
RESULT=ROOT/"results"/"applause_dr4_exact_gaia_identity_and_timing_reconstruction_v094q"
TOL=0.001

def sha(p):
    h=hashlib.sha256()
    with Path(p).open("rb") as f:
        for b in iter(lambda:f.read(8*1024*1024),b""):h.update(b)
    return h.hexdigest()

def log(s):print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {s}",flush=True)

def rows(p):
    with Path(p).open("r",encoding="utf-8-sig",newline="") as f:yield from csv.DictReader(f)

def exact_int_text(v):
    if v is None:return None
    s=str(v).strip()
    if not s:return None
    if any(c in s.lower() for c in (".","e")):
        x=float(s)
        if not math.isfinite(x) or not x.is_integer():return None
        if abs(x)>2**53:raise RuntimeError(f"Unsafe float-form integer encountered: {s}")
        return int(x)
    try:return int(s)
    except:return None

def small_int(v):
    x=exact_int_text(v)
    return x

def fnum(v):
    try:
        x=float(str(v if v is not None else "").strip());return x if math.isfinite(x) else None
    except:return None

def parse_dt(v):
    s=str(v or "").strip().replace("Z","+00:00")
    if not s:return None
    try:d=datetime.fromisoformat(s)
    except:return None
    if d.tzinfo is None:d=d.replace(tzinfo=timezone.utc)
    return d.astimezone(timezone.utc)

def epoch(dt):return dt.timestamp()

def exact_int_col(col,name):
    a=np.ma.asarray(col);mask=np.ma.getmaskarray(a);data=np.asarray(a.data)
    out=np.empty(len(data),dtype=np.int64)
    if np.issubdtype(data.dtype,np.integer):
        out[:]=data.astype(np.int64,copy=False)
    else:
        for i,v in enumerate(data):
            if mask[i]:out[i]=-1;continue
            s=str(v).strip()
            if not s:out[i]=-1;continue
            if any(c in s.lower() for c in (".","e")):
                raise RuntimeError(f"{name} raw VOTable field is not exact integer dtype/string: {data.dtype}")
            out[i]=int(s)
    out[mask]=-1
    return out

def parse_poly(v):
    import re
    a=[float(x) for x in re.findall(r'[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?',str(v or ""))]
    if len(a)<8:return None
    a=a[-8:];p=[(a[i]%360,a[i+1]) for i in range(0,8,2)]
    return None if any(not(-90<=d<=90) for _,d in p) else p

def xyz(ra,dec):
    ra=np.deg2rad(np.asarray(ra,float));dec=np.deg2rad(np.asarray(dec,float));c=np.cos(dec)
    return np.column_stack((c*np.cos(ra),c*np.sin(ra),np.sin(dec)))

def one_xyz(ra,dec):return xyz([ra],[dec])[0]

def center(polys):
    q=np.vstack([one_xyz(ra,dec) for p in polys for ra,dec in p]);v=q.sum(0);v/=np.linalg.norm(v)
    return math.degrees(math.atan2(v[1],v[0]))%360,math.degrees(math.asin(np.clip(v[2],-1,1)))

def project(ra,dec,ra0,dec0):
    r=np.deg2rad(np.asarray(ra,float));d=np.deg2rad(np.asarray(dec,float));r0=math.radians(ra0);d0=math.radians(dec0)
    dr=(r-r0+math.pi)%(2*math.pi)-math.pi
    den=math.sin(d0)*np.sin(d)+math.cos(d0)*np.cos(d)*np.cos(dr);ok=den>1e-10
    x=np.full(len(r),np.nan);y=np.full(len(r),np.nan)
    x[ok]=np.cos(d[ok])*np.sin(dr[ok])/den[ok]
    y[ok]=(math.cos(d0)*np.sin(d[ok])-math.sin(d0)*np.cos(d[ok])*np.cos(dr[ok]))/den[ok]
    return x,y,ok

def inside(x,y,p):
    px=np.asarray([q[0] for q in p]);py=np.asarray([q[1] for q in p]);z=np.zeros(len(x),bool);j=len(px)-1
    for i in range(len(px)):
        cross=((py[i]>y)!=(py[j]>y))&np.isfinite(x)&np.isfinite(y);den=py[j]-py[i]
        if abs(den)>1e-20:z^=cross&(x<(px[j]-px[i])*(y-py[i])/den+px[i])
        j=i
    return z

def common_mask(ra,dec,pa,pb):
    ra0,dec0=center([pa,pb]);x,y,ok=project(ra,dec,ra0,dec0)
    ax,ay,aok=project([q[0] for q in pa],[q[1] for q in pa],ra0,dec0)
    bx,by,bok=project([q[0] for q in pb],[q[1] for q in pb],ra0,dec0)
    if not np.all(aok) or not np.all(bok):return np.zeros(len(np.asarray(ra)),dtype=bool)
    return ok&inside(x,y,list(zip(ax,ay)))&inside(x,y,list(zip(bx,by)))

def arcsec(a,b):
    c=float(np.clip(np.dot(a,b),-1,1));return math.degrees(math.acos(c))*3600

def mutual(a,b):
    if len(a["source_id"])==0 or len(b["source_id"])==0:return []
    xa,xb=xyz(a["ra"],a["dec"]),xyz(b["ra"],b["dec"]);ta,tb=cKDTree(xa),cKDTree(xb)
    da,j=tb.query(xa);db,i=ta.query(xb);out=[]
    for ii,jj in enumerate(j.astype(int)):
        if int(i[int(jj)])==ii:out.append((ii,int(jj),arcsec(xa[ii],xb[int(jj)])))
    return out

def subset(a,m):return {k:v[m] for k,v in a.items() if hasattr(v,"__len__") and len(v)==len(m)}

class LRU:
    def __init__(self,n=8):self.n=n;self.d=OrderedDict()
    def get(self,key,path):
        if key in self.d:self.d.move_to_end(key);return self.d[key]
        z=np.load(path,allow_pickle=False);x={k:np.asarray(z[k]) for k in z.files if not k.endswith("_scalar")}
        self.d[key]=x
        while len(self.d)>self.n:self.d.popitem(last=False)
        return x

def legacy_gaia_predict(exact):
    x=np.asarray(exact,np.int64);out=np.empty(len(x),dtype=np.int64)
    for i,v in enumerate(x):
        out[i]=-1 if int(v)<0 else int(round(float(int(v))))
    return out

def rebuild_exact_caches(root,p):
    from astropy.table import Table
    inv=list(rows(root/p["source_cache_inventory"]["path"]))
    rec={(small_int(r["scan_id"]),small_int(r["solution_num"])):r for r in inv}
    positive={k for k,r in rec.items() if int(r["rows"])>0}
    built=set();EXACT.mkdir(parents=True,exist_ok=True)
    changed=legacy_mismatch=positivity_changes=0
    manifest=[]
    for fi,rr in enumerate(p["raw_votables"]["files"],1):
        f=root/rr["path"]
        if not f.is_file() or f.stat().st_size!=int(rr["size_bytes"]) or sha(f)!=rr["sha256"]:
            raise SystemExit(f"Raw VOTable provenance mismatch: {f}")
        t=Table.read(f,format="votable");cm={str(c).lower():str(c) for c in t.colnames}
        for q in ("source_id","scan_id","solution_num","gaiaedr3_id"):
            if q not in cm:raise SystemExit(f"Missing {q} in {f}")
        src=exact_int_col(t[cm["source_id"]],"source_id");scan=exact_int_col(t[cm["scan_id"]],"scan_id")
        sol=exact_int_col(t[cm["solution_num"]],"solution_num");gid=exact_int_col(t[cm["gaiaedr3_id"]],"gaiaedr3_id")
        if len(src):
            for sid,sn in np.unique(np.column_stack((scan,sol)),axis=0):
                key=(int(sid),int(sn))
                if key not in positive or key in built:continue
                m=(scan==sid)&(sol==sn);rs=src[m];rg=gid[m]
                oldpath=root/rec[key]["relative_path"];z=np.load(oldpath,allow_pickle=False)
                old={k:np.asarray(z[k]) for k in z.files}
                cs=np.asarray(old["source_id"],np.int64);cg=np.asarray(old["gaia_id"],np.int64)
                if len(rs)!=len(cs):raise SystemExit(f"Raw/cache row mismatch for {key}")
                ir=np.argsort(rs);ic=np.argsort(cs)
                if not np.array_equal(rs[ir],cs[ic]):raise SystemExit(f"Raw/cache source_id set mismatch for {key}")
                aligned=np.empty(len(cs),dtype=np.int64);aligned[ic]=rg[ir]
                pred=legacy_gaia_predict(aligned)
                legacy_mismatch+=int(np.sum(pred!=cg))
                changed+=int(np.sum(aligned!=cg))
                positivity_changes+=int(np.sum((aligned>0)!=(cg>0)))
                old["gaia_id"]=aligned
                dst=EXACT/f"scan_{key[0]}_solution_{key[1]}.npz";tmp=dst.with_suffix(".npz.tmp")
                with tmp.open("wb") as fh:np.savez_compressed(fh,**old)
                tmp.replace(dst)
                built.add(key)
                manifest.append({"scan_id":key[0],"solution_num":key[1],"rows":len(cs),
                                 "relative_path":str(dst.relative_to(root)).replace("\\","/"),
                                 "sha256":sha(dst),"size_bytes":dst.stat().st_size})
        del t
        if fi%25==0:log(f"Exact Gaia cache rebuild: {fi}/347 raw files; keys {len(built)}/{len(positive)}")
    if built!=positive:raise SystemExit(f"Exact cache rebuild coverage HOLD: {len(built)}/{len(positive)} positive keys")

    # Reproduce zero-row keys from old cache unchanged.
    for key,r in rec.items():
        if key in positive:continue
        oldpath=root/r["relative_path"];dst=EXACT/f"scan_{key[0]}_solution_{key[1]}.npz"
        shutil.copy2(oldpath,dst)
        manifest.append({"scan_id":key[0],"solution_num":key[1],"rows":0,
                         "relative_path":str(dst.relative_to(root)).replace("\\","/"),
                         "sha256":sha(dst),"size_bytes":dst.stat().st_size})
    manifest.sort(key=lambda r:(r["scan_id"],r["solution_num"]))
    if len(manifest)!=1386 or sum(r["rows"] for r in manifest)!=21609122:
        raise SystemExit("Exact cache manifest mechanical HOLD")
    if legacy_mismatch!=0:raise SystemExit(f"Legacy float-causality HOLD: {legacy_mismatch} cached values differ from predicted legacy conversion")
    if changed!=10583188 or positivity_changes!=0:
        raise SystemExit(f"v094p exact replay HOLD changed={changed}, positivity={positivity_changes}")
    mpath=WORK/"exact_gaia_cache_inventory_v094q.csv";WORK.mkdir(parents=True,exist_ok=True)
    with mpath.open("w",encoding="utf-8",newline="") as fh:
        w=csv.DictWriter(fh,fieldnames=["scan_id","solution_num","rows","relative_path","sha256","size_bytes"])
        w.writeheader();w.writerows(manifest)
    return {"products":len(manifest),"rows":sum(r["rows"] for r in manifest),
            "positive_products":len(positive),"gaia_rows_changed":changed,
            "gaia_positive_status_changes":positivity_changes,
            "legacy_conversion_prediction_mismatches":legacy_mismatch,
            "inventory_path":str(mpath.relative_to(root)).replace("\\","/"),"inventory_sha256":sha(mpath)}, {
                (r["scan_id"],r["solution_num"]):root/r["relative_path"] for r in manifest
            }

def equality_impact(root,p,exactpaths):
    plan=list(rows(root/p["frozen_plan"]["path"]))
    polys={}
    for r in rows(root/p["solution_full"]["path"]):
        sid=small_int(r.get("solution_id"));q=parse_poly(r.get("stc_polygon"))
        if sid is not None and q is not None:polys[sid]=q
    oldinv=list(rows(root/p["source_cache_inventory"]["path"]))
    oldpaths={(small_int(r["scan_id"]),small_int(r["solution_num"])):root/r["relative_path"] for r in oldinv}
    oldcache=LRU(8);excache=LRU(8)
    agg=Counter();over=Counter()
    for ix,r in enumerate(plan,1):
        ka=(small_int(r["scan_id_a"]),small_int(r["solution_num_a"]))
        kb=(small_int(r["scan_id_b"]),small_int(r["solution_num_b"]))
        pa,pb=polys.get(small_int(r["solution_id_a"])),polys.get(small_int(r["solution_id_b"]))
        if pa is None or pb is None:raise SystemExit("Missing polygon in equality replay")
        OA,OB=oldcache.get(ka,oldpaths[ka]),oldcache.get(kb,oldpaths[kb])
        EA,EB=excache.get(ka,exactpaths[ka]),excache.get(kb,exactpaths[kb])
        ma=common_mask(OA["ra"],OA["dec"],pa,pb);mb=common_mask(OB["ra"],OB["dec"],pa,pb)
        A,B=subset(OA,ma),subset(OB,mb);XA,XB=subset(EA,ma),subset(EB,mb)
        if not np.array_equal(A["source_id"],XA["source_id"]) or not np.array_equal(B["source_id"],XB["source_id"]):
            raise SystemExit("Exact/old cache row alignment mismatch after common mask")
        ca,cb=np.asarray(A["gaia_id"],np.int64),np.asarray(B["gaia_id"],np.int64)
        ea,eb=np.asarray(XA["gaia_id"],np.int64),np.asarray(XB["gaia_id"],np.int64)
        cshared=set(int(x) for x in ca if int(x)>0).intersection(int(x) for x in cb if int(x)>0)
        eshared=set(int(x) for x in ea if int(x)>0).intersection(int(x) for x in eb if int(x)>0)
        cma=np.array([int(x)>0 and int(x) in cshared for x in ca],dtype=bool)
        cmb=np.array([int(x)>0 and int(x) in cshared for x in cb],dtype=bool)
        ema=np.array([int(x)>0 and int(x) in eshared for x in ea],dtype=bool)
        emb=np.array([int(x)>0 and int(x) in eshared for x in eb],dtype=bool)
        false_shared=int(np.sum(cma&~ema)+np.sum(cmb&~emb))
        missed_shared=int(np.sum(ema&~cma)+np.sum(emb&~cmb))
        vals=Counter({
            "opportunities":1,
            "common_source_incidences":len(ca)+len(cb),
            "cached_shared_source_incidences":int(cma.sum()+cmb.sum()),
            "exact_shared_source_incidences":int(ema.sum()+emb.sum()),
            "false_cached_shared_source_incidences":false_shared,
            "missed_exact_shared_source_incidences":missed_shared,
            "opportunities_with_shared_membership_change":int(false_shared+missed_shared>0)
        })
        # Tight reference impact using identical MNN geometry and Gaia-distance gates.
        cached_refs=exact_refs=false_refs=missed_refs=0
        for ia,ib,s in mutual(A,B):
            da=fnum(A["gaiaedr3_dist"][ia]);db=fnum(B["gaiaedr3_dist"][ib])
            if s>5 or da is None or db is None or da>1 or db>1:continue
            cs=ca[ia]>0 and ca[ia]==cb[ib]
            es=ea[ia]>0 and ea[ia]==eb[ib]
            cached_refs+=int(cs);exact_refs+=int(es);false_refs+=int(cs and not es);missed_refs+=int(es and not cs)
        vals.update({
            "cached_tight_same_gaia_refs":cached_refs,
            "exact_tight_same_gaia_refs":exact_refs,
            "false_cached_tight_same_gaia_refs":false_refs,
            "missed_exact_tight_same_gaia_refs":missed_refs,
            "opportunities_with_reference_membership_change":int(false_refs+missed_refs>0)
        })
        agg.update(vals)
        if str(r.get("timing_bin"))=="OVERLAP":over.update(vals)
        if ix%100==0:log(f"Exact Gaia equality impact replay: {ix}/1240")
    if agg["missed_exact_shared_source_incidences"]!=0 or agg["missed_exact_tight_same_gaia_refs"]!=0:
        # Deterministic rounding should only merge identities, not split them.
        raise SystemExit("Unexpected exact-shared identity missing under cached representation")
    return {"all_le5min":dict(agg),"overlap_only":dict(over)}

def valid_fragments(exposure,subs,eid):
    r=exposure.get(eid)
    if r is None:return "MISSING_EXPOSURE",[]
    n=r["num_sub"]
    if n is None:return "TIMING_STRUCTURALLY_UNRESOLVED_NUM_SUB",[]
    if n>1:
        ss=subs.get(eid,[])
        if len(ss)!=n:return "SUBEXPOSURE_COUNT_MISMATCH",[]
        ids=[q["subexposure_id"] for q in ss];nums=[q["subexposure_num"] for q in ss]
        if None in ids or len(set(ids))!=len(ids):return "SUBEXPOSURE_ID_INVALID",[]
        if None in nums or len(set(nums))!=len(nums):return "SUBEXPOSURE_NUM_INVALID",[]
        iv=[]
        for q in ss:
            s,e=q["start"],q["end"]
            if s is None or e is None or e<=s:return "SUBEXPOSURE_INTERVAL_INVALID",[]
            iv.append((s,e))
        iv.sort()
        for (s1,e1),(s2,e2) in zip(iv,iv[1:]):
            if s2<e1:return "SUBEXPOSURE_INTERVALS_OVERLAP",[]
        return "FRAGMENTS_EXPOSURE_SUB",iv
    s,e=r["start"],r["end"]
    if s is None or e is None or e<=s:return "PARENT_INTERVAL_INVALID",[]
    return "PROVISIONAL_PARENT_INTERVAL",[(s,e)]

def intersect(a,b):
    out=[]
    for sa,ea in a:
        for sb,eb in b:
            s=max(sa,sb);e=min(ea,eb)
            if e>s:out.append((s,e))
    return sorted(out)

def min_gap(a,b):
    best=None
    for sa,ea in a:
        for sb,eb in b:
            if min(ea,eb)>max(sa,sb):return 0.0
            g=(sb-ea).total_seconds() if ea<=sb else (sa-eb).total_seconds()
            if g>=0 and (best is None or g<best):best=g
    return best

def plan_intervals(r):
    try:q=json.loads(r.get("fragment_overlap_intervals_json") or "[]")
    except:return None
    out=[]
    for z in q:
        s=parse_dt(z.get("start_utc"));e=parse_dt(z.get("end_utc"))
        if not s or not e or e<=s:return None
        out.append((s,e))
    return sorted(out)

def intervals_equal(a,b,tol=TOL):
    if a is None or len(a)!=len(b):return False
    for (sa,ea),(sb,eb) in zip(a,b):
        if abs((sa-sb).total_seconds())>tol or abs((ea-eb).total_seconds())>tol:return False
    return True

def timing_reconstruction(root,p):
    exposure={}
    for r in rows(root/p["v094d_exposure_full"]["path"]):
        eid=small_int(r.get("exposure_id"))
        if eid is None:continue
        exposure[eid]={"num_sub":small_int(r.get("num_sub")),"start":parse_dt(r.get("ut_start")),
                       "end":parse_dt(r.get("ut_end")),"flag_time":str(r.get("flag_time") or "")}
    subs=defaultdict(list)
    for r in rows(root/p["v094d_exposure_sub_full"]["path"]):
        eid=small_int(r.get("exposure_id"))
        if eid is None:continue
        subs[eid].append({"subexposure_id":small_int(r.get("subexposure_id")),
                          "subexposure_num":small_int(r.get("subexposure_num")),
                          "start":parse_dt(r.get("ut_start")),"end":parse_dt(r.get("ut_end"))})
    plan=list(rows(root/p["frozen_plan"]["path"]))
    c=Counter();statuses=Counter()
    max_overlap_diff=0.0;max_gap_diff=0.0
    for ix,r in enumerate(plan,1):
        ea,eb=small_int(r.get("exposure_a")),small_int(r.get("exposure_b"))
        sta,A=valid_fragments(exposure,subs,ea);stb,B=valid_fragments(exposure,subs,eb)
        statuses[sta]+=1;statuses[stb]+=1
        c["opportunities"]+=1
        if not A or not B:
            c["reconstruction_timing_holds"]+=1
            continue
        rec=intersect(A,B);pg=plan_intervals(r)
        rec_overlap=bool(rec);plan_overlap=str(r.get("timing_bin"))=="OVERLAP"
        c["reconstructed_overlap"]+=int(rec_overlap);c["plan_overlap"]+=int(plan_overlap)
        c["overlap_classification_mismatch"]+=int(rec_overlap!=plan_overlap)
        if plan_overlap:
            c["plan_overlap_interval_parse_failure"]+=int(pg is None)
            same=intervals_equal(pg,rec)
            c["overlap_interval_set_mismatch"]+=int(not same)
            if pg is not None:
                pr=sum((e-s).total_seconds() for s,e in pg);rr=sum((e-s).total_seconds() for s,e in rec)
                d=abs(pr-rr);max_overlap_diff=max(max_overlap_diff,d)
                c["total_overlap_duration_mismatch_gt_tolerance"]+=int(d>TOL)
        else:
            rg=min_gap(A,B);pgap=fnum(r.get("min_fragment_gap_seconds"))
            if rg is None or pgap is None:
                c["gap_comparison_unavailable"]+=1
            else:
                d=abs(rg-pgap);max_gap_diff=max(max_gap_diff,d)
                c["min_gap_mismatch_gt_tolerance"]+=int(d>TOL)
        c["any_side_num_sub_gt1"]+=int(
            (exposure.get(ea,{}).get("num_sub") or 0)>1 or (exposure.get(eb,{}).get("num_sub") or 0)>1
        )
        if ix%100==0:log(f"Independent timing reconstruction: {ix}/1240")
    return {**dict(c),"fragment_status_incidence_counts":dict(statuses),
            "max_total_overlap_duration_abs_diff_seconds":max_overlap_diff,
            "max_min_gap_abs_diff_seconds":max_gap_diff,
            "comparison_tolerance_seconds":TOL}

def self_test():
    x=2**60+1
    assert int(round(float(x)))!=x
    exact=np.array([x,x+1,-1],dtype=np.int64)
    pred=legacy_gaia_predict(exact)
    assert pred[0]==pred[1] and pred[0]!=x and pred[2]==-1
    d=lambda s:datetime.fromisoformat(s).replace(tzinfo=timezone.utc)
    a=[(d("2000-01-01T00:00:00"),d("2000-01-01T00:10:00"))]
    b=[(d("2000-01-01T00:05:00"),d("2000-01-01T00:15:00"))]
    q=intersect(a,b);assert len(q)==1 and (q[0][1]-q[0][0]).total_seconds()==300
    assert min_gap(a,[(d("2000-01-01T00:12:00"),d("2000-01-01T00:14:00"))])==120
    print("v094q exact-Gaia + timing-reconstruction self-test PASS")
    return 0

def main():
    ap=argparse.ArgumentParser();ap.add_argument("--self-test",action="store_true");a=ap.parse_args()
    if a.self_test:return self_test()
    if not CONTRACT.is_file() or sha(CONTRACT)!=EXPECTED:raise SystemExit("v094q contract SHA mismatch")
    if not PROV.is_file():raise SystemExit("Missing v094q provenance")
    p=json.loads(PROV.read_text(encoding="utf-8"))
    if p.get("status")!="PARENT_PROVENANCE_PREPARED_BEFORE_V094Q_VALUES":raise SystemExit("Bad v094q provenance")

    for sec in ("frozen_plan","source_cache_inventory","plate_site_cache","solution_full","v094d_exposure_full","v094d_exposure_sub_full"):
        rec=p[sec];f=ROOT/rec["path"]
        if not f.is_file() or sha(f)!=rec["sha256"]:raise SystemExit(f"Runtime frozen input hash mismatch: {sec}")

    log("Rebuilding exact-Gaia strict-HQ caches from frozen raw VOTables")
    repair,exactpaths=rebuild_exact_caches(ROOT,p)
    log("Quantifying equality-dependent impact of exact Gaia IDs")
    impact=equality_impact(ROOT,p,exactpaths)
    log("Independently reconstructing exposure/subexposure timing")
    timing=timing_reconstruction(ROOT,p)

    RESULT.mkdir(parents=True,exist_ok=True)
    report={
      "status":"COMPLETE",
      "analysis_kind":"applause_dr4_exact_gaia_identity_and_timing_reconstruction_v094q",
      "contract_sha256":EXPECTED,
      "parent_provenance_sha256":sha(PROV),
      "exact_gaia_cache_repair":repair,
      "gaia_equality_impact":impact,
      "independent_timing_reconstruction":timing,
      "downstream_inference_status":{
        "gaia_resolved_vs_unresolved_positivity":"RECONFIRMED_UNCHANGED" if repair["gaia_positive_status_changes"]==0 else "HOLD",
        "gaia_identity_equality_analyses":"REPLAY_REQUIRED",
        "v094n_v094o_parallax_inference":"HOLD",
        "candidate_unblinding_allowed":False
      },
      "guards":{"network_queries":0,"private_candidate_map_reads":0,"candidate_identity_inspection":0,
                "source_or_gaia_ids_emitted":0,"coordinates_emitted":0,"pixels":0,"fits":0,
                "registration":0,"new_physical_source_pairing":0}
    }
    rp=RESULT/"applause_dr4_exact_gaia_identity_and_timing_reconstruction_v094q.json"
    rp.write_text(json.dumps(report,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    man=RESULT/"v094q_output_manifest.sha256"
    man.write_text(f"{sha(rp)}  {rp.name}\n{repair['inventory_sha256']}  exact_gaia_cache_inventory_v094q.csv\n",encoding="utf-8")

    a5=impact["all_le5min"];ao=impact["overlap_only"]
    print("\n"+"="*108)
    print("v094q EXACT-GAIA IDENTITY + TIMING RECONSTRUCTION COMPLETE")
    print("="*108)
    print(f"Exact Gaia cache products / rows:             {repair['products']} / {repair['rows']:,}")
    print(f"Legacy conversion prediction mismatches:      {repair['legacy_conversion_prediction_mismatches']:,}")
    print(f"Gaia rows repaired:                           {repair['gaia_rows_changed']:,}")
    print(f"Gaia positivity changes:                      {repair['gaia_positive_status_changes']:,}")
    print(f"<=5min false cached-shared source incidences:  {a5.get('false_cached_shared_source_incidences',0):,}")
    print(f"<=5min missed exact-shared source incidences:  {a5.get('missed_exact_shared_source_incidences',0):,}")
    print(f"Overlap false cached-shared source incidences: {ao.get('false_cached_shared_source_incidences',0):,}")
    print(f"Cached / exact tight same-Gaia refs (overlap): {ao.get('cached_tight_same_gaia_refs',0):,} / {ao.get('exact_tight_same_gaia_refs',0):,}")
    print(f"False cached tight refs (overlap):             {ao.get('false_cached_tight_same_gaia_refs',0):,}")
    print(f"Timing opportunities independently rebuilt:   {timing.get('opportunities',0)}")
    print(f"Timing reconstruction HOLDs:                  {timing.get('reconstruction_timing_holds',0)}")
    print(f"Overlap classification mismatches:            {timing.get('overlap_classification_mismatch',0)}")
    print(f"Overlap interval-set mismatches:              {timing.get('overlap_interval_set_mismatch',0)}")
    print(f"Total-overlap duration mismatches >1ms:        {timing.get('total_overlap_duration_mismatch_gt_tolerance',0)}")
    print(f"Non-overlap min-gap mismatches >1ms:           {timing.get('min_gap_mismatch_gt_tolerance',0)}")
    print("Private candidate identities inspected:        0")
    print("Network / pixels / registration / pairing:    0 / 0 / 0 / 0")
    print("STOP: interpret exact identity and independent timing before historical-frame validation.")
    return 0

if __name__=="__main__":
    raise SystemExit(main())
