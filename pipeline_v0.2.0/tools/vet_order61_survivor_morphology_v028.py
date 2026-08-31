from __future__ import annotations

from collections import defaultdict
from pathlib import Path
import csv
import json
import math
import re

import numpy as np

ROOT = Path.cwd()

RESULTS = ROOT / "results" / "order61_native_full_v028"
WORK = ROOT / "work" / "order61_native_full_v028"

GAIA = RESULTS / "order61_gaia_static_triage.csv"
STRICT = RESULTS / "order61_strict_match_triage.csv"
POSS_CAND = RESULTS / "order61_poss_native_candidates.csv"
DASCH_CAND = RESULTS / "order61_dasch_native_candidates.csv"
REPORT = RESULTS / "order61_whole_pair_report.json"

OUT = RESULTS / "order61_survivor_native_morphology.csv"
OUT_REPORT = RESULTS / "order61_survivor_native_morphology_report.json"
CUTOUT_DIR = RESULTS / "order61_survivor_native_cutouts"

EXPECTED_POLICY_SHA = (
    "44fc3453c3291a7cbe72894d781729a3"
    "0943ad540aa169b2c0897b446c5c8ec7"
)
EXPECTED_DETECTOR_SHA = (
    "709da8d7a7972b15808d70a1e4dbffa"
    "0fd0fee864a81d954f74fe4a5f5af25e7"
)
EXPECTED_METHOD_SHA = (
    "2cb3cabd573d7af99399899f2ccecd30"
    "02be90297e55bb0e0dcdd9dea1d0c4c1"
)

HALO = 64
CUT_RADIUS = 20
PEER_MAX = 250

POSS_SHAPE_XY = (14000, 13999)
DASCH_SHAPE_XY = (17410, 22041)

# Diagnostic-only morphology flags fixed before looking at cutout outcomes.
PLATEAU_FLAG_COUNT = 4
ELLIPTICITY_FLAG = 0.60
CENTROID_OFFSET_FLAG_PX = 1.50
PEER_EXTREME_LOW_PCT = 1.0
PEER_EXTREME_HIGH_PCT = 99.0

FIELDS = [
    "strict_rank",
    "gaia_class",
    "gaia_clean_5arcsec",
    "pair_separation_arcsec",
    "same_polarity",
    "min_snr",

    "poss_tile_id",
    "poss_candidate_index",
    "poss_global_x",
    "poss_global_y",
    "poss_snr",
    "poss_polarity",
    "poss_local_bg",
    "poss_local_sigma",
    "poss_peak_bgsub_polarity",
    "poss_centroid_offset_px",
    "poss_sigma_major_px",
    "poss_sigma_minor_px",
    "poss_ellipticity",
    "poss_peak_to_flux5",
    "poss_concentration_flux3_flux8",
    "poss_plateau_count_3x3",
    "poss_local_extreme_count_3x3",
    "poss_ellipticity_peer_percentile",
    "poss_peak_to_flux5_peer_percentile",
    "poss_centroid_offset_peer_percentile",
    "poss_plateau_peer_percentile",
    "poss_flag_plateau",
    "poss_flag_elongated",
    "poss_flag_centroid_offset",
    "poss_flag_peer_extreme",
    "poss_peer_count",

    "dasch_tile_id",
    "dasch_candidate_index",
    "dasch_global_x",
    "dasch_global_y",
    "dasch_snr",
    "dasch_polarity",
    "dasch_local_bg",
    "dasch_local_sigma",
    "dasch_peak_bgsub_polarity",
    "dasch_centroid_offset_px",
    "dasch_sigma_major_px",
    "dasch_sigma_minor_px",
    "dasch_ellipticity",
    "dasch_peak_to_flux5",
    "dasch_concentration_flux3_flux8",
    "dasch_plateau_count_3x3",
    "dasch_local_extreme_count_3x3",
    "dasch_ellipticity_peer_percentile",
    "dasch_peak_to_flux5_peer_percentile",
    "dasch_centroid_offset_peer_percentile",
    "dasch_plateau_peer_percentile",
    "dasch_flag_plateau",
    "dasch_flag_elongated",
    "dasch_flag_centroid_offset",
    "dasch_flag_peer_extreme",
    "dasch_peer_count",

    "registration_ref_count",
    "registration_median_east_arcsec",
    "registration_median_north_arcsec",
    "pair_east_offset_arcsec",
    "pair_north_offset_arcsec",
    "registration_residual_arcsec",

    "endpoint_morphology_flag_count",
    "cutout_npz",
]


def read_csv(path: Path):
    with path.open(newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def write_csv(path: Path, rows):
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
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
    try:
        x = float(str(v).strip())
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


def pick(row, aliases):
    lower = {str(k).lower(): v for k, v in row.items()}
    for name in aliases:
        if name.lower() in lower:
            return lower[name.lower()]
    return None


TILE_RE = re.compile(
    r"^[PD]_x(?P<x0>\d+)-(?P<x1>\d+)_y(?P<y0>\d+)-(?P<y1>\d+)$"
)


def parse_tile(tile_id):
    m = TILE_RE.match(tile_id)
    if not m:
        raise RuntimeError(f"Unparseable tile id: {tile_id}")
    return tuple(int(m.group(k)) for k in ("x0", "x1", "y0", "y1"))


def ext_bounds(tile_id, full_shape_xy):
    x0, x1, y0, y1 = parse_tile(tile_id)
    nx, ny = full_shape_xy
    return (
        max(0, x0 - HALO),
        min(nx, x1 + HALO),
        max(0, y0 - HALO),
        min(ny, y1 + HALO),
    )


def row_tile(row):
    v = pick(row, ["tile_id", "tile", "detector_tile_id"])
    return "" if v is None else str(v).strip()


def row_snr(row):
    return ffloat(pick(row, ["snr", "candidate_snr"]))


def row_pol(row):
    return fint(pick(row, ["polarity", "candidate_polarity"]))


def row_radec(row):
    ra = ffloat(pick(row, ["ra_deg", "ra", "icrs_ra_deg"]))
    dec = ffloat(pick(row, ["dec_deg", "dec", "icrs_dec_deg"]))
    return ra, dec


XY_ALIASES = [
    ("global_x", "global_y"),
    ("global_x_px", "global_y_px"),
    ("x_global", "y_global"),
    ("x_full", "y_full"),
    ("full_x", "full_y"),
    ("x_px", "y_px"),
    ("x", "y"),
]


def resolve_global_xy(row, tile_id, full_shape_xy):
    x0, x1, y0, y1 = parse_tile(tile_id)
    ex0, ex1, ey0, ey1 = ext_bounds(tile_id, full_shape_xy)

    lower = {str(k).lower(): v for k, v in row.items()}

    candidates = []
    for xa, ya in XY_ALIASES:
        if xa.lower() not in lower or ya.lower() not in lower:
            continue
        x = ffloat(lower[xa.lower()])
        y = ffloat(lower[ya.lower()])
        if x is None or y is None:
            continue
        candidates.append((xa, ya, x, y))

    if not candidates:
        raise RuntimeError(
            f"No usable x/y columns for tile {tile_id}; columns={sorted(row.keys())}"
        )

    # Prefer a coordinate pair already lying in the non-overlapping global core.
    for xa, ya, x, y in candidates:
        if x0 <= x < x1 and y0 <= y < y1:
            return x, y, f"{xa}/{ya}:global"

    # Otherwise interpret it as extracted-array-local coordinates and verify
    # that conversion lands in the accepted core.
    for xa, ya, x, y in candidates:
        gx = ex0 + x
        gy = ey0 + y
        if x0 <= gx < x1 and y0 <= gy < y1:
            return gx, gy, f"{xa}/{ya}:local_plus_ext"

    raise RuntimeError(
        f"Could not place candidate coordinates inside core for {tile_id}: "
        + repr(candidates[:6])
    )


def build_tile_index(rows):
    out = defaultdict(list)
    for i, r in enumerate(rows):
        r = dict(r)
        r["_aggregate_row_index"] = i
        out[row_tile(r)].append(r)
    return out


def match_candidate(rows, target_index, tile_id, target_snr, target_ra, target_dec):
    # First: explicit candidate index field.
    index_aliases = [
        "candidate_index", "index", "candidate_id", "peak_index"
    ]
    direct = []
    for r in rows:
        idx = fint(pick(r, index_aliases))
        if idx is not None and idx == target_index:
            direct.append(r)

    # Second: aggregate row index, accepting either 0- or 1-based conventions.
    if not direct:
        for r in rows:
            ai = int(r["_aggregate_row_index"])
            if ai == target_index or ai + 1 == target_index:
                direct.append(r)

    def score(r):
        s = 0.0
        if row_tile(r) == tile_id:
            s += 1000.0

        rs = row_snr(r)
        if rs is not None and target_snr is not None:
            s -= abs(rs - target_snr) * 50.0

        ra, dec = row_radec(r)
        if (
            ra is not None and dec is not None
            and target_ra is not None and target_dec is not None
        ):
            dra = (ra - target_ra) * math.cos(math.radians(target_dec))
            ddec = dec - target_dec
            arcsec = math.hypot(dra, ddec) * 3600.0
            s -= arcsec * 10.0

        return s

    if direct:
        best = max(direct, key=score)
        if row_tile(best) == tile_id:
            return best

    # Robust fallback: search the tile by SNR/sky position.
    pool = [r for r in rows if row_tile(r) == tile_id]
    if not pool:
        raise RuntimeError(f"No aggregate candidate rows for tile {tile_id}")

    best = max(pool, key=score)

    rs = row_snr(best)
    if (
        target_snr is not None and rs is not None
        and abs(rs - target_snr) > 0.02
    ):
        raise RuntimeError(
            f"Candidate-index fallback for {tile_id} failed SNR validation: "
            f"wanted {target_snr}, got {rs}"
        )

    return best


def find_npy(tile_id):
    # Prefer direct filename matches.
    hits = list(WORK.rglob(f"*{tile_id}*.npy"))
    if hits:
        hits.sort(key=lambda p: (len(str(p)), str(p)))
        return hits[0]

    # Fall back to completed metadata JSON references.
    for jp in WORK.rglob("*.json"):
        if tile_id not in jp.name:
            continue
        try:
            obj = json.loads(jp.read_text(encoding="utf-8"))
        except Exception:
            continue

        stack = [obj]
        refs = []
        while stack:
            v = stack.pop()
            if isinstance(v, dict):
                stack.extend(v.values())
            elif isinstance(v, list):
                stack.extend(v)
            elif isinstance(v, str) and v.lower().endswith(".npy"):
                refs.append(v)

        for ref in refs:
            p = Path(ref)
            if not p.is_absolute():
                p = ROOT / p
            if p.is_file():
                return p

    raise RuntimeError(f"Native tile NPY not found for {tile_id}")


ARRAY_CACHE = {}


def load_tile(tile_id, full_shape_xy):
    if tile_id in ARRAY_CACHE:
        return ARRAY_CACHE[tile_id]

    p = find_npy(tile_id)
    arr = np.load(p, mmap_mode="r")

    if arr.ndim != 2:
        raise RuntimeError(f"{tile_id}: expected 2-D NPY, got {arr.shape}")

    ex0, ex1, ey0, ey1 = ext_bounds(tile_id, full_shape_xy)
    expected = (ey1 - ey0, ex1 - ex0)

    if tuple(arr.shape) != expected:
        raise RuntimeError(
            f"{tile_id}: NPY shape {arr.shape} != expected extracted shape {expected}"
        )

    ARRAY_CACHE[tile_id] = (arr, p, (ex0, ex1, ey0, ey1))
    return ARRAY_CACHE[tile_id]


def morphology(arr, lx, ly, polarity):
    ix = int(round(lx))
    iy = int(round(ly))

    r = CUT_RADIUS
    y0, y1 = iy - r, iy + r + 1
    x0, x1 = ix - r, ix + r + 1

    if y0 < 0 or x0 < 0 or y1 > arr.shape[0] or x1 > arr.shape[1]:
        raise RuntimeError(
            f"Candidate lacks full {2*r+1}x{2*r+1} morphology cutout"
        )

    cut = np.asarray(arr[y0:y1, x0:x1], dtype=float)
    yy, xx = np.indices(cut.shape)
    cx = cy = r
    rr = np.hypot(xx - cx, yy - cy)

    ann = cut[(rr >= 12) & (rr <= 20) & np.isfinite(cut)]
    if ann.size < 100:
        raise RuntimeError("Insufficient finite morphology annulus")

    bg = float(np.median(ann))
    mad = float(np.median(np.abs(ann - bg)))
    sigma = 1.4826 * mad

    if not math.isfinite(sigma) or sigma <= 0:
        raise RuntimeError(f"Invalid local morphology sigma: {sigma}")

    oriented = int(polarity) * (cut - bg)
    oriented[~np.isfinite(oriented)] = 0.0
    positive = np.clip(oriented, 0.0, None)

    peak = float(oriented[cy, cx])

    def flux(rad):
        return float(positive[rr <= rad].sum())

    f3 = flux(3)
    f5 = flux(5)
    f8 = flux(8)

    weights = positive * (rr <= 6)
    wsum = float(weights.sum())

    if wsum > 0:
        dx = float((weights * (xx - cx)).sum() / wsum)
        dy = float((weights * (yy - cy)).sum() / wsum)

        ux = (xx - cx) - dx
        uy = (yy - cy) - dy

        mxx = float((weights * ux * ux).sum() / wsum)
        myy = float((weights * uy * uy).sum() / wsum)
        mxy = float((weights * ux * uy).sum() / wsum)

        cov = np.array([[mxx, mxy], [mxy, myy]], dtype=float)
        vals = np.linalg.eigvalsh(cov)
        vals = np.clip(vals, 0, None)

        sigma_minor = float(math.sqrt(vals[0]))
        sigma_major = float(math.sqrt(vals[1]))
        ellipticity = (
            1.0 - sigma_minor / sigma_major
            if sigma_major > 0
            else 1.0
        )
        centroid_offset = float(math.hypot(dx, dy))
    else:
        sigma_minor = sigma_major = float("nan")
        ellipticity = float("nan")
        centroid_offset = float("nan")

    core3 = cut[cy-1:cy+2, cx-1:cx+2]
    center_raw = cut[cy, cx]
    plateau_count = int(np.count_nonzero(core3 == center_raw))

    if polarity >= 0:
        extreme = np.nanmax(cut)
    else:
        extreme = np.nanmin(cut)
    local_extreme_count = int(np.count_nonzero(core3 == extreme))

    return {
        "cutout": cut,
        "local_bg": bg,
        "local_sigma": sigma,
        "peak_bgsub_polarity": peak,
        "centroid_offset_px": centroid_offset,
        "sigma_major_px": sigma_major,
        "sigma_minor_px": sigma_minor,
        "ellipticity": ellipticity,
        "peak_to_flux5": peak / f5 if f5 > 0 else float("nan"),
        "concentration_flux3_flux8": f3 / f8 if f8 > 0 else float("nan"),
        "plateau_count_3x3": plateau_count,
        "local_extreme_count_3x3": local_extreme_count,
    }


def percentile(value, values):
    vals = np.asarray(
        [x for x in values if x is not None and math.isfinite(float(x))],
        dtype=float,
    )
    if vals.size == 0 or value is None or not math.isfinite(float(value)):
        return None
    return float(100.0 * np.mean(vals <= float(value)))


PEER_CACHE = {}


def peer_metrics(tile_id, tile_rows, full_shape_xy, target_polarity):
    key = (tile_id, int(target_polarity))
    if key in PEER_CACHE:
        return PEER_CACHE[key]

    pool = [
        r for r in tile_rows
        if row_pol(r) == int(target_polarity)
    ]

    if not pool:
        PEER_CACHE[key] = []
        return []

    # Deterministic spatial/order-independent-ish sampling from the existing
    # frozen candidate list: evenly spaced row positions, no outcome tuning.
    if len(pool) > PEER_MAX:
        sel = np.linspace(0, len(pool) - 1, PEER_MAX, dtype=int)
        pool = [pool[i] for i in sel]

    arr, _, (ex0, ex1, ey0, ey1) = load_tile(tile_id, full_shape_xy)

    out = []
    for r in pool:
        try:
            gx, gy, _ = resolve_global_xy(r, tile_id, full_shape_xy)
            lx, ly = gx - ex0, gy - ey0
            out.append(morphology(arr, lx, ly, target_polarity))
        except Exception:
            continue

    PEER_CACHE[key] = out
    return out


def endpoint(
    prefix,
    strict_row,
    cand_rows_all,
    cand_by_tile,
    full_shape_xy,
):
    tile = str(strict_row[f"{prefix}_tile_id"])
    idx = int(strict_row[f"{prefix}_candidate_index"])
    target_snr = float(strict_row[f"{prefix}_snr"])
    target_ra = float(strict_row[f"{prefix}_ra_deg"])
    target_dec = float(strict_row[f"{prefix}_dec_deg"])
    polarity = int(strict_row[f"{prefix}_polarity"])

    row = match_candidate(
        cand_rows_all,
        idx,
        tile,
        target_snr,
        target_ra,
        target_dec,
    )

    gx, gy, coord_source = resolve_global_xy(row, tile, full_shape_xy)

    arr, npy_path, (ex0, ex1, ey0, ey1) = load_tile(tile, full_shape_xy)
    lx, ly = gx - ex0, gy - ey0

    m = morphology(arr, lx, ly, polarity)

    peers = peer_metrics(
        tile,
        cand_by_tile[tile],
        full_shape_xy,
        polarity,
    )

    def pp(name):
        return percentile(
            m[name],
            [q[name] for q in peers],
        )

    ell_pct = pp("ellipticity")
    sharp_pct = pp("peak_to_flux5")
    cent_pct = pp("centroid_offset_px")
    plat_pct = pp("plateau_count_3x3")

    flag_plateau = (
        m["plateau_count_3x3"] >= PLATEAU_FLAG_COUNT
        or m["local_extreme_count_3x3"] >= PLATEAU_FLAG_COUNT
    )
    flag_elongated = (
        math.isfinite(m["ellipticity"])
        and m["ellipticity"] >= ELLIPTICITY_FLAG
    )
    flag_centroid = (
        math.isfinite(m["centroid_offset_px"])
        and m["centroid_offset_px"] >= CENTROID_OFFSET_FLAG_PX
    )

    peer_extreme = False
    for q in (ell_pct, sharp_pct, cent_pct, plat_pct):
        if q is not None and (
            q <= PEER_EXTREME_LOW_PCT
            or q >= PEER_EXTREME_HIGH_PCT
        ):
            peer_extreme = True

    return {
        "tile_id": tile,
        "candidate_index": idx,
        "global_x": gx,
        "global_y": gy,
        "snr": target_snr,
        "polarity": polarity,
        "coord_source": coord_source,
        "npy_path": str(npy_path),
        "cutout": m.pop("cutout"),
        **m,
        "ellipticity_peer_percentile": ell_pct,
        "peak_to_flux5_peer_percentile": sharp_pct,
        "centroid_offset_peer_percentile": cent_pct,
        "plateau_peer_percentile": plat_pct,
        "flag_plateau": flag_plateau,
        "flag_elongated": flag_elongated,
        "flag_centroid_offset": flag_centroid,
        "flag_peer_extreme": peer_extreme,
        "peer_count": len(peers),
    }


def main():
    print("=" * 88)
    print("ORDER 61 — GAIA-SURVIVOR NATIVE MORPHOLOGY / REGISTRATION VETTING")
    print("=" * 88)
    print("No detector run. No threshold retuning. All 12 Gaia-3\" survivors are retained.")
    print()

    for p in (GAIA, STRICT, POSS_CAND, DASCH_CAND, REPORT):
        if not p.is_file():
            raise RuntimeError(f"Missing required file: {p}")

    report = json.loads(REPORT.read_text(encoding="utf-8"))

    guards = {
        "status": report.get("status") == "COMPLETE",
        "order": int(report.get("canonical_order", -1)) == 61,
        "detector": report.get("detector_sha256") == EXPECTED_DETECTOR_SHA,
        "method": report.get("method_sha256") == EXPECTED_METHOD_SHA,
        "policy": report.get("policy_sha256") == EXPECTED_POLICY_SHA,
        "raw10": int(report.get("raw_le_10arcsec", -1)) == 235,
        "strict3": int(report.get("raw_le_3arcsec", -1)) == 23,
    }
    if not all(guards.values()):
        raise RuntimeError("REFUSING: completed-result guard failure: " + repr(guards))

    gaia_rows = read_csv(GAIA)
    strict_rows = read_csv(STRICT)
    poss_rows = read_csv(POSS_CAND)
    dasch_rows = read_csv(DASCH_CAND)

    if len(gaia_rows) != 23 or len(strict_rows) != 23:
        raise RuntimeError("REFUSING: expected exactly 23 strict/Gaia audit rows")

    survivors = [
        r for r in gaia_rows
        if as_bool(r["survives_conservative_gaia_3arcsec_any_endpoint_gate"])
    ]

    if len(survivors) != 12:
        raise RuntimeError(
            f"REFUSING: expected 12 Gaia-3\" survivors from completed stage, got {len(survivors)}"
        )

    strict_by_rank = {int(r["strict_rank"]): r for r in strict_rows}

    # Registration reference: only strict pairs where the same Gaia source
    # is within 3" of BOTH endpoints at the historical epoch.
    gaia_both_ranks = {
        int(r["strict_rank"])
        for r in gaia_rows
        if as_bool(r["gaia_both_endpoints_within_3arcsec"])
    }

    ref_vec = []
    for rank in sorted(gaia_both_ranks):
        r = strict_by_rank[rank]
        ref_vec.append((
            float(r["east_offset_arcsec"]),
            float(r["north_offset_arcsec"]),
        ))

    if len(ref_vec) < 3:
        raise RuntimeError(
            f"REFUSING: insufficient Gaia-both strong registration references: {len(ref_vec)}"
        )

    ref_e = float(np.median([x for x, y in ref_vec]))
    ref_n = float(np.median([y for x, y in ref_vec]))

    poss_by_tile = build_tile_index(poss_rows)
    dasch_by_tile = build_tile_index(dasch_rows)

    CUTOUT_DIR.mkdir(parents=True, exist_ok=True)

    out_rows = []
    gaia_clean = 0

    print("Completed-result guards: PASS")
    print(f"Gaia-3\" survivors: {len(survivors)}")
    print(f"Gaia-both registration references: {len(ref_vec)}")
    print(f"Registration median vector: east={ref_e:+.4f}\", north={ref_n:+.4f}\"")
    print()
    print("Resolving exact native pixels and measuring all survivors ...", flush=True)

    for i, g in enumerate(sorted(survivors, key=lambda r: int(r["strict_rank"])), 1):
        rank = int(g["strict_rank"])
        s = strict_by_rank[rank]

        p = endpoint(
            "poss",
            s,
            poss_rows,
            poss_by_tile,
            POSS_SHAPE_XY,
        )

        d = endpoint(
            "dasch",
            s,
            dasch_rows,
            dasch_by_tile,
            DASCH_SHAPE_XY,
        )

        east = float(s["east_offset_arcsec"])
        north = float(s["north_offset_arcsec"])
        reg_resid = float(math.hypot(east - ref_e, north - ref_n))

        clean5 = str(g["gaia_class"]) == "NO_GAIA_WITHIN_5_ARCSEC_AT_TARGET_EPOCH"
        gaia_clean += int(clean5)

        flags = sum([
            p["flag_plateau"],
            p["flag_elongated"],
            p["flag_centroid_offset"],
            p["flag_peer_extreme"],
            d["flag_plateau"],
            d["flag_elongated"],
            d["flag_centroid_offset"],
            d["flag_peer_extreme"],
        ])

        cutout_path = CUTOUT_DIR / f"strict_{rank:02d}_native_cutouts.npz"
        tmp = cutout_path.with_suffix(".npz.tmp")

        # np.savez appends .npz when given a string without the suffix;
        # use an open file object so the atomic temp filename is exact.
        with tmp.open("wb") as fh:
            np.savez_compressed(
                fh,
                poss_cutout=p["cutout"],
                dasch_cutout=d["cutout"],
                poss_tile_id=np.array(p["tile_id"]),
                dasch_tile_id=np.array(d["tile_id"]),
                poss_global_xy=np.array([p["global_x"], p["global_y"]], dtype=float),
                dasch_global_xy=np.array([d["global_x"], d["global_y"]], dtype=float),
                poss_polarity=np.array(p["polarity"], dtype=int),
                dasch_polarity=np.array(d["polarity"], dtype=int),
            )
        tmp.replace(cutout_path)

        row = {
            "strict_rank": rank,
            "gaia_class": g["gaia_class"],
            "gaia_clean_5arcsec": clean5,
            "pair_separation_arcsec": float(s["separation_arcsec"]),
            "same_polarity": as_bool(s["same_polarity"]),
            "min_snr": min(float(s["poss_snr"]), float(s["dasch_snr"])),

            "registration_ref_count": len(ref_vec),
            "registration_median_east_arcsec": ref_e,
            "registration_median_north_arcsec": ref_n,
            "pair_east_offset_arcsec": east,
            "pair_north_offset_arcsec": north,
            "registration_residual_arcsec": reg_resid,
            "endpoint_morphology_flag_count": flags,
            "cutout_npz": str(cutout_path),
        }

        for prefix, e in (("poss", p), ("dasch", d)):
            for key in (
                "tile_id",
                "candidate_index",
                "global_x",
                "global_y",
                "snr",
                "polarity",
                "local_bg",
                "local_sigma",
                "peak_bgsub_polarity",
                "centroid_offset_px",
                "sigma_major_px",
                "sigma_minor_px",
                "ellipticity",
                "peak_to_flux5",
                "concentration_flux3_flux8",
                "plateau_count_3x3",
                "local_extreme_count_3x3",
                "ellipticity_peer_percentile",
                "peak_to_flux5_peer_percentile",
                "centroid_offset_peer_percentile",
                "plateau_peer_percentile",
                "flag_plateau",
                "flag_elongated",
                "flag_centroid_offset",
                "flag_peer_extreme",
                "peer_count",
            ):
                row[f"{prefix}_{key}"] = e[key]

        out_rows.append(row)

        print(
            f"  [{i:02d}/12] strict #{rank:02d} "
            f"Gaia5={'CLEAN' if clean5 else 'DIAG ':5s} "
            f"flags={flags} reg_resid={reg_resid:.3f}\" "
            f"P[e={p['ellipticity']:.2f},c={p['centroid_offset_px']:.2f}] "
            f"D[e={d['ellipticity']:.2f},c={d['centroid_offset_px']:.2f}]",
            flush=True,
        )

    write_csv(OUT, out_rows)

    report_out = {
        "status": "COMPLETE",
        "analysis_kind": "order61_gaia_survivor_native_morphology_registration",
        "guards": guards,
        "input_survivor_count": len(out_rows),
        "gaia_clean_5arcsec_count": gaia_clean,
        "gaia_diagnostic_3to5arcsec_count": len(out_rows) - gaia_clean,
        "registration_reference": {
            "definition": "strict pairs with Gaia within 3 arcsec of both endpoints",
            "count": len(ref_vec),
            "median_east_arcsec": ref_e,
            "median_north_arcsec": ref_n,
        },
        "fixed_diagnostic_parameters": {
            "cut_radius_px": CUT_RADIUS,
            "peer_max_per_tile_polarity": PEER_MAX,
            "plateau_flag_count_3x3": PLATEAU_FLAG_COUNT,
            "ellipticity_flag": ELLIPTICITY_FLAG,
            "centroid_offset_flag_px": CENTROID_OFFSET_FLAG_PX,
            "peer_extreme_percentiles": [
                PEER_EXTREME_LOW_PCT,
                PEER_EXTREME_HIGH_PCT,
            ],
        },
        "no_candidate_deleted": True,
        "detector_rerun": False,
        "detector_parameter_retuning": False,
        "native_pixels_read": True,
        "outputs": {
            "morphology_csv": str(OUT),
            "cutout_dir": str(CUTOUT_DIR),
        },
        "next_stage": (
            "Review morphology/plateau/registration diagnostics for all 12. "
            "For survivors without obvious plate/PSF defects, perform an "
            "independent static-sky/recurrence check and injection-recovery "
            "sensitivity controls before any physical interpretation."
        ),
    }
    write_json(OUT_REPORT, report_out)

    print()
    print("=" * 88)
    print("ORDER 61 SURVIVOR MORPHOLOGY / REGISTRATION VETTING COMPLETE")
    print("=" * 88)
    print(f"Survivors retained:                {len(out_rows)}")
    print(f"No Gaia within 5\":                 {gaia_clean}")
    print(f"Gaia diagnostic 3-5\" association: {len(out_rows) - gaia_clean}")
    print()
    print("Rows ordered by fewest morphology flags, then registration residual:")
    for r in sorted(
        out_rows,
        key=lambda q: (
            int(q["endpoint_morphology_flag_count"]),
            float(q["registration_residual_arcsec"]),
            int(q["strict_rank"]),
        ),
    ):
        print(
            f"  strict #{int(r['strict_rank']):02d} "
            f"Gaia5={'clean' if r['gaia_clean_5arcsec'] else 'diag ':5s} "
            f"flags={int(r['endpoint_morphology_flag_count'])} "
            f"reg={float(r['registration_residual_arcsec']):.3f}\" "
            f"minSNR={float(r['min_snr']):.2f}"
        )

    print()
    print("Outputs:")
    print(" ", OUT_REPORT)
    print(" ", OUT)
    print(" ", CUTOUT_DIR)
    print()
    print("No detector was rerun.")
    print("No detector parameter was changed.")
    print("No candidate was deleted.")


if __name__ == "__main__":
    main()
