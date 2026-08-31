#!/usr/bin/env python3
"""
ORDER 01 — focused final POSS mechanism audit for active pairs #24/#30 v028ac

Prerequisite
------------
v028ab formally reduced the active unresolved two-observatory set to [24, 30].

This stage keeps those states frozen and addresses their two distinct remaining
POSS mechanisms.

BRANCH #24 — physical plate-edge / bipolar detector structure
-------------------------------------------------------------
#24 lies close to the physical x=0 edge and had inadequate symmetric blank
controls. We therefore:
  * infer the real POSS plate bounds from completed tile metadata;
  * build deterministic same-edge-distance raw-image controls along the plate,
    excluding known Gaia sources/native candidates;
  * compare #24's aperture/centering measurements with those edge controls;
  * audit how commonly negative native detections near that physical edge have
    a nearby positive-polarity native partner (candidate #24 itself has one
    only ~4 px away).

BRANCH #30 — bright-star / saturation-aware detector satellites
---------------------------------------------------------------
#30 has satellite-compatible geometry around Gaia source
302788670313550336 (G~7.92), but v028x did not label the neighbour because the
smoothed raw positive peak was below the generic >=3 sigma threshold.
We therefore:
  * use frozen v028b Gaia sources on this same POSS plate;
  * construct a bright-star control population (G<=10);
  * for each bright star, measure raw image centering, nearest positive native
    detection, and count/radii of negative frozen detector satellites;
  * compare #30's identified neighbour and science satellite directly with
    this bright-star population.

No network access.
SCIENCE PIXELS ARE READ (edge controls and bright-star raw measurements).
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

ROOT = Path.cwd()
BASE = ROOT / "results" / "order01_native_full_v028"
WORK = ROOT / "work" / "order01_native_full_v028"

V028V_SCRIPT = ROOT / "tools" / "audit_order01_poss_physical_source_centering_v028v.py"
V028AB_JSON = BASE / "order01_candidate_disposition_freeze_v028ab.json"
V028AA_JSON = BASE / "order01_poss_platewide_detector_satellite_adjudication_v028aa.json"
V028Y_JSON = BASE / "order01_poss_science_centered_counterpart_adjudication_v028y.json"
V028B_GAIA = BASE / "order01_gaia_source_candidates_v028b.csv"
STRICT = BASE / "order01_strict_match_triage_v028.csv"
POSS_CAND = BASE / "order01_poss_native_candidates.csv"
POSS_TILE_DIR = WORK / "poss_tiles"

OUT_JSON = BASE / "order01_active24_30_focused_poss_mechanism_v028ac.json"
OUT_CSV = BASE / "order01_active24_30_focused_poss_mechanism_v028ac.csv"
OUT_EDGE = BASE / "order01_candidate24_edge_controls_v028ac.csv"
OUT_BRIGHT = BASE / "order01_candidate30_bright_star_controls_v028ac.csv"
OUT_MD = BASE / "ORDER01_ACTIVE24_30_FOCUSED_POSS_MECHANISM_V028AC.md"

PREVIOUS = [10,24,25,26,29,30]
ACTIVE = [24,30]

# General
STAMP_MARGIN = 32

# #24 edge controls
EDGE_X_TOL_PX = 28.0
EDGE_Y_STEP_PX = 160
EDGE_EXCLUDE_NATIVE_PX = 10.0
EDGE_EXCLUDE_GAIA_PX = 10.0
EDGE_MAX_CONTROLS = 160
EDGE_PAIR_BAND_PX = 160.0
BIPOLAR_MATCH_PX = 6.0
BIPOLAR_STRONG_MATCH_PX = 4.5

# #30 bright-star controls
BRIGHT_G_MAX = 10.0
BRIGHT_POSITIVE_NATIVE_SEARCH_PX = 14.0
SAT_INNER_PX = 4.0
SAT_OUTER_PX = 25.0
MIN_BRIGHT_CONTROLS = 5
SIMILAR_RADIUS_TOL_PX = 3.0


def load_v028v_module():
    spec=importlib.util.spec_from_file_location("v028vmod",V028V_SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import {V028V_SCRIPT}")
    mod=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def read_csv(path):
    with path.open("r",encoding="utf-8-sig",newline="") as fh:
        return list(csv.DictReader(fh))


def write_csv(path,rows,fields):
    tmp=path.with_suffix(path.suffix+".tmp")
    with tmp.open("w",encoding="utf-8",newline="") as fh:
        w=csv.DictWriter(fh,fieldnames=fields,extrasaction="ignore")
        w.writeheader(); w.writerows(rows)
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


def quant(vals,q):
    a=np.asarray([x for x in vals if x is not None and math.isfinite(float(x))],float)
    return None if a.size==0 else float(np.quantile(a,q))


def emp_lower(vals,x):
    a=np.asarray([v for v in vals if v is not None and math.isfinite(float(v))],float)
    if a.size==0 or x is None:return None
    return float((1+np.count_nonzero(a<=x))/(len(a)+1))


def emp_upper(vals,x):
    a=np.asarray([v for v in vals if v is not None and math.isfinite(float(v))],float)
    if a.size==0 or x is None:return None
    return float((1+np.count_nonzero(a>=x))/(len(a)+1))


def plate_core_inventory():
    rows=[]
    for jp in sorted(POSS_TILE_DIR.glob("*.json")):
        try:o=json.loads(jp.read_text(encoding="utf-8"))
        except Exception:continue
        if o.get("complete") is not True:continue
        core=o.get("core");ext=o.get("extended")
        tid=str(o.get("tile_id","")).strip()
        if not tid or not isinstance(core,list) or len(core)!=4:continue
        if not isinstance(ext,list) or len(ext)!=4:continue
        rows.append({
            "tile_id":tid,
            "core":tuple(map(int,core)),
            "extended":tuple(map(int,ext)),
        })
    if not rows:raise RuntimeError("no completed POSS tile metadata")
    xmin=min(r["core"][0] for r in rows);xmax=max(r["core"][1] for r in rows)
    ymin=min(r["core"][2] for r in rows);ymax=max(r["core"][3] for r in rows)
    return rows,(xmin,xmax,ymin,ymax)


def find_meta_for_point(inv,core_rows,gx,gy):
    """
    Select a cached tile whose extended region can support the v028v stamp.
    Prefer one whose core owns the coordinate.
    """
    candidates=[]
    for c in core_rows:
        ex0,ex1,ey0,ey1=c["extended"]
        if not (ex0+STAMP_MARGIN <= gx < ex1-STAMP_MARGIN and
                ey0+STAMP_MARGIN <= gy < ey1-STAMP_MARGIN):
            continue
        tid=c["tile_id"]
        if tid not in inv:continue
        x0,x1,y0,y1=c["core"]
        owner=(x0<=gx<x1 and y0<=gy<y1)
        candidates.append((not owner,tid))
    if not candidates:return None
    candidates.sort()
    return inv[candidates[0][1]]


def nearest_dist(gx,gy,pts):
    if not pts:return None
    return min(math.hypot(px-gx,py-gy) for px,py in pts)


def nearest_native(gx,gy,rows,polarity=None,exclude_idx=None,maxdist=None):
    q=[]
    for r in rows:
        if exclude_idx is not None and i(r.get("candidate_index"))==exclude_idx:
            continue
        if polarity is not None and i(r.get("polarity"))!=polarity:
            continue
        rx=f(r.get("global_x"));ry=f(r.get("global_y"))
        if None in (rx,ry):continue
        d=math.hypot(rx-gx,ry-gy)
        if maxdist is not None and d>maxdist:continue
        q.append((d,r))
    if not q:return None
    q.sort(key=lambda z:z[0])
    return q[0]


def main():
    print("="*128)
    print("ORDER 01 — FOCUSED FINAL POSS MECHANISM AUDIT FOR ACTIVE #24/#30 v028ac")
    print("="*128)
    print("NO NETWORK ACCESS.")
    print("SCIENCE PIXELS ARE READ.")
    print("Frozen transient detector is NOT rerun.\n")

    for p in (V028V_SCRIPT,V028AB_JSON,V028AA_JSON,V028Y_JSON,
              V028B_GAIA,STRICT,POSS_CAND):
        if not p.is_file():
            print(f"FAIL missing input: {p}");return 2

    v=load_v028v_module()
    ab=json.loads(V028AB_JSON.read_text(encoding="utf-8"))
    aa=json.loads(V028AA_JSON.read_text(encoding="utf-8"))
    yy=json.loads(V028Y_JSON.read_text(encoding="utf-8"))
    if ab.get("new_active_unresolved_two_observatory_set")!=ACTIVE:
        raise RuntimeError("v028ab active-set guard mismatch")
    if ab.get("guards",{}).get("candidate_state_mutation") is not True:
        raise RuntimeError("v028ab mutation guard mismatch")
    if aa.get("frozen_active_ranks")!=PREVIOUS or yy.get("frozen_active_ranks")!=PREVIOUS:
        raise RuntimeError("prerequisite frozen-rank mismatch")

    strict_rows=read_csv(STRICT)
    native=read_csv(POSS_CAND)
    gaia=read_csv(V028B_GAIA)
    strict={i(r["strict_rank"]):r for r in strict_rows if i(r["strict_rank"]) in PREVIOUS}
    if sorted(strict)!=PREVIOUS:
        raise RuntimeError("strict-rank guard mismatch")

    inv=v.inventory()
    core_rows,bounds=plate_core_inventory()
    xmin,xmax,ymin,ymax=bounds

    tiles={str(pick(strict[r],"poss_tile_id")) for r in PREVIOUS}
    tr={tid:v.fit_transform(native,tid) for tid in sorted(tiles)}
    for tid,t in tr.items():
        if not(t.validation["forward_ok"] and t.validation["inverse_ok"]):
            raise RuntimeError(f"{tid}: transform validation failed")

    sci_native={r:v.resolve_science_native(strict[r],native) for r in PREVIOUS}
    yres={int(r["strict_rank"]):r for r in yy["results"]}
    ares={int(r["strict_rank"]):r for r in aa["results"]}

    native_by_tile={}
    for r in native:
        native_by_tile.setdefault(str(r.get("tile_id","")),[]).append(r)

    # Frozen Gaia predictions in local tile coordinates.
    gaia_pred=[]
    for g in gaia:
        rank=rank_of_gaia(g)
        if rank not in PREVIOUS:continue
        ra=f(pick(g,"ra_target_deg"));dec=f(pick(g,"dec_target_deg"))
        if None in (ra,dec):continue
        tid=str(pick(strict[rank],"poss_tile_id"))
        gx,gy=tr[tid].sky_to_pixel(ra,dec)
        gaia_pred.append({
            "strict_rank":rank,
            "tile_id":tid,
            "source_id":str(pick(g,"source_id")),
            "g_mag":f(pick(g,"g_mag")),
            "global_x":gx,"global_y":gy,
        })

    print(f"Physical POSS core bounds: x=[{xmin},{xmax}) y=[{ymin},{ymax})")
    print("Frozen v028ab/rank/tile/transform guards: PASS\n")

    # ==================================================================
    # BRANCH #24 — edge matched controls
    # ==================================================================
    rank=24
    nr=sci_native[rank]
    sgx=f(nr["global_x"]);sgy=f(nr["global_y"]);sidx=i(nr["candidate_index"])
    tid=str(nr["tile_id"])
    edge_left=sgx-xmin
    edge_right=(xmax-1)-sgx
    edge_bottom=sgy-ymin
    edge_top=(ymax-1)-sgy
    edge_distance=min(edge_left,edge_right,edge_bottom,edge_top)
    edge_name=min(
        [("LEFT",edge_left),("RIGHT",edge_right),("BOTTOM",edge_bottom),("TOP",edge_top)],
        key=lambda z:z[1]
    )[0]

    science24=v.measure(inv[tid],sgx,sgy)
    if science24.get("status")!="SUCCESS":
        raise RuntimeError("#24 science measure failed")

    all_native_pts=[(f(r.get("global_x")),f(r.get("global_y"))) for r in native
                    if f(r.get("global_x")) is not None and f(r.get("global_y")) is not None]
    all_gaia_pts=[(r["global_x"],r["global_y"]) for r in gaia_pred]

    # Same physical edge distance, with small deterministic x offsets.
    xs=[]
    if edge_name=="LEFT":
        base=xmin+edge_distance
        xs=[base-EDGE_X_TOL_PX,base,base+EDGE_X_TOL_PX]
    elif edge_name=="RIGHT":
        base=(xmax-1)-edge_distance
        xs=[base-EDGE_X_TOL_PX,base,base+EDGE_X_TOL_PX]
    else:
        # Candidate is expected LEFT; keep general but use its x for y-edge.
        xs=[sgx-EDGE_X_TOL_PX,sgx,sgx+EDGE_X_TOL_PX]

    edge_controls=[]
    # y phase deliberately offset from candidate so it never samples science.
    start_y=ymin+STAMP_MARGIN+73
    ys=list(range(int(start_y),int(ymax-STAMP_MARGIN),EDGE_Y_STEP_PX))
    for gx in xs:
        for gy in ys:
            if math.hypot(gx-sgx,gy-sgy)<80:continue
            meta=find_meta_for_point(inv,core_rows,gx,gy)
            if meta is None:continue
            if nearest_dist(gx,gy,all_native_pts) is not None and \
               nearest_dist(gx,gy,all_native_pts)<EDGE_EXCLUDE_NATIVE_PX:
                continue
            if nearest_dist(gx,gy,all_gaia_pts) is not None and \
               nearest_dist(gx,gy,all_gaia_pts)<EDGE_EXCLUDE_GAIA_PX:
                continue
            met=v.measure(meta,gx,gy)
            if met.get("status")!="SUCCESS":continue
            edge_controls.append({
                "global_x":gx,"global_y":gy,
                "physical_edge":edge_name,
                "edge_distance_px":min(gx-xmin,(xmax-1)-gx,gy-ymin,(ymax-1)-gy),
                **met
            })
            if len(edge_controls)>=EDGE_MAX_CONTROLS:break
        if len(edge_controls)>=EDGE_MAX_CONTROLS:break

    # Native bipolar-pair statistics.
    neg_native=[r for r in native if i(r.get("polarity"))==-1]
    pos_native=[r for r in native if i(r.get("polarity"))==1]
    pospts=[(f(r["global_x"]),f(r["global_y"]),r) for r in pos_native]

    bipolar_rows=[]
    for n in neg_native:
        gx=f(n.get("global_x"));gy=f(n.get("global_y"))
        if None in (gx,gy):continue
        d_edge=min(gx-xmin,(xmax-1)-gx,gy-ymin,(ymax-1)-gy)
        q=nearest_native(gx,gy,pos_native,polarity=1)
        if q is None:continue
        d,p=q
        bipolar_rows.append({
            "negative_candidate_index":i(n.get("candidate_index")),
            "negative_snr":f(n.get("snr")),
            "negative_global_x":gx,"negative_global_y":gy,
            "edge_distance_px":d_edge,
            "nearest_positive_distance_px":d,
            "nearest_positive_candidate_index":i(p.get("candidate_index")),
            "nearest_positive_snr":f(p.get("snr")),
        })

    b24=next(r for r in bipolar_rows if r["negative_candidate_index"]==sidx)
    edge_band=[r for r in bipolar_rows if r["edge_distance_px"]<=EDGE_PAIR_BAND_PX]
    plate_pairs=bipolar_rows
    edge_close=sum(1 for r in edge_band if r["nearest_positive_distance_px"]<=BIPOLAR_MATCH_PX)
    plate_close=sum(1 for r in plate_pairs if r["nearest_positive_distance_px"]<=BIPOLAR_MATCH_PX)
    edge_strong=sum(1 for r in edge_band if r["nearest_positive_distance_px"]<=BIPOLAR_STRONG_MATCH_PX)

    edge_ap7=[r["ap7_signed_z"] for r in edge_controls]
    edge_center=[r["gaussian_center_z"] for r in edge_controls]
    edge_peakoff=[r["positive_gaussian_peak_offset_px_r7"] for r in edge_controls]

    edge_summary={
        "science_edge":edge_name,
        "science_edge_distance_px":edge_distance,
        "edge_control_count":len(edge_controls),
        "science_ap7_signed_z":science24["ap7_signed_z"],
        "edge_ap7_lower_tail_p":emp_lower(edge_ap7,science24["ap7_signed_z"]),
        "edge_ap7_upper_tail_p":emp_upper(edge_ap7,science24["ap7_signed_z"]),
        "edge_ap7_p05":quant(edge_ap7,.05),
        "edge_ap7_median":quant(edge_ap7,.50),
        "edge_ap7_p95":quant(edge_ap7,.95),
        "science_center_z":science24["gaussian_center_z"],
        "edge_center_lower_tail_p":emp_lower(edge_center,science24["gaussian_center_z"]),
        "science_positive_peak_offset_px":science24["positive_gaussian_peak_offset_px_r7"],
        "edge_peak_offset_p95_px":quant(edge_peakoff,.95),
        "science_nearest_positive_native_px":b24["nearest_positive_distance_px"],
        "science_nearest_positive_native_index":b24["nearest_positive_candidate_index"],
        "edge_negative_count":len(edge_band),
        "edge_negative_with_positive_within6px":edge_close,
        "edge_negative_with_positive_within4p5px":edge_strong,
        "edge_bipolar_fraction_within6px":None if not edge_band else edge_close/len(edge_band),
        "plate_negative_count":len(plate_pairs),
        "plate_negative_with_positive_within6px":plate_close,
        "plate_bipolar_fraction_within6px":None if not plate_pairs else plate_close/len(plate_pairs),
    }

    # Conservative descriptive branch result.
    if (
        len(edge_controls)>=20
        and b24["nearest_positive_distance_px"]<=BIPOLAR_STRONG_MATCH_PX
        and edge_close>=5
    ):
        adj24="EDGE_ASSOCIATED_BIPOLAR_DETECTOR_STRUCTURE_SUPPORTED"
    elif b24["nearest_positive_distance_px"]<=BIPOLAR_STRONG_MATCH_PX:
        adj24="LOCAL_BIPOLAR_DETECTOR_STRUCTURE_PRESENT;_EDGE_SUPPORT_INSUFFICIENT"
    else:
        adj24="EDGE_MECHANISM_UNRESOLVED"

    print("BRANCH #24 — physical edge / bipolar structure")
    print(
        f"  edge={edge_name} distance={edge_distance:.1f}px "
        f"edgeControls={len(edge_controls)}"
    )
    print(
        f"  science ap7={science24['ap7_signed_z']:+.2f}; "
        f"edge p05/med/p95="
        f"{edge_summary['edge_ap7_p05']}/{edge_summary['edge_ap7_median']}/{edge_summary['edge_ap7_p95']}"
    )
    print(
        f"  nearest +native={b24['nearest_positive_distance_px']:.2f}px; "
        f"edge negatives with +partner<=6px={edge_close}/{len(edge_band)}"
    )
    print(f"  => {adj24}\n")

    # ==================================================================
    # BRANCH #30 — bright star / saturation-aware controls
    # ==================================================================
    rank=30
    y30=yres[30]
    a30=ares[30]
    target_sid=str(y30.get("v028x_displaced_positive_gaia_source_id"))
    target_rows=[g for g in gaia_pred if g["source_id"]==target_sid]
    if not target_rows:
        raise RuntimeError(f"#30 target Gaia {target_sid} not found in v028b predictions")
    # Prefer the rank-30 instance.
    target=sorted(target_rows,key=lambda g:(g["strict_rank"]!=30,g["strict_rank"]))[0]
    tgx=target["global_x"];tgy=target["global_y"]
    ttid=target["tile_id"]
    tmeta=inv[ttid]
    tmeasure=v.measure(tmeta,tgx,tgy)
    if tmeasure.get("status")!="SUCCESS":
        raise RuntimeError("#30 neighbour raw measurement failed")

    # Unique bright Gaia sources represented in the frozen local Gaia sets.
    bright_candidates={}
    for g in gaia_pred:
        if g["g_mag"] is None or g["g_mag"]>BRIGHT_G_MAX:continue
        key=(g["source_id"],g["tile_id"])
        bright_candidates.setdefault(key,g)

    bright_rows=[]
    for g in bright_candidates.values():
        tid=g["tile_id"];gx=g["global_x"];gy=g["global_y"]
        if tid not in inv:continue
        met=v.measure(inv[tid],gx,gy)
        if met.get("status")!="SUCCESS":continue

        nrows=native_by_tile.get(tid,[])
        qp=nearest_native(
            gx,gy,nrows,polarity=1,maxdist=BRIGHT_POSITIVE_NATIVE_SEARCH_PX
        )
        neg=[]
        for n in nrows:
            if i(n.get("polarity"))!=-1:continue
            nx=f(n.get("global_x"));ny=f(n.get("global_y"))
            if None in (nx,ny):continue
            d=math.hypot(nx-gx,ny-gy)
            if SAT_INNER_PX<=d<=SAT_OUTER_PX:
                neg.append((d,n))
        neg.sort(key=lambda z:z[0])

        bright_rows.append({
            "source_id":g["source_id"],
            "strict_rank_context":g["strict_rank"],
            "tile_id":tid,
            "g_mag":g["g_mag"],
            "global_x":gx,"global_y":gy,
            "raw_gaussian_center_z":met["gaussian_center_z"],
            "raw_positive_peak_z_r7":met["positive_gaussian_peak_z_r7"],
            "raw_positive_peak_offset_px_r7":met["positive_gaussian_peak_offset_px_r7"],
            "nearest_positive_native_distance_px":None if qp is None else qp[0],
            "nearest_positive_native_index":None if qp is None else i(qp[1].get("candidate_index")),
            "nearest_positive_native_snr":None if qp is None else f(qp[1].get("snr")),
            "negative_satellite_count_4to25px":len(neg),
            "nearest_negative_satellite_radius_px":None if not neg else neg[0][0],
            "negative_satellite_radius_median_px":None if not neg else float(np.median([x[0] for x in neg])),
        })

    if len(bright_rows)<MIN_BRIGHT_CONTROLS:
        print(f"WARNING: only {len(bright_rows)} bright Gaia controls")

    # Exact target row (may occur multiple contexts; select same source/tile).
    tb=[r for r in bright_rows if r["source_id"]==target_sid and r["tile_id"]==ttid]
    if len(tb)!=1:
        raise RuntimeError(f"#30 expected one bright target row, got {len(tb)}")
    tb=tb[0]

    # Use OTHER bright sources as controls.
    bctrl=[r for r in bright_rows
           if not (r["source_id"]==target_sid and r["tile_id"]==ttid)]
    posd=[r["nearest_positive_native_distance_px"] for r in bctrl
          if r["nearest_positive_native_distance_px"] is not None]
    negcnt=[r["negative_satellite_count_4to25px"] for r in bctrl]
    negrad=[r["nearest_negative_satellite_radius_px"] for r in bctrl
            if r["nearest_negative_satellite_radius_px"] is not None]

    sci_radius=f(a30.get("science_to_neighbor_radius_px"))
    sci_snr=f(a30.get("science_native_snr"))
    similar_bright=sum(
        1 for r in bctrl
        if r["nearest_negative_satellite_radius_px"] is not None
        and sci_radius is not None
        and abs(r["nearest_negative_satellite_radius_px"]-sci_radius)<=SIMILAR_RADIUS_TOL_PX
    )

    bright_summary={
        "target_source_id":target_sid,
        "target_g_mag":tb["g_mag"],
        "target_raw_gaussian_center_z":tb["raw_gaussian_center_z"],
        "target_raw_positive_peak_z_r7":tb["raw_positive_peak_z_r7"],
        "target_raw_positive_peak_offset_px_r7":tb["raw_positive_peak_offset_px_r7"],
        "target_nearest_positive_native_distance_px":tb["nearest_positive_native_distance_px"],
        "target_nearest_positive_native_index":tb["nearest_positive_native_index"],
        "target_nearest_positive_native_snr":tb["nearest_positive_native_snr"],
        "target_negative_satellite_count_4to25px":tb["negative_satellite_count_4to25px"],
        "target_nearest_negative_satellite_radius_px":tb["nearest_negative_satellite_radius_px"],
        "science_candidate30_radius_from_target_px":sci_radius,
        "science_candidate30_snr":sci_snr,
        "bright_control_count_excluding_target":len(bctrl),
        "bright_positive_native_distance_p95_px":quant(posd,.95),
        "bright_negative_satellite_count_median":quant(negcnt,.50),
        "bright_negative_satellite_count_p95":quant(negcnt,.95),
        "bright_nearest_negative_radius_p05_px":quant(negrad,.05),
        "bright_nearest_negative_radius_median_px":quant(negrad,.50),
        "bright_nearest_negative_radius_p95_px":quant(negrad,.95),
        "bright_controls_nearest_negative_within3px_of_science_radius":similar_bright,
    }

    target_positive_native_compatible=bool(
        tb["nearest_positive_native_distance_px"] is not None
        and bright_summary["bright_positive_native_distance_p95_px"] is not None
        and tb["nearest_positive_native_distance_px"] <=
            max(bright_summary["bright_positive_native_distance_p95_px"],4.0)
    )
    target_has_satellite_field=tb["negative_satellite_count_4to25px"]>=1
    science_radius_bright_compatible=bool(
        sci_radius is not None
        and bright_summary["bright_nearest_negative_radius_p05_px"] is not None
        and bright_summary["bright_nearest_negative_radius_p95_px"] is not None
        and bright_summary["bright_nearest_negative_radius_p05_px"] <= sci_radius <=
            bright_summary["bright_nearest_negative_radius_p95_px"]
    )

    if (
        len(bctrl)>=MIN_BRIGHT_CONTROLS
        and target_positive_native_compatible
        and target_has_satellite_field
        and science_radius_bright_compatible
    ):
        adj30="BRIGHT_GAIA_STAR_NEGATIVE_SATELLITE_MECHANISM_SUPPORTED"
    elif target_has_satellite_field and science_radius_bright_compatible:
        adj30="BRIGHT_STAR_SATELLITE_GEOMETRY_SUPPORTED;_POSITIVE_CORE_ATTRIBUTION_STILL_WEAK"
    else:
        adj30="BRIGHT_STAR_MECHANISM_UNRESOLVED"

    print("BRANCH #30 — bright-star / saturation-aware controls")
    print(
        f"  target Gaia={target_sid} G={tb['g_mag']:.2f} "
        f"raw centerZ={tb['raw_gaussian_center_z']:.2f} "
        f"+peakZ={tb['raw_positive_peak_z_r7']:.2f}"
    )
    print(
        f"  target nearest +native="
        f"{tb['nearest_positive_native_distance_px']}px "
        f"negative satellites={tb['negative_satellite_count_4to25px']}"
    )
    print(
        f"  science #30 radius={sci_radius:.2f}px; "
        f"bright controls={len(bctrl)} "
        f"nearest-neg radius p05/med/p95="
        f"{bright_summary['bright_nearest_negative_radius_p05_px']}/"
        f"{bright_summary['bright_nearest_negative_radius_median_px']}/"
        f"{bright_summary['bright_nearest_negative_radius_p95_px']}"
    )
    print(f"  => {adj30}\n")

    summary_rows=[
        {
            "strict_rank":24,
            "branch":"PHYSICAL_EDGE_BIPOLAR_STRUCTURE",
            "adjudication":adj24,
            **edge_summary,
        },
        {
            "strict_rank":30,
            "branch":"BRIGHT_STAR_SATELLITE",
            "adjudication":adj30,
            **bright_summary,
        },
    ]

    write_csv(OUT_CSV,summary_rows,sorted({k for r in summary_rows for k in r}))
    write_csv(OUT_EDGE,edge_controls,sorted({k for r in edge_controls for k in r}))
    write_csv(OUT_BRIGHT,bright_rows,sorted({k for r in bright_rows for k in r}))

    payload={
        "stage":"ORDER01_ACTIVE24_30_FOCUSED_POSS_MECHANISM_V028AC",
        "active_unresolved_input":ACTIVE,
        "guards":{
            "network_access":False,
            "science_pixels_read":True,
            "transient_detector_rerun":False,
            "transient_detector_parameters_changed":False,
            "candidate_state_mutation":False,
            "candidate_promotion":False,
            "candidate_deletion":False,
            "weighted_candidate_score":False,
        },
        "plate_bounds":{
            "xmin":xmin,"xmax_exclusive":xmax,
            "ymin":ymin,"ymax_exclusive":ymax,
        },
        "candidate24":{**edge_summary,"adjudication":adj24},
        "candidate30":{**bright_summary,"adjudication":adj30},
        "interpretive_boundary":(
            "#24 is tested against raw-image controls matched to its physical "
            "plate-edge geometry and against the frequency of nearby opposite-"
            "polarity native detector pairs. #30 is tested against bright Gaia "
            "stars so that saturation/extended-image behaviour is not judged "
            "using the generic >=3 sigma centred-star rule. These are mechanism "
            "diagnostics only. No active candidate state is changed."
        )
    }
    write_json(OUT_JSON,payload)

    md=[
        "# ORDER 01 — Focused Final POSS Mechanism Audit for Active #24/#30 v028ac","",
        "## Guard state","",
        "- No network access.",
        "- Science pixels were read for edge and bright-star physical measurements.",
        "- The frozen transient detector was not rerun.",
        "- No candidate state was changed.","",
        "## #24 — physical edge / bipolar structure","",
        f"- Physical edge: **{edge_name}**, distance **{edge_distance:.1f} px**.",
        f"- Edge-matched raw controls: **{len(edge_controls)}**.",
        f"- Science r=7 signed aperture: **{science24['ap7_signed_z']:+.3f} sigma**.",
        f"- Nearest positive native detection: **{b24['nearest_positive_distance_px']:.2f} px**.",
        f"- Edge-band negative detections with positive partner <=6 px: "
        f"**{edge_close}/{len(edge_band)}**.",
        f"- Adjudication: `{adj24}`.","",
        "## #30 — bright-star / saturation-aware satellite","",
        f"- Identified Gaia neighbour: `{target_sid}`, G **{tb['g_mag']:.2f}**.",
        f"- Raw centre/positive-peak Z at Gaia position: "
        f"**{tb['raw_gaussian_center_z']:.2f}/{tb['raw_positive_peak_z_r7']:.2f}**.",
        f"- Nearest positive native detection: "
        f"**{tb['nearest_positive_native_distance_px']} px**.",
        f"- Negative native satellites 4–25 px around target: "
        f"**{tb['negative_satellite_count_4to25px']}**.",
        f"- #30 science radius from target: **{sci_radius:.2f} px**.",
        f"- Bright controls excluding target: **{len(bctrl)}**.",
        f"- Adjudication: `{adj30}`.","",
        "## Interpretation boundary","",
        payload["interpretive_boundary"]
    ]
    OUT_MD.write_text("\n".join(md),encoding="utf-8")

    print("Outputs:")
    print(f"  {OUT_JSON}")
    print(f"  {OUT_CSV}")
    print(f"  {OUT_EDGE}")
    print(f"  {OUT_BRIGHT}")
    print(f"  {OUT_MD}")
    print()
    print("NO network query was made.")
    print("SCIENCE PIXELS WERE READ.")
    print("Transient detector was NOT rerun.")
    print("No candidate was promoted or deleted.")
    return 0


if __name__=="__main__":
    raise SystemExit(main())
