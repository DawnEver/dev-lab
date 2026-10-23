"""REPO-AUTOMODE: a repo's ``.claude/automode.json`` -- the prose its Claude Code auto-mode classifier reads.

Claude Code reads ``autoMode`` only from user, managed or ``--settings`` files; the user's launcher passes a
trusted repo's ``.claude/automode.json`` through ``--settings``. So each consuming repo carries one,
GENERATED here, never hand-written: ``{"autoMode": {"environment": [...], "allow": [...]}}``, each array
opening with ``"$defaults"`` so the client's own defaults stay in force.

PROSE, NEVER SPELLINGS. The classifier judges INTENT; the exact command a door takes is the narrow
``permissions.allow`` row :mod:`dev_lab.dev.autodoors` renders. A command or module spelled here would be a
second, unchecked allow list (:func:`spelled_commands` refuses one).

SINGLE SOURCES, and what is NOT rendered:

* the source-control remote: this checkout's ``origin`` (:func:`dev_lab.dev.forge.forge_from_remote`) and its
  declared branch set (trunk, long-lived branches);
* the forge serve fleet and the cluster accounts are MACHINE-LOCAL -- the synced workstation registry named by
  the machine file's ``[workstation] registry`` and the machine file's ``[[hpc.grant]]`` tables. A tracked file
  rendered from them would differ per machine, so the file names those SOURCES and lists no host;
* the action categories: :data:`INTENTS`, one per door or rule the kit holds, and :data:`OPTIONAL_INTENTS`,
  rendered only for a repo that names one in ``[tool.lab_commons.automode] declares``.

``python -m dev_lab.dev.autodoors --write`` writes it beside the Codex rules; without ``--write`` a stale file
exits 1.
"""

from __future__ import annotations

import json
import re
import tomllib
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Final

from dev_lab.dev.branchset import BranchSetNotDeclared, declared_branchset
from dev_lab.dev.forge import UnreadableRemote, forge_from_remote

__all__ = [
    'AUTOMODE_REL',
    'DEFAULTS',
    'INTENTS',
    'OPTIONAL_INTENTS',
    'automode',
    'check',
    'render',
    'spelled_commands',
    'write',
]

#: Where the launcher finds a repo's auto-mode prose.
AUTOMODE_REL: Final = '.claude/automode.json'

#: Keeps the client's built-in entries in force; the first entry of every array.
DEFAULTS: Final = '$defaults'

#: The toolchain facts true of every consuming repo; the repo's own remote is added by :func:`automode`.
_ENVIRONMENT: Final = (
    (
        "The family development kit (dev-lab) is installed in each checkout's own virtual environment; its checked "
        'doors are the sanctioned way to run privileged development operations, and each re-checks its safety '
        'bound at the moment it acts.'
    ),
    (
        'The forge serve fleet is the set of workstations listed in the synced workstation registry (hosts.json, '
        'whose path the local machine file declares under its workstation table; an entry with the forge role serves) '
        'plus the university HPC cluster accounts declared in that machine file as cluster grants, each reached '
        'by key-based ssh at its declared login hosts. Both lists are machine-local, so they are named here by '
        'source rather than copied.'
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
        'Deploying or restarting the forge serve hosts of the declared fleet: the workstation scheduled task '
        'and each declared cluster account, over ssh, detached, one log per account.'
    ),
    'cancel-stuck': (
        "Cancelling the forge's own test jobs of one commit that are confirmed stuck: busy at full CPU with no "
        'new result for longer than their bound. Never any other job.'
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


def automode(root: Path) -> dict[str, Any]:
    """The ``autoMode`` settings object for the checkout at *root*."""
    allow = [*INTENTS.values(), *(OPTIONAL_INTENTS[name] for name in _declared(root))]
    environment = [_source_control(root), *_ENVIRONMENT]
    return {'autoMode': {'environment': [DEFAULTS, *environment], 'allow': [DEFAULTS, *allow]}}


def render(root: Path) -> str:
    """:func:`automode` as the file's text."""
    return json.dumps(automode(root), indent=2) + '\n'


def check(root: Path) -> bool:
    """Whether the tracked file equals a fresh render."""
    target = root / AUTOMODE_REL
    return target.is_file() and target.read_text(encoding='utf-8') == render(root)


def write(root: Path) -> None:
    """Write the fresh render."""
    target = root / AUTOMODE_REL
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(render(root), encoding='utf-8', newline='\n')
