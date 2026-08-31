
from __future__ import annotations

from pathlib import Path
import csv
import hashlib
import json
import math
import re

ROOT = Path.cwd()

TIMING = ROOT / "results" / "wide_census_physical_timing_final_v050.json"
WIDE = ROOT / "research" / "census_inputs" / "archive_pair_overlap_candidates.csv"
APPLAUSE = ROOT / "research" / "census_inputs" / "applause_exposures_1951_1955.csv"
POLICY = ROOT / "config" / "candidate_adjudication_policy_v002.json"

OUT_JSON = ROOT / "results" / "wide_census_footprint_plan_v051.json"
OUT_CSV = ROOT / "results" / "wide_census_exact_footprint_queue_v051.csv"
CLOSED_CSV = ROOT / "results" / "wide_census_independence_closed_v051.csv"

EXPECTED_POLICY_ID = "candidate_adjudication_policy_v002"


def sha(path: Path):
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def read_csv(path):
    with path.open(newline="", encoding="utf-8-sig") as fh:
        return list(csv.DictReader(fh))


def fnum(v):
    try:
        x = float(str(v).strip())
        return x if math.isfinite(x) else None
    except Exception:
        return None


def angular_sep_deg(ra1, dec1, ra2, dec2):
    r1, d1, r2, d2 = map(math.radians, (ra1, dec1, ra2, dec2))
    a = (
        math.sin((d2-d1)/2.0)**2
        + math.cos(d1) * math.cos(d2) * math.sin((r2-r1)/2.0)**2
    )
    return math.degrees(2.0 * math.asin(math.sqrt(min(1.0, max(0.0, a)))))


def canonical(a, b):
    return " | ".join(sorted((str(a).strip(), str(b).strip())))


def source_kind(exposure):
    s = str(exposure)
    if s.startswith("APPLAUSE:"):
        return "APPLAUSE"
    if s.startswith("POSS-I:"):
        return "POSS"
    if "DASCH:" in s or "/dasch/q/" in s:
        return "DASCH"
    return "UNKNOWN"


def dasch_plate(exposure):
    m = re.search(r"/q/([a-z]+\d+)$", str(exposure), re.I)
    if not m:
        m = re.search(r"([a-z]+\d+)$", str(exposure), re.I)
    return m.group(1).lower() if m else ""


def write_csv(path, rows, fields):
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    tmp.replace(path)


def main():
    print("=" * 132)
    print("WIDE CENSUS — FOOTPRINT / INDEPENDENCE EXECUTION PLAN v051")
    print("=" * 132)
    print("NO NETWORK. NO PIXELS. NO DETECTOR. NO CANDIDATE STATE MUTATION.")
    print("Coarse FOV geometry is PRIORITIZATION ONLY; it never closes a sky-overlap hypothesis.\n")

    for path in (TIMING, WIDE, APPLAUSE, POLICY):
        if not path.is_file():
            raise RuntimeError(f"REFUSING: missing input: {path}")

    policy = json.loads(POLICY.read_text(encoding="utf-8"))
    if policy.get("policy_id") != EXPECTED_POLICY_ID:
        raise RuntimeError("REFUSING: policy mismatch")

    timing = json.loads(TIMING.read_text(encoding="utf-8"))
    if timing.get("status") != "COMPLETE":
        raise RuntimeError(
            "REFUSING: v050 timing census is not fully complete; "
            f"status={timing.get('status')!r}"
        )
    if int(timing.get("timing_unresolved_pair_count", -1)) != 0:
        raise RuntimeError("REFUSING: timing census still has unresolved pairs")

    wide_rows = read_csv(WIDE)
    wide_by_pair = {
        canonical(r["exposure_a"], r["exposure_b"]): r
        for r in wide_rows
    }

    applause_rows = read_csv(APPLAUSE)
    applause_by_exposure = {
        int(float(r["exposure_id"])): r
        for r in applause_rows
    }

    survivors = [x for x in timing["pairs"] if x.get("timing_survivor")]
    queue = []
    closed = []

    for pair in survivors:
        key = pair["canonical_pair"]
        src = wide_by_pair.get(key)
        if src is None:
            raise RuntimeError(f"REFUSING: wide source row missing for {key}")

        side_meta = {}
        for side in ("a", "b"):
            exposure = src[f"exposure_{side}"]
            kind = source_kind(exposure)
            meta = {
                "side": side,
                "exposure": exposure,
                "kind": kind,
                "archive": src[f"archive_{side}"],
                "site": src[f"site_{side}"],
                "ra_deg": fnum(src[f"ra_{side}_deg"]),
                "dec_deg": fnum(src[f"dec_{side}_deg"]),
                "nominal_fov_deg": fnum(src[f"fov_{side}_deg"]),
            }

            if kind == "APPLAUSE":
                eid = int(str(exposure).split(":")[1])
                ap = applause_by_exposure.get(eid)
                if ap is None:
                    raise RuntimeError(f"REFUSING: APPLAUSE exposure {eid} missing")
                meta.update({
                    "applause_exposure_id": eid,
                    "physical_plate_id": int(float(ap["plate_id"])),
                    "applause_archive_id": int(float(ap["archive_id"])),
                    "physical_plate_key": (
                        f"APPLAUSE:{int(float(ap['archive_id']))}:"
                        f"{int(float(ap['plate_id']))}"
                    ),
                })
            elif kind == "DASCH":
                plate = dasch_plate(exposure)
                if not plate:
                    raise RuntimeError(f"REFUSING: DASCH plate parse failed: {exposure}")
                meta.update({
                    "dasch_plate_id": plate,
                    "physical_plate_key": f"DASCH:{plate}",
                })
            else:
                # v050's timing survivors are expected to be non-POSS after the
                # legacy timing repair. Unknown kinds remain unresolved, never closed.
                meta["physical_plate_key"] = ""
            side_meta[side] = meta

        same_physical = (
            side_meta["a"].get("physical_plate_key")
            and side_meta["a"].get("physical_plate_key")
            == side_meta["b"].get("physical_plate_key")
        )
        same_site = (
            str(side_meta["a"]["site"]).strip().lower()
            == str(side_meta["b"]["site"]).strip().lower()
        )

        if same_physical:
            closed.append({
                "canonical_pair": key,
                "timing_validation_priority": pair["timing_validation_priority"],
                "classification": "NOT_INDEPENDENT_SAME_PHYSICAL_PLATE",
                "exposure_a": src["exposure_a"],
                "exposure_b": src["exposure_b"],
                "site_a": src["site_a"],
                "site_b": src["site_b"],
                "physical_plate_key_a": side_meta["a"]["physical_plate_key"],
                "physical_plate_key_b": side_meta["b"]["physical_plate_key"],
                "science_eligible": False,
            })
            continue

        if same_site:
            closed.append({
                "canonical_pair": key,
                "timing_validation_priority": pair["timing_validation_priority"],
                "classification": "NOT_DISTINCT_OBSERVATORY_SITE",
                "exposure_a": src["exposure_a"],
                "exposure_b": src["exposure_b"],
                "site_a": src["site_a"],
                "site_b": src["site_b"],
                "physical_plate_key_a": side_meta["a"].get("physical_plate_key", ""),
                "physical_plate_key_b": side_meta["b"].get("physical_plate_key", ""),
                "science_eligible": False,
            })
            continue

        ra1 = side_meta["a"]["ra_deg"]
        de1 = side_meta["a"]["dec_deg"]
        ra2 = side_meta["b"]["ra_deg"]
        de2 = side_meta["b"]["dec_deg"]
        f1 = side_meta["a"]["nominal_fov_deg"]
        f2 = side_meta["b"]["nominal_fov_deg"]

        if None not in (ra1, de1, ra2, de2, f1, f2) and f1 > 0 and f2 > 0:
            sep = angular_sep_deg(ra1, de1, ra2, de2)

            # Deliberately inflated bound: sqrt(2)*FOV for EACH side.
            # This is not used to reject a pair; it only orders exact work.
            r1 = math.sqrt(2.0) * f1
            r2 = math.sqrt(2.0) * f2
            if sep > r1 + r2:
                coarse = "COARSE_BOUND_DISJOINT_CANDIDATE"
                priority_class = 1
            else:
                coarse = "COARSE_BOUND_POSSIBLE_OVERLAP"
                priority_class = 0
        else:
            sep = None
            r1 = r2 = None
            coarse = "COARSE_GEOMETRY_INCOMPLETE"
            priority_class = 0

        row = {
            "canonical_pair": key,
            "timing_validation_priority": pair["timing_validation_priority"],
            "time_gate": pair["current_time_gate"],
            "physical_overlap_s": pair.get("physical_overlap_s"),
            "coarse_footprint_state": coarse,
            "coarse_priority_class": priority_class,
            "center_separation_deg": sep,
            "inflated_bound_radius_a_deg": r1,
            "inflated_bound_radius_b_deg": r2,
            "exposure_a": src["exposure_a"],
            "kind_a": side_meta["a"]["kind"],
            "archive_a": src["archive_a"],
            "site_a": src["site_a"],
            "ra_a_deg": ra1,
            "dec_a_deg": de1,
            "fov_a_deg": f1,
            "physical_plate_key_a": side_meta["a"].get("physical_plate_key", ""),
            "applause_plate_id_a": side_meta["a"].get("physical_plate_id", ""),
            "applause_archive_id_a": side_meta["a"].get("applause_archive_id", ""),
            "dasch_plate_id_a": side_meta["a"].get("dasch_plate_id", ""),
            "exposure_b": src["exposure_b"],
            "kind_b": side_meta["b"]["kind"],
            "archive_b": src["archive_b"],
            "site_b": src["site_b"],
            "ra_b_deg": ra2,
            "dec_b_deg": de2,
            "fov_b_deg": f2,
            "physical_plate_key_b": side_meta["b"].get("physical_plate_key", ""),
            "applause_plate_id_b": side_meta["b"].get("physical_plate_id", ""),
            "applause_archive_id_b": side_meta["b"].get("applause_archive_id", ""),
            "dasch_plate_id_b": side_meta["b"].get("dasch_plate_id", ""),
            "needs_exact_footprint": True,
            "science_eligible": False,
        }
        queue.append(row)

    queue.sort(
        key=lambda x: (
            int(x["coarse_priority_class"]),
            int(x["timing_validation_priority"]),
            x["canonical_pair"],
        )
    )
    for i, row in enumerate(queue, 1):
        row["exact_footprint_priority"] = i

    qfields = [
        "exact_footprint_priority",
        "canonical_pair",
        "timing_validation_priority",
        "time_gate",
        "physical_overlap_s",
        "coarse_footprint_state",
        "coarse_priority_class",
        "center_separation_deg",
        "inflated_bound_radius_a_deg",
        "inflated_bound_radius_b_deg",
        "exposure_a", "kind_a", "archive_a", "site_a", "ra_a_deg", "dec_a_deg",
        "fov_a_deg", "physical_plate_key_a", "applause_plate_id_a",
        "applause_archive_id_a", "dasch_plate_id_a",
        "exposure_b", "kind_b", "archive_b", "site_b", "ra_b_deg", "dec_b_deg",
        "fov_b_deg", "physical_plate_key_b", "applause_plate_id_b",
        "applause_archive_id_b", "dasch_plate_id_b",
        "needs_exact_footprint", "science_eligible",
    ]
    cfields = [
        "canonical_pair", "timing_validation_priority", "classification",
        "exposure_a", "exposure_b", "site_a", "site_b",
        "physical_plate_key_a", "physical_plate_key_b", "science_eligible",
    ]

    write_csv(OUT_CSV, queue, qfields)
    write_csv(CLOSED_CSV, closed, cfields)

    applause_plate_ids = sorted({
        int(x[k])
        for x in queue
        for k in ("applause_plate_id_a", "applause_plate_id_b")
        if str(x.get(k, "")).strip()
    })
    dasch_plate_ids = sorted({
        str(x[k]).strip()
        for x in queue
        for k in ("dasch_plate_id_a", "dasch_plate_id_b")
        if str(x.get(k, "")).strip()
    })

    coarse_counts = {}
    for x in queue:
        coarse_counts[x["coarse_footprint_state"]] = (
            coarse_counts.get(x["coarse_footprint_state"], 0) + 1
        )
    closed_counts = {}
    for x in closed:
        closed_counts[x["classification"]] = closed_counts.get(x["classification"], 0) + 1

    payload = {
        "status": "COMPLETE",
        "analysis_kind": "wide_census_footprint_plan_v051",
        "guards": {
            "network_access": False,
            "science_pixels_read": False,
            "non_science_pixels_read": False,
            "transient_detector_rerun": False,
            "candidate_state_mutation": False,
        },
        "input_sha256": {
            "timing_v050": sha(TIMING),
            "wide_inventory": sha(WIDE),
            "applause_metadata": sha(APPLAUSE),
            "policy": sha(POLICY),
        },
        "timing_survivors_entering": len(survivors),
        "closed_before_exact_footprint_count": len(closed),
        "closed_counts": closed_counts,
        "exact_footprint_queue_count": len(queue),
        "coarse_priority_counts": coarse_counts,
        "unique_applause_physical_plates_needed": len(applause_plate_ids),
        "unique_applause_plate_ids": applause_plate_ids,
        "unique_dasch_plates_needed": len(dasch_plate_ids),
        "unique_dasch_plate_ids": dasch_plate_ids,
        "science_eligible_count": 0,
        "coarse_geometry_policy": (
            "Nominal source FOV is expanded to sqrt(2)*FOV as a deliberately "
            "conservative prioritization bound. COARSE_BOUND_DISJOINT_CANDIDATE "
            "does NOT close a pair; every independent timing survivor remains "
            "queued for exact archive-derived footprint geometry."
        ),
        "next_stage": (
            "Resolve exact APPLAUSE DR4 stc_polygon/header_wcs and DASCH DR7 TPV "
            "footprints for every queued pair, then freeze true sky-overlap survivors."
        ),
    }

    tmp = OUT_JSON.with_suffix(OUT_JSON.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(OUT_JSON)

    print(f"Timing survivors entering: {len(survivors)}")
    print(f"Closed on physical independence/site before geometry: {len(closed)}")
    print(f"Exact footprint queue: {len(queue)}")
    print("Coarse priority counts:", json.dumps(coarse_counts, sort_keys=True))
    print(f"Unique APPLAUSE physical plates needed: {len(applause_plate_ids)}")
    print(f"Unique DASCH plates needed: {len(dasch_plate_ids)}")
    print("SCIENCE ELIGIBLE: 0")
    print(f"Queue: {OUT_CSV}")
    print("\nSTAGE STATUS: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
