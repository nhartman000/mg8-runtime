"""Build sdist + wheel, install only wheels into a fresh venv, test off-tree.

Supply a separately built NYCH wheel. No editable/source/PYTHONPATH fallback.
Network may be needed for build/install dependencies, never for demo execution.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
import venv
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--nych-wheel', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    wheel_nych = args.nych_wheel.resolve(strict=True)
    output = args.output.resolve()
    output.mkdir(exist_ok=False)
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1', PIP_DISABLE_PIP_VERSION_CHECK='1')
    for key in ('PYTHONPATH', 'PYTHONHOME', 'PYTHONOPTIMIZE'):
        env.pop(key, None)

    def call(command, cwd=output):
        print('+', ' '.join(map(str, command)), flush=True)
        subprocess.run(list(map(str, command)), cwd=cwd, env=env, check=True)

    call([sys.executable, '-m', 'build', '--outdir', output / 'dist', ROOT])
    direct = next((output / 'dist').glob('mg8_runtime-*.whl'))
    with zipfile.ZipFile(direct) as archive:
        for name in ('g8son.schema.json', 'qson.schema.json'):
            member = next((n for n in archive.namelist() if n.endswith('/share/mg8-runtime/schemas/' + name)), None)
            if member is None:
                raise ValueError('runtime wheel omits canonical schema: ' + name)
            if archive.read(member) != (ROOT / 'schemas' / name).read_bytes():
                raise ValueError('runtime wheel schema bytes differ: ' + name)
            packaged = 'mg8_runtime/schemas/' + name
            if packaged not in archive.namelist():
                raise ValueError('runtime wheel omits package schema: ' + name)
            if archive.read(packaged) != (ROOT / 'schemas' / name).read_bytes():
                raise ValueError('runtime wheel package schema bytes differ: ' + name)
    sdist = next((output / 'dist').glob('*.tar.gz'))
    unpack = output / 'sdist'
    unpack.mkdir()
    with tarfile.open(sdist) as archive:
        archive.extractall(unpack, filter='data')
    call([sys.executable, '-m', 'build', '--wheel', '--outdir', output / 'rebuilt', next(unpack.iterdir())])
    wheel_runtime = next((output / 'rebuilt').glob('*.whl'))
    venv.EnvBuilder(with_pip=True).create(output / 'venv')
    python = output / 'venv/bin/python'
    call([python, '-m', 'pip', 'install', str(wheel_runtime) + '[integration]', wheel_nych])
    call([python, '-I', '-c', "import pathlib,sys,nych,mg8_runtime; from nych.schemas.qson import QSONValidator; "
          "bad=[m.__file__ for m in (nych,mg8_runtime) if not pathlib.Path(m.__file__).is_relative_to(sys.prefix)]; "
          "bad and sys.exit('imports outside fresh environment: '+repr(bad)); "
          "print('wheel imports:',nych.__file__,mg8_runtime.__file__)"])
    call([python, '-I', '-m', 'pip', 'check'])
    # Copy tests and their read-only fixtures, never src/: imported code must
    # remain the installed wheel rather than a checkout shadowing it.
    suite = output / 'suite'
    suite.mkdir()
    for name in ('tests', 'examples', 'schemas', 'docs', 'tools'):
        shutil.copytree(ROOT / name, suite / name, ignore=shutil.ignore_patterns('__pycache__'))
    call([python, '-I', '-m', 'unittest', 'discover', '-s', suite / 'tests', '-t', suite, '-v'])
    # Exercise pip --target: schemas must resolve beside the imported package,
    # not via sys.prefix or the producer's checkout.
    target = output / 'target'
    call([python, '-m', 'pip', 'install', '--no-deps', '--target', target, wheel_runtime])
    target_probe = ("import pathlib,runpy,sys; sys.path.insert(0,sys.argv.pop(1)); "
                    "import mg8_runtime; "
                    "pathlib.Path(mg8_runtime.__file__).is_relative_to(sys.argv.pop(1)) or sys.exit('target import missing'); "
                    "runpy.run_module('mg8_runtime.nych_verify',run_name='__main__')")
    for scenario in ('pass', 'fail', 'unknown'):
        call([python, '-I', '-m', 'mg8_runtime.nych_demo', 'run', output / scenario, '--scenario', scenario])
        call([python, '-I', '-m', 'mg8_runtime.nych_verify', output / scenario])
        call([python, '-I', '-c', target_probe, target, target, output / scenario])
    result = {'status': 'PASS', 'runtime_wheel': str(wheel_runtime), 'nych_wheel': str(wheel_nych),
              'sha256': {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (wheel_runtime, wheel_nych)},
              'scope': 'fresh venv; sdist-built wheel; off-tree integration tests; no model inference'}
    (output / 'result.json').write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
