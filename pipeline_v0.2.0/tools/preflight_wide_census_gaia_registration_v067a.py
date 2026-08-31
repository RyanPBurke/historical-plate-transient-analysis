from pathlib import Path
import csv
import hashlib
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "results"
RESEARCH = ROOT / "research"

OUT = RESULTS / "wide_census_gaia_registration_preflight_v067a.json"

EXPECTED_HASHES = {
    RESEARCH / "prospective_freezes" /
    "wide_census_postdetector_adjudication_contract_v001.json":
        "1215400b989b187e87ceee27237fd2faf7ccff80dd57632158e06cbed7add2ad",

    RESEARCH / "prospective_freezes" /
    "wide_census_gaia_reference_acquisition_contract_v002.json":
        "458a043dfbdda8dbb853cbae77c269ff17a586c0ddb2fdcf7ac0388ee57ab3fc",

    RESEARCH / "prospective_freezes" /
    "wide_census_gaia_registration_contract_v001.json":
        "bd3456356392d56b73b3f6c8e16f51a028c1a43bce6a011871b7b3d341be907b",
}

REQUIRED_NAMES = [
    "wide_census_detector_candidates_v056.csv",
    "wide_census_pair_raw_matches_v056.csv",
    "wide_census_primary_astrometry_queue_v061.csv",
    "wide_census_postdetector_pair_inventory_v061.csv",
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


def resolve_unique(name):
    matches = sorted(
        p for p in RESULTS.rglob(name)
        if p.is_file()
    )

    return matches


report = {
    "stage": "wide_census_gaia_registration_preflight_v067a",
    "repair_of": "v067",
    "repair_reason":
        "v067 incorrectly assumed v061 compact products were at results root",
    "scientific_contract_changed": False,
    "thresholds_changed": False,
    "guards": {
        "network_calls": 0,
        "registrations_run": 0,
        "candidate_dispositions_changed": 0,
        "detector_rerun": False,
        "bulk_source_mutation": False
    },
    "hash_checks": [],
    "inputs": []
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


for name in REQUIRED_NAMES:
    matches = resolve_unique(name)

    item = {
        "filename": name,
        "match_count": len(matches),
        "matches": [
            str(p.relative_to(ROOT))
            for p in matches
        ]
    }

    if len(matches) == 1:
        path = matches[0]
        item["resolved_path"] = str(path.relative_to(ROOT))
        item["bytes"] = path.stat().st_size
        item["header"] = csv_header(path)
        item["status"] = "PASS"
    elif len(matches) == 0:
        item["status"] = "MISSING"
        failed = True
    else:
        item["status"] = "AMBIGUOUS"
        failed = True

    report["inputs"].append(item)


OUT.parent.mkdir(parents=True, exist_ok=True)

with OUT.open("w", encoding="utf-8") as f:
    json.dump(report, f, indent=2)


print("=" * 92)
print("WIDE CENSUS GAIA REGISTRATION PREFLIGHT v067a")
print("=" * 92)
print("Repair only: recursive exact-filename resolution for required inputs")
print("Scientific contract changed: NO")
print("Thresholds changed: NO")
print()

for row in report["hash_checks"]:
    print(
        f"HASH {'PASS' if row['match'] else 'FAIL'}  "
        f"{row['path']}"
    )

print()

for row in report["inputs"]:
    print(
        f"INPUT {row['status']:9s} "
        f"{row['filename']} "
        f"(matches={row['match_count']})"
    )

    if row.get("resolved_path"):
        print("  resolved:", row["resolved_path"])
        print("  columns:")
        print("   ", row["header"])

    if row["status"] == "AMBIGUOUS":
        for p in row["matches"]:
            print("   candidate:", p)

print()
print("Report:", OUT)
print()
print("Network calls: 0")
print("Astrometric registrations run: 0")
print("Candidate dispositions changed: NONE")

if failed:
    print("STAGE STATUS: FAILED PREFLIGHT")
    sys.exit(2)

print("STAGE STATUS: PREFLIGHT COMPLETE")
