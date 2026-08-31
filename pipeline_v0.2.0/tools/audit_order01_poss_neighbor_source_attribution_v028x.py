#!/usr/bin/env python3
"""
ORDER 01 — POSS neighbouring-source attribution / centred-deficit audit v028x

Purpose
-------
v028w established:
  - #10/#25 have locally unusual broad positive flux but no centred positive core.
  - #30 also has no centred positive core.
  - #29 has a centred negative deficit whose joint depth+centring is unusual
    relative to deterministic local blank controls.
  - #26/#24 remain mixed.

This stage localises the actual positive/negative raw-image structures and asks
whether displaced positive structures can be attributed to known sky sources
or native POSS detections.

For every frozen science endpoint:
  1. Reconstruct the same local planar background used by v028v/v028w.
  2. Find the strongest Gaussian-smoothed positive and negative structures
     within 25 px, recording full dx/dy rather than only radial offset.
  3. Convert those extrema to sky coordinates with the validated native
     pixel->sky transform.
  4. Match each extremum against:
       a. frozen epoch-propagated Gaia sources from v028b;
       b. native POSS detector candidates, excluding the science detection.
  5. Match the exact science coordinate itself against Gaia.
  6. Recompute the deterministic blank-control *joint* negative tail:
       P(blank ap7 <= science ap7 AND
         blank negative-trough offset <= science offset)
     using the +1 guarded empirical estimator.

Interpretation is descriptive:
  - A strong displaced positive structure spatially coincident with Gaia/native
    evidence is an identified neighbouring-source explanation for broad
    positive science apertures.
  - A centred negative feature without a corresponding positive-source match
    supports a local deficit/defect interpretation, but does not identify the
    physical defect mechanism.

No network access.
SCIENCE PIXELS ARE READ.
Frozen transient detector is NOT rerun.
No candidate promotion/deletion/state mutation.
"""

from __future__ import annotations

import csv
import importlib.util
import json
import math
from pathlib import Path

import numpy as np
from scipy.ndimage import gaussian_filter

ROOT = Path.cwd()
BASE = ROOT / "results" / "order01_native_full_v028"
WORK = ROOT / "work" / "order01_native_full_v028"

V028V_SCRIPT = ROOT / "tools" / "audit_order01_poss_physical_source_centering_v028v.py"
V028W_JSON = BASE / "order01_poss_signal_matched_and_blank_controls_v028w.json"
V028W_BLANK = BASE / "order01_poss_local_blank_controls_v028w.csv"
V028B_GAIA = BASE / "order01_gaia_source_candidates_v028b.csv"
STRICT = BASE / "order01_strict_match_triage_v028.csv"
POSS_CAND = BASE / "order01_poss_native_candidates.csv"

OUT_JSON = BASE / "order01_poss_neighbor_source_attribution_v028x.json"
OUT_CSV = BASE / "order01_poss_neighbor_source_attribution_v028x.csv"
OUT_MD = BASE / "ORDER01_POSS_NEIGHBOR_SOURCE_ATTRIBUTION_V028X.md"

EXPECTED = [10,24,25,26,29,30]

SEARCH_RADIUS_PX = 25.0
GAUSSIAN_SIGMA_PX = 2.5
GAIA_MATCH_MAX_PX = 4.0
NATIVE_MATCH_MAX_PX = 4.0
STRONG_POSITIVE_Z = 3.0
CENTERED_NEGATIVE_MAX_PX = 2.0


def load_v028v_module():
    if not V028V_SCRIPT.is_file():
        raise RuntimeError(f"missing prerequisite script: {V028V_SCRIPT}")
    spec=importlib.util.spec_from_file_location("v028vmod",V028V_SCRIPT)
    mod=importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


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


def pick(row,*names,default=None):
    norm={str(k).lower().replace("_",""):k for k in row}
    for name in names:
        q=str(name).lower().replace("_","")
        if q in norm:
            return row[norm[q]]
    return default


def rank_of_gaia(row):
    return i(pick(row,"strict_rank","rank","candidate_rank","survivor_rank"))


def angular_vector(ra1,dec1,ra2,dec2):
    dec0=.5*(dec1+dec2)
    east=(ra2-ra1)*3600.0*math.cos(math.radians(dec0))
    north=(dec2-dec1)*3600.0
    return east,north,math.hypot(east,north)


def local_extrema(v,meta,gx,gy):
    """
    Reproduce the v028v physical background treatment but return full dx/dy for
    extrema. This does NOT call or reproduce the frozen transient detector.
    """
    arr=v.load_arr(meta)
    ex0,ex1,ey0,ey1=meta["extended"]
    px=gx-ex0;py=gy-ey0
    ix=int(round(px));iy=int(round(py))
    R=v.STAMP_RADIUS
    x0=ix-R;x1=ix+R+1;y0=iy-R;y1=iy+R+1
    if x0<0 or y0<0 or x1>arr.shape[1] or y1>arr.shape[0]:
        return {"status":"STAMP_OUTSIDE_TILE"}

    cut=np.asarray(arr[y0:y1,x0:x1],float)
    yy,xx=np.indices(cut.shape)
    cx=px-x0;cy=py-y0
    rr=np.hypot(xx-cx,yy-cy)
    bgmask=(rr>=v.BACKGROUND_INNER)&(rr<=v.BACKGROUND_OUTER)
    plane,resid,sigma,beta=v.robust_plane(cut,xx,yy,bgmask)
    sm=gaussian_filter(resid,GAUSSIAN_SIGMA_PX,mode="nearest")/sigma

    m=rr<=SEARCH_RADIUS_PX
    wp=np.where(m,sm,-np.inf)
    wn=np.where(m,sm,np.inf)
    yp,xp=np.unravel_index(int(np.argmax(wp)),sm.shape)
    yn,xn=np.unravel_index(int(np.argmin(wn)),sm.shape)

    def pack(x,y,z):
        dx=float(x-cx);dy=float(y-cy)
        return {
            "dx_px":dx,
            "dy_px":dy,
            "offset_px":math.hypot(dx,dy),
            "z":float(z),
            "global_x":float(x+x0+ex0),
            "global_y":float(y+y0+ey0),
        }

    return {
        "status":"SUCCESS",
        "positive":pack(xp,yp,sm[yp,xp]),
        "negative":pack(xn,yn,sm[yn,xn]),
        "background_sigma":float(sigma),
    }


def nearest_gaia(gx,gy,rows):
    if not rows:
        return None
    q=[]
    for r in rows:
        dx=float(r["pred_global_x"])-gx
        dy=float(r["pred_global_y"])-gy
        q.append((math.hypot(dx,dy),r))
    q.sort(key=lambda z:z[0])
    d,r=q[0]
    return {
        "distance_px":d,
        "source_id":r["source_id"],
        "g_mag":r["g_mag"],
        "pred_global_x":r["pred_global_x"],
        "pred_global_y":r["pred_global_y"],
    }


def nearest_native(gx,gy,rows,science_index):
    q=[]
    for r in rows:
        idx=i(r.get("candidate_index"))
        if idx==science_index:
            continue
        rx=f(r.get("global_x"));ry=f(r.get("global_y"))
        if None in (rx,ry):
            continue
        q.append((math.hypot(rx-gx,ry-gy),r))
    if not q:
        return None
    q.sort(key=lambda z:z[0])
    d,r=q[0]
    return {
        "distance_px":d,
        "candidate_index":i(r.get("candidate_index")),
        "snr":f(r.get("snr")),
        "polarity":i(r.get("polarity")),
        "global_x":f(r.get("global_x")),
        "global_y":f(r.get("global_y")),
    }


def guarded_joint_lower(blanks,science_ap7,science_trough_offset):
    usable=[]
    for r in blanks:
        a=f(r.get("ap7_signed_z"))
        o=f(r.get("negative_gaussian_trough_offset_px_r7"))
        if None not in (a,o):
            usable.append((a,o))
    if not usable or None in (science_ap7,science_trough_offset):
        return None,None,None
    n=sum(1 for a,o in usable
          if a<=science_ap7 and o<=science_trough_offset)
    p=(1+n)/(len(usable)+1)
    return p,n,len(usable)


def main():
    print("="*128)
    print("ORDER 01 — POSS NEIGHBOURING-SOURCE ATTRIBUTION / CENTRED-DEFICIT AUDIT v028x")
    print("="*128)
    print("NO NETWORK ACCESS.")
    print("SCIENCE PIXELS ARE READ.")
    print("Frozen transient detector is NOT rerun.\n")

    for p in (V028V_SCRIPT,V028W_JSON,V028W_BLANK,V028B_GAIA,STRICT,POSS_CAND):
        if not p.is_file():
            print(f"FAIL missing input: {p}");return 2

    v=load_v028v_module()
    vw=json.loads(V028W_JSON.read_text(encoding="utf-8"))
    if vw.get("frozen_active_ranks")!=EXPECTED:
        raise RuntimeError("v028w frozen ranks mismatch")
    if vw.get("guards",{}).get("candidate_state_mutation") is not False:
        raise RuntimeError("v028w state guard mismatch")

    strict_rows=read_csv(STRICT)
    native=read_csv(POSS_CAND)
    gaia=read_csv(V028B_GAIA)
    blank=read_csv(V028W_BLANK)
    strict={i(r["strict_rank"]):r for r in strict_rows if i(r["strict_rank"]) in EXPECTED}
    if sorted(strict)!=EXPECTED:
        raise RuntimeError("strict survivor mismatch")

    inv=v.inventory()
    tiles={str(pick(strict[r],"poss_tile_id")) for r in EXPECTED}
    tr={tid:v.fit_transform(native,tid) for tid in sorted(tiles)}
    for tid,t in tr.items():
        if not(t.validation["forward_ok"] and t.validation["inverse_ok"]):
            raise RuntimeError(f"{tid}: transform validation failed")

    science_native={r:v.resolve_science_native(strict[r],native) for r in EXPECTED}
    vwres={int(r["strict_rank"]):r for r in vw["results"]}

    # Precompute frozen Gaia predictions in POSS pixels.
    gaia_by_rank={r:[] for r in EXPECTED}
    for g in gaia:
        rank=rank_of_gaia(g)
        if rank not in EXPECTED:
            continue
        ra=f(pick(g,"ra_target_deg"));dec=f(pick(g,"dec_target_deg"))
        if None in (ra,dec):
            continue
        tid=str(pick(strict[rank],"poss_tile_id"))
        gx,gy=tr[tid].sky_to_pixel(ra,dec)
        gaia_by_rank[rank].append({
            "source_id":str(pick(g,"source_id")),
            "g_mag":f(pick(g,"g_mag")),
            "ra_target_deg":ra,
            "dec_target_deg":dec,
            "pred_global_x":gx,
            "pred_global_y":gy,
        })

    native_by_tile={}
    for r in native:
        native_by_tile.setdefault(str(r.get("tile_id","")),[]).append(r)

    print("Frozen v028w/rank/tile/transform guards: PASS\n")

    out=[]
    for rank in EXPECTED:
        nr=science_native[rank]
        tid=str(nr["tile_id"])
        sci_idx=i(nr.get("candidate_index"))
        sgx=f(nr.get("global_x"));sgy=f(nr.get("global_y"))
        ex=local_extrema(v,inv[tid],sgx,sgy)
        if ex["status"]!="SUCCESS":
            raise RuntimeError(f"#{rank}: local extrema failed")

        scale=tr[tid].local_scale(sgx,sgy)
        pos=ex["positive"];neg=ex["negative"]

        pra,pdec=tr[tid].pixel_to_sky(pos["global_x"],pos["global_y"])
        nra,ndec=tr[tid].pixel_to_sky(neg["global_x"],neg["global_y"])

        pg=nearest_gaia(pos["global_x"],pos["global_y"],gaia_by_rank[rank])
        ng=nearest_gaia(neg["global_x"],neg["global_y"],gaia_by_rank[rank])
        sg=nearest_gaia(sgx,sgy,gaia_by_rank[rank])

        pn=nearest_native(pos["global_x"],pos["global_y"],
                          native_by_tile.get(tid,[]),sci_idx)
        nn=nearest_native(neg["global_x"],neg["global_y"],
                          native_by_tile.get(tid,[]),sci_idx)

        vr=vwres[rank]
        blanks=[r for r in blank if i(r.get("strict_rank"))==rank]
        jp,jn,jN=guarded_joint_lower(
            blanks,
            f(vr.get("science_ap7_signed_z")),
            f(vr.get("science_negative_trough_offset_px")),
        )

        pos_gaia_match=bool(pg and pg["distance_px"]<=GAIA_MATCH_MAX_PX)
        pos_native_match=bool(pn and pn["distance_px"]<=NATIVE_MATCH_MAX_PX)
        neg_gaia_match=bool(ng and ng["distance_px"]<=GAIA_MATCH_MAX_PX)
        neg_native_match=bool(nn and nn["distance_px"]<=NATIVE_MATCH_MAX_PX)

        # Descriptive attribution.
        if pos["z"]>=STRONG_POSITIVE_Z and pos["offset_px"]>4:
            if pos_gaia_match:
                positive_attr="DISPLACED_POSITIVE_STRUCTURE_MATCHES_GAIA"
            elif pos_native_match:
                positive_attr="DISPLACED_POSITIVE_STRUCTURE_MATCHES_NATIVE_DETECTION"
            else:
                positive_attr="DISPLACED_POSITIVE_STRUCTURE_UNATTRIBUTED"
        elif pos["z"]>=STRONG_POSITIVE_Z:
            positive_attr="STRONG_POSITIVE_STRUCTURE_NEAR_SCIENCE_POSITION"
        else:
            positive_attr="NO_STRONG_POSITIVE_STRUCTURE_WITHIN_25PX"

        centered_neg=(
            f(vr.get("science_ap7_signed_z")) is not None
            and f(vr.get("science_ap7_signed_z"))<0
            and f(vr.get("science_negative_trough_offset_px")) is not None
            and f(vr.get("science_negative_trough_offset_px"))<=CENTERED_NEGATIVE_MAX_PX
        )
        if centered_neg:
            if neg_gaia_match:
                negative_attr="CENTERED_NEGATIVE_FEATURE_NEAR_GAIA_SOURCE"
            elif neg_native_match:
                negative_attr="CENTERED_NEGATIVE_FEATURE_NEAR_OTHER_NATIVE_DETECTION"
            else:
                negative_attr="CENTERED_NEGATIVE_FEATURE_WITHOUT_POSITIVE_SOURCE_COUNTERPART"
        else:
            negative_attr="NO_STRONG_CENTERED_NEGATIVE_ATTRIBUTION"

        row={
            "strict_rank":rank,
            "tile_id":tid,
            "science_candidate_index":sci_idx,
            "science_global_x":sgx,
            "science_global_y":sgy,
            "pixel_scale_arcsec":scale,
            "science_ap7_signed_z":f(vr.get("science_ap7_signed_z")),
            "science_negative_trough_offset_px":f(vr.get("science_negative_trough_offset_px")),
            "blank_joint_negative_tail_p":jp,
            "blank_joint_negative_count":jn,
            "blank_joint_negative_total":jN,

            "positive_dx_px":pos["dx_px"],
            "positive_dy_px":pos["dy_px"],
            "positive_offset_px":pos["offset_px"],
            "positive_offset_arcsec":pos["offset_px"]*scale,
            "positive_z":pos["z"],
            "positive_ra_deg":pra,
            "positive_dec_deg":pdec,
            "positive_attribution":positive_attr,
            "positive_gaia_match":pos_gaia_match,
            "positive_nearest_gaia_distance_px":None if pg is None else pg["distance_px"],
            "positive_nearest_gaia_distance_arcsec":None if pg is None else pg["distance_px"]*scale,
            "positive_nearest_gaia_source_id":None if pg is None else pg["source_id"],
            "positive_nearest_gaia_g_mag":None if pg is None else pg["g_mag"],
            "positive_native_match":pos_native_match,
            "positive_nearest_native_distance_px":None if pn is None else pn["distance_px"],
            "positive_nearest_native_candidate_index":None if pn is None else pn["candidate_index"],
            "positive_nearest_native_snr":None if pn is None else pn["snr"],
            "positive_nearest_native_polarity":None if pn is None else pn["polarity"],

            "negative_dx_px":neg["dx_px"],
            "negative_dy_px":neg["dy_px"],
            "negative_offset_px":neg["offset_px"],
            "negative_offset_arcsec":neg["offset_px"]*scale,
            "negative_z":neg["z"],
            "negative_ra_deg":nra,
            "negative_dec_deg":ndec,
            "negative_attribution":negative_attr,
            "negative_gaia_match":neg_gaia_match,
            "negative_nearest_gaia_distance_px":None if ng is None else ng["distance_px"],
            "negative_nearest_gaia_source_id":None if ng is None else ng["source_id"],
            "negative_native_match":neg_native_match,
            "negative_nearest_native_distance_px":None if nn is None else nn["distance_px"],
            "negative_nearest_native_candidate_index":None if nn is None else nn["candidate_index"],

            "science_nearest_gaia_distance_px":None if sg is None else sg["distance_px"],
            "science_nearest_gaia_distance_arcsec":None if sg is None else sg["distance_px"]*scale,
            "science_nearest_gaia_source_id":None if sg is None else sg["source_id"],
            "science_nearest_gaia_g_mag":None if sg is None else sg["g_mag"],
        }
        out.append(row)

        print(
            f"#{rank}: +structure z={pos['z']:.2f} off={pos['offset_px']:.2f}px "
            f"Gaia={None if pg is None else f'{pg['distance_px']:.2f}px'} "
            f"native={None if pn is None else f'{pn['distance_px']:.2f}px'} "
            f"=> {positive_attr}"
        )
        print(
            f"     -structure z={neg['z']:.2f} off={neg['offset_px']:.2f}px "
            f"jointBlankP={jp} => {negative_attr}"
        )

    fields=sorted({k for r in out for k in r})
    write_csv(OUT_CSV,out,fields)

    payload={
        "stage":"ORDER01_POSS_NEIGHBOR_SOURCE_ATTRIBUTION_V028X",
        "frozen_active_ranks":EXPECTED,
        "guards":{
            "network_access":False,
            "science_pixels_read":True,
            "candidate_pixels_used_as_gaia_reference_inputs":False,
            "transient_detector_rerun":False,
            "transient_detector_parameters_changed":False,
            "candidate_state_mutation":False,
            "candidate_promotion":False,
            "candidate_deletion":False,
            "weighted_candidate_score":False,
        },
        "fixed_policy":{
            "search_radius_px":SEARCH_RADIUS_PX,
            "gaussian_sigma_px":GAUSSIAN_SIGMA_PX,
            "gaia_match_max_px":GAIA_MATCH_MAX_PX,
            "native_match_max_px":NATIVE_MATCH_MAX_PX,
            "strong_positive_z":STRONG_POSITIVE_Z,
            "centered_negative_max_px":CENTERED_NEGATIVE_MAX_PX,
            "joint_blank_estimator":"(1 + count[blank_ap7<=science_ap7 AND blank_trough_offset<=science_offset])/(N+1)"
        },
        "results":out,
        "interpretive_boundary":(
            "Spatial coincidence of a displaced positive structure with a frozen "
            "Gaia source or independent native POSS detection provides a concrete "
            "neighbour-source explanation for broad positive aperture flux. A "
            "centred negative feature without such a positive-source counterpart "
            "supports a local deficit/defect interpretation but does not identify "
            "the physical mechanism. Joint blank tails are local descriptive "
            "empirical diagnostics, not astrophysical p-values. No candidate "
            "state is changed."
        )
    }
    write_json(OUT_JSON,payload)

    md=[
        "# ORDER 01 — POSS Neighbouring-Source Attribution / Centred-Deficit Audit v028x","",
        "## Guard state","",
        "- No network access.",
        "- Science pixels were read.",
        "- The frozen transient detector was not rerun.",
        "- No candidate was promoted, deleted, or otherwise mutated.","",
        "## Results","",
        "| rank | +structure Z | +offset | nearest Gaia | +attribution | -offset | joint negative blank p | -attribution |",
        "|---:|---:|---:|---:|---|---:|---:|---|"
    ]
    for r in out:
        gd=r["positive_nearest_gaia_distance_px"]
        md.append(
            f"| #{r['strict_rank']} | {r['positive_z']:.2f} | "
            f"{r['positive_offset_px']:.2f} px | "
            f"{'n/a' if gd is None else f'{gd:.2f} px'} | "
            f"`{r['positive_attribution']}` | "
            f"{r['negative_offset_px']:.2f} px | "
            f"{'n/a' if r['blank_joint_negative_tail_p'] is None else f'{r['blank_joint_negative_tail_p']:.4f}'} | "
            f"`{r['negative_attribution']}` |"
        )
    md += ["","## Interpretation boundary","",payload["interpretive_boundary"]]
    OUT_MD.write_text("\n".join(md),encoding="utf-8")

    print("\nOutputs:")
    print(f"  {OUT_JSON}")
    print(f"  {OUT_CSV}")
    print(f"  {OUT_MD}")
    print()
    print("NO network query was made.")
    print("SCIENCE PIXELS WERE READ.")
    print("Transient detector was NOT rerun.")
    print("No candidate was promoted or deleted.")
    return 0


if __name__=="__main__":
    raise SystemExit(main())
