"""A machine the config source does not declare yet renders ONE safe default; the doors it may not use say how to enrol.

The family file declares the default ONCE, as ``[dev.default]`` (user ruling 2026-11-16, issue 638): no forge
write account (``forges = {}``), no HPC roles (``hpc = []``), no vendor seats, hooks warn-only (``hooks =
"warn"``). ``devhost render`` reads it for a host with no ``hosts/<name>.toml`` and stamps the machine file's
``[devhost] unmanaged = "<name>"``; every door refusing a write or HPC action there names :func:`enrolment`.

``[dev] bridge.hpc`` (user ruling 2026-11-16: on EVERY development machine, so the family declares it) renders as
the machine file's ``[bridge.hpc]``: the HPC usage read door the session bridge runs for the agents dashboard
(``command``, an argv) and its cadence (``cadence_hours``). The command's interpreter is a MACHINE fact (#782): the
local-only ``[tools] python``, a stable install outside every worktree, set with ``devhost local set tools.python
<path>``; render copies it and never the caller's own interpreter, so two renders from different envs agree.
"""

from __future__ import annotations

import tomllib
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Final

from dev_lab.dev.venvpath import running_interpreter

__all__ = [
    'DEFAULT_TABLE', 'HPC_READ_DOOR', 'TOOLS_TABLE', 'UNMANAGED', 'bridge_tables', 'enrolment', 'family_dev',
    'host_declaration', 'refusal', 'unmanaged',
]  # fmt: skip

#: The family ``[dev]`` sub-table that IS the default profile.
DEFAULT_TABLE: Final = 'default'
#: The ``[devhost]`` key stamping a render of the default: the hostname it was rendered for.
UNMANAGED: Final = 'unmanaged'
#: The HPC usage read door's module arguments (``dev_lab.dev.hpcusage``), run by the session bridge's collector.
HPC_READ_DOOR: Final = ('-m', 'dev_lab.dev.hpcusage', 'report', '--json')
#: The local-only machine table naming this machine's stable tool interpreter (``python``).
TOOLS_TABLE: Final = 'tools'


def _read(path: Path) -> dict[str, Any]:
    return tomllib.loads(path.read_text(encoding='utf-8'))


def family_dev(family: Mapping[str, Any]) -> dict[str, Any]:
    """The family ``[dev]`` every machine shares: the default profile aside."""
    return {k: v for k, v in family.get('dev', {}).items() if k != DEFAULT_TABLE}


def host_declaration(clone: Path, host: str) -> tuple[dict[str, Any], bool]:
    """*host*'s parsed host file, else the default profile as one (``True``: unmanaged).

    Raises:
        LookupError: neither the host file nor the family's ``[dev.default]`` exists.
        TypeError: the family's ``default`` is not a table.

    """
    path = clone / 'hosts' / f'{host}.toml'
    if path.is_file():
        return _read(path), False
    family = _read(clone / 'family.toml') if (clone / 'family.toml').is_file() else {}
    default = family.get('dev', {}).get(DEFAULT_TABLE)
    if default is None:
        msg = f'{host!r} has no hosts/{host}.toml and {clone / "family.toml"} declares no [dev.{DEFAULT_TABLE}]'
        raise LookupError(msg)
    if not isinstance(default, Mapping):
        msg = f'{clone / "family.toml"} [dev] {DEFAULT_TABLE} must be a table'
        raise TypeError(msg)
    return {'dev': dict(default)}, True


#: How a change to the config source is proposed: IN ITS OWN CHECKOUT (a family repo), never from this repo -- a
#: worktree there pushes under the config source's own hooks and opens its PR on its own forge (#745).
PROPOSE: Final = (
    "propose it in the config source's own checkout (its [repos] path in the machine file): "
    'git -C <that path> worktree add .claude/worktrees/<feature> -b pr/<task>/<feature> origin/<its branch>, '
    'edit there, then push and `python -m dev_lab.dev.forge pr create` FROM that worktree, '
    'so its own hooks judge the push and its own forge takes the PR'
)


def enrolment(host: str) -> str:
    """The one enrolment door for unmanaged *host*."""
    return (
        f'this machine is UNMANAGED ({host!r} renders the family default): enrol it -- declare hosts/{host}.toml in '
        f'the config source from family.toml [dev.{DEFAULT_TABLE}] through a pull request ({PROPOSE}), then '
        f'{running_interpreter()} -m dev_lab.dev.devhost render --host {host} --write'
    )


def unmanaged(live: Mapping[str, Any]) -> str | None:
    """The hostname a *live* machine file was rendered for from the default, else ``None``."""
    return live.get('devhost', {}).get(UNMANAGED) or None


def refusal(live: Mapping[str, Any], action: str) -> str | None:
    """Why *action* (a write or HPC door) is refused on this machine, naming the enrolment door; ``None`` if managed."""
    host = unmanaged(live)
    return f'{action} refused: {enrolment(host)}' if host else None


def bridge_tables(dev: Mapping[str, Any], live: Mapping[str, Any]) -> dict[str, Any]:
    """The machine file's ``[bridge]`` rendered from an effective ``[dev] bridge``; ``{}`` when undeclared.

    Raises:
        ValueError: a bridge is declared but the *live* machine file names no ``[tools] python`` -- never the
            caller's interpreter, which is one worktree's env and differs per render (#782).

    """
    hpc = dev.get('bridge', {}).get('hpc')
    if not isinstance(hpc, Mapping):
        return {}
    python = live.get(TOOLS_TABLE, {}).get('python') if isinstance(live.get(TOOLS_TABLE), Mapping) else None
    if not python:
        msg = (f'[dev] bridge.hpc is declared but this machine names no [{TOOLS_TABLE}] python, the stable interpreter '
               f'its command runs (never a worktree env): {running_interpreter()} -m dev_lab.dev.devhost local set '
               f'{TOOLS_TABLE}.python <absolute path to a python outside every worktree>')  # fmt: skip
        raise ValueError(msg)
    command = [python, *HPC_READ_DOOR]
    return {'bridge': {'hpc': {'command': command, 'cadence_hours': hpc.get('cadence_hours', 6)}}}
