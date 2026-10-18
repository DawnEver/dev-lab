"""The hosts issue is found, never guessed: two ticks leave ONE issue and ONE card per host.

THE INCIDENT (2026-10-12): every ``forge serve`` tick on Ada opened a new ``forge hosts`` issue -- 128
across three repos -- because gitea's ``"pull_request": null`` made every listed issue look like a
pull, so the lookup found nothing. The planted control replays that predicate against the same
stateful forge and shows it duplicating.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from lab_commons.dev import forgehosts
from lab_commons.dev.forgehosts import HOSTS_MARKER, HOSTS_TITLE, HostCard, publish, read_cards
from lab_commons.dev.forgework import ForgeCallFailed, is_pull
from tests._forge_state import StateForge

if TYPE_CHECKING:
    from collections.abc import Mapping
    from typing import Any

NOW = datetime(2026, 10, 12, 12, tzinfo=UTC)


def _card(host: str, minute: int = 0) -> HostCard:
    return HostCard(host, 'alice', 'linux', NOW.replace(minute=minute).isoformat())


def _cards_on(forge: StateForge, number: int, host: str) -> int:
    return sum(f'lab-commons:host:{host} ' in c['body'] for c in forge.comments[number])


def test_two_ticks_of_two_hosts_leave_one_issue_and_one_card_each() -> None:
    forge = StateForge()
    assert publish(forge, _card('ada/alice')) == 'created'
    assert publish(forge, _card('ada/bob')) == 'created'
    assert publish(forge, _card('ada/alice', 5)) == 'updated'
    assert publish(forge, _card('ada/bob', 5)) == 'updated'
    (home,) = forge.titled(HOSTS_TITLE)
    assert HOSTS_MARKER in forge.issues_by_number[home]['body']
    assert (_cards_on(forge, home, 'ada/alice'), _cards_on(forge, home, 'ada/bob')) == (1, 1)
    assert {card.host for card in read_cards(forge)} == {'ada/alice', 'ada/bob'}


def _presence_only(raw: Mapping[str, Any]) -> bool:
    return 'pull_request' in raw


def _old_publish(forge: StateForge, card: HostCard) -> None:
    """The pre-fix shape: the first open listing page, a presence test, and a create on a miss."""
    listed = forge.call('GET', f'{forge.repo}/issues?state=open&type=issues&limit=50')
    number = next((r['number'] for r in listed if r['title'] == HOSTS_TITLE and not _presence_only(r)), None)
    number = number or forge.issue_create(HOSTS_TITLE, 'hosts').number
    forgehosts.comment_upsert(forge, number, kind=forgehosts.Marker.HOST, key=card.host, text=card.text())


def test_planted_control_the_old_lookup_opens_a_duplicate_every_tick() -> None:
    forge = StateForge()
    _old_publish(forge, _card('ada/alice'))
    _old_publish(forge, _card('ada/alice', 5))
    assert len(forge.titled(HOSTS_TITLE)) == 2, 'the control must reproduce the flood'
    assert not is_pull({'pull_request': None})
    assert is_pull({'pull_request': {'merged': False}})
    assert is_pull({'pull_request': {}})


def test_a_lookup_that_cannot_see_the_issue_it_just_created_refuses(monkeypatch) -> None:
    forge = StateForge()
    monkeypatch.setattr('lab_commons.dev.forgepulls.is_pull', _presence_only)  # the 2026-10-12 blindness
    with pytest.raises(forgehosts.HostsIssueLost):
        publish(forge, _card('ada/alice'))
    with pytest.raises(forgehosts.HostsIssueLost, match='repository counts 1'):
        publish(forge, _card('ada/alice', 5))
    assert len(forge.titled(HOSTS_TITLE)) == 1, 'blind, the second tick refuses before it creates'


def test_the_home_is_found_past_the_first_page_and_when_closed() -> None:
    forge = StateForge()
    home = forge.add_issue(HOSTS_TITLE, f'{HOSTS_MARKER}\nhome', state='closed')
    for index in range(120):  # newest first on gitea: the home sits on page three
        forge.add_issue(f'area:{index}')
    assert publish(forge, _card('ada/alice')) == 'created'
    assert len(forge.issues_by_number) == 121, 'nothing new was opened'
    assert _cards_on(forge, home, 'ada/alice') == 1


def test_the_oldest_of_several_is_the_one_home_marker_or_legacy_title() -> None:
    forge = StateForge()
    legacy = forge.add_issue(HOSTS_TITLE, 'opened before the marker')
    forge.add_issue('renamed by a human', f'{HOSTS_MARKER}\n')
    publish(forge, _card('ada/alice'))
    assert _cards_on(forge, legacy, 'ada/alice') == 1


def test_a_failed_lookup_opens_nothing_and_alarms() -> None:
    forge = StateForge()
    forge.fail_lists = True
    with pytest.raises(ForgeCallFailed):
        publish(forge, _card('ada/alice'))
    assert not forge.issues_by_number


def test_a_card_carries_its_supply_and_running_and_reads_back() -> None:
    card = HostCard(
        'ada/alice', 'a', 'linux', NOW.isoformat(), supply={'cpu': 3.0}, running=('gate measure',)
    )  # 'a' writes it
    forge = StateForge()
    publish(forge, card)
    assert read_cards(forge) == (card,)
    assert 'running: gate measure' in next(iter(forge.comments.values()))[0]['body']


def test_a_card_written_before_a_field_was_renamed_reads_without_it() -> None:
    """A field a version no longer declares is not read: a fleet mid-upgrade never crashes its readers.

    PLANTED CONTROL: the same body with the field this version declares reads it.
    """
    forge = StateForge()
    publish(forge, HostCard('ada/alice', 'alice', 'linux', NOW.isoformat(), supply={'cpu': 3.0}))
    (comment,) = next(iter(forge.comments.values()))
    current = read_cards(forge)
    comment['body'] = comment['body'].replace('"supply"', '"retired_key"')
    (old,) = read_cards(forge)
    assert (current[0].supply, old.supply) == ({'cpu': 3.0}, {})


def test_retiring_a_host_removes_its_one_card_and_leaves_the_others() -> None:
    forge = StateForge()
    publish(forge, _card('duip622037'))
    publish(forge, _card('ada/alice'))
    assert forgehosts.retire(forge, 'duip622037') == 'retired'
    assert {card.host for card in read_cards(forge)} == {'ada/alice'}
    assert forgehosts.retire(forge, 'duip622037') == 'absent', 'a second retire finds nothing and says so'
    assert publish(forge, _card('duip622037', 5)) == 'created', 'the host rejoins by ticking again'


def test_planted_control_retiring_an_unknown_host_touches_no_card() -> None:
    forge = StateForge()
    publish(forge, _card('ada/alice'))
    assert forgehosts.retire(forge, 'ada/ali') == 'absent', 'a prefix of a host is not that host'
    assert {card.host for card in read_cards(forge)} == {'ada/alice'}


def test_the_cli_retires_through_the_forge_door(monkeypatch, capsys) -> None:
    forge = StateForge()
    publish(forge, _card('duip622037'))
    monkeypatch.setattr(forgehosts, 'client_for', lambda _root: forge)
    assert forgehosts.main(['retire', 'duip622037']) == 0
    assert 'duip622037: retired' in capsys.readouterr().out
    assert read_cards(forge) == ()
