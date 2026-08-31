#!/usr/bin/env python3
"""
ORDER 01 — candidate #24 joint bipolar-cluster / raw-pair audit v028af

Purpose
-------
v028ae corrected #24's tile identity and established:
  - frozen POSS science detection is negative polarity, SNR ~4.60;
  - nearest positive-polarity native detection is 4.0 px away;
  - #24 has 8 other negative detections within 15 px;
  - adjacent opposite-polarity pairs recur in matched LEFT-edge controls.

Because close pairing alone is not rare (~20-25%), this stage evaluates the
JOINT geometry:
  A. pair distance <= the science pair distance AND
     local negative clustering >= the science clustering;
  B. the same joint test using <=4.5 px as the bipolar-pair tolerance;
  C. optional third condition: positive partner SNR >= the science partner SNR.

It also reads the raw POSS pixels once to measure #24 and its exact positive
partner on one common local background model, establishing whether the two
native detections are physically opposite-signed lobes of the same local
image structure.

Empirical control tails are descriptive local diagnostics, not astrophysical
p-values.

No network access.
SCIENCE PIXELS ARE READ.
Frozen transient detector is NOT rerun.
No candidate state mutation.
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
V028AD = BASE / "order01_candidate30_disposition_freeze_v028ad.json"
V028AE = BASE / "order01_candidate24_left_edge_bipolar_audit_v028ae.json"
V028AE_CTRL = BASE / "order01_candidate24_left_edge_bipolar_controls_v028ae.csv"
POSS = BASE / "order01_poss_native_candidates.csv"

OUT_JSON = BASE / "order01_candidate24_joint_bipolar_cluster_rawpair_v028af.json"
OUT_CSV = BASE / "order01_candidate24_joint_bipolar_cluster_rawpair_v028af.csv"
OUT_MD = BASE / "ORDER01_CANDIDATE24_JOINT_BIPOLAR_CLUSTER_RAWPAIR_V028AF.md"

ACTIVE = [24]
PAIR_TOL_PX = 4.5
RAW_STAMP_RADIUS = 30
RAW_BG_INNER = 12.0
RAW_BG_OUTER = 24.0
RAW_GAUSS_SIGMA = 2.5


def load_v028v():
    spec=importlib.util.spec_from_file_location("v028vmod",V028V_SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import {V028V_SCRIPT}")
    mod=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def read_csv(p):
    with p.open("r",encoding="utf-8-sig",newline="") as fh:
        return list(csv.DictReader(fh))


def write_csv(p,rows,fields):
    tmp=p.with_suffix(p.suffix+".tmp")
    with tmp.open("w",encoding="utf-8",newline="") as fh:
        w=csv.DictWriter(fh,fieldnames=fields,extrasaction="ignore")
        w.writeheader();w.writerows(rows)
    tmp.replace(p)


def write_json(p,obj):
    tmp=p.with_suffix(p.suffix+".tmp")
    tmp.write_text(json.dumps(obj,indent=2,sort_keys=True,default=str)+"\n",
                   encoding="utf-8")
    tmp.replace(p)


def f(v,default=None):
    try:
        if v is None or str(v).strip()=="":return default
        x=float(str(v).strip())
        return x if math.isfinite(x) else default
    except Exception:return default


def i(v,default=None):
    try:
        if v is None or str(v).strip()=="":return default
        return int(float(str(v).strip()))
    except Exception:return default


def guarded_fraction(count,n):
    return None if n==0 else (1+count)/(n+1)


def summarize_pool(rows,science_pair,science_cluster,science_partner_snr):
    n=len(rows)
    exact=[
        r for r in rows
        if f(r.get("nearest_positive_distance_px")) <= science_pair
        and i(r.get("other_negative_within15px")) >= science_cluster
    ]
    tol=[
        r for r in rows
        if f(r.get("nearest_positive_distance_px")) <= PAIR_TOL_PX
        and i(r.get("other_negative_within15px")) >= science_cluster
    ]
    triple=[
        r for r in rows
        if f(r.get("nearest_positive_distance_px")) <= PAIR_TOL_PX
        and i(r.get("other_negative_within15px")) >= science_cluster
        and f(r.get("nearest_positive_snr")) >= science_partner_snr
    ]
    return {
        "count":n,
        "joint_exact_count":len(exact),
        "joint_exact_guarded_tail":guarded_fraction(len(exact),n),
        "joint_4p5_count":len(tol),
        "joint_4p5_guarded_tail":guarded_fraction(len(tol),n),
        "joint_4p5_partner_snr_count":len(triple),
        "joint_4p5_partner_snr_guarded_tail":guarded_fraction(len(triple),n),
    }


def common_raw_pair(v,meta,negx,negy,posx,posy):
    arr=v.load_arr(meta)
    ex0,ex1,ey0,ey1=meta["extended"]

    mx=.5*(negx+posx); my=.5*(negy+posy)
    px=mx-ex0; py=my-ey0
    ix=int(round(px));iy=int(round(py))
    R=RAW_STAMP_RADIUS
    x0=ix-R;x1=ix+R+1;y0=iy-R;y1=iy+R+1
    if x0<0 or y0<0 or x1>arr.shape[1] or y1>arr.shape[0]:
        raise RuntimeError("common raw pair stamp outside cached tile")

    cut=np.asarray(arr[y0:y1,x0:x1],float)
    yy,xx=np.indices(cut.shape)
    cx=px-x0;cy=py-y0
    rr=np.hypot(xx-cx,yy-cy)
    bg=(rr>=RAW_BG_INNER)&(rr<=RAW_BG_OUTER)
    plane,resid,sigma,beta=v.robust_plane(cut,xx,yy,bg)
    sm=gaussian_filter(resid,RAW_GAUSS_SIGMA,mode="nearest")/sigma

    def sample(gx,gy):
        lx=gx-ex0-x0
        ly=gy-ey0-y0
        jx=int(round(lx));jy=int(round(ly))
        return float(sm[jy,jx]),float(resid[jy,jx]/sigma),jx,jy

    nz,nraw,nix,niy=sample(negx,negy)
    pz,praw,pix,piy=sample(posx,posy)

    # Sample the line joining the two native detections.
    ts=np.linspace(0,1,17)
    line=[]
    for t in ts:
        gx=negx+t*(posx-negx);gy=negy+t*(posy-negy)
        lx=gx-ex0-x0;ly=gy-ey0-y0
        # nearest pixel is sufficient for a descriptive sign profile.
        jx=int(round(lx));jy=int(round(ly))
        line.append(float(sm[jy,jx]))

    return {
        "common_background_sigma":float(sigma),
        "negative_native_smoothed_z":nz,
        "negative_native_raw_residual_z":nraw,
        "positive_native_smoothed_z":pz,
        "positive_native_raw_residual_z":praw,
        "smoothed_z_difference_positive_minus_negative":pz-nz,
        "line_z_min":float(min(line)),
        "line_z_max":float(max(line)),
        "line_z_values":[float(x) for x in line],
        "opposite_signed_at_native_positions":bool(nz<0 and pz>0),
    }


def main():
    print("="*128)
    print("ORDER 01 — CANDIDATE #24 JOINT BIPOLAR-CLUSTER / RAW-PAIR AUDIT v028af")
    print("="*128)
    print("NO NETWORK ACCESS.")
    print("SCIENCE PIXELS ARE READ.")
    print("Frozen transient detector is NOT rerun.\n")

    for p in (V028V_SCRIPT,V028AD,V028AE,V028AE_CTRL,POSS):
        if not p.is_file():
            print(f"FAIL missing input: {p}");return 2

    ad=json.loads(V028AD.read_text(encoding="utf-8"))
    ae=json.loads(V028AE.read_text(encoding="utf-8"))
    if ad.get("new_active_unresolved_two_observatory_set")!=ACTIVE:
        raise RuntimeError("v028ad active-set guard mismatch")
    if ae.get("active_unresolved_input")!=ACTIVE:
        raise RuntimeError("v028ae active-set guard mismatch")
    if ae.get("adjudication")!="LEFT_EDGE_BIPOLAR_NATIVE_DETECTOR_MECHANISM_SUPPORTED":
        raise RuntimeError("v028ae mechanism guard mismatch")

    v=load_v028v()
    controls=read_csv(V028AE_CTRL)
    native=read_csv(POSS)

    sci=ae["science"]
    stid=str(sci["tile_id"]);sidx=i(sci["candidate_index"])
    pidx=i(sci["nearest_positive_candidate_index"])
    ptid=str(sci["nearest_positive_tile_id"])
    if ptid!=stid:
        raise RuntimeError("science and positive partner unexpectedly on different tiles")

    sn=[r for r in native if str(r.get("tile_id",""))==stid and i(r.get("candidate_index"))==sidx]
    pn=[r for r in native if str(r.get("tile_id",""))==ptid and i(r.get("candidate_index"))==pidx]
    if len(sn)!=1 or len(pn)!=1:
        raise RuntimeError("tile-aware science/partner resolution failed")
    sn=sn[0];pn=pn[0]

    sx=f(sn["global_x"]);sy=f(sn["global_y"])
    px=f(pn["global_x"]);py=f(pn["global_y"])
    pair=math.hypot(px-sx,py-sy)
    if abs(pair-f(sci["nearest_positive_distance_px"]))>1e-9:
        raise RuntimeError("pair-distance guard mismatch")

    science_cluster=i(sci["other_negative_within15px"])
    science_partner_snr=f(sci["nearest_positive_snr"])

    poolA=controls
    poolB=[r for r in controls if str(r.get("in_snr_matched_pool")).lower()=="true"]
    poolC=[r for r in controls if str(r.get("in_local_y_pool")).lower()=="true"]

    summaries={
        "same_edge":summarize_pool(poolA,pair,science_cluster,science_partner_snr),
        "same_edge_snr_matched":summarize_pool(poolB,pair,science_cluster,science_partner_snr),
        "same_edge_snr_and_local_y":summarize_pool(poolC,pair,science_cluster,science_partner_snr),
    }

    inv=v.inventory()
    if stid not in inv:
        raise RuntimeError(f"science tile not in raw inventory: {stid}")
    raw=common_raw_pair(v,inv[stid],sx,sy,px,py)

    print("Science #24 / partner:")
    print(f"  negative native: {stid}::{sidx} polarity={i(sn['polarity']):+d} SNR={f(sn['snr']):.3f}")
    print(f"  positive native: {ptid}::{pidx} polarity={i(pn['polarity']):+d} SNR={f(pn['snr']):.3f}")
    print(f"  separation={pair:.3f}px; other negative within15px={science_cluster}")
    print(
        f"  common raw background: negativeZ={raw['negative_native_smoothed_z']:+.3f} "
        f"positiveZ={raw['positive_native_smoothed_z']:+.3f} "
        f"oppositeSigned={raw['opposite_signed_at_native_positions']}"
    )
    print()

    for name,s in summaries.items():
        print(
            f"{name}: N={s['count']} "
            f"joint(pair<=4.0,cluster>=8)={s['joint_exact_count']} "
            f"tail={s['joint_exact_guarded_tail']} "
            f"joint(pair<=4.5,cluster>=8)={s['joint_4p5_count']} "
            f"tail={s['joint_4p5_guarded_tail']} "
            f"+partnerSNR>={science_partner_snr:.2f}: "
            f"{s['joint_4p5_partner_snr_count']} "
            f"tail={s['joint_4p5_partner_snr_guarded_tail']}"
        )

    # Conservative mechanism adjudication. We do NOT require rarity <0.05:
    # the question is recurrence of the same bipolar+cluster morphology, not
    # whether the science event is statistically exceptional.
    sb=summaries["same_edge_snr_matched"]
    sc=summaries["same_edge_snr_and_local_y"]
    if (
        raw["opposite_signed_at_native_positions"]
        and sb["joint_4p5_count"]>=10
        and sc["joint_4p5_count"]>=3
    ):
        adjudication="BIPOLAR_CLUSTER_MECHANISM_REPRODUCED_IN_MATCHED_CONTROLS"
    elif raw["opposite_signed_at_native_positions"]:
        adjudication="RAW_BIPOLAR_PAIR_CONFIRMED;_JOINT_CONTROL_RECURRENCE_INSUFFICIENT"
    else:
        adjudication="BIPOLAR_MECHANISM_NOT_CONFIRMED_IN_RAW_PAIR"

    print(f"\nADJUDICATION: {adjudication}")

    payload={
        "stage":"ORDER01_CANDIDATE24_JOINT_BIPOLAR_CLUSTER_RAWPAIR_V028AF",
        "active_unresolved_input":[24],
        "guards":{
            "network_access":False,
            "science_pixels_read":True,
            "transient_detector_rerun":False,
            "transient_detector_parameters_changed":False,
            "candidate_state_mutation":False,
            "candidate_promotion":False,
            "candidate_deletion":False,
            "tile_aware_science_identity":True,
        },
        "science":{
            "strict_rank":24,
            "negative_tile_id":stid,
            "negative_candidate_index":sidx,
            "negative_snr":f(sn["snr"]),
            "positive_tile_id":ptid,
            "positive_candidate_index":pidx,
            "positive_snr":f(pn["snr"]),
            "pair_separation_px":pair,
            "other_negative_within15px":science_cluster,
        },
        "joint_control_summaries":summaries,
        "raw_pair":raw,
        "adjudication":adjudication,
        "interpretive_boundary":(
            "The empirical joint tails quantify how often matched frozen native "
            "detections reproduce #24's close opposite-polarity pairing plus dense "
            "negative clustering. They are not astrophysical p-values. Raw pixels "
            "are read only to verify that the exact frozen negative/positive pair "
            "are opposite-signed lobes on one common local background. No candidate "
            "state changes."
        )
    }
    write_json(OUT_JSON,payload)

    row={
        "strict_rank":24,
        "adjudication":adjudication,
        "pair_separation_px":pair,
        "science_negative_snr":f(sn["snr"]),
        "science_positive_partner_snr":f(pn["snr"]),
        "other_negative_within15px":science_cluster,
        "raw_negative_smoothed_z":raw["negative_native_smoothed_z"],
        "raw_positive_smoothed_z":raw["positive_native_smoothed_z"],
        "raw_opposite_signed":raw["opposite_signed_at_native_positions"],
        "snr_matched_joint_4p5_count":sb["joint_4p5_count"],
        "snr_matched_joint_4p5_tail":sb["joint_4p5_guarded_tail"],
        "local_y_joint_4p5_count":sc["joint_4p5_count"],
        "local_y_joint_4p5_tail":sc["joint_4p5_guarded_tail"],
        "snr_matched_joint_partner_snr_count":sb["joint_4p5_partner_snr_count"],
        "snr_matched_joint_partner_snr_tail":sb["joint_4p5_partner_snr_guarded_tail"],
        "local_y_joint_partner_snr_count":sc["joint_4p5_partner_snr_count"],
        "local_y_joint_partner_snr_tail":sc["joint_4p5_partner_snr_guarded_tail"],
    }
    write_csv(OUT_CSV,[row],list(row))

    md=[
        "# ORDER 01 — Candidate #24 Joint Bipolar-Cluster / Raw-Pair Audit v028af","",
        "## Guard state","",
        "- No network access.",
        "- Science pixels were read.",
        "- The frozen transient detector was not rerun.",
        "- Tile-aware science/partner identity was enforced.",
        "- No candidate state was changed.","",
        "## Science pair","",
        f"- Negative native: `{stid}::{sidx}`, SNR **{f(sn['snr']):.3f}**.",
        f"- Positive native: `{ptid}::{pidx}`, SNR **{f(pn['snr']):.3f}**.",
        f"- Separation: **{pair:.3f} px**.",
        f"- Other negative detections within 15 px: **{science_cluster}**.",
        f"- Common-background smoothed Z at negative/positive positions: "
        f"**{raw['negative_native_smoothed_z']:+.3f} / {raw['positive_native_smoothed_z']:+.3f}**.",
        f"- Opposite-signed raw pair: **{raw['opposite_signed_at_native_positions']}**.","",
        "## Joint controls",""
    ]
    for name in ("same_edge","same_edge_snr_matched","same_edge_snr_and_local_y"):
        s=summaries[name]
        md += [
            f"### {name}",
            f"- N: **{s['count']}**.",
            f"- Pair <=4.0 px AND cluster >=8: **{s['joint_exact_count']}**, "
            f"guarded tail **{s['joint_exact_guarded_tail']}**.",
            f"- Pair <=4.5 px AND cluster >=8: **{s['joint_4p5_count']}**, "
            f"guarded tail **{s['joint_4p5_guarded_tail']}**.",
            f"- Above + partner SNR >= {science_partner_snr:.3f}: "
            f"**{s['joint_4p5_partner_snr_count']}**, "
            f"guarded tail **{s['joint_4p5_partner_snr_guarded_tail']}**.",
            ""
        ]
    md += ["## Adjudication","",f"`{adjudication}`","",
           "## Interpretation boundary","",payload["interpretive_boundary"]]
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
