"""THE ONE INSTALL DOOR of the host roles: render every file the configuration asks for, under a root.

Idempotent: a file whose content is already what the config renders is not rewritten, and the result names
each path ``written`` or ``unchanged``. Rendering never runs a host command; the commands that make a change live
-- create the accounts, reload systemd, test and reload sshd -- are returned as :data:`Rendered.next_steps` for the
operator, because they need root on the live host and a test root has none.

Every service it renders -- the roles' and the supervisor's own (``[ops.supervise]``) -- loads the declared
``[ops] environment_file`` (:mod:`dev_lab.ops.config`) and sits where its role's ``slice`` / ``after`` / ``wants``
place it. The sudo-reached verbs get no sudoers ``env_keep`` for that file: they read it themselves as root, so the
secrets never pass through the invoking account and that account cannot override them.

It also PREPARES what the roles need: it creates the keys directory (root's, 0755) when a role renders keys, puts
the ``[ops.access]`` PAM include into the sshd stack (:func:`dev_lab.ops.access.ensure_include`, refusing a stack of
another shape before writing anything), and for the promote run it creates an absent clone ``home`` (0750) and,
given a ``chown`` (the door passes one when it runs as root), hands the promote user that home and its credential
(0600), and makes the environment file root's, 0600. What it cannot apply -- no root, no account yet, no file
yet -- is a next step. It
NEVER re-owns or widens a directory it did not create: an existing home is left as it is, and a directory holding a
credential or key its user (promote's, the judge's) cannot enter is named in a next step with the ``root:<user> 750``
remedy, never opened.
"""

from __future__ import annotations

import shlex
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from dev_lab.dev.taskkeys import REVIEW_TASK, loader
from dev_lab.ops import forcecommand
from dev_lab.ops.access import KEYS_DIR, Prepared, keys_file, prepare, secret_file
from dev_lab.ops.access import files as access_files
from dev_lab.ops.accounts import account_of, may_enter
from dev_lab.ops.backuprole import Backup
from dev_lab.ops.config import OpsConfig, Probe
from dev_lab.ops.placement import Placement
from dev_lab.ops.totp import write_private
from dev_lab.supervise.daemon import watchdog_seconds

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


def _judge(config: OpsConfig) -> dict[str, str]:
    role = config.judge
    if role is None:
        return {}
    extra = [f'EnvironmentFile={role.environment_file}'] if role.environment_file else []
    home = f'Environment=HOME={role.home_dir}'  # ai-lab reads its model keys from this HOME's credential store
    body = ['Type=oneshot', f'User={role.user}', home, *extra, f'ExecStart={_door(config, "judge")}',
            f'MemoryMax={role.memory_max}']  # fmt: skip
    service = _service(config, role, 'Judge every prepared review bundle (dev_lab.ops)', body, network=True)
    timer = (
        '[Unit]\nDescription=Bundle-review judge pass (dev_lab.ops)\n'
        f'[Timer]\nOnCalendar={role.schedule}\nPersistent=true\n[Install]\nWantedBy=timers.target\n'
    )
    return {f'etc/systemd/system/{_UNIT}-judge.service': service, f'etc/systemd/system/{_UNIT}-judge.timer': timer}


def _consent(config: OpsConfig) -> dict[str, str]:
    role = config.consent
    return {} if role is None else forcecommand.files(_UNIT, role.account, role.keys, _door(config, 'consent', 'serve'))


def _breakglass(config: OpsConfig) -> dict[str, str]:
    role = config.breakglass
    if role is None:
        return {}
    tick_service = _service(
        config, role, 'End expired break-glass waves, resend undelivered wave summaries (dev_lab.ops)',
        ['Type=oneshot', f'ExecStart={_door(config, "breakglass", "tick")}'], network=False,
    )  # fmt: skip
    tick_timer = (
        '[Unit]\nDescription=Break-glass wave tick (dev_lab.ops)\n'
        f'[Timer]\nOnCalendar={role.tick}\nPersistent=true\n[Install]\nWantedBy=timers.target\n'
    )
    return {
        f'etc/systemd/system/{_UNIT}-breakglass-tick.service': tick_service,
        f'etc/systemd/system/{_UNIT}-breakglass-tick.timer': tick_timer,
        **forcecommand.files(_UNIT, role.account, role.keys, _door(config, 'breakglass', 'serve')),
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
        keys = keys_file(role.account)
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
    if config.access is not None:
        secret_file(config)  # refuse two TOTP secrets on one host before anything renders
    access = access_files(config.access) if config.access is not None else {}
    return {
        **_promote(config),
        **_judge(config),
        **_breakglass(config),
        **_consent(config),
        **_backup(config),
        **_probe(config),
        **access,
        **_supervise(config),
    }


def _consent_steps(config: OpsConfig, root: Path) -> list[str]:
    """The issuer's account, then its signing key and TOTP secret where the host holds none yet."""
    if (issuer := config.consent) is None:
        return []
    steps = forcecommand.steps(_UNIT, issuer.account)
    if not _under(root, issuer.key).is_file():
        steps.append(_door(config, 'consent', 'keygen'))
    if not _under(root, issuer.totp).is_file():
        steps.append(_door(config, 'consent', 'enrol'))
    return steps


def _steps(config: OpsConfig, root: Path, prepared: list[str], access: Prepared | None) -> tuple[str, ...]:
    steps = []
    if config.promote is not None:
        steps += [f'id {config.promote.user} || useradd --system --home-dir {config.home} {config.promote.user}',
                  *prepared, 'systemctl daemon-reload', f'systemctl enable --now {_UNIT}-promote.timer']  # fmt: skip
    else:
        steps += prepared
    steps += _judge_steps(config)
    if (role := config.breakglass) is not None:
        steps += [*forcecommand.steps(_UNIT, role.account), 'systemctl daemon-reload',
                  f'systemctl enable --now {_UNIT}-breakglass-tick.timer']  # fmt: skip
    steps += _consent_steps(config, root)
    if (backup := config.backup) is not None and backup.dumpers:
        steps += [f'id {backup.account} || useradd --create-home --shell /bin/sh {backup.account}',
                  f'visudo -cf /etc/sudoers.d/{_UNIT}-{backup.account}', 'sshd -t && systemctl reload ssh']  # fmt: skip
    if backup is not None and backup.source:
        steps += [f'id {backup.user} || useradd --system {backup.user}', 'systemctl daemon-reload',
                  f'systemctl enable --now {_UNIT}-backup-pull.timer']  # fmt: skip
    steps += _probe_steps(config)
    if (role := config.access) is not None:
        steps += ['apt-get install -y libpam-oath', f'id {role.account} || useradd --create-home {role.account}',
                  'sshd -t && systemctl reload ssh']  # fmt: skip
        if access is not None and access.needs_secret:
            steps.append(
                f'{_door(config, "access", "enrol")}  (first-ever; a phone already holding the host '
                f'secret: {_door(config, "access", "adopt", "--secret-file", "-")})'
            )
    if config.supervise is not None:
        steps += ['systemctl daemon-reload', f'systemctl enable --now {_SUPERVISE}.service']
    return tuple(steps)


def _judge_steps(config: OpsConfig) -> list[str]:
    if (judged := config.judge) is None:
        return []
    as_judge = f'sudo -u {judged.user}'  # ai-lab reads the model keys from this HOME's git credential store
    # the task's bundle on stdin: root reads the host's root-only file, else the operator pipes it
    bundle = f' < {shlex.quote(judged.keys_file)}' if judged.keys_file else f'  (the {REVIEW_TASK} key bundle on stdin)'
    return [f'id {judged.user} || useradd --system --create-home --home-dir {judged.home_dir} {judged.user}',
            f'chmod 700 {judged.home_dir}', f'{as_judge} git config --global credential.helper store',
            f'{as_judge} {shlex.join(loader(config.python, REVIEW_TASK))}{bundle}',
            'systemctl daemon-reload', f'systemctl enable --now {_UNIT}-judge.timer']  # fmt: skip


def _probe_steps(config: OpsConfig) -> list[str]:
    if (probe := config.probe) is None:
        return []
    tokens = ' '.join(sorted(probe.tokens.values()))
    return [f'id {probe.user} || useradd --system {probe.user}',
            f'install -d -m 0700 -o {probe.user} {probe.state}',
            f'chown {probe.user} {tokens} && chmod 600 {tokens}',
            'systemctl daemon-reload', f'systemctl enable --now {_UNIT}-probe.timer']  # fmt: skip


def _under(root: Path, path: Path | str) -> Path:
    path = Path(path)
    return root / path.relative_to(path.anchor)


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


def _keys_dir(root: Path, chown: Chown | None, done: dict[str, str]) -> list[str]:
    """Create :data:`KEYS_DIR` (root's, 0755) when absent; an existing one is the host's, never re-owned."""
    keys = _under(root, KEYS_DIR)
    if keys.is_dir():
        done[keys.relative_to(root).as_posix()] = 'unchanged'
        return []
    done[keys.relative_to(root).as_posix()] = 'created'
    keys.mkdir(parents=True)
    keys.chmod(0o755)
    return [] if _own(chown, keys, 'root', 'root') else [f'chown root:root {KEYS_DIR}']


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
        steps += _entered(root, role.credentials, role.user)
    if (judge := config.judge) is not None:
        for secret in judge.secrets:
            steps += _private(root, chown, secret, judge.user) + _entered(root, secret, judge.user)
    # every root-only host secret takes the one narrowing: the environment files and the judge's key bundle
    root_only = [config.environment_file, *((judge.environment_file, judge.keys_file) if judge is not None else ())]
    for environment in filter(None, root_only):
        steps += _private(root, chown, environment, 'root', 'root')
    return done, steps


def _entered(root: Path, declared: str, user: str) -> list[str]:
    """The remedy when *user* cannot enter the directory holding *declared*: install never opens one it did not make."""
    parent = _under(root, declared).parent
    if not parent.is_dir() or _may_enter(parent, user):
        return []
    where = Path(declared).parent.as_posix()
    return [f'{user} cannot enter {where}: chown root:{user} {where} && chmod 750 {where}, or move the file out of it']


def _private(root: Path, chown: Chown | None, declared: str, user: str, group: str | None = None) -> list[str]:
    """Narrow *declared* to 0600 and hand it to *user*; what could not be applied is a next step."""
    found = _under(root, declared)
    if found.is_file():
        found.chmod(0o600)
    if _own(chown, found, user, group):
        return []
    return [f'chown {user}{f":{group}" if group else ""} {declared} && chmod 600 {declared}']


def install(config: OpsConfig, root: Path, *, chown: Chown | None = None) -> Rendered:
    """Write :func:`files` under *root*, each only when its content differs; sudoers and keys at mode 0440/0644.

    The ``[ops.access]`` pam_oath users file is derived here (mode 600) from the host's one TOTP secret, once it exists.

    Raises:
        ValueError: ``[ops.access]`` is declared and the sshd PAM stack is absent or of an unexpected shape, or the
            host declares two TOTP secrets.

    Then prepare the promote home, its credential and the environment file (see the module docstring): *chown* is
    applied where given, and what it could not apply is a next step.

    """
    rendered = files(config)
    # refuses an unexpected PAM stack (or two secrets) before anything is written
    access = prepare(config, root) if config.access is not None else None
    private = access.private if access is not None else {}
    rendered |= (access.public if access is not None else {}) | private
    done, prepared = _prepare(config, root, chown)
    accounts = (config.breakglass, config.consent, config.access)
    if any(role is not None for role in accounts) or (config.backup and config.backup.dumpers):
        prepared += _keys_dir(root, chown, done)
    for relative, content in rendered.items():
        target = root / relative
        if target.is_file() and target.read_text(encoding='utf-8') == content:
            if relative in private:  # a secret is narrowed even when its content already matches
                target.chmod(0o600)
            done[relative] = 'unchanged'
            continue
        if relative in private:  # 600 before a byte is written: never a readable window
            write_private(target, content)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding='utf-8', newline='\n')
            target.chmod(0o440 if 'sudoers.d' in relative else 0o644)
        done[relative] = 'written'
    return Rendered(done, _steps(config, root, prepared, access))
