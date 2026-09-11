"""Offline RC5 release probes; no HTTP or catalogue connection is possible.

Usage: python independent_rc5_probes.py /path/to/v095a_stageA_implementation_rc5
The supplied release directory is read/imported, never modified.
"""
from pathlib import Path
from collections import Counter
import contextlib
import copy
import io
import json
import sys
import tempfile
import time
import types

PACKAGE = Path(sys.argv[1]).resolve()
sys.path.insert(0, str(PACKAGE))
import v095a_jobs_rc5 as jobs
import v095a_runtime_rc5 as runtime
import test_v095a_rc5 as fixtures


def fake_response_worker(payload, directory):
    """Exercise the real transport worker with an entirely synthetic requests module."""
    class Response:
        status_code = payload['fake_status']
        headers = {'Location': jobs.BASE + '/synthetic_receipt',
                   'Content-Type': 'text/plain'}

        def __enter__(self): return self
        def __exit__(self, *args): pass

        def iter_content(self, chunk_size):
            yield b'prefix'
            if payload['fake_mode'] == 'stream_error':
                raise ConnectionError('synthetic stream interruption')
            if payload['fake_mode'] == 'overflow':
                yield b'x' * (payload['max_bytes'] + 1)
            if payload['fake_mode'] == 'deadline':
                while True:
                    time.sleep(0.025)
                    yield b'x'

    class Session:
        def __init__(self): self.headers = {}; self.cookies = []
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def request(self, *args, **kwargs): return Response()

    fake_requests = types.ModuleType('requests')
    fake_requests.Session = Session
    sys.modules['requests'] = fake_requests
    runtime._http_worker(payload, directory)


def transport_probe(mode, status):
    payload = {'method': 'POST', 'url': jobs.BASE, 'data': {}, 'headers': {},
               'cookies': [], 'timeout': (1, 1), 'read_body': True,
               'max_bytes': jobs.SUBMISSION_BODY_LIMIT,
               'fake_mode': mode, 'fake_status': status}
    fixture = fixtures.LifecycleTests('test_success_and_resume_without_requests')
    fixture.setUp()
    try:
        class TransportClient:
            calls = 0
            def request(self, method, url, **kwargs):
                self.calls += 1
                assert self.calls == 1 and method == 'POST' and url == jobs.BASE
                response, _ = runtime.isolated_request(
                    payload, time.monotonic() + (1.0 if mode == 'deadline' else 5.0),
                    worker=fake_response_worker)
                return response

        client = TransportClient()
        try:
            fixture.run_batch(client=client)
        except SystemExit as exc:
            hold = str(exc)
        else:
            raise AssertionError('Expected conservative submission HOLD')
        evidence = fixture.meta()['attempts'][0]['submission_response']
        return {'probe': mode, 'synthetic_received_status': status,
                'retained_status': evidence['status'],
                'retained_headers': evidence['headers'],
                'partial_bytes': evidence['body_bytes'],
                'requests': client.calls, 'hold': hold,
                'receipt_loss_reproduced': evidence['status'] is None and not evidence['headers']}
    finally:
        fixture.tearDown()


def checkpoint_probe(mutation):
    fixture = fixtures.LifecycleTests('test_success_and_resume_without_requests')
    fixture.setUp()
    try:
        with contextlib.redirect_stdout(io.StringIO()): fixture.run_batch()
        meta = fixture.meta()
        attempt = meta['attempts'][0]
        if mutation == 'change_status':
            attempt['submission_response']['status'] = 401
        elif mutation == 'change_location':
            attempt['submission_response']['headers']['location'] = 'https://example.invalid/other_job'
        elif mutation == 'remove_receipt':
            del attempt['submission_response']
            for item in attempt['artifacts']:
                if item.get('kind') == 'submission': (fixture.directory / item['file']).unlink()
            attempt['artifacts'] = [x for x in attempt['artifacts'] if x.get('kind') != 'submission']
        jobs.atomic_json(fixture.directory / 'meta.json', meta)
        before = len(fixture.client.requests)
        try:
            with contextlib.redirect_stdout(io.StringIO()): fixture.run_batch()
            accepted = True
        except SystemExit:
            accepted = False
        return {'probe': mutation, 'inconsistent_checkpoint_accepted': accepted,
                'new_requests': len(fixture.client.requests) - before}
    finally:
        fixture.tearDown()


if __name__ == '__main__':
    results = [transport_probe('stream_error', 303), transport_probe('overflow', 401),
               transport_probe('deadline', 303)]
    results += [checkpoint_probe(x) for x in ('change_status', 'change_location', 'remove_receipt')]
    print(json.dumps({'catalogue_calls': 0, 'network_calls': 0, 'results': results}, indent=2))
