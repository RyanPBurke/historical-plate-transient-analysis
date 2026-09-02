from pathlib import Path
from collections import defaultdict
import csv
import hashlib
import importlib.util
import json
import math
import os
import sys

import numpy as np
from scipy.spatial import cKDTree


ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)

RESULTS = ROOT / "results"
RESEARCH = ROOT / "research"
TOOLS = ROOT / "tools"

V062_SCRIPT = TOOLS / "run_wide_census_population_controls_v062.py"
V065_SCRIPT = TOOLS / "audit_wide_census_gaia_reference_coverage_v065.py"
V068A_SCRIPT = TOOLS / "run_wide_census_gaia_registration_v068a.py"

CONTROL_CONTRACT = (
    RESEARCH / "prospective_freezes"
    / "wide_census_registered_control_contract_v001.json"
)

GAIA_ACQ_CONTRACT = (
    RESEARCH / "prospective_freezes"
    / "wide_census_gaia_reference_acquisition_contract_v002.json"
)

GAIA_REG_CONTRACT = (
    RESEARCH / "prospective_freezes"
    / "wide_census_gaia_registration_contract_v001.json"
)

V062_CONTROLS = (
    RESULTS / "wide_census_population_controls_v062"
    / "wide_census_population_controls_v062.csv"
)

V062_REPORT = (
    RESULTS / "wide_census_population_controls_v062"
    / "wide_census_population_controls_v062.json"
)

PAIR_PLAN = RESULTS / "wide_census_detector_pair_plan_v054.json"

V065_DIR = RESULTS / "wide_census_gaia_reference_coverage_audit_v065"

V065_REPORT = (
    V065_DIR / "wide_census_gaia_reference_coverage_audit_v065.json"
)

V065_PAIR_CELLS = (
    V065_DIR / "wide_census_gaia_reference_candidate_cells_v065.csv"
)

V065_HPM = (
    V065_DIR / "wide_census_gaia_corrected_hpm_pair_queries_v065.csv"
)

STATE064 = (
    RESULTS / "wide_census_gaia_acquisition_v064"
    / "state_v064.json"
)

STATE066 = (
    RESULTS / "wide_census_gaia_supplemental_acquisition_v066"
    / "state_v066.json"
)

OUT = RESULTS / "wide_census_registered_control_coverage_preflight_v069"

PAIR_OUT = OUT / "wide_census_registered_control_coverage_pair_summary_v069.csv"

MISSING_OUT = OUT / "wide_census_registered_control_missing_cells_v069.csv"

HPM_OUT = OUT / "wide_census_registered_control_hpm_requirements_v069.csv"

REPORT_OUT = OUT / "wide_census_registered_control_coverage_preflight_v069.json"


EXPECTED = {
    V062_SCRIPT:
        "ec764f7f35b53f682d59d1acf0e6fa6da1b24f4282b4c6c4f99a9d853c2e1001",

    V065_SCRIPT:
        "213416fcb26406a1c14986ebf4d7de7482a5853e3dc7ecce0f5d46c8bf3bc6b2",

    V068A_SCRIPT:
        "9376ed5244b5defe074732dbb92e7870b618e25001cd2da4162b48dff549e0f2",

    GAIA_ACQ_CONTRACT:
        "458a043dfbdda8dbb853cbae77c269ff17a586c0ddb2fdcf7ac0388ee57ab3fc",

    GAIA_REG_CONTRACT:
        "bd3456356392d56b73b3f6c8e16f51a028c1a43bce6a011871b7b3d341be907b",
}

EXPECTED_PAIRS = 33
EXPECTED_CONTROL_JOBS = 528

BASE_CELL_DEG = 0.25


def sha256(path):
    h = hashlib.sha256()

    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)

    return h.hexdigest()


def read_csv(path):
    with path.open(
        "r",
        encoding="utf-8-sig",
        newline=""
    ) as f:
        return list(csv.DictReader(f))


def atomic_json(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)

    tmp = path.with_suffix(path.suffix + ".tmp")

    with tmp.open("w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, sort_keys=True)

    tmp.replace(path)


def atomic_csv(path, rows, fields):
    path.parent.mkdir(parents=True, exist_ok=True)

    tmp = path.with_suffix(path.suffix + ".tmp")

    with tmp.open(
        "w",
        encoding="utf-8",
        newline=""
    ) as f:
        w = csv.DictWriter(
            f,
            fieldnames=fields,
            extrasaction="ignore",
        )

        w.writeheader()
        w.writerows(rows)

    tmp.replace(path)


def load_module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)

    if spec is None or spec.loader is None:
        raise RuntimeError(
            f"Cannot import implementation: {path}"
        )

    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    return mod


def unit_vector(ra_deg, dec_deg):
    ra = math.radians(float(ra_deg))
    dec = math.radians(float(dec_deg))
    c = math.cos(dec)

    return np.asarray(
        [
            c * math.cos(ra),
            c * math.sin(ra),
            math.sin(dec),
        ],
        dtype=np.float64,
    )


def vector_to_radec(v):
    v = np.asarray(v, dtype=np.float64)
    v = v / np.linalg.norm(v)

    ra = math.degrees(
        math.atan2(float(v[1]), float(v[0]))
    ) % 360.0

    dec = math.degrees(
        math.asin(
            max(-1.0, min(1.0, float(v[2])))
        )
    )

    return ra, dec


def angular_deg_vectors(vectors, center):
    dot = np.clip(
        np.asarray(vectors) @ np.asarray(center),
        -1.0,
        1.0,
    )

    return np.degrees(np.arccos(dot))


def midpoint_vectors(a, b):
    v = np.asarray(a) + np.asarray(b)

    n = np.linalg.norm(v, axis=1)

    bad = n == 0.0

    if np.any(bad):
        v[bad] = np.asarray(a)[bad]
        n[bad] = np.linalg.norm(v[bad], axis=1)

    return v / n[:, None]


def cell_set(coords):
    if len(coords) == 0:
        return set()

    ra = np.mod(coords[:, 0], 360.0)
    dec = coords[:, 1]

    ira = np.floor(ra / BASE_CELL_DEG).astype(
        np.int32
    )

    idec = np.floor(
        (dec + 90.0) / BASE_CELL_DEG
    ).astype(np.int32)

    return set(
        zip(
            ira.tolist(),
            idec.tolist(),
        )
    )


def require_complete_state(path, label):
    obj = json.loads(
        path.read_text(encoding="utf-8-sig")
    )

    if obj.get("status") != "COMPLETE":
        raise RuntimeError(
            f"{label} is not COMPLETE: {path}"
        )

    return obj


def main():
    print("=" * 118)
    print("WIDE CENSUS REGISTERED-CONTROL COVERAGE PREFLIGHT v069")
    print("=" * 118)
    print("Network access: NO")
    print("Gaia source rows read: NO")
    print("Astrometric registrations: NO")
    print("Detector rerun: NO")
    print("Candidate dispositions: NONE")
    print()

    if not CONTROL_CONTRACT.is_file():
        raise RuntimeError(
            f"Missing prospective control contract: "
            f"{CONTROL_CONTRACT}"
        )

    for path, expected in EXPECTED.items():
        if not path.is_file():
            raise RuntimeError(
                f"Missing frozen prerequisite: {path}"
            )

        actual = sha256(path)

        if actual.lower() != expected.lower():
            raise RuntimeError(
                "Frozen SHA mismatch:\n"
                f"  {path}\n"
                f"  expected {expected}\n"
                f"  actual   {actual}"
            )

        print(
            "HASH PASS:",
            path.relative_to(ROOT),
        )

    print(
        "CONTROL CONTRACT SHA256:",
        sha256(CONTROL_CONTRACT),
    )

    require_complete_state(STATE064, "v064")
    require_complete_state(STATE066, "v066")

    v062_report = json.loads(
        V062_REPORT.read_text(
            encoding="utf-8-sig"
        )
    )

    if v062_report.get("status") != "COMPLETE":
        raise RuntimeError("v062 report is not COMPLETE")

    v065_report = json.loads(
        V065_REPORT.read_text(
            encoding="utf-8-sig"
        )
    )

    if v065_report.get("status") != "COMPLETE":
        raise RuntimeError("v065 report is not COMPLETE")

    coverage = v065_report["coverage_correction"]

    reference_radius_arcmin = float(
        coverage[
            "reference_candidate_domain_radius_arcmin"
        ]
    )

    ordinary_margin_arcsec = float(
        coverage[
            "corrected_ordinary_margin_arcsec"
        ]
    )

    if abs(reference_radius_arcmin - 30.25) > 1e-9:
        raise RuntimeError(
            "Frozen reference-domain radius changed"
        )

    if abs(ordinary_margin_arcsec - 125.4) > 1e-9:
        raise RuntimeError(
            "Frozen ordinary transport margin changed"
        )

    print()
    print(
        f"Reference-domain radius: "
        f"{reference_radius_arcmin:.2f} arcmin"
    )
    print(
        f"Ordinary transport margin: "
        f"{ordinary_margin_arcsec:.1f} arcsec"
    )

    v62 = load_module(
        V062_SCRIPT,
        "frozen_v062",
    )

    v65 = load_module(
        V065_SCRIPT,
        "frozen_v065",
    )

    controls = read_csv(V062_CONTROLS)

    if len(controls) != EXPECTED_CONTROL_JOBS:
        raise RuntimeError(
            f"Expected {EXPECTED_CONTROL_JOBS} v062 "
            f"control rows; found {len(controls)}"
        )

    control_map = {}

    for row in controls:
        key = (
            int(row["pair_index"]),
            float(row["shift_radius_arcsec"]),
            row["direction"],
        )

        if key in control_map:
            raise RuntimeError(
                f"Duplicate v062 control key: {key}"
            )

        control_map[key] = row

    pair_plan = json.loads(
        PAIR_PLAN.read_text(
            encoding="utf-8-sig"
        )
    ).get("pairs", [])

    if len(pair_plan) != EXPECTED_PAIRS:
        raise RuntimeError(
            f"Expected 33 pair-plan rows; "
            f"found {len(pair_plan)}"
        )

    v065_pair_cells = defaultdict(set)
    acquired_global_cells = set()

    for row in read_csv(V065_PAIR_CELLS):
        idx = int(row["pair_index"])
        cell = (
            int(row["cell_ira"]),
            int(row["cell_idec"]),
        )

        v065_pair_cells[idx].add(cell)
        acquired_global_cells.add(cell)

    expected_global_cells = int(
        coverage["global_required_candidate_cells"]
    )

    if len(acquired_global_cells) != expected_global_cells:
        raise RuntimeError(
            "v065 global candidate-cell population "
            "does not match report"
        )

    hpm_rows = {
        int(r["pair_index"]): r
        for r in read_csv(V065_HPM)
    }

    if len(hpm_rows) != EXPECTED_PAIRS:
        raise RuntimeError(
            "Expected 33 corrected v065 HPM queries"
        )

    hpm_margins = {
        float(
            r["j2016_hpm_transport_margin_arcsec"]
        )
        for r in hpm_rows.values()
    }

    if hpm_margins != {915.0}:
        raise RuntimeError(
            f"Unexpected HPM margins: {hpm_margins}"
        )

    hpm_margin_deg = 915.0 / 3600.0

    ref_theta = math.radians(
        reference_radius_arcmin / 60.0
    )

    ref_chord = 2.0 * math.sin(
        ref_theta / 2.0
    )

    R3 = v62.chord_radius(3.0)
    R10 = v62.chord_radius(10.0)

    print()
    print(
        "Loading frozen 5,083,325 detector "
        "candidate coordinates..."
    )

    arrays, endpoint_counts = (
        v62.load_candidate_arrays()
    )

    print(
        f"Candidate arrays ready: "
        f"{sum(endpoint_counts.values()):,} rows"
    )

    pair_rows = []
    hpm_out_rows = []

    missing_consumers = defaultdict(set)

    total_jobs_reproduced = 0
    total_control3 = 0
    total_control10 = 0

    for idx, p in enumerate(pair_plan, 1):
        ea = str(p["endpoint_a"])
        eb = str(p["endpoint_b"])
        poly = p["common_polygon_icrs_deg"]

        if ea not in arrays or eb not in arrays:
            raise RuntimeError(
                f"Pair {idx}: endpoint absent from "
                "candidate arrays"
            )

        aa_all = arrays[ea]
        bb_all = arrays[eb]

        aa = aa_all[
            v62.polygon_mask(aa_all, poly)
        ]

        bb = bb_all[
            v62.polygon_mask(bb_all, poly)
        ]

        first_control = control_map[
            (
                idx,
                float(v62.RADII_ARCSEC[0]),
                v62.DIRECTIONS[0][0],
            )
        ]

        exp_a = int(
            first_control[
                "endpoint_a_candidates_in_common_polygon"
            ]
        )

        exp_b = int(
            first_control[
                "endpoint_b_candidates_in_common_polygon"
            ]
        )

        if len(aa) != exp_a or len(bb) != exp_b:
            raise RuntimeError(
                f"Pair {idx}: common-polygon "
                f"candidate mismatch "
                f"A={len(aa)} expected={exp_a}; "
                f"B={len(bb)} expected={exp_b}"
            )

        a_xyz = v62.radec_to_xyz(aa)

        tree_a = cKDTree(
            a_xyz,
            leafsize=32,
            compact_nodes=True,
            balanced_tree=True,
        )

        midpoint_chunks = []

        pair_control3 = 0
        pair_control10 = 0

        for radius in v62.RADII_ARCSEC:
            for direction, pa in v62.DIRECTIONS:
                key = (
                    idx,
                    float(radius),
                    direction,
                )

                expected = control_map[key]

                shifted = v62.shift_radec(
                    bb,
                    radius,
                    pa,
                )

                b_xyz = v62.radec_to_xyz(
                    shifted
                )

                tree_b = cKDTree(
                    b_xyz,
                    leafsize=32,
                    compact_nodes=True,
                    balanced_tree=True,
                )

                matrix = tree_a.sparse_distance_matrix(
                    tree_b,
                    max_distance=R10,
                    output_type="coo_matrix",
                )

                c10 = int(matrix.nnz)

                c3 = int(
                    np.count_nonzero(
                        matrix.data <= R3
                    )
                )

                exp3 = int(
                    expected[
                        "control_le_3arcsec_matches"
                    ]
                )

                exp10 = int(
                    expected[
                        "control_le_10arcsec_matches"
                    ]
                )

                if c3 != exp3 or c10 != exp10:
                    raise RuntimeError(
                        f"Pair {idx} control "
                        f"{radius:.0f}/{direction}: "
                        f"reproduction failed "
                        f"got ({c3},{c10}) "
                        f"expected ({exp3},{exp10})"
                    )

                total_jobs_reproduced += 1
                total_control3 += c3
                total_control10 += c10

                pair_control3 += c3
                pair_control10 += c10

                if c10:
                    mids = midpoint_vectors(
                        a_xyz[matrix.row],
                        b_xyz[matrix.col],
                    )

                    midpoint_chunks.append(mids)

        if not midpoint_chunks:
            pair_rows.append({
                "pair_index": idx,
                "canonical_pair": p["canonical_pair"],
                "control_jobs_reproduced": 16,
                "control_le3_associations_total": pair_control3,
                "control_le10_associations_total": pair_control10,
                "reference_domain_detector_candidates": 0,
                "required_candidate_cells": 0,
                "cells_already_in_v065_pair_domain": 0,
                "additional_cells_available_globally": 0,
                "missing_ordinary_cells": 0,
                "existing_hpm_query_covers_control_domain": True,
            })

            continue

        control_midpoints = np.vstack(
            midpoint_chunks
        )

        target_tree = cKDTree(
            control_midpoints,
            leafsize=32,
            compact_nodes=True,
            balanced_tree=True,
        )

        required_cells = set()
        eligible_vectors = []

        eligible_count = 0
        vector_sum = np.zeros(
            3,
            dtype=np.float64,
        )

        old_hpm = hpm_rows[idx]

        old_hpm_center = unit_vector(
            float(old_hpm["query_ra_deg"]),
            float(old_hpm["query_dec_deg"]),
        )

        old_hpm_radius_deg = float(
            old_hpm["query_radius_deg"]
        )

        max_sep_from_old_center = 0.0

        for ep in (ea, eb):
            coords = arrays[ep]

            for start in range(
                0,
                len(coords),
                250000,
            ):
                chunk = coords[
                    start:start + 250000
                ]

                xyz = v62.radec_to_xyz(
                    chunk
                )

                dist, _ = target_tree.query(
                    xyz,
                    k=1,
                    distance_upper_bound=ref_chord,
                    workers=-1,
                )

                mask = np.isfinite(dist)

                if not np.any(mask):
                    continue

                selected_coords = chunk[mask]
                selected_vecs = xyz[mask]

                eligible_count += len(
                    selected_coords
                )

                vector_sum += selected_vecs.sum(
                    axis=0
                )

                eligible_vectors.append(
                    selected_vecs
                )

                required_cells.update(
                    cell_set(selected_coords)
                )

                sep_old = angular_deg_vectors(
                    selected_vecs,
                    old_hpm_center,
                )

                if len(sep_old):
                    max_sep_from_old_center = max(
                        max_sep_from_old_center,
                        float(np.max(sep_old)),
                    )

        if eligible_count == 0:
            raise RuntimeError(
                f"Pair {idx}: control target "
                "population produced zero "
                "reference-domain candidates"
            )

        norm = np.linalg.norm(vector_sum)

        if not np.isfinite(norm) or norm == 0:
            raise RuntimeError(
                f"Pair {idx}: HPM center undefined"
            )

        new_center = vector_sum / norm

        far_new = 0.0

        for vecs in eligible_vectors:
            sep = angular_deg_vectors(
                vecs,
                new_center,
            )

            if len(sep):
                far_new = max(
                    far_new,
                    float(np.max(sep)),
                )

        new_hpm_radius_deg = (
            far_new + hpm_margin_deg
        )

        required_extent_from_old_center = (
            max_sep_from_old_center
            + hpm_margin_deg
        )

        old_hpm_covers = (
            required_extent_from_old_center
            <= old_hpm_radius_deg + 1e-10
        )

        new_hpm_ra, new_hpm_dec = (
            vector_to_radec(new_center)
        )

        existing_pair = v065_pair_cells[idx]

        missing_global = (
            required_cells
            - acquired_global_cells
        )

        additional_global = (
            required_cells
            - existing_pair
            - missing_global
        )

        for cell in missing_global:
            missing_consumers[cell].add(idx)

        pair_rows.append({
            "pair_index": idx,
            "canonical_pair": p["canonical_pair"],
            "control_jobs_reproduced": 16,
            "control_le3_associations_total":
                pair_control3,
            "control_le10_associations_total":
                pair_control10,
            "reference_domain_detector_candidates":
                eligible_count,
            "required_candidate_cells":
                len(required_cells),
            "cells_already_in_v065_pair_domain":
                len(required_cells & existing_pair),
            "additional_cells_available_globally":
                len(additional_global),
            "missing_ordinary_cells":
                len(missing_global),
            "existing_hpm_query_covers_control_domain":
                old_hpm_covers,
        })

        hpm_out_rows.append({
            "pair_index": idx,
            "canonical_pair": p["canonical_pair"],
            "existing_query_ra_deg":
                old_hpm["query_ra_deg"],
            "existing_query_dec_deg":
                old_hpm["query_dec_deg"],
            "existing_query_radius_deg":
                old_hpm_radius_deg,
            "required_control_query_ra_deg":
                new_hpm_ra,
            "required_control_query_dec_deg":
                new_hpm_dec,
            "required_control_query_radius_deg":
                new_hpm_radius_deg,
            "required_extent_from_existing_center_deg":
                required_extent_from_old_center,
            "hpm_margin_arcsec": 915.0,
            "existing_query_covers_control_domain":
                old_hpm_covers,
        })

        print(
            f"[{idx:02d}/33] "
            f"controls10={pair_control10:,} "
            f"refcand={eligible_count:,} "
            f"cells={len(required_cells):,} "
            f"missing={len(missing_global):,} "
            f"HPM={'PASS' if old_hpm_covers else 'GAP'}",
            flush=True,
        )

    if total_jobs_reproduced != EXPECTED_CONTROL_JOBS:
        raise RuntimeError(
            f"Only {total_jobs_reproduced}/"
            f"{EXPECTED_CONTROL_JOBS} "
            "control jobs reproduced"
        )

    expected_total3 = sum(
        int(r["control_le_3arcsec_matches"])
        for r in controls
    )

    expected_total10 = sum(
        int(r["control_le_10arcsec_matches"])
        for r in controls
    )

    if total_control3 != expected_total3:
        raise RuntimeError(
            "Aggregate v062 <=3 control "
            "reproduction mismatch"
        )

    if total_control10 != expected_total10:
        raise RuntimeError(
            "Aggregate v062 <=10 control "
            "reproduction mismatch"
        )

    missing_rows = []

    for (ira, idec), consumers in sorted(
        missing_consumers.items()
    ):
        missing_rows.append({
            "cell_ira": ira,
            "cell_idec": idec,
            "consumer_pair_count":
                len(consumers),
            "consumer_pair_indices":
                ";".join(
                    str(x)
                    for x in sorted(consumers)
                ),
        })

    hpm_gap_pairs = [
        int(r["pair_index"])
        for r in hpm_out_rows
        if not bool(
            r[
                "existing_query_covers_control_domain"
            ]
        )
    ]

    atomic_csv(
        PAIR_OUT,
        pair_rows,
        list(pair_rows[0].keys()),
    )

    atomic_csv(
        MISSING_OUT,
        missing_rows,
        [
            "cell_ira",
            "cell_idec",
            "consumer_pair_count",
            "consumer_pair_indices",
        ],
    )

    if hpm_out_rows:
        atomic_csv(
            HPM_OUT,
            hpm_out_rows,
            list(hpm_out_rows[0].keys()),
        )

    coverage_complete = (
        len(missing_rows) == 0
        and len(hpm_gap_pairs) == 0
    )

    report = {
        "status": "COMPLETE",
        "analysis_kind":
            "wide_census_registered_control_coverage_preflight_v069",

        "contract_sha256":
            sha256(CONTROL_CONTRACT),

        "verified": {
            "pairs": EXPECTED_PAIRS,
            "v062_control_jobs":
                total_jobs_reproduced,
            "v062_control_le3_associations_total":
                total_control3,
            "v062_control_le10_associations_total":
                total_control10,
            "v062_exact_reproduction": True,
        },

        "existing_gaia_domain": {
            "v065_global_acquired_candidate_cells":
                len(acquired_global_cells),
            "reference_candidate_domain_radius_arcmin":
                reference_radius_arcmin,
            "ordinary_transport_margin_arcsec":
                ordinary_margin_arcsec,
            "hpm_transport_margin_arcsec":
                915.0,
        },

        "control_domain": {
            "missing_ordinary_cells":
                len(missing_rows),
            "pairs_with_hpm_coverage_gap":
                hpm_gap_pairs,
            "existing_cache_fully_sufficient":
                coverage_complete,
        },

        "guards": {
            "network_access": False,
            "gaia_source_rows_read": 0,
            "science_pixels_read": False,
            "transient_detector_rerun": False,
            "astrometric_registration_run": False,
            "candidate_state_mutation": False,
        },

        "interpretation_boundary":
            "Coverage/provenance result only. "
            "No registered-control scientific "
            "count has been calculated.",

        "next_stage": (
            "Execute frozen registered controls "
            "using existing Gaia cache."
            if coverage_complete
            else
            "Prospectively acquire only the "
            "objectively missing ordinary/HPM "
            "control-reference domain before "
            "registered controls."
        ),
    }

    atomic_json(
        REPORT_OUT,
        report,
    )

    print()
    print("=" * 118)
    print("v069 COVERAGE PREFLIGHT COMPLETE")
    print("=" * 118)
    print(
        f"v062 control jobs reproduced: "
        f"{total_jobs_reproduced:,}/528"
    )
    print(
        f"Control <=3 associations across "
        f"all jobs: {total_control3:,}"
    )
    print(
        f"Control <=10 associations across "
        f"all jobs: {total_control10:,}"
    )
    print(
        f"Existing global ordinary cells: "
        f"{len(acquired_global_cells):,}"
    )
    print(
        f"Missing ordinary cells: "
        f"{len(missing_rows):,}"
    )
    print(
        f"Pairs with HPM coverage gap: "
        f"{len(hpm_gap_pairs):,}"
    )

    print()

    if coverage_complete:
        print(
            "COVERAGE STATUS: COMPLETE — "
            "NO SUPPLEMENTAL GAIA ACQUISITION REQUIRED"
        )
    else:
        print(
            "COVERAGE STATUS: INCOMPLETE — "
            "SUPPLEMENTAL CONTROL-DOMAIN "
            "ACQUISITION REQUIRED"
        )

    print()
    print("Network calls: 0")
    print("Gaia source rows read: 0")
    print("Registrations run: 0")
    print("Detector reruns: 0")
    print("Candidate dispositions changed: NONE")


if __name__ == "__main__":
    main()
