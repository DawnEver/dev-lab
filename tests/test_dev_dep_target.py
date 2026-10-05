"""The target environment, not the interpreter running the door, owns exclusion."""

import json
import os
import shutil
import subprocess
import sys
import time
import venv
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

from lab_commons.dev import _dep_project, dep
from lab_commons.dev.boxlock import BoxLock
from lab_commons.resources import Exhausted


@contextmanager
def _live_verdict(tmp_path, monkeypatch, *, python: str = sys.executable) -> Iterator[dict[str, str]]:
    monkeypatch.setenv('LAB_COMMONS_RESOURCE_DIR', str(tmp_path / 'resources'))
    environment = dict(os.environ, PYTHONPATH=os.pathsep.join(sys.path))
    ready = tmp_path / 'ready.json'
    ready.unlink(missing_ok=True)
    code = (
        'import json,pathlib,sys\n'
        'from lab_commons.dev.boxlock import BoxLock\n'
        'with BoxLock("gate:environment-A").held():\n'
        ' pending=pathlib.Path(sys.argv[1]).with_suffix(".tmp")\n'
        ' pending.write_text(\n'
        '  json.dumps({"prefix":sys.prefix,"python":sys.executable}),encoding="utf-8")\n'
        ' pending.replace(sys.argv[1])\n'
        ' sys.stdin.readline()\n'
    )
    process = subprocess.Popen(
        [python, '-c', code, str(ready)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding='utf-8',
        env=environment,
    )
    try:
        deadline = time.monotonic() + 20
        while not ready.exists() and process.poll() is None and time.monotonic() < deadline:
            time.sleep(0.02)
        if not ready.exists():
            msg = 'verdict child failed or did not announce readiness within 20 seconds'
            raise AssertionError(msg)
        metadata = json.loads(ready.read_text(encoding='utf-8'))
        yield metadata
    finally:
        process.communicate('\n', timeout=20)
        assert process.returncode == 0


def _port() -> dep.Port:
    return dep.Port(name='target-control', holders=tuple, anchor_paths=tuple, key=lambda: 'unchanged')


def test_a_real_verdict_refuses_mutation_of_its_environment_before_the_child_runs(tmp_path, monkeypatch) -> None:
    calls = []
    with _live_verdict(tmp_path, monkeypatch) as active, pytest.raises(dep.HeldEnvironmentError, match='environment-A'):
        dep.mutate(('example',), port=_port(), python=active['python'], run=lambda *a, **_k: calls.append(a))
    assert calls == []


def test_a_real_verdict_in_A_does_not_refuse_another_interpreters_environment_B(tmp_path, monkeypatch) -> None:
    target = tmp_path / 'B'
    venv.EnvBuilder().create(target)
    python = target / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
    prefix = subprocess.check_output(
        [str(python), '-c', 'import sys;print(sys.prefix)'], text=True, encoding='utf-8'
    ).strip()
    calls = []

    def run(argv, **_kwargs: object) -> SimpleNamespace:
        calls.append(tuple(argv))
        return SimpleNamespace(returncode=0)

    with _live_verdict(tmp_path, monkeypatch) as active:
        assert Path(prefix).resolve() != Path(active['prefix']).resolve()
        result = dep.mutate(('example',), port=_port(), python=str(python), run=run)
    assert Path(result.prefix).resolve() == Path(prefix).resolve()
    assert len(calls) == 1
    assert str(python) in calls[0]


def test_bootstrap_defaults_to_the_declared_full_extra_set_and_named_worktree(tmp_path, monkeypatch) -> None:
    root = tmp_path / 'lane'
    root.mkdir()
    (root / 'pyproject.toml').write_text(
        '[project]\nname="example"\nversion="0"\n'
        '[project.optional-dependencies]\ndev=[]\nimg-to-cad=[]\ntooldrivers=[]\n'
        '[tool.lab_commons.dep]\nextras=["dev","img-to-cad","tooldrivers"]\n',
        encoding='utf-8',
    )
    calls = []

    def run(argv, **kwargs: object) -> SimpleNamespace:
        calls.append((tuple(argv), kwargs))
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(dep, 'current_env_key', lambda: 'stable')
    assert dep.main(['--bootstrap', str(root)], run=run, cwd=tmp_path) == 0
    sync = next(argv for argv, _ in calls if 'sync' in argv)
    assert [sync[i + 1] for i, value in enumerate(sync) if value == '--extra'] == ['dev', 'img-to-cad', 'tooldrivers']
    assert sync[sync.index('--project') + 1] == str(root)
    options = next(options for argv, options in calls if 'sync' in argv)
    assert options['env']['UV_PROJECT_ENVIRONMENT'] == str(root / '.venv')
    assert 'VIRTUAL_ENV' not in options['env']
    assert not any('venv' in argv for argv, _ in calls), 'uv sync owns creation; do not overwrite a venv'


def test_mutation_holds_the_same_environment_seat_until_the_child_finishes(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv('LAB_COMMONS_RESOURCE_DIR', str(tmp_path / 'resources'))

    def run(_argv, **_kwargs: object) -> SimpleNamespace:
        with pytest.raises(Exhausted), BoxLock('gate:starts-during-mutation').held():
            pytest.fail('a verdict entered an environment while its mutation was running')
        return SimpleNamespace(returncode=0)

    assert dep.mutate(('example',), port=_port(), run=run).returncode == 0
    with BoxLock('gate:after-mutation').held():
        pass


def test_real_bootstrap_B_runs_while_A_has_a_verdict_then_B_refuses_its_own_sync(tmp_path, monkeypatch, capsys) -> None:
    root = tmp_path / 'B'
    root.mkdir()
    (root / 'pyproject.toml').write_text(
        '[project]\nname="empty-local-control"\nversion="0"\nrequires-python=">=3.12"\n[tool.uv]\npackage=false\n',
        encoding='utf-8',
    )
    monkeypatch.setenv('UV_OFFLINE', 'true')
    with _live_verdict(tmp_path, monkeypatch):
        assert dep.main(['--bootstrap', str(root)], cwd=tmp_path) == 0
    python = root / ('.venv/Scripts/python.exe' if os.name == 'nt' else '.venv/bin/python')
    assert python.is_file()
    capsys.readouterr()
    with _live_verdict(tmp_path, monkeypatch, python=str(python)):
        assert dep.main(['--root', str(root), '--sync'], cwd=tmp_path) == 1
    refusal = capsys.readouterr().out
    assert 'REFUSED:' in refusal
    assert 'installed' not in refusal
    failed = subprocess.run(
        [str(python), '-I', '-m', 'lab_commons.dev.dep', '--sync'],
        check=False,
    )
    assert failed.returncode != 0


@pytest.mark.parametrize('anchor', ['../another-lane/verdict', 'C:/another-lane/verdict', '/another-lane/verdict'])
def test_sync_refuses_anchors_outside_its_project_before_mutating(tmp_path, anchor) -> None:
    (tmp_path / 'pyproject.toml').write_text(
        f'[project]\nname="empty"\nversion="0"\n[tool.lab_commons.dep]\nanchors=["{anchor}"]\n',
        encoding='utf-8',
    )
    with pytest.raises(ValueError, match='inside the target project'):
        dep.main(['--bootstrap', str(tmp_path)], cwd=tmp_path)


def test_sync_failure_is_nonzero_and_retires_only_changed_target_anchors(tmp_path, monkeypatch) -> None:
    (tmp_path / 'pyproject.toml').write_text(
        '[project]\nname="empty"\nversion="0"\n[tool.lab_commons.dep]\nanchors=["verdict"]\n',
        encoding='utf-8',
    )
    anchor = tmp_path / 'verdict'
    anchor.write_text('PASS', encoding='utf-8')
    readings = iter(('before', 'after'))
    monkeypatch.setattr(dep.Port, 'env_key', lambda _self, _python=None: next(readings))

    venv.EnvBuilder().create(tmp_path / '.venv')

    def run(_argv, **_kwargs: object) -> SimpleNamespace:
        return SimpleNamespace(returncode=17)

    assert dep.main(['--bootstrap', str(tmp_path)], run=run, cwd=tmp_path) == 17
    assert not anchor.exists()


def test_a_lane_cannot_target_main_but_main_can_bootstrap_the_lane(tmp_path) -> None:
    git = shutil.which('git')
    assert git is not None
    main = tmp_path / 'main'
    lane = main / '.claude/worktrees/lane'
    subprocess.run([git, 'init', str(main)], check=True, capture_output=True)
    subprocess.run(
        [
            git,
            '-C',
            str(main),
            '-c',
            'user.name=control',
            '-c',
            'user.email=control@example.invalid',
            'commit',
            '--allow-empty',
            '-m',
            'control',
        ],
        check=True,
        capture_output=True,
    )
    subprocess.run([git, '-C', str(main), 'worktree', 'add', '-b', 'lane', str(lane)], check=True, capture_output=True)
    with pytest.raises(ValueError, match='may not mutate main'):
        dep.main(['--bootstrap', str(lane / '../..' / '..')], cwd=lane)
    assert _dep_project.target_root(lane, main) == lane.resolve()


def test_an_unknown_extra_refuses_before_sync(tmp_path) -> None:
    (tmp_path / 'pyproject.toml').write_text('[project]\nname="empty"\nversion="0"\n', encoding='utf-8')
    with pytest.raises(ValueError, match='unknown dependency extras'):
        dep.main(['--bootstrap', str(tmp_path), '--extra', 'undeclared'], cwd=tmp_path)


def test_bootstrap_refuses_an_own_venv_alias_to_another_environment(tmp_path) -> None:
    owner = tmp_path / 'owner'
    lane = tmp_path / 'lane'
    owner.mkdir()
    lane.mkdir()
    venv.EnvBuilder().create(owner / '.venv')
    (lane / 'pyproject.toml').write_text('[project]\nname="lane"\nversion="0"\n', encoding='utf-8')
    alias = lane / '.venv'
    if os.name == 'nt':
        cmd = shutil.which('cmd')
        assert cmd is not None
        subprocess.run([cmd, '/c', 'mklink', '/J', str(alias), str(owner / '.venv')], check=True, capture_output=True)
    else:
        alias.symlink_to(owner / '.venv', target_is_directory=True)

    def run(_argv, **_kwargs: object) -> SimpleNamespace:
        return SimpleNamespace(returncode=0)

    with pytest.raises(ValueError, match='own environment'):
        dep.main(['--bootstrap', str(lane)], cwd=tmp_path, run=run)


def test_sync_defaults_to_cwd_full_extras_and_reresolves_floating_git(tmp_path) -> None:
    (tmp_path / 'pyproject.toml').write_text(
        '[project]\nname="empty"\nversion="0"\ndependencies=["peer @ git+https://example.invalid/peer.git"]\n'
        '[project.optional-dependencies]\ndev=[]\ngeometry=[]\n',
        encoding='utf-8',
    )
    calls = []

    def run(argv, **_kwargs: object) -> SimpleNamespace:
        calls.append(tuple(argv))
        return SimpleNamespace(returncode=0)

    assert dep.main(['--sync'], cwd=tmp_path, run=run) == 0
    command = calls[0]
    assert [command[i + 1] for i, flag in enumerate(command) if flag == '--extra'] == ['dev', 'geometry']
    assert command[command.index('--upgrade-package') + 1] == 'peer'


def test_an_upgrade_without_sync_only_resolves_the_named_package(tmp_path) -> None:
    (tmp_path / 'pyproject.toml').write_text('[project]\nname="empty"\nversion="0"\n', encoding='utf-8')
    calls = []

    def run(argv, **_kwargs: object) -> SimpleNamespace:
        calls.append(tuple(argv))
        return SimpleNamespace(returncode=0)

    assert dep.main(['--upgrade-package', 'peer'], cwd=tmp_path, run=run) == 0
    assert calls[0][1] == 'lock'
    assert calls[0][calls[0].index('--upgrade-package') + 1] == 'peer'


def test_explicit_interpreters_with_one_resolved_binary_still_have_distinct_prefixes(tmp_path, monkeypatch) -> None:
    target = tmp_path / 'B'
    if os.name == 'posix':
        venv.EnvBuilder(symlinks=True).create(target)
        python = target / 'bin/python'
        assert python.resolve() == Path(sys.executable).resolve()
    else:
        python = target / 'Scripts/python.exe'
        monkeypatch.setattr(Path, 'resolve', lambda _self: Path('C:/shared-base/python.exe'))
        monkeypatch.setattr(
            dep.subprocess, 'run', lambda *_a, **_k: SimpleNamespace(stdout=json.dumps([str(target), 'B-key']))
        )
    prefix, _ = dep._snapshot(str(python))
    assert prefix == str(target)


def test_a_lane_cannot_bootstrap_an_unrelated_repositories_main_environment(tmp_path) -> None:
    git = shutil.which('git')
    assert git is not None
    main = tmp_path / 'main-A'
    foreign = tmp_path / 'main-B'
    lane = main / '.claude/worktrees/lane'
    for root in (main, foreign):
        subprocess.run([git, 'init', str(root)], check=True, capture_output=True)
    subprocess.run(
        [
            git,
            '-C',
            str(main),
            '-c',
            'user.name=control',
            '-c',
            'user.email=control@example.invalid',
            'commit',
            '--allow-empty',
            '-m',
            'control',
        ],
        check=True,
        capture_output=True,
    )
    subprocess.run([git, '-C', str(main), 'worktree', 'add', '-b', 'lane', str(lane)], check=True, capture_output=True)
    (foreign / 'pyproject.toml').write_text('[project]\nname="empty"\nversion="0"\n', encoding='utf-8')

    def run(_argv, **_kwargs: object) -> SimpleNamespace:
        return SimpleNamespace(returncode=0)

    with pytest.raises(ValueError, match='main'):
        dep.main(['--bootstrap', str(foreign)], cwd=lane, run=run)
