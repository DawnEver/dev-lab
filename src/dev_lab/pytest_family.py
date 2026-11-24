"""The ``pytest11`` entry point that runs dev-lab's always-on family rows in every repo installing it.

It also puts every test temp dir in a swept system-temp entry (:mod:`dev_lab.dev.testtemp`).

A SHIM OUTSIDE ``dev_lab.dev`` ON PURPOSE, and it imports nothing from dev_lab at load. pytest
loads a ``pytest11`` plugin BEFORE pytest-cov starts measuring, so a module imported at plugin load
has its module-level lines executed unmeasured. The rows live in
:mod:`dev_lab.dev.famtests.alwayson`, and importing it at load pulls ``dev_lab.dev``'s package
``__init__`` with 30-odd modules behind it, every one of them then reading as under-covered in
dev-lab's own runs. So this module defers the import to the collection hook, after measuring starts.
"""

from __future__ import annotations

import importlib

import pytest

__all__ = [
    'pytest_collection_modifyitems',
    'pytest_configure',
    'pytest_fixture_setup',
    'pytest_runtest_call',
    'pytest_sessionfinish',
]

#: The base temp entry this session made, which :func:`pytest_sessionfinish` reclaims.
_MADE: pytest.StashKey[object] = pytest.StashKey()


@pytest.hookimpl(tryfirst=True)
def pytest_configure(config: pytest.Config) -> None:
    """Put pytest's base temp in a swept system-temp entry (:func:`dev_lab.dev.testtemp.configure`) first."""
    config.stash[_MADE] = importlib.import_module('dev_lab.dev.testtemp').configure(config)
    config.addinivalue_line('markers', 'needs(*names): what the test needs (dev_lab.dev.needs); missing FAILS')


@pytest.hookimpl(trylast=True)
def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    """Reclaim the base temp entry this session made (:func:`dev_lab.dev.testtemp.release`)."""
    config = session.config
    importlib.import_module('dev_lab.dev.testtemp').release(
        config.stash.get(_MADE, None),
        passed=exitstatus in {pytest.ExitCode.OK, pytest.ExitCode.NO_TESTS_COLLECTED},
        policy=str(config.getini('tmp_path_retention_policy')),
    )


@pytest.hookimpl(wrapper=True)
def pytest_fixture_setup(fixturedef: pytest.FixtureDef[object]) -> object:
    """Make every ``pytester`` sandbox its own pytest root (:func:`dev_lab.dev.testtemp.bound_sandbox`)."""
    value = yield
    if fixturedef.argname == 'pytester':
        importlib.import_module('dev_lab.dev.testtemp').bound_sandbox(value)
    return value


@pytest.hookimpl(trylast=True)
def pytest_collection_modifyitems(session: pytest.Session, config: pytest.Config, items: list[pytest.Item]) -> None:
    """Refuse an unregistered need and a hand-kept cost marker, plan by the ledger, then append the always-on rows."""
    importlib.import_module('dev_lab.dev.needs').refuse_unregistered(items, root=config.rootpath)
    cost = importlib.import_module('dev_lab.dev.testcost')
    cost.refuse_cost_markers(items)
    cost.schedule(config, items, budget=cost.read_budget())
    importlib.import_module('dev_lab.dev.famtests.alwayson').append_rows(session, config, items)


@pytest.hookimpl(tryfirst=True)
def pytest_runtest_call(item: pytest.Item) -> None:
    """A need declared on *item* and missing on this host FAILS it by name (:func:`dev_lab.dev.needs.judge`).

    In the CALL phase, so the outcome is ``failed`` -- a red of the test, not a setup error of its fixtures.
    """
    if item.get_closest_marker('needs') is not None:
        module = importlib.import_module('dev_lab.dev.needs')
        module.judge(item, root=item.config.rootpath, host=module.Host.this())
