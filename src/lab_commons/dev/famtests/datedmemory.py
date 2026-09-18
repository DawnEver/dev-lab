"""EVERY MEMORY ENTRY SITS UNDER ITS OWN DATE -- the READERS, so the walk is not written a third time.

WHAT THE CONSUMER'S FILE ASSERTS. A memory tree's index is GENERATED from what is on disk, so the
PATH is the only key a reader has. A file that names itself ``.claude/memory/notes/foo.md`` is still
listed, still reads as a record, and is unreachable by date forever after. This family has already
paid for that: a writer composed its records under a literal ``lanes/`` directory, grew a
seventeen-file parallel tree beside the real one, the index builder listed every file without a word,
and it survived for days because the layout was a documented instruction. AN INSTRUCTION IS NOT A
CONTROL.

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
  one path -- a gate. Nothing here raises on an offender: every reader RETURNS THE SET, because both
  consumers pin their offenders as a NAMED SET compared by equality, and an exception that fires on
  the first one cannot be pinned, cannot say how many there are, and cannot be ratcheted downward.
* THEIR FLOORS DIFFER BECAUSE ONLY ONE OF THEM SCANS. ``dated_log`` has no floor and needs none; it
  reads nothing. A scan needs one or its silence is vacuous, so every arm here goes through
  :mod:`lab_commons.dev.floors` first and the floor is the consumer's own measured number.

WHAT THE TWO CONSUMERS MEASURED, because the diff between them IS the repo boundary rather than a
guess. ``wdg-lab`` walks FIVE memory trees holding 352 entries; ``optimi-lab`` reads ONE holding a
handful, and the kit's own ``tests/test_arch_memory_lives_in_a_dated_directory.py`` reads a third
shape again. So the TREES are a named set the repo declares, the FLOOR is the repo's measurement, and
the two exclusion sets differ concretely -- ``wdg-lab`` drops ``_meta.json`` AND ``.gitkeep`` and
never descends into ``node_modules``, ``target`` or a sibling checkout, where ``optimi-lab`` has
neither problem. Every one of those arrives as a KEYWORD ARGUMENT WITH NO DEFAULT. A guessed
exclusion set is the worst of them: it does not raise, it removes files from the population, and the
scan then reports clean over a tree it stopped reading.

``silent`` AND ``undated`` ARE DIFFERENT QUESTIONS AND THE THIRD IS NEITHER. An entry can be in the
right directory and decline to date itself; a file can be dated in its header and sit outside every
date. ``optimi-lab`` folded the first into :func:`date_disagreements` as a string reason, ``wdg-lab``
split it out, and the split is what this publishes -- not because one repo was right but because
folding them makes the pinned set a mixture of two populations, and a ratchet over a mixture cannot
say which half moved.

**AND "NO SILENT ENTRIES" MAY NOT BE THE SAME ANSWER AS "NO ENTRIES AT ALL."** That is the whole
reason :func:`assert_every_entry_is_dated` binds the floor BEFORE it looks at a single offender, and
why the floor is a required argument rather than a number this module chose.

WHERE THIS DELIBERATELY DIFFERS FROM :mod:`lab_commons.dev.famtests.rostercensus`, whose waiver arm
REFUSES an empty declaration. There, an empty set meant the arm had outlived its subject and had to
be deleted. Here, an empty set is a LEGITIMATE END STATE -- a tree where every entry dates itself is
the state the ratchet exists to reach and hold -- so an empty declaration is accepted and the
vacuity is closed by the entry floor instead. Copying the refusal across would have made the fixed
state unreachable, which is the same defect as a waiver nothing uses pointing the other way.

WHAT THIS DOES NOT PROVE. Nothing here reads an INDEX. The family rule also says the index is
generated from what is on disk, and neither lab's memory trees carry one; a guard asserting a
property of a file that does not exist is the vacuous green this tier refuses.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING, Final, NamedTuple

from lab_commons.dev import floors

if TYPE_CHECKING:
    from collections.abc import Collection, Iterable, Mapping

__all__ = [
    'DATE_DEPTH',
    'MemoryScan',
    'ParallelTree',
    'assert_dates_agree',
    'assert_every_entry_is_dated',
    'assert_silent_entries_are_the_named_set',
    'assert_the_readers_still_convict',
    'assert_trees_are_the_named_set',
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


class ParallelTree(AssertionError):
    """An entry sits outside a dated directory -- the fork an index lists and no reader can reach."""


class MemoryScan(NamedTuple):
    """One reading over every declared tree, taken once and shared by the arms below.

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
        that is :func:`assert_every_entry_is_dated`'s floor, which is where the caller's number is.

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


def assert_trees_are_the_named_set(root: Path, *, declared: Collection[str], not_walked: Collection[str]) -> None:
    """A tree that APPEARED is a fork; a tree that VANISHED means the scans stopped covering it.

    Compared by EQUALITY in both directions, and as a SET of names rather than a count: an integer
    cannot say which tree moved, so a swap compares equal and the honest-looking repair when the
    digit disagrees is to edit the digit.

    Raises:
        AssertionError: the walk and the declaration disagree in either direction.

    """
    found = memory_trees(root, not_walked=not_walked)
    if set(found) != set(declared):
        msg = (
            f'appeared: {sorted(set(found) - set(declared))}; declared and not found: '
            f'{sorted(set(declared) - set(found))}. An arrival is a parallel record nobody decided on; '
            f'a disappearance means every scan below silently stopped covering that tree.'
        )
        raise AssertionError(msg)


def assert_every_entry_is_dated(scan: MemoryScan, *, floor: int, headroom: int) -> None:
    """THE CHECK, and the FLOOR IS BOUND FIRST so an empty walk cannot read as a clean tree.

    Both sides of the floor are taken here rather than only the low one: a floor measured against a
    tree that has since tripled refuses nothing reachable, and the remedy is to re-measure it. See
    :mod:`lab_commons.dev.floors`.

    Args:
        scan: what :func:`take_scan` returned.
        floor: the consumer's MEASURED entry count, set below the real population. NO DEFAULT -- one
            lab measured 352 entries across five trees and the other measured a handful in one.
        headroom: how far past its floor the population may grow before the floor is re-measured.

    Raises:
        lab_commons.dev.floors.FloorUnmet: fewer entries were read than the floor.
        lab_commons.dev.floors.SlackFloor: the floor has stopped binding and must be re-measured.
        ParallelTree: at least one entry sits outside a dated directory.

    """
    floors.assert_floor(scan.entries_read, floor=floor, what='dated-memory')
    floors.assert_floor_still_binds(scan.entries_read, floor=floor, headroom=headroom, what='dated-memory')
    if scan.undated:
        msg = (
            f'{list(scan.undated)} sit outside a YYYY/MM/DD directory -- a parallel tree an index will '
            f'list and no reader will find. The date is the PATH, not a field inside the file.'
        )
        raise ParallelTree(msg)


def assert_silent_entries_are_the_named_set(scan: MemoryScan, *, declared: Collection[str]) -> None:
    """THE DEBT, two-sided: a new silent entry reds, and so does a pinned name that gained the field.

    An EMPTY declaration is ACCEPTED here, unlike the waiver in
    :mod:`lab_commons.dev.famtests.rostercensus` -- a tree where every entry dates itself is the
    state this ratchet exists to reach, and refusing the empty set would make the fixed state
    unreachable. What stops an empty set from being vacuous is the entry floor in
    :func:`assert_every_entry_is_dated`, which the consumer must have already bound.

    Raises:
        AssertionError: the measured set and the declaration disagree in either direction.

    """
    found = frozenset(scan.silent)
    pinned = frozenset(declared)
    if found != pinned:
        msg = (
            f'arrived: {sorted(found - pinned)}; fixed and still pinned: {sorted(pinned - found)}. An '
            f'entry that declines to date itself leaves the path as the only answer, and the HEADER is '
            f'the answer a reader sees. Delete a name here in the same edit that adds its field.'
        )
        raise AssertionError(msg)


def assert_dates_agree(scan: MemoryScan, *, declared: Mapping[str, str]) -> None:
    """The other half of the frontmatter property, pinned WITH the wrong date each entry claims.

    Raises:
        AssertionError: the measured mapping and the declaration differ in name OR in claimed date.

    """
    if dict(scan.disagreements) != dict(declared):
        msg = (
            f'the tree reports {dict(scan.disagreements)} against the {dict(declared)} on record. An '
            f'entry carried forward into a new day keeps its old header; pinning the DATE as well as '
            f'the name is what tells a copied header from a moved directory.'
        )
        raise AssertionError(msg)


def assert_the_readers_still_convict(plant_root: Path, *, non_entry_names: Collection[str]) -> None:
    """THE PLANTED CONTROL, in BOTH directions, driving the REAL readers over a REAL tree.

    A reader that never fires reports exactly what a clean tree reports, so the four shapes the
    readers exist to tell apart are planted at once: a fork under a literal directory, a loose file
    at the root, a stale header, and a missing one -- each beside an honest neighbour that must NOT
    be named. The nested-below-the-date file and the agreeing entry are the arms that matter most:
    without them, a reader that named everything would pass every assertion above.

    Args:
        plant_root: an empty directory to plant into -- a consumer's ``tmp_path``. Taken as an
            argument so the control drives the shipped readers rather than a re-implementation,
            which would agree with itself and prove nothing.
        non_entry_names: the consumer's own exclusion set, so the debris arm asserts about the set
            THIS repo declares rather than one this module chose.

    Raises:
        AssertionError: a reader failed to name a planted offender, or named an honest neighbour.

    """
    day = plant_root / '2026' / '09' / '18'
    (day / 'attachments').mkdir(parents=True)
    (day / 'agrees.md').write_text('---\nname: a\ncreated: 2026-09-18\n---\n# a\n', encoding='utf-8')
    (day / 'stale.md').write_text('---\nname: b\ncreated: 2026-09-04\n---\n# b\n', encoding='utf-8')
    (day / 'quiet.md').write_text('# c\n', encoding='utf-8')
    (day / 'attachments' / 'figure.txt').write_text('below the date is fine\n', encoding='utf-8')
    (plant_root / 'lanes').mkdir()
    (plant_root / 'lanes' / 'a-lane.md').write_text('---\ncreated: 2026-09-18\n---\n', encoding='utf-8')
    (plant_root / 'loose.md').write_text('---\ncreated: 2026-09-18\n---\n', encoding='utf-8')
    for name in non_entry_names:
        (day / name).write_text('{}', encoding='utf-8')

    found = entries(plant_root, non_entry_names=non_entry_names, not_walked=())
    excluded = {path.name for path in found} & frozenset(non_entry_names)
    if excluded:
        msg = f'{sorted(excluded)} entered the population and the repo declares them not entries'
        raise AssertionError(msg)
    if undated(plant_root, found) != ('lanes/a-lane.md', 'loose.md'):
        msg = (
            f'the shape reader named {undated(plant_root, found)}. The literal-directory fork and the '
            f'loose file must BOTH come back, and nesting below the date must not -- a reader that '
            f'named the nested file would make every clean tree look forked.'
        )
        raise AssertionError(msg)
    if silent(plant_root, found) != ('2026/09/18/quiet.md',):
        msg = (
            f'the silent reader named {silent(plant_root, found)}; the agreeing and the stale entry both '
            f'HAVE the field, so naming either would fold two populations into one pin.'
        )
        raise AssertionError(msg)
    if date_disagreements(plant_root, found) != {'2026/09/18/stale.md': '2026-09-04'}:
        msg = (
            f'the frontmatter reader answered {date_disagreements(plant_root, found)}. Only the '
            f'contradicting entry belongs here, and the value must be the date it CLAIMS rather than a '
            f'reason string -- a pin without the date cannot tell a copied header from a moved file.'
        )
        raise AssertionError(msg)
