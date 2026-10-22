"""A SETTING LAB-COMMONS OWNS IS DEFINED ONCE -- no consumer re-declares it in its schema, its tables or its defaults.

THE DEFECT, MEASURED 2026-10-13. ``text_editor_command`` and the four logging settings were fields of
two consumers' own config schemas, each with the SAME default literal, and the machine file carried
``text_editor_command = "start"`` once per package. One fact about the user, written three times.
:mod:`lab_commons.config` now owns them in its ``[user]`` table (:func:`lab_commons.config.user`, one
default each) and refuses a machine-file package table repeating one. This module is the SOURCE-side
twin every consumer runs over its own tree: a re-declaration is convicted before it ships.

WHAT CONVICTS, in a consumer's ``.py`` and ``.toml`` files:

* a CLASS-LEVEL field named a :data:`~lab_commons.config.SHARED_KEYS` key -- a schema re-declaring it;
* a dict-literal or TOML key named one -- a table carrying it;
* a string literal equal to one of :class:`~lab_commons.config.User`'s distinctive defaults -- the
  package's own default for it, however it is spelled around.

WHAT DOES NOT: reading the setting (``user().log_level``), passing it on (``file_format=...``), and
prose. The level default ``'INFO'`` is not matched as a literal: it is a level NAME every logger
spells, so matching it would convict every ``log('...', 'INFO')`` and the guard would be switched off.

THE CONTROL TAKES NO ARGUMENT (:func:`assert_a_planted_redefinition_is_convicted`), and the scan
carries a FLOOR on files read, because an empty walk reads exactly like a clean tree.
"""

from __future__ import annotations

import ast
import tomllib
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Final

from lab_commons.config import SHARED_KEYS, USER_TABLE, User

from dev_lab.dev.floors import assert_floor

__all__ = [
    'DEFAULT_LITERALS',
    'Redefinition',
    'assert_a_planted_redefinition_is_convicted',
    'assert_no_package_redefines_a_shared_setting',
    'redefinitions_in',
]

#: Each distinctive default of :class:`User`, mapped to its key. ``log_level`` is left out: see the module docstring.
DEFAULT_LITERALS: Final = {value: key for key, value in asdict(User()).items() if key != 'log_level'}

_REMEDY: Final = (
    f'delete it here: lab-commons owns it, with one default, in the [{USER_TABLE}] table of the machine '
    f'file -- read it through lab_commons.config.user().<key>, and put a machine value under [{USER_TABLE}]'
)


@dataclass(frozen=True)
class Redefinition:
    """One place a consumer re-declares a shared setting."""

    path: str
    line: int
    what: str

    def __str__(self) -> str:
        """``path:line: what``, the shape an editor jumps to."""
        return f'{self.path}:{self.line}: {self.what}'


def _python(text: str, path: str) -> list[Redefinition]:
    found: list[Redefinition] = []
    for node in ast.walk(ast.parse(text)):
        if isinstance(node, ast.ClassDef):
            for stmt in node.body:
                targets = (
                    stmt.targets
                    if isinstance(stmt, ast.Assign)
                    else [stmt.target]
                    if isinstance(stmt, ast.AnnAssign)
                    else []
                )
                found += [
                    Redefinition(path, stmt.lineno, f'class {node.name} declares the shared field {t.id!r}')
                    for t in targets
                    if isinstance(t, ast.Name) and t.id in SHARED_KEYS
                ]
        elif isinstance(node, ast.Dict):
            found += [
                Redefinition(path, key.lineno, f'a table carries the shared key {key.value!r}')
                for key in node.keys
                if isinstance(key, ast.Constant) and key.value in SHARED_KEYS
            ]
        elif isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value in DEFAULT_LITERALS:
            key = DEFAULT_LITERALS[node.value]
            found.append(Redefinition(path, node.lineno, f'its own default for the shared {key!r}'))
    return found


def _toml(value: object, path: str, where: str) -> list[Redefinition]:
    if isinstance(value, list):
        return [hit for item in value for hit in _toml(item, path, where)]
    if not isinstance(value, dict):
        return []
    hits = [Redefinition(path, 0, f'[{where}] carries the shared key {key!r}') for key in value if key in SHARED_KEYS]
    return hits + [hit for key, inner in value.items() for hit in _toml(inner, path, f'{where}.{key}'.strip('.'))]


def redefinitions_in(text: str, path: str) -> list[Redefinition]:
    """Every re-declaration in one file's *text*; *path* picks the reader (``.py`` or ``.toml``)."""
    if path.endswith('.toml'):
        return _toml(tomllib.loads(text), path, '')
    return _python(text, path)


def assert_no_package_redefines_a_shared_setting(root: Path, *, floor: int, sanctioned: Iterable[str] = ()) -> None:
    """Refuse every re-declaration under *root*, naming the remedy.

    Args:
        root: the consumer's tree to scan (its ``src``).
        floor: fewest files the walk must read; an empty walk reads like a clean tree.
        sanctioned: ``root``-relative POSIX paths allowed to declare them -- the owner, and nothing else.

    """
    allowed = set(sanctioned)
    files = sorted(p for pattern in ('*.py', '*.toml') for p in root.rglob(pattern))
    assert_floor(len(files), floor=floor, what=f'files read under {root}')
    found = [
        hit
        for p in files
        if (rel := p.relative_to(root).as_posix()) not in allowed
        for hit in redefinitions_in(p.read_text(encoding='utf-8'), rel)
    ]
    if found:
        msg = f'{len(found)} re-declared shared setting(s); {_REMEDY}:\n' + '\n'.join(map(str, found))
        raise AssertionError(msg)


def assert_a_planted_redefinition_is_convicted() -> None:
    """PLANTED CONTROL: each convicting shape convicts through the real reader, and a reading does not."""
    planted = {
        'class Utils:\n    text_editor_command: str = "vim"\n': 'shared field',
        'TABLE = {"log_level": "INFO"}\n': 'shared key',
        'DATE = "%m/%d/%Y %H:%M:%S"\n': 'its own default',
        '[pkg.utils]\nlog_console_format = "x"\n': 'shared key',
    }
    for text, what in planted.items():
        path = 'planted.toml' if text.startswith('[') else 'planted.py'
        hits = redefinitions_in(text, path)
        if len(hits) != 1 or what not in hits[0].what:
            msg = f'the reader missed a planted {what}: {text!r} -> {hits}'
            raise AssertionError(msg)
    reading = 'level = user().log_level\nlog("x", "INFO")\nadd(file_format=user().log_file_format)\n'
    if hits := redefinitions_in(reading, 'reading.py'):
        msg = f'the reader convicts a READ, which only switches it off: {hits}'
        raise AssertionError(msg)
