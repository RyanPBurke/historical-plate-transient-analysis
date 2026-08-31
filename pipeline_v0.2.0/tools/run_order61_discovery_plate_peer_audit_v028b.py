from __future__ import annotations

from pathlib import Path
import csv
import importlib.util
import json
import math

import numpy as np

ROOT = Path.cwd()
BASE = ROOT / "results" / "order61_native_full_v028"
WORK = ROOT / "work" / "order61_native_full_v028"
OUTDIR = BASE / "order61_discovery_plate_audit_v028"
OUTDIR.mkdir(parents=True, exist_ok=True)

MORPH_MODULE = ROOT / "tools" / "vet_order61_survivor_morphology_v028.py"

PAIR_REPORT = BASE / "order61_whole_pair_report.json"
STRICT = BASE / "order61_strict_match_triage.csv"
GAIA = BASE / "order61_gaia_static_triage.csv"
MORPH = BASE / "order61_survivor_native_morphology.csv"
POSS_CAND = BASE / "order61_poss_native_candidates.csv"
DASCH_CAND = BASE / "order61_dasch_native_candidates.csv"
STAGE3 = BASE / "order61_platephot_stage3_report.json"
CATALOG_ASTROM = BASE / "order61_catalog_anchored_local_systematics_report_v028.json"

OUT_ENDPOINT = OUTDIR / "order61_discovery_plate_endpoint_metrics_v028b.csv"
OUT_CONTROL = OUTDIR / "order61_discovery_plate_matched_controls_v028b.csv"
OUT_SUMMARY = OUTDIR / "order61_discovery_plate_candidate_summary_v028b.csv"
OUT_REPORT = OUTDIR / "order61_discovery_plate_audit_report_v028b.json"

ACTIVE_RANKS = [11, 14, 20]

# ---------------------------------------------------------------------
# PROSPECTIVELY FIXED MATCHED-PEER POLICY
# Defined before looking at the new matched-control morphology outcomes.
# ---------------------------------------------------------------------
MIN_PREFERRED_CONTROLS = 12
MAX_CONTROLS = 32
EXCLUSION_RADIUS_PX = 32.0
PREFERRED_SNR_RATIO = (0.75, 1.25)
FALLBACK_SNR_RATIO = (0.50, 1.50)
DISPLAY_RADIUS_PX = 40

CONTINUOUS_METRICS = [
    "sigma_major_px",
    "sigma_minor_px",
    "ellipticity",
    "peak_to_flux5",
    "concentration_flux3_flux8",
    "centroid_offset_px",
]
COUNT_METRICS = [
    "plateau_count_3x3",
    "local_extreme_count_3x3",
]

ENDPOINT_FIELDS = [
    "strict_rank", "archive",
    "tile_id", "candidate_index", "global_x", "global_y",
    "snr", "polarity",
    "control_selection_mode", "control_count",
    "local_bg", "local_sigma", "peak_bgsub_polarity",
    "sigma_major_px", "sigma_minor_px", "ellipticity",
    "peak_to_flux5", "concentration_flux3_flux8",
    "centroid_offset_px", "plateau_count_3x3", "local_extreme_count_3x3",
    "sigma_major_peer_percentile", "sigma_minor_peer_percentile",
    "ellipticity_peer_percentile", "peak_to_flux5_peer_percentile",
    "concentration_peer_percentile", "centroid_offset_peer_percentile",
    "plateau_peer_percentile", "local_extreme_peer_percentile",
    "matched_peer_extreme_continuous_metric_count",
    "matched_peer_count_metric_ge95_count",
    "display_npy",
    "display_png",
]

CONTROL_FIELDS = [
    "strict_rank", "archive", "control_order", "selection_mode",
    "tile_id", "candidate_index", "global_x", "global_y",
    "distance_from_science_px", "snr", "snr_ratio", "polarity",
    "local_bg", "local_sigma", "peak_bgsub_polarity",
    "sigma_major_px", "sigma_minor_px", "ellipticity",
    "peak_to_flux5", "concentration_flux3_flux8",
    "centroid_offset_px", "plateau_count_3x3", "local_extreme_count_3x3",
]

SUMMARY_FIELDS = [
    "strict_rank",
    "pair_separation_arcsec",
    "poss_snr", "dasch_snr",
    "poss_polarity", "dasch_polarity", "same_polarity",
    "prior_morphology_flag_count",
    "prior_registration_residual_arcsec",
    "recurrence_tested_plates",
    "recurrence_sources_within_5arcsec",
    "local_astrometry_status",
    "poss_control_count", "dasch_control_count",
    "poss_matched_peer_extreme_continuous_metric_count",
    "dasch_matched_peer_extreme_continuous_metric_count",
    "poss_matched_peer_count_metric_ge95_count",
    "dasch_matched_peer_count_metric_ge95_count",
    "discovery_plate_status",
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
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def as_bool(v):
    return str(v).strip().lower() in {"true", "1", "yes", "y", "t"}


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


def percentile(value, values):
    vals = np.asarray(
        [float(x) for x in values if x is not None and math.isfinite(float(x))],
        dtype=float,
    )
    if not math.isfinite(float(value)) or len(vals) == 0:
        return None
    # Midrank empirical percentile.
    lt = int(np.sum(vals < float(value)))
    eq = int(np.sum(vals == float(value)))
    return 100.0 * (lt + 0.5 * eq) / len(vals)


def extract_display(arr, lx, ly, radius=DISPLAY_RADIUS_PX):
    """
    Audit-only fixed-size display extraction.

    v028 incorrectly required the optional 81x81 visual panel to fit fully
    inside the cached/native array, even though the scientific morphology
    measurement requires only the already-validated 41x41 (radius-20) cutout.

    Preserve the requested display size by copying the available native
    pixels into an NaN-padded array.  No pixel is synthesized or reflected;
    padded values are excluded from percentile scaling by the plotting code.
    This function is not used by any morphology metric or peer selection.
    """
    ix, iy = int(round(lx)), int(round(ly))
    size = 2 * radius + 1
    out = np.full((size, size), np.nan, dtype=float)

    src_x0 = max(0, ix - radius)
    src_x1 = min(arr.shape[1], ix + radius + 1)
    src_y0 = max(0, iy - radius)
    src_y1 = min(arr.shape[0], iy + radius + 1)

    if src_x0 >= src_x1 or src_y0 >= src_y1:
        raise RuntimeError("display center lies outside native array")

    dst_x0 = src_x0 - (ix - radius)
    dst_y0 = src_y0 - (iy - radius)
    dst_x1 = dst_x0 + (src_x1 - src_x0)
    dst_y1 = dst_y0 + (src_y1 - src_y0)

    out[dst_y0:dst_y1, dst_x0:dst_x1] = np.asarray(
        arr[src_y0:src_y1, src_x0:src_x1],
        dtype=float,
    )
    return out


def save_display(rank, archive, candidate_cut, control_cuts):
    stem = f"strict_{rank:02d}_{archive.lower()}"
    npy = OUTDIR / f"{stem}_candidate_display.npy"
    np.save(npy, candidate_cut)

    png = OUTDIR / f"{stem}_candidate_and_controls.png"
    png_written = False

    try:
        import matplotlib.pyplot as plt

        ncontrols = min(8, len(control_cuts))
        ncols = 3
        nitems = 1 + ncontrols
        nrows = int(math.ceil(nitems / ncols))

        fig, axes = plt.subplots(nrows, ncols, figsize=(9, 3*nrows), squeeze=False)
        axes = axes.ravel()

        panels = [("SCIENCE", candidate_cut)] + [
            (f"CTRL {i+1}", control_cuts[i]) for i in range(ncontrols)
        ]

        for ax, (title, cut) in zip(axes, panels):
            finite = cut[np.isfinite(cut)]
            if finite.size:
                lo, hi = np.percentile(finite, [2, 98])
                if not math.isfinite(lo) or not math.isfinite(hi) or hi <= lo:
                    lo, hi = float(np.nanmin(finite)), float(np.nanmax(finite))
            else:
                lo, hi = 0.0, 1.0

            ax.imshow(cut, origin="lower", cmap="gray", vmin=lo, vmax=hi)
            c = DISPLAY_RADIUS_PX
            ax.plot([c], [c], marker="+", markersize=10)
            ax.set_title(title)
            ax.set_xticks([])
            ax.set_yticks([])

        for ax in axes[len(panels):]:
            ax.axis("off")

        fig.suptitle(f"Order 61 strict #{rank:02d} {archive} native cutout audit")
        fig.tight_layout()
        fig.savefig(png, dpi=160)
        plt.close(fig)
        png_written = True
    except Exception as exc:
        print(f"  NOTE: PNG panel skipped for rank #{rank:02d} {archive}: {exc}")

    return str(npy), str(png) if png_written else None


def candidate_spec(strict_row, archive):
    p = archive.lower()
    return {
        "tile": str(strict_row[f"{p}_tile_id"]),
        "idx": int(strict_row[f"{p}_candidate_index"]),
        "snr": float(strict_row[f"{p}_snr"]),
        "pol": int(strict_row[f"{p}_polarity"]),
        "ra": float(strict_row[f"{p}_ra_deg"]),
        "dec": float(strict_row[f"{p}_dec_deg"]),
    }


def candidate_metrics(m, cand_rows_all, cand_by_tile, spec, full_shape):
    row = m.match_candidate(
        cand_rows_all,
        spec["idx"],
        spec["tile"],
        spec["snr"],
        spec["ra"],
        spec["dec"],
    )
    gx, gy, coord_source = m.resolve_global_xy(row, spec["tile"], full_shape)
    arr, npy_path, (ex0, ex1, ey0, ey1) = m.load_tile(spec["tile"], full_shape)
    lx, ly = gx-ex0, gy-ey0
    metrics = m.morphology(arr, lx, ly, spec["pol"])
    display = extract_display(arr, lx, ly)

    return {
        "row": row,
        "gx": gx,
        "gy": gy,
        "coord_source": coord_source,
        "arr": arr,
        "npy_path": npy_path,
        "ex0": ex0,
        "ey0": ey0,
        "lx": lx,
        "ly": ly,
        "metrics": metrics,
        "display": display,
    }


def peer_candidates(m, rows, spec, full_shape, science_gx, science_gy):
    candidates = []

    for row in rows:
        pol = m.row_pol(row)
        snr = m.row_snr(row)
        if pol != spec["pol"] or snr is None or snr <= 0:
            continue

        try:
            gx, gy, coord_source = m.resolve_global_xy(row, spec["tile"], full_shape)
        except Exception:
            continue

        dist = math.hypot(gx-science_gx, gy-science_gy)
        if dist < EXCLUSION_RADIUS_PX:
            continue

        ratio = float(snr) / float(spec["snr"])
        idx = fint(m.pick(row, ["candidate_index", "index", "candidate_id", "peak_index"]))

        candidates.append({
            "row": row,
            "gx": gx,
            "gy": gy,
            "dist": dist,
            "snr": float(snr),
            "ratio": ratio,
            "idx": idx,
            "coord_source": coord_source,
        })

    preferred = [
        q for q in candidates
        if PREFERRED_SNR_RATIO[0] <= q["ratio"] <= PREFERRED_SNR_RATIO[1]
    ]
    fallback = [
        q for q in candidates
        if FALLBACK_SNR_RATIO[0] <= q["ratio"] <= FALLBACK_SNR_RATIO[1]
    ]

    if len(preferred) >= MIN_PREFERRED_CONTROLS:
        pool = preferred
        mode = "same_tile_same_polarity_snr_ratio_0.75_1.25"
        pool.sort(key=lambda q: (q["dist"], abs(math.log(q["ratio"])), q["snr"]))
    elif len(fallback) >= MIN_PREFERRED_CONTROLS:
        pool = fallback
        mode = "same_tile_same_polarity_snr_ratio_0.50_1.50_fallback"
        pool.sort(key=lambda q: (q["dist"], abs(math.log(q["ratio"])), q["snr"]))
    else:
        pool = candidates
        mode = "same_tile_same_polarity_nearest_snr_fallback"
        pool.sort(key=lambda q: (abs(math.log(q["ratio"])), q["dist"], q["snr"]))

    return pool[:MAX_CONTROLS], mode


def evaluate_endpoint(m, rank, archive, strict_row, cand_rows_all, cand_by_tile, full_shape):
    spec = candidate_spec(strict_row, archive)
    sci = candidate_metrics(m, cand_rows_all, cand_by_tile, spec, full_shape)

    tile_rows = cand_by_tile[spec["tile"]]
    controls_raw, mode = peer_candidates(
        m, tile_rows, spec, full_shape, sci["gx"], sci["gy"]
    )

    control_rows = []
    control_metrics = []
    control_cuts = []

    for order, q in enumerate(controls_raw, 1):
        try:
            arr, npy_path, (ex0, ex1, ey0, ey1) = m.load_tile(spec["tile"], full_shape)
            lx, ly = q["gx"]-ex0, q["gy"]-ey0
            met = m.morphology(arr, lx, ly, spec["pol"])
            disp = extract_display(arr, lx, ly)
        except Exception:
            continue

        control_metrics.append(met)
        control_cuts.append(disp)

        control_rows.append({
            "strict_rank": rank,
            "archive": archive,
            "control_order": len(control_rows)+1,
            "selection_mode": mode,
            "tile_id": spec["tile"],
            "candidate_index": q["idx"],
            "global_x": q["gx"],
            "global_y": q["gy"],
            "distance_from_science_px": q["dist"],
            "snr": q["snr"],
            "snr_ratio": q["ratio"],
            "polarity": spec["pol"],
            **{k: met.get(k) for k in (
                "local_bg", "local_sigma", "peak_bgsub_polarity",
                "sigma_major_px", "sigma_minor_px", "ellipticity",
                "peak_to_flux5", "concentration_flux3_flux8",
                "centroid_offset_px", "plateau_count_3x3",
                "local_extreme_count_3x3",
            )},
        })

    if len(control_metrics) < 5:
        raise RuntimeError(
            f"rank #{rank} {archive}: only {len(control_metrics)} usable matched controls"
        )

    sm = sci["metrics"]
    pct = {}

    for key in CONTINUOUS_METRICS + COUNT_METRICS:
        pct[key] = percentile(sm[key], [q[key] for q in control_metrics])

    extreme_cont = sum(
        pct[k] is not None and (pct[k] <= 5.0 or pct[k] >= 95.0)
        for k in CONTINUOUS_METRICS
    )
    count_hi = sum(
        pct[k] is not None and pct[k] >= 95.0
        for k in COUNT_METRICS
    )

    display_npy, display_png = save_display(
        rank, archive, sci["display"], control_cuts
    )

    endpoint_row = {
        "strict_rank": rank,
        "archive": archive,
        "tile_id": spec["tile"],
        "candidate_index": spec["idx"],
        "global_x": sci["gx"],
        "global_y": sci["gy"],
        "snr": spec["snr"],
        "polarity": spec["pol"],
        "control_selection_mode": mode,
        "control_count": len(control_metrics),
        **{k: sm.get(k) for k in (
            "local_bg", "local_sigma", "peak_bgsub_polarity",
            "sigma_major_px", "sigma_minor_px", "ellipticity",
            "peak_to_flux5", "concentration_flux3_flux8",
            "centroid_offset_px", "plateau_count_3x3",
            "local_extreme_count_3x3",
        )},
        "sigma_major_peer_percentile": pct["sigma_major_px"],
        "sigma_minor_peer_percentile": pct["sigma_minor_px"],
        "ellipticity_peer_percentile": pct["ellipticity"],
        "peak_to_flux5_peer_percentile": pct["peak_to_flux5"],
        "concentration_peer_percentile": pct["concentration_flux3_flux8"],
        "centroid_offset_peer_percentile": pct["centroid_offset_px"],
        "plateau_peer_percentile": pct["plateau_count_3x3"],
        "local_extreme_peer_percentile": pct["local_extreme_count_3x3"],
        "matched_peer_extreme_continuous_metric_count": extreme_cont,
        "matched_peer_count_metric_ge95_count": count_hi,
        "display_npy": display_npy,
        "display_png": display_png,
    }

    return endpoint_row, control_rows


def main():
    print("=" * 108)
    print("ORDER 61 — DISCOVERY-PLATE NATIVE PIXEL + SNR-MATCHED PEER AUDIT v028b")
    print("=" * 108)
    print(
        "No detector rerun. Same-tile/same-polarity controls selected only by SNR and position. "
        "Visual panels are audit-only."
    )
    print(
        "Implementation amendment: optional 81x81 display cutouts are NaN-padded at native "
        "array/physical edges; quantitative morphology and peer policy are unchanged."
    )
    print()

    for p in (
        MORPH_MODULE, PAIR_REPORT, STRICT, GAIA, MORPH,
        POSS_CAND, DASCH_CAND, STAGE3, CATALOG_ASTROM,
    ):
        if not p.is_file():
            raise RuntimeError(f"Missing required input: {p}")

    m = load_module(MORPH_MODULE, "order61_morph_v028")

    pair = json.loads(PAIR_REPORT.read_text(encoding="utf-8"))
    stage3 = json.loads(STAGE3.read_text(encoding="utf-8"))
    astrom = json.loads(CATALOG_ASTROM.read_text(encoding="utf-8"))

    s3 = {
        int(r["strict_rank"]): r
        for r in stage3.get("active_rank_summaries_cumulative_1024", [])
    }

    guards = {
        "pair_complete": pair.get("status") == "COMPLETE",
        "order61": int(pair.get("canonical_order", -1)) == 61,
        "stage3_complete": stage3.get("status") == "COMPLETE",
        "stage3_active": sorted(s3) == ACTIVE_RANKS,
        "stage3_all_1024": all(
            int(s3[r]["cumulative_completed_plates"]) == 1024
            for r in ACTIVE_RANKS
        ),
        "stage3_all_zero5": all(
            int(s3[r]["observed_sources_within_5arcsec"]) == 0
            for r in ACTIVE_RANKS
        ),
        "catalog_astrometry_complete": astrom.get("status") == "COMPLETE",
        "catalog_astrometry_all_insufficient": all(
            astrom.get("per_rank", {}).get(str(r), {}).get("status")
            == "INSUFFICIENT_CATALOG_ANCHORED_REFERENCES"
            for r in ACTIVE_RANKS
        ),
        "astrometry_detector_not_rerun": astrom.get("detector_rerun") is False,
    }
    if not all(guards.values()):
        raise RuntimeError("REFUSING: completed-stage guard failure: " + repr(guards))

    strict_rows = read_csv(STRICT)
    morph_rows = read_csv(MORPH)
    poss_rows = read_csv(POSS_CAND)
    dasch_rows = read_csv(DASCH_CAND)

    strict_by_rank = {int(r["strict_rank"]): r for r in strict_rows}
    prior_morph = {int(r["strict_rank"]): r for r in morph_rows}

    if any(r not in strict_by_rank or r not in prior_morph for r in ACTIVE_RANKS):
        raise RuntimeError("missing active candidate input row")

    poss_by_tile = m.build_tile_index(poss_rows)
    dasch_by_tile = m.build_tile_index(dasch_rows)

    endpoint_rows = []
    control_rows = []
    summaries = []
    report_ranks = {}

    print("Completed-stage guards: PASS")
    print(
        "Fixed controls: same tile + same polarity; exclude <32 px; prefer SNR ratio "
        "0.75–1.25, fixed fallback 0.50–1.50 if <12, otherwise nearest-SNR fallback; "
        "maximum 32 controls."
    )
    print()

    for rank in ACTIVE_RANKS:
        sr = strict_by_rank[rank]
        pm = prior_morph[rank]

        poss_ep, poss_ctrl = evaluate_endpoint(
            m, rank, "POSS", sr, poss_rows, poss_by_tile, m.POSS_SHAPE_XY
        )
        dasch_ep, dasch_ctrl = evaluate_endpoint(
            m, rank, "DASCH", sr, dasch_rows, dasch_by_tile, m.DASCH_SHAPE_XY
        )

        endpoint_rows.extend([poss_ep, dasch_ep])
        control_rows.extend(poss_ctrl)
        control_rows.extend(dasch_ctrl)

        summary = {
            "strict_rank": rank,
            "pair_separation_arcsec": float(sr["separation_arcsec"]),
            "poss_snr": float(sr["poss_snr"]),
            "dasch_snr": float(sr["dasch_snr"]),
            "poss_polarity": int(sr["poss_polarity"]),
            "dasch_polarity": int(sr["dasch_polarity"]),
            "same_polarity": int(sr["poss_polarity"]) == int(sr["dasch_polarity"]),
            "prior_morphology_flag_count": int(pm["morphology_flag_count"]),
            "prior_registration_residual_arcsec": float(pm["registration_residual_arcsec"]),
            "recurrence_tested_plates": int(s3[rank]["cumulative_completed_plates"]),
            "recurrence_sources_within_5arcsec": int(s3[rank]["observed_sources_within_5arcsec"]),
            "local_astrometry_status": astrom["per_rank"][str(rank)]["status"],
            "poss_control_count": int(poss_ep["control_count"]),
            "dasch_control_count": int(dasch_ep["control_count"]),
            "poss_matched_peer_extreme_continuous_metric_count": int(
                poss_ep["matched_peer_extreme_continuous_metric_count"]
            ),
            "dasch_matched_peer_extreme_continuous_metric_count": int(
                dasch_ep["matched_peer_extreme_continuous_metric_count"]
            ),
            "poss_matched_peer_count_metric_ge95_count": int(
                poss_ep["matched_peer_count_metric_ge95_count"]
            ),
            "dasch_matched_peer_count_metric_ge95_count": int(
                dasch_ep["matched_peer_count_metric_ge95_count"]
            ),
            "discovery_plate_status": "MATCHED_PEER_NATIVE_PIXEL_AUDIT_COMPLETE",
        }
        summaries.append(summary)
        report_ranks[str(rank)] = {
            "summary": summary,
            "POSS": poss_ep,
            "DASCH": dasch_ep,
        }

        print(
            f"strict #{rank:02d}: "
            f"POSS controls={poss_ep['control_count']:2d} "
            f"continuous-extremes={poss_ep['matched_peer_extreme_continuous_metric_count']} "
            f"count-hi={poss_ep['matched_peer_count_metric_ge95_count']} | "
            f"DASCH controls={dasch_ep['control_count']:2d} "
            f"continuous-extremes={dasch_ep['matched_peer_extreme_continuous_metric_count']} "
            f"count-hi={dasch_ep['matched_peer_count_metric_ge95_count']}"
        )
        print(
            f"  POSS pct: ell={poss_ep['ellipticity_peer_percentile']:.1f} "
            f"sharp={poss_ep['peak_to_flux5_peer_percentile']:.1f} "
            f"conc={poss_ep['concentration_peer_percentile']:.1f} "
            f"cent={poss_ep['centroid_offset_peer_percentile']:.1f}"
        )
        print(
            f"  DASCH pct: ell={dasch_ep['ellipticity_peer_percentile']:.1f} "
            f"sharp={dasch_ep['peak_to_flux5_peer_percentile']:.1f} "
            f"conc={dasch_ep['concentration_peer_percentile']:.1f} "
            f"cent={dasch_ep['centroid_offset_peer_percentile']:.1f}"
        )

    write_csv(OUT_ENDPOINT, endpoint_rows, ENDPOINT_FIELDS)
    write_csv(OUT_CONTROL, control_rows, CONTROL_FIELDS)
    write_csv(OUT_SUMMARY, summaries, SUMMARY_FIELDS)

    report = {
        "status": "COMPLETE",
        "analysis_kind": "order61_discovery_plate_native_pixel_snr_matched_peer_audit_v028b",
        "guards": guards,
        "implementation_amendment": {
            "prior_worker": "run_order61_discovery_plate_peer_audit_v028.py",
            "failure_stage": "audit_display_extraction_before_first_endpoint_result",
            "prior_quantitative_endpoint_outcomes_produced": False,
            "change": (
                "optional 81x81 display extraction now NaN-pads unavailable edge pixels "
                "instead of requiring a full visual-only window"
            ),
            "scientific_morphology_function_changed": False,
            "peer_selection_changed": False,
            "snr_matching_changed": False,
            "candidate_gate_changed": False,
        },
        "fixed_peer_policy": {
            "same_tile": True,
            "same_polarity": True,
            "exclude_within_science_candidate_px": EXCLUSION_RADIUS_PX,
            "preferred_snr_ratio": list(PREFERRED_SNR_RATIO),
            "minimum_preferred_controls": MIN_PREFERRED_CONTROLS,
            "fallback_snr_ratio": list(FALLBACK_SNR_RATIO),
            "fallback_if_preferred_below_minimum": True,
            "last_resort_selection": "same tile/polarity sorted by abs(log SNR ratio), then distance",
            "maximum_controls": MAX_CONTROLS,
            "morphology_function": "unchanged from vet_order61_survivor_morphology_v028.py",
            "display_radius_px": DISPLAY_RADIUS_PX,
            "display_panels_are_audit_only": True,
            "matched_peer_extreme_definition": "continuous metric empirical percentile <=5 or >=95",
            "count_metric_high_definition": "empirical percentile >=95",
            "candidate_gate_changed": False,
            "detector_rerun": False,
        },
        "astrometry_closure": {
            "status": (
                "raw <=3 arcsec association retained; local systematic correction unavailable"
            ),
            "global_five_gaia_star_registration_is_context_only": True,
            "local_attempt_result": "insufficient Harvard references under all fixed local routes",
        },
        "per_rank": report_ranks,
        "detector_rerun": False,
        "candidate_pixels_read": True,
        "control_pixels_read": True,
        "candidate_deleted": False,
        "candidate_promoted": False,
        "next_stage": (
            "Review quantitative matched-peer morphology and audit panels together with "
            "existing injection/recovery and 0/1024 recurrence evidence. If a survivor is "
            "not morphologically exceptional in a defect-like direction, proceed to physical "
            "interpretation (station/parallax/illumination/motion) without altering detector gates."
        ),
        "outputs": {
            "endpoint_metrics_csv": str(OUT_ENDPOINT),
            "matched_controls_csv": str(OUT_CONTROL),
            "candidate_summary_csv": str(OUT_SUMMARY),
            "audit_directory": str(OUTDIR),
        },
    }
    write_json(OUT_REPORT, report)

    print()
    print("=" * 108)
    print("DISCOVERY-PLATE MATCHED-PEER AUDIT COMPLETE")
    print("=" * 108)
    print("Outputs:")
    print(" ", OUT_REPORT)
    print(" ", OUT_SUMMARY)
    print(" ", OUT_ENDPOINT)
    print(" ", OUT_CONTROL)
    print(" ", OUTDIR)
    print()
    print("No detector was rerun.")
    print("No candidate gate was changed.")
    print("No candidate was deleted or promoted.")


if __name__ == "__main__":
    main()
