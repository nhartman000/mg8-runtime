"""Acceptance checks must survive optimization, including inherited settings."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


class WheelDriverTests(unittest.TestCase):
    def test_corrupt_schema_rejected_under_optimization(self):
        driver = Path(__file__).resolve().parents[1] / 'tools/check_wheel_install.py'
        probe = '''
import pathlib, runpy, subprocess, sys, zipfile
from unittest.mock import patch

def fake_build(command, **kwargs):
    output = pathlib.Path(command[command.index('--outdir') + 1])
    output.mkdir()
    with zipfile.ZipFile(output / 'mg8_runtime-corrupt.whl', 'w') as archive:
        for name in ('g8son.schema.json', 'qson.schema.json'):
            archive.writestr('data/share/mg8-runtime/schemas/' + name, '{}')
    return subprocess.CompletedProcess(command, 0)

with patch('subprocess.run', fake_build):
    driver = sys.argv.pop(1)
    runpy.run_path(driver, run_name='__main__')
'''
        with tempfile.TemporaryDirectory() as temp:
            wheel = Path(temp) / 'nych.whl'
            wheel.touch()
            result = subprocess.run([sys.executable, '-O', '-c', probe, str(driver),
                                     '--nych-wheel', str(wheel), '--output', str(Path(temp) / 'out')],
                                    capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('runtime wheel schema bytes differ', result.stderr)

    def test_corrupt_package_schema_is_rejected(self):
        driver = Path(__file__).resolve().parents[1] / 'tools/check_wheel_install.py'
        probe = '''
import pathlib, runpy, subprocess, sys, zipfile
from unittest.mock import patch
root = pathlib.Path(sys.argv[1]).parent.parent

def fake_build(command, **kwargs):
    output = pathlib.Path(command[command.index('--outdir') + 1])
    output.mkdir()
    with zipfile.ZipFile(output / 'mg8_runtime-corrupt.whl', 'w') as archive:
        for name in ('g8son.schema.json', 'qson.schema.json'):
            archive.writestr('data/share/mg8-runtime/schemas/' + name, (root / 'schemas' / name).read_bytes())
            archive.writestr('mg8_runtime/schemas/' + name, '{}')
    return subprocess.CompletedProcess(command, 0)

with patch('subprocess.run', fake_build):
    driver = sys.argv.pop(1)
    runpy.run_path(driver, run_name='__main__')
'''
        with tempfile.TemporaryDirectory() as temp:
            wheel = Path(temp) / 'nych.whl'
            wheel.touch()
            result = subprocess.run([sys.executable, '-O', '-c', probe, str(driver),
                                     '--nych-wheel', str(wheel), '--output', str(Path(temp) / 'out')],
                                    capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('runtime wheel package schema bytes differ', result.stderr)

    def test_subprocess_environment_removes_optimization(self):
        import runpy
        from unittest.mock import patch
        driver = Path(__file__).resolve().parents[1] / 'tools/check_wheel_install.py'
        captured = {}
        class StopProbe(Exception):
            pass
        def stop(command, **kwargs):
            captured.update(kwargs['env'])
            raise StopProbe()
        with tempfile.TemporaryDirectory() as temp:
            wheel = Path(temp) / 'nych.whl'
            wheel.touch()
            argv = [str(driver), '--nych-wheel', str(wheel), '--output', str(Path(temp) / 'out')]
            with patch.dict(os.environ, {'PYTHONOPTIMIZE': '2', 'PYTHONPATH': '/untrusted', 'PYTHONHOME': '/untrusted'}), \
                    patch.object(sys, 'argv', argv), patch('subprocess.run', stop):
                with self.assertRaises(StopProbe):
                    runpy.run_path(str(driver), run_name='__main__')
        for name in ('PYTHONOPTIMIZE', 'PYTHONPATH', 'PYTHONHOME'):
            self.assertNotIn(name, captured)
