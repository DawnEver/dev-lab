"""Who is in the family: a checkout that declares itself one, and nothing kept here.

A repository joins by adopting this package -- by carrying a ``[tool.lab_commons]`` table in its own
``pyproject.toml`` -- so membership has ONE source, the member's own manifest. A list of names here
would be a second source that drifts (a lab that adopts the kit and is missing from the list is
refused by every door that consults it), and it would put consumer names into the leaf, which
:mod:`lab_commons.dev.foreign` forbids.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

__all__ = ['is_member']


def is_member(root: Path) -> bool:
    """Whether the checkout at *root* declares a ``[tool.lab_commons]`` table in its ``pyproject.toml``.

    No manifest, or one that is not TOML, is not a member: a door that cannot read the declaration
    has nothing to admit.
    """
    try:
        data = tomllib.loads((root / 'pyproject.toml').read_text(encoding='utf-8'))
    except (OSError, tomllib.TOMLDecodeError):
        return False
    return isinstance(data.get('tool', {}).get('lab_commons'), dict)
