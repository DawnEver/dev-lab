"""``[ops.postgres]``: database roles and their predefined grants, ensured by ``install`` (2026-11-20).

A host's supervisor reads ``pg_stat_activity`` as its own OS user by local peer auth, which needs a LOGIN role of
that name holding ``pg_monitor``. That role was a manual admin step; now it is declared::

    [ops.postgres]
    roles = { "supervisor" = ["pg_monitor"] }

and ensured idempotently -- created only when absent, each grant re-granted (a no-op when held) -- as the
``postgres`` OS user over the local socket, so no password exists. Only PREDEFINED ``pg_*`` roles may be granted:
the declaration cannot make a superuser, and every name is checked before it reaches SQL. Like the units install
enables (:mod:`dev_lab.ops.enableunits`), the declaration changes only by a consented ``config apply``, so running it
grants nothing the consent did not.
"""

from __future__ import annotations

import re
import shlex
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Final

from lab_commons import launch

__all__ = ['Postgres', 'argv', 'ensure', 'step']

_ROLE: Final = re.compile(r'[a-z_][a-z0-9_-]{0,62}')
_PREDEFINED: Final = re.compile(r'pg_[a-z_]+')

Runner = Callable[[list[str]], int]


@dataclass(frozen=True)
class Postgres:
    """Each declared LOGIN role and the predefined roles it is granted; ``os_user`` runs ``psql`` by peer auth."""

    roles: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    os_user: str = 'postgres'

    def __post_init__(self) -> None:
        """Refuse no roles, an unsafe role name, or a grant that is not a predefined ``pg_*`` role."""
        if not self.roles:
            msg = '[ops.postgres] declares no roles; drop the table instead'
            raise ValueError(msg)
        for name, grants in self.roles.items():
            if not _ROLE.fullmatch(name):
                msg = f'[ops.postgres] role name {name!r} must match {_ROLE.pattern}'
                raise ValueError(msg)
            if bad := [grant for grant in grants if not _PREDEFINED.fullmatch(str(grant))]:
                msg = f'[ops.postgres] {name}: only predefined pg_* roles are granted, got {bad}'
                raise ValueError(msg)
        if not _ROLE.fullmatch(self.os_user):
            msg = f'[ops.postgres] os_user {self.os_user!r} must match {_ROLE.pattern}'
            raise ValueError(msg)
        object.__setattr__(self, 'roles', {name: tuple(grants) for name, grants in sorted(self.roles.items())})


def _sql(postgres: Postgres) -> str:
    parts = []
    for name, grants in postgres.roles.items():
        parts.append(
            f"DO $$ BEGIN IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '{name}') "
            f'THEN CREATE ROLE "{name}" LOGIN; END IF; END $$;'
        )
        parts += [f'GRANT {grant} TO "{name}";' for grant in grants]
    return ' '.join(parts)


def argv(postgres: Postgres) -> list[str]:
    """The one command that ensures every declared role, as the postgres OS user over the local socket."""
    return ['runuser', '-u', postgres.os_user, '--', 'psql', '-X', '-q', '-v', 'ON_ERROR_STOP=1', '-c', _sql(postgres)]


def step(postgres: Postgres) -> str:
    """:func:`argv` as a line an operator can run."""
    return shlex.join(argv(postgres))


def _run(command: list[str]) -> int:
    return launch.run(command, check=False).returncode


def ensure(postgres: Postgres, *, run: Runner = _run) -> bool:
    """Run :func:`argv`; whether it succeeded."""
    return run(argv(postgres)) == 0
