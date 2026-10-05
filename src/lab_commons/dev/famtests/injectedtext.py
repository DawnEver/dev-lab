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

__all__ = ['assert_refusals_fit', 'assert_the_budget_still_convicts']


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
