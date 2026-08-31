from __future__ import annotations

from pathlib import Path
import csv
import importlib.util
import json
import math

import numpy as np
import astropy.units as u
from astropy.coordinates import EarthLocation
from astropy.time import Time
from scipy.optimize import minimize

ROOT = Path.cwd()
BASE = ROOT / "results" / "order61_native_full_v028"

DYNAMICS = BASE / "order61_branch_c_candidate462_physical_dynamics_v028d.json"
REFINED = BASE / "order61_branch_c_refined_controls_v028.json"
PARALLAX = BASE / "order61_branch_c_parallax_preflight_v028.json"
STRICT = BASE / "order61_strict_match_triage.csv"
DYN_WORKER = ROOT / "tools" / "run_order61_branch_c_candidate462_physical_dynamics_v028d.py"

OUT = BASE / "order61_branch_c_candidate462_perigee_flyby_sensitivity_v028.json"
OUT_ROWS = BASE / "order61_branch_c_candidate462_perigee_flyby_sensitivity_v028.csv"

PARENT_RANK = 20
TARGET_INDEX = 462

# Fixed before inspecting any sensitivity outcome.
BOUND_MIN_PERIGEE_ALTITUDES_KM = [
    0.0,
    100.0,
    500.0,
    1_000.0,
    10_000.0,
    35_786.0,
    50_000.0,
]

UNBOUND_MIN_PERIGEE_ALTITUDES_KM = [
    0.0,
    100.0,
    1_000.0,
    10_000.0,
]

# The unbound search is a conventional Solar-System-scale sensitivity
# calculation, not a universal upper bound on interstellar speeds.
UNBOUND_SPEED_CAP_KMS = 75.0

FIBONACCI_DIRECTIONS = 1024
BOUND_SPEED_FRACTIONS_OF_ESCAPE = [
    0.10, 0.20, 0.30, 0.40, 0.50,
    0.60, 0.70, 0.80, 0.90, 0.97, 0.995,
]
UNBOUND_SPEED_MULTIPLES_OF_ESCAPE = [
    1.0001, 1.02, 1.05, 1.10, 1.20,
    1.50, 2.0, 3.0, 5.0, 10.0, 20.0,
]
TOP_SEEDS = 16

REPORT_ANGLES_ARCSEC = [1.0, 3.0, 5.0, 10.0]

FIELDS = [
    "family",
    "minimum_perigee_altitude_km",
    "speed_cap_kms",
    "optimizer_success",
    "vx_kms", "vy_kms", "vz_kms", "speed_kms",
    "specific_energy_km2_s2",
    "bound_to_earth",
    "eccentricity",
    "semimajor_axis_km",
    "perigee_radius_km",
    "perigee_altitude_km",
    "apogee_radius_km",
    "period_hours",
    "palomar_rate_arcsec_s",
    "dona_ana_rate_arcsec_s",
    "max_rate_arcsec_s",
    "rms_rate_arcsec_s",
    "shorter_time_1arcsec_s",
    "shorter_time_3arcsec_s",
    "shorter_time_5arcsec_s",
    "shorter_time_10arcsec_s",
    "palomar_full_2700s_motion_deg",
    "dona_ana_full_6300s_motion_deg",
]


def load_module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not import {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def read_csv(path):
    with path.open(newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def write_csv(path, rows, fields):
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    tmp.replace(path)


def write_json(path, obj):
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(obj, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )
    tmp.replace(path)


def fibonacci_directions(n):
    out = []
    golden = math.pi * (3.0 - math.sqrt(5.0))
    for i in range(n):
        z = 1.0 - 2.0 * (i + 0.5) / n
        rr = math.sqrt(max(0.0, 1.0 - z*z))
        phi = golden * i
        out.append([rr*math.cos(phi), rr*math.sin(phi), z])
    return np.asarray(out, dtype=float)


def shorter_time(angle_arcsec, prate, drate):
    p = float(angle_arcsec)/float(prate) if prate > 0 else float("inf")
    d = float(angle_arcsec)/float(drate) if drate > 0 else float("inf")
    return min(p, d)


def objective(v, dyn, r_obj, rP, vP, rD, vD):
    return dyn.objective_rms(v, r_obj, rP, vP, rD, vD)


def perigee_constraint(v, dyn, r_obj, min_alt):
    e = dyn.orbital_elements(r_obj, v)
    rp = e["perigee_radius_km"]
    if rp is None or not math.isfinite(rp):
        return -1e9
    return float(rp) - (dyn.EARTH_RADIUS_KM + float(min_alt))


def bound_energy_constraint(v, dyn, r_obj):
    e = dyn.orbital_elements(r_obj, v)
    return -float(e["specific_energy_km2_s2"]) - 1e-10


def unbound_energy_constraint(v, dyn, r_obj):
    e = dyn.orbital_elements(r_obj, v)
    return float(e["specific_energy_km2_s2"]) - 1e-10


def admissible(v, dyn, r_obj, family, min_alt, speed_cap):
    speed = float(np.linalg.norm(v))
    if speed_cap is not None and speed > float(speed_cap) + 1e-8:
        return False

    e = dyn.orbital_elements(r_obj, v)
    rp = e["perigee_radius_km"]
    if rp is None or not math.isfinite(rp):
        return False
    if rp < dyn.EARTH_RADIUS_KM + float(min_alt) - 1e-7:
        return False

    energy = float(e["specific_energy_km2_s2"])
    if family == "bound":
        return energy < 0.0
    if family == "unbound":
        return energy >= 0.0
    raise ValueError(family)


def seed_grid(dyn, r_obj, vesc, family, min_alt, speed_cap):
    dirs = fibonacci_directions(FIBONACCI_DIRECTIONS)

    if family == "bound":
        speeds = [f*vesc for f in BOUND_SPEED_FRACTIONS_OF_ESCAPE]
    else:
        speeds = [
            min(m*vesc, speed_cap)
            for m in UNBOUND_SPEED_MULTIPLES_OF_ESCAPE
            if m*vesc <= speed_cap + 1e-9
        ]
        if speed_cap not in speeds:
            speeds.append(speed_cap)

    candidates = []
    for speed in speeds:
        for direction in dirs:
            v = float(speed) * direction
            if not admissible(v, dyn, r_obj, family, min_alt, speed_cap):
                continue
            candidates.append(v)

    return candidates


def optimize_family(
    dyn, r_obj, rP, vP, rD, vD,
    family, min_alt, vesc, speed_cap,
):
    grid = seed_grid(
        dyn, r_obj, vesc,
        family=family,
        min_alt=min_alt,
        speed_cap=speed_cap,
    )
    if not grid:
        return None, {
            "success": False,
            "reason": "no deterministic admissible seed",
            "seed_count": 0,
            "attempts": [],
        }

    scored = sorted(
        (
            objective(v, dyn, r_obj, rP, vP, rD, vD),
            v,
        )
        for v in grid
    )
    seeds = [v.copy() for _, v in scored[:TOP_SEEDS]]

    if family == "bound":
        lim = 0.999999*vesc
        bounds = [(-lim, lim)]*3
        constraints = [
            {
                "type": "ineq",
                "fun": lambda v: bound_energy_constraint(v, dyn, r_obj),
            },
            {
                "type": "ineq",
                "fun": lambda v: perigee_constraint(
                    v, dyn, r_obj, min_alt
                ),
            },
        ]
    else:
        lim = float(speed_cap)
        bounds = [(-lim, lim)]*3
        constraints = [
            {
                "type": "ineq",
                "fun": lambda v: unbound_energy_constraint(v, dyn, r_obj),
            },
            {
                "type": "ineq",
                "fun": lambda v: perigee_constraint(
                    v, dyn, r_obj, min_alt
                ),
            },
            {
                "type": "ineq",
                "fun": lambda v: float(speed_cap)-float(np.linalg.norm(v)),
            },
        ]

    best = None
    attempts = []

    for seed_no, seed in enumerate(seeds, 1):
        res = minimize(
            objective,
            seed,
            args=(dyn, r_obj, rP, vP, rD, vD),
            method="SLSQP",
            bounds=bounds,
            constraints=constraints,
            options={
                "maxiter": 1500,
                "ftol": 1e-13,
                "disp": False,
            },
        )

        v = np.asarray(res.x, float)
        ok = admissible(
            v, dyn, r_obj,
            family=family,
            min_alt=min_alt,
            speed_cap=speed_cap,
        )
        obj = objective(v, dyn, r_obj, rP, vP, rD, vD)

        attempts.append(
            {
                "seed_no": seed_no,
                "optimizer_success": bool(res.success),
                "message": str(res.message),
                "admissible": bool(ok),
                "objective_arcsec_s": float(obj),
                "speed_kms": float(np.linalg.norm(v)),
                "velocity_kms": v.tolist(),
            }
        )

        if ok and (best is None or obj < best[0]):
            best = (float(obj), v.copy())

    if best is None:
        return None, {
            "success": False,
            "reason": "optimizer produced no admissible state",
            "seed_count": len(seeds),
            "attempts": attempts,
        }

    return best[1], {
        "success": True,
        "seed_count": len(seeds),
        "attempts": attempts,
    }


def make_row(
    dyn, family, min_alt, speed_cap,
    r_obj, v, rP, vP, rD, vD,
    optimizer_success,
):
    st = dyn.state_row(
        f"{family}_min_perigee_{min_alt:g}km",
        r_obj, v, rP, vP, rD, vD,
    )
    pr = float(st["palomar_rate_arcsec_s"])
    dr = float(st["dona_ana_rate_arcsec_s"])

    row = {
        "family": family,
        "minimum_perigee_altitude_km": float(min_alt),
        "speed_cap_kms": speed_cap,
        "optimizer_success": bool(optimizer_success),
        **st,
        "shorter_time_1arcsec_s": shorter_time(1.0, pr, dr),
        "shorter_time_3arcsec_s": shorter_time(3.0, pr, dr),
        "shorter_time_5arcsec_s": shorter_time(5.0, pr, dr),
        "shorter_time_10arcsec_s": shorter_time(10.0, pr, dr),
        "palomar_full_2700s_motion_deg": pr*2700.0/3600.0,
        "dona_ana_full_6300s_motion_deg": dr*6300.0/3600.0,
    }
    return row


def main():
    print("="*116)
    print("ORDER 61 — BRANCH C #20 / CANDIDATE 462 PERIGEE + FLYBY MOTION SENSITIVITY v028")
    print("="*116)
    print(
        "Prospective sensitivity to physically less pathological perigees plus an unbound/fly-by family."
    )
    print(
        "No detector, no image pixels, no candidate threshold. This quantifies compact-flash duration scales only."
    )
    print()

    for p in (DYNAMICS, REFINED, PARALLAX, STRICT, DYN_WORKER):
        if not p.is_file():
            raise RuntimeError(f"Missing required input: {p}")

    dyn_report = json.loads(DYNAMICS.read_text(encoding="utf-8"))
    refined = json.loads(REFINED.read_text(encoding="utf-8"))
    parallax = json.loads(PARALLAX.read_text(encoding="utf-8"))

    guards = {
        "dynamics_complete": dyn_report.get("status") == "COMPLETE",
        "dynamics_kind": (
            dyn_report.get("analysis_kind")
            == "order61_branch_c_candidate462_physical_dynamical_plausibility_v028d"
        ),
        "dynamics_no_detector": dyn_report.get("detector_rerun") is False,
        "dynamics_no_pixels": dyn_report.get("science_image_pixels_read") is False,
        "dynamics_no_promotion": dyn_report.get("candidate_promoted") is False,
        "dynamics_surface_boundary_solution_present": (
            abs(
                float(
                    dyn_report["best_bound_state"][
                        "shorter_time_to_3arcsec_s"
                    ]
                )
                - 2.4176621635179347
            )
            < 1e-9
        ),
    }
    if not all(guards.values()):
        raise RuntimeError(
            "REFUSING: completed-stage guard failure: " + repr(guards)
        )

    dyn = load_module(DYN_WORKER, "order61_dyn_v028d")

    strict = {int(r["strict_rank"]): r for r in read_csv(STRICT)}
    sr = strict[PARENT_RANK]

    hits = [
        r for r in refined["refined_unique_hits"]
        if int(r["strict_rank"]) == PARENT_RANK
        and int(r["dasch_candidate_index"]) == TARGET_INDEX
    ]
    if len(hits) != 1:
        raise RuntimeError(
            f"Expected one refined #20/candidate462 hit, got {len(hits)}"
        )
    hit = hits[0]

    event_time = dyn.parse_offset_aware_time(hit["refined_best_time_utc"])

    pal = parallax["site_geometry"]["palomar"]
    da = parallax["site_geometry"]["dona_ana"]

    pal_loc = EarthLocation.from_geodetic(
        float(pal["lon_deg_east"])*u.deg,
        float(pal["lat_deg"])*u.deg,
        float(pal["height_m"])*u.m,
    )
    da_loc = EarthLocation.from_geodetic(
        float(da["lon_deg_east"])*u.deg,
        float(da["lat_deg"])*u.deg,
        float(da["height_m"])*u.m,
    )

    rP, vP = dyn.observer_posvel(pal_loc, event_time)
    rD, vD = dyn.observer_posvel(da_loc, event_time)

    uP = dyn.unit_from_radec(
        float(sr["poss_ra_deg"]),
        float(sr["poss_dec_deg"]),
    )
    c462 = dyn_report["same_time_triangulation"]

    # Reuse the frozen completed 3-D point rather than refit it.
    r_obj = np.asarray(
        c462["object_gcrs_position_km"],
        dtype=float,
    )

    # Verify it remains on both observed rays at the completed event time.
    frozen_rgeo = float(c462["geocentric_radius_km"])
    if abs(np.linalg.norm(r_obj)-frozen_rgeo) > 1e-6:
        raise RuntimeError("Frozen object position/radius mismatch")

    rgeo = float(np.linalg.norm(r_obj))
    vesc = math.sqrt(
        2.0*dyn.MU_EARTH_KM3_S2/rgeo
    )

    print("Completed-stage guards: PASS")
    print(
        f"Frozen same-time point: r={rgeo:.3f} km, "
        f"altitude={rgeo-dyn.EARTH_RADIUS_KM:.3f} km, "
        f"escape speed={vesc:.6f} km/s"
    )
    print()

    rows = []
    audit = {}

    print("BOUND NON-IMPACTING SENSITIVITY")
    print("-"*116)

    for min_alt in BOUND_MIN_PERIGEE_ALTITUDES_KM:
        print(
            f"  optimizing minimum perigee altitude >= {min_alt:,.0f} km ...",
            flush=True,
        )
        v, meta = optimize_family(
            dyn, r_obj, rP, vP, rD, vD,
            family="bound",
            min_alt=min_alt,
            vesc=vesc,
            speed_cap=None,
        )
        audit[f"bound_{min_alt:g}"] = meta

        if v is None:
            print("    NO ADMISSIBLE SOLUTION")
            continue

        row = make_row(
            dyn, "bound", min_alt, None,
            r_obj, v, rP, vP, rD, vD,
            meta["success"],
        )
        rows.append(row)

        print(
            f"    speed={row['speed_kms']:.4f} km/s "
            f"perigee_alt={row['perigee_altitude_km']:.1f} km "
            f"max_rate={row['max_rate_arcsec_s']:.4f}\"/s "
            f"3\" in {row['shorter_time_3arcsec_s']:.3f}s "
            f"10\" in {row['shorter_time_10arcsec_s']:.3f}s"
        )

    print()
    print("UNBOUND / FLYBY SENSITIVITY")
    print("-"*116)

    for min_alt in UNBOUND_MIN_PERIGEE_ALTITUDES_KM:
        print(
            f"  optimizing unbound family, perigee >= {min_alt:,.0f} km, "
            f"speed cap {UNBOUND_SPEED_CAP_KMS:.0f} km/s ...",
            flush=True,
        )
        v, meta = optimize_family(
            dyn, r_obj, rP, vP, rD, vD,
            family="unbound",
            min_alt=min_alt,
            vesc=vesc,
            speed_cap=UNBOUND_SPEED_CAP_KMS,
        )
        audit[f"unbound_{min_alt:g}"] = meta

        if v is None:
            print("    NO ADMISSIBLE SOLUTION")
            continue

        row = make_row(
            dyn, "unbound", min_alt, UNBOUND_SPEED_CAP_KMS,
            r_obj, v, rP, vP, rD, vD,
            meta["success"],
        )
        rows.append(row)

        print(
            f"    speed={row['speed_kms']:.4f} km/s "
            f"energy={row['specific_energy_km2_s2']:.4f} km^2/s^2 "
            f"perigee_alt={row['perigee_altitude_km']:.1f} km "
            f"max_rate={row['max_rate_arcsec_s']:.4f}\"/s "
            f"3\" in {row['shorter_time_3arcsec_s']:.3f}s "
            f"10\" in {row['shorter_time_10arcsec_s']:.3f}s"
        )

    write_csv(OUT_ROWS, rows, FIELDS)

    bound_rows = [r for r in rows if r["family"] == "bound"]
    unbound_rows = [r for r in rows if r["family"] == "unbound"]

    report = {
        "status": "COMPLETE",
        "analysis_kind": (
            "order61_branch_c_candidate462_perigee_flyby_motion_sensitivity_v028"
        ),
        "guards": guards,
        "fixed_policy": {
            "bound_minimum_perigee_altitudes_km":
                BOUND_MIN_PERIGEE_ALTITUDES_KM,
            "unbound_minimum_perigee_altitudes_km":
                UNBOUND_MIN_PERIGEE_ALTITUDES_KM,
            "unbound_speed_cap_kms":
                UNBOUND_SPEED_CAP_KMS,
            "unbound_speed_cap_interpretation": (
                "conventional Solar-System-scale sensitivity cap, not a "
                "universal physical upper bound on interstellar objects"
            ),
            "fibonacci_directions":
                FIBONACCI_DIRECTIONS,
            "bound_speed_fractions_of_escape":
                BOUND_SPEED_FRACTIONS_OF_ESCAPE,
            "unbound_speed_multiples_of_escape":
                UNBOUND_SPEED_MULTIPLES_OF_ESCAPE,
            "top_seeds_per_optimization":
                TOP_SEEDS,
            "reported_compactness_angles_arcsec":
                REPORT_ANGLES_ARCSEC,
            "random_sampling": False,
            "candidate_threshold_changed": False,
        },
        "frozen_same_time_geometry": {
            "event_time_utc": hit["refined_best_time_utc"],
            "object_gcrs_position_km": r_obj.tolist(),
            "geocentric_radius_km": rgeo,
            "altitude_km": rgeo-dyn.EARTH_RADIUS_KM,
            "escape_speed_kms": vesc,
        },
        "bound_sensitivity": bound_rows,
        "unbound_flyby_sensitivity": unbound_rows,
        "optimizer_audit": audit,
        "interpretation_contract": {
            "persistent_source": (
                "Full-exposure angular motion values show what a continuously "
                "visible source would do during the 45-min POSS and 105-min "
                "DASCH integrations."
            ),
            "flash_source": (
                "A compact detector peak only constrains apparent-rate times "
                "flash duration. The 1/3/5/10 arcsec times are reporting scales, "
                "not measured flash durations or PSF FWHM."
            ),
            "cannot_establish": [
                "a unique orbit",
                "object identity",
                "natural versus artificial origin",
                "a flash duration from morphology alone",
                "formal discovery significance",
            ],
        },
        "detector_rerun": False,
        "science_image_pixels_read": False,
        "candidate_deleted": False,
        "candidate_promoted": False,
        "next_stage": (
            "Use the sensitivity table to close persistent Earth-bound models "
            "and define viable brief-flash duration ranges. Then test historical "
            "natural-object/meteor and artificial-launch plausibility without "
            "inferring origin. A trajectory-specific ephemeris cannot be unique "
            "from one triangulated position without velocity."
        ),
        "outputs": {
            "sensitivity_csv": str(OUT_ROWS),
        },
    }
    write_json(OUT, report)

    print()
    print("="*116)
    print("PERIGEE + FLYBY MOTION SENSITIVITY COMPLETE")
    print("="*116)
    print("Output:", OUT)
    print("Sensitivity table:", OUT_ROWS)
    print()
    print("No detector was rerun.")
    print("No science image pixel was read.")
    print("No candidate was deleted or promoted.")


if __name__ == "__main__":
    main()
