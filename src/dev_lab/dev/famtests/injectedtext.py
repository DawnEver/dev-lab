"""INJECTED-TEXT-IS-PROGRESSIVE, as the assertions a consumer runs over the refusals it ships.

The budget is :data:`dev_lab.dev.disclosure.BUDGETS`; this module only applies it. Details:
``docs-src/dev/refusals.md#the-shape-of-a-refusal`` (lab-commons).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from dev_lab.dev import disclosure
from dev_lab.dev.disclosure import InjectedTextOverBudget

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

    from dev_lab.dev.hooks import DenyRule, Remedy
    from dev_lab.dev.rules import Rule

__all__ = [
    'assert_refusals_fit',
    'assert_rows_fit',
    'assert_the_budget_still_convicts',
    'assert_the_row_budgets_still_convict',
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
    """Raise unless every row field fits its surface's budget, and no row budget is slack.

    Slack is a budget above the longest row it measures: lowering it is a declaration edit, never a
    rewrite, so freed room is not banked for the next arrival.
    """
    fields = row_fields(rules, deny_rules)
    over = [
        f'{field}:{row_id}: {problem}'
        for field, row_id, text in fields
        for problem in disclosure.problems(text, disclosure.ROW_SURFACES[field])
    ]
    for field, surface in disclosure.ROW_SURFACES.items():
        budget = disclosure.BUDGETS[surface]
        rows = [text.split('\n') for name, _, text in fields if name == field]
        lines = max(len(row) for row in rows)
        width = max(len(line) for row in rows for line in row)
        if lines < budget.max_lines or width < budget.max_line_chars:
            used = f'({lines}, {width})'
            over.append(f'{surface} budget ({budget.max_lines}, {budget.max_line_chars}) > used {used}; lower it')
    if over:
        msg = 'rows over the budget:\n  ' + '\n  '.join(over)
        raise InjectedTextOverBudget(msg)


def assert_the_row_budgets_still_convict() -> None:
    """PLANTED CONTROL: a row over both limits is convicted on both; a fitting multi-sentence row passes."""
    budget = disclosure.BUDGETS['deny-hazard']
    planted = '\n'.join(['x' * (budget.max_line_chars + 1)] * (budget.max_lines + 1))
    found = disclosure.problems(planted, 'deny-hazard')
    if not (any('lines >' in p for p in found) and any('chars >' in p for p in found)):
        msg = f'the row budgets no longer convict a planted row: {found}'
        raise InjectedTextOverBudget(msg)
    if disclosure.problems('It is planted. It fits.', 'deny-hazard'):
        msg = 'the row budgets convict a row that fits; they would refuse everything.'
        raise InjectedTextOverBudget(msg)
