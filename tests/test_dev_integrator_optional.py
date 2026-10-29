"""The integration-branch flow is OPT-IN: present only where ``[tool.dev_lab.integrator]`` is declared.

A repo that declares no integrator table (a public GitHub repo on ``main`` alone) has no integration branch:
its trunk is ``main``, its PRs target ``main``, and every integration rule is ABSENT -- not refusing, not
warning. Each absence has its planted control: the same repo declaring the table gets the gate back.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from dev_lab.dev import forgecli, pradmit
from dev_lab.dev.famtests.branchset import BranchSetViolation, assert_the_pr_flow_is_declared
from dev_lab.dev.lanepolicy import load_policy, policy_from
from dev_lab.dev.pushgate import INTEGRATION, LANE, destination_of
from dev_lab.dev.rules import RULES, rules_by_id
from dev_lab.dev.sessionbranch import refusals

_GIT = shutil.which('git') or 'git'
_ZERO = '0' * 40
_BRANCHSET = "[tool.dev_lab.branchset]\ntrunk = 'main'\nsessions = ['integrate/main']\nephemeral = ['pr/*']\n"
_DECLARED = "[tool.dev_lab.integrator]\nintegration = 'integrate/main'\n"
#: The rules that exist only where an integration branch is declared.
_CONDITIONAL = frozenset(
    {
        'DOWNSTREAM-SYNCS-INTEGRATION',
        'TRUNK-MOVES-BY-FAST-FORWARD',
        'PRS-TARGET-INTEGRATION',
        'INTEGRATION-IS-MERGES-ONLY',
        'INTEGRATION-TAKES-ONLY-FORGE-MERGES',
        'MERGE-RESOLUTION-DECLARED',
    }
)


def _git(cwd: Path, *args: str) -> str:
    done = subprocess.run(
        [_GIT, '-c', 'user.name=t', '-c', 'user.email=t@t', '-c', 'core.hooksPath=', *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding='utf-8',
        check=True,
        timeout=60,
    )
    return done.stdout.strip()


def _repo(tmp_path: Path, manifest: str) -> tuple[Path, str]:
    _git(tmp_path, 'init', '-b', 'main', '.')
    (tmp_path / 'pyproject.toml').write_text(manifest, encoding='utf-8')
    _git(tmp_path, 'add', 'pyproject.toml')
    _git(tmp_path, 'commit', '-m', 'chore: seed')
    return tmp_path, _git(tmp_path, 'rev-parse', 'HEAD')


def test_an_undeclared_repo_has_no_integration_branch_and_its_prs_target_main(tmp_path: Path) -> None:
    policy = load_policy(tmp_path)
    assert (policy.integration, policy.declared, policy.pr_base) == ('', False, 'main')


def test_a_declared_repo_names_its_integration_branch_and_its_prs_target_it() -> None:
    policy = policy_from(_DECLARED, 'p')
    assert (policy.integration, policy.declared, policy.pr_base) == ('integrate/main', True, 'integrate/main')


def test_a_declared_table_without_an_integration_name_is_refused() -> None:
    with pytest.raises(ValueError, match='integration'):
        policy_from("[tool.dev_lab.integrator]\ntrunk = 'main'\n", 'p')


def test_an_undeclared_repo_pushes_a_plain_commit_to_a_session_branch_unjudged(tmp_path: Path) -> None:
    """INTEGRATION-IS-MERGES-ONLY is absent: the same push a declared repo refuses (control below) lands."""
    root, sha = _repo(tmp_path, _BRANCHSET)
    assert refusals(root, f'refs/heads/integrate/main {sha} refs/heads/integrate/main {_ZERO}\n') == []


def test_a_declared_repo_refuses_that_push(tmp_path: Path) -> None:
    root, sha = _repo(tmp_path, _BRANCHSET + _DECLARED)
    found = refusals(root, f'refs/heads/integrate/main {sha} refs/heads/integrate/main {_ZERO}\n')
    assert any('INTEGRATION-IS-MERGES-ONLY' in line for line in found), found


def test_the_pushgate_has_no_integration_destination_in_an_undeclared_repo() -> None:
    undeclared, declared = policy_from('', 'p'), policy_from(_DECLARED, 'p')
    assert destination_of('refs/heads/integrate/main', undeclared) == LANE
    assert destination_of('refs/heads/integrate/main', declared) == INTEGRATION


def test_an_undeclared_repo_needs_no_integration_session_in_its_branch_set(tmp_path: Path) -> None:
    (tmp_path / 'pyproject.toml').write_text(
        "[tool.dev_lab.branchset]\ntrunk = 'main'\nsessions = []\nephemeral = ['pr/*']\n", encoding='utf-8'
    )
    assert_the_pr_flow_is_declared(root=tmp_path)
    (tmp_path / 'pyproject.toml').write_text(
        "[tool.dev_lab.branchset]\ntrunk = 'main'\nsessions = []\nephemeral = ['pr/*']\n" + _DECLARED,
        encoding='utf-8',
    )
    with pytest.raises(BranchSetViolation, match='integrate/main'):
        assert_the_pr_flow_is_declared(root=tmp_path)


@pytest.mark.parametrize(('manifest', 'base'), [('', 'main'), (_DECLARED, 'integrate/main')])
def test_forge_pr_create_defaults_its_base_to_the_declared_flow(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, manifest: str, base: str
) -> None:
    (tmp_path / 'pyproject.toml').write_text(manifest, encoding='utf-8')
    opened: list[str] = []

    def create(title: str, _body: str, *, head: str, base: str) -> SimpleNamespace:
        opened.append(f'{head}->{base}')
        return SimpleNamespace(number=1, state='open', title=title, url='u')

    monkeypatch.setattr(forgecli, 'client_for', lambda *_a, **_k: SimpleNamespace(pr_create=create))
    monkeypatch.setattr(pradmit, 'create_advice', lambda *_a, **_k: ())
    assert forgecli.issue_and_pr(['pr', 'create', '--title', 't', '--head', 'pr/x'], cwd=tmp_path) == 0
    assert opened == [f'pr/x->{base}']


@pytest.mark.parametrize('rule', sorted(_CONDITIONAL))
def test_each_integration_rule_says_where_it_applies(rule: str) -> None:
    assert '[tool.dev_lab.integrator]' in rules_by_id(RULES)[rule].statement
