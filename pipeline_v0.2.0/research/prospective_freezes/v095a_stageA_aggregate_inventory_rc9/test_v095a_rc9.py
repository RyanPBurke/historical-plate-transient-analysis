"""Offline release regressions: synthetic metadata/counts and simulated TAP only."""
from pathlib import Path
from collections import Counter
from unittest.mock import patch
import json
import multiprocessing
import os
import shutil
import tempfile
import time
import threading
import signal
import unittest
import sys
import types

import run_v095a_stageA_inventory_rc9 as runner
import v095a_jobs_rc9 as jobs
import v095a_runtime_rc9 as runtime
from v095a_runtime_rc9 import (ProjectLock, HTTPResponse, TransportFailure,
                               RequestDeadline, BoundedHTTP, isolated_request)

FAMILY = 'Q2_PHYSICAL_PLATE_PROCESSING_MULTIPLICITY'
HEADER = ','.join(runner.Q2_FIELDS)+'\n'
GOOD = (HEADER+'77,1,1,1,1,1\n').encode()
QUERY = runner.materialize(runner.extract_template(FAMILY), '/*__Q2_VALUES__*/', [(77,)])


class Clock:
    def __init__(self): self.elapsed = 0.0
    def time(self): return 1800000000+self.elapsed
    def monotonic(self): return self.elapsed
    def sleep(self, seconds): self.elapsed += seconds


class SimulatedCrash(BaseException): pass


class Client:
    def __init__(self, clock):
        self.clock = clock; self.requests = []; self.submissions = 0
        self.aborted = set(); self.errors = 0; self.body = GOOD
        self.crash = None; self.phase_hook = None; self.download_failures = 0
    def request(self, method, url, **kw):
        self.requests.append((method, url, kw.get('data')))
        if method == 'POST' and url == jobs.BASE:
            self.submissions += 1
            return HTTPResponse(303, {'location': jobs.BASE+f'/job{self.submissions}'}, b'')
        if method == 'POST':
            self.aborted.add(url.removesuffix('/phase'))
            return HTTPResponse(303, {}, b'')
        if url.endswith('/phase'):
            if self.crash is not None:
                exc, self.crash = self.crash, None
                raise exc
            if self.phase_hook is not None:
                self.phase_hook(self)
            if url.removesuffix('/phase') in self.aborted: value = 'ABORTED'
            elif self.errors > 0:
                self.errors -= 1; value = 'ERROR'
            else: value = 'COMPLETED'
            return HTTPResponse(200, {}, value.encode())
        if url.endswith('/results/csv'):
            if self.download_failures:
                self.download_failures -= 1
                raise TransportFailure('HTTP_ReadTimeout', b'partial aggregate')
            return HTTPResponse(200, {}, self.body)
        raise AssertionError('unexpected synthetic URL')


class DelayedSubmissionClient(Client):
    """Synthetic POST where headers arrive 120 s before body return."""
    def request(self, method, url, **kw):
        if method == 'POST' and url == jobs.BASE:
            self.requests.append((method, url, kw.get('data')))
            self.submissions += 1
            location = jobs.BASE+f'/job{self.submissions}'
            receipt = jobs.make_header_receipt(
                303, {'location': location}, self.clock.time(), self.clock.monotonic())
            jobs.atomic_json(Path(kw['durable_receipt_path']), receipt)
            self.clock.sleep(120)
            return HTTPResponse(303, {'location': location}, b'')
        return super().request(method, url, **kw)


def lock_child(project, output):
    try:
        with ProjectLock(project): Path(output).write_text('acquired')
    except SystemExit: Path(output).write_text('blocked')


def drip_worker(payload, directory):
    # Sends bytes frequently forever: an inactivity timeout would not end this.
    with (Path(directory)/'body').open('wb') as stream:
        while True:
            stream.write(b'x'); stream.flush(); time.sleep(0.025)

def durable_receipt_sleep_worker(payload, directory):
    path = Path(payload['durable_receipt_path'])
    runtime._atomic_json(path, runtime._canonical_receipt_payload(303, {'location': jobs.BASE+'/deadline_job'}))
    while True:
        time.sleep(0.05)

def durable_receipt_body_sleep_worker(payload, directory):
    directory = Path(directory)
    receipt = runtime._canonical_receipt_payload(303, {'location': jobs.BASE+'/interrupt_job'})
    runtime._atomic_json(directory/'receipt.json', receipt)
    runtime._atomic_json(Path(payload['durable_receipt_path']), receipt)
    with (directory/'body').open('wb') as stream:
        stream.write(b'bounded-partial-body')
        stream.flush(); os.fsync(stream.fileno())
    Path(payload['ready_path']).write_text('ready')
    while True:
        time.sleep(0.05)


class ParserTests(unittest.TestCase):
    def parse(self, row):
        return runner.validate_q2(runner.parse_csv_bytes((HEADER+row).encode(), runner.Q2_FIELDS, FAMILY), [77])
    def test_empty_plate(self): self.assertEqual(self.parse('77,0,0,0,0,0\n')[0]['all_processing_source_rows'], 0)
    def test_empty_plate_old_regression(self):
        with self.assertRaises(ValueError): self.parse('77,0,0,0,1,1\n')
    def test_truncated_quote(self):
        with self.assertRaises(ValueError): self.parse('77,1,1,1,1,"1')
    def test_quoted_newline(self):
        with self.assertRaises(ValueError): self.parse('77,10,1,1,10,"1\n0"\n')
    def test_missing_cell(self):
        with self.assertRaises(ValueError): self.parse('77,1,1,1,1\n')
    def test_extra_cell(self):
        with self.assertRaises(ValueError): self.parse('77,1,1,1,1,1,1\n')
    def test_duplicate_plate(self):
        with self.assertRaises(ValueError): self.parse('77,1,1,1,1,1\n77,1,1,1,1,1\n')
    def test_wrong_schema(self):
        with self.assertRaises(ValueError): runner.parse_csv_bytes(b'source_id,ra_icrs\n1,2\n',runner.Q2_FIELDS,FAMILY)
    def test_impossible_positive_counts(self):
        with self.assertRaises(ValueError): self.parse('77,1,99,88,77,66\n')
    def test_projection_counts(self):
        with self.assertRaises(ValueError): self.parse('77,10,1,1,5,4\n')
    def test_real_null_processing_tuple(self): self.parse('77,1,0,0,1,1\n')
    def test_nonempty_requires_composites(self):
        with self.assertRaises(ValueError): self.parse('77,1,0,0,0,0\n')
    def test_negative_counts(self):
        with self.assertRaises(ValueError): self.parse('77,-1,0,0,0,0\n')
    def test_large_exact_integer(self): self.assertEqual(runner.parse_int('9007199254740993'),9007199254740993)
    def test_float_not_integer(self):
        with self.assertRaises(ValueError): runner.parse_int('1.0')
    def test_values_reject_float(self):
        with self.assertRaises(SystemExit): runner.materialize('VALUES X','X',[(77.0,)])
    def test_cross_totals(self):
        with self.assertRaises(ValueError): runner.validate_cross_totals([{'plate_id':77,'source_rows':2}],self.parse('77,1,1,1,1,1\n'))
    def test_cross_totals_sums_selected_solutions(self):
        with self.assertRaises(ValueError): runner.validate_cross_totals([{'plate_id':77,'source_rows':1}]*2,self.parse('77,1,1,1,1,1\n'))
    def test_q1_partition_mismatch(self):
        row = {f:'0' for f in runner.Q1_FIELDS}
        row.update(key_id='1',plate_id='77',scan_id='88',process_id='99',solution_num='1',source_rows='1')
        with self.assertRaises(ValueError): runner.validate_q1([row],{1:(77,88,99,1)})
    def test_q0_bindings_and_failures(self):
        row = dict(zip(runner.Q0_FIELDS,map(str,[1,101,77,88,77,88,99,1,1001,1])))
        self.assertEqual(runner.validate_q0([row],{1:(101,77,88)})[0]['process_id'],99)
        for field,value in [('returned_scan_id','89'),('returned_plate_id','78'),('process_id',''),('solution_row_found','0')]:
            with self.subTest(field=field),self.assertRaises(ValueError): runner.validate_q0([{**row,field:value}],{1:(101,77,88)})
        with self.assertRaises(ValueError): runner.validate_q0([row,row],{1:(101,77,88)})
    def test_q0_science_collision(self):
        a = dict(zip(runner.Q0_FIELDS,map(str,[1,101,77,88,77,88,99,1,1001,1])))
        b = {**a,'key_id':'2','solution_id':'102'}
        with self.assertRaises(ValueError): runner.validate_q0([a,b],{1:(101,77,88),2:(102,77,88)})


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='v095a_test_')
        self.project = Path(self.temp.name)
        self.work = self.project/'work/v095a_stageA_aggregate_inventory_rc9'
        self.clock = Clock(); self.client = Client(self.clock)
        self.context = {'contract':runner.CONTRACT_SHA,'sql':runner.SQL_SHA,'freeze':'synthetic'}
        self.directory = self.work/'jobs'/FAMILY/'batch_0001'
    def tearDown(self): self.temp.cleanup()
    def run_batch(self, client=None, context=None):
        with ProjectLock(self.project) as owner:
            return jobs.run_batch(client or self.client,FAMILY,1,QUERY,runner.Q2_FIELDS,
                                  runner.parse_csv_bytes,runner.validate_q2,[77],self.work,Counter(),
                                  owner=owner,context=context or self.context,clock=self.clock)
    def meta(self): return json.loads((self.directory/'meta.json').read_text())
    def publication_specs(self):
        return {(FAMILY,1): {'query':QUERY,'fields':runner.Q2_FIELDS,
                            'validator':runner.validate_q2,'expected':[77]}}
    def copy_for_publication(self, staging):
        return runner.copy_validated_jobs(self.work, staging, {FAMILY:1},
                                          self.publication_specs(), self.context)
    def test_success_and_resume_without_requests(self):
        self.run_batch(); n=len(self.client.requests)
        self.run_batch(); self.assertEqual(len(self.client.requests),n)
    def test_submission_deadline_starts_at_header_receipt_not_body_return(self):
        client=DelayedSubmissionClient(self.clock)
        self.run_batch(client=client)
        a=self.meta()['attempts'][0]
        self.assertEqual(a['submitted_epoch'],1800000000.0)
        self.assertEqual(a['submitted_monotonic'],0.0)
        self.assertEqual(a['deadline_epoch'],1800003900.0)
        self.assertEqual(a['deadline_monotonic'],3900.0)
        self.assertEqual(self.clock.elapsed,120.0)

    def test_completed_receipt_requires_disposition(self):
        self.run_batch();meta=self.meta();a=meta['attempts'][0]
        a.pop('submission_disposition',None)
        (self.directory/'meta.json').write_text(json.dumps(meta,sort_keys=True,indent=2)+'\n')
        before=self.client.submissions
        with self.assertRaises(SystemExit) as caught:self.run_batch()
        self.assertIn('CHECKPOINT_HOLD',str(caught.exception));self.assertEqual(self.client.submissions,before)

    def test_receipt_time_rehash_cannot_extend_job_budget(self):
        self.run_batch();meta=self.meta();a=meta['attempts'][0];path=self.directory/a['header_receipt_file']
        hdr=json.loads(path.read_text());hdr['received_epoch']+=60;hdr['received_monotonic']+=60
        hdr['receipt_sha256']=jobs.header_receipt_hash(hdr)
        path.write_text(json.dumps(hdr,sort_keys=True,separators=(',',':'))+'\n')
        for art in a['artifacts']:
            if art.get('kind')=='submission_headers':
                art['sha256']=jobs.digest(path.read_bytes());art['bytes']=path.stat().st_size
        sr=a['submission_response'];sr['header_receipt_sha256']=hdr['receipt_sha256']
        sr['header_received_epoch']=hdr['received_epoch'];sr['header_received_monotonic']=hdr['received_monotonic']
        sr['receipt_sha256']=jobs.receipt_hash(sr)
        (self.directory/'meta.json').write_text(json.dumps(meta,sort_keys=True,indent=2)+'\n')
        before=self.client.submissions
        with self.assertRaises(SystemExit) as caught:self.run_batch()
        self.assertIn('CHECKPOINT_HOLD',str(caught.exception));self.assertEqual(self.client.submissions,before)

    def test_corrupt_result_hold_no_resubmit(self):
        self.run_batch();(self.directory/'result.csv').write_bytes(b'bad')
        with self.assertRaises(SystemExit): self.run_batch()
        self.assertEqual(self.client.submissions,1)
    def test_context_change_hold(self):
        self.run_batch()
        with self.assertRaises(SystemExit): self.run_batch(context={'freeze':'different'})
        self.assertEqual(self.client.submissions,1)
    def test_corrupt_query_hold(self):
        self.run_batch();(self.directory/'query.sql').write_bytes(b'SELECT 1')
        with self.assertRaises(SystemExit): self.run_batch()
    def test_crash_resume_existing_job(self):
        self.client.crash = SimulatedCrash()
        with self.assertRaises(SimulatedCrash): self.run_batch()
        self.assertIn('job_url',self.meta()['attempts'][0])
        self.run_batch();self.assertEqual(self.client.submissions,1)
    def test_ctrl_c_records_abort_and_keeps_budget(self):
        self.client.crash=KeyboardInterrupt()
        with self.assertRaises(SystemExit): self.run_batch()
        self.assertEqual(self.meta()['attempts'][0]['abort_terminal_phase'],'ABORTED')
        self.run_batch();self.assertEqual(len(self.meta()['attempts']),2)
    def test_retry_limit_survives_resume(self):
        self.client.errors=10
        with self.assertRaises(SystemExit): self.run_batch()
        with self.assertRaises(SystemExit): self.run_batch()
        self.assertEqual(self.client.submissions,3)
        bodies=[d['QUERY'] for method,url,d in self.client.requests if method=='POST' and url==jobs.BASE]
        self.assertEqual(len(set(bodies)),1)
    def test_late_completion_not_accepted(self):
        def late(client):
            client.phase_hook=None;self.clock.sleep(3930)
        self.client.phase_hook=late
        self.run_batch()
        self.assertEqual(self.client.submissions,2)
        self.assertIn('failure',self.meta()['attempts'][0])
    def test_resume_does_not_reset_deadline(self):
        self.client.crash=SimulatedCrash()
        with self.assertRaises(SimulatedCrash): self.run_batch()
        self.clock.sleep(4000)
        self.run_batch();self.assertEqual(self.client.submissions,2)
    def test_failed_validation_retains_bytes_hash_and_sticks(self):
        self.client.body=(HEADER+'77,1,1,1,1,"1').encode()
        with self.assertRaises(SystemExit): self.run_batch()
        meta=self.meta();artifact=next(x for x in meta['attempts'][0]['artifacts'] if x.get('kind')=='result')
        self.assertEqual((self.directory/artifact['file']).read_bytes(),self.client.body)
        self.assertEqual(artifact['sha256'],jobs.digest(self.client.body))
        self.assertEqual(meta['status'],'FAILED_HOLD')
        with self.assertRaises(SystemExit):self.run_batch()
        self.assertEqual(self.client.submissions,1)
    def test_download_retry_reuses_completed_job(self):
        self.client.download_failures=1
        self.run_batch();meta=self.meta()
        self.assertEqual(self.client.submissions,1)
        self.assertEqual(meta['attempts'][0]['fetch_attempts'],2)
        artifact=next(x for x in meta['attempts'][0]['artifacts'] if x.get('kind')=='result')
        self.assertTrue(artifact['partial'])
    def test_download_retry_limit(self):
        self.client.download_failures=10
        with self.assertRaises(SystemExit):self.run_batch()
        with self.assertRaises(SystemExit):self.run_batch()
        self.assertEqual(self.meta()['attempts'][0]['fetch_attempts'],3)
    def test_http_error_result_body_is_retained(self):
        original=self.client.request
        failed=[False]
        body=b'synthetic service error body'
        def error_once(method,url,**kw):
            if url.endswith('/results/csv') and not failed[0]:
                failed[0]=True
                return HTTPResponse(503,{},body)
            return original(method,url,**kw)
        with patch.object(self.client,'request',side_effect=error_once):self.run_batch()
        artifact=next(x for x in self.meta()['attempts'][0]['artifacts'] if x.get('kind')=='result')
        self.assertEqual((self.directory/artifact['file']).read_bytes(),body)
        self.assertEqual(artifact['sha256'],jobs.digest(body))
        self.assertEqual(self.client.submissions,1)
    def test_unknown_submission_no_automatic_retry(self):
        with patch.object(self.client,'request',side_effect=TransportFailure('HTTP_ConnectionError')):
            with self.assertRaises(SystemExit):self.run_batch()
        with self.assertRaises(SystemExit):self.run_batch()
        self.assertEqual(len(self.meta()['attempts']),1)
        self.assertEqual(self.meta()['failure'].split(':')[0],'SUBMISSION_UNCERTAIN_HOLD')

    def test_submission_explicit_rejections_are_preserved_and_sticky(self):
        for status in (400,401,403,404,405,413,415,422,429):
            with self.subTest(status=status):
                # Fresh batch directory for each status.
                if self.directory.exists(): shutil.rmtree(self.directory)
                body=f'synthetic rejection {status}'.encode()
                with patch.object(self.client,'request',return_value=HTTPResponse(status,{'content-type':'text/plain','content-length':str(len(body))},body)):
                    with self.assertRaises(SystemExit) as caught:self.run_batch()
                self.assertIn('TAP_SUBMISSION_REJECTED_HOLD',str(caught.exception))
                meta=self.meta();a=meta['attempts'][0];ev=a['submission_response']
                self.assertEqual(ev['status'],status);self.assertEqual(ev['body_sha256'],jobs.digest(body))
                self.assertEqual((self.directory/ev['artifact']).read_bytes(),body)
                self.assertEqual(a['submission_disposition'],'EXPLICIT_HTTP_REJECTION')
                with self.assertRaises(SystemExit):self.run_batch()
                self.assertEqual(len(meta['attempts']),1)

    def test_submission_ambiguous_http_status_preserved(self):
        for status in (200,202,307,408,500,503):
            with self.subTest(status=status):
                if self.directory.exists(): shutil.rmtree(self.directory)
                body=f'synthetic ambiguous {status}'.encode()
                with patch.object(self.client,'request',return_value=HTTPResponse(status,{'content-type':'text/plain'},body)):
                    with self.assertRaises(SystemExit) as caught:self.run_batch()
                self.assertIn('SUBMISSION_UNCERTAIN_HOLD',str(caught.exception))
                meta=self.meta();a=meta['attempts'][0]
                self.assertEqual(a['submission_response']['status'],status)
                self.assertEqual((self.directory/a['submission_response']['artifact']).read_bytes(),body)
                self.assertEqual(a['submission_disposition'],'AMBIGUOUS_HTTP_RESPONSE')

    def test_submission_valid_303_records_receipt_evidence_before_polling(self):
        self.run_batch();a=self.meta()['attempts'][0]
        self.assertEqual(a['submission_response']['status'],303)
        self.assertEqual(a['submission_response']['headers']['location'],jobs.BASE+'/job1')
        self.assertEqual(a['submission_disposition'],'JOB_RECEIPT_VALIDATED')
        self.assertEqual((self.directory/a['submission_response']['artifact']).read_bytes(),b'')

    def test_submission_accepted_status_bad_location_is_uncertain_and_preserved(self):
        body=b'accepted but bad location'
        with patch.object(self.client,'request',return_value=HTTPResponse(303,{'location':'https://example.com/job'},body)):
            with self.assertRaises(SystemExit) as caught:self.run_batch()
        self.assertIn('SUBMISSION_UNCERTAIN_HOLD',str(caught.exception))
        a=self.meta()['attempts'][0]
        self.assertEqual(a['submission_response']['status'],303)
        self.assertEqual(a['submission_disposition'],'ACCEPTED_STATUS_WITHOUT_VALID_JOB_LOCATION')
        self.assertEqual((self.directory/a['submission_response']['artifact']).read_bytes(),body)

    def test_corrupt_submission_artifact_holds_on_resume(self):
        self.run_batch();meta=self.meta();a=meta['attempts'][0]
        (self.directory/a['submission_response']['artifact']).write_bytes(b'corrupt')
        n=self.client.submissions
        with self.assertRaises(SystemExit) as caught:self.run_batch()
        self.assertIn('CHECKPOINT_HOLD',str(caught.exception))
        self.assertEqual(self.client.submissions,n)

    def test_submission_metadata_mismatch_holds_on_resume(self):
        self.run_batch();meta=self.meta();a=meta['attempts'][0]
        a['submission_response']['body_sha256']='0'*64
        (self.directory/'meta.json').write_text(json.dumps(meta,sort_keys=True,indent=2)+'\n')
        n=self.client.submissions
        with self.assertRaises(SystemExit) as caught:self.run_batch()
        self.assertIn('CHECKPOINT_HOLD',str(caught.exception))
        self.assertEqual(self.client.submissions,n)

    def test_submission_transport_partial_is_preserved(self):
        partial=b'partial submission response'
        with patch.object(self.client,'request',side_effect=TransportFailure('HTTP_ReadTimeout',partial)):
            with self.assertRaises(SystemExit) as caught:self.run_batch()
        self.assertIn('SUBMISSION_UNCERTAIN_HOLD',str(caught.exception))
        a=self.meta()['attempts'][0];ev=a['submission_response']
        self.assertTrue(ev['partial']);self.assertEqual(ev['transport_failure'],'HTTP_ReadTimeout')
        self.assertEqual((self.directory/ev['artifact']).read_bytes(),partial)
        self.assertEqual(a['submission_disposition'],'TRANSPORT_ACCEPTANCE_UNKNOWN')

    def test_transport_counter_includes_failure(self):
        self.client.download_failures=1;self.run_batch()
        self.assertEqual(self.meta()['transport_request_attempts'],len(self.client.requests))
    def test_second_owner_refused_before_batch_changes(self):
        with ProjectLock(self.project):
            with self.assertRaises(SystemExit): self.run_batch()
        self.assertEqual(self.client.requests,[])
    def test_foreign_job_location_refused(self):
        with patch.object(self.client,'request',return_value=HTTPResponse(303,{'location':'https://example.com/job'},b'')):
            with self.assertRaises(SystemExit):self.run_batch()
        self.assertEqual(self.meta()['status'],'FAILED_HOLD')
    def test_unknown_phase_is_sticky_hold(self):
        original=self.client.request
        def invalid(method,url,**kw):
            if url.endswith('/phase'):return HTTPResponse(200,{},b'<html>login</html>')
            return original(method,url,**kw)
        with patch.object(self.client,'request',side_effect=invalid):
            with self.assertRaises(SystemExit):self.run_batch()
        self.assertEqual(self.meta()['status'],'FAILED_HOLD')
    def test_abort_unconfirmed_never_resubmits(self):
        self.client.crash=SimulatedCrash()
        with self.assertRaises(SimulatedCrash):self.run_batch()
        self.clock.sleep(4000)
        original=self.client.request
        def executing(method,url,**kw):
            if url.endswith('/phase') and method=='GET':return HTTPResponse(200,{},b'EXECUTING')
            return original(method,url,**kw)
        with patch.object(self.client,'request',side_effect=executing):
            with self.assertRaises(SystemExit):self.run_batch()
        self.assertEqual(self.meta()['attempts'][0]['state'],'ABORT_PENDING')
        self.assertEqual(self.client.submissions,1)
    def test_publication_excludes_unselected_directories(self):
        self.run_batch()
        extra=self.work/'jobs'/FAMILY/'batch_0001.invalid_old'
        extra.mkdir();(extra/'unvalidated.txt').write_text('synthetic extra')
        staging=self.project/'staging';staging.mkdir()
        counts=self.copy_for_publication(staging)
        self.assertFalse((staging/'jobs'/FAMILY/extra.name).exists())
        self.assertEqual(counts['tap_job_submission_attempts'],1)
        self.assertEqual((staging/'jobs'/FAMILY/'batch_0001'/'result.csv').read_bytes(),GOOD)

    def test_controller_crash_after_durable_headers_never_resubmits(self):
        original=self.client.request
        crashed=[False]
        def crash_after_headers(method,url,**kw):
            if method=='POST' and url==jobs.BASE and not crashed[0]:
                crashed[0]=True
                self.client.submissions += 1
                path=Path(kw['durable_receipt_path'])
                jobs.atomic_json(path,jobs.make_header_receipt(303,{'location':jobs.BASE+'/orphan_job'}))
                raise SimulatedCrash()
            return original(method,url,**kw)
        with patch.object(self.client,'request',side_effect=crash_after_headers):
            with self.assertRaises(SimulatedCrash): self.run_batch()
        meta=self.meta();a=meta['attempts'][0]
        sidecar=self.directory/a['header_receipt_file']
        self.assertTrue(sidecar.is_file())
        self.assertEqual(json.loads(sidecar.read_text())['headers']['location'],jobs.BASE+'/orphan_job')
        with self.assertRaises(SystemExit) as caught:self.run_batch()
        self.assertIn('SUBMISSION_UNCERTAIN_HOLD',str(caught.exception))
        self.assertEqual(self.client.submissions,1)
        self.assertEqual(len(self.meta()['attempts']),1)
        self.assertTrue(self.meta()['attempts'][0].get('interrupted_header_receipt_sha256'))

    def test_completed_receipt_status_mutation_rehashed_still_holds(self):
        self.run_batch();meta=self.meta();a=meta['attempts'][0]
        a['submission_response']['status']=401
        a['submission_response']['receipt_sha256']=jobs.receipt_hash(a['submission_response'])
        (self.directory/'meta.json').write_text(json.dumps(meta,sort_keys=True,indent=2)+'\n')
        with self.assertRaises(SystemExit) as caught:self.run_batch()
        self.assertIn('CHECKPOINT_HOLD',str(caught.exception));self.assertEqual(self.client.submissions,1)

    def test_completed_receipt_location_mutation_rehashed_still_holds(self):
        self.run_batch();meta=self.meta();a=meta['attempts'][0]
        a['submission_response']['headers']['location']='https://example.invalid/other_job'
        a['submission_response']['receipt_sha256']=jobs.receipt_hash(a['submission_response'])
        (self.directory/'meta.json').write_text(json.dumps(meta,sort_keys=True,indent=2)+'\n')
        with self.assertRaises(SystemExit) as caught:self.run_batch()
        self.assertIn('CHECKPOINT_HOLD',str(caught.exception));self.assertEqual(self.client.submissions,1)

    def test_completed_header_sidecar_removal_holds(self):
        self.run_batch();meta=self.meta();a=meta['attempts'][0]
        (self.directory/a['header_receipt_file']).unlink()
        with self.assertRaises(SystemExit) as caught:self.run_batch()
        self.assertIn('CHECKPOINT_HOLD',str(caught.exception));self.assertEqual(self.client.submissions,1)

    def test_completed_header_sidecar_semantic_mutation_holds_even_rehashed(self):
        self.run_batch();meta=self.meta();a=meta['attempts'][0];path=self.directory/a['header_receipt_file']
        hdr=json.loads(path.read_text());hdr['status']=401;hdr['receipt_sha256']=jobs.header_receipt_hash(hdr)
        path.write_text(json.dumps(hdr,sort_keys=True,separators=(',',':'))+'\n')
        # Update artifact file hash too: semantic relationship must still reject it.
        for art in a['artifacts']:
            if art.get('kind')=='submission_headers': art['sha256']=jobs.digest(path.read_bytes());art['bytes']=path.stat().st_size
        (self.directory/'meta.json').write_text(json.dumps(meta,sort_keys=True,indent=2)+'\n')
        with self.assertRaises(SystemExit) as caught:self.run_batch()
        self.assertIn('CHECKPOINT_HOLD',str(caught.exception));self.assertEqual(self.client.submissions,1)

    def test_publication_revalidates_receipt_semantics(self):
        self.run_batch();meta=self.meta();a=meta['attempts'][0]
        a['submission_response']['status']=401
        a['submission_response']['receipt_sha256']=jobs.receipt_hash(a['submission_response'])
        (self.directory/'meta.json').write_text(json.dumps(meta,sort_keys=True,indent=2)+'\n')
        staging=self.project/'staging_receipt';staging.mkdir()
        with self.assertRaises(SystemExit) as caught:self.copy_for_publication(staging)
        self.assertIn('PUBLICATION_HOLD',str(caught.exception))

    def test_publication_rejects_missing_receipt_disposition(self):
        self.run_batch();meta=self.meta();a=meta['attempts'][0]
        a.pop('submission_disposition',None)
        (self.directory/'meta.json').write_text(json.dumps(meta,sort_keys=True,indent=2)+'\n')
        staging=self.project/'staging_missing_disposition';staging.mkdir()
        with self.assertRaises(SystemExit) as caught:self.copy_for_publication(staging)
        self.assertIn('PUBLICATION_HOLD',str(caught.exception))


    def test_publication_rejects_deleted_attempt_history(self):
        self.run_batch();meta=self.meta();meta['attempts']=[]
        (self.directory/'meta.json').write_text(json.dumps(meta,sort_keys=True,indent=2)+'\n')
        staging=self.project/'staging_no_attempts';staging.mkdir()
        with self.assertRaises(SystemExit) as caught:self.copy_for_publication(staging)
        self.assertIn('PUBLICATION_HOLD',str(caught.exception))

    def test_publication_rejects_nonvalidated_final_attempt(self):
        self.run_batch();meta=self.meta();meta['attempts'][-1]['state']='WAITING'
        (self.directory/'meta.json').write_text(json.dumps(meta,sort_keys=True,indent=2)+'\n')
        staging=self.project/'staging_waiting_final';staging.mkdir()
        with self.assertRaises(SystemExit) as caught:self.copy_for_publication(staging)
        self.assertIn('PUBLICATION_HOLD',str(caught.exception))

    def test_publication_rejects_context_mismatch(self):
        self.run_batch();meta=self.meta();meta['context_sha256']=jobs.canonical({'different':'context'})
        (self.directory/'meta.json').write_text(json.dumps(meta,sort_keys=True,indent=2)+'\n')
        staging=self.project/'staging_context';staging.mkdir()
        with self.assertRaises(SystemExit) as caught:self.copy_for_publication(staging)
        self.assertIn('PUBLICATION_HOLD',str(caught.exception))

    def test_ctrl_c_submission_retains_buffered_body_and_never_resubmits(self):
        partial=b'bounded-partial-body'
        original=self.client.request
        fired=[False]
        def interrupt(method,url,**kw):
            if method=='POST' and url==jobs.BASE and not fired[0]:
                fired[0]=True;self.client.submissions+=1
                receipt=jobs.make_header_receipt(303,{'location':jobs.BASE+'/interrupt_job'},
                                                 self.clock.time(),self.clock.monotonic())
                jobs.atomic_json(Path(kw['durable_receipt_path']),receipt)
                jobs.atomic_bytes(Path(kw['durable_partial_body_path']),partial)
                raise KeyboardInterrupt()
            return original(method,url,**kw)
        with patch.object(self.client,'request',side_effect=interrupt):
            with self.assertRaises(SystemExit):self.run_batch()
        meta=self.meta();a=meta['attempts'][0];sr=a['submission_response']
        self.assertEqual(a['state'],'SUBMITTING')
        self.assertEqual(a['submission_disposition'],'TRANSPORT_RESPONSE_INCOMPLETE')
        self.assertEqual((self.directory/sr['artifact']).read_bytes(),partial)
        self.assertEqual(sr['body_sha256'],jobs.digest(partial));self.assertTrue(sr['partial'])
        before=self.client.submissions
        with self.assertRaises(SystemExit):self.run_batch()
        self.assertEqual(self.client.submissions,before);self.assertEqual(len(self.meta()['attempts']),1)



class IncidentGateTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='v095a_incident_');self.project=Path(self.temp.name)
        self.source=self.project/runner.RC4_INCIDENT_REL;self.source.parent.mkdir(parents=True)
        self.meta={'family':'Q0_SELECTED_SOLUTION_BINDING','batch':1,'status':'FAILED_HOLD',
                   'failure':'SUBMISSION_UNCERTAIN_HOLD: job receipt unavailable; do not resubmit',
                   'transport_request_attempts':1,'created_utc':'2026-09-10T21:39:41.940997+00:00',
                   'updated_utc':'2026-09-10T21:39:42.901565+00:00',
                   'attempts':[{'attempt':1,'state':'SUBMITTING'}]}
        runner.atomic_json(self.source,self.meta)
        self.evidence=self.project/'work/prior.json'
        self.write_evidence(True)
    def tearDown(self):self.temp.cleanup()
    def write_evidence(self,ack):
        runner.atomic_json(self.evidence,{
            'schema_version':1,'incident_id':'v095a-rc4-first-live-q0-submission',
            'status':'UNRESOLVED_UNKNOWN_SUBMISSION_ACKNOWLEDGED_FOR_SUPERSEDING_READ_ONLY_RETRY',
            'acknowledged_superseding_read_only_retry':ack,
            'source_checkpoint_relative':runner.RC4_INCIDENT_REL.as_posix(),
            'source_checkpoint_sha256':runner.sha(self.source),
            'recorded_created_utc':self.meta['created_utc'],'recorded_updated_utc':self.meta['updated_utc']})
    def test_prior_incident_acknowledgement_passes_without_network(self):
        self.assertEqual(runner.verify_prior_rc4_incident(self.project,self.evidence),runner.sha(self.evidence))
    def test_prior_incident_requires_explicit_acknowledgement(self):
        self.write_evidence(False)
        with self.assertRaises(SystemExit) as caught:runner.verify_prior_rc4_incident(self.project,self.evidence)
        self.assertIn('PRIOR_INCIDENT_HOLD',str(caught.exception))
    def test_prior_incident_detects_checkpoint_mutation(self):
        self.meta['updated_utc']='changed';runner.atomic_json(self.source,self.meta)
        with self.assertRaises(SystemExit) as caught:runner.verify_prior_rc4_incident(self.project,self.evidence)
        self.assertIn('PRIOR_INCIDENT_HOLD',str(caught.exception))



class RuntimeTests(unittest.TestCase):
    def test_frozen_parent_archive_path_is_rc4_name(self):
        self.assertEqual(runner.V094Y_PROOF_REL.as_posix(),
                         'research/proof_archives/v094y_rc4_proof_archive.zip')

    @unittest.skipIf(os.name == 'nt', 'POSIX SIGINT transport-boundary probe')
    def test_sigint_after_headers_and_body_chunk_preserves_bounded_body(self):
        with tempfile.TemporaryDirectory() as durable_dir:
            base=Path(durable_dir);receipt=base/'receipt.json';body=base/'partial.bin';ready=base/'ready'
            payload={'durable_receipt_path':str(receipt),'durable_partial_body_path':str(body),
                     'ready_path':str(ready),'max_bytes':1024}
            stop=threading.Event()
            def interrupt():
                end=time.monotonic()+5
                while not stop.is_set() and time.monotonic()<end:
                    if ready.is_file():
                        os.kill(os.getpid(),signal.SIGINT);return
                    time.sleep(0.005)
            watcher=threading.Thread(target=interrupt,daemon=True);watcher.start()
            try:
                with self.assertRaises(KeyboardInterrupt):
                    isolated_request(payload,time.monotonic()+5,worker=durable_receipt_body_sleep_worker)
            finally:
                stop.set();watcher.join(1)
            self.assertTrue(receipt.is_file());self.assertTrue(body.is_file())
            self.assertEqual(body.read_bytes(),b'bounded-partial-body')
            self.assertLessEqual(len(body.read_bytes()),payload['max_bytes'])

    def test_token_not_echoed(self):
        with self.assertRaises(SystemExit) as caught:BoundedHTTP('secret\ntoken')
        self.assertNotIn('secret',str(caught.exception))
    def test_http_drip_has_enforced_wall_deadline(self):
        start=time.monotonic()
        with self.assertRaises(RequestDeadline):isolated_request({},start+1.25,worker=drip_worker)
        self.assertLess(time.monotonic()-start,6)
    def test_worker_persists_durable_headers_before_stream_failure(self):
        class FakeResponse:
            status_code=303
            headers={'Location':jobs.BASE+'/stream_job','Content-Type':'text/plain'}
            def __enter__(self): return self
            def __exit__(self,*args): return False
            def iter_content(self,chunk_size=8192):
                yield b'abc'
                raise ConnectionError('synthetic')
        class FakeSession:
            def __init__(self): self.headers={};self.cookies=[]
            def __enter__(self): return self
            def __exit__(self,*args): return False
            def request(self,*args,**kwargs): return FakeResponse()
        fake=types.SimpleNamespace(Session=FakeSession)
        with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as durable_dir:
            receipt=Path(durable_dir)/'receipt.json'
            payload={'method':'POST','url':jobs.BASE,'data':{},'headers':{},'cookies':[],
                     'timeout':(1,1),'read_body':True,'max_bytes':1024,
                     'durable_receipt_path':str(receipt)}
            with patch.dict(sys.modules,{'requests':fake}): runtime._http_worker(payload,d)
            value=json.loads(receipt.read_text())
            self.assertEqual(value['status'],303);self.assertEqual(value['headers']['location'],jobs.BASE+'/stream_job')
            self.assertEqual(value['schema_version'],2);self.assertIsInstance(value['received_epoch'],float)
            self.assertIsInstance(value['received_monotonic'],float)
            self.assertEqual(value['receipt_sha256'],jobs.header_receipt_hash(value))
            transport=json.loads((Path(d)/'transport.json').read_text())
            self.assertEqual(transport['error'],'HTTP_ConnectionError')

    def test_worker_receipt_time_precedes_body_completion(self):
        class FakeResponse:
            status_code=303
            headers={'Location':jobs.BASE+'/timed_job','Content-Type':'text/plain'}
            def __enter__(self): return self
            def __exit__(self,*args): return False
            def iter_content(self,chunk_size=8192):
                time.sleep(0.15)
                yield b'ok'
        class FakeSession:
            def __init__(self): self.headers={};self.cookies=[]
            def __enter__(self): return self
            def __exit__(self,*args): return False
            def request(self,*args,**kwargs): return FakeResponse()
        fake=types.SimpleNamespace(Session=FakeSession)
        with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as durable_dir:
            receipt=Path(durable_dir)/'receipt.json'
            payload={'method':'POST','url':jobs.BASE,'data':{},'headers':{},'cookies':[],
                     'timeout':(1,1),'read_body':True,'max_bytes':1024,
                     'durable_receipt_path':str(receipt)}
            with patch.dict(sys.modules,{'requests':fake}): runtime._http_worker(payload,d)
            finished=time.time();value=json.loads(receipt.read_text())
            self.assertLess(value['received_epoch'],finished-0.10)
            self.assertEqual(value['receipt_sha256'],jobs.header_receipt_hash(value))

    def test_worker_persists_durable_headers_before_size_hold(self):
        class FakeResponse:
            status_code=401
            headers={'Location':jobs.BASE+'/oversize_job','Content-Type':'text/plain'}
            def __enter__(self): return self
            def __exit__(self,*args): return False
            def iter_content(self,chunk_size=8192): yield b'x'*64
        class FakeSession:
            def __init__(self): self.headers={};self.cookies=[]
            def __enter__(self): return self
            def __exit__(self,*args): return False
            def request(self,*args,**kwargs): return FakeResponse()
        fake=types.SimpleNamespace(Session=FakeSession)
        with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as durable_dir:
            receipt=Path(durable_dir)/'receipt.json'
            payload={'method':'POST','url':jobs.BASE,'data':{},'headers':{},'cookies':[],
                     'timeout':(1,1),'read_body':True,'max_bytes':8,
                     'durable_receipt_path':str(receipt)}
            with patch.dict(sys.modules,{'requests':fake}): runtime._http_worker(payload,d)
            value=json.loads(receipt.read_text());self.assertEqual(value['status'],401)
            transport=json.loads((Path(d)/'transport.json').read_text())
            self.assertEqual(transport['error'],'RESPONSE_SIZE_HOLD')

    def test_parent_deadline_kill_leaves_durable_receipt_outside_ipc(self):
        with tempfile.TemporaryDirectory() as durable_dir:
            receipt=Path(durable_dir)/'receipt.json'
            payload={'durable_receipt_path':str(receipt)}
            start=time.monotonic()
            with self.assertRaises(RequestDeadline):isolated_request(payload,start+2.5,worker=durable_receipt_sleep_worker)
            self.assertTrue(receipt.is_file())
            value=json.loads(receipt.read_text())
            self.assertEqual(value['status'],303);self.assertEqual(value['headers']['location'],jobs.BASE+'/deadline_job')
    def test_cross_process_lock(self):
        with tempfile.TemporaryDirectory(prefix='v095a_lock_') as directory:
            output=Path(directory)/'child.txt'
            with ProjectLock(directory):
                p=multiprocessing.get_context('spawn').Process(target=lock_child,args=(directory,str(output)))
                p.start();p.join(10)
                self.assertFalse(p.is_alive());self.assertEqual(p.exitcode,0)
                self.assertEqual(output.read_text(),'blocked')
            with ProjectLock(directory): pass


if __name__=='__main__':unittest.main(verbosity=2)
