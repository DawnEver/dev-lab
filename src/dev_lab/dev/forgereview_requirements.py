"""REVIEW REQUIREMENTS: what a PR review is required to judge a change against, declared per repo (D226).

User ruling 2026-11-28 (D226): the review stays ADVISORY -- it never blocks a merge -- and its REQUIREMENTS are
configurable per repo. ``[tool.dev_lab.review] requirements`` lists them from the closed set
:data:`REQUIREMENT_KINDS`, the family default :data:`FAMILY_REQUIREMENTS`:

* ``principles`` -- the family principles (:mod:`dev_lab.dev.principles`, handed to the engine as ``--principles``):
  the reviewer returns a verdict for each one;
* ``architecture`` -- the repo's architecture documents, the files its ``architecture`` globs match (required
  exactly when ``architecture`` is listed; either half alone is refused), at most ``max_architecture`` in all. They
  are read at the TRUSTED integration branch through the forge (:func:`~dev_lab.dev.reviewgate.blob_at`), never at
  the PR head: a head cannot rewrite what it is judged against.

:func:`requirements_at` builds the per-run JSON the command reads as ``{requirements}``
(:data:`~dev_lab.dev.forgereview_scope.REQUIREMENTS_FIELD`); a key is present only when its kind is required::

    {"principles": true, "architecture": [{"id": "arch:<path>", "path": "<path>", "blob": "<sha>", "text": "..."}]}

The engine (ai-lab) answers every requirement ``met | violated | amended | untouched`` (``unverified``: a violation
it could not ground in a changed file); :mod:`dev_lab.dev.forgereview_findings` reads the answers and the review
comment lists them -- information for the integrator, who gates draft -> ready by hand, never a merge condition.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Final

from dev_lab.dev.reviewcode import matches
from dev_lab.dev.reviewgate import DeclarationUnread, blob_at, tree_at

if TYPE_CHECKING:
    from collections.abc import Sequence

    from dev_lab.dev.forgereview_declared import Review
    from dev_lab.dev.reviewgate import RepoReader

__all__ = [
    'ARCHITECTURE',
    'ARCH_PREFIX',
    'DEFAULT_MAX_ARCHITECTURE',
    'FAMILY_REQUIREMENTS',
    'PRINCIPLES',
    'REQUIREMENT_KINDS',
    'RequirementsRefused',
    'declared_refusal',
    'requirements_at',
]

PRINCIPLES: Final = 'principles'
ARCHITECTURE: Final = 'architecture'

#: The requirement kinds a repo may list: a closed set, an unknown one refused by name.
REQUIREMENT_KINDS: Final = (PRINCIPLES, ARCHITECTURE)

#: What a repo declaring no ``requirements`` is reviewed against: the family principles.
FAMILY_REQUIREMENTS: Final = (PRINCIPLES,)

#: The default ``max_architecture`` in bytes: every architecture document is in every reviewer's stable prefix.
DEFAULT_MAX_ARCHITECTURE: Final = 120_000

#: An architecture requirement's id is this prefix and its path: it is also the ``rule`` a finding may cite.
ARCH_PREFIX: Final = 'arch:'

#: A glob character: a pattern holding none names one path, read directly instead of listing the tree.
_GLOB: Final = frozenset('*?[')


class RequirementsRefused(DeclarationUnread):
    """The declared requirements cannot be built at the trusted branch: a glob matching nothing, a size past its cap."""


def declared_refusal(requirements: Sequence[str], architecture: Sequence[str]) -> str | None:
    """Why ``requirements`` and ``architecture`` cannot stand together, or ``None``: what the declaration refuses."""
    if unknown := [kind for kind in requirements if kind not in REQUIREMENT_KINDS]:
        return f'requirements = {list(requirements)} names {unknown}: the kinds are {list(REQUIREMENT_KINDS)}'
    if repeated := sorted({kind for kind in requirements if list(requirements).count(kind) > 1}):
        return f'requirements = {list(requirements)} lists {repeated} twice'
    if ARCHITECTURE in requirements and not architecture:
        return (
            'requirements lists "architecture" and no architecture = [<globs>] names its documents: declare them, '
            'or drop "architecture" from requirements'
        )
    if architecture and ARCHITECTURE not in requirements:
        return (
            f'architecture = {list(architecture)} is declared and requirements does not list "architecture": '
            'add it to requirements, or delete the globs'
        )
    return None


def requirements_at(client: RepoReader, review: Review, ref: str) -> dict[str, Any]:
    """The ``{requirements}`` JSON payload of *review*'s declared requirements, read at *ref*.

    *ref* is the TRUSTED integration branch (the module docstring). Each ``architecture`` glob is matched against
    *ref*'s tree (a pattern holding no glob character is read directly); a glob matching nothing, or documents
    past ``max_architecture`` bytes in all, is :class:`RequirementsRefused` naming it.

    Raises:
        RequirementsRefused: a glob matched nothing, or the documents are past ``max_architecture``.
        DeclarationUnread: a document or the tree could not be read through the forge.

    """
    payload: dict[str, Any] = {}
    requirements, max_architecture = review.requirements, review.max_architecture
    if PRINCIPLES in requirements:
        payload[PRINCIPLES] = True
    if ARCHITECTURE not in requirements:
        return payload
    paths = _matched(client, review.architecture, ref)
    rows: list[dict[str, str]] = []
    for path in paths:
        text, blob = blob_at(client, path, ref)
        rows.append({'id': f'{ARCH_PREFIX}{path}', 'path': path, 'blob': blob, 'text': text})
    sizes = {row['path']: len(row['text'].encode()) for row in rows}
    if (total := sum(sizes.values())) > max_architecture:
        each = ', '.join(f'{path} {size} B' for path, size in sizes.items())
        msg = (
            f'[tool.dev_lab.review] architecture at {ref} is {total} B, past max_architecture ({max_architecture} B): '
            f'{each} -- raise max_architecture or name fewer documents'
        )
        raise RequirementsRefused(msg)
    payload[ARCHITECTURE] = rows
    return payload


def _matched(client: RepoReader, architecture: Sequence[str], ref: str) -> list[str]:
    """The paths *architecture* names at *ref*, in declared order, each once; a glob matching nothing refused."""
    listed: list[str] | None = None
    found: dict[str, None] = {}
    for pattern in architecture:
        if not _GLOB & set(pattern):
            found.setdefault(pattern)  # read directly: an absent one is refused by the read, naming the path
            continue
        listed = tree_at(client, ref) if listed is None else listed
        hits = sorted(path for path in listed if matches(path, (pattern,)))
        if not hits:
            msg = f'[tool.dev_lab.review] architecture glob {pattern!r} matches no file at {ref}'
            raise RequirementsRefused(msg)
        for path in hits:
            found.setdefault(path)
    return list(found)
