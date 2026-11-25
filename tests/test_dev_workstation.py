"""``python -m dev_lab.dev.workstation`` against fake ``git``, ``dep --bootstrap``, venv python and ``schtasks``.

Each fake is a tiny Python program run through :data:`sys.executable`, logging its argv to ``calls.log``
and keeping its state in files under the test's temporary directory; the COM and PATH probes are
callables. No test touches this box's machine file, Scheduled Task or credential store.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tomllib
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Final

import pytest
from _roles_fixtures import HPC_REPO, carry
from lab_commons.config import CONFIG_ENV
from lab_commons.hpc.retired import RETIRED

from dev_lab.dev import hostrefresh, venvfollow, workstation, workstationfile, workstationregistry
from dev_lab.dev.forgealarm import Alarm
from dev_lab.dev.rolecheck import host_refusals
from dev_lab.dev.venvpath import venv_interpreter

#: Every probed tool its probe marks heavy; a plain probed tool (ngspice, node) is never withheld.


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
    (git.parent / 'pyproject.toml').write_text('[project]\nname = "x"\n')
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
elif args[0] == '/Delete':
    state.unlink()
"""

#: Every argv fragment that CHANGES something; a second run and a dry run log none of them.
CHANGES: Final = ('clone', 'merge', 'fetch', 'bootstrap', '--install', '/Delete')


@dataclass(frozen=True)
class Box:
    """One fake workstation: its checkouts (``<forge home>/repos``), machine file, retired Task state, call log."""

    root: Path
    machine: Path
    task: Path
    log: Path
    programs: workstation.Programs

    def calls(self) -> list[str]:
        return self.log.read_text().splitlines() if self.log.exists() else []

    def deploy(self, *extra: str) -> int:
        return workstation.deploy([*DEPLOY, *extra], programs=self.programs)


#: A fake ``-m dev_lab.dev.toolrelease``: it logs ``toolrelease <verb> <tool>`` and installs nothing.
_FAKE_TOOLRELEASE = 'import sys; open(sys.argv[1], "a").write("toolrelease " + " ".join(sys.argv[2:]) + chr(10))'


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
        toolrelease=(py, '-c', _FAKE_TOOLRELEASE, str(log)),
        tool_dir=tmp_path / 'tools',
    )
    return Box(tmp_path / 'home' / 'repos', machine, task, log, programs)


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


def test_a_fresh_box_is_cloned_bootstrapped_hooked_and_declared_and_nothing_is_scheduled(box: Box) -> None:
    assert box.deploy() == 0
    calls = box.calls()
    for name in ('dev-lab', 'alpha', 'beta'):
        assert f'git clone -q -b integrate/main {FORGE}/{name}.git {box.root / name}' in calls
        assert f'bootstrap {box.root / name}' in calls
        assert (box.root / name / '.git' / 'HOOKED').exists()
    declared = tomllib.loads(box.machine.read_text(encoding='utf-8'))
    jmag = {'seats': 4, 'in_use': {'process': list(workstationfile.JMAG_SOLVER_IMAGES)}}
    assert declared['capabilities'] == {'workstation': {}, 'jmag': jmag}, 'a jmag seat is observed by its solvers'
    assert 'serve' not in declared, "a workstation never serves a merge's parts (user ruling 2026-11-16)"
    assert 'reserve' not in declared, 'deploy reserves nothing: the OS headroom keeps its defaults'
    assert not box.task.exists(), 'a workstation never serves: no Task is registered'
    assert not [call for call in calls if '/Delete' in call.split()], 'PLANTED CONTROL: no retired Task, no delete'


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
    assert '+[serve]' not in out
    assert '+[capabilities.jmag]' in out
    assert 'lab-forge-serve' in out
    assert 'none installed' in out
    assert not box.programs.home.exists()


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
    assert workstation.deploy([*DEPLOY], programs=bare) == 2
    err = capsys.readouterr().err
    assert 'astral.sh/uv/install.ps1' in err
    assert 'OpenJS.NodeJS.LTS' in err
    assert '@openai/codex' in err
    assert 'designer.Application, scheduler.JobApplication not registered' in err
    assert '4 missing' in err
    assert box.calls() == []


def test_the_workstation_kit_and_jmag_are_probed_only_when_declared(box: Box) -> None:
    bare = replace(box.programs, which=lambda tool: None if tool in {'node', 'codex'} else tool, com=lambda _p: None)
    argv = ['--repos', REPOS, '--capabilities', 'femm:1', '--forge', FORGE]
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
    """One repo's refusal never stops the others: its owner is alarmed, the exit is 2."""
    raised: list[Alarm] = []
    programs = replace(box.programs, alarm=raised.append)
    argv = [*DEPLOY]
    assert workstation.deploy(argv, programs=programs) == 0
    (box.root / 'beta' / '.git' / 'DIRTY').touch()
    (box.root / 'alpha' / '.git' / 'UP_SHA').write_text('b' * 40)
    capsys.readouterr()
    assert workstation.deploy(argv, programs=programs) == 2
    assert f'git -C {box.root / "alpha"} merge --ff-only -q @{{u}}' in box.calls(), 'the planted control moves on'
    declared = tomllib.loads(box.machine.read_text(encoding='utf-8'))
    assert 'serve' not in declared, "no [serve]: a host serves by each repo's producer, never a list"
    assert 'beta' in capsys.readouterr().err
    assert [(one.repo, 'local changes' in one.body) for one in raised] == [(f'{FORGE}/beta.git', True)]


def test_a_missing_checkout_without_a_forge_is_refused(box: Box, capsys: pytest.CaptureFixture[str]) -> None:
    argv = ['--repos', REPOS]
    assert workstation.deploy(argv, programs=box.programs) == 2
    assert 'pass --forge' in capsys.readouterr().err


def test_a_jmag_solver_image_is_the_solver_and_never_its_launcher_or_service() -> None:
    images = set(workstationfile.JMAG_SOLVER_IMAGES)
    assert 'jam.exe' in images
    assert images.isdisjoint({'execsolver.exe', 'scheduler.exe', 'designer.exe'}), 'one solve counts once'


@pytest.mark.parametrize('flag', ['--seat-margin=jmag=2', '--cpu-margin=8', '--mem-margin=0.25'])
def test_deploy_reserves_nothing_for_people(flag: str) -> None:
    """A person DECLARES their use (``box claim``, ruling 2026-10-25): deploy writes no margin for them."""
    with pytest.raises(SystemExit):
        workstation.deploy(['--repos', REPOS, '--capabilities', 'jmag:4', flag])


def test_the_kit_is_deployed_on_every_host_even_when_not_named(box: Box) -> None:
    """Ruling 2026-10-29 (D73): the kit checkout is kept current on every host, named in ``--repos`` or not."""
    assert (
        workstation.deploy(
            ['--repos', 'alpha,beta', '--capabilities', 'workstation', '--forge', FORGE], programs=box.programs
        )
        == 0
    )
    declared = tomllib.loads(box.machine.read_text(encoding='utf-8'))
    assert 'serve' not in declared
    assert f'bootstrap {box.root / "dev-lab"}' in box.calls(), 'the kit is deployed though not named'


def test_a_bad_capability_is_refused_by_name() -> None:
    with pytest.raises(SystemExit):
        workstation.deploy(['--repos', REPOS, '--capabilities', 'jmag:x'])


def test_a_vendor_tool_without_a_seat_count_is_refused_by_the_parser(capsys: pytest.CaptureFixture[str]) -> None:
    """A vendor tool's seats are declared, never lent 1 (lab-commons UndeclaredSeat): an argument error, no trace."""
    with pytest.raises(SystemExit) as stopped:
        workstation.deploy(['--repos', REPOS, '--capabilities', 'femm'])
    assert stopped.value.code == 2
    assert 'femm' in capsys.readouterr().err


def test_a_retired_serve_task_is_deleted_and_a_second_run_finds_none(box: Box) -> None:
    """User ruling 2026-11-16: a workstation never serves, so the Task an older deploy registered is deleted."""
    box.task.write_text('<Arguments>-m dev_lab.dev.workstation serve</Arguments>')
    assert box.deploy('--dry-run') == 0
    assert box.task.exists(), 'a dry run deletes nothing'
    assert box.deploy() == 0
    assert f'schtasks /Delete /TN {workstation.RETIRED_TASK} /F' in box.calls()
    assert not box.task.exists()
    seen = len(box.calls())
    assert box.deploy() == 0
    assert not [c for c in box.calls()[seen:] if '/Delete' in c.split()], 'PLANTED CONTROL: none left to delete'


def test_the_retired_serve_verb_is_refused_by_name_with_the_ruling_and_its_door(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """PLANTED: ``workstation serve`` is refused by name, never parsed into an argparse error; ``template`` runs."""
    assert workstation.main(['serve']) == 2
    err = capsys.readouterr().err
    assert '`workstation serve` is retired' in err
    assert 'user ruling 2026-11-16' in err
    assert 'forge queue' in err, 'the door to read a sha is named'
    assert 'workstation deploy' in err, 'the door that deletes the retired Task is named'
    assert workstation.main(['template', '--role', 'light']) == 0, 'PLANTED CONTROL: a live verb runs'


def test_off_windows_the_deploy_is_refused(box: Box) -> None:
    assert workstation.deploy([*DEPLOY], programs=replace(box.programs, windows=False)) == 2


def test_the_registry_entry_is_matched_by_computer_before_name(box: Box, tmp_path: Path) -> None:
    _registry(tmp_path, box.machine, ['forge'], computer='box')
    assert workstationregistry.forge_refusal('BOX') is None, 'COMPUTERNAME matches case-insensitively'
    assert workstationregistry.forge_refusal('G') is None, 'the label matches when no computer does'
    assert 'roles of WS9' in (workstationregistry.forge_refusal('OTHER') or '')


def test_deploy_is_refused_on_a_host_without_the_forge_role(
    box: Box, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    registry = _registry(tmp_path, box.machine, ['client', 'node'])
    assert box.deploy() == 2
    err = capsys.readouterr().err
    assert str(registry) in err
    assert 'add "forge"' in err
    assert box.calls() == []


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
    python = venvfollow.venv_python(checkout)
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


def test_the_retired_root_flag_is_refused_by_name(capsys: pytest.CaptureFixture[str]) -> None:
    """Serve checkouts are DERIVED from the forge home; ``--root`` is retired, never silently ignored."""
    assert workstation.main(['deploy', *DEPLOY, '--root=C:/anywhere']) == 2
    err = capsys.readouterr().err
    assert '`workstation --root` is retired' in err
    assert 'repos' in err


def test_deploy_removes_a_hand_written_serve_table(box: Box) -> None:
    assert box.deploy() == 0
    box.machine.write_text(
        box.machine.read_text(encoding='utf-8') + '\n[serve]\nroot = "D:/srv/src"\nparts = "every"\n', encoding='utf-8'
    )
    assert box.deploy() == 0
    assert 'serve' not in tomllib.loads(box.machine.read_text(encoding='utf-8')), 'deploy removes the whole table'


LIGHT: Final = ('--repos', REPOS, '--role', 'light', '--forge', FORGE)


def test_the_light_role_declares_its_capabilities_and_no_serve(box: Box) -> None:
    """The light role never runs heavy compute (user ruling 2026-10-28) and never serves (user ruling 2026-11-16)."""
    assert workstation.deploy(list(LIGHT), programs=box.programs) == 0
    declared = tomllib.loads(box.machine.read_text(encoding='utf-8'))
    assert declared['capabilities'] == {'workstation': {}}
    assert 'serve' not in declared
    assert 'node' not in workstationfile.HEAVY, 'PLANTED CONTROL: a plain probed tool is not heavy'
    assert {'femm', 'jmag', 'matlab'} <= set(workstationfile.HEAVY), 'a heavy tool the probe finds is refused'


def test_a_role_deploys_card_passes_the_host_refusals(box: Box) -> None:
    """PLANTED: a card carrying the old ``[serve]`` is refused; the role deploy removes it, and the card passes."""
    held = box.machine.read_text(encoding='utf-8')
    box.machine.write_text(held + '\n[serve]\nparts = "every"\nwithhold = ["jmag"]\n', encoding='utf-8')
    assert host_refusals('ws.toml', tomllib.loads(box.machine.read_text(encoding='utf-8'))), 'PLANTED CONTROL'
    assert workstation.deploy(list(LIGHT), programs=box.programs) == 0
    assert host_refusals('ws.toml', tomllib.loads(box.machine.read_text(encoding='utf-8'))) == []


@pytest.mark.parametrize('heavy', ['jmag:4', 'femm:1', 'matlab:2'])
def test_the_light_role_refuses_a_heavy_capability(box: Box, heavy: str, capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        workstation.deploy([*LIGHT, '--capabilities', f'workstation,{heavy}'], programs=box.programs)
    assert heavy.split(':', maxsplit=1)[0] in capsys.readouterr().err
    assert not box.machine.exists() or 'capabilities.jmag' not in box.machine.read_text(encoding='utf-8')
    assert workstation.deploy([*LIGHT, '--capabilities', 'workstation'], programs=box.programs) == 0, 'PLANTED CONTROL'


def test_deploy_drops_every_retired_capability_table_and_moves_a_runtime_path(
    box: Box, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No alias survives a deploy: a retired ``[capabilities.<name>]`` is removed, a runtime path carried over.

    The registry rows are PLANTED, so the rule is tested whatever the locked lab-commons has retired so far.
    """
    monkeypatch.setitem(RETIRED, 'capabilities.gone', '[capabilities.workstation]')
    monkeypatch.setitem(RETIRED, 'capabilities.olden', '[runtimes.olden] python')
    tables = '[capabilities.gone]\n\n[capabilities.olden]  # moved\npython = "C:/rt/python.exe"\n'
    box.machine.write_text(box.machine.read_text(encoding='utf-8') + tables, encoding='utf-8')
    assert box.deploy() == 0
    declared = tomllib.loads(box.machine.read_text(encoding='utf-8'))
    assert set(declared['capabilities']) == {'workstation', 'jmag'}, 'PLANTED CONTROL: a live table is kept'
    assert declared['runtimes'] == {'olden': {'python': 'C:/rt/python.exe'}}


G_RUNTIME: Final = '[capabilities.ai_lab]  # the review interpreter\npython = "C:/ai-lab/.venv/Scripts/python.exe"\n'


def _g_shaped(box: Box) -> str:
    """The forge host's 10-29 machine file: the retired runtime table, commented, between live capabilities tables."""
    text = box.machine.read_text(encoding='utf-8').replace('[capabilities.jmag]', G_RUNTIME + '\n[capabilities.jmag]')
    text += '\n[capabilities.connection]  # supply\nseats = 1\n'
    box.machine.write_text(text, encoding='utf-8')
    return text


def test_a_dry_run_reports_the_runtime_move_it_would_make(box: Box, capsys: pytest.CaptureFixture[str]) -> None:
    """Live bug: the forge host's dry run said "declares every table" over a retired ``[capabilities.ai_lab]``."""
    assert box.deploy() == 0
    held = _g_shaped(box)
    capsys.readouterr()
    assert box.deploy('--dry-run') == 0
    out = capsys.readouterr().out
    assert 'already declares every table' not in out
    assert 'retired spelling moved: [capabilities.ai_lab] dropped: built from the ai-lab commit' in out
    assert '-[capabilities.ai_lab]  # the review interpreter' in out
    assert box.machine.read_text(encoding='utf-8') == held, 'a dry run writes nothing'


def test_deploy_drops_a_hand_set_ai_lab_runtime_backs_up_once_and_is_idempotent(box: Box) -> None:
    """2026-11-05: the review runtime is built from the lock, so a deploy drops the path G kept by hand."""
    assert box.deploy() == 0
    _g_shaped(box)
    box.machine.write_text(
        box.machine.read_text(encoding='utf-8') + G_RUNTIME.replace('capabilities', 'runtimes'), encoding='utf-8'
    )
    held = box.machine.read_text(encoding='utf-8')
    assert box.deploy() == 0
    text = box.machine.read_text(encoding='utf-8')
    declared = tomllib.loads(text)
    assert set(declared['capabilities']) == {'workstation', 'jmag', 'connection'}, 'PLANTED CONTROL: supply kept'
    assert 'ai_lab' not in declared.get('runtimes', {}), 'both spellings of the derived runtime are dropped'
    backup = box.machine.with_name(box.machine.name + '.lab-deploy.bak')
    assert backup.read_text(encoding='utf-8') == held
    assert box.deploy() == 0
    assert box.machine.read_text(encoding='utf-8') == text, 'a second deploy changes nothing'


def test_the_template_is_the_role_as_deploy_writes_it(capsys: pytest.CaptureFixture[str]) -> None:
    assert workstation.main(['template', '--role', 'light']) == 0
    assert tomllib.loads(capsys.readouterr().out) == {'capabilities': {'workstation': {}}}


DOC: Final = Path(__file__).resolve().parents[1] / 'docs-src' / 'dev' / 'adding-a-workstation.md'
TEMPLATE_BLOCK: Final = re.compile(r'<!-- template: (?P<role>\w+) -->\n```toml\n(?P<body>.*?)```', re.DOTALL)


def test_the_docs_template_is_the_profile_rendered_never_a_hand_copy() -> None:
    """SINGLE SOURCE: the page's block is what ``template`` prints for the role its marker names."""
    blocks = list(TEMPLATE_BLOCK.finditer(DOC.read_text(encoding='utf-8')))
    assert [b['role'] for b in blocks] == ['light'], 'the page carries the one light template'
    for block in blocks:
        assert block['body'] == workstationfile.template(block['role'])


def test_a_host_follow_never_moves_a_checkout_a_live_run_executes_from(tmp_path: Path) -> None:
    """TREE-HAS-A-LIVE-RUN: the follow skips before its fetch and names the holder; PLANTED CONTROL: idle moves on."""
    checkout = tmp_path / 'repo'
    subprocess.run([shutil.which('git') or 'git', 'init', '-q', str(checkout)], check=True)
    ran: list[str] = []

    class _Step:
        dry = True

        def change(self, what: str, _argv: object, **_kw: object) -> int:
            ran.append(what)
            return 0

    git = (shutil.which('git') or 'git',)
    held = hostrefresh.follow(_Step(), git, checkout, busy=lambda _root: 'live run: pid 4242 (app)')
    assert held.rc == 2
    assert 'pid 4242 (app)' in held.why
    assert not ran
    assert hostrefresh.follow(_Step(), git, checkout, busy=lambda _root: '').rc == 0
    assert ran


@pytest.fixture(autouse=True)
def _hpc_repo(monkeypatch: pytest.MonkeyPatch) -> None:
    """These repos are served by an HPC executor: the family binds tests, merge and prune there (planted)."""
    carry(monkeypatch, HPC_REPO)


def test_a_box_without_rclone_installs_the_pinned_release(box: Box) -> None:
    """D76: the setup installs every pinned-release tool that resolves nowhere, through its one door."""
    lacking = replace(box, programs=replace(box.programs, which=lambda t: None if t == 'rclone' else f'/bin/{t}'))
    assert lacking.deploy() == 0
    assert 'toolrelease install rclone' in lacking.calls()


def test_a_box_with_rclone_installs_nothing(box: Box) -> None:
    """PLANTED CONTROL for the install test: a resolvable rclone is left alone."""
    assert box.deploy() == 0
    assert not [call for call in box.calls() if call.startswith('toolrelease')]
