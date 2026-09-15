"""FLOOR-ON-EVERY-SCAN and PLANTED-CONTROL, checked over the guards themselves.

A guard is the one kind of code whose failure mode is SILENCE. If its corpus goes empty -- a rename,
a moved directory, a `tracked_files` call that answered nothing -- it reports exactly what a clean
tree reports, and it keeps reporting it for as long as nobody looks. Two properties close that, and
neither is checkable by reading the guard:

* IT BINDS A FLOOR. Any module that takes a corpus from `_arch_corpus` must hand the count to
  `assert_floor`, so a scan that stopped reaching the tree fails instead of passing.
* IT HAS A PLANTED CONTROL. A scope claim needs a test that PLANTS the thing in the region and calls
  the REAL guard -- not a re-implementation, which would agree with itself. The control is what says
  the guard can still fail; a guard that cannot fail is the defect this whole family cares most
  about.

THE SET OF GUARDS IS DERIVED, NOT LISTED, and that is what makes this two-sided: a new guard is
scanned the moment it imports a corpus, so it cannot arrive without either property, and a guard
that stops scanning drops out of the set instead of leaving a dead entry behind. The floor below is
this guard's own floor -- it scans the scanners, so it needs one too.
"""

from __future__ import annotations

import ast
from pathlib import Path

from _arch_corpus import assert_floor, parse, rel, suite_modules

#: The corpus enumerators. A module calling one of these is scanning the tree and owes both
#: properties; a module that merely imports `ROOT` is reading one file and owes neither.
ENUMERATORS = ('source_modules', 'suite_modules', 'rules_pages')

#: This guard's own floor: the number of scanning guards it must find before an empty problem list
#: means anything. MEASURED 2026-09-15 (6 scanning guards).
GUARD_FLOOR = 5


def _calls(tree: ast.Module) -> set[str]:
    return {node.func.id for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)}


def scanning_guards(paths: tuple[Path, ...]) -> tuple[Path, ...]:
    """Every test module that takes a corpus from `_arch_corpus` -- derived, never listed."""
    return tuple(p for p in paths if _calls(parse(p)) & set(ENUMERATORS))


def unfloored_or_uncontrolled(paths: tuple[Path, ...]) -> tuple[str, ...]:
    """Every scanning guard missing a floor or a planted control -- pure over its argument."""
    out: list[str] = []
    for path in paths:
        tree = parse(path)
        if 'assert_floor' not in _calls(tree):
            out.append(f'{_name(path)} scans a corpus and binds no floor: an unread tree reads as a clean one')
        planted = [
            node.name
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name.startswith('test_') and 'planted' in node.name
        ]
        if not planted:
            out.append(f'{_name(path)} has no planted control, so nothing says its guard can still fail')
    return tuple(out)


def _name(path: Path) -> str:
    try:
        return rel(path)
    except ValueError:
        return path.name


def test_every_scanning_guard_binds_a_floor_and_plants_a_control() -> None:
    """THE CHECK, over the guards this repo actually has."""
    guards = scanning_guards(suite_modules())
    assert_floor(len(guards), GUARD_FLOOR, 'guard')
    problems = unfloored_or_uncontrolled(guards)
    assert problems == (), 'these guards cannot report their own failure:\n  ' + '\n  '.join(problems)


def test_a_planted_floorless_guard_is_refused(tmp_path: Path) -> None:
    """THE PLANTED CONTROL for the meta guard -- one module short of each property, one clean."""
    floorless = tmp_path / 'test_floorless.py'
    floorless.write_text(
        'def test_x():\n    source_modules()\n\n\ndef test_a_planted_thing_is_refused():\n    ...\n',
        encoding='utf-8',
    )
    uncontrolled = tmp_path / 'test_uncontrolled.py'
    uncontrolled.write_text('def test_x():\n    assert_floor(len(source_modules()), 1, "x")\n', encoding='utf-8')
    clean = tmp_path / 'test_clean.py'
    clean.write_text(
        'def test_x():\n    assert_floor(len(rules_pages()), 1, "x")\n\n\n'
        'def test_a_planted_row_is_refused():\n    ...\n',
        encoding='utf-8',
    )
    found = scanning_guards((floorless, uncontrolled, clean))
    assert set(found) == {floorless, uncontrolled, clean}, 'the derivation must find all three'
    problems = unfloored_or_uncontrolled(found)
    assert any('binds no floor' in p for p in problems)
    assert any('no planted control' in p for p in problems)
    assert not any('test_clean' in p for p in problems)
