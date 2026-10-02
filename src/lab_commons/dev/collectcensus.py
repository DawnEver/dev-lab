"""THE COLLECTION-REACH CENSUS as a KIT: would a recorded selection leave a repo able to COLLECT its tests?

:mod:`lab_commons.dev.collectscope` is the reader -- one test tree joined with what a selection of
extras leaves installed. This module is the CENSUS over it: a row records, per (repo, selection),
which distributions the tree would strand at collection (``errors``), which it would merely skip
(``degrades``) and which no committed text can settle (``unresolved``), and :func:`assert_reaches`
re-measures every row by EQUALITY IN BOTH DIRECTIONS.

THE KIT HOLDS NO REPO'S ROWS. A repo's selections, and what they strand in its tree, are facts about
that repo; each repo declares its rows in its own tests and calls :func:`assert_reaches` over its own
checkout, passing ``roots={'<its name>': <its root>}``. A repo named in ``here`` is read from its
WORKING TREE, any other root at ``HEAD`` (:func:`lab_commons.dev.doorcensus.door_text` argues why).

UNRESOLVED IS RECORDED, NEVER TOLERATED, AND AUDITED: :func:`assert_no_unresolved_has_a_declared_supplier`
refuses a residue name the manifest beside it already answers. The defect it was written for is on
record: a residue reported as "all transitive, none declared" while three of its five names had a
declared supplier in the very manifest being read.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Final

from lab_commons.dev.collectscope import FileReading, Reach, local_modules, reach, read_imports, tree_texts
from lab_commons.dev.doorcensus import UnreadableRepo, door_text
from lab_commons.dev.syncscope import Selection, _base, canon, extras

__all__ = [
    'TESTS',
    'WHY_FLOOR',
    'CollectRow',
    'CollectRowError',
    'ReachDriftError',
    'UnresolvedSupplierError',
    'VacuousTreeScanError',
    'assert_no_unresolved_has_a_declared_supplier',
    'assert_reaches',
    'derivable_suppliers',
    'measure',
    'readings_of',
]

#: The shortest a row's REASON may be. A row's deliverable is WHY that selection is made and what
#: its three sets mean; a caption carries neither, and is how a row is added without anybody looking.
WHY_FLOOR: Final = 200

#: Where a repo keeps its tests. A repo that moved its tree would otherwise read as a tree with no
#: imports, which is a clean-looking lie -- the per-repo file floor is what refuses it.
TESTS: Final = 'tests'


class CollectRowError(ValueError):
    """A row the census refuses to hold -- today, a caption standing in for a reason."""


class ReachDriftError(AssertionError):
    """A recorded selection no longer leaves the test tree what the row records, in either direction."""


class VacuousTreeScanError(AssertionError):
    """A scan read fewer test files, repos or rows than its floor, so its clean answer proves nothing."""


class UnresolvedSupplierError(AssertionError):
    """A name recorded UNRESOLVED while a distribution the SAME manifest declares can be derived to supply it."""


@dataclass(frozen=True, slots=True)
class CollectRow:
    """One repo's selection and what it leaves the TEST TREE able to do. Three sets, all by EQUALITY."""

    repo: str
    selected: tuple[str, ...]
    errors: frozenset[str]
    degrades: frozenset[str]
    unresolved: frozenset[str]
    why: str

    def __post_init__(self) -> None:
        """Refuse a row that cannot be true before any tree is read."""
        if len(self.why) < WHY_FLOOR:
            msg = f'{self.key}: reason is {len(self.why)} characters, below the floor of {WHY_FLOOR}'
            raise CollectRowError(msg)
        if not self.selected:
            msg = f'{self.key}: a row exists where a selection is MADE, and this one names no extra'
            raise CollectRowError(msg)

    @property
    def key(self) -> str:
        """``<repo>[<extra>,<extra>]``, the spelling a refusal names a row by."""
        return f'{self.repo}[{",".join(self.selected)}]'


def _declared(manifest: str) -> frozenset[str]:
    """Every distribution *manifest* names anywhere -- base, project, and every extra, EXPANDED.

    `_base` is the scope reader's own "project plus its required dependencies"; a second copy here
    would be free to disagree with it.
    """
    return _base(manifest) | frozenset(dist for members in extras(manifest).values() for dist in members)


@cache
def readings_of(root: Path, *, at_head: bool) -> tuple[dict[str, FileReading], str, frozenset[str], frozenset[str]]:
    """*root*'s test-tree readings, manifest, declared set and local names. Cached: a tree is read once.

    Raises:
        UnreadableRepo: *root* has no readable ``pyproject.toml``, so nothing it declares can be read.

    """
    manifest = door_text(root, 'pyproject.toml', at_head=at_head)
    if manifest is None:
        msg = f'{root} has no readable pyproject.toml (at_head={at_head}); its selections cannot be judged'
        raise UnreadableRepo(msg)
    texts = tree_texts(root, TESTS, at_head=at_head)
    readings = {name: read_imports(name, text) for name, text in texts.items()}
    return readings, manifest, _declared(manifest), local_modules(root)


def measure(root: Path, selected: tuple[str, ...], *, at_head: bool) -> Reach:
    """What *selected* leaves *root*'s test tree able to do. The join, in one call, over the REAL reader."""
    readings, manifest, declared, local = readings_of(root, at_head=at_head)
    return reach(readings, Selection(prunes=True, extras=frozenset(selected)), manifest, declared, local)


def assert_reaches(
    rows: tuple[CollectRow, ...],
    roots: Mapping[str, Path],
    floors: Mapping[str, int],
    *,
    here: str,
    repo_floor: int,
    row_floor: int,
) -> frozenset[str]:
    """Refuse unless every row whose repo is in *roots* still leaves the tree what it records.

    *floors* is the fewest test files each repo's read must hold. Returns the repos actually read.

    Raises:
        ReachDriftError: the join now answers something else, in either direction.
        VacuousTreeScanError: a tree, the repo set or the row set was below its floor.

    """
    seen: set[str] = set()
    checked = 0
    for row in rows:
        root = roots.get(row.repo)
        if root is None:
            continue
        found = measure(root, row.selected, at_head=row.repo != here)
        _assert_read(found.files, floors[row.repo], row.repo)
        _assert_row(row, found)
        seen.add(row.repo)
        checked += 1
    if len(seen) < repo_floor or checked < row_floor:
        msg = (
            f'judged {checked} selections across {len(seen)} repos, below the floors of {row_floor} '
            f'and {repo_floor}. Finding no stranded import in a set that was not read proves nothing.'
        )
        raise VacuousTreeScanError(msg)
    return frozenset(seen)


def _assert_read(files: int, floor: int, repo: str) -> None:
    if files < floor:
        msg = (
            f'{repo}: read {files} test files, below the floor of {floor}. An empty stranded set over '
            f'a tree that was not read is vacuous, not green -- re-point the scan at the test tree.'
        )
        raise VacuousTreeScanError(msg)


def _assert_row(row: CollectRow, found: Reach) -> None:
    live = (found.errors, found.degrades, found.unresolved)
    recorded = (row.errors, row.degrades, row.unresolved)
    if live != recorded:
        msg = (
            f'{row.key} records errors={sorted(row.errors)} degrades={sorted(row.degrades)} '
            f'unresolved={sorted(row.unresolved)} and now measures errors={sorted(found.errors)} '
            f'degrades={sorted(found.degrades)} unresolved={sorted(found.unresolved)}. Sites: '
            f'{found.sites[:5]}. Either the manifest moved an extra, or a test grew an import its '
            f'selection cannot supply -- which is a repo that reports no verdict rather than a '
            f'failing one. Re-measure the row; never widen it.'
        )
        raise ReachDriftError(msg)


def derivable_suppliers(name: str, declared: frozenset[str]) -> frozenset[str]:
    """Declared distributions whose SPELLING ALONE says they could supply *name*, with no table consulted.

    Three shapes: a SUFFIXED distribution (``pdfminer`` -> ``pdfminer.six``), a NAMESPACED one
    (``OCP`` -> ``cadquery-ocp``), and the ``py`` prefix in either direction (``yaml`` -> ``pyyaml``).
    The identity case is absent: `collectscope.resolve` rule 1 already claimed it.

    WHAT IT CANNOT DERIVE, AND THE ANSWER IS NOT MORE PATTERNS: ``win32com`` and ``pywintypes`` both
    come from ``pywin32`` and no rule over the spellings relates them. That half stays a NAMED SET
    with a written reason per name, in the repo whose residue it is.
    """
    spelled = canon(name)
    return frozenset(
        dist
        for dist in declared
        if dist.startswith(f'{spelled}-')
        or dist.endswith(f'-{spelled}')
        or f'py{spelled}' == dist
        or f'py{dist}' == spelled
    )


def assert_no_unresolved_has_a_declared_supplier(
    rows: tuple[CollectRow, ...],
    roots: Mapping[str, Path],
    *,
    here: str,
    pair_floor: int,
) -> int:
    """Refuse a residue name the manifest beside it already answers. Returns the pairs examined.

    Raises:
        UnresolvedSupplierError: a recorded UNRESOLVED name has a derivable declared supplier.
        VacuousTreeScanError: fewer (name, distribution) pairs were examined than the floor.

    """
    pairs = 0
    for row in rows:
        root = roots.get(row.repo)
        if root is None:
            continue
        _, _, declared, _ = readings_of(root, at_head=row.repo != here)
        for name in sorted(row.unresolved):
            pairs += len(declared)
            found = derivable_suppliers(name, declared)
            if found:
                msg = (
                    f'{row.key}: `{name}` is recorded UNRESOLVED, but this manifest DECLARES '
                    f'{sorted(found)}, which its spelling alone derives as a supplier. That is a '
                    f'missing `collectscope.ALIASES` row, not a transitive dependency -- add the row '
                    f'and re-measure the residue. Never widen the residue to keep it quiet.'
                )
                raise UnresolvedSupplierError(msg)
    if pairs < pair_floor:
        msg = (
            f'examined {pairs} (import name, declared distribution) pairs, below the floor of '
            f'{pair_floor}. Finding no derivable supplier in a set that was not read is vacuous.'
        )
        raise VacuousTreeScanError(msg)
    return pairs
