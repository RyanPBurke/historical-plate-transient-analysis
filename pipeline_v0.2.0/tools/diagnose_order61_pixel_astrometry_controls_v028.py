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
from astropy.wcs import WCS
import gzip, base64

ROOT = Path.cwd()
BASE = ROOT / "results" / "order61_native_full_v028"

WORKER = ROOT / "tools" / "run_order61_pixel_gaia_astrometry_v028b.py"
PAIR_REPORT = BASE / "order61_whole_pair_report.json"
STRICT = BASE / "order61_strict_match_triage.csv"
GAIA_TRIAGE = BASE / "order61_gaia_static_triage.csv"
GAIA_SOURCES = BASE / "order61_gaia_source_candidates.csv"
POSS_CAND = BASE / "order61_poss_native_candidates.csv"
DASCH_CAND = BASE / "order61_dasch_native_candidates.csv"
PRIOR_PIXEL_REFS = BASE / "order61_pixel_gaia_astrometry_references_v028.csv"

OUT = BASE / "order61_pixel_astrometry_known_gaia_controls_v028.json"
OUTCSV = BASE / "order61_pixel_astrometry_known_gaia_controls_v028.csv"

FIELDS = [
    "strict_rank", "gaia_source_id",
    "gaia_sep_poss_arcsec", "gaia_sep_dasch_arcsec",
    "poss_tile_id", "poss_candidate_index",
    "poss_global_x", "poss_global_y", "poss_frozen_detector_snr",
    "poss_gaia_pred_x", "poss_gaia_pred_y",
    "poss_pred_to_detector_px", "poss_pred_to_detector_arcsec",
    "poss_measure_at_gaia_status", "poss_measure_at_gaia_peak_snr",
    "poss_measure_at_detector_status", "poss_measure_at_detector_peak_snr",
    "dasch_tile_id", "dasch_candidate_index",
    "dasch_global_x", "dasch_global_y", "dasch_frozen_detector_snr",
    "dasch_gaia_pred_x", "dasch_gaia_pred_y",
    "dasch_pred_to_detector_px", "dasch_pred_to_detector_arcsec",
    "dasch_measure_at_gaia_status", "dasch_measure_at_gaia_peak_snr",
    "dasch_measure_at_detector_status", "dasch_measure_at_detector_peak_snr",
]


def read_csv(p):
    with p.open(newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def write_csv(p, rows):
    t = p.with_suffix(p.suffix + ".tmp")
    with t.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    t.replace(p)


def write_json(p, obj):
    t = p.with_suffix(p.suffix + ".tmp")
    t.write_text(json.dumps(obj, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    t.replace(p)


def truth(v):
    return str(v).strip().lower() in {"true", "1", "yes", "y", "t"}


def load_worker():
    spec = importlib.util.spec_from_file_location("pixel_astrometry_v028b", WORKER)
    if spec is None or spec.loader is None:
        raise RuntimeError("could not create import spec for v028b worker")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def cand_index(rows):
    out = {}
    for r in rows:
        out[(str(r["tile_id"]), int(r["candidate_index"]))] = r
    return out


def finite_stats(vals):
    q = [float(v) for v in vals if v not in (None, "") and math.isfinite(float(v))]
    if not q:
        return None
    a = np.asarray(q, float)
    return {
        "n": len(a),
        "min": float(np.min(a)),
        "median": float(np.median(a)),
        "p90": float(np.percentile(a, 90)),
        "max": float(np.max(a)),
        "ge4": int(np.sum(a >= 4.0)),
        "ge5": int(np.sum(a >= 5.0)),
    }


def main():
    print("=" * 100)
    print("ORDER 61 — KNOWN GAIA-BOTH NATIVE-PIXEL ASTROMETRY CONTROL v028")
    print("=" * 100)
    print("Read-only control of pixel/WCS/centroid plumbing. No detector rerun; no science-candidate adjudication.")
    print()

    for p in (WORKER, PAIR_REPORT, STRICT, GAIA_TRIAGE, GAIA_SOURCES, POSS_CAND, DASCH_CAND):
        if not p.is_file():
            raise RuntimeError(f"Missing required input: {p}")

    m = load_worker()

    pair = json.loads(PAIR_REPORT.read_text(encoding="utf-8"))
    if pair.get("status") != "COMPLETE" or int(pair.get("canonical_order", -1)) != 61:
        raise RuntimeError("completed Order-61 report guard failed")

    strict = read_csv(STRICT)
    triage = read_csv(GAIA_TRIAGE)
    sources = read_csv(GAIA_SOURCES)
    pidx = cand_index(read_csv(POSS_CAND))
    didx = cand_index(read_csv(DASCH_CAND))

    both = [r for r in triage if truth(r["gaia_both_endpoints_within_3arcsec"])]
    if len(both) != 5:
        raise RuntimeError(f"REFUSING: expected exactly 5 completed Gaia-both<=3 controls, got {len(both)}")

    sby = {int(r["strict_rank"]): r for r in strict}
    srcby = {}
    for r in sources:
        srcby[(int(r["strict_rank"]), str(r["source_id"]))] = r

    # Recover exact plate geometry identically to the worker.
    _, dss = m.load_functions(
        m.GEOM_SOURCE,
        ("plate_center_radians", "dss_world"),
        {"np": np},
    )
    (tpv,) = m.load_functions(
        m.CONTROL_SOURCE,
        ("tpv",),
        {"fits": fits, "WCS": WCS, "gzip": gzip, "base64": base64},
    )

    h = fits.getheader(m.REF, 0)
    fw, fh = int(h.get("XPIXELS", 14000)), int(h.get("YPIXELS", 13999))
    pkg = m.mosaic_package()
    dw, dh, rk, shape = tpv(pkg["metadata"])
    H, W = shape
    outH, outW = (W, H) if rk in (-1, 1) else (H, W)

    rows = []

    for q in sorted(both, key=lambda r: int(r["strict_rank"])):
        rank = int(q["strict_rank"])
        sr = sby[rank]
        sid = str(q["best_both_source_id"])
        gs = srcby.get((rank, sid))
        if gs is None:
            raise RuntimeError(f"rank {rank}: Gaia audit source {sid} not found")

        c = SkyCoord(
            float(gs["ra_target_deg"]) * u.deg,
            float(gs["dec_target_deg"]) * u.deg,
            frame="icrs",
        )

        pk = (sr["poss_tile_id"], int(sr["poss_candidate_index"]))
        dk = (sr["dasch_tile_id"], int(sr["dasch_candidate_index"]))
        pr = pidx.get(pk)
        dr = didx.get(dk)
        if pr is None or dr is None:
            raise RuntimeError(f"rank {rank}: known detector endpoint row missing")

        pgx, pgy = float(pr["global_x"]), float(pr["global_y"])
        dgx, dgy = float(dr["global_x"]), float(dr["global_y"])

        # Gaia->POSS prediction seeded at the known nearby detector endpoint.
        ppx, ppy = m.poss_inv(h, dss, c, pgx, pgy)
        pscale = m.poss_scale(h, dss, ppx, ppy)
        psep_px = math.hypot(ppx - pgx, ppy - pgy)

        # Gaia->DASCH direct TPV prediction.
        dpx, dpy = map(float, dw.world_to_pixel(c))
        dscale = m.dasch_scale(dw, dpx, dpy)
        dsep_px = math.hypot(dpx - dgx, dpy - dgy)

        # Current centroid estimator at Gaia prediction and at known detector peak.
        pm_g = m.centroid("POSS", ppx, ppy, pscale, fw, fh, m.POSS_DIR)
        pm_d = m.centroid("POSS", pgx, pgy, m.poss_scale(h, dss, pgx, pgy), fw, fh, m.POSS_DIR)
        dm_g = m.centroid("DASCH", dpx, dpy, dscale, outW, outH, m.DASCH_DIR)
        dm_d = m.centroid("DASCH", dgx, dgy, m.dasch_scale(dw, dgx, dgy), outW, outH, m.DASCH_DIR)

        out = {
            "strict_rank": rank,
            "gaia_source_id": sid,
            "gaia_sep_poss_arcsec": float(q["best_both_sep_poss_arcsec"]),
            "gaia_sep_dasch_arcsec": float(q["best_both_sep_dasch_arcsec"]),
            "poss_tile_id": pk[0],
            "poss_candidate_index": pk[1],
            "poss_global_x": pgx,
            "poss_global_y": pgy,
            "poss_frozen_detector_snr": float(pr["snr"]),
            "poss_gaia_pred_x": ppx,
            "poss_gaia_pred_y": ppy,
            "poss_pred_to_detector_px": psep_px,
            "poss_pred_to_detector_arcsec": psep_px * pscale,
            "poss_measure_at_gaia_status": pm_g.get("status"),
            "poss_measure_at_gaia_peak_snr": pm_g.get("peak_snr"),
            "poss_measure_at_detector_status": pm_d.get("status"),
            "poss_measure_at_detector_peak_snr": pm_d.get("peak_snr"),
            "dasch_tile_id": dk[0],
            "dasch_candidate_index": dk[1],
            "dasch_global_x": dgx,
            "dasch_global_y": dgy,
            "dasch_frozen_detector_snr": float(dr["snr"]),
            "dasch_gaia_pred_x": dpx,
            "dasch_gaia_pred_y": dpy,
            "dasch_pred_to_detector_px": dsep_px,
            "dasch_pred_to_detector_arcsec": dsep_px * dscale,
            "dasch_measure_at_gaia_status": dm_g.get("status"),
            "dasch_measure_at_gaia_peak_snr": dm_g.get("peak_snr"),
            "dasch_measure_at_detector_status": dm_d.get("status"),
            "dasch_measure_at_detector_peak_snr": dm_d.get("peak_snr"),
        }
        rows.append(out)

        print(
            f"strict #{rank:02d} Gaia={sid} | "
            f"P frozen={out['poss_frozen_detector_snr']:.2f} "
            f"cent@Gaia={out['poss_measure_at_gaia_peak_snr']} "
            f"pred->peak={out['poss_pred_to_detector_arcsec']:.2f}\" | "
            f"D frozen={out['dasch_frozen_detector_snr']:.2f} "
            f"cent@Gaia={out['dasch_measure_at_gaia_peak_snr']} "
            f"pred->peak={out['dasch_pred_to_detector_arcsec']:.2f}\""
        )

    write_csv(OUTCSV, rows)

    prior = None
    if PRIOR_PIXEL_REFS.is_file():
        rr = read_csv(PRIOR_PIXEL_REFS)
        prior = {}
        for rank in (11, 14, 20):
            q = [r for r in rr if int(r["strict_rank"]) == rank]
            prior[str(rank)] = {
                "selected_rows": len(q),
                "poss_peak_snr": finite_stats(r.get("poss_peak_snr") for r in q),
                "dasch_peak_snr": finite_stats(r.get("dasch_peak_snr") for r in q),
                "poss_status_counts": {
                    k: sum(r.get("poss_status") == k for r in q)
                    for k in sorted(set(r.get("poss_status") for r in q))
                },
                "dasch_status_counts": {
                    k: sum(r.get("dasch_status") == k for r in q)
                    for k in sorted(set(r.get("dasch_status") for r in q))
                },
            }

    report = {
        "status": "COMPLETE",
        "analysis_kind": "order61_known_gaia_both_pixel_astrometry_control_v028",
        "purpose": (
            "Validate Gaia->native-pixel coordinate mapping and current centroid-SNR "
            "estimator against the five already-completed Gaia-both<=3 strict detector "
            "associations before interpreting the ordinary-star zero-reference run."
        ),
        "known_control_count": len(rows),
        "controls": rows,
        "ordinary_star_run_snr_audit": prior,
        "scientific_thresholds_changed": False,
        "detector_rerun": False,
        "science_candidate_adjudication_performed": False,
        "image_pixels_read": True,
        "outputs": {"control_csv": str(OUTCSV)},
    }
    write_json(OUT, report)

    print()
    print("=" * 100)
    print("KNOWN GAIA-BOTH PIXEL CONTROL COMPLETE")
    print("=" * 100)
    print("Output:", OUT)
    print("CSV:   ", OUTCSV)

    if prior is not None:
        print()
        print("Ordinary-star DASCH centroid-SNR audit from the prior v028b run:")
        for rank in (11, 14, 20):
            z = prior[str(rank)]["dasch_peak_snr"]
            print(f"  strict #{rank:02d}: {z}")

    print()
    print("No detector was rerun.")
    print("No #11/#14/#20 candidate was adjudicated or deleted.")
    print("No measurement threshold was changed.")


if __name__ == "__main__":
    main()
