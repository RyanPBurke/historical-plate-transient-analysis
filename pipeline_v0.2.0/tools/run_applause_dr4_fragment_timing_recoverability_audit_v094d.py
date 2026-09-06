#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
from collections import Counter, defaultdict
from datetime import datetime, timezone
import argparse
import csv
import hashlib
import json
import math
import re
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "research" / "prospective_freezes" / "applause_dr4_fragment_timing_recoverability_contract_v094d.json"
EXPECTED_CONTRACT_SHA = "55f24e22fc43515b24710e1413a8daabfcee0def2dfab06ac2b8429ba38b1779"

TAP_ASYNC = "https://www.plate-archive.org/tap/async"
MAXREC = 500000

WORK = ROOT / "work" / "applause_dr4_fragment_timing_recoverability_audit_v094d"
RAW = WORK / "tap_raw_votables"
NORMALIZED = WORK / "tap_normalized_csv"
STATE = WORK / "state"
RESULT = ROOT / "results" / "applause_dr4_fragment_timing_recoverability_audit_v094d"

V093_WORK = ROOT / "work" / "applause_dr4_busko_first_cross_observatory_opportunity_census_v093" / "tap_cache"
V093_RESULT = ROOT / "results" / "applause_dr4_busko_first_cross_observatory_opportunity_census_v093"
V093E_RESULT = ROOT / "results" / "applause_dr4_site_coordinate_semantics_repair_v093e"

OLD_EXPOSURE = V093_WORK / "exposure.csv"
OLD_SCAN = V093_WORK / "scan.csv"
OLD_SOLUTION = V093_WORK / "solution.csv"
OLD_REGISTRY = V093_RESULT / "applause_dr4_digitally_usable_exposure_registry_v093.csv"
V093E_OPP = V093E_RESULT / "applause_dr4_site_coordinate_repaired_opportunities_v093e.csv"
V093E_COMP = V093E_RESULT / "applause_dr4_site_coordinate_repaired_comparisons_v093e.csv"

EXPECTED_FROZEN_HASHES = {
    OLD_EXPOSURE: "68681ed5a5d9116e1cf8b304a306a9fbbea6ebf2e8e709848e58d31d2800c162",
    OLD_SCAN: "e6879ca2c1e63a75f50920221a90a3896d9ff2c39a5cd0a7eda4df65b456e22d",
    OLD_SOLUTION: "a3ceb6d63d27dc594875e9ad4b29e3716dd921a629113e92ca35e2e5b28a10bc",
    OLD_REGISTRY: "9e332bf49a2aa3b23f02e2db146dfe4977450eba1918ab6dc2d3782b7969e4f1",
    V093E_OPP: "b8e05e30eadab90c949f22f50bfe156fae985fddbab799164be08ac90068e0db",
    V093E_COMP: "a15333d27076b1a202f4ef3f00fb3a09e91c0fe1a0ce4d3c88cb6d26525b7869",
}

QUERIES = {
    "exposure_full": "SELECT * FROM applause_dr4.exposure",
    "exposure_sub_full": "SELECT * FROM applause_dr4.exposure_sub",
    "scan_full": (
        "SELECT scan_id, plate_id, archive_id, filename_scan, naxis1, naxis2 "
        "FROM applause_dr4.scan"
    ),
    "solution_full": (
        "SELECT solution_id, scan_id, plate_id, archive_id, solution_num, "
        "ra_icrs, dec_icrs, fov1, fov2, stc_polygon, num_xmatch "
        "FROM applause_dr4.solution"
    ),
}

EXPECTED_COLS = {
    "exposure_full": {"exposure_id", "plate_id", "archive_id", "ut_start", "ut_end", "ra_icrs", "dec_icrs", "num_sub", "flag_time"},
    "exposure_sub_full": {"subexposure_id", "exposure_id", "subexposure_num", "ut_start", "ut_end", "exptime"},
    "scan_full": {"scan_id", "plate_id", "filename_scan"},
    "solution_full": {"solution_id", "scan_id", "plate_id", "ra_icrs", "dec_icrs", "stc_polygon", "num_xmatch"},
}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(8 * 1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def log(msg: str = "") -> None:
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}", flush=True)


def write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def iter_csv(path: Path):
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        yield from csv.DictReader(f)


def safe_float(v):
    try:
        s = str(v if v is not None else "").strip()
        if not s:
            return None
        x = float(s)
        return x if math.isfinite(x) else None
    except Exception:
        return None


def safe_int(v):
    x = safe_float(v)
    if x is None:
        return None
    r = int(round(x))
    if abs(x - r) > 1e-9:
        return None
    return r


def parse_dt(v):
    s = str(v if v is not None else "").strip()
    if not s:
        return None
    s = s.replace("Z", "+00:00")
    try:
        d = datetime.fromisoformat(s)
    except Exception:
        d = None
        for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S"):
            try:
                d = datetime.strptime(s, fmt)
                break
            except Exception:
                pass
        if d is None:
            return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d.astimezone(timezone.utc)


def bval(v) -> bool:
    return str(v if v is not None else "").strip().lower() in {"1", "true", "yes"}


def interpret_flag_time(v):
    raw = str(v if v is not None else "")
    code = raw.strip()
    if code == "":
        return raw, "NO_EXPLICIT_WARNING_EMPTY", False
    u = code.upper()
    if u == "NULL":
        return raw, "NO_EXPLICIT_WARNING_LITERAL_NULL", False
    if u == "M":
        return raw, "WARNING_MISSING", True
    if u == "E":
        return raw, "WARNING_ERROR", True
    if u == "U":
        return raw, "WARNING_UNCERTAIN", True
    return raw, "WARNING_UNKNOWN_CODE", True


def parse_stc_polygon(v):
    s = str(v if v is not None else "").strip()
    nums = [float(x) for x in re.findall(r'[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?', s)]
    if len(nums) < 8:
        return None
    nums = nums[-8:]
    pts = [(nums[i] % 360.0, nums[i + 1]) for i in range(0, 8, 2)]
    if any(not (-90.0 <= dec <= 90.0) for _, dec in pts):
        return None
    return pts


def angular_sep_deg(ra1, dec1, ra2, dec2):
    r1, r2 = math.radians(ra1), math.radians(ra2)
    d1, d2 = math.radians(dec1), math.radians(dec2)
    c = math.sin(d1) * math.sin(d2) + math.cos(d1) * math.cos(d2) * math.cos(r1 - r2)
    c = max(-1.0, min(1.0, c))
    return math.degrees(math.acos(c))


def discover_result_url(job: str) -> str:
    try:
        with urllib.request.urlopen(job, timeout=120) as r:
            body = r.read().decode("utf-8", "replace")
        root = ET.fromstring(body)
        for el in root.iter():
            if el.tag.lower().endswith("result"):
                href = el.attrib.get("{http://www.w3.org/1999/xlink}href") or el.attrib.get("href")
                if href:
                    return urllib.parse.urljoin(job + "/", href)
    except Exception:
        pass
    for suffix in ("/results/result", "/results/votable", "/results/csv"):
        u = job + suffix
        try:
            with urllib.request.urlopen(u, timeout=120) as r:
                head = r.read(1024)
            if b"VOTABLE" in head.upper() or head.lstrip().startswith(b"<?xml"):
                return u
        except Exception:
            pass
    raise RuntimeError(f"Could not discover TAP result URL for {job}")


def download(url: str, dest: Path) -> None:
    tmp = dest.with_suffix(dest.suffix + ".part")
    with urllib.request.urlopen(url, timeout=3600) as r, tmp.open("wb") as out:
        while True:
            b = r.read(1024 * 1024)
            if not b:
                break
            out.write(b)
    tmp.replace(dest)


def validate_normalized(path: Path, expected_cols: set[str]) -> bool:
    if not path.is_file() or path.stat().st_size < 20:
        return False
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as f:
            hdr = next(csv.reader(f), [])
        return expected_cols.issubset({str(x).strip().lower() for x in hdr})
    except Exception:
        return False


def tap_acquire(name: str, query: str, expected_cols: set[str]) -> tuple[Path, Path, dict]:
    from astropy.table import Table
    RAW.mkdir(parents=True, exist_ok=True)
    NORMALIZED.mkdir(parents=True, exist_ok=True)
    STATE.mkdir(parents=True, exist_ok=True)
    raw = RAW / f"{name}.vot"
    norm = NORMALIZED / f"{name}.csv"
    meta = STATE / f"{name}_tap_acquisition.json"

    if raw.is_file() and validate_normalized(norm, expected_cols):
        tbl = Table.read(raw, format="votable")
        if expected_cols.issubset({str(c).lower() for c in tbl.colnames}):
            rec = {
                "status": "CACHE_REUSED",
                "name": name,
                "query": query,
                "raw_votable": str(raw.relative_to(ROOT)).replace("\\", "/"),
                "raw_sha256": sha256(raw),
                "normalized_csv": str(norm.relative_to(ROOT)).replace("\\", "/"),
                "normalized_sha256": sha256(norm),
                "row_count": len(tbl),
            }
            write_json(meta, rec)
            return raw, norm, rec

    q = " ".join(query.split())
    attempts = []
    for attempt in range(1, 7):
        try:
            log(f"TAP submit {name}, attempt {attempt}")
            data = urllib.parse.urlencode({
                "REQUEST": "doQuery", "LANG": "ADQL", "FORMAT": "votable",
                "QUERY": q, "QUEUE": "1h", "MAXREC": str(MAXREC), "PHASE": "RUN",
            }).encode("utf-8")
            req = urllib.request.Request(TAP_ASYNC, data=data, method="POST")
            with urllib.request.urlopen(req, timeout=180) as r:
                job = r.geturl().rstrip("/")
                body = r.read(20000).decode("utf-8", "replace")
                loc = r.headers.get("Location")
                if loc:
                    job = urllib.parse.urljoin(job + "/", loc).rstrip("/")
            if "/tap/async/" not in job:
                m = re.search(r'https?://[^"\s<]+/tap/async/[^"\s<]+', body)
                if m:
                    job = m.group(0).rstrip("/")
            if "/tap/async/" not in job:
                raise RuntimeError(f"Could not resolve TAP job URL: {job!r}")

            t0 = time.time()
            while True:
                with urllib.request.urlopen(job + "/phase", timeout=120) as r:
                    phase = r.read().decode("utf-8", "replace").strip().upper()
                if "COMPLETED" in phase:
                    break
                if "ERROR" in phase or "ABORTED" in phase:
                    raise RuntimeError(f"TAP job ended in phase {phase}")
                if time.time() - t0 > 4 * 3600:
                    raise RuntimeError("TAP job exceeded 4 hours")
                time.sleep(20)

            result_url = discover_result_url(job)
            download(result_url, raw)
            tbl = Table.read(raw, format="votable")
            cols = {str(c).lower() for c in tbl.colnames}
            if not expected_cols.issubset(cols):
                raise RuntimeError(f"{name} VOTable missing required columns: {sorted(expected_cols - cols)}")
            # Normalize VOTable cells ourselves so database NULL/masked values become an
            # explicit empty CSV cell while a literal string such as flag_time="NULL"
            # remains the literal four-character value. The raw VOTable is retained too.
            from numpy import ma
            tmp_norm = norm.with_suffix(norm.suffix + ".tmp")
            with tmp_norm.open("w", encoding="utf-8", newline="") as nf:
                cw = csv.writer(nf)
                cw.writerow([str(c) for c in tbl.colnames])
                for row in tbl:
                    vals = []
                    for c in tbl.colnames:
                        v = row[c]
                        if v is ma.masked or ma.is_masked(v):
                            vals.append("")
                        elif isinstance(v, bytes):
                            vals.append(v.decode("utf-8", "replace"))
                        else:
                            vals.append(str(v))
                    cw.writerow(vals)
            tmp_norm.replace(norm)
            if not validate_normalized(norm, expected_cols):
                raise RuntimeError(f"Normalized CSV failed validation: {norm}")
            rec = {
                "status": "COMPLETE", "name": name, "query": q, "job_url": job,
                "result_url": result_url, "row_count": len(tbl),
                "raw_votable": str(raw.relative_to(ROOT)).replace("\\", "/"),
                "raw_sha256": sha256(raw), "raw_size_bytes": raw.stat().st_size,
                "normalized_csv": str(norm.relative_to(ROOT)).replace("\\", "/"),
                "normalized_sha256": sha256(norm), "normalized_size_bytes": norm.stat().st_size,
                "completed_utc": now_utc(), "attempts": attempts + [{"attempt": attempt, "status": "COMPLETE"}],
            }
            write_json(meta, rec)
            return raw, norm, rec
        except Exception as e:
            attempts.append({"attempt": attempt, "error": repr(e), "failed_utc": now_utc()})
            write_json(meta, {"status": "RETRYING", "name": name, "query": q, "attempts": attempts})
            for p in (raw, norm):
                if p.exists():
                    try:
                        p.unlink()
                    except Exception:
                        pass
            time.sleep(min(180, 15 * attempt))
    raise RuntimeError(f"Unable to acquire TAP dataset {name}")


def verify_frozen_inputs() -> None:
    if not CONTRACT.is_file():
        raise FileNotFoundError(CONTRACT)
    if sha256(CONTRACT) != EXPECTED_CONTRACT_SHA:
        raise RuntimeError("v094d contract SHA256 mismatch; refuse post-freeze mutation")
    for path, expected in EXPECTED_FROZEN_HASHES.items():
        if not path.is_file():
            raise FileNotFoundError(f"Frozen provenance input missing: {path}")
        actual = sha256(path)
        if actual != expected:
            raise RuntimeError(f"Frozen provenance input changed: {path} sha={actual} expected={expected}")


def load_old_v093_context():
    old_cache_rows = {}
    for r in iter_csv(OLD_EXPOSURE):
        eid = safe_int(r.get("exposure_id"))
        if eid is not None:
            old_cache_rows[eid] = r

    scans_by_plate = defaultdict(list)
    scan_ids_by_plate = defaultdict(set)
    for r in iter_csv(OLD_SCAN):
        pid, sid = safe_int(r.get("plate_id")), safe_int(r.get("scan_id"))
        if pid is None or sid is None:
            continue
        scans_by_plate[pid].append(r)
        scan_ids_by_plate[pid].add(sid)

    sols_by_plate = defaultdict(list)
    for r in iter_csv(OLD_SOLUTION):
        pid, sid = safe_int(r.get("plate_id")), safe_int(r.get("scan_id"))
        if pid is None or sid is None or sid not in scan_ids_by_plate.get(pid, set()):
            continue
        poly = parse_stc_polygon(r.get("stc_polygon"))
        if poly is None:
            continue
        ra, dec = safe_float(r.get("ra_icrs")), safe_float(r.get("dec_icrs"))
        if ra is None or dec is None:
            continue
        sols_by_plate[pid].append({
            "solution_id": safe_int(r.get("solution_id")), "scan_id": sid,
            "ra": ra, "dec": dec, "fov1": safe_float(r.get("fov1")), "fov2": safe_float(r.get("fov2")),
            "num_xmatch": safe_int(r.get("num_xmatch")) or 0,
        })

    if len(old_cache_rows) != 72621:
        raise RuntimeError(f"Frozen v093 exposure cache row count changed: {len(old_cache_rows)} != 72621")

    actual_registry = set()
    for r in iter_csv(OLD_REGISTRY):
        eid = safe_int(r.get("exposure_id"))
        if eid is not None:
            actual_registry.add(eid)
    return old_cache_rows, scans_by_plate, sols_by_plate, actual_registry


def reconstruct_old_status(row, scans_by_plate, sols_by_plate):
    eid, pid, aid = safe_int(row.get("exposure_id")), safe_int(row.get("plate_id")), safe_int(row.get("archive_id"))
    ra, dec = safe_float(row.get("ra_icrs")), safe_float(row.get("dec_icrs"))
    st, en = parse_dt(row.get("ut_start")), parse_dt(row.get("ut_end"))
    if None in (eid, pid, aid) or ra is None or dec is None or st is None or en is None or en <= st:
        return "V093_REJECT_TIMING_OR_CENTER_INVALID", None
    if not scans_by_plate.get(pid):
        return "V093_REJECT_NO_SCAN", None
    sols = sols_by_plate.get(pid, [])
    if not sols:
        return "V093_REJECT_NO_SOLUTION_POLYGON", None
    ranked = []
    for s in sols:
        sep = angular_sep_deg(ra, dec, s["ra"], s["dec"])
        ranked.append((sep, -s["num_xmatch"], s["solution_id"] or -1, s))
    ranked.sort(key=lambda x: (x[0], x[1], x[2]))
    sep, _, _, sol = ranked[0]
    diag = None
    if sol["fov1"] is not None and sol["fov2"] is not None:
        diag = math.hypot(sol["fov1"], sol["fov2"])
    plausible = True if diag is None else (sep <= max(1.0, 0.75 * diag))
    detail = {
        "selected_solution_id": sol["solution_id"], "selected_scan_id": sol["scan_id"],
        "separation_deg": sep, "fov_diagonal_deg": diag,
        "association_threshold_deg": None if diag is None else max(1.0, 0.75 * diag),
    }
    if not plausible:
        return "V093_REJECT_SOLUTION_ASSOCIATION_IMPLAUSIBLE", detail
    return "V093_USABLE_RECONSTRUCTED", detail


def old_query_audit(full_row):
    missing = []
    null_tokens = {"", "--", "NONE"}
    for c in ("ut_start", "ut_end", "ra_icrs", "dec_icrs"):
        v = str(full_row.get(c, "") if full_row.get(c, "") is not None else "").strip()
        if v.upper() in null_tokens:
            missing.append(c)
    return (len(missing) == 0), ("" if not missing else "OLD_QUERY_EXCLUDED_MISSING_" + "|".join(x.upper() for x in missing))


def build_complete_scan_solution_context(scan_csv: Path, solution_csv: Path):
    scans_by_plate = defaultdict(list)
    scan_ids = set()
    for r in iter_csv(scan_csv):
        pid, sid = safe_int(r.get("plate_id")), safe_int(r.get("scan_id"))
        if pid is None or sid is None:
            continue
        rec = {"scan_id": sid, "filename_scan": str(r.get("filename_scan", "") or "").strip()}
        scans_by_plate[pid].append(rec)
        scan_ids.add(sid)

    valid_solutions = defaultdict(list)
    for r in iter_csv(solution_csv):
        pid, sid = safe_int(r.get("plate_id")), safe_int(r.get("scan_id"))
        if pid is None or sid is None or sid not in scan_ids:
            continue
        poly = parse_stc_polygon(r.get("stc_polygon"))
        ra, dec = safe_float(r.get("ra_icrs")), safe_float(r.get("dec_icrs"))
        if poly is None or ra is None or dec is None:
            continue
        valid_solutions[pid].append({
            "solution_id": safe_int(r.get("solution_id")), "scan_id": sid,
            "ra": ra, "dec": dec, "num_xmatch": safe_int(r.get("num_xmatch")) or 0,
        })
    return scans_by_plate, valid_solutions


def fragment_analysis(exp_row, sub_rows):
    num_raw = str(exp_row.get("num_sub", "") if exp_row.get("num_sub", "") is not None else "").strip()
    nsub = safe_int(num_raw)
    parent_start, parent_end = parse_dt(exp_row.get("ut_start")), parse_dt(exp_row.get("ut_end"))
    parent_valid = parent_start is not None and parent_end is not None and parent_end > parent_start
    parent_duration = (parent_end - parent_start).total_seconds() if parent_valid else None
    parent_exptime = safe_float(exp_row.get("exptime"))

    base = {
        "num_sub_raw": num_raw, "num_sub": nsub, "fragment_expected_count": nsub,
        "fragment_observed_count": len(sub_rows), "fragment_ids_complete_unique": False,
        "fragment_numbers_complete_unique": False, "fragment_valid_interval_count": 0,
        "fragment_overlap_or_duplicate_anomaly": False, "fragment_outside_parent_envelope_count": 0,
        "fragment_intervals": [], "fragment_total_wall_seconds": None, "fragment_sum_exptime_seconds": None,
        "parent_interval_duration_seconds": parent_duration, "parent_exptime_seconds": parent_exptime,
        "fragment_wall_minus_parent_exptime_seconds": None, "fragment_subexptime_minus_parent_exptime_seconds": None,
        "fragment_structure_status": "TIMING_STRUCTURALLY_UNRESOLVED", "timing_intervals_supported": False,
    }

    if nsub is None or nsub < 0:
        base["fragment_structure_status"] = "TIMING_STRUCTURALLY_UNRESOLVED_NUM_SUB"
        return base

    if nsub <= 1:
        if not parent_valid:
            base["fragment_structure_status"] = "TIMING_STRUCTURALLY_UNRESOLVED_PARENT_INTERVAL"
            return base
        base["fragment_structure_status"] = "SINGLE_PARENT_INTERVAL_PROVISIONALLY_USABLE"
        base["timing_intervals_supported"] = True
        base["fragment_expected_count"] = nsub
        base["fragment_observed_count"] = len(sub_rows)
        base["fragment_intervals"] = [{
            "kind": "PARENT_PROVISIONAL_CONTINUOUS", "start_utc": parent_start.isoformat(),
            "end_utc": parent_end.isoformat(), "duration_seconds": parent_duration,
        }]
        base["fragment_valid_interval_count"] = 1
        base["fragment_total_wall_seconds"] = parent_duration
        if parent_exptime is not None:
            base["fragment_wall_minus_parent_exptime_seconds"] = parent_duration - parent_exptime
        return base

    # nsub > 1: only exposure_sub fragments define continuous intervals.
    ids = [safe_int(r.get("subexposure_id")) for r in sub_rows]
    nums = [safe_int(r.get("subexposure_num")) for r in sub_rows]
    ids_ok = len(ids) == nsub and all(x is not None for x in ids) and len(set(ids)) == len(ids)
    nums_ok = len(nums) == nsub and all(x is not None for x in nums) and len(set(nums)) == len(nums)
    base["fragment_ids_complete_unique"] = ids_ok
    base["fragment_numbers_complete_unique"] = nums_ok

    parsed = []
    sum_sub_exptime = 0.0
    all_sub_exptime = True
    invalid_interval = False
    for r in sub_rows:
        st, en = parse_dt(r.get("ut_start")), parse_dt(r.get("ut_end"))
        sx = safe_float(r.get("exptime"))
        if sx is None:
            all_sub_exptime = False
        else:
            sum_sub_exptime += sx
        if st is None or en is None or en <= st:
            invalid_interval = True
            continue
        dur = (en - st).total_seconds()
        parsed.append((st, en, safe_int(r.get("subexposure_id")), safe_int(r.get("subexposure_num")), sx, dur))
        if parent_valid and (st < parent_start or en > parent_end):
            base["fragment_outside_parent_envelope_count"] += 1

    parsed.sort(key=lambda x: (x[0], x[1], x[2] if x[2] is not None else -1))
    overlap = False
    for i in range(1, len(parsed)):
        if parsed[i][0] < parsed[i - 1][1]:
            overlap = True
            break
    base["fragment_overlap_or_duplicate_anomaly"] = overlap
    base["fragment_valid_interval_count"] = len(parsed)
    base["fragment_intervals"] = [{
        "kind": "EXPOSURE_SUB_CONTINUOUS_FRAGMENT", "subexposure_id": sid, "subexposure_num": snum,
        "start_utc": st.isoformat(), "end_utc": en.isoformat(), "duration_seconds": dur, "exptime_seconds": sx,
    } for st, en, sid, snum, sx, dur in parsed]
    base["fragment_total_wall_seconds"] = sum(x[5] for x in parsed) if parsed else 0.0
    base["fragment_sum_exptime_seconds"] = sum_sub_exptime if all_sub_exptime and len(sub_rows) > 0 else None
    if parent_exptime is not None:
        base["fragment_wall_minus_parent_exptime_seconds"] = base["fragment_total_wall_seconds"] - parent_exptime
        if base["fragment_sum_exptime_seconds"] is not None:
            base["fragment_subexptime_minus_parent_exptime_seconds"] = base["fragment_sum_exptime_seconds"] - parent_exptime

    structural_ok = (
        len(sub_rows) == nsub and ids_ok and nums_ok and not invalid_interval and len(parsed) == nsub and not overlap
    )
    if structural_ok:
        base["fragment_structure_status"] = "FRAGMENT_INTERVALS_STRUCTURALLY_COMPLETE"
        base["timing_intervals_supported"] = True
    else:
        reasons = []
        if len(sub_rows) != nsub:
            reasons.append("COUNT_MISMATCH")
        if not ids_ok:
            reasons.append("ID_INCOMPLETE_OR_DUPLICATE")
        if not nums_ok:
            reasons.append("NUMBER_INCOMPLETE_OR_DUPLICATE")
        if invalid_interval or len(parsed) != nsub:
            reasons.append("INVALID_INTERVAL")
        if overlap:
            reasons.append("OVERLAPPING_OR_DUPLICATE_INTERVALS")
        base["fragment_structure_status"] = "TIMING_STRUCTURALLY_UNRESOLVED_" + "+".join(reasons)
    return base


def timing_intervals_from_analysis(a):
    if not a["timing_intervals_supported"]:
        return []
    out = []
    for x in a["fragment_intervals"]:
        st, en = parse_dt(x.get("start_utc")), parse_dt(x.get("end_utc"))
        if st is not None and en is not None and en > st:
            out.append((st, en))
    return out


def intersections(a_intervals, b_intervals):
    segs = []
    for a0, a1 in a_intervals:
        for b0, b1 in b_intervals:
            st, en = max(a0, b0), min(a1, b1)
            if en > st:
                segs.append((st, en))
    segs.sort()
    return segs


def pair_interval_relation(a, b):
    a0, a1 = a
    b0, b1 = b
    if b1 <= a0:
        return (a0 - b1).total_seconds(), "PRECEDING"
    if b0 >= a1:
        return (b0 - a1).total_seconds(), "FOLLOWING"
    return 0.0, "OVERLAPPING"


def aggregate_control_relation(science_intervals, control_intervals):
    if not science_intervals or not control_intervals:
        return None, "UNRESOLVED", []
    rels = []
    gaps = []
    for s in science_intervals:
        for c in control_intervals:
            gap, rel = pair_interval_relation(s, c)
            gaps.append(gap)
            rels.append(rel)
    kinds = sorted(set(rels))
    relation = kinds[0] if len(kinds) == 1 else "MIXED"
    return min(gaps), relation, kinds


def confirmatory_status(fragment, explicit_warning: bool):
    if not fragment["timing_intervals_supported"]:
        return "HOLD_TIMING_STRUCTURALLY_UNRESOLVED"
    if explicit_warning:
        return "HOLD_EXPLICIT_TIME_WARNING"
    if fragment["num_sub"] is not None and fragment["num_sub"] > 1:
        return "OPPORTUNITY_TIMING_SUPPORTED_FEATURE_FRAGMENT_UNIDENTIFIED"
    return "PROVISIONAL_PARENT_INTERVAL_NO_EXPLICIT_WARNING"


def run_self_test() -> None:
    assert interpret_flag_time("")[1:] == ("NO_EXPLICIT_WARNING_EMPTY", False)
    assert interpret_flag_time("NULL")[1:] == ("NO_EXPLICIT_WARNING_LITERAL_NULL", False)
    assert interpret_flag_time("M")[2] is True
    a = [(parse_dt("1953-01-01 00:00:00"), parse_dt("1953-01-01 00:10:00"))]
    b = [(parse_dt("1953-01-01 00:05:00"), parse_dt("1953-01-01 00:15:00"))]
    seg = intersections(a, b)
    assert len(seg) == 1 and (seg[0][1] - seg[0][0]).total_seconds() == 300
    control = [
        (parse_dt("1952-12-31 23:00:00"), parse_dt("1952-12-31 23:30:00")),
        (parse_dt("1953-01-01 01:00:00"), parse_dt("1953-01-01 01:30:00")),
    ]
    _, rel, kinds = aggregate_control_relation(a, control)
    assert rel == "MIXED" and kinds == ["FOLLOWING", "PRECEDING"]
    # Exact v093 threshold semantics: a 2-degree diagonal permits <=1.5 deg, while missing FOV is not distance-rejected.
    assert max(1.0, 0.75 * math.hypot(1.2, 1.6)) == 1.5
    print("v094d self-test PASS")


def main() -> int:
    ap = argparse.ArgumentParser(description="APPLAUSE DR4 fragment-aware timing/recoverability audit v094d")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        run_self_test()
        return 0

    verify_frozen_inputs()
    log("Frozen v094d contract and v093/v093e provenance inputs verified")

    acquisitions = {}
    normalized = {}
    for name in ("exposure_full", "exposure_sub_full", "scan_full", "solution_full"):
        _, norm, rec = tap_acquire(name, QUERIES[name], EXPECTED_COLS[name])
        normalized[name] = norm
        acquisitions[name] = rec
        log(f"{name}: rows={rec['row_count']:,} sha={rec['normalized_sha256'][:16]}...")

    if acquisitions["exposure_full"]["row_count"] != 139539:
        raise RuntimeError(
            f"MASTER POPULATION HOLD: exposure_full rows={acquisitions['exposure_full']['row_count']} != frozen expected 139539"
        )

    old_cache_rows, old_scans, old_solutions, old_registry_ids = load_old_v093_context()
    if len(old_registry_ids) != 56708:
        raise RuntimeError(f"Frozen old registry membership count changed: {len(old_registry_ids)} != 56708")
    complete_scans, complete_solutions = build_complete_scan_solution_context(normalized["scan_full"], normalized["solution_full"])

    subs_by_exposure = defaultdict(list)
    for r in iter_csv(normalized["exposure_sub_full"]):
        eid = safe_int(r.get("exposure_id"))
        if eid is not None:
            subs_by_exposure[eid].append(r)

    RESULT.mkdir(parents=True, exist_ok=True)
    master_path = RESULT / "master_fragment_timing_recoverability_registry_v094d.csv"
    master_fields = [
        "exposure_id", "plate_id", "archive_id", "exposure_num", "object_name", "object_type_code",
        "ra_orig", "dec_orig", "flag_coord", "ra_icrs", "dec_icrs",
        "date_orig_start", "date_orig_end", "time_orig_start", "time_orig_end",
        "ut_start_raw", "ut_mid_raw", "ut_weighted_raw", "ut_end_raw", "jd_start", "jd_mid", "jd_weighted", "jd_end",
        "exptime", "num_sub_raw", "num_sub_parsed", "flag_time_raw", "flag_time_interpretation", "explicit_time_warning",
        "old_v093_query_predicate_pass", "old_v093_query_exclusion_reason", "in_old_v093_exposure_cache",
        "in_actual_old_v093_usable_registry", "old_v093_reconstructed_status", "old_v093_selected_solution_id",
        "old_v093_selected_solution_sep_deg", "old_v093_membership_consistent",
        "scan_count_total", "scan_count_with_filename", "valid_astrometric_solution_count",
        "missing_parent_coordinates_recoverable_from_solution", "preferred_recovery_solution_id", "preferred_recovery_solution_scan_id",
        "preferred_recovery_solution_ra_icrs", "preferred_recovery_solution_dec_icrs", "preferred_recovery_solution_num_xmatch",
        "fragment_structure_status", "fragment_expected_count", "fragment_observed_count", "fragment_ids_complete_unique",
        "fragment_numbers_complete_unique", "fragment_valid_interval_count", "fragment_overlap_or_duplicate_anomaly",
        "fragment_outside_parent_envelope_count", "fragment_intervals_json", "fragment_total_wall_seconds",
        "fragment_sum_exptime_seconds", "parent_interval_duration_seconds", "parent_exptime_seconds",
        "fragment_wall_minus_parent_exptime_seconds", "fragment_subexptime_minus_parent_exptime_seconds",
        "timing_confirmatory_status", "candidate_level_fragment_identity_claim",
    ]

    counters = Counter()
    timing_records = {}
    mismatches = []
    old_reconstructed_counts = Counter()
    flag_counts = Counter()
    fragment_counts = Counter()
    confirm_counts = Counter()

    tmp = master_path.with_suffix(".csv.tmp")
    with tmp.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=master_fields, extrasaction="ignore")
        w.writeheader()
        for idx, r in enumerate(iter_csv(normalized["exposure_full"]), 1):
            eid, pid, aid = safe_int(r.get("exposure_id")), safe_int(r.get("plate_id")), safe_int(r.get("archive_id"))
            counters["master_rows"] += 1
            raw_flag, flag_interp, explicit_warning = interpret_flag_time(r.get("flag_time"))
            flag_counts[flag_interp] += 1
            old_pass, old_excl = old_query_audit(r)
            in_old_cache = eid in old_cache_rows if eid is not None else False
            in_old_registry = eid in old_registry_ids if eid is not None else False

            old_status = "OLD_QUERY_EXCLUDED"
            old_detail = None
            if old_pass:
                replay_row = old_cache_rows.get(eid, r) if eid is not None else r
                old_status, old_detail = reconstruct_old_status(replay_row, old_scans, old_solutions)
            old_reconstructed_counts[old_status] += 1
            reconstructed_usable = old_status == "V093_USABLE_RECONSTRUCTED"
            membership_consistent = reconstructed_usable == in_old_registry
            if old_pass and not in_old_cache:
                membership_consistent = False
            if (not old_pass) and in_old_cache:
                membership_consistent = False
            if not membership_consistent and eid is not None:
                mismatches.append({
                    "exposure_id": eid, "old_query_pass": old_pass, "in_old_cache": in_old_cache,
                    "reconstructed_status": old_status, "in_actual_old_registry": in_old_registry,
                })

            scans = complete_scans.get(pid, []) if pid is not None else []
            sols = complete_solutions.get(pid, []) if pid is not None else []
            preferred = None
            if sols:
                preferred = sorted(sols, key=lambda s: (-s["num_xmatch"], s["solution_id"] if s["solution_id"] is not None else -1))[0]
            parent_ra, parent_dec = safe_float(r.get("ra_icrs")), safe_float(r.get("dec_icrs"))
            missing_parent_coords = parent_ra is None or parent_dec is None
            coord_recoverable = bool(missing_parent_coords and preferred is not None)

            frag = fragment_analysis(r, subs_by_exposure.get(eid, []))
            fragment_counts[frag["fragment_structure_status"]] += 1
            conf = confirmatory_status(frag, explicit_warning)
            confirm_counts[conf] += 1

            timing_records[eid] = {
                "exposure_id": eid, "plate_id": pid, "archive_id": aid,
                "num_sub_raw": frag["num_sub_raw"], "num_sub": frag["num_sub"],
                "flag_time_raw": raw_flag, "flag_time_interpretation": flag_interp,
                "explicit_time_warning": explicit_warning, "fragment": frag,
                "timing_confirmatory_status": conf,
            }

            out = {
                "exposure_id": eid, "plate_id": pid, "archive_id": aid, "exposure_num": r.get("exposure_num", ""),
                "object_name": r.get("object_name", ""), "object_type_code": r.get("object_type_code", ""),
                "ra_orig": r.get("ra_orig", ""), "dec_orig": r.get("dec_orig", ""), "flag_coord": r.get("flag_coord", ""),
                "ra_icrs": r.get("ra_icrs", ""), "dec_icrs": r.get("dec_icrs", ""),
                "date_orig_start": r.get("date_orig_start", ""), "date_orig_end": r.get("date_orig_end", ""),
                "time_orig_start": r.get("time_orig_start", ""), "time_orig_end": r.get("time_orig_end", ""),
                "ut_start_raw": r.get("ut_start", ""), "ut_mid_raw": r.get("ut_mid", ""),
                "ut_weighted_raw": r.get("ut_weighted", ""), "ut_end_raw": r.get("ut_end", ""),
                "jd_start": r.get("jd_start", ""), "jd_mid": r.get("jd_mid", ""), "jd_weighted": r.get("jd_weighted", ""), "jd_end": r.get("jd_end", ""),
                "exptime": r.get("exptime", ""), "num_sub_raw": frag["num_sub_raw"], "num_sub_parsed": frag["num_sub"],
                "flag_time_raw": raw_flag, "flag_time_interpretation": flag_interp, "explicit_time_warning": explicit_warning,
                "old_v093_query_predicate_pass": old_pass, "old_v093_query_exclusion_reason": old_excl,
                "in_old_v093_exposure_cache": in_old_cache, "in_actual_old_v093_usable_registry": in_old_registry,
                "old_v093_reconstructed_status": old_status,
                "old_v093_selected_solution_id": None if old_detail is None else old_detail.get("selected_solution_id"),
                "old_v093_selected_solution_sep_deg": None if old_detail is None else old_detail.get("separation_deg"),
                "old_v093_membership_consistent": membership_consistent,
                "scan_count_total": len(scans), "scan_count_with_filename": sum(1 for s in scans if s["filename_scan"]),
                "valid_astrometric_solution_count": len(sols), "missing_parent_coordinates_recoverable_from_solution": coord_recoverable,
                "preferred_recovery_solution_id": None if preferred is None else preferred["solution_id"],
                "preferred_recovery_solution_scan_id": None if preferred is None else preferred["scan_id"],
                "preferred_recovery_solution_ra_icrs": None if preferred is None else preferred["ra"],
                "preferred_recovery_solution_dec_icrs": None if preferred is None else preferred["dec"],
                "preferred_recovery_solution_num_xmatch": None if preferred is None else preferred["num_xmatch"],
                "fragment_structure_status": frag["fragment_structure_status"], "fragment_expected_count": frag["fragment_expected_count"],
                "fragment_observed_count": frag["fragment_observed_count"], "fragment_ids_complete_unique": frag["fragment_ids_complete_unique"],
                "fragment_numbers_complete_unique": frag["fragment_numbers_complete_unique"],
                "fragment_valid_interval_count": frag["fragment_valid_interval_count"],
                "fragment_overlap_or_duplicate_anomaly": frag["fragment_overlap_or_duplicate_anomaly"],
                "fragment_outside_parent_envelope_count": frag["fragment_outside_parent_envelope_count"],
                "fragment_intervals_json": json.dumps(frag["fragment_intervals"], separators=(",", ":"), sort_keys=True),
                "fragment_total_wall_seconds": frag["fragment_total_wall_seconds"], "fragment_sum_exptime_seconds": frag["fragment_sum_exptime_seconds"],
                "parent_interval_duration_seconds": frag["parent_interval_duration_seconds"], "parent_exptime_seconds": frag["parent_exptime_seconds"],
                "fragment_wall_minus_parent_exptime_seconds": frag["fragment_wall_minus_parent_exptime_seconds"],
                "fragment_subexptime_minus_parent_exptime_seconds": frag["fragment_subexptime_minus_parent_exptime_seconds"],
                "timing_confirmatory_status": conf,
                "candidate_level_fragment_identity_claim": "FORBIDDEN_NOT_INFERRED_FROM_INTEGRATED_PLATE",
            }
            w.writerow(out)
            if idx % 25000 == 0:
                log(f"Master registry: {idx:,}/139,539 exposures")
    tmp.replace(master_path)

    # Reconstruct the exact legacy v094b/v094c 784 directed triplet selection without reading v094c candidates.
    opp = {r["canonical_pair"]: r for r in iter_csv(V093E_OPP)}
    controls = []
    selection_holds = Counter()
    for c in iter_csv(V093E_COMP):
        if c.get("tier") != "A_LE30MIN":
            continue
        if not bval(c.get("primary_common_coverage_ge50pct")):
            continue
        if not bval(c.get("same_site_control")):
            continue
        o = opp.get(c.get("canonical_pair", ""))
        if o is None:
            selection_holds["missing_opportunity"] += 1
            continue
        sep = safe_float(o.get("corrected_site_separation_km"))
        if sep is None or sep < 100.0:
            selection_holds["site_lt100km_or_missing"] += 1
            continue
        ep = c.get("comparison_for_endpoint")
        if ep == "A":
            p_plate, q_plate = safe_int(o.get("plate_a")), safe_int(o.get("plate_b"))
            p_exp, q_exp = safe_int(o.get("exposure_a")), safe_int(o.get("exposure_b"))
            p_num, q_num = safe_int(o.get("plate_numexp_a")), safe_int(o.get("plate_numexp_b"))
        elif ep == "B":
            p_plate, q_plate = safe_int(o.get("plate_b")), safe_int(o.get("plate_a"))
            p_exp, q_exp = safe_int(o.get("exposure_b")), safe_int(o.get("exposure_a"))
            p_num, q_num = safe_int(o.get("plate_numexp_b")), safe_int(o.get("plate_numexp_a"))
        else:
            selection_holds["bad_endpoint_label"] += 1
            continue
        c_plate, c_exp, c_num = safe_int(c.get("comparison_plate_id")), safe_int(c.get("comparison_exposure_id")), safe_int(c.get("comparison_plate_numexp"))
        if None in (p_plate, q_plate, c_plate, p_exp, q_exp, c_exp):
            selection_holds["identity_missing"] += 1
            continue
        if not (p_num == 1 and q_num == 1 and c_num == 1):
            selection_holds["multi_exposure_triplet"] += 1
            continue
        controls.append({
            "canonical_pair": c["canonical_pair"], "endpoint": ep,
            "positive_plate": p_plate, "independent_plate": q_plate, "control_plate": c_plate,
            "positive_exposure": p_exp, "independent_exposure": q_exp, "control_exposure": c_exp,
            "legacy_gap_minutes": safe_float(c.get("endpoint_interval_gap_minutes")),
            "legacy_temporal_relation": c.get("temporal_relation"), "site_separation_km": sep,
            "legacy_science_overlap_start_utc": o.get("physical_overlap_start_utc"),
            "legacy_science_overlap_end_utc": o.get("physical_overlap_end_utc"),
        })
    unique = {}
    for r in controls:
        k = (r["positive_plate"], r["independent_plate"], r["control_plate"])
        if k not in unique or ((r["legacy_gap_minutes"] if r["legacy_gap_minutes"] is not None else 1e99) <
                               (unique[k]["legacy_gap_minutes"] if unique[k]["legacy_gap_minutes"] is not None else 1e99)):
            unique[k] = r
    triplets = list(unique.values())
    if len(controls) != 784 or len(triplets) != 784:
        raise RuntimeError(f"LEGACY POPULATION HOLD: controls={len(controls)} triplets={len(triplets)} expected 784/784")

    legacy_path = RESULT / "legacy_784_fragment_timing_impact_v094d.csv"
    legacy_fields = [
        "legacy_triplet_index", "canonical_pair", "positive_exposure", "independent_exposure", "control_exposure",
        "positive_num_sub_raw", "independent_num_sub_raw", "control_num_sub_raw",
        "positive_flag_time_raw", "independent_flag_time_raw", "control_flag_time_raw",
        "positive_flag_interpretation", "independent_flag_interpretation", "control_flag_interpretation",
        "positive_fragment_structure_status", "independent_fragment_structure_status", "control_fragment_structure_status",
        "science_fragment_intersections_json", "science_fragment_intersection_count", "science_total_intersection_seconds",
        "control_fragment_minimum_gap_seconds", "control_fragment_minimum_gap_minutes", "control_fragment_relation",
        "control_fragment_pair_relation_kinds_json", "legacy_gap_minutes", "legacy_temporal_relation",
        "timing_impact_class", "candidate_level_fragment_identity_claim",
    ]
    class_counts = Counter()
    any_multisub_triplets = 0
    science_multisub_triplets = 0
    affected_science_pairs = set()
    tmp = legacy_path.with_suffix(".csv.tmp")
    with tmp.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=legacy_fields)
        w.writeheader()
        for i, tr in enumerate(triplets, 1):
            p = timing_records.get(tr["positive_exposure"])
            q = timing_records.get(tr["independent_exposure"])
            c = timing_records.get(tr["control_exposure"])
            if p is None or q is None or c is None:
                raise RuntimeError(f"Legacy triplet references exposure absent from master registry at index {i}")
            roles = [p, q, c]
            any_multi = any(x["num_sub"] is not None and x["num_sub"] > 1 for x in roles)
            science_multi = any(x["num_sub"] is not None and x["num_sub"] > 1 for x in (p, q))
            if any_multi:
                any_multisub_triplets += 1
            if science_multi:
                science_multisub_triplets += 1
                affected_science_pairs.add(tr["canonical_pair"])

            p_int = timing_intervals_from_analysis(p["fragment"])
            q_int = timing_intervals_from_analysis(q["fragment"])
            c_int = timing_intervals_from_analysis(c["fragment"])
            segs = intersections(p_int, q_int) if p_int and q_int else []
            total_overlap = sum((en - st).total_seconds() for st, en in segs)
            control_gap, control_rel, control_kinds = aggregate_control_relation(p_int, c_int)

            unresolved = any(not x["fragment"]["timing_intervals_supported"] for x in roles)
            warning = any(x["explicit_time_warning"] for x in roles)
            if unresolved:
                cls = "HOLD_TIMING_STRUCTURALLY_UNRESOLVED"
            elif warning:
                cls = "HOLD_EXPLICIT_TIME_WARNING"
            elif not segs:
                cls = "HOLD_NO_FRAGMENT_LEVEL_SCIENCE_OVERLAP"
            elif control_rel == "MIXED":
                cls = "HOLD_CONTROL_FRAGMENT_RELATION_MIXED"
            elif control_rel == "OVERLAPPING":
                cls = "HOLD_CONTROL_OVERLAPS_SCIENCE"
            elif control_gap is None:
                cls = "HOLD_CONTROL_TIMING_UNRESOLVED"
            elif control_gap > 1800.0:
                cls = "HOLD_CONTROL_NO_LONGER_TIER_A"
            else:
                cls = "KEEP_LEGACY_TRIPLET_TIMING_SUPPORTED"
            class_counts[cls] += 1

            w.writerow({
                "legacy_triplet_index": i, "canonical_pair": tr["canonical_pair"],
                "positive_exposure": p["exposure_id"], "independent_exposure": q["exposure_id"], "control_exposure": c["exposure_id"],
                "positive_num_sub_raw": p["num_sub_raw"], "independent_num_sub_raw": q["num_sub_raw"], "control_num_sub_raw": c["num_sub_raw"],
                "positive_flag_time_raw": p["flag_time_raw"], "independent_flag_time_raw": q["flag_time_raw"], "control_flag_time_raw": c["flag_time_raw"],
                "positive_flag_interpretation": p["flag_time_interpretation"], "independent_flag_interpretation": q["flag_time_interpretation"], "control_flag_interpretation": c["flag_time_interpretation"],
                "positive_fragment_structure_status": p["fragment"]["fragment_structure_status"],
                "independent_fragment_structure_status": q["fragment"]["fragment_structure_status"],
                "control_fragment_structure_status": c["fragment"]["fragment_structure_status"],
                "science_fragment_intersections_json": json.dumps([
                    {"start_utc": st.isoformat(), "end_utc": en.isoformat(), "duration_seconds": (en - st).total_seconds()}
                    for st, en in segs
                ], separators=(",", ":"), sort_keys=True),
                "science_fragment_intersection_count": len(segs), "science_total_intersection_seconds": total_overlap,
                "control_fragment_minimum_gap_seconds": control_gap,
                "control_fragment_minimum_gap_minutes": None if control_gap is None else control_gap / 60.0,
                "control_fragment_relation": control_rel,
                "control_fragment_pair_relation_kinds_json": json.dumps(control_kinds, separators=(",", ":")),
                "legacy_gap_minutes": tr["legacy_gap_minutes"], "legacy_temporal_relation": tr["legacy_temporal_relation"],
                "timing_impact_class": cls,
                "candidate_level_fragment_identity_claim": "FORBIDDEN_NOT_INFERRED_FROM_INTEGRATED_PLATE",
            })
    tmp.replace(legacy_path)

    exposure_4969 = timing_records.get(4969)
    mismatch_path = STATE / "v093_registry_reconstruction_mismatches_v094d.json"
    write_json(mismatch_path, {"count": len(mismatches), "mismatches": mismatches})

    report = {
        "status": "COMPLETE",
        "analysis_kind": "applause_dr4_fragment_timing_recoverability_audit_v094d",
        "completed_utc": now_utc(),
        "contract_sha256": EXPECTED_CONTRACT_SHA,
        "guards": {
            "candidate_csv_reads": 0, "candidate_disposition_changes": 0, "source_calib_queries": 0,
            "pixel_or_fits_reads": 0, "detector_runs": 0, "corrected_branch_population_construction": 0,
            "individual_candidate_inspection": 0,
        },
        "tap_acquisitions": acquisitions,
        "master_registry": {
            "exposure_rows": counters["master_rows"],
            "expected_exposure_rows": 139539,
            "exposure_sub_rows_observed": acquisitions["exposure_sub_full"]["row_count"],
            "exposure_sub_reference_count_at_freeze_diagnostic_only": 2507,
            "flag_time_interpretation_counts": dict(flag_counts),
            "fragment_structure_status_counts": dict(fragment_counts),
            "timing_confirmatory_status_counts": dict(confirm_counts),
            "old_v093_reconstructed_status_counts": dict(old_reconstructed_counts),
            "actual_old_v093_registry_count": len(old_registry_ids),
            "v093_registry_membership_consistency_mismatch_count": len(mismatches),
            "v093_registry_membership_consistency": "PASS" if not mismatches else "MISMATCH_REPORTED_NOT_FORCED",
            "mismatch_detail_path": str(mismatch_path.relative_to(ROOT)).replace("\\", "/"),
            "scan_solution_coordinates_used_as_parent_coordinate_replacements": 0,
        },
        "legacy_784_impact": {
            "legacy_selection_rows_before_physical_triplet_dedup": len(controls),
            "legacy_directed_triplets": len(triplets),
            "selection_holds": dict(selection_holds),
            "timing_impact_class_counts": dict(class_counts),
            "observed_triplets_any_num_sub_gt1": any_multisub_triplets,
            "observed_triplets_science_num_sub_gt1": science_multisub_triplets,
            "observed_unique_science_pairs_affected": len(affected_science_pairs),
            "astra_claim_comparison": {
                "claimed_triplets_any_num_sub_gt1": 51,
                "observed_triplets_any_num_sub_gt1": any_multisub_triplets,
                "matches_claim": any_multisub_triplets == 51,
                "claimed_triplets_science_num_sub_gt1": 49,
                "observed_triplets_science_num_sub_gt1": science_multisub_triplets,
                "matches_science_claim": science_multisub_triplets == 49,
                "claimed_unique_science_pairs_affected": 34,
                "observed_unique_science_pairs_affected": len(affected_science_pairs),
                "matches_unique_pair_claim": len(affected_science_pairs) == 34,
            },
            "exposure_4969_audit": None if exposure_4969 is None else {
                "present_in_master_registry": True,
                "num_sub_raw": exposure_4969["num_sub_raw"],
                "num_sub_parsed": exposure_4969["num_sub"],
                "flag_time_raw": exposure_4969["flag_time_raw"],
                "flag_time_interpretation": exposure_4969["flag_time_interpretation"],
                "fragment_structure_status": exposure_4969["fragment"]["fragment_structure_status"],
                "fragment_intervals": exposure_4969["fragment"]["fragment_intervals"],
                "timing_confirmatory_status": exposure_4969["timing_confirmatory_status"],
                "candidate_level_fragment_identity_inferred": False,
            },
        },
        "interpretive_boundary": (
            "Fragment timing can support or invalidate observing-opportunity timing. It does not identify which fragment produced "
            "a feature on an integrated photographic plate and does not itself validate any v094c catalogue candidate."
        ),
        "no_corrected_science_population_constructed": True,
        "outputs": {},
    }

    report_path = RESULT / "applause_dr4_fragment_timing_recoverability_audit_v094d.json"
    report["outputs"] = {
        master_path.name: {"sha256": sha256(master_path), "size_bytes": master_path.stat().st_size},
        legacy_path.name: {"sha256": sha256(legacy_path), "size_bytes": legacy_path.stat().st_size},
    }
    write_json(report_path, report)

    manifest_path = RESULT / "v094d_output_manifest.sha256"
    manifest_path.write_text(
        "\n".join([
            f"{sha256(master_path)}  {master_path.name}",
            f"{sha256(legacy_path)}  {legacy_path.name}",
            f"{sha256(report_path)}  {report_path.name}",
        ]) + "\n", encoding="ascii"
    )

    log("")
    log("v094d MASTER FRAGMENT TIMING / RECOVERABILITY AUDIT COMPLETE")
    log(f"Master exposure rows: {counters['master_rows']:,}")
    log(f"exposure_sub rows observed: {acquisitions['exposure_sub_full']['row_count']:,}")
    log(f"v093 reconstruction mismatches: {len(mismatches):,}")
    log(f"Legacy directed triplets audited: {len(triplets):,}")
    log(f"Legacy timing-impact classes: {dict(class_counts)}")
    log(f"Any num_sub>1 triplets: {any_multisub_triplets}; science-affected: {science_multisub_triplets}; unique science pairs: {len(affected_science_pairs)}")
    log("STOP: no corrected branch population, registration, source matching, pixels, detector, or candidate inspection performed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
