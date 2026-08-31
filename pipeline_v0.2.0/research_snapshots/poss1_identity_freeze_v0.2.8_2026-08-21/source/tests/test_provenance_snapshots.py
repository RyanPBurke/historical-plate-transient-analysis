from pathlib import Path
import json

from transient_pipeline.provenance import EvidenceStore, sha256_file


def test_snapshot_survives_working_file_rewrite(tmp_path: Path):
    evidence = EvidenceStore(tmp_path / "evidence")
    work = tmp_path / "results.csv"
    work.write_text("a\n1\n", encoding="utf-8")
    rec1 = evidence.record_artifact(path=work, kind="stage_results_csv", snapshot=True)
    snap1 = Path(rec1["path"])
    assert snap1.exists()
    assert rec1["source_path"] == str(work)
    h1 = rec1["sha256"]

    work.write_text("a\n2\n", encoding="utf-8")
    rec2 = evidence.record_artifact(path=work, kind="stage_results_csv", snapshot=True)
    snap2 = Path(rec2["path"])
    assert snap2.exists()
    assert rec2["sha256"] != h1
    assert sha256_file(snap1) == h1
    assert snap1 != snap2


def test_stable_reference_remains_in_place(tmp_path: Path):
    evidence = EvidenceStore(tmp_path / "evidence")
    fits = tmp_path / "x.fits"
    fits.write_bytes(b"SIMPLE  " + b" " * 100)
    rec = evidence.record_artifact(path=fits, kind="scientific_fits")
    assert rec["path"] == str(fits)
    assert rec["storage_mode"] == "stable_reference"
