import tempfile
import unittest
from pathlib import Path
from mg8_runtime.gates import Registry
from mg8_runtime.loader import load_unit
from mg8_runtime.runtime import Runtime


class SourceBindingTests(unittest.TestCase):
    def test_loaded_source_identity_is_durable_and_audited(self):
        unit = load_unit(Path(__file__).resolve().parents[1] / 'examples/basic/unit.mg8')
        with tempfile.TemporaryDirectory() as tmp:
            rt = Runtime(Path(tmp) / 'runtime.sqlite', Registry())
            run = unit.start(rt)
            policy = rt.store.read('run', run)['policy']
            self.assertIn('source_identity', policy, 'loaded byte digests must survive runtime admission')
            self.assertEqual(policy['source_identity']['unit_id'], unit.manifest['unit_id'])
            self.assertEqual(policy['source_identity']['resources'], unit.sources)
            self.assertEqual(rt.store.events(run)[0]['evidence']['source_identity'], policy['source_identity'])
            rt.revise_policy(run, unit.gate_documents)
            self.assertIsNone(rt.store.read('run', run)['policy']['source_identity'], 'programmatic revisions must not claim unchanged source bytes')
