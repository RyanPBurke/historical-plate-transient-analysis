#!/usr/bin/env python3
"""
ORDER 01 — historical close-hit 2-D geometry audit v028h

Consumes:
    results/order01_native_full_v028/order01_candidate_evidence_inventory_v028d.csv
    results/order01_native_full_v028/order01_historical_closehit_calibration_v028g.json

Purpose
-------
For the four frozen Branch-A candidates with exactly one historical <=5"
catalogue hit, reconstruct the full reached-sample 2-D sky-position history of
the SAME catalogue reference and ask:

    Is the close hit near the reference's usual astrometric locus,
    or is it a one-off displacement of a reference normally tens of arcsec away?

This is a catalogue/geometry audit only.

NO:
  * network access
  * science-pixel reads
  * detector reruns
  * candidate promotion
  * candidate deletion
  * weighted candidate score
  * decoding/interpretation of DASCH aflags/bflags

Inputs are already-completed outputs.

Reference-locus rule
--------------------
A reference history is considered "well sampled" only when it has >=100
unique-plate detections in the reached sample.

For a well-sampled reference, a close hit is labelled
    EXTREME_DISPLACEMENT_FROM_WELL_SAMPLED_REFERENCE_LOCUS
only if:
  * the hit is within 5" of the candidate target;
  * its distance from the median 2-D reference-locus vector is at or above the
    empirical 95th percentile of same-reference locus residuals; and
  * the median reference locus itself is >5" from the target.

This label describes the HISTORICAL CATALOGUE HIT, not the transient candidate.

Sparse histories are labelled
    SPARSE_REFERENCE_HISTORY_GEOMETRY_UNRESOLVED
and are not forced into the outlier interpretation.

The 95th-percentile threshold and >=100 sample threshold are explicit
diagnostic conventions, not physical significance thresholds.
"""

from __future__ import annotations

import csv
import json
import math
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "results" / "order01_native_full_v028"

INVENTORY = RESULTS / "order01_candidate_evidence_inventory_v028d.csv"
CALIBRATION = RESULTS / "order01_historical_closehit_calibration_v028g.json"

OUT_JSON = RESULTS / "order01_historical_closehit_geometry_v028h.json"
OUT_CSV = RESULTS / "order01_historical_closehit_geometry_v028h.csv"
OUT_MD = RESULTS / "ORDER01_HISTORICAL_CLOSEHIT_GEOMETRY_V028H.md"

EXPECTED_ALL = [10, 24, 25, 26, 29, 30]
EXPECTED_SINGLE_HIT = [10, 25, 26, 30]

DETAIL_SUFFIXES = (
    "order01_platephot_stage1_detail_v028c.csv",
    "order01_platephot_stage2_detail_new_v028c.csv",
    "order01_platephot_stage3_detail_new_v028c.csv",
)
MANIFEST_SUFFIXES = (
    "order01_platephot_stage1_manifest_v028c.csv",
    "order01_platephot_stage2_cumulative_manifest_v028c.csv",
    "order01_platephot_stage2_new_call_manifest_v028c.csv",
    "order01_platephot_stage3_cumulative_manifest_v028c.csv",
    "order01_platephot_stage3_new_call_manifest_v028c.csv",
)
PLATE_SUMMARY_SUFFIX = "order01_platephot_stage3_plate_summary_new_v028c.csv"

WELL_SAMPLED_MIN = 100
EXTREME_RESIDUAL_PERCENTILE = 0.95


def normpath(s: str) -> str:
    return str(s).replace("\\", "/")


def f(v: Any) -> float:
    return float(str(v).strip())


def i(v: Any) -> int:
    return int(float(str(v).strip()))


def empirical_cdf_le(values: list[float], x: float) -> float:
    return sum(v <= x for v in values) / len(values)


def empirical_upper_ge(values: list[float], x: float) -> float:
    return sum(v >= x for v in values) / len(values)


def circular_angle_deg(ax: float, ay: float, bx: float, by: float) -> float | None:
    na = math.hypot(ax, ay)
    nb = math.hypot(bx, by)
    if na == 0 or nb == 0:
        return None
    c = (ax * bx + ay * by) / (na * nb)
    c = max(-1.0, min(1.0, c))
    return math.degrees(math.acos(c))


def selected_limit_mag(manifest: dict[str, Any]) -> tuple[str, float | None]:
    refcat = str(manifest.get("selected_refcat_for_platephot", "")).strip().lower()
    if refcat == "apass":
        raw = str(manifest.get("limMagApass", "")).strip()
        return "limMagApass", (float(raw) if raw else None)
    if refcat == "atlas":
        raw = str(manifest.get("limMagAtlas", "")).strip()
        return "limMagAtlas", (float(raw) if raw else None)
    return "", None


def geometry_label(
    n_unique: int,
    hit_sep: float,
    median_locus_distance: float,
    residual_percentile: float,
) -> str:
    if n_unique < WELL_SAMPLED_MIN:
        return "SPARSE_REFERENCE_HISTORY_GEOMETRY_UNRESOLVED"
    if (
        hit_sep <= 5.0
        and median_locus_distance > 5.0
        and residual_percentile >= EXTREME_RESIDUAL_PERCENTILE
    ):
        return "EXTREME_DISPLACEMENT_FROM_WELL_SAMPLED_REFERENCE_LOCUS"
    return "CLOSE_HIT_NOT_EXTREME_BY_DECLARED_LOCUS_RULE"


def main() -> int:
    print("=" * 118)
    print("ORDER 01 — HISTORICAL CLOSE-HIT 2-D GEOMETRY AUDIT v028h")
    print("=" * 118)

    if not INVENTORY.exists():
        print(f"FAIL: missing inventory: {INVENTORY}")
        return 2
    if not CALIBRATION.exists():
        print(f"FAIL: missing calibration: {CALIBRATION}")
        return 2

    cal = json.loads(CALIBRATION.read_text(encoding="utf-8"))
    if cal.get("frozen_active_ranks") != EXPECTED_ALL:
        print("FAIL: frozen survivor set mismatch in v028g.")
        return 3

    single = {}
    for row in cal.get("rows", []):
        rank = int(row["strict_rank"])
        if int(row["historical_close5_observed"]) == 1:
            single[rank] = {
                "ref_number": str(row["closest_historical_ref_number"]),
                "refcat": str(row["closest_historical_refcat"]),
                "hit_plate": str(row["closest_historical_plate_id"]),
                "reported_ref_total": int(
                    row["closest_reference_total_detections_in_sample"]
                ),
                "reported_close5": int(
                    row["closest_reference_close5_detections_in_sample"]
                ),
                "reported_hit_sep": float(row["closest_historical_sep_arcsec"]),
            }

    if sorted(single) != EXPECTED_SINGLE_HIT:
        print("FAIL: unexpected one-hit survivor set.")
        print("      got:", sorted(single))
        print(" expected:", EXPECTED_SINGLE_HIT)
        return 4

    detail_rows: dict[int, list[dict[str, Any]]] = defaultdict(list)
    target_coords: dict[int, set[tuple[float, float]]] = defaultdict(set)
    hit_manifests: dict[int, dict[str, Any]] = {}
    hit_plate_summaries: dict[int, dict[str, Any]] = {}

    print("Streaming v028d inventory...")

    with INVENTORY.open("r", encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        required = {
            "strict_rank", "source_file", "source_type",
            "location", "rank_field", "evidence_json"
        }
        if not required.issubset(reader.fieldnames or []):
            print("FAIL: v028d inventory schema mismatch.")
            return 5

        for row in reader:
            try:
                rank = int(row["strict_rank"])
            except Exception:
                continue
            if rank not in single:
                continue

            sf = normpath(row["source_file"])
            try:
                ev = json.loads(row["evidence_json"])
            except Exception:
                continue

            # Same-reference detection history: use non-overlapping detail stages.
            if sf.endswith(DETAIL_SUFFIXES):
                if (
                    str(ev.get("ref_number", "")) == single[rank]["ref_number"]
                    and str(ev.get("refcat", "")).lower()
                    == single[rank]["refcat"].lower()
                ):
                    detail_rows[rank].append(ev)
                continue

            # Target coordinates are invariant across completed plate manifests.
            if sf.endswith(MANIFEST_SUFFIXES):
                try:
                    target_coords[rank].add(
                        (float(ev["target_ra_deg"]), float(ev["target_dec_deg"]))
                    )
                except Exception:
                    pass
                if str(ev.get("plate_id", "")) == single[rank]["hit_plate"]:
                    # Prefer cumulative manifest if encountered, but all duplicate
                    # manifest representations should agree on physical fields.
                    hit_manifests[rank] = ev
                continue

            if (
                sf.endswith(PLATE_SUMMARY_SUFFIX)
                and str(ev.get("plate_id", "")) == single[rank]["hit_plate"]
            ):
                hit_plate_summaries[rank] = ev

    results = []

    for rank in EXPECTED_SINGLE_HIT:
        cfg = single[rank]
        hist = detail_rows.get(rank, [])

        if not hist:
            print(f"FAIL: rank {rank}: no same-reference detail rows found.")
            return 6

        unique_plates = {str(e.get("plate_id", "")) for e in hist}
        if len(unique_plates) != len(hist):
            print(
                f"FAIL: rank {rank}: duplicate same-reference rows by plate "
                f"({len(hist)} rows, {len(unique_plates)} unique plates)."
            )
            return 7

        if len(hist) != cfg["reported_ref_total"]:
            print(
                f"FAIL: rank {rank}: same-reference count mismatch: "
                f"detail={len(hist)} vs v028g={cfg['reported_ref_total']}"
            )
            return 8

        coords = target_coords.get(rank, set())
        if len(coords) != 1:
            print(
                f"FAIL: rank {rank}: expected one invariant target coordinate, "
                f"found {len(coords)}"
            )
            return 9

        target_ra, target_dec = next(iter(coords))
        cos_dec = math.cos(math.radians(target_dec))

        vectors = []
        for ev in hist:
            try:
                ra = f(ev["ra_deg"])
                dec = f(ev["dec_deg"])
                sep = f(ev["sep_target_arcsec"])
            except Exception as exc:
                print(f"FAIL: rank {rank}: malformed detail row: {exc}")
                return 10

            dra = (ra - target_ra) * 3600.0 * cos_dec
            ddec = (dec - target_dec) * 3600.0

            vectors.append({
                "plate_id": str(ev["plate_id"]),
                "dra_arcsec": dra,
                "ddec_arcsec": ddec,
                "sep_target_arcsec": sep,
                "magcal_magdep": (
                    f(ev["magcal_magdep"])
                    if str(ev.get("magcal_magdep", "")).strip()
                    else None
                ),
                "ellipticity": (
                    f(ev["ellipticity"])
                    if str(ev.get("ellipticity", "")).strip()
                    else None
                ),
                "fwhm_world_raw": (
                    f(ev["fwhm_world_raw"])
                    if str(ev.get("fwhm_world_raw", "")).strip()
                    else None
                ),
                # Preserve raw flags only. No decoding is performed here.
                "aflags_raw": str(ev.get("aflags", "")),
                "bflags_raw": str(ev.get("bflags", "")),
                "plate_quality_flag_raw": str(ev.get("plate_quality_flag", "")),
            })

        median_dra = statistics.median(v["dra_arcsec"] for v in vectors)
        median_ddec = statistics.median(v["ddec_arcsec"] for v in vectors)
        median_locus_distance = math.hypot(median_dra, median_ddec)

        for v in vectors:
            v["residual_from_median_locus_arcsec"] = math.hypot(
                v["dra_arcsec"] - median_dra,
                v["ddec_arcsec"] - median_ddec,
            )

        radial_seps = [v["sep_target_arcsec"] for v in vectors]
        locus_resids = [v["residual_from_median_locus_arcsec"] for v in vectors]

        hit_matches = [
            v for v in vectors if v["plate_id"] == cfg["hit_plate"]
        ]
        if len(hit_matches) != 1:
            print(
                f"FAIL: rank {rank}: expected one hit row for "
                f"{cfg['hit_plate']}, found {len(hit_matches)}"
            )
            return 11
        hit = hit_matches[0]

        if not math.isclose(
            hit["sep_target_arcsec"],
            cfg["reported_hit_sep"],
            rel_tol=0.0,
            abs_tol=1e-9,
        ):
            print(f"FAIL: rank {rank}: hit separation mismatch.")
            return 12

        close5_count = sum(v["sep_target_arcsec"] <= 5.0 for v in vectors)
        if close5_count != cfg["reported_close5"]:
            print(
                f"FAIL: rank {rank}: close5 count mismatch: "
                f"detail={close5_count}, v028g={cfg['reported_close5']}"
            )
            return 13

        resid_pct = empirical_cdf_le(
            locus_resids, hit["residual_from_median_locus_arcsec"]
        )
        resid_upper = empirical_upper_ge(
            locus_resids, hit["residual_from_median_locus_arcsec"]
        )
        radial_pct = empirical_cdf_le(radial_seps, hit["sep_target_arcsec"])

        angle = circular_angle_deg(
            hit["dra_arcsec"],
            hit["ddec_arcsec"],
            median_dra,
            median_ddec,
        )

        manifest = hit_manifests.get(rank, {})
        summary = hit_plate_summaries.get(rank, {})
        limit_field, limit_mag = selected_limit_mag(manifest)
        mag_margin = None
        if limit_mag is not None and hit["magcal_magdep"] is not None:
            mag_margin = limit_mag - hit["magcal_magdep"]

        label = geometry_label(
            len(unique_plates),
            hit["sep_target_arcsec"],
            median_locus_distance,
            resid_pct,
        )

        result = {
            "strict_rank": rank,
            "reference_catalogue": cfg["refcat"],
            "reference_number": cfg["ref_number"],
            "reference_unique_plate_detections": len(unique_plates),
            "reference_history_sampling": (
                "WELL_SAMPLED"
                if len(unique_plates) >= WELL_SAMPLED_MIN
                else "SPARSE"
            ),
            "target_ra_deg": target_ra,
            "target_dec_deg": target_dec,
            "reference_median_dra_arcsec": median_dra,
            "reference_median_ddec_arcsec": median_ddec,
            "reference_median_locus_distance_arcsec": median_locus_distance,
            "reference_median_radial_sep_arcsec":
                statistics.median(radial_seps),
            "reference_radial_sep_min_arcsec": min(radial_seps),
            "reference_radial_sep_max_arcsec": max(radial_seps),
            "reference_close5_count": close5_count,
            "hit_plate_id": cfg["hit_plate"],
            "hit_sep_target_arcsec": hit["sep_target_arcsec"],
            "hit_dra_arcsec": hit["dra_arcsec"],
            "hit_ddec_arcsec": hit["ddec_arcsec"],
            "hit_distance_from_median_reference_locus_arcsec":
                hit["residual_from_median_locus_arcsec"],
            "hit_reference_locus_residual_empirical_percentile": resid_pct,
            "hit_reference_locus_residual_empirical_upper_fraction": resid_upper,
            "hit_radial_sep_empirical_cdf": radial_pct,
            "hit_vector_angle_from_median_reference_vector_deg": angle,
            "hit_expdate": str(manifest.get("expdate", "")),
            "hit_exptime_min": None,
            "hit_centerdist": (
                f(manifest["centerdist"])
                if str(manifest.get("centerdist", "")).strip()
                else None
            ),
            "hit_edgedist": (
                f(manifest["edgedist"])
                if str(manifest.get("edgedist", "")).strip()
                else None
            ),
            "hit_selected_refcat":
                str(manifest.get("selected_refcat_for_platephot", "")),
            "hit_limit_field": limit_field,
            "hit_limit_mag": limit_mag,
            "hit_magcal_magdep": hit["magcal_magdep"],
            "hit_limit_minus_source_mag": mag_margin,
            "hit_ellipticity": hit["ellipticity"],
            "hit_fwhm_world_raw": hit["fwhm_world_raw"],
            "hit_aflags_raw": hit["aflags_raw"],
            "hit_bflags_raw": hit["bflags_raw"],
            "hit_plate_quality_flag_raw": hit["plate_quality_flag_raw"],
            "hit_plate_response_rows": (
                i(summary["response_rows"])
                if str(summary.get("response_rows", "")).strip()
                else None
            ),
            "hit_plate_sources_within_60arcsec": (
                i(summary["sources_within_60arcsec"])
                if str(summary.get("sources_within_60arcsec", "")).strip()
                else None
            ),
            "geometry_label": label,
        }
        results.append(result)

    payload = {
        "stage": "ORDER01_HISTORICAL_CLOSEHIT_GEOMETRY_V028H",
        "inputs": {
            "inventory": str(INVENTORY.relative_to(ROOT)),
            "calibration": str(CALIBRATION.relative_to(ROOT)),
        },
        "frozen_active_ranks": EXPECTED_ALL,
        "single_closehit_ranks": EXPECTED_SINGLE_HIT,
        "guards": {
            "network_access": False,
            "science_pixels_read": False,
            "detector_rerun": False,
            "candidate_promotion": False,
            "candidate_deletion": False,
            "weighted_candidate_score": False,
            "aflags_bflags_decoded": False,
        },
        "declared_geometry_rule": {
            "well_sampled_min_unique_plate_detections": WELL_SAMPLED_MIN,
            "extreme_residual_empirical_percentile":
                EXTREME_RESIDUAL_PERCENTILE,
            "close_radius_arcsec": 5.0,
            "warning": (
                "The geometry label describes the isolated historical catalogue "
                "hit, not the transient candidate. It is a diagnostic convention, "
                "not an astrophysical significance threshold."
            ),
        },
        "results": results,
    }
    OUT_JSON.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False),
        encoding="utf-8"
    )

    fields = list(results[0].keys())
    with OUT_CSV.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        writer.writerows(results)

    md = []
    md.append("# ORDER 01 — Historical Close-Hit 2-D Geometry Audit v028h")
    md.append("")
    md.append(
        "Read-only 2-D same-reference geometry audit for the four frozen "
        "Branch-A survivors with exactly one historical <=5 arcsec hit."
    )
    md.append("")
    md.append("## Guardrails")
    md.append("")
    md.append("- No network access.")
    md.append("- No science pixels read.")
    md.append("- No detector rerun.")
    md.append("- No candidate promoted or deleted.")
    md.append("- No weighted candidate score.")
    md.append("- DASCH `aflags` / `bflags` are retained raw and not decoded.")
    md.append("")
    md.append("## Declared diagnostic rule")
    md.append("")
    md.append(
        f"A same-reference history is `WELL_SAMPLED` at >= "
        f"{WELL_SAMPLED_MIN} unique plates."
    )
    md.append(
        f"A close hit is labelled an extreme displacement only when its 2-D "
        f"residual from the median reference locus is at or above the "
        f"{100*EXTREME_RESIDUAL_PERCENTILE:.0f}th empirical percentile, "
        f"the hit is <=5 arcsec from target, and the median reference locus "
        f"is itself >5 arcsec from target."
    )
    md.append("")
    md.append("## Results")
    md.append("")
    md.append(
        "| rank | ref N | median ref locus | hit sep | hit -> ref-locus "
        "distance | residual percentile | edge dist | mag margin | geometry |"
    )
    md.append("|---:|---:|---:|---:|---:|---:|---:|---:|---|")
    for r in results:
        margin = r["hit_limit_minus_source_mag"]
        margin_text = f"{margin:.3f}" if margin is not None else "n/a"
        edge = r["hit_edgedist"]
        edge_text = f"{edge:.3f}" if edge is not None else "n/a"
        md.append(
            f"| #{r['strict_rank']} | {r['reference_unique_plate_detections']} | "
            f"{r['reference_median_locus_distance_arcsec']:.3f}\" | "
            f"{r['hit_sep_target_arcsec']:.3f}\" | "
            f"{r['hit_distance_from_median_reference_locus_arcsec']:.3f}\" | "
            f"{100*r['hit_reference_locus_residual_empirical_percentile']:.2f}% | "
            f"{edge_text} | {margin_text} | `{r['geometry_label']}` |"
        )
    md.append("")
    md.append("## Interpretation boundary")
    md.append("")
    md.append(
        "For a well-sampled reference, an extreme displacement means the "
        "historical catalogue point near the target is atypical of where that "
        "same reference normally appears. This weakens the use of that one row "
        "as recurrence evidence, but does not establish why the displacement "
        "occurred and does not validate the candidate."
    )
    md.append("")
    md.append(
        "A sparse reference history remains unresolved by this test; absence of "
        "a stable locus prevents strong geometric adjudication."
    )
    md.append("")
    OUT_MD.write_text("\n".join(md), encoding="utf-8")

    print()
    print("Same-reference 2-D geometry:")
    print("-" * 118)
    for r in results:
        print(
            f"#{r['strict_rank']:>2} "
            f"N={r['reference_unique_plate_detections']:>3} "
            f"median_locus={r['reference_median_locus_distance_arcsec']:.3f}\" "
            f"hit={r['hit_sep_target_arcsec']:.3f}\" "
            f"hit_to_locus={r['hit_distance_from_median_reference_locus_arcsec']:.3f}\" "
            f"resid_pct={100*r['hit_reference_locus_residual_empirical_percentile']:.2f}% "
            f"upper={100*r['hit_reference_locus_residual_empirical_upper_fraction']:.2f}% "
            f"edge={r['hit_edgedist']} "
            f"mag_margin={r['hit_limit_minus_source_mag']} "
            f"{r['geometry_label']}"
        )

    print()
    print("Outputs:")
    print(f"  {OUT_JSON}")
    print(f"  {OUT_CSV}")
    print(f"  {OUT_MD}")
    print()
    print("No external query was made.")
    print("No science pixel was read.")
    print("No detector was rerun.")
    print("No candidate was promoted or deleted.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
