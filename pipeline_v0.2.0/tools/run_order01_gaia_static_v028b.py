from __future__ import annotations

from pathlib import Path
from datetime import datetime, timezone
from io import StringIO
import csv
import hashlib
import json
import math
import time
import urllib.parse
import urllib.request

import numpy as np
from astropy import units as u
from astropy.coordinates import SkyCoord
from astropy.time import Time

ROOT = Path.cwd()
RESULT = ROOT / "results" / "order01_native_full_v028"

PAIR_REPORT = RESULT / "order01_whole_pair_report.json"
STRICT_JSON = RESULT / "order01_strict_match_triage_v028.json"

OUT_REPORT = RESULT / "order01_gaia_static_report_v028b.json"
OUT_TRIAGE = RESULT / "order01_gaia_static_triage_v028b.csv"
OUT_SOURCES = RESULT / "order01_gaia_source_candidates_v028b.csv"
QUERY_DIR = RESULT / "order01_gaia_queries_v028"

TAP = "https://gea.esac.esa.int/tap-server/tap/sync"
GAIA_TABLE = "gaiadr3.gaia_source"

CORRECT_DETECTOR_SHA = "709da8d7a7972b15808d70a1e4dbffa0fd0fee864a81d954f74fe4a5f5af25e7"
EXPECTED_METHOD_SHA = "2cb3cabd573d7af99399899f2ccecd3002be90297e55bb0e0dcdd9dea1d0c4c1"
EXPECTED_POLICY_SHA = "44fc3453c3291a7cbe72894d781729a30943ad540aa169b2c0897b446c5c8ec7"

EXPECTED_ORDER = 1
EXPECTED_STRICT = 38
EXPECTED_RAW10 = 476

ORDINARY_CONE_ARCSEC = 120.0
HPM_RESCUE_CONE_ARCSEC = 900.0
HPM_RESCUE_MIN_MASYR = 1700.0
STRONG_ARCSEC = 3.0
DIAGNOSTIC_ARCSEC = 5.0
MAXREC = 50000

GAIA_COLUMNS = [
    "source_id",
    "ra",
    "dec",
    "ref_epoch",
    "parallax",
    "pmra",
    "pmdec",
    "ra_error",
    "dec_error",
    "parallax_error",
    "pmra_error",
    "pmdec_error",
    "radial_velocity",
    "phot_g_mean_mag",
    "bp_rp",
    "ruwe",
    "astrometric_params_solved",
]


def sha_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def sha_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def fnum(v):
    s = "" if v is None else str(v).strip()
    if not s:
        return None
    try:
        x = float(s)
    except Exception:
        return None
    return x if math.isfinite(x) else None


def inum(v):
    s = "" if v is None else str(v).strip()
    if not s:
        return None
    try:
        return int(float(s))
    except Exception:
        return None


def parse_dt(s: str) -> datetime:
    x = str(s).strip()
    if x.endswith("Z"):
        x = x[:-1] + "+00:00"
    d = datetime.fromisoformat(x)
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d.astimezone(timezone.utc)


def midpoint_dt(a: datetime, b: datetime) -> datetime:
    return a + (b - a) / 2


def spherical_midpoint(ra1, dec1, ra2, dec2):
    def vec(ra, dec):
        r = math.radians(float(ra))
        d = math.radians(float(dec))
        return np.array([
            math.cos(d) * math.cos(r),
            math.cos(d) * math.sin(r),
            math.sin(d),
        ], dtype=float)

    v = vec(ra1, dec1) + vec(ra2, dec2)
    n = float(np.linalg.norm(v))
    if not math.isfinite(n) or n <= 0:
        raise RuntimeError("REFUSING: invalid spherical midpoint")
    v /= n
    ra = math.degrees(math.atan2(v[1], v[0])) % 360.0
    dec = math.degrees(math.asin(max(-1.0, min(1.0, v[2]))))
    return ra, dec


def adql_for(ra_deg, dec_deg, radius_arcsec, *, hpm_only):
    radius_deg = float(radius_arcsec) / 3600.0
    cols = ",\n       ".join(GAIA_COLUMNS)
    q = f"""SELECT {cols}
FROM {GAIA_TABLE}
WHERE 1 = CONTAINS(
    POINT('ICRS', ra, dec),
    CIRCLE('ICRS', {ra_deg:.12f}, {dec_deg:.12f}, {radius_deg:.12f})
)"""
    if hpm_only:
        mu2 = HPM_RESCUE_MIN_MASYR ** 2
        q += f"""
  AND pmra IS NOT NULL
  AND pmdec IS NOT NULL
  AND (pmra * pmra + pmdec * pmdec) >= {mu2:.6f}"""
    return q + "\n"


def query_tap(adql: str, *, attempts=4):
    payload = urllib.parse.urlencode({
        "REQUEST": "doQuery",
        "LANG": "ADQL",
        "FORMAT": "csv",
        "MAXREC": str(MAXREC),
        "QUERY": adql,
    }).encode("utf-8")

    last = None
    for attempt in range(1, attempts + 1):
        req = urllib.request.Request(
            TAP,
            data=payload,
            method="POST",
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "text/csv,*/*",
                "User-Agent": "historical-transient-pipeline/0.2.8-order01-gaia-static-v028b",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=180) as resp:
                raw = resp.read()
                status = getattr(resp, "status", None)
                ctype = resp.headers.get("Content-Type")
                final_url = resp.geturl()

            text = raw.decode("utf-8-sig", errors="replace")
            first = text.splitlines()[0].lower() if text.splitlines() else ""
            if "source_id" not in first:
                raise RuntimeError(
                    "Gaia TAP response is not expected CSV; "
                    f"first 500 chars={text[:500]!r}"
                )
            return {
                "raw": raw,
                "status": status,
                "content_type": ctype,
                "final_url": final_url,
                "attempt": attempt,
            }
        except Exception as exc:
            last = exc
            if attempt == attempts:
                break
            time.sleep(min(20.0, 2.0 ** attempt))

    raise RuntimeError(f"Gaia TAP failed after {attempts} attempts: {last}")


def parse_gaia_csv(raw: bytes):
    text = raw.decode("utf-8-sig", errors="replace")
    rdr = csv.DictReader(StringIO(text))
    fields = rdr.fieldnames or []
    if "source_id" not in fields:
        raise RuntimeError(f"REFUSING: Gaia CSV fields missing source_id: {fields}")
    rows = list(rdr)
    if len(rows) >= MAXREC:
        raise RuntimeError(
            f"REFUSING: Gaia query reached MAXREC={MAXREC}; result is not scientifically usable"
        )
    return fields, rows


def run_or_cache_query(rank, kind, adql):
    QUERY_DIR.mkdir(parents=True, exist_ok=True)
    stem = QUERY_DIR / f"rank{rank:02d}_{kind}"
    adql_path = stem.with_suffix(".adql")
    csv_path = stem.with_suffix(".csv")
    meta_path = stem.with_suffix(".meta.json")

    if adql_path.exists():
        old = adql_path.read_text(encoding="utf-8")
        if old != adql:
            raise RuntimeError(
                f"REFUSING: cached ADQL changed for rank {rank} {kind}"
            )

    if csv_path.exists() and adql_path.exists() and meta_path.exists():
        raw = csv_path.read_bytes()
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        if meta.get("adql_sha256") != sha_bytes(adql.encode("utf-8")):
            raise RuntimeError(
                f"REFUSING: cached ADQL hash mismatch for rank {rank} {kind}"
            )
        if meta.get("response_sha256") != sha_bytes(raw):
            raise RuntimeError(
                f"REFUSING: cached Gaia response hash mismatch for rank {rank} {kind}"
            )
        _, rows = parse_gaia_csv(raw)
        return rows, {**meta, "cached": True, "rows": len(rows)}

    response = query_tap(adql)
    raw = response["raw"]
    _, rows = parse_gaia_csv(raw)

    adql_path.write_text(adql, encoding="utf-8")
    csv_path.write_bytes(raw)

    meta = {
        "rank": rank,
        "kind": kind,
        "tap": TAP,
        "gaia_table": GAIA_TABLE,
        "request_method": "POST",
        "tls_verification_disabled": False,
        "transport": "python_urllib_default_verified_https",
        "http_status": response["status"],
        "content_type": response["content_type"],
        "final_url": response["final_url"],
        "attempt": response["attempt"],
        "adql_path": str(adql_path),
        "response_path": str(csv_path),
        "adql_sha256": sha_bytes(adql.encode("utf-8")),
        "response_sha256": sha_bytes(raw),
        "rows": len(rows),
        "cached": False,
    }
    meta_path.write_text(
        json.dumps(meta, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return rows, meta


def propagate_source(row, target_time: Time):
    ra = fnum(row.get("ra"))
    dec = fnum(row.get("dec"))
    ref_epoch = fnum(row.get("ref_epoch"))
    pmra = fnum(row.get("pmra"))
    pmdec = fnum(row.get("pmdec"))

    if ra is None or dec is None:
        raise RuntimeError("REFUSING: Gaia row lacks finite ra/dec")

    propagated = False
    ra_t = ra
    dec_t = dec

    if ref_epoch is not None and pmra is not None and pmdec is not None:
        c = SkyCoord(
            ra=ra * u.deg,
            dec=dec * u.deg,
            pm_ra_cosdec=pmra * u.mas / u.yr,
            pm_dec=pmdec * u.mas / u.yr,
            obstime=Time(ref_epoch, format="jyear"),
            frame="icrs",
        )
        p = c.apply_space_motion(new_obstime=target_time)
        ra_t = float(p.ra.deg)
        dec_t = float(p.dec.deg)
        propagated = True

    dt_year = None if ref_epoch is None else float(target_time.jyear - ref_epoch)

    pmra_err = fnum(row.get("pmra_error"))
    pmdec_err = fnum(row.get("pmdec_error"))
    sigma = None
    if dt_year is not None and pmra_err is not None and pmdec_err is not None:
        sigma = abs(dt_year) * math.hypot(pmra_err, pmdec_err) / 1000.0

    return {
        "ra_target_deg": ra_t,
        "dec_target_deg": dec_t,
        "propagated": propagated,
        "dt_year": dt_year,
        "approx_pm_propagation_sigma_arcsec": sigma,
    }


def sep_arcsec(ra1, dec1, ra2, dec2):
    a = SkyCoord(float(ra1) * u.deg, float(dec1) * u.deg, frame="icrs")
    b = SkyCoord(float(ra2) * u.deg, float(dec2) * u.deg, frame="icrs")
    return float(a.separation(b).arcsec)


def clean_source_row(rank, source, origin, prop, poss_ra, poss_dec, dasch_ra, dasch_dec):
    sp = sep_arcsec(
        prop["ra_target_deg"], prop["dec_target_deg"], poss_ra, poss_dec
    )
    sd = sep_arcsec(
        prop["ra_target_deg"], prop["dec_target_deg"], dasch_ra, dasch_dec
    )

    pmra = fnum(source.get("pmra"))
    pmdec = fnum(source.get("pmdec"))
    pm = (
        math.hypot(pmra, pmdec)
        if pmra is not None and pmdec is not None
        else None
    )

    return {
        "strict_rank": rank,
        "source_id": str(source.get("source_id", "")).strip(),
        "origin": origin,
        "ra_2016_deg": fnum(source.get("ra")),
        "dec_2016_deg": fnum(source.get("dec")),
        "ref_epoch": fnum(source.get("ref_epoch")),
        "pm_masyr": pm,
        "pmra_masyr": pmra,
        "pmdec_masyr": pmdec,
        "pmra_error_masyr": fnum(source.get("pmra_error")),
        "pmdec_error_masyr": fnum(source.get("pmdec_error")),
        "parallax_mas": fnum(source.get("parallax")),
        "radial_velocity_kms": fnum(source.get("radial_velocity")),
        "g_mag": fnum(source.get("phot_g_mean_mag")),
        "bp_rp": fnum(source.get("bp_rp")),
        "ruwe": fnum(source.get("ruwe")),
        "astrometric_params_solved": inum(source.get("astrometric_params_solved")),
        "propagated": prop["propagated"],
        "ra_target_deg": prop["ra_target_deg"],
        "dec_target_deg": prop["dec_target_deg"],
        "sep_poss_arcsec": sp,
        "sep_dasch_arcsec": sd,
        "max_endpoint_sep_arcsec": max(sp, sd),
        "min_endpoint_sep_arcsec": min(sp, sd),
        "approx_pm_propagation_sigma_arcsec": prop[
            "approx_pm_propagation_sigma_arcsec"
        ],
    }


def write_csv(path: Path, rows, fields):
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)
    tmp.replace(path)


def main():
    print("=" * 112)
    print("ORDER 01 — GAIA DR3 STATIC-SOURCE EPOCH-PROPAGATION TRIAGE v028b")
    print("=" * 112)
    print(
        'Policy reproduced from completed Order 61: 120" ordinary cone + '
        '900" local high-PM rescue; 3" strong / 5" diagnostic gates.'
    )
    print("No detector. No science image pixels.")
    print()

    for p in (PAIR_REPORT, STRICT_JSON):
        if not p.is_file():
            raise RuntimeError(f"Missing completed input: {p}")

    pair = json.loads(PAIR_REPORT.read_text(encoding="utf-8"))
    triage = json.loads(STRICT_JSON.read_text(encoding="utf-8"))

    policy = ROOT / "research" / "NATIVE_TILE_EXECUTION_POLICY_V028_2026-08-21.json"
    detector = ROOT / "src" / "transient_pipeline" / "detector.py"
    method = ROOT / "config" / "frozen_method.json"

    for p in (policy, detector, method):
        if not p.is_file():
            raise RuntimeError(f"Missing frozen input: {p}")

    guards = {
        "pair_status": pair.get("status") == "COMPLETE",
        "order": int(pair.get("canonical_order", -1)) == EXPECTED_ORDER,
        "detector_report": pair.get("detector_sha256") == CORRECT_DETECTOR_SHA,
        "detector_file": sha_file(detector) == CORRECT_DETECTOR_SHA,
        "method_report": pair.get("method_sha256") == EXPECTED_METHOD_SHA,
        "method_file": sha_file(method) == EXPECTED_METHOD_SHA,
        "policy": sha_file(policy) == EXPECTED_POLICY_SHA,
        "raw10": int(pair.get("raw_le_10arcsec", -1)) == EXPECTED_RAW10,
        "strict3": int(pair.get("raw_le_3arcsec", -1)) == EXPECTED_STRICT,
        "strict_triage_status": triage.get("status") == "COMPLETE",
        "strict_triage_count": int(
            triage["counts"]["strict_le_3arcsec"]
        ) == EXPECTED_STRICT,
        "strict_unique_poss": int(
            triage["counts"]["unique_poss_candidates_in_strict"]
        ) == EXPECTED_STRICT,
        "strict_unique_dasch": int(
            triage["counts"]["unique_dasch_candidates_in_strict"]
        ) == EXPECTED_STRICT,
        "strict_no_detector": triage.get("detector_rerun") is False,
        "strict_no_pixels": triage.get("science_image_pixels_read") is False,
    }
    if not all(guards.values()):
        raise RuntimeError(
            "REFUSING: completed-stage guard failure: " + repr(guards)
        )

    start = parse_dt(pair["overlap_start_utc"])
    end = parse_dt(pair["overlap_end_utc"])
    target_dt = midpoint_dt(start, end)
    target_time = Time(target_dt)
    target_jyear = float(target_time.jyear)
    dt_gaia = abs(target_jyear - 2016.0)

    # Publication-safety correction for Order 1:
    # a <=3" pair can place either endpoint up to 1.5" from the midpoint.
    # To guarantee completeness for the 5" diagnostic static gate, reserve
    # 5.0 + 1.5 = 6.5 arcsec inside each search-cone boundary.
    historical_margin_arcsec = DIAGNOSTIC_ARCSEC + 1.5
    normal_escape = (
        (ORDINARY_CONE_ARCSEC - historical_margin_arcsec)
        * 1000.0
        / dt_gaia
    )
    hpm_coverage = (
        (HPM_RESCUE_CONE_ARCSEC - historical_margin_arcsec)
        * 1000.0
        / dt_gaia
    )

    if HPM_RESCUE_MIN_MASYR > normal_escape:
        raise RuntimeError(
            "REFUSING: local high-PM rescue threshold leaves a proper-motion "
            f"completeness gap: rescue floor={HPM_RESCUE_MIN_MASYR:.1f} mas/yr "
            f"> safe normal-cone escape={normal_escape:.1f} mas/yr"
        )

    strict_rows = triage["strict_rows"]
    if len(strict_rows) != EXPECTED_STRICT:
        raise RuntimeError(
            f"REFUSING: strict_rows length={len(strict_rows)}, "
            f"expected {EXPECTED_STRICT}"
        )

    print("Completed-stage guards: PASS")
    print(f"Target epoch: {target_dt.isoformat()}")
    print(f"Target epoch jyear UTC: {target_jyear:.12f}")
    print(
        f'Ordinary 120" cone SAFE PM escape scale (6.5" margin): '
        f"{normal_escape:.1f} mas/yr"
    )
    print(f'900" rescue SAFE coverage scale (6.5" margin): {hpm_coverage:.1f} mas/yr')
    print()

    all_sources = []
    pair_rows = []
    query_audit = []

    for item in strict_rows:
        rank = int(item["strict_rank"])
        pra = float(item["poss_ra_deg"])
        pdec = float(item["poss_dec_deg"])
        dra = float(item["dasch_ra_deg"])
        ddec = float(item["dasch_dec_deg"])

        qra, qdec = spherical_midpoint(pra, pdec, dra, ddec)

        ordinary_adql = adql_for(
            qra, qdec, ORDINARY_CONE_ARCSEC, hpm_only=False
        )
        hpm_adql = adql_for(
            qra, qdec, HPM_RESCUE_CONE_ARCSEC, hpm_only=True
        )

        print(
            f"[{rank:02d}/{EXPECTED_STRICT:02d}] querying Gaia DR3 "
            f'(120" ordinary + 900" high-PM rescue >=1700 mas/yr) ...',
            flush=True,
        )

        ordinary, ometa = run_or_cache_query(
            rank, "ordinary120", ordinary_adql
        )
        hpm, hmeta = run_or_cache_query(
            rank, "hpm900_mu1700", hpm_adql
        )
        query_audit.extend([ometa, hmeta])

        by_id = {}
        origins = {}

        for row in ordinary:
            sid = str(row.get("source_id", "")).strip()
            if not sid:
                continue
            by_id[sid] = row
            origins.setdefault(sid, set()).add("ordinary120")

        for row in hpm:
            sid = str(row.get("source_id", "")).strip()
            if not sid:
                continue
            by_id[sid] = row
            origins.setdefault(sid, set()).add("hpm900_mu1700")

        candidate_rows = []
        for sid in sorted(by_id, key=lambda x: int(x)):
            src = by_id[sid]
            prop = propagate_source(src, target_time)
            origin = "+".join(sorted(origins[sid]))
            rec = clean_source_row(
                rank, src, origin, prop,
                pra, pdec, dra, ddec,
            )
            candidate_rows.append(rec)
            all_sources.append(rec)

        candidate_rows.sort(
            key=lambda r: (
                r["min_endpoint_sep_arcsec"],
                r["max_endpoint_sep_arcsec"],
                int(r["source_id"]),
            )
        )

        any3_rows = [
            r for r in candidate_rows
            if r["min_endpoint_sep_arcsec"] <= STRONG_ARCSEC
        ]
        both3_rows = [
            r for r in candidate_rows
            if r["max_endpoint_sep_arcsec"] <= STRONG_ARCSEC
        ]
        any5_rows = [
            r for r in candidate_rows
            if r["min_endpoint_sep_arcsec"] <= DIAGNOSTIC_ARCSEC
        ]
        both5_rows = [
            r for r in candidate_rows
            if r["max_endpoint_sep_arcsec"] <= DIAGNOSTIC_ARCSEC
        ]

        best_both = min(
            candidate_rows,
            key=lambda r: (
                r["max_endpoint_sep_arcsec"],
                r["min_endpoint_sep_arcsec"],
                int(r["source_id"]),
            ),
            default=None,
        )
        best_poss = min(
            candidate_rows,
            key=lambda r: (
                r["sep_poss_arcsec"],
                int(r["source_id"]),
            ),
            default=None,
        )
        best_dasch = min(
            candidate_rows,
            key=lambda r: (
                r["sep_dasch_arcsec"],
                int(r["source_id"]),
            ),
            default=None,
        )

        if both3_rows:
            gaia_class = "GAIA_STATIC_BOTH_STRONG_PROPAGATED"
        elif any3_rows:
            gaia_class = "GAIA_STATIC_ONE_ENDPOINT_STRONG_PROPAGATED"
        elif both5_rows:
            gaia_class = "GAIA_STATIC_BOTH_DIAGNOSTIC_PROPAGATED"
        elif any5_rows:
            gaia_class = "GAIA_STATIC_ONE_ENDPOINT_DIAGNOSTIC"
        else:
            gaia_class = "NO_GAIA_WITHIN_5_ARCSEC_AT_TARGET_EPOCH"

        rec = {
            "strict_rank": rank,
            "pair_separation_arcsec": float(item["separation_arcsec"]),
            "poss_ra_deg": pra,
            "poss_dec_deg": pdec,
            "dasch_ra_deg": dra,
            "dasch_dec_deg": ddec,
            "poss_snr": float(item["poss_snr"]),
            "dasch_snr": float(item["dasch_snr"]),
            "poss_polarity": int(item["poss_polarity"]),
            "dasch_polarity": int(item["dasch_polarity"]),
            "same_polarity": bool(item["same_polarity"]),
            "gaia_class": gaia_class,
            "gaia_any_endpoint_within_3arcsec": bool(any3_rows),
            "gaia_both_endpoints_within_3arcsec": bool(both3_rows),
            "gaia_any_endpoint_within_5arcsec": bool(any5_rows),
            "gaia_both_endpoints_within_5arcsec": bool(both5_rows),
            "survives_conservative_gaia_3arcsec_any_endpoint_gate":
                not bool(any3_rows),
            "gaia_clean_5arcsec": not bool(any5_rows),
            "best_both_source_id":
                None if best_both is None else best_both["source_id"],
            "best_both_sep_poss_arcsec":
                None if best_both is None else best_both["sep_poss_arcsec"],
            "best_both_sep_dasch_arcsec":
                None if best_both is None else best_both["sep_dasch_arcsec"],
            "best_both_max_sep_arcsec":
                None if best_both is None else best_both["max_endpoint_sep_arcsec"],
            "best_both_propagated":
                None if best_both is None else best_both["propagated"],
            "best_both_g_mag":
                None if best_both is None else best_both["g_mag"],
            "best_poss_source_id":
                None if best_poss is None else best_poss["source_id"],
            "best_poss_sep_arcsec":
                None if best_poss is None else best_poss["sep_poss_arcsec"],
            "best_poss_propagated":
                None if best_poss is None else best_poss["propagated"],
            "best_dasch_source_id":
                None if best_dasch is None else best_dasch["source_id"],
            "best_dasch_sep_arcsec":
                None if best_dasch is None else best_dasch["sep_dasch_arcsec"],
            "best_dasch_propagated":
                None if best_dasch is None else best_dasch["propagated"],
            "gaia_sources_examined": len(candidate_rows),
            "cone_rows": len(ordinary),
            "hpm_rescue_rows": len(hpm),
            "target_epoch_iso": target_dt.isoformat(),
        }
        pair_rows.append(rec)

        nearest = (
            "none"
            if best_both is None
            else (
                f"{best_both['min_endpoint_sep_arcsec']:.3f}\"/"
                f"{best_both['max_endpoint_sep_arcsec']:.3f}\" "
                f"src={best_both['source_id']}"
            )
        )
        print(
            f"    {gaia_class} | rows={len(candidate_rows)} "
            f"ordinary={len(ordinary)} hpm={len(hpm)} "
            f"| best min/max={nearest}",
            flush=True,
        )

    pair_rows.sort(key=lambda r: r["strict_rank"])
    all_sources.sort(
        key=lambda r: (
            int(r["strict_rank"]),
            r["min_endpoint_sep_arcsec"],
            int(r["source_id"]),
        )
    )

    pair_fields = [
        "strict_rank",
        "pair_separation_arcsec",
        "poss_ra_deg",
        "poss_dec_deg",
        "dasch_ra_deg",
        "dasch_dec_deg",
        "poss_snr",
        "dasch_snr",
        "poss_polarity",
        "dasch_polarity",
        "same_polarity",
        "gaia_class",
        "gaia_any_endpoint_within_3arcsec",
        "gaia_both_endpoints_within_3arcsec",
        "gaia_any_endpoint_within_5arcsec",
        "gaia_both_endpoints_within_5arcsec",
        "survives_conservative_gaia_3arcsec_any_endpoint_gate",
        "gaia_clean_5arcsec",
        "best_both_source_id",
        "best_both_sep_poss_arcsec",
        "best_both_sep_dasch_arcsec",
        "best_both_max_sep_arcsec",
        "best_both_propagated",
        "best_both_g_mag",
        "best_poss_source_id",
        "best_poss_sep_arcsec",
        "best_poss_propagated",
        "best_dasch_source_id",
        "best_dasch_sep_arcsec",
        "best_dasch_propagated",
        "gaia_sources_examined",
        "cone_rows",
        "hpm_rescue_rows",
        "target_epoch_iso",
    ]

    source_fields = [
        "strict_rank",
        "source_id",
        "origin",
        "ra_2016_deg",
        "dec_2016_deg",
        "ref_epoch",
        "pm_masyr",
        "pmra_masyr",
        "pmdec_masyr",
        "pmra_error_masyr",
        "pmdec_error_masyr",
        "parallax_mas",
        "radial_velocity_kms",
        "g_mag",
        "bp_rp",
        "ruwe",
        "astrometric_params_solved",
        "propagated",
        "ra_target_deg",
        "dec_target_deg",
        "sep_poss_arcsec",
        "sep_dasch_arcsec",
        "max_endpoint_sep_arcsec",
        "min_endpoint_sep_arcsec",
        "approx_pm_propagation_sigma_arcsec",
    ]

    write_csv(OUT_TRIAGE, pair_rows, pair_fields)
    write_csv(OUT_SOURCES, all_sources, source_fields)

    class_counts = {}
    for r in pair_rows:
        class_counts[r["gaia_class"]] = (
            class_counts.get(r["gaia_class"], 0) + 1
        )

    any3 = sum(
        bool(r["gaia_any_endpoint_within_3arcsec"])
        for r in pair_rows
    )
    both3 = sum(
        bool(r["gaia_both_endpoints_within_3arcsec"])
        for r in pair_rows
    )
    any5 = sum(
        bool(r["gaia_any_endpoint_within_5arcsec"])
        for r in pair_rows
    )
    both5 = sum(
        bool(r["gaia_both_endpoints_within_5arcsec"])
        for r in pair_rows
    )

    surv3 = [
        r["strict_rank"]
        for r in pair_rows
        if r["survives_conservative_gaia_3arcsec_any_endpoint_gate"]
    ]
    clean5 = [
        r["strict_rank"]
        for r in pair_rows
        if r["gaia_clean_5arcsec"]
    ]

    report = {
        "status": "COMPLETE",
        "analysis_kind": "order01_gaia_dr3_static_epoch_propagation_v028b",
        "guards": guards,
        "strict_input_count": EXPECTED_STRICT,
        "gaia_release": "DR3",
        "gaia_table": GAIA_TABLE,
        "tap_endpoint": TAP,
        "target_epoch_utc": target_dt.isoformat(),
        "target_epoch_jyear_utc": target_jyear,
        "predeclared_thresholds": {
            "strong_static_arcsec": STRONG_ARCSEC,
            "diagnostic_static_arcsec": DIAGNOSTIC_ARCSEC,
            "j2016_cone_arcsec": ORDINARY_CONE_ARCSEC,
            "local_hpm_rescue_cone_arcsec": HPM_RESCUE_CONE_ARCSEC,
            "local_hpm_rescue_min_masyr": HPM_RESCUE_MIN_MASYR,
            "normal_cone_escape_threshold_masyr": normal_escape,
            "local_hpm_rescue_coverage_masyr": hpm_coverage,
        },
        "high_pm_strategy":
            "local_900arcsec_pm_ge_1700_rescue_per_strict_pair",
        "high_pm_strategy_is_conservative": True,
        "implementation_amendment": {
            "supersedes_for_downstream_use": "order01_gaia_static_report_v028.json",
            "reason": (
                "The original Order-1 v028 run copied the Order-61 1800 mas/yr "
                "local rescue floor but omitted the 5 arcsec diagnostic plus "
                "1.5 arcsec midpoint-to-endpoint boundary margin. At the earlier "
                "1951.843 epoch that left a narrow high-proper-motion search "
                "completeness gap. v028b lowers only the rescue-query floor to "
                "1700 mas/yr and adds an explicit no-gap guard. Static rejection "
                "radii, Gaia release, target epoch, detector, method, and science "
                "pixels are unchanged."
            ),
            "original_v028_result_preserved": True,
            "science_thresholds_retuned": False,
            "static_gate_3arcsec_unchanged": True,
            "diagnostic_gate_5arcsec_unchanged": True
        },
        "global_all_sky_high_pm_query_used": False,
        "class_counts": class_counts,
        "gaia_any_endpoint_within_3arcsec": any3,
        "gaia_both_endpoints_within_3arcsec": both3,
        "gaia_any_endpoint_within_5arcsec": any5,
        "gaia_both_endpoints_within_5arcsec": both5,
        "conservative_gaia_3arcsec_survivor_count": len(surv3),
        "conservative_gaia_3arcsec_survivor_ranks": surv3,
        "gaia_clean_5arcsec_count": len(clean5),
        "gaia_clean_5arcsec_ranks": clean5,
        "outputs": {
            "pair_triage_csv": str(OUT_TRIAGE),
            "source_candidates_csv": str(OUT_SOURCES),
            "query_cache_dir": str(QUERY_DIR),
        },
        "input_hashes": {
            "whole_pair_report_sha256": sha_file(PAIR_REPORT),
            "strict_triage_json_sha256": sha_file(STRICT_JSON),
            "detector_sha256": sha_file(detector),
            "method_sha256": sha_file(method),
            "policy_sha256": sha_file(policy),
        },
        "query_audit": query_audit,
        "detector_rerun": False,
        "pixels_read": False,
        "no_candidate_deleted": True,
        "next_stage": (
            "Use this v028b Gaia result for downstream work. Run Pan-STARRS DR2 repeated-static positional checks only on "
            "the Gaia-clean 5-arcsec ranks, using the completed Order-61 "
            "fixed PS1 policy (120 arcsec query, minimum nDetections=2, "
            "3/5 arcsec gates, no PS1 proper-motion rejection)."
        ),
    }

    tmp = OUT_REPORT.with_suffix(OUT_REPORT.suffix + ".tmp")
    tmp.write_text(
        json.dumps(report, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )
    tmp.replace(OUT_REPORT)

    print()
    print("=" * 112)
    print("ORDER 01 GAIA STATIC TRIAGE COMPLETE")
    print("=" * 112)
    print("Class counts:", json.dumps(class_counts, sort_keys=True))
    print(f'Gaia any endpoint <=3": {any3}/{EXPECTED_STRICT}')
    print(
        f'Conservative 3" survivors: {len(surv3)}/{EXPECTED_STRICT} '
        f"-> {surv3}"
    )
    print(f'Gaia any endpoint <=5": {any5}/{EXPECTED_STRICT}')
    print(
        f'Gaia-clean 5" ranks: {len(clean5)}/{EXPECTED_STRICT} '
        f"-> {clean5}"
    )
    print()
    print("Report:", OUT_REPORT)
    print("Triage:", OUT_TRIAGE)
    print("Sources:", OUT_SOURCES)
    print()
    print("No detector was rerun.")
    print("No science image pixel was read.")
    print("No candidate was deleted or promoted.")


if __name__ == "__main__":
    main()
