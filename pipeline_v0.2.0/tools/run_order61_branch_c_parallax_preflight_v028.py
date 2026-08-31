from __future__ import annotations

from pathlib import Path
from datetime import datetime, timezone, timedelta
import csv
import json
import math
import warnings

import numpy as np
import astropy.units as u
from astropy.coordinates import EarthLocation
from astropy.time import Time
from astropy.utils import iers
from scipy.spatial import cKDTree

ROOT = Path.cwd()
BASE = ROOT / "results" / "order61_native_full_v028"

PAIR_REPORT = BASE / "order61_whole_pair_report.json"
STRICT = BASE / "order61_strict_match_triage.csv"
DASCH_CAND = BASE / "order61_dasch_native_candidates.csv"
PHYS = BASE / "order61_physical_interpretation_preflight_v028.json"
DISCOVERY = (
    BASE / "order61_discovery_plate_audit_v028c"
    / "order61_discovery_plate_audit_report_v028c.json"
)

OUT = BASE / "order61_branch_c_parallax_preflight_v028.json"
OUT_BEST = BASE / "order61_branch_c_parallax_nearest_matches_v028.csv"
OUT_STRICT = BASE / "order61_branch_c_existing_strict_counterpart_geometry_v028.csv"

ACTIVE_RANKS = [11, 14, 20]

# ----------------------------------------------------------------------
# VERIFIED OBSERVING SITES
# ----------------------------------------------------------------------
# Palomar: Caltech Palomar RMS almanac:
# longitude +7h47m27s W, latitude +33d21.4m, elevation 1706 m.
PALOMAR = {
    "name": "Palomar Observatory",
    "lat_deg": 33.0 + 21.4/60.0,
    "lon_deg_east": -(7.0 + 47.0/60.0 + 27.0/3600.0) * 15.0,
    "height_m": 1706.0,
    "source": "Caltech Palomar Observatory RMS almanac",
    "source_url": "https://reservations.palomar.caltech.edu/almanac/",
}

# Doña Ana: F. L. Whipple, Astronomical Journal 59 (1954), contemporary
# geodetic station listing. Longitude is west in the published New Mexico
# station table. The same paper gives Soledad<->Doña Ana separation 28.6 km.
DONA_ANA = {
    "name": "Harvard Doña Ana meteor/patrol station, New Mexico",
    "lat_deg": 32.0 + 30.0/60.0 + 21.94/3600.0,
    "lon_deg_east": -(106.0 + 47.0/60.0 + 58.50/3600.0),
    "height_m": 1412.0,
    "source": "Whipple 1954 AJ 59, 201, contemporary geodetic station table",
    "source_url": "https://adsabs.harvard.edu/pdf/1954AJ.....59..201W",
}

# The official StarGlass plate-detail location identifies ai44092 as Doña Ana
# but its numeric coordinates are retained only as approximate metadata, not
# precision geometry.

# ----------------------------------------------------------------------
# PROSPECTIVELY FIXED BRANCH-C PREFLIGHT GRID
# ----------------------------------------------------------------------
TIME_STEP_SECONDS = 30

RANGE_BINS_KM = [
    ("0.5-2k_LEO_like",        500.0,        2_000.0,   32),
    ("2-30k_MEO_like",       2_000.0,       30_000.0,  64),
    ("30-50k_GEO_focus",    30_000.0,       50_000.0,  48),
    ("50-100k",             50_000.0,      100_000.0,  48),
    ("100-500k_high_lunar",100_000.0,      500_000.0,  64),
    # Distant controls show where the observed near-coincident counterpart
    # would become geometrically possible; these are NOT "near-Earth".
    ("0.5-5M_distant",     500_000.0,    5_000_000.0,  48),
    ("5-50M_distant",    5_000_000.0,   50_000_000.0,  48),
    ("50-200M_distant", 50_000_000.0,  200_000_000.0,  64),
]

BROAD_DIAGNOSTIC_ARCSEC = 10.0
STRICT_DIAGNOSTIC_ARCSEC = 3.0

# Avoid network EOP downloads. Historical UT1 uncertainty is recorded as a
# limitation; it is immaterial to degree-scale near-Earth parallax conclusions.
iers.conf.auto_download = False
iers.conf.iers_degraded_accuracy = "warn"


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


def parse_iso_utc(s):
    q = str(s).strip()
    if q.endswith("Z"):
        q = q[:-1] + "+00:00"
    dt = datetime.fromisoformat(q)
    if dt.tzinfo is None:
        raise RuntimeError(f"timezone-naive timestamp: {s}")
    return dt.astimezone(timezone.utc)


def unit_from_radec(ra_deg, dec_deg):
    ra = math.radians(float(ra_deg))
    dec = math.radians(float(dec_deg))
    return np.array([
        math.cos(dec)*math.cos(ra),
        math.cos(dec)*math.sin(ra),
        math.sin(dec),
    ], dtype=float)


def radec_from_unit(v):
    v = np.asarray(v, dtype=float)
    v = v / np.linalg.norm(v)
    ra = math.degrees(math.atan2(v[1], v[0])) % 360.0
    dec = math.degrees(math.atan2(v[2], math.hypot(v[0], v[1])))
    return ra, dec


def angle_arcsec(a, b):
    a = np.asarray(a, float)
    b = np.asarray(b, float)
    c = float(np.dot(a, b) / (np.linalg.norm(a)*np.linalg.norm(b)))
    c = max(-1.0, min(1.0, c))
    # atan2 formulation is better conditioned for arcsecond separations.
    s = float(np.linalg.norm(np.cross(a/np.linalg.norm(a), b/np.linalg.norm(b))))
    return math.degrees(math.atan2(s, c)) * 3600.0


def make_range_grid(lo, hi, n):
    # Geometric spacing is appropriate over orders of magnitude; include edges.
    return np.geomspace(float(lo), float(hi), int(n))


def observer_xyz_km(location: EarthLocation, times: Time):
    # GCRS axes are kinematically aligned to ICRS. EarthLocation.get_gcrs()
    # gives the terrestrial observing position in that inertial orientation.
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        g = location.get_gcrs(times)
    return np.stack([
        g.cartesian.x.to_value(u.km),
        g.cartesian.y.to_value(u.km),
        g.cartesian.z.to_value(u.km),
    ], axis=-1)


def nearest_candidate(tree, cand_vectors, pred_u):
    chord, idx = tree.query(pred_u, k=1)
    # Convert chord length on unit sphere to angular separation robustly.
    chord = max(0.0, min(2.0, float(chord)))
    sep_rad = 2.0 * math.asin(chord/2.0)
    return int(idx), math.degrees(sep_rad)*3600.0


def line_closest_approach(rA, uA, rB, uB):
    # Rays rA+s*uA and rB+t*uB. Return closest positive/negative line solution.
    d = rB - rA
    b = float(np.dot(uA, uB))
    den = 1.0 - b*b
    if den <= 1e-16:
        return None
    dA = float(np.dot(d, uA))
    dB = float(np.dot(d, uB))
    s = (dA - b*dB) / den
    t = b*s - dB
    pA = rA + s*uA
    pB = rB + t*uB
    gap = float(np.linalg.norm(pA-pB))
    return s, t, gap


def main():
    print("=" * 110)
    print("ORDER 61 — BRANCH C TOPOCENTRIC PARALLAX LOCUS PREFLIGHT v028")
    print("=" * 110)
    print(
        "Palomar POSS survivor -> predicted Doña Ana locus over event time/range; "
        "search all frozen DASCH candidates. No detector rerun."
    )
    print()

    for p in (PAIR_REPORT, STRICT, DASCH_CAND, PHYS, DISCOVERY):
        if not p.is_file():
            raise RuntimeError(f"Missing required completed-stage input: {p}")

    pair = json.loads(PAIR_REPORT.read_text(encoding="utf-8"))
    phys = json.loads(PHYS.read_text(encoding="utf-8"))
    discovery = json.loads(DISCOVERY.read_text(encoding="utf-8"))

    guards = {
        "pair_complete": pair.get("status") == "COMPLETE",
        "order61": int(pair.get("canonical_order", -1)) == 61,
        "physical_preflight_complete": phys.get("status") == "COMPLETE",
        "physical_preflight_site_name": (
            str(phys.get("site_resolution", {}).get("name", "")).lower()
            .replace("ñ", "n").startswith("dona ana")
        ),
        "physical_preflight_no_geometry": phys.get("branch_c_geometry_executed") is False,
        "discovery_complete": discovery.get("status") == "COMPLETE",
        "discovery_detector_not_rerun": discovery.get("detector_rerun") is False,
    }
    if not all(guards.values()):
        raise RuntimeError("REFUSING: completed-stage guard failure: " + repr(guards))

    strict_rows = read_csv(STRICT)
    sby = {int(r["strict_rank"]): r for r in strict_rows}
    if any(r not in sby for r in ACTIVE_RANKS):
        raise RuntimeError("missing active strict survivor row")

    dcand = read_csv(DASCH_CAND)
    if len(dcand) != 4109:
        raise RuntimeError(f"REFUSING: expected 4109 frozen DASCH candidates, got {len(dcand)}")

    cand_vec = np.stack([
        unit_from_radec(float(r["ra_deg"]), float(r["dec_deg"]))
        for r in dcand
    ])
    tree = cKDTree(cand_vec)

    start = parse_iso_utc(pair["overlap_start_utc"])
    end = parse_iso_utc(pair["overlap_end_utc"])
    if not end > start:
        raise RuntimeError("invalid overlap interval")

    nsteps = int(math.floor((end-start).total_seconds()/TIME_STEP_SECONDS))
    dts = [
        start + timedelta(seconds=i*TIME_STEP_SECONDS)
        for i in range(nsteps+1)
    ]
    if dts[-1] < end:
        dts.append(end)

    times = Time(dts, scale="utc")

    pal_loc = EarthLocation.from_geodetic(
        PALOMAR["lon_deg_east"]*u.deg,
        PALOMAR["lat_deg"]*u.deg,
        PALOMAR["height_m"]*u.m,
    )
    da_loc = EarthLocation.from_geodetic(
        DONA_ANA["lon_deg_east"]*u.deg,
        DONA_ANA["lat_deg"]*u.deg,
        DONA_ANA["height_m"]*u.m,
    )

    rP = observer_xyz_km(pal_loc, times)
    rD = observer_xyz_km(da_loc, times)
    baseline = rD-rP
    baseline_norm = np.linalg.norm(baseline, axis=1)

    print("Completed-stage guards: PASS")
    print(
        f"Overlap: {start.isoformat()} -> {end.isoformat()} "
        f"({(end-start).total_seconds()/60:.1f} min)"
    )
    print(f"Time grid: {len(dts)} samples at {TIME_STEP_SECONDS}s")
    print(
        "Palomar: "
        f"lat={PALOMAR['lat_deg']:.8f} lon={PALOMAR['lon_deg_east']:.8f} "
        f"h={PALOMAR['height_m']:.0f}m"
    )
    print(
        "Doña Ana (1954 geodetic): "
        f"lat={DONA_ANA['lat_deg']:.8f} lon={DONA_ANA['lon_deg_east']:.8f} "
        f"h={DONA_ANA['height_m']:.0f}m"
    )
    print(
        f"3-D station baseline over grid: "
        f"{baseline_norm.min():.3f}–{baseline_norm.max():.3f} km"
    )
    print()

    best_rows = []
    strict_geom_rows = []
    report_ranks = {}

    for rank in ACTIVE_RANKS:
        sr = sby[rank]
        uP = unit_from_radec(sr["poss_ra_deg"], sr["poss_dec_deg"])
        uDobs = unit_from_radec(sr["dasch_ra_deg"], sr["dasch_dec_deg"])
        raw_sep = angle_arcsec(uP, uDobs)

        bdot = baseline @ uP
        btrans = np.sqrt(np.maximum(0.0, baseline_norm**2 - bdot**2))

        approx_range_at_raw = btrans / math.radians(raw_sep/3600.0)
        range_for_3 = btrans / math.radians(STRICT_DIAGNOSTIC_ARCSEC/3600.0)
        range_for_10 = btrans / math.radians(BROAD_DIAGNOSTIC_ARCSEC/3600.0)

        # Existing strict counterpart exact ray-ray geometry across event time.
        line_results = []
        for ti in range(len(dts)):
            q = line_closest_approach(rP[ti], uP, rD[ti], uDobs)
            if q is None:
                continue
            sP, sD, gap = q
            line_results.append((gap, ti, sP, sD))
        line_results.sort(key=lambda q: q[0])
        best_line = line_results[0] if line_results else None

        strict_geom = {
            "strict_rank": rank,
            "raw_pair_separation_arcsec": raw_sep,
            "projected_baseline_min_km": float(btrans.min()),
            "projected_baseline_max_km": float(btrans.max()),
            "approx_range_for_raw_pair_sep_min_km": float(approx_range_at_raw.min()),
            "approx_range_for_raw_pair_sep_max_km": float(approx_range_at_raw.max()),
            "range_for_3arcsec_parallax_min_km": float(range_for_3.min()),
            "range_for_3arcsec_parallax_max_km": float(range_for_3.max()),
            "range_for_10arcsec_parallax_min_km": float(range_for_10.min()),
            "range_for_10arcsec_parallax_max_km": float(range_for_10.max()),
        }
        if best_line is not None:
            gap, ti, sP, sD = best_line
            strict_geom.update({
                "closest_ray_gap_km": gap,
                "closest_ray_time_utc": dts[ti].isoformat(),
                "closest_ray_palomar_range_km": sP,
                "closest_ray_dona_ana_range_km": sD,
                "closest_ray_both_forward": bool(sP > 0 and sD > 0),
            })
        strict_geom_rows.append(strict_geom)

        print(f"strict #{rank:02d}: existing counterpart sep={raw_sep:.3f}\"")
        print(
            f"  transverse baseline={btrans.min():.1f}–{btrans.max():.1f} km; "
            f"3\" parallax requires range >=~{range_for_3.min()/1e6:.1f}M km"
        )
        print(
            f"  scalar range matching {raw_sep:.3f}\" ~= "
            f"{approx_range_at_raw.min()/1e6:.1f}–"
            f"{approx_range_at_raw.max()/1e6:.1f}M km"
        )

        rank_bins = []

        for bin_name, lo, hi, n in RANGE_BINS_KM:
            ranges = make_range_grid(lo, hi, n)

            best = None
            parallax_min = float("inf")
            parallax_max = 0.0

            for ti, dt in enumerate(dts):
                # Object positions along the Palomar topocentric POSS sightline.
                # Shape: n_range x 3
                obj = rP[ti][None, :] + ranges[:, None]*uP[None, :]
                vecD = obj - rD[ti][None, :]
                vecD = vecD / np.linalg.norm(vecD, axis=1)[:, None]

                # Two-site parallax relative to the Palomar sightline.
                dots = np.clip(vecD @ uP, -1.0, 1.0)
                crosses = np.linalg.norm(np.cross(vecD, uP[None, :]), axis=1)
                par = np.degrees(np.arctan2(crosses, dots))*3600.0
                parallax_min = min(parallax_min, float(np.min(par)))
                parallax_max = max(parallax_max, float(np.max(par)))

                for ri, pred_u in enumerate(vecD):
                    ci, sep = nearest_candidate(tree, cand_vec, pred_u)
                    if best is None or sep < best["nearest_dasch_sep_arcsec"]:
                        cra, cdec = radec_from_unit(pred_u)
                        cr = dcand[ci]
                        best = {
                            "strict_rank": rank,
                            "range_bin": bin_name,
                            "event_time_utc": dt.isoformat(),
                            "palomar_range_km": float(ranges[ri]),
                            "predicted_dasch_ra_deg": cra,
                            "predicted_dasch_dec_deg": cdec,
                            "two_site_parallax_arcsec": float(par[ri]),
                            "nearest_dasch_sep_arcsec": float(sep),
                            "nearest_dasch_candidate_index": int(cr["candidate_index"]),
                            "nearest_dasch_tile_id": cr["tile_id"],
                            "nearest_dasch_ra_deg": float(cr["ra_deg"]),
                            "nearest_dasch_dec_deg": float(cr["dec_deg"]),
                            "nearest_dasch_snr": float(cr["snr"]),
                            "nearest_dasch_polarity": int(cr["polarity"]),
                            "within_10arcsec": bool(sep <= BROAD_DIAGNOSTIC_ARCSEC),
                            "within_3arcsec": bool(sep <= STRICT_DIAGNOSTIC_ARCSEC),
                            "is_existing_strict_counterpart": (
                                cr["tile_id"] == sr["dasch_tile_id"]
                                and int(cr["candidate_index"]) == int(sr["dasch_candidate_index"])
                            ),
                        }

            if best is None:
                raise RuntimeError(f"rank {rank} bin {bin_name}: no geometry result")

            best["bin_parallax_min_arcsec"] = parallax_min
            best["bin_parallax_max_arcsec"] = parallax_max
            best_rows.append(best)
            rank_bins.append(best)

            print(
                f"  {bin_name:19s}: parallax "
                f"{parallax_min/3600:.3f}–{parallax_max/3600:.3f} deg | "
                f"nearest frozen DASCH={best['nearest_dasch_sep_arcsec']:.2f}\" "
                f"at range={best['palomar_range_km']:.0f} km "
                f"time={best['event_time_utc'][11:19]}"
            )

        report_ranks[str(rank)] = {
            "existing_strict_counterpart": strict_geom,
            "range_bins": rank_bins,
            "near_earth_bins_with_any_frozen_dasch_within_10arcsec": [
                r["range_bin"] for r in rank_bins[:5] if r["within_10arcsec"]
            ],
            "near_earth_bins_with_any_frozen_dasch_within_3arcsec": [
                r["range_bin"] for r in rank_bins[:5] if r["within_3arcsec"]
            ],
        }
        print()

    best_fields = [
        "strict_rank", "range_bin", "event_time_utc", "palomar_range_km",
        "predicted_dasch_ra_deg", "predicted_dasch_dec_deg",
        "two_site_parallax_arcsec",
        "bin_parallax_min_arcsec", "bin_parallax_max_arcsec",
        "nearest_dasch_sep_arcsec",
        "nearest_dasch_candidate_index", "nearest_dasch_tile_id",
        "nearest_dasch_ra_deg", "nearest_dasch_dec_deg",
        "nearest_dasch_snr", "nearest_dasch_polarity",
        "within_10arcsec", "within_3arcsec",
        "is_existing_strict_counterpart",
    ]
    write_csv(OUT_BEST, best_rows, best_fields)

    strict_fields = [
        "strict_rank", "raw_pair_separation_arcsec",
        "projected_baseline_min_km", "projected_baseline_max_km",
        "approx_range_for_raw_pair_sep_min_km",
        "approx_range_for_raw_pair_sep_max_km",
        "range_for_3arcsec_parallax_min_km",
        "range_for_3arcsec_parallax_max_km",
        "range_for_10arcsec_parallax_min_km",
        "range_for_10arcsec_parallax_max_km",
        "closest_ray_gap_km", "closest_ray_time_utc",
        "closest_ray_palomar_range_km", "closest_ray_dona_ana_range_km",
        "closest_ray_both_forward",
    ]
    write_csv(OUT_STRICT, strict_geom_rows, strict_fields)

    out = {
        "status": "COMPLETE",
        "analysis_kind": "order61_branch_c_topocentric_parallax_locus_preflight_v028",
        "guards": guards,
        "site_geometry": {
            "palomar": PALOMAR,
            "dona_ana": DONA_ANA,
            "starglass_numeric_location_used_for_geometry": False,
            "starglass_role": "plate ai44092 -> named observing site identity only",
            "baseline_km_min": float(baseline_norm.min()),
            "baseline_km_max": float(baseline_norm.max()),
        },
        "fixed_grid": {
            "event_time_interval": [start.isoformat(), end.isoformat()],
            "event_time_step_seconds": TIME_STEP_SECONDS,
            "event_time_samples": len(dts),
            "range_bins_km": [
                {"name": n, "min_km": lo, "max_km": hi, "samples": nn}
                for n, lo, hi, nn in RANGE_BINS_KM
            ],
            "nearest_match_catalog": "all 4109 frozen native DASCH detections",
            "broad_diagnostic_arcsec": BROAD_DIAGNOSTIC_ARCSEC,
            "strict_diagnostic_arcsec": STRICT_DIAGNOSTIC_ARCSEC,
            "detector_rerun": False,
            "no_candidate_filter_by_polarity": True,
        },
        "historical_time_accuracy_note": (
            "Astropy historical Earth rotation is used with IERS auto-download disabled. "
            "EOP/UT1 uncertainty is not treated as sub-arcsecond precision evidence; "
            "it is negligible for the degree-scale near-Earth parallax exclusion and "
            "must be propagated before any arcsecond-level triangulation claim."
        ),
        "per_rank": report_ranks,
        "interpretation_contract": {
            "this_stage_can": [
                "test whether any frozen DASCH detection lies near the predicted simultaneous parallax locus",
                "show the scale of two-site parallax versus topocentric range",
                "show whether the existing strict counterpart could geometrically be an Earth-orbit simultaneous counterpart",
            ],
            "this_stage_cannot": [
                "prove a nearest DASCH locus hit is the same physical object",
                "use a DASCH non-detection to reject a directional specular reflection hypothesis",
                "promote a candidate without static/morphology/chance controls for any new locus hit",
            ],
        },
        "detector_rerun": False,
        "science_pixels_read": False,
        "candidate_deleted": False,
        "candidate_promoted": False,
        "outputs": {
            "nearest_matches_csv": str(OUT_BEST),
            "existing_strict_counterpart_geometry_csv": str(OUT_STRICT),
        },
    }
    write_json(OUT, out)

    print("=" * 110)
    print("BRANCH C PARALLAX LOCUS PREFLIGHT COMPLETE")
    print("=" * 110)
    print("Outputs:")
    print(" ", OUT)
    print(" ", OUT_BEST)
    print(" ", OUT_STRICT)
    print()
    print("No detector was rerun.")
    print("No science image pixel was read.")
    print("No candidate was deleted or promoted.")


if __name__ == "__main__":
    main()
