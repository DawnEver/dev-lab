"""A tick never lists the issues in full: a client with a cache reads only what changed since its last read.

THE INCIDENT (2026-10-24): ``GET /repos/<org>/<repo>/issues`` was the forge's costliest request -- 958 calls
and 2775 s of server time in ten minutes on one repo -- because every tick of every host re-read every
issue ever opened, page by page (the hosts lookup alone asks ``state=all``). The planted control is the
client WITHOUT a cache: it still reads in full, so the incremental read is what the cache bought.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from dev_lab.dev.forgepulls import forget_issue, issues
from tests._forge_state import StateForge

if TYPE_CHECKING:
    from pathlib import Path


def _listings(forge: StateForge) -> list[str]:
    return [one for one in forge.asked if one.startswith('GET /api/v1/repos/o/r/issues?')]


def _cached(tmp_path: Path) -> StateForge:
    forge = StateForge()
    forge.cache_dir = tmp_path
    return forge


def test_a_second_read_asks_only_since_the_first_and_sees_what_changed(tmp_path: Path) -> None:
    forge = _cached(tmp_path)
    old = forge.add_issue('old')
    first = {raw['number'] for raw in issues(forge)}
    forge.now_http = 'Mon, 12 Oct 2026 12:05:00 GMT'
    new = forge.add_issue('new')
    second = {raw['number'] for raw in issues(forge)}
    cold, warm = _listings(forge)
    assert 'since=' not in cold
    assert 'since=2026-10-12T11%3A58%3A00' in warm  # the forge's clock at the first read, less the overlap
    assert first == {old}
    assert second == {old, new}


def test_an_issue_closed_since_the_last_read_reads_closed(tmp_path: Path) -> None:
    forge = _cached(tmp_path)
    number = forge.add_issue('x')
    assert [raw['number'] for raw in issues(forge, state='open')] == [number]
    forge.now_http = 'Mon, 12 Oct 2026 12:05:00 GMT'
    forge.issue_close(number)
    assert issues(forge, state='open') == ()
    assert [raw['state'] for raw in issues(forge, state='all')] == ['closed']


def test_an_unchanged_issue_is_not_read_again_yet_stays_listed(tmp_path: Path) -> None:
    forge = _cached(tmp_path)
    forge.add_issue('settled')  # updated 12:00
    issues(forge)
    forge.now_http = 'Mon, 12 Oct 2026 13:00:00 GMT'
    issues(forge)
    forge.asked.clear()
    assert len(issues(forge)) == 1
    (warm,) = _listings(forge)
    assert 'since=2026-10-12T12%3A58%3A00' in warm
    assert forge._listed({'state': 'all', 'since': '2026-10-12T12:58:00+00:00'}) == []  # the forge sent nothing


def test_planted_control_a_client_without_a_cache_reads_in_full_every_time() -> None:
    forge = StateForge()
    forge.add_issue('x')
    issues(forge)
    forge.now_http = 'Mon, 12 Oct 2026 12:05:00 GMT'
    issues(forge)
    assert all('since=' not in one for one in _listings(forge))


def test_a_deleted_issue_is_forgotten_by_the_cache(tmp_path: Path) -> None:
    forge = _cached(tmp_path)
    number = forge.add_issue('doomed')
    issues(forge)
    forge.call('DELETE', f'{forge.repo}/issues/{number}')
    forget_issue(forge, number)
    assert issues(forge) == ()


def test_an_issue_another_host_deleted_is_not_listed_from_its_cache(tmp_path: Path) -> None:
    """A cache holding more open issues than the repository counts re-reads in full.

    A ``since=`` read never says an issue is gone, and only the deleting host forgets it: every OTHER host's
    cache would list a deleted open issue for ever (a route then edits it, a tidy deletes it again).
    """
    forge = _cached(tmp_path)
    kept, doomed = forge.add_issue('kept'), forge.add_issue('doomed')
    issues(forge)
    forge.call('DELETE', f'{forge.repo}/issues/{doomed}')  # by another host: this cache is not told
    forge.now_http = 'Mon, 12 Oct 2026 12:05:00 GMT'
    assert [raw['number'] for raw in issues(forge, state='open')] == [kept]
    assert [raw['number'] for raw in issues(forge, state='all')] == [kept]
