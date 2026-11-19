"""INJECTED-TEXT-IS-PROGRESSIVE: every refusal the family ships fits its budget and points at its history.

Details: docs-src/dev/refusals.md#the-shape-of-a-refusal.
"""

from __future__ import annotations

import importlib
import re
from pathlib import Path

import pytest

from dev_lab.dev import agenthooks, disclosure, rules
from dev_lab.dev.famtests import injectedtext
from dev_lab.dev.hook_adoption import HookAdoption, render
from dev_lab.dev.hooks import DENY_RULES, DenyRule, Remedy

ROOT = Path(__file__).resolve().parents[1]
DOOR = '.venv/Scripts/python.exe -m dev_lab.dev.verify'
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
    texts = {
        'ok': 'X: y\nz\n' + disclosure.details_for('GIT-STASH'),
        'bad': 'X: y\nz\n' + disclosure.details_for('NOPE'),
    }
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


def test_every_rule_row_and_deny_row_fits_its_surface_budget() -> None:
    """Rows are injected text: each fits its surface's (lines, chars per line), and no budget is slack."""
    injectedtext.assert_rows_fit(rules.RULES, DENY_RULES)


def test_the_row_budgets_still_convict() -> None:
    """PLANTED CONTROL: a row over both limits reds on both; a fitting multi-sentence row passes."""
    injectedtext.assert_the_row_budgets_still_convict()


def test_a_row_may_hold_several_sentences() -> None:
    """The budget is lines and width; a sentence count was a proxy that shrank nothing, so it is gone."""
    assert disclosure.problems('One. Two. Three.', 'deny-hazard') == []


@pytest.mark.parametrize('surface', sorted(disclosure.BUDGETS))
def test_a_budget_above_the_default_names_its_reason(surface: str) -> None:
    """A relaxation is allowed only WITH A REASON visible in the declaration; no silent waiver."""
    assert disclosure.unreasoned_relaxations({surface: disclosure.BUDGETS[surface]}) == []


def test_an_unreasoned_relaxation_is_refused() -> None:
    """PLANTED CONTROL: a budget wider than the default with an empty reason is named; with one it passes."""
    wide = disclosure.DEFAULT_BUDGET.max_line_chars + 1
    bare = disclosure.Budget(max_lines=1, max_line_chars=wide)
    assert disclosure.unreasoned_relaxations({'planted': bare}) == ['planted']
    reasoned = disclosure.Budget(max_lines=1, max_line_chars=wide, reason='planted')
    assert disclosure.unreasoned_relaxations({'planted': reasoned}) == []


def test_every_pointer_names_dev_lab_whose_page_holds_it() -> None:
    """MEASURED 2026-11-16: every refusal said `(lab-commons)`, a repo that deleted the page on 2026-10-23.

    The page lives in dev-lab, this repo, so the pointer names it and the resolver runs against this checkout.
    """
    assert disclosure.details_for('GIT-STASH').endswith(f'#git-stash ({disclosure.REFUSALS_REPO})')
    assert disclosure.REFUSALS_REPO == 'dev-lab'
    assert (ROOT / disclosure.REFUSALS_DOC).is_file()
    assert disclosure.pointer('X: y\nz\ndetails: docs-src/dev/refusals.md#a (lab-commons)') is None


def _details_callers() -> dict[str, str]:
    """Every rule ID a module passes to ``details_for``, a literal or one of its own constants, by module."""
    found = {}
    for path in sorted((ROOT / 'src' / 'dev_lab' / 'dev').rglob('*.py')):
        text = path.read_text(encoding='utf-8')
        if path.name == 'disclosure.py' or 'details_for(' not in text:
            continue
        name = '.'.join(path.relative_to(ROOT / 'src').with_suffix('').parts)
        module = importlib.import_module(name)
        for argument in re.findall(r'details_for\(([^()]+)\)', text):
            literal = re.fullmatch(r"""['"]([A-Z0-9-]+)['"]""", argument.strip())
            value = literal[1] if literal else getattr(module, argument.strip(), None)
            if isinstance(value, str):
                found[f'{name}:{value}'] = 'X: y\nz\n' + disclosure.details_for(value)
    return found


def test_every_refusal_outside_the_registry_points_at_a_section_that_exists() -> None:
    """The Edit/Write, Stop and lifetime guards cite their rule too; each anchor resolves on the page.

    PLANTED CONTROL: famtests' own budget control cites ``PLANTED``, which has no section, and is the one dead hop.
    """
    callers = _details_callers()
    assert len(callers) >= 7, sorted(callers)
    assert disclosure.unresolved_pointers(callers, ROOT) == ['dev_lab.dev.famtests.injectedtext:PLANTED']
