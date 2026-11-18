"""WHO PERFORMS EACH FORGE ROLE OF A REPO: the family instance binds it once; this module is only the mechanism.

A repo's PR lifecycle is five ROLES (:data:`ROLES`), each performed by one EXECUTOR of a KIND (toolchain D73,
2026-11-18, superseding the repo-declared ``producer`` of 2026-11-16 and the review's ``where``):

* :data:`CI` -- the forge's own CI (GitHub Actions or Gitea Actions): :mod:`dev_lab.dev.ciworkflows` renders a job
  only for a role bound here, so a repo with no role on CI renders no workflow;
* :data:`HPC` -- the accounts of ONE grant role on ONE cluster, ``{ hpc = "<cluster>", role = "<grant role>" }``:
  ``forge serve`` under their ``hpcaccount`` tick performs the role; it resolves through the family's declared
  ``[[hpc.grant]]`` rows (:func:`accounts`);
* :data:`HOST` -- a named ops host, ``{ host = "<name>" }``, that carries the ``[ops.<duty>]`` the role needs
  (:data:`DUTIES`: the judge for ``review``, the promoter for ``promote``); checked where the host files are read
  (:func:`host_refusals`, run by :mod:`dev_lab.ops.configcheck`).

THE BINDING IS THE FAMILY'S, NEVER A REPO'S: dev-lab names no machine and no closed list of places. The family layer
(``lab_commons.config.family``) holds::

    [roles.<forge>]                      # one table per forge kind: "github" or "gitea"
    tests = { hpc = "<cluster>", role = "<grant role>" }
    review = { host = "<name>" }
    merge = "ci"
    promote = { host = "<name>" }
    prune = "ci"

    [roles.repos."<owner>/<repo>"]       # optional: one repo's roles over its forge's
    tests = "ci"

A role unbound for a repo, a kind its role cannot take (:data:`TAKES`), or an ``hpc`` binding no declared grant
resolves is refused by name, naming the table to add (:class:`Unbound`). A process with no family layer -- a forge
CI job -- reads the KINDS the render carried into its environment (:data:`ROLES_ENV`, rendered from this same
binding by :mod:`dev_lab.dev.ciworkflows`), never a default.

A REPO DECLARES NO PLACEMENT (FORMATS-MIGRATE-ONCE): ``[tool.dev_lab.protection] producer``, ``[tool.dev_lab.review]
where`` and the ``[tool.dev_lab.ci."merge.yml"]`` merge opt-in are refused by name with their one migration
(:func:`retired_placement`).

A PART MAY BE NOT REQUIRED (user ruling 2026-11-16). ``[tool.dev_lab.parts] optional_needs`` names RESOURCES; a part
needing one is never a merge or promotion condition, and still runs wherever a host offers it.
:func:`producible` says which parts the ``tests`` executor's kind posts.
"""

from __future__ import annotations

import json
import os
import tomllib
from collections.abc import Collection, Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from lab_commons.config import family
from lab_commons.hpc.grants import declared_grants
from lab_commons.hpc.needsets import BASE

from dev_lab.dev._forgebackends import backend_for
from dev_lab.dev.family import declared_table
from dev_lab.dev.forge import forge_from_remote, forge_of_url
from dev_lab.dev.partrows import needs_of_row, row_part

__all__ = [
    'CI',
    'DUTIES',
    'HOST',
    'HPC',
    'KINDS',
    'MERGE',
    'PROMOTE',
    'PRUNE',
    'REVIEW',
    'ROLES',
    'ROLES_ENV',
    'TAKES',
    'TESTS',
    'Executor',
    'Roles',
    'Unbound',
    'accounts',
    'executor_from',
    'host_refusals',
    'optional_needs_from',
    'optional_parts',
    'producible',
    'retired_placement',
    'roles_at',
    'roles_for',
    'roles_of_url',
]

TESTS: Final = 'tests'
REVIEW: Final = 'review'
MERGE: Final = 'merge'
PROMOTE: Final = 'promote'
PRUNE: Final = 'prune'
#: Every role a repo's PR lifecycle has, in lifecycle order.
ROLES: Final = (TESTS, REVIEW, MERGE, PROMOTE, PRUNE)

#: The forge's own CI (GitHub Actions or Gitea Actions).
CI: Final = 'ci'
#: The accounts of one grant role on one cluster, running ``forge serve`` under their ``hpcaccount`` tick.
HPC: Final = 'hpc'
#: A named ops host carrying the role's ``[ops.<duty>]``.
HOST: Final = 'host'
KINDS: Final = (CI, HPC, HOST)

#: Which kinds can perform each role: what each kind's code runs.
TAKES: Final = {
    TESTS: (CI, HPC),
    REVIEW: (CI, HPC, HOST),
    MERGE: (CI, HPC),
    PROMOTE: (CI, HOST),
    PRUNE: (CI, HPC),
}
#: The ``[ops.<duty>]`` a :data:`HOST` bound to a role must carry.
DUTIES: Final = {REVIEW: 'judge', PROMOTE: 'promote'}

#: The environment variable a rendered workflow carries: ``{"<role>": "<kind>", ...}`` of its repo, as JSON.
ROLES_ENV: Final = 'DEV_LAB_ROLES'

_SHAPES: Final = '"ci" | { hpc = "<cluster>", role = "<grant role>" } | { host = "<name>" }'


class Unbound(ValueError):
    """A role has no binding, a malformed one, or one the family cannot resolve; the message names the table."""


@dataclass(frozen=True)
class Executor:
    """Who performs a role: its :attr:`kind`, and the facts that kind names (a cluster and grant role, or a host)."""

    kind: str
    cluster: str = ''
    grant_role: str = ''
    host: str = ''

    def __str__(self) -> str:
        """The binding as written."""
        if self.kind == HPC:
            return f'{{ hpc = "{self.cluster}", role = "{self.grant_role}" }}'
        if self.kind == HOST:
            return f'{{ host = "{self.host}" }}'
        return f'"{self.kind}"'


@dataclass(frozen=True)
class Roles:
    """Which executor performs each role of :data:`ROLES` for one repo."""

    by: Mapping[str, Executor]

    def of(self, role: str) -> Executor:
        """The executor of *role* (one of :data:`ROLES`)."""
        return self.by[role]

    def kind(self, role: str) -> str:
        """The kind of *role*'s executor."""
        return self.by[role].kind

    def on(self, kind: str) -> frozenset[str]:
        """Every role an executor of *kind* performs."""
        return frozenset(role for role in ROLES if self.by[role].kind == kind)

    def env(self) -> str:
        """The kinds as :data:`ROLES_ENV` carries them."""
        return json.dumps({role: self.by[role].kind for role in ROLES}, sort_keys=True)

    @classmethod
    def of_kinds(cls, **kinds: str) -> Roles:
        """Roles naming only kinds (a planted fixture, or what :data:`ROLES_ENV` carries)."""
        return cls({role: Executor(kinds[role]) for role in ROLES})


def _is_hpc(value: object) -> bool:
    return (
        isinstance(value, Mapping)
        and set(value) == {'hpc', 'role'}
        and all(isinstance(one, str) and one for one in value.values())
    )


def executor_from(value: object, where: str) -> Executor:
    """The executor a binding *value* names; *where* names it in a refusal.

    Raises:
        Unbound: *value* is none of the shapes.

    """
    if value == CI:
        return Executor(CI)
    if isinstance(value, Mapping) and _is_hpc(value):
        return Executor(HPC, cluster=str(value['hpc']), grant_role=str(value['role']))
    if isinstance(value, Mapping) and set(value) == {'host'} and isinstance(value['host'], str) and value['host']:
        return Executor(HOST, host=str(value['host']))
    msg = f'{where} = {value!r} is no binding: write {_SHAPES} (D73)'
    raise Unbound(msg)


def accounts(executor: Executor, layer: Mapping[str, Any]) -> tuple[str, ...]:
    """The users of every declared ``[[hpc.grant]]`` of *layer* an :data:`HPC` *executor* names, in order."""
    if executor.kind != HPC or not isinstance(layer.get('hpc'), Mapping):
        return ()
    grants, _ = declared_grants(dict(layer['hpc']))
    named = (
        grant.user for grant in grants if grant.cluster_name == executor.cluster and grant.role == executor.grant_role
    )
    return tuple(dict.fromkeys(named))


def _bound(layer: Mapping[str, Any], forge: str, repo: str, role: str) -> Executor:
    table = layer['roles']
    override = table.get('repos', {}).get(repo, {})
    if role in override:
        where = f'[roles.repos."{repo}"] {role}'
        value = override[role]
    elif role in table.get(forge, {}):
        where = f'[roles.{forge}] {role}'
        value = table[forge][role]
    else:
        msg = (
            f'{repo} on {forge}: {role} is unbound -- bind it in [roles.{forge}] or [roles.repos."{repo}"] ({_SHAPES})'
        )
        raise Unbound(msg)
    executor = executor_from(value, where)
    if executor.kind not in TAKES[role]:
        msg = f'{where} = {executor}: {role} is performed by {list(TAKES[role])} alone'
        raise Unbound(msg)
    if executor.kind == HPC and not accounts(executor, layer):
        msg = (
            f'{where} = {executor} resolves to no account: declare a [[hpc.grant]] with cluster = '
            f'"{executor.cluster}" and role = "{executor.grant_role}" in the family layer'
        )
        raise Unbound(msg)
    return executor


def roles_for(layer: Mapping[str, Any], forge: str, repo: str) -> Roles:
    """The roles family *layer* binds for *repo* (``<owner>/<repo>``) hosted on *forge* (``github`` or ``gitea``).

    Raises:
        Unbound: a role is unbound, malformed, of a kind it cannot take, or an ``hpc`` binding resolves to no grant.

    """
    table = layer.get('roles')
    if not isinstance(table, Mapping):
        msg = f'the family layer declares no [roles]: bind every role of {forge} repos in [roles.{forge}] -- {_SHAPES}'
        raise Unbound(msg)
    named = set(table.get(forge, {})) | set(table.get('repos', {}).get(repo, {}))
    if unknown := sorted(named - set(ROLES)):
        msg = f'[roles.{forge}] or [roles.repos."{repo}"] names unknown roles {unknown}: the roles are {list(ROLES)}'
        raise Unbound(msg)
    return Roles({role: _bound(layer, forge, repo, role) for role in ROLES})


def roles_at(root: Path, *, layer: Mapping[str, Any] | None = None, env: Mapping[str, str] | None = None) -> Roles:
    """The roles of the repo checked out at *root*: from the family layer, else the kinds a render carried.

    *layer* defaults to this machine's family layer; *env* to the process environment, read only when the layer is
    empty (a forge CI job carries :data:`ROLES_ENV`).

    Raises:
        Unbound: neither source holds the binding, or the binding is refused.

    """
    layer = family() if layer is None else layer
    if layer:
        found = forge_from_remote(root)
        return roles_for(layer, backend_for(found).name, f'{found.owner}/{found.repo}')
    carried = (os.environ if env is None else env).get(ROLES_ENV, '')
    if not carried:
        msg = (
            f'{root}: no family layer on this machine and no {ROLES_ENV} carried -- the roles binding lives in the '
            "family layer's [roles.<forge>]: declare [family] in this machine file (lab_commons.config)"
        )
        raise Unbound(msg)
    kinds = json.loads(carried)
    if not isinstance(kinds, dict) or set(kinds) != set(ROLES) or not set(kinds.values()) <= set(KINDS):
        msg = f'{ROLES_ENV} = {carried!r} is not one kind per role of {list(ROLES)}: re-render the workflows'
        raise Unbound(msg)
    return Roles.of_kinds(**kinds)


def roles_of_url(url: str, *, layer: Mapping[str, Any] | None = None) -> Roles:
    """The roles family *layer* (default: this machine's) binds for the repo at remote *url* -- an ops host's read.

    Raises:
        Unbound: the layer binds no roles for it.

    """
    found = forge_of_url(url)
    return roles_for(family() if layer is None else layer, backend_for(found).name, f'{found.owner}/{found.repo}')


def _bindings(layer: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    table = layer.get('roles', {})
    found = {f'[roles.{forge}]': bound for forge, bound in table.items() if forge != 'repos'}
    return found | {f'[roles.repos."{repo}"]': bound for repo, bound in table.get('repos', {}).items()}


def host_refusals(layer: Mapping[str, Any], cards: Mapping[str, Mapping[str, Any]]) -> list[str]:
    """Every :data:`HOST` binding of *layer* whose host card (*cards*, by name) is missing or lacks the role's duty.

    Run where every host file is read (:mod:`dev_lab.ops.configcheck`); a layer binding no host has nothing to check.
    """
    found = []
    for where, bound in _bindings(layer).items():
        for role, value in bound.items():
            if role not in DUTIES:
                continue
            try:
                executor = executor_from(value, f'{where} {role}')
            except Unbound as bad:
                found.append(str(bad))
                continue
            if executor.kind != HOST:
                continue
            if executor.host not in cards:
                found.append(f'{where} {role} = {executor}: no host file declares that host')
            elif DUTIES[role] not in cards[executor.host].get('ops', {}):
                found.append(f'{where} {role} = {executor}: that host carries no [ops.{DUTIES[role]}]')
    return found


#: Each retired placement a repo once declared -> its one migration.
_RETIRED: Final = (
    (('protection', 'producer'), "bind tests, merge, promote and prune in the family layer's [roles.<forge>]"),
    (('review', 'where'), "bind review in the family layer's [roles.<forge>]"),
    (('ci', 'merge.yml'), 'bind merge = "ci" in the family layer\'s [roles.repos."<owner>/<repo>"]'),
)


def retired_placement(text: str, origin: str) -> list[str]:
    """Every retired placement pyproject *text* still declares, each with its migration (D73, migrate once)."""
    data = tomllib.loads(text)
    found = []
    for (table, key), migration in _RETIRED:
        declared = declared_table(data, table, {})
        if isinstance(declared, Mapping) and key in declared:
            found.append(
                f'{origin}: [tool.dev_lab.{table}] {key} is retired -- a repo declares no placement: {migration}, '
                'then delete the key (D73)'
            )
    return found


def optional_needs_from(text: str) -> frozenset[str]:
    """The resources ``[tool.dev_lab.parts] optional_needs`` names: a part needing one is never required."""
    parts: Mapping[str, Any] = declared_table(tomllib.loads(text), 'parts', {})
    value = parts.get('optional_needs', [])
    if not isinstance(value, list) or not all(isinstance(one, str) and one for one in value):
        msg = '[tool.dev_lab.parts] optional_needs must be an array of resource names, e.g. ["solverx", "windows"]'
        raise ValueError(msg)
    return frozenset(value)


def optional_parts(parts: Iterable[str], optional: Collection[str]) -> frozenset[str]:
    """Every row of *parts* that needs a resource of *optional*: run when offered, never a merge condition."""
    return frozenset(part for part in parts if needs_of_row(part) & set(optional))


def producible(tests: str, part: str, *, hosted: Collection[str], optional: Collection[str]) -> bool:
    """Whether an executor of kind *tests* (the ``tests`` role's) posts row *part*.

    CI posts the base rows and the declared *hosted* parts; an HPC executor every part needing no *optional*
    resource (an optional one is a Windows/vendor part no cluster node offers).
    """
    if tests == CI:
        return row_part(part) == BASE or row_part(part) in hosted
    return not needs_of_row(part) & set(optional)
