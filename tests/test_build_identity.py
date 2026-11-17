"""Package version must not substitute for its source revision and dirty state."""
import subprocess
import shutil
from pathlib import Path
import hashlib
import json

import pytest

from plugins import build


def test_build_identity_reports_commit_and_uncommitted_changes(tmp_path):
    subprocess.run(['git', 'init', '-q', str(tmp_path)], check=True)
    (tmp_path / 'tracked.txt').write_text('one\n')
    subprocess.run(['git', '-C', str(tmp_path), 'add', 'tracked.txt'], check=True)
    subprocess.run(['git', '-C', str(tmp_path), '-c', 'user.name=Test',
                    '-c', 'user.email=test@example.invalid', 'commit', '-qm', 'baseline'], check=True)
    assert hasattr(build, 'source_identity'), 'build source identity is missing'
    clean = build.source_identity(tmp_path)
    commit = subprocess.check_output(['git', '-C', str(tmp_path), 'rev-parse', 'HEAD'], text=True).strip()
    assert clean == {'source_commit': commit, 'source_clean': True}
    (tmp_path / 'tracked.txt').write_text('two\n')
    assert build.source_identity(tmp_path) == {'source_commit': commit, 'source_clean': False}


def test_build_identity_does_not_inherit_an_enclosing_repository(tmp_path):
    assert hasattr(build, 'source_identity'), 'build source identity is missing'
    assert build.source_identity(tmp_path) == {'source_commit': None, 'source_clean': None}


def test_clean_build_snapshot_must_equal_the_committed_source_tree(tmp_path):
    repo, snapshot = tmp_path / 'repo', tmp_path / 'snapshot'
    repo.mkdir(); snapshot.mkdir()
    subprocess.run(['git', 'init', '-q', str(repo)], check=True)
    (repo / 'src/simscene').mkdir(parents=True)
    (repo / 'src/simscene/__init__.py').write_text('value = 1\n')
    for name in ('pyproject.toml', 'README.md', 'LICENSE'):
        (repo / name).write_text(name + '\n')
    subprocess.run(['git', '-C', str(repo), 'add', 'src', 'pyproject.toml', 'README.md', 'LICENSE'], check=True)
    subprocess.run(['git', '-C', str(repo), '-c', 'user.name=Test',
                    '-c', 'user.email=test@example.invalid', 'commit', '-qm', 'baseline'], check=True)
    commit = subprocess.check_output(['git', '-C', str(repo), 'rev-parse', 'HEAD'], text=True).strip()
    shutil.copytree(repo / 'src', snapshot / 'src')
    for name in ('pyproject.toml', 'README.md', 'LICENSE'):
        shutil.copyfile(repo / name, snapshot / name)
    assert hasattr(build, 'verify_source_snapshot'), 'clean-source snapshot verification is missing'
    build.verify_source_snapshot(repo, snapshot, commit)
    (snapshot / 'src/simscene/ignored.py').write_text('extra\n')
    with pytest.raises(RuntimeError, match='snapshot'):
        build.verify_source_snapshot(repo, snapshot, commit)


def test_packaged_resources_are_from_the_frozen_commit_even_if_checkout_changes(tmp_path, monkeypatch):
    original = build.ROOT
    repo = tmp_path / 'repo'; repo.mkdir()
    for name in ('pyproject.toml', 'README.md', 'LICENSE', 'NOTICE', 'OPEN_SOURCE_NOTICES.md'):
        shutil.copyfile(original / name, repo / name)
    for directory in ('src', 'skills'):
        shutil.copytree(original / directory, repo / directory,
                        ignore=shutil.ignore_patterns('__pycache__', '*.pyc', '*.egg-info', '.simscene-plugin-root'))
    for name in ('plugins/install.py', 'plugins/deepseek_patch.py',
                 *(f'examples/{example}/{name}' for example, names in build.EXAMPLE_DATA.items() for name in names),
                 *(f'experiments/{name}' for name in build.EXAMPLE_HELPERS)):
        target = repo / name; target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(original / name, target)
    subprocess.run(['git', 'init', '-q', str(repo)], check=True)
    subprocess.run(['git', '-C', str(repo), 'add', '.'], check=True)
    subprocess.run(['git', '-C', str(repo), '-c', 'user.name=Test', '-c',
                    'user.email=test@example.invalid', 'commit', '-qm', 'baseline'], check=True)
    changed = ('skills/build-scene/SKILL.md', 'examples/integration_workspace/recipe.json',
               'experiments/assemble_integration_receipt.py', 'plugins/install.py', 'NOTICE')
    expected = {name: (repo / name).read_bytes() for name in changed}
    run = subprocess.run
    def change_during_wheel(command, *args, **kwargs):
        if isinstance(command, list) and len(command) > 3 and command[1:4] == ['-m', 'pip', 'wheel']:
            for name in changed:
                with (repo / name).open('ab') as stream: stream.write(b'\nchanged during wheel build\n')
        return run(command, *args, **kwargs)
    monkeypatch.setattr(build, 'ROOT', repo)
    monkeypatch.setattr(build.subprocess, 'run', change_during_wheel)
    result = build.build(tmp_path / 'dist', use_installed_deps=True)
    package = Path(result['portable'])
    manifest_path = package/'server/resource-manifest.json'
    manifest = json.loads(manifest_path.read_text())
    info = json.loads((package/'server/build-info.json').read_text())
    assert info['resource_manifest_sha256'] == hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    assert manifest['files']['skills/build-scene/SKILL.md'] == hashlib.sha256(expected['skills/build-scene/SKILL.md']).hexdigest()
    for name, content in expected.items():
        relative = 'install.py' if name == 'plugins/install.py' else name
        assert (package / relative).read_bytes() == content, name
