from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
import csv
import hashlib
import json
import re
import shutil
import sqlite3
import subprocess
import sys


ROOT = Path.cwd()

VERSION = "0.2.7"
DATE = "2026-08-21"

STAGE = "poss1-identity:prospective_production"

SKY = ROOT / "src" / "transient_pipeline" / "poss1_skyview.py"
POSS = ROOT / "src" / "transient_pipeline" / "poss1.py"
WRAPPER = ROOT / "run_poss1_identity_preflight.ps1"
RESULT = ROOT / "results" / "poss1_identity_preflight.csv"
DB = ROOT / "state" / "poss1_identity_prospective.sqlite"
EVIDENCE = ROOT / "evidence"

PYTHON = ROOT / ".venv" / "Scripts" / "python.exe"
CLI = ROOT / ".venv" / "Scripts" / "transient-pipeline.exe"

FREEZE = (
    ROOT
    / "research_snapshots"
    / f"poss1_identity_freeze_v{VERSION}_{DATE}"
)

NOTE = (
    ROOT
    / "research"
    / f"POSS1_IDENTITY_PREFLIGHT_V027_CLOSURE_{DATE}.md"
)

EXPECTED_HASHES = {
    "src/transient_pipeline/poss1_skyview.py":
        "22470c1956e6b0ddb885d51092aa0a30dd322bfc1d48c6b49bcd0ed3620a732e",
    "src/transient_pipeline/poss1.py":
        "6161a74d5ce76f70235c66a748077b3517f7d2d7946e9f48998927c331374ac7",
    "run_poss1_identity_preflight.ps1":
        "70ae2a0d62b5d2bdaffe74b512cee0ff161d9900d8afc933b574a57f3906b606",
}

EXPECTED_UNAVAILABLE = {
    "POSS-I:449:O:rec198": {
        "finder_region": "XO197",
        "vi25_mlp": "198",
        "identity_source":
            "vi25_plus_primary_stsci_failure_and_skyview_gap",
        "skyview_descriptor_image_count": "0",
        "archive_failure_kind": "",
        "skyview_raw_hhh_url": "",
    },
    "POSS-I:832:E:rec760": {
        "finder_region": "XE760",
        "vi25_mlp": "761",
        "identity_source":
            "vi25_plus_primary_stsci_failure_and_skyview_descriptor_raw_hhh_gap",
        "skyview_descriptor_image_count": "1",
        "archive_failure_kind": "skyview_raw_hhh_http_404",
        "skyview_raw_hhh_url":
            "https://skyview.gsfc.nasa.gov/surveys/dss/xe760/xe760.hhh",
    },
}


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def rel(path: Path) -> str:
    return str(path.relative_to(ROOT)).replace("\\", "/")


def require_file(path: Path) -> None:
    if not path.is_file():
        raise SystemExit(f"REFUSING: required file missing: {path}")


def boolish(value: object) -> bool:
    return str(value or "").strip().lower() in {"true", "1", "yes"}


def copy_preserving_root(src: Path) -> Path:
    src = src.resolve()
    root = ROOT.resolve()

    try:
        relative = src.relative_to(root)
    except ValueError:
        raise SystemExit(
            f"REFUSING: attempted snapshot of file outside project root: {src}"
        )

    dst = FREEZE / "inputs" / relative
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    return dst


def run_checked(args, *, label: str) -> subprocess.CompletedProcess:
    print()
    print("=" * 92)
    print(label)
    print("=" * 92)

    cp = subprocess.run(
        [str(x) for x in args],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )

    if cp.stdout:
        print(cp.stdout, end="" if cp.stdout.endswith("\n") else "\n")
    if cp.stderr:
        print(cp.stderr, end="" if cp.stderr.endswith("\n") else "\n")

    if cp.returncode != 0:
        raise SystemExit(
            f"{label} FAILED with exit code {cp.returncode}. "
            "No freeze snapshot was created."
        )

    return cp


print("=" * 92)
print("POSS-I v0.2.7 IDENTITY / AVAILABILITY PUBLICATION FREEZE")
print("=" * 92)
print("No transient detector is executed by this program.")

for p in (SKY, POSS, WRAPPER, RESULT, DB, PYTHON, CLI):
    require_file(p)

if not EVIDENCE.is_dir():
    raise SystemExit(f"REFUSING: evidence directory missing: {EVIDENCE}")

if FREEZE.exists():
    raise SystemExit(
        f"REFUSING: freeze destination already exists: {FREEZE}"
    )

# ----------------------------------------------------------------------
# 1. Exact final source identity.
# ----------------------------------------------------------------------

print()
print("FINAL SOURCE HASH GUARDS")
print("-" * 92)

for relative, expected in EXPECTED_HASHES.items():
    path = ROOT / relative
    actual = sha256_file(path)
    print(relative)
    print("  expected:", expected)
    print("  actual:  ", actual)

    if actual != expected:
        raise SystemExit(
            f"REFUSING: {relative} changed after reviewed v0.2.7 validation."
        )

# ----------------------------------------------------------------------
# 2. Full live Python test tree.
# ----------------------------------------------------------------------

pytest_cp = run_checked(
    [PYTHON, "-m", "pytest", "-q", ROOT / "tests"],
    label="FULL LIVE TEST TREE",
)

m = re.search(r"(\d+)\s+passed", pytest_cp.stdout)

if not m:
    raise SystemExit("REFUSING: could not establish pytest pass count.")

test_count = int(m.group(1))

if test_count != 50:
    raise SystemExit(
        f"REFUSING: expected frozen 50-test suite, got {test_count} passed."
    )

# ----------------------------------------------------------------------
# 3. PowerShell parser check.
# ----------------------------------------------------------------------

parser_command = r'''
$tokens = $null
$errors = $null

[System.Management.Automation.Language.Parser]::ParseFile(
    (Resolve-Path ".\run_poss1_identity_preflight.ps1"),
    [ref]$tokens,
    [ref]$errors
) | Out-Null

if ($errors.Count -gt 0) {
    $errors | Format-List *
    exit 1
}

Write-Output "PowerShell parser: PASS"
'''

parser_cp = run_checked(
    [
        "powershell.exe",
        "-NoProfile",
        "-ExecutionPolicy", "Bypass",
        "-Command", parser_command,
    ],
    label="PREFLIGHT WRAPPER POWERSHELL PARSER",
)

# ----------------------------------------------------------------------
# 4. Run the completed preflight again.
#
#    All 31 jobs are already completed, so this validates accounting and
#    evidence without executing a transient detector.
# ----------------------------------------------------------------------

preflight_cp = run_checked(
    [
        "powershell.exe",
        "-NoProfile",
        "-ExecutionPolicy", "Bypass",
        "-File", WRAPPER,
    ],
    label="FINAL IDENTITY / AVAILABILITY PREFLIGHT",
)

required_preflight_text = (
    "succeeded=31",
    "POSS-I IDENTITY/AVAILABILITY PREFLIGHT ACCOUNTED: 31/31 exposures.",
    "pixel-validated / detector-eligible: 29",
    "catalogue-identified but digital pixels unavailable: 2",
    "No transient detector was run.",
)

for needle in required_preflight_text:
    if needle not in preflight_cp.stdout:
        raise SystemExit(
            f"REFUSING: final preflight output missing expected statement: "
            f"{needle!r}"
        )

# ----------------------------------------------------------------------
# 5. Verify checkpoint database independently.
# ----------------------------------------------------------------------

con = sqlite3.connect(DB)
con.row_factory = sqlite3.Row

db_counts = dict(
    con.execute(
        """
        SELECT status, COUNT(*)
        FROM jobs
        WHERE stage=?
        GROUP BY status
        ORDER BY status
        """,
        (STAGE,),
    ).fetchall()
)

if db_counts != {"succeeded": 31}:
    con.close()
    raise SystemExit(
        "REFUSING: final database checkpoint is not exactly "
        f"31 succeeded: {db_counts}"
    )

db_rows = con.execute(
    """
    SELECT job_key,status,attempts,last_error
    FROM jobs
    WHERE stage=?
    ORDER BY job_key
    """,
    (STAGE,),
).fetchall()

if len(db_rows) != 31:
    con.close()
    raise SystemExit(
        f"REFUSING: expected 31 stage rows in checkpoint, got {len(db_rows)}"
    )

# ----------------------------------------------------------------------
# 6. Independently validate result CSV.
# ----------------------------------------------------------------------

with RESULT.open("r", encoding="utf-8-sig", newline="") as fh:
    rows = list(csv.DictReader(fh))

if len(rows) != 31:
    con.close()
    raise SystemExit(
        f"REFUSING: result CSV contains {len(rows)} rows, expected 31."
    )

if any(r.get("status") != "succeeded" for r in rows):
    con.close()
    raise SystemExit("REFUSING: result CSV contains a non-succeeded row.")

status_counts = Counter(r.get("identity_status", "") for r in rows)

expected_status_counts = {
    "validated": 29,
    "catalogue_identified_pixels_unavailable": 2,
}

if dict(status_counts) != expected_status_counts:
    con.close()
    raise SystemExit(
        "REFUSING: identity-status accounting changed:\n"
        + json.dumps(dict(status_counts), indent=2, sort_keys=True)
    )

validated = [
    r for r in rows
    if r.get("identity_status") == "validated"
]

if any(not boolish(r.get("eligible_for_science")) for r in validated):
    con.close()
    raise SystemExit(
        "REFUSING: a pixel-validated exposure is no longer science eligible."
    )

unavailable = {
    r["exposure_id"]: r
    for r in rows
    if r.get("identity_status")
    == "catalogue_identified_pixels_unavailable"
}

if set(unavailable) != set(EXPECTED_UNAVAILABLE):
    con.close()
    raise SystemExit(
        "REFUSING: exact archive-unavailable identity set changed:\n"
        + json.dumps(sorted(unavailable), indent=2)
    )

for exposure_id, expected in EXPECTED_UNAVAILABLE.items():
    row = unavailable[exposure_id]

    if boolish(row.get("eligible_for_science")):
        con.close()
        raise SystemExit(
            f"REFUSING: unavailable exposure became science eligible: "
            f"{exposure_id}"
        )

    if row.get("archive_availability_status") != "digital_pixels_unavailable":
        con.close()
        raise SystemExit(
            f"REFUSING: availability status changed for {exposure_id}"
        )

    for key, expected_value in expected.items():
        actual = str(row.get(key) or "")
        if actual != expected_value:
            con.close()
            raise SystemExit(
                f"REFUSING: {exposure_id} {key} mismatch:\n"
                f"Expected: {expected_value!r}\n"
                f"Actual:   {actual!r}"
            )

source_counts = Counter(str(r.get("identity_source") or "") for r in rows)

expected_source_counts = {
    "": 25,
    "skyview_raw_fallback": 4,
    "vi25_plus_primary_stsci_failure_and_skyview_gap": 1,
    "vi25_plus_primary_stsci_failure_and_skyview_descriptor_raw_hhh_gap": 1,
}

if dict(source_counts) != expected_source_counts:
    con.close()
    raise SystemExit(
        "REFUSING: identity-source composition changed:\n"
        + json.dumps(dict(source_counts), indent=2, sort_keys=True)
    )

# ----------------------------------------------------------------------
# 7. Verify evidence again directly and retain its output.
# ----------------------------------------------------------------------

evidence_cp = run_checked(
    [CLI, "verify-evidence", "--root", EVIDENCE],
    label="DIRECT EVIDENCE VERIFICATION",
)

try:
    evidence_summary = json.loads(evidence_cp.stdout)
except Exception:
    con.close()
    raise SystemExit(
        "REFUSING: verify-evidence did not return parseable JSON."
    )

if evidence_summary.get("errors") != 0:
    con.close()
    raise SystemExit(
        f"REFUSING: evidence verification errors: {evidence_summary}"
    )

if evidence_summary.get("verified_artifacts") != 447:
    con.close()
    raise SystemExit(
        "REFUSING: evidence artifact count changed: "
        f"{evidence_summary.get('verified_artifacts')} != 447"
    )

# ----------------------------------------------------------------------
# 8. Everything is validated. Only now create freeze destination.
# ----------------------------------------------------------------------

FREEZE.mkdir(parents=True)

# Consistent SQLite snapshot.
db_snapshot = FREEZE / "inputs" / "state" / DB.name
db_snapshot.parent.mkdir(parents=True, exist_ok=True)

dst_con = sqlite3.connect(db_snapshot)
con.backup(dst_con)
dst_con.close()
con.close()

# ----------------------------------------------------------------------
# 9. Core reproducibility inputs.
# ----------------------------------------------------------------------

core_files = [
    SKY,
    POSS,
    ROOT / "src" / "transient_pipeline" / "__init__.py",
    WRAPPER,
    RESULT,
    ROOT / "research" / "poss1_plate_metadata.csv",
    ROOT / "research" / "production_sub5_queue_2026-08-20.csv",
    ROOT / "config" / "frozen_method.json",

    ROOT / "tests" / "test_poss1_v027_identity_policy.py",
    ROOT / "tests" / "test_poss1_v027_hhh_date_policy.py",
    ROOT / "tests" / "test_poss1_v026_nonresolution_fallback.py",
    ROOT / "tests" / "test_poss1_skyview.py",
    ROOT / "tests" / "test_poss1_skyview_v024.py",

    ROOT / "tools" / "requeue_v027_five_identity_jobs.py",
    ROOT / "tools" / "requeue_v027_hhh_date_four_jobs.py",
    ROOT / "tools" / "recover_v027_hhh_date_patch_atomic.py",
    ROOT / "tools" / "patch_v027_preflight_archive_guard.py",
]

for path in core_files:
    if path.exists():
        copy_preserving_root(path)

# Include v0.2.7 audit records.
for path in sorted((ROOT / "research").glob("POSS1_V027_*.json")):
    copy_preserving_root(path)

# Include centre-gate empirical diagnostic if still present.
centre_diag = (
    ROOT
    / "work"
    / "poss_preflight"
    / "descriptor_hhh_gate_diagnostic_v026"
    / "descriptor_hhh_gate_diagnostic_report.json"
)

if centre_diag.exists():
    copy_preserving_root(centre_diag)

# Include only provenance sidecars actually referenced by final result rows.
referenced_sidecars = set()

for row in rows:
    for column in (
        "provenance_sidecar",
        "archive_unavailable_provenance_sidecar",
    ):
        raw = str(row.get(column) or "").strip()

        if not raw:
            continue

        sidecar = ROOT / Path(raw)

        if not sidecar.is_file():
            raise SystemExit(
                f"REFUSING: result references missing provenance sidecar: "
                f"{sidecar}"
            )

        referenced_sidecars.add(sidecar)

for path in sorted(referenced_sidecars, key=lambda p: str(p)):
    copy_preserving_root(path)

# ----------------------------------------------------------------------
# 10. Freeze validation transcripts.
# ----------------------------------------------------------------------

validation_dir = FREEZE / "validation"
validation_dir.mkdir(parents=True, exist_ok=True)

(validation_dir / "pytest.txt").write_text(
    pytest_cp.stdout + pytest_cp.stderr,
    encoding="utf-8",
)

(validation_dir / "wrapper_parser.txt").write_text(
    parser_cp.stdout + parser_cp.stderr,
    encoding="utf-8",
)

(validation_dir / "identity_preflight.txt").write_text(
    preflight_cp.stdout + preflight_cp.stderr,
    encoding="utf-8",
)

(validation_dir / "verify_evidence.txt").write_text(
    evidence_cp.stdout + evidence_cp.stderr,
    encoding="utf-8",
)

# ----------------------------------------------------------------------
# 11. Hash every current evidence-store file.
#
#     We deliberately manifest rather than duplicate the potentially-large
#     content-addressed evidence store.
# ----------------------------------------------------------------------

evidence_files = []

for path in sorted(EVIDENCE.rglob("*")):
    if not path.is_file():
        continue

    evidence_files.append({
        "path": rel(path),
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    })

evidence_manifest_path = FREEZE / "evidence_manifest.json"

evidence_manifest_path.write_text(
    json.dumps(
        {
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
            "verified_artifacts": evidence_summary["verified_artifacts"],
            "verification_errors": evidence_summary["errors"],
            "files": evidence_files,
        },
        indent=2,
        sort_keys=True,
    ) + "\n",
    encoding="utf-8",
)

# ----------------------------------------------------------------------
# 12. Publication/methodological closure note.
# ----------------------------------------------------------------------

note_text = f"""# POSS-I identity/availability preflight v0.2.7 closure

**Frozen:** {DATE}  
**Prospective exposures:** 31  
**Pixel-validated / detector-eligible:** 29  
**Catalogue-identified, digital pixels unavailable:** 2  
**Execution failures at freeze:** 0  
**Evidence artifacts verified:** 447  
**Evidence errors:** 0  
**Transient detection performed by this freeze:** No

## Final identity accounting

The prospective POSS-I identity/availability preflight completed with all
31 exposure jobs in `succeeded` state. Twenty-nine exposures have validated
digital plate pixels and are eligible for subsequent detector execution.

Two physical exposures remain in the prospective denominator but are not
detector-eligible because validated digital pixels are unavailable:

1. `POSS-I:449:O:rec198` — deterministic region `XO197`.
   VI/25 identity is retained, but no exact current SkyView DSS1 descriptor
   product exists for the required region.

2. `POSS-I:832:E:rec760` — VI/25 MLP `761`, deterministic region `XE760`.
   The exact `XE760` descriptor entry exists, but the exact raw product
   `https://skyview.gsfc.nasa.gov/surveys/dss/xe760/xe760.hhh`
   returns HTTP 404. No neighbouring region is substituted.

These two exposures are archive-availability states, not scientific
non-detections.

## Corrected DSS-region interpretation

An earlier investigative narrative referred to the second unavailable
exposure as `XE759`. That interpretation was incorrect and is superseded.

The deterministic POSS-I DSS region mapping uses the VI/25 MLP lineage,
not the catalogue `recno` value directly. For
`POSS-I:832:E:rec760`, VI/25 records MLP `761`, yielding deterministic
region `XE760`. The final pipeline result, descriptor path, raw-HHH URL,
and archive-availability provenance are therefore internally consistent.

## Descriptor / raw-header positional policy

An initially proposed descriptor-to-HHH plate-centre equality gate was
empirically rejected. Pixel-equivalent controls demonstrated intrinsic
cross-source centre offsets of at least 357.680 arcsec.

Descriptor/HHH centre separation is therefore retained as diagnostic
provenance but is not a terminal identity criterion. Stronger independent
identity checks remain in force.

Suggested methods wording:

> An initially proposed cross-source positional identity check was
> empirically rejected after pixel-equivalent controls demonstrated
> intrinsic descriptor/header centre offsets of at least 357.7 arcsec.

## VI/25 and GSSS date semantics

VI/25 expresses an exposure within a two-date observing night and records
E/O start clocks in Pacific Standard Time. The historical GSSS raw headers
were empirically found to encode their `DATE-OBS` calendar date using at
least two conventions among pixel-equivalent POSS-I controls:

- the initial observing-night date; or
- the calendar date of the normalized UTC exposure start.

The hard HHH calendar-date identity check therefore admits only those two
independently defined encodings. It does not use a generic +/-1-day
tolerance.

GSSS `DATE-OBS` clock values are retained as provenance but are not used as
minute-accurate exposure-start authority. VI/25-derived normalized UTC
exposure intervals remain authoritative for temporal overlap calculations.

## Regression-fixture correction

The historical XE513 test fixture incorrectly contained E/O clock values
`20:15` / `19:55`. The authoritative VI/25 values are `22:10` / `23:01`.
The regression fixture was corrected before this freeze.

## Detector boundary

No transient detector was run during the identity-remediation or freeze
process.

Subsequent scientific analysis must:

- execute only against the 29 detector-eligible exposures;
- retain XO197 and XE760 in the prospective denominator;
- never treat archive unavailability as a scientific zero;
- calculate and record actual exposure-overlap intervals for every
  cross-observatory candidate pair rather than relying only on midpoint
  separation.
"""

NOTE.write_text(note_text, encoding="utf-8")
copy_preserving_root(NOTE)

# ----------------------------------------------------------------------
# 13. Build immutable snapshot manifest.
# ----------------------------------------------------------------------

snapshot_files = []

for path in sorted(FREEZE.rglob("*")):
    if not path.is_file():
        continue

    if path.name == "freeze_manifest.json":
        continue

    snapshot_files.append({
        "path": str(path.relative_to(FREEZE)).replace("\\", "/"),
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    })

manifest_core = {
    "snapshot_format": 1,
    "version": VERSION,
    "created_at_utc": datetime.now(timezone.utc).isoformat(),
    "project_root_at_capture": str(ROOT.resolve()),
    "stage": STAGE,
    "science_analysis_performed": False,
    "transient_detector_run": False,
    "checkpoint": {
        "succeeded": 31,
    },
    "identity_accounting": {
        "validated_detector_eligible": 29,
        "catalogue_identified_pixels_unavailable": 2,
    },
    "identity_source_counts": expected_source_counts,
    "archive_unavailable": EXPECTED_UNAVAILABLE,
    "evidence_verification": evidence_summary,
    "pytest_passed": test_count,
    "reviewed_source_hashes": EXPECTED_HASHES,
    "referenced_provenance_sidecars": [
        rel(p) for p in sorted(referenced_sidecars, key=lambda p: str(p))
    ],
    "files": snapshot_files,
}

snapshot_id = hashlib.sha256(
    json.dumps(
        manifest_core,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
).hexdigest()

manifest = {
    **manifest_core,
    "snapshot_id": snapshot_id,
}

manifest_path = FREEZE / "freeze_manifest.json"

manifest_path.write_text(
    json.dumps(manifest, indent=2, sort_keys=True) + "\n",
    encoding="utf-8",
)

print()
print("=" * 92)
print("PUBLICATION FREEZE v0.2.7 PASSED")
print("=" * 92)
print("Snapshot:", FREEZE)
print("Snapshot ID:", snapshot_id)
print("Manifest SHA256:", sha256_file(manifest_path))
print("Closure note:", NOTE)
print()
print("Final accounting:")
print("  prospective exposures:                       31")
print("  pixel-validated / detector-eligible:          29")
print("  catalogue-identified pixels unavailable:       2")
print("  execution failures:                            0")
print("  evidence artifacts verified:                 447")
print("  evidence errors:                               0")
print()
print("Unavailable:")
print("  POSS-I:449:O:rec198 -> XO197")
print("  POSS-I:832:E:rec760 -> XE760 (VI/25 MLP 761)")
print()
print("No transient detector was run.")
print("IDENTITY / AVAILABILITY PREFLIGHT IS FROZEN.")
