import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class CliTests(unittest.TestCase):
    def test_demo_runs_real_workflow_and_writes_verified_trace(self):
        with tempfile.TemporaryDirectory() as parent:
            output = Path(parent) / 'demo'
            result = subprocess.run([sys.executable, '-m', 'mg8_runtime', 'demo', '--output', str(output)],
                capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)
            report = json.loads(result.stdout)
            self.assertEqual(report['status'], 'COMPLETE')
            trace = json.loads((output / 'execution.qson').read_text())
            self.assertEqual([e['result'] for e in trace['events'] if e['event_type'] == 'gate_attempt'], ['FAIL', 'PASS'])
            self.assertEqual(json.loads((output / 'committed.gst').read_text())['state']['answer'], report['state']['answer'])
            duplicate = subprocess.run([sys.executable, '-m', 'mg8_runtime', 'demo', '--output', str(output)],
                capture_output=True, text=True, timeout=10)
            self.assertNotEqual(duplicate.returncode, 0, 'demo must not overwrite historical evidence')

    def test_canonical_example_runs_through_cli(self):
        with tempfile.TemporaryDirectory() as parent:
            base = Path(__file__).resolve().parents[1] / 'examples' / 'basic'
            trace = Path(parent) / 'execution.qson'
            result = subprocess.run([sys.executable, '-m', 'mg8_runtime', 'run', str(base / 'unit.mg8'),
                '--proposal', str(base / 'proposal.json'), '--database', str(Path(parent) / 'state.sqlite'),
                '--output', str(trace)], capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)['status'], 'COMPLETE')
            self.assertTrue(any(e['event_type'] == 'state_commit' for e in json.loads(trace.read_text())['events']))
