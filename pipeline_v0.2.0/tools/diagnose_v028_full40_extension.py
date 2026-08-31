from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path
import csv
import hashlib
import math


ROOT = Path.cwd()

QUEUE = ROOT / "research" / "production_sub5_queue_2026-08-20.csv"
CANON = ROOT / "research" / "canonical_sub5_pairs_74.csv"

EXPECTED_QUEUE_SHA = (
    "b044684fef65437a352edd28eafd21d668640bbec50cd0bc95f92e3529d0d77c"
)

EXPECTED_CANON_SHA = (
    "58529e1d4de46f3c49865a89454d1cd488ee23ec920b01250006f2180d2ed99a"
)

MISSING = {
    "POSS-I:1009:O:rec785",
    "POSS-I:1023:O:rec675",
    "POSS-I:1023:O:rec799",
    "POSS-I:305:E:rec637",
    "POSS-I:306:E:rec703",
    "POSS-I:318:E:rec524",
    "POSS-I:606:E:rec348",
    "POSS-I:779:E:rec404",
    "POSS-I:988:O:rec207",
}


def sha256(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def load(path):
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def poss_ids(row):
    return [
        x
        for x in (
            str(row.get("exposure_a") or ""),
            str(row.get("exposure_b") or ""),
        )
        if x.startswith("POSS-I:")
    ]


def maybe_float(value):
    try:
        return float(str(value))
    except Exception:
        return None


if sha256(QUEUE) != EXPECTED_QUEUE_SHA:
    raise SystemExit("REFUSING: production queue SHA changed.")

if sha256(CANON) != EXPECTED_CANON_SHA:
    raise SystemExit("REFUSING: canonical queue SHA changed.")

rows = load(QUEUE)
canon = load(CANON)

if len(rows) != 74 or len(canon) != 74:
    raise SystemExit("REFUSING: queue row count changed.")


print("=" * 100)
print("NINE OMITTED PHYSICAL POSS EXPOSURES — EXACT COHORT LABELS")
print("=" * 100)

found = set()

for row in sorted(rows, key=lambda r: int(float(r["canonical_order"]))):
    ids = set(poss_ids(row))
    hit = ids & MISSING

    if not hit:
        continue

    for pid in sorted(hit):
        found.add(pid)

        print()
        print(pid)
        print("  canonical_order :", row.get("canonical_order"))
        print("  legacy_rank     :", row.get("legacy_rank"))
        print("  publication_cohort:",
              repr(row.get("publication_cohort")))
        print("  production_action  :",
              repr(row.get("production_action")))
        print("  pre_freeze_touched  :",
              repr(row.get("pre_freeze_touched")))
        print("  pre_freeze_reason   :",
              repr(row.get("pre_freeze_reason")))
        print("  saved_status        :",
              repr(row.get("saved_status")))
        print("  saved_notes         :",
              repr(row.get("saved_notes")))
        print("  pair_key            :",
              row.get("pair_key"))

if found != MISSING:
    raise SystemExit(
        f"REFUSING: missing-set mismatch: "
        f"found={sorted(found)} expected={sorted(MISSING)}"
    )


print()
print("=" * 100)
print("PUBLICATION COHORT ACCOUNTING")
print("=" * 100)

row_counts = Counter()
poss_by_cohort = defaultdict(set)

for row in rows:
    cohort = str(row.get("publication_cohort") or "")
    row_counts[cohort] += 1

    for pid in poss_ids(row):
        poss_by_cohort[cohort].add(pid)

for cohort in sorted(row_counts):
    print(
        f"{cohort!r}: "
        f"rows={row_counts[cohort]}, "
        f"unique_POSS={len(poss_by_cohort[cohort])}"
    )

all_poss = set().union(*poss_by_cohort.values())

print()
print("All unique POSS physical exposures:", len(all_poss))

if len(all_poss) != 40:
    raise SystemExit(
        f"REFUSING: expected 40 unique POSS exposures; got {len(all_poss)}"
    )

prospective = poss_by_cohort.get("prospective_production", set())

print(
    "prospective_production unique POSS:",
    len(prospective)
)

print(
    "non-prospective unique POSS:",
    len(all_poss - prospective)
)


print()
print("=" * 100)
print("29 SHARED-FIELD DIFFERENCES — NUMERIC-ROUNDING CLASSIFICATION")
print("=" * 100)

a_by_order = {
    int(float(r["canonical_order"])): r
    for r in rows
}

b_by_order = {
    int(float(r["canonical_order"])): r
    for r in canon
}

common = sorted(set(rows[0]) & set(canon[0]))

numeric_diffs = []
text_diffs = []

for order in range(1, 75):
    a = a_by_order[order]
    b = b_by_order[order]

    for col in common:
        av = str(a.get(col) or "")
        bv = str(b.get(col) or "")

        if av == bv:
            continue

        af = maybe_float(av)
        bf = maybe_float(bv)

        if af is not None and bf is not None:
            numeric_diffs.append({
                "order": order,
                "column": col,
                "a": af,
                "b": bf,
                "abs_delta": abs(af - bf),
            })
        else:
            text_diffs.append({
                "order": order,
                "column": col,
                "production": av,
                "canonical": bv,
            })


print("numeric differing cells:", len(numeric_diffs))
print("non-numeric differing cells:", len(text_diffs))

if text_diffs:
    print()
    print("NON-NUMERIC DIFFERENCES:")
    for d in text_diffs:
        print(
            d["order"],
            d["column"],
            repr(d["production"]),
            "!=",
            repr(d["canonical"]),
        )


by_field = defaultdict(list)

for d in numeric_diffs:
    by_field[d["column"]].append(d["abs_delta"])

print()
print("Maximum absolute numeric delta by field:")

for field in sorted(by_field):
    print(
        f"  {field:40s} "
        f"{max(by_field[field]):.18g}"
    )


print()
print("=" * 100)
print("IDENTITY CLI IMPLEMENTATION — READ ONLY")
print("=" * 100)

for filename, lo, hi in (
    ("src/transient_pipeline/poss1.py", 257, 300),
    ("src/transient_pipeline/cli.py", 297, 345),
):
    path = ROOT / filename

    print()
    print("FILE:", filename)

    lines = path.read_text(
        encoding="utf-8",
        errors="replace",
    ).splitlines()

    for n in range(lo, min(hi, len(lines)) + 1):
        print(f"{n:5d}: {lines[n - 1]}")


print()
print("=" * 100)
print("DIAGNOSTIC COMPLETE")
print("=" * 100)
print("No files were changed.")
print("No checkpoint state was changed.")
print("No identity jobs were added.")
print("No transient detector was run.")
