"""THE DECLARED SCHEDULE: a repo's ``[tool.lab_commons.schedule]`` read once over the family default.

Each duration is parsed once, with its unit, and held in hours (its :class:`~lab_commons.compute.model.Schedule`
field's unit); a retired, renamed or unknown key is refused by name. The scheduler that reads it is
:mod:`dev_lab.dev.forgeschedule`.
"""

from __future__ import annotations

import dataclasses
import tomllib
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Final

from lab_commons.compute.model import (
    SCHEDULE_TABLE,
    Schedule,
)
from lab_commons.hpc.retired import RETIRED
from lab_commons.quantity import Renamed, form, parse, refuse_renamed

#: The schedule's durations: declared key -> (:class:`Schedule` field, held in hours; a table of class -> duration).
#: The Schedule's field names are lab-commons'; this table is where the declared, unit-free keys meet them.
_HOURS: Final = {
    'starve_after': ('starve_after_hours', True),
    'daily_budget': ('daily_budget_core_h', True),
    'prior_cost': ('prior_cost_h', False),
    'request_unadmitted': ('request_unadmitted_hours', False),
}


#: The unit-suffixed keys the 2026-11-25 ruling retired (the value carries its unit), each refused with its new line.
SCHEDULE_RENAMED: Final = {field: Renamed(key, 'h') for key, (field, _table) in _HOURS.items()}


def load_schedule(root: Path) -> Schedule:
    """*root*'s ``[tool.lab_commons.schedule]`` over the family default; an unknown key is refused."""
    manifest = root / 'pyproject.toml'
    declared: dict[str, Any] = {}
    if manifest.is_file():
        with manifest.open('rb') as handle:
            declared = tomllib.load(handle).get('tool', {}).get('lab_commons', {}).get(SCHEDULE_TABLE, {})
    default = Schedule()
    where = f'[tool.lab_commons.{SCHEDULE_TABLE}] in {manifest}:'
    _refuse_unit_keys(where, declared)
    retired = [
        f'{key} is retired: {RETIRED[f"{SCHEDULE_TABLE}] {key}"]}'
        for key in declared
        if f'{SCHEDULE_TABLE}] {key}' in RETIRED
    ]
    if retired:
        msg = f'[tool.lab_commons.{SCHEDULE_TABLE}] in {manifest}: ' + '; '.join(retired)
        raise ValueError(msg)
    known = {one.name for one in dataclasses.fields(Schedule)} - set(SCHEDULE_RENAMED) | set(_HOURS)
    unknown = sorted(set(declared) - known)
    if unknown:
        msg = (
            f'[tool.lab_commons.{SCHEDULE_TABLE}] in {manifest} has unknown key(s) {unknown}; '
            f'the keys are {sorted(known)}'
        )
        raise ValueError(msg)
    merged: dict[str, Any] = {}
    defaults = dataclasses.asdict(default)
    for key, given in _in_hours(where, declared).items():
        current = defaults[key]
        replaces = key == 'classes_by_ref' or not isinstance(current, Mapping)
        merged[key] = given if replaces else {**current, **given}
    schedule = dataclasses.replace(default, **merged)
    undeclared = sorted(set(schedule.classes_by_ref.values()) - set(schedule.classes))
    if undeclared:
        msg = (
            f'[tool.lab_commons.{SCHEDULE_TABLE}] classes_by_ref in {manifest} names class(es) {undeclared} '
            f'that classes does not value: {sorted(schedule.classes)}'
        )
        raise ValueError(msg)
    return schedule


def _refuse_unit_keys(where: str, declared: Mapping[str, Any]) -> None:
    """Refuse a retired unit-suffixed key, writing its new line from its own value (a table: each class's)."""
    for old, new in SCHEDULE_RENAMED.items():
        table = declared.get(old) if isinstance(declared.get(old), Mapping) else None
        if table is not None:
            pairs = ', '.join(f'{name} = {form(hours, new.unit)}' for name, hours in table.items())
            msg = (
                f'{where} {old} is retired (user ruling 2026-11-25: a value carries its unit, parsed once by '
                f'lab_commons.quantity): write {new.key} = {{{pairs}}}'
            )
            raise ValueError(msg)
    refuse_renamed(where, declared, SCHEDULE_RENAMED)


def _in_hours(where: str, declared: Mapping[str, Any]) -> dict[str, Any]:
    """*declared* keyed by :class:`Schedule` field, each duration read once and held in hours (its field's unit)."""

    def hours(label: str, value: object, *, positive: bool) -> float:
        return parse(f'{where} {label}', value, 'duration', positive=positive) / 3600

    out: dict[str, Any] = {}
    for key, given in declared.items():
        if key not in _HOURS:
            out[key] = given
            continue
        field, table = _HOURS[key]
        positive = key != 'daily_budget'  # a zero budget is a class never claimed on a cluster: declarable
        if table and not isinstance(given, Mapping):
            msg = f'{where} {key} is a table of class -> duration, such as {{integration = "6 h"}}'
            raise ValueError(msg)
        out[field] = (
            {name: hours(f'{key}.{name}', value, positive=positive) for name, value in given.items()}
            if table
            else hours(key, given, positive=positive)
        )
    return out
