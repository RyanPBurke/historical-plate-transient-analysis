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
WORK = ROOT / "work" / "order61_platephot_preflight_v028"
CACHE = WORK / "api_cache"

PAIR_REPORT = BASE / "order61_whole_pair_report.json"
PS1_TRIAGE = BASE / "order61_ps1_static_triage.csv"
INJ_REPORT = BASE / "order61_injection_recovery_report.json"
REC_REPORT = BASE / "order61_dasch_catalog_recurrence_report.json"

OUT_EXPOSURES = BASE / "order61_queryexps_exposure_census.csv"
OUT_CURRENT = BASE / "order61_ai44092_platephot_context.csv"
OUT_SOURCES = BASE / "order61_ai44092_platephot_sources_within60arcsec.csv"
OUT_REPORT = BASE / "order61_platephot_preflight_report.json"

for d in (WORK, CACHE):
    d.mkdir(parents=True, exist_ok=True)

API_BASE = "https://api.starglass.cfa.harvard.edu/public"
QUERYEXPS = API_BASE + "/dasch/dr7/queryexps"
PLATEPHOT = API_BASE + "/dasch/dr7/platephot"
UA = "historical-transient-pipeline/0.2.8-order61-platephot-preflight"

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

EXPECTED_RANKS = [11, 14, 20, 22]
PAIR_PLATE_ID = "ai44092"

# Context only. No survivor is deleted in this worker.
SOURCE_AUDIT_RADIUS_ARCSEC = 60.0
STRONG_CONTEXT_ARCSEC = 3.0
DIAGNOSTIC_CONTEXT_ARCSEC = 5.0

EXPOSURE_FIELDS = [
    "strict_rank",
    "target_ra_deg",
    "target_dec_deg",
    "series",
    "platenum",
    "plate_id",
    "scannum",
    "mosnum",
    "expnum",
    "solnum",
    "class",
    "ra_deg",
    "dec_deg",
    "exptime_min",
    "expdate",
    "wcssource",
    "centerdist",
    "edgedist",
    "limMagApass",
    "limMagAtlas",
    "resultIdApass",
    "resultIdAtlas",
    "nSolutionsApass",
    "nSolutionsAtlas",
    "nMagdepApass",
    "nMagdepAtlas",
    "has_imaging",
    "has_apass_phot",
    "has_atlas_phot",
    "selected_refcat_for_platephot",
    "is_pair_plate_ai44092",
    "eligible_independent_platephot",
]

CURRENT_FIELDS = [
    "strict_rank",
    "dasch_ra_deg",
    "dasch_dec_deg",
    "pair_mid_ra_deg",
    "pair_mid_dec_deg",
    "ai44092_queryexps_solution_count",
    "ai44092_imaging_solution_count",
    "ai44092_advertised_refcat_attempts",
    "ai44092_platephot_success_calls",
    "ai44092_platephot_failed_calls",
    "ai44092_context_status",
    "nearest_any_sep_arcsec",
    "nearest_any_solution_number",
    "nearest_any_refcat",
    "nearest_any_ref_number",
    "nearest_any_is_catalog_matched",
    "nearest_any_magcal_magdep",
    "nearest_any_fwhm_world_arcsec",
    "nearest_any_ellipticity",
    "nearest_any_catalog_sep_arcsec",
    "nearest_unmatched_sep_arcsec",
    "nearest_unmatched_solution_number",
    "nearest_unmatched_refcat",
    "nearest_unmatched_magcal_magdep",
    "nearest_unmatched_fwhm_world_arcsec",
    "sources_within_3arcsec",
    "sources_within_5arcsec",
    "sources_within_60arcsec",
]

SOURCE_FIELDS = [
    "strict_rank",
    "plate_id",
    "solution_number",
    "refcat",
    "sep_dasch_endpoint_arcsec",
    "sep_pair_midpoint_arcsec",
    "ra_deg",
    "dec_deg",
    "ref_number",
    "is_catalog_matched",
    "catalog_ra_deg",
    "catalog_dec_deg",
    "detected_to_catalog_sep_arcsec",
    "magcal_magdep",
    "magcal_local_rms",
    "limiting_mag_local",
    "flux_max",
    "background",
    "fwhm_image_px",
    "fwhm_world_arcsec",
    "ellipticity",
    "image_x",
    "image_y",
    "aflags",
    "bflags",
    "plate_quality_flag",
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
    for alias in aliases:
        k = normkey(alias)
        if k in nr:
            return nr[k]
    return None


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


def angular_sep_arcsec(ra1, dec1, ra2, dec2):
    r1 = math.radians(float(ra1))
    d1 = math.radians(float(dec1))
    r2 = math.radians(float(ra2))
    d2 = math.radians(float(dec2))

    dr = r2 - r1
    while dr > math.pi:
        dr -= 2 * math.pi
    while dr < -math.pi:
        dr += 2 * math.pi

    a = (
        math.sin((d2 - d1) / 2.0) ** 2
        + math.cos(d1) * math.cos(d2) * math.sin(dr / 2.0) ** 2
    )
    a = min(1.0, max(0.0, a))
    return 2.0 * math.asin(math.sqrt(a)) * 206264.80624709636


def plate_id(series, platenum):
    s = "" if series is None else str(series).strip().lower()
    p = fint(platenum)
    if not s or p is None or p < 0:
        return None
    return f"{s}{p:05d}"


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

    part = raw_path.with_suffix(".json.part")
    payload_text = json.dumps(payload, sort_keys=True, separators=(",", ":"))
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
            f"{label}: expected JSON list, got {type(obj).__name__}"
        )
    if not obj:
        raise RuntimeError(f"{label}: empty API response; expected CSV header")
    if not all(isinstance(x, str) for x in obj):
        raise RuntimeError(f"{label}: non-string item in CSV-line response")

    text = "\n".join(x.rstrip("\r\n") for x in obj) + "\n"
    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None:
        raise RuntimeError(f"{label}: no CSV header")

    return list(reader), list(reader.fieldnames)


def queryexps(rank, ra, dec):
    payload = {
        "ra_deg": float(ra),
        "dec_deg": float(dec),
    }
    obj, meta, status = curl_post_json(
        QUERYEXPS,
        payload,
        f"strict_{rank:02d}_queryexps",
    )
    rows, header = parse_json_csv_lines(
        obj,
        f"strict #{rank} queryexps",
    )
    return rows, header, status


def parse_exposure(rank, target_ra, target_dec, row):
    series = str(getv(row, "series") or "").strip().lower()
    platenum = fint(getv(row, "platenum", "plateNumber"))
    pid = plate_id(series, platenum)

    scannum = fint(getv(row, "scannum", "scanNumber"))
    mosnum = fint(getv(row, "mosnum", "mosaicNumber"))
    expnum = fint(getv(row, "expnum", "exposureNumber"))
    solnum = fint(getv(row, "solnum", "solutionNumber"))

    wcssource = str(getv(row, "wcssource", "wcsSource") or "").strip().lower()

    lim_apass = ffloat(getv(row, "limMagApass"))
    lim_atlas = ffloat(getv(row, "limMagAtlas"))

    result_apass = str(getv(row, "resultIdApass") or "").strip()
    result_atlas = str(getv(row, "resultIdAtlas") or "").strip()

    nsol_apass = fint(getv(row, "nSolutionsApass", "n_solutions_apass")) or 0
    nsol_atlas = fint(getv(row, "nSolutionsAtlas", "n_solutions_atlas")) or 0
    nmag_apass = fint(getv(row, "nMagdepApass", "n_magdep_apass")) or 0
    nmag_atlas = fint(getv(row, "nMagdepAtlas", "n_magdep_atlas")) or 0

    has_imaging = (
        wcssource == "imwcs"
        and solnum is not None
        and solnum >= 0
        and pid is not None
    )

    # These are position-specific calibrated-photometry indicators used
    # for the future exhaustive independent-exposure recurrence census.
    has_apass = has_imaging and lim_apass is not None
    has_atlas = has_imaging and lim_atlas is not None

    if has_apass:
        selected = "apass"
    elif has_atlas:
        selected = "atlas"
    else:
        selected = None

    is_pair = pid == PAIR_PLATE_ID

    return {
        "strict_rank": rank,
        "target_ra_deg": target_ra,
        "target_dec_deg": target_dec,
        "series": series,
        "platenum": platenum,
        "plate_id": pid,
        "scannum": scannum,
        "mosnum": mosnum,
        "expnum": expnum,
        "solnum": solnum,
        "class": str(getv(row, "class") or "").strip(),
        "ra_deg": ffloat(getv(row, "ra", "raDeg")),
        "dec_deg": ffloat(getv(row, "dec", "decDeg")),
        "exptime_min": ffloat(getv(row, "exptime", "exposureTime")),
        "expdate": str(getv(row, "expdate", "exposureDate") or "").strip(),
        "wcssource": wcssource,
        "centerdist": ffloat(getv(row, "centerdist", "centerDistance")),
        "edgedist": ffloat(getv(row, "edgedist", "edgeDistance")),
        "limMagApass": lim_apass,
        "limMagAtlas": lim_atlas,
        "resultIdApass": result_apass,
        "resultIdAtlas": result_atlas,
        "nSolutionsApass": nsol_apass,
        "nSolutionsAtlas": nsol_atlas,
        "nMagdepApass": nmag_apass,
        "nMagdepAtlas": nmag_atlas,
        "has_imaging": has_imaging,
        "has_apass_phot": has_apass,
        "has_atlas_phot": has_atlas,
        "selected_refcat_for_platephot": selected,
        "is_pair_plate_ai44092": is_pair,
        "eligible_independent_platephot": bool(
            selected is not None and not is_pair
        ),
    }



def platephot(rank, plate_id_, solnum, refcat, ra, dec):
    payload = {
        "plate_id": plate_id_,
        "solution_number": int(solnum),
        "refcat": refcat,
        "center_ra_deg": float(ra),
        "center_dec_deg": float(dec),
    }

    obj, meta, status = curl_post_json(
        PLATEPHOT,
        payload,
        (
            f"strict_{rank:02d}_{plate_id_}_"
            f"s{int(solnum)}_{refcat}_platephot"
        ),
    )

    rows, header = parse_json_csv_lines(
        obj,
        f"strict #{rank} {plate_id_} s{solnum} {refcat} platephot",
    )
    return rows, header, status


def parse_platephot_source(
    rank,
    plate_id_,
    solnum,
    refcat,
    row,
    dasch_ra,
    dasch_dec,
    mid_ra,
    mid_dec,
):
    ra = ffloat(getv(row, "ra_deg", "raDeg", "ra"))
    dec = ffloat(getv(row, "dec_deg", "decDeg", "dec"))

    if ra is None or dec is None:
        return None

    sep_d = angular_sep_arcsec(dasch_ra, dasch_dec, ra, dec)
    sep_m = angular_sep_arcsec(mid_ra, mid_dec, ra, dec)

    refnum = fint(getv(row, "ref_number", "refNumber"))
    matched = refnum is not None and refnum >= 0

    cra = ffloat(getv(row, "catalog_ra", "catalogRa"))
    cdec = ffloat(getv(row, "catalog_dec", "catalogDec"))

    catsep = None
    if cra is not None and cdec is not None:
        catsep = angular_sep_arcsec(ra, dec, cra, cdec)

    fwhm_world = ffloat(getv(row, "fwhm_world", "fwhmWorld", "fwhmDeg"))

    return {
        "strict_rank": rank,
        "plate_id": plate_id_,
        "solution_number": solnum,
        "refcat": refcat,
        "sep_dasch_endpoint_arcsec": sep_d,
        "sep_pair_midpoint_arcsec": sep_m,
        "ra_deg": ra,
        "dec_deg": dec,
        "ref_number": refnum,
        "is_catalog_matched": matched,
        "catalog_ra_deg": cra,
        "catalog_dec_deg": cdec,
        "detected_to_catalog_sep_arcsec": catsep,
        "magcal_magdep": ffloat(getv(row, "magcal_magdep", "magcalMagdep")),
        "magcal_local_rms": ffloat(getv(
            row, "magcal_local_rms", "magcalLocalRms"
        )),
        "limiting_mag_local": ffloat(getv(
            row, "limiting_mag_local", "limitingMagLocal"
        )),
        "flux_max": ffloat(getv(row, "flux_max", "fluxMax")),
        "background": ffloat(getv(row, "background")),
        "fwhm_image_px": ffloat(getv(row, "fwhm_image", "fwhmImage")),
        "fwhm_world_arcsec": (
            None if fwhm_world is None else fwhm_world * 3600.0
        ),
        "ellipticity": ffloat(getv(row, "ellipticity")),
        "image_x": ffloat(getv(row, "image_x", "imageX")),
        "image_y": ffloat(getv(row, "image_y", "imageY")),
        "aflags": fint(getv(row, "aflags")),
        "bflags": fint(getv(row, "bflags")),
        "plate_quality_flag": fint(getv(
            row, "plate_quality_flag", "plateQualityFlag"
        )),
    }


def main():
    print("=" * 94)
    print("ORDER 61 — AI44092 PLATEPHOT CONTEXT + INDEPENDENT EXPOSURE CENSUS v028b")
    print("=" * 94)
    print(
        "All 4 catalogue-clean ranks. Current-plate source context plus "
        "queryexps workload census; no survivor deletion."
    )
    print()

    for p in (PAIR_REPORT, PS1_TRIAGE, INJ_REPORT, REC_REPORT):
        if not p.is_file():
            raise RuntimeError(f"Missing required completed-stage file: {p}")

    pair_report = json.loads(PAIR_REPORT.read_text(encoding="utf-8"))
    inj_report = json.loads(INJ_REPORT.read_text(encoding="utf-8"))
    rec_report = json.loads(REC_REPORT.read_text(encoding="utf-8"))

    guards = {
        "pair_complete": pair_report.get("status") == "COMPLETE",
        "order": int(pair_report.get("canonical_order", -1)) == 61,
        "detector": pair_report.get("detector_sha256") == EXPECTED_DETECTOR_SHA,
        "method": pair_report.get("method_sha256") == EXPECTED_METHOD_SHA,
        "policy": pair_report.get("policy_sha256") == EXPECTED_POLICY_SHA,
        "injection_complete": inj_report.get("status") == "COMPLETE",
        "injection_ranks": [
            int(x) for x in inj_report.get("survivor_ranks", [])
        ] == EXPECTED_RANKS,
        "recurrence_complete": rec_report.get("status") == "COMPLETE",
        "recurrence_ranks_5arcsec": [
            int(x) for x in rec_report.get("survivor_ranks_5arcsec", [])
        ] == EXPECTED_RANKS,
    }

    if not all(guards.values()):
        raise RuntimeError(
            "REFUSING: completed-stage guard failure: "
            + json.dumps(guards, sort_keys=True)
        )

    triage = read_csv(PS1_TRIAGE)
    by_rank = {int(r["strict_rank"]): r for r in triage}

    if any(rank not in by_rank for rank in EXPECTED_RANKS):
        raise RuntimeError("REFUSING: missing PS1 triage row")

    print("Completed-stage guards: PASS")
    print(
        "Exposure interpretation follows current daschlab contract: "
        "wcssource=imwcs => imaging; finite limMagApass/Atlas => photometry."
    )
    print()

    exposure_rows = []
    current_rows = []
    source_rows = []
    census = {}

    # First enumerate ALL exposure lists and validate schemas before platephot.
    print("[1/2] Querying complete DASCH exposure lists ...")

    per_rank_exposures = {}

    required_exposure_cols = {
        "series", "platenum", "solnum", "wcssource",
        "limMagApass", "limMagAtlas",
    }

    for rank in EXPECTED_RANKS:
        r = by_rank[rank]
        mid_ra, mid_dec = midpoint_sky(r)

        raw, header, status = queryexps(rank, mid_ra, mid_dec)

        missing = required_exposure_cols - set(header)
        if missing:
            raise RuntimeError(
                f"REFUSING: strict #{rank:02d} queryexps missing documented "
                f"columns {sorted(missing)}; header={header}"
            )

        parsed = [
            parse_exposure(rank, mid_ra, mid_dec, row)
            for row in raw
        ]

        per_rank_exposures[rank] = parsed
        exposure_rows.extend(parsed)

        imaging = [e for e in parsed if e["has_imaging"]]
        phot = [
            e for e in parsed
            if e["selected_refcat_for_platephot"] is not None
        ]
        independent = [
            e for e in parsed
            if e["eligible_independent_platephot"]
        ]
        pair_exps = [
            e for e in parsed
            if e["is_pair_plate_ai44092"]
            and e["has_imaging"]
        ]

        unique_independent_plates = sorted({
            e["plate_id"] for e in independent if e["plate_id"]
        })

        census[rank] = {
            "queryexps_status": status,
            "total_exposures": len(parsed),
            "imaging_exposures": len(imaging),
            "photometric_exposures": len(phot),
            "independent_platephot_eligible_exposures": len(independent),
            "independent_physical_plates": len(unique_independent_plates),
            "ai44092_imaging_solutions": len(pair_exps),
            "apass_selected_exposures": sum(
                e["selected_refcat_for_platephot"] == "apass"
                for e in independent
            ),
            "atlas_fallback_exposures": sum(
                e["selected_refcat_for_platephot"] == "atlas"
                for e in independent
            ),
        }

        print(
            f"  strict #{rank:02d} {status.upper():6s} "
            f"total={len(parsed):4d} imaging={len(imaging):4d} "
            f"phot={len(phot):4d} independent={len(independent):4d} "
            f"plates={len(unique_independent_plates):4d} "
            f"ai44092-imaging-solutions={len(pair_exps)}",
            flush=True,
        )

    print("All 4 queryexps schemas/counts: PASS")
    print()
    print("[2/2] Inspecting official platephot context on ai44092 ...")

    for rank in EXPECTED_RANKS:
        r = by_rank[rank]

        dasch_ra = float(r["dasch_ra_deg"])
        dasch_dec = float(r["dasch_dec_deg"])
        mid_ra, mid_dec = midpoint_sky(r)

        pair_exps = [
            e for e in per_rank_exposures[rank]
            if e["is_pair_plate_ai44092"]
            and e["has_imaging"]
        ]

        if not pair_exps:
            # This would be a genuine contradiction with the native-mosaic
            # geometry used by the completed science run, so fail closed.
            raise RuntimeError(
                f"REFUSING: strict #{rank:02d} queryexps has no imaging "
                "solution for ai44092"
            )

        all_current_sources = []
        success_calls = 0
        failed_calls = 0
        advertised_attempts = 0
        failure_messages = []

        # For current-plate context, finite limMag at the query position is
        # NOT required. DASCH documents nSolutions*/resultId* as plate-level
        # evidence that a photometric calibration exists, while limMag* is
        # position-specific. Try every advertised refcat for every covering
        # ai44092 imaging solution; a solution-specific failure is audited
        # rather than treated as plate absence.
        seen_call = set()

        for e in pair_exps:
            candidate_refcats = []

            if (
                int(e["nSolutionsApass"]) > 0
                or bool(str(e["resultIdApass"]).strip())
            ):
                candidate_refcats.append("apass")

            if (
                int(e["nSolutionsAtlas"]) > 0
                or bool(str(e["resultIdAtlas"]).strip())
            ):
                candidate_refcats.append("atlas")

            for refcat in candidate_refcats:
                key = (e["plate_id"], e["solnum"], refcat)
                if key in seen_call:
                    continue
                seen_call.add(key)
                advertised_attempts += 1

                try:
                    rows, header, status = platephot(
                        rank,
                        e["plate_id"],
                        e["solnum"],
                        refcat,
                        dasch_ra,
                        dasch_dec,
                    )
                except RuntimeError as exc:
                    failed_calls += 1
                    failure_messages.append(
                        f"{e['plate_id']} sol={e['solnum']} "
                        f"refcat={refcat}: {exc}"
                    )
                    continue

                success_calls += 1

                normalized_header = {normkey(x) for x in header}
                if not (
                    {"radeg", "decdeg"} <= normalized_header
                    or {"ra", "dec"} <= normalized_header
                ):
                    raise RuntimeError(
                        f"REFUSING: strict #{rank:02d} successful platephot "
                        f"response has no usable RA/Dec columns; header={header}"
                    )

                for row in rows:
                    src = parse_platephot_source(
                        rank,
                        e["plate_id"],
                        e["solnum"],
                        refcat,
                        row,
                        dasch_ra,
                        dasch_dec,
                        mid_ra,
                        mid_dec,
                    )
                    if src is None:
                        continue

                    if (
                        src["sep_dasch_endpoint_arcsec"]
                        <= SOURCE_AUDIT_RADIUS_ARCSEC
                    ):
                        all_current_sources.append(src)

        if advertised_attempts == 0:
            context_status = "NO_ADVERTISED_PHOTOMETRIC_CALIBRATION_ON_AI44092"
        elif success_calls == 0:
            context_status = "OFFICIAL_PLATEPHOT_UNAVAILABLE_FOR_COVERING_SOLUTION"
        elif failed_calls:
            context_status = "PARTIAL_OFFICIAL_PLATEPHOT_CONTEXT"
        else:
            context_status = "OFFICIAL_PLATEPHOT_CONTEXT_COMPLETE"

        # Deduplicate identical source rows that might be returned by duplicate
        # queryexps records; keep solution/refcat distinct.
        dedup = {}
        for s in all_current_sources:
            key = (
                s["solution_number"],
                s["refcat"],
                round(float(s["ra_deg"]), 10),
                round(float(s["dec_deg"]), 10),
                s["ref_number"],
            )
            dedup[key] = s

        sources = sorted(
            dedup.values(),
            key=lambda s: (
                float(s["sep_dasch_endpoint_arcsec"]),
                s["solution_number"],
                s["refcat"],
            )
        )
        source_rows.extend(sources)

        nearest_any = sources[0] if sources else None
        unmatched = [s for s in sources if not s["is_catalog_matched"]]
        nearest_unmatched = unmatched[0] if unmatched else None

        def val(src, key):
            return None if src is None else src.get(key)

        within3 = sum(
            float(s["sep_dasch_endpoint_arcsec"]) <= STRONG_CONTEXT_ARCSEC
            for s in sources
        )
        within5 = sum(
            float(s["sep_dasch_endpoint_arcsec"]) <= DIAGNOSTIC_CONTEXT_ARCSEC
            for s in sources
        )

        current_rows.append({
            "strict_rank": rank,
            "dasch_ra_deg": dasch_ra,
            "dasch_dec_deg": dasch_dec,
            "pair_mid_ra_deg": mid_ra,
            "pair_mid_dec_deg": mid_dec,
            "ai44092_queryexps_solution_count": len(pair_exps),
            "ai44092_imaging_solution_count": len(pair_exps),
            "ai44092_advertised_refcat_attempts": advertised_attempts,
            "ai44092_platephot_success_calls": success_calls,
            "ai44092_platephot_failed_calls": failed_calls,
            "ai44092_context_status": context_status,
            "nearest_any_sep_arcsec": val(
                nearest_any, "sep_dasch_endpoint_arcsec"
            ),
            "nearest_any_solution_number": val(
                nearest_any, "solution_number"
            ),
            "nearest_any_refcat": val(nearest_any, "refcat"),
            "nearest_any_ref_number": val(nearest_any, "ref_number"),
            "nearest_any_is_catalog_matched": val(
                nearest_any, "is_catalog_matched"
            ),
            "nearest_any_magcal_magdep": val(
                nearest_any, "magcal_magdep"
            ),
            "nearest_any_fwhm_world_arcsec": val(
                nearest_any, "fwhm_world_arcsec"
            ),
            "nearest_any_ellipticity": val(
                nearest_any, "ellipticity"
            ),
            "nearest_any_catalog_sep_arcsec": val(
                nearest_any, "detected_to_catalog_sep_arcsec"
            ),
            "nearest_unmatched_sep_arcsec": val(
                nearest_unmatched, "sep_dasch_endpoint_arcsec"
            ),
            "nearest_unmatched_solution_number": val(
                nearest_unmatched, "solution_number"
            ),
            "nearest_unmatched_refcat": val(
                nearest_unmatched, "refcat"
            ),
            "nearest_unmatched_magcal_magdep": val(
                nearest_unmatched, "magcal_magdep"
            ),
            "nearest_unmatched_fwhm_world_arcsec": val(
                nearest_unmatched, "fwhm_world_arcsec"
            ),
            "sources_within_3arcsec": within3,
            "sources_within_5arcsec": within5,
            "sources_within_60arcsec": len(sources),
        })

        anytxt = (
            "none"
            if nearest_any is None
            else (
                f"{nearest_any['sep_dasch_endpoint_arcsec']:.3f}\" "
                f"{'matched' if nearest_any['is_catalog_matched'] else 'UNMATCHED'} "
                f"FWHM={nearest_any['fwhm_world_arcsec']}"
            )
        )
        unmtxt = (
            "none"
            if nearest_unmatched is None
            else f"{nearest_unmatched['sep_dasch_endpoint_arcsec']:.3f}\""
        )

        print(
            f"  strict #{rank:02d} imaging-sol={len(pair_exps)} "
            f"attempts={advertised_attempts} ok={success_calls} fail={failed_calls} "
            f"status={context_status} "
            f"nearest={anytxt} nearest-unmatched={unmtxt}",
            flush=True,
        )

    write_csv(OUT_EXPOSURES, exposure_rows, EXPOSURE_FIELDS)
    write_csv(OUT_CURRENT, current_rows, CURRENT_FIELDS)
    write_csv(OUT_SOURCES, source_rows, SOURCE_FIELDS)

    total_eligible = sum(
        census[r]["independent_platephot_eligible_exposures"]
        for r in EXPECTED_RANKS
    )

    total_unique_rank_plate_pairs = sum(
        census[r]["independent_physical_plates"]
        for r in EXPECTED_RANKS
    )

    report = {
        "status": "COMPLETE",
        "analysis_kind": (
            "order61_ai44092_platephot_context_and_independent_exposure_census"
        ),
        "guards": guards,
        "input_ranks": EXPECTED_RANKS,
        "current_plate_id": PAIR_PLATE_ID,
        "source_audit_radius_arcsec": SOURCE_AUDIT_RADIUS_ARCSEC,
        "context_radii_arcsec": {
            "strong": STRONG_CONTEXT_ARCSEC,
            "diagnostic": DIAGNOSTIC_CONTEXT_ARCSEC,
        },
        "exposure_selection_contract": {
            "has_imaging": "wcssource == imwcs and valid solnum",
            "has_apass_phot": (
                "finite limMagApass at the query position on an imaged exposure"
            ),
            "has_atlas_phot": (
                "finite limMagAtlas at the query position on an imaged exposure"
            ),
            "current_ai44092_context_exception": (
                "for current-plate context only, any covering imaging solution "
                "may be queried with a refcat advertised by nSolutions*/resultId*, "
                "even when the position-specific limMag* is non-finite"
            ),
            "future_platephot_refcat_choice": (
                "APASS when available, otherwise ATLAS fallback"
            ),
            "exclude_current_pair_physical_plate": PAIR_PLATE_ID,
            "multiple_exposure_policy": (
                "retain each covering WCS solution; recurrence confirmation "
                "must ultimately use distinct physical plate IDs"
            ),
        },
        "per_rank_census": {
            str(k): v for k, v in census.items()
        },
        "total_independent_platephot_eligible_exposures_across_ranks": (
            total_eligible
        ),
        "total_independent_physical_plate_counts_across_ranks": (
            total_unique_rank_plate_pairs
        ),
        "no_candidate_deleted": True,
        "detector_rerun": False,
        "science_image_pixels_read": False,
        "official_dasch_platephot_queried": True,
        "outputs": {
            "exposure_census_csv": str(OUT_EXPOSURES),
            "ai44092_context_csv": str(OUT_CURRENT),
            "ai44092_sources_within60arcsec_csv": str(OUT_SOURCES),
        },
        "next_stage": (
            "Use the exposure census to execute a resumable independent-plate "
            "platephot recurrence search. The run scope can be exhaustive if "
            "the eligible exposure count is tractable; otherwise use a "
            "prospectively fixed staged expansion based only on exposure "
            "metadata/API workload, not candidate outcomes."
        ),
    }

    write_json(OUT_REPORT, report)

    print()
    print("=" * 94)
    print("AI44092 PLATEPHOT CONTEXT + EXPOSURE CENSUS COMPLETE")
    print("=" * 94)

    for rank in EXPECTED_RANKS:
        c = census[rank]
        q = next(r for r in current_rows if int(r["strict_rank"]) == rank)
        near = q["nearest_any_sep_arcsec"]
        near_txt = "none" if near is None else f"{float(near):.3f}\""

        print(
            f"strict #{rank:02d}: independent eligible exposures="
            f"{c['independent_platephot_eligible_exposures']} "
            f"physical plates={c['independent_physical_plates']} "
            f"| ai44092 nearest official photometry={near_txt}"
        )

    print()
    print(
        "Total independent eligible exposure calls across all four ranks: "
        f"{total_eligible}"
    )
    print()
    print("Outputs:")
    print(" ", OUT_REPORT)
    print(" ", OUT_EXPOSURES)
    print(" ", OUT_CURRENT)
    print(" ", OUT_SOURCES)
    print()
    print("No detector was rerun.")
    print("No science image pixel was read.")
    print("No candidate was deleted.")


if __name__ == "__main__":
    main()
