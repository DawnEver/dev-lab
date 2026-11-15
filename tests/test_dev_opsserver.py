"""``opsserver``: the ops account's fixed verbs on a DECLARED server, over the one remote transport."""

from __future__ import annotations

import contextlib
import io
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

import pytest

from dev_lab.dev.opsserver import Server, declared_servers, main, remote_line

_FILE = {'server': [{'name': 'forge', 'target': 'ops@forge.example'}]}


def _run(argv: list[str]) -> tuple[int, list[Sequence[str]]]:
    ran: list[Sequence[str]] = []
    code = main(argv, file=lambda: _FILE, runner=lambda line: ran.append(line) or 0)
    return code, ran


def test_a_unit_verb_runs_its_fixed_sudo_command_over_an_attached_ssh() -> None:
    code, ran = _run(['forge', 'restart', 'gitea'])
    assert code == 0
    assert ran[0][:2] == ['ssh', '-t'], 'the ops login asks a one-time code: a terminal, never BatchMode'
    assert ran[0][-2] == 'ops@forge.example'
    assert 'sudo systemctl restart gitea' in ran[0][-1]


def test_install_runs_the_ops_door_from_the_servers_kit_checkout() -> None:
    line = remote_line(Server('forge', 'ops@forge.example'), 'install', None)
    assert line == 'sudo /opt/dev-lab/.venv/bin/python -m dev_lab.ops --config /etc/dev-lab/supervise.toml install'


@pytest.mark.parametrize(
    'argv',
    [
        ['elsewhere', 'status', 'gitea'],  # not declared
        ['forge', 'restart'],  # no unit
        ['forge', 'restart', 'gitea;rm'],  # a unit that widens the line
        ['forge', 'install', 'gitea'],  # a unit where none is taken
    ],
)
def test_anything_but_a_declared_server_and_a_fixed_verb_is_refused_before_any_ssh(argv: list[str]) -> None:
    """PLANTED CONTROLS: each refusal runs nothing."""
    code, ran = _run(argv)
    assert code == 2
    assert ran == []


def test_a_dry_run_prints_and_runs_nothing() -> None:
    assert _run(['forge', 'logs', 'caddy', '--dry-run']) == (0, [])


def test_disk_and_clean_run_the_servers_ops_door_with_its_declared_retention() -> None:
    server = declared_servers(
        {'server': [{'name': 'forge', 'target': 'ops@f', 'gitea_data': '/srv/gitea/data', 'journal_max_mb': 300}]}
    )['forge']
    door = 'sudo /opt/dev-lab/.venv/bin/python -m dev_lab.ops --config /etc/dev-lab/supervise.toml'
    assert remote_line(server, 'disk', None) == f'{door} disk --gitea-data /srv/gitea/data --journal-max-mb 300'
    assert remote_line(server, 'clean', None).startswith(f'{door} clean ')


def test_the_retention_defaults_are_documented_values() -> None:
    assert remote_line(Server('forge', 'ops@f'), 'clean', None).endswith(
        'clean --gitea-data /var/lib/gitea/data --journal-max-mb 500'
    )


@pytest.mark.parametrize(
    ('field', 'value'),
    [
        ('gitea_data', '/var/lib/gitea;rm -rf /'),
        ('gitea_data', 'relative'),
        ('gitea_data', '/a/../b'),
        ('journal_max_mb', 10),
        ('journal_max_mb', '500'),
        ('journal_max_mb', True),
    ],
)
def test_a_retention_value_that_widens_the_line_is_refused(field: str, value: object) -> None:
    """PLANTED CONTROLS: the declared values land on a sudo line, so each is checked before any ssh."""
    row = {'name': 'forge', 'target': 'ops@f', field: value}
    with pytest.raises(ValueError, match=field):
        remote_line(declared_servers({'server': [row]})['forge'], 'clean', None)


def test_a_server_table_without_a_target_is_refused() -> None:
    with pytest.raises(ValueError, match='name and target'):
        declared_servers({'server': [{'name': 'forge'}]})


_NOW = datetime(2026, 11, 13, 12, 0, tzinfo=UTC)
_CARDS = {
    'server': [
        {'name': 'forge', 'target': 'ops@forge.example', 'status': 'https://forge.example/dev-lab/status.json'},
        {'name': 'mirror', 'target': 'ops@mirror.example', 'status': 'https://mirror.example/dev-lab/status.json'},
        {'name': 'dark', 'target': 'ops@dark.example'},
    ]
}


def _a_card(at: datetime, *, down: bool = False) -> dict:
    return {
        'schema': 1,
        'at': at.isoformat(),
        'interval_s': 300,
        'status': 'degraded' if down else 'healthy',
        'components': {'http_health': 'down' if down else 'up'},
        'metrics': {},
        'last_error': None,
        'dev_lab': 'abc123',
    }


def _cards(argv: list[str], answers: dict[str, tuple[int, object, str]]) -> tuple[int, str, list[str]]:
    asked: list[str] = []
    ran: list[Sequence[str]] = []

    def fetch(url: str) -> tuple[int, object, str]:
        asked.append(url)
        return answers[url]

    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
        code = main(
            argv, file=lambda: _CARDS, runner=lambda line: ran.append(line) or 0, fetch=fetch, clock=lambda: _NOW
        )
    assert ran == [], 'reading a card never opens an ssh: no one-time code is asked'
    return code, out.getvalue(), asked


def test_every_declared_card_is_read_over_https_and_a_down_component_shows_down() -> None:
    answers = {
        'https://forge.example/dev-lab/status.json': (200, _a_card(_NOW, down=True), ''),
        'https://mirror.example/dev-lab/status.json': (200, _a_card(_NOW), ''),
    }
    code, out, asked = _cards(['all', 'card'], answers)
    assert code == 0
    assert asked == list(answers), 'a server with no declared status is not asked'
    assert 'forge: degraded' in out
    assert 'down: http_health' in out
    assert 'mirror: healthy' in out


def test_a_stale_or_unreachable_card_says_so_and_exits_one() -> None:
    """PLANTED CONTROLS: a card nobody rewrote for four cycles, and a host that does not answer."""
    stale = {'https://forge.example/dev-lab/status.json': (200, _a_card(_NOW - timedelta(minutes=20)), '')}
    code, out, _ = _cards(['forge', 'card'], stale)
    assert (code, 'STALE' in out) == (1, True)
    gone = {'https://forge.example/dev-lab/status.json': (0, None, 'ConnectionRefusedError: refused')}
    code, out, _ = _cards(['forge', 'card'], gone)
    assert code == 1
    assert 'forge: unreachable' in out
    assert 'ConnectionRefusedError' in out


def test_a_server_with_no_declared_card_is_refused_before_any_request() -> None:
    code, out, asked = _cards(['dark', 'card'], {})
    assert (code, asked) == (2, [])
    assert 'status = "https://' in out, 'the refusal names the key to declare'
