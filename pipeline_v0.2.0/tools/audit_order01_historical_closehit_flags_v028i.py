#!/usr/bin/env python3
"""
ORDER 01 — historical close-hit DASCH flag audit v028i

Consumes:
    results/order01_native_full_v028/order01_historical_closehit_geometry_v028h.json

Purpose
-------
Decode the raw DASCH AFLAGS/BFLAGS values already preserved for the four
single historical close-hit rows, using the published daschlab flag bit
definitions.

This stage is read-only and offline.

NO:
  * network access
  * science-pixel reads
  * detector reruns
  * candidate promotion/deletion
  * weighted candidate score
  * claim that a flag proves an artifact

Interpretive separation
-----------------------
AFLAGS are warning/data-quality bits.
BFLAGS are processing-context bits and are NOT automatically bad.

For recurrence/identity adjudication we keep three transparent groups:

1) DIRECT_ASSOCIATION_WARNINGS
   Flags whose documented semantics directly concern source identity,
   blending, defects, astrometric displacement, or boundary corruption.

2) PHOTOMETRIC_QUALITY_WARNINGS
   Flags concerning brightness limits, RMS/calibration quality, background,
   smoothing, saturation, etc.

3) PROCESSING_CONTEXT
   BFLAGS describing processing/calibration steps. These are retained but not
   counted as warnings unless they are explicitly association-risk bits such
   as NEIGHBORS or BLEND.

The classifications below describe THE HISTORICAL CLOSE-HIT ROW only.
They do not promote or reject the transient candidate.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "results" / "order01_native_full_v028"

INPUT = RESULTS / "order01_historical_closehit_geometry_v028h.json"
OUT_JSON = RESULTS / "order01_historical_closehit_flag_audit_v028i.json"
OUT_CSV = RESULTS / "order01_historical_closehit_flag_audit_v028i.csv"
OUT_MD = RESULTS / "ORDER01_HISTORICAL_CLOSEHIT_FLAG_AUDIT_V028I.md"

EXPECTED_SINGLE = [10, 25, 26, 30]

# Definitions from current daschlab.photometry AFlags/BFlags.
# Bit indexes here are Python/zero-based; documentation calls 1<<6 "Bit 7".
AFLAGS = {
    6:  ("HIGH_BACKGROUND", "High SExtractor background level at object position"),
    7:  ("BAD_PLATE_QUALITY", "Plate fails general quality checks"),
    8:  ("MULT_EXP_UNMATCHED", "Object is unmatched and this is a multiple-exposure plate"),
    9:  ("UNCERTAIN_DATE", "Observation time is too uncertain to calculate extinction accurately"),
    10: ("MULT_EXP_BLEND", "Object is a blend and this is a multiple-exposure plate"),
    11: ("LARGE_ISO_RMS", "SExtractor isophotonic RMS is suspiciously large"),
    12: ("LARGE_LOCAL_SMOOTH_RMS", "Local-binning RMS is suspiciously large"),
    13: ("CLOSE_TO_LIMITING", "Object brightness is too close to the local limiting magnitude"),
    14: ("RADIAL_BIN_9", "Object is in radial bin 9 (close to the plate edge)"),
    15: ("BIN_DRAD_UNKNOWN", "Object's spatial bin has unmeasured drad"),
    19: ("UNCERTAIN_CATALOG_MAG", "Magnitude of the catalog source is uncertain/variable"),
    20: ("CASE_B_BLEND", "Multiple catalog entries for one imaged star"),
    21: ("CASE_C_BLEND", "Multiple imaged stars for one catalog entry"),
    22: ("CASE_BC_BLEND", "Multiple catalog entries and imaged stars all mixed up"),
    23: ("LARGE_DRAD", "Object drad is large relative to its bin, or spatial/local bin is bad"),
    24: ("PICKERING_WEDGE", "Object is a Pickering Wedge image"),
    25: ("SUSPECTED_DEFECT", "Object is a suspected plate defect"),
    26: ("SXT_BLEND", "SExtractor flags the object as a blend"),
    27: ("REJECTED_BLEND", "Rejected blended object"),
    28: ("LARGE_SMOOTHING_CORRECTION", "Smoothing correction is suspiciously large"),
    29: ("TOO_BRIGHT", "Object is too bright for accurate calibration"),
    30: ("LOW_ALTITUDE", "Object is within 23.5 deg of the horizon"),
}

BFLAGS = {
    0:  ("NEIGHBORS", "Object has nearby neighbors"),
    1:  ("BLEND", "Object was blended with another"),
    2:  ("SATURATED", "At least one image pixel was saturated"),
    3:  ("NEAR_BOUNDARY", "Object is too close to the image boundary"),
    4:  ("APERTURE_INCOMPLETE", "Object aperture data incomplete or corrupt"),
    5:  ("ISOPHOT_INCOMPLETE", "Object isophotal data incomplete or corrupt"),
    6:  ("DEBLEND_OVERFLOW", "Memory overflow during deblending"),
    7:  ("EXTRACTION_OVERFLOW", "Memory overflow during extraction"),
    8:  ("CORRECTED_FOR_BLEND", "Magnitude corrected for blend"),
    9:  ("LARGE_BIN_DRAD", "Object drad is low, but its bin drad is large"),
    10: ("PSF_SATURATED", "Object PSF considered saturated"),
    11: ("MAG_DEP_CAL_APPLIED", "Magnitude-dependent calibration has been applied"),
    16: ("GOOD_STAR", "Appears to be a good star"),
    17: ("LOWESS_CAL_APPLIED", "Lowess calibration has been applied"),
    18: ("LOCAL_CAL_APPLIED", "Local calibration has been applied"),
    19: ("EXTINCTION_CAL_APPLIED", "Extinction calibration has been applied"),
    20: ("TOO_BRIGHT", "Object is too bright to calibrate"),
    21: ("COLOR_CORRECTION_APPLIED", "Color correction has been applied"),
    22: ("COLOR_CORRECTION_USED_METROPOLIS", "Color correction used the Metropolis algorithm"),
    24: ("LATE_CATALOG_MATCH", "Object was only matched to catalog at the end of the pipeline"),
    25: ("LARGE_PROMO_UNCERT", "Object has high proper motion uncertainty"),
    27: ("LARGE_SPATIAL_BIN_COLORTERM", "Spatial bin color-term calibration fails quality check"),
    28: ("POSITION_ADJUSTED", "RA/Dec have been adjusted by bin medians"),
    29: ("LARGE_JD_UNCERT", "Plate date is uncertain"),
    30: ("PROMO_APPLIED", "Catalog position has been corrected for proper motion"),
}

# Direct relevance to whether a historical point should be trusted as
# identifying the same source at the candidate position.
DIRECT_ASSOCIATION_A = {
    "MULT_EXP_UNMATCHED",
    "MULT_EXP_BLEND",
    "RADIAL_BIN_9",
    "BIN_DRAD_UNKNOWN",
    "CASE_B_BLEND",
    "CASE_C_BLEND",
    "CASE_BC_BLEND",
    "LARGE_DRAD",
    "PICKERING_WEDGE",
    "SUSPECTED_DEFECT",
    "SXT_BLEND",
    "REJECTED_BLEND",
}
DIRECT_ASSOCIATION_B = {
    "NEIGHBORS",
    "BLEND",
    "NEAR_BOUNDARY",
    "APERTURE_INCOMPLETE",
    "ISOPHOT_INCOMPLETE",
    "DEBLEND_OVERFLOW",
    "EXTRACTION_OVERFLOW",
    "CORRECTED_FOR_BLEND",
    "LARGE_BIN_DRAD",
    "PSF_SATURATED",
    "LATE_CATALOG_MATCH",
    "LARGE_PROMO_UNCERT",
}

PHOTOMETRIC_A = {
    "HIGH_BACKGROUND",
    "BAD_PLATE_QUALITY",
    "UNCERTAIN_DATE",
    "LARGE_ISO_RMS",
    "LARGE_LOCAL_SMOOTH_RMS",
    "CLOSE_TO_LIMITING",
    "UNCERTAIN_CATALOG_MAG",
    "LARGE_SMOOTHING_CORRECTION",
    "TOO_BRIGHT",
    "LOW_ALTITUDE",
}
PHOTOMETRIC_B = {
    "SATURATED",
    "PSF_SATURATED",
    "TOO_BRIGHT",
    "LARGE_SPATIAL_BIN_COLORTERM",
    "LARGE_JD_UNCERT",
}


def decode(value: int, defs: dict[int, tuple[str, str]]) -> list[dict[str, Any]]:
    out = []
    for bit, (name, desc) in defs.items():
        if value & (1 << bit):
            out.append({
                "zero_based_bit": bit,
                "documented_bit_number": bit + 1,
                "value": 1 << bit,
                "name": name,
                "description": desc,
            })
    return out


def unknown_bits(value: int, defs: dict[int, tuple[str, str]]) -> list[int]:
    known_mask = 0
    for bit in defs:
        known_mask |= 1 << bit
    rem = value & ~known_mask
    return [bit for bit in range(64) if rem & (1 << bit)]


def names(decoded: list[dict[str, Any]]) -> list[str]:
    return [x["name"] for x in decoded]


def join(xs: list[str]) -> str:
    return ";".join(xs)


def hit_flag_label(
    direct: list[str],
    phot: list[str],
    geometry_label: str,
    sparse: bool,
) -> str:
    if direct:
        return "DIRECT_ASSOCIATION_WARNING_PRESENT"
    if sparse:
        return "NO_DIRECT_ASSOCIATION_WARNING_BUT_REFERENCE_HISTORY_SPARSE"
    if phot and geometry_label.startswith("EXTREME_DISPLACEMENT"):
        return "EXTREME_GEOMETRIC_DISPLACEMENT_WITH_PHOTOMETRIC_WARNINGS"
    if phot:
        return "PHOTOMETRIC_WARNINGS_PRESENT_NO_DIRECT_ASSOCIATION_WARNING"
    return "NO_DECODED_WARNING_ON_DECLARED_GROUPS"


def main() -> int:
    print("=" * 120)
    print("ORDER 01 — HISTORICAL CLOSE-HIT DASCH FLAG AUDIT v028i")
    print("=" * 120)

    if not INPUT.exists():
        print(f"FAIL: missing input: {INPUT}")
        return 2

    src = json.loads(INPUT.read_text(encoding="utf-8"))
    results = src.get("results") or []

    ranks = [int(r["strict_rank"]) for r in results]
    if ranks != EXPECTED_SINGLE:
        print("FAIL: unexpected single-hit rank set/order.")
        print("      got:", ranks)
        print(" expected:", EXPECTED_SINGLE)
        return 3

    rows = []
    for r in results:
        rank = int(r["strict_rank"])
        aval = int(str(r["hit_aflags_raw"]).strip() or "0")
        bval = int(str(r["hit_bflags_raw"]).strip() or "0")

        adec = decode(aval, AFLAGS)
        bdec = decode(bval, BFLAGS)
        anames = names(adec)
        bnames = names(bdec)

        aunknown = unknown_bits(aval, AFLAGS)
        bunknown = unknown_bits(bval, BFLAGS)

        direct = sorted(
            [n for n in anames if n in DIRECT_ASSOCIATION_A]
            + [n for n in bnames if n in DIRECT_ASSOCIATION_B]
        )
        phot = sorted(
            [n for n in anames if n in PHOTOMETRIC_A]
            + [n for n in bnames if n in PHOTOMETRIC_B]
        )
        processing = sorted(
            n for n in bnames
            if n not in DIRECT_ASSOCIATION_B and n not in PHOTOMETRIC_B
        )

        sparse = str(r["reference_history_sampling"]) == "SPARSE"
        label = hit_flag_label(
            direct,
            phot,
            str(r["geometry_label"]),
            sparse,
        )

        row = {
            "strict_rank": rank,
            "hit_plate_id": r["hit_plate_id"],
            "geometry_label": r["geometry_label"],
            "reference_history_sampling": r["reference_history_sampling"],
            "reference_unique_plate_detections":
                r["reference_unique_plate_detections"],
            "hit_sep_target_arcsec": r["hit_sep_target_arcsec"],
            "hit_distance_from_median_reference_locus_arcsec":
                r["hit_distance_from_median_reference_locus_arcsec"],
            "hit_reference_locus_residual_empirical_percentile":
                r["hit_reference_locus_residual_empirical_percentile"],
            "hit_limit_minus_source_mag": r["hit_limit_minus_source_mag"],
            "hit_edgedist": r["hit_edgedist"],
            "aflags_raw": aval,
            "aflags_hex": f"0x{aval:08X}",
            "aflags_decoded": adec,
            "aflags_names": anames,
            "aflags_unknown_zero_based_bits": aunknown,
            "bflags_raw": bval,
            "bflags_hex": f"0x{bval:08X}",
            "bflags_decoded": bdec,
            "bflags_names": bnames,
            "bflags_unknown_zero_based_bits": bunknown,
            "direct_association_warning_names": direct,
            "direct_association_warning_count": len(direct),
            "photometric_quality_warning_names": phot,
            "photometric_quality_warning_count": len(phot),
            "processing_context_names": processing,
            "historical_hit_flag_label": label,
        }
        rows.append(row)

    payload = {
        "stage": "ORDER01_HISTORICAL_CLOSEHIT_FLAG_AUDIT_V028I",
        "input": str(INPUT.relative_to(ROOT)),
        "frozen_active_ranks": src.get("frozen_active_ranks"),
        "single_closehit_ranks": EXPECTED_SINGLE,
        "guards": {
            "network_access": False,
            "science_pixels_read": False,
            "detector_rerun": False,
            "candidate_promotion": False,
            "candidate_deletion": False,
            "weighted_candidate_score": False,
            "flag_proves_artifact_claimed": False,
        },
        "definition_source_note": (
            "Bit maps transcribed from published daschlab.photometry "
            "AFlags/BFlags definitions. BFLAGS processing flags are not "
            "automatically treated as bad."
        ),
        "declared_groups": {
            "direct_association_aflags": sorted(DIRECT_ASSOCIATION_A),
            "direct_association_bflags": sorted(DIRECT_ASSOCIATION_B),
            "photometric_aflags": sorted(PHOTOMETRIC_A),
            "photometric_bflags": sorted(PHOTOMETRIC_B),
        },
        "results": rows,
        "interpretive_guardrail": (
            "Flag labels describe trust/context of the isolated historical "
            "catalogue row only. They do not classify the transient candidate."
        ),
    }
    OUT_JSON.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False),
        encoding="utf-8"
    )

    csv_fields = [
        "strict_rank", "hit_plate_id", "geometry_label",
        "reference_history_sampling", "reference_unique_plate_detections",
        "hit_sep_target_arcsec",
        "hit_distance_from_median_reference_locus_arcsec",
        "hit_reference_locus_residual_empirical_percentile",
        "hit_limit_minus_source_mag", "hit_edgedist",
        "aflags_raw", "aflags_hex", "aflags_names",
        "aflags_unknown_zero_based_bits",
        "bflags_raw", "bflags_hex", "bflags_names",
        "bflags_unknown_zero_based_bits",
        "direct_association_warning_names",
        "direct_association_warning_count",
        "photometric_quality_warning_names",
        "photometric_quality_warning_count",
        "processing_context_names",
        "historical_hit_flag_label",
    ]
    with OUT_CSV.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=csv_fields)
        w.writeheader()
        for row in rows:
            flat = dict(row)
            for key in (
                "aflags_names", "aflags_unknown_zero_based_bits",
                "bflags_names", "bflags_unknown_zero_based_bits",
                "direct_association_warning_names",
                "photometric_quality_warning_names",
                "processing_context_names",
            ):
                flat[key] = join([str(x) for x in flat[key]])
            flat.pop("aflags_decoded", None)
            flat.pop("bflags_decoded", None)
            w.writerow(flat)

    md = []
    md.append("# ORDER 01 — Historical Close-Hit DASCH Flag Audit v028i")
    md.append("")
    md.append(
        "Offline decoding of AFLAGS/BFLAGS for the four isolated historical "
        "<=5 arcsec catalogue rows."
    )
    md.append("")
    md.append("## Guardrails")
    md.append("")
    md.append("- No network access.")
    md.append("- No science pixels read.")
    md.append("- No detector rerun.")
    md.append("- No candidate promoted or deleted.")
    md.append("- No weighted candidate score.")
    md.append("- A warning flag does not by itself prove an artifact.")
    md.append("")
    md.append("## Results")
    md.append("")
    md.append(
        "| rank | plate | AFLAGS warnings | direct association warnings | "
        "photometric warnings | geometry | row label |"
    )
    md.append("|---:|---|---|---|---|---|---|")
    for row in rows:
        md.append(
            f"| #{row['strict_rank']} | `{row['hit_plate_id']}` | "
            f"{', '.join(row['aflags_names']) or 'none'} | "
            f"{', '.join(row['direct_association_warning_names']) or 'none'} | "
            f"{', '.join(row['photometric_quality_warning_names']) or 'none'} | "
            f"`{row['geometry_label']}` | "
            f"`{row['historical_hit_flag_label']}` |"
        )
    md.append("")
    md.append("## Detailed decode")
    md.append("")
    for row in rows:
        md.append(f"### Strict #{row['strict_rank']} — `{row['hit_plate_id']}`")
        md.append("")
        md.append(
            f"- AFLAGS `{row['aflags_raw']}` / `{row['aflags_hex']}`: "
            f"{', '.join(row['aflags_names']) or 'none'}."
        )
        md.append(
            f"- BFLAGS `{row['bflags_raw']}` / `{row['bflags_hex']}`: "
            f"{', '.join(row['bflags_names']) or 'none'}."
        )
        md.append(
            "- Direct association warnings: "
            + (", ".join(row["direct_association_warning_names"]) or "none")
            + "."
        )
        md.append(
            "- Photometric-quality warnings: "
            + (", ".join(row["photometric_quality_warning_names"]) or "none")
            + "."
        )
        md.append(
            "- Processing context retained separately: "
            + (", ".join(row["processing_context_names"]) or "none")
            + "."
        )
        if row["aflags_unknown_zero_based_bits"] or row["bflags_unknown_zero_based_bits"]:
            md.append(
                "- WARNING: one or more raw bits were not represented in the "
                "transcribed definition map; inspect JSON."
            )
        md.append("")
    md.append("## Interpretation boundary")
    md.append("")
    md.append(
        "Direct association warnings weaken the evidentiary value of a single "
        "historical catalogue row as a recurrence/identity match. Photometric "
        "warnings instead indicate measurement/calibration concerns and should "
        "not automatically be conflated with source misidentification."
    )
    md.append("")
    OUT_MD.write_text("\n".join(md), encoding="utf-8")

    print()
    print("Decoded close-hit flags:")
    print("-" * 120)
    for row in rows:
        print(
            f"#{row['strict_rank']:>2} {row['hit_plate_id']} "
            f"A={row['aflags_hex']} "
            f"direct=[{', '.join(row['direct_association_warning_names']) or '-'}] "
            f"phot=[{', '.join(row['photometric_quality_warning_names']) or '-'}] "
            f"label={row['historical_hit_flag_label']}"
        )
        print(
            f"    AFLAGS: {', '.join(row['aflags_names']) or 'none'}"
        )
        print(
            f"    BFLAGS: {', '.join(row['bflags_names']) or 'none'}"
        )

    print()
    unknown_any = any(
        r["aflags_unknown_zero_based_bits"] or r["bflags_unknown_zero_based_bits"]
        for r in rows
    )
    print("Unknown decoded raw bits:", "YES - REVIEW REQUIRED" if unknown_any else "none")
    print()
    print("Outputs:")
    print(f"  {OUT_JSON}")
    print(f"  {OUT_CSV}")
    print(f"  {OUT_MD}")
    print()
    print("No external query was made by this script.")
    print("No science pixel was read.")
    print("No detector was rerun.")
    print("No candidate was promoted or deleted.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
