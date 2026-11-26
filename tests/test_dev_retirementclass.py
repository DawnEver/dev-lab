"""Every retirement is classified; a dropped capability cites the user's ruling (keep-valuable-options)."""

from __future__ import annotations

from dev_lab.dev.retirementclass import CLASSES, refusals


def test_a_classified_registry_is_refused_nothing() -> None:
    rows = {
        'old': ('new', 'D40 2026-11-17: moved', 'renamed'),
        'dead': ('nothing', 'no caller', 'baggage'),
        'gone': ('nothing', 'user ruling 2026-11-06: no rounds', 'capability-dropped'),
    }
    assert refusals(rows) == []


def test_an_unclassified_row_is_refused_by_name_with_its_door() -> None:
    (line,) = refusals({'old': ('new', 'why')})
    assert "'old'" in line
    assert 'capability-dropped' in line


def test_an_unknown_class_is_refused() -> None:
    (line,) = refusals({'old': ('new', 'why', 'moved')})
    assert 'moved' in line
    assert all(cls in line for cls in CLASSES)


def test_a_dropped_capability_without_a_ruling_is_refused() -> None:
    (line,) = refusals({'gone': ('nothing', 'nobody used it', 'capability-dropped')})
    assert 'user ruling' in line


def test_the_same_reason_as_baggage_is_admitted() -> None:
    """Planted control: the ruling check binds only capability-dropped."""
    assert refusals({'gone': ('nothing', 'nobody used it', 'baggage')}) == []
