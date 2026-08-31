from pathlib import Path
import argparse
import hashlib
import json
import math
import re
import shutil
import sys
import time
import warnings

try:
    import numpy as np
    import pandas as pd
    from scipy.spatial import cKDTree
    import astropy.units as u
    from astropy.coordinates import SkyCoord
    from astropy.time import Time
except Exception as exc:
    print("DEPENDENCY FAILURE:", repr(exc))
    print("Required: numpy, pandas, scipy, astropy")
    sys.exit(2)


ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "results"
RESEARCH = ROOT / "research"
WORK = ROOT / "work" / "wide_census_gaia_registration_v068"
OUT = RESULTS / "wide_census_gaia_registration_v068"

DETECTOR = RESULTS / "wide_census_detector_candidates_v056.csv"
RAW = RESULTS / "wide_census_pair_raw_matches_v056.csv"

V065 = RESULTS / "wide_census_gaia_reference_coverage_audit_v065"
PAIR_SUMMARY = (
    V065 / "wide_census_gaia_reference_coverage_pair_summary_v065.csv"
)
PAIR_CELLS = (
    V065 / "wide_census_gaia_reference_candidate_cells_v065.csv"
)

V064 = RESULTS / "wide_census_gaia_acquisition_v064"
V066 = RESULTS / "wide_census_gaia_supplemental_acquisition_v066"

V064_ORD = V064 / "cache" / "ordinary"
V066_ORD = V066 / "cache" / "ordinary"
V066_HPM = V066 / "cache" / "hpm"

STATE064 = V064 / "state_v064.json"
STATE066 = V066 / "state_v066.json"

CONTRACT = (
    RESEARCH
    / "prospective_freezes"
    / "wide_census_gaia_registration_contract_v001.json"
)

UPSTREAM = {
    RESEARCH / "prospective_freezes"
    / "wide_census_postdetector_adjudication_contract_v001.json":
        "1215400b989b187e87ceee27237fd2faf7ccff80dd57632158e06cbed7add2ad",

    RESEARCH / "prospective_freezes"
    / "wide_census_gaia_reference_acquisition_contract_v002.json":
        "458a043dfbdda8dbb853cbae77c269ff17a586c0ddb2fdcf7ac0388ee57ab3fc",

    CONTRACT:
        "bd3456356392d56b73b3f6c8e16f51a028c1a43bce6a011871b7b3d341be907b",
}

EXPECTED_PAIRS = 33
EXPECTED_RAW_LE10 = 512788
EXPECTED_RAW_LE3 = 185532
EXPECTED_DETECTOR_ROWS = 5083325

MATCH_RADIUS_ARCSEC = 15.0
SCIENCE_EXCLUSION_ARCSEC = 30.0
WINDOWS_ARCMIN = (5.0, 10.0, 20.0, 30.0)
PRIMARY_MIN_REFS = 5
SPARSE_MIN_REFS = 3

GAIA_COLUMNS = [
    "source_id",
    "ra",
    "dec",
    "ref_epoch",
    "pmra",
    "pmdec",
]

RAW_COLUMNS = [
    "pair_index",
    "separation_arcsec",
    "a_tile_id",
    "a_candidate_index",
    "a_ra_deg",
    "a_dec_deg",
    "b_tile_id",
    "b_candidate_index",
    "b_ra_deg",
    "b_dec_deg",
]

CELL_RE = re.compile(r"cell_(\d+)_(\d+)_d", re.IGNORECASE)


def sha256(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def atomic_json(path, obj):
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2)
    tmp.replace(path)


def chord_radius_arcsec(arcsec):
    rad = math.radians(arcsec / 3600.0)
    return 2.0 * math.sin(rad / 2.0)


def chord_radius_arcmin(arcmin):
    rad = math.radians(arcmin / 60.0)
    return 2.0 * math.sin(rad / 2.0)


R15 = chord_radius_arcsec(MATCH_RADIUS_ARCSEC)
R30SEC = chord_radius_arcsec(SCIENCE_EXCLUSION_ARCSEC)
R30MIN = chord_radius_arcmin(30.0)


def unit_vectors(ra_deg, dec_deg):
    ra = np.deg2rad(np.asarray(ra_deg, dtype=np.float64))
    dec = np.deg2rad(np.asarray(dec_deg, dtype=np.float64))

    c = np.cos(dec)

    return np.column_stack((
        c * np.cos(ra),
        c * np.sin(ra),
        np.sin(dec),
    ))


def midpoint_vectors(a, b):
    v = a + b
    n = np.linalg.norm(v, axis=1)

    bad = n == 0.0

    if np.any(bad):
        v[bad] = a[bad]
        n[bad] = np.linalg.norm(v[bad], axis=1)

    return v / n[:, None]


def chord_to_arcmin(chord):
    x = np.clip(np.asarray(chord) / 2.0, 0.0, 1.0)
    return np.rad2deg(2.0 * np.arcsin(x)) * 60.0


def wrap_ra_delta(deg):
    return (np.asarray(deg) + 180.0) % 360.0 - 180.0


def residual_east_north_arcsec(det_ra, det_dec, ref_ra, ref_dec):
    dra = wrap_ra_delta(
        np.asarray(det_ra, dtype=np.float64)
        - np.asarray(ref_ra, dtype=np.float64)
    )

    east = (
        dra
        * np.cos(np.deg2rad(np.asarray(ref_dec, dtype=np.float64)))
        * 3600.0
    )

    north = (
        np.asarray(det_dec, dtype=np.float64)
        - np.asarray(ref_dec, dtype=np.float64)
    ) * 3600.0

    return east, north


def raw_pair_vector_arcsec(a_ra, a_dec, b_ra, b_dec):
    mid_dec = 0.5 * (a_dec + b_dec)

    east = (
        wrap_ra_delta(b_ra - a_ra)
        * np.cos(np.deg2rad(mid_dec))
        * 3600.0
    )

    north = (b_dec - a_dec) * 3600.0

    return float(east), float(north)


def read_complete_state(path, label):
    with path.open("r", encoding="utf-8") as f:
        obj = json.load(f)

    if obj.get("status") != "COMPLETE":
        raise RuntimeError(
            f"{label} is not COMPLETE: {obj.get('status')!r}"
        )

    return obj


def build_leaf_index(directory, compressed):
    index = {}

    for p in directory.rglob("*"):
        if not p.is_file():
            continue

        n = p.name.lower()

        if ".maxrec." in n:
            continue

        if compressed:
            if not n.endswith(".csv.gz"):
                continue
        else:
            if not n.endswith(".csv"):
                continue

        m = CELL_RE.search(p.name)

        if not m:
            continue

        key = (int(m.group(1)), int(m.group(2)))
        index.setdefault(key, []).append(p)

    for paths in index.values():
        paths.sort()

    return index


def read_gaia_file(path):
    try:
        df = pd.read_csv(
            path,
            usecols=GAIA_COLUMNS,
            dtype={
                "source_id": "int64",
                "ra": "float64",
                "dec": "float64",
                "ref_epoch": "float64",
                "pmra": "float64",
                "pmdec": "float64",
            },
        )
    except pd.errors.EmptyDataError:
        return pd.DataFrame(columns=GAIA_COLUMNS)

    return df


def load_pair_gaia(pair_index, cells, idx64, idx66):
    frames = []
    missing_cells = []
    files_read = 0
    rows_transport = 0

    for cell in sorted(cells):
        paths = []
        paths.extend(idx64.get(cell, []))
        paths.extend(idx66.get(cell, []))

        if not paths:
            missing_cells.append(cell)
            continue

        for path in paths:
            df = read_gaia_file(path)

            if not df.empty:
                frames.append(df)
                rows_transport += len(df)

            files_read += 1

    if missing_cells:
        raise RuntimeError(
            "Missing resolved Gaia coverage for cells: "
            + ", ".join(str(x) for x in missing_cells[:20])
        )

    hpm = V066_HPM / f"hpm_pair_{pair_index:02d}.csv.gz"

    if not hpm.exists():
        raise RuntimeError(f"Missing corrected HPM cache: {hpm}")

    hpm_df = read_gaia_file(hpm)

    if not hpm_df.empty:
        frames.append(hpm_df)
        rows_transport += len(hpm_df)

    files_read += 1

    if not frames:
        raise RuntimeError(f"No Gaia rows loaded for pair {pair_index}")

    gaia = pd.concat(frames, ignore_index=True)

    before = len(gaia)

    gaia = gaia.drop_duplicates(
        subset=["source_id"],
        keep="first"
    ).reset_index(drop=True)

    duplicate_rows_removed = before - len(gaia)

    finite = (
        np.isfinite(gaia["ra"].to_numpy())
        & np.isfinite(gaia["dec"].to_numpy())
        & np.isfinite(gaia["ref_epoch"].to_numpy())
        & np.isfinite(gaia["pmra"].to_numpy())
        & np.isfinite(gaia["pmdec"].to_numpy())
    )

    missing_motion = int((~finite).sum())

    gaia = gaia.loc[finite].reset_index(drop=True)

    return gaia, {
        "transport_rows": int(rows_transport),
        "unique_rows_before_motion_filter": int(before - duplicate_rows_removed),
        "duplicate_rows_removed": int(duplicate_rows_removed),
        "missing_motion_excluded": int(missing_motion),
        "usable_rows": int(len(gaia)),
        "files_read": int(files_read),
    }


def propagate_gaia(df, epoch_iso, chunk_size=250000):
    n = len(df)

    out_ra = np.empty(n, dtype=np.float64)
    out_dec = np.empty(n, dtype=np.float64)

    target_time = Time(epoch_iso)

    for start in range(0, n, chunk_size):
        end = min(start + chunk_size, n)

        part = df.iloc[start:end]

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")

            coord = SkyCoord(
                ra=part["ra"].to_numpy() * u.deg,
                dec=part["dec"].to_numpy() * u.deg,
                pm_ra_cosdec=part["pmra"].to_numpy() * u.mas / u.yr,
                pm_dec=part["pmdec"].to_numpy() * u.mas / u.yr,
                obstime=Time(
                    part["ref_epoch"].to_numpy(),
                    format="jyear"
                ),
                frame="icrs",
            )

            moved = coord.apply_space_motion(
                new_obstime=target_time
            )

        out_ra[start:end] = moved.ra.deg
        out_dec[start:end] = moved.dec.deg

    return {
        "source_id": df["source_id"].to_numpy(dtype=np.int64),
        "ra": out_ra,
        "dec": out_dec,
        "vec": unit_vectors(out_ra, out_dec),
    }


def reciprocal_match(det, gaia):
    if len(det) == 0 or len(gaia["ra"]) == 0:
        return {
            "source_id": np.array([], dtype=np.int64),
            "gaia_ra": np.array([], dtype=np.float64),
            "gaia_dec": np.array([], dtype=np.float64),
            "gaia_vec": np.empty((0, 3), dtype=np.float64),
            "det_ra": np.array([], dtype=np.float64),
            "det_dec": np.array([], dtype=np.float64),
            "east": np.array([], dtype=np.float64),
            "north": np.array([], dtype=np.float64),
        }

    det_ra = det[:, 0]
    det_dec = det[:, 1]
    det_vec = unit_vectors(det_ra, det_dec)

    gvec = gaia["vec"]

    tg = cKDTree(gvec)
    td = cKDTree(det_vec)

    _, d2g = tg.query(
        det_vec,
        k=1,
        distance_upper_bound=R15,
        workers=-1,
    )

    _, g2d = td.query(
        gvec,
        k=1,
        distance_upper_bound=R15,
        workers=-1,
    )

    d_idx = np.arange(len(det_vec), dtype=np.int64)

    valid = d2g < len(gvec)

    valid_d = d_idx[valid]
    valid_g = d2g[valid]

    reciprocal = g2d[valid_g] == valid_d

    d_keep = valid_d[reciprocal]
    g_keep = valid_g[reciprocal]

    east, north = residual_east_north_arcsec(
        det_ra[d_keep],
        det_dec[d_keep],
        gaia["ra"][g_keep],
        gaia["dec"][g_keep],
    )

    return {
        "source_id": gaia["source_id"][g_keep],
        "gaia_ra": gaia["ra"][g_keep],
        "gaia_dec": gaia["dec"][g_keep],
        "gaia_vec": gvec[g_keep],
        "det_ra": det_ra[d_keep],
        "det_dec": det_dec[d_keep],
        "east": east,
        "north": north,
    }


def common_matches(a, b):
    common, ia, ib = np.intersect1d(
        a["source_id"],
        b["source_id"],
        assume_unique=True,
        return_indices=True,
    )

    return {
        "source_id": common,
        "gaia_vec": a["gaia_vec"][ia],
        "gaia_ra": a["gaia_ra"][ia],
        "gaia_dec": a["gaia_dec"][ia],
        "a_east": a["east"][ia],
        "a_north": a["north"][ia],
        "b_east": b["east"][ib],
        "b_north": b["north"][ib],
    }


def loo_medians(values):
    x = np.asarray(values, dtype=np.float64)
    n = len(x)

    if n < 2:
        return np.full(n, np.nan)

    order = np.argsort(x)
    s = x[order]

    rank = np.empty(n, dtype=np.int64)
    rank[order] = np.arange(n)

    out = np.empty(n, dtype=np.float64)

    if n % 2 == 0:
        k = n // 2

        out[rank < k] = s[k]
        out[rank >= k] = s[k - 1]

    else:
        k = n // 2

        low = rank < k
        mid = rank == k
        high = rank > k

        out[low] = 0.5 * (s[k] + s[k + 1])
        out[mid] = 0.5 * (s[k - 1] + s[k + 1])
        out[high] = 0.5 * (s[k - 1] + s[k])

    return out


def exact_loo_separation(
    raw_east,
    raw_north,
    a_e,
    a_n,
    b_e,
    b_n,
):
    ae = loo_medians(a_e)
    an = loo_medians(a_n)
    be = loo_medians(b_e)
    bn = loo_medians(b_n)

    dx = raw_east - (be - ae)
    dy = raw_north - (bn - an)

    sep = np.hypot(dx, dy)

    return float(np.nanmin(sep)), float(np.nanmax(sep))


def select_indices(tree, vecs, target_mid, target_a, target_b, radius):
    idx = tree.query_ball_point(target_mid, r=radius)

    if not idx:
        return np.array([], dtype=np.int64), np.array([], dtype=np.float64)

    idx = np.asarray(idx, dtype=np.int64)
    rv = vecs[idx]

    da = np.linalg.norm(rv - target_a, axis=1)
    db = np.linalg.norm(rv - target_b, axis=1)

    keep = (da > R30SEC) & (db > R30SEC)

    idx = idx[keep]

    if len(idx) == 0:
        return idx, np.array([], dtype=np.float64)

    dist = np.linalg.norm(vecs[idx] - target_mid, axis=1)
    arcmin = chord_to_arcmin(dist)

    return idx, arcmin


def build_endpoint_cache(endpoints):
    cache_dir = WORK / "endpoint_candidates"
    manifest_path = cache_dir / "manifest.json"

    endpoints = sorted(endpoints)

    if manifest_path.exists():
        with manifest_path.open("r", encoding="utf-8") as f:
            manifest = json.load(f)

        if (
            manifest.get("detector_size") == DETECTOR.stat().st_size
            and manifest.get("endpoints") == endpoints
            and manifest.get("source_rows") == EXPECTED_DETECTOR_ROWS
        ):
            return manifest

    if cache_dir.exists():
        shutil.rmtree(cache_dir)

    cache_dir.mkdir(parents=True, exist_ok=True)

    wanted = set(endpoints)
    buckets = {x: [] for x in endpoints}

    total_rows = 0
    retained_rows = 0

    print()
    print("Building endpoint candidate cache from v056 detector CSV...")
    t0 = time.time()

    for chunk_no, chunk in enumerate(
        pd.read_csv(
            DETECTOR,
            usecols=["endpoint_key", "ra_deg", "dec_deg"],
            chunksize=250000,
            dtype={
                "endpoint_key": "string",
                "ra_deg": "float64",
                "dec_deg": "float64",
            },
        ),
        start=1,
    ):
        total_rows += len(chunk)

        sub = chunk[chunk["endpoint_key"].isin(wanted)]

        sub = sub[
            np.isfinite(sub["ra_deg"].to_numpy())
            & np.isfinite(sub["dec_deg"].to_numpy())
        ]

        retained_rows += len(sub)

        for endpoint, grp in sub.groupby(
            "endpoint_key",
            sort=False,
            observed=True,
        ):
            buckets[str(endpoint)].append(
                grp[["ra_deg", "dec_deg"]].to_numpy(
                    dtype=np.float64,
                    copy=True,
                )
            )

        if chunk_no % 4 == 0:
            print(
                f"  detector rows scanned: {total_rows:,}",
                flush=True,
            )

    if total_rows != EXPECTED_DETECTOR_ROWS:
        raise RuntimeError(
            f"Detector row invariant failed: "
            f"{total_rows:,} != {EXPECTED_DETECTOR_ROWS:,}"
        )

    files = {}
    counts = {}

    for i, endpoint in enumerate(endpoints, start=1):
        pieces = buckets[endpoint]

        if pieces:
            arr = np.concatenate(pieces, axis=0)
        else:
            arr = np.empty((0, 2), dtype=np.float64)

        filename = f"endpoint_{i:03d}.npy"

        np.save(cache_dir / filename, arr)

        files[endpoint] = filename
        counts[endpoint] = int(len(arr))

    manifest = {
        "detector_path": str(DETECTOR),
        "detector_size": DETECTOR.stat().st_size,
        "source_rows": int(total_rows),
        "retained_rows": int(retained_rows),
        "endpoints": endpoints,
        "files": files,
        "counts": counts,
        "elapsed_s": time.time() - t0,
    }

    atomic_json(manifest_path, manifest)

    print(
        f"Endpoint cache COMPLETE: "
        f"{retained_rows:,} candidates in "
        f"{time.time() - t0:.1f}s"
    )

    return manifest


def load_endpoint(endpoint, manifest):
    path = (
        WORK
        / "endpoint_candidates"
        / manifest["files"][endpoint]
    )

    return np.load(path, mmap_mode="r")


def write_state(state):
    atomic_json(OUT / "state_v068.json", state)


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--pair",
        type=int,
        default=None,
        help="Process only one pair index."
    )

    parser.add_argument(
        "--resume",
        action="store_true",
        help="Skip already completed pair products."
    )

    args = parser.parse_args()

    OUT.mkdir(parents=True, exist_ok=True)
    WORK.mkdir(parents=True, exist_ok=True)

    print("=" * 100)
    print("WIDE CENSUS OFFLINE GAIA REGISTRATION v068")
    print("=" * 100)
    print("Scientific method: prospectively frozen v001")
    print("Network access: DISALLOWED")
    print("Detector rerun: NO")
    print("Candidate dispositions: NONE")
    print("Primary transform: translation-only componentwise median")
    print("Primary common same-Gaia minimum: 5")
    print("Local windows: 5, 10, 20, 30 arcmin")
    print("Science exclusion: 30 arcsec")
    print("Detector/Gaia reciprocal-nearest radius: 15 arcsec")
    print("Sparse fallback: >=3 refs/archive, diagnostic only")
    print()

    for path, expected in UPSTREAM.items():
        if not path.exists():
            raise RuntimeError(f"Missing frozen input: {path}")

        actual = sha256(path)

        if actual != expected:
            raise RuntimeError(
                f"Frozen SHA mismatch:\n"
                f"  {path}\n"
                f"  expected {expected}\n"
                f"  actual   {actual}"
            )

        print("HASH PASS:", path.relative_to(ROOT))

    read_complete_state(STATE064, "v064")
    read_complete_state(STATE066, "v066")

    pair_summary = pd.read_csv(PAIR_SUMMARY)
    pair_cells = pd.read_csv(PAIR_CELLS)

    if len(pair_summary) != EXPECTED_PAIRS:
        raise RuntimeError(
            f"Pair invariant failed: "
            f"{len(pair_summary)} != {EXPECTED_PAIRS}"
        )

    pair_metadata = {}

    for pair_index, grp in pair_cells.groupby("pair_index"):
        pair_index = int(pair_index)

        a = grp["endpoint_a"].drop_duplicates().tolist()
        b = grp["endpoint_b"].drop_duplicates().tolist()
        cp = grp["canonical_pair"].drop_duplicates().tolist()

        if len(a) != 1 or len(b) != 1 or len(cp) != 1:
            raise RuntimeError(
                f"Ambiguous pair metadata for pair {pair_index}"
            )

        summary_row = pair_summary[
            pair_summary["pair_index"] == pair_index
        ]

        if len(summary_row) != 1:
            raise RuntimeError(
                f"Missing/duplicate v065 pair summary: {pair_index}"
            )

        row = summary_row.iloc[0]

        cells = set(
            zip(
                grp["cell_ira"].astype(int),
                grp["cell_idec"].astype(int),
            )
        )

        pair_metadata[pair_index] = {
            "canonical_pair": cp[0],
            "endpoint_a": a[0],
            "endpoint_b": b[0],
            "cells": cells,
            "registration_epoch_utc": row["registration_epoch_utc"],
        }

    if set(pair_metadata) != set(range(1, EXPECTED_PAIRS + 1)):
        raise RuntimeError(
            "Pair indices are not exactly 1..33"
        )

    print()
    print("Loading v056 raw association population...")

    raw = pd.read_csv(
        RAW,
        usecols=RAW_COLUMNS,
        dtype={
            "pair_index": "int16",
            "separation_arcsec": "float64",
            "a_candidate_index": "int64",
            "b_candidate_index": "int64",
            "a_ra_deg": "float64",
            "a_dec_deg": "float64",
            "b_ra_deg": "float64",
            "b_dec_deg": "float64",
        },
    )

    raw.insert(
        0,
        "raw_match_row",
        np.arange(1, len(raw) + 1, dtype=np.int64),
    )

    if len(raw) != EXPECTED_RAW_LE10:
        raise RuntimeError(
            f"Raw association invariant failed: "
            f"{len(raw):,} != {EXPECTED_RAW_LE10:,}"
        )

    raw_le3 = int(
        (raw["separation_arcsec"].to_numpy() <= 3.0).sum()
    )

    if raw_le3 != EXPECTED_RAW_LE3:
        raise RuntimeError(
            f"Raw <=3 invariant failed: "
            f"{raw_le3:,} != {EXPECTED_RAW_LE3:,}"
        )

    max_raw = float(raw["separation_arcsec"].max())

    if max_raw > 10.000001:
        raise RuntimeError(
            f"Unexpected raw separation >10 arcsec: {max_raw}"
        )

    print(
        f"Raw associations verified: {len(raw):,} <=10\", "
        f"{raw_le3:,} <=3\""
    )

    endpoints = set()

    for meta in pair_metadata.values():
        endpoints.add(meta["endpoint_a"])
        endpoints.add(meta["endpoint_b"])

    endpoint_manifest = build_endpoint_cache(endpoints)

    print()
    print("Indexing resolved Gaia leaves...")

    idx64 = build_leaf_index(V064_ORD, compressed=False)
    idx66 = build_leaf_index(V066_ORD, compressed=True)

    print(
        f"v064 resolved-cell index: "
        f"{sum(len(v) for v in idx64.values()):,} leaves"
    )
    print(
        f"v066 resolved-cell index: "
        f"{sum(len(v) for v in idx66.values()):,} leaves"
    )

    if sum(len(v) for v in idx64.values()) != 6651:
        raise RuntimeError(
            "v064 resolved-leaf invariant failed"
        )

    if sum(len(v) for v in idx66.values()) != 13916:
        raise RuntimeError(
            "v066 resolved-leaf invariant failed"
        )

    script_sha = sha256(Path(__file__))

    state_path = OUT / "state_v068.json"

    if args.resume and state_path.exists():
        with state_path.open("r", encoding="utf-8") as f:
            state = json.load(f)
    else:
        state = {
            "analysis_kind":
                "wide_census_offline_gaia_registration_v068",
            "status": "RUNNING",
            "script_sha256": script_sha,
            "registration_contract_sha256":
                UPSTREAM[CONTRACT],
            "guards": {
                "network_access": False,
                "detector_rerun": False,
                "candidate_disposition_changes": False,
                "threshold_retuning": False,
            },
            "scope": {
                "raw_le10_associations": EXPECTED_RAW_LE10,
                "raw_le3_associations": EXPECTED_RAW_LE3,
                "pairs": EXPECTED_PAIRS,
            },
            "completed_pairs": [],
            "pair_summaries": {},
            "interpretation_boundary":
                "Registration only. No candidate disposition "
                "and no corrected shifted-control inference.",
        }

    if state.get("script_sha256") != script_sha:
        raise RuntimeError(
            "Existing v068 state was created by a different script SHA."
        )

    if args.pair is not None:
        if args.pair not in pair_metadata:
            raise RuntimeError(f"Invalid pair index {args.pair}")

        wanted_pairs = [args.pair]
    else:
        wanted_pairs = list(range(1, EXPECTED_PAIRS + 1))

    run_start = time.time()

    for pair_index in wanted_pairs:
        pair_file = OUT / f"pair_{pair_index:02d}_registrations_v068.csv"
        pair_json = OUT / f"pair_{pair_index:02d}_summary_v068.json"

        if (
            args.resume
            and pair_index in state.get("completed_pairs", [])
            and pair_file.exists()
            and pair_json.exists()
        ):
            print(
                f"\nPAIR {pair_index:02d}: already COMPLETE; skipping."
            )
            continue

        t0 = time.time()

        meta = pair_metadata[pair_index]

        print()
        print("=" * 100)
        print(
            f"PAIR {pair_index:02d}/33 — "
            f"{meta['canonical_pair']}"
        )
        print("=" * 100)

        det_a = load_endpoint(
            meta["endpoint_a"],
            endpoint_manifest,
        )

        det_b = load_endpoint(
            meta["endpoint_b"],
            endpoint_manifest,
        )

        pair_raw = raw[
            raw["pair_index"] == pair_index
        ].copy()

        print(
            f"Detector candidates: "
            f"A={len(det_a):,}, B={len(det_b):,}"
        )
        print(
            f"Raw pair associations: {len(pair_raw):,}; "
            f"raw <=3\": "
            f"{int((pair_raw['separation_arcsec'] <= 3.0).sum()):,}"
        )
        print(
            f"Required Gaia cells: {len(meta['cells']):,}"
        )

        gaia_df, gaia_stats = load_pair_gaia(
            pair_index,
            meta["cells"],
            idx64,
            idx66,
        )

        print(
            f"Gaia usable unique rows: "
            f"{gaia_stats['usable_rows']:,} "
            f"(transport={gaia_stats['transport_rows']:,}, "
            f"dedup removed={gaia_stats['duplicate_rows_removed']:,}, "
            f"missing motion excluded="
            f"{gaia_stats['missing_motion_excluded']:,})"
        )

        gaia = propagate_gaia(
            gaia_df,
            meta["registration_epoch_utc"],
        )

        del gaia_df

        match_a = reciprocal_match(det_a, gaia)
        match_b = reciprocal_match(det_b, gaia)

        common = common_matches(match_a, match_b)

        print(
            f"Reciprocal Gaia references: "
            f"A={len(match_a['source_id']):,}, "
            f"B={len(match_b['source_id']):,}, "
            f"same-Gaia common={len(common['source_id']):,}"
        )

        tree_common = (
            cKDTree(common["gaia_vec"])
            if len(common["source_id"])
            else None
        )

        tree_a = (
            cKDTree(match_a["gaia_vec"])
            if len(match_a["source_id"])
            else None
        )

        tree_b = (
            cKDTree(match_b["gaia_vec"])
            if len(match_b["source_id"])
            else None
        )

        a_target_vec = unit_vectors(
            pair_raw["a_ra_deg"].to_numpy(),
            pair_raw["a_dec_deg"].to_numpy(),
        )

        b_target_vec = unit_vectors(
            pair_raw["b_ra_deg"].to_numpy(),
            pair_raw["b_dec_deg"].to_numpy(),
        )

        mid_target_vec = midpoint_vectors(
            a_target_vec,
            b_target_vec,
        )

        outputs = []

        primary_count = 0
        sparse_count = 0
        none_count = 0
        corrected_le3 = 0
        raw_le3_to_corrected_le3 = 0
        raw_le3_to_corrected_gt3 = 0
        raw_gt3_to_corrected_le3 = 0

        rows_list = pair_raw.to_dict("records")

        for j, row in enumerate(rows_list):
            avec = a_target_vec[j]
            bvec = b_target_vec[j]
            midvec = mid_target_vec[j]

            mode = "NONE"
            chosen_window = np.nan
            n_common = 0
            n_a = 0
            n_b = 0

            shift_a_e = np.nan
            shift_a_n = np.nan
            shift_b_e = np.nan
            shift_b_n = np.nan

            loo_min = np.nan
            loo_max = np.nan

            selected_common = None

            if tree_common is not None:
                idx, dist_arcmin = select_indices(
                    tree_common,
                    common["gaia_vec"],
                    midvec,
                    avec,
                    bvec,
                    R30MIN,
                )

                for window in WINDOWS_ARCMIN:
                    use = idx[dist_arcmin <= window]

                    if len(use) >= PRIMARY_MIN_REFS:
                        selected_common = use
                        chosen_window = float(window)
                        break

                if selected_common is not None:
                    use = selected_common

                    n_common = int(len(use))
                    n_a = n_common
                    n_b = n_common

                    shift_a_e = float(
                        np.median(common["a_east"][use])
                    )
                    shift_a_n = float(
                        np.median(common["a_north"][use])
                    )
                    shift_b_e = float(
                        np.median(common["b_east"][use])
                    )
                    shift_b_n = float(
                        np.median(common["b_north"][use])
                    )

                    mode = "PRIMARY"
                    primary_count += 1

            if mode == "NONE":
                a_idx = np.array([], dtype=np.int64)
                b_idx = np.array([], dtype=np.int64)

                if tree_a is not None:
                    a_idx, _ = select_indices(
                        tree_a,
                        match_a["gaia_vec"],
                        midvec,
                        avec,
                        bvec,
                        R30MIN,
                    )

                if tree_b is not None:
                    b_idx, _ = select_indices(
                        tree_b,
                        match_b["gaia_vec"],
                        midvec,
                        avec,
                        bvec,
                        R30MIN,
                    )

                n_a = int(len(a_idx))
                n_b = int(len(b_idx))

                if (
                    n_a >= SPARSE_MIN_REFS
                    and n_b >= SPARSE_MIN_REFS
                ):
                    shift_a_e = float(
                        np.median(match_a["east"][a_idx])
                    )
                    shift_a_n = float(
                        np.median(match_a["north"][a_idx])
                    )
                    shift_b_e = float(
                        np.median(match_b["east"][b_idx])
                    )
                    shift_b_n = float(
                        np.median(match_b["north"][b_idx])
                    )

                    mode = "SPARSE_DIAGNOSTIC"
                    chosen_window = 30.0
                    sparse_count += 1
                else:
                    none_count += 1

            raw_e, raw_n = raw_pair_vector_arcsec(
                row["a_ra_deg"],
                row["a_dec_deg"],
                row["b_ra_deg"],
                row["b_dec_deg"],
            )

            if mode != "NONE":
                corr_e = raw_e - (shift_b_e - shift_a_e)
                corr_n = raw_n - (shift_b_n - shift_a_n)

                corr_sep = float(
                    math.hypot(corr_e, corr_n)
                )
            else:
                corr_e = np.nan
                corr_n = np.nan
                corr_sep = np.nan

            raw_is_le3 = row["separation_arcsec"] <= 3.0
            corr_is_le3 = (
                np.isfinite(corr_sep)
                and corr_sep <= 3.0
            )

            if corr_is_le3:
                corrected_le3 += 1

            if raw_is_le3 and corr_is_le3:
                raw_le3_to_corrected_le3 += 1

            if (
                raw_is_le3
                and np.isfinite(corr_sep)
                and corr_sep > 3.0
            ):
                raw_le3_to_corrected_gt3 += 1

            if (not raw_is_le3) and corr_is_le3:
                raw_gt3_to_corrected_le3 += 1

            if (
                mode == "PRIMARY"
                and corr_is_le3
                and selected_common is not None
            ):
                use = selected_common

                loo_min, loo_max = exact_loo_separation(
                    raw_e,
                    raw_n,
                    common["a_east"][use],
                    common["a_north"][use],
                    common["b_east"][use],
                    common["b_north"][use],
                )

            outputs.append({
                "raw_match_row": row["raw_match_row"],
                "pair_index": pair_index,
                "a_tile_id": row["a_tile_id"],
                "a_candidate_index": row["a_candidate_index"],
                "b_tile_id": row["b_tile_id"],
                "b_candidate_index": row["b_candidate_index"],
                "raw_separation_arcsec":
                    row["separation_arcsec"],
                "raw_le3": bool(raw_is_le3),
                "registration_mode": mode,
                "window_arcmin": chosen_window,
                "common_same_gaia_refs": n_common,
                "refs_a": n_a,
                "refs_b": n_b,
                "shift_a_east_arcsec": shift_a_e,
                "shift_a_north_arcsec": shift_a_n,
                "shift_b_east_arcsec": shift_b_e,
                "shift_b_north_arcsec": shift_b_n,
                "corrected_east_arcsec": corr_e,
                "corrected_north_arcsec": corr_n,
                "corrected_separation_arcsec": corr_sep,
                "corrected_le3": bool(corr_is_le3),
                "loo_corrected_sep_min_arcsec": loo_min,
                "loo_corrected_sep_max_arcsec": loo_max,
            })

            if (j + 1) % 10000 == 0:
                print(
                    f"  registered {j + 1:,}/{len(rows_list):,} "
                    f"raw associations...",
                    flush=True,
                )

        out_df = pd.DataFrame(outputs)

        out_df.to_csv(
            pair_file,
            index=False,
        )

        pair_summary_obj = {
            "pair_index": pair_index,
            "canonical_pair": meta["canonical_pair"],
            "endpoint_a": meta["endpoint_a"],
            "endpoint_b": meta["endpoint_b"],
            "registration_epoch_utc":
                meta["registration_epoch_utc"],
            "required_gaia_cells": len(meta["cells"]),
            "detector_candidates_a": int(len(det_a)),
            "detector_candidates_b": int(len(det_b)),
            "gaia": gaia_stats,
            "reciprocal_refs_a":
                int(len(match_a["source_id"])),
            "reciprocal_refs_b":
                int(len(match_b["source_id"])),
            "common_same_gaia_refs":
                int(len(common["source_id"])),
            "raw_le10_associations": int(len(pair_raw)),
            "raw_le3_associations":
                int((pair_raw["separation_arcsec"] <= 3.0).sum()),
            "primary_registered": int(primary_count),
            "sparse_diagnostic_registered":
                int(sparse_count),
            "unregistered": int(none_count),
            "corrected_le3": int(corrected_le3),
            "raw_le3_to_corrected_le3":
                int(raw_le3_to_corrected_le3),
            "raw_le3_to_corrected_gt3":
                int(raw_le3_to_corrected_gt3),
            "raw_gt3_to_corrected_le3":
                int(raw_gt3_to_corrected_le3),
            "elapsed_s": time.time() - t0,
            "candidate_dispositions": "NONE",
        }

        atomic_json(pair_json, pair_summary_obj)

        if pair_index not in state["completed_pairs"]:
            state["completed_pairs"].append(pair_index)
            state["completed_pairs"].sort()

        state["pair_summaries"][str(pair_index)] = (
            pair_summary_obj
        )

        write_state(state)

        print()
        print(
            f"PAIR {pair_index:02d} COMPLETE in "
            f"{time.time() - t0:.1f}s"
        )
        print(
            f"  Primary registered:       {primary_count:,}"
        )
        print(
            f"  Sparse diagnostic:       {sparse_count:,}"
        )
        print(
            f"  Unregistered:            {none_count:,}"
        )
        print(
            f"  Raw <=3\":                "
            f"{pair_summary_obj['raw_le3_associations']:,}"
        )
        print(
            f"  Corrected <=3\":          {corrected_le3:,}"
        )
        print(
            f"  <=3\" surviving:          "
            f"{raw_le3_to_corrected_le3:,}"
        )
        print(
            f"  <=3\" moving outward:     "
            f"{raw_le3_to_corrected_gt3:,}"
        )
        print(
            f"  >3\" moving inward:       "
            f"{raw_gt3_to_corrected_le3:,}"
        )

        del gaia
        del match_a
        del match_b
        del common
        del out_df
        del outputs

    if args.pair is None:
        completed = sorted(
            int(x)
            for x in state["completed_pairs"]
        )

        if completed == list(range(1, EXPECTED_PAIRS + 1)):
            summaries = [
                state["pair_summaries"][str(i)]
                for i in completed
            ]

            total_raw = sum(
                x["raw_le10_associations"]
                for x in summaries
            )

            total_raw_le3 = sum(
                x["raw_le3_associations"]
                for x in summaries
            )

            total_primary = sum(
                x["primary_registered"]
                for x in summaries
            )

            total_sparse = sum(
                x["sparse_diagnostic_registered"]
                for x in summaries
            )

            total_none = sum(
                x["unregistered"]
                for x in summaries
            )

            total_corr_le3 = sum(
                x["corrected_le3"]
                for x in summaries
            )

            outward = sum(
                x["raw_le3_to_corrected_gt3"]
                for x in summaries
            )

            inward = sum(
                x["raw_gt3_to_corrected_le3"]
                for x in summaries
            )

            surviving = sum(
                x["raw_le3_to_corrected_le3"]
                for x in summaries
            )

            state["status"] = "COMPLETE"
            state["completed_at_utc"] = (
                pd.Timestamp.utcnow().isoformat()
            )
            state["totals"] = {
                "raw_le10_associations": total_raw,
                "raw_le3_associations": total_raw_le3,
                "primary_registered": total_primary,
                "sparse_diagnostic_registered": total_sparse,
                "unregistered": total_none,
                "corrected_le3": total_corr_le3,
                "raw_le3_to_corrected_le3": surviving,
                "raw_le3_to_corrected_gt3": outward,
                "raw_gt3_to_corrected_le3": inward,
            }

            write_state(state)

            pd.DataFrame(summaries).to_csv(
                OUT / "wide_census_gaia_registration_pair_summary_v068.csv",
                index=False,
            )

            print()
            print("=" * 100)
            print("v068 OFFLINE GAIA REGISTRATION COMPLETE")
            print("=" * 100)
            print(
                f"Raw <=10\" associations:     {total_raw:,}"
            )
            print(
                f"Raw <=3\" associations:      {total_raw_le3:,}"
            )
            print(
                f"Primary registered:         {total_primary:,}"
            )
            print(
                f"Sparse diagnostic:          {total_sparse:,}"
            )
            print(
                f"Unregistered:               {total_none:,}"
            )
            print(
                f"Corrected <=3\":             {total_corr_le3:,}"
            )
            print(
                f"Raw <=3\" surviving <=3\":   {surviving:,}"
            )
            print(
                f"Raw <=3\" moving outward:   {outward:,}"
            )
            print(
                f"Raw >3\" moving inward:     {inward:,}"
            )
            print()
            print("Network calls: 0")
            print("Detector reruns: 0")
            print("Candidate dispositions changed: NONE")
            print(
                "SCIENTIFIC INTERPRETATION: "
                "registration result only; corrected shifted "
                "controls have not yet been run."
            )
            print("STAGE STATUS: COMPLETE")

        else:
            state["status"] = "PARTIAL"
            write_state(state)

    print()
    print(
        f"Invocation elapsed: "
        f"{time.time() - run_start:.1f}s"
    )


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print()
        print("=" * 100)
        print("v068 FAILED")
        print("=" * 100)
        print(type(exc).__name__ + ":", str(exc))
        print()
        print("This is an operational failure only.")
        print("No candidate disposition is implied.")
        raise
