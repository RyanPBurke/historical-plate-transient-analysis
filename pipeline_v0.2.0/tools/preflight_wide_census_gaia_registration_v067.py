from pathlib import Path
import csv
import hashlib
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "results"
RESEARCH = ROOT / "research"

OUT = RESULTS / "wide_census_gaia_registration_preflight_v067.json"

EXPECTED_HASHES = {
    RESEARCH / "prospective_freezes" /
    "wide_census_postdetector_adjudication_contract_v001.json":
        "1215400b989b187e87ceee27237fd2faf7ccff80dd57632158e06cbed7add2ad",

    RESEARCH / "prospective_freezes" /
    "wide_census_gaia_reference_acquisition_contract_v002.json":
        "458a043dfbdda8dbb853cbae77c269ff17a586c0ddb2fdcf7ac0388ee57ab3fc",
}

INPUTS = [
    RESULTS / "wide_census_detector_candidates_v056.csv",
    RESULTS / "wide_census_pair_raw_matches_v056.csv",
    RESULTS / "wide_census_primary_astrometry_queue_v061.csv",
    RESULTS / "wide_census_postdetector_pair_inventory_v061.csv",
]


def sha256(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def csv_header(path):
    with path.open(
        "r",
        encoding="utf-8-sig",
        errors="replace",
        newline=""
    ) as f:
        return next(csv.reader(f), [])


report = {
    "stage": "wide_census_gaia_registration_preflight_v067",
    "guards": {
        "network_calls": 0,
        "registrations_run": 0,
        "candidate_dispositions_changed": 0,
        "detector_rerun": False,
        "bulk_source_mutation": False
    },
    "hash_checks": [],
    "inputs": [],
    "relevant_products": []
}

failed = False

for path, expected in EXPECTED_HASHES.items():
    exists = path.exists()
    actual = sha256(path) if exists else None
    match = exists and actual == expected

    report["hash_checks"].append({
        "path": str(path.relative_to(ROOT)),
        "exists": exists,
        "expected_sha256": expected,
        "actual_sha256": actual,
        "match": match
    })

    if not match:
        failed = True

for path in INPUTS:
    exists = path.exists()

    item = {
        "path": str(path.relative_to(ROOT)),
        "exists": exists
    }

    if exists:
        item["bytes"] = path.stat().st_size
        item["header"] = csv_header(path)
    else:
        failed = True

    report["inputs"].append(item)

for p in RESULTS.rglob("*"):
    if not p.is_file():
        continue

    name = str(p).lower()

    if any(v in name for v in ("v061", "v064", "v065", "v066")):
        report["relevant_products"].append({
            "path": str(p.relative_to(ROOT)),
            "bytes": p.stat().st_size
        })

report["relevant_products"].sort(key=lambda x: x["path"])

OUT.parent.mkdir(parents=True, exist_ok=True)

with OUT.open("w", encoding="utf-8") as f:
    json.dump(report, f, indent=2)

print("=" * 88)
print("WIDE CENSUS GAIA REGISTRATION PREFLIGHT v067")
print("=" * 88)

for row in report["hash_checks"]:
    print(
        f"HASH {'PASS' if row['match'] else 'FAIL'}  "
        f"{row['path']}"
    )

print()

for row in report["inputs"]:
    print(
        f"INPUT {'PASS' if row['exists'] else 'FAIL'}  "
        f"{row['path']}"
    )
    if row.get("header") is not None:
        print("  columns:")
        print("   ", row["header"])

print()
print(
    "Relevant v061/v064/v065/v066 files:",
    len(report["relevant_products"])
)
print("Report:", OUT)
print()
print("Network calls: 0")
print("Astrometric registrations run: 0")
print("Candidate dispositions changed: NONE")

if failed:
    print("STAGE STATUS: FAILED PREFLIGHT")
    sys.exit(2)

print("STAGE STATUS: PREFLIGHT COMPLETE")
