"""A forge's Actions runner on this host: ``[ops.runner.<name>]`` renders its unit, its config and its steps.

One table per runner:

* ``instance`` -- the forge it registers with; ``labels`` -- the job labels it takes (at least one);
* ``capacity`` -- jobs at once (>= 1); ``memory_max`` -- its unit's ``MemoryMax=`` (empty: none);
* ``token_file`` -- the registration token, a root-only secret placed by ``ops secret place``;
* ``binary`` -- the runner executable (``act_runner`` interface: ``register`` and ``daemon --config``);
* ``slice`` / ``after`` / ``wants`` -- where its service sits (:class:`~dev_lab.ops.placement.Placement`).

The runner runs as its own system user ``runner-<name>`` in ``/var/lib/runner-<name>``; its registration (the
``.runner`` file) is written once, by the step install names when that file is absent. The token is read from its
file by the step's shell, so it never sits in the config or a unit; ``act_runner`` takes it as an argument, so it is
briefly visible to root's process list during that one registration.
"""

from __future__ import annotations

import shlex
from dataclasses import dataclass, fields
from typing import TYPE_CHECKING, Any

from dev_lab.ops.placement import Placement

if TYPE_CHECKING:
    from dev_lab.ops.config import OpsConfig

__all__ = ['ForgeRunner', 'files', 'runners', 'steps']

_UNIT = 'dev-lab-runner'


@dataclass(frozen=True)
class ForgeRunner(Placement):
    """One declared runner (see the module docstring)."""

    name: str
    instance: str
    labels: tuple[str, ...]
    token_file: str
    capacity: int = 1
    memory_max: str = ''
    binary: str = '/usr/local/bin/act_runner'

    @property
    def user(self) -> str:
        """The system account it runs as."""
        return f'runner-{self.name}'

    @property
    def home(self) -> str:
        """Its working directory, where its registration lives."""
        return f'/var/lib/{self.user}'

    @property
    def config_file(self) -> str:
        """The runner's own config file, rendered by install."""
        return f'/etc/dev-lab/{self.user}/config.yaml'


def runners(table: object) -> tuple[ForgeRunner, ...]:
    """The runners ``[ops.runner]`` declares, by name; refuse an unknown key, no label, or a capacity below one."""
    if table is None:
        return ()
    if not isinstance(table, dict):
        msg = '[ops.runner] must be a table of runners'
        raise TypeError(msg)
    known = {field.name for field in fields(ForgeRunner)} - {'name'}
    found = []
    for name, row in sorted(table.items()):
        where = f'[ops.runner.{name}]'
        if not isinstance(row, dict):
            msg = f'{where} must be a table'
            raise TypeError(msg)
        if unknown := sorted(set(row) - known):
            msg = f'{where} has unknown keys {unknown}; known: {sorted(known)}'
            raise ValueError(msg)
        values: dict[str, Any] = {key: tuple(value) if isinstance(value, list) else value for key, value in row.items()}
        try:
            runner = ForgeRunner(name=name, **values)
        except TypeError as missing:
            msg = f'{where}: {missing}'
            raise ValueError(msg) from missing
        if not runner.labels:
            msg = f'{where} declares no labels: a runner that takes no job label runs nothing'
            raise ValueError(msg)
        if int(runner.capacity) < 1:
            msg = f'{where} capacity {runner.capacity} is below one'
            raise ValueError(msg)
        found.append(runner)
    return tuple(found)


def _unit(runner: ForgeRunner) -> str:
    unit = [f'Description=Forge Actions runner {runner.name} ({runner.instance})', 'Wants=network-online.target',
            'After=network-online.target', *(f'Wants={n}' for n in runner.wants),
            *(f'After={n}' for n in runner.after)]  # fmt: skip
    service = [*([f'Slice={runner.slice}'] if runner.slice else []), f'User={runner.user}',
               f'WorkingDirectory={runner.home}', f'ExecStart={runner.binary} daemon --config {runner.config_file}',
               'Restart=always', 'RestartSec=10',
               *([f'MemoryMax={runner.memory_max}'] if runner.memory_max else [])]  # fmt: skip
    head = '[Unit]\n' + ''.join(f'{line}\n' for line in unit)
    return head + '[Service]\n' + ''.join(f'{line}\n' for line in service) + '[Install]\nWantedBy=multi-user.target\n'


def _yaml(runner: ForgeRunner) -> str:
    labels = ''.join(f'    - {label}\n' for label in runner.labels)
    return (f'log:\n  level: info\nrunner:\n  file: {runner.home}/.runner\n  capacity: {int(runner.capacity)}\n'
            f'  labels:\n{labels}')  # fmt: skip


def files(config: OpsConfig) -> dict[str, str]:
    """Every file the declared runners render, by path relative to the root."""
    rendered: dict[str, str] = {}
    for runner in config.runners:
        rendered[f'etc/systemd/system/{_UNIT}-{runner.name}.service'] = _unit(runner)
        rendered[runner.config_file.lstrip('/')] = _yaml(runner)
    return rendered


def steps(config: OpsConfig) -> list[str]:
    """The live steps install leaves: the account, a registration where none exists yet, then the unit."""
    found: list[str] = []
    for runner in config.runners:
        register = shlex.join([runner.binary, 'register', '--no-interactive', '--instance', runner.instance,
                               '--name', runner.name, '--labels', ','.join(runner.labels),
                               '--config', runner.config_file])  # fmt: skip
        token, with_token = shlex.quote(runner.token_file), shlex.quote(register + ' --token "$1"')
        found += [
            f'id {runner.user} || useradd --system --home-dir {runner.home} --create-home {runner.user}',
            (
                f'test -f {runner.home}/.runner || (cd {runner.home} && sudo -u {runner.user} sh -c '
                f'{with_token} _ "$(cat {token})")'
            ),
            'systemctl daemon-reload',
            f'systemctl enable --now {_UNIT}-{runner.name}.service',
        ]
    return found
