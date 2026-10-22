"""MERGE owned keys into the machine file's TEXT: every other table, key and comment is kept byte for byte.

The machine file (:mod:`lab_commons.config`) is hand-written and commented, so a deploy never re-renders
it: :func:`merged` sets each owned ``key = value`` inside its ``[table]`` -- replacing the line only
when its value differs, appending the key or the table when absent -- and refuses a result that does
not parse or does not read back the values asked for.
"""

from __future__ import annotations

import difflib
import re
import tomllib
from collections.abc import Mapping
from typing import Final

__all__ = ['diff', 'merged']

#: A ``[table]`` or ``[[array]]`` header line.
_HEADER: Final = re.compile(r'^\s*(\[\[?)\s*([^\]]+?)\s*\]\]?\s*(#.*)?$')

Value = str | int | float | list[str]


def _render(value: Value) -> str:
    if isinstance(value, str):
        return '"' + value.replace('\\', '\\\\').replace('"', '\\"') + '"'
    if isinstance(value, list):
        return '[' + ', '.join(_render(v) for v in value) + ']'
    return repr(value)


def _same(line: str, key: str, value: Value) -> bool:
    try:
        return tomllib.loads(line).get(key) == value
    except tomllib.TOMLDecodeError:
        return False


def _set(lines: list[str], table: str, values: Mapping[str, Value]) -> None:
    starts = [i for i, line in enumerate(lines) if (m := _HEADER.match(line)) and m[1] == '[' and m[2] == table]
    if not starts:
        if lines and lines[-1].strip():
            lines.append('')
        lines.extend([f'[{table}]', *(f'{key} = {_render(value)}' for key, value in values.items())])
        return
    start = starts[0]
    end = next((j for j in range(start + 1, len(lines)) if _HEADER.match(lines[j])), len(lines))
    for key, value in values.items():
        row = f'{key} = {_render(value)}'
        pattern = re.compile(rf'^\s*{re.escape(key)}\s*=')
        hit = next((j for j in range(start + 1, end) if pattern.match(lines[j])), None)
        if hit is None:
            last = max((j for j in range(start, end) if lines[j].strip()), default=start)
            lines.insert(last + 1, row)
            end += 1
        elif not _same(lines[hit], key, value):
            lines[hit] = row


def _read(data: Mapping[str, object], table: str) -> object:
    for part in table.split('.'):
        data = data.get(part, {}) if isinstance(data, Mapping) else {}
    return data


def merged(text: str, tables: Mapping[str, Mapping[str, Value]]) -> str:
    """*text* with every ``tables[name][key] = value`` set; a result that does not read them back is refused."""
    lines = text.splitlines()
    for table, values in tables.items():
        _set(lines, table, values)
    out = '\n'.join(lines) + '\n' if lines else ''
    try:
        parsed = tomllib.loads(out)
    except tomllib.TOMLDecodeError as broken:
        msg = f'merging {", ".join(f"[{t}]" for t in tables)} would break the file ({broken}); edit it by hand'
        raise ValueError(msg) from None
    for table, values in tables.items():
        found = _read(parsed, table)
        if not isinstance(found, Mapping) or any(found.get(k) != v for k, v in values.items()):
            msg = f'[{table}] does not read back as {dict(values)} after the merge; edit it by hand'
            raise ValueError(msg)
    return out


def diff(before: str, after: str, path: str) -> str:
    """The unified diff of *before* -> *after*, labelled *path*; ``''`` when they are equal."""
    lines = difflib.unified_diff(before.splitlines(), after.splitlines(), path, path, lineterm='')
    return '\n'.join(lines)
