"""BREAK-GLASS, SERVER SIDE: merge PRs past the forge's protection inside a wave the user opened with a TOTP code.

User rulings 2026-11-03: a local agent session may run it, only under the user's authorization; no certificates, no
second device -- the authorization is the user's Authenticator code, whose secret only this host holds
(:mod:`dev_lab.ops.totp`). A code opens a WAVE (:mod:`dev_lab.ops.wave`); merges inside it need none, and this
server -- never the client -- announces each one through the configuration's ``[alerts]``. The client is
``forge pr breakglass`` / ``forge breakglass open|close|ack|status`` (:mod:`dev_lab.dev.forgebreakglass`); the
transport is the restricted account's ssh ForceCommand, whose key authorizes nothing by itself.

One request is one JSON line with an ``action``:

* ``open {code, hours?, max_merges?}`` -- refused while a wave is open (never because an earlier audit is
  unacknowledged); ``hours`` may only shorten the configured ``wave_hours``, ``max_merges`` only tighten its cap;
* ``merge {repo, pr, head, reason}`` -- refused outside an open wave, past the cap, for an unconfigured repo, a short
  reason, a PR not open, not into the repo's declared integration branch, or whose head is not the one shown; then
  comment, merge at that head with a ``Break-Glass: <reason>`` trailer (so :func:`dev_lab.dev.breakglass.notices`
  opens the follow-up issue every use owes), announce;
* ``close`` -- close the open wave: write and send its audit report; ``ack {id?, by}`` -- record who acknowledged
  an audit (the oldest unacknowledged when no id), no code;
* ``status`` -- every wave's state; :meth:`Server.tick` (a timer) closes an expired wave and reminds an
  unacknowledged audit at most once per ``remind_hours``.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from dev_lab.dev.breakglass import BREAK_GLASS
from dev_lab.dev.lanepolicy import policy_at
from dev_lab.ops import wave as waves
from dev_lab.ops.config import Breakglass, OpsConfig
from dev_lab.ops.promote import DECLARED_AT
from dev_lab.ops.totp import TotpRefused, accept

__all__ = ['BreakglassRefused', 'Forge', 'Server', 'merge_message']

_HOUR = 3600.0


class BreakglassRefused(RuntimeError):
    """The request was refused; the message is what the client prints."""


class Forge(Protocol):
    """The three forge calls the role makes, on one repository, as the break-glass identity."""

    def pull(self, number: int) -> tuple[str, str, str]:
        """``(state, base, head_sha)`` of PR *number*."""
        ...

    def comment(self, number: int, body: str) -> None:
        """Comment on PR *number*."""
        ...

    def merge(self, number: int, *, head: str, message: str) -> None:
        """Merge PR *number* at *head* with a merge commit saying *message*."""
        ...


def merge_message(pr: int, integration: str, reason: str, wave: str) -> str:
    """The merge commit's message: what it is, then the ``Break-Glass`` trailer the history keeps."""
    return f'chore(merge): break-glass #{pr} into {integration} (wave {wave})\n\n{BREAK_GLASS}: {reason}\n'


def _cap(asked: int, declared: int) -> int:
    """The tighter of two merge caps, ``0`` meaning none."""
    given = [cap for cap in (asked, declared) if cap > 0]
    return min(given) if given else 0


@dataclass
class Server:
    """The role over one configuration; *forge_for* builds the forge of a clone, *alert* sends ``(title, body)``."""

    config: OpsConfig
    forge_for: Callable[[Path], Forge]
    alert: Callable[[str, str], None]
    now: Callable[[], float]

    @property
    def role(self) -> Breakglass:
        """The ``[ops.breakglass]`` table; refused when the config does not enable it."""
        if self.config.breakglass is None:
            msg = f'{self.config.path} enables no [ops.breakglass]'
            raise BreakglassRefused(msg)
        return self.config.breakglass

    @property
    def state(self) -> Path:
        """The role's state directory."""
        return Path(self.role.state)

    def _audit(self, line: dict[str, Any]) -> None:
        log = Path(self.role.log)
        log.parent.mkdir(parents=True, exist_ok=True)
        with log.open('a', encoding='utf-8') as out:
            out.write(json.dumps({'at': datetime.now(UTC).isoformat(timespec='seconds'), **line}) + '\n')

    def _code(self, code: str) -> None:
        try:
            accept(Path(self.role.totp), self.state / 'totp.step', code, self.now())
        except TotpRefused as refused:
            raise BreakglassRefused(str(refused)) from refused

    def _current(self) -> waves.Wave | None:
        """The open wave, else ``None``; an expired one is closed first (so it is never merged into)."""
        for wave in waves.held(self.state):
            if wave.state(self.now()) == 'expired':
                self._close(wave)
            elif wave.state(self.now()) == 'open':
                return wave
        return None

    def _close(self, held: waves.Wave) -> str:
        held.closed = min(self.now(), held.expires)
        waves.save(self.state, held)
        text = waves.report(self.state, held)
        self.alert(f'break-glass wave {held.id} closed: AUDIT AND ACKNOWLEDGE', text)
        self._audit({'wave': held.id, 'outcome': 'closed', 'merges': len(held.merges)})
        return text

    def handle(self, line: str) -> str:
        """Judge and perform one request; every refusal is audited and alerted, then raised."""
        verbs = {'open': self._open, 'merge': self._merge, 'close': self._close_verb, 'ack': self._ack,
                 'status': self._status}  # fmt: skip
        try:
            request = json.loads(line)
            action = request['action']
            verb = verbs[action]
        except (ValueError, KeyError, TypeError) as bad:
            msg = f'malformed request ({type(bad).__name__}); one JSON line with action {"|".join(verbs)}'
            raise BreakglassRefused(msg) from bad
        try:
            return verb(request)
        except (KeyError, ValueError, TypeError) as bad:
            msg = f'malformed {action} request ({type(bad).__name__}: {bad})'
            raise BreakglassRefused(msg) from bad
        except BreakglassRefused as refused:
            self._audit({'action': action, 'outcome': f'refused: {refused}', 'pr': request.get('pr')})
            self.alert(f'break-glass {action} REFUSED', str(refused))
            raise

    def _open(self, request: dict[str, Any]) -> str:
        if (held := self._current()) is not None:
            msg = f'wave {held.id} is open: use it, or close it first'
            raise BreakglassRefused(msg)
        self._code(str(request.get('code', '')))
        hours = min(float(request.get('hours') or self.role.wave_hours), self.role.wave_hours)
        cap = _cap(int(request.get('max_merges') or 0), self.role.max_merges)
        now = self.now()
        stamp = datetime.fromtimestamp(now, UTC).strftime('%Y%m%dT%H%M%SZ')
        opened = waves.Wave(stamp, now, now + hours * _HOUR, cap)
        waves.save(self.state, opened)
        said = f'wave {opened.id} open for {hours:g} h' + (f', at most {cap} merge(s)' if cap else '')
        self.alert(f'break-glass wave {opened.id} OPENED', said)
        self._audit({'wave': opened.id, 'outcome': 'opened', 'hours': hours, 'max_merges': cap})
        return said

    def _merge(self, request: dict[str, Any]) -> str:
        held = self._current()
        if held is None:
            msg = 'no break-glass wave is open: the user opens one (forge breakglass open, with their code)'
            raise BreakglassRefused(msg)
        if held.full():
            msg = f'wave {held.id} reached its cap of {held.max_merges} merge(s)'
            raise BreakglassRefused(msg)
        repo, pr, head = str(request['repo']), int(request['pr']), str(request['head'])
        reason = str(request['reason']).strip()
        forge, integration = self._admit(repo, pr, head, reason)
        forge.comment(pr, f'BREAK-GLASS merge (wave {held.id}) of {head[:12]} into {integration}. Reason: {reason}')
        forge.merge(pr, head=head, message=merge_message(pr, integration, reason, held.id))
        held.merges.append(waves.Merge(repo, pr, head, reason, self.now()))
        waves.save(self.state, held)
        said = f'merged {repo}#{pr} at {head[:12]} into {integration} (wave {held.id})'
        self.alert(f'break-glass MERGED {repo}#{pr}', f'{said}, head {head}: {reason}')
        self._audit({'wave': held.id, 'outcome': 'merged', 'repo': repo, 'pr': pr, 'head': head, 'reason': reason})
        return said

    def _admit(self, repo: str, pr: int, head: str, reason: str) -> tuple[Forge, str]:
        url = self.config.repo(repo)
        if url is None:
            msg = f'{repo} is not a repository this host serves'
            raise BreakglassRefused(msg)
        if len(reason) < self.role.min_reason:
            msg = f'a reason of at least {self.role.min_reason} characters is required'
            raise BreakglassRefused(msg)
        root = self.config.checkout(url)
        integration = policy_at(root, DECLARED_AT).integration
        forge = self.forge_for(root)
        state, base, found = forge.pull(pr)
        if state != 'open':
            msg = f'#{pr} is {state}, not open'
            raise BreakglassRefused(msg)
        if base != integration:
            msg = f'#{pr} targets {base}, not the integration branch {integration}'
            raise BreakglassRefused(msg)
        if found != head:
            msg = f'#{pr} head is {found[:12]}, not the {head[:12]} you were shown: re-run the verb'
            raise BreakglassRefused(msg)
        return forge, integration

    def _close_verb(self, request: dict[str, Any]) -> str:
        held = self._current()
        return self._status(request) if held is None else self._close(held)

    def _ack(self, request: dict[str, Any]) -> str:
        self._current()
        waiting = [wave for wave in waves.held(self.state) if wave.state(self.now()) == 'audit']
        wanted = str(request.get('id') or '')
        found = next((wave for wave in waiting if wave.id == wanted or not wanted), None)
        if found is None:
            msg = f'no wave {wanted} awaits acknowledgement' if wanted else 'no wave awaits acknowledgement'
            raise BreakglassRefused(msg)
        found.acked, found.acked_by = self.now(), str(request.get('by') or 'unnamed')
        waves.save(self.state, found)
        self._audit({'wave': found.id, 'outcome': 'acknowledged', 'by': found.acked_by})
        return f'wave {found.id} acknowledged by {found.acked_by}'

    def _status(self, _request: dict[str, Any]) -> str:
        self._current()
        listed = [f'wave {w.id}: {w.state(self.now())}, {len(w.merges)} merge(s)' for w in waves.held(self.state)]
        return '\n'.join(listed) or 'no wave'

    def tick(self) -> str:
        """The timer's step: close an expired wave; remind each unacknowledged audit once per ``remind_hours``."""
        self._current()
        for wave in waves.held(self.state):
            due = (wave.reminded or wave.closed or 0.0) + self.role.remind_hours * _HOUR
            if wave.state(self.now()) == 'audit' and self.now() >= due:
                wave.reminded = self.now()
                waves.save(self.state, wave)
                self.alert(f'break-glass wave {wave.id} awaits acknowledgement', waves.report(self.state, wave))
        return self._status({})
