#!/usr/bin/env python3
"""
ORDER 01 — historical close-hit calibration v028g

Consumes:
    results/order01_native_full_v028/order01_branchA_candidate_adjudication_v028f.json

Purpose
-------
Calibrate the 0/1024 and 1/1024 historical <=5 arcsec observations against
the already-recorded local <=60 arcsec source density, and quantify how
well-characterised each single close hit is for its associated reference.

This stage is diagnostic only.

It DOES NOT:
  * access the network
  * read science pixels
  * rerun a detector
  * promote or delete candidates
  * treat the nominal area model as a formal astrophysical p-value
  * assume repeated plate detections are statistically independent in reality

Nominal local-area model
------------------------
Conditional on a detection lying somewhere within a 60 arcsec radius,
a spatially uniform position has

    p(within 5") = area(5") / area(60") = (5/60)^2 = 1/144.

The existing stage-3 field
    expected_chance_within_5_from_local60
is therefore expected to equal
    total_sources_within_60arcsec / 144.

We verify that identity, then compute an exact Binomial lower-tail diagnostic:
    P(X <= observed | n = local detections, p = 1/144)

This is deliberately named NOMINAL_AREA_LOWER_TAIL, not "significance",
because detections across plates can be correlated and the local sky is not
spatially uniform.

For the four single-close-hit candidates, we also preserve the empirical
same-reference context and compute a Wilson 95% interval for the fraction of
that reference's reached-sample detections falling within 5 arcsec.
"""

from __future__ import annotations

import csv
import json
import math
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "results" / "order01_native_full_v028"

INPUT = RESULTS / "order01_branchA_candidate_adjudication_v028f.json"
OUT_JSON = RESULTS / "order01_historical_closehit_calibration_v028g.json"
OUT_CSV = RESULTS / "order01_historical_closehit_calibration_v028g.csv"
OUT_MD = RESULTS / "ORDER01_HISTORICAL_CLOSEHIT_CALIBRATION_V028G.md"

EXPECTED_RANKS = [10, 24, 25, 26, 29, 30]
P_AREA_5_GIVEN_60 = (5.0 / 60.0) ** 2
Z95 = 1.959963984540054


def binom_cdf_leq(k: int, n: int, p: float) -> float:
    """
    Exact lower tail P(X <= k) with a stable recurrence, avoiding huge comb().
    Suitable here because k is only 0 or 1.
    """
    if k < 0:
        return 0.0
    if k >= n:
        return 1.0

    q = 1.0 - p
    term = q ** n  # P(X=0)
    total = term
    for i in range(0, k):
        # P(X=i+1) from P(X=i)
        term *= ((n - i) / (i + 1)) * (p / q)
        total += term
    return min(1.0, max(0.0, total))


def wilson_interval(k: int, n: int, z: float = Z95) -> tuple[float, float]:
    if n <= 0:
        raise ValueError("n must be > 0")
    phat = k / n
    z2 = z * z
    denom = 1.0 + z2 / n
    center = (phat + z2 / (2.0 * n)) / denom
    half = (
        z
        * math.sqrt((phat * (1.0 - phat) / n) + z2 / (4.0 * n * n))
        / denom
    )
    return max(0.0, center - half), min(1.0, center + half)


def closehit_context_label(k: int, n: int | None) -> str:
    if k == 0:
        return "NO_CLOSE5_HIT"
    if n is None:
        return "SINGLE_CLOSE5_HIT_REFERENCE_SAMPLE_UNAVAILABLE"
    if n < 20:
        return "SINGLE_CLOSE5_HIT_REFERENCE_SAMPLE_SPARSE"
    if n < 100:
        return "SINGLE_CLOSE5_HIT_REFERENCE_SAMPLE_MODERATE"
    return "SINGLE_CLOSE5_HIT_REFERENCE_SAMPLE_LARGE"


def main() -> int:
    print("=" * 116)
    print("ORDER 01 — HISTORICAL CLOSE-HIT CALIBRATION v028g")
    print("=" * 116)

    if not INPUT.exists():
        print(f"FAIL: missing input: {INPUT}")
        return 2

    data = json.loads(INPUT.read_text(encoding="utf-8"))

    if data.get("frozen_active_ranks") != EXPECTED_RANKS:
        print("FAIL: frozen survivor set mismatch.")
        print(f"      input:    {data.get('frozen_active_ranks')}")
        print(f"      expected: {EXPECTED_RANKS}")
        return 3

    profiles = data.get("profiles") or []
    if [p.get("strict_rank") for p in profiles] != EXPECTED_RANKS:
        print("FAIL: profile rank order/set mismatch.")
        return 4

    rows = []
    for p in profiles:
        rank = int(p["strict_rank"])
        n60 = int(p["total_sources_within_60arcsec"])
        observed5 = int(p["historical_close5_plate_count"])
        recorded_expected5 = float(p["expected_chance_within_5_from_local60"])

        model_expected5 = n60 * P_AREA_5_GIVEN_60
        if not math.isclose(
            recorded_expected5, model_expected5, rel_tol=0.0, abs_tol=1e-10
        ):
            print(
                f"FAIL: rank {rank}: recorded expected5={recorded_expected5} "
                f"does not equal n60/144={model_expected5}"
            )
            return 5

        lower_tail = binom_cdf_leq(
            observed5, n60, P_AREA_5_GIVEN_60
        )
        obs_exp_ratio = (
            observed5 / model_expected5 if model_expected5 > 0 else None
        )

        ref_n = p.get("closest_reference_total_detections_in_sample")
        ref_k = p.get("closest_reference_close5_detections_in_sample")
        if ref_n is not None:
            ref_n = int(ref_n)
        if ref_k is not None:
            ref_k = int(ref_k)

        wilson_lo = wilson_hi = None
        ref_fraction = None
        if ref_n and ref_k is not None:
            ref_fraction = ref_k / ref_n
            wilson_lo, wilson_hi = wilson_interval(ref_k, ref_n)

        row = {
            "strict_rank": rank,
            "pair_separation_arcsec": float(p["pair_separation_arcsec"]),
            "historical_close5_observed": observed5,
            "local60_detection_count": n60,
            "nominal_uniform_area_probability_5_given_60":
                P_AREA_5_GIVEN_60,
            "nominal_expected_close5": model_expected5,
            "observed_to_nominal_expected_ratio": obs_exp_ratio,
            "nominal_area_lower_tail_p_x_le_observed": lower_tail,
            "nominal_area_model_interpretation":
                "OBSERVED_BELOW_NOMINAL_LOCAL_AREA_EXPECTATION"
                if observed5 < model_expected5
                else "OBSERVED_AT_OR_ABOVE_NOMINAL_LOCAL_AREA_EXPECTATION",
            "closest_historical_sep_arcsec":
                p.get("closest_historical_sep_arcsec"),
            "closest_historical_plate_id":
                p.get("closest_historical_plate_id", ""),
            "closest_historical_refcat":
                p.get("closest_historical_refcat", ""),
            "closest_historical_ref_number":
                p.get("closest_historical_ref_number", ""),
            "closest_reference_total_detections_in_sample": ref_n,
            "closest_reference_close5_detections_in_sample": ref_k,
            "closest_reference_close5_fraction_in_sample": ref_fraction,
            "closest_reference_close5_fraction_wilson95_low": wilson_lo,
            "closest_reference_close5_fraction_wilson95_high": wilson_hi,
            "closest_reference_median_sep_arcsec":
                p.get("closest_reference_median_sep_arcsec"),
            "closehit_reference_context_label":
                closehit_context_label(observed5, ref_n),
            "frozen_pareto_status": p["pareto_status"],
        }
        rows.append(row)

    payload = {
        "stage": "ORDER01_HISTORICAL_CLOSEHIT_CALIBRATION_V028G",
        "input": str(INPUT.relative_to(ROOT)),
        "frozen_active_ranks": EXPECTED_RANKS,
        "guards": {
            "network_access": False,
            "science_pixels_read": False,
            "detector_rerun": False,
            "candidate_promotion": False,
            "candidate_deletion": False,
            "formal_astrophysical_p_value_claimed": False,
        },
        "nominal_area_model": {
            "conditional_radius_arcsec": 60.0,
            "close_radius_arcsec": 5.0,
            "p_close_given_local_uniform": P_AREA_5_GIVEN_60,
            "formula": "(5/60)^2 = 1/144",
            "warning": (
                "The exact-binomial lower-tail value is a geometry/density "
                "diagnostic only. Repeated plate detections may be correlated, "
                "fixed astronomical sources violate spatial uniformity, and this "
                "must not be reported as a formal astrophysical significance."
            ),
        },
        "rows": rows,
        "interpretive_guardrail": (
            "A single <=5 arcsec historical hit is not positive recurrence "
            "evidence merely because it exists. Its meaning must be judged "
            "against local chance density, repeated-reference behaviour, plate "
            "geometry, and any later pixel-level review."
        ),
    }
    OUT_JSON.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    fields = list(rows[0].keys())
    with OUT_CSV.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)

    md = []
    md.append("# ORDER 01 — Historical Close-Hit Calibration v028g")
    md.append("")
    md.append(
        "Diagnostic calibration of the frozen six Branch-A survivors' "
        "0/1024 or 1/1024 historical <=5 arcsec observations."
    )
    md.append("")
    md.append("## Guardrails")
    md.append("")
    md.append("- No network access.")
    md.append("- No science pixels read.")
    md.append("- No detector rerun.")
    md.append("- No candidate promoted or deleted.")
    md.append(
        "- The nominal area lower-tail value is **not** a formal "
        "astrophysical p-value."
    )
    md.append("")
    md.append("## Nominal local-area model")
    md.append("")
    md.append(
        "Conditional on a local detection lying uniformly within 60 arcsec, "
        "the area fraction inside 5 arcsec is `(5/60)^2 = 1/144`."
    )
    md.append("")
    md.append(
        "All six existing `expected_chance_within_5_from_local60` values were "
        "verified against `total_sources_within_60arcsec / 144`."
    )
    md.append("")
    md.append(
        "| rank | observed <=5 | local <=60 detections | nominal expected <=5 | "
        "obs/exp | nominal P(X<=obs) |"
    )
    md.append("|---:|---:|---:|---:|---:|---:|")
    for r in rows:
        ratio = r["observed_to_nominal_expected_ratio"]
        md.append(
            f"| #{r['strict_rank']} | {r['historical_close5_observed']} | "
            f"{r['local60_detection_count']} | "
            f"{r['nominal_expected_close5']:.3f} | "
            f"{ratio:.3f} | "
            f"{r['nominal_area_lower_tail_p_x_le_observed']:.6f} |"
        )

    md.append("")
    md.append("## Single-hit reference context")
    md.append("")
    md.append(
        "For single-hit candidates, the same reference's reached-sample "
        "behaviour is shown separately. This is descriptive and does not assume "
        "the reference detections are independent."
    )
    md.append("")
    md.append(
        "| rank | hit sep | reference close/total | fraction | Wilson 95% | "
        "reference median sep | context |"
    )
    md.append("|---:|---:|---:|---:|---:|---:|---|")
    for r in rows:
        if r["historical_close5_observed"] == 0:
            continue
        lo = r["closest_reference_close5_fraction_wilson95_low"]
        hi = r["closest_reference_close5_fraction_wilson95_high"]
        md.append(
            f"| #{r['strict_rank']} | "
            f"{float(r['closest_historical_sep_arcsec']):.3f}\" | "
            f"{r['closest_reference_close5_detections_in_sample']}/"
            f"{r['closest_reference_total_detections_in_sample']} | "
            f"{100*r['closest_reference_close5_fraction_in_sample']:.3f}% | "
            f"{100*lo:.3f}%–{100*hi:.3f}% | "
            f"{float(r['closest_reference_median_sep_arcsec']):.3f}\" | "
            f"{r['closehit_reference_context_label']} |"
        )

    md.append("")
    md.append("## Interpretation boundary")
    md.append("")
    md.append(
        "The local-area calculation asks only whether 0 or 1 close detections "
        "is an excess relative to a simple geometric density model. It does not "
        "establish independence, source identity, or transient reality."
    )
    md.append("")
    md.append(
        "The next physical adjudication should therefore inspect the actual "
        "single-hit geometry/plate context for #10, #25, #26 and #30, while "
        "#24 and #29 have no <=5 arcsec historical hit to explain."
    )
    md.append("")
    OUT_MD.write_text("\n".join(md), encoding="utf-8")

    print("Frozen survivors:", EXPECTED_RANKS)
    print("Nominal local area fraction P(r<=5 | r<=60): 1/144")
    print("Existing expected-count identity checks: PASS")
    print()
    print("Historical close-hit calibration:")
    print("-" * 116)
    for r in rows:
        ratio = r["observed_to_nominal_expected_ratio"]
        print(
            f"#{r['strict_rank']:>2} "
            f"obs5={r['historical_close5_observed']}/1024 "
            f"local60={r['local60_detection_count']:>4} "
            f"nominal_exp5={r['nominal_expected_close5']:.3f} "
            f"obs/exp={ratio:.3f} "
            f"nominal_lower_tail={r['nominal_area_lower_tail_p_x_le_observed']:.6f}"
        )

    print()
    print("Single-hit same-reference context:")
    print("-" * 116)
    for r in rows:
        if r["historical_close5_observed"] == 0:
            print(f"#{r['strict_rank']:>2} no <=5\" historical hit")
            continue
        lo = r["closest_reference_close5_fraction_wilson95_low"]
        hi = r["closest_reference_close5_fraction_wilson95_high"]
        print(
            f"#{r['strict_rank']:>2} "
            f"hit={float(r['closest_historical_sep_arcsec']):.3f}\" "
            f"ref_close={r['closest_reference_close5_detections_in_sample']}/"
            f"{r['closest_reference_total_detections_in_sample']} "
            f"({100*r['closest_reference_close5_fraction_in_sample']:.3f}%, "
            f"Wilson95 {100*lo:.3f}-{100*hi:.3f}%) "
            f"median_sep={float(r['closest_reference_median_sep_arcsec']):.3f}\" "
            f"context={r['closehit_reference_context_label']}"
        )

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
    print("Nominal area lower-tail values are diagnostic only.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
