from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import hashlib
import json
import sqlite3


DB = Path("state/poss1_identity_prospective.sqlite")
STAGE = "poss1-identity:prospective_production"
AUDIT_DIR = Path("research")
SOURCE = Path("src/transient_pipeline/poss1_skyview.py")

# Exact v0.2.7 source produced by the reviewed patch.
EXPECTED_SOURCE_SHA256 = (
    "df125f17bfc4f21f6dd1a16ba3290790b5a47e37a8d8bffba6e239932da2000a"
)

EXPECTED = {
    "POSS-I:782:E:rec514": {
        "status": "failed_terminal",
        "error_contains": (
            "SkyView descriptor/HHH center disagreement for XE513:"
        ),
    },
    "POSS-I:832:E:rec760": {
        "status": "failed_retryable",
        "error_contains": "unexpected HTTP 404",
    },
    "POSS-I:872:O:rec148": {
        "status": "failed_terminal",
        "error_contains": (
            "SkyView descriptor/HHH center disagreement for XO147:"
        ),
    },
    "POSS-I:875:E:rec521": {
        "status": "failed_terminal",
        "error_contains": (
            "SkyView descriptor/HHH center disagreement for XE520:"
        ),
    },
    "POSS-I:876:E:rec239": {
        "status": "failed_terminal",
        "error_contains": (
            "SkyView descriptor/HHH center disagreement for XE238:"
        ),
    },
}


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def counts_for(con):
    return dict(
        con.execute(
            """
            SELECT status, COUNT(*)
            FROM jobs
            WHERE stage=?
            GROUP BY status
            """,
            (STAGE,),
        ).fetchall()
    )


print("=" * 88)
print("POSS-I v0.2.7 GUARDED FIVE-JOB REQUEUE")
print("=" * 88)

if not DB.exists():
    raise SystemExit(f"REFUSING: missing checkpoint DB: {DB}")

if not SOURCE.exists():
    raise SystemExit(f"REFUSING: missing patched source: {SOURCE}")

source_sha = sha256_file(SOURCE)
print("source SHA256:", source_sha)

if source_sha != EXPECTED_SOURCE_SHA256:
    raise SystemExit(
        "REFUSING: poss1_skyview.py is not the exact validated "
        f"v0.2.7 source.\nExpected: {EXPECTED_SOURCE_SHA256}\n"
        f"Actual:   {source_sha}"
    )

with sqlite3.connect(DB) as con:
    con.row_factory = sqlite3.Row

    all_rows = con.execute(
        """
        SELECT job_key,status,attempts,last_error,updated_at
        FROM jobs
        WHERE stage=?
        ORDER BY job_key
        """,
        (STAGE,),
    ).fetchall()

    pre_counts = counts_for(con)

    target_rows = {
        r["job_key"]: r
        for r in all_rows
        if r["job_key"] in EXPECTED
    }

    active_or_failed = [
        r for r in all_rows
        if r["status"] in (
            "pending",
            "running",
            "failed_retryable",
            "failed_terminal",
        )
    ]

print()
print("Pre-migration counts:")
print(json.dumps(pre_counts, indent=2, sort_keys=True))

# ------------------------------------------------------------------
# Fail closed unless the checkpoint is exactly in the reviewed state.
# ------------------------------------------------------------------

missing = sorted(set(EXPECTED) - set(target_rows))
if missing:
    raise SystemExit(
        "REFUSING: expected target rows missing: " + ", ".join(missing)
    )

unexpected_active = [
    dict(r)
    for r in active_or_failed
    if r["job_key"] not in EXPECTED
]

if unexpected_active:
    print("\nUnexpected unfinished/failed rows:")
    print(json.dumps(unexpected_active, indent=2, default=str))
    raise SystemExit(
        "REFUSING: checkpoint contains unfinished/failed jobs outside "
        "the reviewed five-row set."
    )

problems = []

for job_key, expected in EXPECTED.items():
    row = target_rows[job_key]
    err = row["last_error"] or ""

    if row["status"] != expected["status"]:
        problems.append(
            f"{job_key}: status {row['status']!r}, "
            f"expected {expected['status']!r}"
        )

    if expected["error_contains"] not in err:
        problems.append(
            f"{job_key}: last_error does not contain reviewed signature "
            f"{expected['error_contains']!r}; actual={err!r}"
        )

if problems:
    print("\nReviewed-state mismatches:")
    for p in problems:
        print("  -", p)
    raise SystemExit(
        "REFUSING: one or more target rows are not in the exact "
        "reviewed v0.2.6 failure state."
    )

print()
print("Reviewed five rows:")
for key in EXPECTED:
    r = target_rows[key]
    print(
        f"  {key} | {r['status']} | attempts={r['attempts']} | "
        f"{r['last_error']}"
    )

# ------------------------------------------------------------------
# Backup before any mutation.
# ------------------------------------------------------------------

stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
backup = DB.with_name(
    f"{DB.stem}.pre_v027_five_job_requeue_{stamp}{DB.suffix}"
)

src = sqlite3.connect(DB)
dst = sqlite3.connect(backup)
try:
    src.backup(dst)
finally:
    dst.close()
    src.close()

backup_sha = sha256_file(backup)

print()
print("Checkpoint backup:", backup)
print("Backup SHA256:    ", backup_sha)

# ------------------------------------------------------------------
# Write pre-mutation audit before changing checkpoint.
# ------------------------------------------------------------------

AUDIT_DIR.mkdir(parents=True, exist_ok=True)
audit = AUDIT_DIR / f"POSS1_V027_FIVE_JOB_REQUEUE_{stamp}.json"

audit_payload = {
    "created_at_utc": datetime.now(timezone.utc).isoformat(),
    "science_analysis_performed": False,
    "detector_run": False,
    "reason": (
        "Requeue exactly five POSS-I identity jobs after v0.2.7 "
        "review. Four v0.2.6 descriptor/HHH centre failures were "
        "demonstrated by pixel-equivalent controls to be invalid "
        "terminal gates. XE759's deterministic raw HHH HTTP 404 is "
        "requeued so v0.2.7 can classify it as catalogue-identified "
        "with digital pixels unavailable rather than repeatedly retrying."
    ),
    "stage": STAGE,
    "source_db": str(DB),
    "backup_db": str(backup),
    "backup_db_sha256": backup_sha,
    "validated_source": str(SOURCE),
    "validated_source_sha256": source_sha,
    "pre_counts": pre_counts,
    "target_job_keys": list(EXPECTED),
    "rows_before": [
        dict(target_rows[k]) for k in EXPECTED
    ],
    "attempt_history_policy": (
        "Preserved. Attempts are not reset; only status, last_error "
        "and updated_at are changed."
    ),
}

audit.write_text(
    json.dumps(audit_payload, indent=2, sort_keys=True, default=str) + "\n",
    encoding="utf-8",
)

# ------------------------------------------------------------------
# Mutation: exact five rows only.
# ------------------------------------------------------------------

now = datetime.now(timezone.utc).isoformat()

with sqlite3.connect(DB) as con:
    con.row_factory = sqlite3.Row

    con.execute("BEGIN IMMEDIATE")

    changed = 0

    for job_key in EXPECTED:
        before = target_rows[job_key]

        marker = (
            "requeued_v0.2.7_after_reviewed_v0.2.6_identity_failure; "
            "prior=" + (before["last_error"] or "")
        )

        cur = con.execute(
            """
            UPDATE jobs
            SET status='pending',
                last_error=?,
                updated_at=?
            WHERE stage=?
              AND job_key=?
              AND status=?
            """,
            (
                marker,
                now,
                STAGE,
                job_key,
                before["status"],
            ),
        )

        if cur.rowcount != 1:
            con.rollback()
            raise SystemExit(
                f"REFUSING/ROLLBACK: expected to update exactly one "
                f"row for {job_key}; updated {cur.rowcount}"
            )

        changed += cur.rowcount

    if changed != 5:
        con.rollback()
        raise SystemExit(
            f"REFUSING/ROLLBACK: expected 5 changes, got {changed}"
        )

    con.commit()

    post_counts = counts_for(con)

    after_rows = con.execute(
        """
        SELECT job_key,status,attempts,last_error,updated_at
        FROM jobs
        WHERE stage=?
          AND job_key IN (?,?,?,?,?)
        ORDER BY job_key
        """,
        (STAGE, *EXPECTED.keys()),
    ).fetchall()

# ------------------------------------------------------------------
# Postcondition verification.
# ------------------------------------------------------------------

if len(after_rows) != 5:
    raise SystemExit(
        f"POSTCONDITION FAILURE: expected five target rows, "
        f"found {len(after_rows)}"
    )

bad_after = [
    dict(r)
    for r in after_rows
    if r["status"] != "pending"
]

if bad_after:
    raise SystemExit(
        "POSTCONDITION FAILURE: not all five rows are pending:\n"
        + json.dumps(bad_after, indent=2, default=str)
    )

audit_payload["post_counts"] = post_counts
audit_payload["rows_after"] = [dict(r) for r in after_rows]
audit_payload["completed_at_utc"] = datetime.now(
    timezone.utc
).isoformat()

audit.write_text(
    json.dumps(audit_payload, indent=2, sort_keys=True, default=str) + "\n",
    encoding="utf-8",
)

print()
print("=" * 88)
print("REQUEUE SUCCESSFUL")
print("=" * 88)
print("Rows changed:", changed)
print("Audit:", audit)
print()
print("Post-migration counts:")
print(json.dumps(post_counts, indent=2, sort_keys=True))
print()
print("Target rows now:")
for r in after_rows:
    print(
        f"  {r['job_key']} | {r['status']} | "
        f"attempts={r['attempts']}"
    )

print()
print("No transient detector was run.")
print("Only the reviewed five identity jobs were requeued.")
