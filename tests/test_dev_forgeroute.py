"""FAILURE ROUTING against a REAL loopback forge: what the SERVER received is the evidence."""

from __future__ import annotations

from collections.abc import Iterator
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest
from _forge_fake import Loopback, Recorder, answer, client, git_out, make_repo, run_git, serve

from lab_commons.dev.forge import Forge
from lab_commons.dev.forgeroute import (
    DEFAULT_AREA,
    area_of,
    group,
    main,
    owners_of,
    read_areas,
    read_owners,
    reconcile,
    render,
    route,
)
from lab_commons.hpc.records import write_record

_FORGE = Forge('forge.example.org', 'o', 'r')
_ROOT = '/api/v1/repos/o/r'
_AREAS = """
[tool.lab_commons.areas]
default = "triage"
jmag = ["src/pkg/hamilton/adapters/jmag/**", "tests/**/jmag/**"]
coupling = ["tests/unit/hamilton/coupling/*.py"]
"""
_JMAG = 'tests/unit/hamilton/adapters/jmag/test_x.py::test_a'
_STRAY = 'tests/unit/elsewhere/test_y.py::test_b'
_GREEN = 'tests/unit/hamilton/coupling/test_c.py::test_c'


@pytest.fixture
def server() -> Iterator[ThreadingHTTPServer]:
    yield from serve()


def _record(outcomes: dict[str, str], reasons: dict[str, str] | None = None) -> dict:
    return {'sha': 'a' * 40, 'platform': 'linux', 'req': 'r1', 'outcomes': outcomes, 'reasons': reasons or {}}


def _issue(number: int, title: str, body: str) -> dict:
    return {'number': number, 'title': title, 'state': 'open', 'body': body, 'html_url': 'h', 'user': {'login': 'u'}}


def _writes() -> list[tuple[str, str, object]]:
    return [(r['method'], r['path'], r['body']) for r in Recorder.received if r['method'] != 'GET']


def test_globs_claim_by_file_in_declaration_order_and_the_rest_is_the_default() -> None:
    areas, default = read_areas(_AREAS)
    assert default == 'triage'
    assert area_of(_JMAG, areas, default) == 'jmag'
    assert area_of('tests/jmag/test_top.py::t', areas, default) == 'jmag', '**/ also matches zero directories'
    assert area_of(_STRAY, areas, default) == 'triage'
    assert area_of('tests/unit/hamilton/coupling/deep/test_d.py::t', areas, default) == 'triage', '* stays in one dir'
    assert read_areas('')[1] == DEFAULT_AREA


@pytest.mark.parametrize('bad', ['[tool.lab_commons.areas]\nx = "a/**"', '[tool.lab_commons.areas]\ndefault = ""'])
def test_a_malformed_area_is_refused(bad: str) -> None:
    with pytest.raises(ValueError, match=r'tool\.lab_commons\.areas'):
        read_areas(bad)


def test_group_separates_reds_from_greens_and_ignores_unknown_outcomes() -> None:
    areas, default = read_areas(_AREAS)
    grouped = group({_JMAG: 'failed', _STRAY: 'lost', _GREEN: 'passed', 'x.py::t': 'weird'}, areas, default)
    assert grouped == {'jmag': ({_JMAG}, set()), 'triage': ({_STRAY}, set()), 'coupling': (set(), {_GREEN})}


def test_render_ticks_off_a_green_and_keeps_an_unrun_id_as_it_was() -> None:
    previous = 'head\n\n- [ ] `old::green` (linux) failed\n- [ ] `other::platform` (windows) failed\n'
    body, red = render(previous, set(), {'old::green'}, _record({'old::green': 'passed'}), 'u')
    assert '- [x] `old::green`' in body
    assert '- [ ] `other::platform` (windows) failed' in body, 'not run here, so not green here'
    assert red


def test_a_planted_jmag_red_and_an_unmapped_red_each_open_their_area_issue(server) -> None:
    answer('GET', f'{_ROOT}/issues', (200, []))
    answer('POST', f'{_ROOT}/issues', (201, _issue(11, 'area:jmag', '')), (201, _issue(12, 'area:triage', '')))
    record = _record({_JMAG: 'failed', _STRAY: 'error', _GREEN: 'passed'}, {_JMAG: 'AssertionError: off\nmore'})
    routed = route(client(_FORGE, Loopback(server)), record, _AREAS)
    assert [(r.area, r.action) for r in routed] == [('jmag', 'created'), ('triage', 'created')]
    created = [body for method, _path, body in _writes() if method == 'POST']
    assert [c['title'] for c in created] == ['area:jmag', 'area:triage'], 'the green-only area opens nothing'
    assert f'- [ ] `{_JMAG}` (linux) failed -- AssertionError: off' in created[0]['body']
    assert '/o/r/commit/' + 'a' * 40 in created[0]['body']
    assert _STRAY in created[1]['body'], 'an unmapped red is reported in the default area, never dropped'


def test_routing_the_same_record_twice_writes_nothing(server) -> None:
    record = _record({_JMAG: 'failed'})
    body, _ = render('', {_JMAG}, set(), record, 'u')
    answer('GET', f'{_ROOT}/issues', (200, [_issue(11, 'area:jmag', '')]))
    answer('GET', f'{_ROOT}/issues/11', (200, _issue(11, 'area:jmag', '[G · claude · b]\n\n' + body)))
    routed = route(client(_FORGE, Loopback(server)), record, _AREAS)
    assert [r.action for r in routed] == ['unchanged']
    assert _writes() == []


def test_a_new_red_updates_the_existing_issue_found_by_exact_title(server) -> None:
    body, _ = render('', {_JMAG}, set(), _record({_JMAG: 'failed'}), 'u')
    listed = [_issue(3, 'area:jmag follow-up', ''), _issue(11, 'area:jmag', '')]
    answer('GET', f'{_ROOT}/issues', (200, listed))
    answer('GET', f'{_ROOT}/issues/11', (200, _issue(11, 'area:jmag', body)))
    answer('PATCH', f'{_ROOT}/issues/11', (200, _issue(11, 'area:jmag', '')))
    other = 'tests/unit/hamilton/adapters/jmag/test_x.py::test_z'
    routed = route(client(_FORGE, Loopback(server)), _record({_JMAG: 'failed', other: 'failed'}), _AREAS)
    assert [(r.action, r.number) for r in routed] == [('updated', 11)]
    [(method, path, sent)] = _writes()
    assert (method, path) == ('PATCH', f'{_ROOT}/issues/11')
    assert _JMAG in sent['body']
    assert other in sent['body']


def test_an_area_gone_green_is_ticked_commented_and_closed(server) -> None:
    body, _ = render('', {_JMAG}, set(), _record({_JMAG: 'failed'}), 'u')
    answer('GET', f'{_ROOT}/issues', (200, [_issue(11, 'area:jmag', '')]))
    answer('GET', f'{_ROOT}/issues/11', (200, _issue(11, 'area:jmag', body)))
    answer('PATCH', f'{_ROOT}/issues/11', (200, _issue(11, 'area:jmag', '')))
    answer('POST', f'{_ROOT}/issues/11/comments', (201, {'id': 1, 'body': 'b', 'html_url': 'c'}))
    routed = route(client(_FORGE, Loopback(server)), _record({_JMAG: 'passed'}), _AREAS)
    assert [r.action for r in routed] == ['closed']
    writes = _writes()
    assert f'- [x] `{_JMAG}`' in writes[0][2]['body']
    assert writes[1][0] == 'POST'
    assert 'green at' in writes[1][2]['body']
    assert writes[2][2] == {'state': 'closed'}


def test_the_cli_reads_the_areas_at_the_records_commit(server, tmp_path: Path, monkeypatch) -> None:
    repo = make_repo(tmp_path, 'https://forge.example.org/o/r.git', branch='main')
    (repo / 'pyproject.toml').write_text(_AREAS, encoding='utf-8')
    run_git(repo, 'add', 'pyproject.toml')
    run_git(repo, '-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-q', '-m', 'areas')
    (repo / 'pyproject.toml').write_text('', encoding='utf-8')  # the working tree is NOT the declaration
    record = _record({_JMAG: 'failed'}) | {'sha': git_out(repo, 'rev-parse', 'HEAD')}
    path = write_record(record, tmp_path / 'records')
    answer('GET', f'{_ROOT}/issues', (200, []))
    answer('POST', f'{_ROOT}/issues', (201, _issue(11, 'area:jmag', '')))
    monkeypatch.setattr('lab_commons.dev.forgeroute.client_for', lambda *_a, **_k: client(_FORGE, Loopback(server)))
    assert main([str(path)], cwd=repo) == 0
    assert [b['title'] for m, _p, b in _writes() if m == 'POST'] == ['area:jmag']


def test_the_cli_refuses_a_record_whose_commit_is_absent(tmp_path: Path) -> None:
    repo = make_repo(tmp_path, 'https://forge.example.org/o/r.git', branch='main')
    path = write_record(_record({_JMAG: 'failed'}), tmp_path / 'records')
    assert main([str(path)], cwd=repo, env={'LAB_FORGE_TOKEN': 't'}) == 2


def test_the_open_issue_is_found_on_page_two_among_pulls_without_the_search_index(server) -> None:
    """PLANTED CONTROL, 2026-10-11: routing created #2432-#2436 beside the open #2427-#2431.

    Gitea sends ``"pull_request": null`` on every ISSUE, and the lookup tested the key's presence, so it
    threw every match away. The issues here carry that null exactly as gitea does; the one real pull of
    the same title is skipped, the issue sits on page 2 beside a newer duplicate and the OLDEST is kept.
    Every query but the plain listing answers ``[]`` -- a lagging search index must not matter.
    """
    record = _record({_JMAG: 'failed'})
    body, _ = render('', {_JMAG}, set(), record, 'u')
    answer('GET', f'{_ROOT}/issues', (200, []))
    pull = _issue(90, 'area:jmag', '') | {'pull_request': {'merged': False}}
    page_one = [pull] + [_issue(100 + n, f'other {n}', '') | {'pull_request': None} for n in range(49)]
    listing = f'{_ROOT}/issues?state=open&type=issues&limit=50&page='
    answer('GET', f'{listing}1', (200, page_one))
    dups = [_issue(17, 'area:jmag', '') | {'pull_request': None}, _issue(11, 'area:jmag', '') | {'pull_request': None}]
    answer('GET', f'{listing}2', (200, dups))
    answer('GET', f'{_ROOT}/issues/11', (200, _issue(11, 'area:jmag', body)))
    routed = route(client(_FORGE, Loopback(server)), record, _AREAS)
    assert [(r.action, r.number) for r in routed] == [('unchanged', 11)]
    assert _writes() == []


_OWNERS = """
[tool.lab_commons.forge.owners]
jmag = ["alice", "bob.k"]
"lane/*" = ["carol"]
"""


def test_owners_match_an_area_or_a_branch_glob_and_an_absent_table_names_nobody() -> None:
    owners = read_owners(_OWNERS)
    assert owners_of('jmag', 'main', owners) == ('alice', 'bob.k')
    assert owners_of('jmag', 'lane/x', owners) == ('alice', 'bob.k', 'carol')
    assert owners_of('triage', 'main', owners) == ()
    assert read_owners(_AREAS) == ()


@pytest.mark.parametrize('bad', ['["@alice"]', '["a b"]', '"alice"', '["-x"]'])
def test_a_malformed_owner_is_refused_with_the_fix(bad: str) -> None:
    with pytest.raises(ValueError, match=r'gitea username'):
        read_owners(f'[tool.lab_commons.forge.owners]\njmag = {bad}\n')


def test_a_created_area_issue_mentions_its_owners(server) -> None:
    answer('GET', f'{_ROOT}/issues', (200, []))
    answer('POST', f'{_ROOT}/issues', (201, _issue(11, 'area:jmag', '')))
    route(client(_FORGE, Loopback(server)), _record({_JMAG: 'failed'}) | {'branch': 'lane/x'}, _AREAS + _OWNERS)
    created = [body for method, _path, body in _writes() if method == 'POST']
    assert created[0]['body'].rstrip().endswith('cc @alice @bob.k @carol')


def test_reconcile_keeps_one_issue_per_title_so_two_hosts_write_once(server) -> None:
    """The first host creates; the second, deriving the same rows, finds it by title and writes nothing.

    PLANTED CONTROLS: a changed body is updated; an open issue under the prefix that no row wants is closed,
    and one under another prefix is left alone.
    """
    wanted = {'integration: feat/a is READY': 'merge it'}
    answer('GET', f'{_ROOT}/issues', (200, []))
    answer('POST', f'{_ROOT}/issues', (201, _issue(21, 'integration: feat/a is READY', 'merge it')))
    first = reconcile(client(_FORGE, Loopback(server)), 'integration: ', wanted)
    assert [(r.action, r.number) for r in first] == [('created', 21)]
    Recorder.received.clear()
    listed = [_issue(21, 'integration: feat/a is READY', ''), _issue(4, 'area:jmag', '')]
    answer('GET', f'{_ROOT}/issues', (200, listed), (200, listed))
    answer('GET', f'{_ROOT}/issues/21', (200, _issue(21, 'integration: feat/a is READY', '[H · x · y]\n\nmerge it')))
    second = reconcile(client(_FORGE, Loopback(server)), 'integration: ', wanted)
    assert [r.action for r in second] == ['unchanged']
    assert _writes() == []
    answer('GET', f'{_ROOT}/issues', (200, listed), (200, listed))
    answer('GET', f'{_ROOT}/issues/21', (200, _issue(21, 'integration: feat/a is READY', 'merge it')))
    answer('PATCH', f'{_ROOT}/issues/21', (200, _issue(21, 'x', '')))
    moved = reconcile(client(_FORGE, Loopback(server)), 'integration: ', {'integration: feat/a is READY': 'now'})
    assert [r.action for r in moved] == ['updated']
    stale = [_issue(21, 'integration: feat/a is READY', ''), _issue(4, 'area:jmag', '')]
    answer('GET', f'{_ROOT}/issues', (200, stale), (200, stale))
    answer('GET', f'{_ROOT}/issues/21', (200, _issue(21, 'integration: feat/a is READY', 'merge it')))
    answer('PATCH', f'{_ROOT}/issues/21', (200, _issue(21, 'x', '')))
    gone = reconcile(client(_FORGE, Loopback(server)), 'integration: ', {})
    assert [(r.action, r.number) for r in gone] == [('closed', 21)]
