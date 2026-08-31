#!/usr/bin/env python3
"""
ORDER 01 — formal POSS-endpoint disposition freeze v028ab

Purpose
-------
Apply the first explicit candidate-state mutation since the post-1024 freeze,
using the completed physical-image / neighbour-star / detector-satellite
adjudications.

This stage DOES NOT delete any historical evidence or candidate rows.
It creates a new additive disposition ledger.

Retirement rule A — neighbour-star detector satellite
------------------------------------------------------
Retire a two-observatory pair from the ACTIVE_UNRESOLVED set when:
  1. v028y says the POSS science coordinate has no centred positive point source
     and broad positive flux is attributable to a neighbouring Gaia source; AND
  2. v028aa adjudicates the frozen negative-polarity POSS detection as either
       NEIGHBOUR_STAR_NEGATIVE_SATELLITE_MECHANISM_STRONGLY_SUPPORTED
     or
       NEIGHBOUR_STAR_NEGATIVE_SATELLITE_MECHANISM_SUPPORTED_PLATEWIDE.

Retirement rule B — centred negative deficit
---------------------------------------------
Retire when:
  1. v028y adjudicates
       CENTERED_NEGATIVE_DEFICIT_NO_LOCAL_POSITIVE_SOURCE_COUNTERPART
  2. science signed aperture r=7 <= -3 sigma;
  3. negative trough <=2 px from the science coordinate;
  4. guarded local joint blank tail <=0.05.

The disposition applies to the TWO-OBSERVATORY TRANSIENT PAIR because the POSS
endpoint is no longer a viable added-light point source. The DASCH endpoint is
preserved as an unresolved independent/single-plate detection.

Expected outcome from frozen v028aa/v028y:
  retire: #10, #25, #26, #29
  remain active unresolved: #24, #30

No network access.
SCIENCE PIXELS ARE NOT READ.
Frozen transient detector is NOT rerun.
Candidate state mutation: TRUE (explicit, additive ledger only).
No evidence files are deleted or overwritten.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

ROOT = Path.cwd()
BASE = ROOT / "results" / "order01_native_full_v028"

V028AA = BASE / "order01_poss_platewide_detector_satellite_adjudication_v028aa.json"
V028Y = BASE / "order01_poss_science_centered_counterpart_adjudication_v028y.json"
V028W = BASE / "order01_poss_signal_matched_and_blank_controls_v028w.json"
STRICT = BASE / "order01_strict_match_triage_v028.csv"

OUT_JSON = BASE / "order01_candidate_disposition_freeze_v028ab.json"
OUT_CSV = BASE / "order01_candidate_disposition_freeze_v028ab.csv"
OUT_MD = BASE / "ORDER01_CANDIDATE_DISPOSITION_FREEZE_V028AB.md"

FROZEN_PREVIOUS = [10,24,25,26,29,30]
EXPECTED_RETIRED = [10,25,26,29]
EXPECTED_ACTIVE = [24,30]

RULE_A_ALLOWED = {
    "NEIGHBOUR_STAR_NEGATIVE_SATELLITE_MECHANISM_STRONGLY_SUPPORTED":
        "STRONG",
    "NEIGHBOUR_STAR_NEGATIVE_SATELLITE_MECHANISM_SUPPORTED_PLATEWIDE":
        "MODERATE_TO_STRONG",
}
Y_NEIGHBOUR = "BROAD_POSITIVE_FLUX_ATTRIBUTED_TO_NEIGHBOUR;_NO_CENTERED_POINT_SOURCE"
Y_NEGATIVE = "CENTERED_NEGATIVE_DEFICIT_NO_LOCAL_POSITIVE_SOURCE_COUNTERPART"

NEG_AP7_MAX = -3.0
NEG_TROUGH_MAX_PX = 2.0
NEG_JOINT_BLANK_MAX = 0.05


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
        return float(str(v).strip())
    except Exception:
        return default


def i(v,default=None):
    try:
        if v is None or str(v).strip()=="":
            return default
        return int(float(str(v).strip()))
    except Exception:
        return default


def main():
    print("="*128)
    print("ORDER 01 — FORMAL POSS-ENDPOINT DISPOSITION FREEZE v028ab")
    print("="*128)
    print("NO NETWORK ACCESS.")
    print("SCIENCE PIXELS ARE NOT READ.")
    print("Frozen transient detector is NOT rerun.")
    print("CANDIDATE STATE MUTATION: TRUE — additive disposition ledger only.\n")

    for p in (V028AA,V028Y,V028W,STRICT):
        if not p.is_file():
            print(f"FAIL missing input: {p}")
            return 2

    aa=json.loads(V028AA.read_text(encoding="utf-8"))
    yy=json.loads(V028Y.read_text(encoding="utf-8"))
    ww=json.loads(V028W.read_text(encoding="utf-8"))

    for name,obj in (("v028aa",aa),("v028y",yy),("v028w",ww)):
        if obj.get("frozen_active_ranks") != FROZEN_PREVIOUS:
            raise RuntimeError(f"{name}: frozen-rank guard mismatch")

    if aa.get("guards",{}).get("candidate_state_mutation") is not False:
        raise RuntimeError("v028aa state guard mismatch")
    if yy.get("guards",{}).get("candidate_state_mutation") is not False:
        raise RuntimeError("v028y state guard mismatch")
    if ww.get("guards",{}).get("candidate_state_mutation") is not False:
        raise RuntimeError("v028w state guard mismatch")

    ares={int(r["strict_rank"]):r for r in aa["results"]}
    yres={int(r["strict_rank"]):r for r in yy["results"]}
    wres={int(r["strict_rank"]):r for r in ww["results"]}

    strict_rows=read_csv(STRICT)
    strict={i(r["strict_rank"]):r for r in strict_rows
            if i(r["strict_rank"]) in FROZEN_PREVIOUS}
    if sorted(strict)!=FROZEN_PREVIOUS:
        raise RuntimeError("strict candidate guard mismatch")

    rows=[]
    retired=[]
    active=[]

    for rank in FROZEN_PREVIOUS:
        a=ares[rank]; y=yres[rank]; w=wres[rank]
        aadj=str(a.get("adjudication") or "")
        yadj=str(y.get("adjudication") or "")

        rule=None
        evidence_strength=None
        poss_endpoint_disposition=None
        pair_disposition=None
        rationale=None

        # Rule A
        if yadj == Y_NEIGHBOUR and aadj in RULE_A_ALLOWED:
            rule="A_NEIGHBOUR_STAR_NEGATIVE_DETECTOR_SATELLITE"
            evidence_strength=RULE_A_ALLOWED[aadj]
            poss_endpoint_disposition=(
                "ADJUDICATED_NON_ASTROPHYSICAL_NEIGHBOUR_STAR_DETECTOR_SATELLITE"
            )
            pair_disposition=(
                "RETIRED_FROM_ACTIVE_TWO_OBSERVATORY_TRANSIENT_SET_DUE_TO_POSS_ENDPOINT"
            )
            rationale=(
                "POSS science coordinate lacks a centred positive point source; "
                "broad positive flux is independently attributed to a displaced "
                "Gaia source; frozen POSS detection has negative polarity and "
                "falls in the ordinary-star negative detector-satellite geometry "
                "on the same physical plate."
            )

        # Rule B
        elif (
            yadj == Y_NEGATIVE
            and f(y.get("science_ap7_signed_z")) is not None
            and f(y.get("science_ap7_signed_z")) <= NEG_AP7_MAX
            and f(y.get("science_negative_trough_offset_px_v028w")) is not None
            and f(y.get("science_negative_trough_offset_px_v028w")) <= NEG_TROUGH_MAX_PX
            and f(y.get("blank_joint_negative_tail_p_v028x")) is not None
            and f(y.get("blank_joint_negative_tail_p_v028x")) <= NEG_JOINT_BLANK_MAX
        ):
            rule="B_CENTERED_NEGATIVE_DEFICIT"
            evidence_strength="STRONG_DESCRIPTIVE"
            poss_endpoint_disposition=(
                "ADJUDICATED_NON_ASTROPHYSICAL_CENTERED_NEGATIVE_DEFICIT"
            )
            pair_disposition=(
                "RETIRED_FROM_ACTIVE_TWO_OBSERVATORY_TRANSIENT_SET_DUE_TO_POSS_ENDPOINT"
            )
            rationale=(
                "POSS endpoint is a centred negative physical deficit rather than "
                "an added-light point source; no Gaia or positive-polarity native "
                "counterpart is present locally; the guarded local joint depth/"
                "centring blank diagnostic is <=0.05."
            )

        else:
            rule="NO_RETIREMENT_RULE_SATISFIED"
            evidence_strength="UNRESOLVED"
            poss_endpoint_disposition="ACTIVE_UNRESOLVED_POSS_ENDPOINT"
            pair_disposition="ACTIVE_UNRESOLVED_TWO_OBSERVATORY_PAIR"
            rationale=(
                "Current physical/morphological/mechanism evidence is insufficient "
                "for explicit endpoint retirement under the frozen v028ab rules."
            )

        is_retired=pair_disposition.startswith("RETIRED_")
        if is_retired:
            retired.append(rank)
            dasch_status="PRESERVED_UNRESOLVED_SINGLE_PLATE_ENDPOINT"
        else:
            active.append(rank)
            dasch_status="ACTIVE_AS_PART_OF_UNRESOLVED_PAIR"

        sr=strict[rank]
        row={
            "strict_rank":rank,
            "previous_pair_state":"ACTIVE_UNRESOLVED_BRANCH_A_AFTER_1024",
            "new_pair_disposition":pair_disposition,
            "poss_endpoint_disposition":poss_endpoint_disposition,
            "dasch_endpoint_disposition":dasch_status,
            "disposition_rule":rule,
            "evidence_strength":evidence_strength,
            "rationale":rationale,

            "v028aa_adjudication":aadj,
            "v028aa_science_native_polarity":i(a.get("science_native_polarity")),
            "v028aa_science_native_snr":f(a.get("science_native_snr")),
            "v028aa_neighbor_gaia_source_id":a.get("identified_neighbor_gaia_source_id"),
            "v028aa_neighbor_gaia_g_mag":f(a.get("identified_neighbor_gaia_g_mag")),
            "v028aa_science_to_neighbor_radius_px":f(a.get("science_to_neighbor_radius_px")),
            "v028aa_radius_percentile_platewide":f(a.get("science_radius_percentile_platewide")),
            "v028aa_snr_percentile_platewide":f(a.get("science_snr_percentile_platewide")),
            "v028aa_controls_within_3px_radius":i(a.get("unique_platewide_controls_within_3px_radius")),

            "v028y_adjudication":yadj,
            "v028y_ap7_signed_z":f(y.get("science_ap7_signed_z")),
            "v028y_negative_trough_offset_px":f(y.get("science_negative_trough_offset_px_v028w")),
            "v028y_joint_blank_negative_tail":f(y.get("blank_joint_negative_tail_p_v028x")),
            "v028y_science_nearest_gaia_px":f(y.get("science_nearest_gaia_distance_px")),
            "v028y_science_nearest_positive_native_px":
                f(y.get("science_nearest_positive_native_distance_px")),

            "v028w_centered_positive_core_ge3sigma":
                bool(w.get("centered_positive_core_ge3sigma")),
            "v028w_positive_peak_offset_px":
                f(w.get("science_positive_peak_offset_px")),
            "v028w_positive_centroid_offset_px":
                f(w.get("science_positive_centroid_offset_px")),

            "poss_ra_deg":f(sr.get("poss_ra_deg")),
            "poss_dec_deg":f(sr.get("poss_dec_deg")),
            "dasch_ra_deg":f(sr.get("dasch_ra_deg")),
            "dasch_dec_deg":f(sr.get("dasch_dec_deg")),
            "pair_sep_arcsec":f(sr.get("sep_arcsec")),
        }
        rows.append(row)

        print(f"#{rank}: {rule}")
        print(f"     POSS: {poss_endpoint_disposition}")
        print(f"     PAIR: {pair_disposition}")
        print(f"     DASCH: {dasch_status}")

    if retired != EXPECTED_RETIRED:
        raise RuntimeError(
            f"REFUSING TO FREEZE: retired set {retired} != expected {EXPECTED_RETIRED}"
        )
    if active != EXPECTED_ACTIVE:
        raise RuntimeError(
            f"REFUSING TO FREEZE: active set {active} != expected {EXPECTED_ACTIVE}"
        )

    fields=[
        "strict_rank","previous_pair_state","new_pair_disposition",
        "poss_endpoint_disposition","dasch_endpoint_disposition",
        "disposition_rule","evidence_strength","rationale",
        "v028aa_adjudication","v028aa_science_native_polarity",
        "v028aa_science_native_snr","v028aa_neighbor_gaia_source_id",
        "v028aa_neighbor_gaia_g_mag","v028aa_science_to_neighbor_radius_px",
        "v028aa_radius_percentile_platewide","v028aa_snr_percentile_platewide",
        "v028aa_controls_within_3px_radius",
        "v028y_adjudication","v028y_ap7_signed_z",
        "v028y_negative_trough_offset_px","v028y_joint_blank_negative_tail",
        "v028y_science_nearest_gaia_px","v028y_science_nearest_positive_native_px",
        "v028w_centered_positive_core_ge3sigma","v028w_positive_peak_offset_px",
        "v028w_positive_centroid_offset_px",
        "poss_ra_deg","poss_dec_deg","dasch_ra_deg","dasch_dec_deg","pair_sep_arcsec"
    ]
    write_csv(OUT_CSV,rows,fields)

    payload={
        "stage":"ORDER01_CANDIDATE_DISPOSITION_FREEZE_V028AB",
        "previous_active_unresolved":FROZEN_PREVIOUS,
        "retired_from_active_two_observatory_set":retired,
        "new_active_unresolved_two_observatory_set":active,
        "guards":{
            "network_access":False,
            "science_pixels_read":False,
            "transient_detector_rerun":False,
            "transient_detector_parameters_changed":False,
            "candidate_state_mutation":True,
            "mutation_type":"ADDITIVE_DISPOSITION_LEDGER_ONLY",
            "historical_evidence_deleted":False,
            "historical_evidence_overwritten":False,
            "dasch_endpoints_deleted":False,
            "weighted_candidate_score":False,
        },
        "frozen_rules":{
            "rule_A_neighbor_star_satellite":{
                "required_v028y":Y_NEIGHBOUR,
                "allowed_v028aa":sorted(RULE_A_ALLOWED),
            },
            "rule_B_centered_negative_deficit":{
                "required_v028y":Y_NEGATIVE,
                "ap7_signed_z_max":NEG_AP7_MAX,
                "negative_trough_offset_px_max":NEG_TROUGH_MAX_PX,
                "joint_blank_tail_max":NEG_JOINT_BLANK_MAX,
            },
        },
        "rows":rows,
        "interpretive_boundary":(
            "Retirement means the candidate no longer qualifies as an active "
            "two-observatory added-light transient because its POSS endpoint has "
            "been adjudicated non-astrophysical under the frozen physical-image "
            "rules. It is not deletion: all historical records remain preserved, "
            "and each DASCH endpoint remains available for independent single-plate "
            "analysis. #24 and #30 remain active unresolved pairs."
        )
    }
    write_json(OUT_JSON,payload)

    md=[
        "# ORDER 01 — Candidate Disposition Freeze v028ab","",
        "## State mutation","",
        "**This stage explicitly changes the active two-observatory candidate set.**",
        "",
        "- Mutation is additive only; no historical evidence is overwritten or deleted.",
        "- Science pixels were not read.",
        "- The frozen transient detector was not rerun.",
        "- DASCH endpoints belonging to retired pairs remain preserved for independent analysis.",
        "",
        "## New frozen state","",
        f"- Previous active unresolved: **{FROZEN_PREVIOUS}**",
        f"- Retired from active two-observatory set: **{retired}**",
        f"- Active unresolved two-observatory set: **{active}**","",
        "## Dispositions","",
        "| rank | POSS endpoint | pair | evidence | rule |",
        "|---:|---|---|---|---|"
    ]
    for r in rows:
        md.append(
            f"| #{r['strict_rank']} | `{r['poss_endpoint_disposition']}` | "
            f"`{r['new_pair_disposition']}` | `{r['evidence_strength']}` | "
            f"`{r['disposition_rule']}` |"
        )
    md += ["","## Interpretation boundary","",payload["interpretive_boundary"]]
    OUT_MD.write_text("\n".join(md),encoding="utf-8")

    print("\n" + "="*128)
    print("DISPOSITION FREEZE PASSED")
    print(f"  retired: {retired}")
    print(f"  active unresolved: {active}")
    print()
    print("Outputs:")
    print(f"  {OUT_JSON}")
    print(f"  {OUT_CSV}")
    print(f"  {OUT_MD}")
    print()
    print("NO network query was made.")
    print("SCIENCE PIXELS WERE NOT READ.")
    print("Transient detector was NOT rerun.")
    print("CANDIDATE STATE WAS MUTATED by additive disposition ledger.")
    print("No historical candidate/evidence row was deleted.")
    return 0


if __name__=="__main__":
    raise SystemExit(main())
