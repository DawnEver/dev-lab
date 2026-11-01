"""A CLUSTER RUN PUBLISHES WHAT IT LEARNED; ``forge run show <sha>`` reads it from the forge alone.

User ruling 2026-10-31: never depend on ssh to learn what a verdict did; the cluster being unreachable is normal.
The forge's records home is an in-memory store here; the reader is run with every subprocess refused, so a
reader that reached for ssh (or any shell) would fail.
"""

from __future__ import annotations

import gzip
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Any, NoReturn

import pytest

from dev_lab.dev import forgerun, forgerunpost, forgerunshow, forgerunstate
from dev_lab.dev.forgecli import NOUNS
from dev_lab.dev.forgerecords import Attachment, sha_of

SHA = 'e' * 40
OOM = {'id': 'a.py::hog', 'kind': 'out_of_memory', 'peak_mb': 4102.2, 'wall_s': 28.0, 'why': 'killed out of memory'}
SLOW = {'id': 'b.py::slow', 'kind': 'timeout', 'peak_mb': None, 'wall_s': 3600.0, 'why': 'cut by the shard wall'}
BAD = {'id': 'c.py::bad', 'kind': 'rejected', 'peak_mb': 300.0, 'wall_s': 3.5, 'why': 'assert 1 == 2'}


class _Home:
    """The records home: name -> bytes, newest last; a client downloads by url = name."""

    def __init__(self) -> None:
        self.files: dict[str, bytes] = {}

    def put(self, _client: object, name: str, content: bytes) -> Attachment:
        self.files.pop(name, None)
        self.files[name] = content
        return Attachment(len(self.files), name, name)

    def listing(self, _client: object) -> tuple[Attachment, ...]:
        return tuple(Attachment(n, name, name) for n, name in enumerate(self.files))

    def client(self) -> SimpleNamespace:  # a duck-typed forge client
        return SimpleNamespace(download=self.files.__getitem__)


@pytest.fixture
def home(monkeypatch: pytest.MonkeyPatch) -> _Home:
    store = _Home()
    monkeypatch.setattr(forgerunshow, 'replace_named', store.put)
    monkeypatch.setattr(forgerunshow, 'listing', store.listing)
    return store


@pytest.fixture
def no_shell(monkeypatch: pytest.MonkeyPatch) -> None:
    """PLANTED: every subprocess is refused, so ssh (or any shell) in the reader raises."""

    def refused(*_a: object, **_k: object) -> NoReturn:
        msg = 'the reader spawned a process: it must read the forge only'
        raise AssertionError(msg)

    monkeypatch.setattr(subprocess, 'Popen', refused)
    monkeypatch.setattr(subprocess, 'run', refused)


class _Cluster:
    def __init__(self, rounds: list[dict[str, Any]]) -> None:
        self.state_rounds = rounds

    def rounds(self, _run: forgerunstate.Run) -> list[dict[str, Any]]:
        return list(self.state_rounds)


def _run() -> forgerunstate.Run:
    return forgerunstate.Run('https://f/o/r.git', SHA, 'integrate/main', 'tests', '/out', 'owner', platform='base')


def _publish(home: _Home, monkeypatch: pytest.MonkeyPatch, rounds: list[dict[str, Any]]) -> tuple[Any, int]:
    monkeypatch.setattr(forgerunpost, 'step', lambda run, **changes: forgerunstate.Run(**{**run.__dict__, **changes}))
    return forgerun._publish_rounds(home.client(), _run(), _Cluster(rounds), lambda _l: None, 'tag')


@pytest.mark.usefixtures('no_shell')
def test_a_round_with_an_oom_a_timeout_and_a_failure_publishes_all_three(
    home: _Home, monkeypatch: pytest.MonkeyPatch
) -> None:
    rounds = [{'job_ids': ['11'], 'lost': [OOM, SLOW, BAD]}, {'job_ids': ['12']}]  # round 1 still running
    run, lost = _publish(home, monkeypatch, rounds)
    assert (run.rounds_posted, lost) == (1, 3)
    shown = '\n'.join(forgerunshow.show(home.client(), SHA))
    assert 'base: in flight' in shown
    assert 'round 0: 3 lost' in shown
    for loss in (OOM, SLOW, BAD):
        assert loss['id'] in shown
    for said in ('out_of_memory', 'peak 4102 MB', 'wall 28 s', 'timeout', 'wall 3600 s', 'rejected', 'assert 1 == 2'):
        assert said in shown


@pytest.mark.usefixtures('no_shell')
def test_a_clean_round_publishes_no_failure(home: _Home, monkeypatch: pytest.MonkeyPatch) -> None:
    """PLANTED CONTROL: the same path over a clean round names no id."""
    run, lost = _publish(home, monkeypatch, [{'job_ids': ['11'], 'lost': []}])
    assert (run.rounds_posted, lost) == (1, 0)
    assert forgerunshow.show(home.client(), SHA) == [f'{SHA[:12]}:', 'base: in flight', '  round 0: clean']


def test_a_round_is_published_once(home: _Home, monkeypatch: pytest.MonkeyPatch) -> None:
    rounds = [{'job_ids': ['11'], 'lost': [OOM]}]
    run, _ = _publish(home, monkeypatch, rounds)
    home.files.clear()
    again, _ = forgerun._publish_rounds(home.client(), run, _Cluster(rounds), lambda _l: None, 'tag')
    assert (again.rounds_posted, home.files) == (1, {}), 'an unchanged round count posts nothing'


@pytest.mark.usefixtures('no_shell')
def test_the_final_record_wins_over_the_ledger_and_names_the_failing_ids(home: _Home) -> None:
    forgerunshow.ledger(home.client(), SHA, 'base', [{'job_ids': ['11'], 'lost': [OOM]}])
    cells = {
        'a.py::hog': {'status': 'out_of_memory', 'reason': {'kind': 'out_of_memory', 'text': 'alone at 64000 MB'}},
        'c.py::bad': {'status': 'rejected', 'reason': {'kind': 'assertion', 'text': 'assert 1 == 2'}},
        'd.py::fine': {'status': 'ok'},
        'e.py::known': {
            'status': 'rejected',
            'reason': {'kind': 'expected', 'text': 'residual'},
            'expectation': {'status': 'rejected', 'why': 'residual'},
        },
        'f.py::gpu': {'status': 'unavailable', 'reason': {'kind': 'resource', 'text': 'no gpu'}},
    }
    record = {'sha': SHA, 'rounds': [{'job_ids': ['11'], 'lost': [OOM]}, {'job_ids': ['12'], 'lost': []}]}
    home.files[f'run-{SHA}-base-20261031.json.gz'] = gzip.compress(json.dumps({**record, 'cells': cells}).encode())
    shown = forgerunshow.show(home.client(), SHA)
    assert shown[1] == 'base: finished'
    assert '  round 1: clean' in shown
    assert '  final: 2 failing' in shown
    finals = shown[shown.index('  final: 2 failing') + 1 :]
    assert [line.split()[1] for line in finals] == ['a.py::hog', 'c.py::bad'], 'xfail, ok and resource skip never fail'


@pytest.mark.usefixtures('no_shell')
def test_a_sha_with_nothing_published_says_so(home: _Home) -> None:
    home.files[f'run-{"f" * 40}-base-1.json.gz'] = b''
    assert forgerunshow.show(home.client(), SHA) == [f'{SHA[:12]}: nothing published on the forge yet']


def test_the_ledger_is_pruned_with_its_sha() -> None:
    assert sha_of(forgerunshow.ledger_name(SHA, 'base')) == SHA


def test_run_show_is_a_forge_noun() -> None:
    assert NOUNS['run'] is forgerunshow.main
    assert Path(forgerunshow.__file__).name == 'forgerunshow.py'
