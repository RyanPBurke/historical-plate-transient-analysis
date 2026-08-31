from __future__ import annotations

"""Install the final metadata-only preflight for Order 11 native execution."""

from pathlib import Path
from datetime import datetime, timezone
import ast
import re
import shutil


ROOT = Path.cwd()
REGISTRY = ROOT / "automation" / "registry_order01.py"
INIT = ROOT / "automation" / "__init__.py"
STAGE = ROOT / "automation" / "stages" / "preflight_order11_native_execution_v028ck.py"


STAGE_SOURCE = r'''from __future__ import annotations

from pathlib import Path
import hashlib
import json
import math
import shutil
import urllib.parse
import urllib.request

from astropy.io import fits
from astropy.wcs import WCS


ROOT = Path.cwd()
PLAN = ROOT / "results" / "physical_overlap_survivor_execution_plan_v028ch.json"
CONTRACT = ROOT / "results" / "parameterized_native_worker_contract_v028ci.json"
REFERENCES = ROOT / "results" / "survivor_poss_reference_acquisition_v028cj.json"
CONTROL = ROOT / "results" / "pair61_native_detector_control_v028" / "pair61_native_detector_control_report.json"
OUT = ROOT / "results" / "order11_native_preflight_v028" / "order11_native_execution_preflight_v028ck.json"
API = "https://api.starglass.cfa.harvard.edu/public/dasch/dr7/mosaic_package"
EXPECTED_ORDER = 11
EXPECTED_POSS = "POSS-I:779:E:rec404"
EXPECTED_REGION = "XE403"
EXPECTED_PLATE = "0733"
EXPECTED_DASCH = "fa13177"
EXPECTED_OVERLAP_S = 2700.0
EXPECTED_JAR_SHA = "8483a20d986bb61fa1d733ce16d446fb2a0ff363bc1b1367e28b01a1bbdcbb8d"


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def post_package(plate_id: str):
    body = json.dumps({"plate_id": plate_id, "binning": 1}).encode("utf-8")
    request = urllib.request.Request(API, data=body, method="POST", headers={
        "Content-Type": "application/json", "Accept": "application/json",
        "User-Agent": "historical-transient-pipeline-v028ck/1.0"})
    with urllib.request.urlopen(request, timeout=120) as response:
        if int(getattr(response, "status", 200)) != 200:
            raise RuntimeError("REFUSING: DASCH metadata request failed")
        return json.loads(response.read().decode("utf-8"))


def find_jar(control):
    recorded = str(control.get("skyview_jar", "")).strip()
    if recorded:
        p = Path(recorded)
        if not p.is_absolute():
            p = ROOT / p
        if p.is_file() and sha(p) == EXPECTED_JAR_SHA:
            return p
    hits = []
    for p in ROOT.rglob("*.jar"):
        try:
            if sha(p) == EXPECTED_JAR_SHA:
                hits.append(p)
        except OSError:
            pass
    if len(hits) != 1:
        raise RuntimeError(f"REFUSING: expected one validated SkyView JAR; found {len(hits)}")
    return hits[0]


def main():
    print("=" * 120)
    print("ORDER 11 — FINAL NATIVE EXECUTION PREFLIGHT v028ck")
    print("=" * 120)
    print("NETWORK: DASCH package metadata only. NO SCIENCE PIXELS. No detector or candidate mutation.\n")
    for p in (PLAN, CONTRACT, REFERENCES, CONTROL):
        if not p.is_file():
            raise RuntimeError(f"Missing required input: {p}")
    plan = json.loads(PLAN.read_text(encoding="utf-8"))
    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    refs = json.loads(REFERENCES.read_text(encoding="utf-8"))
    control = json.loads(CONTROL.read_text(encoding="utf-8"))
    if contract.get("status") != "COMPLETE" or refs.get("status") != "COMPLETE":
        raise RuntimeError("REFUSING: worker contract or reference acquisition is incomplete")

    rows = [x for x in plan["pair_execution_plan"] if int(x["canonical_order"]) == EXPECTED_ORDER]
    if len(rows) != 1:
        raise RuntimeError(f"REFUSING: expected one Order-11 plan row; found {len(rows)}")
    row = rows[0]
    guards = {
        "poss": row["poss_exposure"] == EXPECTED_POSS,
        "region": row["poss_region"] == EXPECTED_REGION,
        "plate": row["poss_plate_id"] == EXPECTED_PLATE,
        "dasch": row["dasch_plate"] == EXPECTED_DASCH,
        "overlap": abs(float(row["physical_overlap_s"]) - EXPECTED_OVERLAP_S) < 1e-6,
        "priority": int(row["execution_priority"]) == 1,
    }
    if not all(guards.values()):
        raise RuntimeError(f"REFUSING: frozen Order-11 identity guard failure: {guards}")

    rr = [x for x in refs["references"] if x["region"] == EXPECTED_REGION]
    if len(rr) != 1:
        raise RuntimeError(f"REFUSING: expected one XE403 reference; found {len(rr)}")
    ref = ROOT / rr[0]["reference_path"]
    if not ref.is_file() or sha(ref) != rr[0]["reference_sha256"]:
        raise RuntimeError("REFUSING: XE403 reference missing or checksum changed")
    h = fits.getheader(ref, 0)
    if str(h.get("REGION", "")).strip().upper() != EXPECTED_REGION or str(h.get("PLATEID", "")).strip().upper() != EXPECTED_PLATE:
        raise RuntimeError("REFUSING: XE403 reference identity changed")
    if not bool(h.get("REFONLY", False)) or not WCS(h).celestial.has_celestial:
        raise RuntimeError("REFUSING: XE403 coordinate reference contract failed")
    if (int(h["XPIXELS"]), int(h["YPIXELS"])) != (14000, 13999):
        raise RuntimeError("REFUSING: XE403 full dimensions changed")

    jar = find_jar(control)
    pkg = post_package(EXPECTED_DASCH)
    if not pkg.get("baseFitsUrl") or not pkg.get("metadata"):
        raise RuntimeError("REFUSING: DASCH package metadata is incomplete")
    astrom = pkg["metadata"].get("astrometry", {})
    mosaic = pkg["metadata"].get("mosaic", {})
    geometry = {
        "b01HeaderGz": astrom.get("b01HeaderGz"),
        "rotationDelta": astrom.get("rotationDelta"),
        "b01Height": int(mosaic["b01Height"]),
        "b01Width": int(mosaic["b01Width"]),
    }
    if not geometry["b01HeaderGz"]:
        raise RuntimeError("REFUSING: DASCH TPV header metadata missing")
    geometry_sha = hashlib.sha256(json.dumps(geometry, sort_keys=True).encode()).hexdigest()
    signed = str(pkg["baseFitsUrl"])
    unsigned_location = urllib.parse.urlunsplit(urllib.parse.urlsplit(signed)._replace(query=""))
    package_bytes = int(pkg.get("baseFitsSize") or 0)
    if package_bytes <= 0:
        raise RuntimeError("REFUSING: DASCH package size is missing")
    disk = shutil.disk_usage(ROOT)
    poss_tiles = math.ceil(14000 / 1024) * math.ceil(13999 / 1024)
    minimum_free = max(5 * package_bytes, 10 * 1024**3)
    if disk.free < minimum_free:
        raise RuntimeError(f"REFUSING: insufficient free disk; {disk.free} bytes available, {minimum_free} required")

    result = {
        "analysis_kind": "order11_native_execution_preflight_v028ck", "status": "COMPLETE",
        "order": EXPECTED_ORDER, "frozen_identity_guards": guards, "plan_row": row,
        "poss": {"coordinate_reference": str(ref.relative_to(ROOT)).replace("\\", "/"),
                 "reference_sha256": sha(ref), "full_shape": [13999, 14000], "planned_core_tiles": poss_tiles},
        "skyview_jar": {"path": str(jar.relative_to(ROOT)).replace("\\", "/"), "sha256": sha(jar)},
        "dasch": {"plate_id": EXPECTED_DASCH, "package_location_without_signature": unsigned_location,
                  "base_fits_size_bytes": package_bytes, "geometry": geometry, "geometry_sha256": geometry_sha},
        "capacity": {"free_bytes": disk.free, "minimum_required_bytes": minimum_free, "pass": True},
        "guards": {"network_access": True, "science_pixels_read": False, "non_science_pixels_read": False,
                   "transient_detector_rerun": False, "candidate_state_mutation": False},
        "next_stage": "Execute resumable frozen native detector for Order 11."
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print("Frozen Order-11 identity: PASS")
    print("XE403 coordinate reference: PASS")
    print("Validated SkyView extractor JAR: PASS")
    print(f"POSS planned core tiles: {poss_tiles}")
    print(f"DASCH bin1 package: {package_bytes / 1024**2:.1f} MiB")
    print(f"Free disk: {disk.free / 1024**3:.1f} GiB; required floor: {minimum_free / 1024**3:.1f} GiB")
    print(f"Output: {OUT}")
    print("STAGE STATUS: PASS")


if __name__ == "__main__":
    main()
'''


CONTRACT = '''    StageContract(
        stage_id="order11_native_execution_preflight_v028ck",
        title="Final metadata and capacity preflight for Order 11 native execution",
        script="automation/stages/preflight_order11_native_execution_v028ck.py",
        requires=(
            "results/survivor_poss_reference_acquisition_v028cj.json",
            "results/parameterized_native_worker_contract_v028ci.json",
            "results/physical_overlap_survivor_execution_plan_v028ch.json",
            "results/pair61_native_detector_control_v028/pair61_native_detector_control_report.json",
        ),
        produces=("results/order11_native_preflight_v028/order11_native_execution_preflight_v028ck.json",),
        dependencies=("survivor_poss_reference_acquisition_v028cj",),
        network_access=True,
        notes="Metadata-only Order-11 identity, reference, JAR, DASCH geometry and disk-capacity gate before native pixels.",
    ),
'''


def main():
    print("=" * 120)
    print("TRANSIENT AUTOMATION UPGRADE v0.3.9 — ORDER-11 NATIVE EXECUTION PREFLIGHT")
    print("=" * 120)
    print("NO NETWORK DURING INSTALL. NO PIXELS. No detector or candidate mutation.\n")
    for p in (REGISTRY, INIT):
        if not p.is_file():
            raise RuntimeError(f"Missing required file: {p}")
    ast.parse(STAGE_SOURCE, filename=str(STAGE))
    registry = REGISTRY.read_text(encoding="utf-8-sig")
    if "order11_native_execution_preflight_v028ck" in registry:
        raise RuntimeError("REFUSING: v028ck already registered")
    marker = "]\n\ndef by_id()"
    if marker not in registry:
        raise RuntimeError("REFUSING: registry insertion marker not found")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = ROOT / "automation" / "backups" / f"pre_v039_order11_preflight_{stamp}"
    backup.mkdir(parents=True, exist_ok=False)
    shutil.copy2(REGISTRY, backup / REGISTRY.name)
    shutil.copy2(INIT, backup / INIT.name)
    if STAGE.exists():
        shutil.copy2(STAGE, backup / STAGE.name)
    STAGE.parent.mkdir(parents=True, exist_ok=True)
    STAGE.write_text(STAGE_SOURCE, encoding="utf-8")
    REGISTRY.write_text(registry.replace(marker, "\n" + CONTRACT + marker, 1), encoding="utf-8")
    init = INIT.read_text(encoding="utf-8-sig")
    init = re.sub(r'__version__\s*=\s*["\'][^"\']+["\']', '__version__ = "0.3.9"', init, count=1)
    INIT.write_text(init, encoding="utf-8")
    ast.parse(STAGE.read_text(encoding="utf-8"), filename=str(STAGE))
    ast.parse(REGISTRY.read_text(encoding="utf-8"), filename=str(REGISTRY))
    print("Installed stage: order11_native_execution_preflight_v028ck")
    print(f"Backup: {backup}")
    print("\nUPGRADE STATUS: PASS")


if __name__ == "__main__":
    main()
