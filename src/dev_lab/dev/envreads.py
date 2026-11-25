"""ENV-IS-READ-ONCE: a repo reads the process environment in its declared entry modules and nowhere else.

User-approved family policy (2026-11-25, a consumer's v1-migration D67/D68). An environment variable is one of
three classes, and only one of them may be read at all:

* A -- a value that changes a result or a behavior (a research-mode switch, a ``*_HOME``, ``RAYON_NUM_THREADS``,
  ``MPLBACKEND``, ``PYTHONOPTIMIZE``) is removed and becomes explicit configuration;
* B -- a fact an external system offers only as an environment variable (a scheduler allocation, ``PATH``, the
  user name, an OS-defined directory, the agent harness's context) is read at ONE family entry and turned into a
  typed record at once. It never changes a numeric result; one that could enters the producer identity;
* C -- a test switch becomes a pytest option or a resource need (``pytest.mark.<resource>``, scheduled where the
  resource is present).

THE DECLARATION, in the repo's ``pyproject.toml`` (an absent table is the empty one -- nothing may read)::

    [tool.dev_lab.env]
    entry = ["src/<pkg>/<entry>.py"]   # the B-class entry module(s), repo-relative files
    pending = ["src/<pkg>/old.py"]     # reads on record, not yet migrated; the list only SHRINKS
    strict = true                      # opt-in: every test read is judged too (otherwise only its switches are)

A TEST SWITCH (class C) is refused in every mode: in a test file, a read of ONE variable by name (``environ[..]``,
``environ.get(..)``, ``getenv(..)``, ``.. in environ``) that decides whether a test runs -- a ``skipif``/``xfail``
condition, or the test of an ``if``/``while``/conditional expression whose branch calls ``skip``, ``skipif``,
``xfail`` or ``importorskip`` -- directly or through a name it is assigned to (:func:`python_switches`). Its door is
:data:`SWITCH_DOOR`. The ``pending`` ledger records one; an ``entry`` never launders one. Any other test read (an
OS-set temp directory, an environment handed to a child) is exempt outside ``strict`` and, under it, allowed only
where declared (``entry`` or ``pending``).

TWO JUDGMENTS. The always-on family check (:func:`check`) reads the tracked tree of every family checkout holding
a ``src/``, ``rust/`` or ``scripts/`` tree (:func:`applies`), under a floor, and refuses a read outside the entry
and the ledger, a test switch off the ledger, a ledger path with no read left (stale: the migrated file leaves the
list in the same change), an entry that is not a file, and a path declared both ways. The
pre-push row (:func:`range_problems`) refuses a ``pending`` entry the pushed head adds since its merge-base with
``origin/<integration>``: the list is the census at adoption, and from there it only shrinks.
``python -m dev_lab.dev.envreads census`` prints the list as it must read now, to paste at adoption.

WHAT IT SEES, read off the source (nothing is imported or run): in Python, ``environ``, ``environb``, ``getenv``,
``getenvb``, ``putenv`` and ``unsetenv`` reached through a name bound to ``os`` (``import os``, ``import os as
_os``) or imported from it (``from os import environ``); in Rust, a runtime ``env::var``/``var_os``/``vars``/
``vars_os``/``set_var``/``remove_var`` on a line that is not a ``//`` comment. WHAT IT CANNOT SEE: an implicit
read inside a library (``Path.home()``, ``shutil.which`` reading ``PATH``), ``os`` reached under a name assigned
at run time, compile-time ``env!``, and a Rust ``use std::env::var`` called bare. As a SWITCH it cannot see a
Rust test's switch (Rust is read by line), a test that returns early instead of skipping, a mode switch that
changes what a test does rather than whether it runs, nor a read inside a helper another file calls: each is still a
read, judged under ``strict``.
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
    'SWITCH_DOOR',
    'USAGE',
    'EnvPolicy',
    'applies',
    'census',
    'check',
    'declared_env',
    'main',
    'problems',
    'python_reads',
    'python_switches',
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
    'switch (C) becomes a pytest option or a resource need'
)
#: A test switch's door: what decides whether a test runs, instead of the environment.
SWITCH_DOOR: Final = (
    'declare a pytest option (pytest_addoption in conftest.py) or a resource need (a pytest.mark.<resource> the '
    'needs mechanism schedules where the resource is present) -- an environment variable never switches a test'
)
#: The calls whose condition argument decides whether a test runs, and the calls a skipping branch makes.
_CONDITION_CALLS: Final = frozenset({'skipif', 'xfail'})
_SKIP_CALLS: Final = frozenset({'skip', 'skipif', 'xfail', 'importorskip'})
_ENVIRONS: Final = frozenset({'environ', 'environb'})
_GETENVS: Final = frozenset({'getenv', 'getenvb'})
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


@dataclass(frozen=True, slots=True)
class _Os:
    """How one source reaches ``os``: the names bound to the module, and each local name imported from it."""

    modules: frozenset[str]
    members: dict[str, str]

    def member(self, node: ast.AST) -> str:
        """The :data:`_OS_NAMES` member *node* names (``os.environ``, an imported ``getenv`` alias), else ``''``."""
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id in self.modules:
            return node.attr if node.attr in _OS_NAMES else ''
        return self.members.get(node.id, '') if isinstance(node, ast.Name) else ''


def _os_bindings(tree: ast.AST) -> _Os:
    modules: set[str] = set()
    members: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules |= {alias.asname or alias.name for alias in node.names if alias.name == 'os'}
        elif isinstance(node, ast.ImportFrom) and node.module == 'os' and not node.level:
            members |= {alias.asname or alias.name: alias.name for alias in node.names if alias.name in _OS_NAMES}
    return _Os(frozenset(modules), members)


def _read_lines(tree: ast.AST, bound_os: _Os) -> set[int]:
    return {node.lineno for node in ast.walk(tree) if bound_os.member(node)}


def python_reads(source: str) -> tuple[int, ...]:
    """The lines of *source* reaching the environment through ``os`` (see the module docstring for the shapes)."""
    tree = ast.parse(source)
    return tuple(sorted(_read_lines(tree, _os_bindings(tree))))


def _named_read_lines(tree: ast.AST, bound_os: _Os) -> set[int]:
    """Lines reading ONE variable by name -- ``environ[..]``, ``environ.get(..)``, ``getenv(..)``, ``.. in environ``.

    Handing the whole environment to a child (``{**os.environ}``, ``dict(os.environ)``) reads no variable's value.
    """
    lines: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Subscript):
            hit = bound_os.member(node.value) in _ENVIRONS
        elif isinstance(node, ast.Call):
            func = node.func
            get = isinstance(func, ast.Attribute) and func.attr == 'get' and bound_os.member(func.value) in _ENVIRONS
            hit = get or bound_os.member(func) in _GETENVS
        elif isinstance(node, ast.Compare):
            hit = any(
                isinstance(op, ast.In | ast.NotIn) and bound_os.member(right) in _ENVIRONS
                for op, right in zip(node.ops, node.comparators, strict=True)
            )
        else:
            hit = False
        if hit:
            lines.add(node.lineno)
    return lines


def _callee(node: ast.AST) -> str:
    if not isinstance(node, ast.Call):
        return ''
    func = node.func
    return func.attr if isinstance(func, ast.Attribute) else func.id if isinstance(func, ast.Name) else ''


def _conditions(tree: ast.AST) -> list[ast.expr]:
    """Every expression deciding whether a test runs: a ``skipif``/``xfail`` condition, a skipping branch's test."""
    found: list[ast.expr] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and _callee(node) in _CONDITION_CALLS:
            found += [*node.args, *(kw.value for kw in node.keywords if kw.arg == 'condition')]
        elif isinstance(node, ast.If | ast.IfExp | ast.While):
            branches = [node.body, node.orelse] if isinstance(node, ast.IfExp) else [*node.body, *node.orelse]
            if any(_callee(inner) in _SKIP_CALLS for branch in branches for inner in ast.walk(branch)):
                found.append(node.test)
    return found


def python_switches(source: str) -> tuple[int, ...]:
    """The lines of *source* whose environment read decides whether a test runs (class C; module docstring)."""
    tree = ast.parse(source)
    bound_os = _os_bindings(tree)
    bound: dict[str, set[int]] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign | ast.AnnAssign | ast.NamedExpr) or node.value is None:
            continue
        if lines := _named_read_lines(node.value, bound_os):
            for target in node.targets if isinstance(node, ast.Assign) else [node.target]:
                if isinstance(target, ast.Name):
                    bound.setdefault(target.id, set()).update(lines)
    found: set[int] = set()
    for condition in _conditions(tree):
        found |= _named_read_lines(condition, bound_os)
        found |= {line for name in ast.walk(condition) if isinstance(name, ast.Name) for line in bound.get(name.id, ())}
    return tuple(sorted(found))


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


def _switchers(root: Path, files: Iterable[str]) -> dict[str, tuple[int, ...]]:
    """Each test file's switch lines (:func:`python_switches`): judged in every mode, ``strict`` or not."""
    found: dict[str, tuple[int, ...]] = {}
    for rel in sorted({rel for rel in files if rel.endswith('.py') and _is_test(rel) and (root / rel).is_file()}):
        try:
            lines = python_switches((root / rel).read_text(encoding='utf-8', errors='replace'))
        except SyntaxError:
            continue
        if lines:
            found[rel] = lines
    return found


def census(root: Path, policy: EnvPolicy, files: Iterable[str]) -> tuple[str, ...]:
    """Every judged reader and test switch outside the entry: the ``pending`` list as it must read now."""
    files = tuple(files)
    readers = set(_readers(root, policy, files)) | set(_switchers(root, files))
    return tuple(sorted(rel for rel in readers if rel not in policy.entry))


def problems(root: Path, policy: EnvPolicy, files: Iterable[str]) -> list[str]:
    """Every refusal over *files* (repo-relative POSIX paths) under *root*, judged against *policy*.

    A test switch is refused off the ledger whatever the mode, the entry included (an entry cannot launder a C read),
    and it is named once, as a switch: its line is never also a plain read finding.
    """
    files = tuple(files)
    readers = _readers(root, policy, files)
    switchers = _switchers(root, files)
    pending = set(policy.pending)
    found = [
        f'{RULE_ID}: {rel}:{line}: an environment read decides whether a test runs (class C) -- {SWITCH_DOOR}'
        for rel, lines in switchers.items()
        if rel not in pending
        for line in lines
    ]
    found += [
        f'{RULE_ID}: {rel}:{line}: reads the environment outside the declared entry and the pending ledger'
        for rel, lines in readers.items()
        if rel not in policy.entry and rel not in pending
        for line in lines
        if line not in switchers.get(rel, ())
    ]
    found += [
        f'{RULE_ID}: {rel}: pending in [tool.dev_lab.{_TABLE}] and reads nothing now -- stale, delete it'
        for rel in sorted(pending - set(readers) - set(switchers))
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
