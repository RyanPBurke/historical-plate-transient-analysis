from __future__ import annotations

from pathlib import Path
import csv
import importlib.util
import json
import math
from datetime import datetime, timezone
import warnings

import numpy as np
import astropy.units as u
from astropy.coordinates import SkyCoord, EarthLocation, get_sun
from astropy.time import Time
from astropy.constants import R_sun

ROOT = Path.cwd()
BASE = ROOT / "results" / "order61_native_full_v028"
WORK = ROOT / "work" / "order61_branch_c_candidate462_v028"
WORK.mkdir(parents=True, exist_ok=True)

REFINE = BASE / "order61_branch_c_refined_controls_v028.json"
STRICT = BASE / "order61_strict_match_triage.csv"
DASCH_CAND = BASE / "order61_dasch_native_candidates.csv"
WHOLE = BASE / "order61_whole_pair_report.json"

GAIA_MODULE = ROOT / "tools" / "gaia_static_order61_v028c.py"
PS1_MODULE = ROOT / "tools" / "check_order61_ps1_static_v028b.py"
MORPH_MODULE = ROOT / "tools" / "vet_order61_survivor_morphology_v028.py"

OUT = BASE / "order61_branch_c_candidate462_validation_v028.json"
OUT_CONTROLS = BASE / "order61_branch_c_candidate462_morphology_controls_v028.csv"
OUT_GAIA = BASE / "order61_branch_c_candidate462_gaia_sources_v028.csv"
OUT_PS1 = BASE / "order61_branch_c_candidate462_ps1_sources_v028.csv"

PARENT_RANK = 20
TARGET_TILE = "D_x11264-12288_y07168-08192"
TARGET_INDEX = 462

# Reuse the exact discovery-plate matched-peer policy fixed before the
# original #11/#14/#20 morphology outcomes.
MIN_PREFERRED_CONTROLS = 12
MAX_CONTROLS = 32
EXCLUSION_RADIUS_PX = 32.0
PREFERRED_SNR_RATIO = (0.75, 1.25)
FALLBACK_SNR_RATIO = (0.50, 1.50)

GAIA_STRONG_ARCSEC = 3.0
GAIA_DIAGNOSTIC_ARCSEC = 5.0
PS1_STRONG_ARCSEC = 3.0
PS1_DIAGNOSTIC_ARCSEC = 5.0

EARTH_RADIUS_KM = 6378.137  # WGS84 equatorial, conservative spherical shadow model


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


def load_module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not import {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def ffloat(v):
    try:
        x = float(v)
    except Exception:
        return None
    return x if math.isfinite(x) else None


def fint(v):
    try:
        return int(str(v).strip())
    except Exception:
        try:
            return int(float(str(v).strip()))
        except Exception:
            return None


def midrank_percentile(value, values):
    vals = np.asarray(
        [float(x) for x in values if x is not None and math.isfinite(float(x))],
        float,
    )
    if value is None or not math.isfinite(float(value)) or len(vals) == 0:
        return None
    v = float(value)
    lt = int(np.sum(vals < v))
    eq = int(np.sum(vals == v))
    return 100.0 * (lt + 0.5*eq) / len(vals)


def plain_coord(ra, dec):
    return SkyCoord(float(ra)*u.deg, float(dec)*u.deg, frame="icrs")


def parse_time(s):
    q = str(s).strip()
    if q.endswith("Z"):
        q = q[:-1] + "+00:00"
    dt = datetime.fromisoformat(q)
    if dt.tzinfo is None:
        raise RuntimeError("timezone-naive refined event time")
    return Time(dt.astimezone(timezone.utc), scale="utc")


def gaia_check(g, coord, target_time):
    # Use the exact completed-v028c Gaia contracts: normal 120" cone plus
    # local high-PM rescue, propagated to the historical event epoch.
    cone, cone_meta, cone_status = g.tap_query(
        g.cone_adql(float(coord.ra.deg), float(coord.dec.deg)),
        "branchc_rank20_candidate462_cone120",
    )
    if len(cone) >= g.MAX_CONE_ROWS:
        raise RuntimeError("Gaia normal cone hit TOP limit")

    rescue, rescue_meta, rescue_status = g.tap_query(
        g.hpm_local_adql(float(coord.ra.deg), float(coord.dec.deg)),
        "branchc_rank20_candidate462_hpm900",
    )
    if len(rescue) >= g.MAX_HPM_RESCUE_ROWS:
        raise RuntimeError("Gaia HPM rescue hit TOP limit")

    merged = {}
    origins = {}
    for s in cone:
        merged[s["source_id"]] = s
        origins.setdefault(s["source_id"], set()).add("cone120")
    for s in rescue:
        merged.setdefault(s["source_id"], s)
        origins.setdefault(s["source_id"], set()).add("hpm900")

    rows = []
    for sid, src in merged.items():
        q = g.propagate_source(src, target_time)
        if q is None:
            continue
        c, did_prop, approx_sigma = q
        sep = float(c.separation(coord).arcsec)

        # Same audit logic: HPM-rescue-only objects need approach within 30".
        if "cone120" not in origins[sid] and sep > 30.0:
            continue

        rows.append({
            "source_id": sid,
            "origin": "+".join(sorted(origins[sid])),
            "ra_2016_deg": src["ra"],
            "dec_2016_deg": src["dec"],
            "ref_epoch": src["ref_epoch"],
            "pm_masyr": src["pm"],
            "pmra_masyr": src["pmra"],
            "pmdec_masyr": src["pmdec"],
            "parallax_mas": src["parallax"],
            "radial_velocity_kms": src["radial_velocity"],
            "g_mag": src["phot_g_mean_mag"],
            "ruwe": src["ruwe"],
            "propagated": did_prop,
            "ra_event_deg": float(c.icrs.ra.deg),
            "dec_event_deg": float(c.icrs.dec.deg),
            "sep_candidate_arcsec": sep,
            "approx_pm_propagation_sigma_arcsec": approx_sigma,
        })

    rows.sort(key=lambda r: r["sep_candidate_arcsec"])
    nearest = rows[0] if rows else None
    nearest_sep = None if nearest is None else float(nearest["sep_candidate_arcsec"])

    if nearest_sep is not None and nearest_sep <= GAIA_STRONG_ARCSEC:
        cls = "GAIA_STATIC_STRONG"
    elif nearest_sep is not None and nearest_sep <= GAIA_DIAGNOSTIC_ARCSEC:
        cls = "GAIA_STATIC_DIAGNOSTIC"
    else:
        cls = "NO_GAIA_WITHIN_5_ARCSEC_AT_EVENT_EPOCH"

    return {
        "classification": cls,
        "nearest": nearest,
        "normal_cone_rows": len(cone),
        "hpm_rescue_rows": len(rescue),
        "sources_examined": len(rows),
        "normal_query_status": cone_status,
        "hpm_query_status": rescue_status,
    }, rows


def ps1_check(p, coord):
    # Synthetic cache key 920 avoids collision with strict-rank caches.
    rows, meta, status = p.query_ps1(
        float(coord.ra.deg),
        float(coord.dec.deg),
        920,
    )

    audit = []
    for r in rows:
        ra = p.ffloat(r.get("raMean"))
        dec = p.ffloat(r.get("decMean"))
        nd = p.fint(r.get("nDetections"))
        if ra is None or dec is None or nd is None:
            continue
        c = plain_coord(ra, dec)
        audit.append({
            "objID": str(r.get("objID", "")).strip(),
            "raMean": ra,
            "decMean": dec,
            "sep_candidate_arcsec": float(c.separation(coord).arcsec),
            "nDetections": nd,
            "qualityFlag": p.fint(r.get("qualityFlag")),
            "epochMean": p.ffloat(r.get("epochMean")),
            "pmra": p.ffloat(r.get("pmra")),
            "pmdec": p.ffloat(r.get("pmdec")),
            "gMeanPSFMag": p.ffloat(r.get("gMeanPSFMag")),
            "rMeanPSFMag": p.ffloat(r.get("rMeanPSFMag")),
            "iMeanPSFMag": p.ffloat(r.get("iMeanPSFMag")),
            "zMeanPSFMag": p.ffloat(r.get("zMeanPSFMag")),
            "yMeanPSFMag": p.ffloat(r.get("yMeanPSFMag")),
        })
    audit.sort(key=lambda r: r["sep_candidate_arcsec"])
    nearest = audit[0] if audit else None
    ns = None if nearest is None else nearest["sep_candidate_arcsec"]

    if ns is not None and ns <= PS1_STRONG_ARCSEC:
        cls = "PS1_REPEATED_STATIC_STRONG"
    elif ns is not None and ns <= PS1_DIAGNOSTIC_ARCSEC:
        cls = "PS1_REPEATED_STATIC_DIAGNOSTIC"
    else:
        cls = "NO_PS1_REPEAT_WITHIN_5_ARCSEC"

    return {
        "classification": cls,
        "nearest": nearest,
        "returned_rows": len(rows),
        "query_status": status,
        "minimum_detections": p.MIN_DETECTIONS,
    }, audit


def morphology_check(m, all_rows, target_row):
    tile = target_row["tile_id"]
    target_snr = float(target_row["snr"])
    target_pol = int(target_row["polarity"])

    by_tile = m.build_tile_index(all_rows)
    row = m.match_candidate(
        all_rows,
        int(target_row["candidate_index"]),
        tile,
        target_snr,
        float(target_row["ra_deg"]),
        float(target_row["dec_deg"]),
    )

    gx, gy, source = m.resolve_global_xy(row, tile, m.DASCH_SHAPE_XY)
    arr, npy, (ex0, ex1, ey0, ey1) = m.load_tile(tile, m.DASCH_SHAPE_XY)
    sci = m.morphology(arr, gx-ex0, gy-ey0, target_pol)
    sci.pop("cutout", None)

    pool = []
    for r in by_tile[tile]:
        if m.row_pol(r) != target_pol:
            continue
        snr = m.row_snr(r)
        if snr is None or snr <= 0:
            continue
        try:
            px, py, _ = m.resolve_global_xy(r, tile, m.DASCH_SHAPE_XY)
        except Exception:
            continue
        dist = math.hypot(px-gx, py-gy)
        if dist < EXCLUSION_RADIUS_PX:
            continue
        ratio = float(snr)/target_snr
        pool.append({
            "row": r,
            "gx": px,
            "gy": py,
            "dist": dist,
            "snr": float(snr),
            "ratio": ratio,
            "candidate_index": fint(m.pick(r, ["candidate_index","index","candidate_id","peak_index"])),
        })

    preferred = [q for q in pool if PREFERRED_SNR_RATIO[0] <= q["ratio"] <= PREFERRED_SNR_RATIO[1]]
    fallback = [q for q in pool if FALLBACK_SNR_RATIO[0] <= q["ratio"] <= FALLBACK_SNR_RATIO[1]]

    if len(preferred) >= MIN_PREFERRED_CONTROLS:
        chosen = preferred
        mode = "same_tile_same_polarity_snr_ratio_0.75_1.25"
        chosen.sort(key=lambda q:(q["dist"],abs(math.log(q["ratio"])),q["snr"]))
    elif len(fallback) >= MIN_PREFERRED_CONTROLS:
        chosen = fallback
        mode = "same_tile_same_polarity_snr_ratio_0.50_1.50_fallback"
        chosen.sort(key=lambda q:(q["dist"],abs(math.log(q["ratio"])),q["snr"]))
    else:
        chosen = pool
        mode = "same_tile_same_polarity_nearest_snr_fallback"
        chosen.sort(key=lambda q:(abs(math.log(q["ratio"])),q["dist"],q["snr"]))

    controls = []
    for q in chosen[:MAX_CONTROLS]:
        try:
            met = m.morphology(arr, q["gx"]-ex0, q["gy"]-ey0, target_pol)
            met.pop("cutout", None)
        except Exception:
            continue
        controls.append({
            "candidate_index": q["candidate_index"],
            "global_x": q["gx"],
            "global_y": q["gy"],
            "distance_from_science_px": q["dist"],
            "snr": q["snr"],
            "snr_ratio": q["ratio"],
            **met,
        })

    if len(controls) < 5:
        raise RuntimeError(f"Only {len(controls)} usable morphology controls")

    metric_names = [
        "sigma_major_px","sigma_minor_px","ellipticity","peak_to_flux5",
        "concentration_flux3_flux8","centroid_offset_px",
        "plateau_count_3x3","local_extreme_count_3x3",
    ]
    pcts = {
        k: midrank_percentile(sci[k], [c[k] for c in controls])
        for k in metric_names
    }

    continuous = [
        "sigma_major_px","sigma_minor_px","ellipticity","peak_to_flux5",
        "concentration_flux3_flux8","centroid_offset_px",
    ]
    extremes = [
        {"metric":k,"percentile":pcts[k]}
        for k in continuous
        if pcts[k] is not None and (pcts[k] <= 5.0 or pcts[k] >= 95.0)
    ]
    count_high = [
        {"metric":k,"percentile":pcts[k]}
        for k in ["plateau_count_3x3","local_extreme_count_3x3"]
        if pcts[k] is not None and pcts[k] >= 95.0
    ]

    return {
        "tile_id": tile,
        "candidate_index": int(target_row["candidate_index"]),
        "snr": target_snr,
        "polarity": target_pol,
        "global_x": gx,
        "global_y": gy,
        "coord_source": source,
        "npy_path": str(npy),
        "selection_mode": mode,
        "control_count": len(controls),
        "metrics": sci,
        "percentiles": pcts,
        "continuous_extremes_5_95": extremes,
        "count_high_ge95": count_high,
    }, controls


def shadow_check(event_time, pal_site, poss_coord, range_km):
    pal = EarthLocation.from_geodetic(
        float(pal_site["lon_deg_east"])*u.deg,
        float(pal_site["lat_deg"])*u.deg,
        float(pal_site["height_m"])*u.m,
    )

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        obs = pal.get_gcrs(event_time)
        sun = get_sun(event_time)

    r_obs = np.array([
        obs.cartesian.x.to_value(u.km),
        obs.cartesian.y.to_value(u.km),
        obs.cartesian.z.to_value(u.km),
    ], float)

    u_los = np.array([
        math.cos(poss_coord.dec.radian)*math.cos(poss_coord.ra.radian),
        math.cos(poss_coord.dec.radian)*math.sin(poss_coord.ra.radian),
        math.sin(poss_coord.dec.radian),
    ], float)

    r_obj = r_obs + float(range_km)*u_los
    r_sun = np.array([
        sun.cartesian.x.to_value(u.km),
        sun.cartesian.y.to_value(u.km),
        sun.cartesian.z.to_value(u.km),
    ], float)

    to_earth = -r_obj
    to_sun = r_sun-r_obj

    de = float(np.linalg.norm(to_earth))
    ds = float(np.linalg.norm(to_sun))

    ue = to_earth/de
    us = to_sun/ds
    sep = math.acos(max(-1.0,min(1.0,float(np.dot(ue,us)))))

    earth_ang = math.asin(min(1.0, EARTH_RADIUS_KM/de))
    sun_radius_km = R_sun.to_value(u.km)
    sun_ang = math.asin(min(1.0, sun_radius_km/ds))

    if earth_ang > sun_ang and sep < earth_ang-sun_ang:
        state = "EARTH_UMBRA"
    elif sep < earth_ang+sun_ang:
        state = "EARTH_PENUMBRA_OR_PARTIAL_OCCULTATION"
    else:
        state = "FULLY_SUNLIT_BY_SPHERICAL_EARTH_MODEL"

    return {
        "state": state,
        "geocentric_distance_km": de,
        "approx_altitude_above_equatorial_earth_km": de-EARTH_RADIUS_KM,
        "earth_sun_center_separation_seen_from_object_deg": math.degrees(sep),
        "earth_angular_radius_seen_from_object_deg": math.degrees(earth_ang),
        "sun_angular_radius_seen_from_object_deg": math.degrees(sun_ang),
        "model": "spherical opaque Earth, finite solar angular radius; no atmosphere/refraction",
    }


def main():
    print("="*108)
    print("ORDER 61 — BRANCH C #20 / DASCH CANDIDATE 462 VALIDATION v028")
    print("="*108)
    print("Gaia + PS1 static rejection, exact SNR-matched DASCH morphology, and Earth-shadow state.")
    print("No detector rerun. Original POSS #20 completed static/morphology evidence is not repeated.")
    print()

    for p in (REFINE,STRICT,DASCH_CAND,WHOLE,GAIA_MODULE,PS1_MODULE,MORPH_MODULE):
        if not p.is_file():
            raise RuntimeError(f"Missing required input: {p}")

    refine = json.loads(REFINE.read_text(encoding="utf-8"))
    whole = json.loads(WHOLE.read_text(encoding="utf-8"))

    controls20 = refine["per_rank_control_summary"]["20"]
    hits20 = [
        r for r in refine["refined_unique_hits"]
        if int(r["strict_rank"]) == PARENT_RANK
    ]

    if len(hits20) != 1:
        raise RuntimeError(f"REFUSING: expected one refined #20 hit, got {len(hits20)}")

    hit = hits20[0]
    guards = {
        "refine_complete": refine.get("status") == "COMPLETE",
        "refine_no_detector": refine.get("detector_rerun") is False,
        "refine_no_pixels": refine.get("science_image_pixels_read") is False,
        "rank20_empirical_p_fixed_96": abs(
            float(controls20["finite_sample_empirical_p"]) - 5.0/97.0
        ) < 1e-12,
        "rank20_unique_hit_count": len(hits20) == 1,
        "target_tile": hit["dasch_tile_id"] == TARGET_TILE,
        "target_index": int(hit["dasch_candidate_index"]) == TARGET_INDEX,
        "target_not_existing_branchA_counterpart": hit["is_existing_strict_counterpart"] is False,
        "target_range_valid": hit["refined_range_within_0p5_to_500k"] is True,
        "whole_complete": whole.get("status") == "COMPLETE",
    }
    if not all(guards.values()):
        raise RuntimeError("REFUSING: completed-stage guard failure: "+repr(guards))

    strict = {int(r["strict_rank"]):r for r in read_csv(STRICT)}
    if PARENT_RANK not in strict:
        raise RuntimeError("Missing original strict #20 row")
    sr = strict[PARENT_RANK]

    dcand = read_csv(DASCH_CAND)
    target_rows = [
        r for r in dcand
        if r["tile_id"] == TARGET_TILE
        and int(r["candidate_index"]) == TARGET_INDEX
    ]
    if len(target_rows) != 1:
        raise RuntimeError(f"Expected exactly one candidate 462 row; got {len(target_rows)}")
    target_row = target_rows[0]

    # Cross-check refined report against frozen candidate row.
    if abs(float(target_row["ra_deg"])-float(hit["dasch_ra_deg"])) > 1e-10:
        raise RuntimeError("candidate 462 RA mismatch")
    if abs(float(target_row["dec_deg"])-float(hit["dasch_dec_deg"])) > 1e-10:
        raise RuntimeError("candidate 462 Dec mismatch")

    event_time = parse_time(hit["refined_best_time_utc"])
    target_coord = plain_coord(target_row["ra_deg"], target_row["dec_deg"])
    poss20_coord = plain_coord(sr["poss_ra_deg"], sr["poss_dec_deg"])

    print("Completed-stage guards: PASS")
    print(
        f"Target DASCH candidate: {TARGET_TILE}#{TARGET_INDEX} "
        f"RA={float(target_row['ra_deg']):.9f} Dec={float(target_row['dec_deg']):+.9f} "
        f"SNR={float(target_row['snr']):.3f} polarity={int(target_row['polarity']):+d}"
    )
    print(
        f"Refined geometry context: time={event_time.utc.isot} "
        f"Palomar range={float(hit['refined_palomar_range_km']):.1f} km; "
        f"shifted-locus empirical p={float(controls20['finite_sample_empirical_p']):.4f}"
    )
    print()

    g = load_module(GAIA_MODULE, "gaia_static_v028c")
    p = load_module(PS1_MODULE, "ps1_static_v028b")
    m = load_module(MORPH_MODULE, "morph_v028")

    print("[1/4] Gaia DR3 static-source check ...", flush=True)
    gaia, gaia_rows = gaia_check(g, target_coord, event_time)
    print("  ", gaia["classification"])
    if gaia["nearest"] is None:
        print("   nearest: none")
    else:
        print(
            f"   nearest={gaia['nearest']['sep_candidate_arcsec']:.3f}\" "
            f"source={gaia['nearest']['source_id']} "
            f"G={gaia['nearest']['g_mag']} propagated={gaia['nearest']['propagated']}"
        )

    gaia_fields = [
        "source_id","origin","ra_2016_deg","dec_2016_deg","ref_epoch",
        "pm_masyr","pmra_masyr","pmdec_masyr","parallax_mas",
        "radial_velocity_kms","g_mag","ruwe","propagated",
        "ra_event_deg","dec_event_deg","sep_candidate_arcsec",
        "approx_pm_propagation_sigma_arcsec",
    ]
    write_csv(OUT_GAIA, gaia_rows, gaia_fields)

    print()
    print("[2/4] Pan-STARRS DR2 repeated-static check ...", flush=True)
    ps1, ps1_rows = ps1_check(p, target_coord)
    print("  ", ps1["classification"])
    if ps1["nearest"] is None:
        print("   nearest: none")
    else:
        print(
            f"   nearest={ps1['nearest']['sep_candidate_arcsec']:.3f}\" "
            f"objID={ps1['nearest']['objID']} nDetections={ps1['nearest']['nDetections']}"
        )

    ps1_fields = [
        "objID","raMean","decMean","sep_candidate_arcsec","nDetections",
        "qualityFlag","epochMean","pmra","pmdec",
        "gMeanPSFMag","rMeanPSFMag","iMeanPSFMag","zMeanPSFMag","yMeanPSFMag",
    ]
    write_csv(OUT_PS1, ps1_rows, ps1_fields)

    print()
    print("[3/4] Native DASCH SNR-matched morphology ...", flush=True)
    morph, morph_controls = morphology_check(m, dcand, target_row)
    print(
        f"   controls={morph['control_count']} mode={morph['selection_mode']}"
    )
    pc = morph["percentiles"]
    print(
        f"   pct: major={pc['sigma_major_px']:.1f} minor={pc['sigma_minor_px']:.1f} "
        f"ell={pc['ellipticity']:.1f} sharp={pc['peak_to_flux5']:.1f} "
        f"conc={pc['concentration_flux3_flux8']:.1f} cent={pc['centroid_offset_px']:.1f}"
    )
    ext = morph["continuous_extremes_5_95"]
    print("   continuous 5/95 extremes:", ext if ext else "none")
    print("   count metrics >=95th:", morph["count_high_ge95"] if morph["count_high_ge95"] else "none")

    morph_fields = [
        "candidate_index","global_x","global_y","distance_from_science_px",
        "snr","snr_ratio","local_bg","local_sigma","peak_bgsub_polarity",
        "sigma_major_px","sigma_minor_px","ellipticity","peak_to_flux5",
        "concentration_flux3_flux8","centroid_offset_px",
        "plateau_count_3x3","local_extreme_count_3x3",
    ]
    write_csv(OUT_CONTROLS, morph_controls, morph_fields)

    print()
    print("[4/4] Earth-shadow / solar-illumination geometry ...", flush=True)
    pal = json.loads((BASE/"order61_branch_c_parallax_preflight_v028.json").read_text(encoding="utf-8"))["site_geometry"]["palomar"]
    shadow = shadow_check(
        event_time,
        pal,
        poss20_coord,
        float(hit["refined_palomar_range_km"]),
    )
    print(
        f"   {shadow['state']} | geocentric distance={shadow['geocentric_distance_km']:.1f} km "
        f"altitude~{shadow['approx_altitude_above_equatorial_earth_km']:.1f} km"
    )
    print(
        f"   Earth/Sun apparent-center separation={shadow['earth_sun_center_separation_seen_from_object_deg']:.3f} deg; "
        f"Earth radius={shadow['earth_angular_radius_seen_from_object_deg']:.3f} deg; "
        f"Sun radius={shadow['sun_angular_radius_seen_from_object_deg']:.3f} deg"
    )

    static_survives = (
        gaia["classification"] == "NO_GAIA_WITHIN_5_ARCSEC_AT_EVENT_EPOCH"
        and ps1["classification"] == "NO_PS1_REPEAT_WITHIN_5_ARCSEC"
    )
    morph_concern = bool(
        morph["continuous_extremes_5_95"]
        or morph["count_high_ge95"]
    )

    if not static_survives:
        disposition = "BRANCH_C_20_NEW_COUNTERPART_STATIC_CONTAMINATION_CONCERN"
    elif morph_concern:
        disposition = "BRANCH_C_20_NEW_COUNTERPART_SURVIVES_STATIC_WITH_MORPHOLOGY_CAVEAT"
    else:
        disposition = "BRANCH_C_20_NEW_COUNTERPART_SURVIVES_STATIC_AND_MATCHED_PEER_MORPHOLOGY"

    report = {
        "status":"COMPLETE",
        "analysis_kind":"order61_branch_c_rank20_candidate462_validation_v028",
        "guards":guards,
        "parent_branch_c_control_context":{
            "parent_rank":PARENT_RANK,
            "observed_coarse_best_arcsec":float(controls20["observed_coarse_best_near_earth_sep_arcsec"]),
            "shifted_controls":int(controls20["control_count"]),
            "controls_at_least_as_close":int(controls20["controls_at_least_as_close_as_observed"]),
            "finite_sample_empirical_p":float(controls20["finite_sample_empirical_p"]),
            "interpretation":"borderline exploratory local shifted-locus result; not formal astrophysical significance",
        },
        "new_dasch_counterpart":{
            "tile_id":TARGET_TILE,
            "candidate_index":TARGET_INDEX,
            "ra_deg":float(target_row["ra_deg"]),
            "dec_deg":float(target_row["dec_deg"]),
            "snr":float(target_row["snr"]),
            "polarity":int(target_row["polarity"]),
        },
        "refined_geometry":hit,
        "gaia":gaia,
        "ps1":ps1,
        "morphology":morph,
        "illumination":shadow,
        "disposition":disposition,
        "detector_rerun":False,
        "original_poss20_pixels_reread":False,
        "new_dasch_candidate_pixels_read_for_morphology":True,
        "candidate_deleted":False,
        "candidate_promoted":False,
        "next_stage":(
            "If candidate 462 survives Gaia/PS1 and does not show a strong defect-like morphology, "
            "run an independent control family for the Branch-C geometry and an independent-plate "
            "recurrence/static test at the candidate-462 sky locus before interpreting illumination "
            "or orbital plausibility. If static contamination is found, retire this Branch-C hit."
        ),
        "outputs":{
            "gaia_sources_csv":str(OUT_GAIA),
            "ps1_sources_csv":str(OUT_PS1),
            "morphology_controls_csv":str(OUT_CONTROLS),
        },
    }
    write_json(OUT,report)

    print()
    print("="*108)
    print("BRANCH C #20 / CANDIDATE 462 VALIDATION COMPLETE")
    print("="*108)
    print("Disposition:", disposition)
    print("Output:",OUT)
    print("Gaia:",OUT_GAIA)
    print("PS1: ",OUT_PS1)
    print("Morph controls:",OUT_CONTROLS)
    print()
    print("No detector was rerun.")
    print("No candidate was deleted or promoted.")


if __name__=="__main__":
    main()
