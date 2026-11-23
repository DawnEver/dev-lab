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
import sys
from collections.abc import Mapping
from dataclasses import dataclass, field, fields, replace
from pathlib import Path
from typing import Any, Final

from dev_lab.dev.forge import forge_of_url
from dev_lab.dev.taskkeys import require_bundle
from dev_lab.ops import clientkeys
from dev_lab.ops.backuprole import Backup, Offsite
from dev_lab.ops.caddy import Caddy, Status
from dev_lab.ops.configretired import refuse as refuse_retired
from dev_lab.ops.consentrole import Access, Consent, ConsentClient
from dev_lab.ops.giteaadmin import Forge
from dev_lab.ops.httpsdoor import HttpsDoor
from dev_lab.ops.judgerole import Judge
from dev_lab.ops.pgroles import Postgres
from dev_lab.ops.placement import Placement
from dev_lab.ops.served import served, served_by
from dev_lab.supervise.config import ENV_PREFIX, load_config

__all__ = [
    'INTEGRATION_REF',
    'OPS_KEYS',
    'Breakglass',
    'ConfigSource',
    'Forge',
    'OpsConfig',
    'Probe',
    'Promote',
    'Supervise',
    'Upgrade',
    'load',
    'repo_name',
]


@dataclass(frozen=True)
class Promote(Placement):
    """The nightly trunk promotion: who runs it, when, and the credential it pushes with."""

    user: str
    schedule: str
    credentials: str
    memory_max: str = '1G'


#: The ref every host installs and releases from (user ruling 2026-11-06: every repo tracks integrate/main; nothing
#: waits for a promotion to ``main`` to take effect).
INTEGRATION_REF: Final = 'integrate/main'


@dataclass(frozen=True)
class ConfigSource:
    """Where ``config apply`` reads this host's reviewed file: ``path`` at the tip of ``ref`` of ``source``.

    ``token_file`` holds a read-only forge token (root 600); it is sent as an HTTP header in the git process's
    environment, never on argv. The whole table is security boundary: a change to it needs consent -- except
    ``schedule`` (when ``config tick`` runs as a root timer; empty: never), which is routine.

    ``family``, ``{file, to}``: the family file (``file`` in the same source, at the same ref) the door also puts at
    the absolute ``to`` on this host, where ``[ops.judge.family] source`` reads it (:mod:`.configdoor`).

    ``clients``: a directory of the same source whose development-machine files declare ``[dev] client_keys``; the
    fetch derives them into the candidate's ``[ops.clients]`` (:mod:`.clientkeys`), reading the declaration from the
    fetched candidate itself, so the first apply that declares it already carries the keys. Empty: none derived.
    """

    source: str
    path: str
    token_file: str
    ref: str = 'main'
    schedule: str = ''
    family: Mapping[str, str] = field(default_factory=dict)
    clients: str = ''

    def __post_init__(self) -> None:
        """Refuse a family declaration that is not exactly ``{file, to}`` with ``to`` absolute."""
        if self.family and (set(self.family) != {'file', 'to'} or not str(self.family['to']).startswith('/')):
            msg = f'[ops.config] family is {{file = "<in the source>", to = "/<absolute>"}}, not {dict(self.family)}'
            raise ValueError(msg)


@dataclass(frozen=True)
class Upgrade:
    """Where ``upgrade`` takes dev-lab from: the tip of ``ref`` of ``source``, never a caller's choice.

    ``extras`` are dev-lab's own extras; ``packages`` further requirements installed beside it (the judge host's
    reviewer, ``ai-lab``, which dev-lab declares only as its ``review`` dependency GROUP, which a git requirement
    cannot carry); ``uv`` the binary (empty: from ``PATH``). The family's revisions (lab-commons, ai-lab) come from
    dev-lab's own lock at the installed commit (:func:`dev_lab.ops.upgrade.locked_family`), never from this table.

    ``follow`` (a branch of ``source``; empty: off) makes the host upgrade ITSELF to that branch's tip on the
    ``schedule`` timer (a systemd ``OnCalendar``), authorized by this declaration instead of a consent grant
    (:mod:`dev_lab.ops.upgradefollow`). ``follow`` is boundary (only a consented ``config apply`` sets it);
    ``schedule`` is routine.
    """

    source: str
    ref: str = INTEGRATION_REF
    extras: tuple[str, ...] = ()
    packages: tuple[str, ...] = ()
    uv: str = ''
    follow: str = ''
    schedule: str = '*:0/15'


@dataclass(frozen=True)
class Breakglass(Placement, HttpsDoor):
    """The emergency merge: the restricted account and its keys, the repos it serves, a token per forge, the waves.

    ``repos`` are the clone URLs it may merge into -- ITS OWN set, never ``[ops] repos`` (what promote fetches): a
    forge host may break glass on repos it does not promote, on any forge. Each URL names its forge (the host);
    ``tokens`` maps each forge host to the ONE file holding that forge's break-glass token, so every repo on that
    forge merges as that identity. A repo is named by its full identity ``<host>/<owner>/<repo>``
    (:attr:`dev_lab.dev.forge.Forge.identity`), so one name on two forges or two owners is two repos. A repo whose
    forge names no token, a token no repo uses, an empty set and one identity twice are refused at load.

    ``state`` is a directory (the waves and their reports). A wave's window and merge cap are the params of the
    ``breakglass.wave`` consent credential that opens it (:mod:`dev_lab.ops.consent`); the role declares only their
    CEILINGS (user ruling 2026-11-06): ``wave_hours_max`` the longest window, ``max_merges_max`` the largest cap
    (``0`` = no ceiling). A non-positive or NaN window ceiling and a negative cap ceiling are refused at load.
    ``tick`` is when the timer ends expired waves and resends a wave summary no alert channel delivered (a systemd
    ``OnCalendar``). ``family`` is the break-glass processes' lab-commons family layer, ``{source, file, max_age}``:
    a wave reads who produces each repo's tests from the family's roles binding (:mod:`dev_lab.dev.roles`, D73), so
    install renders it as the ``[family]`` table of the machine file its serve and tick read
    (:data:`dev_lab.ops.install.BREAKGLASS_MACHINE`, :func:`dev_lab.ops.install.family_env`).
    The ``https_*`` keys declare its HTTPS door (:class:`~dev_lab.ops.httpsdoor.HttpsDoor`).
    """

    account: str
    state: str
    log: str
    repos: tuple[str, ...] = ()
    tokens: Mapping[str, str] = field(default_factory=dict)
    apps: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)
    keys: tuple[str, ...] = ()
    min_reason: int = 10
    wave_hours_max: float = 24.0
    max_merges_max: int = 0
    tick: str = 'hourly'
    family: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Refuse a declaration that lies (see the class docstring)."""
        HttpsDoor.__post_init__(self)
        served_by(self.repos, self.tokens, self.apps, '[ops.breakglass]')
        if self.family and not self.family.get('source'):
            msg = '[ops.breakglass.family] names no source (the family file on this host)'
            raise ValueError(msg)
        if not self.wave_hours_max > 0:  # NaN fails too
            msg = f'[ops.breakglass] wave_hours_max ({self.wave_hours_max}) must be positive'
            raise ValueError(msg)
        if self.max_merges_max < 0:
            msg = f'[ops.breakglass] max_merges_max ({self.max_merges_max}) must not be negative'
            raise ValueError(msg)

    def repo(self, identity: str) -> str | None:
        """The clone URL of the repository ``<host>/<owner>/<repo>`` *identity*, else ``None``."""
        return next((url for url in self.repos if forge_of_url(url).identity == identity), None)

    def token_file(self, url: str) -> str:
        """The file holding the break-glass token of *url*'s forge (a forge with no App: Gitea)."""
        return self.tokens[forge_of_url(url).host]


@dataclass(frozen=True)
class Probe(Placement):
    """The forge probe (:mod:`dev_lab.ops.probe`): the repos it reads, a READ-ONLY token per forge, when, as whom.

    ``repos`` are clone URLs on any forge -- its own set, as break-glass's is; ``tokens`` maps each forge host to the
    file holding that forge's probe token (refused as :class:`Breakglass` refuses its own); ``state`` the directory
    of what was already alerted; ``schedule`` the timer's ``OnCalendar``; ``user`` the account it runs as, which must
    read the token files.
    """

    user: str
    schedule: str
    state: str
    repos: tuple[str, ...] = ()
    tokens: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Refuse a declaration that lies (see :func:`~dev_lab.ops.served.served`)."""
        served(self.repos, self.tokens, '[ops.probe]')

    def token_file(self, url: str) -> str:
        """The file holding the probe token of *url*'s forge."""
        return self.tokens[forge_of_url(url).host]


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
    consent: Consent | None = None
    consent_client: ConsentClient | None = None
    backup: Backup | None = None
    access: Access | None = None
    supervise: Supervise | None = None
    judge: Judge | None = None
    upgrade: Upgrade | None = None
    probe: Probe | None = None
    config_source: ConfigSource | None = None
    forge: Forge | None = None
    environment_file: str = ''
    caddy: Caddy | None = None
    status: Status | None = None
    postgres: Postgres | None = None

    def checkout(self, url: str) -> Path:
        """Where the host keeps its clone of *url*."""
        return self.home / repo_name(url)


#: Every key ``[ops]`` declares: its scalars and its role tables (``config`` is :class:`ConfigSource`). A key
#: outside it is refused at load, as each role refuses a key outside its own fields.
OPS_KEYS: Final = frozenset({
    'home', 'python', 'repos', 'environment_file',
    'promote', 'breakglass', 'consent', 'consent_client', 'backup', 'access', 'caddy', 'supervise', 'judge',
    'upgrade', 'probe', 'config', 'forge', 'status', 'postgres', clientkeys.TABLE,
})  # fmt: skip


def repo_name(url: str) -> str:
    """The repository name a clone URL ends in (``.../owner/name.git`` -> ``name``)."""
    return url.rstrip('/').rsplit('/', 1)[-1].removesuffix('.git')


def _role[
    T: (
        Promote,
        Breakglass,
        Consent,
        ConsentClient,
        Backup,
        Offsite,
        Access,
        Supervise,
        Judge,
        Upgrade,
        Probe,
        ConfigSource,
        Forge,
        Caddy,
        Status,
        Postgres,
    )
](cls: type[T], table: object, where: str) -> T | None:
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


def _root_secret(path: Path, label: str, why: str) -> str:
    """The text of a declared root-only host secret: the ONE read every such file takes; refuse one unreadable."""
    try:
        return path.read_text(encoding='utf-8')
    except OSError as unreadable:
        msg = f'{label} {path} is declared but unreadable ({unreadable}); refusing, {why}'
        raise ValueError(msg) from unreadable


def _environment(path: Path) -> dict[str, str]:
    """The ``KEY=VALUE`` lines of a declared environment file; refuse one unreadable or not an assignment."""
    text = _root_secret(path, '[ops] environment_file', 'alerts would be off')
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


def load(
    path: Path, *, environ: dict[str, str] | None = None, as_root: bool | None = None, structure_only: bool = False,
    alerts: bool = True,
) -> OpsConfig:  # fmt: skip
    """Read *path*'s ``[ops]`` table and its environment (see the module docstring).

    *structure_only* checks the file OFF its host (a config-source repository's CI): only the shape is judged.
    ``alerts=False`` is a verb that sends none (:mod:`dev_lab.ops.alertless`): no ``SUPERVISE_*`` is required.
    *as_root* defaults to the process's own euid. Refuses a missing table, a declared environment that did not
    arrive (root: the file unreadable; non-root: no ``SUPERVISE_*`` variable), a duplicate repo name, a bad role.
    """
    merged = load_config(path, environ=environ)
    ops = merged.get('ops')
    if not isinstance(ops, dict):
        msg = f'{path} has no [ops] table'
        raise TypeError(msg)
    refuse_retired(ops)
    if unknown := sorted(set(ops) - OPS_KEYS):
        msg = f'[ops] has unknown keys {unknown}; known: {sorted(OPS_KEYS)}'
        raise ValueError(msg)
    root = (_is_root() if as_root is None else as_root) and not structure_only
    judge_table = ops.get('judge')
    # a declared keys_file ABSENT is "not yet placed" (`secret place` writes only a declared path, so `config apply`
    # must declare it first; install refuses until it is placed); a PRESENT one must be a bundle
    keys_file = str(judge_table.get('keys_file', '')) if isinstance(judge_table, dict) else ''
    if root and keys_file and os.path.lexists(keys_file):
        where, keyless = f'[ops.judge] keys_file {keys_file}', 'the reviewer would run keyless'
        require_bundle(_root_secret(Path(keys_file), '[ops.judge] keys_file', keyless), where)
    if (environment_file := str(ops.get('environment_file', ''))) and not structure_only:
        process = dict(os.environ if environ is None else environ)
        if root:
            merged = load_config(path, environ=process | _environment(Path(environment_file)))
        elif alerts and not any(name.startswith(ENV_PREFIX) for name in process):
            msg = (
                f'[ops] environment_file {environment_file} is declared but no {ENV_PREFIX}* variable reached this '
                'non-root process (its unit must carry EnvironmentFile=); refusing, alerts would be off'
            )
            raise ValueError(msg)
    repos = tuple(ops.get('repos', ()))
    if len(set(names := [repo_name(url) for url in repos])) != len(names):
        msg = f'[ops] repos name one repository twice: {names}'
        raise ValueError(msg)
    if not ops.get('home') or not ops.get('python'):
        msg = '[ops] needs home (where the clones live) and python (the interpreter the units run)'
        raise ValueError(msg)
    found = OpsConfig(
        path=path,
        home=Path(ops['home']),
        python=str(ops['python']),
        repos=repos,
        promote=_role(Promote, ops.get('promote'), '[ops.promote]'),
        breakglass=_role(Breakglass, ops.get('breakglass'), '[ops.breakglass]'),
        merged=merged,
        consent=_role(Consent, ops.get('consent'), '[ops.consent]'),
        consent_client=_role(ConsentClient, ops.get('consent_client'), '[ops.consent_client]'),
        backup=_backup(ops.get('backup')),
        access=_role(Access, ops.get('access'), '[ops.access]'),
        caddy=_role(Caddy, ops.get('caddy'), '[ops.caddy]'),
        supervise=_role(Supervise, ops.get('supervise'), '[ops.supervise]'),
        judge=_role(Judge, ops.get('judge'), '[ops.judge]'),
        upgrade=_role(Upgrade, ops.get('upgrade'), '[ops.upgrade]'),
        probe=_role(Probe, ops.get('probe'), '[ops.probe]'),
        config_source=_role(ConfigSource, ops.get('config'), '[ops.config]'),
        forge=_role(Forge, ops.get('forge'), '[ops.forge]'),
        environment_file=environment_file,
        status=_role(Status, ops.get('status'), '[ops.status]'),
        postgres=_role(Postgres, ops.get('postgres'), '[ops.postgres]'),
    )
    found = _with_clients(found, ops.get(clientkeys.TABLE))
    _doors_behind_the_allowlist(found)
    if found.status is not None and (found.caddy is None or found.supervise is None):
        msg = (
            '[ops.status] needs [ops.caddy] (the allowlist the card is served behind) and [ops.supervise] '
            '(the supervisor that writes it)'
        )
        raise ValueError(msg)
    return found


def _doors_behind_the_allowlist(found: OpsConfig) -> None:
    """Refuse an HTTPS door that could be routed outside ``[ops.caddy] allow`` (fail closed).

    A door needs ``[ops.caddy]``, and its ``https_site`` must be one the allowlist rewrites (any site when ``sites``
    is empty -- install then still refuses a site holding no ``remote_ip`` matcher); two doors never share a port.
    """
    doors = {name: role for name, role in (('consent', found.consent), ('breakglass', found.breakglass))
             if role is not None and role.https_port}  # fmt: skip
    for name, role in doors.items():
        if found.caddy is None:
            msg = f'[ops.{name}] https_port needs [ops.caddy]: the door is served only behind its remote_ip allowlist'
            raise ValueError(msg)
        if found.caddy.sites and role.https_site not in found.caddy.sites:
            msg = (f'[ops.{name}] https_site {role.https_site!r} is not an allowlisted [ops.caddy] site '
                   f'{list(found.caddy.sites)}: the door would be served outside the allowlist')  # fmt: skip
            raise ValueError(msg)
    if len({role.https_port for role in doors.values()}) < len(doors):
        msg = '[ops.consent] and [ops.breakglass] declare one https_port: each door has its own relay'
        raise ValueError(msg)


def _with_clients(found: OpsConfig, table: object) -> OpsConfig:
    """*found* with the derived ``[ops.clients] keys`` (:mod:`.clientkeys`) added to the break-glass and consent keys.

    The operator login (``[ops.access]``) takes them too on a host that opts in through ``[ops.config] clients``:
    every workstation declared in hosts-config can then do what any other can (user ruling 2026-11-22).

    Raises:
        ValueError: the table is not exactly ``{keys}`` of public key lines.

    """
    if table is None:
        return found
    if not isinstance(table, dict) or set(table) != {'keys'} or not isinstance(table['keys'], list):
        msg = f'[ops.{clientkeys.TABLE}] is the derived {{keys = [...]}} only'
        raise ValueError(msg)
    if table['keys'] and (bad := clientkeys.defects(table['keys'], f'[ops.{clientkeys.TABLE}] keys')):
        raise ValueError('; '.join(bad))
    derived = tuple(table['keys'])

    def joined(own: tuple[str, ...]) -> tuple[str, ...]:
        return own + tuple(key for key in derived if key not in own)

    breakglass = replace(found.breakglass, keys=joined(found.breakglass.keys)) if found.breakglass else None
    consent = replace(found.consent, keys=joined(found.consent.keys)) if found.consent else None
    opted = found.config_source is not None and bool(found.config_source.clients)
    access = replace(found.access, keys=joined(found.access.keys)) if found.access and opted else found.access
    return replace(found, breakglass=breakglass, consent=consent, access=access)


def _backup(table: object) -> Backup | None:
    if not isinstance(table, dict):
        return _role(Backup, table, '[ops.backup]')
    rest = {key: value for key, value in table.items() if key != 'offsite'}
    found = _role(Backup, rest, '[ops.backup]')
    offsite = _role(Offsite, table.get('offsite'), '[ops.backup.offsite]')
    return None if found is None else replace(found, offsite=offsite)
