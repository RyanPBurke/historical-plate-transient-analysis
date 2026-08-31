from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
import csv
import hashlib
import json
import sqlite3
import subprocess
import sys
import time


ROOT = Path.cwd()

QUEUE = ROOT / "research" / "production_sub5_queue_2026-08-20.csv"
VI25 = ROOT / "research" / "poss1_plate_metadata.csv"

V027_FREEZE = (
    ROOT
    / "research_snapshots"
    / "poss1_identity_freeze_v0.2.7_2026-08-21"
)

V027_MANIFEST = V027_FREEZE / "freeze_manifest.json"

V027_DB = ROOT / "state" / "poss1_identity_prospective.sqlite"
V027_RESULT = ROOT / "results" / "poss1_identity_preflight.csv"

V027_FROZEN_DB = (
    V027_FREEZE
    / "inputs"
    / "state"
    / "poss1_identity_prospective.sqlite"
)

V027_FROZEN_RESULT = (
    V027_FREEZE
    / "inputs"
    / "results"
    / "poss1_identity_preflight.csv"
)

V027_DB_SEMANTIC_AUDIT = (
    ROOT
    / "research"
    / "POSS1_V027_LIVE_VS_FROZEN_SQLITE_SEMANTIC_AUDIT_2026-08-21.json"
)

SKY = ROOT / "src" / "transient_pipeline" / "poss1_skyview.py"
POSS = ROOT / "src" / "transient_pipeline" / "poss1.py"

PYTHON = ROOT / ".venv" / "Scripts" / "python.exe"
CLI = ROOT / ".venv" / "Scripts" / "transient-pipeline.exe"

EXT_COHORT = "identity_extension_v028"
EXT_STAGE = f"poss1-identity:{EXT_COHORT}"

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

EXT_DB = (
    ROOT
    / "state"
    / "poss1_identity_extension_v028.sqlite"
)

EXT_RESULT = (
    ROOT
    / "results"
    / "poss1_identity_extension_v028.csv"
)

EXT_CACHE = (
    ROOT
    / "cache"
    / "poss1_identity_v028_extension"
)

EXPECTED_SNAPSHOT_ID = (
    "59c2db6c2c43266bc2af693ff4c6efe1199db409ed912cfa324cadc10793ddb2"
)

EXPECTED_QUEUE_SHA = (
    "b044684fef65437a352edd28eafd21d668640bbec50cd0bc95f92e3529d0d77c"
)

EXPECTED_SKY_SHA = (
    "22470c1956e6b0ddb885d51092aa0a30dd322bfc1d48c6b49bcd0ed3620a732e"
)

EXPECTED_POSS_SHA = (
    "6161a74d5ce76f70235c66a748077b3517f7d2d7946e9f48998927c331374ac7"
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


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def require_file(path: Path) -> None:
    if not path.is_file():
        raise SystemExit(f"REFUSING: required file missing: {path}")


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
        raise ValueError(f"naive timestamp: {value!r}")

    return dt.astimezone(timezone.utc)


def poss_ids(row: dict[str, str]) -> list[str]:
    return [
        value
        for value in (
            str(row.get("exposure_a") or ""),
            str(row.get("exposure_b") or ""),
        )
        if value.startswith("POSS-I:")
    ]


def checkpoint_counts() -> dict[str, int]:
    if not EXT_DB.is_file():
        return {}

    try:
        con = sqlite3.connect(
            EXT_DB,
            timeout=1.0,
        )

        rows = con.execute(
            """
            SELECT status,COUNT(*)
            FROM jobs
            WHERE stage=?
            GROUP BY status
            ORDER BY status
            """,
            (EXT_STAGE,),
        ).fetchall()

        con.close()

        return {
            str(status): int(count)
            for status, count in rows
        }

    except sqlite3.Error:
        return {}


def run_cli_pass(pass_no: int) -> int:
    print()
    print("=" * 96)
    print(f"IDENTITY EXTENSION ARCHIVE PASS {pass_no}")
    print("=" * 96)

    args = [
        str(CLI),
        "--db", str(EXT_DB),
        "poss1-preflight",
        "--queue", str(EXT_QUEUE),
        "--vi25", str(VI25),
        "--cohort", EXT_COHORT,
        "--cache-dir", str(EXT_CACHE),
        "--export", str(EXT_RESULT),
    ]

    proc = subprocess.Popen(
        args,
        cwd=ROOT,
    )

    last_print = 0.0

    while proc.poll() is None:
        now = time.monotonic()

        if now - last_print >= 10.0:
            counts = checkpoint_counts()

            if counts:
                print(
                    "[checkpoint] "
                    + " ".join(
                        f"{k}={v}"
                        for k, v in sorted(counts.items())
                    ),
                    flush=True,
                )

            last_print = now

        time.sleep(1.0)

    return int(proc.returncode or 0)


print("=" * 96)
print("POSS-I v0.2.8 FULL-40 IDENTITY EXTENSION")
print("=" * 96)
print("This workflow resolves ONLY the nine omitted physical POSS exposures.")
print("It does not execute a transient detector.")

for path in (
    QUEUE,
    VI25,
    V027_MANIFEST,
    V027_DB,
    V027_RESULT,
    V027_FROZEN_DB,
    V027_FROZEN_RESULT,
    V027_DB_SEMANTIC_AUDIT,
    SKY,
    POSS,
    PYTHON,
    CLI,
):
    require_file(path)


# ----------------------------------------------------------------------
# 1. Guard the immutable v0.2.7 baseline.
# ----------------------------------------------------------------------

manifest = json.loads(
    V027_MANIFEST.read_text(
        encoding="utf-8",
    )
)

if manifest.get("snapshot_id") != EXPECTED_SNAPSHOT_ID:
    raise SystemExit(
        "REFUSING: v0.2.7 identity snapshot ID changed."
    )

if sha256_file(QUEUE) != EXPECTED_QUEUE_SHA:
    raise SystemExit(
        "REFUSING: authoritative 74-row production queue changed."
    )

if sha256_file(SKY) != EXPECTED_SKY_SHA:
    raise SystemExit(
        "REFUSING: poss1_skyview.py differs from reviewed v0.2.7."
    )

if sha256_file(POSS) != EXPECTED_POSS_SHA:
    raise SystemExit(
        "REFUSING: poss1.py differs from reviewed v0.2.7."
    )

v027_db_before = sha256_file(V027_DB)
v027_result_before = sha256_file(V027_RESULT)

frozen_db_sha = sha256_file(V027_FROZEN_DB)
frozen_result_sha = sha256_file(V027_FROZEN_RESULT)

print()
print("v0.2.7 immutability guards:")
print(" live DB:       ", v027_db_before)
print(" frozen DB:     ", frozen_db_sha)
print(" live result:   ", v027_result_before)
print(" frozen result: ", frozen_result_sha)

db_semantic_audit = json.loads(
    V027_DB_SEMANTIC_AUDIT.read_text(
        encoding="utf-8",
    )
)

if not db_semantic_audit.get(
    "semantic_database_equivalence",
    False,
):
    raise SystemExit(
        "REFUSING: v0.2.7 SQLite semantic-equivalence audit did not pass."
    )

audit_live_sha = (
    db_semantic_audit.get("live", {})
    .get("file_sha256")
)

audit_frozen_sha = (
    db_semantic_audit.get("frozen", {})
    .get("file_sha256")
)

if audit_live_sha != v027_db_before:
    raise SystemExit(
        "REFUSING: current live v0.2.7 DB is not the DB "
        "covered by the semantic-equivalence audit."
    )

if audit_frozen_sha != frozen_db_sha:
    raise SystemExit(
        "REFUSING: current frozen v0.2.7 DB is not the DB "
        "covered by the semantic-equivalence audit."
    )

print(
    " v0.2.7 SQLite semantic equivalence: PASS "
    "(exact audited live/frozen file versions)"
)

if v027_result_before != frozen_result_sha:
    raise SystemExit(
        "REFUSING: live v0.2.7 result differs from frozen copy."
    )


# ----------------------------------------------------------------------
# 2. Full test tree before new archive work.
# ----------------------------------------------------------------------

print()
print("=" * 96)
print("FULL LIVE TEST TREE")
print("=" * 96)

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
        "REFUSING: Python test tree failed."
    )


# ----------------------------------------------------------------------
# 3. Build exact nine-exposure identity-only queue.
#
# Original publication cohort is preserved in a new column.
# We change publication_cohort ONLY in this derived identity queue so the
# existing CLI can assign a separate identity stage. The authoritative
# production queue is never modified.
# ----------------------------------------------------------------------

rows = load_csv(QUEUE)

if len(rows) != 74:
    raise SystemExit(
        f"REFUSING: expected 74 production rows; found {len(rows)}."
    )

usage = defaultdict(list)

for row in rows:
    for pid in poss_ids(row):
        if pid in MISSING:
            usage[pid].append(row)

if set(usage) != MISSING:
    raise SystemExit(
        "REFUSING: exact nine-exposure set not present in authoritative queue."
    )

for pid, matches in usage.items():
    if len(matches) != 1:
        raise SystemExit(
            f"REFUSING: expected exactly one source row for {pid}; "
            f"found {len(matches)}."
        )

selected = []

for pid in sorted(
    MISSING,
    key=lambda p: int(float(
        usage[p][0]["canonical_order"]
    )),
):
    source = dict(usage[pid][0])

    if source.get("publication_cohort") != "development_revalidation":
        raise SystemExit(
            f"REFUSING: {pid} is no longer development_revalidation."
        )

    if str(source.get("pre_freeze_touched") or "").lower() != "true":
        raise SystemExit(
            f"REFUSING: {pid} no longer carries pre_freeze_touched=True."
        )

    # Recompute pair overlap as provenance, without altering timing.
    a0 = parse_utc(source["start_a_utc"])
    a1 = parse_utc(source["end_a_utc"])
    b0 = parse_utc(source["start_b_utc"])
    b1 = parse_utc(source["end_b_utc"])

    overlap_start = max(a0, b0)
    overlap_end = min(a1, b1)
    overlap_s = max(
        0.0,
        (overlap_end - overlap_start).total_seconds(),
    )

    stored_overlap = float(
        source["actual_exposure_overlap_s"]
    )

    if abs(overlap_s - stored_overlap) > 0.01:
        raise SystemExit(
            f"REFUSING: overlap mismatch for {pid}: "
            f"{overlap_s} vs {stored_overlap}"
        )

    if overlap_s <= 0:
        raise SystemExit(
            f"REFUSING: no actual exposure overlap for {pid}."
        )

    source["science_publication_cohort_original"] = (
        source.get("publication_cohort") or ""
    )

    source["identity_extension_v028_reason"] = (
        "physical_plate_identity_required_for_full_74_pair_"
        "experiment_before_reuse_or_rerun_of_development_evidence"
    )

    source["identity_extension_v028_exposure_id"] = pid

    source["identity_extension_v028_overlap_start_utc"] = (
        overlap_start.isoformat()
    )

    source["identity_extension_v028_overlap_end_utc"] = (
        overlap_end.isoformat()
    )

    source["identity_extension_v028_overlap_s"] = (
        f"{overlap_s:.9f}"
    )

    # This is an IDENTITY-stage label only.
    # It does not alter the authoritative science cohort.
    source["publication_cohort"] = EXT_COHORT

    selected.append(source)


if len(selected) != 9:
    raise SystemExit(
        f"REFUSING: expected nine extension rows; got {len(selected)}."
    )


# ----------------------------------------------------------------------
# 4. Confirm the one physical POSS exposure shared across original cohorts.
# ----------------------------------------------------------------------

cohort_poss = defaultdict(set)

for row in rows:
    cohort = str(
        row.get("publication_cohort") or ""
    )

    for pid in poss_ids(row):
        cohort_poss[cohort].add(pid)

shared = (
    cohort_poss["development_revalidation"]
    & cohort_poss["prospective_production"]
)

if len(shared) != 1:
    raise SystemExit(
        "REFUSING: expected exactly one POSS exposure shared across "
        f"the two science cohorts; found {sorted(shared)}."
    )

shared_id = next(iter(shared))

if shared_id in MISSING:
    raise SystemExit(
        "REFUSING: shared cross-cohort identity unexpectedly appears "
        "in the nine-exposure extension set."
    )

print()
print("Cross-cohort physical exposure already covered by v0.2.7:")
print(" ", shared_id)
print("This exposure will NOT be rerun in the extension.")


# ----------------------------------------------------------------------
# 5. Write deterministic extension queue.
# ----------------------------------------------------------------------

EXT_QUEUE.parent.mkdir(
    parents=True,
    exist_ok=True,
)

fieldnames = list(selected[0].keys())

with EXT_QUEUE.open(
    "w",
    encoding="utf-8",
    newline="",
) as fh:
    writer = csv.DictWriter(
        fh,
        fieldnames=fieldnames,
        extrasaction="raise",
    )

    writer.writeheader()
    writer.writerows(selected)

ext_queue_sha = sha256_file(EXT_QUEUE)

print()
print("=" * 96)
print("EXACT NINE-EXPOSURE EXTENSION QUEUE")
print("=" * 96)
print("path:  ", EXT_QUEUE)
print("SHA256:", ext_queue_sha)

for row in selected:
    print(
        f"  order {int(float(row['canonical_order'])):2d} | "
        f"{row['identity_extension_v028_exposure_id']} | "
        f"original_cohort={row['science_publication_cohort_original']} | "
        f"overlap={row['identity_extension_v028_overlap_s']}s"
    )


# ----------------------------------------------------------------------
# 6. Guard/resume extension DB.
#
# New DB is allowed to exist only if it contains no foreign identity stage
# and no unexpected job keys. This permits safe resume after archive/network
# retryable failures.
# ----------------------------------------------------------------------

if EXT_DB.exists():
    con = sqlite3.connect(EXT_DB)

    stages = {
        str(x[0])
        for x in con.execute(
            "SELECT DISTINCT stage FROM jobs"
        ).fetchall()
    }

    keys = {
        str(x[0])
        for x in con.execute(
            "SELECT job_key FROM jobs WHERE stage=?",
            (EXT_STAGE,),
        ).fetchall()
    }

    con.close()

    if stages - {EXT_STAGE}:
        raise SystemExit(
            f"REFUSING: extension DB contains foreign stages: {sorted(stages)}"
        )

    if not keys.issubset(MISSING):
        raise SystemExit(
            "REFUSING: extension DB contains unexpected job keys: "
            f"{sorted(keys - MISSING)}"
        )

    print()
    print("Existing v0.2.8 extension DB found; safe resume permitted.")
    print("Current counts:", checkpoint_counts())


# ----------------------------------------------------------------------
# 7. Run the existing reviewed v0.2.7 identity resolver.
#
# Up to four archive passes are allowed automatically. Completed jobs are
# preserved by CheckpointDB. Retryable archive failures remain explicitly
# non-scientific.
# ----------------------------------------------------------------------

MAX_PASSES = 4

for pass_no in range(1, MAX_PASSES + 1):
    rc = run_cli_pass(pass_no)

    if rc != 0:
        raise SystemExit(
            f"Identity CLI exited non-zero on pass {pass_no}: {rc}"
        )

    counts = checkpoint_counts()

    print()
    print(f"Post-pass {pass_no} checkpoint:")
    print(json.dumps(
        counts,
        indent=2,
        sort_keys=True,
    ))

    if counts.get("failed_terminal", 0):
        break

    if (
        counts.get("failed_retryable", 0) == 0
        and counts.get("pending", 0) == 0
        and counts.get("running", 0) == 0
    ):
        break


# ----------------------------------------------------------------------
# 8. Final extension accounting.
# ----------------------------------------------------------------------

counts = checkpoint_counts()

if sum(counts.values()) != 9:
    raise SystemExit(
        f"REFUSING: extension checkpoint does not contain exactly "
        f"nine jobs: {counts}"
    )

if counts.get("failed_terminal", 0):
    raise SystemExit(
        "v0.2.8 extension has terminal identity failures. "
        "Review before any science."
    )

if (
    counts.get("pending", 0)
    or counts.get("running", 0)
    or counts.get("failed_retryable", 0)
):
    print()
    print("=" * 96)
    print("v0.2.8 EXTENSION PAUSED ON RETRYABLE ARCHIVE STATE")
    print("=" * 96)
    print(json.dumps(
        counts,
        indent=2,
        sort_keys=True,
    ))
    print("No retryable archive failure is a scientific negative.")
    print("Re-run this same script to resume.")
    print("No transient detector was run.")
    raise SystemExit(2)

if counts != {"succeeded": 9}:
    raise SystemExit(
        f"REFUSING: unexpected completed checkpoint accounting: {counts}"
    )


# ----------------------------------------------------------------------
# 9. Inspect final nine result rows.
# ----------------------------------------------------------------------

require_file(EXT_RESULT)

result_rows = load_csv(EXT_RESULT)

if len(result_rows) != 9:
    raise SystemExit(
        f"REFUSING: extension result rows={len(result_rows)}, expected 9."
    )

result_ids = {
    str(r.get("exposure_id") or "")
    for r in result_rows
}

if result_ids != MISSING:
    raise SystemExit(
        "REFUSING: extension result set differs from exact nine."
    )

status_counts = Counter(
    str(r.get("identity_status") or "")
    for r in result_rows
)

allowed_statuses = {
    "validated",
    "catalogue_identified_pixels_unavailable",
}

unexpected = (
    set(status_counts)
    - allowed_statuses
)

if unexpected:
    raise SystemExit(
        "REFUSING: unexpected completed identity state(s): "
        f"{sorted(unexpected)}"
    )

print()
print("=" * 96)
print("NINE-EXPOSURE IDENTITY RESULTS")
print("=" * 96)

for row in sorted(
    result_rows,
    key=lambda r: int(
        r.get("queue_canonical_order_first_seen")
        or 9999
    ),
):
    print()
    print(row.get("exposure_id"))
    print(
        "  order:        ",
        row.get("queue_canonical_order_first_seen"),
    )
    print(
        "  status:       ",
        row.get("identity_status"),
    )
    print(
        "  eligible:     ",
        row.get("eligible_for_science"),
    )
    print(
        "  finder_region:",
        row.get("finder_region"),
    )
    print(
        "  VI/25 MLP:    ",
        row.get("vi25_mlp"),
    )
    print(
        "  source:       ",
        row.get("identity_source"),
    )
    print(
        "  archive state:",
        row.get("archive_availability_status"),
    )
    print(
        "  failure kind: ",
        row.get("archive_failure_kind"),
    )
    print(
        "  FITS SHA256:  ",
        row.get("fits_sha256"),
    )


# ----------------------------------------------------------------------
# 10. Verify the evidence store after the extension.
# ----------------------------------------------------------------------

print()
print("=" * 96)
print("EVIDENCE VERIFICATION")
print("=" * 96)

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
        f"REFUSING: evidence errors present: {evidence_summary}"
    )


# ----------------------------------------------------------------------
# 11. Confirm v0.2.7 was not touched.
# ----------------------------------------------------------------------

v027_db_after = sha256_file(V027_DB)
v027_result_after = sha256_file(V027_RESULT)

if v027_db_after != v027_db_before:
    raise SystemExit(
        "REFUSING: v0.2.7 checkpoint DB changed during extension."
    )

if v027_result_after != v027_result_before:
    raise SystemExit(
        "REFUSING: v0.2.7 result CSV changed during extension."
    )

if sha256_file(SKY) != EXPECTED_SKY_SHA:
    raise SystemExit(
        "REFUSING: poss1_skyview.py changed during extension."
    )

if sha256_file(POSS) != EXPECTED_POSS_SHA:
    raise SystemExit(
        "REFUSING: poss1.py changed during extension."
    )


# ----------------------------------------------------------------------
# 12. Audit record.
# ----------------------------------------------------------------------

audit = {
    "created_at_utc":
        datetime.now(timezone.utc).isoformat(),

    "operation":
        "v0.2.8 nine-exposure identity extension",

    "detector_run":
        False,

    "authoritative_queue": {
        "path":
            str(QUEUE.relative_to(ROOT)),
        "sha256":
            sha256_file(QUEUE),
    },

    "v027_snapshot_id":
        EXPECTED_SNAPSHOT_ID,

    "v027_preserved": {
        "checkpoint_sha256":
            v027_db_after,
        "result_sha256":
            v027_result_after,
        "source_poss1_sha256":
            sha256_file(POSS),
        "source_poss1_skyview_sha256":
            sha256_file(SKY),
    },

    "extension": {
        "cohort":
            EXT_COHORT,
        "stage":
            EXT_STAGE,
        "queue_path":
            str(EXT_QUEUE.relative_to(ROOT)),
        "queue_sha256":
            ext_queue_sha,
        "db_path":
            str(EXT_DB.relative_to(ROOT)),
        "db_sha256":
            sha256_file(EXT_DB),
        "result_path":
            str(EXT_RESULT.relative_to(ROOT)),
        "result_sha256":
            sha256_file(EXT_RESULT),
        "cache_dir":
            str(EXT_CACHE.relative_to(ROOT)),
        "jobs":
            sorted(MISSING),
        "checkpoint":
            counts,
        "identity_status_counts":
            dict(status_counts),
    },

    "cross_cohort_already_frozen_exposure":
        shared_id,

    "evidence_verification":
        evidence_summary,

    "science_cohort_policy": (
        "No authoritative science publication_cohort value was changed. "
        "The identity_extension_v028 label exists only in the derived "
        "identity-preflight queue so previously touched development rows "
        "can receive the same physical-plate identity policy without "
        "becoming prospective science."
    ),
}

EXT_AUDIT.write_text(
    json.dumps(
        audit,
        indent=2,
        sort_keys=True,
    ) + "\n",
    encoding="utf-8",
)

print()
print("=" * 96)
print("v0.2.8 NINE-EXPOSURE IDENTITY EXTENSION COMPLETE")
print("=" * 96)
print("checkpoint:", counts)
print("identity statuses:")
print(json.dumps(
    dict(status_counts),
    indent=2,
    sort_keys=True,
))
print("result:", EXT_RESULT)
print("audit: ", EXT_AUDIT)
print()
print("v0.2.7 checkpoint/result hashes remain unchanged.")
print("No authoritative science cohort was modified.")
print("No transient detector was run.")
print()
print(
    "STOP BEFORE FULL-40 FREEZE: "
    "review any pixels-unavailable identities first."
)
