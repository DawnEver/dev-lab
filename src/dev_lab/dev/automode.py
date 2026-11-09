"""REPO-AUTOMODE: a repo's ``.claude/automode.json`` -- the prose its Claude Code auto-mode classifier reads.

Claude Code reads ``autoMode`` only from user, managed or ``--settings`` files; the user's launcher passes a
trusted repo's ``.claude/automode.json`` through ``--settings``. So each consuming repo carries one,
GENERATED here, never hand-written: ``{"autoMode": {"environment": [...], "allow": [...]}}``, each array
opening with ``"$defaults"`` so the client's own defaults stay in force.

PROSE, NEVER SPELLINGS. The classifier judges INTENT; the exact command a door takes is the narrow
``permissions.allow`` row :mod:`dev_lab.dev.autodoors` renders. A command or module spelled here would be a
second, unchecked allow list (:func:`spelled_commands` refuses one).

THE FILE IS MACHINE-LOCAL AND DERIVED, NEVER COMMITTED (user ruling 2026-10-23). Fleet facts -- account names,
login hosts, workstation names, internal addresses -- are shared through the synced ``hosts.json`` and the
machine file's ``[[hpc.grant]]``; a committed copy would be a second source and internal data in git history.
So the family ``.gitignore`` ignores it in every consumer, and it is rendered on each machine from:

* what the REPO declares, committed and host-free: :data:`INTENTS` (one per agent door of the policy table),
  its own ``[tool.dev_lab.policy] intents`` (prose, never a kit-held text), and its ``origin`` and branch set;
* what the MACHINE holds (:func:`read_fleet`): every workstation of the synced workstation registry
  (``hosts.json``, named by the machine file's ``[workstation] registry``) and every ``[[hpc.grant]]`` account
  with its login hosts, by NAME so the classifier recognises them.

It is rendered by the dependency door's bootstrap and sync (:mod:`dev_lab.dev.dep`) and by
``python -m dev_lab.dev.automode {write [--repo R] | session-start}`` (the latter reads a ``SessionStart`` hook
payload's ``cwd``). When a source is unreadable (a cluster login node holds no ``hosts.json``) NOTHING is
written and the reason is printed by name (:class:`SourcesUnavailable`) -- never a file missing its hosts.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import tomllib
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, TextIO

from lab_commons.config import config_path, section
from lab_commons.hpc.grants import Grant, load_grants
from lab_commons.log import emit

from dev_lab.dev.agentpolicy import POLICY, USER
from dev_lab.dev.branchset import BranchSetNotDeclared, declared_branchset
from dev_lab.dev.family import declared_table
from dev_lab.dev.forge import UnreadableRemote, forge_from_remote
from dev_lab.dev.workstationregistry import FORGE_ROLE, REGISTRY_TABLE

__all__ = [
    'AUTOMODE_REL',
    'DEFAULTS',
    'INTENTS',
    'POLICY_TABLE',
    'Fleet',
    'SourcesUnavailable',
    'automode',
    'leaks',
    'main',
    'read_fleet',
    'refresh',
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
#: The classifier's intents: every agent door's ONE string in :data:`dev_lab.dev.agentpolicy.POLICY`, in table order.
INTENTS: Final = tuple(dict.fromkeys(door.intent for door in POLICY if door.actor != USER))

#: Where a repo states its OWN standing intents, as prose: ``[tool.dev_lab.policy] intents``.
POLICY_TABLE: Final = 'policy'

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
    """The repo's own intents, ``[tool.dev_lab.policy] intents``; a retired ``[tool.dev_lab.automode]`` is refused."""
    manifest = root / 'pyproject.toml'
    data = tomllib.loads(manifest.read_text(encoding='utf-8')) if manifest.is_file() else {}
    if declared_table(data, 'automode', {}):
        msg = (
            f'{manifest}: [tool.dev_lab.automode] is retired -- state each standing intent as prose under '
            f'[tool.dev_lab.{POLICY_TABLE}] intents (user ruling 2026-11-07: a repo row lives in its own pyproject)'
        )
        raise ValueError(msg)
    intents = tuple(declared_table(data, POLICY_TABLE, {}).get('intents', ()))
    if spelled := spelled_commands(intents):
        msg = f'{manifest}: [tool.dev_lab.{POLICY_TABLE}] intents spell a command, not an intent: {list(spelled)}'
        raise ValueError(msg)
    return intents


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
    allow = [*INTENTS, *_declared(root)]
    hosts = _fleet_lines(read_fleet() if fleet is None else fleet)
    environment = [_source_control(root), *hosts, *_ENVIRONMENT]
    return {'autoMode': {'environment': [DEFAULTS, *environment], 'allow': [DEFAULTS, *allow]}}


def render(root: Path, fleet: Fleet | None = None) -> str:
    """:func:`automode` as the file's text."""
    return json.dumps(automode(root, fleet), indent=2) + '\n'


def write(root: Path, fleet: Fleet | None = None) -> None:
    """Write the fresh render; :class:`SourcesUnavailable` (nothing written) when a source is unreadable."""
    text = render(root, fleet)
    target = root / AUTOMODE_REL
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding='utf-8', newline='\n')


def refresh(root: Path, *, say: Callable[[str], None], fleet: Fleet | None = None) -> bool:
    """Render *root*'s local file, or print why not; never raises for an unreadable source. Whether it wrote.

    A declaration the render REFUSES (a retired table, a spelled command) also removes the file it would have
    replaced: a stale render keeps granting what the checkout no longer declares, and withholds what it does.
    """
    try:
        write(root, fleet)
    except SourcesUnavailable as unread:
        say(f'[automode] {AUTOMODE_REL} not written -- {unread}')
        return False
    except ValueError as refused:
        (root / AUTOMODE_REL).unlink(missing_ok=True)
        say(f'[automode] {AUTOMODE_REL} not written, and its stale copy removed -- {refused}')
        return False
    say(f'[automode] wrote {AUTOMODE_REL} (machine-local, gitignored)')
    return True


#: An IPv4 address or a dotted host name: the SHAPES a host takes, whichever fleet this machine holds.
_HOST_SHAPE: Final = re.compile(
    r'\b\d{1,3}(?:\.\d{1,3}){3}\b|\b[a-z0-9-]+(?:\.[a-z0-9-]+)*\.(?:ac\.uk|com|org|net|site)\b',
    re.IGNORECASE,
)


def leaks(texts: Sequence[str], fleet: Fleet | None = None) -> tuple[str, ...]:
    """The fleet facts *texts* (committed, kit or repo) carry -- must be empty.

    Any host SHAPE, plus every name *fleet* holds (workstation name, computer, address; account, login host)
    as a whole word. A committed copy of a fleet fact is the second source the ruling forbids.
    """
    names: set[str] = set()
    for entry in fleet.workstations if fleet else ():
        names |= {str(entry.get(key)) for key in ('name', 'computer', 'address') if entry.get(key)}
    for grant in fleet.grants if fleet else ():
        names |= {grant.user, *grant.hosts}
    found = {m.group(0) for text in texts for m in _HOST_SHAPE.finditer(text)}
    found |= {name for name in names for text in texts if re.search(rf'(?<![\w.-]){re.escape(name)}(?![\w-])', text)}
    return tuple(sorted(found))


def _root_of(cwd: Path) -> Path | None:
    for candidate in (cwd, *cwd.parents):
        if (candidate / '.git').exists():
            return candidate
    return None


def main(argv: Sequence[str] | None = None, *, stdin: TextIO | None = None) -> int:
    """``write [--repo R]`` renders the local file; ``session-start`` does so for a hook payload's ``cwd``.

    Always exit 0: an unreadable source is printed by name, and a session never fails to start over it.
    """
    args = list(sys.argv[1:] if argv is None else argv)
    if args[:1] == ['session-start']:
        try:
            payload = json.load(stdin or sys.stdin)
        except ValueError:
            payload = {}
        cwd = Path((payload if isinstance(payload, dict) else {}).get('cwd') or Path.cwd()).resolve()
        root = _root_of(cwd)
    elif args[:1] == ['write']:
        parser = argparse.ArgumentParser(prog='dev_lab.dev.automode write')
        parser.add_argument('--repo', type=Path, default=Path.cwd())
        repo = parser.parse_args(args[1:]).repo.resolve()
        root = _root_of(repo)
        if root is None:
            emit(f'automode write: {repo} is not inside a git checkout, so there is nothing to render', err=True)
            return 1
    else:
        emit('usage: python -m dev_lab.dev.automode {write [--repo R] | session-start}', err=True)
        return 2
    if root is not None:
        refresh(root, say=emit)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
