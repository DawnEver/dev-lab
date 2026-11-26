"""Every rule's test mechanism COLLECTS and RUNS a verdict (dev-lab#599, the zero-collection control).

The readings are :mod:`dev_lab.dev.guardcollection`; this is the body a repo runs over its own mechanisms (the
registry's for dev-lab, an :class:`~dev_lab.dev.rules.Adoption`'s for a consumer), and its planted control.
"""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

from dev_lab.dev import guardcollection
from dev_lab.dev.rules import LintRule, Rule, tracked_files

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping
    from pathlib import Path

__all__ = ['assert_every_guard_collects', 'assert_the_collection_control_still_convicts', 'mechanism_paths']

#: The remedy every refusal prints.
REMEDY = 'restore the guard so it collects and runs, or repoint the row at the test that refuses the rule now'


def mechanism_paths(rules: Iterable[Rule]) -> dict[str, tuple[str, ...]]:
    """``rule id -> its test-file mechanisms``; a lint mechanism is the selection check's, not this one's."""
    return {rule.id: tuple(m.path for m in rule.mechanisms if not isinstance(m, LintRule)) for rule in rules}


def assert_every_guard_collects(
    *, root: Path, mechanisms: Mapping[str, Iterable[str]], floor: int, python: str = sys.executable
) -> None:
    """Every tracked mechanism file of *root* collects at least one test and is not skipped or xfailed whole.

    *floor* is the measured number of distinct mechanism files judged: a selection that reads fewer judged less.

    Raises:
        AssertionError: fewer files than *floor*, or a mechanism that collects nothing or runs no verdict.

    """
    tracked = tracked_files(root)
    paths = sorted(
        {
            path
            for group in mechanisms.values()
            for path in group
            if path in tracked and guardcollection.is_test_file(path)
        }
    )
    if len(paths) < floor:
        msg = f'{len(paths)} mechanism file(s) judged, under the floor of {floor}: the selection lost guards'
        raise AssertionError(msg)
    texts = {path: (root / path).read_text(encoding='utf-8') for path in paths}
    counts = guardcollection.collected(root, paths, python=python)
    problems = guardcollection.zero_collection(mechanisms, counts=counts, texts=texts)
    if problems:
        raise AssertionError('\n  '.join((f'{len(problems)} guard(s) judge nothing; {REMEDY}:', *problems)))


#: The planted tree: one live guard, and one of each way a tracked guard judges nothing.
_PLANTED = {
    'tests/test_live.py': 'def test_live():\n    assert True\n',
    'tests/test_empty.py': 'X = 1\n',
    'tests/test_broken.py': 'import no_such_module_anywhere\n\ndef test_x():\n    assert True\n',
    'tests/test_module_skip.py': 'import pytest\n\npytestmark = pytest.mark.skip\n\ndef test_x():\n    assert True\n',
    'tests/test_all_xfail.py': (
        'import pytest\n\n@pytest.mark.xfail(reason="r")\ndef test_x():\n    assert True\n\n'
        '@pytest.mark.skip\ndef test_y():\n    assert True\n'
    ),
}
_CONVICT = (
    (
        'LAUNDERED-RULE: tests/test_all_xfail.py collects but runs no verdict: every one of its 2 test(s) is marked '
        'skip or xfail'
    ),
    'LAUNDERED-RULE: tests/test_module_skip.py collects but runs no verdict: its module-level pytestmark is skip',
    'ZERO-RULE: tests/test_broken.py collects no test (empty, or pytest cannot import it)',
    'ZERO-RULE: tests/test_empty.py collects no test (empty, or pytest cannot import it)',
)


def assert_the_collection_control_still_convicts(plant_root: Path, *, python: str = sys.executable) -> None:
    """THE PLANTED CONTROL through actual collection: the live guard passes, each dead one is named.

    Raises:
        AssertionError: the control named anything other than exactly the four dead guards.

    """
    for rel, text in _PLANTED.items():
        (plant_root / rel).parent.mkdir(parents=True, exist_ok=True)
        (plant_root / rel).write_text(text, encoding='utf-8')
    mechanisms = {
        'LIVE-RULE': ('tests/test_live.py',),
        'ZERO-RULE': ('tests/test_empty.py', 'tests/test_broken.py'),
        'LAUNDERED-RULE': ('tests/test_module_skip.py', 'tests/test_all_xfail.py'),
    }
    counts = guardcollection.collected(plant_root, _PLANTED, python=python)
    problems = guardcollection.zero_collection(mechanisms, counts=counts, texts=_PLANTED)
    if tuple(sorted(problems)) != _CONVICT:
        msg = f'the collection control named {sorted(problems)}; it must name exactly {list(_CONVICT)}'
        raise AssertionError(msg)
