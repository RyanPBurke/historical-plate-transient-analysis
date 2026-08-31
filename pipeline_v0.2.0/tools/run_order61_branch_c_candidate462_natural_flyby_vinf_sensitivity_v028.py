from __future__ import annotations

from pathlib import Path
import csv
import importlib.util
import json
import math

import numpy as np
import astropy.units as u
from astropy.coordinates import EarthLocation
from scipy.optimize import minimize

ROOT = Path.cwd()
BASE = ROOT / "results" / "order61_native_full_v028"

SENSITIVITY = BASE / "order61_branch_c_candidate462_perigee_flyby_sensitivity_v028.json"
DYNAMICS = BASE / "order61_branch_c_candidate462_physical_dynamics_v028d.json"
REFINED = BASE / "order61_branch_c_refined_controls_v028.json"
PARALLAX = BASE / "order61_branch_c_parallax_preflight_v028.json"
STRICT = BASE / "order61_strict_match_triage.csv"
DYN_WORKER = ROOT / "tools" / "run_order61_branch_c_candidate462_physical_dynamics_v028d.py"

OUT = BASE / "order61_branch_c_candidate462_natural_flyby_vinf_sensitivity_v028.json"
OUT_ROWS = BASE / "order61_branch_c_candidate462_natural_flyby_vinf_sensitivity_v028.csv"

PARENT_RANK = 20
TARGET_INDEX = 462

# Prospectively fixed natural-flyby sensitivity grid.
VINF_FLOORS_KMS = [1.0, 5.0, 10.0, 20.0, 30.0, 50.0]
MIN_PERIGEE_ALTITUDES_KM = [100.0, 1_000.0, 10_000.0]
TOTAL_SPEED_CAP_KMS = 75.0

FIBONACCI_DIRECTIONS = 1024
TOP_SEEDS = 16

FIELDS = [
    "vinf_floor_kms",
    "minimum_perigee_altitude_km",
    "speed_cap_kms",
    "optimizer_success",
    "vx_kms", "vy_kms", "vz_kms",
    "speed_kms",
    "realized_vinf_kms",
    "specific_energy_km2_s2",
    "eccentricity",
    "perigee_radius_km",
    "perigee_altitude_km",
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
        z = 1.0 - 2.0*(i+0.5)/n
        rr = math.sqrt(max(0.0, 1.0-z*z))
        phi = golden*i
        out.append([rr*math.cos(phi), rr*math.sin(phi), z])
    return np.asarray(out, dtype=float)


def vinf_from_energy(energy):
    return math.sqrt(max(0.0, 2.0*float(energy)))


def energy_floor_constraint(v, dyn, r_obj, vinf_floor):
    e = dyn.orbital_elements(r_obj, v)
    target = 0.5*float(vinf_floor)**2
    return float(e["specific_energy_km2_s2"]) - target


def perigee_constraint(v, dyn, r_obj, min_alt):
    e = dyn.orbital_elements(r_obj, v)
    rp = e["perigee_radius_km"]
    if rp is None or not math.isfinite(rp):
        return -1e9
    return float(rp) - (dyn.EARTH_RADIUS_KM + float(min_alt))


def speed_cap_constraint(v):
    return TOTAL_SPEED_CAP_KMS - float(np.linalg.norm(v))


def admissible(v, dyn, r_obj, vinf_floor, min_alt):
    speed = float(np.linalg.norm(v))
    if speed > TOTAL_SPEED_CAP_KMS + 1e-8:
        return False

    e = dyn.orbital_elements(r_obj, v)
    energy = float(e["specific_energy_km2_s2"])
    if energy < 0.5*float(vinf_floor)**2 - 1e-8:
        return False

    rp = e["perigee_radius_km"]
    if rp is None or not math.isfinite(rp):
        return False
    if rp < dyn.EARTH_RADIUS_KM + float(min_alt) - 1e-6:
        return False

    return True


def objective(v, dyn, r_obj, rP, vP, rD, vD):
    return dyn.objective_rms(v, r_obj, rP, vP, rD, vD)


def seed_speeds(vinf_floor, vesc):
    # Speed at the frozen radius implied by each hyperbolic excess.
    vinfs = [
        vinf_floor,
        max(vinf_floor, vinf_floor*1.10),
        max(vinf_floor, vinf_floor*1.25),
        max(vinf_floor, vinf_floor*1.50),
        max(vinf_floor, vinf_floor*2.0),
    ]
    speeds = []
    for vi in vinfs:
        s = math.sqrt(vesc*vesc + vi*vi)
        if s <= TOTAL_SPEED_CAP_KMS + 1e-9:
            speeds.append(s)
    if not speeds:
        return []
    return sorted(set(round(s, 12) for s in speeds))


def optimize_one(
    dyn, r_obj, rP, vP, rD, vD,
    vinf_floor, min_alt, vesc,
):
    dirs = fibonacci_directions(FIBONACCI_DIRECTIONS)
    seeds = []

    for speed in seed_speeds(vinf_floor, vesc):
        for d in dirs:
            v = float(speed)*d
            if not admissible(v, dyn, r_obj, vinf_floor, min_alt):
                continue
            seeds.append(
                (
                    objective(v, dyn, r_obj, rP, vP, rD, vD),
                    v.copy(),
                )
            )

    if not seeds:
        return None, {
            "success": False,
            "reason": "no admissible deterministic seed",
            "attempts": [],
        }

    seeds.sort(key=lambda q: q[0])
    starts = [v for _, v in seeds[:TOP_SEEDS]]

    constraints = [
        {
            "type": "ineq",
            "fun": lambda v: energy_floor_constraint(
                v, dyn, r_obj, vinf_floor
            ),
        },
        {
            "type": "ineq",
            "fun": lambda v: perigee_constraint(
                v, dyn, r_obj, min_alt
            ),
        },
        {
            "type": "ineq",
            "fun": speed_cap_constraint,
        },
    ]
    bounds = [(-TOTAL_SPEED_CAP_KMS, TOTAL_SPEED_CAP_KMS)]*3

    best = None
    attempts = []

    for seed_no, seed in enumerate(starts, 1):
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
            vinf_floor=vinf_floor,
            min_alt=min_alt,
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
            "attempts": attempts,
        }

    return best[1], {
        "success": True,
        "attempts": attempts,
    }


def shorter_time(angle, prate, drate):
    p = float(angle)/float(prate) if prate > 0 else float("inf")
    d = float(angle)/float(drate) if drate > 0 else float("inf")
    return min(p, d)


def make_row(
    dyn, r_obj, v, rP, vP, rD, vD,
    vinf_floor, min_alt, optimizer_success,
):
    st = dyn.state_row(
        f"vinf_{vinf_floor:g}_perigee_{min_alt:g}",
        r_obj, v, rP, vP, rD, vD,
    )
    energy = float(st["specific_energy_km2_s2"])
    pr = float(st["palomar_rate_arcsec_s"])
    dr = float(st["dona_ana_rate_arcsec_s"])

    return {
        "vinf_floor_kms": float(vinf_floor),
        "minimum_perigee_altitude_km": float(min_alt),
        "speed_cap_kms": TOTAL_SPEED_CAP_KMS,
        "optimizer_success": bool(optimizer_success),
        "vx_kms": float(v[0]),
        "vy_kms": float(v[1]),
        "vz_kms": float(v[2]),
        "speed_kms": float(np.linalg.norm(v)),
        "realized_vinf_kms": vinf_from_energy(energy),
        "specific_energy_km2_s2": energy,
        "eccentricity": st["eccentricity"],
        "perigee_radius_km": st["perigee_radius_km"],
        "perigee_altitude_km": st["perigee_altitude_km"],
        "palomar_rate_arcsec_s": pr,
        "dona_ana_rate_arcsec_s": dr,
        "max_rate_arcsec_s": max(pr, dr),
        "rms_rate_arcsec_s": st["rms_rate_arcsec_s"],
        "shorter_time_1arcsec_s": shorter_time(1.0, pr, dr),
        "shorter_time_3arcsec_s": shorter_time(3.0, pr, dr),
        "shorter_time_5arcsec_s": shorter_time(5.0, pr, dr),
        "shorter_time_10arcsec_s": shorter_time(10.0, pr, dr),
        "palomar_full_2700s_motion_deg": pr*2700.0/3600.0,
        "dona_ana_full_6300s_motion_deg": dr*6300.0/3600.0,
    }


def main():
    print("="*116)
    print("ORDER 61 — BRANCH C #20 / CANDIDATE 462 NATURAL-FLYBY V_INFINITY SENSITIVITY v028")
    print("="*116)
    print(
        "Minimum apparent motion for genuine hyperbolic fly-bys with prospectively fixed "
        "v_infinity floors and non-impacting perigees."
    )
    print(
        "This is a physical sensitivity analysis, not an origin classifier or significance calculation."
    )
    print()

    for p in (
        SENSITIVITY,
        DYNAMICS,
        REFINED,
        PARALLAX,
        STRICT,
        DYN_WORKER,
    ):
        if not p.is_file():
            raise RuntimeError(f"Missing required input: {p}")

    prev = json.loads(SENSITIVITY.read_text(encoding="utf-8"))
    dyn_report = json.loads(DYNAMICS.read_text(encoding="utf-8"))
    refined = json.loads(REFINED.read_text(encoding="utf-8"))
    parallax = json.loads(PARALLAX.read_text(encoding="utf-8"))

    guards = {
        "previous_sensitivity_complete": prev.get("status") == "COMPLETE",
        "previous_unbound_zero_energy_boundary_present": all(
            abs(float(r["specific_energy_km2_s2"])) < 1e-5
            for r in prev.get("unbound_flyby_sensitivity", [])
        ),
        "dynamics_complete": dyn_report.get("status") == "COMPLETE",
        "dynamics_no_detector": dyn_report.get("detector_rerun") is False,
        "dynamics_no_pixels": dyn_report.get("science_image_pixels_read") is False,
        "dynamics_no_promotion": dyn_report.get("candidate_promoted") is False,
    }
    if not all(guards.values()):
        raise RuntimeError(
            "REFUSING: completed-stage guard failure: " + repr(guards)
        )

    dyn = load_module(DYN_WORKER, "order61_dyn_v028d")

    strict = {int(r["strict_rank"]): r for r in read_csv(STRICT)}
    _ = strict[PARENT_RANK]

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

    event_time = dyn.parse_offset_aware_time(
        hit["refined_best_time_utc"]
    )

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

    r_obj = np.asarray(
        dyn_report["same_time_triangulation"]["object_gcrs_position_km"],
        dtype=float,
    )
    rgeo = float(np.linalg.norm(r_obj))
    vesc = math.sqrt(
        2.0*dyn.MU_EARTH_KM3_S2/rgeo
    )

    print("Completed-stage guards: PASS")
    print(
        f"Frozen point: r={rgeo:.3f} km altitude="
        f"{rgeo-dyn.EARTH_RADIUS_KM:.3f} km v_escape={vesc:.6f} km/s"
    )
    print()

    rows = []
    audit = {}

    for vinf in VINF_FLOORS_KMS:
        print(f"V_INFINITY FLOOR >= {vinf:.1f} km/s")
        print("-"*116)

        for min_alt in MIN_PERIGEE_ALTITUDES_KM:
            print(
                f"  perigee altitude >= {min_alt:,.0f} km ...",
                flush=True,
            )

            v, meta = optimize_one(
                dyn, r_obj, rP, vP, rD, vD,
                vinf_floor=vinf,
                min_alt=min_alt,
                vesc=vesc,
            )
            audit[f"vinf_{vinf:g}_perigee_{min_alt:g}"] = meta

            if v is None:
                print("    NO ADMISSIBLE SOLUTION")
                continue

            row = make_row(
                dyn, r_obj, v, rP, vP, rD, vD,
                vinf_floor=vinf,
                min_alt=min_alt,
                optimizer_success=meta["success"],
            )
            rows.append(row)

            print(
                f"    realized v_inf={row['realized_vinf_kms']:.3f} km/s "
                f"speed={row['speed_kms']:.3f} km/s "
                f"perigee_alt={row['perigee_altitude_km']:.1f} km "
                f"max_rate={row['max_rate_arcsec_s']:.3f}\"/s "
                f"3\" in {row['shorter_time_3arcsec_s']:.3f}s "
                f"10\" in {row['shorter_time_10arcsec_s']:.3f}s"
            )

        print()

    write_csv(OUT_ROWS, rows, FIELDS)

    report = {
        "status": "COMPLETE",
        "analysis_kind": (
            "order61_branch_c_candidate462_natural_flyby_vinf_sensitivity_v028"
        ),
        "guards": guards,
        "fixed_policy": {
            "vinf_floors_kms": VINF_FLOORS_KMS,
            "minimum_perigee_altitudes_km":
                MIN_PERIGEE_ALTITUDES_KM,
            "total_speed_cap_kms":
                TOTAL_SPEED_CAP_KMS,
            "fibonacci_directions":
                FIBONACCI_DIRECTIONS,
            "top_seeds":
                TOP_SEEDS,
            "random_sampling": False,
            "candidate_threshold_changed": False,
        },
        "frozen_geometry": {
            "event_time_utc": hit["refined_best_time_utc"],
            "geocentric_radius_km": rgeo,
            "altitude_km": rgeo-dyn.EARTH_RADIUS_KM,
            "escape_speed_kms": vesc,
        },
        "results": rows,
        "optimizer_audit": audit,
        "interpretation_contract": {
            "vinf_definition": (
                "sqrt(2*specific orbital energy), i.e. geocentric "
                "hyperbolic excess speed for an unbound two-body trajectory"
            ),
            "compactness": (
                "Reported 1/3/5/10 arcsec crossing times are only motion "
                "scales. They are not measured flash durations or detector PSFs."
            ),
            "meteor_distinction": (
                "At ~75,000 km altitude the hypothetical object is a "
                "meteoroid/asteroid-like body, not an atmospheric meteor. "
                "Meteor luminosity from atmospheric ablation occurs much lower."
            ),
            "cannot_establish": [
                "object size or brightness without calibrated photometry",
                "a unique natural orbit",
                "natural versus artificial origin",
                "discovery significance",
            ],
        },
        "detector_rerun": False,
        "science_image_pixels_read": False,
        "candidate_deleted": False,
        "candidate_promoted": False,
        "next_stage": (
            "Use this grid with authoritative historical context: atmospheric "
            "meteor heights, known pre-Sputnik rocket altitude capability, and "
            "the absence of artificial Earth satellites before 1957. Preserve "
            "natural fly-by, photographic/systematic, and chance-association "
            "hypotheses unless independently excluded."
        ),
        "outputs": {
            "results_csv": str(OUT_ROWS),
        },
    }
    write_json(OUT, report)

    print("="*116)
    print("NATURAL-FLYBY V_INFINITY SENSITIVITY COMPLETE")
    print("="*116)
    print("Output:", OUT)
    print("Results:", OUT_ROWS)
    print()
    print("No detector was rerun.")
    print("No science image pixel was read.")
    print("No candidate was deleted or promoted.")


if __name__ == "__main__":
    main()
