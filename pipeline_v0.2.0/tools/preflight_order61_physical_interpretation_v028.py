from __future__ import annotations

from pathlib import Path
import csv
import hashlib
import json
import math
import shutil
import subprocess

ROOT = Path.cwd()
BASE = ROOT / "results" / "order61_native_full_v028"
AUDIT = BASE / "order61_discovery_plate_audit_v028c"

ENDPOINT = AUDIT / "order61_discovery_plate_endpoint_metrics_v028c.csv"
SUMMARY = AUDIT / "order61_discovery_plate_candidate_summary_v028c.csv"
REPORT = AUDIT / "order61_discovery_plate_audit_report_v028c.json"
PAIR = BASE / "order61_whole_pair_report.json"
STAGE3 = BASE / "order61_platephot_stage3_report.json"

OUT = BASE / "order61_physical_interpretation_preflight_v028.json"
RAW_PLATE = BASE / "order61_ai44092_plate_detail_raw_v028.json"

PLATE_ID = "ai44092"
PLATE_URL = f"https://api.starglass.cfa.harvard.edu/public/plates/p/{PLATE_ID}"
UA = "historical-transient-pipeline/0.2.8-order61-physical-preflight"

ACTIVE_RANKS = [11, 14, 20]

CONTINUOUS_PERCENTILE_FIELDS = {
    "sigma_major": "sigma_major_peer_percentile",
    "sigma_minor": "sigma_minor_peer_percentile",
    "ellipticity": "ellipticity_peer_percentile",
    "sharpness_peak_to_flux5": "peak_to_flux5_peer_percentile",
    "concentration_flux3_flux8": "concentration_peer_percentile",
    "centroid_offset": "centroid_offset_peer_percentile",
}
COUNT_PERCENTILE_FIELDS = {
    "plateau_3x3": "plateau_peer_percentile",
    "local_extreme_3x3": "local_extreme_peer_percentile",
}


def read_csv(path: Path):
    with path.open(newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def write_json(path: Path, obj):
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(obj, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )
    tmp.replace(path)


def sha256_file(path: Path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def ffloat(v):
    try:
        x = float(v)
    except Exception:
        return None
    return x if math.isfinite(x) else None


def fetch_plate():
    curl = shutil.which("curl.exe") or shutil.which("curl")
    if not curl:
        raise RuntimeError("curl.exe/curl unavailable; verified HTTPS required")

    part = RAW_PLATE.with_suffix(".json.part")
    cmd = [
        curl,
        "--fail", "--silent", "--show-error", "--location",
        "--connect-timeout", "30", "--max-time", "120",
        "--user-agent", UA,
        "--header", "Accept: application/json",
        "--output", str(part),
        PLATE_URL,
    ]
    cp = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=150,
        check=False,
    )
    if cp.returncode != 0:
        raise RuntimeError(
            f"plate-detail curl exit {cp.returncode}: "
            + (cp.stderr or cp.stdout or "")[:800]
        )

    raw = part.read_bytes()
    obj = json.loads(raw.decode("utf-8"))
    part.replace(RAW_PLATE)
    return obj, hashlib.sha256(raw).hexdigest()


def morphology_closure(endpoint_rows):
    by_rank = {}
    for rank in ACTIVE_RANKS:
        rr = [r for r in endpoint_rows if int(r["strict_rank"]) == rank]
        if len(rr) != 2:
            raise RuntimeError(f"rank {rank}: expected 2 endpoint rows, got {len(rr)}")

        entry = {}
        for r in rr:
            archive = r["archive"]
            continuous = {}
            continuous_extreme = []
            for name, col in CONTINUOUS_PERCENTILE_FIELDS.items():
                p = ffloat(r.get(col))
                continuous[name] = p
                if p is not None and (p <= 5.0 or p >= 95.0):
                    continuous_extreme.append({
                        "metric": name,
                        "percentile": p,
                        "direction": "low" if p <= 5.0 else "high",
                    })

            counts = {}
            count_high = []
            for name, col in COUNT_PERCENTILE_FIELDS.items():
                p = ffloat(r.get(col))
                counts[name] = p
                if p is not None and p >= 95.0:
                    count_high.append({
                        "metric": name,
                        "percentile": p,
                    })

            entry[archive] = {
                "control_count": int(r["control_count"]),
                "selection_mode": r["control_selection_mode"],
                "snr": float(r["snr"]),
                "polarity": int(r["polarity"]),
                "continuous_percentiles": continuous,
                "continuous_extremes_5_95": continuous_extreme,
                "count_percentiles": counts,
                "count_high_ge95": count_high,
            }
        by_rank[str(rank)] = entry
    return by_rank


def location_status(detail):
    loc = detail.get("location")
    if not isinstance(loc, dict):
        return {
            "resolved_from_plate_detail": False,
            "reason": "location missing or non-object",
            "raw_location": loc,
        }

    name = str(loc.get("name") or "").strip()
    lat = ffloat(loc.get("lat"))
    lon = ffloat(loc.get("lon"))
    elev = ffloat(loc.get("elevation"))

    # Do not silently interpret longitude sign convention here. This
    # preflight is only for identity/site resolution; geometry follows only
    # after the named historical site is independently verified.
    resolved = bool(name) and lat is not None and lon is not None

    return {
        "resolved_from_plate_detail": resolved,
        "name": name or None,
        "raw_lat": lat,
        "raw_lon": lon,
        "raw_elevation": elev,
        "longitude_sign_interpretation_applied": False,
        "geometry_authorized": False,
        "geometry_block_reason": (
            "Named site must be independently verified, including longitude "
            "sign convention and telescope/station applicability, before Branch C."
        ),
    }


def main():
    print("=" * 104)
    print("ORDER 61 — PHYSICAL-INTERPRETATION / DASCH SITE PREFLIGHT v028")
    print("=" * 104)
    print(
        "Read-only closure of matched-peer morphology plus official ai44092 "
        "plate-detail/site retrieval. No detector, no science pixels, no geometry."
    )
    print()

    for p in (ENDPOINT, SUMMARY, REPORT, PAIR, STAGE3):
        if not p.is_file():
            raise RuntimeError(f"Missing required completed-stage input: {p}")

    report = json.loads(REPORT.read_text(encoding="utf-8"))
    pair = json.loads(PAIR.read_text(encoding="utf-8"))
    stage3 = json.loads(STAGE3.read_text(encoding="utf-8"))

    guards = {
        "discovery_report_complete": report.get("status") == "COMPLETE",
        "discovery_detector_not_rerun": report.get("detector_rerun") is False,
        "discovery_no_candidate_deleted": report.get("candidate_deleted") is False,
        "discovery_no_candidate_promoted": report.get("candidate_promoted") is False,
        "pair_complete": pair.get("status") == "COMPLETE",
        "order61": int(pair.get("canonical_order", -1)) == 61,
        "stage3_complete": stage3.get("status") == "COMPLETE",
    }
    if not all(guards.values()):
        raise RuntimeError("REFUSING: completed-stage guard failure: " + repr(guards))

    endpoint_rows = read_csv(ENDPOINT)
    if len(endpoint_rows) != 6:
        raise RuntimeError(f"expected 6 endpoint rows, got {len(endpoint_rows)}")

    closure = morphology_closure(endpoint_rows)

    print("Completed-stage guards: PASS")
    print()
    print("MATCHED-PEER MORPHOLOGY CLOSURE")
    print("-" * 104)

    for rank in ACTIVE_RANKS:
        print(f"strict #{rank:02d}")
        for archive in ("POSS", "DASCH"):
            e = closure[str(rank)][archive]
            ex = e["continuous_extremes_5_95"]
            ex_txt = (
                ", ".join(
                    f"{q['metric']}={q['percentile']:.1f}pct"
                    for q in ex
                )
                if ex else "none"
            )
            print(
                f"  {archive:5s}: controls={e['control_count']:2d} "
                f"continuous 5/95 extremes: {ex_txt}"
            )
            cp = e["continuous_percentiles"]
            print(
                "         "
                f"major={cp['sigma_major']:.1f} "
                f"minor={cp['sigma_minor']:.1f} "
                f"ell={cp['ellipticity']:.1f} "
                f"sharp={cp['sharpness_peak_to_flux5']:.1f} "
                f"conc={cp['concentration_flux3_flux8']:.1f} "
                f"cent={cp['centroid_offset']:.1f}"
            )
        print()

    print("OFFICIAL DASCH PLATE DETAIL")
    print("-" * 104)
    detail, detail_sha = fetch_plate()

    if str(detail.get("plate_id", "")).lower() != PLATE_ID:
        raise RuntimeError(
            f"plate-detail identity mismatch: {detail.get('plate_id')!r}"
        )

    locstat = location_status(detail)

    print("plate_id:         ", detail.get("plate_id"))
    print("class:            ", detail.get("class"))
    print("telescope:        ", detail.get("telescope"))
    print("location(raw):    ", json.dumps(detail.get("location"), sort_keys=True))
    print("has_markings:     ", detail.get("has_markings"))
    print("markings_cleaned: ", detail.get("markings_cleaned"))
    print("plate_comment:    ", detail.get("plate_comment"))
    print("catalog_exposures:", len(detail.get("catalog_exposures") or []))
    for i, e in enumerate(detail.get("catalog_exposures") or [], 1):
        print(f"  exposure[{i}]: {json.dumps(e, sort_keys=True)}")

    print()
    if locstat["resolved_from_plate_detail"]:
        print(
            "SITE IDENTITY PREFLIGHT: RESOLVED BY PLATE DETAIL "
            f"as {locstat['name']!r}"
        )
        print(
            "Branch-C geometry remains deliberately BLOCKED until that named "
            "site and longitude convention are independently verified."
        )
    else:
        print("SITE IDENTITY PREFLIGHT: UNRESOLVED")
        print("Branch-C geometry remains BLOCKED.")

    out = {
        "status": "COMPLETE",
        "analysis_kind": "order61_physical_interpretation_site_preflight_v028",
        "guards": guards,
        "matched_peer_morphology_closure": closure,
        "ai44092_plate_detail": {
            "url": PLATE_URL,
            "raw_json_path": str(RAW_PLATE),
            "raw_json_sha256": detail_sha,
            "plate_id": detail.get("plate_id"),
            "plate_class": detail.get("class"),
            "telescope": detail.get("telescope"),
            "location": detail.get("location"),
            "plate_comment": detail.get("plate_comment"),
            "has_markings": detail.get("has_markings"),
            "markings_cleaned": detail.get("markings_cleaned"),
            "catalog_exposures": detail.get("catalog_exposures"),
            "exposures_count": len(detail.get("exposures") or []),
            "mosaics_count": len(detail.get("mosaics") or []),
            "jacket_images_count": len(detail.get("jacket_images") or []),
            "plate_images_count": len(detail.get("plate_images") or []),
        },
        "site_resolution": locstat,
        "branch_c_geometry_executed": False,
        "detector_rerun": False,
        "science_image_pixels_read": False,
        "candidate_deleted": False,
        "candidate_promoted": False,
        "next_stage": (
            "Independently verify the named ai44092 observing site/telescope and "
            "coordinate convention using historical/authoritative sources. Only then "
            "execute Branch-C topocentric parallax/illumination geometry. Branch A "
            "can meanwhile retain the raw <=3 arcsec common-sky associations."
        ),
    }
    write_json(OUT, out)

    print()
    print("=" * 104)
    print("PHYSICAL-INTERPRETATION / SITE PREFLIGHT COMPLETE")
    print("=" * 104)
    print("Output:")
    print(" ", OUT)
    print(" ", RAW_PLATE)
    print()
    print("No detector was rerun.")
    print("No science image pixel was read.")
    print("No Branch-C geometry was executed.")
    print("No candidate was deleted or promoted.")


if __name__ == "__main__":
    main()
