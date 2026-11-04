"""THE ONE INSTALL DOOR of the host roles: render every file the configuration asks for, under a root.

Idempotent: a file whose content is already what the config renders is not rewritten, and the result names
each path ``written`` or ``unchanged``. Rendering never runs a host command; the commands that make a change live
-- create the accounts, reload systemd, test and reload sshd -- are returned as :data:`Rendered.next_steps` for the
operator, because they need root on the live host and a test root has none.

Every service it renders -- the roles' and the supervisor's own (``[ops.supervise]``) -- loads the declared
``[ops] environment_file`` (:mod:`dev_lab.ops.config`) and sits where its role's ``slice`` / ``after`` / ``wants``
place it. The sudo-reached verbs get no sudoers ``env_keep`` for that file: they read it themselves as root, so the
secrets never pass through the invoking account and that account cannot override them.

It also PREPARES what the promote run needs: it creates an absent clone ``home`` (0750) and, given a ``chown`` (the
door passes one when it runs as root), hands the promote user that home and its credential (0600), and makes the
environment file root's, 0600. What it cannot apply -- no root, no account yet, no file yet -- is a next step. It
NEVER re-owns or widens a directory it did not create: an existing home is left as it is, and a credential directory
the promote user cannot enter is named in a next step, never opened.
"""

from __future__ import annotations

import shlex
import stat
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from dev_lab.ops.access import PAM_INCLUDE
from dev_lab.ops.access import files as access_files
from dev_lab.ops.config import Backup, OpsConfig, Placement, Probe
from dev_lab.ops.sshkey import ENV
from dev_lab.supervise.daemon import watchdog_seconds

if sys.platform != 'win32':  # the host accounts: POSIX only
    import grp
    import pwd

__all__ = ['Account', 'Chown', 'Rendered', 'account_of', 'files', 'install', 'may_enter']

_UNIT = 'dev-lab-ops'
#: The supervisor's own service.
_SUPERVISE = 'dev-lab-supervise'

#: Change a path's owner and/or group (``shutil.chown``'s shape); ``LookupError`` when the account does not exist.
type Chown = Callable[[Path, str | None, str | None], None]


@dataclass(frozen=True)
class Rendered:
    """What :func:`install` did: each path with ``written`` / ``unchanged`` / ``created``, and the live steps left."""

    paths: dict[str, str] = field(default_factory=dict)
    next_steps: tuple[str, ...] = ()


def _door(config: OpsConfig, *verb: str) -> str:
    return shlex.join([config.python, '-m', 'dev_lab.ops', '--config', str(config.path), *verb])


def _service(
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


def _promote(config: OpsConfig) -> dict[str, str]:
    role = config.promote
    if role is None:
        return {}
    body = ['Type=oneshot', f'User={role.user}', f'Environment=HOME={config.home}',
            f'ExecStart={_door(config, "promote")}', f'MemoryMax={role.memory_max}']  # fmt: skip
    service = _service(config, role, 'Fast-forward each trunk when integrate promote admits it (dev_lab.ops)', body,
                       network=True)  # fmt: skip
    timer = (
        '[Unit]\nDescription=Nightly trunk promotion (dev_lab.ops)\n'
        f'[Timer]\nOnCalendar={role.schedule}\nPersistent=true\n[Install]\nWantedBy=timers.target\n'
    )
    return {
        f'etc/systemd/system/{_UNIT}-promote.service': service,
        f'etc/systemd/system/{_UNIT}-promote.timer': timer,
    }


def _breakglass(config: OpsConfig) -> dict[str, str]:
    role = config.breakglass
    if role is None:
        return {}
    keys = f'/etc/dev-lab/ops/{role.account}.keys'
    serve = _door(config, 'breakglass', 'serve')
    sshd = (
        f'Match User {role.account}\n    AuthorizedKeysFile {keys}\n'
        f'    ExposeAuthInfo yes\n    ForceCommand sudo -n {serve}\n'
        '    AllowTcpForwarding no\n    AllowAgentForwarding no\n    X11Forwarding no\n    PermitTTY no\n'
    )
    tick_service = _service(
        config, role, 'Close expired break-glass waves, remind unacknowledged audits (dev_lab.ops)',
        ['Type=oneshot', f'ExecStart={_door(config, "breakglass", "tick")}'], network=False,
    )  # fmt: skip
    tick_timer = (
        '[Unit]\nDescription=Break-glass wave tick (dev_lab.ops)\n'
        f'[Timer]\nOnCalendar={role.tick}\nPersistent=true\n[Install]\nWantedBy=timers.target\n'
    )
    return {
        f'etc/systemd/system/{_UNIT}-breakglass-tick.service': tick_service,
        f'etc/systemd/system/{_UNIT}-breakglass-tick.timer': tick_timer,
        f'etc/ssh/sshd_config.d/60-{_UNIT}-{role.account}.conf': sshd,
        keys.lstrip('/'): ''.join(f'{key}\n' for key in role.keys),
        f'etc/sudoers.d/{_UNIT}-{role.account}': (
            f'Defaults:{role.account} env_keep += "{ENV}"\n{role.account} ALL=(root) NOPASSWD: {serve}\n'
        ),
    }


def _timer(config: OpsConfig, role: Backup | Probe, name: str, what: str, exec_start: str) -> dict[str, str]:
    body = ['Type=oneshot', f'User={role.user}', f'ExecStart={exec_start}', 'Nice=10']
    service = _service(config, role, f'{what} (dev_lab.ops)', body, network=True)
    timer = (
        f'[Unit]\nDescription={what} (dev_lab.ops)\n'
        f'[Timer]\nOnCalendar={role.schedule}\nPersistent=true\n[Install]\nWantedBy=timers.target\n'
    )
    return {f'etc/systemd/system/{_UNIT}-{name}.service': service, f'etc/systemd/system/{_UNIT}-{name}.timer': timer}


def _backup(config: OpsConfig) -> dict[str, str]:
    role = config.backup
    if role is None:
        return {}
    rendered: dict[str, str] = {}
    if role.dumpers:
        export = _door(config, 'backup', 'export')
        keys = f'/etc/dev-lab/ops/{role.account}.keys'
        line = f'restrict,command="sudo -n {export}" '
        rendered |= {
            f'etc/ssh/sshd_config.d/62-{_UNIT}-{role.account}.conf': (
                f'Match User {role.account}\n    AuthorizedKeysFile {keys}\n    ForceCommand sudo -n {export}\n'
                '    AllowTcpForwarding no\n    AllowAgentForwarding no\n    X11Forwarding no\n    PermitTTY no\n'
            ),
            keys.lstrip('/'): ''.join(f'{line}{key}\n' for key in role.keys),
            f'etc/sudoers.d/{_UNIT}-{role.account}': f'{role.account} ALL=(root) NOPASSWD: {export}\n',
        }
    if role.source:
        if not role.schedule:
            msg = '[ops.backup] pulls (source is set) but declares no schedule'
            raise ValueError(msg)
        rendered |= _timer(config, role, 'backup-pull', 'Pull the forge backup', _door(config, 'backup', 'pull'))
    return rendered


def _probe(config: OpsConfig) -> dict[str, str]:
    role = config.probe
    if role is None:
        return {}
    return _timer(config, role, 'probe', 'Probe forge protection and CI runs', _door(config, 'probe'))


def _supervise(config: OpsConfig) -> dict[str, str]:
    role = config.supervise
    if role is None:
        return {}
    serve = shlex.join(
        [config.python, '-m', 'dev_lab.supervise', 'serve', '--project', role.project, '--config', str(config.path)]
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
    service = _service(config, role, 'Host supervisor (dev_lab.supervise)', body, network=True,
                       wanted_by='multi-user.target')  # fmt: skip
    return {f'etc/systemd/system/{_SUPERVISE}.service': service}


def files(config: OpsConfig) -> dict[str, str]:
    """Every file the configuration renders, by path relative to the root."""
    access = access_files(config.access) if config.access is not None else {}
    rendered = {**_promote(config), **_breakglass(config), **_backup(config), **_probe(config)}
    return {**rendered, **access, **_supervise(config)}


def _steps(config: OpsConfig, prepared: list[str]) -> tuple[str, ...]:
    steps = []
    if config.promote is not None:
        steps += [f'id {config.promote.user} || useradd --system --home-dir {config.home} {config.promote.user}',
                  *prepared, 'systemctl daemon-reload', f'systemctl enable --now {_UNIT}-promote.timer']  # fmt: skip
    else:
        steps += prepared
    if (role := config.breakglass) is not None:
        steps += [f'id {role.account} || useradd --create-home --shell /bin/sh {role.account}',
                  f'visudo -cf /etc/sudoers.d/{_UNIT}-{role.account}', 'sshd -t && systemctl reload ssh',
                  'systemctl daemon-reload', f'systemctl enable --now {_UNIT}-breakglass-tick.timer']  # fmt: skip
        if not Path(role.totp).is_file():
            steps.append(_door(config, 'breakglass', 'enrol'))
    if (backup := config.backup) is not None and backup.dumpers:
        steps += [f'id {backup.account} || useradd --create-home --shell /bin/sh {backup.account}',
                  f'visudo -cf /etc/sudoers.d/{_UNIT}-{backup.account}', 'sshd -t && systemctl reload ssh']  # fmt: skip
    if backup is not None and backup.source:
        steps += [f'id {backup.user} || useradd --system {backup.user}', 'systemctl daemon-reload',
                  f'systemctl enable --now {_UNIT}-backup-pull.timer']  # fmt: skip
    if (probe := config.probe) is not None:
        tokens = ' '.join(sorted(probe.tokens.values()))
        steps += [f'id {probe.user} || useradd --system {probe.user}',
                  f'install -d -m 0700 -o {probe.user} {probe.state}',
                  f'chown {probe.user} {tokens} && chmod 600 {tokens}',
                  'systemctl daemon-reload', f'systemctl enable --now {_UNIT}-probe.timer']  # fmt: skip
    if (access := config.access) is not None:
        steps += ['apt-get install -y libpam-oath', f'id {access.account} || useradd --create-home {access.account}',
                  f'put `@include {PAM_INCLUDE}` as the first auth line of /etc/pam.d/sshd',
                  'sshd -t && systemctl reload ssh']  # fmt: skip
        if not Path(access.oath).is_file():
            steps.append(_door(config, 'access', 'enrol'))
    if config.supervise is not None:
        steps += ['systemctl daemon-reload', f'systemctl enable --now {_SUPERVISE}.service']
    return tuple(steps)


def _under(root: Path, path: Path | str) -> Path:
    path = Path(path)
    return root / path.relative_to(path.anchor)


@dataclass(frozen=True)
class Account:
    """A host account as the kernel judges access: its uid and every gid it holds (primary and supplementary)."""

    uid: int
    gids: frozenset[int]


def account_of(user: str) -> Account | None:
    """*user*'s :class:`Account` on this host, ``None`` where it does not exist yet (or the host has no ``pwd``)."""
    if sys.platform == 'win32':  # a Windows render has no accounts to judge
        return None
    try:
        entry = pwd.getpwnam(user)
    except KeyError:
        return None
    supplementary = {group.gr_gid for group in grp.getgrall() if user in group.gr_mem}
    return Account(entry.pw_uid, frozenset({entry.pw_gid, *supplementary}))


def may_enter(mode: int, uid: int, gid: int, account: Account | None) -> bool:
    """Whether *account* may enter a directory of *mode* owned ``uid:gid``: ONE class decides, as the kernel does.

    Root enters anything; the owner is judged by the owner bits alone, a member of the group by the group bits, anyone
    else by the other bits. An account not made yet (``None``) holds no ownership or membership: the other bits.
    """
    if account is None:
        return bool(mode & stat.S_IXOTH)
    if account.uid == 0:
        return True
    if account.uid == uid:
        return bool(mode & stat.S_IXUSR)
    if gid in account.gids:
        return bool(mode & stat.S_IXGRP)
    return bool(mode & stat.S_IXOTH)


def _may_enter(path: Path, user: str) -> bool:
    found = path.stat()
    return may_enter(found.st_mode, found.st_uid, found.st_gid, account_of(user))


def _own(chown: Chown | None, path: Path, user: str | None, group: str | None) -> bool:
    """Apply the ownership when it can be applied here; ``False`` leaves it to a next step."""
    if chown is None or not path.exists():
        return False
    try:
        chown(path, user, group)
    except LookupError:
        return False
    return True


def _prepare(config: OpsConfig, root: Path, chown: Chown | None) -> tuple[dict[str, str], list[str]]:
    """Create the clone home (only if absent), hand the promote user it and the credential, make the env file root's."""
    done: dict[str, str] = {}
    steps: list[str] = []
    if (role := config.promote) is not None:
        home = _under(root, config.home)
        if home.is_dir():  # an existing directory is the host's; install never re-owns or widens it
            done[home.relative_to(root).as_posix()] = 'unchanged'
        else:
            done[home.relative_to(root).as_posix()] = 'created'
            home.mkdir(parents=True)
            home.chmod(0o750)
            if not _own(chown, home, role.user, role.user):
                steps.append(f'chown {role.user}:{role.user} {config.home.as_posix()}')
        credential = _under(root, role.credentials)
        if credential.is_file():
            credential.chmod(0o600)
        if not _own(chown, credential, role.user, None):
            steps.append(f'chown {role.user} {role.credentials} && chmod 600 {role.credentials}')
        parent = credential.parent
        if parent.is_dir() and not _may_enter(parent, role.user):
            where = Path(role.credentials).parent.as_posix()
            steps.append(f'{role.user} cannot enter {where}: move the credential to a directory it may enter')
    if config.environment_file:
        declared = _under(root, config.environment_file)
        if declared.is_file():
            declared.chmod(0o600)
        if not _own(chown, declared, 'root', 'root'):
            steps.append(f'chown root:root {config.environment_file} && chmod 600 {config.environment_file}')
    return done, steps


def install(config: OpsConfig, root: Path, *, chown: Chown | None = None) -> Rendered:
    """Write :func:`files` under *root*, each only when its content differs; sudoers and keys at mode 0440/0644.

    Then prepare the promote home, its credential and the environment file (see the module docstring): *chown* is
    applied where given, and what it could not apply is a next step.
    """
    done, prepared = _prepare(config, root, chown)
    for relative, content in files(config).items():
        target = root / relative
        if target.is_file() and target.read_text(encoding='utf-8') == content:
            done[relative] = 'unchanged'
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding='utf-8', newline='\n')
        target.chmod(0o440 if 'sudoers.d' in relative else 0o644)
        done[relative] = 'written'
    return Rendered(done, _steps(config, prepared))
