"""THE ONE INSTALL DOOR of the host roles: render every file the configuration asks for, under a root.

Idempotent: a file whose content is already what the config renders is not rewritten, and the result names
each path ``written`` or ``unchanged``. Rendering never runs a host command; the commands that make a change live
-- create the accounts, reload systemd, test and reload sshd -- are returned as :data:`Rendered.next_steps` for the
operator, because they need root on the live host and a test root has none.

Every service it renders -- the roles' and the supervisor's own (``[ops.supervise]``) -- loads the declared
``[ops] environment_file`` (:mod:`dev_lab.ops.config`) and sits where its role's ``slice`` / ``after`` / ``wants``
place it. The sudo-reached verbs get no sudoers ``env_keep`` for that file: they read it themselves as root, so the
secrets never pass through the invoking account and that account cannot override them.

It also PREPARES what the promote run needs: it creates the clone ``home`` (0750) and, given a ``chown`` (the door
passes one when it runs as root), hands the promote user its home and its credential (0600; a credential directory
others cannot enter is opened to the promote group, 0750), and makes the environment file root's, 0600. What it
cannot apply -- no root, no account yet, no file yet -- comes back as a next step instead.
"""

from __future__ import annotations

import shlex
import stat
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from dev_lab.ops.access import PAM_INCLUDE
from dev_lab.ops.access import files as access_files
from dev_lab.ops.config import Backup, OpsConfig, Placement
from dev_lab.ops.sshkey import ENV

__all__ = ['Chown', 'Rendered', 'files', 'install']

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


def _timer(config: OpsConfig, role: Backup, name: str, what: str, exec_start: str) -> dict[str, str]:
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


def _supervise(config: OpsConfig) -> dict[str, str]:
    role = config.supervise
    if role is None:
        return {}
    serve = shlex.join(
        [config.python, '-m', 'dev_lab.supervise', 'serve', '--project', role.project, '--config', str(config.path)]
    )
    body = ['Type=simple', *([f'User={role.user}'] if role.user else []), f'ExecStart={serve}', 'Restart=always',
            'RestartSec=10', *([f'MemoryMax={role.memory_max}'] if role.memory_max else [])]  # fmt: skip
    service = _service(config, role, 'Host supervisor (dev_lab.supervise)', body, network=True,
                       wanted_by='multi-user.target')  # fmt: skip
    return {f'etc/systemd/system/{_SUPERVISE}.service': service}


def files(config: OpsConfig) -> dict[str, str]:
    """Every file the configuration renders, by path relative to the root."""
    access = access_files(config.access) if config.access is not None else {}
    return {**_promote(config), **_breakglass(config), **_backup(config), **access, **_supervise(config)}


def _steps(config: OpsConfig, prepared: list[str]) -> tuple[str, ...]:
    steps = []
    if config.promote is not None:
        steps += [f'id {config.promote.user} || useradd --system --home-dir {config.home} {config.promote.user}',
                  *prepared, 'systemctl daemon-reload', f'systemctl enable --now {_UNIT}-promote.timer']  # fmt: skip
    else:
        steps += prepared
    if config.breakglass is not None and config.promote is not None:
        # the root-run break-glass reads the declaration from the clones the promote user owns
        steps.append(f'git config --system --add safe.directory "{config.home}/*"')
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


def _others_may_enter(path: Path) -> bool:
    return bool(path.stat().st_mode & stat.S_IXOTH)


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
    """Create the clone home, hand the promote user its home and credential, make the environment file root's."""
    done: dict[str, str] = {}
    steps: list[str] = []
    if (role := config.promote) is not None:
        home = _under(root, config.home)
        done[home.relative_to(root).as_posix()] = 'unchanged' if home.is_dir() else 'created'
        home.mkdir(parents=True, exist_ok=True)
        home.chmod(0o750)
        if not _own(chown, home, role.user, role.user):
            steps.append(f'chown {role.user}:{role.user} {config.home.as_posix()}')
        credential = _under(root, role.credentials)
        if credential.is_file():
            credential.chmod(0o600)
        if not _own(chown, credential, role.user, None):
            steps.append(f'chown {role.user} {role.credentials} && chmod 600 {role.credentials}')
        parent = credential.parent
        if parent.is_dir() and not _others_may_enter(parent):
            if _own(chown, parent, None, role.user):
                parent.chmod(0o750)
            else:
                where = Path(role.credentials).parent.as_posix()
                steps.append(f'chgrp {role.user} {where} && chmod 750 {where}')
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
