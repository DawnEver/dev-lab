"""The names a repo declares for its branches, in ``[tool.lab_commons.integrator]`` -- names only, never a rule.

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

from lab_commons.hpc.retired import RETIRED

__all__ = ['Policy', 'load_policy']

_TABLE: Final = 'integrator'


@dataclass(frozen=True)
class Policy:
    """What a consumer declares in ``[tool.lab_commons.integrator]``: names only, never a rule."""

    #: The coordination branch: only the integrator merges into it, and every PR targets it.
    integration: str = 'integrate/main'
    #: The stable branch: moved ONLY by fast-forward to an integration commit whose parts are full PASS.
    trunk: str = 'main'
    #: The test trees :mod:`lab_commons.dev.mergeaudit` reads when a merge is committed.
    test_roots: tuple[str, ...] = ('tests',)
    #: The host that OWNS integration: the serving host (its card name) or forge login whose serve tick derives
    #: the integration queue and raises an ``integration`` alarm when it changes, and prunes merged origin branches
    #: (:mod:`lab_commons.dev.branchprune`); ``''`` is nobody.
    host: str = ''


def load_policy(root: Path) -> Policy:
    """*root*'s ``[tool.lab_commons.integrator]``, defaults for what it omits; an unknown key is refused."""
    manifest = root / 'pyproject.toml'
    if not manifest.is_file():
        return Policy()
    with manifest.open('rb') as handle:
        declared = tomllib.load(handle).get('tool', {}).get('lab_commons', {}).get(_TABLE, {})
    if retired := [f'{key} is retired: {RETIRED[key]}' for key in declared if key in RETIRED]:
        msg = f'[tool.lab_commons.{_TABLE}] in {manifest}: ' + '; '.join(retired)
        raise ValueError(msg)
    known = {field.name for field in dataclasses.fields(Policy)}
    unknown = sorted(set(declared) - known)
    if unknown:
        msg = f'[tool.lab_commons.{_TABLE}] in {manifest} has unknown key(s) {unknown}; the keys are {sorted(known)}'
        raise ValueError(msg)
    declared = declared | {key: tuple(declared[key]) for key in ('test_roots',) if key in declared}
    return Policy(**declared)
