from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
import sys

from .archives import applause_adql
from .checkpoint import CheckpointDB
from .config import FrozenMethod
from .runner import run_stage, starglass_worker
from .regression import compare_results
from .catalogue_workers import applause_resolve_ids, hamburg_recurrence_worker, gps1_worker
from .http import ValidatedSession
from .provenance import (
    EvidenceStore,
    ExchangeContext,
    atomic_write_text,
    code_fingerprint,
    file_record,
    publication_snapshot,
    sha256_file,
    utcnow,
)
from .tables import parse_votable_tabledata
from .poss1 import load_vi25_records, poss1_identity_worker, queue_poss_jobs


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def active_snapshot(root: Path) -> dict:
    p = root / "research" / "ACTIVE_SNAPSHOT.json"
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {"active_snapshot_error": f"could not parse {p}"}


def manifest_context(path: Path, config_path: Path, root: Path) -> dict:
    return {
        "manifest_path": str(path),
        "manifest_sha256": sha256_file(path),
        "frozen_config_path": str(config_path),
        "frozen_config_sha256": sha256_file(config_path),
        "code_fingerprint_sha256": code_fingerprint(root),
        "active_snapshot": active_snapshot(root),
    }


def load_manifest(path: Path, provenance: dict | None = None):
    with path.open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            sid = row.get("source_id") or row.get("job_key")
            if not sid:
                raise ValueError("manifest requires source_id or job_key")
            payload = {
                "source_id": str(sid),
                "ra_deg": float(row["ra_deg"]),
                "dec_deg": float(row["dec_deg"]),
                **({"strip": row["strip"]} if row.get("strip") else {}),
            }
            if provenance:
                payload["_provenance"] = provenance
            yield str(sid), payload


def _write_csv(path: str | Path, rows: list[dict]):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = sorted({k for row in rows for k in row}) if rows else ["status"]
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def _scan_state_dbs(state_dir: Path):
    for p in sorted(state_dir.rglob("*.sqlite")):
        yield p


def _verify_evidence(evidence_dir: Path) -> tuple[int, int, list[str]]:
    index = evidence_dir / "index" / "evidence.jsonl"
    if not index.exists():
        return 0, 1, [f"missing evidence index: {index}"]
    checked = set()
    ok = 0
    errors: list[str] = []
    for line_no, line in enumerate(index.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
        except Exception as exc:
            errors.append(f"index line {line_no}: invalid JSON: {exc}")
            continue
        candidates = []
        if rec.get("record_type") == "remote_exchange":
            resp = rec.get("response") or {}
            if resp.get("path") and resp.get("sha256"):
                candidates.append((resp["path"], resp["sha256"]))
            q = ((rec.get("request") or {}).get("query") or {})
            if q.get("path") and q.get("sha256"):
                candidates.append((q["path"], q["sha256"]))
        elif rec.get("record_type") == "local_artifact":
            if rec.get("path") and rec.get("sha256"):
                candidates.append((rec["path"], rec["sha256"]))
        for pstr, expected in candidates:
            key = (pstr, expected)
            if key in checked:
                continue
            checked.add(key)
            p = Path(pstr)
            if not p.exists():
                errors.append(f"missing artifact: {p}")
                continue
            actual = sha256_file(p)
            if actual != expected:
                errors.append(f"hash mismatch: {p}: expected {expected}, got {actual}")
                continue
            ok += 1
    return ok, len(errors), errors


def main(argv=None):
    root = project_root()
    ap = argparse.ArgumentParser(prog="transient-pipeline")
    ap.add_argument("--db", default="state/pipeline.sqlite")
    ap.add_argument("--config", default="config/frozen_method.json")
    ap.add_argument(
        "--evidence-dir",
        default="evidence",
        help="publication evidence root; use empty string to disable raw-response/artifact indexing",
    )
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("starglass", help="resume frozen-detector Harvard cutout jobs")
    p.add_argument("--manifest", required=True)
    p.add_argument("--plate", required=True)
    p.add_argument("--solution", type=int, default=0)
    p.add_argument("--max-jobs", type=int)
    p.add_argument("--export", default="results/starglass_results.csv")
    p.add_argument("--cache-dir", default="cache/starglass")

    p = sub.add_parser("status")
    p.add_argument("--stage")

    p = sub.add_parser("recover", help="mark interrupted running jobs pending")
    p.add_argument("--stage")

    p = sub.add_parser("verify-regressions", help="compare completed detector CSV with frozen known cases")
    p.add_argument("--expected", default="examples/regression_cases.csv")
    p.add_argument("--results", required=True)

    p = sub.add_parser("resolve-applause", help="resolve source IDs to process coordinates")
    p.add_argument("--ids", required=True, help="CSV with source_id column")
    p.add_argument("--out", required=True)
    p.add_argument("--process", type=int, default=9548)
    p.add_argument("--solution", type=int, default=0)

    p = sub.add_parser("hamburg", help="resume independent Hamburg recurrence checks")
    p.add_argument("--manifest", required=True)
    p.add_argument("--processes", default="9541,9542,9543,9544,9545,9546,9547,9550")
    p.add_argument("--max-jobs", type=int)
    p.add_argument("--export", default="results/hamburg_results.csv")

    p = sub.add_parser("gps1", help="resume exhaustive GPS1 propagated static-source checks")
    p.add_argument("--manifest", required=True)
    p.add_argument("--max-jobs", type=int)
    p.add_argument("--export", default="results/gps1_results.csv")

    p = sub.add_parser("publication-snapshot", help="freeze protocol, queue, code identity and software environment")
    p.add_argument("--protocol", required=True)
    p.add_argument("--queue", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--extra", action="append", default=[])
    p.add_argument("--activate", action="store_true", help="write research/ACTIVE_SNAPSHOT.json for subsequent run provenance")

    p = sub.add_parser("build-ledger", help="combine all SQLite job/stage-run records into publication ledgers")
    p.add_argument("--state-dir", default="state")
    p.add_argument("--jobs-out", default="analysis/master_job_ledger.csv")
    p.add_argument("--runs-out", default="analysis/stage_run_ledger.csv")

    p = sub.add_parser("verify-evidence", help="verify hashes for raw responses and indexed scientific artifacts")
    p.add_argument("--root", default="evidence")

    p = sub.add_parser("register-artifact", help="hash/index an externally retrieved FITS/image/table without copying it")
    p.add_argument("--file", required=True)
    p.add_argument("--kind", required=True)
    p.add_argument("--stage")
    p.add_argument("--job-key")
    p.add_argument("--source-url")
    p.add_argument("--metadata-json", help="JSON object with plate/observatory/role identifiers")
    p.add_argument("--snapshot", action="store_true", help="copy exact current bytes into content-addressed immutable evidence storage")

    p = sub.add_parser("applause-scan-info", help="resolve APPLAUSE process to native scan metadata and stable plate links")
    p.add_argument("--process", required=True, type=int)
    p.add_argument("--out")

    p = sub.add_parser("index-starglass-cache", help="index legacy cached StarGlass FITS without re-downloading")
    p.add_argument("--root", default="cache/verified_starglass")

    p = sub.add_parser("poss1-preflight", help="resolve/force exact POSS-I physical plates for a frozen queue; no transient detection")
    p.add_argument("--queue", required=True)
    p.add_argument("--vi25", default="research/poss1_plate_metadata.csv")
    p.add_argument("--cohort", default="prospective_production")
    p.add_argument("--cache-dir", default="cache/poss1_identity")
    p.add_argument("--max-jobs", type=int)
    p.add_argument("--export", default="results/poss1_identity_preflight.csv")

    args = ap.parse_args(argv)
    evidence = EvidenceStore(args.evidence_dir or None)

    if args.cmd == "publication-snapshot":
        manifest = publication_snapshot(
            project_root=root,
            output_dir=args.out,
            protocol=args.protocol,
            queue=args.queue,
            config=args.config,
            extra_files=args.extra,
        )
        if args.activate:
            pointer = {
                "activated_at_utc": utcnow(),
                "snapshot_id": manifest["snapshot_id"],
                "snapshot_path": str(Path(args.out).resolve()),
                "code_fingerprint_sha256": manifest["code_fingerprint_sha256"],
                "inputs": manifest["inputs"],
            }
            pth = root / "research" / "ACTIVE_SNAPSHOT.json"
            atomic_write_text(pth, json.dumps(pointer, indent=2, sort_keys=True) + "\n")
            print(f"activated snapshot: {pth}")
        print(json.dumps(manifest, indent=2, sort_keys=True))
        return

    if args.cmd == "build-ledger":
        job_rows = []
        run_rows = []
        for db_path in _scan_state_dbs(Path(args.state_dir)):
            db = CheckpointDB(db_path)
            job_rows.extend(db.raw_ledger_rows())
            for row in db.stage_run_rows():
                run_rows.append({"db_path": str(db_path), **row})
        _write_csv(args.jobs_out, job_rows)
        _write_csv(args.runs_out, run_rows)
        print(json.dumps({"databases": len(list(_scan_state_dbs(Path(args.state_dir)))), "job_rows": len(job_rows), "stage_runs": len(run_rows)}, indent=2))
        return

    if args.cmd == "verify-evidence":
        ok, nerr, errors = _verify_evidence(Path(args.root))
        print(json.dumps({"verified_artifacts": ok, "errors": nerr}, indent=2))
        for err in errors:
            print(err)
        raise SystemExit(0 if nerr == 0 else 1)

    if args.cmd == "register-artifact":
        metadata = json.loads(args.metadata_json) if args.metadata_json else {}
        rec = evidence.record_artifact(
            path=args.file,
            kind=args.kind,
            stage=args.stage,
            job_key=args.job_key,
            source_url=args.source_url,
            metadata=metadata,
            snapshot=args.snapshot,
        )
        print(json.dumps(rec, indent=2, sort_keys=True))
        return

    if args.cmd == "index-starglass-cache":
        cache_root = Path(args.root)
        files = sorted(cache_root.rglob("*.fits")) if cache_root.exists() else []
        for fp in files:
            plate_id = fp.parent.name
            evidence.record_artifact(
                path=fp,
                kind="starglass_dasch_cutout_fits",
                stage="legacy_cache_import",
                job_key=fp.stem,
                source_url="https://api.starglass.cfa.harvard.edu/public/dasch/dr7/cutout",
                metadata={
                    "plate_id": plate_id,
                    "legacy_import": True,
                    "original_retrieval_time": None,
                    "note": "Exact preserved FITS indexed after retrieval; original retrieval timestamp was not recorded by v0.1.",
                },
            )
        print(json.dumps({"indexed_fits": len(files), "root": str(cache_root)}, indent=2))
        return

    if args.cmd == "poss1-preflight":
        queue = Path(args.queue)
        vi25 = Path(args.vi25)
        config_path = Path(args.config)
        prov = {
            "queue_path": str(queue),
            "queue_sha256": sha256_file(queue),
            "vi25_path": str(vi25),
            "vi25_sha256": sha256_file(vi25),
            "frozen_config_path": str(config_path),
            "frozen_config_sha256": sha256_file(config_path),
            "code_fingerprint_sha256": code_fingerprint(root),
            "active_snapshot": active_snapshot(root),
            "cohort": args.cohort,
            "science_analysis_performed": False,
        }
        stage = f"poss1-identity:{args.cohort}"
        db = CheckpointDB(args.db)
        invocation = {"argv": list(sys.argv if argv is None else ["transient-pipeline", *argv]), "db": args.db}
        run_id = db.begin_stage_run(stage, invocation, prov)
        jobs = list(queue_poss_jobs(queue, args.cohort))
        added = db.add_jobs(stage, ((k, {**payload, "_provenance": prov}) for k, payload in jobs))
        print(f"POSS-I identity jobs: {len(jobs)} unique exposures; added {added} new jobs")
        records = load_vi25_records(vi25)
        summary = run_stage(
            db,
            stage,
            poss1_identity_worker(
                vi25_records=records,
                evidence=evidence,
                cache_dir=args.cache_dir,
                stage=stage,
            ),
            args.max_jobs,
        )
        db.export_results(stage, args.export)
        if evidence.enabled:
            evidence.record_artifact(path=args.export, kind="poss1_identity_preflight_csv", stage=stage, metadata=prov, snapshot=True)
        db.finish_stage_run(run_id, summary)
        print(json.dumps(summary, indent=2, sort_keys=True))
        return

    if args.cmd == "applause-scan-info":
        proc = int(args.process)
        q = f'''SELECT p.process_id,p.scan_id,p.plate_id,p.archive_id,p.filename,p.plate_epoch,p.pyplate_version,
                       s.filename_scan,s.naxis1,s.naxis2,s.file_size,s.fits_checksum,s.fits_datasum
                FROM applause_dr4.process AS p
                JOIN applause_dr4.scan AS s ON p.scan_id=s.scan_id
                WHERE p.process_id={proc}'''
        ctx = ExchangeContext(stage="applause-scan-info", job_key=str(proc), attempt=1)
        rows = parse_votable_tabledata(applause_adql(ValidatedSession(), q, evidence=evidence, context=ctx))
        if len(rows) != 1:
            raise RuntimeError(f"expected exactly one process/scan row for process {proc}, got {len(rows)}")
        r = rows[0]
        archive_id = int(r["archive_id"])
        plate_id = int(r["plate_id"])
        out = {
            **r,
            "process_id": proc,
            "archive_id": archive_id,
            "plate_id": plate_id,
            "datalink_url": f"https://www.plate-archive.org/datalink/plates/{archive_id}_{plate_id}/",
            "plate_doi_url": f"https://doi.org/10.17876/plate/dr.4/plates/{archive_id}_{plate_id}",
        }
        if args.out:
            atomic_write_text(args.out, json.dumps(out, indent=2, sort_keys=True) + "\n")
        print(json.dumps(out, indent=2, sort_keys=True))
        return

    db = CheckpointDB(args.db)
    if args.cmd == "status":
        print(json.dumps(db.summary(args.stage), indent=2, sort_keys=True))
        return
    if args.cmd == "recover":
        print(db.recover_interrupted(args.stage))
        return
    if args.cmd == "verify-regressions":
        report = compare_results(args.expected, args.results)
        for sid, ok, msg in report:
            print(f"{sid}: {'PASS' if ok else 'FAIL'} - {msg}")
        raise SystemExit(0 if all(ok for _, ok, _ in report) else 1)
    if args.cmd == "resolve-applause":
        ids = []
        with Path(args.ids).open(newline="", encoding="utf-8-sig") as fh:
            for row in csv.DictReader(fh):
                ids.append(row["source_id"])
        rows = applause_resolve_ids(
            ValidatedSession(),
            ids,
            args.process,
            args.solution,
            evidence=evidence,
        )
        outp = Path(args.out)
        outp.parent.mkdir(parents=True, exist_ok=True)
        with outp.open("w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=["source_id", "ra_deg", "dec_deg"])
            w.writeheader()
            w.writerows(rows)
        if evidence.enabled:
            evidence.record_artifact(path=outp, kind="applause_resolved_manifest", stage=f"resolve-applause:{args.process}:solution{args.solution}", snapshot=True)
        print(f"resolved {len(rows)}/{len(ids)} source IDs")
        return

    method = FrozenMethod.from_json(args.config)
    manifest = Path(args.manifest)
    config_path = Path(args.config)
    prov = manifest_context(manifest, config_path, root)
    invocation = {"argv": list(sys.argv if argv is None else ["transient-pipeline", *argv]), "db": args.db}

    if args.cmd == "hamburg":
        stage = "hamburg:" + args.processes
        run_id = db.begin_stage_run(stage, invocation, prov)
        db.add_jobs(stage, load_manifest(manifest, prov))
        worker = hamburg_recurrence_worker(
            method,
            [int(x) for x in args.processes.split(",") if x.strip()],
            evidence=evidence,
            stage=stage,
        )
        summary = run_stage(db, stage, worker, args.max_jobs)
        db.export_results(stage, args.export)
        if evidence.enabled:
            evidence.record_artifact(path=args.export, kind="stage_results_csv", stage=stage, metadata=prov, snapshot=True)
        db.finish_stage_run(run_id, summary)
        print(json.dumps(summary, indent=2, sort_keys=True))
        return

    if args.cmd == "gps1":
        stage = "gps1:epoch" + str(method.gps1_epoch)
        run_id = db.begin_stage_run(stage, invocation, prov)
        db.add_jobs(stage, load_manifest(manifest, prov))
        summary = run_stage(db, stage, gps1_worker(method, evidence=evidence, stage=stage), args.max_jobs)
        db.export_results(stage, args.export)
        if evidence.enabled:
            evidence.record_artifact(path=args.export, kind="stage_results_csv", stage=stage, metadata=prov, snapshot=True)
        db.finish_stage_run(run_id, summary)
        print(json.dumps(summary, indent=2, sort_keys=True))
        return

    stage = f"starglass:{args.plate}:solution{args.solution}"
    run_id = db.begin_stage_run(stage, invocation, prov)
    added = db.add_jobs(stage, load_manifest(manifest, prov))
    print(f"added {added} new jobs; existing completed jobs are preserved")
    summary = run_stage(
        db,
        stage,
        starglass_worker(
            method,
            args.plate,
            args.solution,
            cache_dir=args.cache_dir,
            evidence=evidence,
            stage=stage,
        ),
        args.max_jobs,
    )
    db.export_results(stage, args.export)
    if evidence.enabled:
        evidence.record_artifact(path=args.export, kind="stage_results_csv", stage=stage, metadata=prov, snapshot=True)
    db.finish_stage_run(run_id, summary)
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
