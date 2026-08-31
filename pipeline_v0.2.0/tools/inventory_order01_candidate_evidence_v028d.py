#!/usr/bin/env python3
"""
ORDER 01 — candidate-specific evidence inventory v028d

Purpose
-------
Build a read-only inventory of already-completed Order 01 evidence for the
post-1024 Branch-A survivors. This script does NOT:
  * access the network
  * read science pixels / FITS images
  * rerun a detector
  * promote, delete, or otherwise mutate candidate state

It only scans CSV/JSON products already present beneath:
    results/order01_native_full_v028

Expected frozen active survivor set:
    10, 24, 25, 26, 29, 30
"""

from __future__ import annotations

import csv
import json
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "results" / "order01_native_full_v028"
FREEZE = RESULTS / "order01_post1024_adjudication_v028c.json"

OUT_JSON = RESULTS / "order01_candidate_evidence_inventory_v028d.json"
OUT_CSV = RESULTS / "order01_candidate_evidence_inventory_v028d.csv"
OUT_MD = RESULTS / "ORDER01_CANDIDATE_EVIDENCE_INVENTORY_V028D.md"

EXPECTED_ACTIVE = [10, 24, 25, 26, 29, 30]

RANK_KEYS = (
    "strict_rank",
    "rank",
    "candidate_rank",
    "strict rank",
    "candidate rank",
)

# Intentionally ignore our own outputs and obvious large/raw/image products.
IGNORE_NAMES = {
    OUT_JSON.name.lower(),
    OUT_CSV.name.lower(),
    OUT_MD.name.lower(),
}
MAX_FILE_BYTES = 100 * 1024 * 1024


def norm_key(s: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(s).strip().lower()).strip("_")


def coerce_rank(v: Any) -> int | None:
    if v is None:
        return None
    if isinstance(v, bool):
        return None
    if isinstance(v, int):
        return v
    if isinstance(v, float) and v.is_integer():
        return int(v)
    s = str(v).strip()
    m = re.fullmatch(r"#?\s*(\d+)", s)
    if m:
        return int(m.group(1))
    return None


def rank_from_mapping(d: dict[str, Any]) -> tuple[int | None, str | None]:
    normalized = {norm_key(k): k for k in d}
    for candidate_key in RANK_KEYS:
        nk = norm_key(candidate_key)
        if nk in normalized:
            original = normalized[nk]
            r = coerce_rank(d.get(original))
            if r is not None:
                return r, str(original)
    return None, None


def compact_mapping(d: dict[str, Any], max_fields: int = 80) -> dict[str, Any]:
    """
    Preserve scalar evidence fields; summarize nested structures so the inventory
    remains inspectable and cannot balloon from embedded arrays.
    """
    out: dict[str, Any] = {}
    for i, (k, v) in enumerate(d.items()):
        if i >= max_fields:
            out["__truncated_fields__"] = len(d) - max_fields
            break
        if v is None or isinstance(v, (str, int, float, bool)):
            s = v
            if isinstance(s, str) and len(s) > 1000:
                s = s[:1000] + "...<truncated>"
            out[str(k)] = s
        elif isinstance(v, list):
            out[str(k)] = f"<list:{len(v)}>"
        elif isinstance(v, dict):
            out[str(k)] = f"<dict:{len(v)}>"
        else:
            out[str(k)] = f"<{type(v).__name__}>"
    return out


def walk_json(obj: Any, path: str = "$") -> Iterable[tuple[str, dict[str, Any]]]:
    if isinstance(obj, dict):
        yield path, obj
        for k, v in obj.items():
            if isinstance(v, (dict, list)):
                yield from walk_json(v, f"{path}.{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            if isinstance(v, (dict, list)):
                yield from walk_json(v, f"{path}[{i}]")


def extract_active_from_freeze(data: Any) -> list[int] | None:
    """
    Find a list whose key semantically resembles the active unresolved Branch-A
    ranks. We refuse to silently accept a different survivor set.
    """
    if not isinstance(data, dict):
        return None

    preferred = []
    for k, v in data.items():
        nk = norm_key(k)
        if isinstance(v, list) and all(coerce_rank(x) is not None for x in v):
            score = 0
            for token in ("active", "unresolved", "branch", "rank", "surviv"):
                if token in nk:
                    score += 1
            if score:
                preferred.append((score, k, [coerce_rank(x) for x in v]))

    if preferred:
        preferred.sort(reverse=True, key=lambda x: x[0])
        return [int(x) for x in preferred[0][2] if x is not None]

    # Search one level deeper as a conservative fallback.
    for _, d in walk_json(data):
        if d is data:
            continue
        got = extract_active_from_freeze(d)
        if got:
            return got
    return None


def scan_csv(path: Path, active: set[int]) -> list[dict[str, Any]]:
    hits: list[dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8-sig", newline="", errors="replace") as f:
            reader = csv.DictReader(f)
            if not reader.fieldnames:
                return hits

            normalized = {norm_key(k): k for k in reader.fieldnames}
            rank_col = None
            for rk in RANK_KEYS:
                if norm_key(rk) in normalized:
                    rank_col = normalized[norm_key(rk)]
                    break
            if rank_col is None:
                return hits

            for rownum, row in enumerate(reader, start=2):
                r = coerce_rank(row.get(rank_col))
                if r in active:
                    hits.append({
                        "rank": r,
                        "source_file": str(path.relative_to(ROOT)),
                        "source_type": "csv",
                        "location": f"row {rownum}",
                        "rank_field": rank_col,
                        "evidence": compact_mapping(row),
                    })
    except Exception as e:
        hits.append({
            "rank": None,
            "source_file": str(path.relative_to(ROOT)),
            "source_type": "csv_error",
            "location": "",
            "rank_field": "",
            "evidence": {"error": repr(e)},
        })
    return hits


def scan_json(path: Path, active: set[int]) -> list[dict[str, Any]]:
    hits: list[dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8", errors="replace") as f:
            data = json.load(f)

        seen = set()
        for jpath, d in walk_json(data):
            r, rank_field = rank_from_mapping(d)
            if r in active:
                # Avoid duplicate identical mapping locations if recursive structures
                # expose the same object through unusual JSON construction.
                key = (r, jpath)
                if key in seen:
                    continue
                seen.add(key)
                hits.append({
                    "rank": r,
                    "source_file": str(path.relative_to(ROOT)),
                    "source_type": "json",
                    "location": jpath,
                    "rank_field": rank_field,
                    "evidence": compact_mapping(d),
                })
    except Exception as e:
        hits.append({
            "rank": None,
            "source_file": str(path.relative_to(ROOT)),
            "source_type": "json_error",
            "location": "",
            "rank_field": "",
            "evidence": {"error": repr(e)},
        })
    return hits


def main() -> int:
    print("=" * 104)
    print("ORDER 01 — CANDIDATE-SPECIFIC EVIDENCE INVENTORY v028d")
    print("=" * 104)

    if not RESULTS.exists():
        print(f"FAIL: results directory not found: {RESULTS}")
        return 2

    if not FREEZE.exists():
        print(f"FAIL: required freeze not found: {FREEZE}")
        return 2

    with FREEZE.open("r", encoding="utf-8", errors="replace") as f:
        freeze_data = json.load(f)

    freeze_active = extract_active_from_freeze(freeze_data)
    if freeze_active is None:
        print("WARN: could not automatically recover active ranks from freeze JSON.")
        print(f"      Enforcing expected frozen set: {EXPECTED_ACTIVE}")
        active_list = EXPECTED_ACTIVE
    else:
        active_list = sorted(set(int(x) for x in freeze_active))
        if active_list != EXPECTED_ACTIVE:
            print("FAIL: frozen survivor set does not match the expected v028c set.")
            print(f"      freeze says:  {active_list}")
            print(f"      expected:     {EXPECTED_ACTIVE}")
            print("No inventory outputs were written.")
            return 3

    active = set(active_list)
    print(f"Frozen active ranks: {active_list}")
    print("Guards: no network; no pixels; no detector; no candidate state mutation")

    products = []
    skipped_large = []
    for p in sorted(RESULTS.rglob("*")):
        if not p.is_file():
            continue
        if p.name.lower() in IGNORE_NAMES:
            continue
        if p.suffix.lower() not in {".csv", ".json"}:
            continue
        try:
            size = p.stat().st_size
        except OSError:
            continue
        if size > MAX_FILE_BYTES:
            skipped_large.append({
                "file": str(p.relative_to(ROOT)),
                "bytes": size,
            })
            continue
        products.append(p)

    print(f"Eligible completed CSV/JSON products discovered: {len(products)}")
    if skipped_large:
        print(f"Skipped >100 MiB products: {len(skipped_large)}")

    hits: list[dict[str, Any]] = []
    for idx, p in enumerate(products, start=1):
        if p.suffix.lower() == ".csv":
            hits.extend(scan_csv(p, active))
        else:
            hits.extend(scan_json(p, active))

    # Keep only genuine evidence rows in candidate counts; errors are retained in JSON.
    candidate_hits = [h for h in hits if h.get("rank") in active]
    errors = [h for h in hits if h.get("rank") is None]

    by_rank: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for h in candidate_hits:
        by_rank[int(h["rank"])].append(h)

    payload = {
        "stage": "ORDER01_CANDIDATE_SPECIFIC_EVIDENCE_INVENTORY_V028D",
        "input_freeze": str(FREEZE.relative_to(ROOT)),
        "frozen_active_ranks": active_list,
        "guards": {
            "network_access": False,
            "science_pixels_read": False,
            "detector_rerun": False,
            "candidate_promotion": False,
            "candidate_deletion": False,
        },
        "files_scanned": [str(p.relative_to(ROOT)) for p in products],
        "skipped_large_files": skipped_large,
        "errors": errors,
        "candidate_evidence": {
            str(r): by_rank.get(r, []) for r in active_list
        },
    }

    with OUT_JSON.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)

    with OUT_CSV.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow([
            "strict_rank", "source_file", "source_type",
            "location", "rank_field", "evidence_json"
        ])
        for r in active_list:
            for h in by_rank.get(r, []):
                w.writerow([
                    r,
                    h["source_file"],
                    h["source_type"],
                    h["location"],
                    h["rank_field"],
                    json.dumps(h["evidence"], ensure_ascii=False, sort_keys=True),
                ])

    md = []
    md.append("# ORDER 01 — Candidate-Specific Evidence Inventory v028d")
    md.append("")
    md.append("Read-only assembly of completed evidence for the frozen post-1024 Branch-A survivors.")
    md.append("")
    md.append("## Guards")
    md.append("")
    md.append("- No network access.")
    md.append("- No science pixels read.")
    md.append("- No detector rerun.")
    md.append("- No candidate promoted or deleted.")
    md.append("")
    md.append(f"Frozen active ranks: **{', '.join('#'+str(r) for r in active_list)}**")
    md.append("")
    md.append("## Evidence counts")
    md.append("")
    md.append("| strict rank | matched evidence records | distinct source files |")
    md.append("|---:|---:|---:|")
    for r in active_list:
        rows = by_rank.get(r, [])
        files = sorted({h["source_file"] for h in rows})
        md.append(f"| #{r} | {len(rows)} | {len(files)} |")
    md.append("")
    md.append("## Per-candidate source inventory")
    md.append("")
    for r in active_list:
        md.append(f"### Strict #{r}")
        rows = by_rank.get(r, [])
        if not rows:
            md.append("")
            md.append("_No rank-addressable completed evidence record discovered._")
            md.append("")
            continue
        grouped: dict[str, int] = defaultdict(int)
        for h in rows:
            grouped[h["source_file"]] += 1
        md.append("")
        for fn, n in sorted(grouped.items()):
            md.append(f"- `{fn}` — {n} matched record(s)")
        md.append("")

    if skipped_large:
        md.append("## Skipped large products")
        md.append("")
        for x in skipped_large:
            md.append(f"- `{x['file']}` — {x['bytes']} bytes")
        md.append("")

    if errors:
        md.append("## Parse warnings")
        md.append("")
        for e in errors:
            md.append(f"- `{e['source_file']}` — {e['evidence'].get('error','unknown error')}")
        md.append("")

    OUT_MD.write_text("\n".join(md), encoding="utf-8")

    print()
    print("Per-candidate evidence inventory:")
    for r in active_list:
        rows = by_rank.get(r, [])
        files = sorted({h["source_file"] for h in rows})
        print(f"  strict #{r:>2}: {len(rows):>4} records across {len(files):>3} source files")

    if errors:
        print(f"\nParse warnings: {len(errors)} (retained in JSON/MD)")
    if skipped_large:
        print(f"Large-file skips: {len(skipped_large)} (retained in JSON/MD)")

    print("\nOutputs:")
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
