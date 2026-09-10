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
import unittest

import run_v095a_stageA_inventory_rc5 as runner
import v095a_jobs_rc5 as jobs
from v095a_runtime_rc5 import (ProjectLock, HTTPResponse, TransportFailure,
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


def lock_child(project, output):
    try:
        with ProjectLock(project): Path(output).write_text('acquired')
    except SystemExit: Path(output).write_text('blocked')


def drip_worker(payload, directory):
    # Sends bytes frequently forever: an inactivity timeout would not end this.
    with (Path(directory)/'body').open('wb') as stream:
        while True:
            stream.write(b'x'); stream.flush(); time.sleep(0.025)


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
        self.work = self.project/'work/v095a_stageA_aggregate_inventory_rc5'
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
    def test_success_and_resume_without_requests(self):
        self.run_batch(); n=len(self.client.requests)
        self.run_batch(); self.assertEqual(len(self.client.requests),n)
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
        counts=runner.copy_validated_jobs(self.work,staging,{FAMILY:1})
        self.assertFalse((staging/'jobs'/FAMILY/extra.name).exists())
        self.assertEqual(counts['tap_job_submission_attempts'],1)
        self.assertEqual((staging/'jobs'/FAMILY/'batch_0001'/'result.csv').read_bytes(),GOOD)


class RuntimeTests(unittest.TestCase):
    def test_token_not_echoed(self):
        with self.assertRaises(SystemExit) as caught:BoundedHTTP('secret\ntoken')
        self.assertNotIn('secret',str(caught.exception))
    def test_http_drip_has_enforced_wall_deadline(self):
        start=time.monotonic()
        with self.assertRaises(RequestDeadline):isolated_request({},start+1.25,worker=drip_worker)
        self.assertLess(time.monotonic()-start,6)
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
