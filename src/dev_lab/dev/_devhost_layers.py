"""The machine file holds the host and local layers only: a family leaf is stripped from a render, never restated.

Split out of :mod:`dev_lab.dev.devhost` (2026-11-25, MODULE-SIZE-ALARM) along its own seam: that module renders
and drives the verbs; this one decides which leaves of a layered render belong to the family file.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from lab_commons import config as machineconfig

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

__all__ = ['family_facts_stay_home']


def family_facts_stay_home(
    layered: Mapping[str, Any], family: Mapping[str, Any], clone: Path, *, door: str
) -> dict[str, Any]:
    """*layered* without every leaf the family file holds, and with ``[family] source`` naming that file's clone.

    *door* is the re-render command a refusal names.

    The machine file is the host and local layers only: a reader layers the family file under it
    (``lab_commons.config.section``) and refuses any leaf both hold. Measured 2026-11-20: the render copied the
    family's ``[storage] remotes`` and then ``[breakglass] endpoint`` into the machine file and both readers refused.

    Raises:
        ValueError: the host layer gives a family leaf another value -- the reader refuses a restated leaf, so the
            value is changed in the family file (or the host declares a key the family does not hold).

    """

    def strip(rows: Mapping[str, Any], shared: Mapping[str, Any], where: str) -> dict[str, Any]:
        kept: dict[str, Any] = {}
        for key, value in rows.items():
            if key not in shared or key == machineconfig.FAMILY_TABLE:
                kept[key] = value
            elif isinstance(value, Mapping) and isinstance(shared[key], Mapping):
                if inner := strip(value, shared[key], f'{where}.{key}' if where else key):
                    kept[key] = inner
            elif value != shared[key]:
                leaf = f'[{where}].{key}' if where else key
                msg = (f'{leaf} = {value!r} gives the family key ({shared[key]!r}) another value: change it in the '
                       f'family file through its pull request, then {door}')  # fmt: skip
                raise ValueError(msg)
        return kept

    kept = strip(layered, family, '')
    kept.setdefault(machineconfig.FAMILY_TABLE, {'source': clone.resolve().as_posix()})
    return kept
