#!/usr/bin/env python3
"""
Pair-17 v080 native-pixel preflight.

READ-ONLY / HEADER-ONLY.
This is deliberately not a scientific execution and is not a v080 contract.
It verifies the exact schemas and local FITS/WCS layout needed before freezing
the first comparison-pixel recurrence/sensitivity stage.

Guards:
- no FITS pixel array access
- no detector calls
- no injection
- no recurrence measurement
- no candidate disposition changes
- no network
"""

from pathlib import Path
from collections import Counter, defaultdict
import csv
import hashlib
import json
import math
import re
import sys

from astropy.io import fits
from astropy.wcs import WCS

ROOT = Path(__file__).resolve().parents[1]

V079 = (
    ROOT / "results"
    / "pair17_pixel_followup_scan_plan_and_acquisition_v079"
)

PLAN = V079 / "pair17_candidate_comparison_plan_v079.csv"
QUEUE = V079 / "pair17_unique_scan_acquisition_queue_v079.csv"
URLS = V079 / "pair17_scan_url_resolution_manifest_v079.csv"
ACQ = V079 / "pair17_scan_acquisition_manifest_v079.csv"
REPORT = V079 / "pair17_pixel_followup_scan_plan_and_acquisition_v079.json"
BANK = V079 / "pair17_v079b_bank_manifest.json"

V078 = (
    ROOT / "results"
    / "pair17_applause_catalog_recurrence_screen_v078"
)
V078_QUEUE = V078 / "pair17_pixel_followup_queue_v078.csv"
V078_SUMMARY = V078 / "pair17_catalog_recurrence_candidate_summary_v078.csv"

V077A = (
    ROOT / "results"
    / "pair17_applause_independent_plate_opportunity_census_v077a"
)
V077_OPPS = V077A / "pair17_candidate_plate_opportunities_v077a.csv"

V075 = (
    ROOT / "results"
    / "pair17_epoch_aware_gaia_static_triage_v075"
    / "pair17_epoch_aware_gaia_static_triage_v075.csv"
)

OUTDIR = ROOT / "results" / "pair17_native_pixel_preflight_v080"
OUT_JSON = OUTDIR / "pair17_native_pixel_preflight_v080.json"

EXPECTED = {
    REPORT:
        "a6695398285882ef13e8f67cf04955fb4b6c6b2f8fd7cf58f0580ad18aec635d",
    PLAN:
        "9794ee6dc3eebd91281a46af25f0025da86492dde2aeb0e44f04ae3292a3d356",
    QUEUE:
        "4c47a647befc4cc801aebfb505588f13373dcc12b731cf2ed2d6c5204f2875cc",
    URLS:
        "c09b43a17f2524cd1267f12b0be0de3f420ebf903e7a695bc852d5680d94ec32",
    ACQ:
        "392e73303d01f20a386627e8a743c4a6769e31deb5a4a9a22f7a81055c809f7a",
    BANK:
        "d3bd17cb6c9da62feb17d10bd8f7b86789ee11b63acc8d131407ba0b785e1e42",
}

COORD_PAIRS = [
    ("coverage_locus_ra_deg", "coverage_locus_dec_deg"),
    ("target_ra_deg", "target_dec_deg"),
    ("ra_deg", "dec_deg"),
    ("midpoint_ra_deg", "midpoint_dec_deg"),
    ("locus_ra_deg", "locus_dec_deg"),
    ("candidate_ra_deg", "candidate_dec_deg"),
]

def sha(path):
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for b in iter(lambda: fh.read(8 * 1024 * 1024), b""):
            h.update(b)
    return h.hexdigest()

def read_csv(path):
    with path.open("r", newline="", encoding="utf-8-sig") as fh:
        return list(csv.DictReader(fh))

def header(path):
    with path.open("r", newline="", encoding="utf-8-sig") as fh:
        r = csv.reader(fh)
        return next(r)

def find_coord_pairs(fields):
    f = set(fields)
    return [(a,b) for a,b in COORD_PAIRS if a in f and b in f]

def finite(v):
    try:
        return math.isfinite(float(str(v).strip()))
    except Exception:
        return False

def wcs_keys(h):
    out = []
    if "CTYPE1" in h and "CTYPE2" in h:
        out.append(" ")
    for name in h:
        m = re.fullmatch(r"CTYPE1([A-Z])", str(name))
        if m and f"CTYPE2{m.group(1)}" in h:
            out.append(m.group(1))
    return sorted(set(out), key=lambda x: (x != " ", x))

def scan_path(row):
    p = str(row.get("local_path") or "").strip()
    if not p:
        return None
    return ROOT / Path(p.replace("/", "\\"))

def inspect_fits_header_only(path):
    """
    Do not touch HDU.data. fits.open is used only to read HDU headers.
    """
    result = {
        "path": str(path.relative_to(ROOT)).replace("\\", "/"),
        "file_size": path.stat().st_size,
        "hdu_count": 0,
        "hdus": [],
        "celestial_wcs_hdus": [],
    }

    with fits.open(
        path,
        mode="readonly",
        memmap=True,
        lazy_load_hdus=True,
        do_not_scale_image_data=True,
        ignore_missing_end=True,
    ) as hdul:
        result["hdu_count"] = len(hdul)

        for i, hdu in enumerate(hdul):
            h = hdu.header
            keys = wcs_keys(h)
            nx = h.get("NAXIS1")
            ny = h.get("NAXIS2")
            hinfo = {
                "hdu_index": i,
                "xtension": str(h.get("XTENSION", "PRIMARY")),
                "naxis": h.get("NAXIS"),
                "naxis1": nx,
                "naxis2": ny,
                "wcs_keys": keys,
            }

            usable = []
            for key in keys:
                try:
                    w = WCS(h, key=key).celestial
                    if w.pixel_n_dim == 2 and w.world_n_dim == 2:
                        usable.append(key)
                except Exception:
                    pass

            hinfo["usable_celestial_wcs_keys"] = usable
            if usable:
                result["celestial_wcs_hdus"].append({
                    "hdu_index": i,
                    "keys": usable,
                    "naxis1": nx,
                    "naxis2": ny,
                })
            result["hdus"].append(hinfo)

    return result

def main():
    print("=" * 118)
    print("PAIR 17 — v080 NATIVE-PIXEL PREFLIGHT (HEADER/SCHEMA ONLY)")
    print("=" * 118)
    print("FITS pixel arrays accessed: NO")
    print("Detector calls:             0")
    print("Injection measurements:     0")
    print("Recurrence measurements:    0")
    print("Network calls:              0")
    print("Disposition changes:        NONE")
    print()

    for path, expected in EXPECTED.items():
        if not path.is_file():
            raise RuntimeError(f"Missing banked v079b input: {path}")
        actual = sha(path)
        if actual != expected:
            raise RuntimeError(
                f"SHA mismatch:\n{path}\nexpected {expected}\nactual   {actual}"
            )
        print("HASH PASS:", path.relative_to(ROOT))

    required = [V078_QUEUE, V078_SUMMARY, V077_OPPS, V075]
    for p in required:
        if not p.is_file():
            raise RuntimeError(f"Missing required upstream file: {p}")

    schemas = {}
    for name, p in [
        ("v079_plan", PLAN),
        ("v079_scan_queue", QUEUE),
        ("v079_url_manifest", URLS),
        ("v079_acquisition_manifest", ACQ),
        ("v078_followup_queue", V078_QUEUE),
        ("v078_candidate_summary", V078_SUMMARY),
        ("v077a_opportunities", V077_OPPS),
        ("v075_static_triage", V075),
    ]:
        fields = header(p)
        schemas[name] = {
            "fields": fields,
            "coordinate_pairs_present": find_coord_pairs(fields),
        }

    plan = read_csv(PLAN)
    acq = read_csv(ACQ)
    follow = read_csv(V078_QUEUE)

    if len(plan) != 129:
        raise RuntimeError(f"Expected 129 v079 plan rows; got {len(plan)}")
    if len(acq) != 53:
        raise RuntimeError(f"Expected 53 acquisition rows; got {len(acq)}")
    if len(follow) != 23:
        raise RuntimeError(f"Expected 23 frozen survivors; got {len(follow)}")

    role_counts = Counter(str(r.get("selection_role") or "") for r in plan)
    population_counts = Counter(str(r.get("population") or "") for r in follow)

    print()
    print("SCHEMA DISCOVERY")
    for name, info in schemas.items():
        print(f"  {name}:")
        print("    fields:", ",".join(info["fields"]))
        print(
            "    candidate coordinate pairs:",
            info["coordinate_pairs_present"] or "NONE"
        )

    print()
    print("FROZEN POPULATION / PLAN")
    print("  follow-up candidates:", len(follow))
    print("  population counts:", dict(population_counts))
    print("  candidate x selected-plate rows:", len(plan))
    print("  selection-role counts:", dict(role_counts))
    print("  acquired unique scans:", len(acq))

    scan_reports = []
    missing = []
    bad_sha = []

    print()
    print("Inspecting 53 acquired FITS headers only ...")

    for i, row in enumerate(acq, 1):
        p = scan_path(row)
        if p is None or not p.is_file():
            missing.append({
                "scan_id": row.get("scan_id"),
                "local_path": row.get("local_path"),
            })
            continue

        expected_sha = str(row.get("sha256") or "").strip().lower()
        if expected_sha:
            actual_sha = sha(p)
            if actual_sha != expected_sha:
                bad_sha.append({
                    "scan_id": row.get("scan_id"),
                    "expected": expected_sha,
                    "actual": actual_sha,
                })
                continue

        scan_reports.append({
            "scan_id": row.get("scan_id"),
            "filename_scan": row.get("filename_scan"),
            "scan_basename": row.get("scan_basename"),
            **inspect_fits_header_only(p),
        })

        if i % 10 == 0 or i == len(acq):
            print(
                f"  headers {i}/{len(acq)}; "
                f"missing={len(missing)} sha_mismatch={len(bad_sha)}"
            )

    if missing:
        raise RuntimeError(f"{len(missing)} acquired scan files are missing")
    if bad_sha:
        raise RuntimeError(f"{len(bad_sha)} acquired scan SHA mismatches")

    wcs_scans = sum(bool(r["celestial_wcs_hdus"]) for r in scan_reports)
    no_wcs_scans = len(scan_reports) - wcs_scans
    hdu_hist = Counter(int(r["hdu_count"]) for r in scan_reports)

    print()
    print("FITS HEADER INVENTORY")
    print("  scans verified:", len(scan_reports))
    print("  scans with FITS-header celestial WCS:", wcs_scans)
    print("  scans without FITS-header celestial WCS:", no_wcs_scans)
    print("  HDU-count histogram:", dict(sorted(hdu_hist.items())))

    coord_sources = {
        name: info["coordinate_pairs_present"]
        for name, info in schemas.items()
        if info["coordinate_pairs_present"]
    }

    report = {
        "status": "COMPLETE",
        "analysis_kind": "pair17_native_pixel_preflight_v080",
        "science_execution": False,
        "population": {
            "all": 23,
            "plan_rows": 129,
            "unique_scans": 53,
        },
        "schemas": schemas,
        "coordinate_sources_discovered": coord_sources,
        "selection_role_counts": dict(role_counts),
        "fits_header_inventory": {
            "scans_verified": len(scan_reports),
            "scans_with_header_celestial_wcs": wcs_scans,
            "scans_without_header_celestial_wcs": no_wcs_scans,
            "hdu_count_histogram": {
                str(k): v for k, v in sorted(hdu_hist.items())
            },
            "scans": scan_reports,
        },
        "guards": {
            "fits_pixel_arrays_accessed": 0,
            "detector_calls": 0,
            "injection_measurements": 0,
            "recurrence_measurements": 0,
            "network_calls": 0,
            "candidate_disposition_changes": False,
        },
        "decision_for_v080_freeze": (
            "Use this inventory to bind the exact candidate-coordinate source "
            "and WCS transport before any comparison-pixel outcome is read."
        ),
    }

    OUTDIR.mkdir(parents=True, exist_ok=True)
    tmp = OUT_JSON.with_suffix(".json.tmp")
    tmp.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    tmp.replace(OUT_JSON)

    print()
    print("=" * 118)
    print("v080 PREFLIGHT COMPLETE")
    print("=" * 118)
    print("Science pixels read:       0")
    print("Detector calls:            0")
    print("Injection measurements:    0")
    print("Candidate dispositions:    NONE")
    print("Report:", OUT_JSON.relative_to(ROOT))
    print("Report SHA256:", sha(OUT_JSON))


if __name__ == "__main__":
    main()
