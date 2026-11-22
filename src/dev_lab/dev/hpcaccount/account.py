"""The ACCOUNT steps of ``dev_lab.dev.hpcaccount deploy`` -- what is checked or written before anything is installed.

:func:`credentials` checks git's credential helper and its store, every repo's ``git ls-remote`` and the
forge API calls a tick makes (:func:`auth_check`); :func:`grant` writes this account's own
``[[hpc.grant]]`` when the machine file has none. Each reports and is safe to repeat; the pure checks
they apply are :mod:`dev_lab.dev.hpcaccount.checks`, and :mod:`dev_lab.dev.hpcaccount.deploy` runs them in order.
"""

from __future__ import annotations

import json
import os
import stat
import sys
import tomllib
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any, Final
from urllib.parse import urlsplit

import lab_commons.launch as _door
from lab_commons.config import FAMILY_TABLE
from lab_commons.log import emit

from dev_lab.dev._forgebackends import GITHUB_HOST
from dev_lab.dev.devdeclared import OWN_TABLE
from dev_lab.dev.forgeauth import UNREACHABLE_EXIT
from dev_lab.dev.hpcaccount.checks import association_refusal, store_problem
from dev_lab.dev.hpcaccount.grantslice import grant_refusal, machine_table, own_grant, render_grant, without_hpc
from dev_lab.dev.hpcaccount.spec import Deployment, unserved
from dev_lab.dev.hpcaccount.steps import Step

__all__ = ['UNREACHED', 'ApiCheck', 'RoleCheck', 'auth_check', 'credentials', 'grant', 'reader', 'role_of']

_CREDENTIAL_REMEDY: Final = (
    'store your OWN forge token for it once: `git config --global credential.helper store`, then '
    '`python -m dev_lab.dev.forge auth login` (or one line https://<user>:<token>@<forge host> in '
    '~/.git-credentials, chmod 600) and re-run'
)

_READER_REMEDY: Final = (
    "place a read-only forge login's minted token (the role's reader when [hpc.roles.<role>] reader names one) "
    'from the workstation: `python -m dev_lab.dev.hpcaccount credential <user>@<login host> --login <reader> '
    "--host-config <the forge host's config>` "
    "with the token on stdin; it replaces only this account's forge line. Then re-run"
)

#: The lead of an :data:`ApiCheck` answer saying the forge did not answer, which is no verdict on the token.
UNREACHED: Final = 'unreachable'

#: Reads the forge API a tick needs for one repo url; ``''`` when nothing is refused.
ApiCheck = Callable[[str, Path], str]
#: Who the stored credential is on one repo url: ``{login, push, admin}``, or ``{error}``.
RoleCheck = Callable[[str, Path], dict[str, object]]


def _store_mode(store: Path) -> int | None:
    if not store.is_file():
        return None
    return stat.S_IMODE(store.stat().st_mode) if os.name == 'posix' else 0o600  # modes are POSIX's


def credentials(step: Step, spec: Deployment, home: Path, api: ApiCheck, *, serves: bool) -> int:
    """Refuse (2) unless git can read every repo and the forge API answers what a tick needs on each served one.

    Only a SERVED repo posts statuses, so only it needs the stored token (ruling 2026-10-29, D81) -- one the family
    binds to this account's role by its URL (:func:`~dev_lab.dev.hpcaccount.spec.unserved`; cloned or not, so a first
    deploy still proves the token of what it serves and asks none for what it does not); any other is only cloned
    and fetched. Every repo
    is read with the account's own helper: a private forge repo answers no anonymous read, served here or not
    (measured 2026-11-20: two research accounts' cloned, unserved product repos were refused at exit 128).
    An account whose role never *serves* (research) ticks nothing, so no repo there needs the tick's scopes:
    ``git ls-remote`` is its whole check (a server holds only a read token).
    """
    emit('[credentials] git credential helper and the forge API per served repo; git ls-remote per repo')
    off = unserved(spec)
    served_repos = [repo for repo in spec.repos if serves and repo.name not in off]
    helper = step.read([*step.tools.git, 'config', '--global', '--get', 'credential.helper']).stdout.strip()
    store = home / '.git-credentials'
    if served_repos and (problem := store_problem(helper, store, mode=_store_mode(store))):
        emit(f'deploy refused: {problem}', err=True)
        return 2
    denied = []
    for repo in spec.repos:
        rc = step.read([*step.tools.git, 'ls-remote', repo.url, f'refs/heads/{repo.ref}']).returncode
        emit(f'  {repo.name}: {"ok" if rc == 0 else f"refused (exit {rc})"}')
        if rc:
            denied.append(repo.name)
    if denied:
        emit(f'deploy refused: no read access to {", ".join(denied)}; {_CREDENTIAL_REMEDY}', err=True)
        return 2
    if not serves:
        emit(f'  {spec.role} account: not served here: read access only, no forge API scopes asked')
        return 0
    checked = {repo.name: why for repo in served_repos if (why := api(repo.url, home))}
    unreachable = {name: why for name, why in checked.items() if why.startswith(UNREACHED)}
    refused = {name: why for name, why in checked.items() if name not in unreachable}
    for name, why in unreachable.items():
        emit(f'  {name}: {why}', err=True)
    if unreachable and not refused:
        emit(f'deploy stopped: the forge API did not answer for {", ".join(unreachable)} -- the token is not '
             'at fault; re-run the deploy', err=True)  # fmt: skip
        return 2
    for name, why in refused.items():
        emit(f'  {name}: {why}', err=True)
    if refused:
        emit(
            f'deploy refused: the forge API refuses what a tick needs on {", ".join(refused)}; store a token '
            'with the scopes each refusal names: `python -m dev_lab.dev.forge auth login`',
            err=True,
        )
        return 2
    return 0


def auth_check(url: str, home: Path) -> str:
    """The forge's own ``auth check`` of *url*, run as a subprocess, as a person runs it.

    Its :data:`~dev_lab.dev.forgeauth.UNREACHABLE_EXIT` -- the forge did not answer -- leads with :data:`UNREACHED`.
    """
    argv = [sys.executable, '-m', 'dev_lab.dev.forge', 'auth', 'check', '--url', url]
    done = _door.run(argv, cwd=home, capture_output=True, text=True, encoding='utf-8', errors='replace', check=False)
    said = done.stderr.strip() or f'auth check exited {done.returncode}'
    if done.returncode == 0:
        return ''
    return f'{UNREACHED}: {said}' if done.returncode == UNREACHABLE_EXIT else said


def role_of(url: str, home: Path) -> dict[str, object]:
    """The forge's own ``auth role`` of *url*, as a subprocess: ``{login, push, admin}``, or ``{error}``.

    It reads the stored credential as git does (``git credential fill``) and prints only the login and the
    permissions -- the token never reaches this process.
    """
    argv = [sys.executable, '-m', 'dev_lab.dev.forge', 'auth', 'role', '--url', url]
    done = _door.run(argv, cwd=home, capture_output=True, text=True, encoding='utf-8', errors='replace', check=False)
    if done.returncode:
        return {'error': done.stderr.strip() or f'auth role exited {done.returncode}'}
    return json.loads(done.stdout)


def _seen(name: str, seen: dict[str, object]) -> tuple[str, list[str]]:
    login = str(seen.get('login') or '')
    writes = [right for right in ('push', 'admin') if seen.get(right)]
    emit(f'  {name}: {login or "no stored credential (anonymous)"}' + (f' with {"+".join(writes)}' if writes else ''))
    return login, writes


def reader(spec: Deployment, home: Path, role: RoleCheck, *, semantics: Mapping[str, Any]) -> int:
    """Report the stored forge credential per forge-hosted repo; refuse (2) a writer when the role is read-only.

    Also refused: a credential other than the role's declared ``reader``, when it names one.

    User rulings 2026-11-09 (:mod:`dev_lab.dev.hpcaccount.division`): no stored credential (anonymous) cannot write
    and passes; a role that is not ``read_only`` is only reported.
    """
    expected = str(semantics.get('reader', ''))
    strict = bool(semantics.get('read_only', False))
    emit(f'[reader] the stored forge credential per forge-hosted repo ({spec.role}: '
         f'{"refused" if strict else "reported"} unless read-only{" as " + expected if expected else ""})')  # fmt: skip
    refused = []
    for repo in (repo for repo in spec.repos if urlsplit(repo.url).hostname != GITHUB_HOST):
        seen = role(repo.url, home)
        if 'error' in seen:
            emit(f'  {repo.name}: {seen["error"]}', err=True)
            refused.append(f'{repo.name}: the forge did not say who the credential is')
            continue
        login, writes = _seen(repo.name, seen)
        if writes:
            refused.append(f'{repo.name}: {login} holds {"+".join(writes)}')
        elif expected and login and login != expected:
            refused.append(f'{repo.name}: the credential is {login}, not the role reader {expected}')
    if not refused:
        return 0
    why = '; '.join(refused)
    if not strict:
        emit(f'  [report only: {spec.role} is not read_only] {why}')
        return 0
    emit(f'deploy refused: this {spec.role} account must pull read-only -- {why}. {_READER_REMEDY}', err=True)
    return 2


def _family_grant(step: Step, path: Path, live: Mapping[str, Any], user: str) -> int:
    """Confirm the grant the family file of a rendered machine file declares for this account; write nothing.

    ONE SOURCE: the render names its ``[family] source`` and holds no family leaf, and every reader layers that
    file under it. Until 2026-11-22 the family's slice was written back here, and each tick's roles read
    (``lab_commons.config.section``) then refused every leaf both files held.
    """
    source, host = live[FAMILY_TABLE].get('source', ''), live.get(OWN_TABLE, {}).get('host', '')
    door = 'python -m dev_lab.dev.hpcaccount deploy-fleet (it renders the file from the config source)'
    if restated := sorted({'clusters', 'grant'} & set(live.get('hpc', {}))):
        keys = ', '.join(f'[hpc] {key}' for key in restated)
        emit(f'deploy refused: {path} restates {keys}, which the family file at {source} holds: {door}', err=True)
        return 2
    if retired := grant_refusal(path):
        emit(f'deploy refused: the family file at {source} declares an [hpc] this kit refuses ({retired})', err=True)
        return 2
    row = own_grant(machine_table(path).get('hpc', {}), host)
    if row is None or row.get('user') != user:
        emit(
            f'deploy refused: the family file at {source} declares no [[hpc.grant]] of {user} for {host or path}: '
            f'declare it there through its pull request, then {door}',
            err=True,
        )
        return 2
    sacct = step.read([*step.tools.sacctmgr, '-nP', 'show', 'assoc', f'user={user}', 'format=account,grptres'])
    if why := association_refusal(user, sacct.stdout, row['slurm_account']):
        emit(f'deploy refused: {why}', err=True)
        return 2
    emit(f'  the family file at {source} holds the grant ({user}, {row["slurm_account"]}); {path} is written none')
    return 0


def grant(step: Step, path: Path, table: Mapping[str, Any] | None) -> int:
    """Confirm this account's grant; write its own ``[hpc]`` slice only into a file that names no family.

    A rendered machine file names its ``[family] source``: the grant is read there and nothing is written
    (:func:`_family_grant`). A hand-declared file naming none is written the slice ``deploy-fleet`` passed, when it
    holds no grant; a hand-run deploy has none to write and is refused, never a grant derived here. The declared
    Slurm account must be one of the user's associations (``sacctmgr``).
    """
    emit("[grant] this account's own [hpc] slice")
    user = step.read([*step.tools.id, '-un']).stdout.strip()
    held = path.read_text(encoding='utf-8') if path.is_file() else ''
    live = tomllib.loads(held)
    return _family_grant(step, path, live, user) if FAMILY_TABLE in live else _written(step, path, held, user, table)


def _written(step: Step, path: Path, held: str, user: str, table: Mapping[str, Any] | None) -> int:
    """Write the passed slice *table* into the hand-declared file at *path* (text *held*) when it grants no *user*."""
    hpc = tomllib.loads(held).get('hpc', {})
    holds = any(g.get('user') == user for g in hpc.get('grant', []))
    retired = grant_refusal(path) if holds else ''
    if holds and not retired:
        emit(f'  {user} already holds a grant in {path}')
        return 0
    if table is None:
        holds = f'holds a grant this kit refuses ({retired})' if retired else f'holds no grant for {user}'
        emit(
            f'deploy refused: {path} {holds} and none was passed: deploy it through deploy-fleet '
            '(the family declaration is the one source of a grant)',
            err=True,
        )
        return 2
    rows = [row for row in table.get('grant', []) if row.get('user') == user]
    if len(rows) != 1:
        emit(f'deploy refused: the passed [hpc] slice declares {len(rows)} grants for {user}, not one', err=True)
        return 2
    sacct = step.read([*step.tools.sacctmgr, '-nP', 'show', 'assoc', f'user={user}', 'format=account,grptres'])
    if why := association_refusal(user, sacct.stdout, rows[0]['slurm_account']):
        emit(f'deploy refused: {why}', err=True)
        return 2
    # ONE [hpc]: the file's other [hpc] keys (reach ...) are merged under the passed slice, never a second table
    kept = {} if retired else hpc
    text = render_grant({**kept, **table})
    if step.dry:
        emit(f'  [dry-run] {"replace the [hpc] slice of" if retired else "write to"} {path}:{text}')
        return 0
    path.parent.mkdir(parents=True, exist_ok=True)
    # FORMATS-MIGRATE-ONCE: a refused slice is rewritten from the passed declaration; every other table is kept
    path.write_text(without_hpc(held) + text, encoding='utf-8')
    done = f'migrated the grant of {user} in {path}: the file held {retired}' if retired else 'wrote the grant'
    emit(f'  {done} ({user}, {rows[0]["slurm_account"]}) to {path}')
    return 0
