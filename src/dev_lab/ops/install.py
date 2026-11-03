"""THE ONE INSTALL DOOR of the host roles: render every file the configuration asks for, under a root.

Idempotent: a file whose content is already what the config renders is not rewritten, and the result names
each path ``written`` or ``unchanged``. Rendering never runs a host command; the commands that make a change live
-- create the accounts, reload systemd, test and reload sshd -- are returned as :data:`Rendered.next_steps` for the
operator, because they need root on the live host and a test root has none.
"""

from __future__ import annotations

import shlex
from dataclasses import dataclass, field
from pathlib import Path

from dev_lab.ops.config import OpsConfig
from dev_lab.ops.sshkey import ENV

__all__ = ['Rendered', 'files', 'install']

_UNIT = 'dev-lab-ops'


@dataclass(frozen=True)
class Rendered:
    """What :func:`install` did: each path with ``written`` / ``unchanged``, and the live steps left to run."""

    paths: dict[str, str] = field(default_factory=dict)
    next_steps: tuple[str, ...] = ()


def _door(config: OpsConfig, *verb: str) -> str:
    return shlex.join([config.python, '-m', 'dev_lab.ops', '--config', str(config.path), *verb])


def _promote(config: OpsConfig) -> dict[str, str]:
    role = config.promote
    if role is None:
        return {}
    service = (
        '[Unit]\nDescription=Fast-forward each trunk when integrate promote admits it (dev_lab.ops)\n'
        'Wants=network-online.target\nAfter=network-online.target\n'
        f'[Service]\nType=oneshot\nUser={role.user}\nEnvironment=HOME={config.home}\n'
        f'ExecStart={_door(config, "promote")}\nMemoryMax={role.memory_max}\n'
    )
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
    tick_service = (
        '[Unit]\nDescription=Close expired break-glass waves, remind unacknowledged audits (dev_lab.ops)\n'
        f'[Service]\nType=oneshot\nExecStart={_door(config, "breakglass", "tick")}\n'
    )
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


def files(config: OpsConfig) -> dict[str, str]:
    """Every file the configuration renders, by path relative to the root."""
    return {**_promote(config), **_breakglass(config)}


def _steps(config: OpsConfig) -> tuple[str, ...]:
    steps = []
    if config.promote is not None:
        steps += [f'id {config.promote.user} || useradd --system --home-dir {config.home} {config.promote.user}',
                  'systemctl daemon-reload', f'systemctl enable --now {_UNIT}-promote.timer']  # fmt: skip
    if config.breakglass is not None and config.promote is not None:
        # the root-run break-glass reads the declaration from the clones the promote user owns
        steps.append(f'git config --system --add safe.directory "{config.home}/*"')
    if (role := config.breakglass) is not None:
        steps += [f'id {role.account} || useradd --create-home --shell /bin/sh {role.account}',
                  f'visudo -cf /etc/sudoers.d/{_UNIT}-{role.account}', 'sshd -t && systemctl reload ssh',
                  'systemctl daemon-reload', f'systemctl enable --now {_UNIT}-breakglass-tick.timer']  # fmt: skip
        if not Path(role.totp).is_file():
            steps.append(_door(config, 'breakglass', 'enrol'))
    return tuple(steps)


def install(config: OpsConfig, root: Path) -> Rendered:
    """Write :func:`files` under *root*, each only when its content differs; sudoers and keys at mode 0440/0644."""
    done: dict[str, str] = {}
    for relative, content in files(config).items():
        target = root / relative
        if target.is_file() and target.read_text(encoding='utf-8') == content:
            done[relative] = 'unchanged'
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding='utf-8', newline='\n')
        target.chmod(0o440 if 'sudoers.d' in relative else 0o644)
        done[relative] = 'written'
    return Rendered(done, _steps(config))
