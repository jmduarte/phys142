"""Publish one changed Lab 09 from required, verified reusable release state."""

import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

from relocate_labs import site_manifest


MEMBER = 'labs/lab09/lab09.ipynb'
SCHEMA = 'phys142-lab09-publication-v1'
BASE_MANIFEST = '99f5b33ecfb768e50eb6839d3d898bd3fe7bce5d326b468e30ae767224b8c7bc'
BASE_COMMIT = '0e4a5c981db44cfd948e7253992086c7ff0f9ea9'
PUBLICATION_FILES = {
    MEMBER, '.github/workflows/publish-lab09.yml',
    'ci/publish_lab09.py', 'ci/patch_lab09_release.py',
    'ci/test_publish_lab09.py', 'ci/test_patch_lab09_release.py',
    'ci/lab09-publish-requirements.txt', 'ci/LAB09_PUBLISH.md',
}
CONFIG = '''title: UCSD PHYS 142/242
author: Javier Duarte
execute:
  execute_notebooks: force
  timeout: 120
sphinx:
  config:
    nb_execution_raise_on_error: true
'''


def sha256(content):
    return hashlib.sha256(content).hexdigest()


def _digest(value):
    if not isinstance(value, str) or not re.fullmatch(r'[0-9a-f]{64}', value):
        raise ValueError('State requires complete lowercase SHA-256 digests')
    return value


def _write_state(path, state):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.tmp')
    temporary.write_text(json.dumps(state, sort_keys=True, indent=2) + '\n')
    temporary.replace(path)


def initialize_state(site, state_path, expected_manifest, source_hash, dependency_hash):
    """Explicit first migration from a complete, verified prior release."""
    if state_path.exists():
        raise ValueError('Initialization is first-use only; existing state must be updated')
    if site_manifest(site) != _digest(expected_manifest):
        raise ValueError('Cannot initialize from a corrupt or unexpected prior release')
    _write_state(state_path, {
        'schema': SCHEMA, 'member': MEMBER, 'site_manifest': expected_manifest,
        'source_sha256': _digest(source_hash),
        'dependency_sha256': _digest(dependency_hash),
    })


def update_member(site, state_path, source, dependency_hash, renderer, assembler):
    """Reuse unchanged content; render exactly one member when its input changes."""
    state = json.loads(state_path.read_text())
    if (not isinstance(state, dict) or state.get('schema') != SCHEMA
            or state.get('member') != MEMBER):
        raise ValueError('Missing or incompatible incremental publication state')
    for field in ('site_manifest', 'source_sha256', 'dependency_sha256'):
        _digest(state.get(field))
    if state['dependency_sha256'] != _digest(dependency_hash):
        raise ValueError('Rendering dependencies changed; a separately scoped migration is required')
    if site_manifest(site) != state['site_manifest']:
        raise ValueError('Retained release does not match its reusable state')
    source_hash = sha256(source.read_bytes())
    if source_hash == state['source_sha256']:
        return {'rendered_members': 0, 'changed_files': [],
                'input_manifest': state['site_manifest'], 'output_manifest': state['site_manifest']}
    rendered = renderer(source)
    report = assembler(site, rendered, source, state['site_manifest'])
    if report['output_manifest'] != site_manifest(site):
        raise ValueError('Assembled output does not match its reported manifest')
    state.update(source_sha256=source_hash, site_manifest=report['output_manifest'])
    _write_state(state_path, state)
    return dict(report, rendered_members=1)


def dependencies(root):
    """Hash actual declared dependencies; release revisions are not inputs."""
    lock = root / 'ci/lab09-publish-requirements.txt'
    for line in lock.read_text().splitlines():
        name, expected = line.split('==')
        if importlib.metadata.version(name) != expected:
            raise ValueError(f'Installed rendering dependency differs from the lock: {name}')
    result = hashlib.sha256(CONFIG.encode())
    for name in ('ci/lab09-publish-requirements.txt', 'ci/publish_lab09.py',
                 'ci/patch_lab09_release.py', 'ci/relocate_labs.py'):
        result.update(name.encode() + b'\0' + (root / name).read_bytes())
    return result.hexdigest()


def verify_source_scope(root, base_commit):
    if subprocess.run(['git', 'merge-base', '--is-ancestor', base_commit, 'HEAD'],
                      cwd=root, check=False).returncode:
        raise ValueError('The retained release must be an ancestor of the current sources')
    changed = set(subprocess.check_output(
        ['git', 'diff', '--name-only', base_commit, 'HEAD'], cwd=root, text=True).splitlines())
    unexpected = changed - PUBLICATION_FILES
    if unexpected:
        raise ValueError('Course sources changed outside Lab 09: ' + ', '.join(sorted(unexpected)))


def render_one(source, work):
    member = work / 'member'
    member.mkdir()
    shutil.copyfile(source, member / 'lab09.ipynb')
    config = work / 'config.yml'
    config.write_text(CONFIG)
    kernel = work / 'jupyter/kernels/python3'
    kernel.mkdir(parents=True)
    (kernel / 'kernel.json').write_text(json.dumps({
        'argv': [sys.executable, '-m', 'ipykernel_launcher', '-f', '{connection_file}'],
        'display_name': 'Lab 09 publication', 'language': 'python',
    }))
    env = dict(os.environ, OPENBLAS_NUM_THREADS='1', OMP_NUM_THREADS='1',
               JUPYTER_PATH=str(work / 'jupyter'),
               JUPYTER_DATA_DIR=str(work / 'jupyter'),
               JUPYTER_RUNTIME_DIR=str(work / 'runtime'),
               IPYTHONDIR=str(work / 'ipython'), MPLCONFIGDIR=str(work / 'matplotlib'))
    subprocess.run([
        str(Path(sys.executable).with_name('jupyter-book')), 'build',
        str(member / 'lab09.ipynb'), '--config', str(config),
        '--path-output', str(work / 'rendered'), '-W',
    ], env=env, check=True)
    return work / 'rendered/_build/_page/lab09/html'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=['initialize', 'update'])
    parser.add_argument('--site', type=Path, required=True)
    parser.add_argument('--state', type=Path, required=True)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--base-commit', required=True)
    parser.add_argument('--report', type=Path)
    args = parser.parse_args()
    verify_source_scope(args.root, args.base_commit)
    dependency_hash = dependencies(args.root)
    if args.operation == 'initialize':
        if args.base_commit != BASE_COMMIT:
            raise ValueError('First-use migration requires the pinned successful release')
        baseline = subprocess.check_output(['git', 'show', BASE_COMMIT + ':' + MEMBER], cwd=args.root)
        initialize_state(args.site, args.state, BASE_MANIFEST, sha256(baseline), dependency_hash)
        print('Initialized reusable Lab 09 state from the pinned existing release')
        return
    from patch_lab09_release import patch_release
    with tempfile.TemporaryDirectory(prefix='phys142-lab09-member-') as temporary:
        report = update_member(args.site, args.state, args.root / MEMBER, dependency_hash,
                               lambda source: render_one(source, Path(temporary)), patch_release)
    if args.report:
        args.report.write_text(json.dumps(report, sort_keys=True, indent=2) + '\n')
    print(json.dumps(report, sort_keys=True))


if __name__ == '__main__':
    main()
