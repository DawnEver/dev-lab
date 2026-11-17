"""The install door carries the host's environment, renders the supervisor, prepares the promote user, places units.

G1: one declared ``[ops] environment_file`` -- every rendered unit loads it, and every verb (sudo-run ones included)
folds it in itself, so an alert channel never runs silently off; declared but unreadable is refused.
G2: ``[ops.supervise]`` renders the supervisor's own service. G3: install creates the clone home and hands the promote
user its home and credential. G5: each role may place its units (``slice``, ``after``, ``wants``); default none.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from _ops_fixtures import config

from dev_lab.ops import accounts, installpaths
from dev_lab.ops.__main__ import main
from dev_lab.ops.config import load
from dev_lab.ops.install import files, install

_SECRETS = (
    '# alert secrets\nSUPERVISE_ALERTS__TELEGRAM__ENABLED=true\n'
    'SUPERVISE_ALERTS__TELEGRAM__TOKEN="123:abc"\nSUPERVISE_ALERTS__TELEGRAM__CHAT=42\n'
)
_PULL = """[ops.backup]
source = "forgebackup@forge.example"
identity = "/srv/backup/.ssh/id"
dest = "/srv/backup/forge"
schedule = "*-*-* 03:30:00"
"""
_SUPERVISE = '[ops.supervise]\nproject = "/srv/target"\n'


def _host(tmp_path: Path, *, env: str | None = _SECRETS, extra: str = '') -> Path:
    head = ''
    if env is not None:
        (tmp_path / 'ops.env').write_text(env, encoding='utf-8')
        head = f'environment_file = "{(tmp_path / "ops.env").as_posix()}"\n'
    host = config(tmp_path, [], extra=extra)
    text = host.path.read_text(encoding='utf-8').replace('[ops]\n', f'[ops]\n{head}', 1)
    host.path.write_text(text, encoding='utf-8')
    return host.path


def _units(rendered: dict[str, str]) -> dict[str, str]:
    return {path: text for path, text in rendered.items() if path.endswith('.service')}


def test_every_rendered_service_loads_the_declared_environment_file(tmp_path: Path) -> None:
    path = _host(tmp_path, extra=_PULL + _SUPERVISE)
    units = _units(files(load(path, environ={}, as_root=True)))
    assert {Path(p).name for p in units} == {
        'dev-lab-ops-promote.service', 'dev-lab-ops-breakglass-tick.service',
        'dev-lab-ops-backup-pull.service', 'dev-lab-supervise.service',
    }  # fmt: skip
    for unit in units.values():
        assert f'EnvironmentFile={(tmp_path / "ops.env").as_posix()}\n' in unit


def test_no_environment_file_is_rendered_when_none_is_declared(tmp_path: Path) -> None:
    path = _host(tmp_path, env=None, extra=_PULL)
    assert not any('EnvironmentFile' in unit for unit in _units(files(load(path, environ={}, as_root=True))).values())


def test_a_verb_run_under_sudo_reads_its_alert_secrets_from_the_declared_file(tmp_path: Path) -> None:
    # sudo resets the environment: nothing arrives, the file alone must turn the channel on
    telegram = load(_host(tmp_path), environ={}, as_root=True).merged['alerts']['telegram']
    assert (telegram['enabled'], telegram['token'], telegram['chat']) == (True, '123:abc', 42)


def test_the_invoking_environment_cannot_switch_a_declared_channel_off(tmp_path: Path) -> None:
    host = load(_host(tmp_path), environ={'SUPERVISE_ALERTS__TELEGRAM__ENABLED': 'false'}, as_root=True)
    assert host.merged['alerts']['telegram']['enabled'] is True


def test_the_sudoers_line_forwards_no_secret_from_the_caller(tmp_path: Path) -> None:
    sudo = files(load(_host(tmp_path), environ={}, as_root=True))['etc/sudoers.d/dev-lab-ops-breakglass']
    assert 'SUPERVISE' not in sudo


def test_a_root_verb_refuses_a_declared_but_unreadable_environment_file(tmp_path: Path) -> None:
    path = _host(tmp_path)
    assert load(path, environ={}, as_root=True).merged['alerts']['telegram']['enabled'] is True  # control: readable
    (tmp_path / 'ops.env').unlink()
    with pytest.raises(ValueError, match='unreadable'):
        load(path, environ={}, as_root=True)


def _from_systemd() -> dict[str, str]:
    return {'SUPERVISE_ALERTS__TELEGRAM__ENABLED': 'true', 'SUPERVISE_ALERTS__TELEGRAM__TOKEN': '9:z',
            'SUPERVISE_ALERTS__TELEGRAM__CHAT': '7'}  # fmt: skip


def test_a_non_root_verb_takes_its_secrets_from_the_environment_systemd_handed_it(tmp_path: Path) -> None:
    path = _host(tmp_path)
    (tmp_path / 'ops.env').unlink()  # the root-only file: a non-owner must never need to read it
    telegram = load(path, environ=_from_systemd(), as_root=False).merged['alerts']['telegram']
    assert (telegram['enabled'], telegram['token']) == (True, '9:z')


def test_a_non_root_verb_with_neither_file_nor_environment_refuses(tmp_path: Path) -> None:
    path = _host(tmp_path)
    (tmp_path / 'ops.env').unlink()
    with pytest.raises(ValueError, match='EnvironmentFile='):
        load(path, environ={}, as_root=False)
    assert main(['--config', str(path), 'promote']) == 2


def test_an_environment_line_that_is_not_an_assignment_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match='KEY=VALUE'):
        load(_host(tmp_path, env='SUPERVISE_ALERTS__TELEGRAM__ENABLED true\n'), environ={}, as_root=True)


def test_the_supervisor_service_is_rendered_from_its_table(tmp_path: Path) -> None:
    table = '[ops.supervise]\nproject = "/srv/target"\nmemory_max = "300M"\n'
    host = load(_host(tmp_path, extra=table), environ={}, as_root=True)
    unit = files(host)['etc/systemd/system/dev-lab-supervise.service']
    assert '-m dev_lab.supervise serve --project /srv/target --config ' in unit
    assert host.path.as_posix() in unit.replace('\\', '/')
    for line in ('Restart=always', 'MemoryMax=300M', 'WantedBy=multi-user.target'):
        assert f'{line}\n' in unit
    assert 'User=' not in unit


def test_no_supervisor_service_without_its_table(tmp_path: Path) -> None:
    assert not any('supervise' in path for path in files(load(_host(tmp_path), environ={}, as_root=True)))


def test_units_carry_the_declared_slice_and_ordering_and_none_by_default(tmp_path: Path) -> None:
    plain = files(load(_host(tmp_path), environ={}, as_root=True))['etc/systemd/system/dev-lab-ops-promote.service']
    assert 'Slice=' not in plain
    assert 'gitea' not in plain
    placed = tmp_path / 'placed'
    placed.mkdir()
    path = _host(placed)
    text = path.read_text(encoding='utf-8').replace(
        'credentials = ', 'slice = "core.slice"\nafter = ["gitea.service"]\nwants = ["gitea.service"]\ncredentials = '
    )
    path.write_text(text, encoding='utf-8')
    unit = files(load(path, environ={}, as_root=True))['etc/systemd/system/dev-lab-ops-promote.service']
    for line in ('Slice=core.slice', 'After=gitea.service', 'Wants=gitea.service', 'After=network-online.target'):
        assert f'{line}\n' in unit


def _under(root: Path, path: Path) -> Path:
    return root / path.relative_to(path.anchor)


def test_install_creates_the_clone_home_and_hands_the_promote_user_its_home_and_credential(tmp_path: Path) -> None:
    host = load(_host(tmp_path), environ={}, as_root=True)
    assert host.promote is not None
    root = tmp_path / 'root'
    credential = _under(root, Path(host.promote.credentials))
    credential.parent.mkdir(parents=True)
    credential.write_text('https://bot:x@forge.example\n', encoding='utf-8')
    calls: list[tuple[Path, str | None, str | None]] = []
    first = install(host, root, chown=lambda p, u, g: calls.append((p, u, g)))
    home = _under(root, host.home)
    assert home.is_dir()
    assert first.paths[home.relative_to(root).as_posix()] == 'created'
    assert (home, 'promote', 'promote') in calls
    assert (credential, 'promote', None) in calls
    assert not any(step.startswith('chown promote') for step in first.next_steps)
    again = install(host, root, chown=lambda *_: None)
    assert again.paths[home.relative_to(root).as_posix()] == 'unchanged'


def test_install_never_widens_a_credential_directory_or_re_owns_a_home_it_did_not_create(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    host = load(_host(tmp_path), environ={}, as_root=True)
    assert host.promote is not None
    root = tmp_path / 'root'
    credential = _under(root, Path(host.promote.credentials))
    credential.parent.mkdir(parents=True)  # a /root-like directory, 0700: others cannot enter
    credential.write_text('x', encoding='utf-8')
    home = _under(root, host.home)
    home.mkdir(parents=True)  # an existing deploy:deploy 0750 home
    mode = home.stat().st_mode
    monkeypatch.setattr(installpaths, '_may_enter', lambda path, _user: path != credential.parent)
    calls: list[tuple[Path, str | None, str | None]] = []
    done = install(host, root, chown=lambda p, u, g: calls.append((p, u, g)))
    assert not any(path in {credential.parent, home} for path, _, _ in calls)
    assert home.stat().st_mode == mode
    assert done.paths[home.relative_to(root).as_posix()] == 'unchanged'
    assert any('cannot enter' in step for step in done.next_steps)
    assert (credential, 'promote', None) in calls  # control: the declared credential itself is still handed over


def test_a_render_without_root_leaves_ownership_as_next_steps(tmp_path: Path) -> None:
    host = load(_host(tmp_path), environ={}, as_root=True)
    assert host.promote is not None
    steps = install(host, tmp_path / 'root').next_steps
    home = host.home.as_posix()
    assert f'chown promote:promote {home}' in steps
    assert any(step.startswith(f'chown promote {host.promote.credentials}') for step in steps)
    assert any(step.startswith('chown root:root ') and 'ops.env' in step for step in steps)
    useradd = next(i for i, step in enumerate(steps) if 'useradd' in step and 'promote' in step)
    assert steps.index(f'chown promote:promote {home}') > useradd


_PROMOTE = accounts.Account(uid=1001, gids=frozenset({1001}))


@pytest.mark.parametrize(
    ('mode', 'uid', 'gid', 'account', 'enters'),
    [
        (0o750, 0, 1001, _PROMOTE, True),  # root:promote 750 -- the deployed /etc/promote; the group enters
        (0o750, 0, 0, _PROMOTE, False),  # planted control: root:root 750, promote is no member
        (0o700, 1001, 0, _PROMOTE, True),  # owner
        (0o070, 1001, 0, _PROMOTE, False),  # the owner class decides for the owner, never the group's bits
        (0o751, 0, 0, _PROMOTE, True),  # other-execute
        (0o710, 0, 50, accounts.Account(uid=1001, gids=frozenset({1001, 50})), True),  # a supplementary group
        (0o700, 5, 5, accounts.Account(uid=0, gids=frozenset({0})), True),  # root enters anything
    ],
)
def test_entering_is_decided_by_the_users_owner_group_or_other_class(
    mode: int, uid: int, gid: int, account: accounts.Account, *, enters: bool
) -> None:
    assert accounts.may_enter(mode, uid, gid, account) is enters


def test_an_account_not_yet_made_is_judged_by_the_other_bits() -> None:
    shut = accounts.may_enter(0o750, 0, 1001, None)
    assert (shut, accounts.may_enter(0o751, 0, 1001, None)) == (False, True)


@pytest.mark.parametrize(
    ('cycle', 'watchdog'), [('', 900), ('[cycle]\ninterval = 600\n', 1800), ('[cycle]\ninterval = 1\n', 15)]
)
def test_the_supervisor_service_is_watched_on_its_own_cycle(tmp_path: Path, cycle: str, watchdog: int) -> None:
    """The daemon speaks sd_notify, so the unit is Type=notify and its WatchdogSec is the loop's cycle, derived.

    The planted control is the interval itself: a changed ``cycle.interval`` (or one under the loop's floor) moves
    WatchdogSec with it, which a second literal in the renderer could not do.
    """
    host = load(_host(tmp_path, extra=_SUPERVISE + cycle), environ={}, as_root=True)
    unit = files(host)['etc/systemd/system/dev-lab-supervise.service']
    for line in ('Type=notify', 'NotifyAccess=main', f'WatchdogSec={watchdog}', 'Restart=always', 'RestartSec=10'):
        assert f'{line}\n' in unit
    assert 'Type=simple' not in unit


def test_the_break_glass_tick_reaches_the_forge(tmp_path: Path) -> None:
    # the tick lands an open wave's green PRs (dev_lab.ops.wavesweep): it must wait for the network
    path = _host(tmp_path, extra=_PULL)
    units = _units(files(load(path, environ={}, as_root=True)))
    tick = next(text for unit, text in units.items() if unit.endswith('breakglass-tick.service'))
    assert 'network-online.target' in tick
