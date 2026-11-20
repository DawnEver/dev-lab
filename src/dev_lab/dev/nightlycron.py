"""A workflow's ``nightly`` declaration read as the cron it schedules (D63: the time is a per-repo setting).

``true`` asks for the family default, ``false`` for none, and a string is the repo's own 5-field cron; anything
else is refused naming where it was declared. PURE: no I/O.
"""

from __future__ import annotations

import re
from typing import Any, Final

__all__ = ['NIGHTLY_CRON', 'NIGHTLY_KEY', 'nightly_cron', 'scheduled']

#: The table key asking for the nightly schedule; a trigger, never part of the rendered workflow.
NIGHTLY_KEY: Final = 'nightly'
#: When a nightly workflow runs unless its repo sets ``nightly = "<cron>"`` (D48-1A, user ruling 2026-11-01): 02:00
#: UTC. GitHub starts it ~6-8 h late (measured 2026-11-18); D63 accepts the delay and makes the time per-repo.
NIGHTLY_CRON: Final = '0 2 * * *'
_CRON_FIELDS: Final = 5
_CRON_FIELD: Final = re.compile(r'[0-9*,/-]+')


def nightly_cron(value: object, where: str, default: str = NIGHTLY_CRON) -> str | None:
    """The cron a ``nightly`` *value* schedules: none for ``false``, *default* for ``true``, else the repo's own.

    A string must be five cron fields of digits, ``*``, ``,``, ``/``, ``-``; anything else is refused naming *where*.
    """
    if value is False:
        return None
    if value is True:
        return default
    fields = value.split() if isinstance(value, str) else []
    if len(fields) != _CRON_FIELDS or not all(_CRON_FIELD.fullmatch(field) for field in fields):
        msg = f'{where} = {value!r}: not a 5-field cron (e.g. {default!r}); give true for the default or a cron'
        raise ValueError(msg)
    return ' '.join(fields)


def scheduled(workflow: dict[str, Any], table: str) -> dict[str, Any]:
    """*workflow* with its :data:`NIGHTLY_KEY` trigger removed and, when it asks for one, its schedule added. PURE.

    *table* names the declaring table in a refusal (``[tool.dev_lab.ci."<name>"]``).
    """
    rest = {key: value for key, value in workflow.items() if key != NIGHTLY_KEY}
    if cron := nightly_cron(workflow.get(NIGHTLY_KEY, False), f'{table} {NIGHTLY_KEY}'):
        rest['on'] = {**rest['on'], 'schedule': [{'cron': cron}]}
    return rest
