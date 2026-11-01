"""FOOTPRINT -- every repo path a test file's outcome can depend on, derived STATICALLY at one commit.

A test's outcome at commit A stands at a descendant B when no path ``git diff A B`` names lies in its
footprint (:mod:`dev_lab.dev.forgecarry`). That is only sound if the footprint over-approximates
what the test can read, so it is built to be WIDE, never hopeful:

* the test file itself, and every ``conftest.py`` and ``__init__.py`` CANDIDATE in its directory chain
  up to the root -- candidates, not files that exist, so a conftest ADDED above the test reaches it;
* the transitive closure of its imports WITHIN THE REPO (``ast``, no execution): for a dotted name every
  prefix's ``<p>.py`` and ``<p>/__init__.py`` under each import root (the repo root, ``src/`` and every
  ancestor directory of the importing file) -- again candidates, so a module shadowed by a new package
  is reached; ``pytest_plugins`` strings count as imports; relative imports resolve against the package;
* :data:`ALWAYS` (pytest's configuration and the interpreter pin) and the declared ``everywhere`` globs,
  in every footprint -- a NATIVE extension built from the repo is reached only through these, so a repo
  building one declares its sources there;
* the TOP-LEVEL NAME of every absolute import in the closure, as the pseudo-path ``import:<name>``
  (:data:`IMPORT`) -- the door through which a :data:`LOCK` change reaches a test (:func:`resolve_lock`);
* a module in the closure that can REACH THE REPO BY PATH (:func:`_reads_by_path`: ``__file__``,
  ``import_module``, ``subprocess``, a cwd, a pytest path attribute, a string literal starting with a
  tracked top-level name) makes the footprint EVERYTHING -- unless the repo declares what it reads::

    [tool.dev_lab.carry]
    everywhere = ["rust/**"]                        # paths that reach every test (beyond ALWAYS)

    [tool.dev_lab.carry.reads]                  # module glob -> the path globs it reads
    "tests/test_docs.py" = ["docs-src/**"]

A LOCK CHANGE REACHES ONLY ITS IMPORTERS (user ruling D48-2, 2026-11-01). :data:`LOCK` used to sit in
:data:`ALWAYS`, so a relock that only moved the ``dev-lab`` git pin re-ran a consumer's whole suite
(``scope=full ran=5471`` on the cluster, measured 2026-11-01; motronics #5397 relocked ~7 times that day).
Now :func:`resolve_lock` replaces a changed :data:`LOCK` by ``import:<name>`` for the import names of the
packages whose locked entry changed, closed over the lock's dependency graph IN REVERSE (a numpy bump
reaches scipy's importers). Doubt reaches everything by leaving :data:`LOCK` itself in the diff: a change
outside ``[[package]]`` (header, resolution markers, ``requires-python``), an unparseable lock, a package
:func:`import_names` cannot map, or one the RUNNER loads whatever a test imports (``pytest``, a ``pytest11``
plugin, a ``.pth`` installer). ``pyproject.toml`` stays in :data:`ALWAYS`: it carries pytest's and this
module's configuration, and splitting it by table is a second TOML differ no measured waste asks for yet.
Rendered workflows (``.github/workflows/**``) are no Python, so they reach a test only by a read by path.

Globs are :func:`fnmatch.fnmatchcase` over repo-relative POSIX paths, so ``*`` crosses ``/``. A
declaration is the consumer's statement, like any declared table: a wrong one carries a stale outcome,
so it names the reads of a module, never a hope.
"""

from __future__ import annotations

import ast
import functools
import importlib.metadata
import re
import subprocess
import tomllib
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from fnmatch import fnmatchcase
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, Any, Final

import lab_commons.launch as _door

from dev_lab.dev.family import declared_table
from dev_lab.dev.forge import _GIT

if TYPE_CHECKING:
    from pathlib import Path

__all__ = [
    'ALWAYS', 'EVERYTHING', 'IMPORT', 'LOCK', 'Footprint', 'Footprints', 'declared', 'import_names', 'lock_reach',
    'resolve_lock', 'test_files',
]  # fmt: skip

#: Paths in every footprint: pytest's own configuration and the interpreter pin.
ALWAYS: Final = frozenset({'pyproject.toml', 'pytest.ini', 'setup.cfg', 'tox.ini', '.python-version'})

#: The lock: in every footprint while UNRESOLVED; :func:`resolve_lock` turns it into the imports it reaches.
LOCK: Final = 'uv.lock'

#: The pseudo-path prefix of an imported top-level name (module docstring).
IMPORT: Final = 'import:'

#: The one glob meaning every path.
EVERYTHING: Final = '*'

#: Modules whose import alone lets code reach a path it does not name.
_PATH_MODULES: Final = frozenset(
    {'subprocess', 'importlib', 'importlib_resources', 'pkgutil', 'runpy', 'pkg_resources'}
)

#: Names and attributes through which code reaches the repo (or runs arbitrary code) by path.
_PATH_NAMES: Final = frozenset(
    {
        '__file__', '__path__', '__spec__', '__loader__', '__import__', 'exec', 'eval', 'import_module',
        'getcwd', 'cwd', 'chdir', 'system', 'popen', 'rootpath', 'rootdir', 'fspath', 'invocation_params',
        'startpath', 'datadir', 'shared_datadir', 'original_datadir',
    }
)  # fmt: skip

#: pytest's default ``python_files``.
_DEFAULT_TEST_FILES: Final = ('test_*.py', '*_test.py')

_GIT_TIMEOUT_S: Final = 120


def _git(root: Path, *args: str, stdin: str | None = None) -> str:
    done = _door.run(
        [_GIT, '-C', str(root), *args],
        input=stdin,
        capture_output=True,
        text=True,
        encoding='utf-8',
        errors='replace',
        timeout=_GIT_TIMEOUT_S,
        check=True,
    )
    return done.stdout


def declared(pyproject: str) -> tuple[tuple[str, ...], dict[str, tuple[str, ...]]]:
    """``(everywhere globs, reads by module glob)`` of ``[tool.dev_lab.carry]`` in *pyproject*.

    Raises:
        ValueError: a key is not the shape the module docstring shows; the message names it.

    """
    table = declared_table(tomllib.loads(pyproject), 'carry', {})
    everywhere = table.get('everywhere', [])
    reads = table.get('reads', {})
    ok = _globs(everywhere) and isinstance(reads, dict) and all(_globs(value) for value in reads.values())
    if not ok:
        msg = (
            '[tool.dev_lab.carry] must declare everywhere as an array of path globs and reads as a table '
            f'of module glob -> array of path globs, e.g. everywhere = ["rust/**"] -- not {table!r}'
        )
        raise ValueError(msg)
    return tuple(everywhere), {key: tuple(value) for key, value in reads.items()}


def _globs(value: object) -> bool:
    return isinstance(value, list) and all(isinstance(item, str) and item for item in value)


def test_files(pyproject: str, tracked: Iterable[str]) -> tuple[str, ...]:
    """The tracked paths pytest collects as test files, by ``python_files`` (pytest's default when unset)."""
    option = tomllib.loads(pyproject).get('tool', {}).get('pytest', {}).get('ini_options', {}).get('python_files')
    patterns = tuple(option.split() if isinstance(option, str) else option or _DEFAULT_TEST_FILES)
    return tuple(
        p for p in tracked if p.endswith('.py') and any(fnmatchcase(p.rpartition('/')[2], g) for g in patterns)
    )


@dataclass(frozen=True)
class Footprint:
    """The paths (exact) and globs one test file's outcome can depend on."""

    paths: frozenset[str]
    globs: tuple[str, ...] = ()

    def reaches(self, path: str) -> bool:
        """Whether a change to *path* can change the outcome."""
        return path in self.paths or any(fnmatchcase(path, glob) for glob in self.globs)

    def reaches_any(self, paths: Iterable[str]) -> bool:
        """Whether a change to any of *paths* can change the outcome."""
        return any(self.reaches(path) for path in paths)


@dataclass(frozen=True)
class _Parsed:
    candidates: frozenset[str]
    by_path: bool


def _ancestors(path: str) -> list[str]:
    """Every directory above *path*, nearest first, ending with the root (``''``)."""
    parts = PurePosixPath(path).parts[:-1]
    return ['/'.join(parts[:i]) for i in range(len(parts), -1, -1)]


def _join(directory: str, name: str) -> str:
    return f'{directory}/{name}' if directory else name


def _seeds(test: str) -> set[str]:
    """*test* and every ``conftest.py`` / ``__init__.py`` candidate in its directory chain (module docstring)."""
    return {test} | {_join(d, n) for d in _ancestors(test) for n in ('conftest.py', '__init__.py')}


def _dotted(dotted: str, roots: Iterable[str]) -> set[str]:
    """Every candidate file of *dotted* and its prefixes under each of *roots*."""
    parts = [part for part in dotted.split('.') if part]
    found = set()
    for root in roots:
        for i in range(1, len(parts) + 1):
            stem = _join(root, '/'.join(parts[:i]))
            found |= {f'{stem}.py', f'{stem}/__init__.py'}
    return found


def _parse(path: str, text: str, top: frozenset[str]) -> _Parsed:
    """The import candidates of module *path*, and whether it reaches the repo by path."""
    try:
        tree = ast.parse(text, filename=path)
    except (SyntaxError, ValueError):
        return _Parsed(frozenset(), by_path=True)
    roots = ['src', *_ancestors(path)]
    found: set[str] = set()
    by_path = False
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                found |= _dotted(alias.name, roots) | {IMPORT + alias.name.split('.')[0]}
                by_path = by_path or alias.name.split('.')[0] in _PATH_MODULES
        elif isinstance(node, ast.ImportFrom):
            found |= _from(path, node, roots)
            top = (node.module or '').split('.')[0]
            found |= {IMPORT + top} if node.level == 0 and top else set()
            by_path = by_path or (node.level == 0 and top in _PATH_MODULES)
        elif isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == 'pytest_plugins' for t in node.targets
        ):
            for item in ast.walk(node.value):
                if isinstance(item, ast.Constant) and isinstance(item.value, str):
                    found |= _dotted(item.value, roots) | {IMPORT + item.value.split('.')[0]}
        by_path = by_path or _reads_by_path(node, top)
    return _Parsed(frozenset(found), by_path=by_path)


def _from(path: str, node: ast.ImportFrom, roots: list[str]) -> set[str]:
    names = [alias.name for alias in node.names if alias.name != '*']
    if not node.level:
        base = node.module or ''
        return _dotted(base, roots) | {c for name in names for c in _dotted(f'{base}.{name}', roots)}
    package = _ancestors(path)[node.level - 1] if node.level - 1 < len(_ancestors(path)) else ''
    module = (node.module or '').replace('.', '/')
    stem = _join(package, module) if module else package
    found = {_join(package, '__init__.py')}
    if module:
        found |= {f'{stem}.py', f'{stem}/__init__.py'}
    for name in names:
        found |= {f'{_join(stem, name)}.py', f'{_join(stem, name)}/__init__.py'}
    return found


def _reads_by_path(node: ast.AST, top: frozenset[str]) -> bool:
    """Whether *node* reaches the repo by a path the import graph cannot see (module docstring)."""
    if isinstance(node, ast.Name):
        return node.id in _PATH_NAMES
    if isinstance(node, ast.Attribute):
        if node.attr == 'path':  # request.path / item.path / node.path -- but not os.path
            return not (isinstance(node.value, ast.Name) and node.value.id in {'os', 'sys'})
        return node.attr in _PATH_NAMES
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        head = node.value.replace('\\', '/').lstrip('./').split('/', 1)[0]
        return head in top
    return False


@dataclass
class Footprints:
    """Every test file's :class:`Footprint` at one commit, parsed once (:meth:`at`)."""

    tracked: frozenset[str]
    texts: Mapping[str, str]
    everywhere: tuple[str, ...]
    reads: Mapping[str, tuple[str, ...]]
    pyproject: str
    _parsed: dict[str, _Parsed] = field(default_factory=dict)
    _taint: dict[tuple[str, ...], frozenset[str]] = field(default_factory=dict)
    _graph: frozenset[str] | None = None
    _top: frozenset[str] | None = None

    @classmethod
    def at(cls, root: Path, sha: str) -> Footprints:
        """The footprints of commit *sha* of *root*; raises :class:`ValueError` on a malformed declaration."""
        tracked = frozenset(_git(root, 'ls-tree', '-r', '--name-only', '-z', sha).split('\0')) - {''}
        pyproject = _git(root, 'show', f'{sha}:pyproject.toml') if 'pyproject.toml' in tracked else ''
        everywhere, reads = declared(pyproject)
        return cls(
            tracked, _blobs(root, sha, sorted(p for p in tracked if p.endswith('.py'))), everywhere, reads, pyproject
        )

    def tests(self) -> tuple[str, ...]:
        """The test files of this commit (:func:`test_files`)."""
        return test_files(self.pyproject, sorted(self.tracked))

    def of(self, test: str) -> Footprint:
        """The footprint of test file *test* (module docstring)."""
        if not test.endswith('.py'):
            return Footprint(frozenset(), (EVERYTHING,))
        seeds = _seeds(test)
        paths, globs, todo, seen = set(seeds) | ALWAYS | {LOCK}, list(self.everywhere), sorted(seeds), set()
        while todo:
            module = todo.pop()
            if module in seen or module not in self.texts:
                continue
            seen.add(module)
            parsed = self._parse(module)
            paths |= parsed.candidates
            todo += sorted(parsed.candidates - seen)
            if parsed.by_path:
                declared_reads = self._declared_reads(module)
                if not declared_reads:
                    return Footprint(frozenset(paths), (EVERYTHING,))
                globs += declared_reads
        return Footprint(frozenset(paths), tuple(dict.fromkeys(globs)))

    def reaches(self, test: str, changed: Iterable[str]) -> bool:
        """``self.of(test).reaches_any(changed)``, judged by ONE pass over the import graph per *changed* set.

        The tests of a repo share most of their closure, so :meth:`of` per test file is quadratic in it: on
        5k test files it held a cluster serve tick for 33 min of pure CPU (Ada, 2026-10-17). Here a module is
        TAINTED when its closure reaches *changed* -- by a candidate path it names, or a read by path that
        is undeclared or matches -- and so is every importer of a tainted module, walked backwards once. A
        test reaches *changed* by a seed, :data:`ALWAYS` or unresolved :data:`LOCK` path, an ``everywhere``
        glob, or a tainted seed.
        """
        hit = tuple(sorted(set(changed)))
        if not hit:
            return False
        seeds = _seeds(test)
        if not test.endswith('.py') or not (seeds | ALWAYS | {LOCK}).isdisjoint(hit):
            return True
        if any(fnmatchcase(path, glob) for path in hit for glob in self.everywhere):
            return True
        graph = self._closures()
        if not {seed for seed in seeds if seed in self.texts} <= graph:  # not a test file this commit names
            return self.of(test).reaches_any(hit)
        return not self._tainted(hit).isdisjoint(seeds)

    def _tainted(self, hit: tuple[str, ...]) -> frozenset[str]:
        """The modules of :meth:`_closures` whose own closure reaches *hit* (memoized per changed set)."""
        if hit not in self._taint:
            changed, importers, tainted = frozenset(hit), {}, set()
            for module in self._closures():
                parsed = self._parse(module)
                for imported in parsed.candidates & self.texts.keys():
                    importers.setdefault(imported, []).append(module)
                if not changed.isdisjoint(parsed.candidates) or (parsed.by_path and self._reads_reach(module, hit)):
                    tainted.add(module)
            todo = list(tainted)
            while todo:
                for importer in importers.get(todo.pop(), ()):
                    if importer not in tainted:
                        tainted.add(importer)
                        todo.append(importer)
            self._taint[hit] = frozenset(tainted)
        return self._taint[hit]

    def _reads_reach(self, module: str, hit: tuple[str, ...]) -> bool:
        """Whether by-path *module* reaches *hit*: always when it declares no reads, else when one matches."""
        declared_reads = self._declared_reads(module)
        return not declared_reads or any(fnmatchcase(path, glob) for path in hit for glob in declared_reads)

    def _declared_reads(self, module: str) -> list[str]:
        return [glob for key, value in self.reads.items() if fnmatchcase(module, key) for glob in value]

    def _closures(self) -> frozenset[str]:
        """Every module in some test file's closure, each walked once: the union of :meth:`of`'s walks."""
        if self._graph is None:
            seen: set[str] = set()
            todo = [seed for test in self.tests() for seed in _seeds(test) if seed in self.texts]
            while todo:
                module = todo.pop()
                if module not in seen:
                    seen.add(module)
                    todo += [m for m in self._parse(module).candidates if m in self.texts and m not in seen]
            self._graph = frozenset(seen)
        return self._graph

    def _parse(self, module: str) -> _Parsed:
        if module not in self._parsed:
            if self._top is None:  # once: it is every tracked path's top level
                self._top = frozenset(path.split('/', 1)[0] for path in self.tracked)
            self._parsed[module] = _parse(module, self.texts[module], self._top)
        return self._parsed[module]


def _blobs(root: Path, sha: str, paths: list[str]) -> dict[str, str]:
    """The text of each of *paths* at *sha*, through ONE ``git cat-file --batch``."""
    if not paths:
        return {}
    done = _door.run(
        [_GIT, '-C', str(root), 'cat-file', '--batch'],
        input=''.join(f'{sha}:{path}\n' for path in paths).encode('utf-8'),
        capture_output=True,
        timeout=_GIT_TIMEOUT_S,
        check=True,
    )
    out, texts, at = done.stdout, {}, 0
    for path in paths:
        end = out.index(b'\n', at)
        header = out[at:end].split()
        at = end + 1
        if header[1:2] != [b'blob']:  # 'missing' (a submodule, a race): no text, nothing parsed
            continue
        size = int(header[2])
        texts[path] = out[at : at + size].decode('utf-8', errors='replace')
        at += size + 1
    return texts


def _canon(name: str) -> str:
    """PEP 503's normal form of a distribution name: the lock's and the metadata's spellings meet here."""
    return re.sub(r'[-_.]+', '-', name).lower()


@functools.cache
def _installed() -> tuple[dict[str, frozenset[str]], frozenset[str]]:
    """``({distribution: import names}, runner distributions)`` of the running environment, read once."""
    names: dict[str, set[str]] = {}
    for top, dists in importlib.metadata.packages_distributions().items():
        if top.isidentifier() and not top.startswith('__editable__'):
            for dist in dists:
                names.setdefault(_canon(dist), set()).add(top)
    plugins = importlib.metadata.entry_points(group='pytest11')
    runner = {'pytest'} | {_canon(ep.dist.name) for ep in plugins if ep.dist is not None}
    for dist in importlib.metadata.distributions():
        if any(len(f.parts) == 1 and f.name.endswith('.pth') for f in dist.files or ()):
            runner.add(_canon(dist.metadata['Name'] or ''))
    return {dist: frozenset(tops) for dist, tops in names.items()}, frozenset(runner)


def import_names(dist: str) -> frozenset[str] | None:
    """The top-level import names distribution *dist* installs; ``None`` when it reaches EVERY test.

    Read from the running environment's metadata (``packages_distributions``: ``top_level.txt``, else
    RECORD). ``None`` for a distribution that environment does not know -- doubt carries nothing -- and for
    one the RUNNER loads whatever a test imports: ``pytest``, a ``pytest11`` plugin, a top-level ``.pth``.
    """
    known, runner = _installed()
    dist = _canon(dist)
    return None if dist in runner else known.get(dist)


def _packages(lock: Mapping[str, Any]) -> dict[str, list[Any]] | None:
    """``{canonical name: [its locked entries]}``; ``None`` when an entry is not a named table."""
    found: dict[str, list[Any]] = {}
    for entry in lock.get('package', []):
        if not isinstance(entry, dict) or not isinstance(entry.get('name'), str):
            return None
        found.setdefault(_canon(entry['name']), []).append(entry)
    return found


def _depends(entries: Iterable[Mapping[str, Any]]) -> set[str]:
    """Every package the *entries* depend on: runtime, optional and dev dependency lists alike."""
    found = set()
    for entry in entries:
        groups = [entry.get('dependencies', [])]
        for key in ('optional-dependencies', 'dev-dependencies'):
            groups += list(entry.get(key, {}).values())
        found |= {_canon(dep['name']) for group in groups for dep in group}
    return found


def _graphs(old: str, new: str) -> tuple[set[str], dict[str, set[str]]] | None:
    """``(changed packages, {package: its dependents})`` of two locks; ``None`` on any doubt (:func:`lock_reach`)."""
    try:
        before, after = tomllib.loads(old), tomllib.loads(new)
        if {k: v for k, v in before.items() if k != 'package'} != {k: v for k, v in after.items() if k != 'package'}:
            return None
        was, now = _packages(before), _packages(after)
        if was is None or now is None:
            return None
        dependents: dict[str, set[str]] = {}
        for graph in (was, now):
            for package, entries in graph.items():
                for dep in _depends(entries):
                    dependents.setdefault(dep, set()).add(package)
    except (tomllib.TOMLDecodeError, AttributeError, TypeError, KeyError):
        return None
    return {package for package in was.keys() | now.keys() if was.get(package) != now.get(package)}, dependents


def lock_reach(
    old: str, new: str, names: Callable[[str], frozenset[str] | None] | None = None
) -> frozenset[str] | None:
    """The import names a lock change from *old* to *new* reaches; ``None`` when it reaches everything.

    A package is CHANGED when its locked entries differ (version, source or git sha, dependency list --
    any byte of an entry), and REACHED when changed or depending on a reached package, over the union of
    both locks' graphs (a dropped edge still reaches). A difference outside ``[[package]]``, an unreadable
    lock, or a reached package *names* maps to ``None``, reaches everything (module docstring).
    """
    graphs = _graphs(old, new)
    if graphs is None:
        return None
    reached, dependents = graphs
    todo = list(reached)
    while todo:
        for dependent in dependents.get(todo.pop(), ()):
            if dependent not in reached:
                reached.add(dependent)
                todo.append(dependent)
    found: set[str] = set()
    for package in sorted(reached):
        tops = (names or import_names)(package)
        if tops is None:
            return None
        found |= tops
    return frozenset(found)


def resolve_lock(
    root: Path, a: str, b: str, changed: Iterable[str], names: Callable[[str], frozenset[str] | None] | None = None
) -> tuple[str, ...]:
    """*changed* with :data:`LOCK` replaced by the ``import:<name>`` paths it reaches; kept on any doubt."""
    changed = tuple(changed)
    if LOCK not in changed:
        return changed
    try:
        reach = lock_reach(_git(root, 'show', f'{a}:{LOCK}'), _git(root, 'show', f'{b}:{LOCK}'), names)
    except subprocess.SubprocessError:  # added or deleted: no two sides to compare
        return changed
    if reach is None:
        return changed
    return tuple(sorted({*changed, *(IMPORT + top for top in reach)} - {LOCK}))
