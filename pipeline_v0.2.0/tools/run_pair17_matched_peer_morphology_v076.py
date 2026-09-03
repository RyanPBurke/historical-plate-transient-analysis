#!/usr/bin/env python3
"""
v076 — Pair 17 deterministic matched-peer native-pixel morphology.

Scientific contract:
  research/prospective_freezes/pair17_matched_peer_morphology_contract_v076.json
  SHA256 02f3d9d0b5bbc7a89a44c270d59537c878ec9d52fb7a70d0d97930aeb5420c2f

Execution is contextual only:
  * all 603 frozen v075 associations are processed;
  * v075 Gaia class does not select targets or alter control selection;
  * exact frozen v056 candidate identities define targets and controls;
  * exact acquired APPLAUSE DR4 FITS bytes define native pixels;
  * no detector, registration, catalogue query, disposition change, or manual review.
"""

from pathlib import Path
from collections import Counter, defaultdict
import csv
import hashlib
import json
import math
import re
import socket

import numpy as np
import pandas as pd
from astropy.io import fits

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "results"
TOOLS = ROOT / "tools"
RESEARCH = ROOT / "research"
WORK = ROOT / "work"

PAIR_INDEX = 17

CONTRACT = (
    RESEARCH / "prospective_freezes"
    / "pair17_matched_peer_morphology_contract_v076.json"
)
V075_DIR = RESULTS / "pair17_epoch_aware_gaia_static_triage_v075"
V075_ROWS = V075_DIR / "pair17_epoch_aware_gaia_static_triage_v075.csv"
V075_JSON = V075_DIR / "pair17_epoch_aware_gaia_static_triage_v075.json"
V075_MANIFEST = V075_DIR / "pair17_static_triage_input_manifest_v075.csv"

ACQ_META_DIR = RESULTS / "pair17_morphology_scan_acquisition_v076"
ACQ_JSON = ACQ_META_DIR / "pair17_morphology_scan_acquisition_v076.json"
ACQ_CSV = ACQ_META_DIR / "pair17_morphology_scan_acquisition_v076.csv"
SCAN_DIR = WORK / "pair17_morphology_v076" / "scans"

TILE_ROOT = RESULTS / "wide_census_detector_execution_v056" / "tiles"

OUT = RESULTS / "pair17_matched_peer_morphology_v076"
OUT_ENDPOINT = OUT / "pair17_morphology_endpoint_metrics_v076.csv"
OUT_CONTROL = OUT / "pair17_morphology_control_metrics_v076.csv"
OUT_PAIR = OUT / "pair17_morphology_pair_summary_v076.csv"
OUT_REPORT = OUT / "pair17_matched_peer_morphology_v076.json"
OUT_PIXEL_MANIFEST = OUT / "pair17_morphology_pixel_manifest_v076.csv"

EXPECTED_SHA = {
    CONTRACT:
        "02f3d9d0b5bbc7a89a44c270d59537c878ec9d52fb7a70d0d97930aeb5420c2f",
    V075_ROWS:
        "cc571a4da103dc3900907fe9568567dd540f8f85217b7e7e73ca4442239f2097",
    V075_JSON:
        "abbf447a6cbb4b754f68b28e28cd821178e356b49cf7fac4d89ef9b701e9b2de",
    V075_MANIFEST:
        "66f7da8dfee178ee98f42255d7c58c2f292e3a2b62a5d7e64c25697eb95a673d",
}

ENDPOINTS = {
    "A": {
        "endpoint_key": "APPLAUSE:14120",
        "dirname": "APPLAUSE_14120",
        "scan": SCAN_DIR / "LA08164_y.fits",
        "scan_sha256":
            "e3340ba35643cf9342c2d1f5588a7e888dc5a1b157637f7d6f4e69e71ab6390f",
        "scan_bytes": 426124800,
        # Pre-freeze v054 endpoint-plan dimensions: NAXIS1 x NAXIS2.
        "expected_width": 17168,
        "expected_height": 12410,
        "v075_tile_field": "a_tile_id",
        "v075_index_field": "a_candidate_index",
    },
    "B": {
        "endpoint_key": "APPLAUSE:132654",
        "dirname": "APPLAUSE_132654",
        "scan": SCAN_DIR / "012673_1953_h.fits",
        "scan_sha256":
            "871622bc7113e5d0fa8936c9a4a10ce0b85861176b3c98bacb8fcfa70c641b62",
        "scan_bytes": 174888000,
        "expected_width": 8111,
        "expected_height": 10780,
        "v075_tile_field": "b_tile_id",
        "v075_index_field": "b_candidate_index",
    },
}

EXPECTED_TOTAL = 603
EXPECTED_PRIMARY = 424
EXPECTED_DIAGNOSTIC = 179

R = 10
EXCLUSION_PX = 32.0
PREF = (0.75, 1.25)
FALLBACK = (0.50, 1.50)
PREF_MIN = 12
MAX_CONTROLS = 32
MIN_USABLE = 5
OUTLIER_Z = 3.5

METRICS = [
    "sigma_major_px",
    "sigma_minor_px",
    "ellipticity",
    "centroid_offset_px",
    "concentration_f3_f8",
    "peak_to_flux5",
]


# -------------------------------------------------------------------------------------------------
# Utilities / guards
# -------------------------------------------------------------------------------------------------

def sha256(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for b in iter(lambda: f.read(8 * 1024 * 1024), b""):
            h.update(b)
    return h.hexdigest()


def fail(msg):
    raise RuntimeError(msg)


def block_network():
    def denied_connect(self, *args, **kwargs):
        raise RuntimeError("NETWORK ACCESS DISALLOWED BY v076")

    def denied_create_connection(*args, **kwargs):
        raise RuntimeError("NETWORK ACCESS DISALLOWED BY v076")

    socket.socket.connect = denied_connect
    socket.create_connection = denied_create_connection


def atomic_csv(path, rows, fields):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    tmp.replace(path)


def atomic_json(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(obj, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )
    tmp.replace(path)


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
            x = float(v)
            if math.isfinite(x) and x.is_integer():
                return int(x)
        except Exception:
            pass
    return None


def robust_scale(vals):
    a = np.asarray(
        [float(x) for x in vals if x is not None and math.isfinite(float(x))],
        dtype=float,
    )
    if len(a) == 0:
        return None, None
    med = float(np.median(a))
    scale = 1.4826 * float(np.median(np.abs(a - med)))
    if not math.isfinite(scale) or scale <= 0:
        scale = None
    return med, scale


# -------------------------------------------------------------------------------------------------
# Frozen population and frozen candidate inventory
# -------------------------------------------------------------------------------------------------

def load_v075_rows():
    df = pd.read_csv(V075_ROWS, dtype=str, keep_default_na=False)

    if len(df) != EXPECTED_TOTAL:
        fail(f"v075 row count changed: {len(df)} != {EXPECTED_TOTAL}")

    pops = Counter(df["population"].astype(str))
    if pops.get("PRIMARY_424", 0) != EXPECTED_PRIMARY:
        fail(f"v075 PRIMARY_424 changed: {pops}")
    if pops.get("DIAGNOSTIC_179", 0) != EXPECTED_DIAGNOSTIC:
        fail(f"v075 DIAGNOSTIC_179 changed: {pops}")

    if len(df["raw_match_row"].astype(str).unique()) != EXPECTED_TOTAL:
        fail("v075 raw_match_row identities are not unique")

    return df


def expected_v056_hashes_from_v075_manifest():
    m = pd.read_csv(V075_MANIFEST, dtype=str, keep_default_na=False)
    need = m[m["kind"] == "v056_candidate_csv"].copy()

    out = {}
    for _, r in need.iterrows():
        p = ROOT / str(r["path"])
        out[p.resolve()] = str(r["sha256"]).lower()

    if not out:
        fail("v075 input manifest contains no v056 candidate CSV hashes")
    return out


def load_endpoint_candidates(cfg, expected_hashes):
    d = TILE_ROOT / cfg["dirname"]
    if not d.is_dir():
        fail(f"Missing v056 endpoint directory: {d}")

    frames = []
    file_manifest = []

    for p in sorted(d.glob("*_candidates.csv")):
        expected = expected_hashes.get(p.resolve())
        if expected is None:
            fail(f"v056 candidate file absent from frozen v075 manifest: {p}")

        actual = sha256(p)
        if actual.lower() != expected:
            fail(
                f"v056 candidate CSV changed:\n{p}\n"
                f"expected {expected}\nactual   {actual}"
            )

        q = pd.read_csv(p, dtype=str, keep_default_na=False)
        if len(q) == 0:
            continue

        required = {
            "endpoint_key", "tile_id", "candidate_index",
            "local_x", "local_y", "global_x", "global_y",
            "snr", "polarity",
        }
        if not required.issubset(q.columns):
            fail(f"Unexpected v056 candidate schema in {p}: {list(q.columns)}")

        if not (q["endpoint_key"].astype(str) == cfg["endpoint_key"]).all():
            fail(f"Endpoint key mismatch inside {p}")

        frames.append(q)
        file_manifest.append({
            "kind": "v056_candidate_csv",
            "endpoint_key": cfg["endpoint_key"],
            "path": str(p.relative_to(ROOT)).replace("\\", "/"),
            "size_bytes": p.stat().st_size,
            "sha256": actual,
        })

    if not frames:
        fail(f"No non-empty v056 candidate CSVs for {cfg['endpoint_key']}")

    full = pd.concat(frames, ignore_index=True)

    by_tile = defaultdict(list)
    id_map = {}

    for i, r in full.iterrows():
        tid = str(r["tile_id"])
        idx = fint(r["candidate_index"])
        if idx is None:
            fail(f"Invalid candidate_index in {cfg['endpoint_key']}")

        k = (tid, idx)
        if k in id_map:
            fail(f"Duplicate frozen candidate identity: {cfg['endpoint_key']} {k}")

        rr = r.to_dict()
        rr["_row_index"] = int(i)
        by_tile[tid].append(rr)
        id_map[k] = rr

    return full, by_tile, id_map, file_manifest


# -------------------------------------------------------------------------------------------------
# Pixel-coordinate convention preflight — no science morphology is measured here
# -------------------------------------------------------------------------------------------------

TILE_RE = re.compile(
    r"^x(?P<x0>\d+)-(?P<x1>\d+)_y(?P<y0>\d+)-(?P<y1>\d+)$"
)


def preflight_tile_geometry(full, cfg):
    """
    Prove that frozen v056 local/global coordinates encode the known 64-pixel
    detector halo around each requested 1024x1024 tile:

      local_x = global_x - max(0, requested_x0 - 64)
      local_y = global_y - max(0, requested_y0 - 64)

    This reads catalogue coordinates only, not FITS pixel values.
    """
    checked = 0
    per_tile = {}

    for tid, g in full.groupby("tile_id", sort=True):
        m = TILE_RE.match(str(tid))
        if not m:
            fail(f"Unexpected tile_id geometry: {tid}")

        x0 = int(m.group("x0"))
        y0 = int(m.group("y0"))
        ext_x0 = max(0, x0 - 64)
        ext_y0 = max(0, y0 - 64)

        dxs = []
        dys = []

        for _, r in g.iterrows():
            lx = ffloat(r["local_x"])
            ly = ffloat(r["local_y"])
            gx = ffloat(r["global_x"])
            gy = ffloat(r["global_y"])

            if None in (lx, ly, gx, gy):
                fail(f"Non-finite local/global coordinate in {cfg['endpoint_key']} {tid}")

            dxs.append(gx - lx)
            dys.append(gy - ly)

            if gx < 0 or gy < 0:
                fail(f"Negative global coordinate in {cfg['endpoint_key']} {tid}")
            if gx >= cfg["expected_width"] or gy >= cfg["expected_height"]:
                fail(
                    f"v056 global coordinate outside frozen scan dimensions "
                    f"{cfg['endpoint_key']} {tid}: ({gx},{gy})"
                )

            checked += 1

        if max(abs(x - ext_x0) for x in dxs) > 1e-6:
            fail(
                f"x coordinate convention mismatch in {cfg['endpoint_key']} {tid}: "
                f"expected offset {ext_x0}"
            )

        if max(abs(y - ext_y0) for y in dys) > 1e-6:
            fail(
                f"y coordinate convention mismatch in {cfg['endpoint_key']} {tid}: "
                f"expected offset {ext_y0}"
            )

        per_tile[str(tid)] = {
            "requested_x0": x0,
            "requested_y0": y0,
            "extended_x0": ext_x0,
            "extended_y0": ext_y0,
            "candidate_rows_checked": len(g),
        }

    return {
        "status": "PASS",
        "coordinate_definition":
            "zero-based native FITS x=global_x, y=global_y; local coordinates are relative to 64px-halo extraction",
        "candidate_rows_checked": checked,
        "tiles_checked": len(per_tile),
        "per_tile": per_tile,
    }


# -------------------------------------------------------------------------------------------------
# FITS provenance and morphology
# -------------------------------------------------------------------------------------------------

def open_exact_scan(cfg):
    p = cfg["scan"]
    if not p.is_file():
        fail(f"Missing acquired physical scan: {p}")

    if p.stat().st_size != cfg["scan_bytes"]:
        fail(
            f"Physical scan byte count changed {p.name}: "
            f"{p.stat().st_size} != {cfg['scan_bytes']}"
        )

    actual_sha = sha256(p)
    if actual_sha != cfg["scan_sha256"]:
        fail(
            f"Physical scan SHA mismatch {p.name}:\n"
            f"expected {cfg['scan_sha256']}\nactual   {actual_sha}"
        )

    # Raw stored FITS image values avoid any implicit resampling and keep the
    # large images memory-map compatible. Positive linear FITS scaling/offset
    # does not change the frozen morphology ratios/moments after local background
    # subtraction; BITPIX/BSCALE/BZERO are recorded below.
    hdul = fits.open(
        p,
        mode="readonly",
        memmap=True,
        do_not_scale_image_data=True,
        uint=False,
    )

    matching = []

    for hdu_index, hdu in enumerate(hdul):
        shape = getattr(getattr(hdu, "data", None), "shape", None)
        if shape is None or len(shape) != 2:
            continue
        if tuple(shape) == (cfg["expected_height"], cfg["expected_width"]):
            matching.append((hdu_index, hdu))

    if len(matching) != 1:
        hdul.close()
        fail(
            f"{p.name}: expected exactly one 2-D HDU with shape "
            f"{cfg['expected_height']}x{cfg['expected_width']}; found {len(matching)}"
        )

    hdu_index, hdu = matching[0]
    header = hdu.header
    data = hdu.data

    meta = {
        "endpoint_key": cfg["endpoint_key"],
        "path": str(p.relative_to(ROOT)).replace("\\", "/"),
        "size_bytes": p.stat().st_size,
        "sha256": actual_sha,
        "hdu_index": hdu_index,
        "shape_yx": list(data.shape),
        "dtype": str(data.dtype),
        "BITPIX": header.get("BITPIX"),
        "BSCALE": header.get("BSCALE", 1),
        "BZERO": header.get("BZERO", 0),
    }

    # Refuse negative FITS scaling because polarity orientation would invert.
    bscale = ffloat(meta["BSCALE"])
    if bscale is None or bscale <= 0:
        hdul.close()
        fail(f"{p.name}: non-positive/invalid BSCALE is incompatible with frozen polarity semantics")

    return hdul, data, meta


def morphology(data, gx, gy, polarity):
    ix = int(round(float(gx)))
    iy = int(round(float(gy)))

    y0, y1 = iy - R, iy + R + 1
    x0, x1 = ix - R, ix + R + 1

    if y0 < 0 or x0 < 0 or y1 > data.shape[0] or x1 > data.shape[1]:
        return None, "full_21x21_patch_unavailable"

    patch = np.asarray(data[y0:y1, x0:x1], dtype=np.float64)
    if patch.shape != (2 * R + 1, 2 * R + 1):
        return None, "full_21x21_patch_unavailable"

    yy, xx = np.mgrid[-R:R+1, -R:R+1]
    rr = np.hypot(xx, yy)
    finite = np.isfinite(patch)

    bgvals = patch[(rr >= 7) & finite]
    if len(bgvals) == 0:
        return None, "no_finite_background_pixels"

    bg = float(np.median(bgvals))
    oriented = int(polarity) * (patch - bg)
    oriented[~np.isfinite(oriented)] = 0.0
    positive = np.clip(oriented, 0.0, None)

    support = rr <= 6
    weights = positive * support
    wsum = float(weights.sum())

    f3 = float(positive[rr <= 3].sum())
    f5 = float(positive[rr <= 5].sum())
    f8 = float(positive[rr <= 8].sum())
    center = float(oriented[R, R])

    if wsum > 0:
        cx = float((weights * xx).sum() / wsum)
        cy = float((weights * yy).sum() / wsum)

        dx = xx - cx
        dy = yy - cy
        mxx = float((weights * dx * dx).sum() / wsum)
        myy = float((weights * dy * dy).sum() / wsum)
        mxy = float((weights * dx * dy).sum() / wsum)

        vals = np.linalg.eigvalsh(
            np.array([[mxx, mxy], [mxy, myy]], dtype=float)
        )
        minor = math.sqrt(max(float(vals[0]), 0.0))
        major = math.sqrt(max(float(vals[1]), 0.0))
        ell = (1.0 - minor / major) if major > 0 else None
        cent = math.hypot(cx, cy)
    else:
        major = minor = ell = cent = None

    out = {
        "background": bg,
        "positive_flux_support_r6": wsum,
        "sigma_major_px": major,
        "sigma_minor_px": minor,
        "ellipticity": ell,
        "centroid_offset_px": cent,
        "concentration_f3_f8": (f3 / f8) if f8 > 0 else None,
        "peak_to_flux5": (center / f5) if f5 > 0 else None,
        "flux3": f3,
        "flux5": f5,
        "flux8": f8,
        "oriented_center_value": center,
        "rounded_x": ix,
        "rounded_y": iy,
    }

    valid_metrics = sum(
        1 for k in METRICS
        if out.get(k) is not None and math.isfinite(float(out[k]))
    )

    if valid_metrics == 0:
        return out, "no_valid_frozen_morphology_metrics"

    return out, None


# -------------------------------------------------------------------------------------------------
# Deterministic peer selection / endpoint evaluation
# -------------------------------------------------------------------------------------------------

def select_peers(rows, science):
    gx0 = ffloat(science["global_x"])
    gy0 = ffloat(science["global_y"])
    snr0 = ffloat(science["snr"])
    pol0 = fint(science["polarity"])
    idx0 = fint(science["candidate_index"])

    if None in (gx0, gy0, snr0, pol0, idx0) or snr0 <= 0:
        fail("Frozen science candidate lacks usable SNR/polarity/position")

    eligible = []

    for r in rows:
        idx = fint(r.get("candidate_index"))
        pol = fint(r.get("polarity"))
        snr = ffloat(r.get("snr"))
        gx = ffloat(r.get("global_x"))
        gy = ffloat(r.get("global_y"))

        if None in (idx, pol, snr, gx, gy):
            continue
        if idx == idx0:
            continue
        if pol != pol0 or snr <= 0:
            continue

        dist = math.hypot(gx - gx0, gy - gy0)
        if dist < EXCLUSION_PX:
            continue

        ratio = snr / snr0
        if ratio < FALLBACK[0] or ratio > FALLBACK[1]:
            continue

        eligible.append({
            "candidate": r,
            "candidate_index": idx,
            "global_x": gx,
            "global_y": gy,
            "snr": snr,
            "polarity": pol,
            "distance_px": dist,
            "snr_ratio": ratio,
        })

    preferred = [
        q for q in eligible
        if PREF[0] <= q["snr_ratio"] <= PREF[1]
    ]

    if len(preferred) >= PREF_MIN:
        pool = preferred
        mode = "same_tile_same_polarity_preferred_snr_0.75_1.25"
    else:
        pool = eligible
        mode = "same_tile_same_polarity_fallback_snr_0.50_1.50"

    pool.sort(
        key=lambda q: (
            q["distance_px"],
            abs(math.log(q["snr_ratio"])),
            q["candidate_index"],
        )
    )

    return pool[:MAX_CONTROLS], mode, {
        "eligible_fallback_count": len(eligible),
        "eligible_preferred_count": len(preferred),
    }


def evaluate_endpoint(
    assoc_row,
    side,
    cfg,
    by_tile,
    id_map,
    data,
    pixel_meta,
):
    tid = str(assoc_row[cfg["v075_tile_field"]])
    idx = fint(assoc_row[cfg["v075_index_field"]])

    if idx is None:
        fail(f"Invalid v075 candidate index {side}")

    science = id_map.get((tid, idx))
    if science is None:
        fail(f"Frozen v056 science identity missing: {cfg['endpoint_key']} {tid} #{idx}")

    gx = ffloat(science["global_x"])
    gy = ffloat(science["global_y"])
    snr = ffloat(science["snr"])
    pol = fint(science["polarity"])

    if None in (gx, gy, snr, pol):
        fail(f"Frozen v056 science row incomplete: {cfg['endpoint_key']} {tid} #{idx}")

    target, target_error = morphology(data, gx, gy, pol)

    base = {
        "raw_match_row": str(assoc_row["raw_match_row"]),
        "population": str(assoc_row["population"]),
        "side": side,
        "endpoint_key": cfg["endpoint_key"],
        "tile_id": tid,
        "candidate_index": idx,
        "global_x": gx,
        "global_y": gy,
        "snr": snr,
        "polarity": pol,
        "scan_sha256": cfg["scan_sha256"],
        "scan_path": pixel_meta["path"],
        "hdu_index": pixel_meta["hdu_index"],
        "error": "",
    }

    if target is None:
        return {
            **base,
            "endpoint_status": "MORPHOLOGY_TARGET_UNMEASURABLE",
            "control_selection_mode": "",
            "selected_control_count": 0,
            "usable_control_count": 0,
            "outlier_metric_count": "",
            "outlier_metrics": "",
            "error": target_error,
        }, []

    peers, mode, pool_meta = select_peers(by_tile[tid], science)

    controls = []
    usable_metrics = []

    for order, q in enumerate(peers, 1):
        met, err = morphology(
            data,
            q["global_x"],
            q["global_y"],
            q["polarity"],
        )

        cr = {
            "raw_match_row": str(assoc_row["raw_match_row"]),
            "population": str(assoc_row["population"]),
            "side": side,
            "endpoint_key": cfg["endpoint_key"],
            "science_tile_id": tid,
            "science_candidate_index": idx,
            "control_order": order,
            "control_selection_mode": mode,
            "control_candidate_index": q["candidate_index"],
            "control_global_x": q["global_x"],
            "control_global_y": q["global_y"],
            "distance_from_science_px": q["distance_px"],
            "control_snr": q["snr"],
            "snr_ratio": q["snr_ratio"],
            "polarity": q["polarity"],
            "usable": met is not None,
            "error": err or "",
        }

        if met is not None:
            cr.update(met)
            usable_metrics.append(met)

        controls.append(cr)

    ep = {
        **base,
        **target,
        "control_selection_mode": mode,
        "selected_control_count": len(peers),
        "usable_control_count": len(usable_metrics),
        "eligible_preferred_count": pool_meta["eligible_preferred_count"],
        "eligible_fallback_count": pool_meta["eligible_fallback_count"],
    }

    if len(usable_metrics) < MIN_USABLE:
        ep.update({
            "endpoint_status": "INSUFFICIENT_USABLE_MATCHED_CONTROLS",
            "outlier_metric_count": "",
            "outlier_metrics": "",
            "error":
                f"only {len(usable_metrics)} usable controls from {len(peers)} selected",
        })
        return ep, controls

    outliers = []

    for metric in METRICS:
        target_value = target.get(metric)
        vals = [
            m.get(metric) for m in usable_metrics
            if m.get(metric) is not None
            and math.isfinite(float(m.get(metric)))
        ]

        med = scale = z = None

        if (
            target_value is not None
            and math.isfinite(float(target_value))
            and len(vals) >= MIN_USABLE
        ):
            med, scale = robust_scale(vals)
            if scale is not None:
                z = (float(target_value) - med) / scale

        ep[f"{metric}_control_n"] = len(vals)
        ep[f"{metric}_control_median"] = med
        ep[f"{metric}_control_robust_sigma"] = scale
        ep[f"{metric}_robust_z"] = z

        if z is not None and abs(z) >= OUTLIER_Z:
            outliers.append(metric)

    valid_target_metrics = [
        k for k in METRICS
        if target.get(k) is not None and math.isfinite(float(target[k]))
    ]

    if not valid_target_metrics:
        ep["endpoint_status"] = "MORPHOLOGY_TARGET_UNMEASURABLE"
        ep["error"] = "no valid frozen morphology metrics"
    elif outliers:
        ep["endpoint_status"] = "MORPHOLOGY_OUTLIER_VS_SNR_MATCHED_CONTROLS"
    else:
        ep["endpoint_status"] = "MORPHOLOGY_NOT_OUTLIER_VS_SNR_MATCHED_CONTROLS"

    ep["outlier_metric_count"] = len(outliers)
    ep["outlier_metrics"] = ";".join(outliers)

    return ep, controls


def pair_context(a, b):
    unresolved = {
        "INSUFFICIENT_USABLE_MATCHED_CONTROLS",
        "MORPHOLOGY_TARGET_UNMEASURABLE",
        "MORPHOLOGY_UNRESOLVED_ERROR",
    }

    if a["endpoint_status"] in unresolved or b["endpoint_status"] in unresolved:
        return "MORPHOLOGY_UNRESOLVED_ONE_OR_MORE_ENDPOINTS"

    ao = a["endpoint_status"] == "MORPHOLOGY_OUTLIER_VS_SNR_MATCHED_CONTROLS"
    bo = b["endpoint_status"] == "MORPHOLOGY_OUTLIER_VS_SNR_MATCHED_CONTROLS"

    if ao and bo:
        return "MORPHOLOGY_OUTLIER_BOTH_ENDPOINTS"
    if ao or bo:
        return "MORPHOLOGY_OUTLIER_ONE_ENDPOINT"
    return "NO_MORPHOLOGY_OUTLIER_EITHER_ENDPOINT"


# -------------------------------------------------------------------------------------------------
# Main
# -------------------------------------------------------------------------------------------------

def main():
    print("=" * 132)
    print("PAIR 17 — MATCHED-PEER NATIVE-PIXEL MORPHOLOGY v076")
    print("=" * 132)
    print("Contextual evidence only.")
    print("Network:              DISALLOWED")
    print("Detector rerun:       NO")
    print("Registration rerun:   NO")
    print("Catalogue requery:    NO")
    print("Disposition changes:  NONE")
    print()

    block_network()

    for p, expected in EXPECTED_SHA.items():
        if not p.is_file():
            fail(f"Missing frozen input: {p}")
        actual = sha256(p)
        if actual.lower() != expected.lower():
            fail(
                f"Frozen SHA mismatch:\n{p}\n"
                f"expected {expected}\nactual   {actual}"
            )
        print("HASH PASS:", p.relative_to(ROOT))

    contract = json.loads(CONTRACT.read_text(encoding="utf-8-sig"))
    if contract.get("contract_id") != "pair17_matched_peer_morphology_v076":
        fail("Wrong v076 contract id")

    # Acquisition manifests are provenance only, but must confirm completed exact scans.
    if not ACQ_JSON.is_file() or not ACQ_CSV.is_file():
        fail("Missing completed v076 scan-acquisition manifests")

    acq = json.loads(ACQ_JSON.read_text(encoding="utf-8"))
    if acq.get("status") != "COMPLETE":
        fail("v076 scan acquisition is not COMPLETE")
    if acq.get("contract_sha256") != EXPECTED_SHA[CONTRACT]:
        fail("v076 acquisition manifest is tied to a different contract")

    rows = load_v075_rows()
    expected_hashes = expected_v056_hashes_from_v075_manifest()

    endpoint_data = {}
    all_candidate_manifest = []

    # Coordinate preflight occurs before opening science image arrays.
    for side, cfg in ENDPOINTS.items():
        full, by_tile, id_map, manifest = load_endpoint_candidates(
            cfg, expected_hashes
        )
        geom = preflight_tile_geometry(full, cfg)

        endpoint_data[side] = {
            "full": full,
            "by_tile": by_tile,
            "id_map": id_map,
            "geometry": geom,
        }
        all_candidate_manifest.extend(manifest)

        print()
        print(f"{side} {cfg['endpoint_key']} coordinate preflight: PASS")
        print(f"  tiles checked:          {geom['tiles_checked']}")
        print(f"  candidate rows checked: {geom['candidate_rows_checked']}")

    # Verify every v075 target identity exists before reading target pixels.
    for _, r in rows.iterrows():
        for side, cfg in ENDPOINTS.items():
            tid = str(r[cfg["v075_tile_field"]])
            idx = fint(r[cfg["v075_index_field"]])
            if idx is None or (tid, idx) not in endpoint_data[side]["id_map"]:
                fail(
                    f"v075 target identity missing before pixel read: "
                    f"{side} {cfg['endpoint_key']} {tid} #{idx}"
                )

    print()
    print("All 603 pair identities resolved against frozen v056 candidates: PASS")

    # Only now open exact physical scan arrays.
    hduls = {}
    pixel_meta = {}

    try:
        for side, cfg in ENDPOINTS.items():
            hdul, data, meta = open_exact_scan(cfg)
            hduls[side] = hdul
            endpoint_data[side]["pixels"] = data
            pixel_meta[side] = meta

            print()
            print(f"{side} physical scan verified:")
            print(f"  {meta['path']}")
            print(f"  SHA256 {meta['sha256']}")
            print(f"  shape  {meta['shape_yx']}")
            print(f"  dtype  {meta['dtype']}")

        endpoint_rows = []
        control_rows = []
        pair_rows = []

        for n, (_, assoc) in enumerate(rows.iterrows(), 1):
            a, ac = evaluate_endpoint(
                assoc,
                "A",
                ENDPOINTS["A"],
                endpoint_data["A"]["by_tile"],
                endpoint_data["A"]["id_map"],
                endpoint_data["A"]["pixels"],
                pixel_meta["A"],
            )
            b, bc = evaluate_endpoint(
                assoc,
                "B",
                ENDPOINTS["B"],
                endpoint_data["B"]["by_tile"],
                endpoint_data["B"]["id_map"],
                endpoint_data["B"]["pixels"],
                pixel_meta["B"],
            )

            endpoint_rows.extend([a, b])
            control_rows.extend(ac)
            control_rows.extend(bc)

            pair_rows.append({
                "raw_match_row": str(assoc["raw_match_row"]),
                "population": str(assoc["population"]),
                "a_endpoint_status": a["endpoint_status"],
                "b_endpoint_status": b["endpoint_status"],
                "a_control_count": a.get("usable_control_count", 0),
                "b_control_count": b.get("usable_control_count", 0),
                "a_outlier_metric_count": a.get("outlier_metric_count", ""),
                "b_outlier_metric_count": b.get("outlier_metric_count", ""),
                "a_outlier_metrics": a.get("outlier_metrics", ""),
                "b_outlier_metrics": b.get("outlier_metrics", ""),
                "pair_morphology_context": pair_context(a, b),
                "candidate_disposition_changed": False,
            })

            if n % 50 == 0 or n == len(rows):
                print(f"Processed {n}/{len(rows)} pair associations", flush=True)

    finally:
        for h in hduls.values():
            try:
                h.close()
            except Exception:
                pass

    if len(endpoint_rows) != 2 * EXPECTED_TOTAL:
        fail(f"Endpoint output row count changed: {len(endpoint_rows)}")
    if len(pair_rows) != EXPECTED_TOTAL:
        fail(f"Pair output row count changed: {len(pair_rows)}")

    def aggregate(pop):
        z = [r for r in pair_rows if r["population"] == pop]
        return {
            "n": len(z),
            "pair_context_counts":
                dict(sorted(Counter(r["pair_morphology_context"] for r in z).items())),
            "endpoint_a_status_counts":
                dict(sorted(Counter(r["a_endpoint_status"] for r in z).items())),
            "endpoint_b_status_counts":
                dict(sorted(Counter(r["b_endpoint_status"] for r in z).items())),
        }

    # Pixel provenance output.
    pixel_manifest = []
    for side, meta in pixel_meta.items():
        pixel_manifest.append({
            "side": side,
            **meta,
            "coordinate_preflight_status":
                endpoint_data[side]["geometry"]["status"],
            "coordinate_definition":
                endpoint_data[side]["geometry"]["coordinate_definition"],
            "tiles_checked":
                endpoint_data[side]["geometry"]["tiles_checked"],
            "candidate_rows_checked":
                endpoint_data[side]["geometry"]["candidate_rows_checked"],
        })

    endpoint_fields = sorted({k for r in endpoint_rows for k in r})
    control_fields = sorted({k for r in control_rows for k in r}) if control_rows else ["empty"]
    pair_fields = list(pair_rows[0].keys())
    pixel_fields = sorted({k for r in pixel_manifest for k in r})

    atomic_csv(OUT_ENDPOINT, endpoint_rows, endpoint_fields)
    atomic_csv(OUT_CONTROL, control_rows, control_fields)
    atomic_csv(OUT_PAIR, pair_rows, pair_fields)
    atomic_csv(OUT_PIXEL_MANIFEST, pixel_manifest, pixel_fields)

    report = {
        "status": "COMPLETE",
        "analysis_kind": "pair17_matched_peer_morphology_v076",
        "contract_sha256": EXPECTED_SHA[CONTRACT],
        "population": {
            "all": EXPECTED_TOTAL,
            "primary": EXPECTED_PRIMARY,
            "diagnostic": EXPECTED_DIAGNOSTIC,
        },
        "fixed_method": {
            "native_patch_shape": [21, 21],
            "patch_radius_px": R,
            "same_tile": True,
            "same_polarity": True,
            "exclude_within_science_px": EXCLUSION_PX,
            "preferred_snr_ratio": list(PREF),
            "preferred_minimum_controls": PREF_MIN,
            "fallback_snr_ratio": list(FALLBACK),
            "maximum_controls": MAX_CONTROLS,
            "minimum_usable_controls": MIN_USABLE,
            "robust_outlier_abs_z": OUTLIER_Z,
            "metrics": METRICS,
        },
        "coordinate_preflight": {
            side: endpoint_data[side]["geometry"]
            for side in ENDPOINTS
        },
        "pixel_provenance": pixel_meta,
        "aggregate": {
            "PRIMARY_424": aggregate("PRIMARY_424"),
            "DIAGNOSTIC_179": aggregate("DIAGNOSTIC_179"),
            "ALL_603": {
                "n": len(pair_rows),
                "pair_context_counts":
                    dict(sorted(Counter(r["pair_morphology_context"] for r in pair_rows).items())),
            },
        },
        "guards": {
            "network_calls": 0,
            "detector_rerun": False,
            "registration_rerun": False,
            "catalogue_requery": False,
            "candidate_disposition_changes": False,
            "manual_review": False,
        },
        "interpretation_boundary": (
            "Morphology is contextual only. Ordinary morphology does not establish "
            "persistence; compact/outlier morphology does not establish transience or "
            "artifact. No candidate disposition is changed by v076."
        ),
        "outputs": {
            "endpoint_metrics":
                str(OUT_ENDPOINT.relative_to(ROOT)).replace("\\", "/"),
            "control_metrics":
                str(OUT_CONTROL.relative_to(ROOT)).replace("\\", "/"),
            "pair_summary":
                str(OUT_PAIR.relative_to(ROOT)).replace("\\", "/"),
            "pixel_manifest":
                str(OUT_PIXEL_MANIFEST.relative_to(ROOT)).replace("\\", "/"),
        },
    }

    atomic_json(OUT_REPORT, report)

    print()
    print("=" * 132)
    print("v076 MORPHOLOGY COMPLETE")
    print("=" * 132)

    for pop in ("PRIMARY_424", "DIAGNOSTIC_179"):
        agg = report["aggregate"][pop]
        print(pop)
        for k, v in agg["pair_context_counts"].items():
            print(f"  {k}: {v}")

    print()
    print("Morphology interpreted as proof of transience: NO")
    print("Morphology alone changed disposition:         NO")
    print("Network calls:                               0")
    print("Detector reruns:                             0")
    print("Registrations rerun:                         0")
    print("Candidate dispositions changed:              NONE")
    print("STAGE STATUS: COMPLETE")


if __name__ == "__main__":
    main()
