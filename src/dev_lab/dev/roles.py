"""WHO PERFORMS EACH FORGE ROLE OF A REPO: declared ONCE, ``[tool.dev_lab.roles]``, and derived everywhere.

A repo's PR lifecycle is five ROLES, and each is performed by exactly one EXECUTOR, named by the PLACE it runs
(toolchain D70-D72, 2026-11-18, superseding the one ``producer`` of 2026-11-16, which named only where the tests ran,
and the review's ``where``)::

    [tool.dev_lab.roles]     # a Gitea repo of the family; a GitHub one: "actions" for all but review
    tests = "hpc"            # posts tests/<part>
    review = "judge"         # the AI review: its comment and tests/review (advisory, never a merge condition)
    merge = "hpc"            # the merge decision -- tests/merge-ready, tests/security, the head gates -- and the merge
    promote = "forge"        # integration -> trunk
    prune = "hpc"            # close the landed PRs, sweep the branches integration holds, prune the records home

The executors (:data:`EXECUTORS`), each a place the family's host files declare:

* :data:`ACTIONS` -- the forge's own CI (GitHub Actions or Gitea Actions): :mod:`dev_lab.dev.ciworkflows` renders a
  job only for a role on it (every base job names its role), so a repo with no role on it renders no workflow.
* :data:`HPC` -- ``forge serve`` under the ``hpcaccount`` tick on the verification accounts: it claims parts
  (tests), judges and merges (merge), and closes, sweeps and prunes (prune) only where the repo puts that role here.
* :data:`JUDGE` -- the independent review host (``[ops.judge]``, user ruling 2026-11-10: every family PR is reviewed
  there) over a bundle the forge's CI prepares: the one job rendered for it is that prepare
  (:data:`~dev_lab.dev.reviewgate.PREPARE_WORKFLOW`).
* :data:`FORGE` -- the Gitea host itself: its ops ``promote`` role fast-forwards the trunk of each repo whose
  ``promote`` is here.

Which executor may perform which role is :data:`ALLOWED`; a value outside it is refused by name. EVERY ROLE IS
DECLARED: no default, so no repo is on an executor it never chose. A missing table, a missing or unknown role and an
executor not allowed for its role are refused by name with the table to write. The retired declarations are refused
by name with their one-shot migration (FORMATS-MIGRATE-ONCE): ``[tool.dev_lab.protection] producer`` and the
review's ``[tool.dev_lab.review] where``.

A PART MAY BE NOT REQUIRED (user ruling 2026-11-16: Windows-only vendor parts no longer gate a merge).
``[tool.dev_lab.parts] optional_needs`` names RESOURCES; a part needing any of them is never a merge or promotion
condition, and still runs wherever a host offers it -- the capability stays, only the requirement goes.
:func:`producible` says which parts the executor of ``tests`` can post; :mod:`dev_lab.dev.rolecheck` refuses a
declaration whose required part nothing posts.
"""

from __future__ import annotations

import tomllib
from collections.abc import Collection, Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from lab_commons.hpc.declared import pyproject_at
from lab_commons.hpc.needsets import BASE

from dev_lab.dev.family import declared_table
from dev_lab.dev.partrows import needs_of_row, row_part

__all__ = [
    'ACTIONS',
    'ALLOWED',
    'EXECUTORS',
    'FORGE',
    'HPC',
    'JUDGE',
    'MERGE',
    'PROMOTE',
    'PRUNE',
    'REVIEW',
    'ROLES',
    'TESTS',
    'Roles',
    'UndeclaredRoles',
    'optional_needs_from',
    'optional_parts',
    'producible',
    'roles_at',
    'roles_from',
]

TESTS: Final = 'tests'
REVIEW: Final = 'review'
MERGE: Final = 'merge'
PROMOTE: Final = 'promote'
PRUNE: Final = 'prune'
#: Every role a repo's PR lifecycle has, in lifecycle order.
ROLES: Final = (TESTS, REVIEW, MERGE, PROMOTE, PRUNE)

#: The forge's own CI (GitHub Actions or Gitea Actions), rendered by :mod:`dev_lab.dev.ciworkflows`.
ACTIONS: Final = 'actions'
#: ``forge serve`` under the ``hpcaccount`` tick on the verification accounts.
HPC: Final = 'hpc'
#: The independent review host (``[ops.judge]``).
JUDGE: Final = 'judge'
#: The Gitea host itself (its ops ``promote`` role).
FORGE: Final = 'forge'
EXECUTORS: Final = (ACTIONS, HPC, JUDGE, FORGE)

#: Which executors can perform each role: what each place runs.
ALLOWED: Final = {
    TESTS: (ACTIONS, HPC),
    REVIEW: (ACTIONS, HPC, JUDGE),
    MERGE: (ACTIONS, HPC),
    PROMOTE: (ACTIONS, FORGE),
    PRUNE: (ACTIONS, HPC),
}

_TABLE: Final = '[tool.dev_lab.roles]'
_EXAMPLE: Final = f'{_TABLE} ' + ' '.join(f'{role} = {"|".join(ALLOWED[role])}' for role in ROLES) + ' (D70-D72)'
#: The roles table a repo's retired ``producer`` migrates to, by its value.
_MIGRATED: Final = {
    'hpc': 'tests = "hpc", review = "judge", merge = "hpc", promote = "forge", prune = "hpc"',
    'actions': 'tests = "actions", review = "judge", merge = "actions", promote = "actions", prune = "actions"',
}


class UndeclaredRoles(ValueError):
    """A repo's roles are missing, malformed or in a retired spelling; the message names the table to write."""


@dataclass(frozen=True)
class Roles:
    """Which executor performs each role of :data:`ROLES`."""

    by: Mapping[str, str]

    def of(self, role: str) -> str:
        """The executor of *role* (one of :data:`ROLES`)."""
        return self.by[role]

    def on(self, executor: str) -> frozenset[str]:
        """Every role *executor* performs."""
        return frozenset(role for role in ROLES if self.by[role] == executor)


def _retired(data: Mapping[str, Any], origin: str) -> None:
    protection = declared_table(data, 'protection', {})
    if isinstance(protection, dict) and 'producer' in protection:
        value = protection['producer']
        msg = (
            f'{origin} declares the retired [tool.dev_lab.protection] producer = {value!r}: migrate it once to '
            f'{_TABLE} {_MIGRATED.get(value, _MIGRATED["actions"])} and delete the producer key (D70-D72)'
        )
        raise UndeclaredRoles(msg)
    review = declared_table(data, 'review', {})
    if isinstance(review, dict) and 'where' in review:
        msg = (
            f'{origin} declares the retired [tool.dev_lab.review] where = {review["where"]!r}: migrate it once to '
            f'{_TABLE} review = "{JUDGE}" (or the executor that reviews) and delete the where key (D71)'
        )
        raise UndeclaredRoles(msg)


def roles_from(text: str, origin: str) -> Roles:
    """The roles pyproject *text* declares; refused naming *origin* when missing, malformed or retired.

    Raises:
        UndeclaredRoles: the table is missing, a role is missing or unknown, an executor is not one :data:`ALLOWED`
            for its role, or a retired declaration still stands.

    """
    data = tomllib.loads(text)
    _retired(data, origin)
    table = declared_table(data, 'roles', None)
    if not isinstance(table, dict):
        msg = f'{origin} declares no {_TABLE}: declare who performs every role -- {_EXAMPLE}'
        raise UndeclaredRoles(msg)
    if unknown := sorted(set(table) - set(ROLES)):
        msg = f'{origin} {_TABLE} names unknown roles {unknown}: the roles are {list(ROLES)}'
        raise UndeclaredRoles(msg)
    if missing := [role for role in ROLES if role not in table]:
        msg = f'{origin} {_TABLE} leaves {missing} undeclared: every role is declared -- {_EXAMPLE}'
        raise UndeclaredRoles(msg)
    if wrong := [f'{role} = {table[role]!r}' for role in ROLES if table[role] not in ALLOWED[role]]:
        allowed = '; '.join(f'{role}: {list(ALLOWED[role])}' for role in ROLES)
        msg = f'{origin} {_TABLE} names executors no place runs ({", ".join(wrong)}): each role takes {allowed}'
        raise UndeclaredRoles(msg)
    return Roles({role: str(table[role]) for role in ROLES})


def roles_at(root: Path, sha: str | None = None) -> Roles:
    """The roles commit *sha* of *root* declares (its working tree when ``None``)."""
    text = pyproject_at(root, sha) if sha else (root / 'pyproject.toml').read_text(encoding='utf-8')
    return roles_from(text, f'{root}{"@" + sha[:12] if sha else ""}:pyproject.toml')


def optional_needs_from(text: str) -> frozenset[str]:
    """The resources ``[tool.dev_lab.parts] optional_needs`` names: a part needing one is never required."""
    parts: Mapping[str, Any] = declared_table(tomllib.loads(text), 'parts', {})
    value = parts.get('optional_needs', [])
    if not isinstance(value, list) or not all(isinstance(one, str) and one for one in value):
        msg = '[tool.dev_lab.parts] optional_needs must be an array of resource names, e.g. ["solverx", "windows"]'
        raise UndeclaredRoles(msg)
    return frozenset(value)


def optional_parts(parts: Iterable[str], optional: Collection[str]) -> frozenset[str]:
    """Every row of *parts* that needs a resource of *optional*: run when offered, never a merge condition."""
    return frozenset(part for part in parts if needs_of_row(part) & set(optional))


def producible(tests: str, part: str, *, hosted: Collection[str], optional: Collection[str]) -> bool:
    """Whether *tests*, the executor of the ``tests`` role, posts row *part*.

    Actions post the base rows and the declared *hosted* parts; the HPC every part needing no *optional* resource
    (an optional one is a Windows/vendor part no cluster node offers).
    """
    if tests == ACTIONS:
        return row_part(part) == BASE or row_part(part) in hosted
    return not needs_of_row(part) & set(optional)
