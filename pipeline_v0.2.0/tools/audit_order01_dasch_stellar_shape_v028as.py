#!/usr/bin/env python3
"""
ORDER 01 — DASCH amplitude-normalized stellar-shape audit v028as

Purpose
-------
v028ar-r1 established that all six preserved DASCH endpoints are centered,
positive features in the same raw-pixel polarity as official same-plate stars.

v028as asks the stricter question:
    After removing overall signal amplitude, do the six science features occupy
    the same SHAPE space as official DR7 stellar-image controls?

This stage reads only the previously measured v028ar-r1 JSON. It does not read
science pixels again.

Method
------
For each control/science object derive amplitude-normalized shape features:
  - centroid offset
  - second-moment radius
  - quadrant imbalance
  - aperture concentration ap3/ap7
  - aperture concentration ap5/ap7
  - normalized radial-profile bins 0-1.5, 1.5-3, 3-5, 5-7 px

Feature dimensions are robustly standardized from official controls only.
A leave-one-out nearest-neighbour distance distribution is computed for the
official controls. Each science feature's nearest-control shape distance is then
placed in that empirical distribution.

Separately, science amplitude is placed in the official-control ap5 distribution
so that "stellar shape but brighter/fainter than controls" is not confused with
a shape anomaly.

This is descriptive empirical morphology, not an astrophysical p-value.

NO network access.
SCIENCE PIXELS ARE NOT READ in this stage (prior v028ar-r1 metrics are reused).
Frozen transient detector is NOT rerun.
No endpoint state mutation.
"""

from __future__ import annotations

import csv
import json
import math
from pathlib import Path

import numpy as np

ROOT = Path.cwd()
BASE = ROOT / "results" / "order01_native_full_v028"

CLOSURE = BASE / "order01_candidate24_final_disposition_and_closure_v028ag.json"
MORPH = BASE / "order01_dasch_physical_morphology_v028ar_r1.json"

OUT_JSON = BASE / "order01_dasch_stellar_shape_v028as.json"
OUT_CSV = BASE / "order01_dasch_stellar_shape_summary_v028as.csv"
OUT_NEAREST = BASE / "order01_dasch_stellar_shape_nearest_controls_v028as.csv"
OUT_MD = BASE / "ORDER01_DASCH_STELLAR_SHAPE_V028AS.md"

RANKS = [10,24,25,26,29,30]
K_NEAREST = 5

FEATURES = [
    "centroid_offset_pix",
    "moment_radius_pix",
    "quadrant_imbalance",
    "concentration_ap3_ap7",
    "concentration_ap5_ap7",
    "radial0_norm",
    "radial1_norm",
    "radial2_norm",
    "radial3_norm",
]


def write_json(path,obj):
    tmp=path.with_suffix(path.suffix+".tmp")
    tmp.write_text(json.dumps(obj,indent=2,sort_keys=True,default=str)+"\n",
                   encoding="utf-8")
    tmp.replace(path)


def write_csv(path,rows,fields):
    tmp=path.with_suffix(path.suffix+".tmp")
    with tmp.open("w",encoding="utf-8",newline="") as fh:
        w=csv.DictWriter(fh,fieldnames=fields,extrasaction="ignore")
        w.writeheader(); w.writerows(rows)
    tmp.replace(path)


def finite(v):
    try:
        x=float(v)
        return x if math.isfinite(x) else None
    except Exception:
        return None


def derived(r):
    ap3=finite(r.get("ap3_signed_zsum"))
    ap5=finite(r.get("ap5_signed_zsum"))
    ap7=finite(r.get("ap7_signed_zsum"))

    radial=[
        finite(r.get("radial_0_1.5_signed_zmean")),
        finite(r.get("radial_1.5_3_signed_zmean")),
        finite(r.get("radial_3_5_signed_zmean")),
        finite(r.get("radial_5_7_signed_zmean")),
    ]

    # Normalize radial profile by L1 absolute amplitude, preserving sign.
    if any(x is None for x in radial):
        rn=[None]*4
    else:
        den=sum(abs(x) for x in radial)
        rn=[x/den for x in radial] if den>0 else [None]*4

    return {
        "centroid_offset_pix":finite(r.get("centroid_offset_pix")),
        "moment_radius_pix":finite(r.get("moment_radius_pix")),
        "quadrant_imbalance":finite(r.get("quadrant_imbalance")),
        "concentration_ap3_ap7":
            (ap3/ap7 if ap3 is not None and ap7 not in (None,0) else None),
        "concentration_ap5_ap7":
            (ap5/ap7 if ap5 is not None and ap7 not in (None,0) else None),
        "radial0_norm":rn[0],
        "radial1_norm":rn[1],
        "radial2_norm":rn[2],
        "radial3_norm":rn[3],
        "amplitude_ap5":ap5,
        "center3":finite(r.get("center3_signed_zmean")),
        "core_peak":finite(r.get("core_signed_peak_z")),
    }


def robust_center_scale(control_vectors):
    a=np.asarray(control_vectors,float)
    med=np.median(a,axis=0)
    mad=np.median(np.abs(a-med),axis=0)
    scale=1.4826*mad
    std=np.std(a,axis=0,ddof=1)
    scale=np.where((~np.isfinite(scale))|(scale<=1e-9),std,scale)
    scale=np.where((~np.isfinite(scale))|(scale<=1e-9),1.0,scale)
    return med,scale


def distance(z1,z2):
    d=np.asarray(z1)-np.asarray(z2)
    return float(np.sqrt(np.mean(d*d)))


def empirical_percentile(vals,x):
    a=np.asarray([v for v in vals if v is not None and math.isfinite(v)],float)
    if a.size==0 or x is None:
        return None
    return float((np.sum(a<x)+0.5*np.sum(a==x))/a.size)


def main():
    print("="*128)
    print("ORDER 01 — DASCH AMPLITUDE-NORMALIZED STELLAR-SHAPE AUDIT v028as")
    print("="*128)
    print("NO NETWORK ACCESS.")
    print("SCIENCE PIXELS ARE NOT READ IN THIS STAGE; v028ar-r1 METRICS ARE REUSED.")
    print("Frozen transient detector is NOT rerun.\n")

    for p in (CLOSURE,MORPH):
        if not p.is_file():
            print(f"FAIL missing input: {p}")
            return 2

    closure=json.loads(CLOSURE.read_text(encoding="utf-8"))
    if closure.get("new_active_unresolved_two_observatory_set")!=[]:
        raise RuntimeError("Order-01 closure guard mismatch")

    obj=json.loads(MORPH.read_text(encoding="utf-8"))
    if obj.get("guards",{}).get("science_pixels_read") is not True:
        raise RuntimeError("v028ar-r1 science-pixel guard is not TRUE")
    if obj.get("guards",{}).get("candidate_state_mutation") is not False:
        raise RuntimeError("v028ar-r1 mutation guard mismatch")

    controls=obj.get("official_controls",[])
    science=obj.get("science",[])
    if len(controls)<8:
        raise RuntimeError(f"too few controls: {len(controls)}")
    if sorted(int(r["strict_rank"]) for r in science)!=RANKS:
        raise RuntimeError("science rank guard mismatch")

    cder=[derived(r) for r in controls]
    sder={int(r["strict_rank"]):derived(r) for r in science}

    # Require complete feature vector.
    good_controls=[]
    good_cder=[]
    for r,d in zip(controls,cder):
        if all(d[k] is not None and math.isfinite(d[k]) for k in FEATURES):
            good_controls.append(r)
            good_cder.append(d)
    if len(good_controls)<8:
        raise RuntimeError(f"too few complete controls: {len(good_controls)}")

    X=np.array([[d[k] for k in FEATURES] for d in good_cder],float)
    med,scale=robust_center_scale(X)
    Z=(X-med)/scale

    # Leave-one-out control NN distances.
    loo_nn=[]
    for j in range(len(Z)):
        ds=[distance(Z[j],Z[k]) for k in range(len(Z)) if k!=j]
        loo_nn.append(min(ds))

    loo_p50=float(np.median(loo_nn))
    loo_p90=float(np.quantile(loo_nn,0.90))
    loo_p95=float(np.quantile(loo_nn,0.95))
    loo_max=float(np.max(loo_nn))

    ctrl_amp=[d["amplitude_ap5"] for d in good_cder if d["amplitude_ap5"] is not None]
    amp_min=float(np.min(ctrl_amp))
    amp_max=float(np.max(ctrl_amp))

    summaries=[]
    nearest_rows=[]

    print(f"Complete official shape controls: {len(good_controls)}")
    print(
        f"Official leave-one-out nearest-shape distance: "
        f"median={loo_p50:.3f} p90={loo_p90:.3f} p95={loo_p95:.3f} max={loo_max:.3f}"
    )
    print(f"Official ap5 amplitude range: {amp_min:.3f} .. {amp_max:.3f}\n")

    for rank in RANKS:
        d=sder[rank]
        if not all(d[k] is not None and math.isfinite(d[k]) for k in FEATURES):
            raise RuntimeError(f"#{rank}: incomplete science shape vector")

        x=np.array([d[k] for k in FEATURES],float)
        z=(x-med)/scale

        ds=[distance(z,Z[k]) for k in range(len(Z))]
        order=np.argsort(ds)
        nn=float(ds[int(order[0])])
        nn_pct=empirical_percentile(loo_nn,nn)

        amp=d["amplitude_ap5"]
        amp_pct=empirical_percentile(ctrl_amp,amp)
        outside_amp = amp < amp_min or amp > amp_max
        amp_side = (
            "ABOVE_CONTROL_RANGE" if amp>amp_max else
            "BELOW_CONTROL_RANGE" if amp<amp_min else
            "WITHIN_CONTROL_RANGE"
        )

        if nn <= loo_p95:
            shape_class="CONSISTENT_WITH_OFFICIAL_SOURCE_SHAPE_CLOUD"
        elif nn <= loo_max:
            shape_class="MARGINAL_SHAPE_OUTLIER_VS_OFFICIAL_CONTROLS"
        else:
            shape_class="STRONG_SHAPE_OUTLIER_VS_OFFICIAL_CONTROLS"

        rec={
            "strict_rank":rank,
            "nearest_shape_distance":nn,
            "nearest_shape_distance_vs_control_loo_percentile":nn_pct,
            "control_loo_nn_median":loo_p50,
            "control_loo_nn_p90":loo_p90,
            "control_loo_nn_p95":loo_p95,
            "control_loo_nn_max":loo_max,
            "shape_classification":shape_class,
            "ap5_amplitude":amp,
            "ap5_control_percentile":amp_pct,
            "ap5_control_min":amp_min,
            "ap5_control_max":amp_max,
            "amplitude_support_status":amp_side,
            "amplitude_extrapolation":outside_amp,
            "center3":d["center3"],
            "core_peak":d["core_peak"],
        }
        for k in FEATURES:
            rec[k]=d[k]
        summaries.append(rec)

        print(
            f"#{rank}: shapeNN={nn:.3f} "
            f"(control-LOO percentile={nn_pct:.3f}) "
            f"=> {shape_class}"
        )
        print(
            f"    ap5={amp:.3f} controlPct={amp_pct:.3f} "
            f"{amp_side}"
        )

        for position,idx in enumerate(order[:K_NEAREST],start=1):
            cr=good_controls[int(idx)]
            cd=good_cder[int(idx)]
            nearest_rows.append({
                "strict_rank":rank,
                "nearest_control_rank":position,
                "shape_distance":float(ds[int(idx)]),
                "control_ref_number":cr.get("ref_number"),
                "control_ra_deg":cr.get("ra_deg"),
                "control_dec_deg":cr.get("dec_deg"),
                "control_tile_id":cr.get("tile_id"),
                "control_ap5":cd["amplitude_ap5"],
                "control_center3":cd["center3"],
                "control_centroid_offset_pix":cd["centroid_offset_pix"],
                "control_moment_radius_pix":cd["moment_radius_pix"],
                "control_quadrant_imbalance":cd["quadrant_imbalance"],
                "control_fwhm_pix_official":cr.get("fwhm_pix_official"),
                "control_ellipticity_official":cr.get("ellipticity_official"),
                "control_aflags":cr.get("aflags"),
                "control_bflags":cr.get("bflags"),
            })

    payload={
        "stage":"ORDER01_DASCH_AMPLITUDE_NORMALIZED_STELLAR_SHAPE_V028AS",
        "plate":PLATE if "PLATE" in globals() else "ai43437",
        "ranks":RANKS,
        "guards":{
            "network_access":False,
            "science_pixels_read":False,
            "science_pixel_metrics_reused_from":"v028ar-r1",
            "source_v028ar_science_pixels_read":True,
            "transient_detector_rerun":False,
            "candidate_state_mutation":False,
            "control_only_feature_scaling":True,
            "amplitude_removed_from_shape_distance":True,
        },
        "feature_names":FEATURES,
        "complete_official_control_count":len(good_controls),
        "control_loo_nearest_distance":{
            "median":loo_p50,"p90":loo_p90,"p95":loo_p95,"max":loo_max
        },
        "control_ap5_range":{"min":amp_min,"max":amp_max},
        "summaries":summaries,
        "nearest_controls":nearest_rows,
        "interpretive_boundary":(
            "v028as evaluates whether each science feature has an amplitude-normalized "
            "raw morphology resembling official same-plate DR7 stellar images. The "
            "nearest-neighbour percentile is a descriptive empirical control statistic, "
            "not an astrophysical p-value. A stellar-like single-plate image can still "
            "be a photographic defect, blend, catalogue-unresolved source, or other "
            "non-transient phenomenon."
        )
    }

    write_json(OUT_JSON,payload)
    write_csv(OUT_CSV,summaries,list(summaries[0]))
    write_csv(OUT_NEAREST,nearest_rows,list(nearest_rows[0]))

    md=[
        "# ORDER 01 — DASCH Amplitude-Normalized Stellar Shape v028as","",
        "## Guard state","",
        "- No network access.",
        "- Science pixels were **not reread**; v028ar-r1 metrics were reused.",
        "- The frozen detector was not rerun.",
        "- No endpoint state was changed.",
        "- Overall signal amplitude is excluded from the morphology distance.",
        "- All feature scaling is learned from official same-plate controls only.","",
        f"Complete official controls: **{len(good_controls)}**.",
        f"Control leave-one-out shape NN p95: **{loo_p95:.3f}**.","",
        "## Science shape results","",
        "| rank | shape NN | control-LOO percentile | shape classification | ap5 amplitude status |",
        "|---:|---:|---:|---|---|"
    ]
    for r in summaries:
        md.append(
            f"| #{r['strict_rank']} | {r['nearest_shape_distance']:.3f} | "
            f"{r['nearest_shape_distance_vs_control_loo_percentile']:.3f} | "
            f"{r['shape_classification']} | {r['amplitude_support_status']} |"
        )
    md += ["","## Interpretation boundary","",payload["interpretive_boundary"]]
    OUT_MD.write_text("\n".join(md),encoding="utf-8")

    print("\nOutputs:")
    print(f"  {OUT_JSON}")
    print(f"  {OUT_CSV}")
    print(f"  {OUT_NEAREST}")
    print(f"  {OUT_MD}")
    print()
    print("NO network query was made.")
    print("SCIENCE PIXELS WERE NOT READ IN THIS STAGE.")
    print("Transient detector was NOT rerun.")
    print("No endpoint state was changed.")
    return 0


if __name__=="__main__":
    PLATE="ai43437"
    raise SystemExit(main())
