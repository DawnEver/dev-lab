"""THE HARNESS CONTEXT: dev-lab's one ENV-IS-READ-ONCE entry, where the process environment is read.

Family policy 2026-11-25 (v1-migration D67/D68): a fact an external system offers only as an environment variable
(class B) is read at ONE entry and turned into a typed record at once; host and scheduler facts are lab-commons',
the agent harness's context is dev-lab's, and it is this module (``[tool.dev_lab.env] entry``). Nothing read here
may change a numeric result. Two doors, and no third:

* :func:`context` -- the typed :class:`Harness` record of the facts dev-lab reads by NAME: which agent project
  directory a hook runs for, which machine a forge claim names, who ran a door;
* :func:`child_env` -- the environment a child process inherits, with overlays applied and keys dropped: passing
  the environment through is not reading a value from it.

A value that changes a result or a behavior (class A) is configuration, and a test switch (class C) a pytest
option; neither is added here, because this module would then be the laundering door the rule exists to close.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

__all__ = [
    'CLAUDE_CONFIG_ENV',
    'CODEX_HOME_ENV',
    'MACHINE_ENV',
    'PROJECT_DIR_ENV',
    'SUDO_USER_ENV',
    'USER_ENVS',
    'Harness',
    'child_env',
    'context',
]

#: The agent harness's project directory (Claude Code sets it for every hook).
PROJECT_DIR_ENV: Final = 'CLAUDE_PROJECT_DIR'
#: The agent harness's own configuration and the Codex home.
CLAUDE_CONFIG_ENV: Final = 'CLAUDE_CONFIG_DIR'
CODEX_HOME_ENV: Final = 'CODEX_HOME'
#: The machine name a harness declares for its forge claims, over the host name.
MACHINE_ENV: Final = 'HARNESS_MACHINE'
#: The account that ran a door under ``sudo``.
SUDO_USER_ENV: Final = 'SUDO_USER'
#: The login name, as POSIX then Windows spell it.
USER_ENVS: Final = ('USER', 'USERNAME')


@dataclass(frozen=True, slots=True)
class Harness:
    """The harness facts dev-lab reads by name; ``''`` where the environment does not say."""

    project_dir: str = ''
    claude_config_dir: str = ''
    codex_home: str = ''
    machine: str = ''
    user: str = ''
    sudo_user: str = ''


def context(env: Mapping[str, str] | None = None) -> Harness:
    """The :class:`Harness` record of *env* (default: this process's environment, read now)."""
    env = os.environ if env is None else env
    return Harness(
        project_dir=env.get(PROJECT_DIR_ENV, ''),
        claude_config_dir=env.get(CLAUDE_CONFIG_ENV, ''),
        codex_home=env.get(CODEX_HOME_ENV, ''),
        machine=env.get(MACHINE_ENV, '').strip(),
        user=next((value for name in USER_ENVS if (value := env.get(name, ''))), ''),
        sudo_user=env.get(SUDO_USER_ENV, ''),
    )


def child_env(*overlays: Mapping[str, str], drop: Iterable[str] = ()) -> dict[str, str]:
    """The environment a child inherits from this process: *drop* removed, then each of *overlays* applied in order."""
    dropped = frozenset(drop)
    out = {name: value for name, value in os.environ.items() if name not in dropped}
    for overlay in overlays:
        out.update(overlay)
    return out
