import tempfile
import threading
import time
import unittest
from pathlib import Path

from mg8_runtime.gates import Evaluation, GateSet, Outcome, Registry
from mg8_runtime.runtime import AdmissionError, Runtime
from tests.test_runtime import gates


_GLOBAL_CONFIG = {'allowed': True}


class ReviewRegressionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.registry = Registry()
        self.rt = Runtime(self.root / 'runtime.sqlite', self.registry)

    def test_nested_global_evaluator_config_invalidates_permit(self):
        _GLOBAL_CONFIG['allowed'] = True
        self.addCleanup(_GLOBAL_CONFIG.update, allowed=True)
        def evaluator(context, condition):
            return Evaluation(Outcome.PASS if all(_GLOBAL_CONFIG['allowed'] for _ in [1]) else Outcome.FAIL, 'nested global')
        self.registry.register('nested-global@1', evaluator)
        doc = gates()
        doc['gates'][0]['conditions'] = [{'requirement': 'configured condition', 'evaluator_ref': 'nested-global@1'}]
        run = self.rt.create_run({'verified': False}, [doc], actors=['agent'], writable_paths=['/verified'])
        p = self.rt.propose(run, 'agent', {'verified': True}, base_version=0)
        self.assertEqual(self.rt.evaluate(p)['outcome'], 'PASS')
        permit = self.rt.authorize(p)
        _GLOBAL_CONFIG['allowed'] = False
        with self.assertRaises(AdmissionError):
            self.rt.commit(permit)
        self.assertEqual(self.rt.snapshot(run)['version'], 0)

    def test_mutable_defaults_and_keyword_defaults_change_fingerprint(self):
        for keyword_only in (False, True):
            with self.subTest(keyword_only=keyword_only):
                config = {'allowed': True}
                if keyword_only:
                    def keyword_evaluator(context, condition, *, config=config):
                        return Evaluation(Outcome.PASS if config['allowed'] else Outcome.FAIL, 'keyword config')
                    evaluator = keyword_evaluator
                else:
                    def default_evaluator(context, condition, config=config):
                        return Evaluation(Outcome.PASS if config['allowed'] else Outcome.FAIL, 'default config')
                    evaluator = default_evaluator
                registry = Registry()
                registry.register('default-config@1', evaluator)
                original = registry.fingerprint()
                config['allowed'] = False
                self.assertNotEqual(registry.fingerprint(), original)

    def test_nested_global_adapter_config_invalidates_dispatch(self):
        _GLOBAL_CONFIG['allowed'] = True
        self.addCleanup(_GLOBAL_CONFIG.update, allowed=True)
        def adapter(args, operation_id):
            return {'allowed': all(_GLOBAL_CONFIG['allowed'] for _ in [1])}
        self.rt.register_operation('nested-global-effect@1', adapter)
        run = self.rt.create_run({'verified': False}, [gates()], actors=['agent'], writable_paths=['/verified'],
            allowed_operations=['nested-global-effect@1'], effect_gate_documents=[gates()])
        p = self.rt.propose(run, 'agent', {'verified': True}, base_version=0,
            operation={'name': 'nested-global-effect@1', 'arguments': {}})
        self.rt.evaluate(p, phase='effect')
        permit = self.rt.authorize(p, purpose='effect')
        _GLOBAL_CONFIG['allowed'] = False
        with self.assertRaises(AdmissionError):
            self.rt.dispatch(permit)

    def test_late_effect_return_cannot_overwrite_reconciliation(self):
        started, release = self.root / 'started', self.root / 'release'
        def adapter(args, operation_id):
            started.write_text('started')
            deadline = time.monotonic() + 4
            while not release.exists() and time.monotonic() < deadline:
                time.sleep(0.01)
            return {'callback_returned': True}
        self.rt.register_operation('fixture@1', adapter)
        run = self.rt.create_run({'verified': False},
            [gates(path='/evidence/operation/status', value='SUCCEEDED')],
            actors=['agent'], writable_paths=['/verified'], allowed_operations=['fixture@1'],
            effect_gate_documents=[gates()], max_seconds=5)
        proposal = self.rt.propose(run, 'agent', {'verified': True}, base_version=0,
            operation={'name': 'fixture@1', 'arguments': {}})
        self.rt.evaluate(proposal, phase='effect')
        permit = self.rt.authorize(proposal, purpose='effect')
        results, errors = [], []
        def dispatch():
            try:
                results.append(self.rt.dispatch(permit))
            except Exception as exc:
                errors.append(exc)
        worker = threading.Thread(target=dispatch)
        worker.start()
        deadline = time.monotonic() + 3
        while not started.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertTrue(started.exists())
        operation_id = 'OP_' + proposal
        self.rt.reconcile_operation(operation_id, status='FAILED', result={'verified': False}, reason='independent postcondition failed')
        release.write_text('release')
        worker.join(6)
        self.assertFalse(worker.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(results[0]['status'], 'FAILED', 'late callback cannot replace an independently recorded outcome')
        self.assertEqual(self.rt.store.read('operation', operation_id)['status'], 'FAILED')
        self.assertEqual(self.rt.evaluate(proposal)['outcome'], 'FAIL')
        with self.assertRaises(AdmissionError):
            self.rt.authorize(proposal)
        self.assertTrue(any(e.get('action') == 'late_effect_result_discarded' for e in self.rt.store.events(run)))

    def test_operation_arguments_are_visible_to_g8son_conditions(self):
        self.rt.register_operation('transfer@1', lambda args, operation_id: {'done': True})
        effect_doc = gates(path='/operation/arguments/destination', value='approved')
        try:
            GateSet(effect_doc)
        except ValueError as exc:
            self.fail('G8SON cannot inspect operation arguments: ' + str(exc))
        run = self.rt.create_run({'verified': False}, [gates()], actors=['agent'], writable_paths=['/verified'],
            allowed_operations=['transfer@1'], effect_gate_documents=[effect_doc])
        p = self.rt.propose(run, 'agent', {'verified': True}, base_version=0,
            operation={'name': 'transfer@1', 'arguments': {'destination': 'unapproved'}})
        self.assertEqual(self.rt.evaluate(p, phase='effect')['outcome'], 'FAIL')
        with self.assertRaises(AdmissionError):
            self.rt.authorize(p, purpose='effect')

    def test_changed_captured_evaluator_config_invalidates_permit(self):
        config = {'pass': True}
        def evaluator(context, condition):
            return Evaluation(Outcome.PASS if config['pass'] else Outcome.FAIL, 'configured assessment')
        self.registry.register('configured@1', evaluator)
        doc = gates()
        doc['gates'][0]['conditions'] = [{'requirement': 'configured condition', 'evaluator_ref': 'configured@1'}]
        run = self.rt.create_run({'verified': False}, [doc], actors=['agent'], writable_paths=['/verified'])
        p = self.rt.propose(run, 'agent', {'verified': True}, base_version=0)
        self.rt.evaluate(p)
        permit = self.rt.authorize(p)
        config['pass'] = False
        with self.assertRaises(AdmissionError):
            self.rt.commit(permit)
        self.assertEqual(self.rt.snapshot(run)['version'], 0)

    def test_phase_purpose_and_receipt_substitution_are_rejected(self):
        self.rt.register_operation('fixture@1', lambda args, operation_id: {})
        run = self.rt.create_run({'verified': False}, [gates(path='/evidence/tests/exit_code', value=0)],
            actors=['agent'], writable_paths=['/verified'], allowed_operations=['fixture@1'], effect_gate_documents=[gates()])
        p = self.rt.propose(run, 'agent', {'verified': True}, base_version=0,
            operation={'name': 'fixture@1', 'arguments': {}})
        self.rt.evaluate(p, phase='effect')
        effect_permit = self.rt.authorize(p, purpose='effect')
        with self.assertRaisesRegex(AdmissionError, 'evaluation phase'):
            self.rt.authorize(p, purpose='commit')
        with self.assertRaises(AdmissionError):
            self.rt.commit(effect_permit)
        other = self.rt.propose(run, 'agent', {'verified': True}, base_version=0)
        self.rt.record_evidence(other, 'tests', {'exit_code': 0}, kind='tool')
        self.assertEqual(self.rt.evaluate(p)['outcome'], 'INTERMEDIATE', 'another proposal receipt must not satisfy this one')
        self.rt.evaluate(other)
        commit_permit = self.rt.authorize(other)
        with self.assertRaisesRegex(AdmissionError, 'evaluation phase'):
            self.rt.authorize(other, purpose='effect')
        with self.assertRaises(AdmissionError):
            self.rt.dispatch(commit_permit)

    def test_changed_captured_operation_config_invalidates_dispatch(self):
        config = {'destination': 'approved'}
        def adapter(args, operation_id):
            return {'destination': config['destination']}
        self.rt.register_operation('configured-effect@1', adapter)
        run = self.rt.create_run({'verified': False}, [gates()], actors=['agent'], writable_paths=['/verified'],
            allowed_operations=['configured-effect@1'], effect_gate_documents=[gates()])
        p = self.rt.propose(run, 'agent', {'verified': True}, base_version=0,
            operation={'name': 'configured-effect@1', 'arguments': {}})
        self.rt.evaluate(p, phase='effect')
        permit = self.rt.authorize(p, purpose='effect')
        config['destination'] = 'unapproved'
        with self.assertRaises(AdmissionError):
            self.rt.dispatch(permit)
