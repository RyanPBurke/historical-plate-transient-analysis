"""Durable, aggregate-only TAP batch lifecycle. Query text comes from the frozen runner."""
from pathlib import Path
from datetime import datetime, timezone
from urllib.parse import urljoin, urlsplit
import hashlib
import json
import math
import os
import re
import tempfile
import time

from v095a_runtime_rc9 import TransportFailure, RequestDeadline

BASE = 'https://www.plate-archive.org/tap/async'
TERMINAL = {'COMPLETED', 'ERROR', 'ABORTED'}
ACTIVE = {'PENDING', 'QUEUED', 'EXECUTING', 'HELD', 'SUSPENDED', 'UNKNOWN'}
RETRY_DELAYS = (30, 120)
DEADLINE = 3900
HTTP_BUDGET = 135
BODY_LIMIT = 8 * 1024 * 1024
SUBMISSION_BODY_LIMIT = 64 * 1024
ACCEPTED_SUBMISSION_STATUSES = {201, 302, 303}
EXPLICIT_REJECTION_STATUSES = set(range(400, 500)) - {408}


def digest(data):
    return hashlib.sha256(data).hexdigest()


def canonical(value):
    return digest(json.dumps(value, sort_keys=True, separators=(',', ':')).encode())


def atomic_bytes(path, data):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=path.name+'.', suffix='.tmp', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data); stream.flush(); os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name): os.unlink(name)


def atomic_json(path, value):
    atomic_bytes(path, (json.dumps(value, sort_keys=True, indent=2)+'\n').encode())


def job_url(value):
    value = value.rstrip('/')
    if not re.fullmatch(re.escape(BASE)+r'/[A-Za-z0-9_-]+', value):
        raise ValueError('TAP_JOB_URL_HOLD: unexpected job origin/path')
    return value


def timestamp(clock):
    return datetime.fromtimestamp(clock.time(), timezone.utc).isoformat()


def remaining(attempt, clock):
    # UTC preserves the expiry across restarts; monotonic time can only shorten it.
    wall = attempt['deadline_epoch'] - clock.time()
    if clock.time() < attempt['submitted_epoch']:
        raise ValueError('CLOCK_HOLD: clock precedes submission')
    if clock.monotonic() >= attempt['submitted_monotonic']:
        wall = min(wall, attempt['deadline_monotonic'] - clock.monotonic())
    return max(0.0, min(DEADLINE, wall))


def header_receipt_hash(value):
    payload = {
        'schema_version': value.get('schema_version'),
        'status': value.get('status'),
        'headers': value.get('headers'),
        'received_epoch': value.get('received_epoch'),
        'received_monotonic': value.get('received_monotonic'),
    }
    return canonical(payload)


def make_header_receipt(status, headers, received_epoch=None, received_monotonic=None, *, clock=time):
    safe = {}
    for key in ('location', 'content-type', 'content-length'):
        value = (headers or {}).get(key)
        if value is not None:
            safe[key] = str(value)
    if received_epoch is None:
        received_epoch = clock.time()
    if received_monotonic is None:
        received_monotonic = clock.monotonic()
    value = {
        'schema_version': 2, 'status': int(status), 'headers': safe,
        'received_epoch': float(received_epoch),
        'received_monotonic': float(received_monotonic),
    }
    value['receipt_sha256'] = header_receipt_hash(value)
    return value


def validate_header_receipt(directory, attempt, required=False):
    name = attempt.get('header_receipt_file')
    if not name or not re.fullmatch(r'attempt_[0-9]{2}_submission_headers\.json', name):
        if required:
            raise ValueError('durable header receipt file required')
        return None
    path = directory / name
    if not path.is_file():
        if required:
            raise ValueError('durable header receipt missing')
        return None
    value = json.loads(path.read_text(encoding='utf-8'))
    if value.get('schema_version') != 2 or not isinstance(value.get('headers'), dict):
        raise ValueError('durable header receipt schema')
    if set(value['headers']) - {'location','content-type','content-length'}:
        raise ValueError('durable header receipt headers')
    status = value.get('status')
    if not isinstance(status, int) or status < 100 or status > 599:
        raise ValueError('durable header receipt status')
    received_epoch = value.get('received_epoch')
    received_monotonic = value.get('received_monotonic')
    if (not isinstance(received_epoch, (int, float)) or isinstance(received_epoch, bool) or
            not isinstance(received_monotonic, (int, float)) or isinstance(received_monotonic, bool) or
            not math.isfinite(float(received_epoch)) or not math.isfinite(float(received_monotonic)) or
            received_epoch < 0 or received_monotonic < 0):
        raise ValueError('durable header receipt timing')
    if value.get('receipt_sha256') != header_receipt_hash(value):
        raise ValueError('durable header receipt hash')
    return value


def receipt_hash(value):
    payload = {k: value.get(k) for k in (
        'status','headers','body_sha256','body_bytes','artifact','partial',
        'transport_failure','header_receipt_file','header_receipt_sha256',
        'header_received_epoch','header_received_monotonic')}
    return canonical(payload)


def validate_submission_evidence(directory, attempt, required=False):
    sr = attempt.get('submission_response')
    if sr is None:
        # A SUBMITTING attempt may have received headers immediately before a
        # controller crash. Preserve/validate that sidecar even before the
        # final response envelope exists.
        hdr = validate_header_receipt(directory, attempt, required=False)
        recorded = attempt.get('interrupted_header_receipt_sha256')
        if recorded is not None and (hdr is None or recorded != hdr.get('receipt_sha256')):
            raise ValueError('interrupted header receipt binding')
        if required:
            raise ValueError('submission evidence required')
        return
    if not isinstance(sr, dict) or not isinstance(sr.get('headers'), dict):
        raise ValueError('submission evidence schema')
    if set(sr['headers']) - {'location','content-type','content-length'}:
        raise ValueError('submission evidence headers')
    status = sr.get('status')
    if status is not None and (not isinstance(status,int) or status < 100 or status > 599):
        raise ValueError('submission evidence status')
    name = sr.get('artifact')
    artifacts = attempt.get('artifacts', [])
    matching = [x for x in artifacts if x.get('file') == name and x.get('kind') == 'submission']
    if len(matching) != 1:
        raise ValueError('submission evidence artifact')
    raw = (directory/name).read_bytes()
    if digest(raw) != sr.get('body_sha256') or len(raw) != sr.get('body_bytes'):
        raise ValueError('submission evidence body')
    if bool(matching[0].get('partial')) != bool(sr.get('partial')):
        raise ValueError('submission evidence partial')

    if status is not None:
        hdr = validate_header_receipt(directory, attempt, required=True)
        if sr.get('header_receipt_file') != attempt.get('header_receipt_file'):
            raise ValueError('submission header receipt file binding')
        if sr.get('header_receipt_sha256') != hdr.get('receipt_sha256'):
            raise ValueError('submission header receipt hash binding')
        if hdr.get('status') != status or hdr.get('headers') != sr.get('headers'):
            raise ValueError('submission header receipt semantic binding')
        if (sr.get('header_received_epoch') != hdr.get('received_epoch') or
                sr.get('header_received_monotonic') != hdr.get('received_monotonic')):
            raise ValueError('submission header receipt timing binding')
        hm = [x for x in artifacts if x.get('file') == attempt.get('header_receipt_file') and x.get('kind') == 'submission_headers']
        if len(hm) != 1 or digest((directory/attempt['header_receipt_file']).read_bytes()) != hm[0].get('sha256'):
            raise ValueError('submission header receipt artifact binding')
    else:
        if (sr.get('header_receipt_file') is not None or sr.get('header_receipt_sha256') is not None or
                sr.get('header_received_epoch') is not None or sr.get('header_received_monotonic') is not None):
            raise ValueError('header receipt present without received status')

    if sr.get('receipt_sha256') != receipt_hash(sr):
        raise ValueError('submission receipt envelope hash')

    disposition = attempt.get('submission_disposition')
    location = sr['headers'].get('location')
    if disposition == 'JOB_RECEIPT_VALIDATED':
        if status not in ACCEPTED_SUBMISSION_STATUSES or sr.get('partial') or sr.get('transport_failure'):
            raise ValueError('validated receipt disposition')
        if not attempt.get('job_url') or job_url(urljoin(BASE+'/', location or '')) != attempt['job_url']:
            raise ValueError('validated receipt job relationship')
    elif disposition == 'EXPLICIT_HTTP_REJECTION':
        if status not in EXPLICIT_REJECTION_STATUSES or attempt.get('job_url') or sr.get('partial') or sr.get('transport_failure'):
            raise ValueError('rejection receipt disposition')
    elif disposition == 'AMBIGUOUS_HTTP_RESPONSE':
        if status in ACCEPTED_SUBMISSION_STATUSES or status in EXPLICIT_REJECTION_STATUSES or attempt.get('job_url') or sr.get('partial') or sr.get('transport_failure'):
            raise ValueError('ambiguous receipt disposition')
    elif disposition == 'TRANSPORT_ACCEPTANCE_UNKNOWN':
        if status is not None or not sr.get('partial') or not sr.get('transport_failure') or attempt.get('job_url'):
            raise ValueError('transport-unknown receipt disposition')
    elif disposition == 'TRANSPORT_RESPONSE_INCOMPLETE':
        if status is None or not sr.get('partial') or not sr.get('transport_failure') or attempt.get('job_url'):
            raise ValueError('transport-incomplete receipt disposition')
    elif disposition == 'ACCEPTED_STATUS_WITHOUT_VALID_JOB_LOCATION':
        if status not in ACCEPTED_SUBMISSION_STATUSES or attempt.get('job_url') or sr.get('partial') or sr.get('transport_failure'):
            raise ValueError('invalid-location receipt disposition')
    elif disposition is not None:
        raise ValueError('unknown submission disposition')

    progressed = {'WAITING','FETCHING','VALIDATED','ABORT_PENDING','RETRYABLE'}
    state = attempt.get('state')
    if sr is not None and disposition is None:
        raise ValueError('submission disposition required with final receipt envelope')
    if state in progressed:
        if disposition != 'JOB_RECEIPT_VALIDATED':
            raise ValueError('attempt state requires validated job receipt disposition')
        if status is None:
            raise ValueError('progressed attempt missing received status')
        hdr = validate_header_receipt(directory, attempt, required=True)
        if (attempt.get('submitted_epoch') != hdr.get('received_epoch') or
                attempt.get('submitted_monotonic') != hdr.get('received_monotonic') or
                attempt.get('deadline_epoch') != hdr.get('received_epoch') + DEADLINE or
                attempt.get('deadline_monotonic') != hdr.get('received_monotonic') + DEADLINE):
            raise ValueError('job deadline is not bound to header receipt time')
    elif state == 'SUBMITTING' and disposition == 'JOB_RECEIPT_VALIDATED':
        # A crash between disposition persistence and WAITING persistence is
        # deliberately a HOLD.  Preserve the known job; never infer permission
        # to resubmit from an incomplete lifecycle transition.
        raise ValueError('validated job receipt without progressed attempt state')


def validate_checkpoint(directory, meta, query, fields, parse, validate, expected, context):
    try:
        if meta['schema_version'] != 4 or meta['query_sha256'] != digest(query):
            raise ValueError('identity')
        if meta['context_sha256'] != canonical(context) or meta['expected_keys_sha256'] != canonical(expected):
            raise ValueError('provenance')
        if (directory/'query.sql').read_bytes() != query:
            raise ValueError('query bytes')
        attempts = meta['attempts']
        if len(attempts) > 3 or [a['attempt'] for a in attempts] != list(range(1, len(attempts)+1)):
            raise ValueError('attempt history')
        for a in attempts:
            if a.get('query_sha256') != digest(query):
                raise ValueError('attempt query identity')
            expected_header = f"attempt_{a['attempt']:02d}_submission_headers.json"
            if a.get('header_receipt_file') != expected_header:
                raise ValueError('header receipt filename identity')
            if a.get('job_url'):
                job_url(a['job_url'])
            artifacts = a.get('artifacts', [])
            for artifact in artifacts:
                name = artifact['file']
                if not re.fullmatch(r'attempt_[0-9]{2}_(?:submission_(?:response|partial)\.bin|submission_headers\.json|response_[0-9]{2}\.(?:csv|partial))', name):
                    raise ValueError('artifact path')
                if digest((directory/name).read_bytes()) != artifact['sha256']:
                    raise ValueError('attempt artifact hash')
            required = a.get('state') in {'WAITING','FETCHING','VALIDATED','ABORT_PENDING','RETRYABLE'} or a.get('submission_disposition') is not None
            validate_submission_evidence(directory, a, required=required)
        if meta['status'] == 'COMPLETED_VALIDATED':
            if not attempts or attempts[-1]['state'] != 'VALIDATED':
                raise ValueError('completion history')
            raw = (directory/'result.csv').read_bytes()
            if digest(raw) != meta['result_sha256'] or digest(raw) != attempts[-1]['result_sha256']:
                raise ValueError('result hash')
            rows = parse(raw, fields, meta['family']); validate(rows, expected)
            return rows
        return None
    except (ValueError, KeyError, TypeError, OSError, json.JSONDecodeError) as exc:
        raise SystemExit('CHECKPOINT_HOLD: invalid evidence; preserve/restore checkpoint, do not resubmit') from exc

def run_batch(client, family, number, query, fields, parse, validate, expected,
              work, counters, *, owner, context, clock=time):
    work = Path(work)
    owner.require(work.parent.parent)
    directory = work/'jobs'/family/f'batch_{number:04d}'
    meta_path = directory/'meta.json'
    if directory.exists():
        try: meta = json.loads(meta_path.read_text(encoding='utf-8'))
        except (OSError, ValueError) as exc:
            raise SystemExit('CHECKPOINT_HOLD: missing/invalid durable job record; no resubmission') from exc
        if meta.get('family') != family or meta.get('batch') != number:
            raise SystemExit('CHECKPOINT_HOLD: batch identity mismatch')
        cached = validate_checkpoint(directory, meta, query, fields, parse, validate, expected, context)
        if cached is not None:
            print(f'[{family}] batch {number}: resume PASS', flush=True)
            return cached
    else:
        directory.mkdir(parents=True, exist_ok=False)
        atomic_bytes(directory/'query.sql', query)
        meta = {'schema_version': 4, 'status': 'IN_PROGRESS', 'family': family, 'batch': number,
                'query_sha256': digest(query), 'context_sha256': canonical(context),
                'expected_keys_sha256': canonical(expected), 'attempts': [],
                'transport_request_attempts': 0, 'created_utc': timestamp(clock)}
        atomic_json(meta_path, meta)

    def save():
        meta['updated_utc'] = timestamp(clock); atomic_json(meta_path, meta)

    def hold(code):
        meta['status'] = 'FAILED_HOLD'; meta['failure'] = code; save()
        raise SystemExit(code)

    if meta['status'] == 'FAILED_HOLD':
        raise SystemExit(meta.get('failure', 'CHECKPOINT_HOLD: failed batch requires review'))
    if meta['status'] != 'IN_PROGRESS':
        hold('CHECKPOINT_HOLD: unknown batch status')

    def request(method, url, *, end, data=None, max_bytes=BODY_LIMIT, read_body=True, durable_receipt_path=None, durable_partial_body_path=None):
        if clock.monotonic() >= end: raise RequestDeadline('HTTP_WALL_DEADLINE_HOLD')
        meta['transport_request_attempts'] += 1
        counter = 'catalogue_tap_metadata_binding_calls' if family.startswith('Q0_') else 'catalogue_tap_aggregate_inventory_calls'
        counters[counter] += 1
        save()  # Counts attempted requests, including transport failures.
        response = client.request(method, url, deadline=end, data=data,
                                  max_bytes=max_bytes, read_body=read_body, durable_receipt_path=durable_receipt_path,
                                  durable_partial_body_path=durable_partial_body_path)
        if clock.monotonic() >= end:
            raise RequestDeadline('HTTP_WALL_DEADLINE_HOLD', response.body, response.status, response.headers)
        return response

    def checked_get(url, end, max_bytes):
        # GET redirects remain on the archive origin, with one shared deadline.
        for _ in range(4):
            response = request('GET', url, end=end, max_bytes=max_bytes)
            if response.status in (301, 302, 303, 307, 308):
                target = urljoin(url, response.headers.get('location', ''))
                u = urlsplit(target)
                if u.scheme != 'https' or u.netloc != 'www.plate-archive.org' or u.username or u.password:
                    raise ValueError('TAP_REDIRECT_HOLD: unexpected result origin')
                url = target
                continue
            if response.status != 200:
                raise TransportFailure(f'TAP_HTTP_STATUS_{response.status}_HOLD', response.body)
            return response
        raise ValueError('TAP_REDIRECT_HOLD: redirect limit')

    def phase(a, end):
        response = checked_get(job_url(a['job_url'])+'/phase', end, 4096)
        try: value = response.body.decode('ascii').strip().upper()
        except UnicodeError: raise ValueError('TAP_PHASE_HOLD: invalid phase encoding')
        if value not in TERMINAL | ACTIVE:
            raise ValueError('TAP_PHASE_HOLD: unknown phase')
        a['events'].append({'utc': timestamp(clock), 'phase': value})
        save()
        return value

    def abort(a):
        a['state'] = 'ABORT_PENDING'; save()
        end = clock.monotonic() + HTTP_BUDGET
        try:
            ack = request('POST', job_url(a['job_url'])+'/phase', end=end,
                          data={'PHASE': 'ABORT'}, max_bytes=4096, read_body=False)
            a['abort_http_acknowledged'] = ack.status in (200, 202, 204, 303)
            save()
            while clock.monotonic() < end:
                seen = phase(a, end)
                if seen in TERMINAL:
                    a['abort_terminal_phase'] = seen
                    a['state'] = 'RETRYABLE'; a['finished_epoch'] = clock.time(); save()
                    return True
                clock.sleep(min(5, max(0, end-clock.monotonic())))
        except (TransportFailure, ValueError):
            pass
        a['abort_confirmation_pending'] = True; save()
        return False

    def retain(a, body, partial=False):
        artifacts = a.setdefault('artifacts', [])
        result_count = sum(1 for x in artifacts if '_response_' in x.get('file', ''))
        name = f"attempt_{a['attempt']:02d}_response_{result_count+1:02d}."+('partial' if partial else 'csv')
        atomic_bytes(directory/name, body)
        artifacts.append({'file': name, 'sha256': digest(body), 'bytes': len(body), 'partial': partial, 'kind': 'result'})
        save()

    def retain_submission(a, *, status=None, headers=None, body=b'', partial=False, transport_failure=None):
        header_name = a['header_receipt_file']
        header_path = directory / header_name
        header = None
        if status is not None:
            if header_path.exists():
                header = validate_header_receipt(directory, a, required=True)
                expected_header = make_header_receipt(
                    status, headers, header['received_epoch'], header['received_monotonic'])
                if header['status'] != expected_header['status'] or header['headers'] != expected_header['headers']:
                    raise ValueError('durable header receipt differs from returned response')
            else:
                # Synthetic clients and a normal parent path may not use the
                # worker-side sink. Persist before interpreting the receipt.
                header = make_header_receipt(status, headers, clock=clock)
                atomic_json(header_path, header)

        name = f"attempt_{a['attempt']:02d}_submission_" + ('partial.bin' if partial else 'response.bin')
        atomic_bytes(directory/name, body)
        record = {'file': name, 'sha256': digest(body), 'bytes': len(body),
                  'partial': bool(partial), 'kind': 'submission'}
        artifacts = a.setdefault('artifacts', [])
        artifacts[:] = [x for x in artifacts if x.get('kind') not in {'submission','submission_headers'}]
        if header is not None:
            artifacts.append({'file': header_name, 'sha256': digest(header_path.read_bytes()),
                              'bytes': header_path.stat().st_size, 'partial': False,
                              'kind': 'submission_headers'})
        artifacts.append(record)
        safe = {}
        for key in ('location', 'content-type', 'content-length'):
            value = (headers or {}).get(key)
            if value is not None:
                safe[key] = str(value)
        a['submission_response'] = {
            'status': int(status) if status is not None else None,
            'headers': safe,
            'body_sha256': record['sha256'], 'body_bytes': record['bytes'],
            'artifact': name, 'partial': bool(partial),
            'transport_failure': transport_failure,
            'header_receipt_file': header_name if header is not None else None,
            'header_receipt_sha256': header.get('receipt_sha256') if header is not None else None,
            'header_received_epoch': header.get('received_epoch') if header is not None else None,
            'header_received_monotonic': header.get('received_monotonic') if header is not None else None,
        }
        a['submission_response']['receipt_sha256'] = receipt_hash(a['submission_response'])
        save()

    def record_interrupted_submission(a):
        header = validate_header_receipt(directory, a, required=False)
        if header is None:
            return
        a['interrupted_header_receipt_sha256'] = header['receipt_sha256']
        partial_path = directory / f"attempt_{a['attempt']:02d}_submission_partial.bin"
        body = partial_path.read_bytes() if partial_path.is_file() else b''
        if len(body) > SUBMISSION_BODY_LIMIT:
            raise ValueError('interrupted submission body exceeded configured bound')
        # Build the same hash-bound receipt envelope used for ordinary transport
        # failures. The attempt deliberately remains SUBMITTING/FAILED_HOLD; this
        # retained evidence never authorizes a replacement POST.
        retain_submission(a, status=header['status'], headers=header['headers'], body=body,
                          partial=True, transport_failure='CONTROLLER_INTERRUPT')
        a['submission_disposition'] = 'TRANSPORT_RESPONSE_INCOMPLETE'
        save()


    a = meta['attempts'][-1] if meta['attempts'] else None
    try:
        while True:
            if a is None or a['state'] == 'RETRYABLE':
                if len(meta['attempts']) >= 3:
                    hold('TAP_RETRY_LIMIT_HOLD: three job attempts exhausted')
                if a is not None:
                    delay = RETRY_DELAYS[len(meta['attempts'])-1]
                    clock.sleep(max(0, a['finished_epoch']+delay-clock.time()))
                attempt_no = len(meta['attempts'])+1
                a = {'attempt': attempt_no, 'state': 'SUBMITTING',
                     'query_sha256': digest(query), 'events': [], 'artifacts': [],
                     'header_receipt_file': f'attempt_{attempt_no:02d}_submission_headers.json'}
                meta['attempts'].append(a); save()  # Durable intent BEFORE POST.
                response = request('POST', BASE, end=clock.monotonic()+HTTP_BUDGET,
                                   data={'QUERY': query.decode('utf-8'), 'LANG': 'postgresql-9.6',
                                         'QUEUE': '1h', 'PHASE': 'RUN'}, max_bytes=SUBMISSION_BODY_LIMIT, read_body=True,
                                   durable_receipt_path=directory/a['header_receipt_file'],
                                   durable_partial_body_path=directory/f"attempt_{attempt_no:02d}_submission_partial.bin")
                # Receipt evidence is durable BEFORE status/location interpretation. Never print the body.
                retain_submission(a, status=response.status, headers=response.headers, body=response.body)
                if response.status not in ACCEPTED_SUBMISSION_STATUSES:
                    if response.status in EXPLICIT_REJECTION_STATUSES:
                        a['submission_disposition'] = 'EXPLICIT_HTTP_REJECTION'; save()
                        hold(f'TAP_SUBMISSION_REJECTED_HOLD: HTTP {response.status}; response preserved; do not resubmit')
                    a['submission_disposition'] = 'AMBIGUOUS_HTTP_RESPONSE'; save()
                    hold(f'SUBMISSION_UNCERTAIN_HOLD: HTTP {response.status}; response preserved; do not resubmit')
                try:
                    a['job_url'] = job_url(urljoin(BASE+'/', response.headers.get('location', '')))
                except ValueError:
                    a['submission_disposition'] = 'ACCEPTED_STATUS_WITHOUT_VALID_JOB_LOCATION'; save()
                    hold('SUBMISSION_UNCERTAIN_HOLD: accepted response without valid job Location; response preserved; do not resubmit')
                a['submission_disposition'] = 'JOB_RECEIPT_VALIDATED'; save()
                header = validate_header_receipt(directory, a, required=True)
                a.update(state='WAITING', submitted_epoch=header['received_epoch'],
                         submitted_monotonic=header['received_monotonic'],
                         deadline_epoch=header['received_epoch']+DEADLINE,
                         deadline_monotonic=header['received_monotonic']+DEADLINE)
                save()  # Job identity and original receipt-time budget are durable BEFORE any polling.
            elif a['state'] == 'SUBMITTING':
                record_interrupted_submission(a)
                hold('SUBMISSION_UNCERTAIN_HOLD: interrupted submission; durable header/body evidence retained if received; reconcile the existing job')

            if a['state'] == 'ABORT_PENDING':
                if not abort(a): raise SystemExit('ABORT_UNCONFIRMED_HOLD: existing job retained; no new submission')
                continue
            if a['state'] == 'WAITING':
                left = remaining(a, clock)
                if left <= 0:
                    a['failure'] = 'TAP_TIMEOUT_HOLD'
                    if not abort(a): raise SystemExit('ABORT_UNCONFIRMED_HOLD: existing job retained')
                    continue
                try:
                    observed = phase(a, clock.monotonic()+left)
                except TransportFailure as exc:
                    a['failure'] = 'TAP_TIMEOUT_HOLD' if remaining(a, clock) <= 0 else exc.code
                    save()
                    if not abort(a): raise SystemExit('ABORT_UNCONFIRMED_HOLD: existing job retained')
                    continue
                # Check again AFTER receipt; a late COMPLETED phase is not accepted.
                if remaining(a, clock) <= 0:
                    a['failure'] = 'TAP_TIMEOUT_HOLD'
                    if not abort(a): raise SystemExit('ABORT_UNCONFIRMED_HOLD: existing job retained')
                    continue
                if observed == 'COMPLETED':
                    a['state'] = 'FETCHING'; a['fetch_attempts'] = 0; save()
                elif observed in ('ERROR', 'ABORTED'):
                    a.update(state='RETRYABLE', failure='TAP_JOB_'+observed+'_HOLD', finished_epoch=clock.time()); save()
                    continue
                else:
                    elapsed = DEADLINE-remaining(a, clock)
                    interval = 5 if elapsed < 60 else 15 if elapsed < 600 else 30
                    clock.sleep(min(interval, remaining(a, clock))); continue
            if a['state'] == 'FETCHING':
                if a['fetch_attempts'] >= 3:
                    hold('TAP_RESULT_RETRY_LIMIT_HOLD: existing completed job retained')
                if a['fetch_attempts']:
                    wait = RETRY_DELAYS[a['fetch_attempts']-1]
                    clock.sleep(max(0, a.get('fetch_finished_epoch', clock.time())+wait-clock.time()))
                a['fetch_attempts'] += 1; save()
                try:
                    raw = checked_get(job_url(a['job_url'])+'/results/csv', clock.monotonic()+HTTP_BUDGET, BODY_LIMIT).body
                except TransportFailure as exc:
                    retain(a, exc.partial, partial=True)
                    a['fetch_finished_epoch'] = clock.time(); a['fetch_failure'] = exc.code; save()
                    continue
                retain(a, raw)
                rows = parse(raw, fields, family); validate(rows, expected)
                atomic_bytes(directory/'result.csv', raw)
                a['state'] = 'VALIDATED'; a['result_sha256'] = digest(raw)
                meta.update(status='COMPLETED_VALIDATED', result_sha256=digest(raw), validated_utc=timestamp(clock))
                save()
                print(f'[{family}] batch {number}: PASS rows={len(rows)}', flush=True)
                return rows
            if a['state'] not in ('WAITING', 'FETCHING', 'RETRYABLE', 'ABORT_PENDING'):
                hold('CHECKPOINT_HOLD: unknown attempt state')
    except KeyboardInterrupt:
        meta['interrupted_utc'] = timestamp(clock); save()
        if a and a.get('job_url') and a['state'] in ('WAITING', 'ABORT_PENDING'):
            try: abort(a)
            except KeyboardInterrupt: save()
        elif a and a['state'] == 'SUBMITTING':
            record_interrupted_submission(a)
            meta.update(status='FAILED_HOLD', failure='SUBMISSION_UNCERTAIN_HOLD'); save()
        raise SystemExit('INTERRUPTED_HOLD: durable state retained; resume uses existing job/budget')
    except ValueError as exc:
        hold(str(exc))
    except TransportFailure as exc:
        # POST acceptance cannot safely be inferred from a transport failure. Preserve any received bytes.
        if a:
            a['transport_failure'] = exc.code
            if a.get('state') == 'SUBMITTING':
                retain_submission(a, status=exc.status, headers=exc.headers, body=exc.partial or b'', partial=True, transport_failure=exc.code)
                a['submission_disposition'] = ('TRANSPORT_RESPONSE_INCOMPLETE' if exc.status is not None else 'TRANSPORT_ACCEPTANCE_UNKNOWN')
            save()
        hold('SUBMISSION_UNCERTAIN_HOLD: reconcile receipt before further submission')
