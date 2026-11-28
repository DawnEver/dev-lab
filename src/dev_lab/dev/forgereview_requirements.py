"""REVIEW REQUIREMENTS: what a PR review is required to judge a change against, declared per repo (D226).

User ruling 2026-11-28 (D226): the review stays ADVISORY -- it never blocks a merge -- and its REQUIREMENTS are
configurable per repo. ``[tool.dev_lab.review] requirements`` lists them from the closed set
:data:`REQUIREMENT_KINDS`, the family default :data:`FAMILY_REQUIREMENTS`:

* ``principles`` -- the family principles (:mod:`dev_lab.dev.principles`, handed to the engine as ``--principles``):
  the reviewer returns a verdict for each one;
* ``architecture`` -- the repo's architecture documents, the files its ``architecture`` globs match (required
  exactly when ``architecture`` is listed; either half alone is refused), at most ``max_architecture`` in all. They
  are read from ONE snapshot of the TRUSTED integration branch through the forge -- its tip resolved to a commit
  once (:func:`~dev_lab.dev.reviewgate.branch_sha`), the tree and every document read at that commit -- never at
  the PR head: a head cannot rewrite what it is judged against.

:func:`requirements_at` builds the per-run JSON the command reads as ``{requirements}``
(:data:`~dev_lab.dev.forgereview_scope.REQUIREMENTS_FIELD`); a key is present only when its kind is required::

    {"principles": true, "architecture": [{"id": "arch:<path>", "path": "<path>", "blob": "<sha>", "text": "..."}]}

A REQUIREMENT THAT CANNOT BE BUILT DEGRADES ALONE (review item 3 on dev-lab #1121): a glob matching nothing, a
document past ``max_architecture`` or a read the forge refuses leaves ``architecture`` out of the payload and
:attr:`Required.unjudged` names it, so the review still judges the principles and its comment lists
``architecture`` as ``unverified`` with the cause; merge-ready names the same cause on every ready head
(:func:`requirements_refusal`). The declaration's own shape is refused when it is loaded (:func:`declared_refusal`).

The engine (ai-lab) answers every requirement ``met | violated | amended | untouched`` (``unverified``: a violation
it could not ground in a changed file); :mod:`dev_lab.dev.forgereview_findings` reads the answers and the review
comment lists them -- information for the integrator, who gates draft -> ready by hand, never a merge condition.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final, cast

from dev_lab.dev.reviewcode import matches
from dev_lab.dev.reviewgate import DeclarationUnread, blob_at, branch_sha, tree_at

if TYPE_CHECKING:
    from collections.abc import Mapping

    from dev_lab.dev.forgereview_declared import Review
    from dev_lab.dev.reviewgate import RepoReader

__all__ = [
    'ARCHITECTURE',
    'ARCH_PREFIX',
    'DEFAULT_MAX_ARCHITECTURE',
    'FAMILY_REQUIREMENTS',
    'PRINCIPLES',
    'REQUIREMENT_KINDS',
    'Required',
    'RequirementsRefused',
    'declared_refusal',
    'requirements_at',
    'requirements_refusal',
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

#: Each list key's expected form, named in its refusal.
_FORMS: Final = {
    'requirements': 'requirements = ["principles", "architecture"]',
    'architecture': 'architecture = ["AGENTS.md", "docs/*.md"]',
}


class RequirementsRefused(DeclarationUnread):
    """The declared requirements cannot be built at the trusted branch: a glob matching nothing, a size past its cap."""


@dataclass(frozen=True)
class Required:
    """What a review is handed: the ``{requirements}`` payload, and every declared requirement it could not build."""

    payload: Mapping[str, Any]
    #: ``(id, why)`` of each declared requirement left out of the payload: the review lists it ``unverified``.
    unjudged: tuple[tuple[str, str], ...] = ()


def declared_refusal(requirements: object, architecture: object) -> str | None:
    """Why ``requirements`` and ``architecture`` cannot stand together, or ``None``: what the declaration refuses.

    Each must be a LIST of non-empty strings: a bare string would read as its letters (one-character kinds or paths).
    """
    kinds, globs = _strings('requirements', requirements), _strings('architecture', architecture)
    if isinstance(kinds, str) or isinstance(globs, str):
        return kinds if isinstance(kinds, str) else str(globs)
    if unknown := [kind for kind in kinds if kind not in REQUIREMENT_KINDS]:
        return f'requirements = {list(kinds)} names {unknown}: the kinds are {list(REQUIREMENT_KINDS)}'
    if repeated := sorted({kind for kind in kinds if kinds.count(kind) > 1}):
        return f'requirements = {list(kinds)} lists {repeated} twice'
    if ARCHITECTURE in kinds and not globs:
        return (
            'requirements lists "architecture" and no architecture = [<globs>] names its documents: declare them, '
            'or drop "architecture" from requirements'
        )
    if globs and ARCHITECTURE not in kinds:
        return (
            f'architecture = {list(globs)} is declared and requirements does not list "architecture": '
            'add it to requirements, or delete the globs'
        )
    return None


def _strings(key: str, value: object) -> tuple[str, ...] | str:
    """*value* as the tuple of non-empty strings a TOML list loads as, else the refusal naming *key*'s form."""
    items: tuple[object, ...] | None = cast('tuple[object, ...]', value) if isinstance(value, tuple) else None
    if items is None or not all(isinstance(one, str) and one.strip() for one in items):
        shown = f'{value!r}' if items is None else repr(list(items))  # a TOML list loads as a tuple: show it as written
        return f'{key} = {shown} is not a list of non-empty strings: write {_FORMS[key]}'
    return tuple(str(one) for one in items)


def requirements_at(client: RepoReader, review: Review, ref: str) -> Required:
    """What *review*'s declared requirements hand the reviewer, read from one snapshot of *ref*.

    *ref* is the TRUSTED integration branch (the module docstring). An architecture that cannot be built is left out
    and named in :attr:`Required.unjudged`: the principles are judged all the same.
    """
    payload: dict[str, Any] = {}
    if PRINCIPLES in review.requirements:
        payload[PRINCIPLES] = True
    if ARCHITECTURE not in review.requirements:
        return Required(payload)
    try:
        sha, sizes = _snapshot(client, review, ref)
        rows: list[dict[str, str]] = []
        for path in sizes:
            text, blob = blob_at(client, path, sha)
            rows.append({'id': f'{ARCH_PREFIX}{path}', 'path': path, 'blob': blob, 'text': text})
    except DeclarationUnread as refused:
        return Required(payload, ((ARCHITECTURE, f'not judged: {refused}'),))
    payload[ARCHITECTURE] = rows
    return Required(payload)


def requirements_refusal(client: RepoReader, review: Review, ref: str) -> str | None:
    """Why *review*'s architecture cannot be built at *ref* -- what merge-ready names -- or ``None``; no blob read."""
    if ARCHITECTURE not in review.requirements:
        return None
    try:
        _snapshot(client, review, ref)
    except DeclarationUnread as refused:
        return str(refused)
    return None


def _snapshot(client: RepoReader, review: Review, ref: str) -> tuple[str, dict[str, int]]:
    """*ref*'s commit and ``{path: size}`` of the documents *review*'s globs match there, in declared order.

    Refused (:class:`RequirementsRefused`): a glob matching nothing at that commit, naming the fix; documents past
    ``max_architecture`` in all, naming the key and every size -- both judged from the tree listing, before any
    document is read.
    """
    sha = branch_sha(client, ref)
    tree = tree_at(client, sha)
    found: dict[str, int] = {}
    for pattern in review.architecture:
        hits = sorted(path for path in tree if matches(path, (pattern,)))
        if not hits:
            msg = (
                f'[tool.dev_lab.review] architecture entry {pattern!r} matches no file at {ref} ({sha[:12]}): fix the '
                'path in architecture = [...]'
            )
            raise RequirementsRefused(msg)
        found |= {path: tree[path] for path in hits}
    if (total := sum(found.values())) > review.max_architecture:
        each = ', '.join(f'{path} {size} B' for path, size in found.items())
        msg = (
            f'[tool.dev_lab.review] architecture at {ref} is {total} B, past max_architecture '
            f'({review.max_architecture} B): {each} -- raise max_architecture or name fewer documents'
        )
        raise RequirementsRefused(msg)
    return sha, found
