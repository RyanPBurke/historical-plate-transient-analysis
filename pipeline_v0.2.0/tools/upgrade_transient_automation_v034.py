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
SOURCE_STAGE = ROOT / "automation" / "stages" / "audit_order55_timing_provenance_v028cc.py"
IDENTITY = ROOT / "results" / "order74_native_preflight_v028" / "order74_poss_identity_acquisition_v028ce.json"
STAGE_ID = "order74_timing_provenance_audit_v028cf"
STAGE_REL = "automation/stages/audit_order74_timing_provenance_v028cf.py"
STAGE = ROOT / STAGE_REL
OUT_REL = "results/order74_native_preflight_v028/order74_timing_provenance_audit_v028cf.json"


def adapt(source: str) -> str:
    replacements = {
        'IDENTITY = ROOT / "results" / "order55_native_preflight_v028" / "order55_poss_identity_acquisition_v028cb.json"':
            'IDENTITY = ROOT / "results" / "order74_native_preflight_v028" / "order74_poss_identity_acquisition_v028ce.json"',
        'OUT = ROOT / "results" / "order55_native_preflight_v028" / "order55_timing_provenance_audit_v028cc.json"':
            'OUT = ROOT / "results" / "order74_native_preflight_v028" / "order74_timing_provenance_audit_v028cf.json"',
        'ORDER = 55': 'ORDER = 74',
        'EXPECTED_POSS = "POSS-I:606:E:rec348"': 'EXPECTED_POSS = "POSS-I:318:E:rec524"',
        'EXPECTED_DASCH = "fa12998"': 'EXPECTED_DASCH = "ka02504"',
        'resolved.get("region") != "XE347"': 'resolved.get("region") != "XE523"',
        'str(resolved.get("plate_id", "")).upper() != "06RF"':
            'str(resolved.get("plate_id", "")).upper() != "090Q"',
        '"analysis_kind": "order55_timing_provenance_audit_v028cc"':
            '"analysis_kind": "order74_timing_provenance_audit_v028cf"',
        '"PHYSICAL_PLATE_TIME_REMOVES_OVERLAP_ORDER55_PAIR_BLOCKED"':
            '"PHYSICAL_PLATE_TIME_REMOVES_OVERLAP_ORDER74_PAIR_BLOCKED"',
        '"Advance to Order 74 if physical overlap is zero; preserve Order 55 as a timing-provenance exception."':
            '"If physical timing passes, proceed to exact native-input preflight; otherwise close Order 74 and advance the queue."',
    }
    for old, new in replacements.items():
        if old not in source:
            raise RuntimeError(f"REFUSING: timing-stage marker missing: {old}")
        source = source.replace(old, new)
    source = source.replace("ORDER 55", "ORDER 74").replace("Order-55", "Order-74")
    ast.parse(source, filename=str(STAGE))
    return source


def main():
    print("=" * 120)
    print("TRANSIENT AUTOMATION UPGRADE v0.3.4 — ORDER-74 TIMING PROVENANCE AUDIT")
    print("=" * 120)
    print("NO NETWORK. NO PIXELS. No detector or candidate mutation.\n")
    for path in (REGISTRY, INIT, SOURCE_STAGE, IDENTITY):
        if not path.is_file():
            raise RuntimeError(f"Missing required input: {path}")
    identity = json.loads(IDENTITY.read_text(encoding="utf-8"))
    resolved = identity.get("resolved_poss_identity") or {}
    if resolved.get("region") != "XE523" or str(resolved.get("plate_id", "")).upper() != "090Q":
        raise RuntimeError("REFUSING: Order-74 identity is not verified XE523/090Q")
    stage_source = adapt(SOURCE_STAGE.read_text(encoding="utf-8"))
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = ROOT / "automation" / "backups" / f"pre_v034_order74_timing_{stamp}"
    backup.mkdir(parents=True, exist_ok=False)
    shutil.copy2(REGISTRY, backup / REGISTRY.name)
    shutil.copy2(INIT, backup / INIT.name)
    STAGE.parent.mkdir(parents=True, exist_ok=True)
    STAGE.write_text(stage_source, encoding="utf-8", newline="\n")
    registry = REGISTRY.read_text(encoding="utf-8")
    if STAGE_ID not in registry:
        marker = re.search(r"\n\]\s*\n\s*def by_id\(\):", registry)
        if not marker:
            raise RuntimeError("REFUSING: registry closing marker not found")
        contract = f'''\n\n    StageContract(\n        stage_id="{STAGE_ID}",\n        title="Audit Order-74 physical plate time and recompute true overlap",\n        script="{STAGE_REL}",\n        requires=("results/order74_native_preflight_v028/order74_poss_identity_acquisition_v028ce.json", "research/poss1_pixel_repair_v028_queue.csv"),\n        produces=("{OUT_REL}",),\n        dependencies=("order74_poss_identity_acquisition_v028ce",),\n        notes="No network/pixels; compares catalogue interval with physical HHH DATE-OBS before native execution.",\n    ),\n'''
        registry = registry[:marker.start()] + contract + registry[marker.start():]
        ast.parse(registry, filename=str(REGISTRY))
        REGISTRY.write_text(registry, encoding="utf-8", newline="\n")
    init = re.sub(r'__version__\s*=\s*["\'][^"\']+["\']', '__version__ = "0.3.10"', INIT.read_text(encoding="utf-8"), count=1)
    ast.parse(init, filename=str(INIT))
    INIT.write_text(init, encoding="utf-8", newline="\n")
    print(f"Installed stage: {STAGE_ID}")
    print(f"Backup: {backup}\n\nUPGRADE STATUS: PASS")


if __name__ == "__main__":
    main()
