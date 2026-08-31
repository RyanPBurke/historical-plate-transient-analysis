#!/usr/bin/env python3
"""
ORDER 01 â€” plate-level registered bright-Gaia astrometry v028q

This is a refinement of v028p, not a new transient search.

v028p demonstrated that bright ordinary stars can be detected on ai43437, but
its 30" blind guided search allowed the coarse (~13"/pixel) DASCH image to jump
between neighbouring peaks.  v028q uses only the already-selected/frozen v028p
Gaia controls and proceeds in two explicit phases:

A. INITIAL PLATE REGISTRATION
   - Reconstruct measured sky positions from v028p sub-pixel centroids.
   - Retain only high-confidence ordinary-star associations:
       POSS SUCCESS, positive, <=10" from Gaia;
       DASCH SUCCESS, positive, >=5 sigma.
   - Estimate a robust plate-level DASCH-minus-Gaia offset vector.

B. REGISTERED DASCH RECENTROID
   - Shift each Gaia prediction by the frozen phase-A offset.
   - Search only one DASCH pixel around that registered prediction.
   - Search POSITIVE flux only (ordinary stars on this plate are positive).
   - Require >=5 sigma for the primary reference set.
   - Re-centroid sub-pixel within a 2-pixel positive-flux footprint.

The resulting same-Gaia POSS<->DASCH vectors are then pooled across the single
shared physical plate pair (POSS 06S2 / DASCH ai43437).  Translation and
first-order spatial models are evaluated with leave-one-out residuals.  The
simpler model is retained unless the affine model is sufficiently supported
and improves cross-validated scatter.

Only after the ordinary-star model is frozen are the six science pair vectors
compared with it.

Guards
------
No network access in v028q: it reuses v028p's frozen/cached Gaia selection.
Science NPY pixels are read.
Candidate pixels are NOT reference-fit inputs.
Frozen transient detector is NOT rerun.
No candidate is promoted/deleted/mutated.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
import statistics
from pathlib import Path
from typing import Any

import numpy as np
from scipy.optimize import least_squares

ROOT = Path.cwd()
BASE = ROOT / "results" / "order01_native_full_v028"
WORK = ROOT / "work" / "order01_native_full_v028"

V028P_JSON = BASE / "order01_bright_gaia_subpixel_astrometry_v028p.json"
V028P_REFS = BASE / "order01_bright_gaia_subpixel_references_v028p.csv"
STRICT = BASE / "order01_strict_match_triage_v028.csv"
POSS_CAND = BASE / "order01_poss_native_candidates.csv"
DASCH_CAND = BASE / "order01_dasch_native_candidates.csv"
INJ = BASE / "order01_injection_recovery_report_v028.json"

POSS_TILE_DIR = WORK / "poss_tiles"
DASCH_TILE_DIR = WORK / "dasch_tiles"

OUT_JSON = BASE / "order01_plate_registered_bright_gaia_astrometry_v028q.json"
OUT_CSV = BASE / "order01_plate_registered_bright_gaia_astrometry_v028q.csv"
OUT_REFS = BASE / "order01_plate_registered_bright_gaia_references_v028q.csv"
OUT_MD = BASE / "ORDER01_PLATE_REGISTERED_BRIGHT_GAIA_ASTROMETRY_V028Q.md"

EXPECTED = [10, 24, 25, 26, 29, 30]

# Phase A guards.
INITIAL_POSS_MAX_GAIA_RESID_ARCSEC = 10.0
INITIAL_DASCH_MIN_SNR = 5.0
INITIAL_REQUIRED_SIGN = 1
MIN_INITIAL_REGISTRATION_STARS = 5

# Phase B registered search.
REGISTERED_SEARCH_RADIUS_PIXELS = 1.0
REGISTERED_DASCH_CENTROID_RADIUS_PX = 2.0
REGISTERED_PRIMARY_MIN_SNR = 5.0
REGISTERED_DIAGNOSTIC_MIN_SNR = 3.5
MIN_BACKGROUND_PIXELS = 40

# Final common-reference quality.
FINAL_POSS_MAX_GAIA_RESID_ARCSEC = 10.0
MIN_FINAL_REFERENCES_DESCRIPTIVE = 5
MIN_FINAL_REFERENCES_AFFINE = 8

# Model selection.  Affine must improve leave-one-out p95 by at least this
# fraction, otherwise translation is retained.
AFFINE_REQUIRED_P95_IMPROVEMENT = 0.20

POLY_DEGREES = [1, 2, 3]
MAX_FORWARD_P95_ARCSEC = 0.35
MAX_INVERSE_P95_PX = 0.20


def f(v: Any) -> float:
    return float(str(v).strip())


def i(v: Any) -> int:
    return int(float(str(v).strip()))


def truth(v: Any) -> bool:
    return str(v).strip().lower() in {"true", "1", "yes", "y", "t"}


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    tmp.replace(path)


def write_json(path: Path, obj: Any) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, indent=2, sort_keys=True, default=str) + "\n",
                   encoding="utf-8")
    tmp.replace(path)


def sha_file(path: Path, block: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for b in iter(lambda: fh.read(block), b""):
            h.update(b)
    return h.hexdigest()


def tangent_xy(ra, dec, ra0: float, dec0: float):
    return (
        (np.asarray(ra, dtype=float) - ra0)
        * 3600.0 * math.cos(math.radians(dec0)),
        (np.asarray(dec, dtype=float) - dec0) * 3600.0,
    )


def tangent_vector(ra1, dec1, ra2, dec2):
    dec0 = 0.5 * (dec1 + dec2)
    east = (ra2 - ra1) * 3600.0 * math.cos(math.radians(dec0))
    north = (dec2 - dec1) * 3600.0
    return east, north, math.hypot(east, north), (
        math.degrees(math.atan2(east, north)) % 360.0
    )


def offset_sky(ra: float, dec: float, east_arcsec: float, north_arcsec: float):
    out_dec = dec + north_arcsec / 3600.0
    out_ra = ra + east_arcsec / (
        3600.0 * max(math.cos(math.radians(dec)), 1e-12)
    )
    return out_ra, out_dec


def poly_terms(x: np.ndarray, y: np.ndarray, degree: int) -> np.ndarray:
    cols = [np.ones_like(x)]
    for total in range(1, degree + 1):
        for xp in range(total, -1, -1):
            yp = total - xp
            cols.append((x ** xp) * (y ** yp))
    return np.column_stack(cols)


class Transform:
    def __init__(self, x0, y0, pscale, ra0, dec0, sscale,
                 fdeg, fx, fy, ideg, ix, iy, validation):
        self.x0=x0; self.y0=y0; self.pscale=pscale
        self.ra0=ra0; self.dec0=dec0; self.sscale=sscale
        self.fdeg=fdeg; self.fx=fx; self.fy=fy
        self.ideg=ideg; self.ix=ix; self.iy=iy
        self.validation=validation

    def pixel_to_sky(self, gx, gy):
        px=(np.atleast_1d(np.asarray(gx,float))-self.x0)/self.pscale
        py=(np.atleast_1d(np.asarray(gy,float))-self.y0)/self.pscale
        A=poly_terms(px,py,self.fdeg)
        sx=(A@self.fx)*self.sscale
        sy=(A@self.fy)*self.sscale
        ra=self.ra0+sx/(3600.0*math.cos(math.radians(self.dec0)))
        dec=self.dec0+sy/3600.0
        if np.ndim(gx)==0:
            return float(ra[0]),float(dec[0])
        return ra,dec

    def sky_to_pixel(self, ra, dec):
        sx,sy=tangent_xy(np.atleast_1d(np.asarray(ra,float)),
                         np.atleast_1d(np.asarray(dec,float)),
                         self.ra0,self.dec0)
        sx=np.asarray(sx)/self.sscale; sy=np.asarray(sy)/self.sscale
        A=poly_terms(sx,sy,self.ideg)
        gx=(A@self.ix)*self.pscale+self.x0
        gy=(A@self.iy)*self.pscale+self.y0
        if np.ndim(ra)==0:
            return float(gx[0]),float(gy[0])
        return gx,gy

    def local_scale(self,gx,gy):
        r0,d0=self.pixel_to_sky(gx,gy)
        r1,d1=self.pixel_to_sky(gx+1,gy)
        r2,d2=self.pixel_to_sky(gx,gy+1)
        _,_,sx,_=tangent_vector(r0,d0,r1,d1)
        _,_,sy,_=tangent_vector(r0,d0,r2,d2)
        return float(statistics.median([q for q in (sx,sy) if q>0]))


def fit_transform(rows, tile_id):
    pts=[]
    for r in rows:
        if str(r.get("tile_id","")) != tile_id:
            continue
        try:
            pts.append((f(r["global_x"]),f(r["global_y"]),
                        f(r["ra_deg"]),f(r["dec_deg"])))
        except Exception:
            continue
    if len(pts)<30:
        raise RuntimeError(f"{tile_id}: only {len(pts)} WCS rows")
    a=np.asarray(pts,float); gx,gy,ra,dec=a.T
    x0=float(np.median(gx)); y0=float(np.median(gy))
    pscale=max(float(np.ptp(gx)),float(np.ptp(gy)),512.0)/2
    ra0=float(np.median(ra)); dec0=float(np.median(dec))
    sx,sy=tangent_xy(ra,dec,ra0,dec0); sx=np.asarray(sx); sy=np.asarray(sy)
    sscale=max(float(np.ptp(sx)),float(np.ptp(sy)),100.0)/2
    px=(gx-x0)/pscale; py=(gy-y0)/pscale
    snx=sx/sscale; sny=sy/sscale
    order=np.lexsort((gy,gx)); test=np.zeros(len(a),bool); test[order[::5]]=True
    train=~test

    fb=None
    for deg in POLY_DEGREES:
        A=poly_terms(px,py,deg)
        cx,*_=np.linalg.lstsq(A[train],snx[train],rcond=None)
        cy,*_=np.linalg.lstsq(A[train],sny[train],rcond=None)
        rr=np.hypot((A[test]@cx)*sscale-sx[test],
                    (A[test]@cy)*sscale-sy[test])
        p95=float(np.quantile(rr,.95))
        if fb is None or p95<fb[0]: fb=(p95,deg)
        if p95<=.05: break
    fdeg=fb[1]; A=poly_terms(px,py,fdeg)
    fx,*_=np.linalg.lstsq(A,snx,rcond=None); fy,*_=np.linalg.lstsq(A,sny,rcond=None)

    ib=None
    for deg in POLY_DEGREES:
        A=poly_terms(snx,sny,deg)
        cx,*_=np.linalg.lstsq(A[train],px[train],rcond=None)
        cy,*_=np.linalg.lstsq(A[train],py[train],rcond=None)
        rr=np.hypot((A[test]@cx)*pscale+x0-gx[test],
                    (A[test]@cy)*pscale+y0-gy[test])
        p95=float(np.quantile(rr,.95))
        if ib is None or p95<ib[0]: ib=(p95,deg)
        if p95<=.05: break
    ideg=ib[1]; A=poly_terms(snx,sny,ideg)
    ix,*_=np.linalg.lstsq(A,px,rcond=None); iy,*_=np.linalg.lstsq(A,py,rcond=None)

    val={"forward_p95_arcsec":fb[0],"inverse_p95_px":ib[0],
         "forward_ok":fb[0]<=MAX_FORWARD_P95_ARCSEC,
         "inverse_ok":ib[0]<=MAX_INVERSE_P95_PX}
    return Transform(x0,y0,pscale,ra0,dec0,sscale,
                     fdeg,fx,fy,ideg,ix,iy,val)


def load_inventory(tile_dir: Path, archive: str):
    out={}
    for jp in sorted(tile_dir.glob("*.json")):
        try:o=json.loads(jp.read_text(encoding="utf-8"))
        except Exception:continue
        if o.get("complete") is not True:continue
        tid=str(o.get("tile_id","")).strip(); ext=o.get("extended"); ref=o.get("npy_path")
        if not tid or not isinstance(ext,list) or len(ext)!=4 or not ref:continue
        p=Path(str(ref)); p=p if p.is_absolute() else ROOT/p
        if not p.is_file():raise RuntimeError(f"{archive} {tid}: missing {p}")
        actual=sha_file(p); rec=str(o.get("npy_file_sha256") or "").lower()
        if rec and rec!=actual:raise RuntimeError(f"{archive} {tid}: SHA mismatch")
        out[tid]={"archive":archive,"tile_id":tid,"extended":tuple(map(int,ext)),
                  "npy_path":p,"npy_sha256":actual}
    return out


ARR={}
def load_array(meta):
    key=(meta["archive"],meta["tile_id"])
    if key in ARR:return ARR[key]
    a=np.load(meta["npy_path"],mmap_mode="r")
    ex0,ex1,ey0,ey1=meta["extended"]
    if a.shape!=(ey1-ey0,ex1-ex0):raise RuntimeError(f"{key}: shape mismatch")
    ARR[key]=a;return a


def reconstruct_measurement(row, prefix, tr):
    if str(row.get(f"{prefix}_status",""))!="SUCCESS":
        return None
    if not str(row.get(f"{prefix}_centroid_x","")).strip():
        return None
    gx=f(row[f"{prefix}_centroid_x"]); gy=f(row[f"{prefix}_centroid_y"])
    mra,mdec=tr.pixel_to_sky(gx,gy)
    gra=f(row["ra_target_deg"]); gdec=f(row["dec_target_deg"])
    e,n,r,pa=tangent_vector(gra,gdec,mra,mdec)
    return {"ra_deg":mra,"dec_deg":mdec,"east_gaia_arcsec":e,
            "north_gaia_arcsec":n,"resid_gaia_arcsec":r,
            "centroid_x":gx,"centroid_y":gy}


def registered_dasch_centroid(meta,tr,gaia_ra,gaia_dec,reg_east,reg_north):
    cra,cdec=offset_sky(gaia_ra,gaia_dec,reg_east,reg_north)
    gx,gy=tr.sky_to_pixel(cra,cdec)
    scale=tr.local_scale(gx,gy)
    a=load_array(meta); ex0,ex1,ey0,ey1=meta["extended"]
    px=gx-ex0;py=gy-ey0

    sr=REGISTERED_SEARCH_RADIUS_PIXELS
    cr=REGISTERED_DASCH_CENTROID_RADIUS_PX
    R=int(math.ceil(sr+cr+8))
    ix=int(round(px));iy=int(round(py))
    x0,x1=ix-R,ix+R+1;y0,y1=iy-R,iy+R+1
    if x0<0 or y0<0 or x1>a.shape[1] or y1>a.shape[0]:
        return {"status":"STAMP_OUTSIDE_TILE","registered_pred_x":gx,
                "registered_pred_y":gy,"scale_arcsec_px":scale}
    cut=np.asarray(a[y0:y1,x0:x1],float)
    yy,xx=np.indices(cut.shape); cx0=px-x0;cy0=py-y0
    rr=np.hypot(xx-cx0,yy-cy0)

    ann=cut[(rr>=sr+cr+2)&(rr<=R-1)&np.isfinite(cut)]
    if ann.size<MIN_BACKGROUND_PIXELS:
        return {"status":"INSUFFICIENT_BACKGROUND"}
    bg=float(np.median(ann))
    sig=1.4826*float(np.median(np.abs(ann-bg)))
    if not(sig>0):return {"status":"INVALID_BACKGROUND_SIGMA"}
    res=cut-bg

    # Ordinary stars on ai43437 are empirically positive.  Do not let a
    # negative defect win merely because abs(residual) is larger.
    valid=(rr<=sr)&np.isfinite(res)
    score=np.where(valid,res,-np.inf)
    pyi,pxi=np.unravel_index(int(np.argmax(score)),cut.shape)
    peak=float(res[pyi,pxi]); snr=peak/sig
    if snr<REGISTERED_DIAGNOSTIC_MIN_SNR:
        return {"status":"POSITIVE_PEAK_BELOW_3P5SIGMA","peak_snr":snr,
                "registered_pred_x":gx,"registered_pred_y":gy,
                "scale_arcsec_px":scale}

    rp=np.hypot(xx-pxi,yy-pyi)
    wt=np.clip(res,0,None)*(rp<=cr)
    ws=float(wt.sum())
    if ws<=0:return {"status":"INVALID_CENTROID_WEIGHTS","peak_snr":snr}
    cx=float((wt*xx).sum()/ws);cy=float((wt*yy).sum()/ws)
    cgx=ex0+x0+cx;cgy=ey0+y0+cy
    mra,mdec=tr.pixel_to_sky(cgx,cgy)
    e,n,r,pa=tangent_vector(gaia_ra,gaia_dec,mra,mdec)
    return {
        "status":("SUCCESS_PRIMARY" if snr>=REGISTERED_PRIMARY_MIN_SNR
                  else "SUCCESS_DIAGNOSTIC"),
        "peak_snr":snr,"peak_sign":1,
        "centroid_x":cgx,"centroid_y":cgy,
        "measured_ra_deg":mra,"measured_dec_deg":mdec,
        "gaia_east_resid_arcsec":e,"gaia_north_resid_arcsec":n,
        "gaia_resid_arcsec":r,
        "registered_pred_x":gx,"registered_pred_y":gy,
        "scale_arcsec_px":scale,
    }


def fit_translation(coords, vectors):
    med=np.median(vectors,axis=0)
    return {"kind":"translation","params":med.tolist()}


def predict_model(model, ra, dec, center):
    if model["kind"]=="translation":
        return np.array(model["params"],float)
    ra0,dec0=center
    x=(ra-ra0)*math.cos(math.radians(dec0))
    y=dec-dec0
    p=np.array(model["params"],float)
    return np.array([p[0]+p[1]*x+p[2]*y,
                     p[3]+p[4]*x+p[5]*y])


def fit_affine(coords, vectors, center):
    ra0,dec0=center
    x=(coords[:,0]-ra0)*math.cos(math.radians(dec0))
    y=coords[:,1]-dec0
    A=np.column_stack([np.ones(len(x)),x,y])
    def fun(p):
        pred=np.column_stack([A@p[:3],A@p[3:]])
        return (pred-vectors).ravel()
    init=np.r_[np.median(vectors[:,0]),0,0,
               np.median(vectors[:,1]),0,0]
    fit=least_squares(fun,init,loss="soft_l1",f_scale=5.0,max_nfev=500)
    return {"kind":"affine","params":fit.x.tolist(),"success":bool(fit.success)}


def loo_residuals(coords,vectors,kind,center):
    out=[]
    n=len(coords)
    if n<2:return out
    for j in range(n):
        keep=np.arange(n)!=j
        if kind=="translation":
            m=fit_translation(coords[keep],vectors[keep])
        else:
            if np.count_nonzero(keep)<6:return []
            m=fit_affine(coords[keep],vectors[keep],center)
        pred=predict_model(m,coords[j,0],coords[j,1],center)
        out.append(float(np.hypot(*(vectors[j]-pred))))
    return out


def p95(vals):
    if vals is None:
        return None
    arr = np.asarray(vals, dtype=float)
    if arr.size == 0:
        return None
    return float(np.quantile(arr, .95, method="higher"))


def main():
    print("="*128)
    print("ORDER 01 â€” PLATE-LEVEL REGISTERED BRIGHT-GAIA ASTROMETRY v028q")
    print("="*128)
    print("No network query. Reuses v028p Gaia selection.")
    print("SCIENCE PIXELS ARE READ. Candidate pixels are NOT reference-fit inputs.")
    print("Frozen transient detector is NOT rerun.\n")

    for p in (V028P_JSON,V028P_REFS,STRICT,POSS_CAND,DASCH_CAND,INJ):
        if not p.is_file():
            print(f"FAIL missing input: {p}");return 2

    pj=json.loads(V028P_JSON.read_text(encoding="utf-8"))
    if pj.get("frozen_active_ranks")!=EXPECTED:
        raise RuntimeError("v028p frozen ranks mismatch")
    if pj.get("guards",{}).get("candidate_pixels_used_as_reference_fit") is not False:
        raise RuntimeError("v028p candidate-reference guard mismatch")

    rows=read_csv(V028P_REFS);strict=read_csv(STRICT)
    prows=read_csv(POSS_CAND);drows=read_csv(DASCH_CAND)
    inj=json.loads(INJ.read_text(encoding="utf-8"))
    sr={i(r["strict_rank"]):r for r in strict if i(r["strict_rank"]) in EXPECTED}
    if sorted(sr)!=EXPECTED:raise RuntimeError("strict survivor mismatch")

    pinv=load_inventory(POSS_TILE_DIR,"POSS");dinv=load_inventory(DASCH_TILE_DIR,"DASCH")
    ptiles={str(sr[r]["poss_tile_id"]) for r in EXPECTED}
    dtiles={str(sr[r]["dasch_tile_id"]) for r in EXPECTED}
    pt={tid:fit_transform(prows,tid) for tid in sorted(ptiles)}
    dt={tid:fit_transform(drows,tid) for tid in sorted(dtiles)}
    for ts in (pt,dt):
        for tid,t in ts.items():
            if not(t.validation["forward_ok"] and t.validation["inverse_ok"]):
                raise RuntimeError(f"{tid}: transform validation failed")

    # NPY SHA guards against frozen injection report.
    emap={}
    for e in inj.get("endpoint_summaries",[]):
        try:r=int(e["strict_rank"])
        except Exception:continue
        a=str(e.get("archive",""))
        if r in EXPECTED and a in ("POSS","DASCH"):emap[(r,a)]=e
    for rank in EXPECTED:
        for a,tid,iv in (("POSS",str(sr[rank]["poss_tile_id"]),pinv),
                         ("DASCH",str(sr[rank]["dasch_tile_id"]),dinv)):
            e=emap[(rank,a)]
            if str(e.get("tile_id"))!=tid:raise RuntimeError(f"{rank} {a}: tile mismatch")
            h=str(e.get("native_npy_sha256","")).lower()
            if h and h!=iv[tid]["npy_sha256"]:raise RuntimeError(f"{rank} {a}: SHA mismatch")
    print("Frozen v028p/rank/tile/hash/transform guards: PASS\n")

    # ------------------------------------------------------------------
    # Phase A: reconstruct v028p Gaia residual vectors and freeze one
    # plate-level DASCH offset from high-confidence common bright stars.
    # ------------------------------------------------------------------
    initial=[]
    enriched=[]
    for r in rows:
        rank=i(r["strict_rank"])
        if rank not in EXPECTED:continue
        ptr=pt[str(sr[rank]["poss_tile_id"])]
        dtr=dt[str(sr[rank]["dasch_tile_id"])]
        pm=reconstruct_measurement(r,"poss",ptr)
        dm=reconstruct_measurement(r,"dasch",dtr)
        e=dict(r)
        if pm:
            e.update({
                "v028p_poss_east_gaia_arcsec":pm["east_gaia_arcsec"],
                "v028p_poss_north_gaia_arcsec":pm["north_gaia_arcsec"],
                "v028p_poss_reconstructed_gaia_resid_arcsec":pm["resid_gaia_arcsec"],
            })
        if dm:
            e.update({
                "v028p_dasch_east_gaia_arcsec":dm["east_gaia_arcsec"],
                "v028p_dasch_north_gaia_arcsec":dm["north_gaia_arcsec"],
                "v028p_dasch_reconstructed_gaia_resid_arcsec":dm["resid_gaia_arcsec"],
            })

        init_ok=(
            pm is not None and dm is not None
            and i(r["poss_peak_sign"])==INITIAL_REQUIRED_SIGN
            and i(r["dasch_peak_sign"])==INITIAL_REQUIRED_SIGN
            and pm["resid_gaia_arcsec"]<=INITIAL_POSS_MAX_GAIA_RESID_ARCSEC
            and f(r["dasch_peak_snr"])>=INITIAL_DASCH_MIN_SNR
        )
        e["initial_registration_reference"]=init_ok
        if init_ok:
            initial.append({
                "strict_rank":rank,"source_id":r["source_id"],
                "ra_target_deg":f(r["ra_target_deg"]),
                "dec_target_deg":f(r["dec_target_deg"]),
                "dasch_east_gaia_arcsec":dm["east_gaia_arcsec"],
                "dasch_north_gaia_arcsec":dm["north_gaia_arcsec"],
                "dasch_gaia_resid_arcsec":dm["resid_gaia_arcsec"],
            })
        enriched.append(e)

    if len(initial)<MIN_INITIAL_REGISTRATION_STARS:
        raise RuntimeError(
            f"only {len(initial)} initial registration stars; "
            f"need {MIN_INITIAL_REGISTRATION_STARS}"
        )

    init_vec=np.array([[q["dasch_east_gaia_arcsec"],q["dasch_north_gaia_arcsec"]]
                       for q in initial],float)
    init_med=np.median(init_vec,axis=0)
    init_res=np.hypot(*(init_vec-init_med).T)
    print("Phase A â€” initial plate registration:")
    print(f"  high-confidence stars: {len(initial)}")
    print(f"  DASCH-minus-Gaia median: east={init_med[0]:+.3f}\" north={init_med[1]:+.3f}\" "
          f"mag={math.hypot(*init_med):.3f}\"")
    print(f"  residual median={np.median(init_res):.3f}\" p95={p95(init_res):.3f}\"\n")

    # ------------------------------------------------------------------
    # Phase B: recenter every frozen v028p selected Gaia star around the
    # registered DASCH prediction using positive flux only.
    # ------------------------------------------------------------------
    final_rows=[]
    primary_refs=[]
    diagnostic_refs=[]

    for e in enriched:
        rank=i(e["strict_rank"])
        ptr=pt[str(sr[rank]["poss_tile_id"])]
        dtr=dt[str(sr[rank]["dasch_tile_id"])]
        dmeta=dinv[str(sr[rank]["dasch_tile_id"])]

        pm=reconstruct_measurement(e,"poss",ptr)
        gra=f(e["ra_target_deg"]);gdec=f(e["dec_target_deg"])
        dm=registered_dasch_centroid(dmeta,dtr,gra,gdec,
                                     float(init_med[0]),float(init_med[1]))

        row={
            "strict_rank":rank,"selection_order":i(e["selection_order"]),
            "source_id":e["source_id"],"g_mag":f(e["g_mag"]),
            "ra_target_deg":gra,"dec_target_deg":gdec,
            "initial_registration_reference":truth(e["initial_registration_reference"]),
            "poss_status":e["poss_status"],
            "poss_peak_snr":f(e["poss_peak_snr"]) if str(e.get("poss_peak_snr","")).strip() else None,
            "poss_peak_sign":i(e["poss_peak_sign"]) if str(e.get("poss_peak_sign","")).strip() else None,
            "poss_gaia_resid_arcsec":pm["resid_gaia_arcsec"] if pm else None,
            "registered_dasch_status":dm.get("status"),
            "registered_dasch_peak_snr":dm.get("peak_snr"),
            "registered_dasch_gaia_resid_arcsec":dm.get("gaia_resid_arcsec"),
            "registered_dasch_east_gaia_arcsec":dm.get("gaia_east_resid_arcsec"),
            "registered_dasch_north_gaia_arcsec":dm.get("gaia_north_resid_arcsec"),
            "registered_dasch_centroid_x":dm.get("centroid_x"),
            "registered_dasch_centroid_y":dm.get("centroid_y"),
        }

        poss_good=(
            pm is not None
            and row["poss_peak_sign"]==1
            and row["poss_gaia_resid_arcsec"]<=FINAL_POSS_MAX_GAIA_RESID_ARCSEC
        )
        diag_good=poss_good and dm.get("status") in ("SUCCESS_PRIMARY","SUCCESS_DIAGNOSTIC")
        prim_good=poss_good and dm.get("status")=="SUCCESS_PRIMARY"

        if diag_good:
            pra,pdec=pm["ra_deg"],pm["dec_deg"]
            dra,ddec=dm["measured_ra_deg"],dm["measured_dec_deg"]
            ce,cn,csep,cpa=tangent_vector(pra,pdec,dra,ddec)
            row.update({"cross_east_arcsec":ce,"cross_north_arcsec":cn,
                        "cross_separation_arcsec":csep,"cross_pa_deg":cpa})
            diagnostic_refs.append(row)
        if prim_good:
            primary_refs.append(row)
        row["final_primary_reference"]=prim_good
        row["final_diagnostic_reference"]=diag_good
        final_rows.append(row)

    print("Phase B â€” registered DASCH recenter:")
    print(f"  primary >=5sigma common references: {len(primary_refs)}")
    print(f"  diagnostic >=3.5sigma common references: {len(diagnostic_refs)}")
    if len(primary_refs)<MIN_FINAL_REFERENCES_DESCRIPTIVE:
        print("  NOTE: primary set remains sparse; diagnostic set will be reported separately.\n")
    else:
        print()

    # Primary set is authoritative.  Only if it is too sparse do we provide a
    # diagnostic model, explicitly labelled as such.
    if len(primary_refs)>=MIN_FINAL_REFERENCES_DESCRIPTIVE:
        fit_refs=primary_refs; fit_kind="PRIMARY_GE5SIGMA"
    elif len(diagnostic_refs)>=MIN_FINAL_REFERENCES_DESCRIPTIVE:
        fit_refs=diagnostic_refs; fit_kind="DIAGNOSTIC_GE3P5SIGMA_FALLBACK"
    else:
        fit_refs=[];fit_kind="INSUFFICIENT_AFTER_REGISTERED_RECENTER"

    result_rows=[]
    model_info={"reference_kind":fit_kind,"reference_count":len(fit_refs)}

    if fit_refs:
        coords=np.array([[f(q["ra_target_deg"]),f(q["dec_target_deg"])] for q in fit_refs],float)
        vec=np.array([[f(q["cross_east_arcsec"]),f(q["cross_north_arcsec"])] for q in fit_refs],float)
        center=(float(np.median(coords[:,0])),float(np.median(coords[:,1])))

        tmodel=fit_translation(coords,vec)
        tloo=loo_residuals(coords,vec,"translation",center)
        tp95=p95(tloo);tmed=float(np.median(tloo)) if tloo else None

        amodel=None;aloo=[];ap95=None;amed=None
        if len(fit_refs)>=MIN_FINAL_REFERENCES_AFFINE:
            amodel=fit_affine(coords,vec,center)
            aloo=loo_residuals(coords,vec,"affine",center)
            ap95=p95(aloo);amed=float(np.median(aloo)) if aloo else None

        use_affine=(
            amodel is not None and ap95 is not None and tp95 is not None
            and ap95 <= tp95*(1.0-AFFINE_REQUIRED_P95_IMPROVEMENT)
        )
        model=amodel if use_affine else tmodel
        selected_loo=aloo if use_affine else tloo
        selected_p95=ap95 if use_affine else tp95
        selected_med=amed if use_affine else tmed

        model_info.update({
            "model_center_ra_deg":center[0],
            "model_center_dec_deg":center[1],
            "translation_model":tmodel,
            "translation_loo_median_arcsec":tmed,
            "translation_loo_p95_arcsec":tp95,
            "affine_model":amodel,
            "affine_loo_median_arcsec":amed,
            "affine_loo_p95_arcsec":ap95,
            "selected_model":model,
            "selected_loo_median_arcsec":selected_med,
            "selected_loo_p95_arcsec":selected_p95,
            "affine_required_p95_improvement":AFFINE_REQUIRED_P95_IMPROVEMENT,
        })

        print("Final ordinary-star plate model:")
        print(f"  reference kind: {fit_kind} N={len(fit_refs)}")
        print(f"  translation LOO median/p95: {tmed:.3f}\" / {tp95:.3f}\"")
        if amodel is not None:
            print(f"  affine      LOO median/p95: {amed:.3f}\" / {ap95:.3f}\"")
        print(f"  selected model: {model['kind']} "
              f"LOO median={selected_med:.3f}\" p95={selected_p95:.3f}\"\n")

        for rank in EXPECTED:
            s=sr[rank]
            pra,pdec=f(s["poss_ra_deg"]),f(s["poss_dec_deg"])
            dra,ddec=f(s["dasch_ra_deg"]),f(s["dasch_dec_deg"])
            raw_e,raw_n,raw_sep,_=tangent_vector(pra,pdec,dra,ddec)
            cra=(pra+dra)/2;cdec=(pdec+ddec)/2
            expected=predict_model(model,cra,cdec,center)
            ce=raw_e-expected[0];cn=raw_n-expected[1]
            cres=math.hypot(ce,cn)
            ep=(1+sum(x>=cres for x in selected_loo))/(len(selected_loo)+1)
            within=(cres<=selected_p95) if selected_p95 is not None else None
            row={
                "strict_rank":rank,
                "candidate_raw_east_arcsec":raw_e,
                "candidate_raw_north_arcsec":raw_n,
                "candidate_raw_separation_arcsec":raw_sep,
                "expected_ordinary_star_east_arcsec":float(expected[0]),
                "expected_ordinary_star_north_arcsec":float(expected[1]),
                "expected_ordinary_star_offset_mag_arcsec":float(math.hypot(*expected)),
                "candidate_residual_from_ordinary_star_model_arcsec":cres,
                "candidate_upper_tail_empirical_p":ep,
                "candidate_within_reference_loo_p95":within,
                "reference_kind":fit_kind,
                "selected_model_kind":model["kind"],
                "reference_count":len(fit_refs),
                "reference_loo_median_arcsec":selected_med,
                "reference_loo_p95_arcsec":selected_p95,
            }
            result_rows.append(row)
            print(
                f"#{rank:>2} raw={raw_sep:.3f}\" "
                f"expected=({expected[0]:+.2f},{expected[1]:+.2f})\" "
                f"resid={cres:.3f}\" "
                f"p={ep:.4f} within_p95={within}"
            )
    else:
        print("Final ordinary-star plate model: INSUFFICIENT_REFERENCES\n")
        for rank in EXPECTED:
            s=sr[rank]
            pra,pdec=f(s["poss_ra_deg"]),f(s["poss_dec_deg"])
            dra,ddec=f(s["dasch_ra_deg"]),f(s["dasch_dec_deg"])
            raw_e,raw_n,raw_sep,_=tangent_vector(pra,pdec,dra,ddec)
            result_rows.append({
                "strict_rank":rank,
                "candidate_raw_east_arcsec":raw_e,
                "candidate_raw_north_arcsec":raw_n,
                "candidate_raw_separation_arcsec":raw_sep,
                "reference_kind":fit_kind,
                "reference_count":0,
            })

    ref_fields=[
        "strict_rank","selection_order","source_id","g_mag","ra_target_deg","dec_target_deg",
        "initial_registration_reference","poss_status","poss_peak_snr","poss_peak_sign",
        "poss_gaia_resid_arcsec","registered_dasch_status","registered_dasch_peak_snr",
        "registered_dasch_gaia_resid_arcsec","registered_dasch_east_gaia_arcsec",
        "registered_dasch_north_gaia_arcsec","registered_dasch_centroid_x",
        "registered_dasch_centroid_y","cross_east_arcsec","cross_north_arcsec",
        "cross_separation_arcsec","cross_pa_deg","final_primary_reference",
        "final_diagnostic_reference"
    ]
    write_csv(OUT_REFS,final_rows,ref_fields)

    result_fields=[
        "strict_rank","candidate_raw_east_arcsec","candidate_raw_north_arcsec",
        "candidate_raw_separation_arcsec","expected_ordinary_star_east_arcsec",
        "expected_ordinary_star_north_arcsec","expected_ordinary_star_offset_mag_arcsec",
        "candidate_residual_from_ordinary_star_model_arcsec",
        "candidate_upper_tail_empirical_p","candidate_within_reference_loo_p95",
        "reference_kind","selected_model_kind","reference_count",
        "reference_loo_median_arcsec","reference_loo_p95_arcsec"
    ]
    write_csv(OUT_CSV,result_rows,result_fields)

    payload={
        "stage":"ORDER01_PLATE_REGISTERED_BRIGHT_GAIA_ASTROMETRY_V028Q",
        "frozen_active_ranks":EXPECTED,
        "guards":{
            "network_access":False,
            "gaia_selection_reused_from_v028p":True,
            "science_pixels_read":True,
            "candidate_pixels_used_as_reference_fit":False,
            "transient_detector_rerun":False,
            "transient_detector_parameters_changed":False,
            "candidate_state_mutation":False,
            "candidate_promotion":False,
            "candidate_deletion":False,
            "weighted_candidate_score":False,
        },
        "phase_a_initial_registration":{
            "reference_count":len(initial),
            "dasch_minus_gaia_median_east_arcsec":float(init_med[0]),
            "dasch_minus_gaia_median_north_arcsec":float(init_med[1]),
            "dasch_minus_gaia_median_magnitude_arcsec":float(math.hypot(*init_med)),
            "residual_median_arcsec":float(np.median(init_res)),
            "residual_p95_arcsec":p95(init_res),
            "fixed_filters":{
                "poss_max_gaia_resid_arcsec":INITIAL_POSS_MAX_GAIA_RESID_ARCSEC,
                "dasch_min_snr":INITIAL_DASCH_MIN_SNR,
                "required_sign":INITIAL_REQUIRED_SIGN,
            }
        },
        "phase_b_registered_recenter":{
            "registered_search_radius_pixels":REGISTERED_SEARCH_RADIUS_PIXELS,
            "dasch_centroid_radius_pixels":REGISTERED_DASCH_CENTROID_RADIUS_PX,
            "primary_min_snr":REGISTERED_PRIMARY_MIN_SNR,
            "diagnostic_min_snr":REGISTERED_DIAGNOSTIC_MIN_SNR,
            "primary_reference_count":len(primary_refs),
            "diagnostic_reference_count":len(diagnostic_refs),
        },
        "plate_model":model_info,
        "results":result_rows,
        "interpretive_boundary":(
            "The final model is fitted only to ordinary bright Gaia stars on the "
            "shared discovery plate pair. Candidate pixels do not influence the "
            "fit. A large residual relative to ordinary-star registration weighs "
            "against a common physical sky source but does not identify the "
            "instrumental cause or by itself prove a chance coincidence."
        )
    }
    write_json(OUT_JSON,payload)

    md=[
        "# ORDER 01 â€” Plate-Registered Bright-Gaia Astrometry v028q","",
        "## Guard state","",
        "- No network query; v028p's Gaia selection was reused.",
        "- Science pixels were read.",
        "- Candidate pixels were not reference-fit inputs.",
        "- The transient detector was not rerun.",
        "- No candidate was promoted, deleted, or otherwise mutated.","",
        "## Initial registration","",
        f"- Initial high-confidence stars: **{len(initial)}**.",
        f"- DASCHâˆ’Gaia median: east **{init_med[0]:+.3f} arcsec**, "
        f"north **{init_med[1]:+.3f} arcsec**.",
        f"- Initial residual median/p95: **{np.median(init_res):.3f} / {p95(init_res):.3f} arcsec**.","",
        "## Registered recenter","",
        f"- Primary â‰¥5Ïƒ common references: **{len(primary_refs)}**.",
        f"- Diagnostic â‰¥3.5Ïƒ common references: **{len(diagnostic_refs)}**.","",
        "## Candidate comparison","",
        "| rank | raw sep | expected ordinary-star offset | residual | empirical p | within ref p95 |",
        "|---:|---:|---:|---:|---:|---|"
    ]
    for r in result_rows:
        if r.get("candidate_residual_from_ordinary_star_model_arcsec") is None:
            md.append(f"| #{r['strict_rank']} | {r['candidate_raw_separation_arcsec']:.3f}\" | n/a | n/a | n/a | n/a |")
        else:
            md.append(
                f"| #{r['strict_rank']} | {r['candidate_raw_separation_arcsec']:.3f}\" | "
                f"{r['expected_ordinary_star_offset_mag_arcsec']:.3f}\" | "
                f"{r['candidate_residual_from_ordinary_star_model_arcsec']:.3f}\" | "
                f"{r['candidate_upper_tail_empirical_p']:.4f} | "
                f"{r['candidate_within_reference_loo_p95']} |"
            )
    md += ["","## Interpretation boundary","",
           "This stage asks whether each science pair has the same cross-archive "
           "astrometric behaviour as ordinary bright stars on the same physical "
           "plate pair. It does not classify a candidate as astrophysical."]
    OUT_MD.write_text("\n".join(md),encoding="utf-8")

    print("\nOutputs:")
    print(f"  {OUT_JSON}")
    print(f"  {OUT_CSV}")
    print(f"  {OUT_REFS}")
    print(f"  {OUT_MD}")
    print()
    print("No network query was made.")
    print("SCIENCE PIXELS WERE READ.")
    print("Candidate pixels were NOT reference-fit inputs.")
    print("Transient detector was NOT rerun.")
    print("No candidate was promoted or deleted.")
    return 0


if __name__=="__main__":
    raise SystemExit(main())
