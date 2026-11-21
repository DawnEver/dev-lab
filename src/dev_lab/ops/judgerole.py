"""The ``[ops.judge]`` role: the bundle-review judge's placement, schedule, repos and credentials.

A plain declaration read by :func:`dev_lab.ops.config.load`, split from it as :mod:`dev_lab.ops.consentrole` and
:mod:`dev_lab.ops.backuprole` are.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from dev_lab.dev.forge import forge_of_url
from dev_lab.ops.placement import Placement
from dev_lab.ops.served import app_of_forge, credential_files, served_by

__all__ = ['Judge']


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
