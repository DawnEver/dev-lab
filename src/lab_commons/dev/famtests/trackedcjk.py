"""NO CJK IN TRACKED SOURCE -- the VERDICTS over :mod:`lab_commons.dev.cjk`'s readings, and the control.

WHAT THE CONSUMER'S FILE ASSERTS. Across every repo in this family, no content git tracks may contain
CJK characters, outside the three exempt prefixes :data:`lab_commons.dev.cjk.EXEMPT_PREFIXES` names.
The scan, the ranges, the exemption match and the two-sided ratchet are all
:mod:`lab_commons.dev.cjk`'s and are not restated here; what was missing was everything a consumer
still had to write around them, and the three copies of it measure as near-twins.

THREE CONSUMERS, and the two labs' copies share their test-function NAMES line for line -- the same
nine, in the same order. The third is motronics' under ``tests/architecture/docs/``. What differs
between them is four repo-shaped facts and nothing else: the corpus, the floor, its headroom, and the
declared set. Every one of them arrives as a keyword argument with NO DEFAULT.

**THIS IS NOT THE BODY THE INJECTED-DOC WIDTH GUARD NEEDS**, and the question was settled before this
module was written rather than after. That guard's assertion half is still UNWRITTEN -- there is no
``famtests`` module to point at, which is exactly why the two were priced as possibly one. Their
consumer files really do share five of their nine arm names. One body for both was refused on three
measured differences, not on taste:

* THE SURFACES THEY SIT ON SHARE NO NAME AT ALL. Measured 2026-09-18, ``lab_commons.dev.cjk``
  publishes 12 names and ``lab_commons.dev.docwidth`` publishes 14, and the intersection is EMPTY --
  ``scan_files``/``scan_widths``, ``ratchet``/``width_ratchet``, ``remedy``/``width_remedy``. They are
  deliberate parallels, not one surface with two entry points.
* THE DECLARED SET IS KEYED DIFFERENTLY, which is a behaviour difference and not a spelling one. Here
  a waiver names a FILE; there it names a ``path:line`` SITE. A body taking the key as an argument
  would let a repo declare one guard's shape to the other, and the failure is silent in the direction
  that matters: every entry orphans, so the ratchet reds loudly for the wrong reason and the honest-
  looking repair is to delete the declaration.
* ONLY ONE OF THEM HAS A CEILING ON ITS ESCAPE HATCH. One repo pins a maximum size for its over-width
  declaration; no repo has one for its CJK declaration, and none needs one, because the CJK
  declaration is EMPTY in every repo measured. A shared body would carry an arm two of its three
  consumers could only pass vacuously.

  What remains genuinely shared is the floor and the two-sided ratchet -- and both already have a home
  in :mod:`lab_commons.dev.floors` and in each scanner's own ``ratchet``. A third layer over two
  ten-line bodies is the abstraction that costs more than it saves.

THE FLOOR IS TAKEN ON BOTH SIDES HERE, WHERE EVERY CONSUMER TAKES ONLY THE LOW ONE. All three call
:func:`lab_commons.dev.cjk.assert_floor`, which refuses an under-read tree and says nothing about a
floor the tree has outgrown -- and one consumer sits at 500 against a measured 624 while another sits
exactly ON its measurement at 53. The first of those refuses only a total collapse today. So this body
routes through :mod:`lab_commons.dev.floors` instead, which has both sides, and whose ``what`` has no
default: ``cjk.assert_floor`` defaults its label to ``'CJK'``, and a second scan inheriting that label
sends a reader to a guard that did not fail.

THE CONTROL PLANTS A CJK CHARACTER AND THIS FILE CONTAINS NONE, which is the one place the guard must
not convict itself. :mod:`lab_commons.dev.cjk` already solved this for a consumer by scanning FILE
TEXT taken verbatim, so a backslash-u escape is eight plain ASCII characters and passes on its own.
This module does not need even that: it builds the planted character with :func:`chr` from a code
point in :data:`lab_commons.dev.cjk.CJK_RANGES`, so the ranges stay DERIVED -- widening them widens the
control -- and nothing that looks like CJK appears in the source at all.
:func:`assert_the_source_is_itself_clean` is the arm that keeps that true rather than asserted, and it
takes the CONSUMER's file through ``also`` because the consumer's file is subject to the same
obligation and was carrying a hand-written copy of this arm to say so.

WHAT THIS DOES NOT PROVE. It says nothing about which files a repo tracks -- a corpus handed over
empty clears every arm but the floor, which is exactly what the floor is for -- and nothing about
whether a translation kept the meaning of the text it replaced. A guard cannot read prose.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from lab_commons.dev import cjk, floors

if TYPE_CHECKING:
    from collections.abc import Collection, Iterable

__all__ = [
    'MisdeclaredWaiver',
    'NonAsciiRemains',
    'OrphanedTranslation',
    'UndeclaredCjk',
    'assert_every_translation_has_its_source',
    'assert_no_tracked_non_ascii',
    'assert_no_undeclared_cjk',
    'assert_the_declaration_is_the_shape_the_ratchet_keys_on',
    'assert_the_exemptions_match_a_path_segment',
    'assert_the_scanner_still_convicts',
    'assert_the_source_is_itself_clean',
    'take_scan',
]

#: A code point inside :data:`lab_commons.dev.cjk.CJK_RANGES`, reached through :func:`chr` so that no
#: CJK character is ever written into this file. DERIVED from the shared ranges rather than typed, so
#: a range list that is narrowed until it matches nothing takes the control down with it instead of
#: leaving it green.
_PLANTED_POINT = cjk.CJK_RANGES[2][0]


class UndeclaredCjk(AssertionError):
    """A tracked, non-exempt file carries CJK that no declaration names, or a waiver outlived its file."""


class OrphanedTranslation(AssertionError):
    """A ``<stem>.zh.md`` translation is tracked without the English ``<stem>.md`` it must render."""


class NonAsciiRemains(AssertionError):
    """The corpus still carries non-ASCII characters; the message is the DISTANCE to the final goal."""


class MisdeclaredWaiver(AssertionError):
    """A declared waiver is spelled in a shape the ratchet cannot key on, so it can only ever orphan."""


def take_scan(paths: Iterable[Path], *, root: Path, exempt_prefixes: Collection[str]) -> cjk.Scan:
    """Read *paths* once, naming every record relative to *root*. One walk, under the name the arms use.

    Args:
        paths: the consumer's OWN corpus -- ``git ls-files`` through
            :func:`lab_commons.dev.rules.tracked_files` in every repo measured, never a walk of the
            working tree. NO DEFAULT: a file present in one checkout is not a file the fleet has, and
            a guessed corpus does not raise, it reads an empty list and reports clean.
        root: what a record is named relative to, so a refusal is checkable on another box.
        exempt_prefixes: where CJK is permitted without a declaration. NO DEFAULT even though
            :data:`lab_commons.dev.cjk.EXEMPT_PREFIXES` exists and every consumer passes exactly it --
            an exemption set is the one argument whose wrong value WIDENS the silence, and a repo that
            inherits it has never said it agrees.

    Returns:
        A :class:`lab_commons.dev.cjk.Scan`, whose ``exempted`` and ``undecodable`` are NAMED rather
        than counted: "could not be decoded" is not evidence of "contains no CJK".

    """
    return cjk.scan_files(paths, exempt_prefixes=exempt_prefixes, root=root)


def assert_no_undeclared_cjk(
    scan: cjk.Scan,
    *,
    declared: Collection[str],
    floor: int,
    headroom: int,
    what: str,
) -> None:
    """THE CHECK, with the floor bound on BOTH sides before one occurrence is looked at.

    The order is the property. A clean tree and an unread one produce the identical empty occurrence
    list, so the reading is proved to be a reading first; and a floor the corpus has long outgrown
    proves only that the tree did not vanish entirely, which is why the second side is taken here
    where no consumer takes it.

    Args:
        scan: what :func:`take_scan` returned.
        declared: the repo's own named set of files still carrying CJK -- its migration ledger, keyed
            by FILE exactly as :func:`lab_commons.dev.cjk.ratchet` keys its own. Two-sided: an
            undeclared file reds, and a declared file that has been cleaned reds too. An EMPTY set is
            legal and is the state every repo in this family measures today; what stops it being
            vacuous is the floor above, not a refusal of the empty set.
        floor: the consumer's MEASURED count of files the scan READS -- the number after exemptions
            and undecodable files come off. NO DEFAULT: measured 2026-09-18, two consumers read 624
            and 53 files.
        headroom: how far past that floor the corpus may grow before the floor is re-measured. NO
            DEFAULT, and it is the argument this family has least often written down: a floor of 500
            against 624 files is 124 clear, and a walk losing four fifths of that corpus would still
            clear it.
        what: names the guard in the floor refusals. NO DEFAULT -- see the module docstring for the
            default label that misdirects.

    Raises:
        lab_commons.dev.floors.FloorUnmet: fewer files were read than the floor.
        lab_commons.dev.floors.SlackFloor: the floor has stopped binding and must be re-measured.
        UndeclaredCjk: the ratchet moved in either direction.

    """
    floors.assert_floor(scan.files_read, floor=floor, what=what)
    floors.assert_floor_still_binds(scan.files_read, floor=floor, headroom=headroom, what=what)
    problems = cjk.ratchet(scan.occurrences, declared)
    if problems:
        raise UndeclaredCjk('\n  '.join(('the CJK ratchet moved:', *problems)))


def assert_the_declaration_is_the_shape_the_ratchet_keys_on(declared: Collection[str]) -> None:
    """A waiver spelled in the wrong shape can ONLY orphan, so the ratchet reds for the wrong reason.

    :func:`lab_commons.dev.cjk.ratchet` keys its found set by repo-relative POSIX PATH. An entry
    carrying a line number, a backslash, or a leading ``./`` matches nothing it could ever have been
    about; the arm still fires, which is why this is not caught by testing that the guard fails, and
    the reader's cheapest repair is to delete the entry that was trying to say something true.

    THIS IS WHERE THIS GUARD AND THE WIDTH GUARD DIVERGE MOST, and the check is what keeps that from
    being prose: there a site IS ``path:line`` and a bare path is the misdeclaration. Copying one
    repo's declaration into the other guard would pass every other arm in either file.

    Raises:
        MisdeclaredWaiver: an entry cannot be a key of the found set.

    """
    wrong = sorted(
        entry
        for entry in declared
        if '\\' in entry or entry.startswith(('/', './')) or entry.rsplit(':', 1)[-1].isdigit()
    )
    if wrong:
        msg = (
            f'{wrong} cannot key the found set: a CJK waiver names a repo-relative POSIX FILE, with no '
            f'line number, no backslash and no leading dot-slash. An entry in any other shape matches '
            f'nothing, so it reports as ORPHANED -- loudly, and for the wrong reason.'
        )
        raise MisdeclaredWaiver(msg)


def assert_the_exemptions_match_a_path_segment(exempt_prefixes: Collection[str]) -> None:
    """Nested exempt dirs match, a ROOT-ANCHORED one matches only at the root, a lookalike never.

    The measured reason is in :data:`lab_commons.dev.cjk.EXEMPT_PREFIXES`: one repo's memory tree is
    scoped per module and a root-only prefix reported 47,521 CJK characters where the true answer is
    zero. The opposite error is as fatal and is planted beside it -- a substring match would exempt
    ``notattic/`` and open an island nobody declared. An ANCHORED prefix (leading ``/``, e.g.
    ``/archived/``) is planted both ways: ``archived/f.py`` exempt and ``x/archived/f.py`` NOT.

    Raises:
        AssertionError: a prefix fails to match where it must, or matches where it must not.

    """
    for prefix in exempt_prefixes:
        anchored = prefix.startswith('/')
        bare = prefix.lstrip('/')
        stem = bare.rstrip('/')
        nested = cjk.exempted(f'src/pkg/{bare}note.md', exempt_prefixes)
        if anchored and nested:
            msg = f'{prefix!r} is ROOT-ANCHORED yet matched src/pkg/{bare}; a nested {bare} is not exempt'
            raise AssertionError(msg)
        if not anchored and not nested:
            msg = f'{prefix!r} is not matched as a nested path SEGMENT; a scoped tree would be scanned wrongly'
            raise AssertionError(msg)
        if not cjk.exempted(f'{bare}note.md', exempt_prefixes):
            msg = f'{prefix!r} is not matched at the ROOT, where every repo in this family also puts it'
            raise AssertionError(msg)
        if cjk.exempted(f'not{stem}/note.md', exempt_prefixes):
            msg = f'{prefix!r} matched not{stem}/, so the exemption is a substring test and excuses a tree nobody named'
            raise AssertionError(msg)


def assert_every_translation_has_its_source(corpus: Collection[str]) -> None:
    """``TRANSLATION-HAS-ITS-SOURCE``: every tracked ``<stem>.zh.md`` has its English ``<stem>.md``.

    The translation is exempt from the CJK guard only BESIDE its source, and the scan already reads
    an orphan like any other file -- this arm is what names the orphan AS an orphan, with the remedy,
    instead of leaving it to surface as one more anonymous CJK hit someone is tempted to declare.

    Args:
        corpus: the consumer's repo-relative tracked names -- the same corpus its scan reads.

    Raises:
        OrphanedTranslation: a translation has no English source in *corpus*.

    """
    problems = cjk.orphaned_translations(corpus)
    if problems:
        raise OrphanedTranslation('\n  '.join(('a translation without its source:', *problems)))


def assert_no_tracked_non_ascii(scan: cjk.NonAsciiScan, *, floor: int, what: str) -> None:
    """THE FINAL GOAL: no non-ASCII character in the corpus. FAILS, stating the distance, until it holds.

    The floor comes first for the reason it does everywhere: an unread corpus has no non-ASCII either.
    The failure message IS :func:`lab_commons.dev.cjk.non_ascii_distance` -- total characters, file
    count, the per-class breakdown and the top offending files -- because the user asked for the gap
    to be shown AS a test error, and a red that does not say how far is only a colour.

    Raises:
        lab_commons.dev.floors.FloorUnmet: fewer files were read than *floor*.
        NonAsciiRemains: any non-ASCII character remains.

    """
    floors.assert_floor(scan.files_read, floor=floor, what=what)
    if scan.total:
        msg = f'{what}: the corpus is not yet all-ASCII. Distance to the goal:\n{cjk.non_ascii_distance(scan)}'
        raise NonAsciiRemains(msg)


def assert_the_scanner_still_convicts(plant_root: Path, *, exempt_prefixes: Collection[str]) -> None:
    """THE PLANTED CONTROL, in BOTH directions, driving the REAL scanner over a REAL tree.

    Four files are planted at once, because each of the scanner's distinctions is only meaningful
    against its neighbour: a dirty file must be NAMED at the right line and column; a clean ASCII file
    must not be; a file under an exempt prefix must be EXEMPTED rather than read; and a file spelling
    the character as a backslash-u ESCAPE must pass, because that escape is the remedy
    :func:`lab_commons.dev.cjk.remedy` recommends and a scanner convicting its own remedy is worse
    than one that convicts nothing.

    NO CJK CHARACTER IS WRITTEN INTO THIS FILE. The planted one is built with :func:`chr` from
    :data:`lab_commons.dev.cjk.CJK_RANGES`, so it stays DERIVED from the shared ranges and this
    module's own source is plain ASCII -- which :func:`assert_the_source_is_itself_clean` then holds,
    over this module AND over the consumer file it is handed.

    THE AXIS THIS CONTROL IS BLIND TO: it plants a TREE and proves nothing about the CORPUS. A
    consumer whose ``tracked_files`` call answers an empty list, or drops every file under one
    directory, passes every arm here unchanged. That axis belongs to the two floors in
    :func:`assert_no_undeclared_cjk`, and it is a different argument entirely.

    Args:
        plant_root: an empty directory to plant into -- a consumer's ``tmp_path``. Taken as an
            argument so the control drives the SHIPPED scanner rather than a re-implementation.
        exempt_prefixes: the consumer's own exemption set, so the exempt arm exercises the prefixes
            THIS repo declares. The first prefix is the one planted under.

    Raises:
        AssertionError: the scanner missed the planted character, named an honest neighbour, read an
            exempt file, or convicted the escape sequence it recommends.

    """
    prefixes = list(exempt_prefixes)
    if not prefixes:
        msg = 'the control was handed no exempt prefixes, so its exemption arm would assert nothing at all'
        raise AssertionError(msg)
    char = chr(_PLANTED_POINT)
    dirty = plant_root / 'dirty.md'
    dirty.write_text(f'first line\nahead {char} behind\n', encoding='utf-8')
    (plant_root / 'clean.md').write_text('plain ASCII prose, and it stays that way\n', encoding='utf-8')
    (plant_root / 'escaped.py').write_text('REJECTED = "\\u4e00"  # the remedy, in eight ASCII characters\n', 'utf-8')
    exempt = plant_root / prefixes[0].lstrip('/') / 'note.md'
    exempt.parent.mkdir(parents=True, exist_ok=True)
    exempt.write_text(f'{char}\n', encoding='utf-8')

    # FILES ONLY, and the bug that taught it: `rglob('*.*')` matches the DIRECTORY `.claude` too, and
    # the scanner reads what it is handed, so the control died on a PermissionError instead of
    # reporting. A corpus is a list of files -- every consumer's `tracked_files` already is one.
    planted_files = sorted(path for path in plant_root.rglob('*') if path.is_file())
    scan = take_scan(planted_files, root=plant_root, exempt_prefixes=prefixes)
    named = [(hit.path, hit.line, hit.col) for hit in scan.occurrences]
    if named != [('dirty.md', 2, 7)]:
        msg = (
            f'the scanner named {named} and the only planted offender is dirty.md line 2 column 7, both '
            f'1-based. The ASCII neighbour must stay unnamed, the backslash-u ESCAPE must pass -- it is '
            f'the remedy this family recommends, and a scanner reading escape sequences would refuse it '
            f'-- and the exempt file must not be read at all.'
        )
        raise AssertionError(msg)
    if exempt.relative_to(plant_root).as_posix() not in scan.exempted:
        msg = (
            f'the exempt file is missing from {scan.exempted}. An exemption must be RECORDED by name, '
            f'not silently folded into the clean result: excused and clean are different facts.'
        )
        raise AssertionError(msg)
    if cjk.ratchet(scan.occurrences, ()) == () or cjk.ratchet(scan.occurrences, ('dirty.md',)) != ():
        msg = 'the ratchet must convict the undeclared file and fall silent once it is declared, in that order'
        raise AssertionError(msg)


def assert_the_source_is_itself_clean(*, also: Collection[Path]) -> None:
    """The kit's module AND the consumer's file carry no non-ASCII character.

    THE HALF THIS BODY COULD NOT SEE, and it was the half that mattered. Resolving ``Path(__file__)``
    inside this module scans THE KIT'S OWN SOURCE and nothing else -- which is a real and necessary
    property (the control below plants a CJK character, so the module publishing the guard must
    survive its own scan), but it is not the property either consumer needed. Both wrote the same six
    lines beside the call to cover THEMSELVES, byte-identically, in two repos. That duplication is the
    gap: a consumer that has to hand-write an assertion the kit already reasons about is one edit away
    from writing it differently, and this family measures that drift rather than assuming it away.

    ``also`` IS REQUIRED AND HAS NO DEFAULT, on the rule the whole package runs on: a body that
    guessed would report the kit's answer as the repo's, and the guess would be silent precisely
    because the wrong answer (scan the kit) is the one this function produced before.

    ASCII, NOT MERELY OUTSIDE :data:`lab_commons.dev.cjk.CJK_RANGES`, and the consumers' own arm is
    why. Both asserted ``text.isascii()`` -- strictly stronger than the ranges -- under the reasoning
    that a guard refusing a character may not be written with one. Applying the ranges here would
    have left that stronger half in the consumer and closed nothing; the family's tracked-source
    guards are ASCII-only anyway, so the tightening costs no repo a real character. It is stated
    because it is a TIGHTENING of what this function checked yesterday, not a restatement.

    Args:
        also: the consumer's own file(s) -- in practice ``(Path(__file__),)`` from the arm that
            installs this guard. NO DEFAULT -- see above.

    Raises:
        AssertionError: this module's own source, or any file in *also*, carries a character outside
            ASCII.

    """
    sources = (Path(__file__), *also)
    offenders: list[str] = []
    for path in sources:
        text = path.read_text(encoding='utf-8')
        if not text.isascii():
            offenders.append(f'{path.name}: {"".join(sorted({char for char in text if not char.isascii()}))[:8]}')
    if offenders:
        msg = (
            f'a guard that refuses a character may not be written with one, and BOTH bodies are read '
            f'by the scan it publishes: {offenders}. The first is this kit module; anything after it '
            f'arrived through ``also``, which is the consumer file installing this guard. Spell the '
            f'character as a backslash-u ESCAPE -- eight ASCII characters, and the remedy this family '
            f'recommends -- rather than pasting it in, or the guard reds on the file that publishes it.'
        )
        raise AssertionError(msg)
