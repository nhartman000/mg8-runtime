import importlib
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path


def gates(op='AND', path='/candidate/verified', value: object=True):
    return {'g8son_version': '1.0', 'file_id': 'test.conditions', 'gates': [{
        'gate_id': 'admission', 'type': op,
        'conditions': [{'path': path, 'op': 'eq', 'value': value}],
        'outcomes': {'PASS': 'commit', 'FAIL': 'reject', 'INTERMEDIATE': 'review'},
    }]}


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'runtime.sqlite'
        try:
            self.api = importlib.import_module('mg8_runtime.runtime')
            self.logic = importlib.import_module('mg8_runtime.gates')
        except ImportError:
            self.fail('the governed runtime is not implemented')
        self.registry = self.logic.Registry()
        self.now = 1000.0
        self.runtime = self.api.Runtime(self.path, self.registry, clock=lambda: self.now)

    def create(self, doc=None, **kwargs):
        return self.runtime.create_run({'verified': False}, [doc or gates()],
                                       actors=['agent'], writable_paths=['/verified'], **kwargs)

    def propose(self, run, verified=True):
        return self.runtime.propose(run, 'agent', {'verified': verified}, base_version=0)

    def permit(self, run):
        proposal = self.propose(run)
        self.assertEqual(self.runtime.evaluate(proposal)['outcome'], 'PASS')
        return self.runtime.authorize(proposal)

    def test_pass_commits_and_survives_reopen(self):
        run = self.create()
        permit = self.permit(run)
        self.runtime.commit(permit)
        reopened = self.api.Runtime(self.path, self.registry, clock=lambda: self.now)
        self.assertEqual(reopened.snapshot(run)['state'], {'verified': True})
        self.assertEqual(reopened.snapshot(run)['version'], 1)
        ledger = reopened.store.qson(run)
        self.assertEqual(sum(e['event_type'] == 'state_commit' for e in ledger['events']), 1)

    def test_false_and_missing_evidence_cannot_authorize(self):
        for doc, expected in [(gates(value=False), 'FAIL'),
                              (gates(path='/evidence/tests/exit_code', value=0), 'INTERMEDIATE')]:
            with self.subTest(expected=expected):
                run = self.create(doc)
                proposal = self.propose(run)
                self.assertEqual(self.runtime.evaluate(proposal)['outcome'], expected)
                with self.assertRaises(self.api.AdmissionError):
                    self.runtime.authorize(proposal)
                self.assertEqual(self.runtime.snapshot(run)['version'], 0)

    def test_evidence_requires_host_receipt_and_exact_candidate(self):
        run = self.create(gates(path='/evidence/tests/exit_code', value=0))
        proposal = self.propose(run)
        self.runtime.record_evidence(proposal, 'tests', {'exit_code': 0}, kind='tool', expires_at=1010)
        self.assertEqual(self.runtime.evaluate(proposal)['outcome'], 'PASS')
        permit = self.runtime.authorize(proposal)
        self.now = 1011
        with self.assertRaises(self.api.AdmissionError):
            self.runtime.commit(permit)
        self.assertEqual(self.runtime.snapshot(run)['version'], 0)

    def test_permits_are_single_use_and_revocable(self):
        run = self.create()
        permit = self.permit(run)
        self.runtime.revoke(permit, 'operator request')
        with self.assertRaises(self.api.AdmissionError):
            self.runtime.commit(permit)
        run2 = self.create()
        permit2 = self.permit(run2)
        self.runtime.commit(permit2)
        with self.assertRaises(self.api.AdmissionError):
            self.runtime.commit(permit2)

    def test_cancellation_and_policy_changes_invalidate_permits(self):
        for cancel in [True, False]:
            run = self.create()
            permit = self.permit(run)
            if cancel:
                self.runtime.cancel(run)
            else:
                self.runtime.revise_policy(run, [gates(value=False)])
            with self.assertRaises(self.api.AdmissionError):
                self.runtime.commit(permit)
            self.assertEqual(self.runtime.snapshot(run)['version'], 0)

    def test_scope_and_actor_cannot_be_overridden(self):
        run = self.create()
        with self.assertRaises(self.api.AdmissionError):
            self.runtime.propose(run, 'intruder', {'verified': True}, base_version=0)
        with self.assertRaises(self.api.AdmissionError):
            self.runtime.propose(run, 'agent', {'verified': True, 'gate_result': 'PASS'}, base_version=0)

    def test_competing_permits_only_one_can_commit(self):
        run = self.create()
        permits = [self.permit(run), self.permit(run)]
        def commit(permit):
            rt = self.api.Runtime(self.path, self.registry, clock=lambda: self.now)
            try:
                rt.commit(permit)
                return True
            except self.api.AdmissionError:
                return False
        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual(sum(pool.map(commit, permits)), 1)
        self.assertEqual(self.runtime.snapshot(run)['version'], 1)

    def test_loop_bound_is_not_reset_by_new_proposal(self):
        run = self.create(gates(value=False), max_attempts=2)
        for _ in range(2):
            self.runtime.evaluate(self.propose(run))
        with self.assertRaises(self.api.AdmissionError):
            self.runtime.evaluate(self.propose(run))
        self.assertEqual(self.runtime.snapshot(run)['status'], 'UNRESOLVED')

    def test_expired_permit_and_changed_evidence_are_rejected(self):
        run = self.create()
        permit = self.permit(run)
        self.now += 61
        with self.assertRaises(self.api.AdmissionError):
            self.runtime.commit(permit)
        self.now = 1000
        run2 = self.create()
        proposal = self.propose(run2)
        self.runtime.evaluate(proposal)
        permit2 = self.runtime.authorize(proposal)
        self.runtime.record_evidence(proposal, 'new', 1, kind='runtime')
        with self.assertRaises(self.api.AdmissionError):
            self.runtime.commit(permit2)

    def test_rollback_never_publishes_state_without_audit(self):
        run = self.create()
        permit = self.permit(run)
        def fail(point):
            if point == 'after_state_write':
                raise RuntimeError('injected crash')
        self.runtime.fault_hook = fail
        with self.assertRaises(RuntimeError):
            self.runtime.commit(permit)
        self.assertEqual(self.runtime.snapshot(run)['version'], 0)
        self.assertEqual(self.runtime.store.read('permit', permit)['status'], 'ISSUED')
        self.assertFalse(any(e['event_type'] == 'state_commit' for e in self.runtime.store.events(run)))
        self.runtime.fault_hook = None
        self.runtime.commit(permit)

    def test_required_admissibility_is_not_a_model_claim(self):
        run = self.create(admissibility_ref='not-installed')
        proposal = self.propose(run)
        self.assertEqual(self.runtime.evaluate(proposal)['outcome'], 'INTERMEDIATE')
        with self.assertRaises(self.api.AdmissionError):
            self.runtime.authorize(proposal)
