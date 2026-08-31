from __future__ import annotations

from pathlib import Path
from datetime import datetime, timezone
import csv
import hashlib
import json
import math
import statistics

import numpy as np
from scipy.spatial import cKDTree

ROOT = Path.cwd()

V057 = (
    ROOT / "research" / "prospective_freezes"
    / "wide_census_postdetector_adjudication_contract_v001.json"
)
V061_PLAN = (
    ROOT / "research" / "prospective_freezes"
    / "wide_census_postdetector_execution_plan_v061.json"
)
V056_REPORT = ROOT / "results" / "wide_census_detector_execution_v056.json"
CAND = ROOT / "results" / "wide_census_detector_candidates_v056.csv"
PAIR_SUMMARY = ROOT / "results" / "wide_census_pair_raw_match_summary_v056.csv"
PAIR_PLAN = ROOT / "results" / "wide_census_detector_pair_plan_v054.json"

OUTDIR = ROOT / "results" / "wide_census_population_controls_v062"
STATE = OUTDIR / "state_v062.json"
OUT_JSON = OUTDIR / "wide_census_population_controls_v062.json"
OUT_CONTROLS = OUTDIR / "wide_census_population_controls_v062.csv"
OUT_PAIRS = OUTDIR / "wide_census_population_control_pair_summary_v062.csv"
OUT_GLOBAL = OUTDIR / "wide_census_population_control_global_summary_v062.csv"

EXPECTED_V057_SHA = "1215400b989b187e87ceee27237fd2faf7ccff80dd57632158e06cbed7add2ad"
EXPECTED_V061_PLAN_SHA = "08330cb1c1693e1b40cfb7e41dd35abe721206df3a6437511cb0e642e6b5bfd3"

EXPECTED_CANDIDATES = 5_083_325
EXPECTED_PAIRS = 33
EXPECTED_RAW10 = 512_788
EXPECTED_RAW3 = 185_532

RADII_ARCSEC = (60.0, 120.0)
DIRECTIONS = (
    ("N", 0.0),
    ("NE", 45.0),
    ("E", 90.0),
    ("SE", 135.0),
    ("S", 180.0),
    ("SW", 225.0),
    ("W", 270.0),
    ("NW", 315.0),
)
GATES_ARCSEC = (3.0, 10.0)

CAND_FIELDS_EXPECTED = [
    "endpoint_key", "kind", "exposure", "tile_id", "candidate_index",
    "local_x", "local_y", "global_x", "global_y",
    "ra_deg", "dec_deg", "snr", "signal", "polarity", "sigma",
]


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def read_csv(path):
    with path.open(newline="", encoding="utf-8-sig") as fh:
        return list(csv.DictReader(fh))


def write_json(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(obj, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )
    tmp.replace(path)


def write_csv(path, rows, fields):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    tmp.replace(path)


def fnum(v):
    try:
        x = float(str(v).strip())
        return x if math.isfinite(x) else None
    except Exception:
        return None


def inum(v):
    x = fnum(v)
    return None if x is None else int(x)


def polygon_center(poly):
    vec = []
    for ra, dec in poly:
        r = math.radians(float(ra))
        d = math.radians(float(dec))
        vec.append([
            math.cos(d) * math.cos(r),
            math.cos(d) * math.sin(r),
            math.sin(d),
        ])
    v = np.sum(np.asarray(vec, float), axis=0)
    v /= np.linalg.norm(v)
    ra = math.degrees(math.atan2(v[1], v[0])) % 360.0
    dec = math.degrees(math.asin(float(v[2])))
    return ra, dec


def project_points(ra, dec, cra, cdec):
    r = np.radians(np.asarray(ra, float))
    d = np.radians(np.asarray(dec, float))
    r0, d0 = math.radians(cra), math.radians(cdec)
    cosc = (
        math.sin(d0) * np.sin(d)
        + math.cos(d0) * np.cos(d) * np.cos(r - r0)
    )
    x = np.cos(d) * np.sin(r-r0) / cosc
    y = (
        math.cos(d0) * np.sin(d)
        - math.sin(d0) * np.cos(d) * np.cos(r-r0)
    ) / cosc
    return x, y


def polygon_mask(coords, poly):
    """Exact vectorized equivalent of v056's points_in_polygon."""
    if len(coords) == 0:
        return np.zeros(0, dtype=bool)
    cra, cdec = polygon_center(poly)
    pra = [p[0] for p in poly]
    pdec = [p[1] for p in poly]
    px, py = project_points(pra, pdec, cra, cdec)
    x, y = project_points(coords[:, 0], coords[:, 1], cra, cdec)

    inside = np.zeros(len(coords), dtype=bool)
    n = len(poly)
    j = n - 1
    for k in range(n):
        xi, yi = px[k], py[k]
        xj, yj = px[j], py[j]
        crosses = ((yi > y) != (yj > y))
        # Avoid divide-by-zero on horizontal polygon edges exactly as the
        # scalar v056 routine does by evaluating only crossing edges.
        xint = np.full(len(coords), np.inf, dtype=float)
        valid = crosses
        xint[valid] = (
            (xj - xi) * (y[valid] - yi) / (yj - yi) + xi
        )
        inside ^= (crosses & (x < xint))
        j = k
    return inside


def radec_to_xyz(coords):
    ra = np.radians(coords[:, 0])
    dec = np.radians(coords[:, 1])
    c = np.cos(dec)
    return np.column_stack((
        c * np.cos(ra),
        c * np.sin(ra),
        np.sin(dec),
    ))


def shift_radec(coords, separation_arcsec, pa_deg):
    """
    Exact great-circle directional offset.

    Position angle is east of north:
      N=0, E=90, S=180, W=270.
    """
    ra = np.radians(coords[:, 0])
    dec = np.radians(coords[:, 1])
    s = math.radians(float(separation_arcsec) / 3600.0)
    pa = math.radians(float(pa_deg))

    cosd = np.cos(dec)
    sind = np.sin(dec)
    cosa = np.cos(ra)
    sina = np.sin(ra)

    r = np.column_stack((cosd*cosa, cosd*sina, sind))
    north = np.column_stack((-sind*cosa, -sind*sina, cosd))
    east = np.column_stack((-sina, cosa, np.zeros_like(ra)))
    tangent = math.cos(pa)*north + math.sin(pa)*east

    v = math.cos(s)*r + math.sin(s)*tangent
    # Numerical normalization only; geometrically already unit length.
    v /= np.linalg.norm(v, axis=1)[:, None]
    out_ra = (np.degrees(np.arctan2(v[:, 1], v[:, 0])) % 360.0)
    out_dec = np.degrees(np.arcsin(np.clip(v[:, 2], -1.0, 1.0)))
    return np.column_stack((out_ra, out_dec))


def chord_radius(arcsec):
    theta = math.radians(float(arcsec) / 3600.0)
    return 2.0 * math.sin(theta / 2.0)


R3 = chord_radius(3.0)
R10 = chord_radius(10.0)


def count_pair(tree_a, coords_b):
    if tree_a.n == 0 or len(coords_b) == 0:
        return 0, 0
    tree_b = cKDTree(
        radec_to_xyz(coords_b),
        leafsize=32,
        compact_nodes=True,
        balanced_tree=True,
    )
    counts = tree_a.count_neighbors(
        tree_b,
        np.asarray([R3, R10], dtype=float),
        cumulative=True,
    )
    return int(counts[0]), int(counts[1])


def describe(vals):
    vals = [float(v) for v in vals]
    if not vals:
        return {
            "n": 0, "mean": None, "median": None,
            "min": None, "max": None, "stdev": None,
        }
    return {
        "n": len(vals),
        "mean": statistics.fmean(vals),
        "median": statistics.median(vals),
        "min": min(vals),
        "max": max(vals),
        "stdev": statistics.stdev(vals) if len(vals) > 1 else 0.0,
    }


def state_default():
    return {
        "status": "IN_PROGRESS",
        "completed_pair_indices": [],
        "control_rows": [],
        "pair_rows": [],
        "started_at_utc": datetime.now(timezone.utc).isoformat(),
    }


def load_candidate_arrays():
    """
    Two-pass CSV load. Only RA/Dec are retained, avoiding Python-object
    storage for 5.08 million detector rows.
    """
    counts = {}
    total = 0

    with CAND.open(newline="", encoding="utf-8-sig") as fh:
        rdr = csv.DictReader(fh)
        fields = list(rdr.fieldnames or [])
        if fields != CAND_FIELDS_EXPECTED:
            raise RuntimeError(
                "REFUSING: v056 candidate CSV schema changed: "
                + repr(fields)
            )
        for row in rdr:
            key = row["endpoint_key"]
            counts[key] = counts.get(key, 0) + 1
            total += 1

    if total != EXPECTED_CANDIDATES:
        raise RuntimeError(
            f"REFUSING: expected {EXPECTED_CANDIDATES} candidates, got {total}"
        )

    arrays = {
        key: np.empty((n, 2), dtype=np.float64)
        for key, n in counts.items()
    }
    fill = {key: 0 for key in counts}

    with CAND.open(newline="", encoding="utf-8-sig") as fh:
        rdr = csv.DictReader(fh)
        for row in rdr:
            key = row["endpoint_key"]
            j = fill[key]
            arrays[key][j, 0] = float(row["ra_deg"])
            arrays[key][j, 1] = float(row["dec_deg"])
            fill[key] = j + 1

    if any(fill[k] != counts[k] for k in counts):
        raise RuntimeError("REFUSING: candidate coordinate fill mismatch")

    return arrays, counts


def main():
    print("=" * 132)
    print("WIDE CENSUS — FROZEN SHIFTED POPULATION CONTROLS v062")
    print("=" * 132)
    print("NO NETWORK. NO PIXELS. NO DETECTOR. NO CANDIDATE STATE MUTATION.")
    print("60/120 arcsec x 8 directions; cumulative gates 3 and 10 arcsec.")
    print("Population context only; never an individual-candidate rejection.\n")

    for p in (V057, V061_PLAN, V056_REPORT, CAND, PAIR_SUMMARY, PAIR_PLAN):
        if not p.is_file():
            raise RuntimeError(f"REFUSING: missing prerequisite {p}")

    if sha(V057) != EXPECTED_V057_SHA:
        raise RuntimeError("REFUSING: v057 prospective contract SHA changed")
    if sha(V061_PLAN) != EXPECTED_V061_PLAN_SHA:
        raise RuntimeError(
            "REFUSING: v061 execution-plan SHA changed: " + sha(V061_PLAN)
        )

    v56 = json.loads(V056_REPORT.read_text(encoding="utf-8"))
    if v56.get("status") != "COMPLETE":
        raise RuntimeError("REFUSING: v056 is not complete")
    if int(v56.get("accepted_native_detector_candidates_total", -1)) != EXPECTED_CANDIDATES:
        raise RuntimeError("REFUSING: v056 candidate count changed")
    if int(v56.get("raw_le_10arcsec_match_count", -1)) != EXPECTED_RAW10:
        raise RuntimeError("REFUSING: v056 raw <=10 count changed")
    if int(v56.get("raw_le_3arcsec_match_count", -1)) != EXPECTED_RAW3:
        raise RuntimeError("REFUSING: v056 raw <=3 count changed")

    sums = read_csv(PAIR_SUMMARY)
    plan = json.loads(PAIR_PLAN.read_text(encoding="utf-8")).get("pairs", [])
    if len(sums) != EXPECTED_PAIRS or len(plan) != EXPECTED_PAIRS:
        raise RuntimeError("REFUSING: expected 33 pair rows in summary and plan")

    # Exact pair identity/ordering guard.
    for idx, (s, p) in enumerate(zip(sums, plan), 1):
        if inum(s.get("pair_index")) != idx:
            raise RuntimeError(f"REFUSING: pair summary index mismatch at {idx}")
        if str(s.get("canonical_pair")) != str(p.get("canonical_pair")):
            raise RuntimeError(f"REFUSING: canonical pair mismatch at {idx}")
        if str(s.get("endpoint_a")) != str(p.get("endpoint_a")):
            raise RuntimeError(f"REFUSING: endpoint_a mismatch at {idx}")
        if str(s.get("endpoint_b")) != str(p.get("endpoint_b")):
            raise RuntimeError(f"REFUSING: endpoint_b mismatch at {idx}")

    print("v057 contract SHA: PASS")
    print("v061 execution-plan SHA: PASS")
    print("v056 aggregate guards: PASS")
    print("Pair-plan/summary identities: 33/33 PASS")
    print("\nLoading 5,083,325 candidate RA/Dec values in two passes ...", flush=True)

    arrays, endpoint_counts = load_candidate_arrays()
    print(
        f"Candidate coordinate arrays ready: {len(arrays)} endpoints, "
        f"{sum(endpoint_counts.values())} rows"
    )

    OUTDIR.mkdir(parents=True, exist_ok=True)
    state = (
        json.loads(STATE.read_text(encoding="utf-8"))
        if STATE.is_file()
        else state_default()
    )
    done = set(int(x) for x in state.get("completed_pair_indices", []))
    controls = list(state.get("control_rows", []))
    pair_rows = list(state.get("pair_rows", []))

    # Validate any resumed state against frozen input hashes.
    state_hashes = state.get("input_sha256")
    current_hashes = {
        "v057": sha(V057),
        "v061_plan": sha(V061_PLAN),
        "v056_report": sha(V056_REPORT),
        "candidate_csv": sha(CAND),
        "pair_summary": sha(PAIR_SUMMARY),
        "pair_plan": sha(PAIR_PLAN),
    }
    if state_hashes is not None and state_hashes != current_hashes:
        raise RuntimeError("REFUSING: v062 checkpoint input hashes changed")
    state["input_sha256"] = current_hashes

    observed_global3 = 0
    observed_global10 = 0

    # On resume, rebuild observed totals from pair summary independently.
    for s in sums:
        observed_global3 += int(s["raw_le_3arcsec_matches"])
        observed_global10 += int(s["raw_le_10arcsec_matches"])
    if observed_global3 != EXPECTED_RAW3 or observed_global10 != EXPECTED_RAW10:
        raise RuntimeError("REFUSING: pair-summary raw totals do not match v056")

    for idx, (s, p) in enumerate(zip(sums, plan), 1):
        if idx in done:
            print(f"[{idx:02d}/{EXPECTED_PAIRS}] checkpointed; skipping")
            continue

        ea = str(p["endpoint_a"])
        eb = str(p["endpoint_b"])
        poly = p["common_polygon_icrs_deg"]
        if ea not in arrays or eb not in arrays:
            raise RuntimeError(
                f"REFUSING: pair {idx} references endpoint absent from candidate CSV"
            )

        aa_all = arrays[ea]
        bb_all = arrays[eb]
        aa = aa_all[polygon_mask(aa_all, poly)]
        bb = bb_all[polygon_mask(bb_all, poly)]

        expected_a = int(s["endpoint_a_candidates_in_common_polygon"])
        expected_b = int(s["endpoint_b_candidates_in_common_polygon"])
        if len(aa) != expected_a or len(bb) != expected_b:
            raise RuntimeError(
                f"REFUSING: common-polygon candidate count mismatch pair {idx}: "
                f"A {len(aa)} vs {expected_a}, B {len(bb)} vs {expected_b}"
            )

        tree_a = cKDTree(
            radec_to_xyz(aa),
            leafsize=32,
            compact_nodes=True,
            balanced_tree=True,
        )
        obs3, obs10 = count_pair(tree_a, bb)
        exp3 = int(s["raw_le_3arcsec_matches"])
        exp10 = int(s["raw_le_10arcsec_matches"])
        if obs3 != exp3 or obs10 != exp10:
            raise RuntimeError(
                f"REFUSING: cKDTree reproduction mismatch pair {idx}: "
                f"observed ({obs3},{obs10}) vs v056 ({exp3},{exp10})"
            )

        print(
            f"[{idx:02d}/{EXPECTED_PAIRS}] {p['canonical_pair']} "
            f"A={len(aa)} B={len(bb)} observed3={obs3} observed10={obs10}",
            flush=True,
        )

        local_rows = []
        for radius in RADII_ARCSEC:
            for direction, pa in DIRECTIONS:
                shifted = shift_radec(bb, radius, pa)
                c3, c10 = count_pair(tree_a, shifted)
                rec = {
                    "pair_index": idx,
                    "canonical_pair": p["canonical_pair"],
                    "endpoint_a": ea,
                    "endpoint_b": eb,
                    "detector_coverage_state": s["detector_coverage_state"],
                    "endpoint_a_candidates_in_common_polygon": len(aa),
                    "endpoint_b_candidates_in_common_polygon": len(bb),
                    "shifted_endpoint": "endpoint_b",
                    "shift_radius_arcsec": radius,
                    "direction": direction,
                    "position_angle_deg_east_of_north": pa,
                    "control_le_3arcsec_matches": c3,
                    "control_le_10arcsec_matches": c10,
                    "observed_le_3arcsec_matches": obs3,
                    "observed_le_10arcsec_matches": obs10,
                    "fixed_pre_shift_candidate_denominator": True,
                    "population_context_only": True,
                }
                controls.append(rec)
                local_rows.append(rec)

        vals3 = [r["control_le_3arcsec_matches"] for r in local_rows]
        vals10 = [r["control_le_10arcsec_matches"] for r in local_rows]
        d3 = describe(vals3)
        d10 = describe(vals10)

        pair_row = {
            "pair_index": idx,
            "canonical_pair": p["canonical_pair"],
            "endpoint_a": ea,
            "endpoint_b": eb,
            "detector_coverage_state": s["detector_coverage_state"],
            "observed_le_3arcsec_matches": obs3,
            "control3_mean": d3["mean"],
            "control3_median": d3["median"],
            "control3_min": d3["min"],
            "control3_max": d3["max"],
            "control3_stdev": d3["stdev"],
            "observed_to_control3_mean_ratio": (
                None if not d3["mean"] else obs3 / d3["mean"]
            ),
            "observed_le_10arcsec_matches": obs10,
            "control10_mean": d10["mean"],
            "control10_median": d10["median"],
            "control10_min": d10["min"],
            "control10_max": d10["max"],
            "control10_stdev": d10["stdev"],
            "observed_to_control10_mean_ratio": (
                None if not d10["mean"] else obs10 / d10["mean"]
            ),
            "individual_candidate_disposition": "NONE_POPULATION_CONTEXT_ONLY",
        }
        pair_rows.append(pair_row)

        done.add(idx)
        state.update({
            "status": "IN_PROGRESS",
            "completed_pair_indices": sorted(done),
            "control_rows": controls,
            "pair_rows": pair_rows,
            "last_completed_pair_index": idx,
            "updated_at_utc": datetime.now(timezone.utc).isoformat(),
        })
        write_json(STATE, state)

        print(
            f"             controls: <=3 mean={d3['mean']:.2f} "
            f"range={d3['min']:.0f}-{d3['max']:.0f}; "
            f"<=10 mean={d10['mean']:.2f} "
            f"range={d10['min']:.0f}-{d10['max']:.0f}",
            flush=True,
        )

    if len(done) != EXPECTED_PAIRS:
        raise RuntimeError(
            f"Internal checkpoint error: completed {len(done)}/{EXPECTED_PAIRS}"
        )
    if len(controls) != EXPECTED_PAIRS * 16:
        raise RuntimeError(
            f"REFUSING: expected 528 control rows, got {len(controls)}"
        )
    if len(pair_rows) != EXPECTED_PAIRS:
        raise RuntimeError(
            f"REFUSING: expected 33 pair summaries, got {len(pair_rows)}"
        )

    control_fields = [
        "pair_index", "canonical_pair", "endpoint_a", "endpoint_b",
        "detector_coverage_state",
        "endpoint_a_candidates_in_common_polygon",
        "endpoint_b_candidates_in_common_polygon",
        "shifted_endpoint", "shift_radius_arcsec", "direction",
        "position_angle_deg_east_of_north",
        "control_le_3arcsec_matches", "control_le_10arcsec_matches",
        "observed_le_3arcsec_matches", "observed_le_10arcsec_matches",
        "fixed_pre_shift_candidate_denominator", "population_context_only",
    ]
    pair_fields = list(pair_rows[0].keys())
    write_csv(OUT_CONTROLS, controls, control_fields)
    write_csv(OUT_PAIRS, pair_rows, pair_fields)

    # Aggregate the identically defined shift across all 33 opportunities.
    global_rows = []
    for radius in RADII_ARCSEC:
        for direction, pa in DIRECTIONS:
            subset = [
                r for r in controls
                if float(r["shift_radius_arcsec"]) == radius
                and r["direction"] == direction
            ]
            if len(subset) != EXPECTED_PAIRS:
                raise RuntimeError(
                    f"REFUSING: global control cell {radius}/{direction} "
                    f"has {len(subset)} pairs"
                )
            global_rows.append({
                "shift_radius_arcsec": radius,
                "direction": direction,
                "position_angle_deg_east_of_north": pa,
                "control_le_3arcsec_matches_sum": sum(
                    int(r["control_le_3arcsec_matches"]) for r in subset
                ),
                "control_le_10arcsec_matches_sum": sum(
                    int(r["control_le_10arcsec_matches"]) for r in subset
                ),
                "observed_le_3arcsec_matches": EXPECTED_RAW3,
                "observed_le_10arcsec_matches": EXPECTED_RAW10,
                "pair_count": EXPECTED_PAIRS,
            })
    write_csv(
        OUT_GLOBAL,
        global_rows,
        [
            "shift_radius_arcsec", "direction",
            "position_angle_deg_east_of_north",
            "control_le_3arcsec_matches_sum",
            "control_le_10arcsec_matches_sum",
            "observed_le_3arcsec_matches",
            "observed_le_10arcsec_matches", "pair_count",
        ],
    )

    g3 = describe([r["control_le_3arcsec_matches_sum"] for r in global_rows])
    g10 = describe([r["control_le_10arcsec_matches_sum"] for r in global_rows])

    report = {
        "status": "COMPLETE",
        "analysis_kind": "wide_census_population_controls_v062",
        "completed_at_utc": datetime.now(timezone.utc).isoformat(),
        "guards": {
            "network_access": False,
            "science_pixels_read": False,
            "transient_detector_rerun": False,
            "candidate_state_mutation": False,
            "geometry_state_mutation": False,
            "automation_registry_mutation": False,
        },
        "prospective_contract": {
            "v057_sha256": EXPECTED_V057_SHA,
            "v061_execution_plan_sha256": EXPECTED_V061_PLAN_SHA,
        },
        "inputs_sha256": state["input_sha256"],
        "method": {
            "observed_candidate_domain": (
                "exact same per-pair common_polygon membership as v056"
            ),
            "shifted_endpoint": "endpoint_b",
            "shift_model": "exact great-circle directional offset",
            "radii_arcsec": list(RADII_ARCSEC),
            "directions": [x[0] for x in DIRECTIONS],
            "candidate_denominator": (
                "fixed endpoint_b candidates selected inside common polygon "
                "before shift; no outside candidates are introduced"
            ),
            "gates_arcsec": list(GATES_ARCSEC),
            "neighbor_counter": "scipy.spatial.cKDTree on unit-sphere chord distance",
            "unshifted_exact_reproduction_required": True,
        },
        "verified_observed": {
            "raw_le_3arcsec": EXPECTED_RAW3,
            "raw_le_10arcsec": EXPECTED_RAW10,
            "pair_count": EXPECTED_PAIRS,
        },
        "global_control_distribution": {
            "le_3arcsec": g3,
            "le_10arcsec": g10,
            "observed_to_control3_mean_ratio": (
                None if not g3["mean"] else EXPECTED_RAW3 / g3["mean"]
            ),
            "observed_to_control10_mean_ratio": (
                None if not g10["mean"] else EXPECTED_RAW10 / g10["mean"]
            ),
        },
        "pairs_with_uninformative_detector_coverage": sum(
            r["detector_coverage_state"]
            != "COMPLETE_VALID_DETECTOR_COVERAGE"
            for r in pair_rows
        ),
        "interpretation_boundary": (
            "Shifted controls estimate population-level local coincidence "
            "structure only. An observed excess or null does not promote, reject "
            "or close any individual candidate. Astrometric registration and "
            "candidate-level static/morphology/recurrence adjudication remain "
            "separate frozen stages."
        ),
        "outputs": {
            "control_rows": str(OUT_CONTROLS.relative_to(ROOT)).replace("\\", "/"),
            "pair_summary": str(OUT_PAIRS.relative_to(ROOT)).replace("\\", "/"),
            "global_summary": str(OUT_GLOBAL.relative_to(ROOT)).replace("\\", "/"),
        },
    }
    write_json(OUT_JSON, report)

    state.update({
        "status": "COMPLETE",
        "finished_at_utc": datetime.now(timezone.utc).isoformat(),
        "control_rows": controls,
        "pair_rows": pair_rows,
    })
    write_json(STATE, state)

    print("\n" + "=" * 132)
    print("SHIFTED POPULATION CONTROLS COMPLETE")
    print("=" * 132)
    print("Control jobs:", len(controls))
    print(
        f"Global observed <=3\": {EXPECTED_RAW3}; "
        f"control mean={g3['mean']:.2f}, median={g3['median']:.2f}, "
        f"range={g3['min']:.0f}-{g3['max']:.0f}"
    )
    print(
        f"Global observed <=10\": {EXPECTED_RAW10}; "
        f"control mean={g10['mean']:.2f}, median={g10['median']:.2f}, "
        f"range={g10['min']:.0f}-{g10['max']:.0f}"
    )
    print(
        "Observed/control-mean ratios: "
        f"<=3\"={report['global_control_distribution']['observed_to_control3_mean_ratio']:.4f}; "
        f"<=10\"={report['global_control_distribution']['observed_to_control10_mean_ratio']:.4f}"
    )
    print("Individual candidate dispositions: NONE")
    print("SCIENCE POSITIVES: 0")
    print("\nOutputs:")
    print(" ", OUT_JSON)
    print(" ", OUT_CONTROLS)
    print(" ", OUT_PAIRS)
    print(" ", OUT_GLOBAL)
    print("\nSTAGE STATUS: PASS")


if __name__ == "__main__":
    main()
