"""The names a repo declares for its branches, in ``[tool.dev_lab.integrator]`` -- names only, never a rule.

EVERY repo declares the table and names its ``integration`` branch there -- the one source of the name
(user ruling 2026-10-29, ONE flow on every forge). An absent manifest, an absent table and a table naming no
branch are each refused by name, never defaulted.

A LEAF: the integrator's queue, push admission, the forge tick and the record attacher all read the
same declaration, and none of them may import another just to learn a branch name. Which origin
branches are CHILDREN is not a name but a rule, and it is the schedule's one rule
(``[tool.lab_commons.schedule] classes_by_ref``, :meth:`lab_commons.compute.model.Schedule.class_of`).
"""

from __future__ import annotations

import dataclasses
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from lab_commons.hpc.declared import pyproject_at
from lab_commons.hpc.retired import RETIRED

from dev_lab.dev.family import declared_table
from dev_lab.dev.familyrepos import manifest_text

__all__ = [
    'FAMILY_INTEGRATION',
    'UNDECLARED_INTEGRATION',
    'Derived',
    'IntegrationNotDeclared',
    'Policy',
    'load_policy',
    'policy_at',
    'policy_from',
]

_TABLE: Final = 'integrator'

#: The family's integration branch name: what a repo declaring no ``integration`` is told to declare, and the one
#: PR base a checkout without the table is still judged against (:mod:`dev_lab.dev.forgemergeready`).
FAMILY_INTEGRATION: Final = 'integrate/main'

#: The note a decision carries when it was judged against :data:`FAMILY_INTEGRATION` for want of a declaration.
UNDECLARED_INTEGRATION: Final = f'no [tool.dev_lab.{_TABLE}]: judged into {FAMILY_INTEGRATION}'


class IntegrationNotDeclared(ValueError):
    """The manifest names no ``integration`` branch; the message names the declaration that is the exit."""


@dataclass(frozen=True)
class Derived:
    """A DERIVED machine branch: its producer regenerates its WHOLE content (decision D23, 2026-11-17).

    Deleting one loses nothing (:func:`dev_lab.dev.deletejudge.judge`). Declared with the producer that regenerates
    it, never inferred from a name: ``derived = [{ branch = "pr/components-bump", producer =
    "dev_lab.dev.componentbump" }]``.
    """

    branch: str
    producer: str


#: The one shape of a ``derived`` row, said in its refusal.
_DERIVED_ROW: Final = '{ branch = "<branch>", producer = "<the module that regenerates its whole content>" }'


@dataclass(frozen=True)
class Policy:
    """What a consumer declares in ``[tool.dev_lab.integrator]``: names only, never a rule."""

    #: The coordination branch: only the integrator merges into it, and every PR targets it.
    integration: str
    #: The stable branch: moved ONLY by fast-forward to an integration commit whose parts are full PASS.
    trunk: str = 'main'
    #: The test trees :mod:`dev_lab.dev.mergeaudit` reads when a merge is committed.
    test_roots: tuple[str, ...] = ('tests',)
    #: INTEGRATION-IS-MERGES-ONLY holds for every first-parent commit of the integration branch after this sha
    #: (:mod:`dev_lab.dev.sessionbranch`); a push that CREATES the branch is refused while it is ``''``.
    merges_only_since: str = ''
    #: How many commits behind ``origin/<integration>`` a branch may sit: ``forge serve`` raises an
    #: ``integration`` alarm for a child branch past it; no local push reads it (:mod:`dev_lab.dev.forgeintegration`).
    behind_max: int = 20
    #: INTEGRATION-TAKES-ONLY-FORGE-MERGES from this sha on: the forge merges a PR into the integration branch
    #: server-side once it is green (:mod:`dev_lab.dev.forgemerge`), and a client push adding any commit to
    #: it is refused (:mod:`dev_lab.dev.sessionbranch`). ``''``: the integrator merges and pushes.
    pr_merges_since: str = ''
    #: The forge checks the merge decision waits on IN PLACE of the statuses a serve host posts (the test parts,
    #: ``tests/security``, the head gates): each a status context that must stand ``success`` at the PR head
    #: (:func:`dev_lab.dev.forgemergewaits.checks_wait`), and required on the integration branch
    #: (:func:`dev_lab.dev.forgeprotect.required_contexts`). For a repo no serve host serves -- a config-only repo
    #: whose Actions workflow is its check (user ruling 2026-11-12). ``()``: the serve-posted statuses gate.
    merge_checks: tuple[str, ...] = ()
    #: A head committed more recently than this duration is not AUTO-SYNCED (:mod:`dev_lab.dev.forgeautosync`,
    #: on wherever ``pr_merges_since`` is declared): a live author is not raced.
    auto_sync_quiet: str = '10 min'
    #: FORGE NOTICES (:mod:`dev_lab.dev.forgenotice`): a notice whose head saw no new push this long after it
    #: opened goes to the integrator.
    notice_escalate: str = '2 h'
    #: A PR head whose parts are still unsettled this long after its commit is a ``stall`` notice.
    notice_stall: str = '6 h'
    #: The DERIVED machine branches (:class:`Derived`): each regenerated whole by its producer, so LOSSLESS-DELETE
    #: deletes it whatever it carries. ``()``: every branch is judged by its content.
    derived: tuple[Derived, ...] = ()


def load_policy(root: Path) -> Policy:
    """*root*'s working-tree ``[tool.dev_lab.integrator]``, a data repo's from its family row; neither is refused."""
    return policy_from(*manifest_text(root))


def policy_at(root: Path, rev: str) -> Policy:
    """The ``[tool.dev_lab.integrator]`` commit or tree *rev* of *root* carries -- never the working tree's."""
    return policy_from(pyproject_at(root, rev), f'{rev}:pyproject.toml')


def policy_from(text: str, origin: str) -> Policy:
    """The policy *text* declares, defaults for what it omits; a retired or unknown key is refused naming *origin*.

    ``integration`` is never defaulted: an absent table, or one naming no branch, is refused naming *origin*.
    """
    declared = declared_table(tomllib.loads(text), _TABLE, {})
    spelled = {key: f'{_TABLE}.{key}' if f'{_TABLE}.{key}' in RETIRED else key for key in declared}
    if retired := [f'{key} is retired: {RETIRED[name]}' for key, name in spelled.items() if name in RETIRED]:
        msg = f'[tool.dev_lab.{_TABLE}] in {origin}: ' + '; '.join(retired)
        raise ValueError(msg)
    known = {field.name for field in dataclasses.fields(Policy)}
    unknown = sorted(set(declared) - known)
    if unknown:
        msg = f'[tool.dev_lab.{_TABLE}] in {origin} has unknown key(s) {unknown}; the keys are {sorted(known)}'
        raise ValueError(msg)
    if not declared.get('integration'):
        # The exit leads: a forge status description is cut at its limit, and the origin path is the longest part.
        msg = (
            f'names no integration branch: declare [tool.dev_lab.{_TABLE}] integration = "{FAMILY_INTEGRATION}" '
            f'in {origin} (docs-src/dev/onboarding.md)'
        )
        raise IntegrationNotDeclared(msg)
    declared = declared | {key: tuple(declared[key]) for key in ('test_roots', 'merge_checks') if key in declared}
    if 'derived' in declared:
        declared = declared | {'derived': _derived(declared['derived'], origin)}
    return Policy(**declared)


def _derived(rows: object, origin: str) -> tuple[Derived, ...]:
    """The declared ``derived`` rows; a row naming no branch or no producer, or any other key, is refused."""
    found: list[Derived] = []
    for row in rows if isinstance(rows, list) else [rows]:
        fields = row if isinstance(row, dict) else {}
        named = [fields.get(key) for key in ('branch', 'producer')]
        if set(fields) != {'branch', 'producer'} or not all(isinstance(one, str) and one.strip() for one in named):
            msg = (
                f'[tool.dev_lab.{_TABLE}] derived in {origin}: {row!r} must name its branch AND the producer that '
                f'regenerates it, each row {_DERIVED_ROW}'
            )
            raise ValueError(msg)
        found.append(Derived(fields['branch'].strip(), fields['producer'].strip()))
    return tuple(found)
