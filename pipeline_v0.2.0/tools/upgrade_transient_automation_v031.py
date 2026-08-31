from __future__ import annotations

from pathlib import Path
import ast
import csv
import datetime as dt
import hashlib
import json
import re
import shutil

from astropy.io import fits


ROOT = Path.cwd()
PAIR_MAP = ROOT / "research" / "SUB5_V028_POSS_PAIR_EXECUTION_MAP_2026-08-21.csv"
INVENTORY = ROOT / "results" / "existing_identified_pair_inventory_v028ca.json"
TEMPLATE = ROOT / "tools" / "preflight_order01_exact_native_source_v028.py"
REGISTRY = ROOT / "automation" / "registry_order01.py"
INIT = ROOT / "automation" / "__init__.py"

STAGE_ID = "order55_exact_native_source_metadata_preflight_v028cb"
STAGE_REL = "automation/stages/preflight_order55_exact_native_source_v028cb.py"
STAGE = ROOT / STAGE_REL
OUTPUT_REL = "results/order55_native_preflight_v028/order55_exact_native_source_and_dasch_metadata_v028cb.json"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def read_rows(path: Path):
    with path.open(newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def one_order(rows, order: int):
    hits = []
    for row in rows:
        try:
            if int(float(str(row.get("canonical_order", "")).strip())) == order:
                hits.append(row)
        except ValueError:
            pass
    if len(hits) != 1:
        raise RuntimeError(f"REFUSING: expected exactly one Order {order} pair-map row; got {len(hits)}")
    return hits[0]


def quoted(value) -> str:
    return json.dumps(value)


def main():
    print("=" * 120)
    print("TRANSIENT AUTOMATION UPGRADE v0.3.1 — ORDER-55 EXACT NATIVE METADATA PREFLIGHT")
    print("=" * 120)
    print("NO NETWORK ACCESS. NO SCIENCE PIXELS ARE READ. No detector or candidate state is changed.\n")

    for path in (PAIR_MAP, INVENTORY, TEMPLATE, REGISTRY, INIT):
        if not path.is_file():
            raise RuntimeError(f"Missing required input: {path}")

    inv = json.loads(INVENTORY.read_text(encoding="utf-8"))
    nxt = inv.get("next_pair") or {}
    if int(nxt.get("canonical_order", -1)) != 55:
        raise RuntimeError("REFUSING: frozen inventory does not identify Order 55 as next_pair")
    if int(inv.get("remaining_pair_count", -1)) != 10:
        raise RuntimeError("REFUSING: expected 10 remaining pairs in frozen inventory")

    rows = read_rows(PAIR_MAP)
    row = one_order(rows, 55)
    poss = str(row.get("poss_exposure_id", "")).strip()
    dasch = str(row.get("partner_dasch_plate_id", "")).strip().lower()
    region = str(row.get("poss_region", "")).strip().upper()
    band = poss.split(":")[2].upper() if len(poss.split(":")) >= 3 else ""
    overlap = float(row["actual_overlap_s"])
    identity_path = Path(row["poss_fits_path"])
    if not identity_path.is_file():
        raise RuntimeError(f"Missing frozen Order-55 identity FITS: {identity_path}")

    with fits.open(identity_path, memmap=False, do_not_scale_image_data=True) as hdul:
        hdr = hdul[0].header
        plate_id = str(hdr.get("PLATEID", "")).strip().upper()
        fits_region = str(hdr.get("REGION", "")).strip().upper()
    if not all((poss, dasch, region, band, plate_id)):
        raise RuntimeError("REFUSING: incomplete Order-55 identity fields")
    if region != fits_region:
        raise RuntimeError(f"REFUSING: pair-map region {region} != FITS region {fits_region}")
    if sha256_file(identity_path).lower() != str(row["poss_fits_sha256"]).strip().lower():
        raise RuntimeError("REFUSING: Order-55 frozen identity FITS SHA mismatch")
    if abs(overlap - float(nxt["actual_exposure_overlap_s"])) > 1e-6:
        raise RuntimeError("REFUSING: Order-55 inventory/pair-map overlap mismatch")

    text = TEMPLATE.read_text(encoding="utf-8")
    replacements = {
        "ORDER = 1": "ORDER = 55",
        'EXPECTED_POSS = "POSS-I:413:E:rec297"': f"EXPECTED_POSS = {quoted(poss)}",
        'EXPECTED_BAND = "E"': f"EXPECTED_BAND = {quoted(band)}",
        'EXPECTED_REGION = "XE296"': f"EXPECTED_REGION = {quoted(region)}",
        'EXPECTED_PLATE_ID = "06S2"': f"EXPECTED_PLATE_ID = {quoted(plate_id)}",
        'EXPECTED_DASCH = "ai43437"': f"EXPECTED_DASCH = {quoted(dasch)}",
        "EXPECTED_OVERLAP_S = 3480.0": f"EXPECTED_OVERLAP_S = {overlap!r}",
        'OUT_DIR = ROOT / "results" / "order01_native_preflight_v028"': 'OUT_DIR = ROOT / "results" / "order55_native_preflight_v028"',
        'OUT = OUT_DIR / "order01_exact_native_source_and_dasch_metadata_v028.json"': 'OUT = OUT_DIR / "order55_exact_native_source_and_dasch_metadata_v028cb.json"',
        'DESC_COPY = OUT_DIR / "order01_skyview_dss1r_descriptor_v028.xml"': 'DESC_COPY = OUT_DIR / "order55_skyview_dss1r_descriptor_v028cb.xml"',
        'HHH_COPY = OUT_DIR / "order01_xe296_hhh_v028.hhh"': f'HHH_COPY = OUT_DIR / "order55_{region.lower()}_hhh_v028cb.hhh"',
        'UA = "historical-transient-pipeline/0.2.8-order01-exact-native-metadata-preflight"': 'UA = "historical-transient-pipeline/0.3.7-order55-exact-native-metadata-preflight"',
        'shape = tuple(int(x) for x in hdul[0].data.shape)': 'shape = (int(h.get("NAXIS2", 0)), int(h.get("NAXIS1", 0)))',
        'expected_raw_dir = "https://skyview.gsfc.nasa.gov/surveys/dss/xe296"': f'expected_raw_dir = "https://skyview.gsfc.nasa.gov/surveys/dss/{region.lower()}"',
        '"analysis_kind": "order01_exact_native_source_and_dasch_metadata_v028",': '"analysis_kind": "order55_exact_native_source_and_dasch_metadata_v028cb",',
    }
    for old, new in replacements.items():
        if old not in text:
            raise RuntimeError(f"REFUSING: template marker not found: {old}")
        text = text.replace(old, new, 1)

    text = text.replace("ORDER 01", "ORDER 55").replace("Order-1", "Order-55")
    text = text.replace("Order-1 input", "Order-55 input")
    text = text.replace("XE296", region).replace("xe296", region.lower())
    text = text.replace("ai43437", dasch)
    result_marker = "    result = {\n"
    if result_marker not in text:
        raise RuntimeError("REFUSING: result marker missing from template")
    guard_block = (
        '    result = {\n'
        '        "guards": {\n'
        '            "network_access": True,\n'
        '            "science_pixels_read": False,\n'
        '            "non_science_pixels_read": False,\n'
        '            "transient_detector_rerun": False,\n'
        '            "candidate_state_mutation": False,\n'
        '        },\n'
        f'        "frozen_inventory_sha256": {quoted(sha256_file(INVENTORY))},\n'
    )
    text = text.replace(result_marker, guard_block, 1)
    ast.parse(text, filename=str(STAGE))

    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = ROOT / "automation" / "backups" / f"pre_v031_order55_preflight_{stamp}"
    backup.mkdir(parents=True, exist_ok=False)
    shutil.copy2(REGISTRY, backup / REGISTRY.name)
    shutil.copy2(INIT, backup / INIT.name)
    if STAGE.exists():
        shutil.copy2(STAGE, backup / STAGE.name)

    STAGE.parent.mkdir(parents=True, exist_ok=True)
    STAGE.write_text(text, encoding="utf-8", newline="\n")

    registry = REGISTRY.read_text(encoding="utf-8")
    if STAGE_ID not in registry:
        marker = re.search(r"\n\]\s*\n\s*def by_id\(\):", registry)
        if not marker:
            raise RuntimeError("REFUSING: could not locate ORDER01_STAGES closing marker")
        contract = f'''\n\n    StageContract(\n        stage_id="{STAGE_ID}",\n        title="Resolve exact native POSS and DASCH metadata for frozen Order 55",\n        script="{STAGE_REL}",\n        requires=(\n            "results/existing_identified_pair_inventory_v028ca.json",\n            "research/SUB5_V028_POSS_PAIR_EXECUTION_MAP_2026-08-21.csv",\n        ),\n        produces=(\n            "{OUTPUT_REL}",\n        ),\n        dependencies=("existing_identified_pair_inventory_v028ca",),\n        network_access=True,\n        notes="Descriptor, HHH and DASCH package metadata only; no science tile/mosaic, detector, or candidate mutation.",\n    ),\n'''
        registry = registry[:marker.start()] + contract + registry[marker.start():]
        ast.parse(registry, filename=str(REGISTRY))
        REGISTRY.write_text(registry, encoding="utf-8", newline="\n")

    init_text = INIT.read_text(encoding="utf-8")
    init_text = re.sub(r'__version__\s*=\s*["\'][^"\']+["\']', '__version__ = "0.3.7"', init_text, count=1)
    ast.parse(init_text, filename=str(INIT))
    INIT.write_text(init_text, encoding="utf-8", newline="\n")

    print(f"Order 55: {poss} -> {region} / {plate_id}; DASCH {dasch}")
    print(f"Overlap: {overlap:.6f} s ({overlap / 60.0:.3f} min)")
    print(f"Installed stage: {STAGE_ID}")
    print(f"Backup: {backup}")
    print("\nUPGRADE STATUS: PASS")


if __name__ == "__main__":
    main()
