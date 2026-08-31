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
QUEUE = ROOT / "research" / "poss1_pixel_repair_v028_queue.csv"
AUDIT74 = ROOT / "results" / "order74_native_preflight_v028" / "order74_timing_provenance_audit_v028cf.json"
STAGE_ID = "remaining_pair_physical_timing_census_v028cg"
STAGE_REL = "automation/stages/census_remaining_pair_physical_timing_v028cg.py"
STAGE = ROOT / STAGE_REL
OUT_REL = "results/remaining_pair_physical_timing_census_v028cg.json"

STAGE_SOURCE = r'''from __future__ import annotations

from pathlib import Path
import csv
import datetime as dt
import hashlib
import json
import math
import re
import urllib.request

from transient_pipeline.poss1_skyview import parse_skyview_descriptor, raw_plate_directory, hhh_identity

ROOT = Path.cwd()
QUEUE = ROOT / "research" / "poss1_pixel_repair_v028_queue.csv"
OUT = ROOT / "results" / "remaining_pair_physical_timing_census_v028cg.json"
OUT_DIR = ROOT / "results" / "remaining_pair_physical_timing_census_v028cg"
EXPECTED_ORDERS = [28, 29, 11, 9, 18, 24, 4, 21]
DSS_DESCRIPTOR = {
    "E": "https://skyview.gsfc.nasa.gov/current/jar/surveys/xml/dss1r.xml.gz",
    "O": "https://skyview.gsfc.nasa.gov/current/jar/surveys/xml/dss1b.xml.gz",
}
DASCH_API = "https://api.starglass.cfa.harvard.edu/public/dasch/dr7/mosaic_package"
UA = "historical-transient-pipeline/0.3.11-remaining-pair-physical-timing-census"


def sha256_bytes(raw):
    return hashlib.sha256(raw).hexdigest()


def sha256_file(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def read_csv(path):
    with path.open(newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def parse_time(value):
    value = dt.datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
    if value.tzinfo is None:
        value = value.replace(tzinfo=dt.timezone.utc)
    return value.astimezone(dt.timezone.utc)


def decimal_year(value):
    t = parse_time(value)
    start = dt.datetime(t.year, 1, 1, tzinfo=dt.timezone.utc)
    end = dt.datetime(t.year + 1, 1, 1, tzinfo=dt.timezone.utc)
    return t.year + (t-start).total_seconds()/(end-start).total_seconds()


def sep_deg(ra1, dec1, ra2, dec2):
    r1, d1, r2, d2 = map(math.radians, map(float, (ra1, dec1, ra2, dec2)))
    a = math.sin((d2-d1)/2)**2 + math.cos(d1)*math.cos(d2)*math.sin((r2-r1)/2)**2
    return math.degrees(2*math.asin(math.sqrt(min(1.0, max(0.0, a)))))


def overlap_s(a0, a1, b0, b1):
    return max(0.0, (min(a1, b1)-max(a0, b0)).total_seconds())


def get_bytes(url, accept="*/*"):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": accept})
    with urllib.request.urlopen(req, timeout=90) as response:
        return response.read(), getattr(response, "status", None), response.geturl()


def post_json(url, payload):
    raw = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=raw, method="POST", headers={
        "User-Agent": UA, "Accept": "application/json", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=90) as response:
        return json.loads(response.read().decode("utf-8")), getattr(response, "status", None), response.geturl()


def side(row, archive):
    for suffix in ("a", "b"):
        if archive.upper() in str(row.get(f"archive_{suffix}", "")).upper():
            return suffix
    raise RuntimeError(f"Missing {archive} side in Order {row.get('canonical_order')}")


def dasch_plate(row, suffix):
    value = str(row[f"exposure_{suffix}"]).strip()
    match = re.search(r"/([a-z]+\d+)$", value, re.I)
    if not match:
        raise RuntimeError(f"Cannot parse DASCH plate from {value!r}")
    return match.group(1).lower()


def descriptor_match(desc, ra, dec, epoch):
    ranked = []
    for entry in desc.images:
        try:
            ranked.append((abs(float(entry.epoch)-epoch), sep_deg(ra, dec, entry.ra_deg, entry.dec_deg), entry))
        except (TypeError, ValueError):
            pass
    ranked.sort(key=lambda x: (x[0], x[1], x[2].path))
    plausible = [x for x in ranked if x[0] <= 0.02 and x[1] <= 5.0]
    return plausible, ranked[:10]


def main():
    print("=" * 124)
    print("REMAINING IDENTIFIED PAIRS — PHYSICAL POSS/DASCH TIMING CENSUS v028cg")
    print("=" * 124)
    print("NETWORK: descriptor, HHH and DASCH package metadata only. NO SCIENCE PIXELS. No detector/state mutation.\n")
    rows = read_csv(QUEUE)
    selected = {int(float(r["canonical_order"])): r for r in rows if int(float(r["canonical_order"])) in EXPECTED_ORDERS}
    if set(selected) != set(EXPECTED_ORDERS):
        raise RuntimeError(f"REFUSING: remaining-order mismatch: {sorted(selected)}")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    descriptors = {}
    descriptor_meta = {}
    for band, url in DSS_DESCRIPTOR.items():
        raw, status, final_url = get_bytes(url, "application/xml,*/*")
        descriptors[band] = parse_skyview_descriptor(raw)
        copy = OUT_DIR / f"skyview_dss1_{band.lower()}_descriptor.xml"
        copy.write_bytes(raw)
        descriptor_meta[band] = {"url": url, "status": status, "final_url": final_url,
                                 "sha256": sha256_bytes(raw), "saved_copy": str(copy),
                                 "image_count": len(descriptors[band].images)}

    results = []
    for index, order in enumerate(EXPECTED_ORDERS, 1):
        row = selected[order]
        ps = side(row, "POSS")
        ds = side(row, "DASCH")
        poss_id = str(row[f"exposure_{ps}"]).strip()
        parts = poss_id.split(":")
        if len(parts) < 4 or parts[2].upper() not in descriptors:
            raise RuntimeError(f"Invalid POSS identity {poss_id!r}")
        band = parts[2].upper()
        plate = dasch_plate(row, ds)
        ra, dec = float(row[f"ra_{ps}_deg"]), float(row[f"dec_{ps}_deg"])
        catalog_poss_start = parse_time(row[f"start_{ps}_utc"])
        catalog_poss_end = parse_time(row[f"end_{ps}_utc"])
        poss_duration = float(row[f"duration_{ps}_s"])
        epoch = decimal_year(catalog_poss_start)
        plausible, top = descriptor_match(descriptors[band], ra, dec, epoch)
        item = {"canonical_order": order, "poss_exposure": poss_id, "band": band, "dasch_plate": plate,
                "catalog_overlap_s": float(row["actual_exposure_overlap_s"]),
                "catalog_poss_start_utc": catalog_poss_start.isoformat(),
                "catalog_poss_end_utc": catalog_poss_end.isoformat()}
        if len(plausible) != 1:
            item.update({"classification": "UNRESOLVED_POSS_DESCRIPTOR_IDENTITY",
                         "plausible_descriptor_matches": len(plausible),
                         "top_descriptor_candidates": [{"path": x[2].path, "epoch_delta_year": x[0], "center_sep_deg": x[1]} for x in top]})
            results.append(item)
            print(f"[{index}/8] Order {order}: UNRESOLVED descriptor matches={len(plausible)}")
            continue
        epoch_delta, center_sep, entry = plausible[0]
        region = Path(entry.path).name.upper()
        raw_dir = raw_plate_directory(band=band, region=region, descriptor_entry=entry)
        hhh_url = f"{raw_dir}/{region.lower()}.hhh"
        hhh_raw, hhh_status, hhh_final = get_bytes(hhh_url, "application/octet-stream,*/*")
        hident = hhh_identity(hhh_raw)
        if str(hident.get("region", "")).strip().upper() != region or not hident.get("date_obs"):
            raise RuntimeError(f"Order {order}: invalid HHH identity {hident!r}")
        physical_poss_start = parse_time(hident["date_obs"])
        physical_poss_end = physical_poss_start + dt.timedelta(seconds=poss_duration)

        pkg, pkg_status, pkg_url = post_json(DASCH_API, {"plate_id": plate, "binning": 1})
        exposures = (((pkg.get("metadata") or {}).get("astrometry") or {}).get("exposures") or [])
        physical_dasch = []
        for exp in exposures:
            if not exp.get("midpointDate") or exp.get("durMin") is None:
                continue
            midpoint = parse_time(exp["midpointDate"])
            half = dt.timedelta(minutes=float(exp["durMin"])/2.0)
            start, end = midpoint-half, midpoint+half
            physical_dasch.append({"number": exp.get("number"), "start_utc": start.isoformat(),
                                   "end_utc": end.isoformat(), "midpoint_utc": midpoint.isoformat(),
                                   "duration_min": float(exp["durMin"]), "date_source": exp.get("dateSource"),
                                   "date_accuracy_days": exp.get("dateAccDays"),
                                   "overlap_with_physical_poss_s": overlap_s(physical_poss_start, physical_poss_end, start, end)})
        if not physical_dasch:
            classification = "UNRESOLVED_DASCH_PHYSICAL_TIME"
            max_overlap = None
        else:
            max_overlap = max(x["overlap_with_physical_poss_s"] for x in physical_dasch)
            classification = "PHYSICAL_TIME_OVERLAP_SURVIVES" if max_overlap > 0 else "NO_PHYSICAL_TIME_OVERLAP"
        item.update({"region": region, "plate_id": hident.get("plate_id"),
                     "descriptor_epoch_delta_year": epoch_delta, "descriptor_center_sep_deg": center_sep,
                     "hhh_url": hhh_url, "hhh_status": hhh_status, "hhh_final_url": hhh_final,
                     "hhh_sha256": sha256_bytes(hhh_raw), "physical_poss_start_utc": physical_poss_start.isoformat(),
                     "physical_poss_end_utc": physical_poss_end.isoformat(),
                     "catalog_minus_physical_poss_start_s": (catalog_poss_start-physical_poss_start).total_seconds(),
                     "dasch_package_status": pkg_status, "dasch_package_url": pkg_url,
                     "dasch_exposures": physical_dasch, "maximum_physical_overlap_s": max_overlap,
                     "classification": classification, "science_pixels_read": False})
        results.append(item)
        print(f"[{index}/8] Order {order}: {poss_id}->{region}/{hident.get('plate_id')} + {plate}: {classification}; overlap={max_overlap}")

    counts = {}
    for item in results:
        counts[item["classification"]] = counts.get(item["classification"], 0) + 1
    survivors = [x["canonical_order"] for x in results if x["classification"] == "PHYSICAL_TIME_OVERLAP_SURVIVES"]
    unresolved = [x["canonical_order"] for x in results if x["classification"].startswith("UNRESOLVED")]
    result = {"status": "COMPLETE", "analysis_kind": "remaining_pair_physical_timing_census_v028cg",
              "guards": {"network_access": True, "science_pixels_read": False, "non_science_pixels_read": False,
                         "transient_detector_rerun": False, "candidate_state_mutation": False},
              "queue_sha256": sha256_file(QUEUE), "orders_audited": EXPECTED_ORDERS,
              "descriptor_provenance": descriptor_meta, "results": results, "classification_counts": counts,
              "physical_overlap_survivor_orders": survivors, "unresolved_orders": unresolved,
              "next_stage": "Only physical-overlap survivors proceed to native science-pixel analysis; resolve any unresolved metadata first."}
    tmp = OUT.with_suffix(OUT.suffix + ".tmp")
    tmp.write_text(json.dumps(result, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    tmp.replace(OUT)
    print(f"\nClassification counts: {counts}")
    print(f"Physical-overlap survivors: {survivors}")
    print(f"Unresolved: {unresolved}")
    print(f"Output: {OUT}\nSTAGE STATUS: PASS")


if __name__ == "__main__":
    main()
'''


def main():
    print("=" * 124)
    print("TRANSIENT AUTOMATION UPGRADE v0.3.5 — REMAINING-PAIR PHYSICAL TIMING CENSUS")
    print("=" * 124)
    print("NO NETWORK DURING INSTALL. NO PIXELS. No detector or candidate mutation.\n")
    for path in (REGISTRY, INIT, QUEUE, AUDIT74):
        if not path.is_file():
            raise RuntimeError(f"Missing required input: {path}")
    audit = json.loads(AUDIT74.read_text(encoding="utf-8"))
    if audit.get("classification") != "PHYSICAL_PLATE_TIME_REMOVES_OVERLAP_ORDER74_PAIR_BLOCKED":
        raise RuntimeError("REFUSING: Order 74 has not reached verified zero-overlap classification")
    ast.parse(STAGE_SOURCE, filename=str(STAGE))
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = ROOT / "automation" / "backups" / f"pre_v035_timing_census_{stamp}"
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
        contract = f'''\n\n    StageContract(\n        stage_id="{STAGE_ID}",\n        title="Census physical POSS/DASCH timing for all eight remaining identified pairs",\n        script="{STAGE_REL}",\n        requires=("results/order74_native_preflight_v028/order74_timing_provenance_audit_v028cf.json", "research/poss1_pixel_repair_v028_queue.csv"),\n        produces=("{OUT_REL}",),\n        dependencies=("order74_timing_provenance_audit_v028cf",),\n        network_access=True,\n        notes="17 metadata requests maximum; evaluates all DASCH exposures per plate; no science pixels/detector/state mutation.",\n    ),\n'''
        registry = registry[:marker.start()] + contract + registry[marker.start():]
        ast.parse(registry, filename=str(REGISTRY))
        REGISTRY.write_text(registry, encoding="utf-8", newline="\n")
    init = re.sub(r'__version__\s*=\s*["\'][^"\']+["\']', '__version__ = "0.3.11"', INIT.read_text(encoding="utf-8"), count=1)
    ast.parse(init, filename=str(INIT))
    INIT.write_text(init, encoding="utf-8", newline="\n")
    print(f"Installed stage: {STAGE_ID}")
    print(f"Backup: {backup}\n\nUPGRADE STATUS: PASS")


if __name__ == "__main__":
    main()
