import json
import re
import tempfile
import unittest
from pathlib import Path
from jsonschema import Draft7Validator, FormatChecker

from mg8_runtime.store import Store

ROOT = Path(__file__).resolve().parents[1]


class SchemaTests(unittest.TestCase):
    def test_actual_persisted_qson_matches_pinned_canonical_schema(self):
        schema = json.loads((ROOT / 'schemas/qson.schema.json').read_text())
        Draft7Validator.check_schema(schema)
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(Path(tmp) / 'runtime.sqlite')
            with store.transaction() as tx:
                tx.event('RUN_fixture', 'gate_attempt', gate_id='g', file_id='f', input_state_id='s', result='PASS')
                tx.event('RUN_fixture', 'state_commit', input_state_id='s', output_state_id='s2')
            errors = list(Draft7Validator(schema, format_checker=FormatChecker()).iter_errors(store.qson('RUN_fixture')))
            self.assertEqual(errors, [], '\n'.join(error.message for error in errors))

    def test_contract_json_examples_match_g8son_envelope(self):
        schema = json.loads((ROOT / 'schemas/g8son.schema.json').read_text())
        doc = (ROOT / 'docs/AGENT_RUNTIME_CONTRACT.md').read_text()
        for block in re.findall(r'```json\n(.*?)\n```', doc, re.S):
            Draft7Validator(schema).validate(json.loads(block))
