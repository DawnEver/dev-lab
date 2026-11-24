"""THE IR VERSION CLASS: what a schema change IS, computed by diffing against a git revision.

``version`` in ``[tool.dev_lab.ir_schema]`` is ``MAJOR.MINOR.PATCH``, one epoch per repo (``docs-src/dev/ir-schema.md``,
"Versioning"). PATCH is docs only; MINOR is additive (a new optional field, record, enum, enum value, quantity, port
domain, dim or module); MAJOR is everything else, and its tracked records migrate once in the same change. The
generator refuses a declared bump below the class it computes here (``IR-VERSION-NOT-BUMPED``).
"""

from __future__ import annotations

import dataclasses
import enum
import shutil
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

import lab_commons.launch as _door

from dev_lab.dev.ircheck import records_reached
from dev_lab.dev.irmodel import parse

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from dev_lab.dev.irmodel import IR, Record

__all__ = ['Change', 'Level', 'at_revision', 'bump_refusal', 'classify', 'declared_level']

_GIT: Final = shutil.which('git') or 'git'
_GIT_TIMEOUT_S: Final = 60.0


class Level(enum.IntEnum):
    """How far a change reaches; ordered, so a declared bump compares against a computed one."""

    NONE = 0
    PATCH = 1
    MINOR = 2
    MAJOR = 3


@dataclass(frozen=True)
class Change:
    """The class of a change, the records it touches (qualified), and one line per reason."""

    level: Level
    records: frozenset[str] = frozenset()
    why: tuple[str, ...] = ()


def _undocumented(record: Record) -> tuple:
    return tuple(dataclasses.replace(f, doc='') for f in record.fields)


def _record_level(old: Record, new: Record) -> tuple[Level, str]:
    if _undocumented(old) == _undocumented(new):
        return (Level.PATCH, 'docs') if (old.doc, old.fields) != (new.doc, new.fields) else (Level.NONE, '')
    before = {f.name: dataclasses.replace(f, doc='') for f in old.fields}
    after = {f.name: dataclasses.replace(f, doc='') for f in new.fields}
    if any(name not in after or after[name] != f for name, f in before.items()):
        return Level.MAJOR, 'a field was removed or changed'
    if any(not after[name].optional for name in after.keys() - before.keys()):
        return Level.MAJOR, 'a required field was added'
    return Level.MINOR, 'an optional field was added'


def _records(ir: IR) -> dict[str, Record]:
    return {f'{m.name}.{r.name}': r for m in ir.modules.values() for r in m.records.values()}


def _enum_users(ir: IR, qualified_enum: str) -> set[str]:
    return {
        name
        for name, record in _records(ir).items()
        for f in record.fields
        if qualified_enum in (f.type.target, f.type.item.target if f.type.item else '')
    }


def _containers(ir: IR, touched: set[str]) -> set[str]:
    """*touched* plus every record that holds one of them by value, transitively."""
    records = _records(ir)
    grown = set(touched)
    while True:
        more = {name for name, record in records.items() if grown & set(records_reached(record))} - grown
        if not more:
            return grown
        grown |= more


def _catalogue_level(old: IR, new: IR) -> tuple[Level, str]:
    if any(new.quantities.get(n) != q for n, q in old.quantities.items()):
        return Level.MAJOR, 'a quantity was removed or changed'
    if any(new.port_domains.get(n) != d for n, d in old.port_domains.items()):
        return Level.MAJOR, 'a port domain was removed or changed'
    if new.quantities.keys() - old.quantities.keys() or new.port_domains.keys() - old.port_domains.keys():
        return Level.MINOR, 'a quantity or port domain was added'
    return Level.NONE, ''


type _Note = tuple[Level, str, set[str]]


def _record_notes(old: IR, new: IR) -> Iterator[_Note]:
    before, after = _records(old), _records(new)
    for name in before.keys() - after.keys():
        yield Level.MAJOR, f'{name} was removed', {name}
    for name in after.keys() - before.keys():
        yield Level.MINOR, f'{name} was added', {name}
    for name in before.keys() & after.keys():
        found, reason = _record_level(before[name], after[name])
        yield found, f'{name}: {reason}', {name}


def _module_notes(old: IR, new: IR) -> Iterator[_Note]:
    for module in old.modules.values():
        other = new.modules.get(module.name)
        for enum_name, old_enum in module.enums.items():
            qualified = f'{module.name}.{enum_name}'
            new_enum = None if other is None else other.enums.get(enum_name)
            if new_enum is None or not set(old_enum.values) <= set(new_enum.values):
                yield Level.MAJOR, f'{qualified}: a value was removed', _enum_users(old, qualified)
            elif new_enum.values != old_enum.values:
                yield Level.MINOR, f'{qualified}: a value was added', _enum_users(new, qualified)
        if other is not None and any(other.dims.get(d) != b for d, b in module.dims.items()):
            yield Level.MAJOR, f'{module.name}: a dim bound was removed or changed', set()


def _text_moved(old: IR, new: IR) -> bool:
    sources = any(old.modules[m].source != n.source for m, n in new.modules.items() if m in old.modules)
    return sources or old.catalogue_source != new.catalogue_source


def classify(old: IR | None, new: IR) -> Change:
    """The class of the change from *old* (``None``: no IR before) to *new*."""
    if old is None:
        return Change(Level.MINOR, frozenset(_records(new)), ('the IR is new',))
    level, catalogue_why = _catalogue_level(old, new)
    notes = [(level, catalogue_why, set()), *_record_notes(old, new), *_module_notes(old, new)]
    notes = [note for note in notes if note[0] > Level.NONE]
    if not notes and _text_moved(old, new):
        notes = [(Level.PATCH, 'docs', set())]
    touched = set().union(*(names for _, _, names in notes))
    current = set(_records(new))
    records = _containers(new, touched & current) | (touched - current)
    return Change(max((n[0] for n in notes), default=Level.NONE), frozenset(records), tuple(n[1] for n in notes))


def declared_level(old: tuple[int, int, int], new: tuple[int, int, int]) -> Level | None:
    """The bump *old* -> *new* declares; ``None`` for a version that went backwards."""
    if new < old:
        return None
    for level, (a, b) in zip((Level.MAJOR, Level.MINOR, Level.PATCH), zip(old, new, strict=True), strict=True):
        if b != a:
            return level
    return Level.NONE


def bump_refusal(old: IR | None, new: IR) -> str | None:
    """``IR-VERSION-NOT-BUMPED`` naming the computed class and the reasons, or ``None`` when the bump covers it."""
    change = classify(old, new)
    if old is None or change.level == Level.NONE:
        return None
    was, now = old.declaration.version, new.declaration.version
    declared = declared_level(was, now)
    if declared is not None and declared >= change.level:
        return None
    return (
        f'IR-VERSION-NOT-BUMPED: version {old.declaration.version_text} -> {new.declaration.version_text} declares '
        f'{"a decrease" if declared is None else declared.name}, the change is {change.level.name} '
        f'({"; ".join(change.why)}) -- bump [tool.dev_lab.ir_schema] version to at least the next {change.level.name}'
    )


def at_revision(root: Path, revision: str) -> IR | None:
    """The repo's IR as committed at *revision*; ``None`` when it declared none there."""

    def read(relative: str) -> str:
        done = _door.run(
            [_GIT, '-C', str(root), 'show', f'{revision}:{relative}'],
            capture_output=True,
            text=True,
            encoding='utf-8',
            check=False,
            timeout=_GIT_TIMEOUT_S,
        )
        if done.returncode != 0:
            raise FileNotFoundError(relative)
        return done.stdout

    try:
        return parse(root, read)
    except FileNotFoundError:
        return None
