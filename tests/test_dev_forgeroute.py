"""FAILURE ROUTING against a REAL loopback forge: what the SERVER received is the evidence."""

from __future__ import annotations

from collections.abc import Iterator
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest
from _forge_fake import Loopback, Recorder, answer, client, git_out, make_repo, run_git, serve
from lab_commons.hpc.records import write_record
from lab_commons.hpc.testcells import TestCell
from lab_commons.outcomes import Cell, Reason, Status

from dev_lab.dev.forge import Forge
from dev_lab.dev.forgeroute import (
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
    still_red,
)

_FORGE = Forge('forge.example.org', 'o', 'r')
_ROOT = '/api/v1/repos/o/r'
_AREAS = """
[tool.dev_lab.areas]
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


def _record(statuses: dict[str, str], reasons: dict[str, str] | None = None, handed: dict | None = None) -> dict:
    """A run record whose cells read *statuses* (status tokens), each non-OK cell carrying its reason."""
    meta = {'sha': 'a' * 40, 'platform': 'base', 'req': 'r1'}
    why = reasons or {}
    cells = {
        node: Cell(Status(token), reason=None if token in ('ok', 'pending') else Reason('x', why.get(node, '')))
        for node, token in statuses.items()
    }
    return meta | {'cells': {node: TestCell(cell).to_plain() for node, cell in cells.items()}, 'handed': handed or {}}


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


@pytest.mark.parametrize('bad', ['[tool.dev_lab.areas]\nx = "a/**"', '[tool.dev_lab.areas]\ndefault = ""'])
def test_a_malformed_area_is_refused(bad: str) -> None:
    with pytest.raises(ValueError, match=r'tool.dev_lab.areas'):
        read_areas(bad)


_NODE_ONLY = 'tests/unit/hamilton/adapters/jmag/test_hooks.py::test_node'


def _body(record: dict, area: str = 'jmag', previous: str = '') -> str:
    areas, default = read_areas(_AREAS)
    return render(previous, group(record, areas, default).get(area, {}), record, 'u')


def test_group_rows_reported_reds_per_id_and_folds_the_never_reported_into_one_row_per_area() -> None:
    areas, default = read_areas(_AREAS)
    unrun = {f'tests/jmag/test_{n}.py::t': 'infra' for n in range(7)}
    record = _record({_JMAG: 'rejected', _STRAY: 'rejected', _GREEN: 'ok', **unrun}, {_JMAG: 'boom\nmore'})
    grouped = group(record, areas, default)
    assert grouped['triage'] == {_STRAY: ' (base) rejected'}
    assert grouped['jmag'][_JMAG] == ' (base) rejected -- boom'
    assert grouped['jmag']['base: no answer'].startswith(' (base) 7 test(s) -- tests/jmag/test_0.py::t, ')
    assert grouped['jmag']['base: no answer'].endswith(', ...')
    assert 'coupling' not in grouped, 'a green id has no row'


def test_a_record_replaces_its_own_parts_rows_and_drops_rows_no_current_part_selects() -> None:
    """PLANTED CONTROL, 2026-10-15: area rows tagged by a retired part outlived it forever.

    The previous body holds a row of a retired platform name, a row tagged ``base`` for an id the record
    now hands to ``node`` (it moved part), a ``node`` row for an id ``node`` still selects, a ``node`` row
    for an id no longer collected, a ticked row and this part's own stale red. Only the ``node`` row whose
    id ``node`` still selects stands beside this record's reds.
    """
    previous = (
        'head\n\n'
        f'- [ ] `{_JMAG}` (base) rejected\n'
        '- [ ] `tests/jmag/test_old.py::t` (linux) rejected\n'
        f'- [ ] `{_NODE_ONLY}` (base) rejected\n'
        f'- [ ] `{_NODE_ONLY}x` (node) rejected\n'
        '- [ ] `tests/jmag/test_gone.py::t` (node) error\n'
        '- [x] `tests/jmag/test_ticked.py::t` (node) rejected\n'
        '- [ ] `node: no answer` (node) 2 test(s) -- a, b\n'
        '- [ ] `linux: no answer` (linux) 2 test(s) -- a, b\n'
    )
    other = 'tests/jmag/test_new.py::t'
    record = _record(
        {_JMAG: 'ok', other: 'rejected'},
        handed={_NODE_ONLY: 'node', f'{_NODE_ONLY}x': 'node'},
    )
    body = _body(record, previous=previous)
    rows = [line for line in body.splitlines() if line.startswith('- [')]
    assert rows == [
        '- [ ] `node: no answer` (node) 2 test(s) -- a, b',
        f'- [ ] `{other}` (base) rejected',
        f'- [ ] `{_NODE_ONLY}x` (node) rejected',
    ]
    assert body.startswith('Last routed: part `base` at [aaaaaaaaaaaa](u) (req `r1`), FAIL.')


def test_a_green_record_leaves_no_row_of_its_part_and_the_body_reads_green_to_tidy() -> None:
    body = _body(_record({_JMAG: 'ok'}), previous=f'h\n\n- [ ] `{_JMAG}` (base) rejected\n')
    assert not still_red(body)
    assert 'PASS.' in body


def test_a_red_beside_unanswered_ids_keeps_both_rows_and_reads_fail() -> None:
    """A wrong answer is wrong whatever else is missing (outcomes.Conclusion): the record reads FAIL."""
    body = _body(_record({_JMAG: 'rejected', 'tests/jmag/test_l.py::t': 'pending'}))
    assert f'- [ ] `{_JMAG}` (base) rejected' in body
    assert '- [ ] `base: no answer` (base) 1 test(s) -- tests/jmag/test_l.py::t' in body
    assert 'FAIL.' in body


def test_an_inconclusive_record_says_so_and_rows_its_unanswered_ids() -> None:
    body = _body(_record({_JMAG: 'ok', 'tests/jmag/test_l.py::t': 'infra'}))
    assert '- [ ] `base: no answer` (base) 1 test(s) -- tests/jmag/test_l.py::t' in body
    assert 'INCONCLUSIVE.' in body


def test_a_planted_jmag_red_and_an_unmapped_red_each_open_their_area_issue(server) -> None:
    answer('GET', f'{_ROOT}/issues', (200, []))
    answer('POST', f'{_ROOT}/issues', (201, _issue(11, 'area:jmag', '')), (201, _issue(12, 'area:triage', '')))
    record = _record({_JMAG: 'rejected', _STRAY: 'rejected', _GREEN: 'ok'}, {_JMAG: 'AssertionError: off\nmore'})
    routed = route(client(_FORGE, Loopback(server)), record, _AREAS)
    assert [(r.area, r.action) for r in routed] == [('jmag', 'created'), ('triage', 'created')]
    created = [body for method, _path, body in _writes() if method == 'POST']
    assert [c['title'] for c in created] == ['area:jmag', 'area:triage'], 'the green-only area opens nothing'
    assert f'- [ ] `{_JMAG}` (base) rejected -- AssertionError: off' in created[0]['body']
    assert '/o/r/commit/' + 'a' * 40 in created[0]['body']
    assert _STRAY in created[1]['body'], 'an unmapped red is reported in the default area, never dropped'


def test_routing_the_same_record_twice_writes_nothing(server) -> None:
    record = _record({_JMAG: 'rejected'})
    body = _body(record)
    answer('GET', f'{_ROOT}/issues', (200, [_issue(11, 'area:jmag', '')]))
    answer('GET', f'{_ROOT}/issues/11', (200, _issue(11, 'area:jmag', '[G · claude · b]\n\n' + body)))
    routed = route(client(_FORGE, Loopback(server)), record, _AREAS)
    assert [r.action for r in routed] == ['unchanged']
    assert _writes() == []


def test_a_new_red_updates_the_existing_issue_found_by_exact_title(server) -> None:
    body = _body(_record({_JMAG: 'rejected'}))
    listed = [_issue(3, 'area:jmag follow-up', ''), _issue(11, 'area:jmag', '')]
    answer('GET', f'{_ROOT}/issues', (200, listed))
    answer('GET', f'{_ROOT}/issues/11', (200, _issue(11, 'area:jmag', body)))
    answer('PATCH', f'{_ROOT}/issues/11', (200, _issue(11, 'area:jmag', '')))
    other = 'tests/unit/hamilton/adapters/jmag/test_x.py::test_z'
    routed = route(client(_FORGE, Loopback(server)), _record({_JMAG: 'rejected', other: 'rejected'}), _AREAS)
    assert [(r.action, r.number) for r in routed] == [('updated', 11)]
    [(method, path, sent)] = _writes()
    assert (method, path) == ('PATCH', f'{_ROOT}/issues/11')
    assert _JMAG in sent['body']
    assert other in sent['body']


def test_an_area_gone_green_is_rewritten_and_left_for_tidy_to_close(server) -> None:
    """Routing never closes: ``forge tidy`` (``green_areas``) closes by the same :func:`still_red`."""
    answer('GET', f'{_ROOT}/issues', (200, [_issue(11, 'area:jmag', '')]))
    answer('GET', f'{_ROOT}/issues/11', (200, _issue(11, 'area:jmag', _body(_record({_JMAG: 'rejected'})))))
    answer('PATCH', f'{_ROOT}/issues/11', (200, _issue(11, 'area:jmag', '')))
    routed = route(client(_FORGE, Loopback(server)), _record({_JMAG: 'ok'}), _AREAS)
    assert [r.action for r in routed] == ['updated']
    [(method, _path, sent)] = _writes()
    assert method == 'PATCH'
    assert not still_red(sent['body'])


def test_an_open_area_the_record_has_no_row_in_still_loses_a_retired_parts_rows(server) -> None:
    stale = (
        'Last routed: run `linux` at x.\n\n- [ ] `tests/unit/hamilton/coupling/test_c.py::test_c` (linux) rejected\n'
    )
    answer('GET', f'{_ROOT}/issues', (200, [_issue(5, 'area:coupling', stale)]))
    answer('GET', f'{_ROOT}/issues/5', (200, _issue(5, 'area:coupling', stale)))
    answer('PATCH', f'{_ROOT}/issues/5', (200, _issue(5, 'area:coupling', '')))
    routed = route(client(_FORGE, Loopback(server)), _record({_GREEN: 'ok'}), _AREAS)
    assert [(r.area, r.action) for r in routed] == [('coupling', 'updated')]
    assert not still_red(_writes()[0][2]['body'])


def test_a_record_covering_no_test_routes_nothing(server) -> None:
    record = _record({}, handed={_JMAG: 'node'})
    assert route(client(_FORGE, Loopback(server)), record, _AREAS) == ()
    assert Recorder.received == []


def test_the_cli_reads_the_areas_at_the_records_commit(server, tmp_path: Path, monkeypatch) -> None:
    repo = make_repo(tmp_path, 'https://forge.example.org/o/r.git', branch='main')
    (repo / 'pyproject.toml').write_text(_AREAS, encoding='utf-8')
    run_git(repo, 'add', 'pyproject.toml')
    run_git(repo, '-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-q', '-m', 'areas')
    (repo / 'pyproject.toml').write_text('', encoding='utf-8')  # the working tree is NOT the declaration
    record = _record({_JMAG: 'rejected'}) | {'sha': git_out(repo, 'rev-parse', 'HEAD')}
    path = write_record(record, tmp_path / 'records')
    answer('GET', f'{_ROOT}/issues', (200, []))
    answer('POST', f'{_ROOT}/issues', (201, _issue(11, 'area:jmag', '')))
    monkeypatch.setattr('dev_lab.dev.forgeroute.client_for', lambda *_a, **_k: client(_FORGE, Loopback(server)))
    assert main([str(path)], cwd=repo) == 0
    assert [b['title'] for m, _p, b in _writes() if m == 'POST'] == ['area:jmag']


def test_the_cli_refuses_a_record_whose_commit_is_absent(tmp_path: Path) -> None:
    repo = make_repo(tmp_path, 'https://forge.example.org/o/r.git', branch='main')
    path = write_record(_record({_JMAG: 'rejected'}), tmp_path / 'records')
    assert main([str(path)], cwd=repo, env={'LAB_FORGE_TOKEN': 't'}) == 2


def test_the_open_issue_is_found_on_page_two_among_pulls_without_the_search_index(server) -> None:
    """PLANTED CONTROL, 2026-10-11: routing created #2432-#2436 beside the open #2427-#2431.

    Gitea sends ``"pull_request": null`` on every ISSUE, and the lookup tested the key's presence, so it
    threw every match away. The issues here carry that null exactly as gitea does; the one real pull of
    the same title is skipped, the issue sits on page 2 beside a newer duplicate and the OLDEST is kept.
    Every query but the plain listing answers ``[]`` -- a lagging search index must not matter.
    """
    record = _record({_JMAG: 'rejected'})
    body = _body(record)
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
[tool.dev_lab.forge.owners]
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
        read_owners(f'[tool.dev_lab.forge.owners]\njmag = {bad}\n')


def test_a_created_area_issue_mentions_its_owners(server) -> None:
    answer('GET', f'{_ROOT}/issues', (200, []))
    answer('POST', f'{_ROOT}/issues', (201, _issue(11, 'area:jmag', '')))
    route(client(_FORGE, Loopback(server)), _record({_JMAG: 'rejected'}) | {'branch': 'lane/x'}, _AREAS + _OWNERS)
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
