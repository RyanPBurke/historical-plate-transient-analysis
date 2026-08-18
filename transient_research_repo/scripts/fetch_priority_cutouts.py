#!/usr/bin/env python3
"""Fetch deterministic 20-arcmin DASCH/POSS cutout pairs for top candidates."""

from __future__ import annotations

import base64
import gzip
import json
import math
from pathlib import Path
from urllib.parse import urlencode
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "results"
CUTOUTS = ROOT / "cutouts"
CUTOUTS.mkdir(exist_ok=True)
DASCH_API = "https://api.starglass.cfa.harvard.edu/public/dasch/dr7/cutout"
DSS_API = "https://archive.stsci.edu/cgi-bin/dss_search"


def destination_point(ra1, dec1, ra2, dec2, distance_deg):
    """Point distance_deg from coordinate 1 toward coordinate 2."""
    p1, p2 = math.radians(dec1), math.radians(dec2)
    dl = math.radians(ra2 - ra1)
    bearing = math.atan2(
        math.sin(dl) * math.cos(p2),
        math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl),
    )
    delta = math.radians(distance_deg)
    p3 = math.asin(math.sin(p1)*math.cos(delta) + math.cos(p1)*math.sin(delta)*math.cos(bearing))
    dl3 = math.atan2(math.sin(bearing)*math.sin(delta)*math.cos(p1), math.cos(delta)-math.sin(p1)*math.sin(p3))
    return (ra1 + math.degrees(dl3)) % 360, math.degrees(p3)


def choose_center(row, dasch_side):
    other = "b" if dasch_side == "a" else "a"
    ra_other, dec_other = row[f"ra_{other}_deg"], row[f"dec_{other}_deg"]
    overlap = row.overlap_fraction_smaller_field
    if overlap >= 0.25:
        return ra_other, dec_other, "center_of_non_dasch_plate"
    ra_d, dec_d = row[f"ra_{dasch_side}_deg"], row[f"dec_{dasch_side}_deg"]
    d = row.center_separation_deg
    r_d = row[f"fov_{dasch_side}_deg"] / 2
    r_o = row[f"fov_{other}_deg"] / 2
    near_edge = max(0.0, d - r_d)
    distance = (near_edge + r_o) / 2
    ra, dec = destination_point(ra_other, dec_other, ra_d, dec_d, distance)
    return ra, dec, "midpoint_of_approximate_radial_intersection"


def dasch_cutout(plate_id, solution, ra, dec) -> bytes:
    payload = json.dumps({
        "plate_id": plate_id, "solution_number": int(solution),
        "center_ra_deg": float(ra), "center_dec_deg": float(dec),
    }).encode()
    request = Request(DASCH_API, data=payload, headers={
        "User-Agent": "Transients-Villarroel-reproducibility/1.0",
        "Content-Type": "application/json", "Accept": "application/json",
    })
    with urlopen(request, timeout=180) as response:
        encoded = json.load(response)
    return base64.b64decode(encoded)


def dss_cutout(band, ra, dec) -> bytes:
    params = {
        "v": "poss1_red" if band == "E" else "poss1_blue",
        "r": f"{ra:.8f}", "d": f"{dec:.8f}", "e": "J2000",
        "h": "20", "w": "20", "f": "fits", "c": "none",
    }
    request = Request(DSS_API + "?" + urlencode(params), headers={"User-Agent": "Transients-Villarroel-reproducibility/1.0"})
    with urlopen(request, timeout=180) as response:
        return response.read()


def main():
    pairs = pd.read_csv(RESULTS / "validated_sub5_pairs.csv", low_memory=False)
    pairs = pairs[(pairs.archive_a.str.contains("POSS", na=False)) | (pairs.archive_b.str.contains("POSS", na=False))].copy()
    manifest = []
    for _, row in pairs.iterrows():
        dasch_side = "a" if str(row.exposure_a).startswith("DASCH:") else "b"
        poss_side = "b" if dasch_side == "a" else "a"
        plate_id = row[f"dasch_plate_id_{dasch_side}"]
        poss_id = row[f"exposure_{poss_side}"]
        band = str(poss_id).rsplit(":", 1)[-1]
        ra, dec, center_rule = choose_center(row, dasch_side)
        prefix = f"rank{int(row.priority_rank):02d}_{plate_id}_{str(poss_id).replace(':','_')}"
        status, error = "retrieved", ""
        dasch_path = CUTOUTS / f"{prefix}_dasch.fits.gz"
        poss_path = CUTOUTS / f"{prefix}_poss.fits"
        try:
            dasch_bytes = dasch_cutout(plate_id, 0, ra, dec)
            # The API response is already a gzipped FITS file.
            if not dasch_bytes.startswith(b"\x1f\x8b"):
                raise RuntimeError("DASCH response is not gzip data")
            dasch_path.write_bytes(dasch_bytes)
            poss_bytes = dss_cutout(band, ra, dec)
            if not poss_bytes.startswith(b"SIMPLE"):
                raise RuntimeError("DSS response is not a FITS file")
            poss_path.write_bytes(poss_bytes)
            if not gzip.decompress(dasch_bytes).startswith(b"SIMPLE"):
                raise RuntimeError("Decompressed DASCH response is not FITS")
        except HTTPError as exc:
            if exc.code == 422:
                status = "rejected_no_dasch_wcs_coverage"
                error = "DASCH cutout service rejected the deterministic center (HTTP 422)"
            else:
                status, error = "failed", f"HTTP {exc.code}: {exc.reason}"
        except Exception as exc:
            status, error = "failed", str(exc)
        manifest.append({
            "priority_rank": row.priority_rank, "dasch_plate_id": plate_id,
            "poss_exposure_id": poss_id, "poss_band": band,
            "center_ra_deg": ra, "center_dec_deg": dec, "center_rule": center_rule,
            "dasch_solution_number": 0, "cutout_width_arcmin": 20,
            "dasch_file": str(dasch_path.relative_to(ROOT)),
            "poss_file": str(poss_path.relative_to(ROOT)),
            "retrieval_status": status, "retrieval_error": error,
        })
    frame = pd.DataFrame(manifest)
    frame.to_csv(RESULTS / "priority_cutout_manifest.csv", index=False)
    print(frame[["priority_rank", "dasch_plate_id", "poss_exposure_id", "retrieval_status", "retrieval_error"]].to_string(index=False))
    if (frame.retrieval_status == "failed").any():
        raise SystemExit(2)


if __name__ == "__main__":
    main()
