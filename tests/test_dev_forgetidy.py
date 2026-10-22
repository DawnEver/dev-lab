"""``forge tidy`` deletes machine duplicates and retired-marker comments, closes finished and idle issues, once."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from dev_lab.dev.forgehosts import HOSTS_MARKER, HOSTS_ORIGIN, HOSTS_TITLE
from dev_lab.dev.forgepulls import Marker, marker
from dev_lab.dev.forgetidy import Hygiene, load_hygiene, tidy
from dev_lab.dev.forgework import ForgeCallFailed
from tests._forge_state import StateForge

if TYPE_CHECKING:
    from pathlib import Path

ALL = Hygiene()
LONG_AGO = '2026-09-01T00:00:00+00:00'
RETIRED_BODY = '<!-- lab-commons:reserve:alpha -->\nheld'
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
        'idle': forge.add_issue('analyse the thing', created_at=LONG_AGO, updated_at=LONG_AGO),
        'touched': forge.add_issue('analyse more', created_at=LONG_AGO, updated_at='2026-10-11T00:00:00+00:00'),
        'old_red': forge.add_issue('area:old', '- [ ] `tests/c.py::t` red', created_at=LONG_AGO, updated_at=LONG_AGO),
        'alarm': forge.add_issue(
            'integration: integrate/main is BLOCKED', 'x', created_at=LONG_AGO, updated_at=LONG_AGO
        ),
        'marked': forge.add_issue('kept', f'{marker(Marker.INTEGRATION)}\n', created_at=LONG_AGO, updated_at=LONG_AGO),
    }
    home = forge.comments[named['home']]
    for body in (RETIRED_BODY, f'{marker(Marker.HOST, "alpha")}\ncard', 'a human note'):
        home.append({'id': len(home) + 1, 'body': body, 'html_url': 'c', 'user': {'login': 'a'}})
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
        'idle': 'closed',
        'touched': 'open',
        'old_red': 'open',
        'alarm': 'open',
        'marked': 'open',
    }
    *kept, summary = [c['body'] for c in forge.comments[named['home']]]
    assert [body.split('\n')[-1] for body in kept] == ['card', 'a human note'], 'only the retired marker went'
    assert f'#{named["dup"]} `forge hosts`: deleted' in summary
    assert 'comment deleted -- machine comment of retired marker kind reserve' in summary
    assert f'#{named["idle"]} `analyse the thing`: closed -- work issue idle 41 d, past 14 d' in summary
    assert lines[-1] == f'summary created on #{named["home"]}'
    assert tidy(forge, ALL) == ['nothing to close'], 'a second pass changes nothing'


def test_a_token_without_delete_rights_closes_instead_and_says_so() -> None:
    forge, named = _flooded()
    forge.deny_delete = True
    lines = tidy(forge, ALL)
    assert _states(forge, named)['dup'] == 'closed'
    assert _states(forge, named)['closed_dup'] == 'closed'
    assert f'#{named["dup"]}: delete refused (403), closed instead' in lines


def test_a_dry_run_writes_nothing() -> None:
    forge, named = _flooded()
    lines = tidy(forge, ALL, dry_run=True)
    assert [line.split(' #')[0] for line in lines] == [
        'would delete comment 1 on',
        'would delete',
        'would delete',
        'would close',
        'would close',
        'would close',
    ]
    assert set(_states(forge, named).values()) == {'open', 'closed'}
    assert len(forge.issues_by_number) == len(named)
    assert len(forge.comments[named['home']]) == 3


def test_nothing_declared_is_every_rule_on(tmp_path: Path) -> None:
    """Issues must never rot: a repo with no table is tidied by the defaults, never skipped."""
    assert load_hygiene(tmp_path) == ALL
    assert ALL.host_duplicates
    assert ALL.green_areas
    assert ALL.work_max_idle_days == ALL.request_max_age_days == 14


def test_a_failed_listing_removes_nothing() -> None:
    forge, named = _flooded()
    forge.fail_lists = True
    with pytest.raises(ForgeCallFailed):
        tidy(forge, ALL)
    assert len(forge.issues_by_number) == len(named)


def test_planted_control_a_rule_that_is_off_removes_nothing_of_its_kind() -> None:
    forge, named = _flooded()
    tidy(forge, Hygiene(green_areas=False, request_max_age_days=10_000, work_max_idle_days=10_000))
    assert _states(forge, named)['green'] == 'open'
    assert _states(forge, named)['old'] == 'open'
    assert _states(forge, named)['idle'] == 'open'
    assert _states(forge, named)['dup'] == GONE


def test_the_declaration_is_read_from_pyproject_and_an_unknown_key_refused(tmp_path: Path) -> None:
    manifest = tmp_path / 'pyproject.toml'
    manifest.write_text('[tool.lab_commons.forge.issue_hygiene]\nwork_max_idle_days = 7\n', encoding='utf-8')
    assert load_hygiene(tmp_path) == Hygiene(work_max_idle_days=7)
    manifest.write_text('[tool.lab_commons.forge.issue_hygiene]\ndelete = true\n', encoding='utf-8')
    with pytest.raises(ValueError, match='unknown key'):
        load_hygiene(tmp_path)
