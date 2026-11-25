"""Single-record machine fixtures are JSONL (ruling R3), holding the values their JSON held.

Each pin is the sha256 of the canonical value (sorted keys, compact) measured on the ``.json`` this
``.jsonl`` replaced (2026-11-24): a moved value moves the hash. A deliberate fixture change updates its pin.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

_TESTS = Path(__file__).parent
_ROLES = 'cd73598d73f042b8d6b055cff4c51e4c38cbd7072d4e9689c4da3032f22503c5'
#: Re-pinned 2026-11-25: the en-us migration (US-SPELLING-IS-CHECKED) renamed the record's empty ``artefact`` key
#: to ``artifact``; no other value moved.
_SCHEMA_1 = '7395698dd4367a314f0f92b21847af00a68ae90ec54aa128fe4d15ce8c4fadae'
_PINS = {
    '_hpc_fixtures/forge-run-schema1-2026-10-17.jsonl': _SCHEMA_1,
    '_render_fixtures/gitea_review/roles.jsonl': _ROLES,
    '_render_fixtures/github_overrides/roles.jsonl': _ROLES,
    '_render_fixtures/github_plain/roles.jsonl': _ROLES,
}


@pytest.mark.parametrize('rel', sorted(_PINS))
def test_the_record_is_one_line_holding_the_value_the_json_held(rel: str) -> None:
    lines = (_TESTS / rel).read_text(encoding='utf-8').splitlines()
    assert len(lines) == 1, f'{rel} is ONE JSONL record'
    canonical = json.dumps(json.loads(lines[0]), sort_keys=True, separators=(',', ':'))
    assert hashlib.sha256(canonical.encode()).hexdigest() == _PINS[rel]


def test_no_json_fixture_is_left_in_these_trees() -> None:
    for tree in ('_hpc_fixtures', '_rem_fixtures', '_render_fixtures'):
        assert not list((_TESTS / tree).rglob('*.json')), tree
