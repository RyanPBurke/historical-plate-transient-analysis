from pathlib import Path
import json
import sqlite3
import subprocess
import sys


def make_db(path: Path):
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
        stage = "poss1-identity:prospective_production"
        for i in range(5):
            con.execute(
                "INSERT INTO jobs VALUES(?,?,?,?,?,?,?,?,?)",
                (f"ok{i}", stage, "succeeded", 1, "{}", "{}", None, "x", "x"),
            )
        known = "terminal_error: ValueError: SkyView descriptor center mismatch for XE001: 99 arcsec"
        for i in range(21):
            con.execute(
                "INSERT INTO jobs VALUES(?,?,?,?,?,?,?,?,?)",
                (f"bad_center{i}", stage, "failed_terminal", 2, "{}", None, known, "x", "x"),
            )
        mlp = "terminal_error: ValueError: VI/25 MLP/recno mismatch prevents deterministic DSS region mapping: x"
        for i in range(4):
            con.execute(
                "INSERT INTO jobs VALUES(?,?,?,?,?,?,?,?,?)",
                (f"bad_mlp{i}", stage, "failed_terminal", 2, "{}", None, mlp, "x", "x"),
            )
        xo = "terminal_error: ValueError: SkyView descriptor expected exactly one image for XO197, got 0"
        con.execute(
            "INSERT INTO jobs VALUES(?,?,?,?,?,?,?,?,?)",
            ("POSS-I:449:O:rec198", stage, "failed_terminal", 3, "{}", None, xo, "x", "x"),
        )
        con.commit()


def test_v025_requeue_accepts_only_reviewed_26(tmp_path):
    db = tmp_path / "state.sqlite"
    make_db(db)
    validation = tmp_path / "validation.json"
    validation.write_text(json.dumps({
        "exposure_id": "POSS-I:449:O:rec198",
        "classification": "catalogue_identified_pixels_unavailable",
    }), encoding="utf-8")
    audit = tmp_path / "audit"
    script = Path("tools/requeue_v023_terminal_identity_jobs.py")
    cp = subprocess.run(
        [sys.executable, str(script), "--db", str(db), "--audit-dir", str(audit), "--exception-validation", str(validation)],
        capture_output=True,
        text=True,
    )
    assert cp.returncode == 0, cp.stdout + cp.stderr
    with sqlite3.connect(db) as con:
        counts = dict(con.execute("SELECT status,COUNT(*) FROM jobs GROUP BY status"))
    assert counts == {"pending": 26, "succeeded": 5}
    assert list(audit.glob("POSS1_V025_REQUEUE_*.json"))
