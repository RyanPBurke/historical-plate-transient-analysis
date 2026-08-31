from __future__ import annotations

from pathlib import Path
from urllib.parse import urlencode
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
from astropy.coordinates import SkyCoord

ROOT = Path.cwd()
BASE = ROOT / "results" / "order01_native_full_v028"
WORK = ROOT / "work" / "order01_ps1_static_v028"
CACHE = WORK / "query_cache"

PAIR_REPORT = BASE / "order01_whole_pair_report.json"
GAIA_REPORT = BASE / "order01_gaia_static_report_v028b.json"
GAIA_TRIAGE = BASE / "order01_gaia_static_triage_v028b.csv"

OUT = BASE / "order01_ps1_static_triage_v028.csv"
OUT_SOURCES = BASE / "order01_ps1_static_sources_v028.csv"
OUT_REPORT = BASE / "order01_ps1_static_report_v028.json"

API = "https://catalogs.mast.stsci.edu/api/v0.1/panstarrs/dr2/mean.csv"
UA = "historical-transient-pipeline/0.2.8-order01-ps1-static"

EXPECTED_POLICY_SHA = "44fc3453c3291a7cbe72894d781729a30943ad540aa169b2c0897b446c5c8ec7"
EXPECTED_DETECTOR_SHA = "709da8d7a7972b15808d70a1e4dbffa0fd0fee864a81d954f74fe4a5f5af25e7"
EXPECTED_METHOD_SHA = "2cb3cabd573d7af99399899f2ccecd3002be90297e55bb0e0dcdd9dea1d0c4c1"

EXPECTED_ORDER = 1
EXPECTED_RAW10 = 476
EXPECTED_STRICT3 = 38
EXPECTED_GAIA_CLEAN = [
    3, 5, 6, 7, 8, 10, 11, 12, 18, 19, 20, 21, 22,
    23, 24, 25, 26, 27, 28, 29, 30, 31, 35, 36, 37, 38,
]

# Frozen by the completed Order-61 independent PS1 stage.
QUERY_RADIUS_ARCSEC = 120.0
STATIC_STRONG_ARCSEC = 3.0
STATIC_DIAGNOSTIC_ARCSEC = 5.0
MIN_DETECTIONS = 2
PAGE_SIZE = 10000

PAIR_FIELDS = [
    "strict_rank",
    "gaia_class",
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
    "ps1_class",
    "ps1_within_3arcsec",
    "ps1_within_5arcsec",
    "ps1_nearest_objid",
    "ps1_nearest_sep_mid_arcsec",
    "ps1_nearest_sep_poss_arcsec",
    "ps1_nearest_sep_dasch_arcsec",
    "ps1_nearest_nDetections",
    "ps1_nearest_qualityFlag",
    "ps1_nearest_raMean_deg",
    "ps1_nearest_decMean_deg",
    "ps1_nearest_epochMean_mjd",
    "ps1_nearest_pmra_masyr",
    "ps1_nearest_pmdec_masyr",
    "ps1_nearest_gMeanPSFMag",
    "ps1_nearest_rMeanPSFMag",
    "ps1_nearest_iMeanPSFMag",
    "ps1_nearest_zMeanPSFMag",
    "ps1_nearest_yMeanPSFMag",
    "ps1_returned_rows",
    "survives_gaia_and_ps1_3arcsec",
    "survives_gaia_and_ps1_5arcsec",
]

SOURCE_FIELDS = [
    "strict_rank",
    "objID",
    "raMean",
    "decMean",
    "sep_mid_arcsec",
    "sep_poss_arcsec",
    "sep_dasch_arcsec",
    "nDetections",
    "qualityFlag",
    "epochMean",
    "pmra",
    "pmdec",
    "pmraErr",
    "pmdecErr",
    "gMeanPSFMag",
    "rMeanPSFMag",
    "iMeanPSFMag",
    "zMeanPSFMag",
    "yMeanPSFMag",
]


def sha_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def read_csv(path: Path):
    with path.open(newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def write_csv(path: Path, rows, fields):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    tmp.replace(path)


def write_json(path: Path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(obj, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )
    tmp.replace(path)


def as_bool(v):
    return str(v).strip().lower() in {"true", "1", "yes", "y", "t"}


def ffloat(v):
    if v is None:
        return None
    s = str(v).strip()
    if not s or s.lower() in {"nan", "null", "none", "-999"}:
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


def midpoint_coord(p: SkyCoord, d: SkyCoord):
    xyz = p.cartesian.xyz.value + d.cartesian.xyz.value
    xyz = xyz / np.linalg.norm(xyz)
    c = SkyCoord(
        x=xyz[0],
        y=xyz[1],
        z=xyz[2],
        representation_type="cartesian",
        frame="icrs",
    )
    return SkyCoord(
        ra=c.spherical.lon,
        dec=c.spherical.lat,
        frame="icrs",
    )


def parse_ps1(raw: bytes):
    text = raw.decode("utf-8-sig", errors="strict")
    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None:
        raise RuntimeError("PS1 response has no CSV header")

    required = {"objID", "raMean", "decMean", "nDetections"}
    missing = required - set(reader.fieldnames)
    if missing:
        raise RuntimeError(
            "PS1 mean response missing required columns: "
            + repr(sorted(missing))
        )

    rows = list(reader)
    if len(rows) >= PAGE_SIZE:
        raise RuntimeError(
            f"REFUSING: PS1 query hit pagesize={PAGE_SIZE}; completeness not assured"
        )
    return rows


def query_ps1(ra_deg: float, dec_deg: float, rank: int):
    """
    Exact transport/query policy used by the completed Order-61 PS1 stage:
    official MAST Pan-STARRS DR2 mean-object endpoint, nDetections>=2,
    verified curl HTTPS, no TLS bypass.
    """
    CACHE.mkdir(parents=True, exist_ok=True)

    params = {
        "ra": f"{ra_deg:.12f}",
        "dec": f"{dec_deg:.12f}",
        "radius": f"{QUERY_RADIUS_ARCSEC / 3600.0:.12f}",
        "pagesize": str(PAGE_SIZE),
        "nDetections.gte": str(MIN_DETECTIONS),
    }

    url = API + "?" + urlencode(params)
    raw_path = CACHE / f"strict_{rank:02d}_ps1_mean.csv"
    meta_path = CACHE / f"strict_{rank:02d}_ps1_mean.json"

    if raw_path.is_file() and meta_path.is_file():
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        raw = raw_path.read_bytes()
        sha = hashlib.sha256(raw).hexdigest()

        if (
            meta.get("complete") is True
            and meta.get("url") == url
            and meta.get("sha256") == sha
        ):
            rows = parse_ps1(raw)
            return rows, {**meta, "cached": True}, "cached"

    curl = shutil.which("curl.exe") or shutil.which("curl")
    if not curl:
        raise RuntimeError(
            "Verified HTTPS transport unavailable: curl.exe/curl was not found. "
            "TLS verification will not be disabled."
        )

    part_path = raw_path.with_suffix(".csv.part")
    if part_path.exists():
        part_path.unlink()

    errors = []

    for attempt in range(1, 5):
        if part_path.exists():
            part_path.unlink()

        cmd = [
            curl,
            "--fail",
            "--silent",
            "--show-error",
            "--location",
            "--connect-timeout", "30",
            "--max-time", "180",
            "--user-agent", UA,
            "--header", "Accept: text/csv,*/*",
            "--output", str(part_path),
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
                    f"curl exit {cp.returncode}: {err[:500]}"
                )

            if not part_path.is_file():
                raise RuntimeError(
                    "curl reported success but produced no response file"
                )

            raw = part_path.read_bytes()
            preview = raw[:500].decode("utf-8", errors="replace")

            if preview.lstrip().startswith("<"):
                raise RuntimeError(
                    "MAST returned HTML/XML rather than PS1 CSV: "
                    + preview.replace("\n", " ")[:250]
                )

            rows = parse_ps1(raw)
            sha = hashlib.sha256(raw).hexdigest()

            part_path.replace(raw_path)

            meta = {
                "complete": True,
                "url": url,
                "sha256": sha,
                "bytes": len(raw),
                "row_count": len(rows),
                "transport": "curl_verified_https",
                "curl_executable": curl,
                "tls_verification_disabled": False,
                "attempt": attempt,
                "cached": False,
            }
            write_json(meta_path, meta)

            return rows, meta, "done"

        except (subprocess.TimeoutExpired, RuntimeError, OSError) as exc:
            errors.append(repr(exc))
            print(
                f"    PS1 strict #{rank:02d} attempt {attempt}/4 FAILED: {exc}",
                flush=True,
            )

            if part_path.exists():
                try:
                    part_path.unlink()
                except OSError:
                    pass

            if attempt < 4:
                time.sleep(2 ** attempt)

    raise RuntimeError(
        f"PS1 query failed for strict #{rank:02d}: {errors[-1]}"
    )


def classify(rows, p: SkyCoord, d: SkyCoord, mid: SkyCoord, rank: int):
    """
    Reproduce the frozen Order-61 PS1 positional classification exactly:
    nearest repeated PS1 mean object to the pair midpoint; <=3" strong,
    <=5" diagnostic. Endpoint separations are retained for audit.
    """
    out = []

    for r in rows:
        ra = ffloat(r.get("raMean"))
        dec = ffloat(r.get("decMean"))
        nd = fint(r.get("nDetections"))

        if ra is None or dec is None or nd is None:
            continue

        c = SkyCoord(
            ra=ra * u.deg,
            dec=dec * u.deg,
            frame="icrs",
        )

        out.append({
            "strict_rank": rank,
            "objID": str(r.get("objID", "")).strip(),
            "raMean": ra,
            "decMean": dec,
            "sep_mid_arcsec": float(c.separation(mid).arcsec),
            "sep_poss_arcsec": float(c.separation(p).arcsec),
            "sep_dasch_arcsec": float(c.separation(d).arcsec),
            "nDetections": nd,
            "qualityFlag": fint(r.get("qualityFlag")),
            "epochMean": ffloat(r.get("epochMean")),
            "pmra": ffloat(r.get("pmra")),
            "pmdec": ffloat(r.get("pmdec")),
            "pmraErr": ffloat(r.get("pmraErr")),
            "pmdecErr": ffloat(r.get("pmdecErr")),
            "gMeanPSFMag": ffloat(r.get("gMeanPSFMag")),
            "rMeanPSFMag": ffloat(r.get("rMeanPSFMag")),
            "iMeanPSFMag": ffloat(r.get("iMeanPSFMag")),
            "zMeanPSFMag": ffloat(r.get("zMeanPSFMag")),
            "yMeanPSFMag": ffloat(r.get("yMeanPSFMag")),
        })

    out.sort(
        key=lambda x: (
            x["sep_mid_arcsec"],
            x["objID"],
        )
    )

    nearest = out[0] if out else None

    within3 = (
        nearest is not None
        and nearest["sep_mid_arcsec"] <= STATIC_STRONG_ARCSEC
    )
    within5 = (
        nearest is not None
        and nearest["sep_mid_arcsec"] <= STATIC_DIAGNOSTIC_ARCSEC
    )

    if within3:
        cls = "PS1_REPEATED_STATIC_STRONG"
    elif within5:
        cls = "PS1_REPEATED_STATIC_DIAGNOSTIC"
    else:
        cls = "NO_PS1_REPEAT_WITHIN_5_ARCSEC"

    return cls, within3, within5, nearest, out


def main():
    print("=" * 94)
    print("ORDER 01 — PAN-STARRS DR2 INDEPENDENT STATIC / REPEATED-SOURCE CHECK v028")
    print("=" * 94)
    print(
        "Corrected-v028b Gaia-clean cases only; verified curl HTTPS; "
        "no detector; no science image pixels; no candidate deletion."
    )
    print()

    for p in (PAIR_REPORT, GAIA_REPORT, GAIA_TRIAGE):
        if not p.is_file():
            raise RuntimeError(f"Missing required completed-stage file: {p}")

    policy = ROOT / "research" / "NATIVE_TILE_EXECUTION_POLICY_V028_2026-08-21.json"
    detector = ROOT / "src" / "transient_pipeline" / "detector.py"
    method = ROOT / "config" / "frozen_method.json"

    for p in (policy, detector, method):
        if not p.is_file():
            raise RuntimeError(f"Missing frozen input: {p}")

    pair_report = json.loads(PAIR_REPORT.read_text(encoding="utf-8"))
    gaia_report = json.loads(GAIA_REPORT.read_text(encoding="utf-8"))
    gaia_rows = read_csv(GAIA_TRIAGE)

    gaia_clean_report = [
        int(x)
        for x in gaia_report.get("gaia_clean_5arcsec_ranks", [])
    ]
    gaia_clean_rows = sorted(
        int(r["strict_rank"])
        for r in gaia_rows
        if as_bool(r["gaia_clean_5arcsec"])
    )

    amendment = gaia_report.get("implementation_amendment", {})

    guards = {
        "pair_status": pair_report.get("status") == "COMPLETE",
        "order": int(pair_report.get("canonical_order", -1)) == EXPECTED_ORDER,
        "pair_detector": pair_report.get("detector_sha256") == EXPECTED_DETECTOR_SHA,
        "detector_file": sha_file(detector) == EXPECTED_DETECTOR_SHA,
        "pair_method": pair_report.get("method_sha256") == EXPECTED_METHOD_SHA,
        "method_file": sha_file(method) == EXPECTED_METHOD_SHA,
        "policy_file": sha_file(policy) == EXPECTED_POLICY_SHA,
        "raw10": int(pair_report.get("raw_le_10arcsec", -1)) == EXPECTED_RAW10,
        "strict3": int(pair_report.get("raw_le_3arcsec", -1)) == EXPECTED_STRICT3,
        "gaia_status": gaia_report.get("status") == "COMPLETE",
        "gaia_kind_v028b": gaia_report.get("analysis_kind")
            == "order01_gaia_dr3_static_epoch_propagation_v028b",
        "gaia_input_count": int(gaia_report.get("strict_input_count", -1))
            == EXPECTED_STRICT3,
        "gaia_clean_count": int(gaia_report.get("gaia_clean_5arcsec_count", -1))
            == len(EXPECTED_GAIA_CLEAN),
        "gaia_clean_report_ranks": gaia_clean_report == EXPECTED_GAIA_CLEAN,
        "gaia_clean_csv_ranks": gaia_clean_rows == EXPECTED_GAIA_CLEAN,
        "gaia_no_detector": gaia_report.get("detector_rerun") is False,
        "gaia_no_pixels": gaia_report.get("pixels_read") is False,
        "gaia_amendment_present": bool(amendment),
        "gaia_amendment_no_retune":
            amendment.get("science_thresholds_retuned") is False,
        "gaia_amendment_3arcsec_unchanged":
            amendment.get("static_gate_3arcsec_unchanged") is True,
        "gaia_amendment_5arcsec_unchanged":
            amendment.get("diagnostic_gate_5arcsec_unchanged") is True,
    }
    if not all(guards.values()):
        raise RuntimeError(
            "REFUSING: completed-stage guard failure: "
            + json.dumps(guards, sort_keys=True)
        )

    by_rank = {int(r["strict_rank"]): r for r in gaia_rows}
    if len(by_rank) != EXPECTED_STRICT3:
        raise RuntimeError(
            f"REFUSING: expected {EXPECTED_STRICT3} unique Gaia triage rows, "
            f"got {len(by_rank)}"
        )

    print("Completed-stage guards: PASS")
    print(f"Corrected Gaia-clean input: {len(EXPECTED_GAIA_CLEAN)}")
    print(
        f'PS1 policy: DR2 mean; nDetections>={MIN_DETECTIONS}; '
        f'query radius={QUERY_RADIUS_ARCSEC:.0f}"; '
        f'strong={STATIC_STRONG_ARCSEC:.0f}"; '
        f'diagnostic={STATIC_DIAGNOSTIC_ARCSEC:.0f}"'
    )
    print("PS1 proper motion is recorded but NOT used for rejection.")
    print()

    pair_rows = []
    all_sources = []
    query_audit = []

    for i, rank in enumerate(EXPECTED_GAIA_CLEAN, 1):
        g = by_rank[rank]

        p = SkyCoord(
            ra=float(g["poss_ra_deg"]) * u.deg,
            dec=float(g["poss_dec_deg"]) * u.deg,
            frame="icrs",
        )
        d = SkyCoord(
            ra=float(g["dasch_ra_deg"]) * u.deg,
            dec=float(g["dasch_dec_deg"]) * u.deg,
            frame="icrs",
        )
        mid = midpoint_coord(p, d)

        rows, meta, status = query_ps1(
            float(mid.ra.deg),
            float(mid.dec.deg),
            rank,
        )

        cls, within3, within5, nearest, audit_sources = classify(
            rows, p, d, mid, rank
        )
        all_sources.extend(audit_sources)
        query_audit.append({
            "strict_rank": rank,
            "status": status,
            **meta,
        })

        def nv(key):
            return None if nearest is None else nearest.get(key)

        pair_rows.append({
            "strict_rank": rank,
            "gaia_class": g["gaia_class"],
            "pair_separation_arcsec": float(g["pair_separation_arcsec"]),
            "poss_ra_deg": float(g["poss_ra_deg"]),
            "poss_dec_deg": float(g["poss_dec_deg"]),
            "dasch_ra_deg": float(g["dasch_ra_deg"]),
            "dasch_dec_deg": float(g["dasch_dec_deg"]),
            "poss_snr": float(g["poss_snr"]),
            "dasch_snr": float(g["dasch_snr"]),
            "poss_polarity": int(float(g["poss_polarity"])),
            "dasch_polarity": int(float(g["dasch_polarity"])),
            "same_polarity": as_bool(g["same_polarity"]),
            "ps1_class": cls,
            "ps1_within_3arcsec": within3,
            "ps1_within_5arcsec": within5,
            "ps1_nearest_objid": nv("objID"),
            "ps1_nearest_sep_mid_arcsec": nv("sep_mid_arcsec"),
            "ps1_nearest_sep_poss_arcsec": nv("sep_poss_arcsec"),
            "ps1_nearest_sep_dasch_arcsec": nv("sep_dasch_arcsec"),
            "ps1_nearest_nDetections": nv("nDetections"),
            "ps1_nearest_qualityFlag": nv("qualityFlag"),
            "ps1_nearest_raMean_deg": nv("raMean"),
            "ps1_nearest_decMean_deg": nv("decMean"),
            "ps1_nearest_epochMean_mjd": nv("epochMean"),
            "ps1_nearest_pmra_masyr": nv("pmra"),
            "ps1_nearest_pmdec_masyr": nv("pmdec"),
            "ps1_nearest_gMeanPSFMag": nv("gMeanPSFMag"),
            "ps1_nearest_rMeanPSFMag": nv("rMeanPSFMag"),
            "ps1_nearest_iMeanPSFMag": nv("iMeanPSFMag"),
            "ps1_nearest_zMeanPSFMag": nv("zMeanPSFMag"),
            "ps1_nearest_yMeanPSFMag": nv("yMeanPSFMag"),
            "ps1_returned_rows": len(rows),
            "survives_gaia_and_ps1_3arcsec": not within3,
            "survives_gaia_and_ps1_5arcsec": not within5,
        })

        nearest_text = (
            "none"
            if nearest is None
            else (
                f'{nearest["sep_mid_arcsec"]:.3f}" '
                f'nDet={nearest["nDetections"]}'
            )
        )

        print(
            f"  [{i:02d}/{len(EXPECTED_GAIA_CLEAN):02d}] "
            f"strict #{rank:02d} "
            f"{status.upper():6s} rows={len(rows):3d} "
            f"nearest={nearest_text:>18s} {cls}",
            flush=True,
        )

    write_csv(OUT, pair_rows, PAIR_FIELDS)
    write_csv(OUT_SOURCES, all_sources, SOURCE_FIELDS)

    strong = sum(as_bool(r["ps1_within_3arcsec"]) for r in pair_rows)
    diag_any = sum(as_bool(r["ps1_within_5arcsec"]) for r in pair_rows)

    survive3 = [
        r for r in pair_rows
        if as_bool(r["survives_gaia_and_ps1_3arcsec"])
    ]
    survive5 = [
        r for r in pair_rows
        if as_bool(r["survives_gaia_and_ps1_5arcsec"])
    ]

    out_report = {
        "status": "COMPLETE",
        "analysis_kind": "order01_ps1_dr2_independent_static_repeated_source_v028",
        "catalog": "Pan-STARRS DR2 mean",
        "api": API,
        "guards": guards,
        "input_gaia_report": str(GAIA_REPORT),
        "input_gaia_report_sha256": sha_file(GAIA_REPORT),
        "input_gaia_triage": str(GAIA_TRIAGE),
        "input_gaia_triage_sha256": sha_file(GAIA_TRIAGE),
        "input_gaia_clean_count": len(pair_rows),
        "input_gaia_clean_ranks": EXPECTED_GAIA_CLEAN,
        "fixed_policy": {
            "policy_origin": "completed_order61_ps1_stage",
            "https_transport": "curl_verified_https",
            "tls_verification_disabled": False,
            "query_radius_arcsec": QUERY_RADIUS_ARCSEC,
            "minimum_nDetections": MIN_DETECTIONS,
            "strong_static_arcsec": STATIC_STRONG_ARCSEC,
            "diagnostic_static_arcsec": STATIC_DIAGNOSTIC_ARCSEC,
            "classification_coordinate": "nearest_ps1_mean_object_to_pair_midpoint",
            "endpoint_separations_retained_for_audit": True,
            "ps1_proper_motion_used_for_rejection": False,
            "reason": (
                "This is an independent modern repeated-source positional check. "
                "Corrected Gaia v028b already supplies the historical-epoch "
                "proper-motion safety screen."
            ),
        },
        "ps1_within_3arcsec_count": strong,
        "ps1_within_5arcsec_count": diag_any,
        "gaia_and_ps1_3arcsec_survivor_count": len(survive3),
        "gaia_and_ps1_5arcsec_survivor_count": len(survive5),
        "survivor_ranks_3arcsec": [
            int(r["strict_rank"]) for r in survive3
        ],
        "survivor_ranks_5arcsec": [
            int(r["strict_rank"]) for r in survive5
        ],
        "query_audit": query_audit,
        "no_candidate_deleted": True,
        "detector_rerun": False,
        "image_pixels_read": False,
        "next_stage": (
            "For Gaia+PS1 5-arcsec survivors, run native endpoint morphology "
            "against SNR-matched same-tile peers before historical recurrence "
            "or Branch-C escalation. Keep Branch-A and any later Branch-C "
            "candidate identities separate."
        ),
        "outputs": {
            "pair_triage_csv": str(OUT),
            "all_returned_sources_csv": str(OUT_SOURCES),
        },
    }
    write_json(OUT_REPORT, out_report)

    print()
    print("=" * 94)
    print("ORDER 01 PAN-STARRS STATIC / REPEATED-SOURCE CHECK COMPLETE")
    print("=" * 94)
    print(f"Gaia-clean input:                  {len(pair_rows)}")
    print(f'PS1 repeated source within 3":     {strong}')
    print(f'PS1 repeated source within 5":     {diag_any}')
    print(f'Survive Gaia+PS1 3" gate:          {len(survive3)}')
    print(f'Survive Gaia+PS1 5" diagnostic:    {len(survive5)}')
    print(
        f'Gaia+PS1 5" survivor ranks:        '
        f'{[int(r["strict_rank"]) for r in survive5]}'
    )
    print()

    print("Cases:")
    for r in pair_rows:
        sep = r["ps1_nearest_sep_mid_arcsec"]
        septext = "none" if sep is None else f'{float(sep):.3f}"'
        print(
            f"  strict #{int(r['strict_rank']):02d} "
            f"PS1={r['ps1_class']:<31s} "
            f"nearest={septext:>8s} "
            f"P/D SNR={float(r['poss_snr']):.2f}/{float(r['dasch_snr']):.2f} "
            f"pol={'same' if as_bool(r['same_polarity']) else 'opp'}"
        )

    print()
    print("Outputs:")
    print(" ", OUT_REPORT)
    print(" ", OUT)
    print(" ", OUT_SOURCES)
    print()
    print("No detector was rerun.")
    print("No science image pixel was read.")
    print("No candidate was deleted or promoted.")


if __name__ == "__main__":
    main()
