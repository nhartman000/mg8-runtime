import os
from contextlib import closing
from pathlib import Path
import tempfile
import unittest


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'nested' / 'store.db'

    def test_records_commit_reopen_detached_and_rollback(self):
        from mg8_runtime.store import Store
        store = Store(self.path)
        record = {'anything': {'value': [1]}}
        with store.transaction() as tx:
            tx.put('state', 's', record)
            record['anything']['value'].append(2)
            fetched = tx.get('state', 's')
            fetched['anything']['value'].append(3)
            self.assertEqual(tx.all('state'), [{'anything': {'value': [1]}}])
        self.assertEqual(Store(str(self.path)).read('state', 's'), {'anything': {'value': [1]}})
        with self.assertRaises(RuntimeError):
            with store.transaction() as tx:
                tx.put('state', 's', {'changed': True})
                raise RuntimeError('rollback')
        self.assertEqual(store.all('state'), [{'anything': {'value': [1]}}])
        with self.assertRaises(KeyError):
            store.read('state', 'missing')
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)

    def test_events_are_durable_chained_and_exported_canonically(self):
        from mg8_runtime.store import Store
        from mg8_runtime import canonical
        import json
        import uuid
        from datetime import datetime, timezone
        store = Store(self.path)
        before = datetime.now(timezone.utc)
        with store.transaction() as tx:
            first = tx.event('run', 'gate_attempt', file_id='f', gate_id='g',
                             input_state_id='s', result='INTERMEDIATE')
            second = tx.event('run', 'state_commit', input_state_id='s', output_state_id='s2')
            tx.event('other', 'review')
        self.assertEqual(first['sequence'], 1)
        self.assertEqual(second['sequence'], 2)
        self.assertNotEqual(first['trace_id'], second['trace_id'])
        uuid.UUID(first['trace_id'])
        self.assertGreaterEqual(datetime.fromisoformat(first['timestamp'].replace('Z', '+00:00')), before)
        self.assertEqual(first['actor'], {'type': 'runtime', 'id': 'mg8-runtime'})
        self.assertNotIn('previous_event_hash', first)
        self.assertEqual(second['previous_event_hash'], first['event_hash'])
        unsigned = dict(first)
        del unsigned['event_hash']
        self.assertEqual(first['event_hash'], canonical.digest(unsigned))
        first['actor']['id'] = 'mutated'
        ledger = Store(self.path).qson('run')
        self.assertEqual(ledger['qson_version'], '1.0')
        self.assertEqual(ledger['run_id'], 'run')
        self.assertEqual(len(ledger['events']), 2)
        self.assertEqual(ledger['events'][0]['actor']['id'], 'mg8-runtime')
        target = Path(self.tmp.name) / 'output' / 'trace.qson'
        store.export_qson('run', target)
        self.assertEqual(target.read_text(), canonical.dumps(ledger))
        self.assertEqual(json.loads(target.read_text()), ledger)
        with self.assertRaises(ValueError):
            store.qson('absent')

    def test_event_validation_and_atomic_rollback(self):
        from mg8_runtime.store import Store
        store = Store(self.path)
        invalid = [
            ('unknown', {}), ('review', {'result': 'UNKNOWN'}),
            ('review', {'actor': 'runtime'}), ('review', {'actor': {'type': 'runtime'}}),
            ('review', {'actor': {'type': '', 'id': 'x'}}),
            ('review', {'sequence': 8}), ('review', {'trace_id': 'forged'}),
            ('review', {'timestamp': 'forged'}), ('review', {'event_hash': 'forged'}),
            ('review', {'previous_event_hash': 'forged'}),
            ('gate_attempt', {}), ('state_commit', {'input_state_id': 's'}),
        ]
        for event_type, fields in invalid:
            with self.subTest(event_type=event_type, fields=fields):
                with self.assertRaises((ValueError, TypeError)):
                    with store.transaction() as tx:
                        tx.event('run', event_type, **fields)
        with self.assertRaises(RuntimeError):
            with store.transaction() as tx:
                tx.put('state', 's', {'committed': False})
                tx.event('run', 'review')
                raise RuntimeError('crash')
        self.assertEqual(store.events('run'), [])
        self.assertEqual(store.all('state'), [])
        with store.transaction() as tx:
            self.assertEqual(tx.event('run', 'review')['sequence'], 1)


    def test_sqlite_durability_and_strict_json_records(self):
        from mg8_runtime.store import Store
        store = Store(self.path)
        connection = store._connect()
        try:
            self.assertEqual(connection.execute('PRAGMA journal_mode').fetchone()[0], 'wal')
            self.assertEqual(connection.execute('PRAGMA synchronous').fetchone()[0], 2)
            self.assertGreaterEqual(connection.execute('PRAGMA busy_timeout').fetchone()[0], 1000)
        finally:
            connection.close()
        for record in ([], {'bad': float('nan')}, {1: 'nonstring-key'}):
            with self.subTest(record=record), self.assertRaises(ValueError):
                with store.transaction() as tx:
                    tx.put('generic', 'x', record)
        self.assertEqual(store.all('generic'), [])

    def test_export_failure_preserves_previous_file_and_cleans_temp(self):
        from mg8_runtime.store import Store
        from unittest.mock import patch
        store = Store(self.path)
        with store.transaction() as tx:
            tx.event('run', 'review')
        target = Path(self.tmp.name) / 'trace.qson'
        target.write_text('old ledger')
        with patch('mg8_runtime.store.os.replace', side_effect=OSError('injected failure')):
            with self.assertRaises(OSError):
                store.export_qson('run', target)
        self.assertEqual(target.read_text(), 'old ledger')
        self.assertEqual(list(target.parent.glob('.trace.qson.*')), [])

    def test_sql_events_reject_updates_and_deletes(self):
        from mg8_runtime.store import Store
        import sqlite3
        store = Store(self.path)
        with store.transaction() as tx:
            tx.event('run', 'review')
        with closing(sqlite3.connect(self.path)) as connection, connection:
            for sql in ('UPDATE events SET sequence=9', 'DELETE FROM events',
                        'INSERT OR REPLACE INTO events SELECT * FROM events'):
                with self.subTest(sql=sql), self.assertRaises(sqlite3.IntegrityError):
                    connection.execute(sql)
        self.assertEqual(len(store.qson('run')['events']), 1)

    def test_concurrent_thread_and_process_writers(self):
        from mg8_runtime.store import Store
        from concurrent.futures import ThreadPoolExecutor
        import subprocess
        import sys
        store = Store(self.path)
        def writer(number):
            local = Store(self.path)
            for index in range(8):
                with local.transaction() as tx:
                    tx.put('items', f'{number}-{index}', {'n': number, 'i': index})
                    tx.event('run', 'review')
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(writer, range(4)))
        code = "from mg8_runtime.store import Store; import sys; s=Store(sys.argv[1]); " \
               "exec('for i in range(8):\\n with s.transaction() as t:\\n  t.event(\\\"run\\\", \\\"review\\\")')"
        processes = [subprocess.Popen([sys.executable, '-c', code, str(self.path)],
                                     stdout=subprocess.PIPE, stderr=subprocess.PIPE) for _ in range(3)]
        for process in processes:
            _, stderr = process.communicate(timeout=30)
            self.assertEqual(process.returncode, 0, stderr.decode())
        self.assertEqual([event['sequence'] for event in store.qson('run')['events']], list(range(1, 57)))
        self.assertEqual(len(store.all('items')), 32)

    def test_process_exit_rolls_back_records_and_events(self):
        from mg8_runtime.store import Store
        import subprocess
        import sys
        store = Store(self.path)
        with store.transaction() as tx:
            tx.put('state', 's', {'version': 1})
            tx.event('run', 'review')
        code = "from mg8_runtime.store import Store; import sys,os; s=Store(sys.argv[1]); " \
               "exec('with s.transaction() as t:\\n t.put(\\\"state\\\", \\\"s\\\", {\\\"version\\\":2})\\n t.event(\\\"run\\\", \\\"review\\\")\\n os._exit(19)')"
        result = subprocess.run([sys.executable, '-c', code, str(self.path)], capture_output=True, timeout=20)
        self.assertEqual(result.returncode, 19, result.stderr.decode())
        reopened = Store(self.path)
        self.assertEqual(reopened.read('state', 's'), {'version': 1})
        self.assertEqual(len(reopened.events('run')), 1)
        with reopened.transaction() as tx:
            self.assertEqual(tx.event('run', 'review')['sequence'], 2)

    def test_qson_rejects_corrupt_schema_and_hashes(self):
        from mg8_runtime.store import Store
        from mg8_runtime import canonical
        import json
        import sqlite3
        store = Store(self.path)
        with store.transaction() as tx:
            original = tx.event('run', 'gate_attempt', file_id='f', gate_id='g',
                                input_state_id='s', result='PASS')
        mutations = [dict(original, run_id='other'), dict(original, sequence=True),
                     dict(original, trace_id='bad'), dict(original, actor={}),
                     dict(original, previous_event_hash='bad'), dict(original, event_hash='bad'),
                     dict(original, result='UNKNOWN'), dict(original, gate_id='')]
        with closing(sqlite3.connect(self.path)) as connection, connection:
            for name, in connection.execute("SELECT name FROM sqlite_master WHERE type='trigger'").fetchall():
                connection.execute('DROP TRIGGER "' + name + '"')
            for event in mutations:
                connection.execute('UPDATE events SET event=?', (json.dumps(event),))
                connection.commit()
                with self.subTest(event=event), self.assertRaises(ValueError):
                    store.qson('run')
            connection.execute('UPDATE events SET event=?', (canonical.dumps(original),))
        self.assertEqual(len(store.qson('run')['events']), 1)


if __name__ == '__main__':
    unittest.main()
