#!/usr/bin/env python3
"""
ORDER 01 — POSS physical image-polarity consistency audit v028o

Motivation
----------
v028n revealed two separate facts:

1) DASCH has a coarse native scale (~12.6--13.2 arcsec/pixel), so integer-pixel
   Gaia centroid acceptance at <=5 arcsec was inappropriate.  That astrometric
   branch remains unresolved.

2) On POSS, the Gaia-guided measurements are highly asymmetric in sign:
   accepted ordinary Gaia stars are overwhelmingly positive raw-image
   excursions, whereas every frozen science POSS endpoint has detector
   polarity -1.

v028o tests whether that is merely a detector-sign convention or a real
physical contrast difference in the SAME frozen POSS science arrays.

For each frozen POSS science endpoint and its accepted Gaia stars:
  * read the same hashed native NPY tile;
  * evaluate raw center contrast;
  * evaluate min/max excursion in a 3-pixel core;
  * evaluate background-subtracted aperture flux at radii 2, 3, and 5 px;
  * evaluate Gaussian-weighted flux (sigma=2.5 px);
  * repeat the measurements with three independent local background annuli;
  * compare the science feature sign with Gaia stars measured by the identical
    metrics on the same tile.

SCIENCE PIXELS ARE READ.
No network access.
No transient detector rerun.
No candidate state mutation.
No promotion/deletion.
No weighted overall candidate score.

Physical interpretation boundary
--------------------------------
If ordinary stellar images are consistently positive in the same native array
while a candidate is robustly negative under multiple local measures, that
weighs against interpreting the candidate as an additional light source.
It does not by itself identify the instrumental/plate cause.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
import statistics
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path.cwd()
BASE = ROOT / "results" / "order01_native_full_v028"
WORK = ROOT / "work" / "order01_native_full_v028"

V028M = BASE / "order01_pixel_local_astrometry_v028m.json"
V028N = BASE / "order01_gaia_guided_local_astrometry_v028n.json"
STRICT = BASE / "order01_strict_match_triage_v028.csv"
POSS_CAND = BASE / "order01_poss_native_candidates.csv"
INJ = BASE / "order01_injection_recovery_report_v028.json"
GUIDED_ANCHORS = BASE / "order01_gaia_guided_anchor_measurements_v028n.csv"

POSS_TILE_DIR = WORK / "poss_tiles"

OUT_JSON = BASE / "order01_poss_physical_polarity_v028o.json"
OUT_CSV = BASE / "order01_poss_physical_polarity_v028o.csv"
OUT_CONTROLS = BASE / "order01_poss_physical_polarity_gaia_controls_v028o.csv"
OUT_MD = BASE / "ORDER01_POSS_PHYSICAL_POLARITY_V028O.md"

EXPECTED = [10, 24, 25, 26, 29, 30]
EXPECTED_SCIENCE_POLARITY = -1

# Multiple independent local background definitions.
ANNULI = [(9, 17), (12, 22), (16, 30)]
APERTURE_RADII = [2, 3, 5]
GAUSS_SIGMA_PX = 2.5
METRIC_RADIUS_PX = 35

MIN_LOCAL_GAIA_FOR_STRONG = 5
MIN_LOCAL_GAIA_FOR_DESCRIPTIVE = 3

# "Ordinary star sign" must be very one-sided before we call a science feature
# opposite to the stellar image polarity.
DOMINANT_STELLAR_SIGN_FRACTION = 0.90

# Science feature requires robust agreement across annulus choices.
MIN_SCIENCE_NEGATIVE_ANNULUS_FRACTION = 2 / 3

# A control Gaia row was already frozen as accepted by v028n.
PRIMARY_G_MAX = 18.0


def f(v: Any) -> float:
    return float(str(v).strip())


def i(v: Any) -> int:
    return int(float(str(v).strip()))


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def sha_file(path: Path, block=1024 * 1024) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        while True:
            b = fh.read(block)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def load_tile_inventory(tile_dir: Path) -> dict[str, dict[str, Any]]:
    out = {}
    for jp in sorted(tile_dir.glob("*.json")):
        try:
            obj = json.loads(jp.read_text(encoding="utf-8"))
        except Exception:
            continue
        if obj.get("complete") is not True:
            continue
        tid = str(obj.get("tile_id", "")).strip()
        ext = obj.get("extended")
        ref = obj.get("npy_path")
        if not tid or not isinstance(ext, list) or len(ext) != 4 or not ref:
            continue
        npy = Path(str(ref))
        if not npy.is_absolute():
            npy = ROOT / npy
        if not npy.is_file():
            raise RuntimeError(f"{tid}: missing NPY {npy}")
        actual = sha_file(npy)
        recorded = str(obj.get("npy_file_sha256") or "").strip().lower()
        if recorded and actual != recorded:
            raise RuntimeError(f"{tid}: NPY SHA mismatch")
        out[tid] = {
            "tile_id": tid,
            "extended": tuple(map(int, ext)),
            "npy_path": npy,
            "npy_sha256": actual,
            "meta_path": jp,
        }
    if not out:
        raise RuntimeError("no completed POSS tile metadata")
    return out


ARRAY_CACHE = {}


def load_array(meta: dict[str, Any]) -> np.ndarray:
    tid = meta["tile_id"]
    if tid in ARRAY_CACHE:
        return ARRAY_CACHE[tid]
    arr = np.load(meta["npy_path"], mmap_mode="r")
    ex0, ex1, ey0, ey1 = meta["extended"]
    expected = (ey1 - ey0, ex1 - ex0)
    if arr.ndim != 2 or tuple(arr.shape) != expected:
        raise RuntimeError(f"{tid}: NPY shape {arr.shape} != {expected}")
    ARRAY_CACHE[tid] = arr
    return arr


def robust_bg_sigma(vals: np.ndarray) -> tuple[float, float]:
    x = np.asarray(vals, dtype=float)
    x = x[np.isfinite(x)]
    if x.size < 100:
        raise RuntimeError(f"only {x.size} usable background pixels")
    med = float(np.median(x))
    mad = float(np.median(np.abs(x - med)))
    sigma = 1.4826 * mad
    if not math.isfinite(sigma) or sigma <= 0:
        sigma = float(np.std(x))
    if not math.isfinite(sigma) or sigma <= 0:
        raise RuntimeError("invalid local sigma")
    return med, sigma


def measure_at(
    meta: dict[str, Any],
    global_x: float,
    global_y: float,
) -> dict[str, Any]:
    arr = load_array(meta)
    ex0, ex1, ey0, ey1 = meta["extended"]
    lx = float(global_x) - ex0
    ly = float(global_y) - ey0

    ix = int(round(lx))
    iy = int(round(ly))
    r = METRIC_RADIUS_PX
    if (
        ix - r < 0 or iy - r < 0
        or ix + r >= arr.shape[1]
        or iy + r >= arr.shape[0]
    ):
        return {"status": "INSUFFICIENT_EDGE_MARGIN"}

    y0, y1 = iy - r, iy + r + 1
    x0, x1 = ix - r, ix + r + 1
    cut = np.asarray(arr[y0:y1, x0:x1], dtype=float)
    yy, xx = np.indices(cut.shape, dtype=float)
    cx = lx - x0
    cy = ly - y0
    rr = np.hypot(xx - cx, yy - cy)

    results = []
    for ann_in, ann_out in ANNULI:
        ann = cut[(rr >= ann_in) & (rr <= ann_out)]
        bg, sigma = robust_bg_sigma(ann)
        q = cut - bg

        # Exact rounded science/control center.
        cval = float(cut[iy - y0, ix - x0])
        center_z = (cval - bg) / sigma

        core = rr <= 3.0
        core_vals = q[core]
        max_z = float(np.nanmax(core_vals) / sigma)
        min_z = float(np.nanmin(core_vals) / sigma)
        chosen_core_sign = 1 if abs(max_z) >= abs(min_z) else -1
        chosen_core_abs_z = max(abs(max_z), abs(min_z))

        apertures = {}
        for ar in APERTURE_RADII:
            m = rr <= float(ar)
            flux = float(np.nansum(q[m]))
            npx = int(np.count_nonzero(m))
            # This is not a formal independent-pixel SNR; it is a signed
            # standardized aperture statistic for same-array comparison.
            std_flux = flux / (sigma * math.sqrt(max(npx, 1)))
            apertures[str(ar)] = {
                "flux_bgsub": flux,
                "pixel_count": npx,
                "standardized_flux": std_flux,
                "sign": 1 if flux > 0 else (-1 if flux < 0 else 0),
            }

        weights = np.exp(-0.5 * (rr / GAUSS_SIGMA_PX) ** 2)
        weights[rr > 3.5 * GAUSS_SIGMA_PX] = 0.0
        wf = float(np.nansum(q * weights))
        wnorm = sigma * math.sqrt(float(np.sum(weights * weights)))
        wz = wf / wnorm if wnorm > 0 else float("nan")

        results.append({
            "annulus_inner_px": ann_in,
            "annulus_outer_px": ann_out,
            "background": bg,
            "sigma": sigma,
            "center_z": center_z,
            "center_sign": 1 if center_z > 0 else (-1 if center_z < 0 else 0),
            "core_max_z": max_z,
            "core_min_z": min_z,
            "core_dominant_sign": chosen_core_sign,
            "core_dominant_abs_z": chosen_core_abs_z,
            "apertures": apertures,
            "gaussian_weighted_flux": wf,
            "gaussian_weighted_z": wz,
            "gaussian_weighted_sign": 1 if wf > 0 else (-1 if wf < 0 else 0),
        })

    def sign_fraction(extractor):
        signs = [extractor(q) for q in results]
        return {
            "positive_fraction": sum(s > 0 for s in signs) / len(signs),
            "negative_fraction": sum(s < 0 for s in signs) / len(signs),
            "zero_fraction": sum(s == 0 for s in signs) / len(signs),
            "signs": signs,
        }

    summary = {
        "center": sign_fraction(lambda q: q["center_sign"]),
        "core_dominant": sign_fraction(lambda q: q["core_dominant_sign"]),
        "gaussian_weighted": sign_fraction(lambda q: q["gaussian_weighted_sign"]),
    }
    for ar in APERTURE_RADII:
        summary[f"aperture_r{ar}"] = sign_fraction(
            lambda q, ar=ar: q["apertures"][str(ar)]["sign"]
        )

    # Median standardized metrics across background definitions.
    summary["median_center_z"] = statistics.median(
        q["center_z"] for q in results
    )
    summary["median_gaussian_weighted_z"] = statistics.median(
        q["gaussian_weighted_z"] for q in results
    )
    for ar in APERTURE_RADII:
        summary[f"median_aperture_r{ar}_standardized_flux"] = statistics.median(
            q["apertures"][str(ar)]["standardized_flux"] for q in results
        )

    return {
        "status": "MEASURED",
        "global_x": global_x,
        "global_y": global_y,
        "annulus_measurements": results,
        "sign_summary": summary,
    }


def exact_native(
    rows: list[dict[str, str]], tile_id: str, candidate_index: int
) -> dict[str, str]:
    hits = [
        r for r in rows
        if str(r.get("tile_id", "")) == tile_id
        and i(r["candidate_index"]) == candidate_index
    ]
    if len(hits) != 1:
        raise RuntimeError(
            f"{tile_id} candidate {candidate_index}: exact count={len(hits)}"
        )
    return hits[0]


def dominant_control_sign(
    controls: list[dict[str, Any]],
    metric: str,
) -> dict[str, Any]:
    signs = []
    vals = []
    for c in controls:
        m = c["measurement"]["sign_summary"]
        if metric == "gaussian_weighted":
            sf = m["gaussian_weighted"]
            sign = 1 if sf["positive_fraction"] > sf["negative_fraction"] else -1
            val = m["median_gaussian_weighted_z"]
        elif metric.startswith("aperture_r"):
            sf = m[metric]
            sign = 1 if sf["positive_fraction"] > sf["negative_fraction"] else -1
            val = m[f"median_{metric}_standardized_flux"]
        elif metric == "center":
            sf = m["center"]
            sign = 1 if sf["positive_fraction"] > sf["negative_fraction"] else -1
            val = m["median_center_z"]
        else:
            raise KeyError(metric)
        signs.append(sign)
        vals.append(val)

    if not signs:
        return {
            "count": 0,
            "positive_fraction": None,
            "negative_fraction": None,
            "dominant_sign": None,
            "median_standardized_value": None,
        }

    pf = sum(s > 0 for s in signs) / len(signs)
    nf = sum(s < 0 for s in signs) / len(signs)
    return {
        "count": len(signs),
        "positive_fraction": pf,
        "negative_fraction": nf,
        "dominant_sign": 1 if pf > nf else (-1 if nf > pf else 0),
        "median_standardized_value": statistics.median(vals),
    }


def science_metric_sign(science: dict[str, Any], metric: str) -> tuple[int, float]:
    s = science["sign_summary"]
    if metric == "gaussian_weighted":
        q = s["gaussian_weighted"]
        val = s["median_gaussian_weighted_z"]
    elif metric.startswith("aperture_r"):
        q = s[metric]
        val = s[f"median_{metric}_standardized_flux"]
    elif metric == "center":
        q = s["center"]
        val = s["median_center_z"]
    else:
        raise KeyError(metric)

    if q["negative_fraction"] >= MIN_SCIENCE_NEGATIVE_ANNULUS_FRACTION:
        sign = -1
    elif q["positive_fraction"] >= MIN_SCIENCE_NEGATIVE_ANNULUS_FRACTION:
        sign = 1
    else:
        sign = 0
    return sign, val


def main() -> int:
    print("=" * 126)
    print("ORDER 01 — POSS PHYSICAL IMAGE-POLARITY CONSISTENCY AUDIT v028o")
    print("=" * 126)
    print("SCIENCE PIXELS ARE READ. Frozen transient detector is NOT rerun.")
    print()

    for p in (V028M, V028N, STRICT, POSS_CAND, INJ, GUIDED_ANCHORS):
        if not p.is_file():
            print(f"FAIL: missing required input: {p}")
            return 2

    m = json.loads(V028M.read_text(encoding="utf-8"))
    n = json.loads(V028N.read_text(encoding="utf-8"))
    inj = json.loads(INJ.read_text(encoding="utf-8"))

    if m.get("frozen_active_ranks") != EXPECTED:
        print("FAIL: v028m frozen ranks mismatch")
        return 3
    if n.get("frozen_active_ranks") != EXPECTED:
        print("FAIL: v028n frozen ranks mismatch")
        return 3
    if n.get("guards", {}).get("science_pixels_read") is not True:
        print("FAIL: v028n guard mismatch")
        return 3

    strict = read_csv(STRICT)
    native = read_csv(POSS_CAND)
    guided = read_csv(GUIDED_ANCHORS)

    sr = {
        i(r["strict_rank"]): r
        for r in strict
        if i(r["strict_rank"]) in EXPECTED
    }
    if sorted(sr) != EXPECTED:
        raise RuntimeError("strict survivor set mismatch")

    inv = load_tile_inventory(POSS_TILE_DIR)

    inj_map = {}
    for e in inj.get("endpoint_summaries", []):
        try:
            rank = int(e["strict_rank"])
        except Exception:
            continue
        if rank in EXPECTED and str(e.get("archive")) == "POSS":
            inj_map[rank] = e

    # Verify hashes for all six science tiles before reading.
    for rank in EXPECTED:
        tid = str(sr[rank]["poss_tile_id"])
        if tid not in inv:
            raise RuntimeError(f"rank {rank}: missing tile metadata {tid}")
        e = inj_map.get(rank)
        if e is None:
            raise RuntimeError(f"rank {rank}: missing injection POSS endpoint")
        if str(e.get("tile_id")) != tid:
            raise RuntimeError(f"rank {rank}: injection tile mismatch")
        h = str(e.get("native_npy_sha256", "")).lower()
        if h and h != inv[tid]["npy_sha256"]:
            raise RuntimeError(f"rank {rank}: NPY SHA mismatch")

    print("Frozen POSS tile/hash guards: PASS")
    print()

    # Freeze the aggregate v028n POSS Gaia result before remeasurement.
    accepted_v028n = [
        r for r in guided
        if str(r.get("poss_accepted_guided_anchor", "")).lower() == "true"
    ]
    accepted_signs = Counter(i(r["poss_chosen_sign"]) for r in accepted_v028n)
    bright_v028n = [
        r for r in accepted_v028n
        if str(r.get("g_mag", "")).strip()
        and f(r["g_mag"]) <= PRIMARY_G_MAX
    ]
    bright_signs = Counter(i(r["poss_chosen_sign"]) for r in bright_v028n)

    print("Frozen v028n accepted POSS Gaia anchors:")
    print(f"  all:    N={len(accepted_v028n)} signs={dict(accepted_signs)}")
    print(
        f"  G<={PRIMARY_G_MAX:g}: N={len(bright_v028n)} "
        f"signs={dict(bright_signs)}"
    )
    print()

    control_rows = []
    results = []

    METRICS = [
        "center",
        "gaussian_weighted",
        "aperture_r2",
        "aperture_r3",
        "aperture_r5",
    ]

    print("Per-candidate same-tile physical polarity:")
    print("-" * 126)

    for rank in EXPECTED:
        s = sr[rank]
        tid = str(s["poss_tile_id"])
        cidx = i(s["poss_candidate_index"])
        exact = exact_native(native, tid, cidx)

        if i(exact["polarity"]) != EXPECTED_SCIENCE_POLARITY:
            raise RuntimeError(
                f"rank {rank}: expected POSS science polarity -1, "
                f"got {exact['polarity']}"
            )

        science = measure_at(
            inv[tid],
            f(exact["global_x"]),
            f(exact["global_y"]),
        )
        if science["status"] != "MEASURED":
            raise RuntimeError(f"rank {rank}: science measurement failed")

        # Same-rank accepted POSS Gaia anchors; primary control subset G<=18.
        grows = [
            r for r in guided
            if i(r["strict_rank"]) == rank
            and str(r.get("poss_accepted_guided_anchor", "")).lower() == "true"
            and str(r.get("poss_measured_global_x", "")).strip()
            and str(r.get("poss_measured_global_y", "")).strip()
        ]

        controls_all = []
        for g in grows:
            gm = (
                f(g["g_mag"])
                if str(g.get("g_mag", "")).strip()
                else None
            )
            meas = measure_at(
                inv[tid],
                f(g["poss_measured_global_x"]),
                f(g["poss_measured_global_y"]),
            )
            if meas["status"] != "MEASURED":
                continue
            rec = {
                "strict_rank": rank,
                "tile_id": tid,
                "source_id": str(g["source_id"]),
                "g_mag": gm,
                "v028n_chosen_sign": i(g["poss_chosen_sign"]),
                "v028n_abs_z": f(g["poss_chosen_abs_z"]),
                "v028n_gaia_sep_arcsec":
                    f(g["poss_gaia_to_measured_sep_arcsec"]),
                "measurement": meas,
            }
            controls_all.append(rec)

        controls_primary = [
            q for q in controls_all
            if q["g_mag"] is not None and q["g_mag"] <= PRIMARY_G_MAX
        ]
        if len(controls_primary) >= MIN_LOCAL_GAIA_FOR_DESCRIPTIVE:
            controls = controls_primary
            control_kind = f"SAME_TILE_GAIA_G_LE_{PRIMARY_G_MAX:g}"
        else:
            controls = controls_all
            control_kind = "SAME_TILE_ALL_ACCEPTED_GAIA_FALLBACK"

        metric_results = {}
        opposite_metrics = 0
        usable_metrics = 0
        for metric in METRICS:
            ctrl = dominant_control_sign(controls, metric)
            ssign, sval = science_metric_sign(science, metric)

            opposite = (
                ctrl["count"] > 0
                and ctrl["dominant_sign"] == 1
                and ctrl["positive_fraction"] is not None
                and ctrl["positive_fraction"]
                    >= DOMINANT_STELLAR_SIGN_FRACTION
                and ssign == -1
            )
            if ctrl["count"] > 0:
                usable_metrics += 1
            if opposite:
                opposite_metrics += 1

            metric_results[metric] = {
                "control": ctrl,
                "science_sign": ssign,
                "science_standardized_value": sval,
                "science_opposite_to_dominant_positive_stars": opposite,
            }

        if len(controls) >= MIN_LOCAL_GAIA_FOR_STRONG:
            evidence_strength = "STRONG_LOCAL_GAIA_CONTROL"
        elif len(controls) >= MIN_LOCAL_GAIA_FOR_DESCRIPTIVE:
            evidence_strength = "DESCRIPTIVE_LOCAL_GAIA_CONTROL"
        else:
            evidence_strength = "SPARSE_LOCAL_GAIA_CONTROL"

        if (
            usable_metrics >= 4
            and opposite_metrics >= 4
            and len(controls) >= MIN_LOCAL_GAIA_FOR_STRONG
        ):
            label = "ROBUSTLY_OPPOSITE_TO_LOCAL_GAIA_STELLAR_POLARITY"
        elif (
            usable_metrics >= 4
            and opposite_metrics >= 4
            and len(controls) >= MIN_LOCAL_GAIA_FOR_DESCRIPTIVE
        ):
            label = "DESCRIPTIVELY_OPPOSITE_TO_LOCAL_GAIA_STELLAR_POLARITY"
        elif opposite_metrics >= 3:
            label = "PARTIAL_OPPOSITE_STELLAR_POLARITY_EVIDENCE"
        else:
            label = "POSS_PHYSICAL_POLARITY_UNRESOLVED"

        ssum = science["sign_summary"]
        result = {
            "strict_rank": rank,
            "tile_id": tid,
            "candidate_index": cidx,
            "frozen_detector_polarity": i(exact["polarity"]),
            "global_x": f(exact["global_x"]),
            "global_y": f(exact["global_y"]),
            "science_measurement": science,
            "gaia_controls_all_count": len(controls_all),
            "gaia_controls_primary_count": len(controls_primary),
            "chosen_control_count": len(controls),
            "chosen_control_kind": control_kind,
            "control_evidence_strength": evidence_strength,
            "metric_results": metric_results,
            "opposite_metric_count": opposite_metrics,
            "usable_metric_count": usable_metrics,
            "physical_polarity_label": label,
        }
        results.append(result)

        for c in controls_all:
            flat = {
                "strict_rank": rank,
                "tile_id": tid,
                "source_id": c["source_id"],
                "g_mag": c["g_mag"],
                "v028n_chosen_sign": c["v028n_chosen_sign"],
                "v028n_abs_z": c["v028n_abs_z"],
                "v028n_gaia_sep_arcsec": c["v028n_gaia_sep_arcsec"],
            }
            ms = c["measurement"]["sign_summary"]
            flat.update({
                "median_center_z": ms["median_center_z"],
                "median_gaussian_weighted_z":
                    ms["median_gaussian_weighted_z"],
                "median_aperture_r2_standardized_flux":
                    ms["median_aperture_r2_standardized_flux"],
                "median_aperture_r3_standardized_flux":
                    ms["median_aperture_r3_standardized_flux"],
                "median_aperture_r5_standardized_flux":
                    ms["median_aperture_r5_standardized_flux"],
            })
            control_rows.append(flat)

        scvals = [
            metric_results[k]["science_standardized_value"]
            for k in METRICS
        ]
        cfracs = [
            metric_results[k]["control"]["positive_fraction"]
            for k in METRICS
            if metric_results[k]["control"]["positive_fraction"] is not None
        ]
        print(
            f"#{rank:>2} controls={len(controls):>2}({control_kind}) "
            f"science detector=-1 "
            f"centerZ={ssum['median_center_z']:+.2f} "
            f"gaussZ={ssum['median_gaussian_weighted_z']:+.2f} "
            f"ap3={ssum['median_aperture_r3_standardized_flux']:+.2f} "
            f"stellar_positive="
            f"{('n/a' if not cfracs else f'{100*statistics.median(cfracs):.1f}%')} "
            f"opposite_metrics={opposite_metrics}/{usable_metrics} "
            f"{label}"
        )

    payload = {
        "stage": "ORDER01_POSS_PHYSICAL_POLARITY_V028O",
        "inputs": {
            "pixel_astrometry_v028m": str(V028M.relative_to(ROOT)),
            "gaia_guided_astrometry_v028n": str(V028N.relative_to(ROOT)),
            "strict_triage": str(STRICT.relative_to(ROOT)),
            "poss_native_candidates": str(POSS_CAND.relative_to(ROOT)),
            "injection_report": str(INJ.relative_to(ROOT)),
            "guided_anchor_measurements": str(GUIDED_ANCHORS.relative_to(ROOT)),
        },
        "frozen_active_ranks": EXPECTED,
        "guards": {
            "network_access": False,
            "science_pixels_read": True,
            "npy_arrays_loaded": True,
            "transient_detector_rerun": False,
            "transient_detector_parameters_changed": False,
            "candidate_state_mutation": False,
            "candidate_promotion": False,
            "candidate_deletion": False,
            "weighted_candidate_score": False,
        },
        "v028n_poss_gaia_anchor_freeze": {
            "all_accepted_count": len(accepted_v028n),
            "all_accepted_sign_counts": dict(accepted_signs),
            f"g_le_{PRIMARY_G_MAX:g}_count": len(bright_v028n),
            f"g_le_{PRIMARY_G_MAX:g}_sign_counts": dict(bright_signs),
        },
        "declared_parameters": {
            "background_annuli_px": ANNULI,
            "aperture_radii_px": APERTURE_RADII,
            "gaussian_sigma_px": GAUSS_SIGMA_PX,
            "dominant_stellar_sign_fraction":
                DOMINANT_STELLAR_SIGN_FRACTION,
            "science_negative_annulus_fraction":
                MIN_SCIENCE_NEGATIVE_ANNULUS_FRACTION,
            "primary_g_max": PRIMARY_G_MAX,
        },
        "results": results,
        "interpretive_boundary": (
            "A robust opposite sign between ordinary stellar images and a "
            "candidate in the same native POSS array weighs against the candidate "
            "being an additional light source, but does not identify the physical "
            "artifact mechanism."
        ),
    }
    OUT_JSON.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    fields = [
        "strict_rank",
        "tile_id",
        "candidate_index",
        "frozen_detector_polarity",
        "gaia_controls_all_count",
        "gaia_controls_primary_count",
        "chosen_control_count",
        "chosen_control_kind",
        "control_evidence_strength",
        "median_center_z",
        "median_gaussian_weighted_z",
        "median_aperture_r2_standardized_flux",
        "median_aperture_r3_standardized_flux",
        "median_aperture_r5_standardized_flux",
        "center_stellar_positive_fraction",
        "gaussian_stellar_positive_fraction",
        "aperture_r2_stellar_positive_fraction",
        "aperture_r3_stellar_positive_fraction",
        "aperture_r5_stellar_positive_fraction",
        "opposite_metric_count",
        "usable_metric_count",
        "physical_polarity_label",
    ]
    with OUT_CSV.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        for r in results:
            ss = r["science_measurement"]["sign_summary"]
            mr = r["metric_results"]
            w.writerow({
                "strict_rank": r["strict_rank"],
                "tile_id": r["tile_id"],
                "candidate_index": r["candidate_index"],
                "frozen_detector_polarity": r["frozen_detector_polarity"],
                "gaia_controls_all_count": r["gaia_controls_all_count"],
                "gaia_controls_primary_count":
                    r["gaia_controls_primary_count"],
                "chosen_control_count": r["chosen_control_count"],
                "chosen_control_kind": r["chosen_control_kind"],
                "control_evidence_strength": r["control_evidence_strength"],
                "median_center_z": ss["median_center_z"],
                "median_gaussian_weighted_z":
                    ss["median_gaussian_weighted_z"],
                "median_aperture_r2_standardized_flux":
                    ss["median_aperture_r2_standardized_flux"],
                "median_aperture_r3_standardized_flux":
                    ss["median_aperture_r3_standardized_flux"],
                "median_aperture_r5_standardized_flux":
                    ss["median_aperture_r5_standardized_flux"],
                "center_stellar_positive_fraction":
                    mr["center"]["control"]["positive_fraction"],
                "gaussian_stellar_positive_fraction":
                    mr["gaussian_weighted"]["control"]["positive_fraction"],
                "aperture_r2_stellar_positive_fraction":
                    mr["aperture_r2"]["control"]["positive_fraction"],
                "aperture_r3_stellar_positive_fraction":
                    mr["aperture_r3"]["control"]["positive_fraction"],
                "aperture_r5_stellar_positive_fraction":
                    mr["aperture_r5"]["control"]["positive_fraction"],
                "opposite_metric_count": r["opposite_metric_count"],
                "usable_metric_count": r["usable_metric_count"],
                "physical_polarity_label": r["physical_polarity_label"],
            })

    control_fields = [
        "strict_rank",
        "tile_id",
        "source_id",
        "g_mag",
        "v028n_chosen_sign",
        "v028n_abs_z",
        "v028n_gaia_sep_arcsec",
        "median_center_z",
        "median_gaussian_weighted_z",
        "median_aperture_r2_standardized_flux",
        "median_aperture_r3_standardized_flux",
        "median_aperture_r5_standardized_flux",
    ]
    with OUT_CONTROLS.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=control_fields)
        w.writeheader()
        for r in control_rows:
            w.writerow(r)

    md = []
    md.append("# ORDER 01 — POSS Physical Image-Polarity Audit v028o")
    md.append("")
    md.append("## Guard state")
    md.append("")
    md.append("**Science pixels were read.**")
    md.append("")
    md.append("- No network access.")
    md.append("- No transient detector rerun.")
    md.append("- No detector parameter change.")
    md.append("- No candidate promoted, deleted, or otherwise mutated.")
    md.append("")
    md.append("## Frozen v028n ordinary-star sign context")
    md.append("")
    md.append(
        f"- Accepted POSS Gaia anchors: **{len(accepted_v028n)}**; "
        f"sign counts `{dict(accepted_signs)}`."
    )
    md.append(
        f"- G≤{PRIMARY_G_MAX:g} accepted anchors: **{len(bright_v028n)}**; "
        f"sign counts `{dict(bright_signs)}`."
    )
    md.append("")
    md.append("## Results")
    md.append("")
    md.append(
        "| rank | controls | center Z | Gaussian Z | aperture r=3 | "
        "opposite metrics | label |"
    )
    md.append("|---:|---:|---:|---:|---:|---:|---|")
    for r in results:
        ss = r["science_measurement"]["sign_summary"]
        md.append(
            f"| #{r['strict_rank']} | {r['chosen_control_count']} | "
            f"{ss['median_center_z']:+.2f} | "
            f"{ss['median_gaussian_weighted_z']:+.2f} | "
            f"{ss['median_aperture_r3_standardized_flux']:+.2f} | "
            f"{r['opposite_metric_count']}/{r['usable_metric_count']} | "
            f"`{r['physical_polarity_label']}` |"
        )
    md.append("")
    md.append("## Interpretation boundary")
    md.append("")
    md.append(
        "This stage asks whether the POSS science feature has the same raw-image "
        "contrast as ordinary Gaia-tied stellar images in the same frozen array. "
        "A robust opposite sign weighs against an additional-light interpretation "
        "but does not identify the artifact mechanism."
    )
    OUT_MD.write_text("\n".join(md), encoding="utf-8")

    print()
    print("Outputs:")
    print(f"  {OUT_JSON}")
    print(f"  {OUT_CSV}")
    print(f"  {OUT_CONTROLS}")
    print(f"  {OUT_MD}")
    print()
    print("SCIENCE PIXELS WERE READ.")
    print("No network query was made.")
    print("No transient detector was rerun.")
    print("No candidate was promoted or deleted.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
