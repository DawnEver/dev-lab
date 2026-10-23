"""REPO-AUTOMODE: a repo's ``.claude/automode.json`` -- the prose its Claude Code auto-mode classifier reads.

Claude Code reads ``autoMode`` only from user, managed or ``--settings`` files; the user's launcher passes a
trusted repo's ``.claude/automode.json`` through ``--settings``. So each consuming repo carries one,
GENERATED here, never hand-written: ``{"autoMode": {"environment": [...], "allow": [...]}}``, each array
opening with ``"$defaults"`` so the client's own defaults stay in force.

PROSE, NEVER SPELLINGS. The classifier judges INTENT; the exact command a door takes is the narrow
``permissions.allow`` row :mod:`dev_lab.dev.autodoors` renders. A command or module spelled here would be a
second, unchecked allow list (:func:`spelled_commands` refuses one).

SINGLE SOURCES:

* the source-control remote: this checkout's ``origin`` (:func:`dev_lab.dev.forge.forge_from_remote`) and its
  declared branch set (trunk, long-lived branches);
* the trusted hosts, by NAME so the classifier recognises them (:func:`read_fleet`): every workstation of the
  synced workstation registry (``hosts.json``, named by the machine file's ``[workstation] registry``) with its
  computer name, address and roles, and every cluster account of the machine file's ``[[hpc.grant]]`` tables
  with its login hosts;
* the action categories: :data:`INTENTS`, one per door or rule the kit holds, and :data:`OPTIONAL_INTENTS`,
  rendered only for a repo that names one in ``[tool.lab_commons.automode] declares``.

THE COMMITTED FILE IS A DERIVED ARTEFACT OF MACHINE-LOCAL SOURCES. ``python -m dev_lab.dev.autodoors --write``
writes it beside the Codex rules, and refuses when a source is unreadable. Without ``--write`` the drift check
re-renders it: a stale file exits 1, and where a source cannot be read (a cluster login node holds no
``hosts.json``) :class:`SourcesUnavailable` is raised -- INCONCLUSIVE, naming the source, never a pass (the
rule :exc:`~dev_lab.dev.famtests.latestversions.FetchUnavailable` states for an unanswered fetch).
"""

from __future__ import annotations

import json
import re
import tomllib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from lab_commons.config import config_path, section
from lab_commons.hpc.grants import Grant, load_grants

from dev_lab.dev.branchset import BranchSetNotDeclared, declared_branchset
from dev_lab.dev.forge import UnreadableRemote, forge_from_remote
from dev_lab.dev.workstation import FORGE_ROLE, REGISTRY_TABLE

__all__ = [
    'AUTOMODE_REL',
    'DEFAULTS',
    'INTENTS',
    'OPTIONAL_INTENTS',
    'Fleet',
    'SourcesUnavailable',
    'automode',
    'check',
    'read_fleet',
    'render',
    'spelled_commands',
    'write',
]

#: Where the launcher finds a repo's auto-mode prose.
AUTOMODE_REL: Final = '.claude/automode.json'

#: Keeps the client's built-in entries in force; the first entry of every array.
DEFAULTS: Final = '$defaults'

#: The toolchain facts true of every consuming repo; the remote and the hosts are added by :func:`automode`.
_ENVIRONMENT: Final = (
    (
        "The family development kit (dev-lab) is installed in each checkout's own virtual environment; its checked "
        'doors are the sanctioned way to run privileged development operations, and each re-checks its safety '
        'bound at the moment it acts.'
    ),
    (
        'Test verdicts are produced once per commit by the forge serve hosts and posted as commit statuses; a '
        'session reads them rather than running the full gate itself.'
    ),
)

#: THE ACTION CATEGORIES an agent may take unattended, keyed by the door or rule that bounds each one.
INTENTS: Final[dict[str, str]] = {
    'break-glass': (
        'A Break-Glass merge into the integration branch when the forge cannot merge a pull request, carried '
        'by a commit trailer that states the reason, so every use stays in the history it bypassed.'
    ),
    'close-landed': 'Closing pull requests whose head is already merged into their base branch.',
    'close-superseded': (
        'Closing an open pull request whose content was salvaged into another open pull request, with a '
        'comment naming the replacement, then deleting its branch only if that loses no commit.'
    ),
    'lossless-prune': (
        'Deleting a remote branch only when every commit on it is already on the integration branch or on '
        'another live branch or open pull request; never a force push and never a lossy delete.'
    ),
    'install-hooks': 'Installing or refreshing the kit git hooks in a checkout of this repository.',
    'deploy-fleet': (
        'Deploying or restarting the forge serve hosts of the trusted fleet: the workstation scheduled task '
        'and each trusted cluster account on its own declared login host, over ssh, detached, one log per account.'
    ),
    'cancel-stuck': (
        "Cancelling the forge's own test jobs of one commit that are confirmed stuck: busy at full CPU with no "
        'new test result for longer than a multiple of their measured duration. Never any other job.'
    ),
    'monitor': 'Read-only monitoring of the forge: commit statuses, the queue, host cards and run progress.',
}

#: Categories a repo must DECLARE before they render (``[tool.lab_commons.automode] declares``).
OPTIONAL_INTENTS: Final[dict[str, str]] = {
    'jmag-material-card': (
        'Installing a missing JMAG material card into the local JMAG material library, the one write outside '
        'the checkout this repository authorizes standing.'
    ),
}

#: What a command or module spelling looks like; prose carries none.
_SPELLED: Final = re.compile(r'`|\bpython\b|\s-m\s|\s--?[a-z]|\bdev_lab\b|\blab_commons\b|\.py\b|\bssh\s+\S+@')


class SourcesUnavailable(RuntimeError):
    """A machine-local source of the fleet could not be read, so the render cannot be judged. INCONCLUSIVE.

    Not a stale file and not a current one: a check that read it as either would report a fleet it never read.
    """


@dataclass(frozen=True)
class Fleet:
    """The trusted hosts: the registry's workstation entries and the machine file's cluster grants."""

    workstations: tuple[Mapping[str, Any], ...]
    grants: tuple[Grant, ...]


def read_fleet() -> Fleet:
    """The fleet from its two machine-local sources; :class:`SourcesUnavailable` naming the one that did not read."""
    registry = section(REGISTRY_TABLE).get('registry')
    if not isinstance(registry, str) or not registry:
        msg = f'no [{REGISTRY_TABLE}] registry in {config_path()}: the workstation registry is unreadable here'
        raise SourcesUnavailable(msg)
    try:
        hosts = json.loads(Path(registry).expanduser().read_text(encoding='utf-8-sig'))['hosts']
        grants = load_grants().grants
    except (OSError, ValueError, KeyError, TypeError) as bad:
        msg = f'the fleet sources did not read ({registry}, {config_path()}): {bad}'
        raise SourcesUnavailable(msg) from None
    return Fleet(tuple(hosts), tuple(grants))


def spelled_commands(entries: Sequence[str]) -> tuple[str, ...]:
    """The *entries* that spell a command or module rather than state an intent -- must be empty."""
    return tuple(entry for entry in entries if _SPELLED.search(entry))


def _declared(root: Path) -> tuple[str, ...]:
    manifest = root / 'pyproject.toml'
    data = tomllib.loads(manifest.read_text(encoding='utf-8')) if manifest.is_file() else {}
    names = tuple(data.get('tool', {}).get('lab_commons', {}).get('automode', {}).get('declares', ()))
    if unknown := sorted(set(names) - set(OPTIONAL_INTENTS)):
        msg = f'{manifest}: [tool.lab_commons.automode] declares {unknown}; known: {sorted(OPTIONAL_INTENTS)}'
        raise ValueError(msg)
    return names


def _source_control(root: Path) -> str:
    try:
        forge = forge_from_remote(root)
    except UnreadableRemote:
        said = 'Source control: this checkout has no forge origin'
    else:
        said = f'Source control: this repository origin is {forge.owner}/{forge.repo} on the Gitea forge {forge.host}'
    try:
        branches = declared_branchset(root)
    except BranchSetNotDeclared:
        return said + '.'
    others = ', '.join(sorted(branches.sessions))
    return said + f'; its trunk is {branches.trunk} and its long-lived branches are {others}.'


def _workstation(entry: Mapping[str, Any]) -> str:
    facts = [f'computer {entry["computer"]}'] if entry.get('computer') else []
    facts += [f'address {entry["address"]}'] if entry.get('address') else []
    roles = list(entry.get('roles') or [])
    if roles:
        facts.append(f'roles {", ".join(roles)}{", serves the forge" if FORGE_ROLE in roles else ""}')
    return f'{entry.get("name", "?")} ({"; ".join(facts)})'


def _fleet_lines(fleet: Fleet) -> list[str]:
    lines = []
    if fleet.workstations:
        names = ', '.join(_workstation(entry) for entry in fleet.workstations)
        lines.append(f'Trusted workstations of this team (the synced workstation registry): {names}.')
    accounts: dict[str, Grant] = {}
    for grant in fleet.grants:
        accounts.setdefault(grant.user, grant)
    if accounts:
        listed = '; '.join(
            f'account {g.user} at login hosts {", ".join(g.hosts)} (Slurm account {g.slurm_account})'
            for g in accounts.values()
        )
        lines.append(f'Trusted university HPC cluster accounts of this team, reached by key-based ssh: {listed}.')
    return lines


def automode(root: Path, fleet: Fleet | None = None) -> dict[str, Any]:
    """The ``autoMode`` settings object for the checkout at *root* (*fleet*: :func:`read_fleet` when omitted)."""
    allow = [*INTENTS.values(), *(OPTIONAL_INTENTS[name] for name in _declared(root))]
    hosts = _fleet_lines(read_fleet() if fleet is None else fleet)
    environment = [_source_control(root), *hosts, *_ENVIRONMENT]
    return {'autoMode': {'environment': [DEFAULTS, *environment], 'allow': [DEFAULTS, *allow]}}


def render(root: Path, fleet: Fleet | None = None) -> str:
    """:func:`automode` as the file's text."""
    return json.dumps(automode(root, fleet), indent=2) + '\n'


def check(root: Path, fleet: Fleet | None = None) -> bool:
    """Whether the tracked file equals a fresh render; :class:`SourcesUnavailable` when that cannot be said."""
    fresh = render(root, fleet)
    target = root / AUTOMODE_REL
    return target.is_file() and target.read_text(encoding='utf-8') == fresh


def write(root: Path, fleet: Fleet | None = None) -> None:
    """Write the fresh render; :class:`SourcesUnavailable` (nothing written) when a source is unreadable."""
    text = render(root, fleet)
    target = root / AUTOMODE_REL
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding='utf-8', newline='\n')
