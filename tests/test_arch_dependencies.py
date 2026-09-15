"""LATEST-DEPENDENCIES, plus the constraint that is this package's alone: what a consumer INHERITS.

TWO CHECKS, ONE SUBJECT -- the ``[project].dependencies`` list.

A FLOOR IS A STATEMENT AND AN UPPER BOUND IS A CEILING NOBODY RE-ARGUED. ``pint>=0.25.2`` says "this
code needs a fix that landed there". ``pint<0.26`` says "somebody, once, had a bad afternoon", and
it is inherited by every repo that installs this one -- an upper bound here is not a local decision,
it is a resolver constraint imposed on four trees that never agreed to it. So one is allowed and the
other is refused, and the refusal names the remedy: fix the incompatibility, or pin in the consumer
that actually has the problem.

AND THE RUNTIME SET IS PINNED BY NAME, because a dependency added here is installed by every
consumer whether it uses the feature or not. The dev layer is the counter-example that proves the
shape works: ``lab_commons.dev`` drives pytest and ruff, needs no new runtime dependency, and is
gated behind the ``dev`` extra -- `tests/test_dev_gate.py` pins that against a fresh interpreter.
A new name in the list below is a decision, and it must be typed here to be made.
"""

from __future__ import annotations

import re

from _arch_corpus import ROOT

from lab_commons.file_io import read_toml

#: The tier-1 runtime dependencies, BY NAME. Two-sided: an arrival reds, and so does a removal that
#: leaves a dead entry behind. Measured 2026-09-15.
RUNTIME_DEPENDENCIES = frozenset({'structlog', 'platformdirs', 'rtoml', 'pint', 'pydantic', 'numpy'})

#: The name-boundary of a PEP 508 requirement: everything before the first comparator or marker.
_NAME = re.compile(r'^[A-Za-z0-9._-]+')

#: A bound that keeps a consumer OFF a newer release.
_UPPER = re.compile(r'(<=?|==|~=)\s*\d')


def _declared() -> tuple[str, ...]:
    return tuple(read_toml(ROOT / 'pyproject.toml')['project']['dependencies'])


def upper_bounded(requirements: tuple[str, ...]) -> tuple[str, ...]:
    """Every requirement carrying a ceiling -- pure over its argument, so a control can drive it."""
    return tuple(req for req in requirements if _UPPER.search(req.split(';')[0]))


def test_no_runtime_dependency_carries_an_upper_bound() -> None:
    """THE CHECK. A floor is a statement; a ceiling is inherited by every consumer."""
    requirements = _declared()
    assert requirements, 'the dependency list read empty -- an unread pyproject is not a clean one'
    bounded = upper_bounded(requirements)
    assert bounded == (), (
        f'these requirements pin a ceiling every consumer inherits: {list(bounded)}. Fix the '
        f'incompatibility, or pin it in the consumer that has the problem -- not in the package four '
        f'repos install.'
    )


def test_the_runtime_dependency_set_is_the_declared_one() -> None:
    """BOTH SIDES: a new inherited dependency reds, and a dead entry in the pin reds too."""
    live = {m.group(0).lower() for req in _declared() if (m := _NAME.match(req))}
    assert live == RUNTIME_DEPENDENCIES, (
        f'undeclared runtime dependencies: {sorted(live - RUNTIME_DEPENDENCIES)} -- every consumer '
        f'installs these, including the ones that only wanted logging. Declared but gone: '
        f'{sorted(RUNTIME_DEPENDENCIES - live)} -- delete the entry in the same edit.'
    )


def test_a_planted_ceiling_is_refused() -> None:
    """THE PLANTED CONTROL, through the REAL matcher, with the allowed spelling alongside."""
    assert upper_bounded(('pint<0.26',)) == ('pint<0.26',)
    assert upper_bounded(('numpy==2.1.0',)) == ('numpy==2.1.0',)
    assert upper_bounded(('pint>=0.25.2', 'structlog')) == ()
