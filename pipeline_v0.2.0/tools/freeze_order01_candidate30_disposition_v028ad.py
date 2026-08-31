#!/usr/bin/env python3
"""
ORDER 01 — candidate #30 disposition freeze v028ad

Purpose
-------
v028ab left #24 and #30 active unresolved.

v028aa established that #30's frozen POSS detection:
  - has negative detector polarity;
  - lies 17.68 px from Gaia source 302788670313550336;
  - lies within the independent plate-wide ordinary-star negative-satellite
    radius distribution;
  - has 19 independent controls within +/-3 px of its radius.

v028ac-r1 then directly verified the previously tentative neighbour:
  - Gaia source 302788670313550336 (G~7.92) is a strong centred positive raw
    POSS source at the predicted position;
  - raw Gaussian centre Z ~8.32;
  - positive peak Z ~8.35;
  - positive peak offset ~1.07 px;
  - 17 frozen negative native detections occur 4-25 px around that star.

This closes the missing positive-neighbour premise from v028aa.

Disposition
-----------
Retire #30 from the active two-observatory transient set because its POSS
endpoint is adjudicated as a negative detector satellite around a verified
positive Gaia neighbour.

The DASCH endpoint is preserved as an unresolved single-plate detection.

#24 remains active unresolved.

No network access.
SCIENCE PIXELS ARE NOT READ.
Frozen transient detector is NOT rerun.
Candidate state mutation: TRUE, additive ledger only.
No historical evidence is deleted or overwritten.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

ROOT = Path.cwd()
BASE = ROOT / "results" / "order01_native_full_v028"

V028AB = BASE / "order01_candidate_disposition_freeze_v028ab.json"
V028AA = BASE / "order01_poss_platewide_detector_satellite_adjudication_v028aa.json"
V028AC = BASE / "order01_active24_30_focused_poss_mechanism_v028ac.json"

OUT_JSON = BASE / "order01_candidate30_disposition_freeze_v028ad.json"
OUT_CSV = BASE / "order01_candidate30_disposition_freeze_v028ad.csv"
OUT_MD = BASE / "ORDER01_CANDIDATE30_DISPOSITION_FREEZE_V028AD.md"

EXPECTED_INPUT_ACTIVE = [24,30]
EXPECTED_OUTPUT_ACTIVE = [24]
TARGET = 30

REQ_NEIGHBOR = "302788670313550336"
MAX_PEAK_OFFSET_PX = 2.0
MIN_CENTER_Z = 3.0
MIN_PEAK_Z = 3.0
MIN_NEGATIVE_SATELLITES = 5
MIN_PLATEWIDE_SIMILAR = 3


def write_json(path,obj):
    tmp=path.with_suffix(path.suffix+".tmp")
    tmp.write_text(json.dumps(obj,indent=2,sort_keys=True,default=str)+"\n",
                   encoding="utf-8")
    tmp.replace(path)


def write_csv(path,rows,fields):
    tmp=path.with_suffix(path.suffix+".tmp")
    with tmp.open("w",encoding="utf-8",newline="") as fh:
        w=csv.DictWriter(fh,fieldnames=fields,extrasaction="ignore")
        w.writeheader();w.writerows(rows)
    tmp.replace(path)


def main():
    print("="*128)
    print("ORDER 01 — CANDIDATE #30 DISPOSITION FREEZE v028ad")
    print("="*128)
    print("NO NETWORK ACCESS.")
    print("SCIENCE PIXELS ARE NOT READ.")
    print("Frozen transient detector is NOT rerun.")
    print("CANDIDATE STATE MUTATION: TRUE — additive disposition ledger only.\n")

    for p in (V028AB,V028AA,V028AC):
        if not p.is_file():
            print(f"FAIL missing input: {p}")
            return 2

    ab=json.loads(V028AB.read_text(encoding="utf-8"))
    aa=json.loads(V028AA.read_text(encoding="utf-8"))
    ac=json.loads(V028AC.read_text(encoding="utf-8"))

    if ab.get("new_active_unresolved_two_observatory_set") != EXPECTED_INPUT_ACTIVE:
        raise RuntimeError("v028ab active-set guard mismatch")
    if ab.get("guards",{}).get("candidate_state_mutation") is not True:
        raise RuntimeError("v028ab mutation guard mismatch")
    if aa.get("guards",{}).get("candidate_state_mutation") is not False:
        raise RuntimeError("v028aa state guard mismatch")
    if ac.get("guards",{}).get("candidate_state_mutation") is not False:
        raise RuntimeError("v028ac state guard mismatch")

    arows={int(r["strict_rank"]):r for r in aa["results"]}
    a=arows[TARGET]
    c=ac["candidate30"]

    # Frozen evidence guards.
    guards={
        "negative_science_polarity": a.get("science_native_polarity")==-1,
        "identified_neighbor_matches": str(a.get("identified_neighbor_gaia_source_id"))==REQ_NEIGHBOR,
        "platewide_radius_supported": bool(a.get("science_radius_within_platewide_p05_p95")),
        "platewide_similar_controls": int(a.get("unique_platewide_controls_within_3px_radius",0)) >= MIN_PLATEWIDE_SIMILAR,
        "raw_neighbor_source_id_matches": str(c.get("target_source_id"))==REQ_NEIGHBOR,
        "raw_neighbor_center_positive": float(c.get("target_raw_gaussian_center_z",-999)) >= MIN_CENTER_Z,
        "raw_neighbor_peak_positive": float(c.get("target_raw_positive_peak_z_r7",-999)) >= MIN_PEAK_Z,
        "raw_neighbor_peak_centered": float(c.get("target_raw_positive_peak_offset_px_r7",999)) <= MAX_PEAK_OFFSET_PX,
        "raw_neighbor_negative_satellite_field": int(c.get("target_negative_satellite_count_4to25px",0)) >= MIN_NEGATIVE_SATELLITES,
    }

    for k,v in guards.items():
        print(f"{k}: {v}")
    if not all(guards.values()):
        raise RuntimeError("REFUSING TO FREEZE #30: one or more evidence guards failed")

    row={
        "strict_rank":30,
        "previous_pair_state":"ACTIVE_UNRESOLVED_TWO_OBSERVATORY_PAIR",
        "new_pair_disposition":"RETIRED_FROM_ACTIVE_TWO_OBSERVATORY_TRANSIENT_SET_DUE_TO_POSS_ENDPOINT",
        "poss_endpoint_disposition":"ADJUDICATED_NON_ASTROPHYSICAL_NEIGHBOUR_STAR_DETECTOR_SATELLITE",
        "dasch_endpoint_disposition":"PRESERVED_UNRESOLVED_SINGLE_PLATE_ENDPOINT",
        "disposition_rule":"C_VERIFIED_BRIGHT_GAIA_NEIGHBOUR_PLUS_PLATEWIDE_NEGATIVE_SATELLITE_GEOMETRY",
        "evidence_strength":"STRONG",
        "neighbor_gaia_source_id":REQ_NEIGHBOR,
        "neighbor_g_mag":c.get("target_g_mag"),
        "neighbor_raw_center_z":c.get("target_raw_gaussian_center_z"),
        "neighbor_raw_positive_peak_z":c.get("target_raw_positive_peak_z_r7"),
        "neighbor_raw_positive_peak_offset_px":c.get("target_raw_positive_peak_offset_px_r7"),
        "neighbor_negative_satellite_count_4to25px":c.get("target_negative_satellite_count_4to25px"),
        "science_to_neighbor_radius_px":a.get("science_to_neighbor_radius_px"),
        "science_radius_percentile_platewide":a.get("science_radius_percentile_platewide"),
        "platewide_controls_within_3px_radius":a.get("unique_platewide_controls_within_3px_radius"),
        "science_native_snr":a.get("science_native_snr"),
        "rationale":(
            "The POSS science detection has negative polarity and lies at an ordinary "
            "negative-satellite radius around Gaia source 302788670313550336. "
            "The neighbouring Gaia source is independently verified in raw POSS pixels "
            "as a strong centred positive image, and its field contains numerous frozen "
            "negative detector satellites. The POSS endpoint is therefore not retained "
            "as an added-light transient point source."
        )
    }

    payload={
        "stage":"ORDER01_CANDIDATE30_DISPOSITION_FREEZE_V028AD",
        "previous_active_unresolved_two_observatory_set":EXPECTED_INPUT_ACTIVE,
        "retired_this_stage":[30],
        "new_active_unresolved_two_observatory_set":EXPECTED_OUTPUT_ACTIVE,
        "guards":{
            "network_access":False,
            "science_pixels_read":False,
            "transient_detector_rerun":False,
            "transient_detector_parameters_changed":False,
            "candidate_state_mutation":True,
            "mutation_type":"ADDITIVE_DISPOSITION_LEDGER_ONLY",
            "historical_evidence_deleted":False,
            "historical_evidence_overwritten":False,
            "dasch_endpoint_deleted":False,
        },
        "evidence_guards":guards,
        "row":row,
        "interpretive_boundary":(
            "Retirement applies to the two-observatory transient pair because the "
            "POSS endpoint has a specific non-astrophysical detector-satellite "
            "explanation. The DASCH endpoint remains preserved for independent "
            "single-plate analysis. #24 remains the sole active unresolved pair."
        )
    }

    write_json(OUT_JSON,payload)
    write_csv(OUT_CSV,[row],list(row))

    md=[
        "# ORDER 01 — Candidate #30 Disposition Freeze v028ad","",
        "## State mutation","",
        "- #30 is retired from the active two-observatory transient set.",
        "- Its POSS endpoint is adjudicated as a neighbour-star negative detector satellite.",
        "- Its DASCH endpoint remains preserved as an unresolved single-plate detection.",
        "- #24 remains the sole active unresolved two-observatory pair.",
        "- No historical evidence was deleted or overwritten.","",
        "## Frozen evidence","",
        f"- Gaia neighbour: `{REQ_NEIGHBOR}`.",
        f"- Raw neighbour centre Z: **{float(c['target_raw_gaussian_center_z']):.3f}**.",
        f"- Raw neighbour positive-peak Z: **{float(c['target_raw_positive_peak_z_r7']):.3f}**.",
        f"- Raw neighbour peak offset: **{float(c['target_raw_positive_peak_offset_px_r7']):.3f} px**.",
        f"- Negative satellites 4–25 px around neighbour: **{int(c['target_negative_satellite_count_4to25px'])}**.",
        f"- #30 science radius from neighbour: **{float(a['science_to_neighbor_radius_px']):.3f} px**.",
        f"- Plate-wide controls within ±3 px of that radius: **{int(a['unique_platewide_controls_within_3px_radius'])}**.","",
        "## New active unresolved set","",
        "`[24]`","",
        "## Interpretation boundary","",
        payload["interpretive_boundary"],
    ]
    OUT_MD.write_text("\n".join(md),encoding="utf-8")

    print("\nDISPOSITION FREEZE PASSED")
    print("  retired this stage: [30]")
    print("  active unresolved: [24]")
    print("\nOutputs:")
    print(f"  {OUT_JSON}")
    print(f"  {OUT_CSV}")
    print(f"  {OUT_MD}")
    print()
    print("NO network query was made.")
    print("SCIENCE PIXELS WERE NOT READ.")
    print("Transient detector was NOT rerun.")
    print("CANDIDATE STATE WAS MUTATED by additive disposition ledger.")
    return 0


if __name__=="__main__":
    raise SystemExit(main())
