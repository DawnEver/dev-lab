"""The by-path loader, driven by EXECUTING real modules rather than by inspecting the loader.

Every arm here writes an actual ``.py`` file and loads it, because all four properties the module
claims are about what happens WHEN THE FILE RUNS -- module state, ``sys.modules`` registration during
the class body, and what is left behind when execution raises. A test that asserted on the returned
object's attributes without ever having a second load, a second spelling or a failure could pass
against a loader that re-executed every time.

THE SIDE EFFECT IS THE INSTRUMENT. Each planted module appends to a list it finds in
``builtins``, so "ran once" is a COUNT this test reads rather than an identity check it infers --
two module objects for one file would be indistinguishable from one if only ``is`` were asked, and
the reverse is also true of a cache that returned the same object while re-executing the file.
"""

from __future__ import annotations

import builtins
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

from lab_commons.dev import bypath
from lab_commons.dev.bypath import load

#: The name the planted modules append to. Held on ``builtins`` because a by-path module has no
#: import route back to this test file.
_LEDGER = '_bypath_test_ledger'


@pytest.fixture(autouse=True)
def _clean_process_state() -> Iterator[None]:
    """Leave ``sys.modules`` and the loader cache exactly as they were found.

    A loader whose whole subject is process-global state cannot be tested without owning the undo:
    without this, one arm's planted module is another arm's mysteriously-already-loaded one, which
    is precisely the defect class the module under test exists to remove.
    """
    before_modules = dict(sys.modules)
    before_cache = dict(bypath._LOADED)
    setattr(builtins, _LEDGER, [])
    try:
        yield
    finally:
        delattr(builtins, _LEDGER)
        bypath._LOADED.clear()
        bypath._LOADED.update(before_cache)
        sys.modules.clear()
        sys.modules.update(before_modules)


def _ledger() -> list[str]:
    """Every execution the planted modules have recorded so far."""
    return getattr(builtins, _LEDGER)


def _plant(directory: Path, stem: str, body: str = '') -> Path:
    """A module that records its own execution, plus whatever *body* adds."""
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f'{stem}.py'
    path.write_text(
        f'import builtins\nbuiltins.{_LEDGER}.append({stem!r})\nSTATE = []\n{body}\n',
        encoding='utf-8',
    )
    return path


def test_a_loaded_module_runs_and_is_named_after_its_stem(tmp_path: Path) -> None:
    """THE FLOOR: the loader loads at all, and the name matches what an ordinary import would use."""
    path = _plant(tmp_path, 'harness')
    module = load(path)
    assert _ledger() == ['harness']
    assert module.__name__ == 'harness'
    assert sys.modules['harness'] is module


def test_loading_the_same_file_twice_EXECUTES_IT_ONCE(tmp_path: Path) -> None:
    """One object per file, read off the execution COUNT rather than off object identity alone."""
    path = _plant(tmp_path, 'harness')
    first = load(path)
    first.STATE.append('written by the first caller')
    second = load(path)
    assert _ledger() == ['harness']
    assert second is first
    assert second.STATE == ['written by the first caller']


def test_two_SPELLINGS_of_one_file_are_one_module(tmp_path: Path) -> None:
    """The cache is keyed by RESOLVED path, so a relative detour is not a second module."""
    path = _plant(tmp_path, 'harness')
    detour = path.parent / 'sub' / '..' / 'harness.py'
    (path.parent / 'sub').mkdir()
    assert load(detour) is load(path)
    assert _ledger() == ['harness']


def test_a_module_ALREADY_IMPORTED_BY_NAME_is_adopted_rather_than_shadowed(tmp_path: Path) -> None:
    """The measured 2026-09-05 defect: two objects for one file, and the patch landing on the wrong one."""
    package = tmp_path / 'pkg'
    package.mkdir()
    (package / '__init__.py').write_text('', encoding='utf-8')
    path = _plant(package, 'policy')
    sys.path.insert(0, str(tmp_path))
    try:
        imported = __import__('pkg.policy', fromlist=['policy'])
        imported.STATE.append('set through the package route')
        adopted = load(path, 'policy')
    finally:
        sys.path.remove(str(tmp_path))
    assert adopted is imported
    assert adopted.STATE == ['set through the package route']
    assert _ledger() == ['policy']


def test_adoption_prefers_the_PACKAGE_QUALIFIED_name_when_two_already_point_at_one_file(tmp_path: Path) -> None:
    """The declared tie-break: the object every other importer in the process is holding wins."""
    path = _plant(tmp_path, 'harness')
    module = load(path)
    sys.modules['pkg.harness'] = module
    bypath._LOADED.clear()
    assert load(path, 'nobody_used_this_name') is module


def test_a_module_whose_FILE_DIFFERS_is_not_adopted_so_adoption_is_not_a_name_match(tmp_path: Path) -> None:
    """THE PLANTED CONTROL: a same-named module from a DIFFERENT file must not be handed back.

    This is the arm that fails if adoption regresses to the by-NAME keying the module docstring
    records as a live defect -- and it is the direction that keying gets wrong.
    """
    mine = _plant(tmp_path / 'a', 'harness')
    theirs = _plant(tmp_path / 'b', 'harness')
    first = load(theirs)
    second = load(mine)
    assert second is not first
    assert second.__file__ is not None
    assert Path(second.__file__).resolve() == mine.resolve()
    assert _ledger() == ['harness', 'harness']


def test_a_dataclass_in_the_loaded_file_resolves_its_annotations(tmp_path: Path) -> None:
    """THE ``sys.modules``-BEFORE-``exec_module`` ARM, planted as the construct that needs it.

    Without the registration the class body dies with ``'NoneType' object has no attribute
    '__dict__'`` -- a failure at LOAD time that takes a whole collection down, which is how it was
    measured on 2026-09-04.
    """
    path = _plant(
        tmp_path,
        'holder',
        body='from dataclasses import dataclass\n\n@dataclass\nclass Row:\n    name: str = "x"\n',
    )
    assert load(path).Row().name == 'x'


def test_a_module_that_RAISES_leaves_nothing_cached_and_nothing_registered(tmp_path: Path) -> None:
    """A half-executed module is not a module, in BOTH registries, and the error still propagates."""
    path = _plant(tmp_path, 'broken', body='raise RuntimeError("the top half ran")')
    with pytest.raises(RuntimeError, match='the top half ran'):
        load(path)
    assert 'broken' not in sys.modules
    assert path.resolve() not in bypath._LOADED
    assert _ledger() == ['broken']


def test_a_failed_load_can_be_RETRIED_once_the_file_is_fixed(tmp_path: Path) -> None:
    """Why the cleanup above matters to a caller: a cached failure would poison the rest of the run."""
    path = _plant(tmp_path, 'broken', body='raise RuntimeError("the top half ran")')
    with pytest.raises(RuntimeError, match='the top half ran'):
        load(path)
    _plant(tmp_path, 'broken')
    assert load(path).STATE == []


def test_loading_does_not_touch_sys_path(tmp_path: Path) -> None:
    """The second defect the call replaces: seven inserts that outlived every call that made them."""
    before = list(sys.path)
    load(_plant(tmp_path, 'harness'))
    assert sys.path == before


def test_a_path_that_is_not_a_module_raises_ImportError(tmp_path: Path) -> None:
    """A directory claims no loader, and the refusal names the path rather than failing later."""
    with pytest.raises(ImportError, match='no import machinery claims it'):
        load(tmp_path)
