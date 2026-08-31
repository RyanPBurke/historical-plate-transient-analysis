
from __future__ import annotations
from pathlib import Path
from datetime import datetime, timezone
import csv, hashlib, json

ROOT = Path.cwd()
SOURCE = ROOT / "research" / "census_inputs" / "archive_pair_overlap_candidates.csv"
CURRENT = ROOT / "results" / "existing_identified_pair_inventory_v028ca.json"
TIMING = ROOT / "results" / "remaining_pair_physical_timing_census_v028cg.json"
PLAN = ROOT / "results" / "physical_overlap_survivor_execution_plan_v028ch.json"
MATCH3 = ROOT / "results" / "order11_followup_match3_v047" / "order11_match3_method_freeze_v047.json"

OUT_JSON = ROOT / "results" / "census_scope_audit_v048.json"
OUT_CSV = ROOT / "results" / "wide_census_physical_timing_queue_v048.csv"

EXPECTED_SOURCE_SHA = "ed6ad88c17f79c64ca1bbd5471095faebd457707563b17d47cbc3e9ce566fe74"
EXPECTED_ROWS = 236
EXPECTED_FAMILIES = 10
EXPECTED_GATE_COUNTS = {"LE5": 32, "LE10_CUMULATIVE": 73, "LE15_CUMULATIVE": 111}
EXPECTED_CURRENT_SURVIVORS = {28, 29, 11, 18, 24}

def sha256_file(path: Path):
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024*1024), b""):
            h.update(chunk)
    return h.hexdigest()

def parse_dt(s):
    s = str(s).strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    return datetime.fromisoformat(s).astimezone(timezone.utc)

def overlap(a0, a1, b0, b1):
    start = max(a0, b0)
    end = min(a1, b1)
    sec = max(0.0, (end - start).total_seconds())
    return start, end, sec

def gate(delta):
    x = abs(float(delta))
    if x <= 5.0:
        return "LE5_MIN"
    if x <= 10.0:
        return "GT5_LE10_MIN"
    if x <= 15.0:
        return "GT10_LE15_MIN"
    return "GT15_MIN"

def family(a, b):
    return " <-> ".join(sorted((str(a).strip(), str(b).strip())))

def main():
    print("="*128)
    print("PROJECT CENSUS SCOPE AUDIT + <=15 MIN PHYSICAL-TIMING QUEUE v048")
    print("="*128)
    print("NO NETWORK. NO PIXELS. NO DETECTOR. NO CANDIDATE STATE MUTATION.\n")

    for p in (SOURCE, CURRENT, TIMING, PLAN, MATCH3):
        if not p.is_file():
            raise RuntimeError(f"REFUSING: required input missing: {p}")

    if sha256_file(SOURCE) != EXPECTED_SOURCE_SHA:
        raise RuntimeError("REFUSING: wide archive-pair inventory hash changed")

    with SOURCE.open(newline="", encoding="utf-8-sig") as fh:
        rows = list(csv.DictReader(fh))
    if len(rows) != EXPECTED_ROWS:
        raise RuntimeError(f"REFUSING: expected {EXPECTED_ROWS} wide rows, got {len(rows)}")

    canonical = set()
    families = {}
    queue = []
    all_summary = []

    for i, r in enumerate(rows, 1):
        a = str(r["exposure_a"]).strip()
        b = str(r["exposure_b"]).strip()
        key = " | ".join(sorted((a, b)))
        if key in canonical:
            raise RuntimeError(f"REFUSING: duplicate canonical pair: {key}")
        canonical.add(key)

        fam = family(r["archive_a"], r["archive_b"])
        families[fam] = families.get(fam, 0) + 1
        tier = gate(r["midpoint_delta_minutes"])

        a0, a1 = parse_dt(r["start_a_utc"]), parse_dt(r["end_a_utc"])
        b0, b1 = parse_dt(r["start_b_utc"]), parse_dt(r["end_b_utc"])
        os_, oe_, osec = overlap(a0, a1, b0, b1)

        rec = {
            "wide_source_row": i,
            "canonical_pair": key,
            "exposure_a": a,
            "archive_a": r["archive_a"],
            "site_a": r["site_a"],
            "catalog_start_a_utc": a0.isoformat(),
            "catalog_end_a_utc": a1.isoformat(),
            "catalog_time_precision_a": r["time_precision_a"],
            "exposure_b": b,
            "archive_b": r["archive_b"],
            "site_b": r["site_b"],
            "catalog_start_b_utc": b0.isoformat(),
            "catalog_end_b_utc": b1.isoformat(),
            "catalog_time_precision_b": r["time_precision_b"],
            "archive_pair_family": fam,
            "midpoint_delta_minutes": float(r["midpoint_delta_minutes"]),
            "current_time_gate": tier,
            "catalog_interval_overlap_start_utc": os_.isoformat() if osec > 0 else "",
            "catalog_interval_overlap_end_utc": oe_.isoformat() if osec > 0 else "",
            "catalog_interval_overlap_s": osec,
            "catalog_interval_overlap_is_not_physical_validation": True,
            "source_validation_needed": r.get("validation_needed", ""),
            "needs_physical_timing_validation": True,
            "needs_physical_plate_provenance_audit": True,
            "science_eligible": False,
            "science_eligibility_reason": "AWAIT_PHYSICAL_TIMING_AND_PROVENANCE",
        }
        all_summary.append(rec)
        if tier != "GT15_MIN":
            queue.append(rec)

    if len(families) != EXPECTED_FAMILIES:
        raise RuntimeError(f"REFUSING: expected {EXPECTED_FAMILIES} families, got {len(families)}")

    counts = {
        "LE5": sum(x["current_time_gate"] == "LE5_MIN" for x in all_summary),
        "LE10_CUMULATIVE": sum(x["current_time_gate"] in ("LE5_MIN", "GT5_LE10_MIN") for x in all_summary),
        "LE15_CUMULATIVE": sum(x["current_time_gate"] != "GT15_MIN" for x in all_summary),
    }
    if counts != EXPECTED_GATE_COUNTS:
        raise RuntimeError(f"REFUSING: gate counts changed: {counts}")

    current = json.loads(CURRENT.read_text(encoding="utf-8"))
    timing = json.loads(TIMING.read_text(encoding="utf-8"))
    plan = json.loads(PLAN.read_text(encoding="utf-8"))
    match3 = json.loads(MATCH3.read_text(encoding="utf-8"))

    guards = {
        "current_cohort_rows_11": int(current.get("queue_rows", -1)) == 11,
        "current_scope_boundary_preserved": "not proof that every historical or possible observatory pair has been enumerated" in current.get("scope_boundary", ""),
        "remaining_timing_rows_8": len(timing.get("results", [])) == 8,
        "remaining_timing_unresolved_empty": timing.get("unresolved_orders") == [],
        "current_survivor_set": set(map(int, timing.get("physical_overlap_survivor_orders", []))) == EXPECTED_CURRENT_SURVIVORS,
        "survivor_plan_five": len(plan.get("pair_execution_plan", [])) == 5,
        "match3_method_freeze_complete": match3.get("status") == "COMPLETE",
        "match3_pair_hypothesis_closed": match3.get("pair_disposition") == "CLOSED_COMMON_SKY_COINCIDENCE_SPARSE_REGISTRATION_ROBUST",
    }
    if not all(guards.values()):
        raise RuntimeError("REFUSING: project semantic guard failed: " + json.dumps(guards, sort_keys=True))

    tier_order = {"LE5_MIN": 0, "GT5_LE10_MIN": 1, "GT10_LE15_MIN": 2}
    queue.sort(key=lambda x: (
        tier_order[x["current_time_gate"]],
        abs(x["midpoint_delta_minutes"]),
        -x["catalog_interval_overlap_s"],
        x["canonical_pair"],
    ))
    for i, rec in enumerate(queue, 1):
        rec["timing_validation_priority"] = i

    fields = [
        "timing_validation_priority", "wide_source_row", "current_time_gate", "canonical_pair",
        "exposure_a", "archive_a", "site_a", "catalog_start_a_utc", "catalog_end_a_utc", "catalog_time_precision_a",
        "exposure_b", "archive_b", "site_b", "catalog_start_b_utc", "catalog_end_b_utc", "catalog_time_precision_b",
        "archive_pair_family", "midpoint_delta_minutes",
        "catalog_interval_overlap_start_utc", "catalog_interval_overlap_end_utc", "catalog_interval_overlap_s",
        "catalog_interval_overlap_is_not_physical_validation",
        "needs_physical_timing_validation", "needs_physical_plate_provenance_audit",
        "science_eligible", "science_eligibility_reason", "source_validation_needed"
    ]
    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    tmp_csv = OUT_CSV.with_suffix(".csv.tmp")
    with tmp_csv.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(queue)
    tmp_csv.replace(OUT_CSV)

    family_rows = []
    for fam, n in sorted(families.items()):
        family_rows.append({
            "archive_pair_family": fam,
            "wide_inventory_rows": n,
            "le15_rows": sum(x["archive_pair_family"] == fam and x["current_time_gate"] != "GT15_MIN" for x in all_summary),
        })

    payload = {
        "status": "COMPLETE",
        "analysis_kind": "project_census_scope_audit_v048",
        "guards": {
            "network_access": False,
            "science_pixels_read": False,
            "non_science_pixels_read": False,
            "transient_detector_rerun": False,
            "candidate_state_mutation": False,
        },
        "semantic_guards": guards,
        "input_sha256": {
            str(SOURCE.relative_to(ROOT)): sha256_file(SOURCE),
            str(CURRENT.relative_to(ROOT)): sha256_file(CURRENT),
            str(TIMING.relative_to(ROOT)): sha256_file(TIMING),
            str(PLAN.relative_to(ROOT)): sha256_file(PLAN),
            str(MATCH3.relative_to(ROOT)): sha256_file(MATCH3),
        },
        "scope_classification": "CURRENT_11_ROW_POSS_DASCH_COHORT_TIMING_RESOLVED_ARCHIVE_WIDE_CENSUS_REQUIRES_PHYSICAL_VALIDATION",
        "current_identified_cohort": {
            "queue_scope": current.get("queue_scope"),
            "rows": current.get("queue_rows"),
            "scope_boundary": current.get("scope_boundary"),
            "remaining_eight_timing_audited": len(timing.get("results", [])),
            "remaining_eight_physical_overlap_survivors": timing.get("physical_overlap_survivor_orders"),
            "remaining_eight_zero_overlap_count": timing.get("classification_counts", {}).get("NO_PHYSICAL_TIME_OVERLAP"),
            "unresolved_orders": timing.get("unresolved_orders"),
        },
        "wider_archive_pair_inventory": {
            "rows": len(rows),
            "unique_canonical_pairs": len(canonical),
            "archive_pair_family_count": len(families),
            "archive_pair_families": family_rows,
            "time_gate_counts": counts,
            "le15_physical_timing_validation_queue_rows": len(queue),
            "catalog_interval_positive_overlap_all_rows": sum(x["catalog_interval_overlap_s"] > 0 for x in all_summary),
            "catalog_interval_positive_overlap_le15": sum(x["catalog_interval_overlap_s"] > 0 for x in queue),
            "interpretation_boundary": "Catalog start/end intervals are queue-construction metadata only. Every queued pair requires physical/logbook timing validation and physical-plate provenance before science eligibility."
        },
        "queue": {
            "path": str(OUT_CSV.relative_to(ROOT)),
            "ordering": "<=5 min first, then >5-10, then >10-15; within tier smaller midpoint delta then larger catalogue interval overlap.",
            "no_row_is_science_eligible_yet": True
        },
        "next_stage": "Run a resumable metadata-only physical timing/provenance census over the 111-row <=15-minute queue before more candidate-level detector adjudication."
    }

    tmp = OUT_JSON.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(OUT_JSON)

    print(f"Wide inventory rows: {len(rows)}")
    print(f"Archive-pair families: {len(families)}")
    print(f"Current gates: <=5={counts['LE5']} <=10(cum)={counts['LE10_CUMULATIVE']} <=15(cum)={counts['LE15_CUMULATIVE']}")
    print(f"<=15 physical-timing/provenance validation queue: {len(queue)}")
    print("SCIENCE ELIGIBLE FROM THIS STAGE: 0")
    print(f"Outputs: {OUT_JSON}, {OUT_CSV}")
    print("\nSTAGE STATUS: PASS")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
