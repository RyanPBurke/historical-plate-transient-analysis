from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from dataclasses import fields
import csv
import hashlib
import inspect
import json
import math

import numpy as np
from scipy.ndimage import gaussian_filter

ROOT = Path.cwd()

BASE = ROOT / "results" / "order01_native_full_v028"
WORK = ROOT / "work" / "order01_native_full_v028"
CONTROL_WORK = ROOT / "work" / "order01_injection_recovery_v028"
CACHE = CONTROL_WORK / "endpoint_cache"

PS1_REPORT = BASE / "order01_ps1_static_report_v028.json"
PS1_TRIAGE = BASE / "order01_ps1_static_triage_v028.csv"
MORPH_REPORT = BASE / "order01_matched_peer_morphology_v028" / "order01_matched_peer_morphology_report_v028.json"
MORPH_ENDPOINT = BASE / "order01_matched_peer_morphology_v028" / "order01_matched_peer_endpoint_metrics_v028.csv"
PAIR_REPORT = BASE / "order01_whole_pair_report.json"

DETECTOR_PATH = ROOT / "src" / "transient_pipeline" / "detector.py"
METHOD_PATH = ROOT / "config" / "frozen_method.json"

OUT_REPORT = BASE / "order01_injection_recovery_report_v028.json"
OUT_SUMMARY = BASE / "order01_injection_recovery_summary_v028.csv"
OUT_DETAIL = BASE / "order01_injection_recovery_detail_v028.csv"
OUT_POSITIONS = BASE / "order01_injection_positions_v028.csv"

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

EXPECTED_SURVIVORS = [5, 6, 8, 10, 12, 24, 25, 26, 29, 30, 36]

# ----------------------------------------------------------------------
# FROZEN INJECTION/RECOVERY CONTROL DESIGN
# Identical to completed Order-61 v028b.
# ----------------------------------------------------------------------
PSF_SIGMAS_PX = [1.0, 2.0, 3.0]
TARGET_DETECTOR_SNRS = [3.5, 4.0, 4.5, 5.0, 6.0, 8.0, 10.0, 12.0]
INJECTION_POLARITIES = [-1, +1]

N_INJECTION_POSITIONS = 24
INJECTION_MATCH_RADIUS_PX = 3.0
BASELINE_EXCLUSION_RADIUS_PX = 8.0
LOCAL_OFFSETS_PX = [-384, -256, -128, 128, 256, 384]
FALLBACK_STEP_PX = 128
STAMP_RADIUS_PX = 16
EXPECTED_DETECTOR_EDGE_PX = 30
RECOVERY_LEVELS = [0.50, 0.90]

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




def load_tile_inventory(tile_dir: Path, archive: str):
    """
    Resolve native geometry from completed tile metadata rather than any
    pair-specific full-plate shape constant.
    """
    if not tile_dir.is_dir():
        raise RuntimeError(f"Missing {archive} tile directory: {tile_dir}")

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
        npy_ref = obj.get("npy_path")
        if not tid or not isinstance(core, list) or len(core) != 4:
            continue
        if not isinstance(ext, list) or len(ext) != 4 or not npy_ref:
            continue

        p = Path(str(npy_ref))
        if not p.is_absolute():
            p = ROOT / p
        if not p.is_file():
            raise RuntimeError(
                f"{archive} {tid}: completed tile metadata references missing NPY {p}"
            )

        actual = sha256_file(p)
        recorded = str(obj.get("npy_file_sha256") or "").strip().lower()
        if recorded and recorded != actual:
            raise RuntimeError(
                f"{archive} {tid}: completed NPY SHA mismatch"
            )

        if tid in out:
            raise RuntimeError(f"{archive}: duplicate completed tile metadata for {tid}")

        out[tid] = {
            "archive": archive,
            "tile_id": tid,
            "core": tuple(int(x) for x in core),
            "extended": tuple(int(x) for x in ext),
            "shape": tuple(int(x) for x in obj.get("shape", [])),
            "npy_path": p,
            "npy_sha256": actual,
            "meta_path": jp,
        }

    if not out:
        raise RuntimeError(f"{archive}: no completed tile metadata found")
    return out


TILE_INVENTORY = {}
ARRAY_CACHE = {}


def load_tile(archive, tile_id):
    key = (archive, tile_id)
    if key in ARRAY_CACHE:
        return ARRAY_CACHE[key]

    inv = TILE_INVENTORY[archive]
    if tile_id not in inv:
        raise RuntimeError(f"{archive}: no completed tile metadata for {tile_id}")

    meta = inv[tile_id]
    arr = np.load(meta["npy_path"], mmap_mode="r")
    if arr.ndim != 2:
        raise RuntimeError(f"{archive} {tile_id}: expected 2-D NPY, got {arr.shape}")

    ex0, ex1, ey0, ey1 = meta["extended"]
    expected = (ey1 - ey0, ex1 - ex0)
    if tuple(arr.shape) != expected:
        raise RuntimeError(
            f"{archive} {tile_id}: NPY shape {arr.shape} != completed metadata {expected}"
        )
    if meta["shape"] and tuple(arr.shape) != meta["shape"]:
        raise RuntimeError(
            f"{archive} {tile_id}: NPY shape {arr.shape} != recorded shape {meta['shape']}"
        )

    ARRAY_CACHE[key] = (arr, meta["npy_path"], meta)
    return ARRAY_CACHE[key]


def choose_positions(
    archive,
    tile_id,
    science_global_x,
    science_global_y,
    baseline_pts_local,
):
    meta = TILE_INVENTORY[archive][tile_id]
    x0, x1, y0, y1 = meta["core"]
    ex0, ex1, ey0, ey1 = meta["extended"]

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

    for dy in LOCAL_OFFSETS_PX:
        for dx in LOCAL_OFFSETS_PX:
            gx = int(round(science_global_x + dx))
            gy = int(round(science_global_y + dy))
            if valid(gx, gy):
                dist = float(math.hypot(gx - science_global_x, gy - science_global_y))
                candidates.append((dist, gy, gx))

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
            f"{archive} {tile_id}: only {len(selected)} valid deterministic injection "
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


def checkpoint_path(rank, archive):
    CACHE.mkdir(parents=True, exist_ok=True)
    return CACHE / f"rank{rank:02d}_{archive.lower()}.json"


def write_endpoint_checkpoint(rank, archive, payload):
    p = checkpoint_path(rank, archive)
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )
    tmp.replace(p)


def read_endpoint_checkpoint(rank, archive, fingerprint):
    p = checkpoint_path(rank, archive)
    if not p.is_file():
        return None
    obj = json.loads(p.read_text(encoding="utf-8"))
    if obj.get("complete") is not True:
        return None
    if obj.get("fingerprint") != fingerprint:
        raise RuntimeError(
            f"REFUSING: stale/incompatible injection checkpoint for rank {rank} {archive}"
        )
    return obj

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
    print("=" * 100)
    print("ORDER 01 — RESUMABLE FROZEN-DETECTOR NATIVE-PIXEL INJECTION / RECOVERY CONTROL v028")
    print("=" * 100)
    print(
        "All 11 Gaia+PS1-clean ranks; both archives; both polarities; "
        "fixed Order-61 PSF/amplitude grid."
    )
    print("Completed endpoints are checkpointed and skipped on rerun.")
    print()

    required = (
        PS1_REPORT,
        PS1_TRIAGE,
        MORPH_REPORT,
        MORPH_ENDPOINT,
        PAIR_REPORT,
        DETECTOR_PATH,
        METHOD_PATH,
    )
    for p in required:
        if not p.is_file():
            raise RuntimeError(f"Missing required input: {p}")

    pair_report = json.loads(PAIR_REPORT.read_text(encoding="utf-8"))
    ps1_report = json.loads(PS1_REPORT.read_text(encoding="utf-8"))
    morph_report = json.loads(MORPH_REPORT.read_text(encoding="utf-8"))

    guards = {
        "pair_complete": pair_report.get("status") == "COMPLETE",
        "order": int(pair_report.get("canonical_order", -1)) == 1,
        "policy": pair_report.get("policy_sha256") == EXPECTED_POLICY_SHA,
        "raw10": int(pair_report.get("raw_le_10arcsec", -1)) == 476,
        "strict3": int(pair_report.get("raw_le_3arcsec", -1)) == 38,
        "ps1_complete": ps1_report.get("status") == "COMPLETE",
        "ps1_survivors": (
            [int(x) for x in ps1_report.get("survivor_ranks_5arcsec", [])]
            == EXPECTED_SURVIVORS
        ),
        "ps1_no_detector": ps1_report.get("detector_rerun") is False,
        "ps1_no_pixels": ps1_report.get("image_pixels_read") is False,
        "morph_complete": morph_report.get("status") == "COMPLETE",
        "morph_ranks": (
            [int(x) for x in morph_report.get("input_survivor_ranks", [])]
            == EXPECTED_SURVIVORS
        ),
        "morph_no_detector": morph_report.get("detector_rerun") is False,
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

    global TILE_INVENTORY
    TILE_INVENTORY = {
        "POSS": load_tile_inventory(WORK / "poss_tiles", "POSS"),
        "DASCH": load_tile_inventory(WORK / "dasch_tiles", "DASCH"),
    }

    morph_rows = read_csv(MORPH_ENDPOINT)
    morph_by_key = {
        (int(r["strict_rank"]), str(r["archive"]).upper()): r
        for r in morph_rows
    }

    expected_keys = {
        (rank, archive)
        for rank in EXPECTED_SURVIVORS
        for archive in ("POSS", "DASCH")
    }
    if set(morph_by_key) != expected_keys:
        raise RuntimeError(
            "REFUSING: morphology endpoint key set differs from expected "
            f"22 endpoints; got={sorted(morph_by_key)}"
        )
    if any(
        morph_by_key[k].get("endpoint_status") != "MATCHED_PEER_MORPHOLOGY_COMPLETE"
        for k in expected_keys
    ):
        raise RuntimeError(
            "REFUSING: one or more PS1 survivors lacks a completed morphology endpoint"
        )

    print("Completed-stage guards: PASS")
    print("Frozen detector/method hashes: PASS")
    print(
        f"Completed tile inventory: POSS={len(TILE_INVENTORY['POSS'])} "
        f"DASCH={len(TILE_INVENTORY['DASCH'])}"
    )
    print(
        "Injection design: "
        f"{len(PSF_SIGMAS_PX)} widths x "
        f"{len(TARGET_DETECTOR_SNRS)} amplitudes x "
        f"{len(INJECTION_POLARITIES)} polarities x "
        f"{N_INJECTION_POSITIONS} positions per endpoint"
    )
    print(
        f"Total synthetic-source outcomes if all endpoints run: "
        f"{len(EXPECTED_SURVIVORS)*2*len(PSF_SIGMAS_PX)*len(TARGET_DETECTOR_SNRS)*len(INJECTION_POLARITIES)*N_INJECTION_POSITIONS}"
    )
    print(
        f"Baseline-peak exclusion: {BASELINE_EXCLUSION_RADIUS_PX:.0f}px "
        "(fixed Order-61 v028b geometry-derived amendment)"
    )
    print()

    # ------------------------------------------------------------------
    # Preflight all endpoint backgrounds before any new injection outcome.
    # Baseline detect_array runs are controls, not science reclassification.
    # ------------------------------------------------------------------
    endpoint_preflight = {}

    print("Preflighting deterministic injection positions on all 22 endpoints ...")
    for rank in EXPECTED_SURVIVORS:
        for archive in ("POSS", "DASCH"):
            m = morph_by_key[(rank, archive)]
            tile_id = str(m["tile_id"])
            science_x = float(m["global_x"])
            science_y = float(m["global_y"])
            observed_snr = float(m["snr"])
            observed_pol = int(float(m["polarity"]))
            observed_sigma_major = float(m["sigma_major_px"])

            base, npy_path, meta = load_tile(archive, tile_id)
            baseline = detect_array(np.asarray(base), method)
            baseline_pts = baseline_peak_xy(baseline)

            positions = choose_positions(
                archive,
                tile_id,
                science_x,
                science_y,
                baseline_pts,
            )
            if len(positions) != N_INJECTION_POSITIONS:
                raise RuntimeError(
                    f"REFUSING: {rank}/{archive} preflight returned "
                    f"{len(positions)} positions"
                )

            fingerprint_obj = {
                "rank": rank,
                "archive": archive,
                "tile_id": tile_id,
                "tile_npy_sha256": meta["npy_sha256"],
                "science_x": science_x,
                "science_y": science_y,
                "observed_snr": observed_snr,
                "observed_pol": observed_pol,
                "observed_sigma_major": observed_sigma_major,
                "detector_sha256": EXPECTED_DETECTOR_SHA,
                "method_sha256": EXPECTED_METHOD_SHA,
                "psf_sigmas": PSF_SIGMAS_PX,
                "target_snrs": TARGET_DETECTOR_SNRS,
                "polarities": INJECTION_POLARITIES,
                "positions": positions,
                "baseline_sigma": float(baseline["sigma"]),
            }
            fingerprint = hashlib.sha256(
                json.dumps(
                    fingerprint_obj, sort_keys=True, separators=(",", ":")
                ).encode("utf-8")
            ).hexdigest()

            endpoint_preflight[(rank, archive)] = {
                "tile_id": tile_id,
                "science_x": science_x,
                "science_y": science_y,
                "observed_snr": observed_snr,
                "observed_pol": observed_pol,
                "observed_sigma_major": observed_sigma_major,
                "base": base,
                "npy_path": npy_path,
                "meta": meta,
                "baseline": baseline,
                "positions": positions,
                "fingerprint": fingerprint,
            }

            cached = read_endpoint_checkpoint(rank, archive, fingerprint)
            tag = "CACHED" if cached is not None else "READY "
            print(
                f"  [{tag} rank {rank:02d} {archive:5s}] "
                f"tile={tile_id} baseline_peaks={len(baseline['x'])} "
                f"positions={len(positions)} PASS",
                flush=True,
            )

    if len(endpoint_preflight) != len(EXPECTED_SURVIVORS) * 2:
        raise RuntimeError("REFUSING: endpoint preflight count mismatch")

    print("All 22 endpoint position preflights: PASS")
    print("Beginning/resuming fixed injection/recovery grid ...")
    print()

    # Each endpoint is independently checkpointed.
    for rank in EXPECTED_SURVIVORS:
        for archive in ("POSS", "DASCH"):
            pf = endpoint_preflight[(rank, archive)]
            cached = read_endpoint_checkpoint(
                rank, archive, pf["fingerprint"]
            )
            if cached is not None:
                print(
                    f"[rank {rank:02d} {archive:5s}] CACHED complete",
                    flush=True,
                )
                continue

            tile_id = pf["tile_id"]
            observed_snr = pf["observed_snr"]
            observed_pol = pf["observed_pol"]
            observed_sigma_major = pf["observed_sigma_major"]
            base = pf["base"]
            npy_path = pf["npy_path"]
            baseline = pf["baseline"]
            positions = pf["positions"]

            print(
                f"[rank {rank:02d} {archive:5s}] RUNNING "
                f"tile={tile_id} observed={observed_snr:.2f} "
                f"pol={observed_pol:+d} baseline_sigma={float(baseline['sigma']):.3f}",
                flush=True,
            )

            endpoint_summary_rows = []
            endpoint_detail_rows = []

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
                        rec = match_recovery(det, positions, polarity)

                        recovered_snrs = [
                            float(q["recovered_snr"])
                            for q in rec
                            if q["recovered"] and q["recovered_snr"] is not None
                        ]
                        n_rec = len(recovered_snrs)
                        frac = n_rec / len(positions)

                        row = {
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
                                if recovered_snrs else None
                            ),
                            "min_recovered_snr": (
                                min(recovered_snrs) if recovered_snrs else None
                            ),
                            "max_recovered_snr": (
                                max(recovered_snrs) if recovered_snrs else None
                            ),
                            "n_quantization_clipped": clipped,
                        }
                        endpoint_summary_rows.append(row)

                        for p, q in zip(positions, rec):
                            endpoint_detail_rows.append({
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

            matching = [
                r for r in endpoint_summary_rows
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
                            q, key=lambda z: float(z["target_detector_snr"])
                        )
                    ],
                }

            endpoint_summary = {
                "strict_rank": rank,
                "archive": archive,
                "tile_id": tile_id,
                "native_npy": str(npy_path),
                "native_npy_sha256": pf["meta"]["npy_sha256"],
                "observed_candidate_snr": observed_snr,
                "observed_candidate_polarity": observed_pol,
                "observed_sigma_major_px": observed_sigma_major,
                "baseline_detector_sigma": float(baseline["sigma"]),
                "baseline_peak_count_full_extracted_tile": len(baseline["x"]),
                "n_injection_positions": len(positions),
                "matching_polarity_recovery_by_width": width_summary,
            }

            payload = {
                "complete": True,
                "fingerprint": pf["fingerprint"],
                "endpoint_summary": endpoint_summary,
                "positions": positions,
                "summary_rows": endpoint_summary_rows,
                "detail_rows": endpoint_detail_rows,
            }
            write_endpoint_checkpoint(rank, archive, payload)

            print(
                f"[rank {rank:02d} {archive:5s}] COMPLETE "
                f"grid_rows={len(endpoint_summary_rows)} "
                f"outcomes={len(endpoint_detail_rows)}",
                flush=True,
            )

    # Aggregate only after every endpoint checkpoint is complete and compatible.
    endpoint_summaries = []
    position_rows = []
    summary_rows = []
    detail_rows = []

    for rank in EXPECTED_SURVIVORS:
        for archive in ("POSS", "DASCH"):
            pf = endpoint_preflight[(rank, archive)]
            obj = read_endpoint_checkpoint(rank, archive, pf["fingerprint"])
            if obj is None:
                raise RuntimeError(
                    f"REFUSING: missing completed checkpoint rank {rank} {archive}"
                )

            endpoint_summaries.append(obj["endpoint_summary"])
            for p in obj["positions"]:
                position_rows.append({
                    "strict_rank": rank,
                    "archive": archive,
                    "tile_id": pf["tile_id"],
                    **p,
                })
            summary_rows.extend(obj["summary_rows"])
            detail_rows.extend(obj["detail_rows"])

    expected_summary = (
        len(EXPECTED_SURVIVORS) * 2
        * len(INJECTION_POLARITIES)
        * len(PSF_SIGMAS_PX)
        * len(TARGET_DETECTOR_SNRS)
    )
    expected_detail = expected_summary * N_INJECTION_POSITIONS

    if len(summary_rows) != expected_summary:
        raise RuntimeError(
            f"REFUSING: summary rows {len(summary_rows)} != {expected_summary}"
        )
    if len(detail_rows) != expected_detail:
        raise RuntimeError(
            f"REFUSING: detail outcomes {len(detail_rows)} != {expected_detail}"
        )

    write_csv(OUT_POSITIONS, position_rows, POSITION_FIELDS)
    write_csv(OUT_SUMMARY, summary_rows, SUMMARY_FIELDS)
    write_csv(OUT_DETAIL, detail_rows, DETAIL_FIELDS)

    clipping_total = sum(
        int(r["n_quantization_clipped"]) for r in summary_rows
    )

    out_report = {
        "status": "COMPLETE",
        "analysis_kind":
            "order01_native_frozen_detector_injection_recovery_v028",
        "guards": guards,
        "detector_sha256": EXPECTED_DETECTOR_SHA,
        "method_sha256": EXPECTED_METHOD_SHA,
        "policy_sha256": EXPECTED_POLICY_SHA,
        "survivor_ranks": EXPECTED_SURVIVORS,
        "fixed_injection_design": {
            "policy_origin": "completed_order61_injection_recovery_v028b",
            "psf_model": "circular_gaussian_raw_pixel_injection",
            "psf_sigmas_px": PSF_SIGMAS_PX,
            "target_detector_snrs": TARGET_DETECTOR_SNRS,
            "polarities": INJECTION_POLARITIES,
            "positions_per_endpoint": N_INJECTION_POSITIONS,
            "position_selection": (
                "deterministic local lattice around science candidate, then "
                "globally anchored tile-core fallback; positions within "
                f"{BASELINE_EXCLUSION_RADIUS_PX:.0f}px of any baseline "
                "frozen-detector peak excluded"
            ),
            "position_preflight_all_endpoints_before_injection": True,
            "simultaneous_injections_per_run": N_INJECTION_POSITIONS,
            "recovery_match_radius_px": INJECTION_MATCH_RADIUS_PX,
            "recovery_requires_same_polarity": True,
            "detector_edge_px_respected": EXPECTED_DETECTOR_EDGE_PX,
            "native_integer_requantization": True,
            "detector_threshold_retuned": False,
        },
        "execution_generalisation": {
            "pair_specific_full_plate_shapes_hardcoded": False,
            "tile_geometry_source": "completed per-tile execution metadata",
            "endpoint_checkpointing": True,
            "resume_skips_hash-compatible_completed_endpoints": True,
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
            "endpoint_cache": str(CACHE),
        },
        "next_stage": (
            "Interpret recovery sensitivity against each observed endpoint SNR. "
            "Then run a blind independent historical-plate recurrence stage for "
            "the Gaia+PS1-clean candidates, prioritising morphology-clean rank 30 "
            "but retaining all 11 unless a predeclared veto applies."
        ),
    }
    write_json(OUT_REPORT, out_report)

    print()
    print("=" * 100)
    print("ORDER 01 INJECTION / RECOVERY CONTROL COMPLETE")
    print("=" * 100)
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
            f"  strict #{int(e['strict_rank']):02d} {e['archive']:5s} "
            f"obs={float(e['observed_candidate_snr']):.2f} "
            f"pol={int(e['observed_candidate_polarity']):+d}: "
            + ", ".join(vals)
        )

    print()
    print("Outputs:")
    print(" ", OUT_REPORT)
    print(" ", OUT_POSITIONS)
    print(" ", OUT_SUMMARY)
    print(" ", OUT_DETAIL)
    print(" ", CACHE)
    print()
    print("Frozen detect_array was used for all recovery tests.")
    print("No detector parameter was changed.")
    print("No science candidate was deleted.")


if __name__ == "__main__":
    main()
