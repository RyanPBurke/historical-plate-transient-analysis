from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3

ALLOWED_ERROR_PREFIXES = (
    "terminal_error: ValueError: VI/25 MLP/recno mismatch prevents deterministic DSS region mapping:",
    "terminal_error: ValueError: SkyView descriptor center mismatch for",
    "terminal_error: ValueError: SkyView HHH center mismatch for",
    "terminal_error: ValueError: SkyView descriptor expected exactly one image for XO197, got 0",
)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="state/poss1_identity_prospective.sqlite")
    ap.add_argument("--stage", default="poss1-identity:prospective_production")
    ap.add_argument("--audit-dir", default="research")
    ap.add_argument("--exception-validation", default="research/POSS1_XO197_ARCHIVE_EXCEPTION_VALIDATION_v0.2.5.json")
    args = ap.parse_args()

    db = Path(args.db)
    validation = Path(args.exception_validation)
    if not db.exists():
        raise SystemExit(f"missing checkpoint DB: {db}")
    if not validation.exists():
        raise SystemExit(f"missing XO197 archive-exception validation: {validation}")
    v = json.loads(validation.read_text(encoding="utf-8"))
    if v.get("exposure_id") != "POSS-I:449:O:rec198" or v.get("classification") != "catalogue_identified_pixels_unavailable":
        raise SystemExit("XO197 archive-exception validation has unexpected contents")

    with sqlite3.connect(db) as con:
        con.row_factory = sqlite3.Row
        rows = con.execute(
            "SELECT job_key,status,attempts,last_error,updated_at FROM jobs WHERE stage=? ORDER BY job_key",
            (args.stage,),
        ).fetchall()

    counts = {}
    for r in rows:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    terminal = [r for r in rows if r["status"] == "failed_terminal"]
    unexpected = [
        r for r in terminal
        if not any((r["last_error"] or "").startswith(p) for p in ALLOWED_ERROR_PREFIXES)
    ]

    print("v0.2.3/v0.2.4 terminal-state audit for v0.2.5")
    print(json.dumps(counts, indent=2, sort_keys=True))
    print("terminal rows:", len(terminal))
    grouped = {}
    for r in terminal:
        err = r["last_error"] or ""
        label = next((p for p in ALLOWED_ERROR_PREFIXES if err.startswith(p)), "UNEXPECTED")
        grouped[label] = grouped.get(label, 0) + 1
    print("terminal error classes:")
    print(json.dumps(grouped, indent=2, sort_keys=True))

    if unexpected:
        print("\nUNEXPECTED terminal errors; refusing to requeue:")
        for r in unexpected:
            print(r["job_key"], "=>", r["last_error"])
        return 2
    if counts.get("succeeded", 0) != 5 or len(terminal) != 26:
        print("Refusing migration: expected exactly 5 succeeded + 26 reviewed v0.2.3 terminals.")
        return 3
    if any(counts.get(x, 0) for x in ("pending", "running", "failed_retryable")):
        print("Refusing migration: checkpoint has non-final work states.")
        return 4

    xo = [r for r in terminal if r["job_key"] == "POSS-I:449:O:rec198"]
    if len(xo) != 1 or "SkyView descriptor expected exactly one image for XO197, got 0" not in (xo[0]["last_error"] or ""):
        print("Refusing migration: the reviewed XO197 row is not in the expected terminal state.")
        return 5

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = db.with_name(f"{db.stem}.pre_v025_requeue_{stamp}{db.suffix}")
    src = sqlite3.connect(db)
    dst = sqlite3.connect(backup)
    try:
        src.backup(dst)
    finally:
        dst.close(); src.close()
    backup_sha = sha256_file(backup)

    audit_dir = Path(args.audit_dir); audit_dir.mkdir(parents=True, exist_ok=True)
    audit = audit_dir / f"POSS1_V025_REQUEUE_{stamp}.json"
    audit_payload = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "science_analysis_performed": False,
        "reason": (
            "Requeue 26 v0.2.3 terminal rows after v0.2.4/v0.2.5 implementation review. "
            "Twenty-five were invalid identity gates; XO197 is requeued so v0.2.5 can record it as an "
            "archive-pixels-unavailable workflow completion if STScI remains unavailable and SkyView still lacks the region."
        ),
        "stage": args.stage,
        "source_db": str(db),
        "backup_db": str(backup),
        "backup_db_sha256": backup_sha,
        "pre_counts": counts,
        "allowed_error_prefixes": list(ALLOWED_ERROR_PREFIXES),
        "archive_exception_validation": {"path": str(validation), "sha256": sha256_file(validation)},
        "rows": [dict(r) for r in terminal],
    }
    audit.write_text(json.dumps(audit_payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    now = datetime.now(timezone.utc).isoformat()
    with sqlite3.connect(db) as con:
        for r in terminal:
            con.execute(
                "UPDATE jobs SET status='pending', last_error=?, updated_at=? WHERE stage=? AND job_key=? AND status='failed_terminal'",
                (
                    "requeued_v0.2.5_after_reviewed_v0.2.3_terminal; prior=" + (r["last_error"] or ""),
                    now, args.stage, r["job_key"],
                ),
            )
        con.commit()
        post = dict(con.execute(
            "SELECT status,COUNT(*) FROM jobs WHERE stage=? GROUP BY status", (args.stage,)
        ).fetchall())

    print("backup:", backup)
    print("backup SHA256:", backup_sha)
    print("audit:", audit)
    print("post-migration counts:")
    print(json.dumps(post, indent=2, sort_keys=True))
    print("No transient detector was run.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
