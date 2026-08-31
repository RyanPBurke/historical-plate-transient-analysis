#!/usr/bin/env python3
"""
ORDER 01 — final candidate #24 disposition and Order-01 closure freeze v028ag

Purpose
-------
Correct the final interpretive bug in v028af and, if all frozen evidence guards
pass, retire #24 from the active two-observatory transient set.

Critical correction
-------------------
The frozen transient detector defines polarity from the UNSMOOTHED high-pass
residual at the native detector peak. v028af incorrectly set its
`opposite_signed_at_native_positions` flag from an additional Gaussian-smoothed
diagnostic map.

For #24, v028af itself records on one common raw/background model:
  native negative position raw residual Z = -4.5018
  native positive position raw residual Z = +6.5803

Therefore the exact frozen native pair IS physically opposite-signed at detector
scale, even though the broader sigma=2.5 smoothed map is positive at both
locations.

Disposition rule
----------------
Retire #24 only if ALL of the following hold:
  1. v028ad leaves [24] as the sole active unresolved pair;
  2. v028ae confirms tile-aware native geometry and a <=4.5 px positive partner;
  3. v028af raw detector-scale residual at science position <= -3 sigma;
  4. v028af raw detector-scale residual at positive partner >= +3 sigma;
  5. native polarities are -1 / +1;
  6. exact pair separation <=4.0 px;
  7. joint bipolar+cluster morphology is reproduced in matched controls:
       SNR-matched joint <=4.5px + cluster>=8 guarded tail <=0.025
       local-y matched joint <=4.5px + cluster>=8 guarded tail <=0.025
  8. signal-matched physical audit still says no centered positive point source.

The pair is retired because its POSS endpoint now has a concrete reproducible
non-astrophysical detector/plate-structure explanation.

The DASCH endpoint is PRESERVED as an unresolved single-plate detection.

No historical evidence is deleted or overwritten.
No network access.
SCIENCE PIXELS ARE NOT READ.
Frozen transient detector is NOT rerun.
Candidate state mutation: TRUE, additive ledger only.

Expected final active Order-01 two-observatory set: [].
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

ROOT = Path.cwd()
BASE = ROOT / "results" / "order01_native_full_v028"

V028AD = BASE / "order01_candidate30_disposition_freeze_v028ad.json"
V028AE = BASE / "order01_candidate24_left_edge_bipolar_audit_v028ae.json"
V028AF = BASE / "order01_candidate24_joint_bipolar_cluster_rawpair_v028af.json"
V028Y = BASE / "order01_poss_science_centered_counterpart_adjudication_v028y.json"
V028AB = BASE / "order01_candidate_disposition_freeze_v028ab.json"

OUT_JSON = BASE / "order01_candidate24_final_disposition_and_closure_v028ag.json"
OUT_CSV = BASE / "order01_candidate24_final_disposition_v028ag.csv"
OUT_MD = BASE / "ORDER01_FINAL_TWO_OBSERVATORY_DISPOSITION_FREEZE_V028AG.md"

RAW_NEG_MAX = -3.0
RAW_POS_MIN = +3.0
PAIR_MAX_PX = 4.0
JOINT_TAIL_MAX = 0.025
PARTNER_MAX_PX = 4.5


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


def main():
    print("="*128)
    print("ORDER 01 — FINAL CANDIDATE #24 DISPOSITION / TWO-OBSERVATORY CLOSURE FREEZE v028ag")
    print("="*128)
    print("NO NETWORK ACCESS.")
    print("SCIENCE PIXELS ARE NOT READ.")
    print("Frozen transient detector is NOT rerun.")
    print("CANDIDATE STATE MUTATION: TRUE — additive disposition ledger only.\n")

    for p in (V028AD,V028AE,V028AF,V028Y,V028AB):
        if not p.is_file():
            print(f"FAIL missing input: {p}")
            return 2

    ad=json.loads(V028AD.read_text(encoding="utf-8"))
    ae=json.loads(V028AE.read_text(encoding="utf-8"))
    af=json.loads(V028AF.read_text(encoding="utf-8"))
    yy=json.loads(V028Y.read_text(encoding="utf-8"))
    ab=json.loads(V028AB.read_text(encoding="utf-8"))

    if ad.get("new_active_unresolved_two_observatory_set") != [24]:
        raise RuntimeError("v028ad active-set guard mismatch")
    if ae.get("active_unresolved_input") != [24]:
        raise RuntimeError("v028ae active-set guard mismatch")
    if af.get("active_unresolved_input") != [24]:
        raise RuntimeError("v028af active-set guard mismatch")

    science=af["science"]
    raw=af["raw_pair"]
    joints=af["joint_control_summaries"]
    aescience=ae["science"]
    y24={int(r["strict_rank"]):r for r in yy["results"]}[24]

    snr_joint=joints["same_edge_snr_matched"]
    local_joint=joints["same_edge_snr_and_local_y"]

    raw_neg=float(raw["negative_native_raw_residual_z"])
    raw_pos=float(raw["positive_native_raw_residual_z"])
    corrected_opposite_signed=bool(raw_neg < 0 and raw_pos > 0)

    guards={
        "sole_active_input_is_24":
            ad.get("new_active_unresolved_two_observatory_set")==[24],
        "tile_aware_identity":
            bool(ae.get("guards",{}).get("tile_aware_science_identity")),
        "v028ae_mechanism_supported":
            ae.get("adjudication")=="LEFT_EDGE_BIPOLAR_NATIVE_DETECTOR_MECHANISM_SUPPORTED",
        "negative_native_polarity":
            int(aescience.get("polarity"))==-1,
        "positive_partner_distance_le_4p5":
            float(aescience.get("nearest_positive_distance_px"))<=PARTNER_MAX_PX,
        "raw_detector_negative_le_minus3":
            raw_neg<=RAW_NEG_MAX,
        "raw_detector_positive_ge_plus3":
            raw_pos>=RAW_POS_MIN,
        "corrected_raw_detector_opposite_signed":
            corrected_opposite_signed,
        "pair_separation_le_4px":
            float(science.get("pair_separation_px"))<=PAIR_MAX_PX,
        "snr_matched_joint_tail_le_0p025":
            float(snr_joint.get("joint_4p5_guarded_tail"))<=JOINT_TAIL_MAX,
        "local_y_joint_tail_le_0p025":
            float(local_joint.get("joint_4p5_guarded_tail"))<=JOINT_TAIL_MAX,
        "no_centered_positive_point_source":
            y24.get("adjudication")=="NO_CENTERED_POSITIVE_POINT_SOURCE;_POSS_STRUCTURE_WEAK_OR_MIXED",
        "v028af_no_prior_state_mutation":
            af.get("guards",{}).get("candidate_state_mutation") is False,
    }

    print("Corrected detector-scale polarity semantics:")
    print(f"  raw negative position Z = {raw_neg:+.6f}")
    print(f"  raw positive position Z = {raw_pos:+.6f}")
    print(f"  corrected opposite-signed = {corrected_opposite_signed}")
    print("  v028af smoothed-map oppositeSigned=False is superseded for detector-polarity adjudication.\n")

    print("Final evidence guards:")
    for k,v in guards.items():
        print(f"  {k}: {v}")

    if not all(guards.values()):
        failed=[k for k,v in guards.items() if not v]
        raise RuntimeError(f"REFUSING FINAL FREEZE; failed guards: {failed}")

    row={
        "strict_rank":24,
        "previous_pair_state":"ACTIVE_UNRESOLVED_TWO_OBSERVATORY_PAIR",
        "new_pair_disposition":
            "RETIRED_FROM_ACTIVE_TWO_OBSERVATORY_TRANSIENT_SET_DUE_TO_POSS_ENDPOINT",
        "poss_endpoint_disposition":
            "ADJUDICATED_NON_ASTROPHYSICAL_BIPOLAR_LOCAL_DETECTOR_PLATE_STRUCTURE",
        "dasch_endpoint_disposition":
            "PRESERVED_UNRESOLVED_SINGLE_PLATE_ENDPOINT",
        "disposition_rule":
            "D_RAW_DETECTOR_SCALE_BIPOLAR_PAIR_PLUS_REPRODUCIBLE_MATCHED_CLUSTER_GEOMETRY",
        "evidence_strength":"STRONG_MECHANISTIC",
        "negative_native_candidate_index":science.get("negative_candidate_index"),
        "positive_native_candidate_index":science.get("positive_candidate_index"),
        "pair_separation_px":science.get("pair_separation_px"),
        "negative_native_snr":science.get("negative_snr"),
        "positive_native_snr":science.get("positive_snr"),
        "other_negative_within15px":science.get("other_negative_within15px"),
        "raw_negative_highpass_z":raw_neg,
        "raw_positive_highpass_z":raw_pos,
        "corrected_opposite_signed_detector_scale":corrected_opposite_signed,
        "gaussian_smoothed_negative_position_z":raw.get("negative_native_smoothed_z"),
        "gaussian_smoothed_positive_position_z":raw.get("positive_native_smoothed_z"),
        "snr_matched_joint_4p5_cluster_tail":snr_joint.get("joint_4p5_guarded_tail"),
        "local_y_joint_4p5_cluster_tail":local_joint.get("joint_4p5_guarded_tail"),
        "snr_matched_exact_joint_tail":snr_joint.get("joint_exact_guarded_tail"),
        "local_y_exact_joint_tail":local_joint.get("joint_exact_guarded_tail"),
        "rationale":(
            "The frozen POSS science candidate is the negative member of a tile-correct "
            "adjacent native pair separated by 4 px. On one common raw-image/background "
            "model its detector-scale high-pass residual is strongly negative, while "
            "the adjacent positive native detection is strongly positive. The broader "
            "Gaussian-smoothed field remains positive at both positions, showing that "
            "the negative candidate is a local high-frequency dip beside broader positive "
            "structure rather than a centered added-light point source. The same close-pair "
            "plus dense-negative-cluster geometry is reproduced in matched LEFT-edge controls."
        )
    }

    ab_rows={int(r["strict_rank"]):r for r in ab.get("rows",[])}
    retired_summary=[]
    for rank in [10,25,26,29]:
        r=ab_rows[rank]
        retired_summary.append({
            "strict_rank":rank,
            "poss_endpoint_disposition":r["poss_endpoint_disposition"],
            "pair_disposition":r["new_pair_disposition"],
            "dasch_endpoint_disposition":r["dasch_endpoint_disposition"],
            "source_stage":"v028ab",
        })

    adrow=ad["row"]
    retired_summary.append({
        "strict_rank":30,
        "poss_endpoint_disposition":adrow["poss_endpoint_disposition"],
        "pair_disposition":adrow["new_pair_disposition"],
        "dasch_endpoint_disposition":adrow["dasch_endpoint_disposition"],
        "source_stage":"v028ad",
    })
    retired_summary.append({
        "strict_rank":24,
        "poss_endpoint_disposition":row["poss_endpoint_disposition"],
        "pair_disposition":row["new_pair_disposition"],
        "dasch_endpoint_disposition":row["dasch_endpoint_disposition"],
        "source_stage":"v028ag",
    })
    retired_summary.sort(key=lambda r:r["strict_rank"])

    payload={
        "stage":"ORDER01_FINAL_CANDIDATE24_DISPOSITION_AND_TWO_OBSERVATORY_CLOSURE_V028AG",
        "previous_active_unresolved_two_observatory_set":[24],
        "retired_this_stage":[24],
        "new_active_unresolved_two_observatory_set":[],
        "order01_viable_two_observatory_transient_pairs_remaining":0,
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
            "v028af_smoothed_polarity_flag_superseded":True,
            "detector_polarity_semantics":"UNSMOOTHED_HIGH_PASS_RESIDUAL",
        },
        "evidence_guards":guards,
        "candidate24_row":row,
        "all_retired_pair_dispositions":retired_summary,
        "interpretive_boundary":(
            "Order 01 now contains zero active viable two-observatory added-light "
            "transient pairs under the frozen physical-image adjudication rules. "
            "This does NOT mean the DASCH detections are erased, disproven, or "
            "uninteresting: every DASCH endpoint remains preserved for independent "
            "single-plate analysis. The result is that the matched POSS endpoints "
            "no longer support the stronger claim of contemporaneous independent "
            "two-observatory transients."
        )
    }

    write_json(OUT_JSON,payload)
    write_csv(OUT_CSV,[row],list(row))

    md=[
        "# ORDER 01 — Final Two-Observatory Disposition Freeze v028ag","",
        "## Critical v028af correction","",
        "v028af's final `oppositeSigned=False` label used an additional Gaussian-smoothed diagnostic map.",
        "The frozen detector polarity is instead defined from the unsmoothed high-pass residual.","",
        f"- #24 negative native raw high-pass residual: **{raw_neg:+.3f} sigma**.",
        f"- Adjacent positive native raw high-pass residual: **{raw_pos:+.3f} sigma**.",
        f"- Correct detector-scale opposite-signed pair: **{corrected_opposite_signed}**.",
        f"- Pair separation: **{float(science['pair_separation_px']):.3f} px**.","",
        "## Matched-control recurrence","",
        f"- SNR-matched joint <=4.5 px + cluster>=8 guarded tail: **{float(snr_joint['joint_4p5_guarded_tail']):.6f}**.",
        f"- SNR+local-y joint <=4.5 px + cluster>=8 guarded tail: **{float(local_joint['joint_4p5_guarded_tail']):.6f}**.",
        "",
        "These are descriptive empirical diagnostics, not astrophysical p-values.","",
        "## #24 disposition","",
        f"- POSS endpoint: `{row['poss_endpoint_disposition']}`.",
        f"- Pair: `{row['new_pair_disposition']}`.",
        f"- DASCH endpoint: `{row['dasch_endpoint_disposition']}`.","",
        "## Final Order-01 active state","",
        "**No active viable two-observatory transient pairs remain.**","",
        "| rank | POSS endpoint disposition | DASCH endpoint |",
        "|---:|---|---|",
    ]
    for r in retired_summary:
        md.append(
            f"| #{r['strict_rank']} | `{r['poss_endpoint_disposition']}` | "
            f"`{r['dasch_endpoint_disposition']}` |"
        )
    md += ["","## Interpretation boundary","",payload["interpretive_boundary"]]
    OUT_MD.write_text("\n".join(md),encoding="utf-8")

    print("\nFINAL DISPOSITION FREEZE PASSED")
    print("  retired this stage: [24]")
    print("  active unresolved: []")
    print("  viable Order-01 two-observatory pairs remaining: 0")
    print("\nAll DASCH endpoints remain preserved for independent single-plate analysis.")
    print("\nOutputs:")
    print(f"  {OUT_JSON}")
    print(f"  {OUT_CSV}")
    print(f"  {OUT_MD}")
    print()
    print("NO network query was made.")
    print("SCIENCE PIXELS WERE NOT READ.")
    print("Transient detector was NOT rerun.")
    print("CANDIDATE STATE WAS MUTATED by additive disposition ledger.")
    print("No historical evidence row was deleted or overwritten.")
    return 0


if __name__=="__main__":
    raise SystemExit(main())
