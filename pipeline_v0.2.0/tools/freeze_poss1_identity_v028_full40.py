from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
import csv
import hashlib
import json
import shutil
import sqlite3
import subprocess
import sys


ROOT = Path.cwd()

VERSION = "0.2.8"
DATE = "2026-08-21"

PRODUCTION = (
    ROOT / "research" / "production_sub5_queue_2026-08-20.csv"
)

CANONICAL = (
    ROOT / "research" / "canonical_sub5_pairs_74.csv"
)

V027_FREEZE = (
    ROOT
    / "research_snapshots"
    / "poss1_identity_freeze_v0.2.7_2026-08-21"
)

V027_MANIFEST = V027_FREEZE / "freeze_manifest.json"

V027_RESULT = (
    V027_FREEZE
    / "inputs"
    / "results"
    / "poss1_identity_preflight.csv"
)

EXT_RESULT = (
    ROOT
    / "results"
    / "poss1_identity_extension_v028.csv"
)

EXT_DB = (
    ROOT
    / "state"
    / "poss1_identity_extension_v028.sqlite"
)

EXT_QUEUE = (
    ROOT
    / "research"
    / "poss1_identity_extension_v028_nine_queue.csv"
)

EXT_AUDIT = (
    ROOT
    / "research"
    / "POSS1_V028_NINE_IDENTITY_EXTENSION_AUDIT_2026-08-21.json"
)

SEMANTIC_AUDIT = (
    ROOT
    / "research"
    / "POSS1_V027_LIVE_VS_FROZEN_SQLITE_SEMANTIC_AUDIT_2026-08-21.json"
)

SKY = ROOT / "src" / "transient_pipeline" / "poss1_skyview.py"
POSS = ROOT / "src" / "transient_pipeline" / "poss1.py"

CONFIG = ROOT / "config" / "frozen_method.json"

RUN_SCRIPT = (
    ROOT
    / "tools"
    / "run_v028_nine_identity_extension.py"
)

FULL40_RESULT = (
    ROOT
    / "results"
    / "poss1_identity_full40_v028.csv"
)

FREEZE = (
    ROOT
    / "research_snapshots"
    / "poss1_identity_freeze_v0.2.8_2026-08-21"
)

CLOSURE = (
    ROOT
    / "research"
    / "POSS1_IDENTITY_PREFLIGHT_V028_FULL40_CLOSURE_2026-08-21.md"
)

PYTHON = ROOT / ".venv" / "Scripts" / "python.exe"
CLI = ROOT / ".venv" / "Scripts" / "transient-pipeline.exe"

EXPECTED_PRODUCTION_SHA = (
    "b044684fef65437a352edd28eafd21d668640bbec50cd0bc95f92e3529d0d77c"
)

EXPECTED_CANONICAL_SHA = (
    "58529e1d4de46f3c49865a89454d1cd488ee23ec920b01250006f2180d2ed99a"
)

EXPECTED_V027_SNAPSHOT_ID = (
    "59c2db6c2c43266bc2af693ff4c6efe1199db409ed912cfa324cadc10793ddb2"
)

EXPECTED_V027_MANIFEST_SHA = (
    "a6b2012218168018665d555aba1336b05a1ccad4b5655d4a8a82c1d7b91f62bc"
)

EXPECTED_V027_RESULT_SHA = (
    "4d57fce8e2c683acc6b1a9ba3714852cb1ee66136880f1df34f8ce3ed3d19017"
)

EXPECTED_EXT_QUEUE_SHA = (
    "5199026fcce3fa21a9bd960a56494f9e8fb53a4c88d9f59de94bcf5f3f409693"
)

EXPECTED_SKY_SHA = (
    "22470c1956e6b0ddb885d51092aa0a30dd322bfc1d48c6b49bcd0ed3620a732e"
)

EXPECTED_POSS_SHA = (
    "6161a74d5ce76f70235c66a748077b3517f7d2d7946e9f48998927c331374ac7"
)

EXPECTED_UNAVAILABLE = {
    "POSS-I:449:O:rec198": "XO197",
    "POSS-I:832:E:rec760": "XE760",
    "POSS-I:988:O:rec207": "XO206",
}


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()

    with path.open("rb") as fh:
        for block in iter(
            lambda: fh.read(1024 * 1024),
            b"",
        ):
            h.update(block)

    return h.hexdigest()


def require(path: Path) -> None:
    if not path.is_file():
        raise SystemExit(
            f"REFUSING: required file missing: {path}"
        )


def load_csv(path: Path) -> list[dict[str, str]]:
    with path.open(
        "r",
        encoding="utf-8-sig",
        newline="",
    ) as fh:
        return list(csv.DictReader(fh))


def exposure_id(row: dict[str, str]) -> str:
    value = (
        row.get("exposure_id")
        or row.get("job_key")
        or ""
    )

    return str(value)


def poss_ids(row: dict[str, str]) -> list[str]:
    return [
        value
        for value in (
            str(row.get("exposure_a") or ""),
            str(row.get("exposure_b") or ""),
        )
        if value.startswith("POSS-I:")
    ]


def is_true(value) -> bool:
    return str(value).strip().lower() in {
        "1",
        "true",
        "yes",
    }


def copy_file(
    src: Path,
    destination_relative: str,
) -> dict:
    dst = FREEZE / destination_relative

    dst.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    shutil.copy2(
        src,
        dst,
    )

    return {
        "source":
            str(src.relative_to(ROOT)),
        "snapshot_path":
            destination_relative.replace("\\", "/"),
        "bytes":
            dst.stat().st_size,
        "sha256":
            sha256_file(dst),
    }


def sqlite_snapshot(
    src: Path,
    destination_relative: str,
) -> dict:
    dst = FREEZE / destination_relative

    dst.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    if dst.exists():
        raise SystemExit(
            f"REFUSING: snapshot SQLite target exists: {dst}"
        )

    source = sqlite3.connect(
        f"file:{src.resolve()}?mode=ro",
        uri=True,
    )

    target = sqlite3.connect(dst)

    source.backup(target)

    target.close()
    source.close()

    con = sqlite3.connect(
        f"file:{dst.resolve()}?mode=ro",
        uri=True,
    )

    integrity = [
        str(x[0])
        for x in con.execute(
            "PRAGMA integrity_check"
        ).fetchall()
    ]

    con.close()

    if integrity != ["ok"]:
        raise SystemExit(
            f"REFUSING: frozen SQLite integrity failed: {integrity}"
        )

    return {
        "source":
            str(src.relative_to(ROOT)),
        "snapshot_path":
            destination_relative.replace("\\", "/"),
        "bytes":
            dst.stat().st_size,
        "sha256":
            sha256_file(dst),
        "integrity_check":
            integrity,
    }


# ======================================================================
# 1. Preconditions / immutability
# ======================================================================

print("=" * 100)
print("POSS-I v0.2.8 FULL-40 IDENTITY / AVAILABILITY PUBLICATION FREEZE")
print("=" * 100)
print("No transient detector is executed by this program.")

for path in (
    PRODUCTION,
    CANONICAL,
    V027_MANIFEST,
    V027_RESULT,
    EXT_RESULT,
    EXT_DB,
    EXT_QUEUE,
    EXT_AUDIT,
    SEMANTIC_AUDIT,
    SKY,
    POSS,
    CONFIG,
    RUN_SCRIPT,
    PYTHON,
    CLI,
):
    require(path)

guards = {
    "production":
        (
            sha256_file(PRODUCTION),
            EXPECTED_PRODUCTION_SHA,
        ),
    "canonical":
        (
            sha256_file(CANONICAL),
            EXPECTED_CANONICAL_SHA,
        ),
    "v027_manifest":
        (
            sha256_file(V027_MANIFEST),
            EXPECTED_V027_MANIFEST_SHA,
        ),
    "v027_result":
        (
            sha256_file(V027_RESULT),
            EXPECTED_V027_RESULT_SHA,
        ),
    "extension_queue":
        (
            sha256_file(EXT_QUEUE),
            EXPECTED_EXT_QUEUE_SHA,
        ),
    "poss1_skyview":
        (
            sha256_file(SKY),
            EXPECTED_SKY_SHA,
        ),
    "poss1":
        (
            sha256_file(POSS),
            EXPECTED_POSS_SHA,
        ),
}

print()
print("HASH GUARDS")
print("-" * 100)

for label, (actual, expected) in guards.items():
    print(label)
    print(" expected:", expected)
    print(" actual:  ", actual)

    if actual != expected:
        raise SystemExit(
            f"REFUSING: hash guard failed: {label}"
        )


v027_manifest = json.loads(
    V027_MANIFEST.read_text(
        encoding="utf-8",
    )
)

if (
    v027_manifest.get("snapshot_id")
    != EXPECTED_V027_SNAPSHOT_ID
):
    raise SystemExit(
        "REFUSING: v0.2.7 snapshot ID changed."
    )


semantic = json.loads(
    SEMANTIC_AUDIT.read_text(
        encoding="utf-8",
    )
)

if not semantic.get(
    "semantic_database_equivalence",
    False,
):
    raise SystemExit(
        "REFUSING: v0.2.7 semantic DB audit is not PASS."
    )


ext_audit = json.loads(
    EXT_AUDIT.read_text(
        encoding="utf-8",
    )
)

if ext_audit.get(
    "detector_run"
) is not False:
    raise SystemExit(
        "REFUSING: extension audit does not explicitly say detector_run=False."
    )

checkpoint = (
    ext_audit
    .get("extension", {})
    .get("checkpoint", {})
)

if checkpoint != {"succeeded": 9}:
    raise SystemExit(
        f"REFUSING: extension checkpoint not 9/9 succeeded: {checkpoint}"
    )


# ======================================================================
# 2. Re-run full test tree.
# ======================================================================

print()
print("=" * 100)
print("FULL TEST TREE")
print("=" * 100)

test = subprocess.run(
    [
        str(PYTHON),
        "-m",
        "pytest",
        "-q",
        str(ROOT / "tests"),
    ],
    cwd=ROOT,
)

if test.returncode != 0:
    raise SystemExit(
        "REFUSING: full test tree failed."
    )


# ======================================================================
# 3. Re-verify evidence.
# ======================================================================

print()
print("=" * 100)
print("DIRECT EVIDENCE VERIFICATION")
print("=" * 100)

verify = subprocess.run(
    [
        str(CLI),
        "verify-evidence",
        "--root",
        str(ROOT / "evidence"),
    ],
    cwd=ROOT,
    capture_output=True,
    text=True,
)

print(verify.stdout)

if verify.stderr:
    print(verify.stderr)

if verify.returncode != 0:
    raise SystemExit(
        "REFUSING: evidence verification command failed."
    )

try:
    evidence_summary = json.loads(
        verify.stdout
    )
except Exception as exc:
    raise SystemExit(
        f"REFUSING: could not parse evidence verification: {exc}"
    )

if evidence_summary.get("errors") != 0:
    raise SystemExit(
        f"REFUSING: evidence verification errors: {evidence_summary}"
    )

if evidence_summary.get("verified_artifacts") != 478:
    raise SystemExit(
        "REFUSING: expected exactly 478 verified evidence artifacts; "
        f"got {evidence_summary.get('verified_artifacts')}"
    )


# ======================================================================
# 4. Authoritative 40-exposure denominator.
# ======================================================================

prod_rows = load_csv(PRODUCTION)

if len(prod_rows) != 74:
    raise SystemExit(
        f"REFUSING: production queue rows={len(prod_rows)}, expected 74."
    )

queue_usage = defaultdict(list)

for row in prod_rows:
    for pid in poss_ids(row):
        queue_usage[pid].append(row)

queue_ids = set(queue_usage)

poss_involving_rows = sum(
    1
    for row in prod_rows
    if poss_ids(row)
)

if poss_involving_rows != 47:
    raise SystemExit(
        f"REFUSING: POSS-involving rows={poss_involving_rows}, expected 47."
    )

if len(queue_ids) != 40:
    raise SystemExit(
        f"REFUSING: unique POSS IDs={len(queue_ids)}, expected 40."
    )


# ======================================================================
# 5. Combine immutable v0.2.7 31 + v0.2.8 extension 9.
# ======================================================================

old_rows = load_csv(V027_RESULT)
new_rows = load_csv(EXT_RESULT)

if len(old_rows) != 31:
    raise SystemExit(
        f"REFUSING: v0.2.7 identity rows={len(old_rows)}, expected 31."
    )

if len(new_rows) != 9:
    raise SystemExit(
        f"REFUSING: extension rows={len(new_rows)}, expected 9."
    )

old_by_id = {
    exposure_id(row): row
    for row in old_rows
}

new_by_id = {
    exposure_id(row): row
    for row in new_rows
}

if "" in old_by_id or "" in new_by_id:
    raise SystemExit(
        "REFUSING: blank exposure ID in identity result."
    )

if len(old_by_id) != 31:
    raise SystemExit(
        "REFUSING: duplicate exposure IDs in v0.2.7 result."
    )

if len(new_by_id) != 9:
    raise SystemExit(
        "REFUSING: duplicate exposure IDs in extension result."
    )

overlap = set(old_by_id) & set(new_by_id)

if overlap:
    raise SystemExit(
        f"REFUSING: old/new identity results overlap: {sorted(overlap)}"
    )

combined_ids = set(old_by_id) | set(new_by_id)

if combined_ids != queue_ids:
    raise SystemExit(
        "REFUSING: combined 31+9 identity IDs do not exactly equal "
        "the 40-ID authoritative production denominator.\n"
        f"missing={sorted(queue_ids - combined_ids)}\n"
        f"extra={sorted(combined_ids - queue_ids)}"
    )


# ======================================================================
# 6. Construct publication-clean full40 table.
# ======================================================================

all_columns = []

for row in old_rows + new_rows:
    for key in row:
        if key not in all_columns:
            all_columns.append(key)

extra_columns = [
    "identity_freeze_version",
    "identity_stage_origin",
    "science_publication_cohorts",
    "queue_canonical_orders",
    "queue_legacy_ranks",
    "queue_pair_keys",
]

for key in extra_columns:
    if key not in all_columns:
        all_columns.append(key)

combined_rows = []

for pid in sorted(queue_ids):
    if pid in old_by_id:
        row = dict(old_by_id[pid])
        origin = "v0.2.7_prospective_identity_freeze"
    else:
        row = dict(new_by_id[pid])
        origin = "v0.2.8_development_revalidation_extension"

    uses = sorted(
        queue_usage[pid],
        key=lambda r: int(float(r["canonical_order"])),
    )

    science_cohorts = sorted({
        str(r.get("publication_cohort") or "")
        for r in uses
    })

    canonical_orders = [
        str(int(float(r["canonical_order"])))
        for r in uses
    ]

    legacy_ranks = sorted({
        str(r.get("legacy_rank") or "")
        for r in uses
        if str(r.get("legacy_rank") or "")
    })

    pair_keys = [
        str(r.get("pair_key") or "")
        for r in uses
    ]

    row["identity_freeze_version"] = VERSION
    row["identity_stage_origin"] = origin

    row["science_publication_cohorts"] = ";".join(
        science_cohorts
    )

    row["queue_canonical_orders"] = ";".join(
        canonical_orders
    )

    row["queue_legacy_ranks"] = ";".join(
        legacy_ranks
    )

    row["queue_pair_keys"] = " || ".join(
        pair_keys
    )

    combined_rows.append(row)


FULL40_RESULT.parent.mkdir(
    parents=True,
    exist_ok=True,
)

with FULL40_RESULT.open(
    "w",
    encoding="utf-8",
    newline="",
) as fh:
    writer = csv.DictWriter(
        fh,
        fieldnames=all_columns,
        extrasaction="raise",
    )

    writer.writeheader()

    for row in combined_rows:
        writer.writerow({
            key: row.get(key, "")
            for key in all_columns
        })


# ======================================================================
# 7. Scientific accounting.
# ======================================================================

status_counts = Counter(
    str(row.get("identity_status") or "")
    for row in combined_rows
)

expected_status_counts = {
    "validated": 37,
    "catalogue_identified_pixels_unavailable": 3,
}

if dict(status_counts) != expected_status_counts:
    raise SystemExit(
        "REFUSING: unexpected full40 identity accounting: "
        f"{dict(status_counts)}"
    )

unavailable = {
    exposure_id(row):
        str(row.get("finder_region") or "")
    for row in combined_rows
    if (
        row.get("identity_status")
        == "catalogue_identified_pixels_unavailable"
    )
}

if unavailable != EXPECTED_UNAVAILABLE:
    raise SystemExit(
        "REFUSING: unavailable set changed.\n"
        f"actual={unavailable}\n"
        f"expected={EXPECTED_UNAVAILABLE}"
    )

for row in combined_rows:
    status = row.get("identity_status")
    eligible = row.get("eligible_for_science")

    if status == "validated":
        if str(eligible).strip() and not is_true(eligible):
            raise SystemExit(
                f"REFUSING: validated row is detector-ineligible: "
                f"{exposure_id(row)}"
            )

    elif (
        status
        == "catalogue_identified_pixels_unavailable"
    ):
        if is_true(eligible):
            raise SystemExit(
                f"REFUSING: pixels-unavailable row marked eligible: "
                f"{exposure_id(row)}"
            )

    else:
        raise SystemExit(
            f"REFUSING: unexpected identity status "
            f"{status!r} for {exposure_id(row)}"
        )


# ======================================================================
# 8. Ensure extension DB itself is exactly 9 succeeded jobs.
# ======================================================================

con = sqlite3.connect(
    f"file:{EXT_DB.resolve()}?mode=ro",
    uri=True,
)

integrity = [
    str(x[0])
    for x in con.execute(
        "PRAGMA integrity_check"
    ).fetchall()
]

if integrity != ["ok"]:
    raise SystemExit(
        f"REFUSING: extension SQLite integrity failed: {integrity}"
    )

db_counts = dict(
    con.execute(
        """
        SELECT status,COUNT(*)
        FROM jobs
        WHERE stage='poss1-identity:identity_extension_v028'
        GROUP BY status
        """
    ).fetchall()
)

db_keys = {
    str(x[0])
    for x in con.execute(
        """
        SELECT job_key
        FROM jobs
        WHERE stage='poss1-identity:identity_extension_v028'
        """
    ).fetchall()
}

con.close()

if db_counts != {"succeeded": 9}:
    raise SystemExit(
        f"REFUSING: extension DB accounting changed: {db_counts}"
    )

if db_keys != set(new_by_id):
    raise SystemExit(
        "REFUSING: extension DB job IDs differ from exported nine."
    )


# ======================================================================
# 9. Build complete evidence hash manifest.
# ======================================================================

print()
print("=" * 100)
print("BUILDING EVIDENCE HASH MANIFEST")
print("=" * 100)

evidence_root = ROOT / "evidence"

evidence_files = sorted(
    path
    for path in evidence_root.rglob("*")
    if path.is_file()
)

evidence_manifest = []

for path in evidence_files:
    evidence_manifest.append({
        "path":
            str(path.relative_to(ROOT)).replace("\\", "/"),
        "bytes":
            path.stat().st_size,
        "sha256":
            sha256_file(path),
    })

print(
    "Evidence files hashed:",
    len(evidence_manifest),
)


# ======================================================================
# 10. Create fresh v0.2.8 snapshot.
# ======================================================================

if FREEZE.exists():
    raise SystemExit(
        f"REFUSING: v0.2.8 freeze directory already exists: {FREEZE}"
    )

FREEZE.mkdir(
    parents=True,
    exist_ok=False,
)

files = []

files.append(
    copy_file(
        FULL40_RESULT,
        "results/poss1_identity_full40_v028.csv",
    )
)

files.append(
    copy_file(
        V027_RESULT,
        "provenance/v027/poss1_identity_preflight.csv",
    )
)

files.append(
    copy_file(
        EXT_RESULT,
        "provenance/v028_extension/poss1_identity_extension_v028.csv",
    )
)

files.append(
    copy_file(
        EXT_QUEUE,
        "provenance/v028_extension/poss1_identity_extension_v028_nine_queue.csv",
    )
)

files.append(
    copy_file(
        EXT_AUDIT,
        "provenance/v028_extension/POSS1_V028_NINE_IDENTITY_EXTENSION_AUDIT_2026-08-21.json",
    )
)

files.append(
    sqlite_snapshot(
        EXT_DB,
        "provenance/v028_extension/poss1_identity_extension_v028.sqlite",
    )
)

files.append(
    copy_file(
        SEMANTIC_AUDIT,
        "provenance/v027/POSS1_V027_LIVE_VS_FROZEN_SQLITE_SEMANTIC_AUDIT_2026-08-21.json",
    )
)

files.append(
    copy_file(
        V027_MANIFEST,
        "provenance/v027/freeze_manifest.json",
    )
)

files.append(
    copy_file(
        PRODUCTION,
        "inputs/research/production_sub5_queue_2026-08-20.csv",
    )
)

files.append(
    copy_file(
        CANONICAL,
        "inputs/research/canonical_sub5_pairs_74.csv",
    )
)

files.append(
    copy_file(
        SKY,
        "source/src/transient_pipeline/poss1_skyview.py",
    )
)

files.append(
    copy_file(
        POSS,
        "source/src/transient_pipeline/poss1.py",
    )
)

files.append(
    copy_file(
        CONFIG,
        "source/config/frozen_method.json",
    )
)

files.append(
    copy_file(
        RUN_SCRIPT,
        "source/tools/run_v028_nine_identity_extension.py",
    )
)


# Copy current tests for reproducibility.
tests_root = ROOT / "tests"

for src in sorted(
    p
    for p in tests_root.rglob("*.py")
    if p.is_file()
):
    rel = src.relative_to(ROOT)

    files.append(
        copy_file(
            src,
            "source/" + str(rel).replace("\\", "/"),
        )
    )


# pip freeze
pip = subprocess.run(
    [
        str(PYTHON),
        "-m",
        "pip",
        "freeze",
    ],
    cwd=ROOT,
    capture_output=True,
    text=True,
)

if pip.returncode != 0:
    raise SystemExit(
        "REFUSING: pip freeze failed."
    )

pip_path = FREEZE / "environment" / "pip_freeze.txt"

pip_path.parent.mkdir(
    parents=True,
    exist_ok=True,
)

pip_path.write_text(
    pip.stdout,
    encoding="utf-8",
)

files.append({
    "source":
        "<generated>",
    "snapshot_path":
        "environment/pip_freeze.txt",
    "bytes":
        pip_path.stat().st_size,
    "sha256":
        sha256_file(pip_path),
})


# Evidence manifest itself.
evidence_manifest_path = (
    FREEZE
    / "evidence"
    / "evidence_manifest.json"
)

evidence_manifest_path.parent.mkdir(
    parents=True,
    exist_ok=True,
)

evidence_manifest_path.write_text(
    json.dumps(
        {
            "verified_artifacts":
                evidence_summary["verified_artifacts"],
            "verification_errors":
                evidence_summary["errors"],
            "filesystem_file_count":
                len(evidence_manifest),
            "files":
                evidence_manifest,
        },
        indent=2,
        sort_keys=True,
    ) + "\n",
    encoding="utf-8",
)

files.append({
    "source":
        "evidence/**",
    "snapshot_path":
        "evidence/evidence_manifest.json",
    "bytes":
        evidence_manifest_path.stat().st_size,
    "sha256":
        sha256_file(evidence_manifest_path),
})


# ======================================================================
# 11. Deterministic snapshot identity / manifest.
# ======================================================================

core = {
    "snapshot_format": 1,
    "version": VERSION,
    "date": DATE,
    "purpose":
        "complete POSS-I physical-plate identity and digital-pixel "
        "availability freeze for all 40 unique POSS exposures in the "
        "authoritative 74-pair <=5-minute production denominator",

    "authoritative_denominator": {
        "production_queue_sha256":
            sha256_file(PRODUCTION),
        "rows":
            74,
        "poss_involving_rows":
            47,
        "unique_poss_exposures":
            40,
    },

    "identity_accounting": {
        "validated_detector_eligible":
            37,
        "catalogue_identified_pixels_unavailable":
            3,
        "execution_failures":
            0,
        "unavailable":
            EXPECTED_UNAVAILABLE,
    },

    "lineage": {
        "v027_snapshot_id":
            EXPECTED_V027_SNAPSHOT_ID,
        "v027_manifest_sha256":
            EXPECTED_V027_MANIFEST_SHA,
        "v027_identity_rows":
            31,
        "v028_extension_rows":
            9,
    },

    "evidence": {
        "verified_artifacts":
            evidence_summary["verified_artifacts"],
        "verification_errors":
            evidence_summary["errors"],
        "evidence_manifest_sha256":
            sha256_file(evidence_manifest_path),
    },

    "detector_run":
        False,

    "files":
        sorted(
            files,
            key=lambda x: x["snapshot_path"],
        ),
}

snapshot_id = hashlib.sha256(
    json.dumps(
        core,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
).hexdigest()

manifest = {
    **core,
    "created_at_utc":
        datetime.now(timezone.utc).isoformat(),
    "project_root_at_capture":
        str(ROOT),
    "snapshot_id":
        snapshot_id,
}

manifest_path = FREEZE / "freeze_manifest.json"

manifest_path.write_text(
    json.dumps(
        manifest,
        indent=2,
        sort_keys=True,
    ) + "\n",
    encoding="utf-8",
)

manifest_sha = sha256_file(
    manifest_path
)


# ======================================================================
# 12. Closure note.
# ======================================================================

closure = f"""# POSS-I identity / availability closure — v0.2.8

Date: {DATE}

## Scope

This freeze closes physical-plate identity and digital-pixel availability
for **all 40 unique POSS-I physical exposures** appearing in the
authoritative 74-row <=5-minute production denominator.

The authoritative production queue is:

`research/production_sub5_queue_2026-08-20.csv`

SHA256:

`{sha256_file(PRODUCTION)}`

## Accounting

- authoritative temporal pairs: **74**
- POSS-involving pair rows: **47**
- unique POSS physical exposures: **40**
- physical identity validated / detector-eligible: **37**
- catalogue identified but digital pixels unavailable: **3**
- identity execution failures: **0**

## Pixels unavailable

1. `POSS-I:449:O:rec198` -> `XO197`
2. `POSS-I:832:E:rec760` -> `XE760`
3. `POSS-I:988:O:rec207` -> `XO206`

These three remain part of the denominator. Archive/pixel unavailability is
**not** a scientific zero or non-detection.

## Lineage

The v0.2.7 identity freeze remains immutable:

`{EXPECTED_V027_SNAPSHOT_ID}`

It accounts for 31 physical POSS exposures.

v0.2.8 adds the nine previously omitted development-revalidation exposures
under the same reviewed physical-identity policy. All nine jobs completed;
eight were validated and O988/rec207 was catalogue identified with pixels
unavailable.

The authoritative science cohort labels were not altered.

## Duplicate POSS number 1023

The two physical O-band records remain distinct:

- `POSS-I:1023:O:rec675` -> `XO674`
- `POSS-I:1023:O:rec799` -> `XO799`

No bare `POSS-I:1023:O` identity is publication-safe.

## Evidence

Evidence verification at freeze:

- verified artifacts: **{evidence_summary["verified_artifacts"]}**
- errors: **{evidence_summary["errors"]}**

## Detector

**No transient detector was run as part of this identity freeze.**

The next gate is pixel/FITS provenance reconciliation against these frozen
physical identities. Old exploratory detector dispositions must not be
silently promoted unless their exact physical plate and pixel provenance
matches this freeze.

Snapshot ID:

`{snapshot_id}`

Manifest SHA256:

`{manifest_sha}`
"""

CLOSURE.write_text(
    closure,
    encoding="utf-8",
)

shutil.copy2(
    CLOSURE,
    FREEZE / "POSS1_IDENTITY_PREFLIGHT_V028_FULL40_CLOSURE_2026-08-21.md",
)


# ======================================================================
# 13. Final independent reread of combined result.
# ======================================================================

check = load_csv(
    FREEZE
    / "results"
    / "poss1_identity_full40_v028.csv"
)

if len(check) != 40:
    raise SystemExit(
        "REFUSING: frozen full40 CSV did not reread as 40 rows."
    )

check_status = Counter(
    row["identity_status"]
    for row in check
)

if dict(check_status) != expected_status_counts:
    raise SystemExit(
        "REFUSING: frozen full40 CSV accounting changed on reread."
    )


print()
print("=" * 100)
print("PUBLICATION FREEZE v0.2.8 PASSED")
print("=" * 100)

print("Snapshot:", FREEZE)
print("Snapshot ID:", snapshot_id)
print("Manifest SHA256:", manifest_sha)
print("Closure:", CLOSURE)

print()
print("Final full-40 accounting:")
print("  unique POSS physical exposures:              40")
print("  validated / detector-eligible:                37")
print("  catalogue-identified pixels unavailable:       3")
print("  identity execution failures:                   0")
print(
    "  evidence artifacts verified:                ",
    evidence_summary["verified_artifacts"],
)
print(
    "  evidence errors:                              ",
    evidence_summary["errors"],
)

print()
print("Unavailable:")
for pid, region in EXPECTED_UNAVAILABLE.items():
    print(f"  {pid} -> {region}")

print()
print("No transient detector was run.")
print("FULL 40/40 POSS-I IDENTITY BOUNDARY IS NOW FROZEN.")
print()
print(
    "NEXT: reconcile existing pixel/FITS products against "
    "the frozen physical identities before detector execution."
)
