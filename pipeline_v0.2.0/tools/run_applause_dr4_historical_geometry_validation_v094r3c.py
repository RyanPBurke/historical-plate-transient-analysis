#!/usr/bin/env python3
from __future__ import annotations
from pathlib import Path
from collections import Counter,defaultdict
from datetime import datetime,timezone,timedelta
import argparse,csv,hashlib,json,math,platform,sys
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
FREEZE=ROOT/"research"/"prospective_freezes"/"v094r3b_historical_geometry_validation"
MANIFEST=FREEZE/"freeze_manifest_v094r3c.json"
SPEC=FREEZE/"applause_dr4_historical_geometry_validation_spec_v094r3b.json"
EXPECTED_SPEC="2a24508c359f31bb14d55755c2579e0314d73d152462286606203273619794cd"
RESULT=ROOT/"results"/"applause_dr4_historical_geometry_validation_v094r3c"

ASEC=206264.80624709636
RE=6378.137
AU=149597870.7
GEN_ARCSEC=7.0
FINAL_ARCSEC=2.0
HEIGHT_STRESS_M=107.0
DISTANCES_KM=(2*RE,0.01*AU,0.1*AU)

def sha(p):
    h=hashlib.sha256()
    with Path(p).open("rb") as f:
        for b in iter(lambda:f.read(8*1024*1024),b""):h.update(b)
    return h.hexdigest()

def log(s):print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {s}",flush=True)

def rows(p):
    with Path(p).open("r",encoding="utf-8-sig",newline="") as f:yield from csv.DictReader(f)

def fnum(v):
    try:
        x=float(str(v if v is not None else "").strip())
        return x if math.isfinite(x) else None
    except:return None

def inum(v):
    try:return int(str(v).strip())
    except:
        x=fnum(v)
        if x is None:return None
        r=int(round(x));return r if abs(x-r)<1e-7 else None

def parse_dt(v):
    s=str(v or "").strip().replace("Z","+00:00")
    if not s:return None
    d=datetime.fromisoformat(s)
    if d.tzinfo is None:d=d.replace(tzinfo=timezone.utc)
    return d.astimezone(timezone.utc)

def qstats(v):
    if not v:return {"n":0,"min":None,"p10":None,"median":None,"p90":None,"p95":None,"max":None}
    a=np.asarray(v,float)
    return {"n":len(a),"min":float(np.min(a)),"p10":float(np.percentile(a,10)),
            "median":float(np.median(a)),"p90":float(np.percentile(a,90)),
            "p95":float(np.percentile(a,95)),"max":float(np.max(a))}

def angle_arcsec(a,b):
    a=np.asarray(a,float);b=np.asarray(b,float)
    na=np.linalg.norm(a);nb=np.linalg.norm(b)
    if na<=0 or nb<=0:return None
    c=float(np.clip((a@b)/(na*nb),-1,1))
    return math.degrees(math.acos(c))*3600

def radec(v):
    v=np.asarray(v,float);v=v/np.linalg.norm(v)
    return math.degrees(math.atan2(v[1],v[0]))%360,math.degrees(math.asin(np.clip(v[2],-1,1)))

def xyz(ra,dec):
    r=math.radians(float(ra));d=math.radians(float(dec));c=math.cos(d)
    return np.array([c*math.cos(r),c*math.sin(r),math.sin(d)])

def parse_poly(v):
    import re
    nums=[float(x) for x in re.findall(r'[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?',str(v or ""))]
    if len(nums)<8:return None
    nums=nums[-8:]
    p=[(nums[i]%360.0,nums[i+1]) for i in range(0,8,2)]
    return None if any(not(-90<=d<=90) for _,d in p) else p

def center(polys):
    vv=np.vstack([xyz(ra,dec) for p in polys for ra,dec in p])
    v=vv.sum(axis=0);v/=np.linalg.norm(v);return radec(v)

def project(vals_ra,vals_dec,ra0,dec0):
    r=np.deg2rad(np.asarray(vals_ra,float));d=np.deg2rad(np.asarray(vals_dec,float))
    r0=math.radians(ra0);d0=math.radians(dec0);dr=(r-r0+math.pi)%(2*math.pi)-math.pi
    den=math.sin(d0)*np.sin(d)+math.cos(d0)*np.cos(d)*np.cos(dr);ok=den>1e-10
    x=np.full(len(r),np.nan);y=np.full(len(r),np.nan)
    x[ok]=np.cos(d[ok])*np.sin(dr[ok])/den[ok]
    y[ok]=(math.cos(d0)*np.sin(d[ok])-math.sin(d0)*np.cos(d[ok])*np.cos(dr[ok]))/den[ok]
    return x,y,ok

def unproject(x,y,ra0,dec0):
    rho=math.hypot(x,y);r0=math.radians(ra0);d0=math.radians(dec0)
    if rho<1e-15:return xyz(ra0,dec0)
    c=math.atan(rho);sc=math.sin(c);cc=math.cos(c)
    dec=math.asin(cc*math.sin(d0)+y*sc*math.cos(d0)/rho)
    ra=r0+math.atan2(x*sc,rho*math.cos(d0)*cc-y*math.sin(d0)*sc)
    return xyz(math.degrees(ra)%360,math.degrees(dec))

def inside(x,y,p):
    px=np.asarray([q[0] for q in p]);py=np.asarray([q[1] for q in p]);z=False;j=len(px)-1
    for i in range(len(px)):
        if ((py[i]>y)!=(py[j]>y)):
            den=py[j]-py[i]
            if abs(den)>1e-20 and x < (px[j]-px[i])*(y-py[i])/den+px[i]:z=not z
        j=i
    return z

def in_polygon_vec(v,p):
    ra,dec=radec(v);ra0,dec0=center([p])
    x,y,ok=project([ra],[dec],ra0,dec0)
    px,py,pok=project([q[0] for q in p],[q[1] for q in p],ra0,dec0)
    return bool(ok[0] and np.all(pok) and inside(x[0],y[0],list(zip(px,py))))

def candidate_geocentric_dirs(pa,pb):
    ra0,dec0=center([pa,pb])
    ax,ay,aok=project([q[0] for q in pa],[q[1] for q in pa],ra0,dec0)
    bx,by,bok=project([q[0] for q in pb],[q[1] for q in pb],ra0,dec0)
    if not np.all(aok) or not np.all(bok):return [xyz(ra0,dec0)]
    xmin,xmax=float(min(ax.min(),bx.min())),float(max(ax.max(),bx.max()))
    ymin,ymax=float(min(ay.min(),by.min())),float(max(ay.max(),by.max()))
    xs=np.linspace(xmin,xmax,5);ys=np.linspace(ymin,ymax,5)
    pts=[]
    # center first, then deterministic distance from center
    for y in ys:
        for x in xs:
            pts.append((x*x+y*y,float(x),float(y)))
    pts.sort()
    return [unproject(x,y,ra0,dec0) for _,x,y in pts]

def mjd_from_dt(d):
    import erfa
    djm0,djm=erfa.cal2jd(d.year,d.month,d.day)
    frac=(d.hour*3600+d.minute*60+d.second+d.microsecond/1e6)/86400.0
    return float(djm+frac)

def decimal_year(d):
    a=datetime(d.year,1,1,tzinfo=timezone.utc);b=datetime(d.year+1,1,1,tzinfo=timezone.utc)
    return d.year+(d-a).total_seconds()/(b-a).total_seconds()

def parse_c01(p):
    rec=[]
    for line in Path(p).read_text(encoding="utf-8",errors="replace").splitlines():
        if not line.strip() or line.lstrip().startswith("#"):continue
        q=line.split()
        if len(q)<10:continue
        try:a=[float(x) for x in q]
        except:continue
        rec.append((a[0],a[1],a[2],a[6],a[7]))
    if len(rec)<1000:raise RuntimeError(f"C01 parse too small: {len(rec)}")
    a=np.asarray(rec,float)
    return {"mjd":a[:,0],"xp":a[:,1],"yp":a[:,2],"xerr":a[:,3],"yerr":a[:,4]}

def interp_c01(c,mjd):
    x=c["mjd"]
    if mjd<x[0] or mjd>x[-1]:return None
    return {k:float(np.interp(mjd,x,c[k])) for k in ("xp","yp","xerr","yerr")}

def parse_hist_deltat(p):
    rec=[]
    for line in Path(p).read_text(encoding="utf-8",errors="replace").splitlines():
        q=line.split()
        if len(q)<3:continue
        try:y,dt,err=float(q[0]),float(q[1]),float(q[2])
        except:continue
        rec.append((y,dt,err))
    if len(rec)<500:raise RuntimeError(f"Historic DeltaT parse too small: {len(rec)}")
    a=np.asarray(rec,float);return {"year":a[:,0],"dt":a[:,1],"err":a[:,2]}

def parse_month_deltat(p):
    if p is None or not Path(p).is_file():return None
    rec=[]
    import erfa
    for line in Path(p).read_text(encoding="utf-8",errors="replace").splitlines():
        q=line.split()
        if len(q)<4:continue
        try:y,m,day=int(q[0]),int(q[1]),int(q[2]);dt=float(q[3])
        except:continue
        _,mjd=erfa.cal2jd(y,m,day);rec.append((float(mjd),dt))
    if len(rec)<100:return None
    a=np.asarray(rec,float);return {"mjd":a[:,0],"dt":a[:,1]}

def delta_t(refs,d):
    y=decimal_year(d);h=refs["hist"]
    if h["year"][0]<=y<=h["year"][-1]:
        return float(np.interp(y,h["year"],h["dt"])),float(np.interp(y,h["year"],h["err"])),"HISTORIC_WITH_ERROR"
    m=refs.get("monthly");mj=mjd_from_dt(d)
    if m is not None and m["mjd"][0]<=mj<=m["mjd"][-1]:
        return float(np.interp(mj,m["mjd"],m["dt"])),None,"MONTHLY_NO_ERROR"
    return None,None,"NO_COVERAGE"

def corrected_lonlat(site,lon,lat):
    if site=="Dr. Remeis-Observatory, Bamberg, Germany":return lat,lon
    return lon,lat

def ecef(lat,lon,h_m):
    a=6378.137;f=1/298.257223563;e2=f*(2-f)
    p=math.radians(lat);l=math.radians(lon);h=h_m/1000.0
    N=a/math.sqrt(1-e2*math.sin(p)**2)
    return np.array([(N+h)*math.cos(p)*math.cos(l),(N+h)*math.cos(p)*math.sin(l),
                     (N*(1-e2)+h)*math.sin(p)])

def up_ecef(lat,lon):
    p=math.radians(lat);l=math.radians(lon)
    return np.array([math.cos(p)*math.cos(l),math.cos(p)*math.sin(l),math.sin(p)])

def site_celestial(site_rec,d,refs,h_delta_m=0.0,xp_delta_arcsec=0.0,yp_delta_arcsec=0.0,dt_delta_sec=0.0):
    import erfa
    lon,lat=corrected_lonlat(site_rec["site_name"],site_rec["site_longitude"],site_rec["site_latitude"])
    mj=mjd_from_dt(d);c=interp_c01(refs["c01"],mj)
    if c is None:return None
    dt,dterr,dtsrc=delta_t(refs,d)
    if dt is None:return None
    xp=math.radians((c["xp"]+xp_delta_arcsec)/3600.0)
    yp=math.radians((c["yp"]+yp_delta_arcsec)/3600.0)
    ut11,ut12=2400000.5,mj
    tt1,tt2=2400000.5,mj+(dt+dt_delta_sec)/86400.0
    rc2t=np.asarray(erfa.c2t06a(tt1,tt2,ut11,ut12,xp,yp),float)
    r=rc2t.T@ecef(lat,lon,site_rec["site_elevation"]+h_delta_m)
    up=rc2t.T@up_ecef(lat,lon);up/=np.linalg.norm(up)
    return {"r":r,"up":up,"c01":c,"delta_t":dt,"delta_t_err":dterr,"delta_t_source":dtsrc,"rc2t":rc2t}

def old_site(site_rec,d):
    lon,lat=corrected_lonlat(site_rec["site_name"],site_rec["site_longitude"],site_rec["site_latitude"])
    v=ecef(lat,lon,0.0);J=2400000.5+mjd_from_dt(d);T=(J-2451545)/36525
    th=math.radians((280.46061837+360.98564736629*(J-2451545)+.000387933*T*T-T*T*T/38710000)%360)
    c,s=math.cos(th),math.sin(th);x,y,z=v
    return np.array([c*x-s*y,s*x+c*y,z])

def ray_solution(rA,rB,nA,nB):
    b=float(nA@nB);den=1-b*b
    if den<1e-15:return None
    w=rA-rB;d=float(nA@w);e=float(nB@w)
    tA=(b*e-d)/den;tB=(e-b*d)/den
    pA=rA+tA*nA;pB=rB+tB*nB;mid=(pA+pB)/2
    miss=float(np.linalg.norm(pA-pB));scale=max(1e-12,(abs(tA)+abs(tB))/2)
    return tA,tB,mid,math.degrees(math.atan2(miss,scale))*3600

def cross_track_arcsec(B,nA,nB):
    normal=np.cross(B,nA);nn=np.linalg.norm(normal)
    if nn<1e-15:return 1e99
    normal/=nn
    return math.degrees(math.asin(min(1.0,abs(float(nB@normal)))))*3600

def geometry_at(siteA,siteB,d,refs,**pert):
    A=site_celestial(siteA,d,refs,
        h_delta_m=pert.get("hA",0),xp_delta_arcsec=pert.get("xp",0),
        yp_delta_arcsec=pert.get("yp",0),dt_delta_sec=pert.get("dt",0))
    B=site_celestial(siteB,d,refs,
        h_delta_m=pert.get("hB",0),xp_delta_arcsec=pert.get("xp",0),
        yp_delta_arcsec=pert.get("yp",0),dt_delta_sec=pert.get("dt",0))
    if A is None or B is None:return None
    return A,B,B["r"]-A["r"]

def score_at(siteA,siteB,d,refs,nA,nB):
    g=geometry_at(siteA,siteB,d,refs)
    if g is None:return 1e99,None
    A,B,base=g;xt=cross_track_arcsec(base,nA,nB);sol=ray_solution(A["r"],B["r"],nA,nB)
    if sol is None:return 1e99,None
    tA,tB,mid,cl=sol;score=max(xt,cl)
    return score,{"xt":xt,"closure":cl,"tA":tA,"tB":tB,"mid":mid,"A":A,"B":B}

def search_pair(siteA,siteB,intervals,refs,nA,nB):
    from scipy.optimize import minimize_scalar
    gen_best=(1e99,None);final_best=(1e99,None)
    for s,e in intervals:
        dur=(e-s).total_seconds()
        if dur<=0:continue
        segments=max(4,min(16,int(math.ceil(dur/300.0))))
        for j in range(segments):
            lo=dur*j/segments;hi=dur*(j+1)/segments
            def xt_obj(x):
                d=s+timedelta(seconds=float(x));g=geometry_at(siteA,siteB,d,refs)
                if g is None:return 1e99
                return cross_track_arcsec(g[2],nA,nB)
            rr=minimize_scalar(xt_obj,bounds=(lo,hi),method="bounded",options={"xatol":1e-3,"maxiter":80})
            x=float(rr.x);xt=float(rr.fun)
            for xx in (lo,hi,x):
                val=xt_obj(xx)
                if val<gen_best[0]:gen_best=(val,s+timedelta(seconds=float(xx)))
            if xt<=GEN_ARCSEC:
                def sc_obj(y):
                    d=s+timedelta(seconds=float(y));v,_=score_at(siteA,siteB,d,refs,nA,nB);return v
                ss=minimize_scalar(sc_obj,bounds=(lo,hi),method="bounded",options={"xatol":1e-3,"maxiter":80})
                y=float(ss.x);val,det=score_at(siteA,siteB,s+timedelta(seconds=y),refs,nA,nB)
                for yy in (lo,hi,y):
                    vv,dd=score_at(siteA,siteB,s+timedelta(seconds=float(yy)),refs,nA,nB)
                    if vv<final_best[0]:final_best=(vv,(s+timedelta(seconds=float(yy)),dd))
    return {"generator_min_xt":gen_best[0],"generator_time":gen_best[1],
            "final_score":final_best[0],"final":final_best[1]}

def reference_uncertainty_scores(siteA,siteB,d,refs,nA,nB):
    g=geometry_at(siteA,siteB,d,refs)
    if g is None:return None
    A,B,_=g;c=A["c01"];dterr=A["delta_t_err"]
    vals=[]
    for dx,dy,dd in ((c["xerr"],0,0),(-c["xerr"],0,0),(0,c["yerr"],0),(0,-c["yerr"],0)):
        gg=geometry_at(siteA,siteB,d,refs,xp=dx,yp=dy,dt=dd)
        if gg:
            xt=cross_track_arcsec(gg[2],nA,nB);sol=ray_solution(gg[0]["r"],gg[1]["r"],nA,nB)
            if sol:vals.append(max(xt,sol[3]))
    if dterr is not None:
        for dd in (dterr,-dterr):
            gg=geometry_at(siteA,siteB,d,refs,dt=dd)
            if gg:
                xt=cross_track_arcsec(gg[2],nA,nB);sol=ray_solution(gg[0]["r"],gg[1]["r"],nA,nB)
                if sol:vals.append(max(xt,sol[3]))
    hvals=[]
    for hA,hB in ((HEIGHT_STRESS_M,-HEIGHT_STRESS_M),(-HEIGHT_STRESS_M,HEIGHT_STRESS_M),
                   (HEIGHT_STRESS_M,HEIGHT_STRESS_M),(-HEIGHT_STRESS_M,-HEIGHT_STRESS_M)):
        gg=geometry_at(siteA,siteB,d,refs,hA=hA,hB=hB)
        if gg:
            xt=cross_track_arcsec(gg[2],nA,nB);sol=ray_solution(gg[0]["r"],gg[1]["r"],nA,nB)
            if sol:hvals.append(max(xt,sol[3]))
    return {"published_max_score_arcsec":max(vals) if vals else None,
            "height107m_max_score_arcsec":max(hvals) if hvals else None,
            "delta_t_error_available":dterr is not None}

def classify_opportunity(nominal_ok,synth_observable,synth_recovered,pub_fail,height_fail):
    """
    Pre-outcome r3c operational repair of r3b report classification only.
    Scientific specification remains the frozen r3b specification.

    Precedence:
      1. reference coverage failure;
      2. no observable synthetic case or any nominal recovery/published-reference failure -> precision unresolved;
      3. nominal recovery passes but fixed +/-107m height stress exceeds 2 arcsec -> site metadata unresolved;
      4. otherwise supported for the bounded synthetic test.

    The APPLAUSE horizontal/elevation datum remains globally QUALIFIED/HOLD in report metadata
    even when an opportunity is supported for the bounded synthetic test.
    """
    if not nominal_ok:
        return "GEOMETRY_UNRESOLVED_REFERENCE_COVERAGE"
    if synth_observable <= 0:
        return "GEOMETRY_UNRESOLVED_PRECISION"
    if pub_fail > 0 or synth_recovered < synth_observable:
        return "GEOMETRY_UNRESOLVED_PRECISION"
    if height_fail > 0:
        return "GEOMETRY_UNRESOLVED_SITE_METADATA"
    return "GEOMETRY_SUPPORTED_FOR_SYNTHETIC_TEST"

def verify_freeze():
    if not MANIFEST.is_file() or not SPEC.is_file():raise SystemExit("Missing frozen v094r3b inputs")
    if sha(SPEC)!=EXPECTED_SPEC:raise SystemExit("Scientific spec SHA mismatch")
    m=json.loads(MANIFEST.read_text(encoding="utf-8"))
    if sha(Path(__file__).resolve())!=m["runner_sha256"]:
        raise SystemExit("Frozen executable SHA mismatch")
    for r in m["frozen_files"]:
        p=FREEZE/r["relative_path"]
        if not p.is_file() or p.stat().st_size!=int(r["size_bytes"]) or sha(p)!=r["sha256"]:
            raise SystemExit(f"Frozen file mismatch: {r['relative_path']}")
    for k in ("frozen_plan","solution_full"):
        r=m["active_project_inputs"][k];p=ROOT/r["path"]
        if not p.is_file() or sha(p)!=r["sha256"]:raise SystemExit(f"Active input mismatch: {k}")
    return m

def load_inputs(m):
    acq=FREEZE/"inputs"/"acquisition"
    plate=acq/"applause_relevant_plate_geometry.csv"
    refsdir=acq/"references"
    c01=refsdir/"EOP_C01_IAU2000_1846-now.txt"
    hist=refsdir/"historic_deltat.data"
    monthly=refsdir/"deltat.data"
    plates={}
    for r in rows(plate):
        pid=inum(r["plate_id"])
        plates[pid]={"site_name":str(r["site_name"]).strip(),"site_longitude":float(r["site_longitude"]),
                     "site_latitude":float(r["site_latitude"]),"site_elevation":float(r["site_elevation"])}
    refs={"c01":parse_c01(c01),"hist":parse_hist_deltat(hist),
          "monthly":parse_month_deltat(monthly if monthly.is_file() else None)}
    polys={}
    for r in rows(ROOT/m["active_project_inputs"]["solution_full"]["path"]):
        sid=inum(r.get("solution_id"));p=parse_poly(r.get("stc_polygon"))
        if sid is not None and p is not None:polys[sid]=p
    plan=list(rows(ROOT/m["active_project_inputs"]["frozen_plan"]["path"]))
    return plates,refs,polys,plan

def self_test():
    import erfa
    # Reference parser samples mirror documented formats.
    tmp=Path(__file__).with_suffix(".selftest.tmp")
    c01=tmp.with_name(tmp.name+".c01");hist=tmp.with_name(tmp.name+".hist")
    c01.write_text("# MJD PM-X PM-Y UT1-TAI DX DY X-ERR Y-ERR UT1-ERR DXERR\n"
                   "33000.0 0.10 0.20 99.99 0 0 0.03 0.04 99.99 0\n"
                   "34000.0 0.20 0.30 99.99 0 0 0.03 0.04 99.99 0\n"*600)
    # duplicated lines are okay for parser size self-test but interpolation x ordering must be fixed below.
    try:
        # direct ERFA transform / ray test instead of invoking parse_c01 duplicate series
        m0=erfa.cal2jd(1952,1,1)[1]
        rc=np.asarray(erfa.c2t06a(2400000.5,m0+30/86400,2400000.5,m0,0,0))
        assert np.max(np.abs(rc@rc.T-np.eye(3)))<1e-10
        rA=np.array([6378.,0,0]);rB=np.array([6378.,400.,0]);R=np.array([100000.,100000.,10000.])
        nA=R-rA;nA/=np.linalg.norm(nA);nB=R-rB;nB/=np.linalg.norm(nB)
        sol=ray_solution(rA,rB,nA,nB);assert sol and sol[0]>0 and sol[1]>0 and sol[3]<1e-3
    finally:
        if c01.exists():c01.unlink()
        if hist.exists():hist.unlink()
    assert classify_opportunity(False,10,10,0,0)=="GEOMETRY_UNRESOLVED_REFERENCE_COVERAGE"
    assert classify_opportunity(True,0,0,0,0)=="GEOMETRY_UNRESOLVED_PRECISION"
    assert classify_opportunity(True,10,9,0,0)=="GEOMETRY_UNRESOLVED_PRECISION"
    assert classify_opportunity(True,10,10,1,0)=="GEOMETRY_UNRESOLVED_PRECISION"
    assert classify_opportunity(True,10,10,0,1)=="GEOMETRY_UNRESOLVED_SITE_METADATA"
    assert classify_opportunity(True,10,10,0,0)=="GEOMETRY_SUPPORTED_FOR_SYNTHETIC_TEST"
    print("v094r3c historical-geometry + classification self-test PASS")
    return 0

def preflight():
    m=verify_freeze();plates,refs,polys,plan=load_inputs(m)
    if len(plates)!=1289:raise SystemExit(f"Relevant plate geometry count HOLD: {len(plates)}")
    overlap=[r for r in plan if str(r.get("timing_bin"))=="OVERLAP"]
    if len(overlap)!=1081:raise SystemExit(f"Overlap population HOLD: {len(overlap)}")
    missing_plate=missing_poly=coverage=0;months_noerr=0
    for r in overlap:
        if inum(r["plate_a"]) not in plates or inum(r["plate_b"]) not in plates:missing_plate+=1
        if inum(r["solution_id_a"]) not in polys or inum(r["solution_id_b"]) not in polys:missing_poly+=1
        try:ivs=json.loads(r.get("fragment_overlap_intervals_json") or "[]")
        except:ivs=[]
        for q in ivs:
            for k in ("start_utc","end_utc"):
                d=parse_dt(q.get(k))
                if d is None:coverage+=1;continue
                c=interp_c01(refs["c01"],mjd_from_dt(d));dt,de,src=delta_t(refs,d)
                if c is None or dt is None:coverage+=1
                if src=="MONTHLY_NO_ERROR":months_noerr+=1
    if missing_plate or missing_poly or coverage:
        raise SystemExit(f"Preflight HOLD plate/poly/reference={missing_plate}/{missing_poly}/{coverage}")
    print("v094r3c FREEZE PREFLIGHT PASS")
    print(f"Relevant plates:                 {len(plates)}")
    print(f"Overlap opportunities:           {len(overlap)}")
    print(f"Reference coverage failures:     {coverage}")
    print(f"Monthly DeltaT samples no error: {months_noerr}")
    print("No target geometry outcomes calculated.")
    return 0

def run():
    m=verify_freeze();plates,refs,polys,plan=load_inputs(m)
    overlap=[r for r in plan if str(r.get("timing_bin"))=="OVERLAP"]
    opp_rows=[];agg=Counter()
    oldcorr=[];lendiff=[];elevang=[];sweeps=[];eop_sens=[];dt_sens=[]
    synth_by_dist=defaultdict(Counter);synth_pub=[];synth_height=[]
    for oi,r in enumerate(overlap,1):
        pa=plates[inum(r["plate_a"])];pb=plates[inum(r["plate_b"])]
        polyA=polys[inum(r["solution_id_a"])];polyB=polys[inum(r["solution_id_b"])]
        try:qivs=json.loads(r.get("fragment_overlap_intervals_json") or "[]")
        except:qivs=[]
        intervals=[]
        for q in qivs:
            s,e=parse_dt(q.get("start_utc")),parse_dt(q.get("end_utc"))
            if s and e and e>s:intervals.append((s,e))
        reasons=[]
        if not intervals:reasons.append("NO_VALIDATED_INTERVAL")
        nominal_ok=True;opp_old=[];opp_len=[];opp_elev=[];opp_sweep=[];opp_eop=[];opp_dt=[]
        for s,e in intervals:
            ts=[s,s+(e-s)*.25,s+(e-s)*.5,s+(e-s)*.75,e]
            bases=[]
            for d in ts:
                g=geometry_at(pa,pb,d,refs)
                if g is None:
                    nominal_ok=False;reasons.append("REFERENCE_COVERAGE");continue
                A,B,base=g;bases.append(base)
                old=old_site(pb,d)-old_site(pa,d)
                aa=angle_arcsec(old,base)
                if aa is not None:opp_old.append(aa);oldcorr.append(aa)
                opp_len.append(abs(np.linalg.norm(base)-np.linalg.norm(old)));lendiff.append(opp_len[-1])
                gz=geometry_at(pa,pb,d,refs,hA=-pa["site_elevation"],hB=-pb["site_elevation"])
                if gz:
                    x=angle_arcsec(base,gz[2])
                    if x is not None:opp_elev.append(x);elevang.append(x)
                c=A["c01"]
                uv=[]
                for dx,dy in ((c["xerr"],0),(-c["xerr"],0),(0,c["yerr"]),(0,-c["yerr"])):
                    gg=geometry_at(pa,pb,d,refs,xp=dx,yp=dy)
                    if gg:
                        x=angle_arcsec(base,gg[2])
                        if x is not None:uv.append(x)
                if uv:opp_eop.append(max(uv));eop_sens.append(max(uv))
                if A["delta_t_err"] is not None:
                    uv=[]
                    for dd in (A["delta_t_err"],-A["delta_t_err"]):
                        gg=geometry_at(pa,pb,d,refs,dt=dd)
                        if gg:
                            x=angle_arcsec(base,gg[2])
                            if x is not None:uv.append(x)
                    if uv:opp_dt.append(max(uv));dt_sens.append(max(uv))
                else:
                    reasons.append("DELTAT_UNCERTAINTY_UNAVAILABLE")
            if len(bases)>=2:
                ref=bases[0]
                z=max((angle_arcsec(ref,b) or 0) for b in bases[1:])
                opp_sweep.append(z);sweeps.append(z)

        # APPLAUSE schema does not document formal CRS/height datum accuracy.
        reasons.extend(["APPLAUSE_HORIZONTAL_DATUM_ACCURACY_UNDOCUMENTED","APPLAUSE_ELEVATION_DATUM_UNDOCUMENTED"])
        synth_attempted=synth_observable=synth_recovered=pub_fail=height_fail=0
        dirs=candidate_geocentric_dirs(polyA,polyB)
        for s,e in intervals:
            true_times=[s,s+(e-s)/2,e]
            for true_t in true_times:
                g=geometry_at(pa,pb,true_t,refs)
                if g is None:continue
                A,B,base=g
                for D in DISTANCES_KM:
                    synth_by_dist[D]["time_distance_cases"]+=1
                    valid=[]
                    for u in dirs:
                        R=D*u
                        nA=R-A["r"];nB=R-B["r"]
                        nA/=np.linalg.norm(nA);nB/=np.linalg.norm(nB)
                        if nA@A["up"]<=0 or nB@B["up"]<=0:continue
                        if not in_polygon_vec(nA,polyA) or not in_polygon_vec(nB,polyB):continue
                        if angle_arcsec(nA,nB)<2.0:continue
                        valid.append((nA,nB))
                    if not valid:
                        synth_by_dist[D]["no_observable_case"]+=1
                        continue
                    # Prospectively require multiple field positions when available:
                    # central-first list -> central, mid-rank, outer-rank.
                    if len(valid)<=3:
                        chosen=valid
                    else:
                        ii=sorted(set((0,len(valid)//2,len(valid)-1)))
                        chosen=[valid[i] for i in ii]
                    for nA,nB in chosen:
                        synth_attempted+=1;synth_observable+=1
                        synth_by_dist[D]["attempted"]+=1;synth_by_dist[D]["observable"]+=1
                        rr=search_pair(pa,pb,intervals,refs,nA,nB)
                        ok=False
                        if rr["generator_min_xt"]<=GEN_ARCSEC and rr["final"] is not None and rr["final"][1] is not None:
                            td,det=rr["final"]
                            sol_mid=np.linalg.norm(det["mid"])
                            ok=(det["xt"]<=FINAL_ARCSEC and det["closure"]<=FINAL_ARCSEC and
                                det["tA"]>0 and det["tB"]>0 and sol_mid>=RE and abs(sol_mid-D)/D<=0.01)
                        if ok:
                            synth_recovered+=1;synth_by_dist[D]["recovered"]+=1
                        else:
                            synth_by_dist[D]["failed_recovery"]+=1
                        us=reference_uncertainty_scores(pa,pb,true_t,refs,nA,nB)
                        if us:
                            if us["published_max_score_arcsec"] is not None:
                                synth_pub.append(us["published_max_score_arcsec"])
                                if us["published_max_score_arcsec"]>FINAL_ARCSEC:
                                    pub_fail+=1;synth_by_dist[D]["published_uncertainty_gt2"]+=1
                            if us["height107m_max_score_arcsec"] is not None:
                                synth_height.append(us["height107m_max_score_arcsec"])
                                if us["height107m_max_score_arcsec"]>FINAL_ARCSEC:
                                    height_fail+=1;synth_by_dist[D]["height107m_gt2"]+=1

        cls=classify_opportunity(
            nominal_ok=nominal_ok,
            synth_observable=synth_observable,
            synth_recovered=synth_recovered,
            pub_fail=pub_fail,
            height_fail=height_fail
        )
        agg[cls]+=1
        agg["synthetic_attempted"]+=synth_attempted;agg["synthetic_observable"]+=synth_observable
        agg["synthetic_recovered"]+=synth_recovered;agg["published_uncertainty_fail"]+=pub_fail
        agg["height107m_fail"]+=height_fail
        opp_rows.append({
            "opportunity_index":oi,"site_pair":r.get("site_pair",""),"epoch_label":r.get("epoch_label",""),
            "classification":cls,"reason_codes":";".join(sorted(set(reasons))),
            "intervals":len(intervals),
            "old_vs_corrected_baseline_angle_max_arcsec":max(opp_old) if opp_old else "",
            "old_vs_corrected_baseline_length_max_abs_km":max(opp_len) if opp_len else "",
            "alt0_vs_supplied_elevation_baseline_angle_max_arcsec":max(opp_elev) if opp_elev else "",
            "corrected_baseline_sweep_max_arcsec":max(opp_sweep) if opp_sweep else "",
            "published_polar_motion_baseline_sensitivity_max_arcsec":max(opp_eop) if opp_eop else "",
            "published_deltat_baseline_sensitivity_max_arcsec":max(opp_dt) if opp_dt else "",
            "synthetic_attempted":synth_attempted,"synthetic_observable":synth_observable,
            "synthetic_recovered":synth_recovered,
            "synthetic_recovery_fraction":(synth_recovered/synth_observable if synth_observable else ""),
            "synthetic_published_uncertainty_gt2arcsec":pub_fail,
            "synthetic_height107m_gt2arcsec":height_fail
        })
        if oi%50==0:log(f"v094r3c geometry/synthetic validation: {oi}/1081")

    RESULT.mkdir(parents=True,exist_ok=True)
    csvp=RESULT/"opportunity_geometry_validation_v094r3c.csv"
    with csvp.open("w",encoding="utf-8",newline="") as f:
        w=csv.DictWriter(f,fieldnames=list(opp_rows[0].keys()));w.writeheader();w.writerows(opp_rows)
    report={
      "status":"COMPLETE",
      "analysis_kind":"applause_dr4_historical_geometry_validation_v094r3c",
      "scientific_spec_sha256":EXPECTED_SPEC,
      "freeze_manifest_sha256":sha(MANIFEST),
      "classification_counts":{k:v for k,v in agg.items() if k.startswith("GEOMETRY_")},
      "synthetic_totals":{k:v for k,v in agg.items() if not k.startswith("GEOMETRY_")},
      "synthetic_by_distance_km":{str(k):dict(v) for k,v in synth_by_dist.items()},
      "diagnostics":{
        "old_vs_corrected_baseline_angle_arcsec":qstats(oldcorr),
        "old_vs_corrected_baseline_length_abs_km":qstats(lendiff),
        "alt0_vs_supplied_elevation_baseline_angle_arcsec":qstats(elevang),
        "corrected_baseline_sweep_arcsec":qstats(sweeps),
        "published_polar_motion_baseline_sensitivity_arcsec":qstats(eop_sens),
        "published_deltat_baseline_sensitivity_arcsec":qstats(dt_sens),
        "synthetic_published_reference_score_arcsec":qstats(synth_pub),
        "synthetic_height107m_score_arcsec":qstats(synth_height)
      },
      "site_metadata_qualification":{
        "applause_horizontal_datum_accuracy":"UNDOCUMENTED",
        "applause_elevation_datum":"UNDOCUMENTED",
        "height_stress_envelope_m":HEIGHT_STRESS_M,
        "precision_certification":"QUALIFIED/HOLD until site datum/accuracy is resolved or shown immaterial for the intended distance regime"
      },
      "guards":{"network_queries":0,"source_pairing":0,"candidate_identity_inspection":0,
                "private_candidate_map_reads":0,"pixels":0,"fits":0,"registration":0},
      "next_matcher_allowed":False
    }
    rp=RESULT/"applause_dr4_historical_geometry_validation_v094r3c.json"
    report["output_hashes"]={csvp.name:sha(csvp)}
    rp.write_text(json.dumps(report,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    man=RESULT/"v094r3c_output_manifest.sha256"
    man.write_text(f"{sha(csvp)}  {csvp.name}\n{sha(rp)}  {rp.name}\n",encoding="utf-8")

    print("\n"+"="*108)
    print("v094r3c HISTORICAL GEOMETRY + OBSERVABLE SYNTHETIC VALIDATION COMPLETE")
    print("="*108)
    for k in ("GEOMETRY_SUPPORTED_FOR_SYNTHETIC_TEST","GEOMETRY_UNRESOLVED_REFERENCE_COVERAGE",
              "GEOMETRY_UNRESOLVED_SITE_METADATA","GEOMETRY_UNRESOLVED_PRECISION"):
        print(f"{k:46s} {agg.get(k,0)}")
    print(f"Synthetic attempted / observable / recovered: {agg['synthetic_attempted']} / {agg['synthetic_observable']} / {agg['synthetic_recovered']}")
    print(f"Published-reference >2arcsec synthetic cases: {agg['published_uncertainty_fail']}")
    print(f"±107m height-envelope >2arcsec cases:          {agg['height107m_fail']}")
    print(f"Old-vs-corrected baseline median arcsec:        {qstats(oldcorr)['median']}")
    print(f"Corrected baseline sweep median arcsec:         {qstats(sweeps)['median']}")
    print(f"Published EOP sensitivity p95 arcsec:           {qstats(eop_sens)['p95']}")
    print(f"Published DeltaT sensitivity p95 arcsec:        {qstats(dt_sens)['p95']}")
    print("Candidate identities inspected:                 0")
    print("Network / source pairing / pixels / registration: 0 / 0 / 0 / 0")
    print("NEW MATCHER: HOLD — interpret validation and site-datum qualification first.")
    return 0

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--self-test",action="store_true")
    ap.add_argument("--preflight",action="store_true")
    a=ap.parse_args()
    if a.self_test:return self_test()
    if a.preflight:return preflight()
    return run()

if __name__=="__main__":raise SystemExit(main())
