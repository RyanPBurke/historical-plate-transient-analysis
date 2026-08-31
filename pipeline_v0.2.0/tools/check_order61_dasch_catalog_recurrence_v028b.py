from __future__ import annotations

from pathlib import Path
import csv
import hashlib
import io
import json
import math
import shutil
import subprocess
import time

import numpy as np

ROOT = Path.cwd()
BASE = ROOT / "results" / "order61_native_full_v028"
WORK = ROOT / "work" / "order61_dasch_recurrence_v028"
CACHE = WORK / "api_cache"

PS1_REPORT = BASE / "order61_ps1_static_report.json"
PS1_TRIAGE = BASE / "order61_ps1_static_triage.csv"
INJ_REPORT = BASE / "order61_injection_recovery_report.json"
PAIR_REPORT = BASE / "order61_whole_pair_report.json"

OUT_PAIR = BASE / "order61_dasch_catalog_recurrence_triage.csv"
OUT_SOURCES = BASE / "order61_dasch_catalog_recurrence_sources.csv"
OUT_LC = BASE / "order61_dasch_catalog_recurrence_lightcurves.csv"
OUT_INVALID = BASE / "order61_dasch_catalog_recurrence_unlocatable_rows.csv"
OUT_REPORT = BASE / "order61_dasch_catalog_recurrence_report.json"

for d in (WORK, CACHE):
    d.mkdir(parents=True, exist_ok=True)

API_BASE = "https://api.starglass.cfa.harvard.edu/public"
QUERYCAT = API_BASE + "/dasch/dr7/querycat"
LIGHTCURVE = API_BASE + "/dasch/dr7/lightcurve"
UA = "historical-transient-pipeline/0.2.8-order61-dasch-recurrence"

EXPECTED_DETECTOR_SHA = (
    "709da8d7a7972b15808d70a1e4dbffa"
    "0fd0fee864a81d954f74fe4a5f5af25e7"
)
EXPECTED_METHOD_SHA = (
    "2cb3cabd573d7af99399899f2ccecd30"
    "02be90297e55bb0e0dcdd9dea1d0c4c1"
)
EXPECTED_POLICY_SHA = (
    "44fc3453c3291a7cbe72894d781729a3"
    "0943ad540aa169b2c0897b446c5c8ec7"
)

EXPECTED_SURVIVORS = [11, 14, 20, 22]

# Frozen before recurrence outcomes.
REFCATS = ["atlas", "apass"]
QUERY_RADIUS_ARCSEC = 60.0
STRONG_ARCSEC = 3.0
DIAGNOSTIC_ARCSEC = 5.0
MIN_QUERYCAT_MATCHES_TO_FETCH_LC = 2
MIN_DISTINCT_PLATES_FOR_RECURRENCE = 2
PAIR_DASCH_PLATE_ID = "ai44092"

PAIR_FIELDS = [
    "strict_rank",
    "pair_ra_deg",
    "pair_dec_deg",
    "pair_separation_arcsec",
    "poss_snr",
    "dasch_snr",
    "morphology_flag_count",
    "registration_residual_arcsec",
    "recurrence_class",
    "strong_multiplate_recurrence",
    "diagnostic_multiplate_recurrence",
    "best_refcat",
    "best_ref_text",
    "best_ref_number",
    "best_sep_arcsec",
    "best_separation_source",
    "best_querycat_num_matches",
    "best_lightcurve_detected_rows",
    "best_lightcurve_distinct_detected_plates",
    "best_lightcurve_contains_ai44092_detection",
    "best_earliest_hjd",
    "best_latest_hjd",
    "atlas_query_rows",
    "atlas_locatable_rows",
    "atlas_unlocatable_nonrecurrent_rows",
    "apass_query_rows",
    "apass_locatable_rows",
    "apass_unlocatable_nonrecurrent_rows",
    "survives_catalogued_dasch_recurrence_3arcsec",
    "survives_catalogued_dasch_recurrence_5arcsec",
]

SOURCE_FIELDS = [
    "strict_rank",
    "refcat",
    "ref_text",
    "ref_number",
    "gsc_bin_index",
    "source_ra_deg",
    "source_dec_deg",
    "sep_arcsec",
    "dra_arcsec",
    "ddec_arcsec",
    "separation_source",
    "num_matches",
    "stdmag",
    "color",
    "class",
    "v_flag",
    "lightcurve_fetched",
    "lightcurve_detected_rows",
    "lightcurve_distinct_detected_plates",
    "lightcurve_contains_ai44092_detection",
    "earliest_hjd",
    "latest_hjd",
]

LC_FIELDS = [
    "strict_rank",
    "refcat",
    "ref_text",
    "ref_number",
    "gsc_bin_index",
    "is_detection",
    "time_hjd",
    "series",
    "platenum",
    "plate_id",
    "expnum",
    "solnum",
    "ra_deg",
    "dec_deg",
    "catalog_ra_deg",
    "catalog_dec_deg",
    "magcal_magdep",
    "fwhm_world_deg",
    "ellipticity",
    "aflags",
    "bflags",
    "plate_quality_flag",
]

INVALID_FIELDS = [
    "strict_rank",
    "refcat",
    "row_index",
    "num_matches",
    "safe_for_fixed_recurrence_screen",
    "reason",
    "columns",
    "raw_row_json",
]


def read_csv(path: Path):
    with path.open(newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def write_csv(path: Path, rows, fields):
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    tmp.replace(path)


def write_json(path: Path, obj):
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(obj, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )
    tmp.replace(path)


def ffloat(v):
    if v is None:
        return None
    s = str(v).strip()
    if not s or s.lower() in {"nan", "null", "none", "--"}:
        return None
    try:
        x = float(s)
    except ValueError:
        return None
    return x if math.isfinite(x) else None


def fint(v):
    if v is None:
        return None
    s = str(v).strip()
    if not s:
        return None
    try:
        return int(s)
    except ValueError:
        try:
            return int(float(s))
        except ValueError:
            return None


def normkey(k):
    return "".join(ch for ch in str(k).lower() if ch.isalnum())


def getv(row, *aliases):
    nr = {normkey(k): v for k, v in row.items()}
    for a in aliases:
        key = normkey(a)
        if key in nr:
            return nr[key]
    return None


def angular_offsets_arcsec(target_ra, target_dec, source_ra, source_dec):
    """
    Return eastward RA*cos(dec), northward Dec, and exact great-circle
    separation in arcsec. Query radii are only 60", but use the exact
    spherical separation for the 3"/5" classification.
    """
    r1 = math.radians(target_ra)
    d1 = math.radians(target_dec)
    r2 = math.radians(source_ra)
    d2 = math.radians(source_dec)

    dra = r2 - r1
    while dra > math.pi:
        dra -= 2 * math.pi
    while dra < -math.pi:
        dra += 2 * math.pi

    sd = math.sin((d2 - d1) / 2.0)
    sr = math.sin(dra / 2.0)
    a = sd * sd + math.cos(d1) * math.cos(d2) * sr * sr
    a = min(1.0, max(0.0, a))
    sep = 2.0 * math.asin(math.sqrt(a)) * 206264.80624709636

    ddec = math.degrees(d2 - d1) * 3600.0
    east = math.degrees(dra) * 3600.0 * math.cos((d1 + d2) / 2.0)

    return east, ddec, sep


def midpoint_sky(row):
    ra1 = math.radians(float(row["poss_ra_deg"]))
    de1 = math.radians(float(row["poss_dec_deg"]))
    ra2 = math.radians(float(row["dasch_ra_deg"]))
    de2 = math.radians(float(row["dasch_dec_deg"]))

    v1 = np.array([
        math.cos(de1) * math.cos(ra1),
        math.cos(de1) * math.sin(ra1),
        math.sin(de1),
    ])
    v2 = np.array([
        math.cos(de2) * math.cos(ra2),
        math.cos(de2) * math.sin(ra2),
        math.sin(de2),
    ])

    v = v1 + v2
    v /= np.linalg.norm(v)

    dec = math.asin(float(v[2]))
    ra = math.atan2(float(v[1]), float(v[0]))
    if ra < 0:
        ra += 2 * math.pi

    return math.degrees(ra), math.degrees(dec)


def curl_post_json(url, payload, cache_stem, attempts=4):
    raw_path = CACHE / f"{cache_stem}.json"
    meta_path = CACHE / f"{cache_stem}.meta.json"

    if raw_path.is_file() and meta_path.is_file():
        raw = raw_path.read_bytes()
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        if (
            meta.get("complete") is True
            and meta.get("url") == url
            and meta.get("payload") == payload
            and meta.get("sha256") == hashlib.sha256(raw).hexdigest()
        ):
            return json.loads(raw.decode("utf-8")), meta, "cached"

    curl = shutil.which("curl.exe") or shutil.which("curl")
    if not curl:
        raise RuntimeError(
            "Verified HTTPS transport unavailable: curl.exe/curl not found"
        )

    payload_text = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    part = raw_path.with_suffix(".json.part")
    errors = []

    for attempt in range(1, attempts + 1):
        if part.exists():
            part.unlink()

        cmd = [
            curl,
            "--fail",
            "--silent",
            "--show-error",
            "--location",
            "--connect-timeout", "30",
            "--max-time", "180",
            "--user-agent", UA,
            "--header", "Accept: application/json",
            "--header", "Content-Type: application/json",
            "--data-binary", payload_text,
            "--output", str(part),
            url,
        ]

        try:
            cp = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=210,
                check=False,
            )

            if cp.returncode != 0:
                err = (cp.stderr or cp.stdout or "").strip()
                raise RuntimeError(
                    f"curl exit {cp.returncode}: {err[:600]}"
                )

            if not part.is_file():
                raise RuntimeError("curl succeeded but produced no response file")

            raw = part.read_bytes()
            obj = json.loads(raw.decode("utf-8"))

            sha = hashlib.sha256(raw).hexdigest()
            part.replace(raw_path)

            meta = {
                "complete": True,
                "url": url,
                "payload": payload,
                "sha256": sha,
                "bytes": len(raw),
                "transport": "curl_verified_https",
                "tls_verification_disabled": False,
            }
            write_json(meta_path, meta)

            return obj, meta, "done"

        except (
            subprocess.TimeoutExpired,
            RuntimeError,
            OSError,
            json.JSONDecodeError,
        ) as exc:
            errors.append(repr(exc))
            print(
                f"    {cache_stem} attempt {attempt}/{attempts} FAILED: {exc}",
                flush=True,
            )

            if part.exists():
                try:
                    part.unlink()
                except OSError:
                    pass

            if attempt < attempts:
                time.sleep(2 ** attempt)

    raise RuntimeError(
        f"API request failed for {cache_stem}: {errors[-1]}"
    )


def parse_json_csv_lines(obj, label):
    if not isinstance(obj, list):
        raise RuntimeError(
            f"{label}: expected JSON list of CSV lines, got {type(obj).__name__}"
        )

    if not obj:
        return [], []

    if not all(isinstance(x, str) for x in obj):
        raise RuntimeError(f"{label}: JSON list contains non-string records")

    text = "\n".join(x.rstrip("\r\n") for x in obj) + "\n"
    reader = csv.DictReader(io.StringIO(text))

    if reader.fieldnames is None:
        raise RuntimeError(f"{label}: no CSV header")

    return list(reader), list(reader.fieldnames)


def querycat(rank, refcat, ra, dec):
    payload = {
        "refcat": refcat,
        "ra_deg": float(ra),
        "dec_deg": float(dec),
        "radius_arcsec": QUERY_RADIUS_ARCSEC,
    }
    obj, meta, status = curl_post_json(
        QUERYCAT,
        payload,
        f"strict_{rank:02d}_{refcat}_querycat",
    )
    rows, header = parse_json_csv_lines(
        obj,
        f"{rank}/{refcat}/querycat",
    )
    return rows, header, status


def source_record(rank, refcat, row, target_ra, target_dec):
    """
    Parse one raw querycat row.

    Official DR7 querycat outputs document `dra`/`ddec`, but raw API
    schemas are camel-case and may contain masked/non-finite values.
    If offsets are unavailable, derive exact separation from returned
    source coordinates. Classification never depends on field spelling.
    """
    num_matches = fint(getv(row, "num_matches", "numMatches"))

    dra = ffloat(getv(row, "dra", "dRa", "delta_ra", "deltaRa"))
    ddec = ffloat(getv(row, "ddec", "dDec", "delta_dec", "deltaDec"))

    source_ra = ffloat(getv(
        row,
        "ra_deg", "raDeg", "ra",
        "ref_ra_deg", "refRaDeg", "ref_ra", "refRa",
        "catalog_ra", "catalogRa",
    ))
    source_dec = ffloat(getv(
        row,
        "dec_deg", "decDeg", "dec",
        "ref_dec_deg", "refDecDeg", "ref_dec", "refDec",
        "catalog_dec", "catalogDec",
    ))

    if source_ra is not None and source_dec is not None:
        calc_dra, calc_ddec, sep = angular_offsets_arcsec(
            target_ra,
            target_dec,
            source_ra,
            source_dec,
        )
        if dra is None:
            dra = calc_dra
        if ddec is None:
            ddec = calc_ddec
        separation_source = "source_coordinates_exact_spherical"

    elif dra is not None and ddec is not None:
        sep = math.hypot(dra, ddec)
        separation_source = "querycat_dra_ddec"

    else:
        return None, {
            "num_matches": num_matches,
            "reason": (
                "querycat row has neither finite dra/ddec nor a usable "
                "source RA/Dec pair"
            ),
        }

    return {
        "strict_rank": rank,
        "refcat": refcat,
        "ref_text": str(getv(row, "ref_text", "refText") or "").strip(),
        "ref_number": fint(getv(row, "ref_number", "refNumber")),
        "gsc_bin_index": fint(getv(row, "gsc_bin_index", "gscBinIndex")),
        "source_ra_deg": source_ra,
        "source_dec_deg": source_dec,
        "sep_arcsec": sep,
        "dra_arcsec": dra,
        "ddec_arcsec": ddec,
        "separation_source": separation_source,
        "num_matches": 0 if num_matches is None else num_matches,
        "stdmag": ffloat(getv(row, "stdmag", "stdMag")),
        "color": ffloat(getv(row, "color")),
        "class": fint(getv(row, "class")),
        "v_flag": fint(getv(row, "v_flag", "vFlag")),
        "lightcurve_fetched": False,
        "lightcurve_detected_rows": None,
        "lightcurve_distinct_detected_plates": None,
        "lightcurve_contains_ai44092_detection": None,
        "earliest_hjd": None,
        "latest_hjd": None,
    }, None


def plate_id(series, platenum):
    if series is None or platenum is None:
        return None
    s = str(series).strip().lower()
    p = fint(platenum)
    if not s or p is None:
        return None
    return f"{s}{p:05d}"


def parse_lightcurve(rank, src, obj):
    rows, header = parse_json_csv_lines(
        obj,
        f"{rank}/{src['refcat']}/{src['ref_number']}/lightcurve",
    )

    audit = []
    detected_plate_ids = set()
    detected_times = []
    contains_pair = False
    n_detected = 0

    for r in rows:
        # Raw DR7 web API is camel-case; normkey/getv accepts both raw and
        # daschlab-processed spellings.
        mag = ffloat(getv(r, "magcal_magdep", "magcalMagdep"))
        is_det = mag is not None

        series = getv(r, "series")
        platenum = fint(getv(r, "platenum", "plate_number", "plateNumber"))
        pid = plate_id(series, platenum)

        hjd = ffloat(getv(r, "time", "date_jd", "dateJd"))

        if is_det:
            n_detected += 1
            if pid is not None:
                detected_plate_ids.add(pid)
                if pid == PAIR_DASCH_PLATE_ID:
                    contains_pair = True
            if hjd is not None:
                detected_times.append(hjd)

        audit.append({
            "strict_rank": rank,
            "refcat": src["refcat"],
            "ref_text": src["ref_text"],
            "ref_number": src["ref_number"],
            "gsc_bin_index": src["gsc_bin_index"],
            "is_detection": is_det,
            "time_hjd": hjd,
            "series": None if series is None else str(series).strip(),
            "platenum": platenum,
            "plate_id": pid,
            "expnum": fint(getv(
                r, "expnum", "exposure_number", "exposureNumber"
            )),
            "solnum": fint(getv(
                r, "solnum", "solution_number", "solutionNumber"
            )),
            "ra_deg": ffloat(getv(r, "ra_deg", "raDeg")),
            "dec_deg": ffloat(getv(r, "dec_deg", "decDeg")),
            "catalog_ra_deg": ffloat(getv(
                r,
                "catalog_ra", "catalogRa",
                "ra_cat_corrected", "raCatCorrected",
            )),
            "catalog_dec_deg": ffloat(getv(
                r,
                "catalog_dec", "catalogDec",
                "dec_cat_corrected", "decCatCorrected",
            )),
            "magcal_magdep": mag,
            "fwhm_world_deg": ffloat(getv(
                r, "fwhm_world", "fwhmWorld", "fwhm_deg", "fwhmDeg"
            )),
            "ellipticity": ffloat(getv(r, "ellipticity")),
            "aflags": fint(getv(r, "aflags")),
            "bflags": fint(getv(r, "bflags")),
            "plate_quality_flag": fint(getv(
                r, "plate_quality_flag", "plateQualityFlag", "quality"
            )),
        })

    return {
        "audit_rows": audit,
        "detected_rows": n_detected,
        "distinct_detected_plates": len(detected_plate_ids),
        "contains_ai44092_detection": contains_pair,
        "earliest_hjd": min(detected_times) if detected_times else None,
        "latest_hjd": max(detected_times) if detected_times else None,
        "detected_plate_ids": sorted(detected_plate_ids),
        "raw_lightcurve_rows": len(rows),
        "raw_header": header,
    }


def fetch_lightcurve(rank, src):
    if src["ref_number"] is None or src["gsc_bin_index"] is None:
        raise RuntimeError(
            f"{rank}/{src['refcat']}: close recurrent-capable source lacks "
            "ref_number/gsc_bin_index required by official lightcurve API"
        )

    payload = {
        "refcat": src["refcat"],
        "ref_number": int(src["ref_number"]),
        "gsc_bin_index": int(src["gsc_bin_index"]),
    }

    obj, meta, status = curl_post_json(
        LIGHTCURVE,
        payload,
        (
            f"strict_{rank:02d}_{src['refcat']}_"
            f"ref{src['ref_number']}_lightcurve"
        ),
    )

    return parse_lightcurve(rank, src, obj), status


def main():
    print("=" * 92)
    print("ORDER 61 — DASCH DR7 CATALOGUED HISTORICAL RECURRENCE SCREEN v028b")
    print("=" * 92)
    print(
        "All 4 Gaia+PS1-clean ranks; ATLAS+APASS; schema-preflighted; "
        "multi-plate recurrence required."
    )
    print()

    for p in (PS1_REPORT, PS1_TRIAGE, INJ_REPORT, PAIR_REPORT):
        if not p.is_file():
            raise RuntimeError(f"Missing required completed-stage file: {p}")

    ps1_report = json.loads(PS1_REPORT.read_text(encoding="utf-8"))
    inj_report = json.loads(INJ_REPORT.read_text(encoding="utf-8"))
    pair_report = json.loads(PAIR_REPORT.read_text(encoding="utf-8"))

    guards = {
        "pair_complete": pair_report.get("status") == "COMPLETE",
        "order": int(pair_report.get("canonical_order", -1)) == 61,
        "detector": pair_report.get("detector_sha256") == EXPECTED_DETECTOR_SHA,
        "method": pair_report.get("method_sha256") == EXPECTED_METHOD_SHA,
        "policy": pair_report.get("policy_sha256") == EXPECTED_POLICY_SHA,
        "ps1_complete": ps1_report.get("status") == "COMPLETE",
        "ps1_survivors": (
            [int(x) for x in ps1_report.get("survivor_ranks_5arcsec", [])]
            == EXPECTED_SURVIVORS
        ),
        "injection_complete": inj_report.get("status") == "COMPLETE",
        "injection_survivors": (
            [int(x) for x in inj_report.get("survivor_ranks", [])]
            == EXPECTED_SURVIVORS
        ),
        "injection_detector_unchanged": (
            inj_report.get("science_detector_parameters_changed") is False
        ),
    }

    if not all(guards.values()):
        raise RuntimeError(
            "REFUSING: completed-stage guard failure: "
            + json.dumps(guards, sort_keys=True)
        )

    triage = read_csv(PS1_TRIAGE)
    by_rank = {int(r["strict_rank"]): r for r in triage}

    if any(rank not in by_rank for rank in EXPECTED_SURVIVORS):
        raise RuntimeError("REFUSING: missing PS1 triage rows")

    print("Completed-stage guards: PASS")
    print(
        f"Policy unchanged: query={QUERY_RADIUS_ARCSEC:.0f}\"; "
        f"strong={STRONG_ARCSEC:.0f}\"; diagnostic={DIAGNOSTIC_ARCSEC:.0f}\"; "
        f"recurrence >= {MIN_DISTINCT_PLATES_FOR_RECURRENCE} distinct plates."
    )
    print()

    # ---------------------------------------------------------------
    # Preflight ALL eight querycat responses before fetching any
    # recurrence lightcurve. A row without coordinates/offsets is safe
    # to retain as an audited non-recurrence row only if num_matches < 2,
    # because it cannot satisfy the fixed multi-plate recurrence rule.
    # ---------------------------------------------------------------

    print("Preflighting all 8 DASCH querycat responses ...")

    query_preflight = {}
    invalid_rows = []

    for rank in EXPECTED_SURVIVORS:
        r = by_rank[rank]
        ra, dec = midpoint_sky(r)

        for refcat in REFCATS:
            qrows, header, status = querycat(rank, refcat, ra, dec)

            parsed = []
            unsafe_invalid = 0
            safe_invalid = 0

            for row_index, row in enumerate(qrows, 1):
                src, err = source_record(
                    rank,
                    refcat,
                    row,
                    ra,
                    dec,
                )

                if src is not None:
                    parsed.append(src)
                    continue

                nm = err["num_matches"]
                safe = nm is not None and nm < MIN_QUERYCAT_MATCHES_TO_FETCH_LC

                invalid_rows.append({
                    "strict_rank": rank,
                    "refcat": refcat,
                    "row_index": row_index,
                    "num_matches": nm,
                    "safe_for_fixed_recurrence_screen": safe,
                    "reason": err["reason"],
                    "columns": "|".join(header),
                    "raw_row_json": json.dumps(
                        row,
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                })

                if safe:
                    safe_invalid += 1
                else:
                    unsafe_invalid += 1

            if unsafe_invalid:
                write_csv(OUT_INVALID, invalid_rows, INVALID_FIELDS)
                raise RuntimeError(
                    f"REFUSING: strict #{rank:02d} {refcat} has "
                    f"{unsafe_invalid} unlocatable row(s) that could satisfy "
                    f"the >=2-match recurrence rule. Audit written to {OUT_INVALID}"
                )

            if qrows and not parsed and safe_invalid != len(qrows):
                raise RuntimeError(
                    f"REFUSING: strict #{rank:02d} {refcat} non-empty query "
                    "could not be safely interpreted"
                )

            query_preflight[(rank, refcat)] = {
                "target_ra": ra,
                "target_dec": dec,
                "raw_count": len(qrows),
                "locatable_count": len(parsed),
                "safe_invalid_count": safe_invalid,
                "header": header,
                "sources": parsed,
                "status": status,
            }

            print(
                f"  [strict #{rank:02d} {refcat:5s}] "
                f"{status.upper():6s} raw={len(qrows):3d} "
                f"locatable={len(parsed):3d} "
                f"unlocatable_nonrecurrent={safe_invalid:2d} PASS",
                flush=True,
            )

    if len(query_preflight) != 8:
        raise RuntimeError("REFUSING: querycat preflight count != 8")

    write_csv(OUT_INVALID, invalid_rows, INVALID_FIELDS)

    print("All 8 querycat schema/position preflights: PASS")
    print("Beginning fixed recurrence evaluation ...")
    print()

    pair_rows = []
    source_rows = []
    lc_rows = []

    for idx, rank in enumerate(EXPECTED_SURVIVORS, 1):
        r = by_rank[rank]
        ra, dec = midpoint_sky(r)

        all_sources = []

        for refcat in REFCATS:
            pf = query_preflight[(rank, refcat)]

            for src in pf["sources"]:
                if (
                    src["sep_arcsec"] <= DIAGNOSTIC_ARCSEC
                    and src["num_matches"] >= MIN_QUERYCAT_MATCHES_TO_FETCH_LC
                ):
                    lc, lcstatus = fetch_lightcurve(rank, src)
                    src["lightcurve_fetched"] = True
                    src["lightcurve_detected_rows"] = lc["detected_rows"]
                    src["lightcurve_distinct_detected_plates"] = (
                        lc["distinct_detected_plates"]
                    )
                    src["lightcurve_contains_ai44092_detection"] = (
                        lc["contains_ai44092_detection"]
                    )
                    src["earliest_hjd"] = lc["earliest_hjd"]
                    src["latest_hjd"] = lc["latest_hjd"]
                    lc_rows.extend(lc["audit_rows"])

                all_sources.append(src)

        all_sources.sort(
            key=lambda s: (
                float(s["sep_arcsec"]),
                -int(s["num_matches"]),
                s["refcat"],
            )
        )
        source_rows.extend(all_sources)

        recurrent = [
            s for s in all_sources
            if s["lightcurve_fetched"]
            and int(s["lightcurve_distinct_detected_plates"] or 0)
            >= MIN_DISTINCT_PLATES_FOR_RECURRENCE
        ]

        strong = [
            s for s in recurrent
            if float(s["sep_arcsec"]) <= STRONG_ARCSEC
        ]
        diagnostic = [
            s for s in recurrent
            if float(s["sep_arcsec"]) <= DIAGNOSTIC_ARCSEC
        ]

        if strong:
            cls = "DASCH_MULTIPLATE_RECURRENCE_STRONG"
            best = strong[0]
        elif diagnostic:
            cls = "DASCH_MULTIPLATE_RECURRENCE_DIAGNOSTIC"
            best = diagnostic[0]
        else:
            close_unconfirmed = [
                s for s in all_sources
                if float(s["sep_arcsec"]) <= DIAGNOSTIC_ARCSEC
                and int(s["num_matches"]) > 0
            ]

            if close_unconfirmed:
                cls = (
                    "DASCH_CLOSE_CATALOG_SOURCE_"
                    "NO_CONFIRMED_MULTIPLATE_RECURRENCE"
                )
                best = close_unconfirmed[0]
            else:
                cls = "NO_CATALOGUED_DASCH_RECURRENCE_WITHIN_5_ARCSEC"
                best = all_sources[0] if all_sources else None

        def bv(key):
            return None if best is None else best.get(key)

        atlas_pf = query_preflight[(rank, "atlas")]
        apass_pf = query_preflight[(rank, "apass")]

        pair_rows.append({
            "strict_rank": rank,
            "pair_ra_deg": ra,
            "pair_dec_deg": dec,
            "pair_separation_arcsec": float(r["pair_separation_arcsec"]),
            "poss_snr": float(r["poss_snr"]),
            "dasch_snr": float(r["dasch_snr"]),
            "morphology_flag_count": int(r["morphology_flag_count"]),
            "registration_residual_arcsec": float(
                r["registration_residual_arcsec"]
            ),
            "recurrence_class": cls,
            "strong_multiplate_recurrence": bool(strong),
            "diagnostic_multiplate_recurrence": bool(diagnostic),
            "best_refcat": bv("refcat"),
            "best_ref_text": bv("ref_text"),
            "best_ref_number": bv("ref_number"),
            "best_sep_arcsec": bv("sep_arcsec"),
            "best_separation_source": bv("separation_source"),
            "best_querycat_num_matches": bv("num_matches"),
            "best_lightcurve_detected_rows": bv("lightcurve_detected_rows"),
            "best_lightcurve_distinct_detected_plates": bv(
                "lightcurve_distinct_detected_plates"
            ),
            "best_lightcurve_contains_ai44092_detection": bv(
                "lightcurve_contains_ai44092_detection"
            ),
            "best_earliest_hjd": bv("earliest_hjd"),
            "best_latest_hjd": bv("latest_hjd"),
            "atlas_query_rows": atlas_pf["raw_count"],
            "atlas_locatable_rows": atlas_pf["locatable_count"],
            "atlas_unlocatable_nonrecurrent_rows": atlas_pf[
                "safe_invalid_count"
            ],
            "apass_query_rows": apass_pf["raw_count"],
            "apass_locatable_rows": apass_pf["locatable_count"],
            "apass_unlocatable_nonrecurrent_rows": apass_pf[
                "safe_invalid_count"
            ],
            "survives_catalogued_dasch_recurrence_3arcsec": not bool(strong),
            "survives_catalogued_dasch_recurrence_5arcsec": not bool(diagnostic),
        })

        best_text = (
            "none"
            if best is None
            else (
                f"{best['sep_arcsec']:.3f}\" "
                f"{best['refcat']} "
                f"num={best['num_matches']} "
                f"plates={best['lightcurve_distinct_detected_plates']}"
            )
        )

        print(
            f"  [{idx:02d}/4] strict #{rank:02d} "
            f"best={best_text:<42s} {cls}",
            flush=True,
        )

    write_csv(OUT_PAIR, pair_rows, PAIR_FIELDS)
    write_csv(OUT_SOURCES, source_rows, SOURCE_FIELDS)
    write_csv(OUT_LC, lc_rows, LC_FIELDS)

    survive3 = [
        int(r["strict_rank"])
        for r in pair_rows
        if r["survives_catalogued_dasch_recurrence_3arcsec"]
    ]
    survive5 = [
        int(r["strict_rank"])
        for r in pair_rows
        if r["survives_catalogued_dasch_recurrence_5arcsec"]
    ]

    out_report = {
        "status": "COMPLETE",
        "analysis_kind": (
            "order61_dasch_dr7_catalogued_historical_recurrence_v028b"
        ),
        "api_base": API_BASE,
        "guards": guards,
        "fixed_policy": {
            "refcats": REFCATS,
            "query_radius_arcsec": QUERY_RADIUS_ARCSEC,
            "strong_recurrence_arcsec": STRONG_ARCSEC,
            "diagnostic_recurrence_arcsec": DIAGNOSTIC_ARCSEC,
            "minimum_querycat_matches_to_fetch_lightcurve": (
                MIN_QUERYCAT_MATCHES_TO_FETCH_LC
            ),
            "minimum_distinct_physical_plates_for_recurrence": (
                MIN_DISTINCT_PLATES_FOR_RECURRENCE
            ),
            "detection_definition": (
                "finite raw magcalMagdep/magcal_magdep in DASCH "
                "lightcurve response"
            ),
            "querycat_separation_policy": (
                "use exact spherical separation from returned source "
                "RA/Dec when available; otherwise documented dra/ddec"
            ),
            "unlocatable_row_policy": (
                "audit; safe only when num_matches<2, which cannot satisfy "
                "the frozen multi-plate recurrence definition; otherwise "
                "fail closed"
            ),
            "querycat_preflight_all_8_before_lightcurve_fetch": True,
            "pair_dasch_plate_id": PAIR_DASCH_PLATE_ID,
            "https_transport": "curl_verified_https",
            "tls_verification_disabled": False,
        },
        "input_ranks": EXPECTED_SURVIVORS,
        "querycat_unlocatable_nonrecurrent_row_count": len(invalid_rows),
        "strong_multiplate_recurrence_count": sum(
            bool(r["strong_multiplate_recurrence"]) for r in pair_rows
        ),
        "diagnostic_multiplate_recurrence_count": sum(
            bool(r["diagnostic_multiplate_recurrence"]) for r in pair_rows
        ),
        "survivor_ranks_3arcsec": survive3,
        "survivor_ranks_5arcsec": survive5,
        "no_candidate_deleted": True,
        "detector_rerun": False,
        "image_pixels_read": False,
        "outputs": {
            "pair_triage_csv": str(OUT_PAIR),
            "source_audit_csv": str(OUT_SOURCES),
            "lightcurve_audit_csv": str(OUT_LC),
            "unlocatable_row_audit_csv": str(OUT_INVALID),
        },
        "next_stage": (
            "For ranks surviving this catalogued recurrence screen, use "
            "DASCH queryexps/platephot to search independent historical "
            "exposures for uncatalogued/unassociated detections at the "
            "candidate position."
        ),
    }

    write_json(OUT_REPORT, out_report)

    print()
    print("=" * 92)
    print("DASCH CATALOGUED HISTORICAL RECURRENCE SCREEN COMPLETE")
    print("=" * 92)
    print(f"Input ranks:                       {EXPECTED_SURVIVORS}")
    print(
        "Strong <=3\" multi-plate recurrence: "
        f"{out_report['strong_multiplate_recurrence_count']}"
    )
    print(
        "Any <=5\" multi-plate recurrence:    "
        f"{out_report['diagnostic_multiplate_recurrence_count']}"
    )
    print(f"Survive <=3\" recurrence screen:   {survive3}")
    print(f"Survive <=5\" diagnostic screen:   {survive5}")
    print(
        "Audited unlocatable rows unable to meet recurrence rule: "
        f"{len(invalid_rows)}"
    )
    print()

    print("Cases:")
    for r in pair_rows:
        sep = r["best_sep_arcsec"]
        septext = "none" if sep is None else f"{float(sep):.3f}\""
        print(
            f"  strict #{int(r['strict_rank']):02d} "
            f"{r['recurrence_class']:<56s} "
            f"nearest={septext:>8s}"
        )

    print()
    print("Outputs:")
    print(" ", OUT_REPORT)
    print(" ", OUT_PAIR)
    print(" ", OUT_SOURCES)
    print(" ", OUT_LC)
    print(" ", OUT_INVALID)
    print()
    print("No detector was rerun.")
    print("No image pixel was read.")
    print("No candidate was deleted.")


if __name__ == "__main__":
    main()
