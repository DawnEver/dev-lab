"""The ``[ops]`` table of a host's supervise configuration: every fact the host roles read, stated once.

ONE FILE PER HOST. The roles live in the same file as the host's supervisor (:mod:`dev_lab.supervise.config`)
so the alert channels are one table, not two copies. What the config does NOT say is derived: the forge,
owner and repository name come from each clone URL, the trunk and integration branch from the repo's own
``[tool.dev_lab.integrator]`` declaration -- never restated here.

A role absent from the file is disabled; a role present is validated whole, so a typo is refused at load
rather than discovered at 04:30.
"""

from __future__ import annotations

from dataclasses import dataclass, fields, replace
from pathlib import Path
from typing import Any

from dev_lab.supervise.config import load_config

__all__ = ['Breakglass', 'OpsConfig', 'Promote', 'load', 'repo_name']


@dataclass(frozen=True)
class Promote:
    """The nightly trunk promotion: who runs it, when, and the credential it pushes with."""

    user: str
    schedule: str
    credentials: str
    memory_max: str = '1G'


@dataclass(frozen=True)
class Breakglass:
    """The emergency merge: the restricted account and its keys, the bypass identity, the TOTP secret, the waves.

    ``state`` is a directory (the wave, its reports, the last accepted TOTP step); ``wave_hours`` the longest wave a
    code opens; ``max_merges`` its cap (``0`` = none); ``tick`` when the timer closes expired waves and reminds
    unacknowledged audits (a systemd ``OnCalendar``), at most once per ``remind_hours``;
    ``lockout_after`` consecutive wrong codes refuse every code for ``lockout_minutes`` (:mod:`dev_lab.ops.lockout`).
    """

    account: str
    token: str
    totp: str
    state: str
    log: str
    keys: tuple[str, ...] = ()
    min_reason: int = 10
    issuer: str = 'forge break-glass'
    wave_hours: float = 4.0
    max_merges: int = 0
    tick: str = 'hourly'
    remind_hours: float = 24.0
    lockout_after: int = 5
    lockout_minutes: float = 15.0


@dataclass(frozen=True)
class Offsite:
    """The off-site copy of each backup: an S3-compatible bucket, written by single PUTs only.

    ``label`` is the first segment of every object key; ``profile`` / ``config_file`` / ``credentials_file`` name the
    AWS CLI profile and files holding the store's key; ``max_put_bytes`` is the single-PUT limit (5 GB on S3).
    """

    endpoint: str
    bucket: str
    label: str
    region: str = ''
    profile: str = ''
    config_file: str = ''
    credentials_file: str = ''
    max_put_bytes: int = 5_000_000_000
    aws: str = 'aws'


@dataclass(frozen=True)
class Backup:
    """The backup role, either side or both: EXPORT on the forge host, PULL (and off-site copy) on the backup host.

    Export (``dumpers`` non-empty): the ``account`` whose forced command is ``ops backup export``, the ``keys`` of the
    pullers, the dumpers' own settings. Pull (``source`` non-empty): ``<account>@<host>`` with a dedicated
    ``identity`` key, the ``dest`` directory, the ``user`` and ``schedule`` of the timer, ``retention_days``, and an
    optional ``offsite`` table (:class:`Offsite`).
    """

    dumpers: tuple[str, ...] = ()
    account: str = ''
    keys: tuple[str, ...] = ()
    tmp: str = ''
    gitea_binary: str = 'gitea'
    gitea_config: str = ''
    gitea_workdir: str = ''
    gitea_user: str = 'gitea'
    pg_database: str = ''
    pg_user: str = 'postgres'
    source: str = ''
    identity: str = ''
    dest: str = ''
    user: str = 'backup'
    schedule: str = ''
    retention_days: int = 14
    offsite: Offsite | None = None


@dataclass(frozen=True)
class Access:
    """The troubleshooting account: ssh key AND a TOTP code (pam_oath), sudo limited to declared commands.

    ``keys`` are its ssh keys, ``oath`` the root-only pam_oath users file, ``commands`` what sudo may run (each a full
    command line, ``*`` as sudoers reads it), ``issuer`` the Authenticator's label.
    """

    account: str
    keys: tuple[str, ...] = ()
    commands: tuple[str, ...] = ()
    oath: str = '/etc/dev-lab/ops/users.oath'
    issuer: str = 'forge ops'


@dataclass(frozen=True)
class OpsConfig:
    """The whole ``[ops]`` table, plus the merged configuration it was read from (for ``[alerts]``)."""

    path: Path
    home: Path
    python: str
    repos: tuple[str, ...]
    promote: Promote | None
    breakglass: Breakglass | None
    merged: dict[str, Any]
    backup: Backup | None = None
    access: Access | None = None

    def checkout(self, url: str) -> Path:
        """Where the host keeps its clone of *url*."""
        return self.home / repo_name(url)

    def repo(self, name: str) -> str | None:
        """The clone URL whose repository is called *name*, else ``None``."""
        return next((url for url in self.repos if repo_name(url) == name), None)


def repo_name(url: str) -> str:
    """The repository name a clone URL ends in (``.../owner/name.git`` -> ``name``)."""
    return url.rstrip('/').rsplit('/', 1)[-1].removesuffix('.git')


def _role[T: (Promote, Breakglass, Backup, Offsite, Access)](cls: type[T], table: object, where: str) -> T | None:
    if table is None or (isinstance(table, dict) and table.get('enabled') is False):
        return None
    if not isinstance(table, dict):
        msg = f'{where} must be a table'
        raise TypeError(msg)
    known = {field.name for field in fields(cls)}
    if unknown := sorted(set(table) - known - {'enabled'}):
        msg = f'{where} has unknown keys {unknown}; known: {sorted(known)}'
        raise ValueError(msg)
    values = {
        key: tuple(value) if isinstance(value, list) else value for key, value in table.items() if key != 'enabled'
    }
    try:
        return cls(**values)
    except TypeError as missing:
        msg = f'{where}: {missing}'
        raise ValueError(msg) from missing


def load(path: Path, *, environ: dict[str, str] | None = None) -> OpsConfig:
    """Read *path*'s ``[ops]`` table; refuse a missing table, a repo list with a duplicate name, or a bad role."""
    merged = load_config(path, environ=environ)
    ops = merged.get('ops')
    if not isinstance(ops, dict):
        msg = f'{path} has no [ops] table'
        raise TypeError(msg)
    repos = tuple(ops.get('repos', ()))
    names = [repo_name(url) for url in repos]
    if len(set(names)) != len(names):
        msg = f'[ops] repos name one repository twice: {names}'
        raise ValueError(msg)
    if not ops.get('home') or not ops.get('python'):
        msg = '[ops] needs home (where the clones live) and python (the interpreter the units run)'
        raise ValueError(msg)
    return OpsConfig(
        path=path,
        home=Path(ops['home']),
        python=str(ops['python']),
        repos=repos,
        promote=_role(Promote, ops.get('promote'), '[ops.promote]'),
        breakglass=_role(Breakglass, ops.get('breakglass'), '[ops.breakglass]'),
        merged=merged,
        backup=_backup(ops.get('backup')),
        access=_role(Access, ops.get('access'), '[ops.access]'),
    )


def _backup(table: object) -> Backup | None:
    if not isinstance(table, dict):
        return _role(Backup, table, '[ops.backup]')
    rest = {key: value for key, value in table.items() if key != 'offsite'}
    found = _role(Backup, rest, '[ops.backup]')
    offsite = _role(Offsite, table.get('offsite'), '[ops.backup.offsite]')
    return None if found is None else replace(found, offsite=offsite)
