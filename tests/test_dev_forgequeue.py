"""THE FORGE IS THE ONLY FEEDBACK CHANNEL: host cards, live progress and the queue, read from a REAL loopback forge."""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest
from _forge_fake import Loopback, Recorder, answer, client, credential_env, git_out, make_repo, run_git, serve

from lab_commons.dev import forgequeue
from lab_commons.dev.forge import Forge
from lab_commons.dev.forgeclaim import Claim
from lab_commons.dev.forgehosts import HOSTS_TITLE, HostCard, publish, read_cards

NOW = datetime(2026, 10, 11, 12, 0, tzinfo=UTC)
NOW_HTTP = 'Sun, 11 Oct 2026 12:00:00 GMT'
API = '/api/v1/repos/o/r'
FORGE = Forge('forge.example.org', 'o', 'r')


@pytest.fixture
def server() -> Iterator[ThreadingHTTPServer]:
    for httpd in serve():
        Recorder.date = NOW_HTTP
        yield httpd


def _issue(number: int, title: str) -> dict[str, object]:
    url = f'https://forge.example.org/o/r/issues/{number}'
    return {'number': number, 'title': title, 'state': 'open', 'body': '', 'html_url': url, 'user': {'login': 'a'}}


def _comment(comment_id: int, card: HostCard) -> dict[str, object]:
    body = f'<!-- lab-commons:host:{card.host} -->\n{card.text()}'
    return {'id': comment_id, 'body': body, 'html_url': f'https://forge.example.org/c/{comment_id}'}


def _card(host: str, platform: str, ticked: datetime, **extra: object) -> HostCard:
    return HostCard(host, 'alice', platform, ticked.isoformat(), **extra)


def test_the_first_card_opens_the_hosts_issue_and_the_next_edits_it_in_place(server) -> None:
    built = client(FORGE, Loopback(server))
    card = _card('ada/alice', 'linux', NOW, headroom={'cores': 64, 'submits': 10})
    answer('GET', f'{API}/issues', (200, []))
    answer('POST', f'{API}/issues', (201, _issue(3, HOSTS_TITLE)))
    answer('GET', f'{API}/issues/3/comments', (200, []))
    answer('POST', f'{API}/issues/3/comments', (201, _comment(10, card)))
    assert publish(built, card) == 'created'
    posted = [r for r in Recorder.received if r['method'] == 'POST']
    assert posted[0]['body']['title'] == HOSTS_TITLE
    assert '<!-- lab-commons:host:ada/alice -->' in posted[1]['body']['body']
    Recorder.received.clear()
    later = _card('ada/alice', 'linux', NOW + timedelta(minutes=5))
    answer('GET', f'{API}/issues', (200, [_issue(3, HOSTS_TITLE)]))
    answer('GET', f'{API}/issues/3/comments', (200, [_comment(10, card)]))
    answer('PATCH', f'{API}/issues/comments/10', (200, _comment(10, later)))
    assert publish(built, later) == 'updated'
    assert not [r for r in Recorder.received if r['method'] == 'POST'], 'one comment per host, edited in place'


def test_a_card_older_than_three_of_its_ticks_is_stale(server) -> None:
    """PLANTED CONTROL: the same card fourteen minutes old is fresh."""
    built = client(FORGE, Loopback(server))
    fresh = _card('box-g', 'windows', NOW - timedelta(minutes=14))
    gone = _card('ada/bob', 'linux', NOW - timedelta(minutes=16))
    answer('GET', f'{API}/issues', (200, [_issue(3, HOSTS_TITLE)]))
    answer('GET', f'{API}/issues/3/comments', (200, [_comment(1, fresh), _comment(2, gone)]))
    cards = read_cards(built)
    assert [(card.host, card.stale(NOW)) for card in cards] == [('box-g', False), ('ada/bob', True)]


def test_a_cards_alarms_and_a_stale_cards_silence_are_shown_by_the_queue(server) -> None:
    """PLANTED CONTROL: a fresh card with no alarm shows no ALARM line and no STALE remedy."""
    built = client(FORGE, Loopback(server))
    alarm = {'kind': 'run', 'subject': 'the cluster run of abc cannot advance', 'body': 'sbatch refused'}
    loud = _card('ada/alice', 'linux', NOW, alarms=(alarm,))
    quiet = _card('box-g', 'windows', NOW)
    gone = _card('ada/bob', 'linux', NOW - timedelta(hours=1))
    answer('GET', f'{API}/issues', (200, [_issue(3, HOSTS_TITLE)]))
    answer('GET', f'{API}/issues/3/comments', (200, [_comment(i, c) for i, c in enumerate((loud, quiet, gone))]))
    cards = read_cards(built)
    assert cards[0].alarms == (alarm,), 'the alarm round-trips through the comment'
    hosts = [{**c.__dict__, 'holds': list(c.holds), 'alarms': list(c.alarms), 'stale': c.stale(NOW)} for c in cards]
    lines = forgequeue.render({'now': NOW.isoformat(), 'queue': [], 'in_flight': [], 'hosts': hosts, 'starved': []})
    assert '    ALARM run: the cluster run of abc cannot advance -- sbatch refused' in lines
    assert sum('ALARM' in line for line in lines) == 1
    stale = [line for line in lines if 'STALE' in line]
    assert len(stale) == 1
    assert 'ada/bob' in stale[0]
    assert 'credential' in stale[0], 'a host that stopped publishing names the likely cause'


def _origin(tmp_path: Path) -> tuple[Path, dict[str, str]]:
    repo = make_repo(tmp_path, 'https://forge.example.org/o/r.git', branch='main')
    (repo / 'pyproject.toml').write_text('[tool.lab_commons.parts.produce.windows]\nfull = ["x"]\n', 'utf-8')
    tips = {}
    for branch in ('integrate/main', 'feat/a'):
        run_git(repo, '-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-q', '--allow-empty', '-m', branch)
        tips[branch] = git_out(repo, 'rev-parse', 'HEAD')
        run_git(repo, 'update-ref', f'refs/remotes/origin/{branch}', tips[branch])
    return repo, tips


def _pull(head: str, sha: str) -> dict[str, object]:
    return {
        **_issue(7, head),
        'head': {'ref': head, 'sha': sha},
        'base': {'ref': 'integrate/main'},
        'labels': [],
    }


def _forge_of(tips: dict[str, str], cards: list[HostCard]) -> None:
    running = Claim('hpclogin02', 'alice', NOW + timedelta(hours=6), 'ada/alice', 'running 40/93 done 12/93')
    claim = {'id': 1, 'context': 'tests/windows', 'status': 'pending', 'description': running.description()}
    answer('GET', '/api/v1/user', (200, {'login': 'carol'}))
    answer('GET', f'{API}/pulls', (200, [_pull('feat/a', tips['feat/a'])]))
    answer('GET', f'{API}/issues', (200, [_issue(3, HOSTS_TITLE)]))
    answer('GET', f'{API}/issues/3/comments', (200, [_comment(i, card) for i, card in enumerate(cards)]))
    answer('GET', f'{API}/statuses/{tips["integrate/main"]}', (200, [claim]))
    answer('GET', f'{API}/statuses/{tips["feat/a"]}', (200, []))


def test_the_queue_shows_progress_hosts_and_why_work_waits(server, tmp_path: Path, monkeypatch) -> None:
    """Read from the forge alone. PLANTED CONTROL: a fresh windows card's reason replaces "no host serves"."""
    monkeypatch.setenv('LAB_COMMONS_CONFIG', str(tmp_path / 'home' / 'config.toml'))
    repo, tips = _origin(tmp_path)
    _forge_of(tips, [_card('box-g', 'windows', NOW - timedelta(hours=1))])
    built = client(FORGE, Loopback(server))
    seen = forgequeue.view(repo, built, fetch=lambda _root: None)
    assert seen['in_flight'] == [
        {
            'candidate': f'integrate/main@{tips["integrate/main"][:12]}:windows',
            'owner': 'ada/alice',
            'login': 'alice',
            'progress': 'running 40/93 done 12/93',
            'until': (NOW + timedelta(hours=6)).isoformat(),
        }
    ]
    (waiting,) = seen['queue']
    assert (waiting['candidate'], waiting['class']) == (f'feat/a@{tips["feat/a"][:12]}:windows', 'pr')
    assert waiting['blocked'] == 'no host serves windows', 'the only windows card is stale'
    assert [(h['host'], h['stale']) for h in seen['hosts']] == [('box-g', True)]
    key = waiting['candidate']
    _forge_of(tips, [_card('box-g', 'windows', NOW, waiting={key: 'no headroom: no free core here'})])
    again = forgequeue.view(repo, built, fetch=lambda _root: None)
    assert again['queue'][0]['blocked'] == 'no headroom: no free core here'
    lines = forgequeue.render(again)
    assert any('running 40/93 done 12/93' in line for line in lines)
    assert any(line.strip().startswith('pr') and 'no headroom' in line for line in lines)


def test_the_queue_cli_prints_json(server, tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.setenv('LAB_COMMONS_CONFIG', str(tmp_path / 'home' / 'config.toml'))
    repo, tips = _origin(tmp_path)
    _forge_of(tips, [])
    code = forgequeue.main(
        ['--json'], cwd=repo, env=credential_env(tmp_path), transport=Loopback(server), fetch=lambda _root: None
    )
    assert code == 0
    printed = json.loads(capsys.readouterr().out)
    assert set(printed) == {'now', 'queue', 'in_flight', 'hosts', 'starved'}
    assert printed['queue'][0]['blocked'] == 'no host serves windows'


def test_a_card_states_why_its_host_cannot_write_the_artefact_store() -> None:
    """PLANTED CONTROL: a card whose store works says nothing about it."""
    why = 'the rclone remote hpc-data: is missing or unusable'
    assert f'artefacts: {why}' in _card('ada/alice', 'linux', NOW, artefacts=why).text()
    assert 'artefacts:' not in _card('ada/alice', 'linux', NOW).text()
