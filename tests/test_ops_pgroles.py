"""``[ops.postgres]``: declared database roles and their predefined grants, ensured by install (2026-11-20).

The supervisor reads ``pg_stat_activity`` as its own OS user by local peer auth; that needs a LOGIN role of that name
holding ``pg_monitor``. Creating it was a manual admin step; now it is declared and ensured idempotently as the
postgres OS user. Only predefined ``pg_*`` roles may be granted: the door cannot hand out a superuser.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from dev_lab.ops import pgroles
from dev_lab.ops.config import load
from dev_lab.ops.pgroles import Postgres

_HOST = '[ops]\nhome = "/srv/ops"\npython = "/opt/ops/bin/python"\nrepos = []\n'


def test_the_ensure_is_idempotent_sql_run_as_the_postgres_user_over_the_local_socket() -> None:
    argv = pgroles.argv(Postgres(roles={'supervisor': ('pg_monitor',)}))
    assert argv[:4] == ['runuser', '-u', 'postgres', '--']
    assert '-h' not in argv, 'local socket, peer auth'
    sql = argv[-1]
    assert "IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'supervisor')" in sql
    assert 'CREATE ROLE "supervisor" LOGIN' in sql
    assert 'GRANT pg_monitor TO "supervisor";' in sql
    assert 'ON_ERROR_STOP=1' in argv


@pytest.mark.parametrize(
    ('roles', 'match'),
    [
        ({'x': ('superuser',)}, 'predefined'),
        ({'x': ('pg_monitor; DROP',)}, 'predefined'),
        ({'x"; DROP ROLE y; --': ('pg_monitor',)}, 'role name'),
        ({}, 'no roles'),
    ],
)
def test_a_grant_that_is_not_predefined_or_an_unsafe_name_is_refused(roles: dict, match: str) -> None:
    """PLANTED CONTROL: the door can say no -- nothing but a pg_* role is ever granted."""
    with pytest.raises(ValueError, match=match):
        Postgres(roles=roles)


def test_the_declaration_loads_from_ops_postgres(tmp_path: Path) -> None:
    path = tmp_path / 'supervise.toml'
    path.write_text(_HOST + '[ops.postgres]\nroles = { "supervisor" = ["pg_monitor"] }\n', encoding='utf-8')
    assert load(path).postgres == Postgres(roles={'supervisor': ('pg_monitor',)})


def test_ensure_reports_a_failure_and_install_prints_it_off_the_live_host() -> None:
    declared = Postgres(roles={'supervisor': ('pg_monitor',)})
    ran: list[list[str]] = []
    assert pgroles.ensure(declared, run=lambda argv: ran.append(argv) or 0) is True
    assert ran == [pgroles.argv(declared)]
    assert pgroles.ensure(declared, run=lambda _argv: 1) is False
    assert pgroles.step(declared).startswith('runuser -u postgres -- psql')
