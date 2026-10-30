"""Black-box integration: producer and verifier never share a process."""
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


@unittest.skipUnless(importlib.util.find_spec('nych'), 'optional NYCH integration dependency')
class NychIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / 'run'

    def cli(self, *args):
        module = 'mg8_runtime.nych_verify' if args[0] == 'verify' else 'mg8_runtime.nych_demo'
        command_args = args[1:] if args[0] == 'verify' else args
        return subprocess.run([sys.executable, '-m', module, *map(str, command_args)],
                              cwd=self.tmp.name, capture_output=True, text=True, timeout=60)

    def produce(self, scenario='pass'):
        result = self.cli('run', self.root, '--scenario', scenario)
        self.assertEqual(result.returncode, 0, result.stderr)

    def tamper_record(self, kind, mutate, *, audit=False):
        import sqlite3
        from contextlib import closing
        from mg8_runtime.canonical import digest
        with closing(sqlite3.connect(self.root / 'runtime.sqlite')) as db:
            key, raw = db.execute('SELECT id,record FROM records WHERE kind=? LIMIT 1', (kind,)).fetchone()
            record = json.loads(raw)
            mutate(record)
            db.execute('UPDATE records SET record=? WHERE kind=? AND id=?', (json.dumps(record), kind, key))
            if audit:
                path = self.root / 'execution.qson'
                ledger = json.loads(path.read_text())
                issued = next(e for e in ledger['events'] if e.get('action') == 'permit_issued' and e['evidence']['id'] == key)
                issued['evidence'] = dict(record, status='ISSUED')
                previous = None
                db.execute('DROP TRIGGER events_no_update')
                for event in ledger['events']:
                    event.pop('event_hash')
                    if previous:
                        event['previous_event_hash'] = previous
                    previous = event['event_hash'] = digest(event)
                    db.execute('UPDATE events SET event=? WHERE sequence=?', (json.dumps(event), event['sequence']))
                path.write_text(json.dumps(ledger))
            db.commit()

    def test_rehashed_permit_cannot_bind_another_candidate(self):
        self.produce()
        self.tamper_record('permit', lambda r: r.update(candidate_digest='0' * 64), audit=True)
        self.assertNotEqual(self.cli('verify', self.root).returncode, 0, 'wrong candidate permit accepted')

    def test_rehashed_expired_permit_is_rejected(self):
        for expiry in (0, None, True, 'invalid'):
            with self.subTest(expiry=expiry):
                self.root = Path(self.tmp.name) / str(expiry)
                self.produce()
                self.tamper_record('permit', lambda r: r.update(expires_at=expiry), audit=True)
                self.assertNotEqual(self.cli('verify', self.root).returncode, 0, 'invalid permit expiry accepted')

    def test_permit_must_remain_valid_until_audited_consumption(self):
        from datetime import datetime
        self.produce()
        events = json.loads((self.root / 'execution.qson').read_text())['events']
        issued = next(e for e in events if e.get('action') == 'permit_issued')
        consumed = next(e for e in events if e.get('action') == 'effect_dispatch_prepared')
        timestamp = lambda e: datetime.fromisoformat(e['timestamp'].replace('Z', '+00:00')).timestamp()
        expiry = (timestamp(issued) + timestamp(consumed)) / 2
        self.tamper_record('permit', lambda r: r.update(expires_at=expiry), audit=True)
        self.assertNotEqual(self.cli('verify', self.root).returncode, 0, 'permit expired before dispatch accepted')

    def test_successful_proposal_cannot_be_cancelled(self):
        self.produce()
        self.tamper_record('proposal', lambda r: r.update(status='CANCELLED'))
        self.assertNotEqual(self.cli('verify', self.root).returncode, 0, 'cancelled proposal accepted')

    def test_blocked_run_cannot_claim_complete(self):
        for scenario in ('fail', 'unknown'):
            with self.subTest(scenario=scenario):
                self.root = Path(self.tmp.name) / scenario
                self.produce(scenario)
                self.tamper_record('run', lambda r: r.update(status='COMPLETE'))
                self.assertNotEqual(self.cli('verify', self.root).returncode, 0, 'blocked COMPLETE accepted')

    def test_extra_unaudited_record_is_rejected(self):
        import sqlite3
        from contextlib import closing
        for kind in ('operation', 'receipt', 'permit', 'proposal', 'unknown'):
            with self.subTest(kind=kind):
                self.root = Path(self.tmp.name) / kind
                self.produce()
                with closing(sqlite3.connect(self.root / 'runtime.sqlite')) as db:
                    raw = db.execute("SELECT record FROM records WHERE kind='operation'").fetchone()[0]
                    record = json.loads(raw)
                    record['id'] = 'OP_UNAUTHORIZED_EXTRA'
                    record['operation'] = {'name': 'unauthorized.write@1', 'arguments': {}}
                    db.execute('INSERT INTO records(kind,id,record) VALUES(?,?,?)', (kind, record['id'], json.dumps(record)))
                    db.commit()
                self.assertNotEqual(self.cli('verify', self.root).returncode, 0, 'extra ' + kind + ' accepted')

    def tamper_events(self, mutate):
        import sqlite3
        from contextlib import closing
        from mg8_runtime.canonical import digest
        path = self.root / 'execution.qson'
        ledger = json.loads(path.read_text())
        mutate(ledger['events'])
        previous = None
        with closing(sqlite3.connect(self.root / 'runtime.sqlite')) as db:
            db.execute('DROP TRIGGER events_no_update')
            for event in ledger['events']:
                event.pop('event_hash')
                if previous:
                    event['previous_event_hash'] = previous
                previous = event['event_hash'] = digest(event)
                db.execute('UPDATE events SET event=? WHERE sequence=?', (json.dumps(event), event['sequence']))
            db.commit()
        path.write_text(json.dumps(ledger))

    def test_audited_transition_inventory_and_bindings_are_exact(self):
        edits = {
            'dispatch': lambda es: next(e for e in es if e.get('action') == 'effect_dispatch_prepared')['evidence'].update(status='SUCCEEDED'),
            'proposal': lambda es: next(e for e in es if e.get('action') == 'proposal_received')['evidence'].update(candidate_digest='0' * 64),
            'attempt': lambda es: next(e for e in es if e.get('action') == 'evaluation_started')['evidence'].update(attempt=99),
            'action': lambda es: next(e for e in es if e.get('action') == 'evaluation_started').update(action='unauthorized_transition'),
        }
        for name, edit in edits.items():
            with self.subTest(name=name):
                self.root = Path(self.tmp.name) / name
                self.produce()
                self.tamper_events(edit)
                self.assertNotEqual(self.cli('verify', self.root).returncode, 0, 'unaudited transition accepted: ' + name)

    def test_blocked_evaluation_and_record_inventory_are_bound(self):
        edits = {
            'evaluation': ('proposal', lambda r: r['evaluation'].update(candidate_digest='0' * 64)),
            'attempts': ('run', lambda r: r.update(attempts=99)),
            'epoch': ('proposal', lambda r: r.update(epoch=99)),
        }
        for name, (kind, edit) in edits.items():
            with self.subTest(name=name):
                self.root = Path(self.tmp.name) / name
                self.produce('fail')
                self.tamper_record(kind, edit)
                self.assertNotEqual(self.cli('verify', self.root).returncode, 0, 'blocked binding accepted: ' + name)

    def test_rehashed_commit_cannot_reuse_effect_permit(self):
        import sqlite3
        from contextlib import closing
        from mg8_runtime.canonical import digest
        self.produce()
        path = self.root / 'execution.qson'
        ledger = json.loads(path.read_text())
        effect_permit = next(e['evidence']['id'] for e in ledger['events']
                             if e.get('action') == 'permit_issued' and e['evidence']['purpose'] == 'effect')
        commit = next(e for e in ledger['events'] if e['event_type'] == 'state_commit')
        commit['evidence']['permit_id'] = effect_permit
        previous = None
        for event in ledger['events']:
            event.pop('event_hash')
            if previous:
                event['previous_event_hash'] = previous
            event['event_hash'] = previous = digest(event)
        path.write_text(json.dumps(ledger))
        with closing(sqlite3.connect(self.root / 'runtime.sqlite')) as db:
            db.execute('DROP TRIGGER events_no_update')
            for event in ledger['events']:
                db.execute('UPDATE events SET event=? WHERE sequence=?', (json.dumps(event), event['sequence']))
            db.commit()
        self.assertNotEqual(self.cli('verify', self.root).returncode, 0, 'commit reused effect authority')

    def test_dependency_source_fingerprints_are_persisted_and_anchored(self):
        import sqlite3
        from mg8_runtime.canonical import digest
        self.produce()
        db = sqlite3.connect(self.root / 'runtime.sqlite')
        try:
            key, raw = db.execute("SELECT id,record FROM records WHERE kind='run'").fetchone()
            record = json.loads(raw)
            identity = record['policy']['source_identity']
            self.assertIn('nych/gates.py', identity.get('implementation_sha256', {}))
            identity['distributions']['nych'] = 'tampered'
            record['policy_digest'] = digest(record['policy'])
            db.execute("UPDATE records SET record=? WHERE kind='run' AND id=?", (json.dumps(record), key))
            db.commit()
        finally:
            db.close()
        self.assertNotEqual(self.cli('verify', self.root).returncode, 0)

    def test_tampered_files_and_records_are_rejected(self):
        import shutil
        import sqlite3
        self.produce()
        original = self.root
        for target in ('accepted.txt', 'committed.gst', 'encoded.json', 'effect.g8son',
                       'source.txt', 'execution.qson', 'run', 'operation', 'receipt'):
            with self.subTest(target=target):
                self.root = Path(self.tmp.name) / ('tamper-' + target)
                shutil.copytree(original, self.root)
                path = self.root / target
                if target in ('run', 'operation', 'receipt'):
                    db = sqlite3.connect(self.root / 'runtime.sqlite')
                    try:
                        key, raw = db.execute('SELECT id,record FROM records WHERE kind=? LIMIT 1', (target,)).fetchone()
                        record = json.loads(raw)
                        if target == 'run':
                            record['state']['artifact']['sha256'] = '0' * 64
                        else:
                            record['candidate_digest'] = '0' * 64
                        db.execute('UPDATE records SET record=? WHERE kind=? AND id=?', (json.dumps(record), target, key))
                        db.commit()
                    finally:
                        db.close()
                elif target in ('accepted.txt', 'source.txt'):
                    path.write_text('tampered')
                else:
                    document = json.loads(path.read_text())
                    if target == 'execution.qson':
                        document['events'] = document['events'][:-1]
                    else:
                        document['tampered'] = True
                    path.write_text(json.dumps(document))
                result = self.cli('verify', self.root)
                self.assertNotEqual(result.returncode, 0, target + ' tamper accepted')
        self.root = original

    def test_verifier_is_read_only_and_existing_workdir_is_refused(self):
        import hashlib
        self.produce()
        def hashes():
            return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in self.root.iterdir()}
        before = hashes()
        result = self.cli('verify', self.root)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(hashes(), before)
        self.assertNotEqual(self.cli('run', self.root).returncode, 0)
        self.assertEqual(hashes(), before)

    def test_actual_nych_atomic_requirement_is_recorded(self):
        self.produce()
        ledger = json.loads((self.root / 'execution.qson').read_text())
        attempt = next(e for e in ledger['events'] if e['event_type'] == 'gate_attempt')
        assessments = [r for r in attempt['evidence']['evaluation']['requirements']
                       if r['evidence'].get('implementation') == 'nych.gates.AtomicRequirement']
        self.assertEqual(len(assessments), 1, 'actual NYCH M-Gate adapter missing')
        self.assertEqual(assessments[0]['evidence']['raw_outcome'], 'PASS')

    def test_rehashed_gate_evaluation_tamper_is_rejected(self):
        from mg8_runtime.canonical import digest
        import sqlite3
        self.produce()
        path = self.root / 'execution.qson'
        ledger = json.loads(path.read_text())
        attempt = next(e for e in ledger['events'] if e['event_type'] == 'gate_attempt')
        attempt['evidence']['evaluation']['requirements'][0]['outcome'] = 'FAIL'
        previous = None
        for event in ledger['events']:
            event.pop('event_hash')
            if previous:
                event['previous_event_hash'] = previous
            event['event_hash'] = previous = digest(event)
        path.write_text(json.dumps(ledger))
        from contextlib import closing
        with closing(sqlite3.connect(self.root / 'runtime.sqlite')) as db:
            db.execute('DROP TRIGGER events_no_update')
            for event in ledger['events']:
                db.execute('UPDATE events SET event=? WHERE sequence=?', (json.dumps(event), event['sequence']))
            db.commit()
        result = self.cli('verify', self.root)
        self.assertNotEqual(result.returncode, 0, 'verifier trusted rehashed producer gate results')

    def test_unknown_exact_operation_has_no_effect_or_commit(self):
        self.produce('unknown')
        self.assertFalse((self.root / 'accepted.txt').exists())
        ledger = json.loads((self.root / 'execution.qson').read_text())
        self.assertTrue(any(e.get('result') == 'INTERMEDIATE' for e in ledger['events']))
        self.assertFalse(any(e['event_type'] == 'state_commit' for e in ledger['events']))
        result = self.cli('verify', self.root)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['status'], 'VERIFIED_BLOCKED')

    def test_failed_exact_operation_has_no_effect_or_commit(self):
        self.produce('fail')
        self.assertFalse((self.root / 'accepted.txt').exists())
        ledger = json.loads((self.root / 'execution.qson').read_text())
        self.assertFalse(any(e['event_type'] == 'state_commit' for e in ledger['events']))
        self.assertTrue(any(e.get('result') == 'FAIL' for e in ledger['events']))
        result = self.cli('verify', self.root)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['status'], 'VERIFIED_BLOCKED')

    def test_real_encoding_effect_commit_and_independent_verification(self):
        self.produce()
        result = self.cli('verify', self.root)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(result.stdout.strip(), 'standalone verifier CLI emitted no result')
        self.assertEqual(json.loads(result.stdout)['status'], 'VERIFIED_COMPLETE')
        encoded = json.loads((self.root / 'encoded.json').read_text())
        self.assertNotEqual(encoded['encoded'], encoded['original'])
        self.assertTrue(encoded['records'])
        self.assertEqual((self.root / 'accepted.txt').read_text(), encoded['encoded'] + '\n')
        qson = json.loads((self.root / 'execution.qson').read_text())
        self.assertEqual(len([e for e in qson['events'] if e['event_type'] == 'state_commit']), 1)
        self.assertTrue((self.root / 'unit.mg8').is_file())
