"""THE READ half of the dated-memory body: where an entry SITS, and what its header CLAIMS.

SPLIT OUT OF :mod:`lab_commons.dev.famtests.datedmemory` at the seam that module's own first
sentence names -- "the READERS" -- and at the same seam
:mod:`lab_commons.dev.famtests._configrender_readings` already runs on next door: everything here is
a READING and everything there is a VERDICT. A reading answers "what is on disk"; a verdict binds a
floor, compares against a declaration and names a remedy. Keeping them apart is what lets a consumer
parametrize on a reading -- :func:`undated`, :func:`silent` and :func:`date_disagreements` are pure
over a tree and can be asserted on directly -- without going through an assert that has already
decided what the answer should have been. The import runs ONE WAY, and the public surface is
unchanged: every name here is re-exported by ``datedmemory``, so a consumer still has one import.

NOTHING HERE RAISES ON AN OFFENDER, and that is the property the split makes structural rather than
a promise. Every reader RETURNS THE SET, because both consumers pin their offenders as a NAMED SET
compared by equality, and an exception that fires on the first one cannot be pinned, cannot say how
many there are, and cannot be ratcheted downward. The one refusal this family owns lives beside the
verdicts that raise it.

WHY THIS IS NOT BOLTED ONTO :mod:`lab_commons.dev.datedlog`, which is the question this half was
dispatched with. ``datedlog`` publishes ``date_parts`` and ``dated_log``, which CONSTRUCT a path.
These READ one. That much is only a direction, and a direction is not a boundary -- these three
measured differences are:

* THE LAYOUTS ARE NOT THE SAME LAYOUT. ``dated_log`` builds ``<base>/<yy>/<mm>/<dd>/<kind>/<name>``:
  a TWO-DIGIT year from ``strftime('%y')``, a mandatory ``kind`` leaf, and a repo-chosen ``base``. A
  memory entry sits at ``<tree>/<YYYY>/<MM>/<DD>/<name>``: four digits, no kind, no base. The layout
  these readers are about is one its neighbour CANNOT PRODUCE, and a reader shipped beside a
  constructor that cannot write what it reads is a declaration that lies by adjacency.
* THE REFUSALS ARE OPPOSITE IN KIND. ``dated_log`` RAISES on the first bad name, at construction, on
  one path -- a gate. These return, for the reason above.
* THEIR FLOORS DIFFER BECAUSE ONLY ONE OF THEM SCANS. ``dated_log`` has no floor and needs none; it
  reads nothing. A scan needs one or its silence is vacuous, so every arm over these readings goes
  through :mod:`lab_commons.dev.floors` first and the floor is the consumer's own measured number.

EVERY REPO-SHAPED FACT ARRIVES AS A KEYWORD ARGUMENT WITH NO DEFAULT, because the diff between the
two consumers IS the repo boundary rather than a guess. ``wdg-lab`` walks FIVE memory trees holding
352 entries; ``optimi-lab`` reads ONE holding a handful, and the kit's own tests read a third shape
again. ``wdg-lab`` drops ``_meta.json`` AND ``.gitkeep`` and never descends into ``node_modules``,
``target`` or a sibling checkout, where ``optimi-lab`` has neither problem. A guessed exclusion set
is the worst of them: it does not raise, it removes files from the population, and the scan then
reports clean over a tree it stopped reading.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING, Final, NamedTuple

if TYPE_CHECKING:
    from collections.abc import Collection, Iterable, Mapping

__all__ = [
    'DATE_DEPTH',
    'MemoryScan',
    'date_disagreements',
    'entries',
    'memory_trees',
    'silent',
    'take_scan',
    'undated',
]

#: ``YYYY / MM / DD`` -- the three leading parts of every memory path. FOUR digits, which is the
#: layout :func:`lab_commons.dev.datedlog.dated_log` does not write; see the module docstring.
DATE_DEPTH: Final = 3

#: How an entry dates itself. One regex, because a second spelling of it is a second answer: both
#: consumers already had this exact pattern, character for character.
_CREATED: Final = re.compile(r'^created:\s*(\d{4})-(\d{2})-(\d{2})\s*$', re.MULTILINE)


class MemoryScan(NamedTuple):
    """One reading over every declared tree, taken once and shared by every arm that judges it.

    Attributes:
        trees: the declared trees, as the consumer spelled them.
        entries_read: the population every arm's floor is bound against.
        undated: tree-qualified paths sitting outside a ``YYYY/MM/DD`` directory.
        silent: tree-qualified markdown entries carrying no ``created:`` field at all.
        disagreements: tree-qualified path to the date its header claims, which is the part a pin
            must carry -- a name alone cannot say whether the header moved or the directory did.

    """

    trees: tuple[str, ...]
    entries_read: int
    undated: tuple[str, ...]
    silent: tuple[str, ...]
    disagreements: Mapping[str, str]


def memory_trees(root: Path, *, not_walked: Collection[str]) -> tuple[str, ...]:
    """Every ``.claude/memory`` directory under *root*, FOUND BY WALKING rather than read from a list.

    The walk is the point: the declaration it is compared against is what the repo believes, and a
    tree that appeared is precisely the thing a declaration cannot report about itself.

    Args:
        root: the checkout to walk.
        not_walked: directory NAMES never descended into. NO DEFAULT -- one repo must skip a
            vendored ``node_modules``, a Rust ``target`` and a sibling checkout that answers for
            itself, and another has none of them. A guessed set does not raise; it makes the walk
            quietly smaller, which is the failure this module's floor exists to catch one layer down.

    Returns:
        Repo-relative POSIX paths, sorted by walk order, for comparison against the named set.

    """
    found: list[str] = []
    skip = frozenset(not_walked)

    def walk(directory: Path) -> None:
        for path in sorted(directory.iterdir()):
            if not path.is_dir() or path.name in skip:
                continue
            if path.name == 'memory' and path.parent.name == '.claude':
                found.append(path.relative_to(root).as_posix())
            else:
                walk(path)

    walk(root)
    return tuple(found)


def entries(tree: Path, *, non_entry_names: Collection[str], not_walked: Collection[str]) -> tuple[Path, ...]:
    """Every shared memory file under *tree*: the POPULATION every floor below is bound against.

    Args:
        tree: one memory tree.
        non_entry_names: filenames that are not a record somebody wrote -- tooling debris that
            reaches no index, and the placeholder that keeps an empty tree tracked. NO DEFAULT: this
            set REMOVES files from the population, so a guessed one shrinks the scan silently and a
            real fork is not in it anyway.
        not_walked: directory names whose contents are not entries, e.g. ``__pycache__``.

    Returns:
        Sorted absolute paths. An empty result is a legitimate reading and is NOT refused here --
        that is the entry floor's job, in
        :func:`lab_commons.dev.famtests.datedmemory.assert_every_entry_is_dated`, which is where the
        caller's number is.

    """
    skipped_names = frozenset(non_entry_names)
    skipped_dirs = frozenset(not_walked)
    return tuple(
        sorted(
            path
            for path in tree.rglob('*')
            if path.is_file()
            and path.name not in skipped_names
            and not skipped_dirs.intersection(path.relative_to(tree).parts)
        )
    )


def _inner(tree: Path, path: Path) -> tuple[str, ...]:
    """*path*'s parts relative to *tree* -- the only thing every reader below asks about a path."""
    return path.relative_to(tree).parts


def _dated(parts: tuple[str, ...]) -> bool:
    """Whether *parts* opens with a date AND has something under it. Nesting BELOW the date is fine."""
    return len(parts) > DATE_DEPTH and all(part.isdigit() for part in parts[:DATE_DEPTH])


def undated(tree: Path, files: Iterable[Path]) -> tuple[str, ...]:
    """THE SHAPE READING. Files whose first three parts are not a date, whatever put them there."""
    return tuple(sorted(Path(*_inner(tree, p)).as_posix() for p in files if not _dated(_inner(tree, p))))


def silent(tree: Path, files: Iterable[Path]) -> tuple[str, ...]:
    """Markdown entries with NO ``created:`` field -- entries whose date only the path asserts.

    Kept separate from :func:`date_disagreements` rather than folded in as a reason string: they are
    two populations, and a pin over a mixture cannot say which half moved. Only DATED markdown is
    asked, because an undated file is already named by :func:`undated` and naming it twice would let
    one fix red two arms.
    """
    out = []
    for path in files:
        parts = _inner(tree, path)
        if path.suffix != '.md' or not _dated(parts):
            continue
        if _CREATED.search(path.read_text(encoding='utf-8', errors='replace')) is None:
            out.append(Path(*parts).as_posix())
    return tuple(sorted(out))


def date_disagreements(tree: Path, files: Iterable[Path]) -> dict[str, str]:
    """THE FRONTMATTER READING: entries whose ``created:`` field CONTRADICTS the directory.

    An entry carried forward into a new day keeps its old header, and the header is the only one of
    the two dates a reader ever sees. A missing field is NOT a disagreement -- see :func:`silent`.

    Returns:
        ``{path: the date the header claims}``. The wrong date is part of the row because a name
        alone cannot tell a copied-forward header from a moved directory.

    """
    out: dict[str, str] = {}
    for path in files:
        parts = _inner(tree, path)
        if path.suffix != '.md' or not _dated(parts):
            continue
        found = _CREATED.search(path.read_text(encoding='utf-8', errors='replace'))
        if found is not None and found.groups() != parts[:DATE_DEPTH]:
            out[Path(*parts).as_posix()] = '-'.join(found.groups())
    return out


def take_scan(
    root: Path,
    *,
    trees: Collection[str],
    non_entry_names: Collection[str],
    not_walked: Collection[str],
) -> MemoryScan:
    """Walk every declared tree ONCE and return the reading all four arms share.

    Args:
        root: the checkout the declared trees are named relative to. NO DEFAULT -- a body resolving
            this itself would answer about whichever tree it happened to be installed into, which is
            the one mistake this whole package exists to stop making.
        trees: the repo's declared memory trees, repo-relative POSIX.
        non_entry_names: see :func:`entries`.
        not_walked: see :func:`entries`.

    Returns:
        A :class:`MemoryScan` whose offender paths are TREE-QUALIFIED, so a repo with five trees can
        pin one set and still say which tree each row is in.

    """
    declared = tuple(trees)
    read = 0
    forked: list[str] = []
    quiet: list[str] = []
    disagreeing: dict[str, str] = {}
    for name in declared:
        tree = root / Path(name)
        if not tree.is_dir():
            continue
        found = entries(tree, non_entry_names=non_entry_names, not_walked=not_walked)
        read += len(found)
        forked += [f'{name}/{row}' for row in undated(tree, found)]
        quiet += [f'{name}/{row}' for row in silent(tree, found)]
        disagreeing |= {f'{name}/{row}': date for row, date in date_disagreements(tree, found).items()}
    return MemoryScan(
        trees=declared,
        entries_read=read,
        undated=tuple(sorted(forked)),
        silent=tuple(sorted(quiet)),
        disagreements=disagreeing,
    )
