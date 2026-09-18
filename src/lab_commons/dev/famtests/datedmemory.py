"""EVERY MEMORY ENTRY SITS UNDER ITS OWN DATE -- the VERDICTS, over the readers split out beside it.

WHAT THE CONSUMER'S FILE ASSERTS. A memory tree's index is GENERATED from what is on disk, so the
PATH is the only key a reader has. A file that names itself ``.claude/memory/notes/foo.md`` is still
listed, still reads as a record, and is unreachable by date forever after. This family has already
paid for that: a writer composed its records under a literal ``lanes/`` directory, grew a
seventeen-file parallel tree beside the real one, the index builder listed every file without a word,
and it survived for days because the layout was a documented instruction. AN INSTRUCTION IS NOT A
CONTROL.

THE READINGS LIVE IN :mod:`lab_commons.dev.famtests._datedmemory_readings` and are re-exported here,
so a consumer has ONE import surface while the split stays real: everything there is a READING and
everything here is a VERDICT that adds a floor, a comparison and a remedy. That seam is not this
module's invention -- it is the one this file's own first sentence named while both halves were
still in it, and the one :mod:`lab_commons.dev.famtests._configrender_readings` already runs on next
door. The import runs ONE WAY. Why these readers are not bolted onto
:mod:`lab_commons.dev.datedlog`, which is the question this half was dispatched with, is argued in
the readings module, because it is a fact about the readers.

WHAT THE TWO CONSUMERS MEASURED, because the diff between them IS the repo boundary rather than a
guess. ``wdg-lab`` walks FIVE memory trees holding 352 entries; ``optimi-lab`` reads ONE holding a
handful, and the kit's own ``tests/test_arch_memory_lives_in_a_dated_directory.py`` reads a third
shape again. So the TREES are a named set the repo declares, the FLOOR is the repo's measurement, and
the two exclusion sets differ concretely. Every one of those arrives as a KEYWORD ARGUMENT WITH NO
DEFAULT, here and in the readings module alike.

``silent`` AND ``undated`` ARE DIFFERENT QUESTIONS AND THE THIRD IS NEITHER. An entry can be in the
right directory and decline to date itself; a file can be dated in its header and sit outside every
date. ``optimi-lab`` folded the first into ``date_disagreements`` as a string reason, ``wdg-lab``
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

from typing import TYPE_CHECKING

from lab_commons.dev import floors
from lab_commons.dev.famtests._datedmemory_readings import (
    DATE_DEPTH,
    MemoryScan,
    date_disagreements,
    entries,
    memory_trees,
    silent,
    take_scan,
    undated,
)

if TYPE_CHECKING:
    from collections.abc import Collection, Mapping
    from pathlib import Path

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


class ParallelTree(AssertionError):
    """An entry sits outside a dated directory -- the fork an index lists and no reader can reach."""


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
        scan: what :func:`lab_commons.dev.famtests._datedmemory_readings.take_scan` returned.
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

    It stays on the VERDICT side of the split because it RAISES, and it drives the readings module
    across the seam, which is the direction that makes it a control rather than a self-agreement.

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
