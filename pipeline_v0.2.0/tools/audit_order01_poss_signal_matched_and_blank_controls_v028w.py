#!/usr/bin/env python3
"""
ORDER 01 — signal-matched POSS star / local blank-background audit v028w

This stage refines v028v after recognising that its v028p control stars were
much brighter than the science candidates.

It performs two independent comparisons:

A. FAINT / SIGNAL-MATCHED GAIA STAR CONTROLS
   - Uses the already-frozen epoch-propagated Gaia candidates from v028b.
   - Predicts their POSS pixels with the same validated native-tile transform.
   - Selects a Gaia location as a physical stellar control only if the raw
     image itself has a positive centered core:
       gaussian center Z >= 3
       positive Gaussian peak <= 3 px from Gaia position
       positive flux centroid <= 3 px from Gaia position
   - For each science candidate, reports the closest controls in positive-peak
     significance. Science pixels never determine which Gaia positions are
     measured or whether a Gaia position qualifies as a star.

B. DETERMINISTIC LOCAL BLANK-BACKGROUND CONTROLS
   - Samples a fixed pixel lattice 30–120 px around each science position.
   - Rejects locations near native detector candidates or Gaia positions.
   - Measures the same raw-image quantities as v028v.
   - Reports empirical tails for the science signed apertures and center value.

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
from scipy.spatial import cKDTree

ROOT = Path.cwd()
BASE = ROOT / "results" / "order01_native_full_v028"
WORK = ROOT / "work" / "order01_native_full_v028"

V028V_SCRIPT = ROOT / "tools" / "audit_order01_poss_physical_source_centering_v028v.py"
V028V_JSON = BASE / "order01_poss_physical_source_centering_v028v.json"
V028B_GAIA = BASE / "order01_gaia_source_candidates_v028b.csv"
STRICT = BASE / "order01_strict_match_triage_v028.csv"
POSS_CAND = BASE / "order01_poss_native_candidates.csv"

OUT_JSON = BASE / "order01_poss_signal_matched_and_blank_controls_v028w.json"
OUT_CSV = BASE / "order01_poss_signal_matched_and_blank_controls_v028w.csv"
OUT_STAR = BASE / "order01_poss_faint_gaia_star_controls_v028w.csv"
OUT_BLANK = BASE / "order01_poss_local_blank_controls_v028w.csv"
OUT_MD = BASE / "ORDER01_POSS_SIGNAL_MATCHED_AND_BLANK_CONTROLS_V028W.md"

EXPECTED = [10,24,25,26,29,30]

STAR_CENTER_MIN_Z = 3.0
STAR_MAX_PEAK_OFFSET_PX = 3.0
STAR_MAX_CENTROID_OFFSET_PX = 3.0
MAX_SIGNAL_MATCH_CONTROLS = 8
MIN_SIGNAL_MATCH_CONTROLS = 3
SIGNAL_MATCH_MAX_RATIO = 4.0

BLANK_GRID_STEP_PX = 24
BLANK_MIN_RADIUS_PX = 30.0
BLANK_MAX_RADIUS_PX = 120.0
BLANK_EXCLUSION_NATIVE_PX = 8.0
BLANK_EXCLUSION_GAIA_PX = 8.0
MAX_BLANK_CONTROLS = 64


def load_v028v_module():
    if not V028V_SCRIPT.is_file():
        raise RuntimeError(f"Missing prerequisite script: {V028V_SCRIPT}")
    spec = importlib.util.spec_from_file_location("v028vmod", V028V_SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


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


def rank_of_gaia(row):
    return i(pick(row, "strict_rank", "rank", "candidate_rank", "survivor_rank"))


def empirical_lower(values, x):
    a = np.asarray([v for v in values if v is not None and math.isfinite(float(v))], float)
    if a.size == 0 or x is None:
        return None
    return float((1 + np.count_nonzero(a <= x)) / (a.size + 1))


def empirical_upper(values, x):
    a = np.asarray([v for v in values if v is not None and math.isfinite(float(v))], float)
    if a.size == 0 or x is None:
        return None
    return float((1 + np.count_nonzero(a >= x)) / (a.size + 1))


def quant(values, q):
    a = np.asarray([v for v in values if v is not None and math.isfinite(float(v))], float)
    return None if a.size == 0 else float(np.quantile(a, q))


def main():
    print("="*128)
    print("ORDER 01 — SIGNAL-MATCHED POSS STAR / LOCAL BLANK-BACKGROUND AUDIT v028w")
    print("="*128)
    print("NO NETWORK ACCESS.")
    print("SCIENCE PIXELS ARE READ.")
    print("Frozen transient detector is NOT rerun.\n")

    for p in (V028V_SCRIPT, V028V_JSON, V028B_GAIA, STRICT, POSS_CAND):
        if not p.is_file():
            print(f"FAIL missing input: {p}")
            return 2

    v = load_v028v_module()
    vv = json.loads(V028V_JSON.read_text(encoding="utf-8"))
    if vv.get("frozen_active_ranks") != EXPECTED:
        raise RuntimeError("v028v frozen ranks mismatch")
    if vv.get("guards",{}).get("candidate_state_mutation") is not False:
        raise RuntimeError("v028v state guard mismatch")

    strict_rows = read_csv(STRICT)
    native = read_csv(POSS_CAND)
    gaia = read_csv(V028B_GAIA)
    strict = {i(r["strict_rank"]): r for r in strict_rows if i(r["strict_rank"]) in EXPECTED}
    if sorted(strict) != EXPECTED:
        raise RuntimeError("strict survivor mismatch")

    inv = v.inventory()
    tiles = {str(pick(strict[r], "poss_tile_id")) for r in EXPECTED}
    tr = {tid: v.fit_transform(native, tid) for tid in sorted(tiles)}
    for tid,t in tr.items():
        if not (t.validation["forward_ok"] and t.validation["inverse_ok"]):
            raise RuntimeError(f"{tid}: transform validation failed")

    science = {int(r["strict_rank"]): r for r in vv["results"]}
    print("Frozen v028v/rank/tile/transform guards: PASS\n")

    # ------------------------------------------------------------------
    # A. Measure every frozen v028b Gaia position that maps into the relevant
    #    POSS tile, then select centered positive raw-image stars.
    # ------------------------------------------------------------------
    star_controls = []
    all_gaia_pixels_by_rank = {r: [] for r in EXPECTED}

    for g in gaia:
        rank = rank_of_gaia(g)
        if rank not in EXPECTED:
            continue
        ra = f(pick(g, "ra_target_deg"))
        dec = f(pick(g, "dec_target_deg"))
        if None in (ra,dec):
            continue
        tid = str(pick(strict[rank], "poss_tile_id"))
        gx,gy = tr[tid].sky_to_pixel(ra,dec)
        all_gaia_pixels_by_rank[rank].append((gx,gy))

        met = v.measure(inv[tid], gx, gy)
        if met.get("status") != "SUCCESS":
            continue

        pcent = met.get("positive_flux_centroid_offset_px_r7")
        qualifies = (
            met.get("gaussian_center_z") is not None
            and met["gaussian_center_z"] >= STAR_CENTER_MIN_Z
            and met.get("positive_gaussian_peak_offset_px_r7") is not None
            and met["positive_gaussian_peak_offset_px_r7"] <= STAR_MAX_PEAK_OFFSET_PX
            and pcent is not None
            and pcent <= STAR_MAX_CENTROID_OFFSET_PX
        )
        if not qualifies:
            continue

        star_controls.append({
            "strict_rank":rank,
            "source_id":pick(g,"source_id"),
            "g_mag":f(pick(g,"g_mag")),
            "tile_id":tid,
            "pred_global_x":gx,
            "pred_global_y":gy,
            **met,
        })

    print("Centered positive Gaia controls from frozen v028b:")
    for rank in EXPECTED:
        rr=[x for x in star_controls if x["strict_rank"]==rank]
        if rr:
            zs=[x["positive_gaussian_peak_z_r7"] for x in rr]
            print(f"  #{rank}: N={len(rr)} peakZ range={min(zs):.2f}–{max(zs):.2f}")
        else:
            print(f"  #{rank}: N=0")
    print()

    # Native-candidate KD trees for blank exclusion.
    native_tree = {}
    for rank in EXPECTED:
        tid=str(pick(strict[rank],"poss_tile_id"))
        pts=[]
        for r in native:
            if str(r.get("tile_id","")) != tid:
                continue
            gx=f(r.get("global_x")); gy=f(r.get("global_y"))
            if gx is not None and gy is not None:
                pts.append((gx,gy))
        native_tree[rank]=cKDTree(np.asarray(pts,float)) if pts else None

    gaia_tree = {}
    for rank in EXPECTED:
        pts=all_gaia_pixels_by_rank[rank]
        gaia_tree[rank]=cKDTree(np.asarray(pts,float)) if pts else None

    blank_rows=[]
    results=[]

    # ------------------------------------------------------------------
    # B. Candidate-by-candidate signal-match and local blanks.
    # ------------------------------------------------------------------
    for rank in EXPECTED:
        sc = science[rank]
        tid = str(sc["tile_id"])
        sgx=float(sc["global_x"]); sgy=float(sc["global_y"])
        speak=f(sc.get("positive_gaussian_peak_z_r7"))
        scenter=f(sc.get("gaussian_center_z"))

        # Signal-matched star controls. Use log peak significance so equal
        # fractional differences are treated symmetrically.
        candidates=[x for x in star_controls if x["strict_rank"]==rank]
        for x in candidates:
            z=max(float(x["positive_gaussian_peak_z_r7"]),1e-9)
            target=max(speak if speak is not None else 0.0,1e-9)
            x["_signal_distance"]=abs(math.log(z/target))
            x["_signal_ratio"]=max(z/target,target/z)
        within=[x for x in candidates if x["_signal_ratio"]<=SIGNAL_MATCH_MAX_RATIO]
        pool=within if len(within)>=MIN_SIGNAL_MATCH_CONTROLS else candidates
        matched=sorted(pool,key=lambda x:x["_signal_distance"])[:MAX_SIGNAL_MATCH_CONTROLS]

        matched_peak_offsets=[x["positive_gaussian_peak_offset_px_r7"] for x in matched]
        matched_cent_offsets=[x["positive_flux_centroid_offset_px_r7"] for x in matched]
        matched_axis=[x["positive_flux_axis_ratio_r7"] for x in matched]
        matched_conc=[x["positive_concentration_r3_r7"] for x in matched]
        matched_centerz=[x["gaussian_center_z"] for x in matched]

        # Deterministic blank lattice.
        blanks=[]
        offsets=[]
        lim=int(BLANK_MAX_RADIUS_PX)
        for dy in range(-lim,lim+1,BLANK_GRID_STEP_PX):
            for dx in range(-lim,lim+1,BLANK_GRID_STEP_PX):
                rr=math.hypot(dx,dy)
                if BLANK_MIN_RADIUS_PX <= rr <= BLANK_MAX_RADIUS_PX:
                    offsets.append((rr,dy,dx))
        offsets.sort()  # deterministic nearest-first

        for _,dy,dx in offsets:
            gx=sgx+dx; gy=sgy+dy
            nt=native_tree[rank]
            gt=gaia_tree[rank]
            if nt is not None:
                d,_=nt.query([gx,gy],k=1)
                if d<BLANK_EXCLUSION_NATIVE_PX:
                    continue
            if gt is not None:
                d,_=gt.query([gx,gy],k=1)
                if d<BLANK_EXCLUSION_GAIA_PX:
                    continue
            met=v.measure(inv[tid],gx,gy)
            if met.get("status")!="SUCCESS":
                continue
            row={
                "strict_rank":rank,"tile_id":tid,
                "global_x":gx,"global_y":gy,
                "offset_from_science_px":math.hypot(dx,dy),
                "offset_dx_px":dx,"offset_dy_px":dy,
                **met
            }
            blanks.append(row); blank_rows.append(row)
            if len(blanks)>=MAX_BLANK_CONTROLS:
                break

        ap3=[x["ap3_signed_z"] for x in blanks]
        ap5=[x["ap5_signed_z"] for x in blanks]
        ap7=[x["ap7_signed_z"] for x in blanks]
        gz=[x["gaussian_center_z"] for x in blanks]

        row={
            "strict_rank":rank,
            "science_gaussian_center_z":scenter,
            "science_positive_peak_z":speak,
            "science_positive_peak_offset_px":f(sc.get("positive_gaussian_peak_offset_px_r7")),
            "science_positive_centroid_offset_px":f(sc.get("positive_flux_centroid_offset_px_r7")),
            "science_positive_axis_ratio":f(sc.get("positive_flux_axis_ratio_r7")),
            "science_positive_concentration":f(sc.get("positive_concentration_r3_r7")),
            "science_negative_trough_offset_px":f(sc.get("negative_gaussian_trough_offset_px_r7")),
            "science_ap3_signed_z":f(sc.get("ap3_signed_z")),
            "science_ap5_signed_z":f(sc.get("ap5_signed_z")),
            "science_ap7_signed_z":f(sc.get("ap7_signed_z")),
            "centered_positive_core_ge3sigma":bool(scenter is not None and scenter>=3.0),
            "same_tile_centered_gaia_control_count":len(candidates),
            "signal_matched_control_count":len(matched),
            "signal_match_used_within_factor4_pool":len(within)>=MIN_SIGNAL_MATCH_CONTROLS,
            "matched_peak_offset_p95_px":quant(matched_peak_offsets,.95),
            "matched_centroid_offset_p95_px":quant(matched_cent_offsets,.95),
            "matched_axis_ratio_p05":quant(matched_axis,.05),
            "matched_concentration_p05":quant(matched_conc,.05),
            "matched_concentration_p95":quant(matched_conc,.95),
            "matched_center_z_min":min(matched_centerz) if matched_centerz else None,
            "blank_control_count":len(blanks),
            "blank_ap3_lower_tail_p":empirical_lower(ap3,f(sc.get("ap3_signed_z"))),
            "blank_ap5_lower_tail_p":empirical_lower(ap5,f(sc.get("ap5_signed_z"))),
            "blank_ap7_lower_tail_p":empirical_lower(ap7,f(sc.get("ap7_signed_z"))),
            "blank_center_z_lower_tail_p":empirical_lower(gz,scenter),
            "blank_ap7_p05":quant(ap7,.05),
            "blank_ap7_median":quant(ap7,.50),
            "blank_ap7_p95":quant(ap7,.95),
        }

        # Conservative descriptive label.
        if row["centered_positive_core_ge3sigma"]:
            if (
                len(matched)>=MIN_SIGNAL_MATCH_CONTROLS
                and row["science_positive_peak_offset_px"] is not None
                and row["matched_peak_offset_p95_px"] is not None
                and row["science_positive_peak_offset_px"] <= row["matched_peak_offset_p95_px"]
                and row["science_positive_centroid_offset_px"] is not None
                and row["matched_centroid_offset_p95_px"] is not None
                and row["science_positive_centroid_offset_px"] <= row["matched_centroid_offset_p95_px"]
            ):
                label="CENTERED_POSITIVE_CORE_CONSISTENT_WITH_SIGNAL_MATCHED_STARS"
            else:
                label="POSITIVE_CORE_PRESENT_BUT_CENTERING_NOT_STARLIKE"
        else:
            if (
                row["science_ap7_signed_z"] is not None
                and row["science_ap7_signed_z"] <= -3
                and row["science_negative_trough_offset_px"] is not None
                and row["science_negative_trough_offset_px"] <= 2
            ):
                label="CENTERED_NEGATIVE_DEFICIT_SUPPORTED"
            elif row["science_ap7_signed_z"] is not None and row["science_ap7_signed_z"] <= -3:
                label="NEGATIVE_APERTURE_DEFICIT_NOT_POINT_CENTERED"
            else:
                label="NO_CENTERED_POSITIVE_POINT_SOURCE;_LOCAL_STRUCTURE_MIXED_OR_WEAK"

        row["descriptive_classification"]=label
        results.append(row)

        print(
            f"#{rank}: GaiaStars={len(candidates)} matched={len(matched)} "
            f"science centerZ={scenter:.2f} peakZ={speak:.2f} "
            f"peakOff={row['science_positive_peak_offset_px']}px "
            f"blankN={len(blanks)} ap7={row['science_ap7_signed_z']:.2f} "
            f"blankLowerP={row['blank_ap7_lower_tail_p']} "
            f"=> {label}"
        )

    # Remove scratch fields before writing star controls.
    for x in star_controls:
        x.pop("_signal_distance",None)
        x.pop("_signal_ratio",None)

    write_csv(OUT_CSV,results,sorted({k for r in results for k in r}))
    write_csv(OUT_STAR,star_controls,sorted({k for r in star_controls for k in r}))
    write_csv(OUT_BLANK,blank_rows,sorted({k for r in blank_rows for k in r}))

    payload={
        "stage":"ORDER01_POSS_SIGNAL_MATCHED_AND_BLANK_CONTROLS_V028W",
        "frozen_active_ranks":EXPECTED,
        "guards":{
            "network_access":False,
            "science_pixels_read":True,
            "candidate_pixels_used_to_select_gaia_star_controls":False,
            "candidate_pixels_used_as_blank_controls":False,
            "transient_detector_rerun":False,
            "transient_detector_parameters_changed":False,
            "candidate_state_mutation":False,
            "candidate_promotion":False,
            "candidate_deletion":False,
            "weighted_candidate_score":False,
        },
        "fixed_policy":{
            "star_center_min_z":STAR_CENTER_MIN_Z,
            "star_max_peak_offset_px":STAR_MAX_PEAK_OFFSET_PX,
            "star_max_centroid_offset_px":STAR_MAX_CENTROID_OFFSET_PX,
            "signal_match_max_ratio":SIGNAL_MATCH_MAX_RATIO,
            "blank_grid_step_px":BLANK_GRID_STEP_PX,
            "blank_min_radius_px":BLANK_MIN_RADIUS_PX,
            "blank_max_radius_px":BLANK_MAX_RADIUS_PX,
            "blank_exclusion_native_px":BLANK_EXCLUSION_NATIVE_PX,
            "blank_exclusion_gaia_px":BLANK_EXCLUSION_GAIA_PX,
            "max_blank_controls":MAX_BLANK_CONTROLS,
        },
        "results":results,
        "interpretive_boundary":(
            "Signal-matched Gaia controls reduce the brightness mismatch present "
            "in v028v. A missing centered positive core weighs against a simple "
            "positive stellar point-source interpretation on POSS, even when "
            "broader integrated flux is positive. Blank-background empirical "
            "tails quantify local unusualness but are not astrophysical p-values "
            "and do not identify a defect mechanism. No candidate state changes."
        )
    }
    write_json(OUT_JSON,payload)

    md=[
        "# ORDER 01 — Signal-Matched POSS Star / Local Blank-Background Audit v028w","",
        "## Guard state","",
        "- No network access.",
        "- Science pixels were read.",
        "- Science pixels did not select Gaia star controls or blank controls.",
        "- The frozen transient detector was not rerun.",
        "- No candidate state was changed.","",
        "## Results","",
        "| rank | centered +core | matched stars | +peak offset | ap7 Z | blank lower-tail p | classification |",
        "|---:|---|---:|---:|---:|---:|---|"
    ]
    for r in results:
        md.append(
            f"| #{r['strict_rank']} | {r['centered_positive_core_ge3sigma']} | "
            f"{r['signal_matched_control_count']} | "
            f"{r['science_positive_peak_offset_px'] if r['science_positive_peak_offset_px'] is not None else 'n/a'} | "
            f"{r['science_ap7_signed_z']:.3f} | "
            f"{r['blank_ap7_lower_tail_p'] if r['blank_ap7_lower_tail_p'] is not None else 'n/a'} | "
            f"`{r['descriptive_classification']}` |"
        )
    md += ["","## Interpretation boundary","",payload["interpretive_boundary"]]
    OUT_MD.write_text("\n".join(md),encoding="utf-8")

    print("\nOutputs:")
    print(f"  {OUT_JSON}")
    print(f"  {OUT_CSV}")
    print(f"  {OUT_STAR}")
    print(f"  {OUT_BLANK}")
    print(f"  {OUT_MD}")
    print()
    print("NO network query was made.")
    print("SCIENCE PIXELS WERE READ.")
    print("Transient detector was NOT rerun.")
    print("No candidate was promoted or deleted.")
    return 0


if __name__=="__main__":
    raise SystemExit(main())
