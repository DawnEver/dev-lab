"""A REQUIREMENT MAY CARRY NO UPPER BOUND NOBODY WROTE DOWN -- across two ecosystems and two policies.

WHAT THE CONSUMER'S FILE ASSERTS. A floor is a statement about what the code NEEDS and it ages in the
safe direction. A ceiling is a statement about what the code CANNOT TAKE, it ages in the unsafe one,
and nothing ever re-argues it. The cost is on record in this family twice, in two languages:

* ``bokeh~=3.8.0`` carried the comment "keep in lockstep with frontend @bokeh/bokehjs" -- and no
  ``package.json`` in that repository declares bokehjs. The pin guarded a coupling that did not
  exist. ``cadquery-ocp==7.9.*`` stated no reason at all, on a distribution that is not the one
  installed there and that is imported lazily, so it constrained a resolution nobody performs. Both
  read as caution and neither was.
* ``pyo3 = "0.29"`` in a Cargo manifest IS an upper bound and announces nothing. Measured 2026-08-19,
  ``0.29.2`` was the latest published, so the ceiling was invisible -- and on the day ``0.30`` ships,
  a fresh clone re-resolves, still takes ``0.29``, and no gate reds.

**THE SAME SPELLING MEANS TWO DIFFERENT THINGS, AND THAT IS THE READING THIS MODULE EXISTS FOR.**
Cargo's default caret treats the leftmost NON-ZERO component as the breaking slot::

    robust = "1.1"   -> ^1.1  -> >=1.1.0, <2.0.0    a minor bump is ALLOWED
    pyo3   = "0.29"  -> ^0.29 -> >=0.29.0, <0.30.0  a minor bump is REFUSED

So a bound is not "an upper limit exists" -- under a caret one always does. A BOUND IS WHATEVER
REFUSES THE ECOSYSTEM'S NEXT NON-BREAKING RELEASE, and on a ``0.x`` crate a bare version string is
exactly that while on a ``1.x`` crate the identical spelling is not. A reader that knows only PEP 508
operators is blind to the whole class, which is the invisible half rather than the loud one.

**TWO CONSUMERS, TWO POLICIES, AND NEITHER IS THE OTHER'S DEFAULT.** Verified 2026-09-18 at each
repo's own tree before this module was written:

* ``wdg-lab/tests/architecture/test_dependencies_take_the_latest.py`` BANS the bound outright and
  carries an exemption set it asserts is EMPTY -- a waiver nothing uses being as wrong as a bound
  nothing refuses.
* ``motronics-studio/tests/architecture/repo/test_no_rust_dependency_carries_an_undeclared_upper_bound.py``
  does NOT ban it, on a measured reason: two of its crates are ABI-coupled, so unbounding either
  alone lets a resolution pair versions that do not compile. It requires the bound to be DECLARED
  with its reason and its partner, so the pair moves together.

Both are right for their repo, and an upper bound is a decision under one and a defect under the
other. So :data:`POLICIES` is a published named set and ``policy`` has NO DEFAULT. The second repo's
rule is the sharper one to have written down: **an upper bound that is written down is a decision;
one that falls out of caret semantics is an accident, and only the second is what the rule forbids.**

THE READINGS LIVE IN :mod:`lab_commons.dev.famtests._upperbounds_readings` and are re-exported here,
so a consumer has ONE import surface while the split stays real: everything there answers about TEXT
and everything here adds a floor, a policy and a remedy. The seam is the one this module's own second
paragraph names -- how a dialect SPELLS a ceiling is a fact about the dialect, not about a repo --
and it is the same reading/verdict split ``datedmemory`` and ``citedtests`` already run on. It was
also forced arithmetically, which is recorded rather than dressed up: written whole, this module
measured 431 lines against a 400-line band, and pinning that is not the fix.

WHERE THIS IS NOT. :mod:`lab_commons.dev.installdoor` reads ``optional-dependencies`` from the same
file and its subject is a FLOATING requirement reaching an install -- whether the door delivers the
kit. This module never installs anything, reaches no network and asks only whether a ceiling was
chosen. Adjacent, and the two share no name: the distinction ``_datedmemory_readings`` drew against
``datedlog``, arriving at the same file from the other end.

WHAT THIS DOES NOT PROVE. It does not ask whether a newer version EXISTS -- a network call inside a
blocking verdict makes every gate depend on somebody else's uptime, which is the opposite of what a
gate is for. It answers the offline half: is every bound one somebody CHOSE. Nor does it read a
lockfile, which is a resolution rather than a declaration.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from lab_commons.dev import floors
from lab_commons.dev.famtests._upperbounds_readings import (
    ECOSYSTEMS,
    Bound,
    requirements,
    upper_bounds,
)

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping
    from pathlib import Path

__all__ = [
    'ECOSYSTEMS',
    'POLICIES',
    'Bound',
    'BoundScan',
    'UndeclaredUpperBound',
    'UnreasonedWaiver',
    'assert_no_undeclared_upper_bound',
    'assert_the_reader_still_convicts',
    'requirements',
    'take_scan',
    'upper_bounds',
]

#: The two answers this family's repos give, neither of them the other's default.
#:
#: * ``'ban'`` -- no requirement may carry an upper bound, and the declaration must be EMPTY.
#: * ``'declare'`` -- a bound is allowed when it is NAMED with a reason, so the set of bounds equals
#:   the set declared and every reason is non-empty. A bound is then a decision on record.
POLICIES: Final[frozenset[str]] = frozenset({'ban', 'declare'})


class UndeclaredUpperBound(AssertionError):
    """A requirement carries a ceiling nobody wrote down, or a declared ceiling has gone."""


class UnreasonedWaiver(AssertionError):
    """A declared bound carries no reason, so the declaration records that it exists and nothing else."""


@dataclass(frozen=True)
class BoundScan:
    """One walk: the bounds, and BOTH populations a floor judges.

    ``requirements_seen`` is carried beside ``files_read`` because they refuse different silences. A
    manifest that was read and whose dependency table was renamed reports zero requirements and zero
    bounds, which is indistinguishable from a manifest that declares only floors.
    """

    files_read: int
    requirements_seen: int
    bounds: tuple[Bound, ...]


def take_scan(paths: Iterable[Path], *, root: Path, ecosystem: str) -> BoundScan:
    """Read *paths* once under *ecosystem*. One walk, under the name the arms use.

    Args:
        paths: the consumer's OWN manifests. NO DEFAULT and no walk here: one repo has a single
            ``pyproject.toml`` and another has a Cargo workspace whose members each declare their
            own, and a guessed glob that matches nothing reports clean.
        root: what a manifest is named relative to, so a refusal is checkable on another box.
        ecosystem: a member of :data:`ECOSYSTEMS`.

    Returns:
        A :class:`BoundScan`. An unreadable or unparseable manifest is SKIPPED and does not count
        toward ``files_read``, because "could not be parsed" is not evidence of "declares no ceiling".

    """
    bounds: list[Bound] = []
    files = 0
    seen = 0
    for path in sorted(paths):
        try:
            text = path.read_text(encoding='utf-8')
            named = path.relative_to(root).as_posix() if path.is_relative_to(root) else path.as_posix()
            found = requirements(text, ecosystem=ecosystem)
        except (OSError, tomllib.TOMLDecodeError):
            continue
        files += 1
        seen += len(found)
        bounds.extend(upper_bounds(text, ecosystem=ecosystem, manifest=named))
    return BoundScan(files_read=files, requirements_seen=seen, bounds=tuple(sorted(bounds)))


def assert_no_undeclared_upper_bound(
    scan: BoundScan,
    *,
    policy: str,
    declared: Mapping[str, str],
    floor: int,
    headroom: int,
    requirement_floor: int,
    requirement_headroom: int,
    what: str,
) -> None:
    """THE CHECK: both floors on both sides, then the policy the repo declared.

    Args:
        scan: what :func:`take_scan` returned.
        policy: a member of :data:`POLICIES`. NO DEFAULT -- one consumer bans the bound and the other
            requires it to be argued, and neither answer is safe to inherit.
        declared: requirement name to the REASON it may carry a ceiling, and what it moves with.
            Two-sided under either policy: an undeclared bound reds, and a declared name with no
            bound left reds too. Under ``'ban'`` this must be EMPTY, and the refusal says so rather
            than quietly ignoring it -- a policy that accepted a non-empty waiver set while calling
            itself a ban is the declaration that lies.
        floor: the consumer's MEASURED count of manifests read. NO DEFAULT.
        headroom: how far past it the population may grow before the floor is re-measured.
        requirement_floor: the MEASURED count of requirements across those manifests, which refuses
            the silence the manifest floor cannot see -- a file read whose dependency table was
            renamed declares zero requirements and zero ceilings.
        requirement_headroom: the same band for that population.
        what: names the guard in the floor refusals. NO DEFAULT.

    Raises:
        ValueError: *policy* is not a member of :data:`POLICIES`.
        lab_commons.dev.floors.FloorUnmet: a population is below its floor.
        lab_commons.dev.floors.SlackFloor: a floor has stopped binding.
        UndeclaredUpperBound: the ratchet moved in either direction.
        UnreasonedWaiver: a declared bound carries an empty reason.

    """
    if policy not in POLICIES:
        msg = f'{policy!r} is not one of {sorted(POLICIES)}; a policy nobody declared cannot judge anything.'
        raise ValueError(msg)
    manifests = f'{what} (manifests)'
    reqs = f'{what} (requirements)'
    floors.assert_floor(scan.files_read, floor=floor, what=manifests)
    floors.assert_floor_still_binds(scan.files_read, floor=floor, headroom=headroom, what=manifests)
    floors.assert_floor(scan.requirements_seen, floor=requirement_floor, what=reqs)
    floors.assert_floor_still_binds(
        scan.requirements_seen, floor=requirement_floor, headroom=requirement_headroom, what=reqs
    )
    if policy == 'ban' and declared:
        msg = (
            f'the policy is {policy!r} and {sorted(declared)} are declared. A ban with a waiver list is not '
            f'a ban -- either the bounds come out, or the repo is on the declare policy and should say so.'
        )
        raise UndeclaredUpperBound(msg)
    empty = sorted(name for name, reason in declared.items() if not reason.strip())
    if empty:
        msg = (
            f'{empty} are declared with no reason. A ceiling records what the code CANNOT take, and a '
            f'declaration that only records THAT it exists leaves the next reader nothing to re-argue it '
            f'with. Name why, and name whatever it moves with.'
        )
        raise UnreasonedWaiver(msg)
    found = {bound.name for bound in scan.bounds}
    pinned = set(declared)
    if found != pinned:
        arrived = sorted(
            f'{bound.manifest}: {bound.name} {bound.spec!r} -- {bound.why}'
            for bound in scan.bounds
            if bound.name not in pinned
        )
        gone = sorted(pinned - found)
        msg = (
            'the upper-bound ratchet moved.\n  UNDECLARED: '
            + ('\n    '.join(arrived) or 'none')
            + f'\n  DECLARED AND NO LONGER BOUND: {gone or "none"}\n'
            f'A floor states what the code needs and ages safely; a ceiling states what it cannot take and '
            f'nobody re-argues it. Remove the bound, or declare it with the reason and its partner -- and '
            f'delete an entry in the same edit that unbinds it, or the waiver outlives its argument.'
        )
        raise UndeclaredUpperBound(msg)


def assert_the_reader_still_convicts(*, ecosystem: str) -> None:
    """THE PLANTED CONTROL, in BOTH directions, driving the REAL reader over a REAL manifest.

    The planting is chosen so the ecosystems' disagreement is the arm rather than a note: under Cargo
    a bare ``0.29`` must be NAMED and a bare ``1.1`` must not, from the same spelling, and under
    PEP 508 a bare version is not a specifier at all. A reader that convicted both would make every
    Cargo manifest in this family an offender; one that convicted neither would be the state the rule
    was written to end.

    THE AXIS THIS CONTROL IS BLIND TO: it plants MANIFEST TEXT and proves nothing about which
    manifests a consumer hands over. A repo whose Cargo workspace members are not in its path list
    passes every arm here; that axis belongs to the two floors in
    :func:`assert_no_undeclared_upper_bound`.

    Args:
        ecosystem: the dialect to exercise -- a member of :data:`ECOSYSTEMS`.

    Raises:
        AssertionError: the reader missed a planted ceiling, or named a requirement that is a floor.

    """
    if ecosystem == 'pep508':
        text = (
            '[project]\n'
            'dependencies = ["numpy>=1.2", "bokeh~=3.8.0", "pandas", "scipy<2", "ruff!=0.5.0"]\n'
            '[project.optional-dependencies]\n'
            'dev = ["pytest==8.0"]\n'
        )
        expected = {'bokeh', 'scipy', 'ruff', 'pytest'}
        floated = {'numpy', 'pandas'}
    else:
        text = (
            '[dependencies]\n'
            'pyo3 = "0.29"\n'
            'robust = "1.1"\n'
            'serde = { version = "1", features = ["derive"] }\n'
            'faer = "~0.24"\n'
            'local = { path = "../local" }\n'
            '[dev-dependencies]\n'
            'criterion = "=0.5.1"\n'
        )
        expected = {'pyo3', 'faer', 'criterion'}
        floated = {'robust', 'serde', 'local'}

    found = upper_bounds(text, ecosystem=ecosystem, manifest='planted.toml')
    named = {bound.name for bound in found}
    if named != expected:
        msg = (
            f'under {ecosystem!r} the reader named {sorted(named)} and the planted ceilings are '
            f'{sorted(expected)}. Every requirement in {sorted(floated)} is a FLOAT and must be left alone '
            f"-- under Cargo that includes a bare '1.1', which is a caret on a non-zero major and permits "
            f"the next minor, while the identically spelled '0.29' refuses it."
        )
        raise AssertionError(msg)
    if any(not bound.why.strip() for bound in found):
        msg = 'every bound must say HOW it is one: an invisible caret and an explicit operator are repaired differently'
        raise AssertionError(msg)
    if len(requirements(text, ecosystem=ecosystem)) != len(expected | floated):
        msg = (
            'the reader lost a requirement: it must see every declared name, optional and '
            'development tables included, or the requirement floor is measured against a short list.'
        )
        raise AssertionError(msg)
