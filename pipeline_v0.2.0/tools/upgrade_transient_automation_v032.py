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
SOURCE = ROOT / "results" / "order55_native_preflight_v028" / "order55_poss_identity_acquisition_v028cb.json"
STAGE_ID = "order55_timing_provenance_audit_v028cc"
STAGE_REL = "automation/stages/audit_order55_timing_provenance_v028cc.py"
STAGE = ROOT / STAGE_REL
OUT_REL = "results/order55_native_preflight_v028/order55_timing_provenance_audit_v028cc.json"

STAGE_SOURCE = r'''from __future__ import annotations

from pathlib import Path
import csv
import datetime as dt
import hashlib
import json

ROOT = Path.cwd()
IDENTITY = ROOT / "results" / "order55_native_preflight_v028" / "order55_poss_identity_acquisition_v028cb.json"
QUEUE = ROOT / "research" / "poss1_pixel_repair_v028_queue.csv"
PAIR_MAP = ROOT / "research" / "SUB5_V028_POSS_PAIR_EXECUTION_MAP_2026-08-21.csv"
OUT = ROOT / "results" / "order55_native_preflight_v028" / "order55_timing_provenance_audit_v028cc.json"
ORDER = 55
EXPECTED_POSS = "POSS-I:606:E:rec348"
EXPECTED_DASCH = "fa12998"


def sha256_file(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def read_csv(path):
    with path.open(newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def one_order(rows):
    hits = []
    for row in rows:
        try:
            if int(float(str(row.get("canonical_order", "")).strip())) == ORDER:
                hits.append(row)
        except ValueError:
            pass
    if len(hits) != 1:
        raise RuntimeError(f"REFUSING: expected one Order {ORDER} row; got {len(hits)}")
    return hits[0]


def parse_time(value):
    text = str(value).strip().replace("Z", "+00:00")
    value = dt.datetime.fromisoformat(text)
    if value.tzinfo is None:
        value = value.replace(tzinfo=dt.timezone.utc)
    return value.astimezone(dt.timezone.utc)


def interval_overlap(a0, a1, b0, b1):
    return max(0.0, (min(a1, b1) - max(a0, b0)).total_seconds())


def find_hhh_date(identity):
    resolved = identity.get("resolved_poss_identity") or {}
    hident = resolved.get("hhh_identity") or {}
    header = resolved.get("hhh_header") or {}
    values = [hident.get("date_obs"), header.get("DATE-OBS")]
    values = [str(v).strip() for v in values if str(v or "").strip()]
    if not values:
        raise RuntimeError("REFUSING: no HHH DATE-OBS in identity acquisition")
    parsed = [parse_time(v) for v in values]
    if any(abs((v - parsed[0]).total_seconds()) > 1 for v in parsed[1:]):
        raise RuntimeError("REFUSING: inconsistent HHH date fields: " + repr(values))
    return values, parsed[0]


def main():
    print("=" * 120)
    print("ORDER 55 — TIMING PROVENANCE AND TRUE-OVERLAP AUDIT v028cc")
    print("=" * 120)
    print("NO NETWORK. NO PIXELS. No detector or candidate mutation.\n")
    for path in (IDENTITY, QUEUE, PAIR_MAP):
        if not path.is_file():
            raise RuntimeError(f"Missing required input: {path}")

    identity = json.loads(IDENTITY.read_text(encoding="utf-8"))
    queue = one_order(read_csv(QUEUE))
    pair_map = one_order(read_csv(PAIR_MAP))
    frozen = identity.get("pair") or {}
    if frozen.get("poss") != EXPECTED_POSS or frozen.get("dasch") != EXPECTED_DASCH:
        raise RuntimeError("REFUSING: identity product is not the frozen Order-55 pair")
    resolved = identity.get("resolved_poss_identity") or {}
    if resolved.get("region") != "XE347" or str(resolved.get("plate_id", "")).upper() != "06RF":
        raise RuntimeError("REFUSING: unexpected resolved Order-55 physical identity")

    poss_is_a = "POSS" in str(queue.get("archive_a", "")).upper()
    poss_prefix = "a" if poss_is_a else "b"
    dasch_prefix = "b" if poss_is_a else "a"
    catalog_poss_start = parse_time(queue[f"start_{poss_prefix}_utc"])
    catalog_poss_end = parse_time(queue[f"end_{poss_prefix}_utc"])
    dasch_start = parse_time(queue[f"start_{dasch_prefix}_utc"])
    dasch_end = parse_time(queue[f"end_{dasch_prefix}_utc"])
    duration_s = float(queue[f"duration_{poss_prefix}_s"])

    hhh_values, physical_poss_start = find_hhh_date(identity)
    physical_poss_end = physical_poss_start + dt.timedelta(seconds=duration_s)
    frozen_overlap = interval_overlap(catalog_poss_start, catalog_poss_end, dasch_start, dasch_end)
    physical_overlap = interval_overlap(physical_poss_start, physical_poss_end, dasch_start, dasch_end)
    start_offset_s = (catalog_poss_start - physical_poss_start).total_seconds()

    near_one_day = abs(abs(start_offset_s) - 86400.0) <= 300.0
    material_conflict = abs(start_offset_s) > 300.0
    overlap_removed = frozen_overlap > 0 and physical_overlap == 0
    if material_conflict and overlap_removed:
        classification = "PHYSICAL_PLATE_TIME_REMOVES_OVERLAP_ORDER55_PAIR_BLOCKED"
        disposition = "DEMOTE_AS_TWO_OBSERVATORY_TIMING_CANDIDATE_PENDING_DOCUMENTED_DATE_CORRECTION"
    elif material_conflict:
        classification = "MATERIAL_TIME_CONFLICT_OVERLAP_REQUIRES_REVIEW"
        disposition = "BLOCK_PIXEL_EXECUTION_PENDING_TIME_RESOLUTION"
    else:
        classification = "PHYSICAL_AND_CATALOG_TIMES_AGREE"
        disposition = "TIMING_GATE_PASS"

    print(f"Catalogue POSS interval: {catalog_poss_start.isoformat()} -> {catalog_poss_end.isoformat()}")
    print(f"Physical HHH interval:   {physical_poss_start.isoformat()} -> {physical_poss_end.isoformat()}")
    print(f"DASCH interval:          {dasch_start.isoformat()} -> {dasch_end.isoformat()}")
    print(f"POSS start-time difference: {start_offset_s:.3f} s ({start_offset_s/3600:.6f} h)")
    print(f"Frozen overlap:  {frozen_overlap:.3f} s")
    print(f"Physical overlap: {physical_overlap:.3f} s")
    print(f"\nClassification: {classification}")
    print(f"Disposition: {disposition}")

    result = {
        "status": "COMPLETE",
        "analysis_kind": "order55_timing_provenance_audit_v028cc",
        "guards": {"network_access": False, "science_pixels_read": False, "non_science_pixels_read": False,
                   "transient_detector_rerun": False, "candidate_state_mutation": False},
        "input_sha256": {str(IDENTITY.relative_to(ROOT)): sha256_file(IDENTITY),
                         str(QUEUE.relative_to(ROOT)): sha256_file(QUEUE),
                         str(PAIR_MAP.relative_to(ROOT)): sha256_file(PAIR_MAP)},
        "identity": {"poss_exposure": EXPECTED_POSS, "region": resolved.get("region"),
                     "plate_id": resolved.get("plate_id"), "dasch_plate": EXPECTED_DASCH},
        "time_provenance": {
            "catalog_poss_start_utc": catalog_poss_start.isoformat(),
            "catalog_poss_end_utc": catalog_poss_end.isoformat(),
            "physical_hhh_date_values": hhh_values,
            "physical_poss_start_utc": physical_poss_start.isoformat(),
            "physical_poss_end_utc_assuming_catalog_duration": physical_poss_end.isoformat(),
            "dasch_start_utc": dasch_start.isoformat(), "dasch_end_utc": dasch_end.isoformat(),
            "catalog_minus_physical_start_s": start_offset_s,
            "near_exact_one_day_offset": near_one_day,
        },
        "overlap": {"frozen_catalog_overlap_s": frozen_overlap, "physical_header_overlap_s": physical_overlap,
                    "overlap_removed_by_physical_time": overlap_removed},
        "classification": classification,
        "disposition": disposition,
        "interpretation": (
            "The physical POSS plate header is the stronger plate-identity timestamp. The catalogue-based "
            "two-observatory pairing must not proceed unless independent provenance demonstrates that the "
            "one-day difference is a documented date convention or source error and supplies a defensible correction."
        ),
        "next_stage": "Advance to Order 74 if physical overlap is zero; preserve Order 55 as a timing-provenance exception.",
    }
    tmp = OUT.with_suffix(OUT.suffix + ".tmp")
    tmp.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(OUT)
    print(f"\nOutput: {OUT}\nSTAGE STATUS: PASS")


if __name__ == "__main__":
    main()
'''


def main():
    print("=" * 120)
    print("TRANSIENT AUTOMATION UPGRADE v0.3.2 — ORDER-55 TIMING PROVENANCE AUDIT")
    print("=" * 120)
    print("NO NETWORK. NO PIXELS. No detector or candidate mutation.\n")
    for path in (REGISTRY, INIT, SOURCE):
        if not path.is_file():
            raise RuntimeError(f"Missing required input: {path}")
    source = json.loads(SOURCE.read_text(encoding="utf-8"))
    resolved = source.get("resolved_poss_identity") or {}
    if resolved.get("region") != "XE347" or str(resolved.get("plate_id", "")).upper() != "06RF":
        raise RuntimeError("REFUSING: Order-55 identity is not the verified XE347/06RF result")
    ast.parse(STAGE_SOURCE, filename=str(STAGE))
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = ROOT / "automation" / "backups" / f"pre_v032_order55_timing_{stamp}"
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
        contract = f'''\n\n    StageContract(\n        stage_id="{STAGE_ID}",\n        title="Audit Order-55 physical plate time and recompute true overlap",\n        script="{STAGE_REL}",\n        requires=("results/order55_native_preflight_v028/order55_poss_identity_acquisition_v028cb.json", "research/poss1_pixel_repair_v028_queue.csv"),\n        produces=("{OUT_REL}",),\n        dependencies=("order55_poss_identity_acquisition_v028cb",),\n        notes="No network/pixels; compares catalogue interval with physical HHH DATE-OBS and blocks false overlap.",\n    ),\n'''
        registry = registry[:marker.start()] + contract + registry[marker.start():]
        ast.parse(registry, filename=str(REGISTRY))
        REGISTRY.write_text(registry, encoding="utf-8", newline="\n")
    init = re.sub(r'__version__\s*=\s*["\'][^"\']+["\']', '__version__ = "0.3.8"', INIT.read_text(encoding="utf-8"), count=1)
    ast.parse(init, filename=str(INIT))
    INIT.write_text(init, encoding="utf-8", newline="\n")
    print(f"Installed stage: {STAGE_ID}")
    print(f"Backup: {backup}\n\nUPGRADE STATUS: PASS")


if __name__ == "__main__":
    main()
