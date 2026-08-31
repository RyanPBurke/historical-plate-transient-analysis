from __future__ import annotations

from pathlib import Path
import csv
import importlib.util
import json
import math
import warnings
from datetime import datetime, timezone

import numpy as np
import astropy.units as u
from astropy.coordinates import EarthLocation, SkyCoord, get_sun, get_body_barycentric
from astropy.time import Time
from astropy.utils import iers
from scipy.optimize import minimize

ROOT = Path.cwd()
BASE = ROOT / "results" / "order61_native_full_v028"

DIRECTIONAL = BASE / "order61_branch_c_candidate462_footprint_directional_controls_v028.json"
RECURRENCE = BASE / "order61_branch_c_candidate462_recurrence256_v028.json"
VALIDATION = BASE / "order61_branch_c_candidate462_validation_v028.json"
REFINED = BASE / "order61_branch_c_refined_controls_v028.json"
PARALLAX = BASE / "order61_branch_c_parallax_preflight_v028.json"
STRICT = BASE / "order61_strict_match_triage.csv"
PARALLAX_WORKER = ROOT / "tools" / "run_order61_branch_c_parallax_preflight_v028.py"

OUT = BASE / "order61_branch_c_candidate462_physical_dynamics_v028d.json"
OUT_STATES = BASE / "order61_branch_c_candidate462_velocity_states_v028d.csv"

PARENT_RANK = 20
TARGET_INDEX = 462

MU_EARTH_KM3_S2 = 398600.4418
EARTH_RADIUS_KM = 6378.137

# Fixed physical, non-promotional reporting thresholds.
COMPACTNESS_ANGLES_ARCSEC = [1.0, 3.0, 5.0, 10.0]

# Deterministic global seed grid for a bound, non-Earth-intersecting
# low-apparent-motion state. No random sampling.
FIBONACCI_DIRECTIONS = 768
SPEED_FRACTIONS = [0.15, 0.25, 0.35, 0.45, 0.55, 0.65, 0.75, 0.85, 0.93, 0.985]
SLSQP_TOP_SEEDS = 12

iers.conf.auto_download = False
iers.conf.iers_degraded_accuracy = "warn"

STATE_FIELDS = [
    "state_name",
    "vx_kms", "vy_kms", "vz_kms", "speed_kms",
    "specific_energy_km2_s2", "bound_to_earth",
    "eccentricity", "semimajor_axis_km",
    "perigee_radius_km", "perigee_altitude_km",
    "apogee_radius_km", "period_hours",
    "palomar_rate_arcsec_s", "dona_ana_rate_arcsec_s",
    "max_rate_arcsec_s", "rms_rate_arcsec_s",
    "palomar_time_1arcsec_s", "palomar_time_3arcsec_s",
    "palomar_time_5arcsec_s", "palomar_time_10arcsec_s",
    "dona_ana_time_1arcsec_s", "dona_ana_time_3arcsec_s",
    "dona_ana_time_5arcsec_s", "dona_ana_time_10arcsec_s",
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


def parse_offset_aware_time(value):
    """
    Implementation-only timestamp parser.

    The completed refinement report stores an ISO-8601 timestamp with an
    explicit +00:00 offset. Astropy Time's optional string-format parser does
    not accept that representation directly in this environment, so parse it
    first with Python datetime and pass the timezone-aware UTC datetime object
    to Time. No instant is altered.
    """
    s = str(value).strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        raise RuntimeError(f"Refined event time is timezone-naive: {value}")
    dt = dt.astimezone(timezone.utc)
    return Time(dt, scale="utc")


def unit_from_radec(ra_deg, dec_deg):
    ra = math.radians(float(ra_deg))
    dec = math.radians(float(dec_deg))
    return np.array(
        [math.cos(dec)*math.cos(ra), math.cos(dec)*math.sin(ra), math.sin(dec)],
        dtype=float,
    )


def angle_between_deg(a, b):
    """
    Return the angle between vectors without mutating caller-owned arrays.

    np.asarray() may return a view of an existing ndarray. The v028c worker
    normalised those views in place, unintentionally replacing physical
    vectors (including the ~1 AU Sun vector) with unit vectors. Defensive
    copies preserve all caller magnitudes.
    """
    a = np.array(a, dtype=float, copy=True)
    b = np.array(b, dtype=float, copy=True)

    an = float(np.linalg.norm(a))
    bn = float(np.linalg.norm(b))
    if not (math.isfinite(an) and math.isfinite(bn) and an > 0.0 and bn > 0.0):
        raise RuntimeError(
            f"REFUSING: angle_between_deg received invalid vector norms {an}, {bn}"
        )

    a /= an
    b /= bn
    return math.degrees(
        math.atan2(float(np.linalg.norm(np.cross(a, b))), float(np.dot(a, b)))
    )


def validated_geocentric_sun_vector_km(t):
    """
    Return a geocentric Sun vector with explicit physical sanity checks.

    Primary route: astropy.coordinates.get_sun(t), documented as GCRS.
    Independent cross-check: barycentric Sun minus barycentric Earth.

    GCRS axes are kinematically non-rotating and closely aligned with ICRS;
    the barycentric-difference route is used only as an independent check /
    fallback for distance-scale sanity. The reflection conclusions here are
    degree-scale, not sub-arcsecond solar astrometry.
    """
    direct = get_sun(t)
    direct_vec = np.asarray(direct.cartesian.xyz.to_value(u.km), dtype=float).reshape(3)
    direct_norm = float(np.linalg.norm(direct_vec))

    sun_bary = get_body_barycentric("sun", t)
    earth_bary = get_body_barycentric("earth", t)
    bary_vec = np.asarray(
        (sun_bary.xyz - earth_bary.xyz).to_value(u.km),
        dtype=float,
    ).reshape(3)
    bary_norm = float(np.linalg.norm(bary_vec))

    min_au_like_km = 1.30e8
    max_au_like_km = 1.70e8

    direct_valid = (
        np.all(np.isfinite(direct_vec))
        and min_au_like_km <= direct_norm <= max_au_like_km
    )
    bary_valid = (
        np.all(np.isfinite(bary_vec))
        and min_au_like_km <= bary_norm <= max_au_like_km
    )

    if not bary_valid:
        raise RuntimeError(
            "REFUSING: independent Sun-Earth barycentric vector has "
            f"nonphysical norm {bary_norm:.3f} km"
        )

    if direct_valid:
        angle_deg = angle_between_deg(direct_vec, bary_vec)
        fractional_distance_difference = abs(direct_norm-bary_norm)/bary_norm
        if angle_deg > 0.10 or fractional_distance_difference > 0.01:
            raise RuntimeError(
                "REFUSING: get_sun and barycentric Sun-Earth vectors disagree "
                f"materially: angle={angle_deg:.6f} deg, "
                f"distance_fraction={fractional_distance_difference:.6g}"
            )
        chosen = direct_vec
        method = "astropy_get_sun_GCRS_crosschecked_by_barycentric_difference"
    else:
        # Do not silently use a malformed direct vector; retain full audit
        # metadata and fall back only because the independent ~1 AU vector is
        # physically sane.
        chosen = bary_vec
        method = "barycentric_sun_minus_earth_fallback_after_invalid_get_sun_vector"
        angle_deg = None
        fractional_distance_difference = None

    return chosen, {
        "method": method,
        "get_sun_vector_norm_km": direct_norm,
        "get_sun_vector_valid_1au_scale": direct_valid,
        "barycentric_sun_minus_earth_norm_km": bary_norm,
        "barycentric_vector_valid_1au_scale": bary_valid,
        "crosscheck_angle_deg": angle_deg,
        "crosscheck_fractional_distance_difference": fractional_distance_difference,
        "accepted_geocentric_sun_vector_norm_km": float(np.linalg.norm(chosen)),
    }


def observer_pos(location: EarthLocation, t: Time):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        g = location.get_gcrs(t)
    return np.array(
        [
            g.cartesian.x.to_value(u.km),
            g.cartesian.y.to_value(u.km),
            g.cartesian.z.to_value(u.km),
        ],
        dtype=float,
    )


def observer_posvel(location: EarthLocation, t: Time):
    # Symmetric 1-second finite difference is more than sufficient for
    # observer rotational velocity at the precision relevant here.
    r0 = observer_pos(location, t)
    rm = observer_pos(location, t - 0.5*u.s)
    rp = observer_pos(location, t + 0.5*u.s)
    v = rp - rm  # km per 1 second
    return r0, v


def line_closest_approach(rA, uA, rB, uB):
    d = rB - rA
    b = float(np.dot(uA, uB))
    den = 1.0 - b*b
    if den <= 1e-18:
        return None
    dA = float(np.dot(d, uA))
    dB = float(np.dot(d, uB))
    s = (dA - b*dB) / den
    t = b*s - dB
    pA = rA + s*uA
    pB = rB + t*uB
    gap = float(np.linalg.norm(pA-pB))
    return s, t, gap, pA, pB


def orbital_elements(r, v):
    r = np.asarray(r, float)
    v = np.asarray(v, float)
    rn = float(np.linalg.norm(r))
    vn = float(np.linalg.norm(v))

    energy = 0.5*vn*vn - MU_EARTH_KM3_S2/rn
    h = np.cross(r, v)
    h2 = float(np.dot(h, h))
    evec = np.cross(v, h)/MU_EARTH_KM3_S2 - r/rn
    ecc = float(np.linalg.norm(evec))

    if energy < 0:
        a = -MU_EARTH_KM3_S2/(2.0*energy)
        rp = a*(1.0-ecc)
        ra = a*(1.0+ecc)
        period = 2.0*math.pi*math.sqrt(a**3/MU_EARTH_KM3_S2)
    else:
        a = None
        rp = h2/(MU_EARTH_KM3_S2*(1.0+ecc)) if (1.0+ecc) > 0 else None
        ra = None
        period = None

    return {
        "specific_energy_km2_s2": energy,
        "bound_to_earth": energy < 0,
        "eccentricity": ecc,
        "semimajor_axis_km": a,
        "perigee_radius_km": rp,
        "perigee_altitude_km": None if rp is None else rp-EARTH_RADIUS_KM,
        "apogee_radius_km": ra,
        "period_hours": None if period is None else period/3600.0,
    }


def apparent_rate_arcsec_s(r_obj, v_obj, r_obs, v_obs):
    rho = np.asarray(r_obj)-np.asarray(r_obs)
    dist = float(np.linalg.norm(rho))
    los = rho/dist
    relv = np.asarray(v_obj)-np.asarray(v_obs)
    trans = relv - float(np.dot(relv, los))*los
    rate_rad_s = float(np.linalg.norm(trans))/dist
    return math.degrees(rate_rad_s)*3600.0


def time_for_angle(angle_arcsec, rate_arcsec_s):
    if rate_arcsec_s <= 0:
        return None
    return float(angle_arcsec)/float(rate_arcsec_s)


def state_row(name, r_obj, v_obj, rP, vP, rD, vD):
    elems = orbital_elements(r_obj, v_obj)
    p_rate = apparent_rate_arcsec_s(r_obj, v_obj, rP, vP)
    d_rate = apparent_rate_arcsec_s(r_obj, v_obj, rD, vD)
    row = {
        "state_name": name,
        "vx_kms": float(v_obj[0]),
        "vy_kms": float(v_obj[1]),
        "vz_kms": float(v_obj[2]),
        "speed_kms": float(np.linalg.norm(v_obj)),
        **elems,
        "palomar_rate_arcsec_s": p_rate,
        "dona_ana_rate_arcsec_s": d_rate,
        "max_rate_arcsec_s": max(p_rate, d_rate),
        "rms_rate_arcsec_s": math.sqrt(0.5*(p_rate*p_rate+d_rate*d_rate)),
    }
    for a in COMPACTNESS_ANGLES_ARCSEC:
        row[f"palomar_time_{int(a)}arcsec_s"] = time_for_angle(a, p_rate)
        row[f"dona_ana_time_{int(a)}arcsec_s"] = time_for_angle(a, d_rate)
    return row


def fibonacci_directions(n):
    # Deterministic approximately uniform unit sphere.
    out = []
    golden = math.pi*(3.0-math.sqrt(5.0))
    for i in range(n):
        z = 1.0 - 2.0*(i+0.5)/n
        r = math.sqrt(max(0.0, 1.0-z*z))
        phi = golden*i
        out.append([r*math.cos(phi), r*math.sin(phi), z])
    return np.asarray(out, dtype=float)


def admissible_bound_nonimpacting(r_obj, v_obj):
    e = orbital_elements(r_obj, v_obj)
    return (
        e["bound_to_earth"]
        and e["perigee_radius_km"] is not None
        and e["perigee_radius_km"] >= EARTH_RADIUS_KM
    )


def objective_rms(v, r_obj, rP, vP, rD, vD):
    pr = apparent_rate_arcsec_s(r_obj, v, rP, vP)
    dr = apparent_rate_arcsec_s(r_obj, v, rD, vD)
    return math.sqrt(0.5*(pr*pr+dr*dr))


def perigee_constraint(r_obj, v):
    e = orbital_elements(r_obj, v)
    rp = e["perigee_radius_km"]
    if rp is None or not math.isfinite(rp):
        return -1e9
    return rp-EARTH_RADIUS_KM


def energy_constraint(r_obj, v):
    e = orbital_elements(r_obj, v)
    # Positive means bound, with a tiny numerical margin.
    return -e["specific_energy_km2_s2"] - 1e-8


def least_squares_kinematic_velocity(r_obj, rP, vP, rD, vD):
    mats = []
    rhs = []
    for ro, vo in ((rP, vP), (rD, vD)):
        rho = r_obj-ro
        dist = float(np.linalg.norm(rho))
        los = rho/dist
        P = np.eye(3)-np.outer(los, los)
        # Weight by inverse distance so squared residual corresponds to rate.
        W = P/dist
        mats.append(W)
        rhs.append(W@vo)
    A = np.vstack(mats)
    b = np.concatenate(rhs)
    v, *_ = np.linalg.lstsq(A, b, rcond=None)
    return np.asarray(v, float)


def best_bound_low_motion(r_obj, rP, vP, rD, vD, vesc):
    dirs = fibonacci_directions(FIBONACCI_DIRECTIONS)
    candidates = []

    for frac in SPEED_FRACTIONS:
        speed = float(frac)*vesc
        for d in dirs:
            v = speed*d
            if not admissible_bound_nonimpacting(r_obj, v):
                continue
            obj = objective_rms(v, r_obj, rP, vP, rD, vD)
            candidates.append((obj, v.copy()))

    if not candidates:
        raise RuntimeError("No admissible bound non-impacting velocity in deterministic seed grid")

    candidates.sort(key=lambda q: q[0])
    seeds = [v for _, v in candidates[:SLSQP_TOP_SEEDS]]

    # Add physically structured starts.
    rhat = r_obj/np.linalg.norm(r_obj)
    z = np.array([0.0, 0.0, 1.0])
    t1 = np.cross(z, rhat)
    if np.linalg.norm(t1) < 1e-8:
        t1 = np.cross(np.array([1.0, 0.0, 0.0]), rhat)
    t1 /= np.linalg.norm(t1)
    t2 = np.cross(rhat, t1)
    vcirc = math.sqrt(MU_EARTH_KM3_S2/np.linalg.norm(r_obj))

    structured = [
        vcirc*t1, -vcirc*t1, vcirc*t2, -vcirc*t2,
        0.75*vcirc*(t1+t2)/math.sqrt(2),
        0.75*vcirc*(t1-t2)/math.sqrt(2),
    ]
    seeds.extend(v for v in structured if admissible_bound_nonimpacting(r_obj, v))

    bounds = [(-0.9999*vesc, 0.9999*vesc)]*3
    constraints = [
        {"type": "ineq", "fun": lambda v: energy_constraint(r_obj, v)},
        {"type": "ineq", "fun": lambda v: perigee_constraint(r_obj, v)},
    ]

    best = None
    attempts = []
    for seed_no, seed in enumerate(seeds, 1):
        res = minimize(
            objective_rms,
            np.asarray(seed, float),
            args=(r_obj, rP, vP, rD, vD),
            method="SLSQP",
            bounds=bounds,
            constraints=constraints,
            options={"maxiter": 1000, "ftol": 1e-12, "disp": False},
        )
        v = np.asarray(res.x, float)
        admissible = admissible_bound_nonimpacting(r_obj, v)
        obj = objective_rms(v, r_obj, rP, vP, rD, vD)
        attempts.append(
            {
                "seed_no": seed_no,
                "success": bool(res.success),
                "message": str(res.message),
                "objective_arcsec_s": obj,
                "admissible": admissible,
                "velocity_kms": v.tolist(),
            }
        )
        if admissible and (best is None or obj < best[0]):
            best = (obj, v)

    if best is None:
        raise RuntimeError("Bound low-motion optimizer produced no admissible state")

    return best[1], attempts


def main():
    print("="*112)
    print("ORDER 61 — BRANCH C #20 / CANDIDATE 462 PHYSICAL-DYNAMICAL PLAUSIBILITY v028d")
    print("="*112)
    print(
        "Reconstruct the same-time 3-D point and evaluate Earth-bound/fly-by motion scales. "
        "This stage is contextual and cannot promote the candidate."
    )
    print(
        "Implementation amendments: offset-aware UTC parsing; independently cross-checked "
        "solar vector; angle helper normalises defensive copies rather than mutating "
        "physical vectors in place. Physical policy is unchanged."
    )
    print()

    for p in (
        DIRECTIONAL, RECURRENCE, VALIDATION, REFINED,
        PARALLAX, STRICT, PARALLAX_WORKER,
    ):
        if not p.is_file():
            raise RuntimeError(f"Missing required input: {p}")

    directional = json.loads(DIRECTIONAL.read_text(encoding="utf-8"))
    recurrence = json.loads(RECURRENCE.read_text(encoding="utf-8"))
    validation = json.loads(VALIDATION.read_text(encoding="utf-8"))
    refined = json.loads(REFINED.read_text(encoding="utf-8"))
    parallax = json.loads(PARALLAX.read_text(encoding="utf-8"))

    ann = directional.get("candidate_specific_annulus", {})
    full = directional.get("full_grid", {})

    guards = {
        "directional_complete": directional.get("status") == "COMPLETE",
        "directional_annulus_zero_beating_controls": ann.get("controls_at_least_as_close_as_observed") == 0,
        "directional_annulus_96_valid": ann.get("valid_rotated_controls") == 96,
        "directional_annulus_p_1over97": abs(float(ann.get("finite_sample_empirical_directional_p")) - 1/97) < 1e-12,
        "directional_full_common_p_3over97": abs(float(full.get("common_support_empirical_p")) - 3/97) < 1e-12,
        "recurrence_complete": recurrence.get("status") == "COMPLETE",
        "recurrence_0_of_256_5arcsec": recurrence.get("summary", {}).get("plates_with_source_within_5arcsec") == 0,
        "validation_survives": validation.get("disposition") == "BRANCH_C_20_NEW_COUNTERPART_SURVIVES_STATIC_AND_MATCHED_PEER_MORPHOLOGY",
        "validation_sunlit": validation.get("illumination", {}).get("state") == "FULLY_SUNLIT_BY_SPHERICAL_EARTH_MODEL",
        "no_prior_promotion": validation.get("candidate_promoted") is False and directional.get("candidate_promoted") is False,
    }
    if not all(guards.values()):
        raise RuntimeError("REFUSING: completed-stage guard failure: "+repr(guards))

    rows = {int(r["strict_rank"]): r for r in read_csv(STRICT)}
    sr = rows[PARENT_RANK]

    hits20 = [
        r for r in refined["refined_unique_hits"]
        if int(r["strict_rank"]) == PARENT_RANK
        and int(r["dasch_candidate_index"]) == TARGET_INDEX
    ]
    if len(hits20) != 1:
        raise RuntimeError(f"Expected exactly one refined #20/candidate462 hit, got {len(hits20)}")
    hit = hits20[0]

    event_time = parse_offset_aware_time(hit["refined_best_time_utc"])
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

    rP, vP = observer_posvel(pal_loc, event_time)
    rD, vD = observer_posvel(da_loc, event_time)

    uP = unit_from_radec(float(sr["poss_ra_deg"]), float(sr["poss_dec_deg"]))
    c462 = validation["new_dasch_counterpart"]
    uD = unit_from_radec(float(c462["ra_deg"]), float(c462["dec_deg"]))

    q = line_closest_approach(rP, uP, rD, uD)
    if q is None:
        raise RuntimeError("Sightline triangulation failed")
    sP, sD, gap, pP, pD = q
    r_obj = 0.5*(pP+pD)

    if abs(sP-float(hit["refined_palomar_range_km"])) > 2.0:
        raise RuntimeError("Reconstructed Palomar range differs from frozen refined result by >2 km")
    if abs(sD-float(hit["refined_dona_ana_range_km"])) > 2.0:
        raise RuntimeError("Reconstructed Doña Ana range differs from frozen refined result by >2 km")

    rgeo = float(np.linalg.norm(r_obj))
    altitude = rgeo-EARTH_RADIUS_KM
    vcirc = math.sqrt(MU_EARTH_KM3_S2/rgeo)
    vesc = math.sqrt(2.0*MU_EARTH_KM3_S2/rgeo)
    tcirc = 2.0*math.pi*math.sqrt(rgeo**3/MU_EARTH_KM3_S2)

    toP = rP-r_obj
    toD = rD-r_obj
    observer_sep_deg = angle_between_deg(toP, toD)

    r_sun, sun_vector_audit = validated_geocentric_sun_vector_km(event_time)
    toSun = r_sun-r_obj
    sun_object_distance_km = float(np.linalg.norm(toSun))

    if not (1.20e8 <= sun_object_distance_km <= 1.80e8):
        raise RuntimeError(
            "REFUSING: Sun-object distance is nonphysical for an Earth-near object: "
            f"{sun_object_distance_km:.3f} km"
        )

    phase_P = angle_between_deg(toSun, toP)
    phase_D = angle_between_deg(toSun, toD)

    solar_radius_ratio = 695700.0/sun_object_distance_km
    if not (0.0 < solar_radius_ratio < 0.02):
        raise RuntimeError(
            "REFUSING: nonphysical solar angular-radius ratio "
            f"{solar_radius_ratio:.9g}"
        )

    sun_ang_radius_deg = math.degrees(math.asin(solar_radius_ratio))
    if not (0.20 <= sun_ang_radius_deg <= 0.35):
        raise RuntimeError(
            "REFUSING: solar angular radius outside physical near-Earth range: "
            f"{sun_ang_radius_deg:.6f} deg"
        )

    sun_diameter_deg = 2.0*sun_ang_radius_deg

    print("Completed-stage guards: PASS")
    print()
    print("TRIANGULATED SAME-TIME GEOMETRY")
    print("-"*112)
    print(f"Event time:              {event_time.utc.isot}")
    print(f"Palomar topocentric:     {sP:.3f} km")
    print(f"Doña Ana topocentric:    {sD:.3f} km")
    print(f"Ray-to-ray gap:          {gap:.6f} km")
    print(f"Geocentric radius:       {rgeo:.3f} km")
    print(f"Altitude above R_eq:     {altitude:.3f} km")
    print(f"Observer separation as seen from object: {observer_sep_deg:.6f} deg")
    print(
        f"Solar vector:             {sun_vector_audit['method']} | "
        f"accepted norm={sun_vector_audit['accepted_geocentric_sun_vector_norm_km']:.1f} km"
    )
    print(f"Sun-object distance:      {sun_object_distance_km:.1f} km")
    print(f"Solar angular diameter at object:         {sun_diameter_deg:.6f} deg")
    print(f"Sun-object-Palomar phase angle:           {phase_P:.3f} deg")
    print(f"Sun-object-Doña Ana phase angle:          {phase_D:.3f} deg")
    print()

    print("LOCAL EARTH-ORBIT SPEED SCALE")
    print("-"*112)
    print(f"Circular speed:          {vcirc:.6f} km/s")
    print(f"Escape speed:            {vesc:.6f} km/s")
    print(f"Circular period:         {tcirc/3600.0:.3f} h")
    print()

    # Structured velocity states.
    rhat = r_obj/rgeo
    z = np.array([0.0,0.0,1.0])
    east = np.cross(z, rhat)
    if np.linalg.norm(east) < 1e-8:
        east = np.cross(np.array([1.0,0.0,0.0]), rhat)
    east /= np.linalg.norm(east)

    states = []

    v_ls = least_squares_kinematic_velocity(r_obj, rP, vP, rD, vD)
    states.append(state_row("unconstrained_kinematic_least_squares", r_obj, v_ls, rP, vP, rD, vD))
    states.append(state_row("circular_eastward_example", r_obj, vcirc*east, rP, vP, rD, vD))
    states.append(state_row("circular_westward_example", r_obj, -vcirc*east, rP, vP, rD, vD))

    print("Searching deterministic bound, non-Earth-intersecting low-motion velocity family ...", flush=True)
    vbest, attempts = best_bound_low_motion(r_obj, rP, vP, rD, vD, vesc)
    states.append(state_row("best_bound_nonimpacting_low_motion", r_obj, vbest, rP, vP, rD, vD))

    write_csv(OUT_STATES, states, STATE_FIELDS)

    print()
    print("APPARENT MOTION STATES")
    print("-"*112)
    for st in states:
        print(
            f"{st['state_name']}: speed={st['speed_kms']:.4f} km/s "
            f"bound={st['bound_to_earth']} perigee_alt={st['perigee_altitude_km']} km"
        )
        print(
            f"  Palomar={st['palomar_rate_arcsec_s']:.4f}\"/s "
            f"DoñaAna={st['dona_ana_rate_arcsec_s']:.4f}\"/s "
            f"max={st['max_rate_arcsec_s']:.4f}\"/s"
        )
        print(
            f"  time to 3\": P={st['palomar_time_3arcsec_s']} s "
            f"D={st['dona_ana_time_3arcsec_s']} s"
        )

    best_state = next(s for s in states if s["state_name"] == "best_bound_nonimpacting_low_motion")
    ls_state = next(s for s in states if s["state_name"] == "unconstrained_kinematic_least_squares")

    ideal_flat_mirror_same_instant = observer_sep_deg <= sun_diameter_deg
    extra_beam_diameter_deg = max(0.0, observer_sep_deg-sun_diameter_deg)

    if best_state["max_rate_arcsec_s"] > 0:
        best_3arcsec_max_duration = min(
            best_state["palomar_time_3arcsec_s"],
            best_state["dona_ana_time_3arcsec_s"],
        )
    else:
        best_3arcsec_max_duration = None

    report = {
        "status": "COMPLETE",
        "analysis_kind": "order61_branch_c_candidate462_physical_dynamical_plausibility_v028d",
        "guards": guards,
        "implementation_amendments": [
            {
                "prior_worker": "run_order61_branch_c_candidate462_physical_dynamics_v028.py",
                "failure_stage": "timestamp parsing before any physical geometry calculation",
                "prior_physical_outputs_produced": False,
                "change": (
                    "parse refined_best_time_utc with datetime.fromisoformat(), normalize "
                    "to UTC, then construct astropy Time from the timezone-aware datetime"
                ),
                "event_instant_changed": False,
                "geometry_policy_changed": False,
                "velocity_search_changed": False,
                "physical_constants_changed": False,
                "candidate_logic_changed": False
            },
            {
                "prior_worker": "run_order61_branch_c_candidate462_physical_dynamics_v028b.py",
                "failure_stage": (
                    "solar angular-size calculation before any completed physical report "
                    "or velocity-state output"
                ),
                "prior_completed_physical_outputs_produced": False,
                "change": (
                    "validate geocentric Sun vector with independent get_sun and "
                    "Sun-minus-Earth barycentric routes; require physical ~1 AU scale "
                    "and plausible solar angular radius before reflection calculations"
                ),
                "asin_argument_clipped": False,
                "event_instant_changed": False,
                "triangulated_object_geometry_changed": False,
                "velocity_search_changed": False,
                "physical_constants_changed": False,
                "candidate_logic_changed": False
            },
            {
                "prior_worker": "run_order61_branch_c_candidate462_physical_dynamics_v028c.py",
                "failure_stage": (
                    "post-triangulation Sun-object distance sanity guard before any "
                    "completed physical report or velocity-state output"
                ),
                "prior_completed_physical_outputs_produced": False,
                "root_cause": (
                    "angle_between_deg used np.asarray followed by in-place normalisation; "
                    "caller-owned Sun vectors were mutated from ~1 AU to unit length"
                ),
                "change": (
                    "angle_between_deg now makes defensive float copies and validates "
                    "finite nonzero norms before normalising"
                ),
                "event_instant_changed": False,
                "triangulated_object_geometry_changed": False,
                "solar_vector_source_changed": False,
                "velocity_search_changed": False,
                "physical_constants_changed": False,
                "candidate_logic_changed": False
            }
        ],
        "same_time_triangulation": {
            "event_time_utc": event_time.utc.isot,
            "palomar_topocentric_range_km": sP,
            "dona_ana_topocentric_range_km": sD,
            "ray_gap_km": gap,
            "object_gcrs_position_km": r_obj.tolist(),
            "geocentric_radius_km": rgeo,
            "approx_altitude_above_equatorial_radius_km": altitude,
            "observer_separation_seen_from_object_deg": observer_sep_deg,
        },
        "earth_orbit_scale": {
            "mu_earth_km3_s2": MU_EARTH_KM3_S2,
            "earth_radius_km": EARTH_RADIUS_KM,
            "circular_speed_kms": vcirc,
            "escape_speed_kms": vesc,
            "circular_period_hours": tcirc/3600.0,
        },
        "illumination_reflection_geometry": {
            "validation_state": validation["illumination"]["state"],
            "sun_vector_audit": sun_vector_audit,
            "sun_object_distance_km": sun_object_distance_km,
            "sun_angular_radius_deg": sun_ang_radius_deg,
            "sun_angular_diameter_deg": sun_diameter_deg,
            "observer_separation_deg": observer_sep_deg,
            "sun_object_palomar_phase_deg": phase_P,
            "sun_object_dona_ana_phase_deg": phase_D,
            "ideal_single_flat_facet_same_instant_can_cover_both_observers_with_reflected_solar_disk": ideal_flat_mirror_same_instant,
            "minimum_additional_reflection_lobe_diameter_beyond_solar_disk_deg_to_cover_both_lines": extra_beam_diameter_deg,
            "caveat": (
                "This flat-facet test applies only to the same-instant single-facet hypothesis. "
                "Rough/diffuse surfaces, multiple facets, extended scattering lobes, or flashes at "
                "different times within the overlapping long exposures are not excluded."
            ),
        },
        "velocity_states": states,
        "best_bound_state": {
            "state_name": best_state["state_name"],
            "max_apparent_rate_arcsec_s": best_state["max_rate_arcsec_s"],
            "rms_apparent_rate_arcsec_s": best_state["rms_rate_arcsec_s"],
            "time_to_3arcsec_palomar_s": best_state["palomar_time_3arcsec_s"],
            "time_to_3arcsec_dona_ana_s": best_state["dona_ana_time_3arcsec_s"],
            "shorter_time_to_3arcsec_s": best_3arcsec_max_duration,
            "interpretation": (
                "Even the most slowly moving bound non-Earth-intersecting state found here "
                "sets only a flash-duration/motion scale. A sufficiently brief optical flash "
                "can remain compact on a long photographic exposure."
            ),
        },
        "unconstrained_kinematic_lower_context": {
            "state_name": ls_state["state_name"],
            "bound_to_earth": ls_state["bound_to_earth"],
            "perigee_altitude_km": ls_state["perigee_altitude_km"],
            "max_apparent_rate_arcsec_s": ls_state["max_rate_arcsec_s"],
            "interpretation": (
                "Pure kinematic least-squares lower-motion context; not accepted as a physical orbit "
                "unless its orbital elements are bound and non-Earth-intersecting."
            ),
        },
        "optimizer": {
            "fibonacci_directions": FIBONACCI_DIRECTIONS,
            "speed_fractions_of_escape": SPEED_FRACTIONS,
            "slsqp_seed_count": len(attempts),
            "attempts": attempts,
            "constraint_bound_to_earth": True,
            "constraint_perigee_radius_at_least_earth_radius": True,
            "random_sampling": False,
        },
        "interpretation_contract": {
            "same_time_hypothesis": (
                "Branch-C triangulation assumes the Palomar and Doña Ana flashes occurred at the same "
                "instant. The photographic plates constrain only exposure overlap, not intra-exposure "
                "flash time. Non-simultaneous two-flash trajectories have more freedom and are not "
                "tested by this worker."
            ),
            "compactness": (
                "Point-like morphology on a long exposure constrains flash duration multiplied by "
                "apparent angular rate, not the full exposure duration, unless persistent emission is assumed."
            ),
            "cannot_establish": [
                "object identity",
                "artificial versus natural origin",
                "a unique orbit from one triangulated position without velocity",
                "formal discovery significance from geometry-control empirical p-values",
            ],
        },
        "historical_artificial_object_context_required": True,
        "detector_rerun": False,
        "science_image_pixels_read": False,
        "candidate_deleted": False,
        "candidate_promoted": False,
        "next_stage": (
            "Interpret the physical outputs together with historical launch chronology. If an Earth-bound "
            "persistent-source state requires motion incompatible with compact morphology, retain only brief-flash "
            "models. If the same-instant specular geometry is too narrow for both sites, distinguish ideal single-facet "
            "glint from rough/multiple-facet or non-simultaneous reflection models. Do not infer artificial origin."
        ),
        "outputs": {
            "velocity_states_csv": str(OUT_STATES),
        },
    }
    write_json(OUT, report)

    print()
    print("="*112)
    print("PHYSICAL-DYNAMICAL PLAUSIBILITY COMPLETE")
    print("="*112)
    print("Output:", OUT)
    print("Velocity states:", OUT_STATES)
    print()
    print("No detector was rerun.")
    print("No science image pixel was read.")
    print("No candidate was deleted or promoted.")


if __name__ == "__main__":
    main()
