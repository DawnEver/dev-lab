"""OWNER-DAG over the declaration itself: every name a row's reason CITES must have a row that grants it.

User-agreed 2026-11-25 (consumer v1 ledger D107). Two drafts of a ``dependencies.toml`` agreed with each other and
both missed rows their own reasons relied on -- a family package (``numerics_lab``) and, for the case pack, a
stdlib module and a package (``zipfile``, ``tomlkit``) -- because nothing reads the tree before the code exists, and
agreement between drafts measures nothing. The declaration can be read against itself before any code exists.

A reason CITES a name it writes in backticks (``tomlkit``, ``os.system``, ``std::fs``), or writes dotted with a
top that is a standard-library module or a ``[python.packages]`` row's top (``lab_commons.temp``,
``importlib.resources``) -- a dotted file name such as ``manifest.toml`` cites nothing. A cited name is granted by:

* a standard-library name (its top in ``sys.stdlib_module_names``: ``os.system``, ``builtins.open``,
  ``nt.environ``, private ``_thread``) -- a ``[python.stdlib]`` row, longest dotted prefix. Unlisted std is allowed
  in code, but a rule that names one is relying on a decision about it, so the decision is a row;
* any other Python name -- a ``[python.packages]`` row;
* in a ``[rust.*]`` reason, ``std::``/``core::``/``alloc::`` paths -- a ``[rust.std]`` row; any other name -- a
  ``[rust.external]`` or ``[rust.crates]`` row (``-`` and ``_`` alike).

And a ``[python.native]`` crate must be a ``[rust.crates]`` row whenever that table is declared.
"""

from __future__ import annotations

import re
import sys
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from collections.abc import Mapping

    from dev_lab.dev.deptable import Declared, Grant

__all__ = ['cited', 'problems']

_TICKED: Final = re.compile(r'`([^`\s]+)`')
_DOTTED: Final = re.compile(r'(?<![\w.`/])([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)+)(?![\w`/])')
_PYTHON_NAME: Final = re.compile(r'[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*')
_RUST_PATH: Final = re.compile(r'(?:std|core|alloc)(?:::\w+)+')
_CRATE: Final = re.compile(r'[A-Za-z_][\w-]*')


def cited(reason: str, package_tops: frozenset[str]) -> list[str]:
    """The names *reason* cites (see the module docstring), in order, each once."""
    names = [m for m in _TICKED.findall(reason) if _PYTHON_NAME.fullmatch(m) or _RUST_PATH.fullmatch(m)]
    tops = frozenset(sys.stdlib_module_names) | package_tops
    names += [m for m in _DOTTED.findall(reason) if m.split('.')[0] in tops]
    return list(dict.fromkeys(names))


def _longest(rows: Mapping[str, Grant], name: str, sep: str) -> bool:
    return any(name == key or name.startswith(key + sep) for key in rows)


def _python(decl: Declared, name: str) -> str | None:
    if name.split('.', maxsplit=1)[0] in sys.stdlib_module_names:
        return None if _longest(decl.stdlib, name, '.') else '[python.stdlib]'
    return None if _longest(decl.packages, name, '.') else '[python.packages]'


def _rust(decl: Declared, name: str) -> str | None:
    if _RUST_PATH.fullmatch(name):
        std = name.replace('core::', 'std::', 1).replace('alloc::', 'std::', 1)
        return None if _longest(decl.std, std, '::') else '[rust.std]'
    if not _CRATE.fullmatch(name):
        return None
    known = {k.replace('-', '_') for k in (*decl.external, *decl.crates)}
    return None if name.replace('-', '_') in known else '[rust.external] or [rust.crates]'


def problems(decl: Declared) -> list[str]:
    """Every cited name no row grants, and every native crate that is no crate row, naming the citing row."""
    tops = frozenset(key.split('.')[0] for key in decl.packages)
    out: list[str] = []
    tables = (
        ('python.packages', decl.packages, _python),
        ('python.stdlib', decl.stdlib, _python),
        ('rust.external', decl.external, _rust),
        ('rust.std', decl.std, _rust),
    )
    for table, grants, judge in tables:
        for key, grant in grants.items():
            out += [
                f'dependencies.toml [{table}] {key} cites {name} in its reason, which no {missing} row grants'
                for name in cited(grant.reason, tops)
                if (missing := judge(decl, name))
            ]
    if decl.crates:
        out += [
            f'dependencies.toml [python.native] {crate} names a crate no [rust.crates] row declares'
            for crate in decl.native
            if crate not in decl.crates
        ]
    return out
