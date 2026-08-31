
from __future__ import annotations

from pathlib import Path
import base64
import csv
import gzip
import hashlib
import html
import io
import json
import math
import re
import shutil
import urllib.parse
import urllib.request

import numpy as np
from astropy.io import fits
from astropy.io.votable import parse_single_table
from astropy.wcs import WCS

ROOT = Path.cwd()

FOOT = ROOT / "results" / "wide_census_exact_footprint_v052.json"
DET_PLAN = ROOT / "results" / "wide_census_detector_execution_plan_v053.json"
DET_QUEUE = ROOT / "results" / "wide_census_detector_execution_queue_v053.csv"
POLICY = ROOT / "config" / "candidate_adjudication_policy_v002.json"
NATIVE_POLICY = ROOT / "research" / "NATIVE_TILE_EXECUTION_POLICY_V028_2026-08-21.json"
DETECTOR = ROOT / "src" / "transient_pipeline" / "detector.py"
METHOD = ROOT / "config" / "frozen_method.json"

V052_CACHE = ROOT / "results" / "wide_census_exact_footprint_v052" / "cache"

OUT_DIR = ROOT / "results" / "wide_census_heavy_preflight_v054"
CACHE = OUT_DIR / "cache"
CHECKPOINT = OUT_DIR / "checkpoint_v054.json"

OUT_JSON = ROOT / "results" / "wide_census_heavy_preflight_v054.json"
ENDPOINT_CSV = ROOT / "results" / "wide_census_detector_endpoint_plan_v054.csv"
PAIR_JSON = ROOT / "results" / "wide_census_detector_pair_plan_v054.json"
TILE_CSV = ROOT / "results" / "wide_census_detector_tile_plan_v054.csv"

TAP_URL = "https://www.plate-archive.org/tap/sync"
DATALINK_BASE = "https://www.plate-archive.org/datalink/plates"
UA = "historical-transient-pipeline/heavy-preflight-v054"

EXPECTED_DETECTOR_SHA = "709da8d7a7972b15808d70a1e4dbffa0fd0fee864a81d954f74fe4a5f5af25e7"
EXPECTED_METHOD_SHA = "2cb3cabd573d7af99399899f2ccecd3002be90297e55bb0e0dcdd9dea1d0c4c1"
EXPECTED_QUEUE = 33
EXPECTED_APPLAUSE_PLATES = 30
EXPECTED_DASCH_PLATES = 14
EXPECTED_POLICY_ID = "candidate_adjudication_policy_v002"

CORE = 1024
HALO = 64
MAX_TRANSPORT_ATTEMPTS = 4
DATALINK_BATCH = 8


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def read_csv(path: Path):
    with path.open(newline="", encoding="utf-8-sig") as fh:
        return list(csv.DictReader(fh))


def load_json(path: Path, default=None):
    if not path.is_file():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(obj, indent=2, sort_keys=True, default=jdefault) + "\n",
        encoding="utf-8",
    )
    tmp.replace(path)


def jdefault(obj):
    if isinstance(obj, np.generic):
        return obj.item()
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    if isinstance(obj, Path):
        return str(obj)
    return str(obj)


def fnum(v):
    try:
        x = float(str(v).strip())
        return x if math.isfinite(x) else None
    except Exception:
        return None


def inum(v):
    try:
        return int(float(str(v).strip()))
    except Exception:
        return None


def _scalar_text(value):
    if value is None:
        return ""
    try:
        if np.ma.is_masked(value):
            return ""
    except Exception:
        pass
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="strict")
    try:
        value = value.item()
    except Exception:
        pass
    return str(value)


def tap_query(adql: str):
    data = urllib.parse.urlencode({
        "REQUEST": "doQuery",
        "LANG": "ADQL",
        "FORMAT": "votable",
        "QUERY": adql,
    }).encode("utf-8")
    req = urllib.request.Request(
        TAP_URL,
        data=data,
        method="POST",
        headers={
            "User-Agent": UA,
            "Accept": "application/x-votable+xml,text/xml,*/*",
            "Content-Type": "application/x-www-form-urlencoded",
        },
    )
    with urllib.request.urlopen(req, timeout=180) as response:
        raw = response.read()
        status = getattr(response, "status", None)
        final_url = response.geturl()
        content_type = str(response.headers.get("Content-Type", "") or "")

    probe = raw[:1000].lstrip().lower()
    if b"<votable" in probe or "votable" in content_type.lower():
        table = parse_single_table(io.BytesIO(raw)).to_table(use_names_over_ids=True)
        rows = []
        for record in table:
            row = {}
            for name in table.colnames:
                row[str(name).lower()] = _scalar_text(record[name])
            rows.append(row)
        fmt = "votable"
    else:
        text = raw.decode("utf-8-sig", errors="strict")
        if "<html" in text[:500].lower():
            raise RuntimeError("APPLAUSE TAP returned HTML, not a result table")
        rows = [
            {str(k).lower(): v for k, v in row.items()}
            for row in csv.DictReader(io.StringIO(text))
        ]
        fmt = "csv"

    if not rows:
        raise RuntimeError("APPLAUSE TAP returned zero rows")

    return rows, {
        "http_status": status,
        "final_url": final_url,
        "content_type": content_type,
        "response_format": fmt,
        "response_sha256": hashlib.sha256(raw).hexdigest(),
        "row_count": len(rows),
        "query": adql,
    }


def checkpoint_default():
    return {
        "status": "IN_PROGRESS",
        "attempts": {},
        "terminal": {},
        "last_error": None,
    }


def mark_failure(cp, key, exc):
    n = int(cp["attempts"].get(key, 0)) + 1
    cp["attempts"][key] = n
    cp["last_error"] = {
        "key": key,
        "attempt": n,
        "type": type(exc).__name__,
        "message": str(exc),
    }
    if n >= MAX_TRANSPORT_ATTEMPTS:
        cp["terminal"][key] = cp["last_error"]
    write_json(CHECKPOINT, cp)
    return n


def angular_sep_deg(ra1, dec1, ra2, dec2):
    r1, d1, r2, d2 = map(math.radians, (ra1, dec1, ra2, dec2))
    a = (
        math.sin((d2-d1)/2.0)**2
        + math.cos(d1)*math.cos(d2)*math.sin((r2-r1)/2.0)**2
    )
    return math.degrees(2.0 * math.asin(math.sqrt(min(1.0, max(0.0, a)))))


def unitvec(ra_deg, dec_deg):
    ra = math.radians(ra_deg)
    dec = math.radians(dec_deg)
    return np.array([
        math.cos(dec) * math.cos(ra),
        math.cos(dec) * math.sin(ra),
        math.sin(dec),
    ], dtype=float)


def tangent_basis(polys):
    vectors = [unitvec(ra, dec) for poly in polys for ra, dec in poly]
    center = np.sum(vectors, axis=0)
    center /= np.linalg.norm(center)
    z = np.array([0.0, 0.0, 1.0])
    east = np.cross(z, center)
    if np.linalg.norm(east) < 1e-8:
        east = np.cross(np.array([1.0, 0.0, 0.0]), center)
    east /= np.linalg.norm(east)
    north = np.cross(center, east)
    north /= np.linalg.norm(north)
    return center, east, north


def project_poly(poly, center, east, north):
    out = []
    for ra, dec in poly:
        v = unitvec(ra, dec)
        den = float(np.dot(v, center))
        if den <= 0:
            raise RuntimeError("Footprint leaves common tangent hemisphere")
        out.append((
            float(np.dot(v, east)) / den,
            float(np.dot(v, north)) / den,
        ))
    return out


def unproject_poly(poly, center, east, north):
    out = []
    for x, y in poly:
        v = center + x * east + y * north
        v /= np.linalg.norm(v)
        ra = math.degrees(math.atan2(v[1], v[0])) % 360.0
        dec = math.degrees(math.asin(float(v[2])))
        out.append((ra, dec))
    return out


def area2(poly):
    return sum(
        poly[i][0] * poly[(i+1) % len(poly)][1]
        - poly[(i+1) % len(poly)][0] * poly[i][1]
        for i in range(len(poly))
    )


def ensure_ccw(poly):
    return list(reversed(poly)) if area2(poly) < 0 else list(poly)


def inside(p, a, b):
    return (
        (b[0]-a[0])*(p[1]-a[1])
        - (b[1]-a[1])*(p[0]-a[0])
    ) >= -1e-14


def line_intersection(p1, p2, q1, q2):
    x1, y1 = p1
    x2, y2 = p2
    x3, y3 = q1
    x4, y4 = q2
    den = (x1-x2)*(y3-y4) - (y1-y2)*(x3-x4)
    if abs(den) < 1e-15:
        return p2
    px = (
        (x1*y2-y1*x2)*(x3-x4)
        - (x1-x2)*(x3*y4-y3*x4)
    ) / den
    py = (
        (x1*y2-y1*x2)*(y3-y4)
        - (y1-y2)*(x3*y4-y3*x4)
    ) / den
    return px, py


def convex_clip(subject, clipper):
    output = list(subject)
    for i in range(len(clipper)):
        a = clipper[i]
        b = clipper[(i+1) % len(clipper)]
        inp = output
        output = []
        if not inp:
            break
        s = inp[-1]
        for e in inp:
            if inside(e, a, b):
                if not inside(s, a, b):
                    output.append(line_intersection(s, e, a, b))
                output.append(e)
            elif inside(s, a, b):
                output.append(line_intersection(s, e, a, b))
            s = e
    return output


def intersection_sky(poly_a, poly_b):
    center, east, north = tangent_basis([poly_a, poly_b])
    a = ensure_ccw(project_poly(poly_a, center, east, north))
    b = ensure_ccw(project_poly(poly_b, center, east, north))
    clipped = convex_clip(a, b)
    if len(clipped) < 3 or abs(area2(clipped)) < 1e-12:
        raise RuntimeError("Robust-overlap pair produced zero canonical intersection")
    return unproject_poly(clipped, center, east, north)


def wcs_keys(header):
    keys = set()
    if "CTYPE1" in header and "CTYPE2" in header:
        keys.add(" ")
    for name in header:
        m = re.fullmatch(r"CTYPE1([A-Z])", str(name))
        if m and f"CTYPE2{m.group(1)}" in header:
            keys.add(m.group(1))
    return sorted(keys, key=lambda x: (x != " ", x))


def parse_header_text(text):
    text = str(text)
    if "\\n" in text and "\n" not in text:
        text = text.replace("\\n", "\n")
    attempts = []
    for sep in ("\n", ""):
        try:
            header = fits.Header.fromstring(text, sep=sep)
            if len(header):
                return header
        except Exception as exc:
            attempts.append(f"{sep!r}:{type(exc).__name__}")
    raise RuntimeError("Could not parse APPLAUSE header_wcs: " + ",".join(attempts))


def select_wcs_key(header, naxis1, naxis2, target_ra, target_dec):
    ranked = []
    for key in wcs_keys(header):
        try:
            w = WCS(header, key=key).celestial
            cen = w.all_pix2world(
                np.array([[(naxis1-1)/2.0, (naxis2-1)/2.0]], dtype=float),
                0,
            )[0]
            sep = angular_sep_deg(
                target_ra, target_dec,
                float(cen[0]) % 360.0, float(cen[1]),
            )
            ranked.append((sep, key, w, float(cen[0]) % 360.0, float(cen[1])))
        except Exception:
            pass
    if not ranked:
        raise RuntimeError("No usable WCS in header")
    ranked.sort(key=lambda x: (x[0], x[1]))
    best = ranked[0]
    if best[0] > 1.0:
        raise RuntimeError(
            f"Best WCS center is {best[0]:.3f} deg from selected solution center"
        )
    return best


def canonical_candidate(geometry):
    candidates = geometry.get("candidates") or []
    if not candidates:
        raise RuntimeError("Endpoint geometry has no candidate solutions")
    return min(
        candidates,
        key=lambda x: (
            float(x.get("center_sep_from_exposure_deg", math.inf)),
            int(x.get("scan_id") or 0),
            str(x.get("wcs_key") or ""),
            int(x.get("solution_num") or 0),
            int(x.get("solution_id") or 0),
        ),
    )


def applause_physical_key_to_ids(value):
    m = re.fullmatch(r"APPLAUSE:(\d+):(\d+)", str(value).strip())
    if not m:
        raise RuntimeError(f"Invalid APPLAUSE physical key {value!r}")
    return int(m.group(1)), int(m.group(2))


def dasch_package(plate):
    path = V052_CACHE / "dasch" / f"{plate}.json"
    if not path.is_file():
        raise RuntimeError(f"Missing v052 DASCH package cache: {path}")
    return load_json(path, {})


def dasch_wcs_for_candidate(plate, candidate):
    pkg = dasch_package(plate)
    meta = pkg.get("metadata") or {}
    astrom = meta.get("astrometry") or {}
    mosaic = meta.get("mosaic") or {}
    raw = astrom.get("b01HeaderGz")
    if not raw:
        raise RuntimeError(f"DASCH {plate}: missing b01HeaderGz")
    header = fits.Header.fromstring(
        gzip.decompress(base64.b64decode(raw)),
        sep="\n",
    )
    keyname = str(candidate.get("wcs_key") or "PRIMARY")
    key = " " if keyname == "PRIMARY" else keyname
    w = WCS(header, key=key).celestial
    return {
        "wcs": w,
        "naxis1": int(mosaic["b01Width"]),
        "naxis2": int(mosaic["b01Height"]),
        "base_fits_url": str(pkg.get("baseFitsUrl") or ""),
        "base_fits_size": int(pkg.get("baseFitsSize") or 0),
        "wcs_key": keyname,
    }


def bbox_for_polygon(wcs, poly, naxis1, naxis2):
    sky = np.asarray(poly, dtype=float)
    pix = np.asarray(wcs.all_world2pix(sky, 0), dtype=float)
    if pix.shape != (len(poly), 2) or not np.all(np.isfinite(pix)):
        raise RuntimeError("Non-finite footprint-to-pixel transform")
    x0 = max(0, int(math.floor(np.min(pix[:, 0]))) - 2)
    x1 = min(naxis1, int(math.ceil(np.max(pix[:, 0]))) + 3)
    y0 = max(0, int(math.floor(np.min(pix[:, 1]))) - 2)
    y1 = min(naxis2, int(math.ceil(np.max(pix[:, 1]))) + 3)
    if x1 <= x0 or y1 <= y0:
        raise RuntimeError("Empty common-footprint pixel bbox")
    return [x0, x1, y0, y1]


def tile_specs(endpoint_key, bbox, naxis1, naxis2):
    x0, x1, y0, y1 = bbox
    ix0, ix1 = x0 // CORE, (x1 - 1) // CORE
    iy0, iy1 = y0 // CORE, (y1 - 1) // CORE
    out = []
    for iy in range(iy0, iy1 + 1):
        for ix in range(ix0, ix1 + 1):
            cx0 = ix * CORE
            cy0 = iy * CORE
            cx1 = min(naxis1, cx0 + CORE)
            cy1 = min(naxis2, cy0 + CORE)
            ex0 = max(0, cx0 - HALO)
            ex1 = min(naxis1, cx1 + HALO)
            ey0 = max(0, cy0 - HALO)
            ey1 = min(naxis2, cy1 + HALO)
            out.append({
                "endpoint_key": endpoint_key,
                "tile_id": f"x{cx0:05d}-{cx1:05d}_y{cy0:05d}-{cy1:05d}",
                "core_x0": cx0,
                "core_x1": cx1,
                "core_y0": cy0,
                "core_y1": cy1,
                "ext_x0": ex0,
                "ext_x1": ex1,
                "ext_y0": ey0,
                "ext_y1": ey1,
                "extended_pixels": (ex1-ex0)*(ey1-ey0),
            })
    return out


def datalink_cache_path(archive_id, plate_id, scan_id):
    return CACHE / "datalink" / f"{archive_id}_{plate_id}_scan{scan_id}.json"


def resolve_datalink(archive_id, plate_id, filename):
    url = f"{DATALINK_BASE}/{archive_id}_{plate_id}/"
    req = urllib.request.Request(
        url,
        headers={"User-Agent": UA, "Accept": "text/html,*/*"},
    )
    with urllib.request.urlopen(req, timeout=90) as response:
        raw = response.read()
        status = getattr(response, "status", None)
        final_url = response.geturl()

    text = raw.decode("utf-8", errors="replace")
    hrefs = [
        html.unescape(x)
        for x in re.findall(r'href=["\']([^"\']+)["\']', text, re.I)
    ]
    fits_urls = [
        urllib.parse.urljoin(final_url, x)
        for x in hrefs
        if ".fits" in x.lower()
    ]
    exact = [
        x for x in fits_urls
        if Path(urllib.parse.urlsplit(x).path).name.lower() == filename.lower()
    ]
    if len(exact) != 1:
        raise RuntimeError(
            f"Datalink {archive_id}_{plate_id}: expected one FITS URL for "
            f"{filename}, got {len(exact)} from {len(fits_urls)} FITS links"
        )

    fits_url = exact[0]
    head_req = urllib.request.Request(
        fits_url,
        method="HEAD",
        headers={"User-Agent": UA, "Accept": "application/fits,*/*"},
    )
    try:
        with urllib.request.urlopen(head_req, timeout=90) as response:
            headers = {k.lower(): v for k, v in response.headers.items()}
            head_status = getattr(response, "status", None)
            head_final = response.geturl()
    except Exception:
        headers = {}
        head_status = None
        head_final = fits_url

    return {
        "datalink_url": url,
        "datalink_http_status": status,
        "datalink_final_url": final_url,
        "datalink_html_sha256": hashlib.sha256(raw).hexdigest(),
        "fits_url": fits_url,
        "head_http_status": head_status,
        "head_final_url": head_final,
        "head_content_length": inum(headers.get("content-length")),
        "head_accept_ranges": str(headers.get("accept-ranges", "")),
        "head_etag": str(headers.get("etag", "")),
        "head_last_modified": str(headers.get("last-modified", "")),
    }


def main():
    print("=" * 132)
    print("WIDE CENSUS — HEAVY DETECTOR RUN METADATA/CAPACITY PREFLIGHT v054")
    print("=" * 132)
    print("NETWORK METADATA ONLY. NO SCIENCE PIXELS. NO DETECTOR. NO CANDIDATE STATE MUTATION.\n")

    for path in (FOOT, DET_PLAN, DET_QUEUE, POLICY, NATIVE_POLICY, DETECTOR, METHOD):
        if not path.is_file():
            raise RuntimeError(f"REFUSING: missing input {path}")

    if sha(DETECTOR) != EXPECTED_DETECTOR_SHA:
        raise RuntimeError("REFUSING: frozen detector SHA changed")
    if sha(METHOD) != EXPECTED_METHOD_SHA:
        raise RuntimeError("REFUSING: frozen method SHA changed")

    policy = load_json(POLICY, {})
    if policy.get("policy_id") != EXPECTED_POLICY_ID:
        raise RuntimeError("REFUSING: candidate adjudication policy changed")

    dplan = load_json(DET_PLAN, {})
    if dplan.get("status") != "COMPLETE":
        raise RuntimeError("REFUSING: detector plan incomplete")
    if int(dplan.get("detector_execution_eligible_count", -1)) != EXPECTED_QUEUE:
        raise RuntimeError("REFUSING: detector opportunity count changed")
    if int(dplan.get("unique_applause_physical_plates_for_detector", -1)) != EXPECTED_APPLAUSE_PLATES:
        raise RuntimeError("REFUSING: APPLAUSE physical-plate count changed")
    if int(dplan.get("unique_dasch_plates_for_detector", -1)) != EXPECTED_DASCH_PLATES:
        raise RuntimeError("REFUSING: DASCH plate count changed")

    qrows = read_csv(DET_QUEUE)
    if len(qrows) != EXPECTED_QUEUE:
        raise RuntimeError(f"REFUSING: expected {EXPECTED_QUEUE} queue rows, got {len(qrows)}")

    foot = load_json(FOOT, {})
    robust = {
        x["canonical_pair"]: x
        for x in foot.get("pairs", [])
        if x.get("classification") == "TRUE_SKY_FOOTPRINT_OVERLAP_ROBUST"
    }
    if len(robust) != EXPECTED_QUEUE:
        raise RuntimeError("REFUSING: robust footprint record count changed")

    endpoint_occurrences = {}
    pair_rows = []

    for q in qrows:
        fp = robust.get(q["canonical_pair"])
        if fp is None:
            raise RuntimeError(f"Missing robust footprint record: {q['canonical_pair']}")

        pair = {
            "canonical_pair": q["canonical_pair"],
            "detector_execution_priority": int(q["detector_execution_priority"]),
            "time_gate": q["time_gate"],
            "physical_overlap_s": fnum(q["physical_overlap_s"]),
        }

        for side in ("a", "b"):
            kind = q[f"kind_{side}"]
            exposure = q[f"exposure_{side}"]
            geom = fp[f"geometry_{side}"]
            cand = canonical_candidate(geom)

            if kind == "APPLAUSE":
                endpoint_key = f"APPLAUSE:{exposure}"
                archive_id, plate_id = applause_physical_key_to_ids(
                    q[f"physical_plate_key_{side}"]
                )
                record = {
                    "endpoint_key": endpoint_key,
                    "kind": kind,
                    "exposure": exposure,
                    "archive": q[f"archive_{side}"],
                    "site": q[f"site_{side}"],
                    "archive_id": archive_id,
                    "plate_id": plate_id,
                    "scan_id": int(cand["scan_id"]),
                    "process_id": int(cand["process_id"]),
                    "solution_id": int(cand["solution_id"]),
                    "solution_num": int(cand["solution_num"]),
                    "solution_ra_deg": float(cand["solution_ra_deg"]),
                    "solution_dec_deg": float(cand["solution_dec_deg"]),
                    "footprint_polygon": cand["polygon"],
                    "solution_center_sep_deg": float(
                        cand["center_sep_from_exposure_deg"]
                    ),
                }
            elif kind == "DASCH":
                plate = str(q[f"dasch_plate_id_{side}"]).strip().lower()
                endpoint_key = f"DASCH:{plate}:exp{int(geom['selected_expnum'])}"
                record = {
                    "endpoint_key": endpoint_key,
                    "kind": kind,
                    "exposure": exposure,
                    "archive": q[f"archive_{side}"],
                    "site": q[f"site_{side}"],
                    "plate_id": plate,
                    "selected_expnum": int(geom["selected_expnum"]),
                    "wcs_key": str(cand["wcs_key"]),
                    "solution_ra_deg": float(cand["center_ra_deg"]),
                    "solution_dec_deg": float(cand["center_dec_deg"]),
                    "footprint_polygon": cand["polygon"],
                    "solution_center_sep_deg": float(
                        cand["center_sep_from_exposure_deg"]
                    ),
                }
            else:
                raise RuntimeError(f"Unsupported detector archive kind {kind!r}")

            endpoint_occurrences.setdefault(endpoint_key, []).append(record)
            pair[f"endpoint_{side}"] = endpoint_key

        pair_rows.append(pair)

    endpoints = {}
    for key, occ in endpoint_occurrences.items():
        first = occ[0]
        identity_fields = (
            ("kind", "exposure", "scan_id", "process_id", "solution_id", "solution_num")
            if first["kind"] == "APPLAUSE"
            else ("kind", "exposure", "plate_id", "selected_expnum", "wcs_key")
        )
        signatures = {
            tuple(str(x.get(k, "")) for k in identity_fields)
            for x in occ
        }
        if len(signatures) != 1:
            raise RuntimeError(f"Endpoint geometry identity differs across pairs: {key}")
        endpoints[key] = dict(first)

    applause_eps = [x for x in endpoints.values() if x["kind"] == "APPLAUSE"]
    dasch_eps = [x for x in endpoints.values() if x["kind"] == "DASCH"]
    scan_ids = sorted({int(x["scan_id"]) for x in applause_eps})

    CACHE.mkdir(parents=True, exist_ok=True)
    cp = load_json(CHECKPOINT, checkpoint_default())

    scan_cache = CACHE / "applause_scan_rows.json"
    wcs_cache = CACHE / "applause_solution_set_rows.json"

    if not scan_cache.is_file():
        key = "tap:scan"
        if key in cp["terminal"]:
            raise RuntimeError("APPLAUSE scan TAP query reached terminal failure")
        try:
            ids = ",".join(str(x) for x in scan_ids)
            rows, meta = tap_query(
                "SELECT scan_id,plate_id,archive_id,filename_scan,naxis1,naxis2,"
                "file_size,fits_checksum,fits_datasum "
                f"FROM applause_dr4.scan WHERE scan_id IN ({ids}) ORDER BY scan_id"
            )
            write_json(scan_cache, {"meta": meta, "rows": rows})
            print(f"APPLAUSE scan metadata: {len(rows)} rows")
        except Exception as exc:
            n = mark_failure(cp, key, exc)
            print(
                f"APPLAUSE scan TAP retry {n}/{MAX_TRANSPORT_ATTEMPTS}: "
                f"{type(exc).__name__}: {exc}"
            )
            return 10

    if not wcs_cache.is_file():
        key = "tap:solution_set"
        if key in cp["terminal"]:
            raise RuntimeError("APPLAUSE solution_set TAP query reached terminal failure")
        try:
            ids = ",".join(str(x) for x in scan_ids)
            rows, meta = tap_query(
                "SELECT solutionset_id,process_id,scan_id,plate_id,archive_id,"
                "num_solutions,header_wcs "
                f"FROM applause_dr4.solution_set WHERE scan_id IN ({ids}) "
                "ORDER BY scan_id,process_id"
            )
            write_json(wcs_cache, {"meta": meta, "rows": rows})
            print(f"APPLAUSE WCS metadata: {len(rows)} solution-set rows")
        except Exception as exc:
            n = mark_failure(cp, key, exc)
            print(
                f"APPLAUSE WCS TAP retry {n}/{MAX_TRANSPORT_ATTEMPTS}: "
                f"{type(exc).__name__}: {exc}"
            )
            return 10

    scan_rows = load_json(scan_cache, {})["rows"]
    wcs_rows = load_json(wcs_cache, {})["rows"]

    scan_by_id = {}
    for row in scan_rows:
        sid = inum(row.get("scan_id"))
        if sid is not None:
            scan_by_id.setdefault(sid, []).append(row)

    wcs_by_scan = {}
    for row in wcs_rows:
        sid = inum(row.get("scan_id"))
        if sid is not None:
            wcs_by_scan.setdefault(sid, []).append(row)

    for ep in applause_eps:
        sid = int(ep["scan_id"])
        scans = scan_by_id.get(sid, [])
        if len(scans) != 1:
            raise RuntimeError(
                f"APPLAUSE scan_id {sid}: expected one scan row, got {len(scans)}"
            )

        sr = scans[0]
        ep["filename_scan"] = str(sr["filename_scan"]).strip()
        ep["naxis1"] = int(float(sr["naxis1"]))
        ep["naxis2"] = int(float(sr["naxis2"]))
        ep["file_size"] = int(float(sr["file_size"]))
        ep["fits_checksum"] = str(sr.get("fits_checksum", ""))
        ep["fits_datasum"] = str(sr.get("fits_datasum", ""))

        sets = [
            x for x in wcs_by_scan.get(sid, [])
            if inum(x.get("process_id")) == int(ep["process_id"])
        ]
        if not sets:
            allsets = wcs_by_scan.get(sid, [])
            if len(allsets) == 1:
                sets = allsets

        if len(sets) != 1:
            raise RuntimeError(
                f"APPLAUSE endpoint {ep['endpoint_key']}: expected one matching "
                f"solution_set, got {len(sets)}"
            )

        header = parse_header_text(sets[0]["header_wcs"])
        sep, key, wcs, cra, cdec = select_wcs_key(
            header,
            ep["naxis1"],
            ep["naxis2"],
            ep["solution_ra_deg"],
            ep["solution_dec_deg"],
        )
        ep["wcs_key"] = "PRIMARY" if key == " " else key
        ep["wcs_center_match_sep_deg"] = sep
        ep["_wcs"] = wcs

    for ep in dasch_eps:
        info = dasch_wcs_for_candidate(ep["plate_id"], ep)
        ep["naxis1"] = info["naxis1"]
        ep["naxis2"] = info["naxis2"]
        ep["file_size"] = info["base_fits_size"]
        ep["fits_url"] = info["base_fits_url"]
        ep["_wcs"] = info["wcs"]

    pending_links = []
    for ep in applause_eps:
        cpath = datalink_cache_path(
            ep["archive_id"], ep["plate_id"], ep["scan_id"]
        )
        if cpath.is_file():
            ep.update(load_json(cpath, {}))
        else:
            pending_links.append(ep)

    for ep in pending_links[:DATALINK_BATCH]:
        cpath = datalink_cache_path(
            ep["archive_id"], ep["plate_id"], ep["scan_id"]
        )
        key = f"datalink:{ep['archive_id']}:{ep['plate_id']}:scan{ep['scan_id']}"

        if key in cp["terminal"]:
            write_json(cpath, {
                "status": "UNRESOLVED_DATALINK",
                "transport": cp["terminal"][key],
            })
            continue

        try:
            rec = resolve_datalink(
                ep["archive_id"],
                ep["plate_id"],
                ep["filename_scan"],
            )
            rec["status"] = "RESOLVED"
            write_json(cpath, rec)
            ep.update(rec)
            print(
                f"APPLAUSE datalink {ep['archive_id']}:{ep['plate_id']} "
                f"scan={ep['scan_id']} -> {ep['filename_scan']}"
            )
        except Exception as exc:
            n = mark_failure(cp, key, exc)
            print(
                f"APPLAUSE datalink retry {n}/{MAX_TRANSPORT_ATTEMPTS} "
                f"{ep['archive_id']}:{ep['plate_id']} scan={ep['scan_id']}: "
                f"{type(exc).__name__}: {exc}"
            )

    link_done = sum(
        datalink_cache_path(
            ep["archive_id"], ep["plate_id"], ep["scan_id"]
        ).is_file()
        for ep in applause_eps
    )

    cp.update({
        "status": "IN_PROGRESS",
        "applause_endpoint_count": len(applause_eps),
        "dasch_endpoint_count": len(dasch_eps),
        "applause_datalink_done": link_done,
        "applause_datalink_total": len(applause_eps),
    })
    write_json(CHECKPOINT, cp)

    if link_done < len(applause_eps):
        print(
            f"\nCHECKPOINT: APPLAUSE datalinks {link_done}/{len(applause_eps)}"
        )
        print("RETURN 10: checkpointed IN_PROGRESS")
        return 10

    unresolved_links = []
    for ep in applause_eps:
        rec = load_json(
            datalink_cache_path(
                ep["archive_id"], ep["plate_id"], ep["scan_id"]
            ),
            {},
        )
        ep.update(rec)
        if rec.get("status") != "RESOLVED":
            unresolved_links.append(ep["endpoint_key"])

    if unresolved_links:
        raise RuntimeError(
            "REFUSING: detector-ready endpoint has unresolved APPLAUSE FITS link(s): "
            + ", ".join(unresolved_links)
        )

    tile_map = {}
    pair_plans = []

    for pair in pair_rows:
        ea = endpoints[pair["endpoint_a"]]
        eb = endpoints[pair["endpoint_b"]]

        common = intersection_sky(
            ea["footprint_polygon"],
            eb["footprint_polygon"],
        )

        bbox_a = bbox_for_polygon(
            ea["_wcs"], common, ea["naxis1"], ea["naxis2"]
        )
        bbox_b = bbox_for_polygon(
            eb["_wcs"], common, eb["naxis1"], eb["naxis2"]
        )

        pair_rec = dict(pair)
        pair_rec["common_polygon_icrs_deg"] = common
        pair_rec["endpoint_a_bbox"] = bbox_a
        pair_rec["endpoint_b_bbox"] = bbox_b
        pair_plans.append(pair_rec)

        for ep, bbox in ((ea, bbox_a), (eb, bbox_b)):
            for tile in tile_specs(
                ep["endpoint_key"],
                bbox,
                ep["naxis1"],
                ep["naxis2"],
            ):
                tile_map[(tile["endpoint_key"], tile["tile_id"])] = tile

    tiles = sorted(
        tile_map.values(),
        key=lambda x: (x["endpoint_key"], x["tile_id"]),
    )

    for tile in tiles:
        ep = endpoints[tile["endpoint_key"]]
        tile["kind"] = ep["kind"]
        tile["exposure"] = ep["exposure"]
        tile["naxis1"] = ep["naxis1"]
        tile["naxis2"] = ep["naxis2"]
        tile["wcs_key"] = ep.get("wcs_key", "")
        tile["fits_url"] = ep["fits_url"]
        tile["source_file_size"] = ep["file_size"]

    applause_file_upper = sum({
        ep["fits_url"]: int(ep["file_size"])
        for ep in applause_eps
    }.values())

    dasch_file_upper = sum({
        ep["fits_url"]: int(ep["file_size"])
        for ep in dasch_eps
    }.values())

    extended_pixels = sum(int(x["extended_pixels"]) for x in tiles)
    estimated_local_tile_bytes = extended_pixels * 4

    max_remote = max(
        [int(ep["file_size"]) for ep in endpoints.values()] or [0]
    )
    streaming_working_floor = max(
        10 * 1024**3,
        int(estimated_local_tile_bytes * 2.5) + 2 * max_remote,
    )
    disk = shutil.disk_usage(ROOT)

    endpoint_rows = []
    for ep in sorted(endpoints.values(), key=lambda x: x["endpoint_key"]):
        row = {k: v for k, v in ep.items() if not k.startswith("_")}
        endpoint_rows.append(row)

    efields = [
        "endpoint_key", "kind", "exposure", "archive", "site",
        "archive_id", "plate_id", "scan_id", "process_id",
        "solution_id", "solution_num", "selected_expnum",
        "filename_scan", "naxis1", "naxis2", "file_size",
        "wcs_key", "wcs_center_match_sep_deg",
        "fits_url", "head_http_status", "head_content_length",
        "head_accept_ranges", "fits_checksum", "fits_datasum",
    ]
    tmp = ENDPOINT_CSV.with_suffix(ENDPOINT_CSV.suffix + ".tmp")
    with tmp.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=efields,
            extrasaction="ignore",
        )
        writer.writeheader()
        writer.writerows(endpoint_rows)
    tmp.replace(ENDPOINT_CSV)

    tfields = [
        "endpoint_key", "kind", "exposure", "tile_id",
        "core_x0", "core_x1", "core_y0", "core_y1",
        "ext_x0", "ext_x1", "ext_y0", "ext_y1",
        "extended_pixels", "naxis1", "naxis2", "wcs_key",
        "fits_url", "source_file_size",
    ]
    tmp = TILE_CSV.with_suffix(TILE_CSV.suffix + ".tmp")
    with tmp.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=tfields,
            extrasaction="ignore",
        )
        writer.writeheader()
        writer.writerows(tiles)
    tmp.replace(TILE_CSV)

    write_json(PAIR_JSON, {
        "status": "COMPLETE",
        "pairs": pair_plans,
    })

    range_yes = sum(
        "bytes" in str(ep.get("head_accept_ranges", "")).lower()
        for ep in applause_eps
    )
    range_unknown = len(applause_eps) - range_yes

    payload = {
        "status": "COMPLETE",
        "analysis_kind": "wide_census_heavy_preflight_v054",
        "guards": {
            "network_access": True,
            "science_pixels_read": False,
            "non_science_pixels_read": False,
            "transient_detector_rerun": False,
            "candidate_state_mutation": False,
        },
        "input_sha256": {
            "footprint_v052": sha(FOOT),
            "detector_plan_v053": sha(DET_PLAN),
            "detector_queue_v053": sha(DET_QUEUE),
            "candidate_policy": sha(POLICY),
            "native_tile_policy": sha(NATIVE_POLICY),
            "detector": sha(DETECTOR),
            "method": sha(METHOD),
        },
        "opportunity_count": len(pair_plans),
        "endpoint_count": len(endpoints),
        "applause_endpoint_count": len(applause_eps),
        "dasch_endpoint_count": len(dasch_eps),
        "unique_tile_count": len(tiles),
        "core_px": CORE,
        "halo_px": HALO,
        "applause_full_file_upper_bound_bytes": applause_file_upper,
        "dasch_full_file_upper_bound_bytes": dasch_file_upper,
        "all_remote_full_file_upper_bound_bytes": (
            applause_file_upper + dasch_file_upper
        ),
        "estimated_local_tile_bytes_conservative": estimated_local_tile_bytes,
        "streaming_working_free_space_floor_bytes": streaming_working_floor,
        "free_disk_bytes": disk.free,
        "capacity_pass": disk.free >= streaming_working_floor,
        "applause_http_range_confirmed_endpoints": range_yes,
        "applause_http_range_unknown_endpoints": range_unknown,
        "endpoint_plan_csv": str(
            ENDPOINT_CSV.relative_to(ROOT)
        ).replace("\\", "/"),
        "pair_plan_json": str(
            PAIR_JSON.relative_to(ROOT)
        ).replace("\\", "/"),
        "tile_plan_csv": str(
            TILE_CSV.relative_to(ROOT)
        ).replace("\\", "/"),
        "selection_policy": {
            "applause_scan_solution": (
                "Before detector pixels, choose the v052 candidate with minimum "
                "exposure-center separation, then scan_id, solution_num, solution_id."
            ),
            "applause_wcs": (
                "Within the selected scan/process solution_set, choose the FITS WCS "
                "whose image center is nearest the already-selected v052 solution center."
            ),
            "dasch_wcs": (
                "Use the canonical v052 WCS candidate for the selected logbook exposure."
            ),
            "tile_grid": (
                "1024-pixel zero-anchored cores with 64-pixel halo, matching frozen native policy."
            ),
            "pair_mask": (
                "Detector peaks are later retained for a pair only inside that pair's exact common polygon."
            ),
        },
        "interpretation_boundary": (
            "This stage freezes acquisition identities, WCS choices and tile workload "
            "before heavy detector execution. It reads metadata only. The 41 v052 "
            "geometry holds remain a separate unresolved census branch and are not "
            "converted into negatives."
        ),
        "next_stage": (
            "If capacity_pass is true, execute the resumable frozen detector over "
            "the v054 endpoint tile plan, then pairwise common-polygon crossmatch."
        ),
    }
    write_json(OUT_JSON, payload)

    cp.update({
        "status": "COMPLETE",
        "unique_tile_count": len(tiles),
        "capacity_pass": disk.free >= streaming_working_floor,
    })
    write_json(CHECKPOINT, cp)

    print("\n" + "=" * 132)
    print("HEAVY RUN PREFLIGHT COMPLETE")
    print("=" * 132)
    print(f"Opportunities: {len(pair_plans)}")
    print(f"Unique detector endpoints: {len(endpoints)}")
    print(f"  APPLAUSE endpoints: {len(applause_eps)}")
    print(f"  DASCH endpoints: {len(dasch_eps)}")
    print(f"Unique 1024-core tiles: {len(tiles)}")
    print(
        "Full-file network upper bound: "
        f"{(applause_file_upper + dasch_file_upper) / 1024**3:.2f} GiB"
    )
    print(
        "Conservative local tile output estimate: "
        f"{estimated_local_tile_bytes / 1024**3:.2f} GiB"
    )
    print(
        f"Free disk: {disk.free / 1024**3:.2f} GiB; "
        f"required streaming floor: {streaming_working_floor / 1024**3:.2f} GiB"
    )
    print(
        f"CAPACITY: {'PASS' if disk.free >= streaming_working_floor else 'FAIL'}"
    )
    print(
        f"APPLAUSE HTTP byte-range confirmed: {range_yes}/{len(applause_eps)} "
        f"(unknown/no-header: {range_unknown})"
    )
    print("SCIENCE PIXELS READ: 0")
    print("DETECTOR RUNS: 0")
    print(f"Report: {OUT_JSON}")
    print("\nSTAGE STATUS: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
