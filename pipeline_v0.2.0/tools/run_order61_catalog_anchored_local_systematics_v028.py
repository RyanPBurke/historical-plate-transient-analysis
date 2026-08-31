from __future__ import annotations

from pathlib import Path
import csv
import importlib.util
import json
import math

import numpy as np
import astropy.units as u
from astropy.coordinates import SkyCoord

ROOT = Path.cwd()
BASE = ROOT / "results" / "order61_native_full_v028"

PLATEPHOT_MODULE = ROOT / "tools" / "preflight_order61_platephot_recurrence_v028b.py"
PAIR_REPORT = BASE / "order61_whole_pair_report.json"
STRICT = BASE / "order61_strict_match_triage.csv"
PIXEL_REFS = BASE / "order61_pixel_gaia_astrometry_references_v028.csv"
KNOWN_CONTROL = BASE / "order61_pixel_astrometry_known_gaia_controls_v028.json"
PRIOR_PP_PREFLIGHT = BASE / "order61_platephot_gaia_astrometry_preflight_v028.json"

OUT_DASCH = BASE / "order61_grid_platephot_astrometric_references_v028.csv"
OUT_SUMMARY = BASE / "order61_catalog_anchored_local_systematics_summary_v028.csv"
OUT_REPORT = BASE / "order61_catalog_anchored_local_systematics_report_v028.json"

ACTIVE_RANKS = [11, 14, 20]
PAIR_PLATE = "ai44092"

# Prospectively fixed after the 8' official-source preflight proved insufficient.
GRID_OFFSETS_ARCMIN = [-12.0, 0.0, 12.0]
LOCAL_RADIUS_ARCMIN = 20.0
MIN_REFS_PER_ARCHIVE = 5

DASCH_FIELDS = [
    "strict_rank", "grid_east_arcmin", "grid_north_arcmin",
    "solution_number", "refcat",
    "image_x", "image_y",
    "measured_ra_deg", "measured_dec_deg",
    "catalog_ra_deg", "catalog_dec_deg",
    "ref_number", "fwhm_world_arcsec", "aflags", "bflags",
    "sep_survivor_mid_arcmin",
    "east_residual_arcsec", "north_residual_arcsec",
    "residual_radius_arcsec",
    "dedupe_kept",
]

SUMMARY_FIELDS = [
    "strict_rank", "status",
    "poss_reference_count", "dasch_reference_count",
    "poss_median_east_arcsec", "poss_median_north_arcsec",
    "dasch_median_east_arcsec", "dasch_median_north_arcsec",
    "poss_robust_sigma_east_arcsec", "poss_robust_sigma_north_arcsec",
    "dasch_robust_sigma_east_arcsec", "dasch_robust_sigma_north_arcsec",
    "expected_cross_east_arcsec", "expected_cross_north_arcsec",
    "candidate_raw_east_arcsec", "candidate_raw_north_arcsec",
    "candidate_raw_separation_arcsec",
    "candidate_corrected_east_arcsec", "candidate_corrected_north_arcsec",
    "candidate_corrected_separation_arcsec",
]


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
        raise RuntimeError(f"could not import {path}")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def ffloat(v):
    try:
        x = float(v)
    except Exception:
        return None
    return x if math.isfinite(x) else None


def truth(v):
    return str(v).strip().lower() in {"true", "1", "yes", "y", "t"}


def robust_sigma(vals):
    a = np.asarray([float(v) for v in vals], dtype=float)
    if len(a) == 0:
        return None
    med = float(np.median(a))
    mad = float(np.median(np.abs(a - med)))
    return 1.4826 * mad


def sky_offset(origin, measured):
    # Explicit plain ICRS objects: positional comparison only.
    a = SkyCoord(
        ra=float(origin.icrs.ra.deg) * u.deg,
        dec=float(origin.icrs.dec.deg) * u.deg,
        frame="icrs",
    )
    b = SkyCoord(
        ra=float(measured.icrs.ra.deg) * u.deg,
        dec=float(measured.icrs.dec.deg) * u.deg,
        frame="icrs",
    )
    e, n = a.spherical_offsets_to(b)
    return float(e.arcsec), float(n.arcsec)


def midpoint(p, d):
    v = p.cartesian.xyz.value + d.cartesian.xyz.value
    v = v / np.linalg.norm(v)
    ra = math.atan2(float(v[1]), float(v[0])) % (2 * math.pi)
    dec = math.atan2(float(v[2]), math.hypot(float(v[0]), float(v[1])))
    return SkyCoord(ra=ra*u.rad, dec=dec*u.rad, frame="icrs")


def grid_center(mid, east_arcmin, north_arcmin):
    # Exact spherical tangent offset for the fixed local grid.
    return mid.spherical_offsets_by(
        east_arcmin * u.arcmin,
        north_arcmin * u.arcmin,
    ).icrs


def source_dedupe_key(s):
    ix = ffloat(s.get("image_x"))
    iy = ffloat(s.get("image_y"))
    if ix is not None and iy is not None:
        # Same photographic extraction returned via APASS/ATLAS should have
        # identical/near-identical detector coordinates.
        return ("xy", int(s["solution_number"]), round(ix, 3), round(iy, 3))
    return (
        "sky", int(s["solution_number"]),
        round(float(s["ra_deg"]), 8),
        round(float(s["dec_deg"]), 8),
    )


def main():
    print("=" * 108)
    print("ORDER 61 — CATALOG-ANCHORED LOCAL ASTROMETRIC SYSTEMATICS v028")
    print("=" * 108)
    print(
        "DASCH: official ai44092 platephot measured-vs-reference-catalogue residuals. "
        "POSS: reuse previously fixed successful Gaia-star measurements."
    )
    print("No detector rerun. No candidate pixel is used in either calibration population.")
    print()

    for p in (
        PLATEPHOT_MODULE, PAIR_REPORT, STRICT, PIXEL_REFS,
        KNOWN_CONTROL, PRIOR_PP_PREFLIGHT,
    ):
        if not p.is_file():
            raise RuntimeError(f"Missing required input: {p}")

    pp = load_module(PLATEPHOT_MODULE, "order61_pp_v028b")

    pair = json.loads(PAIR_REPORT.read_text(encoding="utf-8"))
    known = json.loads(KNOWN_CONTROL.read_text(encoding="utf-8"))
    prior = json.loads(PRIOR_PP_PREFLIGHT.read_text(encoding="utf-8"))

    guards = {
        "pair_complete": pair.get("status") == "COMPLETE",
        "order61": int(pair.get("canonical_order", -1)) == 61,
        "known_control_complete": known.get("status") == "COMPLETE",
        "known_control_count": int(known.get("known_control_count", -1)) == 5,
        "prior_platephot_preflight_complete": prior.get("status") == "COMPLETE",
        "prior_platephot_preflight_all_insufficient": not bool(
            prior.get("all_ranks_meet_future_fit_minimum")
        ),
    }
    if not all(guards.values()):
        raise RuntimeError(
            "REFUSING: completed-stage guard failure: "
            + json.dumps(guards, sort_keys=True)
        )

    strict = {int(r["strict_rank"]): r for r in read_csv(STRICT)}
    pixel_rows = read_csv(PIXEL_REFS)

    for rank in ACTIVE_RANKS:
        if rank not in strict:
            raise RuntimeError(f"missing strict rank {rank}")

    print("Completed-stage guards: PASS")
    print(
        "Fixed post-preflight policy: 3x3 platephot grid at east/north offsets "
        "{-12',0,+12'}, retain matched DASCH references within 20', "
        "minimum 5 references on DASCH and 5 on the already-fixed POSS Gaia set."
    )
    print("Primary model: median translation only; no affine/polynomial terms.")
    print()

    all_dasch_audit = []
    summaries = []
    report_ranks = {}

    for rank in ACTIVE_RANKS:
        sr = strict[rank]
        p = SkyCoord(
            float(sr["poss_ra_deg"]) * u.deg,
            float(sr["poss_dec_deg"]) * u.deg,
            frame="icrs",
        )
        d = SkyCoord(
            float(sr["dasch_ra_deg"]) * u.deg,
            float(sr["dasch_dec_deg"]) * u.deg,
            frame="icrs",
        )
        mid = midpoint(p, d)

        # Discover the exact ai44092 imaging solution and advertised refcats.
        exp_raw, exp_header, exp_status = pp.queryexps(
            rank, float(mid.ra.deg), float(mid.dec.deg)
        )
        exps = [
            pp.parse_exposure(rank, float(mid.ra.deg), float(mid.dec.deg), r)
            for r in exp_raw
        ]
        pair_exps = [
            e for e in exps
            if e["is_pair_plate_ai44092"] and e["has_imaging"]
        ]
        if not pair_exps:
            raise RuntimeError(f"rank {rank}: no ai44092 imaging solution")

        call_specs = []
        seen_spec = set()
        for e in pair_exps:
            refcats = []
            if int(e["nSolutionsApass"]) > 0 or str(e["resultIdApass"]).strip():
                refcats.append("apass")
            if int(e["nSolutionsAtlas"]) > 0 or str(e["resultIdAtlas"]).strip():
                refcats.append("atlas")
            for refcat in refcats:
                spec = (int(e["solnum"]), refcat)
                if spec not in seen_spec:
                    seen_spec.add(spec)
                    call_specs.append(spec)

        if not call_specs:
            raise RuntimeError(f"rank {rank}: no advertised ai44092 platephot refcat")

        raw_sources = []
        call_count = 0

        for east in GRID_OFFSETS_ARCMIN:
            for north in GRID_OFFSETS_ARCMIN:
                gc = grid_center(mid, east, north)

                for solnum, refcat in call_specs:
                    payload = {
                        "plate_id": PAIR_PLATE,
                        "solution_number": int(solnum),
                        "refcat": refcat,
                        "center_ra_deg": float(gc.ra.deg),
                        "center_dec_deg": float(gc.dec.deg),
                    }

                    # Unique cache stem includes grid coordinates; unlike the older
                    # single-center helper, these calls cannot alias one another.
                    stem = (
                        f"catalog_astrometry_rank{rank:02d}_"
                        f"e{east:+05.1f}_n{north:+05.1f}_"
                        f"s{solnum}_{refcat}"
                    ).replace("+", "p").replace("-", "m").replace(".", "d")

                    obj, meta, status = pp.curl_post_json(
                        pp.PLATEPHOT, payload, stem
                    )
                    rows, header = pp.parse_json_csv_lines(
                        obj, f"rank {rank} grid {east},{north} {refcat}"
                    )
                    call_count += 1

                    for rr in rows:
                        s = pp.parse_platephot_source(
                            rank, PAIR_PLATE, solnum, refcat, rr,
                            float(sr["dasch_ra_deg"]),
                            float(sr["dasch_dec_deg"]),
                            float(mid.ra.deg),
                            float(mid.dec.deg),
                        )
                        if s is None:
                            continue
                        if float(s["sep_pair_midpoint_arcsec"]) > LOCAL_RADIUS_ARCMIN * 60:
                            continue
                        if not bool(s["is_catalog_matched"]):
                            continue
                        if s["catalog_ra_deg"] is None or s["catalog_dec_deg"] is None:
                            continue

                        cat = SkyCoord(
                            float(s["catalog_ra_deg"]) * u.deg,
                            float(s["catalog_dec_deg"]) * u.deg,
                            frame="icrs",
                        )
                        meas = SkyCoord(
                            float(s["ra_deg"]) * u.deg,
                            float(s["dec_deg"]) * u.deg,
                            frame="icrs",
                        )
                        re, rn = sky_offset(cat, meas)

                        raw_sources.append({
                            **s,
                            "grid_east_arcmin": east,
                            "grid_north_arcmin": north,
                            "east_residual_arcsec": re,
                            "north_residual_arcsec": rn,
                            "residual_radius_arcsec": math.hypot(re, rn),
                        })

        # Dedupe identical photographic extractions returned by overlapping
        # grid calls/refcats. Prefer APASS if the same extraction appears twice.
        raw_sources.sort(key=lambda s: (
            0 if s["refcat"] == "apass" else 1,
            float(s["residual_radius_arcsec"]),
        ))
        kept_map = {}
        audit = []
        for s in raw_sources:
            key = source_dedupe_key(s)
            keep = key not in kept_map
            if keep:
                kept_map[key] = s
            audit.append({
                "strict_rank": rank,
                "grid_east_arcmin": s["grid_east_arcmin"],
                "grid_north_arcmin": s["grid_north_arcmin"],
                "solution_number": s["solution_number"],
                "refcat": s["refcat"],
                "image_x": s["image_x"],
                "image_y": s["image_y"],
                "measured_ra_deg": s["ra_deg"],
                "measured_dec_deg": s["dec_deg"],
                "catalog_ra_deg": s["catalog_ra_deg"],
                "catalog_dec_deg": s["catalog_dec_deg"],
                "ref_number": s["ref_number"],
                "fwhm_world_arcsec": s["fwhm_world_arcsec"],
                "aflags": s["aflags"],
                "bflags": s["bflags"],
                "sep_survivor_mid_arcmin": float(s["sep_pair_midpoint_arcsec"]) / 60.0,
                "east_residual_arcsec": s["east_residual_arcsec"],
                "north_residual_arcsec": s["north_residual_arcsec"],
                "residual_radius_arcsec": s["residual_radius_arcsec"],
                "dedupe_kept": keep,
            })

        dasch_refs = list(kept_map.values())
        all_dasch_audit.extend(audit)

        # Reuse only the successful POSS measurements from the previously fixed
        # ordinary-Gaia-star run. No new star selection and no new POSS threshold.
        poss_refs = []
        for r in pixel_rows:
            if int(r["strict_rank"]) != rank:
                continue
            if str(r.get("poss_status")) != "SUCCESS":
                continue
            sep_mid = ffloat(r.get("sep_from_survivor_mid_arcmin"))
            pe = ffloat(r.get("poss_east_residual_arcsec"))
            pn = ffloat(r.get("poss_north_residual_arcsec"))
            if sep_mid is None or sep_mid > LOCAL_RADIUS_ARCMIN:
                continue
            if pe is None or pn is None:
                continue
            poss_refs.append((pe, pn))

        raw_e = float(sr["east_offset_arcsec"])
        raw_n = float(sr["north_offset_arcsec"])
        raw_r = float(sr["separation_arcsec"])

        if (
            len(poss_refs) < MIN_REFS_PER_ARCHIVE
            or len(dasch_refs) < MIN_REFS_PER_ARCHIVE
        ):
            row = {
                "strict_rank": rank,
                "status": "INSUFFICIENT_CATALOG_ANCHORED_REFERENCES",
                "poss_reference_count": len(poss_refs),
                "dasch_reference_count": len(dasch_refs),
                "candidate_raw_east_arcsec": raw_e,
                "candidate_raw_north_arcsec": raw_n,
                "candidate_raw_separation_arcsec": raw_r,
            }
        else:
            p_e = [x[0] for x in poss_refs]
            p_n = [x[1] for x in poss_refs]
            d_e = [float(x["east_residual_arcsec"]) for x in dasch_refs]
            d_n = [float(x["north_residual_arcsec"]) for x in dasch_refs]

            pme, pmn = float(np.median(p_e)), float(np.median(p_n))
            dme, dmn = float(np.median(d_e)), float(np.median(d_n))

            # Measured cross-archive offset expected from local astrometric
            # systematics: DASCH_error - POSS_error.
            exp_e = dme - pme
            exp_n = dmn - pmn

            corr_e = raw_e - exp_e
            corr_n = raw_n - exp_n
            corr_r = math.hypot(corr_e, corr_n)

            row = {
                "strict_rank": rank,
                "status": "CATALOG_ANCHORED_TRANSLATION_COMPLETE",
                "poss_reference_count": len(poss_refs),
                "dasch_reference_count": len(dasch_refs),
                "poss_median_east_arcsec": pme,
                "poss_median_north_arcsec": pmn,
                "dasch_median_east_arcsec": dme,
                "dasch_median_north_arcsec": dmn,
                "poss_robust_sigma_east_arcsec": robust_sigma(p_e),
                "poss_robust_sigma_north_arcsec": robust_sigma(p_n),
                "dasch_robust_sigma_east_arcsec": robust_sigma(d_e),
                "dasch_robust_sigma_north_arcsec": robust_sigma(d_n),
                "expected_cross_east_arcsec": exp_e,
                "expected_cross_north_arcsec": exp_n,
                "candidate_raw_east_arcsec": raw_e,
                "candidate_raw_north_arcsec": raw_n,
                "candidate_raw_separation_arcsec": raw_r,
                "candidate_corrected_east_arcsec": corr_e,
                "candidate_corrected_north_arcsec": corr_n,
                "candidate_corrected_separation_arcsec": corr_r,
            }

        summaries.append(row)
        report_ranks[str(rank)] = {
            **row,
            "platephot_grid_calls": call_count,
            "raw_matched_platephot_rows": len(raw_sources),
            "deduplicated_dasch_references": len(dasch_refs),
            "poss_references_reused_from_prior_fixed_run": len(poss_refs),
        }

        print(
            f"strict #{rank:02d}: grid calls={call_count} "
            f"DASCH matched raw/unique={len(raw_sources)}/{len(dasch_refs)} "
            f"POSS refs={len(poss_refs)} => {row['status']}"
        )
        if row["status"] == "CATALOG_ANCHORED_TRANSLATION_COMPLETE":
            print(
                f"  expected local cross offset east={row['expected_cross_east_arcsec']:+.3f}\" "
                f"north={row['expected_cross_north_arcsec']:+.3f}\""
            )
            print(
                f"  candidate raw={raw_r:.3f}\" -> "
                f"catalog-anchored corrected={row['candidate_corrected_separation_arcsec']:.3f}\""
            )

    write_csv(OUT_DASCH, all_dasch_audit, DASCH_FIELDS)
    write_csv(OUT_SUMMARY, summaries, SUMMARY_FIELDS)

    report = {
        "status": "COMPLETE",
        "analysis_kind": "order61_catalog_anchored_local_astrometric_systematics_v028",
        "guards": guards,
        "fixed_policy": {
            "grid_offsets_arcmin_each_axis": GRID_OFFSETS_ARCMIN,
            "grid_shape": "3x3",
            "local_reference_radius_arcmin": LOCAL_RADIUS_ARCMIN,
            "minimum_references_per_archive": MIN_REFS_PER_ARCHIVE,
            "dasch_reference_definition": (
                "official ai44092 platephot extraction with finite measured and "
                "reference-catalogue coordinates and a matched ref_number"
            ),
            "dasch_refcats": "all APASS/ATLAS calibrations advertised by queryexps",
            "dasch_duplicate_policy": (
                "dedupe by solution+image_x/image_y rounded 0.001 px; "
                "APASS preferred over ATLAS for identical extraction"
            ),
            "poss_reference_definition": (
                "reuse only SUCCESS rows from the previously fixed ordinary-Gaia-star "
                "pixel astrometry run, within the same 20 arcmin radius"
            ),
            "astrometric_model": "median translation only",
            "affine_or_polynomial_fit": False,
            "candidate_pixels_used_as_references": False,
            "detector_rerun": False,
            "interpretation_limit": (
                "diagnostic only: POSS residuals are Gaia-anchored while DASCH residuals "
                "are APASS/ATLAS-catalogue-anchored; result cannot alone promote a candidate"
            ),
        },
        "per_rank": report_ranks,
        "detector_rerun": False,
        "candidate_pixel_read": False,
        "candidate_deleted": False,
        "outputs": {
            "dasch_reference_audit_csv": str(OUT_DASCH),
            "summary_csv": str(OUT_SUMMARY),
        },
    }
    write_json(OUT_REPORT, report)

    print()
    print("=" * 108)
    print("CATALOG-ANCHORED LOCAL ASTROMETRIC SYSTEMATICS COMPLETE")
    print("=" * 108)
    print("Outputs:")
    print(" ", OUT_REPORT)
    print(" ", OUT_SUMMARY)
    print(" ", OUT_DASCH)
    print()
    print("No detector was rerun.")
    print("No candidate pixel was used as a calibration reference.")
    print("No candidate was deleted.")
    print("Any correction reported here is diagnostic, not a promotion criterion.")


if __name__ == "__main__":
    main()
