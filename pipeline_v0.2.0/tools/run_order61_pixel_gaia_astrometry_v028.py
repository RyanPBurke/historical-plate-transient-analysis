from __future__ import annotations
from pathlib import Path
from datetime import datetime, timezone
import ast, base64, csv, gzip, hashlib, io, json, math, shutil, subprocess, time
import numpy as np
import astropy.units as u
from astropy.coordinates import SkyCoord, Distance
from astropy.io import fits
from astropy.time import Time
from astropy.wcs import WCS
from scipy.optimize import least_squares

ROOT=Path.cwd()
BASE=ROOT/"results/order61_native_full_v028"
WORK=ROOT/"work/order61_native_full_v028"
OW=ROOT/"work/order61_pixel_astrometry_v028"
CACHE=OW/"gaia_cache"
PAIR_REPORT=BASE/"order61_whole_pair_report.json"
STAGE3_REPORT=BASE/"order61_platephot_stage3_report.json"
LOCAL_REPORT=BASE/"order61_local_astrometry_report_v028.json"
STRICT=BASE/"order61_strict_match_triage.csv"
MORPH=BASE/"order61_survivor_native_morphology.csv"
GEOM_SOURCE=ROOT/"tools/repair_remaining_poss_geometry_v028.py"
CONTROL_SOURCE=ROOT/"tools/run_pair61_native_detector_control_v028.py"
REF=ROOT/"cache/poss1_exact_plate_cutout_preflight_v028b/POSS-I_875_E_rec521/XE520_090N_preflight.fits"
POSS_DIR=WORK/"poss_tiles"
DASCH_DIR=WORK/"dasch_tiles"
OUT_REFS=BASE/"order61_pixel_gaia_astrometry_references_v028.csv"
OUT_SUMMARY=BASE/"order61_pixel_gaia_astrometry_summary_v028.csv"
OUT_REPORT=BASE/"order61_pixel_gaia_astrometry_report_v028.json"
for d in (OW,CACHE): d.mkdir(parents=True,exist_ok=True)

TAP="https://gea.esac.esa.int/tap-server/tap/sync"
MOSAIC_API="https://api.starglass.cfa.harvard.edu/public/dasch/dr7/mosaic_package"
UA="historical-transient-pipeline/0.2.8-order61-pixel-astrometry"
ACTIVE_RANKS=[11,14,20]

REFERENCE_RADIUS_ARCMIN=30.0
GAIA_QUERY_RADIUS_ARCMIN=32.0
GAIA_MAX_G_QUERY=16.0
GAIA_G_MIN=11.0
GAIA_G_MAX=14.0
GAIA_RUWE_MAX=1.4
GAIA_ISOLATION_ARCSEC=60.0
MAX_SELECTED_STARS_PER_RANK=24
PIXEL_SEARCH_RADIUS_ARCSEC=30.0
CENTROID_MIN_SNR=5.0
POSS_CENTROID_RADIUS_PX=4.0
DASCH_CENTROID_RADIUS_PX=2.0
MIN_SUCCESSFUL_BOTH_ARCHIVE_REFS=5
HALO=64
CORE=1024

EXPECTED_DETECTOR_SHA="709da8d7a7972b15808d70a1e4dbffa0fd0fee864a81d954f74fe4a5f5af25e7"
EXPECTED_METHOD_SHA="2cb3cabd573d7af99399899f2ccecd3002be90297e55bb0e0dcdd9dea1d0c4c1"
EXPECTED_POLICY_SHA="44fc3453c3291a7cbe72894d781729a30943ad540aa169b2c0897b446c5c8ec7"

GAIA_COLUMNS=["source_id","ra","dec","ref_epoch","ra_error","dec_error","parallax","parallax_error","pm","pmra","pmdec","pmra_error","pmdec_error","radial_velocity","phot_g_mean_mag","bp_rp","ruwe","astrometric_params_solved"]

REF_FIELDS=["strict_rank","selection_order","source_id","g_mag","ruwe","pm_masyr","ra_target_deg","dec_target_deg","sep_from_survivor_mid_arcmin","nearest_gaia_neighbor_arcsec","poss_pred_x","poss_pred_y","poss_pixel_scale_arcsec","poss_status","poss_peak_snr","poss_peak_sign","poss_centroid_x","poss_centroid_y","poss_ra_measured_deg","poss_dec_measured_deg","poss_east_residual_arcsec","poss_north_residual_arcsec","poss_residual_radius_arcsec","dasch_pred_x","dasch_pred_y","dasch_pixel_scale_arcsec","dasch_status","dasch_peak_snr","dasch_peak_sign","dasch_centroid_x","dasch_centroid_y","dasch_ra_measured_deg","dasch_dec_measured_deg","dasch_east_residual_arcsec","dasch_north_residual_arcsec","dasch_residual_radius_arcsec","both_archive_success","cross_east_offset_arcsec","cross_north_offset_arcsec","cross_separation_arcsec"]
SUMMARY_FIELDS=["strict_rank","status","gaia_selected_count","both_archive_reference_count","candidate_raw_separation_arcsec","candidate_raw_east_arcsec","candidate_raw_north_arcsec","reference_median_cross_east_arcsec","reference_median_cross_north_arcsec","reference_cross_residual_median_arcsec","reference_cross_residual_p95_arcsec","candidate_corrected_east_arcsec","candidate_corrected_north_arcsec","candidate_corrected_separation_arcsec","candidate_upper_tail_empirical_p","candidate_within_reference_p95","poss_median_gaia_residual_arcsec","dasch_median_gaia_residual_arcsec"]

def read_csv(p):
    with p.open(newline="",encoding="utf-8-sig") as f:return list(csv.DictReader(f))
def write_csv(p,rows,fields):
    t=p.with_suffix(p.suffix+".tmp")
    with t.open("w",newline="",encoding="utf-8") as f:
        w=csv.DictWriter(f,fieldnames=fields,extrasaction="ignore");w.writeheader();w.writerows(rows)
    t.replace(p)
def write_json(p,o):
    t=p.with_suffix(p.suffix+".tmp");t.write_text(json.dumps(o,indent=2,sort_keys=True,default=str)+"\n",encoding="utf-8");t.replace(p)
def sha256_bytes(b):return hashlib.sha256(b).hexdigest()
def ffloat(v):
    if v is None:return None
    s=str(v).strip()
    if not s or s.lower() in {"nan","null","none","--"}:return None
    try:x=float(s)
    except:return None
    return x if math.isfinite(x) else None
def fint(v):
    try:return int(str(v).strip())
    except:
        try:return int(float(str(v).strip()))
        except:return None

def load_functions(path,names,namespace):
    tree=ast.parse(path.read_text(encoding="utf-8-sig"),filename=str(path))
    nodes=[n for n in tree.body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and n.name in names]
    if {n.name for n in nodes}!=set(names):raise RuntimeError(f"Could not recover {names} from {path}")
    mod=ast.Module(body=nodes,type_ignores=[]);ast.fix_missing_locations(mod);ns=dict(namespace);exec(compile(mod,str(path),"exec"),ns,ns)
    return tuple(ns[n] for n in names)

def parse_utc(v):
    s=str(v).strip()
    if s.endswith("Z"):s=s[:-1]+"+00:00"
    dt=datetime.fromisoformat(s)
    if dt.tzinfo is None:raise RuntimeError("timezone-naive timestamp")
    return Time(dt.astimezone(timezone.utc),scale="utc")
def target_epoch(pair):
    a,b=parse_utc(pair["overlap_start_utc"]),parse_utc(pair["overlap_end_utc"])
    return a+(b-a)/2
def midpoint(p,d):
    v=p.cartesian.xyz.value+d.cartesian.xyz.value;v=v/np.linalg.norm(v)
    ra=math.atan2(float(v[1]),float(v[0]))%(2*math.pi);dec=math.atan2(float(v[2]),math.hypot(float(v[0]),float(v[1])))
    return SkyCoord(ra=ra*u.rad,dec=dec*u.rad,frame="icrs")
def skyoff(a,b):
    e,n=a.spherical_offsets_to(b);return float(e.arcsec),float(n.arcsec)
def empirical_p95(vals):
    a=np.sort(np.asarray(vals,float))
    if len(a)==0:return None
    i=max(0,min(len(a)-1,int(math.ceil(.95*len(a)))-1));return float(a[i])

def parse_gaia(b):
    r=csv.DictReader(io.StringIO(b.decode("utf-8-sig")))
    out=[]
    for q in r:
        q={str(k).lower():v for k,v in q.items()}
        sid=str(q.get("source_id","")).strip()
        if not sid:continue
        out.append({"source_id":sid,"ra":ffloat(q.get("ra")),"dec":ffloat(q.get("dec")),"ref_epoch":ffloat(q.get("ref_epoch")),"parallax":ffloat(q.get("parallax")),"pm":ffloat(q.get("pm")),"pmra":ffloat(q.get("pmra")),"pmdec":ffloat(q.get("pmdec")),"radial_velocity":ffloat(q.get("radial_velocity")),"phot_g_mean_mag":ffloat(q.get("phot_g_mean_mag")),"ruwe":ffloat(q.get("ruwe"))})
    return out

def gaia_query(mid,rank):
    deg=GAIA_QUERY_RADIUS_ARCMIN/60;cols=", ".join(GAIA_COLUMNS)
    adql=f"SELECT TOP 20000 {cols} FROM gaiadr3.gaia_source WHERE phot_g_mean_mag <= {GAIA_MAX_G_QUERY} AND 1=CONTAINS(POINT('ICRS',ra,dec),CIRCLE('ICRS',{mid.ra.deg:.12f},{mid.dec.deg:.12f},{deg:.12f}))"
    cp=CACHE/f"rank_{rank:02d}_gaia.csv";mp=CACHE/f"rank_{rank:02d}_gaia.json"
    if cp.is_file() and mp.is_file():
        b=cp.read_bytes();m=json.loads(mp.read_text())
        if m.get("complete") and m.get("adql")==adql and m.get("sha256")==sha256_bytes(b):return parse_gaia(b),"cached"
    curl=shutil.which("curl.exe") or shutil.which("curl")
    if not curl:raise RuntimeError("curl unavailable")
    part=cp.with_suffix(".part")
    cmd=[curl,"--fail","--silent","--show-error","--location","--connect-timeout","30","--max-time","180","--user-agent",UA,"--data-urlencode","REQUEST=doQuery","--data-urlencode","LANG=ADQL","--data-urlencode","FORMAT=csv","--data-urlencode",f"QUERY={adql}","--output",str(part),TAP]
    q=subprocess.run(cmd,capture_output=True,text=True,timeout=210)
    if q.returncode:raise RuntimeError((q.stderr or q.stdout)[:600])
    b=part.read_bytes();rows=parse_gaia(b)
    if len(rows)>=20000:raise RuntimeError("Gaia TOP limit hit")
    part.replace(cp);write_json(mp,{"complete":True,"adql":adql,"sha256":sha256_bytes(b),"rows":len(rows)})
    return rows,"done"

def propagate(s,t):
    if any(s[k] is None for k in ("ra","dec","ref_epoch","pmra","pmdec")):return None
    kw=dict(ra=s["ra"]*u.deg,dec=s["dec"]*u.deg,pm_ra_cosdec=s["pmra"]*u.mas/u.yr,pm_dec=s["pmdec"]*u.mas/u.yr,obstime=Time(s["ref_epoch"],format="jyear",scale="tcb"),frame="icrs")
    if s["parallax"] and s["parallax"]>0 and s["radial_velocity"] is not None:
        try:kw["distance"]=Distance(parallax=s["parallax"]*u.mas);kw["radial_velocity"]=s["radial_velocity"]*u.km/u.s
        except:pass
    try:return SkyCoord(**kw).apply_space_motion(new_obstime=t).icrs
    except:
        kw.pop("distance",None);kw.pop("radial_velocity",None)
        try:return SkyCoord(**kw).apply_space_motion(new_obstime=t).icrs
        except:return None

def select_refs(rows,mid,t):
    prop=[]
    for s in rows:
        c=propagate(s,t)
        if c is not None:prop.append((s,c))
    coords=SkyCoord([c.ra.deg for _,c in prop]*u.deg,[c.dec.deg for _,c in prop]*u.deg) if prop else None
    out=[]
    for i,(s,c) in enumerate(prop):
        g=s["phot_g_mean_mag"];r=s["ruwe"]
        if g is None or not(GAIA_G_MIN<=g<=GAIA_G_MAX) or r is None or r>GAIA_RUWE_MAX:continue
        sm=float(c.separation(mid).arcmin)
        if sm>REFERENCE_RADIUS_ARCMIN:continue
        near=float("inf")
        if len(prop)>1:
            z=np.asarray(c.separation(coords).arcsec,float);z[i]=np.inf;near=float(z.min())
        if near<GAIA_ISOLATION_ARCSEC:continue
        out.append({**s,"coord":c,"sep_mid_arcmin":sm,"nearest_neighbor_arcsec":near})
    out.sort(key=lambda x:(x["sep_mid_arcmin"],x["phot_g_mean_mag"],x["source_id"]))
    return out[:MAX_SELECTED_STARS_PER_RANK],len(prop)

def mosaic_package():
    curl=shutil.which("curl.exe") or shutil.which("curl")
    out=OW/"ai44092_pkg.json";payload=json.dumps({"plate_id":"ai44092","binning":1})
    q=subprocess.run([curl,"--fail","--silent","--show-error","--location","--connect-timeout","30","--max-time","120","--user-agent",UA,"--header","Accept: application/json","--header","Content-Type: application/json","--data-binary",payload,"--output",str(out),MOSAIC_API],capture_output=True,text=True,timeout=150)
    if q.returncode:raise RuntimeError((q.stderr or q.stdout)[:600])
    return json.loads(out.read_text())

def poss_inv(h,dss,target,sx,sy):
    ra0,de0=dss(h,sx+1.5,sy+1.5);rax,dex=dss(h,sx+2.5,sy+1.5);ray,dey=dss(h,sx+1.5,sy+2.5)
    c0=SkyCoord(float(np.asarray(ra0))*u.deg,float(np.asarray(de0))*u.deg);cx=SkyCoord(float(np.asarray(rax))*u.deg,float(np.asarray(dex))*u.deg);cy=SkyCoord(float(np.asarray(ray))*u.deg,float(np.asarray(dey))*u.deg)
    ex,nx=skyoff(c0,cx);ey,ny=skyoff(c0,cy);et,nt=skyoff(c0,target)
    J=np.array([[ex,ey],[nx,ny]],float);dp=np.linalg.solve(J,np.array([et,nt]))
    g=np.array([sx+dp[0],sy+dp[1]],float)
    def fun(q):
        ra,de=dss(h,q[0]+1.5,q[1]+1.5);c=SkyCoord(float(np.asarray(ra))*u.deg,float(np.asarray(de))*u.deg)
        return np.array(skyoff(target,c))
    fit=least_squares(fun,g,bounds=([g[0]-100,g[1]-100],[g[0]+100,g[1]+100]),max_nfev=100)
    if not fit.success or np.hypot(*fun(fit.x))>.05:raise RuntimeError("POSS inverse WCS failed")
    return map(float,fit.x)

def poss_scale(h,dss,x,y):
    a=SkyCoord(*[float(np.asarray(v))*u.deg for v in dss(h,x+1.5,y+1.5)])
    b=SkyCoord(*[float(np.asarray(v))*u.deg for v in dss(h,x+2.5,y+1.5)])
    c=SkyCoord(*[float(np.asarray(v))*u.deg for v in dss(h,x+1.5,y+2.5)])
    return float(np.median([a.separation(b).arcsec,a.separation(c).arcsec]))
def dasch_scale(w,x,y):
    a=w.pixel_to_world(x,y);return float(np.median([a.separation(w.pixel_to_world(x+1,y)).arcsec,a.separation(w.pixel_to_world(x,y+1)).arcsec]))

def tid(prefix,x,y,w,h):
    ix,iy=int(math.floor(x)),int(math.floor(y))
    if not(0<=ix<w and 0<=iy<h):raise RuntimeError("predicted pixel outside")
    x0=(ix//CORE)*CORE;y0=(iy//CORE)*CORE
    return f"{prefix}_x{x0:05d}-{min(x0+CORE,w):05d}_y{y0:05d}-{min(y0+CORE,h):05d}"
def parse_tid(t):
    q=t.split("_");a=q[1][1:].split("-");b=q[2][1:].split("-");return *map(int,a),*map(int,b)
AC={}
def load_tile(t,w,h,d):
    if (t,str(d)) in AC:return AC[(t,str(d))]
    x0,x1,y0,y1=parse_tid(t);ex0=max(0,x0-HALO);ex1=min(w,x1+HALO);ey0=max(0,y0-HALO);ey1=min(h,y1+HALO)
    p=d/f"{t}.npy"
    if not p.is_file():raise RuntimeError(f"missing tile {p}")
    a=np.load(p,mmap_mode="r")
    if a.shape!=(ey1-ey0,ex1-ex0):raise RuntimeError("tile shape mismatch")
    AC[(t,str(d))]=(a,ex0,ey0);return AC[(t,str(d))]

def centroid(archive,x,y,scale,w,h,d):
    t=tid("P" if archive=="POSS" else "D",x,y,w,h);a,ex0,ey0=load_tile(t,w,h,d);px=x-ex0;py=y-ey0
    sr=max(1,int(math.ceil(PIXEL_SEARCH_RADIUS_ARCSEC/scale)));cr=POSS_CENTROID_RADIUS_PX if archive=="POSS" else DASCH_CENTROID_RADIUS_PX
    R=int(math.ceil(sr+cr+8));ix,iy=int(round(px)),int(round(py));x0,x1=ix-R,ix+R+1;y0,y1=iy-R,iy+R+1
    if x0<0 or y0<0 or x1>a.shape[1] or y1>a.shape[0]:return {"status":"STAMP_OUTSIDE_CACHED_TILE"}
    cut=np.asarray(a[y0:y1,x0:x1],float);yy,xx=np.indices(cut.shape);cx0=px-x0;cy0=py-y0;rr=np.hypot(xx-cx0,yy-cy0)
    ann=cut[(rr>=sr+cr+2)&(rr<=R-1)&np.isfinite(cut)]
    if ann.size<40:return {"status":"INSUFFICIENT_BACKGROUND"}
    bg=float(np.median(ann));sig=1.4826*float(np.median(np.abs(ann-bg)))
    if not(sig>0):return {"status":"INVALID_BACKGROUND_SIGMA"}
    res=cut-bg;valid=(rr<=sr)&np.isfinite(res);score=np.where(valid,np.abs(res),-np.inf);pyi,pxi=np.unravel_index(int(np.argmax(score)),cut.shape);peak=float(res[pyi,pxi]);snr=abs(peak)/sig
    if snr<CENTROID_MIN_SNR:return {"status":"PEAK_BELOW_5SIGMA","peak_snr":snr,"peak_sign":1 if peak>=0 else -1}
    sign=1 if peak>=0 else -1;rp=np.hypot(xx-pxi,yy-pyi);wt=np.clip(sign*res,0,None)*(rp<=cr);ws=float(wt.sum())
    if ws<=0:return {"status":"INVALID_CENTROID_WEIGHTS"}
    cx=float((wt*xx).sum()/ws);cy=float((wt*yy).sum()/ws)
    return {"status":"SUCCESS","peak_snr":snr,"peak_sign":sign,"centroid_x":ex0+x0+cx,"centroid_y":ey0+y0+cy}

def loo(refs):
    out=[]
    for i,r in enumerate(refs):
        o=refs[:i]+refs[i+1:];me=float(np.median([q["cross_east_offset_arcsec"] for q in o]));mn=float(np.median([q["cross_north_offset_arcsec"] for q in o]))
        out.append(math.hypot(r["cross_east_offset_arcsec"]-me,r["cross_north_offset_arcsec"]-mn))
    return out

def main():
    print("="*102);print("ORDER 61 — ORDINARY-GAIA-STAR NATIVE-PIXEL LOCAL ASTROMETRY v028");print("="*102)
    for p in (PAIR_REPORT,STAGE3_REPORT,LOCAL_REPORT,STRICT,MORPH,GEOM_SOURCE,CONTROL_SOURCE,REF):
        if not p.is_file():raise RuntimeError(f"Missing {p}")
    pair=json.loads(PAIR_REPORT.read_text());stage3=json.loads(STAGE3_REPORT.read_text());loc=json.loads(LOCAL_REPORT.read_text())
    guards={"pair_complete":pair.get("status")=="COMPLETE","order":int(pair.get("canonical_order",-1))==61,"detector":pair.get("detector_sha256")==EXPECTED_DETECTOR_SHA,"method":pair.get("method_sha256")==EXPECTED_METHOD_SHA,"policy":pair.get("policy_sha256")==EXPECTED_POLICY_SHA,"stage3":stage3.get("status")=="COMPLETE","prior_local_complete":loc.get("status")=="COMPLETE","prior_local_zero_refs":loc.get("gaia_both_reference_candidates_before_dedupe")==0}
    if not all(guards.values()):raise RuntimeError("Guard failure "+repr(guards))
    strict={int(r["strict_rank"]):r for r in read_csv(STRICT)};morph={int(r["strict_rank"]):r for r in read_csv(MORPH)}
    t=target_epoch(pair)
    _,dss=load_functions(GEOM_SOURCE,("plate_center_radians","dss_world"),{"np":np})
    (tpv,)=load_functions(CONTROL_SOURCE,("tpv",),{"fits":fits,"WCS":WCS,"gzip":gzip,"base64":base64})
    h=fits.getheader(REF,0);fw,fh=int(h.get("XPIXELS",14000)),int(h.get("YPIXELS",13999))
    pkg=mosaic_package();dw,dh,rk,shape=tpv(pkg["metadata"]);H,W=shape;outH,outW=(W,H) if rk in(-1,1) else (H,W)
    print("Guards: PASS");print("Target epoch:",t.utc.isot);print(f"Fixed refs: 11<=G<=14, RUWE<=1.4, isolation>=60\", within30', nearest24; pixel search 30\", SNR>=5")
    allrows=[];sums=[];surv={}
    for rank in ACTIVE_RANKS:
        s=strict[rank];m=morph[rank];p=SkyCoord(float(s["poss_ra_deg"])*u.deg,float(s["poss_dec_deg"])*u.deg);d=SkyCoord(float(s["dasch_ra_deg"])*u.deg,float(s["dasch_dec_deg"])*u.deg);mid=midpoint(p,d)
        gr,qs=gaia_query(mid,rank);sel,nprop=select_refs(gr,mid,t);refs=[]
        print(f"strict #{rank:02d}: Gaia {qs.upper()} rows={len(gr)} propagated={nprop} selected={len(sel)}")
        for j,g in enumerate(sel,1):
            c=g["coord"]
            row={"strict_rank":rank,"selection_order":j,"source_id":g["source_id"],"g_mag":g["phot_g_mean_mag"],"ruwe":g["ruwe"],"pm_masyr":g["pm"],"ra_target_deg":c.ra.deg,"dec_target_deg":c.dec.deg,"sep_from_survivor_mid_arcmin":g["sep_mid_arcmin"],"nearest_gaia_neighbor_arcsec":g["nearest_neighbor_arcsec"]}
            try:
                px,py=poss_inv(h,dss,c,float(m["poss_global_x"]),float(m["poss_global_y"]));ps=poss_scale(h,dss,px,py);pm=centroid("POSS",px,py,ps,fw,fh,POSS_DIR)
            except Exception as e:px=py=ps=None;pm={"status":"ERROR:"+str(e)[:160]}
            try:
                dx,dy=map(float,dw.world_to_pixel(c));ds=dasch_scale(dw,dx,dy);dm=centroid("DASCH",dx,dy,ds,outW,outH,DASCH_DIR)
            except Exception as e:dx=dy=ds=None;dm={"status":"ERROR:"+str(e)[:160]}
            row.update({"poss_pred_x":px,"poss_pred_y":py,"poss_pixel_scale_arcsec":ps,"poss_status":pm.get("status"),"poss_peak_snr":pm.get("peak_snr"),"poss_peak_sign":pm.get("peak_sign"),"poss_centroid_x":pm.get("centroid_x"),"poss_centroid_y":pm.get("centroid_y"),"dasch_pred_x":dx,"dasch_pred_y":dy,"dasch_pixel_scale_arcsec":ds,"dasch_status":dm.get("status"),"dasch_peak_snr":dm.get("peak_snr"),"dasch_peak_sign":dm.get("peak_sign"),"dasch_centroid_x":dm.get("centroid_x"),"dasch_centroid_y":dm.get("centroid_y")})
            pc=dc=None
            if pm.get("status")=="SUCCESS":
                ra,de=dss(h,pm["centroid_x"]+1.5,pm["centroid_y"]+1.5);pc=SkyCoord(float(np.asarray(ra))*u.deg,float(np.asarray(de))*u.deg);pe,pn=skyoff(c,pc);row.update({"poss_ra_measured_deg":pc.ra.deg,"poss_dec_measured_deg":pc.dec.deg,"poss_east_residual_arcsec":pe,"poss_north_residual_arcsec":pn,"poss_residual_radius_arcsec":math.hypot(pe,pn)})
            if dm.get("status")=="SUCCESS":
                dc=dw.pixel_to_world(dm["centroid_x"],dm["centroid_y"]);de,dn=skyoff(c,dc);row.update({"dasch_ra_measured_deg":dc.ra.deg,"dasch_dec_measured_deg":dc.dec.deg,"dasch_east_residual_arcsec":de,"dasch_north_residual_arcsec":dn,"dasch_residual_radius_arcsec":math.hypot(de,dn)})
            both=pc is not None and dc is not None;row["both_archive_success"]=both
            if both:
                ce,cn=skyoff(pc,dc);row.update({"cross_east_offset_arcsec":ce,"cross_north_offset_arcsec":cn,"cross_separation_arcsec":math.hypot(ce,cn)});refs.append(row)
            allrows.append(row);print(f"  [{j:02d}/{len(sel):02d}] {g['source_id']} G={g['phot_g_mean_mag']:.2f} P={pm.get('status')} D={dm.get('status')} both={'YES' if both else 'no'}")
        re=float(s["east_offset_arcsec"]);rn=float(s["north_offset_arcsec"]);rr=float(s["separation_arcsec"])
        if len(refs)<MIN_SUCCESSFUL_BOTH_ARCHIVE_REFS:
            z={"strict_rank":rank,"status":"INSUFFICIENT_ORDINARY_STAR_PIXEL_REFERENCES","gaia_selected_count":len(sel),"both_archive_reference_count":len(refs),"candidate_raw_separation_arcsec":rr,"candidate_raw_east_arcsec":re,"candidate_raw_north_arcsec":rn}
        else:
            me=float(np.median([q["cross_east_offset_arcsec"] for q in refs]));mn=float(np.median([q["cross_north_offset_arcsec"] for q in refs]));lv=loo(refs);p95=empirical_p95(lv);ce=re-me;cn=rn-mn;cr=math.hypot(ce,cn);ep=(1+sum(x>=cr for x in lv))/(len(lv)+1)
            z={"strict_rank":rank,"status":"ORDINARY_STAR_PIXEL_ASTROMETRY_COMPLETE","gaia_selected_count":len(sel),"both_archive_reference_count":len(refs),"candidate_raw_separation_arcsec":rr,"candidate_raw_east_arcsec":re,"candidate_raw_north_arcsec":rn,"reference_median_cross_east_arcsec":me,"reference_median_cross_north_arcsec":mn,"reference_cross_residual_median_arcsec":float(np.median(lv)),"reference_cross_residual_p95_arcsec":p95,"candidate_corrected_east_arcsec":ce,"candidate_corrected_north_arcsec":cn,"candidate_corrected_separation_arcsec":cr,"candidate_upper_tail_empirical_p":ep,"candidate_within_reference_p95":cr<=p95,"poss_median_gaia_residual_arcsec":float(np.median([q["poss_residual_radius_arcsec"] for q in refs])),"dasch_median_gaia_residual_arcsec":float(np.median([q["dasch_residual_radius_arcsec"] for q in refs]))}
        sums.append(z);surv[str(rank)]=z;print(f"  => refs {len(refs)}/{len(sel)} {z['status']}")
        if z["status"].endswith("_COMPLETE"):print(f"     raw={rr:.3f}\" corrected={z['candidate_corrected_separation_arcsec']:.3f}\" ref_p95={z['reference_cross_residual_p95_arcsec']:.3f}\" p={z['candidate_upper_tail_empirical_p']:.4f}")
    write_csv(OUT_REFS,allrows,REF_FIELDS);write_csv(OUT_SUMMARY,sums,SUMMARY_FIELDS)
    write_json(OUT_REPORT,{"status":"COMPLETE","analysis_kind":"order61_ordinary_gaia_star_native_pixel_astrometry_v028","guards":guards,"fixed_policy":{"reference_radius_arcmin":REFERENCE_RADIUS_ARCMIN,"g_range":[GAIA_G_MIN,GAIA_G_MAX],"ruwe_max":GAIA_RUWE_MAX,"isolation_arcsec":GAIA_ISOLATION_ARCSEC,"max_selected_per_rank":MAX_SELECTED_STARS_PER_RANK,"pixel_search_radius_arcsec":PIXEL_SEARCH_RADIUS_ARCSEC,"centroid_min_snr":CENTROID_MIN_SNR,"minimum_successful_both_archive_references":MIN_SUCCESSFUL_BOTH_ARCHIVE_REFS,"model":"median_translation_only","previous_zero_reference_test_relaxed":False},"survivors":surv,"detector_rerun":False,"ordinary_star_image_pixels_read":True,"candidate_image_pixels_used_for_reference_fit":False,"science_candidate_deleted":False})
    print("="*102);print("ORDINARY-GAIA-STAR NATIVE-PIXEL ASTROMETRY COMPLETE");print("="*102)
    for z in sums:print(f"strict #{z['strict_rank']:02d}: {z['status']} refs={z['both_archive_reference_count']}/{z['gaia_selected_count']}")
    print("Transient detector was NOT rerun. Ordinary-star pixels WERE read. Candidate pixels were NOT references.")

if __name__=="__main__":main()
