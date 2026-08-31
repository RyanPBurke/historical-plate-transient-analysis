from __future__ import annotations

from pathlib import Path
import ast
import datetime as dt
import json
import re
import shutil

ROOT = Path.cwd()
REGISTRY = ROOT / "automation" / "registry_order01.py"
INIT = ROOT / "automation" / "__init__.py"
CENSUS = ROOT / "results" / "remaining_pair_physical_timing_census_v028cg.json"
STAGE_ID = "physical_overlap_survivor_execution_plan_v028ch"
STAGE_REL = "automation/stages/plan_physical_overlap_survivor_execution_v028ch.py"
STAGE = ROOT / STAGE_REL
OUT_REL = "results/physical_overlap_survivor_execution_plan_v028ch.json"

STAGE_SOURCE = r'''from __future__ import annotations
from pathlib import Path
import csv
import datetime as dt
import hashlib
import json

ROOT = Path.cwd()
CENSUS = ROOT / "results" / "remaining_pair_physical_timing_census_v028cg.json"
OUT = ROOT / "results" / "physical_overlap_survivor_execution_plan_v028ch.json"
OUT_CSV = ROOT / "results" / "physical_overlap_survivor_execution_plan_v028ch.csv"
EXPECTED_SURVIVORS = {28, 29, 11, 18, 24}


def sha256_file(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def parse_time(value):
    value = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if value.tzinfo is None:
        value = value.replace(tzinfo=dt.timezone.utc)
    return value.astimezone(dt.timezone.utc)


def overlap_s(a0, a1, b0, b1):
    return max(0.0, (min(a1, b1)-max(a0, b0)).total_seconds())


def conservative_overlap(poss_start, poss_end, dasch_start, dasch_end, accuracy_s):
    early = overlap_s(poss_start, poss_end, dasch_start-dt.timedelta(seconds=accuracy_s), dasch_end-dt.timedelta(seconds=accuracy_s))
    late = overlap_s(poss_start, poss_end, dasch_start+dt.timedelta(seconds=accuracy_s), dasch_end+dt.timedelta(seconds=accuracy_s))
    return min(early, late)


def main():
    print("=" * 120)
    print("PHYSICAL-OVERLAP SURVIVORS — NATIVE EXECUTION PLAN v028ch")
    print("=" * 120)
    print("NO NETWORK. NO PIXELS. No detector or candidate mutation.\n")
    census = json.loads(CENSUS.read_text(encoding="utf-8"))
    survivors = [x for x in census.get("results", []) if x.get("classification") == "PHYSICAL_TIME_OVERLAP_SURVIVES"]
    orders = {int(x["canonical_order"]) for x in survivors}
    if orders != EXPECTED_SURVIVORS or census.get("unresolved_orders"):
        raise RuntimeError(f"REFUSING: unexpected survivor/unresolved set: survivors={sorted(orders)} unresolved={census.get('unresolved_orders')}")

    plan = []
    for item in survivors:
        exposures = item.get("dasch_exposures") or []
        if not exposures:
            raise RuntimeError(f"Order {item['canonical_order']}: missing DASCH exposure interval")
        best = max(exposures, key=lambda x: float(x["overlap_with_physical_poss_s"]))
        accuracy_s = float(best.get("date_accuracy_days") or 0.0) * 86400.0
        ps0, ps1 = parse_time(item["physical_poss_start_utc"]), parse_time(item["physical_poss_end_utc"])
        ds0, ds1 = parse_time(best["start_utc"]), parse_time(best["end_utc"])
        conservative = conservative_overlap(ps0, ps1, ds0, ds1, accuracy_s)
        plan.append({
            "canonical_order": int(item["canonical_order"]),
            "poss_exposure": item["poss_exposure"], "poss_region": item["region"],
            "poss_plate_id": item["plate_id"], "poss_band": item["band"],
            "poss_hhh_url": item["hhh_url"], "poss_hhh_sha256": item["hhh_sha256"],
            "dasch_plate": item["dasch_plate"], "dasch_exposure_number": best.get("number"),
            "physical_overlap_s": float(best["overlap_with_physical_poss_s"]),
            "physical_overlap_min": float(best["overlap_with_physical_poss_s"])/60.0,
            "dasch_date_accuracy_s": accuracy_s,
            "conservative_overlap_s": conservative,
            "conservative_overlap_min": conservative/60.0,
            "poss_start_utc": ps0.isoformat(), "poss_end_utc": ps1.isoformat(),
            "dasch_start_utc": ds0.isoformat(), "dasch_end_utc": ds1.isoformat(),
            "input_state": "METADATA_IDENTITY_AND_PHYSICAL_TIMING_VERIFIED",
        })
    plan.sort(key=lambda x: (-x["conservative_overlap_s"], x["dasch_date_accuracy_s"], x["canonical_order"]))
    for rank, item in enumerate(plan, 1):
        item["execution_priority"] = rank

    unique_poss = {}
    for item in plan:
        key = (item["poss_exposure"], item["poss_region"], item["poss_plate_id"])
        unique_poss.setdefault(key, []).append(item["canonical_order"])
    poss_inputs = [{"poss_exposure": k[0], "region": k[1], "plate_id": k[2],
                    "used_by_orders": sorted(v), "download_once": True} for k, v in unique_poss.items()]
    poss_inputs.sort(key=lambda x: min(x["used_by_orders"]))

    result = {
        "status": "COMPLETE", "analysis_kind": "physical_overlap_survivor_execution_plan_v028ch",
        "guards": {"network_access": False, "science_pixels_read": False, "non_science_pixels_read": False,
                   "transient_detector_rerun": False, "candidate_state_mutation": False},
        "census_sha256": sha256_file(CENSUS),
        "pair_opportunity_count": len(plan), "unique_poss_plate_count": len(poss_inputs),
        "unique_dasch_plate_count": len({x["dasch_plate"] for x in plan}),
        "execution_order": [x["canonical_order"] for x in plan],
        "unique_poss_inputs": poss_inputs, "pair_execution_plan": plan,
        "execution_protocol": [
            "Refresh and hash-pin exact native source metadata immediately before download.",
            "Download each unique POSS plate once and each DASCH plate once; preserve original bytes and checksums.",
            "Validate full WCS footprint and target containment independently on both observatory images.",
            "Run the frozen detector without parameter retuning on each image.",
            "Apply local astrometric registration and location-dependent coordinate uncertainty before cross-matching.",
            "Require independent source-like evidence on both plates; retain plate-defect and catalogue controls.",
        ],
        "next_stage": "Build and certify a parameterised native-input worker, then execute in the frozen priority order.",
    }
    tmp = OUT.with_suffix(OUT.suffix + ".tmp")
    tmp.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(OUT)
    fields = ["execution_priority", "canonical_order", "poss_exposure", "poss_region", "poss_plate_id",
              "dasch_plate", "physical_overlap_min", "dasch_date_accuracy_s", "conservative_overlap_min"]
    with OUT_CSV.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for item in plan:
            writer.writerow({k: item[k] for k in fields})
    print(f"Pair opportunities: {len(plan)}")
    print(f"Unique POSS plates: {len(poss_inputs)}")
    print(f"Unique DASCH plates: {len({x['dasch_plate'] for x in plan})}")
    for x in plan:
        print(f"  {x['execution_priority']}. Order {x['canonical_order']}: overlap={x['physical_overlap_min']:.1f} min; conservative={x['conservative_overlap_min']:.1f} min")
    print(f"Outputs: {OUT}, {OUT_CSV}\nSTAGE STATUS: PASS")


if __name__ == "__main__":
    main()
'''


def main():
    print("=" * 120)
    print("TRANSIENT AUTOMATION UPGRADE v0.3.6 — PHYSICAL-OVERLAP SURVIVOR EXECUTION PLAN")
    print("=" * 120)
    print("NO NETWORK. NO PIXELS. No detector or candidate mutation.\n")
    for path in (REGISTRY, INIT, CENSUS):
        if not path.is_file():
            raise RuntimeError(f"Missing required input: {path}")
    census = json.loads(CENSUS.read_text(encoding="utf-8"))
    if set(census.get("physical_overlap_survivor_orders", [])) != {28, 29, 11, 18, 24}:
        raise RuntimeError("REFUSING: census survivor set is not the verified five-pair cohort")
    ast.parse(STAGE_SOURCE, filename=str(STAGE))
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = ROOT / "automation" / "backups" / f"pre_v036_survivor_plan_{stamp}"
    backup.mkdir(parents=True, exist_ok=False)
    shutil.copy2(REGISTRY, backup / REGISTRY.name)
    shutil.copy2(INIT, backup / INIT.name)
    STAGE.parent.mkdir(parents=True, exist_ok=True)
    STAGE.write_text(STAGE_SOURCE, encoding="utf-8", newline="\n")
    registry = REGISTRY.read_text(encoding="utf-8")
    if STAGE_ID not in registry:
        marker = re.search(r"\n\]\s*\n\s*def by_id\(\):", registry)
        if not marker:
            raise RuntimeError("REFUSING: registry closing marker not found")
        contract = f'''\n\n    StageContract(\n        stage_id="{STAGE_ID}",\n        title="Freeze native execution plan for five physical-overlap survivors",\n        script="{STAGE_REL}",\n        requires=("results/remaining_pair_physical_timing_census_v028cg.json",),\n        produces=("{OUT_REL}",),\n        dependencies=("remaining_pair_physical_timing_census_v028cg",),\n        notes="No network/pixels; ranks conservative overlap and deduplicates shared POSS inputs.",\n    ),\n'''
        registry = registry[:marker.start()] + contract + registry[marker.start():]
        ast.parse(registry, filename=str(REGISTRY))
        REGISTRY.write_text(registry, encoding="utf-8", newline="\n")
    init = re.sub(r'__version__\s*=\s*["\'][^"\']+["\']', '__version__ = "0.3.12"', INIT.read_text(encoding="utf-8"), count=1)
    ast.parse(init, filename=str(INIT))
    INIT.write_text(init, encoding="utf-8", newline="\n")
    print(f"Installed stage: {STAGE_ID}")
    print(f"Backup: {backup}\n\nUPGRADE STATUS: PASS")


if __name__ == "__main__":
    main()
