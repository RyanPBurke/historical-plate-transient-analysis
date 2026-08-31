#!/usr/bin/env python3
"""
ORDER 01 — Gaia-guided local pixel astrometry v028n

Motivation
----------
v028m successfully reconstructed the frozen pixel->sky mappings, but its blind
band-pass extractor produced hundreds of local POSS sources and only 1--5 local
DASCH sources around each science position.  That made the astrometric-control
test underpowered.

v028n does NOT loosen the crossmatch radius or reuse transient candidates as
controls.  Instead it uses the already-frozen epoch-propagated Gaia coordinates
as predetermined astrometric probes:

  1. Reconstruct forward pixel->sky and inverse sky->pixel mappings independently
     for each discovery tile from frozen native catalogue rows.
  2. Predict where every frozen Gaia source should fall on each relevant tile.
  3. Read the frozen NPY science pixels and measure the strongest raw local
     excursion near that predetermined position.
  4. Estimate the response significance from a local annulus, not from a
     whole-tile threshold.
  5. Convert the measured extremum back to sky coordinates.
  6. Build cross-archive ordinary-star offset vectors only when the SAME Gaia
     source is detected on BOTH archives.
  7. Compare each science POSS->DASCH vector with those ordinary-star vectors.

This is a guided astrometric calibration, not a transient search.

Guard state
-----------
SCIENCE PIXELS ARE READ.
No network access.
No transient detector rerun.
No candidate state mutation.
No candidate promotion/deletion.
No weighted overall candidate score.

Interpretation
--------------
Gaia-guided positional consistency can support the positional compatibility of
the two discovery detections.  It cannot establish astrophysical reality.
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

V028K = BASE / "order01_discovery_exposure_overlap_freeze_v028k.json"
V028M = BASE / "order01_pixel_local_astrometry_v028m.json"
STRICT = BASE / "order01_strict_match_triage_v028.csv"
POSS_CAND = BASE / "order01_poss_native_candidates.csv"
DASCH_CAND = BASE / "order01_dasch_native_candidates.csv"
GAIA = BASE / "order01_gaia_source_candidates_v028b.csv"
INJ = BASE / "order01_injection_recovery_report_v028.json"

POSS_TILE_DIR = WORK / "poss_tiles"
DASCH_TILE_DIR = WORK / "dasch_tiles"

OUT_JSON = BASE / "order01_gaia_guided_local_astrometry_v028n.json"
OUT_CSV = BASE / "order01_gaia_guided_local_astrometry_v028n.csv"
OUT_ANCHORS = BASE / "order01_gaia_guided_anchor_measurements_v028n.csv"
OUT_MD = BASE / "ORDER01_GAIA_GUIDED_LOCAL_ASTROMETRY_V028N.md"

EXPECTED = [10, 24, 25, 26, 29, 30]

POLY_DEGREES = [1, 2, 3]
MAX_FORWARD_HOLDOUT_P95_ARCSEC = 0.35
MAX_INVERSE_HOLDOUT_P95_PX = 0.20

# Guided-response geometry.
SEARCH_RADIUS_ARCSEC = 8.0
STRONG_ASTROMETRIC_SEP_ARCSEC = 5.0
VERY_STRONG_ASTROMETRIC_SEP_ARCSEC = 3.0

# Because locations are fixed in advance by Gaia, a lower response threshold is
# scientifically safer than in a blind source finder.
GUIDED_MIN_ABS_Z = 3.5
GUIDED_STRONG_ABS_Z = 5.0

# Local noise annulus in angular units; translated to pixels per WCS.
ANNULUS_INNER_ARCSEC = 18.0
ANNULUS_OUTER_ARCSEC = 55.0
MIN_ANNULUS_PIXELS = 80

# Restrict the calibration to sources plausibly detectable on historical plates.
# We do not reject fainter Gaia rows outright: they are retained as diagnostics,
# but the primary "bright" summary uses this fixed bound.
PRIMARY_G_MAX = 15.0
BRIGHT_G_MAX = 13.5

MIN_GAIA_ANCHORS_STRONG = 5
MIN_GAIA_ANCHORS_DESCRIPTIVE = 3


def sha_file(path: Path, block: int = 1024 * 1024) -> str:
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


def tangent_xy(ra, dec, ra0: float, dec0: float):
    return (
        (np.asarray(ra, dtype=float) - ra0)
        * 3600.0
        * math.cos(math.radians(dec0)),
        (np.asarray(dec, dtype=float) - dec0) * 3600.0,
    )


def tangent_vector(
    ra1: float, dec1: float, ra2: float, dec2: float
) -> tuple[float, float, float, float]:
    dec0 = 0.5 * (dec1 + dec2)
    dx = (ra2 - ra1) * 3600.0 * math.cos(math.radians(dec0))
    dy = (dec2 - dec1) * 3600.0
    sep = math.hypot(dx, dy)
    pa = math.degrees(math.atan2(dx, dy)) % 360.0
    return dx, dy, sep, pa


def poly_terms(x: np.ndarray, y: np.ndarray, degree: int) -> np.ndarray:
    cols = [np.ones_like(x)]
    for total in range(1, degree + 1):
        for xp in range(total, -1, -1):
            yp = total - xp
            cols.append((x ** xp) * (y ** yp))
    return np.column_stack(cols)


class TileTransform:
    def __init__(
        self,
        x0: float,
        y0: float,
        pscale: float,
        ra0: float,
        dec0: float,
        sscale: float,
        fdeg: int,
        fx: np.ndarray,
        fy: np.ndarray,
        ideg: int,
        ix: np.ndarray,
        iy: np.ndarray,
        validation: dict[str, Any],
    ):
        self.x0 = x0
        self.y0 = y0
        self.pscale = pscale
        self.ra0 = ra0
        self.dec0 = dec0
        self.sscale = sscale
        self.fdeg = fdeg
        self.fx = fx
        self.fy = fy
        self.ideg = ideg
        self.ix = ix
        self.iy = iy
        self.validation = validation

    def pixel_to_sky(self, gx, gy):
        px = (np.atleast_1d(np.asarray(gx, dtype=float)) - self.x0) / self.pscale
        py = (np.atleast_1d(np.asarray(gy, dtype=float)) - self.y0) / self.pscale
        A = poly_terms(px, py, self.fdeg)
        sx = (A @ self.fx) * self.sscale
        sy = (A @ self.fy) * self.sscale
        ra = self.ra0 + sx / (
            3600.0 * math.cos(math.radians(self.dec0))
        )
        dec = self.dec0 + sy / 3600.0
        if np.ndim(gx) == 0:
            return float(ra[0]), float(dec[0])
        return ra, dec

    def sky_to_pixel(self, ra, dec):
        sx, sy = tangent_xy(
            np.atleast_1d(np.asarray(ra, dtype=float)),
            np.atleast_1d(np.asarray(dec, dtype=float)),
            self.ra0,
            self.dec0,
        )
        sx = np.asarray(sx) / self.sscale
        sy = np.asarray(sy) / self.sscale
        A = poly_terms(sx, sy, self.ideg)
        px = (A @ self.ix) * self.pscale + self.x0
        py = (A @ self.iy) * self.pscale + self.y0
        if np.ndim(ra) == 0:
            return float(px[0]), float(py[0])
        return px, py

    def local_arcsec_per_pixel(self, gx: float, gy: float) -> float:
        ra0, dec0 = self.pixel_to_sky(gx, gy)
        ra1, dec1 = self.pixel_to_sky(gx + 1.0, gy)
        ra2, dec2 = self.pixel_to_sky(gx, gy + 1.0)
        _, _, sx, _ = tangent_vector(ra0, dec0, ra1, dec1)
        _, _, sy, _ = tangent_vector(ra0, dec0, ra2, dec2)
        vals = [q for q in (sx, sy) if math.isfinite(q) and q > 0]
        if not vals:
            raise RuntimeError("could not derive local arcsec/pixel")
        return float(statistics.median(vals))


def fit_transform(rows: list[dict[str, str]], tile_id: str) -> TileTransform:
    pts = []
    for r in rows:
        if str(r.get("tile_id", "")) != tile_id:
            continue
        try:
            pts.append((
                f(r["global_x"]),
                f(r["global_y"]),
                f(r["ra_deg"]),
                f(r["dec_deg"]),
            ))
        except Exception:
            continue

    if len(pts) < 30:
        raise RuntimeError(f"{tile_id}: only {len(pts)} coordinate rows")

    arr = np.asarray(pts, dtype=float)
    gx, gy, ra, dec = arr.T

    x0 = float(np.median(gx))
    y0 = float(np.median(gy))
    pscale = max(float(np.ptp(gx)), float(np.ptp(gy)), 512.0) / 2.0
    ra0 = float(np.median(ra))
    dec0 = float(np.median(dec))
    sx, sy = tangent_xy(ra, dec, ra0, dec0)
    sscale = max(float(np.ptp(sx)), float(np.ptp(sy)), 100.0) / 2.0

    pxn = (gx - x0) / pscale
    pyn = (gy - y0) / pscale
    sxn = np.asarray(sx) / sscale
    syn = np.asarray(sy) / sscale

    order = np.lexsort((gy, gx))
    test = np.zeros(len(arr), dtype=bool)
    test[order[::5]] = True
    train = ~test
    if np.count_nonzero(test) < 5 or np.count_nonzero(train) < 20:
        raise RuntimeError(f"{tile_id}: insufficient holdout split")

    f_trials = []
    f_best = None
    for deg in POLY_DEGREES:
        A = poly_terms(pxn, pyn, deg)
        cx, *_ = np.linalg.lstsq(A[train], sxn[train], rcond=None)
        cy, *_ = np.linalg.lstsq(A[train], syn[train], rcond=None)
        psx = (A[test] @ cx) * sscale
        psy = (A[test] @ cy) * sscale
        res = np.hypot(psx - np.asarray(sx)[test], psy - np.asarray(sy)[test])
        trial = {
            "degree": deg,
            "median_arcsec": float(np.median(res)),
            "p95_arcsec": float(np.quantile(res, 0.95)),
            "max_arcsec": float(np.max(res)),
        }
        f_trials.append(trial)
        if f_best is None or trial["p95_arcsec"] < f_best[0]:
            f_best = (trial["p95_arcsec"], deg)
        if trial["p95_arcsec"] <= 0.05:
            break

    assert f_best is not None
    fdeg = f_best[1]
    Af = poly_terms(pxn, pyn, fdeg)
    fx, *_ = np.linalg.lstsq(Af, sxn, rcond=None)
    fy, *_ = np.linalg.lstsq(Af, syn, rcond=None)

    i_trials = []
    i_best = None
    for deg in POLY_DEGREES:
        A = poly_terms(sxn, syn, deg)
        cx, *_ = np.linalg.lstsq(A[train], pxn[train], rcond=None)
        cy, *_ = np.linalg.lstsq(A[train], pyn[train], rcond=None)
        ppx = (A[test] @ cx) * pscale + x0
        ppy = (A[test] @ cy) * pscale + y0
        res = np.hypot(ppx - gx[test], ppy - gy[test])
        trial = {
            "degree": deg,
            "median_px": float(np.median(res)),
            "p95_px": float(np.quantile(res, 0.95)),
            "max_px": float(np.max(res)),
        }
        i_trials.append(trial)
        if i_best is None or trial["p95_px"] < i_best[0]:
            i_best = (trial["p95_px"], deg)
        if trial["p95_px"] <= 0.05:
            break

    assert i_best is not None
    ideg = i_best[1]
    Ai = poly_terms(sxn, syn, ideg)
    ix, *_ = np.linalg.lstsq(Ai, pxn, rcond=None)
    iy, *_ = np.linalg.lstsq(Ai, pyn, rcond=None)

    validation = {
        "tile_id": tile_id,
        "coordinate_rows": len(pts),
        "forward_trials": f_trials,
        "forward_chosen_degree": fdeg,
        "forward_holdout_p95_arcsec": f_best[0],
        "forward_acceptable": f_best[0] <= MAX_FORWARD_HOLDOUT_P95_ARCSEC,
        "inverse_trials": i_trials,
        "inverse_chosen_degree": ideg,
        "inverse_holdout_p95_px": i_best[0],
        "inverse_acceptable": i_best[0] <= MAX_INVERSE_HOLDOUT_P95_PX,
    }

    return TileTransform(
        x0, y0, pscale, ra0, dec0, sscale,
        fdeg, fx, fy, ideg, ix, iy, validation
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
            raise RuntimeError(f"{archive} {tid}: NPY SHA mismatch")
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


ARRAY_CACHE: dict[tuple[str, str], np.ndarray] = {}


def load_array(meta: dict[str, Any]) -> np.ndarray:
    key = (meta["archive"], meta["tile_id"])
    if key in ARRAY_CACHE:
        return ARRAY_CACHE[key]
    arr = np.load(meta["npy_path"], mmap_mode="r")
    ex0, ex1, ey0, ey1 = meta["extended"]
    expected = (ey1 - ey0, ex1 - ex0)
    if arr.ndim != 2 or tuple(arr.shape) != expected:
        raise RuntimeError(f"{key}: NPY shape {arr.shape} != {expected}")
    ARRAY_CACHE[key] = arr
    return arr


def robust_location_sigma(vals: np.ndarray) -> tuple[float, float]:
    x = np.asarray(vals, dtype=float)
    x = x[np.isfinite(x)]
    if x.size < MIN_ANNULUS_PIXELS:
        raise RuntimeError(f"only {x.size} finite annulus pixels")
    med = float(np.median(x))
    mad = float(np.median(np.abs(x - med)))
    sigma = 1.4826 * mad
    if not math.isfinite(sigma) or sigma <= 0:
        sigma = float(np.std(x))
    if not math.isfinite(sigma) or sigma <= 0:
        raise RuntimeError("invalid local sigma")
    return med, sigma


def guided_measurement(
    meta: dict[str, Any],
    tr: TileTransform,
    gaia_ra: float,
    gaia_dec: float,
) -> dict[str, Any]:
    gx_pred, gy_pred = tr.sky_to_pixel(gaia_ra, gaia_dec)
    ex0, ex1, ey0, ey1 = meta["extended"]
    lx = gx_pred - ex0
    ly = gy_pred - ey0
    arr = load_array(meta)

    if not (
        0 <= lx < arr.shape[1]
        and 0 <= ly < arr.shape[0]
    ):
        return {
            "status": "OUTSIDE_TILE",
            "predicted_global_x": gx_pred,
            "predicted_global_y": gy_pred,
        }

    app = tr.local_arcsec_per_pixel(gx_pred, gy_pred)
    search_r_px = max(1.5, SEARCH_RADIUS_ARCSEC / app)
    ann_in_px = max(search_r_px + 2.0, ANNULUS_INNER_ARCSEC / app)
    ann_out_px = max(ann_in_px + 3.0, ANNULUS_OUTER_ARCSEC / app)

    margin = int(math.ceil(ann_out_px)) + 2
    ix = int(round(lx))
    iy = int(round(ly))
    if (
        ix - margin < 0 or iy - margin < 0
        or ix + margin >= arr.shape[1]
        or iy + margin >= arr.shape[0]
    ):
        return {
            "status": "INSUFFICIENT_EDGE_MARGIN",
            "predicted_global_x": gx_pred,
            "predicted_global_y": gy_pred,
            "arcsec_per_pixel": app,
        }

    y0, y1 = iy - margin, iy + margin + 1
    x0, x1 = ix - margin, ix + margin + 1
    cut = np.asarray(arr[y0:y1, x0:x1], dtype=float)

    yy, xx = np.indices(cut.shape, dtype=float)
    cx = lx - x0
    cy = ly - y0
    rr = np.hypot(xx - cx, yy - cy)

    ann = cut[(rr >= ann_in_px) & (rr <= ann_out_px)]
    bg, sigma = robust_location_sigma(ann)

    search = rr <= search_r_px
    vals = cut.copy()
    vals[~search] = np.nan

    max_idx = int(np.nanargmax(vals))
    min_idx = int(np.nanargmin(vals))
    max_y, max_x = np.unravel_index(max_idx, vals.shape)
    min_y, min_x = np.unravel_index(min_idx, vals.shape)

    max_z = (float(cut[max_y, max_x]) - bg) / sigma
    min_z = (float(cut[min_y, min_x]) - bg) / sigma

    if abs(max_z) >= abs(min_z):
        sy, sx = max_y, max_x
        signed_z = max_z
        sign = 1
    else:
        sy, sx = min_y, min_x
        signed_z = min_z
        sign = -1

    gx_meas = ex0 + x0 + sx
    gy_meas = ey0 + y0 + sy
    ra_meas, dec_meas = tr.pixel_to_sky(gx_meas, gy_meas)
    dx, dy, sep, pa = tangent_vector(
        gaia_ra, gaia_dec, ra_meas, dec_meas
    )

    return {
        "status": "MEASURED",
        "predicted_global_x": gx_pred,
        "predicted_global_y": gy_pred,
        "measured_global_x": gx_meas,
        "measured_global_y": gy_meas,
        "arcsec_per_pixel": app,
        "search_radius_px": search_r_px,
        "annulus_inner_px": ann_in_px,
        "annulus_outer_px": ann_out_px,
        "local_background": bg,
        "local_sigma": sigma,
        "max_z": max_z,
        "min_z": min_z,
        "chosen_sign": sign,
        "chosen_signed_z": signed_z,
        "chosen_abs_z": abs(signed_z),
        "measured_ra_deg": ra_meas,
        "measured_dec_deg": dec_meas,
        "gaia_to_measured_dx_east_arcsec": dx,
        "gaia_to_measured_dy_north_arcsec": dy,
        "gaia_to_measured_sep_arcsec": sep,
        "gaia_to_measured_pa_deg": pa,
        "passes_guided_z": abs(signed_z) >= GUIDED_MIN_ABS_Z,
        "passes_5arcsec": sep <= STRONG_ASTROMETRIC_SEP_ARCSEC,
        "passes_3arcsec": sep <= VERY_STRONG_ASTROMETRIC_SEP_ARCSEC,
        "accepted_guided_anchor": (
            abs(signed_z) >= GUIDED_MIN_ABS_Z
            and sep <= STRONG_ASTROMETRIC_SEP_ARCSEC
        ),
    }


def summarize_vectors(
    rows: list[dict[str, Any]],
    science_dx: float,
    science_dy: float,
) -> dict[str, Any]:
    if not rows:
        return {
            "count": 0,
            "median_dx_east_arcsec": None,
            "median_dy_north_arcsec": None,
            "candidate_residual_from_median_arcsec": None,
            "candidate_residual_empirical_percentile": None,
        }
    xs = [f(r["cross_dx_east_arcsec"]) for r in rows]
    ys = [f(r["cross_dy_north_arcsec"]) for r in rows]
    mdx = statistics.median(xs)
    mdy = statistics.median(ys)
    residuals = [
        math.hypot(x - mdx, y - mdy)
        for x, y in zip(xs, ys)
    ]
    sres = math.hypot(science_dx - mdx, science_dy - mdy)
    seps = [math.hypot(x, y) for x, y in zip(xs, ys)]
    pct = sum(v <= sres for v in residuals) / len(residuals)
    signs = Counter(
        f"{int(r['poss_chosen_sign']):+d},{int(r['dasch_chosen_sign']):+d}"
        for r in rows
    )
    dom = signs.most_common(1)[0] if signs else (None, 0)
    return {
        "count": len(rows),
        "median_dx_east_arcsec": mdx,
        "median_dy_north_arcsec": mdy,
        "median_translation_magnitude_arcsec": math.hypot(mdx, mdy),
        "median_cross_archive_separation_arcsec": statistics.median(seps),
        "p90_cross_archive_separation_arcsec":
            float(np.quantile(seps, 0.90)),
        "p95_cross_archive_separation_arcsec":
            float(np.quantile(seps, 0.95)),
        "median_control_residual_arcsec": statistics.median(residuals),
        "p90_control_residual_arcsec": float(np.quantile(residuals, 0.90)),
        "p95_control_residual_arcsec": float(np.quantile(residuals, 0.95)),
        "candidate_residual_from_median_arcsec": sres,
        "candidate_residual_empirical_percentile": pct,
        "sign_pair_counts": dict(signs),
        "dominant_sign_pair": dom[0],
        "dominant_sign_count": dom[1],
        "dominant_sign_fraction": dom[1] / len(rows) if rows else None,
    }


def result_label(summary: dict[str, Any]) -> str:
    n = summary["count"]
    pct = summary.get("candidate_residual_empirical_percentile")
    if n >= MIN_GAIA_ANCHORS_STRONG:
        if pct is not None and pct <= 0.95:
            return "CONSISTENT_WITH_GAIA_GUIDED_LOCAL_REGISTRATION"
        return "OUTSIDE_95PCT_GAIA_GUIDED_LOCAL_REGISTRATION"
    if n >= MIN_GAIA_ANCHORS_DESCRIPTIVE:
        if pct is not None and pct <= 0.95:
            return "DESCRIPTIVELY_CONSISTENT_WITH_GAIA_GUIDED_LOCAL_REGISTRATION"
        return "DESCRIPTIVELY_HIGH_RESIDUAL_IN_GAIA_GUIDED_LOCAL_REGISTRATION"
    return "INSUFFICIENT_COMMON_GAIA_GUIDED_ANCHORS"


def main() -> int:
    print("=" * 126)
    print("ORDER 01 — GAIA-GUIDED LOCAL PIXEL ASTROMETRY v028n")
    print("=" * 126)
    print("SCIENCE PIXELS ARE READ. Frozen transient detector is NOT rerun.")
    print()

    for p in (V028K, V028M, STRICT, POSS_CAND, DASCH_CAND, GAIA, INJ):
        if not p.is_file():
            print(f"FAIL: missing required input: {p}")
            return 2

    k = json.loads(V028K.read_text(encoding="utf-8"))
    m = json.loads(V028M.read_text(encoding="utf-8"))
    inj = json.loads(INJ.read_text(encoding="utf-8"))

    if k.get("frozen_active_ranks") != EXPECTED:
        print("FAIL: v028k survivor mismatch")
        return 3
    if m.get("frozen_active_ranks") != EXPECTED:
        print("FAIL: v028m survivor mismatch")
        return 3
    if m.get("guards", {}).get("science_pixels_read") is not True:
        print("FAIL: v028m guard does not record pixel read")
        return 3
    if any(
        r.get("local_astrometry_label")
        != "INSUFFICIENT_PIXEL_DERIVED_ASTROMETRIC_CONTROLS"
        for r in m.get("results", [])
    ):
        print("FAIL: v028n expected v028m unresolved state")
        return 3

    strict = read_csv(STRICT)
    prows = read_csv(POSS_CAND)
    drows = read_csv(DASCH_CAND)
    grows = read_csv(GAIA)

    sr = {
        i(r["strict_rank"]): r
        for r in strict
        if i(r["strict_rank"]) in EXPECTED
    }
    if sorted(sr) != EXPECTED:
        raise RuntimeError("strict survivor set mismatch")

    gaia_by_rank: dict[int, list[dict[str, str]]] = {
        r: [] for r in EXPECTED
    }
    for g in grows:
        try:
            rank = i(g["strict_rank"])
        except Exception:
            continue
        if rank in gaia_by_rank:
            gaia_by_rank[rank].append(g)

    pinv = load_tile_inventory(POSS_TILE_DIR, "POSS")
    dinv = load_tile_inventory(DASCH_TILE_DIR, "DASCH")

    needed_p = {str(sr[r]["poss_tile_id"]) for r in EXPECTED}
    needed_d = {str(sr[r]["dasch_tile_id"]) for r in EXPECTED}

    # Hash cross-check against injection stage.
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
            ("POSS", str(sr[rank]["poss_tile_id"]), pinv),
            ("DASCH", str(sr[rank]["dasch_tile_id"]), dinv),
        ):
            if tid not in inv:
                raise RuntimeError(f"missing {archive} tile {tid}")
            e = inj_map.get((rank, archive))
            if e is None:
                raise RuntimeError(f"missing injection endpoint {rank} {archive}")
            if str(e.get("tile_id")) != tid:
                raise RuntimeError(f"{rank} {archive}: tile mismatch")
            expected_sha = str(e.get("native_npy_sha256", "")).lower()
            if expected_sha and expected_sha != inv[tid]["npy_sha256"]:
                raise RuntimeError(f"{rank} {archive}: NPY SHA mismatch")

    print("Frozen tile/hash guards: PASS")
    print()

    print("Fitting forward + inverse tile transforms...")
    ptrans = {tid: fit_transform(prows, tid) for tid in sorted(needed_p)}
    dtrans = {tid: fit_transform(drows, tid) for tid in sorted(needed_d)}

    for archive, trans in (("POSS", ptrans), ("DASCH", dtrans)):
        for tid, tr in trans.items():
            v = tr.validation
            print(
                f"  {archive:5s} {tid}: "
                f"forward_p95={v['forward_holdout_p95_arcsec']:.4f}\" "
                f"inverse_p95={v['inverse_holdout_p95_px']:.4f}px "
                f"OK={v['forward_acceptable'] and v['inverse_acceptable']}"
            )
            if not (v["forward_acceptable"] and v["inverse_acceptable"]):
                raise RuntimeError(f"{archive} {tid}: transform validation failed")
    print()

    anchor_rows = []
    results = []

    print("Per-candidate Gaia-guided responses:")
    print("-" * 126)

    for rank in EXPECTED:
        s = sr[rank]
        ptid = str(s["poss_tile_id"])
        dtid = str(s["dasch_tile_id"])
        pmeta = pinv[ptid]
        dmeta = dinv[dtid]
        ptr = ptrans[ptid]
        dtr = dtrans[dtid]

        pra, pdec = f(s["poss_ra_deg"]), f(s["poss_dec_deg"])
        dra, ddec = f(s["dasch_ra_deg"]), f(s["dasch_dec_deg"])
        sdx, sdy, ssep, spa = tangent_vector(pra, pdec, dra, ddec)

        measured = []
        for g in gaia_by_rank[rank]:
            try:
                sid = str(g["source_id"])
                gra = f(g["ra_target_deg"])
                gdec = f(g["dec_target_deg"])
            except Exception:
                continue
            gmag = (
                f(g["g_mag"])
                if str(g.get("g_mag", "")).strip()
                else None
            )

            pm = guided_measurement(pmeta, ptr, gra, gdec)
            dm = guided_measurement(dmeta, dtr, gra, gdec)

            row = {
                "strict_rank": rank,
                "source_id": sid,
                "g_mag": gmag,
                "gaia_ra_target_deg": gra,
                "gaia_dec_target_deg": gdec,
                "propagated": str(g.get("propagated", "")),
                "pm_sigma_arcsec": (
                    f(g["approx_pm_propagation_sigma_arcsec"])
                    if str(g.get("approx_pm_propagation_sigma_arcsec", "")).strip()
                    else None
                ),
                "poss_tile_id": ptid,
                "dasch_tile_id": dtid,
                "poss_status": pm.get("status"),
                "dasch_status": dm.get("status"),
            }

            for prefix, q in (("poss", pm), ("dasch", dm)):
                for key in (
                    "predicted_global_x",
                    "predicted_global_y",
                    "measured_global_x",
                    "measured_global_y",
                    "arcsec_per_pixel",
                    "chosen_sign",
                    "chosen_signed_z",
                    "chosen_abs_z",
                    "measured_ra_deg",
                    "measured_dec_deg",
                    "gaia_to_measured_dx_east_arcsec",
                    "gaia_to_measured_dy_north_arcsec",
                    "gaia_to_measured_sep_arcsec",
                    "passes_guided_z",
                    "passes_5arcsec",
                    "passes_3arcsec",
                    "accepted_guided_anchor",
                ):
                    row[f"{prefix}_{key}"] = q.get(key)

            common = (
                pm.get("accepted_guided_anchor") is True
                and dm.get("accepted_guided_anchor") is True
            )
            row["common_accepted_anchor"] = common

            if common:
                cdx, cdy, csep, cpa = tangent_vector(
                    f(pm["measured_ra_deg"]),
                    f(pm["measured_dec_deg"]),
                    f(dm["measured_ra_deg"]),
                    f(dm["measured_dec_deg"]),
                )
                row.update({
                    "cross_dx_east_arcsec": cdx,
                    "cross_dy_north_arcsec": cdy,
                    "cross_sep_arcsec": csep,
                    "cross_pa_deg": cpa,
                })
                measured.append(row)

            anchor_rows.append(row)

        primary = [
            q for q in measured
            if q["g_mag"] is not None and q["g_mag"] <= PRIMARY_G_MAX
        ]
        bright = [
            q for q in measured
            if q["g_mag"] is not None and q["g_mag"] <= BRIGHT_G_MAX
        ]

        # Primary analysis: fixed G<=15 when it leaves enough anchors.
        # Otherwise retain all accepted guided anchors but mark that explicitly.
        if len(primary) >= MIN_GAIA_ANCHORS_DESCRIPTIVE:
            chosen = primary
            chosen_kind = f"GAIA_G_LE_{PRIMARY_G_MAX:g}"
        else:
            chosen = measured
            chosen_kind = "ALL_COMMON_ACCEPTED_GAIA_ANCHORS_FALLBACK"

        summary = summarize_vectors(chosen, sdx, sdy)
        label = result_label(summary)

        p_accept = [
            q for q in anchor_rows
            if q["strict_rank"] == rank
            and q.get("poss_accepted_guided_anchor") is True
        ]
        d_accept = [
            q for q in anchor_rows
            if q["strict_rank"] == rank
            and q.get("dasch_accepted_guided_anchor") is True
        ]

        p_signs = Counter(
            int(q["poss_chosen_sign"]) for q in p_accept
            if q.get("poss_chosen_sign") is not None
        )
        d_signs = Counter(
            int(q["dasch_chosen_sign"]) for q in d_accept
            if q.get("dasch_chosen_sign") is not None
        )

        result = {
            "strict_rank": rank,
            "science_pair_separation_arcsec": ssep,
            "science_dx_east_arcsec": sdx,
            "science_dy_north_arcsec": sdy,
            "science_pa_deg": spa,
            "gaia_rows_examined": len(gaia_by_rank[rank]),
            "poss_guided_anchor_count": len(p_accept),
            "dasch_guided_anchor_count": len(d_accept),
            "common_guided_anchor_count": len(measured),
            "primary_g15_common_count": len(primary),
            "bright_g13p5_common_count": len(bright),
            "chosen_anchor_kind": chosen_kind,
            "chosen_anchor_count": len(chosen),
            "chosen_summary": summary,
            "poss_anchor_sign_counts": dict(p_signs),
            "dasch_anchor_sign_counts": dict(d_signs),
            "local_astrometry_label": label,
        }
        results.append(result)

        pct = summary.get("candidate_residual_empirical_percentile")
        cres = summary.get("candidate_residual_from_median_arcsec")
        mdx = summary.get("median_dx_east_arcsec")
        mdy = summary.get("median_dy_north_arcsec")

        def ft(v, nd=3):
            return "n/a" if v is None else f"{v:.{nd}f}"

        print(
            f"#{rank:>2} Gaia={len(gaia_by_rank[rank]):>2} "
            f"P/D/common={len(p_accept):>2}/{len(d_accept):>2}/{len(measured):>2} "
            f"chosen={len(chosen):>2}({chosen_kind}) "
            f"local_shift=({ft(mdx)}, {ft(mdy)})\" "
            f"science_resid={ft(cres)}\" "
            f"pct={'n/a' if pct is None else f'{100*pct:.1f}%'} "
            f"Psign={dict(p_signs)} Dsign={dict(d_signs)} "
            f"{label}"
        )

    payload = {
        "stage": "ORDER01_GAIA_GUIDED_LOCAL_ASTROMETRY_V028N",
        "inputs": {
            "overlap_freeze": str(V028K.relative_to(ROOT)),
            "pixel_astrometry_v028m": str(V028M.relative_to(ROOT)),
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
            "npy_arrays_loaded": True,
            "transient_detector_rerun": False,
            "transient_detector_parameters_changed": False,
            "candidate_state_mutation": False,
            "candidate_promotion": False,
            "candidate_deletion": False,
            "weighted_candidate_score": False,
        },
        "declared_parameters": {
            "search_radius_arcsec": SEARCH_RADIUS_ARCSEC,
            "strong_astrometric_sep_arcsec": STRONG_ASTROMETRIC_SEP_ARCSEC,
            "very_strong_astrometric_sep_arcsec":
                VERY_STRONG_ASTROMETRIC_SEP_ARCSEC,
            "guided_min_abs_z": GUIDED_MIN_ABS_Z,
            "guided_strong_abs_z": GUIDED_STRONG_ABS_Z,
            "annulus_inner_arcsec": ANNULUS_INNER_ARCSEC,
            "annulus_outer_arcsec": ANNULUS_OUTER_ARCSEC,
            "primary_g_max": PRIMARY_G_MAX,
            "bright_g_max": BRIGHT_G_MAX,
            "min_gaia_anchors_strong": MIN_GAIA_ANCHORS_STRONG,
            "min_gaia_anchors_descriptive": MIN_GAIA_ANCHORS_DESCRIPTIVE,
        },
        "results": results,
        "interpretive_boundary": (
            "Gaia positions were frozen before this guided pixel measurement. "
            "This stage tests local positional registration only. It does not "
            "establish astrophysical reality."
        ),
    }
    OUT_JSON.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    compact_fields = [
        "strict_rank",
        "science_pair_separation_arcsec",
        "gaia_rows_examined",
        "poss_guided_anchor_count",
        "dasch_guided_anchor_count",
        "common_guided_anchor_count",
        "primary_g15_common_count",
        "bright_g13p5_common_count",
        "chosen_anchor_kind",
        "chosen_anchor_count",
        "median_dx_east_arcsec",
        "median_dy_north_arcsec",
        "candidate_residual_from_median_arcsec",
        "candidate_residual_empirical_percentile",
        "dominant_sign_pair",
        "poss_anchor_sign_counts",
        "dasch_anchor_sign_counts",
        "local_astrometry_label",
    ]
    with OUT_CSV.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=compact_fields)
        w.writeheader()
        for r in results:
            s = r["chosen_summary"]
            w.writerow({
                "strict_rank": r["strict_rank"],
                "science_pair_separation_arcsec":
                    r["science_pair_separation_arcsec"],
                "gaia_rows_examined": r["gaia_rows_examined"],
                "poss_guided_anchor_count": r["poss_guided_anchor_count"],
                "dasch_guided_anchor_count": r["dasch_guided_anchor_count"],
                "common_guided_anchor_count": r["common_guided_anchor_count"],
                "primary_g15_common_count": r["primary_g15_common_count"],
                "bright_g13p5_common_count": r["bright_g13p5_common_count"],
                "chosen_anchor_kind": r["chosen_anchor_kind"],
                "chosen_anchor_count": r["chosen_anchor_count"],
                "median_dx_east_arcsec": s.get("median_dx_east_arcsec"),
                "median_dy_north_arcsec": s.get("median_dy_north_arcsec"),
                "candidate_residual_from_median_arcsec":
                    s.get("candidate_residual_from_median_arcsec"),
                "candidate_residual_empirical_percentile":
                    s.get("candidate_residual_empirical_percentile"),
                "dominant_sign_pair": s.get("dominant_sign_pair"),
                "poss_anchor_sign_counts":
                    json.dumps(r["poss_anchor_sign_counts"], sort_keys=True),
                "dasch_anchor_sign_counts":
                    json.dumps(r["dasch_anchor_sign_counts"], sort_keys=True),
                "local_astrometry_label": r["local_astrometry_label"],
            })

    # Detailed guided anchor rows.
    anchor_fields = sorted({
        k for row in anchor_rows for k in row.keys()
    })
    with OUT_ANCHORS.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=anchor_fields)
        w.writeheader()
        for row in anchor_rows:
            w.writerow(row)

    md = []
    md.append("# ORDER 01 — Gaia-Guided Local Pixel Astrometry v028n")
    md.append("")
    md.append("## Guard state")
    md.append("")
    md.append("**Science pixels were read.**")
    md.append("")
    md.append("- No network access.")
    md.append("- No transient detector rerun.")
    md.append("- No transient detector parameter change.")
    md.append("- No candidate promoted, deleted, or otherwise mutated.")
    md.append("")
    md.append("## Method")
    md.append("")
    md.append(
        "Frozen epoch-propagated Gaia positions were projected onto each native "
        "discovery tile. The strongest raw local pixel excursion within a fixed "
        "8 arcsec search radius was measured against a local annular background. "
        "Only the same Gaia source accepted independently on both archives "
        "contributed a cross-archive astrometric control vector."
    )
    md.append("")
    md.append("## Results")
    md.append("")
    md.append(
        "| rank | Gaia | POSS anchors | DASCH anchors | common | chosen | "
        "candidate residual | percentile | dominant signs | label |"
    )
    md.append("|---:|---:|---:|---:|---:|---:|---:|---:|---|---|")
    for r in results:
        s = r["chosen_summary"]
        resid = s.get("candidate_residual_from_median_arcsec")
        pct = s.get("candidate_residual_empirical_percentile")
        md.append(
            f"| #{r['strict_rank']} | {r['gaia_rows_examined']} | "
            f"{r['poss_guided_anchor_count']} | "
            f"{r['dasch_guided_anchor_count']} | "
            f"{r['common_guided_anchor_count']} | "
            f"{r['chosen_anchor_count']} | "
            f"{('n/a' if resid is None else f'{resid:.3f} arcsec')} | "
            f"{('n/a' if pct is None else f'{100*pct:.1f}%')} | "
            f"{s.get('dominant_sign_pair') or 'n/a'} | "
            f"`{r['local_astrometry_label']}` |"
        )
    md.append("")
    md.append("## Interpretation boundary")
    md.append("")
    md.append(
        "This is a guided astrometric calibration using positions fixed before "
        "the pixel measurement. It does not classify the transient candidates "
        "as astrophysical or instrumental."
    )
    OUT_MD.write_text("\n".join(md), encoding="utf-8")

    print()
    print("Outputs:")
    print(f"  {OUT_JSON}")
    print(f"  {OUT_CSV}")
    print(f"  {OUT_ANCHORS}")
    print(f"  {OUT_MD}")
    print()
    print("SCIENCE PIXELS WERE READ.")
    print("No network query was made.")
    print("No transient detector was rerun.")
    print("No candidate was promoted or deleted.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
