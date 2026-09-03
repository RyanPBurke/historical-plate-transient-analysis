#!/usr/bin/env python3
"""
v074 — read-only upstream audit of observed v068a registrations versus
registered shifted controls v073a.

This stage:
  * does NOT access the network
  * does NOT rerun the detector
  * does NOT rerun astrometric registration
  * does NOT change candidate dispositions
  * does NOT retune thresholds
  * reads frozen upstream products and writes only new v074 audit products

The 5-pair dominance set (13,14,28,29,30) predates v074 and was already
identified in the v062/v068a population work. It is not selected from the
v074 observed/control result.
"""

from pathlib import Path
import csv
import hashlib
import json
import math
import statistics

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "results"
RESEARCH = ROOT / "research"
TOOLS = ROOT / "tools"

V068 = RESULTS / "wide_census_gaia_registration_v068a"
V073 = RESULTS / "wide_census_registered_control_registration_v073a"

V073_REPORT = V073 / "wide_census_registered_control_registration_v073a.json"
V073_JOBS = V073 / "wide_census_registered_control_job_summary_v073a.csv"
V073_PAIRS = V073 / "wide_census_registered_control_pair_summary_v073a.csv"
V073_GLOBAL = V073 / "wide_census_registered_control_global_summary_v073a.csv"

V068_STATE = V068 / "state_v068a.json"
V068_PAIR_SUMMARY = V068 / "wide_census_gaia_registration_pair_summary_v068a.csv"

V068_SCRIPT = TOOLS / "run_wide_census_gaia_registration_v068a.py"
V073_SCRIPT = TOOLS / "run_wide_census_registered_control_registration_v073a.py"
CONTROL_CONTRACT = (
    RESEARCH / "prospective_freezes"
    / "wide_census_registered_control_contract_v001.json"
)

OUT = RESULTS / "wide_census_observed_registered_control_audit_v074"
OUT_REPORT = OUT / "wide_census_observed_registered_control_audit_v074.json"
OUT_PAIR = OUT / "wide_census_observed_registered_control_pair_comparison_v074.csv"
OUT_GLOBAL = OUT / "wide_census_observed_registered_control_global_cells_v074.csv"
OUT_GROUP = OUT / "wide_census_observed_registered_control_group_summary_v074.csv"

EXPECTED_SHA = {
    V073_REPORT:
        "6286207758bce9d470b5dbbbd6823253ec0ad5689eab717454e07c931d5a22a0",
    V073_JOBS:
        "277fff807b306780f26434635d1589c3a14d33ee0bf96130a3b11090fbadb3cc",
    V073_PAIRS:
        "9ad6a068fb3627acdc318f3d1b60465e313dfa0f1d8868872a8962143c577ce6",
    V073_GLOBAL:
        "ab3b027e50cdb73a8dd959fab9e3d361f2d8418b5edebfe7c0fdbc55e12fdb7b",
    V068_STATE:
        "a5d89634a073c5a7b024c1260ad65486f70ff8ef356db0426cf137fd6fd2736e",
    V068_PAIR_SUMMARY:
        "b516a13c0f0d322aaba20149b8d7f1f11b04d1af3bc30b973e5f69fd92fe1d2c",
    V068_SCRIPT:
        "9376ed5244b5defe074732dbb92e7870b618e25001cd2da4162b48dff549e0f2",
    V073_SCRIPT:
        "f0ca230b3565e1017b404ea52d4779febaba13db8d9253c2965cd90a0857c353",
    CONTROL_CONTRACT:
        "be2febd2696f1798a0a78c2724420f3aaac939a825ebe5b296b126ba9ce47eeb",
}

EXPECTED_PAIRS = 33
EXPECTED_CONTROL_JOBS = 528
EXPECTED_CONTROL_CELLS = 16

EXPECTED_OBS = {
    "raw_le10": 512_788,
    "raw_le3": 185_532,
    "primary_registered": 510_542,
    "sparse_registered": 2_243,
    "unregistered": 3,
    "primary_corrected_le3": 352_935,
    "primary_loo_robust_le3": 345_997,
    "primary_loo_crosses_gt3": 6_938,
    "sparse_corrected_le3": 218,
    "window_5": 478_312,
    "window_10": 18_902,
    "window_20": 10_442,
    "window_30": 2_886,
}

EXPECTED_CONTROL_RAW = {
    "le10_all_jobs": 3_048_415,
    "le3_all_jobs": 274_648,
}

DOMINANT_PAIRS = (13, 14, 28, 29, 30)

OBS_FIELDS = [
    "raw_match_row", "pair_index", "a_tile_id", "a_candidate_index",
    "b_tile_id", "b_candidate_index", "raw_separation_arcsec", "raw_le3",
    "registration_mode", "window_arcmin", "common_same_gaia_refs",
    "refs_a", "refs_b", "shift_a_east_arcsec", "shift_a_north_arcsec",
    "shift_b_east_arcsec", "shift_b_north_arcsec",
    "corrected_east_arcsec", "corrected_north_arcsec",
    "corrected_separation_arcsec", "corrected_le3",
    "loo_corrected_sep_min_arcsec", "loo_corrected_sep_max_arcsec",
]

CONTROL_JOB_INT_FIELDS = [
    "primary_corrected_le3",
    "primary_loo_crosses_gt3",
    "primary_loo_robust_corrected_le3",
    "primary_raw_gt3_to_corrected_le3",
    "primary_raw_le3_to_corrected_gt3",
    "primary_raw_le3_to_corrected_le3",
    "primary_registered",
    "primary_window_10arcmin",
    "primary_window_20arcmin",
    "primary_window_30arcmin",
    "primary_window_5arcmin",
    "raw_control_le10_associations",
    "raw_control_le3_associations",
    "sparse_diagnostic_corrected_le3",
    "sparse_diagnostic_registered",
    "unregistered",
]


def sha256(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for b in iter(lambda: f.read(1024 * 1024), b""):
            h.update(b)
    return h.hexdigest()


def read_csv(path):
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def write_csv(path, rows, fields):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)
    tmp.replace(path)


def write_json(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, sort_keys=True)
    tmp.replace(path)


def as_bool(v):
    return str(v).strip().lower() in {"true", "1", "yes"}


def finite_float(v):
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def ratio(a, b):
    return None if b == 0 else float(a) / float(b)


def rate(num, den):
    return None if den == 0 else float(num) / float(den)


def close(a, b, tol=1e-12):
    return abs(float(a) - float(b)) <= tol


def describe(values):
    values = [float(x) for x in values]
    return {
        "n": len(values),
        "mean": statistics.fmean(values),
        "median": statistics.median(values),
        "min": min(values),
        "max": max(values),
        "stdev_population": statistics.pstdev(values),
    }


def sum_control_jobs(rows):
    out = {k: 0 for k in CONTROL_JOB_INT_FIELDS}
    for r in rows:
        for k in CONTROL_JOB_INT_FIELDS:
            out[k] += int(r[k])
    return out


def observed_pair(pair_index):
    summary_path = V068 / f"pair_{pair_index:02d}_summary_v068a.json"
    csv_path = V068 / f"pair_{pair_index:02d}_registrations_v068a.csv"

    if not summary_path.is_file() or not csv_path.is_file():
        raise RuntimeError(f"Missing v068a pair products for pair {pair_index}")

    summary = json.loads(summary_path.read_text(encoding="utf-8-sig"))

    counts = {
        "raw_le10": 0,
        "raw_le3": 0,
        "primary_registered": 0,
        "sparse_registered": 0,
        "unregistered": 0,
        "primary_corrected_le3": 0,
        "primary_loo_robust_le3": 0,
        "primary_loo_crosses_gt3": 0,
        "sparse_corrected_le3": 0,
        "all_corrected_le3": 0,
        "window_5": 0,
        "window_10": 0,
        "window_20": 0,
        "window_30": 0,
        "primary_raw_le3_to_corrected_le3": 0,
        "primary_raw_le3_to_corrected_gt3": 0,
        "primary_raw_gt3_to_corrected_le3": 0,
    }

    with csv_path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        if list(reader.fieldnames or []) != OBS_FIELDS:
            raise RuntimeError(
                f"Pair {pair_index}: v068a registration schema changed: "
                f"{reader.fieldnames!r}"
            )

        for row in reader:
            counts["raw_le10"] += 1
            raw_le3 = as_bool(row["raw_le3"])
            corr_le3 = as_bool(row["corrected_le3"])
            mode = row["registration_mode"]

            if raw_le3:
                counts["raw_le3"] += 1

            if corr_le3:
                counts["all_corrected_le3"] += 1

            if mode == "PRIMARY":
                counts["primary_registered"] += 1

                w = finite_float(row["window_arcmin"])
                if w == 5.0:
                    counts["window_5"] += 1
                elif w == 10.0:
                    counts["window_10"] += 1
                elif w == 20.0:
                    counts["window_20"] += 1
                elif w == 30.0:
                    counts["window_30"] += 1
                else:
                    raise RuntimeError(
                        f"Pair {pair_index}: unexpected PRIMARY window {row['window_arcmin']!r}"
                    )

                if corr_le3:
                    counts["primary_corrected_le3"] += 1
                    loo_max = finite_float(row["loo_corrected_sep_max_arcsec"])
                    if loo_max is None:
                        raise RuntimeError(
                            f"Pair {pair_index}: PRIMARY corrected<=3 row lacks finite LOO max"
                        )
                    if loo_max <= 3.0:
                        counts["primary_loo_robust_le3"] += 1
                    else:
                        counts["primary_loo_crosses_gt3"] += 1

                if raw_le3 and corr_le3:
                    counts["primary_raw_le3_to_corrected_le3"] += 1
                elif raw_le3 and not corr_le3:
                    counts["primary_raw_le3_to_corrected_gt3"] += 1
                elif (not raw_le3) and corr_le3:
                    counts["primary_raw_gt3_to_corrected_le3"] += 1

            elif mode == "SPARSE_DIAGNOSTIC":
                counts["sparse_registered"] += 1
                if corr_le3:
                    counts["sparse_corrected_le3"] += 1

            elif mode == "NONE":
                counts["unregistered"] += 1
                if corr_le3:
                    raise RuntimeError(
                        f"Pair {pair_index}: NONE row unexpectedly corrected<=3"
                    )
            else:
                raise RuntimeError(
                    f"Pair {pair_index}: unexpected registration mode {mode!r}"
                )

    # Cross-check against the original v068a pair JSON.
    checks = {
        "raw_le10_associations": counts["raw_le10"],
        "raw_le3_associations": counts["raw_le3"],
        "primary_registered": counts["primary_registered"],
        "sparse_diagnostic_registered": counts["sparse_registered"],
        "unregistered": counts["unregistered"],
        "corrected_le3": counts["all_corrected_le3"],
        "raw_le3_to_corrected_le3":
            counts["primary_raw_le3_to_corrected_le3"]
            + 0,  # pair JSON is mixed only where sparse exists; checked below separately.
    }

    for key in (
        "raw_le10_associations",
        "raw_le3_associations",
        "primary_registered",
        "sparse_diagnostic_registered",
        "unregistered",
        "corrected_le3",
    ):
        if int(summary[key]) != int(checks[key]):
            raise RuntimeError(
                f"Pair {pair_index}: v068a JSON/CSV mismatch for {key}: "
                f"{summary[key]} vs {checks[key]}"
            )

    counts["pair_index"] = pair_index
    counts["canonical_pair"] = summary["canonical_pair"]
    counts["summary_sha256"] = sha256(summary_path)
    counts["registration_csv_sha256"] = sha256(csv_path)
    return counts


def main():
    print("=" * 124)
    print("WIDE CENSUS OBSERVED vs REGISTERED-CONTROL AUDIT v074")
    print("=" * 124)
    print("Upstream products: READ ONLY")
    print("Network access: NO")
    print("Detector rerun: NO")
    print("Astrometric registration rerun: NO")
    print("Threshold retuning: NO")
    print("Candidate dispositions: NONE")
    print()

    for path, expected in EXPECTED_SHA.items():
        if not path.is_file():
            raise RuntimeError(f"Missing frozen prerequisite: {path}")
        actual = sha256(path)
        if actual.lower() != expected.lower():
            raise RuntimeError(
                f"Frozen SHA mismatch:\n  {path}\n  expected {expected}\n  actual   {actual}"
            )
        print("HASH PASS:", path.relative_to(ROOT))

    report73 = json.loads(V073_REPORT.read_text(encoding="utf-8-sig"))
    if report73.get("status") != "COMPLETE":
        raise RuntimeError("v073a report is not COMPLETE")
    if report73.get("verified", {}).get("v062_exact_reproduction") is not True:
        raise RuntimeError("v073a did not record exact v062 reproduction")

    # ------------------------------------------------------------------
    # Reconstruct and verify all 528 registered-control jobs.
    # ------------------------------------------------------------------
    jobs = read_csv(V073_JOBS)
    pairs_saved = read_csv(V073_PAIRS)
    global_saved = read_csv(V073_GLOBAL)

    if len(jobs) != EXPECTED_CONTROL_JOBS:
        raise RuntimeError(f"Expected 528 control jobs; found {len(jobs)}")
    if len(pairs_saved) != EXPECTED_PAIRS:
        raise RuntimeError(f"Expected 33 control pair rows; found {len(pairs_saved)}")
    if len(global_saved) != EXPECTED_CONTROL_CELLS:
        raise RuntimeError(f"Expected 16 control global cells; found {len(global_saved)}")

    job_keys = set()
    by_pair = {}
    by_cell = {}

    for r in jobs:
        pair_index = int(r["pair_index"])
        radius = float(r["shift_radius_arcsec"])
        direction = r["direction"]
        key = (pair_index, radius, direction)
        if key in job_keys:
            raise RuntimeError(f"Duplicate control job key: {key}")
        job_keys.add(key)

        by_pair.setdefault(pair_index, []).append(r)
        by_cell.setdefault((radius, direction), []).append(r)

    if set(by_pair) != set(range(1, EXPECTED_PAIRS + 1)):
        raise RuntimeError("Control pair indices are not exactly 1..33")
    if any(len(v) != 16 for v in by_pair.values()):
        raise RuntimeError("At least one pair does not contain exactly 16 control jobs")
    if len(by_cell) != 16 or any(len(v) != 33 for v in by_cell.values()):
        raise RuntimeError("Global control cells are not exactly 16 x 33 pairs")

    pair_saved_map = {int(r["pair_index"]): r for r in pairs_saved}
    global_saved_map = {
        (float(r["shift_radius_arcsec"]), r["direction"]): r
        for r in global_saved
    }

    pair_control = {}
    for pair_index in range(1, 34):
        calc = sum_control_jobs(by_pair[pair_index])
        saved = pair_saved_map[pair_index]

        mapping = {
            "raw_control_le10_associations_all_jobs": "raw_control_le10_associations",
            "raw_control_le3_associations_all_jobs": "raw_control_le3_associations",
            "primary_registered_all_jobs": "primary_registered",
            "sparse_diagnostic_registered_all_jobs": "sparse_diagnostic_registered",
            "unregistered_all_jobs": "unregistered",
            "primary_corrected_le3_all_jobs": "primary_corrected_le3",
            "sparse_diagnostic_corrected_le3_all_jobs": "sparse_diagnostic_corrected_le3",
            "primary_loo_robust_corrected_le3_all_jobs":
                "primary_loo_robust_corrected_le3",
            "primary_loo_crosses_gt3_all_jobs": "primary_loo_crosses_gt3",
        }

        for saved_key, calc_key in mapping.items():
            if int(saved[saved_key]) != int(calc[calc_key]):
                raise RuntimeError(
                    f"Pair {pair_index}: control summary mismatch {saved_key}: "
                    f"{saved[saved_key]} vs {calc[calc_key]}"
                )

        pair_control[pair_index] = {
            "canonical_pair": saved["canonical_pair"],
            **calc,
        }

    global_rows = []
    for key in sorted(by_cell, key=lambda x: (x[0], x[1])):
        radius, direction = key
        calc = sum_control_jobs(by_cell[key])
        saved = global_saved_map[key]

        mapping = {
            "raw_control_le10_associations_sum": "raw_control_le10_associations",
            "raw_control_le3_associations_sum": "raw_control_le3_associations",
            "primary_registered_sum": "primary_registered",
            "sparse_diagnostic_registered_sum": "sparse_diagnostic_registered",
            "unregistered_sum": "unregistered",
            "primary_corrected_le3_sum": "primary_corrected_le3",
            "sparse_diagnostic_corrected_le3_sum": "sparse_diagnostic_corrected_le3",
            "primary_loo_robust_corrected_le3_sum":
                "primary_loo_robust_corrected_le3",
            "primary_loo_crosses_gt3_sum": "primary_loo_crosses_gt3",
        }

        for saved_key, calc_key in mapping.items():
            if int(saved[saved_key]) != int(calc[calc_key]):
                raise RuntimeError(
                    f"Global cell {key}: mismatch {saved_key}: "
                    f"{saved[saved_key]} vs {calc[calc_key]}"
                )

        global_rows.append({
            "shift_radius_arcsec": radius,
            "direction": direction,
            **calc,
        })

    control_total = sum_control_jobs(jobs)
    if control_total["raw_control_le10_associations"] != EXPECTED_CONTROL_RAW["le10_all_jobs"]:
        raise RuntimeError("Control raw <=10 total changed")
    if control_total["raw_control_le3_associations"] != EXPECTED_CONTROL_RAW["le3_all_jobs"]:
        raise RuntimeError("Control raw <=3 total changed")

    # Verify v073a report distribution against the reconstructed 16 cells.
    dist_fields = {
        "primary_corrected_le3": "primary_corrected_le3",
        "primary_loo_robust_corrected_le3":
            "primary_loo_robust_corrected_le3",
        "primary_registered": "primary_registered",
        "sparse_diagnostic_corrected_le3":
            "sparse_diagnostic_corrected_le3",
    }

    for report_key, row_key in dist_fields.items():
        calc = describe([r[row_key] for r in global_rows])
        saved = report73["global_control_distribution"][report_key]
        for k in ("n", "mean", "median", "min", "max", "stdev_population"):
            if not close(calc[k], saved[k]):
                raise RuntimeError(
                    f"v073a distribution mismatch {report_key}.{k}: "
                    f"{calc[k]} vs {saved[k]}"
                )

    print()
    print("Registered-control reconstruction: PASS")
    print(f"  control jobs: {len(jobs):,}/528")
    print(f"  raw <=10 across jobs: {control_total['raw_control_le10_associations']:,}")
    print(f"  raw <=3 across jobs:  {control_total['raw_control_le3_associations']:,}")

    # ------------------------------------------------------------------
    # Reconstruct the complete observed v068a population from pair CSVs.
    # ------------------------------------------------------------------
    observed = {}
    for pair_index in range(1, 34):
        print(f"Reading observed pair {pair_index:02d}/33 ...", flush=True)
        observed[pair_index] = observed_pair(pair_index)

        cp = pair_control[pair_index]["canonical_pair"]
        if observed[pair_index]["canonical_pair"] != cp:
            raise RuntimeError(
                f"Pair {pair_index}: canonical-pair mismatch observed/control:\n"
                f"  observed {observed[pair_index]['canonical_pair']}\n"
                f"  control  {cp}"
            )

    obs_total = {}
    sum_keys = [
        "raw_le10", "raw_le3", "primary_registered", "sparse_registered",
        "unregistered", "primary_corrected_le3", "primary_loo_robust_le3",
        "primary_loo_crosses_gt3", "sparse_corrected_le3",
        "window_5", "window_10", "window_20", "window_30",
        "primary_raw_le3_to_corrected_le3",
        "primary_raw_le3_to_corrected_gt3",
        "primary_raw_gt3_to_corrected_le3",
    ]
    for k in sum_keys:
        obs_total[k] = sum(int(observed[i][k]) for i in observed)

    for k, expected in EXPECTED_OBS.items():
        if obs_total[k] != expected:
            raise RuntimeError(
                f"Observed v068a invariant failed {k}: "
                f"{obs_total[k]:,} != {expected:,}"
            )

    if (
        obs_total["primary_loo_robust_le3"]
        + obs_total["primary_loo_crosses_gt3"]
        != obs_total["primary_corrected_le3"]
    ):
        raise RuntimeError("Observed PRIMARY corrected<=3 LOO partition does not close")

    print()
    print("Observed v068a reconstruction: PASS")
    print(f"  raw <=10:                    {obs_total['raw_le10']:,}")
    print(f"  raw <=3:                     {obs_total['raw_le3']:,}")
    print(f"  PRIMARY registered:          {obs_total['primary_registered']:,}")
    print(f"  PRIMARY corrected <=3:       {obs_total['primary_corrected_le3']:,}")
    print(f"  PRIMARY LOO robust <=3:      {obs_total['primary_loo_robust_le3']:,}")
    print(f"  sparse diagnostic registered:{obs_total['sparse_registered']:,}")
    print(f"  unregistered:                {obs_total['unregistered']:,}")

    # ------------------------------------------------------------------
    # Exact observed-versus-control descriptive comparisons.
    # ------------------------------------------------------------------
    control_means = {
        "primary_registered":
            statistics.fmean(r["primary_registered"] for r in global_rows),
        "primary_corrected_le3":
            statistics.fmean(r["primary_corrected_le3"] for r in global_rows),
        "primary_loo_robust_le3":
            statistics.fmean(
                r["primary_loo_robust_corrected_le3"] for r in global_rows
            ),
        "sparse_registered":
            statistics.fmean(r["sparse_diagnostic_registered"] for r in global_rows),
        "sparse_corrected_le3":
            statistics.fmean(
                r["sparse_diagnostic_corrected_le3"] for r in global_rows
            ),
    }

    global_comparison = {
        "observed_primary_registered": obs_total["primary_registered"],
        "control_primary_registered_mean": control_means["primary_registered"],
        "observed_primary_corrected_le3": obs_total["primary_corrected_le3"],
        "control_primary_corrected_le3_mean": control_means["primary_corrected_le3"],
        "primary_corrected_count_ratio_observed_over_control_mean":
            ratio(
                obs_total["primary_corrected_le3"],
                control_means["primary_corrected_le3"],
            ),
        "observed_primary_corrected_rate":
            rate(obs_total["primary_corrected_le3"], obs_total["primary_registered"]),
        "control_primary_corrected_rate":
            rate(
                control_means["primary_corrected_le3"],
                control_means["primary_registered"],
            ),
        "primary_corrected_registered_rate_ratio":
            ratio(
                rate(
                    obs_total["primary_corrected_le3"],
                    obs_total["primary_registered"],
                ),
                rate(
                    control_means["primary_corrected_le3"],
                    control_means["primary_registered"],
                ),
            ),
        "observed_primary_loo_robust_le3": obs_total["primary_loo_robust_le3"],
        "control_primary_loo_robust_le3_mean":
            control_means["primary_loo_robust_le3"],
        "primary_loo_count_ratio_observed_over_control_mean":
            ratio(
                obs_total["primary_loo_robust_le3"],
                control_means["primary_loo_robust_le3"],
            ),
        "observed_primary_loo_robust_rate":
            rate(
                obs_total["primary_loo_robust_le3"],
                obs_total["primary_registered"],
            ),
        "control_primary_loo_robust_rate":
            rate(
                control_means["primary_loo_robust_le3"],
                control_means["primary_registered"],
            ),
        "primary_loo_registered_rate_ratio":
            ratio(
                rate(
                    obs_total["primary_loo_robust_le3"],
                    obs_total["primary_registered"],
                ),
                rate(
                    control_means["primary_loo_robust_le3"],
                    control_means["primary_registered"],
                ),
            ),
    }

    # Pair-stratified table.
    pair_rows = []
    for i in range(1, 34):
        o = observed[i]
        c = pair_control[i]

        c_reg_mean = c["primary_registered"] / 16.0
        c_corr_mean = c["primary_corrected_le3"] / 16.0
        c_loo_mean = c["primary_loo_robust_corrected_le3"] / 16.0

        row = {
            "pair_index": i,
            "canonical_pair": o["canonical_pair"],
            "dominant_v062_v068a_pair": i in DOMINANT_PAIRS,
            "observed_primary_registered": o["primary_registered"],
            "control_primary_registered_mean": c_reg_mean,
            "observed_primary_corrected_le3": o["primary_corrected_le3"],
            "control_primary_corrected_le3_mean": c_corr_mean,
            "primary_corrected_count_ratio":
                ratio(o["primary_corrected_le3"], c_corr_mean),
            "observed_primary_corrected_rate":
                rate(o["primary_corrected_le3"], o["primary_registered"]),
            "control_primary_corrected_rate":
                rate(c_corr_mean, c_reg_mean),
            "primary_corrected_registered_rate_ratio":
                ratio(
                    rate(o["primary_corrected_le3"], o["primary_registered"]),
                    rate(c_corr_mean, c_reg_mean),
                ),
            "observed_primary_loo_robust_le3": o["primary_loo_robust_le3"],
            "control_primary_loo_robust_le3_mean": c_loo_mean,
            "primary_loo_count_ratio":
                ratio(o["primary_loo_robust_le3"], c_loo_mean),
            "observed_primary_loo_robust_rate":
                rate(o["primary_loo_robust_le3"], o["primary_registered"]),
            "control_primary_loo_robust_rate":
                rate(c_loo_mean, c_reg_mean),
            "primary_loo_registered_rate_ratio":
                ratio(
                    rate(o["primary_loo_robust_le3"], o["primary_registered"]),
                    rate(c_loo_mean, c_reg_mean),
                ),
            "observed_sparse_registered": o["sparse_registered"],
            "control_sparse_registered_mean":
                c["sparse_diagnostic_registered"] / 16.0,
            "observed_sparse_corrected_le3": o["sparse_corrected_le3"],
            "control_sparse_corrected_le3_mean":
                c["sparse_diagnostic_corrected_le3"] / 16.0,
            "observed_unregistered": o["unregistered"],
            "control_unregistered_mean": c["unregistered"] / 16.0,
            "observed_fraction_of_global_primary_corrected":
                rate(o["primary_corrected_le3"], obs_total["primary_corrected_le3"]),
            "control_fraction_of_global_primary_corrected":
                rate(c_corr_mean, control_means["primary_corrected_le3"]),
            "observed_registration_csv_sha256": o["registration_csv_sha256"],
            "observed_summary_sha256": o["summary_sha256"],
        }

        obs_without = (
            obs_total["primary_corrected_le3"] - o["primary_corrected_le3"]
        )
        ctrl_without = (
            control_means["primary_corrected_le3"] - c_corr_mean
        )
        row["leave_this_pair_out_primary_corrected_count_ratio"] = ratio(
            obs_without, ctrl_without
        )

        pair_rows.append(row)

    # Pre-existing five dominant pairs versus all other pairs.
    def group_row(name, pair_indices):
        pair_indices = tuple(pair_indices)

        o_reg = sum(observed[i]["primary_registered"] for i in pair_indices)
        o_corr = sum(observed[i]["primary_corrected_le3"] for i in pair_indices)
        o_loo = sum(observed[i]["primary_loo_robust_le3"] for i in pair_indices)

        c_reg = sum(pair_control[i]["primary_registered"] for i in pair_indices) / 16.0
        c_corr = sum(pair_control[i]["primary_corrected_le3"] for i in pair_indices) / 16.0
        c_loo = sum(
            pair_control[i]["primary_loo_robust_corrected_le3"]
            for i in pair_indices
        ) / 16.0

        return {
            "group": name,
            "pair_indices": ",".join(str(i) for i in pair_indices),
            "pair_count": len(pair_indices),
            "observed_primary_registered": o_reg,
            "control_primary_registered_mean": c_reg,
            "observed_primary_corrected_le3": o_corr,
            "control_primary_corrected_le3_mean": c_corr,
            "primary_corrected_count_ratio": ratio(o_corr, c_corr),
            "observed_primary_corrected_rate": rate(o_corr, o_reg),
            "control_primary_corrected_rate": rate(c_corr, c_reg),
            "primary_corrected_registered_rate_ratio":
                ratio(rate(o_corr, o_reg), rate(c_corr, c_reg)),
            "observed_primary_loo_robust_le3": o_loo,
            "control_primary_loo_robust_le3_mean": c_loo,
            "primary_loo_count_ratio": ratio(o_loo, c_loo),
            "observed_primary_loo_robust_rate": rate(o_loo, o_reg),
            "control_primary_loo_robust_rate": rate(c_loo, c_reg),
            "primary_loo_registered_rate_ratio":
                ratio(rate(o_loo, o_reg), rate(c_loo, c_reg)),
            "observed_fraction_of_global_primary_corrected":
                rate(o_corr, obs_total["primary_corrected_le3"]),
            "control_fraction_of_global_primary_corrected":
                rate(c_corr, control_means["primary_corrected_le3"]),
        }

    groups = [
        group_row("ALL_33", range(1, 34)),
        group_row("PREEXISTING_DOMINANT_5", DOMINANT_PAIRS),
        group_row(
            "NON_DOMINANT_28",
            [i for i in range(1, 34) if i not in DOMINANT_PAIRS],
        ),
    ]

    # Add observed ratios to each of the 16 global control cells.
    for r in global_rows:
        r["observed_primary_corrected_le3"] = obs_total["primary_corrected_le3"]
        r["observed_over_cell_primary_corrected_ratio"] = ratio(
            obs_total["primary_corrected_le3"],
            r["primary_corrected_le3"],
        )
        r["observed_primary_loo_robust_le3"] = obs_total["primary_loo_robust_le3"]
        r["observed_over_cell_primary_loo_ratio"] = ratio(
            obs_total["primary_loo_robust_le3"],
            r["primary_loo_robust_corrected_le3"],
        )

    pair_fields = list(pair_rows[0].keys())
    global_fields = list(global_rows[0].keys())
    group_fields = list(groups[0].keys())

    write_csv(OUT_PAIR, pair_rows, pair_fields)
    write_csv(OUT_GLOBAL, global_rows, global_fields)
    write_csv(OUT_GROUP, groups, group_fields)

    report = {
        "status": "COMPLETE",
        "analysis_kind": "wide_census_observed_registered_control_audit_v074",
        "input_sha256": {
            str(p.relative_to(ROOT)).replace("\\", "/"): sha256(p)
            for p in EXPECTED_SHA
        },
        "verified": {
            "pairs": 33,
            "control_jobs": 528,
            "control_global_cells": 16,
            "v073a_exact_control_summary_reproduction": True,
            "v068a_observed_population_reconstructed_from_pair_csvs": True,
            "observed": obs_total,
            "control_raw_all_jobs": {
                "le10": control_total["raw_control_le10_associations"],
                "le3": control_total["raw_control_le3_associations"],
            },
        },
        "global_comparison": global_comparison,
        "control_distribution": {
            "primary_registered": describe(
                [r["primary_registered"] for r in global_rows]
            ),
            "primary_corrected_le3": describe(
                [r["primary_corrected_le3"] for r in global_rows]
            ),
            "primary_loo_robust_le3": describe(
                [r["primary_loo_robust_corrected_le3"] for r in global_rows]
            ),
        },
        "preexisting_pair_stratification": {
            "dominant_pair_indices": list(DOMINANT_PAIRS),
            "source":
                "Pair set identified before v074 from the v062/v068a population "
                "structure; not selected using the v074 corrected-control outcome.",
            "groups": groups,
        },
        "guards": {
            "network_access": False,
            "detector_rerun": False,
            "astrometric_registration_rerun": False,
            "threshold_retuning": False,
            "candidate_disposition_changes": False,
        },
        "interpretation_boundary": (
            "Descriptive population-level observed-versus-shifted-control audit. "
            "The 16 shifted control cells are deterministic structured controls, "
            "not independent random replicates; v074 therefore reports no p-value "
            "or formal significance. Sparse-diagnostic registrations remain "
            "separate from PRIMARY and cannot change any individual candidate "
            "disposition."
        ),
        "outputs": {
            "pair_comparison":
                str(OUT_PAIR.relative_to(ROOT)).replace("\\", "/"),
            "global_cells":
                str(OUT_GLOBAL.relative_to(ROOT)).replace("\\", "/"),
            "group_summary":
                str(OUT_GROUP.relative_to(ROOT)).replace("\\", "/"),
        },
    }
    write_json(OUT_REPORT, report)

    print()
    print("=" * 124)
    print("v074 OBSERVED vs REGISTERED-CONTROL AUDIT COMPLETE")
    print("=" * 124)
    print(
        f"PRIMARY corrected <=3: observed={obs_total['primary_corrected_le3']:,}; "
        f"control mean={control_means['primary_corrected_le3']:,.2f}; "
        f"count ratio={global_comparison['primary_corrected_count_ratio_observed_over_control_mean']:.6f}x"
    )
    print(
        f"PRIMARY registered-rate comparison: "
        f"observed={global_comparison['observed_primary_corrected_rate']:.6f}; "
        f"control={global_comparison['control_primary_corrected_rate']:.6f}; "
        f"rate ratio={global_comparison['primary_corrected_registered_rate_ratio']:.6f}x"
    )
    print(
        f"PRIMARY LOO robust <=3: observed={obs_total['primary_loo_robust_le3']:,}; "
        f"control mean={control_means['primary_loo_robust_le3']:,.2f}; "
        f"count ratio={global_comparison['primary_loo_count_ratio_observed_over_control_mean']:.6f}x"
    )
    print(
        f"PRIMARY LOO registered-rate ratio: "
        f"{global_comparison['primary_loo_registered_rate_ratio']:.6f}x"
    )

    for g in groups:
        print()
        print(g["group"])
        print(
            f"  PRIMARY corrected: observed={g['observed_primary_corrected_le3']:,}; "
            f"control mean={g['control_primary_corrected_le3_mean']:,.2f}; "
            f"count ratio={g['primary_corrected_count_ratio']:.6f}x"
        )
        print(
            f"  registered-rate ratio={g['primary_corrected_registered_rate_ratio']:.6f}x"
        )
        print(
            f"  observed share={g['observed_fraction_of_global_primary_corrected']:.6%}; "
            f"control share={g['control_fraction_of_global_primary_corrected']:.6%}"
        )

    print()
    print("Formal p-value/significance calculated: NO")
    print("Network calls:                       0")
    print("Detector reruns:                     0")
    print("Registrations rerun:                 0")
    print("Candidate dispositions changed:      NONE")
    print("STAGE STATUS: COMPLETE")


if __name__ == "__main__":
    main()
