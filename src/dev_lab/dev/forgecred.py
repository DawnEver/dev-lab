"""The forge credential: how a secret from the git credential store is presented to a forge.

Split out of :mod:`dev_lab.dev.forge` (2026-10-12) when naming WHY a credential is absent pushed
that module past the size band; the store itself -- reading, storing and that diagnosis -- moved on to
the runtime :mod:`lab_commons.credentials` (2026-10-13), which model API keys read too. What stays here
is forge-specific: the header, the refusal statuses and their remedy.
"""

from __future__ import annotations

import base64
import os
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import PurePosixPath, PureWindowsPath
from typing import TYPE_CHECKING, Final, Literal

import lab_commons.launch as _door
from lab_commons.credentials import credential_for

from dev_lab.dev.venvpath import running_interpreter

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

__all__ = [
    'AUTH_DOC',
    'AUTH_GONE',
    'AUTH_KEPT',
    'AUTH_REFUSED',
    'AUTH_REMEDY',
    'AUTH_TRANSIENT',
    'CredentialRefresh',
    'authorization',
    'refresh_credential',
    'token_for',
]

#: HTTP statuses that MAY refuse the presented credential -- a SUSPICION, never proof of expiry or
#: store capability. GET /user measures authentication; only a verified provider may attempt its native
#: refresh. Unknown stores retain the original credential and require authorization before changing it.
AUTH_REFUSED: Final = frozenset({401, 403})

#: Where the one explanation of a forge auth refusal lives; every remedy below points there.
AUTH_DOC: Final = 'docs-src/dev/forge.md#credentials (dev-lab)'

#: A confirmed refusal after the available checks; do not assert that a refresh necessarily happened.
AUTH_REMEDY: Final = (
    'the forge still refuses the credential after the available checks and any verified provider refresh -- '
    f'the account, its scopes or the forge itself refuses it; do not re-store it, report this output ({AUTH_DOC})'
)

#: How a refused credential that EXISTS is answered (ruling 2026-10-18: the forge never needs a re-login). Gitea
#: answers a transient 401 on a first attempt that the next attempt does not, so the remedy is to retry and
#: MEASURE -- never ``auth login``, which only a box holding no credential at all is told (:mod:`.forgeauth`).
_MEASURE: Final = f'retry the call, then measure: {running_interpreter()} -m dev_lab.dev.forge auth status'

#: The refresh left the store EMPTY (a store that erased on reject): still a retry and a measurement first.
AUTH_GONE: Final = (
    f'the forge refused the stored credential and the store reads empty after refreshing it as git does -- '
    f'{_MEASURE}; do not re-login, report this output if it persists ({AUTH_DOC})'
)

#: The refused credential sits in a store that cannot refresh it, so it was KEPT, not rejected.
AUTH_KEPT: Final = (
    f'the forge refused the stored credential; no verified new credential was obtained, so the original was kept '
    f'and no erase was requested -- {_MEASURE}; changing credentials requires explicit user authorization; '
    f'do not re-login, report this output if it persists ({AUTH_DOC}). A development machine whose declared login '
    'needs a NEW token: mint it through a one-code consent plan (a `forge token mint` step with stdout_local, '
    f'{running_interpreter()} -m dev_lab.dev.planrun), then place it: '
    f'{running_interpreter()} -m dev_lab.dev.devcredential --login <login> '
    '--forge-config <forge host file> < <minted file>'
)

#: What a 401/403 says when ``GET /user`` still authenticated the same credential: re-storing cannot help.
AUTH_TRANSIENT: Final = (
    'the forge refused this request, yet the stored credential authenticates (GET /user answered) -- '
    f'do not re-store it; report this output if it persists ({AUTH_DOC})'
)


def authorization(username: str, secret: str, scheme: str) -> str:
    """HTTP Basic with the credential's username, exactly as git presents it; ``<scheme> <secret>`` only without one.

    A secret with no username is a bare token handed to ``auth login`` -- the one case Basic cannot carry.
    """
    if username:
        return 'Basic ' + base64.b64encode(f'{username}:{secret}'.encode()).decode()
    return f'{scheme} {secret}'


def token_for(host: str, *, cwd: Path | None = None, env: Mapping[str, str] | None = None) -> str:
    """The secret half of :func:`lab_commons.credentials.credential_for`."""
    return credential_for(host, cwd=cwd, env=env)[1]


@dataclass(frozen=True)
class CredentialRefresh:
    """What actually happened, with the secret excluded from representation/output."""

    credential: tuple[str, str] = field(repr=False)
    state: Literal['kept', 'refreshed']
    attempted: bool
    reason: str


def _git_config(args: list[str], *, cwd: Path | None, env: Mapping[str, str]) -> tuple[int, str]:
    """Read metadata only; helper command values are never logged or executed here."""
    git = shutil.which('git', path=env.get('PATH'))
    if git is None:
        msg = 'git configuration cannot be read'
        raise OSError(msg)
    done = _door.run([git, 'config', *args], cwd=cwd, env=dict(env), capture_output=True, timeout=30, check=False)
    return done.returncode, done.stdout.decode('utf-8', 'replace').rstrip('\n')


def _refresh_support(host: str, username: str, *, cwd: Path | None, env: Mapping[str, str]) -> str:
    """An empty reason permits ONLY the documented GCM GitLab provider-owned fill path.

    GCM 2.9.1/3.0.2 GitLabHostProvider.GetCredentialAsync refreshes account oauth2 itself;
    EraseCredentialAsync deletes BOTH access and refresh tokens. GitHub/generic erase is also destructive.
    Source: https://github.com/git-ecosystem/git-credential-manager/blob/v3.0.2/src/GitLab/GitLabHostProvider.cs
    No host-name guess, username-only permission or automatic reject is safe.
    """
    if username != 'oauth2':
        return 'the account does not establish the documented provider-owned OAuth refresh capability'
    try:
        code, configured = _git_config(['--get-urlmatch', 'credential.provider', f'https://{host}'], cwd=cwd, env=env)
        if code not in (0, 1):
            return 'provider configuration could not be verified'
        provider = env.get('GCM_PROVIDER') or configured.strip()
        if provider.lower() != 'gitlab':
            return 'the selected provider has no verified safe automatic refresh path'
        return _helper_support(cwd=cwd, env=env)
    except (OSError, subprocess.TimeoutExpired):
        return 'credential configuration could not be read; the original credential is preserved'


def _helper_support(*, cwd: Path | None, env: Mapping[str, str]) -> str:
    code, scoped = _git_config(['--name-only', '--get-regexp', r'^credential\..+\.helper$'], cwd=cwd, env=env)
    if code not in (0, 1) or scoped:
        return 'scoped helper configuration does not establish one verified refresh store'
    code, raw = _git_config(['--null', '--get-all', 'credential.helper'], cwd=cwd, env=env)
    if code != 0:
        return 'the credential helper could not be verified'
    helpers: list[str] = []
    for helper in raw.removesuffix('\0').split('\0'):
        if not helper:
            helpers.clear()
        else:
            helpers.append(helper)
    if len(helpers) != 1:
        return 'the helper chain does not establish one verified refresh store'
    helper = helpers[0].strip('"')
    known = helper in {'manager', 'manager-core'} or (
        (PurePosixPath(helper).is_absolute() or PureWindowsPath(helper).is_absolute())
        and PureWindowsPath(helper).name
        in {
            'git-credential-manager',
            'git-credential-manager.exe',
            'git-credential-manager-core',
            'git-credential-manager-core.exe',
        }
    )
    return '' if known else 'the configured helper declaration is not a recognized Git Credential Manager command'


def refresh_credential(
    host: str, refused: tuple[str, str], *, cwd: Path | None = None, env: Mapping[str, str] | None = None
) -> CredentialRefresh:
    """Keep uncertain stores untouched; only a verified provider may perform its native noninteractive fill."""
    effective = {**os.environ, **dict(env or {})}
    reason = _refresh_support(host, refused[0], cwd=cwd, env=effective)
    if reason:
        return CredentialRefresh(refused, 'kept', attempted=False, reason=reason)
    try:
        pair = credential_for(host, username=refused[0], cwd=cwd, env=effective)
    except (OSError, subprocess.TimeoutExpired):
        return CredentialRefresh(
            refused, 'kept', attempted=True, reason='provider supplied no usable credential; original pair retained'
        )
    if pair == refused:
        return CredentialRefresh(
            refused, 'kept', attempted=True, reason='provider supplied no different credential; original pair retained'
        )
    return CredentialRefresh(
        pair,
        'refreshed',
        attempted=True,
        reason='the verified provider supplied a different credential without reject',
    )
