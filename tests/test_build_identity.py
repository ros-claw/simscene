"""Package version must not substitute for its source revision and dirty state."""
import subprocess
import shutil

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
