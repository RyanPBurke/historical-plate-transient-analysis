from pathlib import Path
import json

from transient_pipeline.provenance import EvidenceStore, ExchangeContext, publication_snapshot, sha256_file
from transient_pipeline.checkpoint import CheckpointDB


def test_evidence_store_records_exact_bytes(tmp_path):
    store = EvidenceStore(tmp_path / "evidence")
    ctx = ExchangeContext(stage="gps1:test", job_key="abc", attempt=2)
    rec = store.record_exchange(
        service="unit",
        context=ctx,
        method="POST",
        url="https://example.invalid/tap",
        request_payload={"FORMAT": "csv"},
        query_text="SELECT 1",
        response_bytes=b"x,y\n1,2\n",
        response_content_type="text/csv",
        extension="csv",
    )
    assert Path(rec["response"]["path"]).read_bytes() == b"x,y\n1,2\n"
    assert sha256_file(rec["response"]["path"]) == rec["response"]["sha256"]
    exchange = tmp_path / "evidence" / "exchanges" / "gps1_test" / "abc" / "attempt-0002.json"
    assert exchange.exists()
    assert (tmp_path / "evidence" / "index" / "evidence.jsonl").exists()


def test_checkpoint_stage_run_ledger(tmp_path):
    db = CheckpointDB(tmp_path / "x.sqlite")
    run_id = db.begin_stage_run("stage", {"argv": ["x"]}, {"manifest_sha256": "abc"})
    db.add_jobs("stage", [("1", {"source_id": "1", "ra_deg": 1.0, "dec_deg": 2.0})])
    db.finish_stage_run(run_id, {"succeeded": 1})
    rows = db.stage_run_rows()
    assert len(rows) == 1
    assert rows[0]["run_id"] == run_id
    assert json.loads(rows[0]["final_summary_json"])["succeeded"] == 1


def test_publication_snapshot_hashes_protocol_queue_and_code(tmp_path):
    root = tmp_path / "project"
    (root / "src" / "x").mkdir(parents=True)
    (root / "tests").mkdir()
    (root / "config").mkdir()
    (root / "src" / "x" / "a.py").write_text("x=1\n", encoding="utf-8")
    (root / "config" / "frozen_method.json").write_text("{}\n", encoding="utf-8")
    (root / "README.md").write_text("readme\n", encoding="utf-8")
    protocol = root / "protocol.md"
    queue = root / "queue.csv"
    protocol.write_text("frozen\n", encoding="utf-8")
    queue.write_text("id\n1\n", encoding="utf-8")
    out = root / "snapshot"
    rec = publication_snapshot(
        project_root=root,
        output_dir=out,
        protocol=protocol,
        queue=queue,
        config=root / "config" / "frozen_method.json",
    )
    assert rec["snapshot_id"]
    assert (out / "SNAPSHOT.json").exists()
    assert (out / "SHA256SUMS.txt").exists()
