"""The ``[ops]`` roles that act on a forge with their own credential: the bundle-review judge and break-glass.

Split from :mod:`dev_lab.ops.config` at the module-size band (2026-11-21). Both declare the repos they serve and
ONE credential per forge host -- a token file or a GitHub App -- refused at construction by
:func:`dev_lab.ops.served.served_by`; :func:`dev_lab.ops.config.load` builds them from the host's file.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from dev_lab.dev.forge import forge_of_url
from dev_lab.ops.placement import Placement
from dev_lab.ops.served import app_of_forge, credential_files, served_by

__all__ = ['Breakglass', 'Judge']


@dataclass(frozen=True)
class Judge(Placement):
    """The bundle-review judge (:mod:`dev_lab.dev.forgereview_bundle`): who runs it, when, on which repos, as whom.

    ``repos`` are the web URLs it judges; ``tokens`` maps each forge host to the ONE file holding the judge's token
    there (the shape and refusals of :class:`Breakglass`) -- or ``apps`` maps it to a GitHub App,
    ``{app_id, key_file}``, the judge authenticating as that App (:mod:`dev_lab.dev.forgeapp`); one host is one or
    the other, never both.
    ``home`` is the judge user's HOME (default ``/var/lib/<user>``, 0700): the reviewer (ai-lab) reads its model
    keys ONLY from the git credential store there (``credential.helper store``, ``ai_lab.auth``, task ``pr-review``),
    so the unit runs with ``HOME`` set to it. ``keys_file`` is the host's root-owned 0600 file holding the
    ``pr-review`` task's key bundle (:mod:`dev_lab.dev.taskkeys`), which install loads into that store on stdin; it is a
    host secret exactly as ``[ops] environment_file`` is -- the same root-owned 0600 narrowing at install and the same
    root-time refusal when unreadable (:func:`_root_secret`), plus it must parse as a bundle; empty, the operator
    pipes the bundle to the printed step. ``environment_file`` is an optional
    root-owned 0600 file of further ``KEY=VALUE`` lines loaded into the judge's unit only -- never a model key.
    ``family`` is the judge's lab-commons family layer, ``{source, file, max_age}``: install renders it as the
    ``[family]`` table of the judge's machine file, so the facts every machine shares (the review month among them)
    come from the family file, not a hand-kept copy on the host.
    """

    user: str
    schedule: str
    repos: tuple[str, ...] = ()
    tokens: Mapping[str, str] = field(default_factory=dict)
    apps: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)
    home: str = ''
    keys_file: str = ''
    environment_file: str = ''
    memory_max: str = '2G'
    family: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Refuse a declaration that lies: a role's repos, one credential per forge, a sourceless family."""
        served_by(self.repos, self.tokens, self.apps, '[ops.judge]')
        if self.family and not self.family.get('source'):
            msg = '[ops.judge.family] names no source (a family checkout or the family file on this host)'
            raise ValueError(msg)

    def credential(self, url: str) -> list[str]:
        """The ``forge review judge`` arguments naming the judge's credential on *url*'s forge: App, else token."""
        if (app := app_of_forge(self.apps, url)) is not None:
            return ['--app-id', str(app[0]), '--app-key-file', app[1].as_posix()]
        return ['--token-file', self.tokens[forge_of_url(url).host]]

    @property
    def home_dir(self) -> str:
        """The judge user's HOME: ``home`` as declared, else ``/var/lib/<user>``."""
        return self.home or f'/var/lib/{self.user}'

    @property
    def secrets(self) -> tuple[str, ...]:
        """Every file the judge reads a credential from (token files and App keys): each 0600, owned by ``user``."""
        return credential_files(self.tokens, self.apps)


@dataclass(frozen=True)
class Breakglass(Placement):
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
