"""INJECTED-TEXT-IS-PROGRESSIVE: every refusal the family ships fits its budget and points at its history.

Details: docs-src/dev/refusals.md#the-shape-of-a-refusal.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from lab_commons.dev import agenthooks, disclosure
from lab_commons.dev.famtests import injectedtext
from lab_commons.dev.hook_adoption import HookAdoption, render
from lab_commons.dev.hooks import DENY_RULES, DenyRule, Remedy

ROOT = Path(__file__).resolve().parents[1]
DOOR = '.venv/Scripts/python.exe -m lab_commons.dev.verify'
REMEDIES = {rule.id: Remedy(rule.needs, DOOR) for rule in DENY_RULES if rule.needs}


def _reasons() -> dict[str, str]:
    return {rule.id: rule.reason(REMEDIES.get(rule.id)) for rule in DENY_RULES}


def test_every_universal_refusal_fits_the_refusal_budget() -> None:
    """Three lines, each under the line budget, the last one a details pointer."""
    injectedtext.assert_refusals_fit(DENY_RULES, REMEDIES)


def test_every_details_pointer_resolves_to_a_doc_anchor() -> None:
    """A pointer to a missing page or heading is a dead hop; the history would be unreachable."""
    assert disclosure.unresolved_pointers(_reasons(), ROOT) == []


def test_every_row_points_at_its_own_section() -> None:
    """One section per row, keyed by the row's own ID, so the pointer is derived rather than typed."""
    for rule_id, text in _reasons().items():
        assert disclosure.pointer(text) == (disclosure.REFUSALS_DOC, rule_id.lower()), rule_id


def test_the_doc_keeps_the_text_the_refusal_used_to_carry() -> None:
    """Nothing lost: every row's section holds a fuller statement than the clause the agent now reads."""
    page = (ROOT / disclosure.REFUSALS_DOC).read_text(encoding='utf-8')
    for rule in DENY_RULES:
        section = page.split(f'\n## {rule.id}\n', 1)[1].split('\n## ', 1)[0]
        assert len(section) > len(rule.hazard) + len(rule.remedy), f'{rule.id}: its section is thinner than the refusal'


def test_the_budget_still_convicts() -> None:
    """PLANTED CONTROL: an over-long, over-tall, pointer-less refusal is refused on every count."""
    injectedtext.assert_the_budget_still_convicts()


def test_a_pointer_to_a_missing_anchor_is_unresolved(tmp_path: Path) -> None:
    """PLANTED CONTROL for the resolver: a real page with the wrong heading is a dead hop."""
    (tmp_path / 'docs-src' / 'dev').mkdir(parents=True)
    (tmp_path / disclosure.REFUSALS_DOC).write_text('# Refusals\n\n## GIT-STASH\n', encoding='utf-8')
    texts = {'ok': 'X: y\nz\n' + disclosure.details_for('GIT-STASH'), 'bad': 'X: y\nz\n' + disclosure.details_for('NOPE')}
    assert disclosure.unresolved_pointers(texts, tmp_path) == ['bad']


def test_a_repo_row_without_details_renders_two_lines() -> None:
    """A consumer's own row with no pointer still renders the short shape: the clause, then the exit."""
    rule = DenyRule(id='PLANTED', pattern='x', hazard='it is planted', remedy='do this')
    assert rule.reason() == 'PLANTED: it is planted\ndo this'


def test_the_cross_repo_refusal_fits_its_budget(tmp_path: Path) -> None:
    """The engine's header line for another repo keeps the refusal inside the cross-repo budget."""
    session, bare = tmp_path / 'session', tmp_path / 'bare'
    for repo in (session, bare):
        (repo / '.git').mkdir(parents=True)
    hooks = session / '.claude' / 'hooks'
    hooks.mkdir(parents=True)
    rules = hooks / 'deny-rules.json'
    rules.write_text(render(HookAdoption(app_name='session', remedies=REMEDIES)), encoding='utf-8')
    reason = agenthooks.decide('git stash', rules, cwd=bare)
    assert reason is not None
    assert disclosure.problems(reason, 'cross-repo-refusal') == [], reason


@pytest.mark.parametrize('surface', sorted(disclosure.BUDGETS))
def test_every_budget_is_positive(surface: str) -> None:
    """A zero budget refuses everything and a negative one is a typo; neither is a declaration."""
    budget = disclosure.BUDGETS[surface]
    assert budget.max_lines > 0
    assert budget.max_line_chars > 0
