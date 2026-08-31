#!/usr/bin/env python3
"""
ORDER 01 — discovery-pair local astrometric consistency audit v028l

Purpose
-------
Test whether the six frozen Branch-A POSS/DASCH discovery detections are
astrometrically consistent with the local cross-plate registration, WITHOUT
reading science pixels or rerunning the detector.

Three nested diagnostics are performed:

A) SIX-VECTOR COMMON-SHIFT TEST
   Compute the POSS -> DASCH tangent-plane offset vector for each frozen
   candidate.  This determines whether a single global translation can explain
   all six pair offsets.

B) GAIA-TIED LOCAL ANCHORS
   Use the already-frozen, epoch-propagated Gaia source sets around each
   candidate.  Independently match each Gaia source to the nearest native
   POSS and DASCH detector entry of the expected stellar polarity, then use
   the resulting ordinary-star cross-plate vectors as absolute local anchors.

C) DENSE LOCAL MUTUAL-NEAREST CONTROLS
   Within a local sky radius around each survivor, match native POSS and DASCH
   detector entries using mutual-nearest-neighbour geometry.  This is a denser
   empirical local registration control.  An SNR-matched subset is also
   reported when enough rows exist.

Important interpretation boundary
---------------------------------
The dense control tier is NOT an independent astronomical catalogue.  It is
used only to describe the empirical local cross-plate registration field.
The Gaia-tied tier is the stronger absolute astrometric control when enough
anchors are available.

NO:
  * network access
  * FITS/image pixel reads
  * .npy array loads
  * detector rerun
  * candidate promotion/deletion
  * weighted candidate score
"""

from __future__ import annotations

import csv
import json
import math
import statistics
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "results" / "order01_native_full_v028"

OVERLAP = RESULTS / "order01_discovery_exposure_overlap_freeze_v028k.json"
ADJ = RESULTS / "order01_branchA_candidate_adjudication_v028f.json"
TRIAGE = RESULTS / "order01_strict_match_triage_v028.csv"
GAIA = RESULTS / "order01_gaia_source_candidates_v028b.csv"
WHOLE = RESULTS / "order01_whole_pair_report.json"

OUT_JSON = RESULTS / "order01_discovery_local_astrometry_v028l.json"
OUT_CSV = RESULTS / "order01_discovery_local_astrometry_v028l.csv"
OUT_MD = RESULTS / "ORDER01_DISCOVERY_LOCAL_ASTROMETRY_V028L.md"

EXPECTED = [10, 24, 25, 26, 29, 30]

LOCAL_RADIUS_DEG = 0.50
SCIENCE_EXCLUSION_ARCSEC = 15.0

GAIA_MATCH_RADIUS_ARCSEC = 5.0
GAIA_STRONG_MATCH_RADIUS_ARCSEC = 3.0
GAIA_MIN_ANCHORS_FOR_INTERPRETATION = 5

DENSE_MATCH_RADIUS_ARCSEC = 5.0
DENSE_MIN_SNR = 4.0
DENSE_MIN_CONTROLS_FOR_INTERPRETATION = 30
SNR_RATIO_LOW = 0.75
SNR_RATIO_HIGH = 1.25
SNR_MATCHED_MIN_CONTROLS = 20

EXPECTED_POSS_POLARITY = -1
EXPECTED_DASCH_POLARITY = 1

# Candidate catalogue field aliases.
RA_ALIASES = ["ra_deg", "ra", "sky_ra_deg", "world_ra_deg", "candidate_ra_deg"]
DEC_ALIASES = ["dec_deg", "dec", "sky_dec_deg", "world_dec_deg", "candidate_dec_deg"]
SNR_ALIASES = ["snr", "candidate_snr", "detector_snr", "peak_snr"]
POL_ALIASES = ["polarity", "candidate_polarity", "sign"]
IDX_ALIASES = ["candidate_index", "index", "idx", "peak_index"]


def choose_field(fieldnames: list[str], aliases: list[str], required=True) -> str | None:
    lower = {x.lower(): x for x in fieldnames}
    for a in aliases:
        if a.lower() in lower:
            return lower[a.lower()]
    if required:
        raise RuntimeError(
            f"Could not resolve field from aliases {aliases}; fields={fieldnames}"
        )
    return None


def f(x: Any) -> float:
    return float(str(x).strip())


def i(x: Any) -> int:
    return int(float(str(x).strip()))


def tangent_xy_arcsec(
    ra_deg: np.ndarray | float,
    dec_deg: np.ndarray | float,
    ra0_deg: float,
    dec0_deg: float,
) -> tuple[np.ndarray | float, np.ndarray | float]:
    c = math.cos(math.radians(dec0_deg))
    return (
        (np.asarray(ra_deg) - ra0_deg) * 3600.0 * c,
        (np.asarray(dec_deg) - dec0_deg) * 3600.0,
    )


def vector_between(
    ra1: float, dec1: float, ra2: float, dec2: float
) -> tuple[float, float, float, float]:
    dec0 = 0.5 * (dec1 + dec2)
    dx = (ra2 - ra1) * 3600.0 * math.cos(math.radians(dec0))
    dy = (dec2 - dec1) * 3600.0
    sep = math.hypot(dx, dy)
    pa = math.degrees(math.atan2(dx, dy)) % 360.0  # east of north
    return dx, dy, sep, pa


def percentile_le(values: list[float], x: float) -> float | None:
    if not values:
        return None
    return sum(v <= x for v in values) / len(values)


def median_vector(vectors: list[tuple[float, float]]) -> tuple[float, float]:
    return (
        statistics.median(v[0] for v in vectors),
        statistics.median(v[1] for v in vectors),
    )


def residuals_from_center(
    vectors: list[tuple[float, float]], cx: float, cy: float
) -> list[float]:
    return [math.hypot(x - cx, y - cy) for x, y in vectors]


def read_csv_rows(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        rd = csv.DictReader(fh)
        rows = list(rd)
        return list(rd.fieldnames or []), rows


def resolve_candidate_catalogues() -> tuple[Path, Path, dict[str, Any]]:
    """
    Prefer exact paths declared by order01_whole_pair_report.json.
    Fall back to conservative filename discovery.
    """
    provenance: dict[str, Any] = {"whole_pair_report": str(WHOLE)}
    poss = dasch = None

    if WHOLE.exists():
        w = json.loads(WHOLE.read_text(encoding="utf-8"))
        # Search recursively through report values for plausible CSV paths.
        def walk(obj):
            if isinstance(obj, dict):
                for k, v in obj.items():
                    yield k, v
                    yield from walk(v)
            elif isinstance(obj, list):
                for v in obj:
                    yield from walk(v)

        for k, v in walk(w):
            if not isinstance(v, str):
                continue
            lowk = str(k).lower()
            lowv = v.lower().replace("\\", "/")
            p = Path(v)
            if not p.is_absolute():
                p = ROOT / p
            if "poss" in lowk and "candidate" in lowk and lowv.endswith(".csv") and p.exists():
                poss = p
            if "dasch" in lowk and "candidate" in lowk and lowv.endswith(".csv") and p.exists():
                dasch = p

    if poss is None:
        exact = RESULTS / "order01_poss_native_candidates.csv"
        if exact.exists():
            poss = exact
    if dasch is None:
        exact = RESULTS / "order01_dasch_native_candidates.csv"
        if exact.exists():
            dasch = exact

    if poss is None:
        hits = sorted(RESULTS.glob("*poss*candidate*.csv"))
        if hits:
            poss = hits[0]
    if dasch is None:
        hits = sorted(RESULTS.glob("*dasch*candidate*.csv"))
        if hits:
            dasch = hits[0]

    if poss is None or dasch is None:
        raise RuntimeError(
            "Could not resolve both native candidate catalogues. "
            f"POSS={poss}, DASCH={dasch}"
        )

    provenance["poss_candidates_csv"] = str(poss.relative_to(ROOT))
    provenance["dasch_candidates_csv"] = str(dasch.relative_to(ROOT))
    return poss, dasch, provenance


def load_native_catalogue(path: Path, expected_polarity: int) -> dict[str, Any]:
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        rd = csv.DictReader(fh)
        fields = list(rd.fieldnames or [])
        ra_f = choose_field(fields, RA_ALIASES)
        dec_f = choose_field(fields, DEC_ALIASES)
        snr_f = choose_field(fields, SNR_ALIASES)
        pol_f = choose_field(fields, POL_ALIASES)
        idx_f = choose_field(fields, IDX_ALIASES, required=False)

        ras = []
        decs = []
        snrs = []
        pols = []
        idxs = []
        total = 0
        kept = 0

        for rownum, row in enumerate(rd, start=0):
            total += 1
            try:
                pol = i(row[pol_f])
                if pol != expected_polarity:
                    continue
                ra = f(row[ra_f])
                dec = f(row[dec_f])
                snr = f(row[snr_f])
            except Exception:
                continue
            ras.append(ra)
            decs.append(dec)
            snrs.append(snr)
            pols.append(pol)
            if idx_f and str(row.get(idx_f, "")).strip():
                try:
                    idxs.append(i(row[idx_f]))
                except Exception:
                    idxs.append(rownum)
            else:
                idxs.append(rownum)
            kept += 1

    return {
        "path": path,
        "fields": fields,
        "resolved_fields": {
            "ra": ra_f,
            "dec": dec_f,
            "snr": snr_f,
            "polarity": pol_f,
            "index": idx_f,
        },
        "total_rows": total,
        "expected_polarity_rows": kept,
        "ra": np.asarray(ras, dtype=float),
        "dec": np.asarray(decs, dtype=float),
        "snr": np.asarray(snrs, dtype=float),
        "index": np.asarray(idxs),
    }


def local_subset(cat: dict[str, Any], ra0: float, dec0: float, radius_deg: float):
    x, y = tangent_xy_arcsec(cat["ra"], cat["dec"], ra0, dec0)
    r = np.hypot(x, y)
    m = r <= radius_deg * 3600.0
    return {
        "ra": cat["ra"][m],
        "dec": cat["dec"][m],
        "snr": cat["snr"][m],
        "index": cat["index"][m],
        "x": np.asarray(x)[m],
        "y": np.asarray(y)[m],
        "r": r[m],
    }


def nearest_indices(points_a: np.ndarray, points_b: np.ndarray):
    """
    Return nearest B index and distance for each A.
    Prefer scipy cKDTree; bounded numpy fallback for small local sets.
    """
    try:
        from scipy.spatial import cKDTree
        tree = cKDTree(points_b)
        dist, idx = tree.query(points_a, k=1)
        return np.asarray(idx), np.asarray(dist)
    except Exception:
        # Chunked brute force fallback.
        idxs = np.empty(len(points_a), dtype=int)
        dists = np.empty(len(points_a), dtype=float)
        chunk = 500
        for s in range(0, len(points_a), chunk):
            a = points_a[s:s+chunk]
            # shape chunk x B x 2
            dd = a[:, None, :] - points_b[None, :, :]
            d2 = np.sum(dd * dd, axis=2)
            ii = np.argmin(d2, axis=1)
            idxs[s:s+len(a)] = ii
            dists[s:s+len(a)] = np.sqrt(d2[np.arange(len(a)), ii])
        return idxs, dists


def mutual_nearest_controls(
    poss: dict[str, Any],
    dasch: dict[str, Any],
    candidate: dict[str, Any],
) -> list[dict[str, Any]]:
    ra0 = candidate["mid_ra_deg"]
    dec0 = candidate["mid_dec_deg"]

    p = local_subset(poss, ra0, dec0, LOCAL_RADIUS_DEG)
    d = local_subset(dasch, ra0, dec0, LOCAL_RADIUS_DEG)

    pm = (p["snr"] >= DENSE_MIN_SNR) & (p["r"] >= SCIENCE_EXCLUSION_ARCSEC)
    dm = (d["snr"] >= DENSE_MIN_SNR) & (d["r"] >= SCIENCE_EXCLUSION_ARCSEC)
    for key in list(p):
        p[key] = p[key][pm]
    for key in list(d):
        d[key] = d[key][dm]

    if len(p["ra"]) == 0 or len(d["ra"]) == 0:
        return []

    pp = np.column_stack([p["x"], p["y"]])
    dd = np.column_stack([d["x"], d["y"]])

    p_to_d_idx, p_to_d_dist = nearest_indices(pp, dd)
    d_to_p_idx, d_to_p_dist = nearest_indices(dd, pp)

    rows = []
    used_d = set()
    for pi, (di, dist) in enumerate(zip(p_to_d_idx, p_to_d_dist)):
        di = int(di)
        if dist > DENSE_MATCH_RADIUS_ARCSEC:
            continue
        if int(d_to_p_idx[di]) != pi:
            continue
        if di in used_d:
            continue
        used_d.add(di)

        dx, dy, sep, pa = vector_between(
            float(p["ra"][pi]), float(p["dec"][pi]),
            float(d["ra"][di]), float(d["dec"][di])
        )
        rows.append({
            "poss_index": str(p["index"][pi]),
            "dasch_index": str(d["index"][di]),
            "poss_ra_deg": float(p["ra"][pi]),
            "poss_dec_deg": float(p["dec"][pi]),
            "dasch_ra_deg": float(d["ra"][di]),
            "dasch_dec_deg": float(d["dec"][di]),
            "poss_snr": float(p["snr"][pi]),
            "dasch_snr": float(d["snr"][di]),
            "dx_east_arcsec": dx,
            "dy_north_arcsec": dy,
            "separation_arcsec": sep,
            "position_angle_deg_east_of_north": pa,
            "mid_radius_from_candidate_arcsec": 0.5 * (
                float(p["r"][pi]) + float(d["r"][di])
            ),
        })
    return rows


def nearest_native_to_gaia(
    local: dict[str, Any],
    gx: float,
    gy: float,
) -> tuple[int | None, float | None]:
    if len(local["x"]) == 0:
        return None, None
    dist = np.hypot(local["x"] - gx, local["y"] - gy)
    j = int(np.argmin(dist))
    return j, float(dist[j])


def gaia_anchor_controls(
    poss: dict[str, Any],
    dasch: dict[str, Any],
    gaia_rows: list[dict[str, str]],
    candidate: dict[str, Any],
) -> list[dict[str, Any]]:
    ra0 = candidate["mid_ra_deg"]
    dec0 = candidate["mid_dec_deg"]
    p = local_subset(poss, ra0, dec0, max(LOCAL_RADIUS_DEG, 0.05))
    d = local_subset(dasch, ra0, dec0, max(LOCAL_RADIUS_DEG, 0.05))

    rows = []
    used_p = set()
    used_d = set()

    for g in gaia_rows:
        try:
            gra = f(g["ra_target_deg"])
            gdec = f(g["dec_target_deg"])
            sid = str(g["source_id"])
        except Exception:
            continue

        gx, gy = tangent_xy_arcsec(gra, gdec, ra0, dec0)
        gr = math.hypot(float(gx), float(gy))
        if gr < SCIENCE_EXCLUSION_ARCSEC:
            continue

        pi, pdist = nearest_native_to_gaia(p, float(gx), float(gy))
        di, ddist = nearest_native_to_gaia(d, float(gx), float(gy))
        if pi is None or di is None:
            continue
        if pdist > GAIA_MATCH_RADIUS_ARCSEC or ddist > GAIA_MATCH_RADIUS_ARCSEC:
            continue

        pkey = str(p["index"][pi])
        dkey = str(d["index"][di])
        if pkey in used_p or dkey in used_d:
            continue
        used_p.add(pkey)
        used_d.add(dkey)

        dx, dy, sep, pa = vector_between(
            float(p["ra"][pi]), float(p["dec"][pi]),
            float(d["ra"][di]), float(d["dec"][di])
        )
        rows.append({
            "gaia_source_id": sid,
            "gaia_ra_target_deg": gra,
            "gaia_dec_target_deg": gdec,
            "gaia_g_mag": (
                f(g["g_mag"]) if str(g.get("g_mag", "")).strip() else None
            ),
            "gaia_propagated": str(g.get("propagated", "")),
            "gaia_pm_sigma_arcsec": (
                f(g["approx_pm_propagation_sigma_arcsec"])
                if str(g.get("approx_pm_propagation_sigma_arcsec", "")).strip()
                else None
            ),
            "poss_index": pkey,
            "dasch_index": dkey,
            "poss_to_gaia_arcsec": pdist,
            "dasch_to_gaia_arcsec": ddist,
            "strong_both_within_3arcsec": (
                pdist <= GAIA_STRONG_MATCH_RADIUS_ARCSEC
                and ddist <= GAIA_STRONG_MATCH_RADIUS_ARCSEC
            ),
            "poss_snr": float(p["snr"][pi]),
            "dasch_snr": float(d["snr"][di]),
            "dx_east_arcsec": dx,
            "dy_north_arcsec": dy,
            "separation_arcsec": sep,
            "position_angle_deg_east_of_north": pa,
        })
    return rows


def summarise_vector_controls(
    controls: list[dict[str, Any]],
    cdx: float,
    cdy: float,
) -> dict[str, Any]:
    if not controls:
        return {
            "count": 0,
            "median_dx_east_arcsec": None,
            "median_dy_north_arcsec": None,
            "median_separation_arcsec": None,
            "candidate_residual_from_local_median_arcsec": None,
            "candidate_residual_empirical_percentile": None,
            "candidate_raw_separation_empirical_percentile": None,
        }

    vectors = [
        (float(x["dx_east_arcsec"]), float(x["dy_north_arcsec"]))
        for x in controls
    ]
    cx, cy = median_vector(vectors)
    residuals = residuals_from_center(vectors, cx, cy)
    candidate_resid = math.hypot(cdx - cx, cdy - cy)
    seps = [float(x["separation_arcsec"]) for x in controls]
    csep = math.hypot(cdx, cdy)

    return {
        "count": len(controls),
        "median_dx_east_arcsec": cx,
        "median_dy_north_arcsec": cy,
        "median_vector_magnitude_arcsec": math.hypot(cx, cy),
        "median_separation_arcsec": statistics.median(seps),
        "p90_separation_arcsec": float(np.quantile(seps, 0.90)),
        "p95_separation_arcsec": float(np.quantile(seps, 0.95)),
        "median_residual_from_local_median_arcsec":
            statistics.median(residuals),
        "p90_residual_from_local_median_arcsec":
            float(np.quantile(residuals, 0.90)),
        "p95_residual_from_local_median_arcsec":
            float(np.quantile(residuals, 0.95)),
        "candidate_residual_from_local_median_arcsec": candidate_resid,
        "candidate_residual_empirical_percentile":
            percentile_le(residuals, candidate_resid),
        "candidate_raw_separation_empirical_percentile":
            percentile_le(seps, csep),
    }


def interpretation(
    gaia_summary: dict[str, Any],
    dense_summary: dict[str, Any],
    snr_summary: dict[str, Any],
) -> str:
    if gaia_summary["count"] >= GAIA_MIN_ANCHORS_FOR_INTERPRETATION:
        pct = gaia_summary["candidate_residual_empirical_percentile"]
        if pct is not None and pct <= 0.95:
            return "CONSISTENT_WITH_LOCAL_GAIA_TIED_ASTROMETRIC_SCATTER"
        return "OUTSIDE_95PCT_LOCAL_GAIA_TIED_ASTROMETRIC_SCATTER"

    if snr_summary["count"] >= SNR_MATCHED_MIN_CONTROLS:
        pct = snr_summary["candidate_residual_empirical_percentile"]
        if pct is not None and pct <= 0.95:
            return "GAIA_SPARSE_BUT_CONSISTENT_WITH_SNR_MATCHED_LOCAL_REGISTRATION"
        return "GAIA_SPARSE_AND_OUTSIDE_95PCT_SNR_MATCHED_LOCAL_REGISTRATION"

    if dense_summary["count"] >= DENSE_MIN_CONTROLS_FOR_INTERPRETATION:
        pct = dense_summary["candidate_residual_empirical_percentile"]
        if pct is not None and pct <= 0.95:
            return "GAIA_SPARSE_BUT_CONSISTENT_WITH_DENSE_LOCAL_REGISTRATION"
        return "GAIA_SPARSE_AND_OUTSIDE_95PCT_DENSE_LOCAL_REGISTRATION"

    return "INSUFFICIENT_LOCAL_ASTROMETRIC_CONTROLS"


def main() -> int:
    print("=" * 122)
    print("ORDER 01 — DISCOVERY-PAIR LOCAL ASTROMETRIC CONSISTENCY AUDIT v028l")
    print("=" * 122)

    for p in (OVERLAP, ADJ, TRIAGE, GAIA):
        if not p.exists():
            print(f"FAIL: missing required input: {p}")
            return 2

    ov = json.loads(OVERLAP.read_text(encoding="utf-8"))
    adj = json.loads(ADJ.read_text(encoding="utf-8"))

    if ov.get("frozen_active_ranks") != EXPECTED:
        print("FAIL: v028k frozen rank mismatch.")
        return 3
    if (
        ov.get("actual_exposure_overlap", {}).get("status")
        != "RESOLVED_AND_CROSSCHECKED"
    ):
        print("FAIL: v028k overlap is not resolved/crosschecked.")
        return 3
    if adj.get("frozen_active_ranks") != EXPECTED:
        print("FAIL: v028f frozen rank mismatch.")
        return 3

    tri_fields, tri_rows = read_csv_rows(TRIAGE)
    tri_by_rank = {}
    for row in tri_rows:
        try:
            rank = i(row["strict_rank"])
        except Exception:
            continue
        if rank not in EXPECTED:
            continue
        tri_by_rank[rank] = row

    if sorted(tri_by_rank) != EXPECTED:
        print("FAIL: strict triage survivor set mismatch.")
        print("got:", sorted(tri_by_rank))
        return 4

    candidates = {}
    for rank in EXPECTED:
        r = tri_by_rank[rank]
        pra = f(r["poss_ra_deg"])
        pdec = f(r["poss_dec_deg"])
        dra = f(r["dasch_ra_deg"])
        ddec = f(r["dasch_dec_deg"])
        dx, dy, sep, pa = vector_between(pra, pdec, dra, ddec)
        reported = f(r["separation_arcsec"])
        if abs(sep - reported) > 1e-6:
            print(f"FAIL: rank {rank} separation reconstruction mismatch.")
            return 5
        candidates[rank] = {
            "strict_rank": rank,
            "poss_ra_deg": pra,
            "poss_dec_deg": pdec,
            "dasch_ra_deg": dra,
            "dasch_dec_deg": ddec,
            "poss_snr": f(r["poss_snr"]),
            "dasch_snr": f(r["dasch_snr"]),
            "poss_polarity": i(r["poss_polarity"]),
            "dasch_polarity": i(r["dasch_polarity"]),
            "pair_separation_arcsec": sep,
            "dx_east_arcsec": dx,
            "dy_north_arcsec": dy,
            "position_angle_deg_east_of_north": pa,
            "mid_ra_deg": 0.5 * (pra + dra),
            "mid_dec_deg": 0.5 * (pdec + ddec),
        }

    # A) Common-shift diagnostic across the six.
    six_vectors = [
        (candidates[r]["dx_east_arcsec"], candidates[r]["dy_north_arcsec"])
        for r in EXPECTED
    ]
    six_mdx, six_mdy = median_vector(six_vectors)
    six_resids = residuals_from_center(six_vectors, six_mdx, six_mdy)

    print("Six frozen POSS -> DASCH vectors:")
    print("-" * 122)
    for rank, resid in zip(EXPECTED, six_resids):
        c = candidates[rank]
        print(
            f"#{rank:>2} dx={c['dx_east_arcsec']:+.3f}\" "
            f"dy={c['dy_north_arcsec']:+.3f}\" "
            f"sep={c['pair_separation_arcsec']:.3f}\" "
            f"PA={c['position_angle_deg_east_of_north']:.1f}deg "
            f"resid_from_six_median={resid:.3f}\""
        )
    print(
        f"Six-vector median translation: dx={six_mdx:+.3f}\" "
        f"dy={six_mdy:+.3f}\" magnitude={math.hypot(six_mdx,six_mdy):.3f}\""
    )
    print()

    poss_path, dasch_path, cat_prov = resolve_candidate_catalogues()
    print("Native candidate catalogues:")
    print(f"  POSS:  {poss_path}")
    print(f"  DASCH: {dasch_path}")
    print("Loading expected stellar polarities only...")

    poss = load_native_catalogue(poss_path, EXPECTED_POSS_POLARITY)
    dasch = load_native_catalogue(dasch_path, EXPECTED_DASCH_POLARITY)

    print(
        f"  POSS rows total={poss['total_rows']} polarity -1="
        f"{poss['expected_polarity_rows']}"
    )
    print(
        f"  DASCH rows total={dasch['total_rows']} polarity +1="
        f"{dasch['expected_polarity_rows']}"
    )
    print(f"  POSS fields: {poss['resolved_fields']}")
    print(f"  DASCH fields: {dasch['resolved_fields']}")
    print()

    gaia_fields, gaia_all = read_csv_rows(GAIA)
    gaia_by_rank: dict[int, list[dict[str, str]]] = {r: [] for r in EXPECTED}
    for g in gaia_all:
        try:
            rank = i(g["strict_rank"])
        except Exception:
            continue
        if rank in gaia_by_rank:
            gaia_by_rank[rank].append(g)

    results = []
    dense_dump = {}
    gaia_dump = {}

    print("Per-candidate local astrometry:")
    print("-" * 122)

    for rank in EXPECTED:
        c = candidates[rank]

        gaia_controls = gaia_anchor_controls(
            poss, dasch, gaia_by_rank[rank], c
        )
        # Strong Gaia subset: both native detections within 3" of propagated Gaia.
        gaia_strong = [
            x for x in gaia_controls if x["strong_both_within_3arcsec"]
        ]
        # Prefer strong subset for scientific summary, but preserve all <=5" rows.
        gaia_for_summary = (
            gaia_strong if len(gaia_strong) >= 3 else gaia_controls
        )
        gs = summarise_vector_controls(
            gaia_for_summary, c["dx_east_arcsec"], c["dy_north_arcsec"]
        )
        gs["all_within5_count"] = len(gaia_controls)
        gs["strong_both_within3_count"] = len(gaia_strong)
        gs["summary_subset"] = (
            "BOTH_ENDPOINTS_WITHIN_3ARCSEC_OF_GAIA"
            if gaia_for_summary is gaia_strong
            else "BOTH_ENDPOINTS_WITHIN_5ARCSEC_OF_GAIA"
        )

        dense = mutual_nearest_controls(poss, dasch, c)
        ds = summarise_vector_controls(
            dense, c["dx_east_arcsec"], c["dy_north_arcsec"]
        )

        # SNR-matched dense subset, same 0.75-1.25 endpoint ratios used by
        # the matched-peer morphology concept.
        snr_dense = []
        for x in dense:
            pr = x["poss_snr"] / c["poss_snr"] if c["poss_snr"] else 0
            dr = x["dasch_snr"] / c["dasch_snr"] if c["dasch_snr"] else 0
            if (
                SNR_RATIO_LOW <= pr <= SNR_RATIO_HIGH
                and SNR_RATIO_LOW <= dr <= SNR_RATIO_HIGH
            ):
                snr_dense.append(x)
        ss = summarise_vector_controls(
            snr_dense, c["dx_east_arcsec"], c["dy_north_arcsec"]
        )

        label = interpretation(gs, ds, ss)

        result = {
            **c,
            "gaia_query_source_count": len(gaia_by_rank[rank]),
            "gaia_anchor_all_within5_count": len(gaia_controls),
            "gaia_anchor_strong_within3_count": len(gaia_strong),
            "gaia_summary": gs,
            "dense_mutual_control_count": len(dense),
            "dense_summary": ds,
            "snr_matched_dense_control_count": len(snr_dense),
            "snr_matched_dense_summary": ss,
            "local_astrometry_label": label,
        }
        results.append(result)
        dense_dump[str(rank)] = dense
        gaia_dump[str(rank)] = gaia_controls

        def pct_text(v):
            return "n/a" if v is None else f"{100*v:.1f}%"

        print(
            f"#{rank:>2} sep={c['pair_separation_arcsec']:.3f}\" "
            f"Gaia={len(gaia_controls)}(strong={len(gaia_strong)}) "
            f"dense={len(dense)} snrmatch={len(snr_dense)} "
            f"Gaia_resid_pct={pct_text(gs['candidate_residual_empirical_percentile'])} "
            f"dense_resid_pct={pct_text(ds['candidate_residual_empirical_percentile'])} "
            f"snr_resid_pct={pct_text(ss['candidate_residual_empirical_percentile'])} "
            f"{label}"
        )

    payload = {
        "stage": "ORDER01_DISCOVERY_LOCAL_ASTROMETRY_V028L",
        "inputs": {
            "overlap_freeze": str(OVERLAP.relative_to(ROOT)),
            "adjudication": str(ADJ.relative_to(ROOT)),
            "strict_triage": str(TRIAGE.relative_to(ROOT)),
            "gaia_source_candidates": str(GAIA.relative_to(ROOT)),
            **cat_prov,
        },
        "frozen_active_ranks": EXPECTED,
        "guards": {
            "network_access": False,
            "science_pixels_read": False,
            "fits_pixels_read": False,
            "npy_arrays_loaded": False,
            "detector_rerun": False,
            "candidate_promotion": False,
            "candidate_deletion": False,
            "weighted_candidate_score": False,
        },
        "declared_parameters": {
            "local_radius_deg": LOCAL_RADIUS_DEG,
            "science_exclusion_arcsec": SCIENCE_EXCLUSION_ARCSEC,
            "gaia_match_radius_arcsec": GAIA_MATCH_RADIUS_ARCSEC,
            "gaia_strong_match_radius_arcsec": GAIA_STRONG_MATCH_RADIUS_ARCSEC,
            "gaia_min_anchors_for_interpretation":
                GAIA_MIN_ANCHORS_FOR_INTERPRETATION,
            "dense_match_radius_arcsec": DENSE_MATCH_RADIUS_ARCSEC,
            "dense_min_snr": DENSE_MIN_SNR,
            "dense_min_controls_for_interpretation":
                DENSE_MIN_CONTROLS_FOR_INTERPRETATION,
            "snr_ratio_range": [SNR_RATIO_LOW, SNR_RATIO_HIGH],
            "snr_matched_min_controls": SNR_MATCHED_MIN_CONTROLS,
            "expected_poss_polarity": EXPECTED_POSS_POLARITY,
            "expected_dasch_polarity": EXPECTED_DASCH_POLARITY,
        },
        "native_catalogue_schema": {
            "poss": {
                "path": str(poss_path.relative_to(ROOT)),
                "resolved_fields": poss["resolved_fields"],
                "total_rows": poss["total_rows"],
                "expected_polarity_rows": poss["expected_polarity_rows"],
            },
            "dasch": {
                "path": str(dasch_path.relative_to(ROOT)),
                "resolved_fields": dasch["resolved_fields"],
                "total_rows": dasch["total_rows"],
                "expected_polarity_rows": dasch["expected_polarity_rows"],
            },
        },
        "six_vector_common_shift": {
            "median_dx_east_arcsec": six_mdx,
            "median_dy_north_arcsec": six_mdy,
            "median_translation_magnitude_arcsec":
                math.hypot(six_mdx, six_mdy),
            "candidate_residuals_from_six_median_arcsec": {
                str(r): v for r, v in zip(EXPECTED, six_resids)
            },
            "interpretive_note": (
                "Candidate vectors are not assumed to share a common translation. "
                "This stage reports the common-shift diagnostic before local controls."
            ),
        },
        "results": results,
        "gaia_anchor_rows": gaia_dump,
        "dense_control_rows": dense_dump,
        "interpretive_boundary": (
            "Astrometric consistency with ordinary local sources would support only "
            "the positional compatibility of the two detections. It would not prove "
            "that either detection is astrophysical or that the two plates recorded "
            "the same transient event."
        ),
    }
    OUT_JSON.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False),
        encoding="utf-8"
    )

    csv_fields = [
        "strict_rank", "pair_separation_arcsec",
        "dx_east_arcsec", "dy_north_arcsec",
        "position_angle_deg_east_of_north",
        "gaia_query_source_count",
        "gaia_anchor_all_within5_count",
        "gaia_anchor_strong_within3_count",
        "gaia_candidate_residual_arcsec",
        "gaia_candidate_residual_percentile",
        "dense_mutual_control_count",
        "dense_candidate_residual_arcsec",
        "dense_candidate_residual_percentile",
        "snr_matched_dense_control_count",
        "snr_candidate_residual_arcsec",
        "snr_candidate_residual_percentile",
        "local_astrometry_label",
    ]
    with OUT_CSV.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=csv_fields)
        w.writeheader()
        for r in results:
            w.writerow({
                "strict_rank": r["strict_rank"],
                "pair_separation_arcsec": r["pair_separation_arcsec"],
                "dx_east_arcsec": r["dx_east_arcsec"],
                "dy_north_arcsec": r["dy_north_arcsec"],
                "position_angle_deg_east_of_north":
                    r["position_angle_deg_east_of_north"],
                "gaia_query_source_count": r["gaia_query_source_count"],
                "gaia_anchor_all_within5_count":
                    r["gaia_anchor_all_within5_count"],
                "gaia_anchor_strong_within3_count":
                    r["gaia_anchor_strong_within3_count"],
                "gaia_candidate_residual_arcsec":
                    r["gaia_summary"]["candidate_residual_from_local_median_arcsec"],
                "gaia_candidate_residual_percentile":
                    r["gaia_summary"]["candidate_residual_empirical_percentile"],
                "dense_mutual_control_count": r["dense_mutual_control_count"],
                "dense_candidate_residual_arcsec":
                    r["dense_summary"]["candidate_residual_from_local_median_arcsec"],
                "dense_candidate_residual_percentile":
                    r["dense_summary"]["candidate_residual_empirical_percentile"],
                "snr_matched_dense_control_count":
                    r["snr_matched_dense_control_count"],
                "snr_candidate_residual_arcsec":
                    r["snr_matched_dense_summary"]["candidate_residual_from_local_median_arcsec"],
                "snr_candidate_residual_percentile":
                    r["snr_matched_dense_summary"]["candidate_residual_empirical_percentile"],
                "local_astrometry_label": r["local_astrometry_label"],
            })

    md = []
    md.append("# ORDER 01 — Discovery-Pair Local Astrometric Consistency v028l")
    md.append("")
    md.append("## Guardrails")
    md.append("")
    md.append("- No network access.")
    md.append("- No science/FITS pixel read.")
    md.append("- No `.npy` science array loaded.")
    md.append("- No detector rerun.")
    md.append("- No candidate promoted or deleted.")
    md.append("- No weighted candidate score.")
    md.append("")
    md.append("## Six-vector common-shift diagnostic")
    md.append("")
    md.append(
        f"Median POSS→DASCH translation: dx={six_mdx:+.3f}\", "
        f"dy={six_mdy:+.3f}\"; magnitude="
        f"{math.hypot(six_mdx,six_mdy):.3f}\"."
    )
    md.append("")
    md.append(
        "| rank | dx east | dy north | raw separation | PA east of north | "
        "residual from six-vector median |"
    )
    md.append("|---:|---:|---:|---:|---:|---:|")
    for rank, resid in zip(EXPECTED, six_resids):
        c = candidates[rank]
        md.append(
            f"| #{rank} | {c['dx_east_arcsec']:+.3f}\" | "
            f"{c['dy_north_arcsec']:+.3f}\" | "
            f"{c['pair_separation_arcsec']:.3f}\" | "
            f"{c['position_angle_deg_east_of_north']:.1f}° | "
            f"{resid:.3f}\" |"
        )
    md.append("")
    md.append("## Local controls")
    md.append("")
    md.append(
        "| rank | Gaia anchors (strong) | dense controls | SNR-matched | "
        "Gaia residual pct | dense residual pct | SNR residual pct | label |"
    )
    md.append("|---:|---:|---:|---:|---:|---:|---:|---|")
    for r in results:
        def pt(v):
            return "n/a" if v is None else f"{100*v:.1f}%"
        md.append(
            f"| #{r['strict_rank']} | "
            f"{r['gaia_anchor_all_within5_count']} "
            f"({r['gaia_anchor_strong_within3_count']}) | "
            f"{r['dense_mutual_control_count']} | "
            f"{r['snr_matched_dense_control_count']} | "
            f"{pt(r['gaia_summary']['candidate_residual_empirical_percentile'])} | "
            f"{pt(r['dense_summary']['candidate_residual_empirical_percentile'])} | "
            f"{pt(r['snr_matched_dense_summary']['candidate_residual_empirical_percentile'])} | "
            f"`{r['local_astrometry_label']}` |"
        )
    md.append("")
    md.append("## Interpretation boundary")
    md.append("")
    md.append(
        "This stage tests positional consistency only. Agreement with local Gaia "
        "anchors or dense mutual-nearest controls does not establish astrophysical "
        "reality, simultaneity is already frozen separately in v028k, and candidate "
        "state is unchanged."
    )
    md.append("")
    OUT_MD.write_text("\n".join(md), encoding="utf-8")

    print()
    print("Outputs:")
    print(f"  {OUT_JSON}")
    print(f"  {OUT_CSV}")
    print(f"  {OUT_MD}")
    print()
    print("No external query was made.")
    print("No science pixel was read.")
    print("No detector was rerun.")
    print("No candidate was promoted or deleted.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
