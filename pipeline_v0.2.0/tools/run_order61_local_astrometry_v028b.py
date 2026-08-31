from __future__ import annotations

from pathlib import Path
from urllib.parse import urlencode
from datetime import datetime, timezone
import csv
import hashlib
import io
import json
import math
import shutil
import subprocess
import time

import numpy as np
import astropy.units as u
from astropy.coordinates import SkyCoord, Distance
from astropy.time import Time

ROOT = Path.cwd()
BASE = ROOT / "results" / "order61_native_full_v028"
WORK = ROOT / "work" / "order61_local_astrometry_v028"
CACHE = WORK / "gaia_cache"

PAIR_REPORT = BASE / "order61_whole_pair_report.json"
STAGE3_REPORT = BASE / "order61_platephot_stage3_report.json"
STAGE3_POLICY = BASE / "order61_platephot_stage3_policy.json"
RAW = BASE / "order61_raw_coincidences.csv"
STRICT = BASE / "order61_strict_match_triage.csv"
GAIA_TRIAGE = BASE / "order61_gaia_static_triage.csv"
PREFLIGHT = BASE / "order61_local_astrometry_preflight_v028.json"

OUT_REFS = BASE / "order61_local_astrometry_gaia_references_v028.csv"
OUT_SUMMARY = BASE / "order61_local_astrometry_summary_v028.csv"
OUT_REPORT = BASE / "order61_local_astrometry_report_v028.json"

for d in (WORK, CACHE):
    d.mkdir(parents=True, exist_ok=True)

TAP = "https://gea.esac.esa.int/tap-server/tap/sync"
UA = "historical-transient-pipeline/0.2.8-order61-local-astrometry"

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
EXPECTED_STAGE3_POLICY_SHA = (
    "5e73c8d24ce34a0836fd11c2466e9899"
    "904a16fe845b34f292b10ba4b645b4d1"
)

ACTIVE_RANKS = [11, 14, 20]
REFERENCE_RADII_ARCMIN = [5.0, 10.0, 20.0, 30.0]
MIN_LOCAL_REFS = 5
GAIA_BOTH_ENDPOINT_ARCSEC = 3.0
GAIA_CONE_ARCSEC = 120.0
HPM_RESCUE_CONE_ARCSEC = 900.0
HPM_RESCUE_MIN_MASYR = 1800.0
MAX_CONE_ROWS = 10000
MAX_HPM_ROWS = 10000
MAX_ATTEMPTS = 4

GAIA_COLUMNS = [
    "source_id", "ra", "dec", "ref_epoch",
    "ra_error", "dec_error", "parallax", "parallax_error",
    "pm", "pmra", "pmdec", "pmra_error", "pmdec_error",
    "radial_velocity", "phot_g_mean_mag", "bp_rp", "ruwe",
    "astrometric_params_solved",
]

REF_FIELDS = [
    "survivor_rank", "window_arcmin", "selected_window",
    "raw_match_index", "raw_pair_separation_arcsec",
    "raw_pair_midpoint_sep_from_survivor_arcmin",
    "poss_tile_id", "poss_candidate_index",
    "dasch_tile_id", "dasch_candidate_index",
    "poss_ra_deg", "poss_dec_deg", "dasch_ra_deg", "dasch_dec_deg",
    "east_offset_arcsec", "north_offset_arcsec",
    "gaia_source_id", "gaia_g_mag", "gaia_propagated",
    "gaia_ra_target_deg", "gaia_dec_target_deg",
    "gaia_sep_poss_arcsec", "gaia_sep_dasch_arcsec",
    "gaia_max_endpoint_sep_arcsec", "gaia_pm_masyr",
    "gaia_ruwe", "gaia_approx_pm_sigma_arcsec",
    "dedupe_kept",
]

SUMMARY_FIELDS = [
    "strict_rank", "status", "selected_radius_arcmin",
    "reference_count",
    "candidate_raw_separation_arcsec",
    "candidate_raw_east_arcsec", "candidate_raw_north_arcsec",
    "local_median_east_arcsec", "local_median_north_arcsec",
    "local_robust_sigma_east_arcsec", "local_robust_sigma_north_arcsec",
    "candidate_corrected_east_arcsec", "candidate_corrected_north_arcsec",
    "candidate_corrected_separation_arcsec",
    "loo_reference_residual_median_arcsec",
    "loo_reference_residual_p95_arcsec",
    "candidate_upper_tail_empirical_p",
    "candidate_within_reference_p95",
    "refs_5arcmin", "refs_10arcmin", "refs_20arcmin", "refs_30arcmin",
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


def sha256_file(path: Path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_bytes(b: bytes):
    return hashlib.sha256(b).hexdigest()


def as_bool(v):
    return str(v).strip().lower() in {"true", "1", "yes", "y", "t"}


def ffloat(v):
    if v is None:
        return None
    s = str(v).strip()
    if not s or s.lower() in {"nan", "null", "none", "--"}:
        return None
    try:
        x = float(s)
    except Exception:
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
    except Exception:
        try:
            return int(float(s))
        except Exception:
            return None


def parse_utc_time(v):
    s = str(v).strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        raise RuntimeError(f"timezone-naive timestamp: {v!r}")
    return Time(dt.astimezone(timezone.utc), scale="utc")


def target_epoch(pair_report):
    t0 = parse_utc_time(pair_report["overlap_start_utc"])
    t1 = parse_utc_time(pair_report["overlap_end_utc"])
    if not t1 > t0:
        raise RuntimeError("invalid overlap interval")
    return t0 + (t1 - t0) / 2.0


def midpoint_coord(p: SkyCoord, d: SkyCoord):
    """
    Unit-vector spherical midpoint, returned explicitly in spherical ICRS
    representation so .ra/.dec are always available.

    v028 failed before the first Gaia reference query because the same
    vector midpoint was returned as a Cartesian-representation SkyCoord.
    That was an implementation-only representation bug; the midpoint
    mathematics and all scientific thresholds/policies are unchanged.
    """
    a = p.cartesian.xyz.value
    b = d.cartesian.xyz.value
    v = a + b
    n = float(np.linalg.norm(v))
    if not np.isfinite(n) or n <= 0:
        raise RuntimeError("invalid/antipodal pair midpoint")
    v = v / n

    ra = math.atan2(float(v[1]), float(v[0]))
    if ra < 0:
        ra += 2.0 * math.pi
    dec = math.atan2(
        float(v[2]),
        math.hypot(float(v[0]), float(v[1])),
    )

    return SkyCoord(
        ra=ra * u.rad,
        dec=dec * u.rad,
        frame="icrs",
    )


def robust_sigma(vals):
    a = np.asarray(list(vals), dtype=float)
    if len(a) == 0:
        return None
    med = float(np.median(a))
    mad = float(np.median(np.abs(a - med)))
    return 1.4826 * mad


def percentile95(vals):
    a = np.asarray(list(vals), dtype=float)
    if len(a) == 0:
        return None
    # Conservative empirical nearest-rank percentile, no interpolation.
    a = np.sort(a)
    idx = int(math.ceil(0.95 * len(a))) - 1
    idx = min(max(idx, 0), len(a) - 1)
    return float(a[idx])


def gaia_adql(ra, dec, radius_arcsec, hpm_only=False):
    radius_deg = radius_arcsec / 3600.0
    cols = ", ".join(GAIA_COLUMNS)
    where_pm = f"pm > {HPM_RESCUE_MIN_MASYR:.6f} AND " if hpm_only else ""
    top = MAX_HPM_ROWS if hpm_only else MAX_CONE_ROWS
    return (
        f"SELECT TOP {top} {cols} FROM gaiadr3.gaia_source WHERE "
        f"{where_pm}1 = CONTAINS(POINT('ICRS', ra, dec), "
        f"CIRCLE('ICRS', {ra:.12f}, {dec:.12f}, {radius_deg:.12f}))"
    )


def parse_gaia_csv(b: bytes):
    text = b.decode("utf-8-sig", errors="strict")
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
            "ra": ffloat(r.get("ra")),
            "dec": ffloat(r.get("dec")),
            "ref_epoch": ffloat(r.get("ref_epoch")),
            "ra_error": ffloat(r.get("ra_error")),
            "dec_error": ffloat(r.get("dec_error")),
            "parallax": ffloat(r.get("parallax")),
            "parallax_error": ffloat(r.get("parallax_error")),
            "pm": ffloat(r.get("pm")),
            "pmra": ffloat(r.get("pmra")),
            "pmdec": ffloat(r.get("pmdec")),
            "pmra_error": ffloat(r.get("pmra_error")),
            "pmdec_error": ffloat(r.get("pmdec_error")),
            "radial_velocity": ffloat(r.get("radial_velocity")),
            "phot_g_mean_mag": ffloat(r.get("phot_g_mean_mag")),
            "bp_rp": ffloat(r.get("bp_rp")),
            "ruwe": ffloat(r.get("ruwe")),
            "astrometric_params_solved": fint(r.get("astrometric_params_solved")),
        })
    return out


def tap_query(adql, stem):
    csv_path = CACHE / f"{stem}.csv"
    meta_path = CACHE / f"{stem}.json"

    if csv_path.is_file() and meta_path.is_file():
        b = csv_path.read_bytes()
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        if (
            meta.get("complete") is True
            and meta.get("adql") == adql
            and meta.get("sha256") == sha256_bytes(b)
        ):
            return parse_gaia_csv(b), "cached"

    curl = shutil.which("curl.exe") or shutil.which("curl")
    if not curl:
        raise RuntimeError("curl.exe/curl unavailable; TLS will not be weakened")

    part = csv_path.with_suffix(".csv.part")
    errors = []

    for attempt in range(1, MAX_ATTEMPTS + 1):
        if part.exists():
            part.unlink()

        cmd = [
            curl,
            "--fail", "--silent", "--show-error", "--location",
            "--connect-timeout", "30", "--max-time", "180",
            "--user-agent", UA,
            "--data-urlencode", "REQUEST=doQuery",
            "--data-urlencode", "LANG=ADQL",
            "--data-urlencode", "FORMAT=csv",
            "--data-urlencode", f"QUERY={adql}",
            "--output", str(part),
            TAP,
        ]

        try:
            cp = subprocess.run(
                cmd, capture_output=True, text=True,
                timeout=210, check=False,
            )
            if cp.returncode != 0:
                err = (cp.stderr or cp.stdout or "").strip()
                raise RuntimeError(f"curl exit {cp.returncode}: {err[:600]}")
            if not part.is_file():
                raise RuntimeError("curl success without response file")

            b = part.read_bytes()
            rows = parse_gaia_csv(b)
            part.replace(csv_path)
            write_json(meta_path, {
                "complete": True,
                "adql": adql,
                "sha256": sha256_bytes(b),
                "bytes": len(b),
                "rows": len(rows),
                "transport": "curl_verified_https",
                "tls_verification_disabled": False,
            })
            return rows, "done"

        except (RuntimeError, OSError, subprocess.TimeoutExpired, UnicodeError) as exc:
            errors.append(repr(exc))
            print(f"    {stem} attempt {attempt}/{MAX_ATTEMPTS} FAILED: {exc}", flush=True)
            if part.exists():
                try:
                    part.unlink()
                except OSError:
                    pass
            if attempt < MAX_ATTEMPTS:
                time.sleep(2 ** attempt)

    raise RuntimeError(f"Gaia TAP failed for {stem}: {errors[-1]}")


def propagate_source(src, target: Time):
    if src["ra"] is None or src["dec"] is None:
        return None

    can_pm = (
        src["pmra"] is not None
        and src["pmdec"] is not None
        and src["ref_epoch"] is not None
    )

    if not can_pm:
        c = SkyCoord(src["ra"] * u.deg, src["dec"] * u.deg, frame="icrs")
        return c, False, None

    kwargs = dict(
        ra=src["ra"] * u.deg,
        dec=src["dec"] * u.deg,
        pm_ra_cosdec=src["pmra"] * u.mas / u.yr,
        pm_dec=src["pmdec"] * u.mas / u.yr,
        obstime=Time(float(src["ref_epoch"]), format="jyear", scale="tcb"),
        frame="icrs",
    )

    # Match the earlier conservative Gaia stage: include perspective terms
    # when a physically usable distance/RV pair is available, otherwise use
    # proper motion alone.
    if (
        src["parallax"] is not None and src["parallax"] > 0
        and src["radial_velocity"] is not None
    ):
        try:
            kwargs["distance"] = Distance(parallax=src["parallax"] * u.mas)
            kwargs["radial_velocity"] = src["radial_velocity"] * u.km / u.s
        except Exception:
            pass

    try:
        c0 = SkyCoord(**kwargs)
        c = c0.apply_space_motion(new_obstime=target)
    except Exception:
        # Fail conservative: do not silently discard the source. If full
        # perspective propagation fails, retry proper-motion-only.
        kwargs.pop("distance", None)
        kwargs.pop("radial_velocity", None)
        c0 = SkyCoord(**kwargs)
        c = c0.apply_space_motion(new_obstime=target)

    approx_sigma = None
    if src["pmra_error"] is not None and src["pmdec_error"] is not None:
        dt = abs(float(target.utc.jyear) - float(src["ref_epoch"]))
        approx_sigma = (
            math.hypot(src["pmra_error"], src["pmdec_error"]) * dt / 1000.0
        )

    return c.icrs, True, approx_sigma


def raw_row(r):
    return {
        "match_index": int(r["match_index"]),
        "separation_arcsec": float(r["separation_arcsec"]),
        "poss_tile_id": r["poss_tile_id"],
        "poss_candidate_index": int(r["poss_candidate_index"]),
        "poss_ra_deg": float(r["poss_ra_deg"]),
        "poss_dec_deg": float(r["poss_dec_deg"]),
        "poss_snr": float(r["poss_snr"]),
        "poss_polarity": int(r["poss_polarity"]),
        "dasch_tile_id": r["dasch_tile_id"],
        "dasch_candidate_index": int(r["dasch_candidate_index"]),
        "dasch_ra_deg": float(r["dasch_ra_deg"]),
        "dasch_dec_deg": float(r["dasch_dec_deg"]),
        "dasch_snr": float(r["dasch_snr"]),
        "dasch_polarity": int(r["dasch_polarity"]),
    }


def pair_coords(r):
    p = SkyCoord(r["poss_ra_deg"] * u.deg, r["poss_dec_deg"] * u.deg, frame="icrs")
    d = SkyCoord(r["dasch_ra_deg"] * u.deg, r["dasch_dec_deg"] * u.deg, frame="icrs")
    return p, d, midpoint_coord(p, d)


def pair_offset(r):
    p, d, _ = pair_coords(r)
    east, north = p.spherical_offsets_to(d)
    return float(east.arcsec), float(north.arcsec)


def gaia_reference_for_raw(r, target):
    p, d, mid = pair_coords(r)
    stem = f"raw_{r['match_index']:04d}"

    cone, cstat = tap_query(
        gaia_adql(float(mid.ra.deg), float(mid.dec.deg), GAIA_CONE_ARCSEC, False),
        stem + "_cone120",
    )
    hpm, hstat = tap_query(
        gaia_adql(float(mid.ra.deg), float(mid.dec.deg), HPM_RESCUE_CONE_ARCSEC, True),
        stem + "_hpm900",
    )

    if len(cone) >= MAX_CONE_ROWS:
        raise RuntimeError(f"{stem}: cone query hit TOP limit")
    if len(hpm) >= MAX_HPM_ROWS:
        raise RuntimeError(f"{stem}: HPM query hit TOP limit")

    merged = {}
    origins = {}
    for s in cone:
        merged[s["source_id"]] = s
        origins.setdefault(s["source_id"], set()).add("cone120")
    for s in hpm:
        merged.setdefault(s["source_id"], s)
        origins.setdefault(s["source_id"], set()).add("hpm900")

    candidates = []
    for sid, src in merged.items():
        prop = propagate_source(src, target)
        if prop is None:
            continue
        c, did_prop, approx_sigma = prop
        sp = float(c.separation(p).arcsec)
        sd = float(c.separation(d).arcsec)

        # HPM-only sources are only relevant if they actually approach this pair.
        if "cone120" not in origins[sid] and min(sp, sd) > 30.0:
            continue

        candidates.append({
            "source_id": sid,
            "g_mag": src["phot_g_mean_mag"],
            "pm_masyr": src["pm"],
            "ruwe": src["ruwe"],
            "propagated": did_prop,
            "ra_target_deg": float(c.ra.deg),
            "dec_target_deg": float(c.dec.deg),
            "sep_poss_arcsec": sp,
            "sep_dasch_arcsec": sd,
            "max_endpoint_sep_arcsec": max(sp, sd),
            "approx_pm_sigma_arcsec": approx_sigma,
        })

    if not candidates:
        return None, cstat, hstat

    candidates.sort(key=lambda q: (
        q["max_endpoint_sep_arcsec"],
        max(q["sep_poss_arcsec"], q["sep_dasch_arcsec"]),
        q["source_id"],
    ))
    best = candidates[0]

    if best["max_endpoint_sep_arcsec"] > GAIA_BOTH_ENDPOINT_ARCSEC:
        return None, cstat, hstat

    return best, cstat, hstat


def dedupe_refs(refs):
    """Deterministically enforce unique Gaia source and unique endpoints."""
    ordered = sorted(
        refs,
        key=lambda q: (
            q["gaia_max_endpoint_sep_arcsec"],
            q["raw_pair_separation_arcsec"],
            q["raw_match_index"],
        ),
    )
    kept = []
    used_gaia = set()
    used_p = set()
    used_d = set()

    for r in ordered:
        g = r["gaia_source_id"]
        pk = (r["poss_tile_id"], int(r["poss_candidate_index"]))
        dk = (r["dasch_tile_id"], int(r["dasch_candidate_index"]))
        if g in used_gaia or pk in used_p or dk in used_d:
            r["dedupe_kept"] = False
            continue
        r["dedupe_kept"] = True
        kept.append(r)
        used_gaia.add(g)
        used_p.add(pk)
        used_d.add(dk)

    return kept


def loo_residuals(refs):
    if len(refs) < 3:
        return []
    out = []
    for i, r in enumerate(refs):
        others = refs[:i] + refs[i+1:]
        me = float(np.median([q["east_offset_arcsec"] for q in others]))
        mn = float(np.median([q["north_offset_arcsec"] for q in others]))
        out.append(math.hypot(
            r["east_offset_arcsec"] - me,
            r["north_offset_arcsec"] - mn,
        ))
    return out


def main():
    print("=" * 100)
    print("ORDER 61 — LOCAL GAIA-ANCHORED ASTROMETRIC / PLATE-SYSTEMATICS ADJUDICATION v028b")
    print("=" * 100)
    print(
        "Translation-only local model; same-Gaia-source references within 3\" of BOTH endpoints; "
        "no detector/image pixels."
    )
    print(
        "Implementation amendment: spherical midpoint representation fixed after v028 "
        "failed before the first Gaia-reference query; scientific policy unchanged."
    )
    print()

    required = [
        PAIR_REPORT, STAGE3_REPORT, STAGE3_POLICY,
        RAW, STRICT, GAIA_TRIAGE, PREFLIGHT,
    ]
    for p in required:
        if not p.is_file():
            raise RuntimeError(f"Missing required input: {p}")

    pair_report = json.loads(PAIR_REPORT.read_text(encoding="utf-8"))
    stage3 = json.loads(STAGE3_REPORT.read_text(encoding="utf-8"))
    stage3_policy = json.loads(STAGE3_POLICY.read_text(encoding="utf-8"))
    preflight = json.loads(PREFLIGHT.read_text(encoding="utf-8"))

    s3 = {
        int(r["strict_rank"]): r
        for r in stage3.get("active_rank_summaries_cumulative_1024", [])
    }

    guards = {
        "pair_complete": pair_report.get("status") == "COMPLETE",
        "order": int(pair_report.get("canonical_order", -1)) == 61,
        "detector": pair_report.get("detector_sha256") == EXPECTED_DETECTOR_SHA,
        "method": pair_report.get("method_sha256") == EXPECTED_METHOD_SHA,
        "policy": pair_report.get("policy_sha256") == EXPECTED_POLICY_SHA,
        "stage3_complete": stage3.get("status") == "COMPLETE",
        "stage3_policy_hash": sha256_file(STAGE3_POLICY) == EXPECTED_STAGE3_POLICY_SHA,
        "stage3_active": sorted(s3) == ACTIVE_RANKS,
        "stage3_1024": all(int(s3[r]["cumulative_completed_plates"]) == 1024 for r in ACTIVE_RANKS),
        "stage3_zero5": all(int(s3[r]["observed_sources_within_5arcsec"]) == 0 for r in ACTIVE_RANKS),
        "preflight_complete": preflight.get("status") == "COMPLETE",
        "preflight_no_detector": preflight.get("detector_rerun") is False,
        "preflight_no_pixels": preflight.get("image_pixels_read") is False,
        "same_stage3_spatial_gates": (
            float(stage3_policy.get("strong_arcsec")) == 3.0
            and float(stage3_policy.get("diagnostic_arcsec")) == 5.0
        ),
    }
    if not all(guards.values()):
        raise RuntimeError("REFUSING: guard failure: " + json.dumps(guards, sort_keys=True))

    raw = [raw_row(r) for r in read_csv(RAW)]
    strict_rows = read_csv(STRICT)
    gaia_rows = read_csv(GAIA_TRIAGE)

    if len(raw) != 235 or len(strict_rows) != 23 or len(gaia_rows) != 23:
        raise RuntimeError(
            f"REFUSING: row counts changed raw={len(raw)} strict={len(strict_rows)} gaia={len(gaia_rows)}"
        )

    strict_by_rank = {int(r["strict_rank"]): r for r in strict_rows}
    if any(r not in strict_by_rank for r in ACTIVE_RANKS):
        raise RuntimeError("Missing active strict-rank row")

    target = target_epoch(pair_report)

    print("Completed-stage guards: PASS")
    print("Target epoch:", target.utc.isot)
    print(
        "Fixed local-reference policy: radii="
        + "/".join(f"{int(r)}'" for r in REFERENCE_RADII_ARCMIN)
        + f"; choose smallest with >= {MIN_LOCAL_REFS} unique Gaia-both references"
    )
    print("Primary model: median POSS->DASCH translation only")
    print()

    survivor_mid = {}
    survivor_raw_keys = set()
    for rank in ACTIVE_RANKS:
        sr = strict_by_rank[rank]
        p = SkyCoord(float(sr["poss_ra_deg"]) * u.deg, float(sr["poss_dec_deg"]) * u.deg)
        d = SkyCoord(float(sr["dasch_ra_deg"]) * u.deg, float(sr["dasch_dec_deg"]) * u.deg)
        survivor_mid[rank] = midpoint_coord(p, d)
        survivor_raw_keys.add((
            sr["poss_tile_id"], int(sr["poss_candidate_index"]),
            sr["dasch_tile_id"], int(sr["dasch_candidate_index"]),
        ))

    # Query only raw associations that lie within 30' of at least one survivor.
    needed = []
    membership = {}
    for r in raw:
        _, _, mid = pair_coords(r)
        near = {}
        for rank in ACTIVE_RANKS:
            sepmin = float(mid.separation(survivor_mid[rank]).arcmin)
            near[rank] = sepmin
        if min(near.values()) <= max(REFERENCE_RADII_ARCMIN):
            key = (
                r["poss_tile_id"], r["poss_candidate_index"],
                r["dasch_tile_id"], r["dasch_candidate_index"],
            )
            if key in survivor_raw_keys:
                # Never use the candidates under adjudication as references.
                continue
            needed.append(r)
            membership[r["match_index"]] = near

    print(f"Raw <=10\" associations requiring Gaia local-reference test: {len(needed)}")
    print()

    base_refs = []
    for i, r in enumerate(sorted(needed, key=lambda q: q["match_index"]), 1):
        best, cstat, hstat = gaia_reference_for_raw(r, target)
        if best is None:
            print(
                f"  [{i:03d}/{len(needed)}] raw #{r['match_index']:03d} "
                f"Gaia-both<=3\": NO",
                flush=True,
            )
            continue

        east, north = pair_offset(r)
        base = {
            "raw_match_index": r["match_index"],
            "raw_pair_separation_arcsec": r["separation_arcsec"],
            "poss_tile_id": r["poss_tile_id"],
            "poss_candidate_index": r["poss_candidate_index"],
            "dasch_tile_id": r["dasch_tile_id"],
            "dasch_candidate_index": r["dasch_candidate_index"],
            "poss_ra_deg": r["poss_ra_deg"],
            "poss_dec_deg": r["poss_dec_deg"],
            "dasch_ra_deg": r["dasch_ra_deg"],
            "dasch_dec_deg": r["dasch_dec_deg"],
            "east_offset_arcsec": east,
            "north_offset_arcsec": north,
            "gaia_source_id": best["source_id"],
            "gaia_g_mag": best["g_mag"],
            "gaia_propagated": best["propagated"],
            "gaia_ra_target_deg": best["ra_target_deg"],
            "gaia_dec_target_deg": best["dec_target_deg"],
            "gaia_sep_poss_arcsec": best["sep_poss_arcsec"],
            "gaia_sep_dasch_arcsec": best["sep_dasch_arcsec"],
            "gaia_max_endpoint_sep_arcsec": best["max_endpoint_sep_arcsec"],
            "gaia_pm_masyr": best["pm_masyr"],
            "gaia_ruwe": best["ruwe"],
            "gaia_approx_pm_sigma_arcsec": best["approx_pm_sigma_arcsec"],
        }
        base_refs.append(base)
        print(
            f"  [{i:03d}/{len(needed)}] raw #{r['match_index']:03d} "
            f"Gaia-both<=3\": YES source={best['source_id']} "
            f"maxsep={best['max_endpoint_sep_arcsec']:.2f}\"",
            flush=True,
        )

    print()
    print(f"Gaia-both raw reference candidates before dedupe: {len(base_refs)}")
    print()

    ref_audit = []
    summary_rows = []
    report_survivors = {}

    for rank in ACTIVE_RANKS:
        per_radius = {}
        per_radius_all = {}

        for radius in REFERENCE_RADII_ARCMIN:
            q = []
            for b in base_refs:
                rr = dict(b)
                sepmin = membership[b["raw_match_index"]][rank]
                if sepmin <= radius:
                    rr["survivor_rank"] = rank
                    rr["window_arcmin"] = radius
                    rr["raw_pair_midpoint_sep_from_survivor_arcmin"] = sepmin
                    q.append(rr)
            per_radius_all[radius] = q
            per_radius[radius] = dedupe_refs(q)

        counts = {r: len(per_radius[r]) for r in REFERENCE_RADII_ARCMIN}
        selected_radius = next(
            (r for r in REFERENCE_RADII_ARCMIN if counts[r] >= MIN_LOCAL_REFS),
            None,
        )

        sr = strict_by_rank[rank]
        ce = float(sr["east_offset_arcsec"])
        cn = float(sr["north_offset_arcsec"])
        craw = float(sr["separation_arcsec"])

        if selected_radius is None:
            row = {
                "strict_rank": rank,
                "status": "INSUFFICIENT_LOCAL_REFERENCES",
                "selected_radius_arcmin": None,
                "reference_count": counts[max(REFERENCE_RADII_ARCMIN)],
                "candidate_raw_separation_arcsec": craw,
                "candidate_raw_east_arcsec": ce,
                "candidate_raw_north_arcsec": cn,
                "refs_5arcmin": counts[5.0],
                "refs_10arcmin": counts[10.0],
                "refs_20arcmin": counts[20.0],
                "refs_30arcmin": counts[30.0],
            }
            summary_rows.append(row)
            report_survivors[str(rank)] = row
            print(
                f"strict #{rank:02d}: refs 5/10/20/30' = "
                f"{counts[5.0]}/{counts[10.0]}/{counts[20.0]}/{counts[30.0]} "
                "=> INSUFFICIENT_LOCAL_REFERENCES"
            )
            continue

        refs = per_radius[selected_radius]
        for rr in per_radius_all[selected_radius]:
            rr["selected_window"] = True
            ref_audit.append(rr)

        med_e = float(np.median([r["east_offset_arcsec"] for r in refs]))
        med_n = float(np.median([r["north_offset_arcsec"] for r in refs]))
        sig_e = robust_sigma(r["east_offset_arcsec"] for r in refs)
        sig_n = robust_sigma(r["north_offset_arcsec"] for r in refs)

        corr_e = ce - med_e
        corr_n = cn - med_n
        corr_r = math.hypot(corr_e, corr_n)

        loo = loo_residuals(refs)
        loo_med = float(np.median(loo)) if loo else None
        loo_p95 = percentile95(loo)
        # Finite-sample upper-tail empirical p. Includes +1 correction.
        upper_p = (
            (1 + sum(x >= corr_r for x in loo)) / (len(loo) + 1)
            if loo else None
        )
        within_p95 = None if loo_p95 is None else corr_r <= loo_p95

        row = {
            "strict_rank": rank,
            "status": "LOCAL_TRANSLATION_MODEL_COMPLETE",
            "selected_radius_arcmin": selected_radius,
            "reference_count": len(refs),
            "candidate_raw_separation_arcsec": craw,
            "candidate_raw_east_arcsec": ce,
            "candidate_raw_north_arcsec": cn,
            "local_median_east_arcsec": med_e,
            "local_median_north_arcsec": med_n,
            "local_robust_sigma_east_arcsec": sig_e,
            "local_robust_sigma_north_arcsec": sig_n,
            "candidate_corrected_east_arcsec": corr_e,
            "candidate_corrected_north_arcsec": corr_n,
            "candidate_corrected_separation_arcsec": corr_r,
            "loo_reference_residual_median_arcsec": loo_med,
            "loo_reference_residual_p95_arcsec": loo_p95,
            "candidate_upper_tail_empirical_p": upper_p,
            "candidate_within_reference_p95": within_p95,
            "refs_5arcmin": counts[5.0],
            "refs_10arcmin": counts[10.0],
            "refs_20arcmin": counts[20.0],
            "refs_30arcmin": counts[30.0],
        }
        summary_rows.append(row)
        report_survivors[str(rank)] = row

        print(
            f"strict #{rank:02d}: refs 5/10/20/30'="
            f"{counts[5.0]}/{counts[10.0]}/{counts[20.0]}/{counts[30.0]} "
            f"selected={selected_radius:.0f}' n={len(refs)}"
        )
        print(
            f"  local translation east={med_e:+.3f}\" north={med_n:+.3f}\"; "
            f"raw candidate={craw:.3f}\" -> corrected={corr_r:.3f}\""
        )
        print(
            f"  LOO reference residual median={loo_med:.3f}\" p95={loo_p95:.3f}\"; "
            f"candidate upper-tail empirical p={upper_p:.4f}"
        )

    write_csv(OUT_REFS, ref_audit, REF_FIELDS)
    write_csv(OUT_SUMMARY, summary_rows, SUMMARY_FIELDS)

    out_report = {
        "status": "COMPLETE",
        "analysis_kind": "order61_local_gaia_anchored_astrometry_v028",
        "guards": guards,
        "implementation_amendment": {
            "prior_worker": "run_order61_local_astrometry_v028.py",
            "failure_stage": "before_first_gaia_reference_query",
            "prior_gaia_reference_outcomes_produced": False,
            "change": (
                "midpoint_coord now returns explicit spherical ICRS SkyCoord "
                "instead of Cartesian-representation SkyCoord"
            ),
            "midpoint_mathematics_changed": False,
            "scientific_policy_changed": False,
        },
        "fixed_policy": {
            "active_ranks": ACTIVE_RANKS,
            "reference_windows_arcmin": REFERENCE_RADII_ARCMIN,
            "minimum_unique_local_references": MIN_LOCAL_REFS,
            "reference_definition": (
                "raw <=10-arcsec POSS-DASCH association independently matched "
                "to the same Gaia DR3 source propagated to the 1953 target epoch, "
                "with Gaia <=3 arcsec from BOTH endpoints"
            ),
            "candidate_rows_excluded_from_reference_pool": True,
            "dedupe": (
                "unique Gaia source_id and unique POSS/DASCH endpoint; greedily "
                "retain lowest Gaia max-endpoint separation, then raw pair separation"
            ),
            "window_choice": (
                "smallest of 5/10/20/30 arcmin with >=5 deduplicated references; "
                "otherwise report insufficient local references"
            ),
            "primary_model": "translation_only_median_poss_to_dasch_offset",
            "reference_scatter": "leave-one-out residual radius",
            "candidate_gate_changed": False,
            "recurrence_3_5_arcsec_gates_changed": False,
            "affine_or_higher_order_fit_used": False,
        },
        "gaia": {
            "release": "DR3",
            "table": "gaiadr3.gaia_source",
            "tap": TAP,
            "ordinary_cone_arcsec": GAIA_CONE_ARCSEC,
            "hpm_rescue_cone_arcsec": HPM_RESCUE_CONE_ARCSEC,
            "hpm_rescue_min_masyr": HPM_RESCUE_MIN_MASYR,
            "transport": "curl_verified_https",
            "tls_verification_disabled": False,
            "target_epoch_iso": target.utc.isot,
        },
        "raw_local_associations_queried": len(needed),
        "gaia_both_reference_candidates_before_dedupe": len(base_refs),
        "survivors": report_survivors,
        "detector_rerun": False,
        "image_pixels_read": False,
        "science_candidate_deleted": False,
        "outputs": {
            "reference_audit_csv": str(OUT_REFS),
            "summary_csv": str(OUT_SUMMARY),
        },
        "next_stage": (
            "Interpret local corrected offsets and empirical reference scatter. "
            "Then inspect native discovery cutouts/PSF neighbourhoods for ranks "
            "11/14/20 that remain astrometrically consistent; no detector retuning."
        ),
    }
    write_json(OUT_REPORT, out_report)

    print()
    print("=" * 100)
    print("LOCAL GAIA-ANCHORED ASTROMETRIC ADJUDICATION COMPLETE")
    print("=" * 100)
    print("Outputs:")
    print(" ", OUT_REPORT)
    print(" ", OUT_SUMMARY)
    print(" ", OUT_REFS)
    print()
    print("No detector was rerun.")
    print("No image pixel was read.")
    print("No science candidate was deleted.")


if __name__ == "__main__":
    main()
