"""Canonical schemas must travel with an importable package, not sys.prefix."""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


class SchemaResourceTests(unittest.TestCase):
    def test_relocated_package_uses_unchanged_canonical_schemas(self):
        import mg8_runtime
        package = Path(mg8_runtime.__file__).parent
        canonical = Path(__file__).resolve().parents[1] / 'schemas'
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / 'target'
            shutil.copytree(package, target / 'mg8_runtime', ignore=shutil.ignore_patterns('__pycache__'))
            # A pip --target/--user package need not live beneath sys.prefix.
            probe = '''
import json, sys, sysconfig
sys.path.insert(0, sys.argv[1])
sysconfig.get_path = lambda *args, **kwargs: sys.argv[2]
from mg8_runtime.nych_verify import schema
print(json.dumps({name: schema(name) for name in ('g8son.schema.json', 'qson.schema.json')}))
'''
            result = subprocess.run([sys.executable, '-I', '-c', probe, str(target), str(Path(temp) / 'no-prefix-data')],
                                    cwd=temp, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout), {
                name: json.loads((canonical / name).read_text())
                for name in ('g8son.schema.json', 'qson.schema.json')})
