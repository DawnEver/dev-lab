"""The install door renders the backup role's forced command and timer, and the ops-access PAM/sshd/sudoers files."""

from __future__ import annotations

from pathlib import Path

import pytest

from dev_lab.ops.access import enrol
from dev_lab.ops.config import Access, load
from dev_lab.ops.install import files, install


def _config(tmp_path: Path, tables: str) -> Path:
    path = tmp_path / 'supervise.toml'
    path.write_text(f'[ops]\nhome = "/h"\npython = "/opt/ops/bin/python"\nrepos = []\n{tables}', encoding='utf-8')
    return path


_EXPORT = """[ops.backup]
dumpers = ["gitea", "postgresql"]
account = "forgebackup"
keys = ["ssh-ed25519 AAAA puller"]
gitea_config = "/etc/gitea/app.ini"
pg_database = "gitea"
"""

_PULL = """[ops.backup]
source = "forgebackup@forge.example"
identity = "/srv/backup/.ssh/id_ed25519"
dest = "/srv/backup/forge"
schedule = "*-*-* 03:30:00"
[ops.backup.offsite]
endpoint = "https://store.example"
bucket = "forge-backups"
label = "host-a"
"""

_ACCESS = """[ops.access]
account = "ops"
keys = ["ssh-ed25519 AAAA agent"]
commands = ["/usr/bin/journalctl *", "/usr/bin/systemctl restart gitea"]
"""


def test_the_export_side_renders_a_restricted_forced_command(tmp_path: Path) -> None:
    rendered = files(load(_config(tmp_path, _EXPORT), environ={}))
    keys = rendered['etc/dev-lab/ops/forgebackup.keys']
    assert keys.startswith('restrict,command="sudo -n /opt/ops/bin/python -m dev_lab.ops --config ')
    assert keys.rstrip().endswith('backup export" ssh-ed25519 AAAA puller')
    assert rendered['etc/sudoers.d/dev-lab-ops-forgebackup'].endswith('backup export\n')
    assert 'ForceCommand sudo -n' in rendered['etc/ssh/sshd_config.d/62-dev-lab-ops-forgebackup.conf']


def test_the_pull_side_renders_its_timer_and_reads_the_offsite_table(tmp_path: Path) -> None:
    config = load(_config(tmp_path, _PULL), environ={})
    assert config.backup is not None
    assert config.backup.offsite is not None
    assert config.backup.offsite.max_put_bytes == 5_000_000_000
    rendered = files(config)
    assert 'OnCalendar=*-*-* 03:30:00' in rendered['etc/systemd/system/dev-lab-ops-backup-pull.timer']
    assert 'User=backup' in rendered['etc/systemd/system/dev-lab-ops-backup-pull.service']


def test_a_pull_without_a_schedule_is_refused(tmp_path: Path) -> None:
    config = load(_config(tmp_path, _PULL.replace('schedule = "*-*-* 03:30:00"\n', '')), environ={})
    with pytest.raises(ValueError, match='no schedule'):
        files(config)


def test_an_unknown_offsite_key_is_refused_at_load(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match='unknown keys'):
        load(_config(tmp_path, _PULL + 'multipart = true\n'), environ={})


def test_access_requires_key_and_code_and_narrows_sudo(tmp_path: Path) -> None:
    config = load(_config(tmp_path, _ACCESS), environ={})
    rendered = files(config)
    sshd = rendered['etc/ssh/sshd_config.d/61-dev-lab-ops-ops.conf']
    assert 'AuthenticationMethods publickey,keyboard-interactive' in sshd
    for off in ('AllowTcpForwarding no', 'AllowAgentForwarding no', 'X11Forwarding no', 'PermitTunnel no'):
        assert off in sshd
    pam = rendered['etc/pam.d/dev-lab-ops-access'].splitlines()
    assert pam[1] == 'auth [success=ignore default=1] pam_succeed_if.so quiet user = ops'
    assert pam[2].startswith('auth [success=done default=die] pam_oath.so usersfile=/etc/dev-lab/ops/users.oath')
    sudo = rendered['etc/sudoers.d/dev-lab-ops-ops']
    assert sudo == 'ops ALL=(root) NOPASSWD: /usr/bin/journalctl *, /usr/bin/systemctl restart gitea\n'
    done = install(config, tmp_path / 'root')
    assert any('libpam-oath' in step for step in done.next_steps)


def test_a_command_carrying_sudoers_syntax_is_refused(tmp_path: Path) -> None:
    config = load(_config(tmp_path, _ACCESS.replace('restart gitea', 'restart gitea, ALL')), environ={})
    with pytest.raises(ValueError, match='sudoers syntax'):
        files(config)


def test_enrol_writes_one_pam_oath_line_and_returns_the_uri(tmp_path: Path) -> None:
    role = Access(account='ops', oath=str(tmp_path / 'users.oath'))
    said = enrol(role)
    line = (tmp_path / 'users.oath').read_text(encoding='utf-8')
    assert line.startswith('HOTP/T30/6 ops - ')
    assert len(line.split()[-1]) == 40  # a 160-bit secret in hex
    assert said.startswith('otpauth://totp/forge%20ops%3Aops?')
