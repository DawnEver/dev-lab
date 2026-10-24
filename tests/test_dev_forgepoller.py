"""ONE POLLER PER REPO: the forge-wide poll runs on the one host holding a live lease on the hosts issue.

THE INCIDENT (2026-10-24): five accounts' hosts each polled seven repos every five minutes -- 9425 requests
in ten minutes, 97% from two login nodes -- each re-deriving the same repo-wide answers. The planted
controls: the holder renews without asking again, a second host never polls while the lease lives, and an
expired lease is taken over.
"""

from __future__ import annotations

from datetime import timedelta

from dev_lab.dev.forgehosts import HOSTS_MARKER, HOSTS_TITLE
from dev_lab.dev.forgepoller import elect, lease_of
from dev_lab.dev.forgepulls import comment_list
from tests._forge_state import NOW_HTTP, StateForge

TTL = timedelta(minutes=15)


def _forge() -> tuple[StateForge, int]:
    forge = StateForge()
    return forge, forge.add_issue(HOSTS_TITLE, HOSTS_MARKER)


def _holder(forge: StateForge, number: int) -> str:
    found = lease_of(comment_list(forge, number))
    assert found is not None
    return found[1].holder


def test_the_first_host_takes_the_lease_and_polls() -> None:
    forge, number = _forge()
    assert elect(forge, host='ada/alice', ttl=TTL) == (True, 'ada/alice')
    assert _holder(forge, number) == 'ada/alice'


def test_a_second_host_does_not_poll_while_the_lease_lives() -> None:
    forge, number = _forge()
    elect(forge, host='ada/alice', ttl=TTL)
    forge.now_http = 'Mon, 12 Oct 2026 12:05:00 GMT'
    writes = len([one for one in forge.asked if not one.startswith('GET')])
    assert elect(forge, host='ada/bob', ttl=TTL) == (False, 'ada/alice')
    assert len([one for one in forge.asked if not one.startswith('GET')]) == writes  # it wrote nothing
    assert _holder(forge, number) == 'ada/alice'


def test_planted_control_the_holder_renews_and_keeps_polling() -> None:
    forge, number = _forge()
    elect(forge, host='ada/alice', ttl=TTL)
    forge.now_http = 'Mon, 12 Oct 2026 12:05:00 GMT'
    forge.asked.clear()
    assert elect(forge, host='ada/alice', ttl=TTL) == (True, 'ada/alice')
    listings = [one for one in forge.asked if one.startswith(f'GET {forge.repo}/issues/{number}/comments')]
    found = lease_of(comment_list(forge, number))
    assert found is not None
    assert found[1].until.isoformat() == '2026-10-12T12:20:00+00:00'
    assert len(listings) == 1  # a live lease of its own is renewed without reading it back


def test_an_expired_lease_is_taken_over() -> None:
    forge, number = _forge()
    elect(forge, host='ada/alice', ttl=TTL)
    forge.now_http = 'Mon, 12 Oct 2026 12:16:00 GMT'  # alice's lease ran out at 12:15
    assert elect(forge, host='ada/bob', ttl=TTL) == (True, 'ada/bob')
    assert _holder(forge, number) == 'ada/bob'
    assert sum('lab-commons:poller' in c['body'] for c in forge.comments[number]) == 1


def test_the_oldest_lease_wins_a_race_to_create_it_and_the_loser_drops_its_own() -> None:
    forge, number = _forge()
    forge.call(
        'POST',
        f'{forge.repo}/issues/{number}/comments',
        {'body': '<!-- lab-commons:poller -->\nholder: ada/alice\nuntil: 2026-10-12T12:15:00+00:00'},
    )
    forge.login = 'b'
    forge.call(
        'POST',
        f'{forge.repo}/issues/{number}/comments',
        {'body': '<!-- lab-commons:poller -->\nholder: ada/bob\nuntil: 2026-10-12T12:15:00+00:00'},
    )
    assert forge.now_http == NOW_HTTP
    assert elect(forge, host='ada/bob', ttl=TTL) == (False, 'ada/alice')
    assert elect(forge, host='ada/alice', ttl=TTL) == (True, 'ada/alice')
    assert sum('lab-commons:poller' in c['body'] for c in forge.comments[number]) == 1


def test_a_repo_with_no_hosts_issue_polls_here() -> None:
    assert elect(StateForge(), host='ada/alice', ttl=TTL) == (True, 'ada/alice')
