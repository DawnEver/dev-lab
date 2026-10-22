"""SPLIT-BY-CONCEPT over this tree: no module is its sibling's size overflow, except the one named debt.

PLANTED CONTROLS: ``a.py`` + ``a_b.py`` is a size split and reds; ``a.py`` + ``a_cli.py`` names a concept
and passes; ``_three_d.py`` with no ``_three.py`` sibling is a concept (3D) and passes.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from lab_commons.dev.famtests.sizesplits import SizeSplit, assert_no_new_size_splits, size_splits
from lab_commons.dev.rules import tracked_files

_ROOT = Path(__file__).resolve().parents[1]

#: The size splits that predate the rule, by name -- removing one from the tree must remove it here.
DEBT = frozenset({'src/lab_commons/dev/_rule_rows_b.py'})


def test_the_tree_holds_no_size_split_beyond_its_debt() -> None:
    modules = sorted(path for path in tracked_files(_ROOT) if path.startswith('src/') and path.endswith('.py'))
    assert len(modules) > 100, f'read {len(modules)} modules: an unread tree is not a clean one'
    assert_no_new_size_splits(modules, debt=DEBT)


@pytest.mark.parametrize(
    ('modules', 'found'),
    [
        (('p/a.py', 'p/a_b.py'), {'p/a_b.py'}),
        (('p/a.py', 'p/a_2.py', 'p/a_part3.py'), {'p/a_2.py', 'p/a_part3.py'}),
        (('p/_rows.py', 'p/_rows_more.py'), {'p/_rows_more.py'}),
        (('p/a.py', 'p/a_cli.py'), set()),
        (('p/_three_d.py',), set()),
        (('p/a_b.py', 'q/a.py'), set()),
    ],
)
def test_a_size_split_is_a_sibling_with_an_overflow_suffix(modules: tuple[str, ...], found: set[str]) -> None:
    assert set(size_splits(modules)) == found


def test_the_debt_is_two_sided() -> None:
    with pytest.raises(SizeSplit, match=r'a_b.py'):
        assert_no_new_size_splits(('p/a.py', 'p/a_b.py'), debt=frozenset())
    with pytest.raises(SizeSplit, match='no longer'):
        assert_no_new_size_splits(('p/a.py',), debt=frozenset({'p/a_b.py'}))
