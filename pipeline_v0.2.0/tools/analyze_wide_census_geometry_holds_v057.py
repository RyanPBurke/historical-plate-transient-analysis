from __future__ import annotations

from pathlib import Path
from collections import Counter, defaultdict
import csv
import hashlib
import json

ROOT = Path.cwd()
V052 = ROOT / "results" / "wide_census_exact_footprint_v052.json"

OUT_DIR = ROOT / "results" / "wide_census_geometry_hold_inventory_v057"
OUT_JSON = OUT_DIR / "wide_census_geometry_hold_inventory_v057.json"
OUT_CSV = OUT_DIR / "wide_census_geometry_hold_inventory_v057.csv"
OUT_CAUSES = OUT_DIR / "wide_census_geometry_hold_cause_counts_v057.csv"

EXPECTED_HOLDS = 41


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def write_json(path: Path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def write_csv(path: Path, rows, fields):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    tmp.replace(path)


def branch_for(status: str):
    table = {
        "UNRESOLVED_APPLAUSE_EXPOSURE_METADATA": (
            "APPLAUSE_EXPOSURE_METADATA_REPAIR",
            "Query official applause_dr4.exposure/exposure_sub for this exact exposure_id; do not infer missing metadata from detector outcome.",
            "MAYBE",
        ),
        "UNRESOLVED_APPLAUSE_EXPOSURE_CENTER": (
            "APPLAUSE_EXPOSURE_CENTER_METADATA_REPAIR",
            "Query official exposure/log metadata for a documented pointing center. If no documented center exists, retain hold rather than inventing one.",
            "MAYBE",
        ),
        "UNRESOLVED_APPLAUSE_NO_EXACT_POLYGON": (
            "APPLAUSE_SOLUTION_SCAN_INVENTORY_REPAIR",
            "Inventory exact applause_dr4.solution rows for all scans/processes of the physical plate, with solution_id/header_wcs/stc_polygon provenance; retain all viable solutions.",
            "LIKELY_METADATA_ONLY",
        ),
        "UNRESOLVED_APPLAUSE_SOLUTION_EXPOSURE_ASSOCIATION": (
            "APPLAUSE_SOLUTION_SCAN_ASSOCIATION_REPAIR",
            "Use exact solution_id/scan/process metadata and documented exposure identity/center. Do not choose a solution based on detector output; preserve multiple viable solutions and adjudicate overlap across all.",
            "LIKELY_METADATA_ONLY",
        ),
        "UNRESOLVED_DASCH_TIMING_EXPNUM_MISSING": (
            "DASCH_EXPNUM_LOGBOOK_REPAIR",
            "Resolve the selected logged exposure number from official DR7 queryexps/exposure metadata before geometry. No WCS can be assigned by chronology alone.",
            "LIKELY_METADATA_ONLY",
        ),
        "UNRESOLVED_DASCH_NO_ASTROMETRY_HEADER": (
            "DASCH_IMAGING_AVAILABILITY_HOLD",
            "Check official DR7 exposure-list/value-added metadata for an imaging solution. If no WCS solution exists for the logged exposure, retain as no-imaging geometry hold, not a negative.",
            "MAYBE",
        ),
        "UNRESOLVED_DASCH_MOSAIC_SHAPE": (
            "DASCH_MOSAIC_METADATA_REPAIR",
            "Recover authoritative mosaic dimensions from DR7 metadata/value-added FITS. Do not approximate dimensions.",
            "LIKELY_METADATA_ONLY",
        ),
        "UNRESOLVED_DASCH_SELECTED_EXPOSURE": (
            "DASCH_EXPNUM_TO_SOLNUM_REPAIR",
            "Use authoritative DR7 EXPOSURS/queryexps mapping from expnum to solnum; WCS solution ordering has no chronological significance.",
            "LIKELY_METADATA_ONLY",
        ),
        "UNRESOLVED_DASCH_EXPOSURE_CENTER": (
            "DASCH_EXPOSURE_METADATA_REPAIR",
            "Use official EXPOSURS/queryexps center and source fields. If the exposure lacks a solved imaging WCS, retain the hold.",
            "MAYBE",
        ),
        "UNRESOLVED_DASCH_NO_USABLE_WCS": (
            "DASCH_IMAGING_AVAILABILITY_HOLD",
            "Inspect authoritative expnum↔solnum mapping and WCS availability. Logged exposure without solved WCS remains unresolved, not negative.",
            "MAYBE",
        ),
        "UNRESOLVED_DASCH_WCS_EXPOSURE_ASSOCIATION": (
            "DASCH_EXPNUM_TO_SOLNUM_REPAIR",
            "Replace center-nearest WCS inference with authoritative EXPOSURS/queryexps expnum↔solnum mapping. The solution ordering itself is not meaningful.",
            "LIKELY_METADATA_ONLY",
        ),
        "UNRESOLVED_UNSUPPORTED_ARCHIVE_KIND": (
            "UNSUPPORTED_ARCHIVE_HOLD",
            "No generic repair is permitted until an archive-specific provenance/footprint contract is frozen.",
            "NO",
        ),
    }
    if status in table:
        return table[status]
    if status.startswith("RESOLVED"):
        return ("NONE", "Side geometry is already resolved.", "N/A")
    return (
        "REVIEW_UNKNOWN_GEOMETRY_STATE",
        "Preserve hold and inspect the exact metadata/provenance state; no threshold relaxation.",
        "UNKNOWN",
    )


def pair_family(pair):
    archives = sorted([
        str(pair.get("archive_a") or "").strip(),
        str(pair.get("archive_b") or "").strip(),
    ])
    # Prefer geometry-kind inference when possible.
    exps = [str(pair.get("exposure_a") or ""), str(pair.get("exposure_b") or "")]
    kinds = []
    for e in exps:
        if e.startswith("APPLAUSE:"):
            kinds.append("APPLAUSE")
        elif "DASCH:" in e or "dasch" in e.lower():
            kinds.append("DASCH")
        else:
            kinds.append("OTHER")
    return " <-> ".join(sorted(kinds))


def main():
    print("=" * 132)
    print("WIDE CENSUS — v052 GEOMETRY-HOLD CAUSE INVENTORY v057")
    print("=" * 132)
    print("NO NETWORK. NO PIXELS. NO DETECTOR. NO CANDIDATE STATE MUTATION.\n")

    if not V052.is_file():
        raise RuntimeError(f"REFUSING: missing {V052}")

    obj = json.loads(V052.read_text(encoding="utf-8"))
    holds = [
        p for p in (obj.get("pairs") or [])
        if p.get("classification") in {
            "EXACT_FOOTPRINT_UNRESOLVED",
            "EXACT_FOOTPRINT_GEOMETRY_AMBIGUOUS",
            "EXACT_FOOTPRINT_OVERLAP_AMBIGUOUS_ACROSS_SOLUTIONS",
        }
    ]
    if len(holds) != EXPECTED_HOLDS:
        raise RuntimeError(f"REFUSING: expected {EXPECTED_HOLDS} v052 holds, got {len(holds)}")

    rows = []
    status_counts = Counter()
    pair_status_counts = Counter()
    branch_counts = Counter()
    family_counts = Counter()

    for p in holds:
        ga = p.get("geometry_a") or {}
        gb = p.get("geometry_b") or {}
        sa = str(ga.get("status") or "")
        sb = str(gb.get("status") or "")
        family = pair_family(p)
        family_counts[family] += 1

        for s in (sa, sb):
            status_counts[s] += 1

        ba, aa, ra = branch_for(sa)
        bb, ab, rb = branch_for(sb)
        if ba != "NONE":
            branch_counts[ba] += 1
        if bb != "NONE":
            branch_counts[bb] += 1

        pair_key = (sa, sb)
        pair_status_counts[pair_key] += 1

        rows.append({
            "exact_footprint_priority": p.get("exact_footprint_priority"),
            "canonical_pair": p.get("canonical_pair"),
            "time_gate": p.get("time_gate"),
            "physical_overlap_s": p.get("physical_overlap_s"),
            "pair_family": family,
            "classification": p.get("classification"),
            "exposure_a": p.get("exposure_a"),
            "archive_a": p.get("archive_a"),
            "geometry_a_status": sa,
            "geometry_a_candidate_count": ga.get("candidate_count"),
            "geometry_a_best_center_sep_deg": ga.get("best_center_sep_deg"),
            "geometry_a_repair_branch": ba,
            "geometry_a_repairability": ra,
            "geometry_a_repair_action": aa,
            "exposure_b": p.get("exposure_b"),
            "archive_b": p.get("archive_b"),
            "geometry_b_status": sb,
            "geometry_b_candidate_count": gb.get("candidate_count"),
            "geometry_b_best_center_sep_deg": gb.get("best_center_sep_deg"),
            "geometry_b_repair_branch": bb,
            "geometry_b_repairability": rb,
            "geometry_b_repair_action": ab,
        })

    fields = [
        "exact_footprint_priority", "canonical_pair", "time_gate", "physical_overlap_s",
        "pair_family", "classification",
        "exposure_a", "archive_a", "geometry_a_status", "geometry_a_candidate_count",
        "geometry_a_best_center_sep_deg", "geometry_a_repair_branch",
        "geometry_a_repairability", "geometry_a_repair_action",
        "exposure_b", "archive_b", "geometry_b_status", "geometry_b_candidate_count",
        "geometry_b_best_center_sep_deg", "geometry_b_repair_branch",
        "geometry_b_repairability", "geometry_b_repair_action",
    ]
    write_csv(OUT_CSV, rows, fields)

    cause_rows = []
    for status, n in sorted(status_counts.items(), key=lambda kv: (-kv[1], kv[0])):
        b, action, repairability = branch_for(status)
        cause_rows.append({
            "geometry_status": status,
            "endpoint_occurrences": n,
            "repair_branch": b,
            "repairability": repairability,
            "generic_action": action,
        })
    write_csv(
        OUT_CAUSES, cause_rows,
        ["geometry_status", "endpoint_occurrences", "repair_branch", "repairability", "generic_action"]
    )

    payload = {
        "status": "COMPLETE",
        "analysis_kind": "wide_census_geometry_hold_cause_inventory_v057",
        "guards": {
            "network_access": False,
            "science_pixels_read": False,
            "non_science_pixels_read": False,
            "transient_detector_rerun": False,
            "candidate_state_mutation": False,
        },
        "source_v052_sha256": sha(V052),
        "hold_count": len(holds),
        "pair_family_counts": dict(sorted(family_counts.items())),
        "endpoint_geometry_status_counts": dict(sorted(status_counts.items())),
        "pair_geometry_status_combination_counts": {
            f"{a} || {b}": n for (a, b), n in sorted(pair_status_counts.items())
        },
        "recommended_repair_branch_counts": dict(sorted(branch_counts.items())),
        "rows": rows,
        "interpretation_boundary": (
            "This is a mechanical cause inventory of existing v052 holds. It does not "
            "convert any hold to overlap/no-overlap and does not relax v052 association thresholds."
        ),
        "next_step": (
            "Build metadata-only resolution workers for the dominant generic cause classes, "
            "especially authoritative DASCH expnum↔solnum mapping and exact APPLAUSE "
            "solution/scan inventories, then re-evaluate footprints across all surviving solutions."
        ),
    }
    write_json(OUT_JSON, payload)

    print("Hold pairs:", len(holds))
    print("\nEndpoint geometry-status counts:")
    for k, v in sorted(status_counts.items(), key=lambda kv: (-kv[1], kv[0])):
        print(f"  {v:3d}  {k}")
    print("\nRepair-branch endpoint counts:")
    for k, v in sorted(branch_counts.items(), key=lambda kv: (-kv[1], kv[0])):
        print(f"  {v:3d}  {k}")
    print("\nPair-family counts:")
    for k, v in sorted(family_counts.items()):
        print(f"  {v:3d}  {k}")
    print("\nOutputs:")
    print(" ", OUT_JSON)
    print(" ", OUT_CSV)
    print(" ", OUT_CAUSES)
    print("\nSTAGE STATUS: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
