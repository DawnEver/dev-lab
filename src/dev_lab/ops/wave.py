"""A BREAK-GLASS WAVE: the window one TOTP code opens, and the audit report it leaves behind.

User rulings 2026-11-03: the user works in waves, and a single code relayed by an agent is not bound to the PR the
human saw. So a code OPENS a wave (bounded by a duration and, optionally, a merge cap); merges inside it need no
code. When the wave ENDS -- ``close``, its merge cap reached, or expiry -- one report of every merge is written, and
it is the wave's ONE alert, sent only if the wave merged something (user rulings 2026-11-04: no alert per merge, none
for opening or an empty wave, no reminder). ``summarized`` records that a channel delivered it, so it is sent once.
Acknowledging it is a plain recorded acknowledgement (who, when), needs no code and NEVER blocks the next wave.

Each wave is ``<state>/waves/<id>.json`` with its report beside it as ``<id>.md``; at most one is open.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

__all__ = ['Merge', 'Wave', 'held', 'report', 'save']


def _iso(at: float) -> str:
    return datetime.fromtimestamp(at, UTC).isoformat(timespec='seconds')


@dataclass(frozen=True)
class Merge:
    """One merge the wave made."""

    repo: str
    pr: int
    head: str
    reason: str
    at: float
    #: The fingerprint of the ssh key that asked for it (:mod:`dev_lab.ops.sshkey`).
    key: str = ''


@dataclass
class Wave:
    """One wave; ``closed`` / ``acked`` / ``summarized`` are times, ``None`` while not yet; ``key`` opened it."""

    id: str
    opened: float
    expires: float
    max_merges: int
    merges: list[Merge] = field(default_factory=list)
    closed: float | None = None
    acked: float | None = None
    acked_by: str = ''
    summarized: float | None = None
    #: The fingerprint of the ssh key that opened it (:mod:`dev_lab.ops.sshkey`).
    key: str = ''
    #: ``<repo>#<pr>`` of each PR the sweep held back for its own consent, so each is logged once per wave.
    held_back: list[str] = field(default_factory=list)

    def state(self, now: float) -> str:
        """``open``, ``expired`` (closing is due), ``audit`` (closed, unacknowledged) or ``acknowledged``."""
        if self.closed is None:
            return 'open' if now < self.expires else 'expired'
        return 'audit' if self.acked is None else 'acknowledged'

    def full(self) -> bool:
        """Whether the merge cap (``0`` = none) is reached."""
        return bool(self.max_merges) and len(self.merges) >= self.max_merges


def _dir(state: Path) -> Path:
    return state / 'waves'


def held(state: Path) -> list[Wave]:
    """Every wave under *state*, oldest first."""
    found = []
    for path in sorted(_dir(state).glob('*.json')):
        data: dict[str, Any] = json.loads(path.read_text(encoding='utf-8'))
        data['merges'] = [Merge(**merge) for merge in data.get('merges', [])]
        if 'reminded' in data:  # OLD-SHAPE-READER: that format alerted on close, so a closed wave was summarized
            del data['reminded']
            data['summarized'] = data.get('closed')
        found.append(Wave(**data))
    return found


def save(state: Path, wave: Wave) -> None:
    """Write *wave* atomically under *state*."""
    _dir(state).mkdir(parents=True, exist_ok=True)
    target = _dir(state) / f'{wave.id}.json'
    partial = target.with_suffix('.partial')
    partial.write_text(json.dumps(asdict(wave), indent=1), encoding='utf-8')
    partial.replace(target)


def report(state: Path, wave: Wave) -> str:
    """The wave's audit report (Markdown), kept as ``<state>/waves/<id>.md``; returns its text."""
    lines = [
        f'# Break-glass wave {wave.id}',
        '',
        f'- opened {_iso(wave.opened)} by key {wave.key or "unknown"}, ended {_iso(wave.closed or wave.expires)}, '
        f'{len(wave.merges)} merge(s)' + ('' if wave.merges else ': no merge'),
        '',
        *(f'- {_iso(m.at)} {m.repo}#{m.pr} at {m.head} by key {m.key or "unknown"}: {m.reason}' for m in wave.merges),
        '',
        f'Acknowledge: `python -m dev_lab.dev.forge breakglass ack {wave.id}`.',
    ]
    text = '\n'.join(lines) + '\n'
    _dir(state).mkdir(parents=True, exist_ok=True)
    (_dir(state) / f'{wave.id}.md').write_text(text, encoding='utf-8')
    return text
