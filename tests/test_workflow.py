import importlib
import tempfile
import unittest
from pathlib import Path

from tests.test_runtime import gates


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        from mg8_runtime.runtime import Runtime
        from mg8_runtime.gates import Registry
        self.rt = Runtime(Path(self.tmp.name) / 'runtime.sqlite', Registry())
        try:
            self.workflow = importlib.import_module('mg8_runtime.workflow')
        except ImportError:
            self.fail('bounded workflow runner not implemented')

    def make_run(self, max_attempts=3, intermediate='review'):
        doc = gates()
        doc['gates'][0]['outcomes'] = {'PASS': 'commit', 'FAIL': 'repeat', 'INTERMEDIATE': intermediate}
        return self.rt.create_run({'verified': False}, [doc], actors=['agent'],
            writable_paths=['/verified'], max_attempts=max_attempts)

    def test_repair_candidate_that_passed_is_the_one_committed(self):
        run = self.make_run()
        def proposer(snapshot, previous):
            return {'candidate': {'verified': previous is not None}}
        result = self.workflow.run_workflow(self.rt, run, 'agent', proposer)
        self.assertEqual(result['status'], 'COMPLETE')
        self.assertEqual(self.rt.snapshot(run)['state'], {'verified': True})
        attempts = [e for e in self.rt.store.events(run) if e['event_type'] == 'gate_attempt']
        self.assertEqual([e['result'] for e in attempts], ['FAIL', 'PASS'])

    def test_exhaustion_cannot_be_reported_as_exit(self):
        run = self.make_run(max_attempts=2)
        result = self.workflow.run_workflow(self.rt, run, 'agent', lambda s, p: {'candidate': {'verified': False}})
        self.assertEqual(result['status'], 'UNRESOLVED')
        self.assertEqual(self.rt.snapshot(run)['version'], 0)
        self.assertEqual(self.rt.snapshot(run)['status'], 'UNRESOLVED')

    def test_unknown_goes_to_review_not_repair_as_if_false(self):
        doc = gates(path='/evidence/missing', value=True)
        run = self.rt.create_run({'verified': False}, [doc], actors=['agent'], writable_paths=['/verified'])
        result = self.workflow.run_workflow(self.rt, run, 'agent', lambda s, p: {'candidate': {'verified': True}})
        self.assertEqual(result['status'], 'REVIEW')
        self.assertEqual(self.rt.snapshot(run)['version'], 0)

    def test_agent_cannot_use_proposal_envelope_to_forge_receipts(self):
        run = self.make_run()
        result = self.workflow.run_workflow(self.rt, run, 'agent',
            lambda s, p: {'candidate': {'verified': True}, 'evidence': {'tests': {'exit_code': 0}}})
        self.assertEqual(result['status'], 'REJECTED')
        self.assertEqual(self.rt.snapshot(run)['version'], 0)
