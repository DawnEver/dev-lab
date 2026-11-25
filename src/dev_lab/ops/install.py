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
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

from lab_commons.config import CONFIG_ENV, FAMILY_TABLE

from dev_lab.dev.machinehome import default_layout
from dev_lab.dev.taskkeys import REVIEW_TASK, loader
from dev_lab.ops import forcecommand
from dev_lab.ops.access import Prepared, keys_file, prepare, secret_file
from dev_lab.ops.access import files as access_files
from dev_lab.ops.caddy import Door, install_caddy
from dev_lab.ops.config import Breakglass, OpsConfig
from dev_lab.ops.httpsdoor import PATHS, HttpsDoor
from dev_lab.ops.installpaths import Chown, keys_dir, prepare_paths, under
from dev_lab.ops.installunits import SUPERVISE, UNIT, door, scheduled, service_unit
from dev_lab.ops.judgerole import Judge
from dev_lab.ops.totp import write_private

__all__ = ['BREAKGLASS_MACHINE', 'Rendered', 'family_env', 'files', 'install']

_UNIT = UNIT


@dataclass(frozen=True)
class Rendered:
    """What :func:`install` did: each path with ``written`` / ``unchanged`` / ``created``, and the live steps left."""

    paths: dict[str, str] = field(default_factory=dict)
    next_steps: tuple[str, ...] = ()


def _promote(config: OpsConfig) -> dict[str, str]:
    role = config.promote
    if role is None:
        return {}
    body = ['Type=oneshot', f'User={role.user}', f'Environment=HOME={config.home}',
            f'ExecStart={door(config, "promote")}', f'MemoryMax={role.memory_max}']  # fmt: skip
    service = service_unit(config, role, 'Fast-forward each trunk when integrate promote admits it (dev_lab.ops)', body,
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
    body = ['Type=oneshot', f'User={role.user}', home, *extra, f'ExecStart={door(config, "judge")}',
            f'MemoryMax={role.memory_max}']  # fmt: skip
    service = service_unit(config, role, 'Judge every prepared review bundle (dev_lab.ops)', body, network=True)
    timer = (
        '[Unit]\nDescription=Bundle-review judge pass (dev_lab.ops)\n'
        f'[Timer]\nOnCalendar={role.schedule}\nPersistent=true\n[Install]\nWantedBy=timers.target\n'
    )
    rendered = {f'etc/systemd/system/{_UNIT}-judge.service': service, f'etc/systemd/system/{_UNIT}-judge.timer': timer}
    if role.family:  # the judge's machine file: its family layer, read under the HOME the unit sets
        rendered[_judge_machine_file(role).lstrip('/')] = _family_machine_file(role.family)
    return rendered


def _family_machine_file(family: Mapping[str, Any]) -> str:
    """A lab-commons machine file holding only *family* as its ``[family]`` table -- the one way a role gets one."""
    keys = [key for key in ('source', 'file', 'max_age') if key in family]
    return f'[{FAMILY_TABLE}]\n' + ''.join(f'{key} = {json.dumps(family[key])}\n' for key in keys)


#: The machine file break-glass's serve and tick read (absolute, as every host path here): its ``[family]`` only.
BREAKGLASS_MACHINE: Final = '/etc/dev-lab/ops/breakglass-machine.toml'


def family_env(role: Breakglass | None) -> dict[str, str]:
    """The environment pointing lab-commons at break-glass's rendered machine file; none without a declared family.

    Break-glass runs as root (its forced command sudoes, its tick has no ``User=``), so it cannot rely on a HOME
    layout as the judge does: the verb sets :data:`~lab_commons.config.CONFIG_ENV` itself before it reads a role.
    """
    return {CONFIG_ENV: BREAKGLASS_MACHINE} if role is not None and role.family else {}


def _judge_machine_file(role: Judge) -> str:
    """The judge's machine file, laid out under its HOME as lab-commons lays it out (:mod:`dev_lab.dev.machinehome`)."""
    machine_home, under_home = default_layout()
    return f'{role.home_dir}/{machine_home}/{under_home}'


def _https_unit(name: str) -> str:
    return f'{_UNIT}-{name}-https.service'


def _https_door(config: OpsConfig, name: str, role: HttpsDoor, account: str) -> dict[str, str]:
    """*role*'s HTTPS relay unit (:mod:`dev_lab.ops.httpsdoor`); empty when it declares no ``https_port``.

    The relay runs as the role's restricted *account* on 127.0.0.1 only and sudoes the ForceCommand's OWN serve line
    (the one sudoers line :mod:`.forcecommand` renders), admitting a request only when it is signed by a key of the
    account's authorized-keys file -- the ssh transport's key set. Caddy routes the allowlisted site's path to it
    (:func:`dev_lab.ops.caddy.doors_routed`).
    """
    if not role.https_port:
        return {}
    relay = shlex.join([
        config.python, '-m', 'dev_lab.ops.httpsdoor', '--port', str(role.https_port), '--role', name,
        '--keys', keys_file(account), '--attempts', str(role.https_attempts),
        '--window-minutes', f'{role.https_window / 60:g}', '--lock-minutes', f'{role.https_lock / 60:g}',
        '--', 'sudo', '-n', *shlex.split(door(config, name, 'serve')),
    ])  # fmt: skip
    unit = (
        f'[Unit]\nDescription=HTTPS door of {name}: relays {PATHS[name]} on 127.0.0.1:{role.https_port} '
        '(dev_lab.ops)\nWants=network-online.target\nAfter=network-online.target\n'
        f'[Service]\nUser={account}\nExecStart={relay}\nRestart=always\nRestartSec=5\n'
        '[Install]\nWantedBy=multi-user.target\n'
    )
    return {f'etc/systemd/system/{_https_unit(name)}': unit}


def https_doors(config: OpsConfig) -> list[Door]:
    """The Caddy route of every declared HTTPS door."""
    roles = (('consent', config.consent), ('breakglass', config.breakglass))
    return [Door(role.https_site, PATHS[name], role.https_port) for name, role in roles if role and role.https_port]


def _https_steps(config: OpsConfig) -> list[str]:
    """(Re)start every declared HTTPS door's relay (its Caddy route is in the Caddyfile reload step)."""
    units = [_https_unit(name) for name, role in (('consent', config.consent), ('breakglass', config.breakglass))
             if role is not None and role.https_port]  # fmt: skip
    return (
        ['systemctl daemon-reload', *(f'systemctl enable {unit} && systemctl restart {unit}' for unit in units)]
        if units
        else []
    )


def _consent(config: OpsConfig) -> dict[str, str]:
    role = config.consent
    if role is None:
        return {}
    forced = forcecommand.files(_UNIT, role.account, role.keys, door(config, 'consent', 'serve'))
    return {**forced, **_https_door(config, 'consent', role, role.account)}


def _breakglass(config: OpsConfig) -> dict[str, str]:
    role = config.breakglass
    if role is None:
        return {}
    tick_service = service_unit(
        config, role, 'Land the green PRs of an open wave, end expired waves, resend wave summaries (dev_lab.ops)',
        ['Type=oneshot', f'ExecStart={door(config, "breakglass", "tick")}'], network=True,
    )  # fmt: skip
    tick_timer = (
        '[Unit]\nDescription=Break-glass wave tick (dev_lab.ops)\n'
        f'[Timer]\nOnCalendar={role.tick}\nPersistent=true\n[Install]\nWantedBy=timers.target\n'
    )
    machine = {BREAKGLASS_MACHINE.lstrip('/'): _family_machine_file(role.family)} if role.family else {}
    return {
        f'etc/systemd/system/{_UNIT}-breakglass-tick.service': tick_service,
        f'etc/systemd/system/{_UNIT}-breakglass-tick.timer': tick_timer,
        **forcecommand.files(_UNIT, role.account, role.keys, door(config, 'breakglass', 'serve')),
        **_https_door(config, 'breakglass', role, role.account),
        **machine,
    }


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
        **access,
        **scheduled(config),
    }


def _consent_steps(config: OpsConfig, root: Path) -> list[str]:
    """The issuer's account, then its signing key and TOTP secret where the host holds none yet."""
    if (issuer := config.consent) is None:
        return []
    steps = forcecommand.steps(_UNIT, issuer.account)
    if not under(root, issuer.key).is_file():
        steps.append(door(config, 'consent', 'keygen'))
    if not under(root, issuer.totp).is_file():
        steps.append(door(config, 'consent', 'enroll'))
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
    steps += _https_steps(config)
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
                f'{door(config, "access", "enroll")}  (first-ever; a phone already holding the host '
                f'secret: {door(config, "access", "adopt", "--secret-file", "-")})'
            )
    if (role := config.supervise) is not None:
        steps += [
            *([config.status.directory_step(role.user)] if config.status else []),
            'systemctl daemon-reload',
            f'systemctl enable --now {SUPERVISE}.service',
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
    prepared += install_caddy(config.caddy, root, rendered, config.status, https_doors(config))
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
