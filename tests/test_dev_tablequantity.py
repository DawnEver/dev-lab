"""A schema dataclass's quantity fields are parsed once, and its retired unit-suffixed keys are refused by name.

User ruling 2026-11-25: ``lockout = "15 min"``, never ``lockout_minutes = 15``. The planted defects are the bare
number (its unit nowhere) and the old key (FORMATS-MIGRATE-ONCE: refused with the line that replaces it).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest
from lab_commons.quantity import QuantityRefused

from dev_lab.dev.tablequantity import quantity, values
from dev_lab.ops.config import load


@dataclass(frozen=True)
class _Table:
    """``[planted]``: one duration, one size, one plain key."""

    name: str = ''
    wait: float = quantity('duration', 60.0, retired=('wait_minutes', 'min'))
    cap: float = quantity('size', 1024.0, retired=('cap_mb', 'MiB'))


def test_a_quantity_field_is_parsed_to_its_base_unit_and_a_plain_key_passes() -> None:
    assert values(_Table, {'name': 'x', 'wait': '2 min', 'cap': '1 MiB'}, '[planted]') == {
        'name': 'x', 'wait': 120.0, 'cap': 1024.0**2,
    }  # fmt: skip
    assert _Table().wait == 60.0, 'undeclared: the default, in the base unit'


def test_a_bare_number_is_refused_naming_the_table_and_key() -> None:
    with pytest.raises(QuantityRefused, match=r'\[planted\] wait = 2 is a bare number'):
        values(_Table, {'wait': 2}, '[planted]')


def test_a_retired_unit_key_is_refused_with_its_new_line() -> None:
    with pytest.raises(QuantityRefused, match=r'\[planted\] cap_mb = 3 is retired.*write cap = "3 MiB"'):
        values(_Table, {'cap_mb': 3}, '[planted]')


def _ops(tmp_path: Path, tables: str) -> Path:
    path = tmp_path / 'supervise.toml'
    path.write_text(f'[ops]\nhome = "/h"\npython = "/opt/ops/bin/python"\nrepos = []\n{tables}', encoding='utf-8')
    return path


_CONSENT = '[ops.consent]\naccount = "consent"\ntotp = "/t"\nkey = "/k"\nstate = "/s"\n'
_BACKUP = '[ops.backup]\nsource = "b@h"\nidentity = "/i"\ndest = "/d"\nschedule = "daily"\n'


def test_the_ops_roles_read_their_durations_and_sizes(tmp_path: Path) -> None:
    lines = 'lockout = "30 min"\nhttps_window = "5 min"\nhttps_lock = "2 h"\n'
    backup = 'retention = "30 d"\n[ops.backup.offsite]\nendpoint = "https://s"\nbucket = "b"\nlabel = "l"\n'
    config = load(_ops(tmp_path, _CONSENT + lines + _BACKUP + backup + 'max_put = "1 GB"\n'), structure_only=True)
    assert config.consent is not None
    assert (config.consent.lockout, config.consent.https_window, config.consent.https_lock) == (1800.0, 300.0, 7200.0)
    assert config.backup is not None
    assert config.backup.retention == 30 * 86400.0
    assert config.backup.offsite is not None
    assert config.backup.offsite.max_put == 1e9


@pytest.mark.parametrize(
    ('table', 'line', 'match'),
    [
        (_CONSENT, 'lockout_minutes = 15', r'\[ops.consent\] lockout_minutes = 15 is retired.*lockout = "15 min"'),
        (_CONSENT, 'https_lock_minutes = 60', r'https_lock_minutes = 60 is retired.*https_lock = "60 min"'),
        (_CONSENT, 'lockout = 15', r'\[ops.consent\] lockout = 15 is a bare number'),
        (_BACKUP, 'retention_days = 14', r'\[ops.backup\] retention_days = 14 is retired.*retention = "14 d"'),
    ],
)
def test_an_ops_role_refuses_a_bare_number_and_a_retired_unit_key(
    tmp_path: Path, table: str, line: str, match: str
) -> None:
    with pytest.raises(ValueError, match=match):
        load(_ops(tmp_path, f'{table}{line}\n'), structure_only=True)
