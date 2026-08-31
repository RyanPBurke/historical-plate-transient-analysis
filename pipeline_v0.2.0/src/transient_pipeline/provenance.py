from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
from typing import Any


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: str | Path, chunk_size: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as fh:
        while True:
            block = fh.read(chunk_size)
            if not block:
                break
            h.update(block)
    return h.hexdigest()


def _safe_component(value: str) -> str:
    value = str(value)
    return "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in value)


def atomic_write_bytes(path: str | Path, data: bytes) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + f".tmp.{os.getpid()}")
    with tmp.open("wb") as fh:
        fh.write(data)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)
    return path


def atomic_write_text(path: str | Path, text: str, encoding: str = "utf-8") -> Path:
    return atomic_write_bytes(path, text.encode(encoding))


def file_record(path: str | Path, *, logical_role: str | None = None) -> dict[str, Any]:
    p = Path(path)
    return {
        "path": str(p),
        "bytes": p.stat().st_size,
        "sha256": sha256_file(p),
        **({"logical_role": logical_role} if logical_role else {}),
    }


@dataclass(frozen=True)
class ExchangeContext:
    stage: str
    job_key: str
    attempt: int


class EvidenceStore:
    """Append-only/content-addressed evidence store for remote scientific inputs.

    The store never interprets a remote failure as a scientific result. It records
    successful request/response exchanges and local scientific artifacts so the
    exact inputs used in a decision can be reconstructed later.
    """

    def __init__(self, root: str | Path | None):
        self.root = Path(root) if root else None
        if self.root:
            self.root.mkdir(parents=True, exist_ok=True)
            (self.root / "index").mkdir(parents=True, exist_ok=True)

    @property
    def enabled(self) -> bool:
        return self.root is not None

    def _append_index(self, record: dict[str, Any]) -> None:
        if not self.root:
            return
        index_path = self.root / "index" / "evidence.jsonl"
        index_path.parent.mkdir(parents=True, exist_ok=True)
        with index_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, sort_keys=True) + "\n")
            fh.flush()

    def record_exchange(
        self,
        *,
        service: str,
        context: ExchangeContext,
        method: str,
        url: str,
        request_payload: dict[str, Any] | None,
        query_text: str | None,
        response_bytes: bytes,
        response_content_type: str | None,
        extension: str,
        response_headers: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not self.root:
            return {}

        service_safe = _safe_component(service)
        response_hash = sha256_bytes(response_bytes)
        raw_path = self.root / "raw" / service_safe / response_hash[:2] / f"{response_hash}.{extension.lstrip('.')}"
        if not raw_path.exists():
            atomic_write_bytes(raw_path, response_bytes)

        query_record = None
        if query_text is not None:
            query_bytes = query_text.encode("utf-8")
            query_hash = sha256_bytes(query_bytes)
            query_path = self.root / "queries" / service_safe / query_hash[:2] / f"{query_hash}.txt"
            if not query_path.exists():
                atomic_write_bytes(query_path, query_bytes)
            query_record = {
                "sha256": query_hash,
                "path": str(query_path),
                "bytes": len(query_bytes),
            }

        exchange_dir = (
            self.root
            / "exchanges"
            / _safe_component(context.stage)
            / _safe_component(context.job_key)
        )
        exchange_dir.mkdir(parents=True, exist_ok=True)
        exchange_path = exchange_dir / f"attempt-{int(context.attempt):04d}.json"

        record = {
            "record_type": "remote_exchange",
            "recorded_at_utc": utcnow(),
            "service": service,
            "stage": context.stage,
            "job_key": context.job_key,
            "attempt": int(context.attempt),
            "request": {
                "method": method,
                "url": url,
                "payload": request_payload,
                "query": query_record,
            },
            "response": {
                "sha256": response_hash,
                "bytes": len(response_bytes),
                "path": str(raw_path),
                "content_type": response_content_type,
                "headers": response_headers or {},
            },
        }
        atomic_write_text(exchange_path, json.dumps(record, indent=2, sort_keys=True) + "\n")
        self._append_index(record)
        return record

    def record_artifact(
        self,
        *,
        path: str | Path,
        kind: str,
        stage: str | None = None,
        job_key: str | None = None,
        source_url: str | None = None,
        metadata: dict[str, Any] | None = None,
        snapshot: bool = False,
    ) -> dict[str, Any]:
        """Index a local scientific artifact.

        Stable inputs such as cached FITS can be indexed in place. Generated outputs
        that are legitimately rewritten as a checkpoint advances MUST use
        ``snapshot=True``. In that mode the exact bytes are copied into the
        evidence store under a content-addressed immutable path and the working
        source path is retained only as provenance metadata.
        """
        if not self.root:
            return {}
        p = Path(path)
        digest = sha256_file(p)
        nbytes = p.stat().st_size
        indexed_path = p
        storage_mode = "stable_reference"

        if snapshot:
            kind_safe = _safe_component(kind)
            basename = _safe_component(p.name)
            indexed_path = (
                self.root / "artifacts" / kind_safe / digest[:2] / f"{digest}__{basename}"
            )
            if not indexed_path.exists():
                indexed_path.parent.mkdir(parents=True, exist_ok=True)
                tmp = indexed_path.with_suffix(indexed_path.suffix + f".tmp.{os.getpid()}")
                with p.open("rb") as src, tmp.open("wb") as dst:
                    shutil.copyfileobj(src, dst, length=1024 * 1024)
                    dst.flush()
                    os.fsync(dst.fileno())
                os.replace(tmp, indexed_path)
            elif sha256_file(indexed_path) != digest:
                raise RuntimeError(f"content-addressed artifact collision/corruption: {indexed_path}")
            storage_mode = "content_addressed_snapshot"

        record = {
            "record_type": "local_artifact",
            "recorded_at_utc": utcnow(),
            "kind": kind,
            "path": str(indexed_path),
            "source_path": str(p),
            "storage_mode": storage_mode,
            "sha256": digest,
            "bytes": nbytes,
            "stage": stage,
            "job_key": job_key,
            "source_url": source_url,
            "metadata": metadata or {},
        }
        self._append_index(record)
        return record


def code_tree_manifest(root: str | Path, include_roots: tuple[str, ...] = ("src", "tests", "config")) -> list[dict[str, Any]]:
    root = Path(root).resolve()
    records: list[dict[str, Any]] = []
    for rel_root in include_roots:
        p = root / rel_root
        if not p.exists():
            continue
        for item in sorted(x for x in p.rglob("*") if x.is_file()):
            records.append({
                "path": item.relative_to(root).as_posix(),
                "bytes": item.stat().st_size,
                "sha256": sha256_file(item),
            })
    for name in ("pyproject.toml", "requirements.txt", "README.md"):
        p = root / name
        if p.exists():
            records.append({
                "path": p.relative_to(root).as_posix(),
                "bytes": p.stat().st_size,
                "sha256": sha256_file(p),
            })
    records.sort(key=lambda x: x["path"])
    return records


def code_fingerprint(root: str | Path) -> str:
    data = json.dumps(code_tree_manifest(root), separators=(",", ":"), sort_keys=True).encode("utf-8")
    return sha256_bytes(data)


def git_state(root: str | Path) -> dict[str, Any]:
    root = Path(root)
    try:
        commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True, stderr=subprocess.DEVNULL).strip()
        status = subprocess.check_output(["git", "status", "--porcelain"], cwd=root, text=True, stderr=subprocess.DEVNULL)
        return {"available": True, "commit": commit, "dirty": bool(status.strip()), "status_porcelain": status.splitlines()}
    except Exception:
        return {"available": False, "commit": None, "dirty": None, "status_porcelain": []}


def environment_snapshot() -> dict[str, Any]:
    try:
        pip_freeze = subprocess.check_output([sys.executable, "-m", "pip", "freeze", "--all"], text=True, stderr=subprocess.STDOUT).splitlines()
    except Exception as exc:
        pip_freeze = [f"ERROR: {type(exc).__name__}: {exc}"]
    return {
        "captured_at_utc": utcnow(),
        "python_executable": sys.executable,
        "python_version": sys.version,
        "implementation": platform.python_implementation(),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "processor": platform.processor(),
        "os_name": os.name,
        "pip_freeze": pip_freeze,
    }


def publication_snapshot(
    *,
    project_root: str | Path,
    output_dir: str | Path,
    protocol: str | Path,
    queue: str | Path,
    config: str | Path,
    extra_files: list[str | Path] | None = None,
) -> dict[str, Any]:
    root = Path(project_root).resolve()
    out = Path(output_dir)
    if out.exists() and any(out.iterdir()):
        raise FileExistsError(f"snapshot output already exists and is not empty: {out}")
    out.mkdir(parents=True, exist_ok=True)

    inputs_dir = out / "inputs"
    inputs_dir.mkdir(parents=True, exist_ok=True)
    copied: list[dict[str, Any]] = []
    for role, src in [("protocol", protocol), ("queue", queue), ("frozen_method", config)]:
        srcp = Path(src)
        dst = inputs_dir / srcp.name
        shutil.copy2(srcp, dst)
        copied.append(file_record(dst, logical_role=role))
    for src in extra_files or []:
        srcp = Path(src)
        dst = inputs_dir / srcp.name
        shutil.copy2(srcp, dst)
        copied.append(file_record(dst, logical_role="extra_input"))

    code_manifest = code_tree_manifest(root)
    atomic_write_text(out / "code_manifest.json", json.dumps(code_manifest, indent=2, sort_keys=True) + "\n")
    env = environment_snapshot()
    atomic_write_text(out / "environment.json", json.dumps(env, indent=2, sort_keys=True) + "\n")
    atomic_write_text(out / "pip_freeze.txt", "\n".join(env["pip_freeze"]) + "\n")
    git = git_state(root)
    atomic_write_text(out / "git_state.json", json.dumps(git, indent=2, sort_keys=True) + "\n")

    manifest = {
        "snapshot_format": 1,
        "created_at_utc": utcnow(),
        "project_root_at_capture": str(root),
        "inputs": copied,
        "code_fingerprint_sha256": code_fingerprint(root),
        "code_manifest_sha256": sha256_file(out / "code_manifest.json"),
        "environment_sha256": sha256_file(out / "environment.json"),
        "pip_freeze_sha256": sha256_file(out / "pip_freeze.txt"),
        "git": git,
    }
    core = json.dumps(manifest, separators=(",", ":"), sort_keys=True).encode("utf-8")
    manifest["snapshot_id"] = sha256_bytes(core)
    atomic_write_text(out / "SNAPSHOT.json", json.dumps(manifest, indent=2, sort_keys=True) + "\n")

    checksum_records = []
    for p in sorted(x for x in out.rglob("*") if x.is_file()):
        checksum_records.append(f"{sha256_file(p)}  {p.relative_to(out).as_posix()}")
    atomic_write_text(out / "SHA256SUMS.txt", "\n".join(checksum_records) + "\n")
    return manifest
