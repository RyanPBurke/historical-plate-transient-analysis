#!/usr/bin/env python3
"""
ORDER 01 — official DR7 fitted-position adjudication of v028q v028u

Purpose
-------
v028t established that all eight frozen v028q primary Gaia controls are
officially detected on ai43437 in ATLAS, and five are also detected in APASS.

The catalog identity is already independently frozen by v028s querycat:
the best ATLAS counterparts lie ~0.004–0.019 arcsec from Gaia(1951), and the
best APASS counterparts ~0.03–0.13 arcsec away.

Therefore catalogRa/catalogDec are not needed to perform the decisive test.
For each OFFICIAL_DETECTION row we compare the official DR7 fitted plate
position directly to the frozen Gaia(1951) position from the v028q reference
table.

This stage asks whether the official DASCH fitted-source astrometry reproduces
the coherent raw-pixel v028q translation (-17.08,+10.94 arcsec).

No network access.
No science pixels.
No detector rerun.
No candidate state mutation.
"""

from __future__ import annotations

import csv
import json
import math
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path.cwd()
BASE = ROOT / "results" / "order01_native_full_v028"

V028T_JSON = BASE / "order01_official_dasch_ai43437_row_audit_v028t.json"
V028Q_JSON = BASE / "order01_plate_registered_bright_gaia_astrometry_v028q.json"
V028Q_REFS = BASE / "order01_plate_registered_bright_gaia_references_v028q.csv"

OUT_JSON = BASE / "order01_official_dr7_fitted_position_adjudication_v028u.json"
OUT_CSV = BASE / "order01_official_dr7_fitted_position_adjudication_v028u.csv"
OUT_MD = BASE / "ORDER01_OFFICIAL_DR7_FITTED_POSITION_ADJUDICATION_V028U.md"

EXPECTED = [10,24,25,26,29,30]


def read_csv(path):
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def write_csv(path, rows, fields):
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


def b(v):
    return str(v).strip().lower() in {"true","1","yes","y","t"}


def vec(ra1,dec1,ra2,dec2):
    dec0=0.5*(dec1+dec2)
    east=(ra2-ra1)*3600.0*math.cos(math.radians(dec0))
    north=(dec2-dec1)*3600.0
    sep=math.hypot(east,north)
    pa=math.degrees(math.atan2(east,north))%360.0
    return east,north,sep,pa


def summary(rows):
    if not rows:
        return None
    a=np.array([[r["official_fit_minus_gaia_east_arcsec"],
                 r["official_fit_minus_gaia_north_arcsec"]] for r in rows],float)
    med=np.median(a,axis=0)
    mean=np.mean(a,axis=0)
    res=np.hypot(a[:,0]-med[0],a[:,1]-med[1])
    ang=np.arctan2(a[:,0],a[:,1])
    R=math.hypot(float(np.mean(np.sin(ang))),float(np.mean(np.cos(ang))))
    return {
        "count":len(rows),
        "median_east_arcsec":float(med[0]),
        "median_north_arcsec":float(med[1]),
        "median_vector_magnitude_arcsec":float(math.hypot(*med)),
        "mean_east_arcsec":float(mean[0]),
        "mean_north_arcsec":float(mean[1]),
        "residual_median_arcsec":float(np.median(res)),
        "residual_p95_arcsec":float(np.quantile(res,.95,method="higher")),
        "circular_R":float(R),
    }


def main():
    print("="*128)
    print("ORDER 01 — OFFICIAL DR7 FITTED-POSITION ADJUDICATION OF v028q v028u")
    print("="*128)
    print("NO NETWORK ACCESS.")
    print("SCIENCE PIXELS ARE NOT READ.")
    print("Frozen transient detector is NOT rerun.\n")

    for p in (V028T_JSON,V028Q_JSON,V028Q_REFS):
        if not p.is_file():
            print(f"FAIL missing input: {p}"); return 2

    vt=json.loads(V028T_JSON.read_text(encoding="utf-8"))
    vq=json.loads(V028Q_JSON.read_text(encoding="utf-8"))
    qrefs=read_csv(V028Q_REFS)

    if vt.get("frozen_active_ranks")!=EXPECTED or vq.get("frozen_active_ranks")!=EXPECTED:
        raise RuntimeError("frozen rank guard mismatch")
    if vt.get("guards",{}).get("candidate_state_mutation") is not False:
        raise RuntimeError("v028t state guard mismatch")

    primary=[r for r in qrefs if b(r.get("final_primary_reference"))]
    if len(primary)!=8:
        raise RuntimeError(f"expected 8 frozen v028q primary refs, found {len(primary)}")

    by_source={str(r["source_id"]):r for r in primary}
    if len(by_source)!=8:
        raise RuntimeError("duplicate/missing primary Gaia source IDs")

    model=vq.get("plate_model",{}).get("selected_model",{})
    if model.get("kind")!="translation" or len(model.get("params",[]))!=2:
        raise RuntimeError("v028q selected model is not the expected translation")
    vqv=np.array(model["params"],float)
    vqmag=float(np.hypot(*vqv))
    u=vqv/vqmag

    rows=[]
    for r in vt.get("rows",[]):
        if r.get("classification")!="OFFICIAL_DETECTION":
            continue
        sid=str(r.get("source_id",""))
        g=by_source.get(sid)
        if g is None:
            continue
        gra=f(g.get("ra_target_deg")); gdec=f(g.get("dec_target_deg"))
        fra=f(r.get("fit_ra_deg")); fdec=f(r.get("fit_dec_deg"))
        if None in (gra,gdec,fra,fdec):
            continue
        east,north,sep,pa=vec(gra,gdec,fra,fdec)
        ov=np.array([east,north],float)
        dist_vq=float(np.linalg.norm(ov-vqv))
        proj=float(np.dot(ov,u))
        rows.append({
            "strict_rank":i(r.get("strict_rank")),
            "source_id":sid,
            "g_mag":f(r.get("g_mag")),
            "refcat":str(r.get("refcat")),
            "gaia_ra_1951_deg":gra,
            "gaia_dec_1951_deg":gdec,
            "official_fit_ra_deg":fra,
            "official_fit_dec_deg":fdec,
            "catalog_identity_preprop_gaia_sep_arcsec":f(r.get("preprop_gaia_sep_arcsec")),
            "official_fit_minus_gaia_east_arcsec":east,
            "official_fit_minus_gaia_north_arcsec":north,
            "official_fit_minus_gaia_sep_arcsec":sep,
            "official_fit_minus_gaia_pa_deg":pa,
            "distance_from_v028q_translation_arcsec":dist_vq,
            "projection_along_v028q_translation_arcsec":proj,
            "closer_to_zero_than_v028q_translation":sep<dist_vq,
            "limiting_mag_local":f(r.get("limiting_mag_local")),
            "magcal_magdep":f(r.get("magcal_magdep")),
            "drad_rms2":f(r.get("drad_rms2")),
            "aflags":r.get("aflags"),
            "bflags":r.get("bflags"),
        })

    atlas=[r for r in rows if r["refcat"]=="atlas"]
    apass=[r for r in rows if r["refcat"]=="apass"]
    if len(atlas)!=8:
        raise RuntimeError(f"expected 8 official ATLAS detections, found {len(atlas)}")

    sat=summary(atlas); sap=summary(apass)

    def model_comparison(rr,su):
        arr=np.array([[r["official_fit_minus_gaia_east_arcsec"],
                       r["official_fit_minus_gaia_north_arcsec"]] for r in rr],float)
        med=np.array([su["median_east_arcsec"],su["median_north_arcsec"]],float)
        d=np.linalg.norm(arr-vqv,axis=1)
        proj=arr@u
        return {
            "v028q_translation_east_arcsec":float(vqv[0]),
            "v028q_translation_north_arcsec":float(vqv[1]),
            "v028q_translation_magnitude_arcsec":vqmag,
            "official_median_to_v028q_vector_difference_arcsec":
                float(np.linalg.norm(med-vqv)),
            "median_individual_distance_from_v028q_arcsec":float(np.median(d)),
            "minimum_individual_distance_from_v028q_arcsec":float(np.min(d)),
            "median_projection_along_v028q_direction_arcsec":float(np.median(proj)),
            "all_official_vectors_closer_to_zero_than_to_v028q":
                bool(all(r["closer_to_zero_than_v028q_translation"] for r in rr)),
        }

    catlas=model_comparison(atlas,sat)
    capass=model_comparison(apass,sap) if apass else None

    # Cross-refcat reproducibility for the five sources detected in both.
    amap={r["source_id"]:r for r in atlas}
    pmap={r["source_id"]:r for r in apass}
    shared=sorted(set(amap)&set(pmap))
    cross=[]
    for sid in shared:
        a=amap[sid]; p=pmap[sid]
        de=p["official_fit_minus_gaia_east_arcsec"]-a["official_fit_minus_gaia_east_arcsec"]
        dn=p["official_fit_minus_gaia_north_arcsec"]-a["official_fit_minus_gaia_north_arcsec"]
        cross.append({
            "source_id":sid,
            "strict_rank":a["strict_rank"],
            "apass_minus_atlas_east_arcsec":de,
            "apass_minus_atlas_north_arcsec":dn,
            "apass_atlas_fitted_position_separation_arcsec":math.hypot(de,dn),
        })

    cross_sep=[r["apass_atlas_fitted_position_separation_arcsec"] for r in cross]
    cross_summary={
        "shared_detection_count":len(cross),
        "median_fitted_position_difference_arcsec":
            float(np.median(cross_sep)) if cross_sep else None,
        "max_fitted_position_difference_arcsec":
            float(np.max(cross_sep)) if cross_sep else None,
    }

    # Conservative adjudication:
    # complete official ATLAS set, weak directional concentration, official
    # median far from v028q, and every official vector is closer to zero than
    # to the v028q translation.
    status=(
        "OFFICIAL_DR7_DISAGREES_WITH_V028Q_PIXEL_OFFSET"
        if (
            len(atlas)==8
            and sat["circular_R"] < 0.5
            and catlas["official_median_to_v028q_vector_difference_arcsec"] > 10.0
            and catlas["all_official_vectors_closer_to_zero_than_to_v028q"]
        )
        else "OFFICIAL_DR7_V028Q_COMPARISON_UNRESOLVED"
    )

    print("Official DR7 fitted-position summaries:")
    print(
        f"  ATLAS N={sat['count']} median=({sat['median_east_arcsec']:+.3f},"
        f"{sat['median_north_arcsec']:+.3f})\" "
        f"mag={sat['median_vector_magnitude_arcsec']:.3f}\" "
        f"R={sat['circular_R']:.3f}"
    )
    if sap:
        print(
            f"  APASS N={sap['count']} median=({sap['median_east_arcsec']:+.3f},"
            f"{sap['median_north_arcsec']:+.3f})\" "
            f"mag={sap['median_vector_magnitude_arcsec']:.3f}\" "
            f"R={sap['circular_R']:.3f}"
        )
    print()
    print(f"v028q translation=({vqv[0]:+.3f},{vqv[1]:+.3f})\" mag={vqmag:.3f}\"")
    print(
        f"ATLAS median↔v028q vector difference="
        f"{catlas['official_median_to_v028q_vector_difference_arcsec']:.3f}\""
    )
    print(
        f"ATLAS median individual distance from v028q="
        f"{catlas['median_individual_distance_from_v028q_arcsec']:.3f}\""
    )
    print(
        f"ATLAS median projection along v028q direction="
        f"{catlas['median_projection_along_v028q_direction_arcsec']:.3f}\" "
        f"(v028q expects {vqmag:.3f}\")"
    )
    print(
        f"All 8 official ATLAS vectors closer to zero than v028q: "
        f"{catlas['all_official_vectors_closer_to_zero_than_to_v028q']}"
    )
    print()
    print(
        f"ATLAS/APASS shared detections={cross_summary['shared_detection_count']} "
        f"median/max fitted-position difference="
        f"{cross_summary['median_fitted_position_difference_arcsec']:.3f}/"
        f"{cross_summary['max_fitted_position_difference_arcsec']:.3f}\""
    )
    print()
    print(f"ADJUDICATION: {status}")

    fields=[
        "strict_rank","source_id","g_mag","refcat",
        "gaia_ra_1951_deg","gaia_dec_1951_deg",
        "official_fit_ra_deg","official_fit_dec_deg",
        "catalog_identity_preprop_gaia_sep_arcsec",
        "official_fit_minus_gaia_east_arcsec",
        "official_fit_minus_gaia_north_arcsec",
        "official_fit_minus_gaia_sep_arcsec",
        "official_fit_minus_gaia_pa_deg",
        "distance_from_v028q_translation_arcsec",
        "projection_along_v028q_translation_arcsec",
        "closer_to_zero_than_v028q_translation",
        "limiting_mag_local","magcal_magdep","drad_rms2","aflags","bflags"
    ]
    write_csv(OUT_CSV,rows,fields)

    payload={
        "stage":"ORDER01_OFFICIAL_DR7_FITTED_POSITION_ADJUDICATION_V028U",
        "status":status,
        "frozen_active_ranks":EXPECTED,
        "guards":{
            "network_access":False,
            "science_pixels_read":False,
            "candidate_pixels_used_as_reference_fit":False,
            "transient_detector_rerun":False,
            "transient_detector_parameters_changed":False,
            "candidate_state_mutation":False,
            "candidate_promotion":False,
            "candidate_deletion":False,
            "weighted_candidate_score":False,
        },
        "official_detection_count_total":len(rows),
        "atlas_summary":sat,
        "apass_summary":sap,
        "atlas_comparison_to_v028q":catlas,
        "apass_comparison_to_v028q":capass,
        "atlas_apass_crosscheck":cross_summary,
        "atlas_apass_shared_rows":cross,
        "rows":rows,
        "interpretive_boundary":(
            "The official DR7 fitted source positions are tied to catalog "
            "identities selected independently by querycat agreement with "
            "Gaia propagated to the 1951 epoch. The complete ATLAS set therefore "
            "provides an external test of the coherent v028q raw-pixel offset. "
            "A disagreement invalidates that offset as evidence for a physical "
            "plate-registration displacement, but does not itself classify any "
            "science candidate or alter frozen candidate state."
        )
    }
    write_json(OUT_JSON,payload)

    md=[
        "# ORDER 01 — Official DR7 Fitted-Position Adjudication of v028q v028u","",
        "## Guard state","",
        "- No network access.",
        "- Science pixels were not read.",
        "- The transient detector was not rerun.",
        "- No candidate state was changed.","",
        "## Official DR7 astrometry","",
        f"- ATLAS detections: **{sat['count']}**.",
        f"- ATLAS median fitted−Gaia vector: "
        f"**({sat['median_east_arcsec']:+.3f}, {sat['median_north_arcsec']:+.3f}) arcsec**, "
        f"magnitude **{sat['median_vector_magnitude_arcsec']:.3f} arcsec**.",
        f"- ATLAS directional concentration R: **{sat['circular_R']:.3f}**.",
    ]
    if sap:
        md += [
            f"- APASS detections: **{sap['count']}**.",
            f"- APASS median fitted−Gaia vector: "
            f"**({sap['median_east_arcsec']:+.3f}, {sap['median_north_arcsec']:+.3f}) arcsec**, "
            f"magnitude **{sap['median_vector_magnitude_arcsec']:.3f} arcsec**.",
            f"- APASS directional concentration R: **{sap['circular_R']:.3f}**.",
        ]
    md += ["","## Comparison with v028q","",
        f"- v028q translation: **({vqv[0]:+.3f}, {vqv[1]:+.3f}) arcsec**, "
        f"magnitude **{vqmag:.3f} arcsec**.",
        f"- ATLAS official median differs from v028q by "
        f"**{catlas['official_median_to_v028q_vector_difference_arcsec']:.3f} arcsec**.",
        f"- Median individual ATLAS distance from the v028q vector: "
        f"**{catlas['median_individual_distance_from_v028q_arcsec']:.3f} arcsec**.",
        f"- All eight ATLAS vectors are closer to zero offset than to the v028q "
        f"translation: **{catlas['all_official_vectors_closer_to_zero_than_to_v028q']}**.",
        f"- ATLAS/APASS shared detections: **{cross_summary['shared_detection_count']}**; "
        f"median/max fitted-position disagreement "
        f"**{cross_summary['median_fitted_position_difference_arcsec']:.3f}/"
        f"{cross_summary['max_fitted_position_difference_arcsec']:.3f} arcsec**.","",
        "## Adjudication","",
        f"`{status}`","",
        "## Interpretation boundary","",
        payload["interpretive_boundary"],
    ]
    OUT_MD.write_text("\n".join(md),encoding="utf-8")

    print("\nOutputs:")
    print(f"  {OUT_JSON}")
    print(f"  {OUT_CSV}")
    print(f"  {OUT_MD}")
    print()
    print("NO network query was made.")
    print("SCIENCE PIXELS WERE NOT READ.")
    print("Transient detector was NOT rerun.")
    print("No candidate was promoted or deleted.")
    return 0


if __name__=="__main__":
    raise SystemExit(main())
