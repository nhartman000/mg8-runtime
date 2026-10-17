import importlib
import tempfile
import unittest
from pathlib import Path

from tests.test_runtime import gates


class EffectTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        try:
            self.api = importlib.import_module('mg8_runtime.runtime')
            registry = importlib.import_module('mg8_runtime.gates').Registry()
        except ImportError:
            self.fail('effect authorization is not implemented')
        self.runtime = self.api.Runtime(Path(self.tmp.name) / 'runtime.sqlite', registry)
        self.marker = Path(self.tmp.name) / 'effect.txt'

    def setup_operation(self, adapter):
        self.runtime.register_operation('fixture.write@1', adapter)
        run = self.runtime.create_run({'verified': False},
            [gates(path='/evidence/operation/status', value='SUCCEEDED')],
            actors=['agent'], writable_paths=['/verified'],
            allowed_operations=['fixture.write@1'], effect_gate_documents=[gates()])
        proposal = self.runtime.propose(run, 'agent', {'verified': True}, base_version=0,
            operation={'name': 'fixture.write@1', 'arguments': {'value': 'observed effect'}})
        return run, proposal

    def test_pre_effect_permission_is_not_postcondition_evidence(self):
        def adapter(args, operation_id):
            self.marker.write_text(args['value'])
            return {'operation_id': operation_id, 'written': True}
        run, proposal = self.setup_operation(adapter)
        self.assertEqual(self.runtime.evaluate(proposal)['outcome'], 'INTERMEDIATE')
        self.assertFalse(self.marker.exists())
        self.assertEqual(self.runtime.evaluate(proposal, phase='effect')['outcome'], 'PASS')
        permit = self.runtime.authorize(proposal, purpose='effect')
        operation = self.runtime.dispatch(permit)
        self.assertEqual(operation['status'], 'SUCCEEDED')
        self.assertEqual(self.marker.read_text(), 'observed effect')
        self.assertEqual(self.runtime.snapshot(run)['version'], 0)
        with self.assertRaises(self.api.AdmissionError):
            self.runtime.dispatch(permit)
        self.assertEqual(self.runtime.evaluate(proposal)['outcome'], 'PASS')
        self.runtime.commit(self.runtime.authorize(proposal))
        self.assertEqual(self.runtime.snapshot(run)['version'], 1)

    def test_timeout_is_ambiguous_and_not_retried(self):
        import time
        def adapter(args, operation_id):
            self.marker.write_text('effect happened before timeout')
            time.sleep(2)
        run, proposal = self.setup_operation(adapter)
        self.runtime.evaluate(proposal, phase='effect')
        permit = self.runtime.authorize(proposal, purpose='effect')
        operation = self.runtime.dispatch(permit, timeout=0.4)
        self.assertEqual(operation['status'], 'UNKNOWN')
        self.assertTrue(self.marker.exists())
        with self.assertRaises(self.api.AdmissionError):
            self.runtime.dispatch(permit)
        self.assertEqual(self.runtime.evaluate(proposal)['outcome'], 'FAIL')
        self.assertEqual(self.runtime.snapshot(run)['version'], 0)
        self.runtime.reconcile_operation(operation['id'], status='SUCCEEDED',
            result={'verified': True}, reason='host independently inspected fixture artifact')
        self.runtime.evaluate(proposal)
        self.runtime.commit(self.runtime.authorize(proposal))

    def test_adapter_failure_records_possible_partial_effect(self):
        def adapter(args, operation_id):
            self.marker.write_text('partial')
            raise RuntimeError('remote connection interrupted')
        run, proposal = self.setup_operation(adapter)
        self.runtime.evaluate(proposal, phase='effect')
        operation = self.runtime.dispatch(self.runtime.authorize(proposal, purpose='effect'))
        self.assertEqual(operation['status'], 'UNKNOWN')
        self.assertTrue(self.marker.exists())
        with self.assertRaises(self.api.AdmissionError):
            self.runtime.authorize(proposal)
        self.assertEqual(self.runtime.snapshot(run)['version'], 0)
