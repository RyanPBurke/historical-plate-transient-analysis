from __future__ import annotations

from pathlib import Path
import csv
import datetime as dt
import hashlib
import json
import math
import re
import urllib.error
import urllib.request

from transient_pipeline.poss1 import load_vi25_records, vi25_start_utc
from transient_pipeline.poss1_skyview import (
    parse_skyview_descriptor,
    raw_plate_directory,
    hhh_identity,
    expected_region_for_vi25,
)

ROOT = Path.cwd()
QUEUE = ROOT / "results" / "wide_census_physical_timing_queue_v048.csv"
AUDIT = ROOT / "results" / "census_scope_audit_v048.json"
APPLAUSE = ROOT / "research" / "census_inputs" / "applause_exposures_1951_1955.csv"
POSS_META = ROOT / "research" / "census_inputs" / "poss1_plate_metadata.csv"
POLICY = ROOT / "config" / "candidate_adjudication_policy_v002.json"

OUT_DIR = ROOT / "results" / "wide_census_physical_timing_v049"
CACHE = OUT_DIR / "cache"
CHECKPOINT = OUT_DIR / "checkpoint_v049.json"
OUT_JSON = ROOT / "results" / "wide_census_physical_timing_v049.json"
OUT_CSV = ROOT / "results" / "wide_census_physical_timing_v049.csv"
SURVIVOR_CSV = ROOT / "results" / "wide_census_timing_survivors_for_footprint_v049.csv"

EXPECTED_QUEUE_ROWS = 111
EXPECTED_APPLAUSE_SHA = "12a470623b6e59dbf42e7a2e699cf55127105fb322208c890a00f68d30b991b8"
EXPECTED_POSS_SHA = "41b5732086f5a1d17e6f6d85c99f97a48a0985f19db1ad496cd3e3a2387830c1"
EXPECTED_POLICY_ID = "candidate_adjudication_policy_v002"
EXPECTED_COUNTS = {"APPLAUSE": 96, "POSS": 18, "DASCH": 42}

DSS_DESCRIPTOR = {
    "E": "https://skyview.gsfc.nasa.gov/current/jar/surveys/xml/dss1r.xml.gz",
    "O": "https://skyview.gsfc.nasa.gov/current/jar/surveys/xml/dss1b.xml.gz",
}
DASCH_API = "https://api.starglass.cfa.harvard.edu/public/dasch/dr7/mosaic_package"
UA = "historical-transient-pipeline/wide-census-v049"
REMOTE_BATCH = 12
MAX_TRANSPORT_ATTEMPTS = 4
DASCH_EXPOSURE_IDENTITY_MIDPOINT_TOLERANCE_S = 300.0
DASCH_AMBIGUITY_MARGIN_S = 60.0


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as fh:
        return list(csv.DictReader(fh))


def write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    tmp.replace(path)


def load_json(path: Path, default=None):
    if not path.is_file():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def parse_time(value) -> dt.datetime:
    s = str(value).strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    x = dt.datetime.fromisoformat(s)
    if x.tzinfo is None:
        x = x.replace(tzinfo=dt.timezone.utc)
    return x.astimezone(dt.timezone.utc)


def maybe_time(value):
    try:
        if value is None or not str(value).strip() or str(value).strip().lower() == "nan":
            return None
        return parse_time(value)
    except Exception:
        return None


def fnum(value):
    try:
        if value is None or not str(value).strip() or str(value).strip().lower() == "nan":
            return None
        x = float(value)
        return x if math.isfinite(x) else None
    except Exception:
        return None


def interval_overlap(a0, a1, b0, b1):
    start = max(a0, b0)
    end = min(a1, b1)
    return start, end, max(0.0, (end - start).total_seconds())


def conservative_overlap(a0, a1, b0, b1, ua_s, ub_s):
    vals = []
    for sa in (-ua_s, ua_s):
        for sb in (-ub_s, ub_s):
            _, _, sec = interval_overlap(
                a0 + dt.timedelta(seconds=sa),
                a1 + dt.timedelta(seconds=sa),
                b0 + dt.timedelta(seconds=sb),
                b1 + dt.timedelta(seconds=sb),
            )
            vals.append(sec)
    return min(vals)


def get_bytes(url: str, accept="*/*"):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": accept})
    with urllib.request.urlopen(req, timeout=90) as response:
        return response.read(), getattr(response, "status", None), response.geturl()


def post_json(url: str, payload: dict):
    raw = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=raw,
        method="POST",
        headers={"User-Agent": UA, "Accept": "application/json", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=90) as response:
        return json.loads(response.read().decode("utf-8")), getattr(response, "status", None), response.geturl()


def source_kind(exposure: str) -> str:
    s = str(exposure)
    if s.startswith("APPLAUSE:"):
        return "APPLAUSE"
    if s.startswith("POSS-I:"):
        return "POSS"
    if "DASCH:" in s or "/dasch/q/" in s:
        return "DASCH"
    return "UNKNOWN"


def parse_poss_exposure(exposure: str):
    m = re.fullmatch(r"POSS-I:(\d+):([EO]):rec(\d+)", str(exposure).strip(), re.I)
    if not m:
        return None
    return int(m.group(1)), m.group(2).upper(), int(m.group(3))


def parse_dasch_plate(exposure: str):
    m = re.search(r"/q/([a-z]+\d+)$", str(exposure), re.I)
    if not m:
        m = re.search(r"([a-z]+\d+)$", str(exposure), re.I)
    return m.group(1).lower() if m else None


def applause_map():
    if sha256_file(APPLAUSE) != EXPECTED_APPLAUSE_SHA:
        raise RuntimeError("REFUSING: APPLAUSE pinned source hash changed")
    rows = read_csv(APPLAUSE)
    out = {}
    for row in rows:
        try:
            eid = int(float(row["exposure_id"]))
        except Exception:
            continue
        out[eid] = row
    return out


def resolve_applause(exposure: str, amap):
    eid = int(exposure.split(":")[1])
    row = amap.get(eid)
    if row is None:
        return {"status": "UNRESOLVED_APPLAUSE_ID", "exposure": exposure}

    start = maybe_time(row.get("obs_start_utc") or row.get("ut_start"))
    end = maybe_time(row.get("obs_end_utc") or row.get("ut_end"))
    if start is None or end is None or end <= start:
        return {"status": "UNRESOLVED_APPLAUSE_TIME", "exposure": exposure}

    flag = str(row.get("flag_time", "")).strip()
    if flag.lower() == "nan":
        flag = ""
    reported = fnum(row.get("exptime"))
    duration = (end - start).total_seconds()

    return {
        "status": "RESOLVED",
        "kind": "APPLAUSE",
        "exposure": exposure,
        "archive_id": str(row.get("archive_id", "")).strip(),
        "plate_id": str(row.get("plate_id", "")).strip(),
        "physical_plate_key": f"APPLAUSE:{str(row.get('archive_id','')).strip()}:{str(row.get('plate_id','')).strip()}",
        "start_utc": start.isoformat(),
        "end_utc": end.isoformat(),
        "duration_s": duration,
        "timing_basis": "APPLAUSE_DR4_UT_START_END",
        "timing_quality": "ARCHIVE_CALIBRATED_UT_UNFLAGGED" if not flag else "ARCHIVE_CALIBRATED_UT_FLAGGED",
        "formal_time_accuracy_s": None,
        "flag_time": flag,
        "reported_exptime_s": reported,
        "ut_interval_minus_reported_exptime_s": duration - reported if reported is not None else None,
        "physical_object_semantics": "APPLAUSE_DR4_plate_id_used_as_physical_plate_identity",
    }


def descriptor_cache_path(band: str):
    return CACHE / f"skyview_dss1_{band.lower()}_descriptor.xml"


def poss_cache_path(exposure: str):
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", exposure)
    return CACHE / "poss" / f"{safe}.json"


def dasch_cache_path(plate: str):
    return CACHE / "dasch" / f"{plate}.json"


def fetch_descriptor(band: str):
    path = descriptor_cache_path(band)
    if path.is_file():
        return parse_skyview_descriptor(path.read_bytes())
    raw, status, final_url = get_bytes(DSS_DESCRIPTOR[band], "application/xml,*/*")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    write_json(
        path.with_suffix(".meta.json"),
        {"http_status": status, "final_url": final_url, "sha256": hashlib.sha256(raw).hexdigest()},
    )
    return parse_skyview_descriptor(raw)


def resolve_poss_remote(exposure: str, records, descriptors):
    parsed = parse_poss_exposure(exposure)
    if parsed is None:
        return {"status": "UNRESOLVED_POSS_EXPOSURE_ID", "exposure": exposure}
    poss_number, band, recno = parsed
    record = records.get(recno)
    if record is None:
        return {"status": "UNRESOLVED_POSS_VI25_RECNO", "exposure": exposure, "recno": recno}
    if str(record.poss).strip() != str(poss_number):
        return {
            "status": "UNRESOLVED_POSS_VI25_POSS_NUMBER_MISMATCH",
            "exposure": exposure,
            "recno": recno,
            "vi25_poss": str(record.poss),
        }

    start = vi25_start_utc(record, band)
    duration_min = record.eexp_min if band == "E" else record.oexp_min
    if duration_min is None or float(duration_min) <= 0:
        return {"status": "UNRESOLVED_POSS_VI25_DURATION", "exposure": exposure}
    end = start + dt.timedelta(minutes=float(duration_min))

    region = expected_region_for_vi25(record, band).upper()
    matches = [x for x in descriptors[band].images if Path(x.path).name.upper() == region]
    if len(matches) != 1:
        return {
            "status": "UNRESOLVED_POSS_DESCRIPTOR_REGION",
            "exposure": exposure,
            "expected_region": region,
            "descriptor_matches": len(matches),
        }
    entry = matches[0]
    raw_dir = raw_plate_directory(band=band, region=region, descriptor_entry=entry)
    hhh_url = f"{raw_dir}/{region.lower()}.hhh"
    try:
        raw, http_status, final_url = get_bytes(hhh_url, "application/octet-stream,*/*")
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return {
                "status": "UNRESOLVED_POSS_RAW_HHH_ARCHIVE_UNAVAILABLE",
                "exposure": exposure,
                "expected_region": region,
                "http_status": 404,
            }
        raise

    ident = hhh_identity(raw)
    if str(ident.get("region", "")).strip().upper() != region:
        return {"status": "UNRESOLVED_POSS_HHH_REGION", "exposure": exposure, "expected_region": region}
    if not ident.get("plate_id"):
        return {"status": "UNRESOLVED_POSS_HHH_PLATE_ID", "exposure": exposure, "expected_region": region}

    # HHH clock is NOT a timing authority.  It is only an identity/date cross-check.
    hhh_date = str(ident.get("date_obs", ""))[:10]
    allowed_dates = {str(record.obs).strip(), start.date().isoformat()}
    if hhh_date and hhh_date not in allowed_dates:
        return {
            "status": "UNRESOLVED_POSS_HHH_DATE_IDENTITY",
            "exposure": exposure,
            "expected_region": region,
            "hhh_date": hhh_date,
            "allowed_dates": sorted(allowed_dates),
        }

    return {
        "status": "RESOLVED",
        "kind": "POSS",
        "exposure": exposure,
        "poss_number": poss_number,
        "band": band,
        "vi25_recno": recno,
        "region": region,
        "hhh_plate_id": ident.get("plate_id"),
        "physical_plate_key": f"POSS:{band}:{region}:{ident.get('plate_id')}",
        "start_utc": start.isoformat(),
        "end_utc": end.isoformat(),
        "duration_s": float(duration_min) * 60.0,
        "timing_basis": "AUTHORITATIVE_VI25_NORMALIZED_UTC_PLUS_VI25_BAND_DURATION",
        "timing_quality": "VI25_NORMALIZED_PST_UTC",
        "formal_time_accuracy_s": None,
        "hhh_clock_used_for_timing": False,
        "hhh_date_identity_only": True,
        "hhh_date": hhh_date,
        "allowed_hhh_dates": sorted(allowed_dates),
        "hhh_url": hhh_url,
        "hhh_final_url": final_url,
        "hhh_http_status": http_status,
        "hhh_sha256": hashlib.sha256(raw).hexdigest(),
    }


def resolve_dasch_plate_remote(plate: str):
    payload, status, final_url = post_json(DASCH_API, {"plate_id": plate, "binning": 1})
    exposures = (((payload.get("metadata") or {}).get("astrometry") or {}).get("exposures") or [])
    rows = []
    for exp in exposures:
        if not exp.get("midpointDate") or exp.get("durMin") is None:
            continue
        midpoint = parse_time(exp["midpointDate"])
        duration_s = float(exp["durMin"]) * 60.0
        half = dt.timedelta(seconds=duration_s / 2.0)
        accuracy_days = fnum(exp.get("dateAccDays"))
        rows.append({
            "number": exp.get("number"),
            "start_utc": (midpoint - half).isoformat(),
            "end_utc": (midpoint + half).isoformat(),
            "midpoint_utc": midpoint.isoformat(),
            "duration_s": duration_s,
            "date_source": exp.get("dateSource"),
            "formal_time_accuracy_s": accuracy_days * 86400.0 if accuracy_days is not None else None,
        })
    return {
        "status": "RESOLVED" if rows else "UNRESOLVED_DASCH_NO_TIMED_EXPOSURES",
        "kind": "DASCH_PLATE",
        "plate_id": plate,
        "physical_plate_key": f"DASCH:{plate}",
        "package_http_status": status,
        "package_final_url": final_url,
        "exposures": rows,
    }


def choose_dasch_exposure(side: dict, plate_result: dict):
    if plate_result.get("status") != "RESOLVED":
        return {
            "status": plate_result.get("status", "UNRESOLVED_DASCH_PLATE"),
            "kind": "DASCH",
            "plate_id": plate_result.get("plate_id"),
        }

    catalog_start = parse_time(side["catalog_start"])
    catalog_end = parse_time(side["catalog_end"])
    catalog_mid = catalog_start + (catalog_end - catalog_start) / 2
    catalog_duration_s = (catalog_end - catalog_start).total_seconds()

    ranked = []
    for exp in plate_result["exposures"]:
        midpoint = parse_time(exp["midpoint_utc"])
        ranked.append((
            abs((midpoint - catalog_mid).total_seconds()),
            abs(float(exp["duration_s"]) - catalog_duration_s),
            exp,
        ))
    ranked.sort(key=lambda x: (x[0], x[1], str(x[2].get("number"))))

    if not ranked or ranked[0][0] > DASCH_EXPOSURE_IDENTITY_MIDPOINT_TOLERANCE_S:
        return {
            "status": "UNRESOLVED_DASCH_EXPOSURE_IDENTITY",
            "kind": "DASCH",
            "plate_id": plate_result["plate_id"],
            "closest_midpoint_delta_s": ranked[0][0] if ranked else None,
        }
    if len(ranked) > 1 and ranked[1][0] - ranked[0][0] <= DASCH_AMBIGUITY_MARGIN_S:
        return {
            "status": "UNRESOLVED_DASCH_EXPOSURE_AMBIGUOUS",
            "kind": "DASCH",
            "plate_id": plate_result["plate_id"],
            "best_midpoint_delta_s": ranked[0][0],
            "second_midpoint_delta_s": ranked[1][0],
        }

    midpoint_delta_s, duration_delta_s, exp = ranked[0]
    out = dict(exp)
    out.update({
        "status": "RESOLVED",
        "kind": "DASCH",
        "plate_id": plate_result["plate_id"],
        "physical_plate_key": plate_result["physical_plate_key"],
        "timing_basis": "DASCH_DR7_ASTROMETRY_EXPOSURE_METADATA",
        "timing_quality": "DASCH_LOGBOOK" if str(exp.get("date_source", "")).lower() == "logbook" else "DASCH_ARCHIVE_METADATA",
        "catalog_midpoint_match_delta_s": midpoint_delta_s,
        "catalog_duration_match_delta_s": duration_delta_s,
    })
    return out


def checkpoint_default():
    return {"status": "IN_PROGRESS", "attempts": {}, "terminal_transport": {}, "last_error": None}


def mark_transport(cp: dict, key: str, exc: Exception):
    attempt = int(cp["attempts"].get(key, 0)) + 1
    cp["attempts"][key] = attempt
    rec = {"key": key, "attempt": attempt, "type": type(exc).__name__, "message": str(exc)}
    cp["last_error"] = rec
    if attempt >= MAX_TRANSPORT_ATTEMPTS:
        cp["terminal_transport"][key] = rec
    write_json(CHECKPOINT, cp)
    return attempt


def side_from_row(row: dict, suffix: str):
    return {
        "exposure": row[f"exposure_{suffix}"],
        "archive": row[f"archive_{suffix}"],
        "catalog_start": row[f"catalog_start_{suffix}_utc"],
        "catalog_end": row[f"catalog_end_{suffix}_utc"],
    }


def resolve_final_side(side, amap, poss_results, dasch_results):
    kind = source_kind(side["exposure"])
    if kind == "APPLAUSE":
        return resolve_applause(side["exposure"], amap)
    if kind == "POSS":
        return poss_results.get(side["exposure"], {"status": "UNRESOLVED_POSS_CACHE_MISSING"})
    if kind == "DASCH":
        plate = parse_dasch_plate(side["exposure"])
        return choose_dasch_exposure(
            side,
            dasch_results.get(plate, {"status": "UNRESOLVED_DASCH_CACHE_MISSING", "plate_id": plate}),
        )
    return {"status": "UNRESOLVED_UNKNOWN_ARCHIVE", "exposure": side["exposure"]}


def evaluate_pair(row, a, b):
    out = {
        "timing_validation_priority": int(row["timing_validation_priority"]),
        "current_time_gate": row["current_time_gate"],
        "canonical_pair": row["canonical_pair"],
        "exposure_a": row["exposure_a"],
        "archive_a": row["archive_a"],
        "exposure_b": row["exposure_b"],
        "archive_b": row["archive_b"],
        "side_a": a,
        "side_b": b,
    }
    if a.get("status") != "RESOLVED" or b.get("status") != "RESOLVED":
        out.update({"classification": "UNRESOLVED_TIMING_OR_IDENTITY", "timing_survivor": False, "science_eligible": False})
        return out
    if a.get("physical_plate_key") == b.get("physical_plate_key"):
        out.update({"classification": "NOT_INDEPENDENT_SAME_PHYSICAL_PLATE", "timing_survivor": False, "science_eligible": False})
        return out

    a0, a1 = parse_time(a["start_utc"]), parse_time(a["end_utc"])
    b0, b1 = parse_time(b["start_utc"]), parse_time(b["end_utc"])
    overlap_start, overlap_end, nominal = interval_overlap(a0, a1, b0, b1)
    ua = a.get("formal_time_accuracy_s")
    ub = b.get("formal_time_accuracy_s")
    ua_known = float(ua) if ua is not None else 0.0
    ub_known = float(ub) if ub is not None else 0.0
    conservative = conservative_overlap(a0, a1, b0, b1, ua_known, ub_known)
    formal_complete = ua is not None and ub is not None

    if nominal <= 0:
        classification = "NO_ARCHIVE_SUPPORTED_TIME_OVERLAP"
        survivor = False
    elif (ua is not None or ub is not None) and conservative <= 0:
        classification = "TIMING_OVERLAP_FRAGILE_TO_DOCUMENTED_UNCERTAINTY"
        survivor = False
    elif formal_complete:
        classification = "TIMING_OVERLAP_SURVIVES_CONSERVATIVE"
        survivor = True
    else:
        classification = "TIMING_OVERLAP_SURVIVES_ARCHIVE_SUPPORTED_NO_COMPLETE_FORMAL_UNCERTAINTY"
        survivor = True

    out.update({
        "classification": classification,
        "timing_survivor": survivor,
        "science_eligible": False,
        "physical_overlap_start_utc": overlap_start.isoformat() if nominal > 0 else "",
        "physical_overlap_end_utc": overlap_end.isoformat() if nominal > 0 else "",
        "physical_overlap_s": nominal,
        "conservative_overlap_known_uncertainties_s": conservative,
        "formal_time_uncertainty_available_both": formal_complete,
        "next_gate": "TRUE_FOOTPRINT_AND_REMAINING_PROVENANCE" if survivor else "",
    })
    return out


def main():
    print("=" * 132)
    print("WIDE <=15-MIN CENSUS — RESUMABLE PHYSICAL TIMING / PHYSICAL-PLATE IDENTITY v049")
    print("=" * 132)
    print("NETWORK: SkyView identity metadata + DASCH DR7 metadata only.")
    print("APPLAUSE uses pinned DR4 metadata. POSS timing uses VI/25 normalization; HHH clock is NOT used for timing.")
    print("NO SCIENCE PIXELS. NO DETECTOR. NO CANDIDATE STATE MUTATION.\n")

    for path in (QUEUE, AUDIT, APPLAUSE, POSS_META, POLICY):
        if not path.is_file():
            raise RuntimeError(f"REFUSING: missing input {path}")
    policy = load_json(POLICY, {})
    if policy.get("policy_id") != EXPECTED_POLICY_ID:
        raise RuntimeError("REFUSING: candidate policy mismatch")

    queue = read_csv(QUEUE)
    if len(queue) != EXPECTED_QUEUE_ROWS:
        raise RuntimeError(f"REFUSING: expected {EXPECTED_QUEUE_ROWS} queue rows, got {len(queue)}")

    amap = applause_map()
    if sha256_file(POSS_META) != EXPECTED_POSS_SHA:
        raise RuntimeError("REFUSING: POSS VI/25 pinned source hash changed")
    vi25_records = load_vi25_records(POSS_META)

    applause_ids = sorted({
        int(row[f"exposure_{s}"].split(":")[1])
        for row in queue for s in ("a", "b") if source_kind(row[f"exposure_{s}"]) == "APPLAUSE"
    })
    poss_ids = sorted({
        row[f"exposure_{s}"]
        for row in queue for s in ("a", "b") if source_kind(row[f"exposure_{s}"]) == "POSS"
    })
    dasch_plates = sorted({
        parse_dasch_plate(row[f"exposure_{s}"])
        for row in queue for s in ("a", "b") if source_kind(row[f"exposure_{s}"]) == "DASCH"
    })
    observed_counts = {"APPLAUSE": len(applause_ids), "POSS": len(poss_ids), "DASCH": len(dasch_plates)}
    if observed_counts != EXPECTED_COUNTS:
        raise RuntimeError(f"REFUSING: unique identity counts changed: {observed_counts}")
    missing_ap = [eid for eid in applause_ids if eid not in amap]
    if missing_ap:
        raise RuntimeError(f"REFUSING: pinned APPLAUSE export lacks IDs: {missing_ap[:10]}")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    CACHE.mkdir(parents=True, exist_ok=True)
    cp = load_json(CHECKPOINT, checkpoint_default())

    descriptors = {}
    descriptor_blocked = set()
    for band in ("E", "O"):
        key = f"descriptor:{band}"
        if key in cp["terminal_transport"]:
            descriptor_blocked.add(band)
            continue
        try:
            descriptors[band] = fetch_descriptor(band)
        except Exception as exc:
            attempt = mark_transport(cp, key, exc)
            print(f"DESCRIPTOR transport retry {attempt}/{MAX_TRANSPORT_ATTEMPTS} {band}: {type(exc).__name__}: {exc}")
            if attempt < MAX_TRANSPORT_ATTEMPTS:
                return 10
            descriptor_blocked.add(band)

    remote_this_run = 0
    for exposure in poss_ids:
        path = poss_cache_path(exposure)
        if path.is_file():
            continue
        parsed = parse_poss_exposure(exposure)
        band = parsed[1] if parsed else None
        key = f"poss:{exposure}"
        if band in descriptor_blocked:
            write_json(path, {"status": "METADATA_TRANSPORT_UNRESOLVED_GLOBAL_DESCRIPTOR", "exposure": exposure, "band": band})
            continue
        if key in cp["terminal_transport"]:
            write_json(path, {"status": "METADATA_TRANSPORT_UNRESOLVED", "exposure": exposure, "transport": cp["terminal_transport"][key]})
            continue
        if remote_this_run >= REMOTE_BATCH:
            break
        try:
            result = resolve_poss_remote(exposure, vi25_records, descriptors)
            write_json(path, result)
            print(f"POSS {exposure}: {result.get('status')}")
        except Exception as exc:
            attempt = mark_transport(cp, key, exc)
            print(f"POSS transport retry {attempt}/{MAX_TRANSPORT_ATTEMPTS} {exposure}: {type(exc).__name__}: {exc}")
        remote_this_run += 1

    for plate in dasch_plates:
        path = dasch_cache_path(plate)
        if path.is_file():
            continue
        key = f"dasch:{plate}"
        if key in cp["terminal_transport"]:
            write_json(path, {"status": "METADATA_TRANSPORT_UNRESOLVED", "plate_id": plate, "transport": cp["terminal_transport"][key]})
            continue
        if remote_this_run >= REMOTE_BATCH:
            break
        try:
            result = resolve_dasch_plate_remote(plate)
            write_json(path, result)
            print(f"DASCH {plate}: {result.get('status')} timed_exposures={len(result.get('exposures', []))}")
        except Exception as exc:
            attempt = mark_transport(cp, key, exc)
            print(f"DASCH transport retry {attempt}/{MAX_TRANSPORT_ATTEMPTS} {plate}: {type(exc).__name__}: {exc}")
        remote_this_run += 1

    poss_done = sum(poss_cache_path(x).is_file() for x in poss_ids)
    dasch_done = sum(dasch_cache_path(x).is_file() for x in dasch_plates)
    cp.update({
        "status": "IN_PROGRESS",
        "applause_resolved": len(applause_ids),
        "applause_total": len(applause_ids),
        "poss_done": poss_done,
        "poss_total": len(poss_ids),
        "dasch_done": dasch_done,
        "dasch_total": len(dasch_plates),
        "remote_done": poss_done + dasch_done,
        "remote_total": len(poss_ids) + len(dasch_plates),
    })
    write_json(CHECKPOINT, cp)

    if poss_done < len(poss_ids) or dasch_done < len(dasch_plates):
        print(f"\nCHECKPOINT: APPLAUSE {len(applause_ids)}/{len(applause_ids)} | POSS {poss_done}/{len(poss_ids)} | DASCH {dasch_done}/{len(dasch_plates)}")
        print("RETURN 10: checkpointed IN_PROGRESS")
        return 10

    poss_results = {x: load_json(poss_cache_path(x), {}) for x in poss_ids}
    dasch_results = {x: load_json(dasch_cache_path(x), {}) for x in dasch_plates}

    pairs = []
    for row in queue:
        a = resolve_final_side(side_from_row(row, "a"), amap, poss_results, dasch_results)
        b = resolve_final_side(side_from_row(row, "b"), amap, poss_results, dasch_results)
        pairs.append(evaluate_pair(row, a, b))

    counts = {}
    for row in pairs:
        counts[row["classification"]] = counts.get(row["classification"], 0) + 1
    survivors = [row for row in pairs if row.get("timing_survivor")]
    unresolved = [row for row in pairs if row["classification"] == "UNRESOLVED_TIMING_OR_IDENTITY"]

    fields = [
        "timing_validation_priority", "current_time_gate", "canonical_pair",
        "exposure_a", "archive_a", "exposure_b", "archive_b",
        "classification", "timing_survivor", "science_eligible",
        "physical_overlap_start_utc", "physical_overlap_end_utc", "physical_overlap_s",
        "conservative_overlap_known_uncertainties_s", "formal_time_uncertainty_available_both", "next_gate",
    ]
    for path, rows in ((OUT_CSV, pairs), (SURVIVOR_CSV, survivors)):
        tmp = path.with_suffix(path.suffix + ".tmp")
        with tmp.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)
        tmp.replace(path)

    payload = {
        "status": "COMPLETE",
        "analysis_kind": "wide_census_physical_timing_v049",
        "guards": {
            "network_access": True,
            "science_pixels_read": False,
            "non_science_pixels_read": False,
            "transient_detector_rerun": False,
            "candidate_state_mutation": False,
        },
        "input_sha256": {
            "queue": sha256_file(QUEUE),
            "audit": sha256_file(AUDIT),
            "applause": sha256_file(APPLAUSE),
            "poss_vi25": sha256_file(POSS_META),
            "policy": sha256_file(POLICY),
        },
        "source_counts": {"queue_pairs": len(queue), **observed_counts},
        "classification_counts": counts,
        "timing_survivor_count": len(survivors),
        "unresolved_pair_count": len(unresolved),
        "science_eligible_count": 0,
        "method_notes": {
            "poss_timing": "VI/25 authoritative normalized UTC; HHH clock excluded from timing and used only for identity/date cross-check",
            "applause_timing": "pinned DR4 UT start/end; plate_id used for physical-plate identity",
            "dasch_timing": "specific DR7 astrometry exposure selected by pre-existing catalogue midpoint/duration, never by desired pair overlap",
        },
        "interpretation_boundary": "Timing/identity survivors are not science-eligible. True footprint intersection and any remaining physical-provenance checks are still required before detector work.",
        "pairs": pairs,
        "next_stage": "Resolve metadata-unresolved rows if any, then freeze true-footprint and independence census for timing survivors before any new science-pixel execution.",
    }
    write_json(OUT_JSON, payload)
    cp.update({
        "status": "COMPLETE",
        "pair_classification_counts": counts,
        "timing_survivor_count": len(survivors),
        "unresolved_pair_count": len(unresolved),
    })
    write_json(CHECKPOINT, cp)

    print("\n" + "=" * 132)
    print("WIDE PHYSICAL TIMING CENSUS COMPLETE")
    print("=" * 132)
    print("Classification counts:", json.dumps(counts, sort_keys=True))
    print(f"Timing survivors awaiting footprint validation: {len(survivors)}")
    print(f"Unresolved timing/identity pairs: {len(unresolved)}")
    print("SCIENCE ELIGIBLE: 0")
    print(f"Outputs: {OUT_JSON}, {OUT_CSV}, {SURVIVOR_CSV}")
    print("\nSTAGE STATUS: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
