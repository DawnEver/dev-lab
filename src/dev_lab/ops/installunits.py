"""The host's timed and supervised units ``ops install`` renders: backup, probe, follow, config tick, supervise.

Split out of :mod:`dev_lab.ops.install` (2026-11-20, MODULE-SIZE-ALARM) along its own seam: that module renders the
request-serving roles (promote, judge, break-glass, consent) and applies the result; this one renders every unit
that RUNS ON A SCHEDULE or under the supervisor, and the two primitives both share (:func:`door`, :func:`service`).
"""

from __future__ import annotations

import shlex
from typing import Final

from dev_lab.ops.access import keys_file
from dev_lab.ops.backuprole import Backup
from dev_lab.ops.config import OpsConfig, Probe
from dev_lab.ops.placement import Placement
from dev_lab.ops.upgradefollow import AUDIT
from dev_lab.supervise.daemon import watchdog_seconds

__all__ = ['SUPERVISE', 'UNIT', 'door', 'scheduled', 'service_unit']

#: The prefix of every unit ``ops install`` renders.
UNIT: Final = 'dev-lab-ops'
#: The supervisor's own service.
SUPERVISE = 'dev-lab-supervise'


def door(config: OpsConfig, *verb: str) -> str:
    """The ``dev_lab.ops`` command line running *verb* under *config*."""
    return shlex.join([config.python, '-m', 'dev_lab.ops', '--config', str(config.path), *verb])


def service_unit(
    config: OpsConfig, role: Placement, what: str, body: list[str], *, network: bool, wanted_by: str = ''
) -> str:
    """One service unit: its ordering, the environment file, its slice, then *body* under ``[Service]``."""
    online = ['network-online.target'] if network else []
    unit = [f'Description={what}']
    unit += [f'Wants={name}' for name in (*online, *role.wants)] + [f'After={name}' for name in (*online, *role.after)]
    service = [f'EnvironmentFile={config.environment_file}'] if config.environment_file else []
    service += [f'Slice={role.slice}'] if role.slice else []
    text = '[Unit]\n' + ''.join(f'{line}\n' for line in unit) + '[Service]\n'
    text += ''.join(f'{line}\n' for line in (*service, *body))
    return text + (f'[Install]\nWantedBy={wanted_by}\n' if wanted_by else '')


def _timer(config: OpsConfig, role: Backup | Probe, name: str, what: str, exec_start: str) -> dict[str, str]:
    body = ['Type=oneshot', f'User={role.user}', f'ExecStart={exec_start}', 'Nice=10']
    service = service_unit(config, role, f'{what} (dev_lab.ops)', body, network=True)
    timer = (
        f'[Unit]\nDescription={what} (dev_lab.ops)\n'
        f'[Timer]\nOnCalendar={role.schedule}\nPersistent=true\n[Install]\nWantedBy=timers.target\n'
    )
    return {f'etc/systemd/system/{UNIT}-{name}.service': service, f'etc/systemd/system/{UNIT}-{name}.timer': timer}


def _backup(config: OpsConfig) -> dict[str, str]:
    role = config.backup
    if role is None:
        return {}
    rendered: dict[str, str] = {}
    if role.dumpers:
        export = door(config, 'backup', 'export')
        keys = keys_file(role.account)
        line = f'restrict,command="sudo -n {export}" '
        rendered |= {
            f'etc/ssh/sshd_config.d/62-{UNIT}-{role.account}.conf': (
                f'Match User {role.account}\n    AuthorizedKeysFile {keys}\n    ForceCommand sudo -n {export}\n'
                '    AllowTcpForwarding no\n    AllowAgentForwarding no\n    X11Forwarding no\n    PermitTTY no\n'
            ),
            keys.lstrip('/'): ''.join(f'{line}{key}\n' for key in role.keys),
            f'etc/sudoers.d/{UNIT}-{role.account}': f'{role.account} ALL=(root) NOPASSWD: {export}\n',
        }
    if role.source:
        if not role.schedule:
            msg = '[ops.backup] pulls (source is set) but declares no schedule'
            raise ValueError(msg)
        rendered |= _timer(config, role, 'backup-pull', 'Pull the forge backup', door(config, 'backup', 'pull'))
    return rendered


def _probe(config: OpsConfig) -> dict[str, str]:
    role = config.probe
    if role is None:
        return {}
    return _timer(config, role, 'probe', 'Probe forge protection and CI runs', door(config, 'probe'))


def _root_timer(config: OpsConfig, name: str, what: str, schedule: str, *verb: str) -> dict[str, str]:
    """A root oneshot service running the door's *verb*, and its ``OnCalendar`` timer."""
    env = [f'EnvironmentFile={config.environment_file}'] if config.environment_file else []
    service = (
        f'[Unit]\nDescription={what}\nWants=network-online.target\nAfter=network-online.target\n[Service]\n'
        + ''.join(f'{line}\n' for line in (*env, 'Type=oneshot', f'ExecStart={door(config, *verb)}'))
    )
    timer = (
        f'[Unit]\nDescription={what}\n'
        f'[Timer]\nOnCalendar={schedule}\nPersistent=true\n[Install]\nWantedBy=timers.target\n'
    )
    unit = f'etc/systemd/system/{UNIT}-{name}'
    return {f'{unit}.service': service, f'{unit}.timer': timer}


def _upgrade_follow(config: OpsConfig) -> dict[str, str]:
    """The ``upgrade --follow`` timer: root, since it installs into ``[ops] python``'s environment."""
    if (role := config.upgrade) is None or not role.follow:
        return {}
    what = f'Follow {role.follow} of the dev-lab source (dev_lab.ops)'
    return _root_timer(config, 'upgrade-follow', what, role.schedule, 'upgrade', '--follow')


def _config_tick(config: OpsConfig) -> dict[str, str]:
    """The ``config tick`` timer: root, since it replaces the root-owned live file through the door."""
    if (source := config.config_source) is None or not source.schedule:
        return {}
    what = 'Apply the merged config source (dev_lab.ops)'
    return _root_timer(config, 'config-tick', what, source.schedule, 'config', 'tick')


def _supervise(config: OpsConfig) -> dict[str, str]:
    role = config.supervise
    if role is None:
        return {}
    serve = shlex.join(
        [
            config.python,
            '-m',
            'dev_lab.supervise',
            'serve',
            '--project',
            role.project,
            '--config',
            str(config.path),
            *(config.status.flags(f'{config.home.as_posix()}/{AUDIT}') if config.status else []),
        ]
    )
    # THE DAEMON SPEAKS sd_notify (`supervise.notify`): READY once, WATCHDOG once per cycle. Under
    # Type=simple nobody listens, and the timeout is the loop's own cycle, never a second literal.
    body = [
        'Type=notify',
        'NotifyAccess=main',
        f'WatchdogSec={watchdog_seconds(config.merged)}',
        *([f'User={role.user}'] if role.user else []),
        f'ExecStart={serve}',
        'Restart=always',
        'RestartSec=10',
        *([f'MemoryMax={role.memory_max}'] if role.memory_max else []),
    ]
    service = service_unit(config, role, 'Host supervisor (dev_lab.supervise)', body, network=True,
                       wanted_by='multi-user.target')  # fmt: skip
    return {f'etc/systemd/system/{SUPERVISE}.service': service}


def scheduled(config: OpsConfig) -> dict[str, str]:
    """Every scheduled or supervised unit *config* renders, by path relative to the root."""
    return {
        **_backup(config),
        **_probe(config),
        **_config_tick(config),
        **_upgrade_follow(config),
        **_supervise(config),
    }
