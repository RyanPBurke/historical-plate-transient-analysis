from __future__ import annotations

from collections import Counter
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
import csv
import hashlib
import io
import json
import math
import time
import warnings

import numpy as np
import astropy.units as u
from astropy.coordinates import Distance, SkyCoord
from astropy.time import Time

ROOT = Path.cwd()
BASE = ROOT / "results" / "order61_native_full_v028"
WORK = ROOT / "work" / "order61_gaia_static_v028"
CACHE = WORK / "tap_cache"

REPORT = BASE / "order61_whole_pair_report.json"
RAW = BASE / "order61_raw_coincidences.csv"
STRICT = BASE / "order61_strict_match_triage.csv"

OUT_ROWS = BASE / "order61_gaia_static_triage.csv"
OUT_SOURCES = BASE / "order61_gaia_source_candidates.csv"
OUT_TILE = BASE / "order61_dasch_tile_radial_normalization.csv"
OUT_REPORT = BASE / "order61_gaia_static_report.json"

for d in (WORK, CACHE):
    d.mkdir(parents=True, exist_ok=True)

TAP = "https://gea.esac.esa.int/tap-server/tap/sync"
UA = "historical-transient-pipeline/0.2.8-order61-gaia-static"

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

# Predeclared independently of Gaia outcomes.
GAIA_STRONG_ARCSEC = 3.0
GAIA_DIAGNOSTIC_ARCSEC = 5.0
GAIA_CONE_ARCSEC = 120.0
HPM_RESCUE_MIN_MASYR = 1800.0
HPM_RESCUE_CONE_ARCSEC = 900.0
MAX_CONE_ROWS = 10000
MAX_HPM_RESCUE_ROWS = 10000

GAIA_COLUMNS = [
    "source_id", "ra", "dec", "ref_epoch",
    "ra_error", "dec_error",
    "parallax", "parallax_error",
    "pm", "pmra", "pmdec",
    "pmra_error", "pmdec_error",
    "radial_velocity",
    "phot_g_mean_mag", "bp_rp", "ruwe",
    "astrometric_params_solved",
]

ROW_FIELDS = [
    "strict_rank", "pair_separation_arcsec",
    "poss_ra_deg", "poss_dec_deg",
    "dasch_ra_deg", "dasch_dec_deg",
    "poss_snr", "dasch_snr",
    "poss_polarity", "dasch_polarity",
    "same_polarity",
    "gaia_class",
    "gaia_any_endpoint_within_3arcsec",
    "gaia_both_endpoints_within_3arcsec",
    "gaia_any_endpoint_within_5arcsec",
    "gaia_both_endpoints_within_5arcsec",
    "survives_conservative_gaia_3arcsec_any_endpoint_gate",
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

SOURCE_FIELDS = [
    "strict_rank", "source_id", "origin",
    "ra_2016_deg", "dec_2016_deg", "ref_epoch",
    "pm_masyr", "pmra_masyr", "pmdec_masyr",
    "pmra_error_masyr", "pmdec_error_masyr",
    "parallax_mas", "radial_velocity_kms",
    "g_mag", "bp_rp", "ruwe",
    "astrometric_params_solved",
    "propagated",
    "ra_target_deg", "dec_target_deg",
    "sep_poss_arcsec", "sep_dasch_arcsec",
    "max_endpoint_sep_arcsec", "min_endpoint_sep_arcsec",
    "approx_pm_propagation_sigma_arcsec",
]

TILE_FIELDS = [
    "dasch_tile_id",
    "accepted_core_candidates",
    "raw_le_10arcsec",
    "strict_le_3arcsec",
    "strict_fraction_of_raw",
    "conditional_area_expected_strict",
    "conditional_area_binomial_sd",
    "z_vs_conditional_area_null",
    "raw_matches_per_1000_candidates",
    "strict_matches_per_1000_candidates",
]


def finite_float(v):
    if v is None:
        return None
    s = str(v).strip()
    if not s or s.lower() in {"nan", "null", "none"}:
        return None
    try:
        x = float(s)
    except ValueError:
        return None
    return x if math.isfinite(x) else None


def int_or_none(v):
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


def sha_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def write_csv(path: Path, rows: list[dict], fields: list[str]):
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


def load_csv(path: Path):
    with path.open(newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def midpoint_time(report):
    """
    Parse canonical ISO-8601 UTC overlap strings robustly and
    return the midpoint as an Astropy Time.
    """
    from datetime import datetime, timezone

    start = report.get("overlap_start_utc")
    end = report.get("overlap_end_utc")
    if not start or not end:
        raise RuntimeError(
            "REFUSING: overlap start/end absent from complete report"
        )

    def parse_utc(value):
        s = str(value).strip()
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            raise RuntimeError(
                f"REFUSING: timezone-naive canonical timestamp: {value!r}"
            )
        return Time(dt.astimezone(timezone.utc), scale="utc")

    t0 = parse_utc(start)
    t1 = parse_utc(end)
    if not (t1 > t0):
        raise RuntimeError("REFUSING: invalid overlap interval")
    return t0 + (t1 - t0) / 2.0



def tap_query(adql: str, cache_stem: str, attempts: int = 4):
    csv_path = CACHE / f"{cache_stem}.csv"
    meta_path = CACHE / f"{cache_stem}.json"

    if csv_path.is_file() and meta_path.is_file():
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        b = csv_path.read_bytes()
        if (
            meta.get("complete") is True
            and meta.get("adql") == adql
            and meta.get("sha256") == sha_bytes(b)
        ):
            return parse_gaia_csv(b), meta, "cached"

    params = urlencode({
        "REQUEST": "doQuery",
        "LANG": "ADQL",
        "FORMAT": "csv",
        "QUERY": adql,
    }).encode("utf-8")

    errors = []
    for attempt in range(1, attempts + 1):
        try:
            req = Request(
                TAP,
                data=params,
                headers={
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Accept": "text/csv,*/*",
                    "User-Agent": UA,
                },
                method="POST",
            )
            with urlopen(req, timeout=180) as r:
                body = r.read()
                status = getattr(r, "status", 200)
                ctype = r.headers.get("Content-Type", "")

            if status != 200:
                raise RuntimeError(f"HTTP {status}")

            preview = body[:300].decode("utf-8", errors="replace")
            if "QUERY_STATUS" in preview or "<VOTABLE" in preview.upper():
                raise RuntimeError(
                    "Gaia TAP returned a non-CSV error/VO response: "
                    + preview.replace("\n", " ")[:250]
                )

            rows = parse_gaia_csv(body)
            csv_path.write_bytes(body)
            meta = {
                "complete": True,
                "adql": adql,
                "sha256": sha_bytes(body),
                "bytes": len(body),
                "row_count": len(rows),
                "content_type": ctype,
                "tap": TAP,
            }
            write_json(meta_path, meta)
            return rows, meta, "done"

        except (HTTPError, URLError, TimeoutError, RuntimeError) as exc:
            errors.append(repr(exc))
            print(
                f"    Gaia TAP {cache_stem} attempt {attempt}/{attempts} FAILED: {exc}",
                flush=True,
            )
            if attempt < attempts:
                time.sleep(2 ** attempt)

    raise RuntimeError(
        f"Gaia TAP failed for {cache_stem} after {attempts} attempts: {errors[-1]}"
    )


def parse_gaia_csv(body: bytes):
    text = body.decode("utf-8-sig", errors="strict")
    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None:
        raise RuntimeError("Gaia TAP CSV has no header")

    out = []
    for raw in reader:
        r = {str(k).strip().lower(): v for k, v in raw.items()}
        sid = str(r.get("source_id", "")).strip()
        if not sid:
            continue
        out.append({
            "source_id": sid,
            "ra": finite_float(r.get("ra")),
            "dec": finite_float(r.get("dec")),
            "ref_epoch": finite_float(r.get("ref_epoch")),
            "ra_error": finite_float(r.get("ra_error")),
            "dec_error": finite_float(r.get("dec_error")),
            "parallax": finite_float(r.get("parallax")),
            "parallax_error": finite_float(r.get("parallax_error")),
            "pm": finite_float(r.get("pm")),
            "pmra": finite_float(r.get("pmra")),
            "pmdec": finite_float(r.get("pmdec")),
            "pmra_error": finite_float(r.get("pmra_error")),
            "pmdec_error": finite_float(r.get("pmdec_error")),
            "radial_velocity": finite_float(r.get("radial_velocity")),
            "phot_g_mean_mag": finite_float(r.get("phot_g_mean_mag")),
            "bp_rp": finite_float(r.get("bp_rp")),
            "ruwe": finite_float(r.get("ruwe")),
            "astrometric_params_solved": int_or_none(
                r.get("astrometric_params_solved")
            ),
        })
    return out


def gaia_select():
    return ", ".join(GAIA_COLUMNS)


def cone_adql(ra_deg: float, dec_deg: float):
    radius_deg = GAIA_CONE_ARCSEC / 3600.0
    return (
        f"SELECT TOP {MAX_CONE_ROWS} {gaia_select()} "
        "FROM gaiadr3.gaia_source "
        "WHERE 1 = CONTAINS("
        "POINT('ICRS', ra, dec), "
        f"CIRCLE('ICRS', {ra_deg:.12f}, {dec_deg:.12f}, {radius_deg:.12f})"
        ")"
    )


def hpm_local_adql(ra_deg: float, dec_deg: float):
    """
    Local high-proper-motion rescue query.

    The ordinary 120" J2016 cone contains every source whose
    displacement from 1953 to 2016 is small enough to remain
    inside that cone. Only sufficiently high-PM stars can escape,
    so query those locally in a much larger cone instead of
    performing an all-sky pm scan.
    """
    radius_deg = HPM_RESCUE_CONE_ARCSEC / 3600.0
    return (
        f"SELECT TOP {MAX_HPM_RESCUE_ROWS} {gaia_select()} "
        "FROM gaiadr3.gaia_source "
        f"WHERE pm > {HPM_RESCUE_MIN_MASYR:.6f} "
        "AND 1 = CONTAINS("
        "POINT('ICRS', ra, dec), "
        f"CIRCLE('ICRS', {ra_deg:.12f}, {dec_deg:.12f}, {radius_deg:.12f})"
        ")"
    )



def propagate_source(src, target: Time):
    if src["ra"] is None or src["dec"] is None:
        return None

    propagated = (
        src["pmra"] is not None
        and src["pmdec"] is not None
        and src["ref_epoch"] is not None
    )

    if not propagated:
        c = SkyCoord(src["ra"] * u.deg, src["dec"] * u.deg, frame="icrs")
        return c, False, None

    kwargs = dict(
        ra=src["ra"] * u.deg,
        dec=src["dec"] * u.deg,
        pm_ra_cosdec=src["pmra"] * u.mas / u.yr,
        pm_dec=src["pmdec"] * u.mas / u.yr,
        obstime=Time(src["ref_epoch"], format="jyear"),
        frame="icrs",
    )

    # Include perspective acceleration only when both distance and radial
    # velocity are usable; otherwise Astropy performs tangential propagation.
    if (
        src["parallax"] is not None
        and src["parallax"] > 0
        and src["radial_velocity"] is not None
    ):
        try:
            kwargs["distance"] = Distance(parallax=src["parallax"] * u.mas)
            kwargs["radial_velocity"] = src["radial_velocity"] * u.km / u.s
        except Exception:
            pass

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        c0 = SkyCoord(**kwargs)
        c1 = c0.apply_space_motion(new_obstime=target)

    dt_years = abs(
        target.jyear - float(src["ref_epoch"])
    )

    sigmas = []
    if src["pmra_error"] is not None:
        sigmas.append(dt_years * src["pmra_error"] / 1000.0)
    if src["pmdec_error"] is not None:
        sigmas.append(dt_years * src["pmdec_error"] / 1000.0)

    approx_sigma_arcsec = (
        math.sqrt(sum(x * x for x in sigmas))
        if sigmas
        else None
    )

    return c1, True, approx_sigma_arcsec


def midpoint_coord(p: SkyCoord, d: SkyCoord):
    xyz = p.cartesian.xyz.value + d.cartesian.xyz.value
    xyz = xyz / np.linalg.norm(xyz)
    return SkyCoord(
        x=xyz[0], y=xyz[1], z=xyz[2],
        representation_type="cartesian",
        frame="icrs",
    )


def classify_pair(source_rows):
    if not source_rows:
        return {
            "gaia_class": "NO_GAIA_WITHIN_5_ARCSEC_AT_TARGET_EPOCH",
            "any3": False, "both3": False,
            "any5": False, "both5": False,
            "best_both": None, "best_poss": None, "best_dasch": None,
        }

    best_both = min(source_rows, key=lambda r: r["max_endpoint_sep_arcsec"])
    best_poss = min(source_rows, key=lambda r: r["sep_poss_arcsec"])
    best_dasch = min(source_rows, key=lambda r: r["sep_dasch_arcsec"])

    any3 = min(
        best_poss["sep_poss_arcsec"],
        best_dasch["sep_dasch_arcsec"],
    ) <= GAIA_STRONG_ARCSEC

    both3 = best_both["max_endpoint_sep_arcsec"] <= GAIA_STRONG_ARCSEC

    any5 = min(
        best_poss["sep_poss_arcsec"],
        best_dasch["sep_dasch_arcsec"],
    ) <= GAIA_DIAGNOSTIC_ARCSEC

    both5 = best_both["max_endpoint_sep_arcsec"] <= GAIA_DIAGNOSTIC_ARCSEC

    if both3:
        suffix = "PROPAGATED" if best_both["propagated"] else "POSITION_ONLY"
        cls = f"GAIA_STATIC_BOTH_STRONG_{suffix}"
    elif any3:
        b = best_poss if best_poss["sep_poss_arcsec"] <= best_dasch["sep_dasch_arcsec"] else best_dasch
        suffix = "PROPAGATED" if b["propagated"] else "POSITION_ONLY"
        cls = f"GAIA_STATIC_ONE_ENDPOINT_STRONG_{suffix}"
    elif both5:
        suffix = "PROPAGATED" if best_both["propagated"] else "POSITION_ONLY"
        cls = f"GAIA_STATIC_BOTH_DIAGNOSTIC_{suffix}"
    elif any5:
        cls = "GAIA_STATIC_ONE_ENDPOINT_DIAGNOSTIC"
    else:
        cls = "NO_GAIA_WITHIN_5_ARCSEC_AT_TARGET_EPOCH"

    return {
        "gaia_class": cls,
        "any3": any3,
        "both3": both3,
        "any5": any5,
        "both5": both5,
        "best_both": best_both,
        "best_poss": best_poss,
        "best_dasch": best_dasch,
    }


def get_tile_candidate_counts():
    out = {}
    d = ROOT / "work" / "order61_native_full_v028" / "dasch_tiles"
    if not d.is_dir():
        return out
    for p in d.glob("D_*.json"):
        try:
            m = json.loads(p.read_text(encoding="utf-8"))
            if m.get("complete") is True:
                out[m["tile_id"]] = int(m["accepted_core_peaks"])
        except Exception:
            continue
    return out


def main():
    print("=" * 88)
    print("ORDER 61 — GAIA DR3 STATIC-SOURCE / EPOCH-PROPAGATION TRIAGE")
    print("=" * 88)
    print("No detector run. No image pixels read. No candidate is deleted.")
    print()

    if not (REPORT.is_file() and RAW.is_file() and STRICT.is_file()):
        raise RuntimeError("REFUSING: required completed order61 result files are missing")

    report = json.loads(REPORT.read_text(encoding="utf-8"))

    guards = {
        "status": report.get("status") == "COMPLETE",
        "order": int(report.get("canonical_order", -1)) == 61,
        "detector": report.get("detector_sha256") == EXPECTED_DETECTOR_SHA,
        "method": report.get("method_sha256") == EXPECTED_METHOD_SHA,
        "policy": report.get("policy_sha256") == EXPECTED_POLICY_SHA,
        "raw_count": int(report.get("raw_le_10arcsec", -1)) == 235,
        "strict_count": int(report.get("raw_le_3arcsec", -1)) == 23,
    }
    if not all(guards.values()):
        raise RuntimeError("REFUSING: completed-result guard failure: " + repr(guards))

    target = midpoint_time(report)
    print("Completed result guards: PASS")
    print("Target epoch:", target.utc.isot)
    print(
        f"Gaia strong/static radius: {GAIA_STRONG_ARCSEC:.1f}\"; "
        f"diagnostic radius: {GAIA_DIAGNOSTIC_ARCSEC:.1f}\""
    )
    # Worst-case midpoint-to-endpoint margin for a <=3" pair plus
    # the 5" diagnostic static radius.
    dt_years = abs(2016.0 - float(target.utc.jyear))
    historical_margin_arcsec = GAIA_DIAGNOSTIC_ARCSEC + 1.5
    escape_pm_masyr = (
        (GAIA_CONE_ARCSEC - historical_margin_arcsec)
        * 1000.0
        / dt_years
    )
    rescue_coverage_pm_masyr = (
        (HPM_RESCUE_CONE_ARCSEC - historical_margin_arcsec)
        * 1000.0
        / dt_years
    )

    if HPM_RESCUE_MIN_MASYR > escape_pm_masyr:
        raise RuntimeError(
            "REFUSING: local HPM rescue threshold leaves a proper-motion gap"
        )

    print(
        f"Gaia J2016 normal cone: {GAIA_CONE_ARCSEC:.0f}\""
    )
    print(
        f"Local HPM rescue: pm>{HPM_RESCUE_MIN_MASYR:.0f} mas/yr "
        f"within {HPM_RESCUE_CONE_ARCSEC:.0f}\""
    )
    print(
        f"Escape threshold from normal cone: ~{escape_pm_masyr:.0f} mas/yr"
    )
    print(
        f"Local rescue geometric coverage: ~{rescue_coverage_pm_masyr:.0f} mas/yr"
    )
    print(
        "Objects faster than that finite local-rescue bound are not "
        "auto-rejected; they remain conservative survivors for the "
        "independent static-sky follow-up."
    )
    print()

    strict_raw = load_csv(STRICT)
    raw_all = load_csv(RAW)
    if len(strict_raw) != 23 or len(raw_all) != 235:
        raise RuntimeError("REFUSING: triage/raw CSV row count changed")

    result_rows = []
    source_rows_all = []

    print("[1/2] Querying and propagating Gaia candidates for all 23 strict associations ...", flush=True)

    for idx, r in enumerate(strict_raw, 1):
        rank = int(r["strict_rank"])
        p = SkyCoord(float(r["poss_ra_deg"]) * u.deg, float(r["poss_dec_deg"]) * u.deg)
        d = SkyCoord(float(r["dasch_ra_deg"]) * u.deg, float(r["dasch_dec_deg"]) * u.deg)
        mid = midpoint_coord(p, d)

        # midpoint_coord() returns a Cartesian-representation SkyCoord;
        # use spherical lon/lat rather than .ra/.dec accessors.
        cone, cone_meta, cone_status = tap_query(
            cone_adql(float(mid.spherical.lon.deg), float(mid.spherical.lat.deg)),
            f"strict_{rank:02d}_cone120",
        )
        if len(cone) >= MAX_CONE_ROWS:
            raise RuntimeError(
                f"REFUSING: strict {rank} Gaia cone query hit TOP {MAX_CONE_ROWS}"
            )

        hpm, hpm_meta, hpm_status = tap_query(
            hpm_local_adql(float(mid.spherical.lon.deg), float(mid.spherical.lat.deg)),
            f"strict_{rank:02d}_hpm900_pm1800",
        )
        if len(hpm) >= MAX_HPM_RESCUE_ROWS:
            raise RuntimeError(
                f"REFUSING: strict {rank} local HPM query hit TOP "
                f"{MAX_HPM_RESCUE_ROWS}"
            )

        merged = {}
        origins = {}

        for s in cone:
            merged[s["source_id"]] = s
            origins.setdefault(s["source_id"], set()).add("cone120")

        for s in hpm:
            merged.setdefault(s["source_id"], s)
            origins.setdefault(s["source_id"], set()).add("hpm900_pm1800")

        local_sources = []

        for sid, src in merged.items():
            prop = propagate_source(src, target)
            if prop is None:
                continue
            c, did_prop, approx_sigma = prop
            sp = float(c.separation(p).arcsec)
            sd = float(c.separation(d).arcsec)

            # Keep all normal-cone rows for audit. HPM-rescue-only rows
            # are retained when they approach the historical pair.
            if "cone120" not in origins[sid] and min(sp, sd) > 30.0:
                continue

            sr = {
                "strict_rank": rank,
                "source_id": sid,
                "origin": "+".join(sorted(origins[sid])),
                "ra_2016_deg": src["ra"],
                "dec_2016_deg": src["dec"],
                "ref_epoch": src["ref_epoch"],
                "pm_masyr": src["pm"],
                "pmra_masyr": src["pmra"],
                "pmdec_masyr": src["pmdec"],
                "pmra_error_masyr": src["pmra_error"],
                "pmdec_error_masyr": src["pmdec_error"],
                "parallax_mas": src["parallax"],
                "radial_velocity_kms": src["radial_velocity"],
                "g_mag": src["phot_g_mean_mag"],
                "bp_rp": src["bp_rp"],
                "ruwe": src["ruwe"],
                "astrometric_params_solved": src["astrometric_params_solved"],
                "propagated": did_prop,
                "ra_target_deg": float(c.ra.deg),
                "dec_target_deg": float(c.dec.deg),
                "sep_poss_arcsec": sp,
                "sep_dasch_arcsec": sd,
                "max_endpoint_sep_arcsec": max(sp, sd),
                "min_endpoint_sep_arcsec": min(sp, sd),
                "approx_pm_propagation_sigma_arcsec": approx_sigma,
            }
            local_sources.append(sr)

        local_sources.sort(key=lambda x: x["max_endpoint_sep_arcsec"])
        source_rows_all.extend(local_sources)

        q = classify_pair(local_sources)
        bb, bp, bd = q["best_both"], q["best_poss"], q["best_dasch"]

        result_rows.append({
            "strict_rank": rank,
            "pair_separation_arcsec": float(r["separation_arcsec"]),
            "poss_ra_deg": float(r["poss_ra_deg"]),
            "poss_dec_deg": float(r["poss_dec_deg"]),
            "dasch_ra_deg": float(r["dasch_ra_deg"]),
            "dasch_dec_deg": float(r["dasch_dec_deg"]),
            "poss_snr": float(r["poss_snr"]),
            "dasch_snr": float(r["dasch_snr"]),
            "poss_polarity": int(r["poss_polarity"]),
            "dasch_polarity": int(r["dasch_polarity"]),
            "same_polarity": as_bool(r["same_polarity"]),
            "gaia_class": q["gaia_class"],
            "gaia_any_endpoint_within_3arcsec": q["any3"],
            "gaia_both_endpoints_within_3arcsec": q["both3"],
            "gaia_any_endpoint_within_5arcsec": q["any5"],
            "gaia_both_endpoints_within_5arcsec": q["both5"],
            "survives_conservative_gaia_3arcsec_any_endpoint_gate": not q["any3"],
            "best_both_source_id": None if bb is None else bb["source_id"],
            "best_both_sep_poss_arcsec": None if bb is None else bb["sep_poss_arcsec"],
            "best_both_sep_dasch_arcsec": None if bb is None else bb["sep_dasch_arcsec"],
            "best_both_max_sep_arcsec": None if bb is None else bb["max_endpoint_sep_arcsec"],
            "best_both_propagated": None if bb is None else bb["propagated"],
            "best_both_g_mag": None if bb is None else bb["g_mag"],
            "best_poss_source_id": None if bp is None else bp["source_id"],
            "best_poss_sep_arcsec": None if bp is None else bp["sep_poss_arcsec"],
            "best_poss_propagated": None if bp is None else bp["propagated"],
            "best_dasch_source_id": None if bd is None else bd["source_id"],
            "best_dasch_sep_arcsec": None if bd is None else bd["sep_dasch_arcsec"],
            "best_dasch_propagated": None if bd is None else bd["propagated"],
            "gaia_sources_examined": len(local_sources),
            "cone_rows": len(cone),
            "hpm_rescue_rows": len(hpm),
            "target_epoch_iso": target.utc.isot,
        })

        nearest = None if bb is None else bb["max_endpoint_sep_arcsec"]
        neartext = "none" if nearest is None else f"{nearest:.3f}\""
        print(
            f"  [{idx:02d}/23] strict #{rank:02d} "
            f"cone={cone_status.upper():6s}:{len(cone):4d} "
            f"hpm={hpm_status.upper():6s}:{len(hpm):2d} "
            f"best-both={neartext:>9s} {q['gaia_class']}",
            flush=True,
        )

    # ------------------------------------------------------------
    # Normalize the apparent strict-match concentration in DASCH tiles
    # against raw <=10" associations and detector-candidate counts.
    # ------------------------------------------------------------
    print()
    print("[2/2] Normalizing DASCH tile concentration ...")

    tile_candidates = get_tile_candidate_counts()
    raw_by_tile = Counter(r["dasch_tile_id"] for r in raw_all)
    strict_by_tile = Counter(
        r["dasch_tile_id"] for r in raw_all if as_bool(r["strict_le_3arcsec"])
    )

    tile_ids = sorted(set(tile_candidates) | set(raw_by_tile))
    tile_rows = []

    for tid in tile_ids:
        cand = int(tile_candidates.get(tid, 0))
        raw_n = int(raw_by_tile.get(tid, 0))
        strict_n = int(strict_by_tile.get(tid, 0))
        p = 0.09
        exp = raw_n * p
        sd = math.sqrt(raw_n * p * (1 - p)) if raw_n else 0.0
        z = (strict_n - exp) / sd if sd else 0.0

        tile_rows.append({
            "dasch_tile_id": tid,
            "accepted_core_candidates": cand,
            "raw_le_10arcsec": raw_n,
            "strict_le_3arcsec": strict_n,
            "strict_fraction_of_raw": strict_n / raw_n if raw_n else None,
            "conditional_area_expected_strict": exp,
            "conditional_area_binomial_sd": sd,
            "z_vs_conditional_area_null": z,
            "raw_matches_per_1000_candidates": (
                1000.0 * raw_n / cand if cand else None
            ),
            "strict_matches_per_1000_candidates": (
                1000.0 * strict_n / cand if cand else None
            ),
        })

    write_csv(OUT_ROWS, result_rows, ROW_FIELDS)
    write_csv(OUT_SOURCES, source_rows_all, SOURCE_FIELDS)
    write_csv(OUT_TILE, tile_rows, TILE_FIELDS)

    class_counts = Counter(r["gaia_class"] for r in result_rows)
    any3_count = sum(as_bool(r["gaia_any_endpoint_within_3arcsec"]) for r in result_rows)
    both3_count = sum(as_bool(r["gaia_both_endpoints_within_3arcsec"]) for r in result_rows)
    survivors = [r for r in result_rows if as_bool(r["survives_conservative_gaia_3arcsec_any_endpoint_gate"])]

    report_out = {
        "status": "COMPLETE",
        "analysis_kind": "order61_gaia_dr3_static_epoch_propagation",
        "gaia_release": "DR3",
        "gaia_table": "gaiadr3.gaia_source",
        "tap_endpoint": TAP,
        "target_epoch_utc": target.utc.isot,
        "target_epoch_jyear_utc": float(target.utc.jyear),
        "predeclared_thresholds": {
            "strong_static_arcsec": GAIA_STRONG_ARCSEC,
            "diagnostic_static_arcsec": GAIA_DIAGNOSTIC_ARCSEC,
            "j2016_cone_arcsec": GAIA_CONE_ARCSEC,
            "local_hpm_rescue_min_masyr": HPM_RESCUE_MIN_MASYR,
            "local_hpm_rescue_cone_arcsec": HPM_RESCUE_CONE_ARCSEC,
            "normal_cone_escape_threshold_masyr": escape_pm_masyr,
            "local_hpm_rescue_coverage_masyr": rescue_coverage_pm_masyr,
        },
        "guards": guards,
        "strict_input_count": len(result_rows),
        "gaia_any_endpoint_within_3arcsec": any3_count,
        "gaia_both_endpoints_within_3arcsec": both3_count,
        "conservative_gaia_3arcsec_survivor_count": len(survivors),
        "class_counts": dict(sorted(class_counts.items())),
        "high_pm_strategy": "local_900arcsec_pm_gt_1800_rescue_per_strict_pair",
        "high_pm_strategy_is_conservative": True,
        "no_candidate_deleted": True,
        "global_all_sky_high_pm_query_used": False,
        "detector_rerun": False,
        "pixels_read": False,
        "outputs": {
            "pair_triage_csv": str(OUT_ROWS),
            "source_candidates_csv": str(OUT_SOURCES),
            "dasch_tile_normalization_csv": str(OUT_TILE),
        },
        "next_stage": (
            "Run local morphology/PSF/saturation/registration vetting on Gaia "
            "3-arcsec survivors, while retaining all 23 rows in the audit trail. "
            "If Gaia leaves survivors, add a second static catalogue / image check "
            "before physical interpretation."
        ),
    }
    write_json(OUT_REPORT, report_out)

    print()
    print("=" * 88)
    print("GAIA STATIC-SOURCE TRIAGE COMPLETE")
    print("=" * 88)
    print(f"Strict associations input:               {len(result_rows)}")
    print(f"Gaia within 3\" of either endpoint:       {any3_count}")
    print(f"Gaia within 3\" of both endpoints:        {both3_count}")
    print(f"Conservative 3\" Gaia survivors:          {len(survivors)}")
    print()
    print("Classification counts:")
    for k, v in sorted(class_counts.items()):
        print(f"  {k}: {v}")

    print()
    print("DASCH tile radial-normalization:")
    for r in sorted(tile_rows, key=lambda x: (-x["strict_le_3arcsec"], x["dasch_tile_id"])):
        if r["raw_le_10arcsec"]:
            print(
                f"  {r['dasch_tile_id']}: raw10={r['raw_le_10arcsec']:3d} "
                f"strict3={r['strict_le_3arcsec']:2d} "
                f"expected={r['conditional_area_expected_strict']:.2f} "
                f"z={r['z_vs_conditional_area_null']:+.2f}"
            )

    print()
    if survivors:
        print("Gaia 3\" survivors (retained for morphology/static follow-up):")
        for r in survivors:
            print(
                f"  strict #{int(r['strict_rank']):02d} "
                f"pair_sep={float(r['pair_separation_arcsec']):.3f}\" "
                f"minSNR={min(float(r['poss_snr']), float(r['dasch_snr'])):.2f} "
                f"class={r['gaia_class']}"
            )
    else:
        print("No strict association survives the conservative Gaia 3\" any-endpoint gate.")

    print()
    print("Outputs:")
    print(" ", OUT_REPORT)
    print(" ", OUT_ROWS)
    print(" ", OUT_SOURCES)
    print(" ", OUT_TILE)
    print()
    print("No detector parameter changed.")
    print("No image pixel was read.")
    print("No candidate was deleted.")


if __name__ == "__main__":
    main()
