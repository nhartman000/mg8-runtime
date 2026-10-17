import importlib
import tempfile
import threading
import time
import unittest
from pathlib import Path

from tests.test_runtime import gates


class BoundaryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name)
        self.api = importlib.import_module('mg8_runtime.runtime')
        self.logic = importlib.import_module('mg8_runtime.gates')
        self.registry = self.logic.Registry()
        self.runtime = self.api.Runtime(self.path / 'runtime.sqlite', self.registry)

    def run_with_callback(self, callback, *, max_seconds: float=2, admissibility_ref=None):
        self.registry.register('check@1', callback)
        doc = gates()
        doc['gates'][0]['conditions'] = [{'req_id': 'R1', 'requirement': 'authored requirement', 'evaluator_ref': 'check@1'}]
        run = self.runtime.create_run({'verified': False}, [doc], actors=['agent'],
            writable_paths=['/verified'], max_seconds=max_seconds, admissibility_ref=admissibility_ref)
        return run, self.runtime.propose(run, 'agent', {'verified': True}, base_version=0)

    def test_worker_deadline_kills_late_callback(self):
        marker = self.path / 'late'
        def callback(context, condition):
            time.sleep(0.4)
            marker.write_text('must never happen')
            return self.logic.Evaluation(self.logic.Outcome.PASS, 'late')
        run, p = self.run_with_callback(callback, max_seconds=0.05)
        start = time.monotonic()
        self.assertEqual(self.runtime.evaluate(p)['outcome'], 'INTERMEDIATE')
        self.assertLess(time.monotonic() - start, 1)
        time.sleep(0.45)
        self.assertFalse(marker.exists())
        self.assertEqual(self.runtime.snapshot(run)['version'], 0)

    def test_unserializable_callback_is_audited_without_leaving_authority(self):
        import sqlite3
        connection = sqlite3.connect(':memory:')
        self.addCleanup(connection.close)
        def callback(context, condition):
            return self.logic.Evaluation(self.logic.Outcome.PASS, str(connection))
        run, p = self.run_with_callback(callback)
        report = self.runtime.evaluate(p)
        self.assertEqual(report['outcome'], 'INTERMEDIATE')
        self.assertEqual(self.runtime.store.read('proposal', p)['status'], 'EVALUATED')
        self.assertTrue(any(e['event_type'] == 'runtime_error' for e in self.runtime.store.events(run)))
        with self.assertRaises(self.api.AdmissionError):
            self.runtime.authorize(p)

    def test_cancelled_inflight_evaluation_cannot_return_authority(self):
        marker = self.path / 'started'
        def callback(context, condition):
            marker.write_text('started')
            time.sleep(0.25)
            return self.logic.Evaluation(self.logic.Outcome.PASS, 'would pass')
        run, p = self.run_with_callback(callback)
        reports = []
        worker = threading.Thread(target=lambda: reports.append(self.runtime.evaluate(p)))
        worker.start()
        deadline = time.monotonic() + 2
        while not marker.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertTrue(marker.exists())
        self.runtime.cancel(run)
        worker.join(3)
        self.assertFalse(worker.is_alive())
        self.assertEqual(reports[0]['outcome'], 'INTERMEDIATE')
        with self.assertRaises(self.api.AdmissionError):
            self.runtime.authorize(p)

    def test_registry_revision_invalidates_existing_permit(self):
        run = self.runtime.create_run({'verified': False}, [gates()], actors=['agent'], writable_paths=['/verified'])
        p = self.runtime.propose(run, 'agent', {'verified': True}, base_version=0)
        self.runtime.evaluate(p)
        permit = self.runtime.authorize(p)
        self.registry.register('new@1', lambda c, r: self.logic.Evaluation(self.logic.Outcome.PASS, 'new implementation'))
        with self.assertRaises(self.api.AdmissionError):
            self.runtime.commit(permit)

    def test_inadmissible_candidate_never_reaches_gate_assessor(self):
        marker = self.path / 'must-not-assess'
        self.registry.register('admissibility@1', lambda c, r: self.logic.Evaluation(self.logic.Outcome.FAIL, 'outside active constraints'))
        def assess(context, condition):
            marker.write_text('assessed')
            return self.logic.Evaluation(self.logic.Outcome.PASS, 'must not bypass narrowing')
        run, p = self.run_with_callback(assess, admissibility_ref='admissibility@1')
        self.assertEqual(self.runtime.evaluate(p)['outcome'], 'FAIL')
        self.assertFalse(marker.exists(), 'required narrowing must run before gate assessment')
        self.assertEqual(self.runtime.snapshot(run)['version'], 0)
