"""``python -m lab_commons.dev.workstation`` against fake ``git``, ``dep --bootstrap``, venv python and ``schtasks``.

Each fake is a tiny Python program run through :data:`sys.executable`, logging its argv to ``calls.log``
and keeping its state in files under the test's temporary directory; the COM and PATH probes are
callables. No test touches this box's machine file, Scheduled Task or credential store.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tomllib
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Final

import pytest

from lab_commons.config import CONFIG_ENV
from lab_commons.dev import servetask, workstation
from lab_commons.dev.forgealarm import Alarm
from lab_commons.dev.servelock import held
from lab_commons.dev.venvpath import venv_interpreter

FORGE: Final = 'https://forge.example/team'
REPOS: Final = 'lab-commons,alpha,beta'
DEPLOY: Final = ('--repos', REPOS, '--capabilities', 'dev_checkout,node,jmag:4', '--forge', FORGE)
VENV: Final = str(venv_interpreter(os_name=os.name))

FAKE_GIT: Final = r"""
import os, pathlib, sys
log = pathlib.Path(sys.argv[1]); args = sys.argv[2:]
with log.open('a') as f: f.write('git ' + ' '.join(args) + '\n')
if args[:2] == ['-c', 'credential.interactive=never']:
    denied = [d for d in os.environ.get('FAKE_GIT_DENY', '').split(',') if d]
    sys.exit(128 if any(f'/{d}.git' in args[-2] for d in denied) else 0)
if args[0] == 'clone':
    git = pathlib.Path(args[-1], '.git'); git.mkdir(parents=True)
    for name, text in (('URL', args[-2]), ('HEAD_SHA', 'a' * 40), ('UP_SHA', 'a' * 40)): (git / name).write_text(text)
    sys.exit(0)
git, rest = pathlib.Path(args[1], '.git'), args[2:]
if rest[:2] == ['remote', 'get-url']: print((git / 'URL').read_text())
elif rest[0] == 'status': print(' M dirty' if (git / 'DIRTY').exists() else '')
elif rest[0] == 'rev-parse': print((git / ('HEAD_SHA' if rest[1] == 'HEAD' else 'UP_SHA')).read_text())
elif rest[0] == 'merge': (git / 'HEAD_SHA').write_text((git / 'UP_SHA').read_text())
"""

FAKE_BOOTSTRAP: Final = r"""
import pathlib, sys
with pathlib.Path(sys.argv[1]).open('a') as f: f.write('bootstrap ' + sys.argv[-1] + '\n')
python = pathlib.Path(sys.argv[-1], sys.argv[2]); python.parent.mkdir(parents=True, exist_ok=True); python.touch()
"""

FAKE_PYTHON: Final = r"""
import pathlib, sys
with pathlib.Path(sys.argv[1]).open('a') as f: f.write('python ' + ' '.join(sys.argv[3:]) + '\n')
hooked = pathlib.Path(sys.argv[2], '.git', 'HOOKED')
if '--install' in sys.argv: hooked.touch()
else: sys.exit(0 if hooked.exists() else 1)
"""

FAKE_SCHTASKS: Final = r"""
import pathlib, sys
state = pathlib.Path(sys.argv[1]); args = sys.argv[2:]
with (state.parent / 'calls.log').open('a') as f: f.write('schtasks ' + ' '.join(args) + '\n')
if args[0] == '/Query':
    if not state.exists(): sys.exit(1)
    sys.stdout.write(state.read_text())
elif args[0] == '/Create':
    state.write_text(pathlib.Path(args[args.index('/XML') + 1]).read_text(encoding='utf-16'))
"""

#: Every argv fragment that CHANGES something; a second run and a dry run log none of them.
CHANGES: Final = ('clone', 'merge', 'fetch', 'bootstrap', '--install', '/Create')


@dataclass(frozen=True)
class Box:
    """One fake workstation: its root of checkouts, machine file, Task state and the shared call log."""

    root: Path
    machine: Path
    task: Path
    log: Path
    programs: workstation.Programs

    def calls(self) -> list[str]:
        return self.log.read_text().splitlines() if self.log.exists() else []

    def deploy(self, *extra: str) -> int:
        return workstation.deploy([*DEPLOY, '--root', str(self.root), *extra], programs=self.programs)


@pytest.fixture
def box(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Box:
    fakes = tmp_path / 'fakes'
    fakes.mkdir()
    for name, text in (('git', FAKE_GIT), ('boot', FAKE_BOOTSTRAP), ('py', FAKE_PYTHON), ('sch', FAKE_SCHTASKS)):
        (fakes / f'{name}.py').write_text(text, encoding='utf-8')
    log, task = tmp_path / 'calls.log', tmp_path / 'task.xml'
    machine = tmp_path / 'config' / 'config.toml'
    monkeypatch.setenv(CONFIG_ENV, str(machine))
    monkeypatch.delenv('FAKE_GIT_DENY', raising=False)
    py = sys.executable
    programs = workstation.Programs(
        git=(py, str(fakes / 'git.py'), str(log)),
        schtasks=(py, str(fakes / 'sch.py'), str(task)),
        bootstrap=(py, str(fakes / 'boot.py'), str(log), VENV),
        python_of=lambda co: (py, str(fakes / 'py.py'), str(log), str(co)),
        which=lambda tool: f'/bin/{tool}',
        com=lambda _progid: Path('designer.exe'),
        windows=True,
        home=tmp_path / 'home',
    )
    return Box(tmp_path / 'src', machine, task, log, programs)


def _changes(calls: list[str]) -> list[str]:
    return [call for call in calls if any(word in call.split() for word in CHANGES)]


def test_a_fresh_box_is_cloned_bootstrapped_hooked_declared_and_scheduled(box: Box) -> None:
    assert box.deploy() == 0
    calls = box.calls()
    for name in ('lab-commons', 'alpha', 'beta'):
        assert f'git clone -q -b integrate/main {FORGE}/{name}.git {box.root / name}' in calls
        assert f'bootstrap {box.root / name}' in calls
        assert (box.root / name / '.git' / 'HOOKED').exists()
    declared = tomllib.loads(box.machine.read_text(encoding='utf-8'))
    assert declared['capabilities'] == {'dev_checkout': {}, 'node': {}, 'jmag': {'seats': 4}}
    assert declared['serve'] == {'repos': ['lab-commons', 'alpha', 'beta'], 'root': str(box.root)}
    assert 'reserve' not in declared, 'no delegate named, no [reserve] written'
    assert servetask.installed(box.task.read_text()) == servetask.definition_of(box.root / 'lab-commons')


def test_a_second_run_changes_nothing(box: Box) -> None:
    assert box.deploy() == 0
    before, seen = box.machine.read_bytes(), len(box.calls())
    assert box.deploy() == 0
    again = box.calls()[seen:]
    assert [c for c in _changes(again) if 'fetch' not in c] == [], 'a second run only fetches'
    assert box.machine.read_bytes() == before


def test_a_dry_run_reads_but_touches_nothing_and_prints_the_diff(box: Box, capsys: pytest.CaptureFixture[str]) -> None:
    assert box.deploy('--dry-run') == 0
    assert _changes(box.calls()) == []
    assert not box.root.exists()
    assert not box.machine.exists()
    assert not box.task.exists()
    out = capsys.readouterr().out
    assert '[dry-run] lab-commons: git clone' in out
    assert '+[serve]' in out
    assert '+[capabilities.jmag]' in out
    assert '[dry-run] schtasks /Create /TN lab-forge-serve' in out
    assert not box.programs.home.exists(), 'the task definition is not written either'


def test_unrelated_tables_and_comments_are_kept(box: Box) -> None:
    hand = '# this box\n[[hpc.grant]]\nuser = "me"  # mine\n\n[reserve]\ndelegates = ["bob"]  # ruled\n'
    box.machine.parent.mkdir(parents=True)
    box.machine.write_text(hand, encoding='utf-8')
    assert box.deploy('--delegates', 'bob') == 0
    text = box.machine.read_text(encoding='utf-8')
    assert text.startswith('# this box\n[[hpc.grant]]\nuser = "me"  # mine\n')
    assert 'delegates = ["bob"]  # ruled' in text, 'an equal value keeps its line'


def test_delegates_are_written_as_who_else_may_reserve_this_box(box: Box) -> None:
    assert box.deploy('--delegates', 'bob, carol,bob') == 0
    declared = tomllib.loads(box.machine.read_text(encoding='utf-8'))
    assert declared['reserve'] == {'delegates': ['bob', 'carol']}


def test_no_stored_credential_is_refused_with_the_manual_step(
    box: Box, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv('FAKE_GIT_DENY', 'beta')
    assert box.deploy() == 2
    assert _changes(box.calls()) == []
    err = capsys.readouterr().err
    assert 'no stored git credential reads beta' in err
    assert 'forge auth login' in err
    ls_remote = [c for c in box.calls() if 'ls-remote' in c]
    assert all(c.startswith('git -c credential.interactive=never ls-remote') for c in ls_remote)


def test_every_missing_tool_is_refused_at_once_each_with_its_remedy(
    box: Box, capsys: pytest.CaptureFixture[str]
) -> None:
    bare = replace(box.programs, which=lambda tool: None if tool in {'uv', 'node'} else tool, com=lambda _p: None)
    assert workstation.deploy([*DEPLOY, '--root', str(box.root)], programs=bare) == 2
    err = capsys.readouterr().err
    assert 'astral.sh/uv/install.ps1' in err
    assert 'OpenJS.NodeJS.LTS' in err
    assert 'designer.Application, scheduler.JobApplication not registered' in err
    assert '3 missing' in err
    assert box.calls() == []


def test_node_and_jmag_are_probed_only_when_declared(box: Box) -> None:
    bare = replace(box.programs, which=lambda tool: None if tool == 'node' else tool, com=lambda _p: None)
    argv = ['--repos', REPOS, '--capabilities', 'dev_checkout', '--forge', FORGE, '--root', str(box.root)]
    assert workstation.deploy(argv, programs=bare) == 0


def test_a_dirty_checkout_is_refused_and_a_behind_one_is_fast_forwarded(box: Box) -> None:
    assert box.deploy() == 0
    alpha = box.root / 'alpha' / '.git'
    (alpha / 'UP_SHA').write_text('b' * 40)
    seen = len(box.calls())
    assert box.deploy() == 0
    moved = box.calls()[seen:]
    assert f'git -C {box.root / "alpha"} merge --ff-only -q @{{u}}' in moved
    assert f'bootstrap {box.root / "alpha"}' in moved, 'a moved checkout re-syncs its venv'
    assert f'bootstrap {box.root / "beta"}' not in moved
    (alpha / 'DIRTY').touch()
    assert box.deploy() == 2


def test_a_refused_repo_is_skipped_alone_and_the_others_are_still_served(
    box: Box, capsys: pytest.CaptureFixture[str]
) -> None:
    """One repo's refusal never stops the others: it leaves [serve] repos, its owner is alarmed, the exit is 2."""
    raised: list[Alarm] = []
    programs = replace(box.programs, alarm=raised.append)
    argv = [*DEPLOY, '--root', str(box.root)]
    assert workstation.deploy(argv, programs=programs) == 0
    (box.root / 'beta' / '.git' / 'DIRTY').touch()
    (box.root / 'alpha' / '.git' / 'UP_SHA').write_text('b' * 40)
    capsys.readouterr()
    assert workstation.deploy(argv, programs=programs) == 2
    assert f'git -C {box.root / "alpha"} merge --ff-only -q @{{u}}' in box.calls(), 'the planted control moves on'
    declared = tomllib.loads(box.machine.read_text(encoding='utf-8'))
    assert declared['serve']['repos'] == ['lab-commons', 'alpha'], 'a refused repo is not served'
    assert servetask.installed(box.task.read_text()) == servetask.definition_of(box.root / 'lab-commons')
    assert 'beta' in capsys.readouterr().err
    assert [(one.repo, 'local changes' in one.body) for one in raised] == [(f'{FORGE}/beta.git', True)]


def test_a_missing_checkout_without_a_forge_is_refused(box: Box, capsys: pytest.CaptureFixture[str]) -> None:
    argv = ['--repos', REPOS, '--root', str(box.root)]
    assert workstation.deploy(argv, programs=box.programs) == 2
    assert 'pass --forge' in capsys.readouterr().err


def test_the_repos_must_include_lab_commons_the_task_runs_from() -> None:
    with pytest.raises(SystemExit):
        workstation.deploy(['--repos', 'alpha'])


def test_a_bad_capability_is_refused_by_name() -> None:
    with pytest.raises(SystemExit):
        workstation.deploy(['--repos', REPOS, '--capabilities', 'jmag:x'])


def test_an_older_task_action_is_replaced(box: Box) -> None:
    box.task.write_text('<Command>cmd</Command><Arguments>/c cd /d x &amp;&amp; py -m serve</Arguments>')
    assert box.deploy() == 0
    assert servetask.installed(box.task.read_text()) == servetask.definition_of(box.root / 'lab-commons')


def test_off_windows_the_deploy_is_refused(box: Box) -> None:
    assert workstation.deploy([*DEPLOY], programs=replace(box.programs, windows=False)) == 2


def _serving(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *ready: str) -> Path:
    root = tmp_path / 'src'
    for name in ready:
        python = root / name / VENV
        python.parent.mkdir(parents=True)
        python.touch()
    machine = tmp_path / 'config.toml'
    machine.write_text(f'[serve]\nrepos = ["lab-commons", "alpha", "beta"]\nroot = {str(root)!r}\n', encoding='utf-8')
    monkeypatch.setenv(CONFIG_ENV, str(machine))
    return root


class _Done:
    def __init__(self, returncode: int) -> None:
        self.returncode = returncode


def test_serve_runs_each_declared_repo_in_its_own_checkout_and_reports_the_worst(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _serving(tmp_path, monkeypatch, 'lab-commons', 'beta')
    ran: list[tuple[list[str], Path]] = []
    spawned: list[dict[str, object]] = []

    def run(argv: list[str], *, cwd: Path, **kw: object) -> _Done:
        ran.append((argv, cwd))
        spawned.append(kw)
        return _Done(1 if cwd.name == 'beta' else 0)

    assert workstation.serve(run=run, lock=tmp_path / 'serve.lock') == 2, 'alpha has no venv'
    assert [cwd.name for _, cwd in ran] == ['lab-commons', 'beta'], 'a missing venv never skips the next repo'
    argv, cwd = ran[0]
    assert all(kw[key] == value for kw in spawned for key, value in servetask.windowless().items())
    assert argv == [str(root / 'lab-commons' / VENV), '-m', 'lab_commons.dev.forge', 'serve']
    assert cwd == root / 'lab-commons'


def test_serve_does_nothing_while_another_serve_holds_the_lock(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _serving(tmp_path, monkeypatch, 'lab-commons', 'alpha', 'beta')
    lock, ran = tmp_path / 'serve.lock', []
    with held(lock) as mine:
        assert mine
        assert workstation.serve(run=lambda *a, **_k: ran.append(a), lock=lock) == 0
    assert ran == []


def test_serve_without_a_declaration_is_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(CONFIG_ENV, str(tmp_path / 'absent.toml'))
    assert workstation.serve(lock=tmp_path / 'serve.lock') == 2


def test_a_windowless_serve_writes_itself_and_its_children_to_the_capped_log(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sys, 'stdout', None)  # pythonw: no console, no streams
    monkeypatch.setattr(sys, 'stderr', None)
    monkeypatch.setattr(servetask, 'home', lambda: tmp_path)
    seen: dict[str, object] = {}

    def serve(*, out: object = None) -> int:
        seen.update(out=out)
        workstation.emit('[serve] reached the log')
        return 0

    monkeypatch.setattr(workstation, 'serve', serve)
    assert workstation.main(['serve']) == 0
    assert seen['out'] is not None, 'the children write to the same log'
    assert '[serve] reached the log' in (tmp_path / 'serve.log').read_text(encoding='utf-8')


REAL_DOOR: Final = r"""
import pathlib, sys
from lab_commons.dev._dep_project import target_root
target_root(pathlib.Path(sys.argv[-1]), pathlib.Path.cwd())
"""


def test_the_bootstrap_passes_the_real_door_from_an_unrelated_cwd(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``dep --bootstrap`` refuses to move a primary checkout from elsewhere, so the deploy runs it IN the checkout."""
    checkout, elsewhere = tmp_path / 'lab-commons', tmp_path / 'elsewhere'
    elsewhere.mkdir()
    subprocess.run([shutil.which('git') or 'git', 'init', '-q', str(checkout)], check=True)
    door = tmp_path / 'door.py'
    door.write_text(REAL_DOOR, encoding='utf-8')
    monkeypatch.chdir(elsewhere)
    programs = workstation.Programs(bootstrap=(sys.executable, str(door)))
    step = workstation.Step(workstation.Tools(git=('git',)), dry=False)
    assert workstation._venv(step, programs, checkout, checkout.name, moved=True) == 0
