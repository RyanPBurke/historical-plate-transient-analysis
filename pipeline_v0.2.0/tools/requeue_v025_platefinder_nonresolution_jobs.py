from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3

EXPECTED_NONRESOLVED = {
    "POSS-I:449:O:rec198",
    "POSS-I:782:E:rec514",
    "POSS-I:832:E:rec760",
    "POSS-I:872:O:rec148",
    "POSS-I:875:E:rec521",
    "POSS-I:876:E:rec239",
}


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def parse_result(raw: str | None) -> dict:
    if not raw:
        return {}
    try:
        obj = json.loads(raw)
    except json.JSONDecodeError:
        return {"_unparseable": raw}
    return obj if isinstance(obj, dict) else {"_non_object": obj}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="state/poss1_identity_prospective.sqlite")
    ap.add_argument("--stage", default="poss1-identity:prospective_production")
    ap.add_argument("--audit-dir", default="research")
    args = ap.parse_args()

    db = Path(args.db)
    if not db.exists():
        raise SystemExit(f"missing checkpoint DB: {db}")

    with sqlite3.connect(db) as con:
        con.row_factory = sqlite3.Row
        rows = con.execute(
            "SELECT job_key,status,attempts,payload_json,result_json,last_error,created_at,updated_at "
            "FROM jobs WHERE stage=? ORDER BY job_key",
            (args.stage,),
        ).fetchall()

    counts: dict[str, int] = {}
    for row in rows:
        counts[row["status"]] = counts.get(row["status"], 0) + 1

    succeeded = [r for r in rows if r["status"] == "succeeded"]
    parsed = {r["job_key"]: parse_result(r["result_json"]) for r in succeeded}
    nonresolved = [
        r for r in succeeded
        if parsed[r["job_key"]].get("identity_status") == "no_unique_platefinder_match"
    ]
    validated = [
        r for r in succeeded
        if parsed[r["job_key"]].get("identity_status") == "validated"
        and bool(parsed[r["job_key"]].get("eligible_for_science"))
    ]
    other = [
        r for r in succeeded
        if r not in nonresolved and r not in validated
    ]

    observed_nonresolved = {r["job_key"] for r in nonresolved}

    print("v0.2.5 succeeded-state audit for v0.2.6 Plate Finder non-resolution correction")
    print(json.dumps(counts, indent=2, sort_keys=True))
    print("validated succeeded rows:", len(validated))
    print("no_unique_platefinder_match rows:", len(nonresolved))
    for key in sorted(observed_nonresolved):
        result = parsed[key]
        print(
            "  ", key,
            "candidate_count=", result.get("finder_candidate_count"),
            "finder_sha256=", result.get("finder_response_sha256"),
        )

    if counts != {"succeeded": 31}:
        print("Refusing migration: expected exactly 31 succeeded jobs and no other checkpoint states.")
        return 2
    if len(validated) != 25:
        print(f"Refusing migration: expected 25 validated detector-eligible successes, got {len(validated)}.")
        return 3
    if observed_nonresolved != EXPECTED_NONRESOLVED:
        print("Refusing migration: non-resolution set differs from the reviewed six.")
        print("expected:", json.dumps(sorted(EXPECTED_NONRESOLVED), indent=2))
        print("observed:", json.dumps(sorted(observed_nonresolved), indent=2))
        return 4
    if other:
        print("Refusing migration: unexpected succeeded identity states exist:")
        for r in other:
            print(r["job_key"], "=>", parsed[r["job_key"]])
        return 5

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = db.with_name(f"{db.stem}.pre_v026_nonresolution_requeue_{stamp}{db.suffix}")
    src = sqlite3.connect(db)
    dst = sqlite3.connect(backup)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    backup_sha = sha256_file(backup)

    audit_dir = Path(args.audit_dir)
    audit_dir.mkdir(parents=True, exist_ok=True)
    audit = audit_dir / f"POSS1_V026_NONRESOLUTION_REQUEUE_{stamp}.json"
    audit_payload = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "science_analysis_performed": False,
        "reason": (
            "v0.2.5 completed six jobs as no_unique_platefinder_match after a syntactically valid "
            "STScI Plate Finder response. Code review found that this branch bypassed the frozen/validated "
            "SkyView raw-DSS fallback. v0.2.6 requeues only those six so primary-source non-resolution is "
            "resolved through the same SkyView identity path used for retryable STScI failures."
        ),
        "stage": args.stage,
        "source_db": str(db),
        "backup_db": str(backup),
        "backup_db_sha256": backup_sha,
        "pre_counts": counts,
        "expected_nonresolved_job_keys": sorted(EXPECTED_NONRESOLVED),
        "rows": [
            {
                **dict(r),
                "parsed_result": parsed[r["job_key"]],
            }
            for r in nonresolved
        ],
    }
    audit.write_text(json.dumps(audit_payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    now = datetime.now(timezone.utc).isoformat()
    with sqlite3.connect(db) as con:
        for r in nonresolved:
            con.execute(
                "UPDATE jobs SET status='pending', result_json=NULL, last_error=?, updated_at=? "
                "WHERE stage=? AND job_key=? AND status='succeeded'",
                (
                    "requeued_v0.2.6_platefinder_nonresolution_control_flow_fix",
                    now,
                    args.stage,
                    r["job_key"],
                ),
            )
        con.commit()
        post = dict(con.execute(
            "SELECT status,COUNT(*) FROM jobs WHERE stage=? GROUP BY status",
            (args.stage,),
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
