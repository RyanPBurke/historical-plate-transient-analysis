from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from dataclasses import fields
import csv
import hashlib
import inspect
import json
import math
import re

import numpy as np
from scipy.ndimage import gaussian_filter

ROOT = Path.cwd()

BASE = ROOT / "results" / "order61_native_full_v028"
WORK = ROOT / "work" / "order61_native_full_v028"

PS1_REPORT = BASE / "order61_ps1_static_report.json"
PS1_TRIAGE = BASE / "order61_ps1_static_triage.csv"
MORPH = BASE / "order61_survivor_native_morphology.csv"
PAIR_REPORT = BASE / "order61_whole_pair_report.json"

DETECTOR_PATH = ROOT / "src" / "transient_pipeline" / "detector.py"
METHOD_PATH = ROOT / "config" / "frozen_method.json"

OUT_REPORT = BASE / "order61_injection_recovery_report.json"
OUT_SUMMARY = BASE / "order61_injection_recovery_summary.csv"
OUT_DETAIL = BASE / "order61_injection_recovery_detail.csv"
OUT_POSITIONS = BASE / "order61_injection_positions.csv"

EXPECTED_DETECTOR_SHA = (
    "709da8d7a7972b15808d70a1e4dbffa"
    "0fd0fee864a81d954f74fe4a5f5af25e7"
)
EXPECTED_METHOD_SHA = (
    "2cb3cabd573d7af99399899f2ccecd30"
    "02be90297e55bb0e0dcdd9dea1d0c4c1"
)
EXPECTED_POLICY_SHA = (
    "44fc3453c3291a7cbe72894d781729a3"
    "0943ad540aa169b2c0897b446c5c8ec7"
)

EXPECTED_SURVIVORS = [11, 14, 20, 22]

# ----------------------------------------------------------------------
# FROZEN INJECTION/RECOVERY CONTROL DESIGN
# These values are declared before any injection outcome is inspected.
# ----------------------------------------------------------------------

PSF_SIGMAS_PX = [1.0, 2.0, 3.0]
TARGET_DETECTOR_SNRS = [3.5, 4.0, 4.5, 5.0, 6.0, 8.0, 10.0, 12.0]
INJECTION_POLARITIES = [-1, +1]

N_INJECTION_POSITIONS = 24
INJECTION_MATCH_RADIUS_PX = 3.0

# Keep synthetic controls away from existing frozen-detector peaks.
BASELINE_EXCLUSION_RADIUS_PX = 40.0

# Deterministic local lattice around each science candidate.
LOCAL_OFFSETS_PX = [-384, -256, -128, 128, 256, 384]

# Global deterministic fallback lattice, if plate/core clipping means the
# local lattice does not yield 24 valid blank positions.
FALLBACK_STEP_PX = 128

# Gaussian injection stamp. Radius 16 is >5 sigma for sigma=3.
STAMP_RADIUS_PX = 16
EXPECTED_DETECTOR_EDGE_PX = 30

# Recovery summaries are descriptive only; they are not candidate gates.
RECOVERY_LEVELS = [0.50, 0.90]

POSS_FULL_SHAPE_XY = (14000, 13999)
DASCH_FULL_SHAPE_XY = (17410, 22041)

TILE_RE = re.compile(
    r"^[PD]_x(?P<x0>\d+)-(?P<x1>\d+)_y(?P<y0>\d+)-(?P<y1>\d+)$"
)

SUMMARY_FIELDS = [
    "strict_rank",
    "archive",
    "tile_id",
    "observed_candidate_snr",
    "observed_candidate_polarity",
    "observed_sigma_major_px",
    "injection_polarity",
    "psf_sigma_px",
    "target_detector_snr",
    "baseline_detector_sigma",
    "n_positions",
    "n_recovered",
    "recovery_fraction",
    "median_recovered_snr",
    "min_recovered_snr",
    "max_recovered_snr",
    "n_quantization_clipped",
]

DETAIL_FIELDS = [
    "strict_rank",
    "archive",
    "tile_id",
    "position_index",
    "global_x",
    "global_y",
    "local_x",
    "local_y",
    "injection_polarity",
    "psf_sigma_px",
    "target_detector_snr",
    "raw_peak_amplitude_before_quantization",
    "recovered",
    "recovered_distance_px",
    "recovered_snr",
    "recovered_polarity",
    "quantization_clipped",
]

POSITION_FIELDS = [
    "strict_rank",
    "archive",
    "tile_id",
    "position_index",
    "global_x",
    "global_y",
    "local_x",
    "local_y",
    "distance_from_science_candidate_px",
    "nearest_baseline_peak_px",
]

def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def read_csv(path: Path):
    with path.open(newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def write_csv(path: Path, rows, fields_):
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields_, extrasaction="ignore")
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


def as_bool(v):
    return str(v).strip().lower() in {"true", "1", "yes", "y", "t"}


def ffloat(v):
    if v is None:
        return None
    try:
        x = float(str(v).strip())
    except Exception:
        return None
    return x if math.isfinite(x) else None


def recursive_values(obj, key):
    out = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == key:
                out.append(v)
            out.extend(recursive_values(v, key))
    elif isinstance(obj, list):
        for v in obj:
            out.extend(recursive_values(v, key))
    return out


def load_frozen_detector():
    if sha256_file(DETECTOR_PATH) != EXPECTED_DETECTOR_SHA:
        raise RuntimeError("REFUSING: frozen detector SHA256 mismatch")

    if sha256_file(METHOD_PATH) != EXPECTED_METHOD_SHA:
        raise RuntimeError("REFUSING: frozen method SHA256 mismatch")

    from transient_pipeline import detector as detmod

    source = Path(inspect.getsourcefile(detmod.detect_array)).resolve()
    if source != DETECTOR_PATH.resolve():
        raise RuntimeError(
            "REFUSING: imported detect_array is not the guarded detector.py: "
            f"{source}"
        )

    if not hasattr(detmod, "FrozenMethod"):
        raise RuntimeError("REFUSING: detector module has no FrozenMethod")

    config = json.loads(METHOD_PATH.read_text(encoding="utf-8"))
    kwargs = {}

    for fld in fields(detmod.FrozenMethod):
        vals = recursive_values(config, fld.name)

        # Deduplicate JSON-equivalent values.
        uniq = []
        for v in vals:
            if all(v != q for q in uniq):
                uniq.append(v)

        if len(uniq) != 1:
            raise RuntimeError(
                f"REFUSING: expected one frozen config value for "
                f"{fld.name!r}; found {uniq!r}"
            )

        kwargs[fld.name] = uniq[0]

    method = detmod.FrozenMethod(**kwargs)
    return detmod.detect_array, method


def parse_tile(tile_id):
    m = TILE_RE.match(tile_id)
    if not m:
        raise RuntimeError(f"Unparseable tile id: {tile_id}")
    return tuple(int(m.group(k)) for k in ("x0", "x1", "y0", "y1"))


def ext_bounds(tile_id, full_shape_xy):
    x0, x1, y0, y1 = parse_tile(tile_id)
    nx, ny = full_shape_xy
    return (
        max(0, x0 - 64),
        min(nx, x1 + 64),
        max(0, y0 - 64),
        min(ny, y1 + 64),
    )


def find_npy(tile_id):
    hits = list(WORK.rglob(f"*{tile_id}*.npy"))
    if hits:
        hits.sort(key=lambda p: (len(str(p)), str(p)))
        return hits[0]

    # Fall back to NPY references in the completed tile metadata.
    for jp in WORK.rglob("*.json"):
        if tile_id not in jp.name:
            continue
        try:
            obj = json.loads(jp.read_text(encoding="utf-8"))
        except Exception:
            continue

        stack = [obj]
        while stack:
            v = stack.pop()
            if isinstance(v, dict):
                stack.extend(v.values())
            elif isinstance(v, list):
                stack.extend(v)
            elif isinstance(v, str) and v.lower().endswith(".npy"):
                p = Path(v)
                if not p.is_absolute():
                    p = ROOT / p
                if p.is_file():
                    return p

    raise RuntimeError(f"Native tile NPY not found for {tile_id}")


ARRAY_CACHE = {}


def load_tile(tile_id, full_shape_xy):
    key = (tile_id, full_shape_xy)
    if key in ARRAY_CACHE:
        return ARRAY_CACHE[key]

    p = find_npy(tile_id)
    arr = np.load(p, mmap_mode="r")

    if arr.ndim != 2:
        raise RuntimeError(f"{tile_id}: expected 2-D NPY, got {arr.shape}")

    ex0, ex1, ey0, ey1 = ext_bounds(tile_id, full_shape_xy)
    expected = (ey1 - ey0, ex1 - ex0)

    if tuple(arr.shape) != expected:
        raise RuntimeError(
            f"{tile_id}: NPY shape {arr.shape} != expected {expected}"
        )

    ARRAY_CACHE[key] = (arr, p, (ex0, ex1, ey0, ey1))
    return ARRAY_CACHE[key]


def baseline_peak_xy(det):
    return np.column_stack([
        np.asarray(det["x"], dtype=float),
        np.asarray(det["y"], dtype=float),
    ])


def nearest_distance(x, y, pts):
    if len(pts) == 0:
        return float("inf")
    d2 = (pts[:, 0] - x) ** 2 + (pts[:, 1] - y) ** 2
    return float(np.sqrt(np.min(d2)))


def choose_positions(
    tile_id,
    full_shape_xy,
    science_global_x,
    science_global_y,
    baseline_pts_local,
):
    x0, x1, y0, y1 = parse_tile(tile_id)
    ex0, ex1, ey0, ey1 = ext_bounds(tile_id, full_shape_xy)

    margin = max(
        STAMP_RADIUS_PX + int(math.ceil(INJECTION_MATCH_RADIUS_PX)) + 2,
        EXPECTED_DETECTOR_EDGE_PX + int(math.ceil(INJECTION_MATCH_RADIUS_PX)) + 2,
    )

    def valid(gx, gy):
        if not (x0 + margin <= gx < x1 - margin):
            return False
        if not (y0 + margin <= gy < y1 - margin):
            return False

        lx = gx - ex0
        ly = gy - ey0

        if nearest_distance(lx, ly, baseline_pts_local) < BASELINE_EXCLUSION_RADIUS_PX:
            return False

        return True

    candidates = []

    # Local, deterministic lattice first.
    for dy in LOCAL_OFFSETS_PX:
        for dx in LOCAL_OFFSETS_PX:
            gx = int(round(science_global_x + dx))
            gy = int(round(science_global_y + dy))
            if valid(gx, gy):
                dist = float(math.hypot(gx - science_global_x, gy - science_global_y))
                candidates.append((dist, gy, gx))

    # Global fallback lattice anchored to the tile core.
    if len(candidates) < N_INJECTION_POSITIONS:
        gx_start = x0 + margin
        gy_start = y0 + margin

        gx_vals = range(gx_start, x1 - margin, FALLBACK_STEP_PX)
        gy_vals = range(gy_start, y1 - margin, FALLBACK_STEP_PX)

        already = {(gx, gy) for _, gy, gx in candidates}

        for gy in gy_vals:
            for gx in gx_vals:
                if (gx, gy) in already:
                    continue
                if valid(gx, gy):
                    dist = float(
                        math.hypot(gx - science_global_x, gy - science_global_y)
                    )
                    candidates.append((dist, gy, gx))

    candidates.sort(key=lambda q: (q[0], q[1], q[2]))

    # Enforce mutual spacing, so simultaneous injected sources do not overlap.
    selected = []

    for dist, gy, gx in candidates:
        if any(
            math.hypot(gx - sx, gy - sy) < 2 * STAMP_RADIUS_PX + 16
            for _, sy, sx in selected
        ):
            continue
        selected.append((dist, gy, gx))
        if len(selected) == N_INJECTION_POSITIONS:
            break

    if len(selected) != N_INJECTION_POSITIONS:
        raise RuntimeError(
            f"{tile_id}: only {len(selected)} valid deterministic injection "
            f"positions; expected {N_INJECTION_POSITIONS}"
        )

    out = []
    for i, (dist, gy, gx) in enumerate(selected, 1):
        lx = gx - ex0
        ly = gy - ey0
        out.append({
            "position_index": i,
            "global_x": gx,
            "global_y": gy,
            "local_x": lx,
            "local_y": ly,
            "distance_from_science_candidate_px": dist,
            "nearest_baseline_peak_px": nearest_distance(
                lx, ly, baseline_pts_local
            ),
        })

    return out


def gaussian_stamp(psf_sigma_px):
    r = STAMP_RADIUS_PX
    yy, xx = np.indices((2 * r + 1, 2 * r + 1), dtype=float)
    dx = xx - r
    dy = yy - r
    stamp = np.exp(
        -0.5 * (dx * dx + dy * dy) / (psf_sigma_px * psf_sigma_px)
    )
    stamp /= stamp[r, r]
    return stamp


def template_residual_response(psf_sigma_px, method):
    # Use a large zero-padded field so the response at center is not affected
    # by the finite injection-stamp boundary.
    n = 129
    c = n // 2
    yy, xx = np.indices((n, n), dtype=float)
    dx = xx - c
    dy = yy - c

    t = np.exp(
        -0.5 * (dx * dx + dy * dy) / (psf_sigma_px * psf_sigma_px)
    )
    t /= t[c, c]

    residual = t - gaussian_filter(t, method.background_sigma_px)
    response = float(abs(residual[c, c]))

    if not math.isfinite(response) or response <= 0:
        raise RuntimeError(
            f"Invalid detector residual response for sigma={psf_sigma_px}: "
            f"{response}"
        )

    return response


def quantized_injected_image(
    base,
    positions,
    stamp,
    polarity,
    raw_peak_amplitude,
):
    work = np.asarray(base, dtype=float).copy()
    r = STAMP_RADIUS_PX

    for p in positions:
        cx = int(round(p["local_x"]))
        cy = int(round(p["local_y"]))

        work[
            cy - r : cy + r + 1,
            cx - r : cx + r + 1,
        ] += float(polarity) * raw_peak_amplitude * stamp

    dtype = np.asarray(base).dtype
    clipped = 0

    if np.issubdtype(dtype, np.integer):
        info = np.iinfo(dtype)
        clipped = int(
            np.count_nonzero(
                (work < info.min) | (work > info.max)
            )
        )
        work = np.clip(work, info.min, info.max)
        work = np.rint(work).astype(dtype)
    else:
        work = work.astype(dtype)

    return work, clipped


def match_recovery(det, positions, polarity):
    x = np.asarray(det["x"], dtype=float)
    y = np.asarray(det["y"], dtype=float)
    snr = np.asarray(det["snr"], dtype=float)
    pol = np.asarray(det["polarity"], dtype=int)

    rows = []

    for p in positions:
        dx = x - float(p["local_x"])
        dy = y - float(p["local_y"])
        dist = np.hypot(dx, dy)

        idx = np.where(
            (dist <= INJECTION_MATCH_RADIUS_PX)
            & (pol == int(polarity))
        )[0]

        if len(idx):
            # Closest same-polarity recovered peak.
            j = idx[np.argmin(dist[idx])]
            rows.append({
                "recovered": True,
                "recovered_distance_px": float(dist[j]),
                "recovered_snr": float(snr[j]),
                "recovered_polarity": int(pol[j]),
            })
        else:
            rows.append({
                "recovered": False,
                "recovered_distance_px": None,
                "recovered_snr": None,
                "recovered_polarity": None,
            })

    return rows


def first_recovery_target(summary_rows, level):
    ordered = sorted(
        summary_rows,
        key=lambda r: float(r["target_detector_snr"]),
    )
    for r in ordered:
        if float(r["recovery_fraction"]) >= level:
            return float(r["target_detector_snr"])
    return None


def main():
    print("=" * 92)
    print("ORDER 61 — FROZEN-DETECTOR NATIVE-PIXEL INJECTION / RECOVERY CONTROL")
    print("=" * 92)
    print(
        "All 4 Gaia+PS1 catalogue-clean ranks; both archives; both polarities; "
        "fixed PSF/amplitude grid."
    )
    print()

    for p in (
        PS1_REPORT,
        PS1_TRIAGE,
        MORPH,
        PAIR_REPORT,
        DETECTOR_PATH,
        METHOD_PATH,
    ):
        if not p.is_file():
            raise RuntimeError(f"Missing required input: {p}")

    pair_report = json.loads(PAIR_REPORT.read_text(encoding="utf-8"))
    ps1_report = json.loads(PS1_REPORT.read_text(encoding="utf-8"))

    guards = {
        "pair_complete": pair_report.get("status") == "COMPLETE",
        "order": int(pair_report.get("canonical_order", -1)) == 61,
        "policy": pair_report.get("policy_sha256") == EXPECTED_POLICY_SHA,
        "raw10": int(pair_report.get("raw_le_10arcsec", -1)) == 235,
        "strict3": int(pair_report.get("raw_le_3arcsec", -1)) == 23,
        "ps1_complete": ps1_report.get("status") == "COMPLETE",
        "ps1_survivors": (
            [int(x) for x in ps1_report.get("survivor_ranks_5arcsec", [])]
            == EXPECTED_SURVIVORS
        ),
        "ps1_no_detector": ps1_report.get("detector_rerun") is False,
        "ps1_no_pixels": ps1_report.get("image_pixels_read") is False,
    }

    if not all(guards.values()):
        raise RuntimeError(
            "REFUSING: completed-stage guard failure: "
            + json.dumps(guards, sort_keys=True)
        )

    detect_array, method = load_frozen_detector()

    if float(method.peak_sigma) != 4.0:
        raise RuntimeError(
            f"REFUSING: expected frozen peak_sigma=4; got {method.peak_sigma}"
        )

    if int(method.edge_px) != EXPECTED_DETECTOR_EDGE_PX:
        raise RuntimeError(
            f"REFUSING: expected frozen edge_px={EXPECTED_DETECTOR_EDGE_PX}; "
            f"got {method.edge_px}"
        )

    print("Completed-stage guards: PASS")
    print("Frozen detector/method hashes: PASS")
    print(
        "Injection design: "
        f"{len(PSF_SIGMAS_PX)} widths x "
        f"{len(TARGET_DETECTOR_SNRS)} amplitudes x "
        f"{len(INJECTION_POLARITIES)} polarities x "
        f"{N_INJECTION_POSITIONS} positions per endpoint"
    )
    print()

    morph_rows = read_csv(MORPH)
    morph_by_rank = {
        int(r["strict_rank"]): r
        for r in morph_rows
    }

    missing = [
        rank for rank in EXPECTED_SURVIVORS
        if rank not in morph_by_rank
    ]
    if missing:
        raise RuntimeError(
            f"Missing morphology rows for ranks {missing}"
        )

    summary_rows = []
    detail_rows = []
    position_rows = []

    endpoint_summaries = []

    for rank in EXPECTED_SURVIVORS:
        m = morph_by_rank[rank]

        for archive in ("POSS", "DASCH"):
            prefix = archive.lower()

            tile_id = str(m[f"{prefix}_tile_id"])
            science_x = float(m[f"{prefix}_global_x"])
            science_y = float(m[f"{prefix}_global_y"])
            observed_snr = float(m[f"{prefix}_snr"])
            observed_pol = int(m[f"{prefix}_polarity"])
            observed_sigma_major = float(m[f"{prefix}_sigma_major_px"])

            full_shape = (
                POSS_FULL_SHAPE_XY
                if archive == "POSS"
                else DASCH_FULL_SHAPE_XY
            )

            base, npy_path, (ex0, ex1, ey0, ey1) = load_tile(
                tile_id,
                full_shape,
            )

            baseline = detect_array(np.asarray(base), method)
            baseline_pts = baseline_peak_xy(baseline)

            positions = choose_positions(
                tile_id,
                full_shape,
                science_x,
                science_y,
                baseline_pts,
            )

            for p in positions:
                position_rows.append({
                    "strict_rank": rank,
                    "archive": archive,
                    "tile_id": tile_id,
                    **p,
                })

            print(
                f"[rank {rank:02d} {archive:5s}] "
                f"tile={tile_id} observed={observed_snr:.2f} "
                f"pol={observed_pol:+d} baseline_sigma={float(baseline['sigma']):.3f} "
                f"positions={len(positions)}",
                flush=True,
            )

            endpoint_rows = []

            for polarity in INJECTION_POLARITIES:
                for psf_sigma in PSF_SIGMAS_PX:
                    stamp = gaussian_stamp(psf_sigma)
                    response = template_residual_response(psf_sigma, method)

                    for target_snr in TARGET_DETECTOR_SNRS:
                        raw_amp = (
                            float(target_snr)
                            * float(baseline["sigma"])
                            / response
                        )

                        injected, clipped = quantized_injected_image(
                            base,
                            positions,
                            stamp,
                            polarity,
                            raw_amp,
                        )

                        det = detect_array(injected, method)
                        rec = match_recovery(
                            det,
                            positions,
                            polarity,
                        )

                        recovered_snrs = [
                            float(q["recovered_snr"])
                            for q in rec
                            if q["recovered"]
                            and q["recovered_snr"] is not None
                        ]

                        n_rec = len(recovered_snrs)
                        frac = n_rec / len(positions)

                        summary = {
                            "strict_rank": rank,
                            "archive": archive,
                            "tile_id": tile_id,
                            "observed_candidate_snr": observed_snr,
                            "observed_candidate_polarity": observed_pol,
                            "observed_sigma_major_px": observed_sigma_major,
                            "injection_polarity": polarity,
                            "psf_sigma_px": psf_sigma,
                            "target_detector_snr": target_snr,
                            "baseline_detector_sigma": float(baseline["sigma"]),
                            "n_positions": len(positions),
                            "n_recovered": n_rec,
                            "recovery_fraction": frac,
                            "median_recovered_snr": (
                                float(np.median(recovered_snrs))
                                if recovered_snrs
                                else None
                            ),
                            "min_recovered_snr": (
                                min(recovered_snrs)
                                if recovered_snrs
                                else None
                            ),
                            "max_recovered_snr": (
                                max(recovered_snrs)
                                if recovered_snrs
                                else None
                            ),
                            "n_quantization_clipped": clipped,
                        }

                        summary_rows.append(summary)
                        endpoint_rows.append(summary)

                        for p, q in zip(positions, rec):
                            detail_rows.append({
                                "strict_rank": rank,
                                "archive": archive,
                                "tile_id": tile_id,
                                "position_index": p["position_index"],
                                "global_x": p["global_x"],
                                "global_y": p["global_y"],
                                "local_x": p["local_x"],
                                "local_y": p["local_y"],
                                "injection_polarity": polarity,
                                "psf_sigma_px": psf_sigma,
                                "target_detector_snr": target_snr,
                                "raw_peak_amplitude_before_quantization": raw_amp,
                                "recovered": q["recovered"],
                                "recovered_distance_px": q["recovered_distance_px"],
                                "recovered_snr": q["recovered_snr"],
                                "recovered_polarity": q["recovered_polarity"],
                                "quantization_clipped": clipped > 0,
                            })

            # Descriptive endpoint summary at the observed polarity only.
            matching = [
                r for r in endpoint_rows
                if int(r["injection_polarity"]) == observed_pol
            ]

            width_summary = {}

            for psf_sigma in PSF_SIGMAS_PX:
                q = [
                    r for r in matching
                    if float(r["psf_sigma_px"]) == psf_sigma
                ]

                width_summary[str(psf_sigma)] = {
                    "snr_at_50pct_recovery": first_recovery_target(q, 0.50),
                    "snr_at_90pct_recovery": first_recovery_target(q, 0.90),
                    "curve": [
                        {
                            "target_snr": float(r["target_detector_snr"]),
                            "fraction": float(r["recovery_fraction"]),
                        }
                        for r in sorted(
                            q,
                            key=lambda z: float(z["target_detector_snr"]),
                        )
                    ],
                }

            endpoint_summaries.append({
                "strict_rank": rank,
                "archive": archive,
                "tile_id": tile_id,
                "native_npy": str(npy_path),
                "observed_candidate_snr": observed_snr,
                "observed_candidate_polarity": observed_pol,
                "observed_sigma_major_px": observed_sigma_major,
                "baseline_detector_sigma": float(baseline["sigma"]),
                "baseline_peak_count_full_extracted_tile": len(baseline["x"]),
                "n_injection_positions": len(positions),
                "matching_polarity_recovery_by_width": width_summary,
            })

    write_csv(OUT_POSITIONS, position_rows, POSITION_FIELDS)
    write_csv(OUT_SUMMARY, summary_rows, SUMMARY_FIELDS)
    write_csv(OUT_DETAIL, detail_rows, DETAIL_FIELDS)

    clipping_total = sum(
        int(r["n_quantization_clipped"])
        for r in summary_rows
    )

    out_report = {
        "status": "COMPLETE",
        "analysis_kind": "order61_native_frozen_detector_injection_recovery",
        "guards": guards,
        "detector_sha256": EXPECTED_DETECTOR_SHA,
        "method_sha256": EXPECTED_METHOD_SHA,
        "policy_sha256": EXPECTED_POLICY_SHA,
        "survivor_ranks": EXPECTED_SURVIVORS,
        "fixed_injection_design": {
            "psf_model": "circular_gaussian_raw_pixel_injection",
            "psf_sigmas_px": PSF_SIGMAS_PX,
            "target_detector_snrs": TARGET_DETECTOR_SNRS,
            "polarities": INJECTION_POLARITIES,
            "positions_per_endpoint": N_INJECTION_POSITIONS,
            "position_selection": (
                "deterministic local lattice around science candidate, "
                "then globally anchored tile-core fallback; positions within "
                f"{BASELINE_EXCLUSION_RADIUS_PX:.0f}px of any baseline frozen-"
                "detector peak excluded"
            ),
            "simultaneous_injections_per_run": N_INJECTION_POSITIONS,
            "recovery_match_radius_px": INJECTION_MATCH_RADIUS_PX,
            "recovery_requires_same_polarity": True,
            "detector_edge_px_respected": EXPECTED_DETECTOR_EDGE_PX,
            "native_integer_requantization": True,
            "detector_threshold_retuned": False,
        },
        "endpoint_summaries": endpoint_summaries,
        "quantization_clipped_pixel_count_across_runs": clipping_total,
        "detector_rerun_for_control": True,
        "science_detector_parameters_changed": False,
        "science_candidates_deleted": False,
        "outputs": {
            "positions_csv": str(OUT_POSITIONS),
            "summary_csv": str(OUT_SUMMARY),
            "detail_csv": str(OUT_DETAIL),
        },
        "next_stage": (
            "Interpret sensitivity only after the fixed full grid completes. "
            "Then inspect historical recurrence/context for ranks 11,14,20,22, "
            "with special attention to whether any catalogue-clean, morphology-"
            "acceptable candidate is detectable with high recovery probability "
            "on both native plate backgrounds."
        ),
    }

    write_json(OUT_REPORT, out_report)

    print()
    print("=" * 92)
    print("ORDER 61 INJECTION / RECOVERY CONTROL COMPLETE")
    print("=" * 92)
    print(f"Catalogue-clean ranks: {EXPECTED_SURVIVORS}")
    print(f"Endpoint backgrounds:  {len(endpoint_summaries)}")
    print(f"Summary grid rows:      {len(summary_rows)}")
    print(f"Injection outcomes:     {len(detail_rows)}")
    print(f"Quantization clipping:  {clipping_total} pixels across all runs")
    print()

    print("Matching-polarity nominal SNR at >=90% recovery:")
    for e in endpoint_summaries:
        vals = []
        for width in PSF_SIGMAS_PX:
            v = e["matching_polarity_recovery_by_width"][str(width)][
                "snr_at_90pct_recovery"
            ]
            vals.append(
                f"sigma{width:g}={'none' if v is None else f'{v:g}'}"
            )

        print(
            f"  strict #{e['strict_rank']:02d} {e['archive']:5s} "
            f"obs={e['observed_candidate_snr']:.2f} "
            f"pol={e['observed_candidate_polarity']:+d}: "
            + ", ".join(vals)
        )

    print()
    print("Outputs:")
    print(" ", OUT_REPORT)
    print(" ", OUT_POSITIONS)
    print(" ", OUT_SUMMARY)
    print(" ", OUT_DETAIL)
    print()
    print("Frozen detect_array was used for all recovery tests.")
    print("No detector parameter was changed.")
    print("No science candidate was deleted.")


if __name__ == "__main__":
    main()
