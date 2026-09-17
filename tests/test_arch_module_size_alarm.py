"""MODULE-SIZE-ALARM, NAMED-SETS-NOT-COUNTS, RATCHET-TWO-SIDES and ESCAPE-HATCH-CEILING in one file.

They are one mechanism here because they are one ratchet. The band says a module past it must be
refactored; the DEBT says which modules were already past it the day the band arrived, BY NAME with
the line count each was measured at; and the two-sidedness is what makes the debt a ratchet rather
than a list: a module that grows past its pinned count reds, and a module that comes back under the
band must be DELETED from the pin or it reds as a waiver nothing uses.

WHY A NAMED SET AND NOT "5 MODULES ARE OVER". An integer cannot say WHICH module moved, so a
refactor that fixed one file while another crossed the band compares equal, and the honest-looking
repair when the digit disagrees is to edit the digit. The names make both halves visible.

THE BAND IS REPO DATA; THAT THERE IS ONE IS NOT. 400 lines is this repo's number, chosen at the knee
of its own distribution -- 17 of 22 modules are under it.
"""

from __future__ import annotations

from pathlib import Path

from _arch_corpus import ROOT, SOURCE_FLOOR, assert_floor, parse, rel, source_modules

#: This repo's band. A module past it is refactored, or pinned below with its measurement.
BAND = 400

#: The debt, MEASURED 2026-09-15, re-measured 2026-09-16 when ``resources.py`` gave up its
#: record-writing half to ``_records.py``, and re-measured 2026-09-17 by R1: module -> the line count
#: it may not exceed. Each entry is a refactor that has not happened, not a permission.
#: ``resources.py`` is the standing one; it holds the broker, the registry and the record in one file
#: and splitting it is its own change.
#:
#: THE 2026-09-17 RE-MEASUREMENT IS THE FIRST TIME THESE PINS WENT UP, AND THE COMMENT PER ROW IS THE
#: EVIDENCE THAT NOTHING WAS ADDED. Adopting the family's 58-selector ruff set required a docstring on
#: every public class, method and ``__init__``, and this band counts RAW lines, so a module can cross
#: it by being DOCUMENTED. Counted with docstrings and comments blanked, the four pre-existing rows
#: moved by ONE line in total -- `proc.py`'s `_KB_LINE_TOKENS`, which replaced a magic `2`.
#:
#: `_rule_rows.py` IS A NEW ROW AND IT IS THE SAME STORY IN THE OTHER DIRECTION: 66 real code lines,
#: every one of them ISC004's mandatory parenthesisation of a prose string that was already there.
#: Not one rule row was added. It is pinned rather than refactored because the file is DATA and
#: splitting a registry to fit a line count would be the band deforming the code it measures.
#:
#: THE UNIT IS THE THING TO FIX NEXT, and it is named here rather than fixed under a lint task: a
#: band over raw lines cannot tell a 600-line module from a 400-line one with 200 lines of prose, and
#: the code-line reading above is what it should have been measuring. Changing it re-calibrates the
#: band, which is its own change with its own evidence.
DEBT: dict[str, int] = {
    'src/lab_commons/dev/_rule_rows.py': 461,  # code 356 -> 422, all of it ISC004 parenthesisation
    'src/lab_commons/dev/_unit_tokens.py': 408,  # unchanged by R1, code 310
    'src/lab_commons/dev/rules.py': 466,  # +4 raw, code 214 UNCHANGED: four __post_init__ docstrings
    'src/lab_commons/dev/units.py': 540,  # +1 raw, code 209 UNCHANGED: one __iter__ docstring
    'src/lab_commons/proc.py': 515,  # +6 raw, code 269 -> 270: the one real line in this whole row set
    'src/lab_commons/resources.py': 1547,  # +11 raw, code 741 UNCHANGED: docstrings only
}

#: The ceiling on the escape hatch: total pinned debt in lines. It went UP exactly once, on
#: 2026-09-17, from 3454 to the sum above, and the per-row comments are what makes that checkable:
#: 22 of the 483 lines are docstrings the adopted lint standard requires, 66 are ISC004 wrapping
#: prose that was already there, and 395 are `_rule_rows.py` arriving in the table rather than
#: growing. From here it may only go DOWN.
DEBT_CEILING = 3937


def oversized(paths: tuple[Path, ...], band: int) -> dict[str, int]:
    """``{repo-relative path: line count}`` for every module past *band* -- pure over its argument."""
    out: dict[str, int] = {}
    for path in paths:
        lines = len(path.read_text(encoding='utf-8').splitlines())
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
