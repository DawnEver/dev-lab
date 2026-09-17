"""The seam register, driven by REBINDING REAL MODULES and then proving the tree came back.

THE UNDO IS THE SUBJECT, so every arm here compares the live attribute against the object captured
BEFORE the install -- by identity, which is the only comparison a wrapper cannot satisfy. Asserting
on ``restore_all``'s return value alone would pass against a register that popped its list without
calling ``setattr``, and that is exactly the failure the migrated module exists to prevent.

THE PLANTED SUBJECT IS A REAL IMPORTED MODULE, not a stub object, because the defect being guarded
against is specifically about ``from x import y`` having already bound a name into a second
namespace: a test against a bare object has no second namespace and cannot see it.
"""

from __future__ import annotations

import sys
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType

import pytest

from lab_commons.dev import seams as seams_module
from lab_commons.dev.seams import Seam, install, rebind, restore_all, timings

#: The module that DEFINES the measured callable. Source text rather than a fixture object, because
#: the hazard is about a SECOND namespace holding its own binding, which only a real import creates.
_DEFINITION = '''\
def work(n):
    """Do the thing."""
    if n < 0:
        raise ValueError('negative')
    return n * 2
'''

#: The module that did ``from seamdef import work`` -- the site a harness must actually wrap.
_CALLER = '''\
from seamdef import work


def drive(n):
    """Call it through the imported binding."""
    return work(n)
'''


@pytest.fixture(autouse=True)
def _empty_register() -> Iterator[None]:
    """A register left holding somebody else's rebinding is the defect, so each arm starts empty."""
    restore_all()
    seams_module._TOTALS.clear()
    seams_module._CALLS.clear()
    yield
    restore_all()
    seams_module._TOTALS.clear()
    seams_module._CALLS.clear()


@pytest.fixture
def planted(tmp_path: Path) -> Iterator[tuple[ModuleType, ModuleType]]:
    """A DEFINITION module and a CALLER that did ``from definition import work``.

    Two modules because one is the point: the caller holds its own binding, so an instrument that
    wrapped the definition site would measure nothing while looking installed.
    """
    (tmp_path / 'seamdef.py').write_text(_DEFINITION, encoding='utf-8')
    (tmp_path / 'seamcaller.py').write_text(_CALLER, encoding='utf-8')
    sys.path.insert(0, str(tmp_path))
    before = dict(sys.modules)
    try:
        yield __import__('seamdef'), __import__('seamcaller')
    finally:
        sys.path.remove(str(tmp_path))
        sys.modules.clear()
        sys.modules.update(before)


def test_wrapping_the_DEFINITION_leaves_the_caller_measuring_nothing(planted: tuple[ModuleType, ModuleType]) -> None:
    """THE FLOOR FOR THE WHOLE MODULE: it proves the hazard is real before anything claims to fix it.

    Without this arm, every arm below could pass against a harness that measured the wrong site.
    """
    definition, caller = planted
    assert install([Seam('def-site', 'seamdef', 'work')]) == ()
    assert caller.drive(3) == 6
    assert timings() == {}
    assert definition.work(3) == 6
    assert timings()['def-site'].calls == 1


def test_wrapping_the_CALLER_is_what_the_caller_actually_runs(planted: tuple[ModuleType, ModuleType]) -> None:
    """The same install one module over, and now the count follows the call the harness cares about."""
    _definition, caller = planted
    assert install([Seam('call-site', 'seamcaller', 'work')]) == ()
    assert caller.drive(3) == 6
    assert caller.drive(4) == 8
    assert timings()['call-site'].calls == 2
    assert timings()['call-site'].total_s >= 0.0


def test_restore_all_puts_the_ORIGINAL_OBJECT_back_by_identity(planted: tuple[ModuleType, ModuleType]) -> None:
    """The undo, checked the one way a wrapper cannot fake."""
    _definition, caller = planted
    before = caller.work
    install([Seam('call-site', 'seamcaller', 'work')])
    assert caller.work is not before
    assert restore_all() == 1
    assert caller.work is before


def test_restore_all_returns_ZERO_when_nothing_was_installed() -> None:
    """The count is the instrument, so its "nothing" reading has to be distinguishable and correct."""
    assert restore_all() == 0


def test_a_DOUBLE_install_restores_the_PRISTINE_object_and_not_the_first_wrapper(
    planted: tuple[ModuleType, ModuleType],
) -> None:
    """A profile run inside a captured run: the original is captured once and never overwritten."""
    _definition, caller = planted
    before = caller.work
    install([Seam('outer', 'seamcaller', 'work')])
    install([Seam('inner', 'seamcaller', 'work')])
    assert restore_all() == 1
    assert caller.work is before


def test_several_seams_unwind_together_and_the_whole_tree_comes_back(
    planted: tuple[ModuleType, ModuleType],
) -> None:
    """One ``restore_all`` for the whole set, across two different owners."""
    definition, caller = planted
    before = (definition.work, caller.work, caller.drive)
    install([Seam('a', 'seamdef', 'work'), Seam('b', 'seamcaller', 'work'), Seam('c', 'seamcaller', 'drive')])
    assert restore_all() == 3
    assert (definition.work, caller.work, caller.drive) == before


def test_a_MISSING_seam_is_REPORTED_and_the_resolvable_ones_still_install(
    planted: tuple[ModuleType, ModuleType],
) -> None:
    """A profile silently missing its dominant term reads as "that term is free"; this is that floor."""
    _definition, caller = planted
    missing = install(
        [
            Seam('no-such-module', 'seam_does_not_exist', 'work'),
            Seam('no-such-attr', 'seamcaller', 'not_a_name'),
            Seam('no-such-hop', 'seamcaller', 'work.deeper.leaf'),
            Seam('real', 'seamcaller', 'work'),
        ]
    )
    assert missing == ('no-such-module', 'no-such-attr', 'no-such-hop')
    caller.drive(1)
    assert timings()['real'].calls == 1


def test_a_call_that_RAISES_is_still_counted_and_still_raises(planted: tuple[ModuleType, ModuleType]) -> None:
    """A wrapper counting only successes would report a failing seam as free."""
    _definition, caller = planted
    install([Seam('raiser', 'seamcaller', 'work')])
    with pytest.raises(ValueError, match='negative'):
        caller.drive(-1)
    assert timings()['raiser'].calls == 1


def test_the_wrapper_keeps_the_wrapped_NAME_and_DOCSTRING(planted: tuple[ModuleType, ModuleType]) -> None:
    """An instrumented tree must still be readable: a traceback naming ``timed`` helps nobody."""
    _definition, caller = planted
    install([Seam('named', 'seamcaller', 'work')])
    assert caller.work.__name__ == 'work'
    assert caller.work.__doc__ == 'Do the thing.'


def test_rebinding_a_name_that_DOES_NOT_EXIST_is_refused_rather_than_created() -> None:
    """A rebinding with nothing to restore measures a seam nobody calls and cannot be undone."""
    module = ModuleType('empty_for_the_refusal_arm')
    with pytest.raises(AttributeError):
        rebind(module, 'absent', object())
    assert restore_all() == 0


def test_the_module_registers_itself_under_exactly_ONE_name() -> None:
    """The defect the MOVE dissolved, pinned so a later convenience alias cannot bring it back.

    The migrated original forced one object under two ``sys.modules`` keys because it was reached
    both as a top-level script module and as a package attribute; two registers meant two empty undo
    lists and a ``restore_all`` that returned a plausible ``0`` while restoring nothing. A module in
    an installed package has one import spelling, and this says so.
    """
    holders = {name for name, module in list(sys.modules.items()) if module is seams_module}
    assert holders == {'lab_commons.dev.seams'}
