"""The restated-rules body over planted pages: a page that copies a registry statement reds, one citing its ID does not.

The consumer-side control for :mod:`dev_lab.dev.famtests.restatedrules`. PLANTED CONTROL: the same
page, with the copied sentence replaced by the rule's ID, passes -- so the red is the restatement and not
the page.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from dev_lab.dev.famtests.restatedrules import (
    RestatedRule,
    VacuousRestatementScan,
    assert_no_restated_rules,
    restated,
)
from dev_lab.dev.rules import RULES, rules_by_id

_RULE = rules_by_id(RULES)['MERGE-OR-DELETE']


def _page(root: Path, name: str, text: str) -> Path:
    path = root / '.claude' / 'rules' / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding='utf-8')
    return path


def test_a_page_restating_a_registry_statement_reds_naming_the_rule(tmp_path: Path) -> None:
    copied = _page(tmp_path, 'workflow.md', f'# Workflow\n\n- {_RULE.statement}\n')
    with pytest.raises(RestatedRule, match=r'workflow\.md.*MERGE-OR-DELETE'):
        assert_no_restated_rules(pages=(copied,), n=6, max_shared=2, floor=1)


def test_the_same_page_citing_the_id_passes(tmp_path: Path) -> None:
    """PLANTED CONTROL: the ID plus the local incident is the shape the registry asks for."""
    cited = _page(tmp_path, 'workflow.md', '# Workflow\n\n- `MERGE-OR-DELETE`: earned here when five lanes idled.\n')
    assert_no_restated_rules(pages=(cited,), n=6, max_shared=2, floor=1)
    assert restated(cited.read_text(encoding='utf-8'), n=6, max_shared=2) == {}


def test_formatting_does_not_hide_a_restatement() -> None:
    """Backticks, case and line breaks are not words: the copy is found through them."""
    wrapped = _RULE.statement.upper().replace(' ', '\n  ', 3).replace('a ', '`a` ')
    assert _RULE.id in restated(wrapped, n=6, max_shared=2)


def test_a_scan_below_its_floor_is_vacuous_not_clean() -> None:
    with pytest.raises(VacuousRestatementScan, match='floor'):
        assert_no_restated_rules(pages=(), n=6, max_shared=2, floor=1)
