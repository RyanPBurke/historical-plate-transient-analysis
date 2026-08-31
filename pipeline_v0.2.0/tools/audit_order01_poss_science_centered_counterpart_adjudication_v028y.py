#!/usr/bin/env python3
"""
ORDER 01 — corrected POSS science-centred counterpart adjudication v028y

Purpose
-------
Correct one attribution bug in v028x and consolidate the physical POSS evidence.

v028x correctly localized displaced positive structures, but its #29 negative
attribution matched the strongest negative extremum anywhere inside 25 px.
For #29 that extremum lies at the 25-px search boundary, whereas the
scientifically relevant deficit is the separate trough only 1 px from the
frozen science coordinate.

v028y therefore performs source-counterpart matching at the SCIENCE-CENTRED
feature itself:

  - exact frozen science coordinate
  - strongest Gaussian-smoothed negative trough within 2 px of science
  - nearest Gaia source to each
  - nearest independent native POSS detection to each
  - nearest POSITIVE-polarity native POSS detection to each

It also consolidates v028w/v028x evidence for displaced positive neighbours.

No network access.
SCIENCE PIXELS ARE READ only to localize the <=2 px centred trough.
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

V028V_SCRIPT = ROOT / "tools" / "audit_order01_poss_physical_source_centering_v028v.py"
V028W_JSON = BASE / "order01_poss_signal_matched_and_blank_controls_v028w.json"
V028X_JSON = BASE / "order01_poss_neighbor_source_attribution_v028x.json"
V028B_GAIA = BASE / "order01_gaia_source_candidates_v028b.csv"
STRICT = BASE / "order01_strict_match_triage_v028.csv"
POSS_CAND = BASE / "order01_poss_native_candidates.csv"

OUT_JSON = BASE / "order01_poss_science_centered_counterpart_adjudication_v028y.json"
OUT_CSV = BASE / "order01_poss_science_centered_counterpart_adjudication_v028y.csv"
OUT_MD = BASE / "ORDER01_POSS_SCIENCE_CENTERED_COUNTERPART_ADJUDICATION_V028Y.md"

EXPECTED = [10,24,25,26,29,30]

CENTER_TROUGH_RADIUS_PX = 2.0
COUNTERPART_MATCH_MAX_PX = 4.0
POSITIVE_NATIVE_MATCH_MAX_PX = 4.0
STRONG_CENTERED_NEG_AP7 = -3.0


def load_v028v_module():
    spec = importlib.util.spec_from_file_location("v028vmod", V028V_SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to import {V028V_SCRIPT}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def read_csv(path):
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def write_csv(path, rows, fields):
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        w.writeheader(); w.writerows(rows)
    tmp.replace(path)


def write_json(path, obj):
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, indent=2, sort_keys=True, default=str) + "\n",
                   encoding="utf-8")
    tmp.replace(path)


def f(v, default=None):
    try:
        if v is None or str(v).strip() == "":
            return default
        x = float(str(v).strip())
        return x if math.isfinite(x) else default
    except Exception:
        return default


def i(v, default=None):
    try:
        if v is None or str(v).strip() == "":
            return default
        return int(float(str(v).strip()))
    except Exception:
        return default


def pick(row, *names, default=None):
    norm = {str(k).lower().replace("_",""): k for k in row}
    for name in names:
        q = str(name).lower().replace("_","")
        if q in norm:
            return row[norm[q]]
    return default


def rank_of_gaia(row):
    return i(pick(row, "strict_rank", "rank", "candidate_rank", "survivor_rank"))


def nearest_point(gx, gy, rows, gxk, gyk, predicate=None):
    q=[]
    for r in rows:
        if predicate is not None and not predicate(r):
            continue
        rx=f(r.get(gxk)); ry=f(r.get(gyk))
        if rx is None or ry is None:
            continue
        q.append((math.hypot(rx-gx, ry-gy), r))
    if not q:
        return None
    q.sort(key=lambda z:z[0])
    d,r=q[0]
    return d,r


def centered_trough(v, meta, gx, gy):
    arr=v.load_arr(meta)
    ex0,ex1,ey0,ey1=meta["extended"]
    px=gx-ex0; py=gy-ey0
    ix=int(round(px)); iy=int(round(py))
    R=v.STAMP_RADIUS
    x0=ix-R; x1=ix+R+1; y0=iy-R; y1=iy+R+1
    if x0<0 or y0<0 or x1>arr.shape[1] or y1>arr.shape[0]:
        return {"status":"STAMP_OUTSIDE_TILE"}

    cut=np.asarray(arr[y0:y1,x0:x1],float)
    yy,xx=np.indices(cut.shape)
    cx=px-x0; cy=py-y0
    rr=np.hypot(xx-cx,yy-cy)
    bgmask=(rr>=v.BACKGROUND_INNER)&(rr<=v.BACKGROUND_OUTER)
    plane,resid,sigma,beta=v.robust_plane(cut,xx,yy,bgmask)
    sm=gaussian_filter(resid,v.GAUSSIAN_SIGMA_PX,mode="nearest")/sigma

    mask=rr<=CENTER_TROUGH_RADIUS_PX
    score=np.where(mask,sm,np.inf)
    y,x=np.unravel_index(int(np.argmin(score)),score.shape)
    dx=float(x-cx); dy=float(y-cy)
    return {
        "status":"SUCCESS",
        "z":float(sm[y,x]),
        "dx_px":dx,
        "dy_px":dy,
        "offset_px":math.hypot(dx,dy),
        "global_x":float(x+x0+ex0),
        "global_y":float(y+y0+ey0),
    }


def main():
    print("="*128)
    print("ORDER 01 — CORRECTED POSS SCIENCE-CENTRED COUNTERPART ADJUDICATION v028y")
    print("="*128)
    print("NO NETWORK ACCESS.")
    print("SCIENCE PIXELS ARE READ.")
    print("Frozen transient detector is NOT rerun.\n")

    for p in (V028V_SCRIPT,V028W_JSON,V028X_JSON,V028B_GAIA,STRICT,POSS_CAND):
        if not p.is_file():
            print(f"FAIL missing input: {p}"); return 2

    v=load_v028v_module()
    vw=json.loads(V028W_JSON.read_text(encoding="utf-8"))
    vx=json.loads(V028X_JSON.read_text(encoding="utf-8"))
    if vw.get("frozen_active_ranks")!=EXPECTED or vx.get("frozen_active_ranks")!=EXPECTED:
        raise RuntimeError("frozen rank mismatch")
    if vx.get("guards",{}).get("candidate_state_mutation") is not False:
        raise RuntimeError("v028x state guard mismatch")

    strict_rows=read_csv(STRICT)
    native=read_csv(POSS_CAND)
    gaia=read_csv(V028B_GAIA)
    strict={i(r["strict_rank"]):r for r in strict_rows if i(r["strict_rank"]) in EXPECTED}
    if sorted(strict)!=EXPECTED:
        raise RuntimeError("strict survivor mismatch")

    inv=v.inventory()
    tiles={str(pick(strict[r],"poss_tile_id")) for r in EXPECTED}
    tr={tid:v.fit_transform(native,tid) for tid in sorted(tiles)}
    for tid,t in tr.items():
        if not(t.validation["forward_ok"] and t.validation["inverse_ok"]):
            raise RuntimeError(f"{tid}: transform validation failed")

    sci_native={r:v.resolve_science_native(strict[r],native) for r in EXPECTED}
    wr={int(r["strict_rank"]):r for r in vw["results"]}
    xr={int(r["strict_rank"]):r for r in vx["results"]}

    # Gaia predicted pixels.
    gaia_by_rank={r:[] for r in EXPECTED}
    for g in gaia:
        rank=rank_of_gaia(g)
        if rank not in EXPECTED: continue
        ra=f(pick(g,"ra_target_deg")); dec=f(pick(g,"dec_target_deg"))
        if None in (ra,dec): continue
        tid=str(pick(strict[rank],"poss_tile_id"))
        gx,gy=tr[tid].sky_to_pixel(ra,dec)
        gaia_by_rank[rank].append({
            "source_id":str(pick(g,"source_id")),
            "g_mag":f(pick(g,"g_mag")),
            "pred_global_x":gx,"pred_global_y":gy,
        })

    native_by_tile={}
    for r in native:
        native_by_tile.setdefault(str(r.get("tile_id","")),[]).append(r)

    print("Frozen v028w/v028x/rank/tile/transform guards: PASS\n")

    out=[]
    for rank in EXPECTED:
        nr=sci_native[rank]
        tid=str(nr["tile_id"])
        sci_idx=i(nr.get("candidate_index"))
        sgx=f(nr.get("global_x")); sgy=f(nr.get("global_y"))
        scale=tr[tid].local_scale(sgx,sgy)

        ct=centered_trough(v,inv[tid],sgx,sgy)
        if ct["status"]!="SUCCESS":
            raise RuntimeError(f"#{rank}: centred trough localization failed")

        # Counterparts at exact science coordinate.
        gq=nearest_point(sgx,sgy,gaia_by_rank[rank],"pred_global_x","pred_global_y")
        nq=nearest_point(
            sgx,sgy,native_by_tile.get(tid,[]),"global_x","global_y",
            predicate=lambda r:i(r.get("candidate_index"))!=sci_idx
        )
        npq=nearest_point(
            sgx,sgy,native_by_tile.get(tid,[]),"global_x","global_y",
            predicate=lambda r:(
                i(r.get("candidate_index"))!=sci_idx and i(r.get("polarity"))==1
            )
        )

        # Counterparts at the actual <=2 px centred trough.
        gt=nearest_point(ct["global_x"],ct["global_y"],
                         gaia_by_rank[rank],"pred_global_x","pred_global_y")
        nt=nearest_point(
            ct["global_x"],ct["global_y"],native_by_tile.get(tid,[]),"global_x","global_y",
            predicate=lambda r:i(r.get("candidate_index"))!=sci_idx
        )
        npt=nearest_point(
            ct["global_x"],ct["global_y"],native_by_tile.get(tid,[]),"global_x","global_y",
            predicate=lambda r:(
                i(r.get("candidate_index"))!=sci_idx and i(r.get("polarity"))==1
            )
        )

        def unpack_gaia(q,prefix):
            if q is None:
                return {f"{prefix}_distance_px":None,
                        f"{prefix}_distance_arcsec":None,
                        f"{prefix}_source_id":None,
                        f"{prefix}_g_mag":None}
            d,r=q
            return {f"{prefix}_distance_px":d,
                    f"{prefix}_distance_arcsec":d*scale,
                    f"{prefix}_source_id":r["source_id"],
                    f"{prefix}_g_mag":r["g_mag"]}

        def unpack_native(q,prefix):
            if q is None:
                return {f"{prefix}_distance_px":None,
                        f"{prefix}_candidate_index":None,
                        f"{prefix}_snr":None,
                        f"{prefix}_polarity":None}
            d,r=q
            return {f"{prefix}_distance_px":d,
                    f"{prefix}_candidate_index":i(r.get("candidate_index")),
                    f"{prefix}_snr":f(r.get("snr")),
                    f"{prefix}_polarity":i(r.get("polarity"))}

        w=wr[rank]; x=xr[rank]
        ap7=f(w.get("science_ap7_signed_z"))
        science_trough_off=f(w.get("science_negative_trough_offset_px"))
        jointp=f(x.get("blank_joint_negative_tail_p"))

        gaia_science_match=bool(gq and gq[0]<=COUNTERPART_MATCH_MAX_PX)
        posnative_science_match=bool(npq and npq[0]<=POSITIVE_NATIVE_MATCH_MAX_PX)
        gaia_trough_match=bool(gt and gt[0]<=COUNTERPART_MATCH_MAX_PX)
        posnative_trough_match=bool(npt and npt[0]<=POSITIVE_NATIVE_MATCH_MAX_PX)

        centered_negative=bool(
            ap7 is not None and ap7<=STRONG_CENTERED_NEG_AP7
            and science_trough_off is not None and science_trough_off<=CENTER_TROUGH_RADIUS_PX
        )

        positive_neighbor_attributed=(
            x.get("positive_attribution")=="DISPLACED_POSITIVE_STRUCTURE_MATCHES_GAIA"
        )
        no_centered_positive=not bool(w.get("centered_positive_core_ge3sigma"))

        if centered_negative:
            if not gaia_trough_match and not posnative_trough_match:
                adjudication="CENTERED_NEGATIVE_DEFICIT_NO_LOCAL_POSITIVE_SOURCE_COUNTERPART"
            else:
                adjudication="CENTERED_NEGATIVE_DEFICIT_NEAR_LOCAL_POSITIVE_SOURCE_COUNTERPART"
        elif positive_neighbor_attributed and no_centered_positive:
            adjudication="BROAD_POSITIVE_FLUX_ATTRIBUTED_TO_NEIGHBOUR;_NO_CENTERED_POINT_SOURCE"
        elif no_centered_positive:
            adjudication="NO_CENTERED_POSITIVE_POINT_SOURCE;_POSS_STRUCTURE_WEAK_OR_MIXED"
        else:
            adjudication="POSS_ENDPOINT_REMAINS_UNRESOLVED"

        row={
            "strict_rank":rank,
            "tile_id":tid,
            "science_candidate_index":sci_idx,
            "science_global_x":sgx,
            "science_global_y":sgy,
            "pixel_scale_arcsec":scale,
            "science_ap7_signed_z":ap7,
            "science_negative_trough_offset_px_v028w":science_trough_off,
            "blank_joint_negative_tail_p_v028x":jointp,
            "centered_negative_by_v028w":centered_negative,
            "centered_trough_z_r2":ct["z"],
            "centered_trough_dx_px_r2":ct["dx_px"],
            "centered_trough_dy_px_r2":ct["dy_px"],
            "centered_trough_offset_px_r2":ct["offset_px"],
            "centered_trough_global_x":ct["global_x"],
            "centered_trough_global_y":ct["global_y"],
            "science_gaia_match_within4px":gaia_science_match,
            "science_positive_native_match_within4px":posnative_science_match,
            "trough_gaia_match_within4px":gaia_trough_match,
            "trough_positive_native_match_within4px":posnative_trough_match,
            "v028x_positive_attribution":x.get("positive_attribution"),
            "v028x_displaced_positive_z":f(x.get("positive_z")),
            "v028x_displaced_positive_offset_px":f(x.get("positive_offset_px")),
            "v028x_displaced_positive_gaia_source_id":x.get("positive_nearest_gaia_source_id"),
            "v028x_displaced_positive_gaia_g_mag":f(x.get("positive_nearest_gaia_g_mag")),
            "v028x_displaced_positive_gaia_distance_px":f(x.get("positive_nearest_gaia_distance_px")),
            "adjudication":adjudication,
            **unpack_gaia(gq,"science_nearest_gaia"),
            **unpack_native(nq,"science_nearest_native"),
            **unpack_native(npq,"science_nearest_positive_native"),
            **unpack_gaia(gt,"trough_nearest_gaia"),
            **unpack_native(nt,"trough_nearest_native"),
            **unpack_native(npt,"trough_nearest_positive_native"),
        }
        out.append(row)

        print(
            f"#{rank}: ap7={ap7:+.2f} trough={science_trough_off:.2f}px "
            f"jointP={jointp} "
            f"scienceGaia={None if gq is None else f'{gq[0]:.2f}px'} "
            f"sciencePosNative={None if npq is None else f'{npq[0]:.2f}px'}"
        )
        print(
            f"     centred trough r2: z={ct['z']:.2f} off={ct['offset_px']:.2f}px "
            f"Gaia={None if gt is None else f'{gt[0]:.2f}px'} "
            f"PosNative={None if npt is None else f'{npt[0]:.2f}px'} "
            f"=> {adjudication}"
        )

    write_csv(OUT_CSV,out,sorted({k for r in out for k in r}))

    payload={
        "stage":"ORDER01_POSS_SCIENCE_CENTERED_COUNTERPART_ADJUDICATION_V028Y",
        "frozen_active_ranks":EXPECTED,
        "guards":{
            "network_access":False,
            "science_pixels_read":True,
            "candidate_pixels_used_as_reference_inputs":False,
            "transient_detector_rerun":False,
            "transient_detector_parameters_changed":False,
            "candidate_state_mutation":False,
            "candidate_promotion":False,
            "candidate_deletion":False,
            "weighted_candidate_score":False,
            "v028x_centered_negative_native_attribution_corrected":True,
        },
        "fixed_policy":{
            "center_trough_radius_px":CENTER_TROUGH_RADIUS_PX,
            "counterpart_match_max_px":COUNTERPART_MATCH_MAX_PX,
            "positive_native_match_max_px":POSITIVE_NATIVE_MATCH_MAX_PX,
            "strong_centered_negative_ap7":STRONG_CENTERED_NEG_AP7,
        },
        "results":out,
        "interpretive_boundary":(
            "This stage corrects v028x by matching source counterparts to the "
            "science-centred feature rather than to an unrelated field extremum. "
            "A displaced positive Gaia match can explain broad positive aperture "
            "flux without implying a point source at the science coordinate. "
            "A centred negative deficit lacking a Gaia or positive-polarity "
            "native counterpart supports a local deficit/defect interpretation, "
            "but does not identify the defect mechanism. No candidate state changes."
        )
    }
    write_json(OUT_JSON,payload)

    md=[
        "# ORDER 01 — Corrected POSS Science-Centred Counterpart Adjudication v028y","",
        "## Guard state","",
        "- No network access.",
        "- Science pixels were read only to localize the <=2 px centred trough.",
        "- The frozen transient detector was not rerun.",
        "- No candidate was promoted, deleted, or otherwise mutated.",
        "- v028x's #29 native attribution is explicitly corrected here.","",
        "## Results","",
        "| rank | ap7 Z | trough offset | joint blank p | nearest Gaia at science | nearest +native at science | adjudication |",
        "|---:|---:|---:|---:|---:|---:|---|"
    ]
    for r in out:
        md.append(
            f"| #{r['strict_rank']} | {r['science_ap7_signed_z']:.3f} | "
            f"{r['science_negative_trough_offset_px_v028w']:.2f} px | "
            f"{r['blank_joint_negative_tail_p_v028x'] if r['blank_joint_negative_tail_p_v028x'] is not None else 'n/a'} | "
            f"{r['science_nearest_gaia_distance_px']:.2f} px | "
            f"{r['science_nearest_positive_native_distance_px']:.2f} px | "
            f"`{r['adjudication']}` |"
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
