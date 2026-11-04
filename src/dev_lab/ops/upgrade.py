"""``upgrade``: install dev-lab into ``[ops] python``'s environment at the tip of the CONFIGURED ref and source.

It takes no argument, so an operator allowed exactly this command (sudo) installs only reviewed, promoted code --
never a sha or URL of their choosing. Every input is ``[ops.upgrade]`` (:class:`dev_lab.ops.config.Upgrade`).
"""

from __future__ import annotations

import shutil
from collections.abc import Callable, Sequence

import lab_commons.launch as _door

from dev_lab.dev.netverb import run_network_verb
from dev_lab.ops.config import OpsConfig

__all__ = ['command', 'run', 'version']

#: Runs a command line; its exit code and stdout.
type Runner = Callable[[Sequence[str]], tuple[int, str]]

_VERSION = (
    "import importlib.metadata as m\ntry: print(m.version('dev-lab'))\nexcept m.PackageNotFoundError: print('none')"
)


def command(config: OpsConfig) -> list[str]:
    """The exact ``uv pip install`` line ``[ops.upgrade]`` declares; refuses a config with no such table."""
    role = config.upgrade
    if role is None:
        msg = f'{config.path} enables no [ops.upgrade]'
        raise ValueError(msg)
    uv = role.uv or shutil.which('uv') or 'uv'
    extras = f'[{",".join(role.extras)}]' if role.extras else ''
    line = [uv, 'pip', 'install', '--python', config.python, '--reinstall-package', 'dev-lab']
    line += ['--override', role.overrides] if role.overrides else []
    return [*line, f'dev-lab{extras} @ git+{role.source}@{role.ref}', *role.packages]


def _probe(argv: Sequence[str]) -> tuple[int, str]:
    done = _door.run(list(argv), check=False, capture_output=True, text=True, encoding='utf-8')
    return done.returncode, done.stdout


def _install(argv: Sequence[str]) -> tuple[int, str]:
    report = run_network_verb(argv)
    return report.returncode, report.attempts[-1].output if report.attempts else ''


def version(config: OpsConfig, probe: Runner = _probe) -> str:
    """dev-lab's installed version in ``[ops] python``'s environment (``none`` when absent)."""
    code, out = probe([config.python, '-c', _VERSION])
    return out.strip() if code == 0 else 'unknown'


def run(config: OpsConfig, *, install: Runner = _install, probe: Runner = _probe) -> tuple[int, str]:
    """Install per :func:`command` (retried as a network verb); the exit code and ``old -> new`` (else its output)."""
    line = command(config)
    old = version(config, probe)
    code, out = install(line)
    if code != 0:
        return code, out.strip()
    return 0, f'dev-lab {old} -> {version(config, probe)}'
