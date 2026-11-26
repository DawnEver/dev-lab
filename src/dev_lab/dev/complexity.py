"""The per-owner complexity report: how far a module reaches, how many it leans on, how much it exposes.

A REPORT, NOT A GATE (family policy 2026-11-25, v1-migration D67/D68): nothing here refuses a value. ``record``
appends one JSONL line per owner to the dated tree, ``<output>/logs/<yy>/<mm>/<dd>/complexity/owners.jsonl`` of
the main checkout (so every lane of one repo writes one series), and ``trend`` reads every day back.

AN OWNER is a tracked Python module outside the tests (``tests/``, ``benches/``, ``conftest.py``), named as it
imports (:func:`dev_lab.dev.importedges.module_name`). Its three readings, all read off the source with ``ast``:

* ``fan_out`` -- the distinct in-repo modules it imports, at any nesting depth; the standard library and
  third-party packages are not the repo's, and a package whose submodule it imports is implied, so neither counts;
* ``call_path`` -- the longest chain of in-repo imports starting at it. A static proxy for the call path: what a
  call from here can reach is bounded by what it imports. Mutually importing modules are one strongly connected
  set and count as one hop, so a cycle has a finite length;
* ``surface`` -- its ``__all__`` when declared as a literal, else its public top-level names (``def``, ``class``,
  assignment).

Each line carries ``time``, ``event.name`` (``lab.complexity``), ``vcs.repository.url.full``,
``vcs.ref.head.revision`` and ``code.namespace`` (the owner), as OpenTelemetry names, and the three readings under
``lab.complexity.*``.
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Final

import lab_commons.launch as _door
from lab_commons.log import emit

from dev_lab.dev.datedlog import date_parts
from dev_lab.dev.importedges import import_edges, module_name
from dev_lab.dev.metrics import checkout, repo_of
from dev_lab.dev.rules import tracked_files
from dev_lab.dev.storage import output_path

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence

__all__ = ['KIND', 'Owner', 'main', 'owners', 'read', 'record', 'trend']

#: The output-tree kind the records live under.
KIND: Final = 'complexity'
_FILE: Final = 'owners.jsonl'
_READINGS: Final = ('fan_out', 'call_path', 'surface')
_TEST_DIRS: Final = frozenset({'tests', 'benches'})


@dataclass(frozen=True, slots=True)
class Owner:
    """One module's three readings."""

    name: str
    fan_out: int
    call_path: int
    surface: int


def _owned(rel: str) -> bool:
    path = PurePosixPath(rel)
    return path.suffix == '.py' and path.name != 'conftest.py' and not (_TEST_DIRS & set(path.parts[:-1]))


def _names_all(node: ast.Assign) -> bool:
    return any(isinstance(target, ast.Name) and target.id == '__all__' for target in node.targets)


def _surface(tree: ast.Module) -> int:
    for node in tree.body:
        if isinstance(node, ast.Assign) and _names_all(node) and isinstance(node.value, (ast.List, ast.Tuple)):
            return len(node.value.elts)
    kinds = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
    names = {node.name for node in tree.body if isinstance(node, kinds)}
    for node in tree.body:
        targets = (
            node.targets if isinstance(node, ast.Assign) else [node.target] if isinstance(node, ast.AnnAssign) else []
        )
        names |= {target.id for target in targets if isinstance(target, ast.Name)}
    return sum(1 for name in names if not name.startswith('_'))


def _leaves(names: frozenset[str]) -> frozenset[str]:
    """*names* without an ancestor package of another: importing ``pkg.b`` imports ``pkg`` by construction."""
    return frozenset(name for name in names if not any(other.startswith(f'{name}.') for other in names))


def _postorder(graph: Mapping[str, Iterable[str]], starts: Iterable[str], seen: set[str]) -> list[str]:
    """Every node reachable from *starts* and not in *seen* (which grows), each after its successors; iterative."""
    out: list[str] = []
    for start in starts:
        if start in seen:
            continue
        seen.add(start)
        work = [(start, iter(sorted(graph[start])))]
        while work:
            node, children = work[-1]
            child = next((c for c in children if c not in seen), None)
            if child is None:
                work.pop()
                out.append(node)
            else:
                seen.add(child)
                work.append((child, iter(sorted(graph[child]))))
    return out


def _components(graph: Mapping[str, frozenset[str]]) -> dict[str, int]:
    """Kosaraju: owner -> strongly connected component, numbered in topological order (an importer first)."""
    importers: dict[str, set[str]] = {node: set() for node in graph}
    for node, children in graph.items():
        for child in children:
            importers[child].add(node)
    component: dict[str, int] = {}
    assigned: set[str] = set()
    for start in reversed(_postorder(graph, sorted(graph), set())):
        if start not in assigned:
            number = len(set(component.values()))
            component.update(dict.fromkeys(_postorder(importers, [start], assigned), number))
    return component


def _call_paths(graph: Mapping[str, frozenset[str]]) -> dict[str, int]:
    component = _components(graph)
    reach: dict[int, set[int]] = defaultdict(set)
    for node, children in graph.items():
        reach[component[node]] |= {component[c] for c in children if component[c] != component[node]}
    length: dict[int, int] = {}
    for number in sorted(set(component.values()), reverse=True):  # topological order reversed: successors first
        length[number] = max((length[c] + 1 for c in reach[number]), default=0)
    return {node: length[component[node]] for node in graph}


def owners(root: Path, files: Iterable[str]) -> tuple[Owner, ...]:
    """Every owner among *files* (repo-relative POSIX paths) under *root*, with its three readings, by name."""
    trees: dict[str, ast.Module] = {}
    edges: dict[str, frozenset[str]] = {}
    for rel in sorted(f for f in files if _owned(f) and (root / f).is_file()):
        source = (root / rel).read_text(encoding='utf-8', errors='replace')
        name = module_name(root, root / rel)
        try:
            trees[name] = ast.parse(source)
            edges[name] = import_edges(source, name, is_package=rel.endswith('__init__.py'))
        except (SyntaxError, ImportError):
            continue
    graph = {name: _leaves(frozenset(e for e in found if e in trees and e != name)) for name, found in edges.items()}
    paths = _call_paths(graph)
    return tuple(Owner(name, len(graph[name]), paths[name], _surface(trees[name])) for name in sorted(graph))


def _tracked(root: Path) -> tuple[str, ...]:
    return tracked_files(root)


def _revision(root: Path) -> str:
    done = _door.run(['git', '-C', str(root), 'rev-parse', 'HEAD'], capture_output=True, check=False, timeout=60)
    return done.stdout.decode('utf-8', 'replace').strip() if done.returncode == 0 else ''


def _log(root: Path, day: tuple[str, str, str] | None = None) -> Path:
    return output_path(checkout(root), 'logs', *(day or date_parts()), KIND, _FILE)


def record(root: Path, *, repo: str) -> Path:
    """Append one line per owner of *root*'s tracked tree to today's record; the file."""
    now, revision = datetime.now(UTC).isoformat(), _revision(root)
    lines = [
        {
            'time': now,
            'event.name': f'lab.{KIND}',
            'vcs.repository.url.full': repo,
            'vcs.ref.head.revision': revision,
            'code.namespace': owner.name,
            **{f'lab.{KIND}.{reading}': getattr(owner, reading) for reading in _READINGS},
        }
        for owner in owners(root, _tracked(root))
    ]
    target = _log(root)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(target, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
    try:
        os.write(fd, ''.join(json.dumps(line, sort_keys=True) + '\n' for line in lines).encode('utf-8'))
        os.fsync(fd)
    finally:
        os.close(fd)
    return target


def read(root: Path) -> list[dict[str, object]]:
    """Every recorded line under *root*'s checkout, oldest day first; a torn line is skipped."""
    base = checkout(root)
    found: list[dict[str, object]] = []
    for path in sorted(base.glob(_log(base, ('*', '*', '*')).relative_to(base).as_posix())):
        for raw in path.read_text(encoding='utf-8').splitlines():
            try:
                found.append(json.loads(raw))
            except ValueError:
                continue
    return found


def trend(lines: Sequence[Mapping[str, object]], *, top: int) -> list[str]:
    """One line per run (its totals), then the *top* owners by last fan-out with each reading first -> last."""
    runs: dict[str, dict[str, Mapping[str, object]]] = defaultdict(dict)
    for line in lines:
        runs[str(line['time'])][str(line['code.namespace'])] = line
    view = []
    for time, by_owner in sorted(runs.items()):
        totals = ' '.join(
            f'{reading} {sum(int(str(o[f"lab.{KIND}.{reading}"])) for o in by_owner.values())}' for reading in _READINGS
        )
        revision = str(next(iter(by_owner.values())).get('vcs.ref.head.revision', ''))[:12]
        view.append(f'run {time} {revision} owners {len(by_owner)} {totals}')
    if not runs:
        return view
    first, last = runs[min(runs)], runs[max(runs)]

    def value(owner: Mapping[str, object] | None, reading: str) -> int:
        return int(str(owner[f'lab.{KIND}.{reading}'])) if owner else 0

    ranked = sorted(last, key=lambda name: (-value(last[name], 'fan_out'), name))[:top]
    for name in ranked:
        moved = ', '.join(f'{r} {value(first.get(name), r)} -> {value(last[name], r)}' for r in _READINGS)
        view.append(f'  {name}: {moved}')
    return view


def main(argv: Sequence[str] | None = None, *, cwd: Path | None = None) -> int:
    """``record`` today's readings of the checkout at *cwd*; ``trend [--top N]`` prints every run and the top owners."""
    parser = argparse.ArgumentParser(prog='python -m dev_lab.dev.complexity', description=__doc__.splitlines()[0])
    verbs = parser.add_subparsers(dest='verb', required=True)
    verbs.add_parser('record', help="append today's per-owner readings")
    shown = verbs.add_parser('trend', help='every run, then the top owners first -> last')
    shown.add_argument('--top', type=int, default=20, help='owners shown, by last fan-out (default 20)')
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)
    root = cwd or Path.cwd()
    if args.verb == 'record':
        emit(str(record(root, repo=repo_of(root))))
    else:
        emit('\n'.join(trend(read(root), top=args.top)) or f'no {KIND} record under {checkout(root)}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
