from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
import csv
import hashlib
import json


ROOT = Path.cwd()

IDENTITY_FREEZE = (
    ROOT
    / "research_snapshots"
    / "poss1_identity_freeze_v0.2.7_2026-08-21"
)

OLD_PRODUCTION_FREEZE = (
    ROOT
    / "research_snapshots"
    / "sub5_production_freeze_v0.2.1_2026-08-20"
)

IDENTITY_MANIFEST = IDENTITY_FREEZE / "freeze_manifest.json"

PRODUCTION = (
    ROOT
    / "research"
    / "production_sub5_queue_2026-08-20.csv"
)

PRODUCTION_OLD_FROZEN = (
    OLD_PRODUCTION_FREEZE
    / "inputs"
    / "production_sub5_queue_2026-08-20.csv"
)

PRODUCTION_IDENTITY_FROZEN = (
    IDENTITY_FREEZE
    / "inputs"
    / "research"
    / "production_sub5_queue_2026-08-20.csv"
)

CANONICAL_EXTRA = (
    ROOT
    / "research"
    / "canonical_sub5_pairs_74.csv"
)

CANONICAL_OLD_FROZEN = (
    OLD_PRODUCTION_FREEZE
    / "inputs"
    / "canonical_sub5_pairs_74.csv"
)

IDENTITY = (
    ROOT
    / "results"
    / "poss1_identity_preflight.csv"
)

OUT = (
    ROOT
    / "research"
    / "sub5_v027_science_queue.csv"
)

AUDIT = (
    ROOT
    / "research"
    / "SUB5_V027_SCIENCE_QUEUE_AUDIT_2026-08-21.json"
)

DIFF = (
    ROOT
    / "research"
    / "SUB5_PRODUCTION_VS_CANONICAL_DIFF_2026-08-21.json"
)

EXPECTED_IDENTITY_SNAPSHOT = (
    "59c2db6c2c43266bc2af693ff4c6efe1199db409ed912cfa324cadc10793ddb2"
)

EXPECTED_PRODUCTION_SHA = (
    "b044684fef65437a352edd28eafd21d668640bbec50cd0bc95f92e3529d0d77c"
)

EXPECTED_CANONICAL_SHA = (
    "58529e1d4de46f3c49865a89454d1cd488ee23ec920b01250006f2180d2ed99a"
)

EXPECTED_UNAVAILABLE = {
    "POSS-I:449:O:rec198": {
        "canonical_order": 17,
        "finder_region": "XO197",
    },
    "POSS-I:832:E:rec760": {
        "canonical_order": 60,
        "finder_region": "XE760",
    },
}


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()

    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)

    return h.hexdigest()


def load_csv(path: Path) -> list[dict[str, str]]:
    with path.open(
        "r",
        encoding="utf-8-sig",
        newline="",
    ) as fh:
        return list(csv.DictReader(fh))


def parse_utc(value: str) -> datetime:
    text = str(value).strip()

    if text.endswith("Z"):
        text = text[:-1] + "+00:00"

    dt = datetime.fromisoformat(text)

    if dt.tzinfo is None:
        raise ValueError(
            f"naive datetime forbidden: {value!r}"
        )

    return dt.astimezone(timezone.utc)


def boolish(value: object) -> bool:
    return str(value or "").strip().lower() in {
        "true",
        "1",
        "yes",
    }


def require_file(path: Path) -> None:
    if not path.is_file():
        raise SystemExit(
            f"REFUSING: required file missing: {path}"
        )


print("=" * 96)
print("v0.2.7 <=5-MINUTE AUTHORITATIVE SCIENCE-QUEUE HANDOFF")
print("=" * 96)
print("No transient detector is executed by this program.")

for path in (
    IDENTITY_MANIFEST,
    PRODUCTION,
    PRODUCTION_IDENTITY_FROZEN,
    CANONICAL_EXTRA,
    IDENTITY,
):
    require_file(path)

# ----------------------------------------------------------------------
# 1. Identity-freeze guard.
# ----------------------------------------------------------------------

manifest = json.loads(
    IDENTITY_MANIFEST.read_text(encoding="utf-8")
)

snapshot_id = manifest.get("snapshot_id")

if snapshot_id != EXPECTED_IDENTITY_SNAPSHOT:
    raise SystemExit(
        "REFUSING: active POSS identity snapshot differs "
        "from reviewed v0.2.7 freeze."
    )

print()
print("Identity snapshot:", snapshot_id)

# ----------------------------------------------------------------------
# 2. Resolve queue provenance by the already-frozen roles.
# ----------------------------------------------------------------------

production_sha = sha256_file(PRODUCTION)
production_identity_frozen_sha = sha256_file(
    PRODUCTION_IDENTITY_FROZEN
)
canonical_sha = sha256_file(CANONICAL_EXTRA)

print()
print("QUEUE PROVENANCE")
print("-" * 96)

print("production live:")
print(" ", PRODUCTION)
print(" ", production_sha)

print("production in v0.2.7 identity freeze:")
print(" ", PRODUCTION_IDENTITY_FROZEN)
print(" ", production_identity_frozen_sha)

print("canonical extra input:")
print(" ", CANONICAL_EXTRA)
print(" ", canonical_sha)

if production_sha != EXPECTED_PRODUCTION_SHA:
    raise SystemExit(
        "REFUSING: live production queue hash differs from "
        "the frozen authoritative queue."
    )

if production_identity_frozen_sha != EXPECTED_PRODUCTION_SHA:
    raise SystemExit(
        "REFUSING: v0.2.7 identity freeze does not contain "
        "the expected authoritative production queue."
    )

if canonical_sha != EXPECTED_CANONICAL_SHA:
    raise SystemExit(
        "REFUSING: canonical audit input changed unexpectedly."
    )

# Cross-check against the original sub5 production freeze if retained.
if PRODUCTION_OLD_FROZEN.is_file():
    old_prod_sha = sha256_file(
        PRODUCTION_OLD_FROZEN
    )

    print("production in v0.2.1 sub5 freeze:")
    print(" ", PRODUCTION_OLD_FROZEN)
    print(" ", old_prod_sha)

    if old_prod_sha != EXPECTED_PRODUCTION_SHA:
        raise SystemExit(
            "REFUSING: original production freeze queue "
            "does not match the authoritative SHA."
        )

if CANONICAL_OLD_FROZEN.is_file():
    old_canonical_sha = sha256_file(
        CANONICAL_OLD_FROZEN
    )

    print("canonical in v0.2.1 sub5 freeze:")
    print(" ", CANONICAL_OLD_FROZEN)
    print(" ", old_canonical_sha)

    if old_canonical_sha != EXPECTED_CANONICAL_SHA:
        raise SystemExit(
            "REFUSING: original frozen canonical extra input "
            "does not match expected SHA."
        )

print()
print("Authoritative execution role:")
print("  production_sub5_queue_2026-08-20.csv = QUEUE")
print("  canonical_sub5_pairs_74.csv           = EXTRA INPUT / AUDIT")

# ----------------------------------------------------------------------
# 3. Read both 74-row files and preserve a complete row-level diff.
# ----------------------------------------------------------------------

prod_rows = load_csv(PRODUCTION)
canonical_rows = load_csv(CANONICAL_EXTRA)

if len(prod_rows) != 74:
    raise SystemExit(
        f"REFUSING: authoritative production queue has "
        f"{len(prod_rows)} rows, expected 74."
    )

if len(canonical_rows) != 74:
    raise SystemExit(
        f"REFUSING: canonical audit input has "
        f"{len(canonical_rows)} rows, expected 74."
    )

for label, rows in (
    ("production", prod_rows),
    ("canonical", canonical_rows),
):
    orders = [
        int(float(row["canonical_order"]))
        for row in rows
    ]

    if sorted(orders) != list(range(1, 75)):
        raise SystemExit(
            f"REFUSING: {label} canonical_order is not "
            "exactly 1..74."
        )

prod_by_order = {
    int(float(r["canonical_order"])): r
    for r in prod_rows
}

canonical_by_order = {
    int(float(r["canonical_order"])): r
    for r in canonical_rows
}

prod_columns = list(prod_rows[0].keys())
canonical_columns = list(
    canonical_rows[0].keys()
)

all_columns = sorted(
    set(prod_columns) | set(canonical_columns)
)

row_diffs = []

for order in range(1, 75):
    a = prod_by_order[order]
    b = canonical_by_order[order]

    changed = {}

    for column in all_columns:
        av = str(a.get(column, "") or "")
        bv = str(b.get(column, "") or "")

        if av != bv:
            changed[column] = {
                "production": av,
                "canonical_extra": bv,
            }

    if changed:
        row_diffs.append({
            "canonical_order": order,
            "production_pair_key": a.get(
                "pair_key", ""
            ),
            "canonical_pair_key": b.get(
                "pair_key", ""
            ),
            "changed_fields": changed,
        })

diff_record = {
    "created_at_utc":
        datetime.now(timezone.utc).isoformat(),
    "interpretation": (
        "production_sub5_queue_2026-08-20.csv is the "
        "frozen logical-role queue. "
        "canonical_sub5_pairs_74.csv is retained as "
        "a frozen extra_input and is not an equal "
        "execution claimant."
    ),
    "production": {
        "path": str(
            PRODUCTION.relative_to(ROOT)
        ),
        "sha256": production_sha,
        "logical_role": "queue",
        "rows": 74,
        "columns": prod_columns,
    },
    "canonical_extra": {
        "path": str(
            CANONICAL_EXTRA.relative_to(ROOT)
        ),
        "sha256": canonical_sha,
        "logical_role": "extra_input",
        "rows": 74,
        "columns": canonical_columns,
    },
    "columns_only_in_production": sorted(
        set(prod_columns)
        - set(canonical_columns)
    ),
    "columns_only_in_canonical_extra": sorted(
        set(canonical_columns)
        - set(prod_columns)
    ),
    "row_difference_count": len(row_diffs),
    "row_differences": row_diffs,
}

DIFF.parent.mkdir(
    parents=True,
    exist_ok=True,
)

DIFF.write_text(
    json.dumps(
        diff_record,
        indent=2,
        sort_keys=True,
    ) + "\n",
    encoding="utf-8",
)

print()
print("Production-vs-canonical diff:")
print(" ", DIFF)
print(" rows with >=1 differing field:",
      len(row_diffs))

print(
    " columns only in production:",
    len(
        diff_record[
            "columns_only_in_production"
        ]
    ),
)

print(
    " columns only in canonical:",
    len(
        diff_record[
            "columns_only_in_canonical_extra"
        ]
    ),
)

# ----------------------------------------------------------------------
# 4. Load frozen POSS identity states.
# ----------------------------------------------------------------------

identity_rows = load_csv(IDENTITY)

if len(identity_rows) != 31:
    raise SystemExit(
        f"REFUSING: expected 31 POSS identity rows, "
        f"got {len(identity_rows)}."
    )

identity = {
    row["exposure_id"]: row
    for row in identity_rows
}

if len(identity) != 31:
    raise SystemExit(
        "REFUSING: duplicate POSS exposure IDs "
        "in identity result."
    )

# ----------------------------------------------------------------------
# 5. Recompute ACTUAL exposure overlap for all 74 production rows.
# ----------------------------------------------------------------------

required_columns = {
    "canonical_order",
    "pair_set",
    "pair_key",
    "exposure_a",
    "archive_a",
    "site_a",
    "start_a_utc",
    "end_a_utc",
    "duration_a_s",
    "exposure_b",
    "archive_b",
    "site_b",
    "start_b_utc",
    "end_b_utc",
    "duration_b_s",
    "midpoint_delta_minutes",
    "actual_exposure_overlap_s",
    "actual_exposure_overlap_minutes",
}

missing = (
    required_columns
    - set(prod_rows[0])
)

if missing:
    raise SystemExit(
        "REFUSING: authoritative production queue "
        f"is missing columns: {sorted(missing)}"
    )

out_rows = []
blocked = []

poss_pairs = 0
nonposs_pairs = 0

for source in prod_rows:
    row = dict(source)

    order = int(
        float(row["canonical_order"])
    )

    midpoint = float(
        row["midpoint_delta_minutes"]
    )

    if midpoint < -1e-9 or midpoint > 5.000001:
        raise SystemExit(
            f"REFUSING: order {order} is outside "
            f"<=5-minute gate: {midpoint}"
        )

    start_a = parse_utc(
        row["start_a_utc"]
    )
    end_a = parse_utc(
        row["end_a_utc"]
    )
    start_b = parse_utc(
        row["start_b_utc"]
    )
    end_b = parse_utc(
        row["end_b_utc"]
    )

    if end_a <= start_a:
        raise SystemExit(
            f"REFUSING: invalid exposure A "
            f"interval at order {order}"
        )

    if end_b <= start_b:
        raise SystemExit(
            f"REFUSING: invalid exposure B "
            f"interval at order {order}"
        )

    overlap_start = max(
        start_a,
        start_b,
    )

    overlap_end = min(
        end_a,
        end_b,
    )

    overlap_s = max(
        0.0,
        (
            overlap_end
            - overlap_start
        ).total_seconds(),
    )

    stored_overlap_s = float(
        row[
            "actual_exposure_overlap_s"
        ]
    )

    if abs(
        overlap_s
        - stored_overlap_s
    ) > 0.01:
        raise SystemExit(
            f"REFUSING: actual-overlap mismatch "
            f"at order {order}: "
            f"recomputed={overlap_s:.9f}s, "
            f"stored={stored_overlap_s:.9f}s"
        )

    if overlap_s <= 0:
        raise SystemExit(
            f"REFUSING: order {order} has no "
            "actual simultaneous exposure."
        )

    duration_a_s = (
        end_a - start_a
    ).total_seconds()

    duration_b_s = (
        end_b - start_b
    ).total_seconds()

    fraction_a = (
        overlap_s / duration_a_s
    )

    fraction_b = (
        overlap_s / duration_b_s
    )

    poss_ids = [
        exposure
        for exposure in (
            row["exposure_a"],
            row["exposure_b"],
        )
        if exposure.startswith(
            "POSS-I:"
        )
    ]

    if len(poss_ids) > 1:
        raise SystemExit(
            f"REFUSING: unexpected POSS/POSS "
            f"pair at order {order}: "
            f"{poss_ids}"
        )

    if poss_ids:
        poss_pairs += 1
        poss_id = poss_ids[0]

        if poss_id not in identity:
            raise SystemExit(
                f"REFUSING: order {order} "
                f"references POSS exposure "
                f"absent from frozen identity: "
                f"{poss_id}"
            )

        ident = identity[poss_id]

        identity_status = str(
            ident.get(
                "identity_status",
                "",
            )
        )

        eligible = boolish(
            ident.get(
                "eligible_for_science",
                "",
            )
        )

        if (
            identity_status
            == "validated"
            and eligible
        ):
            identity_gate = (
                "passed_frozen_v027"
            )

            execution_status = (
                "pending_pixel_"
                "provenance_revalidation"
            )

        elif (
            identity_status
            == "catalogue_identified_"
               "pixels_unavailable"
            and not eligible
        ):
            identity_gate = (
                "blocked_archive_unavailable"
            )

            execution_status = (
                "not_detector_executable_"
                "archive_unavailable"
            )

            blocked.append({
                "canonical_order":
                    order,
                "exposure_id":
                    poss_id,
                "finder_region":
                    ident.get(
                        "finder_region",
                        "",
                    ),
                "overlap_start_utc":
                    overlap_start.isoformat(),
                "overlap_end_utc":
                    overlap_end.isoformat(),
                "overlap_s":
                    overlap_s,
            })

        else:
            raise SystemExit(
                f"REFUSING: unexpected "
                f"frozen identity state "
                f"for {poss_id}: "
                f"{identity_status!r}, "
                f"eligible={eligible}"
            )

        row["poss_exposure_id"] = (
            poss_id
        )

        row[
            "poss_identity_status"
        ] = identity_status

        row[
            "poss_finder_region"
        ] = ident.get(
            "finder_region",
            "",
        )

        row[
            "poss_identity_source"
        ] = ident.get(
            "identity_source",
            "",
        )

        row[
            "poss_eligible_for_science"
        ] = ident.get(
            "eligible_for_science",
            "",
        )

    else:
        nonposs_pairs += 1

        row["poss_exposure_id"] = ""
        row["poss_identity_status"] = (
            "not_applicable"
        )
        row["poss_finder_region"] = ""
        row["poss_identity_source"] = ""
        row[
            "poss_eligible_for_science"
        ] = ""

        identity_gate = (
            "not_applicable_nonposs"
        )

        execution_status = (
            "pending_pixel_"
            "provenance_revalidation"
        )

    row[
        "overlap_start_utc"
    ] = overlap_start.isoformat()

    row[
        "overlap_end_utc"
    ] = overlap_end.isoformat()

    row[
        "overlap_duration_s_recomputed"
    ] = f"{overlap_s:.9f}"

    row[
        "overlap_duration_min_recomputed"
    ] = f"{overlap_s / 60:.9f}"

    row[
        "overlap_fraction_a_recomputed"
    ] = f"{fraction_a:.12f}"

    row[
        "overlap_fraction_b_recomputed"
    ] = f"{fraction_b:.12f}"

    row[
        "identity_gate_v027"
    ] = identity_gate

    row[
        "science_execution_status_v027"
    ] = execution_status

    row[
        "authoritative_queue_role"
    ] = "frozen_production_queue"

    row[
        "authoritative_queue_sha256"
    ] = EXPECTED_PRODUCTION_SHA

    row[
        "legacy_saved_status_pre_v027"
    ] = row.get(
        "saved_status",
        "",
    )

    row[
        "legacy_saved_notes_pre_v027"
    ] = row.get(
        "saved_notes",
        "",
    )

    row[
        "legacy_result_policy"
    ] = (
        "retained_for_audit_not_adopted_"
        "as_v027_science_until_pixel_"
        "provenance_matches_frozen_identity"
    )

    out_rows.append(row)

# ----------------------------------------------------------------------
# 6. Exact frozen unavailable-set guard.
# ----------------------------------------------------------------------

if len(blocked) != 2:
    raise SystemExit(
        f"REFUSING: expected exactly two "
        f"archive-unavailable <=5 rows, "
        f"found {len(blocked)}."
    )

blocked_by_id = {
    x["exposure_id"]: x
    for x in blocked
}

if set(blocked_by_id) != set(
    EXPECTED_UNAVAILABLE
):
    raise SystemExit(
        "REFUSING: blocked exposure set "
        "is not exactly XO197 + XE760."
    )

for exposure_id, expected in (
    EXPECTED_UNAVAILABLE.items()
):
    actual = blocked_by_id[
        exposure_id
    ]

    if (
        actual["canonical_order"]
        != expected["canonical_order"]
    ):
        raise SystemExit(
            f"REFUSING: {exposure_id} "
            "canonical order changed: "
            f"{actual['canonical_order']} "
            "!= "
            f"{expected['canonical_order']}"
        )

    if (
        actual["finder_region"]
        != expected["finder_region"]
    ):
        raise SystemExit(
            f"REFUSING: {exposure_id} "
            "finder region changed: "
            f"{actual['finder_region']} "
            "!= "
            f"{expected['finder_region']}"
        )

# ----------------------------------------------------------------------
# 7. Aggregate science-queue invariants.
# ----------------------------------------------------------------------

if poss_pairs != 47:
    raise SystemExit(
        f"REFUSING: expected 47 "
        f"POSS-involving rows, "
        f"got {poss_pairs}."
    )

if nonposs_pairs != 27:
    raise SystemExit(
        f"REFUSING: expected 27 "
        f"non-POSS rows, "
        f"got {nonposs_pairs}."
    )

execution_counts = Counter(
    row[
        "science_execution_status_v027"
    ]
    for row in out_rows
)

expected_execution = Counter({
    "pending_pixel_provenance_revalidation":
        72,
    "not_detector_executable_archive_unavailable":
        2,
})

if execution_counts != expected_execution:
    raise SystemExit(
        "REFUSING: science-execution "
        "accounting changed:\n"
        + json.dumps(
            dict(execution_counts),
            indent=2,
            sort_keys=True,
        )
    )

# ----------------------------------------------------------------------
# 8. Write v0.2.7 science handoff.
# ----------------------------------------------------------------------

OUT.parent.mkdir(
    parents=True,
    exist_ok=True,
)

with OUT.open(
    "w",
    encoding="utf-8",
    newline="",
) as fh:
    writer = csv.DictWriter(
        fh,
        fieldnames=list(
            out_rows[0].keys()
        ),
        extrasaction="raise",
    )

    writer.writeheader()
    writer.writerows(out_rows)

audit = {
    "created_at_utc":
        datetime.now(
            timezone.utc
        ).isoformat(),

    "identity_snapshot_id":
        EXPECTED_IDENTITY_SNAPSHOT,

    "queue_lineage": {
        "authoritative": {
            "path": str(
                PRODUCTION.relative_to(
                    ROOT
                )
            ),
            "sha256":
                production_sha,
            "logical_role":
                "queue",
        },
        "canonical_extra_input": {
            "path": str(
                CANONICAL_EXTRA.relative_to(
                    ROOT
                )
            ),
            "sha256":
                canonical_sha,
            "logical_role":
                "extra_input",
        },
        "diff_report": str(
            DIFF.relative_to(ROOT)
        ),
    },

    "identity_result": {
        "path": str(
            IDENTITY.relative_to(ROOT)
        ),
        "sha256":
            sha256_file(IDENTITY),
        "rows":
            len(identity_rows),
    },

    "derived_queue": {
        "path": str(
            OUT.relative_to(ROOT)
        ),
        "sha256":
            sha256_file(OUT),
        "rows":
            len(out_rows),
    },

    "gate":
        "<=5-minute midpoint separation",

    "actual_overlap_policy": (
        "overlap_start=max(start_a,start_b); "
        "overlap_end=min(end_a,end_b); "
        "all 74 authoritative production rows "
        "independently recomputed and required "
        "to have positive actual overlap"
    ),

    "pair_accounting": {
        "total":
            74,
        "poss_involving":
            poss_pairs,
        "nonposs":
            nonposs_pairs,
        "positive_actual_overlap":
            74,
        "detector_executable_after_identity_gate":
            72,
        "archive_unavailable_not_detector_executable":
            2,
    },

    "blocked_archive_unavailable":
        blocked,

    "legacy_result_policy": (
        "Pre-v0.2.7 dispositions are preserved "
        "for audit but are not automatically "
        "promoted to v0.2.7 publication science "
        "until their pixel/FITS provenance is "
        "demonstrated to match the frozen physical "
        "plate identity."
    ),

    "detector_run":
        False,
}

AUDIT.write_text(
    json.dumps(
        audit,
        indent=2,
        sort_keys=True,
    ) + "\n",
    encoding="utf-8",
)

print()
print("=" * 96)
print("v0.2.7 <=5-MINUTE SCIENCE QUEUE PREPARED")
print("=" * 96)

print("Authoritative source:")
print(" ", PRODUCTION)
print(" ", production_sha)

print()
print("Canonical audit input:")
print(" ", CANONICAL_EXTRA)
print(" ", canonical_sha)

print()
print("Diff report:")
print(" ", DIFF)

print()
print("Derived science queue:")
print(" ", OUT)
print(" ", sha256_file(OUT))

print()
print("Audit:")
print(" ", AUDIT)

print()
print("Pair accounting:")
print("  <=5-minute prospective pairs:                74")
print("  POSS-involving:                              47")
print("  non-POSS:                                    27")
print("  positive actual exposure overlap:            74")
print("  detector-executable after identity gate:     72")
print("  unavailable, retained in denominator:         2")

print()
print("Archive-unavailable:")
for item in sorted(
    blocked,
    key=lambda x: x[
        "canonical_order"
    ],
):
    print(
        f"  order "
        f"{item['canonical_order']:2d}: "
        f"{item['exposure_id']} -> "
        f"{item['finder_region']} | "
        f"{item['overlap_start_utc']} .. "
        f"{item['overlap_end_utc']} | "
        f"{item['overlap_s']:.3f}s"
    )

print()
print(
    "Rows differing between authoritative "
    "production queue and canonical extra input:",
    len(row_diffs),
)

print()
print("No legacy detector result was silently promoted.")
print("No transient detector was run.")
