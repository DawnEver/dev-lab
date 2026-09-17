"""Loading a module BY PATH as a CALL rather than as an import -- once per file, for good.

Migrated 2026-09-17 from motronics-studio's ``scripts/gate/_by_path.py``. It moves whole: every
sentence below is about ``importlib``, ``sys.modules`` and ``dataclasses``, and not one of them is
about any repository. The only thing left behind is the guard that scans ONE tree for competing
loaders, which is that repo's census of its own ``scripts/`` and stays there.

WHY A CALL AND NOT AN IMPORT. A directory of standalone mechanisms -- ``scripts/``, a test tree with
no ``__init__.py`` -- is not a package, so a module in it is reachable only after ``sys.path``
surgery, and an import placed after that surgery is either an E402 (module scope) or a PLC0415
(function scope). Both are suppressible and neither should be suppressed: the migrated file's own
caller carried SEVEN identical PLC0415 waivers reading "loaded by path". Seven identical waivers for
one recurring need name a MISSING MECHANISM, not seven exceptions. A function call has no import
statement to place and nothing to suppress.

IT DOES NOT TOUCH ``sys.path``. The seven sites each prepended a directory that then stayed there
for the life of the process, so the caller's ``sys.path`` grew a duplicate entry per call and any
later plain import could resolve against a directory some unrelated function had inserted. An
absolute file path answers the question the insert was asked for, and answers only that.

ONE OBJECT PER FILE. A by-path load that ran twice would give two module objects with two copies of
module state -- two caches, two lazily-built singletons, two of whatever the module happens to hold.
The cache is keyed by RESOLVED path, so two spellings of one file are one module; and an
already-imported module whose ``__file__`` IS this file is ADOPTED rather than shadowed, so a caller
that reached the module by an ordinary import and one that reached it here hold the same object.

ADOPTION IS BY FILE, NOT BY NAME, and the difference was a live defect rather than a refinement.
Keyed by the requested NAME while the cache beside it was keyed by the PATH, the promise above held
only for a caller that happened to guess the name the other route had used. MEASURED 2026-09-05: a
policy module imported by the test runner as ``tests.heavy_policy`` and loaded here under the stem
``heavy_policy`` -- adoption missed, the process held TWO policies, the runner partitioned the suite
by one while collection partitioned it by the other, and the test that patched "the" policy object
was patching the copy the runner does not read.

WHEN TWO NAMES ALREADY POINT AT ONE FILE the split has already happened and neither choice can undo
it, so the tie-break is DECLARED rather than incidental: an exact name match first, then the
PACKAGE-qualified name, because that is the one an ordinary import produced and therefore the one
every other importer in the process is holding.

REGISTERED IN ``sys.modules`` BEFORE ``exec_module``, and it is not optional. ``dataclasses``
resolves a field's annotation through ``sys.modules.get(cls.__module__).__dict__``; for a module
loaded by path and never registered, that lookup returns ``None`` and the class body dies with
``'NoneType' object has no attribute '__dict__'``. MEASURED 2026-09-04: a by-path helper that omitted
the line took a whole test file down at COLLECTION -- twelve errors from one cause.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

__all__ = ['load']

#: Resolved path -> the one module object for it. NOT ``sys.modules``, because that registry is
#: keyed by NAME and two trees may hold two files of one name; this is keyed by the file itself.
_LOADED: dict[Path, ModuleType] = {}


def _is_this_file(module: ModuleType | None, resolved: Path) -> bool:
    """Whether *module* was loaded FROM *resolved*. A module with no ``__file__`` never is."""
    if module is None:
        return False
    origin = getattr(module, '__file__', None)
    if origin is None:
        return False
    try:
        return Path(origin).resolve() == resolved
    except OSError:
        # An unresolvable __file__ is not this file. Carries NO coverage exemption: this repo
        # reads one as a declaration owing a reason, and "hard to reach" is not a reason -- the
        # branch is either reachable and testable, or it is dead code.
        return False


def _adopted(name: str, resolved: Path) -> ModuleType | None:
    """An already-imported module that IS this file, or ``None`` -- so the two routes never diverge.

    Searched by FILE rather than by the requested name; see the module docstring for the defect that
    cost. The exact name is tried first because it is the common case and costs one dict lookup, and
    only a miss pays for the scan.
    """
    exact = sys.modules.get(name)
    if _is_this_file(exact, resolved):
        return exact
    matches = sorted(
        (other for other, module in list(sys.modules.items()) if _is_this_file(module, resolved)),
        # The package-qualified name wins: it is what an ordinary import produced, so it is the
        # object every other importer in this process already holds.
        key=lambda other: (0 if '.' in other else 1, other),
    )
    return sys.modules[matches[0]] if matches else None


def load(path: Path | str, name: str | None = None) -> ModuleType:
    """The module at *path*, executed AT MOST ONCE per file for the life of the process.

    Args:
        path: the file to load. Resolved, so two spellings of one file are one module.
        name: the name to register it under. Defaults to the file STEM, which is the name an
            ordinary import would have used -- so the module's ``__name__``, its ``sys.modules`` key
            and its dataclasses all read as if the directory had been a package.

    Returns:
        The one module object for that file.

    Raises:
        ImportError: no import machinery claims the path.

    """
    resolved = Path(path).resolve()
    loaded = _LOADED.get(resolved)
    if loaded is not None:
        return loaded

    module_name = name or resolved.stem
    adopted = _adopted(module_name, resolved)
    if adopted is not None:
        _LOADED[resolved] = adopted
        return adopted

    spec = importlib.util.spec_from_file_location(module_name, resolved)
    if spec is None or spec.loader is None:
        msg = f'cannot load {resolved} by path -- no import machinery claims it'
        raise ImportError(msg)
    module = importlib.util.module_from_spec(spec)
    # BEFORE execution: see the module docstring. A dataclass in the loaded file needs its own
    # module in ``sys.modules`` while its class body runs.
    sys.modules[module_name] = module
    _LOADED[resolved] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        # A HALF-EXECUTED MODULE IS NOT A MODULE. Leaving it cached would hand the next caller an
        # object whose top half ran, which is worse than the failure it hides.
        sys.modules.pop(module_name, None)
        _LOADED.pop(resolved, None)
        raise
    return module
