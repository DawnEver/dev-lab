"""An account ticks only what it serves: :func:`~dev_lab.dev.hpcaccount.spec.ticked` follows ``served()``.

User ruling 2026-11-27 (ONE-LOGIN-POLLER): an HPC account keeps only the Gitea repos it serves, and its one poller
ticks only those -- a repo whose roles the family binds elsewhere is never refreshed or built there, and a repo hosted
on github.com is never ticked at all (GITHUB-TESTS-ON-ACTIONS: GitHub Actions alone tests it).
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Final

import pytest
from _roles_fixtures import EVERY_CI, HPC_REPO

from dev_lab.dev.hpcaccount import cronline
from dev_lab.dev.hpcaccount import spec as deploy_spec
from dev_lab.dev.roles import Roles

FORGE: Final = 'https://forge.example/team'
GITHUB: Final = 'https://github.com/someone'


def _deployment(
    tmp_path: Path, *repos: deploy_spec.Repo, role: str = deploy_spec.VERIFICATION
) -> deploy_spec.Deployment:
    lab = deploy_spec.Repo(deploy_spec.KIT, f'{FORGE}/dev-lab.git', 'trunk')
    spec = deploy_spec.Deployment('h', tmp_path.as_posix(), '3.13', (lab, *repos), role=role)
    for repo in spec.repos:  # cloned: served() reads each checkout's binding
        checkout = deploy_spec.checkout_of(spec, repo)
        checkout.mkdir(parents=True, exist_ok=True)
        (checkout / 'pyproject.toml').write_text('[project]\nname = "x"\n', encoding='utf-8')
    return spec


def _bind(monkeypatch: pytest.MonkeyPatch, bound: dict[str, Roles]) -> None:
    monkeypatch.setattr(deploy_spec, 'roles_at', lambda checkout: bound.get(checkout.name, EVERY_CI))


def _names(repos: tuple[deploy_spec.Repo, ...]) -> list[str]:
    return [repo.name for repo in repos]


def test_only_the_served_repos_are_ticked(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """PLANTED CONTROL: beta bound to CI is not ticked; bound to the HPC it is."""
    alpha = deploy_spec.Repo('alpha', f'{FORGE}/alpha.git', 'trunk')
    beta = deploy_spec.Repo('beta', f'{FORGE}/beta.git', 'trunk')
    spec = _deployment(tmp_path, alpha, beta)
    bound = {'alpha': HPC_REPO}
    _bind(monkeypatch, bound)
    assert _names(deploy_spec.ticked(spec)) == ['alpha']
    bound['beta'] = HPC_REPO
    assert _names(deploy_spec.ticked(spec)) == ['alpha', 'beta']


def test_a_github_hosted_repo_is_never_ticked_even_bound_to_the_hpc(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """PLANTED CONTROL: the same repo on the Gitea forge, with the same binding, is ticked."""
    alpha = deploy_spec.Repo('alpha', f'{FORGE}/alpha.git', 'trunk')
    hosted = deploy_spec.Repo('gamma', f'{GITHUB}/gamma.git', 'trunk')
    spec = _deployment(tmp_path, alpha, hosted)
    _bind(monkeypatch, {'alpha': HPC_REPO, 'gamma': HPC_REPO})
    assert _names(deploy_spec.ticked(spec)) == ['alpha']
    assert ' gamma ' not in cronline.cron_lines(spec, tmp_path)[0]
    moved = replace(spec, repos=(spec.repos[0], alpha, replace(hosted, url=f'{FORGE}/gamma.git')))
    assert _names(deploy_spec.ticked(moved)) == ['alpha', 'gamma']


def test_an_account_that_serves_nothing_has_no_line(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Every repo bound elsewhere: nothing ticked, no cron line. PLANTED CONTROL: a research role, the same."""
    spec = _deployment(tmp_path, deploy_spec.Repo('alpha', f'{FORGE}/alpha.git', 'trunk'))
    _bind(monkeypatch, {})
    assert deploy_spec.ticked(spec) == ()
    assert cronline.cron_lines(spec, tmp_path) == []
    _bind(monkeypatch, {'alpha': HPC_REPO})
    assert len(cronline.cron_lines(spec, tmp_path)) == 1
    research = _deployment(tmp_path, spec.repos[1], role=deploy_spec.RESEARCH)
    assert cronline.cron_lines(research, tmp_path) == []
