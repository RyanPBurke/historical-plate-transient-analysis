#!/usr/bin/env python3
"""
ORDER 01 — candidate evidence reduction v028e

Consumes:
    results/order01_native_full_v028/order01_candidate_evidence_inventory_v028d.json

Purpose:
    Reduce the broad v028d rank-addressable inventory into a compact,
    inspectable dossier suitable for the next adjudication pass.

This stage DOES NOT:
  * access the network
  * read science pixels / FITS
  * rerun any detector
  * promote/delete candidates
  * reinterpret repeated control/history rows as independent evidence

Method:
  1. Profile every discovered source file across the six frozen candidates.
  2. Separate low-volume/direct-looking sources from repeated/high-volume sources.
  3. Preserve full evidence rows from low-volume sources.
  4. Preserve only field/cardinality summaries from high-volume sources.
  5. Emit a console source matrix so the next stage can target the genuinely
     candidate-specific completed products.

No scientific conclusion is made here.
"""

from __future__ import annotations

import csv
import json
import math
import statistics
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "results" / "order01_native_full_v028"

INVENTORY = RESULTS / "order01_candidate_evidence_inventory_v028d.json"
OUT_JSON = RESULTS / "order01_candidate_evidence_reduced_v028e.json"
OUT_CSV = RESULTS / "order01_candidate_source_matrix_v028e.csv"
OUT_MD = RESULTS / "ORDER01_CANDIDATE_EVIDENCE_REDUCED_V028E.md"

EXPECTED_ACTIVE = [10, 24, 25, 26, 29, 30]

# A source with at most this many rank-addressable rows PER candidate is small
# enough to preserve verbatim in the compact dossier.
DIRECT_MAX_PER_CANDIDATE = 20

# Limit distinct-value examples per field in high-volume source summaries.
MAX_VALUE_EXAMPLES = 8


def sval(v: Any) -> str:
    if v is None:
        return "<null>"
    if isinstance(v, (dict, list)):
        try:
            return json.dumps(v, sort_keys=True, ensure_ascii=False)
        except Exception:
            return repr(v)
    return str(v)


def safe_median(values):
    return statistics.median(values) if values else 0


def summarize_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """
    Summarize evidence payloads without treating repeated rows as independent
    scientific support.
    """
    field_presence = Counter()
    field_values: dict[str, Counter] = defaultdict(Counter)

    for row in rows:
        ev = row.get("evidence") or {}
        if not isinstance(ev, dict):
            continue
        for k, v in ev.items():
            field_presence[k] += 1
            field_values[k][sval(v)] += 1

    fields = {}
    for k in sorted(field_presence):
        vc = field_values[k]
        examples = [
            {"value": value, "count": count}
            for value, count in vc.most_common(MAX_VALUE_EXAMPLES)
        ]
        fields[k] = {
            "present_in_rows": field_presence[k],
            "distinct_values": len(vc),
            "top_values": examples,
        }

    return {
        "row_count": len(rows),
        "field_count": len(fields),
        "fields": fields,
    }


def source_name_hint(name: str) -> str:
    n = name.lower()
    hints = []
    for token in (
        "adjud", "morph", "inject", "recover", "histor", "recurr",
        "static", "catalog", "peer", "candidate", "summary", "freeze",
        "astrom", "photom", "plate", "control", "blind", "rank"
    ):
        if token in n:
            hints.append(token)
    return ",".join(hints)


def main() -> int:
    print("=" * 108)
    print("ORDER 01 — CANDIDATE EVIDENCE REDUCTION v028e")
    print("=" * 108)

    if not INVENTORY.exists():
        print(f"FAIL: missing v028d inventory: {INVENTORY}")
        return 2

    with INVENTORY.open("r", encoding="utf-8", errors="replace") as f:
        inv = json.load(f)

    active = inv.get("frozen_active_ranks")
    if active != EXPECTED_ACTIVE:
        print("FAIL: v028d frozen survivor set mismatch.")
        print(f"      inventory: {active}")
        print(f"      expected:  {EXPECTED_ACTIVE}")
        return 3

    candidate_evidence = inv.get("candidate_evidence") or {}
    if not isinstance(candidate_evidence, dict):
        print("FAIL: malformed candidate_evidence in v028d.")
        return 4

    # Build source -> rank -> rows.
    source_rank_rows: dict[str, dict[int, list[dict[str, Any]]]] = defaultdict(
        lambda: defaultdict(list)
    )

    for r in EXPECTED_ACTIVE:
        rows = candidate_evidence.get(str(r), [])
        if not isinstance(rows, list):
            continue
        for row in rows:
            sf = row.get("source_file")
            if not sf:
                continue
            source_rank_rows[str(sf)][r].append(row)

    profiles = []
    direct_sources = []
    repeated_sources = []

    for sf in sorted(source_rank_rows):
        counts = [len(source_rank_rows[sf].get(r, [])) for r in EXPECTED_ACTIVE]
        nonzero = [c for c in counts if c > 0]
        max_count = max(counts) if counts else 0
        min_count = min(counts) if counts else 0
        total = sum(counts)
        uniform = len(set(counts)) == 1
        present_all = all(c > 0 for c in counts)
        direct = max_count <= DIRECT_MAX_PER_CANDIDATE

        p = {
            "source_file": sf,
            "hint": source_name_hint(sf),
            "counts": {str(r): counts[i] for i, r in enumerate(EXPECTED_ACTIVE)},
            "total_rows": total,
            "min_per_candidate": min_count,
            "max_per_candidate": max_count,
            "median_per_candidate": safe_median(counts),
            "uniform_counts": uniform,
            "present_for_all_candidates": present_all,
            "classification": "LOW_VOLUME_PRESERVE" if direct else "REPEATED_AGGREGATE_ONLY",
        }
        profiles.append(p)
        (direct_sources if direct else repeated_sources).append(sf)

    # Construct compact dossier.
    dossier = {}
    for r in EXPECTED_ACTIVE:
        direct_records = []
        repeated_summaries = []

        for sf in direct_sources:
            rows = source_rank_rows[sf].get(r, [])
            for row in rows:
                direct_records.append({
                    "source_file": sf,
                    "source_type": row.get("source_type"),
                    "location": row.get("location"),
                    "rank_field": row.get("rank_field"),
                    "evidence": row.get("evidence"),
                })

        for sf in repeated_sources:
            rows = source_rank_rows[sf].get(r, [])
            if not rows:
                continue
            repeated_summaries.append({
                "source_file": sf,
                "summary": summarize_rows(rows),
            })

        dossier[str(r)] = {
            "low_volume_records": direct_records,
            "repeated_source_summaries": repeated_summaries,
        }

    payload = {
        "stage": "ORDER01_CANDIDATE_EVIDENCE_REDUCTION_V028E",
        "input_inventory": str(INVENTORY.relative_to(ROOT)),
        "frozen_active_ranks": EXPECTED_ACTIVE,
        "thresholds": {
            "direct_max_rows_per_candidate": DIRECT_MAX_PER_CANDIDATE,
            "max_value_examples_per_field": MAX_VALUE_EXAMPLES,
        },
        "guards": {
            "network_access": False,
            "science_pixels_read": False,
            "detector_rerun": False,
            "candidate_promotion": False,
            "candidate_deletion": False,
            "scientific_adjudication_performed": False,
        },
        "source_profiles": profiles,
        "low_volume_sources": direct_sources,
        "repeated_sources": repeated_sources,
        "candidate_dossier": dossier,
    }

    OUT_JSON.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False),
        encoding="utf-8"
    )

    with OUT_CSV.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow([
            "source_file",
            "hint",
            *[f"rank_{r}_rows" for r in EXPECTED_ACTIVE],
            "total_rows",
            "min_per_candidate",
            "max_per_candidate",
            "median_per_candidate",
            "uniform_counts",
            "present_for_all_candidates",
            "classification",
        ])
        for p in profiles:
            w.writerow([
                p["source_file"],
                p["hint"],
                *[p["counts"][str(r)] for r in EXPECTED_ACTIVE],
                p["total_rows"],
                p["min_per_candidate"],
                p["max_per_candidate"],
                p["median_per_candidate"],
                p["uniform_counts"],
                p["present_for_all_candidates"],
                p["classification"],
            ])

    md = []
    md.append("# ORDER 01 — Candidate Evidence Reduction v028e")
    md.append("")
    md.append(
        "Reduction of the broad v028d inventory into low-volume candidate records "
        "plus aggregate summaries of repeated/high-volume products."
    )
    md.append("")
    md.append("## Guards")
    md.append("")
    md.append("- No network access.")
    md.append("- No science pixels read.")
    md.append("- No detector rerun.")
    md.append("- No candidate promoted or deleted.")
    md.append("- No scientific adjudication performed.")
    md.append("")
    md.append(f"Frozen active ranks: **{', '.join('#'+str(r) for r in EXPECTED_ACTIVE)}**")
    md.append("")
    md.append("## Source classification")
    md.append("")
    md.append(
        f"Low-volume preservation threshold: **≤{DIRECT_MAX_PER_CANDIDATE} "
        "rank-addressable rows per candidate per source**."
    )
    md.append("")
    md.append(f"- Low-volume sources preserved verbatim: **{len(direct_sources)}**")
    md.append(f"- Repeated/high-volume sources summarized only: **{len(repeated_sources)}**")
    md.append("")
    md.append("| source | hint | #10 | #24 | #25 | #26 | #29 | #30 | class |")
    md.append("|---|---|---:|---:|---:|---:|---:|---:|---|")
    for p in profiles:
        short = p["source_file"].replace("\\", "/")
        md.append(
            f"| `{short}` | {p['hint']} | "
            + " | ".join(str(p["counts"][str(r)]) for r in EXPECTED_ACTIVE)
            + f" | {p['classification']} |"
        )
    md.append("")
    md.append("## Per-candidate compact counts")
    md.append("")
    md.append("| rank | preserved direct rows | repeated source summaries |")
    md.append("|---:|---:|---:|")
    for r in EXPECTED_ACTIVE:
        d = dossier[str(r)]
        md.append(
            f"| #{r} | {len(d['low_volume_records'])} | "
            f"{len(d['repeated_source_summaries'])} |"
        )
    md.append("")
    OUT_MD.write_text("\n".join(md), encoding="utf-8")

    print(f"Source products represented: {len(profiles)}")
    print(f"Low-volume/direct-preserved sources: {len(direct_sources)}")
    print(f"Repeated/high-volume aggregate-only sources: {len(repeated_sources)}")
    print()

    # Console matrix: all sources, sorted from smallest max-per-candidate to largest.
    print("Source matrix (sorted by max rows per candidate):")
    print("-" * 108)
    ordered = sorted(
        profiles,
        key=lambda p: (p["max_per_candidate"], p["total_rows"], p["source_file"])
    )
    for p in ordered:
        counts = "/".join(str(p["counts"][str(r)]) for r in EXPECTED_ACTIVE)
        cls = "DIRECT" if p["classification"] == "LOW_VOLUME_PRESERVE" else "REPEAT"
        hint = f" [{p['hint']}]" if p["hint"] else ""
        print(
            f"{cls:6} max={p['max_per_candidate']:>5} "
            f"counts={counts:<35} {p['source_file']}{hint}"
        )

    print()
    print("Compact dossier:")
    for r in EXPECTED_ACTIVE:
        d = dossier[str(r)]
        print(
            f"  strict #{r:>2}: "
            f"{len(d['low_volume_records']):>4} preserved low-volume row(s), "
            f"{len(d['repeated_source_summaries']):>3} repeated-source summary(ies)"
        )

    print("\nOutputs:")
    print(f"  {OUT_JSON}")
    print(f"  {OUT_CSV}")
    print(f"  {OUT_MD}")
    print()
    print("No external query was made.")
    print("No science pixel was read.")
    print("No detector was rerun.")
    print("No candidate was promoted or deleted.")
    print("No scientific adjudication was performed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
