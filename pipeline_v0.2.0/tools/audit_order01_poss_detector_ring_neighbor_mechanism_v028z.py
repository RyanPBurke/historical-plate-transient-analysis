#!/usr/bin/env python3
"""
ORDER 01 — POSS detector-ring / neighbouring-star mechanism audit v028z

Purpose
-------
v028y established that #10/#25/#26 have broad positive POSS flux attributable
to displaced Gaia stars, while the frozen science coordinate itself lacks a
centred positive point source. #29 instead has a centred negative deficit with
no local positive-source counterpart.

This stage tests a concrete mechanism for the neighbour-attributed cases:
does the frozen POSS detector commonly generate NEGATIVE-polarity native
candidates at comparable radii around ordinary centred positive Gaia stars?

Method
------
1. Reuse v028w's already-selected physical centred-positive Gaia controls.
2. For every such control star, inspect the frozen native POSS candidate list
   on the same tile and record negative-polarity candidates 4–25 px away.
3. For each science endpoint:
   - report its frozen native polarity and SNR;
   - measure its distance from the Gaia neighbour identified by v028y/v028x;
   - if science polarity is negative, compare that radius with the empirical
     nearest-negative-satellite radii around ordinary Gaia controls;
   - report the science candidate's rank among negative-polarity detections
     around its identified neighbour.
4. For #29, separately report local clustering of negative native detections,
   without inventing a positive-star counterpart.

This is a detector-output geometry audit only. It does not rerun the detector.

No network access.
Science pixel arrays are NOT read.
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

V028Y_JSON = BASE / "order01_poss_science_centered_counterpart_adjudication_v028y.json"
V028W_STAR = BASE / "order01_poss_faint_gaia_star_controls_v028w.csv"
POSS_CAND = BASE / "order01_poss_native_candidates.csv"
STRICT = BASE / "order01_strict_match_triage_v028.csv"

OUT_JSON = BASE / "order01_poss_detector_ring_neighbor_mechanism_v028z.json"
OUT_CSV = BASE / "order01_poss_detector_ring_neighbor_mechanism_v028z.csv"
OUT_CTRL = BASE / "order01_poss_detector_ring_control_satellites_v028z.csv"
OUT_MD = BASE / "ORDER01_POSS_DETECTOR_RING_NEIGHBOR_MECHANISM_V028Z.md"

EXPECTED = [10,24,25,26,29,30]
INNER_PX = 4.0
OUTER_PX = 25.0
SIMILAR_RADIUS_TOL_PX = 3.0
MIN_CONTROLS = 4


def read_csv(path):
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def write_csv(path, rows, fields):
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
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


def qtile(values, q):
    a=np.asarray([x for x in values if x is not None and math.isfinite(float(x))],float)
    return None if a.size == 0 else float(np.quantile(a,q))


def guarded_two_sided_rank(values, x):
    """Descriptive empirical percentile/tail, not an astrophysical p-value."""
    a=np.asarray([v for v in values if v is not None and math.isfinite(float(v))],float)
    if a.size == 0 or x is None:
        return None,None
    pct=float((np.count_nonzero(a <= x)+0.5)/(a.size+1.0))
    tail=min(pct,1-pct)*2
    return pct,max(0.0,float(tail))


def main():
    print("="*128)
    print("ORDER 01 — POSS DETECTOR-RING / NEIGHBOURING-STAR MECHANISM AUDIT v028z")
    print("="*128)
    print("NO NETWORK ACCESS.")
    print("SCIENCE PIXELS ARE NOT READ.")
    print("Frozen transient detector is NOT rerun.\n")

    for p in (V028Y_JSON,V028W_STAR,POSS_CAND,STRICT):
        if not p.is_file():
            print(f"FAIL missing input: {p}")
            return 2

    vy=json.loads(V028Y_JSON.read_text(encoding="utf-8"))
    if vy.get("frozen_active_ranks") != EXPECTED:
        raise RuntimeError("v028y frozen ranks mismatch")
    if vy.get("guards",{}).get("candidate_state_mutation") is not False:
        raise RuntimeError("v028y state guard mismatch")

    stars=read_csv(V028W_STAR)
    native=read_csv(POSS_CAND)
    strict_rows=read_csv(STRICT)
    strict={i(r["strict_rank"]):r for r in strict_rows if i(r["strict_rank"]) in EXPECTED}
    if sorted(strict) != EXPECTED:
        raise RuntimeError("strict survivor mismatch")

    vyres={int(r["strict_rank"]):r for r in vy["results"]}

    native_by_tile={}
    for r in native:
        native_by_tile.setdefault(str(r.get("tile_id","")),[]).append(r)

    # ------------------------------------------------------------------
    # Ordinary-star controls: nearest and all negative detector satellites.
    # ------------------------------------------------------------------
    ctrl_rows=[]
    nearest_by_rank={r:[] for r in EXPECTED}

    for s in stars:
        rank=i(s.get("strict_rank"))
        if rank not in EXPECTED:
            continue
        tid=str(s.get("tile_id",""))
        gx=f(pick(s,"pred_global_x","global_x"))
        gy=f(pick(s,"pred_global_y","global_y"))
        if None in (gx,gy):
            continue

        neg=[]
        for n in native_by_tile.get(tid,[]):
            if i(n.get("polarity")) != -1:
                continue
            nx=f(n.get("global_x")); ny=f(n.get("global_y"))
            if None in (nx,ny):
                continue
            d=math.hypot(nx-gx,ny-gy)
            if INNER_PX <= d <= OUTER_PX:
                neg.append((d,n))
        neg.sort(key=lambda z:z[0])

        if neg:
            nearest_by_rank[rank].append(neg[0][0])

        for j,(d,n) in enumerate(neg,1):
            ctrl_rows.append({
                "strict_rank":rank,
                "tile_id":tid,
                "source_id":s.get("source_id"),
                "g_mag":f(s.get("g_mag")),
                "star_global_x":gx,
                "star_global_y":gy,
                "negative_satellite_rank":j,
                "negative_candidate_index":i(n.get("candidate_index")),
                "negative_candidate_snr":f(n.get("snr")),
                "negative_candidate_distance_px":d,
                "is_nearest_negative_satellite":j==1,
            })

    print("Ordinary centred Gaia controls with a negative native satellite in 4–25 px:")
    for rank in EXPECTED:
        vals=nearest_by_rank[rank]
        print(
            f"  #{rank}: N={len(vals)}"
            + ("" if not vals else
               f" nearest-radius median={np.median(vals):.2f}px "
               f"range={min(vals):.2f}–{max(vals):.2f}px")
        )
    print()

    # ------------------------------------------------------------------
    # Science endpoint geometry.
    # ------------------------------------------------------------------
    results=[]
    for rank in EXPECTED:
        y=vyres[rank]
        tid=str(y["tile_id"])
        sci_idx=i(y["science_candidate_index"])
        sgx=f(y["science_global_x"]); sgy=f(y["science_global_y"])

        sci_matches=[r for r in native_by_tile.get(tid,[])
                     if i(r.get("candidate_index"))==sci_idx]
        if len(sci_matches)!=1:
            raise RuntimeError(f"#{rank}: expected one native science row, got {len(sci_matches)}")
        sn=sci_matches[0]
        spol=i(sn.get("polarity")); ssnr=f(sn.get("snr"))

        neigh_sid=str(y.get("v028x_displaced_positive_gaia_source_id") or "")
        neigh_dist=f(y.get("science_nearest_gaia_distance_px"))
        # For neighbour-attributed cases the exact neighbour distance is the
        # distance from science coordinate to that identified source, already
        # frozen by v028y as science_nearest_gaia_distance_px when it is the
        # nearest source. Guard by source-id equality.
        if neigh_sid and str(y.get("science_nearest_gaia_source_id")) != neigh_sid:
            # Reconstruct from v028x offset geometry only if source differs.
            # v028y stores the science->nearest Gaia; do not silently substitute.
            neigh_dist=None

        # All negative native candidates around the identified neighbour cannot
        # be reconstructed unless its pixel coordinates are present here.
        # Use control-star table when the source itself is one of v028w controls.
        star_match=[s for s in stars if str(s.get("source_id"))==neigh_sid
                    and str(s.get("tile_id"))==tid]
        science_rank_around_neighbor=None
        neg_count_around_neighbor=None
        closer_negative_count=None
        if len(star_match)==1 and neigh_sid:
            ngx=f(pick(star_match[0],"pred_global_x","global_x"))
            ngy=f(pick(star_match[0],"pred_global_y","global_y"))
            around=[]
            for n in native_by_tile.get(tid,[]):
                if i(n.get("polarity")) != -1:
                    continue
                nx=f(n.get("global_x")); ny=f(n.get("global_y"))
                if None in (nx,ny): continue
                d=math.hypot(nx-ngx,ny-ngy)
                if INNER_PX <= d <= OUTER_PX:
                    around.append((d,i(n.get("candidate_index"))))
            around.sort()
            neg_count_around_neighbor=len(around)
            ids=[idx for _,idx in around]
            if sci_idx in ids:
                science_rank_around_neighbor=ids.index(sci_idx)+1
                sci_rad=[d for d,idx in around if idx==sci_idx][0]
                neigh_dist=sci_rad
                closer_negative_count=science_rank_around_neighbor-1

        ctrl=nearest_by_rank[rank]
        pct,tail=guarded_two_sided_rank(ctrl,neigh_dist if spol==-1 else None)
        similar=sum(1 for z in ctrl
                    if neigh_dist is not None and abs(z-neigh_dist)<=SIMILAR_RADIUS_TOL_PX)

        local_neg=[]
        for n in native_by_tile.get(tid,[]):
            if i(n.get("polarity")) != -1 or i(n.get("candidate_index"))==sci_idx:
                continue
            nx=f(n.get("global_x")); ny=f(n.get("global_y"))
            if None in (nx,ny): continue
            d=math.hypot(nx-sgx,ny-sgy)
            if d<=15:
                local_neg.append((d,n))
        local_neg.sort(key=lambda z:z[0])

        mechanism_supported=bool(
            spol==-1
            and neigh_sid
            and neigh_dist is not None
            and y.get("v028x_positive_attribution")=="DISPLACED_POSITIVE_STRUCTURE_MATCHES_GAIA"
            and len(ctrl)>=MIN_CONTROLS
            and similar>=1
        )

        if mechanism_supported:
            adjudication="NEGATIVE_DETECTOR_SATELLITE_AROUND_IDENTIFIED_GAIA_NEIGHBOUR_SUPPORTED"
        elif rank==29 and bool(y.get("centered_negative_by_v028w")):
            adjudication="CENTERED_NEGATIVE_FEATURE_WITHOUT_POSITIVE_NEIGHBOUR;_NOT_STAR_RING_ATTRIBUTED"
        elif y.get("adjudication")=="NO_CENTERED_POSITIVE_POINT_SOURCE;_POSS_STRUCTURE_WEAK_OR_MIXED":
            adjudication="NO_CENTERED_POINT_SOURCE;_RING_MECHANISM_NOT_ESTABLISHED"
        else:
            adjudication="DETECTOR_RING_MECHANISM_UNRESOLVED"

        row={
            "strict_rank":rank,
            "tile_id":tid,
            "science_candidate_index":sci_idx,
            "science_native_polarity":spol,
            "science_native_snr":ssnr,
            "v028y_adjudication":y.get("adjudication"),
            "identified_neighbor_gaia_source_id":neigh_sid or None,
            "identified_neighbor_gaia_g_mag":f(y.get("v028x_displaced_positive_gaia_g_mag")),
            "science_to_identified_neighbor_distance_px":neigh_dist,
            "control_nearest_negative_radius_count":len(ctrl),
            "control_nearest_negative_radius_p05_px":qtile(ctrl,.05),
            "control_nearest_negative_radius_median_px":qtile(ctrl,.50),
            "control_nearest_negative_radius_p95_px":qtile(ctrl,.95),
            "science_radius_empirical_percentile":pct,
            "science_radius_two_sided_tail":tail,
            "control_nearest_radii_within_3px_of_science":similar,
            "negative_native_count_4to25px_around_identified_neighbor":neg_count_around_neighbor,
            "science_negative_rank_around_identified_neighbor":science_rank_around_neighbor,
            "closer_negative_candidates_around_identified_neighbor":closer_negative_count,
            "other_negative_native_within15px_of_science":len(local_neg),
            "nearest_other_negative_native_distance_px":
                None if not local_neg else local_neg[0][0],
            "nearest_other_negative_native_candidate_index":
                None if not local_neg else i(local_neg[0][1].get("candidate_index")),
            "mechanism_supported_descriptively":mechanism_supported,
            "adjudication":adjudication,
        }
        results.append(row)

        print(
            f"#{rank}: science polarity={spol:+d} SNR={ssnr:.2f} "
            f"neighbor={neigh_sid or 'none'} radius="
            f"{'n/a' if neigh_dist is None else f'{neigh_dist:.2f}px'} "
            f"controls={len(ctrl)} similar±3px={similar} "
            f"rankAroundNeighbor={science_rank_around_neighbor}"
        )
        print(f"     => {adjudication}")

    write_csv(OUT_CSV,results,sorted({k for r in results for k in r}))
    write_csv(OUT_CTRL,ctrl_rows,sorted({k for r in ctrl_rows for k in r}))

    payload={
        "stage":"ORDER01_POSS_DETECTOR_RING_NEIGHBOR_MECHANISM_V028Z",
        "frozen_active_ranks":EXPECTED,
        "guards":{
            "network_access":False,
            "science_pixels_read":False,
            "transient_detector_rerun":False,
            "transient_detector_parameters_changed":False,
            "candidate_state_mutation":False,
            "candidate_promotion":False,
            "candidate_deletion":False,
            "weighted_candidate_score":False,
        },
        "fixed_policy":{
            "negative_satellite_inner_px":INNER_PX,
            "negative_satellite_outer_px":OUTER_PX,
            "similar_radius_tolerance_px":SIMILAR_RADIUS_TOL_PX,
            "minimum_control_count":MIN_CONTROLS,
        },
        "results":results,
        "interpretive_boundary":(
            "This stage tests whether a negative-polarity science detection lies "
            "at a radius where the frozen detector also produces negative native "
            "satellites around ordinary centred positive Gaia stars. Such a match, "
            "combined with an independently identified neighbouring Gaia source "
            "and absence of a centred science point source, supports a detector/"
            "stellar-wing mechanism. It is descriptive, not a false-positive "
            "probability. No detector is rerun and no candidate state changes."
        )
    }
    write_json(OUT_JSON,payload)

    md=[
        "# ORDER 01 — POSS Detector-Ring / Neighbouring-Star Mechanism Audit v028z","",
        "## Guard state","",
        "- No network access.",
        "- Science pixel arrays were not read.",
        "- The frozen transient detector was not rerun.",
        "- No candidate was promoted, deleted, or otherwise mutated.","",
        "## Results","",
        "| rank | polarity | neighbour Gaia | science→star radius | controls | similar radii | science rank around star | adjudication |",
        "|---:|---:|---|---:|---:|---:|---:|---|"
    ]
    for r in results:
        md.append(
            f"| #{r['strict_rank']} | {r['science_native_polarity']} | "
            f"`{r['identified_neighbor_gaia_source_id'] or ''}` | "
            f"{'n/a' if r['science_to_identified_neighbor_distance_px'] is None else f'{r['science_to_identified_neighbor_distance_px']:.2f} px'} | "
            f"{r['control_nearest_negative_radius_count']} | "
            f"{r['control_nearest_radii_within_3px_of_science']} | "
            f"{r['science_negative_rank_around_identified_neighbor'] if r['science_negative_rank_around_identified_neighbor'] is not None else 'n/a'} | "
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
