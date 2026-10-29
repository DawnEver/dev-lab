"""The names a repo declares for its branches, in ``[tool.dev_lab.integrator]`` -- names only, never a rule.

The integration flow is OPT-IN. A repo that declares no ``[tool.dev_lab.integrator]`` table has NO integration
branch (``integration == ''``): its trunk is ``main``, its pull requests target the trunk, and every
integration rule is absent for it. A repo that declares the table names its integration branch there -- the
one source of the name, never a default.

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

__all__ = ['Policy', 'load_policy', 'policy_at', 'policy_from']

_TABLE: Final = 'integrator'


@dataclass(frozen=True)
class Policy:
    """What a consumer declares in ``[tool.dev_lab.integrator]``: names only, never a rule."""

    #: The coordination branch: only the integrator merges into it, and every PR targets it. ``''`` (no
    #: ``[tool.dev_lab.integrator]`` table): the repo has none, and every integration rule is absent.
    integration: str = ''
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
    #: A head committed more recently than this duration is not AUTO-SYNCED (:mod:`dev_lab.dev.forgeautosync`,
    #: on wherever ``pr_merges_since`` is declared): a live author is not raced.
    auto_sync_quiet: str = '10 min'
    #: FORGE NOTICES (:mod:`dev_lab.dev.forgenotice`): a notice whose head saw no new push this long after it
    #: opened goes to the integrator.
    notice_escalate: str = '2 h'
    #: A PR head whose parts are still unsettled this long after its commit is a ``stall`` notice.
    notice_stall: str = '6 h'

    @property
    def declared(self) -> bool:
        """Whether the repo declares an integration branch, so the integration rules apply to it."""
        return bool(self.integration)

    @property
    def pr_base(self) -> str:
        """The branch every pull request targets and a child syncs from: integration when declared, else trunk."""
        return self.integration or self.trunk


def load_policy(root: Path) -> Policy:
    """*root*'s working-tree ``[tool.dev_lab.integrator]``; defaults when it has no manifest."""
    manifest = root / 'pyproject.toml'
    return policy_from(manifest.read_text(encoding='utf-8'), str(manifest)) if manifest.is_file() else Policy()


def policy_at(root: Path, rev: str) -> Policy:
    """The ``[tool.dev_lab.integrator]`` commit or tree *rev* of *root* carries -- never the working tree's."""
    return policy_from(pyproject_at(root, rev), f'{rev}:pyproject.toml')


def policy_from(text: str, origin: str) -> Policy:
    """The policy *text* declares, defaults for what it omits; a retired or unknown key is refused naming *origin*.

    No table is no integration branch (:class:`Policy` defaults); a table that omits ``integration`` is refused,
    so the branch name has one source.
    """
    declared = declared_table(tomllib.loads(text), _TABLE)
    if declared is None:
        return Policy()
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
        msg = f'[tool.dev_lab.{_TABLE}] in {origin} names no integration branch; declare integration = "<branch>"'
        raise ValueError(msg)
    declared = declared | {key: tuple(declared[key]) for key in ('test_roots',) if key in declared}
    return Policy(**declared)
