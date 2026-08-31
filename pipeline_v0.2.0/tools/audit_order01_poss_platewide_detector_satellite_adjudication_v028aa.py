#!/usr/bin/env python3
"""
ORDER 01 — plate-wide POSS detector-satellite mechanism adjudication v028aa

Purpose
-------
v028z established per-rank neighbour-star satellite support for #10/#25 but
left #26 unresolved because its local tile had only one qualifying ordinary-star
control. All six science endpoints, however, share the same physical POSS plate,
pixel scale, frozen detector, and detector parameters.

v028aa therefore pools the already-qualified ordinary-star satellite controls
plate-wide, while enforcing two independence guards:
  1. exclude all six frozen science candidate indices from the control pool;
  2. deduplicate native negative detections by (tile_id, candidate_index), so a
     single detector peak near multiple Gaia stars is counted only once.

No new star selection is performed. No pixels are read. No detector is rerun.

The pooled unique control distribution is used only to test whether a science
candidate's star-relative radius and SNR are characteristic of ordinary
negative detector satellites on this same physical plate.

No network access.
SCIENCE PIXELS ARE NOT READ.
Frozen transient detector is NOT rerun.
No candidate promotion/deletion/state mutation.
"""

from __future__ import annotations

import csv
import json
import math
from pathlib import Path
import numpy as np

ROOT = Path.cwd()
BASE = ROOT / "results" / "order01_native_full_v028"

V028Z_JSON = BASE / "order01_poss_detector_ring_neighbor_mechanism_v028z.json"
V028Z_CTRL = BASE / "order01_poss_detector_ring_control_satellites_v028z.csv"
V028Y_JSON = BASE / "order01_poss_science_centered_counterpart_adjudication_v028y.json"

OUT_JSON = BASE / "order01_poss_platewide_detector_satellite_adjudication_v028aa.json"
OUT_CSV = BASE / "order01_poss_platewide_detector_satellite_adjudication_v028aa.csv"
OUT_CTRL = BASE / "order01_poss_platewide_unique_detector_satellite_controls_v028aa.csv"
OUT_MD = BASE / "ORDER01_POSS_PLATEWIDE_DETECTOR_SATELLITE_ADJUDICATION_V028AA.md"

EXPECTED = [10,24,25,26,29,30]

RADIUS_CENTRAL_LO = 0.05
RADIUS_CENTRAL_HI = 0.95
SNR_CENTRAL_LO = 0.05
SNR_CENTRAL_HI = 0.95
RADIUS_SIMILAR_TOL_PX = 3.0


def read_csv(path):
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def write_csv(path, rows, fields):
    tmp=path.with_suffix(path.suffix+".tmp")
    with tmp.open("w", encoding="utf-8", newline="") as fh:
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


def quant(vals,q):
    a=np.asarray(vals,float)
    return float(np.quantile(a,q))


def percentile(vals,x):
    a=np.asarray(vals,float)
    return float((np.count_nonzero(a<=x)+0.5)/(len(a)+1.0))


def main():
    print("="*128)
    print("ORDER 01 — PLATE-WIDE POSS DETECTOR-SATELLITE MECHANISM ADJUDICATION v028aa")
    print("="*128)
    print("NO NETWORK ACCESS.")
    print("SCIENCE PIXELS ARE NOT READ.")
    print("Frozen transient detector is NOT rerun.\n")

    for p in (V028Z_JSON,V028Z_CTRL,V028Y_JSON):
        if not p.is_file():
            print(f"FAIL missing input: {p}"); return 2

    vz=json.loads(V028Z_JSON.read_text(encoding="utf-8"))
    vy=json.loads(V028Y_JSON.read_text(encoding="utf-8"))
    if vz.get("frozen_active_ranks")!=EXPECTED or vy.get("frozen_active_ranks")!=EXPECTED:
        raise RuntimeError("frozen rank mismatch")
    if vz.get("guards",{}).get("candidate_state_mutation") is not False:
        raise RuntimeError("v028z state guard mismatch")

    zres={int(r["strict_rank"]):r for r in vz["results"]}
    yres={int(r["strict_rank"]):r for r in vy["results"]}
    ctrl=read_csv(V028Z_CTRL)

    science_keys={
        f"{zres[r]['tile_id']}::{int(zres[r]['science_candidate_index'])}"
        for r in EXPECTED
    }

    # Deduplicate negative native detections and exclude all science candidates.
    unique={}
    duplicate_rows=0
    excluded_science_rows=0
    for row in ctrl:
        tid=str(row.get("tile_id",""))
        idx=i(row.get("negative_candidate_index"))
        if idx is None: continue
        key=f"{tid}::{idx}"
        if key in science_keys:
            excluded_science_rows += 1
            continue
        d=f(row.get("negative_candidate_distance_px"))
        snr=f(row.get("negative_candidate_snr"))
        if None in (d,snr): continue

        if key not in unique:
            unique[key]=dict(row)
            unique[key]["control_key"]=key
            unique[key]["association_count"]=1
            unique[key]["minimum_star_distance_px"]=d
        else:
            duplicate_rows += 1
            unique[key]["association_count"] += 1
            if d < float(unique[key]["minimum_star_distance_px"]):
                # Keep the nearest-star association as the representative
                # geometry for this native detector peak.
                assoc=unique[key]["association_count"]
                new=dict(row)
                new["control_key"]=key
                new["association_count"]=assoc
                new["minimum_star_distance_px"]=d
                unique[key]=new

    u=list(unique.values())
    if len(u)<20:
        raise RuntimeError(f"too few unique plate-wide controls: {len(u)}")

    radii=np.asarray([f(r["negative_candidate_distance_px"]) for r in u],float)
    snrs=np.asarray([f(r["negative_candidate_snr"]) for r in u],float)

    stats={
        "unique_negative_control_count":len(u),
        "excluded_science_control_rows":excluded_science_rows,
        "deduplicated_extra_association_rows":duplicate_rows,
        "radius_p05_px":quant(radii,.05),
        "radius_p25_px":quant(radii,.25),
        "radius_median_px":quant(radii,.50),
        "radius_p75_px":quant(radii,.75),
        "radius_p95_px":quant(radii,.95),
        "snr_p05":quant(snrs,.05),
        "snr_p25":quant(snrs,.25),
        "snr_median":quant(snrs,.50),
        "snr_p75":quant(snrs,.75),
        "snr_p95":quant(snrs,.95),
    }

    print("Independent plate-wide ordinary-star negative-satellite controls:")
    print(f"  unique native detections: {stats['unique_negative_control_count']}")
    print(f"  excluded science rows:   {stats['excluded_science_control_rows']}")
    print(f"  duplicate associations removed: {stats['deduplicated_extra_association_rows']}")
    print(
        f"  radius p05/median/p95 = "
        f"{stats['radius_p05_px']:.2f}/{stats['radius_median_px']:.2f}/{stats['radius_p95_px']:.2f} px"
    )
    print(
        f"  SNR    p05/median/p95 = "
        f"{stats['snr_p05']:.2f}/{stats['snr_median']:.2f}/{stats['snr_p95']:.2f}"
    )
    print()

    out=[]
    for rank in EXPECTED:
        z=zres[rank]; y=yres[rank]
        rad=f(z.get("science_to_identified_neighbor_distance_px"))
        ssnr=f(z.get("science_native_snr"))
        spol=i(z.get("science_native_polarity"))
        neigh=str(z.get("identified_neighbor_gaia_source_id") or "")
        yadj=str(y.get("adjudication") or "")
        xpos=str(y.get("v028x_positive_attribution") or "")

        radius_pct=None if rad is None else percentile(radii,rad)
        snr_pct=None if ssnr is None else percentile(snrs,ssnr)
        radius_central=bool(
            rad is not None and
            stats["radius_p05_px"] <= rad <= stats["radius_p95_px"]
        )
        snr_central=bool(
            ssnr is not None and
            stats["snr_p05"] <= ssnr <= stats["snr_p95"]
        )
        similar=0 if rad is None else int(np.count_nonzero(np.abs(radii-rad)<=RADIUS_SIMILAR_TOL_PX))

        has_identified_positive_neighbor=bool(
            neigh and xpos=="DISPLACED_POSITIVE_STRUCTURE_MATCHES_GAIA"
        )
        no_centered_point=(
            "NO_CENTERED_POINT_SOURCE" in yadj
            or "NO_CENTERED_POSITIVE_POINT_SOURCE" in yadj
        )
        per_rank_support=(
            str(z.get("adjudication"))==
            "NEGATIVE_DETECTOR_SATELLITE_AROUND_IDENTIFIED_GAIA_NEIGHBOUR_SUPPORTED"
        )

        platewide_support=bool(
            spol == -1
            and has_identified_positive_neighbor
            and no_centered_point
            and radius_central
            and similar >= 3
        )

        if per_rank_support and platewide_support:
            adj="NEIGHBOUR_STAR_NEGATIVE_SATELLITE_MECHANISM_STRONGLY_SUPPORTED"
        elif platewide_support:
            adj="NEIGHBOUR_STAR_NEGATIVE_SATELLITE_MECHANISM_SUPPORTED_PLATEWIDE"
        elif rank==29 and "CENTERED_NEGATIVE_DEFICIT" in yadj:
            adj="CENTERED_NEGATIVE_DEFICIT_NOT_EXPLAINED_BY_STAR_SATELLITE_MECHANISM"
        elif spol==-1 and neigh and radius_central and not has_identified_positive_neighbor:
            adj="RING_GEOMETRY_COMPATIBLE_BUT_POSITIVE_NEIGHBOUR_ATTRIBUTION_INSUFFICIENT"
        else:
            adj="PLATEWIDE_SATELLITE_MECHANISM_NOT_ESTABLISHED"

        row={
            "strict_rank":rank,
            "science_candidate_index":i(z.get("science_candidate_index")),
            "science_native_polarity":spol,
            "science_native_snr":ssnr,
            "identified_neighbor_gaia_source_id":neigh or None,
            "identified_neighbor_gaia_g_mag":f(z.get("identified_neighbor_gaia_g_mag")),
            "science_to_neighbor_radius_px":rad,
            "science_radius_percentile_platewide":radius_pct,
            "science_snr_percentile_platewide":snr_pct,
            "science_radius_within_platewide_p05_p95":radius_central,
            "science_snr_within_platewide_p05_p95":snr_central,
            "unique_platewide_controls_within_3px_radius":similar,
            "identified_positive_gaia_neighbor":has_identified_positive_neighbor,
            "no_centered_positive_point_source":no_centered_point,
            "per_rank_mechanism_supported_v028z":per_rank_support,
            "platewide_mechanism_supported":platewide_support,
            "v028y_adjudication":yadj,
            "v028z_adjudication":z.get("adjudication"),
            "adjudication":adj,
        }
        out.append(row)

        print(
            f"#{rank}: radius={'n/a' if rad is None else f'{rad:.2f}px'} "
            f"rPct={'n/a' if radius_pct is None else f'{radius_pct:.3f}'} "
            f"SNR={ssnr:.2f} sPct={snr_pct:.3f} "
            f"similar±3px={similar} positiveNeighbor={has_identified_positive_neighbor}"
        )
        print(f"     => {adj}")

    write_csv(OUT_CSV,out,sorted({k for r in out for k in r}))
    write_csv(OUT_CTRL,u,sorted({k for r in u for k in r}))

    payload={
        "stage":"ORDER01_POSS_PLATEWIDE_DETECTOR_SATELLITE_ADJUDICATION_V028AA",
        "frozen_active_ranks":EXPECTED,
        "guards":{
            "network_access":False,
            "science_pixels_read":False,
            "transient_detector_rerun":False,
            "transient_detector_parameters_changed":False,
            "science_candidates_excluded_from_control_pool":True,
            "native_control_detections_deduplicated":True,
            "candidate_state_mutation":False,
            "candidate_promotion":False,
            "candidate_deletion":False,
            "weighted_candidate_score":False,
        },
        "platewide_control_stats":stats,
        "results":out,
        "interpretive_boundary":(
            "The pooled control distribution contains unique frozen negative "
            "native detections associated with already-qualified ordinary Gaia "
            "stars across the same physical POSS plate. All six science candidate "
            "detections are explicitly excluded before pooling. Plate-wide "
            "compatibility strengthens a neighbouring-star detector-satellite "
            "mechanism when an independent positive Gaia neighbour has already "
            "been identified and the science coordinate lacks a centred positive "
            "point source. This is a mechanism adjudication, not a false-positive "
            "probability, and it does not change candidate state."
        )
    }
    write_json(OUT_JSON,payload)

    md=[
        "# ORDER 01 — Plate-Wide POSS Detector-Satellite Mechanism Adjudication v028aa","",
        "## Guard state","",
        "- No network access.",
        "- Science pixels were not read.",
        "- The frozen transient detector was not rerun.",
        "- All six science candidates were excluded from the pooled controls.",
        "- Native control detections were deduplicated.",
        "- No candidate state was changed.","",
        "## Plate-wide controls","",
        f"- Unique negative native controls: **{stats['unique_negative_control_count']}**.",
        f"- Radius p05/median/p95: **{stats['radius_p05_px']:.2f} / {stats['radius_median_px']:.2f} / {stats['radius_p95_px']:.2f} px**.",
        f"- SNR p05/median/p95: **{stats['snr_p05']:.2f} / {stats['snr_median']:.2f} / {stats['snr_p95']:.2f}**.","",
        "## Results","",
        "| rank | radius | radius pct | SNR | SNR pct | similar ±3 px | positive Gaia neighbour | adjudication |",
        "|---:|---:|---:|---:|---:|---:|---|---|"
    ]
    for r in out:
        md.append(
            f"| #{r['strict_rank']} | "
            f"{'n/a' if r['science_to_neighbor_radius_px'] is None else f'{r['science_to_neighbor_radius_px']:.2f} px'} | "
            f"{'n/a' if r['science_radius_percentile_platewide'] is None else f'{r['science_radius_percentile_platewide']:.3f}'} | "
            f"{r['science_native_snr']:.2f} | "
            f"{'n/a' if r['science_snr_percentile_platewide'] is None else f'{r['science_snr_percentile_platewide']:.3f}'} | "
            f"{r['unique_platewide_controls_within_3px_radius']} | "
            f"{r['identified_positive_gaia_neighbor']} | "
            f"`{r['adjudication']}` |"
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
    print("SCIENCE PIXELS WERE NOT READ.")
    print("Transient detector was NOT rerun.")
    print("No candidate was promoted or deleted.")
    return 0


if __name__=="__main__":
    raise SystemExit(main())
