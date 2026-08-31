#!/usr/bin/env python3
"""
ORDER 01 — discovery exposure overlap freeze v028k

Consumes:
    results/order01_native_full_v028/order01_discovery_exposure_overlap_audit_v028j.json

Purpose
-------
Resolve and freeze the actual Order-01 discovery exposure intervals from the
already-existing, pre-frozen local provenance products discovered by v028j.

This stage does NOT infer timing from midpoint separation. It independently
cross-checks:
  * canonical_sub5_pairs_74.csv
  * production_sub5_queue_2026-08-20.csv
  * SUB5_V028_PIXEL_PROVENANCE_QUEUE_2026-08-21.csv
  * SUB5_V028_POSS47_TPV_GEOMETRY_CENSUS_2026-08-21.csv
  * SUB5_V028_POSS_PAIR_EXECUTION_MAP_2026-08-21.csv
  * POSS1_TIMESTAMP_AND_IDENTITY_NOTE_2026-08-20.md
  * the cached POSS identity FITS HEADER record already captured by v028j
  * the DASCH ai43437 expdate/exposure already captured by v028j

No network.
No science pixels.
No detector rerun.
No candidate promotion/deletion.

Important archival handling
---------------------------
The cached POSS identity FITS header has DATE-OBS=1951-11-04T07:00:00, while
the frozen physical-identity/timestamp note and every production/canonical
pair product resolve the physical E-plate exposure to
1951-11-05T07:00:00–08:00:00 UTC.

This script does NOT rewrite the FITS header. It records the exact 86400-second
discrepancy as archival/header context and uses the pre-frozen physical timing
for overlap because that timing is supported by multiple independent local
provenance products and the explicit timestamp-convention note.
"""

from __future__ import annotations

import csv
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "results" / "order01_native_full_v028"
RESEARCH = ROOT / "research"

INPUT = RESULTS / "order01_discovery_exposure_overlap_audit_v028j.json"

OUT_JSON = RESULTS / "order01_discovery_exposure_overlap_freeze_v028k.json"
OUT_CSV = RESULTS / "order01_discovery_exposure_overlap_freeze_v028k.csv"
OUT_MD = RESULTS / "ORDER01_DISCOVERY_EXPOSURE_OVERLAP_FREEZE_V028K.md"

EXPECTED_RANKS = [10, 24, 25, 26, 29, 30]
PAIR_KEY = (
    "DASCH:ivo://org.gavo.dc/~?dasch/q/ai43437 | "
    "POSS-I:413:E:rec297"
)
POSS_ID = "POSS-I:413:E:rec297"
POSS_PLATE_ID = "06S2"
DASCH_PLATE_ID = "ai43437"

EXPECTED_POSS_START = "1951-11-05T07:00:00+00:00"
EXPECTED_POSS_END = "1951-11-05T08:00:00+00:00"
EXPECTED_DASCH_START_PREFIX = "1951-11-05T07:00:59."
EXPECTED_DASCH_END_PREFIX = "1951-11-05T07:58:59."
EXPECTED_OVERLAP_S = 3480.0

SOURCE_FILES = [
    "canonical_sub5_pairs_74.csv",
    "production_sub5_queue_2026-08-20.csv",
    "SUB5_V028_PIXEL_PROVENANCE_QUEUE_2026-08-21.csv",
    "SUB5_V028_POSS47_TPV_GEOMETRY_CENSUS_2026-08-21.csv",
    "SUB5_V028_POSS_PAIR_EXECUTION_MAP_2026-08-21.csv",
]
NOTE_FILE = "POSS1_TIMESTAMP_AND_IDENTITY_NOTE_2026-08-20.md"


def parse_dt(s: str) -> datetime:
    s = str(s).strip().replace("Z", "+00:00")
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def sec(a: datetime, b: datetime) -> float:
    return (b - a).total_seconds()


def close(a: float, b: float, tol: float = 1e-5) -> bool:
    return math.isclose(a, b, rel_tol=0.0, abs_tol=tol)


def read_pair_row(path: Path) -> dict[str, str]:
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        rd = csv.DictReader(fh)
        if not rd.fieldnames:
            raise RuntimeError(f"{path}: missing CSV header")
        matches = []
        for row in rd:
            # Pair key is stable where present. Some derived files key with
            # poss_exposure_id + dasch_plate_id instead.
            if str(row.get("pair_key", "")).strip() == PAIR_KEY:
                matches.append(row)
                continue
            if (
                str(row.get("poss_exposure_id", "")).strip() == POSS_ID
                and str(row.get("dasch_plate_id", row.get("partner_dasch_plate_id", ""))).strip().lower()
                == DASCH_PLATE_ID
            ):
                matches.append(row)
        if len(matches) != 1:
            raise RuntimeError(
                f"{path}: expected exactly one Order-01 pair row; found {len(matches)}"
            )
        return matches[0]


def first(row: dict[str, str], *names: str) -> str | None:
    for name in names:
        v = row.get(name)
        if v is not None and str(v).strip() != "":
            return str(v).strip()
    return None


def interval_from_general_pair(row: dict[str, str]) -> dict[str, Any] | None:
    a_id = first(row, "exposure_a")
    b_id = first(row, "exposure_b")

    if not a_id or not b_id:
        return None

    a_start = first(row, "start_a_utc")
    a_end = first(row, "end_a_utc")
    b_start = first(row, "start_b_utc")
    b_end = first(row, "end_b_utc")
    if not all([a_start, a_end, b_start, b_end]):
        return None

    if "ai43437" in a_id.lower():
        dasch_start, dasch_end = a_start, a_end
        poss_start, poss_end = b_start, b_end
    elif "ai43437" in b_id.lower():
        dasch_start, dasch_end = b_start, b_end
        poss_start, poss_end = a_start, a_end
    else:
        return None

    return {
        "dasch_start": dasch_start,
        "dasch_end": dasch_end,
        "poss_start": poss_start,
        "poss_end": poss_end,
        "reported_overlap_s": first(row, "actual_exposure_overlap_s", "actual_overlap_s"),
        "reported_overlap_min": first(row, "actual_exposure_overlap_minutes"),
        "reported_overlap_fraction_a": first(row, "overlap_fraction_a"),
        "reported_overlap_fraction_b": first(row, "overlap_fraction_b"),
        "reported_midpoint_delta_min": first(row, "midpoint_delta_minutes"),
    }


def interval_from_derived_pair(row: dict[str, str]) -> dict[str, Any] | None:
    os = first(row, "overlap_start_utc")
    oe = first(row, "overlap_end_utc")
    ov = first(row, "actual_overlap_s", "actual_exposure_overlap_s")
    if not (os and oe and ov):
        return None
    return {
        "overlap_start": os,
        "overlap_end": oe,
        "reported_overlap_s": ov,
        "true_wcs_intersection": first(row, "true_wcs_intersection", "old_true_wcs_intersection"),
        "true_wcs_overlap_fraction": first(
            row, "true_wcs_overlap_fraction", "old_true_wcs_overlap_fraction"
        ),
        "pair_execution_state": first(row, "pair_execution_state"),
    }


def find_fits_413_record(v028j: dict[str, Any]) -> dict[str, Any]:
    matches = [
        r for r in v028j.get("local_fits_header_records", [])
        if "POSS-I_413_E_rec297" in str(r.get("path", ""))
    ]
    if len(matches) != 1:
        raise RuntimeError(
            f"expected exactly one cached POSS-I_413_E_rec297 FITS header record; "
            f"found {len(matches)}"
        )
    return matches[0]


def main() -> int:
    print("=" * 120)
    print("ORDER 01 — DISCOVERY EXPOSURE OVERLAP FREEZE v028k")
    print("=" * 120)

    if not INPUT.exists():
        print(f"FAIL: missing v028j input: {INPUT}")
        return 2

    vj = json.loads(INPUT.read_text(encoding="utf-8"))

    if vj.get("frozen_active_ranks") != EXPECTED_RANKS:
        print("FAIL: frozen active ranks mismatch.")
        return 3

    if (
        vj.get("historical_recurrence_summary")
        != "NO_CLEAN_INDEPENDENT_HISTORICAL_RECURRENCE_OBSERVATION_AMONG_FROZEN_SIX"
    ):
        print("FAIL: historical recurrence freeze state mismatch.")
        return 4

    # Recover and verify all local provenance sources.
    source_results = []
    full_interval_sources = []
    overlap_only_sources = []

    for name in SOURCE_FILES:
        p = RESEARCH / name
        if not p.exists():
            print(f"FAIL: required frozen/local provenance source missing: {p}")
            return 5
        row = read_pair_row(p)
        general = interval_from_general_pair(row)
        derived = interval_from_derived_pair(row)
        item = {
            "source": str(p.relative_to(ROOT)),
            "pair_key": first(row, "pair_key"),
            "general_interval": general,
            "derived_overlap": derived,
        }
        source_results.append(item)
        if general:
            full_interval_sources.append((name, general))
        if derived:
            overlap_only_sources.append((name, derived))

    if len(full_interval_sources) < 3:
        print(
            "FAIL: fewer than three local provenance products carry full pair intervals."
        )
        return 6

    # Parse first full source as reference, then require all other full sources
    # to reproduce the same physical exposure intervals to microsecond tolerance.
    ref_name, ref = full_interval_sources[0]
    d0 = parse_dt(ref["dasch_start"])
    d1 = parse_dt(ref["dasch_end"])
    p0 = parse_dt(ref["poss_start"])
    p1 = parse_dt(ref["poss_end"])

    if not str(ref["dasch_start"]).startswith(EXPECTED_DASCH_START_PREFIX):
        print(f"FAIL: unexpected DASCH start in {ref_name}: {ref['dasch_start']}")
        return 7
    if not str(ref["dasch_end"]).startswith(EXPECTED_DASCH_END_PREFIX):
        print(f"FAIL: unexpected DASCH end in {ref_name}: {ref['dasch_end']}")
        return 7
    if parse_dt(EXPECTED_POSS_START) != p0 or parse_dt(EXPECTED_POSS_END) != p1:
        print(f"FAIL: unexpected POSS interval in {ref_name}")
        return 7

    for name, x in full_interval_sources[1:]:
        checks = [
            abs(sec(d0, parse_dt(x["dasch_start"]))),
            abs(sec(d1, parse_dt(x["dasch_end"]))),
            abs(sec(p0, parse_dt(x["poss_start"]))),
            abs(sec(p1, parse_dt(x["poss_end"]))),
        ]
        if max(checks) > 1e-4:
            print(f"FAIL: interval disagreement in {name}: max delta {max(checks)} s")
            return 8

    dasch_duration_s = sec(d0, d1)
    poss_duration_s = sec(p0, p1)
    overlap_start = max(d0, p0)
    overlap_end = min(d1, p1)
    overlap_s = max(0.0, sec(overlap_start, overlap_end))

    if not close(dasch_duration_s, 3480.0):
        print(f"FAIL: DASCH duration not 3480 s: {dasch_duration_s}")
        return 9
    if not close(poss_duration_s, 3600.0):
        print(f"FAIL: POSS duration not 3600 s: {poss_duration_s}")
        return 9
    if not close(overlap_s, EXPECTED_OVERLAP_S):
        print(f"FAIL: actual overlap not 3480 s: {overlap_s}")
        return 9

    # Verify any overlap-only sources against the independently recomputed result.
    for name, x in overlap_only_sources:
        if abs(sec(overlap_start, parse_dt(x["overlap_start"]))) > 1e-4:
            print(f"FAIL: overlap-start mismatch in {name}")
            return 10
        if abs(sec(overlap_end, parse_dt(x["overlap_end"]))) > 1e-4:
            print(f"FAIL: overlap-end mismatch in {name}")
            return 10
        if not close(float(x["reported_overlap_s"]), overlap_s):
            print(f"FAIL: overlap-duration mismatch in {name}")
            return 10

    # DASCH expdate semantics: v028j recorded 07:30 with 58-min duration.
    dasch_meta = vj["dasch_discovery_pair"]
    expdate = parse_dt(dasch_meta["expdate"])
    midpoint = d0 + (d1 - d0) / 2
    expdate_midpoint_delta_s = abs(sec(midpoint, expdate))
    dasch_semantics = (
        "MIDPOINT_CONFIRMED_BY_FROZEN_INTERVAL"
        if expdate_midpoint_delta_s <= 1e-3
        else "NOT_MIDPOINT_REVIEW_REQUIRED"
    )
    if dasch_semantics != "MIDPOINT_CONFIRMED_BY_FROZEN_INTERVAL":
        print(
            "FAIL: DASCH expdate does not reproduce interval midpoint: "
            f"delta={expdate_midpoint_delta_s}s"
        )
        return 11

    # POSS timestamp convention note must explicitly support physical night/start.
    note_path = RESEARCH / NOTE_FILE
    if not note_path.exists():
        print(f"FAIL: timestamp convention note missing: {note_path}")
        return 12
    note = note_path.read_text(encoding="utf-8", errors="replace")
    required_note_phrases = [
        "observing night: 1951-11-04 to 1951-11-05",
        "E start: 23:00 PST; exposure 60 min -> 1951-11-05 07:00 UTC",
    ]
    missing = [s for s in required_note_phrases if s not in note]
    if missing:
        print(f"FAIL: POSS timestamp convention note missing expected text: {missing}")
        return 13

    fits_rec = find_fits_413_record(vj)
    hdr = fits_rec.get("header") or {}
    if str(hdr.get("PLATEID", "")) != POSS_PLATE_ID:
        print(f"FAIL: cached POSS FITS PLATEID mismatch: {hdr.get('PLATEID')}")
        return 14
    if float(hdr.get("EXPOSURE", -1)) != 60.0:
        print(f"FAIL: cached POSS FITS exposure mismatch: {hdr.get('EXPOSURE')}")
        return 14

    raw_header_date = str(hdr.get("DATE-OBS", ""))
    raw_header_dt = parse_dt(raw_header_date)
    header_vs_physical_start_s = sec(raw_header_dt, p0)
    header_date_context = (
        "LEGACY_HEADER_DATE_ONE_DAY_EARLIER_THAN_FROZEN_PHYSICAL_IDENTITY"
        if close(header_vs_physical_start_s, 86400.0, tol=1e-3)
        else "HEADER_DATE_DISCREPANCY_REQUIRES_REVIEW"
    )
    if header_date_context != (
        "LEGACY_HEADER_DATE_ONE_DAY_EARLIER_THAN_FROZEN_PHYSICAL_IDENTITY"
    ):
        print(
            "FAIL: cached POSS FITS DATE-OBS discrepancy is not the expected "
            f"one-day legacy offset: {header_vs_physical_start_s}s"
        )
        return 15

    overlap_fraction_dasch = overlap_s / dasch_duration_s
    overlap_fraction_poss = overlap_s / poss_duration_s

    payload = {
        "stage": "ORDER01_DISCOVERY_EXPOSURE_OVERLAP_FREEZE_V028K",
        "input": str(INPUT.relative_to(ROOT)),
        "frozen_active_ranks": EXPECTED_RANKS,
        "guards": {
            "network_access": False,
            "science_pixels_read": False,
            "detector_rerun": False,
            "candidate_promotion": False,
            "candidate_deletion": False,
            "midpoint_separation_substituted_for_overlap": False,
            "fits_header_rewritten": False,
        },
        "pair_identity": {
            "pair_key": PAIR_KEY,
            "poss_exposure_id": POSS_ID,
            "poss_plate_id": POSS_PLATE_ID,
            "dasch_plate_id": DASCH_PLATE_ID,
        },
        "provenance_crosscheck": {
            "full_interval_source_count": len(full_interval_sources),
            "overlap_only_source_count": len(overlap_only_sources),
            "sources": source_results,
            "timestamp_note": str(note_path.relative_to(ROOT)),
        },
        "resolved_exposures": {
            "POSS": {
                "start_utc": iso(p0),
                "end_utc": iso(p1),
                "duration_s": poss_duration_s,
                "duration_min": poss_duration_s / 60.0,
                "timing_basis": (
                    "FROZEN_PHYSICAL_IDENTITY_NOTE_PLUS_MULTIPLE_PREEXISTING_PAIR_TABLES"
                ),
            },
            "DASCH": {
                "start_utc": iso(d0),
                "end_utc": iso(d1),
                "duration_s": dasch_duration_s,
                "duration_min": dasch_duration_s / 60.0,
                "recorded_expdate": dasch_meta["expdate"],
                "expdate_semantics": dasch_semantics,
                "expdate_vs_resolved_midpoint_delta_s": expdate_midpoint_delta_s,
            },
        },
        "actual_exposure_overlap": {
            "status": "RESOLVED_AND_CROSSCHECKED",
            "start_utc": iso(overlap_start),
            "end_utc": iso(overlap_end),
            "duration_s": overlap_s,
            "duration_min": overlap_s / 60.0,
            "fraction_of_dasch_exposure": overlap_fraction_dasch,
            "fraction_of_poss_exposure": overlap_fraction_poss,
            "containment": "DASCH_EXPOSURE_FULLY_CONTAINED_WITHIN_POSS_EXPOSURE",
        },
        "poss_cached_fits_header_context": {
            "path": fits_rec.get("path"),
            "plate_id": hdr.get("PLATEID"),
            "survey": hdr.get("SURVEY"),
            "telescope": hdr.get("TELESCOP"),
            "raw_date_obs": raw_header_date,
            "raw_exposure_value": hdr.get("EXPOSURE"),
            "raw_header_vs_physical_start_seconds": header_vs_physical_start_s,
            "classification": header_date_context,
            "handling": (
                "RAW_HEADER_PRESERVED; PHYSICAL_TIMING_FROM_PRE_FROZEN_IDENTITY_CONVENTION"
            ),
        },
        "historical_recurrence_summary":
            vj["historical_recurrence_summary"],
        "interpretive_boundary": (
            "The 58-minute common exposure window establishes strong temporal "
            "contemporaneity of the two discovery plates. It does not by itself "
            "establish that any candidate signal is astrophysical."
        ),
    }

    OUT_JSON.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    with OUT_CSV.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(
            fh,
            fieldnames=[
                "poss_exposure_id", "poss_plate_id", "dasch_plate_id",
                "poss_start_utc", "poss_end_utc", "poss_duration_s",
                "dasch_start_utc", "dasch_end_utc", "dasch_duration_s",
                "overlap_start_utc", "overlap_end_utc", "overlap_s",
                "overlap_min", "fraction_of_dasch", "fraction_of_poss",
                "dasch_expdate_semantics", "poss_raw_fits_date_obs",
                "poss_raw_header_vs_physical_start_s",
                "poss_header_date_context",
            ],
        )
        w.writeheader()
        w.writerow({
            "poss_exposure_id": POSS_ID,
            "poss_plate_id": POSS_PLATE_ID,
            "dasch_plate_id": DASCH_PLATE_ID,
            "poss_start_utc": iso(p0),
            "poss_end_utc": iso(p1),
            "poss_duration_s": poss_duration_s,
            "dasch_start_utc": iso(d0),
            "dasch_end_utc": iso(d1),
            "dasch_duration_s": dasch_duration_s,
            "overlap_start_utc": iso(overlap_start),
            "overlap_end_utc": iso(overlap_end),
            "overlap_s": overlap_s,
            "overlap_min": overlap_s / 60.0,
            "fraction_of_dasch": overlap_fraction_dasch,
            "fraction_of_poss": overlap_fraction_poss,
            "dasch_expdate_semantics": dasch_semantics,
            "poss_raw_fits_date_obs": raw_header_date,
            "poss_raw_header_vs_physical_start_s": header_vs_physical_start_s,
            "poss_header_date_context": header_date_context,
        })

    md = []
    md.append("# ORDER 01 — Discovery Exposure Overlap Freeze v028k")
    md.append("")
    md.append("## Frozen result")
    md.append("")
    md.append(f"- POSS `{POSS_ID}` / physical plate `{POSS_PLATE_ID}`:")
    md.append(f"  - start: `{iso(p0)}`")
    md.append(f"  - end: `{iso(p1)}`")
    md.append(f"  - duration: **{poss_duration_s/60:.1f} min**")
    md.append(f"- DASCH `{DASCH_PLATE_ID}`:")
    md.append(f"  - start: `{iso(d0)}`")
    md.append(f"  - end: `{iso(d1)}`")
    md.append(f"  - duration: **{dasch_duration_s/60:.1f} min**")
    md.append("")
    md.append(
        f"**Actual exposure overlap:** `{iso(overlap_start)}` to "
        f"`{iso(overlap_end)}` = **{overlap_s:.0f} s / {overlap_s/60:.1f} min**."
    )
    md.append("")
    md.append(
        f"This is **{100*overlap_fraction_dasch:.2f}% of the DASCH exposure** "
        f"and **{100*overlap_fraction_poss:.2f}% of the POSS exposure**."
    )
    md.append("")
    md.append("Containment: `DASCH_EXPOSURE_FULLY_CONTAINED_WITHIN_POSS_EXPOSURE`.")
    md.append("")
    md.append("## Timestamp semantics")
    md.append("")
    md.append(
        f"- DASCH recorded `expdate={dasch_meta['expdate']}` is confirmed as "
        f"the exposure midpoint to within {expdate_midpoint_delta_s:.6f} s."
    )
    md.append(
        "- POSS timing is taken from the frozen physical-identity/timestamp "
        "convention and reproduced by multiple pre-existing pair tables."
    )
    md.append("")
    md.append("## Cached POSS FITS header discrepancy")
    md.append("")
    md.append(
        f"- Raw cached header `DATE-OBS={raw_header_date}` is exactly "
        f"{header_vs_physical_start_s:.0f} s earlier than the frozen physical start."
    )
    md.append(
        "- The raw header is preserved unchanged and recorded as "
        "`LEGACY_HEADER_DATE_ONE_DAY_EARLIER_THAN_FROZEN_PHYSICAL_IDENTITY`."
    )
    md.append("")
    md.append("## Guardrails")
    md.append("")
    md.append("- No network access.")
    md.append("- No science pixels read.")
    md.append("- No detector rerun.")
    md.append("- No candidate promoted or deleted.")
    md.append("- Midpoint separation was not substituted for exposure overlap.")
    md.append("")
    md.append(
        "The 58-minute common window establishes temporal contemporaneity of "
        "the two discovery plates, not astrophysical reality of the candidates."
    )
    OUT_MD.write_text("\n".join(md), encoding="utf-8")

    print("Provenance interval cross-checks: PASS")
    print(f"  full interval sources: {len(full_interval_sources)}")
    print(f"  overlap-only sources:  {len(overlap_only_sources)}")
    print()
    print("Resolved discovery exposures:")
    print(
        f"  POSS  {POSS_ID}: {iso(p0)} -> {iso(p1)} "
        f"({poss_duration_s/60:.1f} min)"
    )
    print(
        f"  DASCH {DASCH_PLATE_ID}: {iso(d0)} -> {iso(d1)} "
        f"({dasch_duration_s/60:.1f} min)"
    )
    print(
        f"  DASCH expdate semantics: {dasch_semantics} "
        f"(midpoint delta {expdate_midpoint_delta_s:.6f} s)"
    )
    print()
    print("ACTUAL EXPOSURE OVERLAP:")
    print(
        f"  {iso(overlap_start)} -> {iso(overlap_end)} "
        f"= {overlap_s:.0f} s = {overlap_s/60:.1f} min"
    )
    print(f"  fraction DASCH: {overlap_fraction_dasch:.6f}")
    print(f"  fraction POSS:  {overlap_fraction_poss:.6f}")
    print("  containment: DASCH_EXPOSURE_FULLY_CONTAINED_WITHIN_POSS_EXPOSURE")
    print()
    print("Cached POSS FITS header:")
    print(f"  PLATEID={hdr.get('PLATEID')} SURVEY={hdr.get('SURVEY')}")
    print(f"  raw DATE-OBS={raw_header_date} EXPOSURE={hdr.get('EXPOSURE')}")
    print(f"  raw header vs physical start: {header_vs_physical_start_s:.0f} s")
    print(f"  context: {header_date_context}")
    print("  raw header was NOT rewritten")
    print()
    print("Outputs:")
    print(f"  {OUT_JSON}")
    print(f"  {OUT_CSV}")
    print(f"  {OUT_MD}")
    print()
    print("No external query was made.")
    print("No science pixel was read.")
    print("No detector was rerun.")
    print("No candidate was promoted or deleted.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
