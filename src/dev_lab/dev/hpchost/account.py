"""The ACCOUNT steps of ``dev_lab.dev.hpchost deploy`` -- what is checked or written before anything is installed.

:func:`credentials` checks git's credential helper and its store, every repo's ``git ls-remote`` and the
forge API calls a tick makes (:func:`auth_check`); :func:`grant` writes this account's own
``[[hpc.grant]]`` when the machine file has none. Each reports and is safe to repeat; the pure checks
they apply are :mod:`dev_lab.dev.hpchost.checks`, and :mod:`dev_lab.dev.hpchost.deploy` runs them in order.
"""

from __future__ import annotations

import os
import stat
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Final

import lab_commons.launch as _door
from lab_commons.log import emit

from dev_lab.dev.hpchost.checks import grant_of, store_problem
from dev_lab.dev.hpchost.spec import Deployment, has_grant, render_grant
from dev_lab.dev.hpchost.steps import Step

__all__ = ['ApiCheck', 'auth_check', 'credentials', 'grant']

_CREDENTIAL_REMEDY: Final = (
    'store your OWN forge token for it once: `git config --global credential.helper store`, then '
    '`python -m dev_lab.dev.forge auth login` (or one line https://<user>:<token>@<forge host> in '
    '~/.git-credentials, chmod 600) and re-run'
)

#: Reads the forge API a tick needs for one repo url; ``''`` when nothing is refused.
ApiCheck = Callable[[str, Path], str]


def _store_mode(store: Path) -> int | None:
    if not store.is_file():
        return None
    return stat.S_IMODE(store.stat().st_mode) if os.name == 'posix' else 0o600  # modes are POSIX's


def credentials(step: Step, spec: Deployment, home: Path, api: ApiCheck) -> int:
    """Refuse (2) unless git can read every repo and the forge API answers what a tick needs on each served one.

    Only a SERVED repo posts statuses, so only it needs the stored token (ruling 2026-10-29, D81); an unserved
    one is only cloned and fetched, so an anonymous ``git ls-remote`` -- no credential helper -- must succeed.
    """
    emit('[credentials] git credential helper and the forge API per served repo; git ls-remote per repo')
    served = [repo for repo in spec.repos if repo.serve]
    helper = step.read([*step.tools.git, 'config', '--global', '--get', 'credential.helper']).stdout.strip()
    store = home / '.git-credentials'
    if served and (problem := store_problem(helper, store, mode=_store_mode(store))):
        emit(f'deploy refused: {problem}', err=True)
        return 2
    denied = []
    for repo in spec.repos:
        anonymous = () if repo.serve else ('-c', 'credential.helper=', '-c', 'credential.interactive=never')
        rc = step.read([*step.tools.git, *anonymous, 'ls-remote', repo.url, f'refs/heads/{repo.ref}']).returncode
        emit(f'  {repo.name}: {"ok" if rc == 0 else f"refused (exit {rc})"}')
        if rc:
            denied.append(repo.name)
    if denied:
        emit(f'deploy refused: no read access to {", ".join(denied)}; {_CREDENTIAL_REMEDY}', err=True)
        return 2
    refused = {repo.name: why for repo in served if (why := api(repo.url, home))}
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
    """The forge's own ``auth check`` of *url*, run as a subprocess, as a person runs it."""
    argv = [sys.executable, '-m', 'dev_lab.dev.forge', 'auth', 'check', '--url', url]
    done = _door.run(argv, cwd=home, capture_output=True, text=True, encoding='utf-8', errors='replace', check=False)
    return '' if done.returncode == 0 else done.stderr.strip() or f'auth check exited {done.returncode}'


def grant(step: Step, spec: Deployment, path: Path, hostname: str) -> int:
    """Write this account's own ``[[hpc.grant]]`` when the machine file has none for it."""
    emit("[grant] this account's own [[hpc.grant]]")
    user = step.read([*step.tools.id, '-un']).stdout.strip()
    if has_grant(path, user):
        emit(f'  {user} already holds a grant in {path}')
        return 0
    sacct = step.read([*step.tools.sacctmgr, '-nP', 'show', 'assoc', f'user={user}', 'format=account,grptres'])
    grant = grant_of(user, sacct.stdout, spec=spec, host=hostname)
    if isinstance(grant, str):
        emit(f'deploy refused: {grant}', err=True)
        return 2
    text = render_grant(grant)
    if step.dry:
        emit(f'  [dry-run] write to {path}:{text}')
        return 0
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a', encoding='utf-8') as out:
        out.write(text)
    emit(f'  wrote the grant of {user} ({grant["slurm_account"]}) to {path}')
    return 0
