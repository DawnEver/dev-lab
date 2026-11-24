"""Machine fixtures are never ``.json`` (ruling R3): the trees that held them keep none.

The single-record JSONL fixtures this file pinned became in-code values (H2, 2026-11-24): the schema-1 forge run in
``test_dev_forgerun``, the render fixtures' role bindings in each ``tests/_render_fixtures/<name>/fixture.py``.
"""

from __future__ import annotations

from pathlib import Path

_TESTS = Path(__file__).parent


def test_no_json_fixture_is_left_in_these_trees() -> None:
    for tree in ('_hpc_fixtures', '_rem_fixtures', '_render_fixtures'):
        assert not list((_TESTS / tree).rglob('*.json')), tree
