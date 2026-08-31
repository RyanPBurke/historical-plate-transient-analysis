#!/usr/bin/env python3
"""
ORDER 01 — POSS physical source centering / local-structure audit v028v

Purpose
-------
Return to the physical-image branch after v028u invalidated the spurious
v028q plate-offset interpretation.

Questions:
  1. For #10/#25/#30, whose integrated POSS raw flux was positive in v028o,
     is that positive structure actually centered on the frozen science
     coordinate like an ordinary stellar image?
  2. For #24/#26/#29, what is the geometry of the mixed/negative raw structure:
     is the deficit centered, elongated, adjacent to a positive source, or
     simply low-amplitude background structure?

Reference population:
  Bright isolated Gaia controls already frozen by v028p. Only POSS detections
  with positive image sign and a reconstructed Gaia residual <=10 arcsec are
  accepted as ordinary-star morphology controls.

Measurements:
  - robust local planar background from a 12–24 px annulus
  - background sigma by MAD
  - Gaussian-smoothed positive/negative response (sigma=2.5 px)
  - distance from frozen center to local positive maximum / negative minimum
  - positive- and negative-flux centroids within 7 px
  - second-moment axis ratio
  - positive concentration F(r<=3)/F(r<=7)
  - signed aperture significance at r=2,3,5,7 px
  - nearest strong positive/negative Gaussian structure within 25 px

Science positions NEVER participate in the stellar reference distribution.
No network access.
SCIENCE PIXELS ARE READ.
Frozen transient detector is NOT rerun.
No candidate promotion/deletion/state mutation.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
from scipy.ndimage import gaussian_filter

ROOT = Path.cwd()
BASE = ROOT / "results" / "order01_native_full_v028"
WORK = ROOT / "work" / "order01_native_full_v028"

STRICT = BASE / "order01_strict_match_triage_v028.csv"
POSS_CAND = BASE / "order01_poss_native_candidates.csv"
V028P_REFS = BASE / "order01_bright_gaia_subpixel_references_v028p.csv"
V028U_JSON = BASE / "order01_official_dr7_fitted_position_adjudication_v028u.json"
INJ = BASE / "order01_injection_recovery_report_v028.json"

POSS_TILE_DIR = WORK / "poss_tiles"

OUT_JSON = BASE / "order01_poss_physical_source_centering_v028v.json"
OUT_CSV = BASE / "order01_poss_physical_source_centering_v028v.csv"
OUT_CTRL = BASE / "order01_poss_physical_source_centering_controls_v028v.csv"
OUT_MD = BASE / "ORDER01_POSS_PHYSICAL_SOURCE_CENTERING_V028V.md"

EXPECTED = [10,24,25,26,29,30]
POSITIVE_INTEGRATED_PRIOR = {10,25,30}
MIXED_PRIOR = {24}
NEGATIVE_PRIOR = {26,29}

# WCS reconstruction guard for control identity.
POLY_DEGREES = [1,2,3]
MAX_FORWARD_P95_ARCSEC = 0.35
MAX_INVERSE_P95_PX = 0.20
CONTROL_MAX_GAIA_RESID_ARCSEC = 10.0
CONTROL_REQUIRED_SIGN = 1

# Physical measurement.
STAMP_RADIUS = 30
BACKGROUND_INNER = 12.0
BACKGROUND_OUTER = 24.0
BACKGROUND_CLIP_ITERS = 4
BACKGROUND_CLIP_SIGMA = 3.0
GAUSSIAN_SIGMA_PX = 2.5
CENTER_SEARCH_RADIUS = 7.0
STRUCTURE_SEARCH_RADIUS = 25.0
FLUX_CENTROID_RADIUS = 7.0
FLUX_WEIGHT_MIN_SIGMA = 1.0
STRONG_STRUCTURE_SIGMA = 4.0

# Descriptive classification only.
MIN_CONTROLS_FOR_DESCRIPTIVE = 5


def read_csv(path):
    with path.open("r",encoding="utf-8-sig",newline="") as fh:
        return list(csv.DictReader(fh))


def write_csv(path,rows,fields):
    tmp=path.with_suffix(path.suffix+".tmp")
    with tmp.open("w",encoding="utf-8",newline="") as fh:
        w=csv.DictWriter(fh,fieldnames=fields,extrasaction="ignore")
        w.writeheader();w.writerows(rows)
    tmp.replace(path)


def write_json(path,obj):
    tmp=path.with_suffix(path.suffix+".tmp")
    tmp.write_text(json.dumps(obj,indent=2,sort_keys=True,default=str)+"\n",
                   encoding="utf-8")
    tmp.replace(path)


def f(v,default=None):
    try:
        if v is None or str(v).strip()=="":
            return default
        x=float(str(v).strip())
        return x if math.isfinite(x) else default
    except Exception:
        return default


def i(v,default=None):
    try:
        if v is None or str(v).strip()=="":
            return default
        return int(float(str(v).strip()))
    except Exception:
        return default


def b(v):
    return str(v).strip().lower() in {"true","1","yes","y","t"}


def pick(row,*names,default=None):
    norm={str(k).lower().replace("_",""):k for k in row}
    for name in names:
        q=str(name).lower().replace("_","")
        if q in norm:
            return row[norm[q]]
    return default


def sha_file(path,block=1024*1024):
    h=hashlib.sha256()
    with path.open("rb") as fh:
        for z in iter(lambda:fh.read(block),b""):
            h.update(z)
    return h.hexdigest()


def angular_vector(ra1,dec1,ra2,dec2):
    dec0=.5*(dec1+dec2)
    east=(ra2-ra1)*3600*math.cos(math.radians(dec0))
    north=(dec2-dec1)*3600
    return east,north,math.hypot(east,north)


def tangent_xy(ra,dec,ra0,dec0):
    return (
        (np.asarray(ra,float)-ra0)*3600*math.cos(math.radians(dec0)),
        (np.asarray(dec,float)-dec0)*3600
    )


def poly_terms(x,y,degree):
    cols=[np.ones_like(x)]
    for total in range(1,degree+1):
        for xp in range(total,-1,-1):
            yp=total-xp
            cols.append((x**xp)*(y**yp))
    return np.column_stack(cols)


class Transform:
    def __init__(self,x0,y0,pscale,ra0,dec0,sscale,
                 fdeg,fx,fy,ideg,ix,iy,validation):
        self.x0=x0;self.y0=y0;self.pscale=pscale
        self.ra0=ra0;self.dec0=dec0;self.sscale=sscale
        self.fdeg=fdeg;self.fx=fx;self.fy=fy
        self.ideg=ideg;self.ix=ix;self.iy=iy
        self.validation=validation

    def pixel_to_sky(self,gx,gy):
        px=(np.atleast_1d(np.asarray(gx,float))-self.x0)/self.pscale
        py=(np.atleast_1d(np.asarray(gy,float))-self.y0)/self.pscale
        A=poly_terms(px,py,self.fdeg)
        sx=(A@self.fx)*self.sscale
        sy=(A@self.fy)*self.sscale
        ra=self.ra0+sx/(3600*math.cos(math.radians(self.dec0)))
        dec=self.dec0+sy/3600
        if np.ndim(gx)==0:return float(ra[0]),float(dec[0])
        return ra,dec

    def sky_to_pixel(self,ra,dec):
        sx,sy=tangent_xy(np.atleast_1d(np.asarray(ra,float)),
                         np.atleast_1d(np.asarray(dec,float)),
                         self.ra0,self.dec0)
        sx=np.asarray(sx)/self.sscale;sy=np.asarray(sy)/self.sscale
        A=poly_terms(sx,sy,self.ideg)
        gx=(A@self.ix)*self.pscale+self.x0
        gy=(A@self.iy)*self.pscale+self.y0
        if np.ndim(ra)==0:return float(gx[0]),float(gy[0])
        return gx,gy

    def local_scale(self,gx,gy):
        r0,d0=self.pixel_to_sky(gx,gy)
        r1,d1=self.pixel_to_sky(gx+1,gy)
        r2,d2=self.pixel_to_sky(gx,gy+1)
        _,_,sx=angular_vector(r0,d0,r1,d1)
        _,_,sy=angular_vector(r0,d0,r2,d2)
        return float(np.median([sx,sy]))


def fit_transform(rows,tile_id):
    pts=[]
    for r in rows:
        if str(r.get("tile_id",""))!=tile_id:continue
        try:
            pts.append((f(r["global_x"]),f(r["global_y"]),
                        f(r["ra_deg"]),f(r["dec_deg"])))
        except Exception:
            continue
    if len(pts)<30:raise RuntimeError(f"{tile_id}: only {len(pts)} WCS rows")
    a=np.asarray(pts,float);gx,gy,ra,dec=a.T
    x0=float(np.median(gx));y0=float(np.median(gy))
    pscale=max(float(np.ptp(gx)),float(np.ptp(gy)),512.0)/2
    ra0=float(np.median(ra));dec0=float(np.median(dec))
    sx,sy=tangent_xy(ra,dec,ra0,dec0);sx=np.asarray(sx);sy=np.asarray(sy)
    sscale=max(float(np.ptp(sx)),float(np.ptp(sy)),100.0)/2
    px=(gx-x0)/pscale;py=(gy-y0)/pscale;snx=sx/sscale;sny=sy/sscale
    order=np.lexsort((gy,gx));test=np.zeros(len(a),bool);test[order[::5]]=True
    train=~test

    bestf=None
    for deg in POLY_DEGREES:
        A=poly_terms(px,py,deg)
        cx,*_=np.linalg.lstsq(A[train],snx[train],rcond=None)
        cy,*_=np.linalg.lstsq(A[train],sny[train],rcond=None)
        rr=np.hypot((A[test]@cx)*sscale-sx[test],
                    (A[test]@cy)*sscale-sy[test])
        q=float(np.quantile(rr,.95))
        if bestf is None or q<bestf[0]:bestf=(q,deg)
        if q<=.05:break
    fdeg=bestf[1];A=poly_terms(px,py,fdeg)
    fx,*_=np.linalg.lstsq(A,snx,rcond=None);fy,*_=np.linalg.lstsq(A,sny,rcond=None)

    besti=None
    for deg in POLY_DEGREES:
        A=poly_terms(snx,sny,deg)
        cx,*_=np.linalg.lstsq(A[train],px[train],rcond=None)
        cy,*_=np.linalg.lstsq(A[train],py[train],rcond=None)
        rr=np.hypot((A[test]@cx)*pscale+x0-gx[test],
                    (A[test]@cy)*pscale+y0-gy[test])
        q=float(np.quantile(rr,.95))
        if besti is None or q<besti[0]:besti=(q,deg)
        if q<=.05:break
    ideg=besti[1];A=poly_terms(snx,sny,ideg)
    ix,*_=np.linalg.lstsq(A,px,rcond=None);iy,*_=np.linalg.lstsq(A,py,rcond=None)
    val={"forward_p95_arcsec":bestf[0],"inverse_p95_px":besti[0],
         "forward_ok":bestf[0]<=MAX_FORWARD_P95_ARCSEC,
         "inverse_ok":besti[0]<=MAX_INVERSE_P95_PX}
    return Transform(x0,y0,pscale,ra0,dec0,sscale,
                     fdeg,fx,fy,ideg,ix,iy,val)


def inventory():
    out={}
    for jp in sorted(POSS_TILE_DIR.glob("*.json")):
        try:o=json.loads(jp.read_text(encoding="utf-8"))
        except Exception:continue
        if o.get("complete") is not True:continue
        tid=str(o.get("tile_id","")).strip()
        ext=o.get("extended");ref=o.get("npy_path")
        if not tid or not isinstance(ext,list) or len(ext)!=4 or not ref:continue
        p=Path(str(ref));p=p if p.is_absolute() else ROOT/p
        if not p.is_file():raise RuntimeError(f"{tid}: missing {p}")
        actual=sha_file(p)
        rec=str(o.get("npy_file_sha256") or "").lower()
        if rec and rec!=actual:raise RuntimeError(f"{tid}: SHA mismatch")
        out[tid]={"tile_id":tid,"extended":tuple(map(int,ext)),
                  "npy_path":p,"sha256":actual}
    return out


ARR={}
def load_arr(meta):
    tid=meta["tile_id"]
    if tid in ARR:return ARR[tid]
    a=np.load(meta["npy_path"],mmap_mode="r")
    ex0,ex1,ey0,ey1=meta["extended"]
    if a.shape!=(ey1-ey0,ex1-ex0):
        raise RuntimeError(f"{tid}: array shape mismatch")
    ARR[tid]=a
    return a


def resolve_science_native(strict_row,native_rows):
    tile=str(pick(strict_row,"poss_tile_id"))
    idx=i(pick(strict_row,"poss_candidate_index","poss_index","poss_native_candidate_index"))
    if idx is not None:
        q=[r for r in native_rows if str(r.get("tile_id",""))==tile
           and i(r.get("candidate_index"))==idx]
        if len(q)==1:return q[0]

    # Fallback: unique nearest native row in sky position within the frozen tile.
    ra=f(pick(strict_row,"poss_ra_deg"));dec=f(pick(strict_row,"poss_dec_deg"))
    q=[]
    for r in native_rows:
        if str(r.get("tile_id",""))!=tile:continue
        rra=f(r.get("ra_deg"));rdec=f(r.get("dec_deg"))
        if None in (ra,dec,rra,rdec):continue
        _,_,sep=angular_vector(ra,dec,rra,rdec)
        q.append((sep,r))
    if not q:raise RuntimeError(f"{tile}: cannot resolve science native row")
    q.sort(key=lambda z:z[0])
    if q[0][0]>.05:
        raise RuntimeError(f"{tile}: nearest science native row is {q[0][0]:.3f}\" away")
    return q[0][1]


def robust_plane(cut,xx,yy,mask):
    use=mask & np.isfinite(cut)
    if np.count_nonzero(use)<80:
        raise RuntimeError("insufficient background pixels")
    X=np.column_stack([np.ones(np.count_nonzero(use)),
                       xx[use],yy[use]])
    z=cut[use]
    keep=np.ones(len(z),bool)
    beta=np.array([np.median(z),0.0,0.0])
    for _ in range(BACKGROUND_CLIP_ITERS):
        beta,*_=np.linalg.lstsq(X[keep],z[keep],rcond=None)
        resid=z-X@beta
        med=np.median(resid[keep])
        mad=np.median(np.abs(resid[keep]-med))
        sig=1.4826*mad
        if not(sig>0):break
        new=np.abs(resid-med)<=BACKGROUND_CLIP_SIGMA*sig
        if np.array_equal(new,keep):break
        keep=new
    plane=beta[0]+beta[1]*xx+beta[2]*yy
    resid=cut-plane
    bgres=resid[use]
    med=np.median(bgres)
    sig=1.4826*np.median(np.abs(bgres-med))
    if not(sig>0):raise RuntimeError("invalid background sigma")
    return plane,resid,float(sig),beta


def weighted_centroid_and_shape(resid,rr,positive=True):
    z=resid if positive else -resid
    mask=(rr<=FLUX_CENTROID_RADIUS)&np.isfinite(z)&(z>=FLUX_WEIGHT_MIN_SIGMA)
    # caller passes residual already normalized by sigma below
    if np.count_nonzero(mask)<2:
        return {"centroid_offset_px":None,"axis_ratio":None,
                "weighted_pixels":int(np.count_nonzero(mask))}
    yy,xx=np.indices(z.shape)
    w=np.where(mask,z,0.0)
    ws=float(w.sum())
    cx=float((w*xx).sum()/ws);cy=float((w*yy).sum()/ws)
    center_x=(z.shape[1]-1)/2;center_y=(z.shape[0]-1)/2
    dx=xx-cx;dy=yy-cy
    mxx=float((w*dx*dx).sum()/ws)
    myy=float((w*dy*dy).sum()/ws)
    mxy=float((w*dx*dy).sum()/ws)
    ev=np.linalg.eigvalsh([[mxx,mxy],[mxy,myy]])
    ev=np.sort(np.clip(ev,0,None))
    axis=math.sqrt(ev[0]/ev[1]) if ev[1]>0 else None
    return {
        "centroid_x_stamp":cx,"centroid_y_stamp":cy,
        "centroid_offset_px":math.hypot(cx-center_x,cy-center_y),
        "axis_ratio":axis,
        "weighted_pixels":int(np.count_nonzero(mask))
    }


def measure(meta,gx,gy):
    a=load_arr(meta);ex0,ex1,ey0,ey1=meta["extended"]
    px=gx-ex0;py=gy-ey0
    ix=int(round(px));iy=int(round(py))
    R=STAMP_RADIUS
    x0=ix-R;x1=ix+R+1;y0=iy-R;y1=iy+R+1
    if x0<0 or y0<0 or x1>a.shape[1] or y1>a.shape[0]:
        return {"status":"STAMP_OUTSIDE_TILE"}
    cut=np.asarray(a[y0:y1,x0:x1],float)
    yy,xx=np.indices(cut.shape)
    cx=px-x0;cy=py-y0
    rr=np.hypot(xx-cx,yy-cy)
    bgmask=(rr>=BACKGROUND_INNER)&(rr<=BACKGROUND_OUTER)
    plane,resid,sigma,beta=robust_plane(cut,xx,yy,bgmask)
    z=resid/sigma

    # Re-center grid on exact fractional science/control coordinate for offsets.
    sm=gaussian_filter(resid,GAUSSIAN_SIGMA_PX,mode="nearest")/sigma
    search=rr<=CENTER_SEARCH_RADIUS
    pscore=np.where(search,sm,-np.inf)
    nscore=np.where(search,sm,np.inf)
    pyi,pxi=np.unravel_index(int(np.argmax(pscore)),sm.shape)
    nyi,nxi=np.unravel_index(int(np.argmin(nscore)),sm.shape)
    poff=math.hypot(pxi-cx,pyi-cy)
    noff=math.hypot(nxi-cx,nyi-cy)

    # Exact-coordinate smoothed value by bilinear interpolation.
    def bilinear(im,x,y):
        xlo=int(math.floor(x));ylo=int(math.floor(y))
        xhi=min(xlo+1,im.shape[1]-1);yhi=min(ylo+1,im.shape[0]-1)
        tx=x-xlo;ty=y-ylo
        return float((1-tx)*(1-ty)*im[ylo,xlo]+tx*(1-ty)*im[ylo,xhi]+
                     (1-tx)*ty*im[yhi,xlo]+tx*ty*im[yhi,xhi])

    center_sm=bilinear(sm,cx,cy)

    # Centroid/shape routine expects z centered in the stamp, so shift the
    # coordinate frame by measuring on a small extracted window centered on
    # nearest pixel. Fractional-center difference is recorded separately.
    r7=rr<=FLUX_CENTROID_RADIUS
    zz=np.where(r7,z,0.0)
    # Weighted moments explicitly relative to exact cx/cy.
    def moment(sign):
        w=np.clip(sign*z-FLUX_WEIGHT_MIN_SIGMA,0,None)*r7
        ws=float(w.sum())
        if ws<=0:return (None,None,0)
        wx=float((w*xx).sum()/ws);wy=float((w*yy).sum()/ws)
        dx=xx-wx;dy=yy-wy
        mxx=float((w*dx*dx).sum()/ws);myy=float((w*dy*dy).sum()/ws)
        mxy=float((w*dx*dy).sum()/ws)
        ev=np.sort(np.clip(np.linalg.eigvalsh([[mxx,mxy],[mxy,myy]]),0,None))
        axis=math.sqrt(ev[0]/ev[1]) if ev[1]>0 else None
        return math.hypot(wx-cx,wy-cy),axis,int(np.count_nonzero(w>0))

    pcent,paxis,pnp=moment(+1)
    ncent,naxis,nnp=moment(-1)

    apert={}
    for rad in (2,3,5,7):
        m=(rr<=rad)&np.isfinite(resid)
        vals=resid[m]
        apert[f"ap{rad}_signed_z"]=float(vals.sum()/(sigma*math.sqrt(max(len(vals),1))))
        apert[f"ap{rad}_positive_flux_sigma"]=float(np.clip(vals,0,None).sum()/sigma)
        apert[f"ap{rad}_negative_flux_sigma"]=float(np.clip(-vals,0,None).sum()/sigma)

    pos3=apert["ap3_positive_flux_sigma"]
    pos7=apert["ap7_positive_flux_sigma"]
    concentration=pos3/pos7 if pos7>0 else None

    # Strong structure within 25 px on smoothed map.
    wide=rr<=STRUCTURE_SEARCH_RADIUS
    wp=np.where(wide,sm,-np.inf);wn=np.where(wide,sm,np.inf)
    wyp,wxp=np.unravel_index(int(np.argmax(wp)),sm.shape)
    wyn,wxn=np.unravel_index(int(np.argmin(wn)),sm.shape)
    wide_p=float(wp[wyp,wxp]);wide_n=float(wn[wyn,wxn])

    return {
        "status":"SUCCESS",
        "background_sigma":sigma,
        "background_plane_dx_per_px":float(beta[1]),
        "background_plane_dy_per_px":float(beta[2]),
        "pixel_scale_arcsec":None, # caller fills from transform
        "gaussian_center_z":center_sm,
        "positive_gaussian_peak_z_r7":float(sm[pyi,pxi]),
        "positive_gaussian_peak_offset_px_r7":poff,
        "negative_gaussian_trough_z_r7":float(sm[nyi,nxi]),
        "negative_gaussian_trough_offset_px_r7":noff,
        "positive_flux_centroid_offset_px_r7":pcent,
        "positive_flux_axis_ratio_r7":paxis,
        "positive_flux_weighted_pixels_r7":pnp,
        "negative_flux_centroid_offset_px_r7":ncent,
        "negative_flux_axis_ratio_r7":naxis,
        "negative_flux_weighted_pixels_r7":nnp,
        "positive_concentration_r3_r7":concentration,
        "nearest_strong_positive_z_r25":wide_p,
        "nearest_strong_positive_offset_px_r25":math.hypot(wxp-cx,wyp-cy),
        "nearest_strong_negative_z_r25":wide_n,
        "nearest_strong_negative_offset_px_r25":math.hypot(wxn-cx,wyn-cy),
        **apert
    }


def pct(vals,q):
    a=np.asarray([x for x in vals if x is not None and math.isfinite(float(x))],float)
    if a.size==0:return None
    return float(np.quantile(a,q))


def classify(sc,controls):
    if sc.get("status")!="SUCCESS":
        return "MEASUREMENT_FAILED",{}
    if len(controls)<MIN_CONTROLS_FOR_DESCRIPTIVE:
        return "INSUFFICIENT_STELLAR_CONTROLS",{"control_count":len(controls)}

    metrics={}
    poff95=pct([c["positive_gaussian_peak_offset_px_r7"] for c in controls],.95)
    pcent95=pct([c["positive_flux_centroid_offset_px_r7"] for c in controls],.95)
    axis05=pct([c["positive_flux_axis_ratio_r7"] for c in controls],.05)
    conc05=pct([c["positive_concentration_r3_r7"] for c in controls],.05)
    conc95=pct([c["positive_concentration_r3_r7"] for c in controls],.95)
    gz05=pct([c["gaussian_center_z"] for c in controls],.05)
    metrics.update({
        "control_count":len(controls),
        "control_positive_peak_offset_p95_px":poff95,
        "control_positive_centroid_offset_p95_px":pcent95,
        "control_axis_ratio_p05":axis05,
        "control_concentration_p05":conc05,
        "control_concentration_p95":conc95,
        "control_gaussian_center_z_p05":gz05,
    })

    gz=sc["gaussian_center_z"]
    if gz>=3.0:
        checks=[]
        if poff95 is not None:checks.append(sc["positive_gaussian_peak_offset_px_r7"]<=max(poff95,1.0))
        if pcent95 is not None and sc["positive_flux_centroid_offset_px_r7"] is not None:
            checks.append(sc["positive_flux_centroid_offset_px_r7"]<=max(pcent95,1.0))
        if axis05 is not None and sc["positive_flux_axis_ratio_r7"] is not None:
            checks.append(sc["positive_flux_axis_ratio_r7"]>=axis05)
        if None not in (conc05,conc95,sc["positive_concentration_r3_r7"]):
            checks.append(conc05<=sc["positive_concentration_r3_r7"]<=conc95)
        metrics["positive_stellar_checks_passed"]=int(sum(checks))
        metrics["positive_stellar_checks_total"]=len(checks)
        if len(checks)>=3 and sum(checks)>=3:
            return "POSITIVE_STARLIKE_CENTERING_DESCRIPTIVE",metrics
        return "POSITIVE_FLUX_OFFCENTER_OR_NONSTELLAR_DESCRIPTIVE",metrics

    if gz<=-1.0:
        # No negative-star reference population exists; describe centering only.
        neg_centered=(sc["negative_gaussian_trough_offset_px_r7"]<=2.0 and
                      (sc["negative_flux_centroid_offset_px_r7"] is None or
                       sc["negative_flux_centroid_offset_px_r7"]<=2.5))
        metrics["negative_structure_centered"]=neg_centered
        if neg_centered:
            return "CENTERED_NEGATIVE_DEFICIT_DESCRIPTIVE",metrics
        return "OFFCENTER_NEGATIVE_OR_COMPLEX_STRUCTURE_DESCRIPTIVE",metrics

    return "LOW_CONTRAST_OR_MIXED_STRUCTURE_UNRESOLVED",metrics


def main():
    print("="*128)
    print("ORDER 01 — POSS PHYSICAL SOURCE CENTERING / LOCAL-STRUCTURE AUDIT v028v")
    print("="*128)
    print("NO NETWORK ACCESS.")
    print("SCIENCE PIXELS ARE READ.")
    print("Frozen transient detector is NOT rerun.\n")

    for p in (STRICT,POSS_CAND,V028P_REFS,V028U_JSON,INJ):
        if not p.is_file():
            print(f"FAIL missing input: {p}");return 2

    vu=json.loads(V028U_JSON.read_text(encoding="utf-8"))
    if vu.get("status")!="OFFICIAL_DR7_DISAGREES_WITH_V028Q_PIXEL_OFFSET":
        raise RuntimeError("v028u adjudication guard not satisfied")
    if vu.get("guards",{}).get("candidate_state_mutation") is not False:
        raise RuntimeError("v028u state guard mismatch")

    strict_rows=read_csv(STRICT);native=read_csv(POSS_CAND);vpr=read_csv(V028P_REFS)
    strict={i(r["strict_rank"]):r for r in strict_rows if i(r["strict_rank"]) in EXPECTED}
    if sorted(strict)!=EXPECTED:raise RuntimeError("strict survivor mismatch")

    inv=inventory()
    tiles={str(pick(strict[r],"poss_tile_id")) for r in EXPECTED}
    for t in tiles:
        if t not in inv:raise RuntimeError(f"missing tile inventory {t}")
    tr={t:fit_transform(native,t) for t in sorted(tiles)}
    for tid,t in tr.items():
        if not(t.validation["forward_ok"] and t.validation["inverse_ok"]):
            raise RuntimeError(f"{tid}: transform validation failed")

    # Optional but strong SHA cross-check against frozen injection report.
    inj=json.loads(INJ.read_text(encoding="utf-8"))
    emap={}
    for e in inj.get("endpoint_summaries",[]):
        try:rank=int(e.get("strict_rank"))
        except Exception:continue
        if rank in EXPECTED and str(e.get("archive"))=="POSS":
            emap[rank]=e
    for rank in EXPECTED:
        tid=str(pick(strict[rank],"poss_tile_id"))
        if rank in emap:
            e=emap[rank]
            if str(e.get("tile_id"))!=tid:raise RuntimeError(f"#{rank}: injection tile mismatch")
            h=str(e.get("native_npy_sha256") or "").lower()
            if h and h!=inv[tid]["sha256"]:raise RuntimeError(f"#{rank}: injection SHA mismatch")
    print("Frozen v028u/rank/tile/hash/transform guards: PASS\n")

    science_native={r:resolve_science_native(strict[r],native) for r in EXPECTED}

    # Build positive ordinary-star control pool separately for each rank/tile.
    controls_by_rank={r:[] for r in EXPECTED}
    control_rows=[]
    for g in vpr:
        rank=i(g.get("strict_rank"))
        if rank not in EXPECTED:continue
        if str(g.get("poss_status",""))!="SUCCESS":continue
        if i(g.get("poss_peak_sign"))!=CONTROL_REQUIRED_SIGN:continue
        gx=f(g.get("poss_centroid_x"));gy=f(g.get("poss_centroid_y"))
        gra=f(g.get("ra_target_deg"));gdec=f(g.get("dec_target_deg"))
        if None in (gx,gy,gra,gdec):continue
        tid=str(pick(strict[rank],"poss_tile_id"))
        mra,mdec=tr[tid].pixel_to_sky(gx,gy)
        _,_,gres=angular_vector(gra,gdec,mra,mdec)
        if gres>CONTROL_MAX_GAIA_RESID_ARCSEC:continue
        met=measure(inv[tid],gx,gy)
        if met.get("status")!="SUCCESS":continue
        scale=tr[tid].local_scale(gx,gy);met["pixel_scale_arcsec"]=scale
        row={
            "strict_rank":rank,"source_id":g.get("source_id"),
            "g_mag":f(g.get("g_mag")),"tile_id":tid,
            "gaia_resid_arcsec":gres,"global_x":gx,"global_y":gy,**met
        }
        controls_by_rank[rank].append(row);control_rows.append(row)

    print("Accepted same-tile positive Gaia controls:")
    for rank in EXPECTED:
        print(f"  #{rank}: {len(controls_by_rank[rank])}")
    print()

    results=[]
    for rank in EXPECTED:
        nr=science_native[rank]
        tid=str(nr["tile_id"])
        gx=f(nr["global_x"]);gy=f(nr["global_y"])
        met=measure(inv[tid],gx,gy)
        scale=tr[tid].local_scale(gx,gy)
        if met.get("status")=="SUCCESS":
            met["pixel_scale_arcsec"]=scale
            # convenient angular offsets
            for key in (
                "positive_gaussian_peak_offset_px_r7",
                "negative_gaussian_trough_offset_px_r7",
                "positive_flux_centroid_offset_px_r7",
                "negative_flux_centroid_offset_px_r7",
                "nearest_strong_positive_offset_px_r25",
                "nearest_strong_negative_offset_px_r25",
            ):
                val=met.get(key)
                met[key.replace("_px_","_arcsec_") if "_px_" in key else key+"_arcsec"] = (
                    None if val is None else val*scale
                )
        label,ctx=classify(met,controls_by_rank[rank])
        prior=("POSITIVE_INTEGRATED_V028O" if rank in POSITIVE_INTEGRATED_PRIOR else
               "MIXED_V028O" if rank in MIXED_PRIOR else
               "NEGATIVE_V028O")
        row={
            "strict_rank":rank,"tile_id":tid,
            "candidate_index":i(nr.get("candidate_index")),
            "global_x":gx,"global_y":gy,
            "v028o_prior_physical_sign":prior,
            "control_count":len(controls_by_rank[rank]),
            "descriptive_classification":label,
            **met,**{f"context_{k}":v for k,v in ctx.items()}
        }
        results.append(row)

        print(
            f"#{rank}: controls={len(controls_by_rank[rank])} "
            f"centerG={met.get('gaussian_center_z')} "
            f"+peakOff={met.get('positive_gaussian_peak_offset_px_r7')}px "
            f"+centOff={met.get('positive_flux_centroid_offset_px_r7')}px "
            f"-troughOff={met.get('negative_gaussian_trough_offset_px_r7')}px "
            f"axis+={met.get('positive_flux_axis_ratio_r7')} "
            f"conc={met.get('positive_concentration_r3_r7')} "
            f"=> {label}"
        )

    fields=sorted({k for r in results for k in r.keys()})
    write_csv(OUT_CSV,results,fields)
    cfields=sorted({k for r in control_rows for k in r.keys()})
    write_csv(OUT_CTRL,control_rows,cfields)

    payload={
        "stage":"ORDER01_POSS_PHYSICAL_SOURCE_CENTERING_V028V",
        "frozen_active_ranks":EXPECTED,
        "guards":{
            "network_access":False,
            "science_pixels_read":True,
            "candidate_pixels_used_as_stellar_reference_distribution":False,
            "transient_detector_rerun":False,
            "transient_detector_parameters_changed":False,
            "candidate_state_mutation":False,
            "candidate_promotion":False,
            "candidate_deletion":False,
            "weighted_candidate_score":False,
            "v028u_plate_offset_interpretation_retired":True,
        },
        "fixed_policy":{
            "control_max_gaia_resid_arcsec":CONTROL_MAX_GAIA_RESID_ARCSEC,
            "background_annulus_px":[BACKGROUND_INNER,BACKGROUND_OUTER],
            "gaussian_sigma_px":GAUSSIAN_SIGMA_PX,
            "center_search_radius_px":CENTER_SEARCH_RADIUS,
            "flux_centroid_radius_px":FLUX_CENTROID_RADIUS,
            "structure_search_radius_px":STRUCTURE_SEARCH_RADIUS,
            "strong_structure_sigma":STRONG_STRUCTURE_SIGMA,
        },
        "control_counts_by_rank":{str(r):len(controls_by_rank[r]) for r in EXPECTED},
        "results":results,
        "interpretive_boundary":(
            "This stage measures raw POSS image structure at the frozen science "
            "coordinate and compares positive-source centering/morphology to "
            "ordinary Gaia-tied stellar images on the same tile. A star-like "
            "positive morphology supports, but cannot prove, an added-light "
            "interpretation. Negative or off-center structure weighs against a "
            "simple added-light point source but does not identify a specific "
            "plate defect. No candidate state is changed."
        )
    }
    write_json(OUT_JSON,payload)

    md=[
        "# ORDER 01 — POSS Physical Source Centering / Local-Structure Audit v028v","",
        "## Guard state","",
        "- No network access.",
        "- Science pixels were read.",
        "- Candidate pixels were not used in the stellar reference distributions.",
        "- The frozen transient detector was not rerun.",
        "- No candidate was promoted, deleted, or otherwise mutated.",
        "- The v028q ~20 arcsec plate-offset interpretation is retired by v028u.","",
        "## Results","",
        "| rank | v028o prior | controls | Gaussian center Z | +peak offset | +centroid offset | -trough offset | +axis ratio | +concentration | classification |",
        "|---:|---|---:|---:|---:|---:|---:|---:|---:|---|"
    ]
    for r in results:
        def fm(k,d=2):
            v=r.get(k)
            return "n/a" if v is None else f"{v:.{d}f}"
        md.append(
            f"| #{r['strict_rank']} | `{r['v028o_prior_physical_sign']}` | "
            f"{r['control_count']} | {fm('gaussian_center_z')} | "
            f"{fm('positive_gaussian_peak_offset_px_r7')} px | "
            f"{fm('positive_flux_centroid_offset_px_r7')} px | "
            f"{fm('negative_gaussian_trough_offset_px_r7')} px | "
            f"{fm('positive_flux_axis_ratio_r7')} | "
            f"{fm('positive_concentration_r3_r7')} | "
            f"`{r['descriptive_classification']}` |"
        )
    md += ["","## Interpretation boundary","",payload["interpretive_boundary"]]
    OUT_MD.write_text("\n".join(md),encoding="utf-8")

    print("\nOutputs:")
    print(f"  {OUT_JSON}")
    print(f"  {OUT_CSV}")
    print(f"  {OUT_CTRL}")
    print(f"  {OUT_MD}")
    print()
    print("NO network query was made.")
    print("SCIENCE PIXELS WERE READ.")
    print("Candidate pixels were NOT stellar reference-distribution inputs.")
    print("Transient detector was NOT rerun.")
    print("No candidate was promoted or deleted.")
    return 0


if __name__=="__main__":
    raise SystemExit(main())
