#!/usr/bin/env python3
"""
ORDER 01 — bright-Gaia ordinary-star sub-pixel astrometry v028p

Purpose
-------
Resolve the local POSS<->DASCH astrometry using stars that the shallow
Harvard discovery plate ai43437 could actually record.

Why this stage exists
---------------------
v028l/v028m used transient-detector catalogues as controls and were too sparse.
v028n used pre-frozen 120" Gaia lists, but those lists were mostly G~15--21
and produced zero accepted DASCH anchors.  ai43437 has a local limiting
magnitude around ~12, so that was the wrong control population.

v028p therefore:
  * makes a NEW Gaia TAP query around each frozen science position;
  * queries only bright sources (G <= 13);
  * propagates Gaia coordinates from their reference epoch to the frozen
    Order-01 exposure epoch;
  * selects isolated bright stars before looking at science pixels;
  * uses a 30" guided search and signed flux-weighted SUB-PIXEL centroid,
    matching the native-pixel astrometry method already exercised elsewhere
    in this project;
  * retains only ordinary stars successfully measured on BOTH archives;
  * freezes their median POSS->DASCH translation and leave-one-out scatter;
  * compares the science-pair vector only after the reference field is fixed.

This stage reads science image arrays because the ordinary-star controls and
science candidates inhabit the same frozen native tiles, but candidate pixels
are NEVER used in the astrometric reference fit.

Guard changes
-------------
NETWORK ACCESS IS MADE (Gaia TAP); exact queries and raw CSV responses are
cached locally.
SCIENCE PIXELS ARE READ.
The frozen transient detector is NOT rerun.
No detector parameter is changed.
No candidate is promoted/deleted/mutated.
No weighted overall candidate score is generated.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import statistics
import time
import urllib.parse
import urllib.request
from collections import Counter
from pathlib import Path
from typing import Any

import numpy as np
import astropy.units as u
from astropy.coordinates import SkyCoord
from astropy.time import Time

ROOT = Path.cwd()
BASE = ROOT / "results" / "order01_native_full_v028"
WORK = ROOT / "work" / "order01_native_full_v028"
CACHE = WORK / "bright_gaia_astrometry_v028p"
CACHE.mkdir(parents=True, exist_ok=True)

V028K = BASE / "order01_discovery_exposure_overlap_freeze_v028k.json"
V028N = BASE / "order01_gaia_guided_local_astrometry_v028n.json"
V028O = BASE / "order01_poss_physical_polarity_v028o.json"
STRICT = BASE / "order01_strict_match_triage_v028.csv"
POSS_CAND = BASE / "order01_poss_native_candidates.csv"
DASCH_CAND = BASE / "order01_dasch_native_candidates.csv"
INJ = BASE / "order01_injection_recovery_report_v028.json"

POSS_TILE_DIR = WORK / "poss_tiles"
DASCH_TILE_DIR = WORK / "dasch_tiles"

OUT_JSON = BASE / "order01_bright_gaia_subpixel_astrometry_v028p.json"
OUT_CSV = BASE / "order01_bright_gaia_subpixel_astrometry_v028p.csv"
OUT_REFS = BASE / "order01_bright_gaia_subpixel_references_v028p.csv"
OUT_MD = BASE / "ORDER01_BRIGHT_GAIA_SUBPIXEL_ASTROMETRY_V028P.md"

EXPECTED = [10, 24, 25, 26, 29, 30]
TARGET_EPOCH_ISO = "1951-11-05T07:29:59.999999"

TAP = "https://gea.esac.esa.int/tap-server/tap/sync"
USER_AGENT = "historical-transient-pipeline/0.2.8-order01-bright-gaia-astrometry"

QUERY_RADIUS_DEG = 0.45
QUERY_G_MAX = 13.0
QUERY_MAX_ROWS = 5000

# Selection is frozen BEFORE pixel measurements.
PRIMARY_G_MIN = 8.5
PRIMARY_G_MAX = 11.8
FALLBACK_G_MIN = 7.0
FALLBACK_G_MAX = 12.8
MIN_ISOLATION_ARCSEC = 45.0
MAX_SELECTED_PER_RANK = 24
MIN_PRIMARY_SELECTED = 8

# Native-pixel measurement policy.
PIXEL_SEARCH_RADIUS_ARCSEC = 30.0
CENTROID_MIN_SNR = 5.0
POSS_CENTROID_RADIUS_PX = 4.0
DASCH_CENTROID_RADIUS_PX = 2.0

MIN_REFERENCES_STRONG = 5
MIN_REFERENCES_DESCRIPTIVE = 3

POLY_DEGREES = [1, 2, 3]
MAX_FORWARD_P95_ARCSEC = 0.35
MAX_INVERSE_P95_PX = 0.20

REQUEST_ATTEMPTS = 4
REQUEST_PAUSE_S = 1.0


def f(v: Any) -> float:
    return float(str(v).strip())


def i(v: Any) -> int:
    return int(float(str(v).strip()))


def truth(v: Any) -> bool:
    return str(v).strip().lower() in {"true", "1", "yes", "y", "t"}


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]):
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    tmp.replace(path)


def write_json(path: Path, obj: Any):
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(obj, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )
    tmp.replace(path)


def sha_file(path: Path, block=1024 * 1024) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for b in iter(lambda: fh.read(block), b""):
            h.update(b)
    return h.hexdigest()


def tangent_xy(ra, dec, ra0: float, dec0: float):
    return (
        (np.asarray(ra, dtype=float) - ra0)
        * 3600.0
        * math.cos(math.radians(dec0)),
        (np.asarray(dec, dtype=float) - dec0) * 3600.0,
    )


def tangent_vector(
    ra1: float, dec1: float, ra2: float, dec2: float
) -> tuple[float, float, float, float]:
    dec0 = 0.5 * (dec1 + dec2)
    east = (ra2 - ra1) * 3600.0 * math.cos(math.radians(dec0))
    north = (dec2 - dec1) * 3600.0
    sep = math.hypot(east, north)
    pa = math.degrees(math.atan2(east, north)) % 360.0
    return east, north, sep, pa


def poly_terms(x: np.ndarray, y: np.ndarray, degree: int) -> np.ndarray:
    cols = [np.ones_like(x)]
    for total in range(1, degree + 1):
        for xp in range(total, -1, -1):
            yp = total - xp
            cols.append((x ** xp) * (y ** yp))
    return np.column_stack(cols)


class Transform:
    def __init__(
        self, x0, y0, pscale, ra0, dec0, sscale,
        fdeg, fx, fy, ideg, ix, iy, validation
    ):
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
        sx,sy=tangent_xy(
            np.atleast_1d(np.asarray(ra,float)),
            np.atleast_1d(np.asarray(dec,float)),
            self.ra0,self.dec0
        )
        sx=np.asarray(sx)/self.sscale
        sy=np.asarray(sy)/self.sscale
        A=poly_terms(sx,sy,self.ideg)
        gx=(A@self.ix)*self.pscale+self.x0
        gy=(A@self.iy)*self.pscale+self.y0
        if np.ndim(ra)==0:
            return float(gx[0]),float(gy[0])
        return gx,gy

    def local_scale(self,gx,gy):
        ra0,de0=self.pixel_to_sky(gx,gy)
        ra1,de1=self.pixel_to_sky(gx+1,gy)
        ra2,de2=self.pixel_to_sky(gx,gy+1)
        _,_,sx,_=tangent_vector(ra0,de0,ra1,de1)
        _,_,sy,_=tangent_vector(ra0,de0,ra2,de2)
        return float(statistics.median([q for q in (sx,sy) if q>0]))


def fit_transform(rows: list[dict[str,str]], tile_id: str) -> Transform:
    pts=[]
    for r in rows:
        if str(r.get("tile_id",""))!=tile_id:
            continue
        try:
            pts.append((f(r["global_x"]),f(r["global_y"]),f(r["ra_deg"]),f(r["dec_deg"])))
        except Exception:
            continue
    if len(pts)<30:
        raise RuntimeError(f"{tile_id}: only {len(pts)} coordinate rows")

    a=np.asarray(pts,float)
    gx,gy,ra,dec=a.T
    x0=float(np.median(gx)); y0=float(np.median(gy))
    pscale=max(float(np.ptp(gx)),float(np.ptp(gy)),512.0)/2
    ra0=float(np.median(ra)); dec0=float(np.median(dec))
    sx,sy=tangent_xy(ra,dec,ra0,dec0)
    sx=np.asarray(sx); sy=np.asarray(sy)
    sscale=max(float(np.ptp(sx)),float(np.ptp(sy)),100.0)/2
    px=(gx-x0)/pscale; py=(gy-y0)/pscale
    snx=sx/sscale; sny=sy/sscale

    order=np.lexsort((gy,gx))
    test=np.zeros(len(a),dtype=bool); test[order[::5]]=True
    train=~test

    fbest=None; ftrials=[]
    for deg in POLY_DEGREES:
        A=poly_terms(px,py,deg)
        cx,*_=np.linalg.lstsq(A[train],snx[train],rcond=None)
        cy,*_=np.linalg.lstsq(A[train],sny[train],rcond=None)
        rx=(A[test]@cx)*sscale-sx[test]
        ry=(A[test]@cy)*sscale-sy[test]
        rr=np.hypot(rx,ry)
        t={"degree":deg,"p95_arcsec":float(np.quantile(rr,.95)),"median_arcsec":float(np.median(rr))}
        ftrials.append(t)
        if fbest is None or t["p95_arcsec"]<fbest[0]:
            fbest=(t["p95_arcsec"],deg)
        if t["p95_arcsec"]<=.05: break
    assert fbest
    fdeg=fbest[1]
    A=poly_terms(px,py,fdeg)
    fx,*_=np.linalg.lstsq(A,snx,rcond=None)
    fy,*_=np.linalg.lstsq(A,sny,rcond=None)

    ibest=None; itrials=[]
    for deg in POLY_DEGREES:
        A=poly_terms(snx,sny,deg)
        cx,*_=np.linalg.lstsq(A[train],px[train],rcond=None)
        cy,*_=np.linalg.lstsq(A[train],py[train],rcond=None)
        rx=(A[test]@cx)*pscale+x0-gx[test]
        ry=(A[test]@cy)*pscale+y0-gy[test]
        rr=np.hypot(rx,ry)
        t={"degree":deg,"p95_px":float(np.quantile(rr,.95)),"median_px":float(np.median(rr))}
        itrials.append(t)
        if ibest is None or t["p95_px"]<ibest[0]:
            ibest=(t["p95_px"],deg)
        if t["p95_px"]<=.05: break
    assert ibest
    ideg=ibest[1]
    A=poly_terms(snx,sny,ideg)
    ix,*_=np.linalg.lstsq(A,px,rcond=None)
    iy,*_=np.linalg.lstsq(A,py,rcond=None)

    val={
        "tile_id":tile_id,
        "coordinate_rows":len(pts),
        "forward_trials":ftrials,
        "inverse_trials":itrials,
        "forward_p95_arcsec":fbest[0],
        "inverse_p95_px":ibest[0],
        "forward_ok":fbest[0]<=MAX_FORWARD_P95_ARCSEC,
        "inverse_ok":ibest[0]<=MAX_INVERSE_P95_PX,
    }
    return Transform(x0,y0,pscale,ra0,dec0,sscale,fdeg,fx,fy,ideg,ix,iy,val)


def load_inventory(tile_dir: Path, archive: str):
    out={}
    for jp in sorted(tile_dir.glob("*.json")):
        try: o=json.loads(jp.read_text(encoding="utf-8"))
        except Exception: continue
        if o.get("complete") is not True: continue
        tid=str(o.get("tile_id","")).strip()
        ext=o.get("extended"); ref=o.get("npy_path")
        if not tid or not isinstance(ext,list) or len(ext)!=4 or not ref: continue
        p=Path(str(ref)); p=p if p.is_absolute() else ROOT/p
        if not p.is_file(): raise RuntimeError(f"{archive} {tid}: missing {p}")
        actual=sha_file(p); rec=str(o.get("npy_file_sha256") or "").lower()
        if rec and rec!=actual: raise RuntimeError(f"{archive} {tid}: SHA mismatch")
        out[tid]={"archive":archive,"tile_id":tid,"extended":tuple(map(int,ext)),
                  "npy_path":p,"npy_sha256":actual}
    if not out: raise RuntimeError(f"{archive}: no tile metadata")
    return out


ARRAY_CACHE={}
def load_array(meta):
    key=(meta["archive"],meta["tile_id"])
    if key in ARRAY_CACHE:return ARRAY_CACHE[key]
    a=np.load(meta["npy_path"],mmap_mode="r")
    ex0,ex1,ey0,ey1=meta["extended"]
    if a.shape!=(ey1-ey0,ex1-ex0):
        raise RuntimeError(f"{key}: array shape mismatch")
    ARRAY_CACHE[key]=a
    return a


def propagate_gaia(row: dict[str,str]):
    ra=f(row["ra"]); dec=f(row["dec"])
    ref=f(row["ref_epoch"]) if str(row.get("ref_epoch","")).strip() else 2016.0
    pmra=f(row["pmra"]) if str(row.get("pmra","")).strip() else 0.0
    pmdec=f(row["pmdec"]) if str(row.get("pmdec","")).strip() else 0.0
    c=SkyCoord(
        ra=ra*u.deg, dec=dec*u.deg,
        pm_ra_cosdec=pmra*u.mas/u.yr,
        pm_dec=pmdec*u.mas/u.yr,
        obstime=Time(ref,format="jyear"),
    )
    try:
        t=c.apply_space_motion(new_obstime=Time(TARGET_EPOCH_ISO,scale="utc"))
        return float(t.ra.deg),float(t.dec.deg),True
    except Exception:
        # Linear fallback preserving pm_ra_cosdec convention.
        dt=1951.8459-ref
        ddec=pmdec*dt/3.6e6
        dra=(pmra*dt/3.6e6)/max(math.cos(math.radians(dec)),1e-8)
        return ra+dra,dec+ddec,False


def gaia_query(rank:int,ra0:float,dec0:float):
    cache_csv=CACHE/f"rank{rank:02d}_gaia_bright.csv"
    cache_meta=CACHE/f"rank{rank:02d}_gaia_bright_query.json"
    adql=f"""
SELECT TOP {QUERY_MAX_ROWS}
 source_id,ra,dec,ref_epoch,ra_error,dec_error,
 pmra,pmdec,pmra_error,pmdec_error,parallax,parallax_error,
 phot_g_mean_mag,ruwe
FROM gaiadr3.gaia_source
WHERE 1=CONTAINS(
 POINT('ICRS',ra,dec),
 CIRCLE('ICRS',{ra0:.12f},{dec0:.12f},{QUERY_RADIUS_DEG:.8f})
)
AND phot_g_mean_mag <= {QUERY_G_MAX:.3f}
ORDER BY phot_g_mean_mag ASC
""".strip()

    if cache_csv.is_file() and cache_meta.is_file():
        rows=read_csv(cache_csv)
        return rows,adql,True

    payload=urllib.parse.urlencode({
        "REQUEST":"doQuery","LANG":"ADQL","FORMAT":"csv","QUERY":adql
    }).encode()
    last=None
    for attempt in range(1,REQUEST_ATTEMPTS+1):
        try:
            req=urllib.request.Request(
                TAP,data=payload,
                headers={"User-Agent":USER_AGENT,
                         "Content-Type":"application/x-www-form-urlencoded"},
                method="POST"
            )
            with urllib.request.urlopen(req,timeout=120) as resp:
                raw=resp.read()
            text=raw.decode("utf-8-sig")
            rows=list(csv.DictReader(io.StringIO(text)))
            cache_csv.write_text(text,encoding="utf-8")
            write_json(cache_meta,{
                "rank":rank,"center_ra_deg":ra0,"center_dec_deg":dec0,
                "query_radius_deg":QUERY_RADIUS_DEG,"query_g_max":QUERY_G_MAX,
                "adql":adql,"row_count":len(rows),
                "raw_csv_sha256":hashlib.sha256(raw).hexdigest(),
            })
            return rows,adql,False
        except Exception as exc:
            last=exc
            if attempt<REQUEST_ATTEMPTS: time.sleep(REQUEST_PAUSE_S*attempt)
    raise RuntimeError(f"Gaia query rank {rank} failed: {last!r}")


def isolation_arcsec(rows):
    if not rows:return {}
    c=SkyCoord(
        [f(r["ra_target_deg"]) for r in rows]*u.deg,
        [f(r["dec_target_deg"]) for r in rows]*u.deg
    )
    out={}
    for idx,r in enumerate(rows):
        if len(rows)==1:
            out[str(r["source_id"])]=float("inf");continue
        sep=c[idx].separation(c).arcsec
        sep[idx]=np.inf
        out[str(r["source_id"])]=float(np.min(sep))
    return out


def inside_tile(meta,tr,ra,dec,margin_px=12):
    gx,gy=tr.sky_to_pixel(ra,dec)
    ex0,ex1,ey0,ey1=meta["extended"]
    lx=gx-ex0;ly=gy-ey0
    return (
        margin_px<=lx<(ex1-ex0-margin_px)
        and margin_px<=ly<(ey1-ey0-margin_px)
    ),gx,gy


def centroid(meta,tr,ra,dec,archive):
    gx,gy=tr.sky_to_pixel(ra,dec)
    scale=tr.local_scale(gx,gy)
    a=load_array(meta)
    ex0,ex1,ey0,ey1=meta["extended"]
    px=gx-ex0;py=gy-ey0
    sr=max(1,int(math.ceil(PIXEL_SEARCH_RADIUS_ARCSEC/scale)))
    cr=POSS_CENTROID_RADIUS_PX if archive=="POSS" else DASCH_CENTROID_RADIUS_PX
    R=int(math.ceil(sr+cr+8))
    ix=int(round(px));iy=int(round(py))
    x0,x1=ix-R,ix+R+1;y0,y1=iy-R,iy+R+1
    if x0<0 or y0<0 or x1>a.shape[1] or y1>a.shape[0]:
        return {"status":"STAMP_OUTSIDE_TILE","pred_x":gx,"pred_y":gy,"scale":scale}
    cut=np.asarray(a[y0:y1,x0:x1],float)
    yy,xx=np.indices(cut.shape)
    cx0=px-x0;cy0=py-y0
    rr=np.hypot(xx-cx0,yy-cy0)
    ann=cut[(rr>=sr+cr+2)&(rr<=R-1)&np.isfinite(cut)]
    if ann.size<40:return {"status":"INSUFFICIENT_BACKGROUND","pred_x":gx,"pred_y":gy,"scale":scale}
    bg=float(np.median(ann))
    sig=1.4826*float(np.median(np.abs(ann-bg)))
    if not(sig>0):return {"status":"INVALID_BACKGROUND_SIGMA","pred_x":gx,"pred_y":gy,"scale":scale}
    res=cut-bg
    valid=(rr<=sr)&np.isfinite(res)
    score=np.where(valid,np.abs(res),-np.inf)
    pyi,pxi=np.unravel_index(int(np.argmax(score)),cut.shape)
    peak=float(res[pyi,pxi]);snr=abs(peak)/sig
    sign=1 if peak>=0 else -1
    if snr<CENTROID_MIN_SNR:
        return {"status":"PEAK_BELOW_5SIGMA","peak_snr":snr,"peak_sign":sign,
                "pred_x":gx,"pred_y":gy,"scale":scale}
    rp=np.hypot(xx-pxi,yy-pyi)
    wt=np.clip(sign*res,0,None)*(rp<=cr)
    ws=float(wt.sum())
    if ws<=0:return {"status":"INVALID_CENTROID_WEIGHTS","peak_snr":snr,"peak_sign":sign,
                     "pred_x":gx,"pred_y":gy,"scale":scale}
    cx=float((wt*xx).sum()/ws);cy=float((wt*yy).sum()/ws)
    cgx=ex0+x0+cx;cgy=ey0+y0+cy
    mra,mdec=tr.pixel_to_sky(cgx,cgy)
    east,north,sep,pa=tangent_vector(ra,dec,mra,mdec)
    return {
        "status":"SUCCESS","pred_x":gx,"pred_y":gy,"scale":scale,
        "peak_snr":snr,"peak_sign":sign,
        "centroid_x":cgx,"centroid_y":cgy,
        "measured_ra_deg":mra,"measured_dec_deg":mdec,
        "gaia_east_resid_arcsec":east,"gaia_north_resid_arcsec":north,
        "gaia_resid_arcsec":sep,
    }


def loo_residuals(refs):
    out=[]
    if len(refs)<2:return out
    for idx,r in enumerate(refs):
        others=refs[:idx]+refs[idx+1:]
        me=float(np.median([q["cross_east_arcsec"] for q in others]))
        mn=float(np.median([q["cross_north_arcsec"] for q in others]))
        out.append(math.hypot(
            f(r["cross_east_arcsec"])-me,
            f(r["cross_north_arcsec"])-mn
        ))
    return out


def empirical_p95(vals):
    if not vals:return None
    return float(np.quantile(vals,.95,method="higher"))


def main():
    print("="*128)
    print("ORDER 01 — BRIGHT-GAIA ORDINARY-STAR SUB-PIXEL ASTROMETRY v028p")
    print("="*128)
    print("NETWORK ACCESS: Gaia TAP.")
    print("SCIENCE PIXELS ARE READ. Candidate pixels are NOT astrometric references.")
    print("Frozen transient detector is NOT rerun.\n")

    for p in (V028K,V028N,V028O,STRICT,POSS_CAND,DASCH_CAND,INJ):
        if not p.is_file():
            print(f"FAIL missing input: {p}");return 2

    k=json.loads(V028K.read_text(encoding="utf-8"))
    n=json.loads(V028N.read_text(encoding="utf-8"))
    o=json.loads(V028O.read_text(encoding="utf-8"))
    inj=json.loads(INJ.read_text(encoding="utf-8"))
    if k.get("frozen_active_ranks")!=EXPECTED:raise RuntimeError("v028k ranks mismatch")
    if n.get("frozen_active_ranks")!=EXPECTED:raise RuntimeError("v028n ranks mismatch")
    if o.get("frozen_active_ranks")!=EXPECTED:raise RuntimeError("v028o ranks mismatch")

    strict=read_csv(STRICT);prows=read_csv(POSS_CAND);drows=read_csv(DASCH_CAND)
    sr={i(r["strict_rank"]):r for r in strict if i(r["strict_rank"]) in EXPECTED}
    if sorted(sr)!=EXPECTED:raise RuntimeError("strict survivor mismatch")

    pinv=load_inventory(POSS_TILE_DIR,"POSS");dinv=load_inventory(DASCH_TILE_DIR,"DASCH")
    ptiles={str(sr[r]["poss_tile_id"]) for r in EXPECTED}
    dtiles={str(sr[r]["dasch_tile_id"]) for r in EXPECTED}
    pt={tid:fit_transform(prows,tid) for tid in sorted(ptiles)}
    dt={tid:fit_transform(drows,tid) for tid in sorted(dtiles)}

    for archive,ts in (("POSS",pt),("DASCH",dt)):
        for tid,t in ts.items():
            v=t.validation
            if not(v["forward_ok"] and v["inverse_ok"]):
                raise RuntimeError(f"{archive} {tid}: transform validation failed")

    # SHA guard against previously frozen injection stage.
    emap={}
    for e in inj.get("endpoint_summaries",[]):
        try:r=int(e["strict_rank"])
        except Exception:continue
        a=str(e.get("archive",""))
        if r in EXPECTED and a in ("POSS","DASCH"):emap[(r,a)]=e
    for rank in EXPECTED:
        for a,tid,iv in (
            ("POSS",str(sr[rank]["poss_tile_id"]),pinv),
            ("DASCH",str(sr[rank]["dasch_tile_id"]),dinv),
        ):
            e=emap[(rank,a)]
            if str(e.get("tile_id"))!=tid:raise RuntimeError(f"{rank} {a}: tile mismatch")
            h=str(e.get("native_npy_sha256","")).lower()
            if h and h!=iv[tid]["npy_sha256"]:raise RuntimeError(f"{rank} {a}: SHA mismatch")
    print("Frozen rank/tile/hash/transform guards: PASS\n")

    ref_rows=[];summary_rows=[];query_log={}

    for rank in EXPECTED:
        s=sr[rank]
        pra,pdec=f(s["poss_ra_deg"]),f(s["poss_dec_deg"])
        dra,ddec=f(s["dasch_ra_deg"]),f(s["dasch_dec_deg"])
        ra0=(pra+dra)/2;dec0=(pdec+ddec)/2
        raw_e,raw_n,raw_sep,_=tangent_vector(pra,pdec,dra,ddec)

        qrows,adql,cached=gaia_query(rank,ra0,dec0)
        propagated=[]
        for q in qrows:
            try:
                tra,tdec,used_astropy=propagate_gaia(q)
                gm=f(q["phot_g_mean_mag"])
                ruwe=(f(q["ruwe"]) if str(q.get("ruwe","")).strip() else None)
            except Exception:
                continue
            propagated.append({
                **q,
                "ra_target_deg":tra,"dec_target_deg":tdec,
                "propagated_with_astropy":used_astropy,
                "g_mag":gm,"ruwe_value":ruwe,
            })
        iso=isolation_arcsec(propagated)
        for q in propagated:q["nearest_query_neighbor_arcsec"]=iso[str(q["source_id"])]

        ptid=str(s["poss_tile_id"]);dtid=str(s["dasch_tile_id"])
        pmeta=pinv[ptid];dmeta=dinv[dtid];ptr=pt[ptid];dtr=dt[dtid]

        eligible=[]
        for q in propagated:
            if q["ruwe_value"] is not None and q["ruwe_value"]>1.4:continue
            if q["nearest_query_neighbor_arcsec"]<MIN_ISOLATION_ARCSEC:continue
            pin,_,_=inside_tile(pmeta,ptr,q["ra_target_deg"],q["dec_target_deg"])
            din,_,_=inside_tile(dmeta,dtr,q["ra_target_deg"],q["dec_target_deg"])
            if not(pin and din):continue
            eligible.append(q)

        primary=[q for q in eligible if PRIMARY_G_MIN<=q["g_mag"]<=PRIMARY_G_MAX]
        fallback=[q for q in eligible if FALLBACK_G_MIN<=q["g_mag"]<=FALLBACK_G_MAX]
        if len(primary)>=MIN_PRIMARY_SELECTED:
            selected=primary;selmode=f"G_{PRIMARY_G_MIN:g}_{PRIMARY_G_MAX:g}_PRIMARY"
        elif len(fallback):
            selected=fallback;selmode=f"G_{FALLBACK_G_MIN:g}_{FALLBACK_G_MAX:g}_FALLBACK"
        else:
            selected=eligible;selmode=f"G_LE_{QUERY_G_MAX:g}_ALL_ELIGIBLE_FALLBACK"
        selected=sorted(selected,key=lambda q:(q["g_mag"],str(q["source_id"])))[:MAX_SELECTED_PER_RANK]

        query_log[str(rank)]={
            "adql":adql,"cache_used":cached,"query_rows":len(qrows),
            "propagated_rows":len(propagated),"eligible_both_tile_rows":len(eligible),
            "selection_mode":selmode,"selected_count":len(selected),
        }

        print(f"Rank #{rank}: query={len(qrows)} eligible={len(eligible)} selected={len(selected)} mode={selmode}")
        refs=[]
        for idx,q in enumerate(selected,1):
            pm=centroid(pmeta,ptr,q["ra_target_deg"],q["dec_target_deg"],"POSS")
            dm=centroid(dmeta,dtr,q["ra_target_deg"],q["dec_target_deg"],"DASCH")
            row={
                "strict_rank":rank,"selection_order":idx,"source_id":str(q["source_id"]),
                "g_mag":q["g_mag"],"ruwe":q["ruwe_value"],
                "nearest_query_neighbor_arcsec":q["nearest_query_neighbor_arcsec"],
                "ra_target_deg":q["ra_target_deg"],"dec_target_deg":q["dec_target_deg"],
                "poss_status":pm.get("status"),"poss_peak_snr":pm.get("peak_snr"),
                "poss_peak_sign":pm.get("peak_sign"),"poss_pixel_scale_arcsec":pm.get("scale"),
                "poss_centroid_x":pm.get("centroid_x"),"poss_centroid_y":pm.get("centroid_y"),
                "poss_gaia_resid_arcsec":pm.get("gaia_resid_arcsec"),
                "dasch_status":dm.get("status"),"dasch_peak_snr":dm.get("peak_snr"),
                "dasch_peak_sign":dm.get("peak_sign"),"dasch_pixel_scale_arcsec":dm.get("scale"),
                "dasch_centroid_x":dm.get("centroid_x"),"dasch_centroid_y":dm.get("centroid_y"),
                "dasch_gaia_resid_arcsec":dm.get("gaia_resid_arcsec"),
                "both_archive_success":pm.get("status")=="SUCCESS" and dm.get("status")=="SUCCESS",
            }
            if row["both_archive_success"]:
                ce,cn,csep,cpa=tangent_vector(
                    f(pm["measured_ra_deg"]),f(pm["measured_dec_deg"]),
                    f(dm["measured_ra_deg"]),f(dm["measured_dec_deg"])
                )
                row.update({"cross_east_arcsec":ce,"cross_north_arcsec":cn,
                            "cross_separation_arcsec":csep,"cross_pa_deg":cpa})
                refs.append(row)
            ref_rows.append(row)
            print(
                f"  [{idx:02d}/{len(selected):02d}] {q['source_id']} G={q['g_mag']:.2f} "
                f"P={pm.get('status')}({pm.get('peak_sign','-')},{pm.get('peak_snr',float('nan')):.1f}) "
                f"D={dm.get('status')}({dm.get('peak_sign','-')},{dm.get('peak_snr',float('nan')):.1f}) "
                f"both={'YES' if row['both_archive_success'] else 'no'}"
            )

        status="INSUFFICIENT_BRIGHT_GAIA_PIXEL_REFERENCES"
        z={
            "strict_rank":rank,"status":status,"selection_mode":selmode,
            "gaia_selected_count":len(selected),"both_archive_reference_count":len(refs),
            "candidate_raw_separation_arcsec":raw_sep,
            "candidate_raw_east_arcsec":raw_e,"candidate_raw_north_arcsec":raw_n,
            "poss_reference_sign_counts":dict(Counter(int(r["poss_peak_sign"]) for r in refs)),
            "dasch_reference_sign_counts":dict(Counter(int(r["dasch_peak_sign"]) for r in refs)),
        }
        if len(refs)>=MIN_REFERENCES_DESCRIPTIVE:
            me=float(np.median([f(q["cross_east_arcsec"]) for q in refs]))
            mn=float(np.median([f(q["cross_north_arcsec"]) for q in refs]))
            lv=loo_residuals(refs)
            p95=empirical_p95(lv)
            ce=raw_e-me;cn=raw_n-mn;cr=math.hypot(ce,cn)
            ep=(1+sum(x>=cr for x in lv))/(len(lv)+1) if lv else None
            z.update({
                "status":(
                    "BRIGHT_GAIA_PIXEL_ASTROMETRY_COMPLETE"
                    if len(refs)>=MIN_REFERENCES_STRONG
                    else "BRIGHT_GAIA_PIXEL_ASTROMETRY_DESCRIPTIVE"
                ),
                "reference_median_cross_east_arcsec":me,
                "reference_median_cross_north_arcsec":mn,
                "reference_translation_magnitude_arcsec":math.hypot(me,mn),
                "reference_loo_residual_median_arcsec":float(np.median(lv)) if lv else None,
                "reference_loo_residual_p95_arcsec":p95,
                "candidate_corrected_east_arcsec":ce,
                "candidate_corrected_north_arcsec":cn,
                "candidate_corrected_separation_arcsec":cr,
                "candidate_upper_tail_empirical_p":ep,
                "candidate_within_reference_p95":cr<=p95 if p95 is not None else None,
                "poss_median_gaia_residual_arcsec":float(np.median([f(q["poss_gaia_resid_arcsec"]) for q in refs])),
                "dasch_median_gaia_residual_arcsec":float(np.median([f(q["dasch_gaia_resid_arcsec"]) for q in refs])),
            })
        summary_rows.append(z)
        print(f"  => refs={len(refs)}/{len(selected)} {z['status']}")
        if z["status"].startswith("BRIGHT_GAIA"):
            print(
                f"     raw={raw_sep:.3f}\" corrected={z['candidate_corrected_separation_arcsec']:.3f}\" "
                f"ref_p95={z['reference_loo_residual_p95_arcsec']:.3f}\" "
                f"p={z['candidate_upper_tail_empirical_p']:.4f}"
            )
        print()

    ref_fields=[
        "strict_rank","selection_order","source_id","g_mag","ruwe","nearest_query_neighbor_arcsec",
        "ra_target_deg","dec_target_deg",
        "poss_status","poss_peak_snr","poss_peak_sign","poss_pixel_scale_arcsec",
        "poss_centroid_x","poss_centroid_y","poss_gaia_resid_arcsec",
        "dasch_status","dasch_peak_snr","dasch_peak_sign","dasch_pixel_scale_arcsec",
        "dasch_centroid_x","dasch_centroid_y","dasch_gaia_resid_arcsec",
        "both_archive_success","cross_east_arcsec","cross_north_arcsec",
        "cross_separation_arcsec","cross_pa_deg"
    ]
    write_csv(OUT_REFS,ref_rows,ref_fields)

    summary_fields=[
        "strict_rank","status","selection_mode","gaia_selected_count","both_archive_reference_count",
        "candidate_raw_separation_arcsec","candidate_raw_east_arcsec","candidate_raw_north_arcsec",
        "reference_median_cross_east_arcsec","reference_median_cross_north_arcsec",
        "reference_translation_magnitude_arcsec","reference_loo_residual_median_arcsec",
        "reference_loo_residual_p95_arcsec","candidate_corrected_east_arcsec",
        "candidate_corrected_north_arcsec","candidate_corrected_separation_arcsec",
        "candidate_upper_tail_empirical_p","candidate_within_reference_p95",
        "poss_median_gaia_residual_arcsec","dasch_median_gaia_residual_arcsec",
        "poss_reference_sign_counts","dasch_reference_sign_counts"
    ]
    # stringify dicts for CSV
    csvsum=[]
    for r in summary_rows:
        q=dict(r)
        q["poss_reference_sign_counts"]=json.dumps(q.get("poss_reference_sign_counts",{}),sort_keys=True)
        q["dasch_reference_sign_counts"]=json.dumps(q.get("dasch_reference_sign_counts",{}),sort_keys=True)
        csvsum.append(q)
    write_csv(OUT_CSV,csvsum,summary_fields)

    payload={
        "stage":"ORDER01_BRIGHT_GAIA_SUBPIXEL_ASTROMETRY_V028P",
        "frozen_active_ranks":EXPECTED,
        "guards":{
            "network_access":True,
            "network_endpoint":TAP,
            "science_pixels_read":True,
            "candidate_pixels_used_as_reference_fit":False,
            "transient_detector_rerun":False,
            "transient_detector_parameters_changed":False,
            "candidate_state_mutation":False,
            "candidate_promotion":False,
            "candidate_deletion":False,
            "weighted_candidate_score":False,
        },
        "fixed_policy":{
            "target_epoch_iso":TARGET_EPOCH_ISO,
            "query_radius_deg":QUERY_RADIUS_DEG,
            "query_g_max":QUERY_G_MAX,
            "primary_g_range":[PRIMARY_G_MIN,PRIMARY_G_MAX],
            "fallback_g_range":[FALLBACK_G_MIN,FALLBACK_G_MAX],
            "minimum_isolation_arcsec":MIN_ISOLATION_ARCSEC,
            "max_selected_per_rank":MAX_SELECTED_PER_RANK,
            "pixel_search_radius_arcsec":PIXEL_SEARCH_RADIUS_ARCSEC,
            "centroid_min_snr":CENTROID_MIN_SNR,
            "poss_centroid_radius_px":POSS_CENTROID_RADIUS_PX,
            "dasch_centroid_radius_px":DASCH_CENTROID_RADIUS_PX,
            "minimum_references_strong":MIN_REFERENCES_STRONG,
            "minimum_references_descriptive":MIN_REFERENCES_DESCRIPTIVE,
            "registration_model":"median_translation_only",
        },
        "query_log":query_log,
        "results":summary_rows,
        "interpretive_boundary":(
            "Ordinary bright Gaia stars are the only astrometric references. "
            "Science candidate positions are compared after the reference field is frozen. "
            "Astrometric consistency does not establish astrophysical reality."
        )
    }
    write_json(OUT_JSON,payload)

    md=[
        "# ORDER 01 — Bright-Gaia Sub-Pixel Astrometry v028p","",
        "## Guard state","",
        "- Gaia TAP network queries were made and cached.",
        "- Science pixels were read.",
        "- Candidate pixels were not used to fit the ordinary-star registration.",
        "- The transient detector was not rerun.",
        "- No candidate was promoted, deleted, or otherwise mutated.","",
        "## Results","",
        "| rank | selected | both refs | raw sep | corrected sep | ref p95 | empirical p | status |",
        "|---:|---:|---:|---:|---:|---:|---:|---|"
    ]
    for r in summary_rows:
        md.append(
            f"| #{r['strict_rank']} | {r['gaia_selected_count']} | {r['both_archive_reference_count']} | "
            f"{r['candidate_raw_separation_arcsec']:.3f}\" | "
            f"{('n/a' if r.get('candidate_corrected_separation_arcsec') is None else f'{r['candidate_corrected_separation_arcsec']:.3f}\"')} | "
            f"{('n/a' if r.get('reference_loo_residual_p95_arcsec') is None else f'{r['reference_loo_residual_p95_arcsec']:.3f}\"')} | "
            f"{('n/a' if r.get('candidate_upper_tail_empirical_p') is None else f'{r['candidate_upper_tail_empirical_p']:.4f}')} | "
            f"`{r['status']}` |"
        )
    md += [
        "","## Interpretation boundary","",
        "This stage measures local POSS↔DASCH registration with bright, isolated Gaia stars "
        "propagated to the 1951 exposure epoch. It does not classify a transient as astrophysical."
    ]
    OUT_MD.write_text("\n".join(md),encoding="utf-8")

    print("="*128)
    print("v028p complete")
    print(f"  {OUT_JSON}")
    print(f"  {OUT_CSV}")
    print(f"  {OUT_REFS}")
    print(f"  {OUT_MD}")
    print()
    print("Gaia TAP network queries WERE made.")
    print("SCIENCE PIXELS WERE READ.")
    print("Candidate pixels were NOT astrometric references.")
    print("Transient detector was NOT rerun.")
    print("No candidate was promoted or deleted.")
    return 0


if __name__=="__main__":
    raise SystemExit(main())
