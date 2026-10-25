"""``python -m dev_lab.dev.hpchost deploy`` against a fake home, a fake ``crontab``, ``git``, ``uv`` and shell.

Each fake is a tiny Python program run through :data:`sys.executable`, so the test is the same on every
box: it logs its argv to ``calls.log`` and keeps its state in files under the test's temporary directory.
"""

from __future__ import annotations

import shlex
import sys
import tomllib
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Final

import pytest
from lab_commons.hpc.grants import load_grants
from lab_commons.hpc.retired import RETIRED

from dev_lab.dev.hpchost import deploy, tick
from dev_lab.dev.hpchost import spec as deploy_spec
from dev_lab.dev.hpchost import steps as deploy_steps
from dev_lab.dev.hpchost.steps import Tools

URL: Final = 'https://forge.example/team'
LAB: Final = ('--repo', f'dev-lab={URL}/dev-lab.git@trunk')
GRANT: Final = ('--partition', 'shortq', '--partition', 'defq')
DECLARE: Final = (
    '--host', 'login02', *LAB, '--repo', f'alpha={URL}/alpha.git@trunk', '--repo', f'beta={URL}/beta.git@trunk', *GRANT
)  # fmt: skip
SACCT: Final = 'acct-free|cpu=96,mem=360G\nacct-free|cpu=96,mem=360G\n'

FAKE_CRONTAB: Final = r"""
import pathlib, sys
state = pathlib.Path(sys.argv[1])
log = state.parent / 'calls.log'
with log.open('a') as f: f.write('crontab ' + ' '.join(sys.argv[2:]) + '\n')
if sys.argv[2] == '-l':
    if not state.exists():
        sys.stderr.write('no crontab for me\n'); sys.exit(1)
    sys.stdout.write(state.read_text())
elif sys.argv[2] == '-':
    state.write_text(sys.stdin.read())
"""

FAKE_GIT: Final = r"""
import os, pathlib, sys
log = pathlib.Path(sys.argv[1])
args = sys.argv[2:]
with log.open('a') as f: f.write('git ' + ' '.join(args) + '\n')
if args[:3] == ['config', '--global', '--get']:
    helper = os.environ.get('FAKE_GIT_HELPER', 'store')  # 'unset': an empty variable does not survive Windows
    sys.stdout.write('' if helper == 'unset' else helper + '\n')
    sys.exit(1 if helper == 'unset' else 0)
if 'rev-parse' in args and args[-1] == 'HEAD':
    head = pathlib.Path(args[args.index('-C') + 1], '.git', 'HEAD_SHA')
    sys.stdout.write(head.read_text() if head.exists() else 'a' * 40)
if args[0] == 'ls-remote':
    sys.exit(128 if any(d in args[1] for d in os.environ.get('FAKE_GIT_DENY', '').split(',') if d) else 0)
if args[0] == 'clone':
    target = pathlib.Path(args[-1])
    (target / '.git').mkdir(parents=True)
    (target / 'pyproject.toml').write_text('[tool.lab_commons.hpc]\ninstall = "uv sync --extra dev"\n')
"""

FAKE_ANSWER: Final = r"""
import os, pathlib, sys
with pathlib.Path(sys.argv[2]).open('a') as f: f.write(sys.argv[3] + ' ' + ' '.join(sys.argv[4:]) + '\n')
sys.stdout.write(os.environ.get(sys.argv[1], ''))
"""

FAKE_LOGGER: Final = r"""
import pathlib, sys
with pathlib.Path(sys.argv[1]).open('a') as f: f.write(sys.argv[2] + ' ' + ' '.join(sys.argv[3:]) + '\n')
"""


@dataclass(frozen=True)
class Box:
    """One fake login node: its home, machine file, crontab state and the log every fake appends to."""

    home: Path
    machine: Path
    crontab: Path
    calls: Path
    tools: Tools
    refused_api: dict[str, str]
    alarms: list[tuple[str, ...]]

    def run(self, *argv: str, host: str = 'login02.int.cluster') -> int:
        return deploy.deploy(
            [*argv, '--config', str(self.machine)],
            home=self.home,
            hostname=host,
            tools=self.tools,
            api=lambda url, _home: next((why for name, why in self.refused_api.items() if f'/{name}.git' in url), ''),
            alarm=lambda *raised: self.alarms.append(raised),
        )

    def logged(self) -> str:
        return self.calls.read_text(encoding='utf-8') if self.calls.exists() else ''


def _write(path: Path, text: str) -> Path:
    path.write_text(text, encoding='utf-8')
    return path


@pytest.fixture
def box(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Box:
    home = tmp_path / 'home'
    home.mkdir()
    (home / '.git-credentials').write_text('https://me:t@forge.example\n', encoding='utf-8')
    (home / '.git-credentials').chmod(0o600)
    monkeypatch.setenv('FAKE_ID', 'alice')
    monkeypatch.setenv('FAKE_SACCT', SACCT)
    monkeypatch.setattr(deploy, '_which', lambda name, **_kw: f'/x/{name}')
    monkeypatch.setattr(deploy, '_runs', lambda _sh, _env, _tool: True)  # every tool runs unless a test says not
    monkeypatch.setattr(deploy, '_proves', lambda _git, _scratch: '')  # every git qualifies unless a test says not
    calls = tmp_path / 'calls.log'
    crontab = tmp_path / 'crontab.txt'
    logger = str(_write(tmp_path / 'logger.py', FAKE_LOGGER))
    answer = str(_write(tmp_path / 'answer.py', FAKE_ANSWER))
    tools = Tools(
        git=(sys.executable, str(_write(tmp_path / 'git.py', FAKE_GIT)), str(calls)),
        crontab=(sys.executable, str(_write(tmp_path / 'crontab.py', FAKE_CRONTAB)), str(crontab)),
        uv=(sys.executable, logger, str(calls), 'uv'),
        sh=(sys.executable, logger, str(calls), 'sh'),
        id=(sys.executable, answer, 'FAKE_ID', str(calls), 'id'),
        sacctmgr=(sys.executable, answer, 'FAKE_SACCT', str(calls), 'sacctmgr'),
    )
    return Box(home, tmp_path / 'machine' / 'config.toml', crontab, calls, tools, {}, [])


def test_twice_gives_one_marked_line_per_repo_and_keeps_the_users_own(box: Box) -> None:
    _write(box.crontab, '0 1 * * * echo mine\n')
    assert box.run(*DECLARE) == 0
    assert box.run() == 0  # the second run reads the declaration the first one stored
    lines = box.crontab.read_text(encoding='utf-8').splitlines()
    assert lines[0] == '0 1 * * * echo mine'
    marked = [line for line in lines if deploy_spec.MARK in line]
    assert {line.rsplit(deploy_spec.MARK, 1)[1] for line in marked} == {'dev-lab', 'alpha', 'beta'}
    assert len(marked) == 3
    alpha = next(line for line in marked if line.endswith('alpha'))
    assert alpha.startswith('*/5 * * * * ')
    assert 'flock -n' in alpha
    assert alpha.split(' >> ')[0].endswith('dev_lab.dev.hpchost tick alpha'), 'the host ticks the repo'
    assert f'cd {shlex.quote(str(box.home / "src" / "dev-lab"))} &&' in alpha, (
        "from the host's kit, never the repo's venv"
    )
    calls = box.logged()
    assert calls.count('git clone') == 3  # the second run updates, never re-clones
    assert 'fetch -q origin +refs/heads/trunk' in calls


def test_a_repo_declaring_a_retired_table_is_refused_alone_and_the_others_are_served(
    box: Box, capsys: pytest.CaptureFixture[str]
) -> None:
    """The 2026-10-13 incident: one repo's retired table stopped the whole deploy, so the host served none."""
    assert box.run(*DECLARE) == 0
    beta = box.home / 'src' / 'beta' / 'pyproject.toml'
    retired = min(key for key in RETIRED if key.startswith('[tool.lab_commons.'))  # its spelling lives in the registry
    _write(beta, f'[tool.lab_commons.hpc]\ninstall = "uv sync"\n{retired}\nx = 1\n')
    capsys.readouterr()
    assert box.run() == 2, 'a refused repo still fails the deploy -- after the others are served'
    marked = [line for line in box.crontab.read_text(encoding='utf-8').splitlines() if deploy_spec.MARK in line]
    served = {line.rsplit(deploy_spec.MARK, 1)[1] for line in marked}
    assert served == {'dev-lab', 'alpha'}, 'the planted control keeps its line; the refused one loses its own'
    err = capsys.readouterr().err
    assert 'beta' in err
    assert f'{retired} is retired' in err
    assert [(repo, retired in body) for repo, _subject, body in box.alarms] == [(f'{URL}/beta.git', True)]
    calls = box.logged()
    assert calls.count('lab-forge-beta.lock') == 1, 'the refused repo is not ticked on the second run'
    assert calls.count('lab-forge-alpha.lock') == 2


def test_a_repo_whose_hpc_declaration_is_invalid_is_refused_alone_and_the_others_are_served(
    box: Box, capsys: pytest.CaptureFixture[str]
) -> None:
    """The 2026-10-18 Ada incident: ``read_builds`` refused one repo's table inside ``[tools]``; the deploy crashed."""
    assert box.run(*DECLARE) == 0
    beta = box.home / 'src' / 'beta' / 'pyproject.toml'
    _write(beta, '[tool.lab_commons.hpc]\ninstall = "uv sync"\ndependency_inputs = ["uv.lock"]\n')
    capsys.readouterr()
    assert box.run() == 2, 'a refused repo still fails the deploy -- after the others are served'
    marked = [line for line in box.crontab.read_text(encoding='utf-8').splitlines() if deploy_spec.MARK in line]
    served = {line.rsplit(deploy_spec.MARK, 1)[1] for line in marked}
    assert served == {'dev-lab', 'alpha'}, 'the planted control keeps its line; the refused one loses its own'
    assert 'dependency_inputs needs source_roots' in capsys.readouterr().err
    assert [repo for repo, _subject, _body in box.alarms] == [f'{URL}/beta.git']


def test_the_declaration_is_stored_once_and_a_disagreeing_one_is_refused(
    box: Box, capsys: pytest.CaptureFixture[str]
) -> None:
    assert box.run(*DECLARE) == 0
    stored = deploy_spec.load(box.machine)
    assert stored is not None
    assert stored.host == 'login02'
    assert [r.name for r in stored.repos] == ['dev-lab', 'alpha', 'beta']
    assert stored.partitions == ('shortq', 'defq')
    assert box.run(*DECLARE) == 0
    assert box.machine.read_text(encoding='utf-8').count('[deploy]') == 1
    assert box.run('--host', 'login02', *LAB, '--repo', f'gamma={URL}/gamma.git@trunk', *GRANT) == 2
    assert str(box.machine) in capsys.readouterr().err


def test_an_undeclared_box_names_the_flags(box: Box, capsys: pytest.CaptureFixture[str]) -> None:
    assert box.run() == 2
    assert '--host <login host> --repo' in capsys.readouterr().err


def test_remove_deletes_only_the_marked_lines(box: Box) -> None:
    _write(box.crontab, '0 1 * * * echo mine\n')
    assert box.run(*DECLARE) == 0
    assert box.run('--remove') == 0
    assert box.crontab.read_text(encoding='utf-8') == '0 1 * * * echo mine\n'


def test_the_wrong_host_is_refused_naming_the_declared_one(box: Box, capsys: pytest.CaptureFixture[str]) -> None:
    assert box.run(*DECLARE, host='login01.int.cluster') == 2
    err = capsys.readouterr().err
    assert 'login02' in err
    assert '[deploy]' in err
    assert box.logged() == ''
    assert not box.machine.exists()


def test_a_credential_failure_names_the_remedy_and_changes_nothing(
    box: Box, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv('FAKE_GIT_DENY', 'beta')
    assert box.run(*DECLARE) == 2
    err = capsys.readouterr().err
    assert 'beta' in err
    assert '~/.git-credentials' in err
    assert 'clone' not in box.logged()
    assert not box.crontab.exists()


def test_dry_run_touches_nothing_and_prints_every_action(box: Box, capsys: pytest.CaptureFixture[str]) -> None:
    assert box.run(*DECLARE, '--dry-run') == 0
    out = capsys.readouterr().out
    assert not box.crontab.exists()
    assert not box.machine.exists()
    assert [p.name for p in box.home.iterdir()] == ['.git-credentials'], 'only the token the fixture stored'
    reads = {'git ls-remote', 'git config', 'crontab -l', 'id -un', 'sacctmgr -nP'}
    assert {' '.join(line.split()[:2]) for line in box.logged().splitlines()} <= reads
    for action in ('declare [deploy]', 'git clone', 'uv sync --extra dev', 'crontab', 'tick'):
        assert action in out
    assert '[[hpc.grant]]' in out
    assert out.count('[dry-run]') >= 7


def test_the_venv_is_built_once_per_declaration(box: Box) -> None:
    assert box.run(*DECLARE) == 0
    assert box.run() == 0
    assert box.logged().count('uv sync --extra dev') == 3  # one per repo, not per run


def _overlays(box: Box) -> list[str]:
    return [line for line in box.logged().splitlines() if '--reinstall-package lab-commons' in line]


def test_every_served_venv_is_exactly_its_committed_lock(box: Box) -> None:
    """PIN + FRESHNESS (user ruling 2026-10-17): nothing is installed over a repo's locked venv.

    PLANTED: the served dev-lab moves; no repo's venv is touched, because its producers run the kit
    its commit was tested with.
    """
    assert box.run(*DECLARE) == 0
    (box.home / 'src' / 'dev-lab' / '.git' / 'HEAD_SHA').write_text('b' * 40, encoding='utf-8')
    assert box.run() == 0
    assert _overlays(box) == []


def test_a_deployment_that_does_not_serve_lab_commons_is_refused(box: Box, capsys: pytest.CaptureFixture[str]) -> None:
    assert box.run('--host', 'login02', '--repo', f'alpha={URL}/alpha.git@trunk', *GRANT) == 2
    assert '--repo dev-lab=' in capsys.readouterr().err
    assert box.logged() == ''


def test_a_token_the_api_refuses_is_refused_before_anything_changes(
    box: Box, capsys: pytest.CaptureFixture[str]
) -> None:
    """ls-remote passed on Ada and every tick then died at GET /user. PLANTED CONTROL: the same run, API allowed."""
    box.refused_api['beta'] = 'GET /api/v1/user refused'
    assert box.run(*DECLARE) == 2
    err = capsys.readouterr().err
    assert 'beta: GET /api/v1/user refused' in err
    assert 'auth login' in err
    assert 'clone' not in box.logged()
    box.refused_api.clear()
    assert box.run(*DECLARE) == 0


def test_an_unset_credential_helper_is_refused_naming_the_fix(
    box: Box, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv('FAKE_GIT_HELPER', 'unset')
    assert box.run(*DECLARE) == 2
    assert 'git config --global credential.helper store' in capsys.readouterr().err
    assert 'ls-remote' not in box.logged()


def test_a_missing_tool_is_installed_or_refused_by_name(
    box: Box, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The uv and cargo installers are the official ones, into ~/.local and ~/.cargo; cc cannot, so it is refused."""
    monkeypatch.setattr(deploy, '_runs', lambda _sh, _env, tool: tool not in {'uv', 'cargo'})
    monkeypatch.setattr(deploy, 'declared', lambda _c: deploy_steps.Builds(install='uv sync', needs=('cargo',)))
    assert box.run(*DECLARE) == 0
    installs = [line for line in box.logged().splitlines() if line.startswith('sh curl')]
    assert len(installs) == 2
    assert 'UV_NO_MODIFY_PATH=1' in installs[0]
    assert '--no-modify-path' in installs[1]
    monkeypatch.setattr(deploy, 'declared', lambda _c: deploy_steps.Builds(install='uv sync', needs=('cc',)))
    monkeypatch.setattr(deploy, '_runs', lambda _sh, _env, tool: tool != 'cc')
    assert box.run() == 2
    err = capsys.readouterr().err
    assert 'cc' in err
    assert '.local/bin' in err


def test_a_tool_is_probed_by_its_version_in_the_tick_environment(box: Box, monkeypatch: pytest.MonkeyPatch) -> None:
    """Present is CAPABILITY: ``cargo --version`` under the tick's PATH and grant setup, never a PATH lookup."""
    probed: list[tuple[str, str]] = []
    monkeypatch.setattr(deploy, '_runs', lambda _sh, env, tool: probed.append((env, tool)) or True)
    monkeypatch.setattr(deploy, 'declared', lambda _c: deploy_steps.Builds(install='uv sync', needs=('cargo',)))
    assert box.run(*DECLARE) == 0
    assert {tool for _env, tool in probed} == {'uv', 'cargo'}
    assert all(env == deploy_spec.tick_environment(box.home, [str(Path('/x'))]) for env, _tool in probed)


def test_the_login_shell_gets_the_tick_user_installs_once_with_a_backup(box: Box) -> None:
    """Measured on Ada 2026-10-25: cargo ran for cron only. The login files get one marked line, written once."""
    (box.home / '.bashrc').write_text('alias ll=ls\n', encoding='utf-8')
    assert box.run(*DECLARE) == 0
    edits = [line for line in box.logged().splitlines() if deploy.LOGIN_MARK in line]
    assert len(edits) == 2, edits
    bashrc = next(line for line in edits if '.bashrc' in line)
    assert '.lab-deploy.bak' in bashrc
    assert str(box.home / '.cargo/bin') in bashrc
    for name in ('.bash_profile', '.bashrc'):
        (box.home / name).write_text(deploy.login_line(box.home) + '\n', encoding='utf-8')
    assert box.run() == 0
    assert len([line for line in box.logged().splitlines() if deploy.LOGIN_MARK in line]) == 2, 'already marked'


def test_the_deploy_writes_this_accounts_own_grant_once(box: Box) -> None:
    """PLANTED CONTROL: an account that already holds a grant keeps it, untouched."""
    assert box.run(*DECLARE) == 0
    (grant,) = load_grants(tomllib.loads(box.machine.read_text(encoding='utf-8'))['hpc']).grants
    assert grant.account == ('alice', 'acct-free')
    assert grant.hosts == ('login02.int.cluster',)
    assert grant.partitions == ('shortq', 'defq')
    before = box.machine.read_text(encoding='utf-8')
    assert box.run() == 0
    assert box.machine.read_text(encoding='utf-8') == before


def test_two_slurm_accounts_are_refused_until_one_is_declared(
    box: Box, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv('FAKE_SACCT', 'acct-int|cpu=96\nacct-free|cpu=96,mem=1G\n')
    assert box.run(*DECLARE) == 2
    err = capsys.readouterr().err
    assert 'acct-int' in err
    assert '--slurm-account' in err
    assert not box.machine.exists() or '[[hpc.grant]]' not in box.machine.read_text(encoding='utf-8')
    box.machine.unlink(missing_ok=True)
    assert box.run(*DECLARE, '--slurm-account', 'acct-free') == 0
    (grant,) = load_grants(tomllib.loads(box.machine.read_text(encoding='utf-8'))['hpc']).grants
    assert grant.slurm_account == 'acct-free'


def test_the_rendered_declaration_reads_back(tmp_path: Path) -> None:
    spec = deploy_spec.Deployment('h', 'src', '3.13', (deploy_spec.Repo('a', 'https://x/a"b', 'r'),), 'acct', ('q',))
    path = _write(tmp_path / 'config.toml', deploy_spec.render(spec))
    assert deploy_spec.load(path) == spec


def test_the_retired_serve_key_is_refused_by_name_with_its_remedy(tmp_path: Path) -> None:
    spec = deploy_spec.Deployment('h', 'src', '3.13', (deploy_spec.Repo('a', 'https://x/a', 'r'),))
    stale = deploy_spec.render(spec).replace('[deploy]', '[deploy]' + chr(10) + 'serve = []')
    with pytest.raises(ValueError, match=r'delete the \[deploy\] serve key'):
        deploy_spec.load(_write(tmp_path / 'config.toml', stale))


def test_the_cron_path_carries_where_slurm_resolved_at_deploy_time(
    box: Box, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Cron's PATH has no site Slurm: a tick said "this box has no sbatch". PLANTED CONTROL: no sbatch, no deploy."""
    slurm = {'sbatch': '/opt/slurm/23.02.6/bin/sbatch', 'sacct': '/opt/slurm/23.02.6/bin/sacct'}
    slurm['squeue'] = '/opt/slurm/23.02.6/bin/squeue'
    monkeypatch.setattr(deploy, '_which', lambda name, **_kw: slurm.get(name, f'/x/{name}'))
    assert box.run(*DECLARE) == 0
    marked = [line for line in box.crontab.read_text(encoding='utf-8').splitlines() if deploy_spec.MARK in line]
    assert all(':/bin:' + str(Path('/opt/slurm/23.02.6/bin')) + ';' in line for line in marked), marked[0]
    del slurm['sbatch']
    monkeypatch.setattr(deploy, '_which', lambda name, **_kw: None if name == 'sbatch' else slurm.get(name, '/x/y'))
    assert box.run() == 2
    assert 'sbatch' in capsys.readouterr().err


def test_the_tick_runs_inside_the_grant_setup_and_its_git_is_proven_there(
    box: Box, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Ada 2026-10-17: the module's git ran only INSIDE its module (``libiconv.so.2``), so a PATH entry for it failed.

    PLANTED CONTROLS: a git that works only after the setup is accepted when proven under it, and every cron
    line then runs that setup before its tick; a setup-less environment with an old git is refused, naming the fix.
    """
    setup = 'module load git/2.42'
    monkeypatch.setattr(deploy, '_proves', lambda git, _scratch: '' if setup in git[-2] else 'usage: git merge-tree')
    assert box.run(*DECLARE) == 2
    err = capsys.readouterr().err
    assert 'git >= 2.38' in err
    assert 'setup = ["module load' in err
    assert not box.crontab.exists()
    text = box.machine.read_text(encoding='utf-8')
    box.machine.write_text(text.replace('[[hpc.grant]]\n', f'[[hpc.grant]]\nsetup = ["{setup}"]\n'))
    assert box.run() == 0
    marked = [line for line in box.crontab.read_text(encoding='utf-8').splitlines() if deploy_spec.MARK in line]
    assert marked
    for line in marked:
        argv = shlex.split(line.removeprefix('*/5 * * * * ').split(deploy_spec.MARK)[0])
        assert argv[:2] == ['bash', '-lc'], line
        assert argv[2].startswith(f'PATH={box.home / ".local/bin"}:'), line
        assert f'; {setup}; cd ' in argv[2], line
        assert argv[2].index(setup) < argv[2].index('dev_lab.dev.hpchost tick'), line


def test_a_setup_with_spaces_semicolons_and_quotes_reaches_bash_verbatim(tmp_path: Path) -> None:
    """The setup is quoted once into ``bash -lc``; PLANTED CONTROL: no setup leaves the plain command."""
    lab = deploy_spec.Repo(deploy_spec.KIT, f'{URL}/dev-lab.git', 'trunk')
    spec = deploy_spec.Deployment('h', 'src', '3.13', (lab,))
    setup = ("module load git/2.42; export X='a b'", 'echo "$HOME" `id`')
    command = deploy_spec.tick_command(spec, tmp_path, lab, log=True, setup=setup)
    argv = shlex.split(command)
    assert argv[:2] == ['bash', '-lc']
    assert argv[2].startswith(deploy_spec.tick_environment(tmp_path, (), setup) + '; cd ')
    assert argv[3:5] == ['>>', str(tmp_path / '.cache' / 'lab-forge-dev-lab.log')]
    plain = deploy_spec.tick_command(spec, tmp_path, lab, log=False)
    assert plain.startswith(f'PATH={tmp_path / ".local/bin"}:')
    assert 'bash -lc' not in plain


FAKE_RCLONE: Final = r"""
import pathlib, sys
with pathlib.Path(sys.argv[1]).open('a') as f: f.write('rclone ' + ' '.join(sys.argv[3:]) + '\n')
if sys.argv[2] != 'present':
    sys.stderr.write("didn't find section in config file\n"); sys.exit(1)
"""


@pytest.mark.parametrize('state', ['missing', 'present'])
def test_a_repo_declaring_rclone_artefacts_has_its_remote_checked_and_a_missing_one_warns(
    box: Box, tmp_path: Path, capsys: pytest.CaptureFixture[str], state: str
) -> None:
    """A missing remote WARNS with the recipe and the deploy still completes; PLANTED CONTROL: present is quiet."""
    assert box.run(*DECLARE) == 0
    alpha = box.home / deploy_spec.DEFAULT_ROOT / 'alpha' / 'pyproject.toml'
    alpha.write_text(
        '[tool.lab_commons.hpc]\ninstall = "uv sync"\n'
        '[tool.lab_commons.artefacts]\nbackend = "rclone"\nremote = "hpc-data:consumer-a"\n',
        encoding='utf-8',
    )
    rclone = (sys.executable, str(_write(tmp_path / 'rclone.py', FAKE_RCLONE)), str(box.calls), state)
    with_rclone = replace(box, tools=replace(box.tools, rclone=rclone))
    capsys.readouterr()
    assert with_rclone.run() == 0, 'a missing remote is a warning, never a refusal'
    out, err = capsys.readouterr()
    assert 'rclone lsd hpc-data: --max-depth 1' in box.logged()
    assert 'beta: no rclone artefact store declared' in out
    if state == 'missing':
        assert 'alpha: WARNING' in err
        assert 'rclone authorize "onedrive"' in err
        assert 'documentLibrary' in err
    else:
        assert 'alpha: the rclone remote answers' in out
        assert 'WARNING' not in err


class _Done:
    def __init__(self, returncode: int) -> None:
        self.returncode = returncode


def _tick(box: Box, name: str, served: list[tuple[list[str], Path, str]]) -> int:
    def run(argv: list[str], *, cwd: Path, **_kw: object) -> _Done:
        served.append((argv, cwd, box.logged()))
        return _Done(0)

    return tick.tick(name, home=box.home, config=box.machine, tools=box.tools, run=run)


def test_a_tick_refreshes_its_repo_before_the_repos_own_forge_serve(box: Box) -> None:
    """THE PLANTED CONTROL (incident 2026-10-13): the HOST refreshes the repo, then serves it with the host kit.

    alpha's venv is its committed lock, so nothing is installed over it.
    """
    assert box.run(*DECLARE) == 0
    src = box.home / 'src'
    start, served = len(box.logged()), []
    assert _tick(box, 'alpha', served) == 0
    [(argv, cwd, logged)] = served
    assert cwd == src / 'alpha'
    assert argv == deploy_spec.host_serve_argv(), 'the HOST kit serves; the repo venv only runs its producers'
    before = logged[start:]
    assert f'git -C {src / "alpha"} checkout -q -B trunk' in before
    assert '--reinstall-package' not in before, 'a served venv is exactly its lock'


def test_only_the_lab_commons_tick_writes_the_shared_kit_checkout(box: Box) -> None:
    """ONE WRITER OF THE SHARED KIT (Ada 2026-10-19): every repo's tick used to update ``~/src/dev-lab``.

    Each tick holds only its OWN repo's flock, so two ticks checked the kit out at once and one died on
    ``.git/index.lock``. The planted concurrent update: the kit's own tick is mid-checkout (its index.lock
    held) while alpha and beta tick together -- neither touches the kit, both serve, and the kit's own
    tick is the one that refreshes it.
    """
    assert box.run(*DECLARE) == 0
    kit = box.home / 'src' / 'dev-lab'
    (kit / '.git' / 'HEAD_SHA').write_text('b' * 40, encoding='utf-8')
    lock = kit / '.git' / 'index.lock'
    lock.write_text('', encoding='utf-8')  # the kit's own tick, mid-update
    start, served = len(box.logged()), []
    with ThreadPoolExecutor(2) as pool:
        codes = list(pool.map(lambda name: _tick(box, name, served), ['alpha', 'beta']))
    assert codes == [0, 0]
    assert f'git -C {kit} ' not in box.logged()[start:], 'a repo tick never writes the shared kit'
    lock.unlink()
    start = len(box.logged())
    assert _tick(box, deploy_spec.KIT, served) == 0
    assert f'git -C {kit} checkout -q -B trunk' in box.logged()[start:], "the kit's own tick refreshes it"


def test_a_repo_whose_refresh_fails_is_released_by_name_and_its_forge_never_runs(
    box: Box, capsys: pytest.CaptureFixture[str]
) -> None:
    assert box.run(*DECLARE) == 0
    _write(box.home / 'src' / 'alpha' / 'pyproject.toml', '[project]\nname = "alpha"\n')
    capsys.readouterr()
    served: list[tuple[list[str], Path, str]] = []
    assert _tick(box, 'alpha', served) == 2
    assert served == []
    assert 'alpha released, not served this tick' in capsys.readouterr().err
    assert _tick(box, 'beta', served) == 0, 'one repo released never stops another'


def test_a_tick_of_an_undeclared_repo_is_refused(box: Box, capsys: pytest.CaptureFixture[str]) -> None:
    assert box.run(*DECLARE) == 0
    assert _tick(box, 'gamma', []) == 2
    assert 'gamma is not a served repo' in capsys.readouterr().err


def test_a_tick_whose_declared_need_no_longer_runs_serves_nothing_and_alarms_naming_account_and_tool(
    box: Box, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Every tick RE-ASSERTS the deploy's ``needs`` with the same probe, once per tool per tick.

    Ada 2026-10-25: cargo ran at deploy and was gone later; every tick claimed parts its build could not make.
    """
    assert box.run(*DECLARE) == 0
    probed: list[str] = []
    monkeypatch.setattr(tick, '_runs', lambda _sh, _env, tool: probed.append(tool) or tool != 'cargo')
    monkeypatch.setattr(tick, 'declared', lambda _c: deploy_steps.Builds(install='uv sync', needs=('cargo', 'cmake')))
    alarms: list[object] = []
    cache: dict[str, bool] = {}
    served: list[tuple[list[str], Path, str]] = []

    def run(argv: list[str], *, cwd: Path, **_kw: object) -> _Done:
        served.append((argv, cwd, ''))
        return _Done(0)

    for name in ('alpha', 'beta'):
        code = tick.tick(
            name, home=box.home, config=box.machine, tools=box.tools, run=run, alarm=alarms.append, probed=cache
        )
        assert code == 2
    assert served == [], 'a repo whose need fails claims nothing'
    assert sorted(probed) == ['cargo', 'cmake'], 'one probe per tool per tick'
    first = alarms[0]
    assert 'cargo' in first.subject
    assert tick.account() in first.subject
    assert 'cmake' not in first.subject
    assert first.repo == f'{URL}/alpha.git'
