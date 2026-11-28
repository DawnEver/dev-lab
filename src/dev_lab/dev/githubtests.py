"""GITHUB-TESTS-ON-ACTIONS: a repo hosted on github.com is tested by GitHub Actions alone (user ruling 2026-11-27).

The ruling, repeated many times before it became this mechanism: no host -- an HPC account, an ops host, a
workstation -- ever produces a test part of a GitHub repo. Every place that could make one is refused by name:

* the family's roles binding (:func:`family_refusals`): ``[roles.github] tests``, or a GitHub repo's
  ``[roles.repos."<owner>/<repo>"] tests``, bound to anything but ``"ci"``;
* an HPC account's ``[deploy] repos`` row (:func:`account_refusals`): a GitHub repo the family binds a role of to
  THIS account's grant -- the account would serve its queue -- unless the row claims nothing (``claims = "none"``);
* the repo itself (:func:`dev_lab.dev.rolecheck.repo_refusals`): a required part GitHub Actions does not post.

A Gitea repo is untouched: its tests may be bound to a cluster or a host. The forge of a repo is read from its remote
(:func:`dev_lab.dev._forgebackends.backend_for`), the family's ``[family_repos]`` being the one list of remotes.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from typing import Any, Final

from dev_lab.dev._forgebackends import backend_for
from dev_lab.dev.accounthost import grant_of
from dev_lab.dev.forge import UnreadableRemote, forge_of_url
from dev_lab.dev.roles import CI, HPC, ROLES, TESTS, Unbound, binding, executor_from

__all__ = ['DOOR', 'FORGE', 'RULE', 'account_refusals', 'family_refusals', 'on_github']

#: The rule's registered id (``dev_lab.dev.rules``).
RULE: Final = 'GITHUB-TESTS-ON-ACTIONS'
#: The forge kind the rule binds, as :mod:`dev_lab.dev.roles` names it.
FORGE: Final = 'github'
#: Where a GitHub repo's part that needs more than the base job goes instead of onto a host.
DOOR: Final = 'its parts come from GitHub Actions: declare them in [tool.dev_lab.parts] hosted'


def _slug(url: str) -> str | None:
    """``<owner>/<repo>`` of a remote *url* hosted on github.com; ``None`` for another forge or an unreadable url."""
    try:
        forge = forge_of_url(url)
    except UnreadableRemote:
        return None
    return f'{forge.owner}/{forge.repo}' if backend_for(forge).name == FORGE else None


def on_github(url: str) -> bool:
    """Whether the remote *url* is a repo hosted on github.com."""
    return _slug(url) is not None


def _github_repos(layer: Mapping[str, Any]) -> Iterator[str]:
    rows: Mapping[str, Mapping[str, Any]] = layer.get('family_repos', {})
    for row in rows.values():
        if slug := _slug(str(row.get('remote', ''))):
            yield slug


def family_refusals(layer: Mapping[str, Any]) -> list[str]:
    """Every ``tests`` binding of *layer* that puts a GitHub repo's tests anywhere but GitHub Actions."""
    found: list[str] = []
    forge_table: Mapping[str, Any] = layer.get('roles', {}).get(FORGE, {})
    seen: set[str] = set()
    if TESTS in forge_table:
        try:
            executor = executor_from(forge_table[TESTS], f'[roles.{FORGE}] {TESTS}')
        except Unbound:
            executor = None  # malformed: roles.host_refusals / the render names it
        if executor is not None and executor.kind != CI:
            seen.add(f'[roles.{FORGE}] {TESTS}')
            found.append(
                f'[roles.{FORGE}] {TESTS} = {executor}: a GitHub repo is tested only by GitHub Actions ({RULE}) -- '
                f'bind {TESTS} = "{CI}"; {DOOR}'
            )
    for repo in _github_repos(layer):
        try:
            where, executor = binding(layer, FORGE, repo, TESTS)
        except Unbound:
            continue
        if executor.kind != CI and where not in seen:
            found.append(
                f'{where} = {executor}: {repo} is on github.com, tested only by GitHub Actions ({RULE}) -- '
                f'bind {TESTS} = "{CI}" or delete the override; {DOOR}'
            )
    return found


def account_refusals(name: str, host: Mapping[str, Any], layer: Mapping[str, Any]) -> list[str]:
    """Every ``[deploy] repos`` row of account file *name* (parsed: *host*) that would serve a GitHub repo's queue."""
    grant = grant_of(name, layer)
    if grant is None:
        return []  # accounthost.check names a file of no grant
    found: list[str] = []
    rows: list[Mapping[str, Any]] = host.get('deploy', {}).get('repos', [])
    for row in rows:
        repo = _slug(str(row.get('url', '')))
        if repo is None or row.get('claims') == 'none':
            continue
        for role in ROLES:
            try:
                where, executor = binding(layer, FORGE, repo, role)
            except Unbound:
                continue
            here = executor.cluster == grant.get('cluster') and executor.grant_role == grant.get('role')
            if executor.kind == HPC and here:
                found.append(
                    f'{name}: [deploy] repos {row.get("name", repo)} ({repo}) would be served here -- {where} = '
                    f'{executor} binds it to this account, yet a GitHub repo is tested only by GitHub Actions '
                    f'({RULE}): bind its roles off this grant, or declare claims = "none" on the row; {DOOR}'
                )
                break
    return found
