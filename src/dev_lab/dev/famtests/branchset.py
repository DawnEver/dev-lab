"""ONE-BRANCH-PER-SESSION, as the pure check of a repo's DECLARATION.

The live branch set -- what origin carries -- is judged in ONE place: the forge's ``branchset`` status on
every open PR head (:mod:`dev_lab.dev.forgeheadgate`), plus the serve tick's pruner
(:mod:`dev_lab.dev.branchprune`). No test reads origin's refs or this box's branches: such a test judges the
environment, not the code under test, and reds every unrelated PR (ruling 2026-10-24). A consumer calls::

    from dev_lab.dev.famtests import branchset

    def test_the_pr_flow_is_declared() -> None:
        branchset.assert_the_pr_flow_is_declared(root=ROOT)

Every refusal is a ``raise``, never an ``assert``, so ``python -O`` cannot switch the guard off.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from dev_lab.dev.branchset import EPHEMERAL_OFF, BranchSetNotDeclared, declared_branchset
from dev_lab.dev.lanepolicy import load_policy

if TYPE_CHECKING:
    from pathlib import Path

__all__ = ['BranchSetViolation', 'assert_the_pr_flow_is_declared']


class BranchSetViolation(AssertionError):
    """A repo's declared branch set does not declare the one PR flow."""


#: The declarations that ARE the flow, on the lines a repo adds to adopt it (``ephemeral`` is the family default).
_PR_FLOW: Final = (
    "[tool.dev_lab.branchset]  trunk = 'main'  sessions = ['integrate/main']\n"
    '[tool.dev_lab.integrator] pr_merges_since = "<the integrate/main sha the flow starts after>"'
)


def assert_the_pr_flow_is_declared(*, root: Path) -> str:
    """A repo declares the one flow: a ``pr/*`` head is pushable with no row, and integration moves by forge merges.

    ``integrate/main`` moving ONCE BY FORGE MERGES is INTEGRATION-TAKES-ONLY-FORGE-MERGES, enforced from
    ``pr_merges_since`` forward (:mod:`dev_lab.dev.sessionbranch`); ``ephemeral = ['pr/*']`` is what lets an
    author push a PR head with no declared session row (:mod:`dev_lab.dev.branchset`). A repo declaring
    neither admits a hand merge, so the declarations ARE the flow and not a convention beside it. A repo
    declaring no ``[tool.dev_lab.integrator]`` has no integration branch: only its ``pr/*`` namespace is asked.

    Returns:
        The declared sha the rule starts after, so a case can print it.

    Raises:
        BranchSetViolation: a declaration is missing, naming the line to add.

    """
    policy = load_policy(root)
    try:
        declared = declared_branchset(root)
    except BranchSetNotDeclared as undeclared:
        msg = f'{root} declares no branch set ({undeclared}); add:\n{_PR_FLOW}'
        raise BranchSetViolation(msg) from undeclared
    missing = [
        *(
            ['[tool.dev_lab.integrator] pr_merges_since = "<sha>"']
            if policy.declared and not policy.pr_merges_since
            else []
        ),
        *([EPHEMERAL_OFF] if not declared.is_ephemeral('pr/x') else []),
        *(
            [f'[tool.dev_lab.branchset] sessions names {policy.integration!r}']
            if policy.declared and policy.integration not in declared.sessions
            else []
        ),
    ]
    if missing:
        msg = f'{root} does not declare the one PR flow; missing: {"; ".join(missing)}'
        raise BranchSetViolation(msg)
    return policy.pr_merges_since
