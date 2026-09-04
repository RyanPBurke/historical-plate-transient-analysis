#!/usr/bin/env python3
"""
v082 — Pair-17 survivor chronology + close-time native-pixel synthesis.

Outcome-bearing only where a frozen v081a candidate x scan pair was not already
measured in v080. In that case this runner reuses the exact frozen v080a science
implementation with:
  * no network,
  * existing v079 scan bytes,
  * existing v080 Gaia cache,
  * a separate v082 checkpoint namespace.

No formal candidate dispositions are changed.
"""

from pathlib import Path
from collections import Counter, defaultdict
from io import BytesIO
import csv
import hashlib
import importlib.util
import json
import math
import sys

from astropy.table import Table

ROOT = Path(__file__).resolve().parents[1]

CONTRACT = (
    ROOT / "research" / "prospective_freezes"
    / "pair17_survivor_chronology_native_pixel_synthesis_contract_v082.json"
)
EXPECTED_CONTRACT_SHA = "50116b1c96763c28e7327b544a04d55e9f55d5fc2df95a0ca3a53d603aba3f97"

V075 = (
    ROOT / "results" / "pair17_epoch_aware_gaia_static_triage_v075"
    / "pair17_epoch_aware_gaia_static_triage_v075.csv"
)

V080 = ROOT / "results" / "pair17_registered_native_pixel_recurrence_sensitivity_v080"
V080_TARGETS = V080 / "pair17_registered_target_coordinates_v080.csv"
V080_PLATES = V080 / "pair17_native_pixel_plate_measurements_v080.csv"
V080_CAND = V080 / "pair17_native_pixel_candidate_summary_v080.csv"
V080_BANK = V080 / "pair17_v080a_bank_manifest.json"
V080A_RUNNER = ROOT / "tools" / "run_pair17_registered_native_pixel_recurrence_sensitivity_v080a.py"
V080_CONTRACT = (
    ROOT / "research" / "prospective_freezes"
    / "pair17_registered_native_pixel_recurrence_sensitivity_contract_v080.json"
)

V081 = ROOT / "results" / "pair17_temporal_bracketing_census_v081"
V081_OPPS = V081 / "pair17_temporal_bracketing_opportunities_v081.csv"
V081_SUM = V081 / "pair17_temporal_bracketing_candidate_summary_v081.csv"
V081_QUEUE = V081 / "pair17_temporal_bracketing_acquisition_queue_v081.csv"
V081_REPORT = V081 / "pair17_temporal_bracketing_census_v081.json"
V081_BANK = V081 / "pair17_v081a_bank_manifest.json"
V081A_RUNNER = ROOT / "tools" / "run_pair17_temporal_bracketing_census_v081a.py"
V081_CONTRACT = (
    ROOT / "research" / "prospective_freezes"
    / "pair17_temporal_bracketing_census_contract_v081.json"
)

EXPECTED = {
    V080_CONTRACT:
        "732c0822003abf3217d713437f1b9c47a86f7b8fa42d171498f3453e78787ac7",
    V080A_RUNNER:
        "48e927bfe9c790a7cb4e89511e5d8a28c938ec9746f7048be827764dbcb31f41",
    V080_BANK:
        "f2ba81ab1222162e3d94a57d61d4f92da14ec37fef3dab4e54abd060ca699327",
    V081_CONTRACT:
        "f0c45348477dc6a7094a739e34766bf5867cf94c3fec3c71066fbf594b060b63",
    V081A_RUNNER:
        "818e9b14fac1ee3d7d1ccf3f422157e832cb83e874a42f3dedd5eab7f608736e",
    V081_BANK:
        "b361e0165061550bacd31f44ec0926dc450b2242b52e5b73de571deb7d56172d",
}

OUT = ROOT / "results" / "pair17_survivor_chronology_native_pixel_synthesis_v082"
CHECKPOINTS = OUT / "checkpoints"

OUT_EVID = OUT / "pair17_survivor_evidence_table_v082.csv"
OUT_CLOSE = OUT / "pair17_close_time_native_pixel_measurements_v082.csv"
OUT_INJ = OUT / "pair17_close_time_injection_summary_v082.csv"
OUT_CHRON = OUT / "pair17_close_time_chronology_rows_v082.csv"
OUT_JSON = OUT / "pair17_survivor_chronology_native_pixel_synthesis_v082.json"


def sha(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as fh:
        for block in iter(lambda: fh.read(8 * 1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def read_csv(path):
    with Path(path).open("r", encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def write_csv(path, rows, fields=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    if fields is None:
        fields = list(rows[0].keys()) if rows else []
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        if fields:
            w.writeheader()
            w.writerows(rows)
    tmp.replace(path)


def write_json(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(obj, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )
    tmp.replace(path)


def num(v):
    try:
        x = float(str(v).strip())
        return x if math.isfinite(x) else None
    except Exception:
        return None


def integer(v):
    x = num(v)
    return None if x is None else int(x)


def truth(v):
    return str(v).strip().lower() in {"1", "true", "yes", "y"}


def split_semicolon(v):
    return [x.strip() for x in str(v or "").split(";") if x.strip()]


def import_v080a():
    spec = importlib.util.spec_from_file_location("v080a_frozen", V080A_RUNNER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    # Redirect only checkpoint storage. Science functions/constants stay frozen.
    mod.CHECKPOINTS = CHECKPOINTS

    return mod


def load_v080_gaia(mod, rid):
    qpath, vpath, mpath = mod.gaia_cache_paths(rid)

    if not (qpath.is_file() and vpath.is_file() and mpath.is_file()):
        raise RuntimeError(f"Missing frozen v080 Gaia cache for candidate {rid}")

    meta = json.loads(mpath.read_text(encoding="utf-8"))

    if meta.get("status") != "COMPLETE":
        raise RuntimeError(f"Frozen v080 Gaia cache incomplete for {rid}")

    if meta.get("raw_votable_sha256") != sha(vpath):
        raise RuntimeError(f"Frozen v080 Gaia VOTable SHA changed for {rid}")

    tbl = Table.read(BytesIO(vpath.read_bytes()), format="votable")
    rows = mod.table_rows(tbl)

    if len(rows) != int(meta.get("rows", -1)):
        raise RuntimeError(f"Frozen v080 Gaia row count changed for {rid}")

    return rows


def close_time_class(row):
    mode = str(row.get("registration_mode") or "")

    if mode in {"SPARSE", "NONE"}:
        return "CLOSE_TIME_REGISTRATION_INSUFFICIENT"

    if truth(row.get("strict_native_recurrence")):
        return "CLOSE_TIME_STRICT_NATIVE_RECURRENCE"

    if int(row.get("diagnostic_native_peak_count") or 0) > 0:
        return "CLOSE_TIME_DIAGNOSTIC_NATIVE_CONTEXT"

    if truth(row.get("sensitivity_qualified_negative")):
        return "CLOSE_TIME_SENSITIVITY_QUALIFIED_NEGATIVE"

    return "CLOSE_TIME_NONDETECTION_NOT_SENSITIVITY_QUALIFIED"


def main():
    print("=" * 128)
    print("PAIR 17 — SURVIVOR CHRONOLOGY + CLOSE-TIME NATIVE-PIXEL SYNTHESIS v082")
    print("=" * 128)
    print("Network calls:                  0")
    print("New scan downloads:             0")
    print("Formal disposition changes:     NONE")
    print("Threshold retuning:             NO")
    print()

    if not CONTRACT.is_file() or sha(CONTRACT) != EXPECTED_CONTRACT_SHA:
        raise RuntimeError("v082 scientific contract SHA mismatch")

    for p, expected in EXPECTED.items():
        if not p.is_file():
            raise RuntimeError(f"Missing frozen v082 input: {p}")
        actual = sha(p)
        if actual != expected:
            raise RuntimeError(
                f"Frozen v082 input SHA mismatch:\n{p}\n"
                f"expected {expected}\nactual   {actual}"
            )
        print("HASH PASS:", p.relative_to(ROOT))

    report81 = json.loads(V081_REPORT.read_text(encoding="utf-8"))

    if report81.get("status") != "COMPLETE":
        raise RuntimeError("v081a report is not COMPLETE")

    if report81["v082_queue"]["unique_scans"] != 1:
        raise RuntimeError("v081a frozen queue changed: expected 1 unique scan")

    if report81["v082_queue"]["new_scans_required"] != 0:
        raise RuntimeError("v081a frozen queue unexpectedly requires a new scan")

    cand80 = read_csv(V080_CAND)
    targets80 = {str(r["raw_match_row"]): r for r in read_csv(V080_TARGETS)}
    tri75 = {str(r["raw_match_row"]): r for r in read_csv(V075)}
    plate80 = read_csv(V080_PLATES)
    chron81 = read_csv(V081_OPPS)
    sum81 = {str(r["raw_match_row"]): r for r in read_csv(V081_SUM)}
    queue81 = read_csv(V081_QUEUE)

    survivors = {
        str(r["raw_match_row"]): r
        for r in cand80
        if str(r.get("mechanical_evidence_state") or "") ==
           "TRANSIENT_LIKE_NATIVE_NONRECURRENCE_SUPPORTED"
    }

    if len(survivors) != 6:
        raise RuntimeError(f"Expected 6 frozen survivors; found {len(survivors)}")

    if set(str(r.get("population") or "") for r in survivors.values()) != {"PRIMARY_424"}:
        raise RuntimeError("v082 survivor population is not entirely PRIMARY_424")

    print()
    print("Frozen candidates:", len(survivors), "all PRIMARY_424")

    # Expand frozen v081 queue into candidate x scan tasks.
    frozen_pairs = []
    for q in queue81:
        sid = integer(q.get("scan_id"))
        pid = integer(q.get("physical_plate_id"))
        fname = str(q.get("filename_scan") or "")

        for rid in split_semicolon(q.get("candidate_ids")):
            if rid not in survivors:
                raise RuntimeError(
                    f"Frozen v081 queue references non-survivor candidate {rid}"
                )

            matching = [
                r for r in chron81
                if str(r["raw_match_row"]) == rid
                and integer(r.get("scan_id")) == sid
                and integer(r.get("physical_plate_id")) == pid
                and str(r.get("filename_scan") or "") == fname
            ]

            if not matching:
                raise RuntimeError(
                    f"No v081 chronology rows for candidate={rid} scan={sid}"
                )

            matching.sort(
                key=lambda r: (
                    float(r.get("gap_seconds") or 1e99),
                    str(r.get("relation_to_common_overlap") or ""),
                    int(r.get("exposure_index") or 0),
                )
            )

            frozen_pairs.append({
                "raw_match_row": rid,
                "population": survivors[rid]["population"],
                "scan_id": sid,
                "physical_plate_id": pid,
                "filename_scan": fname,
                "observatory": matching[0]["observatory"],
                "series": matching[0]["series"],
                "same_science_series": matching[0]["same_science_series"],
                "nearest_relation": matching[0]["relation_to_common_overlap"],
                "nearest_gap_seconds": matching[0]["gap_seconds"],
                "nearest_gap_hours": matching[0]["gap_hours"],
                "nearest_exposure_start_utc": matching[0]["exposure_start_utc"],
                "nearest_exposure_end_utc": matching[0]["exposure_end_utc"],
                "chronology_interval_count_for_plate": len(matching),
            })

    frozen_pairs.sort(
        key=lambda r: (
            int(r["raw_match_row"]),
            int(r["physical_plate_id"]),
            int(r["scan_id"]),
        )
    )

    print("Frozen close-time candidate x scan pairs:", len(frozen_pairs))
    print("Frozen close-time unique scans:", len({
        (r["scan_id"], r["filename_scan"]) for r in frozen_pairs
    }))

    # Chronology output: all <=24 h same-series plus <=6 h supplemental
    selected_chronology = []
    frozen_pair_keys = {
        (r["raw_match_row"], r["scan_id"], r["physical_plate_id"])
        for r in frozen_pairs
    }

    for r in chron81:
        key = (
            str(r["raw_match_row"]),
            integer(r.get("scan_id")),
            integer(r.get("physical_plate_id")),
        )
        if key in frozen_pair_keys:
            selected_chronology.append(r)

    write_csv(OUT_CHRON, selected_chronology)

    existing = {}
    for r in plate80:
        key = (
            str(r["raw_match_row"]),
            integer(r.get("physical_plate_id")),
            integer(r.get("scan_id")),
        )
        existing[key] = r

    mod = import_v080a()
    target_rows, target_map = mod.build_registered_targets()

    # Integrity: target map should match banked v080 target table.
    for rid in survivors:
        if rid not in target_map or rid not in targets80:
            raise RuntimeError(f"Missing frozen target for {rid}")

        a = targets80[rid]
        ra0 = float(a["registered_target_ra_deg"])
        de0 = float(a["registered_target_dec_deg"])
        ra1 = float(target_map[rid]["coord"].ra.deg)
        de1 = float(target_map[rid]["coord"].dec.deg)

        if abs(ra0-ra1) > 1e-10 or abs(de0-de1) > 1e-10:
            raise RuntimeError(f"Frozen registered target reconstruction changed for {rid}")

    acq = mod.acquisition_map()
    inj_mod, detect_array, method = mod.load_order01_injection()

    close_measurements = []
    close_injections = []
    reused_v080 = 0
    newly_executed = 0

    gaia_cache = {}

    for i, task in enumerate(frozen_pairs, 1):
        rid = task["raw_match_row"]
        pid = task["physical_plate_id"]
        sid = task["scan_id"]
        key = (rid, pid, sid)

        if key in existing:
            m = dict(existing[key])
            m["v082_measurement_source"] = "REUSED_BANKED_V080"
            inj = []
            reused_v080 += 1
        else:
            if rid not in gaia_cache:
                gaia_cache[rid] = load_v080_gaia(mod, rid)

            if sid not in acq:
                raise RuntimeError(
                    f"Frozen v081 close-time scan {sid} is absent from v079 acquisition manifest"
                )

            # Build the minimal plan-row interface consumed by the frozen v080 method.
            plan_row = {
                "raw_match_row": rid,
                "population": survivors[rid]["population"],
                "selection_role": "V081_FROZEN_CLOSE_TIME",
                "physical_plate_id": pid,
                "scan_id": sid,
                "archive_family": task["observatory"],
                "filename_scan": task["filename_scan"],
                "representative_exposure_start_utc":
                    task["nearest_exposure_start_utc"],
            }

            m, inj, was_checkpoint = mod.process_plan_row(
                plan_row,
                target_map[rid],
                gaia_cache[rid],
                acq[sid],
                inj_mod,
                detect_array,
                method,
            )

            m = dict(m)
            m["v082_measurement_source"] = (
                "REUSED_V082_CHECKPOINT" if was_checkpoint
                else "NEW_FROZEN_V080_METHOD_EXECUTION"
            )
            close_injections.extend(inj)
            newly_executed += int(not was_checkpoint)

        # Attach frozen chronology.
        m["v081_nearest_relation"] = task["nearest_relation"]
        m["v081_nearest_gap_seconds"] = task["nearest_gap_seconds"]
        m["v081_nearest_gap_hours"] = task["nearest_gap_hours"]
        m["v081_nearest_exposure_start_utc"] = task["nearest_exposure_start_utc"]
        m["v081_nearest_exposure_end_utc"] = task["nearest_exposure_end_utc"]
        m["v082_close_time_class"] = close_time_class(m)

        close_measurements.append(m)

        print(
            f"close-time {i}/{len(frozen_pairs)} "
            f"candidate={rid} scan={sid} "
            f"gap={float(task['nearest_gap_hours']):.3f} h "
            f"class={m['v082_close_time_class']} "
            f"source={m['v082_measurement_source']}"
        )

    close_measurements.sort(
        key=lambda r: (
            int(r["raw_match_row"]),
            int(r["physical_plate_id"]),
            int(r["scan_id"]),
        )
    )
    close_injections.sort(
        key=lambda r: (
            int(r["raw_match_row"]),
            int(r["physical_plate_id"]),
            float(r["psf_sigma_px"]),
            int(r["injection_polarity"]),
            float(r["target_detector_snr"]),
        )
    )

    write_csv(OUT_CLOSE, close_measurements)
    write_csv(OUT_INJ, close_injections)

    close_by_candidate = defaultdict(list)
    for r in close_measurements:
        close_by_candidate[str(r["raw_match_row"])].append(r)

    # Full per-candidate evidence synthesis.
    evid = []

    for rid in sorted(survivors, key=int):
        c = survivors[rid]
        t = targets80[rid]
        tr = tri75[rid]
        s81 = sum81.get(rid, {})
        close = close_by_candidate.get(rid, [])

        classes = sorted({str(r["v082_close_time_class"]) for r in close})
        gaps = sorted(float(r["v081_nearest_gap_hours"]) for r in close)

        evid.append({
            "raw_match_row": rid,
            "population": c["population"],
            "registered_target_ra_deg": t["registered_target_ra_deg"],
            "registered_target_dec_deg": t["registered_target_dec_deg"],

            "hamburg_exposure": "APPLAUSE:14120",
            "hamburg_physical_plate_id": 7685,
            "hamburg_science_scan": "LA08164_y.fits",
            "hamburg_science_snr": tr.get("a_snr", ""),
            "hamburg_science_polarity": tr.get("a_polarity", ""),

            "bamberg_exposure": "APPLAUSE:132654",
            "bamberg_physical_plate_id": 89580,
            "bamberg_science_scan": "012673_1953_h.fits",
            "bamberg_science_snr": tr.get("b_snr", ""),
            "bamberg_science_polarity": tr.get("b_polarity", ""),

            "science_common_overlap_seconds": 299,

            "v080_strict_native_recurrence_physical_plate_count":
                c.get("strict_native_recurrence_physical_plate_count", ""),
            "v080_sensitivity_qualified_negative_physical_plate_count":
                c.get("sensitivity_qualified_negative_physical_plate_count", ""),
            "v080_mechanical_evidence_state":
                c.get("mechanical_evidence_state", ""),

            "hamburg_same_series_within_1h":
                s81.get("hamburg_same_series_within_1h", ""),
            "hamburg_same_series_within_2h":
                s81.get("hamburg_same_series_within_2h", ""),
            "hamburg_same_series_within_6h":
                s81.get("hamburg_same_series_within_6h", ""),
            "hamburg_same_series_within_24h":
                s81.get("hamburg_same_series_within_24h", ""),

            "bamberg_same_series_within_1h":
                s81.get("bamberg_same_series_within_1h", ""),
            "bamberg_same_series_within_2h":
                s81.get("bamberg_same_series_within_2h", ""),
            "bamberg_same_series_within_6h":
                s81.get("bamberg_same_series_within_6h", ""),
            "bamberg_same_series_within_24h":
                s81.get("bamberg_same_series_within_24h", ""),

            "v081_bilateral_same_series_bracketing_both_observatories_within_24h":
                s81.get(
                    "bilateral_same_series_bracketing_both_observatories_within_24h",
                    ""
                ),

            "close_time_frozen_plate_count": len(close),
            "close_time_min_gap_hours": min(gaps) if gaps else "",
            "close_time_classes": ";".join(classes),
            "close_time_sensitivity_qualified_negative_count": sum(
                truth(r.get("sensitivity_qualified_negative")) for r in close
            ),
            "close_time_strict_native_recurrence_count": sum(
                truth(r.get("strict_native_recurrence")) for r in close
            ),

            "formal_candidate_disposition_changed": False,
        })

    write_csv(OUT_EVID, evid)

    class_counts = Counter(
        r["v082_close_time_class"] for r in close_measurements
    )

    report = {
        "status": "COMPLETE",
        "analysis_kind": "pair17_survivor_chronology_native_pixel_synthesis_v082",
        "contract_sha256": EXPECTED_CONTRACT_SHA,
        "population": {
            "candidates": 6,
            "population_label": "PRIMARY_424",
        },
        "frozen_close_time_queue": {
            "unique_scans": 1,
            "candidate_x_scan_pairs": len(frozen_pairs),
            "new_scan_downloads": 0,
        },
        "execution": {
            "reused_banked_v080_measurements": reused_v080,
            "new_v082_frozen_v080_method_executions": newly_executed,
            "close_time_class_counts": dict(class_counts),
            "close_time_injection_rows": len(close_injections),
        },
        "guards": {
            "network_calls": 0,
            "new_scan_downloads": 0,
            "manual_image_review": False,
            "threshold_retuning": False,
            "formal_candidate_disposition_changes": False,
            "v080_method_changes": False,
        },
        "outputs": {
            "survivor_evidence_table":
                str(OUT_EVID.relative_to(ROOT)).replace("\\", "/"),
            "close_time_native_pixel_measurements":
                str(OUT_CLOSE.relative_to(ROOT)).replace("\\", "/"),
            "close_time_injection_summary":
                str(OUT_INJ.relative_to(ROOT)).replace("\\", "/"),
            "close_time_chronology":
                str(OUT_CHRON.relative_to(ROOT)).replace("\\", "/"),
        },
    }

    write_json(OUT_JSON, report)

    print()
    print("=" * 128)
    print("v082 SURVIVOR SYNTHESIS COMPLETE")
    print("=" * 128)
    print("Candidates:", 6, "(all PRIMARY_424)")
    print("Close-time candidate x scan pairs:", len(frozen_pairs))
    print("Reused banked v080 measurements:", reused_v080)
    print("New frozen-v080-method executions:", newly_executed)
    print("Close-time evidence classes:")
    for key in sorted(class_counts):
        print(f"  {key}: {class_counts[key]}")
    print()
    print("Candidate evidence table:")
    for r in evid:
        print(
            f"  candidate {r['raw_match_row']}: "
            f"RA={float(r['registered_target_ra_deg']):.7f} "
            f"Dec={float(r['registered_target_dec_deg']):+.7f} "
            f"v080 negatives={r['v080_sensitivity_qualified_negative_physical_plate_count']} "
            f"close-time={r['close_time_classes'] or 'NONE'}"
        )
    print()
    print("Network calls:              0")
    print("New scan downloads:         0")
    print("Formal dispositions:        NONE")
    print("STAGE STATUS: COMPLETE")


if __name__ == "__main__":
    main()
