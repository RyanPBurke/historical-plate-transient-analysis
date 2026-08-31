from __future__ import annotations

from pathlib import Path
from datetime import timedelta
import base64
import csv
import gzip
import importlib.util
import json
import math

import numpy as np
import astropy.units as u
from astropy.coordinates import SkyCoord, EarthLocation
from astropy.io import fits
from astropy.time import Time
from astropy.wcs import WCS
from scipy.spatial import cKDTree

ROOT = Path.cwd()
BASE = ROOT / "results" / "order61_native_full_v028"

RECURRENCE = BASE / "order61_branch_c_candidate462_recurrence256_v028.json"
VALIDATION = BASE / "order61_branch_c_candidate462_validation_v028.json"
PARALLAX_REPORT = BASE / "order61_branch_c_parallax_preflight_v028.json"
PARALLAX_MATCHES = BASE / "order61_branch_c_parallax_nearest_matches_v028.csv"
STRICT = BASE / "order61_strict_match_triage.csv"
DASCH_CAND = BASE / "order61_dasch_native_candidates.csv"

PARALLAX_WORKER = ROOT / "tools" / "run_order61_branch_c_parallax_preflight_v028.py"
WHOLE_WORKER = ROOT / "tools" / "run_order61_whole_native_v028.py"

OUT_REPORT = BASE / "order61_branch_c_candidate462_footprint_directional_controls_v028.json"
OUT_FULL = BASE / "order61_branch_c_candidate462_directional_fullgrid_controls_v028.csv"
OUT_ANNULUS = BASE / "order61_branch_c_candidate462_directional_annulus_controls_v028.csv"

PARENT_RANK = 20
TARGET_TILE = "D_x11264-12288_y07168-08192"
TARGET_INDEX = 462

# Fixed before inspecting this control family.
# 97-fold circle: member 0 is the actual baseline direction; the remaining
# 96 members are deterministic rotation controls. 97 is prime and therefore
# does not duplicate the actual direction at 180/90-degree symmetries.
ROTATION_DENOMINATOR = 97
ROTATION_OFFSETS_DEG = [360.0 * i / ROTATION_DENOMINATOR for i in range(1, ROTATION_DENOMINATOR)]

NEAR_EARTH_BIN_NAMES = {
    "0.5-2k_LEO_like",
    "2-30k_MEO_like",
    "30-50k_GEO_focus",
    "50-100k",
    "100-500k_high_lunar",
}

OBSERVED_COARSE_BIN = "50-100k"
MIN_VALID_ANNULUS_CONTROLS_FOR_INTERPRETATION = 20

FULL_FIELDS = [
    "rotation_index",
    "rotation_offset_deg",
    "valid_grid_points_in_processed_footprint",
    "own_support_min_sep_arcsec",
    "own_support_best_bin",
    "own_support_best_time_utc",
    "own_support_best_range_km",
    "own_support_best_dasch_tile_id",
    "own_support_best_dasch_candidate_index",
    "common_support_grid_points",
    "common_support_min_sep_arcsec",
    "common_support_best_bin",
    "common_support_best_time_utc",
    "common_support_best_range_km",
    "common_support_best_dasch_tile_id",
    "common_support_best_dasch_candidate_index",
]

ANNULUS_FIELDS = [
    "rotation_index",
    "rotation_offset_deg",
    "position_angle_deg",
    "inside_processed_footprint",
    "control_ra_deg",
    "control_dec_deg",
    "nearest_dasch_sep_arcsec",
    "nearest_dasch_tile_id",
    "nearest_dasch_candidate_index",
    "nearest_dasch_snr",
    "nearest_dasch_polarity",
    "at_least_as_close_as_actual",
]


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not import {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def read_csv(path: Path):
    with path.open(newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def write_csv(path: Path, rows, fields):
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    tmp.replace(path)


def write_json(path: Path, obj):
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(obj, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )
    tmp.replace(path)


def plain_coord(ra_deg, dec_deg):
    return SkyCoord(float(ra_deg) * u.deg, float(dec_deg) * u.deg, frame="icrs")


def unit_vectors(coords: SkyCoord):
    ra = np.deg2rad(np.asarray(coords.icrs.ra.deg, dtype=float))
    dec = np.deg2rad(np.asarray(coords.icrs.dec.deg, dtype=float))
    return np.stack(
        [
            np.cos(dec) * np.cos(ra),
            np.cos(dec) * np.sin(ra),
            np.sin(dec),
        ],
        axis=-1,
    )


def nearest_candidates(tree, dcand, coords: SkyCoord):
    vec = unit_vectors(coords)
    chord, idx = tree.query(vec, k=1)
    chord = np.clip(np.asarray(chord, dtype=float), 0.0, 2.0)
    sep = np.degrees(2.0 * np.arcsin(chord / 2.0)) * 3600.0
    idx = np.asarray(idx, dtype=int)
    return sep, idx


def footprint_mask(dw, coords: SkyCoord, cores):
    x, y = dw.world_to_pixel(coords)
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)

    finite = np.isfinite(x) & np.isfinite(y)
    inside = np.zeros(x.shape, dtype=bool)

    for x0, x1, y0, y1 in cores:
        inside |= (
            finite
            & (x >= float(x0))
            & (x < float(x1))
            & (y >= float(y0))
            & (y < float(y1))
        )
    return inside, x, y


def best_on_mask(sep, idx, mask, meta, dcand):
    ii = np.flatnonzero(mask)
    if len(ii) == 0:
        return None

    local = int(np.argmin(sep[ii]))
    gi = int(ii[local])
    cr = dcand[int(idx[gi])]
    return {
        "sep_arcsec": float(sep[gi]),
        "grid_index": gi,
        "range_bin": meta[gi]["range_bin"],
        "event_time_utc": meta[gi]["event_time_utc"],
        "range_km": float(meta[gi]["range_km"]),
        "dasch_tile_id": cr["tile_id"],
        "dasch_candidate_index": int(cr["candidate_index"]),
    }


def main():
    print("=" * 116)
    print("ORDER 61 — BRANCH C #20 / CANDIDATE 462 FOOTPRINT-CONDITIONED DIRECTIONAL CONTROLS v028")
    print("=" * 116)
    print(
        "Independent geometry null: rotate the Palomar->Doña Ana parallax direction while preserving "
        "each original time/range displacement amplitude."
    )
    print(
        "Primary full-grid comparison uses only COMMON-SUPPORT grid points inside the actually processed "
        "DASCH tile cores for the actual direction and all 96 controls."
    )
    print(
        "Secondary candidate-specific annulus comparison rotates only the discovered coarse displacement "
        "amplitude and conditions each one-point control on the processed footprint."
    )
    print("No detector rerun. No science image pixels. No candidate deletion or promotion.")
    print()

    for p in (
        RECURRENCE,
        VALIDATION,
        PARALLAX_REPORT,
        PARALLAX_MATCHES,
        STRICT,
        DASCH_CAND,
        PARALLAX_WORKER,
        WHOLE_WORKER,
    ):
        if not p.is_file():
            raise RuntimeError(f"Missing required input: {p}")

    recurrence = json.loads(RECURRENCE.read_text(encoding="utf-8"))
    validation = json.loads(VALIDATION.read_text(encoding="utf-8"))
    par_report = json.loads(PARALLAX_REPORT.read_text(encoding="utf-8"))

    guards = {
        "recurrence_complete": recurrence.get("status") == "COMPLETE",
        "recurrence_zero_3arcsec": recurrence.get("summary", {}).get("plates_with_source_within_3arcsec") == 0,
        "recurrence_zero_5arcsec": recurrence.get("summary", {}).get("plates_with_source_within_5arcsec") == 0,
        "recurrence_256_complete": recurrence.get("summary", {}).get("completed_plates") == 256,
        "validation_complete": validation.get("status") == "COMPLETE",
        "validation_survives_static_morphology": (
            validation.get("disposition")
            == "BRANCH_C_20_NEW_COUNTERPART_SURVIVES_STATIC_AND_MATCHED_PEER_MORPHOLOGY"
        ),
        "parallax_preflight_complete": par_report.get("status") == "COMPLETE",
        "parallax_no_detector": par_report.get("detector_rerun") is False,
    }
    if not all(guards.values()):
        raise RuntimeError("REFUSING: completed-stage guard failure: " + repr(guards))

    pm = load_module(PARALLAX_WORKER, "order61_branch_c_parallax_preflight_v028")
    wm = load_module(WHOLE_WORKER, "order61_whole_native_v028")

    strict = {int(r["strict_rank"]): r for r in read_csv(STRICT)}
    if PARENT_RANK not in strict:
        raise RuntimeError("Missing strict #20 row")
    sr = strict[PARENT_RANK]
    parent = plain_coord(sr["poss_ra_deg"], sr["poss_dec_deg"])

    dcand = read_csv(DASCH_CAND)
    if len(dcand) != 4109:
        raise RuntimeError(f"REFUSING: expected 4109 frozen DASCH candidates, got {len(dcand)}")
    cand_vec = np.stack(
        [pm.unit_from_radec(float(r["ra_deg"]), float(r["dec_deg"])) for r in dcand]
    )
    tree = cKDTree(cand_vec)

    # ------------------------------------------------------------------
    # Recover the exact DR7 TPV geometry and validate against completed
    # native-tile metadata. No image bytes are requested/read here.
    # ------------------------------------------------------------------
    print("Completed-stage guards: PASS")
    print("[1/5] Recovering and validating DASCH TPV + processed footprint ...", flush=True)

    tile_meta_paths = sorted(wm.DASCH_DIR.glob("D_*.json"))
    tile_meta = []
    for p in tile_meta_paths:
        try:
            obj = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        if obj.get("complete") and obj.get("archive") == "DASCH":
            tile_meta.append(obj)

    if len(tile_meta) != 9:
        raise RuntimeError(f"REFUSING: expected 9 completed DASCH tile metadata files, got {len(tile_meta)}")

    geometry_sigs = {m["geometry_signature"] for m in tile_meta}
    if len(geometry_sigs) != 1:
        raise RuntimeError("REFUSING: completed DASCH tile geometry signatures disagree")
    frozen_geometry_sig = next(iter(geometry_sigs))

    cores = [tuple(map(float, m["core"])) for m in tile_meta]
    output_shapes = {tuple(map(int, m["output_shape"])) for m in tile_meta}
    if len(output_shapes) != 1:
        raise RuntimeError("REFUSING: completed DASCH tile output shapes disagree")

    pkg = wm.package()
    if wm.geometry_sig(pkg) != frozen_geometry_sig:
        raise RuntimeError("REFUSING: current official DR7 geometry metadata differs from completed science tiles")

    (tpv,) = wm.load_functions(
        wm.CONTROL_SOURCE,
        ("tpv",),
        {"fits": fits, "WCS": WCS, "gzip": gzip, "base64": base64},
    )
    dw, dh, rk, base_shape = tpv(pkg["metadata"])
    _ = (dh, rk, base_shape)

    print(f"  completed DASCH tile cores: {len(cores)}")
    print(f"  frozen/current geometry signature: {frozen_geometry_sig}")
    print("  current official TPV geometry matches completed native science tiles: PASS")
    print()

    # ------------------------------------------------------------------
    # Reconstruct the exact original near-Earth coarse time/range grid.
    # ------------------------------------------------------------------
    print("[2/5] Reconstructing original 0.5-500,000 km coarse Branch-C grid ...", flush=True)

    start = pm.parse_iso_utc(par_report["fixed_grid"]["event_time_interval"][0])
    end = pm.parse_iso_utc(par_report["fixed_grid"]["event_time_interval"][1])
    step = int(par_report["fixed_grid"]["event_time_step_seconds"])
    total = (end - start).total_seconds()
    nsteps = int(math.floor(total / step))
    dts = [start + timedelta(seconds=i * step) for i in range(nsteps + 1)]
    if dts[-1] < end:
        dts.append(end)

    times = Time(dts, scale="utc")
    pal = par_report["site_geometry"]["palomar"]
    da = par_report["site_geometry"]["dona_ana"]

    pal_loc = EarthLocation.from_geodetic(
        float(pal["lon_deg_east"]) * u.deg,
        float(pal["lat_deg"]) * u.deg,
        float(pal["height_m"]) * u.m,
    )
    da_loc = EarthLocation.from_geodetic(
        float(da["lon_deg_east"]) * u.deg,
        float(da["lat_deg"]) * u.deg,
        float(da["height_m"]) * u.m,
    )
    rP = pm.observer_xyz_km(pal_loc, times)
    rD = pm.observer_xyz_km(da_loc, times)

    uA = pm.unit_from_radec(float(sr["poss_ra_deg"]), float(sr["poss_dec_deg"]))

    grid_coords = []
    grid_meta = []
    for bin_name, lo, hi, nsamp in pm.RANGE_BINS_KM:
        if bin_name not in NEAR_EARTH_BIN_NAMES:
            continue
        ranges = pm.make_range_grid(lo, hi, nsamp)
        for ti, dt in enumerate(dts):
            obj = rP[ti][None, :] + ranges[:, None] * uA[None, :]
            vecD = obj - rD[ti][None, :]
            vecD /= np.linalg.norm(vecD, axis=1)[:, None]

            ra = np.degrees(np.arctan2(vecD[:, 1], vecD[:, 0])) % 360.0
            dec = np.degrees(
                np.arctan2(vecD[:, 2], np.hypot(vecD[:, 0], vecD[:, 1]))
            )
            grid_coords.append(SkyCoord(ra * u.deg, dec * u.deg, frame="icrs"))

            for rv in ranges:
                grid_meta.append(
                    {
                        "range_bin": bin_name,
                        "event_time_utc": dt.isoformat(),
                        "range_km": float(rv),
                    }
                )

    actual_coords = SkyCoord(
        np.concatenate([np.asarray(c.ra.deg) for c in grid_coords]) * u.deg,
        np.concatenate([np.asarray(c.dec.deg) for c in grid_coords]) * u.deg,
        frame="icrs",
    )
    if len(actual_coords) != len(grid_meta):
        raise RuntimeError("REFUSING: grid coordinate/meta length mismatch")

    # The displacement amplitude and actual direction at each original
    # time/range point are defined relative to the fixed POSS #20 sightline.
    radii = parent.separation(actual_coords)
    pas = parent.position_angle(actual_coords)

    actual_mask, _, _ = footprint_mask(dw, actual_coords, cores)

    print(f"  original near-Earth grid points: {len(grid_meta)}")
    print(f"  actual-direction points inside processed DASCH cores: {int(actual_mask.sum())}")
    print()

    # ------------------------------------------------------------------
    # Build all 97 masks first. The primary p-style comparison is then
    # evaluated ONLY on their intersection, guaranteeing exactly the same
    # time/range trial set for actual and every rotated control.
    # ------------------------------------------------------------------
    print("[3/5] Building 96 rotated-direction footprint masks ...", flush=True)

    offsets = [0.0] + ROTATION_OFFSETS_DEG
    masks = []
    for oi, offset in enumerate(offsets):
        coords = parent.directional_offset_by(
            pas + float(offset) * u.deg,
            radii,
        ).icrs
        mask, _, _ = footprint_mask(dw, coords, cores)
        masks.append(mask)
        if oi == 0:
            print(f"  actual direction: valid={int(mask.sum())}")
        elif oi % 16 == 0 or oi == len(offsets) - 1:
            print(f"  rotation {oi:02d}/96: offset={offset:.3f} deg valid={int(mask.sum())}", flush=True)

    common_mask = np.logical_and.reduce(masks)
    common_n = int(common_mask.sum())
    print(f"  common-support grid points valid for all 97 directions: {common_n}")
    print()

    # ------------------------------------------------------------------
    # Evaluate actual + 96 controls.
    # ------------------------------------------------------------------
    print("[4/5] Evaluating nearest frozen DASCH detection under each direction ...", flush=True)

    full_rows = []
    actual_common_best = None
    actual_own_best = None

    for oi, offset in enumerate(offsets):
        coords = parent.directional_offset_by(
            pas + float(offset) * u.deg,
            radii,
        ).icrs

        sep, idx = nearest_candidates(tree, dcand, coords)
        own_best = best_on_mask(sep, idx, masks[oi], grid_meta, dcand)
        common_best = best_on_mask(sep, idx, common_mask, grid_meta, dcand)

        if oi == 0:
            actual_own_best = own_best
            actual_common_best = common_best

        full_rows.append(
            {
                "rotation_index": oi,
                "rotation_offset_deg": float(offset),
                "valid_grid_points_in_processed_footprint": int(masks[oi].sum()),
                "own_support_min_sep_arcsec": None if own_best is None else own_best["sep_arcsec"],
                "own_support_best_bin": None if own_best is None else own_best["range_bin"],
                "own_support_best_time_utc": None if own_best is None else own_best["event_time_utc"],
                "own_support_best_range_km": None if own_best is None else own_best["range_km"],
                "own_support_best_dasch_tile_id": None if own_best is None else own_best["dasch_tile_id"],
                "own_support_best_dasch_candidate_index": None if own_best is None else own_best["dasch_candidate_index"],
                "common_support_grid_points": common_n,
                "common_support_min_sep_arcsec": None if common_best is None else common_best["sep_arcsec"],
                "common_support_best_bin": None if common_best is None else common_best["range_bin"],
                "common_support_best_time_utc": None if common_best is None else common_best["event_time_utc"],
                "common_support_best_range_km": None if common_best is None else common_best["range_km"],
                "common_support_best_dasch_tile_id": None if common_best is None else common_best["dasch_tile_id"],
                "common_support_best_dasch_candidate_index": None if common_best is None else common_best["dasch_candidate_index"],
            }
        )

    write_csv(OUT_FULL, full_rows, FULL_FIELDS)

    if actual_own_best is None:
        raise RuntimeError("REFUSING: actual geometry has zero valid processed-footprint grid points")

    if common_n > 0 and actual_common_best is not None:
        common_control_vals = [
            float(r["common_support_min_sep_arcsec"])
            for r in full_rows[1:]
            if r["common_support_min_sep_arcsec"] is not None
        ]
        n_common_le = sum(v <= actual_common_best["sep_arcsec"] for v in common_control_vals)
        common_empirical_p = (1 + n_common_le) / (1 + len(common_control_vals))
    else:
        common_control_vals = []
        n_common_le = None
        common_empirical_p = None

    print(
        f"  actual own-support minimum: {actual_own_best['sep_arcsec']:.4f}\" "
        f"({actual_own_best['range_bin']}, {actual_own_best['range_km']:.0f} km, "
        f"{actual_own_best['event_time_utc'][11:19]})"
    )
    if common_empirical_p is None:
        print("  primary common-support comparison: INSUFFICIENT (zero common-support grid points)")
    else:
        print(
            f"  primary common-support actual min={actual_common_best['sep_arcsec']:.4f}\" | "
            f"controls <= actual={n_common_le}/{len(common_control_vals)} | "
            f"finite-sample empirical p={common_empirical_p:.4f}"
        )
    print()

    # ------------------------------------------------------------------
    # Candidate-specific annulus control at the DISCOVERED coarse solution.
    # One sky point per control => identical trial count. Controls outside
    # the actually processed DASCH footprint are excluded explicitly.
    # ------------------------------------------------------------------
    print("[5/5] Candidate-specific footprint-conditioned annulus direction control ...", flush=True)

    pmatches = read_csv(PARALLAX_MATCHES)
    rows = [
        r for r in pmatches
        if int(r["strict_rank"]) == PARENT_RANK
        and r["range_bin"] == OBSERVED_COARSE_BIN
        and r["nearest_dasch_tile_id"] == TARGET_TILE
        and int(r["nearest_dasch_candidate_index"]) == TARGET_INDEX
    ]
    if len(rows) != 1:
        raise RuntimeError(f"REFUSING: expected exactly one coarse candidate-462 row, got {len(rows)}")
    coarse = rows[0]

    coarse_pred = plain_coord(
        coarse["predicted_dasch_ra_deg"],
        coarse["predicted_dasch_dec_deg"],
    )
    coarse_radius = parent.separation(coarse_pred)
    coarse_pa = parent.position_angle(coarse_pred)

    # Reproduce observed nearest candidate and separation directly.
    obs_inside, _, _ = footprint_mask(dw, SkyCoord([coarse_pred]), cores)
    if not bool(obs_inside[0]):
        raise RuntimeError("REFUSING: discovered coarse predicted point is outside processed footprint")

    obs_sep_arr, obs_idx_arr = nearest_candidates(tree, dcand, SkyCoord([coarse_pred]))
    obs_sep = float(obs_sep_arr[0])
    obs_cr = dcand[int(obs_idx_arr[0])]
    if not (
        obs_cr["tile_id"] == TARGET_TILE
        and int(obs_cr["candidate_index"]) == TARGET_INDEX
    ):
        raise RuntimeError("REFUSING: discovered coarse point no longer has candidate 462 as nearest frozen detection")

    reported_obs_sep = float(coarse["nearest_dasch_sep_arcsec"])
    if abs(obs_sep - reported_obs_sep) > 1e-5:
        raise RuntimeError(
            f"REFUSING: reproduced coarse separation {obs_sep} != reported {reported_obs_sep}"
        )

    annulus_rows = []
    valid_control_seps = []

    # Include actual as index 0 for audit; 1..96 are controls.
    for oi, offset in enumerate(offsets):
        c = parent.directional_offset_by(
            coarse_pa + float(offset) * u.deg,
            coarse_radius,
        ).icrs

        inside, _, _ = footprint_mask(dw, SkyCoord([c]), cores)
        row = {
            "rotation_index": oi,
            "rotation_offset_deg": float(offset),
            "position_angle_deg": float(circ := (coarse_pa.to_value(u.deg) + float(offset)) % 360.0),
            "inside_processed_footprint": bool(inside[0]),
            "control_ra_deg": float(c.ra.deg),
            "control_dec_deg": float(c.dec.deg),
            "nearest_dasch_sep_arcsec": None,
            "nearest_dasch_tile_id": None,
            "nearest_dasch_candidate_index": None,
            "nearest_dasch_snr": None,
            "nearest_dasch_polarity": None,
            "at_least_as_close_as_actual": None,
        }

        if bool(inside[0]):
            s, ix = nearest_candidates(tree, dcand, SkyCoord([c]))
            cr = dcand[int(ix[0])]
            row.update(
                {
                    "nearest_dasch_sep_arcsec": float(s[0]),
                    "nearest_dasch_tile_id": cr["tile_id"],
                    "nearest_dasch_candidate_index": int(cr["candidate_index"]),
                    "nearest_dasch_snr": float(cr["snr"]),
                    "nearest_dasch_polarity": int(cr["polarity"]),
                    "at_least_as_close_as_actual": bool(float(s[0]) <= obs_sep),
                }
            )
            if oi > 0:
                valid_control_seps.append(float(s[0]))

        annulus_rows.append(row)

    write_csv(OUT_ANNULUS, annulus_rows, ANNULUS_FIELDS)

    valid_annulus_n = len(valid_control_seps)
    annulus_le = sum(v <= obs_sep for v in valid_control_seps)
    annulus_p = (
        (1 + annulus_le) / (1 + valid_annulus_n)
        if valid_annulus_n >= MIN_VALID_ANNULUS_CONTROLS_FOR_INTERPRETATION
        else None
    )

    print(
        f"  discovered coarse amplitude: {coarse_radius.deg:.6f} deg | "
        f"actual PA={coarse_pa.deg:.3f} deg | observed nearest={obs_sep:.6f}\""
    )
    print(
        f"  valid rotated one-point controls inside processed footprint: "
        f"{valid_annulus_n}/96"
    )
    if annulus_p is None:
        print(
            f"  annulus comparison: INSUFFICIENT (<{MIN_VALID_ANNULUS_CONTROLS_FOR_INTERPRETATION} valid controls)"
        )
    else:
        print(
            f"  controls <= observed: {annulus_le}/{valid_annulus_n} | "
            f"finite-sample empirical directional p={annulus_p:.4f}"
        )

    # Explicitly do not manufacture a promotion threshold after seeing outcomes.
    if annulus_p is None:
        directional_disposition = "INCONCLUSIVE_FOOTPRINT_CONDITIONED_DIRECTIONAL_CONTROL"
    elif annulus_le == 0:
        directional_disposition = "NO_ROTATED_VALID_CONTROL_AS_CLOSE_AS_ACTUAL_DIRECTION"
    else:
        directional_disposition = "ROTATED_VALID_CONTROLS_CAN_MATCH_OR_BEAT_ACTUAL_DIRECTION"

    report = {
        "status": "COMPLETE",
        "analysis_kind": "order61_branch_c_candidate462_footprint_conditioned_directional_controls_v028",
        "guards": guards,
        "control_policy": {
            "rotation_denominator": ROTATION_DENOMINATOR,
            "control_offsets_deg": ROTATION_OFFSETS_DEG,
            "near_earth_bins": sorted(NEAR_EARTH_BIN_NAMES),
            "full_grid_primary": (
                "rotate actual Palomar->Dona Ana parallax displacement direction at every original "
                "time/range grid point while preserving angular amplitude; compare minima only on "
                "intersection of processed-footprint-valid points shared by actual+all96 controls"
            ),
            "annulus_secondary": (
                "at the discovered coarse candidate-462 time/range solution, preserve its exact "
                "parent-to-predicted angular amplitude and rotate direction through the same 96 offsets; "
                "one point per control; exclude points outside processed DASCH tile-core union"
            ),
            "candidate_polarity_not_used": True,
            "candidate_snr_not_used": True,
            "no_detector_rerun": True,
            "no_new_science_pixels": True,
            "no_posthoc_promotion_threshold": True,
        },
        "processed_footprint": {
            "completed_tile_cores": len(cores),
            "cores_xy": cores,
            "geometry_signature": frozen_geometry_sig,
            "wcs_current_metadata_matches_completed_tiles": True,
        },
        "full_grid": {
            "original_grid_points": len(grid_meta),
            "actual_direction_valid_grid_points": int(actual_mask.sum()),
            "common_support_grid_points": common_n,
            "actual_own_support_best": actual_own_best,
            "actual_common_support_best": actual_common_best,
            "common_support_controls_at_least_as_close": n_common_le,
            "common_support_control_count": len(common_control_vals),
            "common_support_empirical_p": common_empirical_p,
            "interpretation": (
                "Primary fair full-search directional null because every included grid point is present "
                "for actual and all 96 rotated directions. If common support is empty/small, do not infer "
                "significance from own-support minima."
            ),
        },
        "candidate_specific_annulus": {
            "coarse_range_bin": coarse["range_bin"],
            "coarse_event_time_utc": coarse["event_time_utc"],
            "coarse_palomar_range_km": float(coarse["palomar_range_km"]),
            "angular_amplitude_deg": float(coarse_radius.deg),
            "actual_position_angle_deg": float(coarse_pa.deg),
            "observed_nearest_sep_arcsec": obs_sep,
            "observed_nearest_tile_id": obs_cr["tile_id"],
            "observed_nearest_candidate_index": int(obs_cr["candidate_index"]),
            "valid_rotated_controls": valid_annulus_n,
            "invalid_outside_footprint_controls": 96 - valid_annulus_n,
            "controls_at_least_as_close_as_observed": annulus_le,
            "finite_sample_empirical_directional_p": annulus_p,
            "minimum_valid_controls_required": MIN_VALID_ANNULUS_CONTROLS_FOR_INTERPRETATION,
            "disposition": directional_disposition,
            "interpretation": (
                "Candidate-conditioned local directional-density diagnostic; independent of the earlier "
                "shifted-parent-sightline control family, but not a formal global astrophysical p-value."
            ),
        },
        "recurrence_context": recurrence.get("summary"),
        "detector_rerun": False,
        "science_image_pixels_read": False,
        "candidate_deleted": False,
        "candidate_promoted": False,
        "next_stage": (
            "If candidate 462 remains unusual under the footprint-conditioned directional control, "
            "freeze a physical/orbital plausibility stage: geocentric state vector family, angular motion "
            "during both long exposures, illumination/reflection constraints, and known 1953 artificial-object "
            "exclusion. If rotated valid controls commonly match/beat the actual direction, retire Branch-C "
            "candidate 462 as a chance geometric association while preserving the separate Branch-A #20 survivor."
        ),
        "outputs": {
            "full_grid_controls_csv": str(OUT_FULL),
            "annulus_controls_csv": str(OUT_ANNULUS),
        },
    }
    write_json(OUT_REPORT, report)

    print()
    print("=" * 116)
    print("FOOTPRINT-CONDITIONED DIRECTIONAL CONTROLS COMPLETE")
    print("=" * 116)
    print("Directional disposition:", directional_disposition)
    print("Output:", OUT_REPORT)
    print("Full-grid controls:", OUT_FULL)
    print("Annulus controls:", OUT_ANNULUS)
    print()
    print("No detector was rerun.")
    print("No science image pixel was read.")
    print("No candidate was deleted or promoted.")


if __name__ == "__main__":
    main()
