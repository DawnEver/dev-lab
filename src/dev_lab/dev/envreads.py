"""ENV-IS-READ-ONCE: a repo reads the process environment in its declared entry modules and nowhere else.

User-approved family policy (2026-11-25, a consumer's v1-migration D67/D68). An environment variable is one of
three classes, and only one of them may be read at all:

* A -- a value that changes a result or a behavior (a research-mode switch, a ``*_HOME``, ``RAYON_NUM_THREADS``,
  ``MPLBACKEND``, ``PYTHONOPTIMIZE``) is removed and becomes explicit configuration;
* B -- a fact an external system offers only as an environment variable (a scheduler allocation, ``PATH``, the
  user name, an OS-defined directory, the agent harness's context) is read at ONE family entry and turned into a
  typed record at once. It never changes a numeric result; one that could enters the producer identity;
* C -- a test switch becomes a pytest option or test configuration.

THE DECLARATION, in the repo's ``pyproject.toml`` (an absent table is the empty one -- nothing may read)::

    [tool.dev_lab.env]
    entry = ["src/<pkg>/<entry>.py"]   # the B-class entry module(s), repo-relative files
    pending = ["src/<pkg>/old.py"]     # reads on record, not yet migrated; the list only SHRINKS
    strict = true                      # opt-in: tests are judged too (otherwise a test file is exempt)

TWO JUDGMENTS. The always-on family check (:func:`check`) reads the tracked tree of every family checkout holding
a ``src/``, ``rust/`` or ``scripts/`` tree (:func:`applies`), under a floor, and refuses a read outside the entry
and the ledger, a ledger path with no read left (stale: the migrated file leaves the list in the same change), an
entry that is not a file, and a path declared both ways. The
pre-push row (:func:`range_problems`) refuses a ``pending`` entry the pushed head adds since its merge-base with
``origin/<integration>``: the list is the census at adoption, and from there it only shrinks.
``python -m dev_lab.dev.envreads census`` prints the list as it must read now, to paste at adoption.

WHAT IT SEES, read off the source (nothing is imported or run): in Python, ``environ``, ``environb``, ``getenv``,
``getenvb``, ``putenv`` and ``unsetenv`` reached through a name bound to ``os`` (``import os``, ``import os as
_os``) or imported from it (``from os import environ``); in Rust, a runtime ``env::var``/``var_os``/``vars``/
``vars_os``/``set_var``/``remove_var`` on a line that is not a ``//`` comment. WHAT IT CANNOT SEE: an implicit
read inside a library (``Path.home()``, ``shutil.which`` reading ``PATH``), ``os`` reached under a name assigned
at run time, compile-time ``env!``, and a Rust ``use std::env::var`` called bare.
"""

from __future__ import annotations

import ast
import re
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Final

import lab_commons.launch as _door
from lab_commons.log import emit

from dev_lab.dev.family import declared_table
from dev_lab.dev.lanepolicy import policy_at
from dev_lab.dev.rules import tracked_files

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

__all__ = [
    'DOOR',
    'RULE_ID',
    'SOURCE_TREES',
    'USAGE',
    'EnvPolicy',
    'applies',
    'census',
    'check',
    'declared_env',
    'main',
    'problems',
    'python_reads',
    'range_problems',
    'rust_reads',
]

RULE_ID: Final = 'ENV-IS-READ-ONCE'
USAGE: Final = 2
_TABLE: Final = 'env'
_KEYS: Final = frozenset({'entry', 'pending', 'strict'})
DOOR: Final = (
    'a result- or behavior-changing value (A) becomes explicit configuration; a fact only the environment '
    'offers (B) is read in a declared [tool.dev_lab.env] entry module and passed on as a typed record; a test '
    'switch (C) becomes a pytest option'
)
_DETAILS: Final = 'details: docs-src/dev/refusals.md#env-is-read-once (dev-lab)'
_OS_NAMES: Final = frozenset({'environ', 'environb', 'getenv', 'getenvb', 'putenv', 'unsetenv'})
_RUST_READ: Final = re.compile(r'\benv::(?:var|var_os|vars|vars_os|set_var|remove_var)\s*\(')
_SUFFIXES: Final = ('.py', '.rs')
_TEST_DIRS: Final = frozenset({'tests', 'benches'})
#: Where a checkout's population lives: a family checkout with none of these has nothing for the check to read.
SOURCE_TREES: Final = ('src', 'rust', 'scripts')
_ZERO: Final = '0' * 40
_REF_LINE_FIELDS: Final = 4


@dataclass(frozen=True, slots=True)
class EnvPolicy:
    """The declaration: the entry modules, the pending ledger, and whether tests are judged."""

    entry: tuple[str, ...] = ()
    pending: tuple[str, ...] = ()
    strict: bool = False


def _paths(table: dict[str, object], key: str) -> tuple[str, ...]:
    value = table.get(key, [])
    if not isinstance(value, list) or not all(isinstance(p, str) and p.strip('/') for p in value):
        msg = f'[tool.dev_lab.{_TABLE}] {key} must be a list of repo-relative paths, not {value!r}'
        raise ValueError(msg)
    return tuple(p.strip('/') for p in value)


def _policy(data: dict[str, object]) -> EnvPolicy:
    table = declared_table(data, _TABLE, {})
    if unknown := sorted(set(table) - _KEYS):
        msg = f'[tool.dev_lab.{_TABLE}] knows {sorted(_KEYS)}, not {unknown}'
        raise ValueError(msg)
    strict = table.get('strict', False)
    if type(strict) is not bool:  # 1 is not true: TOML spells a flag as a boolean
        msg = f'[tool.dev_lab.{_TABLE}] strict must be true or false, not {strict!r}'
        raise ValueError(msg)
    return EnvPolicy(_paths(table, 'entry'), _paths(table, 'pending'), strict=strict)


def declared_env(root: Path) -> EnvPolicy:
    """*root*'s ``[tool.dev_lab.env]``; no manifest or no table is the empty policy. A malformed one raises."""
    try:
        text = (root / 'pyproject.toml').read_text(encoding='utf-8')
    except OSError:
        return EnvPolicy()
    return _policy(tomllib.loads(text))


def _os_bindings(tree: ast.AST) -> tuple[set[str], set[str]]:
    """Names bound to the ``os`` module, and names imported from it that read the environment."""
    modules: set[str] = set()
    members: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules |= {alias.asname or alias.name for alias in node.names if alias.name == 'os'}
        elif isinstance(node, ast.ImportFrom) and node.module == 'os' and not node.level:
            members |= {alias.asname or alias.name for alias in node.names if alias.name in _OS_NAMES}
    return modules, members


def python_reads(source: str) -> tuple[int, ...]:
    """The lines of *source* reaching the environment through ``os`` (see the module docstring for the shapes)."""
    tree = ast.parse(source)
    modules, members = _os_bindings(tree)
    lines = {
        node.lineno
        for node in ast.walk(tree)
        if (
            isinstance(node, ast.Attribute)
            and node.attr in _OS_NAMES
            and isinstance(node.value, ast.Name)
            and node.value.id in modules
        )
        or (isinstance(node, ast.Name) and node.id in members)
    }
    return tuple(sorted(lines))


def rust_reads(source: str) -> tuple[int, ...]:
    """The lines of *source* calling a runtime ``std::env`` reader or writer, ``//`` comment lines skipped."""
    return tuple(
        number
        for number, line in enumerate(source.splitlines(), start=1)
        if not line.lstrip().startswith('//') and _RUST_READ.search(line)
    )


def _is_test(rel: str) -> bool:
    """A test file: ``conftest.py``, ``test_*``, ``*_test``, or anything under a ``tests/`` or ``benches/``."""
    path = PurePosixPath(rel)
    named = path.name == 'conftest.py' or path.name.startswith('test_') or path.stem.endswith('_test')
    return named or bool(_TEST_DIRS & set(path.parts[:-1]))


def _reads(root: Path, rel: str) -> tuple[int, ...]:
    source = (root / rel).read_text(encoding='utf-8', errors='replace')
    if rel.endswith('.py'):
        try:
            return python_reads(source)
        except SyntaxError:
            return ()
    return rust_reads(source)


def _judged(policy: EnvPolicy, files: Iterable[str]) -> list[str]:
    return sorted(rel for rel in set(files) if rel.endswith(_SUFFIXES) and (policy.strict or not _is_test(rel)))


def _readers(root: Path, policy: EnvPolicy, files: Iterable[str]) -> dict[str, tuple[int, ...]]:
    found = {rel: _reads(root, rel) for rel in _judged(policy, files) if (root / rel).is_file()}
    return {rel: lines for rel, lines in found.items() if lines}


def census(root: Path, policy: EnvPolicy, files: Iterable[str]) -> tuple[str, ...]:
    """Every judged path that reads, outside the entry: the ``pending`` list as it must read now."""
    return tuple(rel for rel in _readers(root, policy, files) if rel not in policy.entry)


def problems(root: Path, policy: EnvPolicy, files: Iterable[str]) -> list[str]:
    """Every refusal over *files* (repo-relative POSIX paths) under *root*, judged against *policy*."""
    readers = _readers(root, policy, files)
    pending = set(policy.pending)
    found = [
        f'{RULE_ID}: {rel}:{line}: reads the environment outside the declared entry and the pending ledger'
        for rel, lines in readers.items()
        if rel not in policy.entry and rel not in pending
        for line in lines
    ]
    found += [
        f'{RULE_ID}: {rel}: pending in [tool.dev_lab.{_TABLE}] and reads nothing now -- stale, delete it'
        for rel in sorted(pending - set(readers))
    ]
    found += [
        f'{RULE_ID}: {rel}: a declared [tool.dev_lab.{_TABLE}] entry that is not a file'
        for rel in policy.entry
        if not (root / rel).is_file()
    ]
    found += [
        f'{RULE_ID}: {rel}: declared both entry and pending -- an entry reads by design'
        for rel in sorted(pending & set(policy.entry))
    ]
    return found


def applies(root: Path) -> bool:
    """Whether *root* holds a :data:`SOURCE_TREES` directory: where the always-on check has a population to read."""
    return any((root / tree).is_dir() for tree in SOURCE_TREES)


def check(root: Path) -> None:
    """The always-on family check: raise naming every refusal in *root*'s tracked tree, under a floor."""
    policy = declared_env(root)
    files = tracked_files(root)
    if not _judged(policy, files):
        msg = f'{RULE_ID}: the tracked .py/.rs population under {root} read EMPTY, so a clean result means nothing'
        raise AssertionError(msg)
    if found := problems(root, policy, files):
        raise AssertionError('\n'.join([*found, f'door: {DOOR}', _DETAILS]))


def _git(root: Path, *args: str) -> str:
    done = _door.run(['git', '-C', str(root), *args], capture_output=True, check=False, timeout=120)
    if done.returncode != 0:
        msg = f'git {" ".join(args)} failed: {done.stderr.decode("utf-8", "replace").strip()}'
        raise RuntimeError(msg)
    return done.stdout.decode('utf-8', 'replace')


def _pending_at(root: Path, rev: str) -> frozenset[str]:
    try:
        text = _git(root, 'show', f'{rev}:pyproject.toml')
    except RuntimeError:
        return frozenset()
    return frozenset(_policy(tomllib.loads(text)).pending)


def range_problems(root: Path, base: str, head: str) -> list[str]:
    """A ``pending`` path *head* adds since its merge-base with *base*. A base with no table admits the census."""
    since = _git(root, 'merge-base', base, head).strip()
    before = _pending_at(root, since)
    if not before:
        return []
    return [
        f'{RULE_ID}: {rel}: added to [tool.dev_lab.{_TABLE}] pending since {since[:12]} -- the list only shrinks; '
        f'{DOOR}\n{_DETAILS}'
        for rel in sorted(_pending_at(root, head) - before)
    ]


def _pushed(root: Path, ref_lines: str) -> list[str]:
    base = f'origin/{policy_at(root, "HEAD").integration}'
    out: list[str] = []
    for line in ref_lines.splitlines():
        parts = line.split()
        if len(parts) == _REF_LINE_FIELDS and parts[1] != _ZERO:
            out.extend(range_problems(root, base, parts[1]))
    return out


def main(argv: Sequence[str] | None = None, *, cwd: Path | None = None) -> int:
    """``check`` the tree, print the ``census``, judge a ``range <base> <head>``; no mode: the pre-push row."""
    args = list(sys.argv[1:] if argv is None else argv)
    root = Path(_git(cwd or Path.cwd(), 'rev-parse', '--show-toplevel').strip())
    try:
        policy = declared_env(root)
    except ValueError as exc:
        emit(f'{RULE_ID}: {exc}')
        return 1
    if args == ['census']:
        listed = ''.join(f'    "{rel}",\n' for rel in census(root, policy, tracked_files(root)))
        emit(f'[tool.dev_lab.{_TABLE}]\nentry = {list(policy.entry)!r}\npending = [\n{listed}]'.replace("'", '"'))
        return 0
    if args == ['check']:
        found = problems(root, policy, tracked_files(root))
    elif args[:1] == ['range'] and len(args) == len(('range', '<base>', '<head>')):
        found = range_problems(root, args[1], args[2])
    elif not args or (len(args) <= len(('<remote>', '<url>')) and not args[0].startswith('-')):
        found = _pushed(root, '' if sys.stdin.isatty() else sys.stdin.read())
    else:
        emit(f'{RULE_ID}: usage: python -m dev_lab.dev.envreads [check | census | range <base> <head>]')
        return USAGE
    for problem in found:
        emit(problem)
    return 1 if found else 0


if __name__ == '__main__':
    sys.exit(main())
