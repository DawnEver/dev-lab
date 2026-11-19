"""The host's STATUS CARD: one small JSON each supervise cycle publishes, so a host is read without ssh.

User ruling 2026-11-13: debugging a forge host must not need the user's one-time code, and nothing a host's
supervisor measured was readable without an ssh login. So a cycle that is handed ``--card <file>`` rewrites this card
after every cycle; the ops door (``[ops.status]``, :mod:`dev_lab.ops.caddy`) serves that file read-only behind the
host's existing allowlist, and ``python -m dev_lab.dev.opsserver <server|all> card`` reads and renders it.

What it says, first things first: the cycle's ``status``; each enabled component ``up`` or ``down`` (down: an anomaly
of this cycle came from it); the supervisor's own memory against its cgroup cap; every metric the checks reported
(disk free, RAM, a queue depth a probe declares); the last error with its time -- kept across quiet cycles, redacted
(:func:`dev_lab.supervise.report.redact`); the installed dev-lab sha; the last auto-upgrade audit line.

A CARD NOBODY REWRITES SAYS "UP" FOREVER, so it carries its own ``interval_s`` and the reader judges it
:func:`is_stale` past :data:`STALE_CYCLES` intervals -- the same multiple the unit's watchdog allows.
"""

from __future__ import annotations

import importlib.metadata
import json
import os
import tempfile
from collections.abc import Mapping, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any, Final

from dev_lab.supervise.loop import CycleResult
from dev_lab.supervise.report import redact

__all__ = [
    'SCHEMA',
    'STALE_CYCLES',
    'card',
    'installed_sha',
    'is_stale',
    'last_audit',
    'own_memory',
    'read',
    'render',
    'write',
]

#: The card's shape. A reader refuses any other (a format migrates once, never upgrades on read).
SCHEMA: Final = 1

#: Past this many intervals without a rewrite, a card is stale: its supervisor is not cycling.
STALE_CYCLES: Final = 3

_MB: Final = 2**20
_DISTRIBUTION: Final = 'dev-lab'
_PROC_CGROUP: Final = Path('/proc/self/cgroup')
_CGROUP_MOUNT: Final = Path('/sys/fs/cgroup')


def card(
    result: CycleResult,
    at: datetime,
    *,
    components: Sequence[str],
    interval_s: int,
    previous: Mapping[str, Any] | None = None,
    installed: str = '',
    upgrade: Mapping[str, Any] | None = None,
    memory: Mapping[str, float | None] | None = None,
) -> dict[str, Any]:
    """The card of one cycle: *result* at *at*, the enabled *components*, and the host facts beside it.

    *previous* is the card this one replaces: its ``last_error`` survives a cycle that found nothing.
    """
    down = {anomaly.source.split('.', 1)[0] for anomaly in result.anomalies}
    last_error = (previous or {}).get('last_error')
    if result.anomalies:
        first = result.anomalies[0]
        last_error = {'at': at.isoformat(), 'source': first.source, 'message': redact(first.message)}
    return {
        'schema': SCHEMA,
        'at': at.isoformat(),
        'interval_s': interval_s,
        'status': result.status,
        'components': {name: 'down' if name in down else 'up' for name in components},
        'memory': dict(memory) if memory is not None else None,
        'metrics': dict(sorted(result.metrics.items())),
        'last_error': last_error,
        'dev_lab': installed,
        'upgrade': dict(upgrade) if upgrade is not None else None,
    }


def write(path: Path, found: Mapping[str, Any]) -> None:
    """Publish *found* at *path* whole (a staged file renamed over it), mode 0644 for the web server to read."""
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, staged = tempfile.mkstemp(prefix='.card-', dir=path.parent)
    try:
        with os.fdopen(handle, 'w', encoding='utf-8') as out:
            json.dump(found, out, indent=1)
        Path(staged).chmod(0o644)
        Path(staged).replace(path)
    except BaseException:
        Path(staged).unlink(missing_ok=True)
        raise


def read(path: Path) -> dict[str, Any] | None:
    """The card at *path*, or None when there is none yet or it does not parse (the next cycle rewrites it)."""
    try:
        found = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None
    return found if isinstance(found, dict) else None


def installed_sha() -> str:
    """The installed dev-lab's vcs commit (its ``direct_url.json``), else its version, else ``uninstalled``."""
    try:
        dist = importlib.metadata.distribution(_DISTRIBUTION)
    except importlib.metadata.PackageNotFoundError:
        return 'uninstalled'
    try:
        commit = json.loads(dist.read_text('direct_url.json') or '{}').get('vcs_info', {}).get('commit_id', '')
    except ValueError:
        commit = ''
    return str(commit or dist.version)


def last_audit(path: Path) -> dict[str, Any] | None:
    """The last line of the auto-upgrade audit (``upgrade-follow/audit.jsonl``), or None when there is none."""
    try:
        lines = [line for line in path.read_text(encoding='utf-8').splitlines() if line.strip()]
    except OSError:
        return None
    try:
        found = json.loads(lines[-1]) if lines else None
    except ValueError:
        return {'unparsed': lines[-1][:200]}
    return found if isinstance(found, dict) else None


def own_memory(proc: Path = _PROC_CGROUP, mount: Path = _CGROUP_MOUNT) -> dict[str, float | None] | None:
    """The running process's cgroup ``memory.current`` and ``memory.max`` in MB (max None: no cap); None off v2."""
    try:
        line = next(line for line in proc.read_text(encoding='utf-8').splitlines() if line.startswith('0::'))
        group = mount / line.removeprefix('0::').strip().lstrip('/')
        current = int((group / 'memory.current').read_text(encoding='utf-8'))
        cap = (group / 'memory.max').read_text(encoding='utf-8').strip()
    except (OSError, StopIteration, ValueError):
        return None
    return {'current_mb': round(current / _MB, 1), 'max_mb': None if cap == 'max' else round(int(cap) / _MB, 1)}


def is_stale(found: Mapping[str, Any], now: datetime) -> bool:
    """Whether *found* is older than :data:`STALE_CYCLES` of its own intervals at *now*."""
    age = (now - datetime.fromisoformat(str(found['at']))).total_seconds()
    return age > STALE_CYCLES * int(found['interval_s'])


def render(name: str, found: Mapping[str, Any], now: datetime) -> str:
    """The card of server *name* as a few lines a reader takes in at once; refuse anything not a card.

    Raises:
        ValueError: *found* is not a card of :data:`SCHEMA`.

    """
    if found.get('schema') != SCHEMA or 'at' not in found or 'interval_s' not in found:
        msg = f'{name}: not a status card of schema {SCHEMA} (keys {sorted(found)})'
        raise ValueError(msg)
    age = int((now - datetime.fromisoformat(str(found['at']))).total_seconds())
    stale = f' -- STALE: no cycle for over {STALE_CYCLES} intervals' if is_stale(found, now) else ''
    lines = [f'{name}: {found["status"]} at {found["at"]} ({age} s ago){stale}']
    components = found.get('components') or {}
    down = sorted(component for component, state in components.items() if state == 'down')
    up = sorted(component for component, state in components.items() if state != 'down')
    lines.append(f'  down: {", ".join(down)}' if down else '  down: none')
    lines.append(f'  up: {", ".join(up) or "none"}')
    if memory := found.get('memory'):
        cap = f'{memory["max_mb"]} MB' if memory.get('max_mb') is not None else 'no cap'
        lines.append(f'  memory: {memory["current_mb"]} MB of {cap}')
    if metrics := found.get('metrics'):
        lines.append('  metrics: ' + ' '.join(f'{key}={value:g}' for key, value in metrics.items()))
    if error := found.get('last_error'):
        lines.append(f'  last error: {error["at"]} {error["source"]}: {error["message"]}')
    lines.append(f'  dev-lab: {found.get("dev_lab") or "unknown"}')
    if upgrade := found.get('upgrade'):
        lines.append(f'  last upgrade: {json.dumps(upgrade, sort_keys=True)}')
    return '\n'.join(lines)
