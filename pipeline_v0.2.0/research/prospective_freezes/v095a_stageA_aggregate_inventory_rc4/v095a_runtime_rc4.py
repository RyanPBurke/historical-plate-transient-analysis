"""OS-owned project lock and killable HTTP requests for the RC4 controller.

This module contains no catalogue queries. A child process performs one HTTP
operation; the controller owns its wall-clock deadline, including slow bodies.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
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
    def __init__(self, code, partial=b''):
        super().__init__(code)
        self.code = code
        self.partial = partial


class RequestDeadline(TransportFailure):
    pass


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
                            output.write(chunk)
                            output.flush()
                    output.flush(); os.fsync(output.fileno())
    except Exception as exc:
        metadata['error'] = 'HTTP_' + type(exc).__name__
    # This file is private transport IPC, removed before returning to the caller.
    # The controller takes cookies into memory; they never enter the job ledger.
    target = directory / 'transport.json'
    tmp = directory / 'transport.json.tmp'
    tmp.write_text(json.dumps(metadata), encoding='utf-8')
    os.replace(tmp, target)


def _stop_process(process):
    if process.is_alive():
        process.terminate(); process.join(2)
    if process.is_alive():
        process.kill(); process.join(2)
    if process.is_alive():
        raise SystemExit('TRANSPORT_CLEANUP_HOLD: HTTP child did not exit; no further requests permitted')


def isolated_request(payload, deadline, *, worker=_http_worker):
    """Run one operation under a parent-enforced monotonic deadline.

    No thread is left performing HTTP after a timeout or Ctrl+C. The worker
    argument is used only by the offline regression suite, never a CLI option.
    """
    if time.monotonic() >= deadline:
        raise RequestDeadline('HTTP_WALL_DEADLINE_HOLD')
    with tempfile.TemporaryDirectory(prefix='v095a_http_') as directory:
        process = multiprocessing.get_context('spawn').Process(
            target=worker, args=(payload, directory), daemon=True)
        process.start()
        try:
            while process.is_alive():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    _stop_process(process)
                    path = Path(directory) / 'body'
                    partial = path.read_bytes() if path.exists() else b''
                    raise RequestDeadline('HTTP_WALL_DEADLINE_HOLD', partial)
                process.join(min(remaining, 0.05))
            path = Path(directory) / 'body'
            body = path.read_bytes() if path.exists() else b''
            if time.monotonic() >= deadline:
                raise RequestDeadline('HTTP_WALL_DEADLINE_HOLD', body)
            result = Path(directory) / 'transport.json'
            if process.exitcode != 0 or not result.is_file():
                raise TransportFailure('HTTP_WORKER_FAILED_HOLD', body)
            metadata = json.loads(result.read_text(encoding='utf-8'))
            if metadata.get('error'):
                raise TransportFailure(metadata['error'], body)
            if time.monotonic() >= deadline:
                raise RequestDeadline('HTTP_WALL_DEADLINE_HOLD', body)
            return HTTPResponse(metadata['status'], metadata['headers'], body), metadata['cookies']
        finally:
            _stop_process(process)
            process.close()


class BoundedHTTP:
    def __init__(self, token='', *, operation_seconds=135, connect_seconds=15, read_seconds=120):
        self.headers = {'User-Agent': 'historical-plate-transient-analysis/v095a-stageA-rc4'}
        if token:
            if '\r' in token or '\n' in token:
                raise SystemExit('AUTHENTICATION_HOLD: invalid token encoding')
            self.headers['Authorization'] = token if token.lower().startswith('token ') else 'Token ' + token
        self.cookies = []
        self.operation_seconds = operation_seconds
        self.connect_seconds = connect_seconds
        self.read_seconds = read_seconds

    def request(self, method, url, *, deadline, data=None, max_bytes=8*1024*1024, read_body=True):
        end = min(deadline, time.monotonic() + self.operation_seconds)
        remaining = end - time.monotonic()
        if remaining <= 0:
            raise RequestDeadline('HTTP_WALL_DEADLINE_HOLD')
        payload = {'method': method, 'url': url, 'data': data, 'headers': self.headers,
                   'cookies': self.cookies, 'max_bytes': max_bytes, 'read_body': read_body,
                   'timeout': (min(self.connect_seconds, remaining), min(self.read_seconds, remaining))}
        response, self.cookies = isolated_request(payload, end)
        return response
