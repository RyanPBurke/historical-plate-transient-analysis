#!/usr/bin/env python3
"""
ORDER 01 — discovery exposure / overlap audit v028j

Inputs
------
results/order01_native_full_v028/order01_historical_closehit_flag_audit_v028i.json
results/order01_native_full_v028/order01_branchA_candidate_adjudication_v028f.json
results/order01_native_full_v028/order01_candidate_evidence_inventory_v028d.csv

Purpose
-------
1. Freeze the historical-recurrence evidence state after v028g/h/i WITHOUT
   changing candidate state.
2. Recover the discovery DASCH pair-plate metadata (ai43437) from the completed
   exposure census.
3. Search existing LOCAL project metadata / FITS HEADERS for the POSS discovery
   exposure timing.
4. Calculate an actual exposure-overlap interval ONLY when both exposure
   intervals can be constructed from supported timestamp semantics.

This script is deliberately conservative about timestamp semantics.  A field
named "expdate" is NOT silently assumed to be start time or midpoint.

Guards
------
* no network
* no science-pixel reads
* no detector rerun
* no candidate promotion/deletion
* no .npy array loads
* FITS headers may be read; FITS pixel arrays are not accessed
"""

from __future__ import annotations

import csv
import json
import os
import re
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "results" / "order01_native_full_v028"
WORK = ROOT / "work" / "order01_native_full_v028"

FLAG_AUDIT = RESULTS / "order01_historical_closehit_flag_audit_v028i.json"
ADJUDICATION = RESULTS / "order01_branchA_candidate_adjudication_v028f.json"
INVENTORY = RESULTS / "order01_candidate_evidence_inventory_v028d.csv"

OUT_JSON = RESULTS / "order01_discovery_exposure_overlap_audit_v028j.json"
OUT_CSV = RESULTS / "order01_discovery_exposure_overlap_audit_v028j.csv"
OUT_MD = RESULTS / "ORDER01_DISCOVERY_EXPOSURE_OVERLAP_AUDIT_V028J.md"

EXPECTED = [10, 24, 25, 26, 29, 30]
PAIR_DASCH_PLATE = "ai43437"

TEXT_EXTS = {
    ".json", ".csv", ".md", ".txt", ".yaml", ".yml", ".toml",
    ".ini", ".cfg", ".py", ".ps1", ".log", ".hdr", ".head",
}
FITS_EXTS = {".fits", ".fit", ".fts", ".fz"}

MAX_TEXT_BYTES = 12 * 1024 * 1024
MAX_TEXT_FILES = 5000
MAX_FITS_FILES = 500
MAX_CLUES = 250

DATE_TOKEN = "1951-11-05"

HEADER_KEYS = [
    "DATE-OBS", "DATEOBS", "DATE", "UT", "UTC", "TIME-OBS", "TIMEOBS",
    "EXPTIME", "EXPOSURE", "EXP_TIME", "TM-START", "TM-END",
    "MJD-OBS", "JD", "PLATEID", "PLATE-ID", "PLATE", "PLATEID",
    "SURVEY", "TELESCOP", "OBSERVAT", "ORIGIN", "FILTER", "BANDPASS",
]


def normpath(x: str) -> str:
    return str(x).replace("\\", "/")


def parse_iso(s: str) -> datetime:
    s = str(s).strip().replace("Z", "+00:00")
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def interval_from_timestamp(
    timestamp: datetime,
    duration_s: float,
    semantics: str,
) -> tuple[datetime, datetime]:
    if semantics == "START":
        return timestamp, timestamp + timedelta(seconds=duration_s)
    if semantics == "MIDPOINT":
        half = timedelta(seconds=duration_s / 2.0)
        return timestamp - half, timestamp + half
    if semantics == "END":
        return timestamp - timedelta(seconds=duration_s), timestamp
    raise ValueError(semantics)


def overlap(
    a0: datetime, a1: datetime, b0: datetime, b1: datetime
) -> tuple[datetime | None, datetime | None, float]:
    s = max(a0, b0)
    e = min(a1, b1)
    sec = max(0.0, (e - s).total_seconds())
    return (s, e, sec) if sec > 0 else (None, None, 0.0)


def historical_state(flag_rows: list[dict[str, Any]]) -> dict[int, str]:
    by_rank = {int(x["strict_rank"]): x for x in flag_rows}
    state = {
        24: "NO_HISTORICAL_CLOSE5_HIT_IN_1024",
        29: "NO_HISTORICAL_CLOSE5_HIT_IN_1024",
    }
    for r in (10, 26, 30):
        x = by_rank[r]
        if (
            x["geometry_label"]
            == "EXTREME_DISPLACEMENT_FROM_WELL_SAMPLED_REFERENCE_LOCUS"
            and int(x["direct_association_warning_count"]) == 0
        ):
            state[r] = (
                "SINGLE_CLOSE5_HIT_WEAKENED_BY_EXTREME_REFERENCE_DISPLACEMENT"
            )
        else:
            state[r] = "SINGLE_CLOSE5_HIT_REQUIRES_REVIEW"
    x = by_rank[25]
    if int(x["direct_association_warning_count"]) > 0:
        state[25] = "SINGLE_CLOSE5_HIT_WEAKENED_BY_DIRECT_ASSOCIATION_WARNINGS"
    else:
        state[25] = "SINGLE_CLOSE5_HIT_REQUIRES_REVIEW"
    return state


def stream_pair_dasch_rows() -> dict[int, dict[str, Any]]:
    out: dict[int, list[dict[str, Any]]] = defaultdict(list)
    with INVENTORY.open("r", encoding="utf-8", newline="") as fh:
        rd = csv.DictReader(fh)
        for row in rd:
            sf = normpath(row.get("source_file", ""))
            if not sf.endswith("order01_queryexps_exposure_census_v028c.csv"):
                continue
            try:
                rank = int(row["strict_rank"])
            except Exception:
                continue
            if rank not in EXPECTED:
                continue
            try:
                ev = json.loads(row["evidence_json"])
            except Exception:
                continue
            if (
                str(ev.get("plate_id", "")).lower() == PAIR_DASCH_PLATE
                and str(ev.get("is_pair_plate_ai43437", "")).lower() == "true"
            ):
                out[rank].append(ev)

    final = {}
    for rank in EXPECTED:
        rows = out.get(rank, [])
        if len(rows) != 1:
            raise RuntimeError(
                f"rank {rank}: expected exactly one {PAIR_DASCH_PLATE} "
                f"exposure-census row; found {len(rows)}"
            )
        final[rank] = rows[0]
    return final


def candidate_roots() -> list[Path]:
    roots = []
    for p in [
        ROOT,
        RESULTS,
        WORK,
        ROOT / "data",
        ROOT / "inputs",
        ROOT / "input",
        ROOT / "cache",
        ROOT / "downloads",
    ]:
        if p.exists() and p not in roots:
            roots.append(p)
    return roots


def path_relevant(p: Path) -> bool:
    low = normpath(p).lower()
    if any(part in low for part in ["/.venv/", "/.git/", "/node_modules/", "/__pycache__/"]):
        return False
    # Strongly prefer project/order/POSS material. General ROOT text remains
    # eligible because source metadata may live in a config file.
    return True


def scan_text_clues() -> list[dict[str, Any]]:
    clues = []
    seen = set()
    files_seen = 0

    for base in candidate_roots():
        for p in base.rglob("*"):
            if files_seen >= MAX_TEXT_FILES or len(clues) >= MAX_CLUES:
                return clues
            if not p.is_file() or not path_relevant(p):
                continue
            if p.suffix.lower() not in TEXT_EXTS:
                continue
            key = str(p.resolve())
            if key in seen:
                continue
            seen.add(key)
            files_seen += 1

            try:
                size = p.stat().st_size
            except OSError:
                continue
            if size > MAX_TEXT_BYTES:
                continue

            try:
                text = p.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue

            lower = text.lower()
            # Require timing/date plus some discovery context.
            has_date = DATE_TOKEN in text
            has_pair = PAIR_DASCH_PLATE in lower
            has_poss = "poss" in lower or "palomar" in lower
            has_time_key = any(
                k in lower
                for k in [
                    "date-obs", "date_obs", "dateobs", "exptime", "exposure",
                    "midpoint", "start_time", "end_time", "time-obs",
                ]
            )
            if not ((has_date or has_pair) and (has_poss or has_time_key)):
                continue

            lines = text.splitlines()
            hits = []
            for idx, line in enumerate(lines, start=1):
                lo = line.lower()
                if (
                    DATE_TOKEN in line
                    or PAIR_DASCH_PLATE in lo
                    or (
                        ("poss" in lo or "palomar" in lo)
                        and any(
                            t in lo for t in
                            ["date", "time", "exposure", "exptime", "plate"]
                        )
                    )
                ):
                    hits.append({"line": idx, "text": line[:500]})
                    if len(hits) >= 12:
                        break
            if hits:
                clues.append({
                    "path": str(p.relative_to(ROOT)) if ROOT in p.parents else str(p),
                    "size_bytes": size,
                    "hits": hits,
                })
    return clues


def scan_fits_headers() -> list[dict[str, Any]]:
    rows = []
    seen = set()
    count = 0

    try:
        from astropy.io import fits
    except Exception:
        return [{
            "status": "ASTROPY_UNAVAILABLE",
            "note": "FITS header scan skipped; no pixel fallback attempted.",
        }]

    # Search likely areas. Merely opening HDUs and reading headers does not
    # access hdu.data.
    for base in candidate_roots():
        for p in base.rglob("*"):
            if count >= MAX_FITS_FILES:
                return rows
            if not p.is_file() or not path_relevant(p):
                continue
            name = p.name.lower()
            if not (
                p.suffix.lower() in FITS_EXTS
                or name.endswith(".fits.gz")
                or name.endswith(".fit.gz")
            ):
                continue
            key = str(p.resolve())
            if key in seen:
                continue
            seen.add(key)
            count += 1

            lowpath = normpath(p).lower()
            # Avoid unrelated package/sample FITS files when ROOT is broad.
            if not any(
                token in lowpath
                for token in [
                    "order01", "poss", "palomar", "dasch",
                    "/work/", "/input", "/data/", "/download",
                ]
            ):
                continue

            try:
                with fits.open(
                    p,
                    mode="readonly",
                    memmap=True,
                    do_not_scale_image_data=True,
                    lazy_load_hdus=True,
                ) as hdul:
                    hdr = hdul[0].header
                    kv = {}
                    for k in HEADER_KEYS:
                        if k in hdr:
                            try:
                                kv[k] = hdr[k]
                            except Exception:
                                pass
                    # Also retain any header card containing POSS/Palomar/date/exposure.
                    extra = {}
                    for card in hdr.cards:
                        txt = f"{card.keyword}={card.value} {card.comment}"
                        lo = txt.lower()
                        if (
                            "poss" in lo
                            or "palomar" in lo
                            or DATE_TOKEN in txt
                            or "exptime" in lo
                            or "exposure" in lo
                        ):
                            extra[card.keyword] = str(card.value)
                    if kv or extra:
                        rows.append({
                            "path": str(p.relative_to(ROOT)) if ROOT in p.parents else str(p),
                            "header": kv,
                            "extra_relevant_cards": extra,
                            "pixels_read": False,
                        })
            except Exception as exc:
                rows.append({
                    "path": str(p.relative_to(ROOT)) if ROOT in p.parents else str(p),
                    "status": "HEADER_READ_FAILED",
                    "error": repr(exc),
                    "pixels_read": False,
                })
    return rows


def derive_header_interval(row: dict[str, Any]) -> dict[str, Any] | None:
    """
    Conservative auto-derivation only for explicit DATE-OBS + EXPTIME-style
    combinations. DATE-OBS is NOT automatically assumed to be exposure start:
    we return possible interpretations unless an explicit start/end keyword exists.
    """
    hdr = row.get("header") or {}
    if not hdr:
        return None

    # Timestamp candidate.
    date_key = next(
        (k for k in ("DATE-OBS", "DATEOBS") if k in hdr), None
    )
    dur_key = next(
        (k for k in ("EXPTIME", "EXPOSURE", "EXP_TIME") if k in hdr), None
    )
    if not date_key:
        return None

    raw_date = str(hdr[date_key]).strip()
    # Add TIME-OBS if DATE-OBS is date only.
    if "T" not in raw_date:
        time_key = next(
            (k for k in ("TIME-OBS", "TIMEOBS", "UT", "UTC") if k in hdr),
            None,
        )
        if time_key:
            raw_date = raw_date + "T" + str(hdr[time_key]).strip()

    try:
        ts = parse_iso(raw_date)
    except Exception:
        return {
            "path": row.get("path"),
            "status": "TIMESTAMP_PARSE_FAILED",
            "raw_date": raw_date,
            "date_key": date_key,
        }

    dur_s = None
    if dur_key:
        try:
            dur_s = float(hdr[dur_key])
        except Exception:
            dur_s = None

    result = {
        "path": row.get("path"),
        "date_key": date_key,
        "timestamp": iso(ts),
        "duration_key": dur_key,
        "duration_seconds_raw": dur_s,
        "timestamp_semantics": "UNVERIFIED",
    }
    if dur_s is not None:
        result["possible_intervals"] = {
            sem: {
                "start": iso(interval_from_timestamp(ts, dur_s, sem)[0]),
                "end": iso(interval_from_timestamp(ts, dur_s, sem)[1]),
            }
            for sem in ("START", "MIDPOINT", "END")
        }
    return result


def main() -> int:
    print("=" * 120)
    print("ORDER 01 — DISCOVERY EXPOSURE / OVERLAP AUDIT v028j")
    print("=" * 120)

    for p in (FLAG_AUDIT, ADJUDICATION, INVENTORY):
        if not p.exists():
            print(f"FAIL: missing required input: {p}")
            return 2

    flag = json.loads(FLAG_AUDIT.read_text(encoding="utf-8"))
    adj = json.loads(ADJUDICATION.read_text(encoding="utf-8"))

    if flag.get("frozen_active_ranks") != EXPECTED:
        print("FAIL: v028i frozen rank mismatch.")
        return 3
    if adj.get("frozen_active_ranks") != EXPECTED:
        print("FAIL: v028f frozen rank mismatch.")
        return 3

    hist = historical_state(flag.get("results") or [])

    print("Historical-recurrence evidence freeze:")
    for r in EXPECTED:
        print(f"  #{r:>2}: {hist[r]}")
    print("  Candidate state remains unchanged.")
    print()

    pair = stream_pair_dasch_rows()
    invariant_fields = ["plate_id", "expdate", "exptime_min", "series", "platenum"]
    for field in invariant_fields:
        vals = {str(pair[r].get(field, "")) for r in EXPECTED}
        if len(vals) != 1:
            print(f"FAIL: discovery DASCH pair field {field!r} is not invariant: {vals}")
            return 4

    d0 = pair[EXPECTED[0]]
    dasch_timestamp = parse_iso(d0["expdate"])
    dasch_duration_s = float(d0["exptime_min"]) * 60.0

    print("Discovery DASCH pair plate recovered:")
    print(f"  plate: {d0['plate_id']}")
    print(f"  expdate: {d0['expdate']}")
    print(f"  exposure duration: {d0['exptime_min']} min")
    print("  IMPORTANT: expdate start/mid/end semantics are not assumed.")
    print()

    dasch_possible = {}
    for sem in ("START", "MIDPOINT", "END"):
        s, e = interval_from_timestamp(dasch_timestamp, dasch_duration_s, sem)
        dasch_possible[sem] = {"start": iso(s), "end": iso(e)}

    print("Searching local project metadata and FITS headers for POSS timing...")
    text_clues = scan_text_clues()
    fits_rows = scan_fits_headers()
    header_intervals = [
        x for x in (derive_header_interval(r) for r in fits_rows)
        if x is not None
    ]

    print(f"  text metadata clue files: {len(text_clues)}")
    print(f"  FITS/header records: {len(fits_rows)}")
    print(f"  parseable DATE-OBS header candidates: {len(header_intervals)}")
    print()

    print("Most relevant text clues:")
    for clue in text_clues[:20]:
        print(f"  {clue['path']}")
        for h in clue["hits"][:5]:
            print(f"    L{h['line']}: {h['text']}")
    if not text_clues:
        print("  none")
    print()

    print("FITS/header timing candidates:")
    for h in header_intervals[:30]:
        print(
            f"  {h.get('path')} "
            f"{h.get('date_key')}={h.get('timestamp')} "
            f"{h.get('duration_key')}={h.get('duration_seconds_raw')} "
            f"semantics={h.get('timestamp_semantics')}"
        )
    if not header_intervals:
        print("  none")
    print()

    # We deliberately do NOT auto-select a POSS interval merely because a
    # DATE-OBS exists. That selection belongs in the next pass once we see the
    # exact header/source semantics.
    payload = {
        "stage": "ORDER01_DISCOVERY_EXPOSURE_OVERLAP_AUDIT_V028J",
        "frozen_active_ranks": EXPECTED,
        "guards": {
            "network_access": False,
            "science_pixels_read": False,
            "detector_rerun": False,
            "candidate_promotion": False,
            "candidate_deletion": False,
            "npy_arrays_loaded": False,
            "fits_headers_may_be_read": True,
            "fits_pixel_arrays_read": False,
        },
        "historical_recurrence_evidence_state": {
            str(k): v for k, v in hist.items()
        },
        "historical_recurrence_summary": (
            "NO_CLEAN_INDEPENDENT_HISTORICAL_RECURRENCE_OBSERVATION_AMONG_FROZEN_SIX"
        ),
        "dasch_discovery_pair": {
            "plate_id": d0["plate_id"],
            "series": d0["series"],
            "platenum": d0["platenum"],
            "expdate": d0["expdate"],
            "exptime_min": float(d0["exptime_min"]),
            "timestamp_semantics": "UNVERIFIED_EXPDATE_SEMANTICS",
            "possible_intervals": dasch_possible,
            "per_rank_plate_geometry": {
                str(r): {
                    "target_ra_deg": float(pair[r]["target_ra_deg"]),
                    "target_dec_deg": float(pair[r]["target_dec_deg"]),
                    "centerdist": float(pair[r]["centerdist"]),
                    "edgedist": float(pair[r]["edgedist"]),
                    "limMagApass": (
                        float(pair[r]["limMagApass"])
                        if str(pair[r]["limMagApass"]).strip() else None
                    ),
                    "limMagAtlas": (
                        float(pair[r]["limMagAtlas"])
                        if str(pair[r]["limMagAtlas"]).strip() else None
                    ),
                }
                for r in EXPECTED
            },
        },
        "local_text_metadata_clues": text_clues,
        "local_fits_header_records": fits_rows,
        "local_fits_header_interval_candidates": header_intervals,
        "actual_exposure_overlap": {
            "status": "NOT_YET_COMPUTED_UNTIL_TIMESTAMP_SEMANTICS_SUPPORTED",
            "reason": (
                "DASCH expdate semantics and the exact POSS discovery exposure "
                "interval must be established from local metadata/header/source "
                "semantics before calculating overlap."
            ),
        },
    }
    OUT_JSON.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8"
    )

    with OUT_CSV.open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow([
            "strict_rank", "historical_recurrence_evidence_state",
            "dasch_plate_id", "dasch_expdate", "dasch_exptime_min",
            "dasch_centerdist", "dasch_edgedist",
        ])
        for r in EXPECTED:
            w.writerow([
                r, hist[r], d0["plate_id"], d0["expdate"], d0["exptime_min"],
                pair[r]["centerdist"], pair[r]["edgedist"],
            ])

    md = []
    md.append("# ORDER 01 — Discovery Exposure / Overlap Audit v028j")
    md.append("")
    md.append("## Guards")
    md.append("")
    md.append("- No network access.")
    md.append("- No science pixels read.")
    md.append("- No detector rerun.")
    md.append("- No candidate promoted or deleted.")
    md.append("- FITS headers may be inspected; FITS data arrays are not accessed.")
    md.append("")
    md.append("## Historical recurrence evidence freeze")
    md.append("")
    for r in EXPECTED:
        md.append(f"- #{r}: `{hist[r]}`")
    md.append("")
    md.append(
        "**Summary:** no clean independent historical recurrence observation "
        "currently survives among the frozen six."
    )
    md.append("")
    md.append("## DASCH discovery pair")
    md.append("")
    md.append(f"- Plate: `{d0['plate_id']}`")
    md.append(f"- Recorded `expdate`: `{d0['expdate']}`")
    md.append(f"- Exposure duration: `{d0['exptime_min']} min`")
    md.append(
        "- `expdate` semantics are deliberately left unverified; start/mid/end "
        "interval interpretations are recorded separately in JSON."
    )
    md.append("")
    md.append("## POSS/local metadata search")
    md.append("")
    md.append(f"- Text clue files: **{len(text_clues)}**")
    md.append(f"- FITS/header records: **{len(fits_rows)}**")
    md.append(f"- Parseable DATE-OBS header candidates: **{len(header_intervals)}**")
    md.append("")
    md.append("## Exposure overlap")
    md.append("")
    md.append(
        "`NOT_YET_COMPUTED_UNTIL_TIMESTAMP_SEMANTICS_SUPPORTED` — this is "
        "intentional. Midpoint separation is not substituted for actual "
        "exposure-overlap."
    )
    md.append("")
    OUT_MD.write_text("\n".join(md), encoding="utf-8")

    print("Outputs:")
    print(f"  {OUT_JSON}")
    print(f"  {OUT_CSV}")
    print(f"  {OUT_MD}")
    print()
    print("No external query was made by this script.")
    print("No science pixel was read.")
    print("No detector was rerun.")
    print("No candidate was promoted or deleted.")
    print("Actual exposure overlap was not guessed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
