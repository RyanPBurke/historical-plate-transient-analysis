from __future__ import annotations

from pathlib import Path
import csv
import json
import re

ROOT = Path.cwd()

NATIVE_MAP = ROOT / "research" / "POSS1_V028_NATIVE_DSS_SOURCE_MAP_2026-08-21.csv"
PAIR_MAP = ROOT / "research" / "SUB5_V028_POSS_PAIR_EXECUTION_MAP_2026-08-21.csv"

CANDIDATE_SOURCES = [
    ROOT / "tools" / "run_order61_whole_native_v028.py",
    ROOT / "tools" / "prepare_native_dss_extractor_v028.py",
    ROOT / "tools" / "validate_native_dss_xe520_control_v028.py",
    ROOT / "src" / "transient_pipeline" / "poss1_skyview.py",
    ROOT / "src" / "transient_pipeline" / "poss1.py",
]

OUT = (
    ROOT / "results" / "order01_native_preflight_v028"
    / "order01_native_source_resolution_diagnostic_v028.json"
)

ORDER = 1
EXPECTED_POSS = "POSS-I:413:E:rec297"
EXPECTED_REGION = "XE296"

SEARCH_PATTERNS = [
    "native",
    "DSSImage",
    "raw_plate_directory",
    "descriptor",
    ".hhh",
    "FilePrefix",
    "region",
    "XE520",
    "ai44092",
    "POSS-I:875:E:rec521",
    "JAR_SHA",
    "findjar",
]


def read_csv(path):
    with path.open(newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def selected_lines(path, patterns, context=3):
    if not path.is_file():
        return {
            "path": str(path),
            "exists": False,
            "matches": [],
        }

    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    hit_lines = set()

    for i, line in enumerate(lines):
        if any(p.lower() in line.lower() for p in patterns):
            for j in range(max(0, i-context), min(len(lines), i+context+1)):
                hit_lines.add(j)

    blocks = []
    if hit_lines:
        ordered = sorted(hit_lines)
        start = prev = ordered[0]
        for idx in ordered[1:]:
            if idx == prev + 1:
                prev = idx
                continue
            blocks.append((start, prev))
            start = prev = idx
        blocks.append((start, prev))

    rendered = []
    for a, b in blocks:
        rendered.append(
            {
                "start_line": a+1,
                "end_line": b+1,
                "lines": [
                    {"line": j+1, "text": lines[j]}
                    for j in range(a, b+1)
                ],
            }
        )

    return {
        "path": str(path),
        "exists": True,
        "line_count": len(lines),
        "matches": rendered,
    }


def main():
    print("="*110)
    print("ORDER 01 — NATIVE SOURCE RESOLUTION DIAGNOSTIC v028")
    print("="*110)
    print(
        "Read-only. Determine the actual scope of the frozen native-source map and "
        "recover the successful native-source resolution contract from existing code."
    )
    print("No detector. No science pixels. No network.")
    print()

    if not NATIVE_MAP.is_file():
        raise RuntimeError(f"Missing native map: {NATIVE_MAP}")
    if not PAIR_MAP.is_file():
        raise RuntimeError(f"Missing pair map: {PAIR_MAP}")

    nrows = read_csv(NATIVE_MAP)
    prows = read_csv(PAIR_MAP)

    if not nrows:
        raise RuntimeError("Native source map is empty")

    print("[1/3] Native-source map census")
    print("-"*110)
    print(f"path: {NATIVE_MAP}")
    print(f"rows: {len(nrows)}")
    print(f"columns ({len(nrows[0])}):")
    for k in nrows[0].keys():
        print(f"  {k}")

    print()
    print("all native-map rows (nonempty fields):")
    for i, r in enumerate(nrows, 1):
        vals = {k: str(v).strip() for k, v in r.items() if v is not None and str(v).strip()}
        print(f"  ROW {i:02d}: {vals}")

    text = "\n".join(
        " | ".join(str(v) for v in r.values() if v is not None)
        for r in nrows
    ).lower()

    exact_exposure_present = EXPECTED_POSS.lower() in text
    exact_region_present = EXPECTED_REGION.lower() in text

    print()
    print(f"{EXPECTED_POSS} present anywhere: {exact_exposure_present}")
    print(f"{EXPECTED_REGION} present anywhere: {exact_region_present}")

    if len(nrows) == 10:
        scope_inference = (
            "TEN_ROW_SPECIAL_PURPOSE_MAP_CONSISTENT_WITH_REPAIRED_NATIVE_GAPS"
        )
    else:
        scope_inference = "MAP_SCOPE_REQUIRES_CODE_CONTEXT"

    print(f"scope inference: {scope_inference}")
    print()

    print("[2/3] Frozen pair-map Order-1 row")
    print("-"*110)

    o1 = []
    for r in prows:
        try:
            if int(float(str(r.get("canonical_order", "")).strip())) == ORDER:
                o1.append(r)
        except Exception:
            pass

    if len(o1) != 1:
        raise RuntimeError(f"Expected one Order-1 row; got {len(o1)}")

    print({k: v for k, v in o1[0].items() if v is not None and str(v).strip()})
    print()

    print("[3/3] Existing native-resolution code context")
    print("-"*110)

    source_audit = []
    for path in CANDIDATE_SOURCES:
        audit = selected_lines(path, SEARCH_PATTERNS, context=4)
        source_audit.append(audit)

        print()
        print(path)
        if not audit["exists"]:
            print("  MISSING")
            continue

        print(f"  source lines: {audit['line_count']}")
        for block in audit["matches"]:
            print(f"  --- L{block['start_line']}-L{block['end_line']} ---")
            for item in block["lines"]:
                print(f"  {item['line']:5d}: {item['text']}")

    result = {
        "status": "COMPLETE",
        "analysis_kind": "order01_native_source_resolution_diagnostic_v028",
        "native_map": {
            "path": str(NATIVE_MAP),
            "row_count": len(nrows),
            "columns": list(nrows[0].keys()),
            "rows": nrows,
            "expected_exposure_present": exact_exposure_present,
            "expected_region_present": exact_region_present,
            "scope_inference": scope_inference,
        },
        "order01_pair_map_row": o1[0],
        "source_code_audit": source_audit,
        "detector_rerun": False,
        "science_image_pixels_read": False,
        "network_access": False,
        "next_stage": (
            "Use the recovered existing-code contract to resolve XE296 exactly. "
            "Do not substitute a neighbouring DSS region and do not change the frozen detector."
        ),
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    tmp = OUT.with_suffix(OUT.suffix + ".tmp")
    tmp.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    tmp.replace(OUT)

    print()
    print("="*110)
    print("NATIVE SOURCE RESOLUTION DIAGNOSTIC COMPLETE")
    print("="*110)
    print("Output:", OUT)
    print()
    print("No detector was rerun.")
    print("No science image pixel was read.")
    print("No network request was made.")


if __name__ == "__main__":
    main()
