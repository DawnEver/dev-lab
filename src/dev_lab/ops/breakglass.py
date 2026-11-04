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
from dev_lab.ops import request as requests
from dev_lab.ops import wave as waves
from dev_lab.ops.clones import CloneUnusable, declared
from dev_lab.ops.config import Breakglass, OpsConfig
from dev_lab.ops.lockout import guarded
from dev_lab.ops.statelock import exclusive
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


def _cap(asked: int | None, declared_cap: int) -> int:
    """The tighter of two merge caps, ``0`` meaning none."""
    given = [cap for cap in (asked or 0, declared_cap) if cap > 0]
    return min(given) if given else 0


@dataclass
class Server:
    """The role over one configuration; *forge_for* builds the forge of a clone, *alert* sends ``(title, body)``.

    Every request and every tick runs under the role's one exclusive lock (:mod:`dev_lab.ops.statelock`), so the
    TOTP step, the lockout count and the waves are each read and written by one session at a time.
    """

    config: OpsConfig
    forge_for: Callable[[Path], Forge]
    alert: Callable[[str, str], None]
    now: Callable[[], float]
    #: The fingerprint of the ssh key this session authenticated with (:mod:`dev_lab.ops.sshkey`), ``''`` unknown.
    key: str = ''

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
            stamp = datetime.now(UTC).isoformat(timespec='seconds')
            out.write(json.dumps({'at': stamp, 'key': self.key, **line}) + '\n')

    def _announce(self, line: dict[str, Any], title: str, body: str) -> None:
        """Audit *line* FIRST, then alert; a failed alert is audited and never aborts the request."""
        self._audit(line)
        try:
            self.alert(title, body)
        except (OSError, ValueError, RuntimeError) as failed:  # a channel failure is recorded, never fatal
            self._audit({'outcome': f'alert failed: {type(failed).__name__}: {failed}', 'title': title})

    def _code(self, code: str) -> None:
        def check() -> None:
            try:
                accept(Path(self.role.totp), self.state / 'totp.step', code, self.now())
            except TotpRefused as refused:
                raise BreakglassRefused(str(refused)) from refused

        def locked(until: float) -> None:
            when = datetime.fromtimestamp(until, UTC).isoformat(timespec='seconds')
            body = f'{self.role.lockout_after} wrong codes; every code refused until {when}'
            self._announce({'outcome': 'locked out', 'until': when}, 'break-glass LOCKED OUT', body)

        guarded(self.state, check, now=self.now(), after=self.role.lockout_after, minutes=self.role.lockout_minutes,
                on_lock=locked, refused=BreakglassRefused)  # fmt: skip

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
        line = {'wave': held.id, 'outcome': 'closed', 'merges': len(held.merges)}
        self._announce(line, f'break-glass wave {held.id} closed: AUDIT AND ACKNOWLEDGE', text)
        return text

    def handle(self, line: str) -> str:
        """Parse, then judge and perform one request under the role lock.

        Refusals (a malformed request included) are audited, alerted and raised as :class:`BreakglassRefused`; an
        internal failure is audited and alerted too, and re-raised as itself -- never relabelled.
        """
        try:
            parsed = requests.parse(line)
        except requests.Malformed as bad:
            refused = BreakglassRefused(f'malformed request: {bad}')
            self._announce({'action': '?', 'outcome': f'refused: {refused}'}, 'break-glass REFUSED', str(refused))
            raise refused from bad
        verbs: dict[str, Callable[[Any], str]] = {
            'open': self._open, 'merge': self._merge, 'close': self._close_verb, 'ack': self._ack,
            'status': self._status,
        }  # fmt: skip
        try:
            with exclusive(self.state):
                return verbs[parsed.action](parsed.fields)
        except BreakglassRefused as refused:
            line_ = {'action': parsed.action, 'outcome': f'refused: {refused}'}
            self._announce(line_, f'break-glass {parsed.action} REFUSED', str(refused))
            raise
        except Exception as failed:
            line_ = {'action': parsed.action, 'outcome': f'failed: {type(failed).__name__}: {failed}'}
            self._announce(line_, f'break-glass {parsed.action} FAILED', f'{type(failed).__name__}: {failed}')
            raise

    def _open(self, asked: requests.Open) -> str:
        if (held := self._current()) is not None:
            msg = f'wave {held.id} is open: use it, or close it first'
            raise BreakglassRefused(msg)
        self._code(asked.code)
        hours = min(asked.hours or self.role.wave_hours, self.role.wave_hours)
        cap = _cap(asked.max_merges, self.role.max_merges)
        now = self.now()
        stamp = datetime.fromtimestamp(now, UTC).strftime('%Y%m%dT%H%M%SZ')
        opened = waves.Wave(stamp, now, now + hours * _HOUR, cap)
        waves.save(self.state, opened)
        said = f'wave {opened.id} open for {hours:g} h' + (f', at most {cap} merge(s)' if cap else '')
        line = {'wave': opened.id, 'outcome': 'opened', 'hours': hours, 'max_merges': cap}
        self._announce(line, f'break-glass wave {opened.id} OPENED', said)
        return said

    def _merge(self, asked: requests.Merge) -> str:
        held = self._current()
        if held is None:
            msg = 'no break-glass wave is open: the user opens one (forge breakglass open, with their code)'
            raise BreakglassRefused(msg)
        if held.full():
            msg = f'wave {held.id} reached its cap of {held.max_merges} merge(s)'
            raise BreakglassRefused(msg)
        repo, pr, head, reason = asked.repo, asked.pr, asked.head, asked.reason
        forge, integration = self._admit(asked)
        forge.comment(pr, f'BREAK-GLASS merge (wave {held.id}) of {head[:12]} into {integration}. Reason: {reason}')
        forge.merge(pr, head=head, message=merge_message(pr, integration, reason, held.id))
        held.merges.append(waves.Merge(repo, pr, head, reason, self.now(), self.key))
        waves.save(self.state, held)
        said = f'merged {repo}#{pr} at {head[:12]} into {integration} (wave {held.id})'
        line = {'wave': held.id, 'outcome': 'merged', 'repo': repo, 'pr': pr, 'head': head, 'reason': reason}
        body = f'{said}, head {head}, key {self.key or "unknown"}: {reason}'
        self._announce(line, f'break-glass MERGED {repo}#{pr}', body)
        return said

    def _admit(self, asked: requests.Merge) -> tuple[Forge, str]:
        url = self.config.repo(asked.repo)
        if url is None:
            msg = f'{asked.repo} is not a repository this host serves'
            raise BreakglassRefused(msg)
        if len(asked.reason) < self.role.min_reason:
            msg = f'a reason of at least {self.role.min_reason} characters is required'
            raise BreakglassRefused(msg)
        try:
            root, policy = declared(self.config, url)
        except CloneUnusable as unusable:
            raise BreakglassRefused(str(unusable)) from unusable
        integration = policy.integration
        forge = self.forge_for(root)
        state, base, found = forge.pull(asked.pr)
        if state != 'open':
            msg = f'#{asked.pr} is {state}, not open'
            raise BreakglassRefused(msg)
        if base != integration:
            msg = f'#{asked.pr} targets {base}, not the integration branch {integration}'
            raise BreakglassRefused(msg)
        if found != asked.head:
            msg = f'#{asked.pr} head is {found[:12]}, not the {asked.head[:12]} you were shown: re-run the verb'
            raise BreakglassRefused(msg)
        return forge, integration

    def _close_verb(self, _asked: None) -> str:
        held = self._current()
        return self._status(None) if held is None else self._close(held)

    def _ack(self, asked: requests.Ack) -> str:
        self._current()
        waiting = [wave for wave in waves.held(self.state) if wave.state(self.now()) == 'audit']
        found = next((wave for wave in waiting if wave.id == asked.id or not asked.id), None)
        if found is None:
            msg = f'no wave {asked.id} awaits acknowledgement' if asked.id else 'no wave awaits acknowledgement'
            raise BreakglassRefused(msg)
        found.acked, found.acked_by = self.now(), asked.by
        waves.save(self.state, found)
        self._audit({'wave': found.id, 'outcome': 'acknowledged', 'by': found.acked_by})
        return f'wave {found.id} acknowledged by {found.acked_by}'

    def _status(self, _asked: None) -> str:
        self._current()
        listed = [f'wave {w.id}: {w.state(self.now())}, {len(w.merges)} merge(s)' for w in waves.held(self.state)]
        return '\n'.join(listed) or 'no wave'

    def tick(self) -> str:
        """The timer's step, under the role lock: close an expired wave; remind each unacknowledged audit."""
        with exclusive(self.state):
            self._current()
            for wave in waves.held(self.state):
                due = (wave.reminded or wave.closed or 0.0) + self.role.remind_hours * _HOUR
                if wave.state(self.now()) == 'audit' and self.now() >= due:
                    wave.reminded = self.now()
                    waves.save(self.state, wave)
                    line = {'wave': wave.id, 'outcome': 'reminded'}
                    title = f'break-glass wave {wave.id} awaits acknowledgement'
                    self._announce(line, title, waves.report(self.state, wave))
            return self._status(None)
