"""Who is in the family: a checkout that declares itself one, and nothing kept here.

A repository joins by adopting the kit -- by carrying a ``[tool.dev_lab]`` or ``[tool.lab_commons]`` table
in its own ``pyproject.toml`` -- so membership has ONE source, the member's own manifest. A list of names
here would be a second source that drifts (a lab that adopts the kit and is missing from the list is
refused by every door that consults it), and it would put consumer names into the leaf, which
:mod:`dev_lab.dev.foreign` forbids.

dev-lab's own tables live under ``[tool.dev_lab.<name>]`` and are read through :func:`declared_table`, the
ONE place that spells the namespace; ``[tool.lab_commons.<name>]`` holds only what lab-commons reads.
"""

from __future__ import annotations

import tomllib
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Final

from lab_commons.hpc.declared import RetiredTable, kit_tables

__all__ = ['NAMESPACE', 'declared_in', 'declared_table', 'is_member']

#: The ``[tool.<NAMESPACE>]`` dev-lab's own configuration tables live under.
NAMESPACE: Final = 'dev_lab'


def declared_table(data: Mapping[str, Any], name: str, default: Any = None) -> Any:  # noqa: ANN401 -- TOML is untyped
    """``[tool.dev_lab.<name>]`` of parsed pyproject *data*, else *default*.

    The old spelling is REFUSED, never read as absent: an unmigrated ``[tool.lab_commons.<name>]`` read as
    *default* would silently switch off what it declares (a hook row, an allowed skip, a door).

    Raises:
        RetiredTable: *data* still declares ``[tool.lab_commons.<name>]``; the message names the replacement.

    """
    tool = data.get('tool', {})
    if name in tool.get('lab_commons', {}):
        msg = f'[tool.lab_commons.{name}] is retired: declare it as [tool.{NAMESPACE}.{name}]'
        raise RetiredTable(msg)
    return tool.get(NAMESPACE, {}).get(name, default)


def declared_in(text: str, name: str) -> dict[str, Any]:
    """``[tool.dev_lab.<name>]`` of pyproject *text*, after :func:`kit_tables` refuses a retired or unknown kit table.

    Raises:
        RetiredTable: *text* declares a retired ``[tool.lab_commons]`` table; the message names its replacement.
        OutdatedKit: *text* declares a ``[tool.lab_commons]`` table this kit does not know.

    """
    kit_tables(text)
    return declared_table(tomllib.loads(text), name, {})


def is_member(root: Path) -> bool:
    """Whether the checkout at *root* declares a ``[tool.dev_lab]`` or ``[tool.lab_commons]`` table.

    No manifest, or one that is not TOML, is not a member: a door that cannot read the declaration
    has nothing to admit.
    """
    try:
        data = tomllib.loads((root / 'pyproject.toml').read_text(encoding='utf-8'))
    except (OSError, tomllib.TOMLDecodeError):
        return False
    tool = data.get('tool', {})
    return isinstance(tool.get(NAMESPACE), dict) or isinstance(tool.get('lab_commons'), dict)
