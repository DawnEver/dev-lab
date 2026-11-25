"""BREAK-GLASS, SERVER SIDE: merge PRs past the forge's protection inside a wave the user consented to.

User rulings 2026-11-03: a local agent session may run it, only under the user's authorization. Since 2026-11-07 that
authorization is a ``breakglass.wave`` CONSENT CREDENTIAL (:mod:`dev_lab.ops.consent`) the user granted with their
cluster code at the issuer: it opens a WAVE (:mod:`dev_lab.ops.wave`) bounded by its signed params; merges
inside it need none, and this server -- never the client -- sends the wave's summary through the configuration's
``[alerts]`` when it ends.
The client is ``forge pr breakglass`` / ``forge breakglass open|close|ack|status``
(:mod:`dev_lab.dev.forgebreakglass`); the transport is the restricted account's ssh ForceCommand,
whose key authorizes nothing by itself.

EVERY FORGE OF THE FAMILY (user ruling 2026-11-04). Each served repo is reached on ITS forge -- Gitea or GitHub, the
backend its URL's host selects (:mod:`dev_lab.ops.breakglassforge`, over :mod:`dev_lab.dev.forgework`) -- as that
forge's ONE break-glass identity (``[ops.breakglass.tokens]``). The repo's integration branch is read from its
declaration on the forge (:func:`dev_lab.dev.reviewgate.manifest_at` at the PR's BASE branch, the one the merge
lands on -- never the default branch, which may be a data commit that declares nothing), so a repo this host never
clones is served as well as one it promotes. The identity must be able to bypass the branch's protection:
on GitHub a user the ruleset lists as a bypass actor
(or a repository admin where classic protection does not enforce on administrators);
on Gitea an account the protection's merge whitelist admits, or an admin.

One request is one JSON line with an ``action``:

* ``open {credential}`` -- audited, never alerted (the user granted the credential); refused while a wave is open
  (never because an earlier audit is unacknowledged). The credential's params ``hours`` and ``max_merges`` may be
  anything up to ``wave_ceiling`` / ``max_merges_max`` (``0`` = no ceiling) -- above a ceiling it is REFUSED naming
  it, never clamped, and before its use is registered, so it is not spent. Then it verifies offline and its ONE use
  is registered with the issuer (:func:`dev_lab.ops.consent.client.redeem`): an issuer that cannot be reached refuses;
* ``merge {repo, pr, head, reason}`` (``repo`` is ``<host>/<owner>/<name>``) -- refused outside an open wave, past
  the cap, for a repo not in
  ``[ops.breakglass] repos``, a short reason, a declaration the forge cannot serve, a PR not open, not into the repo's
  declared integration branch, whose head is not the one shown, or that carries the ``hold`` label (user ruling
  D48, 2026-11-17: refused naming ``forge pr release <N>``, :mod:`dev_lab.dev.forgehold`) -- NEVER for its tests
  (user ruling 2026-11-11: the wave waives them too): unrun, pending or red, it merges, and its test state at
  merge time (:func:`tests_at`) is
  named in the comment, the audit line and the wave's summary. A red naming a failure subject the base's same red
  does not (:mod:`dev_lab.dev.failprint`, finding D13) is admitted ON RECORD too (user ruling D18, 2026-11-17): the
  new subjects join that test state by name; then comment, merge at that
  head with a
  ``Break-Glass: <reason>`` trailer (so :func:`dev_lab.dev.breakglass.notices` opens the follow-up issue every use
  owes), audit ``(repo, pr, head, reason)`` under the id of the consent credential that opened the wave -- the
  wave's one grant has no subject, so each use is tied to it here; the merge that reaches the cap ends the wave;
* ``promote {repo, sha, reason}`` -- the user's EMERGENCY trunk move (``integrate promote <sha> --breakglass``):
  refused outside an open wave, for a repository not served, a short reason, a sha off the integration branch or a
  trunk it does not fast-forward; else a NON-FORCED push of the trunk by the break-glass identity (the trunk
  ruleset's ``always`` bypass actor), counted as one of the wave's merges and audited with the parts state read
  then. Nothing is posted: no passing status is ever fabricated;
* ``close`` -- end the open wave; ``ack {id?, by}`` -- record who acknowledged an audit (the oldest unacknowledged
  when no id), no code;
* ``status`` -- every wave's state; :meth:`Server.tick` (a timer) ends an expired wave and resends a summary no
  channel delivered.

ALERTS (user rulings 2026-11-04, "one final acceptance is enough"): a wave sends ONE alert -- its summary (id, the
opening key, the window, every merge with its full head and reason) when it ENDS, and only if it merged; opening, each
merge and an empty wave are audited only, and nothing reminds. Delivery is recorded on the wave (``summarized``), so
the summary goes once however often the tick runs. Refusals, failures and a lockout still alert: they are no merge.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from lab_commons.log import emit

from dev_lab.dev.breakglass import BREAK_GLASS
from dev_lab.dev.forgefailure import ForgeCallFailed
from dev_lab.dev.forgehold import HOLD_LABEL, RELEASE_DOOR, is_held
from dev_lab.dev.forgemerge import hidden_reds
from dev_lab.dev.forgemergewaits import green_waits
from dev_lab.dev.forgestatus import CommitStatus
from dev_lab.dev.lanepolicy import policy_from
from dev_lab.dev.roles import TESTS, roles_of_url
from dev_lab.ops import request as requests
from dev_lab.ops import wave as waves
from dev_lab.ops.breakglassforge import Forge, NotFastForward
from dev_lab.ops.config import Breakglass, OpsConfig
from dev_lab.ops.configcheck import LABEL
from dev_lab.ops.consent.client import Register, redeem
from dev_lab.ops.consent.credential import ConsentRefused
from dev_lab.ops.statelock import exclusive
from dev_lab.ops.wavesweep import integration_at, sweep

__all__ = ['BreakglassRefused', 'ConsentWanted', 'Held', 'HeldBack', 'Server', 'merge_message']

_HOUR = 3600.0


class BreakglassRefused(RuntimeError):
    """The request was refused; the message is what the client prints."""


class HeldBack(BreakglassRefused):
    """A label holds the PR back (or its labels cannot be read); the sweep skips it, logged once per wave."""


class ConsentWanted(HeldBack):
    """The PR touches a boundary key (or its labels cannot be read): it lands only by its own consent."""


class Held(HeldBack):
    """The PR carries the hold label (:mod:`dev_lab.dev.forgehold`): it lands only once released."""


def _labels_admit(forge: Forge, pr: int) -> None:
    """Refuse PR *pr* while it carries :data:`LABEL` or the hold label, or when its labels cannot be read."""
    try:
        carried = forge.labels(pr)
    except (ForgeCallFailed, KeyError, TypeError, ValueError) as unread:
        msg = f'#{pr} labels cannot be read, so it may touch a boundary key: {str(unread).splitlines()[0]}'
        raise ConsentWanted(msg) from unread
    if LABEL in carried:
        msg = f'#{pr} is labeled {LABEL}: it touches a boundary key and lands only by its own consent'
        raise ConsentWanted(msg)
    if is_held(carried):  # D48: break-glass honors the hold, as the merge tick does
        msg = f'#{pr} is held (label `{HOLD_LABEL}`): release it with `{RELEASE_DOOR.format(n=pr)}` first'
        raise Held(msg)


def tests_at(posted: Sequence[CommitStatus], head: str, *, tests: str) -> str:
    """*head*'s test state at merge time: ``passed``, ``red: <contexts>; <why>`` or ``untested: <why>``.

    User ruling 2026-11-11: break-glass waives the tests as well as the review -- the open wave is the authorization
    -- so this never refuses; it names what was waived, for the audit and the notice. The reading is merge-ready's
    own, by the repo's *producer* (:func:`dev_lab.dev.forgemergewaits.green_waits`).
    """
    waits = green_waits(head, posted, tests=tests)
    if not waits:
        return 'passed'
    latest = {one.context: one.state for one in reversed(posted)}  # newest first: the newest write wins
    red = [ctx for ctx, state in latest.items() if state in {'failure', 'error'} and ctx.startswith('tests/')]
    return f'red: {", ".join(red)}; {"; ".join(waits)}' if red else f'untested: {"; ".join(waits)}'


def _merged(tests: str) -> str:
    """How a merge names its test state: ``merged``, ``merged red (<contexts>)`` or ``merged untested``."""
    if tests.startswith('red: '):
        return f'merged red ({tests.removeprefix("red: ").split("; ")[0]})'
    return 'merged' if tests == 'passed' else 'merged untested'


def merge_message(pr: int, integration: str, reason: str, wave: str) -> str:
    """The merge commit's message: what it is, then the ``Break-Glass`` trailer the history keeps."""
    return f'chore(merge): break-glass #{pr} into {integration} (wave {wave})\n\n{BREAK_GLASS}: {reason}\n'


def _granted(credential: dict[str, Any], role: Breakglass) -> tuple[float, int]:
    """The window and merge cap the credential's params carry, refused outside the role's ceilings."""
    params = credential.get('params')
    if not isinstance(params, dict) or set(params) != {'hours', 'max_merges'}:
        msg = 'the credential carries no breakglass.wave params (hours, max_merges)'
        raise BreakglassRefused(msg)
    hours, cap = params['hours'], params['max_merges']
    if isinstance(hours, bool) or not isinstance(hours, int | float) or not 0 < hours * 3600 <= role.wave_ceiling:
        msg = f'{hours!r} h is outside the ceiling (0, wave_ceiling = {role.wave_ceiling / 3600:g} h]'
        raise BreakglassRefused(msg)
    ceiling = role.max_merges_max or None
    if isinstance(cap, bool) or not isinstance(cap, int) or cap < 0 or (ceiling and not 0 < cap <= ceiling):
        msg = f'{cap!r} merge(s) is outside the ceiling max_merges_max = {role.max_merges_max}'
        raise BreakglassRefused(msg)
    return float(hours), cap


@dataclass
class Server:
    """The role over one configuration; *forge_for* builds the forge of a repo URL, *alert* sends ``(title, body)``.

    Every request and every tick runs under the role's one exclusive lock (:mod:`dev_lab.ops.statelock`), so the
    waves are read and written by one session at a time. *consent_key* verifies a ``breakglass.wave`` credential and
    *register* records its one use with the issuer (:mod:`dev_lab.ops.consent`).
    """

    config: OpsConfig
    forge_for: Callable[[str], Forge]
    #: Sends ``(title, body)``; returns whether ANY channel delivered it.
    alert: Callable[[str, str], bool]
    now: Callable[[], float]
    consent_key: Ed25519PublicKey
    register: Register
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
        self._send(title, body)

    def _send(self, title: str, body: str) -> bool:
        """Alert; whether any channel delivered. A failure is audited, never fatal."""
        try:
            delivered = self.alert(title, body)
        except (OSError, ValueError, RuntimeError) as failed:  # a channel failure is recorded, never fatal
            self._audit({'outcome': f'alert failed: {type(failed).__name__}: {failed}', 'title': title})
            return False
        if not delivered:
            self._audit({'outcome': 'alert failed: no channel delivered', 'title': title})
        return delivered

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
        self._audit({'wave': held.id, 'outcome': 'closed', 'merges': len(held.merges)})
        self._summarize(held)
        return text

    def _summarize(self, held: waves.Wave) -> None:
        """Send an ended wave's ONE summary, unless one was delivered or it merged nothing (then it is logged only)."""
        if not held.merges or held.summarized is not None:
            return
        if self._send(f'break-glass wave {held.id} ended: AUDIT AND ACKNOWLEDGE', waves.report(self.state, held)):
            held.summarized = self.now()
            waves.save(self.state, held)
            self._audit({'wave': held.id, 'outcome': 'summarized'})

    def handle(self, line: str) -> str:
        """Parse, then judge and perform one request under the role lock.

        Refusals (a malformed request included) are audited, alerted and raised as :class:`BreakglassRefused`; an
        internal failure is audited and alerted too, and re-raised as itself -- never relabeled.
        """
        try:
            parsed = requests.parse(line)
        except requests.Malformed as bad:
            refused = BreakglassRefused(f'malformed request: {bad}')
            self._announce({'action': '?', 'outcome': f'refused: {refused}'}, 'break-glass REFUSED', str(refused))
            raise refused from bad
        verbs: dict[str, Callable[[Any], str]] = {
            'open': self._open, 'merge': self._merge, 'promote': self._promote, 'close': self._close_verb,
            'ack': self._ack, 'status': self._status,
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
        hours, cap = _granted(asked.credential, self.role)  # before the use is registered: a refusal spends nothing
        try:
            granted = redeem(asked.credential, action='breakglass.wave', subject=None, key=self.consent_key,
                             register=self.register, now=self.now())  # fmt: skip
        except ConsentRefused as refused:
            raise BreakglassRefused(str(refused)) from refused
        now = self.now()
        stamp = datetime.fromtimestamp(now, UTC).strftime('%Y%m%dT%H%M%SZ')
        opened = waves.Wave(stamp, now, now + hours * _HOUR, cap, key=self.key, consent=granted.id)
        waves.save(self.state, opened)
        said = f'wave {opened.id} open for {hours:g} h' + (f', at most {cap} merge(s)' if cap else '')
        self._audit({'wave': opened.id, 'outcome': 'opened', 'hours': hours, 'max_merges': cap,
                     'consent': granted.id})  # fmt: skip
        return said

    def _merge(self, asked: requests.Merge) -> str:
        if (held := self._current()) is None:
            msg = 'no break-glass wave is open: the user opens one (forge breakglass open, with their code)'
            raise BreakglassRefused(msg)
        repo, pr, head, reason = asked.repo, asked.pr, asked.head, asked.reason
        forge, integration = self._admit(asked)
        hidden = hidden_reds(forge.fingerprints, head, integration, posted := forge.statuses(head))
        by = roles_of_url(self.role.repo(repo) or repo).kind(TESTS)
        tests = tests_at(posted, head, tests=by) + (f'; {hidden}' if hidden else '')  # D18: on record
        forge.comment(pr, f'BREAK-GLASS merge (wave {held.id}) of {head[:12]} into {integration}, '
                          f'{_merged(tests)}. Reason: {reason}. Tests: {tests}')  # fmt: skip
        forge.merge(pr, head=head, message=merge_message(pr, integration, reason, held.id))
        held.merges.append(waves.Merge(repo, pr, head, reason, self.now(), self.key, tests))
        waves.save(self.state, held)
        said = f'{_merged(tests)} {repo}#{pr} at {head[:12]} into {integration} (wave {held.id})'
        self._audit({'wave': held.id, 'outcome': 'merged', 'consent': held.consent, 'repo': repo, 'pr': pr,
                     'head': head, 'reason': reason, 'tests': tests})  # fmt: skip
        if held.full():
            self._close(held)
            said += f'; the cap of {held.max_merges} ended the wave'
        return said

    def _promote(self, asked: requests.Promote) -> str:
        """Fast-forward a served repository's trunk to an integration commit past its parts, inside the open wave.

        The trunk and integration branch are the ones the promoted commit declares. The push is non-forced, by the
        break-glass identity (the trunk ruleset's bypass actor); nothing is posted to the forge, so no passing status
        is fabricated -- the parts state read now is the audit's record.
        """
        if (held := self._current()) is None:
            msg = 'no break-glass wave is open: the user opens one (forge breakglass open, with their code)'
            raise BreakglassRefused(msg)
        url = self.role.repo(asked.repo)
        if url is None:
            msg = f'{asked.repo} is not a repository this host serves'
            raise BreakglassRefused(msg)
        if len(asked.reason) < self.role.min_reason:
            msg = f'a reason of at least {self.role.min_reason} characters is required'
            raise BreakglassRefused(msg)
        forge = self.forge_for(url)
        try:
            policy = policy_from(forge.declaration(asked.sha), f'{asked.repo}@{asked.sha[:12]}:pyproject.toml')
        except ValueError as unread:
            raise BreakglassRefused(str(unread)) from unread
        parts = tests_at(forge.statuses(asked.sha), asked.sha, tests=roles_of_url(url).kind(TESTS))
        try:
            old = forge.fast_forward(policy.trunk, policy.integration, asked.sha)
        except NotFastForward as refused:
            raise BreakglassRefused(str(refused)) from refused
        held.merges.append(waves.Merge(asked.repo, 0, asked.sha, asked.reason, self.now(), self.key, parts,
                                       policy.trunk))  # fmt: skip
        waves.save(self.state, held)
        said = f'promoted {asked.repo} {policy.trunk} {old[:12]} -> {asked.sha[:12]} (wave {held.id}); parts: {parts}'
        self._audit({'wave': held.id, 'outcome': 'promoted', 'consent': held.consent, 'repo': asked.repo,
                     'trunk': policy.trunk, 'from': old, 'sha': asked.sha, 'reason': asked.reason,
                     'parts': parts})  # fmt: skip
        if held.full():
            self._close(held)
            said += f'; the cap of {held.max_merges} ended the wave'
        return said

    def _admit(self, asked: requests.Merge) -> tuple[Forge, str]:
        url = self.role.repo(asked.repo)
        if url is None:
            msg = f'{asked.repo} is not a repository this host serves'
            raise BreakglassRefused(msg)
        if len(asked.reason) < self.role.min_reason:
            msg = f'a reason of at least {self.role.min_reason} characters is required'
            raise BreakglassRefused(msg)
        forge = self.forge_for(url)
        state, base, found = forge.pull(asked.pr)
        if state != 'open':
            msg = f'#{asked.pr} is {state}, not open'
            raise BreakglassRefused(msg)
        try:
            integration = integration_at(forge, base, asked.repo)
        except ValueError as unread:
            raise BreakglassRefused(str(unread)) from unread
        if base != integration:
            msg = f'#{asked.pr} targets {base}, not the integration branch {integration}'
            raise BreakglassRefused(msg)
        if found != asked.head:
            msg = f'#{asked.pr} head is {found[:12]}, not the {asked.head[:12]} you were shown: re-run the verb'
            raise BreakglassRefused(msg)
        _labels_admit(forge, asked.pr)
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
        """The timer's step, under the role lock: land what is green, end an expired wave, resend unsent summaries.

        An open wave lands each green, non-draft PR it serves (:mod:`dev_lab.ops.wavesweep`) through :meth:`_merge`.
        """
        with exclusive(self.state):
            landed = sweep(self.role.repos, self.forge_for, wave=self._open_id, land=self._sweep_land,
                           refused=BreakglassRefused)  # fmt: skip
            for wave in waves.held(self.state):
                if wave.closed is not None:
                    self._summarize(wave)
            return '\n'.join([*landed, self._status(None)])

    def _sweep_land(self, asked: requests.Merge) -> str | None:
        """:meth:`_merge` for the sweep; a PR a label holds back (consent, hold) is ``None``, logged once per wave."""
        try:
            return self._merge(asked)
        except HeldBack as wanted:
            held = self._current()
            if held is not None and (seen := f'{asked.repo}#{asked.pr}') not in held.held_back:
                held.held_back.append(seen)
                waves.save(self.state, held)
                emit(f'[breakglass] wave {held.id}: {seen} skipped: {wanted}', err=True)
                self._audit({'wave': held.id, 'outcome': f'skipped: {wanted}', 'repo': asked.repo, 'pr': asked.pr})
            return None

    def _open_id(self) -> str | None:
        held = self._current()
        return None if held is None else held.id
