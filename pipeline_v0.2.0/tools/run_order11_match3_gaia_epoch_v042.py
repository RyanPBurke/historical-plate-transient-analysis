#!/usr/bin/env python3
"""Order 11 / raw match 3 — Gaia DR3 epoch-aware persistent-source association.

Read-only with respect to all frozen detector/candidate products.  It does not
read science-image pixels, rerun the detector, retune thresholds, promote or
reject a candidate.  It writes only a new follow-up result directory.
"""
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
BASE = ROOT / "results" / "order11_native_full_v028"
CTRL = ROOT / "results" / "order11_coincidence_controls_v028cm"
OUT = ROOT / "results" / "order11_followup_match3_v042"
QUERY_DIR = OUT / "gaia_query_cache"

PAIR_REPORT = BASE / "order11_whole_pair_report.json"
RAW_MATCHES = BASE / "order11_raw_coincidences.csv"
CONTROL_REPORT = CTRL / "order11_coincidence_background_v028cm.json"
TIMING_CENSUS = ROOT / "results" / "remaining_pair_physical_timing_census_v028cg.json"
DETECTOR = ROOT / "src" / "transient_pipeline" / "detector.py"
METHOD = ROOT / "config" / "frozen_method.json"
POLICY = ROOT / "research" / "NATIVE_TILE_EXECUTION_POLICY_V028_2026-08-21.json"

P_TILE = "P_x01024-02048_y09216-10240"
D_TILE = "D_x08192-09216_y17408-18432"
P_SIDE = ROOT / "work" / "order11_native_full_v028" / "poss_tiles" / f"{P_TILE}.json"
D_SIDE = ROOT / "work" / "order11_native_full_v028" / "dasch_tiles" / f"{D_TILE}.json"
P_CAND = ROOT / "work" / "order11_native_full_v028" / "poss_tiles" / f"{P_TILE}_candidates.csv"
D_CAND = ROOT / "work" / "order11_native_full_v028" / "dasch_tiles" / f"{D_TILE}_candidates.csv"

TARGET_MATCH_INDEX = 3
TARGET_P_INDEX = 59
TARGET_D_INDEX = 12
EXPECTED_PAIR_SHA = "115522a59d041e2a4f8c1145faa39fe22610490a723184112b5fc8f1a384d7fb"
EXPECTED_RAW_SHA = "4498c7a1eaa3ba94049dc1479c68269a77f510cdb997ed1cc9ec4a51386d6456"
EXPECTED_CONTROL_SHA = "bc40836d09ac03ee179b059d5dacc124171cb5ab6b27b5792ae89ad184ff32f0"
EXPECTED_TIMING_SHA = "0388e64e4e8a9aedf85ea4388b00817f1ffb3acdbe2977f6c240f6431b860e71"
EXPECTED_DETECTOR_SHA = "709da8d7a7972b15808d70a1e4dbffa0fd0fee864a81d954f74fe4a5f5af25e7"
EXPECTED_METHOD_SHA = "2cb3cabd573d7af99399899f2ccecd3002be90297e55bb0e0dcdd9dea1d0c4c1"
EXPECTED_POLICY_SHA = "44fc3453c3291a7cbe72894d781729a30943ad540aa169b2c0897b446c5c8ec7"
EXPECTED_P_CSV_SHA = "e74a7e0427ad84aa31815229248a3cf699a369ed25ca754eefabdbdf498068e8"
EXPECTED_D_CSV_SHA = "e92e5df6d7ff90659dd7c676f03c655916ffee0496b8aeabba9b8ba877b1bae5"

TAP = "https://gea.esac.esa.int/tap-server/tap/sync"
GAIA_TABLE = "gaiadr3.gaia_source"
ORDINARY_CONE_ARCSEC = 120.0
HPM_RESCUE_CONE_ARCSEC = 900.0
HPM_RESCUE_MIN_MASYR = 1700.0
STRONG_ARCSEC = 3.0
DIAGNOSTIC_ARCSEC = 5.0
# Fixed conservative endpoint allowance inherited from Order-1 v028b: a <=3"
# pair can put an endpoint <=1.5" from its midpoint, so reserve 5 + 1.5".
HISTORICAL_MARGIN_ARCSEC = 6.5
MAXREC = 50000

GAIA_COLUMNS = [
    "source_id", "ra", "dec", "ref_epoch", "parallax", "parallax_error",
    "pmra", "pmdec", "pmra_error", "pmdec_error", "ra_error", "dec_error",
    "radial_velocity", "phot_g_mean_mag", "bp_rp", "ruwe",
    "astrometric_params_solved",
]

SOURCE_FIELDS = [
    "source_id", "origin", "ra_catalog_deg", "dec_catalog_deg", "ref_epoch",
    "pm_masyr", "pmra_masyr", "pmdec_masyr", "pmra_error_masyr",
    "pmdec_error_masyr", "parallax_mas", "parallax_error_mas",
    "max_annual_parallax_amplitude_arcsec", "radial_velocity_kms", "g_mag",
    "bp_rp", "ruwe", "astrometric_params_solved", "propagated_with_pm",
    "target_epoch_ra_deg", "target_epoch_dec_deg", "sep_mid_arcsec",
    "sep_poss_arcsec", "sep_dasch_arcsec", "min_endpoint_sep_arcsec",
    "max_endpoint_sep_arcsec", "approx_pm_propagation_sigma_arcsec",
]


def sha_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def sha_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_csv(path: Path):
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


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
        r = math.radians(float(ra)); d = math.radians(float(dec))
        return np.array([math.cos(d)*math.cos(r), math.cos(d)*math.sin(r), math.sin(d)])
    v = vec(ra1, dec1) + vec(ra2, dec2)
    n = float(np.linalg.norm(v))
    if not math.isfinite(n) or n <= 0:
        raise RuntimeError("REFUSING: invalid spherical midpoint")
    v /= n
    return math.degrees(math.atan2(v[1], v[0])) % 360.0, math.degrees(math.asin(v[2]))


def sep_arcsec(ra1, dec1, ra2, dec2):
    a = SkyCoord(float(ra1)*u.deg, float(dec1)*u.deg, frame="icrs")
    b = SkyCoord(float(ra2)*u.deg, float(dec2)*u.deg, frame="icrs")
    return float(a.separation(b).arcsec)


def adql_for(ra_deg, dec_deg, radius_arcsec, *, hpm_only):
    cols = ",\n       ".join(GAIA_COLUMNS)
    radius_deg = float(radius_arcsec) / 3600.0
    q = f"""SELECT {cols}
FROM {GAIA_TABLE}
WHERE 1 = CONTAINS(
    POINT('ICRS', ra, dec),
    CIRCLE('ICRS', {ra_deg:.12f}, {dec_deg:.12f}, {radius_deg:.12f})
)"""
    if hpm_only:
        mu2 = HPM_RESCUE_MIN_MASYR**2
        q += f"""
  AND pmra IS NOT NULL
  AND pmdec IS NOT NULL
  AND (pmra*pmra + pmdec*pmdec) >= {mu2:.6f}"""
    return q + "\n"


def query_tap(adql: str, *, attempts=4):
    payload = urllib.parse.urlencode({
        "REQUEST": "doQuery", "LANG": "ADQL", "FORMAT": "csv",
        "MAXREC": str(MAXREC), "QUERY": adql,
    }).encode("utf-8")
    last = None
    for attempt in range(1, attempts+1):
        req = urllib.request.Request(
            TAP, data=payload, method="POST",
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "text/csv,*/*",
                "User-Agent": "historical-transient-pipeline/order11-match3-gaia-v042",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=180) as resp:
                raw = resp.read(); status = getattr(resp, "status", None)
                ctype = resp.headers.get("Content-Type"); final_url = resp.geturl()
            text = raw.decode("utf-8-sig", errors="replace")
            first = text.splitlines()[0].lower() if text.splitlines() else ""
            if "source_id" not in first:
                raise RuntimeError(f"Gaia TAP response is not expected CSV: {text[:500]!r}")
            return raw, {"http_status": status, "content_type": ctype,
                         "final_url": final_url, "attempt": attempt}
        except Exception as exc:
            last = exc
            if attempt < attempts:
                time.sleep(min(20.0, 2.0**attempt))
    raise RuntimeError(f"Gaia TAP failed after {attempts} attempts: {last}")


def parse_gaia(raw: bytes):
    rows = list(csv.DictReader(StringIO(raw.decode("utf-8-sig", errors="replace"))))
    if len(rows) >= MAXREC:
        raise RuntimeError(f"REFUSING: Gaia result reached MAXREC={MAXREC}")
    return rows


def run_or_cache(kind: str, adql: str):
    QUERY_DIR.mkdir(parents=True, exist_ok=True)
    stem = QUERY_DIR / kind
    ap, cp, mp = stem.with_suffix(".adql"), stem.with_suffix(".csv"), stem.with_suffix(".meta.json")
    adql_hash = sha_bytes(adql.encode("utf-8"))
    if ap.exists() and ap.read_text(encoding="utf-8") != adql:
        raise RuntimeError(f"REFUSING: cached ADQL changed for {kind}")
    if ap.exists() and cp.exists() and mp.exists():
        raw = cp.read_bytes(); meta = json.loads(mp.read_text(encoding="utf-8"))
        if meta.get("adql_sha256") != adql_hash or meta.get("response_sha256") != sha_bytes(raw):
            raise RuntimeError(f"REFUSING: cached Gaia query hash mismatch for {kind}")
        return parse_gaia(raw), {**meta, "cached": True}
    raw, http = query_tap(adql)
    rows = parse_gaia(raw)
    ap.write_text(adql, encoding="utf-8"); cp.write_bytes(raw)
    meta = {
        "kind": kind, "tap": TAP, "gaia_table": GAIA_TABLE,
        "transport": "python_urllib_default_verified_https", "tls_verification_disabled": False,
        "request_method": "POST", "adql_sha256": adql_hash,
        "response_sha256": sha_bytes(raw), "rows": len(rows), "cached": False, **http,
    }
    mp.write_text(json.dumps(meta, indent=2, sort_keys=True)+"\n", encoding="utf-8")
    return rows, meta


def propagate(row, target_time: Time):
    ra, dec = fnum(row.get("ra")), fnum(row.get("dec"))
    ref_epoch = fnum(row.get("ref_epoch")); pmra = fnum(row.get("pmra")); pmdec = fnum(row.get("pmdec"))
    if ra is None or dec is None:
        raise RuntimeError("REFUSING: Gaia row lacks finite ra/dec")
    ra_t, dec_t, did = ra, dec, False
    if ref_epoch is not None and pmra is not None and pmdec is not None:
        c = SkyCoord(ra=ra*u.deg, dec=dec*u.deg,
                     pm_ra_cosdec=pmra*u.mas/u.yr, pm_dec=pmdec*u.mas/u.yr,
                     obstime=Time(ref_epoch, format="jyear"), frame="icrs")
        p = c.apply_space_motion(new_obstime=target_time)
        ra_t, dec_t, did = float(p.ra.deg), float(p.dec.deg), True
    dt_year = None if ref_epoch is None else float(target_time.jyear - ref_epoch)
    pe1, pe2 = fnum(row.get("pmra_error")), fnum(row.get("pmdec_error"))
    sig = None if dt_year is None or pe1 is None or pe2 is None else abs(dt_year)*math.hypot(pe1, pe2)/1000.0
    return ra_t, dec_t, did, sig


def source_record(row, origin, target_time, mid_ra, mid_dec, pra, pdec, dra, ddec):
    ra_t, dec_t, did, sig = propagate(row, target_time)
    pmra, pmdec = fnum(row.get("pmra")), fnum(row.get("pmdec"))
    pm = None if pmra is None or pmdec is None else math.hypot(pmra, pmdec)
    par = fnum(row.get("parallax"))
    return {
        "source_id": str(row.get("source_id", "")).strip(), "origin": origin,
        "ra_catalog_deg": fnum(row.get("ra")), "dec_catalog_deg": fnum(row.get("dec")),
        "ref_epoch": fnum(row.get("ref_epoch")), "pm_masyr": pm,
        "pmra_masyr": pmra, "pmdec_masyr": pmdec,
        "pmra_error_masyr": fnum(row.get("pmra_error")), "pmdec_error_masyr": fnum(row.get("pmdec_error")),
        "parallax_mas": par, "parallax_error_mas": fnum(row.get("parallax_error")),
        "max_annual_parallax_amplitude_arcsec": None if par is None else abs(par)/1000.0,
        "radial_velocity_kms": fnum(row.get("radial_velocity")), "g_mag": fnum(row.get("phot_g_mean_mag")),
        "bp_rp": fnum(row.get("bp_rp")), "ruwe": fnum(row.get("ruwe")),
        "astrometric_params_solved": inum(row.get("astrometric_params_solved")),
        "propagated_with_pm": did, "target_epoch_ra_deg": ra_t, "target_epoch_dec_deg": dec_t,
        "sep_mid_arcsec": sep_arcsec(ra_t, dec_t, mid_ra, mid_dec),
        "sep_poss_arcsec": sep_arcsec(ra_t, dec_t, pra, pdec),
        "sep_dasch_arcsec": sep_arcsec(ra_t, dec_t, dra, ddec),
        "min_endpoint_sep_arcsec": min(sep_arcsec(ra_t, dec_t, pra, pdec), sep_arcsec(ra_t, dec_t, dra, ddec)),
        "max_endpoint_sep_arcsec": max(sep_arcsec(ra_t, dec_t, pra, pdec), sep_arcsec(ra_t, dec_t, dra, ddec)),
        "approx_pm_propagation_sigma_arcsec": sig,
    }


def write_csv(path: Path, rows, fields):
    tmp = path.with_suffix(path.suffix+".tmp")
    with tmp.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields); w.writeheader(); w.writerows(rows)
    tmp.replace(path)


def close(a, b, tol=2e-9):
    return abs(float(a)-float(b)) <= tol


def main():
    print("="*116)
    print("ORDER 11 — MATCH 3 GAIA DR3 EPOCH-AWARE PERSISTENT-SOURCE ASSOCIATION v042")
    print("="*116)
    print("NETWORK: Gaia DR3 TAP only. NO SCIENCE PIXELS. NO DETECTOR. NO CANDIDATE STATE MUTATION.\n")

    for p in (PAIR_REPORT, RAW_MATCHES, CONTROL_REPORT, TIMING_CENSUS, DETECTOR, METHOD, POLICY, P_SIDE, D_SIDE, P_CAND, D_CAND):
        if not p.is_file():
            raise RuntimeError(f"Missing required input: {p}")

    hash_guards = {
        "pair_report": sha_file(PAIR_REPORT) == EXPECTED_PAIR_SHA,
        "raw_matches": sha_file(RAW_MATCHES) == EXPECTED_RAW_SHA,
        "control_report": sha_file(CONTROL_REPORT) == EXPECTED_CONTROL_SHA,
        "physical_timing_census": sha_file(TIMING_CENSUS) == EXPECTED_TIMING_SHA,
        "detector": sha_file(DETECTOR) == EXPECTED_DETECTOR_SHA,
        "method": sha_file(METHOD) == EXPECTED_METHOD_SHA,
        "policy": sha_file(POLICY) == EXPECTED_POLICY_SHA,
        "poss_candidate_csv": sha_file(P_CAND) == EXPECTED_P_CSV_SHA,
        "dasch_candidate_csv": sha_file(D_CAND) == EXPECTED_D_CSV_SHA,
    }
    if not all(hash_guards.values()):
        raise RuntimeError("REFUSING: frozen/hash guard failed: "+json.dumps(hash_guards, sort_keys=True))

    pair = json.loads(PAIR_REPORT.read_text(encoding="utf-8"))
    ctrl = json.loads(CONTROL_REPORT.read_text(encoding="utf-8"))
    timing = json.loads(TIMING_CENSUS.read_text(encoding="utf-8"))
    trows = [x for x in timing.get("results", []) if int(x.get("canonical_order", -1)) == 11]
    if len(trows) != 1:
        raise RuntimeError(f"REFUSING: expected one Order-11 physical timing row, got {len(trows)}")
    timing11 = trows[0]
    ps = json.loads(P_SIDE.read_text(encoding="utf-8")); ds = json.loads(D_SIDE.read_text(encoding="utf-8"))
    semantic_guards = {
        "pair_complete": pair.get("status") == "COMPLETE",
        "order11": int(pair.get("canonical_order", -1)) == 11,
        "actual_overlap_2700": close(pair.get("actual_overlap_s"), 2700.0),
        "raw10_125": int(pair.get("raw_le_10arcsec", -1)) == 125,
        "raw3_11": int(pair.get("raw_le_3arcsec", -1)) == 11,
        "poss_count_340100": int(pair.get("poss_candidate_count", -1)) == 340100,
        "dasch_count_1471": int(pair.get("dasch_candidate_count_in_acquired_bbox", -1)) == 1471,
        "poss_identity": pair.get("poss_exposure_id") == "POSS-I:779:E:rec404" and pair.get("poss_region") == "XE403" and str(pair.get("poss_plate_id")) == "0733",
        "dasch_identity": pair.get("dasch_plate_id") == "fa13177",
        "control_complete": ctrl.get("status") == "COMPLETE",
        "control_no_population_excess": ctrl.get("interpretation", {}).get("population_level_excess") is False,
        "top_priority_is_match3": str(ctrl.get("top_priority", {}).get("match_index")) == "3",
        "timing_class_survives": timing11.get("classification") == "PHYSICAL_TIME_OVERLAP_SURVIVES",
        "timing_physical_overlap_2700": close(timing11.get("maximum_physical_overlap_s"), 2700.0),
        "timing_poss_identity": timing11.get("poss_exposure") == "POSS-I:779:E:rec404" and timing11.get("region") == "XE403" and str(timing11.get("plate_id")) == "0733",
        "timing_dasch_identity": timing11.get("dasch_plate") == "fa13177",
        "poss_sidecar_csv_hash": ps.get("candidates_csv_sha256") == EXPECTED_P_CSV_SHA,
        "dasch_sidecar_csv_hash": ds.get("candidates_csv_sha256") == EXPECTED_D_CSV_SHA,
        "poss_sidecar_detector": ps.get("detector_sha256") == EXPECTED_DETECTOR_SHA,
        "dasch_sidecar_detector": ds.get("detector_sha256") == EXPECTED_DETECTOR_SHA,
    }
    if not all(semantic_guards.values()):
        raise RuntimeError("REFUSING: semantic guard failed: "+json.dumps(semantic_guards, sort_keys=True))

    raw = read_csv(RAW_MATCHES)
    rows = [r for r in raw if int(r["match_index"]) == TARGET_MATCH_INDEX]
    if len(rows) != 1:
        raise RuntimeError(f"REFUSING: expected exactly one raw match 3 row, got {len(rows)}")
    r = rows[0]
    target_guards = {
        "poss_tile": r["poss_tile_id"] == P_TILE, "poss_index": int(r["poss_candidate_index"]) == TARGET_P_INDEX,
        "dasch_tile": r["dasch_tile_id"] == D_TILE, "dasch_index": int(r["dasch_candidate_index"]) == TARGET_D_INDEX,
        "separation": close(r["separation_arcsec"], 1.5964971533180876, 1e-9),
        "poss_ra": close(r["poss_ra_deg"], 2.30023536982128), "poss_dec": close(r["poss_dec_deg"], 25.83248288899566),
        "dasch_ra": close(r["dasch_ra_deg"], 2.299957251727733), "dasch_dec": close(r["dasch_dec_deg"], 25.832848954372725),
        "poss_positive": int(r["poss_polarity"]) == 1, "dasch_positive": int(r["dasch_polarity"]) == 1,
    }
    if not all(target_guards.values()):
        raise RuntimeError("REFUSING: match-3 identity guard failed: "+json.dumps(target_guards, sort_keys=True))

    # Verify exact candidate rows from the checkpoint CSVs without opening NPY science arrays.
    pr = [x for x in read_csv(P_CAND) if int(x["candidate_index"]) == TARGET_P_INDEX]
    dr = [x for x in read_csv(D_CAND) if int(x["candidate_index"]) == TARGET_D_INDEX]
    if len(pr) != 1 or len(dr) != 1:
        raise RuntimeError(f"REFUSING: candidate row resolution failed P={len(pr)} D={len(dr)}")
    p0, d0 = pr[0], dr[0]
    candidate_row_guards = {
        "p_pixel": int(p0["local_x"]) == 277 and int(p0["local_y"]) == 104,
        "d_pixel": int(d0["local_x"]) == 787 and int(d0["local_y"]) == 87,
        "p_coord": close(p0["ra_deg"], r["poss_ra_deg"]) and close(p0["dec_deg"], r["poss_dec_deg"]),
        "d_coord": close(d0["ra_deg"], r["dasch_ra_deg"]) and close(d0["dec_deg"], r["dasch_dec_deg"]),
    }
    if not all(candidate_row_guards.values()):
        raise RuntimeError("REFUSING: candidate checkpoint row guard failed")

    # The native pair report retained the earlier catalogue POSS interval (10:11-10:56).
    # The later physical-timing census found the verified DSS HHH plate time to be
    # 10:18-11:03, i.e. a +420 s shift, while the DASCH logbook exposure is 10:05-11:04.
    # Use the physical overlap for all new epoch-sensitive measurements and preserve
    # the older catalogue interval explicitly as provenance rather than overwriting it.
    catalog_start, catalog_end = parse_dt(pair["overlap_start_utc"]), parse_dt(pair["overlap_end_utc"])
    physical_poss_start = parse_dt(timing11["physical_poss_start_utc"])
    physical_poss_end = parse_dt(timing11["physical_poss_end_utc"])
    dexp = max(timing11["dasch_exposures"], key=lambda x: float(x.get("overlap_with_physical_poss_s", 0.0)))
    dasch_start, dasch_end = parse_dt(dexp["start_utc"]), parse_dt(dexp["end_utc"])
    start, end = max(physical_poss_start, dasch_start), min(physical_poss_end, dasch_end)
    if (end-start).total_seconds() != 2700.0:
        raise RuntimeError(f"REFUSING: recomputed physical overlap is {(end-start).total_seconds()} s, expected 2700")
    target_dt = midpoint_dt(start, end); target_time = Time(target_dt)
    dt_gaia = abs(float(target_time.jyear)-2016.0)
    normal_escape = (ORDINARY_CONE_ARCSEC-HISTORICAL_MARGIN_ARCSEC)*1000.0/dt_gaia
    hpm_coverage = (HPM_RESCUE_CONE_ARCSEC-HISTORICAL_MARGIN_ARCSEC)*1000.0/dt_gaia
    if HPM_RESCUE_MIN_MASYR > normal_escape:
        raise RuntimeError(f"REFUSING: PM rescue floor {HPM_RESCUE_MIN_MASYR:.1f} leaves gap above {normal_escape:.1f} mas/yr")

    pra, pdec = float(r["poss_ra_deg"]), float(r["poss_dec_deg"])
    dra, ddec = float(r["dasch_ra_deg"]), float(r["dasch_dec_deg"])
    mid_ra, mid_dec = spherical_midpoint(pra, pdec, dra, ddec)

    OUT.mkdir(parents=True, exist_ok=True)
    print("Frozen/input guards: PASS")
    print(f"Legacy/catalogue interval retained in native report: {catalog_start.isoformat()} -> {catalog_end.isoformat()}")
    print(f"Physical POSS interval: {physical_poss_start.isoformat()} -> {physical_poss_end.isoformat()}")
    print(f"DASCH logbook interval: {dasch_start.isoformat()} -> {dasch_end.isoformat()}")
    print(f"PHYSICAL common exposure window: {start.isoformat()} -> {end.isoformat()} = {(end-start).total_seconds():.1f} s")
    print(f"Association epoch (common-window midpoint): {target_dt.isoformat()} | jyear={float(target_time.jyear):.12f}")
    print(f"Pair midpoint: RA={mid_ra:.12f} deg Dec={mid_dec:.12f} deg")
    print(f"Measured-PM completeness: ordinary safe escape={normal_escape:.1f} mas/yr; 900\" rescue safe coverage={hpm_coverage:.1f} mas/yr")
    print("Querying Gaia DR3: 120\" ordinary + 900\" measured-high-PM rescue >=1700 mas/yr ...", flush=True)

    ordinary_adql = adql_for(mid_ra, mid_dec, ORDINARY_CONE_ARCSEC, hpm_only=False)
    hpm_adql = adql_for(mid_ra, mid_dec, HPM_RESCUE_CONE_ARCSEC, hpm_only=True)
    ordinary, ometa = run_or_cache("match3_ordinary120", ordinary_adql)
    hpm, hmeta = run_or_cache("match3_hpm900_mu1700", hpm_adql)

    by_id, origins = {}, {}
    for origin, seq in (("ordinary120", ordinary), ("hpm900_mu1700", hpm)):
        for x in seq:
            sid = str(x.get("source_id", "")).strip()
            if not sid: continue
            by_id[sid] = x; origins.setdefault(sid, set()).add(origin)

    sources = []
    for sid in sorted(by_id, key=lambda z: int(z)):
        sources.append(source_record(by_id[sid], "+".join(sorted(origins[sid])), target_time,
                                     mid_ra, mid_dec, pra, pdec, dra, ddec))
    sources.sort(key=lambda x: (x["max_endpoint_sep_arcsec"], x["min_endpoint_sep_arcsec"], int(x["source_id"])))

    both3 = [x for x in sources if x["max_endpoint_sep_arcsec"] <= STRONG_ARCSEC]
    any3 = [x for x in sources if x["min_endpoint_sep_arcsec"] <= STRONG_ARCSEC]
    both5 = [x for x in sources if x["max_endpoint_sep_arcsec"] <= DIAGNOSTIC_ARCSEC]
    any5 = [x for x in sources if x["min_endpoint_sep_arcsec"] <= DIAGNOSTIC_ARCSEC]
    best = sources[0] if sources else None
    if both3:
        classification = "CATALOGUE_SOURCE_BOTH_ENDPOINTS_WITHIN_3ARCSEC"
    elif any3:
        classification = "CATALOGUE_SOURCE_ONE_ENDPOINT_WITHIN_3ARCSEC"
    elif both5:
        classification = "CATALOGUE_SOURCE_BOTH_ENDPOINTS_WITHIN_5ARCSEC"
    elif any5:
        classification = "CATALOGUE_SOURCE_ONE_ENDPOINT_WITHIN_5ARCSEC"
    else:
        classification = "NO_GAIA_ASSOCIATION_WITHIN_5ARCSEC_UNDER_THIS_QUERY_POLICY"

    write_csv(OUT / "order11_match3_gaia_sources_v042.csv", sources, SOURCE_FIELDS)
    report = {
        "status": "COMPLETE", "analysis_kind": "order11_match3_gaia_epoch_association_v042",
        "canonical_order": 11, "raw_match_index": TARGET_MATCH_INDEX,
        "guards": {**hash_guards, **semantic_guards, **target_guards, **candidate_row_guards},
        "input_sha256": {
            str(PAIR_REPORT.relative_to(ROOT)): sha_file(PAIR_REPORT),
            str(RAW_MATCHES.relative_to(ROOT)): sha_file(RAW_MATCHES),
            str(CONTROL_REPORT.relative_to(ROOT)): sha_file(CONTROL_REPORT),
            str(TIMING_CENSUS.relative_to(ROOT)): sha_file(TIMING_CENSUS),
            str(DETECTOR.relative_to(ROOT)): sha_file(DETECTOR), str(METHOD.relative_to(ROOT)): sha_file(METHOD),
            str(POLICY.relative_to(ROOT)): sha_file(POLICY), str(P_CAND.relative_to(ROOT)): sha_file(P_CAND),
            str(D_CAND.relative_to(ROOT)): sha_file(D_CAND),
        },
        "measurement": {
            "legacy_catalog_overlap_start_utc": catalog_start.isoformat(),
            "legacy_catalog_overlap_end_utc": catalog_end.isoformat(),
            "physical_poss_start_utc": physical_poss_start.isoformat(),
            "physical_poss_end_utc": physical_poss_end.isoformat(),
            "dasch_start_utc": dasch_start.isoformat(), "dasch_end_utc": dasch_end.isoformat(),
            "physical_overlap_start_utc": start.isoformat(), "physical_overlap_end_utc": end.isoformat(),
            "actual_exposure_overlap_s": (end-start).total_seconds(),
            "catalog_minus_physical_poss_start_s": (catalog_start-physical_poss_start).total_seconds(),
            "association_epoch_utc": target_dt.isoformat(), "association_epoch_jyear": float(target_time.jyear),
            "poss": {"tile_id": P_TILE, "candidate_index": TARGET_P_INDEX, "ra_deg": pra, "dec_deg": pdec,
                     "local_x": int(p0["local_x"]), "local_y": int(p0["local_y"]), "snr": float(p0["snr"]), "polarity": int(p0["polarity"])},
            "dasch": {"tile_id": D_TILE, "candidate_index": TARGET_D_INDEX, "ra_deg": dra, "dec_deg": ddec,
                      "local_x": int(d0["local_x"]), "local_y": int(d0["local_y"]), "snr": float(d0["snr"]), "polarity": int(d0["polarity"])},
            "raw_pair_separation_arcsec": float(r["separation_arcsec"]), "pair_midpoint_ra_deg": mid_ra,
            "pair_midpoint_dec_deg": mid_dec,
        },
        "gaia_policy": {
            "release": "DR3", "table": GAIA_TABLE, "tap": TAP,
            "ordinary_cone_arcsec": ORDINARY_CONE_ARCSEC, "hpm_rescue_cone_arcsec": HPM_RESCUE_CONE_ARCSEC,
            "hpm_rescue_min_masyr": HPM_RESCUE_MIN_MASYR, "strong_arcsec": STRONG_ARCSEC,
            "diagnostic_arcsec": DIAGNOSTIC_ARCSEC, "historical_margin_arcsec": HISTORICAL_MARGIN_ARCSEC,
            "safe_normal_cone_escape_masyr": normal_escape, "safe_hpm_coverage_masyr": hpm_coverage,
            "proper_motion_handling": "Gaia PM propagated to common-exposure midpoint with astropy SkyCoord.apply_space_motion when pmra/pmdec exist",
            "parallax_handling": "parallax is recorded and its maximum annual angular amplitude reported, but is not folded into the primary persistent-source positional gate; near-Earth/two-site parallax is a separate later hypothesis test",
            "unknown_pm_caveat": "Gaia rows lacking measured proper motion are not evidence that the historical position is PM-complete; catalogue absence is never treated as proof of transience",
        },
        "query_audit": [ometa, hmeta], "unique_gaia_sources": len(sources),
        "association_counts": {"any_endpoint_le3": len(any3), "both_endpoints_le3": len(both3),
                               "any_endpoint_le5": len(any5), "both_endpoints_le5": len(both5)},
        "classification": classification, "best_source": best,
        "interpretation_boundary": (
            "A close Gaia association supports a persistent/static-source explanation for the raw positional coincidence, "
            "but does not by itself prove that either photographic residual is that source. Conversely, no Gaia association "
            "does not establish transience. The next required measurements are target-independent local registration, "
            "same-tile morphology controls, and sensitivity-qualified other-epoch checks."
        ),
        "detector_rerun": False, "science_image_pixels_read": False, "candidate_state_mutation": False,
        "next_stage": "Run target-independent local astrometry only after recording this catalogue result; do not alter frozen detector/candidate products.",
    }
    rp = OUT / "order11_match3_gaia_epoch_report_v042.json"
    rp.write_text(json.dumps(report, indent=2, sort_keys=True, default=str)+"\n", encoding="utf-8")

    print("\n"+"="*116)
    print("GAIA ASSOCIATION COMPLETE")
    print("="*116)
    print("Classification:", classification)
    print(f"Unique Gaia rows after merge: {len(sources)} | <=3\" any/both={len(any3)}/{len(both3)} | <=5\" any/both={len(any5)}/{len(both5)}")
    if best:
        print(f"Best source {best['source_id']}: P={best['sep_poss_arcsec']:.3f}\" D={best['sep_dasch_arcsec']:.3f}\" max={best['max_endpoint_sep_arcsec']:.3f}\" G={best['g_mag']}")
        print(f"PM={best['pm_masyr']} mas/yr parallax={best['parallax_mas']} mas propagated={best['propagated_with_pm']}")
    print("Report:", rp)
    print("Sources:", OUT / "order11_match3_gaia_sources_v042.csv")
    print("No science pixels were read. Detector was not rerun. Candidate state was not changed.")


if __name__ == "__main__":
    main()
