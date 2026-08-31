from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from typing import Any, Iterable
import uuid


FINAL_STATUSES = {"succeeded", "failed_terminal"}


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class Job:
    job_key: str
    stage: str
    status: str
    attempts: int
    payload: dict[str, Any]
    result: dict[str, Any] | None
    last_error: str | None


class CheckpointDB:
    """SQLite state store with atomic per-job transitions and append-only event log."""

    def __init__(self, path: str | Path, event_log: str | Path | None = None):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.event_log = Path(event_log) if event_log else self.path.with_suffix(".events.jsonl")
        self._init_schema()

    @contextmanager
    def connect(self):
        con = sqlite3.connect(self.path)
        con.row_factory = sqlite3.Row
        try:
            con.execute("PRAGMA journal_mode=WAL")
            con.execute("PRAGMA synchronous=FULL")
            yield con
            con.commit()
        finally:
            con.close()

    def _init_schema(self):
        with self.connect() as con:
            con.executescript(
                """
                CREATE TABLE IF NOT EXISTS jobs (
                    job_key TEXT PRIMARY KEY,
                    stage TEXT NOT NULL,
                    status TEXT NOT NULL,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    payload_json TEXT NOT NULL,
                    result_json TEXT,
                    last_error TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_jobs_stage_status ON jobs(stage, status);

                CREATE TABLE IF NOT EXISTS stage_runs (
                    run_id TEXT PRIMARY KEY,
                    stage TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    finished_at TEXT,
                    invocation_json TEXT NOT NULL,
                    context_json TEXT NOT NULL,
                    final_summary_json TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_stage_runs_stage ON stage_runs(stage, started_at);
                """
            )

    def _event(self, event: str, **data: Any):
        self.event_log.parent.mkdir(parents=True, exist_ok=True)
        record = {"ts": utcnow(), "event": event, **data}
        with self.event_log.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, sort_keys=True) + "\n")
            fh.flush()

    def begin_stage_run(self, stage: str, invocation: dict[str, Any], context: dict[str, Any]) -> str:
        run_id = str(uuid.uuid4())
        started = utcnow()
        with self.connect() as con:
            con.execute(
                "INSERT INTO stage_runs(run_id,stage,started_at,invocation_json,context_json) VALUES(?,?,?,?,?)",
                (run_id, stage, started, json.dumps(invocation, sort_keys=True), json.dumps(context, sort_keys=True)),
            )
        self._event("stage_run_started", run_id=run_id, stage=stage, context=context, invocation=invocation)
        return run_id

    def finish_stage_run(self, run_id: str, summary: dict[str, Any]):
        finished = utcnow()
        with self.connect() as con:
            row = con.execute("SELECT stage FROM stage_runs WHERE run_id=?", (run_id,)).fetchone()
            con.execute(
                "UPDATE stage_runs SET finished_at=?, final_summary_json=? WHERE run_id=?",
                (finished, json.dumps(summary, sort_keys=True), run_id),
            )
        self._event("stage_run_finished", run_id=run_id, stage=row["stage"] if row else None, summary=summary)

    def add_jobs(self, stage: str, rows: Iterable[tuple[str, dict[str, Any]]]):
        now = utcnow()
        added = 0
        with self.connect() as con:
            for key, payload in rows:
                cur = con.execute(
                    """INSERT OR IGNORE INTO jobs
                       (job_key, stage, status, attempts, payload_json, created_at, updated_at)
                       VALUES (?, ?, 'pending', 0, ?, ?, ?)""",
                    (key, stage, json.dumps(payload, sort_keys=True), now, now),
                )
                added += cur.rowcount
        self._event("jobs_added", stage=stage, count=added)
        return added

    def recover_interrupted(self, stage: str | None = None) -> int:
        """On restart, running jobs become retryable pending jobs."""
        now = utcnow()
        with self.connect() as con:
            if stage:
                cur = con.execute(
                    "UPDATE jobs SET status='pending', last_error='recovered_interrupted_run', updated_at=? WHERE stage=? AND status='running'",
                    (now, stage),
                )
            else:
                cur = con.execute(
                    "UPDATE jobs SET status='pending', last_error='recovered_interrupted_run', updated_at=? WHERE status='running'",
                    (now,),
                )
            n = cur.rowcount
        if n:
            self._event("jobs_recovered", stage=stage, count=n)
        return n

    def requeue_retryable(self, stage: str | None = None) -> int:
        """Requeue remote failures once, at the start of a later invocation."""
        now = utcnow()
        with self.connect() as con:
            if stage:
                cur = con.execute(
                    "UPDATE jobs SET status='pending', updated_at=? WHERE stage=? AND status='failed_retryable'",
                    (now, stage),
                )
            else:
                cur = con.execute(
                    "UPDATE jobs SET status='pending', updated_at=? WHERE status='failed_retryable'",
                    (now,),
                )
            n = cur.rowcount
        if n:
            self._event("retryable_jobs_requeued", stage=stage, count=n)
        return n

    def next_job(self, stage: str) -> Job | None:
        with self.connect() as con:
            row = con.execute(
                "SELECT * FROM jobs WHERE stage=? AND status='pending' ORDER BY job_key LIMIT 1",
                (stage,),
            ).fetchone()
            if row is None:
                return None
            now = utcnow()
            con.execute(
                "UPDATE jobs SET status='running', attempts=attempts+1, updated_at=? WHERE job_key=?",
                (now, row["job_key"]),
            )
            attempts = row["attempts"] + 1
        self._event("job_started", job_key=row["job_key"], stage=stage, attempts=attempts)
        return Job(
            job_key=row["job_key"],
            stage=row["stage"],
            status="running",
            attempts=attempts,
            payload=json.loads(row["payload_json"]),
            result=json.loads(row["result_json"]) if row["result_json"] else None,
            last_error=row["last_error"],
        )

    def succeed(self, job_key: str, result: dict[str, Any]):
        with self.connect() as con:
            con.execute(
                "UPDATE jobs SET status='succeeded', result_json=?, last_error=NULL, updated_at=? WHERE job_key=?",
                (json.dumps(result, sort_keys=True), utcnow(), job_key),
            )
        self._event("job_succeeded", job_key=job_key, result=result)

    def fail(self, job_key: str, error: str, retryable: bool = True):
        status = "failed_retryable" if retryable else "failed_terminal"
        with self.connect() as con:
            con.execute(
                "UPDATE jobs SET status=?, last_error=?, updated_at=? WHERE job_key=?",
                (status, error[:4000], utcnow(), job_key),
            )
        self._event("job_failed", job_key=job_key, status=status, error=error[:4000])

    def summary(self, stage: str | None = None) -> dict[str, int]:
        with self.connect() as con:
            if stage:
                rows = con.execute("SELECT status, COUNT(*) n FROM jobs WHERE stage=? GROUP BY status", (stage,)).fetchall()
            else:
                rows = con.execute("SELECT status, COUNT(*) n FROM jobs GROUP BY status").fetchall()
        return {r["status"]: r["n"] for r in rows}

    def export_results(self, stage: str, out_path: str | Path):
        import csv

        rows_out = []
        with self.connect() as con:
            rows = con.execute("SELECT * FROM jobs WHERE stage=? ORDER BY job_key", (stage,)).fetchall()
        for r in rows:
            payload = json.loads(r["payload_json"])
            result = json.loads(r["result_json"]) if r["result_json"] else {}
            rows_out.append(
                {
                    "job_key": r["job_key"],
                    "status": r["status"],
                    "attempts": r["attempts"],
                    "last_error": r["last_error"] or "",
                    "created_at": r["created_at"],
                    "updated_at": r["updated_at"],
                    **payload,
                    **result,
                }
            )
        fields = sorted({k for row in rows_out for k in row}) if rows_out else ["job_key", "status"]
        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with out_path.open("w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=fields)
            w.writeheader()
            w.writerows(rows_out)

    def raw_ledger_rows(self) -> list[dict[str, Any]]:
        with self.connect() as con:
            jobs = con.execute("SELECT * FROM jobs ORDER BY stage, job_key").fetchall()
        out = []
        for r in jobs:
            out.append(
                {
                    "db_path": str(self.path),
                    "stage": r["stage"],
                    "job_key": r["job_key"],
                    "status": r["status"],
                    "attempts": r["attempts"],
                    "payload_json": r["payload_json"],
                    "result_json": r["result_json"] or "",
                    "last_error": r["last_error"] or "",
                    "created_at": r["created_at"],
                    "updated_at": r["updated_at"],
                }
            )
        return out

    def stage_run_rows(self) -> list[dict[str, Any]]:
        with self.connect() as con:
            rows = con.execute("SELECT * FROM stage_runs ORDER BY started_at, run_id").fetchall()
        return [dict(r) for r in rows]
