from pathlib import Path
import json
import sqlite3
import subprocess
import sys

EXPECTED = [
    "POSS-I:449:O:rec198",
    "POSS-I:782:E:rec514",
    "POSS-I:832:E:rec760",
    "POSS-I:872:O:rec148",
    "POSS-I:875:E:rec521",
    "POSS-I:876:E:rec239",
]


def make_db(path: Path, *, mutate_key: str | None = None):
    stage = "poss1-identity:prospective_production"
    with sqlite3.connect(path) as con:
        con.execute(
            """CREATE TABLE jobs (
                job_key TEXT PRIMARY KEY,
                stage TEXT NOT NULL,
                status TEXT NOT NULL,
                attempts INTEGER NOT NULL DEFAULT 0,
                payload_json TEXT NOT NULL,
                result_json TEXT,
                last_error TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )"""
        )
        for i in range(25):
            result = json.dumps({"identity_status": "validated", "eligible_for_science": True})
            con.execute(
                "INSERT INTO jobs VALUES(?,?,?,?,?,?,?,?,?)",
                (f"ok{i:02d}", stage, "succeeded", 1, "{}", result, None, "x", "x"),
            )
        keys = EXPECTED.copy()
        if mutate_key is not None:
            keys[-1] = mutate_key
        for i, key in enumerate(keys):
            result = json.dumps({
                "identity_status": "no_unique_platefinder_match",
                "eligible_for_science": False,
                "finder_candidate_count": i,
                "finder_response_sha256": f"sha{i}",
            })
            con.execute(
                "INSERT INTO jobs VALUES(?,?,?,?,?,?,?,?,?)",
                (key, stage, "succeeded", 3, "{}", result, None, "x", "x"),
            )
        con.commit()


def test_v026_requeues_only_reviewed_six(tmp_path):
    db = tmp_path / "state.sqlite"
    make_db(db)
    audit = tmp_path / "audit"
    script = Path("tools/requeue_v025_platefinder_nonresolution_jobs.py")
    cp = subprocess.run(
        [sys.executable, str(script), "--db", str(db), "--audit-dir", str(audit)],
        capture_output=True,
        text=True,
    )
    assert cp.returncode == 0, cp.stdout + cp.stderr
    with sqlite3.connect(db) as con:
        counts = dict(con.execute("SELECT status,COUNT(*) FROM jobs GROUP BY status"))
        pending = con.execute(
            "SELECT job_key,result_json,last_error FROM jobs WHERE status='pending' ORDER BY job_key"
        ).fetchall()
    assert counts == {"pending": 6, "succeeded": 25}
    assert {r[0] for r in pending} == set(EXPECTED)
    assert all(r[1] is None for r in pending)
    assert all(r[2] == "requeued_v0.2.6_platefinder_nonresolution_control_flow_fix" for r in pending)
    audits = list(audit.glob("POSS1_V026_NONRESOLUTION_REQUEUE_*.json"))
    assert len(audits) == 1
    payload = json.loads(audits[0].read_text())
    assert len(payload["rows"]) == 6
    assert Path(payload["backup_db"]).exists()


def test_v026_migration_refuses_different_nonresolution_set(tmp_path):
    db = tmp_path / "state.sqlite"
    make_db(db, mutate_key="POSS-I:999:E:rec999")
    script = Path("tools/requeue_v025_platefinder_nonresolution_jobs.py")
    cp = subprocess.run(
        [sys.executable, str(script), "--db", str(db), "--audit-dir", str(tmp_path / "audit")],
        capture_output=True,
        text=True,
    )
    assert cp.returncode != 0
    with sqlite3.connect(db) as con:
        counts = dict(con.execute("SELECT status,COUNT(*) FROM jobs GROUP BY status"))
    assert counts == {"succeeded": 31}
