"""HOW A MANIFEST SPELLS A CEILING, in two dialects that disagree -- the READINGS, never a verdict.

Split out of :mod:`lab_commons.dev.famtests.upperbounds` at the seam that module's own first sentence
names, and the reason it is a real seam rather than a size repair: everything here answers about
TEXT and knows nothing about a repo. No floor, no policy, no declaration, and nothing that raises a
verdict -- which is what lets a control drive these functions directly, on a planted manifest, in
both directions.

THE ONE FACT THAT MAKES THIS WORTH A MODULE. ``pyo3 = "0.29"`` and ``robust = "1.1"`` are the same
spelling and only the first is an upper bound, because Cargo's implied caret binds at the leftmost
NON-ZERO component. Under PEP 508 a bare version is not a specifier at all. So a bound is not "an
upper limit exists" -- under a caret one always does -- it is whatever REFUSES THE ECOSYSTEM'S NEXT
NON-BREAKING RELEASE, and that predicate is per dialect. :func:`_why_bounded` is the one place it is
decided, so a third dialect is an entry there rather than a branch in a verdict.

The import runs ONE WAY: the verdicts next door import these, and nothing here imports them back.
"""

from __future__ import annotations

import re
import tomllib
from typing import TYPE_CHECKING, Final, NamedTuple

if TYPE_CHECKING:
    from collections.abc import Mapping

__all__ = [
    'ECOSYSTEMS',
    'Bound',
    'requirements',
    'upper_bounds',
]

#: The manifest dialects this module can read, as a NAMED SET so a consumer parametrizes over it and
#: a dialect silently dropped is a hole with a name rather than a smaller green run.
ECOSYSTEMS: Final[frozenset[str]] = frozenset({'pep508', 'cargo'})


#: PEP 508 operators that refuse a later release. ``>=`` and ``>`` are absent: a floor is the shape
#: this rule permits. ``!=`` is here because it refuses one specific release, which is a ceiling with
#: a hole in it rather than a floor.
_PEP508_CEILINGS: Final[tuple[str, ...]] = ('<=', '!=', '~=', '==', '<')

#: The tables a Cargo manifest declares requirements in. Named rather than walked, so a table added
#: by Cargo that this module cannot read stays invisible instead of silently reading as empty.
_CARGO_TABLES: Final[tuple[str, ...]] = ('dependencies', 'dev-dependencies', 'build-dependencies')

#: A Cargo requirement whose CARET -- written or implied -- lands on a ``0.x`` version, where the
#: MINOR is the breaking slot. This is the bound that announces nothing.
_CARET_ZERO: Final = re.compile(r'^\s*\^?0\.\d+(?:\.\d+)?\s*$')

#: A Cargo operator that refuses the next non-breaking release whatever the version: an exact match,
#: a tilde (patch-only), or an explicit ceiling.
_CARGO_CEILINGS: Final[tuple[str, ...]] = ('<=', '~', '=', '<')

#: Where a PEP 508 requirement's name stops and its specifier begins.
_PEP508_NAME: Final = re.compile(r'^\s*([A-Za-z0-9][A-Za-z0-9._-]*)\s*(?:\[[^\]]*\])?\s*(.*)$')


class Bound(NamedTuple):
    """One ceiling, and HOW it is one: ``(manifest, name, spec, why)``.

    *why* is the half a bare offender list cannot carry. ``'caret on a 0.x version'`` and
    ``'the <= operator'`` are both upper bounds and a reader repairs them differently -- the first is
    invisible in the text and the second is right there -- so naming the mechanism is what makes the
    refusal actionable rather than merely correct.
    """

    manifest: str
    name: str
    spec: str
    why: str


def requirements(text: str, *, ecosystem: str) -> tuple[tuple[str, str], ...]:
    """Every ``(name, spec)`` a manifest declares, from the tables *ecosystem* puts them in.

    Args:
        text: the manifest's TOML source.
        ecosystem: a member of :data:`ECOSYSTEMS`. NO DEFAULT -- the dialects disagree about what a
            bare version string MEANS, so a guessed one reads a real bound as a floor. There is no
            ``manifest`` argument here and there is one on :func:`upper_bounds`: this function answers
            about TEXT and only a refusal needs to say which file it came from.

    Returns:
        Pairs in declaration order, REQUIRED and OPTIONAL alike: an optional extra installs into the
        same resolution and a ceiling there binds exactly as hard.

    Raises:
        ValueError: *ecosystem* is not a member of :data:`ECOSYSTEMS`.
        tomllib.TOMLDecodeError: the manifest is not readable TOML.

    """
    if ecosystem not in ECOSYSTEMS:
        msg = f'{ecosystem!r} is not one of {sorted(ECOSYSTEMS)}; a dialect nobody declared cannot be read.'
        raise ValueError(msg)
    data = tomllib.loads(text)
    if ecosystem == 'pep508':
        return _pep508_requirements(data)
    return _cargo_requirements(data)


def _pep508_requirements(data: Mapping[str, object]) -> tuple[tuple[str, str], ...]:
    """``[project] dependencies`` plus every ``optional-dependencies`` group, in that order."""
    project = data.get('project')
    if not isinstance(project, dict):
        return ()
    listed: list[str] = [item for item in project.get('dependencies', []) if isinstance(item, str)]
    extras = project.get('optional-dependencies')
    if isinstance(extras, dict):
        for group in extras.values():
            listed.extend(item for item in group if isinstance(item, str))
    out: list[tuple[str, str]] = []
    for item in listed:
        head = item.split(';', 1)[0]
        found = _PEP508_NAME.match(head)
        if found is not None:
            out.append((found.group(1), found.group(2).strip()))
    return tuple(out)


def _cargo_requirements(data: Mapping[str, object]) -> tuple[tuple[str, str], ...]:
    """Every named table's entries, whether spelled as a string or as a table with ``version``.

    A table entry with NO ``version`` key -- a path or git dependency -- yields an empty spec and is
    therefore never a bound. That is the true answer rather than a convenient one: such a dependency
    is pinned by something this module does not read, and claiming otherwise would be a scope claim
    with nothing under it.
    """
    out: list[tuple[str, str]] = []
    for table_name in _CARGO_TABLES:
        for where in (data, data.get('workspace', {})):
            table = where.get(table_name) if isinstance(where, dict) else None
            if not isinstance(table, dict):
                continue
            for name, value in table.items():
                if isinstance(value, str):
                    out.append((name, value))
                elif isinstance(value, dict):
                    version = value.get('version')
                    out.append((name, version if isinstance(version, str) else ''))
    return tuple(out)


def _why_bounded(spec: str, *, ecosystem: str) -> str | None:
    """Why *spec* refuses the next non-breaking release, or ``None`` when it does not.

    THE ASYMMETRY IS HERE AND NOWHERE ELSE. Under PEP 508 an absent operator means "any version" and
    only an explicit ceiling binds. Under Cargo an absent operator means a CARET, which binds at the
    leftmost non-zero component -- so ``0.29`` refuses the next minor and ``1.1`` does not, from the
    same spelling. See the module docstring for the measurement that made this visible.
    """
    text = spec.strip()
    if not text:
        return None
    if ecosystem == 'pep508':
        for operator in _PEP508_CEILINGS:
            if operator in text:
                return f'the {operator} operator'
        return None
    for operator in _CARGO_CEILINGS:
        if text.startswith(operator):
            return f'the {operator} operator'
    if _CARET_ZERO.match(text):
        return 'a caret on a 0.x version, where the MINOR is the breaking slot and nothing says so'
    return None


def upper_bounds(text: str, *, ecosystem: str, manifest: str) -> tuple[Bound, ...]:
    """Every requirement in *text* that refuses the next non-breaking release. Pure over its argument."""
    found = [
        Bound(manifest, name, spec, why)
        for name, spec in requirements(text, ecosystem=ecosystem)
        if (why := _why_bounded(spec, ecosystem=ecosystem)) is not None
    ]
    return tuple(sorted(found))
