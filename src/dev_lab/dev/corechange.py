"""ZERO-CORE-CHANGE: application work never changes the core, unless a recorded architecture decision says so.

User ruling 2026-11-24. A repo OPTS IN in its ``pyproject.toml``::

    [tool.dev_lab.layers]
    core = ["src/<pkg>/core", ...]          # repo-relative paths (directories or files)
    applications = "src/<pkg>/applications/*"  # one glob per segment; each match is ONE application root

An undeclared repo is not judged, and every mode says so in its output. Two judgements read the one declaration:

1. THE CHANGE SET (:func:`range_problems`): a change set touching ANY application root AND the core is refused
   unless a commit of the set carries ``Architecture-Decision: <task>#D<n>`` naming a decision RECORDED in that
   task's journal in the task ledger (:func:`dev_lab.dev.taskledger.ledger`, open or archived) -- a made-up id is
   refused by name. The set is judged NET since the merge-base with the base, never per push increment: a core edit
   in one push and an application edit in the next are still one set. It runs as the ``zero-core-change`` pre-push
   row (git's ref lines on stdin, base ``origin/<integration>``) and as ``range <base> <head>`` for a PR diff.
2. THE STATIC RULES (:func:`static_problems`, the always-on family check :func:`check`), read with
   :mod:`dev_lab.dev.importedges`: the core never imports an application module, and the applications form an
   acyclic import graph -- a cycle is named application by application.
"""

from __future__ import annotations

import fnmatch
import re
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Final

import lab_commons.launch as _door
from lab_commons.log import emit

from dev_lab.dev import importedges, taskjournal
from dev_lab.dev.family import declared_table

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

__all__ = [
    'DOOR',
    'RULE_ID',
    'TRAILER',
    'Layers',
    'application_of',
    'change_set_problems',
    'check',
    'decision_missing',
    'decision_trailers',
    'declared_layers',
    'in_core',
    'main',
    'range_problems',
    'static_problems',
]

RULE_ID: Final = 'ZERO-CORE-CHANGE'
TRAILER: Final = 'Architecture-Decision'
_TABLE: Final = 'layers'
_TRAILER_LINE: Final = re.compile(rf'^{TRAILER}:[ \t]*([a-z0-9]+(?:-[a-z0-9]+)*)#D(\d+)[ \t]*$', re.MULTILINE)
_ZERO: Final = '0' * 40
_REF_LINE_FIELDS: Final = 4
DOOR: Final = (
    'split the change so application work leaves the core untouched; or, when the core must move, record the '
    'architecture decision in the task (`python -m dev_lab.dev.task decide "<decision>"`, which mints D<n>) and '
    f'carry `{TRAILER}: <task>#D<n>` as a trailer of a commit in the change set'
)
_DETAILS: Final = 'details: docs-src/dev/refusals.md#zero-core-change (dev-lab)'


@dataclass(frozen=True, slots=True)
class Layers:
    """The declaration: the core paths and the glob whose every match is one application root."""

    core: tuple[str, ...]
    applications: str


#: How many core paths a refusal names before it says how many more.
_SHOWN: Final = 5


def declared(root: Path) -> bool:
    """Whether *root* opts in: a ``[tool.dev_lab.layers]`` table, or a manifest too broken to say (then judged)."""
    try:
        data = tomllib.loads((root / 'pyproject.toml').read_text(encoding='utf-8'))
    except OSError:
        return False
    except ValueError:
        return True
    return declared_table(data, _TABLE) is not None


def declared_layers(root: Path) -> Layers | None:
    """*root*'s ``[tool.dev_lab.layers]``; ``None`` when undeclared (not judged). A malformed one raises ValueError."""
    try:
        data = tomllib.loads((root / 'pyproject.toml').read_text(encoding='utf-8'))
    except OSError:
        return None
    table = declared_table(data, _TABLE)
    if table is None:
        return None
    core, apps = table.get('core'), table.get('applications')
    if not isinstance(core, list) or not core or not all(isinstance(c, str) and c.strip('/') for c in core):
        msg = f'[tool.dev_lab.{_TABLE}] core must be a non-empty list of repo-relative paths, not {core!r}'
        raise ValueError(msg)
    if not isinstance(apps, str) or not apps.strip('/'):
        msg = f'[tool.dev_lab.{_TABLE}] applications must be one glob, e.g. "src/<pkg>/applications/*", not {apps!r}'
        raise ValueError(msg)
    return Layers(tuple(c.strip('/') for c in core), apps.strip('/'))


def in_core(path: str, layers: Layers) -> bool:
    """Whether the repo-relative *path* is a core path or lies below one."""
    return any(path == c or path.startswith(c + '/') for c in layers.core)


def application_of(path: str, layers: Layers) -> str | None:
    """The application root *path* lies below (strictly), else ``None``."""
    pattern, parts = layers.applications.split('/'), path.split('/')
    if len(parts) <= len(pattern) or not all(fnmatch.fnmatchcase(p, g) for p, g in zip(parts, pattern, strict=False)):
        return None
    return '/'.join(parts[: len(pattern)])


def decision_trailers(messages: Iterable[str]) -> list[tuple[str, int]]:
    """Every well-formed ``Architecture-Decision: <task>#D<n>`` trailer in *messages*, in order."""
    return [(m[1], int(m[2])) for text in messages for m in _TRAILER_LINE.finditer(text)]


def decision_missing(ledger: Path, slug: str, number: int) -> str | None:
    """Why ``<slug>#D<number>`` is not a recorded decision in the task ledger *ledger*; ``None`` when it is."""
    folders = [ledger / slug, *sorted((ledger / 'archive').glob(f'*/{slug}'), reverse=True)]
    journal = next((f / 'JOURNAL.md' for f in folders if (f / 'JOURNAL.md').is_file()), None)
    if journal is None:
        return f'no task {slug} in the task ledger {ledger.as_posix()} (open or archived)'
    try:
        decisions = taskjournal.parse(journal.read_text(encoding='utf-8')).decisions
    except taskjournal.RepeatedId as exc:
        return str(exc)
    if all(n != number for n, _, _ in decisions):
        return f'task {slug} records no decision D{number} (its journal mints {len(decisions)} decision(s))'
    return None


def change_set_problems(layers: Layers, paths: Iterable[str], messages: Sequence[str], ledger: Path) -> list[str]:
    """The refusal for one change set (*paths* changed, *messages* of its commits); empty when it passes."""
    paths = list(paths)
    apps = sorted({a for p in paths if (a := application_of(p, layers)) is not None})
    core = sorted(p for p in paths if in_core(p, layers))
    if not apps or not core:
        return []
    trailers = decision_trailers(messages)
    why = [f'{slug}#D{n}: {miss}' for slug, n in trailers if (miss := decision_missing(ledger, slug, n)) is not None]
    if trailers and not why:
        return []
    shown = ', '.join(core[:_SHOWN]) + (f' (+{len(core) - _SHOWN} more)' if len(core) > _SHOWN else '')
    named = f'; the named decision is not recorded: {"; ".join(why)}' if why else f'; no commit carries {TRAILER}'
    head = f'{RULE_ID}: the change set touches application root(s) {", ".join(apps)} AND the core ({shown}){named}'
    return [f'{head} -- {DOOR}\n{_DETAILS}']


def _git(root: Path, *args: str) -> str:
    done = _door.run(['git', '-C', str(root), *args], capture_output=True, check=False, timeout=120)
    if done.returncode != 0:
        msg = f'git {" ".join(args)} failed: {done.stderr.decode("utf-8", "replace").strip()}'
        raise RuntimeError(msg)
    return done.stdout.decode('utf-8', 'replace')


def range_problems(root: Path, layers: Layers, base: str, head: str, ledger: Path) -> list[str]:
    """:func:`change_set_problems` of *head*'s change set since its merge-base with *base*, judged net."""
    since = _git(root, 'merge-base', base, head).strip()
    paths = [
        p for p in _git(root, '-c', 'core.quotepath=off', 'diff', '--name-only', '-z', since, head).split('\0') if p
    ]
    messages = [m for m in _git(root, 'log', '--format=%B%x00', f'{since}..{head}').split('\0') if m.strip()]
    return change_set_problems(layers, paths, messages, ledger)


def _package(root: Path, rel: str) -> str:
    """The dotted package a repo-relative directory or ``.py`` file imports as (:func:`importedges.module_name`)."""
    path = root / rel
    return importedges.module_name(root, path if path.suffix == '.py' else path / '__init__.py')


def _under(name: str, package: str) -> bool:
    return name == package or name.startswith(package + '.')


def _cycle(graph: dict[str, set[str]]) -> list[str] | None:
    """One cycle of *graph* as ``[a, b, ..., a]``, else ``None`` (iterative DFS, deterministic order)."""
    state: dict[str, int] = {}  # 1: on the stack, 2: done
    for start in sorted(graph):
        if start in state:
            continue
        path, stack = [start], [iter(sorted(graph[start]))]
        state[start] = 1
        while stack:
            nxt = next(stack[-1], None)
            if nxt is None:
                state[path.pop()] = 2
                stack.pop()
            elif state.get(nxt) == 1:
                return [*path[path.index(nxt) :], nxt]
            elif nxt not in state:
                state[nxt] = 1
                path.append(nxt)
                stack.append(iter(sorted(graph.get(nxt, ()))))
    return None


def static_problems(root: Path, layers: Layers, files: Iterable[str]) -> list[str]:
    """The static rules over the ``.py`` *files* (repo-relative): core imports no application; applications acyclic."""
    py = sorted(f for f in files if f.endswith('.py'))
    apps = sorted({a for f in py if (a := application_of(f, layers)) is not None})
    packages = {a: _package(root, a) for a in apps}
    owner = sorted(packages.values(), key=len, reverse=True)
    problems: list[str] = []
    graph: dict[str, set[str]] = {packages[a]: set() for a in apps}
    for rel in py:
        app = application_of(rel, layers)
        if app is None and not in_core(rel, layers):
            continue
        edges = importedges.imports_of(root, root / rel)
        hit = {p for e in edges for p in owner if _under(e, p)}
        if app is None:
            if hit:
                problems.append(f'{rel} (core) imports application module(s) {", ".join(sorted(hit))}')
        else:
            graph[packages[app]] |= hit - {packages[app]}
    if (cycle := _cycle(graph)) is not None:
        problems.append(f'the applications import in a cycle: {" -> ".join(cycle)}')
    return [f'{RULE_ID}: {p} -- {_STATIC_DOOR}\n{_DETAILS}' for p in problems]


_STATIC_DOOR: Final = (
    'the core never imports an application and the applications form an acyclic graph: move what the core needs '
    'into the core, and break a cycle by moving the shared part down'
)


def check(root: Path) -> None:
    """The always-on family check: raise naming every static violation in *root*'s tracked tree (when declared)."""
    from dev_lab.dev.rules import tracked_files  # noqa: PLC0415 -- the registry imports this module's rows

    layers = declared_layers(root)
    if layers is None:
        return
    if problems := static_problems(root, layers, (f for f in tracked_files(root) if (root / f).is_file())):
        raise AssertionError('\n'.join(problems))


def _ledger() -> Path:
    from dev_lab.dev.taskledger import ledger  # noqa: PLC0415 -- only a judged change set resolves the ledger

    return ledger()


def _pushed(root: Path, layers: Layers, ref_lines: str) -> list[str]:
    from dev_lab.dev.lanepolicy import policy_at  # noqa: PLC0415 -- only a pushing repo reads its lane policy

    base = f'origin/{policy_at(root, "HEAD").integration}'
    out: list[str] = []
    for line in ref_lines.splitlines():
        parts = line.split()
        if len(parts) == _REF_LINE_FIELDS and parts[1] != _ZERO:
            out.extend(range_problems(root, layers, base, parts[1], _ledger()))
    return out


def main(argv: Sequence[str] | None = None, *, cwd: Path | None = None) -> int:
    """``range <base> <head>``: judge a PR diff; no mode: the pre-push row (git's ref lines on stdin). 1 refuses."""
    args = list(sys.argv[1:] if argv is None else argv)
    root = Path(_git(cwd or Path.cwd(), 'rev-parse', '--show-toplevel').strip())
    try:
        layers = declared_layers(root)
    except ValueError as exc:
        emit(f'{RULE_ID}: {exc}')
        return 1
    if layers is None:
        emit(f'{RULE_ID}: not judged -- {root.name} declares no [tool.dev_lab.{_TABLE}] (opt-in)')
        return 0
    if args == ['static']:
        from dev_lab.dev.rules import tracked_files  # noqa: PLC0415

        problems = static_problems(root, layers, (f for f in tracked_files(root) if (root / f).is_file()))
    elif args[:1] == ['range'] and len(args) == len(('range', '<base>', '<head>')):
        problems = range_problems(root, layers, args[1], args[2], _ledger())
    elif not args or (len(args) <= len(('<remote>', '<url>')) and not args[0].startswith('-')):
        problems = _pushed(root, layers, '' if sys.stdin.isatty() else sys.stdin.read())
    else:
        emit(f'{RULE_ID}: usage: python -m dev_lab.dev.corechange [range <base> <head>]')
        return 2
    for problem in problems:
        emit(problem)
    return 1 if problems else 0


if __name__ == '__main__':
    sys.exit(main())
