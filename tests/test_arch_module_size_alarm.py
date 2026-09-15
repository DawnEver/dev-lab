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

#: The debt, MEASURED 2026-09-15: module -> the line count it may not exceed. Each entry is a
#: refactor that has not happened, not a permission. ``resources.py`` is the standing one; it holds
#: the broker, the registry and the record in one file and splitting it is its own change.
DEBT: dict[str, int] = {
    'src/lab_commons/dev/_unit_tokens.py': 408,
    'src/lab_commons/dev/rules.py': 462,
    'src/lab_commons/dev/units.py': 539,
    'src/lab_commons/proc.py': 509,
    'src/lab_commons/resources.py': 1564,
}

#: The ceiling on the escape hatch: total pinned debt in lines. It may only go DOWN.
DEBT_CEILING = 3482


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
