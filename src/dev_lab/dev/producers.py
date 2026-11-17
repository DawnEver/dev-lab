"""WHO PRODUCES A REPO'S TEST PARTS: declared ONCE, ``[tool.dev_lab.protection] producer``, and derived everywhere.

User ruling 2026-11-16: a family repo is produced EITHER by forge Actions OR by the HPC, never both, and a local
machine is never a PR's producer::

    [tool.dev_lab.protection]
    producer = "hpc"         # HPC hosts produce every part, light and heavy; no forge Actions workflow is rendered
    # absent: "actions"      # forge Actions post tests/base; no HPC host ever offers this repo's parts

ABSENT MEANS :data:`ACTIONS` -- the default is stated here and nowhere else, so only a repo that differs declares
anything. A missing ``hpc`` declaration still surfaces: :mod:`dev_lab.dev.producercheck` refuses a GitHub workflow
in a repo whose required parts only the HPC can produce.

Every consumer reads it here and nowhere else: :mod:`dev_lab.dev.ciworkflows` renders ``ci.yml`` (and anything in
``.github/workflows``) only for :data:`ACTIONS`; :mod:`dev_lab.dev.forgeschedule` offers parts only of an
:data:`HPC` repo; an HPC account serves a checkout only when it declares :data:`HPC`
(:mod:`dev_lab.dev.hpcaccount.tick`); merge-ready of an :data:`ACTIONS` repo reads only the parts Actions post and
never waits on a serve host (:func:`dev_lab.dev.forgemergewaits.status_waits`). Whether a repo can BE BUILT on a
cluster (``[tool.lab_commons.hpc]``) is a different fact: dev-lab ships cluster tooling and is still an Actions repo.

A PART MAY BE NOT REQUIRED (same ruling: Windows-only vendor parts no longer gate a merge). ``[tool.dev_lab.parts]
optional_needs`` names RESOURCES; a part needing any of them is never a merge or promotion condition, and still runs
wherever a host offers it -- the capability stays, only the requirement goes::

    [tool.dev_lab.parts]
    optional_needs = ["solverx", "windows"]

:func:`producible` says which parts a producer can post; :mod:`dev_lab.dev.producercheck` refuses a declaration
whose required part nothing produces.
"""

from __future__ import annotations

import tomllib
from collections.abc import Collection, Iterable, Mapping
from pathlib import Path
from typing import Any, Final

from lab_commons.hpc.declared import pyproject_at
from lab_commons.hpc.needsets import BASE

from dev_lab.dev.family import declared_table
from dev_lab.dev.partrows import needs_of_row, row_part

__all__ = [
    'ACTIONS',
    'CI_WORKFLOW',
    'HPC',
    'PRODUCERS',
    'UndeclaredProducer',
    'optional_needs_from',
    'optional_parts',
    'producer_at',
    'producer_from',
    'producible',
    'renders',
]

#: Forge Actions (GitHub or Gitea) post the repo's parts; no HPC host offers them.
ACTIONS: Final = 'actions'
#: HPC hosts post every part of the repo; no forge Actions workflow runs its tests.
HPC: Final = 'hpc'
PRODUCERS: Final = (ACTIONS, HPC)
#: The workflow whose ``jobparts produce`` posts ``tests/base``: rendered only for an :data:`ACTIONS` producer.
CI_WORKFLOW: Final = 'ci.yml'

_EXAMPLE: Final = f'[tool.dev_lab.protection] producer = "{HPC}" (absent: "{ACTIONS}") -- user ruling 2026-11-16'


class UndeclaredProducer(ValueError):
    """A repo declares a producer that is not :data:`PRODUCERS`; the message names the key."""


def producer_from(text: str, origin: str) -> str:
    """The producer pyproject *text* declares, :data:`ACTIONS` when absent; refused naming *origin* when unknown.

    Raises:
        UndeclaredProducer: ``producer`` is not one of :data:`PRODUCERS`.

    """
    table = declared_table(tomllib.loads(text), 'protection', {})
    value = table.get('producer', ACTIONS) if isinstance(table, dict) else ACTIONS
    if value not in PRODUCERS:
        msg = f'{origin} declares producer = {value!r}: declare {_EXAMPLE}'
        raise UndeclaredProducer(msg)
    return str(value)


def producer_at(root: Path, sha: str | None = None) -> str:
    """The producer commit *sha* of *root* declares (its working tree when ``None``)."""
    text = pyproject_at(root, sha) if sha else (root / 'pyproject.toml').read_text(encoding='utf-8')
    return producer_from(text, f'{root}{"@" + sha[:12] if sha else ""}:pyproject.toml')


def optional_needs_from(text: str) -> frozenset[str]:
    """The resources ``[tool.dev_lab.parts] optional_needs`` names: a part needing one is never required."""
    parts: Mapping[str, Any] = declared_table(tomllib.loads(text), 'parts', {})
    value = parts.get('optional_needs', [])
    if not isinstance(value, list) or not all(isinstance(one, str) and one for one in value):
        msg = '[tool.dev_lab.parts] optional_needs must be an array of resource names, e.g. ["solverx", "windows"]'
        raise UndeclaredProducer(msg)
    return frozenset(value)


def optional_parts(parts: Iterable[str], optional: Collection[str]) -> frozenset[str]:
    """Every row of *parts* that needs a resource of *optional*: run when offered, never a merge condition."""
    return frozenset(part for part in parts if needs_of_row(part) & set(optional))


def producible(producer: str, part: str, *, hosted: Collection[str], optional: Collection[str]) -> bool:
    """Whether *producer* posts row *part*.

    Actions post the base rows and the declared *hosted* parts; the HPC every part needing no *optional* resource
    (an optional one is a Windows/vendor part no cluster node offers).
    """
    if producer == ACTIONS:
        return row_part(part) == BASE or row_part(part) in hosted
    return not needs_of_row(part) & set(optional)


def renders(producer: str, workflow: str, forge: str) -> bool:
    """Whether a repo of *producer* renders *workflow* placed on *forge*.

    An HPC repo renders no :data:`CI_WORKFLOW` and nothing on GitHub.
    """
    return producer == ACTIONS or (workflow != CI_WORKFLOW and forge != 'github')
