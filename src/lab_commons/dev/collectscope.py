"""WILL COLLECTION SUCCEED? The half :mod:`~lab_commons.dev.syncscope` names as unmeasurable in its own words.

That module asks whether a sync leaves the RUNNER able to start, and closes its docstring by naming
what it cannot see: *"whether a test module imports a pruned distribution. A test module importing
``cv2`` from an extra outside ``all`` still errors at collection, and no reading of a manifest can
say so."* This module is that reading, and it needs a second text to do it -- the TEST TREE.

**A COLLECTION ERROR IS NOT A TEST FAILURE, IT IS A REPO WITH NO VERDICT.** pytest IMPORTS every
module it collects; an ``ImportError`` at module scope aborts collection of that file and exits
non-zero having judged nothing. So the failure mode of 2026-09-18 -- a tree that reads as BROKEN
rather than as UNEQUIPPED -- survives one layer in, past a scope that scored ``COMPLETE``.

WHAT THIS CONVICTED, 2026-09-19, and it is the census's own COMPLETE rows rather than a hypothetical.
motronics' SANCTIONED ``--extra pareto --extra dev`` -- the row `_synccensus_rows.py` calls "the
sanctioned spelling" -- strands SEVEN distributions at collection: cadquery-ocp-novtk, ezdxf,
meshio, motronics-native, opencv-python-headless, pillow, wdg-lab. wdg-lab's CI ``extras: 'dev'``
strands diskcache, fastapi, httpx and pandas. Both scores are RIGHT at their own question: the
runner survives both, and neither repo can collect.

SHARPEST OF ALL, AND IT IS A CORRECTION TO THE SIBLING ROW: that row names
``--extra all --extra dev --extra img-to-cad`` as "the incantation that actually restored the box".
It leaves the runner whole and STILL strands ``pillow`` -- declared only in a ``tooldrivers`` extra
that no recorded incantation names. There is no selection in motronics that collects its own tests.

THE JOIN IS IMPORT NAME TO DISTRIBUTION NAME, AND THEY DIFFER. ``cv2`` is ``opencv-python``, ``OCP``
is ``cadquery-ocp``, ``PIL`` is ``pillow``, ``yaml`` is ``pyyaml``, and all four are live here.
**RESOLVING THAT FROM INSTALLED METADATA WAS MEASURED AND REFUSED.**
``importlib.metadata.packages_distributions()`` in this repo's venv knew 22 import names and
answered ``None`` for every interesting case -- cv2, OCP, PIL, yaml, ezdxf, meshio, scipy,
matplotlib. Worse than incomplete, it is the wrong INSTRUMENT: the question is what a prune WOULD
do, and an already-pruned environment answers that a distribution does not exist. So resolution is
TEXT, in a fixed order, and the residue is REPORTED rather than dropped:

1. DECLARED -- :func:`~lab_commons.dev.syncscope.canon` of the import name is a distribution this
   manifest names. Covers numpy, pytest, pydantic, matplotlib, structlog and the family's own
   underscore/hyphen pairs (``wdg_lab`` / ``wdg-lab``, ``motronics_native`` / ``motronics-native``).
2. :data:`ALIASES` -- the NAMED SET where neither name can be derived from the other. Every row is
   reached by the live family scan; an alias nothing uses is a waiver nothing uses.
3. LOCAL -- a ``<name>.py`` or ``<name>/`` exists in the checkout, so the import resolves off
   ``sys.path`` and no sync can take it away. Third deliberately: a repo's own source package is
   BOTH its distribution and a directory, and pruning the distribution DOES break it.
4. UNRESOLVED -- reported BY NAME. A transitive dependency no manifest declares cannot be settled
   from a manifest, because whether it survives is a property of the LOCK graph. Never guessed
   either way: "assume present" agrees with every selection and "assume absent" convicts the family.
   **AUDITED THE OTHER WAY**: a residue its own manifest can supply is a SHORT TABLE, and refused.

A CONDITIONAL IMPORT DEGRADES AND IS NOT A STRAND. A ``try/except ImportError``, an
``if TYPE_CHECKING:`` and a module-scope ``pytest.importorskip`` all leave the module collectable,
and convicting them would red every optional integration here -- measured: it is the difference
between ``OCP`` in wdg-lab (guarded, DEGRADES) and in motronics (bare, ERRORS). An import inside a
function or class body does not execute at collection and is not this module's subject.

**A SKIP MARK IS NOT A GUARD, AND THE BRIEF THAT COMMISSIONED THIS SAID IT WAS.** ``pytestmark =
pytest.mark.skipif(...)`` beside a module-scope ``import cv2`` still errors: the mark object is
CREATED BY THE MODULE BODY, so the body must run before pytest can read it, and the import runs
first. Marks are therefore not consulted, and a reader that treated them as guards would score the
loudest real hazard in the family as safe.

WHAT THIS CANNOT SEE: a ``conftest.py`` ``collect_ignore`` or an ``--ignore`` keeping a module out of
collection; an import performed through ``importlib`` or a string; a distribution that installs but
fails to LOAD; and whether an UNRESOLVED name survives. Nothing here installs, syncs or prunes, and
nothing imports a scanned file -- :mod:`~lab_commons.dev.testfacts`'s refusal, for its reason.
"""

from __future__ import annotations

import ast
import subprocess
import sys
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Final

from lab_commons.dev.syncscope import Selection, canon, survivors

__all__ = [
    'ALIASES',
    'GUARD_EXCEPTIONS',
    'SKIP_DIRS',
    'STDLIB',
    'Fate',
    'FileReading',
    'Reach',
    'Use',
    'fate',
    'local_modules',
    'reach',
    'read_imports',
    'resolve',
    'tree_texts',
]

#: Import names whose distribution cannot be derived from the spelling, with EVERY distribution that
#: can supply each. A SET per name and not a single answer, and that is a MEASUREMENT rather than
#: caution: motronics declares ``cadquery-ocp-novtk`` and ``opencv-python-headless``, so a one-to-one
#: ``cv2 -> opencv-python`` map read that repo as stranding two distributions it never declared. A
#: build variant is a different distribution supplying the same import.
#:
#: Only candidates the manifest DECLARES are used -- the same rule as a name that needs no alias --
#: so an aliased import nothing declares answers UNRESOLVED instead of being convicted on a guess.
#: Every row here is reached by the live family scan; an alias nothing uses is a waiver nothing uses.
ALIASES: Final[dict[str, frozenset[str]]] = {
    'OCP': frozenset({'cadquery-ocp', 'cadquery-ocp-novtk'}),
    'PIL': frozenset({'pillow'}),
    'cv2': frozenset({'opencv-contrib-python', 'opencv-python', 'opencv-python-headless'}),
    'pdfminer': frozenset({'pdfminer-six'}),
    'pywintypes': frozenset({'pywin32'}),
    'win32com': frozenset({'pywin32'}),
    'yaml': frozenset({'pyyaml'}),
}

#: What an ``except`` clause must name for its ``try`` body to count as a GUARD. A bare ``except:``
#: qualifies too. Anything narrower -- ``except ValueError`` around an import -- does NOT make the
#: import conditional, and reading every ``try`` as a guard is how a reader stops convicting.
GUARD_EXCEPTIONS: Final[frozenset[str]] = frozenset(
    {'BaseException', 'Exception', 'ImportError', 'ModuleNotFoundError'}
)

#: Directory names never descended when looking for LOCAL module names. ``.venv`` is the important
#: one and it is the reason this is declared: an installed distribution sits under it, so a walk
#: that entered it would call every third-party import LOCAL and find nothing forever.
SKIP_DIRS: Final[frozenset[str]] = frozenset(
    {'.claude', '.git', '.venv', '__pycache__', 'attic', 'node_modules', 'target'}
)

#: The standard library of the interpreter doing the reading. An import of one of these is supplied
#: by python itself and no sync moves it.
STDLIB: Final[frozenset[str]] = frozenset(sys.stdlib_module_names)

#: The one pytest verb that turns a missing distribution into a SKIP instead of a collection error.
_IMPORTORSKIP: Final = 'importorskip'

#: What :func:`resolve` answers for an import no sync can take away -- stdlib, or a file in the
#: checkout. Distinct from ``None``, which means no text settled it: the two have opposite remedies.
_SUPPLIED: Final[frozenset[str]] = frozenset()


class Fate(Enum):
    """What a selection does to one import at COLLECTION time. Four, and two of them are not failures."""

    ERRORS = 'errors'
    DEGRADES = 'degrades'
    SURVIVES = 'survives'
    UNRESOLVED = 'unresolved'


@dataclass(frozen=True, slots=True)
class Use:
    """One import name reached at MODULE SCOPE, with the line it is on and whether it is guarded."""

    name: str
    line: int
    guarded: bool


@dataclass(frozen=True, slots=True)
class FileReading:
    """Every module-scope import one test file performs. ``parse_error`` is a fact, not a drop.

    A file that does not parse is REPORTED unreadable rather than skipped, because skipping it
    shrinks the population every count below is taken over.
    """

    name: str
    uses: tuple[Use, ...]
    parse_error: bool = False

    @property
    def hard(self) -> tuple[Use, ...]:
        """The uses that execute unconditionally, which are the only ones that can abort collection."""
        return tuple(use for use in self.uses if not use.guarded)


@dataclass(frozen=True, slots=True)
class Reach:
    """What a selection leaves a TEST TREE able to do, as distribution sets plus the sites that name them.

    *errors* is the answer; *unresolved* is the honest residue; *files* is the FLOOR's subject.
    """

    errors: frozenset[str]
    degrades: frozenset[str]
    unresolved: frozenset[str]
    files: int
    sites: tuple[str, ...]


def tree_texts(root: Path, prefix: str, *, at_head: bool) -> dict[str, str]:
    """Every ``test_*.py`` under *prefix*, keyed by repo-relative path. One git call, not one per file.

    MEASURED 2026-09-19 against motronics' 2632 test files: ``ls-tree`` plus a single
    ``cat-file --batch`` reads 26 MB in 0.93 s, where a per-file ``git show`` is 2632 processes. A
    sibling repo is read at ``HEAD`` for the same reason the door census does it -- a lane's
    half-finished edit over there must not turn THIS repo red.
    """
    if not at_head:
        base = root / prefix
        return {
            str(path.relative_to(root)).replace('\\', '/'): path.read_text('utf-8', errors='replace')
            for path in sorted(base.rglob('test_*.py'))
        }
    listing = _git(root, 'ls-tree', '-r', 'HEAD', '--format=%(objectname) %(path)', prefix)
    entries = [line.split(' ', 1) for line in listing.splitlines() if ' ' in line]
    wanted = [(sha, path) for sha, path in entries if _is_test_path(path)]
    if not wanted:
        return {}
    blob = subprocess.run(
        ['git', '-C', str(root), 'cat-file', '--batch'],  # noqa: S607
        input='\n'.join(sha for sha, _ in wanted).encode(),
        capture_output=True,
        check=True,
    ).stdout
    return dict(zip([path for _, path in wanted], _split_batch(blob), strict=True))


def _is_test_path(path: str) -> bool:
    return path.endswith('.py') and path.rsplit('/', 1)[-1].startswith('test_')


def _split_batch(blob: bytes) -> list[str]:
    """Cut ``git cat-file --batch``'s output into contents: a ``<sha> blob <size>`` header, then bytes."""
    out: list[str] = []
    at = 0
    while at < len(blob):
        end = blob.index(b'\n', at)
        size = int(blob[at:end].split()[-1])
        out.append(blob[end + 1 : end + 1 + size].decode('utf-8', errors='replace'))
        at = end + 2 + size
    return out


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        ['git', '-C', str(root), *args],  # noqa: S607
        capture_output=True,
        text=True,
        check=True,
    ).stdout


def local_modules(root: Path, *, skip: frozenset[str] = SKIP_DIRS) -> frozenset[str]:
    """Every top-level name importable from the CHECKOUT itself -- a ``<name>.py`` or a ``<name>/``.

    Anywhere in the tree rather than at the roots pytest happens to prepend, because ``rootdir``
    insertion depends on which files carry an ``__init__.py`` and getting that wrong turns a test
    helper into a phantom missing distribution. Wider than the truth in the SAFE direction: this set
    only ever removes a name from the stranded answer, and rule 1 already claimed the declared ones.
    """
    names: set[str] = set()
    stack = [root]
    while stack:
        for path in stack.pop().iterdir():
            if path.name in skip:
                continue
            if path.is_dir():
                stack.append(path)
                names.add(path.name)
            elif path.suffix == '.py':
                names.add(path.stem)
    return frozenset(names)


def read_imports(name: str, text: str) -> FileReading:
    """Every module-scope import in one test file, PARSED and never imported.

    A ``def`` or ``class`` body is not descended: it does not run at collection, so an import inside
    one cannot abort it. ``try``/``if``/``with`` ARE descended, because they do.
    """
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        return FileReading(name=name, uses=(), parse_error=True)
    uses: list[Use] = []
    _walk(tree.body, uses, guarded=False)
    return FileReading(name=name, uses=tuple(uses))


def _walk(body: list[ast.stmt], out: list[Use], *, guarded: bool) -> None:
    for node in body:
        if isinstance(node, ast.Import):
            out += [Use(alias.name.split('.')[0], node.lineno, guarded) for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            if not node.level and node.module:
                out.append(Use(node.module.split('.')[0], node.lineno, guarded))
        elif isinstance(node, ast.Try):
            inner = guarded or any(_catches_import(handler) for handler in node.handlers)
            _walk(node.body, out, guarded=inner)
            _walk(node.orelse, out, guarded=inner)
            for handler in node.handlers:
                _walk(handler.body, out, guarded=True)
            _walk(node.finalbody, out, guarded=guarded)
        elif isinstance(node, ast.If):
            _walk(node.body, out, guarded=guarded or _is_type_checking(node.test))
            _walk(node.orelse, out, guarded=guarded)
        elif isinstance(node, ast.With):
            _walk(node.body, out, guarded=guarded)
        else:
            out += [Use(found, node.lineno, guarded=True) for found in _importorskips(node)]


def _catches_import(handler: ast.ExceptHandler) -> bool:
    """A bare ``except``, or one naming something in :data:`GUARD_EXCEPTIONS`, guards an import."""
    caught = handler.type
    if caught is None:
        return True
    parts = caught.elts if isinstance(caught, ast.Tuple) else [caught]
    return any(isinstance(part, ast.Name) and part.id in GUARD_EXCEPTIONS for part in parts)


def _is_type_checking(test: ast.expr) -> bool:
    if isinstance(test, ast.Name):
        return test.id == 'TYPE_CHECKING'
    return isinstance(test, ast.Attribute) and test.attr == 'TYPE_CHECKING'


def _importorskips(node: ast.stmt) -> list[str]:
    """Module names a ``pytest.importorskip('x')`` at module scope asks for -- a DEGRADE, not a strand."""
    found: list[str] = []
    for inner in ast.walk(node):
        if not isinstance(inner, ast.Call) or not inner.args:
            continue
        func = inner.func
        named = func.attr if isinstance(func, ast.Attribute) else func.id if isinstance(func, ast.Name) else ''
        first = inner.args[0]
        if named == _IMPORTORSKIP and isinstance(first, ast.Constant) and isinstance(first.value, str):
            found.append(first.value.split('.')[0])
    return found


def resolve(name: str, declared: frozenset[str], local: frozenset[str]) -> frozenset[str] | None:
    """Which DECLARED distributions could supply this import: a set, empty for unprunable, ``None`` for unsettled.

    Three answers and not two. ``None`` is an ANSWER the caller must carry: a miss that fell back to
    "assume it survives" would make the scan agree with every selection, and one that fell back to
    "assume it is missing" would convict every transitive dependency in the family. The EMPTY set is
    the third -- stdlib, or a file in this checkout -- and it is not a miss.
    """
    if name in STDLIB:
        return _SUPPLIED
    spelled = canon(name)
    if spelled in declared:
        return frozenset({spelled})
    suppliers = ALIASES.get(name, frozenset()) & declared
    if suppliers:
        return suppliers
    return _SUPPLIED if name in local else None


def fate(use: Use, suppliers: frozenset[str] | None, left: frozenset[str]) -> Fate:
    """What ONE import does under a surviving set. The whole branch table, in one place and reusable.

    Order matters and is the module's argument in four lines: an unsettled name is never guessed; an
    import nothing can prune SURVIVES; ANY surviving supplier is enough, because one build variant
    of a distribution satisfies the import as well as another; and only then does the guard decide
    between a skip and a collection error. A guarded use of a surviving supplier is a SURVIVOR.
    """
    if suppliers is None:
        return Fate.UNRESOLVED
    if not suppliers or suppliers & left:
        return Fate.SURVIVES
    return Fate.DEGRADES if use.guarded else Fate.ERRORS


def reach(
    readings: dict[str, FileReading],
    chosen: Selection,
    manifest: str,
    declared: frozenset[str],
    local: frozenset[str],
) -> Reach:
    """THE JOIN. Which distributions a selection strands AT COLLECTION, and which merely degrade.

    Pure over its arguments -- the texts, the selection and the two name sets all arrive from the
    caller -- so a planted control drives THIS function rather than a second copy of it.
    """
    left = survivors(chosen, manifest)
    errors: set[str] = set()
    degrades: set[str] = set()
    unresolved: set[str] = set()
    sites: set[str] = set()
    for reading in readings.values():
        for use in reading.uses:
            suppliers = resolve(use.name, declared, local)
            verdict = fate(use, suppliers, left)
            if verdict is Fate.UNRESOLVED:
                unresolved.add(use.name)
            elif verdict is Fate.DEGRADES:
                degrades |= suppliers or frozenset()
            elif verdict is Fate.ERRORS:
                errors |= suppliers or frozenset()
                named = '/'.join(sorted(suppliers or ()))
                sites.add(f'{reading.name}:{use.line}: {use.name} -> {named}')
    return Reach(
        errors=frozenset(errors),
        degrades=frozenset(degrades - errors),
        unresolved=frozenset(unresolved),
        files=len(readings),
        sites=tuple(sorted(sites)),
    )
