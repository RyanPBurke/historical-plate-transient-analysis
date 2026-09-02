from __future__ import annotations

from pathlib import Path
from collections import defaultdict
import argparse
import csv
import gc
import hashlib
import importlib.util
import json
import math
import time

import numpy as np
import pandas as pd
from scipy.spatial import cKDTree

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "results"
RESEARCH = ROOT / "research"
TOOLS = ROOT / "tools"

V062_SCRIPT = TOOLS / "run_wide_census_population_controls_v062.py"
V068A_SCRIPT = TOOLS / "run_wide_census_gaia_registration_v068a.py"
V069_SCRIPT = TOOLS / "preflight_wide_census_registered_controls_v069.py"
V071B_SCRIPT = TOOLS / "run_wide_census_registered_control_gaia_supplemental_acquisition_v071b.py"

CONTROL_CONTRACT = (
    RESEARCH / "prospective_freezes"
    / "wide_census_registered_control_contract_v001.json"
)

V072_REPORT = (
    RESULTS / "wide_census_registered_control_gaia_closure_v072"
    / "wide_census_registered_control_gaia_closure_v072.json"
)

V062_DIR = RESULTS / "wide_census_population_controls_v062"
V062_CONTROLS = V062_DIR / "wide_census_population_controls_v062.csv"

PAIR_PLAN = RESULTS / "wide_census_detector_pair_plan_v054.json"

V065 = RESULTS / "wide_census_gaia_reference_coverage_audit_v065"
PAIR_SUMMARY = V065 / "wide_census_gaia_reference_coverage_pair_summary_v065.csv"

V069_DIR = RESULTS / "wide_census_registered_control_coverage_preflight_v069"
V069_PAIR = V069_DIR / "wide_census_registered_control_coverage_pair_summary_v069.csv"

V064 = RESULTS / "wide_census_gaia_acquisition_v064"
V066 = RESULTS / "wide_census_gaia_supplemental_acquisition_v066"
V071B = RESULTS / "wide_census_registered_control_gaia_supplemental_acquisition_v071b"

V064_ORD = V064 / "cache" / "ordinary"
V066_ORD = V066 / "cache" / "ordinary"
V071B_ORD = V071B / "cache" / "ordinary"

V066_HPM = V066 / "cache" / "hpm"
V071B_HPM = V071B / "cache" / "hpm"

V071B_REPORT = V071B / "wide_census_registered_control_gaia_supplemental_acquisition_v071b.json"

V070_HPM_PLAN = (
    RESULTS / "wide_census_registered_control_gaia_supplement_plan_v070"
    / "wide_census_registered_control_hpm_query_plan_v070.csv"
)

OUT = RESULTS / "wide_census_registered_control_registration_v073a"

JOB_DIR = OUT / "jobs"
PAIR_DIR = OUT / "pairs"
STATE = OUT / "state_v073a.json"
JOB_SUMMARY = OUT / "wide_census_registered_control_job_summary_v073a.csv"
PAIR_OUT = OUT / "wide_census_registered_control_pair_summary_v073a.csv"
GLOBAL_OUT = OUT / "wide_census_registered_control_global_summary_v073a.csv"
REPORT_OUT = OUT / "wide_census_registered_control_registration_v073a.json"

EXPECTED_SHA = {
    V062_SCRIPT:
        "ec764f7f35b53f682d59d1acf0e6fa6da1b24f4282b4c6c4f99a9d853c2e1001",
    V068A_SCRIPT:
        "9376ed5244b5defe074732dbb92e7870b618e25001cd2da4162b48dff549e0f2",
    V069_SCRIPT:
        "0471c95ae5fd44b7d0c951de18aa2af493a276257747fe0e0850bc9c6288dbe9",
    V071B_SCRIPT:
        "d24d5a491d53dc529b4c80887d0c2e5e2b423470db2e80cb0efea15787b4693a",
    CONTROL_CONTRACT:
        "be2febd2696f1798a0a78c2724420f3aaac939a825ebe5b296b126ba9ce47eeb",
    V072_REPORT:
        "7b90b5f5ffc4c8a363fd694d34a13dbde1616c04a71807cfd0e093baadec35c6",
}

EXPECTED_PAIRS = 33
EXPECTED_JOBS = 528
EXPECTED_CONTROL_LE10_ALL_JOBS = 3_048_415
EXPECTED_CONTROL_LE3_ALL_JOBS = 274_648
EXPECTED_DETECTOR_ROWS = 5_083_325

EXPECTED_V064_LEAVES = 6_651
EXPECTED_V066_LEAVES = 13_916
EXPECTED_V071B_LEAVES = 3_063

REFERENCE_DOMAIN_ARCMIN = 30.25
SCIENCE_EXCLUSION_ARCSEC = 30.0
PRIMARY_MIN_REFS = 5
SPARSE_MIN_REFS = 3
WINDOWS_ARCMIN = (5.0, 10.0, 20.0, 30.0)
ORDINARY_BASE_CELL_DEG = 0.25

GAIA_COLUMNS = [
    "source_id",
    "ra",
    "dec",
    "ref_epoch",
    "pmra",
    "pmdec",
]


def sha256(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for b in iter(lambda: f.read(1024 * 1024), b""):
            h.update(b)
    return h.hexdigest()


def atomic_json(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, sort_keys=True)
    tmp.replace(path)


def atomic_csv(path, rows, fields):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)
    tmp.replace(path)


def read_csv(path):
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def load_module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot import implementation: {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def read_complete_json(path, label):
    obj = json.loads(path.read_text(encoding="utf-8-sig"))
    if obj.get("status") != "COMPLETE":
        raise RuntimeError(f"{label} is not COMPLETE: {obj.get('status')!r}")
    return obj


def chord_to_arcsec(chord):
    x = np.clip(np.asarray(chord, dtype=np.float64) / 2.0, 0.0, 1.0)
    return np.rad2deg(2.0 * np.arcsin(x)) * 3600.0


def cell_ids(coords):
    ra = np.asarray(coords[:, 0], dtype=np.float64) % 360.0
    dec = np.asarray(coords[:, 1], dtype=np.float64)
    ira = np.floor(ra / ORDINARY_BASE_CELL_DEG).astype(np.int64)
    idec = np.floor((dec + 90.0) / ORDINARY_BASE_CELL_DEG).astype(np.int64)
    return set(zip(ira.tolist(), idec.tolist()))


def select_indices_control(
    reg,
    tree,
    vecs,
    target_mid,
    target_a,
    target_b_shifted,
    target_b_original,
    radius,
):
    idx = tree.query_ball_point(target_mid, r=radius)

    if not idx:
        return (
            np.array([], dtype=np.int64),
            np.array([], dtype=np.float64),
        )

    idx = np.asarray(idx, dtype=np.int64)
    rv = vecs[idx]

    da = np.linalg.norm(rv - target_a, axis=1)
    dbs = np.linalg.norm(rv - target_b_shifted, axis=1)
    dbo = np.linalg.norm(rv - target_b_original, axis=1)

    keep = (
        (da > reg.R30SEC)
        & (dbs > reg.R30SEC)
        & (dbo > reg.R30SEC)
    )

    idx = idx[keep]

    if len(idx) == 0:
        return idx, np.array([], dtype=np.float64)

    dist = np.linalg.norm(vecs[idx] - target_mid, axis=1)
    arcmin = reg.chord_to_arcmin(dist)

    return idx, arcmin


def load_pair_gaia(
    reg,
    pair_index,
    cells,
    idx64,
    idx66,
    idx71,
):
    # v073a operational memory repair.
    #
    # v073 accumulated every transport DataFrame and only then performed
    # pd.concat(...).drop_duplicates(source_id, keep="first"). Large control
    # domains contain heavy overlap between Gaia query cells, so that transient
    # concat can require several GiB even though the deduplicated catalogue is
    # much smaller.
    #
    # Here we apply exactly the same keep-first source_id semantics while each
    # transport file is read, preserving the original file traversal order and
    # row order. No Gaia values, source eligibility, registration geometry, or
    # thresholds are changed. Only already-seen duplicate transport rows are
    # discarded before the final concat.
    unique_frames = []
    seen_source_ids = set()
    missing_cells = []
    files_read = 0
    rows_transport = 0

    def consume(path):
        nonlocal files_read, rows_transport

        df = reg.read_gaia_file(path)
        files_read += 1

        if df.empty:
            return

        rows_transport += len(df)

        source_ids = df["source_id"].to_numpy(
            dtype=np.int64,
            copy=False,
        )

        keep = np.empty(len(source_ids), dtype=bool)

        # Deliberately sequential: this reproduces pandas'
        # drop_duplicates(subset=["source_id"], keep="first") over the exact
        # original frame/row traversal order.
        for i, sid in enumerate(source_ids):
            key = int(sid)
            if key in seen_source_ids:
                keep[i] = False
            else:
                seen_source_ids.add(key)
                keep[i] = True

        if np.any(keep):
            unique_frames.append(
                df.loc[keep].copy()
            )

        del df

    for cell in sorted(cells):
        paths = []
        paths.extend(idx64.get(cell, []))
        paths.extend(idx66.get(cell, []))
        paths.extend(idx71.get(cell, []))

        if not paths:
            missing_cells.append(cell)
            continue

        for path in paths:
            consume(path)

    if missing_cells:
        raise RuntimeError(
            f"Pair {pair_index}: missing resolved Gaia coverage for cells: "
            + ", ".join(str(x) for x in missing_cells[:20])
        )

    old_hpm = V066_HPM / f"hpm_pair_{pair_index:02d}.csv.gz"

    if not old_hpm.is_file():
        raise RuntimeError(
            f"Pair {pair_index}: missing v066 HPM cache: {old_hpm}"
        )

    hpm_paths = [old_hpm]

    new_hpm = V071B_HPM / f"hpm_pair_{pair_index:02d}.csv.gz"

    if new_hpm.is_file():
        hpm_paths.append(new_hpm)

    for path in hpm_paths:
        consume(path)

    if not unique_frames:
        raise RuntimeError(
            f"Pair {pair_index}: no Gaia rows loaded"
        )

    unique_before_motion = int(len(seen_source_ids))
    duplicate_rows_removed = int(
        rows_transport - unique_before_motion
    )

    print(
        f"Gaia transport streaming dedup: {rows_transport:,} rows -> "
        f"{unique_before_motion:,} unique source_id rows before motion filter",
        flush=True,
    )

    # The membership set has served its only purpose. Release it before the
    # final contiguous DataFrame allocation.
    del seen_source_ids
    gc.collect()

    if len(unique_frames) == 1:
        gaia = unique_frames[0].reset_index(drop=True)
    else:
        gaia = pd.concat(
            unique_frames,
            ignore_index=True,
            copy=False,
        )

    del unique_frames
    gc.collect()

    if len(gaia) != unique_before_motion:
        raise RuntimeError(
            f"Pair {pair_index}: streaming source_id dedup invariant failed "
            f"{len(gaia)} != {unique_before_motion}"
        )

    finite = (
        np.isfinite(gaia["ra"].to_numpy())
        & np.isfinite(gaia["dec"].to_numpy())
        & np.isfinite(gaia["ref_epoch"].to_numpy())
        & np.isfinite(gaia["pmra"].to_numpy())
        & np.isfinite(gaia["pmdec"].to_numpy())
    )

    missing_motion = int((~finite).sum())

    gaia = gaia.loc[finite].reset_index(drop=True)

    return gaia, {
        "transport_rows": int(rows_transport),
        "unique_rows_before_motion_filter":
            int(unique_before_motion),
        "duplicate_rows_removed":
            int(duplicate_rows_removed),
        "missing_motion_excluded":
            int(missing_motion),
        "usable_rows":
            int(len(gaia)),
        "files_read":
            int(files_read),
        "hpm_files_read":
            int(len(hpm_paths)),
        "dedup_strategy":
            "streaming_source_id_keep_first_exact_v073_order",
    }


def build_pair_metadata(pair_plan, pair_summary_rows):
    by_idx = {
        int(r["pair_index"]): r
        for r in pair_summary_rows
    }

    if set(by_idx) != set(range(1, EXPECTED_PAIRS + 1)):
        raise RuntimeError(
            "v065 pair-summary indices are not exactly 1..33"
        )

    if len(pair_plan) != EXPECTED_PAIRS:
        raise RuntimeError(
            f"Pair-plan count changed: {len(pair_plan)}"
        )

    out = {}

    for idx, p in enumerate(pair_plan, 1):
        row = by_idx[idx]

        out[idx] = {
            "canonical_pair": str(p["canonical_pair"]),
            "endpoint_a": str(p["endpoint_a"]),
            "endpoint_b": str(p["endpoint_b"]),
            "common_polygon_icrs_deg":
                p["common_polygon_icrs_deg"],
            "registration_epoch_utc":
                row["registration_epoch_utc"],
        }

    return out


def reconstruct_pair_control_domain(
    v62,
    reg,
    pair_index,
    meta,
    arrays,
    control_map,
    v069_expected,
):
    ea = meta["endpoint_a"]
    eb = meta["endpoint_b"]
    poly = meta["common_polygon_icrs_deg"]

    aa_all = arrays[ea]
    bb_all = arrays[eb]

    aa = aa_all[
        v62.polygon_mask(aa_all, poly)
    ]

    bb = bb_all[
        v62.polygon_mask(bb_all, poly)
    ]

    first = control_map[
        (
            pair_index,
            float(v62.RADII_ARCSEC[0]),
            v62.DIRECTIONS[0][0],
        )
    ]

    exp_a = int(
        first[
            "endpoint_a_candidates_in_common_polygon"
        ]
    )

    exp_b = int(
        first[
            "endpoint_b_candidates_in_common_polygon"
        ]
    )

    if len(aa) != exp_a or len(bb) != exp_b:
        raise RuntimeError(
            f"Pair {pair_index}: common-polygon candidates changed: "
            f"A={len(aa)} expected={exp_a}; "
            f"B={len(bb)} expected={exp_b}"
        )

    a_xyz = v62.radec_to_xyz(aa)
    bb_xyz = v62.radec_to_xyz(bb)

    tree_a = cKDTree(
        a_xyz,
        leafsize=32,
        compact_nodes=True,
        balanced_tree=True,
    )

    jobs = []
    midpoint_chunks = []

    pair_c3 = 0
    pair_c10 = 0

    R3 = v62.chord_radius(3.0)
    R10 = v62.chord_radius(10.0)

    for radius in v62.RADII_ARCSEC:
        for direction, pa in v62.DIRECTIONS:
            key = (
                pair_index,
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
                    f"Pair {pair_index} control "
                    f"{radius:.0f}/{direction}: "
                    f"v062 reproduction failed "
                    f"got ({c3},{c10}) "
                    f"expected ({exp3},{exp10})"
                )

            pair_c3 += c3
            pair_c10 += c10

            if c10:
                mids = reg.midpoint_vectors(
                    a_xyz[matrix.row],
                    b_xyz[matrix.col],
                )

                midpoint_chunks.append(
                    mids
                )

            jobs.append({
                "radius": float(radius),
                "direction": direction,
                "pa": float(pa),
                "matrix": matrix,
                "raw_le3": c3,
                "raw_le10": c10,
            })

    if len(jobs) != 16:
        raise RuntimeError(
            f"Pair {pair_index}: expected 16 control jobs"
        )

    if not midpoint_chunks:
        required_cells = set()
        refcand = 0
    else:
        control_midpoints = np.vstack(
            midpoint_chunks
        )

        target_tree = cKDTree(
            control_midpoints,
            leafsize=32,
            compact_nodes=True,
            balanced_tree=True,
        )

        ref_chord = reg.chord_radius_arcmin(
            REFERENCE_DOMAIN_ARCMIN
        )

        selected_coords = []
        refcand = 0

        for endpoint_arr in (aa_all, bb_all):
            endpoint_xyz = v62.radec_to_xyz(
                endpoint_arr
            )

            dist, _ = target_tree.query(
                endpoint_xyz,
                k=1,
                distance_upper_bound=ref_chord,
                workers=-1,
            )

            keep = np.isfinite(dist)

            refcand += int(
                np.count_nonzero(keep)
            )

            if np.any(keep):
                selected_coords.append(
                    endpoint_arr[keep]
                )

        if selected_coords:
            required_cells = cell_ids(
                np.vstack(selected_coords)
            )
        else:
            required_cells = set()

    exp_refcand = int(
        v069_expected[
            "reference_domain_detector_candidates"
        ]
    )

    exp_cells = int(
        v069_expected[
            "required_candidate_cells"
        ]
    )

    if refcand != exp_refcand:
        raise RuntimeError(
            f"Pair {pair_index}: control reference-candidate "
            f"domain mismatch {refcand} != {exp_refcand}"
        )

    if len(required_cells) != exp_cells:
        raise RuntimeError(
            f"Pair {pair_index}: required-cell mismatch "
            f"{len(required_cells)} != {exp_cells}"
        )

    return {
        "aa_all": aa_all,
        "bb_all": bb_all,
        "aa": aa,
        "bb": bb,
        "a_xyz": a_xyz,
        "bb_xyz": bb_xyz,
        "jobs": jobs,
        "required_cells": required_cells,
        "reference_domain_detector_candidates":
            refcand,
        "pair_raw_control_le3_all_jobs":
            pair_c3,
        "pair_raw_control_le10_all_jobs":
            pair_c10,
    }


def process_job(
    reg,
    v62,
    pair_index,
    meta,
    pair_ctx,
    job,
    match_a,
    match_b,
    common,
):
    radius = job["radius"]
    direction = job["direction"]
    pa = job["pa"]
    matrix = job["matrix"]

    aa = pair_ctx["aa"]
    bb = pair_ctx["bb"]
    a_xyz = pair_ctx["a_xyz"]
    bb_xyz = pair_ctx["bb_xyz"]

    shifted = v62.shift_radec(
        bb,
        radius,
        pa,
    )

    b_xyz = v62.radec_to_xyz(
        shifted
    )

    row_idx = np.asarray(
        matrix.row,
        dtype=np.int64,
    )

    col_idx = np.asarray(
        matrix.col,
        dtype=np.int64,
    )

    a_targets = aa[row_idx]
    b_targets = shifted[col_idx]
    b_original = bb[col_idx]

    avecs = a_xyz[row_idx]
    bvecs = b_xyz[col_idx]
    borig_vecs = bb_xyz[col_idx]

    mids = reg.midpoint_vectors(
        avecs,
        bvecs,
    )

    tree_common = (
        cKDTree(common["gaia_vec"])
        if len(common["source_id"])
        else None
    )

    tree_ma = (
        cKDTree(match_a["gaia_vec"])
        if len(match_a["source_id"])
        else None
    )

    tree_mb = (
        cKDTree(match_b["gaia_vec"])
        if len(match_b["source_id"])
        else None
    )

    primary = 0
    sparse = 0
    none = 0

    primary_corr_le3 = 0
    sparse_corr_le3 = 0

    primary_raw_le3_survive = 0
    primary_raw_le3_outward = 0
    primary_raw_gt3_inward = 0

    loo_robust = 0
    loo_crosses = 0

    window_counts = {
        5.0: 0,
        10.0: 0,
        20.0: 0,
        30.0: 0,
    }

    raw_le3_flags = (
        np.asarray(matrix.data)
        <= v62.chord_radius(3.0)
    )

    for j in range(len(row_idx)):
        avec = avecs[j]
        bvec = bvecs[j]
        borig = borig_vecs[j]
        mid = mids[j]

        mode = "NONE"
        selected_common = None

        shift_a_e = np.nan
        shift_a_n = np.nan
        shift_b_e = np.nan
        shift_b_n = np.nan

        if tree_common is not None:
            idx, dist_arcmin = select_indices_control(
                reg,
                tree_common,
                common["gaia_vec"],
                mid,
                avec,
                bvec,
                borig,
                reg.R30MIN,
            )

            for window in WINDOWS_ARCMIN:
                use = idx[
                    dist_arcmin <= window
                ]

                if len(use) >= PRIMARY_MIN_REFS:
                    selected_common = use
                    window_counts[window] += 1
                    break

            if selected_common is not None:
                use = selected_common

                shift_a_e = float(
                    np.median(
                        common["a_east"][use]
                    )
                )

                shift_a_n = float(
                    np.median(
                        common["a_north"][use]
                    )
                )

                shift_b_e = float(
                    np.median(
                        common["b_east"][use]
                    )
                )

                shift_b_n = float(
                    np.median(
                        common["b_north"][use]
                    )
                )

                mode = "PRIMARY"
                primary += 1

        if mode == "NONE":
            a_idx = np.array(
                [],
                dtype=np.int64,
            )

            b_idx = np.array(
                [],
                dtype=np.int64,
            )

            if tree_ma is not None:
                a_idx, _ = select_indices_control(
                    reg,
                    tree_ma,
                    match_a["gaia_vec"],
                    mid,
                    avec,
                    bvec,
                    borig,
                    reg.R30MIN,
                )

            if tree_mb is not None:
                b_idx, _ = select_indices_control(
                    reg,
                    tree_mb,
                    match_b["gaia_vec"],
                    mid,
                    avec,
                    bvec,
                    borig,
                    reg.R30MIN,
                )

            if (
                len(a_idx) >= SPARSE_MIN_REFS
                and len(b_idx) >= SPARSE_MIN_REFS
            ):
                shift_a_e = float(
                    np.median(
                        match_a["east"][a_idx]
                    )
                )

                shift_a_n = float(
                    np.median(
                        match_a["north"][a_idx]
                    )
                )

                shift_b_e = float(
                    np.median(
                        match_b["east"][b_idx]
                    )
                )

                shift_b_n = float(
                    np.median(
                        match_b["north"][b_idx]
                    )
                )

                mode = "SPARSE_DIAGNOSTIC"
                sparse += 1
            else:
                none += 1

        raw_e, raw_n = reg.raw_pair_vector_arcsec(
            a_targets[j, 0],
            a_targets[j, 1],
            b_targets[j, 0],
            b_targets[j, 1],
        )

        raw_is_le3 = bool(
            raw_le3_flags[j]
        )

        if mode == "NONE":
            continue

        corr_e = (
            raw_e
            - (shift_b_e - shift_a_e)
        )

        corr_n = (
            raw_n
            - (shift_b_n - shift_a_n)
        )

        corr_sep = float(
            math.hypot(
                corr_e,
                corr_n,
            )
        )

        corr_is_le3 = (
            corr_sep <= 3.0
        )

        if mode == "PRIMARY":
            if corr_is_le3:
                primary_corr_le3 += 1

            if raw_is_le3 and corr_is_le3:
                primary_raw_le3_survive += 1

            if raw_is_le3 and not corr_is_le3:
                primary_raw_le3_outward += 1

            if (not raw_is_le3) and corr_is_le3:
                primary_raw_gt3_inward += 1

            if (
                corr_is_le3
                and selected_common is not None
            ):
                use = selected_common

                _, loo_max = reg.exact_loo_separation(
                    raw_e,
                    raw_n,
                    common["a_east"][use],
                    common["a_north"][use],
                    common["b_east"][use],
                    common["b_north"][use],
                )

                if (
                    np.isfinite(loo_max)
                    and loo_max <= 3.0
                ):
                    loo_robust += 1
                else:
                    loo_crosses += 1

        elif mode == "SPARSE_DIAGNOSTIC":
            if corr_is_le3:
                sparse_corr_le3 += 1

    total = len(row_idx)

    if primary + sparse + none != total:
        raise RuntimeError(
            f"Pair {pair_index} {radius}/{direction}: "
            "registration-mode partition failed"
        )

    if (
        primary_corr_le3
        != loo_robust + loo_crosses
    ):
        raise RuntimeError(
            f"Pair {pair_index} {radius}/{direction}: "
            "LOO partition failed"
        )

    return {
        "pair_index": pair_index,
        "canonical_pair": meta["canonical_pair"],
        "endpoint_a": meta["endpoint_a"],
        "endpoint_b": meta["endpoint_b"],
        "shift_radius_arcsec": radius,
        "direction": direction,
        "position_angle_deg_east_of_north": pa,
        "raw_control_le10_associations": total,
        "raw_control_le3_associations":
            int(raw_le3_flags.sum()),
        "primary_registered": primary,
        "sparse_diagnostic_registered": sparse,
        "unregistered": none,
        "primary_corrected_le3": primary_corr_le3,
        "sparse_diagnostic_corrected_le3":
            sparse_corr_le3,
        "primary_raw_le3_to_corrected_le3":
            primary_raw_le3_survive,
        "primary_raw_le3_to_corrected_gt3":
            primary_raw_le3_outward,
        "primary_raw_gt3_to_corrected_le3":
            primary_raw_gt3_inward,
        "primary_loo_robust_corrected_le3":
            loo_robust,
        "primary_loo_crosses_gt3":
            loo_crosses,
        "primary_window_5arcmin":
            window_counts[5.0],
        "primary_window_10arcmin":
            window_counts[10.0],
        "primary_window_20arcmin":
            window_counts[20.0],
        "primary_window_30arcmin":
            window_counts[30.0],
    }


def describe(values):
    x = np.asarray(
        values,
        dtype=np.float64,
    )

    if len(x) == 0:
        return {
            "n": 0,
            "min": None,
            "max": None,
            "median": None,
            "mean": None,
            "stdev_population": None,
        }

    return {
        "n": int(len(x)),
        "min": float(np.min(x)),
        "max": float(np.max(x)),
        "median": float(np.median(x)),
        "mean": float(np.mean(x)),
        "stdev_population": float(np.std(x)),
    }


def aggregate_outputs(job_rows):
    pair_rows = []

    for pair_index in range(
        1,
        EXPECTED_PAIRS + 1,
    ):
        subset = [
            r for r in job_rows
            if int(r["pair_index"]) == pair_index
        ]

        if len(subset) != 16:
            raise RuntimeError(
                f"Pair {pair_index}: "
                f"expected 16 completed jobs, got {len(subset)}"
            )

        row = {
            "pair_index": pair_index,
            "canonical_pair":
                subset[0]["canonical_pair"],
            "raw_control_le10_associations_all_jobs":
                sum(
                    int(r["raw_control_le10_associations"])
                    for r in subset
                ),
            "raw_control_le3_associations_all_jobs":
                sum(
                    int(r["raw_control_le3_associations"])
                    for r in subset
                ),
            "primary_registered_all_jobs":
                sum(
                    int(r["primary_registered"])
                    for r in subset
                ),
            "sparse_diagnostic_registered_all_jobs":
                sum(
                    int(r["sparse_diagnostic_registered"])
                    for r in subset
                ),
            "unregistered_all_jobs":
                sum(
                    int(r["unregistered"])
                    for r in subset
                ),
            "primary_corrected_le3_all_jobs":
                sum(
                    int(r["primary_corrected_le3"])
                    for r in subset
                ),
            "sparse_diagnostic_corrected_le3_all_jobs":
                sum(
                    int(r["sparse_diagnostic_corrected_le3"])
                    for r in subset
                ),
            "primary_loo_robust_corrected_le3_all_jobs":
                sum(
                    int(r["primary_loo_robust_corrected_le3"])
                    for r in subset
                ),
            "primary_loo_crosses_gt3_all_jobs":
                sum(
                    int(r["primary_loo_crosses_gt3"])
                    for r in subset
                ),
        }

        pair_rows.append(row)

    global_rows = []

    for radius in (60.0, 120.0):
        for direction in (
            "N",
            "NE",
            "E",
            "SE",
            "S",
            "SW",
            "W",
            "NW",
        ):
            subset = [
                r for r in job_rows
                if float(r["shift_radius_arcsec"]) == radius
                and r["direction"] == direction
            ]

            if len(subset) != EXPECTED_PAIRS:
                raise RuntimeError(
                    f"Global control cell "
                    f"{radius}/{direction}: "
                    f"{len(subset)} pair rows"
                )

            global_rows.append({
                "shift_radius_arcsec": radius,
                "direction": direction,
                "raw_control_le10_associations_sum":
                    sum(
                        int(r["raw_control_le10_associations"])
                        for r in subset
                    ),
                "raw_control_le3_associations_sum":
                    sum(
                        int(r["raw_control_le3_associations"])
                        for r in subset
                    ),
                "primary_registered_sum":
                    sum(
                        int(r["primary_registered"])
                        for r in subset
                    ),
                "sparse_diagnostic_registered_sum":
                    sum(
                        int(r["sparse_diagnostic_registered"])
                        for r in subset
                    ),
                "unregistered_sum":
                    sum(
                        int(r["unregistered"])
                        for r in subset
                    ),
                "primary_corrected_le3_sum":
                    sum(
                        int(r["primary_corrected_le3"])
                        for r in subset
                    ),
                "sparse_diagnostic_corrected_le3_sum":
                    sum(
                        int(r["sparse_diagnostic_corrected_le3"])
                        for r in subset
                    ),
                "primary_loo_robust_corrected_le3_sum":
                    sum(
                        int(r["primary_loo_robust_corrected_le3"])
                        for r in subset
                    ),
                "primary_loo_crosses_gt3_sum":
                    sum(
                        int(r["primary_loo_crosses_gt3"])
                        for r in subset
                    ),
            })

    return pair_rows, global_rows


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--pair",
        type=int,
        default=None,
        help="Process only one pair index.",
    )

    parser.add_argument(
        "--resume",
        action="store_true",
        help="Resume from completed per-job JSON products.",
    )

    parser.add_argument(
        "--preflight-only",
        action="store_true",
        help=(
            "Reconstruct frozen control associations and "
            "load/propagate the pair Gaia reference field, "
            "but stop before registered-control separations."
        ),
    )

    args = parser.parse_args()

    if (
        args.preflight_only
        and args.pair is None
    ):
        raise RuntimeError(
            "--preflight-only requires --pair"
        )

    if (
        args.pair is not None
        and args.pair not in range(
            1,
            EXPECTED_PAIRS + 1,
        )
    ):
        raise RuntimeError(
            f"Invalid pair: {args.pair}"
        )

    print("=" * 124)
    print(
        "WIDE CENSUS REGISTERED-CONTROL "
        "OFFLINE GAIA REGISTRATION v073a"
    )
    print("=" * 124)
    print(
        "Network access: DISALLOWED"
    )
    print(
        "Detector rerun: NO"
    )
    print(
        "Candidate dispositions: NONE"
    )
    print(
        "Reference field: unshifted detector/Gaia"
    )
    print(
        "Control target: A + synthetically shifted B"
    )
    print(
        "Exclusions: A, shifted B, original unshifted B — 30 arcsec"
    )
    print(
        "Primary: same-Gaia common refs >=5; "
        "translation-only componentwise median"
    )
    print(
        "Windows: 5, 10, 20, 30 arcmin"
    )
    print(
        "Sparse fallback: >=3 refs/archive; diagnostic only"
    )
    print()

    for path, expected in EXPECTED_SHA.items():
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

    closure = read_complete_json(
        V072_REPORT,
        "v072 closure",
    )

    cov = closure.get(
        "coverage",
        {},
    )

    if (
        int(
            cov.get(
                "ordinary_gaps_remaining",
                -1,
            )
        ) != 0
        or int(
            cov.get(
                "hpm_gaps_remaining",
                -1,
            )
        ) != 0
    ):
        raise RuntimeError(
            "v072 does not prove zero remaining coverage gaps"
        )

    read_complete_json(
        V071B_REPORT,
        "v071b acquisition",
    )

    contract = json.loads(
        CONTROL_CONTRACT.read_text(
            encoding="utf-8-sig"
        )
    )

    eq = contract[
        "registration_equivalence"
    ]

    frozen_checks = {
        "detector_gaia_radius_arcsec":
            15.0,
        "science_exclusion_radius_arcsec":
            30.0,
        "primary_minimum_common_same_gaia_references":
            5,
        "sparse_minimum_references_per_archive":
            3,
    }

    for key, expected in frozen_checks.items():
        if float(eq[key]) != expected:
            raise RuntimeError(
                f"Control contract changed: {key}"
            )

    if tuple(
        float(x)
        for x in eq[
            "local_windows_arcmin"
        ]
    ) != WINDOWS_ARCMIN:
        raise RuntimeError(
            "Control registration windows changed"
        )

    if not all(
        bool(eq[x])
        for x in (
            "exclude_control_target_a",
            "exclude_shifted_control_target_b",
            "exclude_original_endpoint_b_source",
            "leave_one_out_robustness",
        )
    ):
        raise RuntimeError(
            "Control exclusion/LOO contract changed"
        )

    reg = load_module(
        V068A_SCRIPT,
        "frozen_v068a",
    )

    v62 = load_module(
        V062_SCRIPT,
        "frozen_v062",
    )

    controls = read_csv(
        V062_CONTROLS
    )

    if len(controls) != EXPECTED_JOBS:
        raise RuntimeError(
            f"v062 control job count changed: {len(controls)}"
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

    raw3_all = sum(
        int(r["control_le_3arcsec_matches"])
        for r in controls
    )

    raw10_all = sum(
        int(r["control_le_10arcsec_matches"])
        for r in controls
    )

    if raw3_all != EXPECTED_CONTROL_LE3_ALL_JOBS:
        raise RuntimeError(
            "v062 global <=3 control total changed"
        )

    if raw10_all != EXPECTED_CONTROL_LE10_ALL_JOBS:
        raise RuntimeError(
            "v062 global <=10 control total changed"
        )

    pair_plan = json.loads(
        PAIR_PLAN.read_text(
            encoding="utf-8-sig"
        )
    ).get(
        "pairs",
        [],
    )

    pair_metadata = build_pair_metadata(
        pair_plan,
        read_csv(PAIR_SUMMARY),
    )

    v069_rows = {
        int(r["pair_index"]): r
        for r in read_csv(V069_PAIR)
    }

    if set(v069_rows) != set(
        range(
            1,
            EXPECTED_PAIRS + 1,
        )
    ):
        raise RuntimeError(
            "v069 pair-summary indices changed"
        )

    print()
    print(
        "Loading exact frozen detector candidate arrays..."
    )

    arrays, endpoint_counts = (
        v62.load_candidate_arrays()
    )

    if sum(endpoint_counts.values()) != EXPECTED_DETECTOR_ROWS:
        raise RuntimeError(
            "Detector candidate count changed"
        )

    print(
        f"Detector candidates verified: "
        f"{sum(endpoint_counts.values()):,}"
    )

    print()
    print(
        "Indexing resolved Gaia ordinary leaves..."
    )

    idx64 = reg.build_leaf_index(
        V064_ORD,
        compressed=False,
    )

    idx66 = reg.build_leaf_index(
        V066_ORD,
        compressed=True,
    )

    idx71 = reg.build_leaf_index(
        V071B_ORD,
        compressed=True,
    )

    n64 = sum(
        len(v)
        for v in idx64.values()
    )

    n66 = sum(
        len(v)
        for v in idx66.values()
    )

    n71 = sum(
        len(v)
        for v in idx71.values()
    )

    if n64 != EXPECTED_V064_LEAVES:
        raise RuntimeError(
            f"v064 leaf count changed: {n64}"
        )

    if n66 != EXPECTED_V066_LEAVES:
        raise RuntimeError(
            f"v066 leaf count changed: {n66}"
        )

    if n71 != EXPECTED_V071B_LEAVES:
        raise RuntimeError(
            f"v071b leaf count changed: {n71}"
        )

    old_global_cells = (
        set(idx64)
        | set(idx66)
    )

    acquired_global_cells = (
        old_global_cells
        | set(idx71)
    )

    hpm_gap_pairs = {
        int(r["pair_index"])
        for r in read_csv(
            V070_HPM_PLAN
        )
    }

    if len(hpm_gap_pairs) != 16:
        raise RuntimeError(
            "v070 HPM supplement pair count changed"
        )

    actual_hpm71 = {
        int(
            p.name.split("_")[-1].split(".")[0]
        )
        for p in V071B_HPM.glob(
            "hpm_pair_*.csv.gz"
        )
    }

    if actual_hpm71 != hpm_gap_pairs:
        raise RuntimeError(
            "v071b HPM cache pair population "
            "does not match v070 plan"
        )

    print(
        f"Gaia leaf indices: "
        f"v064={n64:,}; "
        f"v066={n66:,}; "
        f"v071b={n71:,}"
    )

    wanted_pairs = (
        [args.pair]
        if args.pair is not None
        else list(
            range(
                1,
                EXPECTED_PAIRS + 1,
            )
        )
    )

    script_sha = sha256(
        Path(__file__)
    )

    if not args.preflight_only:
        if (
            OUT.exists()
            and any(OUT.rglob("*"))
            and not args.resume
        ):
            raise RuntimeError(
                "v073a output directory already contains "
                "products; use --resume or move it aside"
            )

        JOB_DIR.mkdir(
            parents=True,
            exist_ok=True,
        )

        PAIR_DIR.mkdir(
            parents=True,
            exist_ok=True,
        )

    run_start = time.time()

    for pair_index in wanted_pairs:
        t0 = time.time()

        meta = pair_metadata[
            pair_index
        ]

        print()
        print("=" * 124)
        print(
            f"PAIR {pair_index:02d}/33 — "
            f"{meta['canonical_pair']}"
        )
        print("=" * 124)

        pair_ctx = reconstruct_pair_control_domain(
            v62,
            reg,
            pair_index,
            meta,
            arrays,
            control_map,
            v069_rows[pair_index],
        )

        required_cells = pair_ctx[
            "required_cells"
        ]

        missing_before = (
            required_cells
            - old_global_cells
        )

        expected_missing_before = int(
            v069_rows[pair_index][
                "missing_ordinary_cells"
            ]
        )

        if (
            len(missing_before)
            != expected_missing_before
        ):
            raise RuntimeError(
                f"Pair {pair_index}: v069 missing-cell "
                f"reproduction failed "
                f"{len(missing_before)} "
                f"!= {expected_missing_before}"
            )

        remaining = (
            required_cells
            - acquired_global_cells
        )

        if remaining:
            raise RuntimeError(
                f"Pair {pair_index}: "
                f"{len(remaining)} Gaia cells still absent "
                "after v071b"
            )

        print(
            f"Control raw associations across 16 jobs: "
            f"<=10 {pair_ctx['pair_raw_control_le10_all_jobs']:,}; "
            f"<=3 {pair_ctx['pair_raw_control_le3_all_jobs']:,}"
        )

        print(
            f"Reference domain: "
            f"{pair_ctx['reference_domain_detector_candidates']:,} "
            f"detector candidates; "
            f"{len(required_cells):,} cells; "
            f"v069-missing now supplied={len(missing_before):,}"
        )

        gaia_df, gaia_stats = load_pair_gaia(
            reg,
            pair_index,
            required_cells,
            idx64,
            idx66,
            idx71,
        )

        gaia = reg.propagate_gaia(
            gaia_df,
            meta[
                "registration_epoch_utc"
            ],
        )

        del gaia_df

        match_a = reg.reciprocal_match(
            pair_ctx["aa_all"],
            gaia,
        )

        match_b = reg.reciprocal_match(
            pair_ctx["bb_all"],
            gaia,
        )

        common = reg.common_matches(
            match_a,
            match_b,
        )

        print(
            f"Gaia usable unique rows: "
            f"{gaia_stats['usable_rows']:,}; "
            f"reciprocal refs "
            f"A={len(match_a['source_id']):,}, "
            f"B={len(match_b['source_id']):,}, "
            f"common={len(common['source_id']):,}"
        )

        if args.preflight_only:
            print()
            print(
                "PREFLIGHT-ONLY STOP: "
                "control associations and Gaia reference "
                "field verified; no registered-control "
                "separations calculated."
            )

            print(
                "Registered-control counts calculated: 0"
            )

            continue

        pair_job_rows = []

        for n, job in enumerate(
            pair_ctx["jobs"],
            1,
        ):
            radius = job["radius"]
            direction = job["direction"]

            job_name = (
                f"pair_{pair_index:02d}_"
                f"r{int(radius):03d}_"
                f"{direction}_v073a.json"
            )

            job_path = (
                JOB_DIR
                / job_name
            )

            if (
                args.resume
                and job_path.is_file()
            ):
                old = json.loads(
                    job_path.read_text(
                        encoding="utf-8"
                    )
                )

                if (
                    old.get("script_sha256")
                    != script_sha
                    or old.get("control_contract_sha256")
                    != EXPECTED_SHA[
                        CONTROL_CONTRACT
                    ]
                ):
                    raise RuntimeError(
                        f"Existing job product was made "
                        f"by different frozen code: {job_path}"
                    )

                result = old[
                    "result"
                ]

                pair_job_rows.append(
                    result
                )

                print(
                    f"[{n:02d}/16] "
                    f"{radius:.0f}/{direction}: "
                    "already COMPLETE; skipping"
                )

                continue

            print(
                f"[{n:02d}/16] "
                f"{radius:.0f}/{direction}: "
                f"{job['raw_le10']:,} raw <=10\" "
                f"associations",
                flush=True,
            )

            jt0 = time.time()

            result = process_job(
                reg,
                v62,
                pair_index,
                meta,
                pair_ctx,
                job,
                match_a,
                match_b,
                common,
            )

            job_obj = {
                "status": "COMPLETE",
                "analysis_kind":
                    "wide_census_registered_control_job_v073a",
                "script_sha256":
                    script_sha,
                "control_contract_sha256":
                    EXPECTED_SHA[
                        CONTROL_CONTRACT
                    ],
                "v062_implementation_sha256":
                    EXPECTED_SHA[
                        V062_SCRIPT
                    ],
                "v068a_registration_implementation_sha256":
                    EXPECTED_SHA[
                        V068A_SCRIPT
                    ],
                "v072_closure_report_sha256":
                    EXPECTED_SHA[
                        V072_REPORT
                    ],
                "result": result,
                "elapsed_s":
                    time.time() - jt0,
                "candidate_dispositions":
                    "NONE",
            }

            atomic_json(
                job_path,
                job_obj,
            )

            pair_job_rows.append(
                result
            )

            print(
                f"         PRIMARY "
                f"{result['primary_registered']:,}; "
                f"PRIMARY corrected<=3 "
                f"{result['primary_corrected_le3']:,}; "
                f"LOO robust "
                f"{result['primary_loo_robust_corrected_le3']:,}; "
                f"sparse "
                f"{result['sparse_diagnostic_registered']:,}; "
                f"none "
                f"{result['unregistered']:,}; "
                f"{time.time()-jt0:.1f}s"
            )

        if len(pair_job_rows) != 16:
            raise RuntimeError(
                f"Pair {pair_index}: did not finish 16 jobs"
            )

        pair_summary = {
            "pair_index": pair_index,
            "canonical_pair":
                meta["canonical_pair"],
            "registration_epoch_utc":
                meta["registration_epoch_utc"],
            "required_control_gaia_cells":
                len(required_cells),
            "reference_domain_detector_candidates":
                pair_ctx[
                    "reference_domain_detector_candidates"
                ],
            "gaia": gaia_stats,
            "reciprocal_refs_a":
                int(
                    len(
                        match_a[
                            "source_id"
                        ]
                    )
                ),
            "reciprocal_refs_b":
                int(
                    len(
                        match_b[
                            "source_id"
                        ]
                    )
                ),
            "common_same_gaia_refs":
                int(
                    len(
                        common[
                            "source_id"
                        ]
                    )
                ),
            "raw_control_le10_all_jobs":
                sum(
                    int(
                        r[
                            "raw_control_le10_associations"
                        ]
                    )
                    for r in pair_job_rows
                ),
            "raw_control_le3_all_jobs":
                sum(
                    int(
                        r[
                            "raw_control_le3_associations"
                        ]
                    )
                    for r in pair_job_rows
                ),
            "primary_registered_all_jobs":
                sum(
                    int(
                        r[
                            "primary_registered"
                        ]
                    )
                    for r in pair_job_rows
                ),
            "primary_corrected_le3_all_jobs":
                sum(
                    int(
                        r[
                            "primary_corrected_le3"
                        ]
                    )
                    for r in pair_job_rows
                ),
            "primary_loo_robust_corrected_le3_all_jobs":
                sum(
                    int(
                        r[
                            "primary_loo_robust_corrected_le3"
                        ]
                    )
                    for r in pair_job_rows
                ),
            "sparse_diagnostic_registered_all_jobs":
                sum(
                    int(
                        r[
                            "sparse_diagnostic_registered"
                        ]
                    )
                    for r in pair_job_rows
                ),
            "unregistered_all_jobs":
                sum(
                    int(
                        r[
                            "unregistered"
                        ]
                    )
                    for r in pair_job_rows
                ),
            "elapsed_s":
                time.time() - t0,
            "candidate_dispositions":
                "NONE",
        }

        atomic_json(
            PAIR_DIR
            / f"pair_{pair_index:02d}_summary_v073a.json",
            pair_summary,
        )

        print()
        print(
            f"PAIR {pair_index:02d} COMPLETE "
            f"in {time.time()-t0:.1f}s"
        )
        print(
            f"  PRIMARY registered:             "
            f"{pair_summary['primary_registered_all_jobs']:,}"
        )
        print(
            f"  PRIMARY corrected <=3\":         "
            f"{pair_summary['primary_corrected_le3_all_jobs']:,}"
        )
        print(
            f"  PRIMARY LOO robust <=3\":        "
            f"{pair_summary['primary_loo_robust_corrected_le3_all_jobs']:,}"
        )
        print(
            f"  Sparse diagnostic registered:   "
            f"{pair_summary['sparse_diagnostic_registered_all_jobs']:,}"
        )
        print(
            f"  Unregistered:                   "
            f"{pair_summary['unregistered_all_jobs']:,}"
        )

        del gaia
        del match_a
        del match_b
        del common
        del pair_ctx

    if args.preflight_only:
        print()
        print("=" * 124)
        print(
            "v073a PREFLIGHT-ONLY COMPLETE"
        )
        print("=" * 124)
        print(
            "Registered-control separations calculated: 0"
        )
        print(
            "Candidate dispositions changed: NONE"
        )
        print(
            f"Invocation elapsed: "
            f"{time.time()-run_start:.1f}s"
        )
        return

    all_job_paths = sorted(
        JOB_DIR.glob(
            "pair_*_v073a.json"
        )
    )

    if args.pair is not None:
        print()
        print(
            "PARTIAL PAIR-SCOPED INVOCATION COMPLETE"
        )
        print(
            f"Total v073a job products currently present: "
            f"{len(all_job_paths)}/{EXPECTED_JOBS}"
        )
        print(
            "Run without --pair and with --resume "
            "to complete the full frozen population."
        )
        return

    if len(all_job_paths) != EXPECTED_JOBS:
        raise RuntimeError(
            f"Expected {EXPECTED_JOBS} job products, "
            f"found {len(all_job_paths)}"
        )

    job_rows = []

    for path in all_job_paths:
        obj = json.loads(
            path.read_text(
                encoding="utf-8"
            )
        )

        if obj.get("status") != "COMPLETE":
            raise RuntimeError(
                f"Incomplete job product: {path}"
            )

        if obj.get("script_sha256") != script_sha:
            raise RuntimeError(
                f"Job script SHA mismatch: {path}"
            )

        job_rows.append(
            obj["result"]
        )

    raw10 = sum(
        int(
            r[
                "raw_control_le10_associations"
            ]
        )
        for r in job_rows
    )

    raw3 = sum(
        int(
            r[
                "raw_control_le3_associations"
            ]
        )
        for r in job_rows
    )

    if raw10 != EXPECTED_CONTROL_LE10_ALL_JOBS:
        raise RuntimeError(
            f"Final <=10 raw control total mismatch: {raw10}"
        )

    if raw3 != EXPECTED_CONTROL_LE3_ALL_JOBS:
        raise RuntimeError(
            f"Final <=3 raw control total mismatch: {raw3}"
        )

    pair_rows, global_rows = (
        aggregate_outputs(
            job_rows
        )
    )

    atomic_csv(
        JOB_SUMMARY,
        job_rows,
        list(job_rows[0].keys()),
    )

    atomic_csv(
        PAIR_OUT,
        pair_rows,
        list(pair_rows[0].keys()),
    )

    atomic_csv(
        GLOBAL_OUT,
        global_rows,
        list(global_rows[0].keys()),
    )

    primary_cells = [
        int(
            r[
                "primary_corrected_le3_sum"
            ]
        )
        for r in global_rows
    ]

    loo_cells = [
        int(
            r[
                "primary_loo_robust_corrected_le3_sum"
            ]
        )
        for r in global_rows
    ]

    primary_registered_cells = [
        int(
            r[
                "primary_registered_sum"
            ]
        )
        for r in global_rows
    ]

    sparse_cells = [
        int(
            r[
                "sparse_diagnostic_corrected_le3_sum"
            ]
        )
        for r in global_rows
    ]

    report = {
        "status": "COMPLETE",
        "analysis_kind":
            "wide_census_registered_control_registration_v073a",
        "script_sha256":
            script_sha,
        "control_contract_sha256":
            EXPECTED_SHA[
                CONTROL_CONTRACT
            ],
        "upstream_implementation_sha256": {
            "v062":
                EXPECTED_SHA[
                    V062_SCRIPT
                ],
            "v068a":
                EXPECTED_SHA[
                    V068A_SCRIPT
                ],
            "v069":
                EXPECTED_SHA[
                    V069_SCRIPT
                ],
            "v071b":
                EXPECTED_SHA[
                    V071B_SCRIPT
                ],
            "v072_closure":
                EXPECTED_SHA[
                    V072_REPORT
                ],
        },
        "verified": {
            "pairs":
                EXPECTED_PAIRS,
            "control_jobs":
                EXPECTED_JOBS,
            "v062_raw_control_le10_all_jobs":
                raw10,
            "v062_raw_control_le3_all_jobs":
                raw3,
            "v062_exact_reproduction":
                True,
            "coverage_closure_v072":
                True,
        },
        "registration_method": {
            "reference_field":
                "unshifted historical detector/Gaia field",
            "target_a":
                "unshifted endpoint_a member",
            "target_b":
                "synthetically shifted endpoint_b member",
            "target_center":
                "spherical midpoint of A and shifted B",
            "exclusion_arcsec":
                SCIENCE_EXCLUSION_ARCSEC,
            "excluded_targets": [
                "A",
                "shifted_B",
                "original_unshifted_B",
            ],
            "windows_arcmin":
                list(
                    WINDOWS_ARCMIN
                ),
            "primary_min_common_same_gaia_refs":
                PRIMARY_MIN_REFS,
            "primary_transform":
                "translation-only componentwise median",
            "primary_clipping":
                False,
            "affine_terms":
                False,
            "higher_order_terms":
                False,
            "sparse_min_refs_per_archive":
                SPARSE_MIN_REFS,
            "sparse_diagnostic_only":
                True,
            "leave_one_out_robustness":
                True,
        },
        "global_control_distribution": {
            "primary_registered":
                describe(
                    primary_registered_cells
                ),
            "primary_corrected_le3":
                describe(
                    primary_cells
                ),
            "primary_loo_robust_corrected_le3":
                describe(
                    loo_cells
                ),
            "sparse_diagnostic_corrected_le3":
                describe(
                    sparse_cells
                ),
        },
        "guards": {
            "network_access":
                False,
            "detector_rerun":
                False,
            "candidate_disposition_changes":
                False,
            "threshold_retuning":
                False,
        },
        "interpretation_boundary":
            (
                "Registered shifted-control population only. "
                "No individual candidate is promoted, rejected, "
                "or closed by this stage. Observed-versus-control "
                "comparison is a separate downstream audit."
            ),
        "outputs": {
            "job_summary":
                str(
                    JOB_SUMMARY.relative_to(ROOT)
                ).replace("\\", "/"),
            "pair_summary":
                str(
                    PAIR_OUT.relative_to(ROOT)
                ).replace("\\", "/"),
            "global_summary":
                str(
                    GLOBAL_OUT.relative_to(ROOT)
                ).replace("\\", "/"),
        },
    }

    atomic_json(
        REPORT_OUT,
        report,
    )

    atomic_json(
        STATE,
        {
            "status": "COMPLETE",
            "analysis_kind":
                report[
                    "analysis_kind"
                ],
            "script_sha256":
                script_sha,
            "control_contract_sha256":
                report[
                    "control_contract_sha256"
                ],
            "completed_jobs":
                EXPECTED_JOBS,
            "completed_pairs":
                EXPECTED_PAIRS,
            "candidate_dispositions":
                "NONE",
        },
    )

    print()
    print("=" * 124)
    print(
        "v073a REGISTERED-CONTROL REGISTRATION COMPLETE"
    )
    print("=" * 124)
    print(
        f"Control jobs:                         "
        f"{EXPECTED_JOBS}"
    )
    print(
        f"Raw <=10 associations across jobs:    "
        f"{raw10:,}"
    )
    print(
        f"Raw <=3 associations across jobs:     "
        f"{raw3:,}"
    )
    print(
        "PRIMARY corrected <=3 global cells:   "
        f"mean={np.mean(primary_cells):,.2f}; "
        f"median={np.median(primary_cells):,.2f}; "
        f"range={min(primary_cells):,}-"
        f"{max(primary_cells):,}"
    )
    print(
        "PRIMARY LOO-robust <=3 global cells: "
        f"mean={np.mean(loo_cells):,.2f}; "
        f"median={np.median(loo_cells):,.2f}; "
        f"range={min(loo_cells):,}-"
        f"{max(loo_cells):,}"
    )
    print(
        "Network calls:                        0"
    )
    print(
        "Detector reruns:                      0"
    )
    print(
        "Candidate dispositions changed:       NONE"
    )
    print(
        "STAGE STATUS: COMPLETE"
    )
    print(
        f"Invocation elapsed: "
        f"{time.time()-run_start:.1f}s"
    )


if __name__ == "__main__":
    main()
