from __future__ import annotations

"""Install the metadata-only POSS coordinate-reference acquisition stage."""

from pathlib import Path
from datetime import datetime, timezone
import ast
import re
import shutil


ROOT = Path.cwd()
REGISTRY = ROOT / "automation" / "registry_order01.py"
INIT = ROOT / "automation" / "__init__.py"
STAGE = ROOT / "automation" / "stages" / "acquire_survivor_poss_references_v028cj.py"


STAGE_SOURCE = r'''from __future__ import annotations

from pathlib import Path
import ast
import hashlib
import json
import urllib.request

import numpy as np
from astropy.coordinates import SkyCoord
from astropy.io import fits
from astropy.wcs import WCS
from astropy.wcs.utils import fit_wcs_from_points
import astropy.units as u


ROOT = Path.cwd()
PLAN = ROOT / "results" / "physical_overlap_survivor_execution_plan_v028ch.json"
CONTRACT = ROOT / "results" / "parameterized_native_worker_contract_v028ci.json"
GEOMETRY = ROOT / "tools" / "repair_remaining_poss_geometry_v028.py"
OUT_DIR = ROOT / "cache" / "survivor_poss_coordinate_references_v028cj"
OUT_JSON = ROOT / "results" / "survivor_poss_reference_acquisition_v028cj.json"
N = 177


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def load_dss_world():
    tree = ast.parse(GEOMETRY.read_text(encoding="utf-8-sig"), filename=str(GEOMETRY))
    wanted = {"plate_center_radians", "dss_world"}
    nodes = [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name in wanted]
    if {n.name for n in nodes} != wanted:
        raise RuntimeError("REFUSING: exact geometry functions were not recovered")
    module = ast.Module(body=nodes, type_ignores=[])
    ns = {"np": np}
    exec(compile(module, str(GEOMETRY), "exec"), ns)
    return ns["dss_world"]


def fetch(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "transient-pipeline-v028cj/1.0"})
    with urllib.request.urlopen(req, timeout=60) as response:
        if int(getattr(response, "status", 200)) != 200:
            raise RuntimeError(f"HTTP failure for {url}")
        return response.read()


def parse_hhh(raw: bytes):
    if len(raw) < 2880 or not raw.startswith(b"SIMPLE"):
        raise RuntimeError("REFUSING: response is not a FITS-style HHH header")
    return fits.Header.fromstring(raw.decode("ISO-8859-1", errors="replace"), sep="")


def make_reference(hhh, dss_world, region: str, plate_id: str, output: Path):
    if str(hhh.get("REGION", "")).strip().upper() != region:
        raise RuntimeError(f"REFUSING: REGION mismatch for {region}")
    if str(hhh.get("PLATEID", "")).strip().upper() != plate_id:
        raise RuntimeError(f"REFUSING: PLATEID mismatch for {region}")
    fw = int(hhh.get("XPIXELS", 14000))
    fh = int(hhh.get("YPIXELS", 13999))
    if (fw, fh) != (14000, 13999):
        raise RuntimeError(f"REFUSING: unexpected DSS dimensions for {region}: {fw}x{fh}")

    # A small reference centred on the full scanned plate.  It contains no
    # observational pixels: only the exact HHH polynomial and a locally fitted
    # TAN WCS used to cross-check coordinate conventions.
    gx0 = (fw - 1) / 2.0
    gy0 = (fh - 1) / 2.0
    cnpix1 = int(round(gx0 - 88.0 + 1.0))
    cnpix2 = int(round(gy0 - 88.0 + 1.0))
    sample = np.array([0., 44., 88., 132., 176.])
    lx, ly = np.meshgrid(sample, sample)
    gx = lx + float(cnpix1) - 1.0
    gy = ly + float(cnpix2) - 1.0
    ra, dec = dss_world(hhh, gx.ravel() + 1.5, gy.ravel() + 1.5)
    sky = SkyCoord(np.asarray(ra) * u.deg, np.asarray(dec) * u.deg)
    local = fit_wcs_from_points((lx.ravel(), ly.ravel()), sky, projection="TAN")

    header = hhh.copy()
    header["NAXIS"] = 2
    header["NAXIS1"] = N
    header["NAXIS2"] = N
    header["CNPIX1"] = cnpix1
    header["CNPIX2"] = cnpix2
    header["OBJECT"] = "coordinate reference; no science pixels"
    header["REFONLY"] = (True, "synthetic coordinate-reference data array")
    for key, value in local.to_header(relax=True).items():
        header[key] = value

    rw = WCS(header).celestial
    errors = []
    for x, y in ((0., 0.), (88., 88.), (176., 0.), (0., 176.), (176., 176.)):
        a = rw.pixel_to_world(x, y)
        px = x + float(cnpix1) - 1.0
        py = y + float(cnpix2) - 1.0
        r, d = dss_world(header, px + 1.5, py + 1.5)
        b = SkyCoord(float(np.asarray(r)) * u.deg, float(np.asarray(d)) * u.deg)
        errors.append(float(a.separation(b).arcsec))
    maximum = max(errors)
    if maximum > 0.1:
        raise RuntimeError(f"REFUSING: {region} local-WCS error {maximum:.6f} arcsec exceeds 0.1")

    output.parent.mkdir(parents=True, exist_ok=True)
    fits.PrimaryHDU(data=np.zeros((N, N), dtype=np.int16), header=header).writeto(output, overwrite=True, checksum=True)
    return maximum, cnpix1, cnpix2


def main():
    print("=" * 120)
    print("PHYSICAL-OVERLAP SURVIVORS — POSS COORDINATE REFERENCES v028cj")
    print("=" * 120)
    print("NETWORK: exact HHH metadata only. NO SCIENCE PIXELS. No detector or candidate mutation.\n")
    for path in (PLAN, CONTRACT, GEOMETRY):
        if not path.is_file():
            raise RuntimeError(f"Missing required input: {path}")
    plan = json.loads(PLAN.read_text(encoding="utf-8"))
    dss_world = load_dss_world()
    rows = []
    unique = {(p["poss_region"], p["poss_plate_id"], p["poss_hhh_url"]): p for p in plan["pair_execution_plan"]}
    if len(unique) != 4:
        raise RuntimeError(f"REFUSING: expected four unique POSS plates; found {len(unique)}")
    for seq, ((region, plate_id, url), p) in enumerate(sorted(unique.items()), 1):
        raw = fetch(url)
        if sha256_bytes(raw) != p["poss_hhh_sha256"]:
            raise RuntimeError(f"REFUSING: pinned HHH SHA changed for {region}")
        hhh = parse_hhh(raw)
        out = OUT_DIR / p["poss_exposure"].replace(":", "_") / f"{region}_{plate_id}_coordinate_reference.fits"
        error, cx, cy = make_reference(hhh, dss_world, region, plate_id, out)
        used = sorted(x["canonical_order"] for x in plan["pair_execution_plan"] if x["poss_region"] == region)
        rows.append({"region": region, "plate_id": plate_id, "poss_exposure": p["poss_exposure"], "used_by_orders": used,
                     "hhh_url": url, "hhh_sha256": sha256_bytes(raw), "reference_path": str(out.relative_to(ROOT)).replace("\\", "/"),
                     "reference_sha256": sha256_file(out), "shape": [N, N], "cnpix1": cx, "cnpix2": cy,
                     "local_wcs_max_error_arcsec": error, "contains_science_pixels": False})
        print(f"[{seq}/4] {region}/{plate_id}: PASS; local-WCS max error={error:.6f} arcsec")
    result = {"analysis_kind": "survivor_poss_reference_acquisition_v028cj", "status": "COMPLETE",
              "reference_count": len(rows), "references": rows,
              "guards": {"network_access": True, "science_pixels_read": False, "non_science_pixels_read": False,
                         "transient_detector_rerun": False, "candidate_state_mutation": False},
              "next_stage": "Execute the parameterised native worker for Order 11 first, then 28, 29, 24 and 18."}
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"\nOutput: {OUT_JSON}")
    print("STAGE STATUS: PASS")


if __name__ == "__main__":
    main()
'''


CONTRACT = '''    StageContract(
        stage_id="survivor_poss_reference_acquisition_v028cj",
        title="Acquire and validate four metadata-only POSS coordinate references",
        script="automation/stages/acquire_survivor_poss_references_v028cj.py",
        requires=(
            "results/parameterized_native_worker_contract_v028ci.json",
            "results/physical_overlap_survivor_execution_plan_v028ch.json",
            "tools/repair_remaining_poss_geometry_v028.py",
        ),
        produces=("results/survivor_poss_reference_acquisition_v028cj.json",),
        dependencies=("parameterized_native_worker_contract_v028ci",),
        network_access=True,
        notes="Fetches exact pinned HHH metadata and creates zero-data 177x177 coordinate-reference FITS; no science pixels/detector/state mutation.",
    ),
'''


def main():
    print("=" * 120)
    print("TRANSIENT AUTOMATION UPGRADE v0.3.8 — SURVIVOR POSS COORDINATE REFERENCES")
    print("=" * 120)
    print("NO NETWORK DURING INSTALL. NO PIXELS. No detector or candidate mutation.\n")
    for path in (REGISTRY, INIT):
        if not path.is_file():
            raise RuntimeError(f"Missing required file: {path}")
    ast.parse(STAGE_SOURCE, filename=str(STAGE))
    registry = REGISTRY.read_text(encoding="utf-8-sig")
    if "survivor_poss_reference_acquisition_v028cj" in registry:
        raise RuntimeError("REFUSING: v028cj is already registered")
    marker = "]\n\ndef by_id()"
    if marker not in registry:
        raise RuntimeError("REFUSING: registry insertion marker not found")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = ROOT / "automation" / "backups" / f"pre_v038_poss_references_{stamp}"
    backup.mkdir(parents=True, exist_ok=False)
    shutil.copy2(REGISTRY, backup / REGISTRY.name)
    shutil.copy2(INIT, backup / INIT.name)
    if STAGE.exists():
        shutil.copy2(STAGE, backup / STAGE.name)
    STAGE.parent.mkdir(parents=True, exist_ok=True)
    STAGE.write_text(STAGE_SOURCE, encoding="utf-8")
    registry = registry.replace(marker, "\n" + CONTRACT + marker, 1)
    REGISTRY.write_text(registry, encoding="utf-8")
    init = INIT.read_text(encoding="utf-8-sig")
    init = re.sub(r'__version__\s*=\s*["\'][^"\']+["\']', '__version__ = "0.3.8"', init, count=1)
    INIT.write_text(init, encoding="utf-8")
    ast.parse(STAGE.read_text(encoding="utf-8"), filename=str(STAGE))
    ast.parse(REGISTRY.read_text(encoding="utf-8"), filename=str(REGISTRY))
    print("Installed stage: survivor_poss_reference_acquisition_v028cj")
    print(f"Backup: {backup}")
    print("\nUPGRADE STATUS: PASS")


if __name__ == "__main__":
    main()
