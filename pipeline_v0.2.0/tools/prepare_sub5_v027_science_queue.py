from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
import csv
import hashlib
import json


ROOT = Path.cwd()

FREEZE = (
    ROOT
    / "research_snapshots"
    / "poss1_identity_freeze_v0.2.7_2026-08-21"
)

FREEZE_MANIFEST = FREEZE / "freeze_manifest.json"

IDENTITY = ROOT / "results" / "poss1_identity_preflight.csv"

OUT = ROOT / "research" / "sub5_v027_science_queue.csv"
AUDIT = ROOT / "research" / "SUB5_V027_SCIENCE_QUEUE_AUDIT_2026-08-21.json"

EXPECTED_SNAPSHOT_ID = (
    "59c2db6c2c43266bc2af693ff4c6efe1199db409ed912cfa324cadc10793ddb2"
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

# The canonical 74-row queue has existed under more than one retained path.
# Select only by content invariants; never silently accept a different queue.
QUEUE_CANDIDATES = [
    ROOT / "research" / "canonical_sub5_pairs_74.csv",
    ROOT / "research" / "production_sub5_queue_2026-08-20.csv",
    ROOT / "canonical_sub5_pairs_74.csv",
    ROOT / "source_data" / "canonical_sub5_pairs_74.csv",
    FREEZE
        / "inputs"
        / "research"
        / "production_sub5_queue_2026-08-20.csv",
]


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def load_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def parse_utc(value: str) -> datetime:
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"

    dt = datetime.fromisoformat(text)

    if dt.tzinfo is None:
        raise ValueError(f"naive datetime is forbidden: {value!r}")

    if dt.utcoffset() != timezone.utc.utcoffset(dt):
        dt = dt.astimezone(timezone.utc)

    return dt


print("=" * 94)
print("v0.2.7 <=5-MINUTE SCIENCE QUEUE PREPARATION")
print("=" * 94)
print("No transient detector is executed by this program.")

# ----------------------------------------------------------------------
# 1. Freeze identity.
# ----------------------------------------------------------------------

if not FREEZE_MANIFEST.is_file():
    raise SystemExit(
        f"REFUSING: frozen v0.2.7 manifest missing: {FREEZE_MANIFEST}"
    )

manifest = json.loads(FREEZE_MANIFEST.read_text(encoding="utf-8"))

actual_snapshot_id = manifest.get("snapshot_id")

print()
print("Frozen identity snapshot:", actual_snapshot_id)

if actual_snapshot_id != EXPECTED_SNAPSHOT_ID:
    raise SystemExit(
        "REFUSING: active identity freeze is not the reviewed v0.2.7 snapshot."
    )

if manifest.get("checkpoint") != {"succeeded": 31}:
    raise SystemExit(
        f"REFUSING: frozen checkpoint changed: {manifest.get('checkpoint')}"
    )

accounting = manifest.get("identity_accounting") or {}

if accounting != {
    "validated_detector_eligible": 29,
    "catalogue_identified_pixels_unavailable": 2,
}:
    raise SystemExit(
        "REFUSING: frozen POSS identity accounting changed."
    )

# ----------------------------------------------------------------------
# 2. Locate exact 74-row canonical <=5-minute queue.
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

valid_queue_sources = []

for candidate in QUEUE_CANDIDATES:
    if not candidate.is_file():
        continue

    try:
        rows = load_csv(candidate)
    except Exception:
        continue

    if len(rows) != 74:
        continue

    if not rows:
        continue

    if not required_columns.issubset(rows[0]):
        continue

    valid_queue_sources.append((candidate, rows))

if not valid_queue_sources:
    raise SystemExit(
        "REFUSING: could not locate a 74-row canonical queue with the "
        "required timing/overlap columns."
    )

# Multiple copies are permitted only if content-identical.
hash_groups = {}

for path, rows in valid_queue_sources:
    hash_groups.setdefault(sha256_file(path), []).append(path)

if len(hash_groups) != 1:
    print()
    print("Conflicting candidate queue copies:")
    for digest, paths in hash_groups.items():
        print(" ", digest)
        for p in paths:
            print("    ", p)

    raise SystemExit(
        "REFUSING: multiple non-identical 74-row canonical queues exist."
    )

QUEUE, queue_rows = valid_queue_sources[0]
QUEUE_SHA = sha256_file(QUEUE)

print()
print("Canonical queue:", QUEUE)
print("Queue SHA256:  ", QUEUE_SHA)
print("Rows:          ", len(queue_rows))

# ----------------------------------------------------------------------
# 3. Frozen POSS identity table.
# ----------------------------------------------------------------------

if not IDENTITY.is_file():
    raise SystemExit(
        f"REFUSING: final POSS identity result missing: {IDENTITY}"
    )

identity_rows = load_csv(IDENTITY)

if len(identity_rows) != 31:
    raise SystemExit(
        f"REFUSING: expected 31 POSS identity rows, got {len(identity_rows)}"
    )

identity = {
    row["exposure_id"]: row
    for row in identity_rows
}

if len(identity) != 31:
    raise SystemExit("REFUSING: duplicate exposure_id in POSS identity table.")

# ----------------------------------------------------------------------
# 4. Recompute overlap interval for EVERY pair.
# ----------------------------------------------------------------------

out_rows = []
blocked = []
poss_pairs = 0
nonposs_pairs = 0

for source in queue_rows:
    row = dict(source)

    canonical_order = int(float(row["canonical_order"]))
    midpoint_delta = float(row["midpoint_delta_minutes"])

    if midpoint_delta < -1e-9 or midpoint_delta > 5.000001:
        raise SystemExit(
            f"REFUSING: canonical order {canonical_order} lies outside "
            f"the <=5-minute gate: {midpoint_delta}"
        )

    a_start = parse_utc(row["start_a_utc"])
    a_end = parse_utc(row["end_a_utc"])
    b_start = parse_utc(row["start_b_utc"])
    b_end = parse_utc(row["end_b_utc"])

    if a_end <= a_start or b_end <= b_start:
        raise SystemExit(
            f"REFUSING: invalid exposure interval at canonical order "
            f"{canonical_order}"
        )

    overlap_start = max(a_start, b_start)
    overlap_end = min(a_end, b_end)

    overlap_s = max(
        0.0,
        (overlap_end - overlap_start).total_seconds(),
    )

    stored_overlap_s = float(row["actual_exposure_overlap_s"])

    # Historical timestamps contain tiny floating-point/microsecond noise.
    if abs(overlap_s - stored_overlap_s) > 0.01:
        raise SystemExit(
            f"REFUSING: overlap mismatch at canonical order {canonical_order}: "
            f"recomputed={overlap_s:.9f}s stored={stored_overlap_s:.9f}s"
        )

    if overlap_s <= 0:
        raise SystemExit(
            f"REFUSING: <=5 canonical row {canonical_order} has no actual "
            "simultaneous exposure."
        )

    duration_a_s = (a_end - a_start).total_seconds()
    duration_b_s = (b_end - b_start).total_seconds()

    frac_a = overlap_s / duration_a_s
    frac_b = overlap_s / duration_b_s

    poss_ids = [
        exposure
        for exposure in (row["exposure_a"], row["exposure_b"])
        if exposure.startswith("POSS-I:")
    ]

    if len(poss_ids) > 1:
        raise SystemExit(
            f"REFUSING: unexpected POSS/POSS pair at canonical order "
            f"{canonical_order}: {poss_ids}"
        )

    if poss_ids:
        poss_pairs += 1
        poss_id = poss_ids[0]

        if poss_id not in identity:
            raise SystemExit(
                f"REFUSING: canonical order {canonical_order} references "
                f"POSS exposure absent from frozen identity table: {poss_id}"
            )

        ident = identity[poss_id]

        identity_status = ident.get("identity_status", "")
        eligible = str(
            ident.get("eligible_for_science", "")
        ).strip().lower() in {"true", "1"}

        if identity_status == "validated" and eligible:
            identity_gate = "passed_frozen_v027"
            execution_status = "pending_pixel_provenance_revalidation"

        elif (
            identity_status == "catalogue_identified_pixels_unavailable"
            and not eligible
        ):
            identity_gate = "blocked_archive_unavailable"
            execution_status = "not_detector_executable_archive_unavailable"

            blocked.append({
                "canonical_order": canonical_order,
                "exposure_id": poss_id,
                "finder_region": ident.get("finder_region", ""),
                "overlap_start_utc": overlap_start.isoformat(),
                "overlap_end_utc": overlap_end.isoformat(),
                "overlap_s": overlap_s,
            })

        else:
            raise SystemExit(
                f"REFUSING: unexpected frozen identity state for {poss_id}: "
                f"{identity_status!r}, eligible={eligible}"
            )

        row["poss_exposure_id"] = poss_id
        row["poss_identity_status"] = identity_status
        row["poss_finder_region"] = ident.get("finder_region", "")
        row["poss_identity_source"] = ident.get("identity_source", "")
        row["poss_eligible_for_science"] = ident.get(
            "eligible_for_science", ""
        )

    else:
        nonposs_pairs += 1
        row["poss_exposure_id"] = ""
        row["poss_identity_status"] = "not_applicable"
        row["poss_finder_region"] = ""
        row["poss_identity_source"] = ""
        row["poss_eligible_for_science"] = ""
        identity_gate = "not_applicable_nonposs"
        execution_status = "pending_pixel_provenance_revalidation"

    # Explicitly record the simultaneous physical exposure interval.
    row["overlap_start_utc"] = overlap_start.isoformat()
    row["overlap_end_utc"] = overlap_end.isoformat()
    row["overlap_duration_s_recomputed"] = f"{overlap_s:.9f}"
    row["overlap_duration_min_recomputed"] = f"{overlap_s / 60.0:.9f}"
    row["overlap_fraction_a_recomputed"] = f"{frac_a:.12f}"
    row["overlap_fraction_b_recomputed"] = f"{frac_b:.12f}"

    row["identity_gate_v027"] = identity_gate
    row["science_execution_status_v027"] = execution_status

    # Preserve prior dispositions but make their epistemic status explicit.
    row["legacy_saved_status_pre_v027"] = row.get("saved_status", "")
    row["legacy_saved_notes_pre_v027"] = row.get("saved_notes", "")
    row["legacy_result_policy"] = (
        "retained_for_audit_not_adopted_as_v027_science_until_pixel_"
        "provenance_matches_frozen_identity"
    )

    out_rows.append(row)

# ----------------------------------------------------------------------
# 5. Exact archive-unavailable pair guard.
# ----------------------------------------------------------------------

if len(blocked) != 2:
    raise SystemExit(
        f"REFUSING: expected exactly two blocked <=5-minute rows; "
        f"found {len(blocked)}"
    )

blocked_by_id = {
    item["exposure_id"]: item
    for item in blocked
}

if set(blocked_by_id) != set(EXPECTED_UNAVAILABLE):
    raise SystemExit(
        "REFUSING: blocked POSS set differs from frozen XO197/XE760 set."
    )

for exposure_id, expected in EXPECTED_UNAVAILABLE.items():
    actual = blocked_by_id[exposure_id]

    if actual["canonical_order"] != expected["canonical_order"]:
        raise SystemExit(
            f"REFUSING: {exposure_id} moved canonical order: "
            f"{actual['canonical_order']} != {expected['canonical_order']}"
        )

    if actual["finder_region"] != expected["finder_region"]:
        raise SystemExit(
            f"REFUSING: {exposure_id} finder region changed: "
            f"{actual['finder_region']} != {expected['finder_region']}"
        )

# ----------------------------------------------------------------------
# 6. Aggregate invariants.
# ----------------------------------------------------------------------

if poss_pairs != 47:
    raise SystemExit(
        f"REFUSING: expected 47 POSS-involving rows, got {poss_pairs}"
    )

if nonposs_pairs != 27:
    raise SystemExit(
        f"REFUSING: expected 27 non-POSS rows, got {nonposs_pairs}"
    )

execution_counts = Counter(
    row["science_execution_status_v027"]
    for row in out_rows
)

if execution_counts != Counter({
    "pending_pixel_provenance_revalidation": 72,
    "not_detector_executable_archive_unavailable": 2,
}):
    raise SystemExit(
        "REFUSING: unexpected science execution accounting:\n"
        + json.dumps(execution_counts, indent=2, sort_keys=True)
    )

# ----------------------------------------------------------------------
# 7. Write derived queue + audit.
# ----------------------------------------------------------------------

OUT.parent.mkdir(parents=True, exist_ok=True)

fieldnames = list(out_rows[0].keys())

with OUT.open("w", encoding="utf-8", newline="") as fh:
    writer = csv.DictWriter(
        fh,
        fieldnames=fieldnames,
        extrasaction="raise",
    )
    writer.writeheader()
    writer.writerows(out_rows)

audit = {
    "created_at_utc": datetime.now(timezone.utc).isoformat(),
    "identity_snapshot_id": EXPECTED_SNAPSHOT_ID,
    "identity_result": {
        "path": str(IDENTITY.relative_to(ROOT)),
        "sha256": sha256_file(IDENTITY),
        "rows": len(identity_rows),
    },
    "canonical_queue": {
        "path": str(QUEUE.relative_to(ROOT)),
        "sha256": QUEUE_SHA,
        "rows": len(queue_rows),
    },
    "derived_queue": {
        "path": str(OUT.relative_to(ROOT)),
        "sha256": sha256_file(OUT),
        "rows": len(out_rows),
    },
    "gate": "<=5-minute midpoint separation",
    "actual_overlap_policy": (
        "overlap_start=max(start_a,start_b); "
        "overlap_end=min(end_a,end_b); "
        "all 74 rows independently recomputed and required positive"
    ),
    "pair_accounting": {
        "total": len(out_rows),
        "poss_involving": poss_pairs,
        "nonposs": nonposs_pairs,
        "detector_executable_after_identity_gate": 72,
        "archive_unavailable_not_detector_executable": 2,
    },
    "blocked_archive_unavailable": blocked,
    "legacy_result_policy": (
        "Pre-v0.2.7 saved dispositions are retained for audit but are not "
        "automatically adopted as publication-grade v0.2.7 scientific "
        "results until pixel/FITS provenance is shown to match the frozen "
        "physical-plate identity."
    ),
    "detector_run": False,
}

AUDIT.write_text(
    json.dumps(audit, indent=2, sort_keys=True) + "\n",
    encoding="utf-8",
)

print()
print("=" * 94)
print("v0.2.7 <=5-MINUTE SCIENCE QUEUE PREPARED")
print("=" * 94)
print("Input canonical queue:", QUEUE)
print("Input SHA256:         ", QUEUE_SHA)
print("Derived queue:        ", OUT)
print("Derived SHA256:       ", sha256_file(OUT))
print("Audit:                ", AUDIT)

print()
print("Pair accounting:")
print("  total <=5-minute pairs:                         74")
print("  POSS-involving:                                  47")
print("  non-POSS:                                        27")
print("  positive actual exposure overlap:                74")
print("  detector-executable after POSS identity gate:    72")
print("  archive-unavailable / detector-ineligible:        2")

print()
print("Archive-unavailable rows:")
for item in sorted(blocked, key=lambda x: x["canonical_order"]):
    print(
        f"  order {item['canonical_order']:2d}: "
        f"{item['exposure_id']} -> {item['finder_region']} | "
        f"{item['overlap_start_utc']} .. "
        f"{item['overlap_end_utc']} | "
        f"{item['overlap_s']:.3f}s"
    )

print()
print("No previous detector result was silently promoted.")
print("No transient detector was run.")
