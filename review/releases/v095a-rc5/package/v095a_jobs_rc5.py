"""Durable, aggregate-only TAP batch lifecycle. Query text comes from the frozen runner."""
from pathlib import Path
from datetime import datetime, timezone
from urllib.parse import urljoin, urlsplit
import hashlib
import json
import os
import re
import tempfile
import time

from v095a_runtime_rc5 import TransportFailure, RequestDeadline

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


def validate_checkpoint(directory, meta, query, fields, parse, validate, expected, context):
    try:
        if meta['schema_version'] != 2 or meta['query_sha256'] != digest(query):
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
            if a.get('job_url'):
                job_url(a['job_url'])
            artifacts = a.get('artifacts', [])
            for artifact in artifacts:
                name = artifact['file']
                if not re.fullmatch(r'attempt_[0-9]{2}_(?:submission_(?:response|partial)\.bin|response_[0-9]{2}\.(?:csv|partial))', name):
                    raise ValueError('artifact path')
                if digest((directory/name).read_bytes()) != artifact['sha256']:
                    raise ValueError('attempt artifact hash')
            sr = a.get('submission_response')
            if sr is not None:
                if not isinstance(sr, dict) or not isinstance(sr.get('headers'), dict):
                    raise ValueError('submission evidence schema')
                if set(sr['headers']) - {'location', 'content-type', 'content-length'}:
                    raise ValueError('submission evidence headers')
                status = sr.get('status')
                if status is not None and (not isinstance(status, int) or status < 100 or status > 599):
                    raise ValueError('submission evidence status')
                name = sr.get('artifact')
                matching = [x for x in artifacts if x.get('file') == name and x.get('kind') == 'submission']
                if len(matching) != 1:
                    raise ValueError('submission evidence artifact')
                raw = (directory/name).read_bytes()
                if digest(raw) != sr.get('body_sha256') or len(raw) != sr.get('body_bytes'):
                    raise ValueError('submission evidence body')
                if bool(matching[0].get('partial')) != bool(sr.get('partial')):
                    raise ValueError('submission evidence partial')
        if meta['status'] == 'COMPLETED_VALIDATED':
            if not attempts or attempts[-1]['state'] != 'VALIDATED':
                raise ValueError('completion history')
            raw = (directory/'result.csv').read_bytes()
            if digest(raw) != meta['result_sha256'] or digest(raw) != attempts[-1]['result_sha256']:
                raise ValueError('result hash')
            rows = parse(raw, fields, meta['family']); validate(rows, expected)
            return rows
        return None
    except (ValueError, KeyError, TypeError, OSError) as exc:
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
        meta = {'schema_version': 2, 'status': 'IN_PROGRESS', 'family': family, 'batch': number,
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

    def request(method, url, *, end, data=None, max_bytes=BODY_LIMIT, read_body=True):
        if clock.monotonic() >= end: raise RequestDeadline('HTTP_WALL_DEADLINE_HOLD')
        meta['transport_request_attempts'] += 1
        counter = 'catalogue_tap_metadata_binding_calls' if family.startswith('Q0_') else 'catalogue_tap_aggregate_inventory_calls'
        counters[counter] += 1
        save()  # Counts attempted requests, including transport failures.
        response = client.request(method, url, deadline=end, data=data,
                                  max_bytes=max_bytes, read_body=read_body)
        if clock.monotonic() >= end:
            raise RequestDeadline('HTTP_WALL_DEADLINE_HOLD', response.body)
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
        name = f"attempt_{a['attempt']:02d}_submission_" + ('partial.bin' if partial else 'response.bin')
        atomic_bytes(directory/name, body)
        record = {
            'file': name, 'sha256': digest(body), 'bytes': len(body), 'partial': bool(partial),
            'kind': 'submission',
        }
        artifacts = a.setdefault('artifacts', [])
        artifacts[:] = [x for x in artifacts if x.get('kind') != 'submission']
        artifacts.append(record)
        safe = {}
        for key in ('location', 'content-type', 'content-length'):
            value = (headers or {}).get(key)
            if value is not None:
                safe[key] = str(value)
        a['submission_response'] = {
            'status': int(status) if status is not None else None,
            'headers': safe,
            'body_sha256': record['sha256'],
            'body_bytes': record['bytes'],
            'artifact': name,
            'partial': bool(partial),
            'transport_failure': transport_failure,
        }
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
                a = {'attempt': len(meta['attempts'])+1, 'state': 'SUBMITTING',
                     'query_sha256': digest(query), 'events': [], 'artifacts': []}
                meta['attempts'].append(a); save()  # Durable intent BEFORE POST.
                response = request('POST', BASE, end=clock.monotonic()+HTTP_BUDGET,
                                   data={'QUERY': query.decode('utf-8'), 'LANG': 'postgresql-9.6',
                                         'QUEUE': '1h', 'PHASE': 'RUN'}, max_bytes=SUBMISSION_BODY_LIMIT, read_body=True)
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
                a.update(state='WAITING', submitted_epoch=clock.time(),
                         submitted_monotonic=clock.monotonic(),
                         deadline_epoch=clock.time()+DEADLINE,
                         deadline_monotonic=clock.monotonic()+DEADLINE)
                save()  # Job identity is durable BEFORE any polling.
            elif a['state'] == 'SUBMITTING':
                hold('SUBMISSION_UNCERTAIN_HOLD: interrupted submission; reconcile the existing job')

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
            meta.update(status='FAILED_HOLD', failure='SUBMISSION_UNCERTAIN_HOLD'); save()
        raise SystemExit('INTERRUPTED_HOLD: durable state retained; resume uses existing job/budget')
    except ValueError as exc:
        hold(str(exc))
    except TransportFailure as exc:
        # POST acceptance cannot safely be inferred from a transport failure. Preserve any received bytes.
        if a:
            a['transport_failure'] = exc.code
            if a.get('state') == 'SUBMITTING':
                retain_submission(a, body=exc.partial or b'', partial=True, transport_failure=exc.code)
                a['submission_disposition'] = 'TRANSPORT_ACCEPTANCE_UNKNOWN'
            save()
        hold('SUBMISSION_UNCERTAIN_HOLD: reconcile receipt before further submission')
