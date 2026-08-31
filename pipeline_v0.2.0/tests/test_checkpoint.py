from pathlib import Path

from transient_pipeline.checkpoint import CheckpointDB


def test_resume_and_no_duplicate(tmp_path: Path):
    db = CheckpointDB(tmp_path / "state.sqlite")
    rows = [("a", {"ra_deg": 1.0, "dec_deg": 2.0}), ("b", {"ra_deg": 3.0, "dec_deg": 4.0})]
    assert db.add_jobs("x", rows) == 2
    assert db.add_jobs("x", rows) == 0
    j = db.next_job("x")
    assert j.job_key == "a"
    # Simulate process death before success.
    assert db.recover_interrupted("x") == 1
    j2 = db.next_job("x")
    assert j2.job_key == "a"
    assert j2.attempts == 2
    db.succeed("a", {"ok": True})
    j3 = db.next_job("x")
    assert j3.job_key == "b"
    db.fail("b", "temporary", retryable=True)
    assert db.next_job("x") is None
    assert db.requeue_retryable("x") == 1
    j4 = db.next_job("x")
    assert j4.job_key == "b"
    db.succeed("b", {"ok": True})
    assert db.summary("x") == {"succeeded": 2}

def test_retryable_failure_deferred_until_next_invocation(tmp_path: Path):
    from transient_pipeline.runner import run_stage
    from transient_pipeline.http import RetryableRemoteError

    db = CheckpointDB(tmp_path / "retry.sqlite")
    db.add_jobs("x", [("a", {"ra_deg": 1.0, "dec_deg": 2.0}), ("b", {"ra_deg": 3.0, "dec_deg": 4.0})])
    calls = []
    def first_run(job):
        calls.append(job.job_key)
        if job.job_key == "a":
            raise RetryableRemoteError("502")
        return {"ok": True}
    summary = run_stage(db, "x", first_run)
    assert calls == ["a", "b"]
    assert summary == {"failed_retryable": 1, "succeeded": 1}

    calls2 = []
    def second_run(job):
        calls2.append(job.job_key)
        return {"ok": True}
    summary2 = run_stage(db, "x", second_run)
    assert calls2 == ["a"]
    assert summary2 == {"succeeded": 2}
