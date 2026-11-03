"""The one install door renders every file the config asks for, idempotently, from the config alone."""

from __future__ import annotations

from pathlib import Path

import pytest
from _ops_fixtures import config

from dev_lab.ops.__main__ import main
from dev_lab.ops.config import load
from dev_lab.ops.install import files, install


def test_install_renders_units_sshd_and_sudoers_and_is_idempotent(tmp_path: Path) -> None:
    host = config(tmp_path, ['https://forge.example/owner/alpha.git'])
    root = tmp_path / 'root'
    first = install(host, root)
    assert set(first.paths.values()) == {'written'}
    assert set(install(host, root).paths.values()) == {'unchanged'}
    rendered = files(host)
    timer = rendered['etc/systemd/system/dev-lab-ops-promote.timer']
    assert 'OnCalendar=*-*-* 04:30:00 Europe/London' in timer
    sshd = rendered['etc/ssh/sshd_config.d/60-dev-lab-ops-breakglass.conf']
    assert 'Match User breakglass' in sshd
    assert 'breakglass serve' in sshd
    assert 'ExposeAuthInfo yes' in sshd
    assert rendered['etc/dev-lab/ops/breakglass.keys'] == 'ssh-ed25519 AAAA agent\n'
    sudo = rendered['etc/sudoers.d/dev-lab-ops-breakglass']
    assert sudo.startswith('Defaults:breakglass env_keep += "SSH_USER_AUTH"\nbreakglass ALL=(root) NOPASSWD: ')


def test_a_disabled_role_renders_nothing(tmp_path: Path) -> None:
    host = config(tmp_path, [], extra='')
    text = host.path.read_text(encoding='utf-8').replace('[ops.breakglass]', '[ops.breakglass]\nenabled = false')
    host.path.write_text(text, encoding='utf-8')
    assert not any('breakglass' in path for path in files(load(host.path, environ={})))


def test_no_host_fact_is_in_the_code() -> None:
    package = Path(__file__).resolve().parents[1] / 'src' / 'dev_lab' / 'ops'
    for source in package.glob('*.py'):
        text = source.read_text(encoding='utf-8')
        for fact in ('motronics', 'wdg-lab', 'Tianjie', 'mingyangbao', '79.72', '152.67', 'Europe/London'):
            assert fact not in text, (source.name, fact)


@pytest.mark.parametrize(
    ('table', 'why'),
    [
        ('[ops.promote]\nuser = "p"\nschedule = "daily"\ncredentials = "c"\ntypo = 1\n', 'unknown keys'),
        ('[ops.promote]\nuser = "p"\n', 'promote'),
    ],
)
def test_a_bad_role_table_is_refused_at_load(tmp_path: Path, table: str, why: str) -> None:
    path = tmp_path / 'supervise.toml'
    path.write_text(f'[ops]\nhome = "h"\npython = "p"\nrepos = []\n{table}', encoding='utf-8')
    with pytest.raises(ValueError, match=why):
        load(path, environ={})


def test_a_duplicate_repo_name_is_refused(tmp_path: Path) -> None:
    path = tmp_path / 'supervise.toml'
    path.write_text(
        '[ops]\nhome = "h"\npython = "p"\nrepos = ["https://a/x/r.git", "https://b/y/r"]\n', encoding='utf-8'
    )
    with pytest.raises(ValueError, match='twice'):
        load(path, environ={})


def test_the_door_refuses_a_file_with_no_ops_table(tmp_path: Path) -> None:
    path = tmp_path / 'supervise.toml'
    path.write_text('[target]\nname = "x"\n', encoding='utf-8')
    assert main(['--config', str(path), 'install', '--root', str(tmp_path / 'r')]) == 2
