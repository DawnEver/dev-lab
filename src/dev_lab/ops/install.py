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

import json
import shlex
from dataclasses import dataclass, field
from pathlib import Path

from lab_commons.config import FAMILY_TABLE

from dev_lab.dev.machinehome import default_layout
from dev_lab.dev.taskkeys import REVIEW_TASK, loader
from dev_lab.ops import forcecommand
from dev_lab.ops.access import Prepared, keys_file, prepare, secret_file
from dev_lab.ops.access import files as access_files
from dev_lab.ops.backuprole import Backup
from dev_lab.ops.caddy import install_caddy
from dev_lab.ops.config import Judge, OpsConfig, Probe
from dev_lab.ops.installpaths import Chown, keys_dir, prepare_paths, under
from dev_lab.ops.placement import Placement
from dev_lab.ops.totp import write_private
from dev_lab.ops.upgradefollow import AUDIT
from dev_lab.supervise.daemon import watchdog_seconds

__all__ = ['Rendered', 'files', 'install']

_UNIT = 'dev-lab-ops'
#: The supervisor's own service.
_SUPERVISE = 'dev-lab-supervise'


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
    rendered = {f'etc/systemd/system/{_UNIT}-judge.service': service, f'etc/systemd/system/{_UNIT}-judge.timer': timer}
    if role.family:  # the judge's machine file: its family layer, read under the HOME the unit sets
        keys = [key for key in ('source', 'file', 'max_age') if key in role.family]
        table = ''.join(f'{key} = {json.dumps(role.family[key])}\n' for key in keys)
        rendered[_judge_machine_file(role).lstrip('/')] = f'[{FAMILY_TABLE}]\n{table}'
    return rendered


def _judge_machine_file(role: Judge) -> str:
    """The judge's machine file, laid out under its HOME as lab-commons lays it out (:mod:`dev_lab.dev.machinehome`)."""
    machine_home, under_home = default_layout()
    return f'{role.home_dir}/{machine_home}/{under_home}'


def _consent(config: OpsConfig) -> dict[str, str]:
    role = config.consent
    return {} if role is None else forcecommand.files(_UNIT, role.account, role.keys, _door(config, 'consent', 'serve'))


def _breakglass(config: OpsConfig) -> dict[str, str]:
    role = config.breakglass
    if role is None:
        return {}
    tick_service = _service(
        config, role, 'Land the green PRs of an open wave, end expired waves, resend wave summaries (dev_lab.ops)',
        ['Type=oneshot', f'ExecStart={_door(config, "breakglass", "tick")}'], network=True,
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


def _root_timer(config: OpsConfig, name: str, what: str, schedule: str, *verb: str) -> dict[str, str]:
    """A root oneshot service running the door's *verb*, and its ``OnCalendar`` timer."""
    env = [f'EnvironmentFile={config.environment_file}'] if config.environment_file else []
    service = (
        f'[Unit]\nDescription={what}\nWants=network-online.target\nAfter=network-online.target\n[Service]\n'
        + ''.join(f'{line}\n' for line in (*env, 'Type=oneshot', f'ExecStart={_door(config, *verb)}'))
    )
    timer = (
        f'[Unit]\nDescription={what}\n'
        f'[Timer]\nOnCalendar={schedule}\nPersistent=true\n[Install]\nWantedBy=timers.target\n'
    )
    unit = f'etc/systemd/system/{_UNIT}-{name}'
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
        **_config_tick(config),
        **_upgrade_follow(config),
        **access,
        **_supervise(config),
    }


def _consent_steps(config: OpsConfig, root: Path) -> list[str]:
    """The issuer's account, then its signing key and TOTP secret where the host holds none yet."""
    if (issuer := config.consent) is None:
        return []
    steps = forcecommand.steps(_UNIT, issuer.account)
    if not under(root, issuer.key).is_file():
        steps.append(_door(config, 'consent', 'keygen'))
    if not under(root, issuer.totp).is_file():
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
    if config.config_source is not None and config.config_source.schedule:
        steps += ['systemctl daemon-reload', f'systemctl enable --now {_UNIT}-config-tick.timer']
    if config.upgrade is not None and config.upgrade.follow:
        steps += ['systemctl daemon-reload', f'systemctl enable --now {_UNIT}-upgrade-follow.timer']
    if (role := config.access) is not None:
        steps += ['apt-get install -y libpam-oath', f'id {role.account} || useradd --create-home {role.account}',
                  'sshd -t && systemctl reload ssh']  # fmt: skip
        if access is not None and access.needs_secret:
            steps.append(
                f'{_door(config, "access", "enrol")}  (first-ever; a phone already holding the host '
                f'secret: {_door(config, "access", "adopt", "--secret-file", "-")})'
            )
    if (role := config.supervise) is not None:
        steps += [
            *([config.status.directory_step(role.user)] if config.status else []),
            'systemctl daemon-reload',
            f'systemctl enable --now {_SUPERVISE}.service',
        ]
    return tuple(steps)


def _judge_steps(config: OpsConfig) -> list[str]:
    if (judged := config.judge) is None:
        return []
    as_judge = f'sudo -u {judged.user}'  # ai-lab reads the model keys from this HOME's git credential store
    # the task's bundle on stdin: root reads the host's root-only file, else the operator pipes it
    bundle = f' < {shlex.quote(judged.keys_file)}' if judged.keys_file else f'  (the {REVIEW_TASK} key bundle on stdin)'
    # the review runtime builds ai-lab's venv (``python -m venv``): Debian/Ubuntu ship venv apart (2026-11-08, AMD-1)
    return ['apt-get install -y python3-venv',
            f'id {judged.user} || useradd --system --create-home --home-dir {judged.home_dir} {judged.user}',
            f'chmod 700 {judged.home_dir}', f'{as_judge} git config --global credential.helper store',
            f'{as_judge} {shlex.join(loader(config.python, REVIEW_TASK))}{bundle}',
            *([f'chown -R {judged.user}: {judged.home_dir}/{default_layout()[0]}'] if judged.family else []),
            'systemctl daemon-reload', f'systemctl enable --now {_UNIT}-judge.timer']  # fmt: skip


def _probe_steps(config: OpsConfig) -> list[str]:
    if (probe := config.probe) is None:
        return []
    tokens = ' '.join(sorted(probe.tokens.values()))
    return [f'id {probe.user} || useradd --system {probe.user}',
            f'install -d -m 0700 -o {probe.user} {probe.state}',
            f'chown {probe.user} {tokens} && chmod 600 {tokens}',
            'systemctl daemon-reload', f'systemctl enable --now {_UNIT}-probe.timer']  # fmt: skip


def install(config: OpsConfig, root: Path, *, chown: Chown | None = None) -> Rendered:
    """Write :func:`files` under *root*, each only when its content differs; sudoers and keys at mode 0440/0644.

    The ``[ops.access]`` pam_oath users file is derived here (mode 600) from the host's one TOTP secret, once it exists.

    Raises:
        ValueError: ``[ops.access]`` is declared and the sshd PAM stack is absent or of an unexpected shape, the
            host declares two TOTP secrets, or the judge's declared ``keys_file`` is not placed yet.

    Then prepare the promote home, its credential and the environment file (see the module docstring): *chown* is
    applied where given, and what it could not apply is a next step.

    """
    if (judged := config.judge) is not None and judged.keys_file and not under(root, judged.keys_file).is_file():
        msg = (f'keys_file {judged.keys_file} is declared but not placed: place it with '
               f'`secret place --path {judged.keys_file}`')  # fmt: skip
        raise ValueError(msg)
    rendered = files(config)
    # refuses an unexpected PAM stack (or two secrets) before anything is written
    access = prepare(config, root) if config.access is not None else None
    private = access.private if access is not None else {}
    rendered |= (access.public if access is not None else {}) | private
    done, prepared = prepare_paths(config, root, chown)
    prepared += install_caddy(config.caddy, root, rendered, config.status)
    accounts = (config.breakglass, config.consent, config.access)
    if any(role is not None for role in accounts) or (config.backup and config.backup.dumpers):
        prepared += keys_dir(root, chown, done)
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
