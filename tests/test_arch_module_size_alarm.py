"""MODULE-SIZE-ALARM, NAMED-SETS-NOT-COUNTS, RATCHET-TWO-SIDES and ESCAPE-HATCH-CEILING in one file.

They are one mechanism here because they are one ratchet. The band says a module past it must be
refactored; the DEBT says which modules were already past it the day the band arrived, BY NAME with
the line count each was measured at; and the two-sidedness is what makes the debt a ratchet rather
than a list: a module that grows past its pinned count reds, and a module that comes back under the
band must be DELETED from the pin or it reds as a waiver nothing uses.

WHY A NAMED SET AND NOT "5 MODULES ARE OVER". An integer cannot say WHICH module moved, so a
refactor that fixed one file while another crossed the band compares equal, and the honest-looking
repair when the digit disagrees is to edit the digit. The names make both halves visible.

THE UNIT IS CODE LINES, AND THAT IS THE REPAIR THIS FILE'S OWN DOCSTRING NAMED AND DID NOT MAKE.
Until 2026-09-19 the band counted RAW lines. A raw band cannot tell a 600-line module from a
400-line one carrying 200 lines of prose, so it measured the wrong thing in BOTH directions at once,
and both directions were live:

* IT TAXED DOCUMENTATION. Four of the six pinned rows were pinned for prose alone, and the
  2026-09-17 re-measurement recorded that in the table itself -- adopting the family's 58-selector
  ruff set required a docstring on every public class, method and ``__init__``, and counted with
  docstrings and comments blanked the four pre-existing rows moved by ONE line in total. That is the
  whole 483-line rise the ceiling had to absorb, for one real line of code.
* IT DEADLOCKED THE PACKAGE AGAINST ITS OWN INVENTORY. ``src/lab_commons/dev/__init__.py`` is a
  DOCUMENT -- 400 raw lines, of which 167 are code -- and
  ``test_arch_the_dev_inventory_lists_every_module`` demands one bullet per public module. It sat at
  exactly the raw band, so EVERY new public module needed a line the band refused, while the ceiling
  below may only go DOWN. Two guards, each right, jointly refusing a module to exist. It was paid
  once by reflowing prose; on the CODE reading that file has 133 lines of room, and the deadlock is
  gone rather than deferred.
* IT WAS ALSO LETTING A REAL OFFENDER THROUGH IN THE OTHER DIRECTION.
  ``src/lab_commons/dev/famtests/depdoor.py`` stood at 411 raw lines -- over the raw band and in no
  pin, a live red nobody had answered. On the code reading it is 209 and genuinely fine.

THE BAND IS RE-CALIBRATED WITH ITS OWN EVIDENCE, because changing the unit invalidates the old
number. MEASURED 2026-09-19 over all 115 tracked source modules, the code-line distribution has a
GAP between 278 (``_doorcensus_rows.py``) and 310 (``_unit_tokens.py``); 300 sits in it. That is a
knee in the data rather than a preference, and it is deliberately NOT placed just above the largest
module landing today -- a band chosen to admit its author's own file is the digit being edited to
meet the table, which is the defect the rest of this file is about. The blanker is
:func:`lab_commons.dev.famtests.density.code_only`, the family's existing prose reader, so there is
no second implementation to keep in step.
"""

from __future__ import annotations

from pathlib import Path

from _arch_corpus import ROOT, SOURCE_FLOOR, assert_floor, parse, rel, source_modules

from lab_commons.dev.famtests.density import code_only

#: This repo's band, in CODE lines. A module past it is refactored, or pinned below with its
#: measurement. See the docstring for why the unit changed and where 300 was measured.
BAND = 300


def code_lines(path: Path) -> int:
    """How many lines of *path* are CODE -- docstrings and comments blanked, blank lines dropped."""
    return len([line for line in code_only(path.read_text(encoding='utf-8')) if line.strip()])


#: The debt, RE-MEASURED 2026-09-19 ON CODE LINES: module -> the code-line count it may not exceed.
#: Each entry is a refactor that has not happened, not a permission.
#:
#: THREE ROWS WHERE THERE WERE SIX, AND NOTHING WAS REFACTORED TO ACHIEVE THAT. The three that left
#: -- `rules.py` (466 raw, 214 code), `units.py` (540 raw, 209 code) and `proc.py` (515 raw, 270
#: code) -- were pinned for PROSE, which is what the old unit could not see and what the old table
#: said about them at the time. They are not waivers being dropped; they were never over THIS band.
#: Two modules the raw reading never convicted -- `em.py` at 259 and `_doorcensus_rows.py` at 278 --
#: are measured here for the first time and are under it, so they take no row either.
#:
#: The two registries stay pinned rather than refactored for the reason the old table already gave:
#: they are DATA, and splitting a registry to fit a line count is the band deforming the code it
#: measures. `resources.py` is the standing one -- it holds the broker, the registry and the record
#: in one file, and splitting it is its own change.
DEBT: dict[str, int] = {
    'src/lab_commons/dev/_rule_rows.py': 422,  # 461 raw; every line it gained was ISC004 parenthesisation
    'src/lab_commons/dev/_unit_tokens.py': 310,  # 408 raw; a token registry, 10 lines over
    'src/lab_commons/resources.py': 741,  # 1547 raw; the broker, the registry and the record in one file
}

#: The ceiling on the escape hatch: total pinned debt in CODE lines. It went UP exactly once, on
#: 2026-09-17, and comes back DOWN here from 3937 to the sum above -- the direction that entry
#: declared was the only one allowed. THE DROP IS A UNIT CHANGE AND NOT A REPAYMENT, and saying so is
#: the difference between a ceiling and a number edited to fit: 2464 of those lines were never code.
#: From here it may only go DOWN.
DEBT_CEILING = 1473


def oversized(paths: tuple[Path, ...], band: int) -> dict[str, int]:
    """``{repo-relative path: code-line count}`` for every module past *band* -- pure over its argument."""
    out: dict[str, int] = {}
    for path in paths:
        lines = code_lines(path)
        if lines > band:
            key = rel(path) if path.is_relative_to(ROOT) else path.name
            out[key] = lines
    return out


def test_the_debt_is_exactly_the_modules_that_are_over_the_band() -> None:
    """BOTH SIDES. A new oversized module reds; a module that came back under the band reds too."""
    paths = source_modules()
    assert_floor(len(paths), SOURCE_FLOOR, 'module size')
    live = oversized(paths, BAND)
    assert set(live) == set(DEBT), (
        f'past the {BAND}-line band and not pinned: {sorted(set(live) - set(DEBT))} -- refactor it, or '
        f'pin it here with its measurement. Pinned but no longer over the band: '
        f'{sorted(set(DEBT) - set(live))} -- delete the entry in the same edit that shrank the module; '
        f'a waiver nothing uses is a hole that reads as a decision.'
    )


def test_no_pinned_module_may_grow() -> None:
    """The ratchet's forward side: a pin is a ceiling on that module, not a licence for it."""
    live = oversized(source_modules(), BAND)
    grew = {name: (live[name], DEBT[name]) for name in DEBT if live[name] > DEBT[name]}
    assert grew == {}, f'pinned modules grew past their measurement (now, pinned): {grew}'


def test_the_total_debt_may_only_shrink() -> None:
    """The ceiling. A refactor that frees budget pays it back here rather than banking it."""
    assert sum(DEBT.values()) <= DEBT_CEILING, (
        f'{sum(DEBT.values())} lines of oversized-module debt, above the {DEBT_CEILING} ceiling. An '
        f'escape hatch needs a ceiling rather than a reason.'
    )


def test_a_planted_oversized_module_is_refused(tmp_path: Path) -> None:
    """THE PLANTED CONTROL, over the REAL scanner, with a file on each side of the band."""
    big = tmp_path / 'big.py'
    big.write_text('x = 1\n' * 12, encoding='utf-8')
    small = tmp_path / 'small.py'
    small.write_text('x = 1\n' * 3, encoding='utf-8')
    live = oversized((big, small), band=10)
    assert live == {'big.py': 12}
    assert parse(small).body, 'the planted files are real modules, not text the guard never parsed'


def test_the_band_measures_code_and_not_prose(tmp_path: Path) -> None:
    """THE CONTROL FOR THE UNIT ITSELF: a module huge in RAW lines and tiny in CODE, and its mirror.

    Without this arm the switch to code lines is asserted only by the docstring above, and a
    ``code_only`` that stopped blanking would restore the raw band SILENTLY -- the exact state the
    dev inventory deadlocked against, arriving back with no red anywhere. BOTH directions are
    planted, because a blanker that returned NOTHING would pass a one-sided version of this.
    """
    prose = tmp_path / 'prose.py'
    prose.write_text('"""\n' + 'a documented module.\n' * 40 + '"""\n' + 'X = 1\n' * 3, encoding='utf-8')
    dense = tmp_path / 'dense.py'
    dense.write_text('X = 1\n' * 40, encoding='utf-8')

    assert len(prose.read_text(encoding='utf-8').splitlines()) > 40, 'the planted prose file must be big RAW'
    assert code_lines(prose) == 3, code_lines(prose)
    assert code_lines(dense) == 40, code_lines(dense)
    assert oversized((prose, dense), band=10) == {'dense.py': 40}, (
        'the band convicted the documented module or acquitted the dense one, so it is still '
        'measuring raw lines -- the reading that taxed four pinned rows for prose and deadlocked '
        'the dev inventory against its own band.'
    )


def test_the_debt_names_only_modules_this_repo_has() -> None:
    """A pin naming a path that is not here would be absent from ``live`` and read as repaid."""
    present = {rel(path) for path in source_modules()}
    missing = sorted(set(DEBT) - present)
    assert missing == [], (
        f'these pins name no module in this tree: {missing}. A pin on a path that does not exist '
        f'never appears in the live oversized set, so the two-sided arm above reads it as a module '
        f'that came back under the band -- a waiver that has quietly stopped being about anything.'
    )
