"""The VALUE half of `UNITS-GO-THROUGH-PINT`: a name that stopped spelling its unit must have
handed that unit to its VALUE, and this is what proves it did.

WHY A SECOND MODULE AND NOT A WIDER `units.py`. :mod:`lab_commons.dev.units` refuses a NAME that
spells a unit (``slot_pitch_mm``). It is complete about what it does and blind to what happens
next, and the blindness has a direction: the cheapest way to make that scan green is to delete the
suffix. ``slot_pitch_mm = 12.5`` becomes ``slot_pitch = 12.5``, the scan goes quiet, and the unit
is now recorded NOWHERE -- not in the name it just left, not in the value it never reached. The
name check alone therefore REWARDS the lossy repair, and motronics' own waiver says so in prose
(``tests/architecture/docs/_units_gap.py``: "renaming a unit-suffixed name WITHOUT typing it
DELETES the unit rather than moving it, which is worse than leaving it") while nothing enforces the
sentence. This module is that enforcement.

THE MIGRATION IS THE SUBJECT, not the steady state. A key leaves a consumer's unconverted-name
waiver only by ENTERING the declared quantity registry this module checks, and
:func:`migration_conflicts` refuses a key that sits in both. That interlock is the whole design:
the two-sided ratchet on the NAME set has an exit, and this fixes where the exit leads. Delete
``intra_slot_pitch_deg`` from the waiver without declaring ``intra_slot_pitch`` here and the
interlock reds; declare it and the value scan below demands a real unit in the value.

DIMENSIONALITY IS THE WRONG QUESTION, AND THIS IS MEASURED RATHER THAN ARGUED. In pint, an ANGLE
is dimensionless::

    Q_('1.6 deg').dimensionality == Q_('1.6').dimensionality == 'dimensionless'
    Q_('1.6 deg').is_compatible_with('rad') is True
    Q_('1.6').is_compatible_with('rad')     is True      # <-- the defect, accepted

So a check written the obvious way -- "parse it and confirm the dimensionality matches" -- PASSES
the bare float it exists to catch, for every angular key. Measured 2026-09-16 against motronics'
declared set: of its 49 unconverted TOML keys, 15 are angular, so a dimensionality check would have
been blind on 31% of its own subject while reporting green. The test is therefore on the UNITS:
:func:`carries_a_unit` asks whether ``q.units`` is anything other than ``dimensionless``, and the
declared reference unit is checked only AFTER that gate. A guard whose natural spelling admits the
defect is the `DECLARATION-LIES` shape, and it is recorded here because the natural spelling is
what the next person will reach for.

WHAT IS SCANNED: TOML values, at every depth INCLUDING arrays of tables. The depth matters and is
not a detail -- a walk that descends dicts but not lists reported 43 of motronics' 49 keys as
absent from a tree that contains all 49, because six of them live only under ``[[...]]`` rows
(measured 2026-09-16; ``intra_slot_pitch_deg`` was one of the six). A scan that silently cannot see
a surface reports the same empty result as a clean one, which is the failure this module's floor
and :attr:`ValueScan.keys_seen` exist to make impossible.

TOML FIRST BECAUSE TOML IS WHERE THE UNIT HAS NOWHERE ELSE TO LIVE: the value is a float and the
document is untyped, so a manifest key is the one surface where the name was genuinely the only
record. A Python parameter can be TYPED instead (``LengthType`` via
:func:`lab_commons.units.get_quantity_type`), which is a different repair with a different
mechanism, and folding the two together would let progress on the easy one hide the hard one.
"""

from __future__ import annotations

import tomllib
from collections.abc import Collection, Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from lab_commons.units import Q_, ureg

__all__ = [
    'DIMENSIONLESS',
    'QuantitySite',
    'ValueScan',
    'assert_value_floor',
    'carries_a_unit',
    'migration_conflicts',
    'parse_quantity',
    'scan_toml_values',
    'value_ratchet',
    'value_remedy',
]

#: The unit spelling pint gives a value that carries no unit at all. Compared as a STRING because
#: that is the only comparison that separates ``'1.6 deg'`` from ``'1.6'`` -- see the module
#: docstring: their dimensionalities are equal and their compatibility answers are both True.
DIMENSIONLESS: Final = 'dimensionless'


@dataclass(frozen=True)
class QuantitySite:
    """One declared quantity key, and what its value actually was.

    *value* is kept as the REPR of the parsed TOML value rather than as raw text, because the defect
    is a TYPE fact -- a float where a quantity string was owed -- and a reader shown ``12.5`` cannot
    tell it from ``'12.5'``. *reason* names which of the three gates rejected it, so the remedy is
    decided by the record instead of re-derived from it.
    """

    path: str
    key: str
    value: str
    reason: str


@dataclass(frozen=True)
class ValueScan:
    """What the value scan found, together with what it was able to look at.

    Deliberately has no ``__len__``/``__bool__``, for the same reason
    :class:`lab_commons.dev.units.Scan` has none: a falsy scan makes "every value carries its unit"
    and "this scan read nothing" the same branch, and those are opposite facts. *keys_seen* is the
    declared keys actually ENCOUNTERED, which is what turns an empty *violations* into evidence --
    a declared key that appears nowhere is an orphan, not a success.
    """

    violations: tuple[QuantitySite, ...]
    files_read: int
    keys_seen: frozenset[str]
    unreadable: tuple[str, ...]

    def __iter__(self) -> Iterator[QuantitySite]:
        return iter(self.violations)


def parse_quantity(text: str) -> Any:
    """*text* as a pint quantity, or ``None`` when pint cannot read it.

    Every pint failure mode is folded into ``None`` on purpose: a caller asking "is this a quantity"
    has no use for the several unrelated ways it can fail to be one, and letting an
    ``UndefinedUnitError`` escape would make one typo in one manifest crash the scan instead of
    reporting that manifest.
    """
    try:
        return Q_(text)
    # Broad on purpose: pint raises from several unrelated hierarchies.
    except Exception:
        return None


def carries_a_unit(text: str) -> bool:
    """Whether *text* parses AND names a real unit -- the gate dimensionality cannot provide.

    ``'12.5 mm'`` and ``'1.6 deg'`` pass; ``'12.5'``, ``'abc'`` and ``'1.6 dimensionless'`` do not.
    """
    quantity = parse_quantity(text)
    return quantity is not None and str(quantity.units) != DIMENSIONLESS


def _compatible(text: str, reference: str) -> bool:
    """Whether *text*'s unit converts to *reference*. Assumes :func:`carries_a_unit` already passed."""
    quantity = parse_quantity(text)
    if quantity is None:
        return False
    try:
        return bool(quantity.is_compatible_with(ureg.Unit(reference)))
    # Broad on purpose: an undefined reference unit is a caller bug, reported here as a mismatch.
    except Exception:
        return False


def _walk(node: Any) -> Iterator[tuple[str, Any]]:
    """Every ``(key, value)`` pair at every depth, THROUGH LISTS AS WELL AS TABLES.

    The list arm is the one that was measured missing; see the module docstring.
    """
    if isinstance(node, dict):
        for key, value in node.items():
            yield key, value
            yield from _walk(value)
    elif isinstance(node, list):
        for item in node:
            yield from _walk(item)


def scan_toml_values(
    paths: Collection[str | Path],
    declared: Mapping[str, str],
    *,
    root: Path | None = None,
) -> ValueScan:
    """THE GUARD. Every site of a *declared* key whose value does not carry its unit.

    Args:
        paths: TOML files to read. Pair with a tracked-file listing; a file that cannot be parsed is
            reported in :attr:`ValueScan.unreadable` rather than passed over silently.
        declared: key name -> the REFERENCE UNIT its value must be convertible to (``'mm'``,
            ``'deg'``, ``'Pa'``). The mapping is the CONSUMER's data, for the same reason the token
            table is: a registry edited through the module that reads it drifts from what it
            describes.
        root: base for the reported relative paths; defaults to each path as given.

    Three gates, in order, each producing a distinct *reason*: the value must be a STRING
    (``bare-number`` otherwise -- a float has no room for a unit), the string must name a unit
    (``no-unit``), and that unit must convert to the declared reference (``wrong-unit``).
    """
    violations: list[QuantitySite] = []
    unreadable: list[str] = []
    seen: set[str] = set()
    files_read = 0
    for raw in paths:
        path = Path(raw)
        name = path.relative_to(root).as_posix() if root is not None and path.is_relative_to(root) else path.as_posix()
        try:
            document = tomllib.loads(path.read_text(encoding='utf-8'))
        except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError):
            unreadable.append(name)
            continue
        files_read += 1
        for key, value in _walk(document):
            reference = declared.get(key)
            if reference is None:
                continue
            seen.add(key)
            if isinstance(value, (dict, list)):
                continue
            if not isinstance(value, str):
                violations.append(QuantitySite(name, key, repr(value), 'bare-number'))
            elif not carries_a_unit(value):
                violations.append(QuantitySite(name, key, repr(value), 'no-unit'))
            elif not _compatible(value, reference):
                violations.append(QuantitySite(name, key, repr(value), 'wrong-unit'))
    return ValueScan(tuple(violations), files_read, frozenset(seen), tuple(unreadable))


def assert_value_floor(reached: int, floor: int, what: str) -> None:
    """Refuse a scan that read too little to have an opinion.

    A clean tree and a walk that never reached the tree produce the same empty result, so the SIZE
    of the scan is part of its verdict rather than a diagnostic printed beside it.
    """
    if reached < floor:
        msg = (
            f'the {what} scan reached {reached}, below the {floor} floor -- an empty result over a '
            f'corpus this small is a walk that did not reach the tree, not a tree that is clean.'
        )
        raise AssertionError(msg)


def value_remedy(site: QuantitySite, reference: str) -> str:
    """The refusal text for *site*, naming what to write instead rather than only what is wrong."""
    if site.reason == 'bare-number':
        return (
            f'{site.path}: `{site.key} = {site.value}` is a bare number, so its unit is recorded '
            f'nowhere -- not in the name it no longer spells, and not here. Write it as a quantity '
            f"STRING pint can read: `{site.key} = '<value> {reference}'`, and have the reader parse "
            f'it with `Q_(...)` instead of `float(...)`. Moving the unit is the repair; deleting the '
            f'suffix on its own is the loss this refuses.'
        )
    if site.reason == 'no-unit':
        return (
            f'{site.path}: `{site.key} = {site.value}` is a string pint reads as DIMENSIONLESS, '
            f'which is the same record a bare number leaves. Name the unit: '
            f"`{site.key} = '<value> {reference}'`."
        )
    return (
        f'{site.path}: `{site.key} = {site.value}` carries a unit that cannot convert to the '
        f'declared `{reference}`. Either the value or the declaration is wrong; fix the one that is, '
        f'and do not widen the declaration to admit a value you have not checked.'
    )


def migration_conflicts(unconverted: Collection[str], declared: Collection[str]) -> dict[str, str]:
    """THE INTERLOCK between the name waiver and this registry -- the two-sided half of the exit.

    A key name may be UNCONVERTED (still spelling its unit, waived) or DECLARED (its unit now lives
    in the value, checked here), and never both: both means the rename was recorded as done while
    the old spelling is still in the tree, which is the state that lets a migration report progress
    it did not make. Returns offending name -> what is wrong with it, empty when the sets are
    disjoint.

    The opposite direction -- a key in NEITHER set -- is deliberately not checked here: the name
    scan already reds an unconverted name nobody declared, and duplicating that judgement in two
    places is how two registries start disagreeing about the same tree.
    """
    both = set(unconverted) & set(declared)
    return {
        name: (
            f'{name!r} is in BOTH the unconverted-name waiver and the declared-quantity registry. '
            f'A name leaves the waiver by moving its unit into the value; until the old spelling is '
            f'gone from the tree it has not left, and holding both entries lets the migration report '
            f'a conversion that did not happen.'
        )
        for name in sorted(both)
    }


def value_ratchet(scan: ValueScan, declared: Collection[str]) -> list[str]:
    """Both sides: a declared key whose values are wrong, and a declared key that is not there.

    The second side is the one a suppression list never has. A registry entry matching nothing is
    not a clean result -- it is a row describing a key that was renamed, deleted, or never spelled
    the way the registry claims -- and it must be removed in the commit that made it stale.
    """
    problems = [f'{site.reason}: {site.path} -- {site.key} = {site.value}' for site in scan.violations]
    problems.extend(
        f'ORPHANED declaration {name!r} -- no such key was found in the scanned corpus; remove it '
        f'from the registry in this same commit.'
        for name in sorted(set(declared) - scan.keys_seen)
    )
    return problems
