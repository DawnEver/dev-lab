"""The ``[ops]`` table of a host's supervise configuration: every fact the host roles read, stated once.

ONE FILE PER HOST. The roles live in the same file as the host's supervisor (:mod:`dev_lab.supervise.config`)
so the alert channels are one table, not two copies. What the config does NOT say is derived: the forge,
owner and repository name come from each clone URL, the trunk and integration branch from the repo's own
``[tool.dev_lab.integrator]`` declaration -- never restated here.

A role absent from the file is disabled; a role present is validated whole, so a typo is refused at load
rather than discovered at 04:30.

THE HOST'S SECRETS ARRIVE THROUGH ONE DECLARED FILE. ``[ops] environment_file`` names a root-owned, mode-0600 file
of ``KEY=VALUE`` lines (systemd's ``EnvironmentFile=`` format) carrying the ``SUPERVISE_*`` overrides -- above all the
alert channels' secrets. Every rendered unit carries ``EnvironmentFile=``, which systemd (PID 1, as root) reads into
the service's environment -- so a NON-ROOT verb (promote, backup pull, a supervisor with a ``user``) never re-reads
the root-only file; it requires that some ``SUPERVISE_*`` variable arrived. A ROOT verb -- above all one reached
through ``sudo`` (break-glass serve, backup export), whose environment sudo reset -- folds the file in itself, the file
winning over the process environment so a caller cannot switch a channel off. Either way a declared environment
that did not arrive refuses the verb rather than letting it run with its alerts silently off.
"""

from __future__ import annotations

import os
import re
import sys
from collections.abc import Mapping
from dataclasses import dataclass, field, fields, replace
from pathlib import Path
from typing import Any

from dev_lab.dev.forge import forge_of_url
from dev_lab.supervise.config import ENV_PREFIX, load_config

__all__ = ['Breakglass', 'OpsConfig', 'Placement', 'Promote', 'Supervise', 'load', 'repo_name']


@dataclass(frozen=True, kw_only=True)
class Placement:
    """Where a role's systemd service sits: its ``Slice=``, and the units it is ordered ``After=`` and ``Wants=``.

    Every role that renders a service carries these keys; each defaults to none, which leaves systemd's own default.
    """

    slice: str = ''
    after: tuple[str, ...] = field(default=())
    wants: tuple[str, ...] = field(default=())


@dataclass(frozen=True)
class Promote(Placement):
    """The nightly trunk promotion: who runs it, when, and the credential it pushes with."""

    user: str
    schedule: str
    credentials: str
    memory_max: str = '1G'


@dataclass(frozen=True)
class Breakglass(Placement):
    """The emergency merge: the restricted account and its keys, the repos it serves, a token per forge, the waves.

    ``repos`` are the clone URLs it may merge into -- ITS OWN set, never ``[ops] repos`` (what promote fetches): a
    forge host may break glass on repos it does not promote, on any forge. Each URL names its forge (the host);
    ``tokens`` maps each forge host to the ONE file holding that forge's break-glass token, so every repo on that
    forge merges as that identity. A repo is named by its full identity ``<host>/<owner>/<repo>``
    (:attr:`dev_lab.dev.forge.Forge.identity`), so one name on two forges or two owners is two repos. A repo whose
    forge names no token, a token no repo uses, an empty set and one identity twice are refused at load.

    ``state`` is a directory (the wave, its reports, the last accepted TOTP step); ``wave_hours`` the longest wave a
    code opens; ``max_merges`` its cap (``0`` = none); ``tick`` when the timer closes expired waves and reminds
    unacknowledged audits (a systemd ``OnCalendar``), at most once per ``remind_hours``;
    ``lockout_after`` consecutive wrong codes refuse every code for ``lockout_minutes`` (:mod:`dev_lab.ops.lockout`).
    """

    account: str
    totp: str
    state: str
    log: str
    repos: tuple[str, ...] = ()
    tokens: Mapping[str, str] = field(default_factory=dict)
    keys: tuple[str, ...] = ()
    min_reason: int = 10
    issuer: str = 'forge break-glass'
    wave_hours: float = 4.0
    max_merges: int = 0
    tick: str = 'hourly'
    remind_hours: float = 24.0
    lockout_after: int = 5
    lockout_minutes: float = 15.0

    def __post_init__(self) -> None:
        """Refuse a declaration that lies (see the class docstring)."""
        if not self.repos:
            msg = '[ops.breakglass] serves no repo: declare repos = ["https://<forge>/<owner>/<name>.git", ...]'
            raise ValueError(msg)
        identities = [forge_of_url(url).identity for url in self.repos]
        if len(set(identities)) != len(identities):
            msg = f'[ops.breakglass] repos name one repository twice: {identities}'
            raise ValueError(msg)
        hosts = {forge_of_url(url).host for url in self.repos}
        if untokened := sorted(hosts - set(self.tokens)):
            msg = f'[ops.breakglass] forge {", ".join(untokened)} names no token: add it to [ops.breakglass.tokens]'
            raise ValueError(msg)
        if unused := sorted(set(self.tokens) - hosts):
            msg = f'[ops.breakglass.tokens] {", ".join(unused)} serves no repo in [ops.breakglass] repos'
            raise ValueError(msg)

    def repo(self, identity: str) -> str | None:
        """The clone URL of the repository ``<host>/<owner>/<repo>`` *identity*, else ``None``."""
        return next((url for url in self.repos if forge_of_url(url).identity == identity), None)

    def token_file(self, url: str) -> str:
        """The file holding the break-glass token of *url*'s forge."""
        return self.tokens[forge_of_url(url).host]


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
class Backup(Placement):
    """The backup role, either side or both: EXPORT on the forge host, PULL (and off-site copy) on the backup host.

    Export (``dumpers`` non-empty): the ``account`` whose forced command is ``ops backup export``, the ``keys`` of the
    pullers, the dumpers' own settings. Pull (``source`` non-empty): ``<account>@<host>`` with a dedicated
    ``identity`` key, the ``dest`` directory, the ``user`` and ``schedule`` of the timer, ``retention_days``, and an
    optional ``offsite`` table (:class:`Offsite`).

    The ``git_mirror`` dumper reads ``mirrors`` (clone URLs on any forge), keeps a ``git clone --mirror`` of each
    under ``mirror_cache`` (persistent, so each export only fetches what is new) and bundles each into the export.
    ``mirror_metadata`` adds each repo's pulls (with reviews and head statuses) and issues as JSON, read through the
    forge's API with the read token in ``mirror_tokens[<host>]`` (a file), anonymously for a host naming none. A
    ``git_mirror`` with no mirror or no cache, one repository twice, or a token no mirror uses is refused at load.
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
    mirrors: tuple[str, ...] = ()
    mirror_cache: str = ''
    mirror_metadata: bool = False
    mirror_tokens: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Refuse a ``git_mirror`` declaration that lies (see the class docstring)."""
        if 'git_mirror' not in self.dumpers:
            return
        if not self.mirrors:
            msg = '[ops.backup] git_mirror names no mirror: declare mirrors = ["<clone url>", ...]'
            raise ValueError(msg)
        if not self.mirror_cache:
            msg = '[ops.backup] git_mirror needs mirror_cache (the persistent directory the mirrors live in)'
            raise ValueError(msg)
        names = [mirror_name(url) for url in self.mirrors]
        if len(set(names)) != len(names):
            msg = f'[ops.backup] mirrors name one repository twice: {names}'
            raise ValueError(msg)
        hosts = {mirror_name(url).split('_', 1)[0] for url in self.mirrors}
        if unused := sorted(set(self.mirror_tokens) - hosts):
            msg = f'[ops.backup.mirror_tokens] {", ".join(unused)} serves no mirror'
            raise ValueError(msg)


def mirror_name(url: str) -> str:
    """``<host>_<owner>_<repo>`` of a clone URL (scheme, credentials, port, ``.git`` dropped); a path keeps parts."""
    if '://' in url:
        authority, _, path = url.partition('://')[2].partition('/')
        rest = f'{authority.rpartition("@")[2].partition(":")[0]}/{path}'
    elif scp := _SCP.match(url):
        rest = f'{scp["host"]}/{scp["path"]}'
    else:
        rest = url
    parts = [part for part in re.split(r'[/\\]+', rest.strip('/\\').removesuffix('.git')) if part]
    return '_'.join(re.sub(r'[^A-Za-z0-9._-]', '-', part) for part in parts)


#: ``[user@]host:path``; a one-letter host is a Windows drive, not a forge.
_SCP = re.compile(r'^(?:[^@/\\]+@)?(?P<host>[^:/\\]{2,}):(?P<path>.+)$')


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
class Supervise(Placement):
    """The host's supervisor daemon (:mod:`dev_lab.supervise`), serving ``project`` with this same file as config.

    ``user`` empty runs it as root (its remedies restart services); ``memory_max`` empty sets no ceiling.
    """

    project: str
    user: str = ''
    memory_max: str = ''


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
    supervise: Supervise | None = None
    environment_file: str = ''

    def checkout(self, url: str) -> Path:
        """Where the host keeps its clone of *url*."""
        return self.home / repo_name(url)


def repo_name(url: str) -> str:
    """The repository name a clone URL ends in (``.../owner/name.git`` -> ``name``)."""
    return url.rstrip('/').rsplit('/', 1)[-1].removesuffix('.git')


def _role[T: (Promote, Breakglass, Backup, Offsite, Access, Supervise)](
    cls: type[T], table: object, where: str
) -> T | None:
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


def _environment(path: Path) -> dict[str, str]:
    """The ``KEY=VALUE`` lines of a declared environment file; refuse one unreadable or not an assignment."""
    try:
        text = path.read_text(encoding='utf-8')
    except OSError as unreadable:
        msg = f'[ops] environment_file {path} is declared but unreadable ({unreadable}); refusing, alerts would be off'
        raise ValueError(msg) from unreadable
    found: dict[str, str] = {}
    for number, line in enumerate(text.splitlines(), 1):
        stripped = line.strip()
        if not stripped or stripped.startswith(('#', ';')):
            continue
        key, sep, value = stripped.partition('=')
        if not sep or not key.strip():
            msg = f'[ops] environment_file {path}:{number} is not a KEY=VALUE line'
            raise ValueError(msg)
        value = value.strip()
        if len(value) > 1 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        found[key.strip()] = value
    return found


def _is_root() -> bool:
    return sys.platform != 'win32' and os.geteuid() == 0


def load(path: Path, *, environ: dict[str, str] | None = None, as_root: bool | None = None) -> OpsConfig:
    """Read *path*'s ``[ops]`` table and its environment (see the module docstring).

    *as_root* defaults to the process's own euid. Refuses a missing table, a declared environment that did not
    arrive (root: the file unreadable; non-root: no ``SUPERVISE_*`` variable), a duplicate repo name, a bad role.
    """
    merged = load_config(path, environ=environ)
    ops = merged.get('ops')
    if not isinstance(ops, dict):
        msg = f'{path} has no [ops] table'
        raise TypeError(msg)
    if environment_file := str(ops.get('environment_file', '')):
        process = dict(os.environ if environ is None else environ)
        if _is_root() if as_root is None else as_root:
            merged = load_config(path, environ=process | _environment(Path(environment_file)))
        elif not any(name.startswith(ENV_PREFIX) for name in process):
            msg = (
                f'[ops] environment_file {environment_file} is declared but no {ENV_PREFIX}* variable reached this '
                'non-root process (its unit must carry EnvironmentFile=); refusing, alerts would be off'
            )
            raise ValueError(msg)
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
        supervise=_role(Supervise, ops.get('supervise'), '[ops.supervise]'),
        environment_file=environment_file,
    )


def _backup(table: object) -> Backup | None:
    if not isinstance(table, dict):
        return _role(Backup, table, '[ops.backup]')
    rest = {key: value for key, value in table.items() if key != 'offsite'}
    found = _role(Backup, rest, '[ops.backup]')
    offsite = _role(Offsite, table.get('offsite'), '[ops.backup.offsite]')
    return None if found is None else replace(found, offsite=offsite)
