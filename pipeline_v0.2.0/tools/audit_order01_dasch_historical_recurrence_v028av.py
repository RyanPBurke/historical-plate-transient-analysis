#!/usr/bin/env python3
"""
ORDER 01 — historical close-hit recurrence reclassification v028av

Purpose
-------
v028au established that the old v028i flags belong to historical close hits on
OTHER plates, not to the 1951 ai43437 science features.

This stage reclassifies those historical hits explicitly. The question is:
does a close historical hit represent independent recurrence at the science
coordinate, or is it an astrometric tail measurement of a persistent reference
source whose normal locus lies elsewhere?

Inputs
------
- v028h historical close-hit geometry
- v028i historical-hit flag audit
- v028as stellar-shape summary for the 1951 ai43437 endpoints

No network access.
SCIENCE PIXELS ARE NOT READ.
Frozen detector is NOT rerun.
No endpoint state mutation.

Classification logic is deliberately conservative:
- Persistent reference histories (>=20 unique plate detections) whose selected
  close hit lies at >=95th percentile distance from that reference source's
  normal fitted-position locus are NOT accepted as recurrence at the target.
- Sparse reference histories with direct blend/defect/association warnings are
  NOT accepted as recurrence.
- Anything else remains unresolved rather than promoted.
"""

from __future__ import annotations

import csv
import json
import math
from pathlib import Path

ROOT = Path.cwd()
BASE = ROOT / "results" / "order01_native_full_v028"

CLOSURE = BASE / "order01_candidate24_final_disposition_and_closure_v028ag.json"
V028H = BASE / "order01_historical_closehit_geometry_v028h.json"
V028I = BASE / "order01_historical_closehit_flag_audit_v028i.json"
V028AS = BASE / "order01_dasch_stellar_shape_v028as.json"

OUT_JSON = BASE / "order01_dasch_historical_recurrence_reclassification_v028av.json"
OUT_CSV = BASE / "order01_dasch_historical_recurrence_reclassification_v028av.csv"
OUT_MD = BASE / "ORDER01_DASCH_HISTORICAL_RECURRENCE_RECLASSIFICATION_V028AV.md"

RANKS = [10,24,25,26,29,30]
PERSISTENT_MIN_DETECTIONS = 20
EXTREME_LOCUS_PERCENTILE = 0.95


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


def result_map(obj):
    out={}
    for r in obj.get("results",[]):
        if not isinstance(r,dict):continue
        rank=i(r.get("strict_rank"))
        if rank in RANKS:
            out[rank]=r
    return out


def science_map(obj):
    out={}
    for r in obj.get("summaries",[]):
        if not isinstance(r,dict):continue
        rank=i(r.get("strict_rank"))
        if rank in RANKS:
            out[rank]=r
    return out


def warning_names(r):
    if not r:return []
    names=[]
    for key in (
        "direct_association_warning_names",
        "photometric_quality_warning_names",
        "aflags_names",
        "bflags_names",
    ):
        v=r.get(key)
        if isinstance(v,list):
            names.extend(str(x) for x in v)
        elif isinstance(v,str):
            names.extend(x for x in v.split(";") if x)
    # dedup
    seen=set();out=[]
    for x in names:
        if x not in seen:
            seen.add(x);out.append(x)
    return out


def main():
    print("="*128)
    print("ORDER 01 — HISTORICAL CLOSE-HIT RECURRENCE RECLASSIFICATION v028av")
    print("="*128)
    print("NO NETWORK ACCESS.")
    print("SCIENCE PIXELS ARE NOT READ.")
    print("Frozen transient detector is NOT rerun.\n")

    for p in (CLOSURE,V028H,V028I,V028AS):
        if not p.is_file():
            print(f"FAIL missing input: {p}")
            return 2

    closure=json.loads(CLOSURE.read_text(encoding="utf-8"))
    if closure.get("new_active_unresolved_two_observatory_set")!=[]:
        raise RuntimeError("Order-01 closure guard mismatch")

    h=result_map(json.loads(V028H.read_text(encoding="utf-8")))
    irows=result_map(json.loads(V028I.read_text(encoding="utf-8")))
    smap=science_map(json.loads(V028AS.read_text(encoding="utf-8")))

    rows=[]

    print("Per-rank recurrence interpretation:\n")

    for rank in RANKS:
        hr=h.get(rank)
        ir=irows.get(rank)
        sr=smap.get(rank)

        if sr is None:
            raise RuntimeError(f"#{rank}: missing v028as science summary")

        if hr is None:
            classification="NO_ACCEPTED_HISTORICAL_CLOSE_HIT"
            rationale=(
                "No v028h historical close-hit result is present for this rank; "
                "there is no historical recurrence evidence to promote."
            )
            rec={
                "strict_rank":rank,
                "ai43437_shape_classification":sr.get("shape_classification"),
                "historical_hit_present":False,
                "historical_hit_plate_id":None,
                "historical_hit_expdate":None,
                "historical_hit_sep_target_arcsec":None,
                "reference_number":None,
                "reference_unique_plate_detections":None,
                "reference_history_sampling":None,
                "reference_median_locus_distance_arcsec":None,
                "hit_distance_from_reference_locus_arcsec":None,
                "hit_reference_locus_percentile":None,
                "hit_reference_locus_upper_fraction":None,
                "hit_limit_minus_source_mag":None,
                "historical_hit_warning_names":"",
                "historical_hit_flag_label":None,
                "recurrence_classification":classification,
                "recurrence_accepted":False,
                "rationale":rationale,
            }
        else:
            nref=i(hr.get("reference_unique_plate_detections"),0) or 0
            percentile=f(hr.get("hit_reference_locus_residual_empirical_percentile"))
            upper=f(hr.get("hit_reference_locus_residual_empirical_upper_fraction"))
            sep=f(hr.get("hit_sep_target_arcsec"))
            locus=f(hr.get("hit_distance_from_median_reference_locus_arcsec"))
            median_locus=f(hr.get("reference_median_locus_distance_arcsec"))
            warnings=warning_names(ir)
            flag_label=None if ir is None else ir.get("historical_hit_flag_label")

            persistent=nref>=PERSISTENT_MIN_DETECTIONS
            extreme=(percentile is not None and percentile>=EXTREME_LOCUS_PERCENTILE)
            direct_bad=any(x in warnings for x in (
                "SUSPECTED_DEFECT","SXT_BLEND","BLEND","NEIGHBORS",
                "LARGE_DRAD","REJECTED_BLEND","CASE_B_BLEND",
                "CASE_C_BLEND","CASE_BC_BLEND",
            ))
            sparse=not persistent

            if persistent and extreme:
                classification="PERSISTENT_REFERENCE_SOURCE_ASTROMETRIC_OUTLIER_NOT_RECURRENCE"
                rationale=(
                    f"The close hit belongs to reference source {hr.get('reference_number')} "
                    f"with {nref} detections across distinct plates. Its selected close-hit "
                    f"position is at the {percentile:.3f} empirical percentile of distance "
                    f"from that source's normal fitted-position locus. This is treated as "
                    f"an astrometric-tail measurement of a persistent source, not an "
                    f"independent recurrence at the ai43437 science coordinate."
                )
                accepted=False
            elif sparse and direct_bad:
                classification="SPARSE_WARNING_BEARING_REFERENCE_HIT_NOT_RECURRENCE"
                rationale=(
                    f"The reference history contains only {nref} plate detections and the "
                    f"selected close hit carries direct association/defect/blend warnings "
                    f"({';'.join(warnings)}). It is not accepted as independent recurrence."
                )
                accepted=False
            else:
                classification="HISTORICAL_CLOSE_HIT_UNRESOLVED_NOT_PROMOTED"
                rationale=(
                    "The historical close hit is insufficiently clean to establish "
                    "independent recurrence. It remains descriptive evidence only."
                )
                accepted=False

            rec={
                "strict_rank":rank,
                "ai43437_shape_classification":sr.get("shape_classification"),
                "historical_hit_present":True,
                "historical_hit_plate_id":hr.get("hit_plate_id"),
                "historical_hit_expdate":hr.get("hit_expdate"),
                "historical_hit_sep_target_arcsec":sep,
                "reference_number":hr.get("reference_number"),
                "reference_unique_plate_detections":nref,
                "reference_history_sampling":hr.get("reference_history_sampling"),
                "reference_median_locus_distance_arcsec":median_locus,
                "hit_distance_from_reference_locus_arcsec":locus,
                "hit_reference_locus_percentile":percentile,
                "hit_reference_locus_upper_fraction":upper,
                "hit_limit_minus_source_mag":f(hr.get("hit_limit_minus_source_mag")),
                "historical_hit_warning_names":";".join(warnings),
                "historical_hit_flag_label":flag_label,
                "recurrence_classification":classification,
                "recurrence_accepted":accepted,
                "rationale":rationale,
            }

        rows.append(rec)
        print(f"#{rank}: {rec['recurrence_classification']}")
        if rec["historical_hit_present"]:
            print(
                f"    plate={rec['historical_hit_plate_id']} "
                f"date={rec['historical_hit_expdate']} "
                f"targetSep={rec['historical_hit_sep_target_arcsec']:.3f}\" "
                f"refDetections={rec['reference_unique_plate_detections']} "
                f"locusPct={rec['hit_reference_locus_percentile']}"
            )
        print(f"    {rec['rationale']}\n")

    accepted=[r["strict_rank"] for r in rows if r["recurrence_accepted"]]

    payload={
        "stage":"ORDER01_DASCH_HISTORICAL_CLOSEHIT_RECURRENCE_RECLASSIFICATION_V028AV",
        "ranks":RANKS,
        "guards":{
            "network_access":False,
            "science_pixels_read":False,
            "transient_detector_rerun":False,
            "candidate_state_mutation":False,
            "historical_hit_flags_apply_only_to_historical_hit_plate":True,
            "historical_hit_flags_not_applied_to_ai43437_science_endpoint":True,
            "persistent_reference_history_threshold":PERSISTENT_MIN_DETECTIONS,
            "extreme_reference_locus_percentile_threshold":EXTREME_LOCUS_PERCENTILE,
        },
        "results":rows,
        "accepted_historical_recurrence_ranks":accepted,
        "interpretive_boundary":(
            "v028av separates the 1951 ai43437 science image from historical "
            "reference-source close hits. A one-off positional excursion from a "
            "persistent catalog/reference source is not independent recurrence at "
            "the science coordinate. No historical hit is promoted unless it "
            "survives this distinction and its own quality metadata."
        )
    }

    write_json(OUT_JSON,payload)
    write_csv(OUT_CSV,rows,list(rows[0]))

    md=[
        "# ORDER 01 — Historical Close-Hit Recurrence Reclassification v028av","",
        "## Guard state","",
        "- No network access.",
        "- Science pixels were not read.",
        "- The frozen detector was not rerun.",
        "- No endpoint state was changed.",
        "- v028i flags are attached only to their historical hit plates, not to ai43437.","",
        f"Accepted independent historical recurrences: **{len(accepted)}**.","",
        "## Results","",
        "| rank | historical plate | ref detections | target sep | locus percentile | classification |",
        "|---:|---|---:|---:|---:|---|"
    ]
    for r in rows:
        sep=r["historical_hit_sep_target_arcsec"]
        pct=r["hit_reference_locus_percentile"]
        md.append(
            f"| #{r['strict_rank']} | {r['historical_hit_plate_id'] or '—'} | "
            f"{r['reference_unique_plate_detections'] if r['reference_unique_plate_detections'] is not None else '—'} | "
            f"{'—' if sep is None else f'{sep:.3f}″'} | "
            f"{'—' if pct is None else f'{pct:.3f}'} | "
            f"{r['recurrence_classification']} |"
        )
    md += ["","## Interpretation boundary","",payload["interpretive_boundary"]]
    OUT_MD.write_text("\n".join(md),encoding="utf-8")

    print("Outputs:")
    print(f"  {OUT_JSON}")
    print(f"  {OUT_CSV}")
    print(f"  {OUT_MD}")
    print()
    print(f"Accepted independent historical recurrences: {accepted}")
    print("NO network query was made.")
    print("SCIENCE PIXELS WERE NOT READ.")
    print("Transient detector was NOT rerun.")
    print("No endpoint state was changed.")
    return 0


if __name__=="__main__":
    raise SystemExit(main())
