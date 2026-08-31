#!/usr/bin/env python3
"""Order 11 / raw match 3 — target-independent local Gaia astrometry v043a.

Purpose
-------
Measure local POSS and DASCH astrometric offsets using ordinary persistent stars,
without using the science candidate in the reference fit.  This stage consumes
only frozen candidate-coordinate CSVs plus the completed v042 Gaia catalogue
association.  It does NOT read science-image pixels, rerun the detector, retune
thresholds, or mutate candidate state.

Reference acquisition is deliberately wider than the final science gate:
reciprocal-nearest candidate<->Gaia associations may be acquired within 15"
for registration only.  The final strict interpretation continues to use the
pre-existing 3" gate; 15" is never used to classify the science candidate.
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
FUP = ROOT / "results" / "order11_followup_match3_v042"
OUT = ROOT / "results" / "order11_followup_match3_v043a"
CACHE = OUT / "gaia_local_reference_cache"

PAIR_REPORT = BASE / "order11_whole_pair_report.json"
RAW_MATCHES = BASE / "order11_raw_coincidences.csv"
POSS_ALL = BASE / "order11_poss_native_candidates.csv"
DASCH_ALL = BASE / "order11_dasch_native_candidates.csv"
CONTROL_REPORT = CTRL / "order11_coincidence_background_v028cm.json"
TIMING_CENSUS = ROOT / "results" / "remaining_pair_physical_timing_census_v028cg.json"
V042_REPORT = FUP / "order11_match3_gaia_epoch_report_v042.json"
V042_SOURCES = FUP / "order11_match3_gaia_sources_v042.csv"
DETECTOR = ROOT / "src" / "transient_pipeline" / "detector.py"
METHOD = ROOT / "config" / "frozen_method.json"
POLICY = ROOT / "research" / "NATIVE_TILE_EXECUTION_POLICY_V028_2026-08-21.json"

EXPECTED_PAIR_SHA = "115522a59d041e2a4f8c1145faa39fe22610490a723184112b5fc8f1a384d7fb"
EXPECTED_RAW_SHA = "4498c7a1eaa3ba94049dc1479c68269a77f510cdb997ed1cc9ec4a51386d6456"
EXPECTED_CONTROL_SHA = "bc40836d09ac03ee179b059d5dacc124171cb5ab6b27b5792ae89ad184ff32f0"
EXPECTED_TIMING_SHA = "0388e64e4e8a9aedf85ea4388b00817f1ffb3acdbe2977f6c240f6431b860e71"
EXPECTED_DETECTOR_SHA = "709da8d7a7972b15808d70a1e4dbffa0fd0fee864a81d954f74fe4a5f5af25e7"
EXPECTED_METHOD_SHA = "2cb3cabd573d7af99399899f2ccecd3002be90297e55bb0e0dcdd9dea1d0c4c1"
EXPECTED_POLICY_SHA = "44fc3453c3291a7cbe72894d781729a30943ad540aa169b2c0897b446c5c8ec7"
EXPECTED_POSS_ALL_SHA = "40a3931615e6cd2ceb5b7a556b094608a6fdb373454ad5626a5f6a6ebe84ba66"
EXPECTED_DASCH_ALL_SHA = "ffc5d88ddd36dfab9033fc3f7812a8e750b2559224ddd6df62fb1ac9232cff07"

TARGET_MATCH_INDEX = 3
TARGET_P_TILE = "P_x01024-02048_y09216-10240"
TARGET_P_INDEX = 59
TARGET_D_TILE = "D_x08192-09216_y17408-18432"
TARGET_D_INDEX = 12
EXPECTED_TARGET_GAIA_SOURCE_ID = "2850550110521018240"

TAP = "https://gea.esac.esa.int/tap-server/tap/sync"
GAIA_TABLE = "gaiadr3.gaia_source"
REFERENCE_WINDOWS_ARCMIN = [5.0, 10.0, 20.0, 30.0]
MIN_COMMON_REFERENCES = 5
# Acquisition radius only.  Not a candidate classification threshold.
REFERENCE_ACQUISITION_ARCSEC = 15.0
# Keep the science region and its already-identified Gaia source entirely out of the fit.
SCIENCE_EXCLUSION_ARCSEC = 30.0
# Query J2016 positions with enough margin to remain complete for very high measured PM
# over ~62 yr; historical positions are then propagated and clipped to <=30'.
GAIA_QUERY_RADIUS_ARCMIN = 46.0
MAXREC = 50000
STRICT_ARCSEC = 3.0
DIAGNOSTIC_ARCSEC = 5.0

GAIA_COLUMNS = [
    "source_id", "ra", "dec", "ref_epoch", "parallax", "parallax_error",
    "pmra", "pmdec", "pmra_error", "pmdec_error", "ra_error", "dec_error",
    "radial_velocity", "phot_g_mean_mag", "bp_rp", "ruwe",
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


def read_csv(path: Path):
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def write_csv(path: Path, rows, fields):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    tmp.replace(path)


def write_json(path: Path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    tmp.replace(path)


def fnum(v):
    s = "" if v is None else str(v).strip()
    if not s or s.lower() in {"nan", "none", "null", "--"}:
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


def midpoint_coord(a: SkyCoord, b: SkyCoord) -> SkyCoord:
    """Great-circle midpoint returned explicitly in spherical ICRS form.

    Constructing the midpoint as a Cartesian SkyCoord leaves its active
    representation Cartesian, so attributes such as .ra/.dec are unavailable
    even after accessing .icrs.  Convert the normalized midpoint vector back
    to spherical longitude/latitude before returning it.
    """
    va = a.cartesian.xyz.value
    vb = b.cartesian.xyz.value
    v = va + vb
    v = v / np.linalg.norm(v)
    c = SkyCoord(x=v[0], y=v[1], z=v[2], representation_type="cartesian", frame="icrs")
    return SkyCoord(ra=c.spherical.lon, dec=c.spherical.lat, frame="icrs")


def robust_sigma(vals):
    a = np.asarray(list(vals), dtype=float)
    if len(a) == 0:
        return None
    med = float(np.median(a))
    mad = float(np.median(np.abs(a - med)))
    return 1.4826 * mad


def nearest_rank_p95(vals):
    a = np.sort(np.asarray(list(vals), dtype=float))
    if len(a) == 0:
        return None
    i = max(0, min(len(a)-1, int(math.ceil(0.95 * len(a))) - 1))
    return float(a[i])


def adql(ra_deg, dec_deg):
    cols = ",\n       ".join(GAIA_COLUMNS)
    radius_deg = GAIA_QUERY_RADIUS_ARCMIN / 60.0
    return f"""SELECT {cols}
FROM {GAIA_TABLE}
WHERE 1 = CONTAINS(
  POINT('ICRS', ra, dec),
  CIRCLE('ICRS', {ra_deg:.12f}, {dec_deg:.12f}, {radius_deg:.12f})
)\n"""


def query_tap(q: str, attempts=4):
    payload = urllib.parse.urlencode({
        "REQUEST": "doQuery", "LANG": "ADQL", "FORMAT": "csv",
        "MAXREC": str(MAXREC), "QUERY": q,
    }).encode("utf-8")
    last = None
    for attempt in range(1, attempts+1):
        req = urllib.request.Request(
            TAP, data=payload, method="POST",
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "text/csv,*/*",
                "User-Agent": "historical-transient-pipeline/order11-match3-local-astrometry-v043a",
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
                raise RuntimeError(f"Gaia TAP response is not expected CSV: {text[:500]!r}")
            return raw, {"http_status": status, "content_type": ctype,
                         "final_url": final_url, "attempt": attempt}
        except Exception as exc:
            last = exc
            if attempt < attempts:
                time.sleep(min(20.0, 2.0**attempt))
    raise RuntimeError(f"Gaia TAP failed after {attempts} attempts: {last}")


def run_or_cache(q: str):
    CACHE.mkdir(parents=True, exist_ok=True)
    ap = CACHE / "local46arcmin.adql"
    cp = CACHE / "local46arcmin.csv"
    mp = CACHE / "local46arcmin.meta.json"
    qhash = sha_bytes(q.encode("utf-8"))
    if ap.exists() and ap.read_text(encoding="utf-8") != q:
        raise RuntimeError("REFUSING: cached local Gaia ADQL changed")
    if ap.exists() and cp.exists() and mp.exists():
        raw = cp.read_bytes()
        meta = json.loads(mp.read_text(encoding="utf-8"))
        if meta.get("adql_sha256") != qhash or meta.get("response_sha256") != sha_bytes(raw):
            raise RuntimeError("REFUSING: cached local Gaia response hash mismatch")
        return list(csv.DictReader(StringIO(raw.decode("utf-8-sig", errors="replace")))), {**meta, "cached": True}
    raw, http = query_tap(q)
    rows = list(csv.DictReader(StringIO(raw.decode("utf-8-sig", errors="replace"))))
    if len(rows) >= MAXREC:
        raise RuntimeError(f"REFUSING: Gaia query reached MAXREC={MAXREC}")
    ap.write_text(q, encoding="utf-8")
    cp.write_bytes(raw)
    meta = {
        "complete": True, "adql_sha256": qhash, "response_sha256": sha_bytes(raw),
        "rows": len(rows), "transport": "python_urllib_default_verified_https",
        "tls_verification_disabled": False, **http,
    }
    write_json(mp, meta)
    return rows, meta


def propagate(row, target_time: Time):
    ra, dec = fnum(row.get("ra")), fnum(row.get("dec"))
    if ra is None or dec is None:
        return None
    ref_epoch = fnum(row.get("ref_epoch"))
    pmra, pmdec = fnum(row.get("pmra")), fnum(row.get("pmdec"))
    if ref_epoch is not None and pmra is not None and pmdec is not None:
        c0 = SkyCoord(
            ra=ra*u.deg, dec=dec*u.deg,
            pm_ra_cosdec=pmra*u.mas/u.yr, pm_dec=pmdec*u.mas/u.yr,
            obstime=Time(ref_epoch, format="jyear"), frame="icrs",
        )
        try:
            c = c0.apply_space_motion(new_obstime=target_time).icrs
            did = True
        except Exception:
            c = SkyCoord(ra*u.deg, dec*u.deg, frame="icrs")
            did = False
    else:
        c = SkyCoord(ra*u.deg, dec*u.deg, frame="icrs")
        did = False
    return {
        "source_id": str(row.get("source_id", "")).strip(),
        "coord": c,
        "ra_1953_deg": float(c.ra.deg), "dec_1953_deg": float(c.dec.deg),
        "propagated": did,
        "g_mag": fnum(row.get("phot_g_mean_mag")),
        "pmra": pmra, "pmdec": pmdec,
        "pm": None if pmra is None or pmdec is None else math.hypot(pmra, pmdec),
        "parallax": fnum(row.get("parallax")), "ruwe": fnum(row.get("ruwe")),
    }


def candidate_rows(rows, center, radius_arcmin, *, archive):
    out = []
    for r in rows:
        ra, dec = fnum(r.get("ra_deg")), fnum(r.get("dec_deg"))
        if ra is None or dec is None:
            continue
        c = SkyCoord(ra*u.deg, dec*u.deg, frame="icrs")
        d = float(c.separation(center).arcmin)
        if d > radius_arcmin:
            continue
        out.append({
            "archive": archive,
            "tile_id": str(r.get("tile_id", "")),
            "candidate_index": inum(r.get("candidate_index")),
            "ra_deg": ra, "dec_deg": dec, "coord": c,
            "snr": fnum(r.get("snr")), "polarity": inum(r.get("polarity")),
            "sep_target_arcmin": d,
        })
    return out


def reciprocal_matches(cands, gaia_sources):
    """Return reciprocal-nearest candidate<->Gaia matches within acquisition radius."""
    if not cands or not gaia_sources:
        return []
    cc = SkyCoord([x["ra_deg"] for x in cands]*u.deg, [x["dec_deg"] for x in cands]*u.deg)
    gg = SkyCoord([x["ra_1953_deg"] for x in gaia_sources]*u.deg,
                  [x["dec_1953_deg"] for x in gaia_sources]*u.deg)
    c_to_g, c_sep, _ = cc.match_to_catalog_sky(gg)
    g_to_c, g_sep, _ = gg.match_to_catalog_sky(cc)
    out = []
    for ci, gi in enumerate(c_to_g):
        gi = int(gi)
        if int(g_to_c[gi]) != ci:
            continue
        sep = float(c_sep[ci].arcsec)
        if sep > REFERENCE_ACQUISITION_ARCSEC:
            continue
        x = dict(cands[ci])
        g = gaia_sources[gi]
        x.update({
            "gaia_source_id": g["source_id"],
            "gaia_ra_1953_deg": g["ra_1953_deg"],
            "gaia_dec_1953_deg": g["dec_1953_deg"],
            "gaia_g_mag": g["g_mag"], "gaia_pm_masyr": g["pm"],
            "gaia_parallax_mas": g["parallax"], "gaia_ruwe": g["ruwe"],
            "candidate_gaia_sep_arcsec": sep,
        })
        out.append(x)
    return out


def offsets(ref):
    g = SkyCoord(ref["gaia_ra_1953_deg"]*u.deg, ref["gaia_dec_1953_deg"]*u.deg)
    p = SkyCoord(ref["poss_ra_deg"]*u.deg, ref["poss_dec_deg"]*u.deg)
    d = SkyCoord(ref["dasch_ra_deg"]*u.deg, ref["dasch_dec_deg"]*u.deg)
    pe, pn = g.spherical_offsets_to(p)
    de, dn = g.spherical_offsets_to(d)
    re, rn = p.spherical_offsets_to(d)
    return float(pe.arcsec), float(pn.arcsec), float(de.arcsec), float(dn.arcsec), float(re.arcsec), float(rn.arcsec)


def loo_radius(refs, east_key, north_key):
    if len(refs) < 3:
        return []
    out = []
    for i, r in enumerate(refs):
        others = refs[:i] + refs[i+1:]
        me = float(np.median([q[east_key] for q in others]))
        mn = float(np.median([q[north_key] for q in others]))
        out.append(math.hypot(r[east_key]-me, r[north_key]-mn))
    return out


def main():
    print("="*120)
    print("ORDER 11 — MATCH 3 TARGET-INDEPENDENT LOCAL GAIA ASTROMETRY v043a")
    print("="*120)
    print("NETWORK: Gaia DR3 TAP only. NO SCIENCE PIXELS. NO DETECTOR. NO CANDIDATE STATE MUTATION.\n")

    required = [PAIR_REPORT, RAW_MATCHES, POSS_ALL, DASCH_ALL, CONTROL_REPORT,
                TIMING_CENSUS, V042_REPORT, V042_SOURCES, DETECTOR, METHOD, POLICY]
    for p in required:
        if not p.is_file():
            raise RuntimeError(f"Missing required input: {p}")

    hash_guards = {
        "pair_report": sha_file(PAIR_REPORT) == EXPECTED_PAIR_SHA,
        "raw_matches": sha_file(RAW_MATCHES) == EXPECTED_RAW_SHA,
        "control_report": sha_file(CONTROL_REPORT) == EXPECTED_CONTROL_SHA,
        "timing_census": sha_file(TIMING_CENSUS) == EXPECTED_TIMING_SHA,
        "detector": sha_file(DETECTOR) == EXPECTED_DETECTOR_SHA,
        "method": sha_file(METHOD) == EXPECTED_METHOD_SHA,
        "policy": sha_file(POLICY) == EXPECTED_POLICY_SHA,
        "poss_candidates": sha_file(POSS_ALL) == EXPECTED_POSS_ALL_SHA,
        "dasch_candidates": sha_file(DASCH_ALL) == EXPECTED_DASCH_ALL_SHA,
    }
    if not all(hash_guards.values()):
        raise RuntimeError("REFUSING: frozen/input hash guard failure: " + json.dumps(hash_guards, sort_keys=True))

    v42 = json.loads(V042_REPORT.read_text(encoding="utf-8"))
    v42_guards = {
        "complete": v42.get("status") == "COMPLETE",
        "analysis_kind": v42.get("analysis_kind") == "order11_match3_gaia_epoch_association_v042",
        "order": int(v42.get("canonical_order", -1)) == 11,
        "match": int(v42.get("raw_match_index", -1)) == TARGET_MATCH_INDEX,
        "no_pixels": v42.get("science_image_pixels_read") is False,
        "no_detector": v42.get("detector_rerun") is False,
        "no_mutation": v42.get("candidate_state_mutation") is False,
        "best_source": str((v42.get("best_source") or {}).get("source_id", "")) == EXPECTED_TARGET_GAIA_SOURCE_ID,
    }
    if not all(v42_guards.values()):
        raise RuntimeError("REFUSING: v042 semantic guard failure: " + json.dumps(v42_guards, sort_keys=True))

    m = v42["measurement"]
    start = parse_dt(m["physical_overlap_start_utc"])
    end = parse_dt(m["physical_overlap_end_utc"])
    if abs((end-start).total_seconds() - 2700.0) > 1e-6:
        raise RuntimeError("REFUSING: physical overlap is no longer 2700 s")
    target_time = Time(start + (end-start)/2, scale="utc")

    ptarget = SkyCoord(float(m["poss"]["ra_deg"])*u.deg, float(m["poss"]["dec_deg"])*u.deg)
    dtarget = SkyCoord(float(m["dasch"]["ra_deg"])*u.deg, float(m["dasch"]["dec_deg"])*u.deg)
    mid = midpoint_coord(ptarget, dtarget)

    # Recover the exact v042 historical Gaia coordinate for the best source.
    v42_sources = read_csv(V042_SOURCES)
    best_rows = [r for r in v42_sources if str(r.get("source_id", "")).strip() == EXPECTED_TARGET_GAIA_SOURCE_ID]
    if len(best_rows) != 1:
        raise RuntimeError(f"REFUSING: expected exactly one v042 row for Gaia {EXPECTED_TARGET_GAIA_SOURCE_ID}; got {len(best_rows)}")
    br = best_rows[0]
    gra = fnum(br.get("target_epoch_ra_deg")); gdec = fnum(br.get("target_epoch_dec_deg"))
    if gra is None or gdec is None:
        raise RuntimeError("REFUSING: v042 best Gaia source lacks historical propagated coordinate")
    target_gaia = SkyCoord(gra*u.deg, gdec*u.deg, frame="icrs")

    print("Frozen/input guards: PASS")
    print(f"Physical common window: {start.isoformat()} -> {end.isoformat()} = 2700.0 s")
    print(f"Registration epoch: {target_time.utc.isot}")
    print(f"Science target Gaia source excluded from fit: {EXPECTED_TARGET_GAIA_SOURCE_ID}")
    print(f"Reference policy: reciprocal-nearest candidate<->Gaia <= {REFERENCE_ACQUISITION_ARCSEC:.1f}\"; science exclusion {SCIENCE_EXCLUSION_ARCSEC:.0f}\"; windows 5/10/20/30'; minimum {MIN_COMMON_REFERENCES} common refs")
    print()

    print("Loading frozen candidate-coordinate catalogues ...", flush=True)
    poss_rows = read_csv(POSS_ALL)
    dasch_rows = read_csv(DASCH_ALL)
    pc = candidate_rows(poss_rows, mid, max(REFERENCE_WINDOWS_ARCMIN)+1.0, archive="POSS")
    dc = candidate_rows(dasch_rows, mid, max(REFERENCE_WINDOWS_ARCMIN)+1.0, archive="DASCH")
    # Remove science endpoints before matching so neither can influence reciprocal-nearest assignments.
    pc = [x for x in pc if not (x["tile_id"] == TARGET_P_TILE and x["candidate_index"] == TARGET_P_INDEX)]
    dc = [x for x in dc if not (x["tile_id"] == TARGET_D_TILE and x["candidate_index"] == TARGET_D_INDEX)]
    print(f"Local candidate coordinates loaded: POSS={len(pc)} DASCH={len(dc)}")

    print(f"Querying Gaia DR3 within {GAIA_QUERY_RADIUS_ARCMIN:.1f}' of target midpoint ...", flush=True)
    raw_gaia, query_meta = run_or_cache(adql(float(mid.ra.deg), float(mid.dec.deg)))
    propagated = []
    for r in raw_gaia:
        q = propagate(r, target_time)
        if q is None or not q["source_id"]:
            continue
        sep = float(q["coord"].separation(mid).arcmin)
        # Historical reference pool is truly local at the event epoch.
        if sep > max(REFERENCE_WINDOWS_ARCMIN) + REFERENCE_ACQUISITION_ARCSEC/60.0:
            continue
        if q["source_id"] == EXPECTED_TARGET_GAIA_SOURCE_ID:
            continue
        if float(q["coord"].separation(mid).arcsec) < SCIENCE_EXCLUSION_ARCSEC:
            continue
        q["sep_target_arcmin"] = sep
        propagated.append(q)
    if not propagated:
        raise RuntimeError("REFUSING: no propagated local Gaia reference sources")
    print(f"Gaia rows returned={len(raw_gaia)}; historical local/exclusion-clean={len(propagated)}")

    pm = reciprocal_matches(pc, propagated)
    dm = reciprocal_matches(dc, propagated)
    pby = {x["gaia_source_id"]: x for x in pm}
    dby = {x["gaia_source_id"]: x for x in dm}
    common_ids = sorted(set(pby) & set(dby))

    refs = []
    for sid in common_ids:
        p, d = pby[sid], dby[sid]
        g = next(x for x in propagated if x["source_id"] == sid)
        r = {
            "gaia_source_id": sid,
            "gaia_ra_1953_deg": g["ra_1953_deg"], "gaia_dec_1953_deg": g["dec_1953_deg"],
            "gaia_g_mag": g["g_mag"], "gaia_pm_masyr": g["pm"],
            "gaia_parallax_mas": g["parallax"], "gaia_ruwe": g["ruwe"],
            "sep_target_arcmin": g["sep_target_arcmin"],
            "poss_tile_id": p["tile_id"], "poss_candidate_index": p["candidate_index"],
            "poss_ra_deg": p["ra_deg"], "poss_dec_deg": p["dec_deg"], "poss_snr": p["snr"],
            "poss_candidate_gaia_sep_arcsec": p["candidate_gaia_sep_arcsec"],
            "dasch_tile_id": d["tile_id"], "dasch_candidate_index": d["candidate_index"],
            "dasch_ra_deg": d["ra_deg"], "dasch_dec_deg": d["dec_deg"], "dasch_snr": d["snr"],
            "dasch_candidate_gaia_sep_arcsec": d["candidate_gaia_sep_arcsec"],
        }
        pe,pn,de,dn,re,rn = offsets(r)
        r.update({
            "poss_minus_gaia_east_arcsec": pe, "poss_minus_gaia_north_arcsec": pn,
            "dasch_minus_gaia_east_arcsec": de, "dasch_minus_gaia_north_arcsec": dn,
            "poss_to_dasch_east_arcsec": re, "poss_to_dasch_north_arcsec": rn,
            "poss_dasch_sep_arcsec": math.hypot(re,rn),
        })
        refs.append(r)

    print(f"Reciprocal Gaia associations: POSS={len(pm)} DASCH={len(dm)} common same-Gaia={len(refs)}")

    counts = {w: sum(r["sep_target_arcmin"] <= w for r in refs) for w in REFERENCE_WINDOWS_ARCMIN}
    selected = next((w for w in REFERENCE_WINDOWS_ARCMIN if counts[w] >= MIN_COMMON_REFERENCES), None)

    ref_fields = [
        "selected_window", "gaia_source_id", "gaia_ra_1953_deg", "gaia_dec_1953_deg", "gaia_g_mag",
        "gaia_pm_masyr", "gaia_parallax_mas", "gaia_ruwe", "sep_target_arcmin",
        "poss_tile_id", "poss_candidate_index", "poss_ra_deg", "poss_dec_deg", "poss_snr",
        "poss_candidate_gaia_sep_arcsec", "dasch_tile_id", "dasch_candidate_index", "dasch_ra_deg",
        "dasch_dec_deg", "dasch_snr", "dasch_candidate_gaia_sep_arcsec",
        "poss_minus_gaia_east_arcsec", "poss_minus_gaia_north_arcsec",
        "dasch_minus_gaia_east_arcsec", "dasch_minus_gaia_north_arcsec",
        "poss_to_dasch_east_arcsec", "poss_to_dasch_north_arcsec", "poss_dasch_sep_arcsec",
    ]

    if selected is None:
        for r in refs:
            r["selected_window"] = False
        write_csv(OUT / "order11_match3_local_reference_audit_v043a.csv", refs, ref_fields)
        result = {
            "status": "COMPLETE",
            "analysis_kind": "order11_match3_target_independent_local_gaia_astrometry_v043a",
            "classification": "INSUFFICIENT_LOCAL_COMMON_GAIA_REFERENCES",
            "reference_counts": {str(k): v for k,v in counts.items()},
            "minimum_common_references": MIN_COMMON_REFERENCES,
            "selected_window_arcmin": None,
            "guards": {**hash_guards, **v42_guards},
            "input_sha256": {str(p.relative_to(ROOT)): sha_file(p) for p in required},
            "query_audit": query_meta,
            "detector_rerun": False, "science_image_pixels_read": False, "candidate_state_mutation": False,
            "interpretation_boundary": "Insufficient target-independent common Gaia references is not a negative or positive scientific result. Do not infer transience or persistence from this stage.",
            "next_stage": "Use official plate astrometric/source products or a wider predeclared target-independent reference strategy; do not fit the science target itself.",
        }
        write_json(OUT / "order11_match3_local_astrometry_report_v043a.json", result)
        print("\nLOCAL ASTROMETRY: INSUFFICIENT REFERENCES")
        print("refs 5/10/20/30' = " + "/".join(str(counts[w]) for w in REFERENCE_WINDOWS_ARCMIN))
        print("No candidate classification changed.")
        return

    sel = [dict(r) for r in refs if r["sep_target_arcmin"] <= selected]
    sel_ids = {r["gaia_source_id"] for r in sel}
    for r in refs:
        r["selected_window"] = r["gaia_source_id"] in sel_ids

    med_pe = float(np.median([r["poss_minus_gaia_east_arcsec"] for r in sel]))
    med_pn = float(np.median([r["poss_minus_gaia_north_arcsec"] for r in sel]))
    med_de = float(np.median([r["dasch_minus_gaia_east_arcsec"] for r in sel]))
    med_dn = float(np.median([r["dasch_minus_gaia_north_arcsec"] for r in sel]))
    med_re = float(np.median([r["poss_to_dasch_east_arcsec"] for r in sel]))
    med_rn = float(np.median([r["poss_to_dasch_north_arcsec"] for r in sel]))

    # Correct each science endpoint independently to the local Gaia frame.
    p_corr = ptarget.spherical_offsets_by((-med_pe)*u.arcsec, (-med_pn)*u.arcsec)
    d_corr = dtarget.spherical_offsets_by((-med_de)*u.arcsec, (-med_dn)*u.arcsec)
    corrected_pd = float(p_corr.separation(d_corr).arcsec)
    p_gaia_corr = float(p_corr.separation(target_gaia).arcsec)
    d_gaia_corr = float(d_corr.separation(target_gaia).arcsec)

    raw_e, raw_n = ptarget.spherical_offsets_to(dtarget)
    relative_corrected_e = float(raw_e.arcsec) - med_re
    relative_corrected_n = float(raw_n.arcsec) - med_rn
    relative_corrected_r = math.hypot(relative_corrected_e, relative_corrected_n)

    loo_p = loo_radius(sel, "poss_minus_gaia_east_arcsec", "poss_minus_gaia_north_arcsec")
    loo_d = loo_radius(sel, "dasch_minus_gaia_east_arcsec", "dasch_minus_gaia_north_arcsec")
    loo_r = loo_radius(sel, "poss_to_dasch_east_arcsec", "poss_to_dasch_north_arcsec")
    p95_p, p95_d, p95_r = nearest_rank_p95(loo_p), nearest_rank_p95(loo_d), nearest_rank_p95(loo_r)

    if p_gaia_corr <= STRICT_ARCSEC and d_gaia_corr <= STRICT_ARCSEC and corrected_pd <= STRICT_ARCSEC:
        classification = "LOCAL_ASTROMETRY_SUPPORTS_PERSISTENT_GAIA_SOURCE_ASSOCIATION"
    elif corrected_pd <= STRICT_ARCSEC and p_gaia_corr <= DIAGNOSTIC_ARCSEC and d_gaia_corr <= DIAGNOSTIC_ARCSEC:
        classification = "LOCAL_ASTROMETRY_SUPPORTS_CROSS_OBSERVATORY_MATCH_GAIA_ASSOCIATION_DIAGNOSTIC"
    elif corrected_pd <= STRICT_ARCSEC:
        classification = "LOCAL_ASTROMETRY_SUPPORTS_CROSS_OBSERVATORY_MATCH_BUT_NOT_TARGET_GAIA_ASSOCIATION"
    else:
        classification = "LOCAL_ASTROMETRY_DOES_NOT_SUPPORT_STRICT_MATCH3_COINCIDENCE"

    measurement = {
        "selected_window_arcmin": selected,
        "reference_count": len(sel),
        "reference_counts_5_10_20_30_arcmin": {str(w): counts[w] for w in REFERENCE_WINDOWS_ARCMIN},
        "median_poss_minus_gaia_east_arcsec": med_pe,
        "median_poss_minus_gaia_north_arcsec": med_pn,
        "median_dasch_minus_gaia_east_arcsec": med_de,
        "median_dasch_minus_gaia_north_arcsec": med_dn,
        "median_poss_to_dasch_east_arcsec": med_re,
        "median_poss_to_dasch_north_arcsec": med_rn,
        "robust_sigma_poss_minus_gaia_east_arcsec": robust_sigma(r["poss_minus_gaia_east_arcsec"] for r in sel),
        "robust_sigma_poss_minus_gaia_north_arcsec": robust_sigma(r["poss_minus_gaia_north_arcsec"] for r in sel),
        "robust_sigma_dasch_minus_gaia_east_arcsec": robust_sigma(r["dasch_minus_gaia_east_arcsec"] for r in sel),
        "robust_sigma_dasch_minus_gaia_north_arcsec": robust_sigma(r["dasch_minus_gaia_north_arcsec"] for r in sel),
        "raw_science_poss_dasch_sep_arcsec": float(ptarget.separation(dtarget).arcsec),
        "corrected_science_poss_dasch_sep_arcsec": corrected_pd,
        "relative_vector_corrected_science_sep_arcsec": relative_corrected_r,
        "corrected_science_poss_to_v042_gaia_arcsec": p_gaia_corr,
        "corrected_science_dasch_to_v042_gaia_arcsec": d_gaia_corr,
        "v042_gaia_source_id": EXPECTED_TARGET_GAIA_SOURCE_ID,
        "loo_poss_absolute_residual_median_arcsec": None if not loo_p else float(np.median(loo_p)),
        "loo_poss_absolute_residual_p95_arcsec": p95_p,
        "loo_dasch_absolute_residual_median_arcsec": None if not loo_d else float(np.median(loo_d)),
        "loo_dasch_absolute_residual_p95_arcsec": p95_d,
        "loo_relative_residual_median_arcsec": None if not loo_r else float(np.median(loo_r)),
        "loo_relative_residual_p95_arcsec": p95_r,
        "science_poss_within_reference_p95": None if p95_p is None else p_gaia_corr <= p95_p,
        "science_dasch_within_reference_p95": None if p95_d is None else d_gaia_corr <= p95_d,
        "science_relative_within_reference_p95": None if p95_r is None else corrected_pd <= p95_r,
    }

    write_csv(OUT / "order11_match3_local_reference_audit_v043a.csv", refs, ref_fields)
    write_json(OUT / "order11_match3_local_astrometry_report_v043a.json", {
        "status": "COMPLETE",
        "analysis_kind": "order11_match3_target_independent_local_gaia_astrometry_v043a",
        "classification": classification,
        "guards": {**hash_guards, **v42_guards},
        "input_sha256": {str(p.relative_to(ROOT)): sha_file(p) for p in required},
        "physical_overlap": {
            "start_utc": start.isoformat(), "end_utc": end.isoformat(),
            "actual_overlap_s": (end-start).total_seconds(), "registration_epoch_utc": target_time.utc.isot,
        },
        "fixed_policy": {
            "reference_windows_arcmin": REFERENCE_WINDOWS_ARCMIN,
            "minimum_common_references": MIN_COMMON_REFERENCES,
            "reference_acquisition_arcsec": REFERENCE_ACQUISITION_ARCSEC,
            "reference_acquisition_is_not_science_gate": True,
            "science_exclusion_arcsec": SCIENCE_EXCLUSION_ARCSEC,
            "science_target_gaia_source_excluded": EXPECTED_TARGET_GAIA_SOURCE_ID,
            "matching": "reciprocal nearest candidate-to-propagated-Gaia independently in POSS and DASCH; intersect same Gaia source_id",
            "fit": "translation-only medians; no affine/higher-order fit; no reference clipping",
            "window_choice": "smallest of 5/10/20/30 arcmin with >=5 common references",
            "strict_science_gate_arcsec": STRICT_ARCSEC,
            "diagnostic_science_gate_arcsec": DIAGNOSTIC_ARCSEC,
        },
        "query_audit": query_meta,
        "counts": {
            "poss_local_candidates_excluding_science": len(pc),
            "dasch_local_candidates_excluding_science": len(dc),
            "gaia_query_rows": len(raw_gaia),
            "gaia_historical_local_exclusion_clean": len(propagated),
            "poss_reciprocal_matches": len(pm), "dasch_reciprocal_matches": len(dm),
            "common_same_gaia_references": len(refs),
        },
        "measurement": measurement,
        "interpretation_boundary": (
            "This stage tests whether the raw match is consistent with local ordinary-star astrometric systematics. "
            "A corrected association with Gaia supports a persistent-source explanation but does not by itself prove "
            "the photographic residuals are the catalogued star; morphology and sensitivity-qualified other-epoch "
            "checks remain required. Failure to associate does not establish transience."
        ),
        "detector_rerun": False, "science_image_pixels_read": False, "candidate_state_mutation": False,
        "next_stage": (
            "If the registered endpoints remain mutually consistent, run same-tile SNR/polarity-matched native morphology "
            "controls for both endpoints, then sensitivity-qualified other-epoch detectability. If registration removes the "
            "strict coincidence, retain match 3 as an astrometric/chance coincidence without deleting frozen evidence."
        ),
    })

    print("\n" + "="*120)
    print("LOCAL ASTROMETRY COMPLETE")
    print("="*120)
    print("Classification:", classification)
    print("refs 5/10/20/30' = " + "/".join(str(counts[w]) for w in REFERENCE_WINDOWS_ARCMIN) + f" | selected={selected:.0f}' n={len(sel)}")
    print(f"Median POSS-Gaia offset:  east={med_pe:+.3f}\" north={med_pn:+.3f}\"")
    print(f"Median DASCH-Gaia offset: east={med_de:+.3f}\" north={med_dn:+.3f}\"")
    print(f"Raw P-D={float(ptarget.separation(dtarget).arcsec):.3f}\" -> corrected P-D={corrected_pd:.3f}\"")
    print(f"Corrected to v042 Gaia source: POSS={p_gaia_corr:.3f}\" DASCH={d_gaia_corr:.3f}\"")
    if p95_r is not None:
        print(f"LOO relative-reference residual median={float(np.median(loo_r)):.3f}\" p95={p95_r:.3f}\"")
    print("Report:", OUT / "order11_match3_local_astrometry_report_v043a.json")
    print("References:", OUT / "order11_match3_local_reference_audit_v043a.csv")
    print("No science pixels were read. Detector was not rerun. Candidate state was not changed.")


if __name__ == "__main__":
    main()
