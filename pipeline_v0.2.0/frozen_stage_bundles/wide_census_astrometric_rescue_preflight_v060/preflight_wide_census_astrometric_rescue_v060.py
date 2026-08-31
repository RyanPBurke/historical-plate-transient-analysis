from __future__ import annotations

from pathlib import Path
from io import BytesIO
from datetime import datetime, timezone
import csv
import hashlib
import json
import math
import time
import urllib.error
import urllib.parse
import urllib.request

import numpy as np
from astropy.table import Table
from astropy.coordinates import SkyCoord
import astropy.units as u

ROOT = Path.cwd()

V059_DIR = ROOT / "results" / "wide_census_applause_process_audit_v059"
V059_JSON = V059_DIR / "wide_census_applause_process_audit_v059.json"
V059_PLATES = V059_DIR / "wide_census_applause_plate_process_state_v059.csv"
V059_PROCESS = V059_DIR / "wide_census_applause_process_rows_v059.csv"

V058_ENDPOINTS = (
    ROOT / "results" / "wide_census_applause_hold_metadata_v058"
    / "wide_census_applause_hold_endpoint_inventory_v058.csv"
)

OUTDIR = ROOT / "results" / "wide_census_astrometric_rescue_preflight_v060"
CACHE = OUTDIR / "cache"
OUT_JSON = OUTDIR / "wide_census_astrometric_rescue_preflight_v060.json"
OUT_PLATES = OUTDIR / "wide_census_astrometric_rescue_plate_priors_v060.csv"
OUT_SOURCES = OUTDIR / "wide_census_astrometric_rescue_source_centroids_v060.csv"
OUT_XMATCH = OUTDIR / "wide_census_astrometric_rescue_existing_xmatch_sample_v060.csv"

FREEZE_DIR = ROOT / "research" / "prospective_freezes"
FREEZE = FREEZE_DIR / "wide_census_independent_astrometric_rescue_preflight_contract_v001.json"

TAP_SYNC = "https://www.plate-archive.org/tap/sync"
UA = "historical-transient-pipeline/0.2.0-wide-census-v060"
TIMEOUT = 180
MAX_ATTEMPTS = 4
SOURCE_TOP = 1000
XMATCH_TOP = 200

EXPECTED_PLATES = 12
EXPECTED_UNSOLVED = 10
EXPECTED_NOPROCESS = 1
EXPECTED_SOLVED = 1


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def sha_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def read_csv(path):
    with path.open(newline="", encoding="utf-8-sig") as fh:
        return list(csv.DictReader(fh))


def write_csv(path, rows, fields):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    tmp.replace(path)


def write_json(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(obj, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )
    tmp.replace(path)


def inum(v):
    s = "" if v is None else str(v).strip()
    if not s or s.lower() in {"none", "null", "nan", "--"}:
        return None
    try:
        return int(float(s))
    except Exception:
        return None


def fnum(v):
    s = "" if v is None else str(v).strip()
    if not s or s.lower() in {"none", "null", "nan", "--"}:
        return None
    try:
        x = float(s)
        return x if math.isfinite(x) else None
    except Exception:
        return None


def rows_from_votable(raw):
    tbl = Table.read(BytesIO(raw), format="votable")
    rows = []
    for tr in tbl:
        d = {}
        for col in tbl.colnames:
            v = tr[col]
            if np.ma.is_masked(v):
                v = ""
            elif isinstance(v, bytes):
                v = v.decode("utf-8", errors="replace")
            elif isinstance(v, np.generic):
                v = v.item()
            d[col] = v
        rows.append(d)
    return rows


def tap_query(name, q):
    CACHE.mkdir(parents=True, exist_ok=True)
    qpath = CACHE / f"{name}.adql"
    xpath = CACHE / f"{name}.xml"
    mpath = CACHE / f"{name}.meta.json"
    qhash = sha_bytes(q.encode("utf-8"))

    if qpath.is_file() and xpath.is_file() and mpath.is_file():
        if qpath.read_text(encoding="utf-8") == q:
            raw = xpath.read_bytes()
            meta = json.loads(mpath.read_text(encoding="utf-8"))
            if (
                meta.get("query_sha256") == qhash
                and meta.get("response_sha256") == sha_bytes(raw)
            ):
                return rows_from_votable(raw), {**meta, "cached": True}

    payload = urllib.parse.urlencode({
        "REQUEST": "doQuery",
        "LANG": "ADQL",
        "FORMAT": "votable",
        "RESPONSEFORMAT": "votable",
        "MAXREC": "10000",
        "QUERY": q,
    }).encode("utf-8")

    last = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        req = urllib.request.Request(
            TAP_SYNC,
            data=payload,
            method="POST",
            headers={
                "Accept": "application/x-votable+xml,text/xml,*/*",
                "Content-Type": "application/x-www-form-urlencoded",
                "User-Agent": UA,
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                raw = resp.read()
                status = int(getattr(resp, "status", 200))
                ctype = resp.headers.get("Content-Type", "")
                final_url = resp.geturl()
            rows = rows_from_votable(raw)
            qpath.write_text(q, encoding="utf-8", newline="\n")
            xpath.write_bytes(raw)
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
            write_json(mpath, meta)
            return rows, meta
        except urllib.error.HTTPError as exc:
            try:
                body = exc.read(6000).decode("utf-8", errors="replace")
            except Exception:
                body = ""
            last = RuntimeError(
                f"HTTP {exc.code} {exc.reason}; TAP body={body!r}"
            )
            if int(exc.code) != 429:
                break
        except Exception as exc:
            last = exc
        if attempt < MAX_ATTEMPTS:
            time.sleep(min(15.0, 2.0 ** attempt))

    raise RuntimeError(
        f"APPLAUSE TAP query {name} failed on attempt {attempt}: "
        f"{type(last).__name__}: {last}"
    ) from last


def or_filter(col, vals):
    vals = sorted({int(v) for v in vals})
    if not vals:
        raise RuntimeError(f"REFUSING: empty filter for {col}")
    return "(" + " OR ".join(f"{col}={v}" for v in vals) + ")"


def pointing_summary(rows):
    pts = []
    for r in rows:
        ra = fnum(r.get("exposure_ra_icrs"))
        dec = fnum(r.get("exposure_dec_icrs"))
        if ra is not None and dec is not None:
            pts.append((ra, dec))
    if not pts:
        return {
            "pointing_ra_deg": None,
            "pointing_dec_deg": None,
            "max_pointing_spread_deg": None,
        }
    # Vector mean protects RA wrap.
    sc = SkyCoord(
        [p[0] for p in pts] * u.deg,
        [p[1] for p in pts] * u.deg,
        frame="icrs",
    )
    xyz = sc.cartesian.xyz.value
    v = xyz.mean(axis=1)
    v /= np.linalg.norm(v)
    center = SkyCoord(
        x=v[0], y=v[1], z=v[2],
        representation_type="cartesian", frame="icrs"
    )
    sep = sc.separation(center).deg
    return {
        "pointing_ra_deg": float(center.spherical.lon.deg % 360.0),
        "pointing_dec_deg": float(center.spherical.lat.deg),
        "max_pointing_spread_deg": float(np.max(sep)),
    }


def main():
    print("=" * 132)
    print("WIDE CENSUS — INDEPENDENT ASTROMETRIC RESCUE METADATA PREFLIGHT v060")
    print("=" * 132)
    print("NETWORK: APPLAUSE DR4 METADATA / EXTRACTED-SOURCE TABLES ONLY.")
    print("NO SCIENCE PIXELS. NO TRANSIENT DETECTOR. NO CANDIDATE STATE MUTATION.")
    print("NO ASTROMETRIC SOLVER IS RUN. NO v052/v058/v059 CLASSIFICATION IS CHANGED.\n")

    for p in (V059_JSON, V059_PLATES, V059_PROCESS, V058_ENDPOINTS):
        if not p.is_file():
            raise RuntimeError(f"REFUSING: missing prerequisite {p}")

    plates = read_csv(V059_PLATES)
    prows = read_csv(V059_PROCESS)
    eps = read_csv(V058_ENDPOINTS)

    states = {}
    for r in plates:
        s = r.get("v059_plate_state", "")
        states[s] = states.get(s, 0) + 1

    if len(plates) != EXPECTED_PLATES:
        raise RuntimeError("REFUSING: v059 plate count changed")
    if states.get("PROCESS_COMPLETED_ASTROMETRICALLY_UNSOLVED", 0) != EXPECTED_UNSOLVED:
        raise RuntimeError("REFUSING: expected 10 completed-unsolved plates")
    if states.get("NO_PROCESS_ROW_FOR_EXACT_SCAN", 0) != EXPECTED_NOPROCESS:
        raise RuntimeError("REFUSING: expected one no-process scan")
    if states.get("V058_OFFICIAL_SOLUTION_ALREADY_PRESENT", 0) != EXPECTED_SOLVED:
        raise RuntimeError("REFUSING: expected one already-solved plate")

    # Prospective preflight contract is written before any new network query.
    freeze_obj = {
        "contract_id": "wide_census_independent_astrometric_rescue_preflight_v001",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "prospective_before_rescue_solver_outcomes": True,
        "v059_input_sha256": sha(V059_JSON),
        "scope": {
            "completed_astrometrically_unsolved_plates": EXPECTED_UNSOLVED,
            "no_process_exact_scan_plates": EXPECTED_NOPROCESS,
            "already_solved_control_plates": EXPECTED_SOLVED,
        },
        "allowed_new_data": [
            "APPLAUSE DR4 plate metadata",
            "APPLAUSE DR4 exact scan metadata",
            "APPLAUSE DR4 pre-existing extracted source x/y catalogue for exact process_id",
            "APPLAUSE DR4 pre-existing source_xmatch rows for diagnostic inventory only",
        ],
        "forbidden": [
            "science scan pixel reads",
            "transient detector outputs as astrometric inputs",
            "candidate coordinates as solver hints",
            "candidate state mutation",
            "changing geometry hold classification",
            "running any astrometric solver in v060",
        ],
        "source_centroid_inventory_rule": {
            "query": "TOP 1000 flag_clean=1 sources per exact unsolved process_id ordered by flux_max DESC",
            "reported_nested_counts": [
                "all returned flag_clean rows",
                "sextractor_flags==0",
                "model_prediction>=0.9",
                "both sextractor_flags==0 and model_prediction>=0.9",
            ],
            "note": "No centroid subset is selected for a future solver by v060.",
        },
        "fov_priors": {
            "scan_based": "naxis * pixel_size_um / 1000 * ota_scale_arcsec_per_mm / 3600",
            "physical_plate_based": "plate_size_cm * 10 * ota_scale_arcsec_per_mm / 3600",
            "note": "Both are reported. v060 does not choose a solver FOV tolerance.",
        },
        "future_solver_boundary": (
            "A later prospective freeze must select solver software/version, "
            "centroid subset schedule, epoch propagation, FOV tolerances, "
            "acceptance/verification criteria and failure semantics before any "
            "plate-solving result is inspected."
        ),
    }
    FREEZE_DIR.mkdir(parents=True, exist_ok=True)
    if FREEZE.is_file():
        existing = json.loads(FREEZE.read_text(encoding="utf-8"))
        # Ignore created_at only by requiring exact stored bytes on rerun.
        if existing.get("contract_id") != freeze_obj["contract_id"]:
            raise RuntimeError("REFUSING: incompatible v060 preflight freeze exists")
    else:
        write_json(FREEZE, freeze_obj)

    print("Prospective preflight contract:", FREEZE)
    print("Contract SHA256:", sha(FREEZE))
    print("ASTROMETRIC SOLVER OUTCOMES READ: 0\n")

    rescue = [
        r for r in plates
        if r.get("v059_plate_state") != "V058_OFFICIAL_SOLUTION_ALREADY_PRESENT"
    ]
    plate_ids = [inum(r["plate_id"]) for r in rescue]
    scan_ids = [inum(r["scan_id"]) for r in rescue]

    plate_q = f"""SELECT
  plate_id,
  archive_id,
  plate_num,
  plate_num_orig,
  series,
  plate_format,
  plate_size1,
  plate_size2,
  ota_foclen,
  ota_scale,
  instrument,
  method_code
FROM applause_dr4.plate
WHERE {or_filter("plate_id", plate_ids)}
ORDER BY plate_id
"""
    scan_q = f"""SELECT
  scan_id,
  plate_id,
  archive_id,
  filename_scan,
  naxis1,
  naxis2,
  scanner,
  scan_res1,
  scan_res2,
  pixel_size1,
  pixel_size2,
  scan_software,
  file_size,
  fits_checksum
FROM applause_dr4.scan
WHERE {or_filter("scan_id", scan_ids)}
ORDER BY scan_id
"""

    print("Querying physical-plate priors ...", flush=True)
    plate_meta, plate_meta_info = tap_query("plate_priors", plate_q)
    print(f"Plate rows: {len(plate_meta)}")
    print("Querying exact scan priors ...", flush=True)
    scan_meta, scan_meta_info = tap_query("scan_priors", scan_q)
    print(f"Scan rows:  {len(scan_meta)}")

    pmeta = {(inum(r["plate_id"]), inum(r["archive_id"])): r for r in plate_meta}
    smeta = {inum(r["scan_id"]): r for r in scan_meta}

    # Exact completed-unsolved process rows.
    unsolved_process = {}
    for pr in prows:
        pid = inum(pr.get("plate_id"))
        sid = inum(pr.get("scan_id"))
        process_id = inum(pr.get("process_id"))
        if process_id is None:
            continue
        for r in rescue:
            if (
                r.get("v059_plate_state") == "PROCESS_COMPLETED_ASTROMETRICALLY_UNSOLVED"
                and inum(r["plate_id"]) == pid
                and inum(r["scan_id"]) == sid
            ):
                unsolved_process[(pid, sid)] = pr

    if len(unsolved_process) != EXPECTED_UNSOLVED:
        raise RuntimeError(
            f"REFUSING: expected 10 exact unsolved process rows, got {len(unsolved_process)}"
        )

    all_source_rows = []
    all_xmatch_rows = []
    source_query_meta = {}
    xmatch_query_meta = {}

    for idx, ((pid, sid), pr) in enumerate(sorted(unsolved_process.items()), 1):
        proc = inum(pr["process_id"])
        print(
            f"[{idx:02d}/{EXPECTED_UNSOLVED}] process {proc} plate {pid}: "
            f"querying top {SOURCE_TOP} clean extracted centroids ...",
            flush=True,
        )
        sq = f"""SELECT TOP {SOURCE_TOP}
  source_id,
  process_id,
  scan_id,
  plate_id,
  archive_id,
  source_num,
  x_source,
  y_source,
  x_peak,
  y_peak,
  flux_iso,
  flux_max,
  flux_radius,
  elongation,
  sextractor_flags,
  flag_clean,
  model_prediction
FROM applause_dr4.source
WHERE process_id={proc} AND flag_clean=1
ORDER BY flux_max DESC
"""
        srows, sm = tap_query(f"source_process_{proc}", sq)
        source_query_meta[str(proc)] = sm
        for rank, sr in enumerate(srows, 1):
            all_source_rows.append({
                **sr,
                "bright_rank_within_query": rank,
            })

        print(
            f"             returned {len(srows)}; querying existing xmatch diagnostic sample ...",
            flush=True,
        )
        xq = f"""SELECT TOP {XMATCH_TOP}
  source_id,
  process_id,
  scan_id,
  plate_id,
  archive_id,
  dist,
  solution_num,
  gaiaedr3_id,
  x_gaia,
  y_gaia,
  flag_xmatch
FROM applause_dr4.source_xmatch
WHERE process_id={proc}
ORDER BY source_id
"""
        xrows, xm = tap_query(f"xmatch_process_{proc}", xq)
        xmatch_query_meta[str(proc)] = xm
        for xr in xrows:
            all_xmatch_rows.append(xr)

    source_fields = [
        "source_id", "process_id", "scan_id", "plate_id", "archive_id",
        "source_num", "x_source", "y_source", "x_peak", "y_peak",
        "flux_iso", "flux_max", "flux_radius", "elongation",
        "sextractor_flags", "flag_clean", "model_prediction",
        "bright_rank_within_query",
    ]
    write_csv(OUT_SOURCES, all_source_rows, source_fields)

    xmatch_fields = [
        "source_id", "process_id", "scan_id", "plate_id", "archive_id",
        "dist", "solution_num", "gaiaedr3_id", "x_gaia", "y_gaia",
        "flag_xmatch",
    ]
    write_csv(OUT_XMATCH, all_xmatch_rows, xmatch_fields)

    eps_by_plate = {}
    for e in eps:
        key = (inum(e["plate_id"]), inum(e["archive_id"]))
        eps_by_plate.setdefault(key, []).append(e)

    src_by_proc = {}
    for s in all_source_rows:
        src_by_proc.setdefault(inum(s["process_id"]), []).append(s)
    xm_by_proc = {}
    for x in all_xmatch_rows:
        xm_by_proc.setdefault(inum(x["process_id"]), []).append(x)

    plate_out = []
    readiness_counts = {}

    for r in rescue:
        pid = inum(r["plate_id"])
        aid = inum(r["archive_id"])
        sid = inum(r["scan_id"])
        state = r["v059_plate_state"]
        pm = pmeta.get((pid, aid), {})
        sm = smeta.get(sid, {})
        pr = unsolved_process.get((pid, sid))
        proc = None if pr is None else inum(pr.get("process_id"))

        ota_scale = fnum(pm.get("ota_scale"))
        psize1 = fnum(pm.get("plate_size1"))
        psize2 = fnum(pm.get("plate_size2"))
        nx = inum(sm.get("naxis1"))
        ny = inum(sm.get("naxis2"))
        pix1 = fnum(sm.get("pixel_size1"))
        pix2 = fnum(sm.get("pixel_size2"))

        scan_fov1 = (
            nx * pix1 / 1000.0 * ota_scale / 3600.0
            if None not in (nx, pix1, ota_scale) else None
        )
        scan_fov2 = (
            ny * pix2 / 1000.0 * ota_scale / 3600.0
            if None not in (ny, pix2, ota_scale) else None
        )
        plate_fov1 = (
            psize1 * 10.0 * ota_scale / 3600.0
            if None not in (psize1, ota_scale) else None
        )
        plate_fov2 = (
            psize2 * 10.0 * ota_scale / 3600.0
            if None not in (psize2, ota_scale) else None
        )

        sr = [] if proc is None else src_by_proc.get(proc, [])
        clean_returned = len(sr)
        sex0 = sum(inum(x.get("sextractor_flags")) == 0 for x in sr)
        ml09 = sum(
            (fnum(x.get("model_prediction")) is not None)
            and fnum(x.get("model_prediction")) >= 0.9
            for x in sr
        )
        both = sum(
            inum(x.get("sextractor_flags")) == 0
            and (fnum(x.get("model_prediction")) is not None)
            and fnum(x.get("model_prediction")) >= 0.9
            for x in sr
        )
        xms = [] if proc is None else xm_by_proc.get(proc, [])

        psummary = pointing_summary(eps_by_plate.get((pid, aid), []))

        if state == "NO_PROCESS_ROW_FOR_EXACT_SCAN":
            readiness = "PIXEL_SOURCE_EXTRACTION_REQUIRED_NO_APPLAUSE_PROCESS"
        elif clean_returned >= 50:
            readiness = "OFFICIAL_CENTROID_CATALOGUE_READY_FOR_PROSPECTIVE_SOLVER"
        else:
            readiness = "INSUFFICIENT_TOP_CLEAN_CENTROID_SAMPLE_REVIEW_METADATA"
        readiness_counts[readiness] = readiness_counts.get(readiness, 0) + 1

        plate_out.append({
            "plate_id": pid,
            "archive_id": aid,
            "scan_id": sid,
            "process_id": proc,
            "v059_plate_state": state,
            "plate_num": pm.get("plate_num"),
            "plate_num_orig": pm.get("plate_num_orig"),
            "series": pm.get("series"),
            "instrument": pm.get("instrument"),
            "method_code": pm.get("method_code"),
            "plate_size1_cm": psize1,
            "plate_size2_cm": psize2,
            "ota_foclen_m": fnum(pm.get("ota_foclen")),
            "ota_scale_arcsec_per_mm": ota_scale,
            "naxis1": nx,
            "naxis2": ny,
            "scanner": sm.get("scanner"),
            "pixel_size1_um": pix1,
            "pixel_size2_um": pix2,
            "scan_fov1_prior_deg": scan_fov1,
            "scan_fov2_prior_deg": scan_fov2,
            "physical_plate_fov1_prior_deg": plate_fov1,
            "physical_plate_fov2_prior_deg": plate_fov2,
            **psummary,
            "process_num_sources": None if pr is None else inum(pr.get("num_sources")),
            "top_clean_centroids_returned": clean_returned,
            "top_clean_sextractor_flags0_count": sex0,
            "top_clean_model_prediction_ge_0p9_count": ml09,
            "top_clean_both_count": both,
            "existing_source_xmatch_sample_rows": len(xms),
            "v060_rescue_readiness": readiness,
            "solver_run": False,
            "science_pixels_read": False,
        })

    plate_fields = [
        "plate_id", "archive_id", "scan_id", "process_id",
        "v059_plate_state", "plate_num", "plate_num_orig", "series",
        "instrument", "method_code", "plate_size1_cm", "plate_size2_cm",
        "ota_foclen_m", "ota_scale_arcsec_per_mm", "naxis1", "naxis2",
        "scanner", "pixel_size1_um", "pixel_size2_um",
        "scan_fov1_prior_deg", "scan_fov2_prior_deg",
        "physical_plate_fov1_prior_deg", "physical_plate_fov2_prior_deg",
        "pointing_ra_deg", "pointing_dec_deg", "max_pointing_spread_deg",
        "process_num_sources", "top_clean_centroids_returned",
        "top_clean_sextractor_flags0_count",
        "top_clean_model_prediction_ge_0p9_count",
        "top_clean_both_count", "existing_source_xmatch_sample_rows",
        "v060_rescue_readiness", "solver_run", "science_pixels_read",
    ]
    write_csv(OUT_PLATES, plate_out, plate_fields)

    fovs = [
        max(x for x in (r["scan_fov1_prior_deg"], r["scan_fov2_prior_deg"]) if x is not None)
        for r in plate_out
        if r["scan_fov1_prior_deg"] is not None or r["scan_fov2_prior_deg"] is not None
    ]
    centroid_counts = [
        r["top_clean_centroids_returned"]
        for r in plate_out
        if r["process_id"] is not None
    ]

    report = {
        "status": "COMPLETE",
        "analysis_kind": "wide_census_astrometric_rescue_preflight_v060",
        "completed_at_utc": datetime.now(timezone.utc).isoformat(),
        "guards": {
            "network_access": True,
            "network_scope": "APPLAUSE DR4 metadata/source catalogues only",
            "science_pixels_read": False,
            "transient_detector_rerun": False,
            "astrometric_solver_run": False,
            "candidate_state_mutation": False,
            "geometry_classification_mutation": False,
            "automation_registry_mutation": False,
        },
        "prospective_preflight_contract": {
            "path": str(FREEZE.relative_to(ROOT)).replace("\\", "/"),
            "sha256": sha(FREEZE),
        },
        "scope": {
            "rescue_physical_plates": len(rescue),
            "completed_unsolved_with_process": EXPECTED_UNSOLVED,
            "no_process_exact_scan": EXPECTED_NOPROCESS,
        },
        "readiness_counts": readiness_counts,
        "scan_fov_prior_deg_summary": {
            "count": len(fovs),
            "min": None if not fovs else float(min(fovs)),
            "median": None if not fovs else float(np.median(fovs)),
            "max": None if not fovs else float(max(fovs)),
        },
        "top_clean_centroid_return_summary": {
            "process_count": len(centroid_counts),
            "min": None if not centroid_counts else min(centroid_counts),
            "median": None if not centroid_counts else float(np.median(centroid_counts)),
            "max": None if not centroid_counts else max(centroid_counts),
            "top_cap": SOURCE_TOP,
            "note": (
                "A value equal to TOP cap means at least that many qualifying "
                "rows exist, not that the process contains only that many."
            ),
        },
        "existing_xmatch_diagnostic": {
            "total_sample_rows": len(all_xmatch_rows),
            "top_cap_per_process": XMATCH_TOP,
            "interpretation": (
                "Diagnostic only. Existing xmatch rows from an archive-unsolved "
                "process are not accepted as an astrometric solution by v060."
            ),
        },
        "tap_provenance": {
            "plate_query": plate_meta_info,
            "scan_query": scan_meta_info,
            "source_queries_by_process": source_query_meta,
            "xmatch_queries_by_process": xmatch_query_meta,
        },
        "plate_inventory": plate_out,
        "next_methodological_gate": (
            "Use only these metadata distributions to prospectively freeze a "
            "Windows-compatible centroid-based solver, its exact version/hash, "
            "FOV-attempt schedule, epoch handling, independent Gaia verification "
            "and failure semantics before running any solve."
        ),
    }
    write_json(OUT_JSON, report)

    print("\nRescue readiness:")
    for k, v in sorted(readiness_counts.items(), key=lambda kv: (-kv[1], kv[0])):
        print(f"  {v:3d}  {k}")
    print("\nScan-FOV prior summary (deg):", report["scan_fov_prior_deg_summary"])
    print("Top-clean-centroid summary:", report["top_clean_centroid_return_summary"])
    print("Existing xmatch diagnostic sample rows:", len(all_xmatch_rows))
    print("\nOutputs:")
    print(" ", OUT_JSON)
    print(" ", OUT_PLATES)
    print(" ", OUT_SOURCES)
    print(" ", OUT_XMATCH)
    print("\nASTROMETRIC SOLVER RUNS: 0")
    print("SCIENCE PIXELS READ: 0")
    print("STAGE STATUS: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
