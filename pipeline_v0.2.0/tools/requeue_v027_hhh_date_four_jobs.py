from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import hashlib
import json
import sqlite3


ROOT = Path.cwd()

DB = ROOT / "state" / "poss1_identity_prospective.sqlite"
SKY = ROOT / "src" / "transient_pipeline" / "poss1_skyview.py"
POSS = ROOT / "src" / "transient_pipeline" / "poss1.py"

STAGE = "poss1-identity:prospective_production"

EXPECTED_SKY_SHA256 = (
    "22470c1956e6b0ddb885d51092aa0a30dd322bfc1d48c6b49bcd0ed3620a732e"
)
EXPECTED_POSS_SHA256 = (
    "6161a74d5ce76f70235c66a748077b3517f7d2d7946e9f48998927c331374ac7"
)

TARGETS = {
    "POSS-I:782:E:rec514": (
        "terminal_error: ValueError: SkyView HHH observing-date mismatch "
        "for XE513: '1953-08-13' != VI/25 '1953-08-12'"
    ),
    "POSS-I:872:O:rec148": (
        "terminal_error: ValueError: SkyView HHH observing-date mismatch "
        "for XO147: '1953-10-29' != VI/25 '1953-10-28'"
    ),
    "POSS-I:875:E:rec521": (
        "terminal_error: ValueError: SkyView HHH observing-date mismatch "
        "for XE520: '1953-10-31' != VI/25 '1953-10-30'"
    ),
    "POSS-I:876:E:rec239": (
        "terminal_error: ValueError: SkyView HHH observing-date mismatch "
        "for XE238: '1953-10-31' != VI/25 '1953-10-30'"
    ),
}


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


print("=" * 92)
print("POSS-I v0.2.7 GUARDED HHH-DATE FOUR-JOB REQUEUE")
print("=" * 92)

for path in (DB, SKY, POSS):
    if not path.exists():
        raise SystemExit(f"REFUSING: missing required file: {path}")

sky_sha = sha256_file(SKY)
poss_sha = sha256_file(POSS)

print("poss1_skyview SHA256:", sky_sha)
print("poss1.py SHA256:       ", poss_sha)

if sky_sha != EXPECTED_SKY_SHA256:
    raise SystemExit(
        "REFUSING: poss1_skyview.py does not match the 50-test-passing "
        "v0.2.7 HHH-date repair."
    )

if poss_sha != EXPECTED_POSS_SHA256:
    raise SystemExit(
        "REFUSING: poss1.py does not match the 50-test-passing "
        "v0.2.7 HHH-date repair."
    )

con = sqlite3.connect(DB)
con.row_factory = sqlite3.Row

counts = dict(
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

print()
print("Pre-migration counts:")
print(json.dumps(counts, indent=2, sort_keys=True))

expected_counts = {
    "failed_terminal": 4,
    "succeeded": 27,
}

if counts != expected_counts:
    con.close()
    raise SystemExit(
        "REFUSING: checkpoint state differs from expected reviewed state.\n"
        f"Expected: {expected_counts}\n"
        f"Actual:   {counts}"
    )

rows = con.execute(
    """
    SELECT job_key,status,attempts,last_error
    FROM jobs
    WHERE stage=?
      AND status!='succeeded'
    ORDER BY job_key
    """,
    (STAGE,),
).fetchall()

if len(rows) != 4:
    con.close()
    raise SystemExit(
        f"REFUSING: expected exactly four non-succeeded rows; found {len(rows)}"
    )

print()
print("Reviewed terminal rows:")

seen = set()

for row in rows:
    key = row["job_key"]
    seen.add(key)

    print(
        f"  {key} | {row['status']} | "
        f"attempts={row['attempts']} | {row['last_error']}"
    )

    if key not in TARGETS:
        con.close()
        raise SystemExit(
            f"REFUSING: unexpected non-succeeded job: {key}"
        )

    if row["status"] != "failed_terminal":
        con.close()
        raise SystemExit(
            f"REFUSING: {key} is {row['status']}, not failed_terminal"
        )

    if row["attempts"] != 6:
        con.close()
        raise SystemExit(
            f"REFUSING: {key} attempts changed: {row['attempts']} != 6"
        )

    if row["last_error"] != TARGETS[key]:
        con.close()
        raise SystemExit(
            f"REFUSING: reviewed error changed for {key}\n"
            f"Expected: {TARGETS[key]}\n"
            f"Actual:   {row['last_error']}"
        )

if seen != set(TARGETS):
    con.close()
    raise SystemExit(
        "REFUSING: exact four reviewed job keys are not present."
    )

stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

backup = (
    ROOT
    / "state"
    / f"poss1_identity_prospective.pre_v027_hhh_date_requeue_{stamp}.sqlite"
)

audit = (
    ROOT
    / "research"
    / f"POSS1_V027_HHH_DATE_FOUR_JOB_REQUEUE_{stamp}.json"
)

audit.parent.mkdir(parents=True, exist_ok=True)

# Consistent SQLite backup before mutation.
backup_con = sqlite3.connect(backup)
con.backup(backup_con)
backup_con.close()

backup_sha = sha256_file(backup)

print()
print("Checkpoint backup:", backup)
print("Backup SHA256:    ", backup_sha)

audit_payload = {
    "created_at_utc": datetime.now(timezone.utc).isoformat(),
    "stage": STAGE,
    "reason": (
        "Four SkyView fallback jobs were terminal solely because the old "
        "HHH DATE-OBS gate required equality with VI/25 initial observing-"
        "night date. Reviewed pixel-equivalent controls and VI/25 timestamp "
        "normalization establish two supported historical encodings: initial "
        "observing-night date or normalized UTC exposure date."
    ),
    "methodological_policy": (
        "HHH calendar date must equal either VI/25 initial observing-night "
        "date or the authoritative normalized UTC exposure-start date; "
        "no arbitrary +/-1-day tolerance."
    ),
    "source_hashes": {
        str(SKY.relative_to(ROOT)): sky_sha,
        str(POSS.relative_to(ROOT)): poss_sha,
    },
    "checkpoint_backup": {
        "path": str(backup.relative_to(ROOT)),
        "sha256": backup_sha,
    },
    "pre_migration_counts": counts,
    "reviewed_rows": [dict(r) for r in rows],
    "target_job_keys": sorted(TARGETS),
    "detector_execution": False,
}

audit.write_text(
    json.dumps(audit_payload, indent=2, sort_keys=True) + "\n",
    encoding="utf-8",
)

now = datetime.now(timezone.utc).isoformat()

changed = 0

try:
    con.execute("BEGIN IMMEDIATE")

    for row in rows:
        key = row["job_key"]

        cur = con.execute(
            """
            UPDATE jobs
            SET status='pending',
                last_error=?,
                updated_at=?
            WHERE stage=?
              AND job_key=?
              AND status='failed_terminal'
              AND attempts=6
              AND last_error=?
            """,
            (
                "requeued_v0.2.7_after_reviewed_hhh_date_semantics; prior="
                + row["last_error"],
                now,
                STAGE,
                key,
                row["last_error"],
            ),
        )

        if cur.rowcount != 1:
            raise RuntimeError(
                f"Fail-closed update affected {cur.rowcount} rows for {key}"
            )

        changed += cur.rowcount

    con.commit()

except Exception:
    con.rollback()
    con.close()
    raise

post_counts = dict(
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

post_rows = con.execute(
    """
    SELECT job_key,status,attempts,last_error
    FROM jobs
    WHERE stage=?
      AND job_key IN (?,?,?,?)
    ORDER BY job_key
    """,
    (STAGE, *sorted(TARGETS)),
).fetchall()

con.close()

if changed != 4:
    raise SystemExit(
        f"REQUEUE FAILED: expected four changed rows; got {changed}"
    )

if post_counts != {"pending": 4, "succeeded": 27}:
    raise SystemExit(
        "REQUEUE FAILED POSTCONDITION:\n"
        f"{json.dumps(post_counts, indent=2, sort_keys=True)}"
    )

print()
print("=" * 92)
print("REQUEUE SUCCESSFUL")
print("=" * 92)
print("Rows changed:", changed)
print("Audit:", audit)

print()
print("Post-migration counts:")
print(json.dumps(post_counts, indent=2, sort_keys=True))

print()
print("Target rows now:")
for row in post_rows:
    print(
        f"  {row['job_key']} | {row['status']} | "
        f"attempts={row['attempts']}"
    )

print()
print("No transient detector was run.")
print("Only the four reviewed HHH-date jobs were requeued.")
