
from __future__ import annotations

from pathlib import Path
from dataclasses import fields
from datetime import datetime, timezone
import base64
import csv
import gzip
import hashlib
import io
import json
import math
import re
import shutil
import time

import numpy as np
import astropy.units as u
from astropy.coordinates import SkyCoord, search_around_sky
from astropy.io import fits
from astropy.wcs import WCS

from transient_pipeline.config import FrozenMethod
from transient_pipeline.detector import detect_array

ROOT = Path.cwd()

CONTRACT = ROOT / "results" / "wide_census_disk_bounded_execution_contract_v055.json"
PREFLIGHT = ROOT / "results" / "wide_census_heavy_preflight_v054.json"
ENDPOINTS = ROOT / "results" / "wide_census_detector_endpoint_plan_v054.csv"
PAIRS = ROOT / "results" / "wide_census_detector_pair_plan_v054.json"
TILES = ROOT / "results" / "wide_census_detector_tile_plan_v054.csv"

APPLAUSE_WCS_CACHE = (
    ROOT / "results" / "wide_census_heavy_preflight_v054" /
    "cache" / "applause_selected_solution_rows.json"
)
DASCH_CACHE = (
    ROOT / "results" / "wide_census_exact_footprint_v052" /
    "cache" / "dasch"
)

DETECTOR = ROOT / "src" / "transient_pipeline" / "detector.py"
METHOD = ROOT / "config" / "frozen_method.json"
NATIVE_POLICY = ROOT / "research" / "NATIVE_TILE_EXECUTION_POLICY_V028_2026-08-21.json"

RESULT = ROOT / "results" / "wide_census_detector_execution_v056"
TILE_RESULT = RESULT / "tiles"
STATE = RESULT / "state_v056.json"
FAILURES = RESULT / "terminal_tile_failures_v056.json"

OUT_JSON = ROOT / "results" / "wide_census_detector_execution_v056.json"
ALL_CAND = ROOT / "results" / "wide_census_detector_candidates_v056.csv"
PAIR_SUMMARY = ROOT / "results" / "wide_census_pair_raw_match_summary_v056.csv"
RAW_MATCHES = ROOT / "results" / "wide_census_pair_raw_matches_v056.csv"

EXPECTED_DETECTOR_SHA = "709da8d7a7972b15808d70a1e4dbffa0fd0fee864a81d954f74fe4a5f5af25e7"
EXPECTED_METHOD_SHA = "2cb3cabd573d7af99399899f2ccecd3002be90297e55bb0e0dcdd9dea1d0c4c1"
EXPECTED_TILES = 6293
EXPECTED_ENDPOINTS = 53
EXPECTED_OPPS = 33
MAX_TILES_PER_CYCLE = 32
MAX_TILE_ATTEMPTS = 6
DISK_ABORT_FLOOR = 8 * 1024**3

CAND_FIELDS = [
    "endpoint_key", "kind", "exposure", "tile_id", "candidate_index",
    "local_x", "local_y", "global_x", "global_y",
    "ra_deg", "dec_deg", "snr", "signal", "polarity", "sigma",
]


def sha_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def sha_array(arr: np.ndarray) -> str:
    a = np.ascontiguousarray(arr)
    return hashlib.sha256(memoryview(a).cast("B")).hexdigest()


def safe_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value)).strip("_")


def read_csv(path):
    with path.open(newline="", encoding="utf-8-sig") as fh:
        return list(csv.DictReader(fh))


def write_json(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(obj, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )
    tmp.replace(path)


def write_csv(path, rows, fields):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    tmp.replace(path)


def inum(v):
    try:
        return int(float(str(v).strip()))
    except Exception:
        return None


def fnum(v):
    try:
        x = float(str(v).strip())
        return x if math.isfinite(x) else None
    except Exception:
        return None


def guard_method():
    if sha_file(DETECTOR) != EXPECTED_DETECTOR_SHA:
        raise RuntimeError("REFUSING: frozen detector SHA changed")
    if sha_file(METHOD) != EXPECTED_METHOD_SHA:
        raise RuntimeError("REFUSING: frozen method SHA changed")

    cfg = json.loads(METHOD.read_text(encoding="utf-8"))
    valid = {f.name for f in fields(FrozenMethod)}
    if set(cfg) - valid:
        raise RuntimeError(
            f"REFUSING: unknown frozen method keys {sorted(set(cfg)-valid)}"
        )
    method = FrozenMethod(**cfg)

    expected = {
        "background_sigma_px": 8.0,
        "peak_sigma": 4.0,
        "max_window_px": 7,
        "edge_px": 30,
        "diagnostic_match_arcsec": 10.0,
        "strict_registered_match_arcsec": 3.0,
    }
    for key, value in expected.items():
        if getattr(method, key) != value:
            raise RuntimeError(f"REFUSING: frozen method changed at {key}")
    return method


def state_default():
    return {
        "status": "IN_PROGRESS",
        "attempts": {},
        "terminal": {},
        "completed_tiles": 0,
        "total_tiles": EXPECTED_TILES,
        "started_at_utc": datetime.now(timezone.utc).isoformat(),
    }


def meta_paths(tile):
    d = TILE_RESULT / safe_name(tile["endpoint_key"])
    stem = safe_name(tile["tile_id"])
    return d / f"{stem}.json", d / f"{stem}_candidates.csv"


def checkpoint_valid(tile, contract_sha):
    meta, csvp = meta_paths(tile)
    if not meta.is_file() or not csvp.is_file():
        return False
    try:
        m = json.loads(meta.read_text(encoding="utf-8"))
        return (
            m.get("complete") is True
            and m.get("contract_sha256") == contract_sha
            and m.get("detector_sha256") == EXPECTED_DETECTOR_SHA
            and m.get("method_sha256") == EXPECTED_METHOD_SHA
            and m.get("candidate_csv_sha256") == sha_file(csvp)
            and m.get("science_pixel_file_persisted") is False
        )
    except Exception:
        return False


def tile_result_state(tile, contract_sha):
    """Return checkpointed detector result state for a valid tile."""
    if not checkpoint_valid(tile, contract_sha):
        return None
    meta, _ = meta_paths(tile)
    m = json.loads(meta.read_text(encoding="utf-8"))
    return m.get("detector_result_state", "DETECTOR_COMPLETE")


def tile_intersects_bbox(tile, bbox):
    """Conservative core-rectangle overlap with a pair's endpoint bbox."""
    tx0 = int(tile["core_x0"])
    tx1 = int(tile["core_x1"])
    ty0 = int(tile["core_y0"])
    ty1 = int(tile["core_y1"])
    bx0, bx1, by0, by1 = map(int, bbox)
    return tx0 < bx1 and tx1 > bx0 and ty0 < by1 and ty1 > by0


def parse_header_text(text):
    text = str(text)
    if "\\n" in text and "\n" not in text:
        text = text.replace("\\n", "\n")
    for sep in ("\n", ""):
        try:
            h = fits.Header.fromstring(text, sep=sep)
            if len(h):
                return h
        except Exception:
            pass
    raise RuntimeError("Could not parse APPLAUSE header_wcs")


def applause_solution_rows():
    obj = json.loads(APPLAUSE_WCS_CACHE.read_text(encoding="utf-8"))
    rows = obj.get("rows", [])
    out = {}
    for row in rows:
        sid = inum(row.get("solution_id"))
        if sid is not None:
            out[sid] = row
    return out


def applause_wcs(endpoint, rows):
    sid = int(endpoint["solution_id"])
    row = rows.get(sid)
    if row is None:
        raise RuntimeError(f"APPLAUSE solution_id {sid} missing from v054 cache")
    h = parse_header_text(row.get("header_wcs", ""))
    keyname = str(endpoint.get("wcs_key") or "PRIMARY")
    key = " " if keyname == "PRIMARY" else keyname
    return WCS(h, key=key).celestial


def dasch_package(plate):
    path = DASCH_CACHE / f"{plate}.json"
    if not path.is_file():
        raise RuntimeError(f"Missing DASCH package cache {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def dasch_wcs(endpoint, pkg):
    astrom = pkg["metadata"]["astrometry"]
    h = fits.Header.fromstring(
        gzip.decompress(base64.b64decode(astrom["b01HeaderGz"])),
        sep="\n",
    )
    keyname = str(endpoint.get("wcs_key") or "PRIMARY")
    key = " " if keyname == "PRIMARY" else keyname
    return WCS(h, key=key).celestial


def rotation_k(pkg):
    rd = pkg["metadata"]["astrometry"].get("rotationDelta")
    rk = {
        90: -1,
        180: 2,
        -180: 2,
        -90: 1,
        0: 0,
        None: 0,
    }.get(rd, "BAD")
    if rk == "BAD":
        raise RuntimeError(f"Unsupported DASCH rotationDelta {rd}")
    return rk


def output_rect_to_base(k, H, W, ox0, ox1, oy0, oy1):
    if k == 0:
        return oy0, oy1, ox0, ox1
    if k == -1:
        return H-ox1, H-ox0, oy0, oy1
    if k == 1:
        return ox0, ox1, W-oy1, W-oy0
    if k == 2:
        return H-oy1, H-oy0, W-ox1, W-ox0
    raise RuntimeError(k)


def image_hdu_for_shape(hdul, shape):
    hits = [
        (i, hdu)
        for i, hdu in enumerate(hdul)
        if getattr(hdu, "shape", None)
        and tuple(map(int, hdu.shape)) == tuple(map(int, shape))
    ]
    if len(hits) != 1:
        raise RuntimeError(
            f"Expected exactly one image HDU of shape {shape}; found {len(hits)}"
        )
    return hits[0]


def validate_integer_pixels(arr, label):
    if np.issubdtype(arr.dtype, np.integer):
        return
    finite = arr[np.isfinite(arr)]
    if finite.size and np.any(np.abs(finite - np.rint(finite)) > 1e-12):
        raise RuntimeError(f"REFUSING: non-integer native pixels for {label}")


def open_endpoint(endpoint):
    kind = endpoint["kind"]
    if kind == "APPLAUSE":
        hdul = fits.open(
            endpoint["fits_url"],
            use_fsspec=True,
            lazy_load_hdus=True,
            fsspec_kwargs={
                "block_size": 4 * 1024 * 1024,
                "cache_type": "readahead",
            },
        )
        hi, hdu = image_hdu_for_shape(
            hdul,
            (int(endpoint["naxis2"]), int(endpoint["naxis1"])),
        )
        return {
            "kind": kind,
            "hdul": hdul,
            "hdu": hdu,
            "hdu_index": hi,
            "wcs": endpoint["_wcs"],
            "rotation_k": 0,
            "base_shape": (
                int(endpoint["naxis2"]),
                int(endpoint["naxis1"]),
            ),
        }

    if kind == "DASCH":
        pkg = endpoint["_pkg"]
        url = endpoint["fits_url"]
        hdul = fits.open(
            url,
            use_fsspec=True,
            lazy_load_hdus=True,
            fsspec_kwargs={
                "block_size": 4 * 1024 * 1024,
                "cache_type": "readahead",
            },
        )
        # b01Height/b01Width are the unrotated base mosaic dimensions.
        m = pkg["metadata"]["mosaic"]
        base_shape = (int(m["b01Height"]), int(m["b01Width"]))
        hi, hdu = image_hdu_for_shape(hdul, base_shape)
        return {
            "kind": kind,
            "hdul": hdul,
            "hdu": hdu,
            "hdu_index": hi,
            "wcs": endpoint["_wcs"],
            "rotation_k": rotation_k(pkg),
            "base_shape": base_shape,
        }

    raise RuntimeError(f"Unsupported endpoint kind {kind}")


def read_tile_pixels(handle, tile):
    x0, x1 = int(tile["ext_x0"]), int(tile["ext_x1"])
    y0, y1 = int(tile["ext_y0"]), int(tile["ext_y1"])

    if handle["kind"] == "APPLAUSE":
        arr = np.asarray(handle["hdu"].section[y0:y1, x0:x1])
    else:
        H, W = handle["base_shape"]
        k = handle["rotation_k"]
        by0, by1, bx0, bx1 = output_rect_to_base(
            k, H, W, x0, x1, y0, y1
        )
        base = np.asarray(handle["hdu"].section[by0:by1, bx0:bx1])
        arr = np.rot90(base, k=k)

    expected = (y1-y0, x1-x0)
    if tuple(arr.shape) != expected:
        raise RuntimeError(
            f"Native section shape {arr.shape} != expected {expected}"
        )
    validate_integer_pixels(arr, tile["endpoint_key"])
    return arr


def run_one_tile(tile, endpoint, handle, method, contract_sha):
    meta_path, csv_path = meta_paths(tile)
    if checkpoint_valid(tile, contract_sha):
        return "cached"

    arr = read_tile_pixels(handle, tile)
    content_sha = sha_array(arr)
    finite = arr[np.isfinite(arr)]

    detector_result_state = "DETECTOR_COMPLETE"
    detector_exception = None

    try:
        det = detect_array(arr, method)
    except RuntimeError as exc:
        # A robust residual sigma of exactly zero is deterministic for the
        # same native pixels and means the frozen detector has no defined
        # significance scale on this tile. It is NOT a non-detection and must
        # not consume network/process retry budget.
        msg = str(exc).strip()
        m = re.fullmatch(
            r"invalid robust sigma\s+([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)",
            msg,
        )
        sigma_value = float(m.group(1)) if m else None
        if m is None or sigma_value != 0.0:
            raise

        detector_result_state = "UNINFORMATIVE_ZERO_ROBUST_SIGMA"
        detector_exception = msg
        det = None

    if detector_result_state == "DETECTOR_COMPLETE":
        x = np.asarray(det["x"], dtype=int)
        y = np.asarray(det["y"], dtype=int)
    else:
        x = np.array([], dtype=int)
        y = np.array([], dtype=int)

    ex0, ey0 = int(tile["ext_x0"]), int(tile["ext_y0"])
    gx, gy = ex0 + x, ey0 + y

    cx0 = int(tile["core_x0"])
    cx1 = int(tile["core_x1"])
    cy0 = int(tile["core_y0"])
    cy1 = int(tile["core_y1"])

    ii = np.flatnonzero(
        (gx >= cx0) & (gx < cx1) &
        (gy >= cy0) & (gy < cy1)
    )

    if len(ii):
        sky = handle["wcs"].pixel_to_world(
            gx[ii].astype(float),
            gy[ii].astype(float),
        )
        ra = np.asarray(sky.ra.deg, dtype=float)
        dec = np.asarray(sky.dec.deg, dtype=float)
    else:
        ra = np.array([], dtype=float)
        dec = np.array([], dtype=float)

    rows = []
    for oi, j in enumerate(ii):
        rows.append({
            "endpoint_key": tile["endpoint_key"],
            "kind": endpoint["kind"],
            "exposure": endpoint["exposure"],
            "tile_id": tile["tile_id"],
            "candidate_index": oi,
            "local_x": int(x[j]),
            "local_y": int(y[j]),
            "global_x": int(gx[j]),
            "global_y": int(gy[j]),
            "ra_deg": float(ra[oi]),
            "dec_deg": float(dec[oi]),
            "snr": float(det["snr"][j]),
            "signal": float(det["signal"][j]),
            "polarity": int(det["polarity"][j]),
            "sigma": float(det["sigma"]),
        })

    write_csv(csv_path, rows, CAND_FIELDS)

    meta = {
        "complete": True,
        "analysis_kind": "wide_census_native_tile_detector_v056",
        "endpoint_key": tile["endpoint_key"],
        "kind": endpoint["kind"],
        "exposure": endpoint["exposure"],
        "tile_id": tile["tile_id"],
        "source_url": endpoint["fits_url"],
        "wcs_key": endpoint.get("wcs_key"),
        "hdu_index": int(handle["hdu_index"]),
        "core": [cx0, cx1, cy0, cy1],
        "extended": [
            int(tile["ext_x0"]), int(tile["ext_x1"]),
            int(tile["ext_y0"]), int(tile["ext_y1"]),
        ],
        "shape": list(map(int, arr.shape)),
        "dtype": str(arr.dtype),
        "native_pixel_content_sha256": content_sha,
        "finite_pixels": int(finite.size),
        "minimum": float(np.min(finite)) if finite.size else None,
        "maximum": float(np.max(finite)) if finite.size else None,
        "detector_result_state": detector_result_state,
        "detector_exception": detector_exception,
        "all_detector_peaks": int(len(x)),
        "accepted_core_peaks": int(len(rows)),
        "robust_sigma": (
            float(det["sigma"])
            if detector_result_state == "DETECTOR_COMPLETE"
            else 0.0
        ),
        "median_residual": (
            float(det["median_residual"])
            if detector_result_state == "DETECTOR_COMPLETE"
            else None
        ),
        "raw_pixel_range": (
            float(np.max(finite) - np.min(finite))
            if finite.size else None
        ),
        "coverage_interpretation": (
            "DETECTOR_VALID"
            if detector_result_state == "DETECTOR_COMPLETE"
            else (
                "UNINFORMATIVE: frozen detector significance scale is undefined "
                "because robust residual sigma is exactly zero; absence of "
                "candidates from this tile is not a scientific negative."
            )
        ),
        "candidate_csv": str(csv_path.relative_to(ROOT)).replace("\\", "/"),
        "candidate_csv_sha256": sha_file(csv_path),
        "science_pixel_file_persisted": False,
        "contract_sha256": contract_sha,
        "detector_sha256": EXPECTED_DETECTOR_SHA,
        "method_sha256": EXPECTED_METHOD_SHA,
        "native_policy_sha256": sha_file(NATIVE_POLICY),
        "completed_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    write_json(meta_path, meta)
    return "done"


def polygon_center(poly):
    vec = []
    for ra, dec in poly:
        r = math.radians(float(ra))
        d = math.radians(float(dec))
        vec.append([
            math.cos(d)*math.cos(r),
            math.cos(d)*math.sin(r),
            math.sin(d),
        ])
    v = np.sum(np.asarray(vec, float), axis=0)
    v /= np.linalg.norm(v)
    ra = math.degrees(math.atan2(v[1], v[0])) % 360.0
    dec = math.degrees(math.asin(float(v[2])))
    return ra, dec


def project_points(ra, dec, cra, cdec):
    r = np.radians(np.asarray(ra, float))
    d = np.radians(np.asarray(dec, float))
    r0, d0 = math.radians(cra), math.radians(cdec)
    cosc = (
        math.sin(d0)*np.sin(d)
        + math.cos(d0)*np.cos(d)*np.cos(r-r0)
    )
    x = np.cos(d)*np.sin(r-r0) / cosc
    y = (
        math.cos(d0)*np.sin(d)
        - math.sin(d0)*np.cos(d)*np.cos(r-r0)
    ) / cosc
    return x, y


def points_in_polygon(rows, poly):
    if not rows:
        return []
    cra, cdec = polygon_center(poly)
    pra = [p[0] for p in poly]
    pdec = [p[1] for p in poly]
    px, py = project_points(pra, pdec, cra, cdec)
    x, y = project_points(
        [r["ra_deg"] for r in rows],
        [r["dec_deg"] for r in rows],
        cra, cdec,
    )

    out = []
    n = len(poly)
    for row, xx, yy in zip(rows, x, y):
        inside = False
        j = n - 1
        for i in range(n):
            xi, yi = px[i], py[i]
            xj, yj = px[j], py[j]
            crosses = ((yi > yy) != (yj > yy))
            if crosses:
                xint = (xj-xi)*(yy-yi)/(yj-yi) + xi
                if xx < xint:
                    inside = not inside
            j = i
        if inside:
            out.append(row)
    return out


def load_endpoint_candidates(endpoint_key, tile_rows, contract_sha):
    out = []
    for tile in tile_rows:
        if tile["endpoint_key"] != endpoint_key:
            continue
        if not checkpoint_valid(tile, contract_sha):
            raise RuntimeError(
                f"REFUSING: aggregate requested before valid tile {tile['tile_id']}"
            )
        _, csvp = meta_paths(tile)
        with csvp.open(newline="", encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                out.append({
                    "endpoint_key": r["endpoint_key"],
                    "kind": r["kind"],
                    "exposure": r["exposure"],
                    "tile_id": r["tile_id"],
                    "candidate_index": int(r["candidate_index"]),
                    "local_x": int(r["local_x"]),
                    "local_y": int(r["local_y"]),
                    "global_x": int(r["global_x"]),
                    "global_y": int(r["global_y"]),
                    "ra_deg": float(r["ra_deg"]),
                    "dec_deg": float(r["dec_deg"]),
                    "snr": float(r["snr"]),
                    "signal": float(r["signal"]),
                    "polarity": int(r["polarity"]),
                    "sigma": float(r["sigma"]),
                })
    return out


def pair_crossmatch(a, b, method):
    if not a or not b:
        return []
    ac = SkyCoord(
        [r["ra_deg"] for r in a] * u.deg,
        [r["dec_deg"] for r in a] * u.deg,
    )
    bc = SkyCoord(
        [r["ra_deg"] for r in b] * u.deg,
        [r["dec_deg"] for r in b] * u.deg,
    )
    ia, ib, sep, _ = search_around_sky(
        ac, bc, method.diagnostic_match_arcsec * u.arcsec
    )
    out = []
    for z in np.argsort(sep.arcsec):
        aa = a[int(ia[z])]
        bb = b[int(ib[z])]
        s = float(sep.arcsec[z])
        out.append((aa, bb, s))
    return out


def finalize(endpoints, tiles, pairs, method, contract_sha):
    by_endpoint = {}
    all_rows = []

    for key in endpoints:
        rows = load_endpoint_candidates(key, tiles, contract_sha)
        by_endpoint[key] = rows
        all_rows.extend(rows)

    write_csv(ALL_CAND, all_rows, CAND_FIELDS)

    match_fields = [
        "pair_index", "canonical_pair", "time_gate", "physical_overlap_s",
        "endpoint_a", "endpoint_b", "separation_arcsec", "raw_le_3arcsec",
        "a_tile_id", "a_candidate_index", "a_ra_deg", "a_dec_deg",
        "a_snr", "a_polarity",
        "b_tile_id", "b_candidate_index", "b_ra_deg", "b_dec_deg",
        "b_snr", "b_polarity",
    ]
    summary_fields = [
        "pair_index", "canonical_pair", "time_gate", "physical_overlap_s",
        "endpoint_a", "endpoint_b",
        "endpoint_a_candidates_total", "endpoint_b_candidates_total",
        "endpoint_a_candidates_in_common_polygon",
        "endpoint_b_candidates_in_common_polygon",
        "endpoint_a_uninformative_tiles_in_pair_bbox",
        "endpoint_b_uninformative_tiles_in_pair_bbox",
        "detector_coverage_state",
        "raw_le_10arcsec_matches", "raw_le_3arcsec_matches",
        "candidate_science_state",
    ]

    uninformative_by_endpoint = {}
    for tile in tiles:
        if tile_result_state(tile, contract_sha) == "UNINFORMATIVE_ZERO_ROBUST_SIGMA":
            uninformative_by_endpoint.setdefault(tile["endpoint_key"], []).append(tile)

    all_matches = []
    summaries = []

    for i, pair in enumerate(pairs, 1):
        ea = pair["endpoint_a"]
        eb = pair["endpoint_b"]
        poly = pair["common_polygon_icrs_deg"]

        aa_all = by_endpoint[ea]
        bb_all = by_endpoint[eb]
        aa = points_in_polygon(aa_all, poly)
        bb = points_in_polygon(bb_all, poly)
        matches = pair_crossmatch(aa, bb, method)

        n3 = sum(s <= method.strict_registered_match_arcsec for _, _, s in matches)

        ua = [
            t for t in uninformative_by_endpoint.get(ea, [])
            if tile_intersects_bbox(t, pair["endpoint_a_bbox"])
        ]
        ub = [
            t for t in uninformative_by_endpoint.get(eb, [])
            if tile_intersects_bbox(t, pair["endpoint_b_bbox"])
        ]
        detector_coverage_state = (
            "INCOMPLETE_UNINFORMATIVE_TILE_HOLD"
            if ua or ub
            else "COMPLETE_VALID_DETECTOR_COVERAGE"
        )
        science_state = (
            "RAW_COINCIDENCE_INVENTORY_WITH_UNINFORMATIVE_COVERAGE_HOLD"
            if ua or ub
            else "RAW_COINCIDENCE_INVENTORY_ONLY"
        )

        summaries.append({
            "pair_index": i,
            "canonical_pair": pair["canonical_pair"],
            "time_gate": pair["time_gate"],
            "physical_overlap_s": pair["physical_overlap_s"],
            "endpoint_a": ea,
            "endpoint_b": eb,
            "endpoint_a_candidates_total": len(aa_all),
            "endpoint_b_candidates_total": len(bb_all),
            "endpoint_a_candidates_in_common_polygon": len(aa),
            "endpoint_b_candidates_in_common_polygon": len(bb),
            "endpoint_a_uninformative_tiles_in_pair_bbox": len(ua),
            "endpoint_b_uninformative_tiles_in_pair_bbox": len(ub),
            "detector_coverage_state": detector_coverage_state,
            "raw_le_10arcsec_matches": len(matches),
            "raw_le_3arcsec_matches": n3,
            "candidate_science_state": science_state,
        })

        for arow, brow, sep in matches:
            all_matches.append({
                "pair_index": i,
                "canonical_pair": pair["canonical_pair"],
                "time_gate": pair["time_gate"],
                "physical_overlap_s": pair["physical_overlap_s"],
                "endpoint_a": ea,
                "endpoint_b": eb,
                "separation_arcsec": sep,
                "raw_le_3arcsec": sep <= method.strict_registered_match_arcsec,
                "a_tile_id": arow["tile_id"],
                "a_candidate_index": arow["candidate_index"],
                "a_ra_deg": arow["ra_deg"],
                "a_dec_deg": arow["dec_deg"],
                "a_snr": arow["snr"],
                "a_polarity": arow["polarity"],
                "b_tile_id": brow["tile_id"],
                "b_candidate_index": brow["candidate_index"],
                "b_ra_deg": brow["ra_deg"],
                "b_dec_deg": brow["dec_deg"],
                "b_snr": brow["snr"],
                "b_polarity": brow["polarity"],
            })

    write_csv(PAIR_SUMMARY, summaries, summary_fields)
    write_csv(RAW_MATCHES, all_matches, match_fields)

    raw10 = len(all_matches)
    raw3 = sum(bool(x["raw_le_3arcsec"]) for x in all_matches)
    pairs10 = sum(int(x["raw_le_10arcsec_matches"]) > 0 for x in summaries)
    pairs3 = sum(int(x["raw_le_3arcsec_matches"]) > 0 for x in summaries)
    uninformative_tiles = sum(
        len(v) for v in uninformative_by_endpoint.values()
    )
    pairs_with_uninformative_coverage = sum(
        x["detector_coverage_state"] == "INCOMPLETE_UNINFORMATIVE_TILE_HOLD"
        for x in summaries
    )

    report = {
        "status": "COMPLETE",
        "analysis_kind": "wide_census_disk_bounded_frozen_detector_v056",
        "guards": {
            "network_access": True,
            "science_pixels_read": True,
            "non_science_pixels_read": False,
            "transient_detector_rerun": True,
            "candidate_state_mutation": False,
        },
        "contract_sha256": contract_sha,
        "detector_sha256": EXPECTED_DETECTOR_SHA,
        "method_sha256": EXPECTED_METHOD_SHA,
        "native_policy_sha256": sha_file(NATIVE_POLICY),
        "tile_count": len(tiles),
        "endpoint_count": len(endpoints),
        "opportunity_count": len(pairs),
        "accepted_native_detector_candidates_total": len(all_rows),
        "raw_le_10arcsec_match_count": raw10,
        "raw_le_3arcsec_match_count": raw3,
        "pairs_with_raw_le_10arcsec_match": pairs10,
        "pairs_with_raw_le_3arcsec_match": pairs3,
        "uninformative_zero_robust_sigma_tile_count": uninformative_tiles,
        "pairs_with_uninformative_detector_coverage": pairs_with_uninformative_coverage,
        "detector_coverage_status": (
            "COMPLETE_WITH_UNINFORMATIVE_TILE_HOLDS"
            if uninformative_tiles
            else "COMPLETE_VALID_DETECTOR_COVERAGE"
        ),
        "science_positive_count": 0,
        "persistent_science_pixel_tile_files": False,
        "outputs": {
            "all_candidates_csv": str(ALL_CAND.relative_to(ROOT)).replace("\\", "/"),
            "pair_summary_csv": str(PAIR_SUMMARY.relative_to(ROOT)).replace("\\", "/"),
            "raw_matches_csv": str(RAW_MATCHES.relative_to(ROOT)).replace("\\", "/"),
            "tile_result_dir": str(TILE_RESULT.relative_to(ROOT)).replace("\\", "/"),
        },
        "interpretation": (
            "Complete frozen-detector execution on the robust v053 observing-opportunity "
            "subset. Raw <=10 and <=3 arcsec coincidences are not transient classifications. "
            "A zero-robust-sigma tile is retained as an explicit uninformative coverage hold "
            "and is never treated as a non-detection; affected pairs therefore cannot support "
            "a complete negative result until the coverage limitation is resolved or otherwise "
            "sensitivity-qualified. Raw coincidences still require the frozen generic v002 "
            "astrometric/static-source/morphology/population/sensitivity adjudication. The "
            "41 v052 geometry holds remain outside this execution denominator and are still "
            "unresolved, not negative."
        ),
        "next_stage": (
            "Run generic automated v002 adjudication over all raw coincidence-bearing pairs; "
            "manual review only after automated mechanical explanations."
        ),
    }
    write_json(OUT_JSON, report)
    return report


def main():
    print("=" * 132)
    print("WIDE CENSUS — DISK-BOUNDED RESUMABLE FROZEN DETECTOR EXECUTION v056 (ZERO-SIGMA HOLD FIX 1)")
    print("=" * 132)
    print("SCIENCE PIXELS: YES. NETWORK: YES. FROZEN DETECTOR: YES.")
    print("NO RESAMPLING. NO THRESHOLD RETUNING. NO CANDIDATE STATE MUTATION.")
    print(
        f"Checkpoint batch: <= {MAX_TILES_PER_CYCLE} native tiles per runner cycle; "
        "successful tiles are skipped on resume.\n"
    )

    for p in (
        CONTRACT, PREFLIGHT, ENDPOINTS, PAIRS, TILES,
        APPLAUSE_WCS_CACHE, DETECTOR, METHOD, NATIVE_POLICY,
    ):
        if not p.is_file():
            raise RuntimeError(f"REFUSING: missing input {p}")

    method = guard_method()
    contract_sha = sha_file(CONTRACT)
    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))

    if contract.get("status") != "COMPLETE":
        raise RuntimeError("REFUSING: v055 contract incomplete")
    if not contract.get("disk_bounded_capacity_pass"):
        raise RuntimeError("REFUSING: v055 disk-bounded capacity did not pass")

    endpoints_rows = read_csv(ENDPOINTS)
    tile_rows = read_csv(TILES)
    pairs = json.loads(PAIRS.read_text(encoding="utf-8")).get("pairs", [])

    if len(endpoints_rows) != EXPECTED_ENDPOINTS:
        raise RuntimeError("REFUSING: endpoint count changed")
    if len(tile_rows) != EXPECTED_TILES:
        raise RuntimeError("REFUSING: tile count changed")
    if len(pairs) != EXPECTED_OPPS:
        raise RuntimeError("REFUSING: opportunity count changed")

    RESULT.mkdir(parents=True, exist_ok=True)
    TILE_RESULT.mkdir(parents=True, exist_ok=True)

    ap_rows = applause_solution_rows()
    endpoints = {}

    for row in endpoints_rows:
        ep = dict(row)
        key = ep["endpoint_key"]
        if ep["kind"] == "APPLAUSE":
            ep["_wcs"] = applause_wcs(ep, ap_rows)
        elif ep["kind"] == "DASCH":
            plate = str(ep["plate_id"]).strip().lower()
            pkg = dasch_package(plate)
            ep["_pkg"] = pkg
            ep["_wcs"] = dasch_wcs(ep, pkg)
        else:
            raise RuntimeError(f"Unsupported endpoint kind {ep['kind']}")
        endpoints[key] = ep

    state = (
        json.loads(STATE.read_text(encoding="utf-8"))
        if STATE.is_file()
        else state_default()
    )

    completed = sum(
        checkpoint_valid(tile, contract_sha)
        for tile in tile_rows
    )
    pending = [
        tile for tile in tile_rows
        if not checkpoint_valid(tile, contract_sha)
    ]

    if not pending:
        report = finalize(endpoints, tile_rows, pairs, method, contract_sha)
        state.update({
            "status": "COMPLETE",
            "completed_tiles": EXPECTED_TILES,
            "finished_at_utc": datetime.now(timezone.utc).isoformat(),
        })
        write_json(STATE, state)

        print("\n" + "=" * 132)
        print("HEAVY FROZEN-DETECTOR RUN COMPLETE")
        print("=" * 132)
        print(f"Tiles complete: {EXPECTED_TILES}/{EXPECTED_TILES}")
        print(
            "Accepted native detector candidates: "
            f"{report['accepted_native_detector_candidates_total']}"
        )
        print(f"Raw <=10\" coincidences: {report['raw_le_10arcsec_match_count']}")
        print(f"Raw <=3\" coincidences: {report['raw_le_3arcsec_match_count']}")
        print(
            "Pairs with raw <=10\" coincidence: "
            f"{report['pairs_with_raw_le_10arcsec_match']}/{EXPECTED_OPPS}"
        )
        print(
            "Pairs with raw <=3\" coincidence: "
            f"{report['pairs_with_raw_le_3arcsec_match']}/{EXPECTED_OPPS}"
        )
        print(
            "Uninformative zero-sigma tiles: "
            f"{report['uninformative_zero_robust_sigma_tile_count']}"
        )
        print(
            "Pairs with uninformative detector coverage: "
            f"{report['pairs_with_uninformative_detector_coverage']}/{EXPECTED_OPPS}"
        )
        print("SCIENCE POSITIVES: 0 (raw matches are not classifications)")
        print(f"Report: {OUT_JSON}")
        print("\nSTAGE STATUS: PASS")
        return 0

    disk = shutil.disk_usage(ROOT)
    if disk.free < DISK_ABORT_FLOOR:
        raise RuntimeError(
            f"REFUSING: free disk {disk.free/1024**3:.2f} GiB below "
            f"{DISK_ABORT_FLOOR/1024**3:.2f} GiB abort floor"
        )

    batch = pending[:MAX_TILES_PER_CYCLE]

    # Keep remote FITS handles open while processing consecutive tiles from
    # the same endpoint, substantially reducing HTTP/header overhead.
    groups = {}
    order = []
    for tile in batch:
        key = tile["endpoint_key"]
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(tile)

    done_this_cycle = 0
    failures_this_cycle = []

    for endpoint_key in order:
        ep = endpoints.get(endpoint_key)
        if ep is None:
            raise RuntimeError(f"Tile references unknown endpoint {endpoint_key}")

        handle = None
        try:
            handle = open_endpoint(ep)
            for tile in groups[endpoint_key]:
                tkey = f"{endpoint_key}|{tile['tile_id']}"
                if checkpoint_valid(tile, contract_sha):
                    continue
                try:
                    status = run_one_tile(
                        tile, ep, handle, method, contract_sha
                    )
                    if status == "done":
                        done_this_cycle += 1
                    state["attempts"].pop(tkey, None)
                    print(
                        f"[{completed+done_this_cycle:04d}/{EXPECTED_TILES}] "
                        f"{endpoint_key} {tile['tile_id']} PASS",
                        flush=True,
                    )
                except Exception as exc:
                    n = int(state["attempts"].get(tkey, 0)) + 1
                    state["attempts"][tkey] = n
                    record = {
                        "tile_key": tkey,
                        "endpoint_key": endpoint_key,
                        "tile_id": tile["tile_id"],
                        "attempt": n,
                        "error_type": type(exc).__name__,
                        "error": str(exc),
                        "at_utc": datetime.now(timezone.utc).isoformat(),
                    }
                    failures_this_cycle.append(record)
                    print(
                        f"  {tkey} attempt {n}/{MAX_TILE_ATTEMPTS} FAILED: {exc}",
                        flush=True,
                    )
                    if n >= MAX_TILE_ATTEMPTS:
                        state["terminal"][tkey] = record
        except Exception as exc:
            # Endpoint-open failure counts once for each batch tile that could
            # not be attempted; it remains an operational/network hold.
            for tile in groups[endpoint_key]:
                tkey = f"{endpoint_key}|{tile['tile_id']}"
                if checkpoint_valid(tile, contract_sha):
                    continue
                n = int(state["attempts"].get(tkey, 0)) + 1
                state["attempts"][tkey] = n
                record = {
                    "tile_key": tkey,
                    "endpoint_key": endpoint_key,
                    "tile_id": tile["tile_id"],
                    "attempt": n,
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                    "at_utc": datetime.now(timezone.utc).isoformat(),
                }
                failures_this_cycle.append(record)
                if n >= MAX_TILE_ATTEMPTS:
                    state["terminal"][tkey] = record
            print(
                f"ENDPOINT OPEN FAILED {endpoint_key}: "
                f"{type(exc).__name__}: {exc}",
                flush=True,
            )
        finally:
            if handle is not None:
                try:
                    handle["hdul"].close()
                except Exception:
                    pass

    completed_after = sum(
        checkpoint_valid(tile, contract_sha)
        for tile in tile_rows
    )
    state.update({
        "status": "IN_PROGRESS",
        "completed_tiles": completed_after,
        "total_tiles": EXPECTED_TILES,
        "last_cycle_completed_tiles": done_this_cycle,
        "last_cycle_failures": failures_this_cycle[-20:],
        "last_cycle_at_utc": datetime.now(timezone.utc).isoformat(),
        "free_disk_bytes": shutil.disk_usage(ROOT).free,
    })
    write_json(STATE, state)

    if state["terminal"]:
        write_json(FAILURES, {
            "status": "BLOCKED_TERMINAL_TILE_FAILURES",
            "terminal": state["terminal"],
        })
        print(
            f"\nBLOCKED: {len(state['terminal'])} tile(s) reached "
            f"{MAX_TILE_ATTEMPTS} attempts."
        )
        print(f"Failure report: {FAILURES}")
        return 1

    print(
        f"\nCHECKPOINT: {completed_after}/{EXPECTED_TILES} tiles complete "
        f"({100.0*completed_after/EXPECTED_TILES:.2f}%)"
    )
    print(
        f"This cycle: {done_this_cycle} completed, "
        f"{len(failures_this_cycle)} failed attempts"
    )
    print(
        f"Free disk: {shutil.disk_usage(ROOT).free/1024**3:.2f} GiB"
    )
    print("RETURN 10: checkpointed IN_PROGRESS")
    return 10


if __name__ == "__main__":
    raise SystemExit(main())
