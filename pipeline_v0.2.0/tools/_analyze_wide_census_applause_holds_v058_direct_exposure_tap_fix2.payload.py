from __future__ import annotations

from pathlib import Path
from io import BytesIO
from datetime import datetime, timezone
import csv
import hashlib
import json
import math
import re
import time
import urllib.parse
import urllib.request
import warnings

import numpy as np
from astropy.io import fits
from astropy.table import Table
from astropy.wcs import WCS
from astropy.coordinates import SkyCoord
import astropy.units as u
from astropy.wcs import FITSFixedWarning

ROOT = Path.cwd()

HOLD_CSV = (
    ROOT / "results" / "wide_census_geometry_hold_inventory_v057"
    / "wide_census_geometry_hold_inventory_v057.csv"
)
HOLD_JSON = (
    ROOT / "results" / "wide_census_geometry_hold_inventory_v057"
    / "wide_census_geometry_hold_inventory_v057.json"
)
V052 = ROOT / "results" / "wide_census_exact_footprint_v052.json"
OUTDIR = ROOT / "results" / "wide_census_applause_hold_metadata_v058"
CACHE = OUTDIR / "cache"

EXPOSURE_RAW_VOTABLE = CACHE / "applause_exposure_unresolved_v058.xml"
EXPOSURE_QUERY_FILE = CACHE / "applause_exposure_unresolved_v058.adql"
EXPOSURE_QUERY_META = CACHE / "applause_exposure_unresolved_v058.meta.json"

RAW_VOTABLE = CACHE / "applause_solution_scan_unresolved_v058.xml"
QUERY_FILE = CACHE / "applause_solution_scan_unresolved_v058.adql"
QUERY_META = CACHE / "applause_solution_scan_unresolved_v058.meta.json"

OUT_JSON = OUTDIR / "wide_census_applause_hold_metadata_v058.json"
OUT_ENDPOINTS = OUTDIR / "wide_census_applause_hold_endpoint_inventory_v058.csv"
OUT_SOLUTIONS = OUTDIR / "wide_census_applause_hold_solution_inventory_v058.csv"
OUT_QUERY_ROWS = OUTDIR / "wide_census_applause_solution_scan_rows_v058.csv"

TAP_SYNC = "https://www.plate-archive.org/tap/sync"
UA = "historical-transient-pipeline/0.2.0-wide-census-v058"
TIMEOUT = 180
MAX_ATTEMPTS = 5

EXPECTED_HOLD_COUNT = 41
EXPECTED_APPLAUSE_NO_POLYGON = 34
EXPECTED_APPLAUSE_ASSOC = 1

UNRESOLVED_APPLAUSE = {
    "UNRESOLVED_APPLAUSE_NO_EXACT_POLYGON",
    "UNRESOLVED_APPLAUSE_SOLUTION_EXPOSURE_ASSOCIATION",
}

FLOAT_RE = re.compile(
    r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?"
)


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def sha_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def read_csv(path: Path):
    with path.open(newline="", encoding="utf-8-sig") as fh:
        return list(csv.DictReader(fh))


def write_csv(path: Path, rows, fields):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    tmp.replace(path)


def write_json(path: Path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(obj, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )
    tmp.replace(path)


def fnum(v):
    s = "" if v is None else str(v).strip()
    if not s or s.lower() in {"none", "null", "nan", "--"}:
        return None
    try:
        x = float(s)
    except Exception:
        return None
    return x if math.isfinite(x) else None


def inum(v):
    x = fnum(v)
    return None if x is None else int(x)


def endpoint_exposure_id(endpoint: str):
    s = str(endpoint).strip()
    if not s.startswith("APPLAUSE:"):
        return None
    try:
        return int(s.split(":", 1)[1])
    except Exception:
        return None


def table_row_dicts(tbl: Table):
    rows = []
    for tr in tbl:
        d = {}
        for name in tbl.colnames:
            v = tr[name]
            if np.ma.is_masked(v):
                d[name] = ""
            else:
                if isinstance(v, bytes):
                    v = v.decode("utf-8", errors="replace")
                elif isinstance(v, np.generic):
                    v = v.item()
                d[name] = v
        rows.append(d)
    return rows


def make_exposure_query(exposure_ids):
    ids = ",".join(str(int(x)) for x in sorted(set(exposure_ids)))
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
  AND e.exposure_id IN ({ids})
ORDER BY e.exposure_id
"""


def make_query(plate_ids):
    ids = ",".join(str(int(x)) for x in sorted(set(plate_ids)))
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
  AND s.plate_id IN ({ids})
ORDER BY s.plate_id, s.scan_id, s.solution_num, s.solution_id
"""


def tap_query(
    q: str,
    *,
    query_file: Path = QUERY_FILE,
    raw_votable: Path = RAW_VOTABLE,
    query_meta: Path = QUERY_META,
):
    CACHE.mkdir(parents=True, exist_ok=True)
    qhash = sha_bytes(q.encode("utf-8"))

    if query_file.is_file() and raw_votable.is_file() and query_meta.is_file():
        old_q = query_file.read_text(encoding="utf-8")
        meta = json.loads(query_meta.read_text(encoding="utf-8"))
        raw = raw_votable.read_bytes()
        if (
            old_q == q
            and meta.get("query_sha256") == qhash
            and meta.get("response_sha256") == sha_bytes(raw)
        ):
            tbl = Table.read(BytesIO(raw), format="votable")
            return table_row_dicts(tbl), {**meta, "cached": True}

    payload = urllib.parse.urlencode({
        "REQUEST": "doQuery",
        "LANG": "ADQL",
        "FORMAT": "votable",
        "QUERY": q,
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

            tbl = Table.read(BytesIO(raw), format="votable")
            rows = table_row_dicts(tbl)

            query_file.write_text(q, encoding="utf-8", newline="\n")
            raw_votable.write_bytes(raw)
            meta = {
                "complete": True,
                "query_sha256": qhash,
                "response_sha256": sha_bytes(raw),
                "row_count": len(rows),
                "http_status": status,
                "content_type": ctype,
                "final_url": final_url,
                "attempt": attempt,
                "cached": False,
                "queried_at_utc": datetime.now(timezone.utc).isoformat(),
            }
            write_json(query_meta, meta)
            return rows, meta
        except Exception as exc:
            last = exc
            if attempt < MAX_ATTEMPTS:
                time.sleep(min(20.0, 2.0 ** attempt))
    raise RuntimeError(
        f"APPLAUSE TAP query failed after {MAX_ATTEMPTS} attempts: "
        f"{type(last).__name__}: {last}"
    ) from last


def parse_stc_polygon(text):
    s = "" if text is None else str(text).strip()
    if not s:
        return None
    vals = [float(x) for x in FLOAT_RE.findall(s)]
    if len(vals) < 8:
        return None
    vals = vals[:8]
    pts = [[vals[i] % 360.0, vals[i + 1]] for i in range(0, 8, 2)]
    if any(not (-90 <= d <= 90) for _, d in pts):
        return None
    return pts


def parse_header(text):
    s = "" if text is None else str(text)
    if not s.strip():
        return None
    candidates = []
    for sep in ("\n", ""):
        try:
            h = fits.Header.fromstring(s, sep=sep)
            candidates.append(h)
        except Exception:
            pass
    for h in candidates:
        try:
            w = WCS(h, relax=True).celestial
            if w.has_celestial:
                return h, w
        except Exception:
            continue
    return None


def polygon_from_header_wcs(row):
    nx = inum(row.get("naxis1"))
    ny = inum(row.get("naxis2"))
    if not nx or not ny or nx <= 1 or ny <= 1:
        return None, "INVALID_SCAN_DIMENSIONS"

    parsed = parse_header(row.get("header_wcs"))
    if parsed is None:
        return None, "NO_USABLE_CELESTIAL_HEADER_WCS"
    h, w = parsed

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", FITSFixedWarning)
            fp = w.calc_footprint(axes=(nx, ny), center=False)
        if fp is None or np.asarray(fp).shape != (4, 2):
            return None, "WCS_CALC_FOOTPRINT_BAD_SHAPE"
        pts = [
            [float(ra) % 360.0, float(dec)]
            for ra, dec in np.asarray(fp, dtype=float)
        ]
        if any(not (math.isfinite(ra) and math.isfinite(dec)) for ra, dec in pts):
            return None, "WCS_CALC_FOOTPRINT_NONFINITE"
        return pts, "OFFICIAL_HEADER_WCS_PLUS_SCAN_DIMENSIONS"
    except Exception as exc:
        return None, f"WCS_CALC_FOOTPRINT_ERROR:{type(exc).__name__}:{exc}"


def best_vertex_agreement_arcsec(a, b):
    """Compare 4-corner polygons allowing cyclic start and reversal."""
    if not a or not b or len(a) != 4 or len(b) != 4:
        return None
    aa = [SkyCoord(ra * u.deg, dec * u.deg) for ra, dec in a]
    variants = []
    for reverse in (False, True):
        seq = list(reversed(b)) if reverse else list(b)
        for k in range(4):
            variants.append(seq[k:] + seq[:k])
    best = None
    for bb in variants:
        vals = [
            float(aa[i].separation(
                SkyCoord(bb[i][0] * u.deg, bb[i][1] * u.deg)
            ).arcsec)
            for i in range(4)
        ]
        score = max(vals)
        if best is None or score < best:
            best = score
    return best


def angular_sep_deg(ra1, dec1, ra2, dec2):
    if None in (ra1, dec1, ra2, dec2):
        return None
    a = SkyCoord(float(ra1) * u.deg, float(dec1) * u.deg)
    b = SkyCoord(float(ra2) * u.deg, float(dec2) * u.deg)
    return float(a.separation(b).deg)


def main():
    print("=" * 132)
    print("WIDE CENSUS — APPLAUSE GEOMETRY-HOLD OFFICIAL METADATA INVENTORY v058 (DIRECT EXPOSURE-TAP FIX 2)")
    print("=" * 132)
    print("NETWORK: APPLAUSE DR4 TAP METADATA ONLY.")
    print("NO SCIENCE PIXELS. NO DETECTOR. NO CANDIDATE STATE MUTATION.")
    print("NO v052 CLASSIFICATION IS CHANGED BY THIS STAGE.\n")

    for p in (HOLD_CSV, HOLD_JSON, V052):
        if not p.is_file():
            raise RuntimeError(f"REFUSING: missing prerequisite {p}")

    hold_meta = json.loads(HOLD_JSON.read_text(encoding="utf-8"))
    if int(hold_meta.get("hold_count", -1)) != EXPECTED_HOLD_COUNT:
        raise RuntimeError("REFUSING: v057 hold count changed")

    hold_rows = read_csv(HOLD_CSV)
    if len(hold_rows) != EXPECTED_HOLD_COUNT:
        raise RuntimeError(f"REFUSING: expected 41 hold rows, got {len(hold_rows)}")

    unresolved = []
    status_counts = {}
    for row in hold_rows:
        for side in ("a", "b"):
            status = row.get(f"geometry_{side}_status", "")
            endpoint = row.get(f"exposure_{side}", "")
            archive = row.get(f"archive_{side}", "")
            if status in UNRESOLVED_APPLAUSE:
                eid = endpoint_exposure_id(endpoint)
                if eid is None:
                    raise RuntimeError(
                        f"REFUSING: APPLAUSE unresolved endpoint has unparseable id: {endpoint}"
                    )
                unresolved.append({
                    "canonical_pair": row.get("canonical_pair"),
                    "pair_family": row.get("pair_family"),
                    "time_gate": row.get("time_gate"),
                    "physical_overlap_s": row.get("physical_overlap_s"),
                    "side": side,
                    "endpoint": endpoint,
                    "exposure_id": eid,
                    "archive": archive,
                    "v052_geometry_status": status,
                })
                status_counts[status] = status_counts.get(status, 0) + 1

    if status_counts.get("UNRESOLVED_APPLAUSE_NO_EXACT_POLYGON", 0) != EXPECTED_APPLAUSE_NO_POLYGON:
        raise RuntimeError("REFUSING: APPLAUSE no-polygon hold count changed")
    if status_counts.get("UNRESOLVED_APPLAUSE_SOLUTION_EXPOSURE_ASSOCIATION", 0) != EXPECTED_APPLAUSE_ASSOC:
        raise RuntimeError("REFUSING: APPLAUSE association hold count changed")

    unique_exposure_ids = sorted({x["exposure_id"] for x in unresolved})
    print(f"Unresolved APPLAUSE endpoint occurrences: {len(unresolved)}")
    print(f"Unique unresolved APPLAUSE exposures:     {len(unique_exposure_ids)}")
    print("Querying exact official applause_dr4.exposure identities ...", flush=True)

    exposure_q = make_exposure_query(unique_exposure_ids)
    exprows, exposure_qmeta = tap_query(
        exposure_q,
        query_file=EXPOSURE_QUERY_FILE,
        raw_votable=EXPOSURE_RAW_VOTABLE,
        query_meta=EXPOSURE_QUERY_META,
    )
    print(f"Official exposure rows returned:           {len(exprows)}")

    by_eid = {}
    for r in exprows:
        eid = inum(r.get("exposure_id"))
        if eid is not None:
            by_eid.setdefault(eid, []).append(r)

    returned_eids = set(by_eid)
    requested_eids = set(unique_exposure_ids)
    if returned_eids != requested_eids:
        raise RuntimeError(
            "REFUSING: official APPLAUSE exposure identity query did not return "
            f"exact requested set; missing={sorted(requested_eids-returned_eids)} "
            f"unexpected={sorted(returned_eids-requested_eids)}"
        )

    endpoint_records = []
    plate_ids = []
    for item in unresolved:
        matches = by_eid.get(item["exposure_id"], [])
        if len(matches) != 1:
            raise RuntimeError(
                f"REFUSING: official APPLAUSE exposure {item['exposure_id']} "
                f"returned {len(matches)} rows; expected exactly one"
            )
        r = matches[0]
        plate_id = inum(r.get("plate_id"))
        archive_id = inum(r.get("archive_id"))
        if plate_id is None or archive_id is None:
            raise RuntimeError(
                f"REFUSING: APPLAUSE exposure {item['exposure_id']} lacks "
                "official plate/archive id"
            )
        item = {
            **item,
            "plate_id": plate_id,
            "archive_id": archive_id,
            "exposure_ra_icrs": fnum(r.get("ra_icrs")),
            "exposure_dec_icrs": fnum(r.get("dec_icrs")),
            "obs_start_utc": str(r.get("ut_start") or ""),
            "obs_end_utc": str(r.get("ut_end") or ""),
            "archive_name": str(r.get("archive_name") or ""),
            "institute": str(r.get("institute") or ""),
            "exposure_identity_source": "OFFICIAL_APPLAUSE_DR4_EXPOSURE_TAP",
        }
        endpoint_records.append(item)
        plate_ids.append(plate_id)

    print(f"Unique physical APPLAUSE plates:          {len(set(plate_ids))}")
    print("Querying official applause_dr4.solution + applause_dr4.scan ...", flush=True)

    q = make_query(plate_ids)
    query_rows, qmeta = tap_query(q)
    print(f"Official solution/scan rows returned:      {len(query_rows)}")

    # Preserve complete returned table in a compact CSV, including header_wcs.
    query_fields = [
        "solution_id", "process_id", "solutionset_id", "scan_id", "plate_id",
        "archive_id", "solution_num", "ra_icrs", "dec_icrs", "fov1", "fov2",
        "pixel_scale", "stc_polygon", "header_wcs", "filename_scan",
        "naxis1", "naxis2", "file_size", "fits_checksum",
    ]
    write_csv(OUT_QUERY_ROWS, query_rows, query_fields)

    by_plate_archive = {}
    for r in query_rows:
        key = (inum(r.get("plate_id")), inum(r.get("archive_id")))
        by_plate_archive.setdefault(key, []).append(r)

    solution_inventory = []
    endpoint_summary = []
    official_vs_header_agreements = []

    for item in endpoint_records:
        candidates = list(
            by_plate_archive.get((item["plate_id"], item["archive_id"]), [])
        )

        # Never select by outcome; preserve every solution row and sort only by
        # deterministic metadata proximity to the exposure's catalogue center.
        enriched = []
        for r in candidates:
            sra = fnum(r.get("ra_icrs"))
            sdec = fnum(r.get("dec_icrs"))
            sep = angular_sep_deg(
                item["exposure_ra_icrs"], item["exposure_dec_icrs"], sra, sdec
            )
            official_poly = parse_stc_polygon(r.get("stc_polygon"))
            header_poly, header_state = polygon_from_header_wcs(r)

            if official_poly is not None:
                adopted_poly = official_poly
                provenance = "OFFICIAL_STC_POLYGON"
            elif header_poly is not None:
                adopted_poly = header_poly
                provenance = "OFFICIAL_HEADER_WCS_PLUS_SCAN_DIMENSIONS"
            else:
                adopted_poly = None
                provenance = "NO_USABLE_EXACT_POLYGON"

            agreement = (
                best_vertex_agreement_arcsec(official_poly, header_poly)
                if official_poly is not None and header_poly is not None
                else None
            )
            if agreement is not None:
                official_vs_header_agreements.append(agreement)

            er = {
                "endpoint": item["endpoint"],
                "exposure_id": item["exposure_id"],
                "plate_id": item["plate_id"],
                "archive_id": item["archive_id"],
                "v052_geometry_status": item["v052_geometry_status"],
                "exposure_ra_icrs": item["exposure_ra_icrs"],
                "exposure_dec_icrs": item["exposure_dec_icrs"],
                "solution_id": inum(r.get("solution_id")),
                "process_id": inum(r.get("process_id")),
                "solutionset_id": inum(r.get("solutionset_id")),
                "scan_id": inum(r.get("scan_id")),
                "solution_num": inum(r.get("solution_num")),
                "solution_ra_icrs": sra,
                "solution_dec_icrs": sdec,
                "exposure_center_sep_deg": sep,
                "filename_scan": str(r.get("filename_scan") or ""),
                "naxis1": inum(r.get("naxis1")),
                "naxis2": inum(r.get("naxis2")),
                "file_size": inum(r.get("file_size")),
                "fits_checksum": str(r.get("fits_checksum") or ""),
                "official_stc_polygon_present": official_poly is not None,
                "header_wcs_present": bool(str(r.get("header_wcs") or "").strip()),
                "header_wcs_footprint_state": header_state,
                "exact_polygon_provenance": provenance,
                "exact_polygon_icrs_deg": json.dumps(adopted_poly) if adopted_poly else "",
                "official_vs_header_max_corner_sep_arcsec": agreement,
            }
            enriched.append(er)
            solution_inventory.append(er)

        enriched.sort(key=lambda x: (
            float("inf") if x["exposure_center_sep_deg"] is None else x["exposure_center_sep_deg"],
            x["scan_id"] if x["scan_id"] is not None else 10**18,
            x["solution_num"] if x["solution_num"] is not None else 10**9,
            x["solution_id"] if x["solution_id"] is not None else 10**18,
        ))

        polygonable = [x for x in enriched if x["exact_polygon_provenance"] != "NO_USABLE_EXACT_POLYGON"]
        direct = [x for x in polygonable if x["exact_polygon_provenance"] == "OFFICIAL_STC_POLYGON"]
        derived = [x for x in polygonable if x["exact_polygon_provenance"] == "OFFICIAL_HEADER_WCS_PLUS_SCAN_DIMENSIONS"]

        if not enriched:
            state = "NO_OFFICIAL_SOLUTION_ROWS_FOR_PHYSICAL_PLATE"
        elif not polygonable:
            state = "OFFICIAL_SOLUTIONS_PRESENT_BUT_NO_USABLE_EXACT_FOOTPRINT"
        elif len(polygonable) == 1:
            state = "UNIQUE_POLYGONABLE_OFFICIAL_SOLUTION"
        else:
            state = "MULTIPLE_POLYGONABLE_OFFICIAL_SOLUTIONS_RETAIN_ASSOCIATION_HOLD"

        nearest = enriched[0] if enriched else None
        endpoint_summary.append({
            **item,
            "official_solution_row_count": len(enriched),
            "polygonable_solution_count": len(polygonable),
            "official_stc_polygon_solution_count": len(direct),
            "header_wcs_derived_polygon_solution_count": len(derived),
            "nearest_solution_id_by_exposure_center": None if nearest is None else nearest["solution_id"],
            "nearest_scan_id_by_exposure_center": None if nearest is None else nearest["scan_id"],
            "nearest_solution_num_by_exposure_center": None if nearest is None else nearest["solution_num"],
            "nearest_exposure_center_sep_deg": None if nearest is None else nearest["exposure_center_sep_deg"],
            "v058_metadata_resolution_state": state,
            "v052_classification_changed": False,
        })

    ep_fields = [
        "canonical_pair", "pair_family", "time_gate", "physical_overlap_s",
        "side", "endpoint", "exposure_id", "plate_id", "archive_id",
        "archive_name", "institute", "obs_start_utc", "obs_end_utc",
        "exposure_ra_icrs", "exposure_dec_icrs", "v052_geometry_status",
        "official_solution_row_count", "polygonable_solution_count",
        "official_stc_polygon_solution_count",
        "header_wcs_derived_polygon_solution_count",
        "nearest_solution_id_by_exposure_center",
        "nearest_scan_id_by_exposure_center",
        "nearest_solution_num_by_exposure_center",
        "nearest_exposure_center_sep_deg",
        "v058_metadata_resolution_state", "v052_classification_changed",
    ]
    write_csv(OUT_ENDPOINTS, endpoint_summary, ep_fields)

    sol_fields = [
        "endpoint", "exposure_id", "plate_id", "archive_id",
        "v052_geometry_status", "exposure_ra_icrs", "exposure_dec_icrs",
        "solution_id", "process_id", "solutionset_id", "scan_id",
        "solution_num", "solution_ra_icrs", "solution_dec_icrs",
        "exposure_center_sep_deg", "filename_scan", "naxis1", "naxis2",
        "file_size", "fits_checksum", "official_stc_polygon_present",
        "header_wcs_present", "header_wcs_footprint_state",
        "exact_polygon_provenance", "exact_polygon_icrs_deg",
        "official_vs_header_max_corner_sep_arcsec",
    ]
    write_csv(OUT_SOLUTIONS, solution_inventory, sol_fields)

    state_counts = {}
    for x in endpoint_summary:
        s = x["v058_metadata_resolution_state"]
        state_counts[s] = state_counts.get(s, 0) + 1

    agreements = sorted(official_vs_header_agreements)
    agreement_summary = {
        "comparison_count": len(agreements),
        "min_arcsec": None if not agreements else agreements[0],
        "median_arcsec": None if not agreements else float(np.median(agreements)),
        "p95_arcsec": None if not agreements else float(np.percentile(agreements, 95)),
        "max_arcsec": None if not agreements else agreements[-1],
        "interpretation": (
            "Diagnostic comparison only. No acceptance threshold is chosen from "
            "these values and no v052 classification is changed."
        ),
    }

    payload = {
        "status": "COMPLETE",
        "analysis_kind": "wide_census_applause_hold_metadata_v058",
        "completed_at_utc": datetime.now(timezone.utc).isoformat(),
        "guards": {
            "network_access": True,
            "network_scope": "APPLAUSE DR4 TAP metadata only",
            "science_pixels_read": False,
            "non_science_pixels_read": False,
            "transient_detector_rerun": False,
            "candidate_state_mutation": False,
            "v052_geometry_classification_mutation": False,
            "automation_registry_mutation": False,
        },
        "input_sha256": {
            str(HOLD_CSV.relative_to(ROOT)).replace("\\", "/"): sha(HOLD_CSV),
            str(HOLD_JSON.relative_to(ROOT)).replace("\\", "/"): sha(HOLD_JSON),
            str(V052.relative_to(ROOT)).replace("\\", "/"): sha(V052),
        },
        "scope": {
            "v057_total_hold_pairs": EXPECTED_HOLD_COUNT,
            "applause_no_exact_polygon_endpoint_occurrences": EXPECTED_APPLAUSE_NO_POLYGON,
            "applause_solution_exposure_association_endpoint_occurrences": EXPECTED_APPLAUSE_ASSOC,
            "applause_unresolved_endpoint_occurrences": len(endpoint_records),
            "unique_applause_unresolved_exposures": len({x["exposure_id"] for x in endpoint_records}),
            "unique_applause_physical_plates": len(set(plate_ids)),
        },
        "tap": {
            "endpoint": TAP_SYNC,
            "exposure_identity_query": {
                "query_sha256": sha_bytes(exposure_q.encode("utf-8")),
                "response": exposure_qmeta,
                "requested_unique_exposure_ids": len(unique_exposure_ids),
                "returned_rows": len(exprows),
                "exact_requested_identity_set_returned": True,
            },
            "solution_scan_query": {
                "query_sha256": sha_bytes(q.encode("utf-8")),
                "response": qmeta,
                "returned_solution_scan_rows": len(query_rows),
            },
        },
        "footprint_sources": {
            "primary_when_present": "applause_dr4.solution.stc_polygon",
            "fallback_when_stc_polygon_absent": (
                "applause_dr4.solution.header_wcs + exact applause_dr4.scan "
                "naxis1/naxis2; WCS.calc_footprint(center=False)"
            ),
            "selection_rule": (
                "No solution is selected by v058. Every official solution row is "
                "retained. Exposure-center separation is diagnostic ordering only."
            ),
        },
        "resolution_state_counts": state_counts,
        "official_stc_vs_header_wcs_polygon_diagnostic": agreement_summary,
        "endpoint_summary": endpoint_summary,
        "outputs": {
            "endpoint_inventory_csv": str(OUT_ENDPOINTS.relative_to(ROOT)).replace("\\", "/"),
            "solution_inventory_csv": str(OUT_SOLUTIONS.relative_to(ROOT)).replace("\\", "/"),
            "official_query_rows_csv": str(OUT_QUERY_ROWS.relative_to(ROOT)).replace("\\", "/"),
            "exposure_query_adql": str(EXPOSURE_QUERY_FILE.relative_to(ROOT)).replace("\\", "/"),
            "exposure_raw_votable_cache": str(EXPOSURE_RAW_VOTABLE.relative_to(ROOT)).replace("\\", "/"),
            "solution_query_adql": str(QUERY_FILE.relative_to(ROOT)).replace("\\", "/"),
            "solution_raw_votable_cache": str(RAW_VOTABLE.relative_to(ROOT)).replace("\\", "/"),
        },
        "interpretation_boundary": (
            "v058 is an official-metadata acquisition and geometry reconstruction "
            "inventory only. It does not change the 41 v052 holds. A later, separately "
            "frozen resolver may use these preserved exact solution identities and "
            "polygons to resolve only cases where the exposure-to-solution association "
            "is justified independently of detector outcomes."
        ),
    }
    write_json(OUT_JSON, payload)

    print("\nEndpoint metadata-resolution states:")
    for k, v in sorted(state_counts.items(), key=lambda kv: (-kv[1], kv[0])):
        print(f"  {v:3d}  {k}")

    print("\nOfficial STC vs header-WCS footprint diagnostic:")
    for k, v in agreement_summary.items():
        if k != "interpretation":
            print(f"  {k}: {v}")

    print("\nOutputs:")
    print(" ", OUT_JSON)
    print(" ", OUT_ENDPOINTS)
    print(" ", OUT_SOLUTIONS)
    print(" ", OUT_QUERY_ROWS)
    print("\nNO v052 classification was changed.")
    print("STAGE STATUS: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
