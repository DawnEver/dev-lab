"""A background shell lives longer only by the USER's grant (ruling 2026-11-15): the launch judgement's controls.

Grants are planted as a ``(id, when) -> (subject, seconds)`` table; the real consent store is never read or written.
"""

from __future__ import annotations

import json

from dev_lab.dev.shelllife import ACTION, GRANT_VAR, Grants, admission, granted_bound, subject_of
from dev_lab.ops.consent.actions import ACTIONS

_ID = '0f0e0d0c-0b0a-4908-8706-050403020100'
_NOW = 1_800_000_000.0
_CMD = 'python -m dev_lab.dev.forge watch --stream'


def _grants(table: dict[str, tuple[str, float]]) -> Grants:
    return lambda grant_id, _when: table.get(grant_id)


def test_a_line_within_the_default_is_admitted_and_an_unbounded_one_is_refused() -> None:
    none = _grants({})
    assert admission(f'timeout 50m {_CMD}', _NOW, none) is None
    assert admission(f'LC_ALL=C timeout -k 5 300 {_CMD}', _NOW, none) is None
    refused = admission(_CMD, _NOW, none)
    assert refused is not None
    assert refused.startswith('BACKGROUND-SHELL-IS-BOUNDED:')
    assert 'timeout 50m' in refused


def test_an_agent_written_longer_timeout_without_a_grant_is_refused_naming_the_door() -> None:
    refused = admission(f'timeout 6h {_CMD}', _NOW, _grants({}))
    assert refused is not None
    assert 'dev_lab.ops.consent grant' in refused
    request = json.loads(refused[refused.index('{') : refused.index('}}') + 2])
    assert request == {'action': ACTION, 'subject': subject_of(_CMD), 'params': {'minutes': 360}}
    assert ACTION in ACTIONS


def test_a_grant_admits_only_its_own_command_for_at_most_its_minutes() -> None:
    grants = _grants({_ID: (subject_of(_CMD), 6 * 3600.0)})
    assert admission(f'{GRANT_VAR}={_ID} timeout 6h {_CMD}', _NOW, grants) is None
    assert admission(f'{GRANT_VAR}={_ID} timeout 7h {_CMD}', _NOW, grants) is not None, 'longer than granted'
    assert admission(f'{GRANT_VAR}={_ID} timeout 6h rm -rf x', _NOW, grants) is not None, 'another command'
    assert admission(f'{GRANT_VAR}={_ID[::-1]} timeout 6h {_CMD}', _NOW, grants) is not None, 'an unknown grant'


def test_the_sweep_bound_is_the_grant_or_the_default() -> None:
    grants = _grants({_ID: ('x', 6 * 3600.0)})
    assert granted_bound(f"eval '{GRANT_VAR}={_ID} timeout 6h x'", _NOW, grants) == 6 * 3600.0
    assert granted_bound("eval 'timeout 6h x'", _NOW, grants) == 50 * 60.0
