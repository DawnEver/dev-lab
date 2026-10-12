"""``forge tidy`` deletes machine-made hosts duplicates, closes finished areas and requests, says so once."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from lab_commons.dev.forgehosts import HOSTS_MARKER, HOSTS_ORIGIN, HOSTS_TITLE
from lab_commons.dev.forgetidy import Hygiene, load_hygiene, tidy
from tests._forge_state import StateForge

if TYPE_CHECKING:
    from pathlib import Path

ALL = Hygiene(host_duplicates=True, green_areas=True, request_max_age_days=14)
_FLOOD_BODY = f'One comment per serving host, edited in place each tick {HOSTS_ORIGIN}.'
GONE = 'deleted'


def _flooded() -> tuple[StateForge, dict[str, int]]:
    forge = StateForge()
    named = {
        'home': forge.add_issue(HOSTS_TITLE, _FLOOD_BODY),
        'dup': forge.add_issue(HOSTS_TITLE, f'{HOSTS_MARKER}\n'),
        'closed_dup': forge.add_issue(HOSTS_TITLE, _FLOOD_BODY, state='closed'),
        'human': forge.add_issue(HOSTS_TITLE, 'I wrote this one by hand'),
        'red': forge.add_issue('area:jmag', '- [ ] `tests/a.py::t` failed\n- [x] `tests/b.py::t`'),
        'green': forge.add_issue('area:hairpin', '- [x] `tests/b.py::t` green at abc'),
        'old': forge.add_issue('run it', labels=[{'name': 'forge:request'}], created_at='2026-09-01T00:00:00+00:00'),
        'young': forge.add_issue('run it', labels=[{'name': 'forge:request'}], created_at='2026-10-10T00:00:00+00:00'),
        'other': forge.add_issue('a human question'),
    }
    return forge, named


def _states(forge: StateForge, named: dict[str, int]) -> dict[str, str]:
    return {key: forge.issues_by_number.get(number, {}).get('state', GONE) for key, number in named.items()}


def test_tidy_deletes_machine_duplicates_closes_the_rest_and_leaves_humans_alone() -> None:
    forge, named = _flooded()
    lines = tidy(forge, ALL)
    assert _states(forge, named) == {
        'home': 'open',
        'dup': GONE,
        'closed_dup': GONE,
        'human': 'open',
        'red': 'open',
        'green': 'closed',
        'old': 'closed',
        'young': 'open',
        'other': 'open',
    }
    (summary,) = [c['body'] for c in forge.comments[named['home']]]
    assert f'#{named["dup"]} `forge hosts`: deleted' in summary
    assert lines[-1] == f'summary created on #{named["home"]}'
    assert tidy(forge, ALL) == ['nothing to close'], 'a second pass changes nothing'


def test_a_token_without_delete_rights_closes_instead_and_says_so() -> None:
    forge, named = _flooded()
    forge.deny_delete = True
    lines = tidy(forge, Hygiene(host_duplicates=True))
    assert _states(forge, named)['dup'] == 'closed'
    assert _states(forge, named)['closed_dup'] == 'closed'
    assert f'#{named["dup"]}: delete refused (403), closed instead' in lines


def test_a_dry_run_writes_nothing() -> None:
    forge, named = _flooded()
    lines = tidy(forge, ALL, dry_run=True)
    assert [line.split(' #')[0] for line in lines] == ['would delete', 'would delete', 'would close', 'would close']
    assert set(_states(forge, named).values()) == {'open', 'closed'}
    assert len(forge.issues_by_number) == len(named)
    assert not forge.comments[named['home']]


def test_nothing_declared_reads_and_removes_nothing() -> None:
    forge, named = _flooded()
    forge.fail_lists = True  # not even read
    assert tidy(forge, Hygiene()) == []
    assert len(forge.issues_by_number) == len(named)


def test_planted_control_a_rule_that_is_off_removes_nothing_of_its_kind() -> None:
    forge, named = _flooded()
    tidy(forge, Hygiene(host_duplicates=True))
    assert _states(forge, named)['green'] == 'open'
    assert _states(forge, named)['old'] == 'open'
    assert _states(forge, named)['dup'] == GONE


def test_the_declaration_is_read_from_pyproject_and_an_unknown_key_refused(tmp_path: Path) -> None:
    manifest = tmp_path / 'pyproject.toml'
    manifest.write_text('[tool.lab_commons.forge.issue_hygiene]\nhost_duplicates = true\n', encoding='utf-8')
    assert load_hygiene(tmp_path) == Hygiene(host_duplicates=True)
    manifest.write_text('[tool.lab_commons.forge.issue_hygiene]\ndelete = true\n', encoding='utf-8')
    with pytest.raises(ValueError, match='unknown key'):
        load_hygiene(tmp_path)
