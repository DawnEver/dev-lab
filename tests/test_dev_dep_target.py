"""The target environment, not the interpreter running the door, owns exclusion."""

import functools
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

from dev_lab.dev import _dep_project, dep, venvcurrent, venvpointer
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
        '[tool.dev_lab.dep]\nextras=["dev","img-to-cad","tooldrivers"]\n',
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
    assert options['env']['UV_PROJECT_ENVIRONMENT'] == str(venvpointer.current(root)), 'built beside, then published'
    assert venvpointer.current(root).parent == root / venvpointer.HOME
    assert 'VIRTUAL_ENV' not in options['env']
    assert not any('venv' in argv for argv, _ in calls), 'uv sync owns creation; do not overwrite a venv'


def test_mutation_holds_the_same_environment_seat_until_the_child_finishes(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv('LAB_COMMONS_RESOURCE_DIR', str(tmp_path / 'resources'))
    monkeypatch.setattr(dep, 'executing_from', lambda *_a, **_k: ())  # sibling suite workers share this venv

    def run(_argv, **_kwargs: object) -> SimpleNamespace:
        with pytest.raises(Refused), EnvironmentSeat(sys.prefix, 'gate:starts-during-mutation').held():
            pytest.fail('a verdict entered an environment while its mutation was running')
        return SimpleNamespace(returncode=0, stdout='', stderr='')

    assert dep.mutate(('example',), port=_port(), run=run).returncode == 0
    with EnvironmentSeat(sys.prefix, 'gate:after-mutation').held():
        pass


def test_real_bootstrap_B_runs_while_A_has_a_verdict_and_B_syncs_beside_its_own(tmp_path, monkeypatch, capsys) -> None:
    """dev-lab #632: a verdict running in B's environment no longer refuses B's sync -- it builds beside it."""
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
    first = venvpointer.current(root)
    python = first / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
    assert python.is_file()
    capsys.readouterr()
    with _live_verdict(tmp_path, monkeypatch, python=str(python)):
        assert dep.main(['--root', str(root), '--sync'], cwd=tmp_path) == 0
        assert first.is_dir(), 'PLANTED CONTROL: the environment the verdict runs from is kept'
    said = capsys.readouterr().out
    assert 'REFUSED:' not in said
    assert venvpointer.current(root) != first
    python = venvpointer.current(root) / python.relative_to(first)
    failed = subprocess.run(
        [str(python), '-I', '-m', 'dev_lab.dev.dep', '--sync'],
        check=False,
    )
    assert failed.returncode != 0


@pytest.mark.parametrize('anchor', ['../another-lane/verdict', 'C:/another-lane/verdict', '/another-lane/verdict'])
def test_sync_refuses_anchors_outside_its_project_before_mutating(tmp_path, anchor) -> None:
    (tmp_path / 'pyproject.toml').write_text(
        f'[project]\nname="empty"\nversion="0"\n[tool.dev_lab.anchors]\npaths=["{anchor}"]\n',
        encoding='utf-8',
    )
    with pytest.raises(ValueError, match='inside the target project'):
        dep.main(['--bootstrap', str(tmp_path)], cwd=tmp_path)


def test_sync_failure_is_nonzero_publishes_nothing_and_keeps_the_anchors(tmp_path, monkeypatch) -> None:
    """A failed build beside the live environment is dropped: the live one never moved, so no verdict is void."""
    (tmp_path / 'pyproject.toml').write_text(
        '[project]\nname="empty"\nversion="0"\n[tool.dev_lab.anchors]\npaths=["verdict"]\n',
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
    assert anchor.exists()
    assert venvpointer.current(tmp_path) == tmp_path / '.venv'
    built = [p.name for p in (tmp_path / venvpointer.HOME).iterdir() if p.name != venvcurrent.BUILD_LOCK]
    assert not built, 'only the worktree build lock stays'


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


def _primary(git: str, checkout: Path) -> Path:
    subprocess.run([git, 'init', str(checkout)], check=True, capture_output=True)
    return checkout.resolve()


def test_one_primary_checkout_bootstrapping_another_is_told_to_run_from_that_checkout(tmp_path) -> None:
    """Another repo's primary checkout is refused with ITS cause: bootstrap it from inside that checkout.

    MEASURED 2026-11-25: a session in one repo bootstrapping a sibling repo's primary checkout was told "a worktree
    may not mutate main" -- neither side was a worktree.
    """
    git = shutil.which('git')
    assert git is not None
    session, sibling = _primary(git, tmp_path / 'session'), _primary(git, tmp_path / 'sibling')
    with pytest.raises(ValueError, match='only from that checkout') as refused:
        _dep_project.target_root(sibling, session)
    said = str(refused.value)
    assert 'may not mutate main' not in said, said
    assert f'cd {sibling} && {sys.executable} -m dev_lab.dev.dep --bootstrap {sibling}' in said, said


def test_a_worktree_targeting_its_own_main_keeps_the_worktree_cause(tmp_path) -> None:
    """PLANTED CONTROL: the same refusal from a linked worktree onto its main still names the worktree."""
    git = shutil.which('git')
    assert git is not None
    main = _primary(git, tmp_path / 'main')
    subprocess.run(
        [
            git,
            '-C',
            str(main),
            '-c',
            'user.name=c',
            '-c',
            'user.email=c@x.invalid',
            'commit',
            '--allow-empty',
            '-m',
            'c',
        ],
        check=True,
        capture_output=True,
    )
    lane = main / 'lane'
    subprocess.run([git, '-C', str(main), 'worktree', 'add', '-b', 'lane', str(lane)], check=True, capture_output=True)
    with pytest.raises(ValueError, match='a worktree may not mutate main') as refused:
        _dep_project.target_root(main, lane)
    assert 'only from that checkout' not in str(refused.value)


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


def test_sync_defaults_to_no_extras_and_upgrades_each_git_requirement(tmp_path) -> None:
    """D78: with nothing declared and no --extra, no extra is installed -- never every available one."""
    (tmp_path / 'pyproject.toml').write_text(
        '[project]\nname="empty"\nversion="0"\ndependencies=["peer @ git+https://example.invalid/peer.git"]\n'
        '[tool.dev_lab.dep]\nextras=[]\n[project.optional-dependencies]\ndev=[]\ngeometry=[]\n',
        encoding='utf-8',
    )
    calls = []

    def run(argv, **_kwargs: object) -> SimpleNamespace:
        calls.append(tuple(argv))
        return SimpleNamespace(returncode=0, stdout='', stderr='')

    assert dep.main(['--sync'], cwd=tmp_path, run=run) == 0
    command = calls[0]
    assert '--extra' not in command
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
            subprocess, 'run', lambda *_a, **_k: SimpleNamespace(stdout=json.dumps([str(target), 'B-key']))
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
        '[tool.dev_lab.dep]\nextras=[]\n[project.optional-dependencies]\ndev=[]\n',
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
    assert '--extra' not in sync, 'D78: nothing declared installs no extra'


def test_lock_upgrade_refuses_an_unreasoned_hold_before_resolving_anything(tmp_path, capsys) -> None:
    """PLANTED CONTROL: the same hold the forge refuses (famtests.lockpin) is refused here, and nothing runs."""
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


def test_a_bootstrap_initializes_the_submodules_its_path_dependencies_point_into(tmp_path, monkeypatch) -> None:
    """A checkout cloned WITHOUT its submodules is synced only after they are initialized (plan C5).

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
    assert not mounted.exists(), 'PLANTED CONTROL: a plain clone leaves the submodule uninitialized'
    seen = []

    def run(argv, **_kwargs: object) -> SimpleNamespace:
        seen.append(('sync' in argv, mounted.exists()))
        return SimpleNamespace(returncode=0, stdout='', stderr='')

    monkeypatch.setattr(dep, 'current_env_key', lambda: 'stable')
    assert dep.main(['--bootstrap', str(lane)], run=run, cwd=lane) == 0
    assert (True, True) in seen, 'the sync ran with the engine mounted'


def test_lock_upgrade_moves_a_pinned_rust_toolchain_to_the_newest_stable(tmp_path) -> None:
    """User ruling 2026-10-25: the door that refreshes the lock refreshes ``rust-toolchain.toml`` with it.

    PLANTED control: a failed resolution moves neither.
    """
    (tmp_path / 'pyproject.toml').write_text('[project]\nname="empty"\nversion="0"\n', encoding='utf-8')
    pin = tmp_path / 'rust-toolchain.toml'
    pin.write_text('[toolchain]\nchannel = "1.99.0"\n', encoding='utf-8')
    _, run = _recording()

    def failing(_argv, **_kwargs: object) -> SimpleNamespace:
        return SimpleNamespace(returncode=1, stdout='', stderr='')

    upgrade = functools.partial(_dep_project.lock_upgrade, tmp_path, 'py', dry_run=False, environment={})
    assert upgrade(run=failing, stable=lambda: '1.99.1') != 0
    assert pin.read_text(encoding='utf-8') == '[toolchain]\nchannel = "1.99.0"\n'
    assert upgrade(run=run, stable=lambda: '1.99.1') == 0
    assert pin.read_text(encoding='utf-8') == '[toolchain]\nchannel = "1.99.1"\n'


def test_a_lock_upgrade_naming_packages_moves_only_them(tmp_path) -> None:
    """The relock's in-house scope (user ruling 2026-11-05): ``--upgrade-package`` replaces ``--upgrade``.

    PLANTED control: the same door naming no package upgrades everything (the case above).
    """
    (tmp_path / 'pyproject.toml').write_text(
        '[project]\nname="empty"\nversion="0"\ndependencies=["peer @ git+https://example.invalid/peer.git"]\n',
        encoding='utf-8',
    )
    calls, run = _recording()
    assert dep.main(['--lock-upgrade', str(tmp_path), '--upgrade-package=peer'], cwd=tmp_path, run=run) == 0
    lock, sync, _ = calls
    assert lock[1:4] == ('lock', '--upgrade-package', 'peer')
    assert '--upgrade' not in lock
    assert '--frozen' in sync


def test_a_lock_upgrade_naming_packages_holds_the_toolchain_where_it_is(tmp_path) -> None:
    """The toolchain is third-party: an in-house relock never moves it. PLANTED control: the full door does."""
    (tmp_path / 'pyproject.toml').write_text('[project]\nname="empty"\nversion="0"\n', encoding='utf-8')
    pin = tmp_path / 'rust-toolchain.toml'
    pin.write_text('[toolchain]\nchannel = "1.99.0"\n', encoding='utf-8')
    _, run = _recording()
    upgrade = functools.partial(_dep_project.lock_upgrade, tmp_path, 'py', dry_run=False, environment={}, run=run)
    assert upgrade(stable=lambda: '1.99.1', packages=('peer',)) == 0
    assert pin.read_text(encoding='utf-8') == '[toolchain]\nchannel = "1.99.0"\n'
    assert upgrade(stable=lambda: '1.99.1') == 0
    assert pin.read_text(encoding='utf-8') == '[toolchain]\nchannel = "1.99.1"\n'


def test_every_sync_compiles_bytecode_so_the_first_hook_after_a_relock_is_warm(tmp_path) -> None:
    """D24 (2026-11-17): a hook's cold first run after a relock was 1.3-2.8 s, mostly compiling the import chain.

    A bootstrap and a sync write the bytecode at install time (`--compile-bytecode`), so no hook pays it.
    PLANTED CONTROL: a bare `uv lock` installs nothing and carries no such flag.
    """
    (tmp_path / 'pyproject.toml').write_text('[project]\nname="empty"\nversion="0"\n', encoding='utf-8')
    calls, run = _recording()
    assert dep.main(['--bootstrap', str(tmp_path)], cwd=tmp_path, run=run) == 0
    syncs = [call for call in calls if call[1] == 'sync']
    assert syncs
    assert all('--compile-bytecode' in call for call in syncs)
    assert dep.main(['--root', str(tmp_path), '--sync'], cwd=tmp_path, run=run) == 0
    syncs = [call for call in calls if call[1] == 'sync']
    assert len(syncs) >= 2
    assert all('--compile-bytecode' in call for call in syncs)
    lock = _dep_project.uv_command(tmp_path, 'py', (), syncing=False, upgrade_packages=())
    assert lock[1] == 'lock'
    assert '--compile-bytecode' not in lock


def test_an_explicit_extra_still_selects_it(tmp_path) -> None:
    """PLANTED CONTROL for the no-extras default: an explicit --extra (e.g. all) is honored."""
    (tmp_path / 'pyproject.toml').write_text(
        '[project]\nname="empty"\nversion="0"\n[tool.dev_lab.dep]\nextras=[]\n[project.optional-dependencies]\ndev=[]\nall=[]\n',
        encoding='utf-8',
    )
    calls = []

    def run(argv, **_kwargs: object) -> SimpleNamespace:
        calls.append(tuple(argv))
        return SimpleNamespace(returncode=0, stdout='', stderr='')

    assert dep.main(['--sync', '--extra', 'all'], cwd=tmp_path, run=run) == 0
    command = calls[0]
    assert [command[i + 1] for i, flag in enumerate(command) if flag == '--extra'] == ['all']
