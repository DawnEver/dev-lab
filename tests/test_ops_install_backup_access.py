"""The install door renders the backup role's forced command and timer, and the ops-access PAM/sshd/sudoers files."""

from __future__ import annotations

import io
import os
import stat
import sys
from pathlib import Path

import pytest

from dev_lab.ops.__main__ import main
from dev_lab.ops.access import adopt, enrol, ensure_include, oath_users, secret_file
from dev_lab.ops.config import Access, load
from dev_lab.ops.install import files, install
from dev_lab.ops.totp import TotpRefused, write_private


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

_STACK = """# PAM configuration for the Secure Shell service

@include common-auth
account required pam_nologin.so
"""


def _pam_root(tmp_path: Path, stack: str = _STACK) -> Path:
    root = tmp_path / 'root'
    (root / 'etc/pam.d').mkdir(parents=True)
    (root / 'etc/pam.d/sshd').write_text(stack, encoding='utf-8')
    return root


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
    config = load(_config(tmp_path, _ACCESS + 'totp = "/etc/breakglass/totp"\n'), environ={})
    rendered = files(config)
    sshd = rendered['etc/ssh/sshd_config.d/61-dev-lab-ops-ops.conf']
    assert 'AuthenticationMethods publickey,keyboard-interactive' in sshd
    for off in ('AllowTcpForwarding no', 'AllowAgentForwarding no', 'X11Forwarding no', 'PermitTunnel no'):
        assert off in sshd
    pam = rendered['etc/pam.d/dev-lab-ops-access'].splitlines()
    assert pam[1] == 'auth [success=ignore default=1] pam_succeed_if.so quiet user = ops'
    assert pam[2].startswith('auth [success=done default=die] pam_oath.so usersfile=/etc/dev-lab/ops/users.oath')
    assert not any(path.endswith(('totp', 'users.oath')) for path in rendered)  # secrets are never rendered
    sudo = rendered['etc/sudoers.d/dev-lab-ops-ops']
    assert sudo == 'ops ALL=(root) NOPASSWD: /usr/bin/journalctl *, /usr/bin/systemctl restart gitea\n'
    done = install(config, _pam_root(tmp_path))
    assert any('libpam-oath' in step for step in done.next_steps)
    assert not any('@include' in step for step in done.next_steps)


def test_a_command_carrying_sudoers_syntax_is_refused(tmp_path: Path) -> None:
    tables = _ACCESS.replace('restart gitea', 'restart gitea, ALL') + 'totp = "/t"\n'
    config = load(_config(tmp_path, tables), environ={})
    with pytest.raises(ValueError, match='sudoers syntax'):
        files(config)


def _host(tmp_path: Path, tables: str = '') -> Path:
    """An access config whose one TOTP secret and users file live under *tmp_path*."""
    secret, oath = (tmp_path / 'totp').as_posix(), (tmp_path / 'users.oath').as_posix()
    return _config(tmp_path, f'{_ACCESS}totp = "{secret}"\noath = "{oath}"\n{tables}')


def test_enrol_makes_the_one_secret_derives_the_users_file_and_returns_the_uri(tmp_path: Path) -> None:
    config = load(_host(tmp_path), environ={})
    said = enrol(config)
    secret = (tmp_path / 'totp').read_text(encoding='utf-8').strip()
    line = (tmp_path / 'users.oath').read_text(encoding='utf-8')
    assert line == oath_users(Access(account='ops'), secret)
    assert line.startswith('HOTP/T30/6 ops - ')
    assert len(line.split()[-1]) == 40  # a 160-bit secret in hex
    assert said.startswith('otpauth://totp/forge%20ops%3Aops?')
    assert f'secret={secret}' in said


def test_enrol_refuses_when_the_host_already_holds_its_secret(tmp_path: Path) -> None:
    config = load(_host(tmp_path), environ={})
    (tmp_path / 'totp').write_text('JBSWY3DPEHPK3PXP\n', encoding='utf-8')
    with pytest.raises(TotpRefused, match='existing enrolment is reused'):
        enrol(config)
    assert (tmp_path / 'totp').read_text(encoding='utf-8') == 'JBSWY3DPEHPK3PXP\n'
    assert not (tmp_path / 'users.oath').exists()


_ISSUER = """[ops.consent]
account = "consent"
totp = "/etc/consent/totp"
key = "/etc/consent/key"
state = "/s"
"""


def test_access_reads_the_issuer_secret_when_it_declares_none(tmp_path: Path) -> None:
    glass = (tmp_path / 'consent-totp').as_posix()
    tables = _ISSUER.replace('/etc/consent/totp', glass)
    config = load(_config(tmp_path, _ACCESS + tables), environ={})
    assert secret_file(config) == glass


def test_two_totp_secrets_on_one_host_are_refused(tmp_path: Path) -> None:
    tables = _ISSUER
    two = load(_config(tmp_path, _ACCESS + 'totp = "/etc/other/totp"\n' + tables), environ={})
    with pytest.raises(ValueError, match='two TOTP secrets on one host'):
        files(two)
    one = load(_config(tmp_path, _ACCESS + 'totp = "/etc/consent/totp"\n' + tables), environ={})
    assert secret_file(one) == '/etc/consent/totp'  # the planted control: the same file is one secret


def test_install_derives_the_users_file_from_the_one_secret(tmp_path: Path) -> None:
    root = _pam_root(tmp_path)
    phone = 'JBSWY3DPEHPK3PXP'
    (root / 'etc/breakglass').mkdir(parents=True)
    (root / 'etc/breakglass/totp').write_text(phone + '\n', encoding='utf-8')
    config = load(_config(tmp_path, _ACCESS + 'totp = "/etc/breakglass/totp"\n'), environ={})
    done = install(config, root)
    oath = root / 'etc/dev-lab/ops/users.oath'
    assert oath.read_text(encoding='utf-8') == oath_users(config.access or Access(account=''), phone)
    assert oath.read_text(encoding='utf-8').endswith(' 48656c6c6f21deadbeef' + chr(10))  # planted: the RFC base32 of it
    assert done.paths['etc/dev-lab/ops/users.oath'] == 'written'
    if sys.platform != 'win32':
        assert stat.S_IMODE(oath.stat().st_mode) == 0o600


def test_install_without_a_secret_derives_nothing_and_names_enrol_or_adopt(tmp_path: Path) -> None:
    config = load(_host(tmp_path), environ={})
    done = install(config, _pam_root(tmp_path))
    assert not any(path.endswith('users.oath') for path in done.paths)
    assert any('access enrol' in step and 'access adopt' in step for step in done.next_steps)


def test_adopt_places_an_existing_secret_without_echoing_it(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    phone = 'JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP'
    monkeypatch.setattr('sys.stdin', io.StringIO(phone + '\n'))
    assert main(['--config', str(_host(tmp_path)), 'access', 'adopt']) == 0
    said = capsys.readouterr()
    assert phone not in said.out + said.err
    assert 'adopted' in said.out
    assert (tmp_path / 'totp').read_text(encoding='utf-8') == phone + '\n'
    assert (tmp_path / 'users.oath').read_text(encoding='utf-8') == oath_users(Access(account='ops'), phone)


def test_adopt_refuses_a_different_secret_and_a_malformed_one(tmp_path: Path) -> None:
    config = load(_host(tmp_path), environ={})
    assert adopt(config, 'JBSWY3DPEHPK3PXP').startswith('adopted')
    assert adopt(config, 'jbswy3dpehpk3pxp').startswith('already held')  # the control: the same secret
    with pytest.raises(TotpRefused, match='different secret'):
        adopt(config, 'GEZDGNBVGY3TQOJQ')
    (tmp_path / 'x').mkdir()
    other = load(_config(tmp_path / 'x', _ACCESS + f'totp = "{(tmp_path / "t2").as_posix()}"\n'), environ={})
    with pytest.raises(TotpRefused, match='base32'):
        adopt(other, 'not-a-secret!')


def test_install_puts_the_include_above_common_auth_once(tmp_path: Path) -> None:
    config = load(_host(tmp_path), environ={})
    root = _pam_root(tmp_path)
    first = install(config, root)
    stack = (root / 'etc/pam.d/sshd').read_text(encoding='utf-8').splitlines()
    assert stack[2:4] == ['@include dev-lab-ops-access', '@include common-auth']
    assert first.paths['etc/pam.d/sshd'] == 'written'
    again = install(config, root)
    assert again.paths['etc/pam.d/sshd'] == 'unchanged'
    assert (root / 'etc/pam.d/sshd').read_text(encoding='utf-8').count('dev-lab-ops-access') == 1


@pytest.mark.parametrize(
    ('stack', 'why'),
    [
        ('auth required pam_unix.so\n@include common-auth\n', 'first auth line'),
        ('account required pam_nologin.so\n', 'first auth line'),
        ('@include common-auth\n@include dev-lab-ops-access\n', 'below'),
    ],
)
def test_an_unexpected_pam_stack_is_refused_before_anything_is_written(tmp_path: Path, stack: str, why: str) -> None:
    config = load(_host(tmp_path), environ={})
    root = _pam_root(tmp_path, stack)
    with pytest.raises(ValueError, match=why):
        install(config, root)
    assert not (root / 'etc/ssh').exists()
    assert (root / 'etc/pam.d/sshd').read_text(encoding='utf-8') == stack


def test_an_absent_pam_stack_is_refused(tmp_path: Path) -> None:
    config = load(_host(tmp_path), environ={})
    with pytest.raises(ValueError, match='absent'):
        install(config, tmp_path / 'root')


def test_an_include_already_above_is_left_alone() -> None:
    assert ensure_include('@include dev-lab-ops-access\n@include common-auth\n') is None


def test_install_creates_the_keys_directory_once(tmp_path: Path) -> None:
    config = load(_host(tmp_path), environ={})
    root = _pam_root(tmp_path)
    owned: list[tuple[Path, str | None, str | None]] = []
    first = install(config, root, chown=lambda path, user, group: owned.append((path, user, group)))
    keys = root / 'etc/dev-lab/ops'
    assert first.paths['etc/dev-lab/ops'] == 'created'
    assert (keys, 'root', 'root') in owned
    if sys.platform != 'win32':
        assert stat.S_IMODE(keys.stat().st_mode) == 0o755
    assert install(config, root).paths['etc/dev-lab/ops'] == 'unchanged'


def test_access_forwards_nothing_unless_permit_open_names_targets(tmp_path: Path) -> None:
    jump = load(_host(tmp_path, 'permit_open = ["192.0.2.22:22", "[fd00::1]:22"]\n'), environ={})
    sshd = files(jump)['etc/ssh/sshd_config.d/61-dev-lab-ops-ops.conf']
    assert '    AllowTcpForwarding local\n    PermitOpen 192.0.2.22:22 [fd00::1]:22\n' in sshd
    assert 'AllowTcpForwarding no' not in sshd
    for off in ('AllowAgentForwarding no', 'AllowStreamLocalForwarding no', 'X11Forwarding no', 'PermitTunnel no'):
        assert off in sshd
    plain = files(load(_host(tmp_path), environ={}))['etc/ssh/sshd_config.d/61-dev-lab-ops-ops.conf']
    assert 'AllowTcpForwarding no' in plain
    assert 'PermitOpen' not in plain


@pytest.mark.parametrize('target', ['192.0.2.22', 'any', '192.0.2.22:22 extra:1', 'h:0', 'h:70000', 'h:22\\nMatch all'])
def test_a_permit_open_target_that_is_not_host_port_is_refused(tmp_path: Path, target: str) -> None:
    config = load(_host(tmp_path, f'permit_open = ["{target}"]\n'), environ={})
    with pytest.raises(ValueError, match='host:port'):
        files(config)


def test_access_enrol_draws_a_qr_on_stdout_and_uri_prints_only_the_uri(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = _host(tmp_path)
    assert main(['--config', str(path), 'access', 'enrol']) == 0
    drawn = capsys.readouterr()
    assert 'otpauth://' not in drawn.out
    assert '█' in drawn.out
    assert len(drawn.out.splitlines()) > 10
    assert main(['--config', str(path), 'access', 'enrol']) == 2  # the secret exists: reused, not re-enrolled
    assert 'reused' in capsys.readouterr().err
    assert main(['--config', str(path), 'access', 'enrol', '--force', '--uri']) == 0
    assert capsys.readouterr().out.startswith('otpauth://totp/')


def test_a_preexisting_world_readable_users_file_is_narrowed_even_when_unchanged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _pam_root(tmp_path)
    phone = 'JBSWY3DPEHPK3PXP'
    (root / 'etc/breakglass').mkdir(parents=True)
    (root / 'etc/breakglass/totp').write_text(phone + '\n', encoding='utf-8')
    config = load(_config(tmp_path, _ACCESS + 'totp = "/etc/breakglass/totp"\n'), environ={})
    oath = root / 'etc/dev-lab/ops/users.oath'
    oath.parent.mkdir(parents=True)
    oath.write_text(oath_users(Access(account='ops'), phone), encoding='utf-8')
    oath.chmod(0o644)
    narrowed: list[tuple[Path, int]] = []
    real = Path.chmod
    monkeypatch.setattr(Path, 'chmod', lambda path, mode: (narrowed.append((path, mode)), real(path, mode))[1])
    assert install(config, root).paths['etc/dev-lab/ops/users.oath'] == 'unchanged'
    assert (oath, 0o600) in narrowed
    if sys.platform != 'win32':
        assert stat.S_IMODE(oath.stat().st_mode) == 0o600


def test_write_private_narrows_before_a_byte_is_written(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = tmp_path / 'secret'
    target.write_text('old', encoding='utf-8')
    target.chmod(0o644)
    seen: list[int] = []  # the file's size when the mode was narrowed
    if sys.platform != 'win32':  # POSIX narrows the descriptor; Windows has no fchmod
        real = os.fchmod
        monkeypatch.setattr(os, 'fchmod', lambda fd, mode: (seen.append(os.fstat(fd).st_size), real(fd, mode))[1])
    else:
        real_chmod = Path.chmod
        monkeypatch.setattr(
            Path, 'chmod', lambda path, mode: (seen.append(path.stat().st_size), real_chmod(path, mode))[1]
        )
    write_private(target, 'NEWSECRET\n')
    assert seen == [0]
    assert target.read_text(encoding='utf-8') == 'NEWSECRET\n'
    if sys.platform != 'win32':
        assert stat.S_IMODE(target.stat().st_mode) == 0o600


@pytest.mark.parametrize('role', ['access', 'consent'])
def test_enrol_without_segno_prints_the_uri_and_still_enrols(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch, role: str
) -> None:
    monkeypatch.setitem(sys.modules, 'segno', None)
    issuer = _ISSUER.replace('/etc/consent/totp', (tmp_path / 'totp').as_posix())
    path = _host(tmp_path, issuer) if role == 'consent' else _host(tmp_path)
    assert main(['--config', str(path), role, 'enrol']) == 0
    said = capsys.readouterr()
    assert said.out.startswith('otpauth://totp/')
    assert 'dev-lab[ops]' in said.err
    assert (tmp_path / 'totp').read_text(encoding='utf-8').strip() in said.out


def test_the_enrol_next_step_reads_the_secret_under_the_root(tmp_path: Path) -> None:
    root = _pam_root(tmp_path)
    config = load(_config(tmp_path, _ACCESS + 'totp = "/etc/dev-lab/ops/totp"\n'), environ={})
    assert any('access enrol' in step for step in install(config, root).next_steps)
    (root / 'etc/dev-lab/ops/totp').write_text('JBSWY3DPEHPK3PXP\n', encoding='utf-8')
    assert not any('access enrol' in step for step in install(config, root).next_steps)


def test_permit_open_accepts_the_highest_port(tmp_path: Path) -> None:
    sshd = files(load(_host(tmp_path, 'permit_open = ["h:65535", "h:1"]\n'), environ={}))
    assert 'PermitOpen h:65535 h:1' in sshd['etc/ssh/sshd_config.d/61-dev-lab-ops-ops.conf']
