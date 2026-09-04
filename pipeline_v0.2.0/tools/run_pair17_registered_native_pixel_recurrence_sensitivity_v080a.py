#!/usr/bin/env python3
"""
Pair-17 v080 — registered native-pixel recurrence + sensitivity.

Outcome-bearing scientific stage. The scientific rules are frozen in the
v080 contract before execution.

Main phases:
  1. Verify frozen inputs and reconstruct registered target coordinates.
  2. Acquire/cache all Gaia DR3 local reference cones for all 23 candidates.
     No comparison pixels are read until all 23 reference acquisitions pass.
  3. Process all 129 frozen candidate x comparison-plate rows:
       - target-independent local Gaia registration
       - frozen-detector native-pixel recurrence
       - forced target residual
       - frozen injection/recovery where prospectively applicable
  4. Aggregate prospectively frozen mechanical evidence states.

Formal candidate dispositions are NOT mutated in v080.
"""

from pathlib import Path
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict
from io import BytesIO
import csv
import hashlib
import importlib.util
import inspect
import json
import math
import os
import re
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

import numpy as np
from astropy.coordinates import SkyCoord
from astropy.io import fits
from astropy.table import Table
from astropy.time import Time
from astropy.wcs import WCS
import astropy.units as u
from scipy.ndimage import gaussian_filter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

CONTRACT = (
    ROOT / "research" / "prospective_freezes"
    / "pair17_registered_native_pixel_recurrence_sensitivity_contract_v080.json"
)
EXPECTED_CONTRACT_SHA = "732c0822003abf3217d713437f1b9c47a86f7b8fa42d171498f3453e78787ac7"
ORIGINAL_V080_RUNNER_SHA = "c48f17a02a7798a7a47e3ac8b92d5fd1b22f6c5e07ab7fd7cb79931da5df3f10"

POLICY = ROOT / "tools" / "candidate_adjudication_policy_v002.json"

V068A = (
    ROOT / "results" / "wide_census_gaia_registration_v068a"
    / "pair_17_registrations_v068a.csv"
)
V075 = (
    ROOT / "results" / "pair17_epoch_aware_gaia_static_triage_v075"
    / "pair17_epoch_aware_gaia_static_triage_v075.csv"
)
V078 = ROOT / "results" / "pair17_applause_catalog_recurrence_screen_v078"
V078_SUMMARY = V078 / "pair17_catalog_recurrence_candidate_summary_v078.csv"
V078_QUEUE = V078 / "pair17_pixel_followup_queue_v078.csv"

V079 = ROOT / "results" / "pair17_pixel_followup_scan_plan_and_acquisition_v079"
V079_PLAN = V079 / "pair17_candidate_comparison_plan_v079.csv"
V079_ACQ = V079 / "pair17_scan_acquisition_manifest_v079.csv"
V079_REPORT = V079 / "pair17_pixel_followup_scan_plan_and_acquisition_v079.json"
V079_BANK = V079 / "pair17_v079b_bank_manifest.json"

PREFLIGHT_SCRIPT = ROOT / "tools" / "preflight_pair17_native_pixel_v080.py"
PREFLIGHT_REPORT = (
    ROOT / "results" / "pair17_native_pixel_preflight_v080"
    / "pair17_native_pixel_preflight_v080.json"
)

INJ_IMPL = ROOT / "tools" / "run_order01_injection_recovery_v028.py"

EXPECTED_SHA = {
    POLICY:
        "eb8512724b2ef23b3ee88e5ffcfab8088144c984f0b75adb7b68e87198cb4cbd",
    V068A:
        "ebbe6ff5513681a3b98a2f4deda1d4b5c7f563ca284dd399e631237cdae4b7a1",
    V075:
        "cc571a4da103dc3900907fe9568567dd540f8f85217b7e7e73ca4442239f2097",
    V078_SUMMARY:
        "4294aa5cb8e7c4138e0a5683945c4d8eaad56aed5ca133c4f7d2ddb71d155ee5",
    V078_QUEUE:
        "3be9c4049f40e9d9af43decfa9036ce186c0d6b22250ea274908e5299e461879",
    V079_PLAN:
        "9794ee6dc3eebd91281a46af25f0025da86492dde2aeb0e44f04ae3292a3d356",
    V079_ACQ:
        "392e73303d01f20a386627e8a743c4a6769e31deb5a4a9a22f7a81055c809f7a",
    V079_REPORT:
        "a6695398285882ef13e8f67cf04955fb4b6c6b2f8fd7cf58f0580ad18aec635d",
    V079_BANK:
        "d3bd17cb6c9da62feb17d10bd8f7b86789ee11b63acc8d131407ba0b785e1e42",
    PREFLIGHT_SCRIPT:
        "2868a91e18ce65cbc20070a3a5d48b7526ea3cc377fd12d70f4b38bff2efa298",
    PREFLIGHT_REPORT:
        "ba4de5aaa87b5eba016e3eca638ea4923da0c7b44cb14241ada59eae30544b9b",
    INJ_IMPL:
        "7149ab75f320fdf2aea167a2126565fea3c2be4433393b353ada79c138e2d483",
}

OUT = ROOT / "results" / "pair17_registered_native_pixel_recurrence_sensitivity_v080"
CACHE = OUT / "cache"
GAIA_CACHE = CACHE / "gaia"
CHECKPOINTS = OUT / "checkpoints"

OUT_TARGETS = OUT / "pair17_registered_target_coordinates_v080.csv"
OUT_GAIA = OUT / "pair17_gaia_reference_query_manifest_v080.csv"
OUT_PLATES = OUT / "pair17_native_pixel_plate_measurements_v080.csv"
OUT_INJ = OUT / "pair17_native_pixel_injection_summary_v080.csv"
OUT_CAND = OUT / "pair17_native_pixel_candidate_summary_v080.csv"
OUT_FAIL = OUT / "pair17_native_pixel_operational_failures_v080.csv"
OUT_JSON = OUT / "pair17_registered_native_pixel_recurrence_sensitivity_v080.json"

GAIA_TAP = "https://gea.esac.esa.int/tap-server/tap/sync"
GAIA_RADIUS_DEG = 30.5 / 60.0
GAIA_G_MAX = 19.5
GAIA_MAXREC = 50000
GAIA_ATTEMPTS = 5
UA = "historical-transient-pipeline/pair17-v080-native-pixel"

MATCH_ARCSEC = 15.0
TARGET_EXCLUSION_ARCSEC = 30.0
REG_WINDOWS_ARCMIN = [5.0, 10.0, 20.0, 30.0]
REG_PRIMARY_MIN = 5
REG_SPARSE_MIN = 3
STRICT_ARCSEC = 3.0
DIAG_ARCSEC = 5.0
REG_FIELD_ARCMIN = 30.5

PIXEL_WORKERS = 2
INJECTION_TILE_SIZE = 1024
CHUNK = 8 * 1024 * 1024

print_lock = threading.Lock()


def say(*args):
    with print_lock:
        print(*args, flush=True)


def fail(msg):
    raise RuntimeError(msg)


def sha256(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as fh:
        for block in iter(lambda: fh.read(CHUNK), b""):
            h.update(block)
    return h.hexdigest()


def read_csv(path):
    with Path(path).open("r", encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def atomic_json(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(obj, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )
    tmp.replace(path)


def atomic_csv(path, rows, fields=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    if fields is None:
        fields = list(rows[0].keys()) if rows else []
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        if fields:
            w.writeheader()
            w.writerows(rows)
    tmp.replace(path)


def fnum(v):
    try:
        x = float(str(v).strip())
        return x if math.isfinite(x) else None
    except Exception:
        return None


def inum(v):
    x = fnum(v)
    return None if x is None else int(x)


def truth(v):
    return str(v).strip().lower() in {"1", "true", "yes", "y"}


def unit_midpoint(c1, c2):
    a = np.array(c1.cartesian.xyz.value, dtype=float)
    b = np.array(c2.cartesian.xyz.value, dtype=float)
    v = a + b
    n = float(np.linalg.norm(v))
    if not math.isfinite(n) or n <= 1e-12:
        fail("Degenerate registered endpoint midpoint")
    v /= n
    ra = math.degrees(math.atan2(v[1], v[0])) % 360.0
    dec = math.degrees(math.asin(max(-1.0, min(1.0, v[2]))))
    return SkyCoord(ra * u.deg, dec * u.deg, frame="icrs")


def corrected_endpoint(ra, dec, shift_east_arcsec, shift_north_arcsec):
    c = SkyCoord(float(ra) * u.deg, float(dec) * u.deg, frame="icrs")
    return c.spherical_offsets_by(
        -float(shift_east_arcsec) * u.arcsec,
        -float(shift_north_arcsec) * u.arcsec,
    )


def load_order01_injection():
    if sha256(INJ_IMPL) != EXPECTED_SHA[INJ_IMPL]:
        fail("Order-01 injection implementation SHA changed")

    spec = importlib.util.spec_from_file_location("order01_inj_v028", INJ_IMPL)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    required = [
        "load_frozen_detector",
        "PSF_SIGMAS_PX",
        "TARGET_DETECTOR_SNRS",
        "INJECTION_POLARITIES",
        "N_INJECTION_POSITIONS",
        "INJECTION_MATCH_RADIUS_PX",
        "BASELINE_EXCLUSION_RADIUS_PX",
        "LOCAL_OFFSETS_PX",
        "FALLBACK_STEP_PX",
        "STAMP_RADIUS_PX",
        "EXPECTED_DETECTOR_EDGE_PX",
        "RECOVERY_LEVELS",
        "gaussian_stamp",
        "template_residual_response",
        "quantized_injected_image",
        "match_recovery",
        "first_recovery_target",
    ]

    missing = [name for name in required if not hasattr(mod, name)]
    if missing:
        fail(f"Order-01 injection implementation missing {missing}")

    # Contract equivalence guard.
    if list(map(float, mod.PSF_SIGMAS_PX)) != [1.0, 2.0, 3.0]:
        fail("Frozen injection PSF grid changed")
    if list(map(float, mod.TARGET_DETECTOR_SNRS)) != [3.5,4.0,4.5,5.0,6.0,8.0,10.0,12.0]:
        fail("Frozen injection SNR grid changed")
    if list(map(int, mod.INJECTION_POLARITIES)) != [-1, 1]:
        fail("Frozen injection polarity grid changed")
    if int(mod.N_INJECTION_POSITIONS) != 24:
        fail("Frozen injection position count changed")

    detect_array, method = mod.load_frozen_detector()
    if float(method.peak_sigma) != 4.0:
        fail(f"Frozen detector peak_sigma changed: {method.peak_sigma}")
    if int(method.edge_px) != 30:
        fail(f"Frozen detector edge_px changed: {method.edge_px}")

    return mod, detect_array, method


def build_registered_targets():
    triage_rows = read_csv(V075)
    reg_rows = read_csv(V068A)
    v078_rows = read_csv(V078_SUMMARY)
    follow_rows = read_csv(V078_QUEUE)

    triage = {str(r["raw_match_row"]): r for r in triage_rows}
    reg = {str(r["raw_match_row"]): r for r in reg_rows}
    v078 = {str(r["raw_match_row"]): r for r in v078_rows}

    follow_ids = [str(r["raw_match_row"]) for r in follow_rows]

    if len(follow_ids) != 23 or len(set(follow_ids)) != 23:
        fail("Frozen v078 follow-up population is not exactly 23 unique candidates")

    out = []
    target_map = {}

    for rid in follow_ids:
        if rid not in triage or rid not in reg or rid not in v078:
            fail(f"Missing target-coordinate input for raw_match_row={rid}")

        t = triage[rid]
        rr = reg[rid]
        vr = v078[rid]

        vals = [
            t.get("a_ra_deg"), t.get("a_dec_deg"),
            t.get("b_ra_deg"), t.get("b_dec_deg"),
            rr.get("shift_a_east_arcsec"), rr.get("shift_a_north_arcsec"),
            rr.get("shift_b_east_arcsec"), rr.get("shift_b_north_arcsec"),
            rr.get("corrected_separation_arcsec"),
            t.get("a_snr"), t.get("b_snr"),
        ]
        if any(fnum(v) is None for v in vals):
            fail(f"Non-finite registered-target input for candidate {rid}")

        a = corrected_endpoint(
            fnum(t["a_ra_deg"]), fnum(t["a_dec_deg"]),
            fnum(rr["shift_a_east_arcsec"]), fnum(rr["shift_a_north_arcsec"])
        )
        b = corrected_endpoint(
            fnum(t["b_ra_deg"]), fnum(t["b_dec_deg"]),
            fnum(rr["shift_b_east_arcsec"]), fnum(rr["shift_b_north_arcsec"])
        )

        reconstructed = float(a.separation(b).arcsec)
        frozen = fnum(rr["corrected_separation_arcsec"])
        delta = abs(reconstructed - frozen)

        if delta > 0.25:
            fail(
                f"Registered-target sign/geometry guard failed for {rid}: "
                f"reconstructed={reconstructed:.6f} frozen={frozen:.6f} "
                f"delta={delta:.6f} arcsec"
            )

        target = unit_midpoint(a, b)
        raw_target = SkyCoord(
            fnum(vr["target_ra_deg"]) * u.deg,
            fnum(vr["target_dec_deg"]) * u.deg,
            frame="icrs",
        )
        raw_to_registered = float(raw_target.separation(target).arcsec)

        science_ref_snr = min(abs(fnum(t["a_snr"])), abs(fnum(t["b_snr"])))

        row = {
            "raw_match_row": rid,
            "population": str(vr.get("population") or ""),
            "registered_target_ra_deg": float(target.ra.deg),
            "registered_target_dec_deg": float(target.dec.deg),
            "corrected_a_ra_deg": float(a.ra.deg),
            "corrected_a_dec_deg": float(a.dec.deg),
            "corrected_b_ra_deg": float(b.ra.deg),
            "corrected_b_dec_deg": float(b.dec.deg),
            "reconstructed_corrected_endpoint_sep_arcsec": reconstructed,
            "frozen_v068a_corrected_endpoint_sep_arcsec": frozen,
            "reconstruction_delta_arcsec": delta,
            "v078_raw_target_ra_deg": fnum(vr["target_ra_deg"]),
            "v078_raw_target_dec_deg": fnum(vr["target_dec_deg"]),
            "v078_raw_to_registered_target_sep_arcsec": raw_to_registered,
            "science_pair_reference_snr": science_ref_snr,
            "a_science_snr": fnum(t["a_snr"]),
            "b_science_snr": fnum(t["b_snr"]),
        }

        out.append(row)
        target_map[rid] = {
            "coord": target,
            "science_ref_snr": science_ref_snr,
            "population": row["population"],
        }

    return out, target_map


def gaia_query_text(target):
    ra = float(target.ra.deg)
    dec = float(target.dec.deg)
    return f"""SELECT
  source_id,
  ra,
  dec,
  ref_epoch,
  pmra,
  pmdec,
  parallax,
  phot_g_mean_mag
FROM gaiadr3.gaia_source
WHERE phot_g_mean_mag <= {GAIA_G_MAX:.1f}
  AND 1 = CONTAINS(
    POINT('ICRS', ra, dec),
    CIRCLE('ICRS', {ra:.12f}, {dec:.12f}, {GAIA_RADIUS_DEG:.12f})
  )
ORDER BY source_id
"""


def gaia_cache_paths(rid):
    base = GAIA_CACHE / f"candidate_{rid}"
    return (
        base.with_suffix(".adql"),
        base.with_suffix(".vot"),
        base.with_suffix(".meta.json"),
    )


def table_rows(tbl):
    rows = []
    for tr in tbl:
        d = {}
        for name in tbl.colnames:
            v = tr[name]
            if np.ma.is_masked(v):
                d[name] = ""
            else:
                try:
                    d[name] = v.item()
                except Exception:
                    d[name] = v
        rows.append(d)
    return rows


def acquire_gaia_candidate(rid, target):
    GAIA_CACHE.mkdir(parents=True, exist_ok=True)
    q = gaia_query_text(target)
    qpath, vpath, mpath = gaia_cache_paths(rid)
    qhash = hashlib.sha256(q.encode("utf-8")).hexdigest()

    if qpath.is_file() and vpath.is_file() and mpath.is_file():
        meta = json.loads(mpath.read_text(encoding="utf-8"))
        if (
            qpath.read_text(encoding="utf-8") == q
            and meta.get("status") == "COMPLETE"
            and meta.get("query_sha256") == qhash
            and meta.get("raw_votable_sha256") == sha256(vpath)
        ):
            raw = vpath.read_bytes()
            tbl = Table.read(BytesIO(raw), format="votable")
            rows = table_rows(tbl)
            if len(rows) != int(meta["rows"]):
                fail(f"Cached Gaia row count changed for candidate {rid}")
            return rows, {**meta, "cached": True}

    payload = urllib.parse.urlencode({
        "REQUEST": "doQuery",
        "LANG": "ADQL",
        "FORMAT": "votable",
        "RESPONSEFORMAT": "votable",
        "MAXREC": str(GAIA_MAXREC),
        "QUERY": q,
    }).encode("utf-8")

    last = None

    for attempt in range(1, GAIA_ATTEMPTS + 1):
        try:
            req = urllib.request.Request(
                GAIA_TAP,
                data=payload,
                method="POST",
                headers={
                    "User-Agent": UA,
                    "Accept": "application/x-votable+xml,text/xml,*/*",
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Cache-Control": "no-cache",
                },
            )
            with urllib.request.urlopen(req, timeout=240) as resp:
                raw = resp.read()
                status = int(getattr(resp, "status", 200))
                final_url = resp.geturl()

            tbl = Table.read(BytesIO(raw), format="votable")
            rows = table_rows(tbl)

            if len(rows) >= GAIA_MAXREC:
                fail(
                    f"Gaia MAXREC guard hit for candidate {rid}: {len(rows)} rows"
                )

            qtmp = qpath.with_suffix(qpath.suffix + ".tmp")
            vtmp = vpath.with_suffix(vpath.suffix + ".tmp")
            qtmp.write_text(q, encoding="utf-8")
            vtmp.write_bytes(raw)
            qtmp.replace(qpath)
            vtmp.replace(vpath)

            meta = {
                "status": "COMPLETE",
                "raw_match_row": rid,
                "rows": len(rows),
                "query_sha256": qhash,
                "raw_votable_sha256": sha256(vpath),
                "http_status": status,
                "final_url": final_url,
                "attempt": attempt,
                "cached": False,
            }
            atomic_json(mpath, meta)
            return rows, meta

        except Exception as exc:
            last = exc
            if attempt < GAIA_ATTEMPTS:
                time.sleep(min(30.0, 2.0 ** attempt))

    raise RuntimeError(
        f"Gaia reference acquisition failed for candidate {rid} after "
        f"{GAIA_ATTEMPTS} attempts: {type(last).__name__}: {last}"
    ) from last


def acquire_all_gaia(target_map):
    manifest = []
    data = {}

    for i, rid in enumerate(sorted(target_map, key=int), 1):
        rows, meta = acquire_gaia_candidate(rid, target_map[rid]["coord"])
        data[rid] = rows

        finite_pm = sum(
            fnum(r.get("ref_epoch")) is not None
            and fnum(r.get("pmra")) is not None
            and fnum(r.get("pmdec")) is not None
            for r in rows
        )

        manifest.append({
            "raw_match_row": rid,
            "population": target_map[rid]["population"],
            "rows": len(rows),
            "finite_motion_rows": finite_pm,
            "pm_incomplete_rows": len(rows) - finite_pm,
            "query_sha256": meta["query_sha256"],
            "raw_votable_sha256": meta["raw_votable_sha256"],
            "http_status": meta.get("http_status", ""),
            "attempt": meta.get("attempt", ""),
            "cached": meta.get("cached", False),
        })

        say(
            f"Gaia references {i}/23 candidate={rid}: "
            f"rows={len(rows):,} finite_motion={finite_pm:,} "
            f"cached={meta.get('cached', False)}"
        )

    return data, manifest


def acquisition_map():
    rows = read_csv(V079_ACQ)
    if len(rows) != 53:
        fail(f"Expected 53 v079 acquisition rows; found {len(rows)}")

    out = {}
    for r in rows:
        sid = inum(r.get("scan_id"))
        if sid is None:
            fail("v079 acquisition manifest contains blank scan_id")
        p = ROOT / str(r["local_path"]).replace("/", os.sep)
        out[sid] = {**r, "_path": p}
    return out


def verify_scan_bytes(acq):
    say()
    say("Verifying exact acquired scan bytes before outcome-bearing pixel phase ...")

    for i, sid in enumerate(sorted(acq), 1):
        r = acq[sid]
        p = r["_path"]
        if not p.is_file():
            fail(f"Acquired scan missing: {p}")
        expected_size = inum(r.get("actual_file_size"))
        if expected_size is not None and p.stat().st_size != expected_size:
            fail(f"Acquired scan size changed: {p}")
        expected_sha = str(r.get("sha256") or "").strip().lower()
        actual_sha = sha256(p)
        if expected_sha and actual_sha != expected_sha:
            fail(f"Acquired scan SHA changed: {p}")
        if i % 10 == 0 or i == len(acq):
            say(f"  scan-byte verification {i}/{len(acq)}")


def wcs_keys(h):
    keys = []
    if "CTYPE1" in h and "CTYPE2" in h:
        keys.append(" ")
    for name in h:
        m = re.fullmatch(r"CTYPE1([A-Z])", str(name))
        if m and f"CTYPE2{m.group(1)}" in h:
            keys.append(m.group(1))
    return sorted(set(keys), key=lambda x: (x != " ", x))


def choose_wcs(h):
    usable = []
    for key in wcs_keys(h):
        try:
            w = WCS(h, key=key).celestial
            if w.pixel_n_dim == 2 and w.world_n_dim == 2:
                usable.append((key, w))
        except Exception:
            pass
    if not usable:
        raise RuntimeError("No usable celestial WCS")
    usable.sort(key=lambda x: (x[0] != " ", x[0]))
    return usable[0]


def parse_time_value(v):
    s = str(v or "").strip()
    if not s:
        return None
    try:
        return Time(s, scale="utc")
    except Exception:
        try:
            return Time(s)
        except Exception:
            return None


def scan_epoch(header, plan_row):
    tavg = parse_time_value(header.get("DATE-AVG"))
    if tavg is not None:
        return tavg, "DATE-AVG"

    tobs = parse_time_value(header.get("DATE-OBS"))
    tend = parse_time_value(header.get("DATE-END"))

    if tobs is not None and tend is not None:
        jd = 0.5 * (float(tobs.jd) + float(tend.jd))
        return Time(jd, format="jd", scale="utc"), "MIDPOINT_DATE_OBS_DATE_END"

    if tobs is not None:
        return tobs, "DATE-OBS"

    p = parse_time_value(plan_row.get("representative_exposure_start_utc"))
    if p is not None:
        return p, "V079_REPRESENTATIVE_EXPOSURE_START"

    raise RuntimeError("No usable comparison scan epoch")


def propagate_gaia(rows, epoch):
    good = []
    incomplete = 0

    for r in rows:
        ra = fnum(r.get("ra"))
        dec = fnum(r.get("dec"))
        ref_epoch = fnum(r.get("ref_epoch"))
        pmra = fnum(r.get("pmra"))
        pmdec = fnum(r.get("pmdec"))

        if None in (ra, dec, ref_epoch, pmra, pmdec):
            incomplete += 1
            continue

        try:
            c = SkyCoord(
                ra=ra * u.deg,
                dec=dec * u.deg,
                pm_ra_cosdec=pmra * u.mas / u.yr,
                pm_dec=pmdec * u.mas / u.yr,
                obstime=Time(ref_epoch, format="jyear"),
                frame="icrs",
            )
            cp = c.apply_space_motion(new_obstime=epoch)
            good.append({
                "source_id": str(r.get("source_id") or ""),
                "coord": SkyCoord(cp.ra, cp.dec, frame="icrs"),
                "gmag": fnum(r.get("phot_g_mean_mag")),
            })
        except Exception:
            incomplete += 1

    return good, incomplete


def circle_bbox(w, shape, target, radius_arcmin, margin_px=64):
    pts = [target]
    radius = float(radius_arcmin) * u.arcmin

    for pa in np.linspace(0.0, 360.0, 16, endpoint=False):
        pts.append(target.directional_offset_by(pa * u.deg, radius))

    world = np.array([[float(c.ra.deg), float(c.dec.deg)] for c in pts])
    pix = np.asarray(w.all_world2pix(world, 0), dtype=float)

    if pix.shape != (len(pts), 2) or not np.all(np.isfinite(pix)):
        raise RuntimeError("Non-finite WCS circle projection")

    ny, nx = shape
    x0 = max(0, int(math.floor(np.min(pix[:,0]) - margin_px)))
    x1 = min(nx, int(math.ceil(np.max(pix[:,0]) + margin_px + 1)))
    y0 = max(0, int(math.floor(np.min(pix[:,1]) - margin_px)))
    y1 = min(ny, int(math.ceil(np.max(pix[:,1]) + margin_px + 1)))

    if x1 - x0 < 64 or y1 - y0 < 64:
        raise RuntimeError("Degenerate registration cutout")

    return x0, x1, y0, y1


def detector_world(baseline, w, x0, y0):
    x = np.asarray(baseline["x"], dtype=float)
    y = np.asarray(baseline["y"], dtype=float)

    if len(x) == 0:
        return [], np.array([], dtype=float), np.array([], dtype=float)

    gx = x + float(x0)
    gy = y + float(y0)
    world = np.asarray(
        w.all_pix2world(np.column_stack([gx, gy]), 0),
        dtype=float,
    )

    coords = [
        SkyCoord(float(ra) * u.deg, float(dec) * u.deg, frame="icrs")
        for ra, dec in world
    ]
    return coords, gx, gy


def reciprocal_matches(det_coords, gaia_rows, target):
    if not det_coords or not gaia_rows:
        return []

    dc = SkyCoord([c.ra for c in det_coords], [c.dec for c in det_coords])
    gc = SkyCoord(
        [g["coord"].ra for g in gaia_rows],
        [g["coord"].dec for g in gaia_rows],
    )

    d_to_g, dsep, _ = dc.match_to_catalog_sky(gc)
    g_to_d, gsep, _ = gc.match_to_catalog_sky(dc)

    out = []

    for di in range(len(det_coords)):
        gi = int(d_to_g[di])
        if int(g_to_d[gi]) != di:
            continue
        sep = float(dsep[di].arcsec)
        if sep > MATCH_ARCSEC:
            continue

        gcoord = gaia_rows[gi]["coord"]
        if float(gcoord.separation(target).arcsec) < TARGET_EXCLUSION_ARCSEC:
            continue

        de, dn = gcoord.spherical_offsets_to(det_coords[di])

        out.append({
            "det_index": di,
            "gaia_index": gi,
            "source_id": gaia_rows[gi]["source_id"],
            "gaia_coord": gcoord,
            "det_coord": det_coords[di],
            "raw_sep_arcsec": sep,
            "east_arcsec": float(de.to_value(u.arcsec)),
            "north_arcsec": float(dn.to_value(u.arcsec)),
            "target_sep_arcmin": float(gcoord.separation(target).arcmin),
        })

    return out


def fit_registration(matches):
    primary = None

    for window in REG_WINDOWS_ARCMIN:
        q = [m for m in matches if m["target_sep_arcmin"] <= window]
        if len(q) >= REG_PRIMARY_MIN:
            primary = (window, q)
            break

    if primary is not None:
        window, q = primary
        mode = "PRIMARY"
    else:
        q = [m for m in matches if m["target_sep_arcmin"] <= 30.0]
        if len(q) >= REG_SPARSE_MIN:
            window = 30.0
            mode = "SPARSE"
        else:
            return {
                "mode": "NONE",
                "window_arcmin": "",
                "n_refs": len(q),
                "shift_east_arcsec": "",
                "shift_north_arcsec": "",
                "matches": q,
            }

    east = float(np.median([m["east_arcsec"] for m in q]))
    north = float(np.median([m["north_arcsec"] for m in q]))

    return {
        "mode": mode,
        "window_arcmin": window,
        "n_refs": len(q),
        "shift_east_arcsec": east,
        "shift_north_arcsec": north,
        "matches": q,
    }


def corrected_peak_separations(det_coords, reg, target):
    if reg["mode"] == "NONE":
        return []

    east = float(reg["shift_east_arcsec"])
    north = float(reg["shift_north_arcsec"])
    out = []

    for i, c in enumerate(det_coords):
        cc = c.spherical_offsets_by(
            -east * u.arcsec,
            -north * u.arcsec,
        )
        sep = float(cc.separation(target).arcsec)
        out.append((sep, i, cc))

    out.sort(key=lambda x: (x[0], x[1]))
    return out


def expected_observed_target(target, reg):
    return target.spherical_offsets_by(
        float(reg["shift_east_arcsec"]) * u.arcsec,
        float(reg["shift_north_arcsec"]) * u.arcsec,
    )


def extract_injection_tile(data, cx, cy):
    ny, nx = data.shape
    half = INJECTION_TILE_SIZE // 2
    x0 = int(round(cx)) - half
    y0 = int(round(cy)) - half
    x1 = x0 + INJECTION_TILE_SIZE
    y1 = y0 + INJECTION_TILE_SIZE

    if x0 < 0:
        x1 -= x0
        x0 = 0
    if y0 < 0:
        y1 -= y0
        y0 = 0
    if x1 > nx:
        x0 -= x1 - nx
        x1 = nx
    if y1 > ny:
        y0 -= y1 - ny
        y1 = ny

    x0 = max(0, x0)
    y0 = max(0, y0)

    tile = np.asarray(data[y0:y1, x0:x1])
    local_x = float(cx) - x0
    local_y = float(cy) - y0

    return tile, x0, y0, local_x, local_y


def nearest_distance(x, y, pts):
    if not pts:
        return float("inf")
    return min(math.hypot(x-px, y-py) for px, py in pts)


def choose_injection_positions(mod, tile_shape, tx, ty, baseline):
    ny, nx = tile_shape

    bx = np.asarray(baseline["x"], dtype=float)
    by = np.asarray(baseline["y"], dtype=float)
    baseline_pts = list(zip(bx.tolist(), by.tolist()))

    margin = max(
        int(mod.STAMP_RADIUS_PX + math.ceil(mod.INJECTION_MATCH_RADIUS_PX) + 2),
        int(mod.EXPECTED_DETECTOR_EDGE_PX + math.ceil(mod.INJECTION_MATCH_RADIUS_PX) + 2),
    )

    def valid(x, y):
        if not (margin <= x < nx - margin):
            return False
        if not (margin <= y < ny - margin):
            return False
        if nearest_distance(x, y, baseline_pts) < float(mod.BASELINE_EXCLUSION_RADIUS_PX):
            return False
        return True

    cand = []

    for dy in mod.LOCAL_OFFSETS_PX:
        for dx in mod.LOCAL_OFFSETS_PX:
            x = int(round(tx + dx))
            y = int(round(ty + dy))
            if valid(x, y):
                cand.append((float(math.hypot(x-tx, y-ty)), y, x))

    if len(cand) < int(mod.N_INJECTION_POSITIONS):
        for y in range(margin, ny-margin, int(mod.FALLBACK_STEP_PX)):
            for x in range(margin, nx-margin, int(mod.FALLBACK_STEP_PX)):
                if valid(x, y):
                    cand.append((float(math.hypot(x-tx, y-ty)), y, x))

    # deterministic dedup + ordering
    uniq = {}
    for d, y, x in cand:
        uniq[(x, y)] = (d, y, x)
    cand = sorted(uniq.values(), key=lambda z: (z[0], z[1], z[2]))

    selected = []

    min_sep = 2 * int(mod.STAMP_RADIUS_PX) + 16

    for d, y, x in cand:
        if any(math.hypot(x-sx, y-sy) < min_sep for _, sy, sx in selected):
            continue
        selected.append((d, y, x))
        if len(selected) == int(mod.N_INJECTION_POSITIONS):
            break

    return [
        {
            "position_index": i,
            "local_x": x,
            "local_y": y,
            "distance_from_target_px": d,
            "nearest_baseline_peak_px": nearest_distance(x, y, baseline_pts),
        }
        for i, (d, y, x) in enumerate(selected, 1)
    ]


def forced_residual(tile, tx, ty, baseline_sigma, method):
    if not math.isfinite(float(baseline_sigma)) or float(baseline_sigma) <= 0:
        return None

    arr = np.asarray(tile, dtype=float)
    if not np.all(np.isfinite(arr)):
        return None

    bg = gaussian_filter(arr, float(method.background_sigma_px))
    residual = arr - bg

    x = int(round(tx))
    y = int(round(ty))

    if not (0 <= x < residual.shape[1] and 0 <= y < residual.shape[0]):
        return None

    return float(residual[y, x] / float(baseline_sigma))


def injection_for_row(mod, detect_array, method, tile, tx, ty, baseline, science_ref_snr, rid, plate_id, scan_id):
    positions = choose_injection_positions(
        mod, tile.shape, tx, ty, baseline
    )

    if len(positions) != int(mod.N_INJECTION_POSITIONS):
        return [], {
            "positions": len(positions),
            "qualified": False,
            "worst_90_snr": None,
            "reason": "INJECTION_POSITION_SHORTFALL",
        }

    baseline_sigma = float(baseline["sigma"])
    summaries = []

    for psf_sigma in mod.PSF_SIGMAS_PX:
        stamp = mod.gaussian_stamp(float(psf_sigma))
        response = float(mod.template_residual_response(float(psf_sigma), method))

        if not math.isfinite(response) or response <= 0:
            raise RuntimeError(
                f"Invalid frozen template residual response sigma={psf_sigma}"
            )

        for polarity in mod.INJECTION_POLARITIES:
            curve = []

            for target_snr in mod.TARGET_DETECTOR_SNRS:
                raw_peak_amplitude = (
                    float(target_snr) * baseline_sigma / response
                )

                injected, clipped = mod.quantized_injected_image(
                    tile,
                    positions,
                    stamp,
                    int(polarity),
                    raw_peak_amplitude,
                )

                det = detect_array(injected, method)
                rec = mod.match_recovery(det, positions, int(polarity))
                recovered = [r for r in rec if r["recovered"]]
                frac = len(recovered) / len(positions)

                row = {
                    "raw_match_row": rid,
                    "physical_plate_id": plate_id,
                    "scan_id": scan_id,
                    "psf_sigma_px": float(psf_sigma),
                    "injection_polarity": int(polarity),
                    "target_detector_snr": float(target_snr),
                    "baseline_detector_sigma": baseline_sigma,
                    "n_positions": len(positions),
                    "n_recovered": len(recovered),
                    "recovery_fraction": frac,
                    "median_recovered_snr": (
                        float(np.median([r["recovered_snr"] for r in recovered]))
                        if recovered else ""
                    ),
                    "min_recovered_snr": (
                        float(min(r["recovered_snr"] for r in recovered))
                        if recovered else ""
                    ),
                    "max_recovered_snr": (
                        float(max(r["recovered_snr"] for r in recovered))
                        if recovered else ""
                    ),
                    "n_quantization_clipped": int(clipped),
                }
                summaries.append(row)
                curve.append(row)

    thresholds90 = []

    for psf_sigma in mod.PSF_SIGMAS_PX:
        for polarity in mod.INJECTION_POLARITIES:
            q = [
                r for r in summaries
                if float(r["psf_sigma_px"]) == float(psf_sigma)
                and int(r["injection_polarity"]) == int(polarity)
            ]
            threshold = mod.first_recovery_target(q, 0.90)
            thresholds90.append(threshold)

    finite_thresholds = [x for x in thresholds90 if x is not None]
    worst = max(finite_thresholds) if len(finite_thresholds) == 6 else None
    qualified = (
        worst is not None
        and float(worst) <= float(science_ref_snr)
    )

    return summaries, {
        "positions": len(positions),
        "qualified": bool(qualified),
        "worst_90_snr": worst,
        "reason": (
            "QUALIFIED"
            if qualified
            else (
                "MISSING_90_PERCENT_THRESHOLD"
                if worst is None
                else "WORST_90_THRESHOLD_ABOVE_SCIENCE_REFERENCE_SNR"
            )
        ),
    }


def checkpoint_path(rid, plate_id, scan_id):
    return CHECKPOINTS / f"candidate_{rid}_plate_{plate_id}_scan_{scan_id}.json"


def load_checkpoint(path):
    if not path.is_file():
        return None
    obj = json.loads(path.read_text(encoding="utf-8"))
    if (
        obj.get("status") == "COMPLETE"
        and obj.get("contract_sha256") == EXPECTED_CONTRACT_SHA
    ):
        return obj
    return None


def process_plan_row(plan_row, target_info, gaia_rows, acq_row, mod, detect_array, method):
    rid = str(plan_row["raw_match_row"])
    plate_id = inum(plan_row.get("physical_plate_id"))
    scan_id = inum(plan_row.get("scan_id"))

    cp = checkpoint_path(rid, plate_id, scan_id)
    old = load_checkpoint(cp)
    if old is not None:
        return old["measurement"], old.get("injection_summary", []), True

    p = acq_row["_path"]
    if not p.is_file():
        raise RuntimeError(f"Missing scan file {p}")

    target = target_info["coord"]
    science_ref_snr = float(target_info["science_ref_snr"])

    with fits.open(
        p,
        mode="readonly",
        memmap=True,
        lazy_load_hdus=True,
        do_not_scale_image_data=True,
        ignore_missing_end=True,
    ) as hdul:
        if len(hdul) != 1:
            raise RuntimeError(
                f"v080 preflight invariant changed: {p} has {len(hdul)} HDUs"
            )

        hdu = hdul[0]
        h = hdu.header
        key, w = choose_wcs(h)

        # This is the first outcome-bearing pixel access.
        data = hdu.data
        if data is None or data.ndim != 2:
            raise RuntimeError(f"No 2-D FITS pixel array in {p}")

        epoch, epoch_source = scan_epoch(h, plan_row)
        propagated, pm_incomplete = propagate_gaia(gaia_rows, epoch)

        x0, x1, y0, y1 = circle_bbox(
            w, data.shape, target, REG_FIELD_ARCMIN
        )
        base = np.asarray(data[y0:y1, x0:x1])
        baseline = detect_array(base, method)
        det_coords, gx, gy = detector_world(baseline, w, x0, y0)

        matches = reciprocal_matches(det_coords, propagated, target)
        reg = fit_registration(matches)

        peak_sep = corrected_peak_separations(det_coords, reg, target)

        strict = [
            q for q in peak_sep
            if q[0] <= STRICT_ARCSEC
        ] if reg["mode"] == "PRIMARY" else []

        diagnostic = [
            q for q in peak_sep
            if STRICT_ARCSEC < q[0] <= DIAG_ARCSEC
        ] if reg["mode"] == "PRIMARY" else []

        best_sep = peak_sep[0][0] if peak_sep else None
        closest_index = peak_sep[0][1] if peak_sep else None

        forced = None
        inj_summary = []
        inj_meta = {
            "positions": 0,
            "qualified": False,
            "worst_90_snr": None,
            "reason": "NOT_RUN",
        }

        if reg["mode"] == "PRIMARY":
            observed_target = expected_observed_target(target, reg)
            xy = np.asarray(
                w.all_world2pix(
                    [[float(observed_target.ra.deg), float(observed_target.dec.deg)]],
                    0,
                ),
                dtype=float,
            )[0]

            if not np.all(np.isfinite(xy)):
                raise RuntimeError("Expected registered target pixel is non-finite")

            tile, tx0, ty0, tx, ty = extract_injection_tile(
                data, float(xy[0]), float(xy[1])
            )
            tile_baseline = detect_array(tile, method)
            forced = forced_residual(
                tile, tx, ty, float(tile_baseline["sigma"]), method
            )

            if not strict:
                inj_summary, inj_meta = injection_for_row(
                    mod,
                    detect_array,
                    method,
                    tile,
                    tx,
                    ty,
                    tile_baseline,
                    science_ref_snr,
                    rid,
                    plate_id,
                    scan_id,
                )

        # A negative is only sensitivity-qualified when there is no <=5" peak.
        sensitivity_qualified = bool(
            reg["mode"] == "PRIMARY"
            and len(strict) == 0
            and len(diagnostic) == 0
            and inj_meta["qualified"]
        )

        strict_ref_after = 0
        if reg["mode"] == "PRIMARY":
            east = float(reg["shift_east_arcsec"])
            north = float(reg["shift_north_arcsec"])
            for m in reg["matches"]:
                cc = m["det_coord"].spherical_offsets_by(
                    -east * u.arcsec, -north * u.arcsec
                )
                if float(cc.separation(m["gaia_coord"]).arcsec) <= 3.0:
                    strict_ref_after += 1

        measurement = {
            "raw_match_row": rid,
            "population": str(plan_row.get("population") or ""),
            "selection_role": str(plan_row.get("selection_role") or ""),
            "physical_plate_id": plate_id,
            "scan_id": scan_id,
            "archive_family": str(plan_row.get("archive_family") or ""),
            "filename_scan": str(plan_row.get("filename_scan") or ""),
            "scan_epoch_isot": str(epoch.isot),
            "scan_epoch_source": epoch_source,
            "wcs_key": key,
            "registration_mode": reg["mode"],
            "registration_window_arcmin": reg["window_arcmin"],
            "registration_refs": reg["n_refs"],
            "registration_shift_east_arcsec": reg["shift_east_arcsec"],
            "registration_shift_north_arcsec": reg["shift_north_arcsec"],
            "gaia_propagated_rows": len(propagated),
            "gaia_pm_incomplete_rows": pm_incomplete,
            "reciprocal_gaia_detector_matches_15arcsec": len(matches),
            "registration_refs_corrected_le3_arcsec": strict_ref_after,
            "baseline_detector_peak_count": len(np.asarray(baseline["x"])),
            "strict_native_recurrence": bool(strict),
            "strict_native_peak_count": len(strict),
            "diagnostic_native_peak_count": len(diagnostic),
            "closest_corrected_peak_sep_arcsec": (
                float(best_sep) if best_sep is not None else ""
            ),
            "closest_peak_detector_snr": (
                float(np.asarray(baseline["snr"], dtype=float)[closest_index])
                if closest_index is not None else ""
            ),
            "closest_peak_polarity": (
                int(np.asarray(baseline["polarity"], dtype=int)[closest_index])
                if closest_index is not None else ""
            ),
            "forced_target_residual_sigma": (
                forced if forced is not None else ""
            ),
            "science_pair_reference_snr": science_ref_snr,
            "injection_run": bool(reg["mode"] == "PRIMARY" and not strict),
            "injection_positions": inj_meta["positions"],
            "worst_sixway_90pct_recovery_snr": (
                inj_meta["worst_90_snr"]
                if inj_meta["worst_90_snr"] is not None else ""
            ),
            "injection_sensitivity_reason": inj_meta["reason"],
            "sensitivity_qualified_negative": sensitivity_qualified,
            "candidate_disposition_changed": False,
        }

    atomic_json(cp, {
        "status": "COMPLETE",
        "contract_sha256": EXPECTED_CONTRACT_SHA,
        "operational_repair": "v080a corrected authoritative candidate-policy path only",
        "original_v080_runner_sha256": ORIGINAL_V080_RUNNER_SHA,
        "scientific_contract_changed_by_v080a": False,
        "measurement": measurement,
        "injection_summary": inj_summary,
    })

    return measurement, inj_summary, False


def aggregate_candidates(plate_rows, target_rows):
    by_candidate = defaultdict(list)
    for r in plate_rows:
        by_candidate[str(r["raw_match_row"])].append(r)

    target_by_id = {str(r["raw_match_row"]): r for r in target_rows}
    out = []

    for rid in sorted(target_by_id, key=int):
        rows = by_candidate.get(rid, [])
        strict_pids = sorted({
            int(r["physical_plate_id"])
            for r in rows
            if truth(r.get("strict_native_recurrence"))
            and str(r.get("registration_mode")) == "PRIMARY"
        })
        negative_pids = sorted({
            int(r["physical_plate_id"])
            for r in rows
            if truth(r.get("sensitivity_qualified_negative"))
        })
        diag_pids = sorted({
            int(r["physical_plate_id"])
            for r in rows
            if int(r.get("diagnostic_native_peak_count") or 0) > 0
            and not truth(r.get("strict_native_recurrence"))
            and str(r.get("registration_mode")) == "PRIMARY"
        })

        if len(strict_pids) >= 2:
            state = "MECHANICALLY_EXPLAINED_RECURRENT_SKY_SOURCE"
        elif len(strict_pids) == 1:
            state = "ONE_INDEPENDENT_NATIVE_RECURRENCE_RETAIN"
        elif len(negative_pids) >= 2:
            state = "TRANSIENT_LIKE_NATIVE_NONRECURRENCE_SUPPORTED"
        else:
            state = "UNRESOLVED_NATIVE_SENSITIVITY_INSUFFICIENT"

        out.append({
            "raw_match_row": rid,
            "population": target_by_id[rid]["population"],
            "planned_plate_rows": len(rows),
            "primary_registered_plate_rows": sum(
                str(r.get("registration_mode")) == "PRIMARY" for r in rows
            ),
            "sparse_registered_plate_rows": sum(
                str(r.get("registration_mode")) == "SPARSE" for r in rows
            ),
            "unregistered_plate_rows": sum(
                str(r.get("registration_mode")) == "NONE" for r in rows
            ),
            "strict_native_recurrence_physical_plate_count": len(strict_pids),
            "strict_native_recurrence_plate_ids": ";".join(map(str, strict_pids)),
            "diagnostic_native_context_physical_plate_count": len(diag_pids),
            "diagnostic_native_context_plate_ids": ";".join(map(str, diag_pids)),
            "sensitivity_qualified_negative_physical_plate_count": len(negative_pids),
            "sensitivity_qualified_negative_plate_ids": ";".join(map(str, negative_pids)),
            "mechanical_evidence_state": state,
            "candidate_disposition_changed": False,
        })

    return out


def main():
    print("=" * 132)
    print("PAIR 17 — REGISTERED NATIVE-PIXEL RECURRENCE + SENSITIVITY v080a")
    print("=" * 132)
    print("Frozen candidates:       23 (13 PRIMARY + 10 DIAGNOSTIC)")
    print("Frozen plan rows:        129")
    print("Acquired scans:          53")
    print("Pixel workers:           2")
    print("Threshold retuning:      NO")
    print("Formal dispositions:     NO MUTATION")
    print()

    if not CONTRACT.is_file():
        fail(f"Missing frozen v080 contract: {CONTRACT}")
    if sha256(CONTRACT) != EXPECTED_CONTRACT_SHA:
        fail("v080 scientific contract SHA mismatch")

    for p, expected in EXPECTED_SHA.items():
        if not p.is_file():
            fail(f"Missing frozen v080 input: {p}")
        actual = sha256(p)
        if actual != expected:
            fail(
                f"Frozen v080 input SHA mismatch:\n{p}\n"
                f"expected {expected}\nactual   {actual}"
            )
        print("HASH PASS:", p.relative_to(ROOT))

    plan_rows = read_csv(V079_PLAN)
    if len(plan_rows) != 129:
        fail(f"Frozen v079 plan row count changed: {len(plan_rows)}")

    target_rows, target_map = build_registered_targets()

    if len(target_rows) != 23:
        fail("Registered target reconstruction did not produce 23 candidates")

    OUT.mkdir(parents=True, exist_ok=True)
    CHECKPOINTS.mkdir(parents=True, exist_ok=True)
    atomic_csv(OUT_TARGETS, target_rows)

    print()
    print("REGISTERED TARGET PRE-PIXEL GUARD PASS")
    print("  candidates: 23")
    print(
        "  max reconstructed-v068a separation delta: "
        f"{max(float(r['reconstruction_delta_arcsec']) for r in target_rows):.6f} arcsec"
    )

    mod, detect_array, method = load_order01_injection()

    print()
    print("Frozen detector / injection implementation: PASS")
    print("  peak_sigma:", method.peak_sigma)
    print("  edge_px:", method.edge_px)
    print("  injection sigmas:", list(mod.PSF_SIGMAS_PX))
    print("  injection target SNRs:", list(mod.TARGET_DETECTOR_SNRS))
    print()

    # CRITICAL prospective guard: finish all network reference acquisition
    # before any comparison image pixels are read.
    print("GAIA REFERENCE ACQUISITION — ALL 23 BEFORE PIXEL PHASE")
    gaia_data, gaia_manifest = acquire_all_gaia(target_map)
    atomic_csv(OUT_GAIA, gaia_manifest)

    print()
    print("Gaia reference acquisition COMPLETE for all 23 candidates.")
    print("Network phase is now closed; comparison pixel phase may begin.")

    acq = acquisition_map()
    verify_scan_bytes(acq)

    # Map exact plan rows to acquired scan provenance.
    tasks = []
    for r in plan_rows:
        rid = str(r["raw_match_row"])
        sid = inum(r.get("scan_id"))
        if rid not in target_map:
            fail(f"Plan contains non-frozen candidate {rid}")
        if sid not in acq:
            fail(f"Plan scan_id {sid} missing from acquisition manifest")
        tasks.append((r, target_map[rid], gaia_data[rid], acq[sid]))

    measurements = []
    injections = []
    failures = []
    reused = 0

    print()
    print("NATIVE PIXEL PHASE")
    print(f"  candidate x plate tasks: {len(tasks)}")
    print(f"  workers: {PIXEL_WORKERS}")

    with ThreadPoolExecutor(max_workers=PIXEL_WORKERS) as pool:
        futs = {
            pool.submit(
                process_plan_row,
                r, ti, gd, ar,
                mod, detect_array, method
            ): r
            for r, ti, gd, ar in tasks
        }

        done = 0
        for fut in as_completed(futs):
            r = futs[fut]
            rid = str(r["raw_match_row"])
            pid = r.get("physical_plate_id")
            sid = r.get("scan_id")

            try:
                m, inj, was_reused = fut.result()
                measurements.append(m)
                injections.extend(inj)
                reused += int(was_reused)
            except Exception as exc:
                failures.append({
                    "raw_match_row": rid,
                    "population": r.get("population", ""),
                    "physical_plate_id": pid,
                    "scan_id": sid,
                    "selection_role": r.get("selection_role", ""),
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                })

            done += 1
            if done % 5 == 0 or done == len(tasks):
                say(
                    f"Processed {done}/{len(tasks)} candidate x plate rows; "
                    f"complete={len(measurements)} failures={len(failures)} "
                    f"checkpoint_reused={reused}"
                )

    measurements.sort(
        key=lambda r: (
            int(r["raw_match_row"]),
            int(r["physical_plate_id"]),
            int(r["scan_id"]),
        )
    )
    injections.sort(
        key=lambda r: (
            int(r["raw_match_row"]),
            int(r["physical_plate_id"]),
            float(r["psf_sigma_px"]),
            int(r["injection_polarity"]),
            float(r["target_detector_snr"]),
        )
    )

    atomic_csv(OUT_PLATES, measurements)
    atomic_csv(OUT_INJ, injections)

    if failures:
        atomic_csv(OUT_FAIL, failures)

    candidate_rows = aggregate_candidates(measurements, target_rows)
    atomic_csv(OUT_CAND, candidate_rows)

    complete_population = (
        len(measurements) == 129
        and len(failures) == 0
        and all(int(r["planned_plate_rows"]) >= 1 for r in candidate_rows)
    )

    state_counts = Counter(r["mechanical_evidence_state"] for r in candidate_rows)
    registration_counts = Counter(r["registration_mode"] for r in measurements)

    report = {
        "status": "COMPLETE" if complete_population else "PARTIAL_OPERATIONAL_HOLD",
        "analysis_kind":
            "pair17_registered_native_pixel_recurrence_sensitivity_v080",
        "contract_sha256": EXPECTED_CONTRACT_SHA,
        "population": {
            "frozen_candidates": 23,
            "primary": 13,
            "diagnostic": 10,
            "planned_candidate_x_plate_rows": 129,
            "completed_candidate_x_plate_rows": len(measurements),
            "operational_failures": len(failures),
        },
        "gaia_reference_acquisition": {
            "candidate_queries_complete_before_pixels": len(gaia_manifest),
            "network_after_pixel_phase_started": False,
        },
        "registration_mode_counts": dict(registration_counts),
        "native_pixel": {
            "strict_recurrence_plate_rows": sum(
                truth(r.get("strict_native_recurrence")) for r in measurements
            ),
            "diagnostic_context_plate_rows": sum(
                int(r.get("diagnostic_native_peak_count") or 0) > 0
                and not truth(r.get("strict_native_recurrence"))
                for r in measurements
            ),
            "sensitivity_qualified_negative_plate_rows": sum(
                truth(r.get("sensitivity_qualified_negative")) for r in measurements
            ),
            "injection_summary_rows": len(injections),
        },
        "mechanical_candidate_state_counts": dict(state_counts),
        "guards": {
            "threshold_retuning": False,
            "manual_review": False,
            "formal_candidate_disposition_changes": False,
            "full_image_copies_written": 0,
        },
        "outputs": {
            "registered_targets": str(OUT_TARGETS.relative_to(ROOT)).replace("\\", "/"),
            "gaia_manifest": str(OUT_GAIA.relative_to(ROOT)).replace("\\", "/"),
            "plate_measurements": str(OUT_PLATES.relative_to(ROOT)).replace("\\", "/"),
            "injection_summary": str(OUT_INJ.relative_to(ROOT)).replace("\\", "/"),
            "candidate_summary": str(OUT_CAND.relative_to(ROOT)).replace("\\", "/"),
            "failure_csv": (
                str(OUT_FAIL.relative_to(ROOT)).replace("\\", "/")
                if failures else ""
            ),
        },
    }
    atomic_json(OUT_JSON, report)

    print()
    print("=" * 132)
    print("v080 NATIVE-PIXEL STAGE FINISHED")
    print("=" * 132)
    print("Status:", report["status"])
    print("Completed plate rows:", len(measurements), "/ 129")
    print("Operational failures:", len(failures))
    print("Registration modes:", dict(registration_counts))
    print(
        "Strict native recurrence plate rows:",
        report["native_pixel"]["strict_recurrence_plate_rows"]
    )
    print(
        "Sensitivity-qualified negative plate rows:",
        report["native_pixel"]["sensitivity_qualified_negative_plate_rows"]
    )
    print("Mechanical candidate states:")
    for key in sorted(state_counts):
        print(f"  {key}: {state_counts[key]}")
    print("Formal candidate dispositions changed: NONE")
    print("Thresholds retuned: NO")

    if failures:
        raise RuntimeError(
            f"v080 PARTIAL_OPERATIONAL_HOLD: {len(failures)} row failures "
            f"preserved in {OUT_FAIL}"
        )


if __name__ == "__main__":
    main()
