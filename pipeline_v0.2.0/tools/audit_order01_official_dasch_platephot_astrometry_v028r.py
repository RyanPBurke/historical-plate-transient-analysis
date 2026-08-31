#!/usr/bin/env python3
"""
ORDER 01 — official DASCH DR7 platephot astrometric adjudication v028r

Purpose
-------
Independently test the coherent ~20 arcsec ordinary-star offset found by v028q
using DASCH DR7's own source measurements, rather than our raw-pixel centroiding.

The official DR7 /dasch/dr7/platephot endpoint returns multi-source photometry
for one plate exposure, including:
  - fitted source sky position
  - catalog source sky position (precessed to plate epoch)
  - image centroid and source-shape measurements
  - quality flags

This stage:
  1. Reuses the already-frozen v028p Gaia control selection.
  2. Resolves the official WCS solution for physical plate ai43437.
  3. Queries official DR7 platephot around each frozen science region.
  4. Matches official catalog positions to the isolated Gaia controls.
  5. Measures, independently:
       official fitted source - Gaia(1951)
       official fitted source - official DASCH catalog position
       official DASCH catalog position - Gaia(1951)
  6. Reports the nearest official DR7 source measurement to each frozen DASCH
     science coordinate, without using science positions in the ordinary-star fit.

Guards
------
NETWORK ACCESS: TRUE (official DASCH DR7 public API).
SCIENCE PIXELS READ: FALSE.
Candidate pixels used as reference fit: FALSE.
Frozen transient detector rerun: FALSE.
No candidate promotion/deletion/state mutation.
"""

from __future__ import annotations

import csv
import io
import json
import math
import statistics
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import requests

ROOT = Path.cwd()
BASE = ROOT / "results" / "order01_native_full_v028"
WORK = ROOT / "work" / "order01_native_full_v028"

V028P_REFS = BASE / "order01_bright_gaia_subpixel_references_v028p.csv"
V028Q_JSON = BASE / "order01_plate_registered_bright_gaia_astrometry_v028q.json"
STRICT = BASE / "order01_strict_match_triage_v028.csv"

CACHE = WORK / "official_dasch_platephot_v028r"
CACHE.mkdir(parents=True, exist_ok=True)

OUT_JSON = BASE / "order01_official_dasch_platephot_astrometry_v028r.json"
OUT_CSV = BASE / "order01_official_dasch_platephot_astrometry_v028r.csv"
OUT_REFS = BASE / "order01_official_dasch_platephot_references_v028r.csv"
OUT_NEAR = BASE / "order01_official_dasch_platephot_science_nearest_v028r.csv"
OUT_MD = BASE / "ORDER01_OFFICIAL_DASCH_PLATEPHOT_ASTROMETRY_V028R.md"

EXPECTED = [10, 24, 25, 26, 29, 30]
PLATE_ID = "ai43437"
TARGET_MIDPOINT = "1951-11-05T07:29:59.999999"
EXPECTED_EXPOSURE_MIN = 58.0

BASE_URL = "https://api.starglass.cfa.harvard.edu/public/"
TIMEOUT = 90
MAX_RETRIES = 4
REFCAT = "apass"

# v028p's Gaia controls were isolated by >=45 arcsec.  Official catalog
# positions should therefore be uniquely identifiable with this conservative
# radius even allowing old-catalog errors.
OFFICIAL_CATALOG_TO_GAIA_MAX_ARCSEC = 10.0

# Report nearest official source around the science coordinate but do not use
# these science matches in any reference fit.
SCIENCE_NEAREST_MAX_ARCSEC = 60.0

# Quality description only. We do not delete rows on flags at this stage.
MIN_ORDINARY_REFERENCE_COUNT = 5


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    tmp.replace(path)


def write_json(path: Path, obj: Any) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, indent=2, sort_keys=True, default=str) + "\n",
                   encoding="utf-8")
    tmp.replace(path)


def f(v: Any, default=None):
    try:
        if v is None or str(v).strip() == "":
            return default
        return float(str(v).strip())
    except Exception:
        return default


def i(v: Any, default=None):
    try:
        if v is None or str(v).strip() == "":
            return default
        return int(float(str(v).strip()))
    except Exception:
        return default


def parse_iso(s: Any):
    if s is None:
        return None
    t = str(s).strip()
    if not t:
        return None
    t = t.replace("Z", "+00:00")
    try:
        d = datetime.fromisoformat(t)
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        return d.astimezone(timezone.utc)
    except Exception:
        return None


def angular_vector(ra1, dec1, ra2, dec2):
    """Small-angle east,north vector from point1 to point2."""
    dec0 = 0.5 * (dec1 + dec2)
    east = (ra2 - ra1) * 3600.0 * math.cos(math.radians(dec0))
    north = (dec2 - dec1) * 3600.0
    sep = math.hypot(east, north)
    pa = math.degrees(math.atan2(east, north)) % 360.0
    return east, north, sep, pa


def med2(rows, east_key, north_key):
    arr = np.array([[float(r[east_key]), float(r[north_key])] for r in rows],
                   dtype=float)
    return np.median(arr, axis=0)


def residuals_about(vecs, center):
    a = np.asarray(vecs, dtype=float)
    return np.hypot(a[:,0]-center[0], a[:,1]-center[1])


def quantile95(vals):
    a = np.asarray(vals, dtype=float)
    if a.size == 0:
        return None
    return float(np.quantile(a, .95, method="higher"))


def circular_R(east, north):
    ang = np.arctan2(np.asarray(east,float), np.asarray(north,float))
    return float(math.hypot(float(np.mean(np.sin(ang))),
                            float(np.mean(np.cos(ang)))))


def request_json(method: str, path: str, payload=None, cache: Path | None=None):
    if cache and cache.is_file():
        return json.loads(cache.read_text(encoding="utf-8")), True

    url = BASE_URL + path.lstrip("/")
    headers = {
        "accept": "application/json",
        "user-agent": "historical-transient-independent-audit-v028r/1.0",
    }

    last = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            if method.upper() == "GET":
                r = requests.get(url, headers=headers, timeout=TIMEOUT)
            else:
                r = requests.post(url, headers=headers, json=payload, timeout=TIMEOUT)
            r.raise_for_status()
            obj = r.json()
            if cache:
                cache.write_text(json.dumps(obj, indent=2) + "\n", encoding="utf-8")
            return obj, False
        except Exception as exc:
            last = exc
            if attempt < MAX_RETRIES:
                time.sleep(min(2**attempt, 8))
    raise RuntimeError(f"{method} {url} failed after {MAX_RETRIES} tries: {last}")


def csv_records_from_api_json(obj):
    """
    DR7 table APIs return a JSON list of strings, where each string is one CSV
    record. Be tolerant of a future object wrapper.
    """
    if isinstance(obj, dict):
        for k in ("data", "rows", "result", "records"):
            if k in obj and isinstance(obj[k], list):
                obj = obj[k]
                break
    if not isinstance(obj, list):
        raise RuntimeError(f"Unexpected table response type: {type(obj).__name__}")
    if not obj:
        return []

    if all(isinstance(x, str) for x in obj):
        text = "\n".join(obj)
        return list(csv.DictReader(io.StringIO(text)))

    if all(isinstance(x, dict) for x in obj):
        return obj

    raise RuntimeError("Unexpected mixed table response")


def pick(row: dict, *names, default=None):
    """Case/underscore-insensitive field resolver."""
    norm = {str(k).lower().replace("_",""): k for k in row.keys()}
    for name in names:
        key = str(name).lower().replace("_","")
        if key in norm:
            return row[norm[key]]
    return default


def resolve_plate_solution():
    cache = CACHE / f"{PLATE_ID}_plate_info.json"
    obj, used = request_json("GET", f"plates/p/{PLATE_ID}", cache=cache)

    exposures = obj.get("exposures", []) if isinstance(obj, dict) else []
    if not exposures:
        raise RuntimeError(f"{PLATE_ID}: official plate metadata has no WCS exposures")

    target = parse_iso(TARGET_MIDPOINT)
    scored = []
    for e in exposures:
        sol = i(pick(e, "solution_num", "solutionNumber", "solnum"))
        dt = parse_iso(pick(e, "datetime", "dateTime"))
        ex = f(pick(e, "exposure", "exposure_length", "exposureLength"))
        if sol is None:
            continue
        time_delta = abs((dt-target).total_seconds()) if dt and target else 1e30
        ex_delta = abs(ex-EXPECTED_EXPOSURE_MIN) if ex is not None else 1e6
        scored.append((time_delta, ex_delta, sol, e))
    if not scored:
        raise RuntimeError(f"{PLATE_ID}: no usable WCS solution records")
    scored.sort(key=lambda q:(q[0], q[1], q[2]))
    td, ed, sol, rec = scored[0]

    # Strong identity guard: if the official metadata has a dated solution,
    # do not silently select a different night.
    if td < 1e29 and td > 12*3600:
        raise RuntimeError(
            f"{PLATE_ID}: nearest official WCS solution is {td/3600:.2f} h "
            "from frozen discovery midpoint"
        )

    return {
        "plate_id": PLATE_ID,
        "solution_number": sol,
        "official_record": rec,
        "midpoint_delta_seconds": None if td >= 1e29 else td,
        "exposure_delta_minutes": None if ed >= 1e5 else ed,
        "cache_used": used,
    }


def extract_official_fields(r: dict):
    # Raw API is documented as camelCase; aliases make this robust to package
    # or future naming variations.
    return {
        "ra_deg": f(pick(r, "raDeg", "ra_deg", "ra")),
        "dec_deg": f(pick(r, "decDeg", "dec_deg", "dec")),
        "catalog_ra_deg": f(pick(r, "catalogRa", "catalog_ra")),
        "catalog_dec_deg": f(pick(r, "catalogDec", "catalog_dec")),
        "image_x": f(pick(r, "imageX", "image_x")),
        "image_y": f(pick(r, "imageY", "image_y")),
        "sxt_number": i(pick(r, "sxtNumber", "sxt_number")),
        "ref_number": i(pick(r, "refNumber", "ref_number")),
        "gsc_bin_index": i(pick(r, "gscBinIndex", "gsc_bin_index")),
        "aflags": pick(r, "aflags"),
        "a2flags": pick(r, "a2flags"),
        "bflags": pick(r, "bflags"),
        "b2flags": pick(r, "b2flags"),
        "drad_rms2": f(pick(r, "dradRms2", "drad_rms2")),
        "fwhm_image": f(pick(r, "fwhmImage", "fwhm_image")),
        "ellipticity": f(pick(r, "ellipticity")),
        "flux_max": f(pick(r, "fluxMax", "flux_max")),
        "flux_iso": f(pick(r, "fluxIso", "flux_iso")),
        "magcal_magdep": f(pick(r, "magcalMagdep", "magcal_magdep")),
        "limiting_mag_local": f(pick(r, "limitingMagLocal", "limiting_mag_local")),
        "solnum": i(pick(r, "solnum", "solutionNumber", "solution_number")),
        "series": pick(r, "series"),
        "platenum": i(pick(r, "platenum", "plateNum", "plate_number")),
    }


def main():
    print("="*128)
    print("ORDER 01 — OFFICIAL DASCH DR7 PLATEPHOT ASTROMETRIC ADJUDICATION v028r")
    print("="*128)
    print("NETWORK ACCESS: official DASCH DR7 public API.")
    print("SCIENCE PIXELS ARE NOT READ.")
    print("Candidate positions are NOT ordinary-star reference-fit inputs.")
    print("Frozen transient detector is NOT rerun.\n")

    for p in (V028P_REFS, V028Q_JSON, STRICT):
        if not p.is_file():
            print(f"FAIL missing input: {p}")
            return 2

    vq = json.loads(V028Q_JSON.read_text(encoding="utf-8"))
    if vq.get("frozen_active_ranks") != EXPECTED:
        raise RuntimeError("v028q frozen active ranks mismatch")
    if vq.get("guards",{}).get("candidate_pixels_used_as_reference_fit") is not False:
        raise RuntimeError("v028q candidate-reference guard mismatch")

    strict_rows = read_csv(STRICT)
    strict = {i(r["strict_rank"]): r for r in strict_rows
              if i(r["strict_rank"]) in EXPECTED}
    if sorted(strict) != EXPECTED:
        raise RuntimeError("strict survivor mismatch")

    vp_rows = read_csv(V028P_REFS)
    vp_by_rank = {}
    for r in vp_rows:
        rank = i(r.get("strict_rank"))
        if rank in EXPECTED:
            vp_by_rank.setdefault(rank, []).append(r)

    sol = resolve_plate_solution()
    solnum = sol["solution_number"]

    print("Official plate identity:")
    print(f"  plate={PLATE_ID} solution={solnum}")
    rec = sol["official_record"]
    print(f"  datetime={pick(rec,'datetime')} exposure={pick(rec,'exposure')} min")
    print(f"  frozen-midpoint delta={sol['midpoint_delta_seconds']} s")
    print()

    all_official_by_rank = {}
    query_log = {}

    for rank in EXPECTED:
        s = strict[rank]
        # Midpoint of frozen discovery coordinates is only the platephot query
        # center. It does not affect ordinary-star matching.
        pra, pdec = f(s["poss_ra_deg"]), f(s["poss_dec_deg"])
        dra, ddec = f(s["dasch_ra_deg"]), f(s["dasch_dec_deg"])
        cra, cdec = (pra+dra)/2.0, (pdec+ddec)/2.0

        cache = CACHE / f"{PLATE_ID}_sol{solnum}_rank{rank}_{REFCAT}_platephot.json"
        payload = {
            "plate_id": PLATE_ID,
            "solution_number": int(solnum),
            "refcat": REFCAT,
            "center_ra_deg": cra,
            "center_dec_deg": cdec,
        }
        obj, used = request_json("POST", "dasch/dr7/platephot",
                                 payload=payload, cache=cache)
        raw_rows = csv_records_from_api_json(obj)
        rows = []
        for rr in raw_rows:
            q = extract_official_fields(rr)
            q["_raw"] = rr
            # Retain rows for this WCS solution when solnum is exposed.
            if q["solnum"] is not None and q["solnum"] != solnum:
                continue
            rows.append(q)
        all_official_by_rank[rank] = rows
        query_log[str(rank)] = {
            "center_ra_deg": cra,
            "center_dec_deg": cdec,
            "response_rows": len(raw_rows),
            "selected_solution_rows": len(rows),
            "cache_used": used,
        }
        print(f"Rank #{rank}: official platephot rows={len(rows)} "
              f"(raw={len(raw_rows)}, cache={'yes' if used else 'no'})")

    print()

    # ------------------------------------------------------------------
    # Match each frozen isolated Gaia control to the official DR7 *catalog*
    # coordinate. This prevents the fitted source coordinate from deciding
    # which star is which.
    # ------------------------------------------------------------------
    refs = []
    seen_gaia = set()

    for rank in EXPECTED:
        off = all_official_by_rank[rank]
        for g in vp_by_rank.get(rank, []):
            sid = str(g.get("source_id","")).strip()
            if not sid or sid in seen_gaia:
                continue
            gra = f(g.get("ra_target_deg"))
            gdec = f(g.get("dec_target_deg"))
            if gra is None or gdec is None:
                continue

            choices = []
            for o in off:
                cra, cdec = o["catalog_ra_deg"], o["catalog_dec_deg"]
                fra, fdec = o["ra_deg"], o["dec_deg"]
                if None in (cra,cdec,fra,fdec):
                    continue
                _,_,sep,_ = angular_vector(gra,gdec,cra,cdec)
                if sep <= OFFICIAL_CATALOG_TO_GAIA_MAX_ARCSEC:
                    choices.append((sep,o))
            if not choices:
                continue
            choices.sort(key=lambda q:q[0])
            cat_sep,o = choices[0]

            # Avoid double-counting the same Gaia source when 10' platephot
            # regions overlap.
            seen_gaia.add(sid)

            fit_gaia_e, fit_gaia_n, fit_gaia_sep, _ = angular_vector(
                gra,gdec,o["ra_deg"],o["dec_deg"])
            fit_cat_e, fit_cat_n, fit_cat_sep, _ = angular_vector(
                o["catalog_ra_deg"],o["catalog_dec_deg"],
                o["ra_deg"],o["dec_deg"])
            cat_gaia_e, cat_gaia_n, cat_gaia_sep, _ = angular_vector(
                gra,gdec,o["catalog_ra_deg"],o["catalog_dec_deg"])

            refs.append({
                "strict_rank_origin": rank,
                "source_id": sid,
                "g_mag": f(g.get("g_mag")),
                "gaia_ra_1951_deg": gra,
                "gaia_dec_1951_deg": gdec,
                "official_catalog_ra_deg": o["catalog_ra_deg"],
                "official_catalog_dec_deg": o["catalog_dec_deg"],
                "official_fit_ra_deg": o["ra_deg"],
                "official_fit_dec_deg": o["dec_deg"],
                "official_catalog_to_gaia_sep_arcsec": cat_sep,
                "official_fit_minus_gaia_east_arcsec": fit_gaia_e,
                "official_fit_minus_gaia_north_arcsec": fit_gaia_n,
                "official_fit_minus_gaia_sep_arcsec": fit_gaia_sep,
                "official_fit_minus_catalog_east_arcsec": fit_cat_e,
                "official_fit_minus_catalog_north_arcsec": fit_cat_n,
                "official_fit_minus_catalog_sep_arcsec": fit_cat_sep,
                "official_catalog_minus_gaia_east_arcsec": cat_gaia_e,
                "official_catalog_minus_gaia_north_arcsec": cat_gaia_n,
                "official_catalog_minus_gaia_sep_arcsec": cat_gaia_sep,
                "image_x": o["image_x"], "image_y": o["image_y"],
                "sxt_number": o["sxt_number"], "ref_number": o["ref_number"],
                "drad_rms2": o["drad_rms2"],
                "fwhm_image": o["fwhm_image"], "ellipticity": o["ellipticity"],
                "flux_max": o["flux_max"], "flux_iso": o["flux_iso"],
                "magcal_magdep": o["magcal_magdep"],
                "limiting_mag_local": o["limiting_mag_local"],
                "aflags": o["aflags"], "a2flags": o["a2flags"],
                "bflags": o["bflags"], "b2flags": o["b2flags"],
            })

    print(f"Official ordinary-star Gaia matches: N={len(refs)}")

    summaries = {}
    if refs:
        for name, ek, nk in (
            ("official_fit_minus_gaia",
             "official_fit_minus_gaia_east_arcsec",
             "official_fit_minus_gaia_north_arcsec"),
            ("official_fit_minus_catalog",
             "official_fit_minus_catalog_east_arcsec",
             "official_fit_minus_catalog_north_arcsec"),
            ("official_catalog_minus_gaia",
             "official_catalog_minus_gaia_east_arcsec",
             "official_catalog_minus_gaia_north_arcsec"),
        ):
            vec = np.array([[r[ek],r[nk]] for r in refs],float)
            med = np.median(vec,axis=0)
            rr = residuals_about(vec,med)
            summaries[name] = {
                "count": len(refs),
                "median_east_arcsec": float(med[0]),
                "median_north_arcsec": float(med[1]),
                "median_vector_magnitude_arcsec": float(math.hypot(*med)),
                "residual_median_arcsec": float(np.median(rr)),
                "residual_p95_arcsec": quantile95(rr),
                "circular_R": circular_R(vec[:,0],vec[:,1]),
            }
            print(
                f"  {name}: median=({med[0]:+.3f},{med[1]:+.3f})\" "
                f"mag={math.hypot(*med):.3f}\" "
                f"resid_med/p95={np.median(rr):.3f}/{quantile95(rr):.3f}\" "
                f"R={summaries[name]['circular_R']:.3f}"
            )
    print()

    # ------------------------------------------------------------------
    # Science-nearest official source diagnostics. These rows never enter
    # the reference summaries above.
    # ------------------------------------------------------------------
    science_near = []
    for rank in EXPECTED:
        s = strict[rank]
        dra,ddec = f(s["dasch_ra_deg"]),f(s["dasch_dec_deg"])
        choices = []
        for o in all_official_by_rank[rank]:
            if o["ra_deg"] is None or o["dec_deg"] is None:
                continue
            e,n,sep,pa = angular_vector(dra,ddec,o["ra_deg"],o["dec_deg"])
            choices.append((sep,e,n,pa,o))
        choices.sort(key=lambda q:q[0])
        if choices:
            sep,e,n,pa,o = choices[0]
            accepted = sep <= SCIENCE_NEAREST_MAX_ARCSEC
            row = {
                "strict_rank":rank,
                "frozen_dasch_ra_deg":dra,
                "frozen_dasch_dec_deg":ddec,
                "nearest_official_sep_arcsec":sep,
                "nearest_official_east_arcsec":e,
                "nearest_official_north_arcsec":n,
                "nearest_official_within_60arcsec":accepted,
                "official_fit_ra_deg":o["ra_deg"],
                "official_fit_dec_deg":o["dec_deg"],
                "official_catalog_ra_deg":o["catalog_ra_deg"],
                "official_catalog_dec_deg":o["catalog_dec_deg"],
                "image_x":o["image_x"],"image_y":o["image_y"],
                "sxt_number":o["sxt_number"],"ref_number":o["ref_number"],
                "drad_rms2":o["drad_rms2"],
                "fwhm_image":o["fwhm_image"],"ellipticity":o["ellipticity"],
                "flux_max":o["flux_max"],"flux_iso":o["flux_iso"],
                "magcal_magdep":o["magcal_magdep"],
                "limiting_mag_local":o["limiting_mag_local"],
                "aflags":o["aflags"],"a2flags":o["a2flags"],
                "bflags":o["bflags"],"b2flags":o["b2flags"],
            }
        else:
            row = {
                "strict_rank":rank,
                "frozen_dasch_ra_deg":dra,
                "frozen_dasch_dec_deg":ddec,
                "nearest_official_sep_arcsec":None,
                "nearest_official_within_60arcsec":False,
            }
        science_near.append(row)
        print(
            f"#{rank}: nearest official fitted source "
            f"{row['nearest_official_sep_arcsec'] if row['nearest_official_sep_arcsec'] is not None else 'n/a'}"
            f" arcsec from frozen DASCH coordinate"
        )

    # Direct adjudication versus v028q model.
    vq_model = vq.get("plate_model",{}).get("selected_model",{})
    vq_params = vq_model.get("params") if vq_model.get("kind")=="translation" else None
    comparison = {
        "v028q_translation_east_arcsec": vq_params[0] if vq_params else None,
        "v028q_translation_north_arcsec": vq_params[1] if vq_params else None,
    }
    if refs and vq_params:
        off = summaries["official_fit_minus_gaia"]
        comparison.update({
            "official_fit_minus_gaia_east_arcsec":off["median_east_arcsec"],
            "official_fit_minus_gaia_north_arcsec":off["median_north_arcsec"],
            "difference_between_v028q_and_official_median_arcsec":
                math.hypot(
                    off["median_east_arcsec"]-vq_params[0],
                    off["median_north_arcsec"]-vq_params[1],
                )
        })

    status = (
        "OFFICIAL_DASCH_ASTROMETRY_COMPLETE"
        if len(refs) >= MIN_ORDINARY_REFERENCE_COUNT
        else "INSUFFICIENT_OFFICIAL_DASCH_GAIA_REFERENCES"
    )

    ref_fields = [
        "strict_rank_origin","source_id","g_mag",
        "gaia_ra_1951_deg","gaia_dec_1951_deg",
        "official_catalog_ra_deg","official_catalog_dec_deg",
        "official_fit_ra_deg","official_fit_dec_deg",
        "official_catalog_to_gaia_sep_arcsec",
        "official_fit_minus_gaia_east_arcsec",
        "official_fit_minus_gaia_north_arcsec",
        "official_fit_minus_gaia_sep_arcsec",
        "official_fit_minus_catalog_east_arcsec",
        "official_fit_minus_catalog_north_arcsec",
        "official_fit_minus_catalog_sep_arcsec",
        "official_catalog_minus_gaia_east_arcsec",
        "official_catalog_minus_gaia_north_arcsec",
        "official_catalog_minus_gaia_sep_arcsec",
        "image_x","image_y","sxt_number","ref_number","drad_rms2",
        "fwhm_image","ellipticity","flux_max","flux_iso","magcal_magdep",
        "limiting_mag_local","aflags","a2flags","bflags","b2flags",
    ]
    write_csv(OUT_REFS, refs, ref_fields)

    near_fields = [
        "strict_rank","frozen_dasch_ra_deg","frozen_dasch_dec_deg",
        "nearest_official_sep_arcsec","nearest_official_east_arcsec",
        "nearest_official_north_arcsec","nearest_official_within_60arcsec",
        "official_fit_ra_deg","official_fit_dec_deg",
        "official_catalog_ra_deg","official_catalog_dec_deg",
        "image_x","image_y","sxt_number","ref_number","drad_rms2",
        "fwhm_image","ellipticity","flux_max","flux_iso","magcal_magdep",
        "limiting_mag_local","aflags","a2flags","bflags","b2flags",
    ]
    write_csv(OUT_NEAR, science_near, near_fields)

    summary_rows = []
    for name,su in summaries.items():
        summary_rows.append({"metric":name,**su})
    write_csv(
        OUT_CSV, summary_rows,
        ["metric","count","median_east_arcsec","median_north_arcsec",
         "median_vector_magnitude_arcsec","residual_median_arcsec",
         "residual_p95_arcsec","circular_R"]
    )

    payload = {
        "stage":"ORDER01_OFFICIAL_DASCH_PLATEPHOT_ASTROMETRY_V028R",
        "status":status,
        "frozen_active_ranks":EXPECTED,
        "guards":{
            "network_access":True,
            "network_endpoint":BASE_URL,
            "science_pixels_read":False,
            "candidate_pixels_used_as_reference_fit":False,
            "transient_detector_rerun":False,
            "transient_detector_parameters_changed":False,
            "candidate_state_mutation":False,
            "candidate_promotion":False,
            "candidate_deletion":False,
            "weighted_candidate_score":False,
        },
        "official_plate_solution":sol,
        "query_log":query_log,
        "ordinary_star_reference_count":len(refs),
        "ordinary_star_summaries":summaries,
        "comparison_to_v028q":comparison,
        "science_nearest_official_sources":science_near,
        "interpretive_boundary":(
            "Official DASCH DR7 fitted source positions and catalog positions "
            "provide an external check on the coherent v028q offset. Science "
            "positions are never used to determine the ordinary-star offset. "
            "Agreement with the official offset would strengthen the conclusion "
            "that near-zero science-pair catalogue separation is atypical of "
            "ordinary common sources on this plate pair; disagreement would "
            "identify v028q's raw-pixel centroiding/coordinate reconstruction "
            "as the likely source of the offset. Neither outcome alone proves "
            "an astrophysical transient or a specific artifact mechanism."
        )
    }
    write_json(OUT_JSON,payload)

    md = [
        "# ORDER 01 — Official DASCH DR7 Platephot Astrometric Adjudication v028r","",
        "## Guard state","",
        "- Official DASCH DR7 public network API was queried.",
        "- Science pixels were not read.",
        "- Candidate positions were not ordinary-star reference-fit inputs.",
        "- The frozen transient detector was not rerun.",
        "- No candidate was promoted, deleted, or otherwise mutated.","",
        "## Official plate solution","",
        f"- Plate: `{PLATE_ID}`",
        f"- WCS solution: `{solnum}`",
        f"- Official datetime: `{pick(rec,'datetime')}`",
        f"- Official exposure: `{pick(rec,'exposure')}` minutes","",
        "## Ordinary-star astrometry","",
        f"- Gaia↔official DR7 matched controls: **{len(refs)}**.",
    ]
    for name,su in summaries.items():
        md.append(
            f"- `{name}`: median east/north "
            f"**{su['median_east_arcsec']:+.3f}/{su['median_north_arcsec']:+.3f} arcsec**, "
            f"magnitude **{su['median_vector_magnitude_arcsec']:.3f} arcsec**, "
            f"residual p95 **{su['residual_p95_arcsec']:.3f} arcsec**, "
            f"directional R **{su['circular_R']:.3f}**."
        )
    md += ["","## Comparison to v028q","",
           f"- v028q translation: east `{comparison.get('v028q_translation_east_arcsec')}`, "
           f"north `{comparison.get('v028q_translation_north_arcsec')}` arcsec.",
           f"- v028q↔official median-vector difference: "
           f"`{comparison.get('difference_between_v028q_and_official_median_arcsec')}` arcsec.","",
           "## Science-nearest official DR7 sources","",
           "| rank | nearest official fitted source | within 60\" |",
           "|---:|---:|---|"]
    for r in science_near:
        d=r.get("nearest_official_sep_arcsec")
        md.append(
            f"| #{r['strict_rank']} | "
            f"{'n/a' if d is None else f'{d:.3f} arcsec'} | "
            f"{r.get('nearest_official_within_60arcsec')} |"
        )
    md += ["","## Interpretation boundary","",
           payload["interpretive_boundary"]]
    OUT_MD.write_text("\n".join(md),encoding="utf-8")

    print("\n" + "="*128)
    print(f"v028r complete: {status}")
    print(f"  {OUT_JSON}")
    print(f"  {OUT_CSV}")
    print(f"  {OUT_REFS}")
    print(f"  {OUT_NEAR}")
    print(f"  {OUT_MD}")
    print()
    print("Official DASCH DR7 network queries WERE made.")
    print("SCIENCE PIXELS WERE NOT READ.")
    print("Candidate positions were NOT ordinary-star reference-fit inputs.")
    print("Transient detector was NOT rerun.")
    print("No candidate was promoted or deleted.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
