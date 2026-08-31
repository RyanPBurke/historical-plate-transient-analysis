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
BASE = ROOT / "results" / "order01_native_full_v028"
WORK = ROOT / "work" / "order01_platephot_stage1_v028"
CACHE = WORK / "api_cache"

PAIR_REPORT = BASE / "order01_whole_pair_report.json"
EXPOSURE_CENSUS = BASE / "order01_queryexps_exposure_census_v028c.csv"
PS1_TRIAGE = BASE / "order01_ps1_static_triage_v028.csv"
CATALOG_REC_REPORT = BASE / "order01_dasch_catalog_recurrence_report_v028c.json"
INJ_REPORT = BASE / "order01_injection_recovery_report_v028.json"

MANIFEST = BASE / "order01_platephot_stage1_manifest_v028c.csv"
POLICY = BASE / "order01_platephot_stage1_policy_v028c.json"
DETAIL = BASE / "order01_platephot_stage1_detail_v028c.csv"
PLATE_SUMMARY = BASE / "order01_platephot_stage1_plate_summary_v028c.csv"
RANK_SUMMARY = BASE / "order01_platephot_stage1_rank_summary_v028c.csv"
REPORT = BASE / "order01_platephot_stage1_report_v028c.json"

for d in (WORK, CACHE):
    d.mkdir(parents=True, exist_ok=True)

API = "https://api.starglass.cfa.harvard.edu/public/dasch/dr7/platephot"
QUERYEXPS = "https://api.starglass.cfa.harvard.edu/public/dasch/dr7/queryexps"
UA = "historical-transient-pipeline/0.2.8-order01-platephot-stage1-v028c"

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

ORIGINAL_RANKS = [5, 6, 8, 10, 12, 24, 25, 26, 29, 30, 36]
RANKS = []
DISCOVERY_PLATE = "ai43437"
PAIR_PLATE_ID = DISCOVERY_PLATE

# ------------------------------------------------------------------
# PROSPECTIVELY FIXED STAGE-1 DESIGN
# ------------------------------------------------------------------
PLATES_PER_RANK = 64
SELECTION_SALT = "order61-platephot-stage1-v028-sha256-blind"
STRONG_ARCSEC = 3.0
DIAGNOSTIC_ARCSEC = 5.0
LOCAL_DENSITY_RADIUS_ARCSEC = 60.0
MIN_INDEPENDENT_RECURRENCE_PLATES = 2
REQUEST_PAUSE_S = 0.25
MAX_ATTEMPTS = 4

MANIFEST_FIELDS = [
    "stage_order",
    "strict_rank",
    "rank_sample_order",
    "selection_sha256",
    "plate_id",
    "series",
    "platenum",
    "solnum",
    "expnum",
    "expdate",
    "selected_refcat_for_platephot",
    "limMagApass",
    "limMagAtlas",
    "centerdist",
    "edgedist",
    "target_ra_deg",
    "target_dec_deg",
]

DETAIL_FIELDS = [
    "strict_rank",
    "rank_sample_order",
    "plate_id",
    "solution_number",
    "refcat",
    "source_index",
    "ra_deg",
    "dec_deg",
    "sep_target_arcsec",
    "within_3arcsec",
    "within_5arcsec",
    "within_60arcsec",
    "ref_number",
    "catalog_matched",
    "catalog_ra_deg",
    "catalog_dec_deg",
    "magcal_magdep",
    "fwhm_world_raw",
    "ellipticity",
    "aflags",
    "bflags",
    "plate_quality_flag",
]

PLATE_FIELDS = [
    "strict_rank",
    "rank_sample_order",
    "plate_id",
    "solution_number",
    "refcat",
    "api_status",
    "response_rows",
    "sources_within_60arcsec",
    "sources_within_5arcsec",
    "sources_within_3arcsec",
    "nearest_sep_arcsec",
    "nearest_ref_number",
    "nearest_catalog_matched",
    "nearest_magcal_magdep",
    "expected_chance_within_3_from_local60",
    "expected_chance_within_5_from_local60",
]

RANK_FIELDS = [
    "strict_rank",
    "selected_plates",
    "completed_plates",
    "failed_plates",
    "plates_with_source_within_3arcsec",
    "plates_with_source_within_5arcsec",
    "total_sources_within_60arcsec",
    "observed_sources_within_3arcsec",
    "observed_sources_within_5arcsec",
    "expected_chance_within_3_from_local60",
    "expected_chance_within_5_from_local60",
    "multi_independent_plate_recurrence_3arcsec",
    "multi_independent_plate_recurrence_5arcsec",
    "single_independent_plate_match_3arcsec",
    "single_independent_plate_match_5arcsec",
    "stage1_complete",
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


def sha256_bytes(data: bytes):
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


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


def as_bool(v):
    return str(v).strip().lower() in {"true", "1", "yes", "y", "t"}


def normkey(k):
    return "".join(ch for ch in str(k).lower() if ch.isalnum())


def getv(row, *aliases):
    nr = {normkey(k): v for k, v in row.items()}
    for a in aliases:
        k = normkey(a)
        if k in nr:
            return nr[k]
    return None


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


def parse_json_csv_lines(obj, label):
    if not isinstance(obj, list):
        raise RuntimeError(
            f"{label}: expected JSON list, got {type(obj).__name__}"
        )
    if not obj:
        raise RuntimeError(f"{label}: empty response; no CSV header")
    if not all(isinstance(x, str) for x in obj):
        raise RuntimeError(f"{label}: non-string response record")

    text = "\n".join(x.rstrip("\r\n") for x in obj) + "\n"
    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None:
        raise RuntimeError(f"{label}: missing CSV header")
    return list(reader), list(reader.fieldnames)


def curl_platephot(item):
    rank = int(item["strict_rank"])
    plate = item["plate_id"]
    solnum = int(item["solnum"])
    refcat = item["selected_refcat_for_platephot"]

    stem = (
        f"r{rank:02d}_{int(item['rank_sample_order']):03d}_"
        f"{plate}_s{solnum}_{refcat}"
    )
    raw_path = CACHE / f"{stem}.json"
    meta_path = CACHE / f"{stem}.meta.json"

    payload = {
        "plate_id": plate,
        "solution_number": solnum,
        "refcat": refcat,
        "center_ra_deg": float(item["target_ra_deg"]),
        "center_dec_deg": float(item["target_dec_deg"]),
    }

    if raw_path.is_file() and meta_path.is_file():
        raw = raw_path.read_bytes()
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        if (
            meta.get("complete") is True
            and meta.get("payload") == payload
            and meta.get("sha256") == sha256_bytes(raw)
        ):
            obj = json.loads(raw.decode("utf-8"))
            rows, header = parse_json_csv_lines(obj, stem)
            return rows, header, "cached"

    curl = shutil.which("curl.exe") or shutil.which("curl")
    if not curl:
        raise RuntimeError("curl.exe/curl not found; TLS will not be weakened")

    payload_text = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    part = raw_path.with_suffix(".json.part")
    errors = []

    for attempt in range(1, MAX_ATTEMPTS + 1):
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
            API,
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
                raise RuntimeError(f"curl exit {cp.returncode}: {err[:600]}")

            if not part.is_file():
                raise RuntimeError("curl success without response file")

            raw = part.read_bytes()
            obj = json.loads(raw.decode("utf-8"))
            rows, header = parse_json_csv_lines(obj, stem)

            part.replace(raw_path)
            write_json(meta_path, {
                "complete": True,
                "payload": payload,
                "sha256": sha256_bytes(raw),
                "bytes": len(raw),
                "row_count": len(rows),
                "transport": "curl_verified_https",
                "tls_verification_disabled": False,
            })

            time.sleep(REQUEST_PAUSE_S)
            return rows, header, "done"

        except (
            subprocess.TimeoutExpired,
            RuntimeError,
            OSError,
            json.JSONDecodeError,
        ) as exc:
            errors.append(repr(exc))
            print(
                f"    {stem} attempt {attempt}/{MAX_ATTEMPTS} FAILED: {exc}",
                flush=True,
            )
            if part.exists():
                try:
                    part.unlink()
                except OSError:
                    pass
            if attempt < MAX_ATTEMPTS:
                time.sleep(2 ** attempt)

    raise RuntimeError(errors[-1])


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
    "is_pair_plate_ai43437",
    "eligible_independent_platephot",
]

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
        "is_pair_plate_ai43437": is_pair,
        "eligible_independent_platephot": bool(
            selected is not None and not is_pair
        ),
    }




def build_manifest(census, triage):
    target_by_rank = {
        int(r["strict_rank"]): (
            float(r["dasch_ra_deg"]),
            float(r["dasch_dec_deg"]),
        )
        for r in triage
        if int(r["strict_rank"]) in RANKS
    }

    rows = []

    for rank in RANKS:
        eligible = [
            r for r in census
            if int(r["strict_rank"]) == rank
            and as_bool(r["eligible_independent_platephot"])
            and str(r["plate_id"]).strip().lower() != DISCOVERY_PLATE
        ]

        # One covering exposure per physical plate. The completed preflight
        # showed these are effectively one-to-one, but enforce it explicitly.
        by_plate = {}
        for r in eligible:
            pid = str(r["plate_id"]).strip().lower()
            key = (
                int(r["solnum"]),
                str(r["selected_refcat_for_platephot"]),
                str(r.get("expdate", "")),
            )
            if pid not in by_plate or key < by_plate[pid][0]:
                by_plate[pid] = (key, r)

        candidates = []

        for pid, (_, r) in by_plate.items():
            token = (
                f"{SELECTION_SALT}|rank={rank}|plate={pid}|"
                f"sol={r['solnum']}|refcat={r['selected_refcat_for_platephot']}"
            )
            h = hashlib.sha256(token.encode("utf-8")).hexdigest()
            candidates.append((h, pid, r))

        candidates.sort(key=lambda q: (q[0], q[1]))

        if len(candidates) < PLATES_PER_RANK:
            raise RuntimeError(
                f"rank {rank}: only {len(candidates)} eligible independent "
                f"plates; need {PLATES_PER_RANK}"
            )

        ra, dec = target_by_rank[rank]

        for sample_order, (h, pid, r) in enumerate(
            candidates[:PLATES_PER_RANK],
            1,
        ):
            rows.append({
                "stage_order": 0,  # filled after global ordering
                "strict_rank": rank,
                "rank_sample_order": sample_order,
                "selection_sha256": h,
                "plate_id": pid,
                "series": r["series"],
                "platenum": r["platenum"],
                "solnum": int(r["solnum"]),
                "expnum": r["expnum"],
                "expdate": r["expdate"],
                "selected_refcat_for_platephot": (
                    r["selected_refcat_for_platephot"]
                ),
                "limMagApass": r["limMagApass"],
                "limMagAtlas": r["limMagAtlas"],
                "centerdist": r["centerdist"],
                "edgedist": r["edgedist"],
                "target_ra_deg": ra,
                "target_dec_deg": dec,
            })

    # Interleave ranks so a partial interruption has similar coverage for all.
    rows.sort(key=lambda r: (
        int(r["rank_sample_order"]),
        int(r["strict_rank"]),
    ))
    for i, r in enumerate(rows, 1):
        r["stage_order"] = i

    return rows


def parse_source(rank, sample_order, plate, solnum, refcat, idx, row, tra, tdec):
    ra = ffloat(getv(row, "ra_deg", "raDeg", "ra"))
    dec = ffloat(getv(row, "dec_deg", "decDeg", "dec"))
    if ra is None or dec is None:
        return None

    sep = angular_sep_arcsec(tra, tdec, ra, dec)
    refnum = fint(getv(row, "ref_number", "refNumber"))
    cra = ffloat(getv(row, "catalog_ra", "catalogRa"))
    cdec = ffloat(getv(row, "catalog_dec", "catalogDec"))

    return {
        "strict_rank": rank,
        "rank_sample_order": sample_order,
        "plate_id": plate,
        "solution_number": solnum,
        "refcat": refcat,
        "source_index": idx,
        "ra_deg": ra,
        "dec_deg": dec,
        "sep_target_arcsec": sep,
        "within_3arcsec": sep <= STRONG_ARCSEC,
        "within_5arcsec": sep <= DIAGNOSTIC_ARCSEC,
        "within_60arcsec": sep <= LOCAL_DENSITY_RADIUS_ARCSEC,
        "ref_number": refnum,
        "catalog_matched": refnum is not None and refnum >= 0,
        "catalog_ra_deg": cra,
        "catalog_dec_deg": cdec,
        "magcal_magdep": ffloat(getv(row, "magcal_magdep", "magcalMagdep")),
        "fwhm_world_raw": ffloat(getv(row, "fwhm_world", "fwhmWorld", "fwhmDeg")),
        "ellipticity": ffloat(getv(row, "ellipticity")),
        "aflags": fint(getv(row, "aflags")),
        "bflags": fint(getv(row, "bflags")),
        "plate_quality_flag": fint(getv(
            row, "plate_quality_flag", "plateQualityFlag"
        )),
    }


def main():
    global RANKS

    print("=" * 104)
    print("ORDER 01 — SURVIVOR-DRIVEN DASCH INDEPENDENT-PLATE RECURRENCE: FIXED STAGE 1 v028c")
    print("=" * 104)
    print(
        "Reads the completed catalogue-recurrence screen, enumerates official "
        "DASCH coverage, freezes the blind 64-plate prefix, then executes platephot."
    )
    print(
        "The discovery plate ai43437 is excluded. Selection uses the same fixed "
        "SHA256 salt/order as Order 61 and does not use morphology, source density, "
        "date, limiting magnitude, or recurrence outcomes."
    )
    print()

    for p in (
        PAIR_REPORT,
        PS1_TRIAGE,
        CATALOG_REC_REPORT,
        INJ_REPORT,
    ):
        if not p.is_file():
            raise RuntimeError(f"Missing required completed-stage file: {p}")

    pair_report = json.loads(PAIR_REPORT.read_text(encoding="utf-8"))
    rec_report = json.loads(CATALOG_REC_REPORT.read_text(encoding="utf-8"))
    inj_report = json.loads(INJ_REPORT.read_text(encoding="utf-8"))

    rec_inputs = [int(x) for x in rec_report.get("input_ranks", [])]
    rec_survivors = [
        int(x) for x in rec_report.get("survivor_ranks_5arcsec", [])
    ]

    guards = {
        "pair_complete": pair_report.get("status") == "COMPLETE",
        "order": int(pair_report.get("canonical_order", -1)) == 1,
        "detector": pair_report.get("detector_sha256") == EXPECTED_DETECTOR_SHA,
        "method": pair_report.get("method_sha256") == EXPECTED_METHOD_SHA,
        "policy": pair_report.get("policy_sha256") == EXPECTED_POLICY_SHA,
        "catalog_recurrence_complete": rec_report.get("status") == "COMPLETE",
        "catalog_recurrence_kind_v028b": (
            rec_report.get("analysis_kind")
            == "order01_dasch_dr7_catalogued_historical_recurrence_v028c"
        ),
        "catalog_recurrence_inputs": rec_inputs == ORIGINAL_RANKS,
        "catalog_recurrence_survivor_subset": set(rec_survivors) <= set(ORIGINAL_RANKS),
        "injection_complete": inj_report.get("status") == "COMPLETE",
        "injection_ranks": (
            [int(x) for x in inj_report.get("survivor_ranks", [])]
            == ORIGINAL_RANKS
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

    RANKS = rec_survivors

    triage = read_csv(PS1_TRIAGE)
    by_rank = {int(r["strict_rank"]): r for r in triage}
    if any(rank not in by_rank for rank in ORIGINAL_RANKS):
        raise RuntimeError(
            "REFUSING: PS1 triage is missing one or more original Order-1 ranks"
        )

    print("Completed-stage guards: PASS")
    print(f"Catalogue-recurrence input ranks:  {ORIGINAL_RANKS}")
    print(f"Catalogue-recurrence clean ranks:  {RANKS}")
    print()

    if not RANKS:
        write_csv(EXPOSURE_CENSUS, [], EXPOSURE_FIELDS)
        write_csv(MANIFEST, [], MANIFEST_FIELDS)
        policy_obj = {
            "analysis_kind": "order01_platephot_recurrence_stage1_fixed_v028c",
            "active_ranks": [],
            "reason_no_calls": (
                "No rank survived the fixed <=5 arcsec catalogued DASCH "
                "multi-plate recurrence screen."
            ),
            "selection_salt": SELECTION_SALT,
            "strong_arcsec": STRONG_ARCSEC,
            "diagnostic_arcsec": DIAGNOSTIC_ARCSEC,
            "minimum_independent_recurrence_plates":
                MIN_INDEPENDENT_RECURRENCE_PLATES,
            "discovery_plate_excluded": DISCOVERY_PLATE,
        }
        write_json(POLICY, policy_obj)
        report = {
            "status": "COMPLETE_NO_ACTIVE_RANKS",
            "analysis_kind": "order01_platephot_recurrence_stage1_v028c",
            "guards": guards,
            "catalog_recurrence_survivors": [],
            "selected_call_count": 0,
            "completed_call_count": 0,
            "failed_call_count": 0,
            "rank_summaries": [],
            "no_candidate_deleted": True,
            "detector_rerun": False,
            "science_image_pixels_read": False,
        }
        write_json(REPORT, report)
        print("No catalogue-recurrence-clean ranks remain; Stage 1 requires no calls.")
        print("Report:", REPORT)
        return

    # --------------------------------------------------------------
    # Official queryexps census for the active recurrence-clean ranks.
    # --------------------------------------------------------------
    print("[1/2] Enumerating official DASCH exposure coverage ...")
    exposure_rows = []
    required_exposure_cols = {
        "series", "platenum", "solnum", "wcssource",
        "limMagApass", "limMagAtlas",
    }

    for rank in RANKS:
        r = by_rank[rank]
        qra, qdec = midpoint_sky(r)
        raw, header, status = queryexps(rank, qra, qdec)

        missing = required_exposure_cols - set(header)
        if missing:
            raise RuntimeError(
                f"REFUSING: strict #{rank:02d} queryexps missing documented "
                f"columns {sorted(missing)}; header={header}"
            )

        parsed = [
            parse_exposure(rank, qra, qdec, row)
            for row in raw
        ]
        exposure_rows.extend(parsed)

        independent = [
            e for e in parsed if e["eligible_independent_platephot"]
        ]
        physical = sorted({
            e["plate_id"] for e in independent if e["plate_id"]
        })

        print(
            f"  strict #{rank:02d} {status.upper():6s} "
            f"total={len(parsed):5d} independent={len(independent):5d} "
            f"physical_plates={len(physical):5d}",
            flush=True,
        )

        if len(physical) < PLATES_PER_RANK:
            raise RuntimeError(
                f"rank {rank}: only {len(physical)} eligible independent physical "
                f"plates; fixed Stage-1 requires {PLATES_PER_RANK}"
            )

    write_csv(EXPOSURE_CENSUS, exposure_rows, EXPOSURE_FIELDS)
    exposure_sha = sha256_file(EXPOSURE_CENSUS)
    print(f"Exposure census: {EXPOSURE_CENSUS}")
    print(f"Exposure census SHA256: {exposure_sha}")
    print()

    # --------------------------------------------------------------
    # Freeze the exact Stage-1 sample before the first independent
    # platephot result is requested.
    # --------------------------------------------------------------
    manifest_rows = build_manifest(exposure_rows, triage)
    write_csv(MANIFEST, manifest_rows, MANIFEST_FIELDS)
    manifest_sha = sha256_file(MANIFEST)

    policy_obj = {
        "analysis_kind": "order01_platephot_recurrence_stage1_fixed_v028c",
        "active_ranks": RANKS,
        "catalog_recurrence_report_sha256": sha256_file(CATALOG_REC_REPORT),
        "exposure_census_sha256": exposure_sha,
        "plates_per_rank": PLATES_PER_RANK,
        "selection": (
            "one eligible exposure per physical plate, then ascending SHA256 "
            "of the historically fixed Order-61 salt + rank + plate_id + "
            "solnum + refcat"
        ),
        "selection_salt": SELECTION_SALT,
        "selection_salt_reused_from_order61": True,
        "manifest_sha256": manifest_sha,
        "strong_arcsec": STRONG_ARCSEC,
        "diagnostic_arcsec": DIAGNOSTIC_ARCSEC,
        "local_density_radius_arcsec": LOCAL_DENSITY_RADIUS_ARCSEC,
        "minimum_independent_recurrence_plates":
            MIN_INDEPENDENT_RECURRENCE_PLATES,
        "discovery_plate_excluded": DISCOVERY_PLATE,
        "selection_uses_candidate_outcomes": False,
        "selection_uses_morphology": False,
        "selection_uses_source_density": False,
        "selection_uses_exposure_date": False,
        "selection_uses_limiting_magnitude": False,
        "catalog_querycat_unresolved_rows_are_retained_for_platephot": True,
        "api": API,
        "transport": "curl_verified_https",
        "tls_verification_disabled": False,
    }
    write_json(POLICY, policy_obj)
    policy_sha = sha256_file(POLICY)

    print("[2/2] Frozen Stage-1 recurrence sample")
    print(f"  active ranks:       {RANKS}")
    print(f"  calls selected:     {len(manifest_rows)}")
    print(f"  manifest SHA256:    {manifest_sha}")
    print(f"  policy SHA256:      {policy_sha}")
    print("Manifest/policy frozen before first independent platephot request: PASS")
    print()

    detail_rows = []
    plate_rows = []
    failures = []

    for i, item in enumerate(manifest_rows, 1):
        rank = int(item["strict_rank"])
        plate = item["plate_id"]
        solnum = int(item["solnum"])
        refcat = item["selected_refcat_for_platephot"]
        tra = float(item["target_ra_deg"])
        tdec = float(item["target_dec_deg"])

        try:
            rows, header, status = curl_platephot(item)
        except RuntimeError as exc:
            failures.append({
                "stage_order": i,
                "strict_rank": rank,
                "plate_id": plate,
                "solnum": solnum,
                "refcat": refcat,
                "error": str(exc),
            })
            print(
                f"  [{i:04d}/{len(manifest_rows):04d}] rank #{rank:02d} "
                f"{plate} s{solnum} {refcat}: FAILED",
                flush=True,
            )
            continue

        sources = []
        for j, row in enumerate(rows, 1):
            s = parse_source(
                rank,
                int(item["rank_sample_order"]),
                plate,
                solnum,
                refcat,
                j,
                row,
                tra,
                tdec,
            )
            if s is not None:
                sources.append(s)

        detail_rows.extend(sources)

        local60 = [s for s in sources if s["within_60arcsec"]]
        close5 = [s for s in sources if s["within_5arcsec"]]
        close3 = [s for s in sources if s["within_3arcsec"]]

        nearest = min(
            sources,
            key=lambda s: float(s["sep_target_arcsec"]),
            default=None,
        )

        n60 = len(local60)
        exp3 = n60 * (STRONG_ARCSEC / LOCAL_DENSITY_RADIUS_ARCSEC) ** 2
        exp5 = n60 * (DIAGNOSTIC_ARCSEC / LOCAL_DENSITY_RADIUS_ARCSEC) ** 2

        plate_rows.append({
            "strict_rank": rank,
            "rank_sample_order": int(item["rank_sample_order"]),
            "plate_id": plate,
            "solution_number": solnum,
            "refcat": refcat,
            "api_status": status,
            "response_rows": len(rows),
            "sources_within_60arcsec": n60,
            "sources_within_5arcsec": len(close5),
            "sources_within_3arcsec": len(close3),
            "nearest_sep_arcsec":
                None if nearest is None else nearest["sep_target_arcsec"],
            "nearest_ref_number":
                None if nearest is None else nearest["ref_number"],
            "nearest_catalog_matched":
                None if nearest is None else nearest["catalog_matched"],
            "nearest_magcal_magdep":
                None if nearest is None else nearest["magcal_magdep"],
            "expected_chance_within_3_from_local60": exp3,
            "expected_chance_within_5_from_local60": exp5,
        })

        nearest_txt = (
            "none"
            if nearest is None
            else f'{float(nearest["sep_target_arcsec"]):.2f}"'
        )
        print(
            f"  [{i:04d}/{len(manifest_rows):04d}] rank #{rank:02d} "
            f"{plate} {status.upper():6s} "
            f"n60={n60:3d} <=5={len(close5)} <=3={len(close3)} "
            f"nearest={nearest_txt}",
            flush=True,
        )

        if i % 16 == 0:
            write_csv(DETAIL, detail_rows, DETAIL_FIELDS)
            write_csv(PLATE_SUMMARY, plate_rows, PLATE_FIELDS)

    write_csv(DETAIL, detail_rows, DETAIL_FIELDS)
    write_csv(PLATE_SUMMARY, plate_rows, PLATE_FIELDS)

    rank_rows = []
    for rank in RANKS:
        selected = [
            r for r in manifest_rows if int(r["strict_rank"]) == rank
        ]
        done = [
            r for r in plate_rows if int(r["strict_rank"]) == rank
        ]
        fail = [
            r for r in failures if int(r["strict_rank"]) == rank
        ]

        p3 = [r for r in done if int(r["sources_within_3arcsec"]) > 0]
        p5 = [r for r in done if int(r["sources_within_5arcsec"]) > 0]

        obs3 = sum(int(r["sources_within_3arcsec"]) for r in done)
        obs5 = sum(int(r["sources_within_5arcsec"]) for r in done)
        n60 = sum(int(r["sources_within_60arcsec"]) for r in done)
        exp3 = sum(
            float(r["expected_chance_within_3_from_local60"]) for r in done
        )
        exp5 = sum(
            float(r["expected_chance_within_5_from_local60"]) for r in done
        )

        rank_rows.append({
            "strict_rank": rank,
            "selected_plates": len(selected),
            "completed_plates": len(done),
            "failed_plates": len(fail),
            "plates_with_source_within_3arcsec": len(p3),
            "plates_with_source_within_5arcsec": len(p5),
            "total_sources_within_60arcsec": n60,
            "observed_sources_within_3arcsec": obs3,
            "observed_sources_within_5arcsec": obs5,
            "expected_chance_within_3_from_local60": exp3,
            "expected_chance_within_5_from_local60": exp5,
            "multi_independent_plate_recurrence_3arcsec":
                len(p3) >= MIN_INDEPENDENT_RECURRENCE_PLATES,
            "multi_independent_plate_recurrence_5arcsec":
                len(p5) >= MIN_INDEPENDENT_RECURRENCE_PLATES,
            "single_independent_plate_match_3arcsec": len(p3) == 1,
            "single_independent_plate_match_5arcsec": len(p5) == 1,
            "stage1_complete":
                len(fail) == 0 and len(done) == len(selected),
        })

    write_csv(RANK_SUMMARY, rank_rows, RANK_FIELDS)

    status = "COMPLETE" if not failures else "INCOMPLETE_API_FAILURES"
    recurrent5 = [
        int(r["strict_rank"])
        for r in rank_rows
        if r["multi_independent_plate_recurrence_5arcsec"]
    ]
    clean5 = [
        int(r["strict_rank"])
        for r in rank_rows
        if not r["multi_independent_plate_recurrence_5arcsec"]
    ]

    report = {
        "status": status,
        "analysis_kind": "order01_platephot_recurrence_stage1_v028c",
        "guards": guards,
        "catalog_recurrence_input_ranks": ORIGINAL_RANKS,
        "catalog_recurrence_clean_active_ranks": RANKS,
        "manifest_sha256": manifest_sha,
        "policy_sha256": policy_sha,
        "fixed_policy": policy_obj,
        "selected_call_count": len(manifest_rows),
        "completed_call_count": len(plate_rows),
        "failed_call_count": len(failures),
        "failures": failures,
        "rank_summaries": rank_rows,
        "stage1_recurrent_ranks_5arcsec": recurrent5,
        "stage1_clean_ranks_5arcsec": clean5,
        "no_candidate_deleted": True,
        "detector_rerun": False,
        "science_image_pixels_read": False,
        "outputs": {
            "exposure_census_csv": str(EXPOSURE_CENSUS),
            "manifest_csv": str(MANIFEST),
            "policy_json": str(POLICY),
            "detail_csv": str(DETAIL),
            "plate_summary_csv": str(PLATE_SUMMARY),
            "rank_summary_csv": str(RANK_SUMMARY),
        },
        "next_stage_if_complete": (
            "Retain Stage-1 recurrent ranks as static-contamination audit cases. "
            "For Stage-1-clean ranks only, expand the identical blind SHA256 "
            "ordering from cumulative 64 to cumulative 256 without changing "
            "the sample prefix or 3/5-arcsec gates."
        ),
    }
    write_json(REPORT, report)

    print()
    print("=" * 104)
    print("ORDER 01 PLATEPHOT RECURRENCE STAGE 1 " + status)
    print("=" * 104)
    print(
        f"Calls selected/completed/failed: "
        f"{len(manifest_rows)}/{len(plate_rows)}/{len(failures)}"
    )
    print()

    for r in rank_rows:
        print(
            f"strict #{int(r['strict_rank']):02d}: "
            f'plates <=3"={int(r["plates_with_source_within_3arcsec"])} '
            f'<=5"={int(r["plates_with_source_within_5arcsec"])} '
            f'| observed <=3"={int(r["observed_sources_within_3arcsec"])} '
            f'(chance~{float(r["expected_chance_within_3_from_local60"]):.3f}) '
            f'<=5"={int(r["observed_sources_within_5arcsec"])} '
            f'(chance~{float(r["expected_chance_within_5_from_local60"]):.3f}) '
            f'| recurrent3={r["multi_independent_plate_recurrence_3arcsec"]} '
            f'recurrent5={r["multi_independent_plate_recurrence_5arcsec"]}'
        )

    print()
    print("Stage-1 recurrent <=5\" ranks:", recurrent5)
    print("Stage-1 clean <=5\" ranks:    ", clean5)
    print()
    print("Outputs:")
    print(" ", REPORT)
    print(" ", EXPOSURE_CENSUS)
    print(" ", MANIFEST)
    print(" ", POLICY)
    print(" ", DETAIL)
    print(" ", PLATE_SUMMARY)
    print(" ", RANK_SUMMARY)
    print()
    print("No detector was rerun.")
    print("No science image pixel was read.")
    print("No candidate was deleted.")


if __name__ == "__main__":
    main()
