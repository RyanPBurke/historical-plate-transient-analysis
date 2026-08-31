from __future__ import annotations

from pathlib import Path
import csv
import json
import re

ROOT = Path.cwd()
PAIR_MAP = ROOT / "research" / "SUB5_V028_POSS_PAIR_EXECUTION_MAP_2026-08-21.csv"

OUT = (
    ROOT / "results" / "order61_native_full_v028"
    / "order61_closeout_next_full_inside_selection_v028.json"
)

# Frozen geometry census already completed before Order 61 science execution.
PARTIAL_COMMON_ORDERS = {9, 21, 23, 27, 39, 45, 54, 67}
NO_SAMPLED_INTERSECTION_ORDERS = {3, 48, 66, 71}
ALREADY_WHOLE_NATIVE_COMPLETE = {61}

NEGATIVE_AVAILABILITY_TERMS = (
    "catalogue-identified pixels unavailable",
    "pixel unavailable",
    "pixels unavailable",
    "source unavailable",
    "unavailable",
    "blocked",
)

ORDER_FIELD_CANDIDATES = (
    "canonical_order",
    "canonical_rank",
    "order",
    "rank",
    "pair_order",
    "canonical_pair_order",
)


def read_csv(path):
    with path.open(newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def norm(s):
    return re.sub(r"[^a-z0-9]+", "_", str(s).strip().lower()).strip("_")


def find_order_field(rows):
    if not rows:
        raise RuntimeError("empty pair map")
    fields = list(rows[0].keys())
    norm_to_raw = {norm(f): f for f in fields}

    for cand in ORDER_FIELD_CANDIDATES:
        if cand in norm_to_raw:
            raw = norm_to_raw[cand]
            vals = []
            ok = True
            for r in rows:
                try:
                    vals.append(int(float(str(r[raw]).strip())))
                except Exception:
                    ok = False
                    break
            if ok and len(vals) == len(set(vals)) and all(1 <= x <= 74 for x in vals):
                return raw

    # Conservative fallback: find a unique integer column whose values all
    # fall inside the canonical 1..74 denominator.
    viable = []
    for f in fields:
        vals = []
        ok = True
        for r in rows:
            try:
                x = int(float(str(r[f]).strip()))
            except Exception:
                ok = False
                break
            vals.append(x)
        if ok and len(vals) == len(set(vals)) and all(1 <= x <= 74 for x in vals):
            viable.append(f)

    if len(viable) != 1:
        raise RuntimeError(
            "Could not uniquely identify canonical-order field. "
            f"Candidate numeric columns: {viable}; fields={fields}"
        )
    return viable[0]


def row_text(row):
    return " | ".join(str(v).strip().lower() for v in row.values() if v is not None)


def availability_state(row):
    txt = row_text(row)

    hits = [term for term in NEGATIVE_AVAILABILITY_TERMS if term in txt]
    if hits:
        return "BLOCKED_OR_UNAVAILABLE", hits

    # The execution map was generated after native-source reconciliation;
    # absence of an explicit negative state is not itself claimed as a proof
    # that pixels are ready. We therefore call it "no explicit block".
    return "NO_EXPLICIT_BLOCK_IN_PAIR_MAP", []


def geometry_state(order):
    if order in PARTIAL_COMMON_ORDERS:
        return "PARTIAL_COMMON_FOOTPRINT"
    if order in NO_SAMPLED_INTERSECTION_ORDERS:
        return "NO_SAMPLED_INTERSECTION_REQUIRES_EXACT_EDGE_CHECK"
    return "FULL_POSS_FOOTPRINT_INSIDE_DASCH"


def concise_nonempty(row):
    out = {}
    for k, v in row.items():
        s = "" if v is None else str(v).strip()
        if s:
            out[k] = s
    return out


def main():
    print("=" * 108)
    print("<=5-MIN POSS COHORT — POST-ORDER61 NEXT FULL-INSIDE SELECTION PREFLIGHT v028")
    print("=" * 108)
    print(
        "Read-only selection from the frozen 47-row POSS execution map plus the "
        "completed geometry census. No detector, pixels, WCS, or candidate logic."
    )
    print()

    if not PAIR_MAP.is_file():
        raise RuntimeError(f"Missing frozen pair execution map: {PAIR_MAP}")

    rows = read_csv(PAIR_MAP)
    if len(rows) != 47:
        raise RuntimeError(f"REFUSING: expected 47 POSS rows, got {len(rows)}")

    order_field = find_order_field(rows)

    parsed = []
    seen = set()
    for r in rows:
        order = int(float(str(r[order_field]).strip()))
        if order in seen:
            raise RuntimeError(f"duplicate canonical order {order}")
        seen.add(order)

        avail, reasons = availability_state(r)
        geom = geometry_state(order)

        parsed.append(
            {
                "canonical_order": order,
                "geometry_state": geom,
                "availability_state": avail,
                "availability_reason_terms": reasons,
                "already_whole_native_complete": order in ALREADY_WHOLE_NATIVE_COMPLETE,
                "row": concise_nonempty(r),
            }
        )

    full = [
        x for x in parsed
        if x["geometry_state"] == "FULL_POSS_FOOTPRINT_INSIDE_DASCH"
    ]
    readyish = [
        x for x in full
        if x["canonical_order"] not in ALREADY_WHOLE_NATIVE_COMPLETE
        and x["availability_state"] == "NO_EXPLICIT_BLOCK_IN_PAIR_MAP"
    ]
    readyish.sort(key=lambda x: x["canonical_order"])

    blocked = [
        x for x in full
        if x["availability_state"] == "BLOCKED_OR_UNAVAILABLE"
    ]
    blocked.sort(key=lambda x: x["canonical_order"])

    if not readyish:
        raise RuntimeError(
            "No post-Order61 full-inside row without an explicit block was found"
        )

    nxt = readyish[0]

    print(f"Pair map: {PAIR_MAP}")
    print(f"Rows: {len(rows)}")
    print(f"Canonical-order field: {order_field!r}")
    print(
        "Frozen geometry census: "
        f"full={len(full)}, partial={len(PARTIAL_COMMON_ORDERS)}, "
        f"no-sampled-intersection={len(NO_SAMPLED_INTERSECTION_ORDERS)}"
    )
    print(f"Already whole-native complete: {sorted(ALREADY_WHOLE_NATIVE_COMPLETE)}")
    print()

    if blocked:
        print("FULL-INSIDE ROWS WITH EXPLICIT PAIR-MAP BLOCK/UNAVAILABLE TEXT")
        print("-" * 108)
        for x in blocked:
            print(
                f"  order {x['canonical_order']:02d}: "
                f"{', '.join(x['availability_reason_terms'])}"
            )
        print()

    print("NEXT FULL-INSIDE SELECTION")
    print("-" * 108)
    print(f"canonical order: {nxt['canonical_order']}")
    print(f"geometry:        {nxt['geometry_state']}")
    print(f"availability:    {nxt['availability_state']}")
    print("Frozen pair-map row:")
    for k, v in nxt["row"].items():
        print(f"  {k}: {v}")

    print()
    print("NEXT TEN FULL-INSIDE / NO-EXPLICIT-BLOCK ORDERS")
    print("-" * 108)
    for x in readyish[:10]:
        print(f"  {x['canonical_order']:02d}")

    result = {
        "status": "COMPLETE",
        "analysis_kind": "sub5_poss_post_order61_next_full_inside_selection_v028",
        "pair_map": str(PAIR_MAP),
        "pair_map_rows": len(rows),
        "canonical_order_field": order_field,
        "frozen_geometry_census": {
            "partial_orders": sorted(PARTIAL_COMMON_ORDERS),
            "no_sampled_intersection_orders": sorted(NO_SAMPLED_INTERSECTION_ORDERS),
            "full_inside_count": len(full),
        },
        "already_whole_native_complete": sorted(ALREADY_WHOLE_NATIVE_COMPLETE),
        "selection_rule": (
            "ascending canonical order among frozen POSS rows classified by the "
            "completed geometry census as full POSS footprint inside DASCH, excluding "
            "already completed whole-native orders and rows containing explicit "
            "blocked/unavailable text in the frozen execution map"
        ),
        "selection_does_not_use_candidate_outcomes": True,
        "selected_next": nxt,
        "next_ten": readyish[:10],
        "blocked_full_inside": blocked,
        "detector_rerun": False,
        "science_pixels_read": False,
        "candidate_deleted": False,
        "candidate_promoted": False,
        "next_stage": (
            "Run a read-only order-specific geometry/native-source preflight for the "
            "selected row, then generalize the Order61 whole-native worker without "
            "altering the frozen detector or tile policy."
        ),
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    tmp = OUT.with_suffix(OUT.suffix + ".tmp")
    tmp.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(OUT)

    print()
    print("=" * 108)
    print("NEXT FULL-INSIDE SELECTION PREFLIGHT COMPLETE")
    print("=" * 108)
    print("Output:", OUT)
    print()
    print("No detector was rerun.")
    print("No science image pixel was read.")
    print("No candidate was deleted or promoted.")


if __name__ == "__main__":
    main()
