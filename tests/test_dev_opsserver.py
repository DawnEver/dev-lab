"""``opsserver``: the ops account's fixed verbs on a DECLARED server, over the one remote transport."""

from __future__ import annotations

from collections.abc import Sequence

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
