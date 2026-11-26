"""The forge schedule's DURATIONS: ``[tool.lab_commons.schedule]`` keys whose value carries its unit.

User ruling 2026-11-25: a value carries its unit, parsed once by :mod:`lab_commons.quantity`. The declared keys
are unit-free (``starve_after = "6 h"``); lab-commons' :class:`~lab_commons.compute.model.Schedule` holds them in
hours under its own field names, and this module is where the two meet. :mod:`dev_lab.dev.forgeschedule` reads
the table through it.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Final

from lab_commons.quantity import Renamed, form, parse, refuse_renamed

__all__ = ['HOURS', 'SCHEDULE_RENAMED', 'in_hours', 'refuse_unit_keys']

#: The schedule's durations: declared key -> (:class:`Schedule` field, held in hours; a table of class -> duration).
#: The Schedule's field names are lab-commons'; this table is where the declared, unit-free keys meet them.
HOURS: Final = {
    'starve_after': ('starve_after_hours', True),
    'daily_budget': ('daily_budget_core_h', True),
    'prior_cost': ('prior_cost_h', False),
    'request_unadmitted': ('request_unadmitted_hours', False),
}
#: The unit-suffixed keys the 2026-11-25 ruling retired (the value carries its unit), each refused with its new line.
SCHEDULE_RENAMED: Final = {field: Renamed(key, 'h') for key, (field, _table) in HOURS.items()}


def refuse_unit_keys(where: str, declared: Mapping[str, Any]) -> None:
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


def in_hours(where: str, declared: Mapping[str, Any]) -> dict[str, Any]:
    """*declared* keyed by :class:`Schedule` field, each duration read once and held in hours (its field's unit)."""

    def hours(label: str, value: object, *, positive: bool) -> float:
        return parse(f'{where} {label}', value, 'duration', positive=positive) / 3600

    out: dict[str, Any] = {}
    for key, given in declared.items():
        if key not in HOURS:
            out[key] = given
            continue
        field, table = HOURS[key]
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
