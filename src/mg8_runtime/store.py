"""Host-owned durable state and append-only evidence; not an agent sandbox."""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import uuid
from datetime import datetime, timezone

from . import canonical

EVENT_TYPES = frozenset({'gate_attempt', 'override', 'correction', 'state_commit',
                         'external_input', 'runtime_error', 'review'})
RESULTS = frozenset({'PASS', 'FAIL', 'INTERMEDIATE'})
RESERVED = frozenset({'trace_id', 'sequence', 'run_id', 'event_type', 'timestamp',
                      'actor', 'previous_event_hash', 'event_hash'})


def _identity(value, name):
    if type(value) is not str or not value.strip():
        raise ValueError(f'{name} must be a nonempty string')


def _validate_event(event):
    for name in ('run_id', 'trace_id', 'timestamp'):
        _identity(event.get(name), name)
    try:
        uuid.UUID(event['trace_id'])
        timestamp = datetime.fromisoformat(event['timestamp'].replace('Z', '+00:00'))
        offset = timestamp.utcoffset()
        if offset is None or offset.total_seconds() != 0:
            raise ValueError('timestamp must be UTC')
    except (ValueError, TypeError, AttributeError) as exc:
        raise ValueError('invalid event identity or UTC timestamp') from exc
    if type(event.get('sequence')) is not int or event['sequence'] < 1:
        raise ValueError('invalid sequence')
    if event.get('event_type') not in EVENT_TYPES:
        raise ValueError('unsupported event type')
    actor = event.get('actor')
    if type(actor) is not dict:
        raise ValueError('actor must be a structured identity')
    for name in ('type', 'id'):
        _identity(actor.get(name), 'actor.' + name)
    if 'result' in event and event['result'] not in RESULTS:
        raise ValueError('unsupported result')
    required = {'gate_attempt': ('file_id', 'gate_id', 'input_state_id', 'result'),
                'state_commit': ('input_state_id', 'output_state_id')}
    for name in required.get(event['event_type'], ()):
        _identity(event.get(name), name)
    canonical.dumps(event)



class Transaction:
    def __init__(self, connection):
        self._connection = connection

    def get(self, kind, id):
        row = self._connection.execute(
            'SELECT record FROM records WHERE kind=? AND id=?', (kind, id)
        ).fetchone()
        if row is None:
            raise KeyError((kind, id))
        return json.loads(row[0])

    def put(self, kind, id, record):
        if type(record) is not dict:
            raise ValueError('record must be an object')
        self._connection.execute(
            'INSERT INTO records(kind,id,record) VALUES(?,?,?) '
            'ON CONFLICT(kind,id) DO UPDATE SET record=excluded.record',
            (kind, id, canonical.dumps(record)),
        )

    def all(self, kind):
        return [json.loads(row[0]) for row in self._connection.execute(
            'SELECT record FROM records WHERE kind=? ORDER BY id', (kind,)
        )]

    def event(self, run_id, event_type, actor=None, **fields):
        if RESERVED.intersection(fields):
            raise ValueError('reserved event fields cannot be overridden')
        _identity(run_id, 'run_id')
        previous = self._connection.execute(
            'SELECT sequence,event FROM events WHERE run_id=? ORDER BY sequence DESC LIMIT 1',
            (run_id,),
        ).fetchone()
        event = dict(fields)
        event.update(run_id=run_id, event_type=event_type,
                     trace_id=str(uuid.uuid4()), sequence=previous[0] + 1 if previous else 1,
                     timestamp=datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
                     actor=actor if actor is not None else {'type': 'runtime', 'id': 'mg8-runtime'})
        if previous:
            event['previous_event_hash'] = json.loads(previous[1])['event_hash']
        _validate_event(event)
        event['event_hash'] = canonical.digest(event)
        self._connection.execute(
            'INSERT INTO events(run_id,sequence,trace_id,event) VALUES(?,?,?,?)',
            (run_id, event['sequence'], event['trace_id'], canonical.dumps(event)),
        )
        return canonical.clone(event)


class Store:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.path, os.O_CREAT | os.O_RDWR, 0o600)
        os.close(fd)
        self.path.chmod(0o600)
        connection = self._connect()
        try:
            connection.execute('PRAGMA journal_mode=WAL')
            connection.execute('CREATE TABLE IF NOT EXISTS records '
                               '(kind TEXT NOT NULL,id TEXT NOT NULL,record TEXT NOT NULL,'
                               'PRIMARY KEY(kind,id))')
            connection.execute('CREATE TABLE IF NOT EXISTS events '
                               '(run_id TEXT NOT NULL,sequence INTEGER NOT NULL CHECK(sequence>0),'
                               'trace_id TEXT NOT NULL UNIQUE,event TEXT NOT NULL,'
                               'PRIMARY KEY(run_id,sequence))')
            connection.execute(
                'CREATE TRIGGER IF NOT EXISTS events_no_replace BEFORE INSERT ON events '
                'WHEN EXISTS (SELECT 1 FROM events WHERE trace_id=NEW.trace_id '
                'OR (run_id=NEW.run_id AND sequence=NEW.sequence)) BEGIN '
                "SELECT RAISE(ABORT, 'events are append-only'); END"
            )
            for operation in ('UPDATE', 'DELETE'):
                connection.execute(
                    f'CREATE TRIGGER IF NOT EXISTS events_no_{operation.lower()} '
                    f'BEFORE {operation} ON events BEGIN '
                    "SELECT RAISE(ABORT, 'events are append-only'); END"
                )
        finally:
            connection.close()

    def _connect(self):
        connection = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        connection.execute('PRAGMA busy_timeout=30000')
        connection.execute('PRAGMA synchronous=FULL')
        return connection

    @contextmanager
    def transaction(self):
        connection = self._connect()
        try:
            connection.execute('BEGIN IMMEDIATE')
            yield Transaction(connection)
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def events(self, run_id):
        connection = self._connect()
        try:
            return [json.loads(row[0]) for row in connection.execute(
                'SELECT event FROM events WHERE run_id=? ORDER BY sequence', (run_id,)
            )]
        finally:
            connection.close()

    def qson(self, run_id):
        _identity(run_id, 'run_id')
        events = self.events(run_id)
        if not events:
            raise ValueError('QSON requires a nonempty ledger')
        previous_hash = None
        previous_sequence = 0
        traces = set()
        for event in events:
            _validate_event(event)
            if event['run_id'] != run_id or event['sequence'] <= previous_sequence:
                raise ValueError('inconsistent run or event ordering')
            if event['trace_id'] in traces:
                raise ValueError('duplicate trace identity')
            if event.get('previous_event_hash') != previous_hash:
                raise ValueError('broken event hash chain')
            unsigned = dict(event)
            event_hash = unsigned.pop('event_hash', None)
            if event_hash != canonical.digest(unsigned):
                raise ValueError('invalid event hash')
            traces.add(event['trace_id'])
            previous_sequence = event['sequence']
            previous_hash = event_hash
        return {'qson_version': '1.0', 'run_id': run_id, 'events': events}

    def export_qson(self, run_id, path):
        payload = canonical.dumps(self.qson(run_id)).encode('utf-8')
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix='.' + path.name + '.', dir=path.parent)
        try:
            with os.fdopen(fd, 'wb') as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
            directory_fd = os.open(path.parent, os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0))
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def read(self, kind, id):
        connection = self._connect()
        try:
            return Transaction(connection).get(kind, id)
        finally:
            connection.close()

    def all(self, kind):
        connection = self._connect()
        try:
            return Transaction(connection).all(kind)
        finally:
            connection.close()
