"""The names a repo declares for its branches, in ``[tool.lab_commons.integrator]`` -- names only, never a rule.

A LEAF: the integrator's queue, push admission, the forge tick and the record attacher all read the
same declaration, and none of them may import another just to learn a branch name.
"""

from __future__ import annotations

import dataclasses
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Final

__all__ = ['Policy', 'load_policy']

_TABLE: Final = 'integrator'


@dataclass(frozen=True)
class Policy:
    """What a consumer declares in ``[tool.lab_commons.integrator]``: names only, never a rule."""

    lane_prefixes: tuple[str, ...] = ('feat/', 'fix/')
    integration: str = 'integrate/main'
    main: str = 'main'
    #: The test trees :mod:`lab_commons.dev.mergeaudit` reads when a merge is committed.
    test_roots: tuple[str, ...] = ('tests',)


def load_policy(root: Path) -> Policy:
    """*root*'s ``[tool.lab_commons.integrator]``, defaults for what it omits; an unknown key is refused."""
    manifest = root / 'pyproject.toml'
    if not manifest.is_file():
        return Policy()
    with manifest.open('rb') as handle:
        declared = tomllib.load(handle).get('tool', {}).get('lab_commons', {}).get(_TABLE, {})
    known = {field.name for field in dataclasses.fields(Policy)}
    unknown = sorted(set(declared) - known)
    if unknown:
        msg = f'[tool.lab_commons.{_TABLE}] in {manifest} has unknown key(s) {unknown}; the keys are {sorted(known)}'
        raise ValueError(msg)
    declared = declared | {key: tuple(declared[key]) for key in ('lane_prefixes', 'test_roots') if key in declared}
    return Policy(**declared)
