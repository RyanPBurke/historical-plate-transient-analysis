
from __future__ import annotations

from pathlib import Path
import csv
import datetime as dt
import hashlib
import json

from transient_pipeline.poss1 import load_vi25_records, vi25_start_utc

ROOT = Path.cwd()

V049A = ROOT / "results" / "wide_census_physical_timing_v049a.json"
QUEUE = ROOT / "results" / "wide_census_physical_timing_queue_v048.csv"
POSS_META = ROOT / "research" / "census_inputs" / "poss1_plate_metadata.csv"
IDENTITY_AUDIT = ROOT / "results" / "poss_legacy_identity_resolution_audit_v049a.csv"
POLICY = ROOT / "config" / "candidate_adjudication_policy_v002.json"

OUT_JSON = ROOT / "results" / "wide_census_physical_timing_final_v050.json"
OUT_CSV = ROOT / "results" / "wide_census_physical_timing_final_v050.csv"
SURVIVOR_CSV = ROOT / "results" / "wide_census_timing_survivors_v050.csv"
NONOPP_CSV = ROOT / "results" / "wide_census_timing_nonopportunities_v050.csv"

EXPECTED_V049A_COUNTS = {
    "NO_ARCHIVE_SUPPORTED_TIME_OVERLAP": 17,
    "TIMING_OVERLAP_FRAGILE_TO_DOCUMENTED_UNCERTAINTY": 6,
    "TIMING_OVERLAP_SURVIVES_ARCHIVE_SUPPORTED_NO_COMPLETE_FORMAL_UNCERTAINTY": 82,
    "UNRESOLVED_TIMING_OR_IDENTITY": 6,
}
EXPECTED_UNRESOLVED = 6
EXPECTED_QUEUE_ROWS = 111
EXPECTED_POLICY_ID = "candidate_adjudication_policy_v002"


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def read_csv(path: Path):
    with path.open(newline="", encoding="utf-8-sig") as fh:
        return list(csv.DictReader(fh))


def write_json(path: Path, obj):
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(obj, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )
    tmp.replace(path)


def parse_time(value):
    s = str(value).strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    x = dt.datetime.fromisoformat(s)
    if x.tzinfo is None:
        x = x.replace(tzinfo=dt.timezone.utc)
    return x.astimezone(dt.timezone.utc)


def overlap(a0, a1, b0, b1):
    start = max(a0, b0)
    end = min(a1, b1)
    return start, end, max(0.0, (end - start).total_seconds())


def poss_band(exposure):
    parts = str(exposure).split(":")
    if len(parts) < 3 or parts[0] != "POSS-I" or parts[2].upper() not in ("E", "O"):
        raise RuntimeError(f"Invalid legacy POSS exposure {exposure!r}")
    return parts[2].upper()


def final_fields():
    return [
        "timing_validation_priority",
        "current_time_gate",
        "canonical_pair",
        "exposure_a",
        "archive_a",
        "exposure_b",
        "archive_b",
        "classification",
        "timing_survivor",
        "science_eligible",
        "physical_overlap_start_utc",
        "physical_overlap_end_utc",
        "physical_overlap_s",
        "conservative_overlap_known_uncertainties_s",
        "formal_time_uncertainty_available_both",
        "physical_scan_identity_unresolved_nonopportunity",
        "next_gate",
    ]


def write_rows(path, rows):
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=final_fields(), extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    tmp.replace(path)


def main():
    print("=" * 132)
    print("WIDE CENSUS — FINAL VI/25 TIMING COMPLETION v050")
    print("=" * 132)
    print("NO NETWORK. NO PIXELS. NO DETECTOR. NO CANDIDATE STATE MUTATION.")
    print("The six residual POSS cases are resolved for TIMING only; unresolved scan provenance is retained separately.\n")

    for path in (V049A, QUEUE, POSS_META, IDENTITY_AUDIT, POLICY):
        if not path.is_file():
            raise RuntimeError(f"REFUSING: missing input: {path}")

    policy = json.loads(POLICY.read_text(encoding="utf-8"))
    if policy.get("policy_id") != EXPECTED_POLICY_ID:
        raise RuntimeError("REFUSING: candidate policy mismatch")

    v049a = json.loads(V049A.read_text(encoding="utf-8"))
    if v049a.get("status") != "COMPLETE":
        raise RuntimeError("REFUSING: v049a is not complete")
    if v049a.get("classification_counts") != EXPECTED_V049A_COUNTS:
        raise RuntimeError(
            "REFUSING: unexpected v049a classification state: "
            + json.dumps(v049a.get("classification_counts"), sort_keys=True)
        )

    queue = read_csv(QUEUE)
    if len(queue) != EXPECTED_QUEUE_ROWS:
        raise RuntimeError(f"REFUSING: expected {EXPECTED_QUEUE_ROWS} queue rows, got {len(queue)}")

    pair_by_key = {x["canonical_pair"]: x for x in v049a.get("pairs", [])}
    if len(pair_by_key) != EXPECTED_QUEUE_ROWS:
        raise RuntimeError(
            f"REFUSING: expected {EXPECTED_QUEUE_ROWS} v049a pairs, got {len(pair_by_key)}"
        )

    audit = read_csv(IDENTITY_AUDIT)
    audit_by_exposure = {x["exposure"]: x for x in audit if x.get("status") == "IDENTITY_RESOLVED"}
    vi25 = load_vi25_records(POSS_META)

    unresolved_old = [
        x for x in v049a["pairs"]
        if x.get("classification") == "UNRESOLVED_TIMING_OR_IDENTITY"
    ]
    if len(unresolved_old) != EXPECTED_UNRESOLVED:
        raise RuntimeError(
            f"REFUSING: expected {EXPECTED_UNRESOLVED} unresolved v049a pairs, got {len(unresolved_old)}"
        )

    repaired = []
    timing_only_audit = []

    for qrow in queue:
        old = pair_by_key[qrow["canonical_pair"]]

        if old.get("classification") != "UNRESOLVED_TIMING_OR_IDENTITY":
            row = dict(old)
            row.setdefault("physical_scan_identity_unresolved_nonopportunity", False)
            repaired.append(row)
            continue

        sides = {"a": dict(old.get("side_a") or {}), "b": dict(old.get("side_b") or {})}
        poss_side = None
        for side in ("a", "b"):
            if str(qrow[f"exposure_{side}"]).startswith("POSS-I:"):
                poss_side = side
                break
        if poss_side is None:
            raise RuntimeError(
                "REFUSING: residual unresolved pair is not a POSS timing case: "
                + qrow["canonical_pair"]
            )

        exposure = qrow[f"exposure_{poss_side}"]
        ident = audit_by_exposure.get(exposure)
        if ident is None:
            raise RuntimeError(f"REFUSING: no v049a identity audit row for {exposure}")

        recno = int(float(ident["vi25_recno"]))
        band = poss_band(exposure)
        record = vi25.get(recno)
        if record is None:
            raise RuntimeError(f"REFUSING: VI/25 recno {recno} missing for {exposure}")

        start = vi25_start_utc(record, band)
        duration_min = record.eexp_min if band == "E" else record.oexp_min
        if duration_min is None or float(duration_min) <= 0:
            raise RuntimeError(f"REFUSING: VI/25 duration missing for {exposure}")
        end = start + dt.timedelta(minutes=float(duration_min))

        timing_side = {
            "status": "TIMING_RESOLVED_PHYSICAL_SCAN_IDENTITY_UNRESOLVED",
            "kind": "POSS",
            "exposure": exposure,
            "poss_number": int(str(exposure).split(":")[1]),
            "band": band,
            "vi25_recno": recno,
            "start_utc": start.isoformat(),
            "end_utc": end.isoformat(),
            "duration_s": float(duration_min) * 60.0,
            "timing_basis": "AUTHORITATIVE_VI25_NORMALIZED_UTC_PLUS_VI25_BAND_DURATION",
            "physical_scan_identity_verified": False,
            "physical_scan_identity_status": sides[poss_side].get("status"),
            "legacy_catalog_clock_used_for_timing": False,
            "hhh_clock_used_for_timing": False,
        }
        sides[poss_side] = timing_side

        other = "b" if poss_side == "a" else "a"
        other_side = sides[other]
        if other_side.get("status") != "RESOLVED":
            raise RuntimeError(
                "REFUSING: partner side unexpectedly unresolved for "
                + qrow["canonical_pair"]
            )

        p0, p1 = start, end
        o0 = parse_time(other_side["start_utc"])
        o1 = parse_time(other_side["end_utc"])

        if poss_side == "a":
            ov_start, ov_end, ov_s = overlap(p0, p1, o0, o1)
        else:
            ov_start, ov_end, ov_s = overlap(o0, o1, p0, p1)

        if ov_s > 0:
            classification = "UNRESOLVED_PHYSICAL_SCAN_IDENTITY_WITH_TIME_OVERLAP"
            timing_survivor = False
            unresolved_for_timing = True
            next_gate = ""
        else:
            classification = (
                "NO_TIME_OVERLAP_VI25_TIMING_RESOLVED_"
                "PHYSICAL_SCAN_IDENTITY_UNRESOLVED"
            )
            timing_survivor = False
            unresolved_for_timing = False
            next_gate = ""

        row = {
            "timing_validation_priority": int(qrow["timing_validation_priority"]),
            "current_time_gate": qrow["current_time_gate"],
            "canonical_pair": qrow["canonical_pair"],
            "exposure_a": qrow["exposure_a"],
            "archive_a": qrow["archive_a"],
            "exposure_b": qrow["exposure_b"],
            "archive_b": qrow["archive_b"],
            "side_a": sides["a"],
            "side_b": sides["b"],
            "classification": classification,
            "timing_survivor": timing_survivor,
            "science_eligible": False,
            "physical_overlap_start_utc": ov_start.isoformat() if ov_s > 0 else "",
            "physical_overlap_end_utc": ov_end.isoformat() if ov_s > 0 else "",
            "physical_overlap_s": ov_s,
            "conservative_overlap_known_uncertainties_s": ov_s,
            "formal_time_uncertainty_available_both": False,
            "physical_scan_identity_unresolved_nonopportunity": not unresolved_for_timing,
            "next_gate": next_gate,
        }
        repaired.append(row)
        timing_only_audit.append({
            "canonical_pair": qrow["canonical_pair"],
            "exposure": exposure,
            "vi25_recno": recno,
            "band": band,
            "vi25_start_utc": start.isoformat(),
            "vi25_end_utc": end.isoformat(),
            "partner_start_utc": other_side["start_utc"],
            "partner_end_utc": other_side["end_utc"],
            "overlap_s": ov_s,
            "classification": classification,
            "retained_scan_identity_status": timing_side["physical_scan_identity_status"],
        })

    counts = {}
    for row in repaired:
        counts[row["classification"]] = counts.get(row["classification"], 0) + 1

    survivors = [x for x in repaired if x.get("timing_survivor")]
    timing_unresolved = [
        x for x in repaired
        if x["classification"] == "UNRESOLVED_PHYSICAL_SCAN_IDENTITY_WITH_TIME_OVERLAP"
    ]
    provenance_unresolved_nonopportunity = [
        x for x in repaired
        if x.get("physical_scan_identity_unresolved_nonopportunity")
    ]
    nonopportunities = [x for x in repaired if not x.get("timing_survivor")]

    if len(repaired) != EXPECTED_QUEUE_ROWS:
        raise RuntimeError("REFUSING: final timing census row count changed")

    # The repair is allowed to *discover* a positive-overlap residual case,
    # but then the timing census is explicitly not declared final.
    final_status = "COMPLETE" if not timing_unresolved else "COMPLETE_WITH_TIMING_UNRESOLVED"

    write_rows(OUT_CSV, repaired)
    write_rows(SURVIVOR_CSV, survivors)
    write_rows(NONOPP_CSV, nonopportunities)

    payload = {
        "status": final_status,
        "analysis_kind": "wide_census_physical_timing_final_v050",
        "supersedes_for_timing_census": "wide_census_physical_timing_v049a",
        "guards": {
            "network_access": False,
            "science_pixels_read": False,
            "non_science_pixels_read": False,
            "transient_detector_rerun": False,
            "candidate_state_mutation": False,
        },
        "input_sha256": {
            "v049a": sha(V049A),
            "queue": sha(QUEUE),
            "poss_vi25": sha(POSS_META),
            "identity_audit": sha(IDENTITY_AUDIT),
            "policy": sha(POLICY),
        },
        "classification_counts": counts,
        "timing_survivor_count": len(survivors),
        "timing_unresolved_pair_count": len(timing_unresolved),
        "provenance_unresolved_but_timing_nonopportunity_count": len(
            provenance_unresolved_nonopportunity
        ),
        "science_eligible_count": 0,
        "timing_only_repair_audit": timing_only_audit,
        "interpretation_boundary": (
            "A VI/25-normalized zero-overlap result is sufficient to exclude a pair "
            "from the contemporaneous two-observatory opportunity census even when "
            "the exact digitized physical-scan identity remains unavailable. Such "
            "provenance failures remain recorded and are not converted into a claim "
            "about the plate feature itself."
        ),
        "pairs": repaired,
        "next_stage": (
            "Build/freeze exact sky-footprint and physical-observation independence "
            "queue for timing survivors."
        ),
    }
    write_json(OUT_JSON, payload)

    print("Classification counts:", json.dumps(counts, sort_keys=True))
    print(f"Timing survivors: {len(survivors)}")
    print(f"Timing unresolved: {len(timing_unresolved)}")
    print(
        "Provenance-unresolved but timing-excluded: "
        f"{len(provenance_unresolved_nonopportunity)}"
    )
    print("SCIENCE ELIGIBLE: 0")
    print(f"Report: {OUT_JSON}")
    print("\nSTAGE STATUS: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
