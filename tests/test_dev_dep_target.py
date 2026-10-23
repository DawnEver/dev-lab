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
from lab_commons.box import Refused

from dev_lab.dev import _dep_project, dep
from dev_lab.dev.envseat import EnvironmentSeat


@contextmanager
def _live_verdict(tmp_path, monkeypatch, *, python: str = sys.executable) -> Iterator[dict[str, str]]:
    monkeypatch.setenv('LAB_COMMONS_RESOURCE_DIR', str(tmp_path / 'resources'))
    environment = dict(os.environ, PYTHONPATH=os.pathsep.join(sys.path))
    ready = tmp_path / 'ready.json'
    ready.unlink(missing_ok=True)
    code = (
        'import json,pathlib,sys\n'
        'from dev_lab.dev.envseat import EnvironmentSeat\n'
        'with EnvironmentSeat(sys.prefix, "gate:environment-A").held():\n'
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
    return dep.Port(name='target-control', anchor_paths=tuple, key=lambda: 'unchanged')


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
        return SimpleNamespace(returncode=0, stdout='', stderr='')

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
        return SimpleNamespace(returncode=0, stdout='', stderr='')

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
        with pytest.raises(Refused), EnvironmentSeat(sys.prefix, 'gate:starts-during-mutation').held():
            pytest.fail('a verdict entered an environment while its mutation was running')
        return SimpleNamespace(returncode=0, stdout='', stderr='')

    assert dep.mutate(('example',), port=_port(), run=run).returncode == 0
    with EnvironmentSeat(sys.prefix, 'gate:after-mutation').held():
        pass


def test_real_bootstrap_B_runs_while_A_has_a_verdict_then_B_refuses_its_own_sync(tmp_path, monkeypatch, capsys) -> None:
    root = tmp_path / 'B'
    root.mkdir()
    (root / 'pyproject.toml').write_text(
        '[project]\nname="empty-local-control"\nversion="0"\nrequires-python=">=3.12"\n[tool.uv]\npackage=false\n',
        encoding='utf-8',
    )
    (root / 'uv.lock').write_text(
        'version = 1\nrequires-python = ">=3.12"\n\n[[package]]\nname = "empty-local-control"\nversion = "0"\n'
        'source = { virtual = "." }\n',
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
        [str(python), '-I', '-m', 'dev_lab.dev.dep', '--sync'],
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
        return SimpleNamespace(returncode=17, stdout='', stderr='')

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
        return SimpleNamespace(returncode=0, stdout='', stderr='')

    with pytest.raises(ValueError, match='own environment'):
        dep.main(['--bootstrap', str(lane)], cwd=tmp_path, run=run)


def test_sync_defaults_to_cwd_full_extras_and_upgrades_each_git_requirement(tmp_path) -> None:
    (tmp_path / 'pyproject.toml').write_text(
        '[project]\nname="empty"\nversion="0"\ndependencies=["peer @ git+https://example.invalid/peer.git"]\n'
        '[project.optional-dependencies]\ndev=[]\ngeometry=[]\n',
        encoding='utf-8',
    )
    calls = []

    def run(argv, **_kwargs: object) -> SimpleNamespace:
        calls.append(tuple(argv))
        return SimpleNamespace(returncode=0, stdout='', stderr='')

    assert dep.main(['--sync'], cwd=tmp_path, run=run) == 0
    command = calls[0]
    assert [command[i + 1] for i, flag in enumerate(command) if flag == '--extra'] == ['dev', 'geometry']
    assert command[command.index('--upgrade-package') + 1] == 'peer'


def test_an_upgrade_without_sync_only_resolves_the_named_package(tmp_path) -> None:
    (tmp_path / 'pyproject.toml').write_text('[project]\nname="empty"\nversion="0"\n', encoding='utf-8')
    calls = []

    def run(argv, **_kwargs: object) -> SimpleNamespace:
        calls.append(tuple(argv))
        return SimpleNamespace(returncode=0, stdout='', stderr='')

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
        return SimpleNamespace(returncode=0, stdout='', stderr='')

    with pytest.raises(ValueError, match='main'):
        dep.main(['--bootstrap', str(foreign)], cwd=lane, run=run)


def test_a_bootstrap_builds_exactly_the_lock_and_a_sync_re_resolves(tmp_path) -> None:
    """PIN + FRESHNESS (2026-10-17): a bootstrap is THAT commit's environment -- `uv sync --frozen`, lock or not.

    PLANTED CONTROL: a `--sync` of the same project re-resolves its floating git requirement.
    """
    (tmp_path / 'pyproject.toml').write_text(
        '[project]\nname="empty"\nversion="0"\ndependencies=["peer @ git+https://example.invalid/peer.git"]\n',
        encoding='utf-8',
    )
    calls = []

    def run(argv, **_kwargs: object) -> SimpleNamespace:
        calls.append(tuple(argv))
        return SimpleNamespace(returncode=0, stdout='', stderr='')

    assert dep.main(['--root', str(tmp_path), '--sync'], cwd=tmp_path, run=run) == 0
    assert '--upgrade-package' in calls[-2]
    assert '--frozen' not in calls[-2]
    assert dep.main(['--bootstrap', str(tmp_path)], cwd=tmp_path, run=run) == 0
    assert '--frozen' in calls[-2]
    assert calls[-1][1:4] == ('-m', 'dev_lab.dev.automode', 'write'), 'a sync renders the local auto-mode prose last'
    assert '--upgrade-package' not in calls[-2]


def _recording() -> tuple[list[tuple[str, ...]], object]:
    calls: list[tuple[str, ...]] = []

    def run(argv, **_kwargs: object) -> SimpleNamespace:
        calls.append(tuple(argv))
        return SimpleNamespace(returncode=0, stdout='', stderr='')

    return calls, run


def test_lock_upgrade_rewrites_the_lock_at_the_newest_then_builds_exactly_it(tmp_path) -> None:
    """The door lockcheck's refusal names: `uv lock --upgrade`, then a FROZEN sync of the declared extras."""
    (tmp_path / 'pyproject.toml').write_text(
        '[project]\nname="empty"\nversion="0"\ndependencies=["peer @ git+https://example.invalid/peer.git"]\n'
        '[project.optional-dependencies]\ndev=[]\n',
        encoding='utf-8',
    )
    calls, run = _recording()
    assert dep.main(['--lock-upgrade', str(tmp_path)], cwd=tmp_path, run=run) == 0
    lock, sync, render = calls
    assert render[1:4] == ('-m', 'dev_lab.dev.automode', 'write')
    assert lock[1:3] == ('lock', '--upgrade')
    assert str(tmp_path) in lock
    assert sync[1] == 'sync'
    assert '--frozen' in sync
    assert '--upgrade-package' not in sync
    assert sync[sync.index('--extra') + 1] == 'dev'


def test_lock_upgrade_refuses_an_unreasoned_hold_before_resolving_anything(tmp_path, capsys) -> None:
    """PLANTED CONTROL: the same hold lockcheck refuses at push is refused here, and nothing runs."""
    (tmp_path / 'pyproject.toml').write_text(
        '[project]\nname="empty"\nversion="0"\ndependencies=["peer==1"]\n', encoding='utf-8'
    )
    calls, run = _recording()
    assert dep.main(['--lock-upgrade', str(tmp_path)], cwd=tmp_path, run=run) == 1
    assert calls == []
    assert '"peer==1"' in capsys.readouterr().out
    (tmp_path / 'pyproject.toml').write_text(
        '[project]\nname="empty"\nversion="0"\ndependencies=["peer==1"]  # held: peer 2 drops Windows\n',
        encoding='utf-8',
    )
    assert dep.main(['--lock-upgrade', str(tmp_path)], cwd=tmp_path, run=run) == 0, 'a reasoned hold is admitted'


def test_a_failed_lock_upgrade_syncs_nothing(tmp_path) -> None:
    (tmp_path / 'pyproject.toml').write_text('[project]\nname="empty"\nversion="0"\n', encoding='utf-8')
    calls: list[tuple[str, ...]] = []

    def run(argv, **_kwargs: object) -> SimpleNamespace:
        calls.append(tuple(argv))
        return SimpleNamespace(returncode=2, stdout='', stderr='')

    assert dep.main(['--lock-upgrade'], cwd=tmp_path, run=run) == 2
    assert {call[1] for call in calls} == {'lock'}, 'a failed lock (retried by netverb) must sync nothing'


def test_a_bootstrap_initialises_the_submodules_its_path_dependencies_point_into(tmp_path, monkeypatch) -> None:
    """A checkout cloned WITHOUT its submodules is synced only after they are initialised (plan C5).

    The sync's path dependency points into ``components/engine``; uv saw it as not existing until a
    manual ``git submodule update --init``. The fake sync records whether the engine is there when it runs.
    """
    git = shutil.which('git')
    assert git is not None
    monkeypatch.setenv('GIT_CONFIG_COUNT', '1')  # a local submodule url is a file:// transport
    monkeypatch.setenv('GIT_CONFIG_KEY_0', 'protocol.file.allow')
    monkeypatch.setenv('GIT_CONFIG_VALUE_0', 'always')
    who = ['-c', 'user.name=control', '-c', 'user.email=control@example.invalid']

    def git_in(where: Path, *argv: str) -> None:
        subprocess.run([git, '-C', str(where), *who, *argv], check=True, capture_output=True)

    engine, product, lane = tmp_path / 'engine', tmp_path / 'product', tmp_path / 'lane'
    for repo in (engine, product):
        subprocess.run([git, 'init', '-q', str(repo)], check=True, capture_output=True)
    (engine / 'pyproject.toml').write_text('[project]\nname="engine"\nversion="0"\n', encoding='utf-8')
    git_in(engine, 'add', '.')
    git_in(engine, 'commit', '-qm', 'engine')
    (product / 'pyproject.toml').write_text(
        '[project]\nname="product"\nversion="0"\ndependencies=["engine"]\n'
        '[tool.uv.sources]\nengine={path="components/engine"}\n',
        encoding='utf-8',
    )
    git_in(product, 'submodule', 'add', '-q', engine.as_uri(), 'components/engine')
    git_in(product, 'add', '.')
    git_in(product, 'commit', '-qm', 'product')
    subprocess.run([git, 'clone', '-q', str(product), str(lane)], check=True, capture_output=True)
    mounted = lane / 'components/engine/pyproject.toml'
    assert not mounted.exists(), 'PLANTED CONTROL: a plain clone leaves the submodule uninitialised'
    seen = []

    def run(argv, **_kwargs: object) -> SimpleNamespace:
        seen.append(('sync' in argv, mounted.exists()))
        return SimpleNamespace(returncode=0, stdout='', stderr='')

    monkeypatch.setattr(dep, 'current_env_key', lambda: 'stable')
    assert dep.main(['--bootstrap', str(lane)], run=run, cwd=lane) == 0
    assert (True, True) in seen, 'the sync ran with the engine mounted'
