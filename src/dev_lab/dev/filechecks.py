"""The family's per-file commit checks -- standard library only, and they REPORT, never rewrite.

``python -m dev_lab.dev.filechecks <check|all> [--skip CHECK]... [--exclude CHECK=REGEX]... [--max-kb N]
<path>...`` -- ONE row of the hook base (``dev_lab/dev/githooks/base.toml``) runs ``all``: the paths are handed
over once and each file is read once, whatever the number of checks. Each finding prints as
``[<check>] <path>[:<line>]: <what>``; the exit is 1 when any check found one.

EACH CHECK STAYS ITS OWN, BY NAME. A check knows which paths it judges (:data:`CHECKS`: ``ast`` reads Python,
``json`` JSON); a repo skips one (``--skip``) or narrows one (``--exclude CHECK=REGEX``, re.search over the
repo-relative POSIX path) by restating the base row's ``run`` in its own ``[[tool.dev_lab.hooks.pre-commit]]``
row of the same id; a single name still runs that one check alone.

WHY THEY NEVER REWRITE. A fixer that edits a staged file changes the thing under review to fit the
tool, and has twice destroyed content whose bytes were the point (a TSV whose trailing tab is a
column; a published deck). A check names the line; the person fixes it.

A binary file (a NUL byte in its first 8 KiB) is skipped by every text check.
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import shutil
import sys
import tomllib
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Final, NamedTuple

import lab_commons.launch as _door
from lab_commons.log import emit

__all__ = ['ALL', 'CHECKS', 'Check', 'main']

#: pre-commit-hooks' own default for the large-file check, kept so a repo's measured threshold holds.
DEFAULT_MAX_KB: Final = 500

_GIT: Final = shutil.which('git') or 'git'
_SNIFF: Final = 8192
_DEBUG_MODULES: Final = frozenset({'pdb', 'ipdb', 'pudb', 'pdbpp', 'wdb', 'rpdb', 'pydevd', 'q'})

Finding = str
#: One file's findings: its path, its bytes (read once for every check), the parsed options.
Judge = Callable[[Path, bytes, argparse.Namespace], list[Finding]]

#: The selector that runs every check.
ALL: Final = 'all'


class Check(NamedTuple):
    """One check: the paths it judges, and how."""

    #: re.search over the POSIX path; ``None`` judges every path.
    files: str | None
    #: ``None`` for a property of the path SET rather than of one file (``case-conflict``).
    judge: Judge | None


def _text(data: bytes) -> bytes | None:
    return None if b'\0' in data[:_SNIFF] else data


def _large(path: Path, data: bytes, args: argparse.Namespace) -> list[Finding]:
    size_kb = len(data) / 1024
    return [f'{path}: {size_kb:.0f} KB exceeds {args.max_kb} KB'] if size_kb > args.max_kb else []


def _ast(path: Path, data: bytes, _args: argparse.Namespace) -> list[Finding]:
    try:
        ast.parse(data, filename=str(path))
    except SyntaxError as exc:
        return [f'{path}:{exc.lineno}: does not parse as Python ({exc.msg})']
    return []


def _json(path: Path, data: bytes, _args: argparse.Namespace) -> list[Finding]:
    try:
        json.loads(data.decode('utf-8'))
    except (ValueError, UnicodeDecodeError) as exc:
        return [f'{path}: not valid JSON ({exc})']
    return []


def _toml(path: Path, data: bytes, _args: argparse.Namespace) -> list[Finding]:
    try:
        tomllib.loads(data.decode('utf-8'))
    except (tomllib.TOMLDecodeError, UnicodeDecodeError) as exc:
        return [f'{path}: not valid TOML ({exc})']
    return []


def _merge_conflict(path: Path, raw: bytes, _args: argparse.Namespace) -> list[Finding]:
    data = _text(raw)
    if data is None:
        return []
    return [
        f'{path}:{number}: a merge conflict marker'
        for number, line in enumerate(data.splitlines(), 1)
        if line.startswith((b'<<<<<<< ', b'>>>>>>> ')) or line.rstrip(b'\r') == b'<<<<<<<'
    ]


def _debug(path: Path, data: bytes, _args: argparse.Namespace) -> list[Finding]:
    try:
        tree = ast.parse(data, filename=str(path))
    except SyntaxError:
        return []  # the ast check's finding, not this one's
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


def _end_of_file(path: Path, raw: bytes, _args: argparse.Namespace) -> list[Finding]:
    data = _text(raw)
    if not data:
        return []
    if not data.endswith(b'\n'):
        return [f'{path}: no newline at the end of the file']
    if data.endswith((b'\n\n', b'\n\r\n')):
        return [f'{path}: blank line(s) at the end of the file']
    return []


def _mixed(path: Path, raw: bytes, _args: argparse.Namespace) -> list[Finding]:
    data = _text(raw)
    if data is None:
        return []
    crlf = data.count(b'\r\n')
    lf = data.count(b'\n') - crlf
    return [f'{path}: mixes CRLF ({crlf}) and LF ({lf}) line endings'] if crlf and lf else []


def _trailing(path: Path, raw: bytes, _args: argparse.Namespace) -> list[Finding]:
    data = _text(raw)
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


_PY: Final = r'\.pyi?$'

#: Every check by name, in the order its findings print.
CHECKS: Final[dict[str, Check]] = {
    'large-files': Check(None, _large),
    'ast': Check(_PY, _ast),
    'case-conflict': Check(None, None),
    'json': Check(r'\.json$', _json),
    'merge-conflict': Check(None, _merge_conflict),
    'toml': Check(r'\.toml$', _toml),
    'debug-statements': Check(_PY, _debug),
    'end-of-file': Check(None, _end_of_file),
    'mixed-line-ending': Check(None, _mixed),
    'trailing-whitespace': Check(None, _trailing),
}


def _name(text: str) -> str:
    if text not in CHECKS:
        msg = f'unknown check {text!r}; the checks are {sorted(CHECKS)}'
        raise argparse.ArgumentTypeError(msg)
    return text


def _exclusion(text: str) -> tuple[str, re.Pattern[str]]:
    name, sep, pattern = text.partition('=')
    if not sep:
        msg = f'{text!r} is not CHECK=REGEX'
        raise argparse.ArgumentTypeError(msg)
    try:
        return _name(name), re.compile(pattern)
    except re.error as exc:
        msg = f'{text!r}: an invalid regex ({exc})'
        raise argparse.ArgumentTypeError(msg) from exc


def _parse(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog='python -m dev_lab.dev.filechecks', description=__doc__.splitlines()[0])
    parser.add_argument('check', choices=[ALL, *sorted(CHECKS)], help=f'one check, or {ALL!r} for every one')
    parser.add_argument('paths', nargs='*', type=Path)
    parser.add_argument('--skip', action='append', default=[], type=_name, metavar='CHECK', help='not this check')
    parser.add_argument(
        '--exclude', action='append', default=[], type=_exclusion, metavar='CHECK=REGEX', help='not these paths'
    )
    parser.add_argument('--max-kb', type=int, default=DEFAULT_MAX_KB, help='large-files: the threshold')
    return parser.parse_args(argv)


def _findings(args: argparse.Namespace) -> list[str]:
    """Every chosen check over the paths it selects, each file read once, as ``[<check>] <finding>`` lines."""
    chosen = [name for name in CHECKS if args.check in (ALL, name) and name not in args.skip]
    excluded: dict[str, list[re.Pattern[str]]] = {}
    for name, pattern in args.exclude:
        excluded.setdefault(name, []).append(pattern)
    present = [path for path in args.paths if path.is_file()]

    def selected(name: str) -> list[Path]:
        files = CHECKS[name].files
        return [
            path
            for path in present
            if (files is None or re.search(files, path.as_posix()))
            and not any(pattern.search(path.as_posix()) for pattern in excluded.get(name, ()))
        ]

    read: dict[Path, bytes] = {}
    out: list[str] = []
    for name in chosen:
        judge, paths = CHECKS[name].judge, selected(name)
        if judge is None:
            found = _case_conflicts(paths) if paths else []
        else:
            found = [f for path in paths for f in judge(path, read.setdefault(path, path.read_bytes()), args)]
        out += [f'[{name}] {finding}' for finding in found]
    return out


def main(argv: Sequence[str] | None = None) -> int:
    """``0`` no finding, ``1`` at least one -- each printed as ``[<check>] <path>[:<line>]: <what>``."""
    findings = _findings(_parse(sys.argv[1:] if argv is None else argv))
    for finding in findings:
        emit(finding)
    return 1 if findings else 0


if __name__ == '__main__':
    raise SystemExit(main())
