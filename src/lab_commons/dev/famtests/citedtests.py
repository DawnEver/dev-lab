"""PROSE THAT POINTS AT A GUARD MUST POINT AT A GUARD THAT EXISTS -- the VERDICTS, over the READERS beside it.

WHAT THE CONSUMERS' FILES ASSERT. A comment or docstring naming ``tests/architecture/test_x.py``, or
naming ``test_x`` bare, tells every reader that a specific guard governs the thing it heads. Being
prose, nothing checks it. The family has already paid for this twice over: 200 files carried a
file-level waiver header naming a ratchet that had been deleted in a consolidation weeks earlier, and
the same sentence sat in a lint config at the repo root where the guard written for the first
incident could not see it. THIS IS THE SCOPE-LIE SHAPE AND IT IS WORSE THAN A PLAIN STALE NAME: a
reader who goes looking finds NO file and reasonably concludes the rule is unguarded -- so the prose
routes people AROUND a check that is in fact working, one directory over.

THE READINGS LIVE IN :mod:`lab_commons.dev.famtests._citedtests_readings` and are re-exported here,
so a consumer has ONE import surface while the split stays real: everything there is a READING and
everything here is a VERDICT that adds a floor, a comparison and a remedy. That seam is the one this
file's own first sentence names, and the one ``_configrender_readings`` and ``_datedmemory_readings``
already run on next door. The import runs ONE WAY.

TWO ARMS, ONE BODY, AND THE PAIR IS THE USEFUL READING RATHER THAN EITHER ALONE. The two consumer
files that produced this measure 5.45% and 0.85% repo density against a 3.0% move bar -- one over, one
under -- so a roster reading them separately says MOVE about one and STAY about the other, and the
repo ends up owning half a mechanism. What they SHARE is the walk, the prose reader, the history
exemptions and the resolution rule; what each KEEPS is which trees it walks, which files are history
keepers and its own floors. Every one of those arrives as a KEYWORD ARGUMENT WITH NO DEFAULT.

A PATH CITATION AND A NAME CITATION ARE DIFFERENT POPULATIONS AND ARE PINNED SEPARATELY, for the
reason ``datedmemory`` states about ``silent`` and ``undated``: folding them makes the pinned set a
mixture, and a ratchet over a mixture cannot say which half moved. They are also unequal in size --
measured 2026-09-18 across this family, one lab's comments carry 5 path citations against 36 name
citations and the other 1 against 15 -- so a single floor over the union would be set by the larger
population and would never notice the smaller one going silent.

TWO FLOORS ARE MANDATORY AND THE SECOND IS THE ONE NOBODY WRITES. The file-count floor says the walk
reached the tree. It says NOTHING about reaching the tree's PROSE: for weeks the originating walk
visited every file and read only its ``#`` lines, leaving 14 dangling citations sitting in docstrings,
green. :func:`assert_the_prose_half_is_reached` is that second floor, and both go through
:mod:`lab_commons.dev.floors` on BOTH sides -- a floor the population has outgrown refuses only a
collapse.

AN EXEMPTION IS PART OF THE SCAN AND IS ASSERTED LIKE ONE. :func:`assert_every_exemption_is_real`
exists because a history keeper naming a deleted file does not red -- it stops covering anything, and
a waiver nothing uses is exactly as wrong as a capability that disappears.

WHAT THIS DOES NOT PROVE. Nothing here reads Markdown. Measured in the originating repo the day the
scan was widened, the ``.md`` population of dangling citations was ZERO -- a scan there would be a
check with nothing to find, and no floor could tell that from a broken walk. A repo that measures a
non-zero population should pass its ``.md`` tree in through ``pointer_dirs``' sibling argument rather
than have this module assume one.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from lab_commons.dev import floors
from lab_commons.dev.famtests._citedtests_readings import (
    CITED_FUNCTION,
    CITED_PATH,
    comment_blocks,
    dangling_function_citations,
    dangling_path_citations,
    defined_test_functions,
    defined_test_modules,
    docstring_citation_count,
    prose_lines,
    resolves,
    scanned_files,
)

if TYPE_CHECKING:
    from collections.abc import Collection
    from pathlib import Path

__all__ = [
    'CITED_FUNCTION',
    'CITED_PATH',
    'CitedScan',
    'DanglingCitation',
    'VacuousExemption',
    'assert_every_exemption_is_real',
    'assert_no_dangling_function_citation',
    'assert_no_dangling_path_citation',
    'assert_the_prose_half_is_reached',
    'assert_the_readers_still_convict',
    'comment_blocks',
    'dangling_function_citations',
    'dangling_path_citations',
    'defined_test_functions',
    'defined_test_modules',
    'docstring_citation_count',
    'prose_lines',
    'resolves',
    'scanned_files',
    'take_scan',
]


class DanglingCitation(AssertionError):
    """Prose names a guard that resolves to nothing -- the scope lie, in the form a reader trusts."""


class VacuousExemption(AssertionError):
    """A history keeper names a file that is gone, so the exemption has stopped covering anything."""


@dataclass(frozen=True)
class CitedScan:
    """One walk of a checkout, with both offender sets and every number the floors judge.

    Taken once and handed to each arm, so the arms cannot disagree about which tree they read -- and
    so a consumer may parametrize on the readings without going through an assert that has already
    decided what the answer should be.
    """

    files_read: int
    functions_defined: int
    prose_citations: int
    dangling_paths: tuple[str, ...]
    dangling_functions: tuple[str, ...]


def take_scan(
    root: Path,
    *,
    pointer_dirs: Collection[str],
    root_configs: Collection[str],
    waiver_header: str,
    waiver_dirs: Collection[str],
    test_dir: str,
    history_keepers: Collection[str],
    history_markers: Collection[str],
    not_citations: Collection[str],
) -> CitedScan:
    """Walk *root* once and answer both questions over the same population.

    Args:
        root: the consumer's checkout.
        pointer_dirs: directories where a citation is always a POINTER -- see
            :func:`lab_commons.dev.famtests._citedtests_readings.scanned_files`. NO DEFAULT.
        root_configs: root configuration filenames to read as prose. NO DEFAULT.
        waiver_header: the file-level header that makes any file a pointer. NO DEFAULT.
        waiver_dirs: the trees searched for that header. NO DEFAULT.
        test_dir: where the tests live, as a repo-relative name -- the set every citation resolves
            against. NO DEFAULT, and it is the argument a guess destroys silently: a ``test_dir``
            that resolves to nothing gives an EMPTY ``defined`` set, at which point every citation in
            the tree is dangling and the arm fails loudly. That is the benign direction; the floor
            below exists for it anyway, because the same mistake one level out -- a tree that walks
            but finds no prose -- reports CLEAN.
        history_keepers: whole files whose prose is a dated log. NO DEFAULT.
        history_markers: phrases making a SENTENCE a record rather than a pointer. NO DEFAULT.
        not_citations: tokens shaped like a test name that are not citations. NO DEFAULT.

    Returns:
        A :class:`CitedScan`.

    """
    files = scanned_files(
        root,
        pointer_dirs=pointer_dirs,
        root_configs=root_configs,
        waiver_header=waiver_header,
        waiver_dirs=waiver_dirs,
    )
    defined = defined_test_functions(root, test_dir=test_dir)
    modules = defined_test_modules(root, test_dir=test_dir)
    return CitedScan(
        files_read=len(files),
        functions_defined=len(defined),
        prose_citations=docstring_citation_count(files),
        dangling_paths=dangling_path_citations(root, files=files, history_keepers=history_keepers),
        dangling_functions=dangling_function_citations(
            root,
            files=files,
            history_keepers=history_keepers,
            history_markers=history_markers,
            not_citations=not_citations,
            defined=defined,
            modules=modules,
        ),
    )


def _bind(found: int, *, floor: int, headroom: int, what: str) -> None:
    """Both sides of one floor. The low side alone is half a ratchet -- see :mod:`lab_commons.dev.floors`."""
    floors.assert_floor(found, floor=floor, what=what)
    floors.assert_floor_still_binds(found, floor=floor, headroom=headroom, what=what)


def assert_no_dangling_path_citation(scan: CitedScan, *, floor: int, headroom: int) -> None:
    """THE PATH ARM, with the walk's file floor bound FIRST so an empty walk cannot read as clean.

    Args:
        scan: what :func:`take_scan` returned.
        floor: the consumer's MEASURED scanned-file count, set below the real population. NO
            DEFAULT -- one repo in this family walks 1437 files and another walks 56, and one repo's
            number handed to the other is a floor nothing measured.
        headroom: how far past its floor the population may grow before the floor is re-measured.

    Raises:
        lab_commons.dev.floors.FloorUnmet: the walk read fewer files than the floor.
        lab_commons.dev.floors.SlackFloor: the floor has stopped binding.
        DanglingCitation: at least one cited ``tests/...`` path is not on disk.

    """
    _bind(scan.files_read, floor=floor, headroom=headroom, what='cited-test-path')
    if scan.dangling_paths:
        msg = (
            'prose points at a guard that does not exist:\n  '
            + '\n  '.join(scan.dangling_paths)
            + '\nRepoint it at whatever enforces the rule now, WRITE the guard the prose promises, or '
            'delete the claim with the guard. A name that merely MOVED is a repoint; a claim whose '
            'subject no longer exists is not.'
        )
        raise DanglingCitation(msg)


def assert_no_dangling_function_citation(scan: CitedScan, *, floor: int, headroom: int) -> None:
    """THE NAME ARM -- the commoner form, and the one the path arm's regex is built to leave alone.

    The floor here is over DEFINED TEST FUNCTIONS rather than over scanned files, and the difference
    is the point: this arm resolves against that set, so a ``tests/`` tree that moved would empty it
    while the file walk stayed healthy. The two arms therefore bind two different populations and
    neither floor stands in for the other.

    Args:
        scan: what :func:`take_scan` returned.
        floor: the consumer's MEASURED count of ``def test_*`` under its test tree. NO DEFAULT --
            measured 2026-09-18 this family holds 2346, 177 and 1127 of them in three repos.
        headroom: how far past its floor that population may grow before the floor is re-measured.

    Raises:
        lab_commons.dev.floors.FloorUnmet: fewer test functions were read than the floor.
        lab_commons.dev.floors.SlackFloor: the floor has stopped binding.
        DanglingCitation: at least one cited test name resolves to nothing.

    """
    _bind(scan.functions_defined, floor=floor, headroom=headroom, what='cited-test-name')
    if scan.dangling_functions:
        msg = (
            f'{len(scan.dangling_functions)} citation(s) name a test that does not exist:\n  '
            + '\n  '.join(scan.dangling_functions)
            + '\nA citation resolves by exact name, by module stem, or as a wrapped fragment, so a '
            'token reported here matched none of the three.'
        )
        raise DanglingCitation(msg)


def assert_the_prose_half_is_reached(scan: CitedScan, *, floor: int, headroom: int) -> None:
    """THE SECOND FLOOR: the walk reached the files, and this says it read their DOCSTRINGS.

    A file-count floor of over a thousand cannot notice that every docstring went unread -- the walk
    is intact, the population is intact, and the offender set is empty for the wrong reason. This
    pins the population the docstring half judges, so a reader narrowed back to ``#`` lines leaves the
    arms above green and THIS one red, which is the whole point.

    Args:
        scan: what :func:`take_scan` returned.
        floor: the consumer's MEASURED count of citations sitting on docstring lines. NO DEFAULT.
        headroom: how far it may grow before the floor is re-measured.

    Raises:
        lab_commons.dev.floors.FloorUnmet: the prose reader has narrowed.
        lab_commons.dev.floors.SlackFloor: the floor has stopped binding.

    """
    _bind(scan.prose_citations, floor=floor, headroom=headroom, what='cited-test-prose')


def assert_every_exemption_is_real(root: Path, *, history_keepers: Collection[str]) -> None:
    """A history keeper that is GONE is a waiver nothing uses, and it does not announce itself.

    The other side of the same ratchet the arms above hold: an exemption list is where a file whose
    prose has gone stale can quietly be parked, and a row naming a deleted path covers nothing while
    still reading as a considered decision.

    Args:
        root: the checkout.
        history_keepers: the repo-relative paths the scan skips. NO DEFAULT.

    Raises:
        VacuousExemption: at least one exempt path is not on disk.

    """
    missing = sorted(name for name in history_keepers if not (root / name).exists())
    if missing:
        msg = (
            f'{missing} are exempt from a scan they are no longer part of. An exemption naming a '
            f'deleted file is a silent widening: delete the row in the same edit that deleted the file.'
        )
        raise VacuousExemption(msg)


def assert_the_readers_still_convict(
    plant_root: Path,
    *,
    history_markers: Collection[str],
    not_citations: Collection[str],
) -> None:
    """THE PLANTED CONTROL, in BOTH directions, driving the REAL readers over a REAL tree.

    A detector that never fires reports exactly what a clean tree reports, so every distinction the
    readers exist to draw is planted at once and each offender sits beside an honest neighbour that
    must NOT be named: a dangling path against a resolving one, a dangling name against a wrapped
    fragment of a real one, a citation in a DOCSTRING against the same path in ordinary CODE, and a
    dangling citation in a ROOT CONFIG, which is the file type the originating incident hid in.

    The code-string arm is the one worth keeping: a path in code is DATA, and a fixture naming a file
    that must NOT exist is legitimate. A reader that convicted it would make this guard refuse correct
    tests, which is how a mechanism gets deleted rather than obeyed.

    Args:
        plant_root: an empty directory to plant into -- a consumer's ``tmp_path``. Taken as an
            argument so the control drives the SHIPPED readers rather than a re-implementation, which
            would agree with itself and prove nothing.
        history_markers: the consumer's own record markers, so the exemption arm asserts about the
            set THIS repo declares.
        not_citations: the consumer's own vocabulary set, for the same reason.

    Raises:
        AssertionError: a reader failed to name a planted offender, or named an honest neighbour.

    """
    (plant_root / 'src').mkdir(parents=True)
    (plant_root / 'tests' / 'unit').mkdir(parents=True)
    (plant_root / 'tests' / 'unit' / 'test_real_guard.py').write_text(
        'def test_the_real_guard_is_live():\n    assert True\n', encoding='utf-8'
    )
    (plant_root / 'src' / 'thing.py').write_text(
        '# guarded by tests/unit/test_no_such_guard.py and by tests/unit/test_real_guard.py\n'
        '# pinned by test_no_such_guard_anywhere, and by test_the_real_guard (a wrapped fragment)\n'
        'PATH = "tests/unit/test_also_missing.py"\n',
        encoding='utf-8',
    )
    (plant_root / 'src' / 'documented.py').write_text(
        '"""See tests/unit/test_gone_from_a_docstring.py."""\n', encoding='utf-8'
    )
    (plant_root / 'ruff.toml').write_text('# waived per tests/unit/test_gone_from_the_config.py\n', encoding='utf-8')

    walk = {
        'pointer_dirs': ('src',),
        'root_configs': ('ruff.toml',),
        'waiver_header': 'ratcheted by',
        'waiver_dirs': (),
    }
    scan = take_scan(
        plant_root,
        test_dir='tests',
        history_keepers=(),
        history_markers=history_markers,
        not_citations=not_citations,
        **walk,
    )
    expected_paths = (
        'ruff.toml:1 -> tests/unit/test_gone_from_the_config.py',
        'src/documented.py:1 -> tests/unit/test_gone_from_a_docstring.py',
        'src/thing.py:1 -> tests/unit/test_no_such_guard.py',
    )
    if scan.dangling_paths != expected_paths:
        msg = (
            f'the path reader answered {scan.dangling_paths}. The comment, the DOCSTRING and the ROOT '
            f'CONFIG hits must all three come back -- the config is the form the original incident hid '
            f'in -- while the resolving citation and the path in CODE must not: a path in code is data.'
        )
        raise AssertionError(msg)
    if scan.dangling_functions != ('src/thing.py:1 -> test_no_such_guard_anywhere',):
        msg = (
            f'the name reader answered {scan.dangling_functions}. Only the unresolvable name belongs '
            f'here: a wrapped PREFIX of a real test must resolve, or this guard becomes noise and is '
            f'deleted rather than obeyed.'
        )
        raise AssertionError(msg)
    if scan.prose_citations < 1:
        msg = (
            'the prose counter read no docstring citation, so its floor cannot tell a narrowed reader from a clean tree'
        )
        raise AssertionError(msg)
