"""INJECTED-TEXT-IS-PROGRESSIVE, as the assertions a consumer runs over the refusals it ships.

The budget is :data:`lab_commons.dev.disclosure.BUDGETS`; this module only applies it. Details:
``docs-src/dev/refusals.md#the-shape-of-a-refusal`` (lab-commons).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from lab_commons.dev import disclosure
from lab_commons.dev.disclosure import InjectedTextOverBudget

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

    from lab_commons.dev.hooks import DenyRule, Remedy
    from lab_commons.dev.rules import Rule

__all__ = [
    'assert_refusals_fit',
    'assert_rows_fit',
    'assert_the_budget_still_convicts',
    'assert_the_row_ceilings_still_convict',
    'row_fields',
]


def assert_refusals_fit(rules: Iterable[DenyRule], remedies: Mapping[str, Remedy]) -> None:
    """Raise unless every rule's rendered refusal fits the ``refusal`` budget.

    *remedies* are the repo's own doors, so a door too long for the budget is caught here too.
    """
    over = {}
    for rule in rules:
        if rule.needs and rule.id not in remedies:
            continue
        found = disclosure.problems(rule.reason(remedies.get(rule.id)), 'refusal')
        if found:
            over[rule.id] = found
    if over:
        lines = '\n  '.join(f'{rule_id}: {"; ".join(found)}' for rule_id, found in sorted(over.items()))
        msg = (
            f'refusals over the budget:\n  {lines}\n'
            f'Move the reasoning into the doc and keep a clause; see {disclosure.REFUSALS_DOC}#the-shape-of-a-refusal.'
        )
        raise InjectedTextOverBudget(msg)


def assert_the_budget_still_convicts() -> None:
    """PLANTED CONTROL: a refusal that breaks every limit must be convicted on every limit."""
    budget = disclosure.BUDGETS['refusal']
    planted = '\n'.join(['x' * (budget.max_line_chars + 1)] * (budget.max_lines + 1))
    found = disclosure.problems(planted, 'refusal')
    kinds = {'lines >', 'chars >', 'no closing'}
    missed = sorted(kind for kind in kinds if not any(kind in problem for problem in found))
    if missed:
        msg = f'the budget no longer convicts a planted refusal on {missed}; it would pass anything.'
        raise InjectedTextOverBudget(msg)
    fitting = f'PLANTED: short\ndo this\n{disclosure.details_for("PLANTED")}'
    if disclosure.problems(fitting, 'refusal'):
        msg = 'the budget convicts a refusal that fits it; it would refuse everything.'
        raise InjectedTextOverBudget(msg)


def row_fields(rules: Iterable[Rule], deny_rules: Iterable[DenyRule]) -> list[tuple[str, str, str]]:
    """Every injected row field as ``(field, id, text)``: rule statements, deny hazards and remedies."""
    out = [('statement', rule.id, rule.statement) for rule in rules]
    for row in deny_rules:
        out += [('hazard', row.id, row.hazard), ('remedy', row.id, row.remedy)]
    return out


def assert_rows_fit(rules: Iterable[Rule], deny_rules: Iterable[DenyRule]) -> None:
    """Raise unless every row field fits its ceiling and is one sentence -- or is named, still over, debt.

    Both sides of the ratchet: a ceiling above the current maximum, a stale exception, or more exceptions
    than :data:`~lab_commons.dev.disclosure.MULTI_SENTENCE_CEILING` all red, so each may only go down.
    """
    fields = row_fields(rules, deny_rules)
    over = [problem for field, row_id, text in fields for problem in disclosure.row_problems(field, row_id, text)]
    for field, ceiling in disclosure.ROW_CEILINGS.items():
        longest = max(len(text) for name, _, text in fields if name == field)
        if longest < ceiling:
            over.append(f'{field} ceiling {ceiling} > the longest row {longest}; lower it')
    multi = {f'{field}:{row_id}' for field, row_id, text in fields if disclosure.sentences(text) > 1}
    over += [f'{key} is named as debt but now fits; drop it' for key in sorted(disclosure.MULTI_SENTENCE_ROWS - multi)]
    if len(disclosure.MULTI_SENTENCE_ROWS) != disclosure.MULTI_SENTENCE_CEILING:
        over.append(
            f'{len(disclosure.MULTI_SENTENCE_ROWS)} multi-sentence rows != ceiling {disclosure.MULTI_SENTENCE_CEILING}'
        )
    if over:
        msg = 'rows over the budget:\n  ' + '\n  '.join(over)
        raise InjectedTextOverBudget(msg)


def assert_the_row_ceilings_still_convict() -> None:
    """PLANTED CONTROL: an over-long, two-sentence row must be convicted on both counts."""
    ceiling = disclosure.ROW_CEILINGS['hazard']
    found = disclosure.row_problems('hazard', 'PLANTED', 'It is planted. X' + 'x' * ceiling)
    if not (any('chars >' in p for p in found) and any('sentences >' in p for p in found)):
        msg = f'the row ceilings no longer convict a planted row: {found}'
        raise InjectedTextOverBudget(msg)
    if disclosure.row_problems('hazard', 'PLANTED', 'it is planted, e.g. here.'):
        msg = 'the row ceilings convict a one-sentence row that fits; they would refuse everything.'
        raise InjectedTextOverBudget(msg)
