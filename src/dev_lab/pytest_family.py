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

__all__ = ['pytest_collection_modifyitems', 'pytest_configure', 'pytest_fixture_setup']


@pytest.hookimpl(tryfirst=True)
def pytest_configure(config: pytest.Config) -> None:
    """Put pytest's base temp in a swept system-temp entry (:func:`dev_lab.dev.testtemp.configure`) first."""
    importlib.import_module('dev_lab.dev.testtemp').configure(config)


@pytest.hookimpl(wrapper=True)
def pytest_fixture_setup(fixturedef: pytest.FixtureDef[object]) -> object:
    """Make every ``pytester`` sandbox its own pytest root (:func:`dev_lab.dev.testtemp.bound_sandbox`)."""
    value = yield
    if fixturedef.argname == 'pytester':
        importlib.import_module('dev_lab.dev.testtemp').bound_sandbox(value)
    return value


@pytest.hookimpl(trylast=True)
def pytest_collection_modifyitems(session: pytest.Session, config: pytest.Config, items: list[pytest.Item]) -> None:
    """Append the always-on rows (:func:`dev_lab.dev.famtests.alwayson.append_rows`)."""
    importlib.import_module('dev_lab.dev.famtests.alwayson').append_rows(session, config, items)
