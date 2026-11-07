"""The ``pytest11`` entry point that runs dev-lab's always-on family rows in every repo installing it.

A SHIM OUTSIDE ``dev_lab.dev`` ON PURPOSE, and it must import nothing from dev_lab at load. pytest
loads a ``pytest11`` plugin BEFORE pytest-cov starts measuring, so every module the plugin imports is
imported unmeasured and stays unmeasured for the session. The rows live in
:mod:`dev_lab.dev.famtests.alwayson`, and importing it at load pulls ``dev_lab.dev``'s package
``__init__`` with 30-odd modules behind it: dev-lab's own coverage read 18% against its 86% bar
(2026-11-07). So this module defers the import to the collection hook, which runs after measuring starts.
"""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pytest

__all__ = ['pytest_collection_modifyitems']


def pytest_collection_modifyitems(session: pytest.Session, config: pytest.Config, items: list[pytest.Item]) -> None:
    """Append the always-on rows (:func:`dev_lab.dev.famtests.alwayson.append_rows`)."""
    importlib.import_module('dev_lab.dev.famtests.alwayson').append_rows(session, config, items)
