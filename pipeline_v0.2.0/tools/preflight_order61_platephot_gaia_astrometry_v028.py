from __future__ import annotations

from pathlib import Path
import csv
import importlib.util
import json
import math

import numpy as np
import astropy.units as u
from astropy.coordinates import SkyCoord
from astropy.io import fits

ROOT = Path.cwd()
BASE = ROOT / "results" / "order61_native_full_v028"

PLATEPHOT_WORKER = ROOT / "tools" / "preflight_order61_platephot_recurrence_v028b.py"
PIXEL_WORKER = ROOT / "tools" / "run_order61_pixel_gaia_astrometry_v028b.py"

PAIR_REPORT = BASE / "order61_whole_pair_report.json"
STRICT = BASE / "order61_strict_match_triage.csv"
MORPH = BASE / "order61_survivor_native_morphology.csv"
KNOWN_CONTROL = BASE / "order61_pixel_astrometry_known_gaia_controls_v028.json"

OUTCSV = BASE / "order61_platephot_gaia_astrometry_preflight_v028.csv"
OUTJSON = BASE / "order61_platephot_gaia_astrometry_preflight_v028.json"

ACTIVE_RANKS = [11, 14, 20]
PLATE_ID = "ai44092"

# Fixed before seeing this preflight outcome.
REFERENCE_RADIUS_ARCMIN = 8.0
GAIA_MATCH_ARCSEC = 3.0
GAIA_G_MIN = 10.5
GAIA_G_MAX = 15.5
GAIA_RUWE_MAX = 1.4
GAIA_ISOLATION_ARCSEC = 15.0
POSS_EDGE_MARGIN_PX = 40.0
MIN_REQUIRED_PER_RANK = 5

FIELDS = [
    "strict_rank",
    "plate_solution",
    "refcat",
    "platephot_ra_deg",
    "platephot_dec_deg",
    "sep_survivor_mid_arcmin",
    "platephot_ref_number",
    "platephot_catalog_matched",
    "platephot_magcal",
    "platephot_fwhm_arcsec",
    "platephot_aflags",
    "platephot_bflags",
    "gaia_source_id",
    "gaia_g_mag",
    "gaia_ruwe",
    "gaia_match_sep_arcsec",
    "gaia_nearest_neighbor_arcsec",
    "gaia_ra_1953_deg",
    "gaia_dec_1953_deg",
    "poss_pred_x",
    "poss_pred_y",
    "poss_inside_with_margin",
    "dedupe_kept",
]


def read_csv(path):
    with path.open(newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def write_csv(path, rows):
    t = path.with_suffix(path.suffix + ".tmp")
    with t.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    t.replace(path)


def write_json(path, obj):
    t = path.with_suffix(path.suffix + ".tmp")
    t.write_text(
        json.dumps(obj, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )
    t.replace(path)


def load_module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not import {path}")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def truth(v):
    return str(v).strip().lower() in {"true", "1", "yes", "y", "t"}


def nearest_neighbor_arcsec(coords, idx):
    if len(coords) <= 1:
        return float("inf")
    sep = np.asarray(coords[idx].separation(coords).arcsec, float)
    sep[idx] = np.inf
    return float(np.min(sep))


def main():
    print("=" * 104)
    print("ORDER 61 — OFFICIAL DASCH PLATEPHOT + GAIA ASTROMETRY PREFLIGHT v028")
    print("=" * 104)
    print("No fit, no detector, no image pixels. Reference-population census only.")
    print()

    for p in (
        PLATEPHOT_WORKER, PIXEL_WORKER, PAIR_REPORT,
        STRICT, MORPH, KNOWN_CONTROL,
    ):
        if not p.is_file():
            raise RuntimeError(f"Missing required input: {p}")

    pp = load_module(PLATEPHOT_WORKER, "platephot_preflight_v028b")
    pw = load_module(PIXEL_WORKER, "pixel_astrometry_v028b")

    pair = json.loads(PAIR_REPORT.read_text(encoding="utf-8"))
    control = json.loads(KNOWN_CONTROL.read_text(encoding="utf-8"))

    guards = {
        "pair_complete": pair.get("status") == "COMPLETE",
        "order61": int(pair.get("canonical_order", -1)) == 61,
        "known_control_complete": control.get("status") == "COMPLETE",
        "known_control_count": int(control.get("known_control_count", -1)) == 5,
        "known_control_no_detector": control.get("detector_rerun") is False,
        "known_control_no_candidate_adjudication": (
            control.get("science_candidate_adjudication_performed") is False
        ),
    }
    if not all(guards.values()):
        raise RuntimeError("REFUSING: guard failure: " + json.dumps(guards, sort_keys=True))

    strict = {int(r["strict_rank"]): r for r in read_csv(STRICT)}
    morph = {int(r["strict_rank"]): r for r in read_csv(MORPH)}
    for rank in ACTIVE_RANKS:
        if rank not in strict or rank not in morph:
            raise RuntimeError(f"missing rank {rank}")

    target = pw.target_epoch(pair)

    _, dss = pw.load_functions(
        pw.GEOM_SOURCE,
        ("plate_center_radians", "dss_world"),
        {"np": np},
    )
    h = fits.getheader(pw.REF, 0)
    fw, fh = int(h.get("XPIXELS", 14000)), int(h.get("YPIXELS", 13999))

    print("Completed-stage guards: PASS")
    print("Target epoch:", target.utc.isot)
    print(
        "Fixed reference preflight: official ai44092 platephot source within "
        f"{REFERENCE_RADIUS_ARCMIN:.0f}', propagated Gaia <= {GAIA_MATCH_ARCSEC:.0f}\", "
        f"{GAIA_G_MIN:.1f}<=G<={GAIA_G_MAX:.1f}, RUWE<={GAIA_RUWE_MAX:.1f}, "
        f"Gaia isolation>={GAIA_ISOLATION_ARCSEC:.0f}\", POSS margin>={POSS_EDGE_MARGIN_PX:.0f}px."
    )
    print()

    all_rows = []
    summary = {}

    for rank in ACTIVE_RANKS:
        sr = strict[rank]
        mr = morph[rank]

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
        mid = pw.midpoint(p, d)

        # Reuse the already-defined G<=16 Gaia query contract from the pixel worker.
        gaia_raw, gstatus = pw.gaia_query(mid, rank)
        propagated = []
        for g in gaia_raw:
            c = pw.propagate(g, target)
            if c is not None:
                propagated.append((g, c))

        if not propagated:
            raise RuntimeError(f"rank {rank}: no propagated Gaia rows")

        gcoords = SkyCoord(
            [c.ra.deg for _, c in propagated] * u.deg,
            [c.dec.deg for _, c in propagated] * u.deg,
            frame="icrs",
        )

        # Use queryexps to discover the exact covering ai44092 imaging solution
        # and every advertised APASS/ATLAS photometric calibration.
        exp_raw, exp_header, exp_status = pp.queryexps(
            rank, float(mid.ra.deg), float(mid.dec.deg)
        )
        exposures = [
            pp.parse_exposure(rank, float(mid.ra.deg), float(mid.dec.deg), r)
            for r in exp_raw
        ]
        pair_exps = [
            e for e in exposures
            if e["is_pair_plate_ai44092"] and e["has_imaging"]
        ]
        if not pair_exps:
            raise RuntimeError(f"rank {rank}: no ai44092 imaging solution")

        calls = []
        seen = set()
        sources = []

        for e in pair_exps:
            refcats = []
            if int(e["nSolutionsApass"]) > 0 or str(e["resultIdApass"]).strip():
                refcats.append("apass")
            if int(e["nSolutionsAtlas"]) > 0 or str(e["resultIdAtlas"]).strip():
                refcats.append("atlas")

            for refcat in refcats:
                key = (e["plate_id"], int(e["solnum"]), refcat)
                if key in seen:
                    continue
                seen.add(key)

                raw, header, status = pp.platephot(
                    rank, e["plate_id"], e["solnum"], refcat,
                    float(mid.ra.deg), float(mid.dec.deg),
                )
                calls.append({
                    "solution": int(e["solnum"]),
                    "refcat": refcat,
                    "status": status,
                    "rows": len(raw),
                })

                normalized_header = {pp.normkey(x) for x in header}
                if not (
                    {"radeg", "decdeg"} <= normalized_header
                    or {"ra", "dec"} <= normalized_header
                ):
                    raise RuntimeError(
                        f"rank {rank} platephot lacks RA/Dec: {header}"
                    )

                for rr in raw:
                    s = pp.parse_platephot_source(
                        rank, e["plate_id"], e["solnum"], refcat, rr,
                        float(sr["dasch_ra_deg"]), float(sr["dasch_dec_deg"]),
                        float(mid.ra.deg), float(mid.dec.deg),
                    )
                    if s is None:
                        continue
                    if float(s["sep_pair_midpoint_arcsec"]) <= REFERENCE_RADIUS_ARCMIN * 60:
                        sources.append(s)

        # Exact duplicate rows can occur between repeated API records.
        dedup_sources = {}
        for s in sources:
            k = (
                int(s["solution_number"]),
                str(s["refcat"]),
                round(float(s["ra_deg"]), 10),
                round(float(s["dec_deg"]), 10),
                s["ref_number"],
            )
            dedup_sources[k] = s
        sources = list(dedup_sources.values())

        matched = []
        for s in sources:
            sc = SkyCoord(
                float(s["ra_deg"]) * u.deg,
                float(s["dec_deg"]) * u.deg,
                frame="icrs",
            )
            sep = np.asarray(sc.separation(gcoords).arcsec, float)
            gi = int(np.argmin(sep))
            gsep = float(sep[gi])
            if gsep > GAIA_MATCH_ARCSEC:
                continue

            g, gc = propagated[gi]
            gg = g["phot_g_mean_mag"]
            ruwe = g["ruwe"]
            if gg is None or not (GAIA_G_MIN <= gg <= GAIA_G_MAX):
                continue
            if ruwe is None or ruwe > GAIA_RUWE_MAX:
                continue

            nn = nearest_neighbor_arcsec(gcoords, gi)
            if nn < GAIA_ISOLATION_ARCSEC:
                continue

            try:
                px, py = pw.poss_inv(
                    h, dss, gc,
                    float(mr["poss_global_x"]),
                    float(mr["poss_global_y"]),
                )
                inside = (
                    POSS_EDGE_MARGIN_PX <= px < fw - POSS_EDGE_MARGIN_PX
                    and POSS_EDGE_MARGIN_PX <= py < fh - POSS_EDGE_MARGIN_PX
                )
            except Exception:
                px = py = None
                inside = False

            row = {
                "strict_rank": rank,
                "plate_solution": int(s["solution_number"]),
                "refcat": s["refcat"],
                "platephot_ra_deg": s["ra_deg"],
                "platephot_dec_deg": s["dec_deg"],
                "sep_survivor_mid_arcmin": float(s["sep_pair_midpoint_arcsec"]) / 60.0,
                "platephot_ref_number": s["ref_number"],
                "platephot_catalog_matched": s["is_catalog_matched"],
                "platephot_magcal": s["magcal_magdep"],
                "platephot_fwhm_arcsec": s["fwhm_world_arcsec"],
                "platephot_aflags": s["aflags"],
                "platephot_bflags": s["bflags"],
                "gaia_source_id": g["source_id"],
                "gaia_g_mag": gg,
                "gaia_ruwe": ruwe,
                "gaia_match_sep_arcsec": gsep,
                "gaia_nearest_neighbor_arcsec": nn,
                "gaia_ra_1953_deg": float(gc.ra.deg),
                "gaia_dec_1953_deg": float(gc.dec.deg),
                "poss_pred_x": px,
                "poss_pred_y": py,
                "poss_inside_with_margin": inside,
                "dedupe_kept": False,
            }
            matched.append(row)

        # One reference per Gaia source. Prefer smallest platephot<->Gaia separation;
        # ties: APASS before ATLAS, then solution number.
        matched.sort(key=lambda r: (
            float(r["gaia_match_sep_arcsec"]),
            0 if r["refcat"] == "apass" else 1,
            int(r["plate_solution"]),
        ))
        kept = []
        seen_gaia = set()
        for r in matched:
            sid = r["gaia_source_id"]
            if sid in seen_gaia:
                continue
            seen_gaia.add(sid)
            r["dedupe_kept"] = True
            kept.append(r)

        all_rows.extend(matched)

        inside = [r for r in kept if truth(r["poss_inside_with_margin"])]
        summary[str(rank)] = {
            "queryexps_status": exp_status,
            "gaia_query_status": gstatus,
            "ai44092_imaging_solutions": len(pair_exps),
            "platephot_calls": calls,
            "platephot_sources_within_8arcmin": len(sources),
            "platephot_gaia_quality_matches_before_dedupe": len(matched),
            "unique_gaia_references": len(kept),
            "unique_gaia_references_inside_poss_margin": len(inside),
            "meets_minimum_for_future_fit": len(inside) >= MIN_REQUIRED_PER_RANK,
        }

        print(
            f"strict #{rank:02d}: platephot calls={len(calls)} "
            f"sources<=8'={len(sources)} Gaia-quality={len(matched)} "
            f"unique={len(kept)} POSS-inside={len(inside)} "
            f"=> {'PASS' if len(inside)>=MIN_REQUIRED_PER_RANK else 'INSUFFICIENT'}"
        )

    write_csv(OUTCSV, all_rows)

    report = {
        "status": "COMPLETE",
        "analysis_kind": "order61_official_platephot_gaia_astrometry_preflight_v028",
        "guards": guards,
        "fixed_policy": {
            "reference_radius_arcmin": REFERENCE_RADIUS_ARCMIN,
            "platephot_plate": PLATE_ID,
            "platephot_refcats": "all APASS/ATLAS calibrations advertised by queryexps",
            "gaia_match_arcsec": GAIA_MATCH_ARCSEC,
            "gaia_g_range": [GAIA_G_MIN, GAIA_G_MAX],
            "gaia_ruwe_max": GAIA_RUWE_MAX,
            "gaia_isolation_arcsec": GAIA_ISOLATION_ARCSEC,
            "poss_edge_margin_px": POSS_EDGE_MARGIN_PX,
            "minimum_required_per_rank_for_future_fit": MIN_REQUIRED_PER_RANK,
            "dedupe": "one row per Gaia source; smallest platephot-Gaia separation, APASS tie preference",
            "fit_performed": False,
            "image_pixels_read": False,
            "detector_rerun": False,
            "candidate_adjudication": False,
        },
        "per_rank": summary,
        "all_ranks_meet_future_fit_minimum": all(
            summary[str(r)]["meets_minimum_for_future_fit"]
            for r in ACTIVE_RANKS
        ),
        "outputs": {"reference_census_csv": str(OUTCSV)},
    }
    write_json(OUTJSON, report)

    print()
    print("=" * 104)
    print("OFFICIAL PLATEPHOT + GAIA ASTROMETRY PREFLIGHT COMPLETE")
    print("=" * 104)
    print("Output:", OUTJSON)
    print("CSV:   ", OUTCSV)
    print()
    print("No astrometric fit was performed.")
    print("No image pixel was read.")
    print("No detector was rerun.")
    print("No #11/#14/#20 candidate was adjudicated or deleted.")


if __name__ == "__main__":
    main()
