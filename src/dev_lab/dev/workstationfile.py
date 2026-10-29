"""WORKSTATION MACHINE FILE: the tables ``workstation deploy`` writes, and the roles that declare them.

A ``--role`` is a declared profile (:data:`ROLES`: its capabilities and ``[serve]`` rule); ``template --role
<role> --repos ...`` prints the tables it writes. The ``light`` role withholds every :data:`HEAVY` tool and refuses
one in ``--capabilities``. The merge (:func:`machine_file`) keeps every other table, key and comment, removes a
RETIRED ``[capabilities.<name>]`` -- carrying its keys into ``[runtimes.<name>]`` when that is its remedy -- and
under ``--dry-run`` prints the diff without writing.
"""

from __future__ import annotations

import argparse
import tomllib
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final

from lab_commons.box.machine import provided
from lab_commons.compute.durable import durable_text
from lab_commons.compute.serves import EVERY, SERVE_TABLE
from lab_commons.compute.toolchecks import CHECKS
from lab_commons.config import config_path
from lab_commons.hpc.retired import RETIRED
from lab_commons.log import emit

from dev_lab.dev._machinefile import diff, merged
from dev_lab.dev.forgereview_runtimes import RUNTIMES_TABLE

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from dev_lab.dev.hpchost.steps import Step

__all__ = [
    'HEAVY',
    'JMAG_SOLVER_IMAGES',
    'ROLES',
    'WORKSTATION',
    'Role',
    'capabilities',
    'machine_file',
    'role_refusal',
    'role_tables',
    'template',
]

#: The resource a developer workstation provides: the live checkout and the agent tooling its guards run on.
WORKSTATION: Final = 'workstation'

#: HEAVY COMPUTE: every tool with a presence probe (:data:`lab_commons.compute.toolchecks.CHECKS`) -- a vendor
#: solver and its licence seat. Derived, so a newly probed tool is heavy without an edit here.
HEAVY: Final = tuple(sorted(CHECKS))


#: The images whose running count is the JMAG seats in use: ONE per solve. The solver kernel family as the
#: installation ships it (a downstream JMAG adapter, checked 2026-09-19 against
#: JMAG-Designer25.1). Not ``execsolver.exe`` -- it launches ``jam.exe``, so counting both counts one solve
#: twice -- and not ``scheduler.exe`` or ``designer.exe``: a seat is a SOLVE, never an open Designer (user
#: correction 2026-10-16).
JMAG_SOLVER_IMAGES: Final = ('jam.exe', 'jam_c.exe', 'jam_intel_mpi_b.exe', 'jam_intel_mpi_c.exe')


@dataclass(frozen=True)
class Role:
    """A declared workstation profile: what a deploy with ``--role`` writes into the machine file."""

    capabilities: tuple[str, ...]  # declared unless --capabilities names a subset
    parts: str  # [serve] parts
    withhold: tuple[str, ...]  # [serve] withhold: never this host's forge work, part or request


#: THE ONE PLACE a workstation role is declared. ``light`` (user ruling 2026-10-28, WS1 and WS2): it serves forge
#: parts and requests but never heavy compute -- every probed tool is withheld, because a probe finds an installed
#: JMAG whether or not it is declared, and a heavy capability is refused at deploy.
ROLES: Final = {'light': Role(capabilities=(WORKSTATION,), parts=EVERY, withhold=HEAVY)}


def capabilities(text: str) -> dict[str, dict[str, Any]]:
    """``--capabilities`` *text* (``name`` or ``name:seats``, comma-separated) as machine-file rows.

    A ``jmag`` row also counts its seats in use by :data:`JMAG_SOLVER_IMAGES`.
    """
    out: dict[str, dict[str, Any]] = {}
    for item in filter(None, (part.strip() for part in text.split(','))):
        name, _, seats = item.partition(':')
        if seats and not seats.isdigit():
            msg = f'--capabilities {item!r}: expected <name> or <name>:<seats>'
            raise argparse.ArgumentTypeError(msg)
        out[name] = {'seats': int(seats)} if seats else {}
        if name == 'jmag':
            out[name]['in_use'] = {'process': list(JMAG_SOLVER_IMAGES)}
    try:
        return provided(out)
    except ValueError as bad:
        raise argparse.ArgumentTypeError(str(bad)) from None


def role_tables(role: Role, capabilities: Mapping[str, Mapping[str, Any]], repos: Sequence[str]) -> dict[str, Any]:
    """The machine-file tables a *role* deploy owns: its capabilities and its ``[serve]`` rule over *repos*."""
    tables: dict[str, Any] = {f'capabilities.{name}': dict(facts) for name, facts in capabilities.items()}
    tables[SERVE_TABLE] = {'repos': list(repos), 'parts': role.parts, 'withhold': list(role.withhold)}
    return tables


def role_refusal(role: str, capabilities: Mapping[str, Any]) -> str | None:
    """Why *capabilities* break *role*'s profile: a heavy capability declared on a host that withholds it."""
    if heavy := sorted(set(capabilities) & set(ROLES[role].withhold)):
        return f'the {role} role runs no heavy compute: drop {", ".join(heavy)} from --capabilities'
    return None


def template(role: str, repos: Sequence[str]) -> str:
    """The machine-file tables ``deploy --role <role> --repos <repos>`` writes, as TOML: the docs' template."""
    return merged('', role_tables(ROLES[role], capabilities(','.join(ROLES[role].capabilities)), repos))


def _retirements(text: str) -> dict[str, Any]:
    """Every RETIRED ``[capabilities.<name>]`` in machine-file *text*, dropped; one retired into a runtime, moved.

    No alias survives a deploy (:data:`lab_commons.hpc.retired.RETIRED`): the table goes, and when its remedy is
    ``[runtimes.<name>]`` its keys (where that runtime lives) are carried there, since only this host knows them.
    """
    try:
        declared = tomllib.loads(text).get('capabilities', {})
    except tomllib.TOMLDecodeError:
        return {}  # the merge refuses the file by name
    out: dict[str, Any] = {}
    for name, facts in declared.items():
        remedy = RETIRED.get(f'capabilities.{name}')
        if remedy is None:
            continue
        out[f'capabilities.{name}'] = None
        if remedy.startswith(f'[{RUNTIMES_TABLE}.{name}]') and isinstance(facts, dict) and facts:
            out[f'{RUNTIMES_TABLE}.{name}'] = dict(facts)
    return out


def machine_file(step: Step, tables: Mapping[str, Mapping[str, Any]]) -> int:
    """Merge *tables* into this host's machine file (retirements first); 0 done or unchanged, 2 refused."""
    path = config_path()
    emit(f'[machine file] {path}')
    before = path.read_text(encoding='utf-8') if path.is_file() else ''
    try:
        after = merged(before, {**_retirements(before), **tables})
    except ValueError as broken:
        emit(f'deploy refused: {path}: {broken}', err=True)
        return 2
    if after == before:
        emit('  already declares every table')
        return 0
    for line in diff(before, after, str(path)).splitlines():
        emit(f'  {line}')
    if step.dry:
        emit('  [dry-run] the diff above is not written')
        return 0
    durable_text(path, after)
    return 0
