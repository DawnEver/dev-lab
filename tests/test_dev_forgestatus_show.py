"""``forge status show``: a verdict line answers "is it green"; the reds it names answer "why not".

The record behind a part is attached to the forge and its URL is the status's ``target_url``
(:mod:`dev_lab.dev.forgerecords`); this verb reads it back and prints the failing node ids.
"""

from __future__ import annotations

import gzip
import json
from typing import Any

from dev_lab.dev.forgestatus import known_reds, status_show

_SHA = 'a' * 40
_RECORD_URL = 'https://forge.example.org/attachments/record.json.gz'


class _Client:
    """The two calls ``status show`` makes: the status list, and the record behind one of them."""

    backend = 'gitea'
    repo = '/api/v1/repos/o/r'

    def __init__(self, statuses: list[dict[str, Any]], record: dict[str, Any] | None) -> None:
        self._statuses = statuses
        self._record = record
        self.downloads: list[str] = []

    def call(self, method: str, path: str) -> list[dict[str, Any]]:
        assert method == 'GET'
        assert path.endswith(f'/statuses/{_SHA}'), path
        return self._statuses

    def download(self, url: str) -> bytes:
        self.downloads.append(url)
        assert self._record is not None, f'{url} was asked for with no record planted'
        return gzip.compress(json.dumps(self._record).encode('utf-8'))


def _status(state: str, description: str = 'scope=full ran=3 hands=-', url: str = _RECORD_URL) -> dict[str, Any]:
    return {'id': 1, 'context': 'tests/base', 'status': state, 'description': description, 'target_url': url}


def _cells(**outcomes: str) -> dict[str, Any]:
    """One plain cell per node; a status that is not OK owes a reason, as :class:`Cell` enforces."""
    return {
        node: {
            'status': status,
            'evidence': 'observed',
            **({} if status == 'ok' else {'reason': {'kind': 'fail', 'text': ''}}),
        }
        for node, status in outcomes.items()
    }


def test_a_green_part_prints_its_verdict_and_fetches_no_record() -> None:
    client = _Client([_status('success')], None)
    assert status_show(client, _SHA) == ('tests/base  success  scope=full ran=3 hands=-',)
    assert client.downloads == [], 'a PASS needs no reason, so the record is not fetched'


def test_a_red_part_names_the_failing_tests_from_its_record() -> None:
    """PLANTED both ways: the same part with every cell OK prints no failing line."""
    cells = _cells(**{'tests/test_a.py::test_a': 'ok', 'tests/test_b.py::test_b': 'error'})
    red = _Client([_status('failure')], {'cells': cells})
    lines = status_show(red, _SHA)
    assert lines[0].startswith('tests/base  failure')
    assert '  not ok: 1 of 2 test(s)' in lines
    assert any(line.startswith('  - tests/test_b.py::test_b') for line in lines)
    assert any(line.endswith(_RECORD_URL) for line in lines)

    green_cells = _Client([_status('failure')], {'cells': _cells(**{'tests/test_a.py::test_a': 'ok'})})
    assert '  not ok: 0 of 1 test(s)' in status_show(green_cells, _SHA)


def test_a_part_with_no_record_says_so_rather_than_guessing() -> None:
    client = _Client([_status('error', url='')], None)
    assert '  no record is attached to this part' in status_show(client, _SHA)


def test_one_part_can_be_asked_for_by_name() -> None:
    statuses = [_status('success'), {**_status('failure'), 'context': 'tests/workstation', 'id': 2}]
    client = _Client(statuses, {'cells': _cells(**{'tests/test_c.py::test_c': 'error'})})
    lines = status_show(client, _SHA, part='tests/workstation')
    assert len([line for line in lines if '  ' not in line[:2]]) == 1
    assert lines[0].startswith('tests/workstation  failure')
    assert status_show(client, _SHA, part='tests/connection') == (f'{_SHA[:12]} carries no tests/connection status',)


def test_an_unreadable_record_names_the_url_instead_of_failing() -> None:
    class Broken(_Client):
        def download(self, url: str) -> bytes:
            msg = 'the attachment is gone'
            raise OSError(msg)

    lines = status_show(Broken([_status('failure')], None), _SHA)
    assert any('could not be read' in line and _RECORD_URL in line for line in lines)


_BASE = 'b' * 40
_BASE_URL = 'https://forge.example.org/attachments/base.json.gz'


class _Pair(_Client):
    """A head and its base (the integration tip), each with its own record."""

    def __init__(self, head: dict[str, Any], base: dict[str, Any]) -> None:
        super().__init__([_status('failure')], head)
        self._base = base

    def call(self, method: str, path: str) -> list[dict[str, Any]]:
        assert method == 'GET'
        if path.endswith(f'/statuses/{_BASE}'):
            return [_status('failure', url=_BASE_URL)]
        return super().call(method, path)

    def download(self, url: str) -> bytes:
        if url == _BASE_URL:
            return gzip.compress(json.dumps(self._base).encode('utf-8'))
        return super().download(url)


def test_against_the_integration_tip_each_red_is_labelled_inherited_or_new() -> None:
    """2026-11-13: an agent could not tell the reds it inherited from the ones it made. PLANTED: one of each."""
    head = {'cells': _cells(**{'tests/test_a.py::test_a': 'error', 'tests/test_b.py::test_b': 'error'})}
    base = {'cells': _cells(**{'tests/test_a.py::test_a': 'error', 'tests/test_b.py::test_b': 'ok'})}
    lines = status_show(_Pair(head, base), _SHA, against=_BASE)
    assert lines[0] == f'against {_BASE[:12]}: reds it carries too are inherited'
    assert '  against the base: 1 inherited, 1 new' in lines
    assert any(line.startswith('  - tests/test_a.py::test_a') and line.endswith('  inherited') for line in lines)
    assert any(line.startswith('  - tests/test_b.py::test_b') and line.endswith('  NEW') for line in lines)


def test_the_known_reds_of_a_tip_are_its_not_ok_nodes_per_part() -> None:
    base = {'cells': _cells(**{'tests/test_a.py::test_a': 'error', 'tests/test_b.py::test_b': 'ok'})}
    assert known_reds(_Pair({}, base), _BASE) == {'tests/base': frozenset({'tests/test_a.py::test_a'})}


def test_a_part_whose_target_is_a_run_page_fetches_no_record() -> None:
    """Live 2026-11-13: an ``error`` part targets its Actions RUN PAGE, and fetching that HTML as a record read 406.

    PLANTED CONTROL: the record URL in the same position is fetched (the test above), so the skip is the target's.
    """
    page = 'https://github.com/o/r/actions/runs/43481529255'
    client = _Client([_status('error', 'unreachable: the box is held class=scheduling', url=page)], None)
    lines = status_show(client, _SHA)
    assert client.downloads == [], 'a run page is not a record'
    assert f'  no record is attached to this part; its target is {page}' in lines
