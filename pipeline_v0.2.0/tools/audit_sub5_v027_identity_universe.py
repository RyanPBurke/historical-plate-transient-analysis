from __future__ import annotations

from collections import defaultdict
from pathlib import Path
import csv
import hashlib
import json
import re


ROOT = Path.cwd()

PRODUCTION = ROOT / "research" / "production_sub5_queue_2026-08-20.csv"
CANONICAL = ROOT / "research" / "canonical_sub5_pairs_74.csv"
IDENTITY = ROOT / "results" / "poss1_identity_preflight.csv"

EXPECTED_PRODUCTION_SHA = (
    "b044684fef65437a352edd28eafd21d668640bbec50cd0bc95f92e3529d0d77c"
)

EXPECTED_CANONICAL_SHA = (
    "58529e1d4de46f3c49865a89454d1cd488ee23ec920b01250006f2180d2ed99a"
)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def load_csv(path: Path):
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


for p in (PRODUCTION, CANONICAL, IDENTITY):
    if not p.is_file():
        raise SystemExit(f"Missing required file: {p}")

if sha256_file(PRODUCTION) != EXPECTED_PRODUCTION_SHA:
    raise SystemExit("Production queue SHA changed; refusing audit.")

if sha256_file(CANONICAL) != EXPECTED_CANONICAL_SHA:
    raise SystemExit("Canonical audit-input SHA changed; refusing audit.")


prod = load_csv(PRODUCTION)
canon = load_csv(CANONICAL)
identity_rows = load_csv(IDENTITY)

if len(prod) != 74:
    raise SystemExit(f"Production queue rows={len(prod)}, expected 74")

if len(canon) != 74:
    raise SystemExit(f"Canonical rows={len(canon)}, expected 74")

if len(identity_rows) != 31:
    raise SystemExit(f"Identity rows={len(identity_rows)}, expected frozen 31")


def poss_ids_from_row(row):
    out = []
    for key in ("exposure_a", "exposure_b"):
        value = str(row.get(key) or "")
        if value.startswith("POSS-I:"):
            out.append(value)
    return out


usage = defaultdict(list)

for row in prod:
    order = int(float(row["canonical_order"]))

    for pid in poss_ids_from_row(row):
        usage[pid].append({
            "canonical_order": order,
            "legacy_rank": row.get("legacy_rank", ""),
            "pair_key": row.get("pair_key", ""),
            "midpoint_delta_minutes": row.get(
                "midpoint_delta_minutes", ""
            ),
            "actual_exposure_overlap_s": row.get(
                "actual_exposure_overlap_s", ""
            ),
            "actual_exposure_overlap_minutes": row.get(
                "actual_exposure_overlap_minutes", ""
            ),
            "true_wcs_intersection": row.get(
                "true_wcs_intersection", ""
            ),
            "saved_status": row.get("saved_status", ""),
        })


production_ids = set(usage)
identity_ids = {
    str(row["exposure_id"])
    for row in identity_rows
}

missing = sorted(production_ids - identity_ids)
extra = sorted(identity_ids - production_ids)

print("=" * 100)
print("POSS-I <=5-MINUTE IDENTITY-UNIVERSE AUDIT")
print("=" * 100)

print()
print("Authoritative production queue:")
print(" rows:                ", len(prod))
print(" POSS-involving rows: ", sum(bool(poss_ids_from_row(r)) for r in prod))
print(" unique POSS IDs:     ", len(production_ids))

print()
print("Frozen v0.2.7 identity:")
print(" rows / unique IDs:   ", len(identity_ids))

print()
print("Coverage:")
print(" covered:             ", len(production_ids & identity_ids))
print(" missing:             ", len(missing))
print(" identity-only extras:", len(extra))

if len(production_ids) != 40:
    raise SystemExit(
        f"Expected 40 distinct production POSS exposures; got {len(production_ids)}"
    )

if len(identity_ids) != 31:
    raise SystemExit(
        f"Expected 31 frozen identity exposures; got {len(identity_ids)}"
    )

if len(missing) != 9:
    raise SystemExit(
        f"Expected exactly 9 missing identities; got {len(missing)}"
    )

print()
print("=" * 100)
print("NINE PRODUCTION POSS EXPOSURES ABSENT FROM v0.2.7 IDENTITY FREEZE")
print("=" * 100)

for pid in missing:
    print()
    print(pid)

    for u in sorted(
        usage[pid],
        key=lambda x: x["canonical_order"],
    ):
        print(
            "  order={order:2d} "
            "legacy_rank={rank!s:>4} "
            "midpoint={mid!s:>10} min "
            "overlap={ov!s:>12} s "
            "true_wcs={wcs!s:>5} "
            "saved={saved}".format(
                order=u["canonical_order"],
                rank=u["legacy_rank"],
                mid=u["midpoint_delta_minutes"],
                ov=u["actual_exposure_overlap_s"],
                wcs=u["true_wcs_intersection"],
                saved=u["saved_status"],
            )
        )

        print("    ", u["pair_key"])


if extra:
    print()
    print("=" * 100)
    print("FROZEN IDENTITY IDs NOT PRESENT IN AUTHORITATIVE PRODUCTION QUEUE")
    print("=" * 100)

    for pid in extra:
        print(" ", pid)


# ----------------------------------------------------------------------
# Compare the two 74-row queue files on COMMON columns only.
# The previous report counted production-only provenance fields as row diffs.
# ----------------------------------------------------------------------

prod_by_order = {
    int(float(r["canonical_order"])): r
    for r in prod
}

canon_by_order = {
    int(float(r["canonical_order"])): r
    for r in canon
}

prod_columns = set(prod[0])
canon_columns = set(canon[0])

common_columns = sorted(prod_columns & canon_columns)
prod_only = sorted(prod_columns - canon_columns)
canon_only = sorted(canon_columns - prod_columns)

common_field_diffs = []

for order in range(1, 75):
    a = prod_by_order[order]
    b = canon_by_order[order]

    changed = {}

    for col in common_columns:
        av = str(a.get(col) or "")
        bv = str(b.get(col) or "")

        if av != bv:
            changed[col] = {
                "production": av,
                "canonical": bv,
            }

    if changed:
        common_field_diffs.append({
            "canonical_order": order,
            "changed_fields": changed,
        })

print()
print("=" * 100)
print("PRODUCTION vs CANONICAL CONTENT CHECK")
print("=" * 100)

print("production-only columns:", prod_only)
print("canonical-only columns: ", canon_only)
print(
    "rows differing in fields shared by both files:",
    len(common_field_diffs),
)

if common_field_diffs:
    print()
    print("First 10 common-field row differences:")

    for item in common_field_diffs[:10]:
        print()
        print("order", item["canonical_order"])

        for col, values in item["changed_fields"].items():
            print(
                f"  {col}: "
                f"production={values['production']!r} "
                f"canonical={values['canonical']!r}"
            )


# ----------------------------------------------------------------------
# Find the code path that constructs the 31-job preflight universe.
# Read-only source scan only.
# ----------------------------------------------------------------------

patterns = [
    re.compile(r"poss1-preflight", re.I),
    re.compile(r"production_sub5", re.I),
    re.compile(r"canonical_sub5", re.I),
    re.compile(r"prospective_production", re.I),
    re.compile(r"PRE_FREEZE_ANALYSIS_INVENTORY", re.I),
    re.compile(r"POSS47", re.I),
    re.compile(r"legacy_rank", re.I),
    re.compile(r"identity.*prospective", re.I),
]

source_roots = [
    ROOT / "src",
    ROOT / "tools",
]

source_files = []

for base in source_roots:
    if not base.exists():
        continue

    for path in base.rglob("*"):
        if path.is_file() and path.suffix.lower() in {
            ".py", ".ps1"
        }:
            source_files.append(path)

wrapper = ROOT / "run_poss1_identity_preflight.ps1"

if wrapper.is_file():
    source_files.append(wrapper)


matches = []

for path in sorted(set(source_files)):
    try:
        lines = path.read_text(
            encoding="utf-8",
            errors="replace",
        ).splitlines()
    except Exception:
        continue

    hit_lines = set()

    for n, text in enumerate(lines, start=1):
        if any(p.search(text) for p in patterns):
            hit_lines.add(n)

    if not hit_lines:
        continue

    for n in sorted(hit_lines):
        lo = max(1, n - 4)
        hi = min(len(lines), n + 6)

        matches.append({
            "path": str(path.relative_to(ROOT)),
            "line": n,
            "context_start": lo,
            "context_end": hi,
            "context": [
                {
                    "line": i,
                    "text": lines[i - 1],
                }
                for i in range(lo, hi + 1)
            ],
        })


report = {
    "production_queue_sha256": sha256_file(PRODUCTION),
    "canonical_extra_sha256": sha256_file(CANONICAL),
    "production_pair_rows": len(prod),
    "production_poss_involving_rows": sum(
        bool(poss_ids_from_row(r))
        for r in prod
    ),
    "production_unique_poss_exposures": len(production_ids),
    "frozen_identity_exposures": len(identity_ids),
    "covered_exposures": sorted(production_ids & identity_ids),
    "missing_exposures": {
        pid: usage[pid]
        for pid in missing
    },
    "identity_only_exposures": extra,
    "production_only_columns": prod_only,
    "canonical_only_columns": canon_only,
    "common_field_difference_count": len(common_field_diffs),
    "common_field_differences": common_field_diffs,
    "preflight_constructor_source_matches": matches,
    "detector_run": False,
}

out = (
    ROOT
    / "research"
    / "SUB5_V027_IDENTITY_UNIVERSE_AUDIT_2026-08-21.json"
)

out.write_text(
    json.dumps(
        report,
        indent=2,
        sort_keys=True,
    ) + "\n",
    encoding="utf-8",
)

print()
print("=" * 100)
print("PREFLIGHT-CONSTRUCTOR SOURCE MATCHES")
print("=" * 100)

for m in matches:
    print()
    print(
        f"FILE: {m['path']} "
        f"(match line {m['line']})"
    )

    for c in m["context"]:
        prefix = ">>" if c["line"] == m["line"] else "  "
        print(
            f"{prefix} {c['line']:5d}: "
            f"{c['text']}"
        )

print()
print("=" * 100)
print("AUDIT COMPLETE")
print("=" * 100)
print("Report:", out)
print()
print("No checkpoint state changed.")
print("No identity job was added.")
print("No transient detector was run.")
