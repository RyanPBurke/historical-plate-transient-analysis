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
PAIR_MAP = ROOT / "research" / "SUB5_V028_POSS_PAIR_EXECUTION_MAP_2026-08-21.csv"
QUEUE = ROOT / "research" / "poss1_pixel_repair_v028_queue.csv"
STAGE_ID = "order55_poss_identity_acquisition_v028cb"
STAGE_REL = "automation/stages/acquire_order55_poss_identity_v028cb.py"
STAGE = ROOT / STAGE_REL
OUT_REL = "results/order55_native_preflight_v028/order55_poss_identity_acquisition_v028cb.json"

STAGE_SOURCE = r'''from __future__ import annotations

from pathlib import Path
import csv
import datetime as dt
import hashlib
import json
import math
import urllib.request

from astropy.io import fits
from transient_pipeline.poss1_skyview import (
    SKYVIEW_DSS1R_DESCRIPTOR,
    parse_skyview_descriptor,
    raw_plate_directory,
    hhh_identity,
)

ROOT = Path.cwd()
PAIR_MAP = ROOT / "research" / "SUB5_V028_POSS_PAIR_EXECUTION_MAP_2026-08-21.csv"
QUEUE = ROOT / "research" / "poss1_pixel_repair_v028_queue.csv"
INVENTORY = ROOT / "results" / "existing_identified_pair_inventory_v028ca.json"
OUT_DIR = ROOT / "results" / "order55_native_preflight_v028"
OUT = OUT_DIR / "order55_poss_identity_acquisition_v028cb.json"
DASCH_API = "https://api.starglass.cfa.harvard.edu/public/dasch/dr7/mosaic_package"
ORDER = 55
EXPECTED_POSS = "POSS-I:606:E:rec348"
EXPECTED_DASCH = "fa12998"
EXPECTED_OVERLAP_S = 3300.000005446
UA = "historical-transient-pipeline/0.3.7-order55-identity-acquisition"


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


def sha256_bytes(raw):
    return hashlib.sha256(raw).hexdigest()


def get_bytes(url, accept="*/*"):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": accept})
    with urllib.request.urlopen(req, timeout=90) as response:
        return response.read(), getattr(response, "status", None), response.geturl(), response.headers.get("Content-Type")


def post_json(url, payload):
    raw = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=raw, method="POST", headers={
        "User-Agent": UA, "Accept": "application/json", "Content-Type": "application/json"
    })
    with urllib.request.urlopen(req, timeout=90) as response:
        return json.loads(response.read().decode("utf-8")), getattr(response, "status", None), response.geturl()


def sep_arcsec(ra1, dec1, ra2, dec2):
    r1, d1, r2, d2 = map(math.radians, map(float, (ra1, dec1, ra2, dec2)))
    a = math.sin((d2-d1)/2)**2 + math.cos(d1)*math.cos(d2)*math.sin((r2-r1)/2)**2
    return math.degrees(2*math.asin(math.sqrt(min(1.0, max(0.0, a))))) * 3600


def decimal_year(value):
    t = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    start = dt.datetime(t.year, 1, 1, tzinfo=t.tzinfo)
    end = dt.datetime(t.year + 1, 1, 1, tzinfo=t.tzinfo)
    return t.year + (t-start).total_seconds()/(end-start).total_seconds()


def parse_hhh(raw):
    text = raw.decode("ISO-8859-1", errors="replace")
    header = fits.Header.fromstring(text, sep="")
    keys = ("PLATEID", "REGION", "DATE-OBS", "XPIXELS", "YPIXELS", "PLTSCALE",
            "PLTRAH", "PLTRAM", "PLTRAS", "PLTDECSN", "PLTDECD", "PLTDECM", "PLTDECS")
    return {k: header[k] for k in keys if k in header}


def main():
    print("=" * 120)
    print("ORDER 55 — POSS IDENTITY ACQUISITION + DASCH METADATA PREFLIGHT v028cb")
    print("=" * 120)
    print("Metadata only: no DSS science tile, no DASCH mosaic, no detector, no candidate mutation.\n")
    for path in (PAIR_MAP, QUEUE, INVENTORY):
        if not path.is_file():
            raise RuntimeError(f"Missing required input: {path}")

    pair = one_order(read_csv(PAIR_MAP))
    queue = one_order(read_csv(QUEUE))
    inv = json.loads(INVENTORY.read_text(encoding="utf-8"))
    guards = {
        "inventory_next_order": int((inv.get("next_pair") or {}).get("canonical_order", -1)) == ORDER,
        "poss_exposure": EXPECTED_POSS in (str(pair) + str(queue)),
        "dasch_plate": EXPECTED_DASCH in (str(pair).lower() + str(queue).lower()),
        "overlap": abs(float(queue["actual_exposure_overlap_s"]) - EXPECTED_OVERLAP_S) < 1e-6,
        "true_wcs_intersection": str(queue["true_wcs_intersection"]).strip().lower() == "true",
    }
    if not all(guards.values()):
        raise RuntimeError("REFUSING: frozen Order-55 guards failed: " + repr(guards))

    if "POSS" in str(queue.get("archive_a", "")).upper():
        ra, dec, observed = queue["ra_a_deg"], queue["dec_a_deg"], queue["start_a_utc"]
    else:
        ra, dec, observed = queue["ra_b_deg"], queue["dec_b_deg"], queue["start_b_utc"]
    ra, dec, epoch = float(ra), float(dec), decimal_year(observed)

    print(f"Frozen target: {EXPECTED_POSS}; RA={ra:.9f} Dec={dec:+.9f}; epoch={epoch:.6f}")
    print("[1/3] Fetching DSS1R descriptor and resolving by position plus observation epoch ...", flush=True)
    desc_raw, desc_status, desc_url, desc_type = get_bytes(SKYVIEW_DSS1R_DESCRIPTOR, "application/xml,*/*")
    desc = parse_skyview_descriptor(desc_raw)
    ranked = []
    for entry in desc.images:
        try:
            separation = sep_arcsec(ra, dec, entry.ra_deg, entry.dec_deg) / 3600.0
            epoch_delta = abs(float(entry.epoch) - epoch)
        except (TypeError, ValueError):
            continue
        ranked.append((epoch_delta, separation, entry))
    ranked.sort(key=lambda x: (x[0], x[1], x[2].path))
    plausible = [x for x in ranked if x[0] <= 0.02 and x[1] <= 5.0]
    if len(plausible) != 1:
        top = [{"path": x[2].path, "epoch_delta_year": x[0], "center_sep_deg": x[1]} for x in ranked[:12]]
        raise RuntimeError(f"REFUSING: expected one position+epoch plate match; got {len(plausible)}; top={top}")
    epoch_delta, center_sep, entry = plausible[0]
    region = Path(entry.path).name.upper()
    raw_dir = raw_plate_directory(band="E", region=region, descriptor_entry=entry)
    expected_dir = f"https://skyview.gsfc.nasa.gov/surveys/dss/{region.lower()}"
    if raw_dir.rstrip("/").lower() != expected_dir.lower():
        raise RuntimeError(f"REFUSING: unexpected native directory {raw_dir}")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    desc_copy = OUT_DIR / "order55_skyview_dss1r_descriptor_v028cb.xml"
    desc_copy.write_bytes(desc_raw)
    print(f"  exact match: {entry.path}; region={region}; center separation={center_sep:.3f} deg; epoch delta={epoch_delta:.6f} yr")

    print("[2/3] Fetching and validating exact HHH plate metadata ...", flush=True)
    hhh_url = f"{raw_dir}/{region.lower()}.hhh"
    hhh_raw, hhh_status, hhh_final, hhh_type = get_bytes(hhh_url, "application/octet-stream,*/*")
    if len(hhh_raw) < 2880 or not hhh_raw.startswith(b"SIMPLE"):
        raise RuntimeError("REFUSING: HHH response is not FITS-style metadata")
    hident = hhh_identity(hhh_raw)
    if str(hident.get("region", "")).strip().upper() != region or not str(hident.get("plate_id", "")).strip():
        raise RuntimeError("REFUSING: HHH region/plate identity failed: " + repr(hident))
    hhh_copy = OUT_DIR / f"order55_{region.lower()}_hhh_v028cb.hhh"
    hhh_copy.write_bytes(hhh_raw)
    print(f"  REGION={region} PLATEID={hident['plate_id']} DATE-OBS={hident.get('date_obs')} PASS")

    print(f"[3/3] Fetching {EXPECTED_DASCH} package metadata ...", flush=True)
    pkg, dasch_status, dasch_url = post_json(DASCH_API, {"plate_id": EXPECTED_DASCH, "binning": 1})
    if not pkg.get("baseFitsUrl") or pkg.get("metadata") is None:
        raise RuntimeError("REFUSING: incomplete DASCH package metadata")

    result = {
        "status": "COMPLETE",
        "analysis_kind": "order55_poss_identity_acquisition_v028cb",
        "guards": {"network_access": True, "science_pixels_read": False, "non_science_pixels_read": False,
                   "transient_detector_rerun": False, "candidate_state_mutation": False},
        "frozen_input_guards": guards,
        "pair": {"order": ORDER, "poss": EXPECTED_POSS, "dasch": EXPECTED_DASCH,
                 "overlap_s": EXPECTED_OVERLAP_S, "ra_deg": ra, "dec_deg": dec, "observed": observed},
        "selection_contract": {"position_radius_deg": 5.0, "epoch_tolerance_year": 0.02,
                               "plausible_match_count": len(plausible), "descriptor_image_count": len(desc.images)},
        "resolved_poss_identity": {"band": "E", "region": region, "plate_id": hident["plate_id"],
                                   "descriptor_path": entry.path, "descriptor_epoch": entry.epoch,
                                   "epoch_delta_year": epoch_delta, "center_separation_deg": center_sep,
                                   "raw_plate_directory": raw_dir, "hhh_url": hhh_url,
                                   "hhh_sha256": sha256_bytes(hhh_raw), "hhh_identity": hident,
                                   "hhh_header": parse_hhh(hhh_raw), "native_science_tile_requested": False},
        "descriptor": {"url": SKYVIEW_DSS1R_DESCRIPTOR, "http_status": desc_status,
                       "final_url": desc_url, "content_type": desc_type, "sha256": sha256_bytes(desc_raw),
                       "saved_copy": str(desc_copy)},
        "dasch_package": {"api": DASCH_API, "http_status": dasch_status, "final_url": dasch_url,
                          "baseFitsUrl": pkg.get("baseFitsUrl"), "baseFitsSize": pkg.get("baseFitsSize"),
                          "metadata": pkg.get("metadata"), "science_mosaic_downloaded": False},
        "candidate_promoted": False,
        "candidate_deleted": False,
        "next_stage": "Freeze the resolved Order-55 identity, then preflight/download the exact native science inputs under protocol v1.",
    }
    tmp = OUT.with_suffix(OUT.suffix + ".tmp")
    tmp.write_text(json.dumps(result, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    tmp.replace(OUT)
    print(f"\nResolved identity: {EXPECTED_POSS} -> {region} / {hident['plate_id']}")
    print(f"Output: {OUT}\nSTAGE STATUS: PASS")


if __name__ == "__main__":
    main()
'''


def main():
    print("=" * 120)
    print("TRANSIENT AUTOMATION REPAIR v0.3.1c — ORDER-55 METADATA IDENTITY ACQUISITION")
    print("=" * 120)
    print("NO NETWORK ACCESS DURING INSTALL. NO PIXELS. No detector or candidate mutation.\n")
    for path in (REGISTRY, INIT, INVENTORY, PAIR_MAP, QUEUE):
        if not path.is_file():
            raise RuntimeError(f"Missing required input: {path}")
    inv = json.loads(INVENTORY.read_text(encoding="utf-8"))
    if int((inv.get("next_pair") or {}).get("canonical_order", -1)) != 55:
        raise RuntimeError("REFUSING: frozen inventory no longer identifies Order 55 as next")
    ast.parse(STAGE_SOURCE, filename=str(STAGE))
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = ROOT / "automation" / "backups" / f"pre_v031c_order55_identity_{stamp}"
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
        contract = f'''\n\n    StageContract(\n        stage_id="{STAGE_ID}",\n        title="Acquire and freeze exact POSS plate identity for Order 55",\n        script="{STAGE_REL}",\n        requires=("results/existing_identified_pair_inventory_v028ca.json", "research/poss1_pixel_repair_v028_queue.csv"),\n        produces=("{OUT_REL}",),\n        dependencies=("existing_identified_pair_inventory_v028ca",),\n        network_access=True,\n        notes="Position+epoch descriptor resolution and HHH/DASCH metadata only; no science pixels or state mutation.",\n    ),\n'''
        registry = registry[:marker.start()] + contract + registry[marker.start():]
        ast.parse(registry, filename=str(REGISTRY))
        REGISTRY.write_text(registry, encoding="utf-8", newline="\n")
    init = re.sub(r'__version__\s*=\s*["\'][^"\']+["\']', '__version__ = "0.3.7"', INIT.read_text(encoding="utf-8"), count=1)
    ast.parse(init, filename=str(INIT))
    INIT.write_text(init, encoding="utf-8", newline="\n")
    print(f"Installed stage: {STAGE_ID}")
    print(f"Backup: {backup}\n\nREPAIR STATUS: PASS")


if __name__ == "__main__":
    main()
