#!/usr/bin/env python3
"""
v077 — Pair 17 APPLAUSE independent-physical-plate opportunity census.

Metadata-only stage. It enumerates solved APPLAUSE DR4 physical plates whose
official footprint covers the complete frozen pair-17 population.

NO comparison pixels.
NO recurrence detection.
NO injection/recovery.
NO detector rerun.
NO candidate disposition changes.
"""

from pathlib import Path
from io import BytesIO
from collections import Counter, defaultdict
import csv
import hashlib
import json
import math
import re
import time
import urllib.error
import urllib.parse
import urllib.request

import numpy as np
import pandas as pd
from astropy.io import fits
from astropy.table import Table
from astropy.wcs import WCS

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "results"
RESEARCH = ROOT / "research"

CONTRACT = (
    RESEARCH / "prospective_freezes"
    / "pair17_applause_independent_plate_opportunity_census_contract_v077.json"
)

V075 = (
    RESULTS / "pair17_epoch_aware_gaia_static_triage_v075"
    / "pair17_epoch_aware_gaia_static_triage_v075.csv"
)

V068 = (
    RESULTS / "wide_census_gaia_registration_v068a"
    / "pair_17_registrations_v068a.csv"
)

V076 = RESULTS / "pair17_matched_peer_morphology_v076"

OUT = RESULTS / "pair17_applause_independent_plate_opportunity_census_v077"
CACHE = OUT / "cache"

OUT_OPPS = OUT / "pair17_candidate_plate_opportunities_v077.csv"
OUT_SOL = OUT / "pair17_candidate_solution_coverage_v077.csv"
OUT_PLATES = OUT / "pair17_independent_plate_inventory_v077.csv"
OUT_QUERIES = OUT / "pair17_tap_query_manifest_v077.csv"
OUT_JSON = OUT / "pair17_applause_independent_plate_opportunity_census_v077.json"

EXPECTED_CONTRACT_SHA = "11c5866a24d8e05a8436c443d16af24dcc244982d664e037e5dac75f93f8143f"

EXPECTED_SHA = {
    V075:
        "cc571a4da103dc3900907fe9568567dd540f8f85217b7e7e73ca4442239f2097",
    V068:
        "ebbe6ff5513681a3b98a2f4deda1d4b5c7f563ca284dd399e631237cdae4b7a1",
    V076 / "pair17_morphology_endpoint_metrics_v076.csv":
        "bfccb273c69421be4e5633964c79d17a34298798fc69b39e11c0a83a3bd9da9f",
    V076 / "pair17_morphology_control_metrics_v076.csv":
        "e3d36e92ff3a262071618b1b55a7b3ba5ff896a57ba3732ae1cc4ed8d4759607",
    V076 / "pair17_morphology_pair_summary_v076.csv":
        "5b088b41dbed89f5945152c93145a55e66005ea9fc52449ff5835e31c71d2eca",
    V076 / "pair17_matched_peer_morphology_v076.json":
        "12fd044535cb9f20020ae998571aa521e5695da29b9e19651178e8f0523f749c",
    V076 / "pair17_morphology_pixel_manifest_v076.csv":
        "31ba2e6189fd8bb3f43a76ba363bf68bf10077d48eac33a4b1712f9c7bf80b2d",
}

TAP_SYNC = "https://www.plate-archive.org/tap/sync"
UA = "historical-transient-pipeline/pair17-v077-opportunity-census"
TIMEOUT = 180
MAX_ATTEMPTS = 5
MAXREC = 200000

EXPECTED_TOTAL = 603
EXPECTED_PRIMARY = 424
EXPECTED_DIAGNOSTIC = 179

SCIENCE_PLATES = {7685, 89580}
EDGE_MARGIN_ARCSEC = 30.0

FLOAT_RE = re.compile(
    r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?"
)


def sha256(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for b in iter(lambda: f.read(1024 * 1024), b""):
            h.update(b)
    return h.hexdigest()


def sha_bytes(b):
    return hashlib.sha256(b).hexdigest()


def fail(msg):
    raise RuntimeError(msg)


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


def write_csv_atomic(path, rows, fields):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    tmp.replace(path)


def write_json_atomic(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(obj, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )
    tmp.replace(path)


def table_rows(tbl):
    rows = []
    for tr in tbl:
        d = {}
        for name in tbl.colnames:
            v = tr[name]
            if np.ma.is_masked(v):
                d[name] = ""
            elif isinstance(v, bytes):
                d[name] = v.decode("utf-8", errors="replace")
            elif isinstance(v, np.generic):
                d[name] = v.item()
            else:
                d[name] = v
        rows.append(d)
    return rows


def overflow_in_votable(raw):
    s = raw.decode("utf-8", errors="ignore").upper()
    return (
        'VALUE="OVERFLOW"' in s
        or "VALUE='OVERFLOW'" in s
        or ">OVERFLOW<" in s
    )


query_manifest = []


def tap_query(label, query):
    CACHE.mkdir(parents=True, exist_ok=True)

    qbytes = query.encode("utf-8")
    qsha = sha_bytes(qbytes)

    qfile = CACHE / f"{label}.adql"
    rawfile = CACHE / f"{label}.vot"
    metafile = CACHE / f"{label}.meta.json"

    if qfile.is_file() and rawfile.is_file() and metafile.is_file():
        oldq = qfile.read_text(encoding="utf-8")
        meta = json.loads(metafile.read_text(encoding="utf-8"))
        raw = rawfile.read_bytes()

        if oldq == query and meta.get("query_sha256") == qsha:
            if overflow_in_votable(raw):
                fail(f"{label}: cached TAP response is OVERFLOW")
            tbl = Table.read(BytesIO(raw), format="votable")
            rows = table_rows(tbl)
            query_manifest.append({
                "label": label,
                "query_sha256": qsha,
                "raw_votable_sha256": sha_bytes(raw),
                "row_count": len(rows),
                "overflow": False,
                "cached": True,
                "query_file": str(qfile.relative_to(ROOT)).replace("\\", "/"),
                "raw_file": str(rawfile.relative_to(ROOT)).replace("\\", "/"),
            })
            return rows

    payload = urllib.parse.urlencode({
        "REQUEST": "doQuery",
        "LANG": "ADQL",
        "FORMAT": "votable",
        "RESPONSEFORMAT": "votable",
        "MAXREC": str(MAXREC),
        "QUERY": query,
    }).encode("utf-8")

    last = None

    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            req = urllib.request.Request(
                TAP_SYNC,
                data=payload,
                method="POST",
                headers={
                    "Accept": "application/x-votable+xml,text/xml,*/*",
                    "Content-Type": "application/x-www-form-urlencoded",
                    "User-Agent": UA,
                    "Cache-Control": "no-cache",
                },
            )

            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                raw = resp.read()
                status = int(getattr(resp, "status", 200))
                final_url = resp.geturl()
                ctype = resp.headers.get("Content-Type", "")

            if overflow_in_votable(raw):
                fail(
                    f"{label}: TAP response declares OVERFLOW; "
                    "partial rows are not a complete opportunity census"
                )

            tbl = Table.read(BytesIO(raw), format="votable")
            rows = table_rows(tbl)

            qfile.write_text(query, encoding="utf-8")
            rawfile.write_bytes(raw)

            meta = {
                "label": label,
                "query_sha256": qsha,
                "raw_votable_sha256": sha_bytes(raw),
                "http_status": status,
                "final_url": final_url,
                "content_type": ctype,
                "row_count": len(rows),
                "overflow": False,
                "attempt": attempt,
            }
            write_json_atomic(metafile, meta)

            query_manifest.append({
                "label": label,
                "query_sha256": qsha,
                "raw_votable_sha256": sha_bytes(raw),
                "row_count": len(rows),
                "overflow": False,
                "cached": False,
                "query_file": str(qfile.relative_to(ROOT)).replace("\\", "/"),
                "raw_file": str(rawfile.relative_to(ROOT)).replace("\\", "/"),
            })

            return rows

        except urllib.error.HTTPError as e:
            try:
                body = e.read(6000).decode("utf-8", errors="replace")
            except Exception:
                body = ""
            last = RuntimeError(
                f"HTTP {e.code} {e.reason}; TAP response body={body!r}"
            )
        except Exception as e:
            last = e

        if attempt < MAX_ATTEMPTS:
            time.sleep(min(20.0, 2.0 ** attempt))

    raise RuntimeError(
        f"{label}: APPLAUSE TAP failed after {MAX_ATTEMPTS} attempts: "
        f"{type(last).__name__}: {last}"
    ) from last


# --------------------------------------------------------------------------------------
# Spherical helpers
# --------------------------------------------------------------------------------------

def unit_vector(ra_deg, dec_deg):
    ra = math.radians(float(ra_deg))
    dec = math.radians(float(dec_deg))
    c = math.cos(dec)
    return np.array([c * math.cos(ra), c * math.sin(ra), math.sin(dec)], dtype=float)


def vector_to_radec(v):
    v = np.asarray(v, dtype=float)
    n = np.linalg.norm(v)
    if not math.isfinite(float(n)) or n <= 0:
        fail("Invalid spherical vector")
    v = v / n
    ra = math.degrees(math.atan2(v[1], v[0])) % 360.0
    dec = math.degrees(math.asin(max(-1.0, min(1.0, float(v[2])))))
    return ra, dec


def spherical_midpoint(ra1, dec1, ra2, dec2):
    v = unit_vector(ra1, dec1) + unit_vector(ra2, dec2)
    return vector_to_radec(v)


def angular_sep_deg(ra1, dec1, ra2, dec2):
    a = unit_vector(ra1, dec1)
    b = unit_vector(ra2, dec2)
    dot = float(np.dot(a, b))
    dot = max(-1.0, min(1.0, dot))
    return math.degrees(math.acos(dot))


def spherical_mean(radec):
    v = np.zeros(3, dtype=float)
    for ra, dec in radec:
        v += unit_vector(ra, dec)
    return vector_to_radec(v)


def tangent_xy_rad(target_ra, target_dec, ra, dec):
    ra0 = math.radians(target_ra)
    dec0 = math.radians(target_dec)

    z = unit_vector(target_ra, target_dec)
    east = np.array([-math.sin(ra0), math.cos(ra0), 0.0], dtype=float)
    north = np.array(
        [
            -math.sin(dec0) * math.cos(ra0),
            -math.sin(dec0) * math.sin(ra0),
            math.cos(dec0),
        ],
        dtype=float,
    )

    v = unit_vector(ra, dec)
    den = float(np.dot(v, z))
    if den <= 0:
        return None

    return float(np.dot(v, east) / den), float(np.dot(v, north) / den)


def point_in_polygon_origin(poly):
    inside = False
    n = len(poly)
    if n < 3:
        return False

    x = 0.0
    y = 0.0

    for i in range(n):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % n]

        if (y1 > y) != (y2 > y):
            den = y2 - y1
            if den == 0:
                continue
            x_cross = x1 + (y - y1) * (x2 - x1) / den
            if x < x_cross:
                inside = not inside

    return inside


def distance_origin_to_segment(x1, y1, x2, y2):
    vx = x2 - x1
    vy = y2 - y1
    vv = vx * vx + vy * vy

    if vv <= 0:
        return math.hypot(x1, y1)

    t = -(x1 * vx + y1 * vy) / vv
    t = min(1.0, max(0.0, t))
    px = x1 + t * vx
    py = y1 + t * vy
    return math.hypot(px, py)


def classify_coverage(target_ra, target_dec, polygon):
    xy = []

    for ra, dec in polygon:
        q = tangent_xy_rad(target_ra, target_dec, ra, dec)
        if q is None:
            return "GEOMETRY_UNRESOLVED", None
        xy.append(q)

    if point_in_polygon_origin(xy):
        return "COVERED_INTERIOR", 0.0

    mind = min(
        distance_origin_to_segment(
            xy[i][0], xy[i][1],
            xy[(i + 1) % len(xy)][0],
            xy[(i + 1) % len(xy)][1],
        )
        for i in range(len(xy))
    )

    edge_arcsec = math.degrees(math.atan(mind)) * 3600.0

    if edge_arcsec <= EDGE_MARGIN_ARCSEC:
        return "COVERED_EDGE_MARGIN_30ARCSEC", edge_arcsec

    return "NOT_COVERED", edge_arcsec


# --------------------------------------------------------------------------------------
# Footprints
# --------------------------------------------------------------------------------------

def parse_stc_polygon(text):
    s = "" if text is None else str(text).strip()
    if not s:
        return None

    vals = [float(x) for x in FLOAT_RE.findall(s)]

    # APPLAUSE stc_polygon products used by the frozen wide census are 4-corner
    # polygons. Preserve more vertices if provided.
    if len(vals) < 6 or len(vals) % 2:
        return None

    pts = [(vals[i] % 360.0, vals[i + 1]) for i in range(0, len(vals), 2)]

    if any(
        not (math.isfinite(ra) and math.isfinite(dec) and -90 <= dec <= 90)
        for ra, dec in pts
    ):
        return None

    return pts


def parse_header(text):
    s = "" if text is None else str(text)
    if not s.strip():
        return None

    for sep in ("\n", ""):
        try:
            h = fits.Header.fromstring(s, sep=sep)
            w = WCS(h)
            if w.has_celestial:
                return h, w
        except Exception:
            pass

    return None


def footprint_from_row(row):
    stc = parse_stc_polygon(row.get("stc_polygon"))

    if stc is not None:
        return stc, "OFFICIAL_STC_POLYGON"

    nx = fint(row.get("naxis1"))
    ny = fint(row.get("naxis2"))
    parsed = parse_header(row.get("header_wcs"))

    if parsed is None or nx is None or ny is None or nx <= 1 or ny <= 1:
        return None, "NO_USABLE_EXACT_FOOTPRINT"

    _, w = parsed

    try:
        pts = w.calc_footprint(axes=(nx, ny))
    except Exception:
        return None, "HEADER_WCS_FOOTPRINT_ERROR"

    if pts is None or len(pts) < 3:
        return None, "HEADER_WCS_FOOTPRINT_ERROR"

    out = []

    for ra, dec in pts:
        ra = float(ra) % 360.0
        dec = float(dec)
        if not (math.isfinite(ra) and math.isfinite(dec)):
            return None, "HEADER_WCS_FOOTPRINT_NONFINITE"
        out.append((ra, dec))

    return out, "OFFICIAL_HEADER_WCS_PLUS_SCAN_DIMENSIONS"


# --------------------------------------------------------------------------------------
# ADQL construction
# --------------------------------------------------------------------------------------

def max_fov_query():
    return """SELECT
  MAX(fov1) AS max_fov1,
  MAX(fov2) AS max_fov2
FROM applause_dr4.solution
"""


def ra_condition(center_ra, radius_deg):
    if radius_deg >= 180.0:
        return "1=1"

    cosd = math.cos(math.radians(max(-89.0, min(89.0, 0.0))))
    # The caller passes an already conservative full cap. We later use the
    # field-center declination-specific expansion instead of this fallback.
    half = radius_deg / max(cosd, 1e-6)
    lo = (center_ra - half) % 360.0
    hi = (center_ra + half) % 360.0

    if lo <= hi:
        return f"(s.ra_icrs >= {lo:.12f} AND s.ra_icrs <= {hi:.12f})"

    return f"(s.ra_icrs >= {lo:.12f} OR s.ra_icrs <= {hi:.12f})"


def solution_query(center_ra, center_dec, radius_deg):
    dec_lo = max(-90.0, center_dec - radius_deg)
    dec_hi = min(90.0, center_dec + radius_deg)

    # RA expansion uses the smallest absolute cosine within the declination
    # strip, giving a rectangle that contains the spherical cap.
    max_abs_dec = max(abs(dec_lo), abs(dec_hi))
    if max_abs_dec >= 89.999:
        racond = "1=1"
    else:
        c = math.cos(math.radians(max_abs_dec))
        half_ra = min(180.0, radius_deg / max(c, 1e-6))
        lo = (center_ra - half_ra) % 360.0
        hi = (center_ra + half_ra) % 360.0

        if half_ra >= 180.0:
            racond = "1=1"
        elif lo <= hi:
            racond = (
                f"(s.ra_icrs >= {lo:.12f} AND s.ra_icrs <= {hi:.12f})"
            )
        else:
            racond = (
                f"(s.ra_icrs >= {lo:.12f} OR s.ra_icrs <= {hi:.12f})"
            )

    return f"""SELECT
  s.solution_id,
  s.process_id,
  s.solutionset_id,
  s.scan_id,
  s.plate_id,
  s.archive_id,
  s.solution_num,
  s.ra_icrs,
  s.dec_icrs,
  s.fov1,
  s.fov2,
  s.pixel_scale,
  s.stc_polygon,
  s.header_wcs,
  c.filename_scan,
  c.naxis1,
  c.naxis2,
  c.file_size,
  c.fits_checksum
FROM applause_dr4.solution AS s, applause_dr4.scan AS c
WHERE s.scan_id = c.scan_id
  AND s.dec_icrs >= {dec_lo:.12f}
  AND s.dec_icrs <= {dec_hi:.12f}
  AND {racond}
ORDER BY s.plate_id, s.scan_id, s.solution_num, s.solution_id
"""


def exposure_query(plate_ids):
    ors = " OR ".join(f"e.plate_id={int(x)}" for x in sorted(set(plate_ids)))

    return f"""SELECT
  e.exposure_id,
  e.plate_id,
  e.archive_id,
  e.ra_icrs,
  e.dec_icrs,
  e.date_orig_start,
  e.date_orig_end,
  e.ut_start,
  e.ut_mid,
  e.ut_end,
  e.exptime,
  a.archive_name,
  a.institute
FROM applause_dr4.exposure AS e, applause_dr4.archive AS a
WHERE e.archive_id = a.archive_id
  AND ({ors})
ORDER BY e.plate_id, e.exposure_id
"""


# --------------------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------------------

def main():
    print("=" * 132)
    print("PAIR 17 — APPLAUSE INDEPENDENT PHYSICAL-PLATE OPPORTUNITY CENSUS v077")
    print("=" * 132)
    print("Metadata-only census.")
    print("Comparison pixels:       NO")
    print("Recurrence measurements: NO")
    print("Injection measurements:  NO")
    print("Disposition changes:     NONE")
    print()

    if not CONTRACT.is_file():
        fail(f"Missing frozen v077 contract: {CONTRACT}")

    actual_contract_sha = sha256(CONTRACT)
    if actual_contract_sha != EXPECTED_CONTRACT_SHA:
        fail(
            f"v077 contract SHA mismatch:\n"
            f"expected {EXPECTED_CONTRACT_SHA}\n"
            f"actual   {actual_contract_sha}"
        )

    for p, expected in EXPECTED_SHA.items():
        if not p.is_file():
            fail(f"Missing frozen upstream product: {p}")
        actual = sha256(p)
        if actual != expected:
            fail(
                f"Frozen upstream SHA mismatch:\n{p}\n"
                f"expected {expected}\nactual   {actual}"
            )
        print("HASH PASS:", p.relative_to(ROOT))

    # v076 is hash-guarded but never read for subsetting.
    targets = pd.read_csv(V075, dtype=str, keep_default_na=False)

    if len(targets) != EXPECTED_TOTAL:
        fail(f"v075 population changed: {len(targets)}")

    pops = Counter(targets["population"].astype(str))

    if pops.get("PRIMARY_424", 0) != EXPECTED_PRIMARY:
        fail(f"PRIMARY population changed: {pops}")
    if pops.get("DIAGNOSTIC_179", 0) != EXPECTED_DIAGNOSTIC:
        fail(f"DIAGNOSTIC population changed: {pops}")

    needed = {
        "raw_match_row", "population",
        "a_ra_deg", "a_dec_deg",
        "b_ra_deg", "b_dec_deg",
    }

    if not needed.issubset(targets.columns):
        fail(
            f"v075 does not contain required coverage coordinates: "
            f"{sorted(needed - set(targets.columns))}"
        )

    loci = []

    for _, r in targets.iterrows():
        vals = [
            ffloat(r["a_ra_deg"]), ffloat(r["a_dec_deg"]),
            ffloat(r["b_ra_deg"]), ffloat(r["b_dec_deg"]),
        ]

        if any(v is None for v in vals):
            fail(f"Non-finite frozen endpoint coordinate raw_match_row={r['raw_match_row']}")

        ra, dec = spherical_midpoint(*vals)

        loci.append({
            "raw_match_row": str(r["raw_match_row"]),
            "population": str(r["population"]),
            "locus_ra_deg": ra,
            "locus_dec_deg": dec,
        })

    if len({r["raw_match_row"] for r in loci}) != EXPECTED_TOTAL:
        fail("Frozen candidate identities are not unique")

    center_ra, center_dec = spherical_mean(
        [(r["locus_ra_deg"], r["locus_dec_deg"]) for r in loci]
    )

    target_cap = max(
        angular_sep_deg(center_ra, center_dec, r["locus_ra_deg"], r["locus_dec_deg"])
        for r in loci
    )

    print()
    print(f"Frozen coverage loci: {len(loci)}")
    print(f"Target cap center: RA={center_ra:.8f} Dec={center_dec:.8f}")
    print(f"Target cap radius: {target_cap:.6f} deg")

    # Query the global solution FOV bound before the candidate-region query.
    fov_rows = tap_query("global_solution_max_fov_v077", max_fov_query())

    if len(fov_rows) != 1:
        fail(f"Unexpected global MAX(fov) row count: {len(fov_rows)}")

    max_fov1 = ffloat(fov_rows[0].get("max_fov1"))
    max_fov2 = ffloat(fov_rows[0].get("max_fov2"))

    if (
        max_fov1 is None or max_fov2 is None
        or max_fov1 <= 0 or max_fov2 <= 0
    ):
        fail(f"Invalid global APPLAUSE FOV bound: {fov_rows[0]}")

    half_diag = 0.5 * math.hypot(max_fov1, max_fov2)
    query_radius = target_cap + half_diag + 1.0

    if query_radius >= 90.0:
        fail(
            f"Conservative solution query radius unexpectedly huge: "
            f"{query_radius:.3f} deg"
        )

    print(f"Global max fov1/fov2: {max_fov1:.6f} / {max_fov2:.6f} deg")
    print(f"Conservative solution-center radius: {query_radius:.6f} deg")

    sol_rows = tap_query(
        "candidate_region_solution_scan_superset_v077",
        solution_query(center_ra, center_dec, query_radius),
    )

    print(f"Solution/scan superset rows: {len(sol_rows):,}")

    # Local spherical-cap filter after conservative rectangle retrieval.
    cap_rows = []

    for r in sol_rows:
        ra = ffloat(r.get("ra_icrs"))
        dec = ffloat(r.get("dec_icrs"))

        if ra is None or dec is None:
            continue

        if angular_sep_deg(center_ra, center_dec, ra, dec) <= query_radius:
            cap_rows.append(r)

    print(f"Solution rows inside conservative cap: {len(cap_rows):,}")

    plate_ids = sorted({
        fint(r.get("plate_id"))
        for r in cap_rows
        if fint(r.get("plate_id")) is not None
    })

    if not plate_ids:
        fail("No APPLAUSE plate IDs returned in the conservative solution cap")

    # Exposure provenance is retrieved for every physical plate in the solution cap,
    # in bounded deterministic chunks.
    exp_rows = []

    chunk_size = 200
    for start in range(0, len(plate_ids), chunk_size):
        chunk = plate_ids[start:start + chunk_size]
        label = f"plate_exposures_{start//chunk_size:04d}_v077"
        rows = tap_query(label, exposure_query(chunk))
        exp_rows.extend(rows)
        print(
            f"Exposure provenance chunk {start//chunk_size + 1}: "
            f"{len(rows):,} rows"
        )

    exposures_by_plate = defaultdict(list)

    for r in exp_rows:
        pid = fint(r.get("plate_id"))
        if pid is not None:
            exposures_by_plate[pid].append(r)

    # Pre-parse footprints once.
    parsed_solutions = []
    geometry_state_counts = Counter()

    for order, r in enumerate(cap_rows, 1):
        pid = fint(r.get("plate_id"))
        sid = fint(r.get("solution_id"))
        scan_id = fint(r.get("scan_id"))

        polygon, provenance = footprint_from_row(r)

        geometry_state_counts[provenance] += 1

        parsed_solutions.append({
            "solution_order": order,
            "plate_id": pid,
            "solution_id": sid,
            "scan_id": scan_id,
            "archive_id": fint(r.get("archive_id")),
            "solution_num": fint(r.get("solution_num")),
            "solution_ra_icrs": ffloat(r.get("ra_icrs")),
            "solution_dec_icrs": ffloat(r.get("dec_icrs")),
            "fov1": ffloat(r.get("fov1")),
            "fov2": ffloat(r.get("fov2")),
            "filename_scan": str(r.get("filename_scan") or ""),
            "naxis1": fint(r.get("naxis1")),
            "naxis2": fint(r.get("naxis2")),
            "file_size": fint(r.get("file_size")),
            "fits_checksum": str(r.get("fits_checksum") or ""),
            "footprint_provenance": provenance,
            "polygon": polygon,
        })

    # Evaluate every candidate against every solution in the conservative cap.
    solution_coverage = []
    candidate_plate_best = {}

    provenance_rank = {
        "OFFICIAL_STC_POLYGON": 0,
        "OFFICIAL_HEADER_WCS_PLUS_SCAN_DIMENSIONS": 1,
    }

    for ci, target in enumerate(loci, 1):
        tra = target["locus_ra_deg"]
        tdec = target["locus_dec_deg"]

        for s in parsed_solutions:
            pid = s["plate_id"]

            if pid is None:
                continue

            if s["polygon"] is None:
                coverage = "GEOMETRY_UNRESOLVED"
                edge = None
            else:
                coverage, edge = classify_coverage(
                    tra, tdec, s["polygon"]
                )

            independent = pid not in SCIENCE_PLATES
            scan_metadata_present = (
                bool(s["filename_scan"])
                and s["scan_id"] is not None
                and s["naxis1"] is not None
                and s["naxis2"] is not None
            )

            eligible = (
                independent
                and coverage in {
                    "COVERED_INTERIOR",
                    "COVERED_EDGE_MARGIN_30ARCSEC",
                }
                and scan_metadata_present
            )

            row = {
                "raw_match_row": target["raw_match_row"],
                "population": target["population"],
                "locus_ra_deg": tra,
                "locus_dec_deg": tdec,
                "plate_id": pid,
                "solution_id": s["solution_id"],
                "scan_id": s["scan_id"],
                "archive_id": s["archive_id"],
                "solution_num": s["solution_num"],
                "solution_ra_icrs": s["solution_ra_icrs"],
                "solution_dec_icrs": s["solution_dec_icrs"],
                "fov1": s["fov1"],
                "fov2": s["fov2"],
                "filename_scan": s["filename_scan"],
                "naxis1": s["naxis1"],
                "naxis2": s["naxis2"],
                "file_size": s["file_size"],
                "fits_checksum": s["fits_checksum"],
                "footprint_provenance": s["footprint_provenance"],
                "coverage_class": coverage,
                "edge_distance_arcsec": edge,
                "independent_physical_plate": independent,
                "scan_metadata_present": scan_metadata_present,
                "eligible_independent_comparison": eligible,
            }

            solution_coverage.append(row)

            if not eligible:
                continue

            key = (target["raw_match_row"], pid)

            rank = (
                0 if coverage == "COVERED_INTERIOR" else 1,
                provenance_rank.get(s["footprint_provenance"], 9),
                s["solution_id"] if s["solution_id"] is not None else 10**30,
                s["scan_id"] if s["scan_id"] is not None else 10**30,
            )

            old = candidate_plate_best.get(key)

            if old is None or rank < old[0]:
                candidate_plate_best[key] = (rank, row)

        if ci % 50 == 0 or ci == len(loci):
            print(f"Coverage evaluated {ci}/{len(loci)} candidates", flush=True)

    opp_rows = []

    for (_, pid), (_, best) in sorted(
        candidate_plate_best.items(),
        key=lambda kv: (int(kv[0][0]), kv[0][1]),
    ):
        exps = exposures_by_plate.get(pid, [])

        exposure_ids = sorted({
            fint(x.get("exposure_id"))
            for x in exps
            if fint(x.get("exposure_id")) is not None
        })

        archive_names = sorted({
            str(x.get("archive_name") or "").strip()
            for x in exps
            if str(x.get("archive_name") or "").strip()
        })

        institutes = sorted({
            str(x.get("institute") or "").strip()
            for x in exps
            if str(x.get("institute") or "").strip()
        })

        starts = sorted({
            str(x.get("date_orig_start") or x.get("ut_start") or "").strip()
            for x in exps
            if str(x.get("date_orig_start") or x.get("ut_start") or "").strip()
        })

        opp_rows.append({
            **best,
            "physical_opportunity_plate_id": pid,
            "physical_plate_exposure_row_count": len(exps),
            "physical_plate_exposure_ids": ";".join(str(x) for x in exposure_ids),
            "archive_names": ";".join(archive_names),
            "institutes": ";".join(institutes),
            "exposure_start_values": ";".join(starts),
            "physical_plate_counting_unit": 1,
        })

    # Plate inventory, independent of candidate multiplicity.
    plate_inventory = []

    solutions_by_plate = defaultdict(list)

    for s in parsed_solutions:
        if s["plate_id"] is not None:
            solutions_by_plate[s["plate_id"]].append(s)

    for pid in sorted(solutions_by_plate):
        ss = solutions_by_plate[pid]
        exps = exposures_by_plate.get(pid, [])
        plate_inventory.append({
            "plate_id": pid,
            "is_science_pair_plate": pid in SCIENCE_PLATES,
            "solution_rows_in_conservative_cap": len(ss),
            "usable_exact_footprint_solution_rows":
                sum(s["polygon"] is not None for s in ss),
            "scan_ids": ";".join(
                str(x) for x in sorted({
                    s["scan_id"] for s in ss if s["scan_id"] is not None
                })
            ),
            "filenames_scan": ";".join(
                sorted({s["filename_scan"] for s in ss if s["filename_scan"]})
            ),
            "exposure_row_count": len(exps),
            "exposure_ids": ";".join(
                str(x) for x in sorted({
                    fint(e.get("exposure_id"))
                    for e in exps
                    if fint(e.get("exposure_id")) is not None
                })
            ),
            "archive_names": ";".join(
                sorted({
                    str(e.get("archive_name") or "").strip()
                    for e in exps
                    if str(e.get("archive_name") or "").strip()
                })
            ),
        })

    per_candidate_counts = Counter()

    opps_by_candidate = Counter(
        r["raw_match_row"] for r in opp_rows
    )

    for t in loci:
        per_candidate_counts[opps_by_candidate[t["raw_match_row"]]] += 1

    def pop_summary(pop):
        ids = {
            r["raw_match_row"]
            for r in loci
            if r["population"] == pop
        }
        q = [r for r in opp_rows if r["raw_match_row"] in ids]
        per = Counter(r["raw_match_row"] for r in q)
        vals = [per[x] for x in ids]
        return {
            "candidate_count": len(ids),
            "candidate_plate_opportunity_rows": len(q),
            "unique_independent_physical_plates": len({
                r["physical_opportunity_plate_id"] for r in q
            }),
            "candidates_with_zero_opportunities": sum(v == 0 for v in vals),
            "opportunities_per_candidate_min": min(vals) if vals else None,
            "opportunities_per_candidate_median":
                float(np.median(vals)) if vals else None,
            "opportunities_per_candidate_max": max(vals) if vals else None,
        }

    # Write outputs.
    sol_fields = list(solution_coverage[0].keys()) if solution_coverage else [
        "raw_match_row", "population"
    ]
    opp_fields = list(opp_rows[0].keys()) if opp_rows else [
        "raw_match_row", "population", "physical_opportunity_plate_id"
    ]
    plate_fields = list(plate_inventory[0].keys()) if plate_inventory else ["plate_id"]
    query_fields = [
        "label", "query_sha256", "raw_votable_sha256", "row_count",
        "overflow", "cached", "query_file", "raw_file",
    ]

    write_csv_atomic(OUT_SOL, solution_coverage, sol_fields)
    write_csv_atomic(OUT_OPPS, opp_rows, opp_fields)
    write_csv_atomic(OUT_PLATES, plate_inventory, plate_fields)
    write_csv_atomic(OUT_QUERIES, query_manifest, query_fields)

    report = {
        "status": "COMPLETE",
        "analysis_kind":
            "pair17_applause_independent_plate_opportunity_census_v077",
        "contract_sha256": EXPECTED_CONTRACT_SHA,
        "population": {
            "all": EXPECTED_TOTAL,
            "primary": EXPECTED_PRIMARY,
            "diagnostic": EXPECTED_DIAGNOSTIC,
            "gaia_subsetting": False,
            "morphology_subsetting": False,
        },
        "target_cap": {
            "center_ra_deg": center_ra,
            "center_dec_deg": center_dec,
            "radius_deg": target_cap,
        },
        "solution_query": {
            "global_max_fov1_deg": max_fov1,
            "global_max_fov2_deg": max_fov2,
            "global_max_half_diagonal_deg": half_diag,
            "conservative_solution_center_radius_deg": query_radius,
            "solution_scan_superset_rows": len(sol_rows),
            "solution_rows_inside_conservative_cap": len(cap_rows),
            "physical_plates_inside_conservative_cap": len(plate_ids),
            "geometry_state_counts": dict(sorted(geometry_state_counts.items())),
        },
        "opportunity": {
            "edge_margin_arcsec": EDGE_MARGIN_ARCSEC,
            "science_plate_ids_excluded": sorted(SCIENCE_PLATES),
            "all_603": {
                "candidate_plate_opportunity_rows": len(opp_rows),
                "unique_independent_physical_plates": len({
                    r["physical_opportunity_plate_id"] for r in opp_rows
                }),
                "candidates_with_zero_opportunities":
                    sum(opps_by_candidate[t["raw_match_row"]] == 0 for t in loci),
            },
            "PRIMARY_424": pop_summary("PRIMARY_424"),
            "DIAGNOSTIC_179": pop_summary("DIAGNOSTIC_179"),
            "distribution_opportunities_per_candidate":
                {str(k): v for k, v in sorted(per_candidate_counts.items())},
        },
        "guards": {
            "comparison_pixels_read": 0,
            "recurrence_measurements": 0,
            "injection_measurements": 0,
            "detector_rerun": False,
            "registration_rerun": False,
            "candidate_disposition_changes": False,
        },
        "interpretation": {
            "zero_opportunity_is_negative_recurrence_evidence": False,
            "unresolved_geometry_is_noncoverage": False,
            "v077_is_metadata_opportunity_census_only": True,
            "next_stage":
                "freeze comparison-scan acquisition and sensitivity-qualified recurrence/injection-recovery",
        },
        "outputs": {
            "candidate_plate_opportunities":
                str(OUT_OPPS.relative_to(ROOT)).replace("\\", "/"),
            "candidate_solution_coverage":
                str(OUT_SOL.relative_to(ROOT)).replace("\\", "/"),
            "plate_inventory":
                str(OUT_PLATES.relative_to(ROOT)).replace("\\", "/"),
            "tap_query_manifest":
                str(OUT_QUERIES.relative_to(ROOT)).replace("\\", "/"),
        },
    }

    write_json_atomic(OUT_JSON, report)

    print()
    print("=" * 132)
    print("v077 OPPORTUNITY CENSUS COMPLETE")
    print("=" * 132)

    for pop in ("PRIMARY_424", "DIAGNOSTIC_179"):
        x = report["opportunity"][pop]
        print(pop)
        print(f"  candidates:                       {x['candidate_count']}")
        print(f"  candidate x physical-plate rows: {x['candidate_plate_opportunity_rows']}")
        print(f"  unique independent plates:       {x['unique_independent_physical_plates']}")
        print(f"  candidates with zero opportunity:{x['candidates_with_zero_opportunities']}")
        print(
            "  opportunities/candidate min/med/max: "
            f"{x['opportunities_per_candidate_min']} / "
            f"{x['opportunities_per_candidate_median']} / "
            f"{x['opportunities_per_candidate_max']}"
        )

    print()
    print("Comparison pixels read:            0")
    print("Recurrence measurements performed: 0")
    print("Injection measurements performed:  0")
    print("Candidate dispositions changed:    NONE")
    print("STAGE STATUS: COMPLETE")


if __name__ == "__main__":
    main()
