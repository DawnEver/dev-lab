"""Every deny row discloses progressively: what and why, the door, what follows an approval, and a live details anchor.

Details: docs-src/dev/refusals.md#the-shape-of-a-refusal.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from dev_lab.dev import disclosure
from dev_lab.dev.hooks import DENY_RULES

ROOT = Path(__file__).resolve().parents[1]
PAGE = (ROOT / disclosure.REFUSALS_DOC).read_text(encoding='utf-8')
#: A remedy names a runnable door, a placeholder the engine fills with one, or says there is none and why.
_DOOR = re.compile(r'\{python\}|\{remedy\}|<venv python>|python -m |\bgit [a-z]|^No door: ')
_ASKS = re.compile(r'\bask the user\b', re.IGNORECASE)
_AFTER = re.compile(r'\bapprov', re.IGNORECASE)


def _section(rule_id: str) -> str:
    return PAGE.split(f'\n## {rule_id}\n', 1)[1].split('\n## ', 1)[0]


def problems(rule_id: str, hazard: str, remedy: str, section: str | None) -> list[str]:
    """Every way one row breaks the shape; empty when it discloses."""
    found = []
    if not hazard.strip() or '\n' in hazard.strip():
        found.append('(a) the hazard is not one line')
    if not _DOOR.search(remedy):
        found.append('(b) the remedy names no door')
    for where, text in (('remedy', remedy), ('section', section or '')):
        if _ASKS.search(text) and not _AFTER.search(text):
            found.append(f'(c) the {where} says ask the user but not what follows an approval')
    if section is None:
        found.append('(d) no section in the refusals page')
    elif '**The exit' not in section:
        found.append('(d) the section states no exit')
    if rule_id.lower() not in disclosure.anchors(PAGE):
        found.append('(d) the details anchor does not resolve')
    return [f'{rule_id}: {one}' for one in found]


@pytest.mark.parametrize('rule', DENY_RULES, ids=lambda rule: rule.id)
def test_every_deny_row_discloses_its_exit(rule) -> None:
    section = _section(rule.id) if f'\n## {rule.id}\n' in PAGE else None
    assert problems(rule.id, rule.hazard, rule.remedy, section) == []


def test_the_shape_check_still_convicts() -> None:
    """PLANTED CONTROL: a row with no door, an ask without an after, and no section fails every count."""
    found = problems('NO-SUCH-ROW', 'two\nlines', 'Anything else: ask the user.', None)
    assert [one.split(': ', 1)[1][:3] for one in found] == ['(a)', '(b)', '(c)', '(d)', '(d)']
