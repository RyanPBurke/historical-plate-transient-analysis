#!/usr/bin/env python3
"""Validate and rank the sub-five-minute cross-archive pair queue."""

from __future__ import annotations

import math
import json
import re
from pathlib import Path
from urllib.request import Request, urlopen

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "results"
API = "https://api.starglass.cfa.harvard.edu/public/plates/p/"


def dasch_plate_id(exposure_id: str) -> str:
    match = re.search(r"/q/([a-z]+)(\d+)$", str(exposure_id))
    return f"{match.group(1)}{int(match.group(2)):05d}" if match else ""


def fetch_dasch_details(plate_ids) -> dict:
    details = {}
    for plate_id in sorted(set(x for x in plate_ids if x)):
        try:
            req = Request(API + plate_id, headers={"User-Agent": "Transients-Villarroel-reproducibility/1.0"})
            with urlopen(req, timeout=60) as response:
                details[plate_id] = json.load(response)
        except Exception as exc:
            details[plate_id] = {"retrieval_error": str(exc)}
    return details


def enrich_side(queue: pd.DataFrame, side: str, details: dict) -> None:
    id_col = f"exposure_{side}"
    queue[f"dasch_plate_id_{side}"] = queue[id_col].apply(dasch_plate_id)
    locations, telescopes, latitudes, longitudes, solutions = [], [], [], [], []
    for plate_id in queue[f"dasch_plate_id_{side}"]:
        detail = details.get(plate_id, {}) if plate_id else {}
        location = detail.get("location") or {}
        locations.append(location.get("name", ""))
        telescopes.append(detail.get("telescope", ""))
        latitudes.append(location.get("lat", ""))
        longitudes.append(location.get("lon", ""))
        exposures = detail.get("exposures") or []
        solutions.append(len(exposures))
    queue[f"resolved_location_{side}"] = locations
    queue[f"telescope_{side}"] = telescopes
    queue[f"latitude_{side}"] = latitudes
    queue[f"longitude_{side}"] = longitudes
    queue[f"wcs_solution_count_{side}"] = solutions
    is_dasch = queue[id_col].astype(str).str.startswith("DASCH:")
    resolved = queue[f"resolved_location_{side}"].astype(str).str.len() > 0
    queue.loc[is_dasch & resolved, f"site_{side}"] = queue.loc[is_dasch & resolved, f"resolved_location_{side}"]


def circle_intersection_area(r1: float, r2: float, d: float) -> float:
    """Planar circle intersection in square degrees (screening approximation)."""
    if d >= r1 + r2:
        return 0.0
    if d <= abs(r1 - r2):
        return math.pi * min(r1, r2) ** 2
    x1 = (d*d + r1*r1 - r2*r2) / (2*d*r1)
    x2 = (d*d + r2*r2 - r1*r1) / (2*d*r2)
    a1 = r1*r1 * math.acos(max(-1, min(1, x1)))
    a2 = r2*r2 * math.acos(max(-1, min(1, x2)))
    a3 = 0.5 * math.sqrt(max(0, (-d+r1+r2)*(d+r1-r2)*(d-r1+r2)*(d+r1+r2)))
    return a1 + a2 - a3


def temporal_metrics(row):
    a0 = pd.Timestamp(row.start_a_utc)
    a1 = pd.Timestamp(row.end_a_utc)
    b0 = pd.Timestamp(row.start_b_utc)
    b1 = pd.Timestamp(row.end_b_utc)
    overlap = max(0.0, (min(a1, b1) - max(a0, b0)).total_seconds())
    if overlap:
        gap = 0.0
    elif a1 < b0:
        gap = (b0 - a1).total_seconds()
    else:
        gap = (a0 - b1).total_seconds()
    return pd.Series({"interval_overlap_s": overlap, "interval_gap_s": gap})


def independence(row) -> str:
    sites = {str(row.site_a), str(row.site_b)}
    if "DASCH historical observing site unresolved" in sites:
        return "independent_archive_site_unresolved"
    if len(sites) == 2:
        return "distinct_physical_sites_from_metadata"
    return "not_independent_site"


def rank(row) -> tuple[int, str]:
    score = 0
    reasons = []
    if row.interval_overlap_s > 0:
        score += 40; reasons.append("exposure_intervals_overlap")
    elif row.interval_gap_s <= 300:
        score += 25; reasons.append("interval_gap_le_5m")
    if row.overlap_fraction_smaller_field >= 0.25:
        score += 25; reasons.append("footprint_overlap_ge_25pct")
    elif row.overlap_fraction_smaller_field > 0:
        score += 10; reasons.append("partial_footprint_overlap")
    if "POSS-I" in str(row.archive_a) or "POSS-I" in str(row.archive_b):
        score += 20; reasons.append("POSS_replication_priority")
    if row.site_independence == "distinct_physical_sites_from_metadata":
        score += 15; reasons.append("physical_sites_resolved")
    else:
        reasons.append("site_resolution_required")
    if "verify" in str(row.time_precision_a) or "verify" in str(row.time_precision_b):
        reasons.append("time_basis_verification_required")
    return score, ";".join(reasons)


def main():
    source = pd.read_csv(RESULTS / "archive_pair_overlap_candidates.csv", low_memory=False)
    queue = source[source.midpoint_delta_minutes <= 5.0].copy()
    plate_ids = [dasch_plate_id(x) for x in pd.concat([queue.exposure_a, queue.exposure_b])]
    details = fetch_dasch_details(plate_ids)
    enrich_side(queue, "a", details)
    enrich_side(queue, "b", details)
    timing = queue.apply(temporal_metrics, axis=1)
    queue = pd.concat([queue, timing], axis=1)
    areas = []
    fractions = []
    for _, row in queue.iterrows():
        r1, r2 = row.fov_a_deg / 2, row.fov_b_deg / 2
        area = circle_intersection_area(r1, r2, row.center_separation_deg)
        areas.append(area)
        fractions.append(area / (math.pi * min(r1, r2) ** 2) if min(r1, r2) > 0 else 0)
    queue["approx_overlap_area_sqdeg"] = areas
    queue["overlap_fraction_smaller_field"] = fractions
    queue["site_independence"] = queue.apply(independence, axis=1)
    ranked = queue.apply(rank, axis=1)
    queue["priority_score"] = [x[0] for x in ranked]
    queue["priority_reasons"] = [x[1] for x in ranked]
    queue["validation_status"] = "metadata_screen_complete_pixel_validation_pending"
    queue = queue.sort_values(
        ["priority_score", "interval_overlap_s", "midpoint_delta_minutes"],
        ascending=[False, False, True],
    )
    queue.insert(0, "priority_rank", range(1, len(queue) + 1))
    queue.to_csv(RESULTS / "validated_sub5_pairs.csv", index=False)

    detail_rows = []
    for plate_id, detail in details.items():
        location = detail.get("location") or {}
        detail_rows.append({
            "plate_id": plate_id, "telescope": detail.get("telescope", ""),
            "location": location.get("name", ""), "latitude_deg": location.get("lat", ""),
            "longitude_deg": location.get("lon", ""), "elevation_m": location.get("elevation", ""),
            "wcs_solution_count": len(detail.get("exposures") or []),
            "retrieval_error": detail.get("retrieval_error", ""),
            "source_url": API + plate_id,
        })
    pd.DataFrame(detail_rows).to_csv(RESULTS / "dasch_priority_plate_details.csv", index=False)

    poss = queue[(queue.archive_a.str.contains("POSS", na=False)) | (queue.archive_b.str.contains("POSS", na=False))]
    physical = queue[queue.site_independence == "distinct_physical_sites_from_metadata"]
    overlaps = queue[queue.interval_overlap_s > 0]
    report = f"""# Sub-five-minute pair validation

## Outcome

- Input candidates: **{len(queue)}**
- Exposure intervals actually overlap: **{len(overlaps)}**
- Distinct physical sites resolved directly from metadata: **{len(physical)}**
- POSS-I replication candidates: **{len(poss)}**
- DASCH-site resolution still required: **{sum(queue.site_independence == 'independent_archive_site_unresolved')}**

The original shortlist used midpoint separation. This validation adds exposure
start/end intervals, approximate circle-intersection area, smaller-field overlap
fraction, timestamp provenance, and a reproducible priority score.

## Promotion rule

`validated_sub5_pairs.csv` is ranked, but no row is yet a confirmed transient
pair. Promotion requires:

1. original logbook/jacket verification of time and observing station;
2. true WCS footprint intersection rather than the circular approximation;
3. selection of predetermined sky positions in the common footprint;
4. pixel retrieval and identical frozen detection on both plates;
5. plate-preserving negative controls and injection/recovery.

## Ranking

- 40 points: exposure intervals overlap.
- 25 points: gap no more than five minutes when intervals do not overlap.
- 25 points: at least 25% of the smaller approximate footprint overlaps.
- 20 points: one member is POSS-I.
- 15 points: metadata directly resolve distinct physical sites.

The score is triage only and has no statistical interpretation.
"""
    (ROOT / "PAIR_VALIDATION_REPORT.md").write_text(report)
    print(f"validated pairs: {len(queue)}")
    print(f"actual interval overlaps: {len(overlaps)}")
    print(f"resolved physical-site pairs: {len(physical)}")
    print(f"POSS-I pairs: {len(poss)}")


if __name__ == "__main__":
    main()
