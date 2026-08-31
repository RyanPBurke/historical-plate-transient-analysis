#!/usr/bin/env python3
"""
ORDER 01 — pixel-derived local astrometric calibration v028m

This stage deliberately crosses the science-pixel-read boundary.

It DOES:
  * verify frozen native tile metadata + SHA256 before reading arrays;
  * memory-map only the discovery tiles containing the six frozen survivors;
  * construct a NEW, independent ordinary-source catalogue using a simple
    band-pass + local-extrema extractor (not the frozen transient detector);
  * reconstruct each tile's pixel->sky mapping from the already-frozen native
    candidate catalogue coordinates;
  * match independent ordinary-source detections between POSS and DASCH;
  * tie extracted sources to the already-frozen epoch-propagated Gaia rows
    where possible;
  * measure the candidate POSS->DASCH vector relative to local ordinary-source
    registration;
  * report the dominant independent-extractor sign combination.

It DOES NOT:
  * access the network;
  * rerun transient_pipeline.detector.detect_array;
  * alter detector thresholds;
  * add/remove/promote/delete candidates;
  * assign an overall candidate score.

The source extractor in this file is intentionally separate from the frozen
transient detector. Its only purpose is astrometric calibration/control.

Interpretation:
  Local astrometric consistency establishes positional compatibility only.
  It does not establish astrophysical reality.
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

try:
    from scipy.ndimage import gaussian_filter, maximum_filter, minimum_filter
    from scipy.spatial import cKDTree
except Exception as exc:
    raise SystemExit(
        "scipy is required for v028m independent source extraction: " + repr(exc)
    )

ROOT = Path.cwd()
BASE = ROOT / "results" / "order01_native_full_v028"
WORK = ROOT / "work" / "order01_native_full_v028"

V028K = BASE / "order01_discovery_exposure_overlap_freeze_v028k.json"
V028L = BASE / "order01_discovery_local_astrometry_v028l.json"
STRICT = BASE / "order01_strict_match_triage_v028.csv"
POSS_CAND = BASE / "order01_poss_native_candidates.csv"
DASCH_CAND = BASE / "order01_dasch_native_candidates.csv"
GAIA = BASE / "order01_gaia_source_candidates_v028b.csv"
INJ = BASE / "order01_injection_recovery_report_v028.json"

POSS_TILE_DIR = WORK / "poss_tiles"
DASCH_TILE_DIR = WORK / "dasch_tiles"

OUT_JSON = BASE / "order01_pixel_local_astrometry_v028m.json"
OUT_CSV = BASE / "order01_pixel_local_astrometry_v028m.csv"
OUT_MD = BASE / "ORDER01_PIXEL_LOCAL_ASTROMETRY_V028M.md"
OUT_EXTRACTED = BASE / "order01_pixel_local_astrometry_extracted_sources_v028m.csv"
OUT_CONTROLS = BASE / "order01_pixel_local_astrometry_controls_v028m.csv"

EXPECTED = [10, 24, 25, 26, 29, 30]

# Independent extractor parameters.
SMALL_GAUSS_SIGMA_PX = 1.0
BROAD_GAUSS_SIGMA_PX = 12.0
LOCAL_EXTREMA_SIZE_PX = 7
EDGE_EXCLUSION_PX = 24
EXTRACT_MIN_SIGMA = 5.0
MAX_EXTRACTED_PER_TILE = 12000

# Registration-control parameters.
LOCAL_CONTROL_RADIUS_ARCSEC = 900.0
SCIENCE_EXCLUSION_ARCSEC = 20.0
CROSSMATCH_RADIUS_ARCSEC = 5.0
THRESHOLDS = [8.0, 6.0, 5.0]
MIN_STRONG_CONTROLS = 30
MIN_DESCRIPTIVE_CONTROLS = 10

# Gaia tie.
GAIA_MATCH_RADIUS_ARCSEC = 5.0
GAIA_STRONG_RADIUS_ARCSEC = 3.0
MIN_GAIA_CROSS_ARCHIVE_ANCHORS = 5

# Pixel->sky reconstruction.
POLY_DEGREES = [1, 2, 3]
MAX_ACCEPTABLE_WCS_RECON_P95_ARCSEC = 0.35

EXPECTED_POSS_POLARITY = -1
EXPECTED_DASCH_POLARITY = 1


def sha_file(path: Path, block=1024 * 1024) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        while True:
            b = fh.read(block)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def f(v: Any) -> float:
    return float(str(v).strip())


def i(v: Any) -> int:
    return int(float(str(v).strip()))


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def tangent_vector(
    ra1: float, dec1: float, ra2: float, dec2: float
) -> tuple[float, float, float, float]:
    dec0 = 0.5 * (dec1 + dec2)
    dx = (ra2 - ra1) * 3600.0 * math.cos(math.radians(dec0))
    dy = (dec2 - dec1) * 3600.0
    sep = math.hypot(dx, dy)
    pa = math.degrees(math.atan2(dx, dy)) % 360.0
    return dx, dy, sep, pa


def tangent_xy(
    ra: np.ndarray | float,
    dec: np.ndarray | float,
    ra0: float,
    dec0: float,
):
    return (
        (np.asarray(ra) - ra0) * 3600.0 * math.cos(math.radians(dec0)),
        (np.asarray(dec) - dec0) * 3600.0,
    )


def percentile_le(values: list[float], x: float) -> float | None:
    if not values:
        return None
    return sum(v <= x for v in values) / len(values)


def robust_sigma(values: np.ndarray) -> tuple[float, float]:
    vals = np.asarray(values, dtype=float)
    vals = vals[np.isfinite(vals)]
    if vals.size == 0:
        raise RuntimeError("no finite pixels for robust sigma")
    med = float(np.median(vals))
    mad = float(np.median(np.abs(vals - med)))
    sig = 1.4826 * mad
    if not math.isfinite(sig) or sig <= 0:
        sig = float(np.std(vals))
    if not math.isfinite(sig) or sig <= 0:
        raise RuntimeError("non-positive robust pixel sigma")
    return med, sig


def poly_terms(x: np.ndarray, y: np.ndarray, degree: int) -> np.ndarray:
    cols = [np.ones_like(x)]
    for total in range(1, degree + 1):
        for xp in range(total, -1, -1):
            yp = total - xp
            cols.append((x ** xp) * (y ** yp))
    return np.column_stack(cols)


class PixelSkyModel:
    def __init__(
        self,
        x0: float,
        y0: float,
        scale: float,
        ra0: float,
        dec0: float,
        degree: int,
        coef_x: np.ndarray,
        coef_y: np.ndarray,
        validation: dict[str, Any],
    ):
        self.x0 = x0
        self.y0 = y0
        self.scale = scale
        self.ra0 = ra0
        self.dec0 = dec0
        self.degree = degree
        self.coef_x = coef_x
        self.coef_y = coef_y
        self.validation = validation

    def sky(self, gx, gy):
        xa = (np.asarray(gx, dtype=float) - self.x0) / self.scale
        ya = (np.asarray(gy, dtype=float) - self.y0) / self.scale
        A = poly_terms(np.atleast_1d(xa), np.atleast_1d(ya), self.degree)
        sx = A @ self.coef_x
        sy = A @ self.coef_y
        ra = self.ra0 + sx / (
            3600.0 * math.cos(math.radians(self.dec0))
        )
        dec = self.dec0 + sy / 3600.0
        if np.ndim(gx) == 0:
            return float(ra[0]), float(dec[0])
        return ra, dec


def fit_pixel_sky(rows: list[dict[str, str]], tile_id: str) -> PixelSkyModel:
    pts = []
    for r in rows:
        if str(r.get("tile_id", "")) != tile_id:
            continue
        try:
            pts.append((
                f(r["global_x"]), f(r["global_y"]),
                f(r["ra_deg"]), f(r["dec_deg"])
            ))
        except Exception:
            continue

    if len(pts) < 30:
        raise RuntimeError(f"{tile_id}: only {len(pts)} WCS reconstruction rows")

    arr = np.asarray(pts, dtype=float)
    gx, gy, ra, dec = arr.T
    x0 = float(np.median(gx))
    y0 = float(np.median(gy))
    scale = max(float(np.ptp(gx)), float(np.ptp(gy)), 512.0) / 2.0
    ra0 = float(np.median(ra))
    dec0 = float(np.median(dec))

    tx, ty = tangent_xy(ra, dec, ra0, dec0)

    order = np.lexsort((gy, gx))
    holdout = np.zeros(len(arr), dtype=bool)
    holdout[order[::5]] = True
    if np.count_nonzero(~holdout) < 20 or np.count_nonzero(holdout) < 5:
        holdout[:] = False
        holdout[order[::7]] = True

    xn = (gx - x0) / scale
    yn = (gy - y0) / scale

    trials = []
    best = None
    for degree in POLY_DEGREES:
        A = poly_terms(xn, yn, degree)
        train = ~holdout
        test = holdout

        cx, *_ = np.linalg.lstsq(A[train], tx[train], rcond=None)
        cy, *_ = np.linalg.lstsq(A[train], ty[train], rcond=None)

        predx = A[test] @ cx
        predy = A[test] @ cy
        resid = np.hypot(predx - tx[test], predy - ty[test])

        trial = {
            "degree": degree,
            "train_count": int(np.count_nonzero(train)),
            "validation_count": int(np.count_nonzero(test)),
            "validation_median_arcsec": float(np.median(resid)),
            "validation_p95_arcsec": float(np.quantile(resid, 0.95)),
            "validation_max_arcsec": float(np.max(resid)),
        }
        trials.append(trial)

        if best is None or trial["validation_p95_arcsec"] < best[0]:
            best = (trial["validation_p95_arcsec"], degree, cx, cy, trial)

        if trial["validation_p95_arcsec"] <= 0.05:
            best = (trial["validation_p95_arcsec"], degree, cx, cy, trial)
            break

    assert best is not None
    _, degree, _, _, chosen_trial = best

    # Refit chosen degree to every available coordinate row.
    A = poly_terms(xn, yn, degree)
    cx, *_ = np.linalg.lstsq(A, tx, rcond=None)
    cy, *_ = np.linalg.lstsq(A, ty, rcond=None)

    validation = {
        "tile_id": tile_id,
        "input_coordinate_rows": len(pts),
        "trials": trials,
        "chosen_degree": degree,
        "chosen_validation_p95_arcsec":
            chosen_trial["validation_p95_arcsec"],
        "acceptable": (
            chosen_trial["validation_p95_arcsec"]
            <= MAX_ACCEPTABLE_WCS_RECON_P95_ARCSEC
        ),
    }
    return PixelSkyModel(
        x0, y0, scale, ra0, dec0, degree, cx, cy, validation
    )


def load_tile_inventory(tile_dir: Path, archive: str) -> dict[str, dict[str, Any]]:
    if not tile_dir.is_dir():
        raise RuntimeError(f"missing tile directory: {tile_dir}")

    out = {}
    for jp in sorted(tile_dir.glob("*.json")):
        try:
            obj = json.loads(jp.read_text(encoding="utf-8"))
        except Exception:
            continue
        if obj.get("complete") is not True:
            continue

        tid = str(obj.get("tile_id", "")).strip()
        core = obj.get("core")
        ext = obj.get("extended")
        ref = obj.get("npy_path")
        if (
            not tid
            or not isinstance(core, list) or len(core) != 4
            or not isinstance(ext, list) or len(ext) != 4
            or not ref
        ):
            continue

        npy = Path(str(ref))
        if not npy.is_absolute():
            npy = ROOT / npy
        if not npy.is_file():
            raise RuntimeError(f"{archive} {tid}: missing NPY {npy}")

        actual = sha_file(npy)
        recorded = str(obj.get("npy_file_sha256") or "").strip().lower()
        if recorded and recorded != actual:
            raise RuntimeError(
                f"{archive} {tid}: NPY SHA mismatch "
                f"recorded={recorded} actual={actual}"
            )

        if tid in out:
            raise RuntimeError(f"{archive}: duplicate tile metadata {tid}")

        out[tid] = {
            "archive": archive,
            "tile_id": tid,
            "core": tuple(map(int, core)),
            "extended": tuple(map(int, ext)),
            "shape": tuple(map(int, obj.get("shape", []))),
            "npy_path": npy,
            "npy_sha256": actual,
            "meta_path": jp,
        }

    if not out:
        raise RuntimeError(f"{archive}: no completed tile metadata")
    return out


def independent_extract(
    meta: dict[str, Any],
    model: PixelSkyModel,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    # THIS IS THE INTENTIONAL SCIENCE-PIXEL READ.
    arr = np.load(meta["npy_path"], mmap_mode="r")
    ex0, ex1, ey0, ey1 = meta["extended"]
    expected = (ey1 - ey0, ex1 - ex0)
    if arr.ndim != 2 or tuple(arr.shape) != expected:
        raise RuntimeError(
            f"{meta['archive']} {meta['tile_id']}: "
            f"NPY shape {arr.shape} != {expected}"
        )

    data = np.asarray(arr, dtype=np.float32)
    finite = np.isfinite(data)
    if not finite.any():
        raise RuntimeError(f"{meta['tile_id']}: no finite pixels")
    fill = float(np.nanmedian(data))
    if not finite.all():
        data = data.copy()
        data[~finite] = fill

    small = gaussian_filter(data, SMALL_GAUSS_SIGMA_PX, mode="nearest")
    broad = gaussian_filter(data, BROAD_GAUSS_SIGMA_PX, mode="nearest")
    bp = small - broad

    med, sigma = robust_sigma(bp)
    z = (bp - med) / sigma

    maxf = maximum_filter(z, size=LOCAL_EXTREMA_SIZE_PX, mode="nearest")
    minf = minimum_filter(z, size=LOCAL_EXTREMA_SIZE_PX, mode="nearest")

    pos = (z == maxf) & (z >= EXTRACT_MIN_SIGMA)
    neg = (z == minf) & (z <= -EXTRACT_MIN_SIGMA)

    edge = EDGE_EXCLUSION_PX
    if edge > 0:
        mask = np.zeros(z.shape, dtype=bool)
        mask[edge:-edge, edge:-edge] = True
        pos &= mask
        neg &= mask

    yy_p, xx_p = np.nonzero(pos)
    yy_n, xx_n = np.nonzero(neg)

    recs = []
    for yy, xx, sign in [
        *[(int(y), int(x), 1) for y, x in zip(yy_p, xx_p)],
        *[(int(y), int(x), -1) for y, x in zip(yy_n, xx_n)],
    ]:
        sig = float(abs(z[yy, xx]))
        recs.append({
            "archive": meta["archive"],
            "tile_id": meta["tile_id"],
            "local_x": xx,
            "local_y": yy,
            "global_x": ex0 + xx,
            "global_y": ey0 + yy,
            "extractor_sign": sign,
            "extractor_sigma": sig,
            "bandpass_value": float(bp[yy, xx]),
        })

    recs.sort(key=lambda r: (-r["extractor_sigma"], r["global_y"], r["global_x"]))
    if len(recs) > MAX_EXTRACTED_PER_TILE:
        recs = recs[:MAX_EXTRACTED_PER_TILE]

    if recs:
        gx = np.asarray([r["global_x"] for r in recs], dtype=float)
        gy = np.asarray([r["global_y"] for r in recs], dtype=float)
        ra, dec = model.sky(gx, gy)
        for r, rr, dd in zip(recs, ra, dec):
            r["ra_deg"] = float(rr)
            r["dec_deg"] = float(dd)

    diag = {
        "archive": meta["archive"],
        "tile_id": meta["tile_id"],
        "npy_path": str(meta["npy_path"]),
        "npy_sha256": meta["npy_sha256"],
        "array_shape": list(arr.shape),
        "bandpass_median": med,
        "bandpass_robust_sigma": sigma,
        "extract_min_sigma": EXTRACT_MIN_SIGMA,
        "extracted_count": len(recs),
        "positive_count": sum(r["extractor_sign"] > 0 for r in recs),
        "negative_count": sum(r["extractor_sign"] < 0 for r in recs),
        "count_ge8sigma": sum(r["extractor_sigma"] >= 8 for r in recs),
        "count_ge6sigma": sum(r["extractor_sigma"] >= 6 for r in recs),
        "count_ge5sigma": sum(r["extractor_sigma"] >= 5 for r in recs),
        "pixel_sky_model": model.validation,
    }
    return recs, diag


def nearest_mutual_matches(
    p: list[dict[str, Any]],
    d: list[dict[str, Any]],
    ra0: float,
    dec0: float,
    max_sep: float,
) -> list[dict[str, Any]]:
    if not p or not d:
        return []

    px, py = tangent_xy(
        np.asarray([x["ra_deg"] for x in p]),
        np.asarray([x["dec_deg"] for x in p]),
        ra0, dec0
    )
    dx, dy = tangent_xy(
        np.asarray([x["ra_deg"] for x in d]),
        np.asarray([x["dec_deg"] for x in d]),
        ra0, dec0
    )
    pp = np.column_stack([px, py])
    dd = np.column_stack([dx, dy])

    td = cKDTree(dd)
    tp = cKDTree(pp)
    pdist, pidx = td.query(pp, k=1)
    ddist, didx = tp.query(dd, k=1)

    out = []
    for pi, (di, dist) in enumerate(zip(pidx, pdist)):
        di = int(di)
        if dist > max_sep:
            continue
        if int(didx[di]) != pi:
            continue

        a, b = p[pi], d[di]
        vx, vy, sep, pa = tangent_vector(
            a["ra_deg"], a["dec_deg"],
            b["ra_deg"], b["dec_deg"]
        )
        mx = 0.5 * (float(px[pi]) + float(dx[di]))
        my = 0.5 * (float(py[pi]) + float(dy[di]))

        out.append({
            "poss_tile_id": a["tile_id"],
            "dasch_tile_id": b["tile_id"],
            "poss_global_x": a["global_x"],
            "poss_global_y": a["global_y"],
            "dasch_global_x": b["global_x"],
            "dasch_global_y": b["global_y"],
            "poss_extractor_sign": a["extractor_sign"],
            "dasch_extractor_sign": b["extractor_sign"],
            "poss_extractor_sigma": a["extractor_sigma"],
            "dasch_extractor_sigma": b["extractor_sigma"],
            "poss_ra_deg": a["ra_deg"],
            "poss_dec_deg": a["dec_deg"],
            "dasch_ra_deg": b["ra_deg"],
            "dasch_dec_deg": b["dec_deg"],
            "dx_east_arcsec": vx,
            "dy_north_arcsec": vy,
            "separation_arcsec": sep,
            "position_angle_deg_east_of_north": pa,
            "mid_radius_from_science_arcsec": math.hypot(mx, my),
            "sign_pair": f"{a['extractor_sign']:+d},{b['extractor_sign']:+d}",
        })
    return out


def summarise_controls(
    rows: list[dict[str, Any]],
    science_dx: float,
    science_dy: float,
) -> dict[str, Any]:
    if not rows:
        return {
            "count": 0,
            "median_dx_east_arcsec": None,
            "median_dy_north_arcsec": None,
            "candidate_residual_from_control_median_arcsec": None,
            "candidate_residual_empirical_percentile": None,
            "dominant_sign_pair": None,
            "dominant_sign_fraction": None,
        }

    xs = [f(r["dx_east_arcsec"]) for r in rows]
    ys = [f(r["dy_north_arcsec"]) for r in rows]
    mdx = statistics.median(xs)
    mdy = statistics.median(ys)
    residuals = [
        math.hypot(x - mdx, y - mdy)
        for x, y in zip(xs, ys)
    ]
    science_resid = math.hypot(science_dx - mdx, science_dy - mdy)
    signs = Counter(str(r["sign_pair"]) for r in rows)
    dom_pair, dom_count = signs.most_common(1)[0]

    return {
        "count": len(rows),
        "median_dx_east_arcsec": mdx,
        "median_dy_north_arcsec": mdy,
        "median_translation_magnitude_arcsec": math.hypot(mdx, mdy),
        "median_pair_separation_arcsec":
            statistics.median(f(r["separation_arcsec"]) for r in rows),
        "p90_pair_separation_arcsec":
            float(np.quantile([f(r["separation_arcsec"]) for r in rows], 0.90)),
        "p95_pair_separation_arcsec":
            float(np.quantile([f(r["separation_arcsec"]) for r in rows], 0.95)),
        "median_control_residual_arcsec": statistics.median(residuals),
        "p90_control_residual_arcsec": float(np.quantile(residuals, 0.90)),
        "p95_control_residual_arcsec": float(np.quantile(residuals, 0.95)),
        "candidate_residual_from_control_median_arcsec": science_resid,
        "candidate_residual_empirical_percentile":
            percentile_le(residuals, science_resid),
        "dominant_sign_pair": dom_pair,
        "dominant_sign_count": dom_count,
        "dominant_sign_fraction": dom_count / len(rows),
        "sign_pair_counts": dict(signs),
    }


def gaia_matches_one_archive(
    sources: list[dict[str, Any]],
    gaia_rows: list[dict[str, str]],
    ra0: float,
    dec0: float,
) -> dict[str, dict[str, Any]]:
    if not sources:
        return {}

    sx, sy = tangent_xy(
        np.asarray([r["ra_deg"] for r in sources]),
        np.asarray([r["dec_deg"] for r in sources]),
        ra0, dec0
    )
    pts = np.column_stack([sx, sy])
    tree = cKDTree(pts)

    out = {}
    used = set()
    # Prefer brighter Gaia rows where g is known.
    ordered = sorted(
        gaia_rows,
        key=lambda g: (
            f(g["g_mag"]) if str(g.get("g_mag", "")).strip() else 99.0,
            str(g.get("source_id", ""))
        )
    )

    for g in ordered:
        try:
            sid = str(g["source_id"])
            gra = f(g["ra_target_deg"])
            gdec = f(g["dec_target_deg"])
        except Exception:
            continue
        gx, gy = tangent_xy(gra, gdec, ra0, dec0)
        dist, idx = tree.query([float(gx), float(gy)], k=1)
        idx = int(idx)
        dist = float(dist)
        if dist > GAIA_MATCH_RADIUS_ARCSEC or idx in used:
            continue
        used.add(idx)
        s = sources[idx]
        vx = float(sx[idx] - gx)
        vy = float(sy[idx] - gy)
        out[sid] = {
            "source_id": sid,
            "gaia_ra_target_deg": gra,
            "gaia_dec_target_deg": gdec,
            "gaia_g_mag": (
                f(g["g_mag"])
                if str(g.get("g_mag", "")).strip() else None
            ),
            "gaia_propagated": str(g.get("propagated", "")),
            "extract_ra_deg": s["ra_deg"],
            "extract_dec_deg": s["dec_deg"],
            "extractor_sign": s["extractor_sign"],
            "extractor_sigma": s["extractor_sigma"],
            "offset_east_arcsec": vx,
            "offset_north_arcsec": vy,
            "separation_arcsec": dist,
            "strong_within3": dist <= GAIA_STRONG_RADIUS_ARCSEC,
        }
    return out


def exact_native_candidate(
    rows: list[dict[str, str]], tile_id: str, candidate_index: int
) -> dict[str, str]:
    hits = [
        r for r in rows
        if str(r.get("tile_id", "")) == tile_id
        and i(r["candidate_index"]) == candidate_index
    ]
    if len(hits) != 1:
        raise RuntimeError(
            f"{tile_id} candidate {candidate_index}: exact native count={len(hits)}"
        )
    return hits[0]


def nearest_extracted_pixel(
    sources: list[dict[str, Any]], gx: float, gy: float
) -> dict[str, Any] | None:
    if not sources:
        return None
    q = min(
        sources,
        key=lambda r: math.hypot(r["global_x"] - gx, r["global_y"] - gy)
    )
    dist = math.hypot(q["global_x"] - gx, q["global_y"] - gy)
    return {
        "pixel_distance": dist,
        "extractor_sign": q["extractor_sign"],
        "extractor_sigma": q["extractor_sigma"],
        "global_x": q["global_x"],
        "global_y": q["global_y"],
        "within_5px": dist <= 5.0,
    }


def choose_control_tier(summaries: dict[str, dict[str, Any]]) -> tuple[str | None, str]:
    for t in ("8", "6", "5"):
        if summaries[t]["count"] >= MIN_STRONG_CONTROLS:
            return t, "STRONG_CONTROL_SAMPLE"
    for t in ("8", "6", "5"):
        if summaries[t]["count"] >= MIN_DESCRIPTIVE_CONTROLS:
            return t, "DESCRIPTIVE_CONTROL_SAMPLE"
    return None, "INSUFFICIENT_PIXEL_DERIVED_CONTROLS"


def label_from_summary(
    tier: str | None,
    strength: str,
    summary: dict[str, Any] | None,
    wcs_ok: bool,
) -> str:
    if not wcs_ok:
        return "PIXEL_SKY_RECONSTRUCTION_QUALITY_INSUFFICIENT"
    if tier is None or summary is None:
        return "INSUFFICIENT_PIXEL_DERIVED_ASTROMETRIC_CONTROLS"

    pct = summary["candidate_residual_empirical_percentile"]
    if pct is None:
        return "INSUFFICIENT_PIXEL_DERIVED_ASTROMETRIC_CONTROLS"

    if strength == "STRONG_CONTROL_SAMPLE":
        if pct <= 0.95:
            return "CONSISTENT_WITH_PIXEL_DERIVED_LOCAL_REGISTRATION"
        return "OUTSIDE_95PCT_PIXEL_DERIVED_LOCAL_REGISTRATION"

    if pct <= 0.95:
        return "DESCRIPTIVELY_CONSISTENT_WITH_PIXEL_DERIVED_LOCAL_REGISTRATION"
    return "DESCRIPTIVELY_HIGH_RESIDUAL_IN_PIXEL_DERIVED_LOCAL_REGISTRATION"


def main() -> int:
    print("=" * 126)
    print("ORDER 01 — PIXEL-DERIVED LOCAL ASTROMETRIC CALIBRATION v028m")
    print("=" * 126)
    print("NOTE: this stage intentionally READS frozen science NPY pixels.")
    print("      It does NOT rerun the frozen transient detector.")
    print()

    for p in (V028K, V028L, STRICT, POSS_CAND, DASCH_CAND, GAIA, INJ):
        if not p.is_file():
            print(f"FAIL: missing required input: {p}")
            return 2

    k = json.loads(V028K.read_text(encoding="utf-8"))
    l = json.loads(V028L.read_text(encoding="utf-8"))
    inj = json.loads(INJ.read_text(encoding="utf-8"))

    if k.get("frozen_active_ranks") != EXPECTED:
        print("FAIL: v028k survivor mismatch")
        return 3
    if l.get("frozen_active_ranks") != EXPECTED:
        print("FAIL: v028l survivor mismatch")
        return 3
    if any(
        r.get("local_astrometry_label")
        != "INSUFFICIENT_LOCAL_ASTROMETRIC_CONTROLS"
        for r in l.get("results", [])
    ):
        print("FAIL: v028m expected v028l to be unresolved for all six")
        return 3

    strict_rows = read_csv(STRICT)
    p_rows = read_csv(POSS_CAND)
    d_rows = read_csv(DASCH_CAND)
    gaia_rows = read_csv(GAIA)

    sr = {i(r["strict_rank"]): r for r in strict_rows if i(r["strict_rank"]) in EXPECTED}
    if sorted(sr) != EXPECTED:
        print("FAIL: strict survivor rows mismatch")
        return 4

    needed_p = {str(sr[r]["poss_tile_id"]) for r in EXPECTED}
    needed_d = {str(sr[r]["dasch_tile_id"]) for r in EXPECTED}

    p_inv_all = load_tile_inventory(POSS_TILE_DIR, "POSS")
    d_inv_all = load_tile_inventory(DASCH_TILE_DIR, "DASCH")

    for tid in needed_p:
        if tid not in p_inv_all:
            raise RuntimeError(f"missing POSS tile metadata {tid}")
    for tid in needed_d:
        if tid not in d_inv_all:
            raise RuntimeError(f"missing DASCH tile metadata {tid}")

    # Cross-check injection endpoint hashes against the tile inventories.
    inj_map = {}
    for e in inj.get("endpoint_summaries", []):
        try:
            rank = int(e["strict_rank"])
        except Exception:
            continue
        archive = str(e.get("archive", ""))
        if rank in EXPECTED and archive in ("POSS", "DASCH"):
            inj_map[(rank, archive)] = e

    for rank in EXPECTED:
        for archive, tid, inv in (
            ("POSS", str(sr[rank]["poss_tile_id"]), p_inv_all),
            ("DASCH", str(sr[rank]["dasch_tile_id"]), d_inv_all),
        ):
            e = inj_map.get((rank, archive))
            if e is None:
                raise RuntimeError(f"missing injection endpoint {rank} {archive}")
            if str(e.get("tile_id")) != tid:
                raise RuntimeError(f"{rank} {archive}: injection tile mismatch")
            rec = str(e.get("native_npy_sha256", "")).lower()
            if rec and rec != inv[tid]["npy_sha256"]:
                raise RuntimeError(f"{rank} {archive}: injection NPY SHA mismatch")

    print("Frozen tile/hash guards: PASS")
    print(f"  unique POSS tiles:  {len(needed_p)}")
    print(f"  unique DASCH tiles: {len(needed_d)}")
    print()

    # Fit pixel->sky models before reading science arrays.
    print("Reconstructing per-tile pixel -> sky mappings...")
    p_models = {tid: fit_pixel_sky(p_rows, tid) for tid in sorted(needed_p)}
    d_models = {tid: fit_pixel_sky(d_rows, tid) for tid in sorted(needed_d)}

    for archive, models in (("POSS", p_models), ("DASCH", d_models)):
        for tid, m in models.items():
            v = m.validation
            print(
                f"  {archive} {tid}: degree={v['chosen_degree']} "
                f"rows={v['input_coordinate_rows']} "
                f"holdout_p95={v['chosen_validation_p95_arcsec']:.4f}\" "
                f"acceptable={v['acceptable']}"
            )
    print()

    # Independent extraction.
    print("Independent ordinary-source extraction from frozen pixels...")
    extracted: dict[tuple[str, str], list[dict[str, Any]]] = {}
    extract_diag = {}

    for tid in sorted(needed_p):
        rows, diag = independent_extract(p_inv_all[tid], p_models[tid])
        extracted[("POSS", tid)] = rows
        extract_diag[f"POSS:{tid}"] = diag
        print(
            f"  POSS  {tid}: {len(rows)} extrema "
            f"(+{diag['positive_count']}/-{diag['negative_count']}; "
            f">=8s {diag['count_ge8sigma']}, >=6s {diag['count_ge6sigma']})"
        )

    for tid in sorted(needed_d):
        rows, diag = independent_extract(d_inv_all[tid], d_models[tid])
        extracted[("DASCH", tid)] = rows
        extract_diag[f"DASCH:{tid}"] = diag
        print(
            f"  DASCH {tid}: {len(rows)} extrema "
            f"(+{diag['positive_count']}/-{diag['negative_count']}; "
            f">=8s {diag['count_ge8sigma']}, >=6s {diag['count_ge6sigma']})"
        )
    print()

    gaia_by_rank = {r: [] for r in EXPECTED}
    for g in gaia_rows:
        try:
            rank = i(g["strict_rank"])
        except Exception:
            continue
        if rank in gaia_by_rank:
            gaia_by_rank[rank].append(g)

    results = []
    control_dump = []
    gaia_dump = []

    print("Per-candidate pixel-derived astrometry:")
    print("-" * 126)

    for rank in EXPECTED:
        s = sr[rank]
        ptid = str(s["poss_tile_id"])
        dtid = str(s["dasch_tile_id"])

        pnative = exact_native_candidate(p_rows, ptid, i(s["poss_candidate_index"]))
        dnative = exact_native_candidate(d_rows, dtid, i(s["dasch_candidate_index"]))

        # Native row coordinate guard.
        for label, native, tra, tdec in (
            ("POSS", pnative, f(s["poss_ra_deg"]), f(s["poss_dec_deg"])),
            ("DASCH", dnative, f(s["dasch_ra_deg"]), f(s["dasch_dec_deg"])),
        ):
            _, _, qsep, _ = tangent_vector(
                f(native["ra_deg"]), f(native["dec_deg"]), tra, tdec
            )
            if qsep > 1e-6:
                raise RuntimeError(
                    f"rank {rank} {label}: native/strict coordinate mismatch {qsep}\""
                )

        pra, pdec = f(s["poss_ra_deg"]), f(s["poss_dec_deg"])
        dra, ddec = f(s["dasch_ra_deg"]), f(s["dasch_dec_deg"])
        science_dx, science_dy, science_sep, science_pa = tangent_vector(
            pra, pdec, dra, ddec
        )
        ra0 = 0.5 * (pra + dra)
        dec0 = 0.5 * (pdec + ddec)

        psrc_all = extracted[("POSS", ptid)]
        dsrc_all = extracted[("DASCH", dtid)]

        # Science-independent extractor response at the endpoint pixel.
        pnear = nearest_extracted_pixel(
            psrc_all, f(pnative["global_x"]), f(pnative["global_y"])
        )
        dnear = nearest_extracted_pixel(
            dsrc_all, f(dnative["global_x"]), f(dnative["global_y"])
        )

        # Gaia ties on each archive.
        pg = gaia_matches_one_archive(
            psrc_all, gaia_by_rank[rank], ra0, dec0
        )
        dg = gaia_matches_one_archive(
            dsrc_all, gaia_by_rank[rank], ra0, dec0
        )
        common_gaia = sorted(set(pg) & set(dg))
        gaia_cross = []
        for sid in common_gaia:
            a, b = pg[sid], dg[sid]
            vx, vy, sep, pa = tangent_vector(
                a["extract_ra_deg"], a["extract_dec_deg"],
                b["extract_ra_deg"], b["extract_dec_deg"]
            )
            row = {
                "strict_rank": rank,
                "source_id": sid,
                "poss_gaia_sep_arcsec": a["separation_arcsec"],
                "dasch_gaia_sep_arcsec": b["separation_arcsec"],
                "poss_extractor_sign": a["extractor_sign"],
                "dasch_extractor_sign": b["extractor_sign"],
                "poss_extractor_sigma": a["extractor_sigma"],
                "dasch_extractor_sigma": b["extractor_sigma"],
                "dx_east_arcsec": vx,
                "dy_north_arcsec": vy,
                "separation_arcsec": sep,
                "position_angle_deg_east_of_north": pa,
            }
            gaia_cross.append(row)
            gaia_dump.append(row)

        gaia_summary = summarise_controls(
            gaia_cross, science_dx, science_dy
        )

        threshold_summaries = {}
        threshold_rows = {}
        for thresh in THRESHOLDS:
            psrc = [
                q for q in psrc_all
                if q["extractor_sigma"] >= thresh
            ]
            dsrc = [
                q for q in dsrc_all
                if q["extractor_sigma"] >= thresh
            ]

            matches = nearest_mutual_matches(
                psrc, dsrc, ra0, dec0, CROSSMATCH_RADIUS_ARCSEC
            )
            matches = [
                q for q in matches
                if q["mid_radius_from_science_arcsec"]
                <= LOCAL_CONTROL_RADIUS_ARCSEC
                and q["mid_radius_from_science_arcsec"]
                >= SCIENCE_EXCLUSION_ARCSEC
            ]

            # Requiring mutual nearest and a <=5" sky match is the source
            # identity control. No candidate/transient state is involved.
            threshold_rows[str(int(thresh))] = matches
            threshold_summaries[str(int(thresh))] = summarise_controls(
                matches, science_dx, science_dy
            )
            for q in matches:
                control_dump.append({
                    "strict_rank": rank,
                    "threshold_sigma": thresh,
                    **q,
                })

        tier, strength = choose_control_tier(threshold_summaries)
        chosen = threshold_summaries[tier] if tier else None

        # Dominant-sign refinement of the chosen tier.
        dominant_summary = None
        dominant_rows = []
        if tier and chosen and chosen["dominant_sign_pair"]:
            dom = chosen["dominant_sign_pair"]
            dominant_rows = [
                q for q in threshold_rows[tier] if q["sign_pair"] == dom
            ]
            dominant_summary = summarise_controls(
                dominant_rows, science_dx, science_dy
            )

        # Prefer dominant-sign subset only if it remains adequately populated.
        effective = chosen
        effective_kind = "ALL_SIGN_COMBINATIONS"
        if (
            dominant_summary is not None
            and dominant_summary["count"] >= MIN_DESCRIPTIVE_CONTROLS
            and chosen is not None
            and chosen["dominant_sign_fraction"] >= 0.60
        ):
            effective = dominant_summary
            effective_kind = "DOMINANT_INDEPENDENT_EXTRACTOR_SIGN_PAIR"

        wcs_ok = (
            p_models[ptid].validation["acceptable"]
            and d_models[dtid].validation["acceptable"]
        )
        label = label_from_summary(tier, strength, effective, wcs_ok)

        science_sign_pair_expected = (
            f"{EXPECTED_POSS_POLARITY:+d},{EXPECTED_DASCH_POLARITY:+d}"
        )
        dom_pair = chosen["dominant_sign_pair"] if chosen else None

        result = {
            "strict_rank": rank,
            "poss_tile_id": ptid,
            "dasch_tile_id": dtid,
            "science_poss_polarity": i(s["poss_polarity"]),
            "science_dasch_polarity": i(s["dasch_polarity"]),
            "science_pair_separation_arcsec": science_sep,
            "science_dx_east_arcsec": science_dx,
            "science_dy_north_arcsec": science_dy,
            "science_position_angle_deg_east_of_north": science_pa,
            "poss_pixel_sky_model_validation":
                p_models[ptid].validation,
            "dasch_pixel_sky_model_validation":
                d_models[dtid].validation,
            "poss_independent_extractor_nearest_science": pnear,
            "dasch_independent_extractor_nearest_science": dnear,
            "gaia_poss_anchor_count": len(pg),
            "gaia_dasch_anchor_count": len(dg),
            "gaia_cross_archive_anchor_count": len(gaia_cross),
            "gaia_cross_archive_summary": gaia_summary,
            "control_threshold_summaries": threshold_summaries,
            "chosen_control_threshold_sigma":
                (float(tier) if tier else None),
            "chosen_control_strength": strength,
            "chosen_control_effective_kind": effective_kind,
            "chosen_control_summary": effective,
            "chosen_all_sign_summary": chosen,
            "chosen_dominant_sign_summary": dominant_summary,
            "science_expected_sign_pair": science_sign_pair_expected,
            "dominant_independent_extractor_sign_pair": dom_pair,
            "science_sign_pair_matches_dominant_extractor_sign_pair":
                (dom_pair == science_sign_pair_expected if dom_pair else None),
            "local_astrometry_label": label,
        }
        results.append(result)

        def pct(v):
            return "n/a" if v is None else f"{100*v:.1f}%"

        eff_count = effective["count"] if effective else 0
        eff_pct = (
            effective["candidate_residual_empirical_percentile"]
            if effective else None
        )
        eff_resid = (
            effective["candidate_residual_from_control_median_arcsec"]
            if effective else None
        )
        print(
            f"#{rank:>2} raw={science_sep:.3f}\" "
            f"Gaia P/D/common={len(pg)}/{len(dg)}/{len(gaia_cross)} "
            f"control={tier or '-'}s:{eff_count} "
            f"resid={('n/a' if eff_resid is None else f'{eff_resid:.3f}\"')} "
            f"pct={pct(eff_pct)} "
            f"domsign={dom_pair or '-'} "
            f"science_extract="
            f"{('-' if not pnear else format(int(pnear['extractor_sign']), '+d'))}/"
            f"{('-' if not dnear else format(int(dnear['extractor_sign']), '+d'))} "
            f"{label}"
        )

    payload = {
        "stage": "ORDER01_PIXEL_LOCAL_ASTROMETRY_V028M",
        "inputs": {
            "overlap_freeze": str(V028K.relative_to(ROOT)),
            "previous_astrometry": str(V028L.relative_to(ROOT)),
            "strict_triage": str(STRICT.relative_to(ROOT)),
            "poss_native_candidates": str(POSS_CAND.relative_to(ROOT)),
            "dasch_native_candidates": str(DASCH_CAND.relative_to(ROOT)),
            "gaia_source_candidates": str(GAIA.relative_to(ROOT)),
            "injection_report": str(INJ.relative_to(ROOT)),
        },
        "frozen_active_ranks": EXPECTED,
        "guards": {
            "network_access": False,
            "science_pixels_read": True,
            "science_pixel_read_scope":
                "only frozen native NPY discovery tiles containing six survivors",
            "fits_pixels_read": False,
            "npy_arrays_loaded": True,
            "transient_detector_rerun": False,
            "transient_detector_parameters_changed": False,
            "candidate_promotion": False,
            "candidate_deletion": False,
            "candidate_state_mutation": False,
            "weighted_candidate_score": False,
        },
        "independent_extractor": {
            "purpose": "ordinary-source astrometric calibration only",
            "small_gaussian_sigma_px": SMALL_GAUSS_SIGMA_PX,
            "broad_gaussian_sigma_px": BROAD_GAUSS_SIGMA_PX,
            "local_extrema_size_px": LOCAL_EXTREMA_SIZE_PX,
            "edge_exclusion_px": EDGE_EXCLUSION_PX,
            "minimum_sigma": EXTRACT_MIN_SIGMA,
            "max_sources_per_tile": MAX_EXTRACTED_PER_TILE,
        },
        "registration_parameters": {
            "local_control_radius_arcsec": LOCAL_CONTROL_RADIUS_ARCSEC,
            "science_exclusion_arcsec": SCIENCE_EXCLUSION_ARCSEC,
            "crossmatch_radius_arcsec": CROSSMATCH_RADIUS_ARCSEC,
            "thresholds_sigma": THRESHOLDS,
            "min_strong_controls": MIN_STRONG_CONTROLS,
            "min_descriptive_controls": MIN_DESCRIPTIVE_CONTROLS,
            "gaia_match_radius_arcsec": GAIA_MATCH_RADIUS_ARCSEC,
            "gaia_strong_radius_arcsec": GAIA_STRONG_RADIUS_ARCSEC,
        },
        "tile_extraction_diagnostics": extract_diag,
        "results": results,
        "interpretive_boundary": (
            "This stage reads frozen science pixels to build an independent "
            "ordinary-source astrometric calibration set. It does not rerun the "
            "transient detector. Positional consistency does not establish "
            "astrophysical reality."
        ),
    }
    OUT_JSON.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False),
        encoding="utf-8"
    )

    # Compact candidate CSV.
    fields = [
        "strict_rank",
        "science_pair_separation_arcsec",
        "science_dx_east_arcsec",
        "science_dy_north_arcsec",
        "gaia_poss_anchor_count",
        "gaia_dasch_anchor_count",
        "gaia_cross_archive_anchor_count",
        "chosen_control_threshold_sigma",
        "chosen_control_strength",
        "chosen_control_effective_kind",
        "chosen_control_count",
        "chosen_control_median_dx_east_arcsec",
        "chosen_control_median_dy_north_arcsec",
        "candidate_residual_from_control_median_arcsec",
        "candidate_residual_empirical_percentile",
        "dominant_independent_extractor_sign_pair",
        "science_expected_sign_pair",
        "science_sign_pair_matches_dominant_extractor_sign_pair",
        "poss_science_independent_extractor_sign",
        "dasch_science_independent_extractor_sign",
        "local_astrometry_label",
    ]
    with OUT_CSV.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        for r in results:
            c = r["chosen_control_summary"] or {}
            pn = r["poss_independent_extractor_nearest_science"] or {}
            dn = r["dasch_independent_extractor_nearest_science"] or {}
            w.writerow({
                "strict_rank": r["strict_rank"],
                "science_pair_separation_arcsec":
                    r["science_pair_separation_arcsec"],
                "science_dx_east_arcsec": r["science_dx_east_arcsec"],
                "science_dy_north_arcsec": r["science_dy_north_arcsec"],
                "gaia_poss_anchor_count": r["gaia_poss_anchor_count"],
                "gaia_dasch_anchor_count": r["gaia_dasch_anchor_count"],
                "gaia_cross_archive_anchor_count":
                    r["gaia_cross_archive_anchor_count"],
                "chosen_control_threshold_sigma":
                    r["chosen_control_threshold_sigma"],
                "chosen_control_strength": r["chosen_control_strength"],
                "chosen_control_effective_kind":
                    r["chosen_control_effective_kind"],
                "chosen_control_count": c.get("count"),
                "chosen_control_median_dx_east_arcsec":
                    c.get("median_dx_east_arcsec"),
                "chosen_control_median_dy_north_arcsec":
                    c.get("median_dy_north_arcsec"),
                "candidate_residual_from_control_median_arcsec":
                    c.get("candidate_residual_from_control_median_arcsec"),
                "candidate_residual_empirical_percentile":
                    c.get("candidate_residual_empirical_percentile"),
                "dominant_independent_extractor_sign_pair":
                    r["dominant_independent_extractor_sign_pair"],
                "science_expected_sign_pair":
                    r["science_expected_sign_pair"],
                "science_sign_pair_matches_dominant_extractor_sign_pair":
                    r["science_sign_pair_matches_dominant_extractor_sign_pair"],
                "poss_science_independent_extractor_sign":
                    pn.get("extractor_sign"),
                "dasch_science_independent_extractor_sign":
                    dn.get("extractor_sign"),
                "local_astrometry_label": r["local_astrometry_label"],
            })

    # Extracted sources CSV.
    ext_fields = [
        "archive", "tile_id", "local_x", "local_y", "global_x", "global_y",
        "ra_deg", "dec_deg", "extractor_sign", "extractor_sigma",
        "bandpass_value",
    ]
    with OUT_EXTRACTED.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=ext_fields)
        w.writeheader()
        for key in sorted(extracted):
            for r in extracted[key]:
                w.writerow({k: r.get(k) for k in ext_fields})

    # Control rows CSV.
    ctrl_fields = [
        "strict_rank", "threshold_sigma",
        "poss_tile_id", "dasch_tile_id",
        "poss_global_x", "poss_global_y", "dasch_global_x", "dasch_global_y",
        "poss_extractor_sign", "dasch_extractor_sign",
        "poss_extractor_sigma", "dasch_extractor_sigma",
        "poss_ra_deg", "poss_dec_deg", "dasch_ra_deg", "dasch_dec_deg",
        "dx_east_arcsec", "dy_north_arcsec", "separation_arcsec",
        "position_angle_deg_east_of_north",
        "mid_radius_from_science_arcsec", "sign_pair",
    ]
    with OUT_CONTROLS.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=ctrl_fields)
        w.writeheader()
        for r in control_dump:
            w.writerow({k: r.get(k) for k in ctrl_fields})

    md = []
    md.append("# ORDER 01 — Pixel-Derived Local Astrometric Calibration v028m")
    md.append("")
    md.append("## Guard change")
    md.append("")
    md.append(
        "**Science pixels were read in this stage.** The read was restricted to "
        "the frozen native NPY discovery tiles containing the six survivors."
    )
    md.append("")
    md.append("- No network access.")
    md.append("- No transient detector rerun.")
    md.append("- No detector parameter change.")
    md.append("- No candidate promoted, deleted, or otherwise mutated.")
    md.append("")
    md.append("## Method")
    md.append("")
    md.append(
        "A separate band-pass/local-extrema source extractor was used solely "
        "to build ordinary-source astrometric controls. Pixel→sky mappings were "
        "reconstructed and holdout-tested from frozen native catalogue coordinates."
    )
    md.append("")
    md.append("## Results")
    md.append("")
    md.append(
        "| rank | raw sep | Gaia common | control tier | controls | "
        "candidate residual | percentile | dominant extractor signs | label |"
    )
    md.append("|---:|---:|---:|---:|---:|---:|---:|---|---|")
    for r in results:
        c = r["chosen_control_summary"] or {}
        res = c.get("candidate_residual_from_control_median_arcsec")
        pctv = c.get("candidate_residual_empirical_percentile")
        md.append(
            f"| #{r['strict_rank']} | "
            f"{r['science_pair_separation_arcsec']:.3f}\" | "
            f"{r['gaia_cross_archive_anchor_count']} | "
            f"{r['chosen_control_threshold_sigma'] or 'n/a'} | "
            f"{c.get('count', 0)} | "
            f"{('n/a' if res is None else f'{res:.3f}\"')} | "
            f"{('n/a' if pctv is None else f'{100*pctv:.1f}%')} | "
            f"{r['dominant_independent_extractor_sign_pair'] or 'n/a'} | "
            f"`{r['local_astrometry_label']}` |"
        )
    md.append("")
    md.append("## Interpretation boundary")
    md.append("")
    md.append(
        "This stage tests whether the two endpoint positions are compatible "
        "with the local ordinary-source registration field. It does not establish "
        "that either signal is astrophysical."
    )
    OUT_MD.write_text("\n".join(md), encoding="utf-8")

    print()
    print("Outputs:")
    print(f"  {OUT_JSON}")
    print(f"  {OUT_CSV}")
    print(f"  {OUT_MD}")
    print(f"  {OUT_EXTRACTED}")
    print(f"  {OUT_CONTROLS}")
    print()
    print("SCIENCE PIXELS WERE READ in this stage.")
    print("No network query was made.")
    print("No transient detector was rerun.")
    print("No candidate was promoted or deleted.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
