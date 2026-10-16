"""The family's per-file commit checks -- standard library only, and they REPORT, never rewrite.

``python -m lab_commons.dev.filechecks <check> [--max-kb N] <path>...`` -- one check per invocation,
wired as rows of the hook base (``lab_commons/dev/githooks/base.toml``). Each prints one line per
finding (``<path>:<line>: <what>``) and exits 1 when it found any.

WHY THEY NEVER REWRITE. A fixer that edits a staged file changes the thing under review to fit the
tool, and has twice destroyed content whose bytes were the point (a TSV whose trailing tab is a
column; a published deck). A check names the line; the person fixes it.

A binary file (a NUL byte in its first 8 KiB) is skipped by every text check.
"""

from __future__ import annotations

import argparse
import ast
import json
import shutil
import sys
import tomllib
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Final

import lab_commons.launch as _door
from lab_commons.log import emit

__all__ = ['CHECKS', 'main']

#: pre-commit-hooks' own default for the large-file check, kept so a repo's measured threshold holds.
DEFAULT_MAX_KB: Final = 500

_GIT: Final = shutil.which('git') or 'git'
_SNIFF: Final = 8192
_DEBUG_MODULES: Final = frozenset({'pdb', 'ipdb', 'pudb', 'pdbpp', 'wdb', 'rpdb', 'pydevd', 'q'})

Finding = str
Check = Callable[[Path, argparse.Namespace], list[Finding]]


def _text(path: Path) -> bytes | None:
    data = path.read_bytes()
    return None if b'\0' in data[:_SNIFF] else data


def _large(path: Path, args: argparse.Namespace) -> list[Finding]:
    size_kb = path.stat().st_size / 1024
    return [f'{path}: {size_kb:.0f} KB exceeds {args.max_kb} KB'] if size_kb > args.max_kb else []


def _ast(path: Path, _args: argparse.Namespace) -> list[Finding]:
    try:
        ast.parse(path.read_bytes(), filename=str(path))
    except SyntaxError as exc:
        return [f'{path}:{exc.lineno}: does not parse as Python ({exc.msg})']
    return []


def _json(path: Path, _args: argparse.Namespace) -> list[Finding]:
    try:
        json.loads(path.read_text(encoding='utf-8'))
    except (ValueError, UnicodeDecodeError) as exc:
        return [f'{path}: not valid JSON ({exc})']
    return []


def _toml(path: Path, _args: argparse.Namespace) -> list[Finding]:
    try:
        tomllib.loads(path.read_text(encoding='utf-8'))
    except (tomllib.TOMLDecodeError, UnicodeDecodeError) as exc:
        return [f'{path}: not valid TOML ({exc})']
    return []


def _merge_conflict(path: Path, _args: argparse.Namespace) -> list[Finding]:
    data = _text(path)
    if data is None:
        return []
    return [
        f'{path}:{number}: a merge conflict marker'
        for number, line in enumerate(data.splitlines(), 1)
        if line.startswith((b'<<<<<<< ', b'>>>>>>> ')) or line.rstrip(b'\r') == b'<<<<<<<'
    ]


def _debug(path: Path, _args: argparse.Namespace) -> list[Finding]:
    try:
        tree = ast.parse(path.read_bytes(), filename=str(path))
    except SyntaxError:
        return []  # check-ast's finding, not this one's
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out += [
                f'{path}:{node.lineno}: imports {a.name}' for a in node.names if a.name.split('.')[0] in _DEBUG_MODULES
            ]
        elif isinstance(node, ast.ImportFrom) and (node.module or '').split('.')[0] in _DEBUG_MODULES:
            out.append(f'{path}:{node.lineno}: imports from {node.module}')
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == 'breakpoint':
            out.append(f'{path}:{node.lineno}: calls breakpoint()')
    return out


def _end_of_file(path: Path, _args: argparse.Namespace) -> list[Finding]:
    data = _text(path)
    if not data:
        return []
    if not data.endswith(b'\n'):
        return [f'{path}: no newline at the end of the file']
    if data.endswith((b'\n\n', b'\n\r\n')):
        return [f'{path}: blank line(s) at the end of the file']
    return []


def _mixed(path: Path, _args: argparse.Namespace) -> list[Finding]:
    data = _text(path)
    if data is None:
        return []
    crlf = data.count(b'\r\n')
    lf = data.count(b'\n') - crlf
    return [f'{path}: mixes CRLF ({crlf}) and LF ({lf}) line endings'] if crlf and lf else []


def _trailing(path: Path, _args: argparse.Namespace) -> list[Finding]:
    data = _text(path)
    if data is None:
        return []
    return [
        f'{path}:{number}: trailing whitespace'
        for number, line in enumerate(data.splitlines(), 1)
        if line != line.rstrip(b' \t')
    ]


def _case_conflicts(paths: Sequence[Path]) -> list[Finding]:
    tracked = _door.run(
        [_GIT, 'ls-files', '-z'], capture_output=True, text=True, encoding='utf-8', check=True, timeout=120
    ).stdout.split('\0')
    seen: dict[str, set[str]] = {}
    for name in {*filter(None, tracked), *(p.as_posix() for p in paths)}:
        parts = name.split('/')
        for depth in range(1, len(parts) + 1):
            prefix = '/'.join(parts[:depth])
            seen.setdefault(prefix.casefold(), set()).add(prefix)
    asked = {p.as_posix().casefold() for p in paths}
    return [
        f'{" vs ".join(sorted(names))}: names differ only in case'
        for key, names in sorted(seen.items())
        if len(names) > 1 and any(a == key or a.startswith(f'{key}/') for a in asked)
    ]


CHECKS: Final[dict[str, Check | None]] = {
    'large-files': _large,
    'ast': _ast,
    'case-conflict': None,  # a property of the path SET, not of one file
    'json': _json,
    'merge-conflict': _merge_conflict,
    'toml': _toml,
    'debug-statements': _debug,
    'end-of-file': _end_of_file,
    'mixed-line-ending': _mixed,
    'trailing-whitespace': _trailing,
}


def main(argv: Sequence[str] | None = None) -> int:
    """``0`` no finding, ``1`` at least one -- each printed as ``<path>[:<line>]: <what>``."""
    parser = argparse.ArgumentParser(prog='python -m lab_commons.dev.filechecks', description=__doc__.splitlines()[0])
    parser.add_argument('check', choices=sorted(CHECKS))
    parser.add_argument('paths', nargs='*', type=Path)
    parser.add_argument('--max-kb', type=int, default=DEFAULT_MAX_KB, help='large-files: the threshold')
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)
    present = [path for path in args.paths if path.is_file()]
    check = CHECKS[args.check]
    findings = _case_conflicts(present) if check is None else [f for path in present for f in check(path, args)]
    for finding in findings:
        emit(f'[{args.check}] {finding}')
    return 1 if findings else 0


if __name__ == '__main__':
    raise SystemExit(main())
