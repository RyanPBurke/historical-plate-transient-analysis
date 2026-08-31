from __future__ import annotations

from pathlib import Path
from typing import Callable
import hashlib
import json
import os

from .archives import STARGLASS_CUTOUT, starglass_cutout_fits_bytes
from .checkpoint import CheckpointDB, Job
from .config import FrozenMethod
from .detector import analyze_fits_bytes
from .http import RetryableRemoteError, ValidatedSession
from .provenance import EvidenceStore, atomic_write_text, sha256_file, utcnow


def run_stage(db: CheckpointDB, stage: str, worker: Callable[[Job], dict], max_jobs: int | None = None):
    db.recover_interrupted(stage)
    # Retryable remote failures from a previous invocation get one fresh chance now.
    # Failures created during this invocation remain deferred until the next run, so a
    # flaky archive cannot trap the runner in an immediate retry loop.
    db.requeue_retryable(stage)
    completed = 0
    while max_jobs is None or completed < max_jobs:
        job = db.next_job(stage)
        if job is None:
            break
        try:
            result = worker(job)
        except RetryableRemoteError as exc:
            db.fail(job.job_key, f"retryable_remote_error: {exc}", retryable=True)
        except Exception as exc:
            # Data/logic errors are terminal for that row; the rest of the queue continues.
            db.fail(job.job_key, f"terminal_error: {type(exc).__name__}: {exc}", retryable=False)
        else:
            db.succeed(job.job_key, result)
        completed += 1
    return db.summary(stage)


def _atomic_write(path: Path, data: bytes):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + f".tmp.{os.getpid()}")
    with tmp.open("wb") as fh:
        fh.write(data)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)


def _starglass_sidecar(
    *,
    cache_path: Path,
    plate_id: str,
    solution_number: int,
    ra_deg: float,
    dec_deg: float,
    sha256: str,
    cache_hit: bool,
) -> Path:
    sidecar = cache_path.with_suffix(".fits.provenance.json")
    if not sidecar.exists():
        record = {
            "artifact_type": "starglass_dasch_cutout_fits",
            "recorded_at_utc": utcnow(),
            "source_url": STARGLASS_CUTOUT,
            "request": {
                "plate_id": plate_id,
                "solution_number": solution_number,
                "center_ra_deg": ra_deg,
                "center_dec_deg": dec_deg,
            },
            "path": str(cache_path),
            "sha256": sha256,
            "bytes": cache_path.stat().st_size,
            "cache_hit_when_sidecar_created": cache_hit,
            "note": (
                "If cache_hit_when_sidecar_created=true, the FITS predates this provenance sidecar; "
                "the exact FITS content is still identified by SHA256 but original retrieval time is unknown."
            ),
        }
        atomic_write_text(sidecar, json.dumps(record, indent=2, sort_keys=True) + "\n")
    return sidecar


def starglass_worker(
    method: FrozenMethod,
    plate_id: str,
    solution_number: int = 0,
    session: ValidatedSession | None = None,
    cache_dir: str | Path = "cache/starglass",
    *,
    evidence: EvidenceStore | None = None,
    stage: str | None = None,
):
    session = session or ValidatedSession()
    cache_dir = Path(cache_dir)
    stage = stage or f"starglass:{plate_id}:solution{solution_number}"

    def worker(job: Job):
        ra = float(job.payload["ra_deg"])
        dec = float(job.payload["dec_deg"])
        safe_key = "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in job.job_key)
        cache_path = cache_dir / plate_id / f"{safe_key}.fits"
        cache_hit = False
        if cache_path.exists():
            raw = cache_path.read_bytes()
            if raw.startswith(b"SIMPLE"):
                cache_hit = True
            else:
                cache_path.unlink()
                raw = starglass_cutout_fits_bytes(session, plate_id, ra, dec, solution_number)
                _atomic_write(cache_path, raw)
        else:
            raw = starglass_cutout_fits_bytes(session, plate_id, ra, dec, solution_number)
            _atomic_write(cache_path, raw)

        cutout_hash = hashlib.sha256(raw).hexdigest()
        sidecar = _starglass_sidecar(
            cache_path=cache_path,
            plate_id=plate_id,
            solution_number=solution_number,
            ra_deg=ra,
            dec_deg=dec,
            sha256=cutout_hash,
            cache_hit=cache_hit,
        )
        if evidence:
            evidence.record_artifact(
                path=cache_path,
                kind="starglass_dasch_cutout_fits",
                stage=stage,
                job_key=job.job_key,
                source_url=STARGLASS_CUTOUT,
                metadata={
                    "plate_id": plate_id,
                    "solution_number": solution_number,
                    "center_ra_deg": ra,
                    "center_dec_deg": dec,
                    "provenance_sidecar": str(sidecar),
                },
            )

        summary = analyze_fits_bytes(raw, ra, dec, method).to_dict()
        summary["strict_match"] = summary["nearest_peak_sep_arcsec"] <= method.strict_registered_match_arcsec
        summary["plate_id"] = plate_id
        summary["cutout_sha256"] = cutout_hash
        summary["cutout_cache_path"] = str(cache_path)
        summary["cutout_cache_hit"] = cache_hit
        summary["cutout_bytes"] = len(raw)
        summary["cutout_provenance_sidecar"] = str(sidecar)
        return summary

    return worker
