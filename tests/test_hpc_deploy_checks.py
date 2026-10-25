"""The deploy's account checks: the credential store, the tools on the tick PATH, and the grant."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Final

import pytest

from dev_lab.dev.hpchost import checks as deploy_checks
from dev_lab.dev.hpchost.spec import Deployment, Repo

URL: Final = 'https://forge.example.org/o/r.git'


@pytest.mark.parametrize(
    ('helper', 'exists', 'mode', 'fix'),
    [
        ('', True, 0o600, 'git config --global credential.helper store'),
        ('store', False, 0o600, 'is missing'),
        ('store', True, 0o640, 'chmod 600'),
        ('store', True, 0o600, ''),
        ('manager', False, 0o644, ''),  # another helper keeps its secret elsewhere
    ],
)
def test_the_credential_store_must_be_configured_and_private(
    tmp_path: Path, helper: str, *, exists: bool, mode: int, fix: str
) -> None:
    store = tmp_path / '.git-credentials'
    if exists:
        store.write_text('x', encoding='utf-8')
    problem = deploy_checks.store_problem(helper, store, mode=mode if exists else None)
    assert (fix in problem) if fix else problem == ''


def test_uv_is_always_needed_and_each_tool_is_installed_or_refused() -> None:
    """PLANTED CONTROL: a box that has everything installs nothing and refuses nothing."""
    installs, refused = deploy_checks.tool_plan(['cargo', 'cmake', 'cc'], found=lambda _t: False)
    assert [tool for tool, _script in installs] == ['uv', 'cargo', 'cmake'], 'uv first: cmake comes through it'
    assert refused == ['cc']
    assert deploy_checks.tool_plan(['cargo', 'cc'], found=lambda _t: True) == ([], [])


#: A fake shell: its one argument is the command line; a tool runs when its name starts with "good".
_RUNS_GOOD: Final = 'import sys; sys.exit(0 if sys.argv[1].split("; ")[-1].startswith("good") else 1)'
FAKE_SH: Final = (sys.executable, '-c', _RUNS_GOOD)


def test_a_tool_is_present_when_its_version_runs_in_the_tick_environment() -> None:
    """Capability, not lookup: a rustup shim with no toolchain is on the PATH and fails ``--version``."""
    assert deploy_checks.runs(FAKE_SH, 'PATH=/x', 'good-tool')
    assert not deploy_checks.runs(FAKE_SH, 'PATH=/x', 'shim')
    assert not deploy_checks.runs(('no-such-shell-anywhere',), 'PATH=/x', 'good-tool'), 'a shell that cannot start'


def test_the_login_files_are_the_ones_bash_reads_and_the_line_names_the_tick_installs(tmp_path: Path) -> None:
    assert deploy_checks.login_files(tmp_path) == [tmp_path / '.bash_profile', tmp_path / '.bashrc']
    (tmp_path / '.profile').write_text('', encoding='utf-8')
    assert deploy_checks.login_files(tmp_path) == [tmp_path / '.profile', tmp_path / '.bashrc'], 'never shadow it'
    line = deploy_checks.login_line(tmp_path)
    assert str(tmp_path / '.local/bin') in line
    assert str(tmp_path / '.cargo/bin') in line
    assert line.endswith(deploy_checks.LOGIN_MARK)


SPEC: Final = Deployment('login02', 'src', '3.13', (Repo('dev-lab', URL, 'trunk'),), '', ('shortq', 'defq'))


def test_the_grant_comes_from_slurm_and_the_declaration() -> None:
    grant = deploy_checks.grant_of('alice', 'acct-free|cpu=96,mem=360G\nacct-free|cpu=96\n', spec=SPEC, host='h.x')
    assert grant == {
        'user': 'alice',
        'hosts': ['h.x'],
        'slurm_account': 'acct-free',
        'partitions': ['shortq', 'defq'],
    }


@pytest.mark.parametrize(
    ('sacct', 'spec', 'named'),
    [
        ('a|cpu=1\nb|cpu=2\n', SPEC, '--slurm-account'),
        ('', SPEC, 'no Slurm association'),
        ('a|cpu=1\n', Deployment('h', 'src', '3.13', (), '', ()), '--partition'),
        ('a|cpu=1\n', Deployment('h', 'src', '3.13', (), 'zz', ('q',)), 'zz'),
    ],
)
def test_a_grant_that_cannot_be_derived_is_refused_naming_why(sacct: str, spec: Deployment, named: str) -> None:
    refused = deploy_checks.grant_of('alice', sacct, spec=spec, host='h')
    assert isinstance(refused, str)
    assert named in refused


FAKE_GIT: Final = r"""
import sys
args = sys.argv[2:]
if 'merge-tree' in args:
    if sys.argv[1] == 'old':  # git 2.31.1, measured on Ada 2026-10-17: no --write-tree
        sys.stderr.write('usage: git merge-tree <base-tree> <branch1> <branch2>\n'); sys.exit(129)
    sys.stdout.write('4b825dc642cb6eb9a060e54bf8d69288fbee4904\n')
"""


@pytest.mark.parametrize('version', ['old', 'new'])
def test_the_serve_git_floor_is_proven_by_a_toy_merge_tree_never_by_its_version(tmp_path: Path, version: str) -> None:
    """PLANTED CONTROLS: a git without ``merge-tree --write-tree`` is refused naming why; one with it is accepted."""
    fake = tmp_path / 'git.py'
    fake.write_text(FAKE_GIT, encoding='utf-8')
    why = deploy_checks.merge_tree_refusal([sys.executable, str(fake), version], tmp_path / 'scratch')
    assert (why == '') == (version == 'new'), why
    if version == 'old':
        assert 'usage: git merge-tree' in why


def test_a_git_that_does_not_run_is_refused(tmp_path: Path) -> None:
    assert 'does not run' in deploy_checks.merge_tree_refusal([str(tmp_path / 'absent-git')], tmp_path)
