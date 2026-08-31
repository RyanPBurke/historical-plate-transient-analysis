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
import urllib.error
import urllib.parse
import urllib.request
import warnings

import numpy as np
from astropy.io import fits
from astropy.table import Table
from astropy.wcs import WCS
from astropy.wcs import FITSFixedWarning

ROOT = Path.cwd()

V058_DIR = ROOT / "results" / "wide_census_applause_hold_metadata_v058"
V058_JSON = V058_DIR / "wide_census_applause_hold_metadata_v058.json"
V058_ENDPOINTS = V058_DIR / "wide_census_applause_hold_endpoint_inventory_v058.csv"
V058_SCAN_CACHE = V058_DIR / "cache" / "applause_scan_unresolved_v058.xml"
V058_SCAN_META = V058_DIR / "cache" / "applause_scan_unresolved_v058.meta.json"

OUTDIR = ROOT / "results" / "wide_census_applause_process_audit_v059"
CACHE = OUTDIR / "cache"

PROCESS_Q = CACHE / "applause_process_v059.adql"
PROCESS_XML = CACHE / "applause_process_v059.xml"
PROCESS_META = CACHE / "applause_process_v059.meta.json"

SET_Q = CACHE / "applause_solution_set_v059.adql"
SET_XML = CACHE / "applause_solution_set_v059.xml"
SET_META = CACHE / "applause_solution_set_v059.meta.json"

OUT_JSON = OUTDIR / "wide_census_applause_process_audit_v059.json"
OUT_PLATES = OUTDIR / "wide_census_applause_plate_process_state_v059.csv"
OUT_PROCESS = OUTDIR / "wide_census_applause_process_rows_v059.csv"
OUT_SETS = OUTDIR / "wide_census_applause_solution_set_rows_v059.csv"

TAP_SYNC = "https://www.plate-archive.org/tap/sync"
UA = "historical-transient-pipeline/0.2.0-wide-census-v059"
TIMEOUT = 180
MAX_ATTEMPTS = 4

EXPECTED_V058_ENDPOINT_OCCURRENCES = 35
EXPECTED_V058_UNIQUE_EXPOSURES = 21
EXPECTED_V058_PHYSICAL_PLATES = 12
EXPECTED_V058_NO_SOLUTION_OCCURRENCES = 34
EXPECTED_V058_UNIQUE_POLYGONABLE = 1


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


def table_rows(tbl):
    out = []
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
        out.append(d)
    return out


def parse_cached_votable(xml_path, meta_path):
    if not xml_path.is_file() or not meta_path.is_file():
        raise RuntimeError(f"REFUSING: missing v058 cache {xml_path} / {meta_path}")
    raw = xml_path.read_bytes()
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    if meta.get("response_sha256") != sha_bytes(raw):
        raise RuntimeError("REFUSING: v058 APPLAUSE scan cache SHA mismatch")
    tbl = Table.read(BytesIO(raw), format="votable")
    return table_rows(tbl), meta


def or_filter(column, values):
    vals = sorted({int(x) for x in values})
    if not vals:
        raise RuntimeError(f"REFUSING: empty filter {column}")
    return "(" + " OR ".join(f"{column}={x}" for x in vals) + ")"


def tap_query(q, qpath, xpath, mpath):
    CACHE.mkdir(parents=True, exist_ok=True)
    qhash = sha_bytes(q.encode("utf-8"))

    if qpath.is_file() and xpath.is_file() and mpath.is_file():
        if qpath.read_text(encoding="utf-8") == q:
            raw = xpath.read_bytes()
            meta = json.loads(mpath.read_text(encoding="utf-8"))
            if (
                meta.get("query_sha256") == qhash
                and meta.get("response_sha256") == sha_bytes(raw)
            ):
                return table_rows(Table.read(BytesIO(raw), format="votable")), {
                    **meta, "cached": True
                }

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
            rows = table_rows(Table.read(BytesIO(raw), format="votable"))
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
                f"HTTP {exc.code} {exc.reason}; TAP response body={body!r}"
            )
            if int(exc.code) != 429:
                break
        except Exception as exc:
            last = exc
        if attempt < MAX_ATTEMPTS:
            time.sleep(min(15.0, 2.0 ** attempt))

    raise RuntimeError(
        f"APPLAUSE TAP query failed on attempt {attempt}: "
        f"{type(last).__name__}: {last}"
    ) from last


def normalize_header_text(text):
    s = "" if text is None else str(text)
    # TAP serialisation can preserve literal backslash-n sequences. Convert only
    # those explicit line separators; do not otherwise alter FITS card content.
    if "\\n" in s and "\n" not in s:
        s = s.replace("\\n", "\n")
    return s


def footprint_from_solution_set_header(text, nx, ny):
    s = normalize_header_text(text)
    if not s.strip() or not nx or not ny:
        return None, "NO_USABLE_SOLUTION_SET_HEADER"

    headers = []
    for sep in ("\n", ""):
        try:
            headers.append(fits.Header.fromstring(s, sep=sep))
        except Exception:
            pass

    for hdr in headers:
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", FITSFixedWarning)
                w = WCS(hdr, relax=True).celestial
                if not w.has_celestial:
                    continue
                fp = w.calc_footprint(axes=(int(nx), int(ny)), center=False)
            arr = np.asarray(fp, dtype=float)
            if arr.shape != (4, 2) or not np.all(np.isfinite(arr)):
                continue
            return [
                [float(ra) % 360.0, float(dec)]
                for ra, dec in arr
            ], "SOLUTION_SET_HEADER_WCS_PLUS_EXACT_SCAN_DIMENSIONS"
        except Exception:
            continue
    return None, "SOLUTION_SET_HEADER_PRESENT_BUT_UNUSABLE"


def main():
    print("=" * 132)
    print("WIDE CENSUS — APPLAUSE UNSOLVED-PLATE PROCESS / SOLUTION-SET AUDIT v059")
    print("=" * 132)
    print("NETWORK: APPLAUSE DR4 TAP METADATA ONLY.")
    print("NO SCIENCE PIXELS. NO DETECTOR. NO CANDIDATE STATE MUTATION.")
    print("NO v052/v058 CLASSIFICATION IS CHANGED.\n")

    for p in (V058_JSON, V058_ENDPOINTS, V058_SCAN_CACHE, V058_SCAN_META):
        if not p.is_file():
            raise RuntimeError(f"REFUSING: missing prerequisite {p}")

    v58 = json.loads(V058_JSON.read_text(encoding="utf-8"))
    eps = read_csv(V058_ENDPOINTS)

    if len(eps) != EXPECTED_V058_ENDPOINT_OCCURRENCES:
        raise RuntimeError(f"REFUSING: expected 35 v058 endpoint rows, got {len(eps)}")
    if len({inum(r.get("exposure_id")) for r in eps}) != EXPECTED_V058_UNIQUE_EXPOSURES:
        raise RuntimeError("REFUSING: v058 unique exposure count changed")
    if len({inum(r.get("plate_id")) for r in eps}) != EXPECTED_V058_PHYSICAL_PLATES:
        raise RuntimeError("REFUSING: v058 physical plate count changed")

    states = {}
    for r in eps:
        s = r.get("v058_metadata_resolution_state", "")
        states[s] = states.get(s, 0) + 1
    if states.get("NO_OFFICIAL_SOLUTION_ROWS_FOR_PHYSICAL_PLATE", 0) != EXPECTED_V058_NO_SOLUTION_OCCURRENCES:
        raise RuntimeError("REFUSING: v058 no-solution occurrence count changed")
    if states.get("UNIQUE_POLYGONABLE_OFFICIAL_SOLUTION", 0) != EXPECTED_V058_UNIQUE_POLYGONABLE:
        raise RuntimeError("REFUSING: v058 polygonable occurrence count changed")

    scan_rows, scan_meta = parse_cached_votable(V058_SCAN_CACHE, V058_SCAN_META)
    if len(scan_rows) != EXPECTED_V058_PHYSICAL_PLATES:
        raise RuntimeError(
            f"REFUSING: expected 12 exact official scan rows, got {len(scan_rows)}"
        )

    scan_by_id = {}
    scans_by_plate = {}
    for r in scan_rows:
        sid = inum(r.get("scan_id"))
        pid = inum(r.get("plate_id"))
        aid = inum(r.get("archive_id"))
        if sid is None or pid is None or aid is None:
            raise RuntimeError("REFUSING: official v058 scan row missing identity")
        if sid in scan_by_id:
            raise RuntimeError(f"REFUSING: duplicate scan_id {sid}")
        scan_by_id[sid] = r
        scans_by_plate.setdefault((pid, aid), []).append(r)

    plates = sorted({(inum(r["plate_id"]), inum(r["archive_id"])) for r in eps})
    plate_ids = [p for p, _ in plates]

    print(f"v058 unresolved APPLAUSE endpoint occurrences: {len(eps)}")
    print(f"Unique exposures:                            {len({inum(r['exposure_id']) for r in eps})}")
    print(f"Physical plates:                             {len(plates)}")
    print(f"Exact scan rows recovered from v058 cache:   {len(scan_rows)}")

    where = or_filter("plate_id", plate_ids)
    process_q = f"""SELECT
  process_id,
  scan_id,
  plate_id,
  archive_id,
  filename,
  num_exposures,
  plate_epoch,
  num_sources,
  num_psf_sources,
  solved,
  num_true_sources,
  num_artifacts,
  num_solutions,
  num_gaia_edr3,
  num_calib,
  calibrated,
  completed,
  pyplate_version,
  timestamp_start,
  timestamp_end
FROM applause_dr4.process
WHERE {where}
ORDER BY plate_id, scan_id, process_id
"""

    set_q = f"""SELECT
  solutionset_id,
  process_id,
  scan_id,
  plate_id,
  archive_id,
  num_solutions,
  num_duplicate_solutions,
  pattern_ratio,
  mean_pixel_scale,
  min_pixel_scale,
  max_pixel_scale,
  mean_fov1,
  mean_fov2,
  source_density,
  max_separation,
  header_wcs,
  timestamp_insert,
  timestamp_update
FROM applause_dr4.solution_set
WHERE {where}
ORDER BY plate_id, scan_id, process_id, solutionset_id
"""

    print("Querying official applause_dr4.process ...", flush=True)
    process_rows, process_meta = tap_query(
        process_q, PROCESS_Q, PROCESS_XML, PROCESS_META
    )
    print(f"Process rows returned:                       {len(process_rows)}")

    print("Querying official applause_dr4.solution_set ...", flush=True)
    set_rows, set_meta = tap_query(set_q, SET_Q, SET_XML, SET_META)
    print(f"Solution-set rows returned:                  {len(set_rows)}")

    write_csv(
        OUT_PROCESS,
        process_rows,
        [
            "process_id", "scan_id", "plate_id", "archive_id", "filename",
            "num_exposures", "plate_epoch", "num_sources", "num_psf_sources",
            "solved", "num_true_sources", "num_artifacts", "num_solutions",
            "num_gaia_edr3", "num_calib", "calibrated", "completed",
            "pyplate_version", "timestamp_start", "timestamp_end",
        ],
    )
    write_csv(
        OUT_SETS,
        set_rows,
        [
            "solutionset_id", "process_id", "scan_id", "plate_id", "archive_id",
            "num_solutions", "num_duplicate_solutions", "pattern_ratio",
            "mean_pixel_scale", "min_pixel_scale", "max_pixel_scale",
            "mean_fov1", "mean_fov2", "source_density", "max_separation",
            "header_wcs", "timestamp_insert", "timestamp_update",
        ],
    )

    proc_by_plate = {}
    for r in process_rows:
        key = (inum(r.get("plate_id")), inum(r.get("archive_id")))
        proc_by_plate.setdefault(key, []).append(r)

    sets_by_plate = {}
    for r in set_rows:
        key = (inum(r.get("plate_id")), inum(r.get("archive_id")))
        sets_by_plate.setdefault(key, []).append(r)

    endpoint_count_by_plate = {}
    exposure_ids_by_plate = {}
    v58_states_by_plate = {}
    for r in eps:
        key = (inum(r["plate_id"]), inum(r["archive_id"]))
        endpoint_count_by_plate[key] = endpoint_count_by_plate.get(key, 0) + 1
        exposure_ids_by_plate.setdefault(key, set()).add(inum(r["exposure_id"]))
        v58_states_by_plate.setdefault(key, set()).add(
            r.get("v058_metadata_resolution_state", "")
        )

    plate_out = []
    state_counts = {}
    recovered_set_wcs = 0

    for key in plates:
        pid, aid = key
        scans = scans_by_plate.get(key, [])
        procs = proc_by_plate.get(key, [])
        sets = sets_by_plate.get(key, [])

        if len(scans) != 1:
            raise RuntimeError(
                f"REFUSING: expected exactly one v058 scan row for plate {key}, "
                f"got {len(scans)}"
            )
        scan = scans[0]
        sid = inum(scan.get("scan_id"))
        nx = inum(scan.get("naxis1"))
        ny = inum(scan.get("naxis2"))

        # Restrict process/solution_set interpretation to the exact scan selected
        # by the v058 plate-scoped scan query.
        exact_procs = [r for r in procs if inum(r.get("scan_id")) == sid]
        exact_sets = [r for r in sets if inum(r.get("scan_id")) == sid]

        solved_rows = [r for r in exact_procs if inum(r.get("solved")) == 1]
        completed_rows = [r for r in exact_procs if inum(r.get("completed")) == 1]
        positive_proc_solutions = [
            r for r in exact_procs if (inum(r.get("num_solutions")) or 0) > 0
        ]
        positive_sets = [
            r for r in exact_sets if (inum(r.get("num_solutions")) or 0) > 0
        ]

        set_polys = []
        for s in exact_sets:
            poly, provenance = footprint_from_solution_set_header(
                s.get("header_wcs"), nx, ny
            )
            if poly is not None:
                set_polys.append({
                    "solutionset_id": inum(s.get("solutionset_id")),
                    "process_id": inum(s.get("process_id")),
                    "num_solutions": inum(s.get("num_solutions")),
                    "polygon_icrs_deg": poly,
                    "provenance": provenance,
                })

        if set_polys:
            recovered_set_wcs += 1

        v58states = v58_states_by_plate.get(key, set())
        had_solution_table = (
            "UNIQUE_POLYGONABLE_OFFICIAL_SOLUTION" in v58states
            or "MULTIPLE_POLYGONABLE_OFFICIAL_SOLUTIONS_RETAIN_ASSOCIATION_HOLD" in v58states
        )

        if had_solution_table:
            state = "V058_OFFICIAL_SOLUTION_ALREADY_PRESENT"
        elif set_polys:
            state = "NO_SOLUTION_ROW_BUT_USABLE_SOLUTION_SET_WCS"
        elif solved_rows or positive_proc_solutions or positive_sets:
            state = "ASTROMETRY_REPORTED_SOLVED_BUT_NO_USABLE_SOLUTION_ROW_OR_SET_WCS"
        elif exact_procs and completed_rows:
            state = "PROCESS_COMPLETED_ASTROMETRICALLY_UNSOLVED"
        elif exact_procs:
            state = "PROCESS_PRESENT_NOT_COMPLETED_OR_UNSOLVED"
        else:
            state = "NO_PROCESS_ROW_FOR_EXACT_SCAN"

        state_counts[state] = state_counts.get(state, 0) + 1

        plate_out.append({
            "plate_id": pid,
            "archive_id": aid,
            "scan_id": sid,
            "filename_scan": scan.get("filename_scan"),
            "naxis1": nx,
            "naxis2": ny,
            "endpoint_occurrences": endpoint_count_by_plate.get(key, 0),
            "unique_exposure_count": len(exposure_ids_by_plate.get(key, set())),
            "exposure_ids": ";".join(
                str(x) for x in sorted(exposure_ids_by_plate.get(key, set()))
            ),
            "v058_states": ";".join(sorted(v58states)),
            "process_row_count_exact_scan": len(exact_procs),
            "completed_process_row_count": len(completed_rows),
            "solved_process_row_count": len(solved_rows),
            "positive_num_solutions_process_row_count": len(positive_proc_solutions),
            "solution_set_row_count_exact_scan": len(exact_sets),
            "positive_solution_set_row_count": len(positive_sets),
            "usable_solution_set_wcs_count": len(set_polys),
            "solution_set_wcs_inventory_json": json.dumps(
                set_polys, sort_keys=True
            ),
            "v059_plate_state": state,
            "v052_or_v058_classification_changed": False,
        })

    write_csv(
        OUT_PLATES,
        plate_out,
        [
            "plate_id", "archive_id", "scan_id", "filename_scan", "naxis1",
            "naxis2", "endpoint_occurrences", "unique_exposure_count",
            "exposure_ids", "v058_states", "process_row_count_exact_scan",
            "completed_process_row_count", "solved_process_row_count",
            "positive_num_solutions_process_row_count",
            "solution_set_row_count_exact_scan",
            "positive_solution_set_row_count", "usable_solution_set_wcs_count",
            "solution_set_wcs_inventory_json", "v059_plate_state",
            "v052_or_v058_classification_changed",
        ],
    )

    report = {
        "status": "COMPLETE",
        "analysis_kind": "wide_census_applause_process_audit_v059",
        "completed_at_utc": datetime.now(timezone.utc).isoformat(),
        "guards": {
            "network_access": True,
            "network_scope": "APPLAUSE DR4 process + solution_set metadata only",
            "science_pixels_read": False,
            "non_science_pixels_read": False,
            "transient_detector_rerun": False,
            "candidate_state_mutation": False,
            "v052_classification_mutation": False,
            "v058_classification_mutation": False,
            "automation_registry_mutation": False,
        },
        "inputs": {
            "v058_json_sha256": sha(V058_JSON),
            "v058_endpoints_sha256": sha(V058_ENDPOINTS),
            "v058_scan_cache_sha256": sha(V058_SCAN_CACHE),
            "v058_scan_cache_meta_sha256": sha(V058_SCAN_META),
        },
        "scope": {
            "endpoint_occurrences": len(eps),
            "unique_exposures": len({inum(r["exposure_id"]) for r in eps}),
            "physical_plates": len(plates),
            "exact_scan_rows": len(scan_rows),
        },
        "tap": {
            "endpoint": TAP_SYNC,
            "process_query_sha256": sha_bytes(process_q.encode("utf-8")),
            "process_response": process_meta,
            "solution_set_query_sha256": sha_bytes(set_q.encode("utf-8")),
            "solution_set_response": set_meta,
        },
        "plate_state_counts": state_counts,
        "plates_with_usable_solution_set_wcs": recovered_set_wcs,
        "plate_inventory": plate_out,
        "interpretation_boundary": (
            "v059 determines whether v058 APPLAUSE no-solution plates are "
            "archive-pipeline astrometric failures, unprocessed scans, or have "
            "a usable official solution_set-level WCS. No hold is resolved here. "
            "A later prospectively frozen resolver may use a solution_set WCS "
            "only when its exact scan/plate identity is preserved and no "
            "detector outcome participates in the choice."
        ),
        "outputs": {
            "plate_state_csv": str(OUT_PLATES.relative_to(ROOT)).replace("\\", "/"),
            "process_rows_csv": str(OUT_PROCESS.relative_to(ROOT)).replace("\\", "/"),
            "solution_set_rows_csv": str(OUT_SETS.relative_to(ROOT)).replace("\\", "/"),
        },
    }
    write_json(OUT_JSON, report)

    print("\nPlate-level states:")
    for k, v in sorted(state_counts.items(), key=lambda kv: (-kv[1], kv[0])):
        print(f"  {v:3d}  {k}")
    print(f"\nPlates with usable solution_set WCS: {recovered_set_wcs}/{len(plates)}")
    print("\nOutputs:")
    print(" ", OUT_JSON)
    print(" ", OUT_PLATES)
    print(" ", OUT_PROCESS)
    print(" ", OUT_SETS)
    print("\nNO v052/v058 classification was changed.")
    print("STAGE STATUS: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
