"""PRIORITY IS ORDERING: a host's declared subjects are claimed first, nothing is set aside, nothing preempted."""

from __future__ import annotations

import dataclasses
from collections.abc import Iterator
from dataclasses import asdict
from datetime import UTC, datetime
from http.server import ThreadingHTTPServer

import pytest
from _forge_fake import Loopback, Recorder, answer, client, serve
from lab_commons.compute.model import Candidate, Ranked, Schedule, rank
from lab_commons.compute.priority import Priority
from lab_commons.hpc.shell import FULL

from dev_lab.dev import forgequeue
from dev_lab.dev.forge import Forge
from dev_lab.dev.forgehosts import HostCard, card_of
from dev_lab.dev.forgeorigin import head_login
from dev_lab.dev.forgework import Comment

NOW = datetime(2026, 10, 14, 12, 0, tzinfo=UTC)
SCHEDULES = {'o/r': Schedule()}
API = '/api/v1/repos/o/r'
FORGE = Forge('forge.example.org', 'o', 'r')


def _cand(ref: str, kind: str, **origin: str) -> Candidate:
    return Candidate('o/r', ref, ref.ljust(40, '0'), 'linux', kind, NOW, FULL, session=ref, **origin)


def _order(ranked: tuple[Ranked, ...]) -> list[str]:
    return [item.candidate.ref for item in ranked]


HEAD = _cand('integrate/main', 'integration', origin='alice')
PUSH = _cand('lane/x', 'branch', origin='carol-gh')


def test_a_matching_login_is_claimed_before_a_higher_score_non_matching_one() -> None:
    """PLANTED CONTROL: without the declaration the integration head outscores the lane."""
    assert _order(rank([PUSH, HEAD], SCHEDULES, NOW, cost_h={})) == ['integrate/main', 'lane/x']
    favoured = rank([HEAD, PUSH], SCHEDULES, NOW, cost_h={}, priority=Priority(logins=frozenset({'carol-gh'})).matches)
    assert [(item.candidate.ref, item.priority) for item in favoured] == [('lane/x', True), ('integrate/main', False)]


def test_within_each_class_the_score_order_stands() -> None:
    other = _cand('lane/y', 'integration', origin='carol-gh')
    favoured = Priority(logins=frozenset({'carol-gh'})).matches
    assert _order(rank([PUSH, HEAD, other], SCHEDULES, NOW, cost_h={}, priority=favoured)) == [
        'lane/y',
        'lane/x',
        'integrate/main',
    ]


def test_a_host_declaring_nothing_keeps_pure_score_order() -> None:
    nothing = Priority.of({})
    assert _order(rank([PUSH, HEAD], SCHEDULES, NOW, cost_h={}, priority=nothing.matches)) == [
        'integrate/main',
        'lane/x',
    ]


def test_an_unresolved_author_gets_no_priority() -> None:
    """An empty origin, host or session never matches -- even a declaration naming an empty string."""
    unresolved = dataclasses.replace(PUSH, origin='', session='')
    declared = Priority.of({'logins': ['carol-gh', ''], 'hosts': [''], 'sessions': ['']})
    assert not declared.matches(unresolved)
    assert declared.matches(PUSH)  # CONTROL: the resolved login matches


def test_host_and_session_subjects_match() -> None:
    from_box = dataclasses.replace(HEAD, origin_host='box-g')
    assert Priority.of({'hosts': ['box-g']}).matches(from_box)
    assert not Priority.of({'hosts': ['box-h']}).matches(from_box)
    assert Priority.of({'sessions': ['lane/x']}).matches(PUSH)
    assert not Priority.of({'sessions': ['lane/x']}).matches(HEAD)


def test_an_unknown_priority_key_is_refused_by_name() -> None:
    with pytest.raises(ValueError, match=r"unknown key\(s\) \['users'\]"):
        Priority.of({'users': ['x']})


@pytest.fixture
def server() -> Iterator[ThreadingHTTPServer]:
    yield from serve()


def test_a_branch_heads_origin_is_the_login_the_forge_resolves(server) -> None:
    """Author, else committer; nothing resolved (or the forge does not know the sha) is ``''``, never a guess."""
    built = client(FORGE, Loopback(server))
    answer('GET', f'{API}/git/commits/{"a" * 40}', (200, {'author': {'login': 'carol-gh'}, 'committer': None}))
    answer('GET', f'{API}/git/commits/{"b" * 40}', (200, {'author': None, 'committer': {'login': 'bob'}}))
    answer('GET', f'{API}/git/commits/{"c" * 40}', (200, {'author': None, 'committer': None}))
    assert head_login(built, 'a' * 40) == 'carol-gh'
    assert head_login(built, 'b' * 40) == 'bob'
    assert head_login(built, 'c' * 40) == ''
    assert head_login(built, 'd' * 40) == ''  # 404
    assert Recorder.received


def test_a_card_carries_its_priority_and_the_queue_marks_the_rows_it_favours() -> None:
    card = HostCard(
        'ada/carol', 'carol', 'linux', NOW.isoformat(), priority=Priority.of({'logins': ['carol-gh']}).row()
    )
    body = f'<!-- lab-commons:host:{card.host} -->\n{card.text()}'
    read = card_of(Comment(1, body, ''))
    assert read is not None
    assert read.favours(PUSH)
    assert not read.favours(HEAD)  # CONTROL
    assert 'priority: logins carol-gh' in card.text()
    row = {'priority': [read.host], 'candidate': PUSH.key, 'class': 'branch', 'blocked': ''}
    row |= {'value': 30.0, 'cost_h': 4.0, 'score': 7.5, 'wait_h': 0.0}
    hosts = [{**asdict(read), 'holds': [], 'stale': False}]
    lines = forgequeue.render({'now': NOW.isoformat(), 'queue': [row], 'in_flight': [], 'hosts': hosts, 'starved': []})
    assert any(line.endswith('* priority on ada/carol') for line in lines)
    assert '    priority logins carol-gh' in lines
