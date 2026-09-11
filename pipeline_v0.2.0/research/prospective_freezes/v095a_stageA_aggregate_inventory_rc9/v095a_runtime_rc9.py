"""OS-owned project lock and killable HTTP requests for the RC9 controller.

This module contains no catalogue queries. A child process performs one HTTP
operation; the controller owns its wall-clock deadline, including slow bodies.
For submission POSTs, sanitized status/Location evidence can also be written
atomically to a caller-supplied durable receipt path immediately after headers
arrive, before any response body is streamed.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import hashlib
import json
import multiprocessing
import os
import tempfile
import time


class ProjectLock:
    """An OS lock, automatically released if its owning process exits."""
    def __init__(self, project):
        self.project = Path(project).resolve()
        self.file = None

    def __enter__(self):
        path = self.project / 'work/v095a_stageA_controller.lock'
        path.parent.mkdir(parents=True, exist_ok=True)
        self.file = path.open('a+b')
        try:
            if path.stat().st_size == 0:
                self.file.write(b'0'); self.file.flush()
            self.file.seek(0)
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (OSError, BlockingIOError):
            self.file.close(); self.file = None
            raise SystemExit('CONTROLLER_LOCK_HOLD: another Stage A controller owns this project')
        return self

    def require(self, project):
        if self.file is None or self.file.closed or Path(project).resolve() != self.project:
            raise SystemExit('CONTROLLER_LOCK_HOLD: project ownership required')

    def __exit__(self, *args):
        if self.file is not None:
            try:
                self.file.seek(0)
                if os.name == 'nt':
                    import msvcrt
                    msvcrt.locking(self.file.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(self.file.fileno(), fcntl.LOCK_UN)
            finally:
                self.file.close(); self.file = None


@dataclass
class HTTPResponse:
    status: int
    headers: dict
    body: bytes


class TransportFailure(Exception):
    def __init__(self, code, partial=b'', status=None, headers=None):
        super().__init__(code)
        self.code = code
        self.partial = partial
        self.status = status
        self.headers = dict(headers or {})


class RequestDeadline(TransportFailure):
    pass


def _canonical_receipt_payload(status, headers, received_epoch=None, received_monotonic=None):
    safe = {}
    for key in ('location', 'content-type', 'content-length'):
        value = (headers or {}).get(key)
        if value is not None:
            safe[key] = str(value)
    # Receipt time is captured at the same boundary as status/headers.  It is
    # part of the canonical sidecar so later body collection cannot extend the
    # per-job terminal budget.
    if received_epoch is None:
        received_epoch = time.time()
    if received_monotonic is None:
        received_monotonic = time.monotonic()
    payload = {
        'schema_version': 2, 'status': int(status), 'headers': safe,
        'received_epoch': float(received_epoch),
        'received_monotonic': float(received_monotonic),
    }
    raw = json.dumps(payload, sort_keys=True, separators=(',', ':')).encode('utf-8')
    payload['receipt_sha256'] = hashlib.sha256(raw).hexdigest()
    return payload


def _atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix=path.name + '.', suffix='.tmp', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8', newline='\n') as stream:
            json.dump(value, stream, sort_keys=True, separators=(',', ':'))
            stream.write('\n')
            stream.flush(); os.fsync(stream.fileno())
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def _atomic_bytes(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix=path.name + '.', suffix='.tmp', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
            stream.flush(); os.fsync(stream.fileno())
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def _http_worker(payload, directory):
    # Never serialize tokens, cookie values or exception messages into audit files.
    directory = Path(directory)
    metadata = {'status': 0, 'headers': {}, 'error': None, 'cookies': []}
    try:
        import requests
        with requests.Session() as session:
            session.headers.update(payload['headers'])
            for cookie in payload['cookies']:
                session.cookies.set_cookie(requests.cookies.create_cookie(**cookie))
            with session.request(payload['method'], payload['url'], data=payload['data'],
                                 timeout=payload['timeout'], stream=True,
                                 allow_redirects=False) as response:
                metadata['status'] = response.status_code
                metadata['headers'] = {k.lower(): v for k, v in response.headers.items()
                                       if k.lower() in ('location', 'content-type', 'content-length')}

                # IPC receipt supports the current request result. The optional
                # durable receipt lives in the batch work directory and survives
                # controller/worker interruption after headers arrive.
                received_epoch = time.time()
                received_monotonic = time.monotonic()
                receipt = _canonical_receipt_payload(
                    metadata['status'], metadata['headers'], received_epoch, received_monotonic)
                _atomic_json(directory / 'receipt.json', receipt)
                durable = payload.get('durable_receipt_path')
                if durable:
                    _atomic_json(Path(durable), receipt)

                metadata['cookies'] = [
                    {'name': c.name, 'value': c.value, 'domain': c.domain,
                     'path': c.path, 'secure': c.secure, 'expires': c.expires}
                    for c in session.cookies
                ]
                total = 0
                with (directory / 'body').open('wb') as output:
                    if payload['read_body']:
                        for chunk in response.iter_content(chunk_size=8192):
                            total += len(chunk)
                            if total > payload['max_bytes']:
                                metadata['error'] = 'RESPONSE_SIZE_HOLD'
                                break
                            output.write(chunk); output.flush(); os.fsync(output.fileno())
                    output.flush(); os.fsync(output.fileno())
    except Exception as exc:
        metadata['error'] = 'HTTP_' + type(exc).__name__
    _atomic_json(directory / 'transport.json', metadata)


def _stop_process(process):
    if process.is_alive():
        process.terminate(); process.join(2)
    if process.is_alive():
        process.kill(); process.join(2)
    if process.is_alive():
        raise SystemExit('TRANSPORT_CLEANUP_HOLD: HTTP child did not exit; no further requests permitted')


def isolated_request(payload, deadline, *, worker=_http_worker):
    """Run one operation under a parent-enforced deadline.

    A submission caller may supply ``durable_receipt_path`` and
    ``durable_partial_body_path``. The worker writes sanitized response
    status/headers immediately after headers arrive. If the controller is
    interrupted while the spawned worker is streaming a bounded body, the
    controller stops the worker and atomically copies the already-fsynced bytes
    out of the temporary IPC directory before cleanup.
    """
    if time.monotonic() >= deadline:
        raise RequestDeadline('HTTP_WALL_DEADLINE_HOLD')
    with tempfile.TemporaryDirectory(prefix='v095a_http_') as directory:
        directory = Path(directory)
        process = multiprocessing.get_context('spawn').Process(
            target=worker, args=(payload, directory), daemon=True)
        process.start()

        def receipt():
            p = directory / 'receipt.json'
            if not p.is_file():
                return None, {}
            try:
                value = json.loads(p.read_text(encoding='utf-8'))
                status = value.get('status'); headers = value.get('headers') or {}
                if not isinstance(status, int) or not isinstance(headers, dict):
                    return None, {}
                return status, headers
            except Exception:
                return None, {}

        def preserve_interrupted_body():
            target = payload.get('durable_partial_body_path')
            source = directory / 'body'
            if not target or not source.is_file():
                return
            raw = source.read_bytes()
            if len(raw) > int(payload.get('max_bytes', len(raw))):
                raise SystemExit('TRANSPORT_CLEANUP_HOLD: buffered body exceeded configured bound')
            _atomic_bytes(Path(target), raw)

        try:
            while process.is_alive():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    _stop_process(process)
                    body = (directory/'body').read_bytes() if (directory/'body').exists() else b''
                    status, headers = receipt()
                    raise RequestDeadline('HTTP_WALL_DEADLINE_HOLD', body, status, headers)
                process.join(min(remaining, 0.05))
            body = (directory/'body').read_bytes() if (directory/'body').exists() else b''
            status, headers = receipt()
            if time.monotonic() >= deadline:
                raise RequestDeadline('HTTP_WALL_DEADLINE_HOLD', body, status, headers)
            result = directory/'transport.json'
            if process.exitcode != 0 or not result.is_file():
                raise TransportFailure('HTTP_WORKER_FAILED_HOLD', body, status, headers)
            metadata = json.loads(result.read_text(encoding='utf-8'))
            status = metadata.get('status') or status
            headers = metadata.get('headers') or headers
            if metadata.get('error'):
                raise TransportFailure(metadata['error'], body, status, headers)
            return HTTPResponse(status, headers, body), metadata.get('cookies', [])
        except BaseException:
            # KeyboardInterrupt/SystemExit can arrive while the child owns the
            # stream. Stop it first, then preserve the fsynced bounded bytes
            # before TemporaryDirectory removes the IPC body.
            _stop_process(process)
            preserve_interrupted_body()
            raise
        finally:
            _stop_process(process)
            process.close()


class BoundedHTTP:
    def __init__(self, token='', *, operation_seconds=135, connect_seconds=15, read_seconds=120):
        self.headers = {'User-Agent': 'historical-plate-transient-analysis/v095a-stageA-rc9'}
        if token:
            if '\r' in token or '\n' in token:
                raise SystemExit('AUTHENTICATION_HOLD: invalid token encoding')
            self.headers['Authorization'] = token if token.lower().startswith('token ') else 'Token ' + token
        self.cookies = []
        self.operation_seconds = operation_seconds
        self.connect_seconds = connect_seconds
        self.read_seconds = read_seconds

    def request(self, method, url, *, deadline, data=None, max_bytes=8*1024*1024,
                read_body=True, durable_receipt_path=None, durable_partial_body_path=None):
        end = min(deadline, time.monotonic() + self.operation_seconds)
        remaining = end - time.monotonic()
        if remaining <= 0:
            raise RequestDeadline('HTTP_WALL_DEADLINE_HOLD')
        payload = {'method': method, 'url': url, 'data': data, 'headers': self.headers,
                   'cookies': self.cookies, 'max_bytes': max_bytes, 'read_body': read_body,
                   'timeout': (min(self.connect_seconds, remaining), min(self.read_seconds, remaining)),
                   'durable_receipt_path': str(durable_receipt_path) if durable_receipt_path else None,
                   'durable_partial_body_path': str(durable_partial_body_path) if durable_partial_body_path else None}
        response, self.cookies = isolated_request(payload, end)
        return response
