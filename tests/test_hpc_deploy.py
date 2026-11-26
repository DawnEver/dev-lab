"""``python -m dev_lab.dev.hpcaccount deploy`` against a fake home, a fake ``crontab``, ``git``, ``uv`` and shell.

Each fake is a tiny Python program run through :data:`sys.executable`, so the test is the same on every
box: it logs its argv to ``calls.log`` and keeps its state in files under the test's temporary directory.
"""

from __future__ import annotations

import json
import re
import shlex
import sys
import tomllib
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Final

import pytest
from _roles_fixtures import EVERY_CI, HPC_REPO, carry
from lab_commons.hpc.grants import Grant, load_grants
from lab_commons.hpc.retired import RETIRED

from dev_lab.dev import tickholder, venvpointer
from dev_lab.dev._machinefile import dumps
from dev_lab.dev.hpcaccount import deploy, tick, tickwall
from dev_lab.dev.hpcaccount import spec as deploy_spec
from dev_lab.dev.hpcaccount import steps as deploy_steps
from dev_lab.dev.hpcaccount.account import UNREACHED
from dev_lab.dev.hpcaccount.declaration import declaration, parser
from dev_lab.dev.hpcaccount.fleet import grant_slice
from dev_lab.dev.hpcaccount.steps import Tools
from dev_lab.dev.roles import ROLES_ENV

URL: Final = 'https://forge.example/team'
LAB: Final = ('--repo', f'dev-lab={URL}/dev-lab.git@trunk')
#: The family's declaration of alice's grant, as deploy-fleet passes it: the one source of a grant.
DECLARED: Final = Grant(
    user='alice', hosts=('login02.int.cluster',), slurm_account='acct-free', partitions=('shortq', 'defq'),
    role='verification', cluster_name='int',
)  # fmt: skip
GRANT: Final = (
    '--partition', 'shortq', '--partition', 'defq', '--role', 'verification',
    '--grant-table', json.dumps(grant_slice(DECLARED)),
)  # fmt: skip
DECLARE: Final = (
    '--host', 'login02', *LAB, '--repo', f'alpha={URL}/alpha.git@trunk', '--repo', f'beta={URL}/beta.git@trunk', *GRANT
)  # fmt: skip
SACCT: Final = 'acct-free|cpu=96,mem=360G\nacct-free|cpu=96,mem=360G\n'

FAKE_CRONTAB: Final = r"""
import os, pathlib, sys
state = pathlib.Path(sys.argv[1])
log = state.parent / 'calls.log'
with log.open('a') as f: f.write('crontab ' + ' '.join(sys.argv[2:]) + '\n')
if os.environ.get('FAKE_CRONTAB_FORBID'):
    sys.stderr.write('You (me) are not allowed to use this program (crontab)\n'); sys.exit(1)
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
if 'ls-remote' in args:
    url = args[args.index('ls-remote') + 1]
    sys.exit(128 if any(d in url for d in os.environ.get('FAKE_GIT_DENY', '').split(',') if d) else 0)
if args[0] == 'clone':
    target = pathlib.Path(args[-1])
    (target / '.git').mkdir(parents=True)
    (target / 'pyproject.toml').write_text(
        '[project.optional-dependencies]\ndev = ["x"]\n[tool.dev_lab.dep]\n'
        'extras = ["dev"]\n[tool.lab_commons.hpc]\n'
    )
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
    #: What the forge says the stored credential is on every repo (``auth role``): a reader by default.
    identity: dict[str, object] = field(default_factory=lambda: {'login': 'ro-login', 'push': False, 'admin': False})

    @property
    def root(self) -> Path:
        """The account's declared root (``[hpc.clusters.<c>] root``): its layout lives under it."""
        return self.home.parent / 'root'

    def run(self, *argv: str, host: str = 'login02.int.cluster') -> int:
        declared = ['--root', self.root.as_posix()] if '--host' in argv else []
        return deploy.deploy(
            [*argv, *declared, '--config', str(self.machine)],
            home=self.home,
            hostname=host,
            tools=self.tools,
            api=lambda url, _home: next((why for name, why in self.refused_api.items() if f'/{name}.git' in url), ''),
            alarm=lambda *raised: self.alarms.append(raised),
            role=lambda _url, _home: dict(self.identity),
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
    assert alpha.split(' ', 1)[0].endswith('-59/5'), 'the schedule default period'
    assert 'flock -n' not in alpha, 'the tick takes its own lock, which names its holder'
    lock = shlex.quote(str(box.root / 'serve' / 'alpha.lock'))
    assert alpha.split(' >> ')[0].endswith(f'dev_lab.dev.hpcaccount tick alpha --lock {lock} --wall-minutes 40'), (
        'the host ticks the repo under its lock and the default wall'
    )
    assert f'cd {shlex.quote(str(box.root / "repos" / "dev-lab"))} &&' in alpha, (
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
    beta = box.root / 'repos' / 'beta' / 'pyproject.toml'
    retired = min(key for key in RETIRED if key.startswith('[tool.lab_commons.'))  # its spelling lives in the registry
    _write(beta, f'[tool.lab_commons.hpc]\n{retired}\nx = 1\n')
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
    assert calls.count(str(Path('serve') / 'beta.lock')) == 1, 'the refused repo is not ticked on the second run'
    assert calls.count(str(Path('serve') / 'alpha.lock')) == 2


def test_a_repo_whose_hpc_declaration_is_invalid_is_refused_alone_and_the_others_are_served(
    box: Box, capsys: pytest.CaptureFixture[str]
) -> None:
    """The 2026-10-18 Ada incident: ``read_builds`` refused one repo's table inside ``[tools]``; the deploy crashed."""
    assert box.run(*DECLARE) == 0
    beta = box.root / 'repos' / 'beta' / 'pyproject.toml'
    _write(beta, '[tool.lab_commons.hpc]\ndependency_inputs = ["uv.lock"]\n')
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
    assert box.logged().count('uv sync --frozen --extra dev') == 3  # one per repo, not per run
    assert box.logged().count('uv cache prune --cache-dir') == 2, 'the ONE cache is pruned after every deploy'


def test_a_changed_key_builds_beside_and_publishes_never_syncing_the_live_venv(box: Box) -> None:
    """W2: a build goes into a FRESH ``.venvs/<name>`` and only then becomes current; the live one is never touched.

    PLANTED: alpha's install recipe (part of the env key) moves after the first deploy -- the second deploy must name
    a different environment; the first, which nothing runs from, is reclaimed at the switch (venvcurrent.reclaim
    spares one a process runs from).
    """
    assert box.run(*DECLARE) == 0
    alpha = box.root / 'repos' / 'alpha'
    first = venvpointer.named(alpha)
    assert first is not None, 'the build is published through the pointer'
    assert (first / '.lab-deploy-env').is_file()
    pyproject = alpha / 'pyproject.toml'
    pyproject.write_text(
        pyproject.read_text(encoding='utf-8').replace('extras = ["dev"]', 'extras = []'), encoding='utf-8'
    )
    assert box.run() == 0
    second = venvpointer.named(alpha)
    assert second is not None
    assert second != first, 'a moved key never syncs into the live environment'
    assert not first.exists(), 'the superseded environment nothing runs from goes at the switch (2026-11-22)'
    assert (second / '.lab-deploy-env').is_file(), 'PLANTED CONTROL: the current environment stays'


def _overlays(box: Box) -> list[str]:
    return [line for line in box.logged().splitlines() if '--reinstall-package lab-commons' in line]


def test_every_served_venv_is_exactly_its_committed_lock(box: Box) -> None:
    """PIN + FRESHNESS (user ruling 2026-10-17): nothing is installed over a repo's locked venv.

    PLANTED: the served dev-lab moves; no repo's venv is touched, because its producers run the kit
    its commit was tested with.
    """
    assert box.run(*DECLARE) == 0
    (box.root / 'repos' / 'dev-lab' / '.git' / 'HEAD_SHA').write_text('b' * 40, encoding='utf-8')
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


def test_a_repo_the_family_binds_elsewhere_is_never_api_checked_even_before_its_first_clone(
    box: Box, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Served-ness is the family's binding of the repo's URL, never whether a checkout exists yet.

    Measured 2026-11-22 on two fresh verification roots: the credentials phase runs before the checkouts, so every
    repo the family binds to hosted CI read as served and was refused "no stored credential" for a host nothing
    serves there. PLANTED CONTROL: the same fresh root still refuses the repo this account does serve.
    """
    bound = {'alpha': HPC_REPO}
    monkeypatch.setattr(
        deploy_spec, 'roles_of_url', lambda url: bound.get(url.rsplit('/', 1)[-1].removesuffix('.git'), EVERY_CI)
    )
    box.refused_api['beta'] = 'no stored credential for elsewhere.example'
    assert not (box.root / 'repos').exists(), 'a fresh root: nothing is cloned yet'
    assert box.run(*DECLARE) == 0, capsys.readouterr().err
    box.refused_api['alpha'] = 'GET /api/v1/user refused'
    assert box.run() == 2
    assert 'alpha: GET /api/v1/user refused' in capsys.readouterr().err


def test_a_forge_api_that_does_not_answer_never_says_restore_the_token(
    box: Box, capsys: pytest.CaptureFixture[str]
) -> None:
    """2026-11-10: a deploy said the token was refused when the forge had only not answered."""
    box.refused_api['beta'] = f'{UNREACHED}: [forge] the forge did not answer'
    assert box.run(*DECLARE) == 2
    err = capsys.readouterr().err
    assert 're-run the deploy' in err
    assert 'auth login' not in err
    assert 'clone' not in box.logged()


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
    assert {tool for _env, tool in probed} == {'uv', 'rclone', 'cargo'}
    assert all(
        env == deploy_spec.tick_environment(box.home, box.root.as_posix(), [str(Path('/x'))]) for env, _tool in probed
    )


def test_the_login_shell_gets_the_tick_user_installs_once_with_a_backup(box: Box) -> None:
    """Measured on Ada 2026-10-25: cargo ran for cron only. The login files get one marked line, written once."""
    (box.home / '.bashrc').write_text('alias ll=ls\n', encoding='utf-8')
    assert box.run(*DECLARE) == 0
    edits = [line for line in box.logged().splitlines() if deploy_steps.LOGIN_MARK in line]
    assert len(edits) == 2, edits
    bashrc = next(line for line in edits if '.bashrc' in line)
    assert '.lab-deploy.bak' in bashrc
    assert str(box.home / '.cargo/bin') in bashrc
    for name in ('.bash_profile', '.bashrc'):
        (box.home / name).write_text(deploy_steps.login_line(box.home, box.root.as_posix()) + '\n', encoding='utf-8')
    assert box.run() == 0
    assert len([line for line in box.logged().splitlines() if deploy_steps.LOGIN_MARK in line]) == 2, 'already marked'


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


#: A grant in the retired shape: ``hosts`` on the grant, not on its cluster.
_RETIRED_SHAPE = (
    '[hpc]\n\n[[hpc.grant]]\nuser = "alice"\nhosts = ["login02.int.cluster"]\nslurm_account = "acct-free"\n'
)


def test_a_grant_in_a_retired_shape_is_migrated_from_the_passed_slice_once(
    box: Box, capsys: pytest.CaptureFixture[str]
) -> None:
    """FORMATS-MIGRATE-ONCE: a grant this kit refuses is rewritten from the family's passed slice, once.

    It used to read as "already holds a grant", and the next phase died in a traceback. Every other table is kept.
    PLANTED CONTROL: a current grant is kept untouched (the test above).
    """
    box.machine.parent.mkdir(parents=True, exist_ok=True)
    box.machine.write_text(_RETIRED_SHAPE.replace('[hpc]', '[other]\nkeep = 1\n\n[hpc]'), encoding='utf-8')
    assert box.run(*DECLARE) == 0
    table = tomllib.loads(box.machine.read_text(encoding='utf-8'))
    (grant,) = load_grants(table['hpc']).grants
    assert grant.account == ('alice', 'acct-free')
    assert table['other'] == {'keep': 1}
    assert 'migrated' in capsys.readouterr().out
    before = box.machine.read_text(encoding='utf-8')
    assert box.run(*DECLARE) == 0
    assert box.machine.read_text(encoding='utf-8') == before, 'migrates once'


def test_a_machine_file_with_an_hpc_table_but_no_grant_gains_the_grant_in_that_one_table(box: Box) -> None:
    """Measured 2026-11-20 on Ada: the deploy appended a second ``[hpc]`` to a file already holding one.

    The rendered file held ``[hpc] reach`` and no grant; the old append wrote a second
    ``[hpc]`` and every later read raised "Cannot declare ('hpc',) twice". The grant joins the ONE table, its keys kept.
    PLANTED CONTROL: the pre-fix append made this file unparsable.
    """
    box.machine.parent.mkdir(parents=True, exist_ok=True)
    box.machine.write_text('[other]\nkeep = 1\n\n[hpc]\nreach = ["research"]\n', encoding='utf-8')
    assert box.run(*DECLARE) == 0
    text = box.machine.read_text(encoding='utf-8')
    table = tomllib.loads(text)
    assert text.count('[hpc]') == 1, text
    assert table['hpc']['reach'] == ['verification'], 'the passed slice wins its own keys'
    assert table['other'] == {'keep': 1}
    (grant,) = load_grants(table['hpc']).grants
    assert grant.account == ('alice', 'acct-free')


def test_a_grant_in_a_retired_shape_with_no_passed_slice_is_refused_naming_deploy_fleet(
    box: Box, capsys: pytest.CaptureFixture[str]
) -> None:
    box.machine.parent.mkdir(parents=True, exist_ok=True)
    box.machine.write_text(_RETIRED_SHAPE, encoding='utf-8')
    declare = DECLARE[: DECLARE.index('--grant-table')]
    assert box.run(*declare) == 2
    err = capsys.readouterr().err
    assert 'retired' in err
    assert 'deploy-fleet' in err


def test_a_declared_account_slurm_does_not_associate_is_refused_and_nothing_is_written(
    box: Box, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The grant is the family's declaration; Slurm only confirms it. PLANTED CONTROL: an associated account deploys."""
    monkeypatch.setenv('FAKE_SACCT', 'acct-int|cpu=96\n')
    assert box.run(*DECLARE) == 2
    err = capsys.readouterr().err
    assert 'acct-free' in err
    assert 'acct-int' in err
    assert not box.machine.exists() or '[[hpc.grant]]' not in box.machine.read_text(encoding='utf-8')
    box.machine.unlink(missing_ok=True)
    monkeypatch.setenv('FAKE_SACCT', 'acct-int|cpu=96\nacct-free|cpu=96,mem=1G\n')
    assert box.run(*DECLARE) == 0
    (grant,) = load_grants(tomllib.loads(box.machine.read_text(encoding='utf-8'))['hpc']).grants
    assert grant.slurm_account == 'acct-free'


def test_a_hand_run_deploy_with_no_grant_is_refused_naming_deploy_fleet(
    box: Box, capsys: pytest.CaptureFixture[str]
) -> None:
    """A grant is never derived on the account. PLANTED CONTROL: the passed slice is written (the test above)."""
    declare = DECLARE[: DECLARE.index('--grant-table')]
    assert box.run(*declare) == 2
    assert 'deploy-fleet' in capsys.readouterr().err


def test_the_rendered_declaration_reads_back(tmp_path: Path) -> None:
    spec = deploy_spec.Deployment('h', '/r/src', '3.13', (deploy_spec.Repo('a', 'https://x/a"b', 'r'),), 'acct', ('q',))
    path = _write(tmp_path / 'config.toml', deploy_spec.render(spec))
    assert deploy_spec.load(path) == spec


def test_a_repo_row_declares_the_parts_this_account_produces_first_and_it_reads_back(tmp_path: Path) -> None:
    """HPC account affinity (user ruling 2026-10-30): a verify account's row names the contexts it is affined to."""
    affined = deploy_spec.Repo('a', 'https://x/a', 'r', verify=('tests/*',))
    spec = deploy_spec.Deployment('h', '/r/src', '3.13', (affined, deploy_spec.Repo('b', 'https://x/b', 'r')))
    path = _write(tmp_path / 'config.toml', deploy_spec.render(spec))
    assert deploy_spec.load(path) == spec
    assert [repo.verify for repo in deploy_spec.load(path).repos] == [('tests/*',), ()], 'PLANTED CONTROL: b has none'


def test_the_retired_serve_key_is_refused_by_name_with_its_remedy(tmp_path: Path) -> None:
    spec = deploy_spec.Deployment('h', '/r/src', '3.13', (deploy_spec.Repo('a', 'https://x/a', 'r'),))
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
    box.machine.write_text(text.replace('[hpc.clusters.int]\n', f'[hpc.clusters.int]\nsetup = ["{setup}"]\n'))
    assert box.run() == 0
    marked = [line for line in box.crontab.read_text(encoding='utf-8').splitlines() if deploy_spec.MARK in line]
    assert marked
    for line in marked:
        argv = shlex.split(line.split(' ', 5)[5].split(deploy_spec.MARK)[0])
        assert argv[:2] == ['bash', '-lc'], line
        assert argv[2].startswith(f'PATH={box.home / ".local/bin"}:'), line
        assert f'; {setup}; cd ' in argv[2], line
        assert argv[2].index(setup) < argv[2].index('dev_lab.dev.hpcaccount tick'), line


def test_a_setup_with_spaces_semicolons_and_quotes_reaches_bash_verbatim(tmp_path: Path) -> None:
    """The setup is quoted once into ``bash -lc``; PLANTED CONTROL: no setup leaves the plain command."""
    lab = deploy_spec.Repo(deploy_spec.KIT, f'{URL}/dev-lab.git', 'trunk')
    spec = deploy_spec.Deployment('h', '/r/src', '3.13', (lab,))
    setup = ("module load git/2.42; export X='a b'", 'echo "$HOME" `id`')
    command = deploy_spec.tick_command(spec, tmp_path, lab, log=True, setup=setup)
    argv = shlex.split(command)
    assert argv[:2] == ['bash', '-lc']
    assert argv[2].startswith(deploy_spec.tick_environment(tmp_path, '/r/src', (), setup) + '; cd ')
    assert argv[3:5] == ['>>', str(Path('/r/src') / 'serve' / 'dev-lab.log')], 'the tick log is the serve dir'
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
def test_a_repo_declaring_rclone_artifacts_has_its_remote_checked_and_a_missing_one_warns(
    box: Box, tmp_path: Path, capsys: pytest.CaptureFixture[str], state: str
) -> None:
    """A missing remote WARNS with the recipe and the deploy still completes; PLANTED CONTROL: present is quiet."""
    assert box.run(*DECLARE) == 0
    alpha = box.root / 'repos' / 'alpha' / 'pyproject.toml'
    alpha.write_text(
        '[tool.lab_commons.hpc]\n[tool.lab_commons.artefacts]\nbackend = "rclone"\nremote = "hpc-data:consumer-a"\n',
        encoding='utf-8',
    )
    rclone = (sys.executable, str(_write(tmp_path / 'rclone.py', FAKE_RCLONE)), str(box.calls), state)
    with_rclone = replace(box, tools=replace(box.tools, rclone=rclone))
    capsys.readouterr()
    assert with_rclone.run() == 0, 'a missing remote is a warning, never a refusal'
    out, err = capsys.readouterr()
    assert 'rclone lsd hpc-data: --max-depth 1' in box.logged()
    assert 'beta: no rclone artifact store declared' in out
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
    src = box.root / 'repos'
    start, served = len(box.logged()), []
    assert _tick(box, 'alpha', served) == 0
    [(argv, cwd, logged)] = served
    assert cwd == src / 'alpha'
    assert argv == deploy_spec.host_serve_argv(), 'the HOST kit serves; the repo venv only runs its producers'
    before = logged[start:]
    assert f'git -C {src / "alpha"} checkout -q -f -B trunk' in before
    assert '--reinstall-package' not in before, 'a served venv is exactly its lock'


def test_only_the_lab_commons_tick_writes_the_shared_kit_checkout(box: Box) -> None:
    """ONE WRITER OF THE SHARED KIT (Ada 2026-10-19): every repo's tick used to update ``~/src/dev-lab``.

    Each tick holds only its OWN repo's flock, so two ticks checked the kit out at once and one died on
    ``.git/index.lock``. The planted concurrent update: the kit's own tick is mid-checkout (its index.lock
    held) while alpha and beta tick together -- neither touches the kit, both serve, and the kit's own
    tick is the one that refreshes it.
    """
    assert box.run(*DECLARE) == 0
    kit = box.root / 'repos' / 'dev-lab'
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
    assert f'git -C {kit} checkout -q -f -B trunk' in box.logged()[start:], "the kit's own tick refreshes it"


def test_a_repo_whose_refresh_fails_is_released_by_name_and_its_forge_never_runs(
    box: Box, capsys: pytest.CaptureFixture[str]
) -> None:
    assert box.run(*DECLARE) == 0
    _write(box.root / 'repos' / 'alpha' / 'pyproject.toml', '[project]\nname = "alpha"\n')
    capsys.readouterr()
    served: list[tuple[list[str], Path, str]] = []
    assert _tick(box, 'alpha', served) == 2
    assert served == []
    assert 'alpha released, not served this tick' in capsys.readouterr().err
    assert _tick(box, 'beta', served) == 0, 'one repo released never stops another'


def test_a_tick_whose_refresh_spent_its_wall_serves_nothing_and_says_so(
    box: Box, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """PLANTED CONTROL beside it: the same tick with time left serves, handing the serve its wall."""
    assert box.run(*DECLARE) == 0
    record = tmp_path / 'alpha.lock.holder'
    tickholder.write(record, tickholder.Holder(1, None, '2026-11-23T09:57:00+00:00', 0.0, 'alpha'))
    served: list[object] = []

    def run(_argv: list[str], **kw: object) -> _Done:
        served.append(kw['wall'])
        return _Done(0)

    spent = tickwall.Wall(record, 0.0)
    capsys.readouterr()
    assert tick.tick('alpha', home=box.home, config=box.machine, tools=box.tools, run=run, wall=spent) == tickwall.WALL
    assert served == []
    assert re.search(r'tick: ended at its wall after \d+ s doing refreshing alpha', capsys.readouterr().err)
    left = tickwall.Wall(record, 3600.0)
    assert tick.tick('alpha', home=box.home, config=box.machine, tools=box.tools, run=run, wall=left) == 0
    assert served == [left]
    assert tickholder.read(record).phase == 'serving alpha'


def test_the_tick_wall_is_the_schedule_tick_wall_default_40_minutes(tmp_path: Path) -> None:
    assert _cron_spec('', tmp_path).tick_wall == deploy_spec.DEFAULT_TICK_WALL == 40 * 60
    assert _cron_spec('\n[schedule]\ntick_wall = "25 min"\n', tmp_path).tick_wall == 25 * 60
    assert _cron_spec('\n[schedule]\ntick_wall = "1 h"\n', tmp_path).tick_wall == 3600


@pytest.mark.parametrize(
    ('wall', 'named'),
    [
        ('"0 min"', 'must be positive'),
        ('"-5 min"', 'must be positive'),
        ('"40"', 'bare number'),
        ('40', 'bare number'),
        ('"90 s"', 'whole minutes'),
        ('"40 GiB"', 'not a duration'),
    ],
)
def test_a_tick_wall_that_is_no_positive_whole_minute_duration_is_refused(
    tmp_path: Path, wall: str, named: str
) -> None:
    with pytest.raises(ValueError, match=rf'\[schedule\] tick_wall = .*{named}'):
        _cron_spec(f'\n[schedule]\ntick_wall = {wall}\n', tmp_path)


def test_the_retired_tick_keys_are_refused_with_their_new_line(tmp_path: Path) -> None:
    """FORMATS-MIGRATE-ONCE (user ruling 2026-11-25): the old keys are never read; the refusal is the migration."""
    with pytest.raises(ValueError, match=r'tick_minutes = 15 is retired.*write tick = "15 min"'):
        _cron_spec('\n[schedule]\ntick_minutes = 15\n', tmp_path)
    with pytest.raises(ValueError, match=r'tick_wall_minutes = 25 is retired.*write tick_wall = "25 min"'):
        _cron_spec('\n[schedule]\ntick_wall_minutes = 25\n', tmp_path)


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


def _cron_spec(text: str, tmp_path: Path) -> deploy_spec.Deployment:
    lab = deploy_spec.Repo(deploy_spec.KIT, f'{URL}/dev-lab.git', 'trunk')
    repos = (lab, deploy_spec.Repo('a', URL, 'r'))
    base = deploy_spec.render(deploy_spec.Deployment('h', '/r/src', '3.13', repos, role=deploy_spec.VERIFICATION))
    spec = deploy_spec.load(_write(tmp_path / 'config.toml', base + text))
    assert spec is not None
    return spec


def test_the_cron_period_is_the_schedule_tick_staggered_per_account(tmp_path: Path) -> None:
    """HPC pressure (2026-10-26): one period, ``[schedule] tick`` -- the one the host card is judged by.

    Each account's minute offset is derived from its home, so accounts do not tick in lockstep.
    PLANTED CONTROL: undeclared, the period is the schedule's one default (5).
    """
    spec = _cron_spec('\n[schedule]\ntick = "15 min"\n', tmp_path)
    assert spec.tick == 15 * 60
    offsets = set()
    for user in ('alice', 'bob', 'carol', 'dave', 'erin', 'frank'):
        lines = deploy_spec.cron_lines(spec, Path('/home') / user)
        assert len({line.split(' ', 1)[0] for line in lines}) == 1, 'one account ticks its repos together'
        minute = lines[0].split(' ', 1)[0]
        offset, _, step = minute.partition('-59/')
        assert step == '15', minute
        assert 0 <= int(offset) < 15, minute
        assert lines == deploy_spec.cron_lines(spec, Path('/home') / user), 'deterministic'
        offsets.add(offset)
    assert len(offsets) > 1, 'accounts are staggered'
    assert _cron_spec('', tmp_path).tick == 5 * 60


@pytest.mark.parametrize('period', ['"7 min"', '"0 min"', '"2.5 min"', '"15"', '15', '"90 s"'])
def test_a_tick_period_cron_cannot_keep_is_refused(tmp_path: Path, period: str) -> None:
    with pytest.raises(ValueError, match=r'\[schedule\] tick = '):
        _cron_spec(f'\n[schedule]\ntick = {period}\n', tmp_path)


def test_an_actions_repo_is_kept_fresh_but_its_queue_is_never_served(
    box: Box, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Serving is the family's binding (D73), never a flag in the account's file.

    A checkout with no role bound to an HPC executor is ticked -- refreshed, the kit's own tick the one writer of the
    kit -- and never served. PLANTED CONTROL: alpha, bound to the HPC, is served.
    """
    assert box.run(*DECLARE) == 0
    bound = {'alpha': HPC_REPO}
    monkeypatch.setattr(deploy_spec, 'roles_at', lambda checkout: bound.get(checkout.name, EVERY_CI))
    spec = deploy_spec.load(box.machine)
    assert spec is not None
    assert deploy_spec.served(spec) == {'alpha'}
    assert deploy_spec.load(_write(tmp_path / 'again.toml', deploy_spec.render(spec))) == spec
    served: list[tuple[list[str], Path, str]] = []
    assert _tick(box, 'dev-lab', served) == 0
    assert _tick(box, 'beta', served) == 0
    assert served == [], 'an actions repo is refreshed, never served'
    assert _tick(box, 'alpha', served) == 0
    assert len(served) == 1


def test_a_repo_row_declaring_the_retired_serve_flag_is_refused_by_name(box: Box) -> None:
    assert box.run(*DECLARE) == 0
    text = box.machine.read_text(encoding='utf-8')
    box.machine.write_text(text.replace('beta.git", ref = "trunk" }', 'beta.git", ref = "trunk", serve = true }'))
    with pytest.raises(ValueError, match=r'beta declare serve, which is retired.*family binds'):
        deploy_spec.load(box.machine)


def test_a_checkout_whose_roles_are_unbound_is_released_by_name(
    box: Box, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Every wall teaches: an unbound repo is named on the tick; one bound to CI is refreshed, never served."""
    assert box.run(*DECLARE) == 0
    pyproject = box.root / 'repos' / 'beta' / 'pyproject.toml'
    served: list[tuple[list[str], Path, str]] = []
    _write(pyproject, '[tool.lab_commons.hpc]\n')
    carry(monkeypatch, EVERY_CI)
    assert _tick(box, 'beta', served) == 0, 'PLANTED CONTROL: every role on CI -- refreshed, not served'
    monkeypatch.delenv(ROLES_ENV)
    monkeypatch.delenv('CI', raising=False)  # a tick is no CI job; under a runner's CI the stale-workflow door speaks
    capsys.readouterr()
    assert _tick(box, 'beta', served) == 2
    assert served == []
    assert 'the roles binding lives in the family layer' in capsys.readouterr().err


def _as_role(box: Box, role: str | None) -> None:
    """Rewrite the stored ``[deploy] role`` as *role*; ``None`` removes the key."""
    table = tomllib.loads(box.machine.read_text(encoding='utf-8'))  # the grant's own role is the declaration's
    table['deploy'].pop('role', None)
    if role is not None:
        table['deploy']['role'] = role
    box.machine.write_text(dumps(table), encoding='utf-8')


def _marked(box: Box) -> set[str]:
    lines = box.crontab.read_text(encoding='utf-8').splitlines() if box.crontab.exists() else []
    return {line.rsplit(deploy_spec.MARK, 1)[1] for line in lines if deploy_spec.MARK in line}


def test_a_research_account_carries_no_serve_line_and_leaves_crontab_untouched(
    box: Box, capsys: pytest.CaptureFixture[str]
) -> None:
    """User ruling 2026-11-06: only a Forge Verification account serves; a research deploy never touches crontab.

    A role switched away from verification drops its lines through the explicit door (``deploy --remove``).
    PLANTED CONTROL: verification writes them.
    """
    _write(box.crontab, '0 1 * * * echo mine\n')
    assert box.run(*DECLARE) == 0
    assert _marked(box) == {'dev-lab', 'alpha', 'beta'}, 'the planted control: a verification account serves'
    _as_role(box, deploy_spec.RESEARCH)
    capsys.readouterr()
    box.calls.unlink(missing_ok=True)
    assert box.run() == 0
    calls = box.logged()
    assert 'crontab' not in calls
    assert 'hpcaccount tick' not in calls, 'a research account is never ticked'
    assert 'fetch -q origin' in calls, 'its checkouts are still kept for research'
    assert box.run('--remove') == 0
    assert _marked(box) == set()
    assert box.crontab.read_text(encoding='utf-8') == '0 1 * * * echo mine\n', 'every other line kept'


def test_a_research_deploy_asks_only_to_read(box: Box, capsys: pytest.CaptureFixture[str]) -> None:
    """A research account never serves, so a token without tick scopes is no refusal (2026-11-15).

    PLANTED CONTROL: the same refusing API on a verification account still refuses, naming the scopes.
    """
    assert box.run(*DECLARE) == 0
    box.refused_api['dev-lab'] = 'a tick needs a token with the scopes repository (read and write)'
    assert box.run() == 2
    assert 'repository (read and write)' in capsys.readouterr().err, 'the planted control: verification refuses'
    _as_role(box, deploy_spec.RESEARCH)
    box.calls.unlink(missing_ok=True)
    assert box.run() == 0
    out = capsys.readouterr().out
    assert 'not served here: read access only' in out
    assert 'git ls-remote' in box.logged(), 'read access is still checked'


def test_a_research_deploy_without_read_access_is_still_refused(
    box: Box, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    assert box.run(*DECLARE) == 0
    _as_role(box, deploy_spec.RESEARCH)
    monkeypatch.setenv('FAKE_GIT_DENY', '/beta.git')
    capsys.readouterr()
    box.calls.unlink(missing_ok=True)
    assert box.run() == 2
    assert 'no read access to beta' in capsys.readouterr().err
    assert 'clone' not in box.logged()
    assert 'fetch' not in box.logged()


def test_an_undeclared_role_is_refused_naming_the_key_and_nothing_changes(
    box: Box, capsys: pytest.CaptureFixture[str]
) -> None:
    assert box.run(*DECLARE) == 0
    before = box.crontab.read_text(encoding='utf-8')
    _as_role(box, None)
    capsys.readouterr()
    box.calls.unlink(missing_ok=True)
    assert box.run() == 2
    err = capsys.readouterr().err
    assert '[deploy] role is undeclared' in err
    assert str(box.machine) in err
    assert box.crontab.read_text(encoding='utf-8') == before
    assert 'crontab -' not in box.logged()


def test_a_malformed_role_is_refused_naming_the_key(tmp_path: Path) -> None:
    lab = deploy_spec.Repo(deploy_spec.KIT, f'{URL}/dev-lab.git', 'trunk')
    text = deploy_spec.render(deploy_spec.Deployment('h', '/r/src', '3.13', (lab,), role='Not A Name'))
    with pytest.raises(ValueError, match=r"\[deploy\] role .* is 'Not A Name'"):
        deploy_spec.load(_write(tmp_path / 'config.toml', text))


def test_a_role_beyond_the_defaults_needs_the_workstations_table(box: Box, capsys: pytest.CaptureFixture[str]) -> None:
    """A hand-run deploy knows only the shipped defaults. PLANTED CONTROL: deploy-fleet passes the table."""
    assert box.run(*DECLARE) == 0
    _as_role(box, 'batch')
    capsys.readouterr()
    assert box.run() == 2
    assert 'deploy-fleet' in capsys.readouterr().err
    box.calls.unlink(missing_ok=True)
    assert box.run(*_fleet('batch', serves=False, read_only=True)) == 0
    assert 'crontab' not in box.logged(), 'its table says it does not serve: no scheduler step at all'


def test_a_serve_tick_on_a_research_account_refuses_naming_the_role(
    box: Box, capsys: pytest.CaptureFixture[str]
) -> None:
    """A stale cron line surviving on a research account never serves. PLANTED CONTROL: verification serves."""
    assert box.run(*DECLARE) == 0
    served: list[tuple[list[str], Path, str]] = []
    assert _tick(box, 'alpha', served) == 0
    assert len(served) == 1, 'the planted control: a verification tick serves'
    _as_role(box, deploy_spec.RESEARCH)
    capsys.readouterr()
    assert _tick(box, 'alpha', served) == 2
    assert len(served) == 1, 'nothing served'
    assert 'role is research' in capsys.readouterr().err


def test_a_checkout_lives_in_the_declared_roots_repos(tmp_path: Path) -> None:
    """A compute node may not see home: the root is the cluster's declared one, ``<root>/repos/<name>``."""
    alpha = deploy_spec.Repo('alpha', f'{URL}/alpha.git', 'trunk')
    spec = deploy_spec.Deployment('h', '/work/project/user', '3.13', (alpha,), role=deploy_spec.RESEARCH)
    assert deploy_spec.load(_write(tmp_path / 'config.toml', deploy_spec.render(spec))) == spec
    assert deploy_spec.checkout_of(spec, alpha).as_posix() == '/work/project/user/repos/alpha'


@pytest.mark.parametrize('root', ['', '.local/share/lab-forge/repos', '~/lab'])
def test_an_undeclared_or_home_relative_root_is_refused_by_name(root: str, tmp_path: Path) -> None:
    """PLANTED CONTROL for the one above: no default root, no home-relative root -- the declaration is the source."""
    alpha = deploy_spec.Repo('alpha', f'{URL}/alpha.git', 'trunk')
    text = deploy_spec.render(deploy_spec.Deployment('h', '/r', '3.13', (alpha,), role=deploy_spec.RESEARCH))
    text = text.replace('root = "/r"', f'root = "{root}"')
    with pytest.raises(ValueError, match='root'):
        deploy_spec.load(_write(tmp_path / 'config.toml', text))


def _fleet(role: str, **table: object) -> tuple[str, ...]:
    return ('--fleet-role', role, '--role-table', json.dumps(table))


@pytest.mark.parametrize('write', ['push', 'admin'])
def test_a_read_only_role_pulling_with_a_writer_is_refused_naming_the_login(
    box: Box, write: str, capsys: pytest.CaptureFixture[str]
) -> None:
    """User rulings 2026-11-09: research (shipped read_only) refuses. PLANTED CONTROL: a reader passes."""
    assert box.run(*DECLARE) == 0
    _as_role(box, deploy_spec.RESEARCH)
    capsys.readouterr()
    assert box.run() == 0, 'the planted control: a reader passes'
    box.identity.update({'login': 'rw-login', write: True})
    capsys.readouterr()
    assert box.run() == 2
    err = capsys.readouterr().err
    assert 'rw-login' in err
    assert 'read-only' in err


def test_a_role_that_is_not_read_only_reports_its_writer(box: Box, capsys: pytest.CaptureFixture[str]) -> None:
    box.identity.update({'login': 'rw-login', 'push': True})
    assert box.run(*DECLARE) == 0
    out = capsys.readouterr().out
    assert 'rw-login' in out
    assert 'report only' in out


def test_the_roles_declared_reader_must_be_the_identity(box: Box, capsys: pytest.CaptureFixture[str]) -> None:
    """PLANTED CONTROL: the role's reader itself passes; another read-only login is refused by name."""
    assert box.run(*DECLARE) == 0
    _as_role(box, deploy_spec.RESEARCH)
    table = {'serves': False, 'read_only': True, 'reader': 'ro-login'}
    assert box.run(*_fleet('research', **table)) == 0
    box.identity['login'] = 'other-ro-login'
    capsys.readouterr()
    assert box.run(*_fleet('research', **table)) == 2
    err = capsys.readouterr().err
    assert 'other-ro-login' in err
    assert 'ro-login' in err


def test_an_account_role_other_than_the_workstations_is_refused_naming_both(
    box: Box, capsys: pytest.CaptureFixture[str]
) -> None:
    """The workstation is the source. PLANTED CONTROL: the equal role deploys."""
    assert box.run(*DECLARE) == 0
    assert box.run(*_fleet('verification', serves=True, read_only=False)) == 0
    capsys.readouterr()
    assert box.run(*_fleet('research', serves=False, read_only=True)) == 2
    err = capsys.readouterr().err
    assert "'verification'" in err
    assert "'research'" in err


def _alias_declare(role: str) -> tuple[str, ...]:
    """A declaration whose ``--host`` is the grant's login ALIAS, one DNS name round-robining over several nodes."""
    aliased = Grant(
        user='alice', hosts=('login.example',), slurm_account='acct-free', partitions=('shortq', 'defq'),
        role=role, cluster_name='int',
    )  # fmt: skip
    return (
        '--host', 'login.example', *LAB, '--repo', f'alpha={URL}/alpha.git@trunk',
        '--partition', 'shortq', '--partition', 'defq', '--role', role,
        '--grant-table', json.dumps(grant_slice(aliased)),
    )  # fmt: skip


def test_a_research_deploy_through_the_login_alias_passes_on_any_node_and_records_the_alias(box: Box) -> None:
    """A research account installs no cron line, so it needs no node pin: its host is the grant's alias."""
    assert box.run(*_alias_declare(deploy_spec.RESEARCH), host='login04.int.cluster') == 0
    assert deploy_spec.load(box.machine).host == 'login.example'
    assert box.run(host='login07.int.cluster') == 0, 'the alias landed on another node: still the same account'


def test_a_verification_deploy_through_the_login_alias_keeps_the_node_pin(
    box: Box, capsys: pytest.CaptureFixture[str]
) -> None:
    """PLANTED CONTROL: cron is per node, so a serving account still refuses, naming the node it is on."""
    assert box.run(*_alias_declare('verification'), host='login04.int.cluster') == 2
    err = capsys.readouterr().err
    assert 'this is login04' in err
    assert 'login.example' in err
    assert not box.machine.exists()


def test_a_research_deploy_naming_a_host_outside_its_grant_is_refused(
    box: Box, capsys: pytest.CaptureFixture[str]
) -> None:
    """PLANTED CONTROL: the waiver is for the grant's own login hosts, never an arbitrary name."""
    argv = list(_alias_declare(deploy_spec.RESEARCH))
    argv[1] = 'elsewhere.example'
    assert box.run(*argv, host='login04.int.cluster') == 2
    assert 'elsewhere.example' in capsys.readouterr().err
    assert not box.machine.exists()


@pytest.fixture(autouse=True)
def _hpc_repo(monkeypatch: pytest.MonkeyPatch) -> None:
    """These repos are served by an HPC executor: the family binds tests, merge and prune there (planted)."""
    carry(monkeypatch, HPC_REPO)


def test_a_cloned_repo_this_account_does_not_serve_is_read_with_the_stored_reader(
    box: Box, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A private forge repo answers no anonymous read, served here or not.

    Measured 2026-11-20 on two research accounts: once the two private product repos were cloned, their checkouts
    declared no role bound here, so the deploy's ``git ls-remote`` ran with ``credential.helper=`` emptied and the
    private forge refused it (exit 128) though the stored server-reader answered. Every repo is read with the
    account's own helper. PLANTED CONTROL: the same account's refused read is still refused.
    """
    assert box.run(*DECLARE) == 0
    _as_role(box, deploy_spec.RESEARCH)
    monkeypatch.setattr(deploy_spec, 'roles_at', lambda _checkout: EVERY_CI)  # every cloned checkout: unserved here
    box.calls.unlink(missing_ok=True)
    assert box.run() == 0
    remote = [line for line in box.logged().splitlines() if 'ls-remote' in line]
    assert remote
    assert all('credential.helper=' not in line for line in remote)
    monkeypatch.setenv('FAKE_GIT_DENY', '/beta.git')
    assert box.run() == 2


def test_a_research_deploy_has_nothing_of_serving(
    box: Box, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A research account never serves, so its deploy has no cron, no tick, no serve-git proof and no CI-PAUSED gate.

    User, 2026-11-20: "why would a research host need cron?" Measured the same day on Cirrus: ``crontab -l`` -- which
    the cluster forbids -- refused a research deploy that wanted zero lines. A research deploy is the kit, its
    declared repos, their venvs and the reader check. PLANTED CONTROL: a verification account on the same box still
    reads crontab, and is refused when it cannot.
    """
    assert box.run(*DECLARE) == 0
    monkeypatch.setenv('FAKE_CRONTAB_FORBID', '1')
    capsys.readouterr()
    assert box.run() == 2, 'the planted control: a serving account cannot place its lines'
    assert 'not allowed' in capsys.readouterr().err
    _as_role(box, deploy_spec.RESEARCH)
    (box.home / '.cache' / 'dev-lab').mkdir(parents=True, exist_ok=True)
    (box.home / '.cache' / 'dev-lab' / 'CI-PAUSED').write_text('paused by the fleet\n', encoding='utf-8')
    box.calls.unlink(missing_ok=True)
    assert box.run() == 0
    out = capsys.readouterr().out
    calls = box.logged()
    assert 'crontab' not in calls
    assert '[cron]' not in out
    assert '[tick]' not in out
    assert 'merge-tree' not in calls
    assert 'fetch -q origin' in calls, 'its checkouts are still kept for research'


def test_a_machine_file_without_a_root_deploys_at_the_root_its_grant_table_declares(tmp_path: Path) -> None:
    """Measured 2026-11-20: every rendered account [deploy] names no root (the family's cluster holds it).

    The deploy refused "no root declared" on every account though deploy-fleet handed it the cluster's root in
    ``--grant-table``. PLANTED CONTROL: with no grant table the same file is still refused, naming the root.
    """
    machine = _write(
        tmp_path / 'machine.toml',
        '[deploy]\nhost = "login02"\nrepos = [{ name = "dev-lab", url = "https://x/dev-lab.git", ref = "main" }]\n',
    )
    rooted = replace(DECLARED, root='/r/declared/lab')
    args = parser().parse_args(['--grant-table', json.dumps(grant_slice(rooted))])
    spec = declaration(args, machine)
    assert not isinstance(spec, str), spec
    assert spec.root == '/r/declared/lab'
    with pytest.raises(ValueError, match='no root declared'):
        declaration(parser().parse_args([]), machine)
