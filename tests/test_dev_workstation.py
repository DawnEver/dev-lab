"""``python -m dev_lab.dev.workstation`` against fake ``git``, ``dep --bootstrap``, venv python and ``schtasks``.

Each fake is a tiny Python program run through :data:`sys.executable`, logging its argv to ``calls.log``
and keeping its state in files under the test's temporary directory; the COM and PATH probes are
callables. No test touches this box's machine file, Scheduled Task or credential store.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import threading
import tomllib
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Final

import pytest
from lab_commons.config import CONFIG_ENV

from dev_lab.dev import hostrefresh, servetask, workstation
from dev_lab.dev.forgealarm import Alarm
from dev_lab.dev.hpchost.spec import host_serve_argv
from dev_lab.dev.lockcheck import UV_VERSION
from dev_lab.dev.servelock import held
from dev_lab.dev.venvpath import venv_interpreter

FORGE: Final = 'https://forge.example/team'
REPOS: Final = 'dev-lab,alpha,beta'
DEPLOY: Final = ('--repos', REPOS, '--capabilities', 'workstation,jmag:4', '--forge', FORGE)
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
    _registry(tmp_path, machine, ['client', 'node', 'forge'])
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
        computer='BOX',
        release=lambda checkout: [f'released {checkout.name}'],
    )
    return Box(tmp_path / 'src', machine, task, log, programs)


def _registry(tmp_path: Path, machine: Path, roles: list[str] | None, *, computer: str = 'BOX') -> Path:
    """Plant a synced hosts.json (BOM-prefixed, as PowerShell writes it) and declare it in the machine file.

    *roles* ``None`` plants a registry with no entry for *computer*.
    """
    hosts = [{'name': 'WS9', 'computer': 'OTHER', 'roles': ['client', 'node']}]
    if roles is not None:
        hosts.append({'name': 'G', 'computer': computer, 'roles': roles})
    registry = tmp_path / 'sync' / 'hosts.json'
    registry.parent.mkdir(parents=True, exist_ok=True)
    registry.write_text(json.dumps({'hosts': hosts}), encoding='utf-8-sig')
    machine.parent.mkdir(parents=True, exist_ok=True)
    machine.write_text(f'[workstation]\nregistry = {json.dumps(str(registry))}\n', encoding='utf-8')
    return registry


def _changes(calls: list[str]) -> list[str]:
    return [call for call in calls if any(word in call.split() for word in CHANGES)]


def test_a_fresh_box_is_cloned_bootstrapped_hooked_declared_and_scheduled(box: Box) -> None:
    assert box.deploy() == 0
    calls = box.calls()
    for name in ('dev-lab', 'alpha', 'beta'):
        assert f'git clone -q -b integrate/main {FORGE}/{name}.git {box.root / name}' in calls
        assert f'bootstrap {box.root / name}' in calls
        assert (box.root / name / '.git' / 'HOOKED').exists()
    declared = tomllib.loads(box.machine.read_text(encoding='utf-8'))
    jmag = {'seats': 4, 'in_use': {'process': list(workstation.JMAG_SOLVER_IMAGES)}}
    assert declared['capabilities'] == {'workstation': {}, 'jmag': jmag}, 'a jmag seat is observed by its solvers'
    assert declared['serve'] == {'repos': ['dev-lab', 'alpha', 'beta'], 'root': str(box.root)}
    assert 'reserve' not in declared, 'deploy reserves nothing: the OS headroom keeps its defaults'
    assert servetask.installed(box.task.read_text()) == servetask.definition_of(box.root / 'dev-lab')


def test_a_second_run_changes_nothing(box: Box) -> None:
    assert box.deploy() == 0
    before, seen = box.machine.read_bytes(), len(box.calls())
    assert box.deploy() == 0
    again = box.calls()[seen:]
    assert [c for c in _changes(again) if 'fetch' not in c] == [], 'a second run only fetches'
    assert box.machine.read_bytes() == before


def test_a_dry_run_reads_but_touches_nothing_and_prints_the_diff(box: Box, capsys: pytest.CaptureFixture[str]) -> None:
    declared = box.machine.read_text(encoding='utf-8')
    assert box.deploy('--dry-run') == 0
    assert _changes(box.calls()) == []
    assert not box.root.exists()
    assert box.machine.read_text(encoding='utf-8') == declared
    assert not box.task.exists()
    out = capsys.readouterr().out
    assert '[dry-run] dev-lab: git clone' in out
    assert '+[serve]' in out
    assert '+[capabilities.jmag]' in out
    assert '[dry-run] schtasks /Create /TN lab-forge-serve' in out
    assert not box.programs.home.exists(), 'the task definition is not written either'


def test_unrelated_tables_and_comments_are_kept(box: Box) -> None:
    hand = '# this box\n[[hpc.grant]]\nuser = "me"  # mine\n\n[reserve]\ncpu_margin = 2  # ruled\n'
    hand = box.machine.read_text(encoding='utf-8') + hand
    box.machine.write_text(hand, encoding='utf-8')
    assert box.deploy() == 0
    text = box.machine.read_text(encoding='utf-8')
    assert text.startswith(hand.split('# this box')[0] + '# this box\n[[hpc.grant]]\nuser = "me"  # mine\n')
    assert 'cpu_margin = 2  # ruled' in text, 'an unrelated table keeps its line'


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
    bare = replace(
        box.programs, which=lambda tool: None if tool in {'uv', 'node', 'codex'} else tool, com=lambda _p: None
    )
    assert workstation.deploy([*DEPLOY, '--root', str(box.root)], programs=bare) == 2
    err = capsys.readouterr().err
    assert f'astral.sh/uv/{UV_VERSION}/install.ps1' in err
    assert 'OpenJS.NodeJS.LTS' in err
    assert '@openai/codex' in err
    assert 'designer.Application, scheduler.JobApplication not registered' in err
    assert '4 missing' in err
    assert box.calls() == []


def test_the_workstation_kit_and_jmag_are_probed_only_when_declared(box: Box) -> None:
    bare = replace(box.programs, which=lambda tool: None if tool in {'node', 'codex'} else tool, com=lambda _p: None)
    argv = ['--repos', REPOS, '--capabilities', 'femm', '--forge', FORGE, '--root', str(box.root)]
    assert workstation.deploy(argv, programs=bare) == 0


def test_a_dirty_checkout_is_refused_and_a_behind_one_is_fast_forwarded(box: Box) -> None:
    assert box.deploy() == 0
    alpha = box.root / 'alpha' / '.git'
    (alpha / 'UP_SHA').write_text('b' * 40)
    seen = len(box.calls())
    assert box.deploy() == 0
    moved = box.calls()[seen:]
    assert f'git -C {box.root / "alpha"} merge --ff-only -q @{{u}}' in moved
    assert f'bootstrap {box.root / "alpha"}' not in moved, 'a move that changes no env input syncs nothing'
    (box.root / 'alpha' / 'uv.lock').write_text('changed')
    seen = len(box.calls())
    assert box.deploy() == 0
    assert f'bootstrap {box.root / "alpha"}' in box.calls()[seen:], 'a changed lock re-syncs its venv'
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
    assert declared['serve']['repos'] == ['dev-lab', 'alpha'], 'a refused repo is not served'
    assert servetask.installed(box.task.read_text()) == servetask.definition_of(box.root / 'dev-lab')
    assert 'beta' in capsys.readouterr().err
    assert [(one.repo, 'local changes' in one.body) for one in raised] == [(f'{FORGE}/beta.git', True)]


def test_a_missing_checkout_without_a_forge_is_refused(box: Box, capsys: pytest.CaptureFixture[str]) -> None:
    argv = ['--repos', REPOS, '--root', str(box.root)]
    assert workstation.deploy(argv, programs=box.programs) == 2
    assert 'pass --forge' in capsys.readouterr().err


def test_a_jmag_solver_image_is_the_solver_and_never_its_launcher_or_service() -> None:
    images = set(workstation.JMAG_SOLVER_IMAGES)
    assert 'jam.exe' in images
    assert images.isdisjoint({'execsolver.exe', 'scheduler.exe', 'designer.exe'}), 'one solve counts once'


@pytest.mark.parametrize('flag', ['--seat-margin=jmag=2', '--cpu-margin=8', '--mem-margin=0.25'])
def test_deploy_reserves_nothing_for_people(flag: str) -> None:
    """A person DECLARES their use (``box claim``, ruling 2026-10-25): deploy writes no margin for them."""
    with pytest.raises(SystemExit):
        workstation.deploy(['--repos', REPOS, '--capabilities', 'jmag:4', flag])


def test_the_repos_must_include_lab_commons_the_task_runs_from() -> None:
    with pytest.raises(SystemExit):
        workstation.deploy(['--repos', 'alpha'])


def test_a_bad_capability_is_refused_by_name() -> None:
    with pytest.raises(SystemExit):
        workstation.deploy(['--repos', REPOS, '--capabilities', 'jmag:x'])


def test_an_older_task_action_is_replaced(box: Box) -> None:
    box.task.write_text('<Command>cmd</Command><Arguments>/c cd /d x &amp;&amp; py -m serve</Arguments>')
    assert box.deploy() == 0
    assert servetask.installed(box.task.read_text()) == servetask.definition_of(box.root / 'dev-lab')


def test_off_windows_the_deploy_is_refused(box: Box) -> None:
    assert workstation.deploy([*DEPLOY], programs=replace(box.programs, windows=False)) == 2


def _serving(box: Box) -> None:
    """A deployed box: every checkout cloned, its venv synced, and ``[serve]`` declared."""
    assert box.deploy() == 0


class _Done:
    def __init__(self, returncode: int) -> None:
        self.returncode = returncode


def _serve(box: Box, tmp_path: Path, rc: dict[str, int] | None = None) -> tuple[int, list[tuple[list[str], Path]]]:
    ran: list[tuple[list[str], Path]] = []

    def run(argv: list[str], *, cwd: Path, **_kw: object) -> _Done:
        ran.append((argv, cwd))
        return _Done((rc or {}).get(cwd.name, 0))

    return workstation.serve(run=run, lock=tmp_path / 'serve.lock', programs=box.programs), ran


def test_serve_runs_each_declared_repo_in_its_own_checkout_and_reports_the_worst(box: Box, tmp_path: Path) -> None:
    _serving(box)
    worst, ran = _serve(box, tmp_path, {'beta': 1})
    assert worst == 1
    assert sorted(cwd.name for _, cwd in ran) == ['alpha', 'beta', 'dev-lab'], 'each repo is served once'
    assert {tuple(argv) for argv, _ in ran} == {tuple(host_serve_argv())}, 'the HOST kit serves every repo'


def test_one_busy_repo_never_starves_the_others(box: Box, tmp_path: Path) -> None:
    """Incident 2026-10-25: one repo's long part held the host lock and every other repo's card went STALE.

    Each repo serves in a lane of its own: while alpha's serve still runs, beta and dev-lab serve again one
    period after their last serve ended. PLANTED CONTROL: once alpha ends nobody serves again -- the Task's
    next tick does.
    """
    _serving(box)
    release, ran, lock = threading.Event(), [], threading.Lock()

    def run(_argv: list[str], *, cwd: Path, **_kw: object) -> _Done:
        with lock:
            ran.append(cwd.name)
            if ran.count('beta') >= 2 and ran.count('dev-lab') >= 2:
                release.set()
        if cwd.name == 'alpha':
            assert release.wait(30), 'the other repos were never served again while alpha ran'
        return _Done(0)

    assert workstation.serve(run=run, lock=tmp_path / 'serve.lock', programs=box.programs, period_s=0.01) == 0
    assert ran.count('alpha') == 1
    assert ran.count('beta') >= 2
    assert ran.count('dev-lab') >= 2


def test_serve_refreshes_a_stale_venv_before_its_forge_runs(box: Box, tmp_path: Path) -> None:
    """THE PLANTED CONTROL (incident 2026-10-13): a venv whose old kit would exit 2 is synced FIRST, by the host."""
    _serving(box)
    alpha = box.root / 'alpha'
    (alpha / '.git' / 'UP_SHA').write_text('b' * 40)
    (alpha / 'pyproject.toml').write_text('[project]\nname = "alpha"  # pins a newer kit\n')
    seen = len(box.calls())
    served: dict[str, int] = {}  # repo -> how many calls had been logged when its forge started

    def run(_argv: list[str], *, cwd: Path, **_kw: object) -> _Done:
        served[cwd.name] = len(box.calls())
        stale = cwd == alpha and f'bootstrap {alpha}' not in box.calls()[seen:]
        return _Done(2 if stale else 0)  # the old kit's `forge serve` exits 2

    assert workstation.serve(run=run, lock=tmp_path / 'serve.lock', programs=box.programs) == 0
    calls = box.calls()
    moved = calls.index(f'git -C {alpha} merge --ff-only -q @{{u}}', seen)
    synced = calls.index(f'bootstrap {alpha}', seen)
    assert moved < synced < served['alpha'], 'moved, then synced, then served'
    assert f'bootstrap {box.root / "beta"}' not in calls[seen:], 'an unchanged venv is not synced'
    kit = calls.index(f'git -C {box.root / "dev-lab"} fetch -q', seen)
    assert kit < calls.index(f'git -C {alpha} fetch -q', seen), 'dev-lab is refreshed first'
    again = len(box.calls())
    assert _serve(box, tmp_path)[0] == 0
    assert not [c for c in box.calls()[again:] if c.startswith('bootstrap')], 'the stamp makes a second tick quiet'


def test_serve_reinstalls_the_serving_checkouts_own_hooks_after_it_updates_itself(box: Box, tmp_path: Path) -> None:
    """PLAN R1: a host's shims are kept current by the machine, never by hand (2026-10-22, #273).

    The serving dev-lab checkout moved to a kit whose shim differs from the installed one: the tick
    re-installs ITS hooks before serving. A repo checkout's hooks are not the serving kit's and are left alone.
    PLANTED CONTROL: hooks already live are only read, never re-written.
    """
    _serving(box)
    kit, alpha = box.root / 'dev-lab', box.root / 'alpha'
    (kit / '.git' / 'HOOKED').unlink()
    (alpha / '.git' / 'HOOKED').unlink()
    seen = len(box.calls())
    assert _serve(box, tmp_path)[0] == 0
    installs = [call for call in box.calls()[seen:] if '--install' in call.split()]
    assert installs == [f'python -m dev_lab.dev.hook_install --repo {kit} --install']
    again = len(box.calls())
    assert _serve(box, tmp_path)[0] == 0
    assert not [call for call in box.calls()[again:] if '--install' in call.split()], 'live hooks are only read'


def test_a_failed_sync_is_retried_by_the_next_tick(box: Box, tmp_path: Path) -> None:
    _serving(box)
    (box.root / 'alpha' / '.venv' / '.lab-host-env').unlink()
    failing = replace(box.programs, bootstrap=(sys.executable, '-c', 'raise SystemExit(3)'))
    assert workstation.serve(run=lambda *_a, **_k: _Done(0), lock=tmp_path / 'l', programs=failing) == 2
    seen = len(box.calls())
    assert _serve(box, tmp_path)[0] == 0
    assert f'bootstrap {box.root / "alpha"}' in box.calls()[seen:]


def test_a_repo_whose_refresh_fails_is_released_by_name_and_the_others_are_served(
    box: Box, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _serving(box)
    (box.root / 'alpha' / '.git' / 'DIRTY').touch()
    shutil.rmtree(box.root / 'beta')
    capsys.readouterr()
    worst, ran = _serve(box, tmp_path)
    assert worst == 2
    assert [cwd.name for _, cwd in ran] == ['dev-lab']
    err = capsys.readouterr().err
    assert 'alpha released, not served this tick' in err
    assert 'local changes' in err
    assert 'beta released, not served this tick: no checkout' in err


def test_serve_does_nothing_while_another_serve_holds_the_lock(box: Box, tmp_path: Path) -> None:
    _serving(box)
    lock, ran, seen = tmp_path / 'serve.lock', [], len(box.calls())
    with held(lock) as mine:
        assert mine
        assert workstation.serve(run=lambda *a, **_k: ran.append(a), lock=lock, programs=box.programs) == 0
    assert box.calls()[seen:] == [], 'nothing is refreshed either'
    assert ran == []


def test_serve_without_a_declaration_is_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(CONFIG_ENV, str(tmp_path / 'absent.toml'))
    assert workstation.serve(lock=tmp_path / 'serve.lock') == 2


@pytest.mark.parametrize(
    ('roles', 'named'),
    [(['client', 'node'], "['client', 'node']"), (None, "no entry for computer 'BOX'")],
    ids=['forge-role-absent', 'no-entry'],
)
def test_a_host_the_registry_gives_no_forge_role_claims_nothing_and_releases_its_journaled_runs(
    box: Box, tmp_path: Path, capsys: pytest.CaptureFixture[str], roles: list[str] | None, named: str
) -> None:
    _serving(box)
    serve = tomllib.loads(box.machine.read_text(encoding='utf-8'))['serve']
    _registry(tmp_path, box.machine, roles)
    box.machine.write_text(
        box.machine.read_text(encoding='utf-8') + f'\n[serve]\nrepos = {json.dumps(serve["repos"])}\n'
        f'root = {json.dumps(serve["root"])}\n',
        encoding='utf-8',
    )
    seen = len(box.calls())
    worst, ran = _serve(box, tmp_path)
    assert (worst, ran) == (0, []), 'no forge serve runs, so nothing is claimed'
    assert box.calls()[seen:] == [], 'nothing is refreshed either'
    out = capsys.readouterr().out
    assert '[serve] not a forge host (' in out
    assert named in out
    assert [line for line in out.splitlines() if 'released ' in line] == [
        f'[serve] {name} released {name}' for name in ('dev-lab', 'alpha', 'beta')
    ]


def test_the_registry_entry_is_matched_by_computer_before_name(box: Box, tmp_path: Path) -> None:
    _registry(tmp_path, box.machine, ['forge'], computer='box')
    assert workstation.forge_refusal('BOX') is None, 'COMPUTERNAME matches case-insensitively'
    assert workstation.forge_refusal('G') is None, 'the label matches when no computer does'
    assert 'roles of WS9' in (workstation.forge_refusal('OTHER') or '')


def test_serve_with_no_registry_declared_is_refused_by_name(
    box: Box, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _serving(box)
    text = box.machine.read_text(encoding='utf-8')
    box.machine.write_text(text.replace('[workstation]', '[workstation_retired]'), encoding='utf-8')
    worst, ran = _serve(box, tmp_path)
    assert (worst, ran) == (2, [])
    assert 'no [workstation] registry' in capsys.readouterr().err


def test_deploy_is_refused_on_a_host_without_the_forge_role(
    box: Box, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    registry = _registry(tmp_path, box.machine, ['client', 'node'])
    assert box.deploy() == 2
    err = capsys.readouterr().err
    assert str(registry) in err
    assert 'add "forge"' in err
    assert box.calls() == []


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
from dev_lab.dev._dep_project import target_root
target_root(pathlib.Path(sys.argv[-1]), pathlib.Path.cwd())
"""


def test_the_bootstrap_passes_the_real_door_from_an_unrelated_cwd(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``dep --bootstrap`` refuses to move a primary checkout from elsewhere, so the deploy runs it IN the checkout."""
    checkout, elsewhere = tmp_path / 'dev-lab', tmp_path / 'elsewhere'
    elsewhere.mkdir()
    subprocess.run([shutil.which('git') or 'git', 'init', '-q', str(checkout)], check=True)
    door = tmp_path / 'door.py'
    door.write_text(REAL_DOOR, encoding='utf-8')
    monkeypatch.chdir(elsewhere)
    programs = workstation.Programs(bootstrap=(sys.executable, str(door)))
    step = workstation.Step(workstation.Tools(git=('git',)), dry=False)
    assert hostrefresh.sync_venv(step, programs.bootstrap, checkout) == 0


def test_a_repo_venv_whose_kit_would_exit_2_no_longer_matters_to_serving(box: Box, tmp_path: Path) -> None:
    """PLANTED CONTROL: every repo venv's kit exits 2, and serving is untouched -- the HOST kit is the scheduler.

    Two repos on one host served by their own venvs ran two different schedulers, and a fix to the host's kit
    never reached the parts it ran (a repo venv held an older non-editable kit).
    """
    _serving(box)

    def run(argv: list[str], **_kw: object) -> _Done:
        stale = Path(argv[0]).is_relative_to(box.root)  # any repo's own venv interpreter
        return _Done(2 if stale else 0)

    assert workstation.serve(run=run, lock=tmp_path / 'serve.lock', programs=box.programs) == 0


def test_a_new_committed_lock_rebootstraps_a_served_venv_and_no_remote_is_asked(tmp_path: Path) -> None:
    """PIN + FRESHNESS (user ruling 2026-10-17): a served venv is its committed lock, keyed by the lock's content.

    The git source is unresolvable (``.invalid``): a key that asked it would fail. PLANTED CONTROL: an unchanged
    lock leaves the venv current and runs nothing.
    """
    checkout = tmp_path / 'repo'
    checkout.mkdir()
    (checkout / 'pyproject.toml').write_text(
        '[project]\nname = "r"\ndependencies = ["lab-commons @ git+https://forge.invalid/o/lab-commons.git"]\n',
        encoding='utf-8',
    )
    (checkout / 'uv.lock').write_text('rev = "1"\n', encoding='utf-8')
    python = hostrefresh.venv_python(checkout)
    python.parent.mkdir(parents=True)
    python.write_text('', encoding='utf-8')
    ran: list[str] = []

    class _Step:
        dry = False

        def change(self, what: str, _argv: object, **_kw: object) -> int:
            ran.append(what)
            return 0

    assert hostrefresh.sync_venv(_Step(), ('boot',), checkout) == 0
    assert len(ran) == 1, 'a venv with no stamp is bootstrapped'
    assert hostrefresh.sync_venv(_Step(), ('boot',), checkout) == 0
    assert len(ran) == 1, 'an unchanged lock leaves it current'
    (checkout / 'uv.lock').write_text('rev = "2"\n', encoding='utf-8')
    assert hostrefresh.sync_venv(_Step(), ('boot',), checkout) == 0
    assert len(ran) == 2, 'a new lock re-bootstraps it'
