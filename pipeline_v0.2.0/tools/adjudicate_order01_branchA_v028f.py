#!/usr/bin/env python3
"""
ORDER 01 — Branch-A candidate-specific adjudication synthesis v028f

Consumes:
    results/order01_native_full_v028/order01_candidate_evidence_reduced_v028e.json

Purpose
-------
Join the completed, frozen candidate-level evidence into a compact comparative
adjudication table for strict ranks 10, 24, 25, 26, 29, 30.

This is deliberately NOT an overall weighted score.  It keeps independent
evidence axes separate and computes Pareto dominance only where one candidate
is at least as favourable on every predeclared comparative axis and strictly
better on at least one.

No network.
No science-pixel read.
No detector rerun.
No candidate promotion.
No candidate deletion.

Comparative axes (direction declared before inspection by this script):
  * pair separation: smaller is favourable
  * SNR floor = min(POSS SNR, DASCH SNR): larger is favourable
  * matched-peer continuous morphology extreme count: smaller is favourable
  * endpoints above all tested 90%-recovery thresholds: larger is favourable
  * historical plates with source <=5 arcsec after 1024: smaller is favourable

Catalogue/static gates are retained as validity/context columns but are not
used in Pareto comparison because all six frozen Branch-A survivors are
expected to have passed those gates.

IMPORTANT
---------
"Pareto frontier" is comparative bookkeeping, not an astrophysical promotion.
"Dominated" does not mean false and does not delete or demote a candidate.
"""

from __future__ import annotations

import csv
import json
import math
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "results" / "order01_native_full_v028"

INPUT = RESULTS / "order01_candidate_evidence_reduced_v028e.json"
OUT_JSON = RESULTS / "order01_branchA_candidate_adjudication_v028f.json"
OUT_CSV = RESULTS / "order01_branchA_candidate_adjudication_v028f.csv"
OUT_MD = RESULTS / "ORDER01_BRANCHA_CANDIDATE_ADJUDICATION_V028F.md"

EXPECTED = [10, 24, 25, 26, 29, 30]

POST_SUFFIX = "order01_post1024_adjudication_v028c.csv"
PLATE_SUFFIX = "order01_platephot_stage3_rank_summary_cumulative_v028c.csv"
CAT_SUFFIX = "order01_dasch_catalog_recurrence_triage_v028c.csv"
GAIA_SUFFIX = "order01_gaia_static_triage_v028b.csv"
PS1_SUFFIX = "order01_ps1_static_triage_v028.csv"
MORPH_SUFFIX = (
    "order01_matched_peer_morphology_v028/"
    "order01_matched_peer_candidate_summary_v028.csv"
)

PARETO_FIELDS = (
    # field, higher_is_better
    ("pair_separation_arcsec", False),
    ("snr_floor", True),
    ("morph_extreme_total", False),
    ("injection_robust_endpoint_count", True),
    ("historical_close5_plate_count", False),
)


def normpath(s: str) -> str:
    return str(s).replace("\\", "/")


def as_bool(v: Any) -> bool:
    if isinstance(v, bool):
        return v
    s = str(v).strip().lower()
    if s in {"true", "1", "yes", "y"}:
        return True
    if s in {"false", "0", "no", "n", ""}:
        return False
    raise ValueError(f"Cannot parse bool from {v!r}")


def as_int(v: Any) -> int:
    return int(float(str(v).strip()))


def as_float(v: Any) -> float:
    return float(str(v).strip())


def opt_float(v: Any) -> float | None:
    if v is None or str(v).strip() == "":
        return None
    return as_float(v)


def opt_int(v: Any) -> int | None:
    if v is None or str(v).strip() == "":
        return None
    return as_int(v)


def get_exact_record(dossier: dict[str, Any], rank: int, suffix: str) -> dict[str, Any]:
    rows = dossier[str(rank)].get("low_volume_records") or []
    matches = [
        r.get("evidence") or {}
        for r in rows
        if normpath(r.get("source_file", "")).endswith(suffix)
    ]
    if len(matches) != 1:
        raise RuntimeError(
            f"rank {rank}: expected exactly one record ending {suffix!r}; "
            f"found {len(matches)}"
        )
    return matches[0]


def catalogue_axis(gaia: dict[str, Any], ps1: dict[str, Any], cat: dict[str, Any]) -> str:
    g = str(gaia.get("gaia_class", ""))
    p = str(ps1.get("ps1_class", ""))
    c = str(cat.get("recurrence_class", ""))
    if (
        g == "NO_GAIA_WITHIN_5_ARCSEC_AT_TARGET_EPOCH"
        and p == "NO_PS1_REPEAT_WITHIN_5_ARCSEC"
        and c == "NO_CATALOGUED_DASCH_RECURRENCE_WITHIN_5_ARCSEC"
    ):
        return "CLEAN_GAIA_PS1_DASCH_CATALOGUE_5ARCSEC"
    return "CATALOGUE_CONTEXT_REQUIRES_REVIEW"


def morphology_axis(poss_n: int, dasch_n: int) -> str:
    total = poss_n + dasch_n
    active_endpoints = int(poss_n > 0) + int(dasch_n > 0)
    if total == 0:
        return "M0_NO_MATCHED_PEER_CONTINUOUS_EXTREME"
    if active_endpoints == 1 and total <= 2:
        return "M1_ONE_ENDPOINT_LOW_COUNT_EXTREME"
    if active_endpoints == 1:
        return "M2_ONE_ENDPOINT_MULTI_METRIC_EXTREME"
    return "M3_BOTH_ENDPOINTS_HAVE_EXTREMES"


def injection_axis(p_ok: bool, d_ok: bool) -> str:
    n = int(p_ok) + int(d_ok)
    if n == 2:
        return "I2_BOTH_ENDPOINTS_ABOVE_ALL_TESTED_90PCT_THRESHOLDS"
    if n == 1:
        return "I1_ONE_ENDPOINT_ABOVE_ALL_TESTED_90PCT_THRESHOLDS"
    return "I0_NEITHER_ENDPOINT_ABOVE_ALL_TESTED_90PCT_THRESHOLDS"


def historical_axis(n5: int, context: str) -> str:
    if n5 == 0:
        return "H0_ZERO_CLOSE5_IN_1024"
    if n5 == 1 and context == "SINGLE_CLOSE_HIT_FROM_REFERENCE_USUALLY_FARTHER_AWAY":
        return "H1_SINGLE_ISOLATED_CLOSE5_CONTEXT_ONLY"
    if n5 == 1:
        return "H2_SINGLE_CLOSE5_REVIEW_CONTEXT"
    return "H3_MULTIPLE_CLOSE5_REVIEW_REQUIRED"


def favourable_or_equal(a: float, b: float, higher_better: bool) -> bool:
    return a >= b if higher_better else a <= b


def strictly_better(a: float, b: float, higher_better: bool) -> bool:
    return a > b if higher_better else a < b


def dominates(a: dict[str, Any], b: dict[str, Any]) -> bool:
    # Pareto comparison only for candidates whose static/catalogue gate is clean.
    if a["catalogue_axis"] != "CLEAN_GAIA_PS1_DASCH_CATALOGUE_5ARCSEC":
        return False
    if b["catalogue_axis"] != "CLEAN_GAIA_PS1_DASCH_CATALOGUE_5ARCSEC":
        return False

    all_not_worse = True
    any_better = False
    for field, higher_better in PARETO_FIELDS:
        av = float(a[field])
        bv = float(b[field])
        all_not_worse &= favourable_or_equal(av, bv, higher_better)
        any_better |= strictly_better(av, bv, higher_better)
    return all_not_worse and any_better


def build_profile(rank: int, dossier: dict[str, Any]) -> dict[str, Any]:
    post = get_exact_record(dossier, rank, POST_SUFFIX)
    plate = get_exact_record(dossier, rank, PLATE_SUFFIX)
    cat = get_exact_record(dossier, rank, CAT_SUFFIX)
    gaia = get_exact_record(dossier, rank, GAIA_SUFFIX)
    ps1 = get_exact_record(dossier, rank, PS1_SUFFIX)
    morph = get_exact_record(dossier, rank, MORPH_SUFFIX)

    if str(post.get("final_disposition")) != "ACTIVE_UNRESOLVED_BRANCH_A_AFTER_1024":
        raise RuntimeError(
            f"rank {rank}: unexpected frozen disposition "
            f"{post.get('final_disposition')!r}"
        )
    if as_int(post.get("cumulative_plates_examined")) != 1024:
        raise RuntimeError(f"rank {rank}: not at frozen 1024-plate stage")

    poss_snr = as_float(post["poss_snr"])
    dasch_snr = as_float(post["dasch_snr"])

    p_m = as_int(post["poss_morph_extreme_continuous_count"])
    d_m = as_int(post["dasch_morph_extreme_continuous_count"])

    p_i = as_bool(post["poss_observed_ge_all_tested_90pct_recovery_thresholds"])
    d_i = as_bool(post["dasch_observed_ge_all_tested_90pct_recovery_thresholds"])

    hist3 = as_int(post["plates_with_source_within_3arcsec"])
    hist5 = as_int(post["plates_with_source_within_5arcsec"])

    # Cross-check duplicated completed-stage summaries.
    if as_int(plate["cumulative_completed_plates"]) != 1024:
        raise RuntimeError(f"rank {rank}: plate summary not complete at 1024")
    if as_int(plate["plates_with_source_within_5arcsec"]) != hist5:
        raise RuntimeError(f"rank {rank}: close5 mismatch between freeze and plate summary")
    if str(morph["pair_morphology_status"]) != str(post["morphology_status"]):
        raise RuntimeError(f"rank {rank}: morphology status mismatch")

    ref_total = opt_int(post.get("closest_reference_total_detections_in_sample"))
    ref_close = opt_int(post.get("closest_reference_close5_detections_in_sample"))
    ref_close_fraction = None
    if ref_total and ref_close is not None:
        ref_close_fraction = ref_close / ref_total

    profile = {
        "strict_rank": rank,
        "frozen_disposition": post["final_disposition"],
        "pair_separation_arcsec": as_float(post["pair_separation_arcsec"]),
        "poss_snr": poss_snr,
        "dasch_snr": dasch_snr,
        "snr_floor": min(poss_snr, dasch_snr),
        "snr_ceiling": max(poss_snr, dasch_snr),
        "poss_polarity": as_int(post["poss_polarity"]),
        "dasch_polarity": as_int(post["dasch_polarity"]),
        "same_polarity": as_bool(post["same_polarity"]),
        "gaia_class": gaia["gaia_class"],
        "ps1_class": ps1["ps1_class"],
        "dasch_catalogue_recurrence_class": cat["recurrence_class"],
        "catalogue_axis": catalogue_axis(gaia, ps1, cat),
        "morphology_status": post["morphology_status"],
        "poss_morph_extreme_continuous_count": p_m,
        "dasch_morph_extreme_continuous_count": d_m,
        "morph_extreme_total": p_m + d_m,
        "morphology_axis": morphology_axis(p_m, d_m),
        "poss_above_all_tested_90pct_recovery_thresholds": p_i,
        "dasch_above_all_tested_90pct_recovery_thresholds": d_i,
        "injection_robust_endpoint_count": int(p_i) + int(d_i),
        "injection_axis": injection_axis(p_i, d_i),
        "poss_max_matching_polarity_snr_at_90pct_recovery":
            as_float(post["poss_max_matching_polarity_snr_at_90pct_recovery"]),
        "dasch_max_matching_polarity_snr_at_90pct_recovery":
            as_float(post["dasch_max_matching_polarity_snr_at_90pct_recovery"]),
        "historical_close3_plate_count": hist3,
        "historical_close5_plate_count": hist5,
        "historical_axis": historical_axis(
            hist5, str(post.get("isolated_close_match_context", ""))
        ),
        "expected_chance_within_3_from_local60":
            as_float(plate["expected_chance_within_3_from_local60"]),
        "expected_chance_within_5_from_local60":
            as_float(plate["expected_chance_within_5_from_local60"]),
        "total_sources_within_60arcsec": as_int(plate["total_sources_within_60arcsec"]),
        "closest_historical_sep_arcsec": opt_float(post.get("closest_historical_sep_arcsec")),
        "closest_historical_plate_id": str(post.get("closest_historical_plate_id", "")),
        "closest_historical_refcat": str(post.get("closest_historical_refcat", "")),
        "closest_historical_ref_number": str(post.get("closest_historical_ref_number", "")),
        "closest_reference_total_detections_in_sample": ref_total,
        "closest_reference_close5_detections_in_sample": ref_close,
        "closest_reference_close5_fraction_in_sample": ref_close_fraction,
        "closest_reference_median_sep_arcsec":
            opt_float(post.get("closest_reference_median_sep_arcsec")),
        "isolated_close_match_context": str(post.get("isolated_close_match_context", "")),
        "source_interpretive_label": str(post.get("interpretive_label", "")),
    }
    return profile


def axis_leaders(profiles: list[dict[str, Any]]) -> dict[str, list[int]]:
    out = {}
    for field, higher_better in PARETO_FIELDS:
        vals = [float(x[field]) for x in profiles]
        best = max(vals) if higher_better else min(vals)
        out[field] = [
            int(x["strict_rank"])
            for x in profiles
            if math.isclose(float(x[field]), best, rel_tol=0.0, abs_tol=1e-12)
        ]
    return out


def profile_note(p: dict[str, Any], leaders: dict[str, list[int]]) -> str:
    r = p["strict_rank"]
    strengths = []
    cautions = []

    if r in leaders["pair_separation_arcsec"]:
        strengths.append("smallest pair separation")
    if r in leaders["snr_floor"]:
        strengths.append("highest two-endpoint SNR floor")
    if r in leaders["morph_extreme_total"]:
        strengths.append("fewest matched-peer morphology extremes")
    if r in leaders["injection_robust_endpoint_count"]:
        strengths.append("joint-best injection/recovery robustness")
    if r in leaders["historical_close5_plate_count"]:
        strengths.append("joint-best historical non-recurrence")

    if p["morph_extreme_total"] >= 3:
        cautions.append("multi-metric morphology extreme on one endpoint")
    elif p["morph_extreme_total"] > 0:
        cautions.append("matched-peer morphology extreme on one endpoint")

    if p["injection_robust_endpoint_count"] == 0:
        cautions.append("neither endpoint exceeds every tested 90%-recovery threshold")
    elif p["injection_robust_endpoint_count"] == 1:
        cautions.append("only one endpoint exceeds every tested 90%-recovery threshold")

    if p["historical_close5_plate_count"] == 1:
        sep = p["closest_historical_sep_arcsec"]
        cautions.append(
            f"one isolated historical <=5\" hit"
            + (f" at {sep:.3f}\"" if sep is not None else "")
        )

    if not strengths:
        strengths.append("retains all frozen Branch-A catalogue/static gates")

    return (
        "Strengths: " + "; ".join(strengths) + ". "
        "Cautions: " + ("; ".join(cautions) if cautions else "none on declared axes") + "."
    )


def main() -> int:
    print("=" * 112)
    print("ORDER 01 — BRANCH-A CANDIDATE-SPECIFIC ADJUDICATION SYNTHESIS v028f")
    print("=" * 112)

    if not INPUT.exists():
        print(f"FAIL: missing input: {INPUT}")
        return 2

    data = json.loads(INPUT.read_text(encoding="utf-8"))

    if data.get("frozen_active_ranks") != EXPECTED:
        print("FAIL: frozen survivor set mismatch.")
        print(f"      input:    {data.get('frozen_active_ranks')}")
        print(f"      expected: {EXPECTED}")
        return 3

    dossier = data.get("candidate_dossier")
    if not isinstance(dossier, dict):
        print("FAIL: malformed candidate_dossier.")
        return 4

    profiles = [build_profile(r, dossier) for r in EXPECTED]
    leaders = axis_leaders(profiles)

    for a in profiles:
        a["dominates_ranks"] = [
            b["strict_rank"] for b in profiles
            if b is not a and dominates(a, b)
        ]
        a["dominated_by_ranks"] = [
            b["strict_rank"] for b in profiles
            if b is not a and dominates(b, a)
        ]
        a["pareto_status"] = (
            "PARETO_FRONTIER_ON_DECLARED_AXES"
            if not a["dominated_by_ranks"]
            else "PARETO_DOMINATED_ON_DECLARED_AXES"
        )

    for p in profiles:
        p["comparative_note"] = profile_note(p, leaders)

    frontier = [p["strict_rank"] for p in profiles if not p["dominated_by_ranks"]]
    dominated = [p["strict_rank"] for p in profiles if p["dominated_by_ranks"]]

    payload = {
        "stage": "ORDER01_BRANCHA_CANDIDATE_ADJUDICATION_V028F",
        "input": str(INPUT.relative_to(ROOT)),
        "frozen_active_ranks": EXPECTED,
        "guards": {
            "network_access": False,
            "science_pixels_read": False,
            "detector_rerun": False,
            "candidate_promotion": False,
            "candidate_deletion": False,
            "weighted_overall_score_used": False,
        },
        "pareto_axes": [
            {"field": f, "higher_is_better": hb} for f, hb in PARETO_FIELDS
        ],
        "axis_leaders": leaders,
        "pareto_frontier_ranks": frontier,
        "pareto_dominated_ranks": dominated,
        "profiles": profiles,
        "interpretation_guardrail": (
            "Pareto status is comparative bookkeeping only. It is not an "
            "astrophysical classification, promotion, rejection, or deletion rule."
        ),
    }
    OUT_JSON.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    csv_fields = [
        "strict_rank",
        "pareto_status",
        "dominated_by_ranks",
        "dominates_ranks",
        "pair_separation_arcsec",
        "poss_snr",
        "dasch_snr",
        "snr_floor",
        "catalogue_axis",
        "morphology_axis",
        "poss_morph_extreme_continuous_count",
        "dasch_morph_extreme_continuous_count",
        "morph_extreme_total",
        "injection_axis",
        "injection_robust_endpoint_count",
        "historical_axis",
        "historical_close3_plate_count",
        "historical_close5_plate_count",
        "expected_chance_within_5_from_local60",
        "closest_historical_sep_arcsec",
        "closest_historical_plate_id",
        "closest_reference_total_detections_in_sample",
        "closest_reference_close5_detections_in_sample",
        "closest_reference_close5_fraction_in_sample",
        "closest_reference_median_sep_arcsec",
        "comparative_note",
    ]
    with OUT_CSV.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=csv_fields, extrasaction="ignore")
        w.writeheader()
        for p in profiles:
            row = dict(p)
            row["dominated_by_ranks"] = ",".join(map(str, p["dominated_by_ranks"]))
            row["dominates_ranks"] = ",".join(map(str, p["dominates_ranks"]))
            w.writerow(row)

    md = []
    md.append("# ORDER 01 — Branch-A Candidate-Specific Adjudication v028f")
    md.append("")
    md.append(
        "Comparative synthesis of the six frozen post-1024 Branch-A survivors. "
        "No weighted overall score is used."
    )
    md.append("")
    md.append("## Guardrails")
    md.append("")
    md.append("- No network access.")
    md.append("- No science pixels read.")
    md.append("- No detector rerun.")
    md.append("- No candidate promoted or deleted.")
    md.append("- Pareto status is **not** an astrophysical promotion/rejection.")
    md.append("")
    md.append("## Declared comparative axes")
    md.append("")
    md.append("- Pair separation: smaller is favourable.")
    md.append("- Two-endpoint SNR floor: larger is favourable.")
    md.append("- Matched-peer continuous morphology extreme count: smaller is favourable.")
    md.append("- Endpoints above all tested 90%-recovery thresholds: larger is favourable.")
    md.append("- Historical <=5 arcsec plate count after 1024: smaller is favourable.")
    md.append("")
    md.append("## Comparative result")
    md.append("")
    md.append(
        "Pareto frontier: **" + ", ".join(f"#{r}" for r in frontier) + "**"
    )
    if dominated:
        md.append(
            "Pareto-dominated on the declared axes: **"
            + ", ".join(f"#{r}" for r in dominated)
            + "**"
        )
    else:
        md.append("No candidate is Pareto-dominated on the declared axes.")
    md.append("")
    md.append(
        "| rank | sep \" | SNR P/D | floor | morph ext P/D | inj robust endpoints | hist <=5/1024 | Pareto |"
    )
    md.append("|---:|---:|---:|---:|---:|---:|---:|---|")
    for p in profiles:
        md.append(
            f"| #{p['strict_rank']} | {p['pair_separation_arcsec']:.3f} | "
            f"{p['poss_snr']:.2f}/{p['dasch_snr']:.2f} | {p['snr_floor']:.2f} | "
            f"{p['poss_morph_extreme_continuous_count']}/"
            f"{p['dasch_morph_extreme_continuous_count']} | "
            f"{p['injection_robust_endpoint_count']}/2 | "
            f"{p['historical_close5_plate_count']}/1024 | "
            f"{p['pareto_status']} |"
        )
    md.append("")
    md.append("## Candidate profiles")
    md.append("")
    for p in profiles:
        md.append(f"### Strict #{p['strict_rank']}")
        md.append("")
        md.append(p["comparative_note"])
        md.append("")
        if p["historical_close5_plate_count"] == 1:
            frac = p["closest_reference_close5_fraction_in_sample"]
            frac_text = (
                f"{p['closest_reference_close5_detections_in_sample']}/"
                f"{p['closest_reference_total_detections_in_sample']}"
                if frac is not None else "n/a"
            )
            md.append(
                f"- Historical close hit: `{p['closest_historical_plate_id']}` at "
                f"{p['closest_historical_sep_arcsec']:.3f}\"; the associated reference "
                f"was within 5\" on {frac_text} detections in the reached sample; "
                f"reference median separation "
                f"{p['closest_reference_median_sep_arcsec']:.3f}\"."
            )
        else:
            md.append("- Historical close hit: none within 5\" in 1024 completed plates.")
        if p["dominated_by_ranks"]:
            md.append(
                "- Pareto-dominated by: "
                + ", ".join(f"#{x}" for x in p["dominated_by_ranks"])
                + "."
            )
        if p["dominates_ranks"]:
            md.append(
                "- Pareto-dominates: "
                + ", ".join(f"#{x}" for x in p["dominates_ranks"])
                + "."
            )
        md.append("")

    md.append("## Interpretation")
    md.append("")
    md.append(
        "The frontier is intentionally broad because different candidates lead on "
        "different independent evidence axes. A candidate remains unresolved unless "
        "and until a later, explicitly defined physical/plate test changes that state."
    )
    md.append("")
    OUT_MD.write_text("\n".join(md), encoding="utf-8")

    print("Frozen survivors:", EXPECTED)
    print("Catalogue/static cross-checks: joined")
    print("Morphology cross-checks: joined")
    print("Injection/recovery cross-checks: joined")
    print("1024-plate recurrence cross-checks: joined")
    print()
    print("Comparative evidence table:")
    print("-" * 112)
    for p in profiles:
        dom = ",".join(map(str, p["dominated_by_ranks"])) or "-"
        print(
            f"#{p['strict_rank']:>2} "
            f"sep={p['pair_separation_arcsec']:.3f}\" "
            f"SNR={p['poss_snr']:.2f}/{p['dasch_snr']:.2f} "
            f"floor={p['snr_floor']:.2f} "
            f"morph_ext={p['poss_morph_extreme_continuous_count']}/"
            f"{p['dasch_morph_extreme_continuous_count']} "
            f"inj90={p['injection_robust_endpoint_count']}/2 "
            f"hist5={p['historical_close5_plate_count']}/1024 "
            f"Pareto={'FRONTIER' if not p['dominated_by_ranks'] else 'DOMINATED'} "
            f"by={dom}"
        )

    print()
    print("Axis leaders:")
    for field, ranks in leaders.items():
        print(f"  {field}: {ranks}")
    print()
    print("Pareto frontier:", frontier)
    print("Pareto dominated:", dominated if dominated else "none")
    print()
    print("Outputs:")
    print(f"  {OUT_JSON}")
    print(f"  {OUT_CSV}")
    print(f"  {OUT_MD}")
    print()
    print("No external query was made.")
    print("No science pixel was read.")
    print("No detector was rerun.")
    print("No candidate was promoted or deleted.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
