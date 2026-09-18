"""EVERY INJECTED DOCUMENT FITS THE WIDTH -- the VERDICTS over :mod:`lab_commons.dev.docwidth`.

WHAT THE CONSUMER'S FILE ASSERTS. Prose an agent is handed on every turn pays its width on every
turn, and a LINE-COUNT ratchet cannot see that: a line is one unit of the pin no matter how long it
is, so a rewrite can double a page's width while LOWERING its count and the count-based guard reads
the change as an improvement. The scan, the corpus definition, the ceiling and the two-sided ratchet
belong to :mod:`lab_commons.dev.docwidth` and are not restated here. What was missing is everything a
consumer had to write around them, and the three copies of it are near-twins.

THREE CONSUMERS: both labs' ``tests/architecture/test_injected_doc_width_ceiling.py`` and motronics'
under ``tests/architecture/docs/``. The labs' two share their arm names in order and differ in four
values -- the corpus, the floor, the declared set, and whether there is a CEILING on that declaration
at all. Every one arrives as a keyword argument with NO DEFAULT.

**THE DECLARED SET IS KEYED BY SITE, NOT BY FILE, AND THAT IS THIS MODULE'S SHARPEST EDGE AGAINST**
:mod:`lab_commons.dev.famtests.trackedcjk`. There a waiver names a FILE; here it names ``path:line``.
The two guards' consumer files share five of their nine arm names, so the shapes are close enough to
copy -- and a declaration copied in the wrong shape does not fall silent, it ORPHANS every entry, so
the ratchet reds LOUDLY for a reason that is not the real one and the cheapest-looking repair is to
delete a true declaration. :func:`assert_the_declaration_is_the_shape_the_ratchet_keys_on` is the arm
that refuses it, and its mirror lives in ``trackedcjk``; the pair is why neither guard is the other
one's body. See that module's docstring for the three measurements that decided it -- foremost that
``dev.cjk`` and ``dev.docwidth`` publish 12 and 14 names with an EMPTY intersection.

**A CEILING ON THE ESCAPE HATCH, AND IT IS THE ONE PLACE A ZERO IS LEGAL.** One repo pins its
over-width declaration at 23 and may only lower it; the other declares an empty set and has no pin at
all, which is the waiver-nothing-uses shape pointing the other way -- nothing stops that set growing
one justified line at a time. So ``declared_ceiling`` is REQUIRED, and ``0`` is a legitimate value
meaning "empty, and it stays empty". That is the opposite of a FLOOR, where
:exc:`lab_commons.dev.floors.FloorMisdeclared` refuses zero because a floor of zero refuses nothing.
A ceiling of zero refuses everything, which is the strongest statement a repo with a clean tree can
make; the asymmetry is stated here because the two numbers sit side by side in a caller's signature
and look interchangeable.

THE FLOOR IS TAKEN ON BOTH SIDES, where every consumer takes only the low one through
:func:`lab_commons.dev.docwidth.assert_width_floor`. Two of the three pin their floor AT the
measurement -- 2 and 25 -- on the argument that this corpus only grows. That argument is right about
the corpus and wrong about the number: a floor pinned at the exact count reds on the next page ADDED,
which is the count-pin failure, and the honest-looking repair is to edit the digit. Routing through
:mod:`lab_commons.dev.floors` gives a band instead, and a ``what`` that has no default.

WHAT THIS DOES NOT PROVE. It says nothing about how many lines a page has --
:mod:`lab_commons.dev.famtests.rulespages` owns that dimension over an overlapping corpus, with its
own per-page ratchet and its own total budget, and a repo adopting this body wants that one as well.
Nor does it know which documents a repo actually injects: that is three data sets in
:mod:`lab_commons.dev.docwidth`, passed through here, and a corpus narrowed until it matches nothing
is refused by the floor rather than by any claim made here.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from lab_commons.dev import docwidth, floors

if TYPE_CHECKING:
    from collections.abc import Collection, Iterable
    from pathlib import Path

__all__ = [
    'MisdeclaredSite',
    'OverwideDeclaration',
    'OverwidthDocument',
    'assert_the_declaration_is_the_shape_the_ratchet_keys_on',
    'assert_the_scanner_still_convicts',
    'assert_widths_are_the_named_set',
    'take_scan',
]


class OverwidthDocument(AssertionError):
    """An injected document carries a line past the ceiling that no declaration names, or the reverse."""


class OverwideDeclaration(AssertionError):
    """The declared set of over-width sites is larger than the repo's own ceiling on it."""


class MisdeclaredSite(AssertionError):
    """A declared waiver is not a ``path:line`` site, so it can only ever orphan."""


def take_scan(paths: Iterable[Path], *, root: Path, ceiling: int) -> docwidth.WidthScan:
    """Read *paths* once, naming every site relative to *root*. One walk, under the name the arms use.

    Args:
        paths: the consumer's OWN injected-doc corpus, narrowed by
            :func:`lab_commons.dev.docwidth.injected_docs` from what git tracks. NO DEFAULT and no
            walk here: a corpus this module guessed would read a directory that is not there and
            report clean, which is the silence the floor below exists to refuse.
        root: what a site is named relative to, so a refusal is checkable on another box.
        ceiling: the column a line may not exceed. NO DEFAULT even though
            :data:`lab_commons.dev.docwidth.WIDTH_CEILING` is 120 in every repo measured -- a
            consumer that inherits it has never said it agrees, and a repo tightening it must be able
            to without editing the kit.

    Returns:
        A :class:`lab_commons.dev.docwidth.WidthScan`, whose ``undecodable`` is NAMED rather than
        counted: a file that could not be read is not evidence of a compliant one.

    """
    return docwidth.scan_widths(paths, ceiling=ceiling, root=root)


def assert_widths_are_the_named_set(
    scan: docwidth.WidthScan,
    *,
    declared: Collection[str],
    declared_ceiling: int,
    floor: int,
    headroom: int,
    what: str,
) -> None:
    """THE CHECK: the floor on both sides, then the two-sided ratchet, then the ceiling on the hatch.

    The order is the property. A corpus that stopped being matched reports exactly what a compliant
    one reports, so the reading is proved to be a reading first; the ratchet then says which sites
    moved in either direction; and the ceiling last, because it is a statement about the DECLARATION
    rather than about the tree, and a reader meeting it should already know the tree is understood.

    Args:
        scan: what :func:`take_scan` returned.
        declared: the repo's named set of ``path:line`` sites still over width -- its ledger, keyed
            exactly as :func:`lab_commons.dev.docwidth.width_ratchet` keys its own. An undeclared
            site reds; a declared site that was rewrapped reds too, so the set can only shrink.
        declared_ceiling: the largest that set may be. NO DEFAULT, and ``0`` is LEGAL and is the
            strongest value -- see the module docstring for why this is the opposite of a floor.
        floor: the consumer's MEASURED count of injected documents READ. NO DEFAULT: measured
            2026-09-18, two consumers read 2 and 25.
        headroom: how far past that floor the corpus may grow before the floor is re-measured. NO
            DEFAULT, and it is the argument that replaces pinning the floor AT the measurement --
            which two of the three consumers do today, and which reds on the next page added.
        what: names the guard in the floor refusals. NO DEFAULT -- an inherited label sends a reader
            to a guard that did not fail.

    Raises:
        lab_commons.dev.floors.FloorUnmet: fewer documents were read than the floor.
        lab_commons.dev.floors.SlackFloor: the floor has stopped binding and must be re-measured.
        OverwidthDocument: the ratchet moved in either direction.
        OverwideDeclaration: the declaration is larger than the ceiling the repo set on it.

    """
    floors.assert_floor(scan.files_read, floor=floor, what=what)
    floors.assert_floor_still_binds(scan.files_read, floor=floor, headroom=headroom, what=what)
    problems = docwidth.width_ratchet(scan.overwidth, declared)
    if problems:
        raise OverwidthDocument('\n  '.join(('the injected-doc width ratchet moved:', *problems)))
    if len(declared) > declared_ceiling:
        msg = (
            f'{len(declared)} over-width sites are declared against a ceiling of {declared_ceiling}. Every '
            f'one is prose an agent loads on every turn and pays for each time, so this number may only go '
            f'DOWN: rewrap a line, delete its entry and lower the ceiling in the same edit. A hatch with no '
            f'ceiling grows one justified line at a time and nobody ever chose its size.'
        )
        raise OverwideDeclaration(msg)


def assert_the_declaration_is_the_shape_the_ratchet_keys_on(declared: Collection[str]) -> None:
    """A waiver that is not ``path:line`` can ONLY orphan, so the ratchet reds for the wrong reason.

    THE MIRROR OF :func:`lab_commons.dev.famtests.trackedcjk.assert_the_declaration_is_the_shape_the_ratchet_keys_on`,
    and the pair is the mechanism that keeps those two guards apart. There a waiver names a FILE and a
    line number is the misdeclaration; here a bare path is. The two consumer files are close enough to
    copy from one another, and a copied declaration passes every other arm in either file.

    Raises:
        MisdeclaredSite: an entry is not ``<repo-relative POSIX path>:<line>``.

    """
    wrong = []
    for entry in sorted(declared):
        path, _, line = entry.rpartition(':')
        if not path or not line.isdigit() or '\\' in entry or entry.startswith(('/', './')):
            wrong.append(entry)
    if wrong:
        msg = (
            f'{wrong} cannot key the found set: a width waiver names a SITE, spelled '
            f'<repo-relative POSIX path>:<line>, with no backslash and no leading dot-slash. A bare path -- '
            f'which is exactly what the CJK ledger next door holds -- matches nothing here, so it reports as '
            f'ORPHANED, loudly and for the wrong reason.'
        )
        raise MisdeclaredSite(msg)


def assert_the_scanner_still_convicts(plant_root: Path, *, ceiling: int) -> None:
    """THE PLANTED CONTROL, in BOTH directions, driving the REAL scanner over a REAL tree.

    The distinctions are planted together because each is only meaningful beside its neighbour: a line
    ONE column over the ceiling must be named with its measured width, a line exactly AT the ceiling
    must not be, and a second over-width line in the same file must appear as its OWN site rather than
    folding into a per-file verdict -- that last one is what makes the ledger a set of sites at all.

    A BOUNDARY IS PLANTED AT THE CEILING, not near it. ``>`` and ``>=`` are one character apart and
    both read as correct; only a line of exactly *ceiling* columns can tell them apart, and it is the
    line a repo sitting at a measured maximum of 99 against a ceiling of 120 would never produce.

    THE AXIS THIS CONTROL IS BLIND TO: it plants a TREE and proves nothing about the CORPUS. A
    consumer whose injected-doc narrowing matches nothing -- a basename set that lost ``AGENTS.md``, a
    prefix that stopped matching nested pages -- passes every arm here. That axis belongs to the floor
    in :func:`assert_widths_are_the_named_set` and to
    :func:`lab_commons.dev.docwidth.is_injected_doc`, which this control deliberately does not re-test.

    Args:
        plant_root: an empty directory to plant into -- a consumer's ``tmp_path``. Taken as an
            argument so the control drives the SHIPPED scanner rather than a re-implementation.
        ceiling: the consumer's own ceiling, so the boundary is planted where THIS repo draws it.

    Raises:
        AssertionError: the scanner missed a planted site, named a compliant line, or lost a width.

    """
    at_ceiling = 'a' * ceiling
    over = 'b' * (ceiling + 1)
    (plant_root / 'AGENTS.md').write_text(f'{at_ceiling}\n{over}\nshort\n{over}\n', encoding='utf-8')
    (plant_root / 'CLAUDE.md').write_text(f'{at_ceiling}\nalso short\n', encoding='utf-8')

    scan = take_scan(sorted(plant_root.glob('*.md')), root=plant_root, ceiling=ceiling)
    sites = [(hit.path, hit.line, hit.width) for hit in scan.overwidth]
    if sites != [('AGENTS.md', 2, ceiling + 1), ('AGENTS.md', 4, ceiling + 1)]:
        msg = (
            f'the scanner named {sites}. Exactly the two lines ONE column over the {ceiling} ceiling must '
            f'come back, each as its own site with its measured width; the two lines sitting exactly AT the '
            f'ceiling must not, which is the only planting that tells > from >=; and the second offender in '
            f'one file must appear separately, or the ledger is keyed by file and not by site.'
        )
        raise AssertionError(msg)
    if docwidth.width_ratchet(scan.overwidth, ()) == ():
        msg = 'the ratchet stayed silent over two undeclared over-width sites, so it convicts nothing'
        raise AssertionError(msg)
    if docwidth.width_ratchet(scan.overwidth, ('AGENTS.md:2', 'AGENTS.md:4')) != ():
        msg = 'a fully declared ledger must fall silent, or the ratchet refuses the state it exists to reach'
        raise AssertionError(msg)
    if docwidth.width_ratchet(scan.overwidth, ('AGENTS.md',)) == ():
        msg = (
            'a FILE-keyed entry -- the shape the CJK ledger uses -- must not satisfy this ratchet. It has to '
            'orphan, which is the failure assert_the_declaration_is_the_shape_the_ratchet_keys_on refuses '
            'earlier and louder.'
        )
        raise AssertionError(msg)
