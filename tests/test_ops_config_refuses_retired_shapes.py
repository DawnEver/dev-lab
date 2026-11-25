"""A retired ``[ops]`` shape is REFUSED by name with its migration, never upgraded on read (FORMATS-MIGRATE-ONCE).

Each row of :data:`~dev_lab.ops.configretired.RETIRED` is one key a host file once held (#311 moved five keys out
of ``[ops.breakglass]``; #402 retired ``[ops.forge] read_only``; the lock retired ``[ops.upgrade] overrides``), and
#403 retired a standing GitHub token of an App role. The loader and the config-source CI
(:mod:`dev_lab.ops.configcheck`) both refuse it; the refusal names the key and where its fact lives now.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from dev_lab.ops.config import load
from dev_lab.ops.configcheck import check_host
from dev_lab.ops.configretired import RETIRED

_BASE = """
[ops]
home = "{home}"
python = "/opt/dev-lab/.venv/bin/python"
repos = []
[ops.breakglass]
account = "breakglass"
keys = ["ssh-ed25519 AAAA agent"]
repos = ["https://gitea.example/owner/alpha.git"]
state = "/var/lib/forge-breakglass"
log = "/var/log/forge-breakglass/audit.log"
wave_ceiling = "24 h"
max_merges_max = 100
{glass}
[ops.breakglass.tokens]
"gitea.example" = "/etc/forge-breakglass/gitea-token"
{glass_tokens}
[ops.upgrade]
source = "https://github.com/owner/dev-lab.git"
{upgrade}
{tail}
"""

#: The two wave keys, spelled apart so the retired-spelling scan reads only their refusal rows.
_WAVE, _CAP = 'wave' + '_hours', 'max' + '_merges'

#: One planted retired key per row of RETIRED, keyed by (table, key): the slot it is written in and its line.
_PLANTED = {
    ('upgrade', 'overrides'): ('upgrade', 'overrides = "/etc/dev-lab/overrides.txt"'),
    ('breakglass', 'totp'): ('glass', 'totp = "/etc/breakglass/totp"'),
    ('breakglass', 'wave_hours'): ('glass', f'{_WAVE} = 24.0'),
    ('breakglass', 'max_merges'): ('glass', f'{_CAP} = 20'),
    ('breakglass', 'lockout_after'): ('glass', 'lockout_after = 5'),
    ('breakglass', 'lockout_minutes'): ('glass', 'lockout_minutes = 15.0'),
    ('forge', 'read_only'): ('tail', '[ops.forge]\nadmin = "admin"\nread_only = ["server-reader"]'),
}

_JUDGE = """[ops.judge]
user = "judge"
schedule = "*:0/5"
repos = ["https://github.com/owner/beta.git"]
[ops.judge.tokens]
"github.com" = "/etc/review-bot/pat"
"""


def _write(tmp_path: Path, **planted: str) -> Path:
    path = tmp_path / 'host.toml'
    slots = {'glass': '', 'glass_tokens': '', 'upgrade': '', 'tail': '', **planted}
    path.write_text(_BASE.format(home=(tmp_path / 'home').as_posix(), **slots), encoding='utf-8')
    return path


def test_the_current_shape_loads(tmp_path: Path) -> None:
    """PLANTED CONTROL: the base, holding no retired key, loads -- so each refusal below is the planted key's."""
    config = load(_write(tmp_path), environ={}, structure_only=True)
    assert config.breakglass is not None
    assert config.consent is None, 'nothing is derived: an issuer is declared, never seeded from break-glass'


def test_every_retired_key_is_planted_here() -> None:
    assert {(row.table, row.key) for row in RETIRED} == set(_PLANTED)


@pytest.mark.parametrize(('table', 'key'), sorted(_PLANTED))
def test_a_retired_key_is_refused_naming_where_its_fact_lives_now(tmp_path: Path, table: str, key: str) -> None:
    slot, line = _PLANTED[table, key]
    row = next(row for row in RETIRED if (row.table, row.key) == (table, key))
    with pytest.raises(ValueError, match='retired') as refused:
        load(_write(tmp_path, **{slot: line}), environ={}, structure_only=True)
    said = str(refused.value)
    assert f'[ops.{table}] {key}' in said
    assert row.migrate in said


@pytest.mark.parametrize('role', ['breakglass', 'judge'])
def test_a_standing_github_token_is_refused_naming_the_app(tmp_path: Path, role: str) -> None:
    planted = {'tail': _JUDGE} if role == 'judge' else {'glass_tokens': '"github.com" = "/etc/breakglass/pat"'}
    with pytest.raises(ValueError, match=rf'\[ops\.{role}\.tokens\] github\.com.*\[ops\.{role}\.apps\]'):
        load(_write(tmp_path, **planted), environ={}, structure_only=True)


def test_every_retired_shape_in_a_file_is_named_at_once(tmp_path: Path) -> None:
    planted = {'glass': 'totp = "/t"\n' + _PLANTED['breakglass', _WAVE][1], 'tail': _PLANTED['forge', 'read_only'][1]}
    with pytest.raises(ValueError, match='retired') as refused:
        load(_write(tmp_path, **planted), environ={}, structure_only=True)
    named = ('[ops.breakglass] totp', '[ops.breakglass] wave_hours', '[ops.forge] read_only')
    assert all(name in str(refused.value) for name in named)


def test_configcheck_refuses_a_retired_shape_off_its_host(tmp_path: Path) -> None:
    """The config-source CI refuses it too: structure_only no longer passes an old shape by upgrading it."""
    assert check_host(_write(tmp_path)) == []
    found = check_host(_write(tmp_path, glass='totp = "/etc/breakglass/totp"'))
    assert any('[ops.breakglass] totp' in line and 'retired' in line for line in found)
