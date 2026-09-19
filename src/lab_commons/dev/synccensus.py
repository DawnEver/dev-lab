"""THE FAMILY'S SYNC SELECTIONS, one row per place a set of extras is CHOSEN, re-measured not remembered.

:mod:`lab_commons.dev.syncscope` answers "would THIS selection leave THIS repo able to run its own
verdict". That answer is worth nothing until it is pointed at the selections that actually exist,
which is this module -- the same seam :mod:`~lab_commons.dev.doorcensus` is to
:mod:`~lab_commons.dev.installdoor`, and it is a separate module for the same reason: a reader
driven only by planted files is a capability with no consumer.

A SELECTION IS RARELY IN THE COMMAND. The one ``uv sync`` in this family's shared CI workflow reads
``uv sync --python ${{ matrix.python-version }} $extra_flags`` -- the extras are a workflow INPUT,
built by a shell loop from the CALLER's ``extras:`` line, and the same file is reused by every
repo. So a row names WHERE the selection is written and pins the evidence line, and the reader is
handed the names rather than the argv. Two facts, two homes, joined here and nowhere else.

WHAT THE ROWS CONVICTED THE DAY THIS WAS WRITTEN, 2026-09-19: motronics' ``dep_sync`` advises, in
running code that prints to an operator mid-incident, "re-run naming every extra you need (``--extra
all`` where the project declares it)" -- and ``--extra all`` in that repo STRANDS pytest,
pytest-xdist, pytest-timeout and ruff, because ``all`` is
``motronics[euclid,maxwell,pareto,femm,gui,native]`` and carries no ``dev``. The remedy printed
after a prune would have left the tree unable to report that it was broken.

Nothing here installs, syncs or prunes. Every answer is a join of committed TEXT with declared
config, which is the only kind this layer may make.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Final

from lab_commons.dev.doorcensus import committed, door_text, reachable
from lab_commons.dev.installdoor import commands
from lab_commons.dev.syncscope import Scope, Selection, scope, selection, stranded

__all__ = [
    'SCOPE_NAMES',
    'WHY_FLOOR',
    'EvidenceGoneError',
    'ScopeDriftError',
    'ScopeRow',
    'ScopeRowError',
    'UncensusedSiteError',
    'VacuousScopeCensusError',
    'assert_scopes',
    'measure',
    'pruning_sites',
    'selection_prunes',
]

#: The scope names a row may carry, taken from the enum so a value that stops existing cannot
#: survive in the table as a string nothing resolves.
SCOPE_NAMES: Final[frozenset[str]] = frozenset(member.name for member in Scope)

#: The shortest a row's REASON may be. A row's deliverable is WHY that selection is made there and
#: what its verdict means; a caption carries neither, and a caption is how a row gets added without
#: anybody having looked at what it claims.
WHY_FLOOR: Final = 150


class ScopeRowError(ValueError):
    """A row the census refuses to hold -- an unknown scope, a caption for a reason, an impossible pair."""


class EvidenceGoneError(AssertionError):
    """A row's evidence line no longer says what the row was measured from, so the selection is unpinned."""


class ScopeDriftError(AssertionError):
    """A recorded selection no longer leaves what the table records, in either direction."""


class UncensusedSiteError(AssertionError):
    """A command that PRUNES a population exists in a declared door file and no row accounts for it."""


class VacuousScopeCensusError(AssertionError):
    """The census read fewer repos or rows than its floor -- finding nothing proves nothing."""


@dataclass(frozen=True, slots=True)
class ScopeRow:
    """One place a set of extras is chosen, with the verdict that choice leaves behind.

    *evidence* is the substring that must still stand at *path*:*line*. It is what stops the row
    outliving its subject: a selection is not a fact about this repo, so nothing else would notice
    the day a caller's ``extras:`` line changed or a documented incantation was edited.
    """

    repo: str
    path: str
    line: int
    evidence: str
    selected: tuple[str, ...]
    scope: str
    stranded: frozenset[str]
    why: str

    def __post_init__(self) -> None:
        """Refuse a row that cannot be true before any tree is read."""
        if self.scope not in SCOPE_NAMES:
            msg = f'{self.key}: scope {self.scope!r} is not one of {sorted(SCOPE_NAMES)}'
            raise ScopeRowError(msg)
        if (self.scope == Scope.STRANDS.name) != bool(self.stranded):
            msg = (
                f'{self.key}: scope {self.scope} and stranded {sorted(self.stranded)} contradict each '
                f'other. STRANDS is exactly the reading that names what it removed; every other '
                f'scope removes nothing, and a named set beside them would be unreachable prose.'
            )
            raise ScopeRowError(msg)
        if len(self.why) < WHY_FLOOR:
            msg = f'{self.key}: reason is {len(self.why)} characters, below the floor of {WHY_FLOOR}'
            raise ScopeRowError(msg)

    @property
    def key(self) -> str:
        """``<repo>::<path>:<line>``, the spelling a refusal names a row by."""
        return f'{self.repo}::{self.path}:{self.line}'


def measure(manifest: str, selected: tuple[str, ...]) -> tuple[Scope, tuple[str, ...]]:
    """What *selected* leaves behind in the repo whose manifest text this is: ``(scope, stranded)``.

    The join, in one call, so a caller never builds half of it. ``prunes=True`` because a row exists
    only where a selection is MADE, and a command that prunes nothing chooses no extras.
    """
    chosen = Selection(prunes=True, extras=frozenset(selected))
    verdict = scope(chosen, manifest)
    return verdict, stranded(chosen, manifest) if verdict is Scope.STRANDS else ()


def pruning_sites(texts: dict[tuple[str, str], str]) -> tuple[tuple[str, str, int], ...]:
    """Every ``(repo, path, line)`` in *texts* holding a command that PRUNES a population, sorted.

    THE OTHER SIDE OF THE RATCHET, and without it this census is a list somebody maintains by hand:
    a row set can only say that the selections it names still measure what they measured, never that
    a new ``uv sync`` arrived in a Makefile last week. Derived by driving the REAL
    :func:`~lab_commons.dev.syncscope.selection` over the REAL command scanner, so a site it finds
    is a site the reader would have judged.

    Pure over its argument: the caller supplies the door texts, which is what lets a planted control
    drive this function rather than a second copy of it that would agree with itself.
    """
    found = {
        (repo, path, line)
        for (repo, path), text in texts.items()
        for line, argv in commands(text)
        if selection_prunes(argv)
    }
    return tuple(sorted(found))


def selection_prunes(argv: list[str]) -> bool:
    """Answer whether *argv* moves a POPULATION, which is the question a scope row exists for."""
    return selection(argv).prunes


def assert_scopes(
    base: Path,
    paths: dict[str, str],
    rows: tuple[ScopeRow, ...],
    *,
    repo_floor: int,
    row_floor: int,
    here: str,
) -> frozenset[str]:
    """Refuse unless every recorded selection still stands where it was found and still leaves what it left.

    Returns the repos it actually read, so a caller can assert the one it runs in was among them.

    Raises:
        EvidenceGoneError: a row's evidence is no longer at that path and line.
        ScopeDriftError: the join now answers something else, in either direction.
        VacuousScopeCensusError: fewer repos or rows were read than the floors allow.

    """
    roots = reachable(base, paths)
    seen: set[str] = set()
    checked = 0
    for row in rows:
        root = roots.get(row.repo)
        if root is None:
            continue
        at_head = row.repo != here
        _assert_evidence(root, row, at_head=at_head)
        manifest = committed(root, 'pyproject.toml') if at_head else (root / 'pyproject.toml').read_text('utf-8')
        if manifest is None:
            msg = f'{row.key}: {row.repo} is checked out and has no committed pyproject.toml, so nothing is measurable'
            raise ScopeDriftError(msg)
        verdict, left = measure(manifest, row.selected)
        if verdict.name != row.scope or frozenset(left) != row.stranded:
            msg = (
                f'{row.key} records {row.scope} stranding {sorted(row.stranded)} and now measures '
                f'{verdict.name} stranding {sorted(left)}. Either the manifest moved an extra -- '
                f're-measure the row -- or a selection that used to leave a runnable verdict no '
                f'longer does, which is the defect this census exists for.'
            )
            raise ScopeDriftError(msg)
        seen.add(row.repo)
        checked += 1
    if len(seen) < repo_floor or checked < row_floor:
        msg = (
            f'read {checked} selections across {len(seen)} repos, below the floors of {row_floor} and '
            f'{repo_floor}. A census that reached one tree is not a census, and finding no stranding '
            f'selection in a set that was not read proves nothing.'
        )
        raise VacuousScopeCensusError(msg)
    return frozenset(seen)


def _assert_evidence(root: Path, row: ScopeRow, *, at_head: bool) -> None:
    """Refuse unless *row*'s evidence still stands at its declared line."""
    text = door_text(root, row.path, at_head=at_head)
    if text is None:
        msg = f'{row.key}: the file holding this selection is not there, so the row outlived its subject'
        raise EvidenceGoneError(msg)
    lines = text.splitlines()
    live = lines[row.line - 1] if 0 < row.line <= len(lines) else ''
    if row.evidence not in live:
        msg = (
            f'{row.key}: expected {row.evidence!r} at that line and found {live.strip()!r}. A row '
            f'records a selection made somewhere else; when that line moves, the row is measuring a '
            f'choice nobody makes any more. Repoint it, and re-measure rather than re-typing.'
        )
        raise EvidenceGoneError(msg)
