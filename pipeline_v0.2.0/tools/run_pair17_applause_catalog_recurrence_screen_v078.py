#!/usr/bin/env python3
"""
v078 — Pair 17 APPLAUSE DR4 catalogue recurrence screen.

Uses applause_dr4.source_calib only. No comparison FITS pixels are read.
All 603 frozen pair-17 associations are queried. Candidate-specific results
are filtered to the frozen v077a independent physical-plate opportunity universe.

This is a resumable catalogue stage. It does not change candidate dispositions.
"""

from pathlib import Path
from io import BytesIO
from collections import Counter, defaultdict
import csv
import hashlib
import json
import math
import time
import urllib.error
import urllib.parse
import urllib.request

import numpy as np
import pandas as pd
from astropy.table import Table

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "results"
RESEARCH = ROOT / "research"

CONTRACT = (
    RESEARCH / "prospective_freezes"
    / "pair17_applause_catalog_recurrence_screen_contract_v078.json"
)
V075 = (
    RESULTS / "pair17_epoch_aware_gaia_static_triage_v075"
    / "pair17_epoch_aware_gaia_static_triage_v075.csv"
)
V077A = RESULTS / "pair17_applause_independent_plate_opportunity_census_v077a"
OPPS = V077A / "pair17_candidate_plate_opportunities_v077a.csv"
V077A_SUMMARY = V077A / "pair17_applause_independent_plate_opportunity_census_v077a.json"
V077A_PLATES = V077A / "pair17_independent_plate_inventory_v077a.csv"
V077A_TAP = V077A / "pair17_tap_query_manifest_v077a.csv"
V077A_BANK = V077A / "pair17_v077a_bank_manifest.json"

OUT = RESULTS / "pair17_applause_catalog_recurrence_screen_v078"
CACHE = OUT / "cache"

OUT_SUMMARY = OUT / "pair17_catalog_recurrence_candidate_summary_v078.csv"
OUT_PLATE = OUT / "pair17_catalog_recurrence_plate_nearest_v078.csv"
OUT_RAW = OUT / "pair17_catalog_recurrence_raw_rows_v078.csv"
OUT_QUERY = OUT / "pair17_catalog_recurrence_query_manifest_v078.csv"
OUT_QUEUE = OUT / "pair17_pixel_followup_queue_v078.csv"
OUT_JSON = OUT / "pair17_applause_catalog_recurrence_screen_v078.json"

EXPECTED_CONTRACT_SHA = "1828bb4369bc1ea40d75561919b7d57bba672e44374ebdbc7689cbdecc1d5397"
EXPECTED_SHA = {
    V075:
        "cc571a4da103dc3900907fe9568567dd540f8f85217b7e7e73ca4442239f2097",
    OPPS:
        "f8bd8a1bc322d0a9dc0239e29f676975f8ff692e17e040e2786cc196caf24b1d",
    V077A_SUMMARY:
        "2e9872fc777d22e9f14bac51e4460abdba7d38352400fab095d36de0df2cd4b2",
    V077A_PLATES:
        "db37816fca8ad3214347d816d52618e9bb97537cf41660386fe6c1c7b7eaa1b1",
    V077A_TAP:
        "53aa4ec0d969c523a52fcf2324399a6848f6473b2d8f90859b082ea498c05c08",
    V077A_BANK:
        "86545f2e4fa228c9472665bfe59ba7625314c548c0117bc00442265d8a1e97ef",
}

TAP_SYNC = "https://www.plate-archive.org/tap/sync"
UA = "historical-transient-pipeline/pair17-v078-catalog-recurrence"
TIMEOUT = 180
MAX_ATTEMPTS = 5
MAXREC = 200000

EXPECTED_TOTAL = 603
EXPECTED_PRIMARY = 424
EXPECTED_DIAGNOSTIC = 179

ACQ_ARCSEC = 15.0
STRICT_ARCSEC = 3.0
DIAG_ARCSEC = 5.0


def sha256(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for block in iter(lambda: f.read(8 * 1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def sha_bytes(b):
    return hashlib.sha256(b).hexdigest()


def fail(msg):
    raise RuntimeError(msg)


def ffloat(v):
    try:
        x = float(v)
    except Exception:
        return None
    return x if math.isfinite(x) else None


def fint(v):
    try:
        return int(str(v).strip())
    except Exception:
        try:
            x = float(v)
            if math.isfinite(x) and x.is_integer():
                return int(x)
        except Exception:
            pass
    return None


def unit_vector(ra_deg, dec_deg):
    ra = math.radians(float(ra_deg))
    dec = math.radians(float(dec_deg))
    c = math.cos(dec)
    return np.array(
        [c * math.cos(ra), c * math.sin(ra), math.sin(dec)],
        dtype=float,
    )


def vector_to_radec(v):
    v = np.asarray(v, dtype=float)
    n = np.linalg.norm(v)
    if not math.isfinite(float(n)) or n <= 0:
        fail("Invalid spherical vector")
    v = v / n
    ra = math.degrees(math.atan2(v[1], v[0])) % 360.0
    dec = math.degrees(math.asin(max(-1.0, min(1.0, float(v[2])))))
    return ra, dec


def midpoint(ra1, dec1, ra2, dec2):
    return vector_to_radec(
        unit_vector(ra1, dec1) + unit_vector(ra2, dec2)
    )


def sep_arcsec(ra1, dec1, ra2, dec2):
    a = unit_vector(ra1, dec1)
    b = unit_vector(ra2, dec2)
    dot = max(-1.0, min(1.0, float(np.dot(a, b))))
    return math.degrees(math.acos(dot)) * 3600.0


def table_rows(tbl):
    rows = []
    for tr in tbl:
        d = {}
        for name in tbl.colnames:
            v = tr[name]
            if np.ma.is_masked(v):
                d[name] = ""
            elif isinstance(v, bytes):
                d[name] = v.decode("utf-8", errors="replace")
            elif isinstance(v, np.generic):
                d[name] = v.item()
            else:
                d[name] = v
        rows.append(d)
    return rows


def votable_overflow(raw):
    s = raw.decode("utf-8", errors="ignore").upper()
    return (
        'VALUE="OVERFLOW"' in s
        or "VALUE='OVERFLOW'" in s
        or ">OVERFLOW<" in s
    )


def atomic_json(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(obj, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )
    tmp.replace(path)


def atomic_csv(path, rows, fields):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    tmp.replace(path)


def source_query(ra, dec):
    radius_deg = ACQ_ARCSEC / 3600.0
    return f"""SELECT
  source_id,
  process_id,
  scan_id,
  plate_id,
  archive_id,
  solution_num,
  sextractor_flags,
  model_prediction,
  ra_icrs,
  dec_icrs,
  ra_error,
  dec_error,
  natmag,
  natmag_error,
  phot_range_flags,
  phot_calib_flags,
  gaiaedr3_id,
  gaiaedr3_dist,
  gaiaedr3_neighbors,
  match_radius
FROM applause_dr4.source_calib
WHERE 1 = CONTAINS(
  POINT('ICRS', ra_icrs, dec_icrs),
  CIRCLE('ICRS', {ra:.12f}, {dec:.12f}, {radius_deg:.12f})
)
ORDER BY plate_id, source_id
"""


def tap_query_candidate(raw_match_row, query):
    CACHE.mkdir(parents=True, exist_ok=True)

    stem = f"candidate_{int(raw_match_row):06d}"
    qpath = CACHE / f"{stem}.adql"
    xpath = CACHE / f"{stem}.vot"
    mpath = CACHE / f"{stem}.meta.json"

    qsha = sha_bytes(query.encode("utf-8"))

    if qpath.is_file() and xpath.is_file() and mpath.is_file():
        oldq = qpath.read_text(encoding="utf-8")
        meta = json.loads(mpath.read_text(encoding="utf-8"))
        raw = xpath.read_bytes()

        if (
            oldq == query
            and meta.get("query_sha256") == qsha
            and meta.get("status") == "COMPLETE"
        ):
            if votable_overflow(raw):
                fail(f"{stem}: cached VOTable overflow")
            tbl = Table.read(BytesIO(raw), format="votable")
            return table_rows(tbl), {
                **meta,
                "cached": True,
                "raw_votable_sha256": sha_bytes(raw),
            }

    payload = urllib.parse.urlencode({
        "REQUEST": "doQuery",
        "LANG": "ADQL",
        "FORMAT": "votable",
        "RESPONSEFORMAT": "votable",
        "MAXREC": str(MAXREC),
        "QUERY": query,
    }).encode("utf-8")

    last = None

    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            req = urllib.request.Request(
                TAP_SYNC,
                data=payload,
                method="POST",
                headers={
                    "Accept": "application/x-votable+xml,text/xml,*/*",
                    "Content-Type": "application/x-www-form-urlencoded",
                    "User-Agent": UA,
                    "Cache-Control": "no-cache",
                },
            )

            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                raw = resp.read()
                status = int(getattr(resp, "status", 200))
                final_url = resp.geturl()
                ctype = resp.headers.get("Content-Type", "")

            if votable_overflow(raw):
                fail(
                    f"{stem}: APPLAUSE source_calib query overflowed MAXREC={MAXREC}"
                )

            tbl = Table.read(BytesIO(raw), format="votable")
            rows = table_rows(tbl)

            qpath.write_text(query, encoding="utf-8", newline="\n")
            xpath.write_bytes(raw)

            meta = {
                "status": "COMPLETE",
                "raw_match_row": str(raw_match_row),
                "query_sha256": qsha,
                "raw_votable_sha256": sha_bytes(raw),
                "row_count": len(rows),
                "http_status": status,
                "final_url": final_url,
                "content_type": ctype,
                "attempt": attempt,
                "cached": False,
            }
            atomic_json(mpath, meta)
            return rows, meta

        except urllib.error.HTTPError as exc:
            try:
                body = exc.read(6000).decode("utf-8", errors="replace")
            except Exception:
                body = ""
            last = RuntimeError(
                f"HTTP {exc.code} {exc.reason}; body={body!r}"
            )
            if int(exc.code) not in {408, 429, 500, 502, 503, 504}:
                break
        except Exception as exc:
            last = exc

        if attempt < MAX_ATTEMPTS:
            time.sleep(min(20.0, 2.0 ** attempt))

    raise RuntimeError(
        f"{stem}: source_calib TAP failed: {type(last).__name__}: {last}"
    ) from last


def load_opportunity_sets():
    # 190 MB file: stream only the fields needed for candidate-specific filtering.
    by_candidate = defaultdict(set)

    with OPPS.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)

        required = {
            "raw_match_row",
            "physical_opportunity_plate_id",
        }
        if not required.issubset(reader.fieldnames or []):
            fail(
                f"Unexpected v077a opportunity schema; missing "
                f"{sorted(required - set(reader.fieldnames or []))}"
            )

        rows = 0
        for r in reader:
            rid = str(r["raw_match_row"]).strip()
            pid = fint(r["physical_opportunity_plate_id"])
            if not rid or pid is None:
                fail("Invalid v077a candidate/plate opportunity identity")
            by_candidate[rid].add(pid)
            rows += 1

    if rows != 350717 + 145292:
        fail(
            f"v077a candidate x plate row count changed: "
            f"{rows} != 496009"
        )

    return by_candidate, rows


def classify_candidate(strict_n, diag_n, wide_n, query_ok=True):
    if not query_ok:
        return "CATALOG_QUERY_UNRESOLVED"
    if strict_n >= 2:
        return "STRICT_RECURRENCE_ON_2PLUS_PHYSICAL_PLATES"
    if strict_n == 1:
        return "STRICT_RECURRENCE_ON_1_PHYSICAL_PLATE"
    if diag_n > 0:
        return "DIAGNOSTIC_RECURRENCE_ONLY"
    if wide_n > 0:
        return "WIDE_5_TO_15_ARCSEC_CONTEXT_ONLY"
    return "NO_APPLAUSE_SOURCE_CALIB_WITHIN_15_ARCSEC_ON_ELIGIBLE_PLATES"


def main():
    print("=" * 132)
    print("PAIR 17 — APPLAUSE DR4 CATALOGUE RECURRENCE SCREEN v078")
    print("=" * 132)
    print("All 603 frozen associations.")
    print("Comparison FITS pixels: NO")
    print("Injection/recovery:     NO")
    print("Detector rerun:         NO")
    print("Disposition changes:    NONE")
    print()

    if not CONTRACT.is_file():
        fail(f"Missing frozen v078 contract: {CONTRACT}")

    if sha256(CONTRACT) != EXPECTED_CONTRACT_SHA:
        fail("v078 contract SHA mismatch")

    for p, expected in EXPECTED_SHA.items():
        if not p.is_file():
            fail(f"Missing frozen v078 input: {p}")
        actual = sha256(p)
        if actual != expected:
            fail(
                f"Frozen input SHA mismatch:\n{p}\n"
                f"expected {expected}\nactual   {actual}"
            )
        print("HASH PASS:", p.relative_to(ROOT))

    targets = pd.read_csv(V075, dtype=str, keep_default_na=False)

    if len(targets) != EXPECTED_TOTAL:
        fail(f"v075 population changed: {len(targets)}")

    pops = Counter(targets["population"].astype(str))
    if pops.get("PRIMARY_424", 0) != EXPECTED_PRIMARY:
        fail(f"PRIMARY count changed: {pops}")
    if pops.get("DIAGNOSTIC_179", 0) != EXPECTED_DIAGNOSTIC:
        fail(f"DIAGNOSTIC count changed: {pops}")

    needed = {
        "raw_match_row", "population",
        "a_ra_deg", "a_dec_deg",
        "b_ra_deg", "b_dec_deg",
    }
    if not needed.issubset(targets.columns):
        fail(f"v075 required coordinate fields missing: {needed - set(targets.columns)}")

    opps, opp_rows_n = load_opportunity_sets()

    if len(opps) != EXPECTED_TOTAL:
        fail(f"v077a opportunity candidate count changed: {len(opps)}")

    print()
    print(f"Frozen opportunity rows: {opp_rows_n:,}")
    print(f"Candidates with opportunity sets: {len(opps)}")

    summary_rows = []
    query_rows = []
    followup_rows = []

    raw_fields = [
        "raw_match_row", "population", "target_ra_deg", "target_dec_deg",
        "eligible_physical_plate_id", "source_id", "process_id", "scan_id",
        "archive_id", "solution_num", "source_ra_icrs", "source_dec_icrs",
        "separation_arcsec", "sextractor_flags", "model_prediction",
        "ra_error", "dec_error", "natmag", "natmag_error",
        "phot_range_flags", "phot_calib_flags", "gaiaedr3_id",
        "gaiaedr3_dist", "gaiaedr3_neighbors", "match_radius",
    ]
    plate_fields = raw_fields + [
        "plate_recurrence_class",
        "source_rows_on_plate_within_acquisition",
    ]

    OUT.mkdir(parents=True, exist_ok=True)
    raw_tmp = OUT_RAW.with_suffix(OUT_RAW.suffix + ".tmp")
    plate_tmp = OUT_PLATE.with_suffix(OUT_PLATE.suffix + ".tmp")
    raw_count = 0
    plate_count = 0

    with raw_tmp.open("w", encoding="utf-8", newline="") as raw_f, \
         plate_tmp.open("w", encoding="utf-8", newline="") as plate_f:
        raw_writer = csv.DictWriter(raw_f, fieldnames=raw_fields, extrasaction="ignore")
        plate_writer = csv.DictWriter(plate_f, fieldnames=plate_fields, extrasaction="ignore")
        raw_writer.writeheader()
        plate_writer.writeheader()

        # One candidate at a time keeps the stage resumable through the cache.
        for i, (_, tr) in enumerate(targets.iterrows(), 1):
            rid = str(tr["raw_match_row"])
            pop = str(tr["population"])

            vals = [
                ffloat(tr["a_ra_deg"]),
                ffloat(tr["a_dec_deg"]),
                ffloat(tr["b_ra_deg"]),
                ffloat(tr["b_dec_deg"]),
            ]
            if any(v is None for v in vals):
                fail(f"Non-finite v075 coordinates raw_match_row={rid}")

            ra, dec = midpoint(*vals)

            eligible_plates = opps.get(rid)
            if not eligible_plates:
                fail(f"No frozen v077a opportunity set raw_match_row={rid}")

            query = source_query(ra, dec)
            rows, qmeta = tap_query_candidate(rid, query)

            query_rows.append({
                "raw_match_row": rid,
                "population": pop,
                "target_ra_deg": ra,
                "target_dec_deg": dec,
                "query_sha256": qmeta["query_sha256"],
                "raw_votable_sha256": qmeta["raw_votable_sha256"],
                "raw_query_row_count": qmeta["row_count"],
                "cached": qmeta.get("cached", False),
                "http_status": qmeta.get("http_status", ""),
            })

            per_plate = defaultdict(list)

            for r in rows:
                pid = fint(r.get("plate_id"))
                rra = ffloat(r.get("ra_icrs"))
                rdec = ffloat(r.get("dec_icrs"))

                if pid is None or rra is None or rdec is None:
                    continue
                if pid not in eligible_plates:
                    continue

                sep = sep_arcsec(ra, dec, rra, rdec)

                rr = {
                    "raw_match_row": rid,
                    "population": pop,
                    "target_ra_deg": ra,
                    "target_dec_deg": dec,
                    "eligible_physical_plate_id": pid,
                    "source_id": str(r.get("source_id") or ""),
                    "process_id": str(r.get("process_id") or ""),
                    "scan_id": str(r.get("scan_id") or ""),
                    "archive_id": str(r.get("archive_id") or ""),
                    "solution_num": str(r.get("solution_num") or ""),
                    "source_ra_icrs": rra,
                    "source_dec_icrs": rdec,
                    "separation_arcsec": sep,
                    "sextractor_flags": str(r.get("sextractor_flags") or ""),
                    "model_prediction": str(r.get("model_prediction") or ""),
                    "ra_error": str(r.get("ra_error") or ""),
                    "dec_error": str(r.get("dec_error") or ""),
                    "natmag": str(r.get("natmag") or ""),
                    "natmag_error": str(r.get("natmag_error") or ""),
                    "phot_range_flags": str(r.get("phot_range_flags") or ""),
                    "phot_calib_flags": str(r.get("phot_calib_flags") or ""),
                    "gaiaedr3_id": str(r.get("gaiaedr3_id") or ""),
                    "gaiaedr3_dist": str(r.get("gaiaedr3_dist") or ""),
                    "gaiaedr3_neighbors": str(r.get("gaiaedr3_neighbors") or ""),
                    "match_radius": str(r.get("match_radius") or ""),
                }

                raw_writer.writerow(rr)
                raw_count += 1
                per_plate[pid].append(rr)

            nearest = []

            for pid in sorted(per_plate):
                q = sorted(
                    per_plate[pid],
                    key=lambda r: (
                        float(r["separation_arcsec"]),
                        str(r["source_id"]),
                    ),
                )
                best = dict(q[0])

                s = float(best["separation_arcsec"])
                if s <= STRICT_ARCSEC:
                    cls = "STRICT_LE3"
                elif s <= DIAG_ARCSEC:
                    cls = "DIAGNOSTIC_GT3_LE5"
                elif s <= ACQ_ARCSEC:
                    cls = "WIDE_GT5_LE15"
                else:
                    # The TAP cone should prevent this except for floating precision.
                    cls = "OUTSIDE_ACQUISITION"

                best["plate_recurrence_class"] = cls
                best["source_rows_on_plate_within_acquisition"] = len(q)
                plate_writer.writerow(best)
                plate_count += 1
                nearest.append(best)

            strict = [r for r in nearest if r["plate_recurrence_class"] == "STRICT_LE3"]
            diag = [
                r for r in nearest
                if r["plate_recurrence_class"] == "DIAGNOSTIC_GT3_LE5"
            ]
            wide = [
                r for r in nearest
                if r["plate_recurrence_class"] == "WIDE_GT5_LE15"
            ]

            gaia_counts = Counter(
                str(r["gaiaedr3_id"]).strip()
                for r in strict
                if str(r["gaiaedr3_id"]).strip()
                not in {"", "0", "None", "none", "nan", "--"}
            )

            repeated_gaia = {
                k: v for k, v in gaia_counts.items() if v >= 2
            }

            cclass = classify_candidate(
                len(strict), len(diag), len(wide), query_ok=True
            )

            best_sep = (
                min(float(r["separation_arcsec"]) for r in nearest)
                if nearest else None
            )

            summary = {
                "raw_match_row": rid,
                "population": pop,
                "target_ra_deg": ra,
                "target_dec_deg": dec,
                "eligible_physical_plate_count": len(eligible_plates),
                "raw_source_calib_rows_in_15arcsec": len(rows),
                "eligible_source_calib_rows_in_15arcsec":
                    sum(len(v) for v in per_plate.values()),
                "physical_plates_with_any_source_within_15arcsec": len(nearest),
                "strict_physical_plate_recurrence_count": len(strict),
                "diagnostic_physical_plate_recurrence_count": len(diag),
                "wide_5_to_15_physical_plate_context_count": len(wide),
                "best_eligible_separation_arcsec": best_sep,
                "distinct_nonnull_gaiaedr3_ids_on_strict_plates":
                    len(gaia_counts),
                "gaiaedr3_ids_repeated_on_2plus_strict_plates":
                    ";".join(
                        f"{k}:{v}"
                        for k, v in sorted(
                            repeated_gaia.items(),
                            key=lambda kv: (-kv[1], kv[0]),
                        )
                    ),
                "catalog_recurrence_class": cclass,
                "candidate_disposition_changed": False,
            }
            summary_rows.append(summary)

            if len(strict) < 2:
                followup_rows.append({
                    "raw_match_row": rid,
                    "population": pop,
                    "catalog_recurrence_class": cclass,
                    "strict_physical_plate_recurrence_count": len(strict),
                    "diagnostic_physical_plate_recurrence_count": len(diag),
                    "eligible_physical_plate_count": len(eligible_plates),
                    "pixel_followup_required_by_frozen_v078_branch": True,
                })

            if i % 25 == 0 or i == EXPECTED_TOTAL:
                print(
                    f"Processed {i}/{EXPECTED_TOTAL} candidates; "
                    f"PRIMARY/DIAGNOSTIC unfiltered; "
                    f"pixel-followup queue so far={len(followup_rows)}",
                    flush=True,
                )

    raw_tmp.replace(OUT_RAW)
    plate_tmp.replace(OUT_PLATE)

    if len(summary_rows) != EXPECTED_TOTAL:
        fail(f"Candidate summary row count changed: {len(summary_rows)}")

    def agg(pop):
        q = [r for r in summary_rows if r["population"] == pop]
        return {
            "n": len(q),
            "class_counts": dict(sorted(Counter(
                r["catalog_recurrence_class"] for r in q
            ).items())),
            "candidates_with_2plus_strict_physical_plate_recurrences":
                sum(
                    int(r["strict_physical_plate_recurrence_count"]) >= 2
                    for r in q
                ),
            "candidates_with_any_strict_physical_plate_recurrence":
                sum(
                    int(r["strict_physical_plate_recurrence_count"]) >= 1
                    for r in q
                ),
            "pixel_followup_required":
                sum(
                    int(r["strict_physical_plate_recurrence_count"]) < 2
                    for r in q
                ),
        }

    summary_fields = list(summary_rows[0].keys())
    query_fields = list(query_rows[0].keys())
    queue_fields = list(followup_rows[0].keys()) if followup_rows else [
        "raw_match_row", "population"
    ]

    atomic_csv(OUT_SUMMARY, summary_rows, summary_fields)
    atomic_csv(OUT_QUERY, query_rows, query_fields)
    atomic_csv(OUT_QUEUE, followup_rows, queue_fields)

    report = {
        "status": "COMPLETE",
        "analysis_kind": "pair17_applause_catalog_recurrence_screen_v078",
        "contract_sha256": EXPECTED_CONTRACT_SHA,
        "population": {
            "all": EXPECTED_TOTAL,
            "primary": EXPECTED_PRIMARY,
            "diagnostic": EXPECTED_DIAGNOSTIC,
            "gaia_subsetting": False,
            "morphology_subsetting": False,
        },
        "method": {
            "catalogue": "applause_dr4.source_calib",
            "acquisition_radius_arcsec": ACQ_ARCSEC,
            "strict_radius_arcsec": STRICT_ARCSEC,
            "diagnostic_radius_arcsec": DIAG_ARCSEC,
            "physical_plate_counting_unit": True,
            "filter_to_v077a_opportunity_universe": True,
            "streamed_raw_catalog_rows": raw_count,
            "streamed_plate_nearest_rows": plate_count,
        },
        "aggregate": {
            "PRIMARY_424": agg("PRIMARY_424"),
            "DIAGNOSTIC_179": agg("DIAGNOSTIC_179"),
            "ALL_603": {
                "n": EXPECTED_TOTAL,
                "class_counts": dict(sorted(Counter(
                    r["catalog_recurrence_class"] for r in summary_rows
                ).items())),
                "pixel_followup_required": len(followup_rows),
            },
        },
        "guards": {
            "comparison_pixels_read": 0,
            "injection_measurements": 0,
            "detector_rerun": False,
            "registration_rerun": False,
            "manual_review": False,
            "candidate_disposition_changes": False,
        },
        "interpretation": {
            "catalogue_absence_is_transience": False,
            "two_plus_strict_physical_plate_recurrences":
                "strong persistent-source contextual support",
            "pixel_followup_branch":
                "all candidates with fewer than two strict physical-plate recurrences",
        },
        "outputs": {
            "candidate_summary": str(OUT_SUMMARY.relative_to(ROOT)).replace("\\", "/"),
            "plate_level_nearest": str(OUT_PLATE.relative_to(ROOT)).replace("\\", "/"),
            "raw_catalog_rows": str(OUT_RAW.relative_to(ROOT)).replace("\\", "/"),
            "query_manifest": str(OUT_QUERY.relative_to(ROOT)).replace("\\", "/"),
            "pixel_followup_queue": str(OUT_QUEUE.relative_to(ROOT)).replace("\\", "/"),
        },
    }

    atomic_json(OUT_JSON, report)

    print()
    print("=" * 132)
    print("v078 CATALOGUE RECURRENCE SCREEN COMPLETE")
    print("=" * 132)

    for pop in ("PRIMARY_424", "DIAGNOSTIC_179"):
        a = report["aggregate"][pop]
        print(pop)
        for k, v in a["class_counts"].items():
            print(f"  {k}: {v}")
        print(
            "  any strict recurrence: "
            f"{a['candidates_with_any_strict_physical_plate_recurrence']}"
        )
        print(
            "  2+ strict physical plates: "
            f"{a['candidates_with_2plus_strict_physical_plate_recurrences']}"
        )
        print(
            "  frozen pixel-followup branch: "
            f"{a['pixel_followup_required']}"
        )

    print()
    print("Comparison FITS pixels read:       0")
    print("Injection measurements performed:  0")
    print("Detector reruns:                   0")
    print("Candidate dispositions changed:    NONE")
    print("STAGE STATUS: COMPLETE")


if __name__ == "__main__":
    main()
