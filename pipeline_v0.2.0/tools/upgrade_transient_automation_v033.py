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
INVENTORY = ROOT / "results" / "existing_identified_pair_inventory_v028ca.json"
ORDER55_AUDIT = ROOT / "results" / "order55_native_preflight_v028" / "order55_timing_provenance_audit_v028cc.json"
ORDER55_ID_STAGE = ROOT / "automation" / "stages" / "acquire_order55_poss_identity_v028cb.py"

CLOSE_ID = "order55_disposition_queue_advance_v028cd"
CLOSE_REL = "automation/stages/close_order55_advance_queue_v028cd.py"
CLOSE_STAGE = ROOT / CLOSE_REL
CLOSE_OUT = "results/order55_native_preflight_v028/order55_disposition_queue_advance_v028cd.json"

ACQUIRE_ID = "order74_poss_identity_acquisition_v028ce"
ACQUIRE_REL = "automation/stages/acquire_order74_poss_identity_v028ce.py"
ACQUIRE_STAGE = ROOT / ACQUIRE_REL
ACQUIRE_OUT = "results/order74_native_preflight_v028/order74_poss_identity_acquisition_v028ce.json"

CLOSE_SOURCE = r'''from __future__ import annotations
from pathlib import Path
import hashlib
import json

ROOT = Path.cwd()
INVENTORY = ROOT / "results" / "existing_identified_pair_inventory_v028ca.json"
AUDIT = ROOT / "results" / "order55_native_preflight_v028" / "order55_timing_provenance_audit_v028cc.json"
OUT = ROOT / "results" / "order55_native_preflight_v028" / "order55_disposition_queue_advance_v028cd.json"


def sha256_file(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def main():
    print("=" * 112)
    print("ORDER 55 — DISPOSITION FREEZE AND EXISTING-PAIR QUEUE ADVANCE v028cd")
    print("=" * 112)
    print("NO NETWORK. NO PIXELS. No detector or source-accounting rewrite.\n")
    inventory = json.loads(INVENTORY.read_text(encoding="utf-8"))
    audit = json.loads(AUDIT.read_text(encoding="utf-8"))
    if int((inventory.get("next_pair") or {}).get("canonical_order", -1)) != 55:
        raise RuntimeError("REFUSING: source inventory does not have Order 55 next")
    if audit.get("classification") != "PHYSICAL_PLATE_TIME_REMOVES_OVERLAP_ORDER55_PAIR_BLOCKED":
        raise RuntimeError("REFUSING: Order-55 terminal timing classification not present")
    if float((audit.get("overlap") or {}).get("physical_header_overlap_s", -1)) != 0:
        raise RuntimeError("REFUSING: physical overlap is not exactly zero")
    remaining = [x for x in inventory.get("processing_plan", []) if int(x["canonical_order"]) != 55]
    if not remaining or int(remaining[0]["canonical_order"]) != 74:
        raise RuntimeError("REFUSING: Order 74 is not the next remaining frozen pair")
    result = {
        "status": "COMPLETE",
        "analysis_kind": "order55_disposition_queue_advance_v028cd",
        "guards": {"network_access": False, "science_pixels_read": False, "non_science_pixels_read": False,
                   "transient_detector_rerun": False, "candidate_state_mutation": False},
        "input_sha256": {str(INVENTORY.relative_to(ROOT)): sha256_file(INVENTORY),
                         str(AUDIT.relative_to(ROOT)): sha256_file(AUDIT)},
        "closed_pair": {"canonical_order": 55, "poss": "POSS-I:606:E:rec348", "dasch": "fa12998",
                        "physical_overlap_s": 0.0,
                        "disposition": "DEMOTED_NO_PHYSICAL_TIME_OVERLAP",
                        "provenance_exception_preserved": True},
        "source_inventory_preserved": True,
        "remaining_pair_count": len(remaining),
        "remaining_orders": [int(x["canonical_order"]) for x in remaining],
        "processing_plan": remaining,
        "next_pair": remaining[0],
        "next_stage": "Acquire exact physical identity for Order 74 before science-pixel work.",
    }
    tmp = OUT.with_suffix(OUT.suffix + ".tmp")
    tmp.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(OUT)
    print("Order 55: DEMOTED — zero physical overlap")
    print(f"Remaining pairs: {len(remaining)}")
    print("Next pair: Order 74")
    print(f"Output: {OUT}\nSTAGE STATUS: PASS")


if __name__ == "__main__":
    main()
'''


def adapt_order74(source: str) -> str:
    replacements = {
        'PAIR_MAP = ROOT / "research" / "SUB5_V028_POSS_PAIR_EXECUTION_MAP_2026-08-21.csv"':
            'PAIR_MAP = ROOT / "research" / "SUB5_V028_POSS_PAIR_EXECUTION_MAP_2026-08-21.csv"',
        'INVENTORY = ROOT / "results" / "existing_identified_pair_inventory_v028ca.json"':
            'INVENTORY = ROOT / "results" / "order55_native_preflight_v028" / "order55_disposition_queue_advance_v028cd.json"',
        'OUT_DIR = ROOT / "results" / "order55_native_preflight_v028"':
            'OUT_DIR = ROOT / "results" / "order74_native_preflight_v028"',
        'OUT = OUT_DIR / "order55_poss_identity_acquisition_v028cb.json"':
            'OUT = OUT_DIR / "order74_poss_identity_acquisition_v028ce.json"',
        'ORDER = 55': 'ORDER = 74',
        'EXPECTED_POSS = "POSS-I:606:E:rec348"': 'EXPECTED_POSS = "POSS-I:318:E:rec524"',
        'EXPECTED_DASCH = "fa12998"': 'EXPECTED_DASCH = "ka02504"',
        'EXPECTED_OVERLAP_S = 3300.000005446': 'EXPECTED_OVERLAP_S = 2940.000009824',
        'UA = "historical-transient-pipeline/0.3.7-order55-identity-acquisition"':
            'UA = "historical-transient-pipeline/0.3.9-order74-identity-acquisition"',
        '"analysis_kind": "order55_poss_identity_acquisition_v028cb"':
            '"analysis_kind": "order74_poss_identity_acquisition_v028ce"',
        'order55_skyview_dss1r_descriptor_v028cb.xml': 'order74_skyview_dss1r_descriptor_v028ce.xml',
        'order55_{region.lower()}_hhh_v028cb.hhh': 'order74_{region.lower()}_hhh_v028ce.hhh',
    }
    for old, new in replacements.items():
        if old not in source:
            raise RuntimeError(f"REFUSING: Order-55 stage marker missing: {old}")
        source = source.replace(old, new)
    source = source.replace("ORDER 55", "ORDER 74").replace("Order-55", "Order-74")
    source = source.replace("Order-55", "Order-74").replace("order55", "order74")
    source = source.replace(
        '"next_stage": "Freeze the resolved Order-74 identity, then preflight/download the exact native science inputs under protocol v1.",',
        '"next_stage": "Audit the physical Order-74 plate time against the paired DASCH exposure before science-pixel work.",'
    )
    ast.parse(source, filename=str(ACQUIRE_STAGE))
    return source


def add_contract(registry: str, contract: str) -> str:
    marker = re.search(r"\n\]\s*\n\s*def by_id\(\):", registry)
    if not marker:
        raise RuntimeError("REFUSING: registry closing marker not found")
    return registry[:marker.start()] + contract + registry[marker.start():]


def main():
    print("=" * 120)
    print("TRANSIENT AUTOMATION UPGRADE v0.3.3 — CLOSE ORDER 55, START ORDER 74")
    print("=" * 120)
    print("NO NETWORK DURING INSTALL. NO PIXELS. No detector or candidate mutation.\n")
    for path in (REGISTRY, INIT, INVENTORY, ORDER55_AUDIT, ORDER55_ID_STAGE):
        if not path.is_file():
            raise RuntimeError(f"Missing required input: {path}")
    audit = json.loads(ORDER55_AUDIT.read_text(encoding="utf-8"))
    if audit.get("classification") != "PHYSICAL_PLATE_TIME_REMOVES_OVERLAP_ORDER55_PAIR_BLOCKED":
        raise RuntimeError("REFUSING: Order 55 has not reached the expected timing disposition")
    ast.parse(CLOSE_SOURCE, filename=str(CLOSE_STAGE))
    acquire_source = adapt_order74(ORDER55_ID_STAGE.read_text(encoding="utf-8"))
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = ROOT / "automation" / "backups" / f"pre_v033_order74_{stamp}"
    backup.mkdir(parents=True, exist_ok=False)
    shutil.copy2(REGISTRY, backup / REGISTRY.name)
    shutil.copy2(INIT, backup / INIT.name)
    CLOSE_STAGE.parent.mkdir(parents=True, exist_ok=True)
    CLOSE_STAGE.write_text(CLOSE_SOURCE, encoding="utf-8", newline="\n")
    ACQUIRE_STAGE.write_text(acquire_source, encoding="utf-8", newline="\n")
    registry = REGISTRY.read_text(encoding="utf-8")
    if CLOSE_ID not in registry:
        registry = add_contract(registry, f'''\n\n    StageContract(\n        stage_id="{CLOSE_ID}",\n        title="Freeze Order-55 zero-overlap disposition and advance existing-pair queue",\n        script="{CLOSE_REL}",\n        requires=("results/order55_native_preflight_v028/order55_timing_provenance_audit_v028cc.json",),\n        produces=("{CLOSE_OUT}",),\n        dependencies=("order55_timing_provenance_audit_v028cc",),\n        notes="No network/pixels; preserves source freeze and advances derived queue to Order 74.",\n    ),\n''')
    if ACQUIRE_ID not in registry:
        registry = add_contract(registry, f'''\n\n    StageContract(\n        stage_id="{ACQUIRE_ID}",\n        title="Acquire and freeze exact POSS plate identity for Order 74",\n        script="{ACQUIRE_REL}",\n        requires=("{CLOSE_OUT}", "research/poss1_pixel_repair_v028_queue.csv"),\n        produces=("{ACQUIRE_OUT}",),\n        dependencies=("{CLOSE_ID}",),\n        network_access=True,\n        notes="Position+epoch descriptor resolution and HHH/DASCH metadata only; no science pixels or state mutation.",\n    ),\n''')
    ast.parse(registry, filename=str(REGISTRY))
    REGISTRY.write_text(registry, encoding="utf-8", newline="\n")
    init = re.sub(r'__version__\s*=\s*["\'][^"\']+["\']', '__version__ = "0.3.9"', INIT.read_text(encoding="utf-8"), count=1)
    ast.parse(init, filename=str(INIT))
    INIT.write_text(init, encoding="utf-8", newline="\n")
    print(f"Installed stages: {CLOSE_ID}, {ACQUIRE_ID}")
    print(f"Backup: {backup}\n\nUPGRADE STATUS: PASS")


if __name__ == "__main__":
    main()
